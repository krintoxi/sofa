"""Show and movie information. Cached on disk.

Shows:  TVmaze (free, no key). Searched with the cleaned folder name and, when the
        folder has one, the year (so "Doctor Who (2005)" isn't the 1963 series).
Movies: TMDB when there's a key (best artwork, collections like "Star Wars").
        Without one: the iTunes Store (posters, summaries) and Wikipedia.
Adult:  ThePornDB with a token, else TMDB's adult titles when there's a TMDB key.

An admin can fix a wrong or missing match on the item's page; the choice is
kept in data/overrides.json and wins over any search.
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from . import config, naming, net

CACHE = os.path.join(config.DATA_DIR, "cache", "metadata")
OVERRIDES = os.path.join(config.DATA_DIR, "overrides.json")
RETRY_MISS = 24 * 3600
REFRESH_RUNNING = 3 * 86400      # a show still on the air: its episode list is looked at again every few days
AGENT = {"User-Agent": "Sofa home media server (https://github.com/krintoxi/sofa)"}
TMDB_IMG = "https://image.tmdb.org/t/p/original"
_olock = threading.Lock()


def _get_json(url, timeout=10, headers=None):
    h = dict(AGENT)
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with net.urlopen(req, timeout=timeout) as r:
        return json.load(r)


_local = threading.local()


def saved_only(on):
    """While on (for this thread): answer only from what's saved, never ask the internet.
    The library's first read after Sofa starts uses it, so Sofa is up in seconds."""
    _local.saved_only = on


