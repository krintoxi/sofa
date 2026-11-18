"""Sofa 1.5.18: bringing watch history from Plex, Jellyfin and Emby (sofa/history.py, sofa/history_cli.py).

The sources are made here: Plex's database with the tables and columns Plex keeps, Jellyfin's database as 10.11 and
later keep it (jellyfin.db) and as 10.10 and before did (library.db beside jellyfin.db), and stand-in Plex and
Jellyfin servers on this computer answering as theirs do. Sofa's side is a small, untidy library: a converted file,
a renamed one, ids in a folder name and an .nfo, a remake, two films of the same name, a two-episode file, a special,
an Adult title, and things that aren't there at all.
"""
import http.server
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.parse

from tests import LIBRARY, ROOT, video
from sofa import auth, config, history, history_cli, kids, metadata, store, web
from sofa.library import LIBRARY as LIB
from tests.test_server import Client

MOVIES, SHOWS, ADULT = (os.path.join(LIBRARY, d) for d in ("Movies", "Shows", "Adult"))
SOFA = [
    "Movies/Harbor Lights (1994)/Harbor Lights (1994).mp4",             # Plex had the .mkv: by path, through the map
    "Movies/Copper Sky (2016)/Copper Sky (2016).mp4",                   # by the TMDB id Sofa saved when it looked it up
    "Movies/Quiet Engine (1999) {imdb-tt0090001}/Quiet Engine (1999) {imdb-tt0090001}.mp4",   # by the id in the name
    "Movies/Lantern Field (2003)/Lantern Field (2003).mp4",             # by the id in its .nfo
    "Movies/Night Ferry (1984)/Night Ferry (1984).mp4",                 # a film and its remake: by title and year
    "Movies/Night Ferry (2021)/Night Ferry (2021).mp4",
    "Movies/Glass Orchard (1982)/Glass Orchard (1982).mp4",             # two of the same name, and no year to choose by
    "Movies/Glass Orchard (2011)/Glass Orchard (2011).mp4",
    "Movies/Paper Moons (2014)/Paper Moons (2014).mp4",                 # a family film (a Kids profile may)
    "Shows/Tidewater (2018)/Season 1/Tidewater S01E01.mp4",
    "Shows/Tidewater (2018)/Season 1/Tidewater S01E02.mp4",
    "Shows/Tidewater (2018)/Season 1/Tidewater S01E03-E04.mp4",         # two episodes in one file
    "Shows/Tidewater (2018)/Specials/Tidewater S00E01.mp4",
    "Shows/Low Orbit (2022)/Season 1/Low Orbit S01E01.mp4",             # the show by the TVDB id in its tvshow.nfo
    "Shows/Low Orbit (2022)/Season 1/Low Orbit S01E02.mp4",
    "Adult/Movies/Velvet Hour/Velvet Hour.mp4",
]
TOKEN = "plex-token-never-kept-7f3a"
KEY = "jellyfin-key-never-kept-91c2"
MAP = "/data/movies => %s\n/data/tv => %s\nD:\\Adult => %s" % (MOVIES, SHOWS, os.path.join(ADULT, "Movies"))
T0 = 1700000000          # (a fixed "when": 2023-11-14)


# ---------------------------------------------------------------- what each source holds

# (user, kind, title, year, show, show_year, s, e, path, ids, show_ids, watched, position, duration, at, rating, liked)
def _plex_history():
    """Four Plex accounts: the owner (same name as a Sofa profile), a grown-up, a child, and someone left out."""
    H = []

    def add(user, kind, title, year=None, path=None, ids=None, watched=False, position=0, at=T0, rating=None,
            show=None, show_year=None, s=None, e=None, show_ids=None, duration=6000):
        H.append(dict(user=user, kind=kind, title=title, year=year, path=path, ids=ids or {}, watched=watched,
                      position=position, at=at, rating=rating, show=show, show_year=show_year, s=s, e=e,
                      show_ids=show_ids or {}, duration=duration))
    tw = dict(show="Tidewater", show_year=2018)
    lo = dict(show="Low Orbit (US)", show_year=2022, show_ids={"tvdb": "999001"})
    add(1, "movie", "Harbor Lights", 1994, "/data/movies/Harbor Lights (1994)/Harbor Lights (1994).mkv", watched=True)
    add(1, "movie", "Copper Sky: First Light", 2016, "/elsewhere/CopperSky.2016.mkv", {"tmdb": "424242"}, position=1200, at=T0 + 50)
    add(1, "movie", "Engine Room", 1999, None, {"imdb": "tt0090001"}, watched=True, at=T0 + 60)
    add(1, "movie", "Lanterns", 2003, None, {"imdb": "tt0090002"}, rating=8.0, at=T0 + 70)
    add(1, "movie", "Night Ferry", 2021, None, watched=True, at=T0 + 80)
    add(1, "movie", "Glass Orchard", None, None, watched=True, at=T0 + 90)
    add(1, "movie", "Last Signal", 2020, "/data/movies/Last Signal (2020)/Last Signal (2020).mkv", watched=True)
    add(1, "episode", "Pilot", None, "/data/tv/Tidewater (2018)/Season 1/Tidewater S01E01.mkv", watched=True, s=1, e=1, at=T0 + 100, **tw)
    add(1, "episode", "Undertow", None, None, position=600, s=1, e=2, at=T0 + 200, duration=2400, **tw)
    add(1, "episode", "Shoals", None, None, watched=True, s=1, e=3, at=T0 + 110, **tw)
    add(1, "episode", "Breakers", None, None, watched=True, s=1, e=4, at=T0 + 120, **tw)
    add(1, "episode", "Christmas", None, None, watched=True, s=0, e=1, at=T0 + 130, **tw)
    add(1, "episode", "Flood", None, None, watched=True, s=2, e=5, at=T0 + 140, **tw)
    add(1, "episode", "Launch", None, None, watched=True, s=1, e=1, at=T0 + 150, **lo)
    add(1, "episode", "Burn", None, None, watched=True, s=1, e=2, at=T0 + 160, **lo)
    add(1, "movie", "Velvet Hour", None, "D:\\Adult\\Velvet Hour\\Velvet Hour.mkv", watched=True, at=T0 + 170)
    add(2, "movie", "Harbor Lights", 1994, "/data/movies/Harbor Lights (1994)/Harbor Lights (1994).mkv", position=300, at=T0 + 500)
    add(2, "movie", "Velvet Hour", None, "D:\\Adult\\Velvet Hour\\Velvet Hour.mkv", watched=True, at=T0 + 510)
    add(2, "movie", "Night Ferry", 2021, None, rating=6.0, at=T0 + 520)
    add(3, "movie", "Paper Moons", 2014, None, watched=True, at=T0 + 600)
    add(3, "movie", "Harbor Lights", 1994, "/data/movies/Harbor Lights (1994)/Harbor Lights (1994).mkv", watched=True, at=T0 + 610)
    add(3, "episode", "Pilot", None, "/data/tv/Tidewater (2018)/Season 1/Tidewater S01E01.mkv", watched=True, s=1, e=1, at=T0 + 620, **tw)
    add(4, "movie", "Night Ferry", 2021, None, watched=True, at=T0 + 700)
    return H


PLEX_USERS = {1: "hist-admin", 2: "Sam", 3: "Kiddo", 4: "Visitor"}
SHOW_RATINGS = [(1, "Low Orbit (US)", 2022, {"tvdb": "999001"}, 10.0)]


