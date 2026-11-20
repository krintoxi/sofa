"""The public demo: a Sofa anyone can open without installing anything, run as its own instance.

The switch is config.demo_on() ("demo": true in config.json, or SOFA_DEMO=1); docs/public-demo.md says how to run
one. With it on:

- Settings: everything in config.DEMO_LOCKED reads as it's set there, and the web can't change it.
- Who: every request counts as the internet (web.Handler.network), whatever address it comes from, so nobody is
  "at home": no admin, setup, sign-in, sign-up, guests, pairing or profiles over the web, and everyone is the public
  library's Visitor. The demo is run from its files (this folder's channels.json, the library's rights records, the
  pages) and the command line.
- Library: only titles whose rights record passes rights.check(), and only ones that can play as they are: from
  their publisher's own address (play_url), or from this server's copy when demo_serve_files is on. Nothing is
  converted, repackaged or relayed.
- Live TV: only the channels in channels.json that pass channel_problems() (below), each played by the browser
  straight from its publisher. The relay at /live/ never answers a Visitor.
- Housekeeping: rate limits per visitor (LIMITS), and a nightly reset of whatever visitors leave behind.
"""
import json
import os
import re
import threading
import time
import urllib.parse

from . import config, rights, store

LIMITS = {
    # kind: (how many, in how many seconds), per visitor address
    "request": (900, 60),        # pages, the app's calls, pictures, and a video's byte ranges while seeking
    "entry": (20, 3600),         # new visitor sign-ins (each is a row in the database until the nightly reset)
}
ENTRIES_PER_HOUR = 3000          # new visitor sign-ins an hour from everyone together
CHANNEL_KINDS = ("us-government", "broadcaster", "public-domain", "cc")
# Free ad-supported TV services (FAST) whose terms forbid playing their streams anywhere but their own apps, the
# distributors that deliver those channels, and the lists that collect them. A channel list may never point at
# them, whatever the stream calls itself.
FAST_HOSTS = (
    "pluto.tv", "plutotv.net", "samsungtvplus.com", "samsung.wurl.tv", "wurl.tv", "wurl.com", "tubi.tv", "tubitv.com",
    "tubi.video", "plex.tv", "plex.direct", "roku.com", "therokuchannel.com", "xumo.com", "xumo.tv", "xumo-ott.com",
    "amagi.tv", "stirr.com", "distro.tv", "lgchannels.com", "freevee.com", "watchfree.vizio.com", "redbox.com",
    "mjh.nz", "jmp2.uk", "iptv-org.github.io", "frequency.stream", "rakuten.tv", "vizio.com",
)
# ...and a stream address that names one of them in its path (a broadcaster's feed made for a FAST service, on a
# shared delivery network: ".../WNNationalSamsung/...", ".../amg01076-...-samsungnz/...")
FAST_PATH = re.compile(r"samsung|pluto|xumo|vizio|rakuten|roku|tubi|plex|freevee|lgchannels|stirr|distro", re.I)
GEO = re.compile(r"geo-?block|\[geo|Ⓖ|vpn|unblock", re.I)
_lock = threading.Lock()
_hits = {}
_entries = []                     # when each of the last hour's new visitor sign-ins was


def on():
    return config.demo_on()


def folder():
    return (config.get("demo_folder") or os.environ.get("SOFA_DEMO_DIR") or os.path.join(config.DATA_DIR, "demo"))


# ---------------------------------------------------------------- titles

def title_ok(entry):
    """A show or movie (as the library lists it) the demo may list: a rights record that passes, and a way to play
    as it is."""
    rec = (entry or {}).get("rights")
    if not rec or rec.get("kind") is None or rights.problems(rec):
        return False
    if "seasons" in entry:                        # a show: at least one episode that plays
        return any(item_ok(ep) for s in entry.get("seasons") or () for ep in s.get("episodes") or ())
    return bool(config.get("demo_serve_files") or rec.get("play_url"))


