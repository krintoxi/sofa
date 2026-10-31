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
    return env


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
        self.proc, self.sock_path, self.payload, self.cookie = None, None, None, ""
        self.status = {}
        self.news, self.seq = [], 0             # what the page hears about, numbered (every page gets all of it)
        self.cond = threading.Condition()
        self.req = 0

    def _args(self, p):
        s, sock = settings(), self.sock_path
        mpv = os.environ.get("SOFA_BOX_MPV", "mpv")         # previews and tests can use a stand-in
        args = ([sys.executable] if mpv.endswith(".py") else []) + [mpv, "--input-ipc-server=" + sock, "--fs", "--force-window=immediate", "--idle=no", "--keep-open=no",
                "--osd-level=1", "--osd-font-size=46", "--osd-bar-h=2.2", "--sub-font-size=46", "--term-osd=no",
                "--title=" + ("Sofa" if p.get("adult") else p.get("title") or "Sofa"),
                "--input-conf=" + os.path.join(HERE, "mpv-input.conf"),
                "--cache=yes", "--demuxer-max-bytes=120MiB", "--network-timeout=40"]
        if not p.get("local"):                              # from Sofa: as the signed-in TV
            args.append("--http-header-fields=Cookie: %s,X-Sofa: 1" % self.cookie.replace(",", "%2C"))
        hw = s["hwdec"] if s["hwdec"] != "auto" else ("v4l2m2m-copy" if slow_board() else "auto-safe")
        args.append("--hwdec=" + hw)
        if slow_board():
            args += ["--profile=fast", "--vd-lavc-threads=4", "--video-sync=audio"]
        if s["audio"] == "passthrough":
            args.append("--audio-spdif=ac3,eac3,dts")
        if p.get("start"):
            args.append("--start=%.1f" % float(p["start"]))
        for sub in p.get("subtitles") or []:
            args.append("--sub-file=" + rewrite(sub.get("url", "")))
        args += list(s.get("mpv_args") or []) + shlex_split(os.environ.get("SOFA_BOX_MPV_ARGS", ""))
        return args + [p["url"] if p.get("local") else rewrite(p["url"])]

    def play(self, payload, cookie):
        self.stop(save=True, reason="replaced")
        self.payload, self.cookie = payload, cookie
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
        drops_checked = False
        while proc.poll() is None:
            time.sleep(1)
            t = self.position()
            if t is None:
                continue
            d = float(p.get("duration") or 0) or float(self.command("get_property", "duration") or 0) + float(p.get("offset") or 0)
            paused = bool(self.command("get_property", "pause"))
            self.status.update(t=int(t), d=int(d), paused=paused)
            marker = self.marker(t)
            if marker and intro_shown != marker["start"]:
                intro_shown = marker["start"]
                self.command("show-text", "OK: skip the %s" % ("recap" if marker.get("kind") == "recap" else "intro"), 6000)
            if d and time.time() - last_save > 10:
                last_save = time.time()
                save_progress(p.get("item"), t, d, False, self.cookie)
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
            save_progress(p.get("item"), d if watched else t, d, bool(watched), self.cookie)
        if code not in (0, 4) and reason is None:
            toast("That video couldn't play on the box: " + (err.splitlines() or ["mpv stopped"])[-1][:120])
        if proc is self.proc:
            self.proc = None
            self.status = {}
        if reason == "replaced":                # another video took its place: the page knows already
            return
        self.tell(done={"item": p.get("item"), "t": t, "d": d, "ended": bool(ended), "done": bool(watched)})

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


def shlex_split(text):
    import shlex
    return shlex.split(text) if text else []


def rewrite(url):
    """The page builds addresses on this agent (127.0.0.1:8091); mpv goes to Sofa itself."""
    if url.startswith("http://127.0.0.1:%d" % PORT) or url.startswith("http://localhost:%d" % PORT):
        return server() + url.split(str(PORT), 1)[1]
    return url if url.startswith("http") else server() + url


