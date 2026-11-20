"""Sofa Box OS: Edge Music as the box's own app (deploy/sofa-box/music/, boxmusic.py), 1.1.103.

Until now the box opened Edge Music's website in a tab, and the website carried a flattened layout for the box. The
owner (2026-11-19): the website stays as beautiful as it can be for desktops and phones, and the box gets an app of
its own that uses the same catalogue and accounts. So: a page the box serves at /box/music/, made for a remote and a
Pi 3; the agent asks Edge Music's app API for it (the page can't: that API answers apps, not pages on another
address) and keeps the account's key to itself; signing in is a code typed on a phone.

Here an Edge Music that stands in (the app API's shapes, read from its code on 2026-11-19) answers the agent, so
nothing is asked of the real one, and no real account is touched. SOFA_BOX_SHOTS=<folder> keeps a picture of each page."""
import base64
import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.test_box_speed import BOX, Page, chrome, free_port, get, load

sys.path.insert(0, BOX)
import boxmusic  # noqa: E402
import boxos  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def wav(seconds=60, rate=8000):      # (long enough that no song ends while a test looks at it)
    n = seconds * rate
    return b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8) + b"data" + struct.pack("<I", n) + b"\x80" * n


def track_id(n):
    return base64.urlsafe_b64encode(("Music/Artists/A%d/song %d.mp3" % (n % 3, n)).encode()).decode().rstrip("=")


