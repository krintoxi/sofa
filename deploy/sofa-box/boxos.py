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
import sys
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


def available_mb():
    """The memory that's there for something new, in MB (the kernel's own figure); None where it can't be read."""
    try:
        with open("/proc/meminfo") as f:
            return int(re.search(r"MemAvailable:\s+(\d+)", f.read()).group(1)) // 1024
    except (OSError, AttributeError):
        return None


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
# Is the page playing something you can hear? Its <video> and <audio>, and what SOUND_PROBE saw start: a player made
# in script and never put on the page (new Audio()), and sound made with Web Audio. And how its sound went, for a report.
PLAYING_JS = ("(window.__sofaSound ? window.__sofaSound.playing() : false) || "
              "Array.from(document.querySelectorAll('video,audio')).some(m => !m.paused && !m.ended && !m.muted && m.volume > 0)")
HEARD_JS = "JSON.stringify({playing: !!(%s), sound: window.__sofaSound ? window.__sofaSound.stats() : null})" % PLAYING_JS
NOW_JS = "JSON.stringify(window.__sofaSound && window.__sofaSound.now ? window.__sofaSound.now() : null)"
ACT_JS = "!!(window.__sofaSound && window.__sofaSound.act && window.__sofaSound.act(%s))"
MUSIC_ACTS = ("play", "pause", "nexttrack", "previoustrack")
# In every app's page, before its own scripts. A music app often plays through a player that is not on the page, or
# through Web Audio (counted only on a page that says what it plays, so a game still sleeps behind Home): the box
# asked the page for its <audio> elements, found none, and put the app to sleep a second
# and a half after Home was pressed, music and all. Here every player is noted as it starts, and every Web Audio
# source while it sounds. It also counts each time sound stopped to wait for more to arrive (the network, or a
# server that's slow to send): what a stutter is, nearly always. And for the box's mini player: what the page says it's
# playing (the browser's Media Session: title, artist, cover) and the buttons it gives the browser's own controls
# (play, pause, next, previous), which the box can then press for it. No page's own code is needed.
SOUND_PROBE = r"""(function () {
  if (window.__sofaSound) return;
  var players = new Set(), sources = new Set(), contexts = new Set(), waitFrom = new WeakMap(), handlers = {}, last = null;
  var heard = { waits: 0, longest: 0, stalls: 0, errors: 0, started: 0 };
  function watch(m) {
    last = m;
    if (players.has(m)) return;
    players.add(m);
    m.addEventListener("waiting", function () { if (!m.seeking && m.currentTime > 0.5) { heard.waits++; waitFrom.set(m, performance.now()); } });
    m.addEventListener("playing", function () {
      var t = waitFrom.get(m);
      if (t) { heard.longest = Math.max(heard.longest, Math.round(performance.now() - t)); waitFrom.delete(m); }
    });
    m.addEventListener("stalled", function () { heard.stalls++; });
    m.addEventListener("error", function () { heard.errors++; });
  }
  try {
    var play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () { try { watch(this); heard.started++; } catch (e) {} return play.apply(this, arguments); };
  } catch (e) {}
  try {
    var S = window.AudioScheduledSourceNode;
    if (S) {
      var start = S.prototype.start;
      S.prototype.start = function () {
        var n = this;
        try { sources.add(n); contexts.add(n.context); heard.started++; n.addEventListener("ended", function () { sources.delete(n); }); } catch (e) {}
        return start.apply(n, arguments);
      };
    }
  } catch (e) {}
  try {
    var MS = window.MediaSession;
    if (MS && MS.prototype.setActionHandler) {
      var set = MS.prototype.setActionHandler;
      MS.prototype.setActionHandler = function (name, fn) { try { handlers[name] = fn || null; } catch (e) {} return set.apply(this, arguments); };
    }
  } catch (e) {}
  var audible = function (m) { return !m.paused && !m.ended && !m.muted && m.volume > 0; };
  window.__sofaSound = {
    playing: function () {
      var on = false;
      players.forEach(function (m) { if (audible(m)) on = true; });
      // Web Audio counts as music only on a page that says what it plays: a game makes its sound with Web Audio too,
      // and a game left behind Home should sleep like any other page.
      if (!on && navigator.mediaSession && navigator.mediaSession.metadata)
        sources.forEach(function (n) { try { if (n.context && n.context.state === "running") on = true; } catch (e) {} });
      return on;
    },
    stats: function () { return { waits: heard.waits, longest: heard.longest, stalls: heard.stalls, errors: heard.errors, started: heard.started }; },
    now: function () {
      var ms = navigator.mediaSession, md = ms && ms.metadata, art = null;
      try { if (md && md.artwork && md.artwork.length) art = md.artwork[md.artwork.length - 1].src; } catch (e) {}
      var can = Object.keys(handlers).filter(function (k) { return handlers[k]; });
      return { started: heard.started, said: !!md, playing: this.playing(), title: (md && md.title) || "", artist: (md && md.artist) || "",
               album: (md && md.album) || "", art: art, can: can,
               t: last && isFinite(last.currentTime) ? Math.round(last.currentTime) : null,
               d: last && isFinite(last.duration) ? Math.round(last.duration) : null };
    },
    act: function (name) {
      var h = handlers[name];
      if (h) { try { h({ action: name }); return true; } catch (e) { return false; } }
      if (name === "pause") {                      // (a page with no buttons of its own: its players, as they are)
        var did = false;
        players.forEach(function (m) { if (audible(m)) { m.pause(); did = true; } });
        contexts.forEach(function (c) { try { if (c.state === "running") { c.suspend(); did = true; } } catch (e) {} });
        return did;
      }
      if (name === "play") {
        var any = false;
        contexts.forEach(function (c) { try { if (c.state === "suspended") { c.resume(); any = true; } } catch (e) {} });
        if (last && last.paused) { last.play(); any = true; }
        return any;
      }
      return false;
    }
  };
})();"""
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
# Addresses the store has changed since boxes installed them: an installed app keeps the address it was given, so
# a box that still has the old one gets the new one. (Edge Music shows its TV layout when it's opened with
# ?client=sofabox, and remembers it; 2026-11-08.)
MOVED_APPS = {
    "edge-music": ({"https://music.edgeventure.uk", "https://music.edgeventure.uk/"}, "https://music.edgeventure.uk/?client=sofabox"),
}


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
        if isinstance(data, dict) and moved_apps(data):         # an address the store has changed since
            try:
                self._save(data)
            except OSError:
                pass
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
            f.flush()
            os.fsync(f.fileno())                        # (on the card at once: a sudden restart mustn't lose it)
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


