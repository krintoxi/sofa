"""Where the library lives: the main folders (~/Entertainment/...), plus library folders on other
drives plugged into this computer (flash drives, external SSDs and disks).

Each extra place is a folder on a drive with the same layout as the main one:

    /Volumes/My SSD/Sofa Library/
        Shows/  Movies/  Adult/  Music/  Music Videos/
        .sofa-library.json        (name and id, so the drive is recognised again later)

Sofa reads every connected place and shows one library: a show with Season 1 here and
Season 2 on a drive is one show. A drive that's unplugged just drops out until it's back
(watch progress isn't lost). The Inbox files new things into the place chosen under
Server → Storage; new episodes of a show that's already on a drive go to that drive.
"""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time

from . import config, store

SECTIONS = {"shows": "Shows", "movies": "Movies", "adult": "Adult", "music": "Music", "musicvideos": "Music Videos"}
MARKER = ".sofa-library.json"
DEFAULT_FOLDER = "Sofa Library"
_lock = threading.Lock()


# ---------------------------------------------------------------- the places

def main_base():
    """The folder that holds the main Shows/, Movies/, ... (normally ~/Entertainment)."""
    return os.path.dirname(config.path("shows"))


def extra():
    return [p for p in (config.get("places") or []) if p.get("id") and p.get("path")]


def connected(place):
    return os.path.isdir(place["path"])


def section(key, place=None):
    """The Shows/Movies/... folder of a place (None: the main one)."""
    if not place:
        return config.path(key)
    return os.path.join(place["path"], SECTIONS[key])


def roots(key):
    """[(art key, folder)] for a section: the main folder first, then each connected drive's."""
    out = [(key, config.path(key))]
    for p in extra():
        d = section(key, p)
        if os.path.isdir(d):
            out.append(("%s~%s" % (key, p["id"]), d))
    return out


def folder_for(art_key):
    """The folder behind an art key ("shows", "movies~a1b2c3")."""
    key, _, pid = art_key.partition("~")
    if key not in SECTIONS:
        return None
    if not pid:
        return config.path(key)
    p = by_id(pid)
    return section(key, p) if p else None


def by_id(pid):
    return next((p for p in extra() if p["id"] == pid), None)


def place_of(path):
    """The extra place a file or folder is in, or None for the main library."""
    a = os.path.abspath(path)
    for p in extra():
        if a == os.path.abspath(p["path"]) or a.startswith(os.path.abspath(p["path"]) + os.sep):
            return p
    return None


def base_of(path):
    """The folder holding the sections for the place `path` is in (for Deleted/ and Converted Originals/)."""
    p = place_of(path)
    return p["path"] if p else main_base()


def target():
    """Where new things from the Inbox go: the place chosen under Server → Storage, if it's connected."""
    pid = config.get("file_new_to") or ""
    p = by_id(pid) if pid else None
    return p if p and connected(p) else None


def all_section_roots(keys=("shows", "movies", "adult")):
    return [os.path.abspath(d) for k in keys for _ak, d in roots(k)]


# ---------------------------------------------------------------- drives plugged into this computer

