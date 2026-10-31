"""Sofa Box OS: the home screen's apps, the store, icons, files and ad blocking, and the box's one
Chromium, steered over its DevTools port: every app is a tab the agent opens, brings forward and
closes. Used by sofa-box-agent.py. Standard library only (Python 3.7+).

The plan and the reasons are in docs/sofa-box-os.md.
"""
import base64
import html
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
MAX_APP_TABS = 4                       # a 1 GB Pi: older tabs that aren't playing close
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_web = urllib.request.build_opener()  # sites on the internet (the system's proxy settings apply)
UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 SofaBox/1"
TV_UA = ("Mozilla/5.0 (Linux; Tizen 6.5) AppleWebKit/537.36 (KHTML, like Gecko) Version/6.5 TV Safari/537.36 "
         "Cobalt/23.lts.4.308289-gold (unlike Gecko) v8/8.8.278.17-jit gles Starboard/15")


# ---------------------------------------------------------------- the apps on the home screen

BUILTIN = [   # always there; can be moved and hidden, not removed
    {"id": "sofa", "name": "Sofa", "kind": "builtin", "url": "/?tv=1", "color": "#F4B740", "icon": "sofa"},
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
        order = data.get("order") or []
        apps.sort(key=lambda a: (order.index(a["id"]) if a["id"] in order else len(order) + apps.index(a)))
        for a in apps:
            a["hidden"] = a["id"] in (data.get("hidden") or [])
            if a.get("icon_file"):
                a["icon_url"] = "/box/icons/" + a["icon_file"]
        return apps

    def get(self, app_id):
        return next((a for a in self.listing() if a["id"] == app_id), None)

    def install(self, entry):
        """Put an app on the home screen (from the store, or any site). Returns it; its icon comes after."""
        app = app_from_store(entry)
        with self.lock:
            data = self._load()
            data["apps"] = [a for a in data["apps"] if a["id"] != app["id"]] + [app]
            self._save(data)
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
            "icon_src": entry.get("icon") or "", "added": int(time.time())}


# ---------------------------------------------------------------- the store

def store():
    with open(os.path.join(HERE, "store.json"), encoding="utf-8") as f:
        return json.load(f)


def store_entry(sid):
    for section in store()["sections"]:
        for e in section["apps"]:
            if e["id"] == sid:
                return e
    return None


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