class StandIn:
    """Edge Music's app API, as far as the box uses it."""

    def __init__(self):
        self.asked, self.lock = [], threading.Lock()
        self.refuse = self.down = False
        self.pair, self.tokens, self.liked, self.played = None, {}, [], []
        self.edit_ready = True
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, status, body, ctype="application/json"):
                body = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self.any(None)

            def do_POST(self):
                self.any(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"))

            def any(self, body):
                u = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                with outer.lock:
                    outer.asked.append({"path": u.path, "query": q, "body": body, "ua": self.headers.get("User-Agent"),
                                        "auth": self.headers.get("Authorization"), "origin": self.headers.get("Origin")})
                if u.path == "/stream.php":                        # in parts when asked, as stream.php does (so a song can be moved through)
                    rng = self.headers.get("Range") or ""
                    if not rng.startswith("bytes="):
                        return self.reply(200, WAV, "audio/wav")
                    a, _, b = rng[6:].partition("-")
                    a, b = int(a or 0), min(int(b) if b else len(WAV) - 1, len(WAV) - 1)
                    self.send_response(206)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, len(WAV)))
                    self.send_header("Content-Length", str(b - a + 1))
                    self.end_headers()
                    return self.wfile.write(WAV[a:b + 1])
                if u.path == "/art.php":
                    return self.reply(200, PNG, "image/png")
                if outer.refuse:
                    return self.reply(403, {"ok": False})
                if outer.down:
                    return self.reply(503, {"ok": False, "error": "Catalog unavailable. Please retry."})
                site = "http://127.0.0.1:%d/" % outer.port
                if u.path == "/native-api.php":
                    tracks = [{"id": track_id(n), "title": "Song %d" % n, "artist": "Artist %d" % (n % 3), "source": "hosted",
                               "streamUrl": site + "stream.php?f=" + track_id(n), "artworkUrl": site + "art.php?f=" + track_id(n),
                               "durationSeconds": 180 + n, "genre": "Reggaeton" if n % 2 else "Trap", "mood": "excited", "language": "es",
                               "explicit": False} for n in range(30)]
                    tracks.append(dict(tracks[0], id="elsewhere", streamUrl="https://example.com/a.mp3"))     # never played from elsewhere
                    off = int(q.get("offset") or 0)
                    return self.reply(200, {"ok": True, "version": 1, "tracks": tracks[off:off + 20], "nextOffset": off + 20 if off + 20 < len(tracks) else None,
                                            "albums": [{"id": "first", "title": "First Album", "artist": "Artist 0", "artworkUrl": None,
                                                        "trackIds": [track_id(0), track_id(3), track_id(6), "gone"]}] if off == 0 else [],
                                            "stations": [{"id": "mix", "name": "The Mix", "subtitle": "A little of everything",
                                                          "artworkUrl": site + "art.php?f=" + track_id(1), "trackIds": [track_id(n) for n in range(10)]}] if off == 0 else []})
                token = (self.headers.get("Authorization") or "")[7:]
                if u.path == "/native-account.php":
                    action = (body or q).get("action", "library")
                    if action == "start":
                        if body.get("libraryEdit") and not outer.edit_ready:
                            return self.reply(503, {"ok": False, "error": "Native playlist editing is not ready yet."})
                        outer.pair = {"device": "d" * 64, "challenge": body["challenge"], "client": body["client"], "edit": body.get("libraryEdit"),
                                      "approved": False, "polls": 0}
                        return self.reply(200, {"ok": True, "deviceCode": "d" * 64, "userCode": "AB12CD34EF", "expiresIn": 600, "interval": 5,
                                                "verificationUrl": site + "devices.php"})
                    if action == "poll":
                        p = outer.pair
                        if not p or body.get("deviceCode") != p["device"] or hashlib.sha256(body.get("verifier", "").encode()).hexdigest() != p["challenge"]:
                            return self.reply(410, {"ok": False, "error": "Device code expired. Start linking again."})
                        p["polls"] += 1
                        if not p["approved"]:
                            return self.reply(200, {"ok": True, "pending": True, "interval": 5})
                        tok = "ab" * 32
                        outer.tokens[tok] = True
                        return self.reply(200, {"ok": True, "pending": False, "accessToken": tok, "tokenType": "Bearer", "expiresIn": 2592000,
                                                "libraryEdit": bool(p["edit"])})
                    if token not in outer.tokens:
                        return self.reply(401, {"ok": False, "error": "Your device link expired or was removed. Link again."})
                    if action == "revoke":
                        del outer.tokens[token]
                        return self.reply(200, {"ok": True, "removed": True})
                    return self.reply(200, {"ok": True, "profile": {"name": "Sam"}, "likedIds": list(outer.liked), "recentIds": list(outer.played),
                                            "playlists": [{"id": "p1", "name": "Sunday", "trackIds": [track_id(2), track_id(4)]}]})
                if u.path == "/native-library.php":
                    if token not in outer.tokens:
                        return self.reply(401, {"ok": False, "error": "Link again."})
                    a, tid = body.get("action"), body.get("trackId")
                    if not isinstance(body.get("clientKey"), str) or len(body["clientKey"]) != 32:
                        return self.reply(400, {"ok": False, "error": "That room reference is invalid."})
                    if a == "like":
                        outer.liked.insert(0, tid)
                    elif a == "unlike":
                        outer.liked.remove(tid)
                    elif a == "played":
                        outer.played.insert(0, tid)
                    return self.reply(200, {"ok": True, "version": 1})
                self.reply(404, {"ok": False})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.site = "http://127.0.0.1:%d" % self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def api_calls(self):
        return [a for a in self.asked if a["path"].startswith("/native")]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


WAV = wav()


