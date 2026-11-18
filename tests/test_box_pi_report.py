"""Sofa Box OS 1.1.91: what a Raspberry Pi 3 B+ showed in an evening on 1.1.86 (report 5V995Z), and what changed.

- Power: short of power since it started, and slowed down; at report time at its soft temperature limit. Home said
  nothing of the power: its one note a start had gone to the heat, seen 12 minutes earlier. Now each problem is told
  once (kept across starts), short of power after heat too, in plain words: what the box saw, and the Pi's own 5.1 V
  supply as what fixes it.
- Home after an app: hidden on the TV, then replaced, then the whole browser started again. The box froze Home behind
  every app, and a page frozen as it comes back in front stays hidden. Home is never frozen now; the box knows the page
  in front before it asks the browser; and a new Home is given time to load before it's judged.
- Slow presses: in the App Store the box above the rows was made anew on every press and changed height (the line about
  DRM), so every row under it moved; each framed icon on screen was a layer of its own; OK on Home started loading the
  app before its opening card was drawn.
- Video: H.264 decoded by the processor on a Pi whose video chip decodes it, and converted by Sofa when the box's mpv
  plays the file as it is (Sofa took the box for a browser: AVI, TS, DTS sound, standard-definition MPEG-2...).
- HDMI sound running dry: PipeWire without real-time priority (no RTKit on the card), one period ahead of the output.

Nothing here runs on a Pi: what only the Pi can say is listed in the pull request."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.parse
import urllib.request
from unittest import mock

import tests
from tests.test_box_apps_close import BOX, HERE, load
from tests.test_box_speed import Page, chrome, free_port, get

boxos = load("boxos")
assert tests.ROOT


def read(*path):
    with open(os.path.join(BOX, *path), encoding="utf-8") as f:
        return f.read()


def agent_with(conf, **env):
    return load("sofa-box-agent", SOFA_BOX_CONF=conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0",
                SOFA_BOX_MPV=os.path.join(HERE, "tools", "fake_mpv.py"), **env)


PI3 = dict(model="Raspberry Pi 3 Model B Plus Rev 1.3", gen=3, memory_mb=905, cores=4, cpu="4 x Cortex-A53",
           video=["VA-API: graphics (renderD128)", "bcm2835-codec-decode (video10)", "bcm2835-codec-image_fx (video18)"],
           vm=None, tv_height=1080)


# ---------------------------------------------------------------- 1. power

class PowerToldOnce(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = agent_with(cls.conf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def setUp(self):
        self.agent.power.update(note=None)
        self.agent.save_settings(power_told=[])

    def test_what_it_saw_and_what_fixes_it(self):
        note = self.agent.power_note
        n = note("throttled=0xd0008", PI3["model"])                     # the report's own value
        self.assertEqual(n["kind"], "power")
        self.assertTrue(n["text"].startswith("Since it started the power reaching it has dropped too low and the Pi slowed itself down"))
        self.assertIn("the Raspberry Pi's own power supply for a Pi 3 (5.1 V, 2.5 A), plugged into the wall", n["text"])
        self.assertIn("A phone charger or the TV's USB socket gives 5 V or less", n["text"])
        self.assertIn("It got hot too.", n["text"])                        # (0x8: at its soft temperature limit now)
        self.assertTrue(note("throttled=0x50005", PI3["model"])["text"].startswith("Right now the power"))
        self.assertNotIn("slowed", note("throttled=0x10000", PI3["model"])["text"])
        for v in ("throttled=0xd0008", "throttled=0x50005", "throttled=0x80000"):
            self.assertNotRegex(note(v, PI3["model"])["text"].lower(), r"\bfixed\b|is fine now|has been fixed")   # (only a supply fixes it)

    def test_short_of_power_is_told_after_heat_was(self):
        """The report's order: heat at 48 s (0x80000), short of power at 768 s (0xd0008). Home told the heat, and the power
        never: its one note a start was spent."""
        a = self.agent
        a.power["note"] = a.power_note("throttled=0x80000", PI3["model"])
        self.assertEqual(a.home_power()["kind"], "heat")
        a.power_seen("heat")
        self.assertIsNone(a.home_power())
        a.power["note"] = a.power_note("throttled=0xd0008", PI3["model"])
        self.assertEqual(a.home_power()["kind"], "power")                  # its own note
        a.power_seen("power")
        self.assertIsNone(a.home_power())
        self.assertEqual(a.settings()["power_told"], ["heat", "power"])

    def test_once_not_at_every_start(self):
        a = self.agent
        a.power["note"] = a.power_note("throttled=0x50000", PI3["model"])
        a.power_seen()                                                     # (an older Home says no kind: the one now)
        b = agent_with(self.conf)                                          # the box started again, the supply as it was
        b.power["note"] = b.power_note("throttled=0x50000", PI3["model"])
        self.assertIsNone(b.home_power())
        self.assertEqual(b.power_told(), ["power"])

    def test_told_again_after_a_start_with_power_enough(self):
        a = self.agent
        a.save_settings(power_told=["power"])
        values = iter([(0, "throttled=0x0"), (1, "not a Pi")])
        with mock.patch.object(a, "run", side_effect=lambda cmd, timeout=20: next(values)), \
                mock.patch.object(a, "uptime", return_value=6.5 * 3600), \
                mock.patch.object(a, "time", types.SimpleNamespace(sleep=lambda s: None, time=time.time)):
            a.watch_power()
        self.assertEqual(a.power_told(), [])                               # (an evening with power enough: a new supply)
        a.save_settings(power_told=["power"])
        values = iter([(0, "throttled=0x0"), (1, "not a Pi")])
        with mock.patch.object(a, "run", side_effect=lambda cmd, timeout=20: next(values)), \
                mock.patch.object(a, "uptime", return_value=2 * 3600.0), \
                mock.patch.object(a, "time", types.SimpleNamespace(sleep=lambda s: None, time=time.time)):
            a.watch_power()
        self.assertEqual(a.power_told(), ["power"])                        # (two hours: a supply that sags later isn't seen yet)

    def test_home_says_which_one_it_showed_once_it_was_on_the_tv(self):
        js = read("home", "home.js")
        self.assertIn('api("/box/api/power/seen", { kind: p.kind })', js)
        self.assertIn("const powerShown = { note: null, done: [], at: 0 };", js)
        self.assertIn("!powerShown.done.includes(data.power.kind)", js)
        gone = js[js.index("  function powerGone(asleep) {"):js.index("  // Home's top: the time and day")]
        self.assertIn("if (asleep || !powerShown.at || mono() - powerShown.at < 3000) return;", gone)   # (drawn unseen: not told)
        self.assertIn('if (name) powerGone(name === "sleep");', js)
        self.assertIn("!document.hidden && !document.documentElement.classList.contains(\"asleep\")", js)


# ---------------------------------------------------------------- 2. Home after an app

def browser(tabs, front="h", evaluate=None, fail=(), hook=None):
    """The box's Browser with a stand-in DevTools (as tests/test_box_white_screen.py)."""
    b = boxos.Browser.__new__(boxos.Browser)
    b.tabs, b.front, b.calls, b.screen, b.port = tabs, front, [], None, 9222
    b.said = boxos.collections.deque(maxlen=40)

    def call(method, params=None, session=None, timeout=10):
        b.calls.append((method, (params or {}).get("state") or (params or {}).get("targetId") or (params or {}).get("url") or "", session))
        if hook:
            hook(method, params or {}, session)
        if method in fail:
            raise OSError("the browser didn't answer %s" % method)
        if method == "Runtime.evaluate":
            return {"result": {"value": evaluate(params["expression"], session) if evaluate else True}}
        if method == "Target.createTarget":
            new = "new%d" % sum(1 for c in b.calls if c[0] == "Target.createTarget")
            b.tabs[new] = {"app": None, "session": "s-" + new, "url": params.get("url"), "used": 0}
            return {"targetId": new}
        if method == "Target.closeTarget":
            b.tabs.pop(params["targetId"], None)
        return {}
    b.call = call
    return b


