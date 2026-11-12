"""Live TV from M3U playlists (for example the free channel lists at github.com/iptv-org/iptv).

Playlists are fetched and cached; channels are shown with their logos and groups.
Streams are passed through Sofa ("proxied") so they play in any browser and on TVs:
many channel servers don't allow browsers to fetch them directly, and some only
use plain http. Only addresses that came from your playlists can be fetched
through Sofa: every proxied link carries a signature made with a key stored on
this server.

Channels that don't answer are left out: Sofa looks at each one now and then (the way a viewer at home would
open it, a few at a time, and only while Live TV is being used here), remembers the ones that are gone, and
lists them again when they come back. An admin can see them anyway.

Adult channels (from a list the admin marked "adult", or in a group like "XXX")
are only listed for people allowed to see the Adult section, and never on TVs.
Note: iptv-org stopped publishing adult channels in January 2024, so adult
channels only come from lists you add yourself.
"""
import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import select
import socket
import socketserver
import threading
import time
import urllib.parse
import urllib.request

from . import config, net, store

CACHE = os.path.join(config.DATA_DIR, "cache", "live")
REFRESH_EVERY = 12 * 3600
FIRST_NUMBER = 101                  # the dial: a list's channels from here on (Sofa's own lineup has 2 to 99)
AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
ADULT_GROUP = re.compile(r"\b(xxx|adult|adults|18\+|erotic|porn|nsfw)\b", re.I)
GEO = re.compile(r"\[geo-?blocked\]|\u24bc", re.I)      # a list's own mark for "only in its country" ([Geo-blocked], Ⓖ)

_lock = threading.Lock()
_channels = {}      # id -> channel
_status = {}        # playlist url -> {"count", "updated", "error"}
_key = None


def _secret():
    global _key
    if _key is None:
        path = os.path.join(config.DATA_DIR, "live.key")
        if not os.path.exists(path):
            os.makedirs(config.DATA_DIR, exist_ok=True)
            with open(path, "w") as f:
                f.write(secrets.token_hex(32))
            os.chmod(path, 0o600)
        with open(path) as f:
            _key = f.read().strip().encode()
    return _key


def sign(url):
    return hmac.new(_secret(), url.encode(), hashlib.sha256).hexdigest()[:32]


def pack(url):
    """URL-safe token for a proxied address: base64(url).signature"""
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=") + "." + sign(url)


def unpack(token):
    try:
        b, sig = token.rsplit(".", 1)
        url = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(sig, sign(url)) or not url.startswith(("http://", "https://")):
        return None
    return url


# ---------------------------------------------------------------- playlists

def playlists():
    return config.get("live_playlists") or []


