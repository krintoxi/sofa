"""Sofa Box OS 1.1.51: the setup through a restart, the setup opening by itself, and the phone remote's speed.

What a 1.1.49 box did on a real Pi 3: joining the home Wi-Fi at the setup, it restarted by itself (Raspberry Pi OS
restarts a Pi whose system stops answering for a minute: its watchdog), then began the setup again from its first
screen, and the phone's Setup Assistant never opened by itself. These are the box's halves of the fixes; what only
the hardware can show (that the restart doesn't come back) is for a test on the Pi."""
import base64
import importlib.util
import json
import os
import re
import shutil
import tempfile
import threading
import time
import unittest
import http.client

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_agent(conf):
    old = {k: os.environ.get(k) for k in ("SOFA_BOX_CONF", "SOFA_BOX_DEVTOOLS", "SOFA_BOX_CAPTIVE_PORT", "SOFA_BOX_UINPUT")}
    os.environ.update(SOFA_BOX_CONF=conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")
    try:
        spec = importlib.util.spec_from_file_location("sofa_box_agent_setup", os.path.join(BOX, "sofa-box-agent.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)


class SetupThroughARestart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load_agent(cls.conf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def setUp(self):
        a = self.agent
        self.real = a.local_address, a.run, a.phone
        self.saved_wifi, self.started = ["Home"], []
        a.local_address = lambda: None
        a.run = lambda cmd, timeout=20: (0, "\n".join("%s:802-11-wireless" % n for n in self.saved_wifi))
        a.save_settings(welcomed=False)
        self.net = a.Network()
        self.net.start_hotspot = lambda: (self.started.append(self.now), setattr(self.net, "hotspot", {"at": self.now}))
        self.net.wired = lambda: False

    def tearDown(self):
        a = self.agent
        a.local_address, a.run, a.phone = self.real
        a.save_settings(welcomed=False)
        a.bluetooth.pause(0)
        try:
            os.remove(os.path.join(a.CONF_DIR, a.Network.KEPT))
        except OSError:
            pass

    def run_for(self, seconds, since=0):
        for self.now in range(since, since + seconds + 1, 10):
            self.offline = self.net.tick(self.offline, self.now)

    def test_a_box_restarted_mid_setup_waits_for_its_home_wifi(self):
        """It had joined the home Wi-Fi, then restarted: its own Wi-Fi came back after 15 seconds, before a Pi 3 had
        joined the home one again, took the Wi-Fi chip off it, and the setup began again. Now it gives the home Wi-Fi
        a minute and a half; a box that knows no Wi-Fi still makes its own in 15 seconds."""
        self.offline = 0
        self.run_for(80)
        self.assertEqual(self.started, [])                           # the home Wi-Fi's chance
        self.address = "192.168.1.30"
        self.agent.local_address = lambda: self.address
        self.run_for(10, 80)
        self.assertIsNone(self.offline)                              # joined it: no hotspot ever
        self.assertEqual(self.started, [])
        self.agent.local_address = lambda: None
        self.saved_wifi, self.started, self.offline = [], [], 0      # a new box: soon
        self.run_for(20)
        self.assertEqual(len(self.started), 1)

    def test_the_join_is_kept_and_the_setup_goes_on_after_a_restart(self):
        a = self.agent
        a.phone = a.PhoneRemote()
        self.net.joining = {"ssid": "HOME-D2CF", "state": "joined", "message": "Connected", "at": time.time()}
        self.net.keep_joined("ab" * 12)
        path = os.path.join(a.CONF_DIR, a.Network.KEPT)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        after = a.Network()                                          # the box restarted
        kept = after.resume()
        self.assertEqual(kept["link"], "ab" * 12)                    # the phone's carry-on link works after it too
        self.assertEqual((after.joining["ssid"], after.joining["state"]), ("HOME-D2CF", "joined"))
        self.assertTrue(after.joining.get("resumed"))
        self.assertLess(time.time() - after.joining["at"], 5)        # "just joined": the TV shows the last step
        self.assertTrue(after.from_phone)
        a.save_settings(welcomed=True)                               # the setup done: nothing to go on with
        self.assertIsNone(a.Network().resume())
        self.assertFalse(os.path.exists(path))

    def test_finishing_the_setup_forgets_the_kept_join(self):
        a = self.agent
        self.net.joining = {"ssid": "Home", "state": "joined", "at": time.time()}
        self.net.keep_joined()
        src = read(os.path.join(BOX, "sofa-box-agent.py"))
        self.assertRegex(src, r"boot_screen\.welcomed\(\)\s+try:\s+os\.remove\(os\.path\.join\(CONF_DIR, Network\.KEPT\)\)")
        self.assertIn("network.resume()", src)                       # at every start

    def test_a_used_carry_on_link_is_not_kept(self):
        a = self.agent
        a.phone, a.network.joining = a.PhoneRemote(), {"ssid": "Home", "state": "joined", "at": time.time()}
        real_toast = a.toast
        a.toast = lambda text: None
        try:
            a.phone.handoff_link = "cd" * 12
            a.network.keep_joined("cd" * 12)
            self.assertTrue(a.phone.pair("cd" * 12, "iPhone"))
            self.assertNotIn("link", json.loads(read(os.path.join(a.CONF_DIR, a.Network.KEPT))))
        finally:
            a.toast, a.network.joining = real_toast, None

    def test_bluetooth_rests_while_the_box_joins_a_wifi(self):
        """On a Pi 3 one chip does Wi-Fi and Bluetooth: the setup's first screen kept Bluetooth discovery going all
        through the join."""
        a, seen = self.agent, []

        def nmcli(cmd, timeout=20):
            if cmd[-1] == "device":
                return 0, "wlan0:wifi"
            if "connect" in cmd:
                seen.append(a.bluetooth.paused())                     # while it joins
                return 0, "Device 'wlan0' successfully activated"
            return 0, "Home"
        a.run = nmcli
        real_wake = a.secure_remote.wake
        a.secure_remote.wake = lambda: None
        try:
            self.net.find = lambda ssid, dev, limit=25: True
            self.assertTrue(self.net.join("Home", "pw")["ok"])
            self.assertEqual(seen, [True])
            self.assertTrue(a.bluetooth.paused())                   # a moment more, for its address there
            a.run = lambda cmd, timeout=20: (4, "Secrets were required") if "connect" in cmd else (0, "wlan0:wifi" if cmd[-1] == "device" else "")
            self.net.join("Home", "nope")
            self.assertFalse(a.bluetooth.paused())                  # it didn't work: free again at once
        finally:
            a.secure_remote.wake = real_wake
        src = read(os.path.join(BOX, "sofa-box-agent.py"))
        self.assertIn('if arg("scan") == "1" and not network.is_joining():', src)

    def test_its_own_wifi_has_a_new_name_on_each_card(self):
        """The name came from the Wi-Fi chip's address, the same each time the box was set up: a phone remembered that
        network (no internet, its sheet closed once) and the Setup Assistant didn't open by itself."""
        names = set()
        for _ in range(6):
            try:
                os.remove(os.path.join(self.conf, "hotspot.json"))
            except OSError:
                pass
            ssid, password = self.net.credentials("wlan0")
            self.assertRegex(ssid, r"^Sofa Box \d{4}$")
            self.assertRegex(password, r"^\d{8}$")
            names.add(ssid)
        self.assertGreater(len(names), 1)
        self.assertNotIn("local_mac(dev)", read(os.path.join(BOX, "sofa-box-agent.py")).split("def credentials")[1].split("def new_name")[0])

    def test_its_sign_in_page_is_up_before_a_phone_can_join(self):
        a, calls, order = self.agent, [], []
        real_start, real_sleep = a.captive.start, a.time.sleep
        a.captive.start = lambda: order.append("captive")

        def nmcli(cmd, timeout=20):
            calls.append(cmd)
            if "hotspot" in cmd:
                order.append("hotspot")
            if cmd[-1] == "device":
                return 0, "wlan0:wifi"
            return 0, ""
        a.run, a.time.sleep = nmcli, (lambda s: None)
        try:
            net = a.Network()
            self.assertTrue(net.start_hotspot())
            self.assertEqual(order[:2], ["captive", "hotspot"])
            self.assertIn(["nmcli", "connection", "modify", "sofa-box-setup", "802-11-wireless-security.pmf", "disable",
                           "ipv6.method", "disabled"], calls)
        finally:
            a.captive.start, a.time.sleep = real_start, real_sleep


class SetupOpensByItself(unittest.TestCase):
    def test_home_waits_for_the_agent_to_say_the_box_is_new(self):
        js = read(os.path.join(BOX, "home", "home.js"))
        self.assertIn("data.welcomed === undefined && i < 40", js)              # asked again until it answers
        self.assertIn('if (data.welcomed === false) { if (!location.hash.startsWith("#/welcome")) location.hash = "#/welcome";', js)
        self.assertNotIn('if (data.welcomed === false && !location.hash) { location.hash = "#/welcome"', js)

    def test_back_closes_the_wifi_password_at_the_setup(self):
        js = read(os.path.join(BOX, "home", "home.js"))
        welcome = re.search(r'if \(location\.hash\.startsWith\("#/welcome"\)\) \{([^\n]*)', js).group(1)
        self.assertIn("if (closeSheet()) return;", welcome)

    def test_the_tv_keyboard_has_its_button_on_the_keys(self):
        js, css = read(os.path.join(BOX, "home", "home.js")), read(os.path.join(BOX, "home", "home.css"))
        self.assertIn('kbHtml("Join", "join", true)', js)                         # Join on the keyboard's last row
        self.assertIn('<button class="kb-key done" data-sheet=', js)
        self.assertIn('id="kbText" type="text"', js)                               # the password readable as it's typed
        self.assertIn(".kb-row.last.with-hide", css)
        self.assertIn('id="i-wifi"', read(os.path.join(BOX, "home", "index.html")))

    def test_the_phone_code_shows_as_soon_as_the_phone_joins(self):
        js = read(os.path.join(BOX, "home", "home.js"))
        self.assertNotIn("now - joinedAt < 20", js)


class RemoteSpeed(unittest.TestCase):
    """Each press is answered at once and done in order on the box; through the relay, presses don't go round
    through a second request on the box."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load_agent(cls.conf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def setUp(self):
        a = self.agent
        self.real = a.browser, a.phone
        self.pressed = []
        test = self

        class SlowBrowser:                                          # Chromium on a Pi 3, taking its time
            def connected(self):
                return True

            def front_app(self):
                return "home"

            def press(self, key, code):
                time.sleep(0.05)
                test.pressed.append(key)

            def insert_text(self, t):
                test.pressed.append("text:" + t)
        a.browser = SlowBrowser()
        a.phone = a.PhoneRemote()
        self.token = "ab" * 24
        a.write_durably(a.phone.path, json.dumps({self.token: {"name": "test", "at": 1}}), 0o600)

    def tearDown(self):
        self.agent.browser, self.agent.phone = self.real

    def wait_for(self, n, seconds=5):
        end = time.time() + seconds
        while len(self.pressed) < n and time.time() < end:
            time.sleep(0.01)

    def test_presses_are_answered_at_once_and_done_in_order(self):
        a = self.agent
        self.assertTrue(a.RemoteHandler.disable_nagle_algorithm and a.Handler.disable_nagle_algorithm)
        srv = a.Server(("127.0.0.1", 0), a.RemoteHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            hdr = {"Content-Type": "application/json", "X-Sofa-Remote": "1", "Cookie": "sofa_remote=" + self.token}
            keys, took = ["down", "down", "right", "ok", "back"], []
            for k in keys:
                t = time.perf_counter()
                c.request("POST", "/api/key", json.dumps({"k": k}), hdr)
                r = c.getresponse()
                r.read()
                took.append(time.perf_counter() - t)
                self.assertEqual(r.status, 200)
            self.assertLess(max(took), 0.04)                         # not after the browser's 50 ms
            self.wait_for(len(keys))
            self.assertEqual(self.pressed, ["ArrowDown", "ArrowDown", "ArrowRight", "Enter", "Escape"])
            c.request("POST", "/api/key", json.dumps({"k": "sideways"}), hdr)
            r = c.getresponse()
            self.assertEqual((r.status, json.loads(r.read())["error"]), (400, "Which key?"))
            c.request("POST", "/api/key", json.dumps({"k": "down"}), dict(hdr, Cookie="sofa_remote=" + "00" * 24))
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 401)                          # not paired: nothing pressed
            c.close()
        finally:
            srv.shutdown()
            srv.server_close()

    def test_an_answer_is_one_write(self):
        """Headers and body in one write: with two, Nagle's algorithm held the body until the phone acknowledged the
        headers (up to 200 ms on a phone)."""
        a, writes = self.agent, []

        class Fake(a.Handler):
            def __init__(self):
                self.request_version, self.command, self._headers_buffer = "HTTP/1.1", "POST", []
                self.requestline, self.client_address = "POST /x HTTP/1.1", ("127.0.0.1", 1)

                class W:
                    def write(self, b):
                        writes.append(b)
                self.wfile = W()
        Fake().send('{"ok":true}')
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].startswith(b"HTTP/1.1 200") and writes[0].endswith(b'\r\n\r\n{"ok":true}'))

    def test_the_relay_presses_on_the_box_itself(self):
        a, answers = self.agent, []
        sr = a.SecureRemote()
        sr._answer = lambda acct, req, status, keep, data: answers.append((req["rid"], status, data))
        sr._relay_one = lambda acct, req: answers.append(("loopback", req["rid"]))

        def req(rid, body, cookie=None, path="/api/key"):
            return {"rid": rid, "method": "POST", "path": path, "body": base64.b64encode(json.dumps(body).encode()).decode(),
                    "headers": {"Cookie": "sofa_remote=" + (cookie or self.token), "X-Sofa-Remote": "1", "Content-Type": "application/json"}}
        acct = {"id": "box", "secret": "s"}
        for i, k in enumerate(["up", "left", "ok"]):
            self.assertTrue(sr._relay_input(acct, req("r%d" % i, {"k": k})))
        self.assertTrue(sr._relay_input(acct, req("t", {"t": "hi"}, path="/api/text")))
        self.wait_for(4)
        self.assertEqual(self.pressed, ["ArrowUp", "ArrowLeft", "Enter", "text:hi"])
        end = time.time() + 5
        while len(answers) < 4 and time.time() < end:
            time.sleep(0.01)
        self.assertEqual(sorted((r, s) for r, s, _ in answers), [("r0", 200), ("r1", 200), ("r2", 200), ("t", 200)])
        self.assertFalse(sr._relay_input(acct, req("x", {"k": "up"}, cookie="00" * 24)))     # not paired: the remote says no
        self.assertFalse(sr._relay_input(acct, dict(req("y", {}), method="GET", path="/api/state")))
        self.assertEqual(len(sr.relay_threads), 0)
        self.assertIsNot(sr.polls, sr.polls2)                        # two waiting at the service, one answering

    def test_the_phone_presses_on_touch(self):
        page = read(os.path.join(BOX, "remote.html"))
        self.assertIn('document.addEventListener("pointerdown", e => {', page)
        self.assertIn("if (e.detail === 0)", page)                   # a click with no pointer still presses
        self.assertIn("Math.hypot(dx, dy) > 26", page)               # a shorter swipe is a step
        self.assertNotIn("font: 18px/1.45 inherit", page)

    def test_the_browser_gets_the_key_without_a_round_trip_first(self):
        src = read(os.path.join(BOX, "boxos.py"))
        press = src[src.index("    def press(self, key, keycode):"):src.index("    def insert_text")]
        self.assertIn('self.tell("Input.dispatchKeyEvent", events[0], session)', press)
        self.assertEqual(press.count("self.call("), 1)


if __name__ == "__main__":
    unittest.main()
