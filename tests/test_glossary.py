"""בדיקות מילון קיצורים. הרצה: python tests/test_glossary.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="gl_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import glossary  # noqa: E402
import library  # noqa: E402

# קיצור עם גרשיים מתורגם; מילה רגילה לא
from hebrew import normalize  # noqa: E402

assert normalize("אדם קדמון") in glossary.index_expansion('וזה סוד הא"ק וכל האורות')
assert glossary.index_expansion("מה זה בן אדם וגר בעיר") == ""
assert normalize("שם מה") in glossary.index_expansion('והוא שם מ"ה של האצילות')
extra, short = glossary.query_expansion("הרב אמר שזעיר אנפין מקבל מאריך אנפין")
assert "אק" not in short and {"זא", "אא"} <= set(short), short

# חיפוש: הרב אמר במלואו, הספר כתב קיצור
A = ('וזה סוד הא"ק שכל האורות יוצאים ממנו והוא עיקר הכללות של כל העולמות כולם, וכן הוא למעלה מן הכל '
     'ואין שום פרצוף שמשיג אותו כלל וכלל מפני גדולתו הנשגבה.')
B = ("ואחר כך נעשה תיקון הכלים בכל העולמות והאורות הולכים ובאים בסדר מסודר, כל אחד לפי מדרגתו ושורשו בעולם "
     "ובכל התיקונים שנעשו לאחר מכן במהלך ההשתלשלות.")
import db  # noqa: E402

db.init()
library.add_book("ספר בדיקה", "", "test", [("פסקה 1", A), ("פסקה 2", B)])
res = library.find("אדם קדמון הוא למעלה מן הכל והאורות יוצאים ממנו")
assert res and "הא\"ק" in res[0]["text"], res[:1]
print("top score:", res[0]["score"])

# עריכת מילון + reindex
glossary.save(glossary.raw_text() + "\nתת\"ק = תיקון קדוש\n")
assert library.reindex() == 2
print("OK")