def _mount_types():
    """{mount point: filesystem type} from `mount` (macOS: "(exfat, local, ...)"; Linux: "type exfat")."""
    out = {}
    try:
        text = subprocess.run(["mount"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return out
    for line in text.splitlines():
        m = re.match(r"^.+? on (.+?) \(([^,)]+)", line) or re.match(r"^.+? on (.+?) type (\S+)", line)
        if m:
            out[m.group(1)] = m.group(2).lower()
    return out


def _drive_folders():
    setting = config.get("drive_folders")
    if setting:
        return [os.path.expanduser(x) for x in setting]
    if platform.system() == "Darwin":
        return ["/Volumes"]
    user = os.environ.get("USER") or ""
    return ["/media/" + user, "/run/media/" + user, "/media", "/mnt"]


def _writable(path):
    try:
        fd, name = tempfile.mkstemp(prefix=".sofa-check-", dir=path)
        os.close(fd)
        os.remove(name)
        return True
    except OSError:
        return False


def drives():
    """Drives Sofa can see, with what it knows about each."""
    types, seen, out = _mount_types(), set(), []
    for folder in _drive_folders():
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if name.startswith(".") or not os.path.isdir(path) or os.path.realpath(path) == "/" or path in seen \
                    or path in _drive_folders():          # /media/<you> holds drives; it isn't one
                continue
            seen.add(path)
            d = {"name": name, "path": path, "fs": types.get(path, ""), "problem": None}
            try:
                du = shutil.disk_usage(path)
                d.update(total=du.total, free=du.free)
                os.listdir(path)
            except PermissionError:
                d["problem"] = "no-permission"
            except OSError as exc:
                d["problem"] = exc.strerror or str(exc)
            if not d["problem"]:
                d["writable"] = _writable(path)
                if not d["writable"]:
                    d["problem"] = "read-only"
            d["fat32"] = d["fs"] in ("msdos", "vfat", "fat32", "fat")
            lib = os.path.join(path, DEFAULT_FOLDER)
            d["existing"] = lib if os.path.isfile(os.path.join(lib, MARKER)) else None
            d["in_use"] = any(os.path.abspath(p["path"]).startswith(os.path.abspath(path) + os.sep) or
                              os.path.abspath(p["path"]) == os.path.abspath(path) for p in extra())
            out.append(d)
    return out


# ---------------------------------------------------------------- adding and removing places

def add(path, name=None, new_here=False):
    """Use a folder on a drive as a library place (made if needed, with the usual folders inside)."""
    path = os.path.abspath(os.path.expanduser(path))
    if not path or path == "/" or not os.path.isdir(os.path.dirname(path)):
        raise ValueError("That folder isn't on a drive Sofa can see.")
    if any(os.path.abspath(p["path"]) == path for p in extra()):
        raise ValueError("Sofa already uses that folder.")
    if path.startswith(main_base() + os.sep) or main_base().startswith(path + os.sep):
        raise ValueError("That's inside the main library already.")
    marker = os.path.join(path, MARKER)
    info = {}
    try:
        with open(marker, encoding="utf-8") as f:
            info = json.load(f)                  # a drive that was a Sofa library before: keep its id
    except (OSError, ValueError):
        pass
    try:
        for folder in SECTIONS.values():
            os.makedirs(os.path.join(path, folder), exist_ok=True)
        pid = info.get("id") or hashlib.sha1(("%s|%s" % (path, time.time())).encode()).hexdigest()[:8]
        name = (name or info.get("name") or os.path.basename(os.path.dirname(path)) or "Drive").strip()[:40]
        with open(marker, "w", encoding="utf-8") as f:
            json.dump({"id": pid, "name": name, "made": info.get("made") or int(time.time())}, f)
    except PermissionError:
        raise ValueError(permission_help())
    except OSError as exc:
        raise ValueError("Couldn't make the library folders there: %s" % (exc.strerror or exc))
    with _lock:
        places = [p for p in extra() if p["id"] != pid] + [{"id": pid, "name": name, "path": path}]
        changes = {"places": places}
        if new_here:
            changes["file_new_to"] = pid
        config.update(changes)
    store.log("settings", "Started using %s (%s) for the library" % (name, path))
    return pid


def remove(pid):
    """Stop using a place. Nothing on the drive is touched."""
    p = by_id(pid)
    if not p:
        return
    with _lock:
        changes = {"places": [x for x in extra() if x["id"] != pid]}
        if config.get("file_new_to") == pid:
            changes["file_new_to"] = ""
        config.update(changes)
    store.log("settings", "Stopped using %s for the library (its files are still on the drive)" % p["name"])


def set_target(pid):
    if pid and not by_id(pid):
        raise ValueError("That drive isn't one Sofa uses.")
    config.update({"file_new_to": pid or ""})


def permission_help():
    import sys
    if platform.system() == "Darwin":
        return ("macOS isn't letting Sofa open this drive. Open System Settings → Privacy & Security → "
                "Full Disk Access, press +, press Command-Shift-G and paste %s, add it and switch it on. "
                "Then restart Sofa (Server → Updates has the command) and try again." % sys.executable)
    return "Sofa isn't allowed to open this drive. Check its permissions (the user running Sofa needs to read and write it)."


def status(library):
    """Every place with its space and what's on it, for Server → Storage."""
    counts = library.place_counts() if hasattr(library, "place_counts") else {}
    try:
        du = shutil.disk_usage(main_base())
        main_space = {"total": du.total, "free": du.free}
    except OSError:
        main_space = {}
    out = [dict({"id": "", "name": "This computer", "path": main_base(), "connected": True, "main": True,
                 "counts": counts.get("", {})}, **main_space)]
    for p in extra():
        d = {"id": p["id"], "name": p["name"], "path": p["path"], "connected": connected(p), "counts": counts.get(p["id"], {})}
        if d["connected"]:
            try:
                du = shutil.disk_usage(p["path"])
                d.update(total=du.total, free=du.free)
            except OSError:
                pass
        out.append(d)
    return {"places": out, "new_to": (target() or {}).get("id", ""), "drives": [d for d in drives() if not d["in_use"]],
            "transfers": transfers()}


# ---------------------------------------------------------------- moving a title to another place

_transfers = []          # [{"id", "title", "from", "to", "state", "done", "total", "error"}]


def transfers():
    with _lock:
        return [dict(t) for t in _transfers[-12:]]


def _size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(d, f)) for d, _s, fs in os.walk(path) for f in fs)


