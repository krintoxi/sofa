"""Save this disc: a DVD or CD in the computer's disc drive, into the library, as files like any others.

Put a disc in a drive (built in, or on USB) and the Server page shows what it is, what's on it, and Save:

  a music CD     each track becomes a FLAC file (every bit of the disc's sound: checked against what was read),
                 named and tagged, in Music/<Artist>/<Album>/.
  a video DVD    the titles you pick become MKV files with the disc's own picture and sound as they are (nothing
                 is converted), every sound and subtitle track, and its chapters: Movies/<Title (Year)>/, or
                 Shows/<Show>/Season N/ as episodes.
  a data disc    the videos, music and subtitles on it are copied to the Inbox, where Sofa files them as usual.

Copy-protected discs are not saved. A commercial DVD's video is scrambled (CSS) and so is a Blu-ray's (AACS); Sofa
has nothing that undoes either and doesn't fetch or call anything that does (in the United States that would be
circumvention, 17 U.S.C. 1201, whoever owns the disc). It notices, says so, and stops. See sofa/dvd.py for how it
tells, and for the one function that reads a title (`dvd.read_title`).

Who does what: Sofa's own code reads the disc (sofa/dvd.py, sofa/cdaudio.py, sofa/iso9660.py). ffmpeg, which Sofa
already needs, only packs what was read: a title's stream into an MKV, a track's sound into FLAC.

While a disc is being saved the drive is only read, and shared: nothing is locked, unmounted or ejected, so it can
still be played. A disc or drive pulled out in the middle ends that save with a plain message; what was already
finished stays, what was half done is removed. Nothing is ever written over a file that's there.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from . import cdaudio, config, dvd, fileops, iso9660, languages, media, naming, store

PROTECTED = ("This %s is copy-protected, so Sofa can't read its video. Already have it as a folder or a disc image? "
             "Save from a folder or disc image files it like any other.")
WONT_READ = ("The drive won't hand over this disc's video, as happens with a copy-protected disc, so Sofa can't read it. "
             "Already have it as a folder or a disc image? Save from a folder or disc image files it like any other.")
BLURAY = ("Sofa doesn't save Blu-ray discs. Nearly all of them are copy-protected, and Sofa doesn't get round copy "
          "protection (in the United States that's against the law, even for a disc you own).")
GONE = "The disc or the drive went away before it was done. What was already saved is kept; the rest wasn't."
SPARE = 1024 ** 3
ART = os.path.join(config.DATA_DIR, "cache", "disc-art")
PLAYS = os.path.join(config.DATA_DIR, "cache", "disc-play")
KINDS = {"cd": "music CD", "dvd": "DVD", "bluray": "Blu-ray", "data": "data disc"}
saved = None                # called after a save, so the library is read again (web.py sets it)

_lock = threading.Lock()
_known = {}                 # drive id -> {"key", "disc"}: what was read from the disc that's in it
_jobs = []                  # the saves, newest last
_sources = {}               # drive id -> what's open on it while it's described or saved


def _media_ext():
    from . import music
    return set(naming.VIDEO_EXT) | set(music.AUDIO_EXT) | set(naming.SUB_EXT)


# ---------------------------------------------------------------- the drives, and what's in them

def _run(cmd, timeout=8):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return out.returncode, out.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _kind_of(source):
    try:
        top = {n.upper(): is_dir for n, (is_dir, _) in source.names("").items()}
    except OSError:
        return None
    if top.get("VIDEO_TS"):
        return "dvd"
    if top.get("BDMV") or top.get("AACS"):
        return "bluray"
    return "data"


def _mac_drives():
    out = []
    code, text = _run(["/sbin/mount"])
    for line in text.splitlines():
        m = re.match(r"^(/dev/\S+) on (.+) \((cddafs|cd9660|udf)\b", line)
        if not m:
            continue
        dev, mount, fs = m.groups()
        whole = re.sub(r"s\d+$", "", dev)
        if any(d["dev"] == whole for d in out):
            continue                                        # (a DVD can show up twice: the same disc)
        kind = "cd" if fs == "cddafs" else _kind_of(iso9660.Folder(mount))
        out.append({"id": os.path.basename(whole), "dev": whole, "mount": mount, "name": "Disc drive", "state": "disc",
                    "kind": kind, "label": os.path.basename(mount)})
    code, text = _run(["/usr/bin/drutil", "status"], 6)
    if code == 0 and "Vendor" in text:
        lines = [x for x in text.splitlines() if x.strip()]
        name = " ".join(lines[1].split()[:-1]) if len(lines) > 1 else "Disc drive"
        m = re.search(r"Name:\s*(/dev/disk\d+)", text)
        if m and any(d["dev"] == m.group(1) for d in out):
            next(d for d in out if d["dev"] == m.group(1))["name"] = name
        elif "No Media" in text:
            out.append({"id": "drive", "dev": None, "mount": None, "name": name, "state": "empty", "kind": None, "label": ""})
        elif m:                                             # something's in it that the Mac didn't open
            out.append({"id": os.path.basename(m.group(1)), "dev": m.group(1), "mount": None, "name": name, "state": "unread",
                        "kind": None, "label": ""})
    return out


def _linux_mounts():
    found = {}
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 1:
                    found.setdefault(os.path.realpath(parts[0]), parts[1].replace("\\040", " "))
    except OSError:
        pass
    return found


def _read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _linux_drives(sys_block="/sys/block"):
    out, mounts = [], _linux_mounts()
    try:
        names = sorted(n for n in os.listdir(sys_block) if re.match(r"^sr\d+$", n))
    except OSError:
        names = []
    for n in names:
        dev = "/dev/" + n
        name = (" ".join([_read_text("%s/%s/device/vendor" % (sys_block, n)), _read_text("%s/%s/device/model" % (sys_block, n))])).strip()
        d = {"id": n, "dev": dev, "mount": mounts.get(dev), "name": name or "Disc drive", "state": "disc", "kind": None, "label": ""}
        status = cdaudio.linux_status(dev)
        if status in ("empty", "open", None):
            d["state"] = "empty" if status else "unread"
        elif status == "audio":
            d["kind"], d["label"] = "cd", "Music CD"
        else:
            try:
                source = iso9660.Folder(d["mount"]) if d["mount"] else iso9660.Image(dev)
                d["kind"], d["label"] = _kind_of(source), source.label
                source.close()
            except (OSError, ValueError):
                if status == "mixed":
                    d["kind"], d["label"] = "cd", "Music CD"
                else:
                    d["state"] = "unread"
        out.append(d)
    return out


def _windows_drives():
    import ctypes
    out = []
    k = ctypes.windll.kernel32
    bits = k.GetLogicalDrives()
    for i in range(26):
        letter = chr(65 + i)
        root = letter + ":\\"
        if not bits >> i & 1 or k.GetDriveTypeW(root) != 5:      # DRIVE_CDROM
            continue
        d = {"id": letter, "dev": letter, "mount": root, "name": "Disc drive (%s:)" % letter, "state": "disc", "kind": None, "label": ""}
        try:
            names = os.listdir(root)
        except OSError:
            d["state"], d["mount"] = "empty", None
            out.append(d)
            continue
        label = ctypes.create_unicode_buffer(261)
        if k.GetVolumeInformationW(root, label, 261, None, None, None, None, 0):
            d["label"] = label.value
        if names and all(n.lower().endswith(".cda") for n in names):
            d["kind"], d["label"] = "cd", d["label"] or "Music CD"
        else:
            d["kind"] = _kind_of(iso9660.Folder(root))
        out.append(d)
    return out


def _made_drives():
    """Disc images and folders to treat as drives with a disc in: the ones added from the Server page (Save from a
    folder or disc image: config "disc_sources"), and SOFA_DISCS, paths separated like PATH (for trying Save this disc
    with no drive: the tests and the pictures do)."""
    out = []
    env = [("image%d" % (n + 1), p, False) for n, p in enumerate([p for p in (os.environ.get("SOFA_DISCS") or "").split(os.pathsep) if p])]
    added = [("copy-" + hashlib.sha1(p.encode("utf-8")).hexdigest()[:8], p, True) for p in config.get("disc_sources") or [] if isinstance(p, str)]
    for did, path, copy in env + added:
        if copy and not os.path.exists(path):
            continue                                        # (a drive that's unplugged, a folder moved: back when it's there)
        d = {"id": did, "dev": path, "mount": path if os.path.isdir(path) else None, "name": "Folder" if os.path.isdir(path) else "Disc image",
             "state": "disc", "kind": None, "label": os.path.splitext(os.path.basename(path.rstrip("/\\")))[0], "image": True, "copy": copy}
        try:
            if path.lower().endswith(".cue") or (os.path.isdir(path) and any(x.lower().endswith((".aiff", ".aif")) for x in os.listdir(path))):
                d["kind"] = "cd"
            else:
                source = dvd.open_source(path)
                d["kind"], d["label"] = _kind_of(source), source.label
                source.close()
        except (OSError, ValueError):
            d["state"] = "unread"
        out.append(d)
    return out


def source_path(path):
    """A folder or disc image to save from, as Sofa will read it: a DVD's folder (the one holding VIDEO_TS, or VIDEO_TS
    itself), a music CD's .cue, or an .iso. Raises ValueError with what's wrong."""
    path = os.path.abspath(os.path.expanduser(str(path or "").strip().strip('"')))
    if not path or not os.path.exists(path):
        raise ValueError("There's nothing at %s." % (path or "that place"))
    if os.path.isdir(path):
        if os.path.basename(path.rstrip("/\\")).upper() == "VIDEO_TS":
            path = os.path.dirname(path.rstrip("/\\"))
        names = {n.upper() for n in os.listdir(path)}
        if "VIDEO_TS" not in names and not any(n.endswith((".AIFF", ".AIF")) for n in names):
            raise ValueError("That folder has no VIDEO_TS folder in it: pick the folder a DVD was copied to.")
        return path
    if not path.lower().endswith((".iso", ".img", ".cue")):
        raise ValueError("Sofa reads a DVD's folder, an .iso disc image or a music CD's .cue.")
    return path


def add_source(path):
    """Save from a folder or disc image: it shows as a disc in a drive, until it's taken away."""
    path = source_path(path)
    have = [p for p in config.get("disc_sources") or [] if isinstance(p, str)]
    if path not in have:
        config.update({"disc_sources": (have + [path])[-10:]})
    return {"ok": True, "drive": "copy-" + hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]}


