"""עיבוד שיעור: תמלול -> סיכום וחילוץ מקורות -> התאמה לספרייה."""
import json
import threading
import traceback

import ai
import library
from db import db

AUTO_OK = 0.6  # מעל זה — מוצג לציבור כמקור מאומת; מתחת — "לא בטוח" (למנהל בלבד)


def _set(lid: int, **kw):
    with db() as c:
        c.execute(f"update lessons set {', '.join(k + '=?' for k in kw)} where id=?", (*kw.values(), lid))


def match_citations(lid: int):
    with db() as c:
        rows = c.execute(
            "select id,quote,source_guess,kind from citations where lesson_id=? and state!='approved'", (lid,)
        ).fetchall()
    for r in rows:
        if r["kind"] not in ("library_book", "other", "unknown"):
            continue
        cands = library.find(f"{r['quote']} {r['source_guess']}", attributed=r["source_guess"], limit=6)
        best, conf, state = None, 0.0, "none"
        if cands:
            try:
                v = ai.rerank(r["quote"], r["source_guess"], cands)
                i = v.get("best")
                if isinstance(i, int) and 0 <= i < len(cands):
                    best, conf = cands[i]["id"], float(v.get("confidence") or 0)
            except ai.AIError:
                best, conf = cands[0]["id"], cands[0]["score"] * 0.8  # בלי AI: ההתאמה הלקסיקלית
            state = "matched" if best and conf >= AUTO_OK else "uncertain"
            if not best:
                best, state = cands[0]["id"], "uncertain"
        with db() as c:
            c.execute(
                "update citations set candidates=?, passage_id=?, confidence=?, state=? where id=?",
                (json.dumps([x["id"] for x in cands]), best, conf, state, r["id"]),
            )


def process(lid: int):
    try:
        with db() as c:
            lesson = c.execute("select * from lessons where id=?", (lid,)).fetchone()
            titles = [b["title"] for b in c.execute("select title from books")]
        transcript = json.loads(lesson["transcript"] or "[]")
        if not transcript:
            _set(lid, status="transcribing", error="")
            transcript = ai.transcribe(lesson["audio_path"])
            _set(lid, transcript=json.dumps(transcript, ensure_ascii=False))
        _set(lid, status="analyzing")
        res = ai.analyze(transcript, titles)
        with db() as c:
            c.execute("delete from citations where lesson_id=? and state!='approved'", (lid,))
            for x in res.get("citations", []):
                c.execute(
                    "insert into citations(lesson_id,quote,source_guess,kind,time,note) values(?,?,?,?,?,?)",
                    (lid, x.get("quote", ""), x.get("source_guess", ""), x.get("kind", "library_book"),
                     x.get("time", ""), x.get("note", "")),
                )
        _set(lid, summary=res.get("summary", ""), topics=json.dumps(res.get("topics", []), ensure_ascii=False),
             status="matching")
        match_citations(lid)
        _set(lid, status="ready")
    except Exception as e:  # noqa: BLE001 — מציגים למנהל, לא מפילים את השרת
        traceback.print_exc()
        _set(lid, status="error", error=str(e)[:500])


def start(lid: int):
    threading.Thread(target=process, args=(lid,), daemon=True).start()


def recover_stuck():
    """בהפעלת השרת: שיעורים שנתקעו באמצע עיבוד מסומנים כשגיאה (אפשר לעבד מחדש)."""
    with db() as c:
        c.execute(
            "update lessons set status='error', error='העיבוד הופסק (השרת הופעל מחדש)' "
            "where status in ('queued','transcribing','analyzing','matching')"
        )
