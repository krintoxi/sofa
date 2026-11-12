"""Sofa Box OS 1.1.81: what the owner found on a Pi 3 B+ with 1.1.73 (report KWMMM3).

The box's browser control had lost two of its methods since 1.1.57: a function written between them closed the class
early, so `hud` (the volume card, the "now playing" notice) and `evaluate` (Home at a page, Resume, a game's rest, the
box chooser) were never the browser's. The phone remote said so in the report. Each finding has its test here."""
import importlib.util
import inspect
import json
import os
import re
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from tests.test_box_speed import BOX, boxos


def load(name, mod, **env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(mod, os.path.join(BOX, name))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)


class StandInBrowser:
    """What the agent asks of the box's browser, written down."""
    def __init__(self):
        self.did = []

    def connected(self):
        return True

    def tab_of(self, app):
        return "T-" + app

    def evaluate(self, target, expression):
        self.did.append(("evaluate", target, expression))

    def home(self, look=None):
        self.did.append(("home",))
        return True

    def close(self, target):
        self.did.append(("close", target))

    def quiet_music(self, but=None):
        self.did.append(("quiet_music", but))
        return "edge-music"


class BrowserMethods(unittest.TestCase):
    def test_hud_and_evaluate_are_the_browser_s_again(self):
        for name in ("hud", "evaluate"):
            self.assertTrue(inspect.isfunction(getattr(boxos.Browser, name, None)), name)
        self.assertTrue(inspect.isfunction(boxos.merge_smooth))                            # (the function that cut the class)
        self.assertNotIn("merge_smooth", vars(boxos.Browser))

    def test_everything_the_box_asks_of_the_browser_is_there(self):
        with open(os.path.join(BOX, "boxos.py"), encoding="utf-8") as f:
            src = f.read()
        body = src[src.index("\nclass Browser"):src.index("\ndef merge_smooth")]
        own = set(vars(boxos.Browser)) | set(re.findall(r"self\.([a-z_]+)\s*=", body))
        asked = {}
        for name in ("sofa-box-agent.py", "sofa-box-input.py", "sofa-box-cec.py", "boxos.py"):
            with open(os.path.join(BOX, name), encoding="utf-8") as f:
                for m in re.findall(r"\bbrowser\.([a-zA-Z_]+)", f.read()):
                    asked.setdefault(m, name)
        self.assertGreater(len(asked), 20)
        self.assertEqual({m: f for m, f in asked.items() if m not in own}, {})