class TheAgentAsksEdgeMusic(unittest.TestCase):
    def setUp(self):
        self.edge, self.conf = StandIn(), tempfile.mkdtemp()
        self.m = boxmusic.Music(self.conf, "SofaBox/9.9 test", site=self.edge.site)

    def tearDown(self):
        self.edge.close()
        shutil.rmtree(self.conf, ignore_errors=True)

    def link(self):
        self.m.link_start()
        self.edge.pair["approved"] = True
        self.m.pairing["next"] = 0
        self.assertTrue(self.m.link_poll()["linked"])

    def test_the_catalogue_as_the_page_draws_it(self):
        c = self.m.catalog()
        self.assertEqual(len(c["tracks"]), 30)                                   # both pages of it; the song from elsewhere left out
        t = c["tracks"][0]
        self.assertEqual(t["stream"], self.edge.site + "/stream.php?f=" + track_id(0))
        self.assertTrue(t["art"].startswith(self.edge.site + "/art.php?f="))
        self.assertEqual(c["albums"][0]["trackIds"], [track_id(0), track_id(3), track_id(6)])     # a song that's gone isn't listed
        self.assertEqual(c["albums"][0]["art"], t["art"])                        # an album without a cover: its first song's
        self.assertEqual(c["stations"][0]["name"], "The Mix")
        self.assertTrue(all(a["ua"] == "SofaBox/9.9 test" and not a["origin"] for a in self.edge.asked))

    def test_kept_ten_minutes_and_the_last_one_when_edge_music_is_away(self):
        self.m.catalog()
        n = len(self.edge.asked)
        self.m.catalog()
        self.assertEqual(len(self.edge.asked), n)                                # not asked again
        self.assertTrue(os.path.exists(os.path.join(self.conf, "edge-music-catalog.json")))
        self.edge.down = True
        again = boxmusic.Music(self.conf, "SofaBox/9.9 test", site=self.edge.site)      # the box started again, Edge Music away
        c = again.catalog()
        self.assertTrue(c["stale"])
        self.assertEqual(len(c["tracks"]), 30)
        fresh = boxmusic.Music(tempfile.mkdtemp(), "SofaBox/9.9 test", site=self.edge.site)
        self.assertEqual(fresh.catalog()["tracks"], [])                          # a new box, Edge Music away: said so, nothing made up
        self.assertIn("can't be reached", fresh.catalog()["error"])

    def test_a_refusal_stops_the_asking(self):
        """A box that was told no doesn't keep asking: after one refusal, nothing more is asked until it starts again."""
        self.edge.refuse = True
        self.m.catalog()
        self.m.catalog()
        self.m.account()
        self.assertFalse(self.m.link_start()["ok"])
        self.assertEqual(len(self.edge.api_calls()), 1)
        self.assertTrue(self.m.stopped)

    def test_signing_in_by_a_code(self):
        self.assertEqual(self.m.account(), {"linked": False, "pairing": None})
        r = self.m.link_start()
        self.assertEqual(r["pairing"]["code"], "AB12CD34EF")
        self.assertTrue(r["pairing"]["at"].endswith("/devices.php"))
        self.assertNotIn("d" * 64, json.dumps(r))                              # the page gets the code to show, nothing more
        p = self.edge.pair
        self.assertEqual((p["client"], p["edit"]), ("desktop", True))            # the one kind Edge Music takes; liking asked for
        self.assertEqual(self.m.link_start()["pairing"]["code"], "AB12CD34EF")   # asked again: the same code, Edge Music not asked
        self.assertEqual(len([a for a in self.edge.api_calls() if (a["body"] or {}).get("action") == "start"]), 1)
        self.assertFalse(self.m.link_poll()["linked"])                           # too soon: Edge Music isn't asked before it said to be
        self.assertEqual(p["polls"], 0)
        self.m.pairing["next"] = 0
        self.assertFalse(self.m.link_poll()["linked"])
        self.assertEqual(p["polls"], 1)
        p["approved"] = True
        self.m.pairing["next"] = 0
        self.assertTrue(self.m.link_poll()["linked"])
        path = os.path.join(self.conf, "edge-music.json")
        if os.name != "nt":                                                      # (Windows keeps no such modes; a box is Linux)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)             # the key: the box's user only
        acc = self.m.account()
        self.assertEqual((acc["linked"], acc["name"], acc["canEdit"]), (True, "Sam", True))
        self.assertEqual(acc["playlists"][0]["name"], "Sunday")
        self.assertNotIn("ab" * 32, json.dumps(acc))                             # the page never sees the key
        again = boxmusic.Music(self.conf, "SofaBox/9.9 test", site=self.edge.site)
        self.assertTrue(again.account()["linked"])                               # still signed in after a restart

    def test_signed_in_to_listen_when_liking_is_switched_off_there(self):
        self.edge.edit_ready = False
        self.m.link_start()
        self.assertFalse(self.edge.pair["edit"])
        self.edge.pair["approved"] = True
        self.m.pairing["next"] = 0
        self.m.link_poll()
        self.assertFalse(self.m.account()["canEdit"])
        self.assertEqual(self.m.taste("like", track_id(1))["reason"], "grant")

    def test_like_unlike_and_played(self):
        self.assertEqual(self.m.taste("like", track_id(1))["reason"], "signin")  # not signed in: Edge Music isn't asked
        self.link()
        self.assertTrue(self.m.account()["linked"])
        self.assertTrue(self.m.taste("like", track_id(1))["ok"])
        self.assertEqual(self.edge.liked, [track_id(1)])
        self.assertEqual(self.m.account()["likedIds"], [track_id(1)])            # shown at once, without asking again
        self.assertTrue(self.m.taste("played", track_id(2))["ok"])
        self.assertEqual(self.edge.played, [track_id(2)])
        self.assertTrue(self.m.taste("unlike", track_id(1))["ok"])
        self.assertEqual(self.edge.liked, [])
        for bad in (("delete", track_id(1)), ("like", "../x"), ("like", None), ("like", "a" * 181)):
            with self.assertRaises(ValueError):
                self.m.taste(*bad)

    def test_a_link_that_ran_out_and_signing_out(self):
        self.link()
        self.edge.tokens.clear()                                                 # 30 days on, or removed on the website
        self.assertEqual(self.m.account(fresh=True), {"linked": False, "expired": True, "pairing": None})
        self.assertFalse(os.path.exists(os.path.join(self.conf, "edge-music.json")))
        self.link()
        self.m.unlink()
        self.assertEqual(self.edge.tokens, {})                                   # Edge Music forgot the key too
        self.assertFalse(self.m.account()["linked"])

    def test_nothing_typed_is_ever_sent(self):
        """Search is the page's, over the catalogue it has: a word typed on the TV never goes into an address."""
        self.link()
        self.m.catalog()
        self.m.account()
        for a in self.edge.api_calls():
            self.assertLessEqual(set(a["query"]), {"v", "limit", "offset", "action"})
        with open(os.path.join(BOX, "music", "music.js"), encoding="utf-8") as f:
            page = f.read()
        self.assertNotIn("edgeventure", page)                                    # the page knows the agent, not Edge Music's address
        self.assertNotIn("q=", page)


