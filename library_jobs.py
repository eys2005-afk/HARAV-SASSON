"""העלאת ספרים כעבודת רקע (ספר של 800 עמודים לא יכול לרוץ בתוך בקשת HTTP)."""
import itertools
import threading
from pathlib import Path

import library

JOBS: dict[int, dict] = {}  # בזיכרון בלבד; נעלם בהפעלה מחדש (הספר עצמו נשמר ב-DB)
_ids = itertools.count(1)
_lock = threading.Lock()


def start(tmp: Path, title: str, author: str, aliases: str, ocr: bool) -> int:
    jid = next(_ids)
    JOBS[jid] = {"title": title, "status": "running", "msg": "מתחיל…"}

    def say(msg: str):
        JOBS[jid]["msg"] = msg

    def run():
        try:
            if ocr and tmp.suffix.lower() == ".pdf":
                import ocr_pdf

                pages, want = ocr_pdf.ocr_pages(tmp, title, log=say)
                if len(pages) < want * 0.9:
                    raise RuntimeError(f"OCR הושלם ל-{len(pages)} מתוך {want} עמודים בלבד. העלה שוב — מה שהושלם נשמר ולא יחויב שוב")
                say("מוסיף לספרייה…")
                _, n = library.add_book(title, author, f"OCR Gemini: {tmp.name}", ocr_pdf.pages_to_items(pages), aliases)
            else:
                say("קורא את הקובץ…")
                _, n = library.add_book_file(tmp, title, author, aliases)
            JOBS[jid].update(status="done", msg=f"נוסף ({n} פסקאות)")
        except Exception as e:  # noqa: BLE001
            JOBS[jid].update(status="error", msg=str(e)[:300])
        finally:
            tmp.unlink(missing_ok=True)

    threading.Thread(target=run, daemon=True).start()
    return jid
