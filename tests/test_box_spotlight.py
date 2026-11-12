"""Sofa Box OS 1.1.73: Home as Spotlight, a TV's own home screen.

The owner tried a live mock-up of three layouts and picked Spotlight: the picture behind Home is whatever the remote is
on (the show you were watching, a game playing, an app's own icon on its colour), its name and a line about it over
the picture, rows below. Classic, the Home before it, stays a choice in Settings. On a Pi 3 (the light look) the picture
and words change once the remote has rested, so a press still draws only the ring (tests/test_box_speed.py)."""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.test_box_speed import BOX, Page, boxos, chrome, free_port, get

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
ITEMS = [{"id": "e1", "title": "Harbour Lights", "sub": "S2 E4 · The Night Ferry", "art": "/art/e1.png", "backdrop": "/art/b1.png", "pct": 58,
          "hash": "#/show/1", "play": "#/play/e1"},
         {"id": "m2", "title": "Low Tide", "sub": "2023", "art": "/art/m2.png", "backdrop": "/art/b2.png", "pct": 31, "hash": "#/movie/2", "play": "#/play/m2"}]
STUB = r"""(() => { const real = window.fetch.bind(window);
  window.fetch = (url, opts) => String(url).includes("/box/api/sofa/continue")
    ? Promise.resolve(new Response(JSON.stringify(%s), { status: 200, headers: { "Content-Type": "application/json" } })) : real(url, opts); })();"""


def solid_png(n, rgb):
    """An n x n picture of one colour (an app's icon that is really there: the 1-pixel one reads as empty)."""
    raw = b"".join(b"\x00" + bytes(rgb) * n for _ in range(n))
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class Art(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(PNG)))
        self.end_headers()
        self.wfile.write(PNG)


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-Sofa-Box": "1"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=20) as r:
        return json.loads(r.read())