def remove_source(drive_id):
    have = [p for p in config.get("disc_sources") or [] if isinstance(p, str)]
    left = [p for p in have if "copy-" + hashlib.sha1(p.encode("utf-8")).hexdigest()[:8] != drive_id]
    config.update({"disc_sources": left})
    return {"ok": len(left) < len(have)}


def drives():
    """The disc drives on this computer and what's in each: [{"id", "name", "state": "empty" | "disc" | "unread",
    "kind": "cd" | "dvd" | "bluray" | "data" | None, "label", "dev", "mount"}]."""
    try:
        found = _mac_drives() if sys.platform == "darwin" else _windows_drives() if os.name == "nt" else _linux_drives()
    except Exception:
        found = []
    return found + _made_drives()


def _open_video(d):
    """A DVD's or data disc's files: from where it's mounted, else from the drive itself."""
    if d.get("mount"):
        return iso9660.Folder(d["mount"], d.get("label"))
    if d.get("image"):
        return iso9660.Image(d["dev"])
    if os.name == "nt":
        return iso9660.Image("\\\\.\\%s:" % d["dev"])
    try:
        return iso9660.Image(d["dev"])
    except (OSError, ValueError):
        if shutil.which("udisksctl"):                       # a Sofa Box: ask for it to be mounted, as Files does
            code, out = _run(["udisksctl", "mount", "--no-user-interaction", "-b", d["dev"]], 30)
            m = re.search(r" at (/\S+?)\.?\s*$", out)
            mount = m.group(1) if m else _linux_mounts().get(d["dev"])
            if mount and os.path.isdir(mount):
                d["mount"] = mount
                return iso9660.Folder(mount, d.get("label"))
        raise


def _open_cd(d):
    if d.get("image"):
        return cdaudio.CueBin(d["dev"]) if not os.path.isdir(d["dev"]) else cdaudio.MacVolume(d["dev"])
    if sys.platform == "darwin":
        return cdaudio.MacVolume(d["mount"])
    if os.name == "nt":
        return cdaudio.WindowsDrive(d["dev"])
    return cdaudio.LinuxDrive(d["dev"])


def _copyright(d):
    """The disc's own word on copy protection, where the computer lets Sofa ask the drive (see cdaudio)."""
    if d.get("image") or not d.get("dev"):
        return None
    if os.name == "nt":
        return cdaudio.windows_copyright(d["dev"])
    if sys.platform.startswith("linux"):
        return cdaudio.linux_copyright(d["dev"])
    return None


def _describe(d):
    """Read what's on the disc in drive `d` (seconds on a real drive: done once a disc, in the background)."""
    out = {"kind": d["kind"], "label": d["label"], "protected": False, "problem": None}
    if d["kind"] == "bluray":
        out.update(protected=True, problem=BLURAY)
    elif d["kind"] == "cd":
        cd = _open_cd(d)
        try:
            text = cd.text() or {}
            out["tracks"] = [{"n": t["n"], "seconds": round(cd.seconds(t), 1), "title": (text.get("titles") or {}).get(t["n"], "")}
                             for t in cd.tracks]
            out["artist"], out["album"] = text.get("artist") or "", text.get("album") or ""
            out["named"] = bool(text.get("titles") or out["album"])
            out["label"] = out["album"] or d["label"] or "Music CD"
            out["_cd_tracks"] = list(cd.tracks)
            out["_addresses"] = getattr(cd, "addresses", None) or ([t["start"] for t in cd.tracks], cd.leadout)
        finally:
            cd.close()
        if not out["tracks"]:
            out["problem"] = "There's no music on this disc that Sofa can read."
    elif d["kind"] == "dvd":
        source = _open_video(d)
        try:
            info = dvd.titles(source)
            out["label"] = info["label"] or d["label"]
            out["_titles"] = info["titles"]
            out["titles"] = [dvd.public(t) for t in info["titles"] if t["seconds"] >= 1]
            said = _copyright(d)
            if said:
                out.update(protected=True, problem=PROTECTED % "DVD")
            else:
                for t in sorted([t for t in info["titles"] if not t["cant"]], key=lambda t: -t["seconds"])[:3]:
                    found = dvd.sample(source, t)
                    if found:
                        out.update(protected=True, problem=PROTECTED % "DVD" if found == "protected" else WONT_READ)
                        break
            if not out["titles"] and not out["problem"]:
                out["problem"] = "There's nothing on this DVD to save."
            out["guess"] = _guess(out["label"])
            if out["guess"].get("found"):                   # the film, free to keep from the Internet Archive?
                try:
                    from . import freecopy
                    out["free"] = freecopy.find(out["guess"]["name"], out["guess"].get("year"))
                except Exception:
                    out["free"] = None
        except dvd.NotVideo as exc:
            out["problem"] = str(exc)
        finally:
            source.close()
    else:
        source = _open_video(d)
        try:
            ext = _media_ext()
            out["files"] = [{"path": p, "size": size} for p, size in iso9660.walk(source)
                            if os.path.splitext(p)[1].lower() in ext and not os.path.basename(p).startswith(".")][:2000]
        finally:
            source.close()
        if not out["files"]:
            out["problem"] = "There are no videos or music on this disc."
    return out


