"""Sofa Box OS 1.1.63: the white, dead screen after a game.

A 1.1.60 box on a real Pi 3 B+ had to be unplugged three times in an hour: leaving Sofa Craft, opening Flare, leaving
Neverball. The TV was white; the controller and the remote were connected and did nothing.

The cause, reproduced in a container with the card's own cage 0.2.0 and Debian 13's Chromium 156 (the screen's own
picture taken with grim): when a game started, the box froze every page through DevTools, Home too, in front as it was.
To freeze a page Chromium first marks it hidden (PageHandler::SetWebLifecycleState calls WasHidden), and waking it
("active") only unfreezes: nothing marks it shown again but another page coming in front of it and going. So after the
game Home's scripts ran, the keys reached it, its own check said it was fine, and the browser drew nothing.

Here: Home is never frozen and neither is the page in front; coming back, the box looks at what is on the TV (the
screen's own picture, not the page's word) and brings Home back by steps, the whole browser last; and Home held for 4
seconds on a controller, a remote or the phone starts the TV's screen again without any of that."""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")


def read(*parts):
    with open(os.path.join(BOX, *parts), encoding="utf-8") as f:
        return f.read()


def load(name, **env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(name.replace("-", "_") + "_white", os.path.join(BOX, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)


boxos = load("boxos")
pads = load("sofa-box-input")

WHITE = b"P6\n192 108\n255\n" + bytes([255, 255, 255]) * (192 * 108)
HOME = b"P6\n192 108\n255\n" + bytes([13, 13, 16]) * (192 * 80) + bytes([255, 46, 136]) * (192 * 28)      # dark, with things on it
BARE = b"P6\n192 108\n255\n" + bytes([13, 13, 16]) * (192 * 108)


def browser(tabs, front="h", evaluate=None, fail=()):
    """The box's Browser with a stand-in DevTools: what it asks is written down."""
    b = boxos.Browser.__new__(boxos.Browser)
    b.tabs, b.front, b.calls, b.screen, b.port = tabs, front, [], None, 9222
    b.said = boxos.collections.deque(maxlen=40)

    def call(method, params=None, session=None, timeout=10):
        b.calls.append((method, (params or {}).get("state") or (params or {}).get("targetId") or (params or {}).get("url") or "", session))
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
    return {"h": {"app": "home", "session": "sh", "url": "http://127.0.0.1:8091/box/home#/games", "used": 3},
            "n": {"app": "netflix", "session": "sn", "url": "https://www.netflix.com/", "used": 2},
            "s": {"app": "sofa", "session": "ss", "url": "http://x.localhost:8091/", "used": 1}}


class AGameNeverFreezesHome(unittest.TestCase):
    def test_the_pages_behind_rest_home_and_the_one_in_front_dont(self):
        b = browser(tabs())
        b.rest()
        frozen = [c[2] for c in b.calls if c[0] == "Page.setWebLifecycleState" and c[1] == "frozen"]
        self.assertEqual(sorted(frozen), ["sn", "ss"])                       # (the pages behind; Home isn't one of them)
        self.assertNotIn("frozen", b.tabs["h"])
        self.assertIn(("Memory.simulatePressureNotification", "", "sh"), b.calls)    # the browser lets go of memory, as before
        b = browser(tabs())
        b.rest(close_apps=True)                                                # a Pi 3: the apps that aren't Sofa close
        self.assertNotIn("n", b.tabs)
        self.assertEqual([c for c in b.calls if c[0] == "Page.setWebLifecycleState" and c[2] == "sh"], [])

    def test_whatever_is_in_front_is_left_running(self):
        b = browser(tabs(), front="n")                                         # (an app in front: not frozen where it stands)
        b.tabs["h"]["frozen"] = True                                           # Home behind it, frozen when the app opened
        b.rest()
        self.assertEqual([c[2] for c in b.calls if c[0] == "Page.setWebLifecycleState"], ["ss"])

    def test_home_stops_its_own_asking_around_instead(self):
        js = read("home", "home.js")
        self.assertIn("window.sofaBoxRest = on => { resting = !!on; restLooks = 0; };", js)
        self.assertIn('document.addEventListener("keydown", () => { resting = false; }, true);', js)       # any key: awake
        self.assertIn("if (g && !g.playing) resting = false;", js)             # (the helper's word never came: it asks)
        self.assertEqual(js.count("if (resting || document.hidden"), 2)
        agent = read("sofa-box-agent.py")
        play = agent[agent.index("    def play(self, gid):"):agent.index("    def _wait(self, g, proc):")]
        self.assertLess(play.index("browser.rest(close_apps=light())"), play.index("home_rests(True)"))
        self.assertIn("except Exception:\n            home_rests(False)", play)       # it didn't start: Home is the page again
        wait = agent[agent.index("    def _wait(self, g, proc):"):agent.index("    def stop(self, why=")]
        self.assertLess(wait.index("home_rests(False)"), wait.index("browser.home(look=True)"))

    def test_a_page_that_didnt_wake_is_still_known_as_frozen(self):
        """Waking a page could fail (a busy box) and the page was written down as awake all the same."""
        b = browser(tabs(), front="n", fail=("Page.setWebLifecycleState",))
        b.tabs["h"]["frozen"] = True
        b.settle = lambda front: None
        b.activate("h")
        self.assertTrue(b.tabs["h"]["frozen"])
        self.assertIn("didn't wake", b.said[-1])


class WhatIsOnTheTv(unittest.TestCase):
    """The screen's own picture (grim asks cage for it), and what it says of Home."""

    def test_one_colour_or_a_picture(self):
        self.assertEqual({k: boxos.ppm_look(WHITE)[k] for k in ("flat", "colour")}, {"flat": True, "colour": "#ffffff"})
        look = boxos.ppm_look(HOME)
        self.assertFalse(look["flat"])
        self.assertEqual((look["colour"], look["size"]), ("#0d0d10", [192, 108]))
        self.assertTrue(boxos.ppm_look(b"P6\n# made by grim\n2 1\n255\n" + bytes([9, 9, 9, 9, 9, 9]))["flat"])
        speck = bytearray(WHITE)                                                # a pointer, a speck: still one colour
        speck[-90:] = bytes([0]) * 90
        self.assertTrue(boxos.ppm_look(bytes(speck))["flat"])
        for junk in (b"", b"PNG", b"P6\n2 2\n255\n\x00", b"P6\nx y\n255\n"):
            self.assertIsNone(boxos.ppm_look(junk))

    def test_the_picture_is_grims(self):
        d = tempfile.mkdtemp()
        try:
            grim = os.path.join(d, "grim")
            with open(os.path.join(d, "shot.ppm"), "wb") as f:
                f.write(WHITE)
            with open(grim, "w") as f:
                f.write("#!/bin/sh\necho \"$@\" > \"%s/asked\"\ncat \"%s/shot.ppm\"\n" % (d, d))
            os.chmod(grim, os.stat(grim).st_mode | stat.S_IEXEC)
            env = dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"], WAYLAND_DISPLAY="wayland-0")
            self.assertTrue(boxos.screen_picture(env)["flat"])
            with open(os.path.join(d, "asked")) as f:
                self.assertEqual(f.read().split(), ["-s", "0.1", "-t", "ppm", "-"])       # small, and nothing kept
            self.assertIsNone(boxos.screen_picture(dict(env, WAYLAND_DISPLAY="")))     # (not cage's screen: can't be told)
            with open(grim, "w") as f:
                f.write("#!/bin/sh\nexit 1\n")
            self.assertIsNone(boxos.screen_picture(env))
            self.assertIsNone(boxos.screen_picture(dict(env, PATH=os.path.join(d, "nowhere"))))    # (no grim on this box)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIn("apt-get install -y --no-install-recommends grim", read("install.sh"))

    def page(self, alive=True, visibility="visible", background="rgb(13, 13, 16)"):
        return lambda expression, session: alive if expression == boxos.Browser.HOME_ALIVE_JS else json.dumps([visibility, background])

    def test_three_looks_at_home(self):
        b = browser(tabs(), evaluate=self.page())
        self.assertIsNone(b.wrong("h"))                                       # no picture to go by: the page's word
        b.screen = lambda: boxos.ppm_look(HOME)
        self.assertIsNone(b.wrong("h"))
        b.screen = lambda: boxos.ppm_look(WHITE)                               # the page says all is well; the TV is white
        self.assertEqual(b.wrong("h"), "the TV shows one flat colour (#ffffff)")
        b.screen = lambda: boxos.ppm_look(BARE)                                # a bare page in its own colour isn't that
        self.assertIsNone(b.wrong("h"))
        b.screen = lambda: 1 / 0                                               # (the look itself failing is no verdict)
        self.assertIsNone(b.wrong("h"))
        b = browser(tabs(), evaluate=self.page(visibility="hidden"))
        self.assertEqual(b.wrong("h"), "the browser has it down as hidden")
        b = browser(tabs(), evaluate=self.page(alive=False))
        self.assertEqual(b.wrong("h"), "its page has nothing in it")


class HomeComesBackBySteps(unittest.TestCase):
    def setUp(self):
        self.sleep = boxos.time.sleep
        boxos.time.sleep = lambda s: None

    def tearDown(self):
        boxos.time.sleep = self.sleep

    def test_home_on_the_tv_is_left_alone(self):
        b = browser(tabs(), evaluate=lambda e, s: True if e == boxos.Browser.HOME_ALIVE_JS else json.dumps(["visible", "rgb(13, 13, 16)"]))
        b.screen = lambda: boxos.ppm_look(HOME)
        self.assertTrue(b.revive("h", settle=0))
        self.assertEqual({c[0] for c in b.calls}, {"Runtime.evaluate"})
        self.assertEqual(list(b.said), [])

    def test_hidden_in_front_another_page_comes_and_goes(self):
        """What a frozen Home was after a game. In the container this, and nothing else, brought its picture back:
        not waking it, not Page.bringToFront, not loading it again."""
        state = {"visibility": "hidden"}

        def evaluate(expression, session):
            return True if expression == boxos.Browser.HOME_ALIVE_JS else json.dumps([state["visibility"], "rgb(13, 13, 16)"])
        b = browser(tabs(), evaluate=evaluate)
        real = b.call

        def call(method, params=None, session=None, timeout=10):
            out = real(method, params, session, timeout)
            if method == "Target.activateTarget" and params["targetId"] == "h" and "new1" in b.tabs:
                state["visibility"] = "visible"                               # (Chromium: shown again on a real tab switch)
            return out
        b.call = call
        self.assertTrue(b.revive("h", settle=0))
        steps = [c[:2] for c in b.calls if c[0].startswith(("Target.", "Page."))]
        self.assertEqual(steps, [("Page.setWebLifecycleState", "active"), ("Target.createTarget", "about:blank"),
                                 ("Target.activateTarget", "h"), ("Target.closeTarget", "new1")])
        self.assertEqual(b.front, "h")
        self.assertNotIn("new1", b.tabs)
        self.assertRegex(b.said[0], r"Home didn't come back \(the browser has it down as hidden\): another page in front of it and back$")
        self.assertRegex(b.said[-1], r"Home is back on the TV$")

    def test_the_passing_page_never_shows_as_an_app(self):
        b = browser(tabs())
        b.tabs["blank"] = {"app": "browser", "session": "sb", "url": "about:blank", "used": 9, "passing": True}
        self.assertNotIn("blank", [r["target"] for r in b.running()])

    def test_then_loaded_again_then_a_new_home_then_the_whole_browser(self):
        b = browser(tabs(), evaluate=lambda e, s: True if e == boxos.Browser.HOME_ALIVE_JS else json.dumps(["visible", "rgb(13, 13, 16)"]))
        b.screen = lambda: boxos.ppm_look(WHITE)                               # white whatever is tried
        b.activate = lambda t: setattr(b, "front", t)
        self.assertFalse(b.revive("h", settle=0))
        said = " | ".join(b.said)
        for step in ("another page in front of it and back", "loading it again", "a new Home in its place", "the browser starts again"):
            self.assertIn(step, said)
        self.assertLess(said.index("loading it again"), said.index("a new Home in its place"))
        self.assertEqual([c[0] for c in b.calls].count("Browser.close"), 1)
        home = b.tab_of("home")                                                # (the new Home)
        self.assertFalse(b.revive(home, settle=0))                             # still white a moment later:
        self.assertEqual([c[0] for c in b.calls].count("Browser.close"), 1)    # not a browser every few seconds
        self.assertIn("Hold Home for 4 seconds", b.said[-1])

    def test_a_browser_that_wont_close_is_stopped(self):
        b = browser(tabs(), fail=("Browser.close",))
        ran = []
        real = boxos.subprocess.run
        boxos.subprocess.run = lambda cmd, **kw: ran.append(cmd)
        try:
            self.assertTrue(b.restart())
        finally:
            boxos.subprocess.run = real
        self.assertEqual(ran, [["pkill", "-KILL", "-f", "--", "--remote-debugging-port=9222"]])

    def test_the_tv_is_looked_at_after_a_game_and_from_an_app_not_on_every_home(self):
        """The screen's picture costs a Pi 3 a moment: Home pressed on Home goes by the browser's word."""
        looks = []
        for front, asked in (("h", None), ("n", None), ("h", True)):
            b = browser(tabs(), front=front, evaluate=lambda e, s: True if e == boxos.Browser.HOME_ALIVE_JS else json.dumps(["visible", "rgb(13, 13, 16)"]))
            b.screen = lambda: looks.append(1) or boxos.ppm_look(HOME)
            b.activate = lambda t, b=b: setattr(b, "front", t)
            real_thread = boxos.threading.Thread
            boxos.threading.Thread = lambda target, args, daemon, name: type("T", (), {"start": lambda self: target(*args)})()
            try:
                b.home() if asked is None else b.home(look=asked)
            finally:
                boxos.threading.Thread = real_thread
        self.assertEqual(len(looks), 2)                                        # back from an app, and after a game
        self.assertIn("browser.home(look=True)", read("sofa-box-agent.py"))

    def test_something_else_in_front_by_then_is_left_alone(self):
        b = browser(tabs(), front="n", evaluate=lambda e, s: False)
        self.assertTrue(b.revive("h", settle=0))
        self.assertEqual(b.calls, [])


class HomeHeldStartsTheScreenAgain(unittest.TestCase):
    """The way out that needs nothing of the page: the controller daemon reads the controllers and remotes itself."""

    def test_held_in_a_game_and_out_of_one(self):
        hk = pads.HomeKey()
        hk.key("xbox", 1, 100.0)
        self.assertEqual([hk.due(t, True) for t in (100.5, 100.9, 101.5, 103.9, 104.1, 104.2)],
                         [None, "leave", None, None, "rescue", None])        # the game first, the screen if it's held on
        hk = pads.HomeKey()
        hk.key("remote", 1, 100.0)
        self.assertEqual([hk.due(t, False) for t in (100.5, 103.9, 104.0)], [None, None, "rescue"])
        hk = pads.HomeKey()
        hk.key("remote", 1, 200.0)
        hk.key("remote", 2, 200.5)                                             # (a keyboard's own repeat)
        hk.key("remote", 0, 201.0)                                             # let go: an ordinary Home
        self.assertIsNone(hk.due(205.0, False))

    def test_the_hold_carries_on_when_the_game_it_left_ends(self):
        hk = pads.HomeKey()
        hk.key("xbox", 1, 100.0)
        self.assertEqual(hk.due(100.9, True), "leave")
        hk.clear()                                                             # (the game is gone: the daemon sees it)
        self.assertIsNone(hk.due(102.0, False))
        self.assertEqual(hk.due(104.0, False), "rescue")                       # still white, still held

    def test_a_tvs_own_remote_five_presses(self):
        """Over HDMI-CEC a held button arrives as presses, again and again."""
        hk = pads.HomeKey()
        for t in (300.0, 300.5, 301.0, 301.5):
            hk.key("cec", 1, t)
            hk.key("cec", 0, t)
        self.assertIsNone(hk.due(301.6, False))
        hk.key("cec", 1, 302.0)
        self.assertEqual(hk.due(302.1, False), "rescue")
        for t in (310.0, 310.2, 310.4, 310.6, 310.8):                          # again at once: it's starting already
            hk.key("cec", 1, t)
        self.assertIsNone(hk.due(311.0, False))
        hk = pads.HomeKey()
        for t in (0.0, 2.0, 4.0, 6.0, 8.0):                                    # Home now and then: just Home
            hk.key("cec", 1, t)
            hk.key("cec", 0, t)
            self.assertIsNone(hk.due(t + 0.1, False))

    def test_the_loop_wakes_for_it(self):
        self.assertAlmostEqual(pads.next_wait(100.0, 100.0, 100.0, {}, {"id": "x"}, {"a": 99.5}), 0.3)          # to leave the game
        self.assertAlmostEqual(pads.next_wait(100.0, 100.3, 100.3, {}, {"id": "x"}, {"a": 96.2}, {"a"}), 0.2)   # then for the screen
        self.assertAlmostEqual(pads.next_wait(100.0, 100.3, 100.3, {}, None, {"a": 96.1}), 0.1)

    def test_it_asks_systemd_and_writes_it_down(self):
        d = tempfile.mkdtemp()
        real = pads.RESCUES, os.environ.get("SOFA_BOX_RESCUE")
        pads.RESCUES = os.path.join(d, "conf", "screen-restarts.log")
        os.environ["SOFA_BOX_RESCUE"] = "touch %s" % os.path.join(d, "asked")
        try:
            pads.rescue("Home held for 4 seconds, or pressed 5 times, on a controller or a remote")
            for _ in range(50):
                if os.path.exists(os.path.join(d, "asked")):
                    break
                time.sleep(0.1)
            self.assertTrue(os.path.exists(os.path.join(d, "asked")))
            with open(pads.RESCUES, encoding="utf-8") as f:
                self.assertRegex(f.read(), r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d the TV's screen started again \(Home held for 4 seconds")
        finally:
            pads.RESCUES = real[0]
            os.environ.pop("SOFA_BOX_RESCUE") if real[1] is None else os.environ.__setitem__("SOFA_BOX_RESCUE", real[1])
            shutil.rmtree(d, ignore_errors=True)
        src = read("sofa-box-input.py")
        # what it runs without the stand-in is what the box's user may already run as root (install.sh's sudoers line)
        self.assertIn('["sudo", "-n", "systemctl", "restart", "sofa-box", "sofa-box-agent"]', src)
        self.assertIn("$SYSTEMCTL restart sofa-box sofa-box-agent,", read("install.sh"))
        self.assertIn("if ev.type == 1 and ev.code == KEY_HOMEPAGE:\n                            hk.key(path, ev.value, now)", src)   # a remote, a game or not
        self.assertIn("if home_button:", src)                                                                       # a controller, a game or not
        self.assertLess(pads.RESCUE_HOLD, 6)                                   # (an Xbox controller switches itself off at 6)


class TheHelpersSide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent", SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def test_a_game_that_doesnt_start_gives_home_back(self):
        """Whatever failed after the pages were put to rest left them resting (and Home, then, frozen for good)."""
        a, rests = self.agent, []
        real = a.home_rests, a.games.native, a.games.binary, a.games._start
        a.home_rests = rests.append
        a.games.native = lambda gid: {"id": gid, "name": "Flare", "controls": "pad"}
        a.games.binary = lambda g: "/usr/games/flare"

        def start(g, gid, exe):
            raise ValueError("Flare didn't start (No such file or directory).")
        a.games._start = start
        try:
            with self.assertRaises(ValueError):
                a.games.play("flare")
            self.assertEqual(rests, [True, False])
        finally:
            a.home_rests, a.games.native, a.games.binary, a.games._start = real

    def test_the_phones_home_held(self):
        a, ran = self.agent, []
        real = a.run, os.environ.get("SOFA_BOX_RESCUE")
        a.run = lambda cmd, timeout=20: ran.append(cmd) or (0, "")
        os.environ["SOFA_BOX_RESCUE"] = "systemctl-stand-in restart"
        try:
            self.assertEqual(a.rescues(), [])
            out = a.rescue("Home held on a phone")
            self.assertTrue(out["ok"])
            for _ in range(30):
                if ran:
                    break
                time.sleep(0.1)
            self.assertEqual(ran, [["systemctl-stand-in", "restart"]])
            self.assertRegex(a.rescues()[-1], r"the TV's screen started again \(Home held on a phone\)$")
        finally:
            a.run = real[0]
            os.environ.pop("SOFA_BOX_RESCUE") if real[1] is None else os.environ.__setitem__("SOFA_BOX_RESCUE", real[1])
        src = read("sofa-box-agent.py")
        self.assertIn('elif path == "/api/screen":', src)
        self.assertIn('return self.send(json.dumps(rescue("Home held on a phone")))', src)
        page = read("remote.html")
        self.assertIn('post("api/screen", { restart: true })', page)
        self.assertIn("}, 4000);", page)

    def test_the_tv_isnt_looked_at_while_something_else_has_it(self):
        a = self.agent
        real = a.boxos.screen_picture, a.asleep["on"], a.games.playing
        a.boxos.screen_picture = lambda env: {"flat": True, "colour": "#000000", "rgb": (0, 0, 0), "share": 1.0}
        try:
            a.asleep["on"], a.games.playing = False, None
            self.assertTrue(a.tv_picture()["flat"])
            a.games.playing = "neverball"                                      # a game's own screen may be anything
            self.assertIsNone(a.tv_picture())
            a.games.playing, a.asleep["on"] = None, True                       # so may the screensaver
            self.assertIsNone(a.tv_picture())
        finally:
            a.boxos.screen_picture, a.asleep["on"], a.games.playing = real

    def test_a_report_says_what_happened(self):
        src = read("sofa-box-agent.py")
        head = src[src.index("def report_text():"):src.index('    code, logs = run(["sudo", "-n", os.path.join(HERE, "sofa-box"), "report"], 90)')]
        for line in ('"the TV\'s screen started again by hand: "', '"Home after a game or an app: "', '"the TV now: "'):
            self.assertIn(line, head)
        self.assertIn('print("Game: %s ended (%s)"', src)                      # the journal: how each game ended


def chrome():
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    return None


@unittest.skipUnless(chrome(), "needs Chrome or Chromium")
class InABrowser(unittest.TestCase):
    """Home's own rest, and the phone's held Home, in real pages."""

    @classmethod
    def setUpClass(cls):
        from tests import test_box_handoff as handoff
        cls.h = handoff
        cls.dir = tempfile.mkdtemp()
        conf = os.path.join(cls.dir, "conf")
        os.makedirs(conf)
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": True, "weather": "off", "boot_sound": "off"}, f)
        cls.port, cls.devtools = handoff.free_port(), handoff.free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cls.dir, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(cls.port), SOFA_BOX_DEVTOOLS="0",
                                              SOFA_BOX_UINPUT="0", SOFA_BOX_ICONS="0", SOFA_BOX_HOTSPOT="0", SOFA_BOX_CERTS="0",
                                              SOFA_BOX_NEWEST="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_REMOTE_PORT=str(handoff.free_port())))
        for _ in range(150):
            try:
                handoff.get(cls.base + "/box/state", 2)
                break
            except OSError:
                time.sleep(0.2)
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1920,1080",
                                       "--allow-file-access-from-files", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), "about:blank"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.tab = handoff.Tab(cls.devtools)
        cls.tab.call("Page.addScriptToEvaluateOnNewDocument", source=handoff.FETCH_STUB)

    @classmethod
    def tearDownClass(cls):
        cls.tab.close()
        cls.agent.terminate()
        cls.chrome.terminate()
        cls.agent.wait(10)
        cls.chrome.wait(10)
        shutil.rmtree(cls.dir, ignore_errors=True)

    ASKED = "performance.getEntriesByType('resource').filter(e => /\\/box\\/api\\/(apps|games|setup)/.test(e.name)).length"

    def test_home_asks_nothing_while_a_game_has_the_tv(self):
        t = self.tab
        t.call("Page.navigate", url=self.base + "/box/home?t=%f#/games" % time.time())
        t.until("!!document.querySelector('#view .tile, #view .btn') && typeof window.sofaBoxRest === 'function'", 30)
        time.sleep(1.0)
        t.value("sofaBoxRest(true); 1")
        before = t.value(self.ASKED)
        time.sleep(6.5)                                    # (it asked every 2.5, 3 and 5 seconds)
        self.assertEqual(t.value(self.ASKED), before)
        t.value("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); 1")     # any key: awake
        time.sleep(6.5)
        self.assertGreater(t.value(self.ASKED), before)
        t.value("sofaBoxRest(true); 1")
        t.value("sofaBoxRest(false); 1")                   # the helper's word that the game is over
        after = t.value(self.ASKED)
        time.sleep(6.5)
        self.assertGreater(t.value(self.ASKED), after)

    def test_home_held_on_the_phone(self):
        t = self.tab
        t.call("Emulation.setDeviceMetricsOverride", width=393, height=852, deviceScaleFactor=2, mobile=True)
        try:
            t.call("Page.navigate", url="file://" + os.path.join(BOX, "remote.html"))
            t.until("!!window.__answers && document.readyState === 'complete'")
            t.value("window.name = JSON.stringify(%s); 1" % json.dumps({
                "api/state": {"paired": True, "name": "Sofa Box", "hotspot": False, "joining": None, "welcomed": True, "asleep": False, "playing": None, "front": None},
                "api/key": {"ok": True}, "api/hello": {"ok": True},
                "api/screen": {"ok": True, "message": "The TV's screen is starting again. Give it half a minute."}}))
            t.call("Page.reload")
            t.until("!!window.__answers && !!window.__answers['api/state'] && !document.getElementById('tab-remote').hidden", 20)
            down = "document.querySelector('[data-k=home]').dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0 })); 1"
            up = "document.querySelector('[data-k=home]').dispatchEvent(new PointerEvent('pointerup', { bubbles: true })); 1"
            screen = "JSON.stringify(window.__asked.filter(a => a.path === 'api/screen'))"
            t.value(down)
            time.sleep(1.0)
            t.value(up)                                    # a tap: Home, and nothing more
            time.sleep(3.5)
            self.assertEqual(json.loads(t.value(screen)), [])
            self.assertEqual(json.loads(t.value("JSON.stringify(window.__asked.filter(a => a.path === 'api/key').map(a => a.body.k))")), ["home"])
            t.value(down)
            time.sleep(4.4)                                # held
            self.assertEqual(json.loads(t.value(screen)), [{"path": "api/screen", "body": {"restart": True}}])
            t.until("document.getElementById('reportMsg').textContent.includes('starting again')")
            self.assertIn("Hold Home for 4 seconds", " ".join(t.value("document.querySelector('.stuck').innerText").split()))
        finally:
            t.call("Emulation.clearDeviceMetricsOverride")


if __name__ == "__main__":
    unittest.main()