class TheStoreAndInstalledBoxes(unittest.TestCase):
    def test_the_store_installs_the_boxs_own_app(self):
        e = boxos.store_entry("edge-music")
        self.assertEqual(e["url"], "/box/music/")
        self.assertTrue(e["icon"].startswith("https://"))                        # (its tile's picture: not looked for at a local address)
        self.assertEqual(boxos.app_from_store(e)["id"], "edge-music")

    def test_a_box_that_has_the_website_gets_the_app(self):
        for old in ("https://music.edgeventure.uk", "https://music.edgeventure.uk/", "https://music.edgeventure.uk/?client=sofabox"):
            data = {"apps": [{"id": "edge-music", "url": old}, {"id": "kitchen", "url": old}]}
            self.assertTrue(boxos.moved_apps(data))
            self.assertEqual(data["apps"][0]["url"], "/box/music/")
            self.assertEqual(data["apps"][1]["url"], old)                        # a site added by hand stays as it is
        data = {"apps": [{"id": "edge-music", "url": "https://music.edgeventure.uk/player.html"}]}
        self.assertFalse(boxos.moved_apps(data))                                 # an address someone chose: left alone
        self.assertFalse(boxos.moved_apps({"apps": [{"id": "edge-music", "url": "/box/music/"}]}))


