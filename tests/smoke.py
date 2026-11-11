"""בדיקת עשן ללא AI: קליטת ספר, חיפוש עם קידומות/ניקוד, ודפי האתר. הרצה: python tests/smoke.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="sassoon_test_")
os.environ["ADMIN_PASSWORD"] = "pw"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import library  # noqa: E402
from app import app  # noqa: E402
from db import db  # noqa: E402
from hebrew import normalize  # noqa: E402

TEXT = """בְּרֵאשִׁית בָּרָא אֱלֹהִים אֵת הַשָּׁמַיִם וְאֵת הָאָרֶץ. והארץ היתה תהו ובהו וחשך על פני תהום ורוח אלהים מרחפת על פני המים.

האורה העליונה מתגלה בכל הבריאה כולה, והנשמה כמו שואפת אל מקורה בעולם האצילות, ומתוך כך כל התשוקות הן ניצוצות של רצון עליון.

התשובה קודמת לעולם, שכן היא מעין שורש הנשמות, והחזרה אל האור היא חזרה אל עצמיות החיים של האדם והעולם כולו."""

assert normalize("שָׁלוֹם ר\"י ךםןףץ") == "שלומ רי כמנפצ", normalize("שָׁלוֹם ר\"י ךםןףץ")

p = Path(os.environ["DATA_DIR"]) / "sample.txt"
p.write_text(TEXT, encoding="utf-8")
bid, n = library.add_book_file(p, "אורות (דוגמה)", "הרב קוק", "אורות")
print("passages:", n)

hits = library.find("אמר הרב שהתשובה קודמת לעולם והיא שורש הנשמות", attributed="באורות")
assert hits and "התשובה קודמת" in hits[0]["text"], hits[:1]
print("best:", hits[0]["ref"], hits[0]["score"])
assert library.find("והאורה העליונה מתגלה בבריאה")[0]["text"].count("האורה העליונה") == 1

with db() as c:
    lid = c.execute("insert into lessons(title,status,summary,transcript) values('שיעור בדיקה','ready','סיכום',?)",
                    (json.dumps([{"t": "00:10", "text": "טקסט"}]),)).lastrowid
    c.execute("insert into citations(lesson_id,quote,source_guess,passage_id,confidence,state,time) values(?,?,?,?,?,?,?)",
              (lid, "התשובה קודמת לעולם", "אורות", hits[0]["id"], 0.9, "matched", "00:10"))
    c.execute("insert into citations(lesson_id,quote,source_guess,kind,state) values(?,?,?,?,?)",
              (lid, "ואהבת לרעך", "ויקרא יט", "tanach", "none"))

cl = app.test_client()
for url in ["/", f"/lesson/{lid}", f"/passage/{hits[0]['id']}", "/search?q=התשובה", "/admin/login"]:
    r = cl.get(url)
    assert r.status_code == 200, (url, r.status_code)
assert "התשובה קודמת לעולם, שכן" in cl.get(f"/lesson/{lid}").get_data(as_text=True)
assert cl.get("/admin").status_code == 302  # מוגן
assert cl.post("/admin/login", data={"password": "x"}).status_code == 200
assert cl.post("/admin/login", data={"password": "pw"}).status_code == 302
for url in ["/admin", "/admin/library", f"/lesson/{lid}"]:
    assert cl.get(url).status_code == 200, url
print("OK")
