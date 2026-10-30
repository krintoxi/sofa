"""Downloads for a trip: a video to keep on a phone or laptop and watch without the Sofa computer.

A file the device plays as it is downloads as it is. Anything else (MKV, AVI, HEVC on an older phone)
gets a travel copy first: 720p H.264 with stereo AAC in an MP4, with its text subtitles, made in the
background in data/cache/travel (roughly 1 GB per hour of video). A copy is deleted two weeks after
it's made, or with Server → Library → Free up space.
"""
import hashlib
import os
import re
import subprocess
import threading
import time

from . import config, media, store

CACHE = os.path.join(config.DATA_DIR, "cache", "travel")
KEEP_DAYS = 14
_lock = threading.Lock()
_queue = []
_jobs = {}                   # key -> {"state": "queued" | "working" | "failed", "progress", "error"}
_wake = threading.Event()


def _key(item):
    st = os.stat(item["path"])
    return hashlib.sha1(("travel1|%s|%d|%d" % (item["path"], st.st_size, int(st.st_mtime))).encode()).hexdigest()[:20]


def copy_path(item):
    try:
        p = os.path.join(CACHE, _key(item) + ".mp4")
    except OSError:
        return None
    return p if os.path.isfile(p) else None


def status(item):
    p = copy_path(item)
    if p:
        return {"state": "ready", "size": os.path.getsize(p)}
    try:
        k = _key(item)
    except OSError:
        return {"state": "none"}
    with _lock:
        job = _jobs.get(k)
        return dict(job) if job else {"state": "none"}


def want(item):
    """Make a travel copy of this video (one at a time, in the background)."""
    k = _key(item)
    with _lock:
        if k in _jobs and _jobs[k]["state"] in ("queued", "working"):
            return
        _jobs[k] = {"state": "queued", "progress": 0}
        _queue.append(item)
    _wake.set()


def _command(item, info, part, with_subs=True):
    exe = media.tool("ffmpeg")
    video, audio = info.get("video"), media.default_audio(info)
    cmd = ["nice", "-n", "12", exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", item["path"]]
    sidecar_subs = [s for s in item.get("subs") or [] if with_subs and os.path.isfile(s.get("path") or "")
                    and s["path"].lower().endswith((".srt", ".vtt", ".ass", ".ssa"))][:3]
    for s in sidecar_subs:
        cmd += ["-i", s["path"]]
    cmd += ["-map", "0:%d" % video["index"]] + (["-map", "0:%d" % audio["index"]] if audio else [])
    inside = [s for s in info.get("subs") or [] if with_subs and s.get("codec") in media.TEXT_SUBS][:3]
    langs = []
    for s in inside:
        cmd += ["-map", "0:%d" % s["index"]]
        langs.append(s.get("lang"))
    for n, s in enumerate(sidecar_subs, 1):
        cmd += ["-map", "%d:0" % n]
        langs.append(s.get("lang"))
    filters = (["yadif"] if video.get("interlaced") else []) + ["scale=-2:'min(720,ih)'", "format=yuv420p"]
    if "libx264" in media.encoders():
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "high", "-level", "4.0"]
    else:
        enc = media.h264_args(720, live=False)
    cmd += ["-vf", ",".join(filters)] + enc
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-ac", "2"]
    if langs:
        cmd += ["-c:s", "mov_text"]
        for n, lang in enumerate(langs):
            if lang:
                cmd += ["-metadata:s:s:%d" % n, "language=%s" % lang]
    return cmd + ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", "-f", "mp4", part]


def _make(item, k):
    info = media.probe(item["path"]) or {}
    if not info.get("video"):
        raise ValueError("there's no video in this file")
    if not media.tool("ffmpeg"):
        raise ValueError("ffmpeg isn't installed on the Sofa computer")
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, k + ".mp4")
    part = dest + ".part"
    total = info.get("duration") or 0
    for with_subs in (True, False):                  # a broken subtitle file mustn't sink the whole copy
        proc = subprocess.Popen(_command(item, info, part, with_subs), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            m = re.match(r"out_time_(?:us|ms)=(\d+)", line.strip())
            if m and total:
                with _lock:
                    _jobs[k]["progress"] = min(0.99, int(m.group(1)) / 1e6 / total)
        err = proc.stderr.read()
        if proc.wait() == 0 and os.path.exists(part):
            os.replace(part, dest)
            return
        if os.path.exists(part):
            os.remove(part)
    raise RuntimeError((err.strip().splitlines() or ["ffmpeg stopped"])[-1][:200])


def _prune():
    cut = time.time() - KEEP_DAYS * 86400
    try:
        for n in os.listdir(CACHE):
            p = os.path.join(CACHE, n)
            if n.endswith(".part") or os.path.getmtime(p) < cut:
                os.remove(p)
    except OSError:
        pass


def _loop():
    _prune()
    pruned = time.time()
    while True:
        _wake.wait(3600)
        _wake.clear()
        if time.time() - pruned > 86400:
            _prune()
            pruned = time.time()
        while True:
            with _lock:
                item = _queue.pop(0) if _queue else None
            if not item:
                break
            while media.should_wait():               # someone is watching something converted live: they come first
                time.sleep(20)
            k = _key(item)
            with _lock:
                _jobs[k]["state"] = "working"
            try:
                _make(item, k)
                with _lock:
                    _jobs.pop(k, None)
            except Exception as exc:
                with _lock:
                    _jobs[k] = {"state": "failed", "error": str(exc)[:200]}
                if item.get("adult"):
                    store.log_private("error", "Couldn't make a travel copy of a private video")
                else:
                    store.log("error", "Couldn't make a travel copy of %s: %s" % (os.path.basename(item["path"]), exc))


def start():
    threading.Thread(target=_loop, daemon=True, name="travel").start()