class ThePage(unittest.TestCase):
    """In a browser at a TV's size, drawn without a graphics card, with the box's agent and the stand-in Edge Music."""

    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.edge, cls.dir = StandIn(), tempfile.mkdtemp()
        cls.conf, run = os.path.join(cls.dir, "conf"), os.path.join(cls.dir, "run")
        os.makedirs(cls.conf)
        os.makedirs(run)
        with open(os.path.join(cls.conf, "apps.json"), "w") as f:
            json.dump({"apps": [{"id": "edge-music", "name": "Edge Music", "kind": "web", "url": "https://music.edgeventure.uk/?client=sofabox"}],
                       "order": [], "hidden": []}, f)
        with open(os.path.join(cls.conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": True, "weather": "off", "boot_sound": "off"}, f)
        cls.port, cls.devtools = free_port(), free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1920,1080",
                                       "--autoplay-policy=no-user-gesture-required", "--mute-audio",
                                       "--remote-debugging-port=%d" % cls.devtools, "--user-data-dir=" + os.path.join(cls.dir, "profile"),
                                       "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cls.dir, SOFA_BOX_CONF=cls.conf, SOFA_BOX_PORT=str(cls.port), SOFA_BOX_SLOW="1",
                                              SOFA_BOX_DEVTOOLS="0", XDG_RUNTIME_DIR=run, SOFA_BOX_UINPUT="0", SOFA_BOX_ICONS="0",
                                              SOFA_BOX_HOTSPOT="0", SOFA_BOX_CERTS="0", SOFA_BOX_NEWEST="0", SOFA_BOX_CAPTIVE_PORT="0",
                                              SOFA_BOX_REMOTE_PORT=str(free_port()), SOFA_BOX_MUSIC=cls.edge.site))
        for _ in range(300):
            try:
                if get(cls.base + "/box/api/apps", 5)[0] == 200:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        cls.page = Page(cls.devtools, "about:blank")
        cls.shots = os.environ.get("SOFA_BOX_SHOTS")

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        cls.agent.terminate()
        cls.chrome.terminate()
        cls.agent.wait(10)
        cls.chrome.wait(10)
        cls.edge.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-Sofa-Box": "1"})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as r:
            return json.loads(r.read())

    def open(self):
        p = self.page
        p.call("Page.navigate", {"url": self.base + "/box/music/?t=%f" % time.time()})
        self.wait("!!window.EdgeMusicBox && document.querySelectorAll('#view .row .card').length > 3")
        return p

    def wait(self, expression, seconds=10):
        for _ in range(int(seconds * 10)):
            if self.page.value(expression):
                return
            time.sleep(0.1)
        self.fail("never: " + expression)

    def shot(self, name):
        if not self.shots:
            return
        os.makedirs(self.shots, exist_ok=True)
        time.sleep(0.4)
        data = self.page.call("Page.captureScreenshot", {"format": "png"})["data"]
        with open(os.path.join(self.shots, name + ".png"), "wb") as f:
            f.write(base64.b64decode(data))

    def state(self):
        return self.page.value("EdgeMusicBox.state()")

    def focus(self):
        return self.page.value("(document.activeElement.dataset.k || document.activeElement.dataset.tab || document.activeElement.id || '')")

    def test_1_the_box_opens_its_own_app(self):
        with open(os.path.join(self.conf, "apps.json")) as f:                    # the agent started: the website's address became the app's
            self.assertEqual(json.load(f)["apps"][0]["url"], "/box/music/")
        self.assertEqual(self.post("/box/api/open", {"id": "edge-music"})["url"], self.base + "/box/music/")
        status, _, body = get(self.base + "/box/api/music/catalog")
        self.assertEqual((status, len(json.loads(body)["tracks"])), (200, 30))
        with self.assertRaises(urllib.error.HTTPError) as no:                    # a page from another site can't sign the box in or out
            get(self.base + "/box/api/music/unlink")
        self.assertEqual(no.exception.code, 405)

    def test_2_home_and_the_remote(self):
        p = self.open()
        self.shot("1-home")
        self.assertEqual(self.focus(), "album:first")                            # the ring starts on the first thing to play
        self.assertEqual(p.value("[...document.querySelectorAll('.f')].map(e => e.dataset.k).join()"), "album:first")   # drawn before any press
        self.assertEqual(p.value("[...document.querySelectorAll('#view h2')].map(h => h.textContent).join()"), "Albums,Stations,Artists,Songs")
        p.press("ArrowDown", 40)
        self.assertEqual(self.focus(), "station:mix")
        p.press("ArrowDown", 40)
        self.assertTrue(self.focus().startswith("artist:"))
        p.press("ArrowDown", 40)
        self.assertEqual(self.focus(), "s:all:0")
        for _ in range(9):                                                       # along a row longer than the TV: it moves under the ring
            p.press("ArrowRight", 39)
        self.assertEqual(self.focus(), "s:all:9")
        self.assertTrue(p.value("(() => { const r = document.activeElement.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; })()"))
        self.assertEqual(p.value("scrollX"), 0)                                  # the row moved, not the page
        p.press("ArrowUp", 38)
        p.press("ArrowUp", 38)
        p.press("ArrowUp", 38)
        p.press("ArrowUp", 38)
        self.assertEqual(p.value("document.activeElement.parentElement.id"), "tabs")
        self.assertEqual(p.value("[...document.styleSheets].flatMap(s => [...s.cssRules]).filter(r => /animation|transition|backdrop-filter|box-shadow/.test(r.cssText)).length"), 0)
        covers = p.value("[...document.querySelectorAll('#view img.cv')].map(i => i.getAttribute('src'))")
        self.assertTrue(covers and all(c.endswith("&w=320") for c in covers))    # covers at the size they're drawn

    def test_3_an_album_plays_and_back_goes_one_step(self):
        p = self.open()
        p.press("Enter", 13)                                                     # the album
        self.assertEqual((self.state()["view"], self.focus()), ("set", "play"))
        self.shot("2-album")
        p.press("Enter", 13)                                                     # Play
        self.wait("EdgeMusicBox.state().playing")
        s = self.state()
        self.assertEqual((s["now"], s["track"], s["queue"]), (True, track_id(0), 3))
        self.assertEqual(self.focus(), "pp")
        self.shot("3-now-playing")
        self.assertEqual(p.value("navigator.mediaSession.metadata.title + '|' + navigator.mediaSession.metadata.artist + '|' + navigator.mediaSession.metadata.artwork.map(a => a.sizes).join()"),
                         "Song 0|Artist 0|320x320,640x640")
        self.assertEqual(p.value("navigator.mediaSession.playbackState"), "playing")
        self.assertTrue(p.value("document.querySelector('#now img.cv').src.endsWith('&w=640')"))
        self.assertTrue(p.value("document.querySelector('#audio').src").startswith(self.edge.site + "/stream.php?f="))
        p.press("MediaPlayPause", 179)
        self.assertFalse(self.state()["playing"])
        p.press("MediaPlayPause", 179)
        self.wait("EdgeMusicBox.state().playing")
        p.press("MediaTrackNext", 176)
        self.assertEqual(self.state()["track"], track_id(3))
        p.press("ArrowRight", 39)                                                # along the buttons: next
        self.assertEqual(self.focus(), "next")
        p.press("Enter", 13)
        self.assertEqual(self.state()["track"], track_id(6))
        p.press("ArrowUp", 38)                                                   # the line of the song: left and right move through it
        self.assertEqual(self.focus(), "seek")
        self.wait("document.querySelector('#audio').currentTime > 0.2")
        p.press("ArrowRight", 39)
        self.assertEqual(self.focus(), "seek")
        self.assertGreater(p.value("document.querySelector('#audio').currentTime"), 9)
        p.press("Escape", 27)                                                    # Back: out of the player, the song goes on
        s = self.state()
        self.assertEqual((s["now"], s["view"], s["playing"]), (False, "set", True))
        self.assertFalse(p.value("document.querySelector('#bar').hidden"))
        self.assertEqual(p.value("document.querySelector('#view .song.on b').textContent"), "Song 6")
        self.shot("4-album-playing")
        p.press("BrowserBack", 166)                                              # Back again: Home, the ring where it was
        self.assertEqual((self.state()["view"], self.focus()), ("home", "album:first"))
        # On the app's Home, Back asks the box for its Home screen by name. (A tab begins as an empty page, so Back
        # left to the browser stepped back to that, and the music stopped.)
        p.value("window.asked = []; const f = window.fetch; window.fetch = (u, o) => { window.asked.push((o && o.method || 'GET') + ' ' + u); return f(u, o); }")
        p.press("Escape", 27)
        self.assertEqual(p.value("window.asked.join()"), "POST /box/api/home")
        s = self.state()
        self.assertEqual((s["view"], s["playing"]), ("home", True))              # the page is still here, the song goes on

    def test_4_search_with_the_remote_or_a_keyboard(self):
        p = self.open()
        p.value("document.querySelector('[data-tab=search]').click()")
        self.assertEqual(self.focus(), "key:A")
        p.press("Enter", 13)                                                     # a letter picked with the remote
        self.assertEqual(p.value("document.querySelector('#typed').textContent"), "A")
        for ch in "rtist 2":                                                     # the rest typed on a keyboard
            p.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": ch, "text": ch})
            p.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch})
        self.assertEqual(p.value("document.querySelector('#typed').textContent"), "ARTIST 2")
        self.assertEqual(p.value("document.querySelectorAll('#found .song').length"), 10)
        self.shot("5-search")
        n = len(self.edge.api_calls())
        p.press("Backspace", 8)                                                  # takes a letter away, while there is one
        self.assertEqual((p.value("document.querySelector('#typed').textContent"), self.state()["view"]), ("ARTIST ", "search"))
        self.assertEqual(len(self.edge.api_calls()), n)                          # searching asks Edge Music nothing

    def test_5_signing_in_and_liking(self):
        self.edge.liked, self.edge.played = [], []
        p = self.open()
        p.value("document.querySelector('[data-tab=account]').click()")
        self.assertEqual(self.focus(), "code")
        self.shot("6-sign-in")
        p.press("Enter", 13)
        self.wait("!!document.querySelector('#view .code')")
        self.assertEqual(p.value("document.querySelector('#view .code').textContent"), "AB12CD34EF")
        self.assertTrue(p.value("!!document.querySelector('#view .qr svg')"))
        self.shot("7-code")
        self.edge.pair["approved"] = True                                        # typed on the phone
        self.wait("EdgeMusicBox.state().linked && EdgeMusicBox.state().view === 'home'", 25)
        self.assertEqual(p.value("document.querySelector('#tabAccount').textContent"), "Sam")
        self.assertNotIn("ab" * 32, p.value("document.documentElement.outerHTML + JSON.stringify(Object.assign({}, localStorage))"))
        p.value("document.querySelector('#view [data-ctx]').click()")           # a song
        self.wait("EdgeMusicBox.state().playing")
        p.value("document.querySelector('#bar').click()")
        p.value("document.querySelector('#now [data-act=like]').click()")
        self.wait("document.querySelector('#now [data-act=like]').getAttribute('aria-pressed') === 'true'")
        for _ in range(50):
            if self.edge.liked:
                break
            time.sleep(0.1)
        self.assertEqual(len(self.edge.liked), 1)
        p.press("Escape", 27)
        p.value("document.querySelector('[data-tab=home]').click()")
        self.assertEqual(p.value("document.querySelector('#view h2').textContent"), "Songs you like")
        self.shot("8-home-signed-in")
        p.value("document.querySelector('[data-tab=account]').click()")
        self.shot("9-account")
        p.value("document.querySelector('[data-act=signout]').click()")
        self.wait("!EdgeMusicBox.state().linked")
        self.assertEqual(self.edge.tokens, {})


if __name__ == "__main__":
    unittest.main()
