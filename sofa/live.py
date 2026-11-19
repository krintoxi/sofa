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

Adult channels (from a list the admin marked "adult", or in a group like "XXX") are never in Live TV itself: they
have their own page in the Adult section, for people allowed to see it, and are never a Visitor's, a Kids profile's or
a TV's on the network, and never played away from home. A channel is adult when any list holding it is.

Categories: lists name their groups every which way ("SPORTS", "Sports", "Kids" with emoji, "News;Business"), and put
a third of their channels in "General" or "Undefined". category() folds them into a short set in a fixed order; a
channel in a catch-all group goes by its name where the name says what it is. The same channel in several lists (or
in several picture sizes) is one row: the first that answers plays, the others stand by (`alt`).
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
import sys
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
ADULT_NAME = re.compile(r"(?<![a-z])(xxx|adults?|18\+|erotic\w*|porn\w*|nsfw)(?![a-z])", re.I)   # in a list's name or address
ADULT_FIRST = 9001                  # the dial: adult channels from here, so adding a list of them moves no other number

# Categories, in the order Live TV shows them. The words are what lists call their groups (and, for a channel in a
# catch-all group, what its name may say).
CATEGORIES = (
    ("News", "news noticias noticiero nouvelles nachrichten notizie noticies business finance weather legislative politics parliament government"),
    ("Sports", "sport sports deportes deporte esportes auto motor racing fight football futbol soccer"),
    ("Movies", "movies movie films film cinema cine classic peliculas filmes"),
    ("Series", "series shows novelas telenovelas drama"),
    ("Entertainment", "entertainment entretenimiento comedy variety infotainment interactive"),
    ("Kids", "kids kid children animation cartoons cartoon family infantil junior toons"),
    ("Music", "music musica musique radio hits"),
    ("Documentary", "documentary documentaries documentales science nature travel history culture"),
    ("Lifestyle", "lifestyle cooking food relax fashion outdoor"),
    ("Learning", "education educational learning educativo"),
    ("Faith", "religious religion faith christian catholic islamic gospel church"),
    ("Shopping", "shop shopping"),
)
REST = "Everything else"
CATCH_ALL = frozenset("other others general undefined unknown all uncategorized misc various tv channel channels none na".split())
_CAT_OF = {w: name for name, words in CATEGORIES for w in words.split()}
_NAME_WORDS = frozenset("news noticias sport sports deportes movies cinema cine films kids junior toons cartoon music musica hits "
                        "gospel church shop shopping weather radio".split())
_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)
_TAGS = re.compile(r"\s*(?:\((?:\d{3,4}[pi]|[SFUQ]?HD|SD|4K)\)|\[(?:geo-?blocked|not 24/7|offline)\]|[\u24bc\u24c8])", re.I)


def tidy_name(name):
    """A channel's name without a list's own marks: "(720p)", "[Geo-blocked]", "[Not 24/7]"."""
    return re.sub(r"\s{2,}", " ", _TAGS.sub("", name or "")).strip() or (name or "").strip() or "Channel"


def category(group, name=""):
    """Where a channel goes in Live TV, from its list's group ("News;Business", "SPORTS", "Kids" with emoji) and, in a
    catch-all group, from its name. A group that names something else (a country, a language) stays, tidied."""
    left = None
    for part in (group or "").split(";"):
        words = [w.lower() for w in _WORDS.findall(part)]
        for w in words:
            if w in _CAT_OF:
                return _CAT_OF[w]
        if left is None and words and not all(w in CATCH_ALL for w in words):
            left = " ".join(w.capitalize() for w in words)[:28]
    if left:
        return sys.intern(left)
    for w in _WORDS.findall(name or ""):
        if w.lower() in _NAME_WORDS and w.lower() in _CAT_OF:
            return _CAT_OF[w.lower()]
    return REST


_CAT_RANK = {name: n for n, (name, _) in enumerate(CATEGORIES)}