def make_plex_db(path, history_rows=None):
    """Plex's library database: the tables Sofa reads, with the columns Plex Media Server 1.43.5 made in our scratch run
    (where it sorts titles by ICU's rules, a stand-in rule here)."""
    db = sqlite3.connect(path)
    db.create_collation("icu_root", lambda a, b: (a > b) - (a < b))
    db.executescript("""
    CREATE TABLE accounts (id INTEGER PRIMARY KEY, name varchar(255), created_at dt_integer(8), updated_at dt_integer(8),
      default_audio_language varchar(255), default_subtitle_language varchar(255), auto_select_subtitle boolean,
      auto_select_audio boolean);
    CREATE TABLE library_sections (id INTEGER PRIMARY KEY, name varchar(255), section_type integer);
    CREATE TABLE metadata_items (id INTEGER PRIMARY KEY, library_section_id INTEGER, parent_id INTEGER,
      metadata_type INTEGER, guid varchar(255), media_item_count INTEGER, title varchar(255), title_sort varchar(255),
      original_title varchar(255), studio varchar(255), rating float, "index" INTEGER, duration INTEGER, year INTEGER,
      added_at dt_integer(8), created_at dt_integer(8), updated_at dt_integer(8), is_adult INTEGER);
    CREATE INDEX index_title_sort_icu ON metadata_items (title_sort COLLATE icu_root);
    CREATE TABLE media_items (id INTEGER PRIMARY KEY, library_section_id integer, metadata_item_id integer, duration integer);
    CREATE TABLE media_parts (id INTEGER PRIMARY KEY, media_item_id integer, directory_id integer, file varchar(255),
      duration integer);
    CREATE TABLE tags (id INTEGER PRIMARY KEY, metadata_item_id integer, tag varchar(255), tag_type integer);
    CREATE TABLE taggings (id INTEGER PRIMARY KEY, metadata_item_id integer, tag_id integer, "index" integer, text varchar(255));
    CREATE TABLE metadata_item_settings (id INTEGER PRIMARY KEY, account_id INTEGER, guid varchar(255), rating float,
      view_offset INTEGER, view_count INTEGER, last_viewed_at dt_integer(8), created_at dt_integer(8),
      updated_at dt_integer(8), skip_count INTEGER, last_skipped_at dt_integer(8), changed_at integer(8),
      extra_data varchar(255), last_rated_at dt_integer(8));
    """)
    for uid, name in PLEX_USERS.items():
        db.execute("INSERT INTO accounts (id, name) VALUES (?, ?)", (uid, name))
    db.execute("INSERT INTO accounts (id, name) VALUES (0, '')")          # (Plex keeps a nameless row 0)
    n = [0]
    movies, shows, seasons, guids = {}, {}, {}, {}

    def item(**kw):
        n[0] += 1
        kw.setdefault("guid", "plex://%s/%06x" % ({1: "movie", 2: "show", 3: "season", 4: "episode"}[kw["metadata_type"]], n[0]))
        cols = ", ".join('"%s"' % k for k in kw)
        db.execute("INSERT INTO metadata_items (id, %s) VALUES (?, %s)" % (cols, ", ".join("?" * len(kw))), (n[0],) + tuple(kw.values()))
        return n[0], kw["guid"]

    def tag_ids(mid, ids):
        for k, v in ids.items():
            cur = db.execute("INSERT INTO tags (tag, tag_type) VALUES (?, 314)", ("%s://%s" % (k, v),))
            db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (?, ?)", (mid, cur.lastrowid))

    def part(mid, path, duration):
        if path:
            cur = db.execute("INSERT INTO media_items (metadata_item_id, duration) VALUES (?, ?)", (mid, duration))
            db.execute("INSERT INTO media_parts (media_item_id, file, duration) VALUES (?, ?, ?)", (cur.lastrowid, path, duration))

    for h in (history_rows or _plex_history()):
        if h["kind"] == "movie":
            key = (h["title"], h["year"])
            if key not in movies:
                legacy = h["ids"].get("imdb") == "tt0090001"           # an item from Plex's older agents
                mid, guid = item(metadata_type=1, title=h["title"], year=h["year"], duration=h["duration"] * 1000,
                                 **({"guid": "com.plexapp.agents.imdb://tt0090001?lang=en"} if legacy else {}))
                if not legacy:
                    tag_ids(mid, h["ids"])
                part(mid, h["path"], h["duration"] * 1000)
                movies[key] = (mid, guid)
            mid, guid = movies[key]
        else:
            if h["show"] not in shows:
                sid, _ = item(metadata_type=2, title=h["show"], year=h["show_year"])
                tag_ids(sid, h["show_ids"])
                shows[h["show"]] = sid
            sid = shows[h["show"]]
            if (sid, h["s"]) not in seasons:
                seasons[(sid, h["s"])] = item(metadata_type=3, parent_id=sid, index=h["s"])[0]
            key = (h["show"], h["s"], h["e"])
            if key not in movies:
                old = h["e"] == 2 and h["show"] == "Low Orbit (US)"    # older agent: the show's TVDB id in the guid
                mid, guid = item(metadata_type=4, parent_id=seasons[(sid, h["s"])], title=h["title"], index=h["e"],
                                 duration=h["duration"] * 1000,
                                 **({"guid": "com.plexapp.agents.thetvdb://999001/1/2?lang=en"} if old else {}))
                part(mid, h["path"], h["duration"] * 1000)
                movies[key] = (mid, guid)
            mid, guid = movies[key]
        db.execute("INSERT INTO metadata_item_settings (account_id, guid, rating, view_offset, view_count, last_viewed_at, "
                   "updated_at, last_rated_at) VALUES (?,?,?,?,?,?,?,?)",
                   (h["user"], guid, h["rating"], int(h["position"] * 1000) if h["position"] else None,
                    1 if h["watched"] else 0, h["at"] if (h["watched"] or h["position"]) else None, h["at"],
                    h["at"] if h["rating"] is not None else None))
    for user, title, year, ids, rating in SHOW_RATINGS:
        sid = shows.get(title)
        guid = db.execute("SELECT guid FROM metadata_items WHERE id = ?", (sid,)).fetchone()[0]
        db.execute("INSERT INTO metadata_item_settings (account_id, guid, rating, view_count, updated_at, last_rated_at) "
                   "VALUES (?,?,?,0,?,?)", (user, guid, rating, T0 + 900, T0 + 900))
    db.commit()
    db.close()


