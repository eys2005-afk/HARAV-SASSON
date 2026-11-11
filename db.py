import sqlite3
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
create table if not exists books(
  id integer primary key,
  title text not null,
  author text default '',
  aliases text default '',          -- שמות נוספים לספר, מופרדים בפסיק (לזיהוי אזכורים)
  source text default '',           -- מאיפה הגיע: sefaria / קובץ
  created text default (datetime('now'))
);
create table if not exists passages(
  id integer primary key,
  book_id integer not null references books(id) on delete cascade,
  seq integer not null,
  ref text not null,
  text text not null
);
create index if not exists passages_book on passages(book_id, seq);
create virtual table if not exists passages_fts using fts5(norm, tokenize='trigram');

create table if not exists lessons(
  id integer primary key,
  title text not null,
  lesson_date text default '',
  audio_path text default '',
  status text default 'queued',     -- queued/transcribing/analyzing/matching/ready/error
  error text default '',
  progress text default '',         -- "מתמלל מקטע 2 מתוך 6"
  summary text default '',
  topics text default '[]',
  transcript text default '[]',     -- JSON: [{"t":"MM:SS","text":"..."}]
  created text default (datetime('now'))
);
create table if not exists citations(
  id integer primary key,
  lesson_id integer not null references lessons(id) on delete cascade,
  quote text default '',
  source_guess text default '',
  kind text default 'library_book',
  time text default '',
  note text default '',
  candidates text default '[]',     -- JSON: passage ids
  passage_id integer,               -- ההתאמה שנבחרה
  confidence real default 0,
  state text default 'pending'      -- matched / uncertain / none / approved / hidden
);
create index if not exists citations_lesson on citations(lesson_id);
"""


@contextmanager
def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("pragma journal_mode=wal")
    c.execute("pragma foreign_keys=on")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with db() as c:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("pragma table_info(lessons)")}
        if "progress" not in cols:  # מיגרציה למסד שנוצר לפני הוספת העמודה
            c.execute("alter table lessons add column progress text default ''")
