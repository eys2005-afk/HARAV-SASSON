"""הגדרות המערכת — הכול מתוך משתני סביבה או קובץ .env (לא נכנס ל-git)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_dotenv():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "app.db"
for _d in (DATA_DIR, AUDIO_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")  # חובה להגדיר; ריק = כניסת מנהל חסומה

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# רשת ארגונית: proxy ל-Gemini ול-Sefaria (למשל http://192.168.174.80:8080)
OUTBOUND_PROXY = os.environ.get("OUTBOUND_PROXY", "")
INSECURE_SSL = os.environ.get("INSECURE_SSL", "") == "1"  # BlueCoat מחליף תעודות

# פיצול הקלטות ארוכות: אורך מקטע (דקות), חפיפה בין מקטעים (שניות), ומקטעים שמתומללים במקביל
CHUNK_MINUTES = int(os.environ.get("CHUNK_MINUTES", "20"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "15"))
TRANSCRIBE_WORKERS = int(os.environ.get("TRANSCRIBE_WORKERS", "3"))

MAX_UPLOAD_MB =int(os.environ.get("MAX_UPLOAD_MB", "500"))
