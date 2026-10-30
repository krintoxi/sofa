"""SQLite storage: users, sessions, watch progress, probe cache and the activity log."""
import json
import os
import sqlite3
import threading
import time

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL, pw TEXT NOT NULL,
  admin INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created INTEGER NOT NULL, seen INTEGER NOT NULL, ip TEXT, agent TEXT);
CREATE TABLE IF NOT EXISTS progress (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, item TEXT NOT NULL,
  t REAL NOT NULL, d REAL NOT NULL, done INTEGER NOT NULL, at INTEGER NOT NULL,
  PRIMARY KEY (user_id, item));
CREATE TABLE IF NOT EXISTS probes (
  path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, info TEXT);
CREATE TABLE IF NOT EXISTS live_favorites (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, channel TEXT NOT NULL,
  PRIMARY KEY (user_id, channel));
CREATE TABLE IF NOT EXISTS music_likes (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, item TEXT NOT NULL, at INTEGER NOT NULL,
  PRIMARY KEY (user_id, item));
CREATE TABLE IF NOT EXISTS music_plays (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, item TEXT NOT NULL, at INTEGER NOT NULL,
  PRIMARY KEY (user_id, item));
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY, at INTEGER NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS likes (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, item TEXT NOT NULL, at INTEGER NOT NULL,
  PRIMARY KEY (user_id, item));
CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY, at INTEGER NOT NULL);
"""


MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN guest INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN adult INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN pin TEXT",
    "ALTER TABLE users ADD COLUMN avatar INTEGER NOT NULL DEFAULT -1",
]


def db():
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        conn = sqlite3.connect(os.path.join(config.DATA_DIR, "sofa.db"), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        for ddl in MIGRATIONS:
            try:
                conn.execute(ddl)
                conn.commit()
            except sqlite3.OperationalError:
                pass   # already applied
        _local.conn = conn
    return conn


def q(sql, *args):
    return db().execute(sql, args).fetchall()


def q1(sql, *args):
    return db().execute(sql, args).fetchone()


def ex(sql, *args):
    conn = db()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur


# ---------------------------------------------------------------- logs, and keeping none

problems_unlogged = [0]       # problems while no logs are kept: only how many, never what


def no_logs():
    """Server → Privacy, "Keep no logs": nothing about what happens on this server is written anywhere."""
    return bool(config.get("no_logs"))


def log(kind, message, detail=None):
    """Activity shown on the admin page: inbox moves, scans, logins, problems."""
    if no_logs():
        if kind == "error":
            problems_unlogged[0] += 1
        return
    ex("INSERT INTO activity (at, kind, message, detail) VALUES (?,?,?,?)",
       int(time.time()), kind, message, json.dumps(detail) if detail is not None else None)
    ex("DELETE FROM activity WHERE id < (SELECT MAX(id) - 2000 FROM activity)")


PRIVATE_LOG = os.path.join(config.DATA_DIR, "logs", "private.jsonl")


def log_private(kind, message, detail=None):
    """Activity about the Adult section: a plain sentence with no titles, names or paths. The details
    (file names, where they went, why) go to data/logs/private.jsonl, which only a report an admin
    asks for with "Include Adult details" contains."""
    log(kind, message, {"private": True})
    if detail and not no_logs():
        try:
            os.makedirs(os.path.dirname(PRIVATE_LOG), exist_ok=True)
            if os.path.exists(PRIVATE_LOG) and os.path.getsize(PRIVATE_LOG) > 5 * 1024 * 1024:
                os.replace(PRIVATE_LOG, PRIVATE_LOG + ".1")
            with open(PRIVATE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": int(time.time()), "kind": kind, "message": message, "detail": detail}) + "\n")
        except OSError:
            pass


LOG_FILES = ("sofa.log", "selftest.log", os.path.join("logs", "private.jsonl"), os.path.join("logs", "private.jsonl.1"))


def wipe_logs():
    """Erase every log Sofa keeps, so nothing can be read back: the activity list, the Adult details log,
    the server log (data/sofa.log), finished downloads and conversions (with their titles and links), the
    addresses and devices signed-in sessions came from, and the same in the backups. The database file is
    rewritten so the erased rows can't be recovered from it either."""
    conn = db()
    conn.execute("PRAGMA secure_delete=ON")        # erased rows are overwritten, not just marked free
    conn.execute("DELETE FROM activity")
    conn.execute("UPDATE sessions SET ip = NULL, agent = NULL")
    for sql in ("DELETE FROM downloads WHERE state NOT IN ('queued', 'working')",
                "DELETE FROM conversions WHERE state NOT IN ('queued', 'working')"):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass                                  # that part of Sofa hasn't been used here
    conn.commit()
    try:
        conn.execute("VACUUM")                    # rewrite the file without the free pages
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass                                      # busy: the rows are already overwritten (secure_delete)
    for rel in LOG_FILES:
        path = os.path.join(config.DATA_DIR, rel)
        try:
            if rel == "sofa.log":
                open(path, "w").close()           # the service keeps it open: empty it rather than remove it
            else:
                os.remove(path)
        except OSError:
            pass
    problems_unlogged[0] = 0