def cat_rank(cat):
    """Sorting by category: the known ones in their order, then the lists' own, then everything else."""
    return (0, _CAT_RANK[cat], "") if cat in _CAT_RANK else (2, 0, "") if cat == REST else (1, 0, (cat or "").lower())

_lock = threading.Lock()
_channels = {}      # id -> channel
_numbered = {}      # a number on the dial -> the first channel that has it
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


NO_HEADERS = {}                       # (shared by every channel that names none: read, never changed)


def parse_m3u(text, source, adult=False):
    """A list's channels. What thousands of channels have in common (their list's name, their group) is kept once:
    a 10,000-channel list held 10.5 MB, the same text over and over."""
    channels, intern = [], sys.intern
    source = intern(source)
    info, opts = None, {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            attrs = dict(ATTR.findall(line))
            name = line.rsplit(",", 1)[-1].strip() if "," in line else attrs.get("tvg-name", "Channel")
            name, raw = tidy_name(name or attrs.get("tvg-name") or "Channel"), attrs.get("group-title") or ""
            info = {"name": name, "logo": attrs.get("tvg-logo") or None, "group": intern(category(raw, name)),
                    "tvg": attrs.get("tvg-id") or None, "geo": bool(GEO.search(line)), "adult": bool(ADULT_GROUP.search(raw))}
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
                channels.append(dict(info, id=cid, url=line, playlist=source, headers=opts or NO_HEADERS,
                                     adult=adult or info["adult"]))
            info, opts = None, {}
    return channels


HOME = "a channel from the internet can't lead to the home network"


def fetch(url, headers=None, timeout=15, home_ok=True):
    h = {"User-Agent": AGENT}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    if home_ok and at_home(url):                # (a tuner at home: no proxy, and offline mode is about the internet)
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)
    # (a channel or a list that can't be found is that channel's news, not the internet's: see net.urlopen)
    if home_ok:
        return net.urlopen(req, timeout=timeout, whole_internet=False)
    if at_home(url):
        raise PermissionError(HOME)
    return net.urlopen(req, timeout=timeout, whole_internet=False,
                       handlers=(_StayOut(), urllib.request.ProxyHandler({}),
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


_fetch_lock = threading.Lock()           # one download of the lists at a time (the hourly one, an admin's, a new list's)
_build_lock = threading.Lock()           # ...and one putting-together of the channels, which waits on no download
_soon = {"busy": False, "again": None}   # the reading that goes on behind a request (refresh_soon)
_gen = [0]                               # counts each time the channels were put together again (rev)
_home = {}                               # a list's address -> does it lead to the home network (looked up when it's fetched)
_errors = {}                             # a list's address -> what went wrong the last time it was fetched


def _saved_as(url):
    return os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest()[:16] + ".m3u")


def refresh(force=False, only=None, download=True):
    """Re-download playlists older than REFRESH_EVERY (or all, when forced; or just the list at `only`), then put the
    channels together again. `download` False: nothing is fetched, the channels are put together from the lists as
    they were last saved (what a request does: it never waits on a list's own server, nor on a download going on)."""
    os.makedirs(CACHE, exist_ok=True)
    if download:
        with _fetch_lock:
            _fetch_lists(force, only)
    with _build_lock:
        return _build(force)


def refresh_soon(force=False, only=None):
    """The same, behind the request that asked: it answers at once and the lists are fetched after it. One reading at
    a time; what's asked for meanwhile is read next (everything, if two different things were asked for)."""
    with _lock:
        if _soon["busy"]:
            was = _soon["again"]
            _soon["again"] = (force, only) if was is None else (force or was[0], only if was[1] == only else None)
            return
        _soon["busy"] = True

    def work(force, only):
        while True:
            try:
                refresh(force, only)
            except Exception as exc:
                store.log("error", "Live TV refresh: %s" % exc)
            with _lock:
                if _soon["again"] is None:
                    _soon["busy"] = False
                    return
                (force, only), _soon["again"] = _soon["again"], None

    threading.Thread(target=work, args=(force, only), daemon=True, name="live-refresh-soon").start()


def count():
    with _lock:
        return len(_channels)


def reading():
    """Is a list being fetched behind a request just now (the Server page says so)?"""
    return _soon["busy"]


def _fetch_lists(force, only):
    for pl in playlists():
        url, name = pl["url"], pl.get("name") or pl["url"]
        path = _saved_as(url)
        stale = not os.path.exists(path) or time.time() - os.path.getmtime(path) > REFRESH_EVERY
        if not (only == url or (only is None and (force or stale))):
            continue
        try:
            with fetch(url, timeout=30) as r:
                data = r.read(20 * 2**20).decode("utf-8", "replace")
            if "#EXTINF" not in data:
                raise ValueError("that address isn't an M3U channel list")
            with open(path + ".tmp", "w", encoding="utf-8") as f:   # (a cut-off write mustn't pass for the list)
                f.write(data)
            os.replace(path + ".tmp", path)
            _errors.pop(url, None)
        except Exception as exc:
            _errors[url] = str(exc)[:200]
            store.log("live", "Couldn't update %s: %s" % ("an adult channel list" if pl.get("adult") else   # (no names of those)
                                                          "channel list \"%s\"" % name, _errors[url]))
        _home[url] = at_home(url)                       # (looking a name up can take a while: here, not in a request)


def _build(force):
    channels = {}
    for pl in playlists():
        url, name = pl["url"], pl.get("name") or pl["url"]
        path = _saved_as(url)
        try:
            with open(path, encoding="utf-8") as f:
                found = parse_m3u(f.read(), name, bool(pl.get("adult")))
        except OSError:
            found = []
        if found and url not in _home:
            _home[url] = at_home(url)
        home = _home.get(url, False)                    # a tuner's list at home (HDHomeRun): its channels are at home too
        off = bool(pl.get("off"))                       # switched off (Server, Live TV): kept, and none of it in Live TV
        for c in () if off else found:
            c["home"] = home
            kept = channels.setdefault(c["id"], c)
            if c["adult"]:
                kept["adult"] = True                    # (adult in any list: adult, whichever list came first)
            if url not in kept.get("lists", ()):
                kept["lists"] = kept.get("lists", ()) + (sys.intern(url),)   # (the same stream in two lists: one channel, in both)
        _status[url] = {"name": name, "url": url, "count": len(found), "error": _errors.get(url), "adult": bool(pl.get("adult")),
                        "updated": int(os.path.getmtime(path)) if os.path.exists(path) else None}
    if config.demo_on():                            # the public demo: its own checked list, and nothing else
        from . import demo
        channels = demo.channels()
    # each channel's number on the dial: today's channels from 101, after Sofa's own lineup (2 to 99), by group and
    # name, counted over every channel so a number is the same channel for everyone (an adult profile, a Visitor)
    # The same channel from several lists, or in several picture sizes: one row and one number (`same`: its category,
    # its name and the id its lists give it, so two channels that only share a name stay two), in list order.
    # Adult channels are counted apart, after everything else (from 9001, or the next thousand in a home with more
    # channels than that): a list of them added or marked moves no other channel's number.
    n, seen, later = -1, {}, []
    for c in sorted(channels.values(), key=lambda c: (bool(c.get("adult")), cat_rank(c["group"]), c["name"].lower(), c["id"])):
        c["same"] = same = sys.intern("%d|%s|%s|%s" % (bool(c.get("adult")), c["group"].lower(), c["name"].lower(), c.get("tvg") or ""))
        if c.get("adult"):
            later.append(c)
            continue
        if same not in seen:
            n += 1
            seen[same] = FIRST_NUMBER + n
        c["number"] = seen[same]
    # then the tuners' channels (sofa/tuners.py), in their own order ("2.1", "5.1", "5.2"), after the lists' so adding
    # a tuner moves no channel a household already knows by its number. A tuner's channel is in no list (so never a
    # Visitor's) and at home (so never played away from home through this Sofa).
    from . import tuners
    last = FIRST_NUMBER + n
    for k, c in enumerate(t for t in tuners.channels(force) if t["id"] not in channels):
        c["number"] = last = FIRST_NUMBER + n + 1 + k
        c["lists"] = ()
        channels[c["id"]] = c
    m = max(ADULT_FIRST, (last // 1000 + 1) * 1000 + 1)
    for c in later:
        if c["same"] not in seen:
            seen[c["same"]] = m
            m += 1
        c["number"] = seen[c["same"]]
    numbered = {}
    for c in channels.values():
        numbered.setdefault(c.get("number"), c["id"])
    with _lock:
        _channels.clear()
        _channels.update(channels)
        _numbered.clear()
        _numbered.update(numbered)
        _gen[0] += 1
    return len(channels)


def channel(cid):
    with _lock:
        return _channels.get(cid)


def visible(chan):
    """Shown at all. A channel whose list asks for a made-up browser name or referrer (to get past a site that wants its
    stream played only on its own pages) only when an admin allowed that (live_headers)."""
    h = (chan or {}).get("headers") or {}
    if chan and config.demo_on() and chan.get("playlist") != "demo":     # the public demo: its own list's channels only
        return False
    return bool(chan) and (bool(config.get("live_headers")) or not (h.get("ua") or h.get("referer")))


def listing(user_id, adult=False, public_only=False, direct_only=False, show_down=False, only_adult=False):
    """Live TV's channels for one viewer, by category (`cats`: their order). The ones that don't answer are left out
    (`down` says how many), except a viewer's own favourites, which stay with a mark, and for an admin who asked to see
    them anyway (`show_down`). The same channel from several lists is one row: the first that answers, the others in
    `alt` for the player to fall back on. Adult channels are never among the others: `only_adult` is their own page, for
    a viewer who may see Adult (`adult`). `public_only`: a Visitor of the public library, who gets only the lists an
    admin marked for visitors. `direct_only`: away from home (and every Visitor), where a channel plays straight from
    where it's streamed or not at all: never through this Sofa, which would make the home's connection theirs (past a
    channel's own country limits) and its upload a public broadcaster. Each such channel carries its own address (src)."""
    _load_health()
    only_adult = bool(only_adult and adult and not public_only)
    favs = {r["channel"] for r in store.q("SELECT channel FROM live_favorites WHERE user_id = ?", user_id)}
    lists = [p for p in playlists() if bool(p.get("adult")) == only_adult]
    public = {p["url"] for p in lists if p.get("public") and not p.get("adult")} | ({"demo"} if config.demo_on() else set())
    with _lock:
        chans = sorted((c for c in _channels.values() if bool(c.get("adult")) == only_adult and visible(c)
                        and (not public_only or public.intersection(c.get("lists") or ()))),
                       key=lambda c: (cat_rank(c["group"]), c["name"].lower(), c.get("number") or 0))
    rows, order, hide = {}, [], checking()
    for c in chans:
        src = None
        if direct_only:
            src = direct_url(c)
            if not src or c.get("geo"):                  # (marked for its own country only: it wouldn't play out here)
                continue
        gone = bool(hide and down(c["id"]))
        key = c.get("same") or c["id"]
        row = rows.get(key)
        if row is not None and not (row.get("down") and not gone):
            row["fav"] = row["fav"] or c["id"] in favs
            if not gone and len(row["alt"]) < 3:
                row["alt"].append(c["id"])               # (the same channel from another list: the player's fallback)
            continue
        new = {"id": c["id"], "name": c["name"], "logo": c["logo"] or (row or {}).get("logo"), "group": c["group"],
               "adult": c.get("adult", False), "playlist": c["playlist"], "number": c.get("number"), "alt": [],
               "fav": c["id"] in favs or bool(row and row["fav"])}
        if c.get("rights"):                         # the public demo's channels: who publishes it, and on what terms
            new.update(publisher=c.get("publisher"), rights=c["rights"], page=c.get("page"))
        if c.get("tuner"):
            new.update(tuner=True, guide_number=c.get("guide_number"), recordable=True)
        elif c.get("home"):
            new["recordable"] = True
        if src:
            new["src"] = src
        if gone:
            new["down"] = True
        if row is None:
            order.append(key)
        rows[key] = new
    out, gone = [], 0
    for key in order:
        row = rows[key]
        if row.get("down"):
            gone += 1
            if not (show_down or row["fav"]):
                continue
        if not row["alt"]:
            del row["alt"]
        out.append(row)
    cats = []
    for row in out:
        if not cats or cats[-1] != row["group"]:
            cats.append(row["group"])
    return {"down": gone, "cats": cats,
            "playlists": [] if public_only else lists_shown(lists),
            "channels": out}


def twins(cid):
    """Every id of the same channel (it may be in several lists): a favourite is all of them."""
    with _lock:
        c = _channels.get(cid)
        if not c or not c.get("same"):
            return [cid]
        return [k for k, x in _channels.items() if x.get("same") == c["same"]] or [cid]


def lists_shown(lists):
    """The channel lists as the Server page and Live TV show them: how many channels, what went wrong, on or off."""
    return [dict(_status.get(p["url"], {"name": p.get("name"), "url": p["url"], "count": 0}), adult=bool(p.get("adult")),
                 public=bool(p.get("public")) and not p.get("adult"), off=bool(p.get("off")),
                 adultish=not p.get("adult") and adultish(p.get("name"), p["url"])) for p in lists]


def summary(adult=False):
    """For the Server page, which asks every few seconds: the lists and the count of what answers, and no channels
    (thousands of them were built and sent each time, a megabyte for two short lines of the page)."""
    return {"playlists": lists_shown([p for p in playlists() if adult or not p.get("adult")]),
            "health": health(adult=adult), "reading": reading()}


def rev(user_id=None):
    """A few letters that change when Live TV's list would: the lists and their switches, the channels put together
    again, Sofa's own lineup switched. A device with Live TV already loaded asks for this alone, and loads the
    channels again only when it's different (a list switched off in Server is gone from the TV's Live TV at once)."""
    seen = json.dumps([playlists(), _gen[0], [bool(config.get(k)) for k in
                       ("live_headers", "live_check", "archive_channels", "retro_eras", "offline", "share_live", "share_cinema")]],
                      sort_keys=True)
    return hashlib.sha1(seen.encode()).hexdigest()[:12]


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


def adultish(name, url=""):
    """Does a list's name or address say it's adult? (The Server page asks then; Sofa doesn't decide for the admin.)"""
    return bool(ADULT_NAME.search("%s %s" % (name or "", urllib.parse.unquote(url or ""))))


def set_adult(url, on):
    """A list marked Adult: its channels leave Live TV for the Adult section's own page, and it can't be a Visitor's."""
    pls = playlists()
    if not any(p["url"] == url for p in pls):
        raise ValueError("That channel list isn't on this Sofa.")
    config.update({"live_playlists": [dict({k: v for k, v in p.items() if not (on and k == "public")}, adult=bool(on))
                                      if p["url"] == url else p for p in pls]})


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
    if on and any(p["url"] == url and p.get("adult") for p in pls):
        raise ValueError("An adult list is never for visitors.")
    config.update({"live_playlists": [dict(p, public=bool(on)) if p["url"] == url else p for p in pls]})


def set_on(url, on):
    """A list switched off stays on the Server page (its address isn't lost) and none of its channels are in Live TV,
    for anyone; switched on, they're back."""
    pls = playlists()
    if not any(p["url"] == url for p in pls):
        raise ValueError("That channel list isn't on this Sofa.")
    config.update({"live_playlists": [({k: v for k, v in p.items() if k != "off"} if on else dict(p, off=True))
                                      if p["url"] == url else p for p in pls]})


def remove_playlist(url):
    config.update({"live_playlists": [p for p in playlists() if p["url"] != url]})
    _status.pop(url, None)
    _home.pop(url, None)
    _errors.pop(url, None)


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


# Changing channel: the playlist of the channel next up and next down is fetched ahead (a few hundred bytes each, no
# video), so the change starts from what's already here instead of a round trip to the channel's server. Kept a few
# seconds (a live playlist moves on with every part); one that only names the picture sizes doesn't change, and its
# first size is fetched too.
WARM_FOR, WARM_SIZES_FOR, WARM_MOST, WARM_TIMEOUT = 4, 60, 8, 6
_warm = {}                          # address -> (when, where it really was, its text)
_warming = set()
_warm_lock = threading.Lock()


def warmed(url):
    with _warm_lock:
        got = _warm.get(url)
    if got and time.time() - got[0] < (WARM_SIZES_FOR if "#EXT-X-STREAM-INF" in got[2] else WARM_FOR):
        return got[1], got[2]
    return None


def _warm_one(chan):
    url = chan["url"]
    try:
        for _ in range(2):                              # the channel's playlist, then its first picture size
            if warmed(url):
                at, text = warmed(url)
            else:
                with open_upstream(url, chan, timeout=WARM_TIMEOUT) as resp:
                    if not is_playlist(resp, resp.geturl()):
                        return
                    at, text = resp.geturl(), resp.read(2**20).decode("utf-8", "replace")
                with _warm_lock:
                    _warm[url] = (time.time(), at, text)
                    for old in sorted(_warm, key=lambda k: _warm[k][0])[:-WARM_MOST]:
                        del _warm[old]
            if "#EXT-X-STREAM-INF" not in text:
                return
            first = next((l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")), None)
            if not first:
                return
            url = urllib.parse.urljoin(at, first)
    except Exception:
        pass                                            # (nobody asked for it yet: nothing is marked)
    finally:
        with _warm_lock:
            _warming.discard(chan["id"])


def near(chan):
    """The channels next up and next down on the dial (the order Live TV lists a category in, and the Sofa Box's up
    and down go through)."""
    n = (chan or {}).get("number")
    if not n:
        return []
    with _lock:
        return [_channels[_numbered[k]] for k in (n + 1, n - 1) if _numbered.get(k) in _channels]


NEAR_AFTER = 30                     # a channel nobody asked for in this long: the next ask is someone tuning in
_near_at = {}


def tuned(chan):
    """Someone asked for this channel's playlist. A player asks again every few seconds while it plays: only the
    first ask (tuning in) makes the channels next to it ready, once, and never again while it's being watched."""
    now = time.time()
    with _warm_lock:
        last = _near_at.get(chan["id"], 0)
        if len(_near_at) > 500:
            _near_at.clear()
        _near_at[chan["id"]] = now
    if now - last >= NEAR_AFTER:
        warm([c for c in near(chan) if bool(c.get("adult")) == bool(chan.get("adult"))])


def warm(chans):
    """Fetch these channels' playlists ahead (two at most at a time, each once). Never a tuner's or a list's at home
    (asking a tuner for a channel takes the tuner), never one that's known not to answer."""
    chans = [c for c in chans if c and visible(c) and not c.get("tuner") and not c.get("home") and not down(c["id"])
             and not config.get("offline")]
    for chan in chans[:2]:
        with _warm_lock:
            if chan["id"] in _warming or len(_warming) >= 4:
                continue
            _warming.add(chan["id"])
        threading.Thread(target=_warm_one, args=(chan,), daemon=True, name="live-warm").start()


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
ADD_WAIT = 3                        # a new list: the request that added it waits this long for it, then answers anyway
TUNE_TIMEOUT = 10                   # someone tuning in: a channel that says nothing for this long didn't answer
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
    fault = net.certificate_fault(exc)                  # (checked, and turned away: the channel's own fault)
    if fault:
        return {"expired": "its certificate has run out", "name": "its certificate is for another address",
                "self": "its certificate is one it signed itself"}.get(fault, "its certificate can't be checked")
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
    with _lock:                                         # (a tuner's channel isn't looked at: a look would take a tuner)
        chans = [c for c in _channels.values() if visible(c) and not c.get("tuner")]
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
