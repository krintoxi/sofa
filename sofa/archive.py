"""Live TV from the Internet Archive (archive.org): channels of free films, classic movies, film noir, westerns,
silent films, cartoons, classic TV and more, each played like a TV channel. A channel is a list of films on a loop,
on the clock: tuning in lands in the middle of what's on, and the next film follows.

The films come straight from archive.org to the screen (not through Sofa). Which films: the most watched of each
category that has one playable video file and a length, leaving out what doesn't belong on a family TV (the
archive's films include exploitation pictures). A channel's list is fetched the first time someone tunes in, and
again after a week; it's kept in data/cache/archive.
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config, net

CACHE = os.path.join(config.DATA_DIR, "cache", "archive")
UA = "Sofa (github.com/krintoxi/sofa)"
KEEP = 7 * 86400                     # a channel's films, before they're fetched again
FILMS = 30                           # films on a channel
ANCHOR = 1704067200                  # 2024-01-01: where every channel's clock starts (the same for every viewer)

# what doesn't belong on a family TV box (the archive's films include exploitation pictures and scare films)
NOT = (' AND NOT subject:(sex OR sexploitation OR erotic OR erotica OR nudity OR nudist OR adult OR burlesque OR'
       ' "exploitation film" OR exploitation OR drugs OR stag OR pinup OR striptease)'
       ' AND NOT title:(sex OR sexy OR nude OR naked OR nudist OR burlesque OR strip OR striptease OR molester OR'
       ' madness OR erotic OR virgin OR orgy OR lust)')
NOT_WORDS = re.compile(r"\b(sex|sexy|nude|naked|nudist|burlesque|strip|striptease|molest\w*|erotic\w*|orgy|lust|xxx)\b", re.I)

# id, name, the archive search, a colour and a mark for its logo
CHANNELS = [
    ("ia-classics", "Classic Movies", "collection:(feature_films) AND mediatype:(movies) AND year:[1930 TO 1975]", "#C8A24A", "★"),
    ("ia-noir", "Film Noir", "collection:(feature_films OR film_noir) AND subject:(\"film noir\" OR noir)", "#5B6B7F", "◐"),
    ("ia-scifi", "Sci-Fi & Horror", "collection:(SciFi_Horror)", "#3FA36B", "✦"),
    ("ia-comedy", "Comedy", "collection:(feature_films) AND subject:(comedy)", "#E2862F", "☺"),
    ("ia-westerns", "Westerns", "collection:(feature_films) AND subject:(western OR westerns)", "#A0522D", "☼"),
    ("ia-silent", "Silent Films", "collection:(silent_films)", "#8A8A8A", "❖"),
    ("ia-cartoons", "Cartoons", "collection:(classic_cartoons)", "#E2483D", "✿"),
    ("ia-tv", "Classic TV", "collection:(classic_tv) AND mediatype:(movies)", "#3D7BE2", "▣"),
    ("ia-docs", "Documentaries", "collection:(prelinger OR documentaries) AND mediatype:(movies)", "#2E9C9A", "◉"),
]
BY_ID = {c[0]: c for c in CHANNELS}
_lock = threading.Lock()
_building = set()


def on():
    return bool(config.get("archive_channels")) and not config.get("offline")


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with net.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def logo(cid):
    """A channel's logo: its colour, its mark and its name (an SVG, made here)."""
    _id, name, _q, colour, mark = BY_ID[cid]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
           '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="#111"/></linearGradient></defs>'
           '<rect width="320" height="200" rx="18" fill="url(#g)"/>'
           '<text x="28" y="92" font-size="64" fill="#fff" font-family="sans-serif">%s</text>'
           '<text x="28" y="150" font-size="34" font-weight="700" fill="#fff" font-family="sans-serif">%s</text>'
           '<text x="28" y="182" font-size="18" fill="#fff" opacity=".7" font-family="sans-serif">Internet Archive</text></svg>'
           % (colour, mark, name.replace("&", "&amp;")))
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)


def channels():
    """The channels, for Live TV's list (group "Internet Archive")."""
    if not on():
        return []
    return [{"id": c[0], "name": c[1], "group": "Internet Archive", "logo": logo(c[0]), "archive": True} for c in CHANNELS]


def seconds(length):
    """'1:17:26', '95 min', '123.4' -> seconds (None when it can't be read)."""
    s = str(length or "").strip().lower()
    m = re.match(r"^(\d+)\s*min", s)
    if m:
        return int(m.group(1)) * 60
    if re.match(r"^[\d:.]+$", s):
        parts = [float(p) for p in s.split(":") if p]
        total = 0.0
        for p in parts:
            total = total * 60 + p
        return int(total) if total else None
    return None


