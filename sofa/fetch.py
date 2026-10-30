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
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from . import config, media, naming, net, store

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


RUNNER = os.path.join(OWN_BIN, "yt-dlp.json")      # how to run Sofa's own copy: {"python": "/path/to/python3.12"}
_known_version = {}
install_state = {}                                 # what the Install button is doing right now


def tool():
    setting = config.get("ytdlp")
    candidates = [os.path.expanduser(setting)] if setting and setting != "auto" else []
    candidates += [own_copy(), "/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp", shutil.which("yt-dlp") or ""]
    for c in candidates:
        if c and os.access(c, os.X_OK):
            return c
    return None


def _runner():
    try:
        with open(RUNNER, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _cmd(exe):
    """How to run it: the Mac build runs by itself; the cross-platform one is a Python program."""
    if exe == own_copy():
        python = _runner().get("python")
        if python:
            return [python, exe]
        if platform.system() != "Darwin":
            return [sys.executable, exe]
    return [exe]


def _try(cmd, timeout=180):
    """Run `cmd --version`: (version, None) or (None, why it didn't work)."""
    try:
        r = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "it didn't answer within %d seconds" % timeout
    except OSError as exc:
        return None, exc.strerror or str(exc)
    out = r.stdout.strip()
    if r.returncode == 0 and re.match(r"^\d{4}\.\d", out):
        return out, None
    if r.returncode in (-4, 132):
        return None, "this computer's processor can't run it (illegal instruction)"
    if r.returncode in (-9, 137) and platform.system() == "Darwin":
        return None, "macOS stopped it (it may not allow this program)"
    lines = (r.stderr or out).strip().splitlines()
    return None, (lines[-1] if lines else "it stopped with code %d" % r.returncode)[:200]


def version():
    exe = tool()
    if not exe:
        return None
    try:
        stamp = os.path.getmtime(exe)
    except OSError:
        return None
    if _known_version.get("exe") != exe or _known_version.get("stamp") != stamp:
        v, _why = _try(_cmd(exe), timeout=60)
        _known_version.update(exe=exe, stamp=stamp, version=v)
    return _known_version.get("version")


def _pythons():
    """Pythons on this computer new enough for yt-dlp (3.11+), best first."""
    names = ["python3.14", "python3.13", "python3.12", "python3.11", "python3"]
    places = [sys.executable] + ["/opt/homebrew/bin/" + n for n in names] + ["/usr/local/bin/" + n for n in names]
    places += sorted(glob.glob("/Library/Frameworks/Python.framework/Versions/3.*/bin/python3"), reverse=True)
    places += [shutil.which(n) or "" for n in names]
    seen, out = set(), []
    for p in places:
        if not p or p in seen or not os.access(p, os.X_OK):
            continue
        seen.add(p)
        try:
            v = subprocess.run([p, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], capture_output=True,
                               text=True, timeout=20).stdout.strip()
            if tuple(int(x) for x in v.split(".")) >= (3, 11):
                out.append(p)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return out


def _download(name, dest):
    tmp = dest + ".part"
    req = urllib.request.Request(RELEASES + name, headers={"User-Agent": "Sofa home media server"})
    with net.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    if os.path.getsize(tmp) < 100000:
        os.remove(tmp)
        raise RuntimeError("the download from GitHub looks wrong")
    os.chmod(tmp, 0o755)
    os.replace(tmp, dest)
    if platform.system() == "Darwin":         # downloaded by a program, not a browser: no quarantine, but be sure
        try:
            subprocess.run(["xattr", "-d", "com.apple.quarantine", dest], capture_output=True)
        except OSError:
            pass


def _set_runner(python):
    with open(RUNNER, "w", encoding="utf-8") as f:
        json.dump({"python": python} if python else {}, f)
    _known_version.clear()


def install():
    """Get a yt-dlp that runs here, trying in turn: the ready-made Mac program, the cross-platform
    version with a Python 3.11+ found on this computer, and Homebrew. Returns its version."""
    os.makedirs(OWN_BIN, exist_ok=True)
    tried = []
    mac = platform.system() == "Darwin"
    install_state.update(step="Downloading yt-dlp from GitHub", at=time.time())
    if mac:
        _download("yt-dlp_macos", own_copy())
        _set_runner(None)
        install_state.update(step="Starting it for the first time (can take a minute)")
        v, why = _try([own_copy()])
        if v:
            return _installed(v, "the Mac version")
        tried.append("The ready-made Mac version: %s." % why)
    pythons = _pythons()
    if pythons:
        install_state.update(step="Trying the cross-platform version")
        _download("yt-dlp", own_copy())
        for python in pythons:
            v, why = _try([python, own_copy()])
            if v:
                _set_runner(python)
                return _installed(v, "the cross-platform version, with %s" % python)
            tried.append("With %s: %s." % (python, why))
    else:
        tried.append("The cross-platform version needs Python 3.11 or newer, and this computer has none.")
    if os.path.exists(own_copy()):
        os.remove(own_copy())
    brew = next((b for b in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if os.access(b, os.X_OK)), None)
    if brew:
        install_state.update(step="Installing with Homebrew (this can take a long time on an older Mac)")
        env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1",
                   PATH=os.path.dirname(brew) + ":/usr/bin:/bin:/usr/sbin:/sbin")
        try:
            r = subprocess.run([brew, "install", "yt-dlp"], capture_output=True, text=True, timeout=3600, env=env)
            if r.returncode != 0:
                tried.append("Homebrew: %s." % ((r.stderr or r.stdout).strip().splitlines() or ["it didn't work"])[-1][:200])
        except (OSError, subprocess.SubprocessError) as exc:
            tried.append("Homebrew: %s." % exc)
        exe = tool()
        if exe and exe != own_copy():
            v, why = _try([exe])
            if v:
                return _installed(v, "Homebrew")
            tried.append("Homebrew's copy: %s." % why)
    else:
        tried.append("Homebrew isn't installed, so Sofa couldn't try that either.")
    store.log("error", "Couldn't install yt-dlp. " + " ".join(tried))
    raise RuntimeError("yt-dlp doesn't run on this computer yet. " + " ".join(tried) +
                       " Fix: install Python 3.12 from python.org, or Homebrew and then 'brew install yt-dlp', and press Install again.")


