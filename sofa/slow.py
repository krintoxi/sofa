"""Answers that take a while, kept for a while.

The Server page asks for its status every few seconds, and some parts of it mean reading a whole folder
(the Deleted folder, Sofa's own pictures, a drive that may be asleep) or running a program. Each part is
worked out in the background: a request gets the last answer straight away, and the next one comes when
it's ready. Only the very first time does a request wait, and then only for a moment.
"""
import threading
import time

_lock = threading.Lock()
_parts = {}       # name -> {"value", "at", "has", "busy" (an Event while it's being worked out)}


def cached(name, ttl, fn, wait=3.0, default=None):
    """fn()'s answer, at most `ttl` seconds old when it can be; the old one while a new one is worked out."""
    with _lock:
        p = _parts.setdefault(name, {"value": default, "at": 0.0, "has": False, "busy": None})
        if p["has"] and time.time() - p["at"] < ttl:
            return p["value"]
        job = p["busy"]
        if job is None:
            job = p["busy"] = threading.Event()
            threading.Thread(target=_work, args=(name, fn, job), daemon=True, name="slow-" + name).start()
        has = p["has"]
    if not has:
        job.wait(wait)
    with _lock:
        return p["value"] if p["has"] else default


def _work(name, fn, job):
    try:
        value, ok = fn(), True
    except Exception:
        value, ok = None, False
    with _lock:
        p = _parts[name]
        if ok:                                  # a failure keeps the last answer; the next request tries again
            p.update(value=value, at=time.time(), has=True)
        p["busy"] = None
    job.set()


def forget(*names):
    """Something changed (the Deleted folder was emptied…): the next request waits for a fresh answer."""
    with _lock:
        for name in names or list(_parts):
            p = _parts.get(name)
            if p and not p["busy"]:
                p.update(has=False, at=0.0)
