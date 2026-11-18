"""Bringing what people watched in Plex, Jellyfin or Emby into Sofa: watched marks, where they stopped, and likes.

Only an admin can do it (Server → People, or `python3 sofa.py import`). Four ways to read a source:

    plex-db       a copy of Plex's library database (com.plexapp.plugins.library.db): every Plex user
    plex          Plex's own address with a token the admin pastes: the token's account in full, and the
                  watched marks of every other account from Plex's watch history (their resume points aren't
                  there: Plex only gives those to each account's own token)
    jellyfin      Jellyfin's (or Emby's) address with an API key the admin makes: every user
    jellyfin-db   a copy of Jellyfin's database folder or file: every user

Each source user goes to a Sofa profile the admin picks (none: left out). Nothing about a profile changes: a Kids
profile stays a Kids profile, and it only gets titles a Kids profile may watch; Adult titles only go to profiles
whose Adult switch is on.

Matching, in order: the file's path (through a folder map the admin sets: what Plex calls /data/movies is
/Volumes/Media/Movies here), then IMDb, TMDB or TVDB ids (Sofa's side from tags in the file names, .nfo files and
the details Sofa already saved), then the title and year (a movie) or the show, season and episode.

A dry run comes first: what matched, what didn't, and what conflicts, before anything is written. An import writes
in one go, never over a newer place in Sofa, and running it again changes nothing.

What's kept: nothing about the source. A token or key is used for the one read and never written anywhere; a
database is read from a private copy that's deleted straight after; what was read stays in Sofa's memory until it's
imported or for an hour at most.
"""
import datetime
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import kids, metadata, naming, store

KEEP_SECONDS = 3600          # what was read stays in memory this long at most
LIKE_RATING = 8              # a rating of 8 out of 10 (four stars of five) or more becomes a like
TICKS = 10000000             # Jellyfin and Emby count time in ticks of 100 nanoseconds
PAGE = 500                   # items per request to Jellyfin or Emby
LIST_LIMIT = 300             # titles per list in a report (the counts are always complete)
ID_KINDS = ("imdb", "tmdb", "tvdb")
SOURCES = {"plex-db": "Plex", "plex": "Plex", "jellyfin": "Jellyfin", "jellyfin-db": "Jellyfin"}


class Problem(Exception):
    """Something to tell the admin as it is (a wrong key, a file that isn't Plex's database)."""


# ---------------------------------------------------------------- records

def record(user, kind, **kw):
    """One source user's state for one title, the same shape from every source.

    kind: "movie", "episode" or "show" (a show carries only a like). Times are seconds; `at` is when it was last
    watched (or rated), Unix time, None when the source doesn't say."""
    r = {"user": str(user), "kind": kind, "title": None, "original": None, "year": None, "show": None,
         "show_year": None, "s": None, "e": None, "paths": [], "ids": {}, "show_ids": {}, "watched": False,
         "position": 0.0, "duration": None, "at": None, "liked": False, "rating": None, "ref": None}
    r.update(kw)
    return r


def _number(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _when(v):
    """Unix seconds from what a source keeps: seconds, or an ISO date (Jellyfin writes seven decimals)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        v = float(v)
        if v > 1e11:                      # milliseconds
            v /= 1000.0
        return v if math.isfinite(v) and v > 0 else None
    text = str(v).strip()
    if re.match(r"^\d+(\.\d+)?$", text):
        return _when(float(text))
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d)(?::(\d\d))?(?:\.\d+)?\s*(Z|[+-]\d\d:?\d\d)?$", text)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x or 0) for x in m.groups()[:6])
    try:
        t = datetime.datetime(y, mo, d, h, mi, s, tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None
    zone = m.group(7)
    if zone and zone != "Z":
        sign = -1 if zone[0] == "+" else 1
        zone = zone[1:].replace(":", "")
        t += sign * (int(zone[:2]) * 3600 + int(zone[2:]) * 60)
    return t if t > 0 else None


def _id_value(kind, value):
    """'tt0113277', '949', '81189': the form ids are compared in (IMDb's keep their tt, the others are numbers)."""
    value = str(value or "").strip()
    if kind == "imdb":
        m = re.match(r"^(tt\d{5,10})$", value, re.I)
        return m.group(1).lower() if m else None
    return value if re.match(r"^\d{1,10}$", value) and value.strip("0") else None


def _ids(pairs):
    out = {}
    for kind, value in pairs:
        kind = str(kind or "").lower()
        kind = {"themoviedb": "tmdb", "thetvdb": "tvdb", "moviedb": "tmdb"}.get(kind, kind)
        if kind in ID_KINDS and kind not in out:
            v = _id_value(kind, value)
            if v:
                out[kind] = v
    return out


# ---------------------------------------------------------------- Plex: its database

PLEX_MOVIE, PLEX_SHOW, PLEX_SEASON, PLEX_EPISODE = 1, 2, 3, 4
PLEX_GUID_TAG = 314          # tags holding "imdb://tt…", "tmdb://…", "tvdb://…" (Plex's newer agents)


def _plex_guid_ids(guid):
    """Ids in an item's own guid (Plex's older agents): com.plexapp.agents.imdb://tt0113277?lang=en,
    com.plexapp.agents.thetvdb://73244/1/2?lang=en. The newer plex://movie/… guids carry none."""
    m = re.match(r"^com\.plexapp\.agents\.(imdb|themoviedb|thetvdb|tmdb|tvdb)://([^/?]+)", guid or "")
    return _ids([(m.group(1), m.group(2))]) if m else {}


def _snapshot(path):
    """A private copy of a SQLite database, made with SQLite's own backup (a consistent picture even while Plex or
    Jellyfin is running and writing), opened read-only. The original is only ever read. Returns (connection, folder
    to delete)."""
    if not os.path.isfile(path):
        raise Problem("There's no file at %s." % path)
    folder = tempfile.mkdtemp(prefix="sofa-import-")
    copy = os.path.join(folder, "copy.db")
    src = dst = None
    try:
        src = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(os.path.abspath(path).replace(os.sep, "/")),
                              uri=True, timeout=30)
        dst = sqlite3.connect(copy)
        src.backup(dst)
        dst.close()
        dst = None
        conn = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(copy.replace(os.sep, "/")), uri=True)
        conn.row_factory = sqlite3.Row
        # Plex sorts some text with ICU's rules (icu_root), which plain SQLite doesn't have: a stand-in, so a query
        # that touches such an index still runs. (Nothing here depends on how titles sort.)
        conn.create_collation("icu_root", lambda a, b: (a > b) - (a < b))
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
        return conn, folder
    except sqlite3.DatabaseError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise Problem("That file couldn't be read as a database (%s)." % exc)
    finally:
        for c in (src, dst):
            if c is not None:
                c.close()


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}


def _columns(conn, table):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}


