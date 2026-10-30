"""Artwork at the size a screen needs.

Posters and episode stills are often 1000-2000 px wide and 200-400 KB. A TV stick or
phone showing a row of them only needs 360-480 px. `/art/...?w=360` serves a resized
copy, made once with ffmpeg and kept in data/cache/thumbs. The originals are never
touched. A background pass after each library scan prepares the common sizes.
"""
import hashlib
import os
import threading
import time

from . import config, media, music

WIDTHS = (240, 360, 480, 720, 1280)
CACHE = os.path.join(config.DATA_DIR, "cache", "thumbs")
_slots = threading.BoundedSemaphore(2)          # the iMac is old: two resizes at a time at most
_warming = threading.Lock()


def file_for(url):
    """The image file behind an /art/<key>/<path> URL, or None."""
    if not url or not url.startswith("/art/"):
        return None
    key, _, rel = url[len("/art/"):].partition("/")
    if key not in ("shows", "movies", "music", "musicvideos", "adult", "cache"):
        return None
    root = music.ART_CACHE if key == "cache" else config.path(key)
    rel = os.path.normpath(rel)
    full = os.path.join(root, rel)
    if rel.startswith("..") or os.path.splitext(full)[1].lower() not in (".jpg", ".jpeg", ".png", ".webp") \
            or not os.path.isfile(full):
        return None
    return full


def resized(full, width, wait=True):
    """Path of `full` scaled to at most `width` px wide (same format), or the original if that fails."""
    if width not in WIDTHS:
        return full
    if not (os.access(media.SIPS, os.X_OK) or media.tool("ffmpeg")):
        return full
    st = os.stat(full)
    ext = ".png" if full.lower().endswith(".png") else ".jpg"    # logos keep their transparency
    key = hashlib.sha1(("v2|%s|%d|%d|%d" % (full, st.st_size, int(st.st_mtime), width)).encode()).hexdigest()[:24]
    dest = os.path.join(CACHE, key + ext)
    if os.path.exists(dest):
        return dest
    if not _slots.acquire(blocking=wait, timeout=20 if wait else -1):
        return full
    try:
        if os.path.exists(dest):
            return dest
        os.makedirs(CACHE, exist_ok=True)
        return dest if media.save_image(full, dest, width, "png" if ext == ".png" else "jpeg") else full
    finally:
        _slots.release()


def warm(library):
    """Prepare the sizes the web app asks for, slowly, in the background."""
    if not _warming.acquire(blocking=False):
        return
    try:
        lib, tunes = library.public(adult=True), library.music_public()
        jobs = []
        for show in lib["shows"] + lib["adult"]["shows"]:
            jobs += [(show.get("poster"), 360), (show.get("backdrop"), 1280), (show.get("logo"), 720)]
            for season in show["seasons"]:
                jobs.append((season.get("poster"), 360))
                jobs += [(ep.get("thumb"), 480) for ep in season["episodes"]]
            jobs += [(x.get("thumb"), 480) for x in show["extras"]]
        for m in lib["movies"] + lib["adult"]["movies"]:
            jobs += [(m.get("poster"), 360), (m.get("backdrop"), 1280)]
        for a in tunes["albums"] + tunes["artists"]:
            jobs.append((a.get("art"), 360))
        jobs += [(v.get("thumb"), 480) for v in tunes["videos"]]
        seen = set()
        for url, width in jobs:
            full = file_for(url)
            if not full or (full, width) in seen:
                continue
            seen.add((full, width))
            resized(full, width)
            time.sleep(0.05)
    finally:
        _warming.release()
