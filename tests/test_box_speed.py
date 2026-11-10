"""Sofa Box OS on a Raspberry Pi 3, quick to answer the remote: what the box measures itself (page by page, in the
report a box sends), app icons at the size Home draws them, and a press on Home that never makes or drops a layer
(each layer made is drawn again from nothing: on a Pi 3 that was most of a press's time)."""
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tests

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")
assert tests.ROOT


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(BOX, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


boxos = load("boxos")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def chrome():
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def get(url, timeout=10):
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read()


class Page:
    """One tab, over DevTools (the box's own WebSocket client)."""

    def __init__(self, devtools_port, url_part):
        for _ in range(100):
            try:
                tabs = json.loads(get("http://127.0.0.1:%d/json/list" % devtools_port)[2])
                tab = next(t for t in tabs if t["type"] == "page" and url_part in t["url"])
                break
            except (OSError, StopIteration, ValueError):
                time.sleep(0.2)
        else:
            raise AssertionError("no page with %s" % url_part)
        self.ws = boxos.WebSocket(tab["webSocketDebuggerUrl"])
        self.ws.sock.settimeout(30)
        self.n, self.events = 0, []

    def call(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                if "error" in m:
                    raise AssertionError(m["error"])
                return m.get("result", {})
            self.events.append(m)

    def value(self, expression):
        r = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        return r["result"].get("value")

    def press(self, key, code):
        for kind in ("rawKeyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": key, "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code})
        time.sleep(0.35)

    def layers(self):
        """The layers the page is drawn in now, by their size (one that draws something)."""
        self.events = []
        self.call("LayerTree.enable")
        for _ in range(50):
            self.value("document.documentElement.style.setProperty('--t', String(Math.random()))")   # (a frame, so the tree comes)
            tree = [e["params"]["layers"] for e in self.events if e.get("method") == "LayerTree.layerTreeDidChange" and e["params"].get("layers")]
            if tree:
                self.call("LayerTree.disable")
                return sorted("%dx%d" % (round(x["width"]), round(x["height"])) for x in tree[-1] if x.get("drawsContent"))
            time.sleep(0.1)
        raise AssertionError("no layer tree")

    def close(self):
        self.ws.close()


class SpeedReport(unittest.TestCase):
    """The report says how quickly each page answers: Home, its Settings, Sofa's pages, each on its own line."""

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

    def test_page_by_page(self):
        stats = {"home": {"presses": 50, "slow": 9, "worst": 410, "long": 4, "long_ms": 900, "pages": {
                    "home": {"presses": 40, "slow": 8, "worst": 410, "hist": [3, 6, 2, 0, 0], "wait": 300, "code": 100, "draw": 600},
                    "settings": {"presses": 10, "slow": 1, "worst": 120, "hist": [0, 1, 0, 0, 0], "wait": 0, "code": 20, "draw": 100}}},
                 "sofa": {"presses": 9, "slow": 0, "worst": 40, "long": 0, "long_ms": 0, "pages": {
                    "show": {"presses": 9, "slow": 0, "worst": 40, "hist": [0, 0, 0, 0, 0], "wait": 0, "code": 0, "draw": 0}}}}
        self.assertEqual(self.agent.smooth_lines(stats), [
            "  home: 50 presses, 9 slower than 0.1 s (slowest 0.41 s); 4 long tasks (0.9 s in all)",
            "    Home: 40 presses: 29 within 0.05 s, 32 within 0.1 s, 38 within 0.25 s; slowest 0.41 s; the slow ones' time: "
            "waiting for the page 30%, the key's own code 10%, drawing 60%",
            "    Settings: 10 presses: 9 within 0.05 s, 9 within 0.1 s, 10 within 0.25 s; slowest 0.12 s; the slow ones' time: "
            "waiting for the page 0%, the key's own code 17%, drawing 83%",
            "  sofa: 9 presses, 0 slower than 0.1 s (slowest 0.04 s); 0 long tasks (0.0 s in all)",
            "    sofa show: 9 presses: 9 within 0.05 s, 9 within 0.1 s, 9 within 0.25 s; slowest 0.04 s"])
        self.assertEqual(self.agent.smooth_lines("(the browser went away)"), [])        # (a report is never lost to it)

    def test_two_tabs_of_one_app(self):
        a = {"presses": 3, "slow": 1, "worst": 300, "long": 1, "long_ms": 80,
             "pages": {"home": {"presses": 3, "slow": 1, "worst": 300, "hist": [0, 0, 1, 0, 0], "wait": 10, "code": 20, "draw": 270}}}
        b = {"presses": 2, "slow": 0, "worst": 60, "long": 0, "long_ms": 0,
             "pages": {"home": {"presses": 2, "slow": 0, "worst": 60, "hist": [1, 0, 0, 0, 0], "wait": 0, "code": 0, "draw": 0},
                       "show": {"presses": 1, "slow": 0, "worst": 0, "hist": [0, 0, 0, 0, 0], "wait": 0, "code": 0, "draw": 0}}}
        m = boxos.merge_smooth(a, b)
        self.assertEqual((m["presses"], m["slow"], m["worst"], m["long_ms"]), (5, 1, 300, 80))
        self.assertEqual(m["pages"]["home"], {"presses": 5, "slow": 1, "worst": 300, "hist": [1, 0, 1, 0, 0], "wait": 10, "code": 20, "draw": 270})
        self.assertEqual(m["pages"]["show"]["presses"], 1)


class SmallIcons(unittest.TestCase):
    """Sites' icons are kept as they come (often 512 or 1024 pixels); Home asks for them at the size its tiles draw."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_made_once_at_that_size(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("no Pillow here (the box has it: python3-pil)")
        Image.new("RGBA", (512, 512), (230, 20, 40, 255)).save(os.path.join(self.dir, "netflix.png"))
        Image.new("RGBA", (120, 120), (0, 0, 0, 0)).save(os.path.join(self.dir, "tiny.png"))
        with open(os.path.join(self.dir, "logo.svg"), "w") as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
        small = boxos.small_icon(self.dir, "netflix.png", 192)
        self.assertEqual(os.path.dirname(small), os.path.join(os.path.realpath(self.dir), ".w192"))
        with Image.open(small) as im:
            self.assertEqual(im.size, (192, 192))
        made = os.path.getmtime(small)
        time.sleep(0.05)
        self.assertEqual(boxos.small_icon(self.dir, "netflix.png", 192), small)
        self.assertEqual(os.path.getmtime(small), made)                    # (kept: not made again)
        self.assertIsNone(boxos.small_icon(self.dir, "tiny.png", 192))      # small already: as it is
        self.assertIsNone(boxos.small_icon(self.dir, "logo.svg", 192))      # drawn at any size
        self.assertIsNone(boxos.small_icon(self.dir, "netflix.png", 500))   # (only the sizes Home asks for)
        self.assertIsNone(boxos.small_icon(self.dir, "../netflix.png", 192))
        self.assertIsNone(boxos.small_icon(self.dir, "gone.png", 192))


class BoxPagesSpeed(unittest.TestCase):
    """In a browser, with the box's agent: Home as a Raspberry Pi 3 has it (the light look)."""

    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.dir = tempfile.mkdtemp()
        conf, run = os.path.join(cls.dir, "conf"), os.path.join(cls.dir, "run")
        os.makedirs(os.path.join(conf, "icons"))
        os.makedirs(run)
        with open(os.path.join(run, "sofa-box-display"), "w") as f:
            f.write("SCALE=2\n")
        apps = []                                   # rows long enough to scroll, as on a box with its apps added
        for sid in ("netflix", "disney-plus", "prime-video", "max", "hulu", "crunchyroll", "twitch", "pluto", "tubi", "spotify"):
            apps.append(boxos.app_from_store(boxos.store_entry(sid)))
        apps[0]["icon_file"] = "netflix.png"
        with open(os.path.join(conf, "apps.json"), "w") as f:
            json.dump({"apps": apps, "order": [], "hidden": []}, f)
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": True, "weather": "off", "boot_sound": "off"}, f)
        with open(os.path.join(conf, "icons", "netflix.png"), "wb") as f:     # (a 1-pixel PNG: Home's tile asks for it)
            f.write(bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                                  "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"))
        cls.port, cls.devtools = free_port(), free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1920,1080",
                                       "--remote-debugging-port=%d" % cls.devtools, "--user-data-dir=" + os.path.join(cls.dir, "profile"),
                                       cls.base + "/box/home"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cls.dir, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(cls.port), SOFA_BOX_SLOW="1",
                                              SOFA_BOX_DEVTOOLS=str(cls.devtools), XDG_RUNTIME_DIR=run, SOFA_BOX_UINPUT="0", SOFA_BOX_ICONS="0",
                                              SOFA_BOX_HOTSPOT="0", SOFA_BOX_CERTS="0", SOFA_BOX_NEWEST="0", SOFA_BOX_CAPTIVE_PORT="0",
                                              SOFA_BOX_REMOTE_PORT=str(free_port())))
        for _ in range(300):
            try:
                if json.loads(get(cls.base + "/box/api/apps", 5)[2]).get("devtools"):
                    break
            except (OSError, ValueError):
                pass
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

    def home(self):
        p = self.page
        p.call("Page.navigate", {"url": self.base + "/box/home?t=%d#/" % time.time()})
        for _ in range(100):
            if p.value("!!document.querySelector('.watch-row .tile') && document.documentElement.classList.contains('lite')"):
                break
            time.sleep(0.1)
        time.sleep(1.5)                                   # (the opening, then the page as it stays)
        return p

    def test_a_press_keeps_the_layers(self):
        """Along a row and down to the next, the page stays in the same layers: the row in focus isn't split into new
        ones around the tile in front (it was, on every press, each drawn again), and nothing is drawn for a background
        that never shows (the page's own background is over it)."""
        p = self.home()
        p.press("ArrowDown", 40)                          # (into the Watch row)
        first = p.layers()
        for key, code in (("ArrowRight", 39), ("ArrowRight", 39), ("ArrowRight", 39), ("ArrowLeft", 37)):
            p.press(key, code)
            self.assertEqual(p.layers(), first, "a press on Home made or dropped a layer")
        self.assertIn("tile", p.value("document.activeElement.className"))
        self.assertEqual(p.value("getComputedStyle(document.querySelector('.bg')).display"), "none")

    def test_measured_page_by_page(self):
        """The box's measure is in Home from the start and stays when the page loads again (it was gone after a reload:
        the report then had nothing to say), and counts each part of Home on its own."""
        p = self.home()
        for _ in range(50):
            if p.value("typeof window.__sofaSmooth") == "function":
                break
            time.sleep(0.1)
        p.press("ArrowDown", 40)
        p.press("ArrowRight", 39)
        p.value("location.hash = '#/settings'")
        time.sleep(0.8)
        p.press("ArrowDown", 40)
        s = json.loads(p.value("__sofaSmooth()"))
        self.assertEqual(s["pages"]["home"]["presses"], 2)
        self.assertEqual(s["pages"]["settings"]["presses"], 1)
        self.assertEqual(s["presses"], 3)
        self.assertEqual(len(s["pages"]["home"]["hist"]), 5)

    def test_icons_at_tile_size(self):
        """App icons are asked for at about the size the tiles draw them, and kept by the browser (their address
        changes with the picture); Home's own files are checked each time, as before."""
        status, head, body = get(self.base + "/box/icons/netflix.png?v=7&w=192")
        self.assertEqual((status, head.get("Content-Type")), (200, "image/png"))
        self.assertIn("max-age=31536000", head.get("Cache-Control", ""))
        self.assertTrue(body.startswith(b"\x89PNG"))
        self.assertEqual(get(self.base + "/box/icons/netflix.png")[1].get("Cache-Control"), "no-store, no-cache")
        self.assertEqual(get(self.base + "/box/home/home.js")[1].get("Cache-Control"), "no-store, no-cache")
        self.assertEqual(get(self.base + "/box/api/apps")[1].get("Cache-Control"), "no-store")
        for bad in ("/box/icons/..%2Fsettings.json?w=192", "/box/icons/nothing.png?w=192"):
            with self.assertRaises(urllib.error.HTTPError) as e:
                get(self.base + bad)
            self.assertEqual(e.exception.code, 404)
        p = self.home()
        for _ in range(50):                                # (what the page asked for, whatever the tile then shows)
            asked = p.value("performance.getEntriesByType('resource').map(e => e.name).filter(n => n.includes('/box/icons/'))")
            if asked:
                break
            time.sleep(0.1)
        self.assertRegex(asked[0], r"/box/icons/netflix\.png\?v=\d+&w=192$")
