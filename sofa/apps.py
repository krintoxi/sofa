"""Sofa's own TV apps, kept on the Sofa computer, so TVs at home get them from here (even offline).

The Fire TV app is built by GitHub (android/) and published on the repository's Releases page as
"firetv-<build>". Sofa fetches the newest into data/apps/ a minute after it starts and then once a
day (never in offline mode, where you put the file there yourself). Fire TVs then get it from Sofa:
- "Install the Sofa app" in Silk: Sofa installs it over the network (adb.py), opens it, done;
- or the Downloader app at http://<sofa>:8090/firetv.
The app itself shows "Update" when Sofa has a newer one, and installs it the same way.
"""
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
import zipfile

from . import adb, config, net, store

FIRETV_APK = os.path.join(config.DATA_DIR, "apps", "sofa-firetv.apk")
FIRETV_INFO = os.path.join(config.DATA_DIR, "apps", "sofa-firetv.json")
PACKAGE, ACTIVITY = "uk.edgeventure.sofa", "uk.edgeventure.sofa/.MainActivity"
_lock = threading.Lock()
_fetching = {"on": False, "error": None}
_jobs = {}                      # Fire TV address -> {"state", "message", "progress", "at"}


def firetv():
    """The Fire TV app on this computer: {"version", "size", "at"}, or None."""
    if not os.path.isfile(FIRETV_APK):
        return None
    try:
        with open(FIRETV_INFO, encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        info = {}                           # put there by hand: we don't know its version
    if info.get("size") != os.path.getsize(FIRETV_APK):
        info = {}
    return {"version": info.get("version"), "size": os.path.getsize(FIRETV_APK),
            "at": info.get("at") or int(os.path.getmtime(FIRETV_APK))}


def status():
    return {"firetv": firetv(), "fetching": _fetching["on"], "error": _fetching["error"], "offline": net.offline_mode()}


def _get(url, timeout=60):
    from .updater import AGENT
    with net.urlopen(urllib.request.Request(url, headers=dict(AGENT, Accept="application/vnd.github+json")), timeout=timeout) as r:
        return r.read()


def newest_release():
    """(build, download address, size, sha256 or None) of the newest Fire TV app on GitHub, or None."""
    from .updater import repo_name
    best = None
    for rel in json.loads(_get("https://api.github.com/repos/%s/releases?per_page=30" % repo_name()).decode("utf-8")):
        m = re.match(r"^firetv-(\d+)$", rel.get("tag_name") or "")
        if not m or rel.get("draft") or rel.get("prerelease"):
            continue
        asset = next((a for a in rel.get("assets") or [] if a.get("name") == "sofa-firetv.apk"), None)
        if asset and (not best or int(m.group(1)) > best[0]):
            digest = (asset.get("digest") or "").partition("sha256:")[2] or None
            best = (int(m.group(1)), asset["browser_download_url"], asset.get("size"), digest)
    return best


def _looks_like_apk(path):
    try:
        with zipfile.ZipFile(path) as z:
            return "AndroidManifest.xml" in z.namelist() and "classes.dex" in z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def fetch(force=False):
    """Get the newest Fire TV app from GitHub if this computer doesn't have it yet. True if it changed."""
    with _lock:
        if _fetching["on"]:
            return False
        _fetching.update(on=True, error=None)
    try:
        rel = newest_release()
        have = firetv()
        if not rel or (have and have["version"] and have["version"] >= rel[0] and not force):
            return False
        build, url, size, digest = rel
        os.makedirs(os.path.dirname(FIRETV_APK), exist_ok=True)
        part = FIRETV_APK + ".part"
        data = _get(url, timeout=180)
        if (size and len(data) != size) or (digest and hashlib.sha256(data).hexdigest() != digest):
            raise ValueError("the download didn't match what GitHub says it is")
        with open(part, "wb") as f:
            f.write(data)
        if not _looks_like_apk(part):
            os.remove(part)
            raise ValueError("the download isn't an Android app")
        os.replace(part, FIRETV_APK)
        with open(FIRETV_INFO, "w", encoding="utf-8") as f:
            json.dump({"version": build, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "at": int(time.time())}, f)
        store.log("apps", "Got the Fire TV app (version %d), ready for Fire TVs at home" % build)
        return True
    except net.Offline:
        return False
    except Exception as exc:
        _fetching["error"] = str(exc)[:200]
        raise
    finally:
        _fetching["on"] = False


def _loop():
    time.sleep(60)
    while True:
        if not net.offline_mode():
            try:
                fetch()
            except Exception:
                pass
        time.sleep(24 * 3600)


def start():
    threading.Thread(target=_loop, daemon=True, name="apps").start()


# ---------------------------------------------------------------- installing it on a Fire TV

STEPS = {
    "getting": "Getting the app onto this computer…",
    "preparing": "Getting ready (the first time takes a few seconds)…",
    "connecting": "Connecting to this Fire TV…",
    "approve": "On the TV: tick \"Always allow from this computer\", then press OK.",
    "copying": "Copying the app to the Fire TV…",
    "installing": "Installing it…",
    "opening": "Opening Sofa…",
    "done": "Done. Sofa is on this Fire TV now: it's under Your Apps & Channels.",
}


def _set(ip, state, message=None, progress=None):
    _jobs[ip] = {"state": state, "message": message or STEPS.get(state, ""), "progress": progress, "at": time.time()}


def install_status(ip):
    return _jobs.get(ip) or {"state": "idle"}


def start_install(ip, who):
    """Install (or update) the Fire TV app on the Fire TV at `ip`, in the background."""
    job = _jobs.get(ip)
    if job and job["state"] not in ("done", "failed") and time.time() - job["at"] < 180:
        return False
    _set(ip, "getting" if not firetv() else "preparing")
    threading.Thread(target=_install, args=(ip, who), daemon=True, name="firetv-install").start()
    return True


def _install(ip, who):
    try:
        if not firetv():
            try:
                fetch()
            except Exception:
                pass
        if not firetv():
            return _set(ip, "failed", "The Fire TV app isn't on the Sofa computer yet, and it couldn't be fetched "
                                      "(Sofa is offline, or GitHub can't be reached). See Server → Overview → Apps.")
        _set(ip, "preparing")
        key = adb.key()
        _set(ip, "connecting")
        with open(FIRETV_APK, "rb") as f:
            data = f.read()
        dev = adb.Device(ip)
        try:
            dev.connect(key, asking=lambda: _set(ip, "approve"))
        except (adb.AdbError, OSError) as exc:          # refused, timed out, or closed on us
            dev.close()
            if isinstance(exc, adb.NotAllowed) or _jobs[ip]["state"] == "approve":
                raise adb.NotAllowed() from exc
            return _set(ip, "failed", "This Fire TV didn't answer. Turn on ADB debugging: Settings → My Fire TV → "
                                      "Developer options → ADB debugging. (No Developer options? Settings → My Fire TV → "
                                      "About, then press OK on the Fire TV's name 7 times.)")
        with dev:
            _set(ip, "copying", progress=0)
            tmp = "/data/local/tmp/sofa-firetv.apk"
            dev.push(data, tmp, progress=lambda p: _set(ip, "copying", progress=round(p, 2)))
            _set(ip, "installing")
            out = dev.shell("pm install -r %s" % tmp).strip()
            dev.shell("rm %s" % tmp)
            if "Success" not in out:
                reason = re.search(r"\[(\w+)", out)
                if reason and reason.group(1) == "INSTALL_FAILED_UPDATE_INCOMPATIBLE":
                    return _set(ip, "failed", "A Sofa app from somewhere else is on this Fire TV. Uninstall it (Settings → "
                                              "Applications → Manage Installed Applications → Sofa), then try again.")
                return _set(ip, "failed", "The Fire TV couldn't install it: %s" % (out[-200:] or "no reason given"))
            _set(ip, "opening")
            dev.shell("am start -n %s" % ACTIVITY)
        info = firetv() or {}
        store.log("apps", "%s put the Sofa app%s on a Fire TV" % (who, " (version %s)" % info["version"] if info.get("version") else ""))
        _set(ip, "done")
    except adb.NotAllowed:
        _set(ip, "failed", "The Fire TV didn't allow it. Try again, and on the TV tick \"Always allow from this computer\", "
                           "then press OK.")
    except Exception as exc:
        _set(ip, "failed", "That didn't work: %s" % str(exc)[:200])

