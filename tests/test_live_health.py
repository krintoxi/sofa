"""Live TV's channels that don't answer: found, remembered, left out, and back when they're back."""
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import auth, config, dlna, live, store, web

CHANNELS = ("good", "gone", "noparts", "qualities", "raw", "empty", "starred")


class Air(BaseHTTPRequestHandler):
    """A channel list as a tuner at home serves it: channels that play, and ones that don't in different ways."""
    base = ""
    dead = set()                # paths that answer 404 for now
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        Air.seen.append(self.path)
        hls = "application/vnd.apple.mpegurl"
        if self.path in Air.dead:
            body = None
        elif self.path == "/list.m3u":
            body, ctype = "#EXTM3U\n" + "".join(
                '#EXTINF:-1 group-title="News",%s\n%s/%s/%s\n' % (c.title(), self.base, c, "feed.ts" if c == "raw" else "index.m3u8")
                for c in CHANNELS), "audio/x-mpegurl"
        elif self.path == "/qualities/index.m3u8":      # a list of qualities, each its own list of parts
            body, ctype = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nlow/index.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2000000\nhigh/index.m3u8\n", hls
        elif self.path == "/empty/index.m3u8":
            body, ctype = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n", hls
        elif self.path.endswith("/index.m3u8") and self.path.split("/")[1] in ("good", "gone", "noparts", "qualities", "starred"):
            body, ctype = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nseg1.ts\n#EXTINF:4,\nseg2.ts\n", hls
        elif self.path.endswith(".ts") and not self.path.startswith("/noparts/"):
            body, ctype = "G" * 188, "video/mp2t"
        else:
            body = None
        if body is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Someone:
    def __init__(self, base, name):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))
        self.call("/api/login", {"name": name, "password": "password123"})

    def call(self, path, data=None):
        req = urllib.request.Request(self.base + path, None if data is None else json.dumps(data).encode(),
                                     {"Content-Type": "application/json", "X-Sofa": "1"})
        try:
            with self.opener.open(req, timeout=30) as r:
                body = r.read()
                return r.status, json.loads(body) if body[:1] in (b"{", b"[") else body
        except urllib.error.HTTPError as e:
            return e.code, e.read()