def scrub_private(folders):
    """Older versions wrote adult titles into the activity log: rewrite those entries without them."""
    rows = q("SELECT id, message, detail FROM activity WHERE detail IS NULL OR detail NOT LIKE '%\"private\": true%'")
    for r in rows:
        text = (r["message"] or "") + " " + (r["detail"] or "")
        if " to Adult" in (r["message"] or "") or any(f and f in text for f in folders):
            ex("UPDATE activity SET message = ?, detail = ? WHERE id = ?",
               "Filed a video in the Adult section", json.dumps({"private": True}), r["id"])


def decode_saved_ids():
    """Until 0.6.1, things saved from the web app were stored under %-encoded IDs ("e%3Athe-sopranos%3A1%3A1"),
    so watch progress, likes and intro marks didn't match the library after a reload. Put them right, once."""
    from urllib.parse import unquote
    if migrated("decode-saved-ids"):
        return 0
    fixed = 0
    for table, key in (("progress", "user_id"), ("music_likes", "user_id"), ("music_plays", "user_id"), ("likes", "user_id"),
                       ("markers", "kind")):
        try:
            rows = q("SELECT rowid, item, {k} FROM {t} WHERE instr(item, '%') > 0".format(k=key, t=table))
        except sqlite3.OperationalError:
            continue                                     # a table that isn't there yet
        for r in rows:
            good = unquote(r["item"])
            if good == r["item"]:
                continue
            if q1("SELECT 1 FROM %s WHERE item = ? AND %s = ?" % (table, key), good, r[key]):
                ex("DELETE FROM %s WHERE rowid = ?" % table, r["rowid"])     # the right one is there already
            else:
                ex("UPDATE %s SET item = ? WHERE rowid = ?" % table, good, r["rowid"])
            fixed += 1
    if fixed:
        log("settings", "Put %d saved watch positions, likes and intro marks back under the right titles" % fixed)
    return fixed


def migrated(name):
    """True once a one-time data change has run; marks it as run."""
    if q1("SELECT 1 FROM migrations WHERE name = ?", name):
        return True
    ex("INSERT INTO migrations (name, at) VALUES (?,?)", name, int(time.time()))
    return False


def recent_activity(limit=60, kinds=None):
    rows = q("SELECT * FROM activity ORDER BY id DESC LIMIT ?", limit * 3 if kinds else limit)
    out = []
    for r in rows:
        if kinds and r["kind"] not in kinds:
            continue
        out.append({"at": r["at"], "kind": r["kind"], "message": r["message"],
                    "detail": json.loads(r["detail"]) if r["detail"] else None})
        if len(out) >= limit:
            break
    return out