def _installed(v, how):
    store.log("download", "Installed yt-dlp %s (%s)" % (v, how))
    return v


def start_install():
    """The Install button: runs in the background (Homebrew can take a long time); status() reports it."""
    if install_state.get("running"):
        return

    def run():
        install_state.clear()
        install_state.update(running=True, at=time.time())
        try:
            install_state.update(done=install(), error=None)
        except Exception as exc:
            text = str(getattr(exc, "reason", None) or exc)
            install_state.update(error=text if text.startswith("yt-dlp") else "Couldn't install yt-dlp: %s" % text[:300])
        finally:
            install_state.update(running=False, step=None)
    threading.Thread(target=run, daemon=True, name="install-ytdlp").start()


def _force_update():
    """Update Sofa's own copy now (at most once an hour). True if it was updated."""
    exe = tool()
    if exe != own_copy():
        return False
    stamp = own_copy() + ".forced"
    try:
        if time.time() - os.path.getmtime(stamp) < 3600:
            return False
    except OSError:
        pass
    open(stamp, "w").close()
    before = version()
    try:
        subprocess.run(_cmd(exe) + ["-U"], capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return False
    _known_version.clear()
    return version() != before


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
            "installing": {k: install_state.get(k) for k in ("running", "step", "error", "done")},
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
    return cmd + _cookies() + ["--", job["url"]]


BROWSERS = ("safari", "chrome", "firefox", "edge", "brave", "chromium", "opera", "vivaldi")
COOKIES_FILE = os.path.join(OWN_BIN, "cookies.txt")


def _cookies():
    """Sites that want a sign-in or an age check: use the session of a browser on this computer
    (sign in there first), or a cookies.txt file saved in data/bin."""
    choice = (config.get("ytdlp_cookies") or "").lower()
    if choice in BROWSERS:
        return ["--cookies-from-browser", choice]
    if choice == "file" and os.path.isfile(COOKIES_FILE):
        return ["--cookies", COOKIES_FILE]
    return []


def explain(error):
    """yt-dlp's last error line, in words."""
    e = error.lower()
    cookies = (config.get("ytdlp_cookies") or "").lower()
    signin = ("The site didn't hand over the video. It usually wants you signed in or to confirm your age "
              "(some countries require that). Do that in a browser on the Sofa computer, then choose that browser "
              "under \"Use the sign-in from\" below and try again." if not cookies else
              "The site didn't hand over the video, even with the %s sign-in. Open the page in %s on the Sofa "
              "computer, make sure it plays there, then try again." % (cookies.title(), cookies.title()))
    if "no video formats found" in e or "unable to extract" in e:
        return signin + " (If it still fails, the site may have changed; Sofa updates yt-dlp daily.)"
    if any(w in e for w in ("sign in", "login", "log in", "age", "verify", "confirm your", "403", "forbidden", "private video")):
        return signin
    if "unsupported url" in e:
        return "yt-dlp doesn't know this site, or this isn't the page of one video. Open the video itself and copy that address."
    if "could not copy" in e and "cookie" in e or "keychain" in e or "cookies database" in e:
        return ("Couldn't read the browser's sign-in. Safari needs Full Disk Access for the program running Sofa "
                "(System Settings, Privacy & Security); Firefox works without it.")
    if "max-filesize" in e or "larger than max" in e:
        return "It's bigger than the size limit set in Settings."
    if "404" in e or "not found" in e:
        return "The page isn't there any more."
    return error


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
            err = re.sub(r"^ERROR:\s*", "", next((x for x in reversed(tail) if "ERROR" in x), tail[-1] if tail else "yt-dlp stopped"))
            if not job.get("retried") and ("no video formats" in err.lower() or "unable to extract" in err.lower()) \
                    and _force_update():
                job = dict(job, retried=True)          # an older yt-dlp may not know the site's latest change
                with _lock:
                    _current.clear()
                return _run_one(job)
            raise RuntimeError(explain(err)[:400] + ("" if explain(err) == err else " [yt-dlp: %s]" % err[:160]))
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
            if media.should_wait():
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