def item_ok(item):
    """An episode or movie the demo may play."""
    rec = (item or {}).get("rights")
    return bool(rec) and not rights.problems(rec) and bool(config.get("demo_serve_files") or rec.get("play_url"))


def play_plan(item):
    """What /api/play answers on the demo: the video as it is, from its publisher or (when allowed) from here."""
    rec = item.get("rights") or {}
    if not item_ok(item):
        return {"mode": "unsupported", "message": "This title can't play on the demo.", "subtitles": [], "audio": []}
    url = "/media/%s/file" % urllib.parse.quote(item["id"], safe=":") if config.get("demo_serve_files") \
        else rec["play_url"]
    return {"mode": "direct", "url": url, "duration": item.get("duration"), "why": [], "audio": [], "subtitles": [],
            "picture_subtitles": [], "markers": [], "trailer": "direct", "error": None}


# ---------------------------------------------------------------- channels

def channel_problems(c):
    """What keeps a channel from the demo's channel list ([] when it may be listed)."""
    if not isinstance(c, dict):
        return ["not a channel"]
    out = []
    url = str(c.get("url") or "")
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if not str(c.get("name") or "").strip():
        out.append("no name")
    if not url.startswith("https://") or not host:
        out.append("not an https stream")
    if any(host == h or host.endswith("." + h) for h in FAST_HOSTS):
        out.append("a FAST service's stream (%s): their terms allow their own apps only" % host)
    elif FAST_PATH.search(urllib.parse.urlsplit(url).path + "?" + urllib.parse.urlsplit(url).query):
        out.append("a feed made for a FAST service (its address says so): their terms allow their own apps only")
    for k in ("headers", "user_agent", "ua", "referer", "referrer", "http-user-agent", "http-referrer"):
        if c.get(k):
            out.append("asks for a made-up browser name or referrer (%s)" % k)
    if c.get("geo") or GEO.search(str(c.get("name") or "")) or GEO.search(url):
        out.append("limited to its own country, or played from around that limit")
    if c.get("kind") not in CHANNEL_KINDS:
        out.append("kind must be one of %s" % ", ".join(CHANNEL_KINDS))
    if not str(c.get("publisher") or "").strip():
        out.append("no publisher")
    if not str(c.get("page") or "").startswith("https://"):
        out.append("no https page where the publisher offers the stream (page)")
    if len(str(c.get("rights") or "").strip()) < 12:
        out.append("no rights note")
    if c.get("cors") is not True or not rights.DATE.match(str(c.get("checked") or "")):
        out.append("not checked for browser playback yet (tools/demo-seed.py channels --check)")
    logo = c.get("logo")
    if logo and not re.match(r"^[\w.-]+\.(png|jpg|jpeg|webp|svg)$", str(logo)):
        out.append("logo must be a picture file in the demo folder's logos/ (no addresses elsewhere)")
    return out


def channel_file():
    return os.path.join(folder(), "channels.json")


