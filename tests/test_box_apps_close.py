"""Sofa Box OS 1.1.70: back on Home, the apps behind it give the box back.

An app left behind Home was put to sleep (no scripts, no timers, no drawing), so it cost no processor. But asleep it
still held its memory and its share of the graphics chip, because its process was still there: on a Pi 3 with 905 MB
that is most of what a game or the next app needs. Now an app that has been out of sight for a while is closed, and its
process ends. Never Home, Sofa or the page in front, and never one that's playing something you can hear."""
import base64
import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from tests.test_box_speed import chrome, free_port

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")


def load(name, **env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(name.replace("-", "_") + "_apps", os.path.join(BOX, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)


boxos = load("boxos")


def read(*parts):
    with open(os.path.join(BOX, *parts), encoding="utf-8") as f:
        return f.read()


def browser(tabs, front="h", playing=(), sounds=None):
    """The box's Browser with a stand-in DevTools: what it asks is written down."""
    b = boxos.Browser.__new__(boxos.Browser)
    b.tabs, b.front, b.calls = tabs, front, []
    b.gave_back = boxos.collections.deque(maxlen=12)
    b.sounds = {}

    def call(method, params=None, session=None, timeout=10):
        b.calls.append((method, (params or {}).get("targetId") or "", session))
        if method == "Runtime.evaluate":
            if session == "s-stuck":
                raise OSError("the browser didn't answer Runtime.evaluate")
            return {"result": {"value": json.dumps({"playing": session in playing, "sound": (sounds or {}).get(session)})}}
        if method == "Target.closeTarget":
            b.tabs.pop(params["targetId"], None)
        return {}
    b.call = call
    return b


def tabs(now, **more):
    t = {"h": {"app": "home", "session": "s-h"},
         "sofa": {"app": "sofa", "session": "s-sofa", "left": now - 900},
         "tube": {"app": "youtube", "session": "s-tube", "left": now - 40, "frozen": True}}
    t.update(more)
    for tab in t.values():
        tab.setdefault("used", 0)
    return t


class LeftBehind(unittest.TestCase):
    def test_an_app_out_of_sight_long_enough_is_closed(self):
        now = 1000.0
        b = browser(tabs(now))
        with mock.patch.object(boxos, "available_mb", side_effect=[310, 492]):
            closed = b.tidy(30, now=now, wait=0)
        self.assertEqual(closed, [{"app": "youtube", "left": 40, "before": 310, "after": 492}])
        self.assertEqual(sorted(b.tabs), ["h", "sofa"])                           # Home and Sofa: never
        self.assertEqual([c for c in b.calls if c[0] == "Target.closeTarget"], [("Target.closeTarget", "tube", None)])
        self.assertEqual(len(b.gave_back), 1)
        self.assertIn("youtube, 40 s out of sight, memory free 310 to 492 MB", b.gave_back[0])

    def test_not_yet_not_the_one_in_front_and_not_one_thats_playing(self):
        now = 1000.0
        b = browser(tabs(now, tube={"app": "youtube", "session": "s-tube", "left": now - 12, "frozen": True}))
        self.assertEqual(b.tidy(30, now=now, wait=0), [])                         # a wrong press of Home: still there
        self.assertIn("tube", b.tabs)
        b = browser(tabs(now), front="tube")                                      # in front (its "left" is from before)
        self.assertEqual(b.tidy(30, now=now, wait=0), [])
        b = browser(tabs(now, music={"app": "music", "session": "s-music", "left": now - 4000}), playing=("s-music",))
        closed = b.tidy(30, now=now, wait=0)                                      # music carries on behind Home
        self.assertEqual([c["app"] for c in closed], ["youtube"])
        self.assertIn("music", b.tabs)
        self.assertIn(("Runtime.evaluate", "", "s-music"), b.calls)
        self.assertNotIn(("Runtime.evaluate", "", "s-tube"), b.calls)             # (asleep: it can't be playing, and can't answer)

    def test_one_that_stopped_playing_or_stopped_answering_goes_too(self):
        now = 1000.0
        b = browser(tabs(now, music={"app": "music", "session": "s-music", "left": now - 4000},
                         stuck={"app": "browser", "session": "s-stuck", "left": now - 100}))
        self.assertEqual(sorted(c["app"] for c in b.tidy(30, now=now, wait=0)), ["browser", "music", "youtube"])

    def test_a_window_an_app_opened_itself_is_counted_from_when_its_seen(self):
        now = 1000.0
        b = browser(tabs(now, pop={"app": "youtube", "session": "s-pop"}))
        self.assertEqual([c["app"] for c in b.tidy(30, now=now, wait=0)], ["youtube"])
        self.assertIn("pop", b.tabs)
        self.assertEqual(b.tidy(30, now=now + 29, wait=0), [])
        self.assertEqual([c["left"] for c in b.tidy(30, now=now + 31, wait=0)], [31])
        self.assertNotIn("pop", b.tabs)
        b = browser(tabs(now, loading={"app": "browser", "session": None, "left": now - 100}))   # (not attached yet: left alone)
        b.tidy(30, now=now, wait=0)
        self.assertIn("loading", b.tabs)

    def test_out_of_sight_is_counted_from_when_another_page_came_in_front(self):
        b = browser({"h": {"app": "home", "session": "s-h"}, "tube": {"app": "youtube", "session": "s-tube", "left": 5.0}})
        b.settle = lambda front: None
        b.activate("tube")                                                        # opened again: as it was, and not "left"
        self.assertNotIn("left", b.tabs["tube"])
        self.assertAlmostEqual(b.tabs["h"]["left"], time.time(), delta=5)
        b.activate("h")
        self.assertAlmostEqual(b.tabs["tube"]["left"], time.time(), delta=5)
        self.assertEqual(b.tidy(30, wait=0), [])
        self.assertEqual([c["app"] for c in b.tidy(30, now=time.time() + 31, wait=0)], ["youtube"])

    def test_the_memory_free_is_the_kernels_own_figure(self):
        text = "MemTotal:         927288 kB\nMemFree:           61220 kB\nMemAvailable:     429056 kB\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=text)):
            self.assertEqual(boxos.available_mb(), 419)
        with mock.patch("builtins.open", side_effect=OSError):
            self.assertIsNone(boxos.available_mb())
        b = browser(tabs(1000.0))
        with mock.patch.object(boxos, "available_mb", return_value=None):         # (not a Linux box: no figures, no fuss)
            b.tidy(30, now=1000.0, wait=0)
        self.assertNotIn("memory", b.gave_back[0])


class Sound(unittest.TestCase):
    """What "playing something you can hear" means, and what a report says of an app's sound."""

    def test_music_carries_on_under_a_game(self):
        now = 1000.0
        b = browser(tabs(now, music={"app": "edge-music", "session": "s-music", "left": now - 5},
                         tube={"app": "youtube", "session": "s-tube", "left": now - 5}), playing=("s-music",))
        b.rest(close_apps=True)                                                   # a game starts on a Pi 3
        self.assertEqual(sorted(b.tabs), ["h", "music", "sofa"])                  # the quiet app closed; the music stays
        self.assertFalse(b.tabs["music"].get("frozen"))                           # ...and awake
        b = browser(tabs(now, music={"app": "edge-music", "session": "s-music", "left": now - 5},
                         tube={"app": "youtube", "session": "s-tube", "left": now - 5}), playing=("s-music",))
        b.rest()                                                                  # on a bigger box nothing closes
        self.assertEqual((bool(b.tabs["music"].get("frozen")), bool(b.tabs["tube"].get("frozen"))), (False, True))
        self.assertFalse(b.tabs["h"].get("frozen"))                               # (Home is never put to sleep)

    def test_a_report_says_how_each_apps_sound_went(self):
        now = 1000.0
        b = browser(tabs(now, music={"app": "edge-music", "session": "s-music", "left": now - 5}), playing=("s-music",),
                    sounds={"s-music": {"waits": 3, "longest": 2140, "stalls": 1, "errors": 0, "started": 9},
                            "s-sofa": {"waits": 0, "longest": 0, "stalls": 0, "errors": 0, "started": 0}})
        lines = b.sound_lines()
        self.assertEqual(len(lines), 1)                                           # (an app that played nothing: no line)
        self.assertIn("edge-music: started 9, stopped to wait for more 3 times (the longest 2.1 s), stalled 1, errors 0", lines[0])
        b.tabs.pop("music")                                                       # closed since: what it said is kept
        self.assertEqual(len(b.sound_lines()), 1)
        self.assertIn("== Sound in the apps", read("sofa-box-agent.py"))

    def test_the_question_covers_players_off_the_page_and_web_audio(self):
        self.assertIn("window.__sofaSound.playing()", boxos.PLAYING_JS)
        self.assertIn("document.querySelectorAll('video,audio')", boxos.PLAYING_JS)
        for part in ("HTMLMediaElement.prototype.play", "AudioScheduledSourceNode", '"waiting"', '"stalled"'):
            self.assertIn(part, boxos.SOUND_PROBE)
        src = read("boxos.py")
        self.assertIn('self.call("Page.addScriptToEvaluateOnNewDocument", {"source": SOUND_PROBE}, session, timeout=3)', src)


class VideosInAReport(unittest.TestCase):
    """How each video played, for the next report: "EL BARCO keeps lagging and stuttering, also takes longer to
    initially play" can't be answered from a report that only said where the video was. Now it says what kind of
    video it was, how long until the picture moved, what it is, whether the video chip decoded it, frames dropped,
    and waits for more to arrive. No titles."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent", SOFA_BOX_CONF=cls.dir, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_what_mpv_says_and_the_line_it_makes(self):
        P = self.agent.Player
        player = P.__new__(P)
        said = {"video-codec": "h264", "hwdec-current": "v4l2m2m-copy", "width": 1920, "height": 1080, "container-fps": 23.976,
                "video-bitrate": 7400000, "audio-codec-name": "eac3", "frame-drop-count": 41, "decoder-frame-drop-count": 3}
        player.command = lambda *cmd: said.get(cmd[1])
        run = {"at": "21:04:10", "kind": "converted", "started_after": 14, "waits": 3, "waited": 11, "played": 1260}
        player.sample(run)
        self.assertEqual(P.ran_line(run),
                         "21:04:10 converted, picture after 14 s, h264 1920x1080 24 fps, decoded by the video chip (v4l2m2m-copy), "
                         "7.4 Mbit/s, audio eac3, dropped 44 frames (3 by the decoder), waited for more 3 times (11 s in all), played 1260 s")
        said.update({"hwdec-current": "no", "video-codec": "hevc"})
        player.sample(run)
        self.assertIn("hevc 1920x1080 24 fps, decoded by the processor", P.ran_line(run))
        self.assertIn("the picture never moved", P.ran_line({"kind": "file", "started_after": None}))

    def test_a_new_track_is_said_over_what_is_in_front(self):
        """The mini player's pop-up: a new track in an app behind the page in front is said for a moment over it. Not
        when the music app is in front, not over a video, not when the box rests; and on Home only for a change of
        track (Home has its own row)."""
        a = self.agent
        said, front, track = [], ["sofa"], [{"app": "edge-music", "title": "One", "artist": "Someone", "playing": True, "front": False}]

        class B:
            def connected(self):
                return True

            def front_app(self):
                return front[0]

            def hud(self, text, level=None):
                said.append(text)
        old = (a.browser, a.now_playing, a.playing, dict(a._now))
        a.browser, a.now_playing, a.playing = B(), lambda fresh=False: dict(track[0]), lambda: False
        a._now["said"] = None
        try:
            a.now_line()
            a.now_line()                                                          # the same track: once
            self.assertEqual(said, ["\u266a One \u00b7 Someone"])
            track[0] = dict(track[0], title="Two")
            a.now_line()
            self.assertEqual(said[-1], "\u266a Two \u00b7 Someone")
            front[0] = "home"
            track[0] = dict(track[0], app="radio", title="Three", artist="")
            a.now_line()                                                          # another app, Home in front: Home shows it
            self.assertEqual(len(said), 2)
            track[0] = dict(track[0], title="Four")
            a.now_line()                                                          # its next track: said
            self.assertEqual(said[-1], "\u266a Four")
            track[0] = dict(track[0], title="Five", front=True)
            a.now_line()                                                          # the music app in front: nothing
            a.playing = lambda: True
            track[0] = dict(track[0], title="Six", front=False)
            a.now_line()                                                          # a video plays: nothing
            self.assertEqual(len(said), 3)
        finally:
            a.browser, a.now_playing, a.playing = old[:3]
            a._now.clear()
            a._now.update(old[3])

    def test_the_player_keeps_it_and_the_report_has_it(self):
        src = read("sofa-box-agent.py")
        self.assertIn('self.ran = collections.deque(maxlen=6)', src)
        self.assertIn('self.command("get_property", "paused-for-cache") is True', src)
        self.assertIn('"videos played (newest last): "', src)
        watch = src[src.index("    def _watch(self, proc):"):src.index("    def tell(self, **what):")]
        self.assertNotIn("title", watch[:watch.index("cache_wait = False")])      # (no titles in what's kept)


class TheAgent(unittest.TestCase):
    def test_how_long_an_app_stays_and_what_a_report_says(self):
        src = read("sofa-box-agent.py")
        self.assertIn('threading.Thread(target=watch_apps, daemon=True, name="apps").start()', src)
        self.assertIn('return 30.0 if light() else 300.0', src)
        self.assertIn('"apps closed behind Home (after %d s out of sight): %s"', src)
        self.assertIn("none since the box started", src)
        self.assertIn("what's playing carries on; the rest close by themselves after a moment", read("home", "home.js"))


def silence(seconds=1):
    """Quiet sound, as a page's own audio (it's "playing something you can hear" to the box)."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<%dh" % (8000 * seconds), *([0] * 8000 * seconds)))
    return "data:audio/wav;base64," + base64.b64encode(out.getvalue()).decode()


