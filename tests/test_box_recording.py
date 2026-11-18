"""Sofa Box OS 1.1.92 with Sofa 1.5.20: a tuner at home on the Sofa Box.

- The box's own player (mpv, through the box's agent): a tuner's channel by its own number (5.1), what's on and next
  from the household's guide, and REC: this programme, or the whole series; stop either. The page says which channels
  may be recorded, and Sofa still refuses anyone else (a Kids profile, a guest, a Visitor, from the internet).
- Sofa's Live TV pages as the box shows them (through its agent, in a browser at a TV's size, by the remote's keys
  only): Antenna into the box's player, the Record dialog's series choices, every row of Recordings one press apart,
  and a recording that's in the library playing in the box's player from where it was left, with its intro marked.

Against the stand-in tuner (tests/stand_in_tuner.py) and a guide written for the moment the tests run. No real tuner,
no real TV and no Raspberry Pi has run any of it; the box's player is the stand-in (tools/fake_mpv.py), and the player
screen's Record sheet is tested in mpv itself (tests/test_sofa_box.py, PlayerScreen).
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

import tests  # noqa: F401  (sets Sofa up for the tests)
from tests import ROOT
from sofa import auth, config, dvr, guide, intros, live, media, store, tuners, web
from sofa.library import LIBRARY
from tests.stand_in_tuner import Tuner
from tests.test_box_speed import Page, chrome, free_port, load

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")
KEY = {"ArrowDown": 40, "ArrowUp": 38, "ArrowLeft": 37, "ArrowRight": 39, "Enter": 13, "Escape": 27}


def stamp(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def guide_now(now):
    """What's on: 5.1 a news hour now, then a series and a film; 2.1 a quiz now (its one showing); 11.3 no guide."""
    shows = [("kstn", now - 600, now + 1800, "Evening News", ""),
             ("kstn", now + 1800, now + 5400, "Harbor Patrol", '<sub-title>Low Tide</sub-title><episode-num system="xmltv_ns">1.2.0/1</episode-num><new/>'),
             ("kstn", now + 5400, now + 12600, "The Long Night", "<category>Movie</category><date>1958</date>"),
             ("kstn", now + 86400, now + 90000, "Harbor Patrol", '<sub-title>The Reef</sub-title><episode-num system="xmltv_ns">1.3.0/1</episode-num><new/>'),
             ("two", now - 900, now + 2700, "Quiz Bowl", ""), ("two", now + 2700, now + 6300, "Two at Night", "")]
    return ('<?xml version="1.0" encoding="UTF-8"?><tv>'
            '<channel id="kstn"><display-name>5.1 KSTN</display-name></channel>'
            '<channel id="two"><display-name>2.1 Channel Two</display-name></channel>'
            '<channel id="news"><display-name>11.3 News Now</display-name></channel>'
            + "".join('<programme start="%s" stop="%s" channel="%s"><title>%s</title>%s</programme>' % (stamp(a), stamp(b), c, t, x)
                      for c, a, b, t, x in shows) + "</tv>").encode()


class WithATunerAtHome:
    """Sofa with the stand-in tuner on, its guide, a household member and a Kids profile (set up once per class)."""
    KEEP = ("tuners", "guide_sources", "live_playlists", "offline", "archive_channels", "retro_eras", "dvr_pad_before", "dvr_pad_after")

    @classmethod
    def sofa_up(cls):
        cls.before = {k: config.get(k) for k in cls.KEEP}
        cls.folder = tempfile.mkdtemp(prefix="sofa-box-rec-", dir=ROOT)
        cls.box = Tuner(cls.folder, media.tool("ffmpeg"))
        cls.now = int(time.time())
        xml = os.path.join(cls.folder, "guide.xml")
        with open(xml, "wb") as f:
            f.write(guide_now(cls.now))
        config.update({"tuners": [], "live_playlists": [], "offline": True, "archive_channels": False, "retro_eras": False,
                       "guide_sources": [{"path": xml}], "dvr_pad_before": 0, "dvr_pad_after": 0})
        tuners._lineups.clear()
        tuners.add(cls.box.base)
        live.refresh(force=True)
        guide.refresh(force=True)
        cls.chans = {c["guide_number"]: c for c in live.all_channels() if c.get("tuner")}
        for name in ("box-home", "box-kid"):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123")
        auth.set_kids(store.q1("SELECT id FROM users WHERE name = 'box-kid'")["id"], True)
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]

    @classmethod
    def sofa_down(cls):
        cls.httpd.shutdown()
        cls.box.close()
        config.update(cls.before)
        tuners._lineups.clear()
        live.refresh(force=True)
        shutil.rmtree(cls.folder, ignore_errors=True)

    def clear_recordings(self):
        dvr._table()
        for t in ("recordings", "recording_rules"):
            store.ex("DELETE FROM %s" % t)
        dvr._changed()

    @classmethod
    def cookie(cls, name):
        """Signed in as `name`: the cookie the TV's page has (the box's player asks Sofa with it, as the page would)."""
        req = urllib.request.Request(cls.base + "/api/login", data=json.dumps({"name": name, "password": "password123"}).encode(),
                                     headers={"Content-Type": "application/json", "X-Sofa": "1"})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as r:
            return "; ".join(c.split(";")[0] for c in r.headers.get_all("Set-Cookie") or [])


