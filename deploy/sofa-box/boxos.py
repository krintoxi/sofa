"""Sofa Box OS: the home screen's apps, the store, icons, files and ad blocking, and the box's one
Chromium, steered over its DevTools port: every app is a tab the agent opens, brings forward and
closes. Used by sofa-box-agent.py. Standard library only (Python 3.7+).

The plan and the reasons are in docs/sofa-box-os.md.
"""
import base64
import collections
import html
import http.client
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEVTOOLS_PORT = int(os.environ.get("SOFA_BOX_DEVTOOLS", "9222"))
def memory_mb():
    try:
        with open("/proc/meminfo") as f:
            return int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1)) // 1024
    except (OSError, AttributeError):
        return 4096


# Apps open at once (besides Home): older ones that aren't playing close. By memory: 1 GB (a Pi 3) two,
# 2 GB three, 4 GB four, 8 GB six.
MAX_APP_TABS = int(os.environ.get("SOFA_BOX_MAX_TABS") or
                   (2 if memory_mb() <= 1100 else 3 if memory_mb() <= 2200 else 4 if memory_mb() <= 4500 else 6))
KEEP_AWAKE = ("sofa",)                 # never frozen: Sofa listens for the phone's "Play on"
# What a report keeps of the pages (Browser.notes): their errors, and what their video players say: which decoder
# plays (the Pi's own, or the processor), and why one stopped.
ROUTINE = re.compile(r'"event":\s*"k(Ended|Seek|Play|Pause|PipelineStateChange|BufferingStateChanged)"')
NOTED = ("Runtime.exceptionThrown", "Runtime.consoleAPICalled", "Log.entryAdded", "Media.playerErrorsRaised",
         "Media.playerMessagesLogged", "Media.playerPropertiesChanged", "Media.playerEventsAdded")
MEDIA_PROPS = ("kVideoCodecName", "kVideoDecoderName", "kIsPlatformVideoDecoder", "kAudioCodecName", "kAudioDecoderName",
               "kResolution", "kFramerate", "kRendererName")
DRAWN_JS = ("location.href !== 'about:blank' && document.readyState !== 'loading' && !!document.body "
            "&& document.body.childElementCount > 0")
PLAYING_JS = "Array.from(document.querySelectorAll('video,audio')).some(m => !m.paused && !m.muted && m.volume > 0)"
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_web = urllib.request.build_opener()  # sites on the internet (the system's proxy settings apply)
UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 SofaBox/1"
TV_UA = ("Mozilla/5.0 (Linux; Tizen 6.5) AppleWebKit/537.36 (KHTML, like Gecko) Version/6.5 TV Safari/537.36 "
         "Cobalt/23.lts.4.308289-gold (unlike Gecko) v8/8.8.278.17-jit gles Starboard/15")


# ---------------------------------------------------------------- the apps on the home screen

BUILTIN = [   # always there; can be moved and hidden, not removed
    {"id": "sofa", "name": "Sofa", "kind": "builtin", "url": "/?tv=1", "color": "#F4B740", "icon": "sofa", "category": "watch"},
    {"id": "live", "name": "Live TV", "kind": "builtin", "url": "", "color": "#FF4D5E", "icon": "live", "category": "watch"},
    {"id": "browser", "name": "Browser", "kind": "builtin", "url": "/box/home#/browser", "color": "#4DA3FF", "icon": "browser"},
    {"id": "store", "name": "App Store", "kind": "builtin", "url": "/box/home#/store", "color": "#C792FF", "icon": "store"},
    {"id": "games", "name": "Games", "kind": "builtin", "url": "/box/home#/games", "color": "#8BD46E", "icon": "games"},
    {"id": "files", "name": "Files", "kind": "builtin", "url": "/box/home#/files", "color": "#3CC8D8", "icon": "files"},
    {"id": "settings", "name": "Settings", "kind": "builtin", "url": "/box/home#/settings", "color": "#8C94AB", "icon": "settings"},
]
FIRST_APPS = ["edge-music", "lj-showroom", "lj-fragrances", "youtube-tv"]   # installed on a new box


class Apps:
    """~/.config/sofa-box/apps.json: the installed apps and the home screen's order."""

    def __init__(self, conf_dir):
        self.dir = conf_dir
        self.path = os.path.join(conf_dir, "apps.json")
        self.icons = os.path.join(conf_dir, "icons")
        self.lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict):                       # a new box: our own apps to begin with
            data = {"apps": [], "order": [], "hidden": []}
            for sid in FIRST_APPS:
                entry = store_entry(sid)
                if entry:
                    data["apps"].append(app_from_store(entry))
            try:
                self._save(data)
            except OSError:
                return data
            for a in data["apps"]:
                threading.Thread(target=self._fetch_icon, args=(a["id"], a.get("icon_src") or a["url"]), daemon=True).start()
        return data

    def _save(self, data):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path + ".new"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    def listing(self):
        """Every app, in the home screen's order: Sofa's own first, then what was installed."""
        with self.lock:
            data = self._load()
        apps = [dict(a) for a in BUILTIN] + [dict(a) for a in data["apps"]]
        sections = None
        for a in apps:                                      # apps from before the store had sections: theirs now
            if not a.get("category"):
                if sections is None:
                    sections = {e["id"]: sec["id"] for sec in store()["sections"] for e in sec["apps"]}
                a["category"] = sections.get(a["id"], "web")
        order = data.get("order") or []
        place = {a["id"]: (order.index(a["id"]) if a["id"] in order else len(order) + i) for i, a in enumerate(apps)}
        apps.sort(key=lambda a: place[a["id"]])
        for a in apps:
            a["hidden"] = a["id"] in (data.get("hidden") or [])
            if a.get("icon_file"):
                try:                                        # (versioned: a newer picture isn't the browser's old one)
                    v = int(os.path.getmtime(os.path.join(self.icons, a["icon_file"])))
                except OSError:
                    v = 0
                a["icon_url"] = "/box/icons/%s?v=%d" % (a["icon_file"], v)
        return apps

    def get(self, app_id):
        return next((a for a in self.listing() if a["id"] == app_id), None)

    def install(self, entry):
        """Put an app on the home screen (from the store, or any site). Returns it; its icon comes after,
        unless the store's copy of it is here already."""
        app = app_from_store(entry)
        ready = store_icons.copy_to(app["id"], self.icons)
        if ready:
            app["icon_file"] = ready
        with self.lock:
            data = self._load()
            data["apps"] = [a for a in data["apps"] if a["id"] != app["id"]] + [app]
            self._save(data)
        if not ready:
            threading.Thread(target=self._fetch_icon, args=(app["id"], app.get("icon_src") or app["url"]), daemon=True).start()
        return app

    def _fetch_icon(self, app_id, url):
        name = fetch_icon(url, self.icons, app_id)
        if name:
            with self.lock:
                data = self._load()
                for a in data["apps"]:
                    if a["id"] == app_id:
                        a["icon_file"] = name
                self._save(data)

    def refresh_icons(self):
        """Once, when the box gets better at finding icons (ICONS_VERSION): every app's picture again, the store's
        current one first, one at a time in the background."""
        mark = os.path.join(self.icons, ".version")
        try:
            with open(mark) as f:
                if f.read().strip() == ICONS_VERSION:
                    return
        except OSError:
            pass

        def work():
            for a in [a for a in self.listing() if a.get("kind") == "web"]:
                entry = store_entry(a["id"]) or {}
                try:
                    self._fetch_icon(a["id"], entry.get("icon") or a.get("icon_src") or a["url"])
                except Exception:
                    pass
            os.makedirs(self.icons, exist_ok=True)
            with open(mark, "w") as f:
                f.write(ICONS_VERSION)
        threading.Thread(target=work, daemon=True, name="icons-again").start()

    def remove(self, app_id):
        with self.lock:
            data = self._load()
            before = len(data["apps"])
            data["apps"] = [a for a in data["apps"] if a["id"] != app_id]
            self._save(data)
        for f in os.listdir(self.icons) if os.path.isdir(self.icons) else []:
            if f.startswith(app_id + "."):
                os.remove(os.path.join(self.icons, f))
        return len(data["apps"]) < before

    def arrange(self, order=None, hidden=None):
        known = {a["id"] for a in self.listing()}
        with self.lock:
            data = self._load()
            if order is not None:
                data["order"] = [i for i in order if i in known]
            if hidden is not None:
                data["hidden"] = [i for i in hidden if i in known]
            self._save(data)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "app"