def parse_m3u(text, source, adult=False):
    channels = []
    info, opts = None, {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            attrs = dict(ATTR.findall(line))
            name = line.rsplit(",", 1)[-1].strip() if "," in line else attrs.get("tvg-name", "Channel")
            info = {"name": name or attrs.get("tvg-name") or "Channel", "logo": attrs.get("tvg-logo") or None,
                    "group": (attrs.get("group-title") or "Other").split(";")[0].strip() or "Other",
                    "tvg": attrs.get("tvg-id") or None, "geo": bool(GEO.search(line))}
            opts = {}
        elif line.startswith("#EXTVLCOPT:"):
            k, _, v = line[len("#EXTVLCOPT:"):].partition("=")
            if k.strip() == "http-user-agent":
                opts["ua"] = v.strip()
            elif k.strip() == "http-referrer":
                opts["referer"] = v.strip()
        elif line and not line.startswith("#") and info:
            if line.startswith(("http://", "https://")):
                cid = hashlib.sha1(line.encode()).hexdigest()[:12]
                channels.append(dict(info, id=cid, url=line, playlist=source, headers=opts,
                                     adult=adult or bool(ADULT_GROUP.search(info["group"]))))
            info, opts = None, {}
    return channels


HOME = "a channel from the internet can't lead to the home network"


def fetch(url, headers=None, timeout=15, home_ok=True):
    h = {"User-Agent": AGENT}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    if home_ok:
        return net.urlopen(req, timeout=timeout)
    if at_home(url):
        raise PermissionError(HOME)
    return net.urlopen(req, timeout=timeout, handlers=(_StayOut(), urllib.request.ProxyHandler({}),
                                                       _OutHTTPHandler(), _OutHTTPSHandler(context=net.context())))


def _home_ip(ip):
    a = ipaddress.ip_address(ip.split("%")[0])
    a = getattr(a, "ipv4_mapped", None) or a
    return not a.is_global or a.is_multicast


def at_home(url):
    """Does this address lead to this computer or the home network (a router's page, a Sofa box's own controls)?"""
    host = urllib.parse.urlsplit(url).hostname
    if not host:
        return True
    try:
        found = {a[4][0] for a in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError):
        return False                                    # (it can't be fetched either)
    return any(_home_ip(ip) for ip in found)


def _connect_out(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    """A connection to the internet and never to the home network: the name is looked up once, every address it gives
    is checked, and the connection goes to one of those very addresses. (Checked first and connected after, a name
    could change its answer in between, to a router's page or this computer.)"""
    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    if not infos or any(_home_ip(sa[0]) for *_x, sa in infos):
        raise PermissionError(HOME)
    err = None
    for family, kind, proto, _name, sa in infos:
        sock = None
        try:
            sock = socket.socket(family, kind, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            return sock
        except OSError as exc:
            err = exc
            if sock is not None:
                sock.close()
    raise err


class _OutHTTP(http.client.HTTPConnection):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._create_connection = _connect_out


class _OutHTTPS(http.client.HTTPSConnection):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._create_connection = _connect_out


class _OutHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_OutHTTP, req)


class _OutHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_OutHTTPS, req, context=self._context)


_relay = {}
_relay_lock = threading.Lock()
FFMPEG_PROTOCOLS = "http,https,tcp,tls,httpproxy,crypto,data"     # what ffmpeg may open for a channel from the internet


def relay():
    """The address of Sofa's relay, which ffmpeg is told to use as its web proxy when it plays a channel from the
    internet itself (a DLNA TV's live channel, a feed that isn't HLS). ffmpeg then connects to nothing directly: the
    channel, every part its playlists name, every redirect and key each go through the relay, which connects to
    internet addresses only (_connect_out). Started the first time it's needed, on this computer only."""
    with _relay_lock:
        if not _relay:
            srv = _Relay(("127.0.0.1", 0), _RelayHandler)
            threading.Thread(target=srv.serve_forever, name="live-relay", daemon=True).start()
            _relay.update(server=srv, url="http://127.0.0.1:%d" % srv.server_address[1])
        return _relay["url"]


class _Relay(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _pipe(a, b, idle=60):
    """Bytes both ways until either side closes, or nothing moves for `idle` seconds."""
    socks = [a, b]
    while True:
        ready, _w, _x = select.select(socks, [], [], idle)
        if not ready:
            return
        for s in ready:
            try:
                data = s.recv(65536)
            except OSError:
                return
            if not data:
                return
            (b if s is a else a).sendall(data)


class _RelayHandler(socketserver.BaseRequestHandler):
    """One connection from ffmpeg: CONNECT host:port (https, the TLS inside untouched) or GET http://host/path (plain
    http, sent on with Connection: close). Anything at home gets 403; anything else that isn't a proxy request, 400."""

    def answer(self, code, why):
        self.request.sendall(("HTTP/1.1 %d %s\r\nContent-Length: 0\r\nConnection: close\r\n\r\n" % (code, why)).encode())

    def handle(self):
        conn = self.request
        conn.settimeout(30)
        head = b""
        try:
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                head += chunk
                if len(head) > 65536:
                    return self.answer(431, "Too Large")
        except OSError:
            return
        head, _, rest = head.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, version = lines[0].split(" ")
            if method == "CONNECT":
                host, _, port = target.rpartition(":")
                host, port, first = host.strip("[]"), int(port), b""
            else:
                u = urllib.parse.urlsplit(target)
                if u.scheme != "http" or not u.hostname:
                    raise ValueError(target)
                host, port = u.hostname, u.port or 80
                keep = [line for line in lines[1:] if line.split(":", 1)[0].strip().lower()
                        not in ("connection", "proxy-connection", "proxy-authorization", "keep-alive")]
                first = ("%s %s %s\r\n" % (method, (u.path or "/") + ("?" + u.query if u.query else ""), version) +
                         "".join(line + "\r\n" for line in keep) + "Connection: close\r\n\r\n").encode("latin-1")
            if not host or not 0 < port < 65536:
                raise ValueError(target)
        except ValueError:
            return self.answer(400, "Bad Request")
        try:
            up = _connect_out((host, port), 20)
        except PermissionError:
            return self.answer(403, "Forbidden")
        except OSError:
            return self.answer(502, "Bad Gateway")
        with up:
            up.settimeout(60)
            conn.settimeout(60)
            try:
                if method == "CONNECT":
                    conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                up.sendall(first + rest)
                _pipe(conn, up)
            except OSError:
                pass


def ffmpeg_input(chan):
    """ffmpeg's options for reading a channel's own address: from a list on the internet, only through the relay and
    only over the web (a playlist can't name a file on this computer, or a raw address); the channel's own
    User-Agent and Referer, as the list gave them."""
    opts = []
    if not chan.get("home"):
        opts += ["-http_proxy", relay(), "-protocol_whitelist", FFMPEG_PROTOCOLS]
    if (chan.get("headers") or {}).get("ua"):
        opts += ["-user_agent", chan["headers"]["ua"]]
    if (chan.get("headers") or {}).get("referer"):
        opts += ["-referer", chan["headers"]["referer"]]
    return opts


class _StayOut(urllib.request.HTTPRedirectHandler):
    """A channel from the internet that answers "go to 192.168.1.1": not followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if at_home(newurl):
            raise PermissionError(HOME)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def refresh(force=False):
    """Re-download playlists older than REFRESH_EVERY (or all, when forced)."""
    os.makedirs(CACHE, exist_ok=True)
    channels = {}
    for pl in playlists():
        url, name = pl["url"], pl.get("name") or pl["url"]
        path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest()[:16] + ".m3u")
        stale = not os.path.exists(path) or time.time() - os.path.getmtime(path) > REFRESH_EVERY
        error = None
        if force or stale:
            try:
                with fetch(url, timeout=30) as r:
                    data = r.read(20 * 2**20).decode("utf-8", "replace")
                if "#EXTINF" not in data:
                    raise ValueError("that address isn't an M3U channel list")
                with open(path + ".tmp", "w", encoding="utf-8") as f:   # (a cut-off write mustn't pass for the list)
                    f.write(data)
                os.replace(path + ".tmp", path)
            except Exception as exc:
                error = str(exc)[:200]
                store.log("live", "Couldn't update channel list \"%s\": %s" % (name, error))
        try:
            with open(path, encoding="utf-8") as f:
                found = parse_m3u(f.read(), name, bool(pl.get("adult")))
        except OSError:
            found = []
        home = at_home(url)                             # a tuner's list at home (HDHomeRun): its channels are at home too
        for c in found:
            c["home"] = home
            kept = channels.setdefault(c["id"], c)
            kept.setdefault("lists", [])
            if url not in kept["lists"]:
                kept["lists"].append(url)               # (the same stream in two lists: one channel, in both)
        _status[url] = {"name": name, "url": url, "count": len(found), "error": error, "adult": bool(pl.get("adult")),
                        "updated": int(os.path.getmtime(path)) if os.path.exists(path) else None}
    # each channel's number on the dial: today's channels from 101, after Sofa's own lineup (2 to 99), by group and
    # name, counted over every channel so a number is the same channel for everyone (an adult profile, a Visitor)
    for n, c in enumerate(sorted(channels.values(), key=lambda c: (c["group"].lower(), c["name"].lower(), c["id"]))):
        c["number"] = FIRST_NUMBER + n
    with _lock:
        _channels.clear()
        _channels.update(channels)
    return len(channels)


def channel(cid):
    with _lock:
        return _channels.get(cid)


def visible(chan):
    """Shown at all. A channel whose list asks for a made-up browser name or referrer (to get past a site that wants its
    stream played only on its own pages) only when an admin allowed that (live_headers)."""
    h = (chan or {}).get("headers") or {}
    return bool(chan) and (bool(config.get("live_headers")) or not (h.get("ua") or h.get("referer")))


def listing(user_id, adult=False, public_only=False, direct_only=False, show_down=False):
    """Live TV's channels for one viewer. The ones that don't answer are left out (`down` says how many), except a
    viewer's own favourites, which stay with a mark, and for an admin who asked to see them anyway (`show_down`). `public_only`: a Visitor of the public library, who gets only the lists an
    admin marked for visitors. `direct_only`: away from home (and every Visitor), where a channel plays straight from
    where it's streamed or not at all: never through this Sofa, which would make the home's connection theirs (past a
    channel's own country limits) and its upload a public broadcaster. Each such channel carries its own address (src)."""
    _load_health()
    favs = {r["channel"] for r in store.q("SELECT channel FROM live_favorites WHERE user_id = ?", user_id)}
    lists = [p for p in playlists() if adult or not p.get("adult")]
    public = {p["url"] for p in lists if p.get("public")}
    with _lock:
        chans = sorted((c for c in _channels.values() if (adult or not c.get("adult")) and visible(c)
                        and (not public_only or public.intersection(c.get("lists") or ()))),
                       key=lambda c: (c["group"].lower(), c["name"].lower()))
    out, gone, hide = [], 0, checking()
    for c in chans:
        row = {"id": c["id"], "name": c["name"], "logo": c["logo"], "group": c["group"], "adult": c.get("adult", False),
               "playlist": c["playlist"], "fav": c["id"] in favs, "number": c.get("number")}
        if direct_only:
            src = direct_url(c)
            if not src or c.get("geo"):                  # (marked for its own country only: it wouldn't play out here)
                continue
            row["src"] = src
        if hide and down(c["id"]):
            gone += 1
            if not (show_down or row["fav"]):
                continue
            row["down"] = True
        out.append(row)
    return {"down": gone,
            "playlists": [] if public_only else
            [dict(_status.get(p["url"], {"name": p.get("name"), "url": p["url"], "count": 0, "adult": bool(p.get("adult"))}),
                  public=bool(p.get("public"))) for p in lists],
            "channels": out}


def direct_url(chan):
    """The channel's own address, for a viewer on the internet to play straight from the channel instead of through
    this Sofa (and its upload, or a tunnel that mustn't carry video). Only an https stream (an https page can't play
    an http one) that needs no headers of its own, from a list on the internet, never a tuner at home."""
    url = (chan or {}).get("url") or ""
    if not url.lower().startswith("https://") or chan.get("home") or chan.get("adult") or \
            (chan.get("headers") or {}).get("ua") or (chan.get("headers") or {}).get("referer"):
        return None
    return url


def all_channels(adult=False, with_down=True):
    """Every channel that's shown at all; `with_down` False leaves out the ones that don't answer (a TV's list)."""
    _load_health()
    hide = not with_down and checking()
    with _lock:
        return [c for c in _channels.values() if (adult or not c.get("adult")) and visible(c)
                and not (hide and down(c["id"]))]


def favorites_anyone():
    return {r["channel"] for r in store.q("SELECT DISTINCT channel FROM live_favorites")}


def add_playlist(name, url, adult=False):
    if not url.startswith(("http://", "https://")):
        raise ValueError("Use an http:// or https:// address.")
    pls = [p for p in playlists() if p["url"] != url] + [{"name": name.strip()[:60] or url, "url": url, "adult": bool(adult)}]
    config.update({"live_playlists": pls})


def set_public(url, on):
    """A list's channels for the public library's Visitors too (an admin's choice, list by list)."""
    pls = playlists()
    if not any(p["url"] == url for p in pls):
        raise ValueError("That channel list isn't on this Sofa.")
    config.update({"live_playlists": [dict(p, public=bool(on)) if p["url"] == url else p for p in pls]})


def remove_playlist(url):
    config.update({"live_playlists": [p for p in playlists() if p["url"] != url]})
    _status.pop(url, None)


# ---------------------------------------------------------------- stream proxy

URI_ATTR = re.compile(r'URI="([^"]+)"')


def rewrite_playlist(text, base, cid):
    """Point every address in an HLS playlist back through Sofa."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            line = URI_ATTR.sub(lambda m: 'URI="%s"' % proxied(urllib.parse.urljoin(base, m.group(1)), cid), line)
        elif s:
            line = proxied(urllib.parse.urljoin(base, s), cid)
        out.append(line)
    return "\n".join(out) + "\n"


def proxied(url, cid):
    return "/live/%s/p/%s" % (cid, pack(url))


def open_upstream(url, chan, timeout=20):
    """A channel's stream, or a part of it, through Sofa. A channel from a list on the internet can't send Sofa to the
    home network or this computer: its playlist (or a redirect) naming a router's page, or a Sofa box's own controls,
    isn't fetched. A list at home (a TV tuner's) can."""
    headers = {}
    if chan and chan.get("headers", {}).get("ua"):
        headers["User-Agent"] = chan["headers"]["ua"]
    if chan and chan.get("headers", {}).get("referer"):
        headers["Referer"] = chan["headers"]["referer"]
    return fetch(url, headers, timeout=timeout, home_ok=bool(chan and chan.get("home")))


def is_playlist(resp, url):
    ctype = (resp.headers.get("Content-Type") or "").lower()
    return "mpegurl" in ctype or urllib.parse.urlsplit(url).path.lower().endswith(".m3u8")


# ---------------------------------------------------------------- channels that don't answer

HEALTH = os.path.join(config.DATA_DIR, "live-health.json")
CHECK_OK_EVERY = 24 * 3600          # a channel that answered: looked at again a day later
CHECK_DOWN_EVERY = 6 * 3600         # one that's gone: sooner, so it's back in the list soon after it's back on air
CHECK_AGAIN = 600                   # one that missed a single look: once more before it's called gone
DOWN_AFTER = 2                      # looks in a row without an answer before a channel is left out
CHECK_TIMEOUT = 8
CHECK_PAUSE = 1.5                   # a worker's rest between two channels
CHECK_WORKERS = 3                   # at once (never two at the same site: a site's channels go to one worker)
CHECK_BATCH = 240                   # channels in one round, before the list is looked at afresh
WANTED_FOR = 7 * 86400              # nobody opened Live TV for a week: no more looking until someone does
ASK_EVERY = 60                      # a viewer's "this didn't play": looked at once a minute at most, per channel
UNREACHED = ("it took too long", "it can't be reached")
OFFLINE_AFTER = 4                   # sites in a row that couldn't be reached, nothing answering between: it's this
                                    # home's connection that's off, not the channels, and nothing is marked

_health = {}                        # channel id -> {"ok", "at", "fails", "why"}
_health_lock = threading.Lock()
_health_state = {"loaded": False, "dirty": False, "saved": 0.0, "wanted": 0.0, "asked": {}, "running": False}
_first = []                         # channels to look at before the rest (a viewer just couldn't play them)
_streak = {}                        # site -> (channel, what was known of it) that couldn't be reached since anything answered
_check_wake = threading.Event()


def checking():
    """Is Sofa looking at channels and leaving out the ones that don't answer (an admin's switch, on by default)?"""
    return bool(config.get("live_check")) and not config.get("offline")


def _load_health():
    if _health_state["loaded"]:
        return
    with _health_lock:
        if _health_state["loaded"]:
            return
        try:
            with open(HEALTH, encoding="utf-8") as f:
                saved = json.load(f)
            _health.update({k: v for k, v in (saved.get("channels") or {}).items() if isinstance(v, dict)})
            _health_state["wanted"] = float(saved.get("wanted") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        _health_state["loaded"] = True


def _save_health(force=False):
    """What's known, kept across restarts: written a minute apart at most, and whole (a cut-off write isn't the list)."""
    with _health_lock:
        if not _health_state["dirty"] or (not force and time.time() - _health_state["saved"] < 60):
            return
        data = {"wanted": int(_health_state["wanted"]), "channels": dict(_health)}
        _health_state.update(dirty=False, saved=time.time())
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(HEALTH + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(HEALTH + ".tmp", HEALTH)
    except OSError:
        pass


def down(cid):
    """Known not to answer: it missed DOWN_AFTER looks in a row, or a viewer's own try to watch it just failed."""
    _load_health()
    h = _health.get(cid)
    return bool(h) and not h.get("ok") and h.get("fails", 0) >= DOWN_AFTER


