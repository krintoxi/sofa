"""The public demo (sofa/demo.py, docs/public-demo.md): each guardrail, tested against the running server so that one
that breaks fails here. The switch locks its settings; nobody is at home, so there's no admin, setup, sign-in or
sign-up from anywhere; everyone is a visitor who sees only titles with a rights record that passes, played as they
are from their publisher; Live TV only from the checked list, never through the relay, with no decades or Classic
Cinema; no uploads, Inbox or downloads; no trackers; games with no account and nowhere to talk to; rate limits; the
nightly reset; the Sofa Box promotion off the Live TV page; and the seed tool, which builds only titles with a
record."""
import email.message
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from tests import LIBRARY, ROOT, video
from sofa import archive, auth, config, demo, live, organizer, rights, sharing, store, web
from sofa.library import LIBRARY as LIB

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOD = {"licence": "CC BY 3.0", "licence_url": "https://creativecommons.org/licenses/by/3.0/", "publisher": "A Studio",
        "source": "https://commons.example/wiki/File:Open_Film.webm", "checked": "2026-11-18",
        "credit": "(c) A Studio", "play_url": "https://media.example/open-film.webm"}
GOV = {"licence": "US government work", "publisher": "NASA", "source": "https://commons.example/wiki/File:Clip.ogv",
       "checked": "2026-11-18", "basis": "Made by NASA, a US federal agency (17 U.S.C. 105)."}
CHANNEL = {"name": "Agency TV", "url": "https://streams.agency.example/live/master.m3u8", "group": "Science",
           "publisher": "A US agency", "page": "https://agency.example/watch", "kind": "us-government",
           "rights": "The agency's own public stream; a US government work.", "cors": True, "checked": "2026-11-18"}
