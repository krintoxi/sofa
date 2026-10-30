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
"""


MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN guest INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN adult INTEGER NOT NULL DEFAULT 0",
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