class Pages(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/box/home"):
            body = "<!doctype html><title>Home</title><div id=view><p>Home</p></div>"
        elif self.path.startswith("/radio"):
            body = "<!doctype html><title>Radio</title><p>on air</p><audio id=a loop autoplay src='%s'></audio>" % silence()
        elif self.path.startswith("/offpage"):              # a player made in script, never put on the page
            body = ("<!doctype html><title>Off the page</title><p>music</p><script>window.player = new Audio('%s');"
                    "player.loop = true; player.play();</script>" % silence(8))
        elif self.path.startswith("/webaudio") or self.path.startswith("/game"):
            # sound made with Web Audio, no player at all: a music app that says what it plays, or a game that doesn't
            body = ("<!doctype html><title>Web Audio</title><p>synth</p><script>window.ctx = new AudioContext();"
                    "const g = ctx.createGain(); g.gain.value = 0.0001; g.connect(ctx.destination);"
                    "window.osc = ctx.createOscillator(); osc.connect(g); osc.start();%s</script>"
                    % ("navigator.mediaSession.metadata = new MediaMetadata({ title: 'A synth', artist: 'Someone' });"
                       if self.path.startswith("/webaudio") else ""))
        elif self.path.startswith("/ran"):                  # a game: it says how it ran as its page goes (pagehide)
            body = ("<!doctype html><title>A game</title><p>game</p><script>addEventListener('pagehide', () =>"
                    " console.error('stand-in ran: 60 fps, 0 late of 1200'));</script>")
        elif self.path.startswith("/preview"):              # a silent preview that played and stopped
            body = ("<!doctype html><title>Previews</title><p>shows</p><video id=v muted src='%s'></video>"
                    "<script>v.play().then(() => v.pause());</script>" % silence())
        else:
            body = ("<!doctype html><title>App</title><p id=n>0</p><script>const hold = [];"
                    "for (let i = 0; i < 40; i++) hold.push(new Uint8Array(1 << 20).fill(i));"
                    "setInterval(() => { n.textContent = +n.textContent + 1; }, 50);</script>")
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class InABrowser(unittest.TestCase):
    """The same, with the box's Browser steering a real one."""

    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Pages)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.dir = tempfile.mkdtemp()
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1280,720",
                                       "--autoplay-policy=no-user-gesture-required", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), cls.base + "/box/home"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.b = boxos.Browser(port=cls.devtools)
        if not cls.b.ready.wait(30):
            raise AssertionError("the browser didn't come up")
        for _ in range(100):
            if cls.b.tab_of("home") and cls.b.tabs[cls.b.tab_of("home")].get("session"):
                break
            time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.chrome.terminate()
        try:
            cls.chrome.wait(10)
        except subprocess.TimeoutExpired:
            cls.chrome.kill()
        cls.srv.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def renderers(self):
        return sum(1 for p in self.b.call("SystemInfo.getProcessInfo").get("processInfo", []) if p.get("type") == "renderer")

    def pages(self):
        with boxos._opener.open("http://127.0.0.1:%d/json/list" % self.devtools, timeout=10) as r:
            return sorted(p["url"].split("/")[-1] for p in json.loads(r.read()) if p["type"] == "page")

    def test_the_quiet_app_goes_with_its_process_and_the_radio_plays_on(self):
        b = self.b
        alone = self.renderers()
        b.open("stream", self.base + "/stream")
        b.open("radio", self.base + "/radio")
        b.open("sofa", self.base + "/sofa")
        self.assertEqual(b.home(look=False), True)
        time.sleep(3.0)                                                           # (the ones behind are put to sleep after 1.5 s)
        self.assertEqual(self.pages(), ["home", "radio", "sofa", "stream"])
        self.assertGreaterEqual(self.renderers(), alone + 1)
        asleep = {tab["app"]: bool(tab.get("frozen")) for tab in b.tabs.values()}
        self.assertEqual((asleep["stream"], asleep["radio"], asleep["sofa"]), (True, False, False))
        with_apps = self.renderers()
        self.assertEqual(b.tidy(3600, wait=0), [])                                # not yet
        closed = b.tidy(1.0, wait=0)
        self.assertEqual([c["app"] for c in closed], ["stream"])
        time.sleep(1.5)
        self.assertEqual(self.pages(), ["home", "radio", "sofa"])                 # the radio plays on; Sofa stays
        self.assertLess(self.renderers(), with_apps)                              # ...and the app's process is gone
        self.assertTrue(b.call("Runtime.evaluate", {"expression": boxos.PLAYING_JS, "returnByValue": True},
                               b.tabs[b.tab_of("radio")]["session"])["result"]["value"])
        target = b.open("stream", self.base + "/stream")                          # opened again: a new page of it
        self.assertEqual(b.front, target)
        self.assertEqual(self.pages(), ["home", "radio", "sofa", "stream"])

    def test_a_game_closed_behind_home_still_says_how_it_ran(self):
        """The box's games say how they ran (a line a report keeps) as their page goes. Closed asleep behind Home, a
        page never ran that: it's woken first, and its line is kept under its own name."""
        b = self.b
        b.open("ran", self.base + "/ran")
        b.home(look=False)
        time.sleep(3.0)
        self.assertTrue(b.tabs[b.tab_of("ran")].get("frozen"))                   # (asleep behind Home, as a game is)
        self.assertEqual([c["app"] for c in b.tidy(0.5, wait=0) if c["app"] == "ran"], ["ran"])
        for _ in range(30):
            if any("stand-in ran:" in n for n in b.notes):
                break
            time.sleep(0.1)
        said = [n for n in b.notes if "stand-in ran:" in n]
        self.assertEqual(len(said), 1, list(b.notes))
        self.assertIn("ran consoleAPICalled: stand-in ran: 60 fps, 0 late of 1200", said[0])

    def test_music_from_a_player_off_the_page_or_from_web_audio_plays_on(self):
        """The box asked a page for its <audio> elements. A music app that plays through `new Audio()` or Web Audio has
        none on the page: it was put to sleep a second and a half after Home, music and all."""
        b = self.b
        for app in ("offpage", "webaudio", "game", "preview"):
            b.open(app, self.base + "/" + app)
        time.sleep(1.0)
        b.home(look=False)
        time.sleep(3.0)
        asleep = {tab["app"]: bool(tab.get("frozen")) for tab in b.tabs.values()}
        self.assertEqual((asleep["offpage"], asleep["webaudio"]), (False, False))
        self.assertEqual((asleep["game"], asleep["preview"]), (True, True))      # a game's sound, a silent preview: asleep
        now = b.now_playing()
        self.assertIn(now["app"], ("offpage", "webaudio"))                        # (the preview isn't music)
        closed = sorted(c["app"] for c in b.tidy(0.5, wait=0) if c["app"] in ("offpage", "webaudio", "game", "preview"))
        self.assertEqual(closed, ["game", "preview"])                             # the quiet ones go; the music stays
        value = lambda app, js: b.call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True},
                                       b.tabs[b.tab_of(app)]["session"])["result"].get("value")
        # the track stops to wait for more, twice: counted, with how long
        value("offpage", "(async () => { while (player.currentTime < 0.6) await new Promise(r => setTimeout(r, 50));"
                         " player.dispatchEvent(new Event('waiting')); await new Promise(r => setTimeout(r, 300));"
                         " player.dispatchEvent(new Event('playing')); player.dispatchEvent(new Event('waiting'));"
                         " player.dispatchEvent(new Event('playing')); player.dispatchEvent(new Event('stalled')); return 1; })()")
        lines = [ln for ln in b.sound_lines() if "offpage" in ln]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"offpage: started 1, stopped to wait for more 2 times \(the longest \d\.\d s\), stalled 1, errors 0")
        value("offpage", "player.pause(); 1")                                     # stopped: they go like any other
        value("webaudio", "osc.stop(); 1")
        time.sleep(0.5)
        self.assertEqual(sorted(c["app"] for c in b.tidy(0.5, wait=0) if c["app"] in ("offpage", "webaudio")), ["offpage", "webaudio"])


