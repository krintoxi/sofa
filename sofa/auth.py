"""Accounts, sessions, login throttling and network classification."""
import hashlib
import re
import hmac
import ipaddress
import secrets
import threading
import time

from . import config, store

SESSION_COOKIE = "sofa_session"
SESSION_DAYS = 60
GUEST_HOURS = 24
GUEST_NAME = "Guest"
PBKDF2_ROUNDS = 240000

_PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fd00::/8", "fe80::/10")]
_TAILSCALE = [ipaddress.ip_network(n) for n in ("100.64.0.0/10", "fd7a:115c:a1e0::/48")]
_LOOPBACK = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "::1/128")]


def network_of(ip):
    """'local' (this machine), 'lan' (home network), 'tailnet' (Tailscale), or 'internet'."""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return "internet"
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped
    if any(addr in n for n in _LOOPBACK):
        return "local"
    if any(addr in n for n in _TAILSCALE):
        return "tailnet"
    if any(addr in n for n in _PRIVATE):
        return "lan"
    return "internet"


def allowed_network(net):
    return net != "internet" or config.get("remote") == "public"


# ---------------------------------------------------------------- passwords

def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ROUNDS, salt, digest)


def check_password(password, stored):
    try:
        _, rounds, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(test, digest)
    except (ValueError, TypeError):
        return False


def validate_new(name, password):
    name = (name or "").strip()
    if not name or len(name) > 40:
        return "Enter a name up to 40 characters."
    if len(password or "") < 8:
        return "Use a password of at least 8 characters."
    return None


# ---------------------------------------------------------------- users

def user_count():
    return store.q1("SELECT COUNT(*) AS n FROM users")["n"]


def create_user(name, password, admin=False):
    store.ex("INSERT INTO users (name, pw, admin, created) VALUES (?,?,?,?)",
             name.strip(), hash_password(password), 1 if admin else 0, int(time.time()))
    return store.q1("SELECT id, name, admin FROM users WHERE name = ?", name.strip())


def guest_user():
    """The shared Guest account (created on first use). It has no usable password."""
    row = store.q1("SELECT id, name FROM users WHERE guest = 1")
    if row:
        return row
    name = GUEST_NAME if not store.q1("SELECT id FROM users WHERE name = ?", GUEST_NAME) else "Guest visitor"
    store.ex("INSERT INTO users (name, pw, admin, guest, created) VALUES (?,?,0,1,?)",
             name, "guest$" + secrets.token_hex(16), int(time.time()))
    return store.q1("SELECT id, name FROM users WHERE guest = 1")


def clear_guest():
    row = store.q1("SELECT id FROM users WHERE guest = 1")
    if row:
        for table in ("progress", "live_favorites", "music_likes", "music_plays", "sessions"):
            store.ex("DELETE FROM %s WHERE user_id = ?" % table, row["id"])


def list_users():
    rows = store.q("""SELECT u.id, u.name, u.admin, u.guest, u.adult, u.kids, u.created,
                      (SELECT MAX(seen) FROM sessions s WHERE s.user_id = u.id) AS seen
                      FROM users u ORDER BY u.guest, u.name""")
    return [dict(r) for r in rows]


def set_password(user_id, password):
    store.ex("UPDATE users SET pw = ? WHERE id = ?", hash_password(password), user_id)
    store.ex("DELETE FROM sessions WHERE user_id = ?", user_id)


def set_adult(user_id, on):
    """Whether this person may see the Adult section. Guests never can."""
    store.ex("UPDATE users SET adult = ? WHERE id = ? AND guest = 0 AND kids = 0", 1 if on else 0, user_id)


def set_kids(user_id, on):
    """A Kids profile sees only family titles, and never the Adult section (switched off with it)."""
    store.ex("UPDATE users SET kids = ? WHERE id = ? AND guest = 0 AND admin = 0", 1 if on else 0, user_id)
    if on:
        store.ex("UPDATE users SET adult = 0 WHERE id = ?", user_id)


def delete_user(user_id):
    store.ex("DELETE FROM users WHERE id = ?", user_id)


# ---------------------------------------------------------------- profiles ("Who's watching?")

AVATARS = 8


def _avatar(row):
    return row["avatar"] if row["avatar"] is not None and row["avatar"] >= 0 else row["id"] % AVATARS


def locked(row):
    """Profiles that can see the Adult section or run the server ask for their PIN (or password) to switch to."""
    return bool(row["admin"] or row["adult"])


def profiles():
    rows = store.q("SELECT id, name, admin, adult, kids, avatar, pin FROM users WHERE guest = 0 ORDER BY id")
    return [{"id": r["id"], "name": r["name"], "avatar": _avatar(r), "locked": locked(r), "pin": bool(r["pin"]),
             "kids": bool(r["kids"])} for r in rows]