def read_plex_db(path):
    """Every Plex account's watched marks, places and ratings, from a copy of com.plexapp.plugins.library.db."""
    conn, folder = _snapshot(path)
    try:
        tables = _tables(conn)
        if not {"metadata_items", "metadata_item_settings", "accounts"} <= tables:
            raise Problem("That isn't Plex's library database (com.plexapp.plugins.library.db).")
        users = [{"key": str(r["id"]), "name": r["name"] or "Plex user %d" % r["id"], "kids": None}
                 for r in conn.execute("SELECT id, name FROM accounts WHERE id > 0 ORDER BY id")]
        # (Text is compared here in Python: some of Plex's columns use a sorting rule plain SQLite doesn't have.)
        items, by_guid = {}, {}
        for r in conn.execute("SELECT id, parent_id, metadata_type, guid, title, original_title, year, \"index\", "
                              "duration FROM metadata_items WHERE metadata_type IN (1, 2, 3, 4)"):
            items[r["id"]] = dict(r)
            by_guid.setdefault(r["guid"], []).append(r["id"])
        ids = {}
        if {"taggings", "tags"} <= tables:
            for r in conn.execute("SELECT tg.metadata_item_id AS item, t.tag AS tag FROM taggings tg "
                                  "JOIN tags t ON t.id = tg.tag_id WHERE t.tag_type = ?", (PLEX_GUID_TAG,)):
                kind, _, value = str(r["tag"] or "").partition("://")
                found = _ids([(kind, value)])
                if found:
                    ids.setdefault(r["item"], {}).update({k: v for k, v in found.items() if k not in ids.get(r["item"], {})})
        paths = {}
        if {"media_items", "media_parts"} <= tables:
            for r in conn.execute("SELECT mi.metadata_item_id AS item, mp.file AS file FROM media_items mi "
                                  "JOIN media_parts mp ON mp.media_item_id = mi.id"):
                if r["file"]:
                    paths.setdefault(r["item"], []).append(r["file"])
        cols = _columns(conn, "metadata_item_settings")
        rated = "last_rated_at" if "last_rated_at" in cols else "updated_at"
        records = []
        for r in conn.execute("SELECT account_id, guid, rating, view_offset, view_count, last_viewed_at, updated_at, "
                              "%s AS rated_at FROM metadata_item_settings" % rated):
            found = [items[i] for i in by_guid.get(r["guid"], ()) if i in items]
            if not found:
                continue
            it = found[0]
            kind = {PLEX_MOVIE: "movie", PLEX_EPISODE: "episode", PLEX_SHOW: "show"}.get(it["metadata_type"])
            if not kind:
                continue
            own = {}
            for f in found:
                own.update({k: v for k, v in dict(_plex_guid_ids(f["guid"]), **ids.get(f["id"], {})).items() if k not in own})
            rec = dict(title=it["title"], original=it["original_title"] or None, year=_int(it["year"]),
                       paths=[p for f in found for p in paths.get(f["id"], [])], ids=own,
                       watched=(_int(r["view_count"]) or 0) > 0, position=(_number(r["view_offset"]) or 0) / 1000.0,
                       duration=(_number(it["duration"]) or 0) / 1000.0 or None,
                       at=_when(r["last_viewed_at"]) or _when(r["updated_at"]),
                       rating=_number(r["rating"]), ref="plex:%s" % it["id"])
            if kind == "episode":
                season = items.get(it["parent_id"]) or {}
                show = items.get(season.get("parent_id")) or {}
                show_ids = dict(ids.get(show.get("id"), {}))
                legacy = re.match(r"^com\.plexapp\.agents\.thetvdb://(\d+)/", it["guid"] or "")
                if legacy and "tvdb" not in show_ids:
                    show_ids["tvdb"] = legacy.group(1)
                rec.update(show=show.get("title"), show_year=_int(show.get("year")), s=_int(season.get("index")),
                           e=_int(it["index"]), show_ids=dict(_plex_guid_ids(show.get("guid")), **show_ids),
                           ids={k: v for k, v in own.items() if not legacy})
            if kind == "show":
                rec["at"] = _when(r["rated_at"]) or rec["at"]
            records.append(record(r["account_id"], kind, **rec))
        return {"source": "Plex", "how": "database", "users": users, "records": _likes(records), "notes": []}
    except sqlite3.DatabaseError as exc:
        raise Problem("Plex's database couldn't be read (%s)." % exc)
    finally:
        conn.close()
        shutil.rmtree(folder, ignore_errors=True)


def _likes(records):
    for r in records:
        if r["rating"] is not None and r["rating"] >= LIKE_RATING:
            r["liked"] = True
    return records


# ---------------------------------------------------------------- talking to a server at home

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A token or key never follows a redirect to somewhere else."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Problem("The server sent Sofa to another address (%s). Give that address instead." %
                      urllib.parse.urlsplit(newurl)._replace(query="", fragment="").geturl())


def _base(url):
    url = str(url or "").strip().rstrip("/")
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    parts = urllib.parse.urlsplit(url)
    if not parts.hostname:
        raise Problem("That address doesn't look right. It's like http://192.168.1.20:32400.")
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc, parts.path.rstrip("/"), "", ""))


def _get(base, path, headers, params=None, timeout=60):
    from . import live, net
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers=dict(headers, Accept="application/json"))
    handlers = [urllib.request.ProxyHandler({}), _NoRedirect()]
    if url.startswith("https://"):
        handlers.append(urllib.request.HTTPSHandler(context=net.context()))
    if not live.at_home(url) and net.offline_mode():
        raise Problem("Sofa is set to work offline (Server → Settings), and that address isn't on the home network.")
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise Problem("The server turned the token or key down (%d). Check it and try again." % exc.code)
        if exc.code == 404:
            raise Problem("The server doesn't know %s (404). Is this the right address and server?" % path)
        raise Problem("The server answered %d to %s." % (exc.code, path))
    except (urllib.error.URLError, OSError) as exc:
        raise Problem("Sofa couldn't reach %s: %s" % (base, getattr(exc, "reason", exc)))
    except ValueError:
        raise Problem("The server's answer to %s wasn't what Plex, Jellyfin or Emby send." % path)


# ---------------------------------------------------------------- Plex: its own address and a token

def _plex_media(m):
    """A Plex API movie or episode, with its files and ids."""
    return {"title": m.get("title"), "original": m.get("originalTitle"), "year": _int(m.get("year")),
            "paths": [p.get("file") for md in m.get("Media") or [] for p in md.get("Part") or [] if p.get("file")],
            "ids": _ids([tuple(g.get("id", "").split("://", 1)) for g in m.get("Guid") or [] if "://" in g.get("id", "")]
                        + list(_plex_guid_ids(m.get("guid")).items())),
            "duration": (_number(m.get("duration")) or 0) / 1000.0 or None,
            "show": m.get("grandparentTitle"), "s": _int(m.get("parentIndex")), "e": _int(m.get("index")),
            "show_key": str(m.get("grandparentRatingKey") or ""), "key": str(m.get("ratingKey") or "")}