def mark(cid, ok, why="", at_once=False):
    """Remember how a look at a channel went. `at_once`: it failed for someone watching, so it's gone now, not after
    a second look."""
    _load_health()
    with _lock:
        host = urllib.parse.urlsplit((_channels.get(cid) or {}).get("url") or "").hostname or cid
    with _health_lock:
        before = _health.get(cid)
        if ok or why not in UNREACHED:
            _streak.clear()                             # something answered (a "404" too): the connection is up
        else:
            if len(_streak) >= OFFLINE_AFTER:
                return False
            _streak.setdefault(host, (cid, before))
            if len(_streak) >= OFFLINE_AFTER:           # ...and what was marked on the way here is taken back
                for k, was in _streak.values():
                    if was is None:
                        _health.pop(k, None)
                    else:
                        _health[k] = was
                _health_state["dirty"] = True
                return False
        h = before or {}
        fails = 0 if ok else max(h.get("fails", 0) + 1, DOWN_AFTER if at_once else 1)
        _health[cid] = {"ok": bool(ok), "at": int(time.time()), "fails": fails, "why": "" if ok else str(why)[:120]}
        _health_state["dirty"] = True
    return True


def cut_off():
    """Nothing on the internet has answered the last few looks: this home's connection looks off."""
    return len(_streak) >= OFFLINE_AFTER


