"""The Sofa box (deploy/sofa-box): the box's agent against a real Sofa (finding it, passing its pages
through with the box's player added, playing, saving the place, telling the page a video ended), its
settings, the boot screen, the remotes (HDMI-CEC, game controllers), and setting up a Raspberry Pi's
boot files (including one LCD-show changed for a 3.5-inch screen)."""
import importlib.util
import io
import json
import os
import re
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
        self.assertEqual(p.feed(3, 0, 0, 4.2), [])                           # (the stick let go)
        self.assertEqual(p.feed(3, 10, 900, 5), ["VOLDOWN"])                  # LT: the volume down...
        self.assertEqual(p.feed(3, 10, 950, 5.1), [])
        self.assertEqual(p.due(5.5), ["VOLDOWN"])                             # ...on and on while held
        self.assertEqual(p.due(5.65), [])                                     # (a little slower than the arrows)
        self.assertEqual(p.due(5.75), ["VOLDOWN"])
        self.assertEqual(p.feed(3, 10, 0, 6), [])
        self.assertEqual(p.due(7), [])
        self.assertEqual(p.feed(1, 315, 1, 8), ["KEY_F2"])                    # Menu: the options for what's in focus
        self.assertEqual(p.feed(1, 310, 1, 8.1), ["KEY_REWIND"])              # LB

    def test_a_web_game_keeps_its_triggers(self):
        """In one of the box's own games (Gloamwell: RT a skill, Start its menu), the triggers and Start are the
        game's: no volume, no options over it. The rest still works for the box (Back, Home, the menus' keys)."""
        p = pads.Pad("Xbox Wireless Controller", {10: (0, 1023), 9: (0, 1023)})
        p.web_game = True
        self.assertEqual(p.feed(3, 9, 1000, 0), [])                           # RT: the game's
        self.assertEqual(p.due(1), [])
        self.assertEqual(p.feed(1, 315, 1, 1.1), [])                          # Start: the game's
        self.assertEqual(p.feed(1, 304, 1, 1.2), ["KEY_ENTER"])               # A: as ever (the game ignores it)
        self.assertEqual(p.feed(1, 305, 1, 1.3), ["KEY_BACK"])                # B: Back stays the box's
        p.web_game = False
        p.feed(3, 9, 0, 2)
        self.assertEqual(p.feed(3, 9, 1000, 3), ["VOLUP"])                    # Home again: the volume

    def test_trigger_buttons_and_remote_volume(self):
        p = pads.Pad("USB Gamepad")
        self.assertEqual(p.feed(1, 313, 1, 0), ["VOLUP"])                     # a pad whose triggers are buttons
        self.assertEqual(p.feed(1, 313, 0, 0.1), [])
        r = pads.Remote({})
        self.assertEqual(r.feed(1, 115, 1), [("VOLUP", 1)])                   # a remote's volume keys: the box's volume
        self.assertEqual(r.feed(1, 114, 2), [("VOLDOWN", 1)])                 # (held: its repeats)
        self.assertEqual(r.feed(1, 113, 1), [("MUTE", 1)])
        self.assertEqual(r.feed(1, 113, 2), [])
        self.assertEqual(r.feed(1, 115, 0), [])

    def test_playstation_layout(self):
        self.assertEqual(pads.Pad("Wireless Controller").feed(1, 308, 1, 0), ["KEY_PLAYPAUSE"])    # square
        self.assertEqual(pads.Pad("Sony Interactive Entertainment DualSense Wireless Controller").feed(1, 307, 1, 0),
                         ["KEY_SLASH"])                                                          # triangle: search

    def test_idle_the_loop_sleeps(self):
        """Nothing held: woken twice a second (to look at the game), not 33 times; a held arrow wakes it when it
        repeats; a stick that's the mouse, pushed, often (smooth)."""
        p = pads.Pad("Xbox Wireless Controller", {0: (-32768, 32767), 1: (-32768, 32767)})
        entry = [None, p, False, None, {}]
        self.assertAlmostEqual(pads.next_wait(100.0, 100.0, 100.0, {"a": entry}, None, {}), 0.5)
        p.feed(1, 545, 1, 100.0)                                             # D-pad down held
        self.assertAlmostEqual(pads.next_wait(100.0, 100.0, 100.0, {"a": entry}, None, {}), pads.FIRST)
        p.feed(1, 545, 0, 100.1)
        self.assertAlmostEqual(pads.next_wait(100.1, 100.0, 100.0, {"a": entry}, None, {}), 0.4)
        game = {"id": "g", "controls": {"left": "mouse"}}
        gm = pads.GameMap(game["controls"], "Xbox Wireless Controller", {0: (-32768, 32767), 1: (-32768, 32767)})
        entry[3] = gm
        self.assertAlmostEqual(pads.next_wait(100.0, 100.0, 100.0, {"a": entry}, game, {}), 0.5)
        self.assertEqual(gm.tick(100.0), [])
        gm.feed(3, 0, 32767)
        self.assertAlmostEqual(pads.next_wait(100.0, 100.0, 100.0, {"a": entry}, game, {}), 0.012)
        self.assertEqual(gm.tick(100.0), [])                                 # (from still: no jump on the first tick)
        self.assertTrue(gm.tick(100.012))
        self.assertAlmostEqual(pads.next_wait(100.0, 100.0, 100.0, {}, game, {"a": 99.5}), 0.3)   # Home held

    def test_devices_that_arent_controllers_arent_opened_again(self):
        tmp = tempfile.mkdtemp()
        try:
            kb, pad = os.path.join(tmp, "event0"), os.path.join(tmp, "event1")
            for path in (kb, pad):
                open(path, "w").close()
            seen = pads.Seen()
            found = seen.new([kb, pad])
            self.assertEqual([p for p, _ in found], [kb, pad])
            seen.skip(*found[0])                                             # a keyboard
            self.assertEqual([p for p, _ in seen.new([kb, pad])], [pad])
            os.remove(kb)
            self.assertEqual(seen.new([pad]), [(pad, found[1][1])])
            self.assertNotIn(kb, seen.known)
            open(kb, "w").close()                                            # something new at that place
            self.assertEqual([p for p, _ in seen.new([kb])], [kb])
            seen.skip(*seen.new([kb])[0])
            os.chmod(kb, 0o600)                                              # (udev giving it its permissions)
            self.assertEqual([p for p, _ in seen.new([kb])], [kb])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


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


class BoxPages(unittest.TestCase):
    def test_every_id_once(self):
        """An id used twice: getElementById finds only the first. The phone remote's round pad once shared its id with
        the Touchpad tab's icon, so its taps went to the (invisible) icon and the Remote tab did nothing."""
        for name in ("remote.html", "home/index.html", "finder.html", "preview.html"):
            with open(os.path.join(BOX, name), encoding="utf-8") as f:
                ids = re.findall(r'\bid="([^"]+)"', f.read())
            self.assertEqual(sorted({i for i in ids if ids.count(i) > 1}), [], name)


GNU_SED = subprocess.run(["sed", "--version"], capture_output=True).returncode == 0     # the box's (a Mac's isn't)


@unittest.skipUnless(GNU_SED, "the box's boot setup uses GNU sed (Raspberry Pi OS has it; a Mac doesn't)")
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
        cls.remote_port = free_port()
        cls.proc = cls.start_agent(os.path.join(HERE, "tools", "fake_mpv.py"), cls.conf, cls.port, FAKE_MPV_LOG=cls.log,
                                   FAKE_MPV_DURATION="100", SOFA_BOX_REMOTE_PORT=str(cls.remote_port))
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
                                env=dict(os.environ, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(port), SOFA_BOX_MPV=mpv, SOFA_BOX_UINPUT="0",
                                         SOFA_BOX_HOTSPOT="0", SOFA_BOX_NEWEST="0", SOFA_BOX_CERTS="0", SOFA_BOX_ICONS="0", SOFA_BOX_LOCAL_DATA=os.path.join(conf, "local-sofa"),
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
                                     headers={"Content-Type": "application/json", "X-Sofa": "1", "X-Sofa-Box": "1"})
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
        self.assertIn('theme: "street"', js)                                    # Sofa starts in the box's own theme
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
            self.post("/box/api/settings", {"quality": "auto", "theme": "street", "boot_text": ""})

    def test_the_setup_survives_a_restart(self):
        """A box that restarts mid-setup carries on at the step it was at (kept on the card, not in the page), and
        the settings file is whole on the card before the agent answers (nothing half-written left beside it)."""
        try:
            self.post("/box/api/settings", {"setup_step": 2})
            self.assertEqual(json.loads(self.get("/box/api/apps"))["setup_step"], 2)
            self.post("/box/api/settings", {"setup_step": 9})                        # not a step: ignored
            with open(os.path.join(self.conf, "settings.json")) as f:
                self.assertEqual(json.load(f)["setup_step"], 2)
            self.assertFalse(os.path.exists(os.path.join(self.conf, "settings.json.new")))
        finally:
            self.post("/box/api/settings", {"setup_step": 0})

    def test_play_save_and_tell_the_page(self):
        n = json.loads(self.get("/box/native/events"))["n"]                     # a page opening: from now on
        self.post("/box/native/play", {"item": "m:heat:1995", "url": self.base + "/media/m%3Aheat%3A1995/file",
                                       "start": 0, "offset": 0, "duration": 100, "title": "Heat"})
        self.wait_for(lambda st: st.get("t", 0) >= 1)
        self.post("/box/native/control", {"cmd": "pause"})
        self.wait_for(lambda st: st.get("paused"))
        self.post("/box/native/control", {"cmd": "seek", "t": 40})
        self.wait_for(lambda st: st.get("t", 0) >= 40)
        self.post("/box/native/key?k=back", {})                                       # Back on the remote
        done = self.ended("m:heat:1995", n)
        self.assertFalse(done[0]["ended"])
        self.assertGreaterEqual(done[0]["t"], 40)
        saved = json.loads(self.get("/api/progress"))["m:heat:1995"]             # the place, saved in Sofa
        self.assertGreaterEqual(saved["t"], 40)
        self.assertFalse(saved["done"])
        fetched = [json.loads(line) for line in read(self.log).splitlines() if '"status"' in line]
        self.assertTrue(fetched[0]["cookie"])                                    # mpv asked Sofa as the signed-in TV
        self.assertIn(fetched[0]["status"], (200, 206))
        self.assertTrue(fetched[0]["fetched"].startswith(self.sofa))             # straight to Sofa, not through the box

    def test_a_slow_start_says_so(self):
        """Resuming a video Sofa converts first can take a while: the player screen (sofa-player.lua) shows its start
        card from mpv's first moment (what it is and from where, written for it before mpv starts), and the card goes
        once the picture moves. The page hears that too: its own start card, behind mpv, goes. Never mpv's own corner
        text (it sat in the part of the picture a TV crops)."""
        n = json.loads(self.get("/box/native/events"))["n"]
        self.post("/box/native/play", {"item": "m:heat:1995", "url": self.base + "/media/m%3Aheat%3A1995/file?fake_delay=4",
                                       "start": 0, "offset": 600, "duration": 7200, "title": "Heat", "h24": True,
                                       "markers": [{"kind": "intro", "start": 610, "end": 650}, "not a marker"]})
        self.wait_for(lambda st: st.get("t", 0) >= 601, 20)
        time.sleep(1.5)
        log = [json.loads(line) for line in read(self.log).splitlines()]
        args = [x for x in log if x.get("started")][-1]["args"]
        with open(next(a for a in args if a.startswith("--script-opts=")).split("sofa_player-info=", 1)[1]) as f:
            info = json.load(f)
        self.assertEqual((info["title"], info["kind"], info["at"], info["offset"], info["h24"]), ("Heat", "resume", 600, 600, True))
        self.assertEqual(info["markers"], [{"kind": "intro", "start": 610, "end": 650}])
        info_file = next(a for a in args if a.startswith("--script-opts=")).split("sofa_player-info=", 1)[1]
        osd = [json.loads(c["command"][3]) for c in log if c.get("command", [""])[:3] == ["script-message-to", "sofa_player", "sofa"]]
        self.assertIn({"card": False}, osd)                                       # gone once it plays
        self.assertFalse([c for c in log if c.get("command", [""])[0] == "show-text"])
        news = json.loads(self.get("/box/native/events?since=%d" % n))["news"]
        self.assertTrue(any((x.get("playing") or {}).get("item") == "m:heat:1995" for x in news))
        self.post("/box/native/key?k=back", {})
        self.ended("m:heat:1995", n)
        self.assertFalse(os.path.exists(info_file))                              # (gone with its mpv: it names the title)

    def test_back_on_the_player_screen(self):
        """Back is the player screen's own key now (sofa-player.lua stops mpv at once, with 10): the box takes it as
        Back, as before: the place saved, not the end of the video, not a player that failed (no "couldn't play")."""
        n = json.loads(self.get("/box/native/events"))["n"]
        self.post("/box/native/play", {"item": "m:heat:1995", "url": self.base + "/media/m%3Aheat%3A1995/file",
                                       "start": 50, "offset": 0, "duration": 100, "title": "Heat"})
        self.wait_for(lambda st: st.get("t", 0) >= 51)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(os.path.join(tempfile.gettempdir(), "sofa-mpv-%d.sock" % self.proc.pid))
        s.sendall(b'{"command": ["quit", "10"]}\n')
        s.recv(1000)
        s.close()
        done = self.ended("m:heat:1995", n)
        self.assertFalse(done[0]["ended"])
        self.assertFalse(done[0].get("failed"))
        self.assertGreaterEqual(done[0]["t"], 50)
        news = json.loads(self.get("/box/native/events?since=%d" % n))["news"]
        self.assertFalse([x for x in news if "toast" in x])                       # (not "That video couldn't play")

    @staticmethod
    def long_clock():
        """A two-minute video in the library, for Sofa to convert: its id and the page's request for it (`hls`)."""
        path = os.path.join(LIBRARY, "Movies", "Long Clock (2021)", "Long Clock (2021).mp4")
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            subprocess.run([media.tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                            "-t", "120", "-c:v", "libx264", "-preset", "ultrafast", "-g", "10", path], check=True)
            LIB.scan("tests")
        return "m:long-clock:2021", "/api/hls/m%3Along-clock%3A2021?mode=remux"

    @unittest.skipUnless(media.tool("ffmpeg"), "needs ffmpeg")
    def test_skipping_far_in_a_converted_video(self):
        """A video Sofa converts for the box, resumed at 1:00 (Sofa's stream starts there), and the phone remote's line
        back to 0:20: the box asks Sofa (as the signed-in TV) to convert it again from 0:20, mpv loads that and opens it
        with the TV's cookie, the conversion before stops, and the place counts (and is saved) from 0:20."""
        item, ask = self.long_clock()
        first = json.loads(self.get(ask + "&t=60.0"))                         # as the page asks, through the box
        n = json.loads(self.get("/box/native/events"))["n"]
        self.post("/box/native/play", {"item": item, "url": self.base + first["url"], "start": 0, "offset": 60,
                                       "duration": 120, "title": "Long Clock", "hls": self.base + ask})
        self.wait_for(lambda st: st.get("t", 0) >= 61, 20)
        self.post("/box/native/control", {"cmd": "seek", "t": 20})
        self.wait_for(lambda st: st.get("t") == 20, 10)                          # at once: where it's going
        self.wait_for(lambda st: 21 <= st.get("t", 0) < 50 and not st.get("paused"), 30)    # then on from there
        log = [json.loads(line) for line in read(self.log).splitlines()]
        loaded = [x["command"][1] for x in log if x.get("command", [""])[0] == "loadfile"]
        self.assertEqual(len(loaded), 1)
        self.assertTrue(loaded[0].startswith(self.sofa + "/media/hls/"))         # straight to Sofa, a new conversion
        self.assertNotIn(first["session"], loaded[0])
        opened = [x for x in log if x.get("fetched") == loaded[0]]
        self.assertTrue(opened[0]["cookie"])                                     # as the signed-in TV
        self.assertIn(opened[0]["status"], (200, 206))
        with self.assertRaises(urllib.error.HTTPError) as gone:                  # the conversion before: stopped
            self.get(first["url"])
        self.assertEqual(gone.exception.code, 404)
        self.post("/box/native/key?k=back", {})
        done = self.ended(item, n)
        self.assertTrue(20 <= done[0]["t"] < 60, done)
        saved = json.loads(self.get("/api/progress"))[item]
        self.assertTrue(20 <= saved["t"] < 60, saved)

    def test_a_player_that_cant_start_hands_back_to_the_page(self):
        n = json.loads(self.get("/box/native/events"))["n"]
        self.post("/box/native/play", {"item": "m:gone:2001", "url": self.base + "/media/m%3Agone%3A2001/file",
                                       "start": 0, "offset": 0, "duration": 100, "title": "Gone"})
        done = self.ended("m:gone:2001", n)
        self.assertTrue(done[0].get("failed"))                                   # the page plays it itself
        self.assertTrue(done[0].get("error"))

    def raw(self, path, host, body=None, headers=None):
        """A request to the agent as a page at `host` makes it."""
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers=dict({"Host": host, "Content-Type": "application/json"}, **(headers or {})))
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(req, timeout=20) as r:
                return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8", "replace")

    def test_a_report_before_the_box_is_registered(self):
        """A box whose id the Sofa Box service hasn't taken yet (offline at first, or it said no) sends its report
        without that id (counted by its address): with it, the service answered "Unknown box" and nothing arrived."""
        agent = load("sofa-box-agent")
        sent = []
        agent.secure_remote.acct = {"id": "ab2cd3ef4g", "secret": "5e" * 24, "unregistered": True}
        agent.secure_remote.call = lambda route, body, timeout=60: sent.append((route, body)) or {"report": "ABC123"}
        agent.report_text = lambda: "the report"
        agent.CONF_DIR = tempfile.mkdtemp()
        try:
            self.assertTrue(agent.send_report()["ok"])
            self.assertEqual(sent[-1], ("/v1/report", {"report": "the report"}))
            agent.secure_remote.acct.pop("unregistered")                          # taken: signed with its secret
            agent._report["at"] = 0
            agent.send_report()
            self.assertEqual(sent[-1][1].get("id"), "ab2cd3ef4g")
        finally:
            shutil.rmtree(agent.CONF_DIR, ignore_errors=True)

    def test_a_plain_get_only_reads(self):
        """Any page the box's browser opens (an app from the store) can point an <img> at the agent: a GET mustn't do
        anything. Factory reset, reboot, Home, the phones forgotten, a key: only a POST with X-Sofa-Box."""
        home = "127.0.0.1:%d" % self.port
        for path in ("/box/api/action/factory-reset", "/box/api/action/reboot", "/box/api/action/update",
                     "/box/api/remote/forget", "/box/api/hotspot", "/box/api/sleep", "/box/api/home", "/box/api/go",
                     "/box/native/key?k=home", "/box/native/control", "/box/native/play", "/box/api/bt/pair",
                     "/box/api/sofa/remove", "/box/api/apps/remove", "/box/api/files/delete"):
            status, headers, _ = self.raw(path, home)
            self.assertEqual(status, 405, path)
            self.assertEqual(headers.get("Allow"), "POST")
        for path in ("/box/state", "/box/api/info", "/box/api/apps", "/box/native/caps", "/box/home/", "/box/api/games"):
            self.assertEqual(self.raw(path, home)[0], 200, path)                       # what's on: still a GET
        self.assertEqual(self.raw("/box/native/key?k=ok", home, {})[0], 400)          # a POST from elsewhere: no header
        self.assertEqual(self.raw("/box/native/key?k=ok", home, {}, {"X-Sofa-Box": "1"})[0], 200)
        with open(load("sofa-box-agent").live_input_conf(), encoding="utf-8") as f:   # mpv's keys post too
            self.assertIn('"-X" "POST" "-H" "X-Sofa-Box: 1"', f.read())
        with open(os.path.join(BOX, "mpv-input.conf"), encoding="utf-8") as f:
            for line in f:
                if "/box/" in line:
                    self.assertIn('"-X" "POST" "-H" "X-Sofa-Box: 1"', line)

    def test_each_server_at_its_own_address(self):
        import importlib
        sys.path.insert(0, BOX)
        boxservers = importlib.import_module("boxservers")
        st = json.loads(self.get("/box/api/sofa"))
        mine = [x for x in st["servers"] if x["url"] == self.sofa]
        self.assertTrue(mine)                                                    # the old setting, moved to the list
        sid = mine[0]["id"]
        self.assertEqual(sid, boxservers.server_id("sofa", self.sofa))
        host = "%s.localhost:%d" % (sid, self.port)
        status, _, page = self.raw("/", host)
        self.assertEqual(status, 200)
        self.assertIn('<script src="/box/native.js"></script>', page)           # Sofa, with the box's player
        self.assertEqual(self.raw("/box/native.js", host)[0], 200)
        self.assertEqual(self.raw("/box/api/apps", host)[0], 403)              # the box's own controls: not from there
        self.assertEqual(self.raw("/box/api/action/reboot", host, {}, {"X-Sofa-Box": "1"})[0], 403)
        self.assertEqual(self.raw("/", "evil.example:%d" % self.port)[0], 403)     # someone else's name for the box
        self.assertEqual(self.raw("/", "nope.localhost:%d" % self.port)[0], 403)
        home = "127.0.0.1:%d" % self.port
        self.assertEqual(self.raw("/box/api/settings", home, {"quality": "720"})[0], 400)    # no other site can post here
        status, _, body = self.raw("/box/api/sofa/add", home, {"url": self.sofa}, {"X-Sofa-Box": "1"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["server"]["kind"], "sofa")
        # playing from that address goes to that server
        status, headers, _ = self.raw("/api/login", host, {"name": "boxtest", "password": "password123"}, {"X-Sofa": "1"})
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";")[0]                            # the browser keeps it for that address
        n = json.loads(self.get("/box/native/events"))["n"]
        self.raw("/box/native/play", host, {"item": "m:heat:1995", "url": "http://%s/media/m%%3Aheat%%3A1995/file" % host,
                                            "start": 0, "offset": 0, "duration": 100, "title": "Heat"}, {"X-Sofa-Box": "1", "Cookie": cookie})
        self.wait_for(lambda st: st.get("t", 0) >= 1)
        self.post("/box/native/key?k=back", {})
        self.ended("m:heat:1995", n)
        fetched = [json.loads(line) for line in read(self.log).splitlines() if '"fetched"' in line]
        self.assertTrue(fetched[-1]["fetched"].startswith(self.sofa + "/media/"))

    def test_a_share_link_through_the_box(self):
        import importlib
        sys.path.insert(0, BOX)
        boxservers = importlib.import_module("boxservers")
        from sofa import config as cfg, sharing
        cfg.update({"share_on": True})
        try:
            sharing.set_shared("m:heat:1995", True)
            entry = boxservers.identify(self.sofa + "/s/" + sharing.token())
            self.assertEqual((entry["kind"], entry["start"]), ("sofa", "/s/" + sharing.token()))
            self.assertTrue(entry["public"])
            status, _, body = self.raw("/box/api/sofa/add", "127.0.0.1:%d" % self.port, {"url": self.sofa + "/s/" + sharing.token()},
                                       {"X-Sofa-Box": "1"})
            sid = json.loads(body)["server"]["id"]
            status, headers, _ = self.raw("/s/%s?tv=1" % sharing.token(), "%s.localhost:%d" % (sid, self.port))
            self.assertEqual(status, 302)
            self.assertEqual(headers["Location"], "/?tv=1")                       # stays on the box, in TV mode
            self.assertNotIn("Secure", headers["Set-Cookie"])
            with self.assertRaises(ValueError):
                boxservers.identify("http://127.0.0.1:1")                      # nothing there
        finally:
            cfg.update({"share_on": False})
            sharing.set_shared("m:heat:1995", False)

    def test_phone_remote(self):
        remote = "http://127.0.0.1:%d" % self.remote_port
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

        def call(path, body=None, cookie="", header=True):
            req = urllib.request.Request(remote + path, data=None if body is None else json.dumps(body).encode(),
                                         headers=dict({"Content-Type": "application/json", "Cookie": cookie}, **({"X-Sofa-Remote": "1"} if header else {})))
            try:
                with opener.open(req, timeout=20) as r:
                    return r.status, dict(r.headers), r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, dict(e.headers), e.read().decode()
        self.assertEqual(call("/")[0], 200)                                       # the page itself
        self.assertEqual(call("/api/state")[0], 401)                              # nothing else without the code
        self.assertEqual(call("/api/key", {"k": "ok"})[0], 401)
        self.assertEqual(call("/api/pair", {"code": "nope"})[0], 403)
        code = json.loads(self.get("/box/api/setup"))["remote"]["code"]
        self.assertEqual(call("/api/pair", {"code": code}, header=False)[0], 400)    # no other site can post here
        status, headers, _ = call("/r/" + code)                                   # the QR code on the TV
        self.assertEqual(status, 302)
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertEqual(json.loads(call("/api/state", cookie=cookie)[2])["paired"], True)
        self.assertEqual(call("/api/key", {"k": "up"}, cookie)[0], 200)
        self.assertEqual(call("/api/key", {"k": "rm -rf"}, cookie)[0], 400)
        self.assertFalse(json.loads(call("/api/report", {}, cookie)[2])["ok"])    # Send a report (no service here)
        self.assertEqual(call("/r/" + code)[1]["Location"], "/?again=1")         # each code works once
        self.post("/box/api/remote/forget", {})
        self.assertEqual(call("/api/state", cookie=cookie)[0], 401)

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
            self.post("/box/native/key?k=back", {})
            self.ended("am:0123456789ab", n)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "needs Pillow")
    def test_boot_screen_picture(self):
        png = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.base + "/box/splash.png", timeout=30).read()
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertIn("Sofa box preview", self.get("/box/preview"))

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "needs Pillow")
    def test_boot_screen_shows_the_version(self):
        """Under SOFA BOX, "OS 1.1.1" (deploy/sofa-box/VERSION); a box without the file shows none."""
        spec = importlib.util.spec_from_file_location("sofa_box_art", os.path.join(BOX, "sofa-box-art.py"))
        art = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(art)
        with open(os.path.join(BOX, "VERSION")) as f:
            self.assertEqual(art.os_version(), f.read().strip())
        self.assertEqual(art.Colors(None).theme, "street")                 # no theme saved yet: Street, all of it
        self.assertEqual(art.Colors(None).second, art.Colors("street").second)
        theme = tempfile.mkdtemp()
        try:
            art.write_plymouth(theme, {"theme": "pirate"})
            self.assertTrue(os.path.exists(os.path.join(theme, "version.png")))
            with open(os.path.join(theme, "sofa.script")) as f:
                self.assertIn('version = place("version.png"', f.read())
            art.os_version = lambda: ""
            art.write_plymouth(theme, {"theme": "pirate"})
            self.assertFalse(os.path.exists(os.path.join(theme, "version.png")))
            with open(os.path.join(theme, "sofa.script")) as f:
                self.assertIn("version = Sprite();", f.read())
        finally:
            shutil.rmtree(theme, ignore_errors=True)

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
            self.post("/box/native/key?k=back", {}, base)
            self.assertGreaterEqual(self.ended("m:clock:2020", n, base)[0]["t"], 15)
        finally:
            proc.terminate()
            proc.wait(10)
            shutil.rmtree(conf, ignore_errors=True)

    @unittest.skipUnless(shutil.which("mpv") and media.tool("ffmpeg") and os.path.exists("/usr/bin/curl"), "needs mpv, ffmpeg and curl")
    def test_real_mpv_skips_far(self):
        """mpv itself, with its player screen, and Sofa converting: a video resumed at 1:00 (Sofa's stream starts there),
        and 0 on the remote (the start). The screen asks the box (as mpv's own keys do), the box asks Sofa to convert it
        from the start, mpv plays that, and the box counts from there."""
        item, ask = self.long_clock()
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
            first = json.loads(self.get(ask + "&t=60.0", base))
            n = json.loads(self.get("/box/native/events", base))["n"]
            self.post("/box/native/play", {"item": item, "url": base + first["url"], "start": 0, "offset": 60, "duration": 120,
                                           "title": "Long Clock", "hls": base + ask}, base)
            self.wait_for(lambda s: s.get("t", 0) >= 62, 30, base)
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(os.path.join(tempfile.gettempdir(), "sofa-mpv-%d.sock" % proc.pid))
            s.sendall(b'{"command": ["keypress", "0"]}\n')
            s.recv(1000)
            s.close()
            self.wait_for(lambda s: 0 <= s.get("t", 99) < 30 and not s.get("paused"), 30, base)
            time.sleep(2)
            st = self.wait_for(lambda s: 1 <= s.get("t", 0) < 30, 10, base)     # it plays on from there
            self.post("/box/native/key?k=back", {}, base)
            done = self.ended(item, n, base)
            self.assertTrue(st["t"] <= done[0]["t"] < 40, (st, done))
            self.assertFalse(done[0].get("failed"))
        finally:
            proc.terminate()
            proc.wait(10)
            shutil.rmtree(conf, ignore_errors=True)