def to(c, may, base):
    """A channel as Sofa's page hands it to the box's player (client/app.js, openLive)."""
    return {"id": c["id"], "name": c["name"], "group": c.get("group") or "", "archive": False, "tuner": bool(c.get("tuner")),
            "number": c.get("guide_number") or c.get("number"), "rec": bool(may and (c.get("recordable") or dvr.recordable(c) is None)),
            "url": base + "/live/%s/index.m3u8" % c["id"]}


class RecInTheBoxPlayer(WithATunerAtHome, unittest.TestCase):
    """The box's agent with Sofa itself: the guide and REC for the channel on now (no browser, no mpv)."""

    @classmethod
    def setUpClass(cls):
        cls.sofa_up()
        cls.conf = tempfile.mkdtemp()
        old = {k: os.environ.get(k) for k in ("SOFA_BOX_CONF", "SOFA_BOX_DEVTOOLS", "SOFA_BOX_CAPTIVE_PORT")}
        os.environ.update(SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0")
        try:
            cls.agent = load("sofa-box-agent")
        finally:
            for k, v in old.items():
                os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)
        cls.home, cls.kid = cls.cookie("box-home"), cls.cookie("box-kid")

    @classmethod
    def tearDownClass(cls):
        cls.sofa_down()
        shutil.rmtree(cls.conf, ignore_errors=True)

    def setUp(self):
        self.clear_recordings()

    def player(self, number, may=True, who=None, order=("2.1", "5.1", "11.3"), look=True):
        """The box's player on a tuner's channel, as the page starts it; what it told the player screen."""
        p, said = self.agent.Player(), []
        p.osd = lambda **w: said.append(w)
        p.command = lambda *c: None                             # (no mpv here)
        chans = [to(self.chans[n], may, self.base) for n in order]
        p.payload = {"live": True, "title": self.chans[number]["name"], "number": number, "at": list(order).index(number), "channels": chans,
                     "h24": True}
        p.cookie, p.base = who or self.home, self.base
        p.status = {}
        got = p.rec_reset(tell=False)
        if look and got:
            p._rec_look(*got)
        return p, said

    def toasts(self, said):
        return [w["toast"] for w in said if w.get("toast")]

    def recordings(self, number):
        return [r for r in dvr.listing()["recordings"] if r["channel"] == self.chans[number]["id"] and r["state"] != "cancelled"]

    def test_the_guide_on_the_banner_and_in_rec(self):
        p, said = self.player("5.1")
        self.assertEqual((p.rec["can"], p.rec["channel"], p.rec["number"]), (True, self.chans["5.1"]["id"], "5.1"))
        self.assertEqual((p.rec["title"], p.rec["series"], p.rec["ends"]), ("Evening News", True, self.agent.wall(self.now + 1800, True)))
        banner = [w["banner"] for w in said if w.get("banner")][-1]
        self.assertEqual((banner["number"], banner["name"], banner["now"]), ("5.1", "KSTN", "Evening News"))
        self.assertEqual(banner["next"], self.agent.wall(self.now + 1800, True) + "  Harbor Patrol")
        self.assertEqual(p.status["sub"], "Evening News")
        self.assertEqual([w["rec"] for w in said if "rec" in w][-1], p.rec)       # (the player screen has it)
        p, said = self.player("11.3")                                            # no guide for it: on air, REC for an hour
        self.assertTrue(p.rec["can"])
        self.assertNotIn("title", p.rec)
        self.assertFalse([w for w in said if w.get("banner")])
        info = json.load(open(p.write_info(p.payload)))                          # from the moment mpv opens
        self.assertEqual((info["number"], info["rec"]["can"]), ("11.3", True))
        os.remove(p.info_path)

    def test_this_programme_then_stop(self):
        p, said = self.player("5.1")
        p.rec_do("now")
        rows = self.recordings("5.1")
        self.assertEqual([(r["title"], r["stop"]) for r in rows], [("Evening News", self.now + 1800)])
        self.assertEqual(self.toasts(said)[-1], "Recording Evening News until %s." % self.agent.wall(self.now + 1800, True))
        self.assertEqual(p.rec["recording"]["id"], rows[0]["id"])               # (the sheet offers to stop it now)
        p.rec_do("now")                                                          # (asked again: nothing twice)
        self.assertEqual(len(self.recordings("5.1")), 1)
        p.rec_do("stop")
        self.assertEqual(dvr.get(rows[0]["id"])["state"], "cancelled")
        self.assertEqual(self.toasts(said)[-1], "Stopped. What's recorded is filed.")
        self.assertNotIn("recording", p.rec)

    def test_the_whole_series(self):
        p, said = self.player("5.1")
        p.rec_do("series")
        rules = dvr.listing()["rules"]
        self.assertEqual([(u["title"], u["channel"], u["new_only"], u["keep"]) for u in rules],
                         [("Evening News", self.chans["5.1"]["id"], 0, 0)])
        self.assertEqual([r["title"] for r in self.recordings("5.1")], ["Evening News"])   # what's on, once: not again
        self.assertIn("every showing from now on", self.toasts(said)[-1])
        self.assertEqual(p.rec["rule"]["id"], rules[0]["id"])
        p.rec_do("stop_series")
        self.assertEqual(dvr.listing()["rules"], [])
        self.assertEqual([r["title"] for r in self.recordings("5.1")], ["Evening News"])   # (what's under way stays)

    def test_rec_follows_the_channel(self):
        p, said = self.player("5.1")
        old = (p.tuned, self.chans["5.1"])
        p.zap(-1)                                                               # up: 2.1, in the tuners' own order
        end = time.time() + 10
        while p.rec.get("title") != "Quiz Bowl" and time.time() < end:
            time.sleep(0.05)
        self.assertEqual((p.rec["channel"], p.rec["title"]), (self.chans["2.1"]["id"], "Quiz Bowl"))
        p._rec_look(*old)                                                       # a late answer for 5.1: dropped
        self.assertEqual(p.rec["channel"], self.chans["2.1"]["id"])
        p.rec_do("now")
        self.assertEqual([r["title"] for r in self.recordings("2.1")], ["Quiz Bowl"])
        self.assertEqual(self.recordings("5.1"), [])

    def test_only_a_channel_at_home_and_only_the_household(self):
        p, said = self.player("5.1")
        p.payload["channels"][1]["rec"] = False                                  # as a channel list from the internet is
        p.rec_reset(tell=False)
        self.assertFalse(p.rec["can"])
        self.assertIn("Only channels at home", p.rec["why"])
        p.rec_do("now")
        self.assertIn("Only channels at home", self.toasts(said)[-1])
        p, said = self.player("5.1", may=False)                                 # a page that may not record says none
        self.assertEqual(p.rec, {"can": False, "why": "Recording isn't available here."})
        p, said = self.player("5.1", who=self.kid)                              # and Sofa refuses anyone else anyway
        p.rec_do("now")
        self.assertEqual(self.toasts(said)[-1], "Recording is for the household, from home.")
        self.assertEqual(self.recordings("5.1"), [])

    def test_menu_has_record(self):
        p, said = self.player("5.1")
        real = self.agent.volume_now
        self.agent.volume_now = lambda: (40, False)
        try:
            items = p.menu_items()
            self.assertEqual(items[0][0], "Record")                            # (first, on Live TV at home)
            p.menu = {"items": items, "at": 0, "used": 0}
            p.menu_key("ok")
            self.assertEqual(said[-1], {"recsheet": True})
            self.assertIsNone(p.menu)
            p.rec_do("now")
            self.assertEqual(p.menu_items()[0][1][0][1], "Recording")
            p2, _ = self.player("5.1", may=False)
            self.assertNotIn("Record", [i[0] for i in p2.menu_items()])
        finally:
            self.agent.volume_now = real


