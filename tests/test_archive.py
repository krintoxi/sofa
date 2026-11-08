"""Live TV's Internet Archive channels (sofa/archive.py): films on a loop, on the clock; one playable file each;
nothing that doesn't belong on a family TV; fetched once a week. A stand-in for archive.org."""
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.parse

import tests  # noqa: F401  (sets Sofa up for the tests)
from tests.test_server import Client
from sofa import archive, auth, config, store, web

DOCS = [{"identifier": "noir1", "title": "Scarlet Street"}, {"identifier": "bundle", "title": "Silent Hall of Fame"},
        {"identifier": "bad", "title": "Sex Madness"}, {"identifier": "noir2", "title": "The Stranger"},
        {"identifier": "quiet", "title": "Hidden Exploitation"}, {"identifier": "short", "title": "A Trailer"}]
META = {
    "noir1": {"metadata": {"title": "Scarlet Street", "year": "1945"}, "files": [
        {"name": "scarlet.mp4", "source": "derivative", "original": "scarlet.avi", "length": "1:43:00", "height": "480", "size": "400"},
        {"name": "scarlet_hd.mp4", "source": "derivative", "original": "scarlet.avi", "length": "1:43:00", "height": "1080", "size": "900"}]},
    "noir2": {"metadata": {"title": "The Stranger", "date": "1946-07-10"}, "files": [
        {"name": "stranger.mp4", "source": "original", "length": "95 min", "height": "480", "size": "300"}]},
    "bundle": {"metadata": {"title": "Silent Hall of Fame"}, "files": [
        {"name": "f%d.mp4" % n, "source": "original", "length": "10:00"} for n in range(6)]},
    "quiet": {"metadata": {"title": "Hidden", "subject": ["erotica", "1960s"]}, "files": [
        {"name": "h.mp4", "source": "original", "length": "1:10:00"}]},
    "short": {"metadata": {"title": "A Trailer"}, "files": [{"name": "t.mp4", "source": "original", "length": "1:30"}]},
}