def app_from_store(entry):
    url = entry["url"]
    return {"id": entry.get("id") or slug(urllib.parse.urlsplit(url).netloc.replace("www.", "")),
            "name": (entry.get("name") or urllib.parse.urlsplit(url).netloc.replace("www.", ""))[:40],
            "kind": "web", "url": url, "color": entry.get("color") or "#4DA3FF", "ua": entry.get("ua") or "",
            "icon_src": entry.get("icon") or "", "added": int(time.time()), "category": entry.get("section") or "web"}


# ---------------------------------------------------------------- the store

def store():
    with open(os.path.join(HERE, "store.json"), encoding="utf-8") as f:
        return json.load(f)


def store_entry(sid):
    for section in store()["sections"]:
        for e in section["apps"]:
            if e["id"] == sid:
                return dict(e, section=section["id"])
    return None


class StoreIcons:
    """The store's icons, fetched by the box from each site (its own home screen icon) the first time the
    store is opened, one at a time, and kept: the store and Home show the real icons, not letters."""

    def __init__(self, folder=None):
        self.folder = folder
        self.queue, self.lock, self.busy, self.tried = [], threading.Lock(), False, {}

    def file(self, sid):
        if not self.folder or not os.path.isdir(self.folder):
            return None
        mark = os.path.join(self.folder, ".version")
        if not os.path.exists(mark):                        # icons from before ICONS_VERSION: fetched again
            for old in os.listdir(self.folder):
                if not old.startswith("."):
                    os.remove(os.path.join(self.folder, old))
            with open(mark, "w") as f:
                f.write(ICONS_VERSION)
        return next((f for f in os.listdir(self.folder) if f.rsplit(".", 1)[0] == sid and not f.startswith(".")), None)

    def want(self, entries):
        with self.lock:
            for e in entries:
                if not self.file(e["id"]) and time.time() - self.tried.get(e["id"], 0) > 86400 and e not in self.queue:
                    self.queue.append(e)
            if self.queue and not self.busy:
                self.busy = True
                threading.Thread(target=self._work, daemon=True, name="store-icons").start()

    def _work(self):
        while True:
            with self.lock:
                if not self.queue:
                    self.busy = False
                    return
                e = self.queue.pop(0)
                self.tried[e["id"]] = time.time()
            try:
                fetch_icon(e.get("icon") or e["url"], self.folder, e["id"])
            except Exception:                              # one site's trouble mustn't stop the rest
                pass

    def copy_to(self, sid, folder):
        name = self.file(sid)
        if not name:
            return None
        os.makedirs(folder, exist_ok=True)
        shutil.copyfile(os.path.join(self.folder, name), os.path.join(folder, name))
        return name


store_icons = StoreIcons()


def site_entry(url, name=None):
    """Any site, as an app (the store's "Add a site", the browser's Add to Home)."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if not parts.netloc or " " in parts.netloc:
        raise ValueError("That doesn't look like a web address.")
    return {"id": slug(parts.netloc.replace("www.", "") + parts.path.rstrip("/").replace("/", "-")),
            "name": (name or parts.netloc.replace("www.", "")).strip()[:40], "url": url}


ICON_LINK = re.compile(r"<link\b[^>]*>", re.I)
ICON_PATHS = (("/android-chrome-512x512.png", 512), ("/apple-touch-icon.png", 180), ("/apple-touch-icon-precomposed.png", 180),
              ("/android-chrome-192x192.png", 192))      # where sites keep their home screen icons, linked or not
ICONS_VERSION = "2"


def image_width(data):
    """How wide a picture is, from its first bytes (PNG, JPEG, ICO's biggest, WebP; an SVG counts as large)."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">I", data[16:20])[0]
        if data[:4] == b"\x00\x00\x01\x00":                          # ICO: a directory of sizes (0 means 256)
            return max((data[6 + 16 * i] or 256) for i in range(min(struct.unpack("<H", data[4:6])[0], 32)))
        if data[:3] == b"\xff\xd8\xff":                                # JPEG: the frame header's width
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker, size = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2):
                    return struct.unpack(">H", data[i + 7:i + 9])[0]
                i += 2 + size
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return (struct.unpack("<I", data[24:27] + b"\0")[0] & 0xFFFFFF) + 1 if data[12:16] == b"VP8X" else 0
        if b"<svg" in data[:1000].lower():
            return 1024
    except (IndexError, struct.error, ValueError):
        pass
    return 0


