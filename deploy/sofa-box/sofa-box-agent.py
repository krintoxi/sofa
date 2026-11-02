#!/usr/bin/env python3
"""The Sofa box agent: what makes a Raspberry Pi on the TV a Sofa box.

The box's browser (Chromium, full screen) opens http://127.0.0.1:8091/. This agent:
- finds Sofa on the home network (the address it had, Bonjour, SSDP) or takes a typed one, and asks
  when there's more than one (the start page, /box/finder);
- then passes Sofa's TV pages through to the browser, adding one small script (/box/native.js) that
  gives them the same "native player" Sofa's Fire TV app has (window.SofaNative);
- plays videos with mpv, full screen with the Pi's hardware decoder (H.264; Sofa converts what the
  box can't play), saves the place in Sofa every 10 seconds, offers Skip Intro, takes the remote's
  keys and the phone remote's commands, and tells the page when a video ends (next episode);
- notices dropped frames, and asks Sofa for 720p from then on if the box can't keep up at 1080p;
- answers the TV pages' Box settings (/box/api/...): quality, sound, the boot screen, Wi-Fi,
  controllers, the TV remote, restart, another Sofa;
- serves a preview of all that for a computer, before there's a Pi (/box/preview,
  tools/sofa-box-preview.py).

Standard library only (Python 3.7+). Settings: ~/.config/sofa-box/settings.json.
"""
import http.client
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxos  # noqa: E402  (Sofa Box OS: apps, store, files, the browser's tabs)
import boxservers  # noqa: E402  (the servers it plays from: Sofa at home, on the internet, on the box; Jellyfin, Emby, Plex)

PORT = int(os.environ.get("SOFA_BOX_PORT", "8091"))
HERE = os.path.dirname(os.path.abspath(__file__))
CONF_DIR = os.environ.get("SOFA_BOX_CONF") or os.path.expanduser("~/.config/sofa-box")
SETTINGS = os.path.join(CONF_DIR, "settings.json")
OLD_SAVED = os.path.join(CONF_DIR, "server")                # from the first Sofa box
SOFA_ST = "urn:sofa-media:device:Sofa:1"
VERSION = "2"
DEFAULTS = {"server": None, "quality": "auto", "hwdec": "auto", "audio": "auto", "learned_720": False,
            "mpv_args": [], "theme": "street", "boot_text": "", "shield": True, "welcomed": False}
THEMES = ("street", "terminal", "pirate", "sofa", "midnight", "cinema", "ocean", "forest", "grape", "oled")
CHOICES = {"quality": ("auto", "720", "1080"), "audio": ("auto", "passthrough"),
           "hwdec": ("auto", "no", "v4l2m2m-copy", "drm", "auto-safe"), "theme": THEMES}
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding",
       "upgrade", "content-length", "host", "accept-encoding"}

_lock = threading.Lock()
found = {}                               # url -> {"name", "id"}
state = {"chosen": None}


def toast(text):
    """A message on the TV."""
    player.tell(toast=text)


def go(where):
    """Send the TV's page somewhere ("#/" is Home)."""
    player.tell(go=where)



