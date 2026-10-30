"""Updating Sofa itself from GitHub, without touching anything that's yours.

What an update replaces: Sofa's own code (sofa/, client/, deploy/, tools/, docs/,
sofa.py, README). What it never touches: your shows, movies and music (they live
outside this folder), and data/ (accounts, watch history, settings, artwork
cache) and vendor/ (a home-built ffmpeg).

Before updating, Sofa makes its usual backup of data/ and a copy of the current
code (data/backups/code-<version>-<date>.tar.gz), so an update can always be
undone. If the new code doesn't even compile, the old code is put back.

Installs made with `git clone` update with git (local edits are stashed, not lost);
others download the newest version as a .tar.gz from GitHub.
"""
import datetime
import io
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request

from . import __version__, backup, config, net, store

CODE = ("sofa", "client", "deploy", "tools", "docs", "integrations", "sofa.py", "README.md", "LICENSE", ".gitignore")
NEVER = ("data", "vendor", ".git")
STAMP_FILE = os.path.join(config.DATA_DIR, "installed-commit")
CHECK_EVERY = 12 * 3600
WATCH_FILE = os.path.join(config.DATA_DIR, "update-check.json")        # see watch_update() in sofa.py
ROLLED_BACK = os.path.join(config.DATA_DIR, "update-rolled-back.json")
AGENT = {"User-Agent": "Sofa updater (https://github.com/krintoxi/sofa)"}

_state = {"checked": 0, "running": False, "step": None, "error": None, "done": None}
_lock = threading.Lock()


def _repo():
    return config.get("update_repo"), config.get("update_branch")


def _get(url, timeout=20):
    with net.urlopen(urllib.request.Request(url, headers=AGENT), timeout=timeout) as r:
        return r.read()


def _git(*args, timeout=120):
    return subprocess.run(["git", "-C", config.APP_DIR] + list(args), capture_output=True, text=True, timeout=timeout)


def is_git_install():
    return os.path.isdir(os.path.join(config.APP_DIR, ".git")) and shutil.which("git") is not None


def local_commit():
    if is_git_install():
        r = _git("rev-parse", "HEAD")
        if r.returncode == 0:
            return r.stdout.strip()
    try:
        with open(STAMP_FILE) as f:
            return f.read().strip() or None
    except OSError:
        return None


def _vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3])


def check(force=False):
    """What's on GitHub compared with what's running. Cached for 12 hours unless forced."""
    with _lock:
        if not force and time.time() - _state["checked"] < CHECK_EVERY and "latest" in _state:
            return status()
    repo, branch = _repo()
    info = {"error": None}
    try:
        commit = json.loads(_get("https://api.github.com/repos/%s/commits/%s" % (repo, branch)))
        info["latest_commit"] = commit["sha"]
        info["latest_date"] = commit["commit"]["committer"]["date"]
        info["latest_message"] = commit["commit"]["message"].split("\n", 1)[0][:140]
    except Exception as exc:
        info["error"] = "Couldn't reach GitHub (%s)." % str(exc)[:120]
    try:
        text = _get("https://raw.githubusercontent.com/%s/%s/sofa/__init__.py" % (repo, branch)).decode()
        m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        info["latest"] = m.group(1) if m else None
    except Exception as exc:
        info["latest"] = None
        info["error"] = info["error"] or "Couldn't reach GitHub (%s)." % str(exc)[:120]
    with _lock:
        _state.update(info, checked=int(time.time()))
    return status()


def status():
    with _lock:
        s = dict(_state)
    mine = local_commit()
    newer_version = bool(s.get("latest")) and _vtuple(s["latest"]) > _vtuple(__version__)
    other_commit = bool(s.get("latest_commit")) and bool(mine) and s["latest_commit"] != mine
    s.update(current=__version__, commit=mine, method="git" if is_git_install() else "download",
             available=newer_version or other_commit or (not mine and bool(s.get("latest_commit"))
                                                         and _vtuple(s.get("latest")) >= _vtuple(__version__)),
             repo="%s@%s" % _repo())
    if s.get("latest") and _vtuple(s["latest"]) < _vtuple(__version__):
        s["available"] = False          # running something newer than GitHub (a development copy)
    try:
        with open(ROLLED_BACK, encoding="utf-8") as f:
            rb = json.load(f)
        if time.time() - rb.get("at", 0) < 7 * 86400:
            s["rolled_back"] = "Sofa %s kept stopping right after the update, so Sofa went back to %s by itself. " \
                "Nothing of yours was changed." % (rb.get("to") or "(new)", rb.get("back_to") or "the version before")
    except (OSError, ValueError):
        pass
    return s


