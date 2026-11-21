"""Free to keep in Movies and Shows (sofa/freefilms.py): only what anyone may keep, never adult films, saved into
Movies and Shows with where it came from beside it; only for an admin at home, never on a public Sofa. The Internet
Archive here is a stand-in function and a stand-in download: nothing in these tests reaches the internet."""
import io
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from unittest import mock

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import auth, config, freecopy, freefilms, net, sharing, store, web

PD = "http://creativecommons.org/licenses/publicdomain/"
FILMS = [
    {"identifier": "his_girl_friday", "title": "His Girl Friday", "year": "1940", "licenseurl": PD, "collection": ["feature_films"],
     "subject": ["comedy", "romance"], "description": "<p>A reporter &amp; her editor.</p>", "downloads": 900},
    {"identifier": "his_girl_friday_2", "title": "His Girl Friday (1940)", "year": "1940", "licenseurl": PD, "collection": ["feature_films"], "downloads": 50},
    {"identifier": "the_general", "title": "The General", "year": "1926", "collection": ["feature_films", "silent_films"], "subject": "silent", "downloads": 800},
    {"identifier": "later_unmarked", "title": "A Later Film", "year": "1952", "collection": ["feature_films"], "downloads": 700},
    {"identifier": "sita", "title": "Sita Sings the Blues", "year": "2008", "licenseurl": "http://creativecommons.org/licenses/by-sa/3.0/",
     "collection": ["feature_films"], "subject": "animation", "downloads": 600},
    {"identifier": "nc_film", "title": "A Shared Short", "year": "2011", "licenseurl": "http://creativecommons.org/licenses/by-nc-nd/3.0/", "collection": ["feature_films"], "downloads": 500},
    {"identifier": "madness", "title": "Sex Madness", "year": "1938", "licenseurl": PD, "collection": ["feature_films"], "subject": "exploitation", "downloads": 400},
    {"identifier": "nudist", "title": "Diary of a Nudist", "year": "1961", "licenseurl": PD, "collection": ["feature_films"], "downloads": 300},
    {"identifier": "bad/id", "title": "Odd", "year": "1930", "licenseurl": PD, "collection": ["feature_films"], "downloads": 200},
]
TV = [{"identifier": "BH_Ep01", "title": "Beverly Hillbillies Ep01 The Clampetts Strike Oil", "licenseurl": PD + "mark/", "collection": ["classic_tv"], "downloads": 90},
      {"identifier": "BH_servants", "title": "The Beverly Hillbillies : The Servants", "licenseurl": "http://creativecommons.org/publicdomain/mark/1.0/", "collection": ["classic_tv"], "downloads": 80},
      {"identifier": "bonanza_pd", "title": "Bonanza public domain episodes", "year": "1959", "licenseurl": "http://creativecommons.org/publicdomain/mark/1.0/", "collection": ["classic_tv"], "downloads": 70}]
FILES = {"his_girl_friday": [{"name": "HisGirlFriday_512kb.mp4", "format": "512Kb MPEG4", "size": "100"}, {"name": "HisGirlFriday.mp4", "format": "h.264", "size": "900", "length": "5520"},
                             {"name": "HisGirlFriday.gif", "size": "5"}, {"name": "HisGirlFriday_meta.xml", "size": "3", "source": "metadata"}],
         "BH_Ep01": [{"name": "bh01.mp4", "format": "h.264", "size": "300"}],
         "BH_servants": [{"name": "bh_servants.mp4", "format": "h.264", "size": "300"}],
         "bonanza_pd": [{"name": "Bonanza - Ep 03 - The Paiute War.mp4", "format": "h.264", "size": "200", "title": "Bonanza Ep 03 The Paiute War"},
                        {"name": "Bonanza - Silent Thunder.mp4", "format": "h.264", "size": "200", "title": "Silent Thunder"}]}


