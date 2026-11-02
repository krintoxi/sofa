"""The servers the box plays from: Sofa at home, Sofa on the internet (a share link), Sofa on the box
itself ("This box"), and other kinds of media server (Jellyfin, Emby, Plex).

Each Sofa gets an address of its own on the box, http://<id>.localhost:8091 (Chromium sends every
*.localhost name to the box itself), and the agent passes that address's pages through to its server.
So each server keeps its own sign-in, settings and history, and switching never signs anyone out.
Jellyfin, Emby and Plex open as they are, as web apps with the Sofa bar.

~/.config/sofa-box/servers.json: {"servers": [...], "default": id or null, "ask": bool}. Standard
library only (Python 3.7+). Used by sofa-box-agent.py.
"""
import hashlib
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = {"sofa": "Sofa", "jellyfin": "Jellyfin", "emby": "Emby", "plex": "Plex"}
WEB_PATH = {"jellyfin": "/web/index.html", "emby": "/web/index.html", "plex": "/web/index.html"}
PORTS = {"sofa": 8090, "jellyfin": 8096, "emby": 8096, "plex": 32400}
FEATURED_URL = "https://raw.githubusercontent.com/krintoxi/sofa/main/deploy/sofa-box/servers.json"
LOCAL = {"id": "box", "kind": "sofa", "name": "This box", "url": "http://127.0.0.1:8095", "where": "box",
         "about": "Live TV and videos on this box and its USB drives. No other computer needed."}
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_web = urllib.request.build_opener()
AGENT = {"User-Agent": "SofaBox/2", "Accept": "application/json"}


def _get(url, timeout=4, limit=200000):
    """(final address, body as text) of a GET; private addresses skip any proxy."""
    host = urllib.parse.urlsplit(url).hostname or ""
    opener = _direct if _private(host) else _web
    with opener.open(urllib.request.Request(url, headers=AGENT), timeout=timeout) as r:
        return r.geturl(), r.read(limit).decode("utf-8", "replace")


