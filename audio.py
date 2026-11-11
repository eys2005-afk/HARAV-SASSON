"""פיצול הקלטה ארוכה למקטעים (ffmpeg) וחיבור התמלולים בחזרה, עם חפיפה בין מקטעים."""
import re
import shutil
import subprocess
from pathlib import Path

from hebrew import normalize


def ffmpeg_exe() -> str:
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:  # בשרת בלי ffmpeg מותקן: הבינארי שמגיע עם החבילה imageio-ffmpeg
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("ffmpeg לא נמצא (התקן ffmpeg או pip install imageio-ffmpeg)") from e


def duration(path: Path) -> float:
    r = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True, errors="ignore")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise ValueError("לא הצלחתי לקרוא את אורך ההקלטה (קובץ פגום?)")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def split(path: Path, out_dir: Path, seg: int = 1200, overlap: int = 15) -> list[tuple[Path, float]]:
    """מפצל למקטעי mp3 מונו 16kHz (קטנים וטובים לתמלול). מחזיר [(קובץ, זמן התחלה בשניות)].
    כל מקטע נמשך seg+overlap שניות, כך שהמקטע הבא מתחיל בתוך הזנב של הקודם."""
    total = duration(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg_exe()
    starts = [0.0] if total <= seg * 1.25 else [float(s) for s in range(0, int(total - overlap - 1), seg)]
    chunks = []
    for k, start in enumerate(starts):
        f = out_dir / f"c{k:03d}.mp3"
        if not f.exists():
            cmd = [ff, "-y", "-v", "error", "-ss", str(start)]
            if len(starts) > 1:
                cmd += ["-t", str(seg + overlap)]
            cmd += ["-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(f)]
            subprocess.run(cmd, check=True, capture_output=True)
        chunks.append((f, start))
    return chunks


def parse_ts(s: str) -> float:
    parts = [p for p in re.split(r"[:.]", str(s).strip()) if p.isdigit()]
    nums = [int(p) for p in parts[-3:]]
    sec = 0
    for n in nums:
        sec = sec * 60 + n
    return float(sec)


def fmt_ts(sec: float) -> str:
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _trim_overlap(prev: list[dict], new: list[dict]) -> list[dict]:
    """מסיר מתחילת `new` את הטקסט שכבר הופיע בסוף `prev` (אזור החפיפה). אם אין התאמה — משאיר הכול
    (עדיף כפילות קטנה על אובדן תוכן)."""
    tail: list[str] = []
    for s in prev[-4:]:
        tail += [normalize(w) for w in s["text"].split()]
    tail = [w for w in tail if w][-40:]
    head, pos = [], []
    for si, s in enumerate(new[:6]):
        for wi, w in enumerate(s["text"].split()):
            n = normalize(w)
            if n:
                head.append(n)
                pos.append((si, wi))
    head, pos = head[:150], pos[:150]
    hit = None
    for k in range(min(10, len(tail)), 3, -1):  # לפחות 4 מילים רצופות
        key = tail[-k:]
        for p in range(len(head) - k + 1):
            if head[p:p + k] == key:
                hit = p + k - 1
                break
        if hit is not None:
            break
    if hit is None:
        return new
    si, wi = pos[hit]
    rest = " ".join(new[si]["text"].split()[wi + 1:])
    out = new[si + 1:]
    if rest:
        out = [dict(new[si], text=rest)] + out
    return out


def merge(chunks: list[list[dict]]) -> list[dict]:
    """chunks: לכל מקטע רשימת {"sec": שניות מוחלטות, "text"}. מחזיר רשימה אחת עם t מעוצב."""
    out: list[dict] = []
    for segs in chunks:
        segs = [dict(s) for s in segs]
        if out and segs:
            segs = _trim_overlap(out, segs)
        out += segs
    return [{"t": fmt_ts(s["sec"]), "text": s["text"]} for s in out]
