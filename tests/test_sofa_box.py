"""The Sofa box (deploy/sofa-box): the box's agent against a real Sofa (finding it, passing its pages
through with the box's player added, playing, saving the place, telling the page a video ended), its
settings, the boot screen, the remotes (HDMI-CEC, game controllers), and setting up a Raspberry Pi's
boot files (including one LCD-show changed for a 3.5-inch screen)."""
import importlib.util
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
        """Resuming a video Sofa converts first can take a while: mpv's screen says it's resuming, from where, and
        that Sofa is getting it ready, and says nothing more once the picture moves (no blank black screen)."""
        n = json.loads(self.get("/box/native/events"))["n"]
        self.post("/box/native/play", {"item": "m:heat:1995", "url": self.base + "/media/m%3Aheat%3A1995/file?fake_delay=4",
                                       "start": 0, "offset": 600, "duration": 7200, "title": "Heat"})
        self.wait_for(lambda st: st.get("t", 0) >= 601, 20)
        time.sleep(1.5)
        said = [c["command"][1] for c in map(json.loads, read(self.log).splitlines()) if c.get("command", [""])[0] == "show-text"]
        self.assertIn("Resuming Heat at 10:00…", said)
        self.assertEqual(said[-1], "")                                            # cleared once it plays
        self.post("/box/native/key?k=back", {})
        self.ended("m:heat:1995", n)

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
        self.assertEqual(self.post("/box/api/open", {"id": "edge-music"})[1]["url"], "https://music.edgeventure.uk")
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
        with self.assertRaises(urllib.error.HTTPError):
            self.opener.open(self.base + "/box/home/../sofa-box-agent.py", timeout=20)


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
        self.offline = 0
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
        self.offline = 0
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
            return answers["hotspot"] if "hotspot" in cmd else (0, "")
        a.run = nmcli
        net, real_sleep = a.Network(), a.time.sleep
        a.time.sleep = lambda s: None
        try:
            self.assertIsNone(net.start_hotspot())
            self.assertIn(["nmcli", "radio", "wifi", "on"], calls)                   # Raspberry Pi OS starts with it off
            self.assertLess(calls.index(["nmcli", "radio", "wifi", "on"]), next(i for i, c in enumerate(calls) if "hotspot" in c))
            self.assertIn("Wi-Fi is disabled", net.problem)                         # said on the TV, not a spinner for ever
            tried = len(calls)
            net.tick(0, net.failed_at + 20)                                          # not again straight away
            self.assertEqual(len(calls), tried)
            answers["hotspot"] = (0, "Device 'wlan0' successfully activated")
            net.tick(0, net.failed_at + 50)
            self.assertTrue(net.hotspot and net.problem is None)
            self.assertIn(["nmcli", "connection", "modify", "sofa-box-setup", "802-11-wireless-security.pmf", "disable"], calls)
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
        self.assertEqual(p.starting_text(1), "Resuming The Expanse at 1:02:05…")
        self.assertIn("Sofa is getting it ready for the box from where you left off", p.starting_text(4))
        self.assertIn("Back stops it", p.starting_text(30))
        p.payload = {"title": "A private title", "adult": True, "start": 0, "url": "http://sofa/media/x/file"}
        self.assertEqual(p.starting_text(5), "Starting…")                       # no adult titles on the screen

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
        self.assertEqual((said[0][0], said[0][2]), ("show-text", 5000))
        return said[0][1]

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
            text = said[-1][1]
            for word in ("Options", "Subtitles", "Off", "Sound", "Speed", "Volume", "40%", "Close"):
                self.assertIn(word, text)
            p.menu_key("right")                                            # Subtitles: Off -> English
            self.assertIn(("set_property", "sid", 1), said)
            p.menu_key("right")
            self.assertIn(("set_property", "sid", 2), said)
            self.assertIn("Signs (forced)", said[-1][1])
            p.menu_key("down")                                             # Sound: English -> Spanish
            p.menu_key("ok")
            self.assertIn(("set_property", "aid", 2), said)
            p.menu_key("back")
            self.assertIn(("disable-section", "sofa-menu"), said)
            self.assertIsNone(p.menu)
            p.menu_key("ok")                                               # (closed: nothing)
        finally:
            a.playing, a.volume_now = real

    def test_the_banner(self):
        progs = [{"title": "Kids' WB {Feb 10, 2001}", "year": 2001, "ad": False}, {"title": "Ad", "ad": True},
                 {"title": "Fox Box", "year": 2002, "ad": False}]
        text = self.banner({"live": True, "title": "00s Saturday Mornings", "number": 4, "programs": progs}, 0)
        self.assertTrue(text.startswith("${osd-ass-cc/0}"))
        self.assertIn("4  {\\c&HFFFFFF&}00s Saturday Mornings", text)
        self.assertIn("Kids' WB (Feb 10, 2001) (2001)", text)             # (ASS's braces out of the title)
        self.assertIn("Next: Fox Box (2002)", text)
        text = self.banner({"live": True, "title": "00s Saturday Mornings", "number": 4, "programs": progs}, 1)
        self.assertIn("Commercials, then Fox Box (2002)", text)
        text = self.banner({"live": True, "title": "A free channel", "programs": []}, 0)
        self.assertNotIn("Next", text)


if __name__ == "__main__":
    unittest.main()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
