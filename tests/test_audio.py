"""בדיקות פיצול וחיבור תמלול (בלי AI). הרצה: python tests/test_audio.py"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import audio  # noqa: E402

assert audio.parse_ts("01:23") == 83 and audio.parse_ts("1:02:03") == 3723 and audio.parse_ts("5") == 5
assert audio.fmt_ts(83) == "01:23" and audio.fmt_ts(3723) == "1:02:03"

# --- חיבור: חפיפה שמופיעה בסוף מקטע 1 ובתחילת מקטע 2 צריכה להיות מוסרת פעם אחת ---
a = [{"sec": 0, "text": "פתיחה של השיעור על עניין האצילות"},
     {"sec": 60, "text": "ואז אמר הרב שהתשובה קודמת לעולם כי היא שורש הנשמות"}]
b = [{"sec": 1198, "text": "שהתשובה קודמת לעולם כי היא שורש הנשמות ולכן המשך הדברים הוא"},
     {"sec": 1260, "text": "פסקה חדשה לגמרי"}]
a2 = [{"sec": 1140, "text": "ואז אמר הרב שהתשובה קודמת לעולם כי היא שורש הנשמות"}]
m = audio.merge([a2, b])
txt = " ".join(s["text"] for s in m)
assert txt.count("שורש הנשמות") == 1, txt
assert "ולכן המשך הדברים הוא" in txt and "פסקה חדשה לגמרי" in txt
# בלי חפיפה — לא מוחק כלום
c = [{"sec": 2400, "text": "טקסט שונה לגמרי שאין לו קשר למקטע הקודם בכלל"}]
assert len(audio.merge([a, c])) == 3

# --- פיצול: 50 דקות => 3 מקטעים (0, 1200, 2400), חפיפה ---
tmp = Path(tempfile.mkdtemp(prefix="split_"))
src = tmp / "long.mp3"
subprocess.run([audio.ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=3000",
                "-ac", "1", "-ar", "16000", "-b:a", "32k", str(src)], check=True)
d = audio.duration(src)
assert 2995 < d < 3005, d
chunks = audio.split(src, tmp / "w", 1200, 15)
assert [s for _, s in chunks] == [0, 1200, 2400], chunks
durs = [round(audio.duration(f)) for f, _ in chunks]
assert durs[0] == 1215 and durs[1] == 1215 and 595 < durs[2] < 605, durs
# הקלטה קצרה — מקטע אחד
short = tmp / "short.mp3"
subprocess.run([audio.ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=600", str(short)], check=True)
assert len(audio.split(short, tmp / "w2", 1200, 15)) == 1
print("OK", durs)
