"""הוספת ספר מקובץ מהשורה: python add_book.py <קובץ> --title "..." [--author ".."] [--aliases "א,ב"] [--preview]
--preview: מדפיס כמה פסקאות לדוגמה ולא שומר (לבדיקת איכות החילוץ, למשל PDF הפוך)."""
import argparse
from pathlib import Path

import db as database
import library

ap = argparse.ArgumentParser()
ap.add_argument("file")
ap.add_argument("--title", required=True)
ap.add_argument("--author", default="")
ap.add_argument("--aliases", default="")
ap.add_argument("--preview", action="store_true")
a = ap.parse_args()
database.init()
p = Path(a.file)
if a.preview:
    items = library.PARSERS[p.suffix.lower()](p)
    print(len(items), "פסקאות")
    for ref, t in items[len(items) // 3: len(items) // 3 + 3]:
        print("-", ref, ":", t[:300])
else:
    _, n = library.add_book_file(p, a.title, a.author, a.aliases)
    print(f"נוסף: {a.title} ({n} פסקאות)")