def move(folder, key, to_pid, title, private=False):
    """Move a show's or a movie's folder to another place, in the background: copy, check, then remove
    the original. `key`: the section ("shows", "movies", "adult")."""
    src_place = place_of(folder)
    dest_place = by_id(to_pid) if to_pid else None
    if to_pid and not dest_place:
        raise ValueError("That drive isn't one Sofa uses.")
    if dest_place and not connected(dest_place):
        raise ValueError("%s isn't plugged in." % dest_place["name"])
    if (src_place or {}).get("id") == (dest_place or {}).get("id"):
        raise ValueError("It's already there.")
    src_root = section(key, src_place)
    rel = os.path.relpath(folder, src_root)
    if rel.startswith(".."):
        raise ValueError("Sofa can only move things that are in the library.")
    dest = os.path.join(section(key, dest_place), rel)
    if os.path.exists(dest):
        raise ValueError("There's already a folder with that name there.")
    total = _size(folder)
    free = shutil.disk_usage(os.path.dirname(section(key, dest_place)) if dest_place else main_base()).free
    if total > free - 512 * 1024 * 1024:
        raise ValueError("There isn't enough room there (%d GB needed, %d GB free)." % (total // 10**9 + 1, free // 10**9))
    job = {"id": hashlib.sha1(("%s|%s" % (folder, time.time())).encode()).hexdigest()[:8], "title": "A private title" if private else title,
           "from": (src_place or {}).get("name", "This computer"), "to": (dest_place or {}).get("name", "This computer"),
           "state": "copying", "done": 0, "total": total, "error": None, "at": int(time.time())}
    with _lock:
        _transfers.append(job)
    threading.Thread(target=_move, args=(job, folder, dest, private), daemon=True, name="move-title").start()
    return job["id"]


def _move(job, src, dest, private):
    tmp = dest + ".sofa-moving"
    try:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        for d, dirs, files in os.walk(src):
            out = os.path.join(tmp, os.path.relpath(d, src))
            os.makedirs(out, exist_ok=True)
            for f in files:
                s, t = os.path.join(d, f), os.path.join(out, f)
                with open(s, "rb") as a, open(t, "wb") as b:
                    while True:
                        chunk = a.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        b.write(chunk)
                        with _lock:
                            job["done"] += len(chunk)
                shutil.copystat(s, t)
        with _lock:
            job["state"] = "checking"
        if _size(tmp) != _size(src):
            raise OSError("the copy isn't the same size as the original")
        os.rename(tmp, dest)
        shutil.rmtree(src)
        with _lock:
            job.update(state="done", done=job["total"])
        msg = "Moved %s from %s to %s" % (job["title"], job["from"], job["to"])
        (store.log_private("library", "Moved a private title from %s to %s" % (job["from"], job["to"]), {"from": src, "to": dest})
         if private else store.log("library", msg, {"from": src, "to": dest}))
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        with _lock:
            job.update(state="failed", error=str(getattr(exc, "strerror", None) or exc)[:200])
        store.log("error", "Moving %s to %s didn't work: %s (the original is where it was)" % (job["title"], job["to"], job["error"]))
    finally:
        from .library import LIBRARY
        threading.Thread(target=LIBRARY.scan, args=("moved between drives",), daemon=True).start()
