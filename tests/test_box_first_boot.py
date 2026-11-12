"""Sofa Box OS 1.1.56: a card that reaches the TV's setup whatever is done in Raspberry Pi Imager, a calm note on Home
when the Pi is short of power or hot, and the right address under the setup's QR code.

What Raspberry Pi Imager writes (read in its source, 2026-11-10):
- Imager 2 (2.0.12) with "Use custom": nothing. A local file carries no `init_format`, so it offers no customisation.
- Imager 2 from a list (Raspberry Pi OS Lite, Trixie: `init_format` cloudinit-rpi): `user-data` (a singular `user:`,
  `hostname` with `manage_etc_hosts: true`, `packages: [avahi-daemon]`, the time zone and keyboard, `ssh_pwauth`, and
  `runcmd: systemctl enable --now ssh`), `network-config` (netplan: eth0 by DHCP, wlan0 with the Wi-Fi), `meta-data`
  (a new instance-id), and `cfg80211.ieee80211_regdom=XX ds=nocloud;i=…` on cmdline.txt.
- Imager 1.8 and 1.9 with "Use custom": "auto". This card has Raspberry Pi OS's own `user-data` on its boot partition,
  so cloud-init: a `users:` list with the name, groups and password hash, and `network-config`. A card without
  `user-data` (pi-gen's issue.txt) would get `firstrun.sh` instead, run by `systemd.run=` after the initramfs's
  imager_fixup points it at /boot/firmware; it calls userconf too.

Either way the user is made by Raspberry Pi OS's userconf (cloud-init's raspberry-pi-os distro calls it for the first
user), which ends with cancel-rename (userconf-pi 0.19): on a box with no lightdm, `raspi-config nonint
do_boot_behaviour B1` (set-default multi-user.target), `systemctl enable getty@tty1`, and `systemctl --no-block start
getty@tty1`, which stops Sofa's screen (sofa-box.service conflicts with it). cloud-init does it in its network stage,
before sysinit.target: before sofa-box-tune, which puts it right (`sofa-box own-screen`)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request

from tests.test_sofa_box import chrome, free_port, load as load_box

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")
SOFA_BOX = os.path.join(BOX, "sofa-box")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_agent(conf):
    old = {k: os.environ.get(k) for k in ("SOFA_BOX_CONF", "SOFA_BOX_DEVTOOLS", "SOFA_BOX_CAPTIVE_PORT", "SOFA_BOX_UINPUT")}
    os.environ.update(SOFA_BOX_CONF=conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")
    try:
        spec = importlib.util.spec_from_file_location("sofa_box_agent_first_boot", os.path.join(BOX, "sofa-box-agent.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)


# A stand-in for systemctl: units enabled are files in $FAKE_SYSTEMD/enabled, the default target is $FAKE_SYSTEMD/default,
# and starts are written down in $FAKE_SYSTEMD/started.
FAKE_SYSTEMCTL = r"""#!/bin/sh
D="$FAKE_SYSTEMD"
echo "$*" >> "$D/calls"
args=""
for a in "$@"; do case "$a" in --quiet|--no-block|-q) ;; *) args="$args $a" ;; esac; done
set -- $args
u="${2:-}"; case "$u" in *.*|"") ;; *) u="$u.service" ;; esac
set -- "$1" "$u"
case "$1" in
  get-default) cat "$D/default" ;;
  set-default) echo "$2" > "$D/default" ;;
  is-enabled) [ -e "$D/enabled/$2" ] ;;
  enable) touch "$D/enabled/$2" ;;
  disable) rm -f "$D/enabled/$2" ;;
  start) echo "$2" >> "$D/started" ;;
  *) exit 0 ;;