def answered(cid):
    """A part of the channel just reached a viewer through Sofa: it's on air, whatever the last look said."""
    h = _health.get(cid)
    if h is None or not h.get("ok") or time.time() - h.get("at", 0) > 3600:
        mark(cid, True)


def wanted():
    """Someone opened Live TV: its channels are looked at from now on (and for a week after the last time)."""
    _load_health()
    now = time.time()
    if now - _health_state["wanted"] > 3600:
        with _health_lock:
            _health_state.update(wanted=now, dirty=True)
        _check_wake.set()
    else:
        _health_state["wanted"] = now


def look_again(cid):
    """A viewer couldn't play this channel. Sofa doesn't take their word for it: it looks itself, next, and leaves
    the channel out at once if it doesn't answer. (Asked for the same channel again within a minute: nothing.)"""
    now = time.time()
    with _health_lock:
        asked = _health_state["asked"]
        if now - asked.get(cid, 0) < ASK_EVERY:
            return False
        for k in [k for k, t in asked.items() if now - t > 3600]:
            del asked[k]
        asked[cid] = now
        if cid not in _first:
            _first.append(cid)
    _check_wake.set()
    return True


def why_not(exc):
    if isinstance(exc, PermissionError):
        return "it leads to the home network"
    if isinstance(exc, urllib.error.HTTPError):
        return "it answered %d" % exc.code
    if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in str(exc):
        return "it took too long"
    return "it can't be reached"