def fetch_icon(url, folder, app_id, timeout=10):
    """The site's best picture for a home screen tile: its manifest's biggest icon, its apple-touch-icon, the places
    sites keep those without linking them, or its favicon. The few likeliest are fetched and the sharpest kept (a
    "180" can be 57 pixels). Saved as <app id>.<ext>; returns the file name, or None."""
    def get(u, limit=2_000_000):
        req = urllib.request.Request(u, headers={"User-Agent": UA})
        with _web.open(req, timeout=timeout) as r:
            try:
                body = r.read(limit)
            except http.client.IncompleteRead as exc:      # a site that hangs up part way: what came is enough for a page
                if "html" not in r.headers.get("Content-Type", ""):
                    raise OSError("cut off") from exc
                body = exc.partial
            return body, r.headers.get("Content-Type", ""), r.geturl()
    try:
        candidates = []
        if re.search(r"\.(png|jpe?g|svg|webp|ico)(\?|$)", url, re.I):
            candidates.append((10000, url))
        else:
            page, _, final = get(url)
            text = page.decode("utf-8", "replace")
            for tag in ICON_LINK.findall(text):
                rel = (re.search(r'rel=["\']?([^"\'>]+)', tag, re.I) or [None, ""])[1].lower()
                href = (re.search(r'href=["\']?([^"\'\s>]+)', tag, re.I) or [None, ""])[1]
                if not href:
                    continue
                href = urllib.parse.urljoin(final, html.unescape(href))
                size = int((re.search(r'sizes=["\']?(\d+)', tag, re.I) or [None, "0"])[1])
                if "manifest" in rel:
                    try:
                        man = json.loads(get(href)[0].decode("utf-8", "replace"))
                        for icon in man.get("icons") or []:
                            s = max([int(x.split("x")[0]) for x in (icon.get("sizes") or "0x0").split() if "x" in x] or [0])
                            candidates.append((s + 1, urllib.parse.urljoin(href, icon.get("src", ""))))
                    except (OSError, ValueError, AttributeError):
                        pass
                elif "apple-touch-icon" in rel:
                    candidates.append((max(size, 180), href))
                elif "icon" in rel:
                    candidates.append((size or 32, href))
            origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(final))
            candidates += [(size, origin + path) for path, size in ICON_PATHS]
            candidates.append((16, urllib.parse.urljoin(final, "/favicon.ico")))
        best, seen = None, set()
        for _, src in sorted(candidates, reverse=True)[:8]:
            if src in seen:
                continue
            seen.add(src)
            try:
                data, ctype, _ = get(src)
            except (OSError, http.client.HTTPException):
                continue
            if len(data) < 100 or b"<html" in data[:200].lower():
                continue
            ext = ("svg" if "svg" in ctype or src.lower().split("?")[0].endswith(".svg") else
                   "ico" if "icon" in ctype or src.lower().split("?")[0].endswith(".ico") else
                   "jpg" if "jpeg" in ctype else "webp" if "webp" in ctype else "png")
            width = image_width(data)
            if not best or width > best[0]:
                best = (width, data, ext)
            if width >= 180:                                # sharp enough on a TV tile: no need to look further
                break
        if not best:
            return None
        os.makedirs(folder, exist_ok=True)
        for old in os.listdir(folder):                      # one picture per app (it may have changed kind)
            if old.rsplit(".", 1)[0] == app_id:
                os.remove(os.path.join(folder, old))
        name = "%s.%s" % (app_id, best[2])
        with open(os.path.join(folder, name), "wb") as f:
            f.write(best[1])
        return name
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return None


# ---------------------------------------------------------------- files (downloads, music, USB drives)

KINDS = {"video": ("mp4", "mkv", "avi", "mov", "m4v", "webm", "ts", "wmv", "mpg", "mpeg"),
         "audio": ("mp3", "m4a", "aac", "flac", "ogg", "opus", "wav"),
         "image": ("jpg", "jpeg", "png", "gif", "webp", "bmp"),
         "archive": ("zip", "tar", "gz", "7z", "rar", "xz")}


def roots():
    """The places Files shows: the box's own folders, and any USB drive plugged in."""
    home = os.path.expanduser("~")
    out = []
    for name, folder in (("Downloads", "Downloads"), ("Videos", "Videos"), ("Music", "Music"), ("Pictures", "Pictures")):
        path = os.path.join(home, folder)
        os.makedirs(path, exist_ok=True)
        out.append({"id": folder.lower(), "name": name, "path": path, "drive": False})
    for base in ("/media/" + os.path.basename(home), "/run/media/" + os.path.basename(home), "/media", "/mnt"):
        try:
            for d in sorted(os.listdir(base)):
                p = os.path.join(base, d)
                if os.path.ismount(p):
                    out.append({"id": "drive-" + slug(d), "name": d, "path": p, "drive": True})
        except OSError:
            pass
    return out


def resolve(root_id, rel=""):
    """A path inside one of the roots, or ValueError (nothing outside them, ever)."""
    root = next((r for r in roots() if r["id"] == root_id), None)
    if not root:
        raise ValueError("That place isn't there any more.")
    full = os.path.realpath(os.path.join(root["path"], (rel or "").lstrip("/")))
    base = os.path.realpath(root["path"])
    if full != base and not full.startswith(base + os.sep):
        raise ValueError("That's outside the box's folders.")
    return root, full


def kind_of(name):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return next((k for k, exts in KINDS.items() if ext in exts), "file")


def listing(root_id, rel=""):
    root, full = resolve(root_id, rel)
    items = []
    for name in os.listdir(full):
        if name.startswith("."):
            continue
        p = os.path.join(full, name)
        try:
            st = os.stat(p)
        except OSError:
            continue
        isdir = os.path.isdir(p)
        items.append({"name": name, "dir": isdir, "size": None if isdir else st.st_size, "mtime": int(st.st_mtime),
                      "kind": "folder" if isdir else kind_of(name)})
    items.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    usage = shutil.disk_usage(full)
    rel = os.path.relpath(full, os.path.realpath(root["path"]))
    return {"root": {k: root[k] for k in ("id", "name", "drive")}, "path": "" if rel == "." else rel,
            "items": items, "free": usage.free, "total": usage.total}


def file_action(action, data):
    """delete, rename, move, folder: within the roots only."""
    root, full = resolve(data.get("root"), data.get("path"))
    if full == os.path.realpath(root["path"]):
        raise ValueError("That's a whole folder of the box.")
    if action == "delete":
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)
        return {"ok": True}
    if action == "rename":
        new = os.path.basename(str(data.get("name") or "")).strip()
        if not new or new.startswith("."):
            raise ValueError("Give it a name.")
        target = os.path.join(os.path.dirname(full), new)
        if os.path.exists(target):
            raise ValueError("Something has that name already.")
        os.rename(full, target)
        return {"ok": True}
    if action == "move":
        _, dest = resolve(data.get("to_root"), data.get("to_path") or "")
        if not os.path.isdir(dest):
            raise ValueError("Move it into a folder.")
        target = os.path.join(dest, os.path.basename(full))
        if os.path.exists(target):
            raise ValueError("There's one with that name there already.")
        shutil.move(full, target)
        return {"ok": True}
    raise ValueError("Unknown action.")


def make_folder(root_id, rel, name):
    _, full = resolve(root_id, rel)
    name = os.path.basename(str(name or "")).strip()
    if not name or name.startswith("."):
        raise ValueError("Give it a name.")
    os.makedirs(os.path.join(full, name), exist_ok=False)
    return {"ok": True}