def confirm_update():
    """The new version has run for a while: the update is good (sofa.py serve calls this)."""
    if os.path.exists(WATCH_FILE):
        try:
            os.remove(WATCH_FILE)
            store.log("update", "Sofa %s is up and running." % __version__)
        except OSError:
            pass
    if os.path.exists(ROLLED_BACK):
        try:
            with open(ROLLED_BACK, encoding="utf-8") as f:
                rb = json.load(f)
            if not rb.get("logged"):
                store.log("update", "Sofa %s kept stopping right after an update, so it went back to %s by itself."
                          % (rb.get("to") or "(new)", rb.get("back_to") or "the version before"))
                rb["logged"] = True
                with open(ROLLED_BACK, "w", encoding="utf-8") as f:
                    json.dump(rb, f)
        except (OSError, ValueError):
            pass


# ---------------------------------------------------------------- doing it

def _step(text):
    with _lock:
        _state["step"] = text
    store.log("update", text)


def _snapshot_code():
    """data/backups/code-<version>-<date>.tar.gz: today's code, so the update can be undone."""
    os.makedirs(backup.folder(), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = os.path.join(backup.folder(), "code-%s-%s.tar.gz" % (__version__, stamp))
    with tarfile.open(path, "w:gz") as tar:
        for name in CODE:
            p = os.path.join(config.APP_DIR, name)
            if os.path.exists(p):
                tar.add(p, arcname=name, filter=lambda t: None if "__pycache__" in t.name else t)
    return path


def _restore_code(snapshot):
    with tarfile.open(snapshot) as tar:
        for name in CODE:
            p = os.path.join(config.APP_DIR, name)
            if os.path.isdir(p):
                shutil.rmtree(p)
            elif os.path.exists(p):
                os.remove(p)
        tar.extractall(config.APP_DIR)


def _new_version():
    try:
        with open(os.path.join(config.APP_DIR, "sofa", "__init__.py"), encoding="utf-8") as f:
            return re.search(r'__version__ = "([^"]+)"', f.read()).group(1)
    except (OSError, AttributeError):
        return None


def _selftest():
    """Start the new version's parts once, on the side, while this one keeps running."""
    try:
        r = subprocess.run([sys.executable, os.path.join(config.APP_DIR, "sofa.py"), "selftest"], capture_output=True,
                           text=True, timeout=300, cwd=config.APP_DIR)
    except subprocess.TimeoutExpired:
        raise RuntimeError("the new version didn't finish its test start within five minutes")
    if r.returncode != 0 or "SELFTEST OK" not in r.stdout:
        lines = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError("the new version didn't start in a test run: %s" % (lines[-1] if lines else "no answer")[:240])


def _go_back(snapshot, before):
    if is_git_install() and before:
        _git("reset", "--hard", before)
    else:
        _restore_code(snapshot)


def _compiles():
    for d, _dirs, files in os.walk(os.path.join(config.APP_DIR, "sofa")):
        for f in files:
            if f.endswith(".py"):
                py_compile.compile(os.path.join(d, f), doraise=True)
    py_compile.compile(os.path.join(config.APP_DIR, "sofa.py"), doraise=True)


def _update_git():
    repo, branch = _repo()
    _step("Downloading the new version with git")
    r = _git("fetch", "https://github.com/%s.git" % repo, branch, timeout=600)
    if r.returncode != 0:
        raise RuntimeError("git fetch failed: %s" % (r.stderr.strip() or r.stdout.strip())[-200:])
    if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        _git("stash", "push", "-m", "Local changes saved by the Sofa updater %s" % time.strftime("%Y-%m-%d %H:%M"))
        store.log("update", "Your own edits to Sofa's code were saved with 'git stash' (see 'git stash list').")
    before = local_commit()
    r = _git("merge", "--ff-only", "FETCH_HEAD")
    if r.returncode != 0:
        r = _git("checkout", "-B", branch, "FETCH_HEAD")
        if r.returncode != 0:
            raise RuntimeError("git couldn't switch to the new version: %s" % r.stderr.strip()[-200:])
        store.log("update", "Moved to the GitHub version; the previous commit was %s." % (before or "?")[:10])


def _update_download():
    repo, branch = _repo()
    _step("Downloading the new version from GitHub")
    data = _get("https://codeload.github.com/%s/tar.gz/refs/heads/%s" % (repo, branch), timeout=600)
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                if m.name.startswith("/") or ".." in m.name.split("/") or m.issym() or m.islnk():
                    raise RuntimeError("the download looks wrong (unsafe paths); nothing was changed")
            tar.extractall(tmp)
        top = [os.path.join(tmp, n) for n in os.listdir(tmp)]
        src = top[0] if len(top) == 1 and os.path.isdir(top[0]) else tmp
        if not os.path.isfile(os.path.join(src, "sofa.py")) or not os.path.isfile(os.path.join(src, "sofa", "__init__.py")):
            raise RuntimeError("the download doesn't look like Sofa; nothing was changed")
        _step("Replacing Sofa's code (your media, accounts and settings stay as they are)")
        for name in CODE:
            new, old = os.path.join(src, name), os.path.join(config.APP_DIR, name)
            if not os.path.exists(new) or name in NEVER:
                continue
            if os.path.isdir(old):
                shutil.rmtree(old)
            elif os.path.exists(old):
                os.remove(old)
            (shutil.copytree if os.path.isdir(new) else shutil.copy2)(new, old)
    sha = _state.get("latest_commit")
    if sha:
        with open(STAMP_FILE, "w") as f:
            f.write(sha)


def _run():
    try:
        _step("Backing up accounts, watch history and settings")
        backup.make("before updating Sofa")
        snapshot, before = _snapshot_code(), local_commit()
        try:
            (_update_git if is_git_install() else _update_download)()
            _step("Checking the new version")
            _compiles()
            _step("Starting the new version once on the side, to be sure it works")
            _selftest()
        except Exception:
            _go_back(snapshot, before)
            raise
        with open(WATCH_FILE, "w", encoding="utf-8") as f:     # after the switch: go back by itself if it keeps stopping
            json.dump({"from": __version__, "to": _new_version(), "commit": before if is_git_install() else None,
                       "snapshot": snapshot, "at": int(time.time()), "starts": 0}, f)
        try:
            os.remove(ROLLED_BACK)
        except OSError:
            pass
        with _lock:
            _state.update(done=int(time.time()), running=False, step="Restarting Sofa")
        store.log("update", "Sofa updated. Restarting.")
        threading.Timer(2.0, restart).start()
    except Exception as exc:
        with _lock:
            _state.update(running=False, error=str(exc)[:300], step=None)
        store.log("update", "The update didn't work, so the old version keeps running: %s" % str(exc)[:200])


def start_update():
    with _lock:
        if _state["running"]:
            return False
        _state.update(running=True, error=None, done=None, step="Starting")
    threading.Thread(target=_run, daemon=True, name="updater").start()
    return True


def restart():
    """Start this same process again with the new code (launchd/systemd see the same process carry on)."""
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os.execv(sys.executable, [sys.executable, os.path.join(config.APP_DIR, "sofa.py")] + sys.argv[1:])


def _loop():
    time.sleep(120)
    while True:
        try:
            s = check()
            if s.get("available"):
                store.log("update", "A new version of Sofa is available (%s). Update it from the Server page." % (s.get("latest") or "newer"))
        except Exception:
            pass
        time.sleep(CHECK_EVERY)


def start():
    threading.Thread(target=_loop, daemon=True, name="update-check").start()
