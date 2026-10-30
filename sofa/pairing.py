"""Sign in with your phone: a TV (or the Fire TV app, the Roku channel, the Sofa box) shows a short
code and a QR code; someone signed in on a phone approves it and picks the profile; the TV is signed
in. No typing passwords with a remote.

Codes last 10 minutes and are kept in memory only. The TV asks every couple of seconds whether its
code was approved, with a secret only it knows; when it was, it gets a sign-in (a cookie for a
browser, a token for an app).
"""
import secrets
import threading
import time

LIFETIME = 600
DIGITS = "23456789"                 # no 0/1: they look like O/I on some TV fonts
_lock = threading.Lock()
_pending = {}                       # code -> {"poll", "name", "ip", "at", "user": None | id}


def _clean():
    cut = time.time() - LIFETIME
    for code in [c for c, p in _pending.items() if p["at"] < cut]:
        del _pending[code]


def start(name, ip):
    """A new code for a device. Returns (code, poll secret)."""
    with _lock:
        _clean()
        if sum(1 for p in _pending.values() if p["ip"] == ip) >= 5:      # one device asking over and over
            oldest = min((c for c, p in _pending.items() if p["ip"] == ip), key=lambda c: _pending[c]["at"])
            del _pending[oldest]
        code = "".join(secrets.choice(DIGITS) for _ in range(6))
        while code in _pending:
            code = "".join(secrets.choice(DIGITS) for _ in range(6))
        poll = secrets.token_urlsafe(24)
        _pending[code] = {"poll": poll, "name": (name or "TV")[:40], "ip": ip, "at": time.time(), "user": None}
        return code, poll


def lookup(code):
    """What's waiting under this code (for the phone's approval page), or None."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    with _lock:
        _clean()
        p = _pending.get(code)
        return dict(p, code=code) if p and p["user"] is None else None


def approve(code, user_id):
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    with _lock:
        _clean()
        p = _pending.get(code)
        if not p or p["user"] is not None:
            return False
        p["user"] = user_id
        return True


def poll(secret):
    """("waiting" | "approved" | "expired", user id, device name). An approved code is used up."""
    with _lock:
        _clean()
        for code, p in list(_pending.items()):
            if secrets.compare_digest(p["poll"], str(secret or "")):
                if p["user"] is None:
                    return "waiting", None, p["name"]
                del _pending[code]
                return "approved", p["user"], p["name"]
    return "expired", None, None