def read_plex_api(url, token):
    """The token's own account in full (watched, places, ratings), and the other accounts' watched marks from
    Plex's watch history. Nothing is sent to plex.tv."""
    base = _base(url)
    token = str(token or "").strip()
    if not token:
        raise Problem("Paste a Plex token.")
    h = {"X-Plex-Token": token, "X-Plex-Product": "Sofa", "X-Plex-Client-Identifier": "sofa-history-import"}
    me = (_get(base, "/", h) or {}).get("MediaContainer") or {}
    if "machineIdentifier" not in me:
        raise Problem("That address answered, but not as a Plex server.")
    accounts = ((_get(base, "/accounts", h) or {}).get("MediaContainer") or {}).get("Account") or []
    users = [{"key": str(a.get("id")), "name": a.get("name") or "Plex user %s" % a.get("id"), "kids": None}
             for a in accounts if _int(a.get("id")) and _int(a.get("id")) > 0]
    owner = me.get("myPlexUsername")
    mine = next((u["key"] for u in users if owner and u["name"] == owner), users[0]["key"] if users else "1")
    if not any(u["key"] == mine for u in users):
        users.insert(0, {"key": mine, "name": owner or "Plex owner", "kids": None})
    sections = ((_get(base, "/library/sections", h) or {}).get("MediaContainer") or {}).get("Directory") or []
    records, media, shows = [], {}, {}
    for sec in sections:
        kind = {"movie": "movie", "show": "show"}.get(sec.get("type"))
        if not kind:
            continue
        types = [(1, "movie")] if kind == "movie" else [(2, "show"), (4, "episode")]
        for type_no, what in types:
            start = 0
            while True:
                page = ((_get(base, "/library/sections/%s/all" % sec.get("key"), h,
                              {"type": type_no, "includeGuids": 1, "X-Plex-Container-Start": start,
                               "X-Plex-Container-Size": PAGE}) or {}).get("MediaContainer") or {})
                rows = page.get("Metadata") or []
                for m in rows:
                    info = _plex_media(m)
                    if what == "show":
                        shows[info["key"]] = info
                        rating = _number(m.get("userRating"))
                        if rating is not None:
                            records.append(record(mine, "show", title=info["title"], year=info["year"], ids=info["ids"],
                                                  rating=rating, at=_when(m.get("lastRatedAt")) or _when(m.get("updatedAt")),
                                                  ref="plex:%s" % info["key"]))
                        continue
                    media[info["key"]] = (what, info)
                    watched, offset = (_int(m.get("viewCount")) or 0) > 0, _number(m.get("viewOffset")) or 0
                    rating = _number(m.get("userRating"))
                    if watched or offset or rating is not None:
                        records.append(_plex_record(mine, what, info, shows, watched=watched, position=offset / 1000.0,
                                                    at=_when(m.get("lastViewedAt")) or _when(m.get("lastRatedAt")),
                                                    rating=rating))
                start += len(rows)
                if not rows or start >= _int(page.get("totalSize") or page.get("size") or 0):
                    break
    # Everyone else: what Plex's history says they watched (a whole play; their places aren't in it).
    start, seen = 0, set()
    while True:
        page = ((_get(base, "/status/sessions/history/all", h,
                      {"sort": "viewedAt:desc", "X-Plex-Container-Start": start, "X-Plex-Container-Size": PAGE}) or {})
                .get("MediaContainer") or {})
        rows = page.get("Metadata") or []
        for v in rows:
            who, key = str(v.get("accountID") or ""), str(v.get("ratingKey") or "")
            if not who or who == mine or (who, key) in seen:
                continue
            seen.add((who, key))
            what, info = media.get(key, (None, None))
            if info is None:                                   # gone from Plex since: what the history says
                what = "episode" if v.get("type") == "episode" else "movie" if v.get("type") == "movie" else None
                if not what:
                    continue
                info = {"title": v.get("title"), "year": _int(v.get("year")), "paths": [], "ids": {}, "duration": None,
                        "show": v.get("grandparentTitle"), "s": _int(v.get("parentIndex")), "e": _int(v.get("index")),
                        "show_key": str(v.get("grandparentRatingKey") or ""), "key": key}
            records.append(_plex_record(who, what, info, shows, watched=True, at=_when(v.get("viewedAt"))))
            if not any(u["key"] == who for u in users):
                users.append({"key": who, "name": "Plex user %s" % who, "kids": None})
        start += len(rows)
        if not rows or start >= _int(page.get("totalSize") or page.get("size") or 0):
            break
    notes = ["Through Plex's address, only the token's own account (%s) brings its places and ratings; the other "
             "accounts bring what they watched to the end. A copy of Plex's database brings everything." %
             next((u["name"] for u in users if u["key"] == mine), mine)]
    return {"source": "Plex", "how": "address", "users": users, "records": _likes(records), "notes": notes}


def _plex_record(user, what, info, shows, **state):
    show = shows.get(info.get("show_key")) or {}
    extra = {}
    if what == "episode":
        extra = dict(show=info.get("show") or show.get("title"), show_year=show.get("year"), show_ids=show.get("ids") or {},
                     s=info.get("s"), e=info.get("e"))
    return record(user, what, title=info.get("title"), original=info.get("original"), year=info.get("year"),
                  paths=info.get("paths") or [], ids=info.get("ids") if what == "movie" else {},
                  duration=info.get("duration"), ref="plex:%s" % info.get("key"), **dict(extra, **state))


# ---------------------------------------------------------------- Jellyfin and Emby: the address and an API key

FIELDS = "ProviderIds,Path,ProductionYear,PremiereDate"


def _jf_items(base, h, user_id, params):
    """Every item a query finds, page by page. Jellyfin 10.9 and later also answer /Items?userId=…; Emby and
    every Jellyfin answer /Users/{id}/Items."""
    out, start = [], 0
    while True:
        q = dict(params, Recursive="true", Fields=FIELDS, EnableUserData="true", StartIndex=start, Limit=PAGE)
        page = _get(base, "/Users/%s/Items" % urllib.parse.quote(user_id), h, q) or {}
        rows = page.get("Items") or []
        out += rows
        start += len(rows)
        if not rows or start >= (_int(page.get("TotalRecordCount")) or 0):
            return out


def _jf_ids(item):
    return _ids((k, v) for k, v in (item.get("ProviderIds") or {}).items())


def read_jellyfin_api(url, key):
    """Every Jellyfin (or Emby) user's watched marks, places and favourites, through the server's API."""
    base = _base(url)
    key = str(key or "").strip()
    if not key:
        raise Problem("Paste an API key (Jellyfin: Dashboard → API Keys; Emby: Settings → Advanced → API Keys).")
    h = {"Authorization": 'MediaBrowser Client="Sofa", Device="Sofa", DeviceId="sofa-history-import", Version="1", '
                          'Token="%s"' % key.replace('"', ""), "X-Emby-Token": key}
    info = _get(base, "/System/Info", h) or {}
    name = "Jellyfin" if "jellyfin" in json.dumps(info).lower() else "Emby"    # (Jellyfin names itself; Emby doesn't)
    raw_users = _get(base, "/Users", h) or []
    if not isinstance(raw_users, list):
        raise Problem("That address answered, but not as Jellyfin or Emby.")
    users, records, series = [], [], {}
    for u in raw_users:
        policy = u.get("Policy") or {}
        if policy.get("IsDisabled"):
            continue
        limited = policy.get("MaxParentalRating") is not None or bool(policy.get("BlockUnratedItems"))
        users.append({"key": u.get("Id"), "name": u.get("Name") or u.get("Id"), "kids": limited})
    for u in users:
        uid = u["key"]
        found = {}
        for filt in ("IsPlayed", "IsResumable", "IsFavorite"):
            for it in _jf_items(base, h, uid, {"IncludeItemTypes": "Movie,Episode,Series", "Filters": filt}):
                found[it.get("Id")] = it
        need = {it.get("SeriesId") for it in found.values() if it.get("Type") == "Episode" and it.get("SeriesId")}
        need -= set(series)
        need = sorted(n for n in need if n)
        for i in range(0, len(need), 50):
            page = _get(base, "/Users/%s/Items" % urllib.parse.quote(uid), h,
                        {"Ids": ",".join(need[i:i + 50]), "Fields": FIELDS}) or {}
            for s in page.get("Items") or []:
                series[s.get("Id")] = s
        for it in found.values():
            rec = _jf_record(uid, it, series)
            if rec:
                records.append(rec)
    return {"source": name, "how": "address", "users": users, "records": _likes(records), "notes": []}