def chrome():
    """A Chromium or Chrome to steer over DevTools (GitHub's machines have Chrome), or None."""
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    import glob
    found = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
    return found[-1] if found else None


class BoxOS(unittest.TestCase):
    """The Sofa Box OS side of the agent: apps, the store, files, games and the home screen's pages (no browser
    here: opening an app gives its address back)."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls.conf = os.path.join(cls.home, ".config", "sofa-box")
        os.makedirs(cls.conf)
        with open(os.path.join(cls.conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": True}, f)
        cls.port = free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.proc = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                    env=dict(os.environ, HOME=cls.home, SOFA_BOX_CONF=cls.conf, SOFA_BOX_PORT=str(cls.port),
                                             SOFA_BOX_DEVTOOLS="0", SOFA_BOX_ICONS="0", SOFA_BOX_MPV=os.path.join(HERE, "tools", "fake_mpv.py")))
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            try:
                cls.get("/box/api/files")
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)
        shutil.rmtree(cls.home, ignore_errors=True)

    @classmethod
    def get(cls, path):
        with cls.opener.open(cls.base + path, timeout=20) as r:
            return json.loads(r.read() or b"{}")

    @classmethod
    def post(cls, path, body):
        req = urllib.request.Request(cls.base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-Sofa-Box": "1"})
        try:
            with cls.opener.open(req, timeout=20) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def ids(self):
        return [a["id"] for a in self.get("/box/api/apps")["apps"]]

    def test_apps_and_the_store(self):
        ids = self.ids()
        self.assertEqual(ids[:7], ["sofa", "live", "browser", "store", "games", "files", "settings"])      # the box's own first
        self.assertIn("edge-music", ids)                                                         # ours, on a new box
        store = self.get("/box/api/store")
        self.assertTrue(any(e["id"] == "edge-music" and e["installed"] for s in store["sections"] for e in s["apps"]))
        self.assertEqual(self.post("/box/api/apps/install", {"store_id": "somafm"})[0], 200)
        status, r = self.post("/box/api/apps/install", {"url": "radio.example.org/live", "name": "Kitchen radio"})
        self.assertEqual((status, r["app"]["name"], r["app"]["url"]), (200, "Kitchen radio", "https://radio.example.org/live"))
        self.assertEqual(self.post("/box/api/apps/install", {"url": "not an address"})[0], 400)
        self.assertEqual(self.post("/box/api/apps/install", {"store_id": "nope"})[0], 400)
        ids = self.ids()
        self.assertTrue({"somafm", r["app"]["id"]} <= set(ids))
        self.post("/box/api/apps/arrange", {"order": ["somafm", "sofa"], "hidden": ["games", "made-up"]})
        apps = self.get("/box/api/apps")["apps"]
        self.assertEqual([a["id"] for a in apps][:2], ["somafm", "sofa"])
        self.assertEqual([a["id"] for a in apps if a["hidden"]], ["games"])
        self.assertTrue(self.post("/box/api/apps/remove", {"id": "somafm"})[1]["ok"])
        self.assertFalse(self.post("/box/api/apps/remove", {"id": "sofa"})[1]["ok"])               # the box's own stay
        self.assertNotIn("somafm", self.ids())

    def test_opening_without_the_browser(self):
        self.assertEqual(self.post("/box/api/open", {"id": "edge-music"})[1]["url"], "https://music.edgeventure.uk/?client=sofabox")
        self.assertEqual(self.post("/box/api/open", {"id": "sofa", "hash": "#/movies"})[1]["url"], self.base + "/?tv=1#/movies")
        self.assertEqual(self.post("/box/api/open", {"url": "javascript:alert(1)"})[0], 400)
        self.assertEqual(self.post("/box/api/open", {"id": "not-installed"})[0], 400)

    def test_files(self):
        downloads = os.path.join(self.home, "Downloads")
        roots = [r["id"] for r in self.get("/box/api/files")["roots"]]
        self.assertEqual(roots[:4], ["downloads", "videos", "music", "pictures"])
        with open(os.path.join(downloads, "song.mp3"), "wb") as f:
            f.write(b"x" * 10)
        listing = self.get("/box/api/files/list?root=downloads")
        self.assertEqual([(i["name"], i["kind"]) for i in listing["items"]], [("song.mp3", "audio")])
        self.assertEqual(self.post("/box/api/files/folder", {"root": "downloads", "path": "", "name": "Mixes"})[0], 200)
        self.assertEqual(self.post("/box/api/files/rename", {"root": "downloads", "path": "song.mp3", "name": "tune.mp3"})[0], 200)
        self.assertEqual(self.post("/box/api/files/move", {"root": "downloads", "path": "tune.mp3", "to_root": "music"})[0], 200)
        self.assertTrue(os.path.exists(os.path.join(self.home, "Music", "tune.mp3")))
        for bad in ({"root": "downloads", "path": "../.config/sofa-box/settings.json"}, {"root": "downloads", "path": ""},
                    {"root": "nowhere", "path": "x"}):
            self.assertEqual(self.post("/box/api/files/delete", bad)[0], 400)                    # nothing outside, never the folder
        self.assertTrue(os.path.exists(os.path.join(self.conf, "settings.json")))
        self.assertEqual(self.post("/box/api/files/delete", {"root": "downloads", "path": "Mixes"})[0], 200)
        self.assertEqual(self.get("/box/api/files/list?root=downloads")["items"], [])

    def test_the_home_screens_pages(self):
        for path in ("/box/home", "/box/home/home.js", "/box/home/home.css", "/box/games/pair-up/", "/box/games/gloamwell/",
                     "/box/games/cinder-knight/", "/box/games/shadow-heist/", "/box/games/rune-tactics/", "/box/games/micro-drifters/",
                     "/box/games/neon-brawler/", "/box/games/void-drifter/", "/box/games/cosmic-cascade/", "/box/games/pad.js",
                     "/box/games/tidewing/", "/box/games/ironmaw/", "/box/games/low3d.js", "/box/games/probe/",
                     "/box/fonts/instrument-sans-latin-wght-normal.woff2"):
            with self.opener.open(self.base + path, timeout=20) as r:
                self.assertEqual(r.status, 200, path)
        self.assertEqual(len(self.get("/box/api/games")["games"]), 13)
        self.assertIn("memory_free", self.get("/box/api/info"))                 # (the games check, in probe/, shows it)
        with self.assertRaises(urllib.error.HTTPError):
            self.opener.open(self.base + "/box/home/../sofa-box-agent.py", timeout=20)


class BoxPointer(unittest.TestCase):
    """At a start the screen's shell (cage) draws its black arrow mid-screen as soon as anything can point, and nothing
    hid it until the pointer first moved. Home, once shown, asks the box to put it in its corner, where pages hide it."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        old = {k: os.environ.get(k) for k in ("SOFA_BOX_CONF", "SOFA_BOX_DEVTOOLS", "SOFA_BOX_CAPTIVE_PORT")}
        os.environ.update(SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0")
        try:
            cls.agent = load("sofa-box-agent")
        finally:
            for k, v in old.items():
                os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def test_parking_really_moves_it(self):
        moves = []

        class Device:
            def write(self, kind, code, value):
                moves.append((code, value))

            def syn(self):
                moves.append("syn")
        p = self.agent.PhoneRemote.__new__(self.agent.PhoneRemote)
        p.tried, p.kb, p.mouse, p.used, p.parked, p.at = True, object(), Device(), 0, True, [1.0, 1.0]
        p.ecodes = type("E", (), {"EV_ABS": 3, "ABS_X": 0, "ABS_Y": 1})
        p.park_now()
        span = self.agent.PhoneRemote.SPAN
        xs = [v for m in moves if m != "syn" for c, v in [m] if c == 0]
        self.assertEqual(xs[-1], span)                                   # in the corner
        self.assertLess(xs[0], span)                                     # from beside it: a real move (not dropped)
        moves.clear()
        p.used = __import__("time").time()                               # a phone using it right now: left alone
        p.park_now()
        self.assertEqual(moves, [])
        self.assertEqual(self.agent.box_action("park-pointer", {}), {"ok": True})


class BoxBluetooth(unittest.TestCase):
    """Bluetooth devices from one call to bluetoothd (busctl), and what each one is."""

    def test_one_call_for_every_device(self):
        boxos = load("boxos")
        busctl = json.dumps({"type": "a{oa{sa{sv}}}", "data": [{
            "/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": {"type": "b", "data": True}}},
            "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {"Address": {"type": "s", "data": "AA:BB:CC:DD:EE:01"},
                                                             "Name": {"type": "s", "data": "Xbox Wireless Controller"},
                                                             "Icon": {"type": "s", "data": "input-gaming"}, "RSSI": {"type": "n", "data": -48},
                                                             "Paired": {"type": "b", "data": False}, "Connected": {"type": "b", "data": False}}},
            "/org/bluez/hci0/dev_BB": {"org.bluez.Device1": {"Address": {"type": "s", "data": "AA:BB:CC:DD:EE:02"},
                                                             "Name": {"type": "s", "data": "RC-17"}, "Appearance": {"type": "q", "data": 0x0180},
                                                             "Paired": {"type": "b", "data": True}, "Connected": {"type": "b", "data": True}}},
            "/org/bluez/hci0/dev_CC": {"org.bluez.Device1": {"Address": {"type": "s", "data": "AA:BB:CC:DD:EE:03"},
                                                             "Alias": {"type": "s", "data": "AA-BB-CC-DD-EE-03"}}}}]})
        real = boxos.run
        boxos.run = lambda cmd, timeout=20: (0, busctl) if cmd[0] == "busctl" else (1, "")
        try:
            found = {d["mac"]: d for d in boxos.bt_devices()}
        finally:
            boxos.run = real
        self.assertEqual(sorted(found), ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"])          # the nameless one left out
        self.assertEqual((found["AA:BB:CC:DD:EE:01"]["kind"], found["AA:BB:CC:DD:EE:01"]["rssi"]), ("controller", -48))
        self.assertEqual(found["AA:BB:CC:DD:EE:02"]["kind"], "remote")                      # it says it's a remote (LE appearance)
        self.assertTrue(found["AA:BB:CC:DD:EE:02"]["paired"] and found["AA:BB:CC:DD:EE:02"]["connected"])
        self.assertIsNone(boxos.bt_objects("Failed to connect to bus"))
        self.assertEqual(boxos.bt_kind({"Name": "Gadget", "Appearance": "0x03c1 (961)"}), "keyboard")   # as bluetoothctl prints it
        self.assertEqual(boxos.bt_kind({"Name": "Gadget"}), "other")

    def test_bluetooth_and_cloud_init_at_start(self):
        with open(os.path.join(BOX, "sofa-box")) as f:
            self.assertIn("rfkill unblock bluetooth", f.read())                                # switched on at every start
        with open(os.path.join(BOX, "install.sh")) as f:
            install = f.read()
        self.assertIn("cloud-final.service.d", install)                                         # cloud-init: the first start only
        self.assertIn("/etc/cloud/cloud-init.disabled", install)


class MovedApps(unittest.TestCase):
    """An app the store has since given a new address: a box that installed the old one gets the new one, once, and
    nothing else on it changes (Edge Music's TV layout needs ?client=sofabox)."""

    def test_an_old_edge_music_address_is_moved(self):
        boxos, conf = load("boxos"), tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, conf, True)
        new = "https://music.edgeventure.uk/?client=sofabox"
        self.assertEqual(boxos.store_entry("edge-music")["url"], new)                     # what a new box installs
        before = {"apps": [{"id": "edge-music", "name": "Edge Music", "kind": "web", "url": "https://music.edgeventure.uk",
                            "color": "#FF2E88", "ua": "", "icon_file": "edge-music.png"},
                           {"id": "kitchen", "name": "Kitchen radio", "kind": "web", "url": "https://music.edgeventure.uk"},
                           {"id": "lj-showroom", "name": "The LJ Collection", "kind": "web", "url": "https://theljcollection.com/showroom.php"}],
                  "order": ["edge-music", "sofa"], "hidden": ["games"]}
        with open(os.path.join(conf, "apps.json"), "w") as f:
            json.dump(before, f)
        apps = boxos.Apps(conf)
        self.assertEqual(apps.get("edge-music")["url"], new)
        with open(os.path.join(conf, "apps.json")) as f:
            saved = json.load(f)
        expected = json.loads(json.dumps(before))
        expected["apps"][0]["url"] = new                                                   # only that one address
        self.assertEqual(saved, expected)
        self.assertEqual(apps.get("kitchen")["url"], "https://music.edgeventure.uk")        # a site added by hand stays as it is

    def test_a_box_already_moved_or_changed_by_hand_is_left_alone(self):
        boxos = load("boxos")
        for url in ("https://music.edgeventure.uk/?client=sofabox", "https://music.edgeventure.uk/player.html"):
            data = {"apps": [{"id": "edge-music", "url": url}]}
            self.assertFalse(boxos.moved_apps(data))
            self.assertEqual(data["apps"][0]["url"], url)
        self.assertTrue(boxos.moved_apps({"apps": [{"id": "edge-music", "url": "https://music.edgeventure.uk/"}]}))
        self.assertFalse(boxos.moved_apps({"apps": ["not an app", {"url": "https://music.edgeventure.uk"}]}))


