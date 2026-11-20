"""Edge Music on the box: the box's own app (music/, at /box/music/) asks the agent, and the agent asks Edge Music.

The page never talks to music.edgeventure.uk itself, except to play a song and show a cover (an <audio> and an
<img>, which any page may point anywhere). Everything else goes through here, for three reasons:

- Edge Music's app API (native-api.php, native-account.php, native-library.php: the one its phone and desktop apps
  use) answers apps, not pages on another address: it sends no cross-site permission, and refuses a sign-in that
  comes with a page's Origin.
- The account's key stays with the agent, in ~/.config/sofa-box/edge-music.json (only the box's user can read it).
  A page never sees it, so nothing a page loads can take it.
- One place decides how often Edge Music is asked: the catalogue is kept for ten minutes (and on the card, so the
  app opens without the internet's answer), the account for a minute, and a refusal stops everything: a box that
  was told no doesn't keep asking.

Signing in is by a code on the TV: the box asks for one, shows it, and the listener types it at
music.edgeventure.uk/devices.php on a phone, signed in there. The box never sees a password.

Standard library only, like the rest of the box."""
import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request

SITE = (os.environ.get("SOFA_BOX_MUSIC") or "https://music.edgeventure.uk").rstrip("/")
CATALOG_FOR = 600          # seconds a catalogue is kept before Edge Music is asked again
ACCOUNT_FOR = 60
TRACK_ID = re.compile(r"^[A-Za-z0-9_-]{1,180}$")
TASTE = ("like", "unlike", "played")
COVER_WIDTHS = (160, 320, 480, 640)     # what art.php?w= makes (Edge Music, art-lib.php)

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Refused(Exception):
    """Edge Music said no in a way that asking again would only make worse (403): nothing more is asked."""


