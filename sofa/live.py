"""Live TV from M3U playlists (for example the free channel lists at github.com/iptv-org/iptv).

Playlists are fetched and cached; channels are shown with their logos and groups.
Streams are passed through Sofa ("proxied") so they play in any browser and on TVs:
many channel servers don't allow browsers to fetch them directly, and some only
use plain http. Only addresses that came from your playlists can be fetched
through Sofa: every proxied link carries a signature made with a key stored on
this server.

Adult channels (from a list the admin marked "adult", or in a group like "XXX")
are only listed for people allowed to see the Adult section, and never on TVs.
Note: iptv-org stopped publishing adult channels in January 2024, so adult
channels only come from lists you add yourself.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request

from . import config, net, store

CACHE = os.path.join(config.DATA_DIR, "cache", "live")
REFRESH_EVERY = 12 * 3600
AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
ADULT_GROUP = re.compile(r"\b(xxx|adult|adults|18\+|erotic|porn|nsfw)\b", re.I)

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
                    "tvg": attrs.get("tvg-id") or None}
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


def fetch(url, headers=None, timeout=15):
    h = {"User-Agent": AGENT}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    return net.urlopen(req, timeout=timeout)


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
                with open(path, "w", encoding="utf-8") as f:
                    f.write(data)
            except Exception as exc:
                error = str(exc)[:200]
                store.log("live", "Couldn't update channel list \"%s\": %s" % (name, error))
        try:
            with open(path, encoding="utf-8") as f:
                found = parse_m3u(f.read(), name, bool(pl.get("adult")))
        except OSError:
            found = []
        for c in found:
            channels.setdefault(c["id"], c)
        _status[url] = {"name": name, "url": url, "count": len(found), "error": error, "adult": bool(pl.get("adult")),
                        "updated": int(os.path.getmtime(path)) if os.path.exists(path) else None}
    with _lock:
        _channels.clear()
        _channels.update(channels)
    return len(channels)


def channel(cid):
    with _lock:
        return _channels.get(cid)


def listing(user_id, adult=False):
    favs = {r["channel"] for r in store.q("SELECT channel FROM live_favorites WHERE user_id = ?", user_id)}
    with _lock:
        chans = sorted((c for c in _channels.values() if adult or not c.get("adult")),
                       key=lambda c: (c["group"].lower(), c["name"].lower()))
    return {"playlists": [_status.get(p["url"], {"name": p.get("name"), "url": p["url"], "count": 0, "adult": bool(p.get("adult"))})
                          for p in playlists() if adult or not p.get("adult")],
            "channels": [{"id": c["id"], "name": c["name"], "logo": c["logo"], "group": c["group"], "adult": c.get("adult", False),
                          "playlist": c["playlist"], "fav": c["id"] in favs} for c in chans]}


def all_channels(adult=False):
    with _lock:
        return [c for c in _channels.values() if adult or not c.get("adult")]


def favorites_anyone():
    return {r["channel"] for r in store.q("SELECT DISTINCT channel FROM live_favorites")}


def add_playlist(name, url, adult=False):
    if not url.startswith(("http://", "https://")):
        raise ValueError("Use an http:// or https:// address.")
    pls = [p for p in playlists() if p["url"] != url] + [{"name": name.strip()[:60] or url, "url": url, "adult": bool(adult)}]
    config.update({"live_playlists": pls})


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


def open_upstream(url, chan):
    headers = {}
    if chan and chan.get("headers", {}).get("ua"):
        headers["User-Agent"] = chan["headers"]["ua"]
    if chan and chan.get("headers", {}).get("referer"):
        headers["Referer"] = chan["headers"]["referer"]
    return fetch(url, headers, timeout=20)


def is_playlist(resp, url):
    ctype = (resp.headers.get("Content-Type") or "").lower()
    return "mpegurl" in ctype or urllib.parse.urlsplit(url).path.lower().endswith(".m3u8")


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