def probe(chan, timeout=CHECK_TIMEOUT):
    """Is this channel on air? Opened the way it is for a viewer at home (the same request, the same care about the
    home network, nothing made up), and read only as far as it takes to know: an HLS channel down to its list of
    parts and the first bytes of the newest part; any other feed, its first bytes. (True, "") or (False, why)."""
    try:
        url = chan["url"]
        for _hop in range(3):                           # a list of qualities, then one quality's list of parts
            with open_upstream(url, chan, timeout) as r:
                final = r.geturl()
                if not is_playlist(r, final):
                    return (True, "") if r.read(188) else (False, "it sent nothing")
                text = r.read(2 * 2**20).decode("utf-8", "replace")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            if not lines:
                return False, "its playlist is empty"
            if "#EXT-X-STREAM-INF" in text:
                url = urllib.parse.urljoin(final, lines[0])
                continue
            with open_upstream(urllib.parse.urljoin(final, lines[-1]), chan, timeout) as r:
                return (True, "") if r.read(188) else (False, "its video is empty")
        return False, "its playlists lead nowhere"
    except Exception as exc:
        return False, why_not(exc)


def _due(now=None):
    """The channels to look at now, in order: the ones a viewer just couldn't play, then people's favourites, then
    the ones never looked at, then the longest ago."""
    now = now or time.time()
    favs = favorites_anyone()
    with _health_lock:
        first = list(_first)
        del _first[:]
    with _lock:
        chans = [c for c in _channels.values() if visible(c)]
    by_id = {c["id"]: c for c in chans}
    out = [by_id[cid] for cid in first if cid in by_id]
    if now - _health_state["wanted"] > WANTED_FOR:
        return out, set(first)

    def when(c):
        h = _health.get(c["id"])
        if not h:
            return 0
        every = CHECK_OK_EVERY if h.get("ok") else CHECK_AGAIN if h.get("fails", 0) < DOWN_AFTER else CHECK_DOWN_EVERY
        return h.get("at", 0) + every

    rest = sorted((c for c in chans if c["id"] not in first and when(c) <= now),
                  key=lambda c: (c["id"] not in favs, when(c), c["id"]))
    return out + rest[:CHECK_BATCH], set(first)