# ---------------------------------------------------------------- USB drives and discs

DISC_NAMES = {"dvd": "DVD", "bluray": "Blu-ray", "cd": "music CD", "data": "disc"}
_mount_tried = {}


def _lsblk():
    code, out = run(["lsblk", "-J", "-b", "-o", "NAME,PATH,FSTYPE,LABEL,MOUNTPOINT,RM,HOTPLUG,TYPE,TRAN,SIZE"], 10)
    if code != 0:
        return []
    try:
        top = json.loads(out).get("blockdevices") or []
    except ValueError:
        return []
    flat = []

    def walk(devs, parent=None):
        for d in devs:
            d["parent_tran"] = (parent or {}).get("tran") or d.get("tran")
            d["parent_hotplug"] = (parent or {}).get("hotplug") or d.get("hotplug")
            flat.append(d)
            walk(d.get("children") or [], d)
    walk(top)
    return flat


def _disc_kind(dev):
    """What's in an optical drive: "dvd", "bluray", "cd" (music), "data", or None (empty)."""
    code, out = run(["udevadm", "info", "--query=property", "--name=" + dev], 5)
    if code != 0:
        return None
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if props.get("ID_CDROM_MEDIA") != "1":
        return None
    if props.get("ID_CDROM_MEDIA_BD") == "1" or props.get("ID_CDROM_MEDIA_BD_R") == "1":
        return "bluray"
    if int(props.get("ID_CDROM_MEDIA_TRACK_COUNT_AUDIO") or 0) > 0 and not props.get("ID_FS_TYPE"):
        return "cd"
    if any(k.startswith("ID_CDROM_MEDIA_DVD") and v == "1" for k, v in props.items()):
        return "dvd"
    return "data" if props.get("ID_FS_TYPE") else "cd"


def devices(mount=False):
    """USB drives (mounted by udisks as they're plugged in when `mount`) and a disc in a USB DVD drive."""
    drives, disc = [], None
    for d in _lsblk():
        hot = d.get("parent_hotplug") in (True, "1", 1) or d.get("parent_tran") == "usb" or d.get("rm") in (True, "1", 1)
        if d.get("type") == "rom":
            kind = _disc_kind(d.get("path") or "/dev/" + d["name"])
            if kind:
                disc = {"dev": d.get("path") or "/dev/" + d["name"], "kind": kind, "label": d.get("label") or DISC_NAMES[kind].capitalize(),
                        "mount": d.get("mountpoint")}
                if kind == "data" and mount and not d.get("mountpoint"):
                    run(["udisksctl", "mount", "--no-user-interaction", "-b", disc["dev"]], 30)
            continue
        if not hot or d.get("type") != "part" and not (d.get("type") == "disk" and d.get("fstype")):
            continue
        if not d.get("fstype") or d.get("fstype") in ("swap", "LVM2_member", "crypto_LUKS"):
            continue
        mp, dev = d.get("mountpoint"), d.get("path") or "/dev/" + d["name"]
        if not mp and mount and time.time() - _mount_tried.get(dev, 0) > 60:      # a drive that won't mount: once a minute
            _mount_tried[dev] = time.time()
            code, out = run(["udisksctl", "mount", "--no-user-interaction", "-b", dev], 30)
            m = re.search(r" at (/\S+)", out)
            mp = m.group(1).rstrip(".") if code == 0 and m else None
        if mp and mp not in ("/", "/boot", "/boot/firmware"):
            drives.append({"dev": d.get("path") or "/dev/" + d["name"], "label": d.get("label") or os.path.basename(mp),
                           "mount": mp, "size": int(d.get("size") or 0), "root": "drive-" + slug(os.path.basename(mp))})
    return {"drives": drives, "disc": disc}


def eject(dev):
    """Safely remove a USB drive (or open the disc tray)."""
    if not re.match(r"^/dev/[\w-]+$", dev or ""):
        raise ValueError("Which drive?")
    if dev.startswith(("/dev/sr", "/dev/cdrom")):
        code, out = run(["eject", dev], 20)
        return {"ok": code == 0, "message": "The tray is open." if code == 0 else out[-160:]}
    code, out = run(["udisksctl", "unmount", "--no-user-interaction", "-b", dev], 30)
    if code != 0:
        return {"ok": False, "message": "It's still in use. Close what's playing from it, then try again." if "busy" in out.lower() else out[-160:]}
    parent = re.sub(r"(p?\d+)$", "", dev) if re.search(r"\d$", dev) else dev
    run(["udisksctl", "power-off", "--no-user-interaction", "-b", parent], 20)
    return {"ok": True, "message": "You can take the drive out now."}


def disc_payload(disc):
    """How the box's player opens a disc (mpv reads DVDs, Blu-rays and music CDs by itself; discs with copy
    protection need libdvdcss / libaacs, which the box doesn't come with)."""
    url = {"dvd": "dvd://", "bluray": "bd://", "cd": "cdda://"}.get(disc["kind"])
    if not url:
        raise ValueError("That disc has files on it: open it in Files.")
    opt = {"dvd": "dvd-device", "bluray": "bluray-device", "cd": "cdrom-device"}[disc["kind"]]
    return {"url": url, "local": True, "title": disc.get("label") or DISC_NAMES[disc["kind"]], "item": None, "mpv": {opt: disc["dev"]}}


# ---------------------------------------------------------------- Bluetooth: remotes, controllers, keyboards, speakers

HID_UUIDS = ("00001124-", "00001812-")       # Human Interface Device: classic, and over Bluetooth LE (HOGP)


def bt_parse_info(text):
    """`bluetoothctl info` as a dict (UUIDs as a list)."""
    out = {"UUIDs": []}
    for line in text.splitlines():
        k, sep, v = line.strip().partition(": ")
        if not sep:
            continue
        if k == "UUID":
            out["UUIDs"].append(v)
        else:
            out[k] = v
    return out


def bt_kind(info):
    """remote, controller, keyboard, mouse, audio, or other: what a device is, from its name, icon and services."""
    name, icon = info.get("Name") or info.get("Alias") or "", info.get("Icon", "")
    hid = any(u in x for x in info.get("UUIDs", []) for u in HID_UUIDS)
    if re.search(r"fire ?tv|amazon|remote|\bAR\d|AFTR|tv remote", name, re.I):
        return "remote"
    if icon == "input-gaming" or re.search(r"controller|gamepad|xbox|dualsense|dualshock|8bitdo|joy-?con", name, re.I):
        return "controller"
    if icon == "input-keyboard" or re.search(r"keyboard", name, re.I):
        return "keyboard"
    if icon in ("input-mouse", "input-tablet") or re.search(r"\bmouse\b|trackpad", name, re.I):
        return "mouse"
    if icon.startswith("audio") or re.search(r"headphone|headset|speaker|buds|airpods|soundbar|\bjbl\b|bose|beats", name, re.I):
        return "audio"
    try:                                                    # what a Bluetooth LE device says it is (its "appearance")
        look = int(str(info.get("Appearance")).split()[0], 0) if info.get("Appearance") not in (None, "") else None
    except ValueError:
        look = None
    if look is not None:
        if 0x0180 <= look <= 0x01BF:
            return "remote"
        if look in (0x03C3, 0x03C4):
            return "controller"
        if look == 0x03C1:
            return "keyboard"
        if look in (0x03C2, 0x03C5):
            return "mouse"
    if hid or icon.startswith("input"):
        return "remote"
    return "other"