class AppIcons(unittest.TestCase):
    def test_how_wide_a_picture_is(self):
        boxos = load("boxos")
        png = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + (180).to_bytes(4, "big") + (180).to_bytes(4, "big") + b"\0" * 20
        ico = b"\0\0\1\0" + (2).to_bytes(2, "little") + bytes([16, 16]) + b"\0" * 14 + bytes([0, 0]) + b"\0" * 14   # 16 and 256
        jpg = b"\xff\xd8\xff\xe0" + (16).to_bytes(2, "big") + b"\0" * 14 + b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + \
            (152).to_bytes(2, "big") + (152).to_bytes(2, "big") + b"\0" * 12
        self.assertEqual(boxos.image_width(png), 180)
        self.assertEqual(boxos.image_width(ico), 256)
        self.assertEqual(boxos.image_width(jpg), 152)
        self.assertEqual(boxos.image_width(b'<?xml version="1.0"?><svg viewBox="0 0 24 24"></svg>'), 1024)
        self.assertEqual(boxos.image_width(b"<html>not a picture</html>"), 0)

    def test_the_sharpest_is_kept(self):
        """A site's labelled "180" icon can be 57 pixels: the box fetches the likeliest few and keeps the widest."""
        boxos, folder = load("boxos"), tempfile.mkdtemp()
        def png(w):
            return b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + w.to_bytes(4, "big") + w.to_bytes(4, "big") + b"\0" * 200
        files = {"/": (b'<html><head><link rel="apple-touch-icon" href="/touch.png"><link rel="icon" href="/fav.png" sizes="128x128"></head></html>', "text/html"),
                 "/touch.png": (png(57), "image/png"), "/fav.png": (png(128), "image/png"), "/apple-touch-icon.png": (png(57), "image/png")}

        class Site(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body, ctype = files.get(self.path, (b"", ""))
                self.send_response(200 if body else 404)
                self.send_header("Content-Type", ctype or "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            name = boxos.fetch_icon("http://127.0.0.1:%d/" % srv.server_address[1], folder, "demo", timeout=5)
            with open(os.path.join(folder, name), "rb") as f:
                self.assertEqual(boxos.image_width(f.read()), 128)
        finally:
            srv.shutdown()
            srv.server_close()
            shutil.rmtree(folder, ignore_errors=True)


class SofaShield(unittest.TestCase):
    def test_on_update_off(self):
        d = tempfile.mkdtemp()
        hosts, blocklist = os.path.join(d, "hosts"), os.path.join(d, "list")
        mine = "127.0.0.1 localhost\n192.168.1.20 imac\n"
        with open(hosts, "w") as f:
            f.write(mine)
        with open(blocklist, "w") as f:
            f.write("0.0.0.0 0.0.0.0\n0.0.0.0 localhost\n" + "".join("0.0.0.0 ads%d.example.com\n" % i for i in range(1200)))
        env = dict(os.environ, SOFA_BOX_HOSTS=hosts, SOFA_BOX_SHIELD_LIST="file://" + blocklist)
        for _ in range(2):                                        # on, then an update: one list, not two
            subprocess.run(["sh", os.path.join(BOX, "sofa-box"), "shield", "on"], env=env, check=True, stdout=subprocess.DEVNULL)
        text = read(hosts)
        self.assertTrue(text.startswith(mine))
        self.assertEqual(text.count("0.0.0.0 ads"), 1200)
        self.assertEqual(text.count("# >>> Sofa Shield"), 1)
        self.assertNotIn("0.0.0.0 localhost", text)
        subprocess.run(["sh", os.path.join(BOX, "sofa-box"), "shield", "off"], env=env, check=True, stdout=subprocess.DEVNULL)
        self.assertEqual(read(hosts), mine)
        shutil.rmtree(d)


@unittest.skipUnless(chrome(), "needs Chrome or Chromium")
class BoxBrowser(unittest.TestCase):
    """The box's one browser, steered by the agent over DevTools: apps are tabs; the Sofa bar's Home and Add to
    Home reach the agent."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        conf = os.path.join(cls.dir, "conf")
        os.makedirs(conf)
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": True}, f)
        cls.port, cls.devtools = free_port(), free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        run = os.path.join(cls.dir, "run")                     # the kiosk session's word: a 1080p TV, pages twice as big
        os.makedirs(run)
        with open(os.path.join(run, "sofa-box-display"), "w") as f:
            f.write("SCALE=2\n")
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1920,1080",
                                       "--remote-debugging-port=%d" % cls.devtools, "--user-data-dir=" + os.path.join(cls.dir, "profile"),
                                       cls.base + "/box/home"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cls.dir, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(cls.port),
                                              SOFA_BOX_DEVTOOLS=str(cls.devtools), XDG_RUNTIME_DIR=run, SOFA_BOX_UINPUT="0",
                                              SOFA_BOX_HOTSPOT="0", SOFA_BOX_REMOTE_PORT=str(free_port())))
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(300):
            try:
                if cls.apps()["devtools"]:
                    break
            except OSError:
                pass
            time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.agent.terminate()
        cls.chrome.terminate()
        cls.agent.wait(10)
        cls.chrome.wait(10)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def apps(cls):
        with cls.opener.open(cls.base + "/box/api/apps", timeout=20) as r:
            return json.loads(r.read())

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-Sofa-Box": "1"})
        with self.opener.open(req, timeout=30) as r:
            return json.loads(r.read())

    def page_value(self, url_part, expression):
        """A value from the page whose address has `url_part` in it."""
        boxos = load("boxos") if "boxos" not in globals() else globals()["boxos"]
        with self.opener.open("http://127.0.0.1:%d/json/list" % self.devtools, timeout=10) as r:
            tab = next(p for p in json.loads(r.read()) if p["type"] == "page" and url_part in p["url"])
        ws = boxos.WebSocket(tab["webSocketDebuggerUrl"])
        try:
            ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == 1:
                    return m["result"]["result"].get("value")
        finally:
            ws.close()

    def test_pages_fill_the_tv(self):
        """The window has the whole screen, and so does every page, at the TV's own size. (Drawing apps at half size
        with doubled pixels, SOFA_BOX_PAGE_SCALE=1, left YouTube in the top-left quarter of the TV on a real Pi:
        the doubling didn't take under cage. Chromium's own scale factor shrank the whole window there.)"""
        self.post("/box/api/open", {"url": self.base + "/box/games/neon-dodge/"})
        end, size = time.time() + 15, None
        while time.time() < end:
            try:
                size = self.page_value("/box/games/neon-dodge", "[innerWidth, devicePixelRatio]")
                if size == [1920, 1]:
                    break
            except (StopIteration, OSError):
                pass
            time.sleep(0.3)
        self.assertEqual(size, [1920, 1])
        self.assertEqual(self.page_value("/box/home", "[innerWidth, devicePixelRatio]"), [1920, 1])

    def bar_says(self, url_part, message):
        """What the Sofa bar sends from a tab (through its script world), as if a key or button did it."""
        boxos = load("boxos") if "boxos" not in globals() else globals()["boxos"]
        with self.opener.open("http://127.0.0.1:%d/json/list" % self.devtools, timeout=10) as r:
            tab = next(p for p in json.loads(r.read()) if url_part in p["url"])
        ws = boxos.WebSocket(tab["webSocketDebuggerUrl"])
        try:
            ws.send(json.dumps({"id": 1, "method": "Page.createIsolatedWorld", "params": {"frameId": tab["id"], "worldName": "sofabox"}}))
            ctx = None
            while ctx is None:
                m = json.loads(ws.recv())
                if m.get("id") == 1:
                    ctx = m["result"]["executionContextId"]
            ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
                "expression": "window.__sofaBox(%s)" % json.dumps(json.dumps(message)), "contextId": ctx}}))
            while json.loads(ws.recv()).get("id") != 2:
                pass
        finally:
            ws.close()

    def wait(self, check, seconds=25):                  # a cold Chromium on a busy machine can be slow
        end = time.time() + seconds
        while time.time() < end:
            d = self.apps()
            if check(d):
                return d
            time.sleep(0.2)
        self.fail("never: %s" % self.apps())

    def test_apps_as_tabs(self):
        self.assertTrue(self.apps()["devtools"], "the agent didn't reach the browser")
        game = self.base + "/box/games/pair-up/"
        self.assertTrue(self.post("/box/api/open", {"url": game})["target"])
        self.post("/box/api/open", {"id": "sofa"})
        d = self.wait(lambda d: len(d["running"]) == 2)
        self.assertEqual(sorted(r["app"] for r in d["running"]), ["browser", "sofa"])
        self.post("/box/api/open", {"id": "sofa"})                                        # again: its tab, not a second
        self.assertEqual(len(self.apps()["running"]), 2)
        self.wait(lambda d: any(r["app"] == "browser" and r["frozen"] for r in d["running"]))       # behind: frozen
        self.assertFalse(any(r["app"] == "sofa" and r["frozen"] for r in self.apps()["running"]))  # in front (and Sofa never)
        behind = next(r["target"] for r in self.apps()["running"] if r["app"] == "browser")
        self.post("/box/api/front", {"target": behind})                                    # Open now: back in front, running
        self.wait(lambda d: d["front"] == "browser" and not any(r["frozen"] for r in d["running"] if r["target"] == behind))
        self.assertEqual(len(self.apps()["running"]), 2)                                   # that tab, not a new one
        self.wait(lambda d: any("pair-up" in r["url"] for r in d["running"]))
        time.sleep(1)
        self.bar_says("/box/games/pair-up", {"a": "home"})
        self.wait(lambda d: d["front"] == "home")
        self.bar_says("/box/games/pair-up", {"a": "add", "url": game, "title": "Pair Up", "icon": ""})
        self.wait(lambda d: any(a["name"] == "Pair Up" and a["url"] == game for a in d["apps"]))
        self.bar_says("/box/games/pair-up", {"a": "close"})
        self.wait(lambda d: [r["app"] for r in d["running"]] == ["sofa"])

    def test_gloamwell_plays(self):
        """Gloamwell in the box's browser: its newer creatures, elite powers and a champion fight on a floor for a
        while with nothing thrown; XP rises in drops as it's won; a legend keeps its power through a save."""
        self.post("/box/api/open", {"url": self.base + "/box/games/gloamwell/#test"})
        js = lambda e: self.page_value("/box/games/gloamwell", e)
        end = time.time() + 25
        while time.time() < end:
            try:
                if js("typeof GW") == "object":
                    break
            except (StopIteration, OSError, KeyError):
                pass
            time.sleep(0.3)
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); GW.newGame(0); GW.goFloor(13); GW.P.hp = GW.P.mhp = 99999; 1")
        js("(() => { for (const t of [19, 20, 21, 23, 0]) { const m = GW.spawnMon(t, GW.P.x + 24, GW.P.y, true); if (m) m.awake = true; }"
           " const c = GW.spawnMon(1, GW.P.x - 24, GW.P.y, false); GW.makeChampion(c); c.awake = true; return 1; })()")
        time.sleep(4)
        state = json.loads(js("JSON.stringify({ errs, champ: !!GW.champM && GW.champM.champ, el: GW.champM ? GW.champM.elS : '', alive: GW.P.hp > 0, mode: GW.mode })"))
        self.assertEqual(state["errs"], [])
        self.assertTrue(state["alive"] and state["mode"] == 3, state)
        self.assertIn("\u0005", state["el"]) if state["champ"] else None          # (two powers, shown as one line)
        drops = js("GW.skillXP(0, 60); GW.xpDrop(4, 25); GW.XD.filter(e => e.on).map(e => e.sk + ':' + e.s).join(',')")
        self.assertIn("0:+60", drops)
        self.assertIn("4:+25", drops)
        kept = json.loads(js("(() => { const it = GW.genUnique(9, 6); GW.P.pack.push(it); GW.save(); const back = JSON.parse(JSON.stringify(it));"
                             " return JSON.stringify({ ok: GW.validItem(back), r: back.r, n: back.n, in: JSON.stringify(GW.readSlot(0).pack).indexOf('HEARTSEEKER BAND') >= 0 }); })()"))
        self.assertEqual(kept, {"ok": True, "r": 5, "n": "HEARTSEEKER BAND", "in": True})

    def test_ironmaw_plays(self):
        """Ironmaw in the box's browser: each of its nine levels starts and plays a moment with every weapon fired and
        everything awake, with nothing thrown, and walls take the marks; the Coldheart's shut core lets little through
        until it opens, and below half it calls its drones; the demo plays itself and keeps nothing."""
        self.post("/box/api/open", {"url": self.base + "/box/games/ironmaw/#test"})
        js = lambda e: self.page_value("/box/games/ironmaw", e)

        def ready():
            end = time.time() + 30
            while time.time() < end:
                try:
                    if js("typeof IM === 'object' && IM.state === 'title'"):
                        return
                except (StopIteration, OSError, KeyError):
                    pass
                time.sleep(0.3)
        ready()
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); 1")
        for k in range(9):
            js("IM.startLevel(%d, false); IM.P.owned = [1, 1, 1, 1, 1, 1, 1]; IM.P.ammo = { rivets: 200, shells: 50, cells: 300, slag: 40 };"
               " IM.P.hp = 1e6; for (const f of IM.foes) f.st = 'chase'; 1" % k)
            for w in range(7):
                js("IM.P.weapon = %d; IM.P.swap = 0; IM.P.next = -1; IM.P.cool = 0; IM.P.spin = 1; IM.fire(); IM.P.a += 0.7; 1" % w)
            time.sleep(0.5)
        state = json.loads(js("JSON.stringify({ errs, state: IM.state, marks: IM.marks.tex.length - 1, levels: IM.ORDER.length })"))
        self.assertEqual(state["errs"], [])
        self.assertEqual((state["state"], state["levels"]), ("play", 9))
        self.assertGreater(state["marks"], 0)
        boss = json.loads(js("(() => { IM.startLevel(8, false); IM.P.hp = 1e6; const b = IM.foes[0]; b.st = 'chase'; const h0 = b.hp; IM.damage(b, 100, IM.P.x, IM.P.y);"
                             " const shut = h0 - b.hp; b.open = 3; const h1 = b.hp; IM.damage(b, 100, IM.P.x, IM.P.y); const open = h1 - b.hp;"
                             " b.open = 3; IM.damage(b, b.hp - b.max * 0.45, IM.P.x, IM.P.y); b.call = 0; return JSON.stringify({ shut, open }); })()"))
        self.assertLess(boss["shut"], 20)                                 # (its core shut)
        self.assertEqual(boss["open"], 100)
        time.sleep(1.5)
        self.assertGreater(js("IM.foes.filter(f => f.k === 'drone').length"), 0)
        self.assertEqual(js("errs.length"), 0)
        js("localStorage.removeItem('ironmaw'); location.hash = '#demo-test'; location.reload(); 1")
        time.sleep(1)
        end = time.time() + 30
        while time.time() < end:
            try:
                if js("typeof IM === 'object' && IM.state === 'play'"):
                    break
            except (StopIteration, OSError, KeyError):
                pass
            time.sleep(0.3)
        x0 = json.loads(js("JSON.stringify([IM.P.x, IM.P.y])"))
        time.sleep(5)
        demo = json.loads(js("JSON.stringify({ state: IM.state, at: [IM.P.x, IM.P.y], kept: localStorage.getItem('ironmaw') })"))
        self.assertEqual(demo["state"], "play")
        self.assertGreater(abs(demo["at"][0] - x0[0]) + abs(demo["at"][1] - x0[1]), 0.5)   # it walks by itself
        self.assertIsNone(demo["kept"])                                  # and keeps nothing

    def test_ironmaw_arena(self):
        """Ironmaw's arena in the box's browser: every arena starts (a ring each, a fighter per start asked for), bots
        walk and fight until someone is fragged, two players get two views, the last shift sends its creatures, and
        leaving goes back to the menu, with nothing thrown."""
        self.post("/box/api/open", {"url": self.base + "/box/games/ironmaw/#test"})
        js = lambda e: self.page_value("/box/games/ironmaw", e)
        end = time.time() + 30
        while time.time() < end:
            try:
                if js("typeof IM === 'object' && IM.state === 'title'"):
                    break
            except (StopIteration, OSError, KeyError):
                pass
            time.sleep(0.3)
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); 1")
        start = ("(() => { Object.assign(IM.save().arena, %s); IM.joined.length = 0; IM.joined.push(...%s); IM.startArena();"
                 " return JSON.stringify({ map: IM.arena.A.id, mode: IM.arena.M.id, fighters: IM.fighters.length, ring: IM.lv.ring.length, views: IM.views.length }); })()")
        for k in range(6):
            got = json.loads(js(start % (json.dumps({"mode": k % 4, "map": k, "bots": 5, "skill": 1, "limit": 2, "time": 2}), "[1]")))
            self.assertEqual((got["fighters"], got["views"]), (6, 1), got)
            self.assertGreater(got["ring"], 0, got)
            time.sleep(0.6)
        js(start % (json.dumps({"mode": 0, "map": 0, "bots": 6, "skill": 2, "limit": 2, "time": 2}), "[1]"))
        x0 = json.loads(js("JSON.stringify(IM.fighters.map(F => [F.x, F.y]))"))
        end, frags = time.time() + 40, 0
        while time.time() < end and not frags:
            time.sleep(1)
            frags = js("IM.fighters.reduce((n, F) => n + F.frags, 0)")
        self.assertGreater(frags, 0)                                      # bots find each other and fight
        moved = json.loads(js("JSON.stringify(IM.fighters.map(F => [F.x, F.y]))"))
        self.assertGreaterEqual(sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1 for a, b in zip(x0[1:], moved[1:])), 4)
        two = json.loads(js(start % (json.dumps({"mode": 1, "map": 5, "bots": 4, "skill": 1, "limit": 2, "time": 2}), "[1, 2]")))
        self.assertEqual((two["views"], two["fighters"]), (2, 6))
        js(start % (json.dumps({"mode": 3, "map": 3, "bots": 2, "skill": 1, "limit": 2, "time": 2}), "[1]") + "; IM.arena.waveT = 0; 1")
        end, foes = time.time() + 10, 0
        while time.time() < end and not foes:
            time.sleep(0.5)
            foes = js("IM.foes.filter(f => !f.dead).length")
        self.assertGreater(foes, 0)                                       # the first wave comes
        js("IM.toTitle(); 1")                                            # (leaving, as the pause menu does)
        time.sleep(0.5)
        self.assertEqual(json.loads(js("JSON.stringify([IM.state, IM.arena, IM.views.length, errs])")), ["title", None, 0, []])

    def test_tidewing_plays(self):
        """Tidewing in the box's browser: every course's line is clear of its land, each new course starts and runs,
        a cup's four races end in standings and a trophy that wins a skimmer, a time trial races the ghost of a best
        lap, two players race on two views with the rivals, and the demo plays by itself and keeps nothing."""
        self.post("/box/api/open", {"url": self.base + "/box/games/tidewing/#test"})
        js = lambda e: self.page_value("/box/games/tidewing", e)

        def until(expr, secs=30):
            end = time.time() + secs
            while time.time() < end:
                try:
                    if js(expr):
                        return True
                except (StopIteration, OSError, KeyError):
                    pass
                time.sleep(0.3)
            return False
        self.assertTrue(until("typeof TW === 'object' && TW.state === 'attract' && TW.screen === 'title'"))
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); 1")
        self.assertEqual(json.loads(js("JSON.stringify([TW.COURSES.length, TW.CUPS.length, TW.CRAFT.length])")), [12, 3, 4])
        clear = json.loads(js("JSON.stringify(TW.COURSES.map((c, i) => TW.checkCourse(i)))"))
        self.assertEqual(clear, [[]] * 12)                               # the line, its gates, sparks and crests on the water
        for ci in range(6, 12):                                          # the six new waters: they start and the rivals race
            js("TW.race = 'single'; TW.startRace(%d); 1" % ci)
            time.sleep(0.4)
        js("TW.startRace(9); 1")
        self.assertTrue(until("TW.state === 'race'", 15))
        time.sleep(2)
        self.assertGreater(js("TW.racers.filter(r => r.ai && r.speed > 10).length"), 1)
        # a cup: four races (each ended at once), the player first in each: gold, and the Swift
        js("TW.startCup(0); 1")
        for race in range(4):
            self.assertTrue(until("TW.state === 'race' || TW.state === 'countdown' || TW.state === 'intro'", 10))
            js("TW.you.passed = 99; TW.you.u = 1e6; TW.finishNow(); 1")
            self.assertTrue(until("TW.screen === 'standings'", 10))
            if race < 3:
                js("TW.menu.button('a', 'press'); 1")
        final = json.loads(js("JSON.stringify({ cups: TW.save().cups, title: document.getElementById('standTitle').textContent, note: document.getElementById('standNote').textContent })"))
        self.assertEqual(final["cups"], {"tide": 1})
        self.assertIn("final standings", final["title"])
        self.assertIn("Swift", final["note"])
        # a time trial against a ghost: a lap's samples along the line, kept as the best; it's raced
        js("""(() => { const W = TW.buildCourse(TW.COURSES[0]), P = W.P, rec = [];
                for (let t = 0; t < 30; t += 0.1) { const i = Math.floor(t / 30 * P.n) % P.n; rec.push(Math.round(P.x[i] * 10), Math.round(P.z[i] * 10), 0); }
                TW.save().ghost.wren = TW.packGhost(rec, 30, 'swift'); TW.save().trial.wren = 30; TW.race = 'trial'; TW.startRace(0); return 1; })()""")
        self.assertTrue(until("TW.state === 'race'", 15))
        trial = json.loads(js("TW.you.passed = 1; JSON.stringify({ racers: TW.racers.length, ghost: !!TW.ghost, craft: TW.ghost && TW.ghost.c })"))
        self.assertEqual(trial, {"racers": 1, "ghost": True, "craft": "swift"})
        time.sleep(0.5)
        self.assertIsNotNone(json.loads(js("JSON.stringify(TW.ghostAt())")))   # out on the water with you
        # two players: a view each, the three rivals too
        js("TW.race = 'single'; TW.two = true; TW.startRace(9); 1")
        self.assertTrue(until("TW.state === 'race'", 15))
        two = json.loads(js("JSON.stringify({ players: TW.players.length, racers: TW.racers.length, views: document.querySelectorAll('#pvs .pv').length })"))
        self.assertEqual(two, {"players": 2, "racers": 5, "views": 2})
        time.sleep(1)
        js("TW.two = false; 1")
        self.assertEqual(js("errs.length"), 0)
        js("localStorage.removeItem('tidewing'); location.hash = '#demo-test'; location.reload(); 1")
        time.sleep(1)
        self.assertTrue(until("typeof TW === 'object' && TW.state === 'attract' && window.SofaStats.demo === true", 30))
        x0 = json.loads(js("JSON.stringify(TW.racers.map(r => r.x))"))
        time.sleep(3)
        demo = json.loads(js("JSON.stringify({ x: TW.racers.map(r => r.x), kept: localStorage.getItem('tidewing') })"))
        self.assertTrue(any(abs(a - b) > 1 for a, b in zip(x0, demo["x"])))   # they race by themselves
        self.assertIsNone(demo["kept"])                                  # and nothing is kept

    def test_neon_brawler_plays(self):
        """Neon Brawler in the box's browser: five stages, three fighters, eight kinds of foe, four bosses; a chain of
        blows ends in a launch, a grabbed foe is thrown, a riot's shield turns a jab but not a jump kick, a full meter's
        special hits what's ahead, a pipe is picked up and thrown; the first boss comes once, and beating it clears the
        stage and starts the next; two fight together; the demo fights by itself and keeps nothing."""
        self.post("/box/api/open", {"url": self.base + "/box/games/neon-brawler/#test"})
        js = lambda e: self.page_value("/box/games/neon-brawler", e)

        def until(expr, secs=30):
            end = time.time() + secs
            while time.time() < end:
                try:
                    if js(expr):
                        return True
                except (StopIteration, OSError, KeyError):
                    pass
                time.sleep(0.3)
            return False
        self.assertTrue(until("typeof NB === 'object' && NB.mode === 'title'"))
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); 1")
        self.assertEqual(json.loads(js("JSON.stringify([NB.STAGES.length, NB.FIGHTERS.length, Object.keys(NB.FOES).length, Object.keys(NB.BOSSES).length])")), [5, 3, 8, 4])
        for i in range(5):                                              # each stage starts, its foes drawn ready
            js("NB.menu.hide(); NB.start(%d, [%d]); 1" % (i, i % 3))
            time.sleep(0.4)
            need = json.loads(js("JSON.stringify([...new Set(NB.STAGES[%d].zones.flatMap(z => z.waves.flat().concat(z.boss ? [z.boss] : [])))].filter(k => !NB.BUILT[k]))" % i))
            self.assertEqual(need, [], i)
        js("NB.start(0, [0]); 1")
        self.assertTrue(until("NB.mode === 'play'", 10))
        # a chain: jab, jab, cross, then the finisher launches
        js("""(() => { const p = NB.P[0]; p.x = 200; p.y = 220; p.face = 1; window.f1 = NB.spawn('punk', 222, 220); f1.inside = true; f1.cd = 99; f1.hp = 60; window.acts = [];
               let n = 0; const iv = setInterval(() => { if (p.act === 'attack' && p.t > 0.08) p.queued = true; if (p.act === 'idle' && n < 4) { n++; NB.attack(p); } acts.push(f1.act); }, 30);
               setTimeout(() => clearInterval(iv), 2000); return 1; })()""")
        time.sleep(2.3)
        chain = json.loads(js("JSON.stringify({ hp: f1.hp, acts: [...new Set(acts)], combo: NB.P[0].combo })"))
        self.assertLessEqual(chain["hp"], 60 - 6 - 6 - 9 - 15 + 1)
        self.assertIn("fall", chain["acts"])
        self.assertGreaterEqual(chain["combo"], 4)
        throw = json.loads(js("""(() => { const p = NB.P[0]; p.act = 'idle'; p.x = 200; p.face = 1; const f = NB.spawn('punk', 214, 220); f.inside = true; f.cd = 99;
               const g = NB.grab(p, f); NB.throwFoe(p, f, 1); return JSON.stringify({ g, act: f.act, hp: f.hp, vx: f.vx }); })()"""))
        self.assertEqual((throw["g"], throw["act"]), (True, "fall"))
        self.assertLess(throw["hp"], 30)
        self.assertGreater(throw["vx"], 100)
        riot = json.loads(js("""(() => { const p = NB.P[0]; p.act = 'idle'; p.x = 200; p.face = 1; const r = NB.spawn('riot', 226, 220); r.inside = true; r.face = -1; r.cd = 99; r.act = 'idle';
               const h0 = r.hp; NB.hitFoe(p, r, 10, null, 0, { name: 'jab' }); const blocked = r.hp === h0; NB.hitFoe(p, r, 13, 'down', 1, { air: 1, name: 'jkick' });
               return JSON.stringify([blocked, r.hp < h0, !r.guard]); })()"""))
        self.assertEqual(riot, [True, True, True])
        js("""(() => { const p = NB.P[0]; p.act = 'idle'; p.x = 120; p.face = 1; p.meter = 1; p.full = true; window.ahead = [NB.spawn('punk', 160, 220), NB.spawn('slicer', 200, 222)];
               ahead.forEach(f => { f.inside = true; f.cd = 99; }); NB.doSpecial(p); return 1; })()""")
        time.sleep(0.9)
        special = json.loads(js("JSON.stringify({ meter: NB.P[0].meter, hurt: ahead.every(f => f.hp < f.max) })"))
        self.assertEqual(special, {"meter": 0, "hurt": True})
        js("(() => { const p = NB.P[0]; p.act = 'idle'; p.special = null; p.x = 240; p.y = 230; NB.drop(240, 230, 'pipe'); return 1; })()")
        time.sleep(0.8)
        self.assertEqual(json.loads(js("JSON.stringify([NB.pickUp(NB.P[0]), NB.P[0].weapon])")), [True, "pipe"])
        self.assertEqual(json.loads(js("NB.throwWeapon(NB.P[0]); JSON.stringify([NB.P[0].weapon, NB.SHOTS.length])")), [None, 1])
        # the first boss: once, and beating it clears the stage and the next one starts
        js("""(() => { NB.FO.forEach(f => { f.hp = 0; f.dead = true; f.deadT = 9; }); const z = NB.STAGES[0].zones; NB.zone = z.length - 1; NB.camX = z[z.length - 1].at - 1;
               NB.P[0].x = NB.camX + 100; return 1; })()""")
        self.assertTrue(until("NB.boss && NB.boss.kind === 'diesel'", 10))
        self.assertEqual(js("NB.FO.filter(f => f.K.boss).length"), 1)
        js("NB.kill(NB.P[0], NB.boss); NB.FO.forEach(f => { if (!f.K.boss) { f.hp = 0; f.dying = true; } }); 1")
        self.assertTrue(until("NB.mode === 'clear'", 10))
        self.assertTrue(until("NB.stage === 1 && NB.mode === 'play'", 15))
        self.assertEqual(js("NB.SAVE.reached"), 1)
        two = json.loads(js("NB.start(2, [1, 2]); JSON.stringify(NB.P.map(p => p.F.id))"))
        self.assertEqual(two, ["brick", "juno"])
        time.sleep(1)
        self.assertEqual(js("errs.length"), 0)
        js("localStorage.removeItem('neon-brawler'); location.hash = '#demo-test'; location.reload(); 1")
        time.sleep(1)
        self.assertTrue(until("typeof NB === 'object' && window.SofaStats.demo === true && NB.mode === 'play'", 30))
        s0 = js("NB.score[0]")
        self.assertTrue(until("NB.score[0] > %d" % s0, 40))              # it fights by itself
        self.assertIsNone(js("localStorage.getItem('neon-brawler')"))    # and keeps nothing

    def test_micro_drifters_plays(self):
        """Micro Drifters in the box's browser: twelve tracks in four settings, four cars, five cups. The bots get round
        every track (and over every gap); a held drift lets go as a boost; a wall keeps a car on the road; skid marks stay
        on the ground; a slow car drops into a canyon's gap and is put back on the road after it; a cup's points add up
        to a podium with the same rivals throughout, and winning it unlocks Bolt; a time trial keeps the best lap and its
        ghost; Knockout ends with a winner; a second player left off the screen catches up; the demo races by itself and
        keeps nothing."""
        self.post("/box/api/open", {"url": self.base + "/box/games/micro-drifters/#test"})
        js = lambda e: self.page_value("/box/games/micro-drifters", e)

        def until(expr, secs=30):
            end = time.time() + secs
            while time.time() < end:
                try:
                    if js(expr):
                        return True
                except (StopIteration, OSError, KeyError):
                    pass
                time.sleep(0.3)
            return False
        self.assertTrue(until("typeof MD === 'object' && MD.mode === 'title'"))
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); 1")
        sets = json.loads(js("JSON.stringify([MD.TRACKS.length, [...new Set(MD.TRACKS.map(t => t.set))].sort(), MD.CLASSES.length, MD.CUPS.length])"))
        self.assertEqual(sets, [12, ["city", "desert", "night", "snow"], 4, 5])
        # every track: the bots go round (two laps each) and clear every gap
        laps = json.loads(js("""JSON.stringify(MD.TRACKS.map(T => { MD.startRace({ kind: 'demo', track: T.id, laps: 2, tier: 0 }); MD.sim(170);
               return [T.id, MD.RACE.state, Math.min(...MD.cars.map(c => c.lap)), MD.cars.reduce((a, c) => a + (c.falls || 0), 0),
                       T.feats.some(f => f.k === 'ramp') ? Math.min(...MD.cars.map(c => c.jumps || 0)) : 1]; }))"""))
        for tid, state, low, falls, jumps in laps:
            self.assertEqual(state, "over", tid)
            self.assertGreaterEqual(low, 2, tid)
            self.assertLessEqual(falls, 2, tid)                          # (a shove into the water now and then)
            self.assertGreaterEqual(jumps, 1, tid)
        # a drift held through a bend lets go as a boost; its marks stay on the ground
        drift = json.loads(js("""(() => { MD.P = [{ pad: 0, ci: 1, col: '#e8463c' }]; MD.startRace({ kind: 'quick', track: 'harbour', laps: 3, tier: 1 }); MD.sim(3.2);
               const c = MD.cars.find(c => c.human), R = MD.TR; c.ctl = null; c.human = true;
               const i = R.at(9.4); c.si = i; c.x = R.x[i]; c.y = R.y[i]; c.a = Math.atan2(R.ty[i], R.tx[i]); c.vx = R.tx[i] * 170; c.vy = R.ty[i] * 170; MD.locate(c);
               const g = R.ground.getContext('2d'), before = g.getImageData(0, 0, R.T.w, R.T.h).data.reduce((a, v) => a + v, 0);
               c.ctl = { x: () => -0.9, held: b => b === 'a' || b === 'x', take: () => false, rumble() {} };
               MD.sim(0.4); const charged = c.drifting && c.charge; c.charge = 1.5; c.ctl.held = b => b === 'a'; MD.sim(1 / 60);
               const after = g.getImageData(0, 0, R.T.w, R.T.h).data.reduce((a, v) => a + v, 0);
               return JSON.stringify({ charged, boost: c.boost, marked: after < before }); })()"""))
        self.assertGreater(drift["charged"], 0.3)                         # it charges while held
        self.assertGreater(drift["boost"], 0.7)                           # (a second-level charge: 0.8 s of boost)
        self.assertTrue(drift["marked"])
        # a wall: driven straight at it, the car stays on its side
        wall = json.loads(js("""(() => { const c = MD.cars.find(c => c.human), R = MD.TR, i = R.at(10.5); c.ctl = { x: () => 0, held: b => b === 'a', take: () => false, rumble() {} };
               c.si = i; c.x = R.x[i]; c.y = R.y[i]; c.a = Math.atan2(R.ny[i], R.nx[i]); c.vx = R.nx[i] * 180; c.vy = R.ny[i] * 180; c.av = 0; MD.locate(c);
               MD.sim(1.2); return JSON.stringify([MD.clearOf(R, c.x, c.y) <= 0, c.fall]); })()"""))
        self.assertEqual(wall, [True, 0])
        # too slow for the canyon's gap: in it goes, and back on the road beyond it
        gap = json.loads(js("""(() => { MD.startRace({ kind: 'quick', track: 'canyon', laps: 3, tier: 1 }); MD.sim(3.2); const c = MD.cars.find(c => c.human), R = MD.TR, rp = R.ramps.find(r => r.gap);
               const i = (rp.i - 12 + R.N) % R.N; c.ctl = { x: () => 0, held: b => b === 'a', take: () => false, rumble() {} };
               c.si = i; c.x = R.x[i]; c.y = R.y[i]; c.a = Math.atan2(R.ty[i], R.tx[i]); c.vx = R.tx[i] * 40; c.vy = R.ty[i] * 40; MD.locate(c);
               MD.sim(3); return JSON.stringify([c.falls || 0, (c.si - rp.i + R.N) % R.N > 10 && (c.si - rp.i + R.N) % R.N < 200]); })()"""))
        self.assertEqual(gap, [1, True])
        # a cup of three: points, the same rivals throughout, a podium, Bolt unlocked
        cup = json.loads(js("""(() => { const cup = { id: 'city', name: 'CITY CUP', tracks: ['harbour', 'market', 'skyline'], i: 0, tier: 1, pts: {}, who: {} }; let rivals = null, same = true;
               for (const id of cup.tracks) { MD.startRace({ kind: 'cup', track: id, laps: 1, tier: 1, cup }); const r = MD.cars.filter(c => !c.human).map(c => c.name + c.ci).join();
                 if (rivals && r !== rivals) same = false; rivals = r; MD.cars.forEach(c => { if (c.human) { c.auto = 1; c.k = 1.3; } }); MD.sim(120); cup.i++; }
               cup.i = 2; MD.cupDone(cup); const st = MD.standings(cup);
               return JSON.stringify({ same, n: st.length, total: st.reduce((a, w) => a + w.pts, 0), top: st[0].human === true, bolt: MD.SAVE.unlocked.bolt, medal: MD.SAVE.cups.city.pro }); })()"""))
        self.assertEqual(cup, {"same": True, "n": 6, "total": 3 * 28, "top": True, "bolt": 1, "medal": 3})
        self.assertEqual(js("JSON.parse(localStorage.getItem('micro-drifters')).unlocked.bolt"), 1)
        # a time trial: the best lap kept, and its ghost
        trial = json.loads(js("""(() => { MD.P = [{ pad: 0, ci: 2, col: '#4ac860' }]; MD.startRace({ kind: 'trial', track: 'pines', laps: 99, tier: 1 }); MD.cars[0].auto = 1; MD.sim(70);
               const b = JSON.parse(localStorage.getItem('micro-drifters')).best.pines; return JSON.stringify([MD.cars.length, b.lap > 10 && b.lap < 40, b.ghost.length > 1000, !!MD.RACE.ghost]); })()"""))
        self.assertEqual(trial, [1, True, True, True])
        # Knockout: a round ends with one car left, and a point for it
        ko = json.loads(js("""(() => { MD.P = [{ pad: 0, ci: 0, col: '#3a7ae8' }]; MD.startRace({ kind: 'ko', track: 'dunes', tier: 1, target: 3 }); MD.cars.forEach(c => { if (c.human) c.auto = 1; });
               MD.sim(45); return JSON.stringify([MD.cars.length, MD.RACE.state, MD.cars.reduce((a, c) => a + c.pts, 0)]); })()"""))
        self.assertEqual(ko, [4, "round", 1])
        # two players: the one left off the screen is brought back behind the leader
        two = json.loads(js("""(() => { MD.P = [{ pad: 0, ci: 0, col: '#e8463c' }, { pad: 2, ci: 1, col: '#3a7ae8' }]; MD.startRace({ kind: 'quick', track: 'neon', laps: 3, tier: 1 });
               MD.cars.forEach(c => { if (c.human) c.auto = 1; }); MD.sim(10); const [a, b] = MD.cars.filter(c => c.human), R = MD.TR, lead = a.prog > b.prog ? a : b, lag = lead === a ? b : a;
               const i = (lead.si - (R.N / 3 | 0) + R.N) % R.N; lag.si = i; lag.x = R.x[i]; lag.y = R.y[i]; lag.vx = lag.vy = 0; MD.locate(lag); MD.sim(1);
               return JSON.stringify([Math.hypot(lag.x - lead.x, lag.y - lead.y) < 200, lag.msg]); })()"""))
        self.assertEqual(two, [True, "CATCH UP!"])
        self.assertEqual(js("JSON.stringify(errs)"), "[]")
        js("localStorage.removeItem('micro-drifters'); location.hash = '#demo-test'; location.reload(); 1")
        time.sleep(1)
        self.assertTrue(until("typeof MD === 'object' && window.SofaStats.demo === true && MD.mode === 'play' && MD.RACE.state === 'race'", 30))
        p0 = js("Math.max(...MD.cars.map(c => c.prog))")
        self.assertTrue(until("Math.max(...MD.cars.map(c => c.prog)) > %d + 60" % p0, 30))   # it races by itself
        self.assertIsNone(js("localStorage.getItem('micro-drifters')"))                       # and keeps nothing

    def test_shadow_heist_plays(self):
        """Shadow Heist in the box's browser: twelve heists in three buildings, each one possible (the prize, the loot and
        the way out all reachable, a pick for every lock); a guard spots a thief in the light ahead of it, chases and
        catches, but not one in the dark behind it; a noise brings a guard to look; smoke hides; a lamp switched off
        darkens its room and a guard puts it back on; a lock is picked with a pick; a jammer blinds a camera; the
        prize taken out the way in finishes the heist, with its stars, ranks and record kept; a second thief joins;
        the demo plays by itself and keeps nothing."""
        self.post("/box/api/open", {"url": self.base + "/box/games/shadow-heist/#test"})
        js = lambda e: self.page_value("/box/games/shadow-heist", e)

        def until(expr, secs=30):
            end = time.time() + secs
            while time.time() < end:
                try:
                    if js(expr):
                        return True
                except (StopIteration, OSError, KeyError):
                    pass
                time.sleep(0.3)
            return False
        self.assertTrue(until("typeof SH === 'object' && SH.mode === 'title'"))
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); 1")
        self.assertEqual(json.loads(js("JSON.stringify([SH.HEISTS.length, SH.BUILDINGS.length])")), [12, 3])
        plans = json.loads(js("""JSON.stringify(SH.HEISTS.map((H, i) => { const L = SH.layout(i), W = L.W, ok = c => ![1, 5, 6].includes(L.t[c]);
               const d = SH.bfs(L.t, W, L.Hh, (L.exit[1] - 1) * W + L.exit[0], ok), locks = [...L.t].filter(v => v === 4).length;
               return [d[L.prize.y * W + L.prize.x] > 0, L.loot.every(l => d[l.y * W + l.x] > 0), L.picks > locks, L.guards.length >= 2, L.lamps.length > 5]; }))"""))
        for i, p in enumerate(plans):
            self.assertEqual(p, [True] * 5, i)
        # every heist can be done: the demo's thief, nobody watching, takes the prize out
        done = json.loads(js("""JSON.stringify(SH.HEISTS.map((H, i) => { SH.startHeist(i, [{ pad: 0, bot: true }]); SH.GU.forEach(g => { g.x = -9999; g.y = -9999; });
               SH.L.cams.forEach(c => c.jam = 9999); SH.sim(300); return SH.mode; }))"""))
        self.assertEqual(done, ["done"] * 12)
        # in the light ahead: spotted, chased, caught; in the dark behind: not
        seen = json.loads(js("""(() => { const r = []; for (const [a, light] of [[0, 1], [Math.PI, 0.05]]) { SH.startHeist(0); const g = SH.GU[0], p = SH.PL[0]; SH.GU.slice(1).forEach(q => q.x = -9999);
                 g.wait = 99; g.look = a; const [gx, gy] = SH.tileOf(g.x, g.y); let k = 2; while (k < 4 && SH.L.t[gy * SH.L.W + gx + k + 1] === 0) k++;
                 p.x = (gx + k) * 16 + 8; p.y = gy * 16 + 8; SH.L.light.fill(light); SH.sim(2.5); r.push([g.state, p.caught, SH.STATS.seen]); } return JSON.stringify(r); })()"""))
        self.assertEqual(seen, [["alert", True, True], ["patrol", False, False]])
        # a noise: a guard comes to look; smoke between them hides the thief
        hear = json.loads(js("""(() => { SH.startHeist(4); const g = SH.GU[1]; g.wait = 0; SH.noise(g.x + 40, g.y, 6); const s1 = g.state;
               const p = SH.PL[0]; SH.useGadget(p); const smoked = SH.sightClear(SH.L, ...SH.tileOf(p.x, p.y), ...SH.tileOf(p.x + 48, p.y)) === false || SH.L.t[SH.tileOf(p.x + 48, p.y)[1] * SH.L.W + SH.tileOf(p.x + 48, p.y)[0]] !== 0;
               return JSON.stringify([s1, smoked, SH.INV.smoke]); })()"""))
        self.assertEqual(hear[0], "check")
        self.assertTrue(hear[1])
        # a lamp switched off: its room goes dark; a guard on its round puts it back on
        lamp = json.loads(js("""(() => { SH.startHeist(0); const L = SH.L, R = L.rooms.find(r => r.lamps.length && r.sw), lp = R.lamps[0], before = L.light[lp.y * L.W + lp.x];
               const p = SH.PL[0]; p.x = R.sw.x * 16 + 8; p.y = R.sw.y * 16 + 8; SH.interact(p, true, true, 1 / 60); SH.sim(1 / 60); const after = L.light[lp.y * L.W + lp.x];
               const g = SH.GU[0]; g.x = R.cells[0] % L.W * 16 + 8; g.y = (R.cells[0] / L.W | 0) * 16 + 8; g.state = 'patrol'; g.wait = 0; p.x = -9999;
               SH.sim(25); return JSON.stringify([before > after, R.lamps.some(l => l.on)]); })()"""))
        self.assertEqual(lamp, [True, True])
        # a lock: held A with a pick opens it, and the pick is spent
        pick = json.loads(js("""(() => { SH.startHeist(1); const L = SH.L, c = [...L.t].findIndex(v => v === 4), x = c % L.W, y = (c / L.W) | 0;
               const W = L.W; let from = null; for (const [dx, dy, a] of [[0, 1, -Math.PI / 2], [0, -1, Math.PI / 2], [1, 0, Math.PI], [-1, 0, 0]]) if (L.t[(y + dy) * W + x + dx] === 0) { from = [x + dx, y + dy, a]; break; }
               const p = SH.PL[0]; p.x = from[0] * 16 + 8; p.y = from[1] * 16 + 8; p.a = from[2]; const n0 = SH.INV.picks; SH.GU.forEach(g => g.x = -9999);
               p.ctl = { x: () => 0, y: () => 0, held: b => b === 'a', take: b => b === 'a', rumble() {} }; SH.sim(2); return JSON.stringify([L.t[c], n0 - SH.INV.picks]); })()"""))
        self.assertEqual(pick, [3, 1])
        jam = json.loads(js("""(() => { SH.startHeist(5); const c = SH.L.cams[0], p = SH.PL[0]; p.x = c.x * 16 + 8; p.y = c.y * 16 + 24; p.sel = 'jam'; SH.useGadget(p); return JSON.stringify([c.jam > 5]); })()"""))
        self.assertEqual(jam, [True])
        # the prize, out the way in: stars, ranks, the record and the next heist
        fin = json.loads(js("""(() => { SH.startHeist(0); const L = SH.L, p = SH.PL[0]; SH.GU.forEach(g => g.x = -9999); p.x = L.prize.x * 16 + 8; p.y = L.prize.y * 16 + 8;
               SH.interact(p, true, true, 1 / 60); p.x = L.exit[0] * 16 + 8; p.y = L.exit[1] * 16 + 4; SH.sim(0.1); const b = JSON.parse(localStorage.getItem('shadow-heist'));
               return JSON.stringify([SH.mode, SH.RESULT.stars >= 2, SH.RESULT.ghost, SH.RESULT.silent, b.best['0'].stars >= 2, b.reached]); })()"""))
        self.assertEqual(fin, ["done", True, True, True, True, 1])
        two = json.loads(js("SH.startHeist(2); SH.onButton('start', 'press', 2); JSON.stringify([SH.PL.length, SH.PL[1].pad])"))
        self.assertEqual(two, [2, 2])
        self.assertEqual(js("JSON.stringify(errs)"), "[]")
        js("localStorage.removeItem('shadow-heist'); location.hash = '#demo-test'; location.reload(); 1")
        time.sleep(1)
        self.assertTrue(until("typeof SH === 'object' && window.SofaStats.demo === true && SH.mode === 'play'", 30))
        x0 = js("SH.PL[0].x + SH.PL[0].y")
        self.assertTrue(until("Math.abs(SH.PL[0].x + SH.PL[0].y - %f) > 20" % x0, 20))       # it plays by itself
        self.assertIsNone(js("localStorage.getItem('shadow-heist')"))                         # and keeps nothing

    def test_rune_tactics_plays(self):
        """Rune Tactics in the box's browser: a campaign of fifteen battles on branching roads, five heroes, ten kinds
        of foe and three bosses, fields on six kinds of land. A battle on each land plays out to a winner; a shove into
        a pit kills; frost freezes water into ice; a heavy golem can't be blown back; fire spreads through forest;
        a fallen hero is revived; the Bog King's tongue pulls a hero in; a hold battle is won by lasting; a won battle
        levels heroes up, opens the next roads and is kept; a hero joins on the road; the controls choose, move and
        attack; the demo fights by itself and keeps nothing."""
        self.post("/box/api/open", {"url": self.base + "/box/games/rune-tactics/#test"})
        js = lambda e: self.page_value("/box/games/rune-tactics", e)

        def until(expr, secs=30):
            end = time.time() + secs
            while time.time() < end:
                try:
                    if js(expr):
                        return True
                except (StopIteration, OSError, KeyError):
                    pass
                time.sleep(0.3)
            return False
        self.assertTrue(until("typeof RT === 'object' && RT.mode === 'title'"))
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); 1")
        counts = json.loads(js("JSON.stringify([RT.NODES.length, Object.keys(RT.HEROES).length, RT.KINDS10.length, Object.values(RT.FOES).filter(f => f.boss).length, Object.keys(RT.THEMES).length])"))
        self.assertEqual(counts, [15, 5, 10, 3, 6])
        lands = json.loads(js("""JSON.stringify(Object.keys(RT.THEMES).map((th, k) => { RT.startBattle({ mode: 'demo', theme: th, seed: 100 + k, heroes: ['kael', 'lyra', 'orin', 'sefa', 'vesk'].map(id => ({ id, lvl: 4 })),
               foes: ['brute', 'wolf', 'wolf', 'archer', 'shaman', 'imp', 'golem', 'bomber', 'slime', 'wraith'], foeLvl: 2 }); RT.sim(400); return [RT.mode, RT.BT.winner != null]; }))"""))
        self.assertEqual(lands, [["result", True]] * 6)
        js("""window.flat = () => { const B = RT.BT; B.f.t.fill(0); B.f.h.fill(0); B.f.fire.fill(0); B.units.length = 0; }; window.put = (u, x, y) => { u.x = x; u.y = y; RT.BT.units.push(u); return u; };
              window.mk = () => RT.startBattle({ mode: 'skirmish', theme: 'meadow', seed: 5, heroes: [{ id: 'kael', lvl: 5 }], foes: ['goblin'] }); 1""")
        rules = json.loads(js("""(() => { const out = {};
               mk(); flat(); let B = RT.BT; let k = put(RT.heroUnit('kael', 2), 3, 4), g = put(RT.foeUnit('brute'), 4, 4); B.f.t[4 * 14 + 5] = 3; g.hp = 30; g.max = 30;
               RT.useSkill(k, 'bash', 4, 4); RT.sim(2); out.pit = g.dead;
               mk(); flat(); B = RT.BT; const v = put(RT.heroUnit('vesk', 4), 3, 4); g = put(RT.foeUnit('golem'), 5, 4); B.f.t[4 * 14 + 6] = 2;
               RT.useSkill(v, 'frost', 6, 4); RT.sim(1.5); out.ice = B.f.t[4 * 14 + 6]; RT.useSkill(v, 'gust', 5, 4); RT.sim(1.5); out.golem = g.x;
               mk(); flat(); B = RT.BT; for (let i = 0; i < 140; i++) B.f.t[i] = (i % 14) > 5 ? 1 : 0; const o = put(RT.heroUnit('orin', 3), 2, 4); put(RT.foeUnit('wolf'), 6, 4);
               RT.useSkill(o, 'firebolt', 6, 4); RT.sim(1.5); const lit = [...B.f.fire].filter(Boolean).length; for (let r = 0; r < 3; r++) RT.fireTick(); out.spread = [...B.f.fire].filter(Boolean).length > lit;
               mk(); flat(); B = RT.BT; const s = put(RT.heroUnit('sefa', 4), 2, 4); k = put(RT.heroUnit('kael', 4), 3, 4); k.dead = true; k.hp = 0; B.fallen.push(k);
               RT.useSkill(s, 'revive', 2, 5); RT.sim(1); out.revived = !k.dead && k.hp > 0;
               mk(); flat(); B = RT.BT; k = put(RT.heroUnit('kael', 5), 2, 4); const b = put(RT.foeUnit('bogking', 1, 3), 6, 4); B.boss = true; B.side = 1; B.ai = [false, true]; B.aiQ = [b]; b.done = false;
               RT.sim(3); out.pulled = k.x === 5;
               return JSON.stringify(out); })()"""))
        self.assertEqual(rules, {"pit": True, "ice": 5, "golem": 5, "spread": True, "revived": True, "pulled": True})
        # the controls: choose Kael, move him, attack the goblin beside him
        ctl = json.loads(js("""(() => { mk(); flat(); const B = RT.BT; const k = put(RT.heroUnit('kael', 5), 3, 4), g = put(RT.foeUnit('goblin'), 6, 4); B.ai = [false, true];
               let n = 0; const press = b => { RT.G.pressAt[0][b] = performance.now() + (n += 0.01); RT.sim(0.05); };   // (each press its own moment)
               RT.cur.x = 3; RT.cur.y = 4; press('a'); const moving = RT.ui; RT.cur.x = 5; press('a'); RT.sim(0.6); const acting = RT.ui; press('a'); const aiming = RT.ui; press('a'); RT.sim(1);
               return JSON.stringify([moving, acting, aiming, k.x, g.hp < g.max]); })()"""))
        self.assertEqual(ctl, ["move", "act", "target", 5, True])
        # the campaign: a won battle levels heroes, opens the roads beyond it, is kept; a hero joins at Reedwater
        js("RT.SAVE.camp = RT.newCamp(); RT.store.save(); RT.campBattle(0); 1")
        self.assertTrue(until("RT.mode === 'battle' && RT.BT && RT.BT.node === 0", 10))
        won = json.loads(js("""(() => { const B = RT.BT; B.units.filter(u => u.hero).forEach(u => u.gain = 40); for (const u of B.units) if (u.side === 1) { u.hp = 0; u.dead = true; } RT.sim(2);
               const c = JSON.parse(localStorage.getItem('rune-tactics')).camp; return JSON.stringify([RT.mode, c.done['0'], c.heroes.kael.lvl > 1, RT.NODES.filter(n => n.from.includes(0)).length, (RT.BT.levels || []).length > 0]); })()"""))
        self.assertEqual(won, ["result", 1, True, 2, True])
        js("RT.campBattle(2); 1")
        self.assertTrue(until("RT.mode === 'battle' && RT.BT && RT.BT.node === 2", 10))
        joined = json.loads(js("""(() => { for (const u of RT.BT.units) if (u.side === 1) { u.hp = 0; u.dead = true; } RT.sim(2); return JSON.stringify(JSON.parse(localStorage.getItem('rune-tactics')).camp.joined); })()"""))
        self.assertIn("sefa", joined)
        hold = json.loads(js("""(() => { RT.startBattle({ mode: 'skirmish', theme: 'meadow', seed: 9, heroes: [{ id: 'kael', lvl: 8 }], foes: ['goblin'], hold: 2 }); const B = RT.BT;
               for (const u of B.units) if (u.side === 1) { u.x = 13; u.y = 0; u.st.frozen = 9; } B.ai = [true, true]; RT.sim(30); return JSON.stringify([B.winner, B.round]); })()"""))
        self.assertEqual(hold[0], 0)
        self.assertEqual(js("JSON.stringify(errs)"), "[]")
        js("localStorage.removeItem('rune-tactics'); location.hash = '#demo-test'; location.reload(); 1")
        time.sleep(1)
        self.assertTrue(until("typeof RT === 'object' && window.SofaStats.demo === true && RT.mode === 'battle'", 30))
        self.assertTrue(until("RT.BT && RT.BT.round >= 2", 60))                                 # it fights by itself
        self.assertIsNone(js("localStorage.getItem('rune-tactics')"))                           # and keeps nothing

    def test_void_drifter_plays(self):
        """Void Drifter in the box's browser: four ships, six weapons, eight modules, four bosses, five events. A zone's
        map has five columns of sectors and the boss, every one reachable, a shop in each zone; a fight clears; an
        asteroid field ends; each boss can be beaten and the next zone opens; every weapon fires; a shield takes a hit
        before the hull; a trader fits a module; a shop sells a weapon; a second ship joins mid-run and brings a downed
        one back; beating the Dreadnought unlocks the Spectre and is kept; the demo flies by itself and keeps nothing."""
        self.post("/box/api/open", {"url": self.base + "/box/games/void-drifter/#test"})
        js = lambda e: self.page_value("/box/games/void-drifter", e)

        def until(expr, secs=30):
            end = time.time() + secs
            while time.time() < end:
                try:
                    if js(expr):
                        return True
                except (StopIteration, OSError, KeyError):
                    pass
                time.sleep(0.3)
            return False
        self.assertTrue(until("typeof VD === 'object' && VD.mode === 'title'"))
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); 1")
        self.assertEqual(json.loads(js("JSON.stringify([Object.keys(VD.SHIPS).length, Object.keys(VD.WEAPONS).length, Object.keys(VD.MODULES).length, VD.BOSSES.length, VD.EVENTS.length])")), [4, 6, 8, 4, 5])
        maps = json.loads(js("""JSON.stringify([0, 1, 2, 3].map(z => { const M = VD.zoneMap(z, 1234 + z); const reach = new Set([0, 1].map(i => '0,' + i));
               for (let c = 0; c < 5; c++) for (const s of M[c]) if (reach.has(c + ',' + s.i)) for (const j of s.next) reach.add((c + 1) + ',' + j);
               return [M.length, M[5][0].type, M.flat().every(s => reach.has(s.c + ',' + s.i)), M.flat().some(s => s.type === 'shop')]; }))"""))
        self.assertEqual(maps, [[6, "boss", True, True]] * 4)
        once = json.loads(js("""(() => { VD.start('vagrant', [{ pad: 0 }]); VD.openMap(); VD.RUN.map[0].forEach(s => s.type = 'fight'); VD.goNode(VD.nextNodes()[0]); VD.goNode(0); return JSON.stringify([VD.RUN.col, VD.mode]); })()"""))
        self.assertEqual(once, [0, "fading"])                          # (a sector chosen once, however often it's pressed while the screen fades)
        fight = json.loads(js("""(() => { VD.start('vagrant', [{ pad: 0, bot: true }]); VD.RUN.weapons = [{ id: 'missile', lvl: 3 }]; VD.PL[0].hull = VD.PL[0].max = 2000; VD.fly('fight'); VD.sim(360); const a = VD.mode;
               VD.start('vagrant', [{ pad: 0, bot: true }]); VD.fly('mine'); VD.sim(60); return JSON.stringify([a, VD.mode, VD.RUN.ore > 0]); })()"""))
        self.assertEqual(fight, ["fading", "fading", True])
        bosses = json.loads(js("""JSON.stringify([0, 1, 2, 3].map(z => { VD.start('vagrant', [{ pad: 0, bot: true }]); VD.RUN.zone = z; VD.RUN.weapons = [{ id: 'missile', lvl: 3 }];
               VD.PL[0].hull = VD.PL[0].max = 900; VD.fly('boss'); const name = VD.BOSS.D.name; VD.sim(300); return [name, VD.BOSS === null, VD.mode, VD.RUN.zone]; }))"""))
        for z, (name, dead, mode, zone) in enumerate(bosses):
            self.assertTrue(dead, name)
            self.assertEqual((mode, zone), ("over", 3) if z == 3 else ("fading", z + 1), name)
        guns = json.loads(js("""(() => { const out = {}; for (const id of Object.keys(VD.WEAPONS)) { VD.start('vagrant', [{ pad: 0 }]); VD.RUN.weapons = [{ id, lvl: 1 }]; VD.fly('fight');
               const p = VD.PL[0]; p.ctl = { x: () => 0, y: () => 0, held: b => b === 'a', take: () => false, pad: () => null, rumble() {} }; VD.sim(0.5); out[id] = VD.B.length > 0 || !!p.beam; } return JSON.stringify(out); })()"""))
        self.assertTrue(all(guns.values()), guns)
        mods = json.loads(js("""(() => { VD.start('vagrant', [{ pad: 0 }]); const max0 = VD.PL[0].max; VD.RUN.mods.push('armor', 'shield'); VD.fitStats(); const p = VD.PL[0]; p.shield = p.smax; p.inv = 0;
               const h = p.hull; VD.hurtPilot(p, 10); const a = [p.max > max0, p.hull === h, p.shield < p.smax];
               VD.RUN.ore = 200; VD.RUN.col = 0; VD.RUN.row = 0; VD.EVT = Object.assign({}, VD.EVENTS[2]); VD.eventChoice('trade'); a.push(VD.RUN.mods.length === 3, VD.RUN.ore === 110);
               VD.openShop(); const it = VD.SHOP.find(i => i.t === 'SPREAD GUN' || i.t === 'LASER' || i.t === 'MISSILES' || i.t === 'RAILGUN' || i.t === 'FLAK'); VD.RUN.ore = 500; it.buy(); a.push(VD.RUN.weapons.length === 2);
               return JSON.stringify(a); })()"""))
        self.assertEqual(mods, [True, True, True, True, True, True])
        two = json.loads(js("""(() => { VD.start('vagrant', [{ pad: 0 }]); VD.fly('mine'); VD.onButton('start', 'press', 2); const [a, b] = VD.PL; b.inv = 0; b.dashT = 0; VD.hurtPilot(b, 9999);
               const down = b.down; a.x = b.x + 10; a.y = b.y; a.vx = a.vy = 0; VD.RO.length = 0; a.ctl = { x: () => 0, y: () => 0, held: () => false, take: () => false, pad: () => null, rumble() {} }; b.ctl = a.ctl; VD.sim(2.5); return JSON.stringify([VD.PL.length, down, b.down]); })()"""))
        self.assertEqual(two, [2, True, False])
        won = json.loads(js("""(() => { VD.start('vagrant', [{ pad: 0 }]); VD.RUN.zone = 3; VD.RUN.won = true; VD.runOver(true); const s = JSON.parse(localStorage.getItem('void-drifter'));
               return JSON.stringify([s.ships.spectre, s.ships.wasp, s.ships.bulwark, s.wins]); })()"""))
        self.assertEqual(won, [1, 1, 1, 1])
        self.assertEqual(js("JSON.stringify(errs)"), "[]")
        js("localStorage.removeItem('void-drifter'); location.hash = '#demo-test'; location.reload(); 1")
        time.sleep(1)
        self.assertTrue(until("typeof VD === 'object' && window.SofaStats.demo === true && !!VD.RUN", 30))
        self.assertTrue(until("VD.RUN && (VD.RUN.col >= 0 || VD.RUN.kills > 0)", 60))        # it flies by itself (chooses its own way on the map)
        self.assertIsNone(js("localStorage.getItem('void-drifter')"))                          # and keeps nothing

    def test_cosmic_cascade_plays(self):
        """Cosmic Cascade in the box's browser: three of a colour in any line clear (across, down, slanting; a wild for
        any), a stone beside a match breaks, what falls into place clears again as a chain; all sixty puzzles can be
        solved with the gems they give (and start with nothing lined up), a solved one is kept, the hint finds a way;
        endless gets faster and ends, its best kept; in versus a big clear sends stones across, the sky falls in a
        long round, and a match against the computer is played to two wins; the board of the day is the same for
        everyone that day; the demo plays by itself and keeps nothing."""
        self.post("/box/api/open", {"url": self.base + "/box/games/cosmic-cascade/#test"})
        js = lambda e: self.page_value("/box/games/cosmic-cascade", e)

        def until(expr, secs=30):
            end = time.time() + secs
            while time.time() < end:
                try:
                    if js(expr):
                        return True
                except (StopIteration, OSError, KeyError):
                    pass
                time.sleep(0.3)
            return False
        self.assertTrue(until("typeof CC === 'object' && CC.mode === 'title'"))
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); 1")
        rules = json.loads(js("""(() => { const C = CC.COLS, R = CC.ROWS, at = (g, r, c, v) => g[r * C + c] = v, out = {};
               let g = new Uint8Array(C * R); at(g, 13, 0, 1); at(g, 13, 1, 1); out.across = CC.drop(g, 2, 1).cleared;
               g = new Uint8Array(C * R); at(g, 13, 0, 2); at(g, 12, 0, 2); out.down = CC.drop(g, 0, 2).cleared;
               g = new Uint8Array(C * R); at(g, 13, 0, 3); at(g, 13, 1, 4); at(g, 12, 1, 3); at(g, 13, 2, 4); at(g, 12, 2, 4); out.slant = CC.drop(g, 2, 3).cleared;
               g = new Uint8Array(C * R); at(g, 13, 0, 5); at(g, 13, 1, CC.WILD); out.wild = CC.drop(g, 2, 5).cleared;
               g = new Uint8Array(C * R); at(g, 13, 0, 6); at(g, 13, 1, 6); at(g, 12, 2, CC.STONE); at(g, 13, 2, 1); const r = CC.drop(g, 3, 6); out.stoneStays = g[12 * C + 2] === CC.STONE;
               g = new Uint8Array(C * R); at(g, 13, 0, 6); at(g, 13, 1, 6); at(g, 13, 3, CC.STONE); out.stone = CC.drop(g, 2, 6).stones;
               g = new Uint8Array(C * R); at(g, 13, 0, 1); at(g, 13, 1, 1); at(g, 13, 2, 3); at(g, 12, 2, 1); at(g, 13, 4, 3);
               out.chain = CC.drop(g, 3, 3).chains; return JSON.stringify(out); })()"""))
        self.assertEqual(rules, {"across": 3, "down": 3, "slant": 3, "wild": 3, "stoneStays": True, "stone": 1, "chain": 2})
        puzzles = json.loads(js("""JSON.stringify(CC.PUZZLES.map((p, i) => { const P = CC.decodePuzzle(i), g = P.g.slice(); const flat = !CC.findMatches(P.g) && CC.starsLeft(P.g) > 0;
               P.sol.forEach((c, k) => CC.drop(g, c, P.seq[k])); return flat && CC.starsLeft(g) === 0 && P.sol.length <= P.seq.length; }))"""))
        self.assertEqual((len(puzzles), all(puzzles)), (60, True))
        solved = json.loads(js("""(() => { CC.startGame({ kind: 'puzzle', puzzle: 4 }); const b = CC.B[0], P = CC.decodePuzzle(4); const h = CC.hint(b);
               for (const c of P.sol) { b.piece.c = c; CC.land(b); CC.sim(2); if (b.won) break; } CC.sim(0.2);
               return JSON.stringify([h != null, b.won, !!JSON.parse(localStorage.getItem('cosmic-cascade')).solved['4']]); })()"""))
        self.assertEqual(solved, [True, True, True])
        endless = json.loads(js("""(() => { CC.startGame({ kind: 'endless' }); const b = CC.B[0]; b.ctl = null; b.ai = { lvl: 2 }; CC.sim(120); const lv = b.level, sc = b.score;
               b.ai = null; b.ctl = { held: () => false, take: b => b === 'a', x: () => 0, y: () => 0 }; CC.sim(120);
               return JSON.stringify([lv > 1, sc > 0, b.over, JSON.parse(localStorage.getItem('cosmic-cascade')).endless.score === b.score]); })()"""))
        self.assertEqual(endless, [True, True, True, True])
        vs = json.loads(js("""(() => { CC.startGame({ kind: 'cpu', cpu: 1 }); const [a, b] = CC.B; const C = CC.COLS; a.g.fill(0); for (const c of [0, 1, 3, 4]) a.g[13 * C + c] = 1; a.piece.v = 1; a.piece.c = 2; const j0 = b.junk; CC.land(a); CC.sim(1.5); const sent = b.junk + 0 > j0 || b.g.includes(CC.STONE);
               a.ctl = null; a.ai = { lvl: 2 }; CC.GAME.rt = 89; CC.sim(7); const sky = CC.GAME.sky > 0;
               b.ai = { lvl: 0 }; let t = 0; while (t < 600 && CC.GAME.ended !== true) { CC.sim(5); t += 5; }
               return JSON.stringify([sent, sky, CC.GAME.ended, Math.max(a.wins, b.wins)]); })()"""))
        self.assertEqual(vs, [True, True, True, 2])
        daily = json.loads(js("""(() => { CC.startGame({ kind: 'daily' }); const a = CC.B[0].next.concat([CC.B[0].piece.v]).join(); CC.startGame({ kind: 'daily' }); const b = CC.B[0].next.concat([CC.B[0].piece.v]).join();
               CC.GAME.t = 179.9; CC.sim(0.5); return JSON.stringify([a === b, CC.B[0].over, CC.GAME.ended]); })()"""))
        self.assertEqual(daily, [True, True, True])
        self.assertEqual(js("JSON.stringify(errs)"), "[]")
        js("localStorage.removeItem('cosmic-cascade'); location.hash = '#demo-test'; location.reload(); 1")
        time.sleep(1)
        self.assertTrue(until("typeof CC === 'object' && window.SofaStats.demo === true && CC.mode === 'play'", 30))
        self.assertTrue(until("CC.B.length === 2 && CC.B[0].score + CC.B[1].score > 0", 40))      # two computers play
        self.assertIsNone(js("localStorage.getItem('cosmic-cascade')"))                          # and nothing's kept

    def test_gloamwell_finds(self):
        """Gloamwell's finds: a gem set in a socket gives its power and is kept through a save; a hidden vault's
        cracked wall breaks open; a familiar follows you down; floors with an omen (a gilded thief, the restless
        dead) play for a while with nothing thrown."""
        self.post("/box/api/open", {"url": self.base + "/box/games/gloamwell/#test"})
        js = lambda e: self.page_value("/box/games/gloamwell", e)
        end = time.time() + 25
        while time.time() < end:
            try:
                if js("typeof GW") == "object":
                    break
            except (StopIteration, OSError, KeyError):
                pass
            time.sleep(0.3)
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); GW.newGame(1); GW.P.hp = GW.P.mhp = 99999; 1")
        gem = json.loads(js("(() => { const P = GW.P, w = P.eq[0]; w.so = 2; w.gm = [-1, -1]; P.gems[11] = 1; GW.recalc(); const c0 = P.crit;"
                            " GW.setGem(w, 0, 11); GW.save(); const back = GW.readSlot(0).eq[0];"
                            " return JSON.stringify({ up: P.crit - c0, gm: back.gm, left: P.gems[11] }); })()"))
        self.assertEqual(gem, {"up": 7, "gm": [11, -1], "left": 0})              # (a radiant topaz in a weapon: +7% critical hits)
        vault = json.loads(js("(() => { if (!GW.vaultFloor(6)) return JSON.stringify({ found: false }); const was = GW.tile(GW.VLT.tx, GW.VLT.ty);"
                              " GW.breakVault(); return JSON.stringify({ found: true, was, now: GW.tile(GW.VLT.tx, GW.VLT.ty), open: GW.VLT.open }); })()"))
        self.assertEqual(vault, {"found": True, "was": 9, "now": 1, "open": True})
        js("(() => { GW.gainFam(2, true); GW.P.fam = 2; GW.recalc(); GW.goFloorOmen(9, 3); GW.P.hp = GW.P.mhp = 99999; return 1; })()")
        time.sleep(2.5)
        state = json.loads(js("JSON.stringify({ errs, omen: GW.omen, thief: GW.MON.some(m => m.on && m.t === 24),"
                              " near: Math.hypot(GW.FAM.x - GW.P.x, GW.FAM.y - GW.P.y) < 60, mode: GW.mode })"))
        self.assertEqual(state, {"errs": [], "omen": 3, "thief": True, "near": True, "mode": 3})
        js("GW.goFloorOmen(10, 4); 1")
        time.sleep(1.5)
        self.assertEqual(json.loads(js("JSON.stringify({ errs, omen: GW.omen })")), {"errs": [], "omen": 4})

    def gloamwell(self):
        """Gloamwell open in the box's browser, with its test handle, a fresh error list and nothing on the slots."""
        self.post("/box/api/open", {"url": self.base + "/box/games/gloamwell/#test"})
        js = lambda e: self.page_value("/box/games/gloamwell", e)
        end = time.time() + 25
        while time.time() < end:
            try:
                if js("typeof GW") == "object":
                    break
            except (StopIteration, OSError, KeyError):
                pass
            time.sleep(0.3)
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); for (let i = 0; i < 3; i++) localStorage.removeItem('gloamwell-slot-' + i); 1")
        return js

    def until(self, js, check, seconds=8):
        """Polls an expression in the page until it's true (or the time's up); its last value."""
        end, v = time.time() + seconds, None
        while time.time() < end:
            v = js(check)
            if v:
                return v
            time.sleep(0.2)
        return v

    def test_gloamwell_guardians(self):
        """Gloamwell's six guardians: each comes in with an entrance of its own when you walk into its room, its
        room's hazard starts, it grows desperate below half its HP, and below a quarter makes its last stand with a
        move kept for the end; nothing is thrown, and you're still standing."""
        js = self.gloamwell()
        js("GW.newGame(0); 1")
        for b in range(6):
            js("(() => { GW.goFloorOmen(%d, -1); const P = GW.P, A = GW.ARENA; P.hp = P.mhp = 99999; P.x = A.cx; P.y = A.y1 - 30; GW.computeFOV(); return 1; })()" % ((b + 1) * 4))
            self.assertTrue(self.until(js, "GW.ENTR.on", 5), "guardian %d: no entrance" % b)
            js("GW.endIntro(); GW.bossHP(0.4); 1")
            self.assertTrue(self.until(js, "GW.bossM.angry", 4), "guardian %d: never desperate" % b)
            js("GW.P.hp = GW.P.mhp; GW.bossHP(0.2); 1")
            self.until(js, "GW.bossM && GW.bossM.used3 > 0", 10)
            state = json.loads(js("JSON.stringify({ errs, b: GW.bossM.boss, ph3: GW.bossM.ph3, used: GW.bossM.used3 > 0, live: GW.ARENA.live, mode: GW.mode, up: GW.P.hp > 0 })"))
            self.assertEqual(state, {"errs": [], "b": b, "ph3": True, "used": True, "live": True, "mode": 3, "up": True})

    PADS = """(() => {          // two controllers the test holds: standard mapping, A 0, X 2, Start 9, down 13
      const mk = i => ({ id: "Xbox Wireless Controller (STANDARD GAMEPAD Vendor: 045e Product: 02fd)", index: i, connected: false, mapping: "standard",
        timestamp: 0, buttons: Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 })), axes: [0, 0, 0, 0] });
      const pads = window.__pads = [mk(0), mk(1)];
      navigator.getGamepads = () => pads.map(p => p.connected ? p : null);
      window.__btn = (i, b, on) => { const B = pads[i].buttons[b]; B.pressed = on; B.value = on ? 1 : 0; pads[i].connected = true; };
      window.__tap = (i, b) => { __btn(i, b, true); setTimeout(() => __btn(i, b, false), 120); };
      return 1; })()"""

    def test_gloamwell_two_players(self):
        """Two Wickbearers on one sofa: a second controller joins with a saved Wickbearer (Start, then A) and plays
        beside the first; a chest's loot is each one's own and a kill's XP is both's; the box's echo of the second's
        press isn't taken as the first's; a fallen one is brought back by the other holding A; both are saved; the
        second leaves from their own pause menu, and the foes go back to their strength for one."""
        js = self.gloamwell()
        tap = lambda pad, b: (js("__tap(%d, %d)" % (pad, b)), time.sleep(0.35))
        js("GW.newGame(1); GW.P.name = 'ODA'; GW.P.slot = 1; GW.save(); GW.newGame(0); GW.P.name = 'BRAN'; GW.save(); 1")
        js(self.PADS)
        tap(0, 0)                                                    # the first controller pressed: the first player's
        tap(1, 9)                                                    # Start on the second: who joins?
        self.assertEqual(json.loads(js("JSON.stringify({ mode: GW.mode, p1Pad: GW.p1Pad })")), {"mode": 20, "p1Pad": 0})
        tap(1, 0)                                                    # A: Oda, from the second save
        self.assertEqual(json.loads(js("JSON.stringify({ two: !!GW.PL[1], name: GW.PL[1] && GW.PL[1].name, pi: GW.PL[1] && GW.PL[1].pi, mode: GW.mode })")),
                         {"two": True, "name": "ODA", "pi": 1, "mode": 3})
        js("(() => { GW.goFloorOmen(5, -1); for (const Q of GW.PL) Q.hp = Q.mhp = 9999; GW.INT.forEach(i => i.off = true); return 1; })()")
        loot = json.loads(js("(() => { const A = GW.PL[0], g = [A.gold, GW.PL[1].gold]; A.fx = 1; A.fy = 0; A.face = 1;"
                             " const c = GW.spawnMon(7, A.x + 14, A.y, false); c.hp = c.mhp = 1; GW.use(0); return JSON.stringify(g); })()"))
        tap(0, 0)                                                    # the first breaks the chest open
        owners = json.loads(js("JSON.stringify([0, 1].map(w => GW.DR.some(d => d.on && d.pl === w) || GW.PL[w].gold > %d))" % max(loot)))
        self.assertEqual(owners, [True, True])                       # (a share each: on the ground in their colour, or picked up)
        js("(() => { const A = GW.PL[0]; for (let k = 0; k < 4; k++) { const m = GW.spawnMon(0, A.x + 12, A.y + (k & 1 ? 6 : -6), false); if (m) { m.awake = true; m.hp = m.mhp = 1; } } return 1; })()")
        js("__btn(0, 0, true); __btn(1, 0, true); 1")
        time.sleep(2.5)
        js("__btn(0, 0, false); __btn(1, 0, false); 1")
        xp = json.loads(js("JSON.stringify(GW.PL.map(Q => Q.xp + Q.lvl * 1000))"))
        self.assertTrue(xp[0] == xp[1] and xp[0] > 1000, xp)          # (both given the kills' XP)
        js("(() => { const A = GW.PL[0]; A.swing = 0; A.atkCD = 0; return 1; })()")
        js("__btn(1, 0, true); setTimeout(() => document.dispatchEvent(new KeyboardEvent('keydown', { code: 'Enter', key: 'Enter' })), 15);"
           " setTimeout(() => { document.dispatchEvent(new KeyboardEvent('keyup', { code: 'Enter', key: 'Enter' })); __btn(1, 0, false); }, 120); 1")
        time.sleep(0.6)
        self.assertEqual(js("GW.PL[0].swing > 0"), False)            # (the daemon's Enter for the second's A: dropped)
        # (a blow lands only off a hit's moment of grace, a dash and a lucky block: the fight just before may have left one on)
        js("(() => { const B = GW.PL[1]; B.inv = 0; B.dashT = 0; B.block = 0; GW.hurtP(1, 1e9); return 1; })()")
        self.assertEqual(json.loads(js("JSON.stringify({ down: GW.PL[1].dead, mode: GW.mode })")), {"down": True, "mode": 3})
        js("(() => { const A = GW.PL[0], B = GW.PL[1]; A.x = B.x + 8; A.y = B.y; return 1; })()")
        js("__btn(0, 0, true); 1")
        time.sleep(1.7)
        js("__btn(0, 0, false); 1")
        self.assertEqual(js("GW.PL[1].dead"), False)
        js("GW.goFloorOmen(6, -1); 1")
        self.assertEqual(json.loads(js("JSON.stringify([GW.readSlot(0).deepest, GW.readSlot(1).deepest, GW.readSlot(1).name])")), [6, 6, "ODA"])
        hp2 = js("GW.MON.filter(m => m.on && m.kind !== 6).reduce((s, m) => s + m.mhp, 0)")
        tap(1, 9)                                                    # the second's Start: their own pause menu
        self.assertEqual(json.loads(js("JSON.stringify({ mode: GW.mode, cur: GW.cur })")), {"mode": 4, "cur": 1})
        for _ in range(5):
            tap(1, 13)
        tap(1, 0)                                                    # LEAVE THE GAME
        state = json.loads(js("JSON.stringify({ errs, two: !!GW.PL[1], p1: GW.PL[0].name, mode: GW.mode })"))
        hp1 = js("GW.MON.filter(m => m.on && m.kind !== 6).reduce((s, m) => s + m.mhp, 0)")
        js("delete navigator.getGamepads; 1")
        self.assertEqual(state, {"errs": [], "two": False, "p1": "BRAN", "mode": 3})
        self.assertLess(hp1, hp2 * 0.7)                              # (the foes, back to their strength for one)
    def test_cinder_knight_plays(self):
        """Cinder Knight in the box's browser, on the 2D engine: the first stage of each region plays a while with every
        move and nothing thrown; a boss's bar shows only once you're in its room, its gates shut behind you and open
        when it falls, leaving its move; a shard and a stage's end are kept; the forge spends shards and embers; the
        demo plays itself, says so, and keeps nothing."""
        self.post("/box/api/open", {"url": self.base + "/box/games/cinder-knight/#test"})
        js = lambda e: self.page_value("/box/games/cinder-knight", e)

        def until(check, seconds=30):
            end = time.time() + seconds
            while time.time() < end:
                try:
                    if js(check):
                        return
                except (StopIteration, OSError, KeyError):
                    pass
                time.sleep(0.3)
            self.fail("never: " + check)
        until("typeof CK === 'object' && CK.mode === 'title'")
        js("window.errs = []; addEventListener('error', e => errs.push(String(e.message))); localStorage.removeItem('cinder-knight'); CK.newJourney(0); 1")
        for i in (0, 4, 8, 12):
            js("CK.loadStage(%d); CK.MV = { double: true, dash: true, climb: true, shield: true }; CK.setMode('play'); CK.KN.hp = 99; 1" % i)
            time.sleep(1.2)
        self.assertEqual(js("errs.length"), 0, js("JSON.stringify(errs)"))
        # Old Charhorn: no bar until you're in its room; the gates shut (stone, 10) and open (9) again; the dash is learned
        before = json.loads(js("(() => { CK.loadStage(3); CK.MV = CK.R.movesAt(3); CK.setMode('play'); const b = { on: CK.ST.bossOn, awake: CK.ST.boss.awake };"
                               " CK.KN.x = CK.ST.arena.x0 + 6 * 16; CK.KN.y = CK.ST.arena.floor; return JSON.stringify(b); })()"))
        self.assertEqual(before, {"on": False, "awake": False})
        time.sleep(1.5)
        room = json.loads(js("JSON.stringify({ on: CK.ST.bossOn, awake: CK.ST.boss.awake, gate: CK.ST.map.at(CK.ST.gates[0].x, CK.ST.gates[0].y), dash: CK.MV.dash })"))
        self.assertEqual(room, {"on": True, "awake": True, "gate": 10, "dash": False})
        js("CK.KN.hp = 99; CK.hitBoss(CK.ST.boss, 999); 1")
        time.sleep(1.8)
        down = json.loads(js("JSON.stringify({ on: CK.ST.bossOn, done: CK.ST.bossDone, gate: CK.ST.map.at(CK.ST.gates[0].x, CK.ST.gates[0].y), dash: CK.MV.dash,"
                             " kept: !!JSON.parse(localStorage.getItem('cinder-knight')).slots[0].learned.dash })"))
        self.assertEqual(down, {"on": False, "done": True, "gate": 9, "dash": True, "kept": True})
        # a shard, then the way out: kept on the box
        js("(() => { CK.loadStage(0); CK.setMode('play'); const it = CK.ST.items.find(i => i.k === 'shard'); CK.KN.x = it.x; CK.KN.y = it.y + 8; return 1; })()")
        time.sleep(0.6)
        self.assertGreater(js("JSON.parse(localStorage.getItem('cinder-knight')).slots[0].shards[0]"), 0)
        js("CK.KN.x = CK.ST.exit.x; CK.KN.y = CK.ST.exit.y; 1")
        time.sleep(1.5)
        clear = json.loads(js("(() => { const s = JSON.parse(localStorage.getItem('cinder-knight')).slots[0]; return JSON.stringify({ mode: CK.mode, best: s.best['1-1'] > 0, reached: s.reached }); })()"))
        self.assertEqual(clear, {"mode": "tally", "best": True, "reached": 1})
        forge = json.loads(js("(() => { CK.slot.embers = 100; CK.slot.shards[1] = 7; CK.buy(CK.FORGE[0]); return JSON.stringify({ blade: CK.slot.forge.blade, embers: CK.slot.embers, spent: CK.slot.spent }); })()"))
        self.assertEqual(forge, {"blade": 1, "embers": 40, "spent": 3})
        self.assertEqual(js("errs.length"), 0, js("JSON.stringify(errs)"))
        # the demo: it plays by itself, says so, and keeps nothing
        js("localStorage.removeItem('cinder-knight'); location.hash = '#demo-test'; location.reload(); 1")
        time.sleep(1)
        until("typeof CK === 'object' && CK.mode === 'play' && SofaStats.demo === true")
        x0 = js("CK.KN.x")
        time.sleep(5)
        demo = json.loads(js("JSON.stringify({ mode: CK.mode, moved: CK.KN.x - %f, kept: localStorage.getItem('cinder-knight'), tier: SofaStats.tier })" % x0))
        self.assertEqual(demo["mode"], "play")
        self.assertGreater(demo["moved"], 48)                             # it runs on by itself,
        self.assertIsNone(demo["kept"])                                   # keeps nothing,
        self.assertTrue(demo["tier"].startswith("2D "), demo["tier"])     # and says how it's drawn


