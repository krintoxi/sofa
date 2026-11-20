"""The Adult section's top lists and kept links: off until an admin says so, behind the Adult switch for everyone,
lists only (Sofa never asks a site for a video), no request waits on the site, and a site that's down is a quiet page.
The site here is a stand-in function: nothing in these tests reaches the internet."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from unittest import mock

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import auth, config, fetch, freeadult, naming, sharing, store, toplists, web

API = "https://www.eporner.com/api/v2/"


def entry(n, **over):
    vid = "Vid%08d" % n
    v = {"id": vid, "title": "Title %d" % n, "views": 1000 - n, "rate": "4.20", "length_sec": 600 + n,
         "url": "https://www.eporner.com/video-%s/title/" % vid, "added": "2026-11-10 10:00:00",
         "embed": "https://www.eporner.com/embed/%s/" % vid,
         "default_thumb": {"src": "https://static-ca-cdn.eporner.com/thumbs/%d.jpg" % n}, "quality": {"max": "1080p"}}
    v.update(over)
    return v


class Site:
    """What the site's API would say, and everything it was asked."""
    def __init__(self):
        self.asked, self.wait, self.down, self.removed = [], 0, False, set()

    def __call__(self, url):
        self.asked.append(url)
        time.sleep(self.wait)
        if self.down:
            raise urllib.error.URLError("the site is down")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if url.startswith(API + "categories/"):
            return {"categories": [{"id": 1, "name": "Massage", "slug": "massage"}, {"id": 2, "name": "Outdoor", "slug": "outdoor"},
                                   {"id": 3, "name": "Teen", "slug": "teens"}, {"id": 4, "name": "Bad Slug", "slug": "../x"}]}
        if url.startswith(API + "video/status/"):
            return {"videos": [{"id": i, "status": "removed" if i in self.removed else "active"} for i in q["id"].split(",")]}
        videos = [entry(n) for n in range(30)]
        videos[3] = entry(3, embed="https://elsewhere.example/embed/Vid00000003/")       # a player that isn't the site's
        videos[4] = entry(4, url="http://www.eporner.com/video-x/")                       # a page that isn't https
        videos[5] = entry(5, default_thumb={"src": "https://elsewhere.example/a.jpg"})    # a picture from elsewhere
        videos[6] = entry(6, embed="https://www.eporner.com/embed/Vid00000007/")          # a player for another video
        return {"videos": videos, "total_count": 30}