def check_code(user_id, code):
    """The profile's 4-digit PIN, or its password when it has no PIN."""
    row = store.q1("SELECT pw, pin FROM users WHERE id = ? AND guest = 0", user_id)
    if not row:
        return False
    return check_password(str(code or ""), row["pin"] or row["pw"])


def set_profile(user_id, avatar=None, pin=None):
    if avatar is not None:
        store.ex("UPDATE users SET avatar = ? WHERE id = ?", max(0, min(AVATARS - 1, int(avatar))), user_id)
    if pin is not None:
        pin = str(pin).strip()
        if pin and not re.match(r"^\d{4}$", pin):
            raise ValueError("A PIN is 4 digits.")
        store.ex("UPDATE users SET pin = ? WHERE id = ?", hash_password(pin) if pin else None, user_id)


# ---------------------------------------------------------------- sessions

def _token_key(token):
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(user_id, ip, agent, label=None):
    """A sign-in. `label`: a name for a paired TV or app ("Paired: Living room"), kept to manage it."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    if store.no_logs():                         # not where anyone signed in from, nor on what
        ip = agent = None
    agent = label or agent
    store.ex("INSERT INTO sessions (token, user_id, created, seen, ip, agent) VALUES (?,?,?,?,?,?)",
             _token_key(token), user_id, now, now, ip, (agent or "")[:200] or None)
    store.ex("DELETE FROM sessions WHERE seen < ?", now - SESSION_DAYS * 86400)
    return token


def sessions():
    """Everyone's sign-ins, newest use first, for the Server page (an id instead of the secret)."""
    rows = store.q("""SELECT s.token, s.created, s.seen, s.agent, u.name, u.id AS user_id FROM sessions s
                      JOIN users u ON u.id = s.user_id WHERE u.guest = 0 ORDER BY s.seen DESC""")
    return [{"id": r["token"][:16], "user": r["name"], "user_id": r["user_id"], "created": r["created"], "seen": r["seen"],
             "device": r["agent"] or ""} for r in rows]


def session_label(token):
    """The name a paired TV or app was given (kept when it switches profile)."""
    row = store.q1("SELECT agent FROM sessions WHERE token = ?", _token_key(token)) if token else None
    return row["agent"] if row and (row["agent"] or "").startswith("Paired: ") else None


def end_session_by_id(sid):
    if len(sid or "") == 16:
        store.ex("DELETE FROM sessions WHERE substr(token, 1, 16) = ?", sid)


def session_user(token):
    if not token:
        return None
    key = _token_key(token)
    row = store.q1("""SELECT u.id, u.name, u.admin, u.guest, u.adult, u.kids, u.avatar, u.pin, s.seen, s.created FROM sessions s
                      JOIN users u ON u.id = s.user_id WHERE s.token = ?""", key)
    if not row or row["seen"] < time.time() - SESSION_DAYS * 86400:
        return None
    if row["guest"] and row["created"] < time.time() - GUEST_HOURS * 3600:
        return None
    if time.time() - row["seen"] > 300:
        store.ex("UPDATE sessions SET seen = ? WHERE token = ?", int(time.time()), key)
    return {"id": row["id"], "name": row["name"], "admin": bool(row["admin"]), "guest": bool(row["guest"]),
            "adult": bool(row["adult"]) and not row["guest"] and not row["kids"], "kids": bool(row["kids"]),
            "avatar": _avatar(row), "pin": bool(row["pin"])}


def end_session(token):
    if token:
        store.ex("DELETE FROM sessions WHERE token = ?", _token_key(token))


# ---------------------------------------------------------------- login throttling

_failures = {}
_fail_lock = threading.Lock()
MAX_FAILURES, WINDOW = 8, 15 * 60


def throttled(ip):
    with _fail_lock:
        recent = [t for t in _failures.get(ip, []) if t > time.time() - WINDOW]
        _failures[ip] = recent
        return len(recent) >= MAX_FAILURES


def record_failure(ip):
    with _fail_lock:
        _failures.setdefault(ip, []).append(time.time())


def login(name, password, ip):
    """Returns the user row or None. Always spends the hashing time so names can't be probed."""
    row = store.q1("SELECT id, name, admin, pw FROM users WHERE name = ? AND guest = 0", (name or "").strip())
    ok = check_password(password or "", row["pw"] if row else hash_password("x"))
    if not row or not ok:
        record_failure(ip)
        store.log("login", "Failed sign-in for \"%s\"" % (name or "")[:40], {"ip": ip})
        return None
    return row
