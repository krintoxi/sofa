"""The server as apps and browsers see it: signing in, pairing, the library, Kids profiles, the phone
remote, privacy. A real Sofa server runs on a free port for these."""
import io
import json
import os
import sqlite3
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from http.cookiejar import CookieJar

from tests import LIBRARY, video
from sofa import auth, config, kids, screens, store, web
from sofa.library import LIBRARY as LIB


class Client:
    def __init__(self, base, token=None):
        self.base, self.token = base, token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, path, body=None):
        headers = {"Content-Type": "application/json", "X-Sofa": "1"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with self.opener.open(req, timeout=40) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        video(os.path.join(LIBRARY, "Shows", "Bluey", "Season 1", "Bluey S01E01.mp4"))
        video(os.path.join(LIBRARY, "Shows", "Westworld", "Season 1", "Westworld S01E01.mp4"))
        video(os.path.join(LIBRARY, "Movies", "Heat (1995)", "Heat (1995).mp4"))
        LIB.scan("tests")
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        if not store.q1("SELECT 1 FROM users WHERE name = 'leo'"):
            auth.create_user("leo", "password123", admin=True)
            auth.create_user("mia", "kidpass123")
        cls.admin = Client(cls.base)
        status, _ = cls.admin.call("/api/login", {"name": "leo", "password": "password123"})
        assert status == 200

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_info_needs_no_sign_in(self):
        status, info = Client(self.base).call("/api/info")
        self.assertEqual(status, 200)
        self.assertTrue(info["sofa"])
        self.assertEqual(info["api"], 1)

    def test_roku_channel_download(self):
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.base + "/roku.zip", timeout=20) as r:
            names = zipfile.ZipFile(io.BytesIO(r.read())).namelist()
        self.assertIn("manifest", names)               # at the top of the zip, as a Roku's developer page wants
        self.assertIn("components/MainScene.brs", names)
        self.assertIn("images/icon_hd.png", names)

    def test_sofa_box_files(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(self.base + "/sofa-box/install.sh", timeout=20) as r:
            self.assertTrue(r.read().startswith(b"#!/bin/sh"))
        for name in ("sofa-box-agent.py", "sofa-box-art.py", "sofa-box-input.py", "finder.html", "preview.html", "mpv-input.conf"):
            with opener.open(self.base + "/sofa-box/" + name, timeout=20) as r:      # all the installer fetches
                self.assertTrue(r.read())
        with self.assertRaises(urllib.error.HTTPError):
            opener.open(self.base + "/sofa-box/../sofa/config.py", timeout=20)
        import tarfile
        with opener.open(self.base + "/sofa-box.tar.gz", timeout=30) as r:          # the whole box in one file
            names = tarfile.open(fileobj=io.BytesIO(r.read()), mode="r:gz").getnames()
        for name in ("sofa-box/sofa-box-agent.py", "sofa-box/boxos.py", "sofa-box/home/index.html", "sofa-box/store.json",
                     "sofa-box/games/games.json", "sofa-box/fonts/instrument-sans-latin-wght-normal.woff2"):
            self.assertIn(name, names)
        self.assertNotIn("sofa-box/README.md", names)
        with self.assertRaises(urllib.error.HTTPError):
            opener.open(self.base + "/sofa-box/README.md", timeout=20)      # only the box's own files

    def test_signed_out_is_401(self):
        self.assertEqual(Client(self.base).call("/api/library")[0], 401)
        self.assertEqual(Client(self.base, token="not-a-token").call("/api/library")[0], 401)

    def test_library(self):
        status, lib = self.admin.call("/api/library")
        self.assertEqual(status, 200)
        self.assertTrue({"Bluey", "Westworld"} <= {s["name"] for s in lib["shows"]})
        self.assertIn("Heat", [m["title"] for m in lib["movies"]])

    def test_pairing_gives_an_app_a_token(self):
        tv = Client(self.base)
        status, start = tv.call("/api/pair/start", {"name": "Living room"})
        self.assertEqual(status, 200)
        self.assertEqual(len(start["code"]), 6)
        self.assertEqual(tv.call("/api/pair/poll?poll=" + start["poll"])[1]["state"], "waiting")
        status, look = self.admin.call("/api/pair/" + start["code"])
        self.assertEqual(look["device"], "Living room")
        self.assertEqual(self.admin.call("/api/pair/approve", {"code": start["code"], "profile": look["me"]})[0], 200)
        status, done = tv.call("/api/pair/poll?poll=" + start["poll"])
        self.assertEqual(done["state"], "approved")
        app = Client(self.base, token=done["token"])
        self.assertEqual(app.call("/api/library")[0], 200)
        self.assertEqual(tv.call("/api/pair/poll?poll=" + start["poll"])[1]["state"], "expired")     # used up
        sessions = self.admin.call("/api/admin/sessions")[1]["sessions"]
        mine = [s for s in sessions if s["device"] == "Paired: Living room"]
        self.assertTrue(mine)
        self.admin.call("/api/admin/sessions", {"id": mine[0]["id"]})                                  # sign it out
        self.assertEqual(app.call("/api/library")[0], 401)

    def test_kids_profile_sees_family_titles_only(self):
        mia = store.q1("SELECT id FROM users WHERE name = 'mia'")["id"]
        self.assertEqual(self.admin.call("/api/admin/users/%d/kids" % mia, {"on": True})[0], 200)
        kids.choose("s:bluey", True)
        kid = Client(self.base)
        kid.call("/api/login", {"name": "mia", "password": "kidpass123"})
        lib = kid.call("/api/library")[1]
        self.assertEqual([s["name"] for s in lib["shows"]], ["Bluey"])
        self.assertEqual(lib["movies"], [])
        self.assertEqual(kid.call("/api/play/e:westworld:1:1")[0], 404)
        self.assertEqual(kid.call("/api/live")[0], 403)

    def test_phone_remote(self):
        got = {}
        tv = Client(self.base)
        tv.opener, tv.token = self.admin.opener, None                      # the same person on another screen

        def wait():
            got["commands"] = tv.call("/api/screen/wait?id=tvtest&name=TV&tv=1")[1]["commands"]
        t = threading.Thread(target=wait)
        t.start()
        for _ in range(50):
            if any(s["id"] == "tvtest" for s in screens.listing(1)):
                break
            time.sleep(0.05)
        status, _ = self.admin.call("/api/screens/tvtest", {"command": {"cmd": "toggle"}, "name": "Phone"})
        self.assertEqual(status, 200)
        t.join(10)
        self.assertEqual(got["commands"][0]["cmd"], "toggle")

    def test_profile_choices_follow_the_person(self):
        status, r = self.admin.call("/api/me/prefs", {"home": {"order": ["continue", "my-list", "Bad Id!", 7], "hidden": ["genres"]},
                                                      "look": {"accent": "#3cc8d8", "motion": "calm", "theme": "url(x)", "other": 1}})
        self.assertEqual(status, 200)
        self.assertEqual(r["prefs"]["home"], {"order": ["continue", "my-list"], "hidden": ["genres"]})   # only real row names
        self.assertEqual(r["prefs"]["look"], {"accent": "#3cc8d8", "motion": "calm"})
        other_screen = Client(self.base)                                       # the same person on another screen
        other_screen.call("/api/login", {"name": "leo", "password": "password123"})
        self.assertEqual(other_screen.call("/api/session")[1]["user"]["prefs"]["look"]["motion"], "calm")
        self.admin.call("/api/me/prefs", {"look": {"motion": None}, "home": None})       # back to Sofa's own
        prefs = other_screen.call("/api/session")[1]["user"]["prefs"]
        self.assertNotIn("home", prefs)
        self.assertEqual(prefs["look"], {"accent": "#3cc8d8"})
        self.admin.call("/api/me/prefs", {"look": {"accent": None}})

    def test_asking_for_an_account(self):
        visitor = Client(self.base)
        self.assertEqual(visitor.call("/api/signup", {"name": "sam", "password": "samspassword1"})[0], 403)   # off unless allowed
        self.admin.call("/api/admin/settings", {"signups": True})
        try:
            self.assertTrue(visitor.call("/api/session")[1]["signup"])
            self.assertEqual(visitor.call("/api/signup", {"name": "sam", "password": "short"})[0], 400)
            self.assertEqual(visitor.call("/api/signup", {"name": "leo", "password": "longenough123"})[0], 400)   # taken
            status, r = visitor.call("/api/signup", {"name": "sam", "password": "samspassword1", "note": "Leo's  cousin\n"})
            self.assertEqual((status, r.get("pending")), (200, True))
            status, r = visitor.call("/api/login", {"name": "sam", "password": "samspassword1"})
            self.assertEqual(status, 403)                                       # not until an admin says yes
            self.assertIn("waiting", r["error"])
            self.assertEqual(visitor.call("/api/login", {"name": "sam", "password": "wrong-password"})[0], 401)
            self.assertEqual(self.admin.call("/api/session")[1]["waiting"], 1)
            users = self.admin.call("/api/admin/status")[1]["users"]
            sam = next(x for x in users if x["name"] == "sam")
            self.assertEqual((sam["pending"], sam["note"]), (1, "Leo's cousin"))
            self.assertNotIn("sam", [p["name"] for p in auth.profiles()])      # not on "Who's watching?" yet
            visitor.call("/api/signup", {"name": "spammer", "password": "spammerpass1"})
            self.assertEqual(self.admin.call("/api/admin/users/%d/approve" % sam["id"], {"kids": True})[0], 200)
            status, _ = visitor.call("/api/login", {"name": "sam", "password": "samspassword1"})
            self.assertEqual(status, 200)
            self.assertTrue(visitor.call("/api/session")[1]["user"]["kids"])
            spam = store.q1("SELECT id FROM users WHERE name = 'spammer'")["id"]
            self.assertEqual(self.admin.call("/api/admin/users/%d/decline" % spam, {})[0], 200)
            self.assertIsNone(store.q1("SELECT id FROM users WHERE name = 'spammer'"))
            self.assertEqual(self.admin.call("/api/admin/users/%d/decline" % spam, {})[0], 404)
            status, r = Client(self.base).call("/api/signup", {"name": "two", "password": "twopassword1"})
            self.assertEqual(status, 400)                       # three an hour from one address (leo, sam, spammer)
            self.assertIn("an hour", r["error"])
        finally:
            self.admin.call("/api/admin/settings", {"signups": False})
            for name in ("sam", "two"):
                store.ex("DELETE FROM users WHERE name = ?", name)
            auth._asked.clear()

    def test_a_failed_write_doesnt_lock_the_database(self):
        self.assertEqual(self.admin.call("/api/admin/users", {"name": "leo", "password": "password123"})[0], 409)
        conn = sqlite3.connect(os.path.join(config.DATA_DIR, "sofa.db"), timeout=1)
        conn.execute("BEGIN IMMEDIATE")                                        # raises if anything still holds the lock
        conn.rollback()
        conn.close()

    def test_no_logs_and_wipe(self):
        self.admin.call("/api/admin/settings", {"no_logs": True})
        before = store.q1("SELECT COUNT(*) AS n FROM activity")["n"]
        store.log("settings", "this must not be written")
        self.assertEqual(store.q1("SELECT COUNT(*) AS n FROM activity")["n"], before)
        self.admin.call("/api/admin/settings", {"no_logs": False})
        store.log("settings", "written")
        self.assertEqual(self.admin.call("/api/admin/privacy", {"wipe": True})[0], 200)
        left = [r["message"] for r in store.q("SELECT message FROM activity")]
        self.assertEqual(left, ["leo wiped all logs"])                         # only who wiped them, nothing before


if __name__ == "__main__":
    unittest.main()


class GuestsAndTVs(unittest.TestCase):
    """A guest at home can send to the house's TVs, and control only what a guest started."""

    def test_guest_rules(self):
        import time as _t
        screens._screens.clear()
        screens._screens["tv1"] = {"id": "tv1", "name": "Living room", "user": 1, "tv": True, "seen": _t.time(), "gen": 0,
                                   "queue": [], "state": {"item": "m:private:2020", "t": 5}}
        screens._screens["lap"] = {"id": "lap", "name": "Laptop", "user": 1, "tv": False, "seen": _t.time(), "gen": 0,
                                   "queue": [], "state": {}}
        tvs = screens.tvs_for_guest()
        self.assertEqual([s["name"] for s in tvs], ["Living room"])      # TVs only
        self.assertEqual(tvs[0]["state"], {})                            # not what the family is watching
        self.assertFalse(screens.send_as_guest("tv1", {"cmd": "pause"}, "Guest"))    # not theirs to pause
        self.assertFalse(screens.send_as_guest("lap", {"cmd": "play", "item": "m:heat:1995"}, "Guest"))
        self.assertTrue(screens.send_as_guest("tv1", {"cmd": "play", "item": "m:heat:1995"}, "Guest"))
        screens._screens["tv1"]["state"] = {"item": "m:heat:1995", "t": 1}
        self.assertTrue(screens.send_as_guest("tv1", {"cmd": "pause"}, "Guest"))     # what a guest started: fine
        self.assertEqual(screens.tvs_for_guest()[0]["state"]["item"], "m:heat:1995")
        screens._screens.clear()