def display_env():
    """The screen's address for mpv. The kiosk session writes it (cage's Wayland socket or X's display),
    since this agent runs as its own service, outside that session."""
    env = dict(os.environ)
    run_dir = env.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    try:
        with open(os.path.join(run_dir, "sofa-box-display"), encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k in ("WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY") and v:
                    env[k] = v
    except OSError:
        pass
    env.setdefault("XDG_RUNTIME_DIR", run_dir)
    sock = env.get("WAYLAND_DISPLAY")
    if not (sock and os.path.exists(os.path.join(run_dir, sock))) and not env.get("DISPLAY"):
        try:                                        # no word from the session: look for a screen ourselves
            names = sorted(n for n in os.listdir(run_dir) if n.startswith("wayland-") and not n.endswith(".lock"))
        except OSError:
            names = []
        if names:
            env["WAYLAND_DISPLAY"] = names[0]
        elif os.path.exists("/tmp/.X11-unix/X0"):
            env["DISPLAY"] = ":0"
    return env


_mpv_help = {}


def mpv_knows(what, name):
    """Whether this mpv has a profile or hwdec called `name` ("fast" is new in mpv 0.37; Raspberry Pi OS
    Bookworm has 0.35, and an unknown profile stops mpv before it plays anything)."""
    mpv = os.environ.get("SOFA_BOX_MPV", "mpv")
    if mpv.endswith(".py"):
        return False
    if what not in _mpv_help:
        try:
            _mpv_help[what] = subprocess.run([mpv, "--%s=help" % what], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            _mpv_help[what] = ""
    return bool(re.search(r"(?m)^\s*%s(\s|$)" % re.escape(name), _mpv_help[what]))


# ---------------------------------------------------------------- settings

def settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            s = dict(DEFAULTS, **json.load(f))
    except (OSError, ValueError):
        s = dict(DEFAULTS)
    if not s["server"]:
        try:
            with open(OLD_SAVED, encoding="utf-8") as f:
                s["server"] = f.read().strip() or None
        except OSError:
            pass
    return s


def save_settings(**changes):
    with _lock:
        s = settings()
        s.update(changes)
        os.makedirs(CONF_DIR, exist_ok=True)
        tmp = SETTINGS + ".new"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, SETTINGS)
    return s


def model():
    try:
        with open("/proc/device-tree/model", encoding="utf-8", errors="replace") as f:
            return f.read().strip("\x00\n ")
    except OSError:
        return ""


def slow_board():
    """A Raspberry Pi 3 or older: 1080p H.264 is about its limit, HEVC is out."""
    m = model()
    return bool(re.search(r"Raspberry Pi (Zero|[1-3])\b", m)) or (not m and os.environ.get("SOFA_BOX_SLOW") == "1")


def max_height():
    s = settings()
    if s["quality"] in ("720", "1080"):
        return int(s["quality"])
    return 720 if s["learned_720"] else 1080


def caps():
    """What the box plays itself (mpv on the Pi): told to Sofa, so it converts only the rest."""
    return {"mkv": True, "hevc": not slow_board(), "hevc10": not slow_board(), "ac3": True, "vp9": not slow_board(),
            "maxh": max_height()}


# ---------------------------------------------------------------- finding Sofa

def info(base):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(base.rstrip("/") + "/api/info", timeout=3) as r:
            j = json.loads(r.read().decode("utf-8"))
        return j if j.get("sofa") else None
    except Exception:
        return None


def add(base):
    base = base.rstrip("/")
    with _lock:
        if base in found:
            return
    j = info(base)
    if j:
        with _lock:
            if not (j.get("id") and any(v.get("id") == j["id"] for v in found.values())):
                found[base] = {"name": j.get("name") or "Sofa", "id": j.get("id")}


def bonjour():
    try:
        out = subprocess.run(["avahi-browse", "-rtp", "_sofa._tcp"], capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return ["http://%s:%s" % (p[7], p[8]) for p in (line.split(";") for line in out.splitlines())
            if len(p) > 8 and p[0] == "=" and p[2] == "IPv4"]


def ssdp():
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: %s\r\n\r\n" % SOFA_ST).encode()
    hits = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.settimeout(1.0)
        s.sendto(msg, ("239.255.255.250", 1900))
        end = time.time() + 3
        while time.time() < end:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                continue
            m = re.search(r"(?im)^LOCATION:\s*(https?://[^/\s]+)", data.decode("utf-8", "replace"))
            if m:
                hits.append(m.group(1))
    except OSError:
        pass
    finally:
        s.close()
    return hits


def look():
    while True:
        last = settings()["server"]
        if last:
            add(last)
            with _lock:
                if state["chosen"] is None and last.rstrip("/") in found:     # the Sofa it had: straight away
                    state["chosen"] = last.rstrip("/")
        if not state["chosen"]:
            for base in bonjour() + ssdp():
                add(base)
        with _lock:
            if state["chosen"] is None:
                if last and last.rstrip("/") in found:
                    state["chosen"] = last.rstrip("/")
                elif len(found) == 1:
                    state["chosen"] = next(iter(found))
        if state["chosen"] and state["chosen"] != last:
            save_settings(server=state["chosen"])
        time.sleep(4 if not state["chosen"] else 30)


def server():
    return state["chosen"]


# ---------------------------------------------------------------- mpv: the player

class Player:
    """One video at a time in mpv, controlled over its JSON socket."""

    def __init__(self):
        self.proc, self.sock_path, self.payload, self.cookie, self.base = None, None, None, "", None
        self.status = {}
        self.news, self.seq = [], 0             # what the page hears about, numbered (every page gets all of it)
        self.cond = threading.Condition()
        self.req = 0

    def _args(self, p):
        s, sock, base = settings(), self.sock_path, self.base
        mpv = os.environ.get("SOFA_BOX_MPV", "mpv")         # previews and tests can use a stand-in
        args = ([sys.executable] if mpv.endswith(".py") else []) + [mpv, "--input-ipc-server=" + sock, "--fs", "--force-window=immediate", "--idle=no", "--keep-open=no",
                "--osd-level=1", "--osd-font-size=46", "--osd-bar-h=2.2", "--sub-font-size=46", "--term-osd=no",
                "--title=" + ("Sofa" if p.get("adult") else p.get("title") or "Sofa"),
                "--input-conf=" + os.path.join(HERE, "mpv-input.conf"),
                "--cache=yes", "--demuxer-max-bytes=120MiB", "--network-timeout=40"]
        if not p.get("local"):                              # from Sofa: as the signed-in TV
            args.append("--http-header-fields=Cookie: %s,X-Sofa: 1" % self.cookie.replace(",", "%2C"))
        hw = s["hwdec"] if s["hwdec"] != "auto" else ("v4l2m2m-copy" if slow_board() and mpv_knows("hwdec", "v4l2m2m-copy")
                                                      else "auto-safe")
        args.append("--hwdec=" + hw)
        if slow_board():
            args += (["--profile=fast"] if mpv_knows("profile", "fast") else []) + ["--vd-lavc-threads=4", "--video-sync=audio"]
        if s["audio"] == "passthrough":
            args.append("--audio-spdif=ac3,eac3,dts")
        if p.get("start"):
            args.append("--start=%.1f" % float(p["start"]))
        for sub in p.get("subtitles") or []:
            args.append("--sub-file=" + rewrite(sub.get("url", ""), base))
        for k, v in (p.get("mpv") or {}).items():           # a disc: which drive
            args.append("--%s=%s" % (k, v))
        args += list(s.get("mpv_args") or []) + shlex_split(os.environ.get("SOFA_BOX_MPV_ARGS", ""))
        return args + [p["url"] if p.get("local") else rewrite(p["url"], base)]

    def play(self, payload, cookie, base=None):
        self.stop(save=True, reason="replaced")
        self.payload, self.cookie, self.base = payload, cookie, base or server()
        self.sock_path = os.path.join(tempfile.gettempdir(), "sofa-mpv-%d.sock" % os.getpid())
        try:
            os.unlink(self.sock_path)
        except OSError:
            pass
        private = bool(payload.get("adult"))            # no adult titles anywhere outside the Adult section
        self.status = {"item": payload.get("item"), "t": int(payload.get("offset") or 0) + int(payload.get("start") or 0),
                       "d": int(payload.get("duration") or 0), "paused": False,
                       "title": "Playing" if private else payload.get("title"), "sub": "" if private else payload.get("sub")}
        self.proc = subprocess.Popen(self._args(payload), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, env=display_env())
        self.proc.sofa_err = []
        threading.Thread(target=self._drain, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._watch, args=(self.proc,), daemon=True).start()

    @staticmethod
    def _drain(proc):
        """mpv's messages, read as they come (a full pipe would stop mpv); the last few explain a failure."""
        for line in proc.stderr:
            proc.sofa_err = (proc.sofa_err + [line.decode("utf-8", "replace").rstrip()])[-8:]

    def command(self, *cmd):
        """Send one command to mpv; returns its "data" (or None)."""
        if not self.sock_path or not self.proc or self.proc.poll() is not None:
            return None
        self.req += 1
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(self.sock_path)
            s.sendall((json.dumps({"command": list(cmd), "request_id": self.req}) + "\n").encode())
            buf = b""
            while True:
                part = s.recv(65536)
                if not part:
                    break
                buf += part
                for line in buf.split(b"\n"):
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("request_id") == self.req:
                        s.close()
                        return msg.get("data")
        except OSError:
            pass
        return None

    def position(self):
        """Seconds into the whole video (a converted stream starts at the payload's offset)."""
        t = self.command("get_property", "time-pos")
        return None if t is None else float(t) + float((self.payload or {}).get("offset") or 0)

    def _watch(self, proc):
        """Every second: where it is, Skip Intro, saving the place; at the end: tell the page."""
        p, last_save, intro_shown = self.payload, 0, None
        drops_checked = started = False
        while proc.poll() is None:
            time.sleep(1)
            t = self.position()
            if t is None:
                continue
            started = True
            d = float(p.get("duration") or 0) or float(self.command("get_property", "duration") or 0) + float(p.get("offset") or 0)
            paused = bool(self.command("get_property", "pause"))
            self.status.update(t=int(t), d=int(d), paused=paused)
            marker = self.marker(t)
            if marker and intro_shown != marker["start"]:
                intro_shown = marker["start"]
                self.command("show-text", "OK: skip the %s" % ("recap" if marker.get("kind") == "recap" else "intro"), 6000)
            if d and time.time() - last_save > 10:
                last_save = time.time()
                save_progress(p.get("item"), t, d, False, self.cookie, self.base)
            if not drops_checked and t - float(p.get("start") or 0) - float(p.get("offset") or 0) > 90:
                drops_checked = True
                self.check_drops()
        code = proc.wait()
        time.sleep(0.2)                         # the last of mpv's messages
        err = "\n".join(l for l in proc.sofa_err if l.strip())
        t, d = self.status.get("t") or 0, self.status.get("d") or 0
        reason = getattr(proc, "sofa_reason", None)
        ended = reason == "next" or (reason is None and code == 0 and d and t > d - 60)
        watched = ended or (d and t > d * 0.95)
        if d:
            save_progress(p.get("item"), d if watched else t, d, bool(watched), self.cookie, self.base)
        failed = code not in (0, 4) and reason is None
        last = (err.splitlines() or ["mpv stopped"])[-1][:120]
        if failed:
            print("mpv stopped (%s): %s" % (code, err.replace("\n", " | ")[-600:]), file=sys.stderr, flush=True)
        if failed and started:
            toast("That video couldn't play on the box: " + last)
        if proc is self.proc:
            self.proc = None
            self.status = {}
        if reason == "replaced":                # another video took its place: the page knows already
            return
        done = {"item": p.get("item"), "t": t, "d": d, "ended": bool(ended), "done": bool(watched)}
        if failed and not started and not p.get("local"):     # mpv couldn't even start: the page plays it itself
            done.update(failed=True, error=last)
        elif failed and not started:
            toast("That couldn't play on the box: " + last)
        self.tell(done=done)

    def tell(self, **what):
        with self.cond:
            self.seq += 1
            self.news = [n for n in self.news if time.time() - n["at"] < 60] + [dict(what, n=self.seq, at=time.time())]
            self.cond.notify_all()

    def marker(self, t):
        for m in (self.payload or {}).get("markers") or []:
            if m.get("kind") in ("intro", "recap") and m["start"] <= t < m["end"] - 1:
                return m
        return None

    def check_drops(self):
        """1080p the box can't keep up with: ask Sofa for 720p from now on (the setting can say otherwise)."""
        drops = (self.command("get_property", "frame-drop-count") or 0) + (self.command("get_property", "decoder-frame-drop-count") or 0)
        fps = float(self.command("get_property", "container-fps") or 25)
        if settings()["quality"] == "auto" and drops > fps * 90 * 0.03 and not settings()["learned_720"]:
            save_settings(learned_720=True)
            toast("Videos come as 720p on this box from now on: it couldn't keep up at 1080p.")

    def ok(self):
        """OK on the remote while playing: skip the intro when it's on, else pause/play."""
        t = self.position()
        m = self.marker(t) if t is not None else None
        if m:
            self.command("seek", m["end"] - float((self.payload or {}).get("offset") or 0), "absolute")
        else:
            self.command("cycle", "pause")

    def control(self, c):
        cmd, off = c.get("cmd"), float((self.payload or {}).get("offset") or 0)
        if cmd == "toggle":
            self.command("cycle", "pause")
        elif cmd == "pause":
            self.command("set_property", "pause", True)
        elif cmd == "resume":
            self.command("set_property", "pause", False)
        elif cmd == "seek":
            self.command("seek", max(0.0, float(c.get("t") or 0) - off), "absolute")
        elif cmd == "skip":
            self.command("seek", float(c.get("by") or 0), "relative")
        elif cmd in ("stop", "next"):
            self.stop(save=True, reason=cmd)

    def stop(self, save=True, reason="stop"):
        proc = self.proc
        if proc and proc.poll() is None:
            proc.sofa_reason = reason
            self.command("quit")
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def events(self, since=None, timeout=25):
        """What the page should hear about after number `since`: videos that ended, messages, somewhere to go
        (a controller's Home button). A page that has just opened asks without `since` and hears only what comes next."""
        with self.cond:
            if since is None:
                return {"n": self.seq, "news": []}
            if self.seq <= since:
                self.cond.wait(timeout)
            return {"n": self.seq, "news": [{k: v for k, v in n.items() if k != "at"} for n in self.news if n["n"] > since]}


player = Player()
apps = boxos.Apps(CONF_DIR)
boxos.store_icons.folder = os.path.join(CONF_DIR, "store-icons")


def page_message(msg, target, tab):
    """What a page's Sofa bar asks (through the browser): Home, Close, Add to Home."""
    a = msg.get("a")
    if a == "home":
        browser.home()
    elif a == "close" and target:
        browser.close(target)
        browser.home()
    elif a == "add" and msg.get("url"):
        try:
            entry = boxos.site_entry(msg["url"], msg.get("title"))
        except ValueError:
            return
        entry["icon"] = msg.get("icon") or ""
        if tab.get("app") not in ("browser", "home", None):     # adding an app's page: it keeps the app's colour
            known = apps.get(tab["app"]) or {}
            entry["color"] = known.get("color")
        apps.install(entry)


browser = boxos.Browser(on_message=page_message) if os.environ.get("SOFA_BOX_DEVTOOLS", "9222") != "0" else None


def go_home():
    """The Home key, from anywhere: the box's home screen in front."""
    if browser and browser.connected():
        return browser.home()
    go("#/")
    return False


def open_app(app_id=None, url=None, hash_=None):
    """An app's tab (or the browser's) brought forward; `hash_` takes Sofa to a page in it. Without the
    browser connection (a preview, tests), the address goes back to the page, which opens it itself."""
    if app_id:
        app = apps.get(app_id)
        if not app:
            raise ValueError("That app isn't on this box.")
        target_url = "http://127.0.0.1:%d%s" % (PORT, app["url"]) if app["url"].startswith("/") else app["url"]
        ua = boxos.tv_user_agent() if app.get("ua") == "tv" else ""
    else:
        if not re.match(r"^https?://", str(url or "")):
            raise ValueError("That doesn't look like a web address.")
        app_id, target_url, ua = "browser", url, ""
    if hash_ and re.match(r"^#/[\w/%:.|-]*$", hash_):
        target_url = target_url.split("#")[0] + hash_
    if browser and browser.connected():
        existing = browser.tab_of(app_id)
        if existing and hash_ and app_id != "browser":
            browser.evaluate(existing, "location.hash = %s" % json.dumps(hash_))
        return {"ok": True, "target": browser.open(app_id, target_url, ua)}
    return {"ok": True, "url": target_url}


# ---------------------------------------------------------------- servers: which Sofa (or Jellyfin, Emby, Plex)

class LocalSofa:
    """"This box": Sofa itself, running on the box (Live TV, and videos on the box and its USB drives) for
    anyone without a Sofa computer. Started the first time someone picks it; light settings for a Pi."""
    PORT = int(os.environ.get("SOFA_BOX_LOCAL_PORT", "8095"))

    def __init__(self):
        self.proc, self.lock = None, threading.Lock()
        self.data = os.environ.get("SOFA_BOX_LOCAL_DATA") or os.path.expanduser("~/.local/share/sofa-box/sofa")

    def code(self):
        for d in (os.environ.get("SOFA_BOX_SOFA"), os.path.join(HERE, "sofa-server"), os.path.join(HERE, "..", "..")):
            if d and os.path.isfile(os.path.join(d, "sofa.py")) and os.path.isdir(os.path.join(d, "sofa")):
                return os.path.realpath(d)
        return None

    def available(self):
        return bool(self.code())

    def url(self):
        return "http://127.0.0.1:%d" % self.PORT

    def answering(self):
        return bool(info(self.url()))

    def _config(self):
        cfg = os.path.join(self.data, "config.json")
        if os.path.exists(cfg):
            return
        os.makedirs(self.data, exist_ok=True)
        lib = os.path.expanduser("~/Videos/Sofa Library")
        user = os.path.basename(os.path.expanduser("~"))
        folders = {"shows": "Shows", "movies": "Movies", "music": "Music", "musicvideos": "Music Videos", "inbox": "Inbox",
                   "review": "Needs Review", "adult": "Adult", "originals": "Converted Originals"}
        conf = {k: os.path.join(lib, v) for k, v in folders.items()}
        conf.update(name=(settings().get("boot_text") or "Sofa Box"), port=self.PORT, dlna=False, guest_access=False,
                    drive_folders=["/media/" + user, "/media"], auto_convert=False, previews=False, trickplay=False,
                    detect_intros=False, machine_test=False,
                    live_playlists=[{"name": "English", "url": "https://iptv-org.github.io/iptv/languages/eng.m3u"},
                                    {"name": "Spanish-language", "url": "https://iptv-org.github.io/iptv/languages/spa.m3u"}])
        for v in conf.values():
            if isinstance(v, str) and v.startswith(lib):
                os.makedirs(v, exist_ok=True)
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump(conf, f, indent=1)

    def ensure(self, wait=40):
        """Running (started now if it wasn't). True when it answers."""
        if self.answering():
            return True
        code = self.code()
        if not code:
            return False
        with self.lock:
            if not (self.proc and self.proc.poll() is None):
                self._config()
                log = open(os.path.join(self.data, "sofa.log"), "ab")
                self.proc = subprocess.Popen([sys.executable, os.path.join(code, "sofa.py"), "serve"], cwd=code, stdin=subprocess.DEVNULL,
                                             stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, SOFA_DATA=self.data))
        end = time.time() + wait
        while time.time() < end:
            if self.answering():
                return True
            if self.proc and self.proc.poll() is not None:
                return False
            time.sleep(0.5)
        return False

    def _post(self, path, body, cookie=""):
        req = urllib.request.Request(self.url() + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Sofa": "1", "Cookie": cookie})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as r:
                return r.status, r.headers.get("Set-Cookie") or ""
        except urllib.error.HTTPError as e:
            return e.code, ""

    def sign_in(self):
        """The box's own account on its own Sofa: made the first time (nobody has to set anything up), and a
        fresh sign-in for the browser when it needs one. Returns the session cookie's value, or None."""
        path = os.path.join(CONF_DIR, "this-box.json")
        try:
            with open(path, encoding="utf-8") as f:
                acct = json.load(f)
        except (OSError, ValueError):
            acct = None
        if not acct:
            acct = {"name": re.sub(r"[^\w '.-]", "", settings().get("boot_text") or "") or "Sofa Box", "password": os.urandom(18).hex()}
            code, _ = self._post("/api/setup", acct)
            if code != 200:
                return None                              # set up by someone already: they sign in themselves
            os.makedirs(CONF_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(acct, f)
            os.chmod(path, 0o600)
        code, cookie = self._post("/api/login", acct)
        m = re.search(r"sofa_session=([^;]+)", cookie)
        return m.group(1) if code == 200 and m else None


local_sofa = LocalSofa()
servers = boxservers.Servers(CONF_DIR, local_available=local_sofa.available)
others_found = {"at": 0, "list": []}


def migrate_server():
    """The first Sofa boxes had one Sofa (settings' "server"): it becomes the first on the list, and the
    one Sofa opens with, as before."""
    st = servers.state()
    old = settings()["server"]
    if old and not any(x["kind"] == "sofa" and x["where"] != "box" for x in st["servers"]):
        j = info(old) or {}
        entry = servers.add({"id": boxservers.server_id("sofa", old), "kind": "sofa", "name": j.get("name") or "Sofa",
                             "url": old.rstrip("/"), "where": "home", "sofa_id": j.get("id")})
        servers.choose(entry["id"], remember=True)


def sofa_listing():
    """Everything the box's Sofa chooser shows."""
    st = servers.state()
    added = {x["url"].rstrip("/") for x in st["servers"]}
    added_ids = {x.get("sofa_id") for x in st["servers"] if x.get("sofa_id")}
    with _lock:
        home = [{"url": u, "name": v["name"], "kind": "sofa", "where": "home", "id": boxservers.server_id("sofa", u)}
                for u, v in sorted(found.items()) if u.rstrip("/") not in added and v.get("id") not in added_ids]
    others = [o for o in others_found["list"] if o["url"].rstrip("/") not in added]
    feat = [f for f in boxservers.featured(CONF_DIR) if f["url"].rstrip("/") not in added]
    return dict(st, found=home, others=others, featured=feat, local=local_sofa.available())


def server_page(entry, start=False, hash_=""):
    """Where an app tab for this server opens."""
    if entry["kind"] != "sofa":
        return entry["url"] + (entry.get("start") or "")
    path = (entry.get("start") or "/") if start else "/"
    return "http://%s.localhost:%d%s?tv=1%s" % (entry["id"], PORT, path, hash_ or "")


def open_sofa(sid=None, hash_=""):
    """Open Sofa from the server picked (or the one it opens with). {"ask": True} when the box should ask."""
    st = servers.state()
    sid = sid or (None if st["ask"] else st["default"])
    if not sid:
        return {"ok": True, "ask": True}
    entry = servers.get(sid)
    if not entry:
        return {"ok": True, "ask": True}
    if entry["where"] == "box":
        if not local_sofa.ensure():
            raise ValueError("Sofa on this box didn't start. Try again, or restart the box.")
        if browser and browser.connected() and "sofa_session=" not in browser.cookies("box.localhost"):
            token = local_sofa.sign_in()                 # straight in: the box's own account
            if token:
                browser.set_cookie("box.localhost", "sofa_session", token)
    url = server_page(entry, start=True, hash_=hash_)
    app = "sofa" if entry["kind"] == "sofa" else "srv-" + entry["id"]
    if browser and browser.connected():
        existing = browser.tab_of(app)
        if existing and app == "sofa":
            here = urllib.parse.urlsplit((browser.tabs.get(existing) or {}).get("url") or "").netloc
            if here.split(":")[0] != "%s.localhost" % entry["id"]:      # another server's Sofa: this one instead
                browser.navigate(existing, url)
            elif hash_:
                browser.evaluate(existing, "location.hash = %s" % json.dumps(hash_))
            browser.activate(existing)
            return {"ok": True, "target": existing, "server": entry["id"]}
        return {"ok": True, "target": browser.open(app, url), "server": entry["id"]}
    return {"ok": True, "url": url, "server": entry["id"]}


_continue = {"at": 0, "key": None, "value": None}


def sofa_continue():
    """What you were watching in the Sofa the box opens with, for Home (asked with that Sofa's own sign-in
    on the box, read from the browser)."""
    st = servers.state()
    entry = servers.get(st["default"]) if st["default"] and not st["ask"] else None
    if not entry or entry["kind"] != "sofa":
        return {"found": False, "servers": len(st["servers"])}
    if _continue["key"] == entry["id"] and time.time() - _continue["at"] < 20:
        return _continue["value"]
    host = "%s.localhost" % entry["id"]
    cookie = browser.cookies(host) if browser and browser.connected() else ""
    out = {"found": True, "name": entry["name"], "server": entry["id"], "where": entry["where"], "signedIn": False,
           "base": "http://%s:%d" % (host, PORT)}

    def get(path):
        req = urllib.request.Request(entry["url"] + path, headers={"Cookie": cookie, "Accept": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if entry["url"].startswith("http://") else urllib.request.build_opener()
        with opener.open(req, timeout=6) as r:
            return json.loads(r.read().decode("utf-8"))
    try:
        if entry["where"] == "box" and not local_sofa.answering():
            return dict(out, found=True, sleeping=True)
        s = get("/api/session")
        out["name"] = s.get("name") or entry["name"]
        if s.get("user"):
            lib, prog = get("/api/library"), get("/api/progress")
            by = {}
            for sh in lib.get("shows") or []:
                for se in sh.get("seasons") or []:
                    for ep in se.get("episodes") or []:
                        by[ep["id"]] = {"title": sh["name"], "sub": "S%s E%s · %s" % (ep.get("s"), ep.get("e"), ep.get("title") or ""),
                                        "art": ep.get("thumb") or sh.get("backdrop") or sh.get("poster"),
                                        "backdrop": sh.get("backdrop") or ep.get("thumb"), "hash": "#/show/" + urllib.parse.quote(sh["id"], safe="")}
            for m in lib.get("movies") or []:
                by[m["id"]] = {"title": m["title"], "sub": str(m.get("year") or ""), "art": m.get("backdrop") or m.get("poster"),
                               "backdrop": m.get("backdrop") or m.get("poster"), "hash": "#/movie/" + urllib.parse.quote(m["id"], safe="")}
            items = [dict(by[i], id=i, pct=round(100 * p["t"] / p["d"])) for i, p in
                     sorted(prog.items(), key=lambda x: -(x[1].get("at") or 0))
                     if i in by and not p.get("done") and p.get("d") and 30 < p["t"] < p["d"] - 30][:12]
            out.update(signedIn=True, user=s["user"]["name"], items=items)
    except Exception:
        out["found"] = False
    _continue.update(at=time.time(), key=entry["id"], value=out)
    return out


def scan_others():
    if time.time() - others_found["at"] > 20:
        others_found["at"] = time.time()
        try:
            others_found["list"] = boxservers.find_others()
        except OSError:
            pass
    return others_found["list"]


# ---------------------------------------------------------------- USB drives and discs

devices_seen = {"drives": [], "disc": None, "n": 0}


def watch_devices():
    """USB drives are mounted as they're plugged in (udisks), and a disc in a USB DVD drive shows on Home."""
    known = set()
    while True:
        try:
            dev = boxos.devices(mount=True)
            names = {d["dev"] for d in dev["drives"]} | ({dev["disc"]["dev"] + ":" + dev["disc"]["kind"]} if dev["disc"] else set())
            new = names - known
            if known and new:
                for d in dev["drives"]:
                    if d["dev"] in new:
                        toast("USB drive %s is ready: it's in Files." % d["label"])
                if dev["disc"] and (dev["disc"]["dev"] + ":" + dev["disc"]["kind"]) in new:
                    toast("A %s is in: open it from Home." % boxos.DISC_NAMES.get(dev["disc"]["kind"], "disc"))
            if names != known:
                devices_seen.update(dev, n=devices_seen["n"] + 1)
            known = names
        except Exception:
            pass
        time.sleep(3)


# ---------------------------------------------------------------- Bluetooth, Wi-Fi and the phone remote (setting the box up)

class Bluetooth:
    """Looks for Bluetooth devices while the setup or Settings page asks it to, and during the first start
    pairs any remote, controller, keyboard or mouse that's in pairing mode by itself (with nothing to press
    "Pair" with yet, a Fire TV remote held on Home is all it takes)."""

    def __init__(self):
        self.until = self.autopair_until = 0
        self.devices, self.state = [], {}               # mac -> "pairing" | "paired" | "failed"
        self.lock, self.thread = threading.Lock(), None

    def want(self, seconds=30, autopair=False):
        now = time.time()
        self.until = max(self.until, now + seconds)
        if autopair:
            self.autopair_until = max(self.autopair_until, now + seconds)
        with self.lock:
            if not (self.thread and self.thread.is_alive()):
                self.thread = threading.Thread(target=self._loop, daemon=True, name="bluetooth")
                self.thread.start()

    def _loop(self):
        run(["bluetoothctl", "power", "on"], 10)
        scan = None
        while time.time() < self.until:
            if not scan or scan.poll() is not None:     # discovery lasts as long as this asks for it
                try:
                    scan = subprocess.Popen(["bluetoothctl", "--timeout", "30", "scan", "on"], stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL)
                except OSError:
                    return
            self.devices = boxos.bt_devices()
            if time.time() < self.autopair_until:
                for d in self.devices:
                    if d["kind"] in ("remote", "controller", "keyboard", "mouse") and not d["paired"] and d["mac"] not in self.state:
                        self.pair(d["mac"])
            time.sleep(2)
        if scan and scan.poll() is None:
            scan.terminate()

    def pair(self, mac):
        self.state[mac] = "pairing"

        def go():
            ok, _ = boxos.bt_pair(mac)
            self.state[mac] = "paired" if ok else "failed"
            name = next((d["name"] for d in self.devices if d["mac"] == mac), "It")
            toast("%s is paired." % name if ok else "%s didn't pair. Put it in pairing mode and try again." % name)
            self.devices = boxos.bt_devices()
        threading.Thread(target=go, daemon=True).start()

    def listing(self):
        shown = [dict(d, state=self.state.get(d["mac"])) for d in self.devices if d["kind"] != "other" or d["paired"]]
        return {"scanning": time.time() < self.until, "autopair": time.time() < self.autopair_until,
                "devices": sorted(shown, key=lambda d: (not d["paired"], not d["connected"], -(d["rssi"] or -999)))}


class Network:
    """The box's network: a cable, Wi-Fi, or with neither (a new box), a Wi-Fi hotspot of its own, so a phone
    can join it, work the box and give it the home Wi-Fi."""
    CON = "sofa-box-setup"

    def __init__(self):
        self.hotspot, self.cached, self.lock = None, [], threading.Lock()

    @staticmethod
    def wifi_device():
        code, out = run(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"], 10)
        return next((line.split(":")[0] for line in out.splitlines() if code == 0 and line.endswith(":wifi")), None)

    @staticmethod
    def wired():
        try:
            for d in os.listdir("/sys/class/net"):
                if d.startswith(("eth", "en")):
                    with open("/sys/class/net/%s/operstate" % d) as f:
                        if f.read().strip() == "up":
                            return True
        except OSError:
            pass
        return False

    def scan(self):
        code, out = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list", "--rescan", "yes"], 25)
        if code != 0:
            return {"ok": False, "networks": self.cached, "message": "Wi-Fi from here needs NetworkManager (Raspberry Pi OS has it)."
                    if "No such file" in out or "not found" in out else out[-200:]}
        nets = {}
        for line in out.splitlines():
            parts = re.split(r"(?<!\\):", line)
            if len(parts) >= 3 and parts[0] and parts[0] != self.hotspot_ssid():
                ssid = parts[0].replace("\\:", ":")
                if ssid not in nets or int(parts[1] or 0) > nets[ssid]["signal"]:
                    nets[ssid] = {"ssid": ssid, "signal": int(parts[1] or 0), "secure": bool(parts[2]), "on": len(parts) > 3 and parts[3] == "*"}
        if nets:
            self.cached = sorted(nets.values(), key=lambda n: -n["signal"])
        return {"ok": True, "networks": self.cached}

    def hotspot_ssid(self):
        return self.hotspot and self.hotspot["ssid"]

    def start_hotspot(self):
        dev = self.wifi_device()
        if not dev or self.hotspot:
            return self.hotspot
        if not self.cached:
            self.scan()                                      # while it still can: a hotspot can't look around
        tail = (re.sub(r"[^0-9]", "", local_mac(dev)) or str(os.getpid()))[-4:]
        ssid, password = "Sofa Box " + tail, "%08d" % (int.from_bytes(os.urandom(4), "big") % 10 ** 8)
        code, out = run(["nmcli", "device", "wifi", "hotspot", "ifname", dev, "con-name", self.CON, "ssid", ssid, "password", password], 30)
        if code == 0:
            self.hotspot = {"ssid": ssid, "password": password, "address": "10.42.0.1",
                            "wifi_qr": "WIFI:T:WPA;S:%s;P:%s;;" % (ssid.replace(";", r"\;"), password)}
            toast("No internet yet: the box made its own Wi-Fi, %s, for your phone." % ssid)
        return self.hotspot

    def stop_hotspot(self):
        if self.hotspot:
            run(["nmcli", "connection", "down", self.CON], 20)
            run(["nmcli", "connection", "delete", self.CON], 20)
            self.hotspot = None

    def join(self, ssid, password):
        had = bool(self.hotspot)
        self.stop_hotspot()
        code, out = run(["nmcli", "device", "wifi", "connect", str(ssid)] + (["password", str(password)] if password else []), 45)
        if code != 0 and had:
            self.start_hotspot()                             # back to the box's own, to try again
        return {"ok": code == 0, "message": "Connected to %s." % ssid if code == 0 else
                ("The password isn't right." if re.search(r"secrets|password|802-11-wireless-security", out, re.I) else out[-200:])}

    def watch(self):
        """No cable, no Wi-Fi a minute after starting: the hotspot. A network again: the hotspot goes."""
        # a new box (at its setup, perhaps with nothing but a phone): its own Wi-Fi soon; later on, a slow router gets time
        time.sleep(int(os.environ.get("SOFA_BOX_HOTSPOT_AFTER") or (15 if not settings()["welcomed"] else 50)))
        while True:
            try:
                online = bool(local_address()) and local_address() != "10.42.0.1"
                if not online and not self.hotspot and not settings().get("no_hotspot"):
                    self.start_hotspot()
                elif online and self.hotspot and self.wired():
                    self.stop_hotspot()
            except Exception:
                pass
            time.sleep(20)


def local_mac(dev):
    try:
        with open("/sys/class/net/%s/address" % dev) as f:
            return f.read().strip()
    except OSError:
        return ""


class PhoneRemote:
    """The phone remote: a page on the home network (http://<box>:8092) that works the box like its remote,
    a keyboard and a touchpad. A phone gets in with the code on the TV (in the QR code there), and keeps a
    sign-in of its own."""
    PORT = int(os.environ.get("SOFA_BOX_REMOTE_PORT", "8092"))
    KEYS = {"up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT", "ok": "KEY_ENTER", "back": "KEY_ESC",
            "menu": "KEY_F2", "play": "KEY_PLAYPAUSE", "rewind": "KEY_REWIND", "forward": "KEY_FASTFORWARD",
            "enter": "KEY_ENTER", "backspace": "KEY_BACKSPACE", "tab": "KEY_TAB"}
    DOM = {"KEY_UP": ("ArrowUp", 38), "KEY_DOWN": ("ArrowDown", 40), "KEY_LEFT": ("ArrowLeft", 37), "KEY_RIGHT": ("ArrowRight", 39),
           "KEY_ENTER": ("Enter", 13), "KEY_ESC": ("Escape", 27), "KEY_F2": ("F2", 113), "KEY_BACKSPACE": ("Backspace", 8),
           "KEY_TAB": ("Tab", 9), "KEY_PLAYPAUSE": ("MediaPlayPause", 179), "KEY_REWIND": ("MediaRewind", 0),
           "KEY_FASTFORWARD": ("MediaFastForward", 0)}

    def __init__(self):
        self.path = os.path.join(CONF_DIR, "phones.json")
        self.code, self.kb, self.mouse, self.tried = self._new_code(), None, None, False

    @staticmethod
    def _new_code():
        return "%04d" % (int.from_bytes(os.urandom(2), "big") % 10000)

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def url(self):
        ip = (network.hotspot or {}).get("address") or local_address()
        return "http://%s:%d" % (ip, self.PORT) if ip else None

    def status(self):
        u = self.url()
        return {"url": u, "pair_url": u + "/r/" + self.code if u else None, "code": self.code, "phones": len(self._load()),
                "hotspot": network.hotspot, "wired": network.wired()}

    def pair(self, code, name):
        if not code or str(code) != self.code:
            return None
        token = os.urandom(24).hex()
        phones = self._load()
        phones[token] = {"name": str(name or "Phone")[:40], "at": int(time.time())}
        os.makedirs(CONF_DIR, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(phones, f)
        os.chmod(self.path, 0o600)
        self.code = self._new_code()                       # each code works once
        toast("%s is a remote now." % phones[token]["name"])
        return token

    def valid(self, token):
        return bool(token) and token in self._load()

    def forget_all(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def _devices(self):
        if self.tried:
            return self.kb
        self.tried = True
        if os.environ.get("SOFA_BOX_UINPUT") == "0":
            return None
        try:
            from evdev import UInput, ecodes
            self.kb = UInput({ecodes.EV_KEY: [ecodes.ecodes[k] for k in set(self.KEYS.values())]}, name="Sofa box phone remote")
            self.mouse = UInput({ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT],
                                 ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL]}, name="Sofa box phone touchpad")
            self.ecodes = ecodes
        except Exception:                                  # no evdev or no /dev/uinput (a preview): through the browser
            self.kb = self.mouse = None
        return self.kb

    def key(self, name):
        if name == "home":
            player.stop(save=True, reason="back")
            return go_home()
        if player.proc and player.proc.poll() is None:     # a video in the box's player: the remote works it
            act = {"ok": player.ok, "back": lambda: player.stop(save=True, reason="back"), "play": lambda: player.control({"cmd": "toggle"}),
                   "left": lambda: player.control({"cmd": "skip", "by": -10}), "rewind": lambda: player.control({"cmd": "skip", "by": -10}),
                   "right": lambda: player.control({"cmd": "skip", "by": 30}), "forward": lambda: player.control({"cmd": "skip", "by": 30})}.get(name)
            if act:
                return act()
        code = self.KEYS.get(name)
        if not code:
            raise ValueError("Which key?")
        kb = self._devices()
        if kb:
            c = self.ecodes.ecodes[code]
            kb.write(self.ecodes.EV_KEY, c, 1)
            kb.write(self.ecodes.EV_KEY, c, 0)
            kb.syn()
        elif browser and browser.connected():
            browser.press(*self.DOM[code])

    def text(self, t):
        if browser and browser.connected():
            browser.insert_text(str(t)[:500])

    def pointer(self, dx=0, dy=0, click=None, scroll=0):
        if not self._devices() or not self.mouse:
            return
        e = self.ecodes
        if dx or dy:
            self.mouse.write(e.EV_REL, e.REL_X, int(max(-200, min(200, dx))))
            self.mouse.write(e.EV_REL, e.REL_Y, int(max(-200, min(200, dy))))
        if scroll:
            self.mouse.write(e.EV_REL, e.REL_WHEEL, int(max(-10, min(10, scroll))))
        if click in ("left", "right"):
            b = e.BTN_LEFT if click == "left" else e.BTN_RIGHT
            self.mouse.write(e.EV_KEY, b, 1)
            self.mouse.syn()
            self.mouse.write(e.EV_KEY, b, 0)
        self.mouse.syn()

    @staticmethod
    def volume(by):
        env = dict(os.environ, XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid())
        args = ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"] if by == "mute" else \
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "%+d%%" % max(-20, min(20, int(by or 0)))]
        try:
            subprocess.run(args, env=env, capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass


def timezones():
    code, out = run(["timedatectl", "list-timezones"], 10)
    return [z for z in out.splitlines() if "/" in z] if code == 0 else []


def current_timezone():
    try:
        return os.path.realpath("/etc/localtime").split("zoneinfo/", 1)[1]
    except (IndexError, OSError):
        return "UTC"


def set_timezone(tz, only_if_unset=False):
    """The box's time zone (the clock on Home). From a phone: only while the box hasn't been given one."""
    if not re.match(r"^[A-Za-z]+(/[A-Za-z0-9_+-]+){1,2}$", tz or "") or (only_if_unset and settings().get("tz_set")):
        return False
    code, _ = run(["sudo", "-n", os.path.join(HERE, "sofa-box"), "timezone", tz], 20)
    if code == 0:
        save_settings(tz_set=True)
    return code == 0


bluetooth = Bluetooth()
network = Network()
phone = None                                              # PhoneRemote, made in main() (it reads the box's settings)


def setup_state():
    """Everything the first-start steps and Settings show about remotes, Wi-Fi and Bluetooth."""
    s = settings()
    code, ssid = run(["iwgetid", "-r"], 5)
    ssid = ssid if code == 0 else ""
    return {"remote": phone.status() if phone else None, "bluetooth": bluetooth.listing(),
            "network": {"wired": network.wired(), "wifi": ssid or None, "address": local_address(), "hotspot": network.hotspot,
                        "networks": network.cached}, "welcomed": s["welcomed"], "name": s["boot_text"], "theme": s["theme"],
            "timezone": current_timezone(), "tz_set": bool(s.get("tz_set"))}


def shlex_split(text):
    import shlex
    return shlex.split(text) if text else []


def rewrite(url, base=None):
    """The page builds addresses on this agent (127.0.0.1:8091, or <server>.localhost:8091); mpv goes to the
    server itself."""
    base = base or server() or ""
    m = re.match(r"^https?://(127\.0\.0\.1|localhost|[a-z0-9-]+\.localhost):%d(/.*)?$" % PORT, url)
    if m:
        return base + (m.group(2) or "/")
    return url if url.startswith("http") else base + url


def save_progress(item, t, d, done, cookie, base=None):
    base = base or server()
    if not item or not base:
        return
    try:
        req = urllib.request.Request(base + "/api/progress/" + urllib.parse.quote(item, safe=""), method="POST",
                                     data=json.dumps({"t": t, "d": d, "done": done}).encode(),
                                     headers={"Content-Type": "application/json", "X-Sofa": "1", "Cookie": cookie})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if base.startswith("http://") else urllib.request.build_opener()
        opener.open(req, timeout=8).close()
    except Exception:
        pass


# ---------------------------------------------------------------- the box itself (settings from the TV)

def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def box_info():
    s = settings()
    temp = None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp = round(int(f.read()) / 1000)
    except (OSError, ValueError):
        pass
    code, ssid = run(["iwgetid", "-r"], 5)
    ssid = ssid if code == 0 else ""
    _, paired = run(["bluetoothctl", "devices", "Paired"], 5)
    controllers = [line.split(" ", 2)[2] for line in paired.splitlines() if line.startswith("Device ") and len(line.split(" ", 2)) == 3]
    try:
        with open("/proc/meminfo") as f:
            mem = int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1)) * 1024
    except (OSError, AttributeError):
        mem = None
    return {"version": VERSION, "model": model() or "this computer", "memory": mem, "temperature": temp,
            "wifi": ssid or None, "address": local_address(), "server": server(), "server_name": (found.get(server()) or {}).get("name"),
            "settings": {k: s[k] for k in ("quality", "hwdec", "audio", "theme", "boot_text")},
            "choices": CHOICES, "learned_720": s["learned_720"],
            "max_height": max_height(), "slow_board": slow_board(), "controllers": controllers}


def local_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def box_action(a, data):
    if a == "pair-controller":
        threading.Thread(target=lambda: run([os.path.join(HERE, "sofa-box"), "pair-controller"], 60), daemon=True).start()
        return {"ok": True, "message": "Put the controller in pairing mode now (Xbox: hold the pair button until it flashes fast)."}
    if a == "wifi-scan":
        return network.hotspot and {"ok": True, "networks": network.cached} or network.scan()
    if a == "wifi-connect":
        return network.join(data.get("ssid", ""), data.get("password"))
    if a == "tv-on":
        code, out = run([os.path.join(HERE, "sofa-box"), "tv-on"], 15)
        return {"ok": code == 0, "message": out[-200:]}
    if a == "restart":
        threading.Timer(1.0, lambda: run(["sudo", "-n", "systemctl", "restart", "sofa-box", "sofa-box-agent"], 30)).start()
        return {"ok": True}
    if a == "reboot":
        threading.Timer(1.0, lambda: run(["sudo", "-n", "systemctl", "reboot"], 30)).start()
        return {"ok": True}
    if a == "choose":
        with _lock:
            state["chosen"] = None
            found.clear()
        save_settings(server=None)
        return {"ok": True, "go": "/box/finder"}
    if a == "factory-reset":                       # back to how it came: for the next owner, or a fresh start
        threading.Timer(1.0, lambda: run(["sudo", "-n", os.path.join(HERE, "sofa-box"), "factory-reset"], 120)).start()
        return {"ok": True, "message": "Resetting. The box starts again as new in a minute."}
    if a == "update":                              # the newest Sofa Box from GitHub (takes a few minutes)
        threading.Thread(target=lambda: run(["sudo", "-n", os.path.join(HERE, "sofa-box"), "update"], 1800), daemon=True).start()
        return {"ok": True, "message": "Updating from GitHub. The box restarts by itself when it's done (a few minutes)."}
    if a == "forget-720":
        save_settings(learned_720=False)
        return {"ok": True}
    if a == "apply-boot":                          # the boot screen in the box's theme and name (takes a minute)
        threading.Thread(target=lambda: run(["sudo", "-n", os.path.join(HERE, "sofa-box"), "apply-boot", SETTINGS], 300),
                         daemon=True).start()
        return {"ok": True, "message": "The new boot screen shows from the next start."}
    return {"ok": False, "message": "Unknown action."}


def box_state():
    """What's on, for the start page and the preview."""
    p = player.status
    with _lock:
        return {"chosen": server(), "name": (found.get(server()) or {}).get("name"),
                "found": [{"url": u, "name": v["name"]} for u, v in sorted(found.items())],
                "playing": dict(p) if p else None, "address": local_address(), "version": VERSION}


_modules = {}


def module(name):
    """The boot screen's drawing (sofa-box-art.py), loaded once, when a preview asks for it."""
    if name not in _modules:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(HERE, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _modules[name] = mod
    return _modules[name]


# ---------------------------------------------------------------- the web side

NATIVE_JS = r"""/* Sofa box: the TV pages get the box's own player (mpv), like Sofa's Fire TV app. */
(function () {
  window.SofaBox = { version: "%(version)s", slow: %(slow)s };
  var html = document.documentElement, onTop = false;
  if (window.SofaBox.slow) {             // a Pi 3: lighter effects, and the banner stays still unless asked
    html.classList.add("box-lite");
    try { if (localStorage.getItem("sofa.bannerClips") === null) localStorage.setItem("sofa.bannerClips", "false"); } catch (e) {}
  }
  // While mpv plays on top, the page behind it acts hidden: no banner clips or trailers using the Pi's power.
  var realHidden = Object.getOwnPropertyDescriptor(Document.prototype, "hidden");
  Object.defineProperty(document, "hidden", { configurable: true, get: function () { return onTop || realHidden.get.call(document); } });
  Object.defineProperty(document, "visibilityState", { configurable: true, get: function () { return document.hidden ? "hidden" : "visible"; } });
  function cover(on) {
    onTop = on;
    html.classList.toggle("native-playing", on);
    if (on) document.querySelectorAll("video, audio").forEach(function (v) { if (!v.paused) v.pause(); });
    document.dispatchEvent(new Event("visibilitychange"));
  }
  function call(m, body) {
    var x = new XMLHttpRequest();
    x.open(body === undefined ? "GET" : "POST", "/box/native/" + m, false);
    if (body !== undefined) x.setRequestHeader("X-Sofa-Box", "1");
    x.send(body === undefined ? null : body);
    return x.responseText;
  }
  function post(path, body) {
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Sofa-Box": "1" }, body: JSON.stringify(body || {}) });
  }
  window.SofaNative = {
    version: function () { return "1"; }, appVersion: function () { return "0"; },
    caps: function () { return call("caps"); }, status: function () { return call("status"); },
    play: function (json) { cover(true); call("play", json); }, control: function (json) { call("control", json); },
    servers: function () { return call("servers"); },
    choose: function (id) { post("/box/api/sofa/open", { id: id }); },
    forget: function () { post("/box/api/sofa/chooser"); }
  };
  var since = null;
  (function events() {
    fetch("/box/native/events" + (since === null ? "" : "?since=" + since)).then(function (r) { return r.json(); }).then(function (e) {
      since = e.n;
      (e.news || []).forEach(function (n) {
        if (n.done) { cover(false); if (window.sofaNativeDone) window.sofaNativeDone(n.done); }
        if (n.toast && window.SofaToast) window.SofaToast(n.toast);
        if (n.go) location.hash = n.go;
      });
      events();
    }).catch(function () { setTimeout(events, 2000); });
  })();
})();
"""


def native_js():
    return NATIVE_JS % {"version": VERSION, "slow": "true" if slow_board() else "false"}


def finder_page():
    with open(os.path.join(HERE, "finder.html"), encoding="utf-8") as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def send(self, body, ctype="application/json", status=200, headers=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        self.route()

    def do_HEAD(self):
        self.route()

    def do_POST(self):
        self.route()

    def do_DELETE(self):
        self.route()

    def home_host(self):
        """The box's own pages (the home screen, at 127.0.0.1:8091)."""
        host = (self.headers.get("Host") or "").lower()
        return host in ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT, "127.0.0.1", "localhost")

    # What a server's pages (<id>.localhost) may ask of the box: its player, and Sofa's server menu.
    SERVER_PAGE_OK = ("/box/native.js", "/box/native/", "/box/api/sofa/open", "/box/api/sofa/chooser", "/box/api/home", "/box/api/go")

    def route(self):
        path = urllib.parse.urlsplit(self.path).path
        entry = boxservers.by_host(self.headers.get("Host"), servers)
        if not entry and not self.home_host():          # an address that isn't the box's (a rebinding trick)
            return self.send('{"error":"not here"}', status=403)
        if path.startswith("/box/"):
            if entry and not path.startswith(self.SERVER_PAGE_OK):
                return self.send('{"error":"not for this page"}', status=403)
            if self.command == "POST" and self.headers.get("X-Sofa-Box") != "1":
                return self.send('{"error":"missing X-Sofa-Box"}', status=400)  # no other site can post here
            return self.box(path, urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query), entry)
        if entry:
            return self.proxy(entry)
        if not server() or "choose=1" in self.path:
            if "choose=1" in self.path:
                with _lock:
                    state["chosen"] = None
            return self.send("", status=302, headers={"Location": "/box/finder"})
        return self.proxy()

    # ---- the agent's own pages and calls
    def box(self, path, qs, entry=None):
        if path == "/box/finder":
            return self.send(finder_page(), "text/html; charset=utf-8")
        if path == "/box/state":
            return self.send(json.dumps(box_state()))
        if path == "/box/choose":
            typed = self.body().decode("utf-8", "replace").strip().rstrip("/")
            if typed and not typed.startswith(("http://", "https://")):
                typed = "http://" + typed
            tries = [typed] if re.search(r":\d+$", typed) else [typed + ":8090", typed]
            url = next((t for t in tries if typed and info(t)), None)
            if url:
                add(url)
                with _lock:
                    state["chosen"] = url
                save_settings(server=url)
            return self.send(json.dumps({"url": url}))
        if path == "/box/native.js":
            return self.send(native_js(), "text/javascript; charset=utf-8")
        if path == "/box/native/caps":
            return self.send(json.dumps(caps()))
        if path == "/box/native/status":
            st = dict(player.status) if player.proc else {}
            return self.send(json.dumps({k: st[k] for k in ("item", "t", "d", "paused") if k in st}))
        if path == "/box/native/play":
            payload = json.loads(self.body() or b"{}")
            payload.pop("mpv", None)                          # only the box's own disc player sets mpv's options
            player.play(payload, self.headers.get("Cookie", ""), entry["url"] if entry else server())
            return self.send('{"ok":true}')
        if path == "/box/native/servers":                     # Sofa's menu on the box: the servers to switch to
            st = servers.state()
            return self.send(json.dumps([{"id": x["id"], "name": x["name"], "kind": x["kind"], "where": x["where"],
                                          "current": bool(entry and entry["id"] == x["id"])} for x in st["servers"]]))
        if path == "/box/native/control":
            player.control(json.loads(self.body() or b"{}"))
            return self.send('{"ok":true}')
        if path == "/box/native/key":                     # mpv's own keys (OK, Back) come here
            k = (qs.get("k") or [""])[0]
            if k == "ok":
                player.ok()
            elif k == "back":
                player.stop(save=True, reason="back")
            elif k == "home":                              # Home while a video plays: stop it (place saved), go home
                player.stop(save=True, reason="back")
                go_home()
            return self.send('{"ok":true}')
        if path == "/box/native/events":
            since = (qs.get("since") or [None])[0]
            return self.send(json.dumps(player.events(int(since) if since and since.isdigit() else None)))
        if path == "/box/api/info":
            return self.send(json.dumps(box_info()))
        if path == "/box/api/settings":
            data = json.loads(self.body() or b"{}") if self.command == "POST" else {}
            changes = {k: v for k, v in data.items() if k in CHOICES and v in CHOICES[k]}
            if "welcomed" in data:                              # the first-start steps are done
                changes["welcomed"] = bool(data["welcomed"])
            if "boot_text" in data:
                changes["boot_text"] = re.sub(r"[^\w '’&.-]", "", str(data["boot_text"]))[:30].strip()
            if changes:
                save_settings(**changes)
            return self.send(json.dumps(dict(box_info(), ok=True)))
        if path == "/box/api/go":
            go(str(json.loads(self.body() or b"{}").get("to") or "#/"))
            return self.send('{"ok":true}')
        if path == "/box/splash.png":
            buf = __import__("io").BytesIO()
            module("sofa-box-art").render(settings(), (960, 540), float((qs.get("phase") or ["0.4"])[0])).save(buf, "PNG")
            return self.send(buf.getvalue(), "image/png")
        if path.startswith("/box/api/action/"):
            return self.send(json.dumps(box_action(path.rsplit("/", 1)[1], json.loads(self.body() or b"{}"))))
        if path == "/box/preview":
            with open(os.path.join(HERE, "preview.html"), encoding="utf-8") as f:
                return self.send(f.read(), "text/html; charset=utf-8")
        if path.startswith(("/box/api/", "/box/home", "/box/icons/", "/box/store-icons/", "/box/games/", "/box/fonts/")) or path == "/box/files/raw":
            try:
                return self.box_os(path, qs)
            except ValueError as exc:
                return self.send(json.dumps({"error": str(exc)}), status=400)
            except OSError as exc:
                return self.send(json.dumps({"error": "That didn't work: %s" % str(exc)[:160]}), status=500)
        return self.send('{"error":"not found"}', status=404)

    # ---- Sofa Box OS: the home screen, apps, the store, files, games
    def static(self, base, rel):
        full = os.path.realpath(os.path.join(base, rel))
        if os.path.isdir(full):                             # a folder: its page
            full = os.path.join(full, "index.html")
        if not full.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(full):
            return self.send('{"error":"not found"}', status=404)
        types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".svg": "image/svg+xml", ".webp": "image/webp", ".ico": "image/x-icon", ".gif": "image/gif",
                 ".woff2": "font/woff2", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav"}
        with open(full, "rb") as f:
            return self.send(f.read(), types.get(os.path.splitext(full)[1].lower(), "application/octet-stream"),
                             headers={"Cache-Control": "no-cache"})

    def box_os(self, path, qs):
        data = json.loads(self.body() or b"{}") if self.command == "POST" else {}
        arg = lambda k, d="": (qs.get(k) or [d])[0]   # noqa: E731
        if path in ("/box/home", "/box/home/"):
            return self.static(os.path.join(HERE, "home"), "index.html")
        if path.startswith("/box/home/"):
            return self.static(os.path.join(HERE, "home"), path[len("/box/home/"):])
        if path.startswith("/box/icons/"):
            return self.static(apps.icons, path[len("/box/icons/"):])
        if path.startswith("/box/store-icons/"):
            return self.static(boxos.store_icons.folder, path[len("/box/store-icons/"):])
        if path.startswith("/box/fonts/"):                 # Sofa's typefaces (on the box, or in Sofa's folder)
            name = os.path.basename(path)
            for d in (os.path.join(HERE, "fonts"), os.path.join(HERE, "..", "..", "client", "vendor", "fonts")):
                if os.path.isfile(os.path.join(d, name)):
                    return self.static(d, name)
            return self.send('{"error":"not found"}', status=404)
        if path.startswith("/box/games/"):
            return self.static(os.path.join(HERE, "games"), path[len("/box/games/"):] or "index.html")
        if path == "/box/api/apps":
            s, st = settings(), servers.state()
            default = servers.get(st["default"]) if st["default"] else None
            return self.send(json.dumps({"apps": apps.listing(), "running": browser.running() if browser and browser.connected() else [],
                                         "devtools": bool(browser and browser.connected()), "sofa": server(),
                                         "sofa_name": (found.get(server()) or {}).get("name"), "theme": s["theme"],
                                         "name": s["boot_text"], "welcomed": s["welcomed"], "slow": slow_board(),
                                         "default_server": {k: default[k] for k in ("id", "name", "kind", "where")} if default else None,
                                         "ask": st["ask"], "servers": len(st["servers"]),
                                         "devices": {k: devices_seen[k] for k in ("drives", "disc", "n")},
                                         "front": browser.front_app() if browser and browser.connected() else None}))
        if path == "/box/api/sofa/continue":                # Home's "Continue watching"
            return self.send(json.dumps(sofa_continue()))
        if path == "/box/api/sofa":                         # the chooser: servers added, found, free, others
            return self.send(json.dumps(sofa_listing()))
        if path == "/box/api/sofa/scan":                    # look again (Jellyfin, Emby, Plex too)
            scan_others()
            return self.send(json.dumps(sofa_listing()))
        if path == "/box/api/sofa/add":                     # a typed or pasted address (a share link works too)
            entry = data.get("entry") if isinstance(data.get("entry"), dict) else None
            if entry and entry.get("featured"):
                entry = boxservers.identify(entry.get("url"))
            elif not entry:
                entry = boxservers.identify(str(data.get("url") or ""))
            else:                                           # one the box found at home: check it's there
                entry = boxservers.identify(str(entry.get("url") or ""))
            return self.send(json.dumps({"ok": True, "server": servers.add(entry)}))
        if path == "/box/api/sofa/remove":
            servers.remove(str(data.get("id") or ""))
            return self.send(json.dumps(dict(sofa_listing(), ok=True)))
        if path == "/box/api/sofa/choose":                  # open this one every time, or ask
            servers.choose(data.get("id"), bool(data.get("remember")))
            return self.send(json.dumps(dict(sofa_listing(), ok=True)))
        if path == "/box/api/sofa/rename":
            servers.rename(str(data.get("id") or ""), data.get("name"))
            return self.send(json.dumps(dict(sofa_listing(), ok=True)))
        if path == "/box/api/sofa/open":
            sid = data.get("id")
            if data.get("live") and not sid:                 # Live TV: the Sofa it opens with, else Sofa on this box
                st = servers.state()
                sid = st["default"] if st["default"] and not st["ask"] else ("box" if local_sofa.available() else None)
            return self.send(json.dumps(open_sofa(sid, data.get("hash") or "")))
        if path == "/box/api/sofa/chooser":                 # from Sofa's menu: the box's server chooser, or its Settings
            to = "#/settings" if data.get("to") == "settings" else "#/sofa"
            if browser and browser.connected():
                t = browser.tab_of("home")
                if t:
                    browser.evaluate(t, "location.hash = %s" % json.dumps(to))
                go_home()
            return self.send(json.dumps({"ok": True, "go": "/box/home" + to}))
        if path == "/box/api/setup":                       # the first start and Settings: remotes, Wi-Fi, Bluetooth
            if arg("scan") == "1":
                bluetooth.want(30, autopair=not settings()["welcomed"] or arg("autopair") == "1")
            return self.send(json.dumps(setup_state()))
        if path == "/box/api/bt/pair":
            bluetooth.pair(str(data.get("mac") or ""))
            return self.send('{"ok":true}')
        if path == "/box/api/bt/forget":
            boxos.bt_forget(str(data.get("mac") or ""))
            bluetooth.devices = boxos.bt_devices()
            return self.send('{"ok":true}')
        if path == "/box/api/remote/forget":                # every phone has to scan the code again
            phone.forget_all()
            return self.send('{"ok":true}')
        if path == "/box/api/timezone":
            if self.command == "POST":
                if not set_timezone(str(data.get("tz") or "")):
                    raise ValueError("That time zone didn't take.")
            return self.send(json.dumps({"timezone": current_timezone(), "zones": timezones() if arg("all") == "1" else []}))
        if path == "/box/api/hotspot":                      # the box's own Wi-Fi, on or off by hand
            if data.get("on"):
                network.start_hotspot()
            else:
                network.stop_hotspot()
            return self.send(json.dumps({"ok": True, "hotspot": network.hotspot}))
        if path == "/box/api/devices":
            return self.send(json.dumps({k: devices_seen[k] for k in ("drives", "disc", "n")}))
        if path == "/box/api/devices/eject":
            return self.send(json.dumps(boxos.eject(str(data.get("dev") or ""))))
        if path == "/box/api/disc/play":                    # a DVD, Blu-ray or music CD, in the box's player
            disc = devices_seen.get("disc")
            if not disc:
                raise ValueError("There's no disc in the drive.")
            player.play(boxos.disc_payload(disc), "")
            return self.send('{"ok":true}')
        if path == "/box/api/apps/install":
            entry = boxos.store_entry(str(data.get("store_id") or "")) if data.get("store_id") else \
                boxos.site_entry(str(data.get("url") or ""), data.get("name"))
            if not entry:
                raise ValueError("That app isn't in the store.")
            return self.send(json.dumps({"ok": True, "app": apps.install(entry)}))
        if path == "/box/api/apps/remove":
            return self.send(json.dumps({"ok": apps.remove(str(data.get("id") or ""))}))
        if path == "/box/api/apps/arrange":
            apps.arrange(data.get("order"), data.get("hidden"))
            return self.send(json.dumps({"ok": True}))
        if path == "/box/api/store":
            installed = {a["id"] for a in apps.listing()}
            st = boxos.store()
            for section in st["sections"]:
                for e in section["apps"]:
                    e["installed"] = e["id"] in installed
                    icon = boxos.store_icons.file(e["id"])
                    if icon:
                        e["icon_url"] = "/box/store-icons/" + icon
            boxos.store_icons.want([e for sec in st["sections"] for e in sec["apps"]])
            return self.send(json.dumps(st))
        if path == "/box/api/open":
            return self.send(json.dumps(open_app(data.get("id"), data.get("url"), data.get("hash"))))
        if path == "/box/api/home":
            return self.send(json.dumps({"ok": True, "home": go_home()}))
        if path == "/box/api/close":
            if browser and browser.connected() and data.get("target"):
                browser.close(str(data["target"]))
            return self.send('{"ok":true}')
        if path == "/box/api/files":
            return self.send(json.dumps({"roots": [{k: r[k] for k in ("id", "name", "drive")} for r in boxos.roots()]}))
        if path == "/box/api/files/list":
            return self.send(json.dumps(boxos.listing(arg("root"), arg("path"))))
        if path in ("/box/api/files/delete", "/box/api/files/rename", "/box/api/files/move"):
            return self.send(json.dumps(boxos.file_action(path.rsplit("/", 1)[1], data)))
        if path == "/box/api/files/folder":
            return self.send(json.dumps(boxos.make_folder(data.get("root"), data.get("path"), data.get("name"))))
        if path == "/box/api/files/play":                   # a video or song from Files, in the box's player
            _, full = boxos.resolve(data.get("root"), data.get("path"))
            player.play({"url": full, "local": True, "title": os.path.basename(full), "item": None}, "")
            return self.send('{"ok":true}')
        if path == "/box/files/raw":                        # a picture from Files, to look at
            _, full = boxos.resolve(arg("root"), arg("path"))
            if boxos.kind_of(full) != "image":
                raise ValueError("Only pictures open here.")
            return self.static(os.path.dirname(full), os.path.basename(full))
        if path == "/box/api/games":
            with open(os.path.join(HERE, "games", "games.json"), encoding="utf-8") as f:
                return self.send(f.read())
        if path == "/box/api/shield":
            if self.command == "POST":
                on = bool(data.get("on"))
                save_settings(shield=on)
                threading.Thread(target=lambda: run(["sudo", "-n", os.path.join(HERE, "sofa-box"), "shield", "on" if on else "off"], 300),
                                 daemon=True).start()
            return self.send(json.dumps(dict(boxos.shield_status(), wanted=settings().get("shield", True))))
        return self.send('{"error":"not found"}', status=404)


    # ---- a server's pages, passed through
    def proxy(self, entry=None):
        base = entry["url"] if entry else server()
        target = urllib.parse.urlsplit(base)
        body = self.body() if self.command in ("POST", "PUT", "DELETE") else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() not in ("origin", "referer")}
        page = urllib.parse.urlsplit(self.path).path in ("/", "/index.html")
        if not page:
            headers["Accept-Encoding"] = self.headers.get("Accept-Encoding", "")
        if entry and entry.get("where") == "box" and not local_sofa.answering():
            local_sofa.ensure()                             # "This box": started on the first visit
        r = conn = None
        for attempt in (1, 2):
            if target.scheme == "https":
                conn = http.client.HTTPSConnection(target.hostname, target.port or 443, timeout=60, context=ssl.create_default_context())
            else:
                conn = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=60)
            try:
                conn.request(self.command, self.path, body=body, headers=dict(headers, Host=target.netloc, Connection="close"))
                r = conn.getresponse()
                break
            except OSError:
                r = None
                if entry and entry.get("where") == "box" and attempt == 1 and local_sofa.ensure():
                    continue
                break
        if r is None:
            where = ("Sofa on this box isn't answering. Trying again…" if entry and entry.get("where") == "box" else
                     "%s isn't answering. Is it on, and is the box online? Trying again…" % html_escape((entry or {}).get("name") or "Sofa"))
            return self.send("<!doctype html><meta http-equiv=refresh content=5><body style='background:#0a0e1a;color:#ccc;"
                             "font:28px system-ui;display:grid;place-items:center;height:90vh;text-align:center;padding:0 10vw'>"
                             + where + "<br><small style='opacity:.6;font-size:20px'>Home goes back to the box's home screen.</small>",
                             "text/html; charset=utf-8", 502)
        out_headers = []
        for k, v in r.getheaders():
            kl = k.lower()
            if kl in HOP or kl == "strict-transport-security":
                continue
            if kl == "set-cookie":                          # kept for this server's address on the box
                v = re.sub(r";\s*(Secure|Domain=[^;]*)", "", v, flags=re.I)
            if kl == "location" and v.startswith(base):     # the server sending you elsewhere on itself
                v = v[len(base):] or "/"
            out_headers.append((k, v))
        if page and r.status == 200:
            html = r.read().decode("utf-8", "replace")
            html = html.replace("<head>", '<head><script src="/box/native.js"></script>', 1)
            data = html.encode("utf-8")
            self.send_response(r.status)
            for k, v in out_headers:
                if k.lower() != "content-encoding":
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            conn.close()
            return
        self.send_response(r.status, r.reason)
        for k, v in out_headers:
            self.send_header(k, v)
        length = r.getheader("Content-Length")
        if length is not None:
            self.send_header("Content-Length", length)
            self.end_headers()
            self.copy(r, int(length))
        else:
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.write(b"0\r\n\r\n")
        conn.close()

    def copy(self, r, n):
        while n > 0:
            chunk = r.read(min(65536, n))
            if not chunk:
                break
            self.wfile.write(chunk)
            n -= len(chunk)


class RemoteHandler(BaseHTTPRequestHandler):
    """The phone remote, on the home network: its page, and what it presses. Phones at home only, and only
    with the code the TV shows (then a sign-in of their own)."""
    protocol_version = "HTTP/1.1"
    COOKIE = "sofa_remote"

    def log_message(self, *args):
        pass

    send = Handler.send
    body = Handler.body

    def token(self):
        m = re.search(r"(?:^|;\s*)%s=([0-9a-f]{48})" % self.COOKIE, self.headers.get("Cookie") or "")
        return m.group(1) if m else None

    def home_network(self):
        ip = self.client_address[0]
        return bool(re.match(r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|::1$|fe80:|fd)", ip))

    def cookie(self, token):
        return "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000" % (self.COOKIE, token)

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route()

    def route(self):
        if not self.home_network():
            return self.send("Phones at home only.", "text/plain; charset=utf-8", 403)
        path = urllib.parse.urlsplit(self.path).path
        m = re.match(r"^/r/(\d{4})$", path)
        if m:                                               # the QR code on the TV
            token = phone.pair(m.group(1), (self.headers.get("User-Agent") or "").split("(")[-1].split(";")[0].strip() or "Phone")
            return self.send("", status=302, headers=dict({"Location": "/" if token else "/?again=1"},
                                                          **({"Set-Cookie": self.cookie(token)} if token else {})))
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "remote.html"), encoding="utf-8") as f:
                return self.send(f.read(), "text/html; charset=utf-8")
        if path in ("/icon.png", "/icon-512.png"):          # the remote's Home Screen icon
            buf = __import__("io").BytesIO()
            module("sofa-box-art").app_icon(settings(), 512 if "512" in path else 180).save(buf, "PNG")
            return self.send(buf.getvalue(), "image/png", headers={"Cache-Control": "max-age=86400"})
        if path == "/manifest.json":                         # Android: "Add to Home screen" as an app
            name = settings().get("boot_text") or "Sofa Box"
            return self.send(json.dumps({"name": name + " remote", "short_name": "Sofa Box", "start_url": "/", "display": "standalone",
                                         "background_color": "#0D0D10", "theme_color": "#0D0D10",
                                         "icons": [{"src": "/icon.png", "sizes": "180x180", "type": "image/png"},
                                                   {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}]}),
                             "application/manifest+json")
        if self.command == "POST" and self.headers.get("X-Sofa-Remote") != "1":
            return self.send('{"error":"missing X-Sofa-Remote"}', status=400)
        data = json.loads(self.body() or b"{}") if self.command == "POST" else {}
        if path == "/api/pair":
            token = phone.pair(str(data.get("code") or "").strip(), data.get("name"))
            if not token:
                return self.send('{"error":"That code isn\'t the one on the TV."}', status=403)
            return self.send('{"ok":true}', headers={"Set-Cookie": self.cookie(token)})
        if not phone.valid(self.token()):
            return self.send(json.dumps({"paired": False, "name": settings().get("boot_text") or "Sofa Box"}), status=401)
        try:
            if path == "/api/state":
                p = player.status
                return self.send(json.dumps({"paired": True, "name": settings().get("boot_text") or "Sofa Box",
                                             "playing": {k: p.get(k) for k in ("title", "sub", "t", "d", "paused")} if p else None,
                                             "front": browser.front_app() if browser and browser.connected() else None,
                                             "hotspot": bool(network.hotspot), "welcomed": settings()["welcomed"]}))
            if path == "/api/key":
                phone.key(str(data.get("k") or ""))
            elif path == "/api/hello":                      # the phone's time zone, for a box that doesn't know its own
                set_timezone(str(data.get("tz") or ""), only_if_unset=True)
            elif path == "/api/text":
                phone.text(data.get("t") or "")
            elif path == "/api/pointer":
                phone.pointer(float(data.get("dx") or 0), float(data.get("dy") or 0), data.get("click"), float(data.get("scroll") or 0))
            elif path == "/api/volume":
                phone.volume(data.get("by"))
            elif path == "/api/wifi":
                return self.send(json.dumps(dict(network.scan() if not network.hotspot else {"ok": True, "networks": network.cached},
                                                 hotspot=bool(network.hotspot))))
            elif path == "/api/wifi/join":
                return self.send(json.dumps(network.join(data.get("ssid") or "", data.get("password"))))
            else:
                return self.send('{"error":"not found"}', status=404)
        except ValueError as exc:
            return self.send(json.dumps({"error": str(exc)}), status=400)
        return self.send('{"ok":true}')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def shutil_which(name):
    import shutil
    return shutil.which(name)


def html_escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    global phone
    try:
        migrate_server()
    except Exception as exc:
        print("Moving the old Sofa setting: %s" % exc, file=sys.stderr)
    threading.Thread(target=look, daemon=True).start()
    threading.Thread(target=watch_devices, daemon=True, name="devices").start()
    phone = PhoneRemote()
    try:
        remote = Server(("0.0.0.0", PhoneRemote.PORT), RemoteHandler)
        threading.Thread(target=remote.serve_forever, daemon=True, name="phone-remote").start()
    except OSError as exc:
        print("The phone remote can't use port %d: %s" % (PhoneRemote.PORT, exc), file=sys.stderr)
    if shutil_which("nmcli") and os.environ.get("SOFA_BOX_HOTSPOT", "1") != "0":
        threading.Thread(target=network.watch, daemon=True, name="hotspot").start()
    if not settings()["welcomed"]:                       # a new box: remotes in pairing mode pair by themselves
        bluetooth.want(600, autopair=True)
    httpd = Server(("127.0.0.1", PORT), Handler)
    print("Sofa box agent on http://127.0.0.1:%d" % PORT, file=sys.stderr, flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