def _cached(key, fetch, refresh=None):
    """A saved answer, or ask now. `refresh(data)`: True when a saved answer may have changed since (a show
    still on the air), so it's asked again when it's older than a few days; the old one stays if that fails."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, re.sub(r"[^\w.-]+", "-", key)[:150] + ".json")
    old = None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("_miss"):
            if time.time() - data["_miss"] < RETRY_MISS:
                return None
        elif refresh and refresh(data) and time.time() - os.path.getmtime(path) > REFRESH_RUNNING:
            old = data
        else:
            return data
    except (OSError, ValueError):
        pass
    if getattr(_local, "saved_only", False):
        return old
    try:
        data = fetch()
    except net.Offline:  # no internet: nothing learned, ask again when it's back
        return old
    except Exception:  # not found, rate limited: try again tomorrow
        data = None
    if old is not None and not data:
        try:
            os.utime(path, None)                     # keep the old answer; look again in a few days
        except OSError:
            pass
        return old
    data = data or {"_miss": time.time()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return None if data.get("_miss") else data


def forget(prefix):
    """Drop cached answers (after a fix, so the next scan asks again)."""
    try:
        for n in os.listdir(CACHE):
            if n.startswith(prefix):
                os.remove(os.path.join(CACHE, n))
    except OSError:
        pass


def strip_html(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip() or None


def _year(date):
    return int(date[:4]) if date and re.match(r"\d{4}", date) else None


# ---------------------------------------------------------------- manual fixes

def overrides():
    try:
        with open(OVERRIDES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def override(item_id):
    return overrides().get(item_id)


def set_override(item_id, value):
    with _olock:
        data = overrides()
        if value:
            data[item_id] = value
        else:
            data.pop(item_id, None)
        tmp = OVERRIDES + ".tmp"
        os.makedirs(os.path.dirname(OVERRIDES), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, OVERRIDES)


# ---------------------------------------------------------------- TV (TVmaze)

def _tvmaze_full(show_id):
    return _get_json("https://api.tvmaze.com/shows/%d?embed[]=episodes&embed[]=images" % int(show_id))


def tv_show(name, year=None, fix=None):
    """TVmaze show with episodes and images, or None."""
    if fix and fix.get("tvmaze"):
        return _cached("tvmaze-id-%s" % fix["tvmaze"], lambda: _tvmaze_full(fix["tvmaze"]), _on_air)
    if fix and fix.get("none"):
        return None
    if not config.get("tvmaze"):
        return None
    if fix and fix.get("title"):
        name, year = fix["title"], fix.get("year")

    def fetch():
        hits = _get_json("https://api.tvmaze.com/search/shows?q=" + urllib.parse.quote(name)) or []
        want = naming.norm(name)

        def rank(h):
            s = h.get("show") or {}
            same = naming.norm(s.get("name") or "") == want
            y = _year(s.get("premiered"))
            return (same and year and y == year, year and y == year, same, h.get("score") or 0)
        hits = [h for h in hits if h.get("show")]
        if not hits:
            return None
        best = max(hits, key=rank)["show"]
        a, b = naming.norm(best.get("name") or ""), want
        if not (a and b and (a.startswith(b) or b.startswith(a) or (year and _year(best.get("premiered")) == year))):
            return None      # nothing close enough: better no details than the wrong show's
        return _tvmaze_full(best["id"])
    return _cached("tvmaze2-%s-%s" % (naming.slug(name), year or ""), fetch, _on_air)


def _on_air(show):
    return show.get("status") in ("Running", "To Be Determined", "In Development")


def search_shows(query):
    """Candidates for the "Fix details" picker."""
    hits = _get_json("https://api.tvmaze.com/search/shows?q=" + urllib.parse.quote(query)) or []
    out = []
    for h in hits[:12]:
        s = h.get("show") or {}
        out.append({"source": "tvmaze", "id": s.get("id"), "title": s.get("name"), "year": _year(s.get("premiered")),
                    "detail": ", ".join(x for x in ((s.get("network") or s.get("webChannel") or {}).get("name"),
                                                     " / ".join(s.get("genres") or [])) if x),
                    "poster": (s.get("image") or {}).get("medium")})
    return out


# TVmaze keeps what kind of show it is apart from its genres: Futurama and Adventure Time are both
# "Animation" there. The kinds people browse by become genres too.
SHOW_TYPES = {"Animation": "Animation", "Documentary": "Documentary", "Reality": "Reality", "Talk Show": "Talk Show",
              "Game Show": "Game Show", "Sports": "Sports", "News": "News"}


def show_genres(show):
    genres = list(show.get("genres") or [])
    kind = SHOW_TYPES.get(show.get("type") or "")
    if kind == "Animation" and (show.get("language") == "Japanese" or
                                ((show.get("network") or show.get("webChannel") or {}).get("country") or {}).get("code") == "JP"):
        kind = "Anime"
    if kind and kind not in genres:
        genres.append(kind)
    return genres


def show_info(show):
    """The parts of a TVmaze show Sofa displays."""
    images = (show.get("_embedded") or {}).get("images") or []
    background = next((i for i in images if i.get("type") == "background" and i.get("main")), None) \
        or next((i for i in images if i.get("type") == "background"), None)
    return {
        "summary": strip_html(show.get("summary")), "genres": show_genres(show),
        "premiered": show.get("premiered"), "ended": show.get("ended"),
        "network": (show.get("network") or show.get("webChannel") or {}).get("name"),
        "rating": (show.get("rating") or {}).get("average"), "runtime": show.get("averageRuntime"),
        "poster_url": (show.get("image") or {}).get("original"),
        "backdrop_url": ((background or {}).get("resolutions") or {}).get("original", {}).get("url"),
        "canonical": show.get("name"), "source": "TVmaze", "source_id": show.get("id"),
    }


def episodes(show):
    out = {}
    for e in (show.get("_embedded") or {}).get("episodes", []):
        out[(e.get("season"), e.get("number"))] = {
            "title": e.get("name"), "summary": strip_html(e.get("summary")),
            "aired": e.get("airdate") or None, "runtime": e.get("runtime"),
            "thumb_url": ((e.get("image") or {}).get("original"))}
    return out


# ---------------------------------------------------------------- movies

def _alt_titles(title):
    """Other ways a movie may be listed: 'Star Wars Episode IV A New Hope' -> 'A New Hope', 'Star Wars'."""
    out = []
    m = re.match(r"^(.+?)\s+(?:episode|chapter|part)\s+[ivx\d]+\s*[-:]?\s*(.+)$", title, re.I)
    if m:
        out += ["%s: %s" % (m.group(1), m.group(2)), m.group(2), m.group(1)]
    if " - " in title:
        out.append(title.split(" - ", 1)[1])
    stripped = naming.strip_part(title)
    if stripped != title:
        out.append(stripped)
    return [t for t in out if t and t.lower() != title.lower()]


def _tmdb(path, **params):
    params["api_key"] = config.get("tmdb_api_key")
    return _get_json("https://api.themoviedb.org/3/%s?%s" % (path, urllib.parse.urlencode(params)))


def _tmdb_movie(movie_id):
    m = _tmdb("movie/%d" % int(movie_id))
    return {"summary": m.get("overview") or None, "rating": m.get("vote_average") or None, "canonical": m.get("title"),
            "year": _year(m.get("release_date")), "runtime": m.get("runtime") or None, "tagline": m.get("tagline") or None,
            "genres": [g["name"] for g in m.get("genres") or []],
            "collection": (m.get("belongs_to_collection") or {}).get("name"),
            "poster_url": TMDB_IMG + m["poster_path"] if m.get("poster_path") else None,
            "backdrop_url": TMDB_IMG + m["backdrop_path"] if m.get("backdrop_path") else None,
            "source": "TMDB", "source_id": m.get("id")}


def _pick(results, title, year, name_of, year_of):
    want = naming.norm(title)
    if not results:
        return None

    def rank(r):
        y = year_of(r)
        return (naming.norm(name_of(r) or "") == want, bool(year and y and abs(y - year) <= 1))
    best = max(results, key=rank)
    if year and year_of(best) and abs(year_of(best) - year) > 1 and naming.norm(name_of(best) or "") != want:
        return None
    return best


def _tmdb_search(title, year, adult=False):
    for t in [title] + _alt_titles(title):
        for y in ([year, None] if year else [None]):
            params = {"query": t, "include_adult": "true" if adult else "false"}
            if y:
                params["year"] = y
            best = _pick(_tmdb("search/movie", **params).get("results") or [], t, year,
                         lambda r: r.get("title"), lambda r: _year(r.get("release_date")))
            if best:
                return _tmdb_movie(best["id"])
    return None


def _itunes_item(r):
    art = r.get("artworkUrl100") or ""
    return {"summary": r.get("longDescription") or r.get("shortDescription") or None, "canonical": r.get("trackName"),
            "year": _year(r.get("releaseDate")), "genres": [r["primaryGenreName"]] if r.get("primaryGenreName") else [],
            "runtime": round(r["trackTimeMillis"] / 60000) if r.get("trackTimeMillis") else None,
            "rating": None, "certificate": r.get("contentAdvisoryRating"),
            "poster_url": art.replace("100x100bb", "1000x1500bb") if art else None, "backdrop_url": None,
            "source": "iTunes", "source_id": r.get("trackId")}


def _itunes_search(title, year):
    for t in [title] + _alt_titles(title):
        res = _get_json("https://itunes.apple.com/search?" + urllib.parse.urlencode(
            {"term": t, "media": "movie", "entity": "movie", "limit": 15})).get("results") or []
        best = _pick(res, t, year, lambda r: r.get("trackName"), lambda r: _year(r.get("releaseDate")))
        if best and (naming.norm(best.get("trackName") or "") == naming.norm(t)
                     or (year and _year(best.get("releaseDate")) == year)):
            return _itunes_item(best)
    return None


def _wikipedia(title, year):
    q = "%s %s film" % (title, year or "")
    hits = _get_json("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": q, "srlimit": 5, "format": "json"}))
    for h in (hits.get("query") or {}).get("search") or []:
        page = _get_json("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(h["title"].replace(" ", "_")))
        desc = (page.get("description") or "").lower()
        if "film" not in desc or (year and str(year) not in desc + h.get("snippet", "") + page.get("extract", "")):
            continue
        return {"summary": page.get("extract"), "canonical": re.sub(r"\s*\((?:\d{4} )?film\)$", "", page.get("title") or ""),
                "year": year or _year(re.search(r"(19|20)\d{2}", desc).group(0) if re.search(r"(19|20)\d{2}", desc) else None),
                "poster_url": (page.get("originalimage") or {}).get("source"), "backdrop_url": None,
                "genres": [], "rating": None, "source": "Wikipedia", "source_id": h["title"]}
    return None


def movie(title, year, fix=None, adult=False):
    """Details for a movie (or, with adult=True, an adult movie or scene), or None."""
    fix = fix or {}
    if fix.get("none"):
        return None
    if fix.get("tmdb") and config.get("tmdb_api_key"):
        return _cached("tmdb-id-%s" % fix["tmdb"], lambda: _tmdb_movie(fix["tmdb"]))
    if fix.get("itunes"):
        return _cached("itunes-id-%s" % fix["itunes"], lambda: _itunes_item(
            (_get_json("https://itunes.apple.com/lookup?id=%d" % int(fix["itunes"])).get("results") or [{}])[0]))
    if fix.get("tpdb"):
        return _cached("tpdb-id-%s" % fix["tpdb"], lambda: _tpdb_scene(fix["tpdb"]))
    if fix.get("title"):
        title, year = fix["title"], fix.get("year")
    if adult:
        return _adult(title, year)
    key = config.get("tmdb_api_key")

    def fetch():
        if key:
            found = _tmdb_search(title, year)
            if found:
                return found
        if config.get("free_movie_lookup"):
            for source in (_itunes_search, _wikipedia):
                try:
                    found = source(title, year)
                except Exception:
                    found = None
                if found:
                    return found
        return None
    return _cached("movie2-%s-%s-%s" % ("k" if key else "f", naming.slug(title), year or ""), fetch)


def search_movies(query, year=None, adult=False):
    """Candidates for the "Fix details" picker: TMDB with a key, else the iTunes Store (and ThePornDB for adult)."""
    out = []
    if adult and config.get("theporndb_api_key"):
        for s in (_tpdb("/scenes?" + urllib.parse.urlencode({"q": query})).get("data") or [])[:12]:
            out.append({"source": "tpdb", "id": s.get("id"), "title": s.get("title"), "year": _year(s.get("date")),
                        "detail": (s.get("site") or {}).get("name"), "poster": _tpdb_poster(s)})
    if config.get("tmdb_api_key"):
        params = {"query": query, "include_adult": "true" if adult else "false"}
        if year:
            params["year"] = year
        for r in (_tmdb("search/movie", **params).get("results") or [])[:12]:
            out.append({"source": "tmdb", "id": r.get("id"), "title": r.get("title"), "year": _year(r.get("release_date")),
                        "detail": (r.get("overview") or "")[:90],
                        "poster": "https://image.tmdb.org/t/p/w185" + r["poster_path"] if r.get("poster_path") else None})
    elif not adult:
        res = _get_json("https://itunes.apple.com/search?" + urllib.parse.urlencode(
            {"term": query, "media": "movie", "entity": "movie", "limit": 12})).get("results") or []
        for r in res:
            out.append({"source": "itunes", "id": r.get("trackId"), "title": r.get("trackName"),
                        "year": _year(r.get("releaseDate")), "detail": r.get("primaryGenreName"),
                        "poster": r.get("artworkUrl100")})
    return out


# ---------------------------------------------------------------- adult (ThePornDB)

TPDB = "https://api.theporndb.net"


def _tpdb(path):
    return _get_json(TPDB + path, headers={"Authorization": "Bearer " + config.get("theporndb_api_key"),
                                           "Accept": "application/json"})


def _tpdb_poster(s):
    posters = s.get("posters") or {}
    return posters.get("large") or posters.get("medium") or s.get("poster") or s.get("image")


def _tpdb_info(s):
    bg = s.get("background") or {}
    return {"summary": s.get("description") or None, "canonical": s.get("title"), "year": _year(s.get("date")),
            "date": s.get("date"), "studio": (s.get("site") or {}).get("name"),
            "genres": [t["name"] for t in (s.get("tags") or [])[:6] if t.get("name")],
            "performers": [p["name"] for p in (s.get("performers") or [])[:8] if p.get("name")],
            "poster_url": _tpdb_poster(s), "backdrop_url": bg.get("large") or bg.get("full") or s.get("image"),
            "rating": None, "source": "ThePornDB", "source_id": s.get("id")}


def _tpdb_scene(scene_id):
    return _tpdb_info(_tpdb("/scenes/%s" % urllib.parse.quote(str(scene_id))).get("data") or {})


def _adult(title, year):
    def fetch():
        if config.get("theporndb_api_key"):
            for path in ("/scenes?" + urllib.parse.urlencode({"parse": title}), "/movies?" + urllib.parse.urlencode({"q": title})):
                try:
                    data = _tpdb(path).get("data") or []
                except Exception:
                    data = []
                if data:
                    return _tpdb_info(data[0])
        if config.get("tmdb_api_key"):
            return _tmdb_search(title, year, adult=True)
        return None
    return _cached("adult-%s-%s" % (naming.slug(title), year or ""), fetch)


# ---------------------------------------------------------------- files

def download(url, dest, replace=False):
    """Save artwork next to the media (folder.jpg etc.) so it survives without Sofa."""
    if not url or (os.path.exists(dest) and not replace):
        return False
    try:
        req = urllib.request.Request(url, headers=AGENT)
        with net.urlopen(req, timeout=20) as r:
            data = r.read()
        if len(data) < 500:
            return False
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        return True
    except Exception:
        return False