esac
"""


class ImagerSettings(unittest.TestCase):
    """The box's half: after Raspberry Pi OS's cancel-rename has had its way, the TV's screen is Sofa's again."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.state = os.path.join(self.d, "systemd")
        os.makedirs(os.path.join(self.state, "enabled"))
        bin_dir = os.path.join(self.d, "bin")
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "systemctl"), "w") as f:
            f.write(FAKE_SYSTEMCTL)
        os.chmod(os.path.join(bin_dir, "systemctl"), 0o755)
        with open(os.path.join(self.state, "default"), "w") as f:
            f.write("graphical.target\n")
        for unit in ("sofa-box.service", "sofa-box-agent.service"):                  # the card as GitHub builds it
            open(os.path.join(self.state, "enabled", unit), "w").close()
        self.hosts = os.path.join(self.d, "hosts")
        with open(self.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"], FAKE_SYSTEMD=self.state,
                        SOFA_BOX_HOSTS=self.hosts, SOFA_BOX_SHIELD_KEPT=os.path.join(self.d, "kept", "shield.hosts"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def systemctl(self, *args):
        subprocess.run(["systemctl"] + list(args), env=self.env, check=False)

    def cancel_rename(self):
        """What userconf-pi 0.19's cancel-rename does on this card (no lightdm: raspi-config's get_boot_cli says console)."""
        self.systemctl("--quiet", "set-default", "multi-user.target")         # raspi-config nonint do_boot_behaviour B1
        self.systemctl("--quiet", "disable", "userconfig")
        self.systemctl("--quiet", "enable", "getty@tty1")
        self.systemctl("--quiet", "--no-block", "start", "getty@tty1")

    def own_screen(self):
        r = subprocess.run(["sh", SOFA_BOX, "own-screen"], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def started(self):
        try:
            return read(os.path.join(self.state, "started")).split()
        except OSError:
            return []

    def test_after_imagers_user_the_tv_is_sofas_again(self):
        self.cancel_rename()
        said = self.own_screen()
        self.assertEqual(read(os.path.join(self.state, "default")).strip(), "graphical.target")
        self.assertFalse(os.path.exists(os.path.join(self.state, "enabled", "getty@tty1.service")))
        self.assertTrue(os.path.exists(os.path.join(self.state, "enabled", "sofa-box.service")))
        self.assertEqual(self.started(), ["getty@tty1.service", "sofa-box.service"])   # (its start takes the login's place)
        self.assertIn("The TV's screen is the box's again", said)
        self.assertIn("not multi-user.target", said)
        self.assertTrue(said.startswith("<4>"))                                    # a warning in the log: reports have it

    def test_a_box_as_it_should_be_is_left_alone(self):
        self.assertEqual(self.own_screen(), "")
        self.assertEqual(self.started(), [])
        calls = read(os.path.join(self.state, "calls"))
        self.assertNotIn("set-default", calls)
        self.assertNotIn("disable", calls)

    def test_the_desktop_keeps_its_screen(self):
        """`sofa-box desktop` turned Sofa's screen off: the console and the login are what's wanted then."""
        os.remove(os.path.join(self.state, "enabled", "sofa-box.service"))
        self.cancel_rename()
        self.own_screen()
        self.assertEqual(read(os.path.join(self.state, "default")).strip(), "multi-user.target")
        self.assertTrue(os.path.exists(os.path.join(self.state, "enabled", "getty@tty1.service")))
        self.assertEqual(self.started(), ["getty@tty1.service"])

    def test_at_every_start_and_after_cloud_init(self):
        """tune (every start) runs it. Its unit has systemd's default dependencies: after sysinit.target, so after
        cloud-init's network stage, which makes Imager's user (cloud-init-network.service: Before=sysinit.target).
        cloud-init's last stage runs it once more (anything its runcmd did), and its work there comes after the TV's."""
        box = read(SOFA_BOX)
        tune = box.split("\n  tune)", 1)[1].split(";;", 1)[0]
        self.assertIn("own_screen", tune)
        self.assertIn("shield back", tune)
        install = read(os.path.join(BOX, "install.sh"))
        unit = install.split("sofa-box-tune.service <<EOF", 1)[1].split("\nEOF", 1)[0]
        self.assertNotIn("DefaultDependencies=no", unit)
        self.assertIn("WantedBy=multi-user.target", unit)
        final = install.split("cloud-final.service.d/sofa-box.conf <<EOF", 1)[1].split("\nEOF", 1)[0]
        self.assertIn("ExecStartPost=-$LIB/sofa-box own-screen", final)
        self.assertIn("touch /etc/cloud/cloud-init.disabled", final)                # (cloud-init: the first start only)
        self.assertIn("set-property --runtime cloud-init-main.service CPUWeight=10", final)
        self.assertIn("systemctl disable userconfig.service", read(os.path.join(HERE, "tools", "build-sofa-box-image.sh")))
        # no login on the TV's screen from the start: systemd's presets enable getty@tty1 at a card's first start (seen
        # booting the 1.1.54 card), and it's off on a box set up over an older Raspberry Pi OS
        self.assertIn('echo "disable getty@.service" > /etc/systemd/system-preset/10-sofa-box.preset', install)
        self.assertIn("systemctl disable getty@tty1.service", install)

    def test_sofa_shield_comes_back_after_cloud_init_rewrites_hosts(self):
        """Imager's host name comes with `manage_etc_hosts: true`: cloud-init writes /etc/hosts from its template at the
        first start, and Sofa Shield's list was gone (Settings said it was off, and its weekly update stopped)."""
        blocklist = os.path.join(self.d, "list")
        with open(blocklist, "w") as f:
            f.write("".join("0.0.0.0 ads%d.example.com\n" % i for i in range(1200)))
        env = dict(self.env, SOFA_BOX_SHIELD_LIST="file://" + blocklist)
        subprocess.run(["sh", SOFA_BOX, "shield", "on"], env=env, check=True, stdout=subprocess.DEVNULL)
        with open(self.hosts, "w") as f:                                         # cloud-init's hosts.debian.tmpl
            f.write("127.0.1.1 livingroom livingroom\n127.0.0.1 localhost\n\n::1 localhost ip6-localhost ip6-loopback\n")
        for _ in range(2):                                                        # at every start: once, not twice
            subprocess.run(["sh", SOFA_BOX, "shield", "back"], env=env, check=True, stdout=subprocess.DEVNULL)
        text = read(self.hosts)
        self.assertTrue(text.startswith("127.0.1.1 livingroom livingroom\n"))      # cloud-init's lines stay
        self.assertEqual(text.count("# >>> Sofa Shield"), 1)
        self.assertEqual(text.count("0.0.0.0 ads"), 1200)
        subprocess.run(["sh", SOFA_BOX, "shield", "off"], env=env, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["sh", SOFA_BOX, "shield", "back"], env=env, check=True, stdout=subprocess.DEVNULL)
        self.assertNotIn("Sofa Shield", read(self.hosts))                         # switched off: it stays off

    def test_a_reset_forgets_imagers_wifi_and_the_card_says_what_it_has(self):
        box = read(SOFA_BOX)
        reset = box.split("\n  factory-reset)", 1)[1].split(";;", 1)[0]
        self.assertIn("rm -f /etc/netplan/50-cloud-init.yaml", reset)
        build = read(os.path.join(HERE, "tools", "build-sofa-box-image.sh"))
        for pkg in ("cloud-init", "userconf-pi", "raspberrypi-sys-mods", "rpi-preseed"):   # the first-start tools, in the report
            self.assertIn(pkg, build)
        self.assertIn("is-enabled getty@tty1", build)
        guide = read(os.path.join(BOX, "README.md"))
        self.assertNotIn("Leave **Set username and password** unticked", guide)


class PowerNote(unittest.TestCase):
    """The Pi's own record (vcgencmd get_throttled), from sample values, as Home and Settings → Help say it."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load_agent(cls.conf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def setUp(self):
        self.agent.power.update(note=None, shown=False)

    def test_sample_values(self):
        note = self.agent.power_note
        pi3 = "Raspberry Pi 3 Model B Plus Rev 1.3"
        self.assertEqual(note("throttled=0x0", pi3), {"kind": "ok", "bits": "0x0"})
        self.assertIsNone(note("VCHI initialization failed", pi3))
        self.assertIsNone(note("", pi3))
        for value in ("throttled=0x50005", "throttled=0x50000", "throttled=0x1", "throttled=0x10000"):   # bits 0 and 16
            n = note(value, pi3)
            self.assertEqual(n["kind"], "power", value)
            self.assertEqual(n["title"], "The box is short of power")
            self.assertIn("official 2.5 A power supply", n["text"])
            self.assertNotIn("hot", n["text"])
        for value in ("throttled=0x80000", "throttled=0x80008", "throttled=0x40000", "throttled=0x20002"):  # heat, power enough
            n = note(value, pi3)                                                  # (0x80000: the owner's 1.1.34 report)
            self.assertEqual(n["kind"], "heat", value)
            self.assertEqual(n["title"], "The box got hot and slowed itself down")
            self.assertIn("Leave air around it", n["text"])
        both = note("throttled=0xd0005", pi3)                                     # short of power, and hot
        self.assertEqual(both["kind"], "power")
        self.assertIn("It got hot too", both["text"])
        self.assertEqual(note("throttled=0x50005", pi3)["bits"], "0x50005")
        self.assertIn("3 A USB-C", note("throttled=0x50000", "Raspberry Pi 4 Model B Rev 1.5")["text"])
        self.assertIn("27 W (5 A) USB-C", note("throttled=0x50000", "Raspberry Pi 5 Model B Rev 1.0")["text"])
        self.assertIn("its official power supply", note("throttled=0x50000", "")["text"])

    def test_watched_every_minute(self):
        a, logged = self.agent, []
        values = iter([(0, "throttled=0x0"), (0, "throttled=0x80000"), (0, "throttled=0x80000"), (0, "throttled=0xd0005"),
                       (1, "vcgencmd: not found")])
        real = a.run, a.time, a.sys
        a.run = lambda cmd, timeout=20: next(values) if cmd == ["vcgencmd", "get_throttled"] else (1, "")
        a.time = types.SimpleNamespace(sleep=lambda s: None, time=time.time)
        a.sys = types.SimpleNamespace(stderr=types.SimpleNamespace(write=logged.append, flush=lambda: None))
        try:
            a.watch_power()                                                       # (ends where vcgencmd isn't: not a Pi)
        finally:
            a.run, a.time, a.sys = real
        self.assertEqual(a.power["note"]["kind"], "power")
        lines = [x for x in "".join(logged).splitlines() if x]
        self.assertEqual(len(lines), 2)                                           # once a change, for the reports
        self.assertIn("got hot", lines[0])
        self.assertIn("short of power", lines[1])

    def test_home_hears_it_once_a_start(self):
        a = self.agent
        httpd = a.Server(("127.0.0.1", 0), a.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def get(path):
            req = urllib.request.Request(base + path, headers={"Host": "127.0.0.1"})
            with opener.open(req, timeout=20) as r:
                return json.loads(r.read())
        try:
            self.assertIsNone(get("/box/api/apps")["power"])                      # nothing known yet
            a.power["note"] = a.power_note("throttled=0x0")
            self.assertIsNone(get("/box/api/apps")["power"])                      # fine: nothing on Home
            self.assertEqual(get("/box/api/info")["power"]["kind"], "ok")         # Settings → Help: all fine
            a.power["note"] = a.power_note("throttled=0x50005")
            self.assertEqual(get("/box/api/apps")["power"]["kind"], "power")
            with self.assertRaises(urllib.error.HTTPError) as e:                  # a plain GET doesn't count as seen
                get("/box/api/power/seen")
            self.assertEqual(e.exception.code, 405)
            req = urllib.request.Request(base + "/box/api/power/seen", data=b"{}", headers={
                "Host": "127.0.0.1", "Content-Type": "application/json", "X-Sofa-Box": "1"})
            with opener.open(req, timeout=20) as r:
                self.assertEqual(json.loads(r.read()), {"ok": True})
            self.assertIsNone(get("/box/api/apps")["power"])                      # shown: not again this start
            self.assertEqual(get("/box/api/info")["power"]["kind"], "power")      # Settings → Help still says it
        finally:
            httpd.shutdown()
            httpd.server_close()


class TypedCodeHint(unittest.TestCase):
    """Under the setup's QR code, "or open <address> and type <code>": the box's own address at home. With the relay
    on, the remote's address is the relay's, which refuses typed codes ("Away from home, scan the code on the TV")."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load_agent(cls.conf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def test_the_home_address_never_the_relays(self):
        a = self.agent
        real = a.local_address, a.secure_remote.relay_base, a.secure_remote.relay_at, a.network.hotspot, a.SecureRemote.url
        relay = "https://relay.box.example/r/0123abcd"
        try:
            a.network.hotspot = None
            a.secure_remote.relay_base, a.secure_remote.relay_at = relay, time.time()
            a.SecureRemote.url = lambda self: relay                               # the relay is on (the default)
            a.local_address = lambda: "192.168.1.30"
            phone = a.PhoneRemote()
            st = phone.status()
            self.assertEqual(st["url"], relay)                                    # the QR code: the relay, from anywhere
            self.assertTrue(st["pair_url"].startswith(relay + "/r/"))
            self.assertEqual(st["home_url"], "http://192.168.1.30:%d" % a.PhoneRemote.PORT)   # typing: at home
            a.local_address = lambda: None                                        # only the relay's address known
            self.assertIsNone(phone.status()["home_url"])
            mine = "https://0123abcd.box.edgeventure.uk:8093"                    # the box's own name and certificate
            a.SecureRemote.url = lambda self: mine
            a.local_address = lambda: "192.168.1.30"
            self.assertEqual(phone.status()["home_url"], mine)                    # (at home, typing works there)
            a.network.hotspot = {"address": "10.42.0.1", "ssid": "Sofa Box 1234", "password": "x"}
            self.assertEqual(phone.status()["home_url"], "http://10.42.0.1:%d" % a.PhoneRemote.PORT)   # its own Wi-Fi
        finally:
            (a.local_address, a.secure_remote.relay_base, a.secure_remote.relay_at, a.network.hotspot,
             a.SecureRemote.url) = real


@unittest.skipUnless(chrome(), "needs Chrome or Chromium")
class HomeScreen(unittest.TestCase):
    """Home and Settings in a real browser: the power note (a box whose vcgencmd says 0x50005), and the hint under the QR
    code with the relay on."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        conf = os.path.join(cls.dir, "conf")
        bin_dir = os.path.join(cls.dir, "bin")
        os.makedirs(conf)
        os.makedirs(bin_dir)
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": True}, f)
        with open(os.path.join(bin_dir, "vcgencmd"), "w") as f:                  # the Pi's record: short of power
            f.write("#!/bin/sh\n[ \"$1\" = get_throttled ] && echo throttled=0x50005 || exit 1\n")
        os.chmod(os.path.join(bin_dir, "vcgencmd"), 0o755)
        run = os.path.join(cls.dir, "run")
        os.makedirs(run)
        cls.port, cls.devtools = free_port(), free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1920,1080",
                                       "--remote-debugging-port=%d" % cls.devtools, "--user-data-dir=" + os.path.join(cls.dir, "profile"),
                                       cls.base + "/box/home"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cls.dir, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(cls.port),
                                              SOFA_BOX_DEVTOOLS=str(cls.devtools), XDG_RUNTIME_DIR=run, SOFA_BOX_UINPUT="0",
                                              SOFA_BOX_HOTSPOT="0", SOFA_BOX_NEWEST="0", SOFA_BOX_CERTS="0", SOFA_BOX_ICONS="0",
                                              SOFA_BOX_REMOTE_PORT=str(free_port()),
                                              PATH=bin_dir + os.pathsep + os.environ["PATH"]))
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(300):
            try:
                with cls.opener.open(cls.base + "/box/api/apps", timeout=20) as r:
                    if json.loads(r.read())["devtools"]:
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

    def page(self, expression):
        boxos = load_box("boxos")
        with self.opener.open("http://127.0.0.1:%d/json/list" % self.devtools, timeout=10) as r:
            tab = next(p for p in json.loads(r.read()) if p["type"] == "page" and "/box/home" in p["url"])
        ws = boxos.WebSocket(tab["webSocketDebuggerUrl"])
        try:
            ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True,
                                                                                    "awaitPromise": True}}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == 1:
                    return m["result"]["result"].get("value")
        finally:
            ws.close()

    def until(self, expression, seconds=40):
        end, value = time.time() + seconds, None
        while time.time() < end:
            value = self.page(expression)
            if value:
                return value
            time.sleep(0.4)
        self.fail("never: %s (%r)" % (expression, value))

    def test_1_power_note_on_home_once_a_start(self):
        note = self.until("(document.querySelector('#view .mast .power-note, #view .spt-detail .power-note') || {}).textContent")   # (Classic, or Spotlight)
        self.assertIn("The box is short of power.", note)
        self.assertIn("Plug it into the wall", note)
        self.assertFalse(self.page("!!(document.activeElement && document.activeElement.closest('.power-note'))"))   # not in the way
        self.assertTrue(self.page("!!document.activeElement.closest('.mast .row-actions, .spt .spt-track')"))   # first press: as ever
        self.page("location.hash = '#/store'")
        self.until("document.documentElement.dataset.page === 'store'")
        self.page("location.hash = '#/'")
        self.until("document.documentElement.dataset.page === 'home' && !!document.querySelector('#view .mast, #view .spt')")
        time.sleep(6)                                                             # (Home looks again every 5 seconds)
        self.assertFalse(self.page("!!document.querySelector('.power-note')"))     # seen: not again this start
        with self.opener.open(self.base + "/box/api/apps", timeout=20) as r:
            self.assertIsNone(json.loads(r.read())["power"])
        self.page("location.hash = '#/settings/help'")
        help_ = self.until("(document.querySelector('#setPane .power-help') || {}).textContent")
        self.assertIn("Power and heat", help_)
        self.assertIn("The box is short of power", help_)
        self.assertIn("0x50005", help_)

    def setup_says(self, remote):
        """The phone remote's box in Settings → Remotes, with the agent's answer about the remote stood in for."""
        answer = {"remote": dict({"code": "4821", "hotspot": None, "home_at": 0, "phones": 0, "wired": True, "problem": None}, **remote),
                  "network": {"wired": True}, "secure": {"state": "ready", "relay": True, "where": "relay.box.example"},
                  "bluetooth": {"devices": []}, "timezone": "Europe/London"}
        self.page("""window.__setup = %s; window.__served = 0; if (!window.__fetch) { window.__fetch = window.fetch;
          window.fetch = (u, o) => String(u).startsWith('/box/api/setup') ? (window.__served++, Promise.resolve(new Response(
            JSON.stringify(window.__setup), {status: 200, headers: {'Content-Type': 'application/json'}}))) : window.__fetch(u, o); }
          location.hash = '#/'; true""" % json.dumps(answer))
        self.until("document.documentElement.dataset.page === 'home'")
        self.page("location.hash = '#/settings/remotes'")
        self.until("window.__served >= 2")                                    # (the box's box redrawn from the answer)
        return self.until("(document.querySelector('#phoneBox .qr-text') || {}).textContent")

    def test_2_the_hint_under_the_qr_code(self):
        relay = "https://relay.box.example/r/0123abcd"
        said = self.setup_says({"url": relay, "pair_url": relay + "/r/" + "ab" * 12, "home_url": "http://192.168.1.30:8092"})
        self.assertIn("or open 192.168.1.30:8092 and type 4821", " ".join(said.split()))
        self.assertNotIn("relay.box.example", said)                               # (the relay refuses typed codes)
        said = self.setup_says({"url": relay, "pair_url": relay + "/r/" + "cd" * 12, "home_url": None})
        self.assertNotIn("type", said)                                            # only the relay's known: no typing line
        self.assertNotIn("4821", said)
        self.assertIn("Scan with your phone's camera", said)


if __name__ == "__main__":
    unittest.main()
