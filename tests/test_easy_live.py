"""Sofa 1.5.41: Live TV for someone who plugs a Sofa Box into a TV and expects channels to just work.

- Sofa's own free channels: more of them (Kids, Shopping, Faith and more News), each saying what's on it in a few
  words, numbered in the order Live TV shows them; one is the channel the TV look opens on.
- A feed made for FAST services is refused by its host's name too (fast-channels.<a broadcaster>.com).
- A picture of what's on a channel now, for the guide and rows looks: one frame, never a tuner's.
- An HDHomeRun's own guide comes by itself, so Antenna's guide and recording a programme work with nothing typed in.
- Live TV opens on Live now, with three looks to switch between (guide, rows, TV).

The tuner is a stand-in (tests/stand_in_tuner.py), and so is SiliconDust's guide service: no real HDHomeRun or
real guide answered these tests.
"""
import io
import json
import os
import re
import shutil
import tempfile
import time
import unittest
import urllib.parse

from tests import ROOT
from sofa import config, demo, dvr, guide, live, media, store, tuners
from tests.stand_in_tuner import DEVICE, Tuner

FFMPEG = media.tool("ffmpeg")
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "client", "app.js")


def the_file():
    with open(live.FREE_FILE, encoding="utf-8") as f:
        return json.load(f)["channels"]


class FreeChannelsForABox(unittest.TestCase):
    def setUp(self):
        self.before = {k: config.get(k) for k in ("live_playlists", "free_channels", "offline", "live_check", "archive_channels", "retro_eras")}
        config.update({"live_playlists": [], "free_channels": True, "offline": False, "live_check": False,
                       "archive_channels": False, "retro_eras": False})
        live.refresh(force=True, download=False)

    def tearDown(self):
        config.update(self.before)
        live.refresh(force=True, download=False)

    def test_more_kinds_of_channel_each_saying_whats_on_it(self):
        chans = the_file()
        self.assertGreaterEqual(len(chans), 28)
        groups = {c["group"] for c in chans}
        self.assertTrue({"News", "Kids", "Entertainment", "Shopping", "Faith", "En español"} <= groups, groups)
        for c in chans:
            self.assertTrue(4 <= len(c.get("about") or "") <= 90, c["name"])
            self.assertEqual(demo.channel_problems(c), [], c["name"])
        self.assertEqual([c["name"] for c in chans if c.get("start")], ["FOX Weather"])
        self.assertNotIn("Cheddar News", [c["name"] for c in chans])                # (took a minute to answer)

    def test_numbered_in_the_order_live_tv_shows_them(self):
        rows = [c for c in live.listing(0)["channels"] if c.get("about")]
        self.assertEqual(len(rows), len(the_file()))
        self.assertEqual([c["number"] for c in rows], sorted(c["number"] for c in rows))
        self.assertEqual(rows[0]["number"], live.FIRST_NUMBER)
        fox = next(c for c in rows if c["name"] == "FOX Weather")
        self.assertEqual((fox["about"], fox.get("start")), ("Weather across the US, live all day", True))
        self.assertNotIn("start", next(c for c in rows if c["name"] == "PBS KIDS"))

    def test_a_feed_made_for_fast_services_is_refused_by_its_host(self):
        c = {"name": "Comet", "url": "https://fast-channels.sinclairstoryline.com/COMET/index.m3u8", "group": "Entertainment",
             "publisher": "Sinclair", "page": "https://www.comettv.com/", "kind": "broadcaster", "rights": "x" * 20,
             "cors": True, "checked": "2026-11-20"}
        self.assertTrue(any("FAST" in p for p in demo.channel_problems(c)))
        ok = dict(c, url="https://247wlive.foxweather.com/stream/index.m3u8")
        self.assertEqual(demo.channel_problems(ok), [])


