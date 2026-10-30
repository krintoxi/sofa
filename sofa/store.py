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


def log(kind, message, detail=None):
    """Activity shown on the admin page: inbox moves, scans, logins, problems."""
    ex("INSERT INTO activity (at, kind, message, detail) VALUES (?,?,?,?)",
       int(time.time()), kind, message, json.dumps(detail) if detail is not None else None)
    ex("DELETE FROM activity WHERE id < (SELECT MAX(id) - 2000 FROM activity)")


PRIVATE_LOG = os.path.join(config.DATA_DIR, "logs", "private.jsonl")


def log_private(kind, message, detail=None):
    """Activity about the Adult section: a plain sentence with no titles, names or paths. The details
    (file names, where they went, why) go to data/logs/private.jsonl, which only a report an admin
    asks for with "Include Adult details" contains."""
    log(kind, message, {"private": True})
    if detail:
        try:
            os.makedirs(os.path.dirname(PRIVATE_LOG), exist_ok=True)
            if os.path.exists(PRIVATE_LOG) and os.path.getsize(PRIVATE_LOG) > 5 * 1024 * 1024:
                os.replace(PRIVATE_LOG, PRIVATE_LOG + ".1")
            with open(PRIVATE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": int(time.time()), "kind": kind, "message": message, "detail": detail}) + "\n")
        except OSError:
            pass


def scrub_private(folders):
    """Older versions wrote adult titles into the activity log: rewrite those entries without them."""
    rows = q("SELECT id, message, detail FROM activity WHERE detail IS NULL OR detail NOT LIKE '%\"private\": true%'")
    for r in rows:
        text = (r["message"] or "") + " " + (r["detail"] or "")
        if " to Adult" in (r["message"] or "") or any(f and f in text for f in folders):
            ex("UPDATE activity SET message = ?, detail = ? WHERE id = ?",
               "Filed a video in the Adult section", json.dumps({"private": True}), r["id"])


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
