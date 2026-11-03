"""Who may do what, tested against the running server rather than read from the docs: PIN and password throttling
(kept across restarts, per address and per profile), signing out on every device, switching profiles from a paired
TV, what a Kids profile can reach, roles changing under a signed-in session, other sites' requests, the address
behind a proxy, uploads at once, and connections at once."""
import json
import os
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from unittest import mock

from tests import LIBRARY, video
from sofa import auth, config, kids, store, uploads, web
from sofa.library import LIBRARY as LIB


class Client:
    def __init__(self, base, token=None, origin=None):
        self.base, self.token, self.origin = base, token, origin
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, path, body=None, origin=None):
        headers = {"Content-Type": "application/json", "X-Sofa": "1"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if origin or self.origin:
            headers["Origin"] = origin or self.origin
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        def parse(raw):
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                return {"text": raw[:200].decode("utf-8", "replace")}       # a file, or a plain "Not found"
        try:
            with self.opener.open(req, timeout=30) as r:
                return r.status, parse(r.read(4096))
        except urllib.error.HTTPError as e:
            return e.code, parse(e.read())


class Access(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        video(os.path.join(LIBRARY, "Shows", "Bluey", "Season 1", "Bluey S01E01.mp4"))
        video(os.path.join(LIBRARY, "Movies", "Heat (1995)", "Heat (1995).mp4"))
        LIB.scan("tests")
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        for name, admin in (("acc-admin", True), ("acc-viewer", False), ("acc-kid", False)):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123", admin=admin)
        cls.ids = {r["name"]: r["id"] for r in store.q("SELECT id, name FROM users WHERE name LIKE 'acc-%'")}
        auth.set_profile(cls.ids["acc-admin"], pin="4321")
        auth.set_kids(cls.ids["acc-kid"], True)
        kids.choose("s:bluey", True)
        cls.admin = cls.signed_in("acc-admin")

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def tearDown(self):
        store.ex("DELETE FROM failures")                       # (the next test starts unthrottled)

    @classmethod
    def signed_in(cls, name, password="password123"):
        c = Client(cls.base)
        status, _ = c.call("/api/login", {"name": name, "password": password})
        assert status == 200, (name, status)
        return c

    def paired_tv(self, as_name):
        tv = Client(self.base)
        _, start = tv.call("/api/pair/start", {"name": "Den"})
        approver = self.admin if as_name == "acc-admin" else self.signed_in(as_name)
        self.assertEqual(approver.call("/api/pair/approve", {"code": start["code"], "profile": self.ids[as_name]})[0], 200)
        return Client(self.base, token=tv.call("/api/pair/poll?poll=" + start["poll"])[1]["token"])

    # ---- PINs and passwords
    def test_pin_tries_are_limited_and_remembered(self):
        viewer = self.signed_in("acc-viewer")
        for _ in range(auth.MAX_FAILURES):
            self.assertEqual(viewer.call("/api/profiles/switch", {"id": self.ids["acc-admin"], "code": "0000"})[0], 403)
        self.assertEqual(viewer.call("/api/profiles/switch", {"id": self.ids["acc-admin"], "code": "4321"})[0], 429)   # even the right one
        self.assertGreaterEqual(store.q1("SELECT COUNT(*) AS n FROM failures")["n"], auth.MAX_FAILURES)       # in the database:
        self.assertTrue(auth.throttled("127.0.0.1"))                                                          # a restart doesn't forget

    def test_a_profile_is_limited_from_every_address(self):
        target = "profile:%d" % self.ids["acc-admin"]
        for i in range(auth.MAX_ACCOUNT_FAILURES):             # one try each from many addresses
            auth.record_failure("192.168.1.%d" % (i + 10), target)
        self.assertTrue(auth.throttled("192.168.1.250", target))
        self.assertFalse(auth.throttled("192.168.1.250", "profile:%d" % self.ids["acc-viewer"]))

    def test_passwords_are_limited_per_account_too(self):
        for i in range(auth.MAX_ACCOUNT_FAILURES):
            auth.record_failure("10.9.0.%d" % i, auth.account_key("acc-viewer"))
        self.assertEqual(Client(self.base).call("/api/login", {"name": "Acc-Viewer", "password": "password123"})[0], 429)

    # ---- signing out everywhere
    def test_a_new_password_signs_out_every_device(self):
        phone, laptop = self.signed_in("acc-viewer"), self.signed_in("acc-viewer")
        tv = self.paired_tv("acc-viewer")
        for c in (phone, laptop, tv):
            self.assertEqual(c.call("/api/library")[0], 200)
        self.assertEqual(self.admin.call("/api/admin/users/%d/password" % self.ids["acc-viewer"], {"password": "newpass456"})[0], 200)
        for c in (phone, laptop, tv):
            self.assertEqual(c.call("/api/library")[0], 401)
        auth.set_password(self.ids["acc-viewer"], "password123")

    def test_removing_someone_signs_them_out(self):
        auth.create_user("acc-gone", "password123")
        gone = self.signed_in("acc-gone")
        uid = store.q1("SELECT id FROM users WHERE name = 'acc-gone'")["id"]
        self.assertEqual(self.admin.call("/api/admin/users/%d/delete" % uid, {})[0], 200)
        self.assertEqual(gone.call("/api/library")[0], 401)

    # ---- a paired TV switching profiles
    def test_a_paired_tv_switches_profile_only_with_its_pin(self):
        tv = self.paired_tv("acc-viewer")
        self.assertEqual(tv.call("/api/profiles/switch", {"id": self.ids["acc-admin"]})[0], 403)                # an admin: its PIN
        self.assertEqual(tv.call("/api/profiles/switch", {"id": self.ids["acc-admin"], "code": "1111"})[0], 403)
        status, out = tv.call("/api/profiles/switch", {"id": self.ids["acc-admin"], "code": "4321"})
        self.assertEqual(status, 200)
        self.assertEqual(tv.call("/api/library")[0], 401)                                                      # the old token ended
        now = Client(self.base, token=out["token"])
        self.assertTrue(now.call("/api/session")[1]["user"]["admin"])
        devices = [s["device"] for s in self.admin.call("/api/admin/sessions")[1]["sessions"] if s["user"] == "acc-admin"]
        self.assertIn("Paired: Den", devices)                                                                   # still the Den TV

    def test_out_of_a_kids_profile_takes_a_code(self):
        tv = self.paired_tv("acc-kid")
        self.assertEqual(tv.call("/api/profiles/switch", {"id": self.ids["acc-viewer"]})[0], 403)   # not locked, but out of Kids
        self.assertEqual(tv.call("/api/profiles/switch", {"id": self.ids["acc-viewer"], "code": "password123"})[0], 200)

    # ---- Kids
    def test_a_kids_profile_reaches_family_titles_only(self):
        kid = self.signed_in("acc-kid")
        self.assertEqual([s["name"] for s in kid.call("/api/library")[1]["shows"]], ["Bluey"])
        heat = "m:heat:1995"
        for path in ("/api/play/" + heat, "/api/hls/" + heat, "/media/%s/file" % heat.replace(":", "%3A"),
                     "/media/%s/stream" % heat.replace(":", "%3A")):
            self.assertIn(kid.call(path)[0], (403, 404), path)
        self.assertEqual(kid.call("/api/admin/settings")[0], 403)
        self.assertEqual(kid.call("/api/live")[0], 403)

    def test_roles_change_under_a_signed_in_session(self):
        viewer = self.signed_in("acc-viewer")
        self.assertIn("Heat", [m["title"] for m in viewer.call("/api/library")[1]["movies"]])
        self.assertEqual(self.admin.call("/api/admin/users/%d/kids" % self.ids["acc-viewer"], {"on": True})[0], 200)
        self.assertEqual(viewer.call("/api/library")[1]["movies"], [])                # at once, on the same session
        self.assertEqual(viewer.call("/api/play/m:heat:1995")[0], 404)
        self.admin.call("/api/admin/users/%d/kids" % self.ids["acc-viewer"], {"on": False})
        self.assertIn("Heat", [m["title"] for m in viewer.call("/api/library")[1]["movies"]])
        self.assertFalse(viewer.call("/api/session")[1]["user"]["adult"])
        self.admin.call("/api/admin/users/%d/adult" % self.ids["acc-viewer"], {"on": True})
        self.assertTrue(viewer.call("/api/session")[1]["user"]["adult"])
        self.admin.call("/api/admin/users/%d/adult" % self.ids["acc-viewer"], {"on": False})
        self.assertFalse(viewer.call("/api/session")[1]["user"]["adult"])
        self.assertEqual(viewer.call("/api/admin/settings")[0], 403)                  # never an admin by asking

    # ---- other sites, proxies
    def test_other_sites_are_turned_away(self):
        self.assertEqual(self.admin.call("/api/me/prefs", {"look": {"motion": "calm"}}, origin="https://evil.example")[0], 403)
        self.assertEqual(self.admin.call("/api/me/prefs", {"look": {"motion": "calm"}}, origin=self.base)[0], 200)
        self.assertEqual(self.admin.call("/api/me/prefs", {"look": {"motion": "calm"}}, origin="http://k3x9q2.localhost:8091")[0], 200)
        self.assertEqual(self.admin.call("/api/me/prefs", {"look": {"motion": "calm"}})[0], 200)            # apps send none

    def test_behind_a_proxy_the_last_address_counts(self):
        h = web.Handler.__new__(web.Handler)
        h.client_address = ("127.0.0.1", 50000)
        h.headers = {"X-Forwarded-For": "192.168.1.5, 203.0.113.9"}                # the first one, the client made up
        with mock.patch.dict(config._config, {"trust_proxy": True}):
            self.assertEqual(h.client_ip(), "203.0.113.9")
        with mock.patch.dict(config._config, {"trust_proxy": False}):
            self.assertEqual(h.client_ip(), "127.0.0.1")

    # ---- uploads, connections
    def test_uploads_at_once_dont_promise_the_same_room(self):
        gb = 1024 ** 3
        disk = mock.Mock(free=20 * gb)
        with mock.patch("shutil.disk_usage", return_value=disk), mock.patch.dict(uploads._active, {"a": {"size": 15 * gb, "got": 1 * gb}}):
            self.assertIsNone(uploads.check("a.mkv", 2 * gb, False))
            self.assertIn("isn't room", uploads.check("b.mkv", 5 * gb, False))       # 14 still coming + 5 + 2 spare > 20
        with mock.patch.dict(config._config, {"upload_max_gb": 1}):
            self.assertIn("bigger than", uploads.check("c.mkv", 2 * gb, False))
        with mock.patch.dict(uploads._active, {str(i): {"size": 1, "got": 0} for i in range(3)}):
            self.assertIn("being sent already", uploads.check("d.mkv", 1, False))

    def test_connections_are_capped(self):
        class Small(web.Server):
            max_connections = 2
        srv = Small(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        held = [socket.create_connection(srv.server_address, timeout=5) for _ in range(2)]   # two idle connections
        try:
            time.sleep(0.3)
            extra = socket.create_connection(srv.server_address, timeout=5)
            self.assertTrue(extra.recv(64).startswith(b"HTTP/1.1 503"))              # the third: busy, at once
            extra.close()
        finally:
            for s in held:
                s.close()
            srv.shutdown()
            srv.server_close()