def read_channel_list(path=None):
    try:
        with open(path or channel_file(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return data.get("channels") if isinstance(data, dict) and isinstance(data.get("channels"), list) else []


_told = set()                     # channels already said to be left out (said once, not on every read)


def channels():
    """Live TV's channels on the demo, in the shape sofa/live.py keeps them: only the ones that pass."""
    import hashlib
    out = {}
    for c in read_channel_list():
        bad = channel_problems(c)
        if bad:
            line = "The demo leaves out channel %r: %s" % (str((c or {}).get("name"))[:60], "; ".join(bad))
            if line not in _told:
                _told.add(line)
                store.log("live", line)
            continue
        cid = hashlib.sha1(c["url"].encode()).hexdigest()[:12]
        out[cid] = {"id": cid, "name": str(c["name"])[:80], "url": c["url"], "group": str(c.get("group") or "Channels")[:40],
                    "logo": "/demo/logos/" + c["logo"] if c.get("logo") else None, "tvg": None, "geo": False,
                    "headers": {}, "adult": False, "home": False, "lists": ("demo",), "playlist": "demo",
                    "publisher": str(c["publisher"])[:80], "rights": str(c["rights"])[:300], "page": c["page"]}
    return out


def credits():
    """For the About page: each channel on the demo now, who publishes it, and its rights note."""
    from . import live
    chans = sorted((c for c in live.all_channels() if c.get("playlist") == "demo"), key=lambda c: c["name"].lower())
    return [{"name": c["name"], "publisher": c["publisher"], "rights": c["rights"], "page": c["page"]} for c in chans]


def page_file(which):
    """The terms or the privacy notice, when it's a file in the demo folder (else None)."""
    name = str(config.get("demo_" + which) or "")
    if not name or name.startswith("https://") or not re.match(r"^[\w.-]+\.html?$", name):
        return None
    path = os.path.join(folder(), name)
    return path if os.path.isfile(path) else None


def page_link(which):
    name = str(config.get("demo_" + which) or "")
    if name.startswith("https://"):
        return name
    return "/demo/" + which if page_file(which) else ""


# ---------------------------------------------------------------- rate limits

def allow(kind, who, now=None):
    """True when this visitor address may do one more of `kind` now (LIMITS)."""
    most, per = LIMITS[kind]
    now = now or time.time()
    window = int(now // per)
    with _lock:
        if len(_hits) > 50000:                    # (old windows go; a flood of addresses can't fill the memory)
            for k in [k for k in _hits if k[2] != int(now // LIMITS[k[0]][1])]:
                del _hits[k]
        key = (kind, who, window)
        n = _hits.get(key, 0) + 1
        _hits[key] = n
        if n > most:
            return False
        if kind == "entry":
            _entries[:] = [t for t in _entries if t > now - 3600]
            if len(_entries) >= ENTRIES_PER_HOUR:
                return False
            _entries.append(now)
    return True


def forget_limits():
    with _lock:
        _hits.clear()
        del _entries[:]


# ---------------------------------------------------------------- the nightly reset

def reset(idle=3600):
    """Put back whatever visitors changed: sign-ins idle for an hour or more (a film being watched keeps its own),
    anything kept per person (places, likes, favourites, plays), the log, the tries counted, the rate limits, the
    screens remembered; then read the channel list and the library again, for the owner's changes to them."""
    from . import live, screens
    try:
        live.refresh(force=True)
    except Exception as exc:
        print("The demo's reset: reading the channel list: %r" % (exc,), flush=True)
    try:
        from .library import LIBRARY
        LIBRARY.scan("the demo's nightly reset")
    except Exception as exc:
        print("The demo's reset: reading the library: %r" % (exc,), flush=True)
    now = int(time.time())                      # (then the clearing, so nothing the reading wrote is left either)
    store.ex("DELETE FROM sessions WHERE seen < ?", now - idle)
    for table in ("progress", "live_favorites", "music_likes", "music_plays", "likes", "activity", "failures"):
        store.ex("DELETE FROM %s" % table)
    screens._screens.clear()
    forget_limits()
    print("The demo's nightly reset is done.", flush=True)


def seconds_until(hhmm, now=None):
    """Seconds from `now` until the next HH:MM on this computer's clock."""
    now = now or time.time()
    try:
        h, m = (int(x) for x in str(hhmm).split(":"))
    except ValueError:
        h, m = 4, 30
    t = time.localtime(now)
    target = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h % 24, m % 60, 0, 0, 0, -1))
    if target <= now:
        target = time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, h % 24, m % 60, 0, 0, 0, -1))
    return max(1.0, target - now)


def _nightly():
    while True:
        time.sleep(seconds_until(config.get("demo_reset")))
        try:
            reset()
        except Exception as exc:
            print("The demo's nightly reset: %r" % (exc,), flush=True)
        time.sleep(90)                            # (past the minute, so it runs once)


def start():
    if not on():
        return
    print("The public demo is on: everyone is a visitor, the demo's settings are locked, and it resets at %s."
          % config.get("demo_reset"), flush=True)
    threading.Thread(target=_nightly, daemon=True, name="demo-reset").start()
