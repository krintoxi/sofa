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
import base64
import collections
import http.client
import json
import os
import re
import select
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
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
VERSION = "2"                                               # what the box offers Sofa's pages (window.SofaBox)


def os_version():
    """Sofa Box OS's version (deploy/sofa-box/VERSION), like 1.0.0; the GitHub release with the card has the same."""
    try:
        with open(os.path.join(HERE, "VERSION")) as f:
            return f.read().strip() or "?"
    except OSError:
        return "?"


OS_VERSION = os_version()
_STEADY = (time.time(), time.monotonic())
_monotonic = time.monotonic


def steady():
    """The time, for "how long ago was that": the clock's time when the agent started plus the seconds since, so it
    never jumps. A new card's clock is weeks behind (it starts from the day its system was made) until the box is first
    online; then it's set right in one step, in the middle of the setup: 36 days at once on a real Pi 3, seconds after
    it joined the home Wi-Fi. Whatever compared a time kept from before with the time now took "just joined" for "a
    month ago": the TV dropped the setup's last step for the plain code, and the remote's secure address was taken for
    gone until the relay next answered. Times that are kept on the card or shown as dates use the clock's own."""
    return _STEADY[0] + _monotonic() - _STEADY[1]


STARTED = steady()
DEFAULTS = {"server": None, "quality": "auto", "hwdec": "auto", "audio": "auto", "learned_720": False, "learned_lite": False,
            "performance": "auto",
            "channel": "stable", "auto_update": "off",          # Settings → Software (weekly updates off: the owner's choice)
            "mpv_args": [], "theme": "street", "boot_text": "", "shield": True, "welcomed": False, "secure_remote": True, "boot_sound": "on",
            "weather": "on", "weather_units": "auto", "weather_place": None,
            "home_layout": "spotlight",                         # Home: the picture follows the remote (Spotlight), or Classic
            "icon_style": "glossy"}                             # the box's own icons: Glossy, Drawn, Sticker, Phosphor, Pixel, or the apps' own
THEMES = ("street", "terminal", "pirate", "sofa", "midnight", "cinema", "ocean", "forest", "grape", "oled")
CHOICES = {"quality": ("auto", "720", "1080"), "audio": ("auto", "passthrough"), "performance": ("auto", "light", "full"),
           "channel": ("stable", "testing"), "auto_update": ("off", "weekly"),
           "hwdec": ("auto", "no", "v4l2m2m-copy", "v4l2m2m", "drm", "auto-safe"), "theme": THEMES, "boot_sound": ("on", "off"),
           "weather": ("on", "off"), "weather_units": ("auto", "c", "f"),
           "home_layout": ("spotlight", "classic"), "icon_style": ("glossy", "drawn", "sticker", "phosphor", "pixel", "original")}
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding",
       "upgrade", "content-length", "host", "accept-encoding"}

_lock = threading.Lock()
found = {}                               # url -> {"name", "id"}
state = {"chosen": None}


def toast(text):
    """A message on the TV: over the page, and on the player screen while a video plays (the page is behind it)."""
    player.tell(toast=text)
    if playing():
        player.osd(toast=text)


# a sound or subtitle track's language, by its code (the player's options)
LANGS = {"en": "English", "eng": "English", "es": "Spanish", "spa": "Spanish", "fr": "French", "fre": "French",
         "fra": "French", "de": "German", "ger": "German", "deu": "German", "it": "Italian", "ita": "Italian",
         "pt": "Portuguese", "por": "Portuguese", "ja": "Japanese", "jpn": "Japanese", "ko": "Korean", "kor": "Korean",
         "zh": "Chinese", "chi": "Chinese", "zho": "Chinese", "ru": "Russian", "rus": "Russian", "ar": "Arabic",
         "ara": "Arabic", "hi": "Hindi", "hin": "Hindi", "nl": "Dutch", "dut": "Dutch", "nld": "Dutch"}


def volume_now():
    """The box's volume now (0-100) and whether it's muted (None: not known)."""
    env = dict(os.environ, XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid())
    try:
        if shutil_which("wpctl"):
            out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], env=env, capture_output=True, text=True,
                                 timeout=5).stdout
        else:
            out = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], env=env, capture_output=True, text=True,
                                 timeout=5).stdout + subprocess.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], env=env,
                                                                     capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    return parse_volume(out)


def parse_volume(out):
    """wpctl's "Volume: 0.45 [MUTED]", or pactl's "... / 45% / ..." and "Mute: yes"."""
    m = re.search(r"Volume:\s*([0-9.]+)", out)
    if m and "%" not in out.split("\n")[0]:
        return int(round(float(m.group(1)) * 100)), "[MUTED]" in out
    m = re.search(r"(\d+)%", out)
    return (int(m.group(1)) if m else None), bool(re.search(r"Mute:\s*yes", out))


def box_volume(by):
    """The box's volume up or down (or muted): a controller's triggers, a remote's volume keys, the phone remote. The
    TV shows it: over the video (the box's player) or over the page."""
    PhoneRemote.volume(by)
    level, muted = volume_now()
    text = "Sound off" if muted else ("Volume %d%%" % level if level is not None else "Volume")
    if playing():                                        # (the player screen's own card, in the TV's safe area)
        player.osd(volume={"level": level, "muted": bool(muted)})
    elif browser and browser.connected():
        try:
            browser.hud(text, None if muted else level)
        except OSError:
            pass
    return level, muted


def go(where):
    """Send the TV's page somewhere ("#/" is Home)."""
    player.tell(go=where)



def live_input_conf():
    """mpv's keys for Live TV: the usual ones, with up and down (and Page Up / Down, channel ±) changing the channel."""
    path = os.path.join(tempfile.gettempdir(), "sofa-mpv-live-%d.conf" % os.getpid())
    zap = {"UP": "chup", "DOWN": "chdown", "PGUP": "chup", "PGDWN": "chdown", "CHANNEL_UP": "chup", "CHANNEL_DOWN": "chdown"}
    with open(os.path.join(HERE, "mpv-input.conf"), encoding="utf-8") as f:
        keep = [line for line in f if (line.split() or [""])[0] not in zap]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(keep)
        for key, k in zap.items():
            f.write("%-12s %s\n" % (key, key_command(k)))
    return path


def key_command(k):
    """What mpv runs for one of its keys that the box answers (OK, Back, the channel, the menu's): a POST, like every
    call that does something (Handler.READ_ONLY)."""
    return 'run "/usr/bin/curl" "-s" "-o" "/dev/null" "-X" "POST" "-H" "X-Sofa-Box: 1" "http://127.0.0.1:%d/box/native/key?k=%s"' % (PORT, k)


