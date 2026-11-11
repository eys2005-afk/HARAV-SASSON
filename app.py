import hmac
import json
import uuid
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

import config
import db as database
import library
import pipeline

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
database.init()
pipeline.recover_stuck()

AUDIO_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".opus", ".aac", ".flac", ".webm", ".mp4"}
STATUS_HE = {"queued": "בתור", "transcribing": "מתמלל…", "analyzing": "מסכם ומאתר מקורות…",
             "matching": "משווה לספרייה…", "ready": "מוכן", "error": "שגיאה"}


def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)

    return w


@app.after_request
def headers(r):
    r.headers["X-Robots-Tag"] = "noindex, nofollow"
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r


@app.template_filter("fromjson")
def fromjson(s):
    try:
        return json.loads(s or "[]")
    except ValueError:
        return []


@app.context_processor
def ctx():
    return {"is_admin": bool(session.get("admin")), "STATUS_HE": STATUS_HE}


# ---------- ציבורי ----------
@app.get("/")
def index():
    with database.db() as c:
        lessons = c.execute(
            "select id,title,lesson_date,summary,status from lessons "
            + ("" if session.get("admin") else "where status='ready' ")
            + "order by coalesce(nullif(lesson_date,''),created) desc, id desc"
        ).fetchall()
    return render_template("index.html", lessons=lessons)


@app.get("/lesson/<int:lid>")
def lesson(lid):
    with database.db() as c:
        les = c.execute("select * from lessons where id=?", (lid,)).fetchone()
        if not les or (les["status"] != "ready" and not session.get("admin")):
            abort(404)
        cits = c.execute("select * from citations where lesson_id=? order by id", (lid,)).fetchall()
    shown, extra, review = [], [], []
    for ct in cits:
        p = library.get_passage(ct["passage_id"]) if ct["passage_id"] else None
        item = {"c": ct, "p": p}
        if ct["state"] == "hidden":
            review.append(item)
        elif ct["kind"] in ("tanach", "talmud") or (ct["kind"] != "library_book" and not p):
            extra.append(item)
        elif p and ct["state"] in ("matched", "approved"):
            shown.append(item)
        else:
            review.append(item)  # uncertain / none — רק למנהל
            if ct["source_guess"] and ct["state"] != "approved":
                extra.append(item)
    return render_template("lesson.html", les=les, shown=shown, extra=extra,
                           review=review if session.get("admin") else [],
                           transcript=json.loads(les["transcript"] or "[]"),
                           topics=json.loads(les["topics"] or "[]"))


@app.get("/passage/<int:pid>")
def passage(pid):
    p = library.get_passage(pid)
    if not p:
        abort(404)
    return render_template("passage.html", p=p, ctx=library.context(pid))


@app.get("/search")
def search():
    q = request.args.get("q", "").strip()
    return render_template("search.html", q=q, results=library.search(q) if q else [])


@app.get("/api/lesson/<int:lid>/status")
def lesson_status(lid):
    with database.db() as c:
        r = c.execute("select status,error from lessons where id=?", (lid,)).fetchone()
    return jsonify(dict(r) if r else {}) if r else abort(404)


# ---------- מנהל ----------
@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if config.ADMIN_PASSWORD and hmac.compare_digest(pw.encode(), config.ADMIN_PASSWORD.encode()):
            session["admin"] = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("admin"))
        flash("סיסמה שגויה" if config.ADMIN_PASSWORD else "לא הוגדרה ADMIN_PASSWORD בשרת")
    return render_template("login.html")


