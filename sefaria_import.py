"""ייבוא ספרים מ-Sefaria (רישיון CC-BY-SA בדרך כלל) לספרייה.

שימוש:
    python sefaria_import.py --list                    # מה זמין מהרשימה המוכנה
    python sefaria_import.py --preset                  # כל הספרים שבקשת ושקיימים ב-Sefaria
    python sefaria_import.py "Orot HaKodesh" "Olat Reiyah"   # לפי שם Sefaria באנגלית
דרך רשת ארגונית: להגדיר OUTBOUND_PROXY (ו-INSECURE_SSL=1 מאחורי BlueCoat) ב-.env
"""
import sys
import time
from urllib.parse import quote

import requests

import config
import db as database
import library

API = "https://www.sefaria.org/api"

# שם ב-Sefaria -> כינויים שהרב עשוי לומר (לזיהוי אזכורים)
PRESET = {
    "Orot": "אורות",
    "Orot HaKodesh": "אורות הקודש",
    "Orot HaTeshuvah": "אורות התשובה",
    "Orot HaTorah": "אורות התורה",
    "Olat Reiyah": "עולת ראיה,עולת הראיה",
    "Musar Avikha": "מוסר אביך",
    "Shemonah Kevatzim": "שמונה קבצים,ח קבצים",
    "Middot HaRa'ayah": "מידות הראיה",
    "Midbar Shur": "מדבר שור",
    "Ma'amar Hador": "מאמר הדור",
    "For the Perplexed of the Generation": "לנבוכי הדור",
    "Ein Ayah": "עין איה,עין אי\"ה",
    "Sha'ar HaKavanot": "שער הכוונות,שער הכוונות לאריזל",
    "Sha'arei Orah": "שערי אורה,שערי אורה לגיקטילא",
}


def session() -> requests.Session:
    s = requests.Session()
    if config.OUTBOUND_PROXY:
        s.proxies = {"http": config.OUTBOUND_PROXY, "https": config.OUTBOUND_PROXY}
    if config.INSECURE_SSL:
        s.verify = False
        import urllib3

        urllib3.disable_warnings()
    return s


def _get(s, path, **params):
    for attempt in range(4):
        r = s.get(f"{API}/{path}", params=params, timeout=90)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(3 * (attempt + 1))
            continue
        return r
    return r


def leaves(schema: dict, en=(), he=()):
    """עלי הסכימה: (ref_en, ref_he). עלה 'default' משתמש בנתיב ההורה."""
    title = schema.get("title", "")
    htitle = schema.get("heTitle", "")
    if schema.get("default"):
        title = htitle = ""
    en = en + ((title,) if title else ())
    he = he + ((htitle,) if htitle else ())
    if "nodes" in schema:
        for n in schema["nodes"]:
            yield from leaves(n, en, he)
    else:
        yield en, he


def import_book(s, name: str, aliases: str = "") -> tuple[int, int]:
    idx = _get(s, f"index/{quote(name)}").json()
    if "schema" not in idx:
        raise ValueError(f"'{name}' לא נמצא ב-Sefaria")
    he_title = idx.get("heTitle") or idx["schema"].get("heTitle") or name
    author = ", ".join(a if isinstance(a, str) else a.get("en", "") for a in idx.get("authors") or [])
    items, ver = [], ""
    root = idx["schema"]
    paths = list(leaves(root, (), ())) if "nodes" in root else [((root["title"],), (he_title,))]
    for en, he in paths:
        # שורש הסכימה כבר כולל את שם הספר כאיבר ראשון
        ref = ", ".join(en) if len(en) > 1 or "nodes" not in root else name
        ref = ref if ref.startswith(name) else f"{name}, {ref}"
        r = _get(s, f"v3/texts/{quote(ref)}", version="hebrew", return_format="text_only")
        if r.status_code != 200:
            print(f"   דילוג על {ref}: {r.status_code}")
            continue
        vs = r.json().get("versions") or []
        if not vs or not vs[0].get("text"):
            continue
        ver = f"{vs[0].get('versionTitle', '')} ({vs[0].get('license', '')})"
        label = " ".join(h for h in he if h != he_title) or he_title
        items += library.flatten_sefaria(vs[0]["text"], label)
        time.sleep(0.3)
    if not items:
        raise ValueError(f"אין טקסט עברי זמין ל-'{name}'")
    items = library._pack([(r, t) for r, t in items])
    return library.add_book(he_title, author, f"Sefaria: {name} — {ver}", items, aliases)


def main(argv):
    database.init()
    if not argv or argv[0] == "--list":
        for k, v in PRESET.items():
            print(f"{k:40} {v}")
        return
    names = list(PRESET) if argv[0] == "--preset" else argv
    s = session()
    for n in names:
        try:
            print("מייבא", n, "…", flush=True)
            bid, cnt = import_book(s, n, PRESET.get(n, ""))
            print(f"   ✓ {cnt} פסקאות (book {bid})")
        except Exception as e:  # noqa: BLE001
            print(f"   ✗ {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