def check_some(pause=None, workers=None):
    """One round of looking: the channels that are due, a few at a time (one at a time, with longer rests, on a slow
    computer: a Raspberry Pi that's playing a video shouldn't feel it). How many were looked at."""
    _load_health()
    if not checking():
        return 0
    if pause is None or workers is None:
        from . import machine                           # (it reads this computer's speed: not at import)
        slow_here = machine.gentle()
        pause = (CHECK_PAUSE * 2 if slow_here else CHECK_PAUSE) if pause is None else pause
        workers = (1 if slow_here else CHECK_WORKERS) if workers is None else workers
    due, at_once = _due()
    if not due:
        return 0
    lanes = [[] for _ in range(max(1, workers))]
    for c in due:                                       # a site's channels all in one lane: one request to it at a time
        host = urllib.parse.urlsplit(c["url"]).hostname or ""
        lanes[int(hashlib.sha1(host.encode()).hexdigest(), 16) % len(lanes)].append(c)

    def run(lane):
        for i, c in enumerate(lane):
            if not checking():
                return
            ok, why = probe(c)
            mark(c["id"], ok, why, at_once=c["id"] in at_once)
            _save_health()
            if cut_off():                               # (the next round finds out if it's back)
                return
            if pause and i + 1 < len(lane):
                time.sleep(pause)

    _health_state["running"] = True
    try:
        threads = [threading.Thread(target=run, args=(lane,), daemon=True, name="live-check") for lane in lanes if lane]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        _health_state["running"] = False
    with _lock:
        known = set(_channels)
    with _health_lock:                                  # a channel no list has had for a month: forgotten
        old = [k for k, h in _health.items() if k not in known and time.time() - h.get("at", 0) > 30 * 86400]
        for k in old:
            del _health[k]
            _health_state["dirty"] = True
    _save_health(force=True)
    return len(due)


