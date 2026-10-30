"""Sofa's own files in data/cache: how much space they use, and freeing it.

Everything here is made again when it's needed: pictures resized for screens, scrubbing
previews, hover clips. Details found online are kept (they take a while to look up again);
only failed lookups can be forgotten, so Sofa asks again now instead of tomorrow.
"""
import json
import os
import shutil
import threading
import time

from . import artwork, metadata, previews, store, trickplay

REBUILDABLE = {"pictures sized for screens": artwork.CACHE, "scrubbing previews": trickplay.CACHE,
               "hover previews": previews.CACHE}
_sizes = {}
_lock = threading.Lock()


def _size(folder):
    total = 0
    for d, _dirs, files in os.walk(folder):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return total


def usage(max_age=600):
    """{"parts": {name: bytes}, "bytes": total}, measured at most every ten minutes."""
    with _lock:
        if time.time() - _sizes.get("at", 0) > max_age:
            parts = {name: _size(folder) for name, folder in REBUILDABLE.items()}
            _sizes.update(at=time.time(), parts=parts, bytes=sum(parts.values()))
        return {"parts": _sizes["parts"], "bytes": _sizes["bytes"]}


def free_space():
    for name, folder in REBUILDABLE.items():
        shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(trickplay.CACHE, exist_ok=True)
    open(os.path.join(trickplay.CACHE, trickplay.VERSION), "w").close()
    _sizes.clear()
    store.log("settings", "Freed the space used by Sofa's own pictures and previews (they're made again as needed)")


def retry_lookups():
    """Forget the lookups that found nothing, so the next scan asks again."""
    n = 0
    try:
        names = os.listdir(metadata.CACHE)
    except OSError:
        names = []
    for name in names:
        p = os.path.join(metadata.CACHE, name)
        try:
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("_miss"):
                    os.remove(p)
                    n += 1
        except (OSError, ValueError, AttributeError):
            pass
    store.log("settings", "Asked again for details Sofa couldn't find before (%d)" % n)
    return n