MPV_SPY = """import json, os, sys
info = next((a.split("sofa_player-info=", 1)[1] for a in sys.argv[1:] if a.startswith("--script-opts=sofa_player-info=")), None)
with open(%(log)r, "a") as f:
    f.write(json.dumps({"info": json.load(open(info)) if info else None}) + "\\n")
sys.argv[0] = %(fake)r
exec(compile(open(%(fake)r).read(), %(fake)r, "exec"), {"__name__": "__main__"})
"""


@unittest.skipUnless(media.tool("ffmpeg"), "needs ffmpeg (the stand-in tuner's channel)")
class TheBoxPages(WithATunerAtHome, unittest.TestCase):
    """Sofa's Live TV pages on the box: through its agent (as the box's browser has them), at 1920x1080, by the keys."""

    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.sofa_up()
        # a recording in the library: an episode Sofa found the intro of, watched for a while
        shows = os.path.join(config.path("shows"), "Harbor Patrol", "Season 2")
        os.makedirs(shows, exist_ok=True)
        cls.ts = os.path.join(shows, "Harbor Patrol S02E02 The Pier.ts")
        subprocess.run([media.tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi",
                        "-i", "sine=frequency=440", "-t", "120", "-c:v", "mpeg2video", "-q:v", "8", "-c:a", "mp2", "-f", "mpegts", cls.ts], check=True)
        LIBRARY.scan("tests")
        cls.item = LIBRARY.item_at(os.path.abspath(cls.ts))
        assert cls.item, "the recording isn't in the library"
        intros.set_marker(cls.item, "intro", 5.0, 35.0, "test")
        cls.dir = tempfile.mkdtemp(prefix="sofa-box-rec-chrome-")
        cls.mpv_log = os.path.join(cls.dir, "mpv.jsonl")
        spy = os.path.join(cls.dir, "mpv-spy.py")
        with open(spy, "w") as f:
            f.write(MPV_SPY % {"log": cls.mpv_log, "fake": os.path.join(HERE, "tools", "fake_mpv.py")})
        cls.conf = os.path.join(cls.dir, "box")
        os.makedirs(cls.conf)
        with open(os.path.join(cls.conf, "settings.json"), "w") as f:
            json.dump({"server": cls.base, "welcomed": True}, f)
        cls.port = free_port()
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], env=dict(
            os.environ, SOFA_BOX_CONF=cls.conf, SOFA_BOX_PORT=str(cls.port), SOFA_BOX_LOCAL_DATA=os.path.join(cls.conf, "sofa"),
            SOFA_BOX_LOCAL_PORT=str(free_port()), SOFA_BOX_CERTS="0", SOFA_BOX_SLOW="1", SOFA_BOX_DEVTOOLS="0",
            SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_ICONS="0", SOFA_BOX_MPV=spy, FAKE_MPV_LOG=os.path.join(cls.dir, "fake.log")),
            stdout=subprocess.DEVNULL, stderr=open(os.path.join(cls.dir, "agent.log"), "w"))
        cls.box_url = "http://127.0.0.1:%d" % cls.port
        sid = None
        for _ in range(150):
            try:
                with open(os.path.join(cls.conf, "servers.json")) as f:
                    sid = json.load(f)["default"]
                if sid:
                    break
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.1)
        assert sid, "the box's agent didn't take Sofa"
        cls.page_base = "http://%s.localhost:%d" % (sid, cls.port)               # Sofa's pages, as the box's browser has them
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--mute-audio",
                                       "--window-size=1920,1080", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), "about:blank"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.page = Page(cls.devtools, "about:blank")
        cls.page.call("Page.enable")
        cls.page.call("Emulation.setFocusEmulationEnabled", {"enabled": True})
        cls.page.call("Emulation.setDeviceMetricsOverride", {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False})
        cls.page.call("Page.navigate", {"url": cls.page_base + "/client/manifest.webmanifest"})
        time.sleep(0.5)
        assert cls.page.value("fetch('/api/login',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},"
                              "body:JSON.stringify({name:'box-home',password:'password123'})}).then(r=>r.status)") == 200
        cls.user = store.q1("SELECT id FROM users WHERE name = 'box-home'")["id"]

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        for proc in (cls.chrome, cls.agent):
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        cls.sofa_down()
        intros.clear_marker(cls.item, "intro")
        shutil.rmtree(os.path.dirname(os.path.dirname(cls.ts)), ignore_errors=True)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.clear_recordings()
        self.stop_playing()

    def stop_playing(self):
        self.box_post("/box/native/control", {"cmd": "stop"})
        self.until_box(lambda st: not st["playing"])

    def box_post(self, path, body=None):
        req = urllib.request.Request(self.box_url + path, data=json.dumps(body or {}).encode(), headers={"X-Sofa-Box": "1"})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as r:
            return r.read()

    def until_box(self, check, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.box_url + "/box/state", timeout=10) as r:
                st = json.loads(r.read())
            if check(st):
                return st
            time.sleep(0.1)
        self.fail("the box never got there: %s" % st)

    def played(self):
        """What the box's player was given each time (the player screen's first look at it)."""
        try:
            with open(self.mpv_log) as f:
                return [json.loads(line)["info"] for line in f]
        except OSError:
            return []

    def open(self, era):
        p = self.page
        p.value("localStorage.clear(); sessionStorage.setItem('sofaPicked','1'); localStorage.setItem('sofa.installAsk', Date.now());"
                "localStorage.setItem('sofa.liveEra', %s); 1" % json.dumps(json.dumps(era)))
        p.call("Page.navigate", {"url": self.page_base + "/?tv=1&t=%f#/live" % time.time()})
        self.until("!!window.SofaBox && !!document.querySelector('.eras [data-era=\"%s\"][aria-selected=\"true\"]')" % era, 30)
        return p

    def until(self, expression, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if self.page.value(expression):
                return
            time.sleep(0.15)
        self.fail("never true: " + expression)

    def press(self, key, wait=0.35):
        code = KEY.get(key) or ord(key.upper())
        for kind in ("keyDown" if key == "Enter" else "rawKeyDown", "keyUp"):
            self.page.call("Input.dispatchKeyEvent", dict({"type": kind, "key": key, "code": key, "windowsVirtualKeyCode": code,
                                                           "nativeVirtualKeyCode": code}, **({"text": "\r"} if kind == "keyDown" else {})))
        time.sleep(wait)

    def focused(self):
        return self.page.value("(() => { const a = document.activeElement; return a ? a.tagName + '|' + a.className + '|' + a.textContent.replace(/\\s+/g, ' ').trim() : ''; })()")

    def test_antenna_into_the_box_player_and_rec(self):
        """OK on what's on in Antenna: the box's player, the channel by its own number and REC offered; up and down there
        go through the tuners in their own order; REC (as mpv's key reaches the agent) records it."""
        self.open("antenna")
        self.until("document.querySelectorAll('#gRows .g-row').length === 3")
        self.until("document.activeElement && document.activeElement.matches('#gRows .g-prog.on')")      # (the remote starts there)
        self.assertIn("Quiz Bowl", self.focused())                                                       # 2.1, first
        self.press("ArrowDown")
        self.assertIn("Evening News", self.focused())                                                    # 5.1
        self.assertIn("REC", self.page.value("document.querySelector('#gNow .g-keys').textContent"))
        n = len(self.played())
        self.press("Enter")
        self.until_box(lambda st: st["playing"] and st["playing"]["title"] == "KSTN" and len(self.played()) > n)
        info = self.played()[n]
        self.assertEqual((info["kind"], info["number"], info["rec"]["can"], info["rec"]["channel"]),
                         ("live", "5.1", True, self.chans["5.1"]["id"]))
        self.until_box(lambda st: st["playing"]["sub"] == "Evening News")                               # (the guide, after)
        self.box_post("/box/native/key?k=chdown")                                                        # down: 11.3
        self.until_box(lambda st: st["playing"]["title"] == "News Now")
        self.box_post("/box/native/key?k=rec&do=now")
        end = time.time() + 10
        while not dvr.listing()["recordings"] and time.time() < end:
            time.sleep(0.1)
        self.assertEqual([(r["title"], r["channel"]) for r in dvr.listing()["recordings"]], [("News Now", self.chans["11.3"]["id"])])
        self.stop_playing()

    def test_the_record_dialog_by_the_remote(self):
        """The series' choices are buttons OK changes (a check box and a drop-down kept the remote stuck on the box)."""
        self.open("antenna")
        self.until("document.querySelectorAll('#gRows .g-row').length === 3")
        self.page.value("(() => { [...document.querySelectorAll('#gRows .g-prog')].find(b => b.textContent.trim() === 'Harbor Patrol').focus(); return 1; })()")
        self.press("Enter")
        self.until("!!document.querySelector('.rec-dialog')")
        self.assertIn("Record it", self.focused())
        self.press("ArrowRight")
        self.assertIn("Record the series", self.focused())
        self.press("ArrowDown")
        self.assertEqual(self.focused(), "BUTTON|btn small|The series: new episodes only")               # (a new episode)
        self.press("Enter")
        self.assertEqual(self.focused(), "BUTTON|btn small|The series: every showing")
        self.press("ArrowDown")
        self.press("Enter")
        self.press("Enter")
        self.assertEqual(self.focused(), "BUTTON|btn small|Keep the last 5")
        self.press("ArrowDown")
        self.assertIn("Close", self.focused())                                                          # (Close last)
        for key in ("ArrowUp", "ArrowUp", "ArrowUp", "ArrowRight"):
            self.press(key)
        self.assertIn("Record the series", self.focused())
        self.press("Enter")
        self.until("!document.querySelector('.rec-dialog')")
        self.assertEqual([(u["title"], u["new_only"], u["keep"]) for u in dvr.listing()["rules"]], [("Harbor Patrol", 0, 5)])

    def test_recordings_by_the_remote_and_one_plays_in_the_box_player(self):
        """Each row one press from the next, in order; OK on a recorded one plays it in the box's player, from where it was
        left, its intro marked (Skip intro); OK on one that's coming offers not to record it."""
        five = self.chans["5.1"]
        coming = dvr.record_programme(five["id"], self.now + 1800)              # coming up
        rid = dvr._insert(five, self.now - 7200, self.now - 3600, "Harbor Patrol")
        store.ex("UPDATE recordings SET state = 'filed', path = ?, size = ? WHERE id = ?", self.ts, os.path.getsize(self.ts), rid)
        dvr.add_rule("Quiz Bowl", channel_id=self.chans["2.1"]["id"])            # a series (and its showing on now)
        dvr._changed()
        store.ex("INSERT OR REPLACE INTO progress (user_id, item, t, d, done, at) VALUES (?, ?, ?, ?, 0, ?)", self.user, self.item, 64, 120,
                 int(time.time()))
        self.open("rec")
        self.until("document.querySelectorAll('.rec-row').length === 4")
        self.page.value("document.querySelector('.eras [data-era=\"rec\"]').focus(), 1")
        rows = []
        for _ in range(4):
            self.press("ArrowDown")
            rows.append(self.page.value("document.activeElement.className"))
        self.assertEqual(rows, ["rec-row s-scheduled", "rec-row s-scheduled", "rec-row s-filed", "rec-row s-series"])
        self.assertIn("Resume", self.page.value("document.querySelector('.rec-row.s-filed').textContent"))
        self.press("ArrowUp")                                                    # the recorded one: OK plays it
        n = len(self.played())
        self.press("Enter")
        self.until_box(lambda st: st["playing"] and st["playing"]["item"] == self.item and len(self.played()) > n, 20)
        info = self.played()[n]
        self.assertEqual((info["kind"], info["title"], round(info["at"])), ("resume", "Harbor Patrol", 64))
        self.assertEqual([(m["kind"], m["start"], m["end"]) for m in info["markers"]], [("intro", 5.0, 35.0)])
        self.stop_playing()
        self.open("rec")
        self.until("document.querySelectorAll('.rec-row').length === 4")
        self.page.value("document.querySelectorAll('.rec-row.s-scheduled')[1].focus(), 1")       # Harbor Patrol, coming
        self.press("Enter")
        self.until("!!document.querySelector('.rec-dialog [data-rec-cancel]')")
        self.assertIn("Don't record it", self.focused())
        self.press("Enter")
        self.until("!document.querySelector('.rec-dialog')")
        self.assertEqual(dvr.get(coming["id"])["state"], "cancelled")


if __name__ == "__main__":
    unittest.main()
