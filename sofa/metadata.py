"""Show and movie information from TVmaze (no key) and, if configured, TMDB. Cached on disk."""
import json
import os
import re
import time
import urllib.parse
import urllib.request

from . import config, naming

CACHE = os.path.join(config.DATA_DIR, "cache", "metadata")
RETRY_MISS = 24 * 3600
AGENT = {"User-Agent": "Sofa home media server"}


def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _cached(key, fetch):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, key + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("_miss") or time.time() - data["_miss"] < RETRY_MISS:
            return None if data.get("_miss") else data
    except (OSError, ValueError):
        pass
    try:
        data = fetch()
    except Exception:  # offline, not found, rate limited: try again tomorrow
        data = None
    data = data or {"_miss": time.time()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return None if data.get("_miss") else data


def strip_html(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip() or None


def tv_show(name):
    """TVmaze show with episodes and images, or None."""
    if not config.get("tvmaze"):
        return None

    def fetch():
        show = _get_json("https://api.tvmaze.com/singlesearch/shows?embed[]=episodes&embed[]=images&q="
                         + urllib.parse.quote(name))
        return show
    return _cached("tvmaze-" + naming.slug(name), fetch)


def show_info(show):
    """The parts of a TVmaze show Sofa displays."""
    images = (show.get("_embedded") or {}).get("images") or []
    background = next((i for i in images if i.get("type") == "background" and i.get("main")), None) \
        or next((i for i in images if i.get("type") == "background"), None)
    return {
        "summary": strip_html(show.get("summary")), "genres": show.get("genres") or [],
        "premiered": show.get("premiered"), "ended": show.get("ended"),
        "network": (show.get("network") or show.get("webChannel") or {}).get("name"),
        "rating": (show.get("rating") or {}).get("average"), "runtime": show.get("averageRuntime"),
        "poster_url": (show.get("image") or {}).get("original"),
        "backdrop_url": ((background or {}).get("resolutions") or {}).get("original", {}).get("url"),
        "canonical": show.get("name"),
    }


def episodes(show):
    out = {}
    for e in (show.get("_embedded") or {}).get("episodes", []):
        out[(e.get("season"), e.get("number"))] = {
            "title": e.get("name"), "summary": strip_html(e.get("summary")),
            "aired": e.get("airdate") or None, "runtime": e.get("runtime"),
            "thumb_url": ((e.get("image") or {}).get("original"))}
    return out


def movie(title, year):
    key = config.get("tmdb_api_key")
    if not key:
        return None

    def fetch():
        q = "https://api.themoviedb.org/3/search/movie?api_key=%s&query=%s" % (key, urllib.parse.quote(title))
        if year:
            q += "&year=%d" % year
        results = _get_json(q).get("results") or []
        if not results:
            return None
        m = results[0]
        return {"summary": m.get("overview"), "rating": m.get("vote_average"), "canonical": m.get("title"),
                "year": int(m["release_date"][:4]) if m.get("release_date") else year,
                "poster_url": "https://image.tmdb.org/t/p/original" + m["poster_path"] if m.get("poster_path") else None,
                "backdrop_url": "https://image.tmdb.org/t/p/original" + m["backdrop_path"] if m.get("backdrop_path") else None}
    return _cached("tmdb-%s-%s" % (naming.slug(title), year or ""), fetch)


def download(url, dest):
    """Save artwork next to the media (folder.jpg etc.) so it survives without Sofa."""
    if not url or os.path.exists(dest):
        return False
    try:
        req = urllib.request.Request(url, headers=AGENT)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        return True
    except Exception:
        return False