def fetch_icon(url, folder, app_id, timeout=10):
    """The site's best picture for a home screen tile: its manifest's biggest icon, its
    apple-touch-icon, or its favicon. Saved as <app id>.<ext>; returns the file name, or None."""
    def get(u, limit=2_000_000):
        req = urllib.request.Request(u, headers={"User-Agent": UA})
        with _web.open(req, timeout=timeout) as r:
            return r.read(limit), r.headers.get("Content-Type", ""), r.geturl()
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
            candidates.append((16, urllib.parse.urljoin(final, "/favicon.ico")))
        for _, src in sorted(candidates, reverse=True):
            try:
                data, ctype, _ = get(src)
            except OSError:
                continue
            ext = ("svg" if "svg" in ctype or src.lower().split("?")[0].endswith(".svg") else
                   "ico" if "icon" in ctype or src.lower().split("?")[0].endswith(".ico") else
                   "jpg" if "jpeg" in ctype else "webp" if "webp" in ctype else "png")
            if len(data) < 100 or b"<html" in data[:200].lower():
                continue
            os.makedirs(folder, exist_ok=True)
            name = "%s.%s" % (app_id, ext)
            with open(os.path.join(folder, name), "wb") as f:
                f.write(data)
            return name
    except (OSError, ValueError):
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
    for base in ("/media/" + os.path.basename(home), "/media", "/mnt"):
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

    def __init__(self, port=DEVTOOLS_PORT, on_message=None):
        self.port, self.on_message = port, on_message
        self.ws, self.next_id, self.waiting = None, 0, {}
        self.tabs = {}               # target id -> {"app", "title", "url", "session", "used", "audible"}
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
        elif m == "Target.attachedToTarget" and p["targetInfo"]["type"] == "page":
            tab = self._track(p["targetInfo"])
            tab["session"] = p["sessionId"]
            threading.Thread(target=self._prepare, args=(p["targetInfo"]["targetId"], p["sessionId"]), daemon=True).start()
        elif m == "Runtime.bindingCalled" and p.get("name") == "__sofaBox":
            target = next((t for t, tab in self.tabs.items() if tab.get("session") == msg.get("sessionId")), None)
            if self.on_message:
                try:
                    self.on_message(json.loads(p.get("payload") or "{}"), target, dict(self.tabs.get(target) or {}))
                except ValueError:
                    pass

    def _prepare(self, target, session):
        """Every page: the Sofa bar, the Home key and pointer hiding (in a script world of their own), and
        the way back to the agent."""
        tab = self.tabs.get(target) or {}
        try:
            self.call("Runtime.addBinding", {"name": "__sofaBox", "executionContextName": "sofabox"}, session)
            if tab.get("ua"):
                self.call("Network.setUserAgentOverride", {"userAgent": tab["ua"]}, session)
            if INJECT and tab.get("app") != "home":
                self.call("Page.addScriptToEvaluateOnNewDocument", {"source": INJECT, "worldName": "sofabox"}, session)
                self.call("Page.enable", {}, session)
                ctx = self.call("Page.createIsolatedWorld", {"frameId": target, "worldName": "sofabox"}, session)
                self.call("Runtime.evaluate", {"expression": INJECT, "contextId": ctx["executionContextId"]}, session)
            self.call("Runtime.runIfWaitingForDebugger", {}, session)
        except OSError:
            pass

    # -- what the agent asks
    def tab_of(self, app_id):
        found = [(t, tab) for t, tab in self.tabs.items() if tab.get("app") == app_id]
        return max(found, key=lambda x: x[1]["used"])[0] if found else None

    def activate(self, target):
        self.call("Target.activateTarget", {"targetId": target})
        if target in self.tabs:
            self.tabs[target]["used"] = time.time()

    def open(self, app_id, url, ua=""):
        """The app's tab brought forward, or a new one."""
        target = self.tab_of(app_id)
        if target and app_id != "browser":
            self.activate(target)
            return target
        self._make_room()
        target = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        tab = self.tabs.setdefault(target, {"used": time.time(), "session": None, "audible": False, "title": "", "url": url})
        tab.update(app=app_id, ua=ua if ua else None)
        for _ in range(30):                                   # attached (auto-attach) and prepared
            if tab.get("session"):
                break
            time.sleep(0.05)
        if tab.get("session") and ua:
            try:
                self.call("Network.setUserAgentOverride", {"userAgent": ua}, tab["session"])
            except OSError:
                pass
        if tab.get("session"):
            self.call("Page.navigate", {"url": url}, tab["session"])
        else:
            self.call("Target.closeTarget", {"targetId": target})
            target = self.call("Target.createTarget", {"url": url})["targetId"]
            self.tabs.setdefault(target, {"used": time.time(), "session": None, "audible": False}).update(app=app_id)
        self.activate(target)
        return target

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
                 "used": tab.get("used")} for t, tab in self.tabs.items() if tab.get("app") not in ("home", None)]

    def _make_room(self):
        apps = sorted((tab["used"], t) for t, tab in self.tabs.items() if tab.get("app") not in ("home", None))
        while len(apps) >= MAX_APP_TABS:
            _, t = apps.pop(0)
            try:
                self.close(t)
            except OSError:
                pass

    def evaluate(self, target, expression):
        tab = self.tabs.get(target) or {}
        if tab.get("session"):
            return self.call("Runtime.evaluate", {"expression": expression}, tab["session"])
        return None


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