MUSIC = """<!doctype html><meta charset=utf-8><title>Stand-in music</title><body style="background:#111;color:#eee">
<p>music</p><script>
const tracks = [["Stand-in track one", "Stand-in artist"], ["Stand-in track two", "Stand-in artist"]];
let i = 0; window.log = [];
const a = new Audio("%s"); a.loop = true;
const cover = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#39ff88"/><rect x="2" y="2" width="6" height="6" fill="#ff2e88"/></svg>');
function show() { navigator.mediaSession.metadata = new MediaMetadata({ title: tracks[i][0], artist: tracks[i][1], artwork: [{ src: cover, sizes: "512x512" }] }); }
navigator.mediaSession.setActionHandler("play", () => { log.push("play"); a.play(); });
navigator.mediaSession.setActionHandler("pause", () => { log.push("pause"); a.pause(); });
navigator.mediaSession.setActionHandler("nexttrack", () => { log.push("next"); i = (i + 1) %% tracks.length; show(); });
navigator.mediaSession.setActionHandler("previoustrack", () => { log.push("previous"); i = (i + tracks.length - 1) %% tracks.length; show(); });
show(); a.play();
</script>"""


class Music(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        data = (MUSIC % silence(8)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class MiniPlayer(unittest.TestCase):
    """The mini player: an app plays music behind Home; Home shows what it says it plays, and its buttons press the
    app's own. The box's agent, its Home and a stand-in music app, in a real browser."""

    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Music)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.music = "http://localhost:%d/" % cls.srv.server_address[1]
        cls.dir = tempfile.mkdtemp()
        conf = os.path.join(cls.dir, "conf")
        os.makedirs(conf)
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": True, "weather": "off", "boot_sound": "off"}, f)
        cls.port, cls.devtools = free_port(), free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        run = os.path.join(cls.dir, "run")
        os.makedirs(run)
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1920,1080",
                                       "--autoplay-policy=no-user-gesture-required", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), cls.base + "/box/home"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cls.dir, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(cls.port),
                                              SOFA_BOX_DEVTOOLS=str(cls.devtools), XDG_RUNTIME_DIR=run, SOFA_BOX_UINPUT="0",
                                              SOFA_BOX_ICONS="0", SOFA_BOX_HOTSPOT="0", SOFA_BOX_CERTS="0", SOFA_BOX_NEWEST="0",
                                              SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_LEAVE_AFTER="0", SOFA_BOX_REMOTE_PORT=str(free_port())))
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(300):
            try:
                if cls.ask("/box/api/apps")["devtools"]:
                    break
            except OSError:
                pass
            time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.agent.terminate()
        cls.chrome.terminate()
        for p in (cls.agent, cls.chrome):
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        cls.srv.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def ask(cls, path, body=None):
        req = urllib.request.Request(cls.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Sofa-Box": "1"})
        with cls.opener.open(req, timeout=30) as r:
            return json.loads(r.read())

    def page(self, part, expression):
        with self.opener.open("http://127.0.0.1:%d/json/list" % self.devtools, timeout=10) as r:
            tab = next(p for p in json.loads(r.read()) if p["type"] == "page" and part in p["url"])
        ws = boxos.WebSocket(tab["webSocketDebuggerUrl"])
        try:
            ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == 1:
                    return m["result"]["result"].get("value")
        finally:
            ws.close()

    def until(self, part, expression, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            try:
                v = self.page(part, expression)
                if v:
                    return v
            except (OSError, StopIteration, KeyError, ValueError):
                pass
            time.sleep(0.3)
        self.fail("never true in %s: %s" % (part, expression))

    def test_home_shows_the_music_and_presses_the_apps_own_buttons(self):
        self.ask("/box/api/open", {"url": self.music})
        self.until(self.music, "window.log && !document.querySelector('audio') && true")
        self.ask("/box/api/home", {})
        now = None
        for _ in range(80):
            now = self.ask("/box/api/apps").get("now")
            if now and now.get("playing") and not now.get("front"):
                break
            time.sleep(0.3)
        self.assertTrue(now, "nothing playing, by the box's look: %s" % self.page(self.music, "JSON.stringify(window.__sofaSound && window.__sofaSound.now())"))
        self.assertEqual({k: now[k] for k in ("title", "artist", "playing", "app")},
                         {"title": "Stand-in track one", "artist": "Stand-in artist", "playing": True, "app": "browser"})
        self.assertEqual(sorted(now["can"]), ["nexttrack", "pause", "play", "previoustrack"])
        self.assertTrue(now["art"].startswith("data:image/svg+xml"))
        self.assertFalse(self.page(self.music, "document.hidden === undefined"))
        # Home: the row, and its Next pressed the way the remote does (OK on it)
        self.until("/box/home", "!!document.querySelector('#np') && document.querySelector('#np b').textContent === 'Stand-in track one'")
        shots = os.environ.get("SOFA_SHOTS")
        if shots:
            self.shot(shots, "mini-player-on-home.png")
        self.page("/box/home", "document.querySelector('[data-music=nexttrack]').click(); 1")
        self.until(self.music, "window.log.includes('next')")
        self.until("/box/home", "document.querySelector('#np b') && document.querySelector('#np b').textContent === 'Stand-in track two'")
        self.page("/box/home", "document.querySelector('[data-music=toggle]').click(); 1")
        self.until(self.music, "window.log.includes('pause')")
        self.until("/box/home", "/Paused in/.test(document.querySelector('#np small').textContent)")
        self.assertEqual(self.ask("/box/api/music", {"act": "play"})["ok"], True)
        self.until(self.music, "window.log.includes('play') && document.hidden")   # (pressed from Home: it stays behind)
        # the app wasn't put to sleep behind Home, and isn't closed (it's playing)
        self.assertFalse(any(r["frozen"] for r in self.ask("/box/api/apps")["running"]))
        # Open: the app in front; then Home has no row for it (it's in front)
        self.ask("/box/api/music", {"act": "open"})
        self.until(self.music, "document.visibilityState === 'visible'")
        with self.assertRaises(urllib.error.HTTPError):
            self.ask("/box/api/music", {"act": "louder"})

    def shot(self, folder, name):
        import base64
        with self.opener.open("http://127.0.0.1:%d/json/list" % self.devtools, timeout=10) as r:
            tab = next(p for p in json.loads(r.read()) if p["type"] == "page" and "/box/home" in p["url"])
        ws = boxos.WebSocket(tab["webSocketDebuggerUrl"])
        try:
            ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == 1:
                    os.makedirs(folder, exist_ok=True)
                    with open(os.path.join(folder, name), "wb") as f:
                        f.write(base64.b64decode(m["result"]["data"]))
                    return
        finally:
            ws.close()


class OnThePhone(unittest.TestCase):
    """The mini player on the phone remote (remote.html at a phone's size, the box's answers stood in for)."""

    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        from tests import test_box_handoff as handoff
        cls.h = handoff
        cls.dir = tempfile.mkdtemp()
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=500,900",
                                       "--allow-file-access-from-files", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), "about:blank"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.tab = handoff.Tab(cls.devtools)
        cls.tab.call("Emulation.setDeviceMetricsOverride", width=393, height=852, deviceScaleFactor=2, mobile=True)
        cls.tab.call("Page.addScriptToEvaluateOnNewDocument", source=handoff.FETCH_STUB)

    @classmethod
    def tearDownClass(cls):
        cls.tab.close()
        cls.chrome.terminate()
        try:
            cls.chrome.wait(10)
        except subprocess.TimeoutExpired:
            cls.chrome.kill()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def open(self, music):
        t = self.tab
        says = {"paired": True, "name": "Sofa Box", "hotspot": False, "joining": None, "welcomed": True, "asleep": False,
                "playing": None, "front": "home", "music": music}
        t.call("Page.navigate", url="file://" + os.path.join(BOX, "remote.html"))
        t.until("!!window.__answers && document.readyState === 'complete'")
        t.value("window.name = JSON.stringify(%s); 1" % json.dumps({"api/state": says, "api/hello": {"ok": True},
                                                                    "api/music": {"ok": True, "done": True}}))
        t.call("Page.reload")
        t.until("!!window.__answers && !!window.__answers['api/state'] && document.readyState === 'complete'")
        return t

    def test_what_plays_and_its_buttons(self):
        t = self.open({"title": "Stand-in track one", "artist": "Stand-in artist", "name": "Edge Music", "playing": True,
                       "can": ["play", "pause", "nexttrack"], "front": False})
        t.until("!document.getElementById('music').hidden")
        self.assertEqual(t.value("document.getElementById('musicIn').textContent"), "Playing in Edge Music")
        self.assertEqual(t.value("document.getElementById('musicTitle').textContent"), "Stand-in track one · Stand-in artist")
        self.assertEqual(t.value("[document.getElementById('musicPrev').hidden, document.getElementById('musicNext').hidden]"), [True, False])
        shots = os.environ.get("SOFA_SHOTS")
        if shots:
            import base64
            os.makedirs(shots, exist_ok=True)
            with open(os.path.join(shots, "mini-player-on-the-phone.png"), "wb") as f:
                f.write(base64.b64decode(t.call("Page.captureScreenshot", format="png")["data"]))
        t.value("document.getElementById('musicToggle').click(); document.getElementById('musicNext').click(); 1")
        t.until("window.__asked.filter(a => a.path === 'api/music').length === 2")
        self.assertEqual(t.value("JSON.stringify(window.__asked.filter(a => a.path === 'api/music').map(a => a.body.act))"),
                         '["pause","nexttrack"]')

    def test_nothing_playing_no_row(self):
        t = self.open(None)
        t.until("document.getElementById('name').textContent === 'Sofa Box'")
        time.sleep(0.5)
        self.assertTrue(t.value("document.getElementById('music').hidden"))


if __name__ == "__main__":
    unittest.main()
