"""Watching together: the room's timeline and its rules (sofa/together.py), then the same through the running server:
who may start, join and steer, a Kids profile and the titles its rules allow, guests and Visitors kept out."""
import os
import threading
import time
import unittest
from unittest import mock

from tests import LIBRARY, video
from tests.test_access import Client
from sofa import auth, config, kids, sharing, store, together, web
from sofa.library import LIBRARY as LIB

HOST = {"id": 9001, "name": "wt-host", "admin": False, "adult": False, "kids": False, "avatar": 1}
SECOND = {"id": 9002, "name": "wt-second", "admin": False, "adult": False, "kids": False, "avatar": 2}
KID = {"id": 9003, "name": "wt-kid", "admin": False, "adult": False, "kids": True, "avatar": 3}


class Clock:
    """Sofa's clock for rooms, moved by hand."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Room(unittest.TestCase):
    def setUp(self):
        together.reset()
        self.clock = Clock()
        patcher = mock.patch.object(together, "clock", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(together.reset)

    def start(self, **kw):
        return together.start(HOST, "tab-host", "Living room TV", kw.pop("item", "m:heat:1995"), **kw)

    def test_a_room_keeps_one_timeline_on_sofas_clock(self):
        r = self.start(pos=120.0)
        self.assertEqual(len(r["code"]), 6)
        self.assertTrue(set(r["code"]) <= set(together.LETTERS))
        self.assertTrue(r["is_host"] and r["may_steer"])
        self.clock.t += 10
        joined = together.join(SECOND, "tab-second", "iPhone", r["code"].lower())       # (a code typed in lower case works)
        # where the video is now: where it was, plus the time since, at its speed
        self.assertAlmostEqual(joined["pos"] + (joined["now"] - joined["at"]) * joined["rate"], 130.0, places=3)
        together.steer(HOST, "tab-host", r["code"], "pause", t=131.5)
        self.clock.t += 30
        v = together.join(SECOND, "tab-second", "iPhone", r["code"])
        self.assertTrue(v["paused"])
        self.assertEqual(v["pos"], 131.5)                                             # paused: it stays put
        together.steer(HOST, "tab-host", r["code"], "rate", t=131.5, rate=1.5)
        together.steer(HOST, "tab-host", r["code"], "play", t=131.5)
        self.clock.t += 10
        self.assertAlmostEqual(together._position(together._rooms[r["code"]]), 146.5, places=3)

    def test_only_the_host_steers_unless_the_host_says_everyone(self):
        r = self.start()
        together.join(SECOND, "tab-second", "iPhone", r["code"])
        with self.assertRaises(together.Refused) as e:
            together.steer(SECOND, "tab-second", r["code"], "pause", t=5)
        self.assertEqual((e.exception.status, e.exception.message), (403, "wt-host is steering this room."))
        with self.assertRaises(together.Refused):
            together.steer(SECOND, "tab-second", r["code"], "everyone", everyone=True)   # not theirs to choose
        together.steer(HOST, "tab-host", r["code"], "everyone", everyone=True)
        v = together.steer(SECOND, "tab-second", r["code"], "seek", t=600)
        self.assertEqual((v["pos"], v["may_steer"], v["last"]["by"], v["last"]["act"]), (600, True, "wt-second", "seek"))

    def test_what_a_screen_sends_is_checked(self):
        r = self.start()
        for kw in ({"act": "seek", "t": -1}, {"act": "seek", "t": float("nan")}, {"act": "rate", "rate": 9},
                   {"act": "rate", "rate": "fast"}, {"act": "dance"}):
            with self.assertRaises(together.Refused, msg=kw):
                together.steer(HOST, "tab-host", r["code"], **kw)

    def test_the_host_leaving_hands_the_room_on_and_ending_it_tells_everyone(self):
        r = self.start()
        together.join(SECOND, "tab-second", "iPhone", r["code"])
        self.clock.t += 1
        together.join(KID, "tab-kid", "Fire TV", r["code"])
        together.leave(HOST, "tab-host", r["code"])
        v = together.wait(SECOND, "tab-second", r["code"], -1)
        self.assertEqual((v["host"], v["is_host"], v["last"]["act"]), ("wt-second", True, "host"))     # the first to join
        self.assertEqual(together.wait(HOST, "tab-host", r["code"], -1), {"gone": "You left the room."})
        with self.assertRaises(together.Refused):
            together.leave(KID, "tab-kid", r["code"], end=True)                    # only the host ends it
        together.leave(SECOND, "tab-second", r["code"], end=True)
        self.assertEqual(together.wait(KID, "tab-kid", r["code"], -1), {"gone": "wt-second ended the room."})
        with self.assertRaises(together.Refused) as e:
            together.join(KID, "tab-kid", "Fire TV", r["code"])
        self.assertEqual(e.exception.status, 410)

    def test_a_screen_not_heard_from_is_taken_out_and_an_empty_room_ends(self):
        r = self.start()
        together.join(SECOND, "tab-second", "iPhone", r["code"])
        self.clock.t += together.GONE - 5
        with mock.patch.object(together, "WAIT", 0):
            together.wait(HOST, "tab-host", r["code"], 10 ** 6)                  # the host is still there
        self.clock.t += 10
        v = together.join(HOST, "tab-host", "Living room TV", r["code"])
        self.assertEqual([m["name"] for m in v["members"]], ["wt-host"])
        self.assertEqual(together.wait(SECOND, "tab-second", r["code"], -1)["gone"], "You were away too long, so you left the room.")
        self.clock.t += together.GONE + 1
        self.assertEqual(together.rooms_of(HOST["id"]), [])
        self.assertIn("ended", together.wait(HOST, "tab-host", r["code"], -1)["gone"])

    def test_a_wait_is_answered_the_moment_the_room_changes(self):
        r = self.start()
        together.join(SECOND, "tab-second", "iPhone", r["code"])
        rev = together.wait(SECOND, "tab-second", r["code"], -1)["rev"]                 # behind: at once
        got = {}

        def waiting():
            started = time.time()
            got["view"], got["took"] = together.wait(SECOND, "tab-second", r["code"], rev), time.time() - started
        th = threading.Thread(target=waiting)
        th.start()
        time.sleep(0.3)
        together.steer(HOST, "tab-host", r["code"], "pause", t=42)
        th.join(5)
        self.assertTrue(got["view"]["paused"])
        self.assertEqual(got["view"]["pos"], 42)
        self.assertLess(got["took"], 2)

    def test_another_title_takes_out_whoever_may_not_watch_it(self):
        r = self.start(item="e:bluey:1:1")
        together.join(KID, "tab-kid", "Fire TV", r["code"])
        together.join(SECOND, "tab-second", "iPhone", r["code"])
        may_see = lambda user, item: not user.get("kids") or item.startswith("e:bluey")    # noqa: E731
        v = together.steer(HOST, "tab-host", r["code"], "item", item="m:heat:1995", may_see=may_see)
        self.assertEqual((v["item"], v["pos"], v["paused"]), ("m:heat:1995", 0, False))
        self.assertEqual([m["name"] for m in v["members"]], ["wt-host", "wt-second"])
        self.assertEqual(together.wait(KID, "tab-kid", r["code"], -1),
                         {"gone": "The room moved on to something this profile can't watch."})

    def test_a_screen_asking_again_lets_its_earlier_wait_go(self):
        r = self.start()
        got = {}
        th = threading.Thread(target=lambda: got.update(v=together.wait(HOST, "tab-host", r["code"], 10 ** 6)))
        th.start()
        time.sleep(0.3)
        started = time.time()
        with mock.patch.object(together, "WAIT", 0):
            together.wait(HOST, "tab-host", r["code"], 10 ** 6)          # the page asked again (after a refused press)
        th.join(5)
        self.assertLess(time.time() - started, 2)
        self.assertEqual(got["v"]["code"], r["code"])

    def test_wrong_codes_are_counted(self):
        self.start()
        for _ in range(together.MISSES):
            with self.assertRaises(together.Refused) as e:
                together.peek(SECOND, "ZZZZZZ")
            self.assertEqual(e.exception.status, 404)
        with self.assertRaises(together.Refused) as e:
            together.peek(SECOND, "ZZZZZZ")
        self.assertEqual(e.exception.status, 429)

    def test_one_screen_one_room(self):
        a = self.start()
        b = together.start(HOST, "tab-host", "Living room TV", "m:heat:1995")
        self.assertNotEqual(a["code"], b["code"])
        self.assertEqual(together.rooms_of(HOST["id"]), [b["code"]])             # (the first ended: nobody left in it)


class ThroughTheServer(unittest.TestCase):
    """The routes in sofa/web.py: who's let in, and what each one sees."""

    @classmethod
    def setUpClass(cls):
        video(os.path.join(LIBRARY, "Shows", "Bluey", "Season 1", "Bluey S01E01.mp4"))
        video(os.path.join(LIBRARY, "Movies", "Heat (1995)", "Heat (1995).mp4"))
        video(os.path.join(LIBRARY, "Adult", "Movies", "After Hours (2001)", "After Hours (2001).mp4"))
        LIB.scan("tests")
        cls.adult = next(k for k, i in LIB.items.items() if i.get("adult"))
        cls.bluey = next(k for k, i in LIB.items.items() if i.get("kind") == "episode" and "bluey" in k)
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        for name in ("wt-host", "wt-second", "wt-kid", "wt-grown"):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123")
        cls.ids = {r["name"]: r["id"] for r in store.q("SELECT id, name FROM users WHERE name LIKE 'wt-%'")}
        auth.set_kids(cls.ids["wt-kid"], True)
        auth.set_adult(cls.ids["wt-grown"], True)
        kids.choose("s:bluey", True)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        together.reset()

    def setUp(self):
        together.reset()

    def signed_in(self, name):
        c = Client(self.base)
        self.assertEqual(c.call("/api/login", {"name": name, "password": "password123"})[0], 200)
        return c

    def test_start_join_steer_and_follow(self):
        host, second = self.signed_in("wt-host"), self.signed_in("wt-second")
        status, room = host.call("/api/together", {"tab": "tab-host", "device": "TV", "item": "m:heat:1995", "t": 61.5})
        self.assertEqual(status, 200, room)
        code = room["code"]
        self.assertIsNone(room["away"])                               # (this Sofa doesn't answer the internet)
        status, peek = second.call("/api/together/" + code)
        self.assertEqual((status, peek["item"], peek["host"]), (200, "m:heat:1995", "wt-host"))
        status, joined = second.call("/api/together/%s/join" % code, {"tab": "tab-second", "device": "iPhone"})
        self.assertEqual((status, joined["is_host"], joined["may_steer"]), (200, False, False))
        self.assertEqual([m["name"] for m in joined["members"]], ["wt-host", "wt-second"])
        self.assertEqual(second.call("/api/together/%s/steer" % code, {"tab": "tab-second", "act": "pause", "t": 70})[0], 403)
        self.assertEqual(host.call("/api/together/%s/steer" % code, {"tab": "tab-host", "act": "pause", "t": 70.25})[0], 200)
        status, news = second.call("/api/together/%s/wait?tab=tab-second&since=%d" % (code, joined["rev"]))
        self.assertEqual((status, news["paused"], news["pos"], news["last"]["act"]), (200, True, 70.25, "pause"))
        self.assertEqual([(m["name"], m["host"], m["you"]) for m in news["members"]], [("wt-host", True, False), ("wt-second", False, True)])
        self.assertIsInstance(second.call("/api/together/clock")[1]["now"], float)
        self.assertEqual(second.call("/api/together/%s/leave" % code, {"tab": "tab-second"})[0], 200)
        self.assertEqual(second.call("/api/together/%s/wait?tab=tab-second&since=0" % code)[1], {"gone": "You left the room."})
        self.assertEqual(host.call("/api/together", {"tab": "x", "item": "m:heat:1995"})[0], 400)          # which screen?
        self.assertEqual(host.call("/api/together", {"tab": "tab-host", "item": "m:nothing:1"})[0], 404)

    def test_a_kids_profile_joins_only_rooms_its_rules_allow(self):
        host, kid = self.signed_in("wt-host"), self.signed_in("wt-kid")
        heat = host.call("/api/together", {"tab": "tab-host", "item": "m:heat:1995"})[1]["code"]
        status, body = kid.call("/api/together/" + heat)
        self.assertEqual(status, 403)
        self.assertNotIn("Heat", str(body))                           # (and not what it is)
        self.assertEqual(kid.call("/api/together/%s/join" % heat, {"tab": "tab-kid"})[0], 403)
        bluey = host.call("/api/together", {"tab": "tab-host", "item": self.bluey})[1]["code"]
        self.assertEqual(kid.call("/api/together/%s/join" % bluey, {"tab": "tab-kid"})[0], 200)
        # the host puts on something else: the Kids profile is out of the room, and told why
        self.assertEqual(host.call("/api/together/%s/steer" % bluey, {"tab": "tab-host", "act": "item", "item": "m:heat:1995"})[0], 200)
        self.assertEqual(kid.call("/api/together/%s/wait?tab=tab-kid&since=0" % bluey)[1],
                         {"gone": "The room moved on to something this profile can't watch."})
        # nor can a Kids profile steer a room it may steer into a title it can't watch
        kid_room = kid.call("/api/together", {"tab": "tab-kid", "item": self.bluey})[1]["code"]
        self.assertEqual(kid.call("/api/together/%s/steer" % kid_room, {"tab": "tab-kid", "act": "item", "item": "m:heat:1995"})[0], 404)
        self.assertEqual(kid.call("/api/together", {"tab": "tab-kid", "item": "m:heat:1995"})[0], 404)

    def test_never_a_title_from_the_adult_section(self):
        grown = self.signed_in("wt-grown")
        self.assertTrue(grown.call("/api/session")[1]["user"]["adult"])                 # (theirs to watch, alone)
        self.assertIn(self.adult.split(":")[1], str(grown.call("/api/library")[1].get("adult")))
        self.assertEqual(grown.call("/api/together", {"tab": "tab-grown", "item": self.adult})[0], 404)
        code = grown.call("/api/together", {"tab": "tab-grown", "item": "m:heat:1995"})[1]["code"]
        self.assertEqual(grown.call("/api/together/%s/steer" % code, {"tab": "tab-grown", "act": "item", "item": self.adult})[0], 404)

    def test_guests_and_visitors_are_never_let_in(self):
        host = self.signed_in("wt-host")
        code = host.call("/api/together", {"tab": "tab-host", "item": "m:heat:1995"})[1]["code"]
        guest = Client(self.base, token=auth.start_session(auth.guest_user()["id"], "127.0.0.1", "test"))
        before = {k: config.get(k) for k in ("share_on", "share_all")}
        config.update({"share_on": True, "share_all": True})
        try:
            visitor = Client(self.base, token=auth.start_session(sharing.visitor_user()["id"], "127.0.0.1", "test", label="Visitor"))
            for who in (guest, visitor):
                self.assertEqual(who.call("/api/together/" + code)[0], 403)
                self.assertEqual(who.call("/api/together/%s/join" % code, {"tab": "tab-out"})[0], 403)
                self.assertEqual(who.call("/api/together", {"tab": "tab-out", "item": "m:heat:1995"})[0], 403)
                self.assertEqual(who.call("/api/together/%s/wait?tab=tab-out&since=0" % code)[0], 403)
        finally:
            config.update(before)
        self.assertEqual(len(together.join({"id": self.ids["wt-host"], "name": "wt-host"}, "tab-host", "", code)["members"]), 1)

    def test_a_link_from_away_when_sofa_answers_the_internet(self):
        host = self.signed_in("wt-host")
        before = {k: config.get(k) for k in ("domain", "remote")}
        config.update({"domain": "sofa.example.net", "remote": "public"})
        try:
            with mock.patch.object(web.tls, "trusted", return_value=True):
                room = host.call("/api/together", {"tab": "tab-host", "item": "m:heat:1995"})[1]
            self.assertEqual(room["away"], "https://sofa.example.net")
        finally:
            config.update(before)


if __name__ == "__main__":
    unittest.main()