class Someone:
    def __init__(self, base, name=None, token=None):
        self.base, self.token = base, token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))
        if name:
            self.call("/api/login", {"name": name, "password": "password123"})

    def call(self, path, data=None):
        head = {"Content-Type": "application/json", "X-Sofa": "1"}
        if self.token:
            head["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + path, None if data is None else json.dumps(data).encode(), head)
        try:
            with self.opener.open(req, timeout=30) as r:
                body = r.read()
                return r.status, json.loads(body) if body[:1] in (b"{", b"[") else body
        except urllib.error.HTTPError as e:
            return e.code, e.read()


class TopLists(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.ids = {}
        for name, admin in (("top-admin", True), ("top-adult", False), ("top-plain", False), ("top-kid", False)):
            row = store.q1("SELECT id FROM users WHERE name = ?", name)
            cls.ids[name] = row["id"] if row else auth.create_user(name, "password123", admin=admin)["id"]
        auth.set_adult(cls.ids["top-admin"], True)
        auth.set_adult(cls.ids["top-adult"], True)
        auth.set_adult(cls.ids["top-kid"], True)
        for name in ("top-admin", "top-adult", "top-kid"):
            auth.confirm_age(cls.ids[name])
        auth.set_kids(cls.ids["top-kid"], True)
        cls.admin, cls.adult = Someone(cls.base, "top-admin"), Someone(cls.base, "top-adult")
        cls.plain, cls.kid = Someone(cls.base, "top-plain"), Someone(cls.base, "top-kid")
        cls.guest = Someone(cls.base, token=auth.start_session(auth.guest_user()["id"], "127.0.0.1", "test"))
        cls.visitor = Someone(cls.base, token=auth.start_session(sharing.visitor_user()["id"], "127.0.0.1", "test"))
        cls.nobody = Someone(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        store.ex("DELETE FROM users WHERE guest != 0")      # the guest and the visitor made here (a guest is named "Guest",
                                                            # and another test makes a person of that name)

    def setUp(self):
        self.site = Site()
        self.before = {k: config.get(k) for k in ("adult_sites", "share_on")}
        config.update({"adult_sites": [], "share_on": True})
        toplists.fetch_json = self.site
        toplists._cache.clear()
        toplists._table()
        store.ex("DELETE FROM kept_links")

    def tearDown(self):
        self.settle()
        toplists.fetch_json = None
        toplists._cache.clear()
        config.update(self.before)

    def settle(self):
        until = time.time() + 10
        while toplists._asking and time.time() < until:
            time.sleep(0.02)

    def ready(self, who, path="/api/adult/top/eporner?cat=massage"):
        for _ in range(200):
            status, out = who.call(path)
            if status != 200 or out["state"] != "reading":
                return status, out
            time.sleep(0.02)
        self.fail("the list never came")

    # ------------------------------------------------------------ off until someone says so

    def test_off_to_begin_with_and_nothing_is_asked_of_any_site(self):
        self.assertEqual(config.DEFAULTS["adult_sites"], [])
        status, out = self.admin.call("/api/adult/top")
        self.assertEqual((status, [s["on"] for s in out["sites"]]), (200, [False]))
        self.assertEqual(self.adult.call("/api/adult/top")[1]["sites"], [])          # (off: not even its name, but for admins)
        self.assertEqual(self.admin.call("/api/adult/top/eporner")[0], 404)
        self.assertFalse(self.admin.call("/api/session")[1]["adult_top"])
        self.assertEqual(self.site.asked, [])

    def test_an_admin_switches_a_site_on_and_off(self):
        self.assertEqual(self.adult.call("/api/admin/adult-sites", {"site": "eporner", "on": True})[0], 403)   # admins only
        self.assertEqual(self.admin.call("/api/admin/adult-sites", {"site": "nowhere", "on": True})[0], 400)
        status, out = self.admin.call("/api/admin/adult-sites", {"site": "eporner", "on": True})
        self.assertEqual((status, out["sites"][0]["on"]), (200, True))
        self.assertTrue(self.adult.call("/api/session")[1]["adult_top"])
        self.assertEqual(self.ready(self.adult)[1]["state"], "ready")
        self.admin.call("/api/admin/adult-sites", {"site": "eporner", "on": False})
        self.assertEqual(self.adult.call("/api/adult/top/eporner")[0], 404)
        self.assertEqual(toplists._cache, {})                                         # (and what was read is let go)
        log = " ".join(r["message"] for r in store.q("SELECT message FROM activity"))
        self.assertNotIn("porner", log)                                               # Activity doesn't name the site

    # ------------------------------------------------------------ the gate

    def test_only_someone_with_the_adult_switch(self):
        config.update({"adult_sites": ["eporner"]})
        self.ready(self.adult)
        for who, name in ((self.plain, "no Adult switch"), (self.kid, "a Kids profile"), (self.guest, "a guest"),
                          (self.visitor, "a visitor"), (self.nobody, "not signed in")):
            for path in ("/api/adult/top", "/api/adult/top/eporner", "/api/adult/top/eporner/v/Vid00000001", "/api/adult/kept"):
                self.assertIn(who.call(path)[0], (401, 403, 404), "%s reached %s" % (name, path))
            self.assertIn(who.call("/api/adult/kept", {"site": "eporner", "id": "Vid00000001", "keep": True})[0], (401, 403, 404), name)
            self.assertIn(who.call("/api/admin/adult-sites", {"site": "eporner", "on": True})[0], (401, 403, 404), name)
            if who is not self.nobody:
                self.assertFalse(who.call("/api/session")[1]["adult_top"], name)
        self.assertEqual(store.q1("SELECT COUNT(*) AS n FROM kept_links")["n"], 0)

    def test_never_on_a_public_sofa(self):
        config.update({"adult_sites": ["eporner"]})
        with mock.patch.object(config, "demo_on", return_value=True):
            self.assertEqual(toplists.on(), [])
            self.assertIsNone(toplists.listing("eporner"))
            self.assertFalse(web.Handler.adult_only({"adult": True}))
            self.assertEqual(config.get("adult_sites"), [])                           # (the demo's lock, whatever the file says)
        self.assertEqual(self.site.asked, [])

    # ------------------------------------------------------------ the lists

    def test_twenty_five_of_a_category_and_only_what_is_the_sites_own(self):
        config.update({"adult_sites": ["eporner"]})
        status, out = self.ready(self.adult)
        self.assertEqual((status, out["state"], len(out["items"])), (200, "ready", 22))    # 25 asked for, three weren't the site's
        self.assertEqual([c["slug"] for c in out["cats"]], ["massage", "outdoor"])    # (not the ones Sofa leaves out)
        ids = [x["id"] for x in out["items"]]
        for bad in ("Vid00000003", "Vid00000004", "Vid00000006"):
            self.assertNotIn(bad, ids)
        five = next(x for x in out["items"] if x["id"] == "Vid00000005")
        self.assertIsNone(five["thumb"])                                              # a picture from elsewhere isn't shown
        one = out["items"][0]
        self.assertEqual(one["embed"], "https://www.eporner.com/embed/Vid00000000/")
        self.assertTrue(one["url"].startswith("https://www.eporner.com/"))
        search = urllib.parse.parse_qs(urllib.parse.urlsplit(self.site.asked[-1]).query)
        self.assertEqual((search["query"], search["order"], search["per_page"]), (["Massage"], ["top-weekly"], ["25"]))
        self.ready(self.adult, "/api/adult/top/eporner?cat=massage&period=month")
        self.assertIn("order=top-monthly", self.site.asked[-1])

    def test_sofa_asks_the_site_for_lists_and_nothing_else(self):
        config.update({"adult_sites": ["eporner"]})
        self.ready(self.adult)
        self.adult.call("/api/adult/top/eporner/v/Vid00000001")
        self.adult.call("/api/adult/kept", {"site": "eporner", "id": "Vid00000001"})
        self.adult.call("/api/adult/kept", {"site": "eporner", "id": "Vid00000001", "keep": True})
        toplists.drop_removed()
        self.assertTrue(self.site.asked)
        for url in self.site.asked:                       # the categories, a search, a status: never a video, a page or a picture
            self.assertRegex(url, r"^https://www\.eporner\.com/api/v2/(categories/$|video/search/\?|video/status/\?)")
        routes = open(web.__file__, encoding="utf-8").read()
        self.assertNotIn("toplists.download", routes)
        self.assertFalse([n for n in dir(toplists) if "download" in n.lower() or "save" in n.lower()])

    def test_a_request_never_waits_on_the_site_and_a_list_is_kept(self):
        config.update({"adult_sites": ["eporner"]})
        self.site.wait = 0.6
        began = time.time()
        status, out = self.adult.call("/api/adult/top/eporner")
        self.assertEqual((status, out["state"]), (200, "reading"))
        self.assertLess(time.time() - began, 0.4)
        self.site.wait = 0
        self.assertEqual(self.ready(self.adult, "/api/adult/top/eporner")[1]["state"], "ready")
        asked = len(self.site.asked)
        for _ in range(5):
            self.assertEqual(self.adult.call("/api/adult/top/eporner")[1]["state"], "ready")
        self.assertEqual(len(self.site.asked), asked)     # the same list again: from what Sofa kept

    def test_a_site_that_is_down_is_a_quiet_page(self):
        config.update({"adult_sites": ["eporner"]})
        self.site.down = True
        status, out = self.ready(self.adult, "/api/adult/top/eporner")
        self.assertEqual((status, out["state"], out["items"]), (200, "down", []))
        self.settle()
        asked = len(self.site.asked)
        self.adult.call("/api/adult/top/eporner")
        self.assertEqual(len(self.site.asked), asked)     # ...and it isn't asked again straight away

    def test_the_last_list_stays_while_the_site_is_away(self):
        config.update({"adult_sites": ["eporner"]})
        self.assertEqual(len(self.ready(self.adult)[1]["items"]), 22)
        self.site.down = True
        for got in toplists._cache.values():
            got["at"] -= toplists.FRESH + 5
        self.adult.call("/api/adult/top/eporner?cat=massage")
        self.settle()
        status, out = self.adult.call("/api/adult/top/eporner?cat=massage")
        self.assertEqual((out["state"], len(out["items"]), out["old"]), ("ready", 22, True))

    def test_a_site_whose_name_cant_be_found_isnt_the_internet_being_down(self):
        import socket
        from sofa import net
        toplists.fetch_json = None                         # (the real reader, with the network taken away under it)
        config.update({"adult_sites": ["eporner"], "offline": False})
        before, asked = net._down_until[0], []

        class Reply:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return self.body

        def gone(req, timeout=None, context=None):
            asked.append(req.full_url)
            raise urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided, or not known"))

        def there(req, timeout=None, context=None):
            asked.append((req.full_url, req.get_header("User-agent")))
            return Reply(json.dumps(self.site(req.full_url)).encode())
        try:
            with mock.patch.object(urllib.request, "urlopen", gone):
                self.assertEqual(toplists.listing("eporner", wait=True)["state"], "down")
            self.assertEqual(net._down_until[0], before)                               # Sofa still asks everyone else
            self.assertTrue(asked)
            toplists._cache.clear()
            with mock.patch.object(urllib.request, "urlopen", there):
                out = toplists.listing("eporner", wait=True)
                out = toplists.listing("eporner", wait=True)
            self.assertEqual((out["state"], len(out["items"])), ("ready", 22))
            self.assertEqual(asked[-1][1], "Sofa")                                     # asked as itself, not as a browser
        finally:
            net._down_until[0] = before
            config.update({"offline": True})

    def test_keep_no_logs_keeps_no_trail_of_what_was_played(self):
        config.update({"adult_sites": ["eporner"]})
        self.ready(self.adult)
        with mock.patch.object(store, "no_logs", return_value=True):
            self.assertEqual(self.adult.call("/api/adult/kept", {"site": "eporner", "id": "Vid00000001"})[0], 200)
            self.assertEqual(self.adult.call("/api/adult/kept", {"site": "eporner", "id": "Vid00000002", "keep": True})[0], 200)
        out = self.adult.call("/api/adult/kept")[1]
        self.assertEqual(([k["id"] for k in out["kept"]], out["played"]), (["Vid00000002"], []))

    # ------------------------------------------------------------ kept links

    def test_keeping_a_link_and_letting_it_go(self):
        config.update({"adult_sites": ["eporner"]})
        self.ready(self.adult)
        self.assertEqual(self.adult.call("/api/adult/kept", {"site": "eporner", "id": "Vid99999999", "keep": True})[0], 404)   # not one Sofa listed
        self.assertEqual(self.adult.call("/api/adult/kept", {"site": "eporner", "id": "../../etc", "keep": True})[0], 404)
        self.assertEqual(self.adult.call("/api/adult/kept", {"site": "eporner", "id": "Vid00000001"})[0], 200)                 # played
        self.assertEqual(self.adult.call("/api/adult/kept", {"site": "eporner", "id": "Vid00000002", "keep": True})[0], 200)
        out = self.adult.call("/api/adult/kept")[1]
        self.assertEqual(([k["id"] for k in out["kept"]], [k["id"] for k in out["played"]]), (["Vid00000002"], ["Vid00000001"]))
        kept = out["kept"][0]
        self.assertEqual(sorted(kept), ["at", "embed", "id", "kept", "length", "site", "site_name", "thumb", "title", "url"])
        self.assertLess(abs(kept["at"] - time.time()), 30)                            # (the day it was kept)
        self.assertEqual(self.admin.call("/api/adult/kept")[1], {"kept": [], "played": []})      # each person their own
        toplists._cache.clear()                                                       # the list has moved on: a kept one still plays
        self.assertEqual(self.adult.call("/api/adult/top/eporner/v/Vid00000002")[1]["embed"], "https://www.eporner.com/embed/Vid00000002/")
        self.adult.call("/api/adult/kept", {"site": "eporner", "id": "Vid00000002", "keep": False})
        self.assertEqual(self.adult.call("/api/adult/kept")[1]["kept"], [])

    def test_what_the_site_removes_leaves_the_kept_links(self):
        config.update({"adult_sites": ["eporner"]})
        self.ready(self.adult)
        for vid in ("Vid00000001", "Vid00000002"):
            self.adult.call("/api/adult/kept", {"site": "eporner", "id": vid, "keep": True})
        self.site.down = True
        self.assertEqual(toplists.drop_removed(), 0)                                   # no answer removes nothing
        self.assertEqual(len(self.adult.call("/api/adult/kept")[1]["kept"]), 2)
        self.site.down, self.site.removed = False, {"Vid00000001"}
        self.assertEqual(toplists.drop_removed(), 1)
        self.assertEqual([k["id"] for k in self.adult.call("/api/adult/kept")[1]["kept"]], ["Vid00000002"])

    def test_played_and_not_kept_is_forgotten_after_a_month(self):
        config.update({"adult_sites": ["eporner"]})
        self.ready(self.adult)
        for vid, keep in (("Vid00000001", None), ("Vid00000002", True)):
            self.adult.call("/api/adult/kept", dict({"site": "eporner", "id": vid}, **({"keep": True} if keep else {})))
        store.ex("UPDATE kept_links SET at = at - ?", (toplists.PLAYED_DAYS + 1) * 86400)
        out = self.adult.call("/api/adult/kept")[1]
        self.assertEqual(([k["id"] for k in out["kept"]], out["played"]), (["Vid00000002"], []))


class EighteenOrOlder(unittest.TestCase):
    """An admin's Adult switch lets a person be asked; nothing adult reaches them until they say themselves that
    they're 18 or older. Once, kept with the day."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.ids = {}
        for name, admin in (("age-admin", True), ("age-one", False), ("age-kid", False)):
            row = store.q1("SELECT id FROM users WHERE name = ?", name)
            cls.ids[name] = row["id"] if row else auth.create_user(name, "password123", admin=admin)["id"]
        store.ex("UPDATE users SET adult = 0, adult_ok = NULL, kids = 0 WHERE name LIKE 'age-%'")
        cls.admin, cls.one, cls.kid = (Someone(cls.base, n) for n in ("age-admin", "age-one", "age-kid"))

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def who(self, someone):
        return someone.call("/api/session")[1]["user"]

    def test_the_switch_asks_and_the_persons_own_word_opens_it(self):
        one, uid = self.one, self.ids["age-one"]
        self.assertEqual(one.call("/api/adult/age", {"ok": True})[0], 404)             # no switch: nothing to say yes to
        self.assertEqual(self.admin.call("/api/admin/users/%d/adult" % uid, {"on": True})[0], 200)
        me = self.who(one)
        self.assertEqual((me["adult"], me["adult_ask"]), (False, True))
        self.assertNotIn("adult", one.call("/api/library")[1])                         # nothing adult yet
        self.assertEqual(one.call("/api/adult/top")[0], 404)
        self.assertEqual(one.call("/api/adult/age", {"ok": False})[0], 400)            # only a plain yes counts
        self.assertEqual(one.call("/api/adult/age", {})[0], 400)
        self.assertFalse(self.who(one)["adult"])
        began = time.time()
        self.assertEqual(one.call("/api/adult/age", {"ok": True})[0], 200)
        me = self.who(one)
        self.assertEqual((me["adult"], me["adult_ask"]), (True, False))
        self.assertIn("adult", one.call("/api/library")[1])
        # (the list the Server page's People tab is drawn from; its status is an answer kept a moment, so not asked here)
        said = next(u for u in auth.list_users() if u["id"] == uid)["adult_ok"]
        self.assertLessEqual(abs(said - began), 5)                                     # the day is kept, for Server, People
        self.assertIn("age-one said they are 18 or older", " ".join(r["message"] for r in store.q("SELECT message FROM activity")))
        # switched off and on again by an admin: they were asked once, and aren't asked again
        self.admin.call("/api/admin/users/%d/adult" % uid, {"on": False})
        self.assertEqual((self.who(one)["adult"], self.who(one)["adult_ask"]), (False, False))
        self.admin.call("/api/admin/users/%d/adult" % uid, {"on": True})
        self.assertTrue(self.who(one)["adult"])
        self.assertEqual(store.q1("SELECT adult_ok FROM users WHERE id = ?", uid)["adult_ok"], said)

    def test_an_admin_is_asked_too_and_nobody_answers_for_someone_else(self):
        self.admin.call("/api/admin/users/%d/adult" % self.ids["age-admin"], {"on": True})
        self.assertEqual((self.who(self.admin)["adult"], self.who(self.admin)["adult_ask"]), (False, True))
        self.assertFalse(auth.confirm_age(self.ids["age-kid"]))                        # no switch: nothing is written
        self.assertIsNone(store.q1("SELECT adult_ok FROM users WHERE id = ?", self.ids["age-kid"])["adult_ok"])
        self.assertEqual(self.admin.call("/api/adult/age", {"ok": True, "user": self.ids["age-kid"]})[0], 200)
        self.assertIsNone(store.q1("SELECT adult_ok FROM users WHERE id = ?", self.ids["age-kid"])["adult_ok"])   # (their own, only)
        self.assertTrue(self.who(self.admin)["adult"])

    def test_a_kids_profile_is_never_asked(self):
        kid = self.ids["age-kid"]
        auth.set_adult(kid, True)
        auth.set_kids(kid, True)
        me = self.who(self.kid)
        self.assertEqual((me["adult"], me["adult_ask"]), (False, False))
        self.assertEqual(self.kid.call("/api/adult/age", {"ok": True})[0], 404)
        auth.set_kids(kid, False)


class AdultVideosFromALink(unittest.TestCase):
    """Save from a link saves adult videos to the Adult section again (the owner's word, after 1.5.30 took it out),
    for an admin who may see Adult and said they're 18 or older, and nobody else."""

    def setUp(self):
        fetch._table()
        store.ex("DELETE FROM downloads")
        self.before = config.get("offline")
        config.update({"offline": False})

    def tearDown(self):
        store.ex("DELETE FROM downloads")
        config.update({"offline": self.before})

    def test_the_downloader_skips_nothing_for_being_adult(self):
        with mock.patch.object(fetch, "tool", return_value="/usr/bin/yt-dlp"):
            cmd = fetch._command({"url": "https://video.example/watch/1", "playlist": 0}, "/tmp/x")
        self.assertNotIn("--age-limit", cmd)
        self.assertEqual(cmd[-2:], ["--", "https://video.example/watch/1"])

    def test_only_someone_who_may_see_adult_and_said_18_puts_one_in_adult(self):
        httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        try:
            for name in ("link-admin", "link-grown"):
                if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                    auth.create_user(name, "password123", admin=True)
            grown = store.q1("SELECT id FROM users WHERE name = 'link-grown'")["id"]
            auth.set_adult(grown, True)
            plain, sure = Someone(base, "link-admin"), Someone(base, "link-grown")
            self.assertEqual(plain.call("/api/admin/downloads", {"add": {"url": "https://video.example/watch/1", "adult": True}})[0], 403)
            self.assertEqual(sure.call("/api/admin/downloads", {"add": {"url": "https://video.example/watch/1", "adult": True}})[0], 403)   # (not said 18 yet)
            auth.confirm_age(grown)
            self.assertEqual(sure.call("/api/admin/downloads", {"add": {"url": "https://video.example/watch/1", "adult": True}})[0], 200)
            self.assertEqual(plain.call("/api/admin/downloads", {"add": {"url": "https://video.example/watch/2"}})[0], 200)
            self.assertEqual({r["url"][-1]: r["adult"] for r in store.q("SELECT url, adult FROM downloads")}, {"1": 1, "2": 0})
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_a_saved_adult_video_goes_to_inbox_xxx_and_activity_names_nothing(self):
        store.ex("INSERT INTO downloads (url, adult, playlist, state, added) VALUES (?,1,0,'queued',1)", "https://video.example/secret-title")
        job = store.q1("SELECT * FROM downloads")

        def fake(cmd, **kw):
            folder = os.path.dirname(cmd[cmd.index("-o") + 1])
            with open(os.path.join(folder, "A Secret Title [x1].mp4"), "wb") as f:
                f.write(b"\0" * 64)

            class P:
                stdout = iter(["SOFA-TITLE A Secret Title\n"])
                returncode = 0

                def wait(self, timeout=None):
                    return 0

                def poll(self):
                    return 0
            return P()
        inbox = tempfile.mkdtemp()
        try:
            with mock.patch.object(fetch, "tool", return_value="/usr/bin/yt-dlp"), \
                    mock.patch.object(fetch.subprocess, "Popen", side_effect=fake), \
                    mock.patch.object(config, "path", side_effect=lambda k: inbox if k == "inbox" else config.DATA_DIR):
                fetch._run_one(job)
            self.assertEqual(os.listdir(os.path.join(inbox, "XXX")), ["A Secret Title"])
            said = " ".join("%s %s" % (r["message"], r["detail"] or "") for r in store.q("SELECT message, detail FROM activity ORDER BY id DESC LIMIT 3"))
            self.assertNotIn("Secret", said)
            self.assertNotIn("secret-title", said)
        finally:
            shutil.rmtree(inbox, ignore_errors=True)

    def test_a_film_queued_with_a_title_is_filed_under_it_with_its_year(self):
        fetch.add("https://archive.org/download/x/A_Free_Ride_(1915).ogv.240p.mp4", adult=True, title="A Free Ride (1915)",
                  details={"year": "1915", "page": "https://archive.org/details/x", "studio": "Internet Archive", "tags": ["Free to keep"]})
        job = store.q1("SELECT * FROM downloads")

        def fake(cmd, **kw):
            folder = os.path.dirname(cmd[cmd.index("-o") + 1])
            for name, body in (("A_Free_Ride_(1915).ogv.240p [x].mp4", "\0" * 64),
                               ("A_Free_Ride_(1915).ogv.240p [x].info.json", json.dumps({"title": "A_Free_Ride_(1915).ogv.240p", "upload_date": "20230101"}))):
                with open(os.path.join(folder, name), "w") as f:
                    f.write(body)

            class P:
                stdout = iter(["SOFA-TITLE A_Free_Ride_(1915).ogv.240p\n"])

                def wait(self, timeout=None):
                    return 0
            return P()
        inbox = tempfile.mkdtemp()
        try:
            with mock.patch.object(fetch, "tool", return_value="/usr/bin/yt-dlp"), \
                    mock.patch.object(fetch.subprocess, "Popen", side_effect=fake), \
                    mock.patch.object(config, "path", side_effect=lambda k: inbox if k == "inbox" else config.DATA_DIR):
                fetch._run_one(job)
            got = os.path.join(inbox, "XXX", "A Free Ride (1915)")
            self.assertEqual(sorted(os.listdir(got)), ["A Free Ride (1915).info.json", "A Free Ride (1915).mp4"])
            with open(os.path.join(got, "A Free Ride (1915).info.json")) as f:
                info = json.load(f)
            self.assertEqual((info["title"], info["release_date"], info["webpage_url"], info.get("upload_date")),
                             ("A Free Ride (1915)", "19150101", "https://archive.org/details/x", None))
        finally:
            shutil.rmtree(inbox, ignore_errors=True)

    def test_a_title_that_is_also_a_category_stays_one_video(self):
        from sofa import naming
        self.assertIn("erotic", naming.ADULT_CATEGORIES)
        store.ex("INSERT INTO downloads (url, adult, playlist, state, added, title) VALUES (?,1,0,'queued',1,'EROTIC')", "https://a.example/e.mp4")
        job = store.q1("SELECT * FROM downloads")

        def fake(cmd, **kw):
            with open(os.path.join(os.path.dirname(cmd[cmd.index("-o") + 1]), "e [e].mp4"), "w") as f:
                f.write("\0" * 64)

            class P:
                stdout = iter([])

                def wait(self, timeout=None):
                    return 0
            return P()
        inbox = tempfile.mkdtemp()
        try:
            with mock.patch.object(fetch, "tool", return_value="/usr/bin/yt-dlp"), \
                    mock.patch.object(fetch.subprocess, "Popen", side_effect=fake), \
                    mock.patch.object(config, "path", side_effect=lambda k: inbox if k == "inbox" else config.DATA_DIR):
                fetch._run_one(job)
            self.assertEqual(os.listdir(os.path.join(inbox, "XXX")), ["EROTIC (video)"])
        finally:
            shutil.rmtree(inbox, ignore_errors=True)

    def test_the_pages_offer_adult_links_again(self):
        app = open(os.path.join(os.path.dirname(web.__file__), "..", "client", "app.js"), encoding="utf-8").read()
        for back in ('data-add-link="adult"', "adult=1&", "Put it in the Adult section", "Add a link to Adult"):
            self.assertIn(back, app)


class FreeToKeep(unittest.TestCase):
    """Free to keep: adult films from the Internet Archive that may be kept (public domain or Creative Commons, before
    1978), with anything that suggests a minor, family, no consent or drawn characters left out; saved into Adult."""

    DOCS = [
        {"identifier": "stag1", "title": "Blonde stag film", "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/", "year": "1925"},
        {"identifier": "pinup2", "title": "Vintage striptease", "licenseurl": "https://creativecommons.org/licenses/by/3.0/", "subject": ["pin-up"]},
        {"identifier": "recent3", "title": "A studio scene", "licenseurl": "https://creativecommons.org/publicdomain/zero/1.0/", "year": "2004"},
        {"identifier": "vhs4", "title": "Some 1950s VHS tape", "licenseurl": "https://creativecommons.org/publicdomain/zero/1.0/"},
        {"identifier": "school5", "title": "1950s stag film at the school", "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"},
        {"identifier": "teen6", "title": "1960s stag film", "description": "with a teen", "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"},
        {"identifier": "toon7", "title": "Vintage cartoon", "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"},
        {"identifier": "nolic8", "title": "1930s stag film", "licenseurl": "http://www.example.com/all-rights-reserved"},
        {"identifier": "step9", "title": "1940s stag film: stepmother", "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"},
        {"identifier": "pack10", "title": "Public domain films", "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/", "subject": ["1920s", "silent film"]},
    ]

    def meta(self, item):
        doc = next(d for d in self.DOCS if d["identifier"] == item)
        files = [{"name": item + ".mp4", "format": "h.264", "size": "1000"}, {"name": item + "_512kb.mp4", "format": "512Kb MPEG4", "size": "400"},
                 {"name": item + ".jpg", "format": "JPEG", "size": "10"}]
        if item == "pack10":
            files = [{"name": "A_Free_Ride_(1915).ogv.360p.mp4", "format": "h.264", "size": "500"}, {"name": "A_Free_Ride_(1915).ogv", "format": "Ogg Video", "size": "300"},
                     {"name": "La_maitresse_d_ecole.ogv.360p.mp4", "format": "h.264", "size": "500"}, {"name": "Massages.mp4", "format": "MPEG4", "size": "700"}]
        return {"metadata": dict(doc, collection=["no-preview", "other"]), "files": files}

    def setUp(self):
        self.asked = []

        def reader(url):
            self.asked.append(url)
            if url.startswith(freeadult.SEARCH):
                return {"response": {"docs": self.DOCS}}
            return self.meta(urllib.parse.unquote(url[len(freeadult.META):]))
        freeadult.fetch_json = reader
        freeadult._cache.clear()
        fetch._table()
        store.ex("DELETE FROM downloads")
        self.before = config.get("offline")
        config.update({"offline": False})

    def tearDown(self):
        freeadult.fetch_json = None
        freeadult._cache.clear()
        store.ex("DELETE FROM downloads")
        config.update({"offline": self.before})

    def test_only_old_free_films_without_a_hint_of_minors_family_or_force(self):
        got = freeadult.listing("vintage", 25)["items"]
        self.assertEqual([i["title"] for i in got], ["Blonde stag film", "Vintage striptease", "A Free Ride (1915)", "Massages"])
        first = got[0]
        self.assertEqual((first["licence"], first["url"], first["size"]), ("Public domain", "https://archive.org/download/stag1/stag1.mp4", 1000))
        self.assertEqual(got[1]["licence"], "CC BY")
        self.assertTrue(all("ecole" not in i["url"] for i in got))
        self.assertEqual(sum(1 for u in self.asked if u.startswith(freeadult.META)), 3)   # (what's left out by its listing isn't asked about)
        freeadult.listing("vintage", 25)
        self.assertEqual(sum(1 for u in self.asked if u.startswith(freeadult.SEARCH)), 1)   # (kept a while)

    def test_the_words_that_keep_a_film_off(self):
        for text in ("Teen", "schoolgirl", "step-sister", "Forced", "hidden cam", "Hentai OVA", "barely legal", "Young wife", "first time"):
            self.assertTrue(freeadult.blocked(text), text)
        for text in ("Blonde stag film", "Vintage striptease", "Bettie Page", "Massages", "Miss Butterfly"):
            self.assertFalse(freeadult.blocked(text), text)
        self.assertFalse(freeadult.old_enough("1985", "stag film"))
        self.assertFalse(freeadult.old_enough("", "1950s stag film on DVD"))
        self.assertTrue(freeadult.old_enough("1972", "a film"))
        self.assertFalse(freeadult.old_enough("", "a film"))
        self.assertIsNone(freeadult.free_licence("https://creativecommons.org/licenses/by-nc-nd/4.0/x") and None)
        self.assertEqual(freeadult.free_licence("http://www.example.com/rights"), None)

    def test_saving_queues_them_into_adult_with_their_titles_once(self):
        got = freeadult.save("vintage", 5)
        self.assertEqual(got, {"queued": 4, "skipped": 0})
        rows = store.q("SELECT url, adult, title, state FROM downloads ORDER BY id")
        self.assertEqual([(r["adult"], r["state"]) for r in rows], [(1, "queued")] * 4)
        self.assertEqual(rows[0]["title"], "Blonde stag film (1925)")                   # (its year, from the Archive)
        self.assertEqual(freeadult.save("vintage", 5), {"queued": 0, "skipped": 4})
        one = "https://archive.org/download/stag1/stag1.mp4"
        store.ex("DELETE FROM downloads")
        self.assertEqual(freeadult.save("vintage", 5, {one}), {"queued": 1, "skipped": 0})

    def test_only_an_admin_who_may_see_adult_gets_the_page(self):
        httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        try:
            for name, admin in (("free-boss", True), ("free-plain", True), ("free-viewer", False)):
                if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                    auth.create_user(name, "password123", admin=admin)
            for name in ("free-boss", "free-viewer"):
                i = store.q1("SELECT id FROM users WHERE name = ?", name)["id"]
                auth.set_adult(i, True)
                auth.confirm_age(i)
            boss, plain, viewer = (Someone(base, n) for n in ("free-boss", "free-plain", "free-viewer"))
            status, body = boss.call("/api/adult/free?cat=vintage&n=5")
            self.assertEqual(status, 200)
            self.assertEqual(len(body["items"]), 4)
            self.assertEqual(plain.call("/api/adult/free?cat=vintage&n=5")[0], 404)       # (no Adult)
            self.assertEqual(viewer.call("/api/adult/free?cat=vintage&n=5")[0], 403)      # (not an admin)
            self.assertEqual(viewer.call("/api/adult/free", {"cat": "vintage", "n": 5})[0], 404)
            status, body = boss.call("/api/adult/free", {"cat": "vintage", "n": 5})
            self.assertEqual((status, body["queued"]), (200, 4))
            self.assertEqual(len(body["saving"]["rows"]), 4)
            said = " ".join(r["message"] for r in store.q("SELECT message FROM activity ORDER BY id DESC LIMIT 5"))
            self.assertNotIn("stag", said.lower())
        finally:
            httpd.shutdown()
            httpd.server_close()


class SeveralLinksAndHowMany(unittest.TestCase):
    def setUp(self):
        fetch._table()
        store.ex("DELETE FROM downloads")
        self.before = config.get("offline")
        config.update({"offline": False})

    def tearDown(self):
        store.ex("DELETE FROM downloads")
        config.update({"offline": self.before})

    def test_several_links_at_once_and_a_playlist_count(self):
        httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            if not store.q1("SELECT 1 FROM users WHERE name = 'link-admin'"):
                auth.create_user("link-admin", "password123", admin=True)
            admin = Someone("http://127.0.0.1:%d" % httpd.server_address[1], "link-admin")
            status, body = admin.call("/api/admin/downloads", {"add": {"url": "https://a.example/1\n\nhttps://a.example/2\nnot a link", "playlist": 10}})
            self.assertEqual(status, 200)
            self.assertIn("1 skipped", body["note"])
            self.assertEqual([(r["url"], r["playlist"]) for r in store.q("SELECT url, playlist FROM downloads ORDER BY id")],
                             [("https://a.example/1", 10), ("https://a.example/2", 10)])
        finally:
            httpd.shutdown()
            httpd.server_close()
        with mock.patch.object(fetch, "tool", return_value="/usr/bin/yt-dlp"):
            cmd = fetch._command({"url": "https://a.example/1", "playlist": 10}, "/tmp/x")
            self.assertEqual(cmd[cmd.index("--playlist-end") + 1], "10")
            cmd = fetch._command({"url": "https://a.example/1", "playlist": 1}, "/tmp/x")
            self.assertEqual(cmd[cmd.index("--playlist-end") + 1], "50")


class TheFilesOwnTags(unittest.TestCase):
    def test_performers_and_tags_from_a_files_own_tags(self):
        said = naming.file_says({"artist": "Amber, Indigo & Sage", "genre": "Story; Outdoors/Vintage"})
        self.assertEqual(said, {"performers": ["Amber", "Indigo", "Sage"], "tags": ["Story", "Outdoors", "Vintage"]})
        self.assertEqual(naming.file_says({"artist": "Whoever Posted It", "genre": "Story"}, saved=True),
                         {"performers": [], "tags": ["Story"]})
        self.assertEqual(naming.file_says(None), {"performers": [], "tags": []})
        self.assertEqual(naming.file_says({"artist": "A, a, A"})["performers"], [])     # (one letter isn't a name)


if __name__ == "__main__":
    unittest.main()