def moved_apps(data):
    """An installed app whose address the store has since changed gets the new one (MOVED_APPS). True if any did."""
    changed = False
    for a in data.get("apps") or []:
        old, new = MOVED_APPS.get(a.get("id") if isinstance(a, dict) else None, ((), None))
        if new and a.get("url") in old:
            a["url"] = new
            changed = True
    return changed


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


ICON_WIDTHS = (96, 192, 384)


def small_icon(folder, name, width):
    """An app's picture at about the size the TV draws it (Home asks ?w=192 on a 1080p TV). Sites' icons are kept as
    they come, often 512 or 1024 pixels: a Pi 3 decodes up to fifty times the pixels its 150-pixel tile shows, every
    time it draws them again. Made once with Pillow and kept beside it (.w<width>/); None (the picture as it is) when
    it's that small already, an SVG, or anything Pillow can't read."""
    if width not in ICON_WIDTHS:
        return None
    base = os.path.realpath(folder or "")
    full = os.path.realpath(os.path.join(base, name))
    if not full.startswith(base + os.sep) or not os.path.isfile(full) or full.lower().endswith(".svg"):
        return None
    small = os.path.join(base, ".w%d" % width, os.path.splitext(os.path.basename(full))[0] + ".png")
    try:
        if os.path.getmtime(small) >= os.path.getmtime(full):
            return small
    except OSError:
        pass
    try:
        from PIL import Image
        with Image.open(full) as im:
            if im.width <= width:
                return None
            im = im.convert("RGBA")
            im = im.resize((width, max(1, round(im.height * width / im.width))), getattr(Image, "Resampling", Image).LANCZOS)
        os.makedirs(os.path.dirname(small), exist_ok=True)
        tmp = "%s.%d.new" % (small, threading.get_ident())
        try:
            im.save(tmp, "PNG")
            os.replace(tmp, small)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return small
    except Exception:                                   # (no Pillow, or a picture it can't read: the original)
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


