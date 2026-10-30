"""The Sofa box (deploy/sofa-box): the box's agent against a real Sofa (finding it, passing its pages
through with the box's player added, playing, saving the place, telling the page a video ended), its
settings, the boot screen, the remotes (HDMI-CEC, game controllers), and setting up a Raspberry Pi's
boot files (including one LCD-show changed for a 3.5-inch screen)."""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

import tests
from tests import LIBRARY, video
from sofa import auth, media, store, web
from sofa.library import LIBRARY as LIB

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(BOX, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cec = load("sofa-box-cec")
pads = load("sofa-box-input")

MONITOR = """Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):
\tui-cmd: Up (0x01)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_RELEASED (0x45)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):
\tui-cmd: Select (0x00)
Received from TV to Playback Device 1 (0 to 4): MENU_REQUEST (0x8d):
\tmenu-req: query (0x02)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44): ui-cmd: Exit (0x0d)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):
\tui-cmd: Number 5 (0x25)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):
\tui-cmd: F1 (Blue) (0x71)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):
\tui-cmd: Play (0x44)
"""


class TvRemote(unittest.TestCase):
    def test_buttons_become_keys(self):
        keys = list(cec.keys_from(MONITOR.splitlines(True)))
        self.assertEqual(keys, ["KEY_UP", "KEY_ENTER", "KEY_BACK", "KEY_5", "KEY_PLAYPAUSE"])   # Blue: nothing

    def test_menu_request_is_noticed(self):
        self.assertTrue(any(cec.MENU_REQUEST.search(line) for line in MONITOR.splitlines()))


class Controllers(unittest.TestCase):
    def test_buttons_and_arrows(self):
        p = pads.Pad("Xbox Wireless Controller", {0: (-32768, 32767), 1: (-32768, 32767), 10: (0, 1023)})
        self.assertEqual(p.feed(1, 304, 1, 0), ["KEY_ENTER"])                 # A
        self.assertEqual(p.feed(1, 304, 0, 0.1), [])                          # let go: nothing more
        self.assertEqual(p.feed(1, 305, 1, 0.2), ["KEY_BACK"])                # B
        self.assertEqual(p.feed(1, 307, 1, 0.3), ["KEY_PLAYPAUSE"])           # X (Xbox)
        self.assertEqual(p.feed(1, 316, 1, 0.4), ["HOME"])                    # the Xbox button
        self.assertEqual(p.feed(3, 17, -1, 1.0), ["KEY_UP"])                  # D-pad up...
        self.assertEqual(p.due(1.2), [])
        self.assertEqual(p.due(1.45), ["KEY_UP"])                             # ...repeats while held
        self.assertEqual(p.feed(3, 17, 0, 1.5), [])
        self.assertEqual(p.due(3), [])
        self.assertEqual(p.feed(3, 0, 30000, 4), ["KEY_RIGHT"])               # the stick
        self.assertEqual(p.feed(3, 10, 900, 5), ["KEY_REWIND"])               # a trigger, once per press
        self.assertEqual(p.feed(3, 10, 950, 5.1), [])

    def test_playstation_layout(self):
        self.assertEqual(pads.Pad("Wireless Controller").feed(1, 308, 1, 0), ["KEY_PLAYPAUSE"])    # square
        self.assertEqual(pads.Pad("Sony Interactive Entertainment DualSense Wireless Controller").feed(1, 307, 1, 0),
                         ["KEY_SLASH"])                                                          # triangle: search


LCD_SHOW_CONFIG = """# For more options and information see
dtparam=audio=on
#dtoverlay=vc4-kms-v3d
max_framebuffers=2
[all]
hdmi_force_hotplug=1
dtparam=spi=on
dtoverlay=mhs35:rotate=90
hdmi_group=2
hdmi_mode=87
hdmi_cvt 480 320 60 6 0 0 0
hdmi_drive=2
"""


class RaspberryPiBoot(unittest.TestCase):
    """`sofa-box setup-boot` on a card LCD-show changed for a 3.5-inch screen."""

    def test_lcd_show_card_gets_the_tv_back(self):
        root = tempfile.mkdtemp()
        boot = os.path.join(root, "boot")
        os.makedirs(os.path.join(root, "etc"))
        os.makedirs(boot)
        with open(os.path.join(boot, "config.txt"), "w") as f:
            f.write(LCD_SHOW_CONFIG)
        with open(os.path.join(boot, "cmdline.txt"), "w") as f:
            f.write("console=serial0,115200 console=tty1 root=PARTUUID=abc-02 rootwait fbcon=map:10 fbcon=font:ProFont6x11\n")
        with open(os.path.join(root, "etc", "rc.local"), "w") as f:
            f.write("#!/bin/sh\nfbcp &\nexit 0\n")
        env = dict(os.environ, SOFA_BOX_ROOT=root)
        for _ in range(2):                                          # twice: the same result
            subprocess.run(["sh", os.path.join(BOX, "sofa-box"), "setup-boot", boot], check=True, env=env,
                           stdout=subprocess.DEVNULL)
        cfg = read(os.path.join(boot, "config.txt")).splitlines()
        cmd = read(os.path.join(boot, "cmdline.txt"))
        self.assertIn("#sofa-box# hdmi_cvt 480 320 60 6 0 0 0", cfg)        # the TV's full picture back
        self.assertIn("#sofa-box# hdmi_mode=87", cfg)
        self.assertIn("#sofa-box# dtoverlay=mhs35:rotate=90", cfg)         # the small screen off
        self.assertIn("dtoverlay=vc4-kms-v3d", cfg)
        self.assertIn("dtparam=audio=off", cfg)                            # sound to the TV
        self.assertEqual(cfg.count("disable_splash=1"), 1)
        self.assertIn("#sofa-box# fbcp &", read(os.path.join(root, "etc", "rc.local")))
        self.assertNotIn("fbcon=map", cmd)
        self.assertIn("console=tty3", cmd)
        self.assertEqual(cmd.split().count("splash"), 1)
        self.assertEqual(read(os.path.join(boot, "config.txt.before-sofa-box")), LCD_SHOW_CONFIG)
        shutil.rmtree(root)


def read(path):
    with open(path) as f:
        return f.read()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Agent(unittest.TestCase):
    """The box's agent, running for real against a Sofa, with a stand-in for mpv (and mpv itself when
    it's installed)."""

    @classmethod
    def setUpClass(cls):
        video(os.path.join(LIBRARY, "Movies", "Heat (1995)", "Heat (1995).mp4"), 64 * 1024)
        LIB.scan("tests")
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.sofa = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        if not store.q1("SELECT 1 FROM users WHERE name = 'boxtest'"):
            auth.create_user("boxtest", "password123")
        cls.conf = tempfile.mkdtemp()
        cls.log = os.path.join(cls.conf, "fake-mpv.log")
        with open(os.path.join(cls.conf, "settings.json"), "w") as f:
            json.dump({"server": cls.sofa}, f)
        cls.port = free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.proc = cls.start_agent(os.path.join(HERE, "tools", "fake_mpv.py"), cls.conf, cls.port, FAKE_MPV_LOG=cls.log,
                                   FAKE_MPV_DURATION="100")
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))
        for _ in range(100):
            try:
                if json.loads(cls.get("/box/state")).get("chosen"):
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        cls.post("/api/login", {"name": "boxtest", "password": "password123"})        # through the box, as the TV does

    @staticmethod
    def start_agent(mpv, conf, port, **env):
        return subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                env=dict(os.environ, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(port), SOFA_BOX_MPV=mpv,
                                         SOFA_BOX_MPV_ARGS="--vo=null --ao=null --force-window=no", **env))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)
        cls.httpd.shutdown()
        shutil.rmtree(cls.conf, ignore_errors=True)

    @classmethod
    def get(cls, path, base=None):
        with cls.opener.open((base or cls.base) + path, timeout=40) as r:
            return r.read().decode("utf-8")

    @classmethod
    def post(cls, path, body, base=None):
        req = urllib.request.Request((base or cls.base) + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Sofa": "1"})
        with cls.opener.open(req, timeout=40) as r:
            return json.loads(r.read() or b"{}")

    def wait_for(self, check, seconds=10, base=None):
        end = time.time() + seconds
        while time.time() < end:
            st = json.loads(self.get("/box/native/status", base))
            if check(st):
                return st
            time.sleep(0.25)
        self.fail("the box never got there: %s" % st)

    def ended(self, item, since, base=None):
        """What the page hears when `item` stops (as the page asks: everything after `since`)."""
        end = time.time() + 15
        while time.time() < end:
            e = json.loads(self.get("/box/native/events?since=%d" % since, base))
            since = e["n"]
            done = [x["done"] for x in e["news"] if x.get("done", {}).get("item") == item]
            if done:
                return done
        self.fail("the page never heard that %s stopped" % item)

    def test_sofa_pages_come_with_the_box_player(self):
        page = self.get("/")
        self.assertIn('<script src="/box/native.js"></script>', page)
        js = self.get("/box/native.js")
        self.assertIn("window.SofaNative", js)
        self.assertIn("slow: false", js)                                        # not a Pi 3 here
        self.assertEqual(json.loads(self.get("/box/state"))["chosen"], self.sofa)
        caps = json.loads(self.get("/box/native/caps"))
        self.assertTrue(caps["mkv"] and caps["ac3"])
        self.assertEqual(caps["maxh"], 1080)

    def test_settings(self):
        try:
            info = self.post("/box/api/settings", {"quality": "720", "theme": "ocean", "boot_text": "Leo's <room>",
                                                   "hwdec": "rm -rf /"})
            self.assertEqual(info["settings"]["quality"], "720")
            self.assertEqual(info["settings"]["theme"], "ocean")
            self.assertEqual(info["settings"]["boot_text"], "Leo's room")             # only letters and the like
            self.assertEqual(info["settings"]["hwdec"], "auto")                      # not one of the choices: ignored
            self.assertEqual(json.loads(self.get("/box/native/caps"))["maxh"], 720)
        finally:
            self.post("/box/api/settings", {"quality": "auto", "theme": "midnight", "boot_text": ""})

    def test_play_save_and_tell_the_page(self):
        n = json.loads(self.get("/box/native/events"))["n"]                     # a page opening: from now on
        self.post("/box/native/play", {"item": "m:heat:1995", "url": self.base + "/media/m%3Aheat%3A1995/file",
                                       "start": 0, "offset": 0, "duration": 100, "title": "Heat"})
        self.wait_for(lambda st: st.get("t", 0) >= 1)
        self.post("/box/native/control", {"cmd": "pause"})
        self.wait_for(lambda st: st.get("paused"))
        self.post("/box/native/control", {"cmd": "seek", "t": 40})
        self.wait_for(lambda st: st.get("t", 0) >= 40)
        self.get("/box/native/key?k=back")                                       # Back on the remote
        done = self.ended("m:heat:1995", n)
        self.assertFalse(done[0]["ended"])
        self.assertGreaterEqual(done[0]["t"], 40)
        saved = json.loads(self.get("/api/progress"))["m:heat:1995"]             # the place, saved in Sofa
        self.assertGreaterEqual(saved["t"], 40)
        self.assertFalse(saved["done"])
        fetched = [json.loads(line) for line in read(self.log).splitlines() if '"fetched"' in line]
        self.assertTrue(fetched[0]["cookie"])                                    # mpv asked Sofa as the signed-in TV
        self.assertIn(fetched[0]["status"], (200, 206))
        self.assertTrue(fetched[0]["fetched"].startswith(self.sofa))             # straight to Sofa, not through the box

    def test_two_pages_both_hear_it(self):
        n = json.loads(self.get("/box/native/events"))["n"]
        heard = []
        t = threading.Thread(target=lambda: heard.append(json.loads(self.get("/box/native/events?since=%d" % n))))
        t.start()
        time.sleep(0.3)
        self.post("/box/api/go", {"to": "#/"})
        t.join(10)
        self.assertEqual(heard[0]["news"][0]["go"], "#/")
        self.assertEqual(json.loads(self.get("/box/native/events?since=%d" % n))["news"][0]["go"], "#/")   # a second page too

    def test_adult_titles_stay_private(self):
        self.post("/box/native/play", {"item": "am:0123456789ab", "url": self.base + "/media/m%3Aheat%3A1995/file",
                                       "duration": 100, "title": "Something private", "adult": True})
        try:
            playing = json.loads(self.get("/box/state"))["playing"]
            self.assertEqual(playing["title"], "Playing")
        finally:
            n = json.loads(self.get("/box/native/events"))["n"]
            self.get("/box/native/key?k=back")
            self.ended("am:0123456789ab", n)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "needs Pillow")
    def test_boot_screen_picture(self):
        png = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.base + "/box/splash.png", timeout=30).read()
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertIn("Sofa box preview", self.get("/box/preview"))

    @unittest.skipUnless(shutil.which("mpv") and media.tool("ffmpeg"), "needs mpv and ffmpeg")
    def test_real_mpv(self):
        """mpv itself: its position moves on, it's controlled over its socket, and Back ends it."""
        path = os.path.join(LIBRARY, "Movies", "Clock (2020)", "Clock (2020).mp4")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run([media.tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "30", "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac", path], check=True)
        LIB.scan("tests")
        conf = tempfile.mkdtemp()
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"server": self.sofa}, f)
        port = free_port()
        base = "http://127.0.0.1:%d" % port
        proc = self.start_agent("mpv", conf, port)
        try:
            for _ in range(100):
                try:
                    if json.loads(self.get("/box/state", base)).get("chosen"):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.1)
            n = json.loads(self.get("/box/native/events", base))["n"]
            self.post("/box/native/play", {"item": "m:clock:2020", "url": base + "/media/m%3Aclock%3A2020/file",
                                           "start": 3, "duration": 30, "title": "Clock"}, base)
            st = self.wait_for(lambda s: s.get("t", 0) >= 5, 20, base)            # started at 3 s, and moving
            self.assertEqual(st["d"], 30)
            self.post("/box/native/control", {"cmd": "skip", "by": 10}, base)
            self.wait_for(lambda s: s.get("t", 0) >= 15, 10, base)
            self.get("/box/native/key?k=back", base)
            self.assertGreaterEqual(self.ended("m:clock:2020", n, base)[0]["t"], 15)
        finally:
            proc.terminate()
            proc.wait(10)
            shutil.rmtree(conf, ignore_errors=True)


assert tests.ROOT

if __name__ == "__main__":
    unittest.main()
