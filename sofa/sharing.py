"""The public library: the shows and movies an admin shares, for anyone with the share link.

Opening the link (/s/<secret>) signs that browser in as the built-in *Visitor* (users.guest = 2). A
Visitor sees only what's shared, can only watch (their place is kept on their own device, not here),
never sees Adult, and can't reach anything else, even when the server is otherwise home-only: from the
internet, only the share link and what a Visitor needs answer. Making a new link signs every Visitor out.

Settings (Server → Sharing): share_on, share_token, share_all (every show and movie), share_live (Live TV
too), share_games (the page games, off a Sofa Box), public_open (the plain address opens the public library,
for a server that only shares), share_title.
"""
import secrets
import threading
import time

from . import config, store

VISITOR = 2                      # users.guest for the Visitor (1 is the home Wi-Fi's Guest)
SESSION_DAYS = 30
_version = [0]                   # goes up with every change, so the public library is made again
_lock = threading.Lock()


def on():
    return bool(config.get("share_on"))


def version():
    return (_version[0], bool(config.get("share_all")), bool(config.get("share_on")))


def _changed():
    with _lock:
        _version[0] += 1


def token():
    t = config.get("share_token")
    if not t:
        t = secrets.token_urlsafe(9)
        config.update({"share_token": t})
    return t


def check_token(t):
    return bool(t) and secrets.compare_digest(str(t), token())


def new_link():
    """A new secret for the link: the old link stops working and every Visitor is signed out."""
    config.update({"share_token": secrets.token_urlsafe(9)})
    sign_out_visitors()


def visitor_user():
    row = store.q1("SELECT id, name FROM users WHERE guest = ?", VISITOR)
    if row:
        return row
    name = "Visitor" if not store.q1("SELECT id FROM users WHERE name = ?", "Visitor") else "Public visitor"
    store.ex("INSERT INTO users (name, pw, admin, guest, created) VALUES (?,?,0,?,?)",
             name, "visitor$" + secrets.token_hex(16), VISITOR, int(time.time()))
    return store.q1("SELECT id, name FROM users WHERE guest = ?", VISITOR)


def sign_out_visitors():
    row = store.q1("SELECT id FROM users WHERE guest = ?", VISITOR)
    if row:
        store.ex("DELETE FROM sessions WHERE user_id = ?", row["id"])


def shared_ids():
    return {r["item"] for r in store.q("SELECT item FROM shared")}


def set_shared(entry_id, share):
    if share:
        store.ex("INSERT OR REPLACE INTO shared (item, at) VALUES (?, ?)", entry_id, int(time.time()))
    else:
        store.ex("DELETE FROM shared WHERE item = ?", entry_id)
    _changed()


def settings_changed():
    _changed()


def entry_shared(entry, picked=None):
    """A show or movie (as the library lists it): shared with Visitors? Adult never is."""
    if not entry or entry.get("adult"):
        return False
    if config.get("share_all"):
        return True
    return entry["id"] in (shared_ids() if picked is None else picked)


def item_shared(item, library):
    """A playable item (an episode, a movie, an extra): part of something shared?"""
    if not item or item.get("adult") or item.get("kind") not in ("episode", "movie", "extra"):
        return False
    owner = library.find(item["id"] if item["kind"] == "movie" else item.get("show_id"))
    return entry_shared(owner)


def title():
    return (config.get("share_title") or "").strip() or config.get("name")