def _private(host):
    return host in ("localhost",) or host.endswith(".local") or bool(
        re.match(r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)", host))


def origin(url):
    p = urllib.parse.urlsplit(url)
    return "%s://%s" % (p.scheme, p.netloc)


def server_id(kind, url):
    return "%s-%s" % (kind[:5], hashlib.sha1(origin(url).lower().encode()).hexdigest()[:6])


def identify(text, timeout=4):
    """What answers at a typed or pasted address: a Sofa (also a share link), Jellyfin, Emby or Plex.
    Returns a server entry, or raises ValueError saying what went wrong."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Type or paste an address.")
    if not re.match(r"^https?://", text, re.I):
        text = ("http://" if _private(text.split("/")[0].split(":")[0]) or re.match(r"^\d", text) else "https://") + text
    parts = urllib.parse.urlsplit(text)
    if not parts.hostname:
        raise ValueError("That doesn't look like an address.")
    share = re.match(r"^/s/([\w-]{6,64})/?$", parts.path or "")
    bases = [origin(text)]
    if not parts.port:                                   # no port: the usual ones too
        bases += ["%s://%s:%d" % (parts.scheme if parts.scheme == "http" or _private(parts.hostname) else "http", parts.hostname, p)
                  for p in (8090, 8096, 32400)]
    last = None
    for base in bases:
        try:
            final, body = _get(base + "/api/info", timeout)
            info = json.loads(body)
            if info.get("sofa"):
                base = origin(final)
                return {"id": server_id("sofa", base), "kind": "sofa", "name": (info.get("share") or {}).get("title") or info.get("name") or "Sofa",
                        "url": base, "start": "/s/" + share.group(1) if share else "",
                        "where": "home" if _private(urllib.parse.urlsplit(base).hostname) else "internet",
                        "public": bool((info.get("share") or {}).get("on")), "sofa_id": info.get("id")}
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last = exc
        try:
            final, body = _get(base + "/System/Info/Public", timeout)
            info = json.loads(body)
            if info.get("Id") and (info.get("ServerName") or info.get("ProductName")):
                kind = "jellyfin" if "jellyfin" in (info.get("ProductName") or "").lower() else "emby"
                base = origin(final)
                return {"id": server_id(kind, base), "kind": kind, "name": info.get("ServerName") or KINDS[kind], "url": base,
                        "start": WEB_PATH[kind], "where": "home" if _private(urllib.parse.urlsplit(base).hostname) else "internet"}
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last = exc
        try:
            final, body = _get(base + "/identity", timeout)
            if "machineIdentifier" in body:
                base = origin(final)
                return {"id": server_id("plex", base), "kind": "plex", "name": "Plex", "url": base, "start": WEB_PATH["plex"],
                        "where": "home" if _private(urllib.parse.urlsplit(base).hostname) else "internet"}
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last = exc
    if isinstance(last, urllib.error.HTTPError) and last.code == 403:
        raise ValueError("That server answered, but it's private. Ask its owner for a share link.")
    raise ValueError("Nothing that the box knows answered there (Sofa, Jellyfin, Emby or Plex). Check the address.")


# ---------------------------------------------------------------- finding servers on the home network

def find_others(wait=2.5):
    """Jellyfin and Emby (they answer a broadcast on UDP 7359) and Plex (GDM, UDP 32414) at home."""
    found = []
    lock = threading.Lock()

    def listen(sock, parse):
        end = time.time() + wait
        while time.time() < end:
            try:
                data, addr = sock.recvfrom(4096)
            except OSError:
                continue
            entry = parse(data.decode("utf-8", "replace"), addr[0])
            if entry:
                with lock:
                    if not any(e["id"] == entry["id"] for e in found):
                        found.append(entry)
        sock.close()

    def jelly(text, ip):
        try:
            j = json.loads(text)
        except ValueError:
            return None
        addr = j.get("Address") or "http://%s:8096" % ip
        kind = "emby" if "emby" in text.lower() and "jellyfin" not in text.lower() else "jellyfin"
        return {"id": server_id(kind, addr), "kind": kind, "name": j.get("Name") or KINDS[kind], "url": origin(addr),
                "start": WEB_PATH[kind], "where": "home"}

    def plex(text, ip):
        if "Resource-Identifier" not in text and "Plex" not in text:
            return None
        port = (re.search(r"(?im)^Port:\s*(\d+)", text) or [None, "32400"])[1]
        name = (re.search(r"(?im)^Name:\s*(.+)$", text) or [None, "Plex"])[1].strip()
        url = "http://%s:%s" % (ip, port)
        return {"id": server_id("plex", url), "kind": "plex", "name": name, "url": url, "start": WEB_PATH["plex"], "where": "home"}

    threads = []
    for msg, port, parse in ((b"Who is JellyfinServer?", 7359, jelly), (b"who is EmbyServer?", 7359, jelly),
                             (b"M-SEARCH * HTTP/1.1\r\n\r\n", 32414, plex)):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(0.5)
            s.sendto(msg, ("255.255.255.255", port))
        except OSError:
            continue
        t = threading.Thread(target=listen, args=(s, parse), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(wait + 1)
    return found


# ---------------------------------------------------------------- the free servers listed for everyone

_featured = {"at": 0, "list": None}


def featured(conf_dir):
    """Public Sofas anyone can watch (deploy/sofa-box/servers.json): the copy on GitHub, checked once a
    day so new ones show up without a new card, else the one that came with the box."""
    cache = os.path.join(conf_dir, "featured.json")
    if time.time() - _featured["at"] > 86400:
        _featured["at"] = time.time()

        def refresh():
            try:
                _, body = _get(FEATURED_URL, timeout=8)
                data = json.loads(body)
                if isinstance(data.get("servers"), list):
                    os.makedirs(conf_dir, exist_ok=True)
                    with open(cache, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                    _featured["list"] = data["servers"]
            except (OSError, ValueError, AttributeError):
                pass
        threading.Thread(target=refresh, daemon=True).start()
    if _featured["list"] is None:
        for path in (cache, os.path.join(HERE, "servers.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    _featured["list"] = json.load(f).get("servers") or []
                break
            except (OSError, ValueError, AttributeError):
                continue
    return [dict(s, id=server_id("sofa", s["url"]), kind="sofa", where="internet", featured=True)
            for s in (_featured["list"] or []) if isinstance(s, dict) and re.match(r"^https?://", s.get("url") or "")]


# ---------------------------------------------------------------- the box's list

class Servers:
    def __init__(self, conf_dir, local_available=None):
        self.dir = conf_dir
        self.path = os.path.join(conf_dir, "servers.json")
        self.lock = threading.Lock()
        self.local_available = local_available or (lambda: False)

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("servers"), list):
                return data
        except (OSError, ValueError):
            pass
        return {"servers": [], "default": None, "ask": True}

    def _save(self, data):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path + ".new"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    def state(self):
        with self.lock:
            data = self._load()
        servers = list(data["servers"])
        if self.local_available():
            servers.append(dict(LOCAL))
        default = data.get("default")
        if default and not any(s["id"] == default for s in servers):
            default = None
        return {"servers": servers, "default": default, "ask": bool(data.get("ask", True)) or not default}

    def get(self, sid):
        return next((s for s in self.state()["servers"] if s["id"] == sid), None)

    def add(self, entry):
        entry = {k: entry.get(k) for k in ("id", "kind", "name", "url", "start", "where", "public", "sofa_id", "featured") if entry.get(k) is not None}
        entry["added"] = int(time.time())
        with self.lock:
            data = self._load()
            same = next((s for s in data["servers"] if s["id"] == entry["id"] or
                         (entry.get("sofa_id") and s.get("sofa_id") == entry["sofa_id"] and s.get("where") == entry.get("where"))), None)
            if same:                                    # the same server again: newer details, same id
                entry["id"] = same["id"]
                if not entry.get("start"):
                    entry["start"] = same.get("start", "")
            data["servers"] = [s for s in data["servers"] if s["id"] != entry["id"]] + [entry]
            self._save(data)
        return entry

    def remove(self, sid):
        with self.lock:
            data = self._load()
            data["servers"] = [s for s in data["servers"] if s["id"] != sid]
            if data.get("default") == sid:
                data["default"], data["ask"] = None, True
            self._save(data)

    def choose(self, sid, remember):
        """The one Sofa opens with (`remember`), or ask every time."""
        with self.lock:
            data = self._load()
            data["default"] = sid if sid else data.get("default")
            data["ask"] = not remember
            self._save(data)

    def rename(self, sid, name):
        with self.lock:
            data = self._load()
            for s in data["servers"]:
                if s["id"] == sid:
                    s["name"] = str(name or "").strip()[:40] or s["name"]
            self._save(data)


def by_host(host, servers):
    """The server for a page's own address on the box: <id>.localhost[:port]."""
    m = re.match(r"^([a-z0-9-]{1,40})\.localhost(:\d+)?$", (host or "").lower())
    return servers.get(m.group(1)) if m else None
