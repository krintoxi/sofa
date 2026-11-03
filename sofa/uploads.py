"""Sending files to the Inbox from any device: a phone's videos, a laptop's downloads.

The file arrives in pieces into data/cache/uploads (so the Inbox never sees half a file), and only
when every byte is there does it move into the Inbox (or Inbox/XXX), where Sofa files it as usual.
Admins only, at home or over Tailscale.
"""
import os
import re
import shutil
import threading
import uuid

from . import config, fileops, naming, store

STAGING = os.path.join(config.DATA_DIR, "cache", "uploads")
CHUNK = 1024 * 1024
SPARE = 2 * 1024 ** 3        # leave this much free on the disk
ALLOWED = tuple(naming.VIDEO_EXT) + (".srt", ".vtt", ".ass", ".ssa", ".sub", ".idx", ".nfo", ".jpg", ".jpeg", ".png",
                              ".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg", ".opus", ".alac", ".aif", ".aiff")
_lock = threading.Lock()
_active = {}                 # upload id -> {"name", "size", "got"}


def safe_name(name):
    name = os.path.basename(str(name or "").replace("\\", "/")).strip()
    name = re.sub(r"[\x00-\x1f/:*?\"<>|]+", " ", name).strip(" .")
    return name[:180] or "upload"


def check(name, size, adult):
    """A reason this upload can't be taken, or None. (Called with _lock held: the room the uploads already coming in
    still need is counted, so several at once can't promise the same free space twice.)"""
    if os.path.splitext(name)[1].lower() not in ALLOWED:
        return "Sofa takes videos, music, subtitles and pictures. %s isn't one of those." % name
    most = float(config.get("upload_max_gb") or 0)
    if most and size > most * 1024 ** 3:
        return "That's bigger than this Sofa takes from the app (%g GB). Copy it to the Inbox folder instead." % most
    if len(_active) >= int(config.get("uploads_at_once") or 3):
        return "%d files are being sent already. Send this one when they're done." % len(_active)
    inbox = config.path("inbox")
    os.makedirs(inbox, exist_ok=True)
    os.makedirs(STAGING, exist_ok=True)
    free = min(shutil.disk_usage(inbox).free, shutil.disk_usage(STAGING).free)
    coming = sum(a["size"] - a["got"] for a in _active.values())
    if size + coming + SPARE > free:
        return "There isn't room on the Sofa computer for that (%d GB free%s)." % (
            free // 1024 ** 3, ", with what's being sent now" if coming else "")
    return None


def receive(stream, name, size, adult, who):
    """Read `size` bytes from `stream` into the Inbox as `name`. Returns where it went (raises on failure)."""
    name = safe_name(name)
    uid = uuid.uuid4().hex[:12]
    part = os.path.join(STAGING, uid + ".part")
    with _lock:                                     # checked and counted in one step
        problem = check(name, size, adult)
        if problem:
            raise ValueError(problem)
        _active[uid] = {"name": "Private file" if adult else name, "size": size, "got": 0}
    try:
        with open(part, "wb") as f:
            left = size
            while left > 0:
                chunk = stream.read(min(CHUNK, left))
                if not chunk:
                    raise ConnectionError("the upload stopped before the end")
                f.write(chunk)
                left -= len(chunk)
                with _lock:
                    _active[uid]["got"] = size - left
        folder = os.path.join(config.path("inbox"), "XXX") if adult else config.path("inbox")
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, name)
        stem, ext = os.path.splitext(name)
        n = 2
        while os.path.exists(dest):
            dest = os.path.join(folder, "%s (%d)%s" % (stem, n, ext))
            n += 1
        fileops.move(part, dest)
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise
    finally:
        with _lock:
            _active.pop(uid, None)
    if adult:
        store.log_private("inbox", "%s sent a file to the Inbox (Adult)" % who, {"file": name})
    else:
        store.log("inbox", "%s sent \"%s\" to the Inbox from the app" % (who, name))
    return dest


def status():
    with _lock:
        return [dict(v) for v in _active.values()]


def clean():
    """Pieces of uploads that never finished (Sofa restarted in the middle)."""
    try:
        for n in os.listdir(STAGING):
            if n.endswith(".part"):
                os.remove(os.path.join(STAGING, n))
    except OSError:
        pass