def _film(identifier):
    """One item's film: its one playable video file (an MP4, the smaller copy where there are two), and its length."""
    d = _get("https://archive.org/metadata/%s" % urllib.parse.quote(identifier))
    meta, files = d.get("metadata") or {}, d.get("files") or []
    title = meta.get("title") if isinstance(meta.get("title"), str) else identifier
    if NOT_WORDS.search(title or "") or NOT_WORDS.search(" ".join(meta.get("subject") or []) if isinstance(meta.get("subject"), list) else str(meta.get("subject") or "")):
        return None
    vids = [f for f in files if f.get("name", "").lower().endswith(".mp4") and seconds(f.get("length"))]
    originals = {f.get("original") for f in vids if f.get("original")}
    sources = [f for f in vids if f.get("source") == "original"] or vids
    if len({f["name"] for f in sources} - originals) > 2:      # a bundle of many videos, not one film
        return None
    if not vids:
        return None
    best = sorted(vids, key=lambda f: (int(f.get("height") or 480) > 720, -int(f.get("size") or 0) if int(f.get("height") or 480) <= 720 else int(f.get("size") or 0)))[0]
    length = seconds(best.get("length"))
    if not length or length < 120:
        return None
    year = re.match(r"\d{4}", str(meta.get("year") or meta.get("date") or ""))
    return {"id": identifier, "title": re.sub(r"\s+", " ", title).strip()[:120], "year": int(year.group(0)) if year else None,
            "url": "https://archive.org/download/%s/%s" % (urllib.parse.quote(identifier), urllib.parse.quote(best["name"])),
            "length": length}


def _build(cid):
    _id, _name, q, _c, _m = BY_ID[cid]
    url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
        [("q", q + NOT), ("fl[]", "identifier"), ("fl[]", "title"), ("rows", str(FILMS * 3)), ("sort[]", "downloads desc"), ("output", "json")])
    docs = [d for d in _get(url).get("response", {}).get("docs", []) if not NOT_WORDS.search(d.get("title") or "")]
    films = []
    with ThreadPoolExecutor(6) as pool:
        for f in pool.map(lambda d: _safe_film(d["identifier"]), docs):
            if f and len(films) < FILMS:
                films.append(f)
    return films


def _safe_film(identifier):
    try:
        return _film(identifier)
    except (OSError, ValueError, KeyError):
        return None


def _path(cid):
    return os.path.join(CACHE, cid + ".json")


def films(cid, wait=True):
    """The channel's films, from the cache, or fetched now (a few seconds) when there are none or they're old."""
    if cid not in BY_ID:
        raise KeyError(cid)
    try:
        with open(_path(cid), encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = None
    if saved and saved.get("films") and time.time() - saved.get("at", 0) < KEEP:
        return saved["films"]
    with _lock:
        if cid in _building:
            return (saved or {}).get("films") or []
        _building.add(cid)
    try:
        fresh = _build(cid) if (wait or not saved) else None
    except (OSError, ValueError) as exc:
        if saved and saved.get("films"):
            return saved["films"]                           # (the archive not answering: last week's list)
        raise OSError("The Internet Archive didn't answer (%s)." % exc)
    finally:
        with _lock:
            _building.discard(cid)
    if fresh:
        os.makedirs(CACHE, exist_ok=True)
        tmp = _path(cid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"at": int(time.time()), "films": fresh}, f)
        os.replace(tmp, _path(cid))
        return fresh
    return (saved or {}).get("films") or []


def _warm():
    """Every channel's films, ready before anyone tunes in (a few seconds each, a channel at a time), then kept fresh."""
    time.sleep(120)                                         # (Sofa reads its library first)
    while True:
        for cid in BY_ID:
            if on():
                try:
                    films(cid)
                except (OSError, ValueError):
                    pass
            time.sleep(10)
        time.sleep(6 * 3600)


def start():
    threading.Thread(target=_warm, daemon=True, name="archive-channels").start()


def now(cid, at=None, ahead=6):
    """What's on: the film, where in it (seconds), and the ones after it, on the channel's clock."""
    fl = films(cid)
    if not fl:
        raise OSError("This channel has nothing to show just now.")
    total = sum(f["length"] for f in fl)
    pos = ((at if at is not None else time.time()) - ANCHOR) % total
    i = 0
    while pos >= fl[i]["length"]:
        pos -= fl[i]["length"]
        i += 1
    order = [fl[(i + k) % len(fl)] for k in range(min(ahead, len(fl)))]
    return {"channel": cid, "name": BY_ID[cid][1], "film": order[0], "offset": int(pos), "left": int(order[0]["length"] - pos),
            "next": order[1:]}