def _jf_record(user, it, series):
    data = it.get("UserData") or {}
    kind = {"Movie": "movie", "Episode": "episode", "Series": "show"}.get(it.get("Type"))
    if not kind:
        return None
    liked = bool(data.get("IsFavorite")) or data.get("Likes") is True
    position = (_number(data.get("PlaybackPositionTicks")) or 0) / TICKS
    watched = bool(data.get("Played"))
    if not (watched or position or liked or data.get("Rating") is not None):
        return None
    rec = dict(title=it.get("Name"), original=it.get("OriginalTitle"), year=_int(it.get("ProductionYear")),
               paths=[it["Path"]] if it.get("Path") else [], ids=_jf_ids(it) if kind != "episode" else {},
               watched=watched, position=position, duration=(_number(it.get("RunTimeTicks")) or 0) / TICKS or None,
               at=_when(data.get("LastPlayedDate")), liked=liked, rating=_number(data.get("Rating")),
               ref="jf:%s" % it.get("Id"))
    if kind == "episode":
        s = series.get(it.get("SeriesId")) or {}
        rec.update(show=it.get("SeriesName") or s.get("Name"), show_year=_int(s.get("ProductionYear")),
                   show_ids=_jf_ids(s), s=_int(it.get("ParentIndexNumber")), e=_int(it.get("IndexNumber")))
    if kind == "show":
        rec.update(watched=False, position=0.0, paths=[])
    return record(user, kind, **rec)


# ---------------------------------------------------------------- Jellyfin: its database

def _jellyfin_files(path):
    """jellyfin.db (10.11 and later: everything in it) or library.db (10.10 and before, with the users in jellyfin.db
    beside it). A folder is searched for them."""
    if os.path.isdir(path):
        for d in (path, os.path.join(path, "data")):
            for n in ("jellyfin.db", "library.db"):
                if os.path.isfile(os.path.join(d, n)):
                    return _jellyfin_files(os.path.join(d, n))
        raise Problem("There's no jellyfin.db or library.db in %s." % path)
    folder = os.path.dirname(path)
    other = os.path.join(folder, "jellyfin.db" if os.path.basename(path) == "library.db" else "library.db")
    return path, other if os.path.isfile(other) else None


def read_jellyfin_db(path):
    """Every Jellyfin user's watched marks, places and favourites, from a copy of its database."""
    first, other = _jellyfin_files(path)
    opened = []
    try:
        conn, folder = _snapshot(first)
        opened.append((conn, folder))
        tables = _tables(conn)
        if {"BaseItems", "UserData", "Users"} <= tables:
            return _jellyfin_new(conn)
        main = conn
        if "TypedBaseItems" not in tables:
            if not other:
                raise Problem("That isn't Jellyfin's database (jellyfin.db or library.db).")
            main, f2 = _snapshot(other)
            opened.append((main, f2))
        users_conn = conn if main is not conn else None
        if users_conn is None and other:
            users_conn, f3 = _snapshot(other)
            opened.append((users_conn, f3))
        return _jellyfin_old(main, users_conn)
    except sqlite3.DatabaseError as exc:
        raise Problem("Jellyfin's database couldn't be read (%s)." % exc)
    finally:
        for c, f in opened:
            c.close()
            shutil.rmtree(f, ignore_errors=True)


def _jf_type(t):
    t = str(t or "")
    return "movie" if t.endswith(".Movie") else "episode" if t.endswith(".Episode") else "show" if t.endswith(".Series") else None


def _jellyfin_new(conn):
    """Jellyfin 10.11 and later: BaseItems, BaseItemProviders, UserData and Users in jellyfin.db."""
    users = []
    ucols = _columns(conn, "Users")
    for r in conn.execute("SELECT * FROM Users"):
        r = dict(r)
        limited = any(r.get(c) is not None for c in ("MaxParentalRatingScore", "MaxParentalAgeRating") if c in ucols)
        users.append({"key": str(r["Id"]).lower(), "name": r.get("Username") or str(r["Id"]), "kids": limited})
    items = {}
    for r in conn.execute("SELECT Id, Type, Name, OriginalTitle, ProductionYear, Path, IndexNumber, ParentIndexNumber, "
                          "SeriesName, SeriesId, RunTimeTicks FROM BaseItems"):
        kind = _jf_type(r["Type"])
        if kind:
            items[_guid_text(r["Id"])] = dict(r, kind=kind)
    ids = {}
    if "BaseItemProviders" in _tables(conn):
        for r in conn.execute("SELECT ItemId, ProviderId, ProviderValue FROM BaseItemProviders"):
            ids.setdefault(_guid_text(r["ItemId"]), []).append((r["ProviderId"], r["ProviderValue"]))
    cols = _columns(conn, "UserData")
    likes = "Likes" if "Likes" in cols else "NULL"
    records, rows = [], {}
    for r in conn.execute("SELECT ItemId, UserId, Played, PlayCount, IsFavorite, PlaybackPositionTicks, LastPlayedDate, "
                          "Rating, %s AS Likes FROM UserData" % likes):
        # One row per key an item is known by (its own id, its TMDB id, its IMDb id…): the same state, kept once
        # (the newest, should they differ).
        k = (str(r["UserId"]).lower(), _guid_text(r["ItemId"]))
        if k not in rows or (_when(r["LastPlayedDate"]) or 0) > (_when(rows[k]["LastPlayedDate"]) or 0):
            rows[k] = r
    for r in rows.values():
        it = items.get(_guid_text(r["ItemId"]))
        if not it:
            continue
        series = items.get(_guid_text(it["SeriesId"])) or {}
        rec = _jf_db_record(str(r["UserId"]).lower(), it, r, _ids(ids.get(_guid_text(it["Id"]), [])),
                            series, _ids(ids.get(_guid_text(series.get("Id")), [])))
        if rec:
            records.append(rec)
    return {"source": "Jellyfin", "how": "database", "users": users, "records": _likes(records), "notes": []}