GENERIC = re.compile(r"^(dvd[\s_-]*(video|rom)?|video[\s_-]*ts|disc\s*\d*|disk\s*\d*|untitled|my[\s_-]*dvd|new[\s_-]*disc|"
                     r"home[\s_-]*movies?|cdrom|volume\s*\d*|[\d\s_-]+)$", re.I)


def tidy_label(label):
    """A disc's label as words: "RULES_OF_ENGAGEMENT" -> "Rules of Engagement", "THE_MATRIX_WS" -> "The Matrix"."""
    words = re.sub(r"[_.]+", " ", str(label or "")).strip()
    words = re.sub(r"\s+(ws|fs|wide\s*screen|full\s*screen|disc\s*\d+|d\d|side\s*[ab]|ntsc|pal|r\d|se|ce)$", "", words, flags=re.I)
    small = {"a", "an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
    def word(i, w):
        if not w.isupper() and not w.islower():
            return w                                      # (written with care already: "McQueen", "iPod")
        if w.isupper() and len(w) <= 4 and not re.search(r"[AEIOUY]", w) or re.match(r"^[IVX]{2,5}$", w.upper()):
            return w.upper()                              # (letters, not a word: "DVD", "TV"; a number: "II", "IV")
        return w.lower() if i and w.lower() in small else w.capitalize()
    out = [word(i, w) for i, w in enumerate(words.split())]
    return " ".join(out)


def same_title(found, asked):
    """Is the film found the one asked for? Its title must be the disc's (give or take "The", punctuation, a subtitle
    after a colon), not just a film from the same year that a search turned up."""
    import difflib
    a, b = naming.norm(found), naming.norm(asked)
    if not a or not b:
        return False
    if a == b or a.split(":")[0] == b or naming.norm(str(found).split(":")[0]) == b:
        return True
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False                                    # (Toy Story is not Toy Story 2)
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.88


def _guess(label):
    """What the DVD is, for its page and for a one-press Save: the label as words and, where it names a film and
    Sofa may look things up, that film's details found as a library movie's are (sofa/metadata.py)."""
    name, year = tidy_label(label), None
    m = re.match(r"^(.*\S)\s+\(?((?:19|20)\d\d)\)?$", name)
    if m:                                                   # ("Summer at the Lake 2004": the year it says)
        name, year = m.group(1), int(m.group(2))
    out = {"name": name or "DVD", "year": year, "summary": None, "poster": False, "found": False}
    if not name or GENERIC.match(name) or config.get("offline"):
        return out
    try:
        from . import metadata
        found = metadata.movie(name, year)
    except Exception:
        found = None
    if not found or not found.get("canonical") or not same_title(found["canonical"], name):
        return out                                      # (a film by another name: a home video's label found "I, Robot")
    out.update(name=found["canonical"], year=found.get("year"), summary=found.get("summary"), found=found.get("source"))
    if found.get("poster_url"):
        try:
            from . import metadata
            os.makedirs(ART, exist_ok=True)
            dest = os.path.join(ART, hashlib.sha1(name.encode("utf-8")).hexdigest()[:16] + ".jpg")
            out["poster"] = metadata.download(found["poster_url"], dest) or os.path.exists(dest)
            out["_poster"] = dest
        except Exception:
            pass
    return out


def poster(drive_id):
    """The picture found for the disc in this drive, or None."""
    with _lock:
        known = _known.get(drive_id)
        guess = ((known or {}).get("disc") or {}).get("guess") or {}
    path = guess.get("_poster")
    return path if path and os.path.isfile(path) else None


def _key(d):
    return (d["kind"], d["label"], d.get("dev"), d.get("mount"))


def _read_in_background(d):
    def work():
        try:
            disc = _describe(dict(d))
        except Exception as exc:
            disc = {"kind": d["kind"], "label": d["label"], "protected": False,
                    "problem": "The disc can't be read: %s" % (getattr(exc, "strerror", None) or exc)}
        with _lock:
            if _known.get(d["id"], {}).get("key") == _key(d):
                _known[d["id"]]["disc"] = disc
    threading.Thread(target=work, daemon=True, name="disc-read").start()


def _public(disc):
    out = {k: v for k, v in disc.items() if not k.startswith("_")}
    if isinstance(out.get("guess"), dict):
        out["guess"] = {k: v for k, v in out["guess"].items() if not k.startswith("_")}
    return out


def status(wait=0):
    """What the pages show: the drives, what's in each (read once, in the background: "reading" until it is), and
    how each save is going."""
    from . import slow                                     # (asking a drive what's in it takes a moment: every few seconds)
    found = slow.cached("disc-drives-%s-%s" % (os.environ.get("SOFA_DISCS") or "", "|".join(config.get("disc_sources") or [])), 5,
                        lambda: drives(), wait=8, default=[])
    with _lock:
        for gone in [k for k in _known if k not in {d["id"] for d in found if d["state"] == "disc"}]:
            _known.pop(gone)
        fresh = []
        for d in found:
            if d["state"] != "disc":
                continue
            if _known.get(d["id"], {}).get("key") != _key(d):
                _known[d["id"]] = {"key": _key(d), "disc": None, "drive": dict(d)}
                fresh.append(d)
    for d in fresh:
        _read_in_background(d)
    end = time.time() + wait
    while wait and time.time() < end and any(k["disc"] is None for k in list(_known.values())):
        time.sleep(0.05)
    out = []
    with _lock:
        for d in found:
            row = {"id": d["id"], "name": d["name"], "state": d["state"], "kind": d["kind"], "label": d["label"], "copy": bool(d.get("copy"))}
            known = _known.get(d["id"])
            if d["state"] == "disc":
                row["disc"] = _public(known["disc"]) if known and known["disc"] else None
                row["reading"] = not row["disc"]
                if row["disc"]:
                    row["label"] = row["disc"].get("label") or row["label"]
            out.append(row)
        jobs = [_public(j) for j in _jobs[-6:]]
    from . import capture, freecopy
    return {"drives": out, "jobs": jobs, "lookup": bool(config.get("disc_lookup")) and not config.get("offline"),
            "ffmpeg": bool(media.tool("ffmpeg")), "free_job": freecopy.status(),
            "capture": slow.cached("capture-%s" % (os.environ.get("SOFA_CAPTURE") or ""), 10, capture.status, wait=8,
                                   default={"devices": [], "job": None}) if not (capture._job.get("state") == "working") else capture.status()}


def names(drive_id, fetch=None):
    """Look this music CD up at MusicBrainz (only when asked, and only if Settings allows it)."""
    if not config.get("disc_lookup") or config.get("offline"):
        raise ValueError("Looking discs up is switched off (Server → Settings).")
    with _lock:
        known = _known.get(drive_id)
        disc = known and known["disc"]
    if not disc or disc.get("kind") != "cd":
        raise ValueError("There's no music CD in that drive.")

    class Toc:
        tracks, addresses, leadout = disc["_cd_tracks"], disc["_addresses"], disc["_addresses"][1]
    found = cdaudio.lookup(Toc, fetch) if fetch else cdaudio.lookup(Toc)
    if not found:
        return {"found": False}
    return {"found": True, "artist": found.get("artist") or "", "album": found.get("album") or "", "year": found.get("year") or "",
            "titles": {str(n): t for n, t in (found.get("titles") or {}).items()}}


# ---------------------------------------------------------------- saving

class Stop(Exception):
    """This save ends here, with these words."""


def _clean(text, most=120):
    return naming.safe_filename(re.sub(r"\s+", " ", str(text or "")).strip())[:most].strip(" .")


def _root(key):
    """Where new things of this kind go (the drive chosen for new files, else the main library)."""
    if key in ("movies", "shows"):
        try:
            from . import organizer
            return organizer._new_root(key)
        except Exception:
            pass
    return config.path(key)


def _show_folder(name):
    """A show's folder: the one it already has (on whichever drive), else a new one where new things go."""
    try:
        from . import organizer
        have = organizer._existing_show(name)
        if have:
            return have
    except Exception:
        pass
    return os.path.join(_root("shows"), name)


def _same_name(folder, name):
    """`name` inside `folder`, as the folder already spells it (Music/the beatles and Music/The Beatles are one artist)."""
    try:
        have = next((d for d in os.listdir(folder) if naming.norm(d) == naming.norm(name) and os.path.isdir(os.path.join(folder, d))), None)
    except OSError:
        have = None
    return os.path.join(folder, have or name)


def _room(folder, need):
    at = folder
    while not os.path.isdir(at):
        at = os.path.dirname(at)
    free = shutil.disk_usage(at).free
    if need + SPARE > free:
        raise ValueError("There isn't room for it: it needs about %s and %s is free." % (_size(need), _size(free)))


def _size(n):
    return "%.1f GB" % (n / 1024.0 ** 3) if n >= 1024 ** 3 else "%d MB" % max(1, n // 1024 ** 2)


def _plan(d, disc, ask):
    """Work out, before anything is read, every file this save will make: [{"dest", "what", ...}]. Raises ValueError
    with what's wrong (a name missing, a file already there, no room)."""
    if disc.get("protected") or (disc.get("problem") and disc["kind"] != "cd"):
        raise ValueError(disc.get("problem") or "This disc can't be saved.")
    if not media.tool("ffmpeg") and disc["kind"] != "data":
        raise ValueError("Sofa needs ffmpeg to save a disc, and it isn't installed on this computer.")
    plan = []
    if disc["kind"] == "cd":
        artist, album = _clean(ask.get("artist")), _clean(ask.get("album"))
        if not artist or not album:
            raise ValueError("Say who it's by and what the album is called.")
        year = str(ask.get("year") or "").strip()
        if year and not re.match(r"^(19|20)\d\d$", year):
            raise ValueError("The year looks like 1999.")
        titles = {int(k): str(v or "").strip() for k, v in (ask.get("tracks") or {}).items() if str(k).isdigit()}
        want = [t for t in disc["_cd_tracks"] if not titles or t["n"] in titles]
        if not want:
            raise ValueError("Pick at least one track.")
        folder = _same_name(_same_name(config.path("music"), artist), album)      # (the artist's and album's own folders, if there)
        for t in want:
            title = titles.get(t["n"]) or "Track %d" % t["n"]
            plan.append({"dest": os.path.join(folder, "%02d %s.flac" % (t["n"], _clean(title) or "Track %d" % t["n"])),
                         "what": title, "track": t, "tags": {"title": title, "artist": artist, "album_artist": artist, "album": album,
                                                             "track": "%d/%d" % (t["n"], len(disc["_cd_tracks"])), "date": year},
                         "size": t["frames"] * cdaudio.FRAME})
        need = sum(p["size"] for p in plan)
    elif disc["kind"] == "dvd":
        by_n = {t["n"]: t for t in disc["_titles"]}
        picked = [by_n[int(n)] for n in ask.get("titles") or [] if str(n).isdigit() and int(n) in by_n]
        if not picked:
            raise ValueError("Pick what to save from the disc.")
        for t in picked:
            if t["cant"]:
                raise ValueError("Title %d can't be saved. %s" % (t["n"], t["cant"]))
        name = _clean(ask.get("name"))
        if not name:
            raise ValueError("Give it a name.")
        if ask.get("to") == "shows":
            show, year = naming.show_name(name)             # (the name Sofa's tidying would give the folder: so it isn't
            name = _clean(show + (" (%d)" % year if year else "")) or name      # renamed under a save that's running)
            try:
                season, episode = int(ask.get("season") or 1), int(ask.get("episode") or 1)
            except (TypeError, ValueError):
                raise ValueError("The season and the episode are numbers.")
            if not 0 <= season <= 99 or not 1 <= episode <= 999:
                raise ValueError("The season and the episode are numbers.")
            folder = os.path.join(_show_folder(name), "Specials" if season == 0 else "Season %d" % season)
            have = set()
            if os.path.isdir(folder):
                for f in os.listdir(folder):
                    ep = naming.parse_episode(os.path.splitext(f)[0], season_hint=season, in_show=True)
                    if ep and os.path.splitext(f)[1].lower() in naming.VIDEO_EXT:
                        have.add((ep["s"], ep["e"]))
            for i, t in enumerate(picked):
                if (season, episode + i) in have:
                    raise ValueError("%s already has season %d episode %d. Start at another episode." % (name, season, episode + i))
                code = "S%02dE%02d" % (season, episode + i)
                plan.append({"dest": os.path.join(folder, "%s %s.mkv" % (name, code)), "what": "%s %s" % (name, code), "title": t,
                             "size": t["size"]})
        elif ask.get("to") == "movies":
            if len(picked) != 1:
                raise ValueError("A movie is one title from the disc. Pick the one that's the movie.")
            year = str(ask.get("year") or "").strip()
            if year and not re.match(r"^(19|20)\d\d$", year):
                raise ValueError("The year looks like 1999.")
            full = "%s (%s)" % (name, year) if year else name
            plan.append({"dest": os.path.join(_root("movies"), full, full + ".mkv"), "what": full, "title": picked[0], "size": picked[0]["size"]})
        else:
            raise ValueError("Say where it goes: Movies or Shows.")
        need = max(p["size"] for p in plan) * 2 + sum(p["size"] for p in plan)
    else:
        name = _clean(ask.get("name")) or _clean(disc.get("label")) or "Disc"
        files = disc.get("files") or []
        if not files:
            raise ValueError("There are no videos or music on this disc.")
        dest = os.path.join(config.path("inbox"), name)
        if os.path.lexists(dest):
            raise ValueError("The Inbox already has \"%s\". Give it another name." % name)
        plan.append({"dest": dest, "what": name, "files": files, "size": sum(f["size"] for f in files)})
        need = plan[0]["size"]
    for p in plan:
        folder = os.path.dirname(p["dest"])
        if "track" in p and os.path.isdir(folder) and any(
                naming.norm(f) == naming.norm(os.path.basename(p["dest"])) for f in os.listdir(folder)):
            raise ValueError("%s is already there (%s). Sofa doesn't write over a file." % (p["what"], os.path.basename(p["dest"])))
        if os.path.lexists(p["dest"]):
            raise ValueError("%s is already there (%s). Sofa doesn't write over a file." % (p["what"], os.path.basename(p["dest"])))
    if len({p["dest"].lower() for p in plan}) != len(plan):
        raise ValueError("Two of them would get the same name. Give each track its own.")
    _room(os.path.dirname(plan[0]["dest"]), need)
    return plan


def main_title(disc):
    """The title a DVD's film is (the longest Sofa can save), or None."""
    ok = [t for t in disc.get("_titles") or [] if not t["cant"] and t["seconds"] >= 1]
    return max(ok, key=lambda t: t["seconds"]) if ok else None


def quick(disc):
    """Save in one press: what to ask, from what the disc says and what was found for it. A DVD's longest title as a
    movie, named as found (or by its label); a music CD as its own text names it; a data disc by its label."""
    if disc["kind"] == "dvd":
        t, g = main_title(disc), disc.get("guess") or {}
        return {"to": "movies", "name": g.get("name") or tidy_label(disc.get("label")) or "DVD", "year": g.get("year") or "",
                "titles": [t["n"]] if t else []}
    if disc["kind"] == "cd":
        return {"artist": disc.get("artist") or "Unknown artist", "album": disc.get("album") or tidy_label(disc.get("label")) or "Music CD",
                "tracks": {str(t["n"]): t.get("title") or "" for t in disc.get("tracks") or []}}
    return {"name": tidy_label(disc.get("label")) or "Disc"}


def save(drive_id, ask, who="someone"):
    """Start saving the disc in `drive_id` as `ask` says (`quick`: as `quick` works it out). Returns the job as the
    pages see it; raises ValueError with a plain reason when it can't start."""
    found = next((d for d in drives() if d["id"] == drive_id and d["state"] == "disc"), None)
    with _lock:
        known = _known.get(drive_id)
        disc = known and known["disc"]
        if not found or not disc or known["key"] != _key(found):
            raise ValueError("There's no disc in that drive that's been read yet.")
        if ask.get("quick") and not disc.get("problem"):
            ask = dict(quick(disc), **{k: v for k, v in ask.items() if k in ("to", "name", "year") and v})
        if any(j["state"] == "working" for j in _jobs):
            raise ValueError("A disc is being saved already. This one can go when it's done.")
        plan = _plan(found, disc, ask)
        job = {"id": uuid.uuid4().hex[:10], "drive": drive_id, "kind": disc["kind"], "name": plan[0]["what"] if len(plan) == 1 else
               "%s, %d %s" % ((_clean(ask.get("album")) or disc["label"], len(plan), "tracks") if disc["kind"] == "cd" else
                              (plan[0]["what"].rsplit(" ", 1)[0], len(plan), "episodes")),
               "to": {"cd": "Music", "data": "Inbox"}.get(disc["kind"]) or ("Shows" if ask.get("to") == "shows" else "Movies"),
               "state": "working", "step": "Starting", "item": 0, "items": len(plan), "done": 0, "total": sum(p["size"] for p in plan),
               "files": [], "notes": [], "error": None, "started": int(time.time()), "finished": None, "_stop": False}
        _jobs.append(job)
        del _jobs[:-20]
    threading.Thread(target=_work, args=(job, dict(found), plan, who), daemon=True, name="disc-save").start()
    return _public(job)


def cancel(job_id):
    with _lock:
        for j in _jobs:
            if j["id"] == job_id and j["state"] == "working":
                j["_stop"] = True
                return True
    return False


def _work(job, d, plan, who):
    stage = None
    try:
        for i, p in enumerate(plan):
            job.update(item=i + 1, step="Reading %s" % p["what"])
            folder = os.path.dirname(p["dest"]) if "files" not in p else config.path("inbox")
            os.makedirs(folder, exist_ok=True)
            stage = os.path.join(folder, ".sofa-disc-%s" % job["id"])
            os.makedirs(stage, exist_ok=True)
            before = job["done"]
            if "track" in p:
                _save_track(job, d, p, stage)
            elif "title" in p:
                _save_title(job, d, p, stage)
            else:
                _save_files(job, d, p, stage)
            job["done"] = before + p["size"]
            job["files"].append(p["dest"])
            shutil.rmtree(stage, ignore_errors=True)
            stage = None
        end = {"state": "done", "step": "Saved"}
    except Stop as exc:
        end = {"state": "cancelled" if job["_stop"] else "failed", "error": str(exc)}
    except dvd.Protected:
        end = {"state": "failed", "error": PROTECTED % "DVD"}
    except FileExistsError:
        end = {"state": "failed", "error": "A file with that name appeared while it was being saved. Sofa doesn't write over a file."}
    except OSError as exc:
        end = {"state": "failed", "error": GONE if not _still_there(d) else "It couldn't be saved: %s" % (exc.strerror or exc)}
    except Exception as exc:
        end = {"state": "failed", "error": "It couldn't be saved: %s" % exc}
    if stage:
        shutil.rmtree(stage, ignore_errors=True)
    for folder in {os.path.dirname(p["dest"]) for p in plan}:
        _drop_empty(folder)
    if end["state"] == "done":
        store.log("disc", "Saved %s from a %s to %s" % (job["name"], KINDS[job["kind"]], job["to"]), {"files": job["files"], "by": who})
    elif end["state"] == "failed":
        store.log("disc", "Saving %s from a %s stopped: %s" % (job["name"], KINDS[job["kind"]], end["error"]))
    job.update(end, finished=int(time.time()))              # (after the tidying up: whoever waits finds everything in its place)
    if job["files"] and saved:                              # the library is read again, on its own time: the next disc needn't wait
        threading.Thread(target=_tell, daemon=True, name="disc-saved").start()


def _tell():
    try:
        saved()
    except Exception as exc:
        store.log("error", "Reading the library after a disc was saved: %s" % exc)


def _drop_empty(folder):
    """A folder made for a save that never put anything in it (and its parent, if that's empty too)."""
    roots = {os.path.normpath(config.path(k)) for k in ("movies", "shows", "music", "inbox")}
    for _ in range(2):
        try:
            if os.path.normpath(folder) in roots or os.listdir(folder):
                return
            os.rmdir(folder)
        except OSError:
            return
        folder = os.path.dirname(folder)


def _still_there(d):
    if d.get("inbox"):
        return os.path.exists(d["dev"])
    return any(x["id"] == d["id"] and x["state"] == "disc" and _key(x) == _key(d) for x in drives())


def _check(job):
    if job["_stop"]:
        raise Stop("Stopped. What was already saved is kept.")


def _ffmpeg(job, cmd, stdin=None):
    """Run ffmpeg to the end; raises Stop with its last words when it fails."""
    run = subprocess.run(cmd, stdin=stdin or subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=6 * 3600)
    if run.returncode != 0:
        raise Stop("ffmpeg couldn't pack it: %s" % (run.stderr.decode("utf-8", "replace").strip().splitlines() or ["no reason given"])[-1][:200])


# ---- a music CD's track

def _flac_md5(path):
    """The checksum of the sound a FLAC file holds, as the file itself records it (STREAMINFO's last 16 bytes)."""
    with open(path, "rb") as f:
        head = f.read(42)
    return head[26:42] if head[:4] == b"fLaC" and head[4] & 0x7F == 0 else None


def _save_track(job, d, p, stage):
    t, tmp = p["track"], os.path.join(stage, ".track.flac")
    cmd = [media.tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", "pipe:0",
           "-c:a", "flac", "-compression_level", "5"]
    for k, v in p["tags"].items():
        if v:
            cmd += ["-metadata", "%s=%s" % (k, v)]
    cd = _open_cd(d)
    proc = subprocess.Popen(cmd + [tmp], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    md5, base = hashlib.md5(), job["done"]
    try:
        at, end = t["start"], t["start"] + t["frames"]
        while at < end:
            _check(job)
            n = min(150, end - at)                          # two seconds of sound at a time
            data = None
            for attempt in range(3):                        # (a scratch: the drive gets three goes)
                try:
                    data = cd.read(at, n)
                    break
                except OSError:
                    if attempt == 2 or not _still_there(d):
                        raise
                    time.sleep(0.5)
            md5.update(data)
            proc.stdin.write(data)
            at += n
            job["done"] = base + (at - t["start"]) * cdaudio.FRAME
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait(600) != 0:
            raise Stop("ffmpeg couldn't pack it: %s" % (err.strip().splitlines() or ["no reason given"])[-1][:200])
    except BrokenPipeError:
        raise Stop("ffmpeg stopped while packing the track.")
    finally:
        cd.close()
        if proc.poll() is None:
            proc.kill()
        for pipe in (proc.stdin, proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass
    if _flac_md5(tmp) != md5.digest():
        raise Stop("The file didn't come out the same as the disc's sound, so it wasn't kept.")
    fileops.place(tmp, p["dest"])


# ---- a DVD's title

def _idx_time(ms):
    return "%02d:%02d:%02d:%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def _save_title(job, d, p, stage):
    t = p["title"]
    vob = os.path.join(stage, ".title.vob")
    seen, subs, base = {}, {}, job["done"]
    source = _open_video(d)
    try:
        with open(vob, "wb") as out:
            got = 0
            for chunk in dvd.read_title(source, t, seen, cancelled=lambda: job["_stop"]):      # (the one reader: see dvd.py)
                out.write(chunk)
                got += len(chunk)
                job["done"] = base + got * 2 // 3           # (reading is two thirds of the wait, packing the rest)
                for track, when, pack in seen.pop("subs", []):
                    s = subs.get(track)
                    if s is None:
                        s = subs[track] = {"f": open(os.path.join(stage, ".sub%02x.sub" % track), "wb"), "at": 0, "lines": []}
                    if when is not None:
                        s["lines"].append("timestamp: %s, filepos: %09x" % (_idx_time(when * 1000 // dvd.CLOCK), s["at"]))
                    s["f"].write(pack)
                    s["at"] += len(pack)
            out.flush()
            os.fsync(out.fileno())
    finally:
        source.close()
        for s in subs.values():
            s["f"].close()
    _check(job)
    job["step"] = "Packing %s" % p["what"]
    streams = seen.get("streams") or {}
    if not any(0xE0 <= sid <= 0xEF for sid, _ in streams):
        raise Stop("There's no picture in that title.")
    video = min(sid for sid, _ in streams if 0xE0 <= sid <= 0xEF)
    here = lambda a: (0xBD, a["id"]) in streams if a["kind"] != "mp2" else (a["id"], None) in streams
    audio = [a for a in t["audio"] if here(a)]
    listed = {a["id"] for a in t["audio"]}
    for sid, sub in sorted(streams, key=lambda k: (k[1] or k[0])):      # sound that's in the stream but not in the disc's list
        if sid == 0xBD and sub is not None and 0x80 <= sub <= 0xAF and sub not in listed:
            audio.append({"id": sub, "kind": "lpcm" if sub >= 0xA0 else "dts" if sub >= 0x88 else "ac3", "lang": None, "bits": 16, "name": ""})
    found = _stream_ids(vob, 100 << 20)
    want = [video + 0x100] + [a["id"] + (0x100 if a["kind"] == "mp2" else 0) for a in audio]
    probe = 100 << 20
    if any(w not in found for w in want):                   # a track that starts late: look through the whole title
        probe = max(os.path.getsize(vob), probe)
        found = _stream_ids(vob, probe)
    missing = [a for a in audio if a["id"] + (0x100 if a["kind"] == "mp2" else 0) not in found]
    audio = [a for a in audio if a not in missing]
    if video + 0x100 not in found:
        raise Stop("ffmpeg can't find the picture in that title.")
    for a in missing:
        job["notes"].append("A sound track (%s) starts too late in %s to be found, and isn't in the saved file." % (a.get("name") or "no name", p["what"]))
    cmd = [media.tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-probesize", str(probe), "-analyzeduration", str(min(probe * 20, 2 ** 31 - 1)),
           "-fflags", "+genpts", "-copyts", "-f", "mpeg", "-i", vob]      # (-copyts: every input keeps the disc's clock)
    maps, meta, n_in = ["-map", "0:#0x%x" % (video + 0x100)], [], 1
    for i, a in enumerate(audio):
        maps += ["-map", "0:#0x%x" % (a["id"] + (0x100 if a["kind"] == "mp2" else 0))]
        if a.get("lang"):
            meta += ["-metadata:s:a:%d" % i, "language=%s" % languages.three(a["lang"])]
        if a.get("name"):
            meta += ["-metadata:s:a:%d" % i, "title=%s" % a["name"]]
        if a["kind"] == "lpcm":                             # (a DVD's PCM can't go in an MKV as it is: the same samples, repacked)
            meta += ["-c:a:%d" % i, "pcm_s24le" if a.get("bits", 16) > 16 else "pcm_s16le"]
    by_id, kept = {s["id"]: s for s in t["subs"]}, 0
    palette = ", ".join(dvd.rgb(t["_palette"]))
    for track in sorted(subs):
        s = subs[track]
        if not s["lines"]:
            continue
        info = by_id.get(track, {})
        idx = os.path.join(stage, ".sub%02x.idx" % track)
        with open(idx, "w", encoding="utf-8") as f:
            f.write("# VobSub index file, v7 (do not modify this line!)\nsize: %dx%d\npalette: %s\n\nid: %s, index: %d\n%s\n" % (
                t["video"]["width"], t["video"]["height"], palette, info.get("lang") or "--", track - 0x20, "\n".join(s["lines"])))
        cmd += ["-f", "vobsub", "-sub_name", os.path.join(stage, ".sub%02x.sub" % track), "-i", idx]
        maps += ["-map", "%d:s" % n_in]
        if info.get("lang"):
            meta += ["-metadata:s:s:%d" % kept, "language=%s" % languages.three(info["lang"])]
        if info.get("name"):
            meta += ["-metadata:s:s:%d" % kept, "title=%s" % info["name"]]
        n_in += 1
        kept += 1
    first = seen.get("first", seen.get("start") or 0)       # the file starts at the earliest picture or sound...
    begins = max(0, (seen.get("start", first) - first)) * 1000 // dvd.CLOCK      # ...and its chapters count from the first picture
    if len(t["chapters"]) > 1:
        chapters = os.path.join(stage, ".chapters.txt")
        marks = [int(c * 1000) for c in t["chapters"]] + [int(t["seconds"] * 1000)]
        with open(chapters, "w", encoding="utf-8") as f:
            f.write(";FFMETADATA1\n" + "".join("[CHAPTER]\nTIMEBASE=1/1000\nSTART=%d\nEND=%d\ntitle=Chapter %d\n" % (
                begins + marks[i], begins + max(marks[i + 1], marks[i] + 1), i + 1) for i in range(len(marks) - 1)))
        cmd += ["-f", "ffmetadata", "-i", chapters]
        meta += ["-map_chapters", str(n_in)]
    else:
        meta += ["-map_chapters", "-1"]
    out = os.path.join(stage, ".title.mkv")
    _ffmpeg(job, cmd + maps + ["-map_metadata", "-1", "-c", "copy"] + meta + ["-metadata", "title=%s" % p["what"],
                               "-output_ts_offset", "%.6f" % (-first / float(dvd.CLOCK)), "-f", "matroska", out])
    _check(job)
    os.unlink(vob)
    fileops.place(out, p["dest"])


def _stream_ids(path, probe):
    """The streams ffmpeg finds in a title's stream, by their ids (0x1e0 the picture, 0x80 the first Dolby track...)."""
    exe = media.tool("ffprobe")
    if not exe:
        return set()
    try:
        out = subprocess.run([exe, "-v", "error", "-probesize", str(probe), "-analyzeduration", str(min(probe * 20, 2 ** 31 - 1)), "-f", "mpeg",
                              "-show_entries", "stream=id", "-of", "csv=p=0", path], capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(x.strip().rstrip(","), 16) for x in out.stdout.split() if x.strip().rstrip(",").startswith("0x")}


# ---- a data disc's files

def _save_files(job, d, p, stage):
    source = _open_video(d)
    base = job["done"]
    try:
        top = os.path.join(stage, os.path.basename(p["dest"]))
        got = 0
        for f in p["files"]:
            _check(job)
            parts = [_clean(x) or "file" for x in f["path"].split("/")]
            dest = os.path.join(top, *parts)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            job["step"] = "Copying %s" % parts[-1]
            with source.open(f["path"]) as src, open(dest, "xb") as out:
                while True:
                    _check(job)
                    data = src.read(4 << 20)
                    if not data:
                        break
                    out.write(data)
                    got += len(data)
                    job["done"] = base + got
                out.flush()
                os.fsync(out.fileno())
            if os.path.getsize(dest) != f["size"]:
                raise OSError("The disc stopped answering.")
    finally:
        source.close()
    if os.path.lexists(p["dest"]):
        raise FileExistsError(p["dest"])
    os.rename(top, p["dest"])


def clean():
    """What a save that was cut short (the power, a crash) left behind: its hidden folders, a day old. And whatever a
    disc being watched left when Sofa stopped."""
    shutil.rmtree(PLAYS, ignore_errors=True)
    gone = 0
    for key in ("movies", "shows", "music", "inbox"):
        for root, dirs, _ in os.walk(config.path(key)):
            for name in [x for x in dirs if x.startswith(".sofa-disc-")]:
                path = os.path.join(root, name)
                try:
                    if time.time() - os.path.getmtime(path) > 86400:
                        shutil.rmtree(path, ignore_errors=True)
                        gone += 1
                except OSError:
                    pass
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            if root.count(os.sep) - config.path(key).count(os.sep) >= 2:
                dirs[:] = []
    return gone


# ---------------------------------------------------------------- watching a DVD in Sofa's player

_plays = {}                 # session -> {"dir", "proc", "drive", "title", "last", "error", "stop"}
PLAY_IDLE = 90              # seconds nobody asks for the stream before it stops


def play(drive_id, n=None, who="someone"):
    """Start watching a title of the DVD in `drive_id` (its film when `n` is None) in Sofa's player: the title is read
    as it's saved (`dvd.read_title`, the one reader) and converted as it plays, to a stream every browser plays.
    Returns {"session", "url", "name", "seconds"}. One at a time; a copy-protected disc isn't played either."""
    found = next((d for d in drives() if d["id"] == drive_id and d["state"] == "disc"), None)
    with _lock:
        known = _known.get(drive_id)
        disc = known and known["disc"]
        if not found or not disc or known["key"] != _key(found) or disc.get("kind") != "dvd":
            raise ValueError("There's no DVD in that drive that's been read yet.")
        if disc.get("problem"):
            raise ValueError(disc["problem"])
        title = main_title(disc) if n is None else next((t for t in disc["_titles"] if t["n"] == int(n)), None)
        if not title:
            raise ValueError("That title isn't on the disc.")
        if title["cant"]:
            raise ValueError(title["cant"].replace("can't save yet", "can't play yet"))
    if not media.tool("ffmpeg"):
        raise ValueError("Sofa needs ffmpeg to play a disc, and it isn't installed on this computer.")
    play_stop()
    sid = uuid.uuid4().hex[:20]
    folder = os.path.join(PLAYS, sid)
    os.makedirs(folder, exist_ok=True)
    audio = title["audio"][0] if title["audio"] else None
    cmd = [media.tool("ffmpeg"), "-v", "error", "-nostdin", "-fflags", "+genpts", "-probesize", "16M", "-analyzeduration", "20M",
           "-f", "mpeg", "-i", "pipe:0", "-map", "0:v:0"]
    if audio:
        cmd += ["-map", "0:#0x%x?" % (audio["id"] + (0x100 if audio["kind"] == "mp2" else 0))]
    cmd += ["-vf", "yadif=deint=interlaced,format=yuv420p"] + media.h264_args(title["video"]["height"], live=True) + \
        ["-g", "48", "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
         "-hls_playlist_type", "event", "-hls_segment_filename", os.path.join(folder, "seg%05d.ts"), os.path.join(folder, "index.m3u8")]
    cmd, extra = media.gently(cmd)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **extra)
    st = {"dir": folder, "proc": proc, "drive": drive_id, "title": title["n"], "last": time.time(), "error": None, "stop": False}
    with _lock:
        _plays[sid] = st

    def feed():
        source = None
        try:
            source = _open_video(found)
            for chunk in dvd.read_title(source, title, cancelled=lambda: st["stop"]):
                if st["stop"] or time.time() - st["last"] > PLAY_IDLE:
                    break
                proc.stdin.write(chunk)
        except dvd.Protected:
            st["error"] = PROTECTED % "DVD"
        except (BrokenPipeError, ValueError):
            pass
        except OSError:
            st["error"] = "The disc stopped answering." if _still_there(found) else GONE.split(".")[0] + "."
        finally:
            if source:
                source.close()
            try:
                proc.stdin.close()
            except OSError:
                pass
            proc.wait()
    threading.Thread(target=feed, daemon=True, name="disc-play").start()
    threading.Thread(target=_reaper, daemon=True, name="disc-play-idle").start()
    end = time.time() + 30
    while time.time() < end and not os.path.exists(os.path.join(folder, "index.m3u8")):
        if proc.poll() is not None or st["error"]:
            break
        time.sleep(0.2)
    if not os.path.exists(os.path.join(folder, "index.m3u8")):
        why = st["error"] or (proc.stderr.read().decode("utf-8", "replace").strip().splitlines() or ["it didn't start"])[-1][:200]
        play_stop(sid)
        raise ValueError("The disc didn't play: %s" % why if not st["error"] else why)
    t = next(x for x in disc["_titles"] if x["n"] == title["n"])
    g = disc.get("guess") or {}
    return {"session": sid, "url": "/api/admin/disc/play/%s/index.m3u8" % sid, "title": t["n"], "seconds": t["seconds"],
            "name": g.get("name") or tidy_label(disc.get("label")) or "DVD", "drive": drive_id}


def play_file(sid, name):
    """A file of a disc that's playing (its list, or a piece), or None. Asking keeps it going."""
    if not re.match(r"^(index\.m3u8|seg\d{5}\.ts)$", name or ""):
        return None
    with _lock:
        st = _plays.get(sid)
    if not st:
        return None
    st["last"] = time.time()
    path = os.path.join(st["dir"], name)
    return path if os.path.isfile(path) else None


def play_status(sid):
    with _lock:
        st = _plays.get(sid)
    if not st:
        return {"playing": False}
    return {"playing": st["proc"].poll() is None, "error": st["error"]}


def play_stop(sid=None):
    """Stop watching (one session, or every one), and remove what was made for it."""
    with _lock:
        gone = [(k, _plays.pop(k)) for k in list(_plays) if sid is None or k == sid]
    for _, st in gone:
        st["stop"] = True
        try:
            st["proc"].kill()
        except OSError:
            pass
        shutil.rmtree(st["dir"], ignore_errors=True)
    return bool(gone)


def _reaper():
    while True:
        time.sleep(15)
        with _lock:
            idle = [k for k, st in _plays.items() if time.time() - st["last"] > PLAY_IDLE]
            left = len(_plays)
        for k in idle:
            play_stop(k)
        if left <= len(idle):
            return


# ---------------------------------------------------------------- a DVD rip dropped in the Inbox

_inbox = set()              # Inbox entries being saved now (the organizer leaves them alone meanwhile)


def rip_source(entry):
    """The DVD in an Inbox entry, or None: an .iso, a folder holding VIDEO_TS (as rippers save a disc), VIDEO_TS
    itself, or a folder holding one .iso. (path to read, its folder or None)"""
    if os.path.isfile(entry):
        return entry if entry.lower().endswith(".iso") else None
    if not os.path.isdir(entry):
        return None
    if os.path.basename(entry.rstrip("/\\")).upper() == "VIDEO_TS":
        return os.path.dirname(entry.rstrip("/\\"))
    for at, dirs, files in os.walk(entry):
        if any(d.upper() == "VIDEO_TS" for d in dirs) and any(f.upper().startswith("VIDEO_TS.") for d in dirs if d.upper() == "VIDEO_TS"
                                                             for f in os.listdir(os.path.join(at, d))):
            return at
        isos = [f for f in files if f.lower().endswith(".iso")]
        if len(isos) == 1 and at == entry:
            return os.path.join(at, isos[0])
        if at.count(os.sep) - entry.count(os.sep) >= 2:
            dirs[:] = []
    return None


def inbox_busy(entry):
    with _lock:
        return os.path.abspath(entry) in _inbox


def inbox_rip(entry, name, year=None, done=None, who="the Inbox"):
    """Save the DVD in an Inbox entry as one movie (its film, with every sound and subtitle track and the chapters),
    named `name` (`year`). Runs in the background; `done(job)` is called at the end, whatever happened. Raises
    ValueError at once when it can't (a copy-protected disc, no film on it, a name that's taken)."""
    path = rip_source(entry)
    if not path:
        raise ValueError("There's no DVD in it.")
    path = os.path.abspath(path)
    d = {"id": "inbox-" + hashlib.sha1(path.encode("utf-8")).hexdigest()[:8], "dev": path, "mount": path if os.path.isdir(path) else None,
         "name": "Inbox", "state": "disc", "kind": "dvd", "label": name, "image": True, "inbox": True}
    source = _open_video(d)
    try:
        info = dvd.titles(source)
        disc = {"kind": "dvd", "label": name, "_titles": info["titles"], "protected": False, "problem": None}
        for t in sorted([t for t in info["titles"] if not t["cant"]], key=lambda t: -t["seconds"])[:3]:
            if dvd.sample(source, t):
                raise ValueError(PROTECTED.split(".")[0] % "DVD" + ": what's in it is still scrambled.")
    finally:
        source.close()
    t = main_title(disc)
    if not t:
        raise ValueError("There's no film on this DVD that Sofa can save.")
    plan = _plan(d, disc, {"to": "movies", "name": name, "year": year or "", "titles": [t["n"]]})
    with _lock:
        if any(j["state"] == "working" for j in _jobs):
            raise ValueError("busy")
        job = {"id": uuid.uuid4().hex[:10], "drive": d["id"], "kind": "dvd", "name": plan[0]["what"], "to": "Movies",
               "state": "working", "step": "Starting", "item": 0, "items": 1, "done": 0, "total": plan[0]["size"],
               "files": [], "notes": [], "error": None, "started": int(time.time()), "finished": None, "_stop": False, "inbox": True}
        _jobs.append(job)
        del _jobs[:-20]
        _inbox.add(os.path.abspath(entry))

    def run():
        try:
            _work(job, d, plan, who)
        finally:
            with _lock:
                _inbox.discard(os.path.abspath(entry))
            if done:
                try:
                    done(_public(job))
                except Exception as exc:
                    store.log("error", "After saving a DVD from the Inbox: %s" % exc)
    threading.Thread(target=run, daemon=True, name="inbox-dvd").start()
    return _public(job)


# ---------------------------------------------------------------- finding a DVD copy on this computer (no typing)

def _places():
    """Where copies are looked for and the browser starts: this computer's own folders, the library's, and drives."""
    home = os.path.expanduser("~")
    out = [("Home", home)]
    for name in ("Desktop", "Downloads", "Movies", "Videos", "Documents"):
        p = os.path.join(home, name)
        if os.path.isdir(p):
            out.append((name, p))
    out.append(("Inbox", config.path("inbox")))
    if os.name == "nt":
        import string
        out += [("Drive %s:" % c, "%s:\\" % c) for c in string.ascii_uppercase if os.path.isdir("%s:\\" % c)]
    else:
        for base in ("/Volumes", "/media/" + os.path.basename(home), "/media", "/mnt"):
            try:
                for n in sorted(os.listdir(base)):
                    p = os.path.join(base, n)
                    if os.path.isdir(p) and not n.startswith(".") and p != "/media/" + os.path.basename(home) and n not in ("Macintosh HD", "Recovery", "Preboot", "VM", "Update", "Data"):
                        out.append((n, p))
            except OSError:
                pass
    seen, keep = set(), []
    for name, p in out:
        if os.path.isdir(p) and os.path.realpath(p) not in seen:
            seen.add(os.path.realpath(p))
            keep.append({"name": name, "path": p})
    return keep


def _is_copy(path, names=None):
    """What a folder or file is to Save from a folder or disc image: "dvd" (holds VIDEO_TS, or is it), "image" (an
    .iso), "cd" (a .cue), or None."""
    if os.path.isfile(path):
        low = path.lower()
        return "image" if low.endswith((".iso", ".img")) else "cd" if low.endswith(".cue") else None
    if os.path.basename(path.rstrip("/\\")).upper() == "VIDEO_TS":
        return "dvd"
    try:
        names = names if names is not None else os.listdir(path)
    except OSError:
        return None
    return "dvd" if any(n.upper() == "VIDEO_TS" and os.path.isdir(os.path.join(path, n)) for n in names) else None


def browse(path=None):
    """A folder on this computer, for picking a copy: {"path", "up", "places", "items": [{"name", "path", "folder",
    "copy"}]}. Folders and copies only; hidden ones left out."""
    places_ = _places()
    if not path:
        return {"path": None, "up": None, "places": places_, "items": [dict(p, folder=True, copy=_is_copy(p["path"])) for p in places_]}
    path = os.path.abspath(os.path.expanduser(str(path)))
    if not os.path.isdir(path):
        raise ValueError("That folder isn't there.")
    items = []
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except OSError as exc:
        raise ValueError("Sofa may not look in that folder (%s)." % (exc.strerror or exc))
    for n in names:
        if n.startswith(".") or n.startswith("$"):
            continue
        p = os.path.join(path, n)
        if os.path.isdir(p):
            items.append({"name": n, "path": p, "folder": True, "copy": _is_copy(p)})
        elif _is_copy(p):
            try:
                size = os.path.getsize(p)
            except OSError:
                size = 0
            items.append({"name": n, "path": p, "folder": False, "copy": _is_copy(p), "size": size})
    up = os.path.dirname(path.rstrip("/\\")) or None
    home = os.path.expanduser("~")
    shown = "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path
    return {"path": path, "shown": shown, "up": up if up and up != path else None, "places": places_, "items": items[:500]}


def find_copies(most_seconds=8, most_dirs=6000):
    """DVD copies (VIDEO_TS folders, .iso images) and CD images (.cue) in this computer's usual folders and on its
    drives, four folders deep: [{"name", "path", "copy", "where"}]. Stops after a few seconds."""
    end, found, looked = time.time() + most_seconds, [], 0
    seen = set()
    for place in _places():
        stack = [(place["path"], 0)]
        while stack and time.time() < end and looked < most_dirs:
            at, depth = stack.pop()
            looked += 1
            try:
                names = os.listdir(at)
            except OSError:
                continue
            kind = _is_copy(at, names) if at != place["path"] or place["name"] not in ("Home",) else None
            if kind:
                if os.path.realpath(at) not in seen:
                    seen.add(os.path.realpath(at))
                    found.append({"name": os.path.basename(at.rstrip("/\\")), "path": at, "copy": kind, "where": place["name"],
                                  "shown": os.path.relpath(os.path.dirname(at.rstrip("/\\")), place["path"]).replace(os.sep, " › ") if os.path.dirname(at.rstrip("/\\")) != place["path"] else ""})
                continue
            for n in names:
                if n.startswith((".", "$")) or n in ("Library", "AppData", "node_modules", "Applications", "System"):
                    continue
                p = os.path.join(at, n)
                if os.path.isdir(p) and not os.path.islink(p):
                    if depth < 4:
                        stack.append((p, depth + 1))
                elif n.lower().endswith((".iso", ".cue")) and os.path.realpath(p) not in seen:
                    seen.add(os.path.realpath(p))
                    found.append({"name": os.path.splitext(n)[0], "path": p, "copy": _is_copy(p), "where": place["name"],
                                  "shown": os.path.relpath(at, place["path"]).replace(os.sep, " › ") if at != place["path"] else ""})
    return found[:200]