class Archive(unittest.TestCase):
    def setUp(self):
        self.asked = []
        self.real_get, self.real_cache = archive._get, archive.CACHE
        archive.CACHE = tempfile.mkdtemp()

        def fake(url, timeout=30):
            self.asked.append(url)
            if "advancedsearch" in url:
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"][0]
                self.assertIn("NOT title:(sex", q)                       # the family filter goes in every search
                return {"response": {"docs": DOCS}}
            ident = urllib.parse.unquote(url.rsplit("/", 1)[1])
            return META[ident]
        archive._get = fake
        self.before = {k: config.get(k) for k in ("offline", "archive_channels")}
        config.update({"offline": False, "archive_channels": True})

    def tearDown(self):
        archive._get, archive.CACHE = self.real_get, self.real_cache
        config.update(self.before)

    def test_lengths(self):
        for text, want in (("1:17:26", 4646), ("95 min", 5700), ("01:18:35", 4715), ("123.4", 123), ("?", None), ("", None)):
            self.assertEqual(archive.seconds(text), want, text)

    def test_one_playable_film_each_and_nothing_unsuitable(self):
        films = archive.films("ia-noir")
        self.assertEqual([f["id"] for f in films], ["noir1", "noir2"])      # not the bundle, the unsuitable ones, the trailer
        self.assertEqual(films[0]["url"], "https://archive.org/download/noir1/scarlet.mp4")   # the 480p copy (a Pi plays it)
        self.assertEqual((films[0]["year"], films[1]["year"]), (1945, 1946))
        self.assertEqual(films[1]["length"], 5700)
        n = len(self.asked)
        archive.films("ia-noir")                                         # kept for a week: the archive isn't asked again
        self.assertEqual(len(self.asked), n)

    def test_on_the_clock(self):
        a = archive.now("ia-noir", at=archive.ANCHOR + 60)
        self.assertEqual((a["film"]["id"], a["offset"], a["next"][0]["id"]), ("noir1", 60, "noir2"))
        b = archive.now("ia-noir", at=archive.ANCHOR + 6180 + 10)          # 1:43:00 in: the second film, 10 s in
        self.assertEqual((b["film"]["id"], b["offset"]), ("noir2", 10))
        c = archive.now("ia-noir", at=archive.ANCHOR + 6180 + 5700 + 5)     # round again
        self.assertEqual((c["film"]["id"], c["offset"]), ("noir1", 5))

    def test_off_when_offline(self):
        self.assertEqual(len(archive.channels()), len(archive.CHANNELS))
        self.assertTrue(archive.channels()[0]["logo"].startswith("data:image/svg+xml"))
        config.update({"offline": True})
        self.assertEqual(archive.channels(), [])

    def test_retro_tv(self):
        """A decade's shows with its commercials between them (three to a break), and the card says what's coming."""
        shows = [{"identifier": "show%d" % n, "title": "Show %d" % n} for n in range(3)]
        ads = [{"identifier": "ad%d" % n, "title": "Ad %d" % n} for n in range(4)]

        def fake(url, timeout=30):
            if "advancedsearch" in url:
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"][0]
                return {"response": {"docs": ads if "classic_tv_commercials" in q else shows}}
            ident = urllib.parse.unquote(url.rsplit("/", 1)[1])
            length = "0:30" if ident.startswith("ad") else "25:00"
            return {"metadata": {"title": ident, "year": "1962"}, "files": [{"name": ident + ".mp4", "source": "original", "length": length}]}
        archive._get = fake
        items = archive.films("ia-retro60")
        self.assertEqual([("ad" if i.get("ad") else i["id"]) for i in items],
                         ["show0", "ad", "ad", "ad", "show1", "ad", "ad", "ad", "show2", "ad", "ad", "ad"])
        self.assertEqual([i["id"] for i in items if i.get("ad")][:5], ["ad0", "ad1", "ad2", "ad3", "ad0"])
        at = archive.ANCHOR + 1500 + 5                                      # into the first break
        self.assertTrue(archive.now("ia-retro60", at=at)["film"].get("ad"))
        card = next(c for c in archive.channels() if c["id"] == "ia-retro60")
        self.assertIn("Retro TV: 60s", card["name"])

    def test_a_title_given_as_a_list(self):
        """The archive gives some titles as a list: filtered like the rest (they used to stop every channel's films
        being fetched), and one channel that fails doesn't keep the others from theirs."""
        docs = [{"identifier": "two", "title": ["Detour", "Detour (1945)"]},
                {"identifier": "bad", "title": ["Fine", "Sex Madness"]}]

        def fake(url, timeout=30):
            if "advancedsearch" in url:
                if "Westerns" in url or "western" in url:
                    raise RuntimeError("an odd answer")
                return {"response": {"docs": docs}}
            ident = urllib.parse.unquote(url.rsplit("/", 1)[1])
            title = {"two": ["Detour", "Detour (1945)"], "bad": "Fine"}[ident]
            return {"metadata": {"title": title, "year": "1945"},
                    "files": [{"name": ident + ".mp4", "source": "original", "length": "1:08:00"}]}
        archive._get = fake
        films = archive.films("ia-noir")
        self.assertEqual([(f["id"], f["title"]) for f in films], [("two", "Detour")])
        archive._warm_once()
        made = os.listdir(archive.CACHE)
        for cid in ("ia-classics", "ia-comedy", "ia-kids00", "ia-retro00", "ia-retro50"):
            self.assertTrue(any(m.startswith(cid + "-") for m in made), cid)
        self.assertFalse(any(m.startswith("ia-westerns-") for m in made))

    def test_the_guide(self):
        """Programmes on the clock, now to three hours on, the commercials after a show counted as the show's; a channel
        not fetched yet has none (the guide never waits on the archive)."""
        shows = [{"identifier": "show%d" % n, "title": "Show %d" % n} for n in range(3)]
        ads = [{"identifier": "ad%d" % n, "title": "Ad %d" % n} for n in range(4)]

        def fake(url, timeout=30):
            if "advancedsearch" in url:
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"][0]
                return {"response": {"docs": ads if "classic_tv_commercials" in q else shows}}
            ident = urllib.parse.unquote(url.rsplit("/", 1)[1])
            return {"metadata": {"title": ident, "year": "1962"},
                    "files": [{"name": ident + ".mp4", "source": "original", "length": "0:30" if ident.startswith("ad") else "25:00"}]}
        archive._get = fake
        archive.films("ia-retro60")
        at = archive.ANCHOR + 1500 + 45                     # into the first break: still Show 0's half hour
        g = {c["id"]: c for c in archive.guide(at=at)}
        p = g["ia-retro60"]["programs"]
        self.assertEqual([x["id"] for x in p[:5]], ["show2", "show0", "show1", "show2", "show0"])   # (the one before too)
        self.assertEqual((p[0]["end"], p[1]["start"], p[1]["end"]), (archive.ANCHOR, archive.ANCHOR, archive.ANCHOR + 1590))
        self.assertEqual(p[2]["start"], p[1]["end"])
        later = archive.guide(at=archive.ANCHOR + 1590 * 2 + 10)       # Show 2 on, Show 1 just before it
        self.assertEqual([x["id"] for x in next(c for c in later if c["id"] == "ia-retro60")["programs"][:2]], ["show1", "show2"])
        self.assertGreaterEqual(p[-1]["end"], at + 3 * 3600)
        self.assertLess(p[-2]["end"], at + 3 * 3600)
        self.assertEqual((g["ia-retro60"]["tapes"], g["ia-retro60"]["number"]), (3, 13))
        self.assertEqual(g["ia-noir"]["programs"], [])      # not fetched yet

    def test_variety(self):
        """Three of one series at most (an upload in twenty parts, a show's every episode), and the family filter
        knows the words the 2000s searches turned up."""
        docs = [{"identifier": "xp%d" % n, "title": "X-Play 2008.11.%02d" % n} for n in range(8)] + \
               [{"identifier": "g4", "title": "G4 Icons: Sega Dreamcast"}, {"identifier": "pot", "title": "Marijuana infomercial"}]
        self.assertEqual([d["identifier"] for d in archive._varied(docs)], ["xp0", "xp1", "xp2", "g4", "pot"])
        self.assertTrue(archive.NOT_WORDS.search("ACLU Marijuana infomercial"))
        self.assertTrue(archive.NOT_WORDS.search("JAILBAIT! (MTV, 2000)"))

    def test_recorded_tapes(self):
        """00s Kids TV and 00s On Air play whole recorded tapes: hours long, so not held to a film's length, and no
        short clips."""
        docs = [{"identifier": i, "title": i} for i in ("tape", "clip", "toolong", "film")]
        lengths = {"tape": "3:30:00", "clip": "5:00", "toolong": "5:00:00", "film": "1:30:00"}

        def fake(url, timeout=30):
            if "advancedsearch" in url:
                return {"response": {"docs": docs}}
            ident = urllib.parse.unquote(url.rsplit("/", 1)[1])
            return {"metadata": {"title": ident, "year": "2003"},
                    "files": [{"name": ident + ".mp4", "source": "original", "length": lengths[ident]}]}
        archive._get = fake
        self.assertEqual([f["id"] for f in archive.films("ia-kids00")], ["tape", "film"])
        self.assertEqual([f["id"] for f in archive.films("ia-air00")], ["tape", "film"])

    def test_in_live_tv(self):
        httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            if not store.q1("SELECT 1 FROM users WHERE name = 'archivetest'"):
                auth.create_user("archivetest", "password123")
            c = Client("http://127.0.0.1:%d" % httpd.server_address[1])
            self.assertEqual(c.call("/api/login", {"name": "archivetest", "password": "password123"})[0], 200)
            status, live = c.call("/api/live")
            self.assertEqual(status, 200)
            ia = [ch for ch in live["channels"] if ch.get("archive")]
            self.assertEqual({ch["group"] for ch in ia}, {"Internet Archive", "Retro TV"})
            retro = [ch["id"] for ch in ia if ch["group"] == "Retro TV"]
            self.assertEqual(retro[:3], ["ia-retro00", "ia-kids00", "ia-sat00"])      # the 2000s first, on the dial from 2
            self.assertEqual([ch["number"] for ch in ia][:3], [2, 3, 4])
            self.assertEqual(len(retro), 13)
            self.assertTrue(all(ch["about"] for ch in ia))
            status, g = c.call("/api/live/guide")
            self.assertEqual(status, 200)
            self.assertEqual(len(g["channels"]), len(ia))
            status, on = c.call("/api/live/archive/ia-noir/now")
            self.assertEqual(status, 200)
            self.assertIn(on["film"]["id"], ("noir1", "noir2"))
            self.assertEqual(c.call("/api/live/archive/ia-nothing/now")[0], 404)
            for ch in ia:                                    # every channel can be tuned to (Retro TV's ids have digits)
                status, on = c.call("/api/live/archive/%s/now" % ch["id"])
                self.assertNotEqual(status, 404, ch["id"])      # (503: the stand-in films don't suit every channel)
                if status == 200:
                    self.assertEqual(on["channel"], ch["id"])
            self.assertEqual(c.call("/api/live/archive/ia-kids00/now")[0], 200)     # whole tapes: the stand-ins suit it
        finally:
            httpd.shutdown()
            shutil.rmtree(archive.CACHE, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
