"""מילון קיצורים ומונחי קבלה. מטרות:
1. החיפוש: הרב אומר "אריך אנפין" והספר כותב א"א. מוסיפים לאינדקס את הפירוש לצד כל קיצור (ולכן trigram מוצא),
   ומוסיפים לשאילתה את הפירושים של קיצורים שהרב אמר.
2. ה-AI: המילון מועבר בפרומפט כדי שיבין קיצורים בתמלול ובפסקאות המועמדות."""
from functools import lru_cache
from pathlib import Path

import config
from hebrew import normalize

SEED = Path(__file__).parent / "glossary_seed.txt"
USER = config.DATA_DIR / "glossary.txt"
_PREFIX = "והבלמשכ"


def raw_text() -> str:
    p = USER if USER.exists() else SEED
    return p.read_text(encoding="utf-8")


def save(text: str):
    USER.write_text(text, encoding="utf-8")
    load.cache_clear()


@lru_cache(maxsize=1)
def load() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(קיצור מנורמל -> פירושים מנורמלים, פירוש מנורמל -> קיצורים)."""
    fwd: dict[str, list[str]] = {}
    rev: dict[str, list[str]] = {}
    for line in raw_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = normalize(k)
        if not key:
            continue
        for ex in v.split("|"):
            e = normalize(ex)
            if e:
                fwd.setdefault(key, []).append(e)
                rev.setdefault(e, []).append(key)
    return fwd, rev


def _strip_prefix(tok: str, fwd) -> str | None:
    if tok in fwd:
        return tok
    if len(tok) > 2 and tok[0] in _PREFIX and tok[1:] in fwd:
        return tok[1:]
    return None


_MARKS = "\"״'׳’"


def _abbr_keys(raw: str, fwd, min_len_unmarked: int = 3) -> list[str]:
    """קיצורים מהמילון שמופיעים בטקסט הגולמי. קיצור קצר (מ"ה, ב"ן) נחשב רק אם יש בו גרש/גרשיים —
    אחרת 'מה' ו'בן' הרגילים היו מקבלים פירוש שגוי."""
    found = []
    for tok in raw.split():
        t = tok.strip(",.;:()[]{}!?–-")
        n = normalize(t)
        if not n:
            continue
        k = _strip_prefix(n, fwd)
        if k and (any(m in t for m in _MARKS) or len(k) >= min_len_unmarked):
            found.append(k)
    return found


def index_expansion(raw_text: str) -> str:
    """לטקסט ספר (גולמי): הפירושים של הקיצורים שמופיעים בו (נוסף לאינדקס בלבד, לא מוצג)."""
    fwd, _ = load()
    out: list[str] = []
    for k in _abbr_keys(raw_text, fwd):
        out += fwd[k]
    return " ".join(dict.fromkeys(out))


def query_expansion(text: str) -> tuple[str, list[str]]:
    """לשאילתה: (פירושים של קיצורים שנאמרו, קיצורים של מונחים מלאים שנאמרו — לניקוד בלבד)."""
    fwd, rev = load()
    n = normalize(text)
    extra: list[str] = []
    for k in _abbr_keys(text, fwd):
        extra += fwd[k]
    short: list[str] = []
    padded = f" {n} "
    for full, abbrs in rev.items():
        if len(full) >= 4 and any(f" {p}{full} " in padded for p in ("", *_PREFIX)):  # גם עם קידומת: מאריך אנפין
            short += abbrs
    return " ".join(dict.fromkeys(extra)), list(dict.fromkeys(short))


def prompt_block(limit: int = 90) -> str:
    """בלוק קצר לפרומפט של ה-AI."""
    lines = [l.strip() for l in raw_text().splitlines() if l.strip() and not l.startswith("#") and "=" in l]
    return "\n".join(lines[:limit])