@app.get("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.get("/admin")
@admin_required
def admin():
    with database.db() as c:
        lessons = c.execute("select id,title,lesson_date,status,error from lessons order by id desc").fetchall()
    return render_template("admin.html", lessons=lessons, has_key=bool(config.GEMINI_API_KEY))


@app.post("/admin/lesson")
@admin_required
def upload_lesson():
    f = request.files.get("audio")
    title = request.form.get("title", "").strip()
    if not f or not title:
        flash("חסר כותרת או קובץ")
        return redirect(url_for("admin"))
    ext = Path(f.filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        flash(f"סוג קובץ לא נתמך ({ext}). נתמכים: {', '.join(sorted(AUDIO_EXT))}")
        return redirect(url_for("admin"))
    path = config.AUDIO_DIR / f"{uuid.uuid4().hex}{ext}"
    f.save(path)
    with database.db() as c:
        lid = c.execute(
            "insert into lessons(title,lesson_date,audio_path) values(?,?,?)",
            (title, request.form.get("date", ""), str(path)),
        ).lastrowid
    pipeline.start(lid)
    return redirect(url_for("lesson", lid=lid))


@app.post("/admin/lesson/<int:lid>/reprocess")
@admin_required
def reprocess(lid):
    if request.form.get("full"):  # תמלול מחדש
        with database.db() as c:
            c.execute("update lessons set transcript='[]' where id=?", (lid,))
    with database.db() as c:
        c.execute("update lessons set status='queued', error='' where id=?", (lid,))
    pipeline.start(lid)
    return redirect(url_for("lesson", lid=lid))


@app.post("/admin/lesson/<int:lid>/delete")
@admin_required
def delete_lesson(lid):
    with database.db() as c:
        r = c.execute("select audio_path from lessons where id=?", (lid,)).fetchone()
        c.execute("delete from lessons where id=?", (lid,))
    if r and r["audio_path"]:
        Path(r["audio_path"]).unlink(missing_ok=True)
    return redirect(url_for("admin"))


@app.post("/admin/citation/<int:cid>")
@admin_required
def edit_citation(cid):
    action = request.form.get("action")
    with database.db() as c:
        ct = c.execute("select * from citations where id=?", (cid,)).fetchone()
        if not ct:
            abort(404)
        if action == "approve":
            pid = request.form.get("passage_id", type=int) or ct["passage_id"]
            if pid and library.get_passage(pid):
                c.execute("update citations set passage_id=?, state='approved', confidence=1 where id=?", (pid, cid))
        elif action == "hide":
            c.execute("update citations set state='hidden' where id=?", (cid,))
        elif action == "reject":
            c.execute("update citations set passage_id=null, state='none' where id=?", (cid,))
    return redirect(url_for("lesson", lid=ct["lesson_id"]) + f"#c{cid}")


@app.get("/admin/library")
@admin_required
def admin_library():
    with database.db() as c:
        books = c.execute(
            "select b.*, (select count(*) from passages where book_id=b.id) n from books b order by b.title"
        ).fetchall()
    return render_template("library.html", books=books)


@app.post("/admin/library/upload")
@admin_required
def upload_book():
    f, title = request.files.get("file"), request.form.get("title", "").strip()
    if not f or not title:
        flash("חסר שם ספר או קובץ")
        return redirect(url_for("admin_library"))
    tmp = config.DATA_DIR / f"tmp_{uuid.uuid4().hex}{Path(secure_filename(f.filename) or 'x.txt').suffix}"
    f.save(tmp)
    try:
        _, n = library.add_book_file(tmp, title, request.form.get("author", ""), request.form.get("aliases", ""))
        flash(f"נוסף: {title} ({n} פסקאות)")
    except Exception as e:  # noqa: BLE001
        flash(f"שגיאה: {e}")
    finally:
        tmp.unlink(missing_ok=True)
    return redirect(url_for("admin_library"))


@app.post("/admin/library/<int:bid>/delete")
@admin_required
def delete_book(bid):
    library.delete_book(bid)
    return redirect(url_for("admin_library"))


@app.post("/admin/library/<int:bid>/aliases")
@admin_required
def book_aliases(bid):
    with database.db() as c:
        c.execute("update books set aliases=? where id=?", (request.form.get("aliases", ""), bid))
    return redirect(url_for("admin_library"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5060, debug=False, threaded=True)