def _jellyfin_old(main, users_conn):
    """Jellyfin 10.10 and before: TypedBaseItems and UserDatas in library.db (keyed by each item's UserDataKey),
    the users in jellyfin.db."""
    users, by_internal = [], {}
    if users_conn is not None and "Users" in _tables(users_conn):
        ucols = _columns(users_conn, "Users")
        for r in users_conn.execute("SELECT * FROM Users"):
            r = dict(r)
            key = str(r.get("InternalId") if "InternalId" in ucols else r["Id"])
            limited = r.get("MaxParentalAgeRating") is not None if "MaxParentalAgeRating" in ucols else None
            users.append({"key": key, "name": r.get("Username") or key, "kids": limited})
            by_internal[key] = True
    items, by_key, series_by_guid = {}, {}, {}
    cols = _columns(main, "TypedBaseItems")
    extra = ", UserDataKey" if "UserDataKey" in cols else ""
    for r in main.execute("SELECT guid, type, Name, OriginalTitle, ProductionYear, Path, IndexNumber, ParentIndexNumber, "
                          "SeriesName, SeriesId, RunTimeTicks, ProviderIds, PresentationUniqueKey%s FROM TypedBaseItems" % extra):
        kind = _jf_type(r["type"])
        if not kind:
            continue
        it = dict(r, kind=kind, Id=_guid_text(r["guid"]), Type=r["type"])
        items[it["Id"]] = it
        dashed = "%s-%s-%s-%s-%s" % (it["Id"][:8], it["Id"][8:12], it["Id"][12:16], it["Id"][16:20], it["Id"][20:])
        for k in (it.get("UserDataKey"), it.get("PresentationUniqueKey"), it["Id"], dashed):
            if k:
                by_key.setdefault(k, it)
        if kind == "show":
            series_by_guid[it["Id"]] = it
    records, rows = [], {}
    for r in main.execute("SELECT * FROM UserDatas"):
        r = dict(r)
        it = by_key.get(r.get("key") or r.get("Key"))
        if not it:
            continue
        uid = str(r.get("userId") if "userId" in r else r.get("UserId"))
        k = (uid, it["Id"])          # (one row per key the item is known by: kept once, the newest)
        if k not in rows or (_when(r.get("lastPlayedDate")) or 0) > (_when(rows[k][1].get("lastPlayedDate")) or 0):
            rows[k] = (it, r)
    for (uid, _), (it, r) in rows.items():
        if uid not in by_internal:
            users.append({"key": uid, "name": "Jellyfin user %s" % uid, "kids": None})
            by_internal[uid] = True
        series = series_by_guid.get(_guid_text(it.get("SeriesId"))) or {}
        rec = _jf_db_record(uid, it, {"Played": r.get("played"), "IsFavorite": r.get("isFavorite"),
                                      "PlaybackPositionTicks": r.get("playbackPositionTicks"),
                                      "LastPlayedDate": r.get("lastPlayedDate"), "Rating": r.get("rating"),
                                      "Likes": r.get("likes")},
                            _ids(_provider_pairs(it.get("ProviderIds"))), series, _ids(_provider_pairs(series.get("ProviderIds"))))
        if rec:
            records.append(rec)
    return {"source": "Jellyfin", "how": "database", "users": users, "records": _likes(records), "notes": []}


def _guid_text(v):
    """An id as 32 lower-case hex digits, however it's kept: 16 bytes in .NET's order (library.db's guid column), or
    text with or without dashes (its SeriesId column, jellyfin.db)."""
    if isinstance(v, (bytes, bytearray)):
        if len(v) == 16:
            import uuid
            return uuid.UUID(bytes_le=bytes(v)).hex
        v = bytes(v).decode("ascii", "replace")
    return str(v or "").lower().replace("-", "")


def _provider_pairs(text):
    """'Imdb=tt0113277|Tmdb=949' (how library.db keeps them)."""
    return [tuple(p.split("=", 1)) for p in str(text or "").split("|") if "=" in p]


def _jf_db_record(user, it, r, own_ids, series, series_ids):
    r = dict(r)
    kind = it["kind"]
    liked = bool(r.get("IsFavorite")) or r.get("Likes") in (1, True)
    position = (_number(r.get("PlaybackPositionTicks")) or 0) / TICKS
    watched = bool(r.get("Played"))
    if not (watched or position or liked or r.get("Rating") is not None):
        return None
    rec = dict(title=it.get("Name"), original=it.get("OriginalTitle"), year=_int(it.get("ProductionYear")),
               paths=[it["Path"]] if it.get("Path") and kind != "show" else [], ids=own_ids if kind != "episode" else {},
               watched=watched and kind != "show", position=position if kind != "show" else 0.0,
               duration=(_number(it.get("RunTimeTicks")) or 0) / TICKS or None, at=_when(r.get("LastPlayedDate")),
               liked=liked, rating=_number(r.get("Rating")), ref="jf:%s" % it.get("Id"))
    if kind == "episode":
        rec.update(show=it.get("SeriesName") or series.get("Name"), show_year=_int(series.get("ProductionYear")),
                   show_ids=series_ids, s=_int(it.get("ParentIndexNumber")), e=_int(it.get("IndexNumber")))
    return record(user, kind, **rec)


def read(source, path=None, url=None, secret=None):
    """Read a source. `secret` (a token or key) is used for this read only."""
    if source == "plex-db":
        return read_plex_db(path)
    if source == "plex":
        return read_plex_api(url, secret)
    if source == "jellyfin":
        return read_jellyfin_api(url, secret)
    if source == "jellyfin-db":
        return read_jellyfin_db(path)
    raise Problem("Pick where to bring history from.")


# ---------------------------------------------------------------- Sofa's side: what's here, and how to find it

TAG = re.compile(r"[\[{(]\s*(imdb|tmdb|tvdb)(?:id)?\s*[-=: ]\s*(tt\d{5,10}|\d{1,10})\s*[\]})]", re.I)
BARE_IMDB = re.compile(r"(?<![a-z0-9])(tt\d{7,10})(?![0-9])", re.I)


def ids_in_name(text):
    """{imdb-tt0113277}, [tmdbid-949], [tvdbid=81189], or a bare tt0113277, in a file or folder name."""
    pairs = [(m.group(1), m.group(2)) for m in TAG.finditer(text or "")]
    pairs += [("imdb", m.group(1)) for m in BARE_IMDB.finditer(text or "")]
    return _ids(pairs)


def ids_in_nfo(path):
    """The ids a Kodi-style .nfo keeps: <uniqueid type="imdb">, <imdbid>, <tmdbid>, <tvdbid>, or an <id> of tt…."""
    try:
        if os.path.getsize(path) > 2 * 1024 * 1024:
            return {}
        with open(path, "rb") as f:
            raw = f.read()
        if b"<!ENTITY" in raw or b"<!DOCTYPE" in raw:
            return {}
        root = ET.fromstring(raw)
    except (OSError, ET.ParseError, ValueError):
        return {}
    pairs = [(el.get("type"), el.text) for el in root.iter("uniqueid")]
    for tag, kind in (("imdbid", "imdb"), ("imdb_id", "imdb"), ("imdb", "imdb"), ("tmdbid", "tmdb"),
                      ("tvdbid", "tvdb"), ("id", "imdb")):
        el = root.find(tag)
        if el is not None and el.text:
            pairs.append((kind, el.text))
    return _ids(pairs)


def _key(path):
    """A path as compared: one kind of slash, one Unicode form (a Mac spells é two ways), any case, no extension
    (Sofa's own conversion turns a .mkv into an .mp4 of the same name)."""
    p = unicodedata.normalize("NFC", str(path or "")).replace("\\", "/").rstrip("/")
    head, _, last = p.rpartition("/")
    stem, dot, ext = last.rpartition(".")
    if dot and stem and len(ext) <= 5:
        last = stem
    return (head + "/" + last).casefold() if head else last.casefold()