def tabs():
    return {"h": {"app": "home", "session": "sh", "url": "http://127.0.0.1:8091/box/home#/", "used": 3},
            "n": {"app": "netflix", "session": "sn", "url": "https://www.netflix.com/", "used": 2},
            "y": {"app": "youtube", "session": "sy", "url": "https://www.youtube.com/tv", "used": 1},
            "s": {"app": "sofa", "session": "ss", "url": "http://x.localhost:8091/", "used": 1}}


class HomeIsNeverFrozen(unittest.TestCase):
    def setUp(self):
        self.sleep = boxos.time.sleep
        boxos.time.sleep = lambda s: None

    def tearDown(self):
        boxos.time.sleep = self.sleep

    def test_behind_an_app_home_stays_awake(self):
        """1.1.86 froze Home behind every app (on the stand-in: 3 times in 3 apps opened; 0 now)."""
        b = browser(tabs(), front="n", evaluate=lambda e, s: json.dumps({"playing": False}))
        b.settle("n")
        frozen = [c[2] for c in b.calls if c[0] == "Page.setWebLifecycleState" and c[1] == "frozen"]
        self.assertEqual(frozen, ["sy"])                                   # the other app; not Home, not Sofa
        self.assertNotIn("frozen", b.tabs["h"])
        self.assertTrue(b.tabs["y"]["frozen"])
        self.assertEqual(b.tabs["y"]["frozen_behind"], "netflix")

    def test_the_page_in_front_is_known_before_the_browser_is_asked(self):
        seen = []
        b = browser(tabs(), front="n", hook=lambda m, p, s: seen.append(b.front) if m == "Target.activateTarget" else None)
        b.settle = lambda front: None
        b.activate("h")
        self.assertEqual(seen, ["h"])                                      # (settle reading `front` meanwhile sees Home)
        b = browser(tabs(), front="n", fail=("Target.activateTarget",))
        b.settle = lambda front: None
        with self.assertRaises(OSError):
            b.activate("y")
        self.assertEqual(b.front, "n")                                     # (it didn't come in front: as it was)

    def test_a_page_brought_in_front_as_it_was_put_to_sleep_is_woken(self):
        def hook(method, params, session):
            if method == "Page.setWebLifecycleState" and params.get("state") == "frozen" and session == "sy":
                b.front = "y"                                              # (the remote brought it in front just then)
        b = browser(tabs(), front="n", evaluate=lambda e, s: json.dumps({"playing": False}), hook=hook)
        b.settle("n")
        states = [(c[1], c[2]) for c in b.calls if c[0] == "Page.setWebLifecycleState"]
        self.assertEqual(states, [("frozen", "sy"), ("active", "sy")])
        self.assertFalse(b.tabs["y"]["frozen"])
        self.assertIn("woken again (youtube)", b.said[-1])