def save_progress(item, t, d, done, cookie):
    if not item or not server():
        return
    try:
        req = urllib.request.Request(server() + "/api/progress/" + urllib.parse.quote(item, safe=""), method="POST",
                                     data=json.dumps({"t": t, "d": d, "done": done}).encode(),
                                     headers={"Content-Type": "application/json", "X-Sofa": "1", "Cookie": cookie})
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5).close()
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
    _, ssid = run(["iwgetid", "-r"], 5)
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
        code, out = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"], 25)
        if code != 0:
            return {"ok": False, "networks": [], "message": "Wi-Fi from here needs NetworkManager (Raspberry Pi OS Bookworm has it)."
                    if "No such file" in out or "not found" in out else out[-200:]}
        nets = {}
        for line in out.splitlines():
            parts = re.split(r"(?<!\\):", line)
            if len(parts) >= 3 and parts[0]:
                ssid = parts[0].replace("\\:", ":")
                if ssid not in nets or int(parts[1] or 0) > nets[ssid]["signal"]:
                    nets[ssid] = {"ssid": ssid, "signal": int(parts[1] or 0), "secure": bool(parts[2])}
        return {"ok": True, "networks": sorted(nets.values(), key=lambda n: -n["signal"])}
    if a == "wifi-connect":
        code, out = run(["nmcli", "device", "wifi", "connect", str(data.get("ssid", ""))] +
                        (["password", str(data["password"])] if data.get("password") else []), 45)
        return {"ok": code == 0, "message": "Connected." if code == 0 else out[-200:]}
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
    x.send(body === undefined ? null : body);
    return x.responseText;
  }
  window.SofaNative = {
    version: function () { return "1"; }, appVersion: function () { return "0"; },
    caps: function () { return call("caps"); }, status: function () { return call("status"); },
    play: function (json) { cover(true); call("play", json); }, control: function (json) { call("control", json); },
    servers: function () { return "[]"; }, choose: function () {}, forget: function () { location.href = "/box/finder?choose=1"; }
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

    def route(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/box/"):
            return self.box(path, urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
        if not server() or "choose=1" in self.path:
            if "choose=1" in self.path:
                with _lock:
                    state["chosen"] = None
            return self.send("", status=302, headers={"Location": "/box/finder"})
        return self.proxy()

    # ---- the agent's own pages and calls
    def box(self, path, qs):
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
            player.play(payload, self.headers.get("Cookie", ""))
            return self.send('{"ok":true}')
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
        if path.startswith(("/box/api/", "/box/home", "/box/icons/", "/box/games/", "/box/fonts/")) or path == "/box/files/raw":
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
        if path.startswith("/box/fonts/"):                 # Sofa's typefaces (on the box, or in Sofa's folder)
            name = os.path.basename(path)
            for d in (os.path.join(HERE, "fonts"), os.path.join(HERE, "..", "..", "client", "vendor", "fonts")):
                if os.path.isfile(os.path.join(d, name)):
                    return self.static(d, name)
            return self.send('{"error":"not found"}', status=404)
        if path.startswith("/box/games/"):
            return self.static(os.path.join(HERE, "games"), path[len("/box/games/"):] or "index.html")
        if path == "/box/api/apps":
            s = settings()
            return self.send(json.dumps({"apps": apps.listing(), "running": browser.running() if browser and browser.connected() else [],
                                         "devtools": bool(browser and browser.connected()), "sofa": server(),
                                         "sofa_name": (found.get(server()) or {}).get("name"), "theme": s["theme"],
                                         "name": s["boot_text"], "welcomed": s["welcomed"], "slow": slow_board(),
                                         "front": browser.front_app() if browser and browser.connected() else None}))
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


    # ---- Sofa's pages, passed through
    def proxy(self):
        target = urllib.parse.urlsplit(server())
        body = self.body() if self.command in ("POST", "PUT", "DELETE") else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        page = urllib.parse.urlsplit(self.path).path in ("/", "/index.html")
        if not page:
            headers["Accept-Encoding"] = self.headers.get("Accept-Encoding", "")
        conn = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=60)
        try:
            conn.request(self.command, self.path, body=body, headers=dict(headers, Host=target.netloc, Connection="close"))
            r = conn.getresponse()
        except OSError:
            return self.send("<!doctype html><meta http-equiv=refresh content=5><body style='background:#0a0e1a;color:#ccc;"
                             "font:28px system-ui;display:grid;place-items:center;height:90vh'>Sofa isn't answering. "
                             "Is the Sofa computer on? Trying again…", "text/html; charset=utf-8", 502)
        out_headers = [(k, v) for k, v in r.getheaders() if k.lower() not in HOP]
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


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def main():
    threading.Thread(target=look, daemon=True).start()
    httpd = Server(("127.0.0.1", PORT), Handler)
    print("Sofa box agent on http://127.0.0.1:%d" % PORT, file=sys.stderr, flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
