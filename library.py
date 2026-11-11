"""ספריית הספרים: קליטה (txt / docx / pdf / JSON של Sefaria), פיצול לפסקאות, וחיפוש."""
import json
import re
from pathlib import Path

from db import db
from hebrew import normalize, query_tokens

MAX_CHUNK = 900  # תווים לפסקה באינדקס
MIN_CHUNK = 160


# ---------- קליטה ----------
def _pack(paras: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """מאחד פסקאות קצרות ומפצל ארוכות. paras = [(ref, text)]."""
    out: list[tuple[str, str]] = []
    buf_ref, buf = "", ""
    for ref, text in paras:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        while len(text) > MAX_CHUNK:  # פיצול בגבול משפט
            cut = max(text.rfind(". ", 0, MAX_CHUNK), text.rfind(": ", 0, MAX_CHUNK), text.rfind(" ", 0, MAX_CHUNK))
            cut = cut + 1 if cut > MIN_CHUNK else MAX_CHUNK
            out.append((ref, text[:cut].strip()))
            text = text[cut:].strip()
        if buf and len(buf) + len(text) > MAX_CHUNK:
            out.append((buf_ref, buf))
            buf = ""
        if not buf:
            buf_ref = ref
        buf = (buf + " " + text).strip() if len(buf) < MIN_CHUNK else buf + " " + text
        if len(buf) >= MIN_CHUNK:
            out.append((buf_ref, buf))
            buf = ""
    if buf:
        out.append((buf_ref, buf))
    return out


def parse_txt(path: Path) -> list[tuple[str, str]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1255", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeError:
            continue
    else:
        text = raw.decode("utf-8", "ignore")
    paras = [p for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if p.strip()]
    if len(paras) < 5:  # ללא שורות ריקות — כל שורה פסקה
        paras = [p for p in text.splitlines() if p.strip()]
    return _pack([(f"פסקה {i + 1}", p) for i, p in enumerate(paras)])


def parse_docx(path: Path) -> list[tuple[str, str]]:
    import docx

    d = docx.Document(str(path))
    heading, n, paras = "", 0, []
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        sty = (p.style.name or "").lower()
        if sty.startswith("heading") or sty.startswith("כותרת"):
            heading, n = t[:80], 0
            continue
        n += 1
        paras.append((f"{heading} · פסקה {n}" if heading else f"פסקה {n}", t))
    return _pack(paras)


def parse_pdf(path: Path) -> list[tuple[str, str]]:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer

    paras, total = [], 0
    for i, page in enumerate(extract_pages(str(path)), 1):
        text = "\n".join(el.get_text() for el in page if isinstance(el, LTTextContainer)).strip()
        total += len(text)
        if text:
            paras.append((f"עמ' {i}", text.replace("\n", " ")))
    if total < 200:
        raise ValueError("ה-PDF נראה סרוק (תמונות בלי שכבת טקסט). נדרש OCR או גרסת טקסט של הספר.")
    return _pack(paras)


def parse_sefaria_json(path: Path) -> list[tuple[str, str]]:
    """JSON בפורמט Sefaria-Export (merged.json): {"text": [[...]] או {"פרק": [...]}}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return flatten_sefaria(data.get("text", data))


def flatten_sefaria(node, prefix: str = "") -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if isinstance(node, str):
        return [(prefix.strip(), node)] if node.strip() else []
    if isinstance(node, dict):
        for k, v in node.items():
            items += flatten_sefaria(v, f"{prefix} {k}".strip())
    elif isinstance(node, list):
        for i, v in enumerate(node, 1):
            items += flatten_sefaria(v, f"{prefix}:{i}" if prefix else str(i))
    return items


PARSERS = {".txt": parse_txt, ".docx": parse_docx, ".pdf": parse_pdf, ".json": parse_sefaria_json}


def add_book(title: str, author: str, source: str, items: list[tuple[str, str]], aliases: str = "") -> tuple[int, int]:
    """מוסיף ספר עם הפסקאות שלו. מחזיר (book_id, מספר פסקאות). מונע כפילות לפי כותרת."""
    items = [(r, t) for r, t in items if len(normalize(t)) >= 8]
    if not items:
        raise ValueError("לא נמצא טקסט שאפשר לאנדקס")
    with db() as c:
        if c.execute("select 1 from books where title=?", (title,)).fetchone():
            raise ValueError(f"הספר '{title}' כבר קיים בספרייה (מחק אותו קודם אם רוצים להחליף)")
        bid = c.execute(
            "insert into books(title,author,aliases,source) values(?,?,?,?)", (title, author, aliases, source)
        ).lastrowid
        for seq, (ref, text) in enumerate(items):
            pid = c.execute(
                "insert into passages(book_id,seq,ref,text) values(?,?,?,?)", (bid, seq, ref, text)
            ).lastrowid
            c.execute("insert into passages_fts(rowid,norm) values(?,?)", (pid, normalize(text)))
    return bid, len(items)


def add_book_file(path: Path, title: str, author: str = "", aliases: str = "") -> tuple[int, int]:
    parser = PARSERS.get(path.suffix.lower())
    if not parser:
        raise ValueError(f"סוג קובץ לא נתמך: {path.suffix} (נתמכים: {', '.join(PARSERS)})")
    return add_book(title, author, f"קובץ: {path.name}", parser(path), aliases)


def delete_book(book_id: int):
    with db() as c:
        c.execute("delete from passages_fts where rowid in (select id from passages where book_id=?)", (book_id,))
        c.execute("delete from books where id=?", (book_id,))


# ---------- חיפוש ----------
def hint_books(attributed: str) -> set[int]:
    """ספרים שהשם/כינוי שלהם מוזכר בטקסט האזכור (למשל 'אורות הקודש' / 'לשם')."""
    a = normalize(attributed)
    if not a:
        return set()
    hits = set()
    with db() as c:
        for b in c.execute("select id,title,aliases from books"):
            names = [b["title"]] + [x for x in (b["aliases"] or "").split(",") if x.strip()]
            if any(len(normalize(n)) >= 3 and normalize(n) in a for n in names):
                hits.add(b["id"])
    return hits


def find(text: str, attributed: str = "", limit: int = 8) -> list[dict]:
    """מחזיר פסקאות מועמדות, הכי קרובות ראשונות. score = כיסוי מילות השאילתה."""
    toks = query_tokens(text)
    if not toks:
        return []
    q = " OR ".join(f'"{t}"' for t in toks)
    hinted = hint_books(attributed)
    with db() as c:
        rows = c.execute(
            """select p.id, p.book_id, p.ref, p.text, b.title, bm25(passages_fts) as bm
               from passages_fts join passages p on p.id=passages_fts.rowid
               join books b on b.id=p.book_id
               where passages_fts match ? order by bm limit ?""",
            (q, limit * 6),
        ).fetchall()
    res = []
    for r in rows:
        n = normalize(r["text"])
        cov = sum(1 for t in toks if t in n) / len(toks)
        score = cov + (0.15 if r["book_id"] in hinted else 0)
        res.append({**dict(r), "score": round(score, 3)})
    res.sort(key=lambda x: (-x["score"], x["bm"]))
    return res[:limit]


def search(q: str, limit: int = 30) -> list[dict]:
    return find(q, limit=limit)


def get_passage(pid: int):
    with db() as c:
        return c.execute(
            "select p.*, b.title as book_title, b.author from passages p join books b on b.id=p.book_id where p.id=?",
            (pid,),
        ).fetchone()


def context(pid: int, radius: int = 3) -> list[dict]:
    with db() as c:
        p = c.execute("select book_id,seq from passages where id=?", (pid,)).fetchone()
        if not p:
            return []
        return [
            dict(r)
            for r in c.execute(
                "select id,ref,text from passages where book_id=? and seq between ? and ? order by seq",
                (p["book_id"], p["seq"] - radius, p["seq"] + radius),
            )
        ]
