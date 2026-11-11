"""נרמול עברית לצורכי חיפוש: ללא ניקוד, פיסוק ואותיות סופיות."""
import re

_NIKUD = re.compile(r"[֑-ׇ]")
_TAGS = re.compile(r"<[^>]+>")
_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
_PREFIX = "והבלמשכ"
STOP = set(
    "של על אל את הוא היא הם הן זה זו זאת אשר כי אם לא גם כל או אבל מה מי איך כך כן אין יש הנה הרי "
    "עוד רק אף אלא כמו עם בין אחר אחד אחת שם פה כאן היה היו יהיה להיות הזה הזאת ההוא אותו אותה".split()
)


def normalize(s: str) -> str:
    s = _TAGS.sub(" ", s or "")
    s = _NIKUD.sub("", s)
    s = s.replace("־", " ")
    s = re.sub(r"[\"'׳״’“”`]", "", s)  # ר"י -> רי
    s = re.sub(r"[^\w\s]|_", " ", s)
    s = s.translate(_FINALS)
    return re.sub(r"\s+", " ", s).strip()


def query_tokens(s: str, limit: int = 20) -> list[str]:
    """מילים לחיפוש trigram: מסיר מילות קישור וקידומות (ו/ה/ב/ל/מ/ש/כ), מעדיף מילים ארוכות."""
    out: list[str] = []
    for t in normalize(s).split():
        if t in STOP:
            continue
        if len(t) >= 6 and t[:2] == "וה":
            t = t[2:]
        elif len(t) >= 5 and t[0] in _PREFIX:
            t = t[1:]
        if len(t) < 3 or t in STOP or t in out:
            continue
        out.append(t)
    out.sort(key=len, reverse=True)
    return out[:limit]