class HomeFromAnywhere(unittest.TestCase):
    """The owner: "Home button on remote should take you back to the sofa box home no matter what"."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent.py", "sofa_box_agent_home_fixes", SOFA_BOX_CONF=os.path.join(cls.dir, "conf"),
                         SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")
        cls.cec = load("sofa-box-cec.py", "sofa_box_cec_home_fixes")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.browser, self.stopped = StandInBrowser(), []
        self.was = (self.agent.browser, self.agent.player.stop)
        self.agent.browser = self.browser
        self.agent.player.stop = lambda save=True, reason="stop": self.stopped.append(reason)

    def tearDown(self):
        self.agent.browser, self.agent.player.stop = self.was

    def test_home_is_home_s_first_page_with_the_video_stopped(self):
        self.assertTrue(self.agent.go_home())
        self.assertEqual(self.stopped, ["back"])                                          # the player, its place kept
        self.assertEqual(self.browser.did, [("evaluate", "T-home", "window.sofaHomeKey && sofaHomeKey()"), ("home",)])

    def test_a_page_s_sofa_bar_home_is_the_same_home(self):
        self.agent.page_message({"a": "home"}, "T-edge-music", {"app": "edge-music"})
        self.assertIn(("evaluate", "T-home", "window.sofaHomeKey && sofaHomeKey()"), self.browser.did)
        self.browser.did.clear()
        self.agent.page_message({"a": "close"}, "T-edge-music", {"app": "edge-music"})
        self.assertEqual(self.browser.did[0], ("close", "T-edge-music"))
        self.assertEqual(self.browser.did[-1], ("home",))

    def test_the_tv_remote_s_home_goes_to_the_agent_not_into_the_page(self):
        asked = []

        class Answer:
            def close(self):
                pass

        def agent_open(req, timeout):
            asked.append((req.full_url, req.get_header("X-sofa-box")))
            return Answer()

        def nobody(req, timeout):
            raise OSError("refused")

        self.assertTrue(self.cec.home(agent_open))
        self.assertEqual(asked, [("http://127.0.0.1:8091/box/api/home", "1")])
        self.assertFalse(self.cec.home(nobody))                                           # (no agent: typed as a key after all)
        with open(os.path.join(BOX, "sofa-box-cec.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('if name == "KEY_HOMEPAGE" and home():\n            return', src)

    def test_home_itself_drops_what_is_open_over_it(self):
        with open(os.path.join(BOX, "home", "home.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn('window.sofaHomeKey = () => { closeSheet(); if (location.hash !== "#/") location.hash = "#/"; };', js)
        self.assertIn('k === "BrowserHome" || k === "F1" || k === "HomePage") { e.preventDefault(); sofaHomeKey(); }', js)



class NotBothAtOnce(unittest.TestCase):
    """The owner: a video started in Sofa while Edge Music played behind Home, and both played."""

    def browser(self, playing):
        b, pressed = boxos.Browser.__new__(boxos.Browser), []
        b.now_playing = lambda: playing
        b.music = lambda target, act: pressed.append((target, act)) or True
        return b, pressed

    def test_the_music_pauses_when_a_video_starts(self):
        b, pressed = self.browser({"target": "T-music", "app": "edge-music", "playing": True})
        self.assertEqual(b.quiet_music(), "edge-music")
        self.assertEqual(pressed, [("T-music", "pause")])

    def test_not_the_page_the_video_is_in_and_not_music_already_paused(self):
        b, pressed = self.browser({"target": "T-music", "app": "edge-music", "playing": True})
        self.assertIsNone(b.quiet_music(but="T-music"))                                    # (an app's own preview)
        b, pressed = self.browser({"target": "T-music", "app": "edge-music", "playing": False})
        self.assertIsNone(b.quiet_music())
        b, pressed = self.browser(None)
        self.assertIsNone(b.quiet_music())
        self.assertEqual(pressed, [])

    def test_the_player_and_every_page_ask_for_it(self):
        with open(os.path.join(BOX, "sofa-box-agent.py"), encoding="utf-8") as f:
            agent = f.read()
        play = agent[agent.index("    def play(self, payload, cookie, base=None):"):]
        self.assertIn("quiet_music()", play[:play.index("self.proc = subprocess.Popen")])   # before mpv starts
        with open(os.path.join(BOX, "home", "inject.js"), encoding="utf-8") as f:
            inject = f.read()
        self.assertIn('if (v && v.tagName === "VIDEO" && !v.muted && v.volume > 0) send({ a: "video" });', inject)

    def test_a_page_s_video_pauses_the_music_elsewhere(self):
        here = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, here, True)
        agent = load("sofa-box-agent.py", "sofa_box_agent_not_both", SOFA_BOX_CONF=os.path.join(here, "conf"),
                     SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")
        agent.browser = StandInBrowser()
        agent.page_message({"a": "video"}, "T-sofa", {"app": "sofa"})
        for th in [x for x in threading.enumerate() if x.name == "quiet-music"]:
            th.join(5)
        self.assertEqual(agent.browser.did, [("quiet_music", "T-sofa")])
        self.assertEqual([app for _, app in agent.music_paused], ["edge-music"])



RUNNING = [{"target": "T1", "app": "sofa", "title": "sofa-2eebdd.localhost:8091/", "url": "http://sofa-2eebdd.localhost:8091/"},
           {"target": "T2", "app": "browser", "title": "en.wikipedia.org/wiki/Main_Page", "url": "https://en.wikipedia.org/wiki/Main_Page"},
           {"target": "T3", "app": "browser", "title": "Radio Garden", "url": "https://radio.garden/"}]
NOW = {"app": "edge-music", "name": "Edge Music", "title": "Midnight Run (Extended Mix)", "artist": "Krintoxi", "playing": True,
       "can": ["play", "pause", "nexttrack", "previoustrack"], "color": "#FF2E88", "target": "T9"}
APPS = r"""(() => { const real = window.fetch.bind(window); window.__asked = [];
  window.fetch = (url, opts) => {
    const u = String(url);
    if (u.includes("/box/api/close") || u.includes("/box/api/front")) { window.__asked.push([u.replace(/^.*\/box\/api\//, ""), opts && opts.body]);
      return Promise.resolve(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })); }
    if (!u.includes("/box/api/apps") || u.includes("/box/api/apps/")) return real(url, opts);
    return real(url, opts).then(r => r.json()).then(j => { j.running = %s; j.now = %s;
      return new Response(JSON.stringify(j), { status: 200, headers: { "Content-Type": "application/json" } }); });
  }; })();"""


class OnHome(unittest.TestCase):
    """Home in Chrome with three apps open and music playing behind it (the owner's photos of 1.1.73)."""
    SLOW = "0"

    @classmethod
    def setUpClass(cls):
        from tests.test_box_spotlight import Spotlight
        Spotlight.setUpClass.__func__(cls)
        cls.page.call("Page.addScriptToEvaluateOnNewDocument", {"source": APPS % (json.dumps(RUNNING), json.dumps(NOW))})
        now = time.time()
        with open(os.path.join(cls.dir, "conf", "browser-sites.json"), "w") as f:
            json.dump({"sites": {"en.wikipedia.org": {"n": 5, "last": now - 600, "url": "https://en.wikipedia.org/wiki/Television", "title": "Television - Wikipedia"},
                                 "radio.garden": {"n": 1, "last": now - 60, "url": "https://radio.garden/", "title": "Radio Garden"}}}, f)

    @classmethod
    def tearDownClass(cls):
        from tests.test_box_spotlight import Spotlight
        Spotlight.tearDownClass.__func__(cls)

    def until(self, expression, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            v = self.page.value(expression)
            if v:
                return v
            time.sleep(0.1)
        self.fail("never: " + expression)

    def home(self, where="#/"):
        self.page.call("Page.navigate", {"url": self.base + "/box/home?t=%f%s" % (time.time(), where)})
        self.until("!!document.querySelector('#view .tile')")
        time.sleep(1.2)
        return self.page

    def test_open_apps_go_by_their_names(self):
        p = self.home()
        names = p.value("[...document.querySelectorAll('#view [data-target]')].map(t => t.querySelector('b').textContent).join('|')")
        self.assertEqual(names, "Sofa|en.wikipedia.org|Radio Garden")                     # (not "sofa-2eebdd.lo…")

    def test_menu_on_an_open_app_closes_it(self):
        p = self.home()
        p.value("window.__asked.length = 0; 1")
        p.value("(t => { t.scrollIntoView(); t.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })); })(document.querySelector('#view [data-target=T1]')); 1")
        self.until("document.querySelector('#view [data-target=T1]').classList.contains('f')")
        p.press("F2", 113)
        self.until("!!document.querySelector('.sheet [data-sheet=quit]')")
        self.assertEqual(p.value("document.querySelector('.sheet h3').textContent"), "Sofa")
        self.assertEqual(p.value("document.activeElement && document.querySelector('.sheet .f') && document.querySelector('.sheet .f').dataset.sheet"), "front")
        p.value("document.querySelector('.sheet [data-sheet=quit]').click(); 1")
        self.until("window.__asked.some(a => a[0] === 'close')")
        self.assertEqual(json.loads(json.loads(p.value("JSON.stringify(window.__asked.find(a => a[0] === 'close'))"))[1]), {"target": "T1"})

    def test_the_top_bar_stays_on_the_screen_with_music_playing(self):
        p = self.home()
        self.until("!!document.querySelector('.spt-np')")
        right = p.value("Math.max(...[...document.querySelectorAll('.top *')].filter(e => e.offsetParent).map(e => e.getBoundingClientRect().right))")
        width = p.value("innerWidth")
        self.assertLessEqual(right, width - 0.035 * width)                                   # (inside the TV's safe area)
        self.assertEqual(p.value("getComputedStyle(document.querySelector('.spt-np img, .spt-np')).display !== 'none'"), True)
        self.assertGreater(p.value("document.querySelector('.spt-np-t').getBoundingClientRect().width"), 4 * p.value("parseFloat(getComputedStyle(document.documentElement).fontSize)"))
        self.assertEqual(p.value("[...document.querySelectorAll('.spt-np .np-k')].filter(b => b.offsetParent).length"), 3)

    def test_the_key_hints_are_below_the_rows(self):
        p = self.home()
        hint = p.value("document.querySelector('#hint').getBoundingClientRect().top")
        self.assertLessEqual(p.value("document.querySelector('#sptRows').getBoundingClientRect().bottom"), hint + 0.5)
        self.assertEqual(p.value("getComputedStyle(document.querySelector('#hint')).backgroundImage"), "none")   # (a floor, not a fade)

    def test_no_404_for_the_browser_s_icon(self):
        from tests.test_box_speed import get
        status, headers, body = get(self.base + "/favicon.ico")
        self.assertEqual((status, body), (204, b""))                                       # (the report's 404 at 10:39:19)
        with open(os.path.join(BOX, "home", "index.html"), encoding="utf-8") as f:
            self.assertIn('<link rel="icon" href="data:,">', f.read())

    def test_the_browser_page_has_your_sites_and_picks(self):
        p = self.home("#/browser")
        self.until("document.querySelectorAll('#view .tile.site').length >= 4")
        rows = json.loads(p.value("JSON.stringify([...document.querySelectorAll('#view .bs-rows .row-title')].map(h => [h.firstChild.textContent.trim(), "
                                  "[...h.nextElementSibling.querySelectorAll('.tile')].map(t => t.querySelector('small') ? t.querySelector('small').textContent : t.querySelector('b').textContent)]))"))
        self.assertEqual(rows[0], ["Recent", ["radio.garden", "en.wikipedia.org"]])
        self.assertEqual(rows[1][0], "More to try")
        self.assertNotIn("youtube.com", rows[1][1])                                        # (on Home already: not twice)
        self.assertIn("duckduckgo.com", rows[1][1])
        self.assertTrue(p.value("document.querySelector('#view .tile.site .ic').classList.contains('framed')"))   # (in the icon style)
        self.assertEqual(p.value("document.querySelector('.bs-shield').textContent.trim()"), "Sofa Shield on")
        self.assertEqual(p.value("document.activeElement && document.activeElement.id"), "address")

    def test_the_phone_remote_s_code_comes_up_over_home(self):
        p = self.home()
        p.value("window.sofaPhoneWaiting(); 1")
        self.until("!!document.querySelector('.sheet .phone-qr .qr svg')")
        codes = p.value("[...document.querySelectorAll('.sheet .phone-qr .code')].map(c => c.textContent).join(' ')")
        self.assertRegex(codes, r"^\d{4} [A-Z2-9]{4}-[A-Z2-9]{4}$")                        # at home, and from anywhere
        p.value("window.sofaPhonePaired('iPhone'); 1")
        self.until("!document.querySelector('.sheet .phone-qr')")
        p.value("(t => t.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })))(document.querySelector('#view [data-game]')); 1")
        p.press("F2", 113)                                                                 # Menu on Home, not on an app: the code
        self.until("!!document.querySelector('.sheet .phone-qr')")
        p.press("Escape", 27)

    def test_one_way_of_writing_the_time(self):
        p = self.home()
        home = p.value("document.querySelector('#sptClock').textContent")
        p = self.home("#/games")
        self.until("!!document.querySelector('#clock').textContent")
        self.assertEqual(p.value("document.querySelector('#clock').textContent"), home)
        self.assertRegex(home, r"^\d{1,2}:\d\d(AM|PM)?$")



class BrowserSites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent.py", "sofa_box_agent_sites", SOFA_BOX_CONF=os.path.join(cls.dir, "conf"),
                         SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0", SOFA_BOX_ICONS="0")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_recent_and_most_visited(self):
        h = self.agent.SiteHistory(os.path.join(self.dir, "sites.json"))
        t = 1_000_000
        self.assertTrue(h.visit("https://www.youtube.com/watch?v=1#t=3", "Some video - YouTube", now=t))
        h.visit("https://www.youtube.com/watch?v=2", "Another - YouTube", now=t + 60)            # (the same visit: still one)
        h.visit("https://en.wikipedia.org/wiki/TV", "TV - Wikipedia", now=t + 120)
        h.visit("https://www.youtube.com/", "YouTube", now=t + 4000)                            # (a visit again, later)
        for own in ("http://127.0.0.1:8091/box/home", "http://sofa-2eebdd.localhost:8091/", "chrome://newtab", "file:///etc/passwd"):
            self.assertFalse(h.visit(own, "x", now=t + 5000))                                   # (the box's own pages, Sofa: never)
        recent, top = h.lists()
        self.assertEqual([s["host"] for s in recent], ["youtube.com", "en.wikipedia.org"])
        self.assertEqual(recent[0]["url"], "https://www.youtube.com/")
        self.assertEqual([(s["host"], s["n"]) for s in top], [("youtube.com", 2)])
        h.save()
        again = self.agent.SiteHistory(os.path.join(self.dir, "sites.json"))
        self.assertEqual([s["host"] for s in again.lists()[0]], ["youtube.com", "en.wikipedia.org"])
        again.forget()
        self.assertEqual(self.agent.SiteHistory(os.path.join(self.dir, "sites.json")).lists(), ([], []))

    def test_only_the_browser_s_own_pages_are_kept(self):
        self.agent.history.forget()
        self.agent.page_message({"a": "visit", "url": "https://radio.garden/", "title": "Radio Garden"}, "T1", {"app": "browser"})
        self.agent.page_message({"a": "visit", "url": "https://music.edgeventure.uk/", "title": "Edge Music"}, "T2", {"app": "edge-music"})
        self.assertEqual([s["host"] for s in self.agent.history.lists()[0]], ["radio.garden"])

    def test_the_sofa_bar_has_size_and_the_shield(self):
        with open(os.path.join(BOX, "home", "inject.js"), encoding="utf-8") as f:
            js = f.read()
        for part in ('data-a="smaller"', 'data-a="bigger"', 'data-a="shield"', 'send({ a: "visit", url: location.href'):
            self.assertIn(part, js)
        with open(os.path.join(BOX, "boxos.py"), encoding="utf-8") as f:
            self.assertIn('bar = "window.__sofaBoxVars = %s;\\n%s" % (told, INJECT)', f.read())



class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class PhoneSignIn(unittest.TestCase):
    """The owner: "when exiting the remote on your phone, and coming back to it, it asks for a code, thats nowhere to be
    seen on the tv so user looses controller". Two of the remote's addresses here (a sign-in is a cookie, and a cookie
    belongs to one address), and the relay's mark on a request."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.agent = a = load("sofa-box-agent.py", "sofa_box_agent_phones", SOFA_BOX_CONF=os.path.join(cls.dir, "conf"),
                             SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0", SOFA_BOX_ICONS="0")
        os.makedirs(a.CONF_DIR, exist_ok=True)
        cls.servers = [a.Server(("127.0.0.1", 0), a.RemoteHandler) for _ in range(2)]
        for srv in cls.servers:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    @classmethod
    def tearDownClass(cls):
        for srv in cls.servers:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        a, self.shown = self.agent, []
        self.was = (a.phone, a.show_phone_code, a.toast)
        a.phone = a.PhoneRemote()
        a.phone.forget_all()
        a.show_phone_code = lambda relayed=False: self.shown.append(relayed)
        a.toast = lambda text: None

    def tearDown(self):
        self.agent.phone, self.agent.show_phone_code, self.agent.toast = self.was

    def req(self, n, path, body=None, cookie=None, relayed=False):
        headers = dict({"Content-Type": "application/json", "X-Sofa-Remote": "1"}, **({"Cookie": cookie} if cookie else {}),
                       **({"X-Sofa-Relay": "1"} if relayed else {}))
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.servers[n].server_address[1], path),
                                   None if body is None else json.dumps(body).encode(), headers)
        try:
            with self.opener.open(r, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def shown_by_now(self):
        for th in [x for x in threading.enumerate() if x.name == "phone-code"]:
            th.join(5)
        return self.shown

    def test_paired_on_one_address_it_presses_on_another(self):
        a = self.agent
        status, headers, _ = self.req(0, "/r/" + a.phone.link)                            # the TV's QR code, scanned
        cookie = headers["Set-Cookie"].split(";")[0]
        status, _, body = self.req(0, "/api/state", cookie=cookie)
        key = json.loads(body)["key"]
        self.assertEqual((status, len(key)), (200, 48))
        self.assertEqual(self.req(1, "/api/state")[0], 401)                              # the other address: no cookie there
        status, headers, page = self.req(1, "/?k=" + key)                                 # the phone's own link, there
        self.assertEqual((status, headers["Set-Cookie"].split(";")[0], headers["Referrer-Policy"]), (200, cookie, "no-referrer"))
        self.assertIn(b"<html", page[:200].lower())
        self.assertEqual(self.req(1, "/api/key", {"k": "up"}, cookie=cookie)[0], 200)     # and it presses
        self.assertEqual(json.loads(self.req(1, "/manifest.json", cookie=cookie)[2])["start_url"], "./?k=" + key)   # the icon keeps it
        self.assertNotIn("Set-Cookie", self.req(1, "/?k=" + "0" * 48)[1])                  # (anyone else's key: nothing)
        old = a.phone.link                                                                # the TV's code scanned again, signed in:
        status, headers, _ = self.req(0, "/r/" + old, cookie=cookie)                       # the remote, and the code kept for another
        self.assertEqual((status, headers["Location"], a.phone.link), (302, "/", old))
        a.phone.forget_all()                                                              # Settings → Forget phones: the link goes too
        self.assertNotIn("Set-Cookie", self.req(1, "/?k=" + key)[1])

    def test_a_phone_from_anywhere_without_a_sign_in_is_never_stuck(self):
        a = self.agent
        status, _, body = self.req(0, "/api/state", relayed=True)
        self.assertEqual((status, json.loads(body)["typing"]), (401, "word"))
        self.assertEqual(self.shown_by_now(), [True])                                     # the TV brings its code up
        self.req(0, "/api/state", relayed=True)
        self.assertEqual(self.shown_by_now(), [True])                                     # (once a minute, not every poll)
        status, _, body = self.req(0, "/api/pair", {"code": a.phone.code}, relayed=True)  # four numbers from the internet: no
        self.assertEqual(status, 403)
        self.assertIn("eight letters", json.loads(body)["error"])
        word = a.phone.word
        status, headers, _ = self.req(0, "/api/pair", {"code": word[:4].lower() + "-" + word[4:]}, relayed=True)
        self.assertEqual(status, 200)
        self.assertTrue(headers["Set-Cookie"].startswith("sofa_remote="))
        self.assertNotEqual(a.phone.word, word)                                           # (each works once)
        with open(os.path.join(BOX, "remote.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn('"The TV shows a code now. Scan it with your phone\'s camera, or type the " + (away ? "eight letters" : "four numbers")', page)
        self.assertIn("if (!s.paired) return showPairing(s.typing);\n      keepLink(s.key);", page)

    def test_guessing_from_the_internet_never_stops_typing_at_home(self):
        a = self.agent
        for _ in range(a.PhoneRemote.MISSES):
            self.assertIsNone(a.phone.pair("ZZZZZZZZ", "Phone", relayed=True))
        self.assertTrue(a.phone.resting(True))
        self.assertIsNone(a.phone.pair(a.phone.word, "Phone", relayed=True))             # resting, even with the right one
        self.assertFalse(a.phone.resting(False))
        self.assertTrue(a.phone.pair(a.phone.code, "Phone"))                              # at home: still four numbers

    def test_the_tv_shows_the_code_when_a_phone_waits(self):
        a = self.agent
        a.show_phone_code = self.was[1]
        browser, said = StandInBrowser(), []
        real = a.browser, a.playing, a.player.osd
        a.browser = browser
        try:
            a.playing = lambda: False
            self.assertEqual(a.show_phone_code(), "home")                                 # Home forward, its sheet up
            self.assertEqual(browser.did, [("home",), ("evaluate", "T-home", "window.sofaPhoneWaiting && sofaPhoneWaiting()")])
            a.playing, a.player.osd = (lambda: True), (lambda **what: said.append(what))
            self.assertEqual(a.show_phone_code(), "player")                               # over a video: a line on it
            self.assertIn(a.phone.status()["word"], said[0]["toast"])
            a.phone_paired("iPhone")
            self.assertEqual(browser.did[-1], ("evaluate", "T-home", 'window.sofaPhonePaired && sofaPhonePaired("iPhone")'))
        finally:
            a.browser, a.playing, a.player.osd = real


if __name__ == "__main__":
    unittest.main()