class TheClient(unittest.TestCase):
    """What the page does is seen in the pictures (docs/images/live-tv); these hold the rules that matter."""
    @classmethod
    def setUpClass(cls):
        with open(APP, encoding="utf-8") as f:
            cls.js = f.read()

    def test_live_tv_opens_on_live_now(self):
        self.assertIn('(eras.find(e => e.id === "now") || eras[0]).id', self.js)
        self.assertNotIn('eras.find(e => e.id === "2000s")', self.js)

    def test_three_looks_and_the_tv_look_tunes_in_once(self):
        self.assertIn('const LIVE_LOOKS = [["guide", "Guide"], ["rows", "Rows"], ["tv", "TV"]];', self.js)
        self.assertIn("liveRecent().find(x => !x.down) || all.find(x => x.start) || all[0]", self.js)
        self.assertIn('if (!onLive()) liveOpened = false;', self.js)

    def test_a_picture_is_never_asked_of_a_tuner_or_away_from_home(self):
        m = re.search(r"const stillOf = c => (.*?) \? null", self.js)
        for word in ("c.tuner", "c.adult", "c.down", "c.src", "LITE()", "liveData.away"):
            self.assertIn(word, m.group(1))


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class WithATuner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="sofa-easy-", dir=ROOT)
        cls.box = Tuner(cls.folder, FFMPEG)

    @classmethod
    def tearDownClass(cls):
        cls.box.close()
        shutil.rmtree(cls.folder, True)

    def setUp(self):
        self.before = {k: config.get(k) for k in ("tuners", "guide_sources", "tuner_guide", "live_playlists", "offline")}
        config.update({"tuners": [], "guide_sources": [], "tuner_guide": True, "live_playlists": [], "offline": False})
        tuners._lineups.clear()
        guide._table(); dvr._table()
        for t in ("recordings", "recording_rules", "guide"):
            store.ex("DELETE FROM %s" % t)
        dvr._changed()
        guide._state["sources"].clear()
        tuners.find(timeout=1.0, to="127.0.0.1", port=self.box.udp_port)
        tuners.switch("%08X" % DEVICE, True)
        live.refresh(force=True, download=False)
        self.chans = {c["guide_number"]: c for c in live.all_channels() if c.get("tuner")}
        self.asked, self.real_fetch = [], live.fetch
        t0 = int(time.time()) // 1800 * 1800
        self.answer = [{"GuideNumber": "5.1", "GuideName": "KSTN", "Guide": [
                            {"StartTime": t0, "EndTime": t0 + 1800, "Title": "Local News", "Synopsis": "The day's news.", "Filter": ["News"]},
                            {"StartTime": t0 + 1800, "EndTime": t0 + 3600, "Title": "Quiz Night", "EpisodeNumber": "S03E07",
                             "EpisodeTitle": "Finals", "First": True}]},
                       {"GuideNumber": "99.9", "Guide": [{"StartTime": t0, "EndTime": t0 + 60, "Title": "Nobody's"}]}]

        def fetch(url, *a, **kw):                        # SiliconDust's guide service, stood in for
            if url.startswith(guide.TUNER_GUIDE):
                self.asked.append(url)
                return io.BytesIO(json.dumps(self.answer).encode())
            return self.real_fetch(url, *a, **kw)
        live.fetch = fetch
        self.t0 = t0

    def tearDown(self):
        live.fetch = self.real_fetch
        with dvr._lock:
            running = list(dvr._procs.values())
            dvr._procs.clear()
        for p in running:
            if p["proc"].poll() is None:
                p["proc"].kill()
            p["proc"].wait()
        store.ex("DELETE FROM recordings")
        config.update(self.before)
        tuners._lineups.clear()
        live.refresh(force=True, download=False)

    def test_the_tuners_own_guide_comes_by_itself(self):
        self.assertEqual(guide.sources(), [])                                        # nothing typed in
        self.assertEqual(guide.refresh(force=True), 2)
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(self.asked[0]).query)["DeviceAuth"], ["stand-in-key+/="])
        progs = guide.on(self.chans["5.1"]["id"], self.t0, self.t0 + 3600)
        self.assertEqual([(p["title"], p["season"], p["episode"], p["sub"]) for p in progs],
                         [("Local News", None, None, None), ("Quiz Night", 3, 7, "Finals")])
        self.assertEqual(progs[1]["fresh"], 1)
        st = guide.status()
        self.assertTrue(st["tuner_guide"])
        self.assertEqual([(s["auto"], s["programmes"]) for s in st["sources"]], [(True, 2)])

    def test_and_a_programme_records_from_it(self):
        guide.refresh(force=True)
        r = dvr.record_programme(self.chans["5.1"]["id"], self.t0 + 1800)
        self.assertEqual((r["title"], r["season"], r["episode"]), ("Quiz Night", 3, 7))

    def test_switched_off_or_offline_nothing_is_asked(self):
        config.update({"tuner_guide": False})
        self.assertEqual(guide.refresh(force=True), 0)
        self.assertEqual(self.asked, [])
        config.update({"tuner_guide": True, "offline": True})
        live.fetch = self.real_fetch                     # offline: the real one says no before anything is sent
        guide.refresh(force=True)
        self.assertEqual(guide.on(self.chans["5.1"]["id"], self.t0, self.t0 + 3600), [])
        self.assertTrue(guide.status()["sources"][0]["error"])

    def test_a_picture_of_whats_on_never_from_a_tuner(self):
        tuned = self.chans["11.3"]
        self.assertIsNone(live.still(tuned))                                       # it would take a tuner
        plain = dict(tuned, id="ab12cd34ef56")
        plain.pop("tuner")                                                         # the same stream, as a list at home has it
        path = live.still(plain)
        self.assertTrue(path and os.path.getsize(path) > 500)
        with open(path, "rb") as f:
            self.assertEqual(f.read(3), b"\xff\xd8\xff")                           # a JPEG
        os.utime(path, (0, 0))
        self.assertEqual(live.still(plain), path)                                   # made again when old
        self.assertGreater(os.path.getmtime(path), time.time() - 60)
        os.remove(path)
        self.assertIsNone(live.still(dict(plain, adult=True)))


if __name__ == "__main__":
    unittest.main()
