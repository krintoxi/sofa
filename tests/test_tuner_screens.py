"""Live TV's screens for the household's own tuners, in a browser (Sofa 1.5.14): Antenna (the tuners' channels on the
clock, from the guide), the Record dialog, Live TV → Recordings, REC in the player, and Server → Live TV's tuners
and guide. Against the stand-in tuner (tests/stand_in_tuner.py) and an XMLTV guide written for the moment it runs.
No real tuner, and no real TV, has run any of it."""
import datetime
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)
from tests import ROOT
from sofa import auth, config, dvr, guide, live, media, store, tuners, web
from tests.stand_in_tuner import Tuner
from tests.test_box_speed import Page, chrome, free_port

KEY = {"ArrowDown": 40, "ArrowUp": 38, "ArrowLeft": 37, "ArrowRight": 39, "Enter": 13}


def stamp(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def xmltv(now):
    """A guide for the stand-in's channels: the half hour now, then the evening. 11.3 is listed with no programmes."""
    t0 = now - now % 1800
    shows = [("kstn", t0, t0 + 1800, "Evening News", ""),
             ("kstn", t0 + 1800, t0 + 5400, "Harbor Patrol", '<sub-title>Low Tide</sub-title><episode-num system="xmltv_ns">1.3.0/1</episode-num><new/>'),
             ("kstn", t0 + 5400, t0 + 12600, "The Long Night", "<category>Movie</category><date>1958</date>"),
             ("kstn", t0 + 12600, t0 + 16200, "Harbor Patrol", '<sub-title>The Reef</sub-title><episode-num system="xmltv_ns">1.4.0/1</episode-num><new/>'),
             ("two", t0, t0 + 3600, "Two at Noon", ""), ("two", t0 + 3600, t0 + 5400, "Quiz Bowl", "")]
    return ('<?xml version="1.0" encoding="UTF-8"?><tv>'
            '<channel id="kstn"><display-name>5.1 KSTN</display-name></channel>'
            '<channel id="two"><display-name>2.1 Channel Two</display-name></channel>'
            '<channel id="news"><display-name>11.3 News Now</display-name></channel>'
            + "".join('<programme start="%s" stop="%s" channel="%s"><title>%s</title>%s</programme>' % (stamp(a), stamp(b), c, t, x)
                      for c, a, b, t, x in shows) + "</tv>").encode()


@unittest.skipUnless(media.tool("ffmpeg"), "needs ffmpeg (the stand-in tuner's channel)")
class TheTunerScreens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.before = {k: config.get(k) for k in ("tuners", "guide_sources", "live_playlists", "offline", "archive_channels",
                                                  "retro_eras", "dvr_pad_before", "dvr_pad_after")}
        cls.folder = tempfile.mkdtemp(prefix="sofa-tuner-screens-", dir=ROOT)
        cls.box = Tuner(cls.folder, media.tool("ffmpeg"))
        cls.now = int(time.time())
        cls.xml = os.path.join(cls.folder, "guide.xml")
        with open(cls.xml, "wb") as f:
            f.write(xmltv(cls.now))
        config.update({"tuners": [], "live_playlists": [], "offline": True, "archive_channels": False, "retro_eras": False,
                       "guide_sources": [{"path": cls.xml}], "dvr_pad_before": 1, "dvr_pad_after": 3})
        tuners._lineups.clear()
        tuners.add(cls.box.base)
        live.refresh(force=True)
        assert guide.refresh(force=True) == 6
        cls.chans = {c["guide_number"]: c for c in live.all_channels() if c.get("tuner")}
        for name, admin in (("tuner-admin", True), ("tuner-viewer", False)):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123", admin=admin)
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        import threading
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.dir = tempfile.mkdtemp(prefix="sofa-tuner-chrome-")
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--mute-audio",
                                       "--window-size=1280,720", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), "about:blank"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.page = Page(cls.devtools, "about:blank")
        cls.page.call("Page.enable")
        cls.page.call("Network.enable")
        cls.page.call("Emulation.setFocusEmulationEnabled", {"enabled": True})   # (focus moves as on a screen in front of someone)
        cls.who = None

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        cls.chrome.terminate()
        try:
            cls.chrome.wait(10)
        except subprocess.TimeoutExpired:
            cls.chrome.kill()
        cls.httpd.shutdown()
        cls.box.close()
        config.update(cls.before)
        tuners._lineups.clear()
        live.refresh(force=True)
        shutil.rmtree(cls.dir, ignore_errors=True)
        shutil.rmtree(cls.folder, ignore_errors=True)

    def setUp(self):
        dvr._table()
        for t in ("recordings", "recording_rules"):
            store.ex("DELETE FROM %s" % t)
        dvr._changed()

    def open(self, who="tuner-viewer", tv=False, era="antenna", width=1280, height=720):
        p = self.page
        p.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        p.call("Page.navigate", {"url": self.base + "/client/manifest.webmanifest"})
        time.sleep(0.4)
        if who != type(self).who:
            p.value("fetch('/api/logout',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},body:'{}'}).then(()=>1,()=>0)")
            status = p.value("fetch('/api/login',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},"
                             "body:JSON.stringify({name:%s,password:'password123'})}).then(r=>r.status)" % json.dumps(who))
            self.assertEqual(status, 200)
            type(self).who = who
        p.value("localStorage.clear(); sessionStorage.setItem('sofaPicked','1'); localStorage.setItem('sofa.installAsk', Date.now());"
                "localStorage.setItem('sofa.tv','%s'); localStorage.setItem('sofa.liveEra', %s); 1" % ("true" if tv else "false", json.dumps(json.dumps(era))))
        p.call("Page.navigate", {"url": self.base + "/?t=%f#/live" % time.time()})
        self.until("!!document.querySelector('.eras [data-era=\"%s\"][aria-selected=\"true\"]')" % era)
        if era == "antenna":
            self.until("document.querySelectorAll('#gRows .g-row').length === 3")
        return p

    def until(self, expression, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if self.page.value(expression):
                return
            time.sleep(0.15)
        self.fail("never true: " + expression)

    def press(self, key, times=1):
        for _ in range(times):
            for kind in ("keyDown" if key == "Enter" else "rawKeyDown", "keyUp"):
                code = KEY.get(key) or ord(key)
                self.page.call("Input.dispatchKeyEvent", dict({"type": kind, "key": key, "code": key, "windowsVirtualKeyCode": code,
                                                               "nativeVirtualKeyCode": code}, **({"text": "\r"} if kind == "keyDown" else {})))
        time.sleep(0.3)

    def cell(self, title, n=0, click=True):
        """Focus (and click) the n-th programme by that title in Antenna's guide."""
        self.page.value("(() => { const b = [...document.querySelectorAll('#gRows .g-prog')].filter(x => x.textContent.trim() === %s)[%d];"
                        " b.focus(); %s return 1; })()" % (json.dumps(title), n, "b.click();" if click else ""))

    def test_antenna_is_the_tuners_on_the_clock_by_their_own_numbers(self):
        p = self.open()
        self.assertEqual(p.value("[...document.querySelectorAll('.eras [data-era]')].map(b => b.dataset.era)"), ["now", "antenna", "rec"])
        rows = p.value("[...document.querySelectorAll('#gRows .g-row')].map(r => [r.querySelector('.g-ch b').textContent,"
                       " [...r.querySelectorAll('.g-prog')].map(b => b.textContent.trim())])")
        self.assertEqual([r[0] for r in rows], ["2.1", "5.1", "11.3"])              # as the tuner numbers them
        self.assertEqual(rows[1][1][:2], ["Evening News", "Harbor Patrol"])
        self.assertEqual(rows[2][1], ["News Now: on air"])                         # no guide for it: on air, all the way
        self.cell("Harbor Patrol", click=False)                                    # a later one, up top
        self.until("document.querySelector('#gNow h2').textContent === 'Harbor Patrol'")
        self.assertIn("S2 E4", p.value("document.querySelector('#gNow .g-sub').textContent"))

    def test_a_later_programme_is_recorded_marked_and_cancelled(self):
        p = self.open()
        self.cell("Harbor Patrol")
        self.until("!!document.querySelector('.rec-dialog [data-rec-one]')")
        p.value("document.querySelector('.rec-dialog [data-rec-one]').click(), 1")
        self.until("!document.querySelector('.rec-dialog') && !!document.querySelector('#gRows .g-prog.rec')")
        rows = dvr.listing()["recordings"]
        self.assertEqual([(r["title"], r["channel"], r["state"]) for r in rows], [("Harbor Patrol", self.chans["5.1"]["id"], "scheduled")])
        self.assertEqual(p.value("document.querySelector('#gRows .g-prog.rec').textContent.trim()"), "Harbor Patrol")
        # Recordings: coming up, with a way out
        p.value("document.querySelector('[data-era=\"rec\"]').click(), 1")
        self.until("!!document.querySelector('.recs .rec-row.s-scheduled')")
        self.assertEqual(p.value("[...document.querySelectorAll('.rec-group h2')].map(h => h.firstChild.textContent)"), ["Coming up"])
        p.value("document.querySelector('.rec-row.s-scheduled [data-rec-cancel]').click(), 1")
        self.until("!!document.querySelector('.rec-empty')")
        self.assertEqual(dvr.get(rows[0]["id"])["state"], "cancelled")

    def test_the_series_new_ones_and_the_last_few(self):
        p = self.open()
        self.cell("Harbor Patrol")
        self.until("!!document.querySelector('.rec-dialog [data-rec-series]')")
        self.assertTrue(p.value("document.querySelector('#recNew').checked"))    # a new episode: new ones only, to start with
        p.value("(() => { const s = document.querySelector('#recKeep'); s.value = '5'; document.querySelector('.rec-dialog [data-rec-series]').click(); return 1; })()")
        self.until("!document.querySelector('.rec-dialog') && document.querySelectorAll('#gRows .g-prog.series, #gRows .g-prog.rec').length > 0")
        rules = dvr.listing()["rules"]
        self.assertEqual([(r["title"], r["channel"], r["new_only"], r["keep"]) for r in rules], [("Harbor Patrol", self.chans["5.1"]["id"], 1, 5)])
        p.value("document.querySelector('[data-era=\"rec\"]').click(), 1")
        self.until("!!document.querySelector('.rec-row.s-series')")
        p.value("document.querySelector('.rec-row.s-series [data-rec-stop-series]').click(), 1")
        self.until("!document.querySelector('.rec-row.s-series')")
        self.assertEqual(dvr.listing()["rules"], [])

    def test_a_film_is_recorded_not_a_series(self):
        p = self.open()
        self.cell("The Long Night")
        self.until("!!document.querySelector('.rec-dialog [data-rec-one]')")
        self.assertFalse(p.value("!!document.querySelector('.rec-dialog [data-rec-series], #recNew')"))
        p.value("history.back(), 1")

    def test_the_remote_goes_on_to_later_hours_and_back(self):
        p = self.open(tv=True, width=1920, height=1080)
        first = p.value("document.querySelector('.g-times .g-line span').textContent")
        p.value("(() => { const r = document.querySelectorAll('#gRows .g-row')[0], c = r.querySelectorAll('.g-prog'); c[c.length - 1].focus(); return 1; })()")
        self.press("ArrowRight")                                                   # past the row's end: two hours on
        self.until("document.querySelector('.g-times .g-line span').textContent !== %s" % json.dumps(first))
        self.assertTrue(p.value("document.activeElement.classList.contains('g-prog')"))
        self.assertFalse(p.value("document.querySelector('[data-gshift=\"-1\"]').disabled"))
        p.value("(() => { document.querySelectorAll('#gRows .g-row')[0].querySelector('.g-prog').focus(); return 1; })()")
        self.press("ArrowLeft")                                                    # before its start: back again
        self.until("document.querySelector('.g-times .g-line span').textContent === %s" % json.dumps(first))
        # OK on what's on now watches; OK on a later one asks what to record
        self.assertIn("OK", p.value("document.querySelector('#gNow .g-keys').textContent"))

    def test_rec_in_the_player_records_what_is_on(self):
        p = self.open()
        p.call("Network.setBlockedURLs", {"urls": ["*/live/*", "*/media/hls/*"]})  # (the picture isn't the point here)
        self.addCleanup(p.call, "Network.setBlockedURLs", {"urls": []})
        self.cell("Evening News")
        self.until("!document.getElementById('player').hidden && !document.querySelector('[data-act=\"rec\"]').hidden")
        self.assertEqual(p.value("document.querySelector('.p-show .p-num').textContent"), "5.1")
        p.value("document.querySelector('[data-act=\"rec\"]').click(), 1")
        self.until("document.querySelector('[data-act=\"rec\"]').getAttribute('aria-pressed') === 'true'")
        rows = dvr.listing()["recordings"]
        self.assertEqual([(r["title"], r["channel"]) for r in rows], [("Evening News", self.chans["5.1"]["id"])])
        p.value("document.querySelector('#player [data-act=\"close\"]').click(), 1")

    def test_the_server_page_has_the_tuners_and_the_guide(self):
        p = self.open(who="tuner-admin", era="antenna")
        p.call("Page.navigate", {"url": self.base + "/?t=%f#/server/live" % time.time()})
        self.until("!!document.querySelector('.tuners-panel .tuner-row')")
        self.assertIn("3 channels in Live TV", p.value("document.querySelector('.tuner-row').textContent"))
        self.assertIn("3 of 3 channels matched", p.value("document.querySelector('.tuners-panel').textContent"))
        p.value("document.querySelector('[data-tuner-switch]').click(), 1")       # off: its channels leave Live TV
        self.until("document.querySelector('[data-tuner-switch]').getAttribute('aria-pressed') === 'false'")
        self.assertFalse(tuners.known()[0]["on"])
        p.value("document.querySelector('[data-tuner-switch]').click(), 1")
        self.until("document.querySelector('[data-tuner-switch]').getAttribute('aria-pressed') === 'true'")
        p.value("(() => { const s = document.querySelector('[data-setting-select=\"dvr_pad_after\"]'); s.value = '5';"
                " s.dispatchEvent(new Event('change', { bubbles: true })); return 1; })()")
        self.until("document.querySelector('[data-setting-select=\"dvr_pad_after\"]').value === '5'")
        end = time.time() + 10
        while config.get("dvr_pad_after") != 5 and time.time() < end:
            time.sleep(0.1)
        self.assertEqual(dvr.pads(), (60, 300))


if __name__ == "__main__":
    unittest.main()
