"""Live TV's page in a browser: one look for all of it. The bar of eras with Live now as one of them, and today's
channels on a dial in the guide's own shape (a row a channel, its number, one bar), light enough for a Raspberry Pi 3:
no picture in a row, rows drawn as they come near, the page itself never scrolling under the remote."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import auth, config, live, store, web
from tests.test_box_speed import Page, chrome, free_port

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUPS = ("Documentary", "Kids", "Movies", "Music", "News")
NAMES = ["%s %03d" % (GROUPS[i % len(GROUPS)], i) for i in range(150)]
KEY = {"ArrowDown": 40, "ArrowUp": 38, "ArrowLeft": 37, "ArrowRight": 39, "Enter": 13}


class Air(BaseHTTPRequestHandler):
    base = ""

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/list.m3u":
            body, ctype = "#EXTM3U\n" + "".join('#EXTINF:-1 group-title="%s",%s\n%s/c%d/index.m3u8\n' % (n.split()[0], n, self.base, i)
                                                for i, n in enumerate(NAMES)), "audio/x-mpegurl"
        elif self.path.endswith("/index.m3u8"):
            body, ctype = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nseg1.ts\n", "application/vnd.apple.mpegurl"
        else:
            body, ctype = "G" * 188, "video/mp2t"
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class TheDial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.up = ThreadingHTTPServer(("127.0.0.1", 0), Air)
        Air.base = "http://127.0.0.1:%d" % cls.up.server_address[1]
        threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.before = {k: config.get(k) for k in ("offline", "live_playlists", "live_check", "archive_channels")}
        config.update({"offline": False, "live_check": True, "archive_channels": False,      # (Sofa's own lineup off:
                       "live_playlists": [{"name": "Tuner", "url": Air.base + "/list.m3u"}]})   # nothing from the internet)
        for name, admin in (("dial-admin", True), ("dial-viewer", False)):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123", admin=admin)
        live._health.clear()
        live._streak.clear()
        live._health_state.update(loaded=True, wanted=0.0, asked={}, dirty=False)
        assert live.refresh(force=True) == len(NAMES)
        cls.ids = {c["name"]: c["id"] for c in live.all_channels()}
        cls.dir = tempfile.mkdtemp(prefix="sofa-dial-")
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--mute-audio",
                                       "--window-size=1280,720", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), "about:blank"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.page = Page(cls.devtools, "about:blank")
        cls.page.call("Page.enable")
        cls.who = None

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        cls.chrome.terminate()
        try:
            cls.chrome.wait(10)
        except subprocess.TimeoutExpired:
            cls.chrome.kill()
        shutil.rmtree(cls.dir, ignore_errors=True)
        store.ex("DELETE FROM live_favorites WHERE channel IN (%s)" % ",".join("?" * len(cls.ids)), *cls.ids.values())
        config.update(cls.before)
        live._health.clear()
        live._health_state.update(wanted=0.0, asked={}, dirty=False)
        live.refresh()
        cls.httpd.shutdown()
        cls.up.shutdown()

    def setUp(self):
        live._health.clear()
        store.ex("DELETE FROM live_favorites WHERE channel IN (%s)" % ",".join("?" * len(self.ids)), *self.ids.values())

    def open(self, who="dial-viewer", tv=True, width=1280, height=720, storage=""):
        p = self.page
        p.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 700})
        p.call("Page.navigate", {"url": self.base + "/client/manifest.webmanifest"})
        time.sleep(0.4)
        if who != type(self).who:
            p.value("fetch('/api/logout',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},body:'{}'}).then(()=>1,()=>0)")
            status = p.value("fetch('/api/login',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},"
                             "body:JSON.stringify({name:%s,password:'password123'})}).then(r=>r.status)" % json.dumps(who))
            self.assertEqual(status, 200)
            type(self).who = who
        p.value("localStorage.clear(); sessionStorage.setItem('sofaPicked','1'); localStorage.setItem('sofa.tv','%s'); %s; 1"
                % ("true" if tv else "false", storage or "0"))
        p.call("Page.navigate", {"url": self.base + "/?t=%f#/live" % time.time()})
        self.until("document.querySelectorAll('#dRows .g-row').length > 0")
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
                                                               "nativeVirtualKeyCode": code},
                                                              **({"text": "\r"} if kind == "keyDown" else {})))
        time.sleep(0.3)

    def rows(self):
        return self.page.value("[...document.querySelectorAll('#dRows .g-row')].map(r => [r.querySelector('.g-ch b').textContent,"
                               " r.querySelector('.g-ch span').textContent, r.className])")

    def test_one_look_the_bar_of_eras_then_the_dial(self):
        p = self.open()
        # the bar of eras is there with Sofa's own lineup off, Live now chosen in it
        self.assertEqual(p.value("[...document.querySelectorAll('.eras [data-era]')].map(b => b.dataset.era + ':' + b.getAttribute('aria-selected'))"),
                         ["now:true"])
        rows = self.rows()
        self.assertEqual(len(rows), 60)                                           # the first rows; the rest as they come near
        numbers = [int(r[0]) for r in rows]
        self.assertEqual(numbers[0], 101)
        self.assertEqual(len(set(numbers)), len(numbers))
        self.assertEqual(rows[0][1], sorted(NAMES)[0])
        self.assertEqual(p.value("document.querySelectorAll('#dRows img').length"), 0)   # no picture in a row
        self.assertFalse(p.value("!!document.querySelector('.channels, .chan')"))  # the grid of cards is gone
        # the channel in view, up top; the remote starts on the dial
        self.assertEqual(p.value("document.querySelector('#dNow h2').textContent"), rows[0][1])
        self.assertEqual(p.value("document.activeElement.dataset.live"), self.ids[rows[0][1]])
        self.assertEqual(p.value("[...document.querySelectorAll('#dial .chips [data-group]')].map(b => b.textContent)"), ["All"] + list(GROUPS))
        # the dial ends on the screen: under the remote only its rows scroll, never the page
        fit = p.value("(() => { const r = document.querySelector('#dRows').getBoundingClientRect(); return [r.bottom <= innerHeight, r.height >= 160, scrollY]; })()")
        self.assertEqual(fit, [True, True, 0])

    def test_the_remote_moves_along_the_dial_and_the_page_stays_put(self):
        p = self.open()
        self.press("ArrowDown", 64)
        rows = self.rows()
        self.assertGreater(len(rows), 60)                                         # the next rows were drawn on the way
        at = p.value("[...document.querySelectorAll('#dRows [data-live]')].indexOf(document.activeElement)")
        self.assertEqual(at, 64)
        self.assertEqual(p.value("document.querySelector('#dNow h2').textContent"), rows[64][1])
        self.assertEqual(p.value("scrollY"), 0)
        box = p.value("(() => { const r = document.activeElement.getBoundingClientRect(); return [r.top, r.bottom, innerHeight]; })()")
        self.assertTrue(0 <= box[0] and box[1] <= box[2], box)                    # the focused row is on the screen
        self.press("ArrowRight")                                                  # the star, then OK: a favourite
        self.assertTrue(p.value("document.activeElement.classList.contains('star')"))
        self.press("Enter")
        self.until("document.activeElement.getAttribute('aria-pressed') === 'true'")
        cid = self.ids[rows[64][1]]
        self.until("true", 1)
        self.assertTrue(any(r["channel"] == cid for r in store.q("SELECT channel FROM live_favorites")))
        self.press("ArrowRight")                                                  # the row's end: stays
        self.assertTrue(p.value("document.activeElement.classList.contains('star')"))
        self.press("ArrowLeft")
        self.assertEqual(p.value("document.activeElement.dataset.live"), cid)
        self.press("ArrowUp", 64)
        self.assertEqual(p.value("[...document.querySelectorAll('#dRows [data-live]')].indexOf(document.activeElement)"), 0)
        self.press("ArrowUp")                                                     # off the top: the groups, not nowhere
        self.assertFalse(p.value("!!document.activeElement.closest('#dRows')"))
        self.assertTrue(p.value("document.activeElement !== document.body"))

    def test_a_channels_number_typed_tunes_to_it(self):
        p = self.open()
        want = self.rows()[4]
        for d in want[0]:
            self.press(d)
        self.until("window.SofaVideoOpen && window.SofaVideoOpen()", 8)
        self.assertIn(want[1], p.value("document.querySelector('.p-show').textContent"))

    def test_the_ones_that_dont_answer_are_out_and_an_admin_can_see_them(self):
        gone = sorted(NAMES)[1:4]
        for name in gone:
            live.mark(self.ids[name], False, "it answered 404", at_once=True)
        p = self.open()
        names = [r[1] for r in self.rows()]
        self.assertFalse(set(gone) & set(names))
        self.assertFalse(p.value("!!document.querySelector('.live-gone')"))        # (how many: the admin's to know)
        p = self.open("dial-admin")
        self.assertEqual(p.value("document.querySelector('.live-gone').firstChild.textContent.trim()"),
                         "3 channels that don't answer are left out.")
        self.assertFalse(set(gone) & {r[1] for r in self.rows()})
        p.value("document.querySelector('[data-live-down]').click()")
        self.until("document.querySelectorAll('#dRows .g-row.down').length === 3")
        self.assertEqual(sorted(r[1] for r in self.rows() if "down" in r[2]), gone)
        self.assertIn("Showing 3 channels", p.value("document.querySelector('.live-gone').textContent"))
        p.value("document.querySelector('[data-live-down]').click()")
        self.until("document.querySelectorAll('#dRows .g-row').length > 0 && !document.querySelector('#dRows .g-row.down')")

    def test_a_group_a_search_and_the_starred_ones(self):
        cid = self.ids["Music 003"]
        uid = store.q1("SELECT id FROM users WHERE name = 'dial-viewer'")["id"]
        store.ex("INSERT OR IGNORE INTO live_favorites (user_id, channel) VALUES (?,?)", uid, cid)
        p = self.open()
        self.assertEqual(p.value("[...document.querySelectorAll('.eras [data-era]')].map(b => b.dataset.era)"), ["now", "fav"])
        p.value("document.querySelector('#dial [data-group=\"Music\"]').click()")
        self.until("document.querySelector('#dial [data-group=\"Music\"]').getAttribute('aria-pressed') === 'true'")
        self.assertEqual({r[1].split()[0] for r in self.rows()}, {"Music"})
        p.value("(() => { const i = document.querySelector('#liveSearch'); i.focus(); i.value = 'news 01'; i.dispatchEvent(new Event('input', { bubbles: true })); })()")
        self.until("document.querySelectorAll('#dRows .g-row').length === 2")
        self.assertEqual([r[1] for r in self.rows()], ["News 014", "News 019"])
        p.value("document.querySelector('[data-era=fav]').click()")
        self.until("document.querySelectorAll('#dRows .g-row').length === 1")
        self.assertEqual(self.rows()[0][1], "Music 003")
        self.assertEqual(p.value("document.querySelector('#dRows .star').getAttribute('aria-pressed')"), "true")

    def test_on_a_phone_the_row_carries_the_name(self):
        p = self.open(tv=False, width=390, height=780)
        shown = p.value("(() => { const r = document.querySelector('#dRows .g-row'); return [getComputedStyle(r.querySelector('.d-name')).display,"
                        " getComputedStyle(r.querySelector('.g-ch span')).display, document.querySelector('#dRows').style.maxHeight,"
                        " document.documentElement.scrollWidth <= innerWidth + 1]; })()")
        self.assertEqual([shown[0] != "none"] + shown[1:], [True, "none", "", True])   # (the name in the bar; the rows as long as the list)

    def test_a_channel_that_didnt_play_is_told_to_sofa(self):
        with open(os.path.join(ROOT, "client", "app.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertEqual(js.count('api("/api/live/failed/" + ch.id, {})'), 2)      # the page's player, and the box's
        self.assertNotIn("channelCard", js)


if __name__ == "__main__":
    unittest.main()
