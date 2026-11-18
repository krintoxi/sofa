"""Watching together on two screens: two browsers (each its own Chrome, signed in as a different profile) in one room,
playing a real video through the running server. How far apart the two pictures are, measured by the pages themselves:
each writes down where its video is against the computer's clock ten times a second, and the two lists are compared at
the same moments (reading the two over DevTools one after the other would add its own gap).

The numbers are printed (`together:` lines; SOFA_TOGETHER_NUMBERS=<file> also writes them down). The checks are loose,
to catch a room that doesn't keep in step at all: the two screens and the server share one computer (GitHub's, on
every change), over its loopback, often busy with other work."""
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests import LIBRARY
from tests.test_box_speed import Page, chrome, free_port
from sofa import auth, media, store, together, web
from sofa.library import LIBRARY as LIB

SAMPLER = """(() => {
  if (window.__wt) return 1;
  window.__wt = [];
  const v = document.querySelector('#player video');
  setInterval(() => {
    let at = null;
    try { at = sofaPlayerState().at; } catch (e) {}
    window.__wt.push([performance.timeOrigin + performance.now(), at, v.paused, v.playbackRate, v.readyState, v.seeking]);
    if (window.__wt.length > 6000) window.__wt.splice(0, 1000);
  }, 100);
  return 1;
})()"""


def make_video(path, seconds, args):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        subprocess.run([media.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=%d" % seconds,
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % seconds] + args + [path], check=True)