def parse_map(text):
    """Folder map lines: "FROM => TO" (or ->, →, or =). Returns [(from, to)], longest FROM first."""
    pairs = []
    lines = text if isinstance(text, (list, tuple)) else str(text or "").splitlines()
    for line in lines:
        if isinstance(line, (list, tuple)) and len(line) == 2:
            a, b = line
        else:
            line = str(line).strip()
            if not line or line.startswith("#"):
                continue
            for sep in ("=>", "->", "→", "\t", "="):
                if sep in line:
                    a, _, b = line.partition(sep)
                    break
            else:
                raise Problem("A folder map line needs two folders, like /data/movies => /Volumes/Media/Movies.")
        a = unicodedata.normalize("NFC", str(a).strip()).replace("\\", "/").rstrip("/")
        b = str(b).strip().rstrip("/\\")
        if not a or not b:
            raise Problem("A folder map line needs two folders, like /data/movies => /Volumes/Media/Movies.")
        pairs.append((a, b))
    return sorted(pairs, key=lambda p: -len(p[0]))


def map_path(path, pairs):
    """Where a source's file is on this computer, by the folder map (the path as it is when nothing applies)."""
    p = unicodedata.normalize("NFC", str(path or "")).replace("\\", "/")
    for a, b in pairs:
        if p[:len(a)].casefold() == a.casefold() and (len(p) == len(a) or p[len(a)] == "/"):
            return b.replace("\\", "/") + p[len(a):]
    return p


class Index:
    """Sofa's library, looked at every way the matching needs. Ids are read only when something needs them."""

    def __init__(self, library=None):
        if library is None:
            from .library import LIBRARY as library
        with library.lock:
            items = dict(library.items)
            self.shows = list(library.shows) + list(library.adult.get("shows") or [])
            self.movies = list(library.movies) + list(library.adult.get("movies") or [])
        self.dirs = dict(getattr(library, "dirs", {}) or {})
        self.items = {k: v for k, v in items.items() if v.get("kind") in ("movie", "episode")}
        self.entries = {x["id"]: x for x in self.shows + self.movies}
        self.by_path, self.by_tail, self.episodes, self.titles, self.names = {}, {}, {}, {}, {}
        for item_id, it in self.items.items():
            k = _key(it.get("path"))
            self.by_path.setdefault(k, set()).add(item_id)
            self.by_tail.setdefault("/".join(k.split("/")[-2:]), set()).add(item_id)
            if it["kind"] == "episode" and it.get("s") is not None and it.get("e") is not None:
                for e in range(it["e"], max(it["e"], it.get("e2") or it["e"]) + 1):
                    self.episodes.setdefault((it["show_id"], it["s"], e), item_id)
        for m in self.movies:
            if m.get("adult"):
                continue
            year = _int(m.get("year"))
            for t in (m.get("title"), _slug_title(m["id"])):
                if t:
                    self.titles.setdefault(naming.norm(t), {}).setdefault(year, set()).add(m["id"])
        for s in self.shows:
            if s.get("adult"):
                continue
            for t in (s.get("name"), naming.show_name(s.get("folder") or "")[0] if s.get("folder") else None):
                if t:
                    self.names.setdefault(naming.norm(t), set()).add(s["id"])
        self._movie_ids = self._show_ids = None

    # ids, read once and only when needed

    def movie_ids(self):
        if self._movie_ids is None:
            self._movie_ids = {}
            for m in self.movies:
                if m.get("adult"):
                    continue
                it = self.items.get(m["id"]) or {}
                for kind, v in self._ids_for_movie(m, it).items():
                    self._movie_ids.setdefault((kind, v), set()).add(m["id"])
        return self._movie_ids

    def show_ids(self):
        if self._show_ids is None:
            self._show_ids = {}
            for s in self.shows:
                if s.get("adult"):
                    continue
                for kind, v in self._ids_for_show(s).items():
                    self._show_ids.setdefault((kind, v), set()).add(s["id"])
        return self._show_ids

    def _ids_for_movie(self, m, it):
        out = {}
        path = it.get("path") or ""
        folder, name = os.path.split(path)
        for found in (ids_in_name(os.path.splitext(name)[0]), ids_in_name(os.path.basename(folder)),
                      ids_in_nfo(os.path.join(folder, os.path.splitext(name)[0] + ".nfo")) if path else {},
                      ids_in_nfo(os.path.join(folder, "movie.nfo")) if path else {}, self._saved_movie(m)):
            for k, v in found.items():
                out.setdefault(k, v)
        return out

    def _ids_for_show(self, s):
        out = {}
        folder = self.dirs.get(s["id"])
        for found in (ids_in_name(s.get("folder") or ""), ids_in_nfo(os.path.join(folder, "tvshow.nfo")) if folder else {},
                      self._saved_show(s)):
            for k, v in found.items():
                out.setdefault(k, v)
        return out

    @staticmethod
    def _saved(fn):
        """What Sofa saved when it looked a title up (never asking the internet now)."""
        before = getattr(metadata._local, "saved_only", False)
        metadata.saved_only(True)
        try:
            return fn() or {}
        except Exception:
            return {}
        finally:
            metadata.saved_only(before)

    def _saved_movie(self, m):
        parts = m["id"].split(":")
        if len(parts) < 3 or parts[0] != "m":
            return {}
        fix = metadata.override(m["id"]) or {}
        found = self._saved(lambda: metadata.movie(parts[1].replace("-", " "), _int(parts[2]), fix))
        ids = {}
        if fix.get("tmdb"):
            ids["tmdb"] = fix["tmdb"]
        if found.get("source") == "TMDB" and found.get("source_id"):
            ids["tmdb"] = found["source_id"]
        return _ids(ids.items())

    def _saved_show(self, s):
        if not s.get("folder"):
            return {}
        name, year = naming.show_name(s["folder"])
        found = self._saved(lambda: metadata.tv_show(name, year, metadata.override(s["id"])))
        ext = found.get("externals") or {}
        return _ids([("tvdb", ext.get("thetvdb")), ("imdb", ext.get("imdb"))])

    # finding

    def by_file(self, paths, pairs):
        for p in paths:
            for candidate in (map_path(p, pairs), p):
                hit = self.by_path.get(_key(candidate))
                if hit and len(hit) == 1:
                    return next(iter(hit))
        for p in paths:                                    # the same folder and file name, anywhere
            k = _key(map_path(p, pairs))
            hit = self.by_tail.get("/".join(k.split("/")[-2:]))
            if hit and len(hit) == 1 and "/" in k:
                return next(iter(hit))
        return None

    def movie_by_ids(self, ids):
        found = set()
        for kind in ID_KINDS:
            if ids.get(kind):
                found |= self.movie_ids().get((kind, ids[kind]), set())
                if found:
                    break
        return found

    def show_by_ids(self, ids):
        found = set()
        for kind in ("tvdb", "imdb", "tmdb"):
            if ids.get(kind):
                found |= self.show_ids().get((kind, ids[kind]), set())
                if found:
                    break
        return found

    def movie_by_title(self, titles, year):
        for t in titles:
            years = self.titles.get(naming.norm(t or "")) if t else None
            if not years:
                continue
            if year in years:
                return years[year]
            near = set()
            for y, ids in years.items():
                if year is None or y is None or abs(y - year) == 1:
                    near |= ids
            if near:
                return near
        return set()

    def show_by_name(self, titles, year):
        for t in titles:
            hits = self.names.get(naming.norm(t or "")) if t else None
            if not hits:
                continue
            if len(hits) > 1 and year:
                same = {h for h in hits if _show_year(self.entries.get(h)) == year}
                if same:
                    return same
            return hits
        return set()


