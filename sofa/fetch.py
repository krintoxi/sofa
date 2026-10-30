"""Save from a link: paste the address of a video page, Sofa downloads it and files it.

The downloading is done by yt-dlp (https://github.com/yt-dlp/yt-dlp), the open-source
tool that understands YouTube and well over a thousand other sites, including the free
adult tube sites. Sofa can install it for you (Server page, Downloads) and keeps that copy
up to date, because sites change and yt-dlp follows within days.

Each download goes to data/cache/downloads/<id>/ first, so the Inbox never sees half a
file. yt-dlp also saves a .info.json (title, date, channel, cast, tags) and a thumbnail;
when it's done the lot moves to Inbox/XXX (adult) or the Inbox, and the organizer files
it like anything else. One download at a time, and it waits while someone watches a video
Sofa is converting live.
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from . import config, media, naming, store

STAGING = os.path.join(config.DATA_DIR, "cache", "downloads")
OWN_BIN = os.path.join(config.DATA_DIR, "bin")
RELEASES = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
UPDATE_EVERY = 24 * 3600
_wake = threading.Event()
_current = {}
_lock = threading.Lock()


def _table():
    store.ex("""CREATE TABLE IF NOT EXISTS downloads (
        id INTEGER PRIMARY KEY, url TEXT NOT NULL, adult INTEGER NOT NULL DEFAULT 0, playlist INTEGER NOT NULL DEFAULT 0,
        state TEXT NOT NULL, title TEXT, error TEXT, added INTEGER NOT NULL, started INTEGER, finished INTEGER, files INTEGER)""")


# ---------------------------------------------------------------- yt-dlp itself

def own_copy():
    return os.path.join(OWN_BIN, "yt-dlp")


def tool():
    setting = config.get("ytdlp")
    candidates = [os.path.expanduser(setting)] if setting and setting != "auto" else []
    candidates += [own_copy(), "/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp", shutil.which("yt-dlp") or ""]
    for c in candidates:
        if c and os.access(c, os.X_OK):
            return c
    return None


def _cmd(exe):
    """How to run it. The macOS build runs by itself; the Linux one is a Python zipapp, run with this Python."""
    if exe == own_copy() and platform.system() != "Darwin":
        return [sys.executable, exe]
    return [exe]


def version():
    exe = tool()
    if not exe:
        return None
    try:
        return subprocess.run(_cmd(exe) + ["--version"], capture_output=True, text=True, timeout=30).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def install():
    """Download the official yt-dlp build into data/bin. Returns its version."""
    name = "yt-dlp_macos" if platform.system() == "Darwin" else "yt-dlp"
    os.makedirs(OWN_BIN, exist_ok=True)
    tmp = own_copy() + ".part"
    req = urllib.request.Request(RELEASES + name, headers={"User-Agent": "Sofa home media server"})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    if os.path.getsize(tmp) < 100000:
        os.remove(tmp)
        raise RuntimeError("the download from GitHub looks wrong")
    os.chmod(tmp, 0o755)
    os.replace(tmp, own_copy())
    v = version()
    if not v:
        raise RuntimeError("yt-dlp was downloaded but doesn't run on this computer")
    store.log("download", "Installed yt-dlp %s" % v)
    return v


def _self_update():
    """Keep Sofa's own copy current (sites change; yt-dlp fixes them within days)."""
    exe = tool()
    if exe != own_copy():
        return
    stamp = own_copy() + ".checked"
    try:
        if time.time() - os.path.getmtime(stamp) < UPDATE_EVERY:
            return
    except OSError:
        pass
    try:
        subprocess.run(_cmd(exe) + ["-U"], capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        pass
    with open(stamp, "w") as f:
        f.write(str(int(time.time())))


# ---------------------------------------------------------------- the queue

def add(url, adult=False, playlist=False):
    url = (url or "").strip()
    if not re.match(r"^https?://[^\s/]+", url):
        raise ValueError("Paste a full link that starts with http:// or https://.")
    _table()
    if store.q1("SELECT 1 FROM downloads WHERE url = ? AND state IN ('queued', 'working')", url):
        raise ValueError("That link is already in the queue.")
    store.ex("INSERT INTO downloads (url, adult, playlist, state, added) VALUES (?,?,?,?,?)",
             url[:2000], 1 if adult else 0, 1 if playlist else 0, "queued", int(time.time()))
    _wake.set()


def retry(job_id):
    _table()
    store.ex("UPDATE downloads SET state = 'queued', error = NULL WHERE id = ? AND state = 'failed'", int(job_id))
    _wake.set()


def cancel(job_id):
    _table()
    with _lock:
        if _current.get("id") == int(job_id) and _current.get("proc"):
            _current["cancelled"] = True
            _current["proc"].kill()
    store.ex("DELETE FROM downloads WHERE id = ? AND state IN ('queued', 'failed')", int(job_id))


def clear_finished():
    _table()
    store.ex("DELETE FROM downloads WHERE state IN ('done', 'failed')")


def status(viewer_adult=False):
    """The queue for the Server page. Adult rows show no title or link to admins without Adult access."""
    _table()
    rows = []
    for r in store.q("""SELECT * FROM downloads ORDER BY CASE state WHEN 'working' THEN 0 WHEN 'queued' THEN 1
                        WHEN 'failed' THEN 2 ELSE 3 END, COALESCE(finished, added) DESC LIMIT 60"""):
        r = dict(r)
        if r["adult"] and not viewer_adult:
            r.update(url=None, title="Private download")
        with _lock:
            if _current.get("id") == r["id"]:
                r["progress"] = _current.get("progress", 0)
                r["title"] = r["title"] or (_current.get("title") if (viewer_adult or not r["adult"]) else None)
        rows.append(r)
    return {"rows": rows, "tool": tool(), "version": version() if tool() else None, "own": tool() == own_copy(),
            "ffmpeg": bool(media.tool("ffmpeg")), "waiting": bool(_current.get("waiting"))}


# ---------------------------------------------------------------- doing one

PROGRESS = re.compile(r"\[download\]\s+([\d.]+)%")
TITLE = re.compile(r"^SOFA-TITLE (.*)$")


def _command(job, folder):
    cmd = _cmd(tool()) + ["--newline", "--no-colors", "--no-mtime", "--windows-filenames",
                          "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b", "--merge-output-format", "mp4",
                          "--write-info-json", "--write-thumbnail", "--convert-thumbnails", "jpg",
                          "--no-simulate", "--no-quiet", "--print", "before_dl:SOFA-TITLE %(title)s",
                          "-o", os.path.join(folder, "%(title).150B [%(id)s].%(ext)s")]
    ff = media.tool("ffmpeg")
    if ff:
        cmd += ["--ffmpeg-location", os.path.dirname(ff)]
    if job["playlist"]:
        cmd += ["--yes-playlist", "--playlist-end", "50"]
    else:
        cmd += ["--no-playlist"]
    gb = float(config.get("download_max_gb") or 0)
    if gb > 0:
        cmd += ["--max-filesize", "%dM" % int(gb * 1024)]
    return cmd + ["--", job["url"]]


def _run_one(job):
    folder = os.path.join(STAGING, str(job["id"]))
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    store.ex("UPDATE downloads SET state = 'working', started = ?, error = NULL WHERE id = ?", int(time.time()), job["id"])
    tail = []
    with _lock:
        _current.update(id=job["id"], progress=0.0, title=None)
    try:
        proc = subprocess.Popen(_command(job, folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                errors="replace")
        with _lock:
            _current["proc"] = proc
        for line in proc.stdout:
            line = line.strip()
            m = PROGRESS.search(line)
            t = TITLE.match(line)
            with _lock:
                if m:
                    _current["progress"] = min(0.99, float(m.group(1)) / 100)
                if t:
                    _current["title"] = t.group(1)[:200]
            if t:
                store.ex("UPDATE downloads SET title = ? WHERE id = ?", t.group(1)[:200], job["id"])
            if line and not m:
                tail = (tail + [line])[-6:]
        code = proc.wait()
        if _current.get("cancelled"):
            raise InterruptedError()
        videos = [f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in naming.VIDEO_EXT]
        if code != 0 or not videos:
            err = next((x for x in reversed(tail) if "ERROR" in x), tail[-1] if tail else "yt-dlp stopped")
            raise RuntimeError(re.sub(r"^ERROR:\s*", "", err)[:300])
        for f in os.listdir(folder):                    # leftovers yt-dlp didn't clean up
            if f.endswith((".part", ".ytdl", ".temp")):
                os.remove(os.path.join(folder, f))
        inbox = os.path.join(config.path("inbox"), "XXX") if job["adult"] else config.path("inbox")
        os.makedirs(inbox, exist_ok=True)
        title = store.q1("SELECT title FROM downloads WHERE id = ?", job["id"])["title"] or "Download %d" % job["id"]
        dest = os.path.join(inbox, naming.safe_filename(title)[:100] or "Download")
        n = 2
        while os.path.exists(dest):
            dest = "%s (%d)" % (os.path.join(inbox, naming.safe_filename(title)[:100]), n)
            n += 1
        shutil.move(folder, dest)
        store.ex("UPDATE downloads SET state = 'done', finished = ?, files = ? WHERE id = ?",
                 int(time.time()), len(videos), job["id"])
        if job["adult"]:
            store.log_private("download", "Saved %d video%s from a link to Adult" % (len(videos), "" if len(videos) == 1 else "s"))
        else:
            store.log("download", "Saved \"%s\" from a link; it's being filed now" % title, {"url": job["url"]})
    except InterruptedError:
        store.ex("DELETE FROM downloads WHERE id = ?", job["id"])
        shutil.rmtree(folder, ignore_errors=True)
    except Exception as exc:
        store.ex("UPDATE downloads SET state = 'failed', finished = ?, error = ? WHERE id = ?",
                 int(time.time()), str(exc)[:400], job["id"])
        shutil.rmtree(folder, ignore_errors=True)
        if job["adult"]:
            store.log_private("download", "A download for Adult didn't work")
        else:
            store.log("download", "Couldn't save from a link: %s" % str(exc)[:200], {"url": job["url"]})
    finally:
        with _lock:
            _current.clear()


def _loop():
    _table()
    store.ex("UPDATE downloads SET state = 'queued' WHERE state = 'working'")      # interrupted by a restart
    shutil.rmtree(STAGING, ignore_errors=True)
    while True:
        _wake.wait(300)
        _wake.clear()
        try:
            _self_update()
        except Exception:
            pass
        while tool():
            if media.busy():
                with _lock:
                    _current["waiting"] = True
                time.sleep(20)
                continue
            with _lock:
                _current.pop("waiting", None)
            row = store.q1("SELECT * FROM downloads WHERE state = 'queued' ORDER BY added LIMIT 1")
            if not row:
                break
            _run_one(dict(row))


def start():
    threading.Thread(target=_loop, daemon=True, name="downloads").start()
