"""Kids profiles: a profile an admin marks as Kids sees only family titles.

Allowed: movies rated for children (G, PG, U, TV-Y, TV-G, TV-PG and the like) and shows and movies
whose genres say Kids, Children or Family. Never the Adult section, Live TV or the Server page.
An admin can allow or block any single show or movie (its page, "For kids"), which wins over the
rule: the details services don't know every title.
"""
import threading

from . import store

KID_RATINGS = {"G", "PG", "U", "TV-Y", "TV-Y7", "TV-Y7-FV", "TV-G", "TV-PG", "0", "6", "7", "AL", "TP", "A"}
KID_GENRES = ("kid", "child", "family")
_lock = threading.Lock()
_choices = None             # entry id -> True (allowed) / False (blocked), as an admin set them
version = [0]               # changes when an admin changes a choice (the web app's library is made again)


def _table():
    store.ex("CREATE TABLE IF NOT EXISTS kids_titles (item TEXT PRIMARY KEY, allow INTEGER NOT NULL)")


def choices():
    global _choices
    with _lock:
        if _choices is None:
            _table()
            _choices = {r["item"]: bool(r["allow"]) for r in store.q("SELECT item, allow FROM kids_titles")}
        return dict(_choices)


def choose(entry_id, allow):
    """An admin's choice for one show or movie: True, False, or None to follow the rule again."""
    global _choices
    _table()
    if allow is None:
        store.ex("DELETE FROM kids_titles WHERE item = ?", entry_id)
    else:
        store.ex("INSERT OR REPLACE INTO kids_titles (item, allow) VALUES (?, ?)", entry_id, 1 if allow else 0)
    with _lock:
        _choices = None
        version[0] += 1


def by_rule(entry):
    """For kids by its rating and genres (a show or movie entry)."""
    if entry.get("adult"):
        return False
    rating = str(entry.get("certificate") or "").strip().upper()
    if rating:
        return rating in KID_RATINGS
    genres = " ".join(str(g) for g in entry.get("genres") or []).lower()
    return any(k in genres for k in KID_GENRES)


def allowed(entry, picked=None):
    if not entry or entry.get("adult"):
        return False
    picked = choices() if picked is None else picked
    if entry["id"] in picked:
        return picked[entry["id"]]
    return by_rule(entry)