def ppm_look(data, flat_share=0.985, near=24):
    """A picture (binary PPM, "P6") in a few words: {"flat": is it one colour, "colour": "#rrggbb" its commonest,
    "rgb", "share": how much of it is within `near` of that colour}. None if it isn't a picture."""
    try:
        if not data.startswith(b"P6"):
            return None
        fields, at = [], 2
        while len(fields) < 3:                              # width, height, the largest value: numbers, between blanks
            while data[at:at + 1].isspace():
                at += 1
            if data[at:at + 1] == b"#":
                at = data.index(b"\n", at) + 1
                continue
            end = at
            while not data[end:end + 1].isspace():
                end += 1
            fields.append(int(data[at:end]))
            at = end
        w, h, top = fields
        px = data[at + 1:at + 1 + w * h * 3]
        if top != 255 or w * h == 0 or len(px) < w * h * 3:
            return None
    except (ValueError, IndexError):
        return None
    counts = collections.Counter(px[i:i + 3] for i in range(0, len(px), 3))
    rgb = tuple(counts.most_common(1)[0][0])
    close = sum(n for c, n in counts.items() if abs(c[0] - rgb[0]) <= near and abs(c[1] - rgb[1]) <= near and abs(c[2] - rgb[2]) <= near)
    share = close / (w * h)
    return {"flat": share >= flat_share, "colour": "#%02x%02x%02x" % rgb, "rgb": rgb, "share": round(share, 4), "size": [w, h]}