class ChannelsThatDontAnswer(unittest.TestCase):
    def setUp(self):
        Air.dead, Air.seen = {"/gone/index.m3u8"}, []
        self.up = ThreadingHTTPServer(("127.0.0.1", 0), Air)
        Air.base = "http://127.0.0.1:%d" % self.up.server_address[1]
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        self.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.before = {k: config.get(k) for k in ("offline", "live_playlists", "live_check", "archive_channels")}
        config.update({"offline": False, "live_check": True, "archive_channels": False,
                       "live_playlists": [{"name": "Tuner", "url": Air.base + "/list.m3u"}]})
        for name, admin in (("air-admin", True), ("air-viewer", False)):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123", admin=admin)
        self.admin, self.viewer = Someone(self.base, "air-admin"), Someone(self.base, "air-viewer")
        self.times = (live.CHECK_AGAIN, live.CHECK_DOWN_EVERY, live.CHECK_OK_EVERY)
        self.forget()
        self.assertEqual(live.refresh(force=True), len(CHANNELS))
        self.ids = {c["name"].lower(): c["id"] for c in live.all_channels()}

    def forget(self):
        live._health.clear()
        live._streak.clear()
        del live._first[:]
        live._health_state.update(loaded=True, wanted=0.0, asked={}, dirty=False)

    def tearDown(self):
        live.CHECK_AGAIN, live.CHECK_DOWN_EVERY, live.CHECK_OK_EVERY = self.times
        store.ex("DELETE FROM live_favorites WHERE channel IN (%s)" % ",".join("?" * len(self.ids)), *self.ids.values())
        config.update(self.before)
        self.forget()
        live.refresh()
        self.httpd.shutdown()
        self.up.shutdown()

    def names(self, who, path="/api/live"):
        status, out = who.call(path)
        self.assertEqual(status, 200)
        return sorted(c["name"].lower() for c in out["channels"]), out

    def look(self):
        return live.check_some(pause=0)

    def test_a_look_tells_what_plays_from_what_doesnt(self):
        verdict = {name: live.probe(live.channel(cid), timeout=5) for name, cid in self.ids.items()}
        for name in ("good", "qualities", "raw", "starred"):
            self.assertEqual(verdict[name], (True, ""), name)
        self.assertEqual(verdict["gone"], (False, "it answered 404"))
        self.assertEqual(verdict["noparts"], (False, "it answered 404"))          # its list is there, its video isn't
        self.assertEqual(verdict["empty"], (False, "its playlist is empty"))
        # the newest part of one quality, not the whole channel: a look is a handful of small requests
        Air.seen = []
        live.probe(live.channel(self.ids["qualities"]), timeout=5)
        self.assertEqual(Air.seen, ["/qualities/index.m3u8", "/qualities/low/index.m3u8", "/qualities/low/seg2.ts"])
        closed = dict(live.channel(self.ids["good"]), url="http://127.0.0.1:9/index.m3u8")
        self.assertEqual(live.probe(closed, timeout=3), (False, "it can't be reached"))
        out = dict(live.channel(self.ids["good"]), home=False)                    # from a list on the internet: never home
        self.assertEqual(live.probe(out, timeout=3), (False, "it leads to the home network"))

    def test_nothing_is_looked_at_until_someone_opens_live_tv(self):
        Air.seen = []
        self.assertEqual(self.look(), 0)
        self.assertEqual(Air.seen, [])
        every, out = self.names(self.viewer)
        self.assertEqual(every, sorted(CHANNELS))                                 # nothing known yet: everything listed
        self.assertNotIn("down", out)                                             # (how many are gone: the admin's to know)
        self.assertNotIn("health", out)
        self.assertEqual(self.look(), len(CHANNELS))
        live._health_state["wanted"] -= live.WANTED_FOR + 60                      # a week and more without Live TV
        live.CHECK_OK_EVERY = live.CHECK_AGAIN = 0
        self.assertEqual(self.look(), 0)

    def test_left_out_after_two_looks_and_back_when_it_answers(self):
        self.names(self.viewer)
        self.look()
        self.assertEqual(self.names(self.viewer)[0], sorted(CHANNELS))            # one missed look isn't "gone" yet
        self.assertEqual(self.look(), 0)                                          # (and the second look isn't due at once)
        live.CHECK_AGAIN = 0
        self.assertEqual(self.look(), 3)                                          # only the three that missed
        gone = ["empty", "gone", "noparts"]
        listed, out = self.names(self.viewer)
        self.assertEqual(listed, sorted(set(CHANNELS) - set(gone)))
        listed, out = self.names(self.admin)
        self.assertEqual(listed, sorted(set(CHANNELS) - set(gone)))
        self.assertEqual(out["down"], 3)
        self.assertEqual({k: out["health"][k] for k in ("on", "total", "checked", "down")},
                         {"on": True, "total": len(CHANNELS), "checked": len(CHANNELS), "down": 3})
        listed, out = self.names(self.admin, "/api/live?down=1")                  # "show them anyway"
        self.assertEqual(listed, sorted(CHANNELS))
        self.assertEqual(sorted(c["name"].lower() for c in out["channels"] if c.get("down")), gone)
        self.assertEqual(self.names(self.viewer, "/api/live?down=1")[0], sorted(set(CHANNELS) - set(gone)))   # an admin's only
        self.assertEqual(sorted(c["name"].lower() for c in live.all_channels(with_down=False)),
                         sorted(set(CHANNELS) - set(gone)))                        # a TV's list (DLNA) too
        self.assertEqual(len(live.all_channels()), len(CHANNELS))
        Air.dead = set()                                                          # "gone" is back on air
        self.assertEqual(self.look(), 0)                                          # (looked at again later, not at once)
        live.CHECK_DOWN_EVERY = 0
        self.assertEqual(self.look(), 3)
        self.assertEqual(self.names(self.viewer)[0], sorted(set(CHANNELS) - {"empty", "noparts"}))

    def test_a_favourite_stays_with_a_mark(self):
        self.assertEqual(self.viewer.call("/api/live/favorite/" + self.ids["starred"], {"on": True})[0], 200)
        Air.dead = {"/gone/index.m3u8", "/starred/index.m3u8"}
        self.names(self.viewer)
        live.CHECK_AGAIN = 0
        self.look(), self.look()
        listed, out = self.names(self.viewer)
        self.assertIn("starred", listed)
        self.assertNotIn("gone", listed)
        self.assertTrue(next(c for c in out["channels"] if c["name"] == "Starred")["down"])
        self.assertNotIn("starred", self.names(self.admin)[0])                    # (someone else's favourite, not theirs)

    def test_tuning_in_to_one_that_doesnt_answer_leaves_it_out_at_once(self):
        self.assertEqual(self.viewer.call("/live/%s/index.m3u8" % self.ids["gone"])[0], 502)
        self.assertNotIn("gone", self.names(self.viewer)[0])
        # a part that doesn't come says less: Sofa looks itself, next, and then it's out
        status, text = self.viewer.call("/live/%s/index.m3u8" % self.ids["noparts"])
        self.assertEqual(status, 200)
        part = [ln for ln in text.decode().splitlines() if ln and not ln.startswith("#")][0]
        self.assertEqual(self.viewer.call(part)[0], 502)
        self.assertIn("noparts", self.names(self.viewer)[0])
        live._health_state["wanted"] = 0.0                                        # (even with nobody else on Live TV)
        Air.seen = []
        self.assertEqual(self.look(), 1)
        self.assertNotIn("noparts", self.names(self.viewer)[0])
        # and one that plays, played: on air, whatever was known
        live.mark(self.ids["good"], False, "it answered 404", at_once=True)
        self.assertNotIn("good", self.names(self.viewer)[0])
        status, text = self.viewer.call("/live/%s/index.m3u8" % self.ids["good"])
        part = [ln for ln in text.decode().splitlines() if ln and not ln.startswith("#")][0]
        self.assertEqual(self.viewer.call(part)[0], 200)
        self.assertIn("good", self.names(self.viewer)[0])

    def test_a_viewer_saying_it_didnt_play_makes_sofa_look_itself(self):
        status, out = self.viewer.call("/api/live/failed/" + self.ids["good"], {})
        self.assertEqual((status, out["looking"]), (200, True))
        self.assertEqual(self.viewer.call("/api/live/failed/" + self.ids["good"], {})[1]["looking"], False)   # once a minute
        self.viewer.call("/api/live/failed/" + self.ids["empty"], {})
        self.assertEqual(self.look(), 2)                                          # those two, first, and nothing else
        listed = self.names(self.viewer)[0]
        self.assertIn("good", listed)                                             # it plays: their word didn't hide it
        self.assertNotIn("empty", listed)                                         # it doesn't: out at once
        self.assertEqual(self.viewer.call("/api/live/failed/000000000000", {})[0], 404)

    def test_switched_off_or_offline_nothing_is_looked_at_or_left_out(self):
        self.names(self.viewer)
        live.CHECK_AGAIN = 0
        self.look(), self.look()
        self.assertEqual(len(self.names(self.viewer)[0]), len(CHANNELS) - 3)
        for change in ({"live_check": False}, {"live_check": True, "offline": True}):
            config.update(change)
            Air.seen = []
            live.CHECK_OK_EVERY = live.CHECK_DOWN_EVERY = 0
            self.assertEqual(self.look(), 0)
            self.assertEqual(Air.seen, [])
            self.assertEqual(len(live.all_channels(with_down=False)), len(CHANNELS))
            self.assertFalse(live.health()["on"])
        config.update({"offline": False})
        self.assertEqual(self.admin.call("/api/admin/settings", {"live_check": False})[0], 200)
        self.assertEqual(self.names(self.viewer)[0], sorted(CHANNELS))
        self.assertEqual(self.viewer.call("/api/admin/settings", {"live_check": True})[0], 403)

    def test_the_homes_connection_going_off_marks_nothing(self):
        sites = ["one.example", "two.example", "three.example", "four.example", "five.example"]
        for i, site in enumerate(sites):
            live._channels["%012x" % i] = {"id": "%012x" % i, "name": "Far %d" % i, "url": "https://%s/a.m3u8" % site,
                                           "group": "News", "headers": {}, "home": False}
        self.addCleanup(lambda: [live._channels.pop("%012x" % i, None) for i in range(len(sites))])
        live.mark("%012x" % 0, True)
        for i in range(3):
            self.assertTrue(live.mark("%012x" % i, False, "it can't be reached", at_once=True))
        self.assertTrue(live.down("%012x" % 1))
        self.assertFalse(live.cut_off())
        self.assertFalse(live.mark("%012x" % 3, False, "it took too long", at_once=True))   # the fourth site in a row
        self.assertTrue(live.cut_off())
        self.assertEqual([live.down("%012x" % i) for i in range(4)], [False] * 4)  # ...and the first three taken back
        self.assertTrue(live._health["%012x" % 0]["ok"])                           # (as it was known before)
        self.assertFalse(live.mark("%012x" % 4, False, "it can't be reached"))
        self.assertTrue(live.mark("%012x" % 4, False, "it answered 404", at_once=True))   # an answer: the connection is up
        self.assertFalse(live.cut_off())
        self.assertTrue(live.down("%012x" % 4))
        for _ in range(6):                                                        # one dead site, tried again and again,
            live.mark("%012x" % 1, False, "it can't be reached", at_once=True)    # isn't "the connection is off"
        self.assertFalse(live.cut_off())
        self.assertTrue(live.down("%012x" % 1))

    def test_whats_known_is_kept_and_names_nobody(self):
        self.names(self.viewer)
        live.CHECK_AGAIN = 0
        self.look(), self.look()
        with open(live.HEALTH, encoding="utf-8") as f:
            saved = f.read()
        for name in CHANNELS:                                                     # ids and verdicts: no names, no addresses
            self.assertNotIn(name.title(), saved)
        self.assertNotIn("127.0.0.1", saved)
        live._health.clear()
        live._health_state["loaded"] = False
        self.assertTrue(live.down(self.ids["gone"]))                              # read again after a restart
        self.assertFalse(live.down(self.ids["good"]))
        self.assertFalse(any("Gone" in (a.get("message") or "") for a in store.recent_activity(50)))
        self.assertFalse(os.path.exists(live.HEALTH + ".tmp"))

    def test_a_number_is_the_same_channel_for_everyone(self):
        """A channel's number on the dial doesn't depend on who looks: an adult channel between two others leaves a gap
        for a profile that can't see it, not a shift."""
        mine = live._channels
        cid = "a" * 12
        mine[cid] = {"id": cid, "name": "Gold", "group": "News", "url": Air.base + "/good/index.m3u8", "headers": {},
                     "home": True, "adult": True, "playlist": "Tuner", "logo": None, "lists": [Air.base + "/list.m3u"]}
        try:
            for n, c in enumerate(sorted(mine.values(), key=lambda c: (c["group"].lower(), c["name"].lower(), c["id"]))):
                c["number"] = live.FIRST_NUMBER + n
            uid = store.q1("SELECT id FROM users WHERE name = 'air-viewer'")["id"]
            plain = {c["name"]: c["number"] for c in live.listing(uid)["channels"]}
            grown = {c["name"]: c["number"] for c in live.listing(uid, adult=True)["channels"]}
            self.assertNotIn("Gold", plain)
            self.assertEqual({k: grown[k] for k in plain}, plain)
            self.assertEqual(len(set(grown.values())), len(grown))
        finally:
            mine.pop(cid, None)
        live.refresh()                                                            # the lists read again: numbered afresh
        self.assertEqual(sorted(c["number"] for c in live.listing(0)["channels"]),
                         list(range(live.FIRST_NUMBER, live.FIRST_NUMBER + len(CHANNELS))))   # (as read: 101 on, no gaps)

    def test_a_tv_on_the_network_gets_only_the_ones_that_answer(self):
        self.names(self.viewer)
        live.CHECK_AGAIN = 0
        self.look(), self.look()
        self.assertTrue(hasattr(dlna, "live"))
        self.assertEqual(len(live.all_channels(with_down=False)), len(CHANNELS) - 3)


if __name__ == "__main__":
    unittest.main()