class BoxNetwork(unittest.TestCase):
    """When the box makes its own Wi-Fi: soon for a new box; a box that knows a Wi-Fi waits for it (a router
    restarting) and, on its own Wi-Fi with nobody using it, goes back to look for it."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        old = {k: os.environ.get(k) for k in ("SOFA_BOX_CONF", "SOFA_BOX_DEVTOOLS", "SOFA_BOX_CAPTIVE_PORT")}
        os.environ.update(SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0")   # not port 80 here
        try:
            cls.agent = load("sofa-box-agent")
        finally:
            for k, v in old.items():
                os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def setUp(self):
        a = self.agent
        self.saved_wifi, self.address, self.started, self.stopped = ["Home"], None, [], []
        self.real = a.local_address, a.run
        a.local_address = lambda: self.address
        a.run = lambda cmd, timeout=20: (0, "\n".join("%s:802-11-wireless" % n for n in self.saved_wifi + ["sofa-box-setup"])
                                         + "\nWired connection 1:802-3-ethernet")
        self.net = a.Network()
        self.net.start_hotspot = lambda: (self.started.append(1), setattr(self.net, "hotspot", {"at": self.now}))
        self.net.stop_hotspot = lambda: (self.stopped.append(1), setattr(self.net, "hotspot", None))
        self.net.wired = lambda: False

    def tearDown(self):
        self.agent.local_address, self.agent.run = self.real
        self.agent.save_settings(welcomed=False)

    def run_for(self, seconds, since=0):
        for self.now in range(since, since + seconds + 1, 10):
            self.offline = self.net.tick(self.offline, self.now)

    def test_the_networks_it_knows(self):
        self.assertEqual(self.net.saved(), ["Home"])                 # not its own hotspot, not the cable

    def test_its_own_wifi_keeps_its_name_and_password(self):
        """So a phone that dropped off it (the box tried a home Wi-Fi that didn't work) joins it again by itself."""
        path = os.path.join(self.conf, "hotspot.json")
        if os.path.exists(path):
            os.remove(path)
        first = self.net.credentials("wlan0")
        self.assertRegex(first[1], r"^\d{8}$")
        self.assertEqual(self.net.credentials("wlan0"), first)
        self.assertEqual(self.agent.Network().credentials("wlan0"), first)            # after a restart too
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_joining_the_home_wifi(self):
        """Off its own Wi-Fi it looks for the home Wi-Fi first (a hotspot can't look around) and joins on its Wi-Fi chip;
        if that doesn't work, its own Wi-Fi comes back and the TV is told why."""
        a, calls, self.now = self.agent, [], 0
        answers = {"connect": (10, "Error: No network with SSID 'Home' found.")}

        def nmcli(cmd, timeout=20):
            calls.append(cmd)
            if cmd[-1] == "device":                                                   # nmcli -t -f DEVICE,TYPE device
                return 0, "eth0:ethernet\nwlan0:wifi"
            if cmd[:4] == ["nmcli", "-t", "-f", "SSID"]:
                return 0, "Neighbours\nHome"
            return answers["connect"] if "connect" in cmd else (0, "")
        a.run = nmcli
        woke, real_wake = [], a.secure_remote.wake
        a.secure_remote.wake = lambda: woke.append(1)
        try:
            self.net.hotspot = {"at": 0}
            r = self.net.join("Home", "pw")
            self.assertFalse(r["ok"])
            self.assertIn("can't see Home", r["message"])
            self.assertEqual((self.net.joining["state"], self.net.joining["message"]), ("failed", r["message"]))
            self.assertEqual(len(self.started), 1)                                    # its own Wi-Fi is back
            connect = next(i for i, c in enumerate(calls) if "connect" in c)
            self.assertLess(next(i for i, c in enumerate(calls) if "rescan" in c), connect)
            self.assertEqual(calls[connect][-2:], ["ifname", "wlan0"])
            answers["connect"] = (4, "Error: Connection activation failed: Secrets were required, but not provided.")
            self.assertIn("password for Home isn't right", self.net.join("Home", "nope")["message"])
            answers["connect"] = (0, "Device 'wlan0' successfully activated")
            self.net.hotspot = {"at": 0}
            self.assertTrue(self.net.join("Home", "pw")["ok"])
            self.assertEqual(self.net.joining["state"], "joined")
            self.assertEqual(woke, [1])                                              # its https remote, straight away
        finally:
            a.secure_remote.wake = real_wake

    def test_joining_answers_the_phone_first(self):
        """The phone may be on the box's own Wi-Fi, which the box is about to leave: it gets its answer before that."""
        joined = []
        self.net.join = lambda ssid, password: joined.append((ssid, password))
        r = self.net.join_soon("Home", "pw")
        self.assertTrue(r["ok"] and r["pending"])
        self.assertEqual(self.net.joining["state"], "joining")
        self.assertEqual(joined, [])
        time.sleep(2)
        self.assertEqual(joined, [("Home", "pw")])
        self.assertFalse(self.net.join_soon("", "pw")["ok"])
        self.assertFalse(self.net.join_soon("Other", "pw")["ok"])                  # one join at a time (still "joining")

    def test_the_boot_screen_waits_for_a_settled_box(self):
        """The rebuild (a minute of a Pi 3's whole processor) used to start within five seconds of Finish, as Home,
        the apps and Sofa loaded: the moment a box restarted by itself. Now: three minutes after the setup (or a
        start), half a minute after the last change, nothing playing, the processor not busy (or busy for ages)."""
        a = self.agent
        real = a.settings, a.playing, a.BootScreen.calm, a.STARTED
        try:
            now = 1_000_000.0
            a.STARTED = now - 3600
            a.settings = lambda: dict(a.DEFAULTS, welcomed=True)
            a.playing = lambda: False
            calm = [True]
            a.BootScreen.calm = staticmethod(lambda: calm[0])
            b = a.BootScreen()
            b.at = now - 120                                                        # the theme picked two minutes ago
            b.welcomed_at = now - 5                                                 # Finish, five seconds ago
            self.assertFalse(b.due(now))
            self.assertFalse(b.due(now + 170))
            self.assertTrue(b.due(now + 180))                                       # three minutes after the setup
            calm[0] = False
            self.assertFalse(b.due(now + 180))                                      # the processor busy: later
            self.assertTrue(b.due(now + 180 + b.BUSY_FOR))                          # (but not never)
            calm[0] = True
            a.playing = lambda: True
            self.assertFalse(b.due(now + 400))                                      # a video on
            a.playing = lambda: False
            b.at = now + 390
            self.assertFalse(b.due(now + 400))                                      # just changed again
            a.settings = lambda: dict(a.DEFAULTS, welcomed=False)
            self.assertFalse(b.due(now + 4000))                                     # the setup not done
            a.settings = lambda: dict(a.DEFAULTS, welcomed=True)
            b2 = a.BootScreen()
            a.STARTED = now
            self.assertFalse(b2.due(now + 60))                                      # a box that just started
            self.assertTrue(b2.due(now + 180))
        finally:
            a.settings, a.playing, a.BootScreen.calm, a.STARTED = real
        script = read(os.path.join(BOX, "sofa-box"))
        self.assertIn('apply-boot) in_the_background "$@"', script)               # its own service, lowest priority
        self.assertIn("one_core update-initramfs -u", script)

    def test_typed_codes_cant_be_worked_through(self):
        """Four digits are 10,000 tries for a laptop on the home Wi-Fi. After ten wrong ones in ten minutes typing rests
        (even the right code), the code changes, and the QR code's long link goes on working."""
        a = self.agent
        folder = tempfile.mkdtemp()
        try:
            p = a.PhoneRemote()
            p.path = os.path.join(folder, "phones.json")
            right = p.code
            wrong = [c for c in ("%04d" % n for n in range(10000)) if c != right][:10]
            for c in wrong[:9]:
                self.assertIsNone(p.pair(c, "Laptop"))
            self.assertFalse(p.resting())
            self.assertIsNone(p.pair(wrong[9], "Laptop"))
            self.assertTrue(p.resting())
            self.assertIsNone(p.pair(p.code, "Laptop"))                            # resting: not even the right one
            self.assertIn(p.link, p.status()["pair_url"] or "/r/" + p.link)        # the QR code: the long link
            self.assertTrue(p.pair(p.link, "Phone"))                                # which still pairs
            p.misses = [t - p.MISS_WINDOW for t in p.misses]                        # ten minutes on
            self.assertFalse(p.resting())
            self.assertTrue(p.pair(p.code, "Phone"))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_phones_on_its_own_wifi(self):
        """The setup shows the next code once a phone has joined the box's Wi-Fi: counted from the neighbour table."""
        a = self.agent
        a.run = lambda cmd, timeout=20: (0, "10.42.0.12 dev wlan0 lladdr 6a:1c:22:aa:01:02 REACHABLE\n"
                                            "10.42.0.31 dev wlan0 lladdr 6a:1c:22:aa:01:03 STALE\n"
                                            "10.42.0.40 dev wlan0  FAILED\n10.42.0.1 dev wlan0 lladdr b8:27:eb:00:00:01 PERMANENT\n")
        self.assertEqual(self.net.clients(), 0)                      # no Wi-Fi of its own: nobody on it
        self.net.hotspot = {"at": 0}
        self.assertEqual(self.net.clients(), 2)                      # not the one that failed, not the box itself

    def test_its_own_wifi_stays_off_while_joining(self):
        """The setup loop on a real box: its own Wi-Fi had been on for minutes (so it had been "offline" that long);
        joining the home Wi-Fi switches it off, and the 10-second look found the box offline with no Wi-Fi of its
        own and brought it back, mid-join, every time. It waits for the join now."""
        self.saved_wifi, self.offline = [], 0                        # a new box: no Wi-Fi of its own saved yet
        self.run_for(20)                                             # a new box: its own Wi-Fi after 15 seconds
        self.assertEqual(len(self.started), 1)
        self.run_for(300, 30)                                        # minutes on it, the phone setting it up
        self.net.joining = {"ssid": "Home", "state": "joining", "at": time.time()}
        self.net.hotspot = None                                      # the join switched it off
        self.run_for(90, 340)                                        # looking for Home, then joining: a minute and a half
        self.assertEqual(len(self.started), 1)                       # left alone
        self.net.joining = {"ssid": "Home", "state": "failed", "at": time.time()}
        self.run_for(0, 440)                                         # it didn't work (and the join didn't bring it back)
        self.assertEqual(len(self.started), 1)
        self.run_for(10, 450)                                        # within 15 seconds of the join: its own Wi-Fi again
        self.assertEqual(len(self.started), 2)
        with self.net.lock:                                          # and never while a join holds the Wi-Fi
            self.net.hotspot, self.net.joining = None, None
            self.run_for(60, 500)
            self.assertEqual(len(self.started), 2)

    def test_a_new_box_makes_its_own_wifi_soon(self):
        self.saved_wifi, self.offline = [], 0
        self.run_for(20)
        self.assertEqual(len(self.started), 1)

    def test_a_set_up_box_waits_for_its_wifi(self):
        self.agent.save_settings(welcomed=True)
        self.offline = 0
        self.run_for(170)                                            # the router restarting: no hotspot
        self.assertEqual(self.started, [])
        self.address = "192.168.1.30"                                # back
        self.run_for(10, 170)
        self.assertIsNone(self.offline)
        self.address = None
        self.run_for(200, 200)                                       # gone for good (moved house): its own Wi-Fi
        self.assertEqual(len(self.started), 1)
        self.net.used = self.now + 300                               # a phone on it: it stays
        self.run_for(600, self.now)
        self.assertEqual(self.stopped, [])
        self.run_for(400, self.now)                                  # quiet: it goes, to look for the home Wi-Fi
        self.assertEqual(len(self.stopped), 1)

    def test_a_set_up_box_with_no_wifi_saved(self):
        self.agent.save_settings(welcomed=True)
        self.saved_wifi, self.offline = [], 0
        self.run_for(60)
        self.assertEqual(len(self.started), 1)
        self.run_for(1200, self.now)                                 # nothing to go back to: it stays
        self.assertEqual(self.stopped, [])

    def test_its_own_wifi_switches_wifi_on_and_says_why_not(self):
        a, calls = self.agent, []
        answers = {"hotspot": (10, "Error: Connection activation failed: Wi-Fi is disabled")}

        def nmcli(cmd, timeout=20):
            calls.append(cmd)
            if cmd[-1] == "device":                                                   # nmcli -t -f DEVICE,TYPE device
                return 0, "wlan0:wifi\neth0:ethernet"
            # (its one start, and the old way it falls back on: tests/test_box_handoff.py)
            return answers["hotspot"] if "hotspot" in cmd or cmd[1:3] == ["connection", "up"] else (0, "")
        a.run = nmcli
        net, real_sleep = a.Network(), a.time.sleep
        a.time.sleep = lambda s: None
        try:
            self.assertIsNone(net.start_hotspot())
            self.assertIn(["nmcli", "radio", "wifi", "on"], calls)                   # Raspberry Pi OS starts with it off
            self.assertLess(calls.index(["nmcli", "radio", "wifi", "on"]), next(i for i, c in enumerate(calls) if "hotspot" in c))
            self.assertIn("Wi-Fi is disabled", net.problem)                         # said on the TV, not a spinner for ever
            tried = len([c for c in calls if "show" not in c])
            net.tick(0, net.failed_at + 20)                                          # not again straight away
            self.assertEqual(len([c for c in calls if "show" not in c]), tried)     # (only the saved Wi-Fi looked at)
            answers["hotspot"] = (0, "Device 'wlan0' successfully activated")
            net.tick(0, net.failed_at + 50)
            self.assertTrue(net.hotspot and net.problem is None)
            made = [c for c in calls if c[1:3] == ["connection", "add"]][-1]
            self.assertEqual([made[made.index(k) + 1] for k in ("802-11-wireless-security.pmf", "ipv6.method")], ["disable", "disabled"])
            self.assertIsNotNone(a.captive.server)                                    # its sign-in page, with it
            net.stop_hotspot()
            self.assertIsNone(a.captive.server)
        finally:
            a.time.sleep = real_sleep
            a.captive.stop()

    def test_its_own_wifi_opens_the_remote_by_itself(self):
        """A phone joining the box's own Wi-Fi gets a sign-in page (captive portal) that opens the remote, paired."""
        a = self.agent
        real = a.on_own_wifi, a.network.hotspot, a.phone
        servers = []

        def serve(handler):
            srv = a.Server(("127.0.0.1", 0), handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            servers.append(srv)
            return "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            a.on_own_wifi = lambda ip: True                                          # as if from 10.42.0.x
            a.network.hotspot = {"ssid": "Sofa Box 1234", "address": "10.42.0.1"}
            a.phone = a.PhoneRemote()
            portal, remote = serve(a.CaptiveHandler), serve(a.RemoteHandler)
            with urllib.request.urlopen(portal + "/hotspot-detect.html", timeout=10) as r:      # what an iPhone asks first
                page = r.read().decode()
            self.assertNotIn("Success", page)                                        # so it opens its sign-in sheet
            self.assertIn('url=http://10.42.0.1:8092/join"', page)
            code = a.phone.code
            opener = urllib.request.build_opener(NoRedirect)
            try:
                opener.open(remote + "/join", timeout=10)
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 302)
                self.assertIn("sofa_remote=", e.headers.get("Set-Cookie") or "")
            self.assertEqual(len(a.phone._load()), 1)
            self.assertEqual(a.phone.code, code)                                     # the TV's code still works for another phone
            a.on_own_wifi = lambda ip: False                                         # on the home network: nothing
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(portal + "/hotspot-detect.html", timeout=10)
            self.assertEqual(e.exception.code, 404)
            try:
                opener.open(remote + "/join", timeout=10)
            except urllib.error.HTTPError as e:
                self.assertNotIn("sofa_remote=", e.headers.get("Set-Cookie") or "")
            self.assertEqual(len(a.phone._load()), 1)
        finally:
            for srv in servers:
                srv.shutdown()
                srv.server_close()
            a.on_own_wifi, a.network.hotspot, a.phone = real

    @unittest.skipUnless(shutil.which("openssl"), "needs the openssl command")
    def test_sending_a_report(self):
        """Settings -> Help -> Send a report: the box's state and logs to the certificate service, signed with the
        box's id, with no titles, codes or passwords in it."""
        a, got, status = self.agent, [], [200]

        class Service(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                got.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                body = json.dumps({"ok": True, "report": "K7Q2MX"} if status[0] == 200 else {"error": "Try again tomorrow."}).encode()
                self.send_response(status[0])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        service = a.Server(("127.0.0.1", 0), Service)
        threading.Thread(target=service.serve_forever, daemon=True).start()
        logs = ("== Sofa Box OS 1.1.7\nmpv stopped (2): Failed to open /media/sofabox/USB/Some Film (2020).mkv | [ffmpeg] 403\n"
                "GET https://www.youtube.com/watch?v=abc123 failed\nnmcli: psk=hunter2\n")
        real = a.secure_remote, a.SecureRemote.SERVICE, a.network.hotspot, a.player.status, a.run
        a.SecureRemote.SERVICE = "http://127.0.0.1:%d" % service.server_address[1]
        a.secure_remote, a.network.hotspot = a.SecureRemote(), None
        a.secure_remote.acct = {"id": "k3x9q2abcd", "secret": "s3cret", "name": "k3x9q2abcd.box.edgeventure.uk"}
        a.player.status = {"item": "x1", "title": "Some Film", "sub": "Part 2", "t": 60, "d": 5400}
        a.run = lambda cmd, timeout=20: (0, logs) if cmd[-1] == "report" else (0, "")
        try:
            out = a.send_report()
            self.assertEqual((out["ok"], out["report"]), (True, "K7Q2MX"))
            self.assertIn("K7Q2MX", out["message"])                                  # the TV shows its number
            ((path, body),) = got
            self.assertEqual((path, body["id"], body["secret"]), ("/v1/report", "k3x9q2abcd", "s3cret"))
            text = body["report"]
            self.assertIn("Sofa Box OS", text)
            self.assertIn('"t": 60', text)                                            # where the player was
            self.assertIn("https://www.youtube.com/watch/…", text)                  # addresses: the site and its first folder
            for private in ("Some Film", "Part 2", "abc123", "hunter2"):
                self.assertNotIn(private, text)
            self.assertEqual(os.stat(os.path.join(a.CONF_DIR, "last-report.txt")).st_mode & 0o777, 0o600)
            self.assertEqual(a.send_report()["report"], "K7Q2MX")                    # pressed twice: sent once
            self.assertEqual(len(got), 1)
            a._report["at"] = 0
            status[0] = 429
            out = a.send_report()
            self.assertFalse(out["ok"])
            self.assertIn("Try again tomorrow.", out["message"])                      # the service's own words
            a.network.hotspot = {"at": 0}                                             # at the setup, on its own Wi-Fi
            self.assertIn("internet", a.send_report()["message"])
            self.assertEqual(len(got), 2)
        finally:
            a.secure_remote, a.SecureRemote.SERVICE, a.network.hotspot, a.player.status, a.run = real
            a._report["at"] = 0
            service.shutdown()
            service.server_close()
        with open(os.path.join(BOX, "install.sh")) as f:
            self.assertIn("$LIB/sofa-box report", f.read())                          # sudo may run it, for the logs

    def test_the_weather_on_home(self):
        """Home's weather from MET Norway (stood in for here), for the place picked in Settings (or the time zone's city),
        asked at most every half hour; and the place search (OpenStreetMap's, stood in for too)."""
        a, asked, now = self.agent, [], time.time()
        series = [{"time": time.strftime("%Y-%m-%dT%H:00:00Z", time.gmtime(now + h * 3600)),
                   "data": {"instant": {"details": {"air_temperature": 10 + h}},
                            "next_1_hours": {"summary": {"symbol_code": "rain" if h == 0 else "clearsky_day"}}}} for h in range(30)]

        class Met(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                asked.append((self.path, self.headers.get("User-Agent")))
                body = json.dumps([{"name": "Miami", "display_name": "Miami, Miami-Dade County, Florida, United States",
                                    "lat": "25.7741728", "lon": "-80.19362", "addresstype": "city"},
                                   {"name": "Miami County", "display_name": "Miami County, Ohio, United States",
                                    "lat": "40.05", "lon": "-84.22", "addresstype": "county"}] if self.path.startswith("/search")
                                  else {"properties": {"timeseries": series}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        service = a.Server(("127.0.0.1", 0), Met)
        threading.Thread(target=service.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % service.server_address[1]
        real = a.WEATHER_URL, a.PLACES_URL
        a.WEATHER_URL, a.PLACES_URL = base + "/forecast", base + "/search"
        a._weather.update(at=0, key=None, series=None)
        try:
            a.save_settings(weather="on", weather_units="c", weather_place={"name": "Testville", "lat": 51.5, "lon": -0.12})
            w = a.weather(now)
            self.assertEqual((w["ok"], w["place"], w["units"], w["temp"], w["symbol"], w["low"]), (True, "Testville", "C", 10, "rain", 10))
            self.assertGreaterEqual(w["high"], 33)                                     # the next 24 hours
            self.assertEqual([h["temp"] for h in w["hours"]], [11, 14, 17, 20])         # every three hours
            self.assertIn("lat=51.50&lon=-0.12", asked[0][0])                         # the place to about a kilometre
            self.assertTrue(asked[0][1].startswith("SofaBox/"))                       # MET Norway asks who's asking
            a.save_settings(weather_units="f")
            self.assertEqual(a.weather(now + 1)["temp"], 50)
            self.assertEqual(len(asked), 1)                                           # kept for half an hour
            a.weather(now + 1900)
            self.assertEqual(len(asked), 2)
            places = a.find_places("Miami")["places"]
            self.assertEqual([(p["name"], p["where"], p["lat"]) for p in places], [("Miami", "Miami-Dade County, Florida, United States", 25.77)])
            self.assertEqual(a.find_places("x")["places"], [])                        # too short to look up
            service.shutdown()
            self.assertTrue(a.weather(now + 4000)["ok"])                              # the service away: the last one still
            a.save_settings(weather="off")
            self.assertTrue(a.weather(now)["off"])
        finally:
            service.shutdown()
            service.server_close()
            a.WEATHER_URL, a.PLACES_URL = real
            a.save_settings(weather="on", weather_units="auto", weather_place=None)
        self.assertIsNone(a.weather_place({"name": "Nowhere", "lat": "95", "lon": 0}))
        self.assertEqual(a.weather_place({"name": "Miami <b>", "lat": 25.7741, "lon": "-80.1936"}), {"name": "Miami b", "lat": 25.77, "lon": -80.19})
        london = a.zone_place("Europe/London")                                       # the time zone's city, from the system
        self.assertEqual(london["name"], "London")
        self.assertAlmostEqual(london["lat"], 51.51, delta=0.05)
        self.assertAlmostEqual(london["lon"], -0.12, delta=0.05)
        self.assertTrue(a.FAHRENHEIT.match("America/New_York") and not a.FAHRENHEIT.match("Europe/London"))

    def test_what_a_slow_start_says(self):
        p = self.agent.Player()
        p.payload = {"title": "The Expanse", "offset": 3725, "start": 0, "url": "http://sofa/media/hls/0123/index.m3u8"}
        self.assertEqual(p.starting_note(1), "")                                 # (the card says Resuming, from 1:02:05)
        self.assertIn("Sofa is getting it ready for the box from where you left off", p.starting_note(4))
        self.assertIn("Back stops it", p.starting_note(30))
        p.payload = {"title": "A private title", "adult": True, "start": 0, "url": "http://sofa/media/x/file"}
        self.assertEqual(p.starting_note(5), "")
        with open(p.write_info(p.payload)) as f:                                 # no adult titles on the screen
            info = json.load(f)
        os.remove(p.info_path)
        self.assertEqual((info["title"], info["sub"], info["kind"]), ("Playing", "", "start"))

    def test_the_first_start_says_so(self):
        """A new card's first start (slow, maybe with a restart): its boot screen says to wait, that start only."""
        with open(os.path.join(BOX, "install.sh")) as f:
            install = f.read()
        unit = install.split("sofa-box-first-start.service <<EOF", 1)[1].split("\nEOF", 1)[0]
        self.assertIn("ConditionFirstBoot=yes", unit)
        self.assertIn("plymouth display-message", unit)
        self.assertRegex(install, r"systemctl enable [^\n]*\\\n\s*sofa-box-first-start\.service")
        with open(os.path.join(BOX, "sofa-box-art.py")) as f:
            self.assertIn("Plymouth.SetMessageFunction(message)", f.read())             # the boot screen shows it
        # no blank moments: the boot screen stays until the box's helper answers, and Home is dark from its first frame
        self.assertIn("ExecStartPre=-+$LIB/sofa-box before-screen", install)
        self.assertNotIn("ExecStartPre=-+/usr/bin/plymouth quit", install)
        with open(os.path.join(BOX, "home", "index.html")) as f:
            page = f.read()
        self.assertIn('<meta name="color-scheme" content="dark">', page)
        self.assertLess(page.index("background: #0D0D10"), page.index("home.css"))

    def test_the_remote_through_the_relay(self):
        """The phone remote from anywhere: the QR code points at the relay (deploy/box-certs), the box keeps a request
        open there, and a phone's requests reach the box's real remote and come back. Only the QR's long link pairs."""
        from tests.test_box_certs import load as load_certs
        a, work = self.agent, tempfile.mkdtemp()
        certs = load_certs(work)
        service = certs.Service(dict(certs.DEFAULTS), None, None)
        certs.Handler.service = service
        relay = ThreadingHTTPServer(("127.0.0.1", 0), certs.Handler)
        threading.Thread(target=relay.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % relay.server_address[1]
        service.cfg["relay_base"] = base
        box = service.register("192.168.1.30")
        remote = a.Server(("127.0.0.1", 0), a.RemoteHandler)
        threading.Thread(target=remote.serve_forever, daemon=True).start()
        real = a.secure_remote, a.phone, a.SecureRemote.SERVICE, a.PhoneRemote.PORT, a.network.hotspot
        a.SecureRemote.SERVICE, a.PhoneRemote.PORT, a.network.hotspot = base, remote.server_address[1], None
        a.secure_remote, a.phone = a.SecureRemote(), a.PhoneRemote()
        a.secure_remote.acct = dict(box)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

        def phone(path, body=None, cookie=None):
            req = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode(),
                                         dict({"Content-Type": "application/json", "X-Sofa-Remote": "1"}, **({"Cookie": cookie} if cookie else {})))
            try:
                with opener.open(req, timeout=30) as r:
                    return r.status, dict(r.headers), r.read()
            except urllib.error.HTTPError as e:
                return e.code, dict(e.headers), e.read()
        try:
            a.secure_remote.start_relay()
            for _ in range(60):
                if a.secure_remote.url():
                    break
                time.sleep(0.1)
            here = "%s/r/%s" % (base, box["id"])
            self.assertEqual(a.secure_remote.url(), here)
            self.assertEqual(a.secure_remote.status()["state"], "ready")
            st = a.phone.status()
            self.assertEqual(st["pair_url"], here + "/r/" + a.phone.link)              # the QR code: the long link
            self.assertNotIn(st["code"], st["pair_url"])
            link = a.phone.link
            status, headers, _ = phone("/r/%s/r/%s" % (box["id"], link))             # scanned
            self.assertEqual((status, headers["Location"]), (302, "/r/%s/" % box["id"]))
            cookie = headers["Set-Cookie"].split(";")[0]
            self.assertTrue(cookie.startswith("sofa_remote="))
            status, _, body = phone("/r/%s/api/state" % box["id"], cookie=cookie)
            self.assertEqual((status, json.loads(body)["paired"]), (200, True))        # the box's own answer, from anywhere
            self.assertEqual(phone("/r/%s/r/%s" % (box["id"], link))[1]["Location"], "/r/%s/?again=1" % box["id"])  # once
            # the setup's phone carries on with a link of its own: someone scanning the TV's code meanwhile doesn't use
            # it up, and it works once too
            a.phone.handoff_link = handoff = "ab" * 12
            self.assertEqual(phone("/r/%s/r/%s" % (box["id"], a.phone.link))[0], 302)   # the TV's code, scanned
            status, headers, _ = phone("/r/%s/r/%s" % (box["id"], handoff))
            self.assertEqual((status, headers["Location"]), (302, "/r/%s/" % box["id"]))
            self.assertEqual(phone("/r/%s/r/%s" % (box["id"], handoff))[1]["Location"], "/r/%s/?again=1" % box["id"])
            code = a.phone.code                                                         # four digits: home only
            req = urllib.request.Request("http://127.0.0.1:%d/r/%s" % (remote.server_address[1], code), headers={"X-Sofa-Relay": "1"})
            try:
                opener.open(req, timeout=10)
            except urllib.error.HTTPError as e:
                self.assertEqual(e.headers["Location"], "/?again=1")
            self.assertEqual(a.phone.code, code)                                        # (not used up)
            self.assertEqual(phone("/r/%s/api/state" % box["id"])[0], 401)             # no sign-in: nothing
        finally:
            a.SecureRemote.SERVICE = "0"                                                # the relay loop ends
            relay.shutdown()
            relay.server_close()
            remote.shutdown()
            remote.server_close()
            a.secure_remote, a.phone, a.SecureRemote.SERVICE, a.PhoneRemote.PORT, a.network.hotspot = real
            shutil.rmtree(work, ignore_errors=True)

    def test_the_phone_remote_over_https_at_home(self):
        """The box gets its own name and certificate (deploy/box-certs, stood in for here) and serves the remote with it."""
        import ssl
        from tests.test_box_certs import TestCA
        a, work = self.agent, tempfile.mkdtemp()
        ca, asked = TestCA(work), []

        class Service(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                asked.append((self.path, data.get("ip")))
                out = {"/v1/register": {"id": "k3x9q2abcd", "secret": "s3cret", "name": "k3x9q2abcd.box.edgeventure.uk"},
                       "/v1/address": {"ok": True}}.get(self.path) or {"cert": ca.sign(data["csr"])}
                body = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        service = a.Server(("127.0.0.1", 0), Service)
        threading.Thread(target=service.serve_forever, daemon=True).start()
        real = a.secure_remote, a.phone, a.resolves_to, a.SecureRemote.SERVICE, a.SecureRemote.PORT
        a.SecureRemote.SERVICE, a.SecureRemote.PORT = "http://127.0.0.1:%d" % service.server_address[1], 0
        a.secure_remote, a.phone = a.SecureRemote(), a.PhoneRemote()
        a.resolves_to = lambda name, ip: True
        a.save_settings(remote_link="certificate")                                     # (the relay is the default)
        r = a.secure_remote
        try:
            self.address = None                                                        # at the setup, not online yet
            self.assertTrue(r.step())                                                  # (so it looks again in 30 s)
            self.assertEqual(asked, [])
            self.address = "192.168.1.30"
            self.assertFalse(r.step())
            self.assertEqual([p for p, _ in asked], ["/v1/register", "/v1/address", "/v1/cert"])
            self.assertEqual(asked[1][1], "192.168.1.30")                            # its address here, and nothing else
            self.assertEqual(r.status()["state"], "ready")
            port = r.server.server_address[1]
            self.assertEqual(a.phone.url(), "https://k3x9q2abcd.box.edgeventure.uk:0")   # (PORT 0 here: a free one)
            ctx = ssl.create_default_context(cafile=ca.cert)                            # a phone that trusts the certificate's CA
            with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
                with ctx.wrap_socket(raw, server_hostname="k3x9q2abcd.box.edgeventure.uk") as tls:
                    tls.sendall(b"GET / HTTP/1.1\r\nHost: k3x9q2abcd.box.edgeventure.uk\r\nConnection: close\r\n\r\n")
                    page = b""
                    while True:
                        chunk = tls.recv(65536)
                        if not chunk:
                            break
                        page += chunk
            self.assertTrue(page.startswith(b"HTTP/1.1 200"))
            self.assertIn(b"<title>", page)
            for f in ("key.pem", "cert.pem", "account.json"):
                self.assertEqual(os.stat(r.path(f)).st_mode & 0o777, 0o600)
            r.step()                                                                    # fresh: nothing asked again
            self.assertEqual(len(asked), 3)
            self.address = "192.168.1.31"                                              # a new address: the name follows it
            r.step()
            self.assertEqual(asked[-1], ("/v1/address", "192.168.1.31"))
            a.resolves_to = lambda name, ip: False                                     # a router that blocks it: plain http
            r.step()
            self.assertEqual(r.status()["state"], "router")
            self.assertEqual(a.phone.url(), "http://192.168.1.31:8092")
            a.save_settings(secure_remote=False)                                      # switched off in Settings
            r.step()
            self.assertIsNone(r.server)
            self.assertEqual(r.status()["state"], "off")
        finally:
            r.stop()
            service.shutdown()
            service.server_close()
            a.save_settings(secure_remote=True, remote_link="relay")
            a.secure_remote, a.phone, a.resolves_to, a.SecureRemote.SERVICE, a.SecureRemote.PORT = real
            shutil.rmtree(work, ignore_errors=True)

    def test_its_version(self):
        with open(os.path.join(BOX, "VERSION")) as f:
            v = f.read().strip()
        self.assertRegex(v, r"^\d+\.\d+\.\d+$")
        self.assertEqual(self.agent.OS_VERSION, v)
        with open(os.path.join(BOX, "CHANGES.md")) as f:
            self.assertIn("\n## %s\n" % v, f.read())                 # the release's notes come from there
        self.assertTrue(self.agent.newer("1.0.10", "1.0.9") and self.agent.newer("2.0.0", "1.9.9"))
        self.assertFalse(self.agent.newer("1.0.0", "1.0.0") or self.agent.newer("0.9.0", "1.0.0") or self.agent.newer("x", "1.0.0"))


assert tests.ROOT


class LiveBanner(unittest.TestCase):
    """Live TV in the box's player: the channel's banner (number, name, what's on, what's next) at each programme of
    an archive channel, not at the commercials between them."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        old = {k: os.environ.get(k) for k in ("SOFA_BOX_CONF", "SOFA_BOX_DEVTOOLS", "SOFA_BOX_CAPTIVE_PORT")}
        os.environ.update(SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0")
        try:
            cls.agent = load("sofa-box-agent")
        finally:
            for k, v in old.items():
                os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def banner(self, payload, at):
        p, said = self.agent.Player(), []
        p.payload = payload
        p.command = lambda *cmd: said.append(cmd)
        p.banner(at)
        self.assertEqual(said[0][:3], ("script-message-to", "sofa_player", "sofa"))   # (the player screen draws it)
        return json.loads(said[0][3])["banner"]

    def test_smoothness(self):
        """The box measures how quickly its pages answer the remote, says so in a report, and on a board with the full
        look by itself (Automatic) takes the light look when a fifth of the presses take 0.1 s or more."""
        a = self.agent
        self.assertFalse(a.too_slow(30, 30))                       # (too few presses to tell)
        self.assertFalse(a.too_slow(100, 10))
        self.assertTrue(a.too_slow(100, 25))
        line = a.smooth_lines({"home": {"presses": 120, "slow": 6, "worst": 240, "long": 3, "long_ms": 410}})[0]
        self.assertEqual(line, "  home: 120 presses, 6 slower than 0.1 s (slowest 0.24 s); 3 long tasks (0.4 s in all)")
        real = a.board
        a.board = lambda: {"gen": 5, "memory_mb": 4096}
        try:
            a.save_settings(performance="auto", learned_lite=False)
            self.assertFalse(a.light())
            a.save_settings(learned_lite=True)                       # the box chose it
            self.assertTrue(a.light())
            a.save_settings(performance="full")
            self.assertFalse(a.light())                              # (the owner's choice comes first)
        finally:
            a.board = real
            a.save_settings(performance="auto", learned_lite=False)

    def test_the_volume(self):
        self.assertEqual(self.agent.parse_volume("Volume: 0.45\n"), (45, False))                 # wpctl
        self.assertEqual(self.agent.parse_volume("Volume: 0.30 [MUTED]\n"), (30, True))
        self.assertEqual(self.agent.parse_volume("Volume: front-left: 29491 /  45% / -20.81 dB,   front-right: 29491 /  45%"
                                                 "\nMute: yes\n"), (45, True))                    # pactl
        self.assertEqual(self.agent.parse_volume(""), (None, False))

    def test_the_options_menu(self):
        """Menu while a video plays: subtitles, sound, speed, volume; the arrows and OK are the menu's while it's open."""
        a = self.agent
        p, said = a.Player(), []
        tracks = [{"type": "video", "id": 1}, {"type": "audio", "id": 1, "lang": "eng", "selected": True},
                  {"type": "audio", "id": 2, "lang": "spa"}, {"type": "sub", "id": 1, "lang": "eng"},
                  {"type": "sub", "id": 2, "title": "Signs", "forced": True}]
        p.command = lambda *cmd: said.append(cmd) or ({"track-list": tracks, "speed": 1.0}.get(cmd[1]) if cmd[0] == "get_property" else None)
        p.payload = {"title": "Heat"}
        real = a.playing, a.volume_now
        a.playing, a.volume_now = (lambda: True), (lambda: (40, False))
        try:
            p.menu_toggle()
            self.assertIn(("enable-section", "sofa-menu", "exclusive"), said)
            menu = lambda: json.loads(said[-1][3])["menu"]                     # (the player screen draws it)
            text = json.dumps(menu(), ensure_ascii=False)
            for word in ("Options", "Subtitles", "Off", "Sound", "Speed", "Volume", "40%", "Close"):
                self.assertIn(word, text)
            self.assertEqual([r["label"] for r in menu()["rows"] if r["on"]], ["Subtitles"])
            p.menu_key("right")                                            # Subtitles: Off -> English
            self.assertIn(("set_property", "sid", 1), said)
            p.menu_key("right")
            self.assertIn(("set_property", "sid", 2), said)
            self.assertIn("Signs (forced)", said[-1][3])
            p.menu_key("down")                                             # Sound: English -> Spanish
            p.menu_key("ok")
            self.assertIn(("set_property", "aid", 2), said)
            p.menu_key("back")
            self.assertIn(("disable-section", "sofa-menu"), said)
            self.assertEqual(json.loads(said[-1][3]), {"menu": False})
            self.assertIsNone(p.menu)
            p.menu_key("ok")                                               # (closed: nothing)
        finally:
            a.playing, a.volume_now = real

    def test_the_banner(self):
        progs = [{"title": "Kids' WB {Feb 10, 2001}", "year": 2001, "ad": False}, {"title": "Ad", "ad": True},
                 {"title": "Fox Box", "year": 2002, "ad": False}]
        b = self.banner({"live": True, "title": "00s Saturday Mornings", "number": 4, "programs": progs}, 0)
        self.assertEqual((b["number"], b["name"]), ("4", "00s Saturday Mornings"))
        self.assertEqual(b["now"], "Kids' WB {Feb 10, 2001} (2001)")      # (as it is: the screen keeps braces as text)
        self.assertEqual(b["next"], "Fox Box (2002)")
        b = self.banner({"live": True, "title": "00s Saturday Mornings", "number": 4, "programs": progs}, 1)
        self.assertEqual(b["sub"], "Commercials, then Fox Box (2002)")
        b = self.banner({"live": True, "title": "A free channel", "programs": []}, 0)
        self.assertNotIn("next", b)


class PlayerScreen(unittest.TestCase):
    """The box's player screen: mpv draws the TV's own (deploy/sofa-box/sofa-player.lua) in place of its desktop controls,
    which came up whenever the pointer moved and stayed while it sat on them (the box parks it in the corner, on the
    bar); everything inside the TV's safe area; Sofa's converted video from its first segment."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        old = {k: os.environ.get(k) for k in ("SOFA_BOX_CONF", "SOFA_BOX_DEVTOOLS", "SOFA_BOX_CAPTIVE_PORT", "SOFA_BOX_MPV")}
        os.environ.update(SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0",
                          SOFA_BOX_MPV=os.path.join(HERE, "tools", "fake_mpv.py"))
        try:
            cls.agent = load("sofa-box-agent")
        finally:
            for k, v in old.items():
                os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def args(self, payload):
        from unittest import mock
        p = self.agent.Player()
        p.sock_path, p.base = os.path.join(self.conf, "x.sock"), "http://sofa"
        with mock.patch.dict(os.environ, {"SOFA_BOX_MPV": os.path.join(HERE, "tools", "fake_mpv.py")}):
            args = p._args(payload)
        os.remove(p.info_path)
        return args

    def test_mpv_gets_the_tv_screen(self):
        args = self.args({"url": "http://sofa/media/m%3Aheat%3A1995/file", "title": "Heat"})
        for want in ("--osc=no", "--input-cursor=no", "--cursor-autohide=always", "--osd-bar=no", "--osd-on-seek=no",
                     "--hr-seek=no", "--force-media-title=Heat"):
            self.assertIn(want, args)
        self.assertIn("--script=" + os.path.join(os.path.abspath(BOX), "sofa-player.lua"), args)
        self.assertTrue(any(a.startswith("--osd-fonts-dir=") for a in args))     # (Sofa's typefaces)
        self.assertFalse([a for a in args if "live_start_index" in a])
        hls = self.args({"url": "http://sofa/media/hls/0123/index.m3u8", "title": "Heat", "offset": 600})
        self.assertIn("--demuxer-lavf-o-append=live_start_index=0", hls)        # from its first segment, not near its end
        live = self.args({"url": "http://sofa/live/abc/index.m3u8", "title": "News", "live": True})
        self.assertFalse([a for a in live if "live_start_index" in a])          # (live TV: from now, as before)
        private = self.args({"url": "http://sofa/media/x/file", "title": "A private title", "adult": True})
        self.assertIn("--force-media-title=Sofa", private)
        self.assertFalse([a for a in private if "private" in a])

    def test_the_keys_reach_the_screen(self):
        """Every key mpv-input.conf gives the player screen is one the screen has (a typo there is a dead button), and
        the remote's OK, arrows and Back are the screen's (answered inside mpv, not by a curl to the agent)."""
        with open(os.path.join(BOX, "mpv-input.conf"), encoding="utf-8") as f:
            conf = f.read()
        with open(os.path.join(BOX, "sofa-player.lua"), encoding="utf-8") as f:
            lua = f.read()
        used = set(re.findall(r"script-binding sofa_player/(\w+)", conf))
        have = set(re.findall(r'mp\.add_key_binding\(nil, "(\w+)"', lua))
        self.assertTrue(used)
        self.assertEqual(sorted(used - have), [])
        said = set(re.findall(r"script-message-to sofa_player (\w+)", conf))       # (the number keys: "percent N")
        self.assertEqual(sorted(said - set(re.findall(r'mp\.register_script_message\("(\w+)"', lua))), [])
        for key in ("ENTER", "ESC", "BS", "LEFT", "RIGHT", "UP", "DOWN", "PLAYPAUSE"):
            self.assertRegex(conf, r"(?m)^%s\s+script-binding sofa_player/" % key)
        for n in range(10):                                                     # through the screen: far ones too
            self.assertRegex(conf, r"(?m)^%d\s+script-message-to sofa_player percent %d$" % (n, n * 10))
        live = self.agent.live_input_conf()                                      # Live TV: up and down change channel
        with open(live, encoding="utf-8") as f:
            self.assertRegex(f.read(), r"(?m)^UP\s+run .*k=chup")

    def test_the_phone_works_the_same_player(self):
        """The phone remote's keys during a video are the player screen's own, as the TV's remote presses them (OK skips
        an intro or pauses, skips add up, up and down show where it is); with the options menu open, the menu's; on Live
        TV, up and down change the channel. (Up and down used to go to the page behind the video.)"""
        a, did = self.agent, []

        class Proc:
            def poll(self):
                return None

        class Player:
            proc, payload, menu = Proc(), {"title": "Heat"}, None
            command = lambda self, *c: did.append(c)
            stop = lambda self, **k: did.append(("stop", k.get("reason")))
            zap = lambda self, step: did.append(("zap", step))
            menu_key = lambda self, k: did.append(("menu", k))
            menu_toggle = lambda self: did.append(("menu-toggle",))
        real, a.player = a.player, Player()
        try:
            phone = a.PhoneRemote()
            for k in ("ok", "right", "left", "up", "play", "back", "menu"):
                phone.key(k)
            self.assertEqual(did, [("script-binding", "sofa_player/ok"), ("script-binding", "sofa_player/on30"),
                                   ("script-binding", "sofa_player/back10"), ("script-binding", "sofa_player/show"),
                                   ("script-binding", "sofa_player/toggle"), ("stop", "back"), ("menu-toggle",)])
            del did[:]
            a.player.payload = {"live": True}
            phone.key("up")
            phone.key("down")
            self.assertEqual(did, [("zap", -1), ("zap", 1)])
            del did[:]
            a.player.menu = {"items": []}
            phone.key("down")
            phone.key("menu")
            self.assertEqual(did, [("menu", "down"), ("menu", "back")])
        finally:
            a.player = real

    def converted(self, playlist=""):
        """A Player playing a video Sofa converts for the box, from 600 s in, with stand-ins for mpv's socket and Sofa."""
        p = self.agent.Player()
        mpv = {"time-pos": 5.0, "demuxer-cache-time": 30.0, "pause": False, "path": "http://sofa/media/hls/aaaa/index.m3u8"}
        said, asked, sofa = [], [], {"playlist": playlist, "sessions": iter(["bbbb", "cccc", "dddd"]), "wait": None}

        def command(*cmd):
            said.append(cmd)
            if cmd[0] == "get_property":
                return mpv.get(cmd[1])
            if cmd[:2] == ("set_property", "pause"):
                mpv["pause"] = cmd[2]
            elif cmd[0] == "loadfile":                                   # (no position until the new one has opened)
                mpv.update({"path": cmd[1], "time-pos": None})

        def ask_sofa(url, timeout=20):
            asked.append(url)
            if url.endswith("/index.m3u8"):
                return sofa["playlist"].encode()
            if sofa["wait"]:
                sofa["wait"].wait(10)
            if isinstance(sofa.get("fail"), Exception):
                raise sofa["fail"]
            sid = next(sofa["sessions"])
            return json.dumps({"url": "/media/hls/%s/index.m3u8" % sid, "session": sid}).encode()

        class Proc:
            def poll(self):
                return None
        p.proc, p.command, p.ask_sofa, p.base, p.cookie = Proc(), command, ask_sofa, "http://sofa", "sofa=tv"
        p.payload = {"item": "m:heat:1995", "url": "http://sofa/media/hls/aaaa/index.m3u8", "offset": 600, "duration": 7200,
                     "hls": "http://sofa/api/hls/m%3Aheat%3A1995?mode=transcode&h=720",
                     "subtitles": [{"url": "http://sofa/media/m%3Aheat%3A1995/subs/0.vtt?offset=600.00", "lang": "en"}]}
        p.status = {"item": "m:heat:1995", "t": 605}
        return p, mpv, said, asked, sofa

    @staticmethod
    def screen(said):
        """What the agent told the player screen (sofa-player.lua), in order."""
        return [json.loads(c[3]) for c in said if c[:3] == ("script-message-to", "sofa_player", "sofa")]

    def settle(self, p):
        end = time.time() + 10
        while p.going and time.time() < end:
            time.sleep(0.02)
        self.assertFalse(p.going)

    def test_skipping_far_in_a_converted_video(self):
        """A video Sofa converts for the box comes as a stream Sofa makes from `offset` on as it plays, and mpv can go only
        where Sofa has converted it so far. A skip into what mpv has, or into what Sofa has made (its playlist), goes there
        in mpv. Further on, or back before where it starts, Sofa converts it again from there (as the page asked for it,
        the conversion before replaced), and mpv loads that, held still meanwhile so it can't run out of the old one and
        stop; the screen, the place saved and the phone remote's line say where it's going, then count from there."""
        p, mpv, said, asked, sofa = self.converted("#EXTM3U\n" + "#EXTINF:4.000000,\nseg.m4s\n" * 30)   # 2 minutes made
        p._go(p.proc, 620, False)                                         # in what mpv has read: mpv goes there itself
        self.assertIn(("seek", 20.0, "absolute"), said)
        self.assertEqual(self.screen(said), [{"far": False}])
        self.assertEqual(asked, [])
        p._go(p.proc, 700, False)                                         # in what Sofa has made: mpv too
        self.assertIn(("seek", 100.0, "absolute"), said)
        self.assertEqual(asked, ["http://sofa/media/hls/aaaa/index.m3u8"])
        del said[:], asked[:]
        p._go(p.proc, 1500, False)                                        # further: Sofa converts it from there
        self.assertEqual(asked, ["http://sofa/media/hls/aaaa/index.m3u8",
                                 "http://sofa/api/hls/m%3Aheat%3A1995?mode=transcode&h=720&t=1500.0&replace=aaaa"])
        held, load, back = (said.index(("set_property", "pause", True)), said.index(("loadfile", "http://sofa/media/hls/bbbb/index.m3u8", "replace")),
                            said.index(("set_property", "pause", False)))
        self.assertLess(held, load)
        self.assertLess(load, back)                                       # (as it was: playing)
        self.assertIn(("set_property", "sub-files", ["http://sofa/media/m%3Aheat%3A1995/subs/0.vtt?offset=1500.00"]), said)
        self.assertEqual(self.screen(said), [{"far": {"at": 1500}},
                                             {"info": {"offset": 1500, "at": 1500}, "far": {"at": 1500, "sid": "bbbb"}}])
        self.assertEqual((p.payload["url"], p.payload["offset"]), ("http://sofa/media/hls/bbbb/index.m3u8", 1500))
        self.assertEqual((p.position(), p.status["t"]), (1500, 1500))     # opening: where it's going
        mpv["time-pos"] = 2.0
        self.assertEqual(p.position(), 1502.0)                            # it plays: from there on
        self.assertIsNone(p.far)
        self.assertEqual(self.screen(said)[-1], {"far": False})
        mpv.update({"time-pos": 2.0, "demuxer-cache-time": 30.0})
        p._go(p.proc, 1000, False)                                        # back before where it starts now: again
        self.assertTrue(asked[-1].endswith("&t=1000.0&replace=bbbb"))
        self.assertEqual(p.payload["offset"], 1000)

    def test_far_skips_one_at_a_time(self):
        """Skips that come while Sofa is converting (more presses, the phone remote): the newest is where it goes, at once
        on the screen and the phone, and only that one is loaded; play and pause meanwhile are for when it's there. Sofa
        busy: it says so, and it plays on as it was. A page from an older Sofa (no `hls`): mpv seeks, as before."""
        p, mpv, said, asked, sofa = self.converted()
        sofa["wait"] = threading.Event()
        p.control({"cmd": "seek", "t": 3000})                             # the phone remote's line
        end = time.time() + 5
        while not p.far and time.time() < end:
            time.sleep(0.02)
        self.assertEqual((p.position(), p.status["t"]), (3000, 3000))
        p.control({"cmd": "toggle"})                                      # pause, for when it's there
        self.assertFalse([c for c in said if c[0] == "cycle"])
        p.control({"cmd": "skip", "by": 300})                             # and on 5 minutes more, while it waits
        self.assertEqual((p.position(), p.status["t"], p.status["paused"]), (3300, 3300, True))
        self.assertEqual(self.screen(said)[-1], {"far": {"at": 3300}})
        sofa["wait"].set()
        self.settle(p)
        self.assertEqual([u.split("&t=")[1] for u in asked if "/api/hls/" in u], ["3000.0&replace=aaaa", "3300.0&replace=bbbb"])
        self.assertEqual([c[1] for c in said if c[0] == "loadfile"], ["http://sofa/media/hls/cccc/index.m3u8"])
        self.assertEqual([c for c in said if c[:2] == ("set_property", "pause")][-1], ("set_property", "pause", True))
        mpv["time-pos"] = 0.5
        self.assertEqual(p.position(), 3300.5)
        # Sofa busy converting for others: it says why, and the video goes on where it was
        p, mpv, said, asked, sofa = self.converted()
        sofa["fail"] = urllib.error.HTTPError("http://sofa/api/hls/x", 503, "Busy", {}, io.BytesIO(
            json.dumps({"error": "The server is busy converting other videos for other people."}).encode()))
        p.seek_to(5000)
        self.settle(p)
        self.assertIsNone(p.far)
        self.assertEqual([c for c in said if c[:2] == ("set_property", "pause")][-1], ("set_property", "pause", False))
        self.assertEqual(self.screen(said)[-1], {"far": False, "toast": "Sofa couldn't get that part ready: The server is busy "
                                                                       "converting other videos for other people."})
        self.assertFalse([c for c in said if c[0] == "loadfile"])
        self.assertEqual(p.position(), 605.0)
        # a page from before Sofa 1.5.2 doesn't say how it asked for the conversion: mpv seeks, as before
        p, mpv, said, asked, sofa = self.converted()
        del p.payload["hls"]
        p.seek_to(5000)
        self.assertEqual(said, [("seek", 4400.0, "absolute")])
        self.assertFalse(p.going or asked)

    def test_the_screen_hears_it_can_skip_far(self):
        """The player screen sends skips past what mpv has to the agent only for a video Sofa converts whose request the
        page gave, on this Sofa (the TV's cookie never goes anywhere else)."""
        from unittest import mock

        def info(payload):
            p = self.agent.Player()
            p.sock_path, p.base = os.path.join(self.conf, "x.sock"), "http://sofa"
            with mock.patch.dict(os.environ, {"SOFA_BOX_MPV": os.path.join(HERE, "tools", "fake_mpv.py")}):
                p._args(payload)
            with open(p.info_path) as f:
                got = json.load(f)
            os.remove(p.info_path)
            return got
        hls = {"url": "http://sofa/media/hls/0123/index.m3u8", "title": "Heat", "offset": 600,
               "hls": "http://sofa/api/hls/m%3Aheat%3A1995?mode=transcode"}
        got = info(hls)
        self.assertTrue(got["far"])
        self.assertEqual(got["agent"], "http://127.0.0.1:%d" % self.agent.PORT)
        self.assertFalse(info(dict(hls, hls="http://elsewhere.example/api/hls/x?mode=remux"))["far"])
        self.assertFalse(info(dict(hls, hls=None))["far"])                # (an older Sofa's page)
        self.assertFalse(info({"url": "http://sofa/media/m%3Aheat%3A1995/file", "title": "Heat",
                               "hls": "http://sofa/api/hls/m%3Aheat%3A1995?mode=remux"})["far"])   # as it is: mpv seeks

    @unittest.skipUnless(shutil.which("mpv") and media.tool("ffmpeg"), "needs mpv and ffmpeg")
    def test_in_mpv_itself(self):
        """The screen in mpv itself: the start card from the first moment, then the panel; OK pauses; three rights
        quickly are one skip of 1:30 (the line moves at once); Skip intro, and OK skips it; a message; every word
        inside the TV's safe area (5% in from the edges of 1920x1080); Back stops mpv with 10."""
        d = tempfile.mkdtemp()
        try:
            video = os.path.join(d, "clock.mp4")
            subprocess.run([media.tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25",
                            "-t", "200", "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", video], check=True)
            info = os.path.join(d, "info.json")
            with open(info, "w") as f:
                json.dump({"title": "Clock", "sub": "2020", "kind": "resume", "at": 3, "offset": 0, "duration": 200,
                           "markers": [{"kind": "intro", "start": 100, "end": 150}], "accent": "FF2E88"}, f)
            seen = os.path.join(d, "seen.jsonl")
            os.makedirs(os.path.join(d, "s"))
            with open(os.path.join(d, "s", "sofa-player.lua"), "w") as f:    # (the same name: the same bindings)
                f.write(SCREEN_SPY % {"seen": json.dumps(seen), "real": json.dumps(os.path.join(os.path.abspath(BOX), "sofa-player.lua"))})
            sock = os.path.join(d, "mpv.sock")
            proc = subprocess.Popen(["mpv", "--no-config", "--vo=null", "--ao=null", "--idle=no", "--input-ipc-server=" + sock,
                                     "--input-conf=" + os.path.join(BOX, "mpv-input.conf"), "--osc=no", "--hr-seek=no",
                                     "--script=" + os.path.join(d, "s", "sofa-player.lua"), "--script-opts=sofa_player-info=" + info,
                                     "--start=3", "--pause", video], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                def mpv(*cmd):
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.settimeout(10)
                    s.connect(sock)
                    s.sendall((json.dumps({"command": list(cmd)}) + "\n").encode())
                    buf = b""
                    while b"\n" not in buf:
                        buf += s.recv(65536)
                    s.close()
                    return json.loads(buf.split(b"\n")[0]).get("data")

                def drawn():
                    with open(seen, encoding="utf-8") as f:
                        return [json.loads(line) for line in f]

                def until(check, secs=15):
                    end = time.time() + secs
                    while time.time() < end:
                        try:
                            if check():
                                return True
                        except (OSError, ValueError):
                            pass
                        time.sleep(0.1)
                    self.fail("never got there")

                until(lambda: os.path.exists(seen) and drawn())
                self.assertIn("RESUMING", drawn()[0])                            # (paused at its start: the card)
                self.assertIn("Clock", drawn()[0])
                mpv("set_property", "pause", False)
                until(lambda: "RESUMING" not in drawn()[-1] and "2020" in drawn()[-1])   # moving: the panel
                mpv("keypress", "ENTER")
                until(lambda: mpv("get_property", "pause") is True)
                mpv("keypress", "ENTER")
                until(lambda: mpv("get_property", "pause") is False)
                t0 = mpv("get_property", "time-pos")
                for _ in range(3):
                    mpv("keypress", "RIGHT")
                until(lambda: any("+1:30" in x for x in drawn()), 3)             # the line moved at once
                until(lambda: (mpv("get_property", "time-pos") or 0) >= t0 + 85)        # and the picture followed
                mpv("seek", 110, "absolute")
                until(lambda: "Skip intro" in drawn()[-1])
                mpv("keypress", "ENTER")
                until(lambda: (mpv("get_property", "time-pos") or 0) >= 149)
                mpv("script-message-to", "sofa_player", "sofa", json.dumps({"toast": "Videos come as 720p from now on."}))
                until(lambda: "Videos come as 720p" in drawn()[-1])
                for data in drawn():
                    for an, x, y in re.findall(r"\\an(\d)\\pos\(([-\d.]+),([-\d.]+)\)\\fn", data):
                        self.assertTrue(96 <= float(x) <= 1824 and 54 <= float(y) <= 1026, (an, x, y, data[:300]))
                mpv("keypress", "ESC")
                self.assertEqual(proc.wait(10), 10)
                self.assertNotIn(b"[sofa_player] Lua error", proc.stderr.read())
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait(10)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(shutil.which("mpv") and media.tool("ffmpeg") and os.path.exists("/usr/bin/curl"), "needs mpv, ffmpeg and curl")
    def test_far_skips_in_mpv_itself(self):
        """Skips in a video Sofa converts (a stream from 10:00 in, 40 s of it made so far), in mpv itself: one into what mpv
        has goes there, with nothing asked of the box; Page Up's 5 minutes moves the line and asks the box's agent (as
        mpv's own keys reach it), mpv staying where it is; the agent's word shows a note, then the new stream plays and the
        screen counts from the new place. Back before where it starts and the number keys ask too; no word at all: a
        message, and it stays where it was."""
        d = tempfile.mkdtemp()
        asked = []

        class TheAgent(BaseHTTPRequestHandler):
            def do_POST(self):
                asked.append((self.path, self.headers.get("X-Sofa-Box")))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass
        agent = ThreadingHTTPServer(("127.0.0.1", 0), TheAgent)
        threading.Thread(target=agent.serve_forever, daemon=True).start()
        proc = None
        try:
            video = os.path.join(d, "clock.mp4")
            subprocess.run([media.tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25",
                            "-t", "120", "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", video], check=True)
            for sid, at in (("aaaa", 0), ("bbbb", 50)):              # Sofa's conversions, as they are mid-way: no end yet
                os.makedirs(os.path.join(d, sid))
                subprocess.run([media.tool("ffmpeg"), "-v", "error", "-y", "-ss", str(at), "-i", video, "-t", "40", "-c", "copy",
                                "-f", "hls", "-hls_time", "4", "-hls_list_size", "0", "-hls_playlist_type", "event",
                                "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4",
                                "-hls_segment_filename", os.path.join(d, sid, "seg%05d.m4s"), os.path.join(d, sid, "index.m3u8")], check=True)
                with open(os.path.join(d, sid, "index.m3u8")) as f:
                    playlist = f.read().replace("#EXT-X-ENDLIST\n", "")
                with open(os.path.join(d, sid, "index.m3u8"), "w") as f:
                    f.write(playlist)
            info = os.path.join(d, "info.json")
            with open(info, "w") as f:
                json.dump({"title": "Clock", "kind": "resume", "at": 600, "offset": 600, "duration": 7200, "far": True,
                           "agent": "http://127.0.0.1:%d" % agent.server_address[1], "accent": "FF2E88"}, f)
            seen = os.path.join(d, "seen.jsonl")
            os.makedirs(os.path.join(d, "s"))
            with open(os.path.join(d, "s", "sofa-player.lua"), "w") as f:
                f.write(SCREEN_SPY % {"seen": json.dumps(seen), "real": json.dumps(os.path.join(os.path.abspath(BOX), "sofa-player.lua"))})
            sock = os.path.join(d, "mpv.sock")
            proc = subprocess.Popen(["mpv", "--no-config", "--vo=null", "--ao=null", "--idle=no", "--input-ipc-server=" + sock,
                                     "--input-conf=" + os.path.join(BOX, "mpv-input.conf"), "--osc=no", "--hr-seek=no", "--cache=yes",
                                     "--demuxer-lavf-o-append=live_start_index=0",
                                     "--script=" + os.path.join(d, "s", "sofa-player.lua"), "--script-opts=sofa_player-info=" + info,
                                     os.path.join(d, "aaaa", "index.m3u8")], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            def mpv(*cmd):
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(10)
                s.connect(sock)
                s.sendall((json.dumps({"command": list(cmd)}) + "\n").encode())
                buf = b""
                while b"\n" not in buf:
                    buf += s.recv(65536)
                s.close()
                return json.loads(buf.split(b"\n")[0]).get("data")

            def drawn():
                with open(seen, encoding="utf-8") as f:
                    return [json.loads(line) for line in f]

            def shown():                                             # the time on the panel's left, in seconds
                m = re.findall(r"\\pos\(96,1026\)[^}]*\}([\d:]+)", drawn()[-1])
                return sum(int(x) * 60 ** i for i, x in enumerate(reversed(m[-1].split(":")))) if m else None

            def until(check, secs=15):
                end = time.time() + secs
                while time.time() < end:
                    try:
                        if check():
                            return True
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.1)
                self.fail("never got there: %s" % (drawn()[-1][-400:] if os.path.exists(seen) else "nothing drawn"))

            until(lambda: os.path.exists(seen) and "RESUMING" not in drawn()[-1] and shown())     # playing: the panel
            until(lambda: (mpv("get_property", "demuxer-cache-time") or 0) >= 36)                 # (mpv has read it all)
            mpv("keypress", "RIGHT")                                         # +30 s: in what mpv has
            until(lambda: (mpv("get_property", "time-pos") or 0) >= 28)
            self.assertEqual(asked, [])
            t0 = mpv("get_property", "time-pos")
            mpv("keypress", "PGUP")                                          # +5 minutes: past it
            until(lambda: asked, 5)
            path, header = asked[-1]
            self.assertEqual(header, "1")                                    # (a POST the box takes from mpv)
            to = float(re.match(r"^/box/native/key\?k=far&t=([\d.]+)$", path).group(1))
            self.assertTrue(600 + t0 + 295 <= to <= 600 + t0 + 310, (t0, to))
            until(lambda: abs((shown() or 0) - to) <= 1, 3)                  # the line is there already...
            self.assertLess(mpv("get_property", "time-pos"), t0 + 5)         # ...and the picture stays put
            self.assertFalse(any("getting it ready" in x for x in drawn()))
            mpv("script-message-to", "sofa_player", "sofa", json.dumps({"far": {"at": to}}))   # Sofa is on it
            until(lambda: "Sofa is getting it ready for the box" in drawn()[-1])
            mpv("script-message-to", "sofa_player", "sofa", json.dumps({"info": {"offset": to, "at": to}, "far": {"at": to, "sid": "bbbb"}}))
            mpv("loadfile", os.path.join(d, "bbbb", "index.m3u8"), "replace")
            until(lambda: "getting it ready" not in drawn()[-1] and (mpv("get_property", "time-pos") or 0) > 1)
            until(lambda: int(to) <= (shown() or 0) <= int(to) + 10)         # counting from the new place
            until(lambda: (mpv("get_property", "demuxer-cache-time") or 0) >= 20)
            del asked[:]
            mpv("keypress", "LEFT")                                          # back before where it starts now
            until(lambda: asked, 5)
            self.assertLess(float(re.search(r"t=([\d.]+)", asked[-1][0]).group(1)), to)
            until(lambda: "The box didn't answer" in drawn()[-1], 10)       # (no word from the agent: as it was)
            until(lambda: int(to) <= (shown() or 0) <= int(to) + 20)
            del asked[:]
            mpv("keypress", "5")                                             # halfway: 1:00:00
            until(lambda: asked, 5)
            self.assertEqual(asked[-1][0], "/box/native/key?k=far&t=3600.0")
            until(lambda: shown() == 3600, 3)
            mpv("script-message-to", "sofa_player", "sofa", json.dumps({"far": False}))     # (it had it after all)
            until(lambda: int(to) <= (shown() or 0) <= int(to) + 20)
            for data in drawn():
                for an, x, y in re.findall(r"\\an(\d)\\pos\(([-\d.]+),([-\d.]+)\)\\fn", data):
                    self.assertTrue(96 <= float(x) <= 1824 and 54 <= float(y) <= 1026, (an, x, y, data[:300]))
            mpv("keypress", "ESC")
            self.assertEqual(proc.wait(10), 10)
            self.assertNotIn(b"[sofa_player] Lua error", proc.stderr.read())
        finally:
            if proc and proc.poll() is None:
                proc.kill()
            if proc:
                proc.wait(10)
            agent.shutdown()
            shutil.rmtree(d, ignore_errors=True)


# The player screen with a spy on what it draws: mpv loads this (named sofa-player.lua, so it's "sofa_player" with
# its key bindings), and it runs the real one, writing each overlay it shows to a file, one JSON line each.
SCREEN_SPY = """local real = mp.create_osd_overlay
local seen = %(seen)s
mp.create_osd_overlay = function(...)
    local o = real(...)
    local mt = getmetatable(o)        -- (on the overlays' shared methods: mpv sends every field of the overlay itself)
    if not rawget(mt, "spied") then
        local update = mt.update
        mt.update = function(self)
            local f = io.open(seen, "a")
            f:write(require("mp.utils").format_json(self.data), "\\n")
            f:close()
            return update(self)
        end
        rawset(mt, "spied", true)
    end
    return o
end
dofile(%(real)s)
"""


class ThisBoxDefaults(unittest.TestCase):
    def test_a_new_box_brings_no_channel_lists(self):
        """A new box's own Sofa starts without anyone else's channel lists: whoever owns the box adds the ones they want
        from Live TV. (A box that came loaded with other people's channels is what the "fully loaded box" cases were
        about.)"""
        from unittest import mock
        agent = load("sofa-box-agent")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(agent, "settings", return_value={}):
            here = agent.LocalSofa()
            here.data = os.path.join(d, "sofa")
            real = os.path.expanduser
            with mock.patch("os.path.expanduser", side_effect=lambda p: p.replace("~", d, 1) if p.startswith("~") else real(p)):
                here._config()
            with open(os.path.join(here.data, "config.json"), encoding="utf-8") as f:
                conf = json.load(f)
        self.assertEqual(conf["live_playlists"], [])
        self.assertNotIn("iptv-org", json.dumps(conf))


if __name__ == "__main__":
    unittest.main()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
