"""Scrubbing previews: the little pictures above the seek bar.

For each video Sofa makes a few contact sheets: one frame every 10 seconds,
240 px wide, 10 x 10 frames per JPEG (so one sheet covers about 16 minutes).
Only keyframes are decoded, which makes this quick: a few seconds per episode
on a Mac with Apple silicon. Sheets live in data/cache/trickplay; the media
folders are never touched.

Videos someone starts playing come first; the rest of the library is done
slowly in the background when nobody is watching.
"""
import hashlib
import json
import math
import os
import shutil
import subprocess
import threading
import time

from . import config, machine, media, store

CACHE = os.path.join(config.DATA_DIR, "cache", "trickplay")
INTERVAL, COLS, ROWS, WIDTH = 10, 8, 8, 320
VERSION = "v2"           # sharper, bigger pictures than v1 (240 px): old sheets are made again
_urgent = []
_lock = threading.Lock()
_wake = threading.Event()
_failed = set()


def _key(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return hashlib.sha1(("%s|%s|%d|%d" % (VERSION, path, st.st_size, int(st.st_mtime))).encode()).hexdigest()[:20]


def folder(item):
    k = _key(item["path"])
    return os.path.join(CACHE, k) if k else None


def meta(item):
    d = folder(item)
    try:
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return None


def sheet(item, n):
    d = folder(item)
    p = os.path.join(d, "sheet%03d.jpg" % n) if d else None
    return p if p and os.path.isfile(p) else None


def want(item):
    """Someone is watching this: make its sheets next."""
    if not config.get("trickplay") or meta(item) or item["path"] in _failed:
        return
    with _lock:
        if item["path"] not in [i["path"] for i in _urgent]:
            _urgent.append(item)
    _wake.set()


def make(item):
    info = media.probe(item["path"]) or {}
    video, duration = info.get("video") or {}, info.get("duration") or 0
    if not video.get("width") or duration < 60:
        return False
    height = max(2, int(round(WIDTH * video["height"] / video["width"] / 2)) * 2)
    out = folder(item)
    tmp = out + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    cmd = ["nice", "-n", "15", media.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-skip_frame", "nokey",
           "-i", item["path"], "-an", "-sn", "-dn", "-vf",
           "fps=1/%d,scale=%d:%d:flags=lanczos,tile=%dx%d" % (INTERVAL, WIDTH, height, COLS, ROWS), "-q:v", "3", "-start_number", "0",
           os.path.join(tmp, "sheet%03d.jpg")]
    try:
        subprocess.run(cmd, capture_output=True, timeout=1800, check=True)
    except (OSError, subprocess.SubprocessError):
        shutil.rmtree(tmp, ignore_errors=True)
        _failed.add(item["path"])
        return False
    sheets = sorted(n for n in os.listdir(tmp) if n.endswith(".jpg"))
    if not sheets:
        shutil.rmtree(tmp, ignore_errors=True)
        _failed.add(item["path"])
        return False
    with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"interval": INTERVAL, "cols": COLS, "rows": ROWS, "w": WIDTH, "h": height,
                   "count": int(math.ceil(duration / INTERVAL)), "sheets": len(sheets)}, f)
    shutil.rmtree(out, ignore_errors=True)
    os.rename(tmp, out)
    return True


def _next(library):
    with _lock:
        if _urgent:
            return _urgent.pop(0)
    if media.should_wait() or not machine.heavy_ok():       # gentle mode: ahead of time only in the quiet hours
        return None
    for item in list(library.items.values()):
        if item["kind"] in ("episode", "movie") and item["path"] not in _failed and not meta(item):
            return item
    return None


def _loop(library):
    time.sleep(60)
    while True:
        item = _next(library) if config.get("trickplay") and media.tool("ffmpeg") else None
        if not item:
            _wake.wait(300)
            _wake.clear()
            continue
        try:
            make(item)
        except Exception as exc:
            _failed.add(item["path"])
            store.log("error", "Scrubbing previews for %s: %s" % (item.get("title") or item["id"], str(exc)[:150]))
        time.sleep(1)


def start(library):
    stamp = os.path.join(CACHE, VERSION)
    if not os.path.exists(stamp):                      # sheets from an older version: make them again
        shutil.rmtree(CACHE, ignore_errors=True)
        os.makedirs(CACHE, exist_ok=True)
        open(stamp, "w").close()
    threading.Thread(target=_loop, args=(library,), daemon=True, name="trickplay").start()
