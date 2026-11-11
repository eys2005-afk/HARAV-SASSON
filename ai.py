"""קריאות ל-Gemini (REST): תמלול אודיו, סיכום + חילוץ מקורות, ואימות התאמה."""
import json
import mimetypes
import re
import time

import requests

from config import GEMINI_API_KEY, GEMINI_MODEL, INSECURE_SSL, OUTBOUND_PROXY

BASE = "https://generativelanguage.googleapis.com"


class AIError(RuntimeError):
    pass


def _session() -> requests.Session:
    if not GEMINI_API_KEY:
        raise AIError("לא הוגדר GEMINI_API_KEY (קובץ .env)")
    s = requests.Session()
    s.headers["x-goog-api-key"] = GEMINI_API_KEY
    if OUTBOUND_PROXY:
        s.proxies = {"http": OUTBOUND_PROXY, "https": OUTBOUND_PROXY}
    if INSECURE_SSL:
        s.verify = False
        import urllib3

        urllib3.disable_warnings()
    return s


def upload_audio(path: str) -> tuple[str, str]:
    """מעלה קובץ ל-Gemini Files API ומחכה שיהיה ACTIVE. מחזיר (uri, mime)."""
    s = _session()
    mime = mimetypes.guess_type(path)[0] or "audio/mpeg"
    size = __import__("os").path.getsize(path)
    r = s.post(
        f"{BASE}/upload/v1beta/files",
        headers={
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime,
            "Content-Type": "application/json",
        },
        json={"file": {"display_name": "lesson"}},
        timeout=60,
    )
    r.raise_for_status()
    url = r.headers["x-goog-upload-url"]
    with open(path, "rb") as f:
        r = s.post(
            url,
            headers={"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"},
            data=f,
            timeout=1800,
        )
    r.raise_for_status()
    info = r.json()["file"]
    for _ in range(120):
        if info.get("state") == "ACTIVE":
            return info["uri"], mime
        if info.get("state") == "FAILED":
            raise AIError("עיבוד הקובץ ב-Gemini נכשל")
        time.sleep(3)
        info = s.get(f"{BASE}/v1beta/{info['name']}", timeout=60).json()
    raise AIError("פג הזמן בהמתנה לעיבוד הקובץ ב-Gemini")


def _generate(parts: list, *, json_out=True, thinking=None, max_tokens=65536) -> str:
    cfg = {"temperature": 0.1, "maxOutputTokens": max_tokens}
    if json_out:
        cfg["responseMimeType"] = "application/json"
    if thinking is not None:
        cfg["thinkingConfig"] = {"thinkingBudget": thinking}
    s = _session()
    last = None
    for attempt in range(4):
        try:
            r = s.post(
                f"{BASE}/v1beta/models/{GEMINI_MODEL}:generateContent",
                json={"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg},
                timeout=900,
            )
            if r.status_code in (429, 500, 503):
                last = f"{r.status_code}"
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            cand = r.json()["candidates"][0]
            return "".join(p.get("text", "") for p in cand["content"]["parts"])
        except (requests.RequestException, KeyError) as e:
            last = repr(e)
            time.sleep(3)
    raise AIError(f"קריאה ל-Gemini נכשלה: {last}")


def _loads(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # פלט שנחתך (שיעור ארוך) — מצילים את האובייקטים התקינים
        dec, i, items = json.JSONDecoder(), text.find("{"), []
        while 0 <= i < len(text):
            try:
                obj, end = dec.raw_decode(text, i)
                items.append(obj)
                i = text.find("{", end)
            except json.JSONDecodeError:
                break
        return items


TRANSCRIBE_PROMPT = """תמלל במדויק את השיעור בקובץ האודיו. הדובר הוא רב שמעביר שיעור תורה בעברית; מילים רבות הן ארמית, לשון הקודש
וציטוטים מספרי קבלה והגות. כתוב כל מונח וציטוט באיות התקני (למשל: אוצרות הראי"ה, עץ חיים, שער הכוונות, תפארת).
אל תמציא ואל תשלים — אם קטע לא ברור כתוב [לא ברור]. חלק לפסקאות של כדקה, עם זמן התחלה.
החזר JSON בלבד: מערך של {"t": "MM:SS" (או "H:MM:SS"), "text": "..."}."""

ANALYZE_PROMPT = """להלן תמלול שיעור תורה. המטרה: לאתר את **המקורות שהרב מצטט או מפנה אליהם** כדי שנוכל לשלוף אותם מהספרים.
החזר JSON בלבד בצורה:
{"summary": "סיכום של 5-8 משפטים", "topics": ["נושא", ...],
 "citations": [{"quote": "...", "source_guess": "...", "kind": "library_book|tanach|talmud|other", "time": "MM:SS", "note": "..."}]}
כללים:
- quote: הניסוח של הציטוט/הרעיון המצוטט כפי שנאמר (עד כ-250 תווים), בלי להמציא.
- source_guess: הספר והמקום כפי שנאמר או משתמע (למשל "אורות הקודש ח"א", "שער הכוונות, דרוש הטלית"). ריק אם לא נאמר.
- kind: library_book אם המקור הוא אחד מספרי הספרייה שלהלן (או נראה כמוהם); tanach / talmud למקרא ולגמרא; other לשאר.
- time: זמן ההתחלה של הפסקה בתמלול שבה נאמר.
- כלול רק מקור שנאמר בפועל בשיעור; אל תוסיף מקורות מהידע שלך.
ספרי הספרייה: {books}
"""

RERANK_PROMPT = """הרב אמר בשיעור: «{quote}»
הוא רמז למקור: {guess}
להלן פסקאות מועמדות מהספרים. איזו מהן היא המקור שהרב ציטט או התכוון אליו? הדיבור בעל-פה לא מדויק — מספיקה התאמה בתוכן ובעיקר המילים.
{cands}
החזר JSON בלבד: {{"best": מספר המועמד או null אם אף אחד לא מתאים, "confidence": 0 עד 1, "reason": "משפט אחד"}}"""


def transcribe(path: str) -> list[dict]:
    uri, mime = upload_audio(path)
    out = _generate(
        [{"file_data": {"mime_type": mime, "file_uri": uri}}, {"text": TRANSCRIBE_PROMPT}], thinking=0
    )
    segs = _loads(out)
    segs = [s for s in segs if isinstance(s, dict) and s.get("text")]
    if not segs:
        raise AIError("התמלול חזר ריק")
    return [{"t": str(s.get("t", "")), "text": str(s["text"])} for s in segs]


def analyze(transcript: list[dict], book_titles: list[str]) -> dict:
    text = "\n".join(f"[{s['t']}] {s['text']}" for s in transcript)
    prompt = ANALYZE_PROMPT.replace("{books}", "; ".join(book_titles) or "(אין עדיין)")
    out = _loads(_generate([{"text": prompt + "\n\nתמלול:\n" + text}]))
    if not isinstance(out, dict):
        raise AIError("תשובת הניתוח לא בפורמט צפוי")
    return out


def rerank(quote: str, guess: str, candidates: list[dict]) -> dict:
    cands = "\n".join(f"[{i}] ({c['title']} — {c['ref']}) {c['text'][:700]}" for i, c in enumerate(candidates))
    out = _loads(_generate([{"text": RERANK_PROMPT.format(quote=quote, guess=guess or "לא צוין", cands=cands)}], thinking=0))
    return out if isinstance(out, dict) else {"best": None, "confidence": 0}