def screen_picture(env, timeout=8):
    """What the TV shows right now, as the screen itself has it: cage's own picture of what it puts out (grim, at a
    tenth of the size), whatever is in front: the browser, a game, a window nobody closed. None where it can't be told
    (no grim, not cage's screen). It's the one look that doesn't take the browser's word for what it drew."""
    if not env.get("WAYLAND_DISPLAY"):
        return None
    try:
        p = subprocess.run(["grim", "-s", "0.1", "-t", "ppm", "-"], capture_output=True, env=env, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return ppm_look(p.stdout) if p.returncode == 0 else None


class Browser:
    """The box's Chromium, over its DevTools port: tabs are apps."""

    def __init__(self, port=DEVTOOLS_PORT, on_message=None, scale=None):
        self.port, self.on_message, self.scale = port, on_message, scale or (lambda: 1.0)
        self.page_script = ""        # run in every app's own pages before theirs (the agent's H264_ONLY on a Pi 3)
        self.ws, self.next_id, self.waiting = None, 0, {}
        self.tabs = {}               # target id -> {"app", "title", "url", "session", "used", "audible"}
        self.notes = collections.deque(maxlen=150)   # the pages' errors and their video players' messages, for a report
        self.lock = threading.Lock()
        self.screen = None           # what the TV shows now (the agent's: screen_picture), for wrong()
        self.said = collections.deque(maxlen=40)     # what went wrong on a way back to Home, and what was done
        self.gave_back = collections.deque(maxlen=12)   # the apps closed behind Home, and the memory that came back
        self.sounds = {}             # app -> how its sound went the last time it was asked (kept after it's closed)
        self.gone = collections.OrderedDict()   # session -> app, of pages closed: their last words keep their name
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

    def tell(self, method, params=None, session=None):
        """A call whose answer nobody waits for (the reader drops it)."""
        if not self.ws:
            raise OSError("no browser")
        with self.lock:
            self.next_id += 1
            mid = self.next_id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.ws.send(json.dumps(msg))

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
            self._remember_gone(self.tabs.pop(p.get("targetId"), None) or {})
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
            app = next((tab.get("app") for tab in self.tabs.values() if tab.get("session") == session), None) or \
                (getattr(self, "gone", None) or {}).get(session) or "?"
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
                self.call("Page.enable", {}, session, timeout=3)     # (without it the probe is gone once the page reloads)
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
            if tab.get("app") != "home":                       # in the page's own world, before its scripts run
                try:
                    self.call("Page.addScriptToEvaluateOnNewDocument", {"source": SOUND_PROBE}, session, timeout=3)
                    self.call("Runtime.evaluate", {"expression": SOUND_PROBE}, session, timeout=3)
                except OSError:
                    pass
            if self.page_script and tab.get("app") != "home":
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
                tab["frozen"] = False
            except OSError as exc:                       # (still frozen, and known to be: woken at the next try)
                self.say("A page didn't wake (%s)" % exc)
        behind = getattr(self, "front", None)
        self.call("Target.activateTarget", {"targetId": target})
        self.front = target
        if behind and behind != target and behind in self.tabs:
            self.tabs[behind]["left"] = time.time()      # out of sight from now (tidy counts from here)
        if target in self.tabs:
            self.tabs[target]["used"] = time.time()
            self.tabs[target].pop("left", None)
        threading.Thread(target=self.settle, args=(target,), daemon=True).start()

    def settle(self, front):
        """The app in front gets the box: the others are frozen (no scripts, timers or drawing) unless they're
        playing something you can hear, so music carries on. Home and the others wake up when they're opened."""
        time.sleep(1.5)                                  # let the one in front start first
        for t, tab in list(self.tabs.items()):
            if t == front or tab.get("frozen") or not tab.get("session") or tab.get("app") in KEEP_AWAKE:
                continue
            try:
                playing = self.heard(tab)
                if not playing and getattr(self, "front", None) != t:
                    self.call("Page.setWebLifecycleState", {"state": "frozen"}, tab["session"], timeout=3)
                    tab["frozen"] = True
            except OSError:
                pass

    def heard(self, tab, timeout=3):
        """Is this page playing something you can hear? And what it says of how its sound went is kept for a report."""
        got = self.call("Runtime.evaluate", {"expression": HEARD_JS, "returnByValue": True}, tab["session"], timeout=timeout)
        try:
            said = json.loads(got.get("result", {}).get("value") or "{}")
        except (TypeError, ValueError):
            said = {}
        if said.get("sound") and tab.get("app"):
            sounds = getattr(self, "sounds", None)
            if sounds is not None:
                sounds[tab["app"]] = dict(said["sound"], at=time.strftime("%H:%M:%S"))
        return bool(said.get("playing"))

    def sound_lines(self):
        """For a report: each app's sound since its page loaded. A wait is sound that stopped until more arrived."""
        for tab in list(self.tabs.values()):               # (the ones awake are asked now; asleep ones keep what they said)
            if tab.get("session") and not tab.get("frozen") and tab.get("app") not in ("home", None):
                try:
                    self.heard(tab, timeout=2)
                except OSError:
                    pass
        out = []
        for app, h in sorted(self.sounds.items()):
            if not h.get("started"):
                continue
            out.append("  %s: started %d, stopped to wait for more %d time%s%s, stalled %d, errors %d (asked at %s)" % (
                app, h["started"], h.get("waits", 0), "" if h.get("waits") == 1 else "s",
                " (the longest %.1f s)" % (h["longest"] / 1000) if h.get("longest") else "", h.get("stalls", 0),
                h.get("errors", 0), h.get("at", "?")))
        return out

    def now_playing(self):
        """The box's mini player: the app that's playing something you can hear (or played something last and is
        paused), what it says it's playing, and the buttons it has. None when nothing has played."""
        best = None
        for t, tab in list(self.tabs.items()):
            if tab.get("app") in ("home", None) or tab.get("frozen") or not tab.get("session") or tab.get("passing"):
                continue
            try:
                got = json.loads(self.call("Runtime.evaluate", {"expression": NOW_JS, "returnByValue": True}, tab["session"],
                                           timeout=2).get("result", {}).get("value") or "null")
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(got, dict) or not got.get("started") or not (got.get("playing") or got.get("said")):
                continue                                 # (a muted preview played and stopped: not music)
            got.update(target=t, app=tab.get("app"), front=t == getattr(self, "front", None),
                       title=str(got.get("title") or tab.get("title") or "")[:200], used=tab.get("used") or 0)
            rank = (bool(got.get("playing")), got["used"])
            if best is None or rank > (bool(best.get("playing")), best["used"]):
                best = got
        if best:
            best.pop("used", None)
            if best.get("art") and not str(best["art"]).startswith(("https://", "http://", "data:image/")):
                best["art"] = None
        return best

    def music(self, target, act):
        """A button of the mini player, pressed in the app that plays: its own if it gave the browser one."""
        if act not in MUSIC_ACTS:
            raise ValueError("That isn't a button of the mini player.")
        tab = self.tabs.get(target) or {}
        if not tab.get("session"):
            raise ValueError("That app isn't open any more.")
        got = self.call("Runtime.evaluate", {"expression": ACT_JS % json.dumps(act), "returnByValue": True,
                                             "userGesture": True}, tab["session"], timeout=3)
        return bool(got.get("result", {}).get("value"))

    def tidy(self, grace, now=None, wait=2.0):
        """The apps left behind give the box back. Asleep, an app costs no processor, but it still holds its memory
        and its share of the graphics chip: its process is still there. So an app that has been out of sight for
        `grace` seconds is closed, and its process ends. Never the page in front, Home or Sofa, and never one that's
        playing something you can hear (music carries on behind Home). Opened again within `grace`, it's as it was
        left. What was closed: [{"app", "left" (seconds out of sight), "before", "after" (MB of memory free)}]."""
        now = now or time.time()
        front = getattr(self, "front", None)
        closed = []
        for t, tab in list(self.tabs.items()):
            if t == front or tab.get("app") in ("home", None) + KEEP_AWAKE or tab.get("passing") or not tab.get("session"):
                continue
            if not tab.get("left"):                      # (a window an app opened itself: counted from when it's seen)
                tab["left"] = now
                continue
            if now - tab["left"] < grace:
                continue
            if not tab.get("frozen"):                    # awake behind the page in front: it was playing. Is it still?
                try:
                    if self.heard(tab):
                        continue
                except OSError:
                    pass
            before = available_mb()
            try:
                self.close(t)
            except OSError:
                continue
            closed.append({"app": tab.get("app"), "left": int(now - tab["left"]), "before": before, "after": None})
        if closed:
            if wait:
                time.sleep(wait)                         # (the process is gone a moment after its page)
            after = available_mb()
            for c in closed:
                c["after"] = after
                self.gave_back.append("%s %s, %d s out of sight%s" % (
                    time.strftime("%H:%M:%S"), c["app"], c["left"],
                    "" if after is None or c["before"] is None else ", memory free %d to %d MB" % (c["before"], after)))
        return closed

    def rest(self, close_apps=False):
        """A game takes the box: the pages behind stop (frozen), the apps that aren't Sofa close on a small box, and the
        browser lets go of the memory it can. Never the page in front, never an app that's playing something you can
        hear (music carries on under a game), and never Home: Home stops its own asking
        around while a game is open (the agent tells it), and stays a page the browser can show.

        (Home was frozen too, in front as it was. To freeze a page the browser first marks it hidden, and waking it
        doesn't mark it shown again: only another page coming in front and going does. So after a game Home's scripts
        ran, the keys reached it, and the browser drew nothing: a white screen, on every way back to Home.)"""
        front = getattr(self, "front", None)
        for t, tab in list(self.tabs.items()):
            if not tab.get("session"):
                continue
            if t != front and tab.get("app") not in ("home", None) and not tab.get("frozen"):
                try:                                     # music carries on under a game: the app that's playing it stays
                    if self.heard(tab):                  # as it is, on a small box too
                        continue
                except OSError:
                    pass
            if close_apps and tab.get("app") not in ("home", None) + KEEP_AWAKE:
                try:
                    self.close(t)
                except OSError:
                    pass
                continue
            if t == front or tab.get("app") == "home":
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

    def front_url(self):
        return (self.tabs.get(getattr(self, "front", None)) or {}).get("url") or ""

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
            # the key going down sent without waiting for the browser's answer (it takes events in the order they're
            # sent), so the page has it a round trip sooner; the wait is for the key coming up
            events = [dict(e, key=key, code=key, windowsVirtualKeyCode=keycode, nativeVirtualKeyCode=keycode) for e in (down, {"type": "keyUp"})]
            self.tell("Input.dispatchKeyEvent", events[0], session)
            self.call("Input.dispatchKeyEvent", events[1], session)

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

    HOME_ALIVE_JS = "!!(document.body && document.getElementById('view') && document.getElementById('view').childElementCount)"

    def home(self, look=None):
        """Home in front, and checked a moment later (revive). `look`: take the screen's own picture too; by itself
        only when Home wasn't in front already (back from an app), and the agent asks for it after a game. Home pressed
        on Home costs no picture."""
        target = self.tab_of("home")
        if target:
            was_front = getattr(self, "front", None) == target
            self.activate(target)
            threading.Thread(target=self.revive, args=(target, 1.2, (not was_front) if look is None else look), daemon=True,
                             name="home-check").start()
            return True
        return False

    def alive(self, target, timeout=3):
        """Does the tab's page answer, with something in it?"""
        tab = self.tabs.get(target) or {}
        if not tab.get("session"):
            return False
        try:
            return bool(self.call("Runtime.evaluate", {"expression": self.HOME_ALIVE_JS, "returnByValue": True}, tab["session"],
                                  timeout=timeout).get("result", {}).get("value"))
        except OSError:
            return False

    LOOK_JS = "JSON.stringify([document.visibilityState, getComputedStyle(document.body || document.documentElement).backgroundColor])"

    def wrong(self, target, look=True):
        """What's wrong with the page that should be on the TV now, in a few words; None if it's there.

        A page can answer, hold everything it should, take the remote's keys, and still not be drawn: the browser has
        it down as hidden (see rest), or what reaches the TV is one flat colour. So three looks: the page has
        something in it; the browser says it's showing it; and the TV's own picture (self.screen, the agent's: the
        screen as cage has it) isn't one colour that isn't the page's own background."""
        tab = self.tabs.get(target) or {}
        if not self.alive(target):
            return "its page has nothing in it"
        background = None
        try:
            got = json.loads(self.call("Runtime.evaluate", {"expression": self.LOOK_JS, "returnByValue": True}, tab["session"],
                                       timeout=3).get("result", {}).get("value") or "[]")
            if got and got[0] == "hidden":
                return "the browser has it down as hidden"
            m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", got[1] if len(got) > 1 else "")
            background = tuple(int(x) for x in m.groups()) if m else None
        except (OSError, ValueError, TypeError):
            pass
        seen = None
        try:
            seen = self.screen() if look and self.screen else None
        except Exception:
            pass
        if seen and seen.get("flat"):
            rgb = seen["rgb"]
            if background is None or max(abs(rgb[i] - background[i]) for i in range(3)) > 8:   # (a bare dark page is its own colour)
                return "the TV shows one flat colour (%s)" % seen["colour"]
        return None

    def show(self, target):
        """The page shown by the browser again: another page comes in front of it, then it does. (Nothing else marks a
        page shown once the browser has it down as hidden while it's in front: not waking it, not bringing it to the
        front, not loading it again.)"""
        tab = self.tabs.get(target) or {}
        if tab.get("session"):
            try:
                self.call("Page.setWebLifecycleState", {"state": "active"}, tab["session"], timeout=3)
            except OSError:
                pass
            tab["frozen"] = False
        blank = self.call("Target.createTarget", {"url": "about:blank"}, timeout=8).get("targetId")     # (in front)
        if not blank:
            raise OSError("the browser made no new page")
        self.tabs.setdefault(blank, {"used": time.time(), "session": None, "audible": False}).update(passing=True)
        time.sleep(0.4)
        try:
            self.call("Target.activateTarget", {"targetId": target}, timeout=5)
        finally:
            try:
                self.close(blank)
            except OSError:
                pass
        self.front = target

    def reload(self, target):
        tab = self.tabs.get(target) or {}
        self.call("Page.setWebLifecycleState", {"state": "active"}, tab["session"], timeout=3)
        self.call("Page.reload", {}, tab["session"], timeout=5)
        for _ in range(16):
            time.sleep(0.5)
            if self.alive(target, timeout=2):
                return

    def renew(self, target):
        """A new Home in the old one's place (a page that never answers)."""
        tab = self.tabs.get(target) or {}
        url = tab.get("url") if "/box/home" in (tab.get("url") or "") else None
        if not url:
            raise OSError("not Home")
        self.close(target)
        new = self.call("Target.createTarget", {"url": url.split("#")[0] + "#/"})["targetId"]
        self.tabs.setdefault(new, {"used": time.time(), "session": None, "audible": False}).update(app="home", url=url)
        self.activate(new)
        return new

    def restart(self):
        """The whole browser, again: the TV's screen starts a new one by itself (sofa-box session), on Home. At most
        once in two minutes, so a box whose screen stays wrong isn't kept starting browsers (hold Home for that)."""
        if time.monotonic() - getattr(self, "restarted", -1e9) < 120:
            return False
        self.restarted = time.monotonic()
        try:
            self.call("Browser.close", timeout=5)
        except OSError:
            try:
                subprocess.run(["pkill", "-KILL", "-f", "--", "--remote-debugging-port=%d" % self.port], capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
        return True

    def revive(self, target, settle=1.2, look=True):
        """Home just brought forward (after a game, from an app): is it really on the TV? If not, by steps, each one
        looked at again: another page in front and back, the page loaded again, a new Home, and last the whole browser
        again. What was wrong and what was done goes in the journal and the next report (self.said). True: it's there."""
        time.sleep(settle)
        if target not in self.tabs or getattr(self, "front", None) != target:
            return True
        why = self.wrong(target, look)
        if not why:
            return True
        for what, step in (("another page in front of it and back", self.show), ("loading it again", self.reload),
                           ("a new Home in its place", self.renew)):
            self.say("Home didn't come back (%s): %s" % (why, what))
            try:
                got = step(target)
                target = got or target
            except Exception as exc:                        # (whatever it was: the next step is still tried)
                self.say("  that didn't work (%s)" % (exc or exc.__class__.__name__))
            time.sleep(1.5)
            if target not in self.tabs or getattr(self, "front", None) != target:
                return True                                 # (something else is in front by now: an app, a game)
            why = self.wrong(target)                        # (the screen's picture too, from here on)
            if not why:
                self.say("Home is back on the TV")
                return True
        if self.restart():
            self.say("Home still isn't on the TV (%s): the browser starts again" % why)
        else:
            self.say("Home still isn't on the TV (%s). Hold Home for 4 seconds to start the TV's screen again." % why)
        return False

    def say(self, text):
        """A line for the journal and for the next report (what went wrong on the way back to Home)."""
        if not hasattr(self, "said"):
            self.said = collections.deque(maxlen=40)
        self.said.append("%s %s" % (time.strftime("%H:%M:%S"), text))
        print(text, file=sys.stderr, flush=True)

    def close(self, target):
        """A page closed. Asleep, it's woken first, so it says its last (a game says how it ran as its page goes, for a
        report); and what it says then keeps its app's name."""
        tab = self.tabs.get(target) or {}
        if tab.get("session"):
            self._remember_gone(tab)
            if tab.get("frozen"):
                try:
                    self.call("Page.setWebLifecycleState", {"state": "active"}, tab["session"], timeout=3)
                except OSError:
                    pass
        self.call("Target.closeTarget", {"targetId": target})
        self.tabs.pop(target, None)

    def _remember_gone(self, tab):
        gone = getattr(self, "gone", None)
        if gone is None or not tab.get("session") or tab.get("app") in (None, "home"):
            return
        gone[tab["session"]] = tab["app"]
        while len(gone) > 30:
            gone.popitem(last=False)

    def running(self):
        return [{"target": t, "app": tab.get("app"), "title": tab.get("title", ""), "url": tab.get("url", ""),
                 "used": tab.get("used"), "frozen": bool(tab.get("frozen"))} for t, tab in self.tabs.items()
                if tab.get("app") not in ("home", None) and not tab.get("passing")]

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
                if name in out:                                  # (two of one app: added up, page by page too)
                    v = merge_smooth(out[name], v)
                out[name] = v
        return out

    def gpu(self):
        """How the browser draws: on the graphics chip or by the processor (chrome://gpu's own words, short)."""
        g = self.call("SystemInfo.getInfo", timeout=5).get("gpu") or {}
        f, aux = g.get("featureStatus") or {}, g.get("auxAttributes") or {}
        on = lambda k: "on" if str(f.get(k, "")).startswith("enabled") else (f.get(k) or "?")   # noqa: E731
        return "compositing %s, raster %s, video decode %s (%s)" % (on("gpu_compositing"), on("rasterization"), on("video_decode"),
                                                                    aux.get("glRenderer") or "renderer not said")


def merge_smooth(a, b):
    """Two pages' speed (two tabs of one app) as one."""
    out = {k: (max if k == "worst" else sum)((a.get(k, 0), b.get(k, 0))) for k in set(a) | set(b) if k != "pages"}
    pages = {}
    for p in (a.get("pages") or {}, b.get("pages") or {}):
        for name, v in p.items():
            have = pages.setdefault(name, {})
            for k, x in v.items():
                have[k] = [i + j for i, j in zip(have.get(k) or [0] * len(x), x)] if isinstance(x, list) else \
                    max(have.get(k, 0), x) if k.endswith("worst") else have.get(k, 0) + x
    if pages:
        out["pages"] = pages
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
# Page by page too (Home, its Settings, Sofa's pages: the part of the address after #/, never what's on it), with how
# many presses answered within 0.05, 0.1 and 0.25 s, and where a slow one's time went: waiting for the page to be free,
# the page's own code for the key, or drawing the answer (style, layout, painting, the graphics chip).
SMOOTH_PROBE = r"""(function () {
  if (window.__sofaSmooth) return;
  var s = { presses: 0, slow: 0, worst: 0, long: 0, long_ms: 0, pages: {} }, recent = [];
  function name() {
    var h = String(location.hash).replace(/^#!?\/?/, "").split(/[\/?&=#]/)[0].toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 20);
    return /^\/box\/home/.test(location.pathname) || window.SofaBox ? h || "home" : "page";
  }
  function of(p) { return s.pages[p] || (s.pages[p] = { presses: 0, slow: 0, worst: 0, hist: [0, 0, 0, 0, 0], wait: 0, code: 0, draw: 0,
    move: 0, move_slow: 0, move_worst: 0, ok: 0, ok_slow: 0, ok_worst: 0 }); }
  // (moving the focus and OK apart: an arrow should cost next to nothing, OK opens or changes something)
  function kind(e) { return /^Arrow/.test(e.key) ? "move" : e.key === "Enter" ? "ok" : ""; }
  addEventListener("keydown", function (e) {
    var p = name(), k = kind(e);
    s.presses++; of(p).presses++;
    if (k) of(p)[k]++;
    recent.push([e.timeStamp, p, k]); if (recent.length > 40) recent.shift();
  }, true);
  try {
    new PerformanceObserver(function (list) {
      list.getEntries().forEach(function (e) {
        if (e.name !== "keydown") return;
        var d = e.duration, p = null, k = "";
        for (var i = recent.length - 1; i >= 0 && !p; i--) if (Math.abs(recent[i][0] - e.startTime) < 1) { p = recent[i][1]; k = recent[i][2]; }
        var v = of(p || name());
        if (k) { if (d > v[k + "_worst"]) v[k + "_worst"] = Math.round(d); if (d >= 100) v[k + "_slow"]++; }
        if (d > s.worst) s.worst = Math.round(d);
        if (d > v.worst) v.worst = Math.round(d);
        if (d >= 50) v.hist[d < 100 ? 0 : d < 250 ? 1 : d < 500 ? 2 : d < 1000 ? 3 : 4]++;    // (0.05-0.1, -0.25, -0.5, -1 s, more)
        if (d >= 100) {
          s.slow++; v.slow++;
          v.wait += Math.max(0, Math.round(e.processingStart - e.startTime));
          v.code += Math.max(0, Math.round(e.processingEnd - e.processingStart));
          v.draw += Math.max(0, Math.round(e.startTime + d - e.processingEnd));
        }
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