def make_jellyfin_db(path):
    """Jellyfin 10.11 and later: jellyfin.db, with the tables and columns Jellyfin 12.4 made in our scratch run (every id
    as upper-case text with dashes).
    Each user's state is kept once per key an item is known by (its id, its TMDB id, its IMDb id)."""
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE Users (Id TEXT PRIMARY KEY, Username TEXT, InternalId INTEGER, MaxParentalRatingScore INTEGER,
      MaxParentalRatingSubScore INTEGER, NormalizedUsername TEXT);
    CREATE TABLE BaseItems (Id TEXT PRIMARY KEY, Type TEXT, Name TEXT, OriginalTitle TEXT, ProductionYear INTEGER,
      Path TEXT, IndexNumber INTEGER, ParentIndexNumber INTEGER, SeriesName TEXT, SeriesId TEXT, RunTimeTicks INTEGER,
      PremiereDate TEXT);
    CREATE TABLE BaseItemProviders (ItemId TEXT, ProviderId TEXT, ProviderValue TEXT, PRIMARY KEY (ItemId, ProviderId));
    CREATE TABLE UserData (ItemId TEXT, UserId TEXT, CustomDataKey TEXT, AudioStreamIndex INTEGER, IsFavorite INTEGER,
      LastPlayedDate TEXT, Likes INTEGER, PlayCount INTEGER, PlaybackPositionTicks INTEGER, Played INTEGER, Rating REAL,
      SubtitleStreamIndex INTEGER, RetentionDate TEXT, PRIMARY KEY (ItemId, UserId, CustomDataKey));
    """)
    for spec in JF_ITEMS:
        db.execute("INSERT INTO BaseItems (Id, Type, Name, OriginalTitle, ProductionYear, Path, IndexNumber, "
                   "ParentIndexNumber, SeriesName, SeriesId, RunTimeTicks) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (_dashed(spec["id"]).upper(), "MediaBrowser.Controller.Entities." + spec["type"], spec["name"], spec["name"],
                    spec.get("year"), spec.get("path"), spec.get("e"), spec.get("s"), spec.get("series_name"),
                    _dashed(spec["series"]).upper() if spec.get("series") else None, spec.get("ticks")))
        for k, v in spec.get("ids", {}).items():
            db.execute("INSERT INTO BaseItemProviders VALUES (?,?,?)", (_dashed(spec["id"]).upper(), k, v))
    for uid, name, limit in JF_USERS:
        db.execute("INSERT INTO Users (Id, Username, MaxParentalRatingScore) VALUES (?,?,?)", (_dashed(uid).upper(), name, limit))
    for uid, item_id, state in JF_STATE:
        for key in (_dashed(item_id), "tt-" + item_id[:6], item_id[-6:]):
            db.execute("INSERT INTO UserData (ItemId, UserId, CustomDataKey, IsFavorite, LastPlayedDate, Likes, PlayCount, "
                       "PlaybackPositionTicks, Played, Rating) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (_dashed(item_id).upper(), _dashed(uid).upper(), key, int(state.get("fav", False)),
                        state.get("last", "").replace("T", " ").replace("Z", "") or None, None,
                        int(state.get("played", False)), state.get("ticks", 0), int(state.get("played", False)), None))
    db.commit()
    db.close()


def make_jellyfin_old(folder):
    """Jellyfin 10.10 and before: TypedBaseItems and UserDatas in library.db, the users in jellyfin.db (as 10.10.7 made
    them in our scratch run: the item's id as 16 bytes in .NET's order, its SeriesId as text)."""
    lib = sqlite3.connect(os.path.join(folder, "library.db"))
    lib.executescript("""
    CREATE TABLE TypedBaseItems (guid GUID PRIMARY KEY NOT NULL, type TEXT NOT NULL, data BLOB NULL, ParentId GUID NULL,
      Path TEXT NULL, Name TEXT, OriginalTitle TEXT, ProductionYear INT, IndexNumber INT, ParentIndexNumber INT,
      SeriesName TEXT, SeriesId GUID, RunTimeTicks BIGINT, ProviderIds TEXT, PresentationUniqueKey TEXT, UserDataKey TEXT);
    CREATE TABLE UserDatas (key nvarchar not null, userId INT not null, rating float null, played bit not null,
      playCount int not null, isFavorite bit not null, playbackPositionTicks bigint not null, lastPlayedDate datetime null,
      AudioStreamIndex INT, SubtitleStreamIndex INT);
    """)
    import uuid
    for spec in JF_ITEMS:
        ids = "|".join("%s=%s" % kv for kv in spec.get("ids", {}).items()) or None
        lib.execute("INSERT INTO TypedBaseItems (guid, type, Path, Name, OriginalTitle, ProductionYear, IndexNumber, "
                    "ParentIndexNumber, SeriesName, SeriesId, RunTimeTicks, ProviderIds, PresentationUniqueKey, UserDataKey) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (uuid.UUID(spec["id"]).bytes_le, "MediaBrowser.Controller.Entities." + spec["type"], spec.get("path"),
                     spec["name"], spec["name"], spec.get("year"), spec.get("e"), spec.get("s"), spec.get("series_name"),
                     _dashed(spec["series"]).upper() if spec.get("series") else None, spec.get("ticks"), ids,
                     spec["id"], "ud" + spec["id"]))
    internal = {uid: n + 1 for n, (uid, _, _) in enumerate(JF_USERS)}
    for uid, item_id, state in JF_STATE:          # as 10.10.7 keeps them: its UserDataKey, an IMDb id, its dashed id
        for key in ("ud" + item_id, "tt" + item_id, _dashed(item_id)):
            lib.execute("INSERT INTO UserDatas (key, userId, rating, played, playCount, isFavorite, playbackPositionTicks, "
                        "lastPlayedDate) VALUES (?,?,?,?,?,?,?,?)",
                        (key, internal[uid], None, int(state.get("played", False)), int(state.get("played", False)),
                         int(state.get("fav", False)), state.get("ticks", 0),
                         state.get("last", "").replace("T", " ") or None))
    lib.commit()
    lib.close()
    users = sqlite3.connect(os.path.join(folder, "jellyfin.db"))
    users.execute("CREATE TABLE Users (Id TEXT PRIMARY KEY, Username TEXT, InternalId INTEGER, MaxParentalAgeRating INTEGER)")
    for uid, name, limit in JF_USERS:
        users.execute("INSERT INTO Users VALUES (?,?,?,?)", (_dashed(uid).upper(), name, internal[uid], limit))
    users.commit()
    users.close()


def _dashed(h):
    return "%s-%s-%s-%s-%s" % (h[:8], h[8:12], h[12:16], h[16:20], h[20:])


SERIES_LO = "5e000000000000000000000000000001"
SERIES_TW = "5e000000000000000000000000000002"
JF_ITEMS = [
    dict(id="a0000000000000000000000000000001", type="Movies.Movie", name="Harbor Lights", year=1994, ticks=60000000000,
         path="/data/movies/Harbor Lights (1994)/Harbor Lights (1994).mkv", ids={"Imdb": "tt0090009"}),
    dict(id="a0000000000000000000000000000002", type="Movies.Movie", name="Paper Moons", year=2014, ticks=50000000000,
         path="/mnt/kids/Paper Moons.mkv", ids={"Tmdb": "777"}),
    dict(id="a0000000000000000000000000000003", type="Movies.Movie", name="Last Signal", year=2020, ticks=50000000000,
         path="/data/movies/Last Signal (2020)/Last Signal (2020).mkv"),
    dict(id=SERIES_LO, type="TV.Series", name="Low Orbit (US)", year=2022, ids={"Tvdb": "999001", "Imdb": "tt0099901"}),
    dict(id=SERIES_TW, type="TV.Series", name="Tidewater", year=2018),
    dict(id="e0000000000000000000000000000001", type="TV.Episode", name="Launch", series=SERIES_LO, series_name="Low Orbit (US)",
         s=1, e=1, ticks=24000000000, path="/srv/tv/Low Orbit/S01/01.mkv"),
    dict(id="e0000000000000000000000000000002", type="TV.Episode", name="Undertow", series=SERIES_TW, series_name="Tidewater",
         s=1, e=2, ticks=24000000000, path="/data/tv/Tidewater (2018)/Season 1/Tidewater S01E02.mkv"),
]
JF_USERS = [("c0000000000000000000000000000001", "hist-admin", None), ("c0000000000000000000000000000002", "Kiddo", 10)]
JF_STATE = [
    ("c0000000000000000000000000000001", "a0000000000000000000000000000001", dict(played=True, last="2023-11-20T10:00:00.1234567Z")),
    ("c0000000000000000000000000000001", "e0000000000000000000000000000001", dict(ticks=9000000000, last="2023-11-21T10:00:00.0000000Z")),
    ("c0000000000000000000000000000001", "e0000000000000000000000000000002", dict(ticks=3000000000)),     # no date
    ("c0000000000000000000000000000001", SERIES_LO, dict(fav=True)),
    ("c0000000000000000000000000000001", "a0000000000000000000000000000003", dict(played=True, last="2023-11-22T10:00:00Z")),
    ("c0000000000000000000000000000002", "a0000000000000000000000000000002", dict(played=True, fav=True, last="2023-11-23T10:00:00Z")),
]


# ---------------------------------------------------------------- stand-in servers

class StandIn(http.server.ThreadingHTTPServer):
    daemon_threads = True


def serve(handler):
    srv = StandIn(("127.0.0.1", 0), handler)
    srv.asked = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


class Answer(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class PlexAnswers(Answer):
    """Plex Media Server's own API, as JSON (Accept: application/json), for the owner's token."""
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        self.server.asked.append((url.path, dict(self.headers), q))
        if self.headers.get("X-Plex-Token") != TOKEN or "X-Plex-Token" in q:
            return self.send(401, {"error": "Unauthorized"})
        start, size = int(q.get("X-Plex-Container-Start", 0)), int(q.get("X-Plex-Container-Size", 50))

        def page(rows):
            return {"MediaContainer": {"size": len(rows[start:start + size]), "totalSize": len(rows),
                                       "Metadata": rows[start:start + size]}}
        H = [h for h in _plex_history()]
        mine = [h for h in H if h["user"] == 1]
        if url.path == "/":
            return self.send(200, {"MediaContainer": {"machineIdentifier": "abc", "myPlexUsername": "hist-admin"}})
        if url.path == "/accounts":
            return self.send(200, {"MediaContainer": {"Account": [{"id": 0, "name": ""}] +
                                                      [{"id": k, "name": v} for k, v in PLEX_USERS.items()]}})
        if url.path == "/library/sections":
            return self.send(200, {"MediaContainer": {"Directory": [{"key": "1", "type": "movie"}, {"key": "2", "type": "show"},
                                                                    {"key": "3", "type": "artist"}]}})
        keys = {}
        for h in H:
            keys.setdefault((h["kind"], h["title"], h["year"], h["show"], h["s"], h["e"]), str(len(keys) + 100))

        def meta(h, state):
            m = {"ratingKey": keys[(h["kind"], h["title"], h["year"], h["show"], h["s"], h["e"])], "title": h["title"],
                 "year": h["year"], "duration": h["duration"] * 1000,
                 "Guid": [{"id": "%s://%s" % kv} for kv in h["ids"].items()],
                 "Media": [{"Part": [{"file": h["path"]}]}] if h["path"] else []}
            if h["kind"] == "episode":
                m.update(grandparentTitle=h["show"], grandparentRatingKey="show-" + h["show"], parentIndex=h["s"], index=h["e"])
            if state:
                if h["watched"]:
                    m.update(viewCount=1, lastViewedAt=h["at"])
                if h["position"]:
                    m.update(viewOffset=int(h["position"] * 1000), lastViewedAt=h["at"])
                if h["rating"] is not None:
                    m.update(userRating=h["rating"], lastRatedAt=h["at"])
            return m
        if url.path == "/library/sections/1/all" and q.get("type") == "1":
            seen, rows = set(), []
            for h in H:
                if h["kind"] == "movie" and (h["title"], h["year"]) not in seen:
                    seen.add((h["title"], h["year"]))
                    own = next((x for x in mine if x["kind"] == "movie" and (x["title"], x["year"]) == (h["title"], h["year"])), None)
                    rows.append(meta(own or h, own is not None))
            return self.send(200, page(rows))
        if url.path == "/library/sections/2/all" and q.get("type") == "2":
            shows = {}
            for h in H:
                if h["kind"] == "episode":
                    shows.setdefault(h["show"], {"ratingKey": "show-" + h["show"], "title": h["show"], "year": h["show_year"],
                                                 "Guid": [{"id": "%s://%s" % kv} for kv in h["show_ids"].items()]})
            for user, title, year, ids, rating in SHOW_RATINGS:
                shows[title]["userRating"] = rating
            return self.send(200, page(list(shows.values())))
        if url.path == "/library/sections/2/all" and q.get("type") == "4":
            seen, rows = set(), []
            for h in H:
                k = (h["show"], h["s"], h["e"])
                if h["kind"] == "episode" and k not in seen:
                    seen.add(k)
                    own = next((x for x in mine if x["kind"] == "episode" and (x["show"], x["s"], x["e"]) == k), None)
                    rows.append(meta(own or h, own is not None))
            return self.send(200, page(rows))
        if url.path == "/status/sessions/history/all":
            rows = [{"ratingKey": keys[(h["kind"], h["title"], h["year"], h["show"], h["s"], h["e"])], "accountID": h["user"],
                     "viewedAt": h["at"], "type": h["kind"], "title": h["title"]} for h in H if h["watched"]]
            rows.append({"ratingKey": "gone-1", "accountID": 2, "viewedAt": T0, "type": "movie", "title": "Deleted Film", "year": 1990})
            return self.send(200, page(rows))
        return self.send(404, {})


class JellyfinAnswers(Answer):
    """Jellyfin's API as 12.4 answered it in our scratch run (Emby answers the same paths)."""
    product = "Jellyfin Server"

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        self.server.asked.append((url.path, dict(self.headers), q))
        auth_header = self.headers.get("Authorization") or ""
        if 'Token="%s"' % KEY not in auth_header or "api_key" in q:
            return self.send(401, {})
        if url.path == "/System/Info":
            return self.send(200, {"ServerName": "den", "Version": "12.4.0", "ProductName": self.product})
        if url.path == "/Users":
            return self.send(200, [{"Name": n, "Id": i, "Policy": {"IsAdministrator": l is None, "MaxParentalRating": l}}
                                   for i, n, l in JF_USERS] + [{"Name": "old", "Id": "c9", "Policy": {"IsDisabled": True}}])
        m = __import__("re").match(r"^/Users/([0-9a-f]+)/Items$", url.path)
        if not m:
            return self.send(404, {})
        uid = m.group(1)
        state = {i: s for u, i, s in JF_STATE if u == uid}

        def dto(spec):
            s = state.get(spec["id"], {})
            d = {"Id": spec["id"], "Name": spec["name"], "Type": spec["type"].split(".")[-1], "ProductionYear": spec.get("year"),
                 "Path": spec.get("path"), "ProviderIds": spec.get("ids", {}), "RunTimeTicks": spec.get("ticks"),
                 "UserData": {"PlaybackPositionTicks": s.get("ticks", 0), "PlayCount": int(s.get("played", False)),
                              "IsFavorite": s.get("fav", False), "Played": s.get("played", False)}}
            if s.get("last"):
                d["UserData"]["LastPlayedDate"] = s["last"]
            if spec.get("series"):
                d.update(SeriesId=spec["series"], SeriesName=spec["series_name"], ParentIndexNumber=spec["s"], IndexNumber=spec["e"])
            return d
        if q.get("Ids"):
            rows = [dto(s) for s in JF_ITEMS if s["id"] in q["Ids"].split(",")]
        else:
            want = {"IsPlayed": lambda s: s.get("played"), "IsResumable": lambda s: s.get("ticks"),
                    "IsFavorite": lambda s: s.get("fav")}[q["Filters"]]
            rows = [dto(s) for s in JF_ITEMS if s["id"] in state and want(state[s["id"]])
                    and s["type"].split(".")[-1] in q["IncludeItemTypes"].split(",")]
        start, limit = int(q.get("StartIndex", 0)), int(q.get("Limit", 100))
        return self.send(200, {"Items": rows[start:start + limit], "TotalRecordCount": len(rows), "StartIndex": start})


