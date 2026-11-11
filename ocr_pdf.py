"""OCR של ספר סרוק/מבולגן ב-Gemini, בחלקים של כמה עמודים (כמו ב-ShiraAI, אבל לספר שלם).

    python ocr_pdf.py "<pdf>" --title "שם הספר" [--author ".."] [--aliases "א,ב"] [--chunk 6] [--workers 4] [--start 1 --end 40]

* כל חלק נשמר ב-data/ocr/<שם>/ ולכן אפשר להפסיק ולהמשיך (חלקים שכבר נעשו מדולגים).
* בסוף מוסיף את הספר לספרייה, כשכל עמוד = ref "עמ' PDF N".
* עלות משוערת: ~0.03$ קלט + ~2.5$ פלט לכל 800 עמודים צפופים. להתחיל עם --start 1 --end 12 לבדיקה.
* אותה פונקציה (ocr_pages) משמשת גם את העלאת הספרים באתר.
"""
import argparse
import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ai
import config
import db as database
import library


def chunk_bytes(reader, a: int, b: int) -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    for i in range(a - 1, b):
        w.add_page(reader.pages[i])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def split_pages(text: str, first_page: int) -> list[tuple[int, str]]:
    return [
        (first_page + int(m.group(1)) - 1, m.group(2).strip())
        for m in re.finditer(r"===\s*עמוד\s*(\d+)\s*===\s*(.*?)(?=\n===\s*עמוד|\Z)", text, re.S)
    ]


def ocr_pages(pdf: Path, title: str, start: int = 1, end: int = 0, chunk: int = 6, workers: int = 4,
              log=print) -> tuple[list[tuple[int, str]], int]:
    """מחזיר ([(עמוד, טקסט)], מספר העמודים שהתבקשו). חלקים שנכשלו לא נשמרים — הרצה חוזרת תשלים אותם."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    end = min(end or len(reader.pages), len(reader.pages))
    cache = config.DATA_DIR / "ocr" / re.sub(r"\W+", "_", title)[:60]
    cache.mkdir(parents=True, exist_ok=True)
    ranges = [(s, min(s + chunk - 1, end)) for s in range(start, end + 1, chunk)]

    def work(r):
        f = cache / f"{r[0]:05d}-{r[1]:05d}.txt"
        if not f.exists():
            f.write_text(ai.ocr_pdf_bytes(chunk_bytes(reader, *r)), encoding="utf-8")
        return r

    done = 0
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(work, r): r for r in ranges}
        for fu in as_completed(futs):
            done += 1
            try:
                fu.result()
                log(f"OCR: חלק {done} מתוך {len(ranges)}")
            except Exception as e:  # noqa: BLE001
                log(f"OCR: חלק {futs[fu][0]}-{futs[fu][1]} נכשל ({e}); הרצה חוזרת תשלים אותו")
    pages: list[tuple[int, str]] = []
    for f in sorted(cache.glob("*.txt")):
        s = int(f.name.split("-")[0])
        if start <= s <= end:
            pages += split_pages(f.read_text(encoding="utf-8"), s)
    return sorted(pages), end - start + 1


def pages_to_items(pages):
    return library._pack([(f"עמ' PDF {n}", t) for n, t in pages if t])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--title", required=True)
    ap.add_argument("--author", default="")
    ap.add_argument("--aliases", default="")
    ap.add_argument("--chunk", type=int, default=6)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--ingest", action="store_true", help="רק להוסיף לספרייה מה-cache, בלי OCR חדש")
    a = ap.parse_args()
    pdf = Path(a.pdf)
    if a.ingest:  # קורא רק מה-cache
        from pypdf import PdfReader

        end = a.end or len(PdfReader(str(pdf)).pages)
        cache = config.DATA_DIR / "ocr" / re.sub(r"\W+", "_", a.title)[:60]
        pages = []
        for f in sorted(cache.glob("*.txt")):
            pages += split_pages(f.read_text(encoding="utf-8"), int(f.name.split("-")[0]))
        pages.sort()
        want = end - a.start + 1
    else:
        pages, want = ocr_pages(pdf, a.title, a.start, a.end, a.chunk, a.workers)
    print(f"עמודים שחולצו: {len(pages)}/{want}")
    if a.ingest or len(pages) >= want * 0.98:
        database.init()
        _, n = library.add_book(a.title, a.author, f"OCR Gemini: {pdf.name}", pages_to_items(pages), a.aliases)
        print(f"נוסף לספרייה: {a.title} ({n} פסקאות)")
    else:
        print("לא הוספתי לספרייה (חסרים עמודים). הרץ שוב להשלמה.")


if __name__ == "__main__":
    main()