class HomeBroughtBack(unittest.TestCase):
    def setUp(self):
        self.sleep = boxos.time.sleep
        boxos.time.sleep = lambda s: None

    def tearDown(self):
        boxos.time.sleep = self.sleep

    def test_a_new_home_is_given_time_to_load(self):
        """22:04:29 a new Home in its place; 22:04:31 "its page has nothing in it": the browser started again, 1.5 s
        after the new page was asked for. Now it's judged once it has loaded (up to 12 s)."""
        loads = {"n": 0}

        def evaluate(expression, session):
            if expression == "document.visibilityState":                   # (the page put in front for a moment)
                return "visible"
            if session == "sh":                                            # the old Home: hidden, whatever is tried
                return True if expression == boxos.Browser.HOME_ALIVE_JS else json.dumps(["hidden", "rgb(13, 13, 16)"])
            if expression == boxos.Browser.HOME_ALIVE_JS:                   # the new one: empty for its first 4 looks
                loads["n"] += 1
                return loads["n"] > 4
            if expression == boxos.Browser.FACTS_JS:
                return json.dumps(["visible", True])
            return json.dumps(["visible", "rgb(13, 13, 16)"])
        b = browser(tabs(), evaluate=evaluate)
        b.activate = lambda t: setattr(b, "front", t)
        self.assertTrue(b.revive("h", settle=0))
        self.assertNotIn("Browser.close", [c[0] for c in b.calls])
        said = list(b.said)
        self.assertRegex(said[0], r"Home didn't come back \(the browser has it down as hidden\): another page in front of it and back "
                                  r"\(the page says hidden; not put to sleep by the box; in front: this page; 1 Home page\)$")
        self.assertRegex(said[2], r"a new Home in its place, as it was still so after another page in front of it and back and after "
                                  r"loading it again \(the page says hidden; .*\)$")
        self.assertRegex(said[-1], r"Home is back on the TV$")

    def test_a_window_that_isnt_shown_is_told_apart_from_a_page(self):
        """The Pi's case that wasn't made to happen here: another page in front and back, and loading it again, both left
        Home hidden. If the page put in front is hidden too, the browser's window is what isn't shown: the report says so."""
        def evaluate(expression, session):
            if expression == "document.visibilityState":
                return "hidden"
            return True if expression == boxos.Browser.HOME_ALIVE_JS else json.dumps(["visible", "rgb(13, 13, 16)"])
        b = browser(tabs(), evaluate=evaluate)
        b.show("h")
        self.assertEqual(len(b.said), 1)
        self.assertRegex(b.said[0], r"^\d\d:\d\d:\d\d   the page put in front of it says hidden too: the browser's window isn't shown$")
        b = browser(tabs(), evaluate=lambda e, s: "visible" if e == "document.visibilityState" else True)
        b.show("h")
        self.assertEqual(list(b.said), [])

    def test_the_old_browsers_pages_are_forgotten(self):
        b = browser(tabs())
        b.forget_gone({"n", "fresh"})
        self.assertEqual(set(b.tabs), {"n"})
        self.assertIn('self.forget_gone({t["targetId"] for t in infos if t.get("type") == "page"})', read("boxos.py"))

    def test_the_facts_say_when_the_box_put_it_to_sleep(self):
        t = tabs()
        t["h"].update(frozen=True, frozen_at=time.time(), frozen_behind="netflix")
        b = browser(t, front="n", evaluate=lambda e, s: json.dumps(["hidden", False]))
        f = b.facts("h")
        self.assertRegex(f, r"^the page says hidden, with nothing in it; put to sleep by the box at \d\d:\d\d:\d\d behind netflix; "
                            r"in front: netflix; 1 Home page$")