def bt_objects(text):
    """bluetoothd's devices from one `busctl --json=short` call (GetManagedObjects), as `bluetoothctl info` would show
    each: Name, Icon, Appearance, UUIDs, Paired, Connected, RSSI. None if that isn't what came back."""
    try:
        objects = json.loads(text)["data"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    devs = []
    for path, ifaces in objects.items() if isinstance(objects, dict) else []:
        d = (ifaces or {}).get("org.bluez.Device1")
        if not isinstance(d, dict):
            continue
        v = {k: x.get("data") for k, x in d.items() if isinstance(x, dict)}
        if v.get("Address"):
            devs.append(v)
    return devs


def bt_devices():
    """Every Bluetooth device the box knows or sees, with what it is and whether it's paired and connected: in one
    call to bluetoothd (busctl, part of systemd), not a `bluetoothctl info` for each of the dozens a room can have
    around it (on a Pi 3 those took seconds, every two seconds, all through the setup)."""
    code, out = run(["busctl", "--system", "--json=short", "call", "org.bluez", "/", "org.freedesktop.DBus.ObjectManager",
                     "GetManagedObjects"], 8)
    objects = bt_objects(out) if code == 0 else None
    if objects is not None:
        found = []
        for v in objects:
            name = v.get("Name") or ""
            if not name:
                continue                                        # nameless (a beacon, a phone's privacy address)
            info = {"Name": name, "Icon": v.get("Icon") or "", "Appearance": v.get("Appearance"), "UUIDs": v.get("UUIDs") or []}
            found.append({"mac": v["Address"], "name": name, "kind": bt_kind(info), "paired": bool(v.get("Paired")),
                          "connected": bool(v.get("Connected")), "rssi": int(v.get("RSSI") or 0)})
        return found
    code, out = run(["bluetoothctl", "devices"], 8)                # (no busctl: one by one)
    if code != 0:
        return []
    found = []
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 3 or parts[0] != "Device":
            continue
        mac, name = parts[1], parts[2]
        _, text = run(["bluetoothctl", "info", mac], 8)
        info = bt_parse_info(text)
        info.setdefault("Name", name)
        if re.match(r"^([0-9A-F]{2}-){5}[0-9A-F]{2}$", info["Name"], re.I):
            continue                                            # nameless (a beacon, a phone's privacy address)
        found.append({"mac": mac, "name": info["Name"], "kind": bt_kind(info), "paired": info.get("Paired") == "yes",
                      "connected": info.get("Connected") == "yes", "rssi": int((re.search(r"-?\d+", info.get("RSSI", "")) or [0])[0] or 0)})
    return found


def bt_pair(mac):
    """Pair, trust and connect (no PIN: remotes, controllers and speakers pair with "just works")."""
    if not re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", mac or "", re.I):
        raise ValueError("Which device?")
    # (the agent's pairing helper, bluetoothctl kept open as the default agent, says yes to what BlueZ asks; a
    # bluetoothctl that brings its own agent here couldn't answer, so an Xbox controller never paired)
    code, out = run(["bluetoothctl", "pair", mac], 40)
    ok = code == 0 or "Pairing successful" in out or "AlreadyExists" in out
    if ok:
        run(["bluetoothctl", "trust", mac], 10)
        run(["bluetoothctl", "connect", mac], 20)
    return ok, out[-200:]


def bt_forget(mac):
    if not re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", mac or "", re.I):
        raise ValueError("Which device?")
    run(["bluetoothctl", "remove", mac], 10)


# ---------------------------------------------------------------- Sofa Shield (ad blocking for the whole box)

SHIELD_LISTS = ["https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts"]


def shield_status():
    """On or off, and how many sites it keeps out (from the box's hosts file)."""
    try:
        with open("/etc/hosts", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        text = ""
    block = re.search(r"# >>> Sofa Shield(.*?)# <<< Sofa Shield", text, re.S)
    count = len(re.findall(r"^0\.0\.0\.0\s", block.group(1), re.M)) if block else 0
    return {"on": bool(block), "sites": count}


# ---------------------------------------------------------------- the browser: a WebSocket and the DevTools protocol

class WebSocket:
    """Just enough of a WebSocket client (RFC 6455) for Chromium's DevTools port."""

    def __init__(self, url, timeout=10):
        u = urllib.parse.urlsplit(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (u.path or "/", u.netloc, key)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            part = self.sock.recv(4096)
            if not part:
                raise OSError("the browser closed the connection")
            head += part
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise OSError("the browser refused: " + head.split(b"\r\n", 1)[0].decode("latin-1"))
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.sock.settimeout(None)
        self.send_lock = threading.Lock()

    def send(self, text):
        data = text.encode("utf-8")
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                                bytes([0x80 | 127]) + struct.pack(">Q", n))
        mask = os.urandom(4)
        masked = (int.from_bytes(data, "big") ^ int.from_bytes((mask * (n // 4 + 1))[:n], "big")).to_bytes(n, "big") if n else b""
        with self.send_lock:
            self.sock.sendall(head + mask + masked)

    def _read(self, n):
        while len(self.buf) < n:
            part = self.sock.recv(65536)
            if not part:
                raise OSError("the browser went away")
            self.buf += part
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        message = b""
        while True:
            b0, b1 = self._read(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if op == 8:
                raise OSError("the browser closed the connection")
            if op == 9:                                            # ping: pong
                with self.send_lock:
                    self.sock.sendall(bytes([0x8A, 0x80 | len(data)]) + b"\0\0\0\0" + data)
                continue
            if op in (0, 1, 2):
                message += data
                if b0 & 0x80:
                    return message.decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


INJECT = open(os.path.join(HERE, "home", "inject.js"), encoding="utf-8").read() if os.path.exists(os.path.join(HERE, "home", "inject.js")) else ""


class Browser:
    """The box's Chromium, over its DevTools port: tabs are apps."""

    def __init__(self, port=DEVTOOLS_PORT, on_message=None, scale=None):
        self.port, self.on_message, self.scale = port, on_message, scale or (lambda: 1.0)
        self.page_script = ""        # run in every app's own pages before theirs (the agent's H264_ONLY on a Pi 3)
        self.ws, self.next_id, self.waiting = None, 0, {}
        self.tabs = {}               # target id -> {"app", "title", "url", "session", "used", "audible"}
        self.notes = collections.deque(maxlen=150)   # the pages' errors and their video players' messages, for a report
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self._closed = threading.Event()
        threading.Thread(target=self._keep_connected, daemon=True, name="devtools").start()

    # -- the connection
    def _keep_connected(self):
        while True:
            try:
                with _opener.open("http://127.0.0.1:%d/json/version" % self.port, timeout=3) as r:
                    url = json.loads(r.read().decode())["webSocketDebuggerUrl"]
                self.ws = WebSocket(url)
                self._closed.clear()
                threading.Thread(target=self._reader, daemon=True, name="devtools-read").start()
                self.call("Target.setDiscoverTargets", {"discover": True})
                self.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True})
                for t in self.call("Target.getTargets").get("targetInfos", []):
                    if t["type"] == "page":
                        self._track(t)
                        if not t.get("attached"):
                            try:
                                self.call("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})
                            except OSError:
                                pass
                self.ready.set()
                self._closed.wait()
            except (OSError, ValueError, KeyError):
                pass
            self.ready.clear()
            time.sleep(2)

    def connected(self):
        return self.ready.is_set()

    def _reader(self):
        try:
            while True:
                msg = json.loads(self.ws.recv())
                if "id" in msg:
                    box = self.waiting.pop(msg["id"], None)
                    if box:
                        box["reply"] = msg
                        box["done"].set()
                else:
                    try:
                        self._event(msg)
                    except Exception:
                        pass
        except (OSError, ValueError):
            pass
        for box in list(self.waiting.values()):
            box["reply"] = {"error": {"message": "the browser went away"}}
            box["done"].set()
        self.waiting.clear()
        self._closed.set()

    def call(self, method, params=None, session=None, timeout=10):
        if not self.ws:
            raise OSError("no browser")
        with self.lock:
            self.next_id += 1
            mid = self.next_id
        box = {"done": threading.Event(), "reply": None}
        self.waiting[mid] = box
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.ws.send(json.dumps(msg))
        if not box["done"].wait(timeout):
            self.waiting.pop(mid, None)
            raise OSError("the browser didn't answer %s" % method)
        if box["reply"].get("error"):
            raise OSError(box["reply"]["error"].get("message", "error"))
        return box["reply"].get("result", {})

    # -- what the browser tells us
    def _track(self, info):
        tab = self.tabs.setdefault(info["targetId"], {"app": None, "used": time.time(), "session": None, "audible": False})
        tab.update(title=info.get("title", ""), url=info.get("url", ""))
        if tab["app"] is None:
            opener = self.tabs.get(info.get("openerId") or "")
            tab["app"] = opener["app"] if opener else ("home" if "/box/home" in info.get("url", "") else "browser")
        return tab

    def _event(self, msg):
        m, p = msg.get("method"), msg.get("params", {})
        if m in ("Target.targetCreated", "Target.targetInfoChanged") and p["targetInfo"]["type"] == "page":
            self._track(p["targetInfo"])
        elif m == "Target.targetDestroyed":
            self.tabs.pop(p.get("targetId"), None)
        elif m in NOTED:
            self._note(m, p, msg.get("sessionId"))
        elif m.startswith("Runtime.") and m != "Runtime.bindingCalled":
            return                                                   # console messages and the like: not ours
        elif m == "Target.attachedToTarget" and p["targetInfo"]["type"] == "page":
            tab = self._track(p["targetInfo"])
            tab["session"] = p["sessionId"]
            threading.Thread(target=self._prepare, args=(p["targetInfo"]["targetId"], p["sessionId"]), daemon=True).start()
        elif m == "Runtime.bindingCalled" and p.get("name") == "__sofaBox":
            target = next((t for t, tab in self.tabs.items() if tab.get("session") == msg.get("sessionId")), None)
            if self.on_message:                 # on a thread of its own: it talks to the browser, whose answers this thread reads
                try:
                    payload = json.loads(p.get("payload") or "{}")
                except ValueError:
                    return
                threading.Thread(target=self.on_message, args=(payload, target, dict(self.tabs.get(target) or {})), daemon=True).start()

    def _note(self, m, p, session):
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails") or {}
            text = (d.get("exception") or {}).get("description") or d.get("text", "")
        elif m == "Runtime.consoleAPICalled":
            if p.get("type") not in ("error", "assert"):
                return
            text = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
        elif m == "Log.entryAdded":
            e = p.get("entry") or {}
            text = "%s: %s" % (e.get("source", ""), e.get("text", "")) if e.get("level") == "error" else ""
        elif m == "Media.playerErrorsRaised":
            text = "; ".join("%s %s" % (e.get("errorType", ""), e.get("code", "")) for e in p.get("errors", []))
        elif m == "Media.playerMessagesLogged":
            text = "; ".join(x.get("message", "") for x in p.get("messages", []) if x.get("level") in ("error", "warning"))
        elif m == "Media.playerPropertiesChanged":
            text = ", ".join("%s=%s" % (x["name"][1:], x.get("value")) for x in p.get("properties", []) if x.get("name") in MEDIA_PROPS)
        else:                                   # (a looping clip's ending, seeking and buffering: routine, left out)
            events = [e for e in p.get("events", []) if not ROUTINE.search(str(e.get("value", "")))]
            text = ", ".join(str(e.get("value", "")) for e in events)
        if text:
            app = next((tab.get("app") for tab in self.tabs.values() if tab.get("session") == session), None) or "?"
            line = "%s %s: %s" % (app, m.split(".", 1)[1], " ".join(text.split())[:300])
            if self.notes and self.notes[-1].split(" ", 1)[1].split(" (×")[0] == line:     # the same again: counted
                n = self.notes[-1].rsplit(" (×", 1)
                self.notes[-1] = n[0] + " (×%d)" % ((int(n[1].rstrip(")")) if len(n) > 1 else 1) + 1)
            else:
                self.notes.append("%s %s" % (time.strftime("%H:%M:%S"), line))

    def _prepare(self, target, session):
        """Every page: the Sofa bar, the Home key and pointer hiding (in a script world of their own), and
        the way back to the agent."""
        tab = self.tabs.get(target) or {}
        try:
            self.call("Runtime.enable", {}, session)              # the page's messages come through only with it on
            try:                                                  # (how quickly it answers: every page, Home too)
                self.call("Page.addScriptToEvaluateOnNewDocument", {"source": SMOOTH_PROBE}, session, timeout=3)
                self.call("Runtime.evaluate", {"expression": SMOOTH_PROBE}, session, timeout=3)
            except OSError:
                pass
            self.call("Runtime.addBinding", {"name": "__sofaBox", "executionContextName": "sofabox"}, session)
            for domain in ("Log", "Media"):                           # for the notes (Media: newer Chromiums only)
                try:
                    self.call(domain + ".enable", {}, session, timeout=3)
                except OSError:
                    pass
            if tab.get("ua"):
                self.call("Network.setUserAgentOverride", {"userAgent": tab["ua"]}, session)
            self.size_page(target, session, tab)
            if self.page_script and tab.get("app") != "home":  # in the page's own world, before its scripts run
                self.call("Page.addScriptToEvaluateOnNewDocument", {"source": self.page_script}, session)
            if INJECT and tab.get("app") != "home":
                self.call("Page.addScriptToEvaluateOnNewDocument", {"source": INJECT, "worldName": "sofabox"}, session)
                self.call("Page.enable", {}, session)
                ctx = self.call("Page.createIsolatedWorld", {"frameId": target, "worldName": "sofabox"}, session)
                self.call("Runtime.evaluate", {"expression": INJECT, "contextId": ctx["executionContextId"]}, session)
            self.call("Runtime.runIfWaitingForDebugger", {}, session)
        except OSError:
            pass
        tab["prepared"] = True

    def size_page(self, target, session, tab):
        """Pages drawn for the sofa (twice as big on a 1080p TV) while the window keeps the whole screen: what
        Chromium's own --force-device-scale-factor does, without its Wayland trouble. The home screen sizes
        itself to the screen (it's measured in screen widths), so it's left as it is.
        Off unless SOFA_BOX_PAGE_SCALE=1: on a real Pi (cage, Wayland) the page took the smaller size but not the
        doubled pixels, so apps such as YouTube filled only the top-left quarter of the TV. Without it, every
        page has the whole TV at its own resolution."""
        if os.environ.get("SOFA_BOX_PAGE_SCALE") != "1":
            return
        scale = float(self.scale() or 1)
        if scale <= 1.01 or tab.get("app") == "home":
            return
        try:
            bounds = self.call("Browser.getWindowForTarget", {"targetId": target}).get("bounds") or {}
        except OSError:
            return
        w, h = bounds.get("width") or 0, bounds.get("height") or 0
        if w < 640 or h < 360:
            return
        cw, ch = int(round(w / scale)), int(round(h / scale))
        self.call("Emulation.setDeviceMetricsOverride", {"width": cw, "height": ch, "deviceScaleFactor": scale, "mobile": False,
                                                         "screenWidth": cw, "screenHeight": ch}, session)

    # -- what the agent asks
    def tab_of(self, app_id):
        found = [(t, tab) for t, tab in self.tabs.items() if tab.get("app") == app_id]
        return max(found, key=lambda x: x[1]["used"])[0] if found else None

    def activate(self, target):
        tab = self.tabs.get(target) or {}
        if tab.get("frozen") and tab.get("session"):     # back in front: running again before it shows
            try:
                self.call("Page.setWebLifecycleState", {"state": "active"}, tab["session"])
            except OSError:
                pass
            tab["frozen"] = False
        self.call("Target.activateTarget", {"targetId": target})
        self.front = target
        if target in self.tabs:
            self.tabs[target]["used"] = time.time()
        threading.Thread(target=self.settle, args=(target,), daemon=True).start()

    def settle(self, front):
        """The app in front gets the box: the others are frozen (no scripts, timers or drawing) unless they're
        playing something you can hear, so music carries on. Home and the others wake up when they're opened."""
        time.sleep(1.5)                                  # let the one in front start first
        for t, tab in list(self.tabs.items()):
            if t == front or tab.get("frozen") or not tab.get("session") or tab.get("app") in KEEP_AWAKE:
                continue
            try:
                playing = (self.call("Runtime.evaluate", {"expression": PLAYING_JS, "returnByValue": True}, tab["session"], timeout=3)
                           .get("result", {}).get("value"))
                if not playing and getattr(self, "front", None) != t:
                    self.call("Page.setWebLifecycleState", {"state": "frozen"}, tab["session"], timeout=3)
                    tab["frozen"] = True
            except OSError:
                pass

    def rest(self, close_apps=False):
        """A game takes the box: every page stops (frozen, Home too), the apps that aren't Sofa close on a small box,
        and the browser lets go of the memory it can. Home wakes when it's brought back (activate)."""
        for t, tab in list(self.tabs.items()):
            if not tab.get("session"):
                continue
            if close_apps and tab.get("app") not in ("home", None) + KEEP_AWAKE:
                try:
                    self.close(t)
                except OSError:
                    pass
                continue
            if not tab.get("frozen"):
                try:
                    self.call("Page.setWebLifecycleState", {"state": "frozen"}, tab["session"], timeout=3)
                    tab["frozen"] = True
                except OSError:
                    pass
        home = self.tab_of("home")
        if home and self.tabs[home].get("session"):
            try:
                self.call("Memory.simulatePressureNotification", {"level": "critical"}, self.tabs[home]["session"], timeout=3)
            except OSError:
                pass

    def front_app(self):
        """The app whose tab was last brought forward."""
        return (self.tabs.get(getattr(self, "front", None)) or {}).get("app")

    def open(self, app_id, url, ua=""):
        """The app's tab brought forward, or a new one."""
        target = self.tab_of(app_id)
        if target and app_id != "browser":
            self.activate(target)
            return target
        self._make_room()
        target = self.call("Target.createTarget", {"url": "about:blank", "background": True})["targetId"]   # Home stays in front
        tab = self.tabs.setdefault(target, {"used": time.time(), "session": None, "audible": False, "title": "", "url": url})
        tab.update(app=app_id, ua=ua if ua else None)
        for _ in range(60):                                   # attached (auto-attach) and prepared: the page's
            if tab.get("session") and tab.get("prepared"):    # scripts are in before its first page loads
                break
            time.sleep(0.05)
        if tab.get("session") and ua:
            try:
                self.call("Network.setUserAgentOverride", {"userAgent": ua}, tab["session"])
            except OSError:
                pass
        if tab.get("session"):
            self.call("Page.navigate", {"url": url}, tab["session"])
            self.drawn(tab["session"])
        else:
            self.call("Target.closeTarget", {"targetId": target})
            target = self.call("Target.createTarget", {"url": url})["targetId"]
            self.tabs.setdefault(target, {"used": time.time(), "session": None, "audible": False}).update(app=app_id)
        self.activate(target)
        return target

    def drawn(self, session, limit=8.0):
        """Wait (behind Home, which says it's opening) until the new page has something to show, so the TV goes from
        Home to the app, not to a blank page while it loads; at most `limit` seconds."""
        until = time.time() + limit
        while time.time() < until:
            try:
                if self.call("Runtime.evaluate", {"expression": DRAWN_JS, "returnByValue": True}, session, timeout=2) \
                        .get("result", {}).get("value"):
                    time.sleep(0.25)                          # its first styles and pictures
                    return True
            except OSError:
                pass
            time.sleep(0.15)
        return False

    def cookies(self, host):
        """The browser's cookies for a host, as a Cookie header (Sofa's sign-in at its address on the box)."""
        try:
            got = self.call("Storage.getCookies", {}).get("cookies") or []
        except OSError:
            return ""
        return "; ".join("%s=%s" % (c["name"], c["value"]) for c in got if c.get("domain", "").lstrip(".") == host)

    def _front_session(self):
        t = getattr(self, "front", None) if getattr(self, "front", None) in self.tabs else self.tab_of("home")
        return (self.tabs.get(t) or {}).get("session")

    def press(self, key, keycode):
        """A key press in the tab in front (the phone remote). Enter carries its character too, as a real keyboard's
        does: some pages only press a button on that."""
        session = self._front_session()
        if session:
            text = {"Enter": "\r"}.get(key)
            down = {"type": "keyDown", "text": text, "unmodifiedText": text} if text else {"type": "rawKeyDown"}
            for event in (down, {"type": "keyUp"}):
                self.call("Input.dispatchKeyEvent", dict(event, key=key, code=key, windowsVirtualKeyCode=keycode,
                                                         nativeVirtualKeyCode=keycode), session)

    def insert_text(self, text):
        """Text typed on the phone, into whatever is focused in the tab in front."""
        session = self._front_session()
        if session and text:
            self.call("Input.insertText", {"text": text}, session)

    def set_cookie(self, host, name, value, days=60):
        try:
            self.call("Storage.setCookies", {"cookies": [{"name": name, "value": value, "domain": host, "path": "/", "httpOnly": True,
                                                          "sameSite": "Lax", "expires": time.time() + days * 86400}]})
        except OSError:
            pass

    def navigate(self, target, url):
        tab = self.tabs.get(target) or {}
        if tab.get("session"):
            self.call("Page.navigate", {"url": url}, tab["session"])

    def home(self):
        target = self.tab_of("home")
        if target:
            self.activate(target)
            return True
        return False

    def close(self, target):
        self.call("Target.closeTarget", {"targetId": target})
        self.tabs.pop(target, None)

    def running(self):
        return [{"target": t, "app": tab.get("app"), "title": tab.get("title", ""), "url": tab.get("url", ""),
                 "used": tab.get("used"), "frozen": bool(tab.get("frozen"))} for t, tab in self.tabs.items() if tab.get("app") not in ("home", None)]

    def _make_room(self):
        apps = sorted((tab["used"], t) for t, tab in self.tabs.items() if tab.get("app") not in ("home", None))
        while len(apps) >= MAX_APP_TABS:
            _, t = apps.pop(0)
            try:
                self.close(t)
            except OSError:
                pass

    def smoothness(self):
        """How quickly each open page answers the remote: {app: {presses, slow, worst, long, long_ms}} (pages asleep
        aren't asked)."""
        out = {}
        for t, tab in list(self.tabs.items()):
            if not tab.get("session") or tab.get("frozen"):
                continue
            try:
                r = self.call("Runtime.evaluate", {"expression": "window.__sofaSmooth ? __sofaSmooth() : ''",
                                                   "returnByValue": True}, tab["session"], timeout=3)
                v = json.loads((r.get("result") or {}).get("value") or "null")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(v, dict):
                name = tab.get("app") or "page"
                if name in out:                                  # (two of one app: added up)
                    v = {k: (max if k == "worst" else sum)((out[name].get(k, 0), v.get(k, 0))) for k in v}
                out[name] = v
        return out

    def hud(self, text, level=None):
        """A short message over whatever is in front (Home, Sofa, an app), like a TV's own: the volume. Drawn in the page
        by the box (no page's code needed), gone after a moment."""
        session = self._front_session()
        if session:
            self.call("Runtime.evaluate", {"expression": HUD_JS % (json.dumps(text), json.dumps(level))}, session, timeout=3)

    def evaluate(self, target, expression):
        tab = self.tabs.get(target) or {}
        if tab.get("session"):
            return self.call("Runtime.evaluate", {"expression": expression}, tab["session"])
        return None


# In every page the box opens, Home too: how quickly it answers the remote, measured by the browser itself (a key
# press until the TV shows the answer; 0.1 s or more feels slow), and the tasks that held it up (50 ms or more). Read
# by Browser.smoothness() (reports; the box choosing its light look by itself on a board too slow for the full one).
SMOOTH_PROBE = r"""(function () {
  if (window.__sofaSmooth) return;
  var s = { presses: 0, slow: 0, worst: 0, long: 0, long_ms: 0 };
  addEventListener("keydown", function () { s.presses++; }, true);
  try {
    new PerformanceObserver(function (list) {
      list.getEntries().forEach(function (e) {
        if (e.name !== "keydown") return;
        if (e.duration > s.worst) s.worst = Math.round(e.duration);
        if (e.duration >= 100) s.slow++;
      });
    }).observe({ type: "event", durationThreshold: 48 });          // (only presses it counted itself)
  } catch (e) {}
  try {
    new PerformanceObserver(function (list) {
      list.getEntries().forEach(function (e) { s.long++; s.long_ms += Math.round(e.duration); });
    }).observe({ type: "longtask", buffered: true });
  } catch (e) {}
  window.__sofaSmooth = function () { return JSON.stringify(s); };
})();"""

HUD_JS = r"""(function (text, level) {
  var d = document.getElementById("__sofa_hud");
  if (!d) {
    d = document.createElement("div"); d.id = "__sofa_hud";
    d.style.cssText = "position:fixed;z-index:2147483647;right:48px;top:40px;min-width:260px;padding:16px 22px;border-radius:16px;" +
      "background:rgba(12,12,16,.9);color:#fff;font:600 22px/1.2 system-ui,sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.5);" +
      "pointer-events:none;transition:opacity .25s";
    d.innerHTML = '<div></div><div style="margin-top:10px;height:6px;border-radius:6px;background:rgba(255,255,255,.18)">' +
      '<div style="height:100%%;border-radius:6px;background:#FF2E88;width:0"></div></div>';
    (document.body || document.documentElement).appendChild(d);
  }
  d.firstChild.textContent = text;
  d.lastChild.style.display = level === null ? "none" : "";
  if (level !== null) d.lastChild.firstChild.style.width = Math.max(0, Math.min(100, level)) + "%%";
  d.style.opacity = "1";
  clearTimeout(d._t); d._t = setTimeout(function () { d.style.opacity = "0"; }, 1600);
})(%s, %s)"""


def tv_user_agent():
    return TV_UA


def chromium():
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None


def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
