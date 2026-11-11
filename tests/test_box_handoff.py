"""Sofa Box OS 1.1.61: the setup's hand-off from the box's own Wi-Fi to the home Wi-Fi, as one clear path.

What a 1.1.60 box did on a real Pi 3 B+ (its own report, SAD8SD): its own Wi-Fi started twice, three seconds apart;
and the box's clock, 36 days behind until it was first online, was set right seconds after it joined the home Wi-Fi,
so "joined a moment ago" read as "a month ago" and the TV dropped the setup's last step for the plain first code.
On the phone, the Wi-Fi's password was a box at the bottom of the page, under the iPhone keyboard's bar and its
password suggestions. These are the box's halves of the fixes, off the hardware: the agent with a stand-in nmcli,
and both pages in a real browser (the TV's against a clock weeks off the agent's, the phone's at a phone's size)."""
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import types
import unittest
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load(name, **env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(name.replace("-", "_") + "_handoff", os.path.join(BOX, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)


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
        return r.read()


class Tab:
    """One tab, over DevTools (the box's own WebSocket client)."""

    def __init__(self, devtools_port, url=None):
        for _ in range(150):
            try:
                tabs = [t for t in json.loads(get("http://127.0.0.1:%d/json/list" % devtools_port)) if t["type"] == "page"]
                if tabs:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        else:
            raise AssertionError("the browser has no page")
        self.ws = boxos.WebSocket(tabs[0]["webSocketDebuggerUrl"])
        self.ws.sock.settimeout(30)
        self.n = 0
        self.call("Page.enable")                              # (without it, a script for new documents doesn't run)

    def call(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                if "error" in m:
                    raise AssertionError(m["error"])
                return m.get("result", {})

    def value(self, expression):
        r = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise AssertionError(r["exceptionDetails"].get("exception", {}).get("description") or r["exceptionDetails"])
        return r["result"].get("value")

    def until(self, expression, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            v = self.value(expression)
            if v:
                return v
            time.sleep(0.1)
        raise AssertionError("never true: %s" % expression)

    def close(self):
        self.ws.close()


class ItsOwnWifiStartsOnce(unittest.TestCase):
    """`nmcli device wifi hotspot` started the box's own Wi-Fi NetworkManager's way; two changes (no PMF, no IPv6) then
    needed it started again. On the Pi: up at 95 s, down and up again at 98 s, its address server with it."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent", SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def setUp(self):
        a = self.agent
        self.real = a.run, a.time, a.captive.start, a.captive.stop
        self.calls = []
        a.captive.start = a.captive.stop = lambda: None
        a.time = types.SimpleNamespace(sleep=lambda s: None, time=time.time)

    def tearDown(self):
        a = self.agent
        a.run, a.time, a.captive.start, a.captive.stop = self.real

    def nmcli(self, refuse=()):
        def run(cmd, timeout=20):
            self.calls.append(cmd)
            if cmd[-1] == "device":
                return 0, "wlan0:wifi"
            return (10, "Error: no") if cmd[1:3] in [list(r) for r in refuse] else (0, "")
        return run

    def starts(self):
        """How many times the commands so far started it (each of these activates the connection)."""
        return sum(1 for c in self.calls if c[1:3] == ["connection", "up"] or c[1:4] == ["device", "wifi", "hotspot"])

    def test_made_whole_then_started_once(self):
        a = self.agent
        a.run = self.nmcli()
        net = a.Network()
        hs = net.start_hotspot()
        self.assertTrue(hs)
        self.assertEqual(self.starts(), 1)
        add = next(c for c in self.calls if c[1:3] == ["connection", "add"])
        said = dict(zip(add[3::2], add[4::2]))
        self.assertEqual(said["con-name"], "sofa-box-setup")
        self.assertEqual(said["802-11-wireless.mode"], "ap")
        self.assertEqual(said["802-11-wireless-security.pmf"], "disable")     # (iPhones can't join the Pi's with it on)
        self.assertEqual(said["ipv6.method"], "disabled")                     # (the sign-in sheet asks the box at once)
        self.assertEqual(said["ipv4.method"], "shared")
        self.assertEqual((said["ssid"], said["802-11-wireless-security.psk"]), (hs["ssid"], hs["password"]))
        self.assertEqual(said["autoconnect"], "no")
        self.assertFalse([c for c in self.calls if "modify" in c or "hotspot" in c])
        self.assertLess(self.calls.index(add), self.calls.index(["nmcli", "connection", "up", "sofa-box-setup"]))

    def test_the_tv_shows_its_code_only_once_it_is_up(self):
        """The code to join it showed while it was about to go down and come up again (it was known as up from the
        first start)."""
        a, seen = self.agent, []
        real = self.nmcli()

        def run(cmd, timeout=20):
            seen.append(bool(net.hotspot))
            return real(cmd, timeout)
        a.run = run
        net = a.Network()
        net.start_hotspot()
        self.assertFalse(any(seen))
        self.assertTrue(net.hotspot)

    def test_the_old_way_where_networkmanager_wont_take_it_whole(self):
        a = self.agent
        for refuse in ([("connection", "add")], [("connection", "up")]):
            self.calls = []
            a.run = self.nmcli(refuse)
            net = a.Network()
            if refuse == [("connection", "up")]:                          # (the start refused: the old way starts it)
                a.run = self.nmcli()
                real, state = a.run, {"refused": False}

                def run(cmd, timeout=20):
                    if cmd[1:3] == ["connection", "up"] and not state["refused"]:
                        state["refused"] = True
                        self.calls.append(cmd)
                        return 4, "Error: Connection activation failed"
                    return real(cmd, timeout)
                a.run = run
            self.assertTrue(net.start_hotspot(), refuse)
            self.assertIn(["nmcli", "connection", "modify", "sofa-box-setup", "802-11-wireless-security.pmf", "disable",
                           "ipv6.method", "disabled"], self.calls)
            self.assertTrue([c for c in self.calls if c[1:4] == ["device", "wifi", "hotspot"]])

    def test_the_command_is_one_debians_nmcli_takes(self):
        """Checked against Debian 13's own nmcli (1.52, `--offline`) wherever one is installed: the box's is the same."""
        if not shutil.which("nmcli"):
            self.skipTest("needs nmcli")
        a = self.agent
        a.run = self.nmcli()
        a.Network().start_hotspot()
        add = next(c for c in self.calls if c[1:3] == ["connection", "add"])
        p = subprocess.run(["nmcli", "--offline"] + add[1:], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("mode=ap", p.stdout)
        self.assertIn("pmf=1", p.stdout)


class ASteadyClock(unittest.TestCase):
    """A new card's clock starts from the day its system was made and is set right when the box is first online: in
    the middle of the setup, seconds after it joins the home Wi-Fi. Whatever asked "how long ago" by the clock took
    a moment for a month."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent", SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def test_the_join_stays_just_now_when_the_clock_is_set_right(self):
        a = self.agent
        real = a.time, a.network.joining, a.secure_remote.relay_base, a.secure_remote.relay_at, a.phone, a.run
        a.run = lambda cmd, timeout=20: (1, "")
        try:
            a.phone = a.PhoneRemote()
            a.network.joining = {"ssid": "HOME-D2CF", "state": "joined", "message": "Connected to HOME-D2CF.", "at": a.steady()}
            a.network.from_phone = a.steady()
            a.secure_remote.relay_base, a.secure_remote.relay_at = "https://boxcert.example/r/abc", a.steady()
            a.bluetooth.pause(20)
            before = a.steady()
            jump = 36.2 * 86400
            a.time = types.SimpleNamespace(time=lambda: time.time() + jump, sleep=time.sleep, monotonic=time.monotonic,
                                           strftime=time.strftime, localtime=time.localtime)   # timesyncd: +36 days
            self.assertLess(a.steady() - before, 5)
            state = a.setup_state()
            self.assertLess(state["now"] - state["network"]["joining"]["at"], 5)      # the TV: "joined a moment ago"
            self.assertLess(state["now"] - state["network"]["from_phone"], 5)
            self.assertEqual(a.secure_remote.url(), "https://boxcert.example/r/abc")   # the https code stays the code
            self.assertTrue(a.bluetooth.paused())
            a.network.joining = dict(a.network.joining, state="joining")
            self.assertTrue(a.network.is_joining())                                    # (no hotspot back mid-join)
        finally:
            a.time, a.network.joining, a.secure_remote.relay_base, a.secure_remote.relay_at, a.phone, a.run = real
            a.bluetooth.pause(0)

    def test_sofa_is_looked_for_as_soon_as_the_box_is_on_the_wifi(self):
        """Minutes after it started, the box looks for Sofa once a minute: Home could open after the setup without the
        Sofa that was on the Wi-Fi it had just joined."""
        a = self.agent
        real = a.run, a.secure_remote.wake, a.network.joining
        a.secure_remote.wake = lambda: None
        a.run = lambda cmd, timeout=20: (0, "wlan0:wifi" if cmd[-1] == "device" else "HOME-D2CF")
        a.looking["until"] = a.steady() - 500                              # (long past its first two minutes)
        a.looking["now"].clear()
        try:
            net = a.Network()
            net.find = lambda ssid, dev, limit=25: True
            self.assertTrue(net.join("HOME-D2CF", "correct-horse")["ok"])
            self.assertTrue(a.looking["now"].is_set())                         # the look loop wakes now
            self.assertGreater(a.looking["until"] - a.steady(), 100)           # and looks every few seconds for a while
        finally:
            a.run, a.secure_remote.wake, a.network.joining = real
            a.bluetooth.pause(0)
        src = read(os.path.join(BOX, "sofa-box-agent.py"))
        self.assertIn('looking["now"].wait(4 if steady() < looking["until"] else 60)', src)

    def test_nothing_in_the_hand_off_asks_the_clock_how_long_ago(self):
        src = read(os.path.join(BOX, "sofa-box-agent.py"))
        network = src.split("class Network:")[1].split("def on_own_wifi")[0]
        self.assertEqual(network.count("time.time()"), 1)                     # (the date kept on the card with the join)
        self.assertIn('kept = {"ssid": self.joining["ssid"], "at": time.time()}', network)
        for part in (src.split("    def url(self):\n        if self.relaying():")[1].split("def resolves_to")[0],
                     src.split("class RemoteHandler")[1].split("class InputQueue")[0],
                     src.split("def look(")[1].split("def ")[0]):
            self.assertNotIn("time.time()", part)
        js = read(os.path.join(BOX, "home", "home.js"))
        setup = js.split("function phoneBox()")[1].split("function viewWelcome()")[0]
        self.assertNotIn("Date.now()", setup)                                 # the agent's times: by the agent's clock
        self.assertIn("boxNow()", setup)
        self.assertEqual(js.count("Date.now()"), 2)                           # (boxNow's own fallback, and its comment)

    def test_the_phone_is_told_how_long_ago_in_seconds(self):
        """The phone's clock isn't the box's: a failed join comes with its age, not a time to compare."""
        src = read(os.path.join(BOX, "sofa-box-agent.py"))
        self.assertIn('"joining": network.joining and dict(network.joining, ago=round(', src)
        self.assertIn("j.ago < 300", read(os.path.join(BOX, "remote.html")))


class Power(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent", SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def test_the_report_says_it_in_words_in_its_first_lines(self):
        """The owner's Pi 3 B+: throttled=0x50000, on a weak supply."""
        a = self.agent
        words = a.power_words(a.power_note("throttled=0x50000", "Raspberry Pi 3 Model B Plus Rev 1.3"))
        self.assertIn("short of power (under-voltage) since it started, not right now", words)
        self.assertIn("slowed down by the Pi itself (throttled) since it started, not right now", words)
        self.assertIn("official 2.5 A power supply", words)
        self.assertIn("right now", a.power_words(a.power_note("throttled=0x50005", "Raspberry Pi 3")).split(";")[0])
        self.assertIn("enough all along", a.power_words(a.power_note("throttled=0x0")))
        self.assertIn("not read", a.power_words(None))
        src = read(os.path.join(BOX, "sofa-box-agent.py"))
        head = src.split("def report_text():")[1].split('"settings: "')[0]
        self.assertIn('"power: " + str(safely(power_words, power["note"]))', head)

    def test_the_setup_says_so_too(self):
        a = self.agent
        real = a.power["note"], a.phone, a.run
        a.run = lambda cmd, timeout=20: (1, "")
        try:
            a.phone = a.PhoneRemote()
            a.power["note"] = a.power_note("throttled=0x50000", "Raspberry Pi 3 Model B Plus Rev 1.3")
            self.assertEqual(a.setup_state()["power"]["kind"], "power")
            a.power["note"] = a.power_note("throttled=0x0")
            self.assertIsNone(a.setup_state()["power"])
        finally:
            a.power["note"], a.phone, a.run = real
        js = read(os.path.join(BOX, "home", "home.js"))
        self.assertIn('<div class="setup-power" id="setupPower">${setupPower()}</div>', js)
        self.assertIn('["setupPower", setupPower]', js)                       # (it shows without leaving the step)


FETCH_STUB = """
(() => {
  const real = window.fetch.bind(window);
  window.__answers = (() => { try { return JSON.parse(window.name) || {}; } catch (e) { return {}; } })();   // (kept by the tab)
  window.__asked = [];
  window.fetch = (url, opts) => {
    const path = String(url).replace(/^[a-z]+:\\/\\/[^/]*/, "").split("?")[0].replace(/^.*\\/(api\\/)/, "$1");
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    for (const key of Object.keys(window.__answers)) {
      if (!path.endsWith(key)) continue;
      window.__asked.push({ path: key, body });
      const a = window.__answers[key];
      if (a === "down") return Promise.reject(new TypeError("Load failed"));
      return Promise.resolve(new Response(JSON.stringify(a), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
    return real(url, opts);
  };
})();
"""


@unittest.skipUnless(chrome(), "needs Chrome or Chromium")
class TheTvAfterTheJoin(unittest.TestCase):
    """The box's home page at its setup, in a browser, with the agent's setup answers stood in for: the box has joined
    the home Wi-Fi, and its times are on a clock weeks away from the page's (as on a new card until it is online)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        conf, run = os.path.join(cls.dir, "conf"), os.path.join(cls.dir, "run")
        os.makedirs(conf)
        os.makedirs(run)
        with open(os.path.join(run, "sofa-box-display"), "w") as f:
            f.write("SCALE=2\n")
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": False, "weather": "off", "boot_sound": "off"}, f)
        cls.port, cls.devtools = free_port(), free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cls.dir, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(cls.port),
                                              SOFA_BOX_DEVTOOLS="0", XDG_RUNTIME_DIR=run, SOFA_BOX_UINPUT="0", SOFA_BOX_ICONS="0",
                                              SOFA_BOX_HOTSPOT="0", SOFA_BOX_CERTS="0", SOFA_BOX_NEWEST="0", SOFA_BOX_CAPTIVE_PORT="0",
                                              SOFA_BOX_REMOTE_PORT=str(free_port())))
        for _ in range(150):
            try:
                cls.state = json.loads(get(cls.base + "/box/api/setup", 5))
                break
            except (OSError, ValueError):
                time.sleep(0.2)
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1920,1080",
                                       "--remote-debugging-port=%d" % cls.devtools, "--user-data-dir=" + os.path.join(cls.dir, "profile"),
                                       "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.tab = Tab(cls.devtools)
        cls.tab.call("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=1, mobile=False)   # a 1080p TV
        cls.tab.call("Page.addScriptToEvaluateOnNewDocument", source=FETCH_STUB)

    @classmethod
    def tearDownClass(cls):
        cls.tab.close()
        cls.agent.terminate()
        cls.chrome.terminate()
        cls.agent.wait(10)
        cls.chrome.wait(10)
        shutil.rmtree(cls.dir, ignore_errors=True)

    AGO = 1791246680.0                                    # the box's clock at the join: 36 days before the page's

    def show(self, **changes):
        """The setup's first screen with the agent saying `changes` (on top of what a new box says)."""
        s = json.loads(json.dumps(self.state))
        s.update(now=self.AGO + 4, power=None)
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(s.get(key), dict):
                s[key].update(value)
            else:
                s[key] = value
        t = self.tab
        t.call("Page.navigate", url=self.base + "/box/home?t=%f" % time.time())
        t.until("!!window.__answers && document.readyState === 'complete'")
        t.value("window.name = JSON.stringify({ 'api/setup': %s }); 1" % json.dumps(s))     # (the page's first look too)
        t.call("Page.reload")
        t.until("!!window.__answers && !!window.__answers['api/setup'] && document.readyState === 'complete'")
        t.until("!!document.querySelector('#phoneBox') && !document.querySelector('#phoneBox .looking .spin + :not(span)') "
                "&& !/Getting ready/.test(document.querySelector('#phoneBox').innerText)")
        return t

    JOINED = {"ssid": "HOME-D2CF", "state": "joined", "message": "Connected to HOME-D2CF.", "at": AGO}
    HOME = {"url": "https://boxcert.example/r/abcdefghij", "pair_url": "https://boxcert.example/r/abcdefghij/r/" + "ab" * 12,
            "home_url": "http://10.0.0.87:8092", "code": "4125", "phones": 1, "home_at": 0, "hotspot": None, "wired": False, "problem": None}

    def fits(self, t):
        """The phone's step is whole on a 1080p TV: its code and words inside their card, the card over Start."""
        box = json.loads(t.value("JSON.stringify(['.way.phone .qr-row', '.way.phone', '.setup-nav .btn.primary'].map(q => "
                                 "(r => [Math.round(r.top), Math.round(r.bottom)])(document.querySelector(q).getBoundingClientRect())))"))
        self.assertLessEqual(box[0][1], box[1][1], box)
        self.assertLessEqual(box[1][1], box[2][0] + 1, box)

    def text(self, t):
        return " ".join(t.value("document.querySelector('#phoneBox').innerText").split())

    def test_the_last_step_stays_the_last_step(self):
        """It showed the plain first code ("Scan with your phone's camera, or open 10.0.0.87:8092 and type 4125"), its
        four steps gone, once the clock was set right: the join's time was a month before the page's."""
        t = self.show(remote=self.HOME, network={"wifi": "HOME-D2CF", "address": "10.0.0.87", "joining": self.JOINED,
                                                 "from_phone": self.AGO - 6}, secure={"state": "ready", "relay": True})
        said = self.text(t)
        self.assertIn("✓ The box is on HOME-D2CF", said)                      # what happened
        self.assertIn("Last step: scan this with your phone's camera", said)   # what to do next
        self.assertNotIn("and type", said)
        self.assertEqual(t.value("[...document.querySelectorAll('#phoneBox .code-steps li.done')].length"), 3)
        self.assertEqual(t.value("document.querySelector('#phoneBox .code-steps li.on').innerText.replace(/\\s+/g, ' ').trim()"),
                         "4 Keep the remote")
        self.assertTrue(t.value("!!document.querySelector('#phoneBox .qr svg')"))
        # the whole step is on the TV, over the bar with Start
        self.fits(t)

    def test_no_code_until_the_secure_one_is_ready_then_one(self):
        t = self.show(remote=dict(self.HOME, url="http://10.0.0.87:8092", pair_url="http://10.0.0.87:8092/r/" + "ab" * 12),
                      network={"wifi": "HOME-D2CF", "address": "10.0.0.87", "joining": self.JOINED, "from_phone": self.AGO - 6},
                      secure={"state": "working", "relay": True})
        said = self.text(t)
        self.assertIn("✓ The box is on HOME-D2CF", said)
        self.assertIn("Getting the last code ready for your phone", said)
        self.assertFalse(t.value("!!document.querySelector('#phoneBox .qr svg')"))
        # a minute on with the service still out of reach: the plain code, not five minutes of waiting
        t = self.show(now=self.AGO + 70, remote=dict(self.HOME, url="http://10.0.0.87:8092", pair_url="http://10.0.0.87:8092/r/" + "ab" * 12),
                      network={"wifi": "HOME-D2CF", "address": "10.0.0.87", "joining": self.JOINED, "from_phone": self.AGO - 6},
                      secure={"state": "error", "relay": True})
        self.assertTrue(t.value("!!document.querySelector('#phoneBox .qr svg')"))
        self.assertIn("Last step", self.text(t))
        self.fits(t)                                                         # (with its line about "not secure" too)

    def test_your_phone_is_the_remote_is_said_once(self):
        t = self.show(remote=dict(self.HOME, home_at=self.AGO + 3), network={"wifi": "HOME-D2CF", "address": "10.0.0.87",
                                                                              "joining": self.JOINED, "from_phone": self.AGO - 6},
                      secure={"state": "ready", "relay": True})
        self.assertEqual(self.text(t).count("Your phone is the remote"), 1)
        self.assertEqual(t.value("[...document.querySelectorAll('#phoneBox .code-steps li.done')].length"), 4)
        self.assertFalse(t.value("!!document.querySelector('#phoneBox .qr svg')"))    # nothing left to scan

    def test_a_join_that_failed_is_still_said_when_its_own_wifi_is_back(self):
        """A wrong password: the TV said so only until the box's own Wi-Fi was back, a few seconds."""
        hs = {"ssid": "Sofa Box 0211", "password": "12345678", "address": "10.42.0.1", "at": self.AGO + 2,
              "wifi_qr": "WIFI:T:WPA;S:Sofa Box 0211;P:12345678;;"}
        failed = dict(self.JOINED, state="failed", message="The password for HOME-D2CF isn't right.")
        for clients, phone_at, then in ((0, 0, "Scan this to connect your phone to it again"),
                                        (1, self.AGO + 3, "On your phone: put the password right, then Join.")):
            t = self.show(remote=dict(self.HOME, url="http://10.42.0.1:8092", pair_url="http://10.42.0.1:8092/r/" + "ab" * 12, hotspot=hs),
                          network={"hotspot": hs, "joining": failed, "clients": clients, "phone_at": phone_at})
            said = self.text(t)
            self.assertIn("✗ The password for HOME-D2CF isn't right.", said)
            self.assertIn(then, said)

    def test_short_of_power_shows_at_the_setup(self):
        note = {"kind": "power", "bits": "0x50000", "title": "The box is short of power",
                "text": "It can freeze or restart by itself. Plug it into the wall with its official 2.5 A power supply and a short cable."}
        t = self.show(power=note)
        t.until("!!document.querySelector('#setupPower .power-note')")
        self.assertIn("The box is short of power.", t.value("document.querySelector('#setupPower').innerText"))
        box = t.value("JSON.stringify((r => [r.left, r.right, r.top, r.bottom])(document.querySelector('#setupPower .power-note').getBoundingClientRect()))")
        left, right, top, bottom = json.loads(box)
        start = json.loads(t.value("JSON.stringify((r => [r.left, r.top])(document.querySelector('.setup-nav .btn.primary').getBoundingClientRect()))"))
        self.assertLess(right, start[0])                                     # beside Start, not under it
        self.assertLessEqual(bottom, 1080)
        t = self.show()
        self.assertEqual(t.value("document.querySelector('#setupPower').innerText.trim()"), "")


@unittest.skipUnless(chrome(), "needs Chrome or Chromium")
class ThePhonesPasswordSheet(unittest.TestCase):
    """The Setup Assistant (remote.html) at a phone's size, with the box's answers stood in for."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=500,900",
                                       "--allow-file-access-from-files", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), "about:blank"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.tab = Tab(cls.devtools)
        cls.tab.call("Emulation.setDeviceMetricsOverride", width=393, height=852, deviceScaleFactor=2, mobile=True)
        cls.tab.call("Page.addScriptToEvaluateOnNewDocument", source=FETCH_STUB)

    @classmethod
    def tearDownClass(cls):
        cls.tab.close()
        cls.chrome.terminate()
        cls.chrome.wait(10)
        shutil.rmtree(cls.dir, ignore_errors=True)

    NETS = [{"ssid": "HOME-D2CF", "signal": 82, "secure": True, "on": False}, {"ssid": "xfinitywifi", "signal": 60, "secure": False, "on": False}] + \
           [{"ssid": "Neighbour %d" % i, "signal": 50 - i, "secure": True, "on": False} for i in range(12)]

    def open(self, sheet=False, **state):
        t = self.tab
        says = dict({"paired": True, "name": "Sofa Box", "hotspot": True, "joining": None, "welcomed": False, "asleep": False,
                     "playing": None, "front": None}, **state)
        t.call("Page.navigate", url="file://" + os.path.join(BOX, "remote.html") + ("?sheet=1" if sheet else ""))
        t.until("!!window.__answers && document.readyState === 'complete'")
        t.value("window.name = JSON.stringify(%s); 1" % json.dumps({
            "api/state": says, "api/wifi": {"ok": True, "networks": self.NETS, "hotspot": says["hotspot"]}, "api/hello": {"ok": True},
            "api/wifi/join": {"ok": True, "pending": True, "message": "Joining…", "next": None}}))
        t.call("Page.reload")                                 # (again, with the box's answers there from its first look)
        t.until("!!window.__answers && !!window.__answers['api/state'] && document.readyState === 'complete'")
        return t

    def pick(self, t, ssid="HOME-D2CF"):
        t.until("document.querySelectorAll('.net').length > 2", 20)
        t.value("[...document.querySelectorAll('.net')].find(b => b.querySelector('span').textContent === %s).click(); 1" % json.dumps(ssid))
        t.until("!document.getElementById('ask').hidden")
        time.sleep(0.5)                                       # (placed again once the keyboard would be up)

    def middle(self, t):
        """How far the sheet's middle is from the middle of what the phone shows (its visual viewport)."""
        return t.value("(() => { const r = document.getElementById('askCard').getBoundingClientRect(), v = window.visualViewport;"
                       " return Math.abs((r.top + r.bottom) / 2 - v.height / 2); })()")

    def test_the_password_pops_up_in_the_middle_with_the_field_in_hand(self):
        t = self.open()
        self.pick(t)
        self.assertEqual(t.value("document.activeElement.id"), "wkey")        # focused as it opens: the keyboard comes up
        self.assertLess(self.middle(t), 3)
        self.assertEqual(t.value("document.getElementById('askName').textContent"), "HOME-D2CF")
        # nothing a phone takes for a sign-in: no password field, no "password" in what names the field
        self.assertEqual(t.value("document.querySelectorAll('input[type=password]').length"), 0)
        named = t.value("(f => [f.type, f.autocomplete, f.name, f.id, f.placeholder, f.getAttribute('aria-label'), f.getAttribute('autocapitalize'),"
                        " f.getAttribute('autocorrect'), String(f.spellcheck)].join('|'))(document.getElementById('wkey'))")
        self.assertTrue(named.startswith("text|off|"), named)
        self.assertNotRegex(named, r"(?i)pass|pwd|login|user")
        self.assertTrue(named.endswith("|none|off|false"), named)
        # the old box under the list is gone
        self.assertFalse(t.value("!!document.getElementById('join') || !!document.getElementById('wpass')"))

    def test_it_stays_in_the_middle_of_what_the_keyboard_leaves(self):
        """An iPhone's keyboard doesn't make the page shorter: it covers the bottom of it (the visual viewport shrinks,
        and may move). The sheet goes to the middle of what's left."""
        t = self.open()
        self.pick(t)
        t.value("(() => { const v = window.visualViewport; Object.defineProperty(v, 'height', { get: () => 430, configurable: true });"
                " Object.defineProperty(v, 'offsetTop', { get: () => 0, configurable: true }); v.dispatchEvent(new Event('resize')); })(); 1")
        time.sleep(0.4)
        r = json.loads(t.value("JSON.stringify((r => [r.top, r.bottom])(document.getElementById('askCard').getBoundingClientRect()))"))
        self.assertLess(abs((r[0] + r[1]) / 2 - 215), 3)
        self.assertGreaterEqual(r[0], 12)
        self.assertLessEqual(r[1], 430)                                       # the whole sheet above the keyboard
        t.value("(() => { const v = window.visualViewport; delete v.height; delete v.offsetTop; })(); 1")

    def test_what_is_typed_shows_and_is_kept_plain(self):
        t = self.open()
        self.pick(t)
        t.value("(f => { f.value = 'it\\u2019s\\u2014ok\\u2026 \\u201Cq\\u201D'; f.dispatchEvent(new Event('input', { bubbles: true })); })(document.getElementById('wkey')); 1")
        self.assertEqual(t.value("document.getElementById('wkey').value"), "it's--ok... \"q\"")
        self.assertFalse(t.value("document.getElementById('wkey').classList.contains('masked')"))   # shown, to see a slip
        t.value("document.getElementById('wshow').click(); 1")
        self.assertEqual(t.value("getComputedStyle(document.getElementById('wkey')).webkitTextSecurity"), "disc")
        self.assertEqual(t.value("document.getElementById('wshow').textContent"), "Show")

    def test_join_says_what_happens_next_and_a_wrong_password_comes_back(self):
        t = self.open()
        self.pick(t)
        t.value("document.getElementById('wkey').value = 'short'; document.getElementById('joinBtn').click(); 1")
        self.assertIn("at least 8 characters", t.value("document.getElementById('wifiMsg').textContent"))
        t.value("window.__asked = []; document.getElementById('wkey').value = 'wrong-horse'; document.getElementById('joinBtn').click(); 1")
        t.until("!document.getElementById('askGoing').hidden")
        asked = json.loads(t.value("JSON.stringify(window.__asked.filter(a => a.path === 'api/wifi/join'))"))
        self.assertEqual(asked, [{"path": "api/wifi/join", "body": {"ssid": "HOME-D2CF", "password": "wrong-horse"}}])
        said = " ".join(t.value("document.getElementById('askCard').innerText").split())
        self.assertIn("The box is joining HOME-D2CF", said)
        self.assertIn("Last step:", said)
        self.assertIn("scan the code", said)
        self.assertLess(self.middle(t), 3)
        # the box leaves its own Wi-Fi: the sheet stays as it is (it was a line under the list and a banner at the top)
        t.value("window.__answers['api/state'] = 'down'; 1")
        t.until("document.getElementById('dotText').textContent === \"Can't reach the box\"", 12)
        self.assertFalse(t.value("document.getElementById('askGoing').hidden"))
        # the password was wrong: the box's own Wi-Fi is back with the phone on it, and the sheet says why
        back = {"paired": True, "name": "Sofa Box", "hotspot": True, "welcomed": False, "asleep": False, "playing": None, "front": None,
                "joining": {"ssid": "HOME-D2CF", "state": "failed", "message": "The password for HOME-D2CF isn't right.", "at": 1791246680.5, "ago": 6.0}}
        t.value("window.__answers['api/state'] = %s; 1" % json.dumps(back))
        t.until("document.getElementById('wifiMsg').textContent.includes(\"isn't right\")", 12)
        self.assertTrue(t.value("document.getElementById('askGoing').hidden"))
        self.assertEqual(t.value("document.getElementById('wkey').value"), "wrong-horse")      # there to put right
        t.value("document.getElementById('askCancel').click(); 1")
        time.sleep(4.5)                                                       # (told once for each try, not at every look)
        self.assertTrue(t.value("document.getElementById('ask').hidden"))

    def test_in_the_sign_in_sheet_it_says_the_sheet_closes(self):
        t = self.open(sheet=True)
        self.pick(t)
        t.value("document.getElementById('wkey').value = 'correct-horse'; document.getElementById('joinBtn').click(); 1")
        t.until("!document.getElementById('askGoing').hidden")
        said = " ".join(t.value("document.getElementById('askCard').innerText").split())
        self.assertIn("this sheet closes by itself", said)
        self.assertIn("camera", said)

    def test_at_home_the_wifi_tab_says_how_it_went(self):
        """Not at the setup: the box already on a network, the remote's Wi-Fi tab moving it to another."""
        t = self.open(hotspot=False, welcomed=True)
        t.until("!document.getElementById('tabs').hidden")
        t.value("document.querySelector('#tabs [data-tab=wifi]').click(); 1")
        self.pick(t)
        t.value("document.getElementById('wkey').value = 'correct-horse'; document.getElementById('joinBtn').click(); 1")
        t.until("!document.getElementById('askGoing').hidden")
        self.assertIn("The TV shows how it goes", t.value("document.getElementById('askGoing').innerText"))
        joined = {"paired": True, "name": "Sofa Box", "hotspot": False, "welcomed": True, "asleep": False, "playing": None, "front": None,
                  "joining": {"ssid": "HOME-D2CF", "state": "joined", "message": "Connected to HOME-D2CF.", "at": 5.0, "ago": 1.0}}
        t.value("window.__answers['api/state'] = %s; 1" % json.dumps(joined))
        t.until("document.getElementById('askGoing').innerText.includes('✓ Connected to HOME-D2CF.')", 12)
        t.value("document.querySelector('#askGoing [data-ask-close]').click(); 1")
        self.assertTrue(t.value("document.getElementById('ask').hidden"))

    def test_an_open_network_asks_for_nothing(self):
        t = self.open()
        self.pick(t, "xfinitywifi")
        self.assertTrue(t.value("document.getElementById('askPw').hidden"))
        self.assertIn("no password", t.value("document.getElementById('askHint').textContent"))
        t.value("window.__asked = []; document.getElementById('joinBtn').click(); 1")
        t.until("!document.getElementById('askGoing').hidden")
        self.assertEqual(json.loads(t.value("JSON.stringify(window.__asked.filter(a => a.path === 'api/wifi/join')[0].body)")),
                         {"ssid": "xfinitywifi", "password": ""})


if __name__ == "__main__":
    unittest.main()