# ---------------------------------------------------------------- 4. video

class TheVideoChip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = agent_with(cls.conf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def choice(self, knows, board=PI3, hwdec="auto"):
        a = self.agent
        with mock.patch.object(a, "board", return_value=board), mock.patch.object(a, "mpv_knows", return_value=knows):
            return a.hwdec_choice(dict(a.settings(), hwdec=hwdec))

    def test_a_pi_3_asks_for_its_decoder_before_mpv_has_said(self):
        self.assertEqual(self.choice(None), "v4l2m2m-copy")                # (mpv hasn't answered yet: the board says)
        self.assertEqual(self.choice(True), "v4l2m2m-copy")
        self.assertEqual(self.choice(False), "auto-safe")                  # (mpv said it hasn't it)
        self.assertEqual(self.choice(None, dict(PI3, video=[])), "auto-safe")
        self.assertEqual(self.choice(None, dict(PI3, gen=0, model="this computer")), "auto-safe")
        self.assertEqual(self.choice(None, hwdec="v4l2m2m"), "v4l2m2m")

    def test_an_answer_that_didnt_come_isnt_kept(self):
        a, asked = self.agent, []
        answers = iter(["", "Valid values:\n  v4l2m2m-copy (h264_v4l2m2m-v4l2m2m-copy)\n"])

        def ask(args, timeout):
            asked.append((args[1], timeout))
            return next(answers)
        a._mpv_help.clear()
        with mock.patch.dict(os.environ, {"SOFA_BOX_MPV": "mpv"}), mock.patch.object(a, "_mpv_ask", side_effect=ask):
            self.assertIsNone(a.mpv_knows("hwdec", "v4l2m2m-copy", wait=False))   # (a video starting doesn't wait)
            self.assertEqual(asked, [])
            self.assertIsNone(a.mpv_knows("hwdec", "v4l2m2m-copy"))       # ran out of time at a busy start: unknown
            self.assertTrue(a.mpv_knows("hwdec", "v4l2m2m-copy"))         # asked again, and kept
            self.assertTrue(a.mpv_knows("hwdec", "v4l2m2m-copy", wait=False))
        self.assertEqual(asked, [("--hwdec=help", 30), ("--hwdec=help", 30)])
        a._mpv_help.clear()

    def test_learning_goes_on_until_mpv_answers(self):
        a, rounds = self.agent, []
        seq = iter([None, None, True, True])
        with mock.patch.object(a, "mpv_knows", side_effect=lambda *x, **k: next(seq)), \
                mock.patch.object(a, "mpv_option", side_effect=lambda *x, **k: rounds.append(1) or True), \
                mock.patch.object(a, "time", types.SimpleNamespace(sleep=lambda s: None, time=time.time)):
            self.assertTrue(a.learn_mpv())
        self.assertEqual(len(rounds), 2)

    def test_the_report_says_what_was_asked_and_what_mpv_said(self):
        P, proc = self.agent.Player, types.SimpleNamespace(sofa_hw=["[ffmpeg/video] h264_v4l2m2m: Could not find a valid device"])
        run = {"at": "22:05:37", "kind": "converted", "mode": "transcode", "why": ["1080p picture (this device plays up to 720p)"],
               "started_after": 12, "video-codec": "H.264", "width": 1280, "height": 720, "container-fps": 24,
               "hwdec-current": "no", "asked": "v4l2m2m-copy", "proc": proc}
        line = P.ran_line(run)
        self.assertIn("22:05:37 converted (converted by Sofa: 1080p picture (this device plays up to 720p))", line)
        self.assertIn("decoded by the processor (asked for v4l2m2m-copy; mpv said: [ffmpeg/video] h264_v4l2m2m: Could not find a valid device)", line)
        self.assertIn("decoded by the processor,", P.ran_line(dict(run, asked="auto-safe", proc=None)))
        self.assertIn("decoded by the video chip (v4l2m2m-copy)", P.ran_line(dict(run, **{"hwdec-current": "v4l2m2m-copy"})))
        self.assertIn("converted (repackaged by Sofa: DTS sound)", P.ran_line(dict(run, mode="remux", why=["DTS sound"])))
        self.assertTrue(self.agent.HW_WORDS.search("Falling back to software decoding."))

    def test_720p_is_learned_only_from_the_chips_drops(self):
        a = self.agent
        p = a.Player()
        props = {"frame-drop-count": 200, "decoder-frame-drop-count": 0, "container-fps": 24, "hwdec-current": "no"}
        p.command = lambda *c: props.get(c[1]) if c[0] == "get_property" else None
        a.save_settings(learned_720=False, quality="auto")
        a.power["note"] = None
        with mock.patch.object(a, "board", return_value=PI3), mock.patch.object(a, "toast", lambda *x: None):
            self.assertEqual(p.check_drops(), "the processor decoded it, not the video chip")
            props["hwdec-current"] = "v4l2m2m-copy"
            a.power["note"] = a.power_note("throttled=0x50005", PI3["model"])
            self.assertEqual(p.check_drops(), "the Pi is short of power and slowed itself down")
            self.assertFalse(a.settings()["learned_720"])
            a.power["note"] = a.power_note("throttled=0x50000", PI3["model"])   # (since the start, not now)
            self.assertEqual(p.check_drops(), "learned")
        self.assertTrue(a.settings()["learned_720"])
        self.assertEqual(a.settings()["learned_720_rule"], a.LEARN_720_RULE)
        a.power["note"] = None
        a.save_settings(learned_720=False)

    def test_720p_learned_before_is_forgotten_once(self):
        a = self.agent
        a.save_settings(learned_720=True, learned_720_rule=None)
        self.assertTrue(a.forget_old_720())
        self.assertFalse(a.settings()["learned_720"])
        a.save_settings(learned_720=True)                                  # (learned by the new rule since)
        self.assertFalse(a.forget_old_720())
        self.assertTrue(a.settings()["learned_720"])
        a.save_settings(learned_720=False)
        self.assertIn("forget_old_720()", read("sofa-box-agent.py").split("def main():", 1)[1])

    def test_the_box_tells_sofa_its_player_is_mpv(self):
        a = self.agent
        with mock.patch.object(a, "board", return_value=PI3):
            c = a.caps()
        self.assertTrue(c["mpv"] and c["sd"])
        with mock.patch.object(a, "board", return_value=dict(PI3, cores=1, model="Raspberry Pi Zero W", gen=1)):
            self.assertFalse(a.caps()["sd"])                               # (one core: SD MPEG-2 is too much)
        js = open(os.path.join(HERE, "client", "app.js"), encoding="utf-8").read()
        self.assertIn("mode: p.mode, why: p.why || [],", js)                # (the page passes Sofa's word on to the box)

    def test_the_reports_settings_say_what_the_box_learned(self):
        self.assertIn('"learned_720", "learned_lite"]}),', read("sofa-box-agent.py"))


class SofaSendsTheBoxTheFile(unittest.TestCase):
    """Sofa's plan for a box whose player is mpv: the file as it is, where it used to convert it as for a browser."""

    def plan(self, ext, video, audio, mpv=True, maxh="1080"):
        from sofa import media
        info = {"duration": 60, "video": dict({"index": 0, "pix_fmt": "yuv420p", "profile": "High"}, **video),
                "audio": [{"codec": audio, "index": 1, "channels": 2, "default": 1}], "subs": []}
        qs = "mkv=1&hevc=0&hevc10=0&ac3=1&vp9=0&maxh=%s%s" % (maxh, "&mpv=1&sd=1" if mpv else "")
        with mock.patch.object(media, "probe", return_value=info), mock.patch.object(media, "tool", return_value="/usr/bin/ffmpeg"):
            return media.plan({"path": "/x." + ext, "ext": ext}, media.caps_from(urllib.parse.parse_qs(qs)))

    def test_what_mpv_plays_goes_as_it_is(self):
        h264 = {"codec": "h264", "height": 720, "width": 1280}
        for ext, audio in (("ts", "aac"), ("avi", "mp3"), ("mkv", "dts"), ("mov", "pcm_s16le"), ("m2ts", "truehd"), ("wmv", "wmav2")):
            self.assertEqual(self.plan(ext, h264, audio)["mode"], "direct", (ext, audio))
            self.assertNotEqual(self.plan(ext, h264, audio, mpv=False)["mode"], "direct", (ext, audio))   # (a browser: as before)
        for codec in ("mpeg2video", "mpeg4", "msmpeg4v3", "vc1"):
            self.assertEqual(self.plan("avi", {"codec": codec, "height": 576, "width": 720}, "mp3")["mode"], "direct", codec)
            self.assertEqual(self.plan("avi", {"codec": codec, "height": 1080, "width": 1920}, "mp3")["mode"], "transcode", codec)
        self.assertEqual(self.plan("mpg", {"codec": "mpeg2video", "height": 576, "width": 720, "interlaced": True}, "mp2")["mode"],
                         "transcode")                                     # (a DVD's interlaced picture: Sofa takes the combing out)

    def test_what_the_pi_cant_decode_is_still_converted(self):
        self.assertEqual(self.plan("mkv", {"codec": "h264", "height": 720, "pix_fmt": "yuv420p10le", "profile": "High 10"}, "aac")["mode"], "transcode")
        self.assertEqual(self.plan("mkv", {"codec": "hevc", "height": 1080}, "aac")["mode"], "transcode")
        self.assertEqual(self.plan("mp4", {"codec": "h264", "height": 1080}, "aac", maxh="720")["mode"], "transcode")
        from sofa import media
        self.assertEqual(media.caps_from(urllib.parse.parse_qs("mkv=1")).get("mpv"), False)   # (older boxes: not said)


# ---------------------------------------------------------------- 5. HDMI sound

class HdmiSound(unittest.TestCase):
    def test_real_time_and_room_ahead(self):
        sh = read("install.sh")
        self.assertIn("apt-get install -y --no-install-recommends rtkit", sh)
        conf = sh.split("cat > /etc/wireplumber/wireplumber.conf.d/50-sofa-box-hdmi.conf <<'EOF'\n", 1)[1].split("\nEOF\n", 1)[0]
        self.assertIn('{ node.name = "~alsa_output.platform-.*hdmi.*" }', conf)
        self.assertIn('{ alsa.card_name = "~vc4-hdmi.*" }', conf)
        self.assertIn("api.alsa.period-size = 1024", conf)
        self.assertIn("api.alsa.headroom = 2048", conf)
        self.assertEqual(conf.count("{"), conf.count("}"))
        self.assertEqual(conf.count("["), conf.count("]"))
        lua = sh.split("cat > /etc/wireplumber/main.lua.d/51-sofa-box-hdmi.lua <<'EOF'\n", 1)[1].split("\nEOF\n", 1)[0]
        self.assertIn('["api.alsa.headroom"] = 2048', lua)
        self.assertIn('"alsa.card_name", "matches", "vc4-hdmi*"', lua)
        # an update has them at once: the box's sound starts again with them
        self.assertIn('systemctl --user -M "$WHO@" restart wireplumber.service pipewire.service pipewire-pulse.service', sh)

    def test_the_rule_matches_the_pis_hdmi_output(self):
        conf = read("install.sh").split("50-sofa-box-hdmi.conf <<'EOF'\n", 1)[1].split("\nEOF\n", 1)[0]
        pattern = re.search(r'node.name = "~([^"]+)"', conf).group(1)
        for name in ("alsa_output.platform-3f902000.hdmi.hdmi-stereo", "alsa_output.platform-fef00700.hdmi.hdmi-stereo",
                     "alsa_output.platform-107c701400.hdmi.hdmi-stereo"):    # a Pi 3, 4 and 5
            self.assertRegex(name, "^" + pattern + "$")
        self.assertNotRegex("alsa_output.usb-Generic_USB_Audio-00.analog-stereo", "^" + pattern + "$")


# ---------------------------------------------------------------- 3. presses, in a browser

class PressesDrawLess(unittest.TestCase):
    """Home as the owner has it (Spotlight, glossy icons, the light look of a Pi 3), in a browser with the box's agent."""

    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.dir = tempfile.mkdtemp()
        conf, run, cls.www = os.path.join(cls.dir, "conf"), os.path.join(cls.dir, "run"), os.path.join(cls.dir, "www")
        for d in (conf, run, cls.www, os.path.join(conf, "icons")):
            os.makedirs(d)
        with open(os.path.join(run, "sofa-box-display"), "w") as f:
            f.write("SCALE=2\n")
        apps = [boxos.app_from_store(boxos.store_entry(sid)) for sid in ("netflix", "disney-plus", "prime-video", "max", "hulu", "tubi")]
        with open(os.path.join(conf, "apps.json"), "w") as f:
            json.dump({"apps": apps, "order": [], "hidden": []}, f)
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": True, "weather": "off", "boot_sound": "off", "home_layout": "spotlight",
                       "icon_style": "glossy", "theme": "street"}, f)
        cls.port, cls.devtools = free_port(), free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1920,1080",
                                       "--remote-debugging-port=%d" % cls.devtools, "--user-data-dir=" + os.path.join(cls.dir, "profile"),
                                       cls.base + "/box/home"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cls.dir, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(cls.port), SOFA_BOX_SLOW="1",
                                              SOFA_BOX_DEVTOOLS="0", XDG_RUNTIME_DIR=run, SOFA_BOX_UINPUT="0", SOFA_BOX_ICONS="0",
                                              SOFA_BOX_HOTSPOT="0", SOFA_BOX_CERTS="0", SOFA_BOX_NEWEST="0", SOFA_BOX_CAPTIVE_PORT="0",
                                              SOFA_BOX_REMOTE_PORT=str(free_port())))
        for _ in range(300):
            try:
                get(cls.base + "/box/api/apps", 5)
                break
            except OSError:
                time.sleep(0.2)
        cls.page = Page(cls.devtools, "/box/home")

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        cls.agent.terminate()
        cls.chrome.terminate()
        cls.agent.wait(10)
        cls.chrome.wait(10)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def open(self, hash_, ready):
        p = self.page
        p.call("Page.navigate", {"url": self.base + "/box/home?t=%d%s" % (time.time(), hash_)})
        for _ in range(150):
            if p.value(ready):
                break
            time.sleep(0.1)
        time.sleep(1.2)
        return p

    def test_the_store_box_stays_one_size_and_is_drawn_in_place(self):
        """Along a row and down to the next: the box above the rows keeps its height and its elements (the rows under it
        never move); only its words, icon and buttons change. On the bench: pieces drawn again per press 10.7 -> 6.0."""
        p = self.open("#/store", "!!document.querySelector('#storeDetail h3') && document.documentElement.classList.contains('lite')")
        p.value("window.__box = document.getElementById('storeDetail'); window.__h3 = __box.querySelector('h3'); "
                "window.__row = document.querySelectorAll('#view .rail')[1].getBoundingClientRect().top + scrollY; 1")
        names, heights = set(), set()
        for key, code in [("ArrowRight", 39)] * 5 + [("ArrowDown", 40)] + [("ArrowRight", 39)] * 3:
            p.press(key, code)
            names.add(p.value("__box.querySelector('h3').textContent"))
            heights.add(p.value("Math.round(__box.getBoundingClientRect().height)"))
            self.assertTrue(p.value("__box.querySelector('h3') === __h3 && document.getElementById('storeDetail') === __box"))
            self.assertEqual(p.value("Math.round(document.querySelectorAll('#view .rail')[1].getBoundingClientRect().top + scrollY - __row)"), 0)
            self.assertTrue(p.value("__box.scrollHeight <= __box.clientHeight + 1"))   # (nothing cut off)
        self.assertGreater(len(names), 4)
        self.assertEqual(len(heights), 1)
        self.assertTrue(p.value("[...document.querySelectorAll('#storeDetail .warn')].length === 1"))

    def test_a_framed_icon_is_no_layer_of_its_own(self):
        """Glossy icons: no stacking context, no piece placed under the screen, the letter a plain block. (On the bench,
        Home as the owner has it: 19 layers before, 8 now; the App Store 41, 27 now. A grid or a flex box for the letter
        brought them all back, so it's checked here.)"""
        p = self.open("#/", "!!document.querySelector('#view .spt-track .tile .ic.framed') && document.documentElement.classList.contains('lite')")
        self.assertTrue(p.value("[...document.querySelectorAll('.ic.framed')].every(e => getComputedStyle(e).isolation === 'auto' && "
                                "getComputedStyle(e, '::before').content === 'none' && getComputedStyle(e, '::after').zIndex === 'auto')"))
        self.assertTrue(p.value("[...document.querySelectorAll('.ic.framed.mono')].length > 0 && "
                                "[...document.querySelectorAll('.ic.framed.mono')].every(e => e.querySelector(':scope > .ic-l') && "
                                "getComputedStyle(e.querySelector('.ic-l')).display === 'block' && getComputedStyle(e.querySelector('.ic-l')).position === 'static')"))

    def test_ok_draws_its_card_before_the_app_starts_loading(self):
        """OK on Home: the opening card is on the screen (a frame drawn) before the box is asked to open the app."""
        p = self.open("#/", "!!document.querySelector('#view [data-app=\"netflix\"]')")
        p.value("""(() => { window.__log = []; const real = window.fetch; let frames = 0;
          (function tick() { frames++; requestAnimationFrame(tick); })();
          window.fetch = (u, o) => { if (String(u).includes('/box/api/open')) { window.__log.push([document.getElementById('opening').classList.contains('on'), frames]);
            return Promise.resolve(new Response('{"ok":true}', {status: 200, headers: {'Content-Type': 'application/json'}})); } return real(u, o); };
          window.__frames = () => frames; })(); 1""")
        p.value("window.__at = __frames(); document.querySelector('#view [data-app=\"netflix\"]').click(); 1")
        for _ in range(30):
            if p.value("__log.length"):
                break
            time.sleep(0.1)
        on, frames = p.value("__log[0]")
        self.assertTrue(on)
        self.assertGreaterEqual(frames - p.value("__at"), 1)               # (at least one frame with the card, first)
        js = read("home", "home.js")
        self.assertIn("opening(body.id && data.apps.find(a => a.id === body.id));\n    await drawnFirst();", js)


if __name__ == "__main__":
    unittest.main()