class Spotlight(unittest.TestCase):
    """The full look (a Pi 4 or 5, a PC)."""
    SLOW = "0"

    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.art = ThreadingHTTPServer(("127.0.0.1", 0), Art)
        threading.Thread(target=cls.art.serve_forever, daemon=True).start()
        cls.dir = tempfile.mkdtemp()
        conf, run = os.path.join(cls.dir, "conf"), os.path.join(cls.dir, "run")
        os.makedirs(os.path.join(conf, "icons"))
        os.makedirs(run)
        with open(os.path.join(run, "sofa-box-display"), "w") as f:
            f.write("SCALE=2\n")
        apps = [boxos.app_from_store(boxos.store_entry(sid)) for sid in ("edge-music", "netflix", "youtube-tv")]
        apps[1]["icon_file"] = "netflix.png"
        with open(os.path.join(conf, "icons", "netflix.png"), "wb") as f:
            f.write(solid_png(64, (229, 9, 20)))
        with open(os.path.join(conf, "apps.json"), "w") as f:
            json.dump({"apps": apps, "order": [], "hidden": []}, f)
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": True, "weather": "off", "boot_sound": "off"}, f)
        cls.port, cls.devtools = free_port(), free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1920,1080",
                                       "--remote-debugging-port=%d" % cls.devtools, "--user-data-dir=" + os.path.join(cls.dir, "profile"), "about:blank"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cls.dir, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(cls.port), SOFA_BOX_SLOW=cls.SLOW,
                                              SOFA_BOX_DEVTOOLS="0", XDG_RUNTIME_DIR=run, SOFA_BOX_UINPUT="0", SOFA_BOX_ICONS="0",
                                              SOFA_BOX_HOTSPOT="0", SOFA_BOX_CERTS="0", SOFA_BOX_NEWEST="0", SOFA_BOX_CAPTIVE_PORT="0",
                                              SOFA_BOX_REMOTE_PORT=str(free_port())))
        for _ in range(300):
            try:
                get(cls.base + "/box/state", 2)
                break
            except OSError:
                time.sleep(0.2)
        cls.page = Page(cls.devtools, "about:blank")
        cls.page.call("Page.enable")
        cont = {"found": True, "name": "Living room", "server": "home", "where": "home", "signedIn": True,
                "base": "http://127.0.0.1:%d" % cls.art.server_address[1], "items": ITEMS}
        cls.page.call("Page.addScriptToEvaluateOnNewDocument", {"source": STUB % json.dumps(cont)})

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        for p in (cls.agent, cls.chrome):
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        cls.art.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def until(self, expression, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            v = self.page.value(expression)
            if v:
                return v
            time.sleep(0.1)
        self.fail("never: " + expression)

    def home(self):
        p = self.page
        p.call("Page.navigate", {"url": self.base + "/box/home?t=%f#/" % time.time()})
        self.until("!!document.querySelector('#view .spt .tile') && !!document.querySelector('#sptText .spt-title')")
        time.sleep(1.2)                                   # (the opening, then the page as it stays)
        return p

    def title(self):
        return self.page.value("document.querySelector('#sptText .spt-title').textContent")

    def picture(self):
        return self.page.value("(l => !l ? '' : l.querySelector('.spt-field') ? 'field' : l.querySelector('img') ? l.querySelector('img').getAttribute('src') : '')"
                               "(document.querySelector('#sptBg .spt-layer.on'))")

    def press(self, key, code, rest=None):
        self.page.press(key, code)
        time.sleep(rest if rest is not None else 1.5 if self.SLOW == "1" else 0.7)

    def test_home_opens_on_spotlight(self):
        p = self.home()
        self.assertTrue(p.value("document.documentElement.classList.contains('spt-on')"))
        self.assertEqual(p.value("document.activeElement.dataset.app"), "sofa")              # the remote starts on Sofa
        self.assertEqual(self.title(), "Harbour Lights")                                    # and Sofa's picture is what you were watching
        self.assertEqual(p.value("document.querySelector('#sptText .spt-kicker').textContent"), "Living room")
        self.assertIn("/art/b1.png?w=%d" % (960 if self.SLOW == "1" else 1600), self.picture())
        self.assertTrue(p.value("!!document.querySelector('#topExtra #sptClock')"))
        self.assertEqual(p.value("[scrollY, getComputedStyle(document.body).overflowY]"), [0, "hidden"])
        self.assertEqual(p.value("[...document.querySelectorAll('#view .spt-row')].map(r => r.dataset.row)"), ["apps", "continue", "games"])

    def test_the_picture_and_words_follow_the_remote(self):
        p = self.home()
        self.press("ArrowRight", 39)
        self.assertEqual(self.title(), "Live TV")
        self.assertEqual(self.picture(), "field")                                           # an app: its icon on its colour
        self.press("ArrowDown", 40)                                                         # Continue watching
        self.assertEqual(p.value("document.activeElement.dataset.cw"), "e1")
        self.assertEqual(self.title(), "Harbour Lights")
        self.assertEqual(p.value("document.querySelector('#sptText .spt-kicker').textContent"), "Continue watching")
        self.press("ArrowRight", 39)
        self.assertEqual(self.title(), "Low Tide")
        self.assertIn("/art/b2.png", self.picture())
        rows = p.value("(r => [r.scrollTop, document.activeElement.closest('.spt-row').offsetTop, scrollY])(document.querySelector('#sptRows'))")
        self.assertEqual(rows[0], rows[1])                                                  # the row in focus on its line
        self.assertEqual(rows[2], 0)                                                        # and the page itself never scrolls
        self.press("ArrowDown", 40)                                                         # the games: each photographed playing
        game = p.value("document.activeElement.dataset.game")
        self.assertEqual(self.picture(), "/box/home/art/games/%s.jpg" % game)
        status, headers, body = get(self.base + "/box/home/art/games/%s.jpg" % game)
        self.assertEqual((status, body[:2]), (200, b"\xff\xd8"))
        self.press("ArrowUp", 38)
        self.press("ArrowUp", 38)
        self.assertEqual(p.value("document.querySelector('#sptRows').scrollTop"), 0)

    def test_the_box_s_own_apps_have_their_own_icons(self):
        p = self.home()
        srcs = p.value("Object.fromEntries([...document.querySelectorAll('#view .spt-app[data-app]')].filter(t => t.querySelector('img.drawn-ic'))"
                       ".map(t => [t.dataset.app, t.querySelector('img.drawn-ic').getAttribute('src')]))")
        for app in ("sofa", "live", "browser", "store", "games", "files", "settings", "edge-music"):
            self.assertEqual(srcs.get(app), "/box/home/art/icons/glossy/192/%s.webp" % app)    # Glossy, unless another is picked
        self.assertNotIn("netflix", srcs)                                                   # another company's: its own icon
        self.assertNotIn("youtube-tv", srcs)
        status, headers, body = get(self.base + srcs["sofa"])
        self.assertEqual((status, body[:4], body[8:12]), (200, b"RIFF", b"WEBP"))
        self.until("(i => i.complete && i.naturalWidth === 192)(document.querySelector('#view .spt-app[data-app=sofa] img.drawn-ic'))")

    def test_other_companies_apps_keep_their_logo_in_the_style(self):
        p = self.home()                                   # Netflix: its own icon, untouched, in the Glossy housing
        tile = "document.querySelector('#view .spt-app[data-app=netflix] .ic')"
        self.assertTrue(p.value(tile + ".classList.contains('framed')"))
        self.assertTrue(p.value(tile + ".querySelector('img').getAttribute('src').startsWith('/box/icons/netflix.png')"))
        under = p.value("getComputedStyle(%s).backgroundImage" % tile)
        over = p.value("getComputedStyle(%s, '::after').backgroundImage" % tile)
        self.assertIn("/box/home/art/icons/glossy/192/frame-under.webp", under)
        self.assertIn("/box/home/art/icons/glossy/192/frame-over.webp", over)
        for part in ("under", "over"):
            status, headers, body = get(self.base + "/box/home/art/icons/glossy/192/frame-%s.webp" % part)
            self.assertEqual((status, body[8:12]), (200, b"WEBP"))
        box = p.value("(r => [r.width, r.height])(%s.getBoundingClientRect())" % tile)
        img = p.value("(r => [r.width, r.height])(%s.querySelector('img').getBoundingClientRect())" % tile)
        self.assertAlmostEqual(img[0] / box[0], 0.76, delta=0.02)                          # (the screen: 12% in from each side)
        try:
            post(self.base + "/box/api/settings", {"icon_style": "original"})               # the apps' own: as before, no housing
            p = self.home()
            self.assertFalse(p.value("!!document.querySelector('#view .framed')"))
        finally:
            post(self.base + "/box/api/settings", {"icon_style": "glossy"})

    def test_the_icons_come_in_styles(self):
        p = self.page                                                                       # Settings → Home screen → Icons
        p.call("Page.navigate", {"url": self.base + "/box/home?t=%f#/settings" % time.time()})
        self.until("!!document.querySelector('[data-set-tab=home]')")
        time.sleep(0.8)                                   # (the tab the focus lands on opens a moment later: then this one)
        p.value("document.querySelector('[data-set-tab=home]').click(); 1")
        self.until("document.querySelectorAll('.iconset').length === 6")
        self.assertEqual(p.value("document.querySelector('.iconset[aria-pressed=true]').dataset.value"), "glossy")
        self.assertEqual(p.value("[...document.querySelectorAll('.iconset[data-value=sticker] img')].map(i => i.getAttribute('src')).join()"),
                         "/box/home/art/icons/sticker/192/sofa.webp,/box/home/art/icons/sticker/192/live.webp,/box/home/art/icons/sticker/192/games.webp")
        try:
            p.value("document.querySelector('.iconset[data-value=pixel]').click(); 1")
            self.until("(b => b && b.dataset.value === 'pixel')(document.querySelector('.iconset[aria-pressed=true]'))")
            self.assertEqual(json.loads(get(self.base + "/box/api/apps")[2])["icon_style"], "pixel")
            p = self.home()
            self.assertEqual(p.value("document.querySelector('#view .spt-app[data-app=sofa] img.drawn-ic').getAttribute('src')"),
                             "/box/home/art/icons/pixel/192/sofa.webp")
            self.assertEqual(p.value("document.documentElement.dataset.icons"), "pixel")
            post(self.base + "/box/api/settings", {"icon_style": "original"})               # the apps' own: Sofa's own mark again
            p = self.home()
            self.assertFalse(p.value("!!document.querySelector('#view img.drawn-ic')"))
            self.assertTrue(p.value("!!document.querySelector('#view .spt-app[data-app=sofa] .ic svg')"))
            post(self.base + "/box/api/settings", {"icon_style": "chrome"})                 # (not a style: left as it was)
            self.assertEqual(json.loads(get(self.base + "/box/api/apps")[2])["icon_style"], "original")
        finally:
            post(self.base + "/box/api/settings", {"icon_style": "glossy"})

    def test_classic_is_a_choice(self):
        post(self.base + "/box/api/settings", {"home_layout": "sideways"})                  # (not a layout: left as it was)
        self.assertEqual(json.loads(get(self.base + "/box/api/apps")[2])["home_layout"], "spotlight")
        post(self.base + "/box/api/settings", {"home_layout": "classic"})
        try:
            p = self.page
            p.call("Page.navigate", {"url": self.base + "/box/home?t=%f#/" % time.time()})
            self.until("!!document.querySelector('#view .mast')")
            self.assertFalse(p.value("document.documentElement.classList.contains('spt-on')"))
            self.assertEqual(p.value("document.querySelector('#topExtra').innerHTML"), "")
            self.assertTrue(p.value("!!document.querySelector('#view .mast img.drawn-ic, #view .watch-row img.drawn-ic')"))   # (the box's icons there too)
        finally:
            post(self.base + "/box/api/settings", {"home_layout": "spotlight"})


class SpotlightOnAPi3(Spotlight):
    """The light look (a Pi 3): the same, and the words and picture wait for the remote to rest."""
    SLOW = "1"

    def test_the_words_wait_for_the_remote_to_rest(self):
        p = self.home()
        self.assertTrue(p.value("document.documentElement.classList.contains('lite')"))
        p.value("window.__changes = 0; new MutationObserver(() => window.__changes++).observe(document.querySelector('#sptText'), { childList: true }); 1")
        for _ in range(3):                                                                  # three quick presses along the row
            for kind in ("rawKeyDown", "keyUp"):
                p.call("Input.dispatchKeyEvent", {"type": kind, "key": "ArrowRight", "code": "ArrowRight", "windowsVirtualKeyCode": 39, "nativeVirtualKeyCode": 39})
            time.sleep(0.12)
        self.assertEqual(self.title(), "Harbour Lights")                                    # not yet: the remote is moving
        time.sleep(1.9)
        self.assertEqual(p.value("window.__changes"), 1)                                    # once it rests, drawn once
        self.assertEqual(self.title(), p.value("document.activeElement.querySelector('b').textContent"))
        layers = p.value("[...document.querySelectorAll('#sptBg .spt-layer')].map(l => l.classList.contains('on') ? 'on' : l.innerHTML.length)")
        self.assertIn("on", layers)
        self.assertIn(0, layers)                                                            # the picture behind it let go of


    def test_what_resting_costs(self):
        """A press draws only its ring (test_box_speed). Once the remote rests, the words and the picture are drawn: once,
        in the layers that were there already (none made, none dropped)."""
        p = self.home()
        p.press("ArrowDown", 40)
        time.sleep(1.6)
        before = p.layers()
        for _ in range(4):                                                                  # (a page come to rest first)
            if not p.drawn_again(lambda: None, 0.5):
                break
        drawn = p.drawn_again(lambda: p.press("ArrowRight", 39), 1.8)
        print("\n    resting after a press on a Pi 3's look: %d pieces drawn in all" % len(drawn), file=sys.stderr)
        self.assertGreater(len(drawn), 2)                                                   # (the picture and words did come)
        self.assertLessEqual(len(drawn), 64)                                                # a screen's picture and the words, once
        self.assertEqual(p.layers(), before)


class Pieces(unittest.TestCase):
    def test_every_web_game_has_its_photograph(self):
        with open(os.path.join(BOX, "games", "games.json"), encoding="utf-8") as f:
            ids = {g["id"] for g in json.load(f)["games"]}
        with open(os.path.join(BOX, "home", "home.js"), encoding="utf-8") as f:
            js = f.read()
        listed = set(re.findall(r'"([a-z0-9-]+)"', js[js.index("const GAME_ART"):js.index("]);", js.index("const GAME_ART"))]))
        self.assertEqual(listed, ids)
        for g in ids:
            path = os.path.join(BOX, "home", "art", "games", g + ".jpg")
            with open(path, "rb") as f:
                self.assertEqual(f.read(2), b"\xff\xd8", g)
            self.assertLess(os.path.getsize(path), 160000, g)

    def own_icons(self):
        with open(os.path.join(BOX, "home", "home.js"), encoding="utf-8") as f:
            js = f.read()
        ids = set(re.findall(r'"([a-z0-9-]+)"', js[js.index("const OWN_ICONS"):js.index("]);", js.index("const OWN_ICONS"))]))
        styles = re.findall(r'\["([a-z]+)", "[^"]+"\]', js[js.index("const ICON_STYLES"):js.index("]];", js.index("const ICON_STYLES")) + 2])
        return ids, styles

    def test_the_box_s_icons_are_for_the_box_and_edgeventure_only(self):
        ids, styles = self.own_icons()
        with open(os.path.join(BOX, "store.json"), encoding="utf-8") as f:
            ours = {a["id"] for sec in json.load(f)["sections"] if sec["id"] == "ours" for a in sec["apps"]}
        own = {"sofa", "live", "browser", "store", "games", "files", "settings"}
        self.assertEqual(ids - own - ours, set())                                           # no other company's logo redrawn
        self.assertTrue(own <= ids)

    def test_every_style_has_every_icon(self):
        ids, styles = self.own_icons()
        with open(os.path.join(BOX, "sofa-box-agent.py"), encoding="utf-8") as f:
            agent = f.read()
        self.assertEqual(styles, re.findall(r'"([a-z]+)"', re.search(r'"icon_style": \(([^)]*)\)', agent).group(1)))   # Home's and the agent's
        self.assertEqual(styles[-1], "original")                                            # (the apps' own: no pictures)
        here = os.path.join(BOX, "home", "art", "icons")
        self.assertEqual(sorted(os.listdir(here)), sorted(styles[:-1]))
        for style in styles[:-1]:
            for size, most in ((192, 30000), (512, 90000)):
                folder = os.path.join(here, style, str(size))
                self.assertEqual({n[:-5] for n in os.listdir(folder)}, ids | {"frame-under", "frame-over"}, folder)
                for app in ids | {"frame-under", "frame-over"}:
                    with open(os.path.join(folder, app + ".webp"), "rb") as f:
                        head = f.read(30)
                    self.assertEqual((head[:4], head[8:16]), (b"RIFF", b"WEBPVP8X"), (style, size, app))   # (VP8X: with see-through)
                    self.assertEqual((int.from_bytes(head[24:27], "little") + 1, int.from_bytes(head[27:30], "little") + 1), (size, size))
                    self.assertLess(os.path.getsize(os.path.join(folder, app + ".webp")), most, (style, size, app))

    def test_the_pictures_are_made_from_the_drawings(self):
        if not shutil.which("node"):
            raise unittest.SkipTest("no node here")
        ids, styles = self.own_icons()
        made = json.loads(subprocess.run(["node", os.path.join(os.path.dirname(os.path.dirname(BOX)), "tools", "box-icons", "sheet.js"), "--list"],
                                         capture_output=True, text=True, check=True).stdout)
        self.assertEqual((set(made["ids"]), made["styles"], made["frames"]), (ids, styles[:-1], ["frame-under", "frame-over"]))

    def test_the_housings_and_home_agree_where_the_logo_sits(self):
        if not shutil.which("node"):
            raise unittest.SkipTest("no node here")
        here = os.path.join(os.path.dirname(os.path.dirname(BOX)), "tools", "box-icons", "frames.js")
        screen = json.loads(subprocess.run(["node", "-e", "process.stdout.write(JSON.stringify(require(%s).SCREEN))" % json.dumps(here)],
                                           capture_output=True, text=True, check=True).stdout)
        with open(os.path.join(BOX, "home", "home.css"), encoding="utf-8") as f:
            css = f.read()
        for style, (pad, rad) in screen.items():
            m = re.search(r'html\[data-icons="%s"\] \.framed \{ --pad: ([\d.]+)%%; --rad: ([\d.]+)%%?;' % style, css)
            self.assertTrue(m, style)
            self.assertEqual((float(m.group(1)) / 100, float(m.group(2)) / 100), (pad, rad), style)


if __name__ == "__main__":
    unittest.main()