def display_env():
    """The screen's address for mpv. The kiosk session writes it (cage's Wayland socket or X's display),
    since this agent runs as its own service, outside that session."""
    env = dict(os.environ)
    run_dir = env.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    try:
        with open(os.path.join(run_dir, "sofa-box-display"), encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k in ("WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "SCALE") and v:
                    env[k] = v
    except OSError:
        pass
    env.setdefault("XDG_RUNTIME_DIR", run_dir)
    env.pop("SCALE", None)
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


def mpv_option(name):
    """Whether this mpv takes --<name> (--osd-fonts-dir is new in mpv 0.37; an option it doesn't know stops it)."""
    mpv = os.environ.get("SOFA_BOX_MPV", "mpv")
    if mpv.endswith(".py"):
        return True                                  # (the stand-in takes anything)
    if "options" not in _mpv_help:
        try:
            _mpv_help["options"] = subprocess.run([mpv, "--list-options"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            _mpv_help["options"] = ""
    return ("--%s " % name) in _mpv_help["options"]


def learn_mpv():
    """What this mpv can do, asked once when the agent starts (in the background). Each question is mpv starting, about
    a second on a Pi 3, and the first video of the day used to wait for three of them."""
    mpv_knows("hwdec", "v4l2m2m-copy")
    mpv_knows("profile", "fast")
    mpv_option("osd-fonts-dir")


def markers_of(p):
    """A video's intros and recaps as the player screen takes them (in seconds into the whole video; nothing else)."""
    out = []
    for m in p.get("markers") or []:
        try:
            out.append({"kind": str(m.get("kind")), "start": float(m["start"]), "end": float(m["end"])})
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return out


# The TV's player screen: drawn by mpv itself (sofa-player.lua), in Sofa's typefaces and the box's theme colour
PLAYER_SCRIPT = os.path.join(HERE, "sofa-player.lua")
FONT_DIRS = (os.path.join(HERE, "fonts"),                                        # on the box
             os.path.join(HERE, "..", "..", "client", "vendor", "fonts"))         # in Sofa itself (a preview)
THEME_ACCENT = {"street": "FF2E88", "terminal": "39FF88", "pirate": "E6B450", "sofa": "F4B740", "midnight": "F4B740",
                "cinema": "E5484D", "ocean": "3CC8D8", "forest": "8BD46E", "grape": "C792FF", "oled": "F4B740"}


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


def write_durably(path, text, mode=0o644):
    """A small file the box mustn't lose: on the card before this returns, whole or not at all. (A Pi that restarts
    by itself, a power cut, a weak power supply: without this, a change from the last few seconds was gone, and a box
    that had just finished its setup asked for it again.)"""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        d = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(d)
        finally:
            os.close(d)
    except OSError:
        pass


def save_settings(**changes):
    with _lock:
        s = settings()
        s.update(changes)
        write_durably(SETTINGS, json.dumps(s, indent=1))
    return s


def model():
    try:
        with open("/proc/device-tree/model", encoding="utf-8", errors="replace") as f:
            return f.read().strip("\x00\n ")
    except OSError:
        return ""


def os_name():
    """The system the box is built on, for About: "Raspberry Pi OS" on a Pi, else what /etc/os-release says
    ("Debian GNU/Linux 13 (trixie)" on a PC or a VM, docs/hardware.md)."""
    if board()["gen"]:
        return "Raspberry Pi OS"
    try:
        with open(os.environ.get("SOFA_BOX_OS_RELEASE") or "/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"') or "Linux"
    except OSError:
        pass
    return "Linux"


_board = {}


def board():
    """What the box is: the Raspberry Pi's generation (0 for any other computer), its memory, its processor's cores and
    what it is, the chips that decode video, a VM's name, the TV's picture. Everything that adapts to the hardware asks
    this."""
    if not _board:
        m = model()
        g = re.search(r"Raspberry Pi (?:Compute Module )?(\d)|Raspberry Pi (Zero 2)|Raspberry Pi (Zero)", m)
        gen = int(g.group(1)) if g and g.group(1) else 3 if g and g.group(2) else 1 if g else 0
        if not m and os.environ.get("SOFA_BOX_SLOW") == "1":
            gen = 3                                        # a preview acting like a Pi 3
        _board.update(model=m or "this computer", gen=gen, memory_mb=boxos.memory_mb(), cores=boxos.cores(),
                      cpu=boxos.processor(), video=boxos.video_chips(), vm=boxos.virtual())
    tv = 0
    for c in sorted(__import__("glob").glob("/sys/class/drm/card*-HDMI-A-*")):
        try:
            with open(c + "/status") as f:
                if f.read().strip() != "connected":
                    continue
            with open(c + "/modes") as f:
                tv = max(tv, int((f.readline().strip().split("x") + ["0"])[1].rstrip("ip") or 0))
        except (OSError, ValueError):
            continue
    return dict(_board, tv_height=tv)


def slow_board():
    """A Raspberry Pi 3 or older (by its chips): 1080p H.264 is about its limit, HEVC is out."""
    return 1 <= board()["gen"] <= 3


def light():
    """The light look (no costly effects, fewer apps open): Settings → Performance, or by itself on a Pi 3 or
    older, or with 1 GB or less."""
    s = settings()
    p = s.get("performance")
    if p in ("light", "full"):
        return p == "light"
    if s.get("learned_lite"):                               # (the box saw the full look was slow to draw here)
        return True
    b = board()
    return 1 <= b["gen"] <= 3 or b["memory_mb"] <= 1100


def max_height():
    s = settings()
    if s["quality"] in ("720", "1080"):
        return int(s["quality"])
    if s["learned_720"]:
        return 720
    b = board()
    return 2160 if (b["gen"] >= 4 or b["gen"] == 0 and b["memory_mb"] >= 3500) and b["tv_height"] >= 2160 else 1080


def caps():
    """What the box plays itself (mpv on the Pi): told to Sofa, so it converts only the rest. A Pi 4 or 5 on a
    4K TV takes 4K as it is."""
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


MACHINES = ((r"imac", "iMac"), (r"macbook[-_ ]?air", "MacBook Air"), (r"macbook[-_ ]?pro", "MacBook Pro"), (r"macbook", "MacBook"),
            (r"mac[-_ ]?mini", "Mac mini"), (r"mac[-_ ]?studio", "Mac Studio"), (r"raspberry|^pi\b|sofabox", "Raspberry Pi"),
            (r"^(desktop|laptop)-[a-z0-9]+$", "Windows PC"), (r"synology|diskstation|nas\b|qnap|truenas|unraid", "NAS"),
            (r"ubuntu|debian|fedora|linux", "Linux computer"))


def machine_of(host):
    """What kind of computer a name says it is ("Marielyss-iMac" -> iMac), or None."""
    h = (host or "").lower()
    return next((kind for pat, kind in MACHINES if re.search(pat, h)), None)


def pretty_host(host):
    """A computer's network name for people: "Marielyss-iMac.local." -> "Marielyss iMac"."""
    h = re.sub(r"\.(local|lan|home)\.?$", "", str(host or "").strip().rstrip("."), flags=re.I)
    return re.sub(r"[-_]+", " ", h).strip()[:40] or None


def library_of(base):
    """How much a Sofa holds (its health check says, at home, with no sign-in): {"movies", "shows"}, or None."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(base.rstrip("/") + "/healthz", timeout=3) as r:
            lib = json.loads(r.read().decode("utf-8")).get("library") or {}
        return {k: int(lib[k]) for k in ("movies", "shows") if isinstance(lib.get(k), int)} or None
    except Exception:
        return None


def add(base, host=None):
    """A Sofa found at `base` (by Bonjour, with its computer's name, or SSDP, or the one it had). The same Sofa reached
    at another address (another network on that computer, or found both ways) is one entry: its id says so, or, for a
    Sofa too old to say, the computer's name and port."""
    base = base.rstrip("/")
    with _lock:
        if base in found:
            if host and not found[base].get("host"):
                found[base]["host"] = pretty_host(host)
            return
    j = info(base)
    if not j:
        return
    port = urllib.parse.urlsplit(base).port
    entry = {"name": j.get("name") or "Sofa", "id": j.get("id"), "version": j.get("version"),
             "host": pretty_host(host), "library": library_of(base), "port": port}
    entry["machine"] = machine_of(host)
    with _lock:
        same = next((u for u, v in found.items() if (entry["id"] and v.get("id") == entry["id"]) or
                     (entry["host"] and v.get("host") == entry["host"] and v.get("port") == port)), None)
        if same:
            for k in ("host", "machine", "library"):            # (what the other way didn't know)
                if entry.get(k) and not found[same].get(k):
                    found[same][k] = entry[k]
            return
        found[base] = entry


def bonjour():
    """Sofas announcing themselves at home: [(address, the computer's name)]."""
    try:
        out = subprocess.run(["avahi-browse", "-rtp", "_sofa._tcp"], capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [("http://%s:%s" % (p[7], p[8]), p[6]) for p in (line.split(";") for line in out.splitlines())
            if len(p) > 8 and p[0] == "=" and p[2] == "IPv4"]


def ssdp():
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: %s\r\n\r\n" % SOFA_ST).encode()
    hits = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.settimeout(1.0)
        s.sendto(msg, ("239.255.255.250", 1900))
        end = steady() + 3
        while steady() < end:
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


looking = {"until": steady() + 120, "now": threading.Event()}   # look often just after starting, and while the chooser is open


def look_soon(seconds=120):
    """Look for Sofa now, and often for a while: the box has just joined a network (at the setup that's minutes after
    it started, when it had gone down to a look a minute: Home could open without the Sofa that was there)."""
    looking["until"] = max(looking["until"], steady() + seconds)
    looking["now"].set()


def playing():
    """A video in the box's player: background work waits (the Pi's power is for the picture)."""
    return bool(player.proc and player.proc.poll() is None)


def look():
    while True:
        if playing():
            time.sleep(15)
            continue
        last = settings()["server"]
        if last:
            add(last)
            with _lock:
                if state["chosen"] is None and last.rstrip("/") in found:     # the Sofa it had: straight away
                    state["chosen"] = last.rstrip("/")
        if not state["chosen"] or steady() < looking["until"]:   # (the chooser open: what's there, by name)
            for base, host in bonjour() + [(b, None) for b in ssdp()]:
                add(base, host)
        with _lock:
            if state["chosen"] is None:
                if last and last.rstrip("/") in found:
                    state["chosen"] = last.rstrip("/")
                elif len(found) == 1:
                    state["chosen"] = next(iter(found))
        if state["chosen"] and state["chosen"] != last:
            save_settings(server=state["chosen"])
        looking["now"].wait(4 if steady() < looking["until"] else 60)
        looking["now"].clear()


def server():
    return state["chosen"]


# ---------------------------------------------------------------- mpv: the player

class Player:
    """One video at a time in mpv, controlled over its JSON socket."""

    def __init__(self):
        self.proc, self.sock_path, self.payload, self.cookie, self.base = None, None, None, "", None
        self.status = {}
        self.news, self.seq = [], 0             # what the page hears about, numbered (every page gets all of it)
        self.failures = []                      # the last few times it stopped by itself, and why (Send a report)
        self.ran = collections.deque(maxlen=6)  # how the last few videos played (Send a report): no titles
        self.cond = threading.Condition()
        self.req = 0
        self.menu = None                        # the options menu, while it's open (Menu while a video plays)
        self.plays, self.info_path = 0, None    # each play's file for the player screen (gone when its mpv stops)
        # skipping far in a video Sofa converts (seek_to): one under way, the newest place asked for, Sofa's session
        self.far, self.want, self.going, self.sid = None, None, False, None
        self.far_lock = threading.Lock()

    def _args(self, p):
        s, sock, base = settings(), self.sock_path, self.base
        mpv = os.environ.get("SOFA_BOX_MPV", "mpv")         # previews and tests can use a stand-in
        title = "Sofa" if p.get("adult") else str(p.get("title") or "Sofa")
        # The TV's own player screen (sofa-player.lua) instead of mpv's desktop controls, which came up whenever the
        # pointer moved (the phone's touchpad, a stick) and then stayed: the box parks the pointer in the bottom right
        # corner, right on mpv's control bar. No pointer at all now, and everything inside the TV's safe area.
        args = ([sys.executable] if mpv.endswith(".py") else []) + [mpv, "--input-ipc-server=" + sock, "--fs", "--force-window=immediate", "--idle=no", "--keep-open=no",
                "--osc=no", "--input-cursor=no", "--cursor-autohide=always", "--osd-bar=no", "--osd-on-seek=no",
                "--osd-level=1", "--osd-font=Instrument Sans", "--osd-font-size=36", "--osd-margin-x=64", "--osd-margin-y=36",
                "--sub-font-size=46", "--sub-margin-y=40", "--term-osd=no",
                "--script=" + PLAYER_SCRIPT, "--script-opts=sofa_player-info=" + self.write_info(p),
                "--title=" + title, "--force-media-title=" + title,
                "--input-conf=" + (live_input_conf() if p.get("live") else os.path.join(HERE, "mpv-input.conf")),
                "--cache=yes"] + boxos.mpv_cache(board()["memory_mb"]) + ["--network-timeout=40",   # (read-ahead by memory)
                "--hr-seek=no"]       # (resuming starts at the frame mpv can show at once: a Pi 3 decoded seconds to be exact)
        fonts = next((d for d in FONT_DIRS if os.path.isdir(d)), None)
        if fonts and mpv_option("osd-fonts-dir"):
            args.append("--osd-fonts-dir=" + os.path.abspath(fonts))
        if "/media/hls/" in str(p.get("url") or "") and not p.get("live"):
            # Sofa's converted video is a playlist still being written. mpv (ffmpeg) took it for live TV and started
            # three segments from its end, up to half a minute past the place it was asked to resume at, and counted
            # from there (the place it saved then was wrong as well): from its first segment.
            args.append("--demuxer-lavf-o-append=live_start_index=0")
        if not p.get("local") and self.from_sofa(p["url"]):   # from Sofa: as the signed-in TV (never to anyone else)
            args.append("--http-header-fields=" + self.sofa_headers())
        hw = s["hwdec"] if s["hwdec"] != "auto" else ("v4l2m2m-copy" if slow_board() and mpv_knows("hwdec", "v4l2m2m-copy")
                                                      else "auto-safe")
        args.append("--hwdec=" + hw)
        if slow_board():
            args += (["--profile=fast"] if mpv_knows("profile", "fast") else []) + \
                ["--vd-lavc-threads=%d" % max(1, board()["cores"]), "--video-sync=audio"]     # (a Pi 1 or Zero has one)
        if s["audio"] == "passthrough":
            args.append("--audio-spdif=ac3,eac3,dts")
        if p.get("start"):
            args.append("--start=%.1f" % float(p["start"]))
        for sub in p.get("subtitles") or []:
            args.append("--sub-file=" + rewrite(sub.get("url", ""), base))
        for k, v in (p.get("mpv") or {}).items():           # a disc: which drive
            args.append("--%s=%s" % (k, v))
        args += list(s.get("mpv_args") or []) + shlex_split(os.environ.get("SOFA_BOX_MPV_ARGS", ""))
        if p.get("start_at") or p.get("then"):              # an archive channel: this film from where it's at, then the next
            return args + ["--{", "--start=%d" % int(p.get("start_at") or 0), rewrite(p["url"], base), "--}"] + \
                [u for u in p.get("then") or [] if str(u).startswith("https://")]
        return args + [p["url"] if p.get("local") else rewrite(p["url"], base)]

    def write_info(self, p):
        """What the player screen shows from the moment mpv opens (sofa-player.lua reads it then): the title, where it
        resumes, its intros, Live TV's channel. Never an adult title: the screen says "Playing"."""
        private = bool(p.get("adult"))
        offset, start = float(p.get("offset") or 0), float(p.get("start") or 0)
        kind = ("live" if p.get("live") else "disc" if p.get("mpv") else "file" if p.get("local")
                else "resume" if offset + start > 30 else "start")
        info = {"title": "Playing" if private else str(p.get("title") or ""), "sub": "" if private else str(p.get("sub") or ""),
                "kind": kind, "at": offset + start, "offset": offset, "duration": float(p.get("duration") or 0),
                "markers": markers_of(p),
                # far: skips past what Sofa has converted go to the agent, which has Sofa convert it again from there
                "far": self.can_convert_again(p), "agent": "http://127.0.0.1:%d" % PORT,
                "live": bool(p.get("live")), "number": p.get("number"), "h24": bool(p.get("h24")),
                "accent": THEME_ACCENT.get(settings().get("theme"), "FF2E88")}
        self.plays += 1
        path = self.info_path = os.path.join(tempfile.gettempdir(), "sofa-play-%d-%d.json" % (os.getpid(), self.plays))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(info, f)
        return path

    def osd(self, **what):
        """What the player screen (sofa-player.lua) shows that only the box knows: the start card's note (False: it
        plays now), a message, the volume, Live TV's banner, the options menu (False closes it)."""
        return self.command("script-message-to", "sofa_player", "sofa", json.dumps(what))

    def from_sofa(self, url):
        return rewrite(url, self.base).startswith((self.base or "http://\0").rstrip("/") + "/")

    def sofa_headers(self):
        return "Cookie: %s,X-Sofa: 1" % (self.cookie or "").replace(",", "%2C")

    def _seek_when_ready(self, to):
        """After loadfile: once the film has started, to its place on the channel's clock."""
        for _ in range(60):
            if self.command("get_property", "time-pos") is not None:
                self.command("seek", to, "absolute")
                return
            time.sleep(0.5)

    def play(self, payload, cookie, base=None):
        asleep["on"] = False                                 # (something plays: the box is awake)
        self.stop(save=True, reason="replaced")
        self.payload, self.cookie, self.base = payload, cookie, base or server()
        self.sock_path = os.path.join(tempfile.gettempdir(), "sofa-mpv-%d.sock" % os.getpid())
        try:
            os.unlink(self.sock_path)
        except OSError:
            pass
        with self.far_lock:
            self.far, self.want, self.sid = None, None, None
        private = bool(payload.get("adult"))            # no adult titles anywhere outside the Adult section
        self.status = {"item": payload.get("item"), "t": int(payload.get("offset") or 0) + int(payload.get("start") or 0),
                       "d": int(payload.get("duration") or 0), "paused": False,
                       "title": "Playing" if private else payload.get("title"), "sub": "" if private else payload.get("sub")}
        self.proc = subprocess.Popen(self._args(payload), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, env=display_env())
        self.proc.sofa_err, self.proc.sofa_info = [], self.info_path
        threading.Thread(target=self._drain, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._watch, args=(self.proc,), daemon=True).start()

    @staticmethod
    def _drain(proc):
        """mpv's messages, read as they come (a full pipe would stop mpv); the last few explain a failure."""
        for line in proc.stderr:              # (never the video's address: it names the title, which may be an adult one)
            said = re.sub(r"\b[a-z][a-z0-9+.-]*://\S+", "the video", line.decode("utf-8", "replace").rstrip())
            proc.sofa_err = (proc.sofa_err + [said])[-8:]

    def command(self, *cmd):
        """Send one command to mpv; returns its "data" (or None)."""
        if not self.sock_path or not self.proc or self.proc.poll() is not None:
            return None
        self.req += 1
        rid = self.req                          # (its own: commands come from several threads at once)
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(self.sock_path)
            s.sendall((json.dumps({"command": list(cmd), "request_id": rid}) + "\n").encode())
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
                    if msg.get("request_id") == rid:
                        s.close()
                        return msg.get("data")
        except OSError:
            pass
        return None

    def position(self):
        """Seconds into the whole video (a converted stream starts at the payload's offset). Skipping far: where to,
        until mpv plays it (the place saved and the phone remote's line say so meanwhile)."""
        far = self.far
        if far and not self._far_settled():
            return far["at"]
        t = self.command("get_property", "time-pos")
        return None if t is None else float(t) + float((self.payload or {}).get("offset") or 0)

    # ---- skipping far in a video Sofa converts for the box. It comes as HLS that Sofa makes from `offset` on while it
    # plays, and mpv can only go where Sofa has converted it so far. Further on (Page Up's 5 minutes, quick presses of
    # right, the number keys, the phone remote's line, Skip intro) or back before where it starts, Sofa converts it
    # again from there, as the page's own player does (load(at) in client/app.js), and mpv loads that. Every skip comes
    # through seek_to; the player screen sends the ones past what mpv has (sofa-player.lua: key "far").

    def can_convert_again(self, p=None):
        """A video Sofa converts for the box, and the page said how it asked Sofa for it (`hls`, Sofa 1.5.2 and later)."""
        p = (self.payload if p is None else p) or {}
        hls = str(p.get("hls") or "")
        return bool(not p.get("live") and not p.get("local") and "/media/hls/" in str(p.get("url") or "") and
                    urllib.parse.urlsplit(hls).path.startswith("/api/hls/") and self.from_sofa(hls))

    def seek_to(self, t, exact=False):
        """To `t` seconds into the whole video. In a video Sofa converts, through _going: one at a time, the newest."""
        p, proc = self.payload or {}, self.proc
        off, d = float(p.get("offset") or 0), float(p.get("duration") or 0)
        if not self.can_convert_again(p):
            return self.command("seek", max(0.0, float(t) - off), "absolute+exact" if exact else "absolute")
        t = max(0.0, min(float(t), d - 3) if d > 3 else float(t))
        with self.far_lock:
            self.want = (proc, t, exact)
            far = self.far if self.far and self.far["proc"] is proc else None
            if far:                                     # one under way: the new place shows at once
                far["at"] = t
                self.status["t"] = int(t)
            busy, self.going = self.going, True
        if far:
            self.osd(far={"at": t})
        if not busy:
            threading.Thread(target=self._going, daemon=True).start()

    def _going(self):
        while True:
            with self.far_lock:
                want, self.want = self.want, None
                if want is None:
                    self.going = False
                    return
            proc, t, exact = want
            if proc is self.proc and proc and proc.poll() is None:
                try:
                    self._go(proc, t, exact)
                except Exception as exc:                # (never stuck: the next skip goes again)
                    print("Skipping: %s" % re.sub(r"\b[a-z][a-z0-9+.-]*://\S+", "the video", str(exc)), file=sys.stderr, flush=True)

    def _go(self, proc, t, exact):
        p = self.payload
        if not (self.far and not self._far_settled()) and self.have(t):
            self.command("seek", max(0.0, t - float(p.get("offset") or 0)), "absolute+exact" if exact else "absolute")
            self.osd(far=False)                         # converted already: mpv goes there itself
            return
        far = self.far                                  # (paused or not, as it goes on: the last skip's is in mpv now)
        paused = far["paused"] if far and not far["sid"] else bool(self.command("get_property", "pause"))
        if not far:
            far = self.far = {"proc": proc, "at": t, "paused": paused, "sid": None}
        far.update(at=t, paused=paused, sid=None)
        self.command("set_property", "pause", True)     # (the picture holds still meanwhile: Sofa stops converting
        self.status["t"] = int(t)                       # what mpv plays now, and mpv mustn't run out of it and stop)
        self.osd(far={"at": t})
        try:
            url, sid = self.convert_again(t)
        except (OSError, ValueError) as exc:
            with self.far_lock:
                if self.want is not None:               # (a newer skip goes on from here)
                    return
            if self.far is far:
                self.far = None
                self.command("set_property", "pause", far["paused"])
                self.osd(far=False, toast="Sofa couldn't get that part ready: %s" % exc)
            return
        if proc is not self.proc or proc.poll() is not None:
            return                                      # (stopped meanwhile: Sofa stops converting when nobody asks)
        self.sid = sid                                  # (the next one replaces this one)
        with self.far_lock:
            if self.want is not None:                   # a newer skip came meanwhile: that one, not this
                return
        p.update(url=url, offset=t, start=0)
        subs = self.subtitles_from(t)
        if subs:                                        # (timed for the new start: Sofa shifts them)
            self.command("set_property", "sub-files", subs)
        far["sid"] = sid
        self.osd(info={"offset": t, "at": t}, far={"at": t, "sid": sid})
        self.command("loadfile", url, "replace")
        self.command("set_property", "pause", far["paused"])

    def _far_settled(self):
        """A far skip is over once mpv plays what Sofa converted for it (where mpv is counts again from then on)."""
        far = self.far
        if not far or not far.get("sid") or self.want is not None:
            return False
        if far["sid"] in str(self.command("get_property", "path") or "") and self.command("get_property", "time-pos") is not None:
            if self.far is far:
                self.far = None
                self.osd(far=False)                     # (the screen saw it start too: this is in case it didn't)
            return True
        return False

    def have(self, t):
        """Whether mpv can go to `t` (the whole video's seconds) in the converted video it plays: from where Sofa started
        it (Sofa keeps all of it) to as far as Sofa has converted it so far."""
        s = t - float((self.payload or {}).get("offset") or 0)
        if s < -0.5:
            return False                                # (before where it starts)
        for prop in ("time-pos", "demuxer-cache-time"):  # back, or into what mpv has read already
            x = self.command("get_property", prop)
            if isinstance(x, (int, float)) and s <= x:
                return True
        made, whole = self.made()
        return whole or s <= made - 2

    def made(self):
        """How much of the converted video Sofa has made so far (its playlist, in seconds), and whether that's all."""
        try:
            text = self.ask_sofa(self.payload["url"], timeout=10).decode("utf-8", "replace")
        except (OSError, ValueError, KeyError):
            return 0.0, False
        return sum(float(x) for x in re.findall(r"#EXTINF:\s*([\d.]+)", text)), "#EXT-X-ENDLIST" in text

    def convert_again(self, t):
        """Sofa converts the video for the box again, from `t` on: as the page asked for it (`hls`: the mode, the
        picture's size, what the box plays), and the conversion before it stops (replace). The new playlist's address."""
        p = self.payload
        old = self.sid or (re.search(r"/media/hls/([0-9a-f]+)/", str(p.get("url") or "")) or [None, None])[1]
        try:
            got = json.loads(self.ask_sofa(p["hls"] + "&t=%.1f" % t + ("&replace=" + old if old else ""), timeout=45))
        except urllib.error.HTTPError as exc:          # Sofa said why (busy converting for others, say)
            try:
                why = json.loads(exc.read()).get("error")
            except (OSError, ValueError, AttributeError):
                why = None
            raise ValueError(why or "Sofa said no (%d)" % exc.code)
        except (OSError, ValueError):
            raise ValueError("Sofa didn't answer")
        path = str(got.get("url") or "") if isinstance(got, dict) else ""
        if not re.match(r"^/media/hls/[0-9a-f]+/index\.m3u8$", path):
            raise ValueError("Sofa didn't say where")
        return self.base.rstrip("/") + path, path.split("/")[3]

    def ask_sofa(self, url, timeout=20):
        """A GET from Sofa as the signed-in TV, as the box's other calls to Sofa go (the page's cookie: to Sofa only)."""
        url = rewrite(url, self.base)
        if not self.from_sofa(url):
            raise ValueError("not this Sofa")
        req = urllib.request.Request(url, headers={"Cookie": self.cookie or "", "X-Sofa": "1"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if url.startswith("http://") else urllib.request.build_opener()
        with opener.open(req, timeout=timeout) as r:
            return r.read(4 << 20)

    def subtitles_from(self, t):
        """The video's subtitles for a converted video that starts at `t` (Sofa shifts them with ?offset=)."""
        out = []
        for sub in (self.payload or {}).get("subtitles") or []:
            u = urllib.parse.urlsplit(rewrite(str(sub.get("url") or ""), self.base))
            q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if k != "offset"]
            out.append(urllib.parse.urlunsplit(u._replace(query=urllib.parse.urlencode(q + ([("offset", "%.2f" % t)] if t else [])))))
        return out

    def starting_note(self, waited):
        """The start card's second line while the picture hasn't moved (the card itself says what's starting, from
        where): resuming a converted video can take a while, and a card that never changes looks like the box hung."""
        p = self.payload or {}
        if p.get("live"):
            return "Up and down change the channel. Back goes back."
        at = float(p.get("offset") or 0) + float(p.get("start") or 0)
        if waited >= 25:
            return "Still waiting for Sofa. Back stops it."
        if "/hls/" in str(p.get("url") or "") and waited >= 3:
            return "Sofa is getting it ready for the box%s: a few seconds more." % (" from where you left off" if at > 30 else "")
        return ""

    def _watch(self, proc):
        """Every second: where it is, Skip Intro, saving the place; at the end: tell the page. Until the picture
        moves, the player screen's start card says it's starting (and starting_note, when it's slow)."""
        p, last_save, noted = self.payload, 0, ""
        drops_checked = started = moving = False
        waited = 0
        run = {"at": time.strftime("%H:%M:%S"), "waits": 0, "waited": 0, "played": 0, "started_after": None,
               "kind": "live" if p.get("live") else "converted" if "/hls/" in str(p.get("url") or "") else "file"}
        self.ran.append(run)
        cache_wait = False
        while proc.poll() is None:
            time.sleep(1)
            if moving:
                run["played"] += 1
                if run["played"] % 5 == 1:
                    self.sample(run)
                now_waiting = self.command("get_property", "paused-for-cache") is True
                if now_waiting:
                    run["waited"] += 1
                    if not cache_wait:
                        run["waits"] += 1
                cache_wait = now_waiting
            if not moving:
                if self.command("get_property", "core-idle") is False:
                    moving = True
                    run["started_after"] = waited + 1
                    self.osd(card=False)
                    self.tell(playing={"item": p.get("item")})     # (the page's start card, behind mpv, can go)
                    if p.get("live"):
                        p["banner_at"] = 0
                        self.banner(0)
                else:
                    waited += 1
                    note = self.starting_note(waited)
                    if note != noted:
                        noted = note
                        self.osd(card=note)
            elif p.get("programs"):                             # an archive channel: its next programme began
                at = self.command("get_property", "playlist-pos")
                if isinstance(at, int) and at != p.get("banner_at", 0):
                    p["banner_at"] = at
                    if 0 <= at < len(p["programs"]) and not p["programs"][at].get("ad"):
                        self.banner(at)
            t = self.position()
            if t is None:
                continue
            far = self.far                                      # (skipping far: where to, and paused or not after)
            started = started or not far
            d = float(p.get("duration") or 0) or float(self.command("get_property", "duration") or 0) + float(p.get("offset") or 0)
            paused = far["paused"] if far else bool(self.command("get_property", "pause"))
            self.status.update(t=int(t), d=int(d), paused=paused)
            if d and steady() - last_save > 10:
                last_save = steady()
                save_progress(p.get("item"), t, d, False, self.cookie, self.base)
            if not drops_checked and not far and t - float(p.get("start") or 0) - float(p.get("offset") or 0) > 90:
                drops_checked = True
                self.check_drops()
        code = proc.wait()
        if self.far and self.far["proc"] is proc:
            self.far = None
        try:
            os.unlink(getattr(proc, "sofa_info", None) or "")   # (what was playing: not left behind in /tmp)
        except OSError:
            pass
        self.menu = None
        time.sleep(0.2)                         # the last of mpv's messages
        err = "\n".join(l for l in proc.sofa_err if l.strip())
        t, d = self.status.get("t") or 0, self.status.get("d") or 0
        reason = getattr(proc, "sofa_reason", None)
        if reason is None and code == 10:       # Back, on the player screen (sofa-player.lua stops mpv with 10)
            reason = "back"
        ended = reason == "next" or (reason is None and code == 0 and d and t > d - 60)
        watched = ended or (d and t > d * 0.95)
        if d:
            save_progress(p.get("item"), d if watched else t, d, bool(watched), self.cookie, self.base)
        failed = code not in (0, 4) and reason is None
        last = (err.splitlines() or ["mpv stopped"])[-1][:120]
        if failed:
            print("mpv stopped (%s): %s" % (code, err.replace("\n", " | ")[-600:]), file=sys.stderr, flush=True)
            self.failures = (self.failures + [{"at": time.strftime("%H:%M:%S"), "code": code, "started": bool(started),
                                               "kind": "live" if p.get("live") else "converted" if "/hls/" in str(p.get("url") or "") else "file",
                                               "said": last}])[-6:]
        if failed and started:
            toast("That video couldn't play on the box: " + last)
        if proc is self.proc:
            self.proc = None
            self.status = {}
        if reason == "replaced":                # another video took its place: the page knows already
            return
        done = {"item": p.get("item"), "t": t, "d": d, "ended": bool(ended), "done": bool(watched)}
        chans = p.get("channels") or []
        if p.get("live") and chans:
            done["channel"] = chans[int(p.get("at") or 0) % len(chans)].get("id")
        if failed and not started and not p.get("local"):     # mpv couldn't even start: the page plays it itself
            done.update(failed=True, error=last)
        elif failed and not started:
            toast("That couldn't play on the box: " + last)
        self.tell(done=done)

    def tell(self, **what):
        with self.cond:
            self.seq += 1
            self.news = [n for n in self.news if steady() - n["at"] < 60] + [dict(what, n=self.seq, at=steady())]
            self.cond.notify_all()

    def marker(self, t):
        for m in (self.payload or {}).get("markers") or []:
            if isinstance(m, dict) and m.get("kind") in ("intro", "recap") and m.get("start", 0) <= t < m.get("end", 0) - 1:
                return m
        return None

    PLAY_PROPS = ("video-codec", "hwdec-current", "width", "height", "container-fps", "video-bitrate", "audio-codec-name",
                  "frame-drop-count", "decoder-frame-drop-count", "current-vo", "current-gpu-context", "vo-delayed-frame-count")

    def sample(self, run):
        """What mpv says now about the video in it (for `ran`): what it is, how it's decoded, frames dropped."""
        for prop in self.PLAY_PROPS:
            v = self.command("get_property", prop)
            if v is not None:
                run[prop] = v

    @staticmethod
    def ran_line(run):
        """One video, for a report: when, what kind, how long until the picture moved, what it is, how it was decoded,
        and what went wrong while it played: frames dropped (the box couldn't keep up decoding or drawing) or waits
        for more to arrive (the network, or Sofa converting it, couldn't keep up)."""
        w, h = run.get("width"), run.get("height")
        hw = run.get("hwdec-current")
        rate = run.get("video-bitrate")
        parts = ["%s %s" % (run.get("at", "?"), run.get("kind", "?")),
                 "picture after %s s" % run["started_after"] if run.get("started_after") is not None else "the picture never moved",
                 "%s%s%s" % (run.get("video-codec") or "video ?", " %sx%s" % (w, h) if w and h else "",
                             " %.3g fps" % run["container-fps"] if run.get("container-fps") else ""),
                 "decoded by %s" % ("the processor" if hw in (None, "", "no") else "the video chip (%s)" % hw),
                 # (how mpv puts the picture on the screen: "gpu" or "gpu-next" with the graphics chip; "wlshm", "sdl" or the
                 # like by the processor, which can't keep up with 1080p on a Pi 3. Left out when mpv didn't say.)
                 "drawn by %s%s" % (run["current-vo"], " (%s)" % run["current-gpu-context"] if run.get("current-gpu-context") else "")
                 if run.get("current-vo") else None,
                 "%.1f Mbit/s" % (rate / 1e6) if rate else "bit rate ?",
                 "audio %s" % (run.get("audio-codec-name") or "?"),
                 "dropped %d frames (%d by the decoder)%s" % ((run.get("frame-drop-count") or 0) + (run.get("decoder-frame-drop-count") or 0),
                                                              run.get("decoder-frame-drop-count") or 0,
                                                              ", %d late on the screen" % run["vo-delayed-frame-count"]
                                                              if run.get("vo-delayed-frame-count") else ""),
                 "waited for more %d time%s (%d s in all)" % (run.get("waits", 0), "" if run.get("waits") == 1 else "s", run.get("waited", 0)),
                 "played %d s" % run.get("played", 0)]
        return ", ".join(p for p in parts if p)

    def check_drops(self):
        """1080p the box can't keep up with: ask Sofa for 720p from now on (the setting can say otherwise)."""
        drops = (self.command("get_property", "frame-drop-count") or 0) + (self.command("get_property", "decoder-frame-drop-count") or 0)
        fps = float(self.command("get_property", "container-fps") or 25)
        if settings()["quality"] == "auto" and drops > fps * 90 * 0.03 and not settings()["learned_720"]:
            save_settings(learned_720=True)
            toast("Videos come as 720p on this box from now on: it couldn't keep up at 1080p.")

    def banner(self, at=0):
        """Live TV: the channel's banner, as on a TV (5 s): its number and name, what's on and what's next. At each
        new programme of an archive channel (not at the commercials between them) and when the channel changes."""
        p = self.payload or {}
        progs = p.get("programs") or []
        shows = [(i, x) for i, x in enumerate(progs) if not x.get("ad")]
        now = next((x for i, x in shows if i >= at), None) if at < len(progs) and not progs[at].get("ad") else None
        later = next((x for i, x in shows if i > at), None)
        name = lambda x: str(x.get("title") or "") + (" (%s)" % x["year"] if x.get("year") else "")
        b = {"number": str(p["number"]) if p.get("number") else None, "name": str(p.get("title") or "")}
        if now:
            b["now"] = name(now)
        elif progs:
            b["sub"] = "Commercials" + (", then " + name(later) if later else "")
        if now and later:
            b["next"] = name(later)
        self.osd(banner=b)

    def zap(self, step):
        """Live TV: the next channel up or down (Sofa's channel list came with it), its name on the screen."""
        p = self.payload or {}
        chans = p.get("channels") or []
        if not p.get("live") or len(chans) < 2:
            return False
        p["at"] = (int(p.get("at") or 0) + step) % len(chans)
        ch = chans[p["at"]]
        if ch.get("archive"):                               # an Internet Archive channel: what's on, from Sofa
            try:
                req = urllib.request.Request(rewrite(ch["url"], self.base), headers={"Cookie": self.cookie or "", "X-Sofa": "1"})
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=15) as r:
                    on = json.loads(r.read())
            except (OSError, ValueError):
                self.osd(toast="%s isn't available just now" % (ch.get("name") or "That channel"))
                return False
            self.command("set_property", "http-header-fields", "")      # (archive.org gets no Sofa cookie)
            self.command("loadfile", on["film"]["url"], "replace")
            for f in on.get("next") or []:
                self.command("loadfile", f["url"], "append")
            threading.Thread(target=self._seek_when_ready, args=(on.get("offset") or 0,), daemon=True).start()
            sub = on["film"]["title"] + (" (%s)" % on["film"]["year"] if on["film"].get("year") else "")
            p.update(title=ch.get("name"), number=ch.get("number"), banner_at=0,
                     programs=[{"title": f.get("title"), "year": f.get("year"), "ad": bool(f.get("ad"))}
                               for f in [on["film"]] + list(on.get("next") or [])])
            self.banner(0)
            self.status.update(title=ch.get("name"), sub=sub)
            return True
        self.command("set_property", "http-header-fields", self.sofa_headers().split(","))
        self.command("loadfile", rewrite(ch["url"], self.base), "replace")
        p.update(title=ch.get("name"), number=ch.get("number"), programs=[])
        self.osd(banner={"number": str(ch["number"]) if ch.get("number") else None, "name": str(ch.get("name") or ""),
                         "sub": str(ch.get("group") or "")})
        self.status.update(title=ch.get("name"), sub=ch.get("group") or "")
        return True

    # ---- the options menu while a video plays (Menu on a controller or remote): subtitles, sound track, speed and
    # volume, in mpv's own screen; while it's open the arrows, OK and Back are its (an mpv input section)
    MENU_KEYS = {"UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right", "ENTER": "ok", "KP_ENTER": "ok",
                 "ESC": "back", "BS": "back", "GO_BACK": "back", "F2": "back", "MENU": "back", "q": "back",
                 "PGUP": "up", "PGDWN": "down", "REWIND": "left", "FORWARD": "right"}
    SPEEDS = [0.75, 1.0, 1.25, 1.5, 2.0]

    def _tracks(self, kind):
        out = []
        for t in self.command("get_property", "track-list") or []:
            if t.get("type") == kind:
                name = t.get("title") or LANGS.get(str(t.get("lang") or "").lower()) or str(t.get("lang") or "").upper()
                out.append((t.get("id"), (name or "Track %s" % t.get("id")) + (" (forced)" if t.get("forced") else ""),
                            bool(t.get("selected"))))
        return out

    def menu_items(self):
        """[label, [(value, shown)], index of the current one, what it sets] for this video."""
        items = []
        subs = self._tracks("sub")
        if subs:
            opts = [("no", "Off")] + [(i, n) for i, n, _ in subs]
            items.append(["Subtitles", opts, next((k + 1 for k, (_, _, on) in enumerate(subs) if on), 0), "sid"])
        audio = self._tracks("audio")
        if len(audio) > 1:
            items.append(["Sound", [(i, n) for i, n, _ in audio], next((k for k, (_, _, on) in enumerate(audio) if on), 0), "aid"])
        if not (self.payload or {}).get("live"):
            speed = float(self.command("get_property", "speed") or 1)
            at = min(range(len(self.SPEEDS)), key=lambda k: abs(self.SPEEDS[k] - speed))
            items.append(["Speed", [(v, ("%g×" % v) if v != 1 else "Normal") for v in self.SPEEDS], at, "speed"])
        level, muted = volume_now()
        items.append(["Volume", [(None, "Sound off" if muted else "%d%%" % level if level is not None else "‹ ›")], 0, "volume"])
        items.append(["Close", [(None, "")], 0, "close"])
        return items

    def menu_toggle(self):
        if getattr(self, "menu", None):
            return self.menu_close()
        if not playing():
            return
        bindings = "\n".join("%s %s" % (key, key_command("menu-" + k)) for key, k in self.MENU_KEYS.items())
        self.command("define-section", "sofa-menu", bindings, "force")
        self.command("enable-section", "sofa-menu", "exclusive")
        self.menu = {"items": self.menu_items(), "at": 0, "used": steady()}
        self.menu_draw()
        threading.Thread(target=self._menu_idle, daemon=True).start()

    def _menu_idle(self):
        while getattr(self, "menu", None):
            time.sleep(1)
            m = self.menu
            if m and steady() - m["used"] > 12:
                self.menu_close()

    def menu_close(self):
        self.menu = None
        self.command("disable-section", "sofa-menu")
        self.osd(menu=False)

    def menu_draw(self):
        m = self.menu
        if not m:
            return
        rows = [{"label": label, "value": str(opts[at][1]) if opts else "", "on": k == m["at"],
                 "more": len(opts) > 1 or what == "volume"} for k, (label, opts, at, what) in enumerate(m["items"])]
        self.osd(menu={"title": "Options", "rows": rows, "hint": "Left and right change it   ·   Back closes"})

    def menu_key(self, k):
        m = getattr(self, "menu", None)
        if not m:
            return
        m["used"] = steady()
        item = m["items"][m["at"]]
        if k == "back":
            return self.menu_close()
        if k in ("up", "down"):
            m["at"] = (m["at"] + (1 if k == "down" else -1)) % len(m["items"])
        elif item[3] == "close":
            if k == "ok":
                return self.menu_close()
        elif item[3] == "volume":
            if k in ("left", "right", "ok"):
                level, muted = box_volume(-4 if k == "left" else 4)
                item[1] = [(None, "Sound off" if muted else "%d%%" % level if level is not None else "‹ ›")]
        elif k in ("left", "right", "ok"):
            item[2] = (item[2] + (-1 if k == "left" else 1)) % len(item[1])
            self.command("set_property", item[3], item[1][item[2]][0])
        self.menu_draw()

    def ok(self):
        """OK on the remote while playing: skip the intro when it's on, else pause/play."""
        t = self.position()
        m = self.marker(t) if t is not None else None
        if m:
            self.seek_to(m["end"])
        else:
            self.control({"cmd": "toggle"})

    def control(self, c):
        """The phone remote (through Sofa's page) and the page itself: pause, play, the line, skips, stop."""
        cmd, far = c.get("cmd"), self.far
        if cmd in ("toggle", "pause", "resume") and far and not far["sid"]:     # skipping far: how it goes on from there
            far["paused"] = not far["paused"] if cmd == "toggle" else cmd == "pause"
            self.status["paused"] = far["paused"]
        elif cmd == "toggle":
            self.command("cycle", "pause")
        elif cmd == "pause":
            self.command("set_property", "pause", True)
        elif cmd == "resume":
            self.command("set_property", "pause", False)
        elif cmd == "seek":
            self.seek_to(float(c.get("t") or 0))
        elif cmd == "skip":
            t = self.position() if self.can_convert_again() else None
            if t is None:
                self.command("seek", float(c.get("by") or 0), "relative")
            else:
                self.seek_to(t + float(c.get("by") or 0))
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


def screen_scale():
    """How big the box draws pages on this TV (the kiosk session says: 2 on 1080p, 4 on 4K; 1 on X11, where
    Chromium does it itself)."""
    try:
        return float(display_env_raw().get("SCALE") or 1)
    except ValueError:
        return 1.0


def display_env_raw():
    run_dir = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    out = {}
    try:
        with open(os.path.join(run_dir, "sofa-box-display"), encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                out[k] = v
    except OSError:
        pass
    return out


browser = boxos.Browser(on_message=page_message, scale=screen_scale) if os.environ.get("SOFA_BOX_DEVTOOLS", "9222") != "0" else None


def tv_picture():
    """What the TV shows now, for the check that Home really came back (Browser.wrong). Not asked while something
    that isn't Home has the TV (a video, a game) or the box sleeps: its screensaver may well be one colour."""
    if asleep["on"] or playing() or games.playing:
        return None
    return boxos.screen_picture(display_env())


if browser:
    browser.screen = tv_picture


def home_rests(on):
    """Home told that a game has the TV (or gave it back): it stops asking the box around while it can't be seen."""
    if browser and browser.connected():
        t = browser.tab_of("home")
        if t:
            try:
                browser.evaluate(t, "window.sofaBoxRest && sofaBoxRest(%s)" % ("true" if on else "false"))
            except OSError:
                pass


RESCUES = os.path.join(CONF_DIR, "screen-restarts.log")    # each time the TV's screen was started again by hand


def rescue(who):
    """The TV's screen and this helper started again: the way out that never needs the page (Home held for 4 seconds
    on a controller or a remote does it in the controller daemon; this is the phone's). Written down for the report."""
    line = "%s the TV's screen started again (%s)" % (time.strftime("%Y-%m-%d %H:%M:%S"), who)
    print(line, file=sys.stderr, flush=True)
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        with open(RESCUES, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    cmd = shlex_split(os.environ.get("SOFA_BOX_RESCUE", "")) or ["sudo", "-n", "systemctl", "restart", "sofa-box", "sofa-box-agent"]
    threading.Timer(0.8, lambda: run(cmd, 60)).start()      # (after the phone has its answer)
    return {"ok": True, "message": "The TV's screen is starting again. Give it half a minute."}


def rescues():
    """The last few times the TV's screen was started again by hand (the controller daemon writes them too)."""
    try:
        with open(RESCUES, encoding="utf-8") as f:
            return [line.strip() for line in f.read().splitlines()[-6:] if line.strip()]
    except OSError:
        return []
# A Pi 3's video chip decodes H.264 only; VP9 and AV1 (what YouTube and others send by default) its processor has to
# decode, and videos stutter. Its pages are told those two can't play, so the sites send H.264. (A Pi 5 has no H.264
# decoder at all, so it's left to choose.)
H264_ONLY = r"""(() => {
  const no = /\b(vp0?9|av01|av1)\b/i, nope = { supported: false, smooth: false, powerEfficient: false };
  for (const MS of [window.MediaSource, window.ManagedMediaSource, window.WebKitMediaSource]) {
    if (MS && MS.isTypeSupported) { const was = MS.isTypeSupported.bind(MS); MS.isTypeSupported = t => !no.test(t) && was(t); }
  }
  const play = HTMLMediaElement.prototype.canPlayType;
  HTMLMediaElement.prototype.canPlayType = function (t) { return no.test(t) ? "" : play.call(this, t); };
  const mc = navigator.mediaCapabilities;
  if (mc && mc.decodingInfo) {
    const was = mc.decodingInfo.bind(mc);
    mc.decodingInfo = c => no.test(((c && c.video) || {}).contentType || "") ? Promise.resolve(nope) : was(c);
  }
})();"""
if browser and slow_board():
    browser.page_script = H264_ONLY


# ---------------------------------------------------------------- asleep (the phone remote's power button)
# The box rests: what plays stops (its place kept), a game ends, and Home shows its screensaver (the time, the weather,
# the art of what you were watching, drifting so nothing burns into the TV). Any key, the phone, Home: awake again.
asleep = {"on": False, "at": 0}


def home_page(where):
    """Home in front, at `where` ("#/sleep", "#/")."""
    if browser and browser.connected():
        t = browser.tab_of("home")
        if t:
            browser.activate(t)
            browser.evaluate(t, "location.hash = %s" % json.dumps(where))
            return True
    go(where)
    return False


def box_sleep():
    player.stop(save=True, reason="sleep")
    if games.playing:
        games.stop("sleep")
    asleep.update(on=True, at=steady())
    home_page("#/sleep")


def box_wake():
    if asleep["on"]:
        asleep["on"] = False
        home_page("#/")
        return True
    return False


PAGE_NAMES = {"home": "Home", "settings": "Settings", "store": "App Store", "games": "Games", "files": "Files", "browser": "Browser",
              "sofa": "Where's your Sofa", "welcome": "the setup", "sleep": "asleep"}


def smooth_lines(stats):
    out = []
    for app, v in sorted(stats.items() if isinstance(stats, dict) else []):
        out.append("  %s: %d presses, %d slower than 0.1 s (slowest %.2f s); %d long tasks (%.1f s in all)"
                   % (app, v.get("presses", 0), v.get("slow", 0), v.get("worst", 0) / 1000, v.get("long", 0), v.get("long_ms", 0) / 1000))
        for page, p in sorted((v.get("pages") or {}).items(), key=lambda x: -x[1].get("presses", 0)):   # (each part of it)
            n, h = p.get("presses", 0), (p.get("hist") or []) + [0] * 5
            if not n:
                continue
            within = lambda k: max(0, n - sum(h[k:5]))     # noqa: E731  (the presses quicker than that bucket)
            line = "    %s: %d presses: %d within 0.05 s, %d within 0.1 s, %d within 0.25 s; slowest %.2f s" % (
                PAGE_NAMES.get(page, page) if app == "home" else "%s %s" % (app, page), n, within(0), within(1), within(2), p.get("worst", 0) / 1000)
            t = p.get("wait", 0) + p.get("code", 0) + p.get("draw", 0)
            if t:
                line += "; the slow ones' time: waiting for the page %d%%, the key's own code %d%%, drawing %d%%" % tuple(
                    round(100 * p.get(k, 0) / t) for k in ("wait", "code", "draw"))
            out.append(line)
            # moving the focus and OK apart: an arrow that's slow is the page drawing too much; a slow OK is what it opens
            kinds = ["%s: %d presses, %d slower than 0.1 s, slowest %s" % (
                label, p[k], p.get(k + "_slow", 0), "%.2f s" % (p[k + "_worst"] / 1000) if p.get(k + "_worst") else "under 0.05 s")
                for k, label in (("move", "moving"), ("ok", "OK")) if p.get(k)]
            if kinds:
                out.append("      " + "; ".join(kinds))
    return out


def too_slow(presses, slow):
    """The full look is too much for this board: of the last presses (enough of them to tell), a fifth or more took a
    tenth of a second or longer to show."""
    return presses >= 40 and slow >= presses * 0.2


def watch_web_game():
    """One of the box's own games in front, in the browser (Gloamwell and the rest): the controller daemon leaves it
    the triggers and Start (they're the game's: a skill, its menu), instead of the volume and the options."""
    web, path = None, GAME_FILE + ".web"
    while True:
        time.sleep(0.5)
        now = bool(browser and browser.connected() and "/box/games/" in browser.front_url() and not asleep["on"])
        if now != web:
            web = now
            try:
                if now:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(browser.front_url().split("/box/games/", 1)[1].split("/", 1)[0])
                elif os.path.exists(path):
                    os.remove(path)
            except OSError:
                web = None                                  # (tried again next time)


def leave_after():
    """How long an app stays open out of sight before it's closed, in seconds: half a minute on a small box (the light
    look: a Pi 3, or 1 GB), five minutes on a bigger one. (SOFA_BOX_LEAVE_AFTER sets it; 0 leaves apps open.)"""
    asked = os.environ.get("SOFA_BOX_LEAVE_AFTER")
    if asked not in (None, ""):
        try:
            return max(0.0, float(asked))
        except ValueError:
            pass
    return 30.0 if light() else 300.0


_now = {"at": -1e9, "value": None, "said": None}


def now_line():
    """A new track in an app behind what's in front (a web page, Sofa, a game in the browser): a moment's word over
    it, as a TV's own banner (the mini player's pop-up). Not over a video, and not when the box rests."""
    if not (browser and browser.connected()) or asleep["on"] or playing():
        return
    v = now_playing()
    title = v and v.get("playing") and not v.get("front") and v.get("title")
    if not title:
        return
    said = (v.get("app"), title, v.get("artist"))
    if said != _now["said"]:
        first = _now["said"] is None or _now["said"][0] != said[0]
        _now["said"] = said
        if not first or browser.front_app() != "home":     # (Home shows it itself)
            browser.hud("\u266a " + title + (" \u00b7 " + v["artist"] if v.get("artist") else ""))
_now_lock = threading.Lock()


def now_playing(fresh=False):
    """The mini player's: what the app that plays music says it's playing (boxos.Browser.now_playing), looked at
    once every two seconds at most, however many ask (Home, phones)."""
    if not (browser and browser.connected()):
        return None
    with _now_lock:
        if fresh or steady() - _now["at"] > 2:
            try:
                _now["value"] = browser.now_playing()
            except Exception:                               # (a page that went away while it was asked)
                _now["value"] = None
            _now["at"] = steady()
        v = _now["value"]
    if not v:
        return None
    a = apps.get(v.get("app")) or {}
    return dict(v, name=a.get("name") or v.get("app") or "", color=a.get("color") or "")


def music(act, target=None):
    """A button of the mini player: play, pause, next, previous in the app that plays, or open it."""
    v = now_playing(fresh=True)
    if not v or (target and v.get("target") != target):
        raise ValueError("Nothing's playing in an app now.")
    if act == "open":
        browser.activate(v["target"])
        return {"ok": True}
    done = browser.music(v["target"], act)
    _now["at"] = -1e9                                        # (the next look is a fresh one)
    return {"ok": True, "done": done}


def low_memory_mb():
    """Below this much free memory the box is short of it: a tenth of its memory, 100 MB at least (SOFA_BOX_LOW_MB)."""
    try:
        return float(os.environ["SOFA_BOX_LOW_MB"])
    except (KeyError, ValueError):
        return max(100, board()["memory_mb"] // 10)


LOW_MEMORY = collections.deque(maxlen=12)                  # when memory ran low, and what was done (a report says)
_low = {"said": -1e9}


def memory_check(now=None):
    """Short of memory: the apps out of sight behind Home close now, not after their half minute (never Home, Sofa, the
    page in front or one that plays). Said once a minute at most: the free memory, who holds it, what was closed."""
    now = now or time.time()
    free = boxos.available_mb()
    if free is None or free >= low_memory_mb():
        return None
    closed = browser.tidy(0, now=now) if browser and browser.connected() else []      # (out of sight at all: closed)
    if not closed and steady() - _low["said"] < 60:
        return None
    _low["said"] = steady()
    users = ", ".join("%s %d MB" % (g, mb) for g, mb, _n in boxos.memory_users()[:4])
    line = "%s %d MB free%s%s" % (time.strftime("%H:%M:%S"), free, "; closed " + ", ".join(c["app"] for c in closed) if closed else "",
                                  " (%s)" % users if users else "")
    LOW_MEMORY.append(line)
    print("Memory low: " + line, flush=True)
    return line


def watch_apps():
    """Back on Home, the apps behind it give the box back: closed once they've been out of sight for a while, unless
    they're playing something you can hear (boxos.Browser.tidy), and at once when the box is short of memory
    (memory_check). Each one closed is a line in the journal and in a report, with the memory that came back. And
    what the agent itself freed goes back to the box (boxos.give_back)."""
    while True:
        time.sleep(5)
        try:
            now_line()
        except Exception:
            pass
        boxos.give_back()
        try:
            memory_check()
        except Exception as exc:
            print("Looking at the memory: %r" % exc, flush=True)
        try:
            grace = leave_after()
            if not grace or not (browser and browser.connected()):
                continue
            for c in browser.tidy(grace):
                print("Closed behind Home: %s (%d s out of sight)%s" % (
                    c["app"], c["left"], "" if c["after"] is None or c["before"] is None
                    else "; memory free %d to %d MB" % (c["before"], c["after"])), flush=True)
        except Exception as exc:                            # (the next look tries again)
            print("Closing apps behind Home: %r" % exc, flush=True)


def watch_smoothness():
    """On a board that has the full look by itself (Automatic): Home and Sofa measured as they're used, and the light
    look chosen when they answer the remote slowly, as the player chooses 720p when 1080p drops frames."""
    seen, presses, slow = {}, 0, 0
    while True:
        time.sleep(120)
        s = settings()
        if s.get("performance") != "auto" or light() or not (browser and browser.connected()) or playing():
            seen, presses, slow = {}, 0, 0
            continue
        try:
            stats = browser.smoothness()
        except OSError:
            continue
        for app in ("home", "sofa"):
            v, was = stats.get(app) or {}, seen.get(app) or {}
            dp, ds = v.get("presses", 0) - was.get("presses", 0), v.get("slow", 0) - was.get("slow", 0)
            if dp < 0:                                      # (the page started again: its counts did too)
                dp, ds = v.get("presses", 0), v.get("slow", 0)
            presses, slow = presses + max(dp, 0), slow + max(ds, 0)
            seen[app] = v
        if too_slow(presses, slow):
            save_settings(learned_lite=True)
            print("Smoothness: %d of %d presses took 0.1 s or more: the light look from now on" % (slow, presses),
                  file=sys.stderr, flush=True)
            toast("The box uses its lighter look from now on: it answers quicker on this board. Settings → Performance "
                  "changes it.")
            seen, presses, slow = {}, 0, 0
        elif presses >= 400:                                # (a long while of presses: only the recent ones count)
            presses, slow = presses // 2, slow // 2


power = {"note": None, "shown": False}                       # (watch_power; Home shows the note once a start)


def power_note(out, board_model=""):
    """What the Pi's own record (vcgencmd get_throttled, "throttled=0x50005") says, for Home and Settings → Help: None
    when it can't be read, kind "ok", "power" (under-voltage now or since the box started: bits 0 and 16), or "heat"
    (the soft temperature limit, bits 3 and 19; or held back and slowed down, bits 1, 2, 17 and 18, with power enough:
    under-voltage does that too), with what to do about it."""
    try:
        bits = int(str(out).strip().split("=")[-1], 16)
    except ValueError:
        return None
    short = bool(bits & 0x10001)
    hot = bool(bits & 0x80008) or (not short and bool(bits & 0x60006))
    note = {"kind": "power" if short else "heat" if hot else "ok", "bits": "0x%x" % bits}
    m = re.search(r"Raspberry Pi (\d)", board_model or "")
    supply = {"3": "its official 2.5 A power supply", "4": "its official 3 A USB-C power supply",
              "5": "its official 27 W (5 A) USB-C power supply"}.get(m.group(1) if m else "",
                                                                       "its official power supply")
    air = "Leave air around it: out of a closed cabinet and not pressed against the TV. A case with a heat sink or a fan helps."
    if short:
        note.update(title="The box is short of power",
                    text="It can freeze or restart by itself. Plug it into the wall with %s and a short cable: a phone "
                         "charger or the TV's USB socket isn't enough.%s" % (supply, (" It got hot too. " + air) if hot else ""))
    elif hot:
        note.update(title="The box got hot and slowed itself down", text=air)
    return note


def power_words(note):
    """The Pi's record of power and heat in plain words, for a report's first lines (the number is further down, with
    the checks): what happened, whether it's still happening, and what to do."""
    if not note:
        return "not read (not a Raspberry Pi, or the box has only just started)"
    bits, said = int(note["bits"], 16), []
    for now, since, what in ((0x1, 0x10000, "short of power (under-voltage)"), (0x4, 0x40000, "slowed down by the Pi itself (throttled)"),
                             (0x2, 0x20000, "its processor's speed capped"), (0x8, 0x80000, "at its soft temperature limit")):
        if bits & now:
            said.append(what + " right now")
        elif bits & since:
            said.append(what + " since it started, not right now")
    if not said:
        return "enough all along, and never held back, since the box started"
    return "%s (%s). %s. %s" % ("; ".join(said), note["bits"], note.get("title", ""), note.get("text", ""))


def watch_power():
    """The Pi's own record of power and heat (vcgencmd get_throttled), read every minute. Home says so once a start: a
    calm note, until you leave Home (power_note); Settings → Help says it all along."""
    time.sleep(10)
    while True:
        code, out = run(["vcgencmd", "get_throttled"], 5)
        if code != 0:
            return                                          # (not a Raspberry Pi)
        note = power_note(out, model())
        if note:
            was = (power["note"] or {}).get("kind")
            power["note"] = note
            if note["kind"] != "ok" and note["kind"] != was:
                print("Power: %s (%s)" % (note["title"], out.strip()), file=sys.stderr, flush=True)
        time.sleep(60 if settings()["welcomed"] else 15)    # (at the setup, sooner: its screens say so, see setup_state)


def go_home():
    """The Home key, from anywhere: the box's home screen in front (a game that's open ends; asleep, it wakes)."""
    if box_wake():
        return True
    if games.playing:
        games.stop("home")
    if browser and browser.connected():
        return browser.home()
    go("#/")
    return False


def open_app(app_id=None, url=None, hash_=None):
    """An app's tab (or the browser's) brought forward; `hash_` takes Sofa to a page in it. Without the
    browser connection (a preview, tests), the address goes back to the page, which opens it itself."""
    asleep["on"] = False
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
            # drawn at once, before the tab comes forward: Resume on Home shows the player's start card, not the page
            # Sofa was on
            browser.evaluate(existing, "location.hash = %s; window.sofaRouteNow && sofaRouteNow()" % json.dumps(hash_))
        return {"ok": True, "target": browser.open(app_id, target_url, ua)}
    return {"ok": True, "url": target_url}


# ---------------------------------------------------------------- the weather on Home

WEATHER_URL = os.environ.get("SOFA_BOX_WEATHER") or "https://api.met.no/weatherapi/locationforecast/2.0/compact"
PLACES_URL = os.environ.get("SOFA_BOX_PLACES") or "https://nominatim.openstreetmap.org/search"
WEB_UA = "SofaBox/%s github.com/krintoxi/sofa" % OS_VERSION   # both services ask to be told who's asking
FAHRENHEIT = re.compile(r"^(America/(New_York|Chicago|Denver|Los_Angeles|Phoenix|Anchorage|Juneau|Sitka|Nome|Adak|Yakutat|"
                        r"Metlakatla|Detroit|Boise|Menominee|Indiana/\w+|Kentucky/\w+|North_Dakota/\w+|Puerto_Rico|Nassau|"
                        r"Belize|Cayman)|Pacific/(Honolulu|Guam|Saipan|Pago_Pago)|US/\w+)$")
_weather = {"at": 0, "key": None, "series": None}


def zone_place(tz):
    """The time zone's own city and where it is (from the system's zone list), for the weather until one is picked."""
    for tab in ("/usr/share/zoneinfo/zone1970.tab", "/usr/share/zoneinfo/zone.tab"):
        try:
            with open(tab, encoding="utf-8") as f:
                for line in f:
                    cols = line.rstrip("\n").split("\t")
                    if len(cols) < 3 or cols[2] != tz:
                        continue
                    m = re.match(r"^([+-])(\d\d)(\d\d)(\d\d)?([+-])(\d\d\d)(\d\d)(\d\d)?$", cols[1])
                    if not m:
                        return None
                    lat = (int(m[2]) + int(m[3]) / 60 + int(m[4] or 0) / 3600) * (-1 if m[1] == "-" else 1)
                    lon = (int(m[6]) + int(m[7]) / 60 + int(m[8] or 0) / 3600) * (-1 if m[5] == "-" else 1)
                    return {"name": tz.rsplit("/", 1)[-1].replace("_", " "), "lat": round(lat, 2), "lon": round(lon, 2)}
        except OSError:
            continue
    return None


def weather(now=None):
    """Home's weather: now, the next 24 hours' high and low, and the next few hours, from MET Norway (api.met.no:
    free, no key, for anyone). It's asked at most every 30 minutes, for the place rounded to about a kilometre: the
    one picked in Settings, else the time zone's city."""
    s, now = settings(), now or time.time()
    if s.get("weather") == "off":
        return {"ok": False, "off": True}
    tz = current_timezone()
    place = s.get("weather_place") or zone_place(tz)
    if not place:
        return {"ok": False, "message": "Pick a place for the weather in Settings."}
    key = (round(place["lat"], 2), round(place["lon"], 2))
    if _weather["key"] != key or now - _weather["at"] > 1800:
        try:
            req = urllib.request.Request(WEATHER_URL + "?" + urllib.parse.urlencode({"lat": "%.2f" % key[0], "lon": "%.2f" % key[1]}),
                                         headers={"User-Agent": WEB_UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                series = json.loads(r.read())["properties"]["timeseries"]
            _weather.update(at=now, key=key, series=series)
        except (OSError, ValueError, KeyError, TypeError):
            if _weather["key"] != key or not _weather["series"]:
                return {"ok": False, "message": "No weather just now."}
            _weather["at"] = now - 1500                           # the last one still, and again in 5 minutes
    f = s.get("weather_units") == "f" or (s.get("weather_units", "auto") == "auto" and bool(FAHRENHEIT.match(tz)))

    def deg(c):
        return int(round(c * 9 / 5 + 32 if f else c))

    def symbol(d):
        return ((d.get("next_1_hours") or d.get("next_6_hours") or {}).get("summary") or {}).get("symbol_code", "")
    rows = []
    for x in _weather["series"]:
        try:
            rows.append((__import__("calendar").timegm(time.strptime(x["time"], "%Y-%m-%dT%H:%M:%SZ")), x["data"]))
        except (KeyError, ValueError):
            continue
    rows = [r for r in rows if r[0] > now - 3600]
    if not rows:
        return {"ok": False, "message": "No weather just now."}
    day = [d["instant"]["details"]["air_temperature"] for t, d in rows if t < now + 86400]
    return {"ok": True, "place": place["name"], "units": "F" if f else "C", "temp": deg(rows[0][1]["instant"]["details"]["air_temperature"]),
            "symbol": symbol(rows[0][1]), "high": deg(max(day)), "low": deg(min(day)),
            "hours": [{"t": t, "temp": deg(d["instant"]["details"]["air_temperature"]), "symbol": symbol(d)}
                      for t, d in rows[1:13:3] if symbol(d)][:4]}


def find_places(q):
    """Settings -> Weather: towns and cities by name (OpenStreetMap's Nominatim), only while someone looks one up."""
    q = re.sub(r"\s+", " ", str(q or "")).strip()[:80]
    if len(q) < 2:
        return {"ok": True, "places": []}
    req = urllib.request.Request(PLACES_URL + "?" + urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 6, "featureType": "settlement"}),
                                 headers={"User-Agent": WEB_UA, "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            found = json.loads(r.read())
    except (OSError, ValueError):
        return {"ok": False, "message": "Couldn't look that up just now.", "places": []}
    places = []
    for x in found if isinstance(found, list) else []:
        if x.get("addresstype") in ("county", "state", "region", "country", "postcode"):
            continue
        try:
            parts = [p.strip() for p in str(x.get("display_name") or "").split(",") if p.strip()]
            name = str(x.get("name") or (parts[:1] or [q])[0])[:60]
            places.append({"name": name, "where": ", ".join(p for p in parts[1:] if p != name)[-80:],
                           "lat": round(float(x["lat"]), 2), "lon": round(float(x["lon"]), 2)})
        except (KeyError, TypeError, ValueError):
            continue
    return {"ok": True, "places": places}


def weather_place(v):
    """A place from Settings (a name and where it is), or None for the time zone's city again."""
    if not isinstance(v, dict):
        return None
    try:
        lat, lon = float(v["lat"]), float(v["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"name": re.sub(r"[^\w '’&.,()-]", "", str(v.get("name") or ""))[:60].strip() or "Here", "lat": round(lat, 2), "lon": round(lon, 2)}


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
            try:                                         # a box's Sofa from before: its USB drives join by themselves too
                with open(cfg, encoding="utf-8") as f:
                    conf = json.load(f)
                if "auto_drives" not in conf:
                    conf["auto_drives"] = True
                    with open(cfg, "w", encoding="utf-8") as f:
                        json.dump(conf, f, indent=1)
            except (OSError, ValueError):
                pass
            return
        os.makedirs(self.data, exist_ok=True)
        lib = os.path.expanduser("~/Videos/Sofa Library")
        user = os.path.basename(os.path.expanduser("~"))
        folders = {"shows": "Shows", "movies": "Movies", "music": "Music", "musicvideos": "Music Videos", "inbox": "Inbox",
                   "review": "Needs Review", "adult": "Adult", "originals": "Converted Originals"}
        conf = {k: os.path.join(lib, v) for k, v in folders.items()}
        conf.update(name=(settings().get("boot_text") or "Sofa Box"), port=self.PORT, dlna=False, guest_access=False,
                    drive_folders=["/media/" + user, "/media"], auto_drives=True, auto_convert=False, previews=False, trickplay=False,
                    detect_intros=False, machine_test=False,
                    # (no channel lists of its own: whoever owns the box adds the ones they want, from Live TV. A box
                    # that came with other people's channels on it is what the "fully loaded box" cases were about.)
                    live_playlists=[])
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
                ionice = ["ionice", "-c", "3"] if shutil_which("ionice") else []       # behind the app in front, always
                self.proc = subprocess.Popen(ionice + [sys.executable, os.path.join(code, "sofa.py"), "serve"], cwd=code, stdin=subprocess.DEVNULL,
                                             stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, SOFA_DATA=self.data),
                                             preexec_fn=lambda: os.nice(10))
        end = steady() + wait
        while steady() < end:
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


    def api(self, path, body=None, timeout=20):
        """The box's own Sofa's API, signed in as the box's own account (its admin), from this box (home)."""
        cookie = self.sign_in()
        if not cookie:
            raise ValueError("The box can't sign in to its own Sofa (someone else set it up: change it in Sofa's Server page).")
        req = urllib.request.Request(self.url() + path, data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST",
                                     headers={"Content-Type": "application/json", "X-Sofa": "1", "Cookie": "sofa_session=" + cookie})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                said = json.loads(e.read()).get("error")
            except ValueError:
                said = None
            raise ValueError(said or "Sofa on the box said %d" % e.code)

    def configured(self):
        return os.path.exists(os.path.join(self.data, "config.json"))

    def public(self):
        try:
            with open(os.path.join(self.data, "config.json"), encoding="utf-8") as f:
                return json.load(f).get("remote") == "public"
        except (OSError, ValueError):
            return False


local_sofa = LocalSofa()


# ---------------------------------------------------------------- Sofa on this box, from anywhere (Settings)
# The box's own Sofa opened to the internet, the way Sofa does it on any computer (its Server -> Internet): an address
# (a free DuckDNS name, or a domain), the router sending ports 443 and 80 to the box (UPnP), a Let's Encrypt certificate,
# then the internet let in, and a look from outside. Here in a few presses on the TV; the box drives its Sofa itself.
thisbox_net = {"step": None, "error": None, "busy": False}


def thisbox_status():
    if not local_sofa.available():
        return {"available": False}
    if not local_sofa.configured() or not local_sofa.answering():
        return {"available": True, "running": False, "public": local_sofa.public(), "progress": dict(thisbox_net)}
    try:
        n = local_sofa.api("/api/admin/internet")
    except (OSError, ValueError) as exc:
        return {"available": True, "running": True, "error": str(exc), "progress": dict(thisbox_net)}
    with open(os.path.join(local_sofa.data, "config.json"), encoding="utf-8") as f:
        port = json.load(f).get("port") or LocalSofa.PORT
    return {"available": True, "running": True, "internet": n, "address": local_address(), "port": port,
            "https_port": (n.get("https") or {}).get("port") or 8443, "progress": dict(thisbox_net)}


def thisbox_open(domain, token):
    """Every step, one after the other, saying which it's on (the TV shows it)."""
    def step(text):
        thisbox_net.update(step=text)

    def wait(check, seconds):
        end = steady() + seconds
        while steady() < end:
            n = local_sofa.api("/api/admin/internet")
            if check(n):
                return n
            time.sleep(3)
        return local_sofa.api("/api/admin/internet")
    thisbox_net.update(busy=True, error=None)
    try:
        step("Starting Sofa on the box")
        if not local_sofa.ensure(60):
            raise ValueError("Sofa on the box didn't start.")
        step("Saving the address")
        change = {"https": "letsencrypt", "domain": domain, "upnp": True, "open_ports": True}
        if token:
            change["duckdns_token"] = token
        local_sofa.api("/api/admin/internet", change)
        step("Asking the router to send ports 443 and 80 to the box")
        n = wait(lambda n: (n.get("upnp") or {}).get("at"), 30)
        step("Getting the certificate from Let's Encrypt (a minute or two)")
        local_sofa.api("/api/admin/internet", {"get_certificate": True})
        time.sleep(3)
        n = wait(lambda n: not (n.get("https") or {}).get("busy"), 240)
        h = n.get("https") or {}
        if h.get("error") or not h.get("trusted"):
            raise ValueError(h.get("error") or "Let's Encrypt didn't give a certificate. Check the address and the router (below).")
        step("Letting the internet in")
        local_sofa.api("/api/admin/internet", {"remote": "public"})
        step("Checking from outside")
        local_sofa.api("/api/admin/internet", {"check_outside": True})
        wait(lambda n: (n.get("outside") or {}).get("at") and not (n.get("outside") or {}).get("busy"), 60)
        step(None)
    except (OSError, ValueError) as exc:
        thisbox_net.update(error=str(exc)[:300], step=None)
    finally:
        thisbox_net["busy"] = False


def thisbox_action(data):
    a = data.get("action")
    if a == "open":
        domain = str(data.get("domain") or "").strip().lower().rstrip(".")
        if not re.match(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$", domain):
            return {"ok": False, "message": "Type the address: yourname.duckdns.org, or your own domain."}
        if domain.endswith(".duckdns.org") and not data.get("token") and not (thisbox_status().get("internet") or {}).get("duckdns_token"):
            return {"ok": False, "message": "A DuckDNS address needs its token (on duckdns.org, after you sign in)."}
        if thisbox_net["busy"]:
            return {"ok": False, "message": "It's on its way already."}
        threading.Thread(target=thisbox_open, args=(domain, str(data.get("token") or "").strip()), daemon=True).start()
        return {"ok": True, "message": "Opening Sofa on the box to the internet…"}
    if a == "check":
        local_sofa.api("/api/admin/internet", {"check_outside": True})
        return {"ok": True, "message": "Checking from outside…"}
    if a == "close":
        local_sofa.api("/api/admin/internet", {"remote": "home", "upnp": False})
        return {"ok": True, "message": "Sofa on the box is home only again."}
    return {"ok": False, "message": "Unknown action."}
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
        home = [{"url": u, "name": v["name"], "kind": "sofa", "where": "home", "id": boxservers.server_id("sofa", u),
                 "host": v.get("host"), "machine": v.get("machine"), "library": v.get("library")}
                for u, v in sorted(found.items()) if u.rstrip("/") not in added and v.get("id") not in added_ids]
        by_id = {v["id"]: v for v in found.values() if v.get("id")}
        by_url = dict(found)
    for x in st["servers"]:                                  # the ones added, with what was found about them
        seen = by_id.get(x.get("sofa_id")) or by_url.get((x.get("url") or "").rstrip("/"))
        if seen and x.get("where") == "home":
            x.update({k: seen.get(k) for k in ("host", "machine", "library") if seen.get(k)})
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
    servers.opened(entry["id"])
    app = "sofa" if entry["kind"] == "sofa" else "srv-" + entry["id"]
    if browser and browser.connected():
        existing = browser.tab_of(app)
        if existing and app == "sofa":
            here = urllib.parse.urlsplit((browser.tabs.get(existing) or {}).get("url") or "").netloc
            if here.split(":")[0] != "%s.localhost" % entry["id"]:      # another server's Sofa: this one instead
                browser.navigate(existing, url)
            elif hash_:
                browser.evaluate(existing, "location.hash = %s; window.sofaRouteNow && sofaRouteNow()" % json.dumps(hash_))
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
    if _continue["key"] == entry["id"] and steady() - _continue["at"] < 20:
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
            # Resume plays at once on a Sofa that knows #/play/ (1.5.1); an older one opens the title's page, as before
            try:
                plays = tuple(int(x) for x in str(get("/api/info").get("version") or "0").split(".")[:3]) >= (1, 5, 1)
            except ValueError:
                plays = False
            by = {}
            for sh in lib.get("shows") or []:
                for se in sh.get("seasons") or []:
                    for ep in se.get("episodes") or []:
                        by[ep["id"]] = {"title": sh["name"], "sub": "S%s E%s · %s" % (ep.get("s"), ep.get("e"), ep.get("title") or ""),
                                        "art": ep.get("thumb") or sh.get("backdrop") or sh.get("poster"),
                                        "backdrop": sh.get("backdrop") or ep.get("thumb"), "hash": "#/show/" + urllib.parse.quote(sh["id"], safe=""),
                                        "play": "#/play/" + urllib.parse.quote(ep["id"], safe="")}
            for m in lib.get("movies") or []:
                by[m["id"]] = {"title": m["title"], "sub": str(m.get("year") or ""), "art": m.get("backdrop") or m.get("poster"),
                               "backdrop": m.get("backdrop") or m.get("poster"), "hash": "#/movie/" + urllib.parse.quote(m["id"], safe=""),
                               "play": "#/play/" + urllib.parse.quote(m["id"], safe="")}
            if not plays:
                for x in by.values():
                    x.pop("play", None)
            items = [dict(by[i], id=i, pct=round(100 * p["t"] / p["d"])) for i, p in
                     sorted(prog.items(), key=lambda x: -(x[1].get("at") or 0))
                     if i in by and not p.get("done") and p.get("d") and 30 < p["t"] < p["d"] - 30][:12]
            out.update(signedIn=True, user=s["user"]["name"], items=items)
    except Exception:
        out["found"] = False
    _continue.update(at=steady(), key=entry["id"], value=out)
    return out


def scan_others():
    if steady() - others_found["at"] > 20:
        others_found["at"] = steady()
        try:
            others_found["list"] = boxservers.find_others()
        except OSError:
            pass
    return others_found["list"]


# ---------------------------------------------------------------- games that run on the box itself (Games)
# Open-source games from Debian (games/games.json, "native"): installed when asked, by the box's root helper and only
# with the packages the list names, then played offline, full screen over the home screen. While one runs, the
# controller daemon (sofa-box-input.py) leaves the controller to the game ("pad": the game reads it itself), or works
# it as the list says ("controls": keys and a mouse, the same on every controller); holding Home for a second ends it.
GAME_FILE = os.environ.get("SOFA_BOX_GAME_FILE") or os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid(), "sofa-box-game")
GAME_DIRS = [d for d in (os.environ.get("SOFA_BOX_GAMES_BIN"),) if d] or ["/usr/games", "/usr/bin", "/usr/local/games"]
GAME_DATA = os.environ.get("SOFA_BOX_GAME_DATA") or os.path.join(os.path.expanduser("~"), ".local", "share", "sofa-box", "games")
PAD_KINDS = {"xbox": "Xbox", "playstation": "PlayStation", "nintendo": "Nintendo", "8bitdo": "8BitDo", "generic": "controller"}


def _apt_why(out):
    """What went wrong installing a game, in a few words."""
    low = out.lower()
    if "temporary failure resolving" in low or "could not resolve" in low or "network is unreachable" in low \
            or "unable to resolve host" in low:                 # (the last: wget, a game that downloads its maps)
        return "The box couldn't reach the internet to download it. Check the Wi-Fi and try again."
    if "hash mismatch" in low:
        return "What it downloaded didn't check out, so it wasn't kept. Try again later."
    if "no space left" in low or "not enough free space" in low:
        return "There isn't room on the box's card for it."
    if "could not get lock" in low or "unable to acquire the dpkg frontend lock" in low:
        return "The box is busy updating. Try again in a few minutes."
    errs = [line[3:].strip() for line in out.splitlines() if line.startswith("E: ")]
    return (errs[-1] if errs else (out.strip().splitlines() or ["it stopped"])[-1])[:200]


class Games:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc, self.playing, self.started, self.ending, self.job = None, None, 0, None, None
        self.pads, self.pads_at = [], 0
        self._list, self._mtime = None, None

    def catalog(self):
        path = os.path.join(HERE, "games", "games.json")
        m = os.path.getmtime(path)
        if self._list is None or m != self._mtime:
            with open(path, encoding="utf-8") as f:
                self._list, self._mtime = json.load(f), m
        return self._list

    def native(self, gid):
        g = next((g for g in self.catalog().get("native", []) if g["id"] == gid), None)
        if not g:
            raise ValueError("That isn't a game the box has.")
        return g

    @staticmethod
    def binary(g):
        """The game's program, when it's on the box. With "data" (beside the program; AssaultCube's maps, which its
        package downloads as it installs), only once that's there too: a download that failed isn't a game."""
        for name in g["run"]:
            for d in GAME_DIRS:
                p = os.path.join(d, name)
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    if g.get("data") and not os.path.exists(os.path.normpath(os.path.join(d, g["data"]))):
                        return None
                    return p
        return None

    @staticmethod
    def screen(g):
        """How big a 3D game draws, (width, height, the TV's height): on a Pi 3 as small as its list says
        ("pi3_height"), and the TV scales it up; at most 1080p on a newer board; never more than the TV."""
        tv = board()["tv_height"] or 1080
        h = min(g["pi3_height"] if slow_board() else 1080, tv)
        return h * 16 // 9, h, tv            # (1024×576, 1280×720, 1920×1080: sizes XWayland can give a game)

    @staticmethod
    def fits(g):
        gen = board()["gen"]
        return gen == 0 or gen >= g.get("pi", 3)        # (not a Raspberry Pi: up to it)

    def pads_now(self):
        """The controllers connected now (the controller daemon says, when they come and go)."""
        return list(self.pads) if steady() - self.pads_at < 90 else []

    def listing(self):
        native = []
        for g in self.catalog().get("native", []):
            d = {k: g.get(k) for k in ("id", "name", "icon", "emoji", "color", "about", "note", "mb", "pi", "players", "added")}
            d.update(installed=self.binary(g) is not None, fits=self.fits(g),
                     mouse=g["controls"] in ("pointer", "wesnoth"), playing=self.playing == g["id"])
            native.append(d)
        try:
            free = shutil.disk_usage("/").free // 2**20
        except OSError:
            free = None
        with self.lock:
            job = dict(self.job) if self.job else None
        return {"games": self.catalog()["games"], "native": native, "job": job, "playing": self.playing,
                "pads": self.pads_now(), "free_mb": free, "board": board()["gen"]}

    def change(self, gid, action):
        """Install or remove a game, in the background (a few minutes: it's downloaded)."""
        g = self.native(gid)
        if action not in ("install", "remove"):
            raise ValueError("Install or remove.")
        with self.lock:
            if self.job and self.job["state"] == "working":
                raise ValueError("One game at a time: %s is on its way." % self.native(self.job["id"])["name"])
            if self.playing == gid:
                raise ValueError("Close %s first." % g["name"])
            if action == "install":
                if not self.fits(g):
                    raise ValueError("%s needs a Raspberry Pi %d or newer." % (g["name"], g["pi"]))
                free = shutil.disk_usage("/").free // 2**20
                if free < g["mb"] * 1.5 + 400:
                    raise ValueError("There isn't room for %s: it needs about %d MB, and the box has %d MB free."
                                     % (g["name"], g["mb"], free))
            self.job = {"id": gid, "action": action, "state": "working", "at": int(time.time()), "error": None}
        threading.Thread(target=self._change, args=(g, action), daemon=True, name="game-" + action).start()
        return dict(self.job)

    def _change(self, g, action):
        helper = os.environ.get("SOFA_BOX_GAMES_HELPER")       # (tests: a stand-in for apt)
        cmd = [helper] if helper else ["sudo", "-n", os.path.join(HERE, "sofa-box"), "games"]
        code, out = run(cmd + [action, g["id"]], 3600)
        ok = code == 0 and (self.binary(g) is not None) == (action == "install")
        with self.lock:
            self.job.update(state="done" if ok else "failed", error=None if ok else _apt_why(out))
        print("Game %s %s: %s" % (action, g["id"], "done" if ok else out.replace("\n", " | ")[-400:]), file=sys.stderr, flush=True)
        if ok:
            toast("%s is ready: it's in Games." % g["name"] if action == "install" else "%s is off the box." % g["name"])
        else:
            toast("%s couldn't be %s. %s" % (g["name"], "installed" if action == "install" else "removed", self.job["error"]))

    @staticmethod
    def _world_mt(path, want, only_missing=False):
        """A Luanti settings file ("key = value" lines) with these values: set where they're missing or blank (or
        always, unless only_missing), the rest of it as it was."""
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        have = {}
        for i, line in enumerate(lines):
            k, eq, v = line.partition("=")
            if eq:
                have[k.strip()] = (i, v.strip())
        for k, v in want.items():
            if k in have and (only_missing or have[k][1] == v) and have[k][1]:
                continue
            if k in have:
                lines[have[k][0]] = "%s = %s" % (k, v)
            else:
                lines.append("%s = %s" % (k, v))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(path + ".tmp", path)

    def _setup(self, g):
        """A game's own settings the first time (its controller, the screen, a lighter look on a Pi 3), and what it
        needs to start straight in (Luanti: a world, no menu)."""
        slow = slow_board()
        if g.get("setup") == "luanti":
            base = os.path.join(GAME_DATA, "luanti")
            world = os.path.join(base, "worlds", "Sofa Box")
            os.makedirs(world, exist_ok=True)
            mt = os.path.join(world, "world.mt")
            self._world_mt(mt, {"gameid": "minetest"})            # (its game, always; a world's storage, only when new)
            self._world_mt(mt, {"backend": "sqlite3", "player_backend": "sqlite3", "auth_backend": "sqlite3",
                                "mod_storage_backend": "sqlite3"}, only_missing=True)
            conf = os.path.join(base, "luanti.conf")              # (the box works the controller: Luanti's own is off)
            self._world_mt(conf, {"fullscreen": "true", "enable_joysticks": "false", "viewing_range": "60" if slow else "160",
                                  "enable_clouds": "false" if slow else "true", "undersampling": "2" if slow else "1",
                                  "fps_max": "30" if slow else "60"}, only_missing=True)
            return ["--config", conf, "--go", "--world", world]
        if g.get("setup") == "flare":
            conf = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "flare")
            if not os.path.exists(os.path.join(conf, "settings.txt")):
                os.makedirs(conf, exist_ok=True)
                with open(os.path.join(conf, "settings.txt"), "w", encoding="utf-8") as f:
                    f.write("fullscreen=1\nenable_joystick=1\njoystick_device=0\nno_mouse=1\nmouse_move=0\nmouse_aim=0\n")
        if g.get("setup") == "sauerbraten":                      # full screen at the board's size (each start)
            w, h, _ = self.screen(g)
            self._sauerbraten(slow)
            return ["-t1", "-w%d" % w, "-h%d" % h]
        if g.get("setup") == "assaultcube":
            w, h, tv = self.screen(g)
            own = h >= tv                                         # (the TV's own size: AssaultCube's "desktop" mode)
            self._cfg_words(os.path.join(os.path.expanduser("~"), ".assaultcube", "config", "init.cfg"),
                            {"fullscreen": "1", "fullscreendesktop": "1" if own else "0"})
            return ["-t1"] + ([] if own else ["-w%d" % w, "-h%d" % h])
        return []

    @staticmethod
    def _cfg_words(path, want):
        """A Cube engine's settings file ("name value" lines) with these values, the rest of it as it was."""
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        out, done = [], set()
        for line in lines:
            name = (line.split(None, 1) or [""])[0]
            if name in want:
                if name in done:
                    continue
                line = "%s %s" % (name, want[name])
                done.add(name)
            out.append(line)
        out += ["%s %s" % (k, v) for k, v in want.items() if k not in done]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        os.replace(path + ".tmp", path)

    SAUER_LOOKS = {     # (Sauerbraten's own on a Pi 4 or 5; a Pi 3: smaller textures, simpler shaders and water)
        "light": "texreduce 1; shaderdetail 1; waterreflect 0; waterrefract 0; waterfade 0; caustics 0; "
                 "maxdynlights 1; maxparticles 1000; maxfps 60",
        "full": "texreduce 0; shaderdetail 3; waterreflect 1; waterrefract 1; waterfade 1; caustics 1; "
                "maxdynlights 3; maxparticles 4000; maxfps 200"}

    def _sauerbraten(self, slow):
        """The box's settings for Sauerbraten (~/.sauerbraten/sofa-box.cfg, run by its autoexec.cfg at each start):
        LT zooms while held, and the look for this board. Each is set once, when it isn't what the game saved last
        (sofabox_* remembered with its settings), so what you change in its Options stays, until the board changes."""
        home = os.path.join(os.path.expanduser("~"), ".sauerbraten")
        os.makedirs(home, exist_ok=True)
        look = "light" if slow else "full"
        cfg = ("// Written by the Sofa Box each time it starts the game: your own settings stay in config.cfg.\n"
               "// LT on a controller (the right mouse button) zooms while it's held.\n"
               "if (=s (getalias sofabox_keys) 1) [] [\n"
               "  bind MOUSE2 [zoom 1; onrelease [zoom -1]]\n"
               "  sofabox_keys = 1\n]\n"
               "// The look for this board (%s).\n"
               "if (=s (getalias sofabox_look) %s) [] [\n  %s\n  sofabox_look = %s\n]\n"
               ) % ("a Raspberry Pi 3: lighter" if slow else "the game's own", look, self.SAUER_LOOKS[look], look)
        with open(os.path.join(home, "sofa-box.cfg.tmp"), "w", encoding="utf-8") as f:
            f.write(cfg)
        os.replace(os.path.join(home, "sofa-box.cfg.tmp"), os.path.join(home, "sofa-box.cfg"))
        auto = os.path.join(home, "autoexec.cfg")                 # (anything else in it stays yours)
        try:
            with open(auto, encoding="utf-8") as f:
                mine = f.read()
        except OSError:
            mine = ""
        if "exec sofa-box.cfg" not in mine:
            with open(auto, "w", encoding="utf-8") as f:
                f.write("exec sofa-box.cfg\n" + mine)

    def play(self, gid):
        g = self.native(gid)
        exe = self.binary(g)
        asleep["on"] = False
        if not exe:
            raise ValueError("%s isn't on the box yet." % g["name"])
        with self.lock:
            if self.proc and self.proc.poll() is None:
                if self.playing == gid:
                    return {"ok": True}
                raise ValueError("Another game is open: hold Home to close it first.")
        if playing():
            player.stop(reason="a game")
        if browser and browser.connected():
            try:
                browser.rest(close_apps=light())
            except OSError:
                pass
        home_rests(True)
        try:
            return self._start(g, gid, exe)
        except Exception:
            home_rests(False)                               # (it didn't start: Home is the page again, at once)
            raise

    def _start(self, g, gid, exe):
        os.makedirs(GAME_DATA, exist_ok=True)
        args = [exe] + list(g.get("args") or []) + self._setup(g)
        env = display_env()
        if env.get("WAYLAND_DISPLAY"):
            env.setdefault("SDL_VIDEODRIVER", "wayland,x11")
        for k, v in (g.get("env") or {}).items():               # (the shooters: XWayland, whose mouse turns them
            if re.match(r"^SDL_[A-Z0-9_]+$", k):                  # without end; cage can't hold a Wayland one still)
                env[k] = str(v)
        controls = None if g["controls"] == "pad" else dict(self.catalog()["controls"][g["controls"]])
        if controls and g.get("pi3_height"):                      # drawn smaller and scaled up, a mouse moves less
            _, h, tv = self.screen(g)                             # in it: the stick turns as fast at any size
            controls["mouse_speed"] = round(float(controls.get("mouse_speed") or 1300) * tv / h)
        tmp = GAME_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"id": gid, "controls": controls}, f)
        os.replace(tmp, GAME_FILE)
        path = os.path.join(GAME_DATA, "last-game.log")
        try:
            with open(path, "rb") as f:
                kept = f.read().splitlines()[-240:]
        except OSError:
            kept = []
        log = open(path, "wb")
        log.write(b"\n".join(kept + [("== %s, %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), g["name"])).encode()]) + b"\n")
        log.flush()
        try:
            os.fsync(log.fileno())                          # (on the card now: a box unplugged a moment later still says
        except OSError:                                     # which game it had opened; Flare's two starts never showed)
            pass
        try:
            proc = subprocess.Popen(args, env=env, cwd=os.path.expanduser("~"), stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            os.remove(GAME_FILE)
            raise ValueError("%s didn't start (%s)." % (g["name"], exc.strerror or exc))
        finally:
            log.close()
        with self.lock:
            self.proc, self.playing, self.started, self.ending = proc, gid, steady(), None
        print("Game: %s" % g["name"], file=sys.stderr, flush=True)
        threading.Thread(target=self._wait, args=(g, proc), daemon=True, name="game").start()
        return {"ok": True}

    def _wait(self, g, proc):
        code = proc.wait()
        with self.lock:
            mine = self.proc is proc
            if mine:
                self.proc, self.playing = None, None
            ending, started = self.ending, self.started
        if not mine:
            return
        try:
            os.remove(GAME_FILE)
        except OSError:
            pass
        home_rests(False)
        if browser and browser.connected():                # Home back in front, and looked at on the TV (Browser.revive)
            try:
                browser.home(look=True)
            except OSError as exc:
                print("Home after %s: %s" % (g["name"], exc), file=sys.stderr, flush=True)
        print("Game: %s ended (%s)" % (g["name"], "Home held" if ending == "home" else ending or "by itself, code %s" % code),
              file=sys.stderr, flush=True)
        if code and not ending and steady() - started < 20:
            toast("%s stopped as it started. OK on it tries again; Settings → Help → Send a report has what it said." % g["name"])
        if not ending:
            go("#/games")

    def stop(self, why="home"):
        """End the game that's open (Home held, or another game)."""
        with self.lock:
            proc, self.ending = self.proc, why
        if not proc or proc.poll() is not None:
            return False
        for sig, wait in ((signal.SIGTERM, 6), (signal.SIGKILL, 3)):
            try:
                os.killpg(proc.pid, sig)
            except OSError:
                break
            try:
                proc.wait(wait)
                break
            except subprocess.TimeoutExpired:
                continue
        return True

    def heard_pads(self, pads):
        clean = []
        for p in pads[:8] if isinstance(pads, list) else []:
            kind = str(p.get("kind") or "generic")
            clean.append({"name": str(p.get("name") or "")[:60], "kind": kind if kind in PAD_KINDS else "generic"})
        new = {p["name"] for p in clean} - {p["name"] for p in self.pads_now()}
        self.pads, self.pads_at = clean, steady()
        return new


games = Games()


# ---------------------------------------------------------------- USB drives and discs

devices_seen = {"drives": [], "disc": None, "n": 0}


def plugged():
    """What's plugged in, from two small files and no programs: the disks and their sizes (a disc put in a drive
    changes its size) and what's mounted under /media. None where there's no /proc (a preview on a Mac)."""
    try:
        with open("/proc/partitions") as f:
            parts = f.read()
        with open("/proc/mounts") as f:
            mounts = [line for line in f if " /media/" in line]
        return parts, tuple(mounts)
    except OSError:
        return None


def watch_devices():
    """USB drives are mounted as they're plugged in (udisks), and a disc in a USB DVD drive shows on Home. lsblk and
    the rest only run when something changed (or once a minute): not every few seconds all day."""
    known, last, checked = set(), None, 0
    while True:
        now_plugged = plugged()
        if now_plugged is not None and now_plugged == last and steady() - checked < 60:
            time.sleep(15 if playing() else 3)
            continue
        last, checked = now_plugged, steady()
        try:
            dev = boxos.devices(mount=True)
            names = {d["dev"] for d in dev["drives"]} | ({dev["disc"]["dev"] + ":" + dev["disc"]["kind"]} if dev["disc"] else set())
            new = names - known
            if known and new:
                for d in dev["drives"]:
                    if d["dev"] in new:
                        toast("USB drive %s is ready: it's in Files%s." % (d["label"], ", and in Sofa on this box in a moment"
                                                                            if os.path.exists(os.path.join(local_sofa.data, "config.json")) else ""))
                if dev["disc"] and (dev["disc"]["dev"] + ":" + dev["disc"]["kind"]) in new:
                    toast("A %s is in: open it from Home." % boxos.DISC_NAMES.get(dev["disc"]["kind"], "disc"))
            if names != known:
                devices_seen.update(dev, n=devices_seen["n"] + 1)
            known = names
        except Exception:
            pass
        time.sleep(15 if playing() else 4)


# ---------------------------------------------------------------- Bluetooth, Wi-Fi and the phone remote (setting the box up)

class PairingHelper:
    """BlueZ asks the box to say yes to a pairing (an Xbox controller asks, and many others): with nobody to ask it
    says no ("No agent available"), the controller stops blinking as if paired, and the box says it didn't pair. A
    bluetoothctl kept open as the box's default agent answers: yes while the box is looking for devices (Settings,
    Games, the setup) or pairing one, no otherwise, so nothing nearby pairs itself to the box behind your back."""
    ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x01|\x02")

    def __init__(self, accepting):
        self.accepting, self.said = accepting, []

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="bt-agent").start()

    def _loop(self):
        while True:
            try:
                proc = subprocess.Popen([os.environ.get("SOFA_BOX_BLUETOOTHCTL") or "bluetoothctl"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
            except OSError:
                return                                    # (no Bluetooth tools here)
            try:
                self._serve(proc)
            except (OSError, ValueError):
                pass
            finally:
                if proc.poll() is None:
                    proc.kill()
            time.sleep(5)                                 # (bluetoothd restarted, say: again)

    def _serve(self, proc):
        proc.stdin.write(b"agent NoInputNoOutput\ndefault-agent\n")
        proc.stdin.flush()
        seen = ""
        while proc.poll() is None:
            if not select.select([proc.stdout], [], [], 5)[0]:
                continue
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                return
            seen = (seen + self.ANSI.sub("", chunk.decode("utf-8", "replace")))[-2000:]
            if "(yes/no)" in seen:                       # "Confirm passkey 123456 (yes/no):", "Authorize service …"
                yes = self.accepting()
                proc.stdin.write(b"yes\n" if yes else b"no\n")
                proc.stdin.flush()
                self.said = (self.said + [(time.strftime("%H:%M:%S"), "yes" if yes else "no")])[-30:]
                print("Bluetooth: a pairing asked, the box said %s" % ("yes" if yes else "no (not looking for devices)"),
                      file=sys.stderr, flush=True)
                seen = ""


class Bluetooth:
    """Looks for Bluetooth devices while the setup or Settings page asks it to, and during the first start
    pairs any remote, controller, keyboard or mouse that's in pairing mode by itself (with nothing to press
    "Pair" with yet, a Fire TV remote held on Home is all it takes)."""

    def __init__(self):
        self.until = self.autopair_until = 0
        self.devices, self.state = [], {}               # mac -> "pairing" | "paired" | "failed"
        self.pairing_until = 0
        self.paused_until = 0                            # while the box joins a Wi-Fi: no looking (see pause)
        self.lock, self.thread = threading.Lock(), None

    def pause(self, seconds):
        """No Bluetooth discovery for a while (0: from now on, it may look again). On a Pi 3 one chip does both Wi-Fi
        and Bluetooth, through one aerial: discovery all through a Wi-Fi join (the setup's first screen looks every few
        seconds) slowed the join down and kept the chip at its busiest just as it switched from the box's own Wi-Fi to
        the home one, which is when a 1.1.49 box restarted by itself."""
        self.paused_until = steady() + seconds if seconds else 0

    def paused(self):
        return steady() < self.paused_until

    def want(self, seconds=30, autopair=False):
        now = steady()
        self.until = max(self.until, now + seconds)
        if autopair:
            self.autopair_until = max(self.autopair_until, now + seconds)
        with self.lock:
            if not (self.thread and self.thread.is_alive()):
                self.thread = threading.Thread(target=self._loop, daemon=True, name="bluetooth")
                self.thread.start()

    def accepting(self):
        """Pairings get a yes now: while looking for devices, or a minute after pairing one."""
        return steady() < max(self.until, self.pairing_until)

    def _loop(self):
        run(["bluetoothctl", "power", "on"], 10)
        run(["bluetoothctl", "pairable", "on"], 10)         # (only while looking: a controller asking to pair is let in)
        scan = None
        while steady() < self.until:
            if playing() or self.paused():                # not while a video plays, or while a Wi-Fi is being joined
                if scan and scan.poll() is None:
                    scan.terminate()
                    run(["bluetoothctl", "scan", "off"], 10)
                scan = None
                time.sleep(2)
                continue
            if not scan or scan.poll() is not None:     # discovery lasts as long as this asks for it
                try:
                    scan = subprocess.Popen(["bluetoothctl", "--timeout", "30", "scan", "on"], stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL)
                except OSError:
                    return
            self.devices = boxos.bt_devices()
            if steady() < self.autopair_until:
                for d in self.devices:
                    if d["kind"] in ("remote", "controller", "keyboard", "mouse") and not d["paired"] and d["mac"] not in self.state:
                        self.pair(d["mac"])
            time.sleep(2)
        if scan and scan.poll() is None:
            scan.terminate()
        if not self.accepting():
            run(["bluetoothctl", "pairable", "off"], 10)

    def pair(self, mac):
        self.state[mac] = "pairing"
        self.pairing_until = steady() + 60

        def go():
            ok, _ = boxos.bt_pair(mac)
            self.state[mac] = "paired" if ok else "failed"
            name = next((d["name"] for d in self.devices if d["mac"] == mac), "It")
            toast("%s is paired." % name if ok else "%s didn't pair. Put it in pairing mode and try again." % name)
            self.devices = boxos.bt_devices()
        threading.Thread(target=go, daemon=True).start()

    def listing(self):
        shown = [dict(d, state=self.state.get(d["mac"])) for d in self.devices if d["kind"] != "other" or d["paired"]]
        return {"scanning": steady() < self.until, "autopair": steady() < self.autopair_until,
                "devices": sorted(shown, key=lambda d: (not d["paired"], not d["connected"], -(d["rssi"] or -999)))}


class Network:
    """The box's network: a cable, Wi-Fi, or with neither (a new box), a Wi-Fi hotspot of its own, so a phone
    can join it, work the box and give it the home Wi-Fi."""
    CON = "sofa-box-setup"

    def __init__(self):
        self.hotspot, self.cached, self.lock = None, [], threading.Lock()
        self.used = 0                                        # when a phone on the hotspot last did something
        self.problem, self.failed_at = None, None            # why the box's own Wi-Fi didn't start, and when
        self.joining = None                                  # the last home Wi-Fi it was asked to join: how that went
        self.phone_at = 0                                    # when a paired phone on its own Wi-Fi last asked (remote open)

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

    @staticmethod
    def radio_on():
        """Raspberry Pi OS keeps Wi-Fi switched off (rfkill) until a country is set in Raspberry Pi Imager; the box's
        own Wi-Fi needs it on. (sofa-box tune does the same as root at every start.)"""
        run(["nmcli", "radio", "wifi", "on"], 10)
        run(["rfkill", "unblock", "wifi"], 5)

    def start_hotspot(self):
        if self.hotspot:
            return self.hotspot
        self.radio_on()
        dev = self.wifi_device()
        if not dev:
            self.problem, self.failed_at = "This box's Wi-Fi isn't working (NetworkManager doesn't see it).", steady()
            return None
        time.sleep(1)                                        # Wi-Fi that was just switched on
        if not self.cached:
            self.scan()                                      # while it still can: a hotspot can't look around
        ssid, password = self.credentials(dev)
        run(["nmcli", "connection", "delete", self.CON], 10)  # one left from before
        captive.start()                                      # first: a phone that joins asks it straight away
        code, out = self.bring_up(dev, ssid, password)
        if code == 0:
            self.hotspot = {"ssid": ssid, "password": password, "address": "10.42.0.1", "at": steady(),
                            "wifi_qr": "WIFI:T:WPA;S:%s;P:%s;;" % (ssid.replace(";", r"\;"), password)}
            self.problem = None
            toast("No internet yet: the box made its own Wi-Fi, %s, for your phone." % ssid)
        else:
            captive.stop()
            self.problem, self.failed_at = (out.splitlines() or ["the box couldn't make its own Wi-Fi"])[-1][:200], steady()
            print("The box's own Wi-Fi: %s" % out[-300:], file=sys.stderr, flush=True)
        return self.hotspot

    def bring_up(self, dev, ssid, password):
        """The box's own Wi-Fi, made whole and then started, once. The Pi's Wi-Fi chip can't do PMF as a hotspot: with it
        on, iPhones see the network but can't join. No IPv6 on it either: a phone that finds only IPv4 here asks the
        sign-in page (the box) at once. (It was `nmcli device wifi hotspot`, which starts it NetworkManager's way, then
        those two changes, then a second start for them to count: on a real Pi 3 the Wi-Fi went up, and three seconds
        later down and up again with its address server, just as the TV showed the code to join it.) Where
        NetworkManager won't take it whole, the old way."""
        made = run(["nmcli", "connection", "add", "type", "wifi", "ifname", dev, "con-name", self.CON, "autoconnect", "no",
                    "ssid", ssid, "802-11-wireless.mode", "ap", "802-11-wireless-security.key-mgmt", "wpa-psk",
                    "802-11-wireless-security.proto", "rsn", "802-11-wireless-security.pairwise", "ccmp",
                    "802-11-wireless-security.group", "ccmp", "802-11-wireless-security.pmf", "disable",
                    "802-11-wireless-security.psk", password, "ipv4.method", "shared", "ipv6.method", "disabled"], 20)
        if made[0] == 0:
            up = run(["nmcli", "connection", "up", self.CON], 30)
            if up[0] == 0:
                return up
            made = up
        print("The box's own Wi-Fi, made in one go: %s. The old way." % made[1][-200:], file=sys.stderr, flush=True)
        run(["nmcli", "connection", "delete", self.CON], 10)
        code, out = run(["nmcli", "device", "wifi", "hotspot", "ifname", dev, "con-name", self.CON, "ssid", ssid, "password", password], 30)
        if code == 0 and run(["nmcli", "connection", "modify", self.CON, "802-11-wireless-security.pmf", "disable",
                              "ipv6.method", "disabled"], 10)[0] == 0:
            run(["nmcli", "connection", "up", self.CON], 30)
        return code, out

    def stop_hotspot(self):
        captive.stop()
        if self.hotspot:
            run(["nmcli", "connection", "down", self.CON], 20)
            run(["nmcli", "connection", "delete", self.CON], 20)
            self.hotspot = None

    @staticmethod
    def credentials(dev):
        """The box's own Wi-Fi keeps its name and password from one time to the next: a phone that drops off it (the box
        tried a home Wi-Fi that didn't work) joins again by itself, and code 1 on the TV stays right. Reset makes new ones."""
        path = os.path.join(CONF_DIR, "hotspot.json")
        try:
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("ssid") and re.match(r"^\d{8}$", str(saved.get("password"))):
                return saved["ssid"], saved["password"]
        except (OSError, ValueError, AttributeError):
            pass
        ssid, password = Network.new_name(), "%08d" % (int.from_bytes(os.urandom(4), "big") % 10 ** 8)
        try:
            os.makedirs(CONF_DIR, exist_ok=True)
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
                json.dump({"ssid": ssid, "password": password}, f)
        except OSError:
            pass
        return ssid, password

    @staticmethod
    def new_name():
        """A name for the box's own Wi-Fi, new for each card (kept from then on). It was the last four digits of the
        Wi-Fi chip's address, the same every time a box was set up again: a phone keeps what it learnt about a Wi-Fi by
        its name (that it has no internet, that its sign-in sheet was closed once, "Auto-Join" or "Auto-Login" off), so
        on a box set up a second time the Setup Assistant never opened by itself on that phone."""
        return "Sofa Box %04d" % (int.from_bytes(os.urandom(2), "big") % 10000)

    def find(self, ssid, dev, limit=25):
        """Just off its own Wi-Fi, the box's list of networks is empty (a hotspot can't look around): look until the one
        to join shows, or for `limit` seconds."""
        on = ["ifname", dev] if dev else []
        end = steady() + limit
        while True:
            run(["nmcli", "device", "wifi", "rescan"] + on, 15)
            code, out = run(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list"] + on, 15)
            if code == 0 and ssid in [line.replace("\\:", ":") for line in out.splitlines()]:
                return True
            if steady() >= end:
                return False
            time.sleep(3)

    KEPT = "setup-joined.json"                               # the setup's home Wi-Fi join, kept across a restart

    def keep_joined(self, link=None):
        """At the setup: the home Wi-Fi it joined (and the phone's link to carry on with), on the card at once, so the
        setup goes on from there after a restart instead of from its first screen."""
        if settings()["welcomed"] or not self.joining or self.joining.get("state") != "joined":
            return
        kept = {"ssid": self.joining["ssid"], "at": time.time()}
        link = link or (phone and getattr(phone, "handoff_link", None))
        if link:
            kept["link"] = link
        try:
            write_durably(os.path.join(CONF_DIR, self.KEPT), json.dumps(kept), 0o600)
        except OSError:
            pass

    def resume(self):
        """After a restart in the middle of the setup: the home Wi-Fi it had joined counts as just joined (the TV shows
        the setup's last step, keeping the phone as the remote), and the phone's carry-on link still works."""
        path = os.path.join(CONF_DIR, self.KEPT)
        try:
            with open(path, encoding="utf-8") as f:
                kept = json.load(f)
        except (OSError, ValueError):
            return None
        if settings()["welcomed"] or not isinstance(kept, dict) or not kept.get("ssid"):
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        self.joining = {"ssid": str(kept["ssid"]), "state": "joined", "message": "Connected to %s." % kept["ssid"],
                        "at": steady(), "resumed": True}
        self.from_phone = steady() if kept.get("link") else 0
        return kept

    def join(self, ssid, password):
        """The home Wi-Fi. If it doesn't work out, the box's own Wi-Fi comes back with the same name and password, and
        `joining` says why (the TV shows it)."""
        ssid = str(ssid)
        self.joining = {"ssid": ssid, "state": "joining", "message": "Joining %s…" % ssid, "at": steady()}
        bluetooth.pause(150)                                # the Wi-Fi chip to itself while it joins (Bluetooth.pause)
        with self.lock:                                     # never while the watch is starting the box's own Wi-Fi
            had = bool(self.hotspot)
            try:
                dev = self.wifi_device()
                self.stop_hotspot()
                if had or ssid not in [n["ssid"] for n in self.cached]:
                    self.find(ssid, dev)
                code, out = run(["nmcli", "device", "wifi", "connect", ssid] + (["password", str(password)] if password else [])
                                + (["ifname", dev] if dev else []), 60)
            except Exception as exc:                        # never left "joining": the watch would wait for ever
                code, out = 1, str(exc)
            if code != 0 and had:
                self.start_hotspot()                         # back to the box's own, same name and password, to try again
        if code == 0:
            message = "Connected to %s." % ssid
            secure_remote.wake()                             # on a home network now: its https remote, straight away
            look_soon()                                      # and the Sofa that's on it
        elif re.search(r"secrets|password|802-11-wireless-security|psk", out, re.I):
            message = "The password for %s isn't right." % ssid
        elif re.search(r"No network with SSID", out, re.I):
            message = "The box can't see %s from here. Is it on, and near enough?" % ssid
        else:
            message = "It didn't join %s: %s" % (ssid, ((out.strip().splitlines() or ["no reason given"])[-1])[:160])
        if code != 0:
            print("Joining %s: %s" % (ssid, out[-300:]), file=sys.stderr, flush=True)
        self.joining = {"ssid": ssid, "state": "joined" if code == 0 else "failed", "message": message, "at": steady()}
        if code == 0:
            self.keep_joined(getattr(self, "pending_link", None))
        bluetooth.pause(20 if code == 0 else 0)             # (a moment more after joining: getting an address there)
        return {"ok": code == 0, "message": message}

    def join_soon(self, ssid, password):
        """Join from a phone or the TV: answer first, then join. The box may be about to leave the Wi-Fi the phone is on
        (its own), and the phone's answer would never arrive; the TV shows how it goes."""
        ssid = str(ssid)
        if not ssid:
            return {"ok": False, "message": "Which Wi-Fi?"}
        if self.is_joining():
            return {"ok": False, "message": "The box is already joining %s. The TV shows how it goes." % self.joining["ssid"]}
        self.joining = {"ssid": ssid, "state": "joining", "message": "Joining %s…" % ssid, "at": steady()}
        threading.Timer(1.5, self.join, (ssid, password)).start()
        return {"ok": True, "pending": True, "message": "Joining %s… The TV shows how it goes." % ssid}

    def clients(self):
        """Devices on the box's own Wi-Fi now (the setup moves on from "join its Wi-Fi" once a phone has)."""
        if not self.hotspot:
            return 0
        code, out = run(["ip", "neigh", "show", "to", "10.42.0.0/24"], 5)
        return sum(1 for line in out.splitlines()
                   if code == 0 and line.startswith("10.42.0.") and not line.startswith("10.42.0.1 ")
                   and not re.search(r"\b(FAILED|INCOMPLETE)\b", line))

    def saved(self):
        """The Wi-Fi networks the box knows (it joins them by itself when they're back)."""
        code, out = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], 10)
        return [line.rsplit(":", 1)[0] for line in out.splitlines()
                if code == 0 and line.endswith(":802-11-wireless") and line.rsplit(":", 1)[0] != self.CON]

    def wait_for(self):
        """How long the box waits, offline, before it makes its own Wi-Fi.
        A new box (at its setup, perhaps with nothing but a phone): soon. A box that knows a Wi-Fi: the router may only be
        restarting, and a hotspot would keep the box off it, so a few minutes. Otherwise a minute, for a slow router."""
        if os.environ.get("SOFA_BOX_HOTSPOT_AFTER"):
            return int(os.environ["SOFA_BOX_HOTSPOT_AFTER"])
        saved = self.saved()
        if not settings()["welcomed"]:
            # in the middle of its setup, a box that has been given a home Wi-Fi (it restarted, say): that Wi-Fi first.
            # (It waited 15 seconds here whatever it knew; a Pi 3 starting up can take longer than that to join, so the
            # box made its own Wi-Fi again, which took the Wi-Fi chip off the home one, and the setup began again.)
            return 90 if saved else 15
        return 180 if saved else 50

    def is_joining(self):
        """A home Wi-Fi being joined right now (a join takes up to about 90 seconds: looking for it, then joining)."""
        return bool(self.joining) and self.joining.get("state") == "joining" and steady() - self.joining.get("at", 0) < 180

    def tick(self, offline_since, now):
        """One look at the network (every 10 seconds); gives back since when the box has been offline."""
        if self.is_joining() or not self.lock.acquire(blocking=False):
            # its own Wi-Fi is off while it joins a home Wi-Fi, so it looks offline: that's no reason to bring its own
            # Wi-Fi back (that took the Wi-Fi chip away mid-join, and the setup looped back to "connecting"). The
            # waiting starts again once the join is over; a join that fails brings its own Wi-Fi back by itself.
            return now
        try:
            return self._tick(offline_since, now)
        finally:
            self.lock.release()

    def _tick(self, offline_since, now):
        address = local_address()
        if address and address != "10.42.0.1":
            if self.hotspot and self.wired():
                self.stop_hotspot()
            return None
        if self.hotspot:
            quiet = now - max(self.hotspot.get("at", 0), self.used)
            if settings()["welcomed"] and quiet > 600 and self.saved():
                self.stop_hotspot()                          # back to the home Wi-Fi, if it's there now
                return now
            return offline_since
        offline_since = now if offline_since is None else offline_since
        if now - offline_since >= self.wait_for() and not settings().get("no_hotspot") \
                and (self.failed_at is None or now - self.failed_at >= 45):
            self.start_hotspot()                             # (after a failure, again every 45 seconds)
        return offline_since

    def watch(self):
        """No cable, no Wi-Fi for a while: the hotspot. A network again: the hotspot goes. A box that knows a Wi-Fi
        doesn't stay on its own for ever: after ten quiet minutes it looks for its Wi-Fi again."""
        offline_since = steady()
        while True:
            try:
                offline_since = self.tick(offline_since, steady())
            except Exception:
                pass
            time.sleep(10)

def on_own_wifi(ip):
    """A phone on the box's own Wi-Fi (NetworkManager's hotspot is 10.42.0.1/24)."""
    return str(ip).startswith("10.42.0.")


CAPTIVE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Sofa Box</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="0;url=%(url)s">
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0D0D10;color:#F6F6F8;
font:17px -apple-system,system-ui,sans-serif;text-align:center}a{display:inline-block;margin-top:1rem;padding:.9rem 1.6rem;
border-radius:999px;background:#FF2E88;color:#fff;font-weight:700;text-decoration:none}</style></head>
<body><div><b>Sofa Box</b><br><a href="%(url)s">Open the remote</a></div></body></html>"""


class CaptiveHandler(BaseHTTPRequestHandler):
    """The box's own Wi-Fi works like a hotel's: every name is the box (dnsmasq-shared.d/sofa-box.conf), so a phone
    that joins finds no internet, only this page, and opens its sign-in sheet by itself (iPhone, Android). The sheet
    opens the phone remote. Unlike the browser, the sheet takes http:// pages even with "HTTPS only" switched on, and
    nothing needs scanning but the Wi-Fi."""
    protocol_version = "HTTP/1.1"
    timeout = 30                         # (a connection that sends nothing doesn't keep its thread)

    def log_message(self, *args):
        pass

    def answer(self, body=True):
        here = network.hotspot and on_own_wifi(self.client_address[0])
        page = (CAPTIVE_PAGE % {"url": "http://%s:%d/join" % (network.hotspot["address"], PhoneRemote.PORT)} if here
                else "Not here.").encode()
        self.send_response(200 if here else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8" if here else "text/plain")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(page)

    def do_GET(self):
        self.answer()

    def do_POST(self):
        self.answer()

    def do_HEAD(self):
        self.answer(body=False)


class Captive:
    """The sign-in page on port 80, while the box's own Wi-Fi is on (the agent may: CAP_NET_BIND_SERVICE)."""
    PORT = int(os.environ.get("SOFA_BOX_CAPTIVE_PORT", "80"))

    def __init__(self):
        self.server = None

    def start(self):
        if self.server:
            return
        for attempt in range(5):
            try:
                self.server = Server(("0.0.0.0", self.PORT), CaptiveHandler)
                break
            except OSError as exc:
                if attempt == 4:
                    print("The sign-in page for the box's own Wi-Fi can't use port %d: %s" % (self.PORT, exc), file=sys.stderr, flush=True)
                    return
                time.sleep(1)
        threading.Thread(target=self.server.serve_forever, daemon=True, name="captive").start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


captive = Captive()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None                                        # (the relay passes a redirect on to the phone as it is)


_local_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


class _Kept:
    """One HTTPS connection to the Sofa Box service, kept open and used again: a new one for every press of the remote
    meant a TLS handshake each time, half a second or more on a Pi 3."""

    def __init__(self):
        self.conn, self.at, self.lock = None, None, threading.Lock()

    def post(self, base, path, body, timeout):
        u = urllib.parse.urlsplit(base)
        with self.lock:
            for attempt in (1, 2):                         # a kept connection the far end has closed: once more, afresh
                try:
                    if self.conn is None or self.at != (u.scheme, u.netloc):
                        if self.conn:
                            self.conn.close()
                        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
                        self.conn, self.at = cls(u.netloc, timeout=timeout), (u.scheme, u.netloc)
                    self.conn.timeout = timeout
                    if self.conn.sock:
                        self.conn.sock.settimeout(timeout)
                    self.conn.request("POST", u.path.rstrip("/") + path, json.dumps(body),
                                      {"Content-Type": "application/json", "User-Agent": "Sofa Box " + OS_VERSION})
                    r = self.conn.getresponse()
                    data = r.read()
                    if r.status >= 400:
                        try:
                            said = json.loads(data).get("error")
                        except ValueError:
                            said = None
                        raise ValueError(said or "the Sofa Box service said %d" % r.status)
                    return json.loads(data)
                except (OSError, http.client.HTTPException):
                    if self.conn:
                        self.conn.close()
                    self.conn = None
                    if attempt == 2:
                        raise


class SecureRemote:
    """The phone remote over real HTTPS at home, which phones' browsers set to "HTTPS only" need: the box's own name,
    <id>.box.edgeventure.uk, pointed at its address here, and a Let's Encrypt certificate for it, both from the Sofa Box
    certificate service (deploy/box-certs). The box makes its own key; the service only sees a certificate request.
    What it sends: the random id and secret the service gave it, and its address on the home network, about once a
    day. Where the router won't let names point at home addresses ("DNS rebinding protection"), it stays http://.
    Settings -> Remotes switches it off."""
    SERVICE = (os.environ.get("SOFA_BOX_CERTS") or "https://boxcert.edgeventure.uk").rstrip("/")
    PORT = int(os.environ.get("SOFA_BOX_REMOTE_TLS_PORT", "8093"))

    def __init__(self):
        self.dir = os.path.join(CONF_DIR, "secure-remote")
        self.acct, self.server, self.served, self.resolves = None, None, None, False
        self.error, self.event = None, threading.Event()
        self.relay_base, self.relay_at, self.relay_threads = None, 0, []
        # the relay's kept connections: two waiting (one is always there while the other brings a press down and asks
        # again, a round trip to the service that a quick second press waited for), and one answering
        self.polls, self.polls2, self.answers = _Kept(), _Kept(), _Kept()

    # -- the relay (the default): the remote from anywhere, through the service, with no certificate or name per box
    # (no Let's Encrypt limits; routers that block names pointing home don't matter). The box keeps a request open
    # there; a phone's requests to <service>/r/<id>/... come down it, go to the remote here, and the answers go back.
    def relaying(self):
        return settings().get("remote_link", "relay") != "certificate"

    def relayed(self, url):
        return bool(url and self.relay_base and url.startswith(self.relay_base))

    def start_relay(self):
        if not any(t.is_alive() for t in self.relay_threads):
            self.relay_threads = [threading.Thread(target=self._relay, args=(kept, i * 0.5), daemon=True, name="relay")
                                  for i, kept in enumerate((self.polls, self.polls2))]
            for t in self.relay_threads:
                t.start()

    def _relay(self, kept=None, delay=0):
        kept = kept or self.polls
        time.sleep(delay)
        backoff, first = 2, True
        while self.on() and self.relaying():
            acct = self.account()
            if not acct.get("id") or acct.get("unregistered") or network.hotspot:
                time.sleep(5)
                continue
            try:                                           # (the first comes back at once: the TV's code shows straight away)
                got = kept.post(self.SERVICE, "/v1/relay/poll", dict({"id": acct["id"], "secret": acct["secret"]},
                                                                            **({"wait": 0} if first else {})), 45)
                first = False
                self.relay_base, self.relay_at, backoff = got.get("base") or self.relay_base, steady(), 2
                for req in got.get("requests") or []:
                    if not self._relay_input(acct, req):     # presses: here, in order; the rest on a thread each
                        threading.Thread(target=self._relay_one, args=(acct, req), daemon=True).start()
            except Exception as exc:                       # offline, or the service restarting: again, more slowly
                self.error, first = "relay: %s" % (str(exc)[:160] or exc.__class__.__name__), True
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
        self.relay_at = 0

    def _relay_input(self, acct, req):
        """A press (or typing, the touchpad, the volume) through the relay, done here and now instead of as a request to
        the remote on this box (a new connection and a whole request for each, on a Pi 3 tens of milliseconds); the same
        checks as there. False: not a press, for _relay_one."""
        path = urllib.parse.urlsplit(req.get("path") or "/").path
        if req.get("method") != "POST" or path not in INPUT_PATHS or not phone:
            return False
        headers = {k.lower(): v for k, v in (req.get("headers") or {}).items()}
        token = re.search(r"(?:^|;\s*)%s=([0-9a-f]{48})" % RemoteHandler.COOKIE, headers.get("cookie") or "")
        if headers.get("x-sofa-remote") != "1" or not (token and phone.valid(token.group(1))):
            return False                                   # (the remote itself says what's wrong)
        try:
            data = json.loads(base64.b64decode(req.get("body") or "") or b"{}")
            phone_input(path, data if isinstance(data, dict) else {})
            status, body = 200, b'{"ok":true}'
        except (ValueError, TypeError) as exc:
            status, body = 400, json.dumps({"error": str(exc)}).encode()
        threading.Thread(target=self._answer, args=(acct, req, status, [], body), daemon=True).start()
        return True

    def _answer(self, acct, req, status, keep, data):
        try:
            self.answers.post(self.SERVICE, "/v1/relay/answer", {"id": acct["id"], "secret": acct["secret"], "rid": req.get("rid"),
                              "answer": {"status": status, "headers": keep, "body": base64.b64encode(data).decode()}}, 20)
        except Exception:
            pass

    def _relay_one(self, acct, req):
        """One phone request, to the remote on this box as the phone sent it (its sign-in, its body), marked as coming
        through the relay (which only ever means less: no typed codes)."""
        headers = {k: v for k, v in (req.get("headers") or {}).items()
                   if k.lower() in ("cookie", "content-type", "x-sofa-remote", "user-agent")}
        headers["X-Sofa-Relay"] = "1"
        try:
            body = base64.b64decode(req.get("body") or "")
        except ValueError:
            body = b""
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (PhoneRemote.PORT, req.get("path") or "/"),
                                   data=body if req.get("method") == "POST" else None, method=req.get("method") or "GET", headers=headers)
        try:
            with _local_opener.open(r, timeout=20) as resp:
                status, hdrs, data = resp.status, resp.headers, resp.read(3_000_000)
        except urllib.error.HTTPError as e:
            status, hdrs, data = e.code, e.headers, e.read(3_000_000)
        except (OSError, ValueError):
            status, hdrs, data = 502, None, b'{"error":"The remote on the box didn\'t answer."}'
        keep = [[k, v] for k, v in (hdrs.items() if hdrs else []) if k.lower() in ("set-cookie", "location")]
        self._answer(acct, req, status, keep, data)

    def on(self):
        return self.SERVICE != "0" and settings().get("secure_remote", True) is not False

    def path(self, name):
        return os.path.join(self.dir, name)

    def account(self):
        if self.acct is None:
            try:
                with open(self.path("account.json"), encoding="utf-8") as f:
                    self.acct = json.load(f)
            except (OSError, ValueError):
                self.acct = {}
        if not self.acct.get("id"):              # a new box: its own id and secret now, offline; the service takes them
            alphabet = "abcdefghijkmnpqrstuvwxyz23456789"   # when it's first online (so the remote's address is known now)
            self.acct.update(id="".join(alphabet[b % len(alphabet)] for b in os.urandom(10)), secret=os.urandom(24).hex(),
                             unregistered=True)
            try:
                self.keep("account.json", self.acct)
            except OSError:
                pass
        return self.acct

    def handoff(self, link):
        """The phone remote's address through the relay, with a pairing link: for the phone at the box's setup to
        carry on there once the box has left its own Wi-Fi for the home one (None: the relay is off)."""
        if not (self.on() and self.relaying()):
            return None
        acct = self.account()
        base = self.relay_base or "%s/r/%s" % (self.SERVICE, acct["id"])
        return "%s/r/%s" % (base.rstrip("/"), link)

    def keep(self, name, data):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        write_durably(self.path(name), data if isinstance(data, str) else json.dumps(data, indent=1), 0o600)

    def call(self, route, body, timeout=60):
        req = urllib.request.Request(self.SERVICE + route, json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "Sofa Box " + OS_VERSION})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                said = json.loads(e.read()).get("error")
            except ValueError:
                said = None
            raise ValueError(said or "the certificate service said %d" % e.code)

    def expires(self):
        try:
            p = subprocess.run(["openssl", "x509", "-noout", "-enddate", "-in", self.path("cert.pem")], capture_output=True, text=True, timeout=20)
            return ssl.cert_time_to_seconds(p.stdout.strip().split("=", 1)[1]) if p.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            return None

    def renew(self, acct):
        """A certificate request for the box's name, with its own key (made once), and the certificate back."""
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        key, name = self.path("key.pem"), acct["name"]
        args = ["openssl", "req", "-new", "-subj", "/CN=" + name, "-addext", "subjectAltName=DNS:" + name]
        args += ["-key", key] if os.path.exists(key) else ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                                                            "-pkeyopt", "ec_param_enc:named_curve", "-nodes", "-keyout", key]
        p = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            raise ValueError("openssl: " + p.stderr.strip()[-200:])
        os.chmod(key, 0o600)
        out = self.call("/v1/cert", {"id": acct["id"], "secret": acct["secret"], "csr": p.stdout}, timeout=300)
        self.keep("cert.pem", out["cert"])

    def step(self, now=None):
        """One look: the name, the address it points at, the certificate (renewed a month ahead), the https remote."""
        now = now or time.time()
        if not self.on():
            return self.stop()
        ip = local_address()
        if not ip or network.hotspot or on_own_wifi(ip):
            return True                                         # not on a home network yet (at its setup, say)
        acct = self.account()
        if acct.get("unregistered"):                        # its own id and secret, made at its first start
            got = self.call("/v1/register", {"id": acct["id"], "secret": acct["secret"]})
            acct.update(id=got["id"], secret=got["secret"], name=got["name"])
            acct.pop("unregistered", None)
            self.keep("account.json", acct)
        if self.relaying():                                 # the relay: no name pointed home, no certificate
            self.stop()
            self.start_relay()
            return None
        if acct.get("ip") != ip or now - acct.get("ip_at", 0) > 86400:
            self.call("/v1/address", {"id": acct["id"], "secret": acct["secret"], "ip": ip})
            acct.update(ip=ip, ip_at=int(now))
            self.keep("account.json", acct)
        until = self.expires()
        if not until or until - now < 30 * 86400:
            self.renew(acct)
        self.serve()
        self.resolves = resolves_to(acct["name"], ip)

    def serve(self):
        """The phone remote on port 8093 with the certificate (again when it's renewed)."""
        try:
            stamp = os.path.getmtime(self.path("cert.pem"))
        except OSError:
            return
        if self.server and self.served == stamp:
            return
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.path("cert.pem"), self.path("key.pem"))
        self.stop()
        server = Server(("0.0.0.0", self.PORT), SecureRemoteHandler)
        server.socket = ctx.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
        threading.Thread(target=server.serve_forever, daemon=True, name="phone-remote-https").start()
        self.server, self.served = server, stamp

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def url(self):
        if self.relaying():
            return self.relay_base if self.relay_base and steady() - self.relay_at < 60 else None
        acct = self.account()
        if self.server and self.resolves and acct.get("name") and acct.get("ip") == local_address():
            return "https://%s:%d" % (acct["name"], self.PORT)
        return None

    def status(self):
        acct = self.account()
        state = "off" if not self.on() else "ready" if self.url() else "router" if self.server and not self.resolves \
            else "error" if self.error else "working"
        return {"state": state, "name": acct.get("name"), "error": self.error, "relay": self.relaying(),
                "where": urllib.parse.urlsplit(self.relay_base).netloc if self.relaying() and self.relay_base else acct.get("name")}

    def wake(self):
        self.event.set()

    def watch(self):
        """A look 20 seconds after starting, then every 10 minutes. Not on a home network yet, every 30 seconds: at the
        setup, the phone needs the https remote soon after the box joins one. After a failure, again in 30 seconds a
        few times (just after joining a Wi-Fi, its DNS may not be ready yet), then hourly, unless woken."""
        wait, fails = 20, 0
        while True:
            self.event.wait(wait)
            self.event.clear()
            j = network.joining if network else None
            soon = bool(j) and j.get("state") == "joined" and steady() - j.get("at", 0) < 180   # (just joined one)
            try:
                offline = self.step()
                self.error, wait, fails = None, (5 if soon else 30) if offline else 600, 0
            except Exception as exc:
                fails += 1
                self.error, wait = str(exc)[:200] or exc.__class__.__name__, 5 if soon else 30 if fails <= 5 else 3600
                print("Secure phone remote: %s" % self.error, file=sys.stderr, flush=True)
                try:
                    self.serve()                                # what it has still works
                except Exception:
                    pass


def resolves_to(name, ip):
    """Does the home network's DNS give the box's name its address? (Routers with "DNS rebinding protection" don't.)"""
    try:
        return any(a[4][0] == ip for a in socket.getaddrinfo(name, None, socket.AF_INET))
    except (OSError, UnicodeError):
        return False


secure_remote = SecureRemote()


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
        self.at, self.parked, self.used, self.parker = [1.0, 1.0], True, 0.0, None     # the touchpad's pointer
        self.link = os.urandom(12).hex()                   # the QR code's: long enough for the internet (the relay)
        self.misses = []                                   # when wrong four-digit codes were typed (MISSES)

    @staticmethod
    def _new_code():
        return "%04d" % (int.from_bytes(os.urandom(2), "big") % 10000)

    def _load(self):
        """The phones with a sign-in. Kept in memory while the file is unchanged: every press checks it, and reading it
        from the card each time cost a Pi 3 a few milliseconds a press."""
        try:
            st = os.stat(self.path)
            stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
            cached = getattr(self, "_cache", None)
            if cached and cached[0] == stamp:
                return dict(cached[1])
            with open(self.path, encoding="utf-8") as f:
                phones = json.load(f)
            self._cache = (stamp, phones)
            return dict(phones)
        except (OSError, ValueError):
            return {}

    def url(self):
        if network.hotspot:
            return "http://%s:%d" % (network.hotspot["address"], self.PORT)
        secure = secure_remote.url()                       # https://<id>.box.edgeventure.uk:8093, where it works
        if secure:
            return secure
        ip = local_address()
        return "http://%s:%d" % (ip, self.PORT) if ip else None

    def home_url(self, u):
        """Where a phone at home types the code (the TV's "or open … and type …"): the remote's own address, never the
        relay's (from the internet, that takes only the QR code's long link)."""
        if u and not secure_remote.relayed(u):
            return u
        ip = local_address()
        return "http://%s:%d" % (ip, self.PORT) if ip else None

    def status(self):
        u = self.url()
        return {"url": u, "pair_url": u + "/r/" + self.link if u else None,      # (the long link: it works while typing rests)
                "home_url": self.home_url(u), "code": self.code, "phones": len(self._load()),
                "home_at": getattr(self, "home_at", 0),     # a remote last open on the home network
                "hotspot": network.hotspot, "wired": network.wired(), "problem": None if u else network.problem}

    MISSES, MISS_WINDOW = 10, 600                          # wrong four-digit codes in ten minutes: typing rests

    def pair(self, code, name, on_own_wifi=False, relayed=False):
        """A phone with the code on the TV (each code works once); or one on the box's own Wi-Fi, whose password is on
        the TV too (its sign-in sheet pairs it, see Captive). Through the relay (from anywhere), only the QR code's
        long link: four digits could be guessed at from the internet. At home too, they could be worked through (10,000
        of them, a minute's work for a laptop on the Wi-Fi): after MISSES wrong ones in MISS_WINDOW, typed codes stop
        working for a while and the code changes; the QR code (its long link) works all along."""
        handoff = getattr(self, "handoff_link", None)
        link = str(code) == self.link or (bool(handoff) and str(code) == handoff)
        if not on_own_wifi and not link:
            if not code or relayed:
                return None
            now = steady()
            self.misses = [t for t in self.misses if now - t < self.MISS_WINDOW]
            if len(self.misses) >= self.MISSES:
                return None                                # being guessed at: typing rests
            if str(code) != self.code:
                self.misses.append(now)
                if len(self.misses) >= self.MISSES:
                    self.code = self._new_code()           # (whatever was learnt from the guesses is no use)
                    print("Phone remote: %d wrong codes typed; typing rests for %d minutes" % (self.MISSES, self.MISS_WINDOW // 60),
                          file=sys.stderr, flush=True)
                return None
        token = os.urandom(24).hex()
        phones = self._load()
        phones[token] = {"name": str(name or "Phone")[:40], "at": int(time.time())}
        write_durably(self.path, json.dumps(phones), 0o600)
        if not on_own_wifi and handoff and str(code) == handoff:
            self.handoff_link = None                       # the setup's phone carried on: its own link, used once
            network.pending_link = None
            network.keep_joined()
        elif not on_own_wifi:
            self.code, self.link = self._new_code(), os.urandom(12).hex()   # each code works once
        toast("%s is a remote now." % phones[token]["name"])
        return token

    def resting(self):
        """Typed codes resting after too many wrong ones (pair)."""
        return len([t for t in self.misses if steady() - t < self.MISS_WINDOW]) >= self.MISSES

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
            # every key of a keyboard, not only the remote's: udev calls a device a keyboard (and the screen, cage, then
            # listens to it) only when it has the whole first row of keys
            keys = set(range(ecodes.KEY_ESC, ecodes.KEY_MICMUTE + 1)) | {ecodes.ecodes[k] for k in self.KEYS.values()}
            self.kb = UInput({ecodes.EV_KEY: sorted(keys)}, name="Sofa box phone remote")
            # The touchpad: a pointer the box puts where it wants (absolute, like a tablet), so it can start from the
            # middle of the screen and go out of the way, to a corner, when it's not used (a mouse is drawn mid-screen
            # by the screen's shell, cage, and stays there). The box moves it with its own acceleration.
            self.mouse = UInput({ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT],
                                 ecodes.EV_ABS: [(ecodes.ABS_X, (0, 0, self.SPAN, 0, 0, 0)), (ecodes.ABS_Y, (0, 0, self.SPAN, 0, 0, 0))],
                                 ecodes.EV_REL: [ecodes.REL_WHEEL]}, name="Sofa box phone touchpad")
            self.ecodes = ecodes
            time.sleep(0.5)                                # a new device takes a moment to be picked up
            self._park()
        except Exception:                                  # no evdev or no /dev/uinput (a preview): through the browser
            self.kb = self.mouse = None
        return self.kb

    def key(self, name):
        if name == "home":
            player.stop(save=True, reason="back")
            return go_home()
        if player.proc and player.proc.poll() is None:     # a video in the box's player: the remote works it
            if player.menu and name in ("up", "down", "left", "right", "ok", "back", "menu"):     # (the options menu, open)
                return player.menu_key({"menu": "back"}.get(name, name))
            # the player screen's own keys, as the TV's remote and a controller press them (OK skips an intro or pauses,
            # skips add up, up and down show where it is), so the phone works the same player the same way
            screen = lambda b: lambda: player.command("script-binding", "sofa_player/" + b)
            live = bool((player.payload or {}).get("live"))
            act = {"ok": screen("ok"), "back": lambda: player.stop(save=True, reason="back"), "play": screen("toggle"),
                   "left": screen("back10"), "rewind": screen("back10"), "right": screen("on30"), "forward": screen("on30"),
                   "up": (lambda: player.zap(-1)) if live else screen("show"),
                   "down": (lambda: player.zap(1)) if live else screen("show"), "menu": player.menu_toggle}.get(name)
            if act:
                return act()
        code = self.KEYS.get(name)
        if not code:
            raise ValueError("Which key?")
        if browser and browser.connected():               # straight into the page in front: it always arrives
            return browser.press(*self.DOM[code])
        kb = self._devices()                               # (no browser to talk to: as a keyboard)
        if kb:
            c = self.ecodes.ecodes[code]
            kb.write(self.ecodes.EV_KEY, c, 1)
            kb.write(self.ecodes.EV_KEY, c, 0)
            kb.syn()

    def text(self, t):
        if browser and browser.connected():
            browser.insert_text(str(t)[:500])

    SPAN = 32767                                           # the touchpad's positions: 0 to SPAN across the screen
    PARK_AFTER = 6                                         # seconds unused, then the pointer goes to a corner

    def _place(self):
        e = self.ecodes
        self.mouse.write(e.EV_ABS, e.ABS_X, int(self.at[0] * self.SPAN))
        self.mouse.write(e.EV_ABS, e.ABS_Y, int(self.at[1] * self.SPAN))

    def _park(self, nudge=False):
        """Out of the way: the bottom right corner (only its tip could show there; pages hide it anyway). `nudge`: from
        just beside it, so it really moves (the kernel drops a move to where the pointer is already)."""
        if self.mouse:
            if nudge:
                self.at = [0.995, 0.995]
                self._place()
                self.mouse.syn()
            self.at, self.parked = [1.0, 1.0], True
            self._place()
            self.mouse.syn()

    def park_now(self):
        """Home is on the screen: the pointer to its corner, through the page, which hides it. At a start the screen's
        shell (cage) draws its own black arrow mid-screen as soon as anything can point, and nothing hid it until the
        pointer first moved (a controller's stick). Not while a phone is using it."""
        if self._devices() is not None and self.mouse and steady() - self.used > self.PARK_AFTER:
            self._park(nudge=True)

    @staticmethod
    def accelerate(d):
        """A finger's move on the phone (CSS pixels) -> a share of the screen: slow moves are precise, quick ones
        cross the screen (about 2.6 screen pixels per phone pixel, up to 3 times that when fast)."""
        gain = 2.6 * min(3.0, 1 + abs(d) / 14.0)
        return d * gain / 1920.0

    def pointer(self, dx=0, dy=0, click=None, scroll=0):
        if not self._devices() or not self.mouse:
            return
        e = self.ecodes
        now = steady()
        woke = self.parked or now - self.used > self.PARK_AFTER
        if woke:                                                        # back from the corner: from the middle
            self.at, self.parked = [0.5, 0.5], False
            self._place()
        if woke and not (dx or dy):
            click = None                       # (the first tap only brings the pointer back: it doesn't press what's there)
        self.used = now
        if dx or dy:
            self.at[0] = max(0.0, min(1.0, self.at[0] + self.accelerate(max(-300, min(300, dx)))))
            self.at[1] = max(0.0, min(1.0, self.at[1] + self.accelerate(max(-300, min(300, dy))) * 16 / 9))
            self._place()
        if not self.parker:                                  # unused for a while: to the corner
            self.parker = threading.Thread(target=self._parker, daemon=True, name="touchpad-park")
            self.parker.start()
        if scroll:
            self.mouse.write(e.EV_REL, e.REL_WHEEL, int(max(-10, min(10, scroll))))
        if click in ("left", "right"):
            b = e.BTN_LEFT if click == "left" else e.BTN_RIGHT
            self.mouse.write(e.EV_KEY, b, 1)
            self.mouse.syn()
            self.mouse.write(e.EV_KEY, b, 0)
        self.mouse.syn()

    def _parker(self):
        while True:
            time.sleep(1)
            if not self.parked and steady() - self.used > self.PARK_AFTER:
                self._park()

    @staticmethod
    def volume(by):
        env = dict(os.environ, XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid())
        step = max(-20, min(20, int(by or 0))) if by != "mute" else 0
        if shutil_which("wpctl"):                          # PipeWire's own (the card has no pactl)
            args = ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"] if by == "mute" else \
                ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "%d%%%s" % (abs(step), "+" if step >= 0 else "-")]
        else:
            args = ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"] if by == "mute" else \
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "%+d%%" % step]
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
pairing_helper = PairingHelper(bluetooth.accepting)
network = Network()
phone = None                                              # PhoneRemote, made in main() (it reads the box's settings)


def setup_state():
    """Everything the first-start steps and Settings show about remotes, Wi-Fi and Bluetooth."""
    s = settings()
    code, ssid = run(["iwgetid", "-r"], 5)
    ssid = ssid if code == 0 else ""

    def safely(fn, default):                             # one part not working mustn't blank the whole setup screen
        try:
            return fn()
        except Exception as exc:
            print("Setup screen, %s: %s" % (getattr(fn, "__name__", "?"), exc), file=sys.stderr, flush=True)
            return default
    return {"remote": safely(phone.status, None) if phone else None,
            "bluetooth": safely(bluetooth.listing, {"devices": [], "scanning": False}),
            "network": {"wired": safely(network.wired, False), "wifi": ssid or None, "address": local_address(), "hotspot": network.hotspot,
                        "networks": network.cached, "problem": network.problem, "joining": network.joining,
                        "clients": safely(network.clients, 0), "phone_at": network.phone_at,
                        "from_phone": getattr(network, "from_phone", 0)}, "secure": safely(secure_remote.status, None),
            "now": steady(),                               # the clock those times are on (steady): "how long ago" by it
            "power": power["note"] if power["note"] and power["note"]["kind"] != "ok" else None,   # (the setup says so too)
            "welcomed": s["welcomed"], "setup_step": s.get("setup_step", 0), "name": s["boot_text"],
            "theme": s["theme"], "timezone": safely(current_timezone, "UTC"), "tz_set": bool(s.get("tz_set"))}


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


# Updates come from one of two channels (Settings → Software). Stable, the default: the version marked stable in
# deploy/sofa-box/STABLE on main (tried on a real box), once its own release (box-os-v<version>) is there. Testing: main's
# newest (VERSION). `sofa-box update` installs the same one.
NEWEST_URL = "https://raw.githubusercontent.com/krintoxi/sofa/main/deploy/sofa-box/VERSION"
STABLE_URL = "https://raw.githubusercontent.com/krintoxi/sofa/main/deploy/sofa-box/STABLE"
RELEASE_URL = "https://raw.githubusercontent.com/krintoxi/sofa/box-os-v%s/deploy/sofa-box/VERSION"
_newest = {"at": 0, "version": None, "stable": None, "looked": 0}


def newer(a, b):
    try:
        return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))
    except (AttributeError, ValueError):
        return False


def version_in(text):
    """The version in one of GitHub's small files (VERSION; STABLE, with its notes: the line that's a version)."""
    for line in (text or "").splitlines():
        if re.match(r"^\d+\.\d+\.\d+$", line.strip()):
            return line.strip()
    return None


def fetch_text(url):
    """A small file from GitHub: its text, "" if it isn't there, None if GitHub couldn't be reached."""
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return r.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return "" if exc.code == 404 else None
    except (OSError, ValueError):
        return None


def look_for_updates():
    """What each channel has on GitHub now: main's newest, and the version marked stable if it has a release of its own
    (a version that never got a card isn't offered). False if GitHub couldn't be reached (what it knew stays)."""
    testing, stable = fetch_text(NEWEST_URL), fetch_text(STABLE_URL)
    if testing is None or stable is None:
        return False
    stable = version_in(stable)
    if stable and stable != _newest["stable"]:
        released = fetch_text(RELEASE_URL % stable)
        if released is None:
            return False
        stable = stable if version_in(released) == stable else None
    _newest.update(version=version_in(testing), stable=stable, looked=time.time())
    return True


def offered(channel, stable, testing, current):
    """The Sofa Box OS a box is offered, or None. Stable (the default): the stable version only. Testing: main's newest
    (or the stable one, if that's ahead). Never one that isn't newer than the box's own."""
    v = testing if channel == "testing" and testing and not newer(stable or "0.0.0", testing) else stable
    return v if v and newer(v, current) else None


def newest_version():
    """A newer Sofa Box OS for this box's channel, if there is one (looked up in the background, once a day); else None."""
    if os.environ.get("SOFA_BOX_NEWEST") == "0":
        return None
    if time.time() - _newest["at"] > 86400:
        _newest["at"] = time.time()
        threading.Thread(target=look_for_updates, daemon=True).start()
    return offered(settings().get("channel"), _newest["stable"], _newest["version"], OS_VERSION)


def software():
    """Settings → Software: the box's channel, what each channel has (once it has looked), whether this box's version is
    the stable one or one being tested, and its last update by itself."""
    s, st = settings(), _newest["stable"]
    return {"channel": "testing" if s.get("channel") == "testing" else "stable", "stable": st, "testing": _newest["version"],
            "looked": _newest["looked"] or None, "auto": s.get("auto_update") == "weekly", "weekly": s.get("update_week") or {},
            "is": None if not _newest["looked"] else "stable" if st == OS_VERSION else
                  "older" if st and newer(st, OS_VERSION) else "testing"}


def update_box():
    """Update the box (Settings → Software): it looks on GitHub first (the daily look may be a day old), then installs
    what its channel offers (`sofa-box update`, its own service: the box restarts by itself when it's done). On Stable,
    nothing unless a newer stable version is there; on Testing, main's newest, as it always did."""
    if os.environ.get("SOFA_BOX_NEWEST") != "0" and not look_for_updates():
        return {"ok": False, "message": "The box couldn't reach GitHub to look for an update. Is it online?"}
    channel, st, main = software()["channel"], _newest["stable"], _newest["version"]
    v = offered(channel, st, main, OS_VERSION)
    if not v and channel == "stable":
        return {"ok": True, "message": "No version is marked stable yet, so the box stays as it is." if not st else
                "This box has Sofa Box OS %s, the stable version." % st if st == OS_VERSION else
                "This box's Sofa Box OS %s is newer than the stable version (%s): it stays as it is." % (OS_VERSION, st)}
    if not v and main and newer(OS_VERSION, main):
        return {"ok": True, "message": "This box's Sofa Box OS %s is newer than main's newest (%s): it stays as it is." % (OS_VERSION, main)}
    threading.Thread(target=lambda: run(["sudo", "-n", os.path.join(HERE, "sofa-box"), "update"], 1800), daemon=True).start()
    return {"ok": True, "version": v, "message": "Updating to %s from GitHub. The box restarts by itself when it's done (a few minutes)."
            % ("Sofa Box OS " + (v or main) if v or main else "the newest Sofa Box OS")}


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
            meminfo = f.read()
        mem = int(re.search(r"MemTotal:\s+(\d+)", meminfo).group(1)) * 1024
        free = re.search(r"MemAvailable:\s+(\d+)", meminfo)            # (what's left for more: the games check shows it)
        free = int(free.group(1)) * 1024 if free else None
    except (OSError, AttributeError):
        mem = free = None
    return {"version": OS_VERSION, "newest": newest_version(), "model": model() or "this computer", "memory": mem, "memory_free": free, "temperature": temp,
            "wifi": ssid or None, "address": local_address(), "server": server(), "server_name": (found.get(server()) or {}).get("name"),
            "settings": {k: s[k] for k in ("quality", "hwdec", "audio", "theme", "boot_text", "performance", "boot_sound", "weather", "weather_units",
                                           "channel", "auto_update", "home_layout", "icon_style")}, "software": software(),
            "weather_place": s.get("weather_place") or zone_place(current_timezone()), "weather_picked": bool(s.get("weather_place")),
            "choices": CHOICES, "learned_720": s["learned_720"], "learned_lite": bool(s.get("learned_lite")),
            "max_height": max_height(), "slow_board": slow_board(), "light": light(), "board": board(), "controllers": controllers,
            "power": power["note"], "os": os_name()}


def local_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


REPORT_URL = re.compile(r"""\b((?:https?|wss?|file)://[^/\s"'<>]*)(/[^/?#\s"'<>]*)?([^\s"'<>]*)""")
REPORT_PATH = re.compile(r"(?<![\w.:/-])(/(?:media|mnt|run/media|home/[^/\s]+)/)[^\n|]*")
REPORT_SECRET = re.compile(r"""(?i)\b(secret|password|psk|token|cookie)("?\s*[:=]\s*)("[^"]*"|\S+)""")
REPORT_MAX = 190000                                         # the certificate service takes 200,000 characters
_report = {"at": 0}


def scrub(text):
    """What a report says of addresses: their site and first folder (no titles, ids or keys after it); of files on
    drives and in the box's folders, only where they are; passwords and secrets blanked."""
    text = REPORT_URL.sub(lambda m: m.group(1) + (m.group(2) or "") + ("/…" if m.group(3) else ""), text)
    return REPORT_SECRET.sub(r"\1\2•••", REPORT_PATH.sub(r"\1…", text))


def memory_lines():
    """A report's "Memory and processor": the box's memory now, who holds it, the times it ran low; the processor, its
    load, what decodes video, and how the player is set for this box."""
    b, free, swap, psi = board(), boxos.available_mb(), boxos.swap_used_mb(), boxos.pressure()
    try:
        load = " ".join("%.2f" % x for x in os.getloadavg())
    except (OSError, AttributeError):
        load = "?"
    cache = [a.split("=", 1)[1].replace("MiB", " MB") for a in boxos.mpv_cache(b["memory_mb"])]
    return ["== Memory and processor",
            "  memory: %d MB, %s MB free now; compressed (zram) in use: %s MB%s" % (
                b["memory_mb"], free if free is not None else "?", swap if swap is not None else "?",
                "; waited for memory %.1f%% of the last 10 s, %.1f%% of the last minute" % psi if psi else ""),
            "  the graphics chip's and the video decoder's own memory (CMA): %s" % (
                "%d MB, %d MB free now (the kernel's refusals of it are counted in the checks below)" % boxos.cma_mb()
                if boxos.cma_mb() else "none set aside here"),
            "  who holds it: " + (", ".join("%s %d MB%s" % (g, mb, " (%d)" % n if n > 1 else "") for g, mb, n in boxos.memory_users())
                                  or "(can't be read here)"),
            "  memory ran low (under %d MB free): %s" % (low_memory_mb(), "; ".join(LOW_MEMORY) or "never since the box started"),
            "  processor: %s, %d core%s, load %s%s" % (b.get("cpu") or "?", b["cores"], "" if b["cores"] == 1 else "s", load,
                                                     ", " + b["vm"] if b.get("vm") else ""),
            "  video decoding: %s; the player reads %s ahead and keeps %s behind%s" % (
                ", ".join(b.get("video") or []) or "the processor only", cache[0], cache[1],
                ", %d threads" % max(1, b["cores"]) if slow_board() else "")]


def report_text():
    """What Send a report sends: the box and how it's doing, the pages' errors and their video players' messages
    (Browser.notes), mpv's last words, then the checks and the logs since it started (sofa-box report). No titles:
    the player's and the pages' aren't in it, and addresses are cut down (scrub); no codes or passwords."""
    def safely(fn, *args):
        try:
            return fn(*args)
        except Exception as exc:
            return "(%s)" % exc
    s = settings()
    out = ["Sofa Box OS %s (for Sofa's pages: %s), %s" % (OS_VERSION, VERSION, time.strftime("%Y-%m-%d %H:%M:%S %Z")),
           "board: " + json.dumps(board()),
           "power: " + str(safely(power_words, power["note"])),
           "settings: " + json.dumps({k: s.get(k) for k in list(CHOICES) + ["secure_remote", "shield", "welcomed"]}),
           "network: " + json.dumps({"wired": safely(network.wired), "address": local_address(), "own_wifi": bool(network.hotspot),
                                     "problem": network.problem, "joining": network.joining, "phones_on_own_wifi": safely(network.clients)}),
           "secure remote: " + json.dumps(safely(secure_remote.status)),
           "phone remote: " + json.dumps({k: v for k, v in (safely(phone.status) if phone else {}).items()
                                          if k in ("url", "phones", "home_at", "problem")} if phone else None),
           "Sofa: " + str(server() or "none chosen"),
           "player: " + json.dumps({k: v for k, v in player.status.items() if k not in ("title", "sub")}),
           "mpv said: " + " | ".join(getattr(player.proc, "sofa_err", None) or ["(nothing)"]),
           "player stopped by itself: " + json.dumps(player.failures or "never, since the box started"),
           "videos played (newest last): " + (" | ".join(Player.ran_line(r) for r in list(player.ran)) or "none since the box started"),
           "Bluetooth pairings asked: " + json.dumps(pairing_helper.said or "none since the box started")]
    out.append("the TV's screen started again by hand: " + ("; ".join(rescues()) or "never"))
    if browser:
        out.append("Home after a game or an app: " + ("; ".join(browser.said) if browser.said else "came back each time"))
        look = safely(tv_picture)
        out.append("the TV now: " + ("%(colour)s over %(share)s of it%(what)s" % dict(look, what=", ONE FLAT COLOUR" if look["flat"] else "")
                                     if isinstance(look, dict) else "not looked at (a video, a game, asleep, or no grim on this box)"))
        out.append("apps closed behind Home (after %d s out of sight): %s" % (
            leave_after(), "; ".join(browser.gave_back) if browser.gave_back else "none since the box started"))
        out.append("browser: %s, in front: %s" % ("connected" if browser.connected() else "not connected", browser.front_app()))
        out += ["  %s%s %s" % (t["app"], " (asleep)" if t["frozen"] else "", t["url"]) for t in safely(browser.running) or []]
        out += ["== Sound in the apps (a wait is sound that stopped until more arrived: the network, or its server)"]
        out += safely(browser.sound_lines) or ["(no app has played anything)"]
        out += ["== The pages and their video players"] + (list(browser.notes) or ["(nothing)"])
        out += ["== How quickly the pages answer the remote (look: %s%s)" % ("light" if light() else "full",
                                                                         ", chosen by the box" if settings().get("learned_lite") else "")]
        out += smooth_lines(safely(browser.smoothness) or {}) or ["(no presses yet)"]
        out.append("  the browser draws with the graphics chip: %s" % safely(browser.gpu))
        problems = safely(browser.gpu_problems)
        if isinstance(problems, dict):
            for head, lines in problems.items():
                out.append("  chrome://gpu, %s: %s" % (head, " | ".join(lines) or "none"))
        else:
            out.append("  chrome://gpu: %s" % (problems or "it didn't say"))
    lines = safely(memory_lines)
    out += lines if isinstance(lines, list) else ["== Memory and processor", "  (%s)" % lines]
    code, logs = run(["sudo", "-n", os.path.join(HERE, "sofa-box"), "report"], 90)
    if code != 0 and "== Sofa Box OS" not in logs:            # a box installed before reports: what it can see itself
        logs = run([os.path.join(HERE, "sofa-box"), "doctor"], 60)[1] + "\n\n" + run(["journalctl", "-b", "--no-pager", "-n", "400"], 30)[1]
    text = scrub("\n".join(out) + "\n\n" + logs)
    return text if len(text) <= REPORT_MAX else text[:REPORT_MAX // 3] + "\n…\n" + text[-(REPORT_MAX * 2 // 3 - 10):]


def send_report():
    """Settings -> Help -> Send a report (and the phone's "Something wrong?"): only when someone presses it, to the
    Sofa Box certificate service, which keeps it for us to read. A box with an id there signs it with its secret."""
    if SecureRemote.SERVICE == "0":
        return {"ok": False, "message": "This box has no certificate service to send reports to."}
    if steady() - _report["at"] < 30:
        return {"ok": True, "report": _report.get("code"), "message": "Sent a moment ago: its number is %s." % _report.get("code")}
    if network.hotspot:
        return {"ok": False, "message": "The box needs the internet to send a report: give it your Wi-Fi first."}
    text = report_text()
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        fd = os.open(os.path.join(CONF_DIR, "last-report.txt"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
    acct, body = secure_remote.account(), {"report": text}
    if acct.get("id") and not acct.get("unregistered"):   # (an id the service hasn't taken yet would be "Unknown box")
        body.update(id=acct["id"], secret=acct["secret"])
    try:
        got = secure_remote.call("/v1/report", body, timeout=60)
    except (OSError, ValueError) as exc:
        return {"ok": False, "message": "The report couldn't be sent: %s. Try again in a minute." % exc}
    _report.update(at=steady(), code=got.get("report"))
    return {"ok": True, "report": got.get("report"), "message": "Report sent. Its number is %s." % got.get("report")}


def box_action(a, data):
    if a == "send-report":
        return send_report()
    if a == "park-pointer":                       # Home, just shown: the pointer out of sight (PhoneRemote.park_now)
        if phone:
            threading.Thread(target=phone.park_now, daemon=True, name="park").start()
        return {"ok": True}
    if a == "pair-controller":
        threading.Thread(target=lambda: run([os.path.join(HERE, "sofa-box"), "pair-controller"], 60), daemon=True).start()
        return {"ok": True, "message": "Put the controller in pairing mode now (Xbox: hold the pair button until it flashes fast)."}
    if a == "wifi-scan":
        return network.hotspot and {"ok": True, "networks": network.cached} or network.scan()
    if a == "wifi-connect":
        return network.join_soon(data.get("ssid", ""), data.get("password"))
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
    if a == "update":                              # a newer Sofa Box OS from GitHub, for the box's channel (a few minutes)
        return update_box()
    if a == "forget-720":
        save_settings(learned_720=False)
        return {"ok": True}
    if a == "apply-boot":                          # the boot screen in the box's theme and name (takes a minute)
        boot_screen.want()
        return {"ok": True, "message": "The new boot screen shows from the next start."}
    return {"ok": False, "message": "Unknown action."}


class BootScreen:
    """The boot screen in the box's theme and name. Making it rebuilds the Pi's start-up files (a minute of the whole
    processor on a Pi 3), so: once, 30 seconds after the last change (a theme and a name at the setup are one), never
    in the first minutes after the setup or a start (Home, the apps and Sofa loading: the box's busiest moment, and a
    Pi 3 working flat out then, on a weak power supply, can restart), not while a video plays or the processor is
    busy, at the lowest priority in a service of its own (sofa-box apply-boot), never two at once, and written out
    to the card before it's done (a restart in the middle mustn't leave the box unable to start)."""
    QUIET, SETTLE, BUSY_FOR = 30, 180, 1200

    def __init__(self):
        self.at, self.thread, self.welcomed_at = 0, None, 0

    def want(self):
        self.at = steady()
        if not (self.thread and self.thread.is_alive()):
            self.thread = threading.Thread(target=self._run, daemon=True, name="boot-screen")
            self.thread.start()

    def welcomed(self):
        """The setup was just finished."""
        self.welcomed_at = steady()

    @staticmethod
    def calm():
        """The processor isn't busy: the last minute's load under about half the cores (always true where it can't
        be told)."""
        try:
            return os.getloadavg()[0] < max(1.5, (os.cpu_count() or 1) * 0.6)
        except (OSError, AttributeError):
            return True

    def due(self, now=None):
        now = now or steady()
        if now - self.at < self.QUIET or not settings()["welcomed"] or playing():
            return False
        settled = max(self.at + self.QUIET, self.welcomed_at, STARTED) + self.SETTLE
        return now >= settled and (self.calm() or now >= settled + self.BUSY_FOR)   # (busy for ever: after a while anyway)

    def _run(self):
        while True:
            time.sleep(5)
            if not self.due():
                continue
            done_for = self.at
            code, out = run(["nice", "-n", "19", "ionice", "-c", "3", "sudo", "-n", os.path.join(HERE, "sofa-box"),
                             "apply-boot", SETTINGS], 600)
            run(["sync"], 60)
            if code != 0:
                print("The boot screen: %s" % out[-300:], file=sys.stderr, flush=True)
            if self.at == done_for:                    # (no change while it was being made)
                return


boot_screen = BootScreen()


class WeeklyUpdate:
    """Settings → Software → Update by itself every week (off until someone switches it on; Stable only). Once a week,
    at night (3 to 5 o'clock where the box is), with the setup done, nothing playing and no game open, the box looks on
    GitHub and installs a newer stable version if there is one, as Update the box does. One that didn't take (the box
    still has its old version: no internet, say) is tried again the next night, three nights at most, then the next
    week. Kept in the settings ("update_week"): when it looks next, and the last update it started."""
    WEEK, NIGHT, AGAIN, TRIES = 7 * 86400, (3, 5), 18 * 3600, 3

    @staticmethod
    def hour(now):
        """The hour where the box is (its time zone, which the setup may have set after the agent started)."""
        try:
            import datetime
            import zoneinfo
            return datetime.datetime.fromtimestamp(now, zoneinfo.ZoneInfo(current_timezone())).hour
        except Exception:                                   # (Python 3.8 and older, or no time zone data)
            return time.localtime(now).tm_hour

    @staticmethod
    def busy():
        return playing() or bool(games.proc and games.proc.poll() is None)

    def due(self, now):
        s = settings()
        return (s.get("auto_update") == "weekly" and s.get("channel") != "testing" and bool(s.get("welcomed"))
                and self.NIGHT[0] <= self.hour(now) < self.NIGHT[1] and now >= (s.get("update_week") or {}).get("next", 0)
                and not self.busy())

    def look(self, now):
        """The week's look (or the next night's): True if it started an update."""
        w = dict(settings().get("update_week") or {})
        v = offered("stable", _newest["stable"], _newest["version"], OS_VERSION) if look_for_updates() else False
        tries = (w.get("tries", 0) + 1 if v == w.get("to") else 1) if v else 0
        if v is False:                                      # GitHub out of reach: the next night
            w["next"] = now + self.AGAIN
        elif v and tries <= self.TRIES:                     # (the next night again, if it didn't take)
            w.update(to=v, came_from=OS_VERSION, at=now, tries=tries, next=now + self.AGAIN)
            save_settings(update_week=w)
            run(["sudo", "-n", os.path.join(HERE, "sofa-box"), "update"], 1800)
            return True
        else:                                               # nothing newer, or three nights didn't take: next week
            w.update(tries=0, next=now + self.WEEK - 6 * 3600)          # (a few hours early: the same night each week)
        save_settings(update_week=w)
        return False

    def watch(self):
        while True:
            time.sleep(600)
            try:
                if self.due(time.time()):
                    self.look(time.time())
            except Exception as exc:
                print("The weekly update: %s" % exc, file=sys.stderr, flush=True)


weekly_update = WeeklyUpdate()


def box_state():
    """What's on, for the start page and the preview."""
    p = player.status
    with _lock:
        return {"chosen": server(), "name": (found.get(server()) or {}).get("name"),
                "found": [{"url": u, "name": v["name"]} for u, v in sorted(found.items())],
                "playing": dict(p) if p else None, "address": local_address(), "version": OS_VERSION}


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
  window.SofaBox = { version: "%(version)s", os: "%(os)s", slow: %(slow)s, theme: "%(theme)s" };
  var CAPS = %(caps)s;                   // what the box's player plays (asked of the page once, as it starts: no waiting)
  var html = document.documentElement, onTop = false;
  if (window.SofaBox.slow) {             // a Pi 3: lighter effects, and the banner stays still unless asked
    html.classList.add("box-lite");
    try {                                // (and no trailers: each is a video the browser plays itself, in the page)
      if (localStorage.getItem("sofa.bannerClips") === null) localStorage.setItem("sofa.bannerClips", "false");
      if (localStorage.getItem("sofa.trailers") === null) localStorage.setItem("sofa.trailers", "false");
    } catch (e) {}
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
  function send(m, body) {
    return fetch("/box/native/" + m, { method: "POST", headers: { "X-Sofa-Box": "1" }, body: body })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r; });
  }
  function post(path, body) {
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Sofa-Box": "1" }, body: JSON.stringify(body || {}) });
  }
  window.SofaNative = {
    version: function () { return "1"; }, appVersion: function () { return "0"; },
    caps: function () { return JSON.stringify(CAPS); }, status: function () { return call("status"); },
    // Play and control don't hold the page up (they were a synchronous request: the page froze while mpv started)
    play: function (json) {
      cover(true);
      send("play", json).catch(function () {
        cover(false);
        var p = {}; try { p = JSON.parse(json); } catch (e) {}
        if (window.sofaNativeDone) window.sofaNativeDone({ item: p.item, failed: true, error: "the box's player didn't answer" });
      });
    },
    control: function (json) { send("control", json).catch(function () {}); },
    servers: function () { return call("servers"); },
    choose: function (id) { post("/box/api/sofa/open", { id: id }); },
    forget: function () { post("/box/api/sofa/chooser"); }
  };
  var since = null;
  (function events() {
    fetch("/box/native/events" + (since === null ? "" : "?since=" + since)).then(function (r) { return r.json(); }).then(function (e) {
      since = e.n;
      (e.news || []).forEach(function (n) {
        if (n.playing && window.sofaNativePlaying) window.sofaNativePlaying(n.playing);
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
    return NATIVE_JS % {"version": VERSION, "os": OS_VERSION, "slow": "true" if light() else "false", "caps": json.dumps(caps()),
                        "theme": settings().get("theme") if settings().get("theme") in THEMES else "street"}


def finder_page():
    with open(os.path.join(HERE, "finder.html"), encoding="utf-8") as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Small answers go at once: with Nagle's algorithm on, a kept-alive connection's answer (written as its headers,
    # then its body) waited for the phone to acknowledge the headers, which phones put off by up to 200 ms.
    disable_nagle_algorithm = True

    def log_message(self, *args):
        pass

    def send(self, body, ctype="application/json", status=200, headers=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if "Cache-Control" not in (headers or {}):              # (unless it's said: an app's icon at one address is kept)
            self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self._headers_buffer.append(b"\r\n")              # the headers and the body in one write (one packet)
        if self.command != "HEAD":
            self._headers_buffer.append(data)
        self.flush_headers()

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
    # What a plain GET may do: show a page, a picture, or how things are. Everything that does something (plays,
    # stops, goes Home, restarts, resets, updates, forgets the phones, pairs Bluetooth...) is a POST with X-Sofa-Box,
    # which a page from another site can't send (it would have to ask first, and the box never says yes). Any site
    # the box's browser opens (an app from the store) could otherwise work the box with an <img> pointed here.
    READ_ONLY = frozenset(("/box/finder", "/box/state", "/box/native.js", "/box/native/caps", "/box/native/status",
                           "/box/native/servers", "/box/native/events", "/box/splash.png", "/box/preview", "/box/files/raw",
                           "/box/api/info", "/box/api/settings", "/box/api/thisbox/internet", "/box/api/weather",
                           "/box/api/weather/places", "/box/api/apps", "/box/api/sofa", "/box/api/sofa/continue",
                           "/box/api/setup", "/box/api/timezone", "/box/api/devices", "/box/api/store", "/box/api/files",
                           "/box/api/files/list", "/box/api/games", "/box/api/shield"))
    READ_ONLY_UNDER = ("/box/home", "/box/icons/", "/box/store-icons/", "/box/games/", "/box/fonts/")

    @classmethod
    def read_only(cls, path):
        return path in cls.READ_ONLY or path.startswith(cls.READ_ONLY_UNDER)

    def route(self):
        path = urllib.parse.urlsplit(self.path).path
        entry = boxservers.by_host(self.headers.get("Host"), servers)
        if not entry and not self.home_host():          # an address that isn't the box's (a rebinding trick)
            return self.send('{"error":"not here"}', status=403)
        if path.startswith("/box/"):
            if entry and not path.startswith(self.SERVER_PAGE_OK):
                return self.send('{"error":"not for this page"}', status=403)
            if self.command in ("GET", "HEAD"):
                if not self.read_only(path):
                    return self.send('{"error":"POST this, with X-Sofa-Box"}', status=405, headers={"Allow": "POST"})
            elif self.headers.get("X-Sofa-Box") != "1":
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
        if path == "/box/native/key":                     # mpv's own keys (Home, Menu, the channel) come here
            self.body()                                   # (read even if empty: on a kept-alive connection the next request follows)
            k = (qs.get("k") or [""])[0]
            if k == "ok":
                player.ok()
            elif k == "back":
                player.stop(save=True, reason="back")
            elif k == "home":                              # Home while a video plays: stop it (place saved), go home
                player.stop(save=True, reason="back")
                go_home()
            elif k in ("chup", "chdown"):                   # Live TV: up and down change the channel
                player.zap(-1 if k == "chup" else 1)
            elif k == "menu":                               # Menu: the video's options (again: closes them)
                player.menu_toggle()
            elif k == "far":                                # the player screen: a skip past what mpv has of a converted video
                try:
                    t = float((qs.get("t") or [""])[0])
                except ValueError:
                    t = -1.0
                if 0 <= t < 1e6:
                    player.seek_to(t, exact=(qs.get("exact") or [""])[0] == "1")
            elif k.startswith("menu-"):
                player.menu_key(k[5:])
            return self.send('{"ok":true}')
        if path == "/box/native/events":
            since = (qs.get("since") or [None])[0]
            return self.send(json.dumps(player.events(int(since) if since and since.isdigit() else None)))
        if path == "/box/api/info":
            return self.send(json.dumps(box_info()))
        if path == "/box/api/settings":
            data = json.loads(self.body() or b"{}") if self.command == "POST" else {}
            changes = {k: v for k, v in data.items() if k in CHOICES and v in CHOICES[k]}
            if "performance" in changes:                        # (chosen again: the box looks again, from now)
                changes["learned_lite"] = False
            if "welcomed" in data:                              # the first-start steps are done
                changes["welcomed"] = bool(data["welcomed"])
                if changes["welcomed"] and not settings()["welcomed"]:
                    boot_screen.welcomed()
                    try:
                        os.remove(os.path.join(CONF_DIR, Network.KEPT))
                    except OSError:
                        pass
            if data.get("setup_step") in (0, 1, 2, 3):          # the step it's at (a restart goes on from there)
                changes["setup_step"] = data["setup_step"]
            if "boot_text" in data:
                changes["boot_text"] = re.sub(r"[^\w '’&.-]", "", str(data["boot_text"]))[:30].strip()
            if "weather_place" in data:                        # Settings -> Weather: a place, or null for the time zone's
                changes["weather_place"] = weather_place(data["weather_place"])
            if "secure_remote" in data:                        # the phone remote over https at home (SecureRemote)
                changes["secure_remote"] = bool(data["secure_remote"])
                secure_remote.wake()
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
    def static(self, base, rel, headers=None):
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
                             headers=headers or {"Cache-Control": "no-store, no-cache"})

    def box_os(self, path, qs):
        data = json.loads(self.body() or b"{}") if self.command == "POST" else {}
        arg = lambda k, d="": (qs.get(k) or [d])[0]   # noqa: E731
        if path in ("/box/home", "/box/home/"):
            return self.static(os.path.join(HERE, "home"), "index.html")
        if path.startswith("/box/home/"):
            return self.static(os.path.join(HERE, "home"), path[len("/box/home/"):])
        if path.startswith(("/box/icons/", "/box/store-icons/")):      # (?w=: at the size Home draws it; ?v=: kept)
            folder, rel = (apps.icons, path[len("/box/icons/"):]) if path.startswith("/box/icons/") else \
                (boxos.store_icons.folder, path[len("/box/store-icons/"):])
            small = boxos.small_icon(folder, rel, int(arg("w")) if arg("w").isdigit() else 0) if arg("w") else None
            keep = {"Cache-Control": "max-age=31536000"} if arg("v") else None
            return self.static(os.path.dirname(small), os.path.basename(small), keep) if small else self.static(folder, rel, keep)
        if path.startswith("/box/fonts/"):                 # Sofa's typefaces (on the box, or in Sofa's folder)
            name = os.path.basename(path)
            for d in (os.path.join(HERE, "fonts"), os.path.join(HERE, "..", "..", "client", "vendor", "fonts")):
                if os.path.isfile(os.path.join(d, name)):
                    return self.static(d, name)
            return self.send('{"error":"not found"}', status=404)
        if path.startswith("/box/games/"):
            return self.static(os.path.join(HERE, "games"), path[len("/box/games/"):] or "index.html")
        if path == "/box/api/thisbox/internet":            # Settings: Sofa on this box, from anywhere
            if self.command == "POST":
                try:
                    return self.send(json.dumps(thisbox_action(json.loads(self.body() or b"{}"))))
                except (OSError, ValueError) as exc:
                    return self.send(json.dumps({"ok": False, "message": str(exc)}))
            return self.send(json.dumps(thisbox_status()))
        if path == "/box/api/weather":
            return self.send(json.dumps(weather()))
        if path == "/box/api/weather/places":
            return self.send(json.dumps(find_places((qs.get("q") or [""])[0])))
        if path == "/box/api/apps":
            s, st = settings(), servers.state()
            default = servers.get(st["default"]) if st["default"] else None
            return self.send(json.dumps({"apps": apps.listing(), "running": browser.running() if browser and browser.connected() else [],
                                         "now": now_playing(),
                                         "devtools": bool(browser and browser.connected()), "sofa": server(),
                                         "sofa_name": (found.get(server()) or {}).get("name"), "theme": s["theme"],
                                         "name": s["boot_text"], "welcomed": s["welcomed"], "setup_step": s.get("setup_step", 0),
                                         "home_layout": s.get("home_layout") or "spotlight", "icon_style": s.get("icon_style") or "glossy",
                                         "slow": light(), "boot_sound": s["boot_sound"],
                                         "default_server": {k: default[k] for k in ("id", "name", "kind", "where")} if default else None,
                                         "ask": st["ask"], "servers": len(st["servers"]),
                                         "devices": {k: devices_seen[k] for k in ("drives", "disc", "n")},
                                         "power": power["note"] if power["note"] and power["note"]["kind"] != "ok"
                                         and not power["shown"] else None,         # (Home's note, once a start)
                                         "front": browser.front_app() if browser and browser.connected() else None}))
        if path == "/box/api/power/seen":                 # Home showed its note: not again until the box starts again
            power["shown"] = True
            return self.send('{"ok":true}')
        if path == "/box/api/sofa/continue":                # Home's "Continue watching"
            return self.send(json.dumps(sofa_continue()))
        if path == "/box/api/sofa":                         # the chooser: servers added, found, free, others
            look_soon(60)                                    # (now, not at its next look in up to a minute)
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
            if data.get("live") and not sid:                 # Live TV: never the chooser (it's the box's own, on Home):
                st = servers.state()                         # the Sofa it opens with, else the last, else this box's Sofa
                sid = st["default"] or st.get("last") or ("box" if local_sofa.available() else None)
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
            if arg("scan") == "1" and not network.is_joining():   # (pairs by itself only at the setup: a GET can't ask for it)
                bluetooth.want(30, autopair=not settings()["welcomed"])
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
                        try:
                            v = int(os.path.getmtime(os.path.join(boxos.store_icons.folder, icon)))
                        except OSError:
                            v = 0
                        e["icon_url"] = "/box/store-icons/%s?v=%d" % (icon, v)
            boxos.store_icons.want([e for sec in st["sections"] for e in sec["apps"]])
            return self.send(json.dumps(st))
        if path == "/box/api/open":
            return self.send(json.dumps(open_app(data.get("id"), data.get("url"), data.get("hash"))))
        if path == "/box/api/home":
            return self.send(json.dumps({"ok": True, "home": go_home()}))
        if path == "/box/api/sleep":                       # (Settings, or the screensaver itself waking)
            if data.get("wake"):
                asleep["on"] = False
            else:
                box_sleep()
            return self.send(json.dumps({"ok": True, "asleep": asleep["on"]}))
        if path == "/box/api/front":                       # Home's "Open now": that very tab back in front
            if browser and browser.connected() and str(data.get("target") or "") in browser.tabs:
                browser.activate(str(data["target"]))
                return self.send('{"ok":true}')
            raise ValueError("That isn't open any more.")
        if path == "/box/api/music":                       # the mini player's buttons
            return self.send(json.dumps(music(str(data.get("act") or ""), data.get("target"))))
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
            if self.command == "POST":
                a = data.get("action")
                if a in ("install", "remove"):
                    return self.send(json.dumps({"ok": True, "job": games.change(str(data.get("id") or ""), a)}))
                if a == "play":
                    return self.send(json.dumps(games.play(str(data.get("id") or ""))))
                if a == "stop":
                    return self.send(json.dumps({"ok": games.stop("asked")}))
                raise ValueError("Install, remove, play or stop.")
            return self.send(json.dumps(games.listing()))
        if path == "/box/api/volume":                   # the controller daemon: the triggers, a remote's volume keys
            level, muted = box_volume(data.get("by"))
            return self.send(json.dumps({"level": level, "muted": muted}))
        if path == "/box/api/pads":                     # the controller daemon: the controllers connected now
            for name in games.heard_pads(data.get("pads")):
                kind = next(p["kind"] for p in games.pads if p["name"] == name)
                toast("%s connected: ready for games." % ("Your %s controller" % PAD_KINDS[kind] if kind != "generic" else name or "A controller"))
            return self.send('{"ok":true}')
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
    disable_nagle_algorithm = True                      # (see Handler)
    COOKIE = "sofa_remote"
    timeout = 120                        # an idle connection from the home network closes (each kept a thread for ever)

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
        if on_own_wifi(self.client_address[0]):              # a phone on the box's own Wi-Fi: keep it on
            network.used = steady()
        path = urllib.parse.urlsplit(self.path).path
        relayed = self.headers.get("X-Sofa-Relay") == "1" and self.client_address[0] in ("127.0.0.1", "::1")   # (Relay below)
        m = re.match(r"^/r/(\d{4}|[0-9a-f]{24})$", path)
        if m:                                               # the QR code on the TV
            token = phone.pair(m.group(1), (self.headers.get("User-Agent") or "").split("(")[-1].split(";")[0].strip() or "Phone",
                               relayed=relayed)
            return self.send("", status=302, headers=dict({"Location": "/" if token else "/?again=1"},
                                                          **({"Set-Cookie": self.cookie(token)} if token else {})))
        if path == "/join":                                  # from the box's own Wi-Fi's sign-in sheet (Captive)
            if not (network.hotspot and on_own_wifi(self.client_address[0])):
                return self.send("", status=302, headers={"Location": "/"})
            token = self.token() if phone.valid(self.token()) else \
                phone.pair(None, (self.headers.get("User-Agent") or "").split("(")[-1].split(";")[0].strip() or "Phone", on_own_wifi=True)
            return self.send("", status=302, headers={"Location": "/?sheet=1", "Set-Cookie": self.cookie(token)})
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "remote.html"), encoding="utf-8") as f:
                return self.send(f.read(), "text/html; charset=utf-8")
        if path in ("/icon.png", "/icon-512.png"):          # the remote's Home Screen icon
            buf = __import__("io").BytesIO()
            module("sofa-box-art").app_icon(settings(), 512 if "512" in path else 180).save(buf, "PNG")
            return self.send(buf.getvalue(), "image/png", headers={"Cache-Control": "max-age=86400"})
        if path == "/manifest.json":                         # Android: "Add to Home screen" as an app
            name = settings().get("boot_text") or "Sofa Box"
            return self.send(json.dumps({"name": name + " remote", "short_name": "Sofa Box", "start_url": "./", "display": "standalone",
                                         "background_color": "#0D0D10", "theme_color": "#0D0D10",       # (relative: the relay too)
                                         "icons": [{"src": "icon.png", "sizes": "180x180", "type": "image/png"},
                                                   {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}]}),
                             "application/manifest+json")
        if self.command == "POST" and self.headers.get("X-Sofa-Remote") != "1":
            return self.send('{"error":"missing X-Sofa-Remote"}', status=400)
        data = json.loads(self.body() or b"{}") if self.command == "POST" else {}
        if path == "/api/pair":
            if relayed:
                return self.send('{"error":"Away from home, scan the code on the TV: typing it works at home only."}', status=403)
            token = phone.pair(str(data.get("code") or "").strip(), data.get("name"))
            if not token:
                return self.send(json.dumps({"error": "Too many wrong codes were typed. Scan the code on the TV instead (typing "
                                                      "works again in a few minutes)." if phone.resting() else
                                             "That code isn't the one on the TV."}), status=429 if phone.resting() else 403)
            return self.send('{"ok":true}', headers={"Set-Cookie": self.cookie(token)})
        if not phone.valid(self.token()):
            return self.send(json.dumps({"paired": False, "name": settings().get("boot_text") or "Sofa Box"}), status=401)
        try:
            if path == "/api/state":
                if on_own_wifi(self.client_address[0]):     # the setup's TV: the remote is open on a phone
                    network.phone_at = steady()
                else:
                    phone.home_at = steady()
                p = player.status
                m = now_playing()
                return self.send(json.dumps({"paired": True, "name": settings().get("boot_text") or "Sofa Box",
                                             "music": m and {k: m.get(k) for k in ("title", "artist", "name", "playing", "can", "front")},
                                             "playing": {k: p.get(k) for k in ("title", "sub", "t", "d", "paused")} if p else None,
                                             "front": browser.front_app() if browser and browser.connected() else None,
                                             "hotspot": bool(network.hotspot), "welcomed": settings()["welcomed"],
                                             "joining": network.joining and dict(network.joining, ago=round(
                                                 steady() - network.joining.get("at", 0), 1)),    # (its clock isn't the box's)
                                             "asleep": asleep["on"]}))
            if path in INPUT_PATHS:
                phone_input(path, data)
            elif path == "/api/power":                      # the phone's power button: the box rests, or wakes
                a = data.get("action") or "toggle"
                if a == "sleep" or (a == "toggle" and not asleep["on"]):
                    box_sleep()
                else:
                    box_wake()
                return self.send(json.dumps({"ok": True, "asleep": asleep["on"]}))
            elif path == "/api/hello":                      # the phone's time zone, for a box that doesn't know its own
                set_timezone(str(data.get("tz") or ""), only_if_unset=True)
            elif path == "/api/wifi":
                return self.send(json.dumps(dict(network.scan() if not network.hotspot else {"ok": True, "networks": network.cached},
                                                 hotspot=bool(network.hotspot))))
            elif path == "/api/wifi/join":
                out = network.join_soon(data.get("ssid") or "", data.get("password"))
                if out.get("ok") and on_own_wifi(self.client_address[0]):   # the setup's phone: where to carry on
                    # (its own link, not the TV's: someone scanning the TV's code meanwhile mustn't use it up)
                    phone.handoff_link = os.urandom(12).hex()
                    out["next"] = secure_remote.handoff(phone.handoff_link)
                    network.from_phone = steady()
                    network.pending_link = phone.handoff_link       # kept on the card once the join works
                return self.send(json.dumps(out))
            elif path == "/api/report":
                return self.send(json.dumps(send_report()))
            elif path == "/api/music":                      # the mini player, on the phone
                return self.send(json.dumps(music(str(data.get("act") or ""))))
            elif path == "/api/screen":                     # Home held on the phone: the TV's screen, again
                if data.get("restart") is not True:
                    raise ValueError("restart?")
                return self.send(json.dumps(rescue("Home held on a phone")))
            else:
                return self.send('{"error":"not found"}', status=404)
        except ValueError as exc:
            return self.send(json.dumps({"error": str(exc)}), status=400)
        return self.send('{"ok":true}')


class InputQueue:
    """What a phone presses, done in the order it was pressed on one thread of its own, while the phone has its answer
    at once. (A press used to be answered only after the browser had taken the key going down and coming up: two
    round trips to Chromium on every press, before the phone could send the next one on that connection.)"""

    def __init__(self):
        self.q, self.cond, self.thread = collections.deque(), threading.Condition(), None

    def put(self, fn, *args):
        with self.cond:
            if len(self.q) > 64:                         # a phone gone wild: the oldest go
                self.q.popleft()
            self.q.append((fn, args))
            if not (self.thread and self.thread.is_alive()):
                self.thread = threading.Thread(target=self._run, daemon=True, name="remote-input")
                self.thread.start()
            self.cond.notify()

    def _run(self):
        while True:
            with self.cond:
                while not self.q:
                    if not self.cond.wait(60):
                        self.thread = None
                        return
                fn, args = self.q.popleft()
            try:
                fn(*args)
            except Exception as exc:
                print("Phone remote: %s" % exc, file=sys.stderr, flush=True)


remote_input = InputQueue()
INPUT_PATHS = ("/api/key", "/api/text", "/api/pointer", "/api/volume")


def phone_key(name):
    if not box_wake():                                   # asleep: a key wakes the box (and does nothing else)
        phone.key(name)


def phone_input(path, data):
    """A press, typing, the touchpad or the volume from a paired phone: checked now, done in order (InputQueue). The
    same for a phone at home and one through the relay. Raises ValueError for what isn't a press."""
    if path == "/api/key":
        k = str(data.get("k") or "")
        if k != "home" and k not in PhoneRemote.KEYS:
            raise ValueError("Which key?")
        remote_input.put(phone_key, k)
    elif path == "/api/text":
        remote_input.put(phone.text, str(data.get("t") or ""))
    elif path == "/api/pointer":
        remote_input.put(phone.pointer, float(data.get("dx") or 0), float(data.get("dy") or 0), data.get("click"), float(data.get("scroll") or 0))
    elif path == "/api/volume":
        remote_input.put(box_volume, data.get("by"))


class SecureRemoteHandler(RemoteHandler):
    """The phone remote over https (SecureRemote); a connection that stalls (its TLS handshake too) gives up."""
    timeout = 30


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
    threading.Thread(target=learn_mpv, daemon=True, name="mpv").start()   # (what mpv can do, before the first video)
    threading.Thread(target=watch_devices, daemon=True, name="devices").start()
    pairing_helper.start()                       # (BlueZ's pairings answered: an Xbox controller pairs)
    threading.Thread(target=watch_power, daemon=True, name="power").start()
    threading.Thread(target=watch_smoothness, daemon=True, name="smoothness").start()
    threading.Thread(target=watch_apps, daemon=True, name="apps").start()
    threading.Thread(target=watch_web_game, daemon=True, name="web-game").start()
    if os.environ.get("SOFA_BOX_NEWEST") != "0":
        threading.Thread(target=weekly_update.watch, daemon=True, name="weekly-update").start()   # (if it's switched on)
    if os.environ.get("SOFA_BOX_ICONS") != "0":
        apps.refresh_icons()                               # sharper app icons, once (boxos.ICONS_VERSION)
    if local_sofa.public():                                # open to the internet: it has to be there, from the start
        threading.Thread(target=local_sofa.ensure, args=(120,), daemon=True, name="this-box-sofa").start()
    phone = PhoneRemote()
    kept = network.resume()                              # restarted in the middle of the setup: on from where it was
    if kept and kept.get("link"):
        phone.handoff_link = kept["link"]
    try:
        remote = Server(("0.0.0.0", PhoneRemote.PORT), RemoteHandler)
        threading.Thread(target=remote.serve_forever, daemon=True, name="phone-remote").start()
    except OSError as exc:
        print("The phone remote can't use port %d: %s" % (PhoneRemote.PORT, exc), file=sys.stderr)
    if SecureRemote.SERVICE != "0":
        threading.Thread(target=secure_remote.watch, daemon=True, name="secure-remote").start()
    if shutil_which("nmcli") and os.environ.get("SOFA_BOX_HOTSPOT", "1") != "0":
        threading.Thread(target=network.watch, daemon=True, name="hotspot").start()
    if not settings()["welcomed"]:                       # a new box: remotes in pairing mode pair by themselves
        bluetooth.want(600, autopair=True)
    httpd = Server(("127.0.0.1", PORT), Handler)
    print("Sofa box agent on http://127.0.0.1:%d" % PORT, file=sys.stderr, flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
