"""Hover previews: a short, silent clip of a video that plays when you point at its card.

Each clip is three 3-second moments (about a fifth, half way and two thirds in, so no
opening logos or credits), 360 px tall, H.264, about 300 KB. Clips live in
data/cache/previews; the media folders are never touched.

A clip is made the first time someone points at a card (a second or two), and in the
background for every movie and the first episode of every show, when nobody is
watching something Sofa has to convert.
"""
import hashlib
import os
import subprocess
import threading
import time

from . import config, media, store

CACHE = os.path.join(config.DATA_DIR, "cache", "previews")
VERSION = "v1"
HEIGHT, PART = 360, 3.0
_urgent = []
_lock = threading.Lock()
_making = set()
_failed = set()
_slots = threading.Semaphore(2)     # clips made while someone waits; more than that waits for the background
_wake = threading.Event()


def _key(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return hashlib.sha1(("%s|%s|%d|%d" % (VERSION, path, st.st_size, int(st.st_mtime))).encode()).hexdigest()[:20]


def clip(item):
    """The finished clip for `item`, or None."""
    k = _key(item["path"])
    p = os.path.join(CACHE, k + ".mp4") if k else None
    return p if p and os.path.isfile(p) else None


def _moments(duration):
    if duration >= 60:
        return [(duration * f, PART) for f in (0.2, 0.45, 0.7)]
    if duration >= 15:
        return [(duration * 0.3, min(8.0, duration * 0.5))]
    return [(0.0, 6.0)]


def make(item, background=False):
    """Make the clip for `item` now. True when there is one."""
    if clip(item):
        return True
    path = item["path"]
    exe = media.tool("ffmpeg")
    if not exe or path in _failed:
        return False
    with _lock:
        if path in _making:
            return False
        _making.add(path)
    try:
        info = media.probe(path) or {}
        if not info.get("video"):
            _failed.add(path)
            return False
        parts = _moments(info.get("duration") or 0)
        cmd = ["nice", "-n", "15" if background else "5", exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        for at, length in parts:
            cmd += ["-ss", "%.2f" % at, "-t", "%.2f" % length, "-i", path]
        chains = ["[%d:v:0]scale=-2:%d:flags=bicubic,setsar=1,fps=24,format=yuv420p[v%d]" % (n, HEIGHT, n)
                  for n in range(len(parts))]
        graph = ";".join(chains) + ";" + "".join("[v%d]" % n for n in range(len(parts))) + \
            "concat=n=%d:v=1:a=0[out]" % len(parts)
        if "h264_videotoolbox" in media.encoders():
            enc = ["-c:v", "h264_videotoolbox", "-allow_sw", "1", "-b:v", "700k"]
        else:
            enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28"]
        os.makedirs(CACHE, exist_ok=True)
        dest = os.path.join(CACHE, _key(path) + ".mp4")
        tmp = dest + ".part.mp4"
        cmd += ["-filter_complex", graph, "-map", "[out]", "-an", "-sn", "-dn"] + enc + \
            ["-movflags", "+faststart", tmp]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, check=True)
            if os.path.getsize(tmp) < 1000:
                raise OSError("empty clip")
            os.replace(tmp, dest)
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            _failed.add(path)
            err = getattr(exc, "stderr", None)
            why = (err.decode("utf-8", "replace").strip().splitlines() or [""])[-1] if err else str(exc)
            if item.get("adult"):
                store.log_private("error", "Couldn't make a hover preview for a private video")
            else:
                store.log("error", "Couldn't make a hover preview for %s: %s" % (os.path.basename(path), why[:150]))
            return False
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    finally:
        with _lock:
            _making.discard(path)


def for_request(item):
    """A clip for someone pointing at a card right now: made on the spot if a slot is free,
    otherwise queued for the background (the next time it's there). Path or None."""
    found = clip(item)
    if found or not config.get("previews"):
        return found
    if not _slots.acquire(blocking=False):
        want(item)
        return None
    try:
        return clip(item) if make(item) else None
    finally:
        _slots.release()


def want(item):
    with _lock:
        if item["path"] not in [i["path"] for i in _urgent]:
            _urgent.append(item)
    _wake.set()


def _wanted(library):
    """Every movie, and the first episode of every show (what a show's card previews)."""
    lib = library.public(adult=True)
    out = [library.item(m["id"]) for m in lib["movies"] + lib["adult"]["movies"]]
    for show in lib["shows"] + lib["adult"]["shows"]:
        seasons = [s for s in show["seasons"] if s["episodes"]]
        regular = [s for s in seasons if s["n"] > 0] or seasons
        if regular:
            out.append(library.item(regular[0]["episodes"][0]["id"]))
    return [i for i in out if i]


def _prune(library):
    """Clips of videos that are gone for good (a week, so an unplugged drive doesn't count)."""
    keep = {_key(i["path"]) for i in list(library.items.values())}
    if not keep:
        return
    try:
        names = os.listdir(CACHE)
    except OSError:
        return
    for n in names:
        p = os.path.join(CACHE, n)
        try:
            if n.endswith(".mp4") and n[:-4] not in keep and time.time() - os.path.getmtime(p) > 7 * 86400:
                os.remove(p)
        except OSError:
            pass


def _next(library):
    with _lock:
        if _urgent:
            return _urgent.pop(0)
    if media.busy():
        return None
    for item in _wanted(library):
        if item["path"] not in _failed and not clip(item):
            return item
    return None


def _loop(library):
    time.sleep(90)                  # let the library be read first
    pruned = 0
    while True:
        item = None
        try:
            if config.get("previews") and media.tool("ffmpeg") and library.generated:
                if time.time() - pruned > 86400 and not library.scanning:
                    _prune(library)
                    pruned = time.time()
                item = _next(library)
        except Exception as exc:
            store.log("error", "Hover previews: %s" % exc)
        if not item:
            _wake.wait(300)
            _wake.clear()
            continue
        make(item, background=True)
        time.sleep(1)


def status(library):
    wanted = _wanted(library)
    return {"made": sum(1 for i in wanted if clip(i)), "wanted": len(wanted), "on": bool(config.get("previews"))}


def start(library):
    threading.Thread(target=_loop, args=(library,), daemon=True, name="previews").start()
