"""עיבוד שיעור: תמלול -> סיכום וחילוץ מקורות -> התאמה לספרייה."""
import json
import shutil
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ai
import audio
import config
import library
from db import db

AUTO_OK = 0.6  # מעל זה — מוצג לציבור כמקור מאומת; מתחת — "לא בטוח" (למנהל בלבד)


def _set(lid: int, **kw):
    with db() as c:
        c.execute(f"update lessons set {', '.join(k + '=?' for k in kw)} where id=?", (*kw.values(), lid))


def transcribe_lesson(lid: int, lesson, titles: list[str]) -> list[dict]:
    """מפצל להקלטה ארוכה למקטעים, מתמלל במקביל (עם cache לכל מקטע, כדי ש'נסה שוב' ימשיך מאותה נקודה),
    ומחבר לתמלול אחד עם זמנים מוחלטים."""
    work = config.AUDIO_DIR / f"chunks_{lid}"
    _set(lid, progress="מפצל את ההקלטה…")
    chunks = audio.split(Path(lesson["audio_path"]), work, config.CHUNK_MINUTES * 60, config.CHUNK_OVERLAP)
    ctx = f"שם השיעור: {lesson['title']}. ספרים שייתכן שמצוטטים: {'; '.join(titles)[:1500]}"
    n = len(chunks)
    results: dict[int, list[dict]] = {}
    errors: list[str] = []

    def one(i: int):
        f, start = chunks[i]
        cache = work / f"c{i:03d}.json"
        if cache.exists():
            return i, json.loads(cache.read_text(encoding="utf-8"))
        segs = ai.transcribe(str(f), ctx)
        for s in segs:
            s["sec"] = audio.parse_ts(s["t"]) + start
        cache.write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")
        return i, segs

    done = 0
    with ThreadPoolExecutor(max(1, config.TRANSCRIBE_WORKERS)) as ex:
        futs = {ex.submit(one, i): i for i in range(n)}
        for fu in as_completed(futs):
            try:
                i, segs = fu.result()
                results[i] = segs
            except Exception as e:  # noqa: BLE001 — ממשיכים עם שאר המקטעים; מה שהושלם נשמר ב-cache
                errors.append(f"מקטע {futs[fu] + 1}: {e}")
            done += 1
            _set(lid, progress=f"תומלל מקטע {done} מתוך {n}")
    if errors:
        raise ai.AIError("; ".join(errors)[:400] + " — לחץ 'נסה שוב': מקטעים שהושלמו לא יתומללו מחדש")
    merged = audio.merge([results[i] for i in range(n)])
    shutil.rmtree(work, ignore_errors=True)
    return merged


def match_citations(lid: int):
    with db() as c:
        rows = c.execute(
            "select id,quote,source_guess,kind from citations where lesson_id=? and state!='approved'", (lid,)
        ).fetchall()
    for r in rows:
        if r["kind"] not in ("library_book", "other", "unknown"):
            continue
        cands = library.find(f"{r['quote']} {r['source_guess']}", attributed=r["source_guess"], limit=6)
        best, conf, state = None, 0.0, "none"
        if cands:
            try:
                v = ai.rerank(r["quote"], r["source_guess"], cands)
                i = v.get("best")
                if isinstance(i, int) and 0 <= i < len(cands):
                    best, conf = cands[i]["id"], float(v.get("confidence") or 0)
            except ai.AIError:
                best, conf = cands[0]["id"], cands[0]["score"] * 0.8  # בלי AI: ההתאמה הלקסיקלית
            state = "matched" if best and conf >= AUTO_OK else "uncertain"
            if not best:
                best, state = cands[0]["id"], "uncertain"
        with db() as c:
            c.execute(
                "update citations set candidates=?, passage_id=?, confidence=?, state=? where id=?",
                (json.dumps([x["id"] for x in cands]), best, conf, state, r["id"]),
            )


def process(lid: int):
    try:
        with db() as c:
            lesson = c.execute("select * from lessons where id=?", (lid,)).fetchone()
            titles = [b["title"] for b in c.execute("select title from books")]
        transcript = json.loads(lesson["transcript"] or "[]")
        if not transcript:
            _set(lid, status="transcribing", error="")
            transcript = transcribe_lesson(lid, lesson, titles)
            _set(lid, transcript=json.dumps(transcript, ensure_ascii=False))
        _set(lid, status="analyzing", progress="מסכם ומאתר מקורות…")
        res = ai.analyze(transcript, titles)
        with db() as c:
            c.execute("delete from citations where lesson_id=? and state!='approved'", (lid,))
            for x in res.get("citations", []):
                c.execute(
                    "insert into citations(lesson_id,quote,source_guess,kind,time,note) values(?,?,?,?,?,?)",
                    (lid, x.get("quote", ""), x.get("source_guess", ""), x.get("kind", "library_book"),
                     x.get("time", ""), x.get("note", "")),
                )
        _set(lid, summary=res.get("summary", ""), topics=json.dumps(res.get("topics", []), ensure_ascii=False),
             status="matching")
        _set(lid, progress="משווה מקורות לספרייה…")
        match_citations(lid)
        _set(lid, status="ready", progress="")
    except Exception as e:  # noqa: BLE001 — מציגים למנהל, לא מפילים את השרת
        traceback.print_exc()
        _set(lid, status="error", error=str(e)[:500])


def start(lid: int):
    threading.Thread(target=process, args=(lid,), daemon=True).start()


def recover_stuck():
    """בהפעלת השרת: שיעורים שנתקעו באמצע עיבוד מסומנים כשגיאה (אפשר לעבד מחדש)."""
    with db() as c:
        c.execute(
            "update lessons set status='error', error='העיבוד הופסק (השרת הופעל מחדש)' "
            "where status in ('queued','transcribing','analyzing','matching')"
        )