def health(adult=True):
    """For the Server page: how many channels there are, how many were looked at, how many don't answer."""
    _load_health()
    with _lock:
        ids = [c["id"] for c in _channels.values() if visible(c) and (adult or not c.get("adult"))]
    return {"on": checking(), "total": len(ids), "checked": sum(1 for i in ids if i in _health),
            "down": sum(1 for i in ids if down(i)), "running": _health_state["running"],
            "waiting": time.time() - _health_state["wanted"] > WANTED_FOR, "cut_off": cut_off()}


def _check_loop():
    time.sleep(20)                                      # (the lists are read first)
    told = None
    while True:
        try:
            n = check_some()
            h = health()
            if n and h["checked"] >= h["total"] and h["down"] != told:   # a whole pass done: one line, no names
                told = h["down"]
                store.log("live", "Live TV: %d of %d channels don't answer and are left out" % (h["down"], h["total"]))
        except Exception as exc:
            n = 0
            store.log("error", "Live TV channel check: %s" % exc)
        _check_wake.clear()
        _check_wake.wait(20 if n and not cut_off() else 300)


# ---------------------------------------------------------------- background refresh

def _loop():
    while True:
        try:
            refresh()
        except Exception as exc:
            store.log("error", "Live TV refresh: %s" % exc)
        time.sleep(3600)


def start():
    threading.Thread(target=_loop, daemon=True, name="live-refresh").start()
    threading.Thread(target=_check_loop, daemon=True, name="live-check-loop").start()