def _slug_title(entry_id):
    parts = entry_id.split(":")
    return parts[1].replace("-", " ") if len(parts) >= 3 and parts[0] == "m" else None


def _show_year(entry):
    if not entry:
        return None
    y = _int(str(entry.get("premiered") or "")[:4])
    return y or naming.show_name(entry.get("folder") or "")[1]


def match(rec, index, pairs):
    """(Sofa id, how) for a record, or (None, why). `how`: "path", "ids" or "title"; `why`: "missing" or
    "ambiguous". A show record finds its show; a movie or episode its item."""
    kind = rec["kind"]
    if kind in ("movie", "episode") and rec["paths"]:
        hit = index.by_file(rec["paths"], pairs)
        if hit:
            return hit, "path"
    if kind == "movie":
        for how, found in (("ids", lambda: index.movie_by_ids(rec["ids"])),
                           ("title", lambda: index.movie_by_title([rec["title"], rec["original"]], rec["year"]))):
            hits = found()
            if len(hits) == 1:
                return next(iter(hits)), how
            if len(hits) > 1:
                return None, "ambiguous"
        return None, "missing"
    if kind == "show":
        ids, titles, year = rec["ids"], [rec["title"], rec["original"]], rec["year"]
    else:
        ids, titles, year = rec["show_ids"], [rec["show"]], rec["show_year"]
    for how, found in (("ids", lambda: index.show_by_ids(ids)), ("title", lambda: index.show_by_name(titles, year))):
        hits = found()
        if len(hits) > 1:
            return None, "ambiguous"
        if hits:
            show_id = next(iter(hits))
            if kind == "show":
                return show_id, how
            if rec["s"] is None or rec["e"] is None:
                return None, "missing"
            item = index.episodes.get((show_id, rec["s"], rec["e"]))
            return (item, how) if item else (None, "missing")
    return None, "missing"


# ---------------------------------------------------------------- the plan (the dry run) and the import

def profiles():
    """The profiles history can go to: not guests, not people still waiting for an account."""
    return [{"id": r["id"], "name": r["name"], "kids": bool(r["kids"]), "adult": bool(r["adult"]) and not r["kids"],
             "admin": bool(r["admin"])}
            for r in store.q("SELECT id, name, admin, adult, kids FROM users WHERE guest = 0 AND pending = 0 ORDER BY id")]


def suggest(users, sofa=None):
    """A source user goes to the Sofa profile with the same name, if there is one."""
    sofa = profiles() if sofa is None else sofa
    names = {p["name"].casefold(): p["id"] for p in sofa}
    return {u["key"]: names.get(str(u["name"]).casefold()) for u in users}


def _label(rec):
    if rec["kind"] == "episode":
        return "%s S%02dE%02d" % (rec["show"] or "?", rec["s"] or 0, rec["e"] or 0)
    return "%s (%d)" % (rec["title"], rec["year"]) if rec["year"] else str(rec["title"] or "?")


def _state(rec):
    """(t, d, done, at in ms or None) to write for a record's progress, or None when it has none.

    A place partway through is kept as a place (Plex and Jellyfin both show a started re-watch as "continue"); a
    title watched to the end is marked watched."""
    d = _number(rec["duration"]) or 0.0
    t = _number(rec["position"]) or 0.0
    at = int(rec["at"] * 1000) if rec["at"] else None
    if t > 0 and not (d and t >= d * 0.95):
        return (min(t, d) if d else t, d, 0, at)
    if rec["watched"] or t > 0:
        return (d, d, 1, at)
    return None


def _better(a, b):
    """Of two records for the same title and profile, the one to keep: the newer, then the further along."""
    ka = (a["at"] or 0, bool(a["watched"]) and not a["position"], a["position"] or 0)
    kb = (b["at"] or 0, bool(b["watched"]) and not b["position"], b["position"] or 0)
    return a if ka >= kb else b


def plan(data, mapping, pairs=(), index=None, sofa=None):
    """What an import would do, written nowhere. `mapping`: source user key -> Sofa profile id (or None).

    Returns {"users": [...], "writes": [...], "likes": [...]} with every record's outcome in "rows"."""
    index = index or Index()
    sofa = {p["id"]: p for p in (profiles() if sofa is None else sofa)}
    picked = kids.choices()
    pairs = parse_map(pairs)
    rows, best, liked = [], {}, {}
    for rec in data["records"]:
        target, how = match(rec, index, pairs)
        uid = mapping.get(rec["user"])
        prof = sofa.get(uid) if uid is not None else None
        row = {"user": rec["user"], "kind": rec["kind"], "label": _label(rec), "match": how if target else None,
               "why": None if target else how, "id": target, "profile": prof["id"] if prof else None, "outcome": None}
        rows.append(row)
        if not target:
            row["outcome"] = "unmatched" if how == "missing" else "ambiguous"
            continue
        thing = index.items.get(target) or index.entries.get(target) or {}
        row["adult"] = bool(thing.get("adult"))
        if not prof:
            row["outcome"] = "no-profile"
            continue
        owner = index.entries.get(thing.get("show_id")) if rec["kind"] == "episode" else index.entries.get(target)
        if row["adult"] and not prof["adult"]:
            row["outcome"] = "skip-adult"
            continue
        if prof["kids"] and not kids.allowed(owner, picked):
            row["outcome"] = "skip-kids"
            continue
        row["outcome"] = "matched"
        if rec["kind"] != "show" and _state(rec):
            k = (prof["id"], target)          # two versions, two episodes in one file, two people to one profile
            if k not in best:
                best[k] = (rec, row)
            elif _better(rec, best[k][0]) is rec:
                best[k][1]["outcome"] = "merged"
                best[k] = (rec, row)
            else:
                row["outcome"] = "merged"
        if rec["liked"] and rec["kind"] in ("movie", "show"):
            liked.setdefault((prof["id"], target), rec)
    # Against what Sofa has now.
    have = {}
    for uid in {k[0] for k in best}:
        for r in store.q("SELECT item, t, d, done, at FROM progress WHERE user_id = ?", uid):
            have[(uid, r["item"])] = dict(r)
    writes = []
    for (uid, item), (rec, row) in best.items():
        t, d, done, at = _state(rec)
        cur = have.get((uid, item))
        same = cur and bool(cur["done"]) == bool(done) and (done or abs((cur["t"] or 0) - t) < 2)
        if same:
            row["outcome"] = "same"
        elif cur and (at is None or (cur["at"] or 0) >= at):
            row["outcome"] = "sofa-newer"
        else:
            row["outcome"] = "update" if cur else "new"
            writes.append({"user": uid, "item": item, "t": t, "d": d, "done": done, "at": at})
    have_likes = set()
    for uid in {k[0] for k in liked}:
        have_likes |= {(uid, r["item"]) for r in store.q("SELECT item FROM likes WHERE user_id = ?", uid)}
    likes = [{"user": uid, "item": item, "at": int(rec["at"] * 1000) if rec["at"] else None}
             for (uid, item), rec in liked.items() if (uid, item) not in have_likes]
    return {"source": data["source"], "how": data["how"], "notes": data.get("notes") or [], "rows": rows,
            "writes": writes, "likes": likes, "users": data["users"], "mapping": dict(mapping)}