MADE = [os.path.join(LIBRARY, "Movies", d) for d in ("Open Film (2008)", "Unrecorded (2001)", "Not Free (2002)")] + \
    [os.path.join(LIBRARY, "Shows", "Space Clips")]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class Demo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        movies, shows = os.path.join(LIBRARY, "Movies"), os.path.join(LIBRARY, "Shows")
        video(os.path.join(movies, "Open Film (2008)", "Open Film (2008).mp4"))
        write(os.path.join(movies, "Open Film (2008)", "Open Film (2008).rights.json"), GOOD)
        video(os.path.join(movies, "Unrecorded (2001)", "Unrecorded (2001).mp4"))
        video(os.path.join(movies, "Not Free (2002)", "Not Free (2002).mp4"))
        write(os.path.join(movies, "Not Free (2002)", "Not Free (2002).rights.json"),
              dict(GOOD, licence="CC BY-NC 4.0", licence_url="https://creativecommons.org/licenses/by-nc/4.0/"))
        write(os.path.join(shows, "Space Clips", "rights.json"), GOV)
        video(os.path.join(shows, "Space Clips", "Season 1", "Space Clips S01E01.mp4"))
        write(os.path.join(shows, "Space Clips", "Season 1", "Space Clips S01E01.rights.json"),
              dict(GOV, play_url="https://media.example/clip-1.webm"))
        video(os.path.join(shows, "Space Clips", "Season 1", "Space Clips S01E02.mp4"))    # the show's record: no play_url
        if not store.q1("SELECT 1 FROM users WHERE name = 'demo-admin'"):
            auth.create_user("demo-admin", "password123", admin=True)
        LIB.scan("tests")
        cls.folder = tempfile.mkdtemp(prefix="sofa-demo-folder-")
        os.makedirs(os.path.join(cls.folder, "logos"))
        with open(os.path.join(cls.folder, "logos", "agency.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        with open(os.path.join(cls.folder, "terms.html"), "w") as f:
            f.write("<h1>Terms</h1>")
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.kept_channels = dict(live._channels)
        # signed in before the switch, at home: a cookie that must count for nothing once the demo is on
        req = urllib.request.Request(cls.base + "/api/login", data=json.dumps({"name": "demo-admin", "password": "password123"}).encode(),
                                     headers={"Content-Type": "application/json", "X-Sofa": "1"})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=20) as r:
            cls.admin_cookie = r.headers["Set-Cookie"].split(";")[0]

    @classmethod
    def tearDownClass(cls):
        config.update({"demo": False})
        cls.httpd.shutdown()
        cls.httpd.server_close()
        for d in MADE:
            shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(cls.folder, ignore_errors=True)
        LIB.scan("tests")
        with live._lock:
            live._channels.clear()
            live._channels.update(cls.kept_channels)

    def setUp(self):
        config.update({"demo": True, "demo_folder": self.folder, "demo_serve_files": False, "demo_terms": "terms.html",
                       "demo_privacy": "https://privacy.example/sofa-demo", "share_contact": "dmca@studio.example"})
        demo.forget_limits()
        sharing.settings_changed()
        self.n = 0

    def tearDown(self):
        config.update({"demo": False, "demo_folder": "", "demo_serve_files": False, "demo_terms": "", "demo_privacy": "",
                       "share_contact": ""})
        demo.forget_limits()
        sharing.settings_changed()
        visitor = store.q1("SELECT id FROM users WHERE guest = ?", sharing.VISITOR)
        if visitor:
            store.ex("DELETE FROM sessions WHERE user_id = ?", visitor["id"])

    # ---- requests, as a browser on the internet makes them through the demo's tunnel

    def raw(self, path, cookie=None, body=None, headers=None, ip=None):
        self.n += 1
        h = {"CF-Connecting-IP": ip or "198.51.100.%d" % (self.n % 200 + 1), "CF-Ray": "8a1b2c3d4e5f-LHR"}
        h.update(headers or {})
        if cookie:
            h["Cookie"] = cookie
        if body is not None:
            h.update({"Content-Type": "application/json", "X-Sofa": "1"})
        req = urllib.request.Request(self.base + path, headers=h, data=None if body is None else json.dumps(body).encode())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(req, timeout=20) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def visitor(self, ip=None):
        st, headers, _ = self.raw("/", ip=ip)
        self.assertEqual(st, 302)
        return headers["Set-Cookie"].split(";")[0]

    def get_json(self, path, cookie):
        st, _, body = self.raw(path, cookie)
        self.assertEqual(st, 200, (path, body[:200]))
        return json.loads(body)

    # ---- the switch

    def test_the_switch_locks_every_setting(self):
        # what the guardrails need, by name (a lock taken out of the table fails here, not only in behaviour)
        must = {"retro_eras": False, "share_cinema": False, "archive_channels": False, "live_headers": False,
                "live_playlists": [], "tuners": [], "live_check": False, "signups": False, "guest_access": False, "dlna": False,
                "upnp": False, "trust_proxy": False, "remote": "home", "check_service": "", "tvmaze": False,
                "free_movie_lookup": False, "tmdb_api_key": "", "tidy_library": False, "auto_convert": False, "share_on": True,
                "public_open": True, "defaults_rev": 1}
        for k, v in must.items():
            self.assertIn(k, config.DEMO_LOCKED, k)
            self.assertEqual(config.DEMO_LOCKED[k], v, k)
        config.update({"demo": False})
        contrary = {}
        for k, v in config.DEMO_LOCKED.items():
            contrary[k] = (not v) if isinstance(v, bool) else ([{"name": "x", "url": "https://x.example/l.m3u"}] if isinstance(v, list)
                                                               else "public" if k == "remote" else "letsencrypt" if k == "https"
                                                               else 0 if k == "defaults_rev" else "set")
        try:
            config.update(contrary)                      # config.json says the opposite of every lock
            config.update({"demo": True})
            for k, v in config.DEMO_LOCKED.items():
                self.assertEqual(config.get(k), v, k)
                self.assertEqual(config.all_settings()[k], v, k)
            config.update({k: contrary[k] for k in config.DEMO_LOCKED})    # and nothing changes them while it's on
            for k, v in config.DEMO_LOCKED.items():
                self.assertEqual(config.get(k), v, k)
            # the decades off, with the defaults' revision a home Sofa would otherwise turn them on again with
            self.assertFalse(config.get("retro_eras"))
            self.assertEqual(config.get("defaults_rev"), 1)
            # the environment turns it on with nothing in config.json, and config.json can't turn it off then
            config.update({"demo": False})
            self.assertFalse(config.demo_on())
            with mock.patch.dict(os.environ, {"SOFA_DEMO": "1"}):
                self.assertTrue(config.demo_on())
                self.assertFalse(config.get("signups"))
        finally:
            config.update({"demo": False})
            for k in config.DEMO_LOCKED:                # (back as the other tests expect them)
                config._config[k] = config.DEFAULTS[k]
            config.update({"offline": True, "tvmaze": False, "free_movie_lookup": False, "dlna": False, "previews": False,
                           "trickplay": False, "detect_intros": False, "auto_convert": False})
            config.update({"demo": True})

    # ---- nobody is at home

    def test_nobody_is_at_home_whatever_address_it_comes_from(self):
        def handler(peer, headers=None):
            h = web.Handler.__new__(web.Handler)
            h.client_address = (peer, 50000)
            h.headers = email.message.Message()
            for k, v in (headers or {}).items():
                h.headers[k] = v
            return h
        tunnel = {"CF-Connecting-IP": "203.0.113.7", "CF-Ray": "8a1b-LHR"}
        config.update({"demo": False})
        self.assertEqual(handler("172.18.0.3", {}).network(), "lan")          # a home Sofa: Docker's bridge is home...
        self.assertEqual(handler("172.18.0.3", tunnel).network(), "internet")  # ...but not what a tunnel there passes on (1.5.21)
        config.update({"demo": True})
        for peer in ("172.18.0.3", "192.168.1.20", "100.64.0.5", "127.0.0.1", "::1", "203.0.113.9"):
            for headers in (None, tunnel):
                self.assertEqual(handler(peer, headers).network(), "internet", (peer, headers))
        self.assertEqual(handler("172.18.0.3", tunnel).visitor_key(), "203.0.113.7")     # (for the rate limits only)

    def test_no_admin_setup_sign_in_or_sign_up_from_anywhere(self):
        closed = [("/api/setup", {"name": "boss", "password": "password123"}), ("/api/login", {"name": "demo-admin", "password": "password123"}),
                  ("/api/signup", {"name": "new", "password": "password123"}), ("/api/pair/start", {"name": "TV"}), ("/api/guest", {}),
                  ("/api/profiles/switch", {"id": 1}), ("/api/admin/sharing", {"share_on": False}),
                  ("/api/admin/settings", {"retro_eras": True}), ("/api/admin/live", {"add": {"name": "x", "url": "https://x.example/l.m3u"}}),
                  ("/api/admin/upload?name=a.mp4", {}), ("/api/admin/inbox", {}), ("/api/admin/downloads", {"url": "https://x.example/v"}),
                  ("/api/admin/restart", {})]
        for path, body in closed:
            for via in ({}, {"CF-Connecting-IP": "", "CF-Ray": ""}):      # through the tunnel, and from this computer itself
                st, _, _ = self.raw(path, self.admin_cookie, body=body, headers=via)
                self.assertIn(st, (403, 404), (path, via))
        for path in ("/api/admin/status", "/api/admin/sharing", "/api/admin/report", "/api/profiles", "/guest", "/dlna/device.xml",
                     "/sofa-box/install.sh", "/roku", "/firetv", "/api/admin/upload/check?size=1"):
            self.assertIn(self.raw(path, self.admin_cookie)[0], (403, 404), path)
        # written another way (%-encoded), they reach nothing either: the routes decode, and so does the gate
        cookie = self.visitor()
        for path in ("/api/%68ls/m:open-film:2008?mode=transcode", "/api/%61dmin/status", "/%6cive/0123456789ab/index.m3u8",
                     "/api/%70air/poll?poll=x", "/%67uest", "/api/admin%2fstatus"):
            self.assertIn(self.raw(path, cookie)[0], (403, 404), path)
        for path in ("/api/%6cogin", "/api/%73etup", "/api/%73ignup", "/api/%61dmin/settings"):
            self.assertIn(self.raw(path, cookie, body={"name": "demo-admin", "password": "password123"})[0], (403, 404), path)
        self.assertTrue(self.get_json("/api/info", cookie)["demo"])            # what the compose file's health check asks
        # a cookie from before the switch is nobody's: the plain address makes a visitor of it
        self.assertEqual(self.raw("/", self.admin_cookie)[0], 302)
        cookie = self.visitor()
        with mock.patch.object(auth, "user_count", return_value=0):        # a fresh demo with no accounts at all
            s = self.get_json("/api/session", cookie)
        self.assertFalse(s["needs_setup"])
        self.assertFalse(s["signup"])
        self.assertTrue(s["user"]["visitor"])
        self.assertFalse(s["share"]["home"])            # no "Sign in" for a visitor

    # ---- the library: titles with rights, played as they are from their publisher

    def test_only_titles_with_a_rights_record_that_passes(self):
        cookie = self.visitor()
        lib = self.get_json("/api/library", cookie)
        self.assertEqual([m["title"] for m in lib["movies"]], ["Open Film"])       # not Heat, nor Unrecorded, nor Not Free
        self.assertEqual(lib["movies"][0]["rights"]["licence"], "CC BY 3.0")
        self.assertEqual(lib["movies"][0]["rights"]["credit"], "(c) A Studio")
        self.assertEqual([s["name"] for s in lib["shows"]], ["Space Clips"])
        eps = [e["id"] for se in lib["shows"][0]["seasons"] for e in se["episodes"]]
        self.assertEqual(len(eps), 1)                     # the episode with nowhere to play from isn't listed
        self.assertEqual(lib["shows"][0]["rights"]["licence"], "US government work")
        open_film = lib["movies"][0]["id"]
        plan = self.get_json("/api/play/" + open_film, cookie)
        self.assertEqual((plan["mode"], plan["url"]), ("direct", GOOD["play_url"]))
        self.assertEqual((plan["audio"], plan["subtitles"]), ([], []))
        for other in ("m:heat:1995", "m:unrecorded:2001", "m:not-free:2002"):
            self.assertEqual(self.raw("/api/play/" + other, cookie)[0], 404, other)
        # nothing made for a visitor, and the file only when this server may serve it
        self.assertEqual(self.get_json("/media/%s/trick.json" % open_film, cookie), {"pending": False})
        for kind in ("file", "stream?mode=transcode", "stream?mode=remux", "travel.mp4", "preview.mp4", "trick/0.jpg", "subs/0.vtt"):
            self.assertEqual(self.raw("/media/%s/%s" % (open_film, kind), cookie)[0], 404, kind)
        self.assertEqual(self.raw("/api/hls/%s?mode=transcode" % open_film, cookie)[0], 404)
        config.update({"demo_serve_files": True})
        plan = self.get_json("/api/play/" + open_film, cookie)
        self.assertEqual((plan["mode"], plan["url"]), ("direct", "/media/%s/file" % open_film))
        self.assertEqual(self.raw("/media/%s/file" % open_film, cookie)[0], 200)
        self.assertEqual(self.raw("/media/%s/file?download=1" % open_film, cookie)[0], 404)
        self.assertEqual(self.raw("/media/%s/stream?mode=transcode" % open_film, cookie)[0], 404)
        lib = self.get_json("/api/library", cookie)
        self.assertEqual(sum(len(se["episodes"]) for se in lib["shows"][0]["seasons"]), 2)   # served from here: both

    def test_the_rights_rules(self):
        self.assertEqual(rights.problems(GOOD), [])
        self.assertEqual(rights.problems(GOV), [])
        self.assertEqual(rights.problems(dict(GOOD, licence="CC0 1.0", licence_url="https://creativecommons.org/publicdomain/zero/1.0/",
                                              credit="")), [])
        for bad, why in ((None, "no rights record"), (dict(GOOD, licence="CC BY-NC 4.0"), "isn't one"),
                         (dict(GOOD, licence="CC BY-ND 4.0"), "isn't one"), (dict(GOOD, licence="Fair use"), "isn't one"),
                         (dict(GOOD, credit=""), "no credit"), (dict(GOOD, licence_url="https://example.org/by"), "licence address"),
                         (dict(GOOD, licence="CC BY-SA 4.0"), "different licence"), (dict(GOV, basis=""), "no basis"),
                         (dict(GOOD, source="http://commons.example/x"), "https page"), (dict(GOOD, checked="last week"), "date"),
                         (dict(GOOD, publisher=""), "no publisher"), (dict(GOOD, play_url="http://media.example/x.mp4"), "isn't https")):
            self.assertTrue(any(why in p for p in rights.problems(bad)), (bad, rights.problems(bad)))

    # ---- Live TV

    def channels(self, chans):
        write(os.path.join(self.folder, "channels.json"), {"channels": chans})
        live.refresh(force=True)

    def test_live_tv_only_from_the_checked_list_and_never_relayed(self):
        bad = [dict(CHANNEL, name="Plain http", url="http://streams.agency.example/a.m3u8"),
               dict(CHANNEL, name="Pluto Movies", url="https://service-stitcher.clusters.pluto.tv/v1/x.m3u8"),
               dict(CHANNEL, name="Samsung", url="https://abc.samsung.wurl.tv/playlist.m3u8"),
               dict(CHANNEL, name="Tubi", url="https://live.tubi.video/x.m3u8"),
               dict(CHANNEL, name="Spoofed", user_agent="Mozilla/5.0 (Windows NT 10.0)"),
               dict(CHANNEL, name="Referred", referrer="https://their.site/"),
               dict(CHANNEL, name="Local News [Geo-blocked]", url="https://news.example/l.m3u8"),
               dict(CHANNEL, name="Elsewhere", geo=True, url="https://else.example/l.m3u8"),
               dict(CHANNEL, name="No rights", rights="", url="https://nr.example/l.m3u8"),
               dict(CHANNEL, name="Unchecked", cors=None, url="https://uc.example/l.m3u8"),
               dict(CHANNEL, name="FAST kind", kind="fast", url="https://fk.example/l.m3u8"),
               dict(CHANNEL, name="Far logo", logo="https://tracker.example/logo.png", url="https://fl.example/l.m3u8")]
        for c in bad:
            self.assertTrue(demo.channel_problems(c), c["name"])
        self.assertEqual(demo.channel_problems(dict(CHANNEL, logo="agency.png")), [])
        config._config["live_playlists"] = [{"name": "Added by hand", "url": "https://x.example/list.m3u", "public": True}]
        try:
            self.channels([dict(CHANNEL, logo="agency.png")] + bad)
            cookie = self.visitor()
            out = self.get_json("/api/live", cookie)
            self.assertEqual([c["name"] for c in out["channels"]], ["Agency TV"])
            chan = out["channels"][0]
            self.assertEqual(chan["src"], CHANNEL["url"])          # the browser plays it straight from the publisher
            self.assertEqual((chan["publisher"], chan["rights"]), (CHANNEL["publisher"], CHANNEL["rights"]))
            self.assertEqual(chan["logo"], "/demo/logos/agency.png")
            self.assertEqual(self.raw(chan["logo"], cookie)[0], 200)
            self.assertEqual(out["eras"], [{"id": "now", "name": "Live now"}])        # no decades, no Classic Cinema
            self.assertEqual(out["playlists"], [])
            self.assertEqual(self.get_json("/api/live/guide", cookie)["channels"], [])
            for cid in list(archive.BY_ID)[:3]:
                self.assertEqual(self.raw("/api/live/archive/%s/now" % cid, cookie)[0], 404)
            self.assertFalse(archive.available("ia-cinema1" if "ia-cinema1" in archive.BY_ID else list(archive.BY_ID)[0]))
            # the relay never answers: not the playlist, not a part of it
            self.assertEqual(self.raw("/live/%s/index.m3u8" % chan["id"], cookie)[0], 404)
            self.assertEqual(self.raw("/live/%s/p/%s" % (chan["id"], live.pack(CHANNEL["url"])), cookie)[0], 404)
            # the About page's list: each channel's publisher and rights note
            s = self.get_json("/api/session", cookie)
            self.assertEqual(s["demo"]["channels"], [{"name": "Agency TV", "publisher": CHANNEL["publisher"],
                                                      "rights": CHANNEL["rights"], "page": CHANNEL["page"]}])
            self.assertFalse(s["retro_tv"])
        finally:
            config._config["live_playlists"] = []
            self.channels([])

    # ---- no uploads, Inbox or downloads

    def test_no_inbox(self):
        inbox = config.path("inbox")
        video(os.path.join(inbox, "Dropped.Film.2003.mp4"))
        try:
            with mock.patch.object(organizer, "SETTLE_SECONDS", 0):
                self.assertEqual(organizer.process_inbox(), 0)
                self.assertEqual(organizer.process_inbox(), 0)
            self.assertTrue(os.path.exists(os.path.join(inbox, "Dropped.Film.2003.mp4")))
        finally:
            os.remove(os.path.join(inbox, "Dropped.Film.2003.mp4"))

    # ---- no accounts, ads or trackers

    def test_nothing_from_anywhere_else_and_no_visitor_kept(self):
        st, headers, page = self.raw("/")
        cookie = headers["Set-Cookie"].split(";")[0]
        st, headers, page = self.raw("/", cookie)
        self.assertEqual(st, 200)
        csp = headers["Content-Security-Policy"]
        for part in ("default-src 'self'", "script-src 'self' 'unsafe-inline';", "img-src 'self' data: blob:;", "font-src 'self';",
                     "object-src 'none'", "frame-ancestors 'self'"):
            self.assertIn(part, csp)
        self.assertNotIn("http", csp.replace("https:", ""))        # no host named: nothing of anyone else's may load
        self.assertIn("camera=()", headers["Permissions-Policy"])
        # the app itself names no script, style, font or picture elsewhere
        with open(os.path.join(APP, "client", "index.html"), encoding="utf-8") as f:
            index = f.read()
        self.assertFalse(re.findall(r'<(?:script|link|img)[^>]+(?:src|href)="(?:https?:)?//', index))
        with open(os.path.join(APP, "client", "app.js"), encoding="utf-8") as f:
            app = f.read()
        self.assertFalse(re.findall(r"(?:googletagmanager|google-analytics|doubleclick|facebook\.net|hotjar|segment\.io|"
                                    r"plausible\.io|clarity\.ms|sentry\.io|fonts\.googleapis)", app))
        # a visitor's sign-in keeps neither the address nor the browser
        visitor = sharing.visitor_user()
        rows = store.q("SELECT ip, agent FROM sessions WHERE user_id = ?", visitor["id"])
        self.assertTrue(rows)
        self.assertTrue(all(r["ip"] is None and r["agent"] in (None, "Visitor") for r in rows), [dict(r) for r in rows])
        # the About page's links: the terms (a file in the demo folder) and the privacy notice
        s = self.get_json("/api/session", cookie)
        self.assertEqual((s["demo"]["terms"], s["demo"]["privacy"]), ("/demo/terms", "https://privacy.example/sofa-demo"))
        self.assertEqual(self.raw("/demo/terms", cookie)[2], b"<h1>Terms</h1>")
        self.assertEqual(s["share"]["contact"], "dmca@studio.example")      # where copyright notices go
        self.assertEqual(self.raw("/demo/../config.json", cookie)[0], 404)

    # ---- games

    def test_games_need_no_account_and_have_nowhere_to_talk_to(self):
        cookie = self.visitor()
        self.assertTrue(self.get_json("/api/session", cookie)["share"]["games"])
        st, headers, body = self.raw("/games/games.json", cookie)
        self.assertEqual(st, 200)
        st, headers, _ = self.raw("/games/neon-dodge/", cookie)
        self.assertEqual(st, 200)
        self.assertIn("connect-src 'self';", headers["Content-Security-Policy"])    # nothing but this server, in code
        self.assertIn("form-action 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.raw("/games/probe/", cookie)[0], 404)     # (the box's graphics check: never served here)
        games = os.path.join(APP, "deploy", "sofa-box", "games")
        for d, dirs, names in os.walk(games):
            dirs[:] = [x for x in dirs if x != "probe"]
            for n in names:
                if n.endswith((".js", ".html")):
                    with open(os.path.join(d, n), encoding="utf-8", errors="replace") as f:
                        src = f.read()
                    self.assertFalse(re.search(r"\b(WebSocket|RTCPeerConnection|EventSource)\b|sendBeacon|/api/", src), n)
                    self.assertFalse(re.search(r"fetch\(\s*['\"`]https?:", src), n)

    # ---- rate limits

    def test_rate_limits(self):
        with mock.patch.dict(demo.LIMITS, {"request": (5, 60), "entry": (2, 3600)}):
            demo.forget_limits()
            codes = [self.raw("/api/info", ip="192.0.2.50")[0] for _ in range(7)]
            self.assertEqual(codes, [200] * 5 + [429] * 2)
            self.assertEqual(self.raw("/api/info", ip="192.0.2.51")[0], 200)     # someone else isn't held up
            # the container's own health check, from inside it, isn't counted
            for _ in range(8):
                req = urllib.request.Request(self.base + "/api/info")
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as r:
                    self.assertEqual(r.status, 200)
            # new visitor sign-ins: a few an hour from one address, and a cap for everyone together
            demo.forget_limits()
            self.assertEqual([self.raw("/", ip="192.0.2.60")[0] for _ in range(3)], [302, 302, 429])
            demo.forget_limits()
            with mock.patch.object(demo, "ENTRIES_PER_HOUR", 3):
                self.assertEqual([self.raw("/", ip="192.0.2.%d" % (70 + i))[0] for i in range(4)], [302, 302, 302, 429])

    # ---- the nightly reset

    def test_the_nightly_reset(self):
        cookie = self.visitor()
        visitor = sharing.visitor_user()
        store.ex("UPDATE sessions SET seen = ? WHERE user_id = ?", int(time.time()) - 7200, visitor["id"])   # left two hours ago
        fresh = self.visitor()                           # watching now
        store.ex("INSERT INTO activity (at, kind, message) VALUES (?, 'live', 'x')", int(time.time()))
        store.ex("INSERT INTO progress (user_id, item, t, d, done, at) VALUES (?, 'm:x', 1, 2, 0, 0)", visitor["id"])
        store.ex("INSERT INTO failures (who, at) VALUES ('198.51.100.1', 0)")
        demo.allow("request", "198.51.100.1")
        demo.reset()
        self.assertEqual(demo._hits, {})                 # the rate limits start again
        self.assertEqual(self.raw("/api/library", cookie)[0], 403)        # signed out: the plain address signs in again
        self.assertEqual(self.raw("/api/library", fresh)[0], 200)
        for table in ("activity", "progress", "failures"):
            self.assertIsNone(store.q1("SELECT 1 FROM %s" % table), table)
        # when: the next 04:30 on this computer's clock
        now = time.mktime((2026, 11, 18, 3, 0, 0, 0, 0, -1))
        self.assertEqual(round(demo.seconds_until("04:30", now)), 90 * 60)
        self.assertEqual(round(demo.seconds_until("02:00", now) / 3600), 23)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "the seed tool's videos need ffmpeg")
class SeedTool(unittest.TestCase):
    """tools/demo-seed.py: the library only from titles with a record that passes."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("demo_seed", os.path.join(APP, "tools", "demo-seed.py"))
        cls.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tool)
        cls.dir = tempfile.mkdtemp(prefix="sofa-demo-seed-test-")
        cls.clip = os.path.join(cls.dir, "clip.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i",
                        "sine=frequency=440", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                        cls.clip], check=True, timeout=120)
        cls.raw_clip = os.path.join(cls.dir, "clip.avi")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "2", "-c:v", "mpeg4",
                        cls.raw_clip], check=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_builds_only_what_has_a_record(self):
        lib = os.path.join(self.dir, "library")
        manifest = os.path.join(self.dir, "library.json")
        write(manifest, {"titles": [
            {"kind": "movie", "title": "Open Film", "year": 2008, "summary": "A film.", "file": self.clip, "rights": GOOD},
            {"kind": "movie", "title": "Old Format", "year": 1999, "file": self.raw_clip, "rights": dict(GOV)},
            {"kind": "movie", "title": "Noncommercial", "year": 2010, "file": self.clip,
             "rights": dict(GOOD, licence="CC BY-NC 4.0", licence_url="https://creativecommons.org/licenses/by-nc/4.0/")},
            {"kind": "movie", "title": "No Record", "year": 2011, "file": self.clip},
            {"kind": "movie", "title": "Waiting", "year": 1968, "file": self.clip, "rights": GOV, "hold": "for the lawyer"},
            {"kind": "show", "title": "Space Clips", "rights": GOV,
             "episodes": [{"season": 1, "episode": 1, "title": "One", "file": self.clip, "rights": dict(GOV, play_url="https://m.example/1.webm")}]}]})
        self.assertEqual(self.tool.main(["library", manifest, "--library", lib]), 1)      # (two refused, one not converted)
        movies = sorted(os.listdir(os.path.join(lib, "Movies")))
        self.assertEqual(movies, ["Open Film (2008)"])
        folder = os.path.join(lib, "Movies", "Open Film (2008)")
        self.assertEqual(sorted(os.listdir(folder)), ["Open Film (2008).mp4", "Open Film (2008).rights.json", "folder.jpg", "movie.nfo"])
        with open(os.path.join(folder, "Open Film (2008).rights.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), GOOD)
        self.assertEqual(rights.read(os.path.join(folder, "Open Film (2008).mp4"))["licence"], "CC BY 3.0")
        ep = os.path.join(lib, "Shows", "Space Clips", "Season 1")
        self.assertTrue(os.path.exists(os.path.join(ep, "Space Clips S01E01.rights.json")))
        self.assertTrue(os.path.exists(os.path.join(lib, "Shows", "Space Clips", "rights.json")))
        # converting: a copy browsers play, and the record says so
        self.assertEqual(self.tool.main(["library", manifest, "--library", lib, "--convert"]), 1)
        rec = rights.read(os.path.join(lib, "Movies", "Old Format (1999)", "Old Format (1999).mp4"))
        self.assertIn("Converted to H.264", rec["changes"])
        # check: every video's record, and what's left out
        video(os.path.join(lib, "Movies", "Stray (2000)", "Stray (2000).mp4"))
        out = subprocess.run([sys.executable, os.path.join(APP, "tools", "demo-seed.py"), "check", "--library", lib],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 1)
        j = os.path.join
        self.assertIn("OUT  %s: no rights record" % j("Movies", "Stray (2000)", "Stray (2000).mp4"), out.stdout)
        self.assertIn("OUT  %s: no play_url" % j("Movies", "Old Format (1999)", "Old Format (1999).mp4"), out.stdout)
        self.assertIn("OK   %s" % j("Movies", "Open Film (2008)", "Open Film (2008).mp4"), out.stdout)

    def test_fetch_takes_the_download_address(self):
        lib, manifest = os.path.join(self.dir, "fetched"), os.path.join(self.dir, "fetch.json")
        write(manifest, {"titles": [{"kind": "movie", "title": "Far Film", "year": 2009,
                                     "download_url": "https://media.example/far-film.mp4", "rights": GOOD}]})
        got = []
        def fake_fetch(url, dest, sha256=None):
            got.append((url, os.path.basename(dest)))
            shutil.copyfile(self.clip, dest)
        with mock.patch.object(self.tool, "fetch", fake_fetch):
            self.assertEqual(self.tool.main(["library", manifest, "--library", lib]), 1)       # without --fetch: refused
            self.assertEqual(got, [])
            self.assertEqual(self.tool.main(["library", manifest, "--library", lib, "--fetch"]), 0)
        self.assertEqual(got, [("https://media.example/far-film.mp4", "Far Film (2009).download.mp4")])
        folder = os.path.join(lib, "Movies", "Far Film (2009)")
        self.assertEqual(sorted(os.listdir(folder)), ["Far Film (2009).mp4", "Far Film (2009).rights.json", "folder.jpg", "movie.nfo"])

    def test_the_channel_list_without_asking(self):
        path = os.path.join(self.dir, "channels.json")
        write(path, {"channels": [CHANNEL, dict(CHANNEL, name="Pluto", url="https://x.pluto.tv/a.m3u8")]})
        self.assertEqual(self.tool.main(["channels", path]), 1)

    def test_ours_has_a_passing_record_for_each_title(self):
        with open(os.path.join(APP, "deploy", "demo", "library.json"), encoding="utf-8") as f:
            titles = json.load(f)["titles"]
        self.assertTrue(titles)
        for t in titles:
            self.assertEqual(rights.problems(t["rights"]), [], t["title"])
            self.assertTrue(t["rights"]["play_url"].startswith("https://"), t["title"])
        with open(os.path.join(APP, "deploy", "demo", "channels.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["channels"], [])                 # the owner picks the channels


class InABrowser(unittest.TestCase):
    """The demo in Chrome: the Sofa Box promotion stays off the Live TV page, a title's page shows its rights, and the
    About page lists the channels' publishers."""

    @classmethod
    def setUpClass(cls):
        from tests.test_box_speed import Page, chrome, free_port
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        Demo.setUpClass.__func__(cls)
        config.update({"demo": True, "demo_folder": cls.folder, "demo_terms": "terms.html", "share_contact": "dmca@studio.example"})
        write(os.path.join(cls.folder, "channels.json"), {"channels": [CHANNEL]})
        live.refresh(force=True)
        cls.dir = tempfile.mkdtemp(prefix="sofa-demo-chrome-")
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1280,800",
                                       "--remote-debugging-port=%d" % cls.devtools, "--user-data-dir=" + os.path.join(cls.dir, "profile"),
                                       cls.base + "/"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.page = Page(cls.devtools, "127.0.0.1")

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        cls.chrome.terminate()
        cls.chrome.wait(10)
        shutil.rmtree(cls.dir, ignore_errors=True)
        config.update({"demo_folder": "", "demo_terms": "", "share_contact": ""})
        Demo.tearDownClass.__func__(cls)
        visitor = store.q1("SELECT id FROM users WHERE guest = ?", sharing.VISITOR)
        if visitor:
            store.ex("DELETE FROM sessions WHERE user_id = ?", visitor["id"])

    def go(self, hash_, ready):
        p = self.page
        p.value("location.hash = %s; 1" % json.dumps(hash_))
        for _ in range(300):                              # (30 s: a busy test machine)
            if p.value(ready):
                return p
            time.sleep(0.1)
        raise AssertionError("%s never showed %s" % (hash_, ready))

    def visiting(self):
        for _ in range(300):
            if self.page.value("document.documentElement.classList.contains('visitor')"):
                return
            time.sleep(0.1)
        raise AssertionError("the app never opened as a visitor")

    def test_the_box_promotion_is_off_the_live_tv_page(self):
        self.visiting()
        p = self.go("#/movies", "!!document.querySelector('#view .card, #view .poster-frame, #view [data-play]')")
        self.assertFalse(p.value("document.querySelector('#navSofaBox').hidden"))
        p = self.go("#/live", "document.querySelector('#view h1') && /Live TV/.test(document.querySelector('#view h1').textContent)")
        self.assertTrue(p.value("document.querySelector('#navSofaBox').hidden"))
        self.assertFalse(p.value("[...document.querySelectorAll('#view a')].some(a => /sofabox|Sofa Box/i.test(a.href + a.textContent))"))
        p = self.go("#/sofabox", "!!document.querySelector('#view .sbx')")
        text = p.value("document.querySelector('#view .sbx').textContent")
        self.assertNotIn("Live TV", text)
        self.assertNotIn("open source", text)

    def test_the_games_page_is_a_shelf_of_cards(self):
        """The games in a browser (the demo shares them): the featured one across the top, then rows by kind; a card
        is the game's own picture, its name, a line, its facts, and where it was left; three looks, one markup."""
        self.visiting()
        p = self.go("#/games", "!!document.querySelector('#view .games-page .game-card')")
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "sofa-box", "games", "games.json"), encoding="utf-8") as f:
            cat = json.load(f)
        p.value("localStorage.removeItem('sofa:games:recent'); localStorage.removeItem('sofa.gamesLook'); localStorage.removeItem('shadow-heist'); 1")
        p.value("location.hash = '#/'; 1")
        p = self.go("#/games", "!!document.querySelector('#view .games-page .game-card')")
        self.assertEqual(p.value("document.querySelector('.games-page').dataset.look"), "marquee")
        hero = json.loads(p.value("""(h => JSON.stringify([h.dataset.gamePlay, h.querySelector('.game-kicker').textContent, h.querySelector('.game-hero-pic').getAttribute('src'),
            [...h.querySelectorAll('.game-facts i')].map(i => i.textContent), h.querySelector('.game-go .btn').textContent.trim()]))(document.querySelector('.game-hero'))"""))
        self.assertEqual(hero, [cat["featured"], "Featured", "/games/art/%s.jpg" % cat["featured"], ["Action RPG", "3D", "1 player", "Controller", "Keyboard", "Touch"], "Play"])
        rows = json.loads(p.value("JSON.stringify([...document.querySelectorAll('.games-row')].map(r => [r.dataset.row, [...r.querySelectorAll('.game-card')].map(c => c.dataset.gamePlay)]))"))
        kinds = ["adventure", "action", "racing", "mind", "arcade"]
        self.assertEqual(rows, [[k, [g["id"] for g in cat["games"] if g["shelf"] == k]] for k in kinds])
        card = json.loads(p.value("""(c => JSON.stringify([c.querySelector('b').textContent, c.querySelector('.game-line').textContent, c.querySelector('img').getAttribute('src'),
            c.querySelector('img').loading, c.querySelector('.game-dim').textContent, !!c.querySelector('.game-where')]))(document.querySelector('.game-card[data-game-play="shadow-heist"]'))"""))
        g = next(x for x in cat["games"] if x["id"] == "shadow-heist")
        self.assertEqual(card, [g["name"], g["line"], "/games/art/small/shadow-heist.jpg", "lazy", "2D", False])
        self.assertEqual(p.value("fetch('/games/art/small/shadow-heist.jpg').then(r => r.status + ' ' + r.headers.get('Content-Type'))"), "200 image/jpeg")
        self.assertFalse(p.value("!!document.querySelector('.games-note, .game-ic')"))          # the old cards, and the note that touch can't play
        # where it was left: the game's own save (the shape Shadow Heist keeps), and what was played last comes first
        p.value("localStorage.setItem('shadow-heist', JSON.stringify({ v: 2, best: {}, reached: 4, heists: 6 })); localStorage.setItem('sofa:games:recent', JSON.stringify([{ id: 'shadow-heist' }, { id: 'tidewing' }])); 1")
        p.value("location.hash = '#/'; 1")
        p = self.go("#/games", "!!document.querySelector('#view .games-page .game-card')")
        self.assertEqual(p.value("document.querySelector('.game-hero').dataset.gamePlay + '|' + document.querySelector('.game-hero .game-kicker').textContent + '|' + document.querySelector('.game-hero .game-where').textContent"),
                         "shadow-heist|Pick up where you left it|4 of 12 heists pulled")
        self.assertEqual(p.value("document.querySelector('.game-hero .game-go .btn').textContent.trim()"), "Continue")
        self.assertEqual(p.value("[...document.querySelectorAll('.games-row[data-row=continue] .game-card')].map(c => c.dataset.gamePlay).join()"), "tidewing")
        # three looks: the same cards, laid out another way, kept on this device
        before = p.value("document.querySelector('.games-row[data-row=adventure]').innerHTML")
        wide = p.value("document.querySelector('.games-row[data-row=adventure] .game-card').offsetWidth")
        for look in ("shelf", "index"):
            p.value("document.querySelector('[data-games-look=%s]').click(); 1" % look)
            time.sleep(0.4)
            self.assertEqual(p.value("document.querySelector('.games-page').dataset.look"), look)
            self.assertEqual(p.value("document.querySelector('.games-row[data-row=adventure]').innerHTML"), before, look)
            self.assertNotEqual(p.value("document.querySelector('.games-row[data-row=adventure] .game-card').offsetWidth"), wide, look)
        self.assertEqual(p.value("localStorage.getItem('sofa.gamesLook')"), '"index"')
        # a phone: no sideways scroll in any look
        p.call("Emulation.setDeviceMetricsOverride", {"width": 375, "height": 812, "deviceScaleFactor": 2, "mobile": True})
        for look in ("index", "shelf", "marquee"):
            p.value("document.querySelector('[data-games-look=%s]').click(); 1" % look)
            time.sleep(0.4)
            self.assertLessEqual(p.value("document.documentElement.scrollWidth"), 375, look)
        p.call("Emulation.clearDeviceMetricsOverride")
        p.value("localStorage.removeItem('sofa:games:recent'); localStorage.removeItem('sofa.gamesLook'); localStorage.removeItem('shadow-heist'); 1")

    def test_a_titles_page_shows_its_rights_and_about_shows_the_channels(self):
        self.visiting()
        p = self.go("#/movies", "!!document.querySelector('#view a[href^=\"#/movie/\"]')")
        p = self.go(p.value("document.querySelector('#view a[href^=\"#/movie/\"]').getAttribute('href')"),
                    "!!document.querySelector('#view .rights')")
        text = p.value("document.querySelector('#view .rights').textContent")
        for part in ("CC BY 3.0", "A Studio", "(c) A Studio", "checked 2026-11-18"):
            self.assertIn(part, text)
        self.assertFalse(p.value("!!document.querySelector('#view [data-download]')"))
        p = self.go("#/show/s:space-clips", "!!document.querySelector('#view .episodes') && !!document.querySelector('#view .rights')")
        self.assertIn("US government work", p.value("document.querySelector('#view .rights').textContent"))
        p = self.go("#/about", "!!document.querySelector('#view .about-chans')")
        text = p.value("document.querySelector('#view .about-body').textContent")
        self.assertIn("Agency TV", text)
        self.assertIn(CHANNEL["rights"], text)
        self.assertIn("Terms", text)
        self.assertIn("dmca@studio.example", text)                       # where copyright notices go
        self.assertIn("free to show", text)