# ---------------------------------------------------------------- the tests

def _ids_of(names):
    return {store.q1("SELECT id FROM users WHERE name = ?", n)["id"] for n in names}


class History(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.made = []
        for rel in SOFA:
            cls.made.append(video(os.path.join(LIBRARY, rel)))
        with open(os.path.join(MOVIES, "Lantern Field (2003)", "Lantern Field (2003).nfo"), "w") as f:
            f.write('<?xml version="1.0"?><movie><title>Lantern Field</title><uniqueid type="imdb">tt0090002</uniqueid></movie>')
        with open(os.path.join(SHOWS, "Low Orbit (2022)", "tvshow.nfo"), "w") as f:
            f.write('<tvshow><title>Low Orbit</title><uniqueid type="tvdb" default="true">999001</uniqueid></tvshow>')
        os.makedirs(metadata.CACHE, exist_ok=True)
        cls.cached = os.path.join(metadata.CACHE, "movie2-f-copper-sky-2016.json")
        with open(cls.cached, "w") as f:                 # what a lookup saved: TMDB's movie 424242
            json.dump({"source": "TMDB", "source_id": 424242, "canonical": "Copper Sky", "year": 2016}, f)
        LIB.scan("tests")
        for name, admin in (("hist-admin", True), ("hist-sam", False), ("hist-kid", False)):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123", admin=admin)
        cls.admin_id, cls.sam_id, cls.kid_id = (store.q1("SELECT id FROM users WHERE name = ?", n)["id"]
                                                for n in ("hist-admin", "hist-sam", "hist-kid"))
        auth.set_adult(cls.admin_id, True)
        auth.set_kids(cls.kid_id, True)
        kids.choose("m:paper-moons:2014", True)
        kids.choose("s:tidewater", True)
        kids.choose("m:harbor-lights:1994", False)
        cls.folder = tempfile.mkdtemp(prefix="sofa-history-", dir=ROOT)
        cls.plex_db = os.path.join(cls.folder, "com.plexapp.plugins.library.db")
        make_plex_db(cls.plex_db)
        cls.jf_new = os.path.join(cls.folder, "jf-new")
        cls.jf_old = os.path.join(cls.folder, "jf-old")
        os.makedirs(cls.jf_new)
        os.makedirs(cls.jf_old)
        make_jellyfin_db(os.path.join(cls.jf_new, "jellyfin.db"))
        make_jellyfin_old(cls.jf_old)

    @classmethod
    def tearDownClass(cls):
        for p in cls.made:
            os.remove(p)
        for rel in ("Movies/Lantern Field (2003)/Lantern Field (2003).nfo", "Shows/Low Orbit (2022)/tvshow.nfo"):
            os.remove(os.path.join(LIBRARY, rel))
        for rel in {os.path.join(*r.split("/")[:3]) for r in SOFA}:      # each title's folder
            shutil.rmtree(os.path.join(LIBRARY, rel), ignore_errors=True)
        os.remove(cls.cached)
        for item in ("m:paper-moons:2014", "s:tidewater", "m:harbor-lights:1994"):
            kids.choose(item, None)
        for uid in (cls.admin_id, cls.sam_id, cls.kid_id):
            auth.delete_user(uid)
        shutil.rmtree(cls.folder, ignore_errors=True)
        LIB.scan("tests")

    def setUp(self):
        for uid in (self.admin_id, self.sam_id, self.kid_id):
            store.ex("DELETE FROM progress WHERE user_id = ?", uid)
            store.ex("DELETE FROM likes WHERE user_id = ?", uid)
        history.forget()

    def plex_people(self, data):
        by_name = {u["name"]: u["key"] for u in data["users"]}
        return {by_name["hist-admin"]: self.admin_id, by_name["Sam"]: self.sam_id, by_name["Kiddo"]: self.kid_id}

    def tables(self):
        uids = (self.admin_id, self.sam_id, self.kid_id)
        return (sorted(tuple(r) for r in store.q("SELECT user_id, item, t, d, done, at FROM progress WHERE user_id IN (?,?,?)", *uids)),
                sorted(tuple(r) for r in store.q("SELECT user_id, item, at FROM likes WHERE user_id IN (?,?,?)", *uids)))

    # ------------------------------------------------------------ the readers

    def test_plex_database_is_read_whole(self):
        data = history.read_plex_db(self.plex_db)
        self.assertEqual((data["source"], data["how"]), ("Plex", "database"))
        self.assertEqual([u["name"] for u in data["users"]], ["hist-admin", "Sam", "Kiddo", "Visitor"])   # (not row 0)
        recs = {(r["user"], r["title"], r["s"], r["e"]): r for r in data["records"]}
        heat = recs[("1", "Harbor Lights", None, None)]
        self.assertEqual((heat["watched"], heat["paths"], heat["at"]), (True, ["/data/movies/Harbor Lights (1994)/Harbor Lights (1994).mkv"], T0))
        copper = recs[("1", "Copper Sky: First Light", None, None)]
        self.assertEqual((copper["position"], copper["duration"], copper["ids"]), (1200.0, 6000.0, {"tmdb": "424242"}))
        self.assertEqual(recs[("1", "Engine Room", None, None)]["ids"], {"imdb": "tt0090001"})          # Plex's older agent
        self.assertTrue(recs[("1", "Lanterns", None, None)]["liked"])                                   # rated 8 of 10
        self.assertFalse(recs[("2", "Night Ferry", None, None)]["liked"])                                # rated 6
        burn = recs[("1", "Burn", 1, 2)]
        self.assertEqual((burn["show"], burn["show_ids"]), ("Low Orbit (US)", {"tvdb": "999001"}))       # from the guid
        show = [r for r in data["records"] if r["kind"] == "show"]
        self.assertEqual([(s["title"], s["liked"], s["ids"]) for s in show], [("Low Orbit (US)", True, {"tvdb": "999001"})])
        self.assertEqual(len(data["records"]), len(_plex_history()) + 1)

    def test_plex_database_is_never_written(self):
        before = os.path.getmtime(self.plex_db), os.path.getsize(self.plex_db)
        with open(self.plex_db, "rb") as f:
            raw = f.read()
        history.read_plex_db(self.plex_db)
        with open(self.plex_db, "rb") as f:
            self.assertEqual(f.read(), raw)
        self.assertEqual((os.path.getmtime(self.plex_db), os.path.getsize(self.plex_db)), before)
        leftovers = [n for n in os.listdir(tempfile.gettempdir()) if n.startswith("sofa-import-")]
        self.assertEqual(leftovers, [])                                     # the private copy is gone
        with self.assertRaises(history.Problem):
            history.read_plex_db(os.path.join(self.jf_new, "jellyfin.db"))   # not Plex's
        with self.assertRaises(history.Problem):
            history.read_plex_db(os.path.join(self.folder, "nothing.db"))

    def test_plex_by_its_address(self):
        srv, base = serve(PlexAnswers)
        try:
            data = history.read_plex_api(base, TOKEN)
            for path, headers, q in srv.asked:
                self.assertNotIn(TOKEN, path + json.dumps(q))                # in a header, never the address
            with self.assertRaises(history.Problem) as no:
                history.read_plex_api(base, "wrong")
            self.assertIn("turned the token or key down", str(no.exception))
        finally:
            srv.shutdown()
        self.assertEqual(data["how"], "address")
        recs = {(r["user"], r["title"], r["s"], r["e"]): r for r in data["records"]}
        self.assertEqual(recs[("1", "Copper Sky: First Light", None, None)]["position"], 1200.0)     # the owner: places too
        self.assertTrue(recs[("1", "Lanterns", None, None)]["liked"])
        self.assertEqual(recs[("1", "Burn", 1, 2)]["show_ids"], {"tvdb": "999001"})
        sam = {k: r for k, r in recs.items() if k[0] == "2"}
        self.assertEqual(sorted(k[1] for k in sam), ["Deleted Film", "Velvet Hour"])                  # watched to the end only
        self.assertEqual(recs[("2", "Velvet Hour", None, None)]["paths"], ["D:\\Adult\\Velvet Hour\\Velvet Hour.mkv"])
        self.assertIn("only the token's own account", data["notes"][0])
        self.assertEqual([r["title"] for r in data["records"] if r["kind"] == "show"], ["Low Orbit (US)"])

    def test_jellyfin_by_its_address(self):
        srv, base = serve(JellyfinAnswers)
        try:
            data = history.read_jellyfin_api(base, KEY)
            for path, headers, q in srv.asked:
                self.assertNotIn(KEY, path + json.dumps(q))
            JellyfinAnswers.product = "Emby Server"
            self.assertEqual(history.read_jellyfin_api(base, KEY)["source"], "Emby")
        finally:
            JellyfinAnswers.product = "Jellyfin Server"
            srv.shutdown()
        self.assertEqual(data["source"], "Jellyfin")
        self.assertEqual([(u["name"], u["kids"]) for u in data["users"]], [("hist-admin", False), ("Kiddo", True)])
        recs = {(r["user"], r["title"]): r for r in data["records"]}
        launch = recs[(JF_USERS[0][0], "Launch")]
        self.assertEqual((launch["position"], launch["duration"], launch["show_ids"]["tvdb"], launch["s"], launch["e"]),
                         (900.0, 2400.0, "999001", 1, 1))                   # ticks: 10,000,000 a second
        self.assertEqual(launch["at"], history._when("2023-11-21T10:00:00Z"))
        self.assertTrue(recs[(JF_USERS[0][0], "Low Orbit (US)")]["liked"])
        self.assertIsNone(recs[(JF_USERS[0][0], "Undertow")]["at"])

    def test_jellyfin_database_new_and_old(self):
        new = history.read_jellyfin_db(self.jf_new)
        old = history.read_jellyfin_db(os.path.join(self.jf_old, "library.db"))
        for data in (new, old):
            self.assertEqual([(u["name"], u["kids"]) for u in data["users"]], [("hist-admin", False), ("Kiddo", True)])
            got = sorted((r["title"], r["watched"], r["position"], r["liked"], r["at"]) for r in data["records"])
            self.assertEqual(got, sorted([
                ("Harbor Lights", True, 0.0, False, history._when("2023-11-20T10:00:00Z")),
                ("Launch", False, 900.0, False, history._when("2023-11-21T10:00:00Z")),
                ("Undertow", False, 300.0, False, None),
                ("Low Orbit (US)", False, 0.0, True, None),
                ("Last Signal", True, 0.0, False, history._when("2023-11-22T10:00:00Z")),
                ("Paper Moons", True, 0.0, True, history._when("2023-11-23T10:00:00Z"))]), data["how"])
            launch = next(r for r in data["records"] if r["title"] == "Launch")
            self.assertEqual((launch["show"], launch["show_ids"]), ("Low Orbit (US)", {"tvdb": "999001", "imdb": "tt0099901"}))
        with self.assertRaises(history.Problem):
            history.read_jellyfin_db(self.folder)                           # no jellyfin.db or library.db there

    def test_when(self):
        self.assertEqual(history._when("2023-11-14T22:13:20Z"), T0)
        self.assertEqual(history._when("2023-11-14 22:13:20.8123168"), T0)
        self.assertEqual(history._when("2023-11-14T23:13:20+01:00"), T0)
        self.assertEqual(history._when(T0), T0)
        self.assertEqual(history._when(T0 * 1000), T0)
        self.assertIsNone(history._when("soon"))
        self.assertIsNone(history._when(None))

    # ------------------------------------------------------------ matching

    def test_matching_on_the_untidy_library(self):
        data = history.read_plex_db(self.plex_db)
        p = history.plan(data, self.plex_people(data), MAP)
        got = {(r["user"], r["label"]): (r["id"], r["match"], r["outcome"]) for r in p["rows"]}
        self.assertEqual(got[("1", "Harbor Lights (1994)")], ("m:harbor-lights:1994", "path", "new"))       # .mkv → .mp4
        self.assertEqual(got[("1", "Copper Sky: First Light (2016)")], ("m:copper-sky:2016", "ids", "new"))  # saved TMDB id
        self.assertEqual(got[("1", "Engine Room (1999)")], ("m:quiet-engine:1999", "ids", "new"))         # {imdb-…} in the name
        self.assertEqual(got[("1", "Lanterns (2003)")], ("m:lantern-field:2003", "ids", "matched"))       # .nfo; a like only
        self.assertEqual(got[("1", "Night Ferry (2021)")], ("m:night-ferry:2021", "title", "new"))         # not the 1984 one
        self.assertEqual(got[("1", "Glass Orchard")], (None, None, "ambiguous"))
        self.assertEqual(got[("1", "Last Signal (2020)")], (None, None, "unmatched"))
        self.assertEqual(got[("1", "Tidewater S01E01")], ("e:tidewater:1:1", "path", "new"))
        self.assertEqual(got[("1", "Tidewater S01E02")], ("e:tidewater:1:2", "title", "new"))
        self.assertEqual({got[("1", "Tidewater S01E03")][:2], got[("1", "Tidewater S01E04")][:2]},
                         {("e:tidewater:1:3", "title")})                    # two episodes, one file: kept once
        self.assertEqual(sorted([got[("1", "Tidewater S01E03")][2], got[("1", "Tidewater S01E04")][2]]), ["merged", "new"])
        self.assertEqual(got[("1", "Tidewater S00E01")], ("e:tidewater:0:1", "title", "new"))
        self.assertEqual(got[("1", "Tidewater S02E05")], (None, None, "unmatched"))
        self.assertEqual(got[("1", "Low Orbit (US) S01E01")], ("e:low-orbit:1:1", "ids", "new"))           # tvshow.nfo's TVDB id
        self.assertEqual(got[("1", "Low Orbit (US) S01E02")], ("e:low-orbit:1:2", "ids", "new"))
        velvet = next(r for r in p["rows"] if r["user"] == "1" and r["label"] == "Velvet Hour")
        self.assertEqual((velvet["match"], velvet["outcome"], velvet["adult"]), ("path", "new", True))     # D:\ → Adult/Movies
        self.assertEqual(got[("2", "Velvet Hour")][2], "skip-adult")
        self.assertEqual(got[("3", "Harbor Lights (1994)")][2], "skip-kids")
        self.assertEqual(got[("3", "Paper Moons (2014)")][2], "new")
        self.assertEqual(got[("3", "Tidewater S01E01")][2], "new")
        self.assertEqual(got[("4", "Night Ferry (2021)")][2], "no-profile")
        # The rates: 24 titles with history (23 watched or started, a show's rating); 21 found: 7 by path, 6 by id,
        # 8 by title. The 3 not found: two films of that name in Sofa and no year to choose, and two that aren't here.
        s = history.summary(p, adult_ok=True)
        self.assertEqual((s["titles"], s["found"], s["by"]), (24, 21, {"path": 7, "ids": 6, "title": 8}))
        self.assertEqual(s["likes"], 2)                                    # Lanterns, and Low Orbit (the show)
        self.assertEqual(sorted((lk["user"], lk["item"]) for lk in p["likes"]),
                         [(self.admin_id, "m:lantern-field:2003"), (self.admin_id, "s:low-orbit")])

    def test_no_map_still_finds_the_same_folder_and_file(self):
        data = history.read_plex_db(self.plex_db)
        p = history.plan(data, self.plex_people(data), "")
        got = {(r["user"], r["label"]): r for r in p["rows"]}
        self.assertEqual((got[("1", "Harbor Lights (1994)")]["match"], got[("1", "Tidewater S01E01")]["match"]), ("path", "path"))
        velvet = got[("1", "Velvet Hour")]                                   # a Windows path: the same folder and file
        self.assertEqual((velvet["match"], velvet["id"].startswith("am:")), ("path", True))
        self.assertEqual(got[("1", "Last Signal (2020)")]["outcome"], "unmatched")

    def test_paths_compare_whatever_the_spelling(self):
        self.assertEqual(history._key("/A/Caf\u00e9/Film.MKV"), history._key("/a/Cafe\u0301/film.mp4"))
        self.assertEqual(history.map_path("D:\\Media\\Films\\X.mkv", history.parse_map("d:\\media => /Volumes/M")),
                         "/Volumes/M/Films/X.mkv")
        self.assertEqual(history.map_path("/data/moviesextra/X.mkv", history.parse_map("/data/movies => /m")),
                         "/data/moviesextra/X.mkv")                          # a whole folder name, not a prefix of one
        self.assertEqual(history.parse_map("/a => /b\n# a note\n/a/b -> /c")[0], ("/a/b", "/c"))   # the longest first
        with self.assertRaises(history.Problem):
            history.parse_map("just one folder")

    def test_ids_in_names_and_nfo(self):
        self.assertEqual(history.ids_in_name("Heat (1995) {imdb-tt0113277}"), {"imdb": "tt0113277"})
        self.assertEqual(history.ids_in_name("Heat (1995) [tmdbid-949] [imdbid=tt0113277]"), {"tmdb": "949", "imdb": "tt0113277"})
        self.assertEqual(history.ids_in_name("Show [tvdbid-81189]"), {"tvdb": "81189"})
        self.assertEqual(history.ids_in_name("Movie 2019 1080p"), {})
        bad = os.path.join(self.folder, "bad.nfo")
        with open(bad, "w") as f:
            f.write('<!DOCTYPE x [<!ENTITY e "tt0000001">]><movie><imdbid>&e;</imdbid></movie>')
        self.assertEqual(history.ids_in_nfo(bad), {})                        # no entity tricks

    # ------------------------------------------------------------ writing

    def test_import_writes_once_and_never_over_newer(self):
        store.ex("INSERT INTO progress (user_id, item, t, d, done, at) VALUES (?,?,?,?,?,?)",     # Sam went on in Sofa
                 self.sam_id, "m:harbor-lights:1994", 2000, 6000, 0, (T0 + 9000) * 1000)
        data = history.read_plex_db(self.plex_db)
        people = self.plex_people(data)
        p = history.plan(data, people, MAP)
        sam = {r["label"]: r["outcome"] for r in p["rows"] if r["user"] == "2"}
        self.assertEqual(sam["Harbor Lights (1994)"], "sofa-newer")
        done = history.apply(p)
        self.assertEqual(done, {"progress": len(p["writes"]), "likes": 2, "profiles": 2})
        rows = {(r["user_id"], r["item"]): dict(r) for r in store.q("SELECT * FROM progress WHERE user_id IN (?,?,?)",
                                                                    self.admin_id, self.sam_id, self.kid_id)}
        self.assertEqual(rows[(self.sam_id, "m:harbor-lights:1994")]["t"], 2000)                       # Sofa's kept
        h = rows[(self.admin_id, "m:harbor-lights:1994")]
        self.assertEqual((h["done"], h["at"]), (1, T0 * 1000))                                        # Plex's own date
        c = rows[(self.admin_id, "m:copper-sky:2016")]
        self.assertEqual((c["t"], c["d"], c["done"]), (1200, 6000, 0))
        self.assertEqual(rows[(self.admin_id, "e:tidewater:1:3")]["at"], (T0 + 120) * 1000)        # the newer of E03 and E04
        self.assertNotIn((self.kid_id, "m:harbor-lights:1994"), rows)                                # not for a Kids profile
        self.assertIn((self.kid_id, "m:paper-moons:2014"), rows)
        self.assertNotIn((self.sam_id, "am:" + "x"), rows)
        self.assertFalse(any(k[1].startswith("am:") for k in rows if k[0] != self.admin_id))
        # A Kids profile is still a Kids profile, an Adult switch still where it was.
        flags = {r["id"]: (r["kids"], r["adult"]) for r in store.q("SELECT id, kids, adult FROM users")}
        self.assertEqual((flags[self.kid_id], flags[self.sam_id], flags[self.admin_id]), ((1, 0), (0, 0), (0, 1)))
        # Again: nothing changes, and the dry run says so.
        before = self.tables()
        again = history.plan(data, people, MAP)
        self.assertEqual((again["writes"], again["likes"]), ([], []))
        self.assertEqual(history.summary(again)["users"][0]["new"], 0)
        self.assertEqual(history.apply(again), {"progress": 0, "likes": 0, "profiles": 0})
        self.assertEqual(self.tables(), before)
        act = store.q1("SELECT message FROM activity WHERE kind = 'history' ORDER BY id DESC LIMIT 1")["message"]
        self.assertNotIn("Velvet", act)                                     # counts only: no titles in Activity
        self.assertNotIn("Harbor", act)

    def test_a_newer_place_written_meanwhile_wins(self):
        data = history.read_plex_db(self.plex_db)
        p = history.plan(data, self.plex_people(data), MAP)
        store.ex("INSERT INTO progress (user_id, item, t, d, done, at) VALUES (?,?,?,?,?,?)",          # played just now
                 self.admin_id, "m:copper-sky:2016", 4000, 6000, 0, int(time.time() * 1000))
        history.apply(p)
        self.assertEqual(store.q1("SELECT t FROM progress WHERE user_id = ? AND item = ?", self.admin_id,
                                  "m:copper-sky:2016")["t"], 4000)

    def test_no_date_only_where_sofa_has_nothing(self):
        data = history.read_jellyfin_db(self.jf_new)
        people = {u["key"]: {"hist-admin": self.admin_id, "Kiddo": self.kid_id}[u["name"]] for u in data["users"]}
        store.ex("INSERT INTO progress (user_id, item, t, d, done, at) VALUES (?,?,?,?,?,?)",
                 self.admin_id, "e:tidewater:1:2", 100, 2400, 0, 5)
        p = history.plan(data, people, MAP)
        und = next(r for r in p["rows"] if r["label"] == "Tidewater S01E02")
        self.assertEqual((und["match"], und["outcome"]), ("path", "sofa-newer"))     # (no date: Sofa's is kept)
        store.ex("DELETE FROM progress WHERE user_id = ?", self.admin_id)
        p = history.plan(data, people, MAP)
        history.apply(p)
        r = store.q1("SELECT t, at FROM progress WHERE user_id = ? AND item = ?", self.admin_id, "e:tidewater:1:2")
        self.assertEqual((r["t"], r["at"]), (300, 0))                      # written, dated "before anything"
        self.assertEqual(store.q1("SELECT item FROM likes WHERE user_id = ?", self.kid_id)["item"], "m:paper-moons:2014")
        self.assertEqual(store.q1("SELECT item FROM likes WHERE user_id = ?", self.admin_id)["item"], "s:low-orbit")

    def test_bad_numbers_are_never_written(self):
        p = {"source": "Plex", "writes": [{"user": self.admin_id, "item": "m:night-ferry:2021", "t": float("nan"), "d": 10,
                                           "done": 0, "at": T0 * 1000},
                                          {"user": self.admin_id, "item": "m:night-ferry:1984", "t": -3, "d": 10, "done": 0,
                                           "at": T0 * 1000}], "likes": []}
        self.assertEqual(history.apply(p)["progress"], 0)
        rec = history.record("1", "movie", title="X", position=float("inf"), duration=float("nan"), watched=True)
        self.assertEqual(history._state(rec), (0.0, 0.0, 1, None))
        self.assertEqual(json.loads(json.dumps(self.tables())), json.loads(json.dumps(self.tables())))

    # ------------------------------------------------------------ the Server page and the command line

    def test_the_server_page(self):
        httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        plex, plex_base = serve(PlexAnswers)
        try:
            admin, sam = Client(base), Client(base)
            self.assertEqual(admin.call("/api/login", {"name": "hist-admin", "password": "password123"})[0], 200)
            self.assertEqual(sam.call("/api/login", {"name": "hist-sam", "password": "password123"})[0], 200)
            self.assertEqual(sam.call("/api/admin/history")[0], 403)
            self.assertEqual(sam.call("/api/admin/history", {"read": {"source": "plex-db", "path": self.plex_db}})[0], 403)
            status, s = admin.call("/api/admin/history", {"read": {"source": "plex", "url": plex_base, "secret": TOKEN, "map": MAP}})
            self.assertEqual(status, 200)
            for _ in range(100):
                s = admin.call("/api/admin/history")[1]
                if s["state"] != "reading":
                    break
                time.sleep(0.05)
            self.assertEqual(s["state"], "ready", s.get("message"))
            users = {u["name"]: u for u in s["report"]["users"]}
            self.assertEqual(users["hist-admin"]["profile"], self.admin_id)            # the same name: suggested
            self.assertIsNone(users["Sam"]["profile"])
            people = {users["Sam"]["key"]: self.sam_id, users["hist-admin"]["key"]: self.admin_id,
                      users["Kiddo"]["key"]: self.kid_id}
            status, s = admin.call("/api/admin/history", {"people": people})
            self.assertEqual({u["name"]: u["profile"] for u in s["report"]["users"]}["Sam"], self.sam_id)
            status, s = admin.call("/api/admin/history", {"import": True, "people": people})
            self.assertEqual((status, s["state"]), (200, "done"))
            self.assertGreater(s["result"]["progress"], 10)
            self.assertNotIn("report", s)                                              # what was read is forgotten
            self.assertEqual(admin.call("/api/admin/history", {"people": people})[0], 400)
            # The token was used and is nowhere: not in the settings, the activity, the database or the log.
            with open(config.CONFIG_PATH, encoding="utf-8") as f:
                self.assertNotIn(TOKEN, f.read())
            for table in ("activity", "progress", "likes"):
                self.assertNotIn(TOKEN, json.dumps([dict(r) for r in store.q("SELECT * FROM %s" % table)]))
            self.assertNotIn(TOKEN, json.dumps(history._job))
            # A wrong map line, a wrong source: said at once.
            self.assertEqual(admin.call("/api/admin/history", {"read": {"source": "plex-db", "path": self.plex_db,
                                                                        "map": "only-one"}})[0], 400)
            admin.call("/api/admin/history", {"read": {"source": "plex-db", "path": "/no/such.db"}})
            for _ in range(100):
                s = admin.call("/api/admin/history")[1]
                if s["state"] != "reading":
                    break
                time.sleep(0.05)
            self.assertEqual(s["state"], "failed")
            self.assertIn("no file", s["message"])
        finally:
            plex.shutdown()
            httpd.shutdown()

    def test_adult_titles_are_named_only_to_those_who_see_them(self):
        data = history.read_plex_db(self.plex_db)
        p = history.plan(data, self.plex_people(data), MAP)
        hidden = json.dumps(history.summary(p, adult_ok=False))
        self.assertNotIn("Velvet", hidden)
        self.assertIn("An Adult title", hidden)
        self.assertIn("Velvet", json.dumps(history.summary(p, adult_ok=True)))

    def test_the_command_line(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = history_cli.main(["plex-db", self.plex_db, "--map", "/data/movies=>%s" % MOVIES, "--map", "/data/tv=>%s" % SHOWS,
                                     "--user", "Sam=>hist-sam", "--user", "Kiddo=>hist-kid", "--list"])
        text = out.getvalue()
        self.assertEqual(code, 0, text)
        self.assertIn("Nothing was written", text)
        self.assertIn("not in Sofa: Last Signal (2020)", text)
        self.assertIn("Glass Orchard: more than one title in Sofa could be this one", text)
        self.assertNotIn("Velvet", text)
        self.assertEqual(self.tables(), ([], []))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(history_cli.main(["plex-db", self.plex_db, "--map", "/data/movies=>%s" % MOVIES,
                                               "--user", "Sam=>hist-sam", "--write"]), 0)
        self.assertTrue(store.q1("SELECT 1 FROM progress WHERE user_id = ? AND item = ?", self.admin_id, "m:harbor-lights:1994"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(history_cli.main(["plex-db", self.plex_db, "--user", "Nobody=>hist-sam"]), 1)
            self.assertEqual(history_cli.main(["plex-db", self.plex_db, "--user", "Sam=>no-such-profile"]), 1)
            self.assertEqual(history_cli.main(["vhs", "x"]), 2)
        self.assertIn("Nobody called 'Nobody'", out.getvalue())


if __name__ == "__main__":
    unittest.main()