def apply(p):
    """Write a plan: in one transaction, never over a place in Sofa that's newer (checked again as it's written),
    likes added and never taken away. Returns what was written."""
    conn = store.db()
    now = int(time.time() * 1000)
    wrote = liked = 0
    try:
        for w in p["writes"]:
            t, d = _number(w["t"]), _number(w["d"])
            if t is None or d is None:
                continue
            if w["at"] is None:                     # no date from the source: only where Sofa has nothing
                cur = conn.execute("INSERT OR IGNORE INTO progress (user_id, item, t, d, done, at) VALUES (?,?,?,?,?,?)",
                                   (w["user"], w["item"], t, d, w["done"], 0))
            else:
                cur = conn.execute("INSERT INTO progress (user_id, item, t, d, done, at) VALUES (?,?,?,?,?,?) "
                                   "ON CONFLICT(user_id, item) DO UPDATE SET t = excluded.t, d = excluded.d, "
                                   "done = excluded.done, at = excluded.at WHERE excluded.at > progress.at",
                                   (w["user"], w["item"], t, d, w["done"], min(int(w["at"]), now)))
            wrote += cur.rowcount > 0
        for lk in p["likes"]:
            cur = conn.execute("INSERT OR IGNORE INTO likes (user_id, item, at) VALUES (?,?,?)",
                               (lk["user"], lk["item"], min(int(lk["at"] or now), now)))
            liked += cur.rowcount > 0
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    people = len({w["user"] for w in p["writes"]} | {lk["user"] for lk in p["likes"]})
    if wrote or liked:
        store.log("history", "History brought in from %s: %d watched or started, %d likes, for %d profile%s" %
                  (p["source"], wrote, liked, people, "" if people == 1 else "s"))
    return {"progress": wrote, "likes": liked, "profiles": people}


def summary(p, adult_ok=False):
    """The dry run as the Server page and the command line show it. Adult titles are never named to someone whose
    Adult switch is off."""
    out = []
    names = {p2["id"]: p2["name"] for p2 in profiles()}
    for u in p["users"]:
        mine = [r for r in p["rows"] if r["user"] == u["key"]]
        count = lambda *o: sum(1 for r in mine if r["outcome"] in o)       # noqa: E731
        label = lambda r: "An Adult title" if r.get("adult") and not adult_ok else r["label"]   # noqa: E731
        why = {"ambiguous": "more than one title in Sofa could be this one", "sofa-newer": "Sofa's place is newer",
               "skip-kids": "not a family title (Kids profile)", "skip-adult": "Adult section (not on for this profile)"}
        out.append({
            "key": u["key"], "name": u["name"], "kids": u.get("kids"), "profile": p["mapping"].get(u["key"]),
            "profile_name": names.get(p["mapping"].get(u["key"])),
            "titles": len(mine),
            "matched": {h: sum(1 for r in mine if r["match"] == h) for h in ("path", "ids", "title")},
            "unmatched": count("unmatched"), "conflicts": count("ambiguous", "sofa-newer"),
            "skipped": count("skip-kids", "skip-adult"), "new": count("new", "update"), "same": count("same"),
            "lists": {
                "unmatched": [label(r) for r in mine if r["outcome"] == "unmatched"][:LIST_LIMIT],
                "conflicts": [{"title": label(r), "why": why[r["outcome"]]} for r in mine
                              if r["outcome"] in ("ambiguous", "sofa-newer")][:LIST_LIMIT],
                "skipped": [{"title": label(r), "why": why[r["outcome"]]} for r in mine
                            if r["outcome"] in ("skip-kids", "skip-adult")][:LIST_LIMIT],
            }})
    total = len(p["rows"])
    hit = sum(1 for r in p["rows"] if r["match"])
    return {"source": p["source"], "how": p["how"], "notes": p["notes"], "users": out, "titles": total, "found": hit,
            "writes": len(p["writes"]), "likes": len(p["likes"]),
            "by": {h: sum(1 for r in p["rows"] if r["match"] == h) for h in ("path", "ids", "title")}}


# ---------------------------------------------------------------- the Server page's import, one at a time

_lock = threading.Lock()
_job = {"state": "idle"}


def status(adult_ok=False):
    with _lock:
        job = dict(_job)
    if job.get("data") and time.time() - job.get("read_at", 0) > KEEP_SECONDS:
        forget()
        job = {"state": "idle", "message": "What was read was forgotten after an hour. Read it again to import."}
    out = {k: job.get(k) for k in ("state", "message", "result", "source", "how")}
    if job.get("plan"):
        out["report"] = summary(job["plan"], adult_ok)
    out["profiles"] = profiles()
    return out


def start_read(source, path=None, url=None, secret=None, pairs=""):
    """Read a source in the background; the Server page asks status() how it's going."""
    parse_map(pairs)                                   # a wrong map line is said now, not after the read
    with _lock:
        if _job.get("state") in ("reading", "importing"):
            raise Problem("An import is already under way.")
        _job.clear()
        _job.update(state="reading", source=SOURCES.get(source, source), message=None)

    def work():
        try:
            data = read(source, path=path, url=url, secret=secret)
            p = plan(data, suggest(data["users"]), pairs)
            with _lock:
                _job.update(state="ready", data=data, plan=p, pairs=pairs, read_at=time.time(), how=data["how"],
                            source=data["source"])
        except Problem as exc:
            with _lock:
                _job.update(state="failed", message=str(exc))
        except Exception as exc:                       # (said, and in the log; never the token)
            print("History import: reading failed: %r" % (exc,), flush=True)
            with _lock:
                _job.update(state="failed", message="Reading it didn't work (%s)." % exc.__class__.__name__)
    threading.Thread(target=work, name="History import", daemon=True).start()


def replan(mapping, pairs=None):
    with _lock:
        data = _job.get("data")
        pairs = _job.get("pairs", "") if pairs is None else pairs
    if not data:
        raise Problem("Read your Plex or Jellyfin history first.")
    p = plan(data, _clean_mapping(mapping), pairs)
    with _lock:
        _job.update(plan=p, pairs=pairs)
    return p


def run_import(mapping, pairs=None):
    """The import itself: planned again from what Sofa has this moment, then written."""
    p = replan(mapping, pairs)
    with _lock:
        _job["state"] = "importing"
    try:
        result = apply(p)
    except Exception:
        with _lock:
            _job["state"] = "ready"
        raise
    forget()
    with _lock:
        _job.update(state="done", result=result, source=p["source"])
    return result


def forget():
    with _lock:
        for k in ("data", "plan", "pairs", "read_at"):
            _job.pop(k, None)
        if _job.get("state") in ("ready", "failed"):
            _job["state"] = "idle"


def _clean_mapping(mapping):
    ok = {p["id"] for p in profiles()}
    out = {}
    for k, v in (mapping or {}).items():
        v = _int(v)
        out[str(k)] = v if v in ok else None
    return out