class Screen:
    """One browser: its own Chrome and its own sign-in."""

    def __init__(self, base, workdir, name):
        self.base, self.dir = base, os.path.join(workdir, name)
        self.port = free_port()
        self.start()

    def start(self):
        self.proc = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--mute-audio",
                                      "--autoplay-policy=no-user-gesture-required", "--window-size=1280,720",
                                      "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                                      "--remote-debugging-port=%d" % self.port, "--user-data-dir=" + self.dir, "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.page = Page(self.port, "about:blank")
        except AssertionError:                          # (a busy computer: Chrome slow to open its first tab)
            self.page = Page(self.port, "about:blank")
        self.page.call("Page.enable")

    def sign_in(self, who):
        p = self.page
        p.call("Page.navigate", {"url": self.base + "/client/manifest.webmanifest"})
        time.sleep(0.4)
        status = p.value("fetch('/api/login',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},"
                         "body:JSON.stringify({name:%s,password:'password123'})}).then(r=>r.status)" % json.dumps(who))
        assert status == 200, status
        p.value("localStorage.clear(); localStorage.setItem('sofa.ambient','false'); sessionStorage.setItem('sofaPicked','1'); 1")

    def go(self, hash_):
        self.page.call("Page.navigate", {"url": self.base + "/?t=%f#%s" % (time.time(), hash_)})
        self.until("typeof sofaPlayerState === 'function' && sofaPlayerState().ready")
        self.v(SAMPLER)

    def v(self, expression):
        return self.page.value(expression)

    def until(self, expression, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.v(expression):
                    return
            except AssertionError:
                pass
            time.sleep(0.15)
        raise AssertionError("never true: %s (%s)" % (expression, self.v("typeof sofaPlayerState === 'function' && JSON.stringify(sofaPlayerState())")))

    def samples(self):
        return self.v("window.__wt")

    def close(self):
        try:
            self.page.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def playing(x):
    """A sample of a video playing: loaded, not paused, not in the middle of a skip."""
    return x[1] is not None and not x[2] and x[4] >= 3 and not x[5]


def at_time(samples, when):
    """Where a screen's video was at `when` (ms on the computer's clock), from the two samples around it; None when it
    wasn't playing smoothly there (loading, paused, skipping, or stuck)."""
    for a, b in zip(samples, samples[1:]):
        if a[0] <= when <= b[0]:
            if not (playing(a) and playing(b)) or b[0] - a[0] > 300 or not 0 < b[1] - a[1] <= 1.0:
                return None
            return a[1] + (b[1] - a[1]) * (when - a[0]) / (b[0] - a[0])
    return None


def gaps(one, two, start, end):
    """How far apart the two videos were (seconds, + the first ahead), every 100 ms from `start` to `end` (ms):
    (when, the gap, the place the one further back was at)."""
    out, t = [], start
    while t <= end:
        a, b = at_time(one, t), at_time(two, t)
        if a is not None and b is not None:
            out.append((t, a - b, min(a, b)))
        t += 100
    return out


def settled(series, within, hold_ms=2000, past=None):
    """When the gap came within `within` and stayed there for `hold_ms` (ms on the clock), both playing for at least
    four fifths of that time (a gap while one is loading isn't being in step), and both past `past` (a skip's target:
    not still before it), or None."""
    if past is not None:
        series = [x for x in series if x[2] >= past]
    for i, (t, _, _) in enumerate(series):
        rest = [x[1] for x in series[i:] if x[0] <= t + hold_ms]
        if series[-1][0] >= t + hold_ms and len(rest) >= 0.8 * hold_ms / 100 and all(abs(g) <= within for g in rest):
            return t
    return None


def summary(series):
    g = [abs(x[1]) for x in series]
    return {"median": round(statistics.median(g), 3), "p95": round(sorted(g)[int(len(g) * 0.95) - 1], 3), "max": round(max(g), 3),
            "samples": len(g)} if g else {}


@unittest.skipUnless(chrome() and media.tool("ffmpeg"), "needs Chrome and ffmpeg")
class TwoScreens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        make_video(os.path.join(LIBRARY, "Movies", "Drift Test (2020)", "Drift Test (2020).mp4"), 240,
                   ["-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
                    "-movflags", "+faststart", "-shortest"])
        # one the browser can't play as it is (an FLV): Sofa repackages it as it plays, as HLS
        make_video(os.path.join(LIBRARY, "Movies", "Drift Packaged (2021)", "Drift Packaged (2021).flv"), 240,
                   ["-c:v", "libx264", "-preset", "ultrafast", "-g", "50", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-shortest"])
        LIB.scan("tests")
        cls.film = next(k for k, i in LIB.items.items() if i.get("kind") == "movie" and "drift-test" in k)
        cls.packaged = next(k for k, i in LIB.items.items() if i.get("kind") == "movie" and "drift-packaged" in k)
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        for name in ("wt-one", "wt-two"):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123")
        cls.dir = tempfile.mkdtemp(prefix="sofa-together-")
        cls.one, cls.two = Screen(cls.base, cls.dir, "one"), Screen(cls.base, cls.dir, "two")
        cls.one.sign_in("wt-one")
        cls.two.sign_in("wt-two")
        cls.results = {}

    @classmethod
    def tearDownClass(cls):
        for s in (cls.one, cls.two):
            s.close()
        shutil.rmtree(cls.dir, ignore_errors=True)
        cls.httpd.shutdown()
        cls.httpd.server_close()
        together.reset()
        out = os.environ.get("SOFA_TOGETHER_NUMBERS")
        if out:
            with open(out, "w") as f:
                json.dump(cls.results, f, indent=2)

    def report(self, name, value):
        type(self).results[name] = value
        print("together: %s %s" % (name, json.dumps(value)))

    def start_room(self, item):
        one, two = self.one, self.two
        for s in (one, two):
            s.go("/")
        one.v("location.hash = '#/play/' + encodeURIComponent(%s); 1" % json.dumps(item))
        one.until("sofaPlayerState().at > 4 && !document.querySelector('#player video').paused")
        self.assertIsNone(one.v("document.querySelector('#player video').error"))
        one.v("document.querySelector('#player [data-act=room]').click(); document.querySelector('[data-room=start]').click(); 1")
        one.until("sofaPlayerState().room && sofaPlayerState().room.code")
        return one.v("sofaPlayerState().room.code")

    def join(self, code):
        two = self.two
        two.v("location.hash = '#/together/%s'; 1" % code)
        two.until("!!document.querySelector('[data-join]')")
        clicked = two.v("performance.timeOrigin + performance.now()")
        two.v("document.querySelector('[data-join]').click(); 1")
        two.until("sofaPlayerState().room && sofaPlayerState().at > 1 && !document.querySelector('#player video').paused", 60)
        self.assertIsNone(two.v("document.querySelector('#player video').error"))
        return clicked

    def gap_since(self, since_ms, until_ms=None):
        end = until_ms or self.one.v("performance.timeOrigin + performance.now()")
        return gaps(self.one.samples(), self.two.samples(), since_ms, end)

    def wait_settled(self, since_ms, within=0.1, timeout=30, past=None):
        """Seconds from `since_ms` until the two were in step (past `past`); None if they never were in `timeout`."""
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(1)
            series = self.gap_since(since_ms)
            t = settled(series, within, past=past)
            if t is not None:
                return round((t - since_ms) / 1000, 1), series
        return None, self.gap_since(since_ms)

    def then(self, name, after_ms, seconds=8):
        """How far apart the two were for `seconds` from `after_ms` (the worst included), reported."""
        time.sleep(max(0, (after_ms + seconds * 1000) / 1000 - self.one.v("performance.timeOrigin + performance.now()") / 1000) + 0.3)
        out = summary(self.gap_since(after_ms, after_ms + seconds * 1000))
        self.report(name, out)
        return out

    def clocks_apart_ms(self):
        """How far apart the two pages' ideas of Sofa's clock are (each: its offset, from its own time origin)."""
        a, b = (s.v("JSON.stringify(sofaPlayerState().room)") for s in (self.one, self.two))
        a, b = json.loads(a), json.loads(b)
        return round(abs((a["offset"] - b["offset"]) * 1000 + (b["origin"] - a["origin"])), 1)

    def advancing(self, s):
        a = s.v("sofaPlayerState().at")
        time.sleep(1)
        b = s.v("sofaPlayerState().at")
        self.assertGreater(b - a, 0.5, "the video isn't playing")

    def test_two_screens_keep_in_step(self):
        one, two = self.one, self.two
        code = self.start_room(self.film)
        time.sleep(4)                                    # the film plays on: the second screen joins mid-film
        clicked = self.join(code)
        for s in (one, two):
            self.advancing(s)
        took, series = self.wait_settled(clicked)
        self.report("join_mid_film_seconds_to_within_100ms", took)
        self.assertIsNotNone(took, "never in step: %s" % summary(series))
        self.assertLess(took, 30)
        self.then("join_then_8s", clicked + took * 1000)
        self.report("clocks_apart_ms", self.clocks_apart_ms())

        # steady: 20 seconds side by side
        t0 = one.v("performance.timeOrigin + performance.now()")
        time.sleep(20)
        steady = summary(self.gap_since(t0))
        self.report("steady_20s", steady)
        self.assertGreater(steady["samples"], 100)
        self.assertLess(steady["median"], 0.15)
        self.assertLess(steady["max"], 1.0)

        # the host skips ahead a minute (as the line or the phone remote does)
        t1 = one.v("performance.timeOrigin + performance.now()")
        target = one.v("sofaPlayerState().at") + 60
        one.v("sofaPlayerControl({cmd: 'seek', t: %f}); 1" % target)
        took, series = self.wait_settled(t1, past=target - 0.5)
        self.report("seek_60s_seconds_to_within_100ms", took)
        self.assertIsNotNone(took, "never in step after the skip: %s" % summary(series))
        self.assertLess(took, 30)
        after = self.then("seek_then_8s", t1 + took * 1000)
        self.assertLess(after["median"], 0.15)

        # the second screen can't steer: its pause doesn't stop the room, nor its own picture
        two.v("sofaPlayerControl({cmd: 'pause'}); 1")
        time.sleep(1)
        self.assertFalse(one.v("document.querySelector('#player video').paused"))
        self.assertFalse(two.v("document.querySelector('#player video').paused"))

        # the host pauses: both stop at the same frame, near enough
        one.v("sofaPlayerControl({cmd: 'pause'}); 1")
        two.until("document.querySelector('#player video').paused", 15)
        time.sleep(1.5)
        held = abs(one.v("sofaPlayerState().at") - two.v("sofaPlayerState().at"))
        self.report("paused_apart_seconds", round(held, 3))
        self.assertLess(held, 0.5)

        # speed: the host's 1.25×, and the second screen follows it
        one.v("sofaPlayerControl({cmd: 'resume'}); 1")
        one.v("document.querySelector('#player [data-act=speed]').click(); 1")
        two.until("sofaPlayerState().rate === 1.25", 15)
        t3 = one.v("performance.timeOrigin + performance.now()")
        time.sleep(10)
        fast = summary(self.gap_since(t3 + 3000))
        self.report("at_1_25x_after_3s", fast)
        self.assertLess(fast["median"], 0.25)

        # headphones or a keyboard's media key pause the host's video itself: the room pauses with it
        one.v("document.querySelector('#player video').pause(); 1")
        two.until("document.querySelector('#player video').paused", 15)
        time.sleep(1)
        self.assertTrue(one.v("document.querySelector('#player video').paused"))       # (and stays paused)
        one.v("sofaPlayerControl({cmd: 'resume'}); 1")
        two.until("!document.querySelector('#player video').paused", 15)

        # the room's panel (W on a keyboard or a remote): drawn at once, before anything is asked of Sofa
        # (to the next frame drawn after the key; a page that draws no frame for a second says null)
        took = two.v("(async () => { const t = performance.now(); document.dispatchEvent(new KeyboardEvent('keydown', {key: 'w', bubbles: true}));"
                     " const shown = !document.querySelector('#player .p-room').hidden;"
                     " const drawn = await Promise.race([new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(true)))),"
                     " new Promise(r => setTimeout(() => r(false), 1000))]);"
                     " return !shown ? -1 : drawn ? performance.now() - t : null; })()")
        self.report("panel_on_screen_ms", None if took is None else round(took, 1))
        self.assertNotEqual(took, -1)
        self.assertIn("wt-one", two.v("document.querySelector('#player .room-people').textContent"))
        two.v("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'w', bubbles: true})); 1")

        # the host lets everyone steer: the second screen's skip moves the room, the host's screen too
        one.v("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'w', bubbles: true})); 1")
        one.v("document.querySelector('[data-room=everyone]').click(); 1")
        two.until("sofaPlayerState().room.everyone", 15)
        target = two.v("sofaPlayerState().at") + 40
        two.v("sofaPlayerControl({cmd: 'seek', t: %f}); 1" % target)
        one.until("Math.abs(sofaPlayerState().at - %f) < 5" % target, 15)

        # the host leaves: the room goes on, and the second screen is its host now
        one.v("sofaPlayerControl({cmd: 'stop'}); 1")
        two.until("sofaPlayerState().room && sofaPlayerState().room.members === 1 && sofaPlayerState().room.host", 15)
        self.advancing(two)
        two.v("sofaPlayerControl({cmd: 'stop'}); 1")

    def test_slow_answers_dont_set_the_clock(self):
        """The joining screen's first answers about Sofa's clock come back 2 seconds late (a busy computer, a slow
        tunnel): read as they are, its idea of the clock would be a second out, and it would sit a second away while
        thinking it's in step. It asks again until an answer comes back quickly."""
        code = self.start_room(self.film)
        real, slow = web.Handler.together_get, {"left": 4}

        def late(handler, path, qs, u):
            if path == "/api/together/clock" and u["name"] == "wt-two" and slow["left"] > 0:
                slow["left"] -= 1
                now = together.clock()
                time.sleep(2)                                   # read now, answered 2 seconds later
                return handler.json({"now": now})
            return real(handler, path, qs, u)
        with mock.patch.object(web.Handler, "together_get", late):
            clicked = self.join(code)
            took, series = self.wait_settled(clicked, timeout=40)
        self.report("slow_clock_join_seconds_to_within_100ms", took)
        self.assertEqual(slow["left"], 0)
        self.assertIsNotNone(took, "never in step: %s" % summary(series))
        self.assertLess(took, 20)               # (taking the late answers, it would wait for its every-15-seconds look: ~30 s)
        apart = self.clocks_apart_ms()
        self.report("slow_clock_clocks_apart_ms", apart)
        self.assertLess(apart, 100)
        self.two.v("sofaPlayerControl({cmd: 'stop'}); 1")
        self.one.v("sofaPlayerControl({cmd: 'stop'}); 1")

    def test_the_tv_remote_reaches_the_room(self):
        """In TV mode, with the remote's arrows: up to the people button, OK opens the room's panel with the remote
        inside it, and Back closes the panel, not the video."""
        one = self.one
        one.go("/")
        one.v("localStorage.setItem('sofa.tv', 'true'); 1")
        self.addCleanup(lambda: one.v("localStorage.setItem('sofa.tv', 'false'); 1"))
        one.go("/")
        one.v("location.hash = '#/play/' + encodeURIComponent(%s); 1" % json.dumps(self.film))
        one.until("sofaPlayerState().at > 1")
        key = {"ArrowUp": 38, "ArrowRight": 39, "ArrowLeft": 37, "Enter": 13, "Backspace": 8}

        def press(k):
            for kind in ("rawKeyDown" if k != "Enter" else "keyDown", "keyUp"):
                one.page.call("Input.dispatchKeyEvent", dict({"type": kind, "key": k, "code": k, "windowsVirtualKeyCode": key[k],
                                                              "nativeVirtualKeyCode": key[k]}, **({"text": "\r"} if kind == "keyDown" else {})))
            time.sleep(0.25)
        on_room = "document.activeElement && document.activeElement.dataset.act === 'room'"
        presses = 0
        for k in ["ArrowUp"] * 3 + ["ArrowRight"] * 4 + ["ArrowLeft"] * 4:
            if one.v(on_room):
                break
            press(k)
            presses += 1
        self.report("tv_presses_to_the_people_button", presses)
        self.assertTrue(one.v(on_room), one.v("document.activeElement.outerHTML.slice(0, 120)"))
        press("Enter")
        self.assertFalse(one.v("document.querySelector('#player .p-room').hidden"))
        self.assertTrue(one.v("document.querySelector('#player .p-room').contains(document.activeElement)"))
        press("Backspace")
        self.assertTrue(one.v("document.querySelector('#player .p-room').hidden"))
        self.assertFalse(one.v("document.querySelector('#player').hidden"))           # still watching
        # full screen (as on a TV) shows only the player: Sofa's messages go in there
        one.page.call("Runtime.evaluate", {"expression": "document.querySelector('#player').requestFullscreen().then(() => 1, () => 0)",
                                           "awaitPromise": True, "userGesture": True, "returnByValue": True})
        full = one.v("!!document.fullscreenElement")
        if not full:                    # (headless Chrome won't go full screen: the page is told the player is)
            one.v("Object.defineProperty(document, 'fullscreenElement', {configurable: true, get: () => document.querySelector('#player')}); 1")
        one.v("SofaToast('A message'); 1")
        self.assertTrue(one.v("document.querySelector('#player').contains(document.getElementById('toast'))"))
        one.v("delete document.fullscreenElement; document.fullscreenElement && document.exitFullscreen().then(() => 1, () => 0); 1")
        one.v("SofaToast('Another'); 1")
        self.assertEqual(one.v("document.getElementById('toast').parentNode === document.body"), True)
        self.report("tv_really_full_screen", full)
        one.v("sofaPlayerControl({cmd: 'stop'}); 1")

    def test_repackaged_video_keeps_in_step_after_a_skip(self):
        one, two = self.one, self.two
        code = self.start_room(self.packaged)
        mode = one.v("document.querySelector('#player .p-mode').textContent")
        self.report("packaged_mode", mode)
        clicked = self.join(code)
        took, series = self.wait_settled(clicked, within=0.15, timeout=40)
        self.report("packaged_join_seconds_to_within_150ms", took)
        self.assertIsNotNone(took, "never in step: %s" % summary(series))
        self.then("packaged_join_then_8s", clicked + took * 1000)
        t1 = one.v("performance.timeOrigin + performance.now()")
        target = one.v("sofaPlayerState().at") + 90                                    # past what's been made: Sofa starts again there
        one.v("sofaPlayerControl({cmd: 'seek', t: %f}); 1" % target)
        took, series = self.wait_settled(t1, within=0.15, timeout=45, past=target - 0.5)
        self.report("packaged_seek_90s_seconds_to_within_150ms", took)
        self.assertIsNotNone(took, "never in step after the skip: %s" % summary(series))
        after = self.then("packaged_seek_then_8s", t1 + took * 1000)
        self.assertLess(after["median"], 0.3)
        two.v("sofaPlayerControl({cmd: 'stop'}); 1")
        one.v("sofaPlayerControl({cmd: 'stop'}); 1")


if __name__ == "__main__":
    unittest.main()