class Archive:
    def __init__(self):
        self.asked, self.down = [], False

    def __call__(self, url):
        self.asked.append(url)
        if self.down:
            raise urllib.error.URLError("the Archive is down")
        if url.startswith(freefilms.SEARCH):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["q"]
            return {"response": {"docs": TV if "classic_tv" in q else FILMS}}
        item = urllib.parse.unquote(url[len(freefilms.META):])
        doc = next((d for d in FILMS + TV if d["identifier"] == item), None)
        return {"metadata": dict(doc, creator="An uploader"), "files": FILES.get(item, [{"name": item + ".mp4", "format": "h.264", "size": "400"}])} if doc else {}


class Download(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


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
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, e.read()


class FreeToKeep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        for name, admin in (("free-admin", True), ("free-viewer", False), ("free-kid", False)):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123", admin=admin)
        auth.set_kids(store.q1("SELECT id FROM users WHERE name = 'free-kid'")["id"], True)
        cls.admin, cls.viewer, cls.kid = (Someone(cls.base, n) for n in ("free-admin", "free-viewer", "free-kid"))
        cls.visitor = Someone(cls.base, token=auth.start_session(sharing.visitor_user()["id"], "127.0.0.1", "test"))

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        store.ex("DELETE FROM users WHERE guest != 0")

    def setUp(self):
        self.archive = Archive()
        freefilms.fetch_json = self.archive
        freefilms._cache.clear()
        with freefilms._lock:
            del freefilms._jobs[:]
        self.before = config.get("offline")
        config.update({"offline": False})
        self.got = []

        def urlopen(req, timeout=20, handlers=(), whole_internet=True):
            self.got.append(req.full_url)
            return Download(b"V" * 900)
        patch = mock.patch.object(net, "urlopen", urlopen)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.settle()
        freefilms.fetch_json = None
        freefilms._cache.clear()
        config.update({"offline": self.before})

    def settle(self, seconds=10):
        end = time.time() + seconds
        while time.time() < end and any(j["state"] in ("queued", "working") for j in freefilms.status()["jobs"]):
            time.sleep(0.05)

    # ------------------------------------------------------------ what's offered

    def test_only_what_anyone_may_keep_and_never_adult_films(self):
        got = freefilms.catalogue("movies")
        self.assertEqual([(f["id"], f["why"]) for f in got], [
            ("his_girl_friday", "Public domain"), ("the_general", "Public domain (made in 1926)"),
            ("sita", "CC BY-SA"), ("nc_film", "CC BY-NC-ND")])
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.archive.asked[0]).query))["q"]
        self.assertIn("-collection:(no-preview)", q)                    # (the Archive's own adult collection, asked away)
        hgf = got[0]
        self.assertEqual((hgf["title"], hgf["year"], hgf["kind"], hgf["about"]), ("His Girl Friday", 1940, "Comedy", "A reporter & her editor."))
        self.assertEqual(freefilms.licence_words("Public domain (made in 1926)"), "Made before 1929: its copyright in the United States has run out.")
        freefilms.catalogue("movies")
        self.assertEqual(len(self.archive.asked), 1)                      # (kept six hours)

    def test_a_film_in_full_its_best_file(self):
        it = freefilms.item("his_girl_friday")
        self.assertEqual([f["file"] for f in it["files"]], ["HisGirlFriday.mp4"])
        self.assertEqual((it["length"], it["who"], it["why"]), (5520, "An uploader", "Public domain"))
        self.assertIsNone(freefilms.item("later_unmarked"))
        self.assertIsNone(freefilms.item("../etc"))

    def test_a_show_from_its_items_with_episode_numbers(self):
        shows = {s["id"]: s for s in freefilms.catalogue("shows")}
        self.assertEqual(sorted(shows), ["beverly-hillbillies", "bonanza"])
        self.assertEqual(shows["beverly-hillbillies"]["items"], ["BH_Ep01", "BH_servants"])
        self.assertIsNone(shows["bonanza"]["kind"])                        # (a show the Archive gives no kind isn't "Drama")
        eps = freefilms.show("bonanza")["episodes"]
        self.assertEqual([(e["n"], e["name"]) for e in eps], [(1, "Silent Thunder"), (3, "The Paiute War")])
        FILES["BH_servants"] = [{"name": "bh_servants.mp4", "format": "h.264", "size": "300", "title": "Ep01 The Servants"}]   # (it says 1 too)
        self.addCleanup(FILES.__setitem__, "BH_servants", [{"name": "bh_servants.mp4", "format": "h.264", "size": "300"}])
        freefilms._cache.clear()
        dup = freefilms.show("beverly-hillbillies")["episodes"]
        self.assertEqual(sorted(e["n"] for e in dup), [1, 2])                            # (two parts that both say 1: 1 and 2)
        FILES["BH_servants"] = [{"name": "bh_servants.mp4", "format": "h.264", "size": "300"}]
        freefilms._cache.clear()
        bh = freefilms.show("beverly-hillbillies")["episodes"]
        self.assertEqual([(e["n"], e["name"]) for e in bh], [(1, "The Clampetts Strike Oil"), (2, "The Servants")])

    # ------------------------------------------------------------ saving

    def test_a_film_goes_into_movies_with_its_licence_beside_it(self):
        out = freefilms.save_movie("his_girl_friday", "free-admin")
        self.assertEqual(out, {"queued": 1, "skipped": 0})
        self.settle()
        dest = os.path.join(config.path("movies"), "His Girl Friday (1940)", "His Girl Friday (1940).mp4")
        self.addCleanup(lambda: __import__("shutil").rmtree(os.path.dirname(dest), True))
        self.assertTrue(os.path.isfile(dest))
        self.assertEqual(self.got, ["https://archive.org/download/his_girl_friday/HisGirlFriday.mp4"])
        nfo = open(os.path.splitext(dest)[0] + ".nfo", encoding="utf-8").read()
        self.assertNotIn("<tag>Public domain</tag>", nfo)                 # (a licence isn't a genre on the Movies page)
        for bit in ("<title>His Girl Friday</title>", "<year>1940</year>", "<genre>Comedy</genre>", "<tag>Free to keep</tag>", "<licence>Public domain</licence>",
                    "<source>https://archive.org/details/his_girl_friday</source>", "<licenseurl>%s</licenseurl>" % PD):
            self.assertIn(bit, nfo)
        self.assertEqual(freefilms.status()["items"]["his_girl_friday"]["left"], 0)
        self.assertEqual(freefilms.save_movie("his_girl_friday"), {"queued": 0, "skipped": 1})       # (it's there already)
        self.assertFalse(os.listdir(os.path.dirname(dest)) and [f for f in os.listdir(os.path.dirname(dest)) if f.startswith(".sofa-free")])

    def test_a_shows_episodes_go_into_shows(self):
        out = freefilms.save_show("bonanza", who="free-admin")
        self.assertEqual(out["queued"], 2)
        self.settle()
        season = os.path.join(config.path("shows"), "Bonanza", "Season 1")
        self.addCleanup(lambda: __import__("shutil").rmtree(os.path.dirname(season), True))
        self.assertEqual(sorted(f for f in os.listdir(season) if f.endswith(".mp4")),
                         ["Bonanza S01E01 Silent Thunder.mp4", "Bonanza S01E03 The Paiute War.mp4"])
        self.assertEqual(freefilms.save_show("bonanza", only={"Bonanza - Silent Thunder.mp4"}), {"queued": 0, "skipped": 1})

    def test_a_download_that_stops_leaves_nothing_behind(self):
        def broken(req, timeout=20, handlers=(), whole_internet=True):
            raise urllib.error.URLError("connection reset")
        with mock.patch.object(net, "urlopen", broken):
            freefilms.save_movie("the_general")
            self.settle()
        job = freefilms.status()["jobs"][-1]
        self.assertEqual(job["state"], "failed")
        self.assertIn("The download stopped", job["error"])
        self.assertFalse(os.path.exists(os.path.join(config.path("movies"), "The General (1926)")))

    def test_offline_nothing_is_saved(self):
        config.update({"offline": True})
        with self.assertRaises(ValueError):
            freefilms.save_movie("his_girl_friday")

    # ------------------------------------------------------------ who

    def test_only_an_admin_at_home_and_never_on_a_public_sofa(self):
        status, out = self.admin.call("/api/free/movies")
        self.assertEqual((status, [f["id"] for f in out["items"]][:2]), (200, ["his_girl_friday", "the_general"]))
        self.assertEqual(self.admin.call("/api/free/movie/his_girl_friday")[1]["files"][0]["file"], "HisGirlFriday.mp4")
        for who, name in ((self.viewer, "not an admin"), (self.kid, "a Kids profile"), (self.visitor, "a visitor")):
            for path in ("/api/free/movies", "/api/free/shows", "/api/free/movie/his_girl_friday", "/api/free/status"):
                self.assertIn(who.call(path)[0], (401, 403, 404), "%s reached %s" % (name, path))
            self.assertIn(who.call("/api/free/save", {"kind": "movie", "id": "his_girl_friday"})[0], (401, 403, 404), name)
        with mock.patch.object(config, "demo_on", return_value=True):
            self.assertFalse(web.Handler.free_ok(mock.Mock(network=lambda: "home"), {"admin": True}))
        self.assertFalse(web.Handler.free_ok(mock.Mock(network=lambda: "internet"), {"admin": True}))
        self.assertEqual(freefilms.status()["jobs"], [])

    def test_the_archive_down_is_a_plain_answer(self):
        self.archive.down = True
        status, out = self.admin.call("/api/free/movies")
        self.assertEqual(status, 200)
        self.assertIn("The Internet Archive didn't answer", out["error"])
        self.archive.down = False
        self.assertEqual(len(self.admin.call("/api/free/movies")[1]["items"]), 4)      # (a failure isn't kept)

    # ------------------------------------------------------------ one source

    def test_the_discs_free_copy_goes_through_the_same_queue(self):
        freecopy._found.clear()
        self.addCleanup(freecopy._found.clear)
        hit = freecopy.find("His Girl Friday", 1940, get=lambda url, timeout=20: self.archive(url))
        self.assertEqual((hit["id"], hit["why"], hit["file"]), ("his_girl_friday", "public domain", "HisGirlFriday.mp4"))
        self.assertIsNone(freecopy.free({"licenseurl": "http://creativecommons.org/licenses/by-nc-nd/3.0/"}))    # (the disc: any use only)
        with mock.patch.object(freecopy, "find", return_value=hit), mock.patch("sofa.disc._room", lambda *a: None):
            freecopy.download("His Girl Friday", 1940, "free-admin")
            self.settle()
        dest = os.path.join(config.path("movies"), "His Girl Friday (1940)")
        self.addCleanup(lambda: __import__("shutil").rmtree(dest, True))
        self.assertEqual(freecopy.status()["state"], "done")
        self.assertEqual(freefilms.status()["jobs"][-1]["item"], "his_girl_friday")
        self.assertTrue(os.path.isfile(os.path.join(dest, "His Girl Friday (1940).mp4")))

    def test_the_pages(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "client", "app.js"), encoding="utf-8") as f:
            js = f.read()
        for text in ('<a class="btn keep-entry" href="#/free/movies">${icon("i-download")}Free to keep</a>', '<a class="btn keep-entry" href="#/free/shows">${icon("i-download")}Free to keep</a>',
                     "[data-keep-tab],[data-keep-save],",
                     "function viewKeep(kind)", "function viewKeepTitle(kind, id)", "Whose word", "Adult films are never here."):
            self.assertIn(text, js)


if __name__ == "__main__":
    unittest.main()