class Music:
    def __init__(self, conf_dir, user_agent, site=None):
        self.site = (site or SITE).rstrip("/")
        self.ua = user_agent
        self.conf = conf_dir
        self.lock = threading.Lock()
        self.stopped = False                # after a 403: until the agent starts again
        self._catalog, self._catalog_at = None, 0
        self._account, self._account_at = None, 0
        self.pairing = None                 # {"device", "verifier", "code", "until", "next", "edit"}
        self.state = self._read("edge-music.json") or {}

    # ---- files
    def _path(self, name):
        return os.path.join(self.conf, name)

    def _read(self, name):
        try:
            with open(self._path(name), encoding="utf-8") as f:
                got = json.load(f)
            return got if isinstance(got, dict) else None
        except (OSError, ValueError):
            return None

    def _write(self, name, data, private=False):
        os.makedirs(self.conf, exist_ok=True)
        tmp = self._path(name) + ".new"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self._path(name))

    # ---- one request
    def _ask(self, path, body=None, token=None, timeout=12):
        """(status, answer). The answer is Edge Music's JSON, or {} when it sent something else."""
        if self.stopped:
            raise Refused()
        headers = {"User-Agent": self.ua, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(self.site + path, data=data, headers=headers)
        try:
            with _opener.open(req, timeout=timeout) as r:
                status, raw = r.status, r.read(4 << 20)
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read(1 << 16)
            exc.close()
        if status == 403:
            self.stopped = True
            raise Refused()
        try:
            got = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            got = {}
        return status, got if isinstance(got, dict) else {}

    # ---- the catalogue (no account needed)
    def catalog(self):
        """Every song, album and station, as the page draws them. Kept ten minutes; when Edge Music can't be reached,
        the last one this box had (with "stale": True), so the app still opens."""
        with self.lock:
            if self._catalog and time.time() - self._catalog_at < CATALOG_FOR:
                return self._catalog
            try:
                fresh = self._fetch_catalog()
            except Refused:
                fresh = None
            except (OSError, ValueError):
                fresh = None
            if fresh:
                self._catalog, self._catalog_at = fresh, time.time()
                try:
                    self._write("edge-music-catalog.json", fresh)
                except OSError:
                    pass
                return fresh
            old = self._catalog or self._read("edge-music-catalog.json")
            if old and old.get("tracks"):
                self._catalog, self._catalog_at = dict(old, stale=True), time.time() - CATALOG_FOR + 60   # asked again in a minute
                return self._catalog
            return {"ok": False, "error": "Edge Music can't be reached right now.", "tracks": [], "albums": [], "stations": []}

    def _fetch_catalog(self):
        tracks, albums, stations, offset = [], [], [], 0
        while offset is not None and offset <= 10000:
            status, got = self._ask("/native-api.php?v=1&limit=200&offset=%d" % offset)
            if status != 200 or not got.get("ok"):
                raise ValueError("catalogue")
            if offset == 0:
                albums, stations = got.get("albums") or [], got.get("stations") or []
            for t in got.get("tracks") or []:
                tid, stream = t.get("id"), t.get("streamUrl") or ""
                if not isinstance(tid, str) or not TRACK_ID.match(tid) or not stream.startswith(self.site + "/"):
                    continue                # (a song is only ever played from Edge Music's own address)
                tracks.append({"id": tid, "title": t.get("title") or "", "artist": t.get("artist") or "",
                               "stream": stream, "art": self._art(t.get("artworkUrl")),
                               "seconds": t.get("durationSeconds"), "genre": t.get("genre"), "mood": t.get("mood"),
                               "language": t.get("language"), "explicit": bool(t.get("explicit"))})
            nxt = got.get("nextOffset")
            offset = nxt if isinstance(nxt, int) and nxt > offset else None
        if not tracks:
            raise ValueError("empty")
        known = {t["id"]: t for t in tracks}

        def ids(entry):
            return [i for i in entry.get("trackIds") or [] if i in known]

        def cover(entry, their):
            return self._art(entry.get("artworkUrl")) or (known[their[0]]["art"] if their else None)

        out_albums = []
        for a in albums:
            their = ids(a)
            if a.get("id") and their:
                out_albums.append({"id": str(a["id"]), "title": a.get("title") or "", "artist": a.get("artist") or "",
                                   "art": cover(a, their), "trackIds": their})
        out_stations = []
        for s in stations:
            their = ids(s)
            if s.get("id") and their:
                out_stations.append({"id": str(s["id"]), "name": s.get("name") or "", "line": s.get("subtitle") or "",
                                     "art": cover(s, their), "trackIds": their})
        return {"ok": True, "site": self.site, "tracks": tracks, "albums": out_albums, "stations": out_stations,
                "widths": list(COVER_WIDTHS), "at": int(time.time())}

    def _art(self, url):
        """A cover's address, only if it's Edge Music's own art.php (the page adds &w= for the size it draws)."""
        return url if isinstance(url, str) and url.startswith(self.site + "/art.php?f=") else None

    # ---- the account
    def _forget(self):
        self.state, self._account, self._account_at = {}, None, 0
        try:
            os.remove(self._path("edge-music.json"))
        except OSError:
            pass

    def account(self, fresh=False):
        """Who is signed in on this box, and their liked and recent songs. Never the key."""
        with self.lock:
            token = self.state.get("token")
            if not token:
                return {"linked": False, "pairing": self._pairing_view()}
            if self._account and not fresh and time.time() - self._account_at < ACCOUNT_FOR:
                return self._account
            try:
                status, got = self._ask("/native-account.php?action=library", token=token)
            except Refused:
                return self._account or {"linked": True, "offline": True, "likedIds": [], "recentIds": [], "playlists": []}
            except OSError:
                return self._account or {"linked": True, "offline": True, "likedIds": [], "recentIds": [], "playlists": []}
            if status == 401:               # the link ran out (30 days) or was removed on the website
                self._forget()
                return {"linked": False, "expired": True, "pairing": None}
            if status != 200 or not got.get("ok"):
                return self._account or {"linked": True, "offline": True, "likedIds": [], "recentIds": [], "playlists": []}
            self._account = {"linked": True, "name": (got.get("profile") or {}).get("name") or "",
                             "likedIds": got.get("likedIds") or [], "recentIds": got.get("recentIds") or [],
                             "playlists": [{"id": p.get("id"), "name": p.get("name") or "Playlist", "trackIds": p.get("trackIds") or []}
                                           for p in got.get("playlists") or [] if p.get("trackIds")],
                             "canEdit": bool(self.state.get("edit")), "until": self.state.get("until")}
            self._account_at = time.time()
            return self._account

    def _pairing_view(self):
        p = self.pairing
        if not p or p["until"] <= time.time():
            self.pairing = None
            return None
        return {"code": p["code"], "at": self.site.split("://", 1)[1] + "/devices.php", "url": self.site + "/devices.php",
                "seconds": int(p["until"] - time.time())}

    def link_start(self):
        """A code to type at music.edgeventure.uk/devices.php. One at a time: asked again, the same code while it lasts."""
        with self.lock:
            if self.state.get("token"):
                return {"ok": True, "linked": True}
            view = self._pairing_view()
            if view:
                return {"ok": True, "pairing": view}
            verifier = secrets.token_hex(32)
            body = {"action": "start", "client": "desktop", "challenge": hashlib.sha256(verifier.encode()).hexdigest(),
                    "libraryEdit": True}
            try:
                status, got = self._ask("/native-account.php", body)
                if status == 503:           # liking from apps is switched off there: sign in to listen, all the same
                    body["libraryEdit"] = False
                    status, got = self._ask("/native-account.php", body)
            except Refused:
                return {"ok": False, "message": "Edge Music isn't answering this box. Try again after a restart."}
            except OSError:
                return {"ok": False, "message": "Edge Music can't be reached right now."}
            if status != 200 or not got.get("deviceCode") or not got.get("userCode"):
                return {"ok": False, "message": got.get("error") or "Edge Music couldn't give a code. Try again in a while."}
            self.pairing = {"device": got["deviceCode"], "verifier": verifier, "code": str(got["userCode"]),
                            "until": time.time() + min(600, int(got.get("expiresIn") or 600)),
                            "next": time.time() + max(5, int(got.get("interval") or 5)), "edit": body["libraryEdit"]}
            return {"ok": True, "pairing": self._pairing_view()}

    def link_poll(self):
        """Has the code been typed yet? Edge Music is asked no more often than it said to be."""
        with self.lock:
            if self.state.get("token"):
                return {"ok": True, "linked": True}
            view = self._pairing_view()
            p = self.pairing
            if not p:
                return {"ok": True, "linked": False, "pairing": None}
            if time.time() < p["next"]:
                return {"ok": True, "linked": False, "pairing": view}
            try:
                status, got = self._ask("/native-account.php", {"action": "poll", "deviceCode": p["device"], "verifier": p["verifier"]})
            except (Refused, OSError):
                p["next"] = time.time() + 15
                return {"ok": True, "linked": False, "pairing": view}
            if status == 200 and got.get("accessToken"):
                until = int(time.time()) + int(got.get("expiresIn") or 2592000)
                self.state = {"token": got["accessToken"], "edit": bool(got.get("libraryEdit")), "linked": int(time.time()), "until": until}
                self._write("edge-music.json", self.state, private=True)
                self.pairing, self._account = None, None
                return {"ok": True, "linked": True}
            if status == 200 and got.get("pending"):
                p["next"] = time.time() + max(5, int(got.get("interval") or 5))
                return {"ok": True, "linked": False, "pairing": view}
            self.pairing = None             # the code ran out, or too many devices: start again
            return {"ok": False, "linked": False, "pairing": None, "message": got.get("error") or "That code ran out. Get a new one."}

    def link_cancel(self):
        with self.lock:
            self.pairing = None
            return {"ok": True}

    def unlink(self):
        """Sign this box out: Edge Music forgets the key too, when it can be told."""
        with self.lock:
            token = self.state.get("token")
            if token:
                try:
                    self._ask("/native-account.php", {"action": "revoke"}, token=token, timeout=8)
                except (Refused, OSError):
                    pass
            self._forget()
            self.pairing = None
            return {"ok": True}

    def taste(self, action, track_id):
        """Like, unlike, or note that a song was played (the account's Recently played, as on the website)."""
        if action not in TASTE or not isinstance(track_id, str) or not TRACK_ID.match(track_id):
            raise ValueError("That isn't something to do with a song.")
        with self.lock:
            token = self.state.get("token")
            if not token:
                return {"ok": False, "reason": "signin", "message": "Sign in to keep the songs you like."}
            if not self.state.get("edit"):
                return {"ok": False, "reason": "grant", "message": "This box may listen but not change your library. Sign out and in again to allow it."}
            try:
                status, got = self._ask("/native-library.php", {"action": action, "trackId": track_id, "clientKey": secrets.token_hex(16)},
                                        token=token, timeout=10)
            except (Refused, OSError):
                return {"ok": False, "reason": "offline", "message": "Edge Music can't be reached right now."}
            if status == 401:
                self._forget()
                return {"ok": False, "reason": "signin", "message": "This box was signed out. Sign in again."}
            if status != 200 or not got.get("ok"):
                return {"ok": False, "reason": got.get("reason") or "refused", "message": got.get("error") or "That wasn't saved."}
            acc = self._account
            if acc and action in ("like", "unlike"):        # the page's next look shows it without asking again
                acc["likedIds"] = [i for i in acc["likedIds"] if i != track_id]
                if action == "like":
                    acc["likedIds"].insert(0, track_id)
            elif acc and action == "played":
                acc["recentIds"] = ([track_id] + [i for i in acc["recentIds"] if i != track_id])[:30]
            return {"ok": True}
