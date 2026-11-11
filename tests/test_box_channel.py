"""Sofa Box OS 1.1.55: stable and testing, and publishing cards safely.

- Which version a box is offered, by its channel (Stable, the default, or Testing), and never an older one as newer.
- What `sofa-box update` installs: on Stable the stable version's own release, on Testing main's newest; GitHub is
  stood in for by folders (file:// addresses).
- The weekly update by itself: off unless it's switched on, Stable only, at night, with nothing playing.
- The card workflow's guard (tools/sofa-box-releases.py): a lower version never replaces a higher one on the testing
  card; and marking the stable card. GitHub's CLI (gh) is stood in for by a small script with the releases in a file.
- The Raspberry Pi OS the cards are built on: pinned, and the build stops if the download isn't that image.

What only GitHub and a real box can show (the queue on GitHub's side, an update on a Pi) is in the pull request."""
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")
TOOLS = os.path.join(HERE, "tools")
WORKFLOWS = os.path.join(HERE, ".github", "workflows")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def stable_says(line):
    """deploy/sofa-box/STABLE's notes, whatever version it marks now, then this line."""
    notes = [n for n in read(os.path.join(BOX, "STABLE")).splitlines() if n.startswith("#")]
    return "\n".join(notes + [line]) + "\n"


def load(path, name, **env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)


def load_agent(conf):
    return load(os.path.join(BOX, "sofa-box-agent.py"), "sofa_box_agent_channel", SOFA_BOX_CONF=conf, SOFA_BOX_DEVTOOLS="0",
                SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")


releases = load(os.path.join(TOOLS, "sofa-box-releases.py"), "sofa_box_releases")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Offered(unittest.TestCase):
    """Which version a box is offered, from what each channel has (stable, testing) and the box's own."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load_agent(cls.conf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def test_stable_is_offered_the_stable_version_only(self):
        offered = self.agent.offered
        self.assertEqual(offered("stable", "1.1.54", "1.1.58", "1.1.53"), "1.1.54")     # not main's 1.1.58
        self.assertIsNone(offered("stable", "1.1.54", "1.1.58", "1.1.54"))             # it has it
        self.assertIsNone(offered("stable", None, "1.1.58", "1.1.53"))                 # nothing marked stable yet
        self.assertEqual(offered(None, "1.1.54", "1.1.58", "1.1.50"), "1.1.54")        # no channel set: Stable
        self.assertEqual(offered("anything else", "1.1.54", "1.1.58", "1.1.50"), "1.1.54")

    def test_testing_is_offered_the_newest(self):
        offered = self.agent.offered
        self.assertEqual(offered("testing", "1.1.54", "1.1.58", "1.1.55"), "1.1.58")
        self.assertIsNone(offered("testing", "1.1.54", "1.1.58", "1.1.58"))
        self.assertEqual(offered("testing", None, "1.1.58", "1.1.55"), "1.1.58")       # nothing stable: still main's
        self.assertEqual(offered("testing", "1.1.60", "1.1.58", "1.1.55"), "1.1.60")   # (stable ahead of main)

    def test_an_older_version_is_never_offered_as_newer(self):
        offered = self.agent.offered
        self.assertIsNone(offered("stable", "1.1.54", "1.1.58", "1.1.56"))             # a box ahead of stable stays
        self.assertIsNone(offered("testing", "1.1.54", "1.1.50", "1.1.55"))            # main behind the box
        self.assertIsNone(offered("stable", "1.1.9", None, "1.1.10"))                  # (numbers, not text: 9 < 10)
        self.assertEqual(offered("stable", "1.1.10", None, "1.1.9"), "1.1.10")
        self.assertIsNone(offered("stable", "1.1.x", None, "1.1.0"))                   # not a version
        self.assertIsNone(offered("stable", "1.1.54", None, "?"))                      # the box's own unknown
        self.assertFalse(self.agent.newer(None, "1.0.0") or self.agent.newer("1.0.0", None))

    def test_what_github_has(self):
        """The two small files on main (STABLE has notes around its version, or "none"), and the stable version's
        own release: a STABLE naming a version that never got a release of its own isn't offered."""
        a, files = self.agent, {}
        real = a.fetch_text, dict(a._newest)
        a.fetch_text = lambda url: files.get(url)
        try:
            files.update({a.NEWEST_URL: "1.1.58\n", a.STABLE_URL: stable_says("none")})
            self.assertTrue(a.look_for_updates())
            self.assertEqual((a._newest["version"], a._newest["stable"]), ("1.1.58", None))   # none marked
            files[a.STABLE_URL] = stable_says("1.1.54")
            files[a.RELEASE_URL % "1.1.54"] = "1.1.54\n"
            self.assertTrue(a.look_for_updates())
            self.assertEqual(a._newest["stable"], "1.1.54")
            files[a.STABLE_URL] = "1.1.56\n"
            files[a.RELEASE_URL % "1.1.56"] = ""                                         # 404: no release of its own
            self.assertTrue(a.look_for_updates())
            self.assertIsNone(a._newest["stable"])
            files[a.STABLE_URL] = "1.1.54\n"
            files[a.NEWEST_URL] = None                                                   # GitHub out of reach
            self.assertFalse(a.look_for_updates())
            self.assertEqual(a._newest["version"], "1.1.58")                             # what it knew stays
        finally:
            a.fetch_text = real[0]
            a._newest.clear()
            a._newest.update(real[1])

    def test_fetching_a_small_file(self):
        """Its text, "" when GitHub says it isn't there (404), None when GitHub can't be reached."""
        class Files(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/STABLE":
                    body = b"# notes\n1.1.54\n"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def log_message(self, *args):
                pass
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Files)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        try:
            self.assertEqual(self.agent.version_in(self.agent.fetch_text(base + "/STABLE")), "1.1.54")
            self.assertEqual(self.agent.fetch_text(base + "/missing"), "")
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertIsNone(self.agent.fetch_text("http://127.0.0.1:%d/STABLE" % free_port()))

    def test_the_channel_setting_and_the_offer(self):
        """Stable unless it's set to Testing; switching shows the other channel's offer at once (no new look)."""
        a = self.agent
        real = dict(a._newest), a.OS_VERSION, os.environ.pop("SOFA_BOX_NEWEST", None)
        try:
            a._newest.update(at=time.time(), version="1.1.58", stable="1.1.54", looked=time.time())
            a.OS_VERSION = "1.1.53"
            self.assertEqual(a.DEFAULTS["channel"], "stable")
            self.assertEqual(a.DEFAULTS["auto_update"], "off")                           # the weekly update: off
            self.assertEqual(a.CHOICES["channel"], ("stable", "testing"))
            self.assertEqual(a.CHOICES["auto_update"], ("off", "weekly"))
            a.save_settings(channel="stable")
            self.assertEqual(a.newest_version(), "1.1.54")
            self.assertEqual(a.software()["is"], "older")
            a.save_settings(channel="testing")
            self.assertEqual(a.newest_version(), "1.1.58")
            self.assertEqual(a.software()["channel"], "testing")
            a.OS_VERSION = "1.1.54"
            a.save_settings(channel="stable")
            self.assertIsNone(a.newest_version())
            self.assertEqual(a.software()["is"], "stable")
            a.OS_VERSION = "1.1.56"
            self.assertIsNone(a.newest_version())                                        # ahead of stable: nothing
            self.assertEqual(a.software()["is"], "testing")
        finally:
            a._newest.clear()
            a._newest.update(real[0])
            a.OS_VERSION = real[1]
            if real[2] is not None:
                os.environ["SOFA_BOX_NEWEST"] = real[2]
            a.save_settings(channel="stable")

    def test_update_the_box(self):
        """Settings → Software → Update the box: it looks again, then starts `sofa-box update` only when its channel has
        something (on Testing, main's newest, as before); otherwise the TV says why not."""
        a, ran = self.agent, []
        real = a.look_for_updates, a.run, dict(a._newest), a.OS_VERSION, os.environ.pop("SOFA_BOX_NEWEST", None)
        have = {"version": "1.1.58", "stable": "1.1.54"}

        def ran_now(n):                                               # (the update starts in a thread of its own)
            end = time.time() + 5
            while len(ran) < n and time.time() < end:
                time.sleep(0.02)
            return len(ran)
        try:
            a.look_for_updates = lambda: (a._newest.update(have, looked=1), True)[1]
            a.run = lambda cmd, timeout=20: (ran.append(cmd), (0, ""))[1]
            a.OS_VERSION = "1.1.53"
            a.save_settings(channel="stable")
            r = a.box_action("update", {})
            self.assertTrue(r["ok"])
            self.assertEqual(r["version"], "1.1.54")
            self.assertIn("1.1.54", r["message"])
            self.assertEqual(ran_now(1), 1)
            self.assertEqual(ran[-1][-1], "update")
            self.assertEqual(ran[-1][:2], ["sudo", "-n"])
            ran.clear()
            a.OS_VERSION = "1.1.54"
            self.assertIn("the stable version", a.box_action("update", {})["message"])
            a.OS_VERSION = "1.1.56"
            self.assertIn("newer than the stable version", a.box_action("update", {})["message"])
            have["stable"] = None
            self.assertIn("No version is marked stable", a.box_action("update", {})["message"])
            self.assertEqual(ran, [])                                                    # nothing ran on Stable
            a.save_settings(channel="testing")
            self.assertIn("1.1.58", a.box_action("update", {})["message"])
            self.assertEqual(ran_now(1), 1)
            a.OS_VERSION = "1.1.59"
            self.assertIn("newer than main's newest", a.box_action("update", {})["message"])
            time.sleep(0.2)
            self.assertEqual(len(ran), 1)
            a.look_for_updates = lambda: False
            r = a.box_action("update", {})
            self.assertFalse(r["ok"])
            self.assertIn("couldn't reach GitHub", r["message"])
        finally:
            a.look_for_updates, a.run, a.OS_VERSION = real[0], real[1], real[3]
            a._newest.clear()
            a._newest.update(real[2])
            if real[4] is not None:
                os.environ["SOFA_BOX_NEWEST"] = real[4]
            a.save_settings(channel="stable")


class SettingsThroughTheAgent(unittest.TestCase):
    """The settings and Software's facts, from a running agent (no GitHub: SOFA_BOX_NEWEST=0)."""

    def test_channel_and_weekly_update_settings(self):
        conf = tempfile.mkdtemp()
        port = free_port()
        proc = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                env=dict(os.environ, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(port), SOFA_BOX_UINPUT="0",
                                         SOFA_BOX_HOTSPOT="0", SOFA_BOX_NEWEST="0", SOFA_BOX_CERTS="0", SOFA_BOX_ICONS="0",
                                         SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_REMOTE_PORT=str(free_port()),
                                         SOFA_BOX_LOCAL_DATA=os.path.join(conf, "local-sofa"),
                                         SOFA_BOX_MPV=os.path.join(TOOLS, "fake_mpv.py")))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def post(path, body):
            req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "X-Sofa-Box": "1"})
            with opener.open(req, timeout=30) as r:
                return json.loads(r.read())
        try:
            for _ in range(150):
                try:
                    with opener.open("http://127.0.0.1:%d/box/api/info" % port, timeout=5) as r:
                        info = json.loads(r.read())
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                self.fail("the agent didn't start")
            self.assertEqual((info["settings"]["channel"], info["settings"]["auto_update"]), ("stable", "off"))
            self.assertEqual(info["software"]["channel"], "stable")
            self.assertIsNone(info["newest"])
            info = post("/box/api/settings", {"channel": "testing", "auto_update": "weekly"})
            self.assertEqual((info["settings"]["channel"], info["settings"]["auto_update"]), ("testing", "weekly"))
            info = post("/box/api/settings", {"channel": "beta", "auto_update": "daily"})          # not choices: ignored
            self.assertEqual((info["settings"]["channel"], info["settings"]["auto_update"]), ("testing", "weekly"))
            info = post("/box/api/settings", {"channel": "stable"})
            self.assertEqual(info["software"]["channel"], "stable")
            r = post("/box/api/action/update", {})                         # Stable, nothing marked: nothing runs
            self.assertIn("No version is marked stable", r["message"])
            with open(os.path.join(conf, "settings.json")) as f:
                self.assertEqual(json.load(f)["channel"], "stable")
        finally:
            proc.terminate()
            proc.wait(10)
            shutil.rmtree(conf, ignore_errors=True)


class UpdateCommand(unittest.TestCase):
    """`sofa-box update` (root on the box; here with GitHub stood in for by folders): what it installs, by channel.
    Each fake release's installer writes which version it is to a log."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lib = os.path.join(self.tmp, "lib")
        self.raw = os.path.join(self.tmp, "raw")
        self.tar = os.path.join(self.tmp, "tar")
        self.log = os.path.join(self.tmp, "installed.log")
        self.settings = os.path.join(self.tmp, "settings.json")
        os.makedirs(self.lib)
        self.box_has("1.1.55")
        self.stable("none")
        self.release("refs/heads/main", "1.1.58")
        self.release("refs/tags/box-os-v1.1.54", "1.1.54")
        self.release("refs/tags/box-os-v1.1.56", "1.1.56")
        self.channel(None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def box_has(self, version):
        with open(os.path.join(self.lib, "VERSION"), "w") as f:
            f.write(version + "\n")

    def stable(self, line):
        path = os.path.join(self.raw, "main", "deploy", "sofa-box", "STABLE")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(stable_says(line))

    def channel(self, name):
        with open(self.settings, "w") as f:
            json.dump({"channel": name} if name else {}, f)

    def release(self, ref, version):
        """A tarball as GitHub makes one: everything in one folder named after the repository and the ref."""
        path = os.path.join(self.tar, ref)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        top = "sofa-" + ref.split("/")[-1]
        with tarfile.open(path, "w:gz") as t:
            for name, text in (("VERSION", version + "\n"), ("sofa-box-agent.py", "# the agent\n"),
                               ("install.sh", '#!/bin/sh\necho "$(cat "$(dirname "$0")/VERSION")" >> "$INSTALL_LOG"\n')):
                data = text.encode()
                info = tarfile.TarInfo("%s/deploy/sofa-box/%s" % (top, name))
                info.size, info.mode = len(data), 0o755
                t.addfile(info, io.BytesIO(data))

    def update(self, **extra):
        env = dict(os.environ, SOFA_BOX_LIB=self.lib, SOFA_BOX_SETTINGS=self.settings, INSTALL_LOG=self.log,
                   SOFA_BOX_RAW="file://" + self.raw, SOFA_BOX_TARBALLS="file://" + self.tar, SOFA_BOX_BRANCH="")
        env.update(extra)
        r = subprocess.run(["sh", os.path.join(BOX, "sofa-box"), "update"], capture_output=True, text=True, timeout=60, env=env)
        installed = read(self.log).split() if os.path.exists(self.log) else []
        if os.path.exists(self.log):
            os.remove(self.log)
        return r.returncode, r.stdout + r.stderr, installed

    def test_stable_installs_the_stable_versions_own_release(self):
        self.stable("1.1.56")
        code, out, installed = self.update()
        self.assertEqual((code, installed), (0, ["1.1.56"]), out)                # not main's 1.1.58
        self.assertIn("Sofa Box OS 1.1.56 (stable)", out)

    def test_stable_never_goes_back_or_reinstalls(self):
        self.stable("1.1.54")                                                   # older than the box's 1.1.55
        code, out, installed = self.update()
        self.assertEqual((code, installed), (0, []), out)
        self.assertIn("nothing newer", out)
        self.box_has("1.1.56")
        self.stable("1.1.56")
        self.assertEqual(self.update()[2], [])                                  # it has it already

    def test_stable_with_nothing_marked(self):
        code, out, installed = self.update()
        self.assertEqual((code, installed), (0, []), out)
        self.assertIn("No version is marked stable", out)

    def test_a_release_that_isnt_the_version_it_says_is_refused(self):
        self.stable("1.1.57")
        self.release("refs/tags/box-os-v1.1.57", "1.1.53")                      # a tag on the wrong commit
        code, out, installed = self.update()
        self.assertEqual((code, installed), (1, []), out)
        self.assertIn("not 1.1.57", out)
        self.stable("1.1.59")                                                   # no release of its own at all
        code, out, installed = self.update()
        self.assertEqual((code, installed), (1, []), out)
        self.assertIn("Couldn't get it", out)

    def test_github_out_of_reach(self):
        shutil.rmtree(self.raw)
        code, out, installed = self.update()
        self.assertEqual((code, installed), (1, []), out)
        self.assertIn("Couldn't reach GitHub", out)

    def test_testing_installs_mains_newest_but_never_an_older_one(self):
        self.channel("testing")
        self.stable("1.1.56")
        self.assertEqual(self.update()[2], ["1.1.58"])
        self.box_has("1.1.58")
        self.assertEqual(self.update()[2], ["1.1.58"])                          # the same again: as it always did
        self.box_has("1.1.60")
        code, out, installed = self.update()
        self.assertEqual((code, installed), (1, []), out)
        self.assertIn("older than this box's 1.1.60", out)

    def test_a_branch_from_ssh(self):
        """SOFA_BOX_BRANCH=<branch>: that branch's newest, whatever the channel (even an older version)."""
        self.release("refs/heads/claude/try-this", "1.1.50")
        self.stable("1.1.56")
        code, out, installed = self.update(SOFA_BOX_BRANCH="claude/try-this")
        self.assertEqual((code, installed), (0, ["1.1.50"]), out)

    def test_from_the_tv_its_own_service_and_no_branch(self):
        """From the TV the update starts again as its own service (the agent restarts mid-way), and it passes on no
        branch unless one was asked for (it used to pass main always, which would have skipped the channel)."""
        script = read(os.path.join(BOX, "sofa-box"))
        self.assertIn('--setenv=SOFA_BOX_BRANCH="${SOFA_BOX_BRANCH:-}"', script)
        self.assertRegex(script, r"update\)[^\n]*\n\s+on_its_own update\n\s+update ;;")
        self.assertNotIn("deploy/sofa-box/install.sh\" | sh", script)           # main's installer piped in: gone

    def test_a_new_box_from_the_one_line_install_gets_stable(self):
        """install.sh through curl on a Pi that isn't a Sofa box yet: the stable version's own release, installed by its
        own installer; a box already (an update from before 1.1.55) or SOFA_BOX_BRANCH: that branch's newest."""
        text = read(os.path.join(BOX, "install.sh"))
        self.assertIn('[ -z "${SOFA_BOX_BRANCH:-}" ] && [ ! -f "$LIB/VERSION" ]', text)
        self.assertIn('REF="refs/tags/box-os-v$STABLE"', text)
        self.assertIn('exec sh "$HERE/install.sh"', text)
        self.assertIn("box-os-v$STABLE/deploy/sofa-box/VERSION", text)          # (only a version with a release)


class WeeklyUpdates(unittest.TestCase):
    """Settings → Software → Update by itself every week."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load_agent(cls.conf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def setUp(self):
        a = self.agent
        self.real = (a.settings, a.save_settings, a.look_for_updates, a.run, a.WeeklyUpdate.hour, a.WeeklyUpdate.busy,
                     dict(a._newest), a.OS_VERSION)
        self.s = dict(a.DEFAULTS, welcomed=True)
        self.ran, self.now, self.hour, self.busy, self.online = [], 1_000_000.0, [4], [False], [True]
        a.settings = lambda: dict(self.s)
        a.save_settings = lambda **kw: self.s.update(kw)
        a.look_for_updates = lambda: self.online[0]
        a.run = lambda cmd, timeout=20: (self.ran.append(cmd), (0, ""))[1]
        a.WeeklyUpdate.hour = staticmethod(lambda now: self.hour[0])
        a.WeeklyUpdate.busy = staticmethod(lambda: self.busy[0])
        a._newest.update(version="1.1.58", stable="1.1.56", looked=1)
        a.OS_VERSION = "1.1.55"
        self.w = a.WeeklyUpdate()

    def tearDown(self):
        a = self.agent
        (a.settings, a.save_settings, a.look_for_updates, a.run, hour, busy, newest, a.OS_VERSION) = self.real
        a.WeeklyUpdate.hour, a.WeeklyUpdate.busy = staticmethod(hour), staticmethod(busy)
        a._newest.clear()
        a._newest.update(newest)

    def test_off_unless_switched_on(self):
        self.assertFalse(self.w.due(self.now))
        self.s["auto_update"] = "weekly"
        self.assertTrue(self.w.due(self.now))

    def test_only_on_stable_at_night_with_nothing_on(self):
        self.s["auto_update"] = "weekly"
        self.s["channel"] = "testing"
        self.assertFalse(self.w.due(self.now))                                  # Testing: never by itself
        self.s["channel"] = "stable"
        self.hour[0] = 14
        self.assertFalse(self.w.due(self.now))                                  # daytime
        self.hour[0] = 3
        self.busy[0] = True
        self.assertFalse(self.w.due(self.now))                                  # a video or a game on
        self.busy[0] = False
        self.s["welcomed"] = False
        self.assertFalse(self.w.due(self.now))                                  # the setup not done
        self.s["welcomed"] = True
        self.assertTrue(self.w.due(self.now))

    def test_once_a_week_the_stable_version(self):
        self.s["auto_update"] = "weekly"
        self.assertTrue(self.w.look(self.now))
        self.assertEqual(self.ran, [["sudo", "-n", os.path.join(BOX, "sofa-box"), "update"]])   # as Update the box does
        week = self.s["update_week"]
        self.assertEqual((week["to"], week["came_from"], week["tries"]), ("1.1.56", "1.1.55", 1))   # stable, not main's 1.1.58
        self.agent.OS_VERSION = "1.1.56"                                        # it took
        self.assertFalse(self.w.due(self.now + 3600))
        self.assertTrue(self.w.due(self.now + self.w.AGAIN))
        self.assertFalse(self.w.look(self.now + self.w.AGAIN))                  # nothing newer: next week
        self.assertEqual(len(self.ran), 1)
        nxt = self.s["update_week"]["next"]
        self.assertFalse(self.w.due(nxt - 60))
        self.assertTrue(self.w.due(nxt))
        self.assertLessEqual(nxt - (self.now + self.w.AGAIN), self.w.WEEK)

    def test_one_that_didnt_take_is_tried_three_nights(self):
        self.s["auto_update"] = "weekly"
        for night in range(3):
            self.assertTrue(self.w.due(self.now + night * 86400), night)
            self.assertTrue(self.w.look(self.now + night * 86400))
        self.assertEqual(len(self.ran), 3)
        self.assertTrue(self.w.due(self.now + 3 * 86400))
        self.assertFalse(self.w.look(self.now + 3 * 86400))                     # the fourth night: next week instead
        self.assertEqual(len(self.ran), 3)
        self.assertGreater(self.s["update_week"]["next"], self.now + 8 * 86400)
        self.assertTrue(self.w.look(self.s["update_week"]["next"]))             # and then it tries again
        self.assertEqual(len(self.ran), 4)

    def test_never_an_older_version_and_offline_tries_the_next_night(self):
        self.s["auto_update"] = "weekly"
        self.agent.OS_VERSION = "1.1.57"                                        # ahead of stable (1.1.56)
        self.assertFalse(self.w.look(self.now))
        self.assertEqual(self.ran, [])
        self.online[0] = False
        self.assertFalse(self.w.look(self.now))
        self.assertEqual(self.s["update_week"]["next"], self.now + self.w.AGAIN)
        self.assertEqual(self.ran, [])

    def test_the_hour_where_the_box_is(self):
        a = self.agent
        hour = self.real[4]
        real_tz = a.current_timezone
        try:
            a.current_timezone = lambda: "UTC"
            self.assertEqual(hour(0), 0)                                        # (1970-01-01 00:00 UTC)
            a.current_timezone = lambda: "Not/AZone"
            self.assertEqual(hour(0), time.localtime(0).tm_hour)               # unknown: the process's own clock
        finally:
            a.current_timezone = real_tz


FAKE_GH = r'''#!%(python)s
"""A stand-in for GitHub's CLI: the releases, tags and comparisons in a JSON file (FAKE_GH_STATE)."""
import json, os, re, sys
path = os.environ["FAKE_GH_STATE"]
state = json.load(open(path))
args = sys.argv[1:]
state.setdefault("calls", []).append(args)


def done(out="", code=0, err=""):
    json.dump(state, open(path, "w"), indent=1)
    sys.stdout.write(out)
    sys.stderr.write(err)
    sys.exit(code)


def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default


if state.get("fail"):
    done(code=1, err="gh: Server Error (HTTP 500)\n")
rels = state.setdefault("releases", [])
by_tag = {r["tag_name"]: r for r in rels}
if args[0] == "api":
    method, p = opt("-X", "GET"), [a for a in args[1:] if not a.startswith("-") and a not in (opt("-X"), opt("--input"))][0]
    body = json.loads(sys.stdin.read()) if "--input" in args else None
    p = re.sub(r"^repos/[^/]+/[^/]+/", "", p)
    m = re.match(r"releases/tags/(.+)$", p)
    if m and method == "GET":
        r = by_tag.get(m.group(1))
        done(json.dumps(r)) if r else done(code=1, err="gh: Not Found (HTTP 404)\n")
    m = re.match(r"git/refs/tags/(.+)$", p)
    if m:
        if method == "PATCH":
            state.setdefault("refs", {})[m.group(1)] = body["sha"]
            done("{}")
        sha = state.get("refs", {}).get(m.group(1))
        done(json.dumps({"object": {"sha": sha, "type": "commit"}})) if sha else done(code=1, err="gh: Not Found (HTTP 404)\n")
    m = re.match(r"compare/(.+)$", p)
    if m:
        st = state.get("compare", {}).get(m.group(1))
        done(json.dumps({"status": st})) if st else done(code=1, err="gh: Not Found (HTTP 404)\n")
    m = re.match(r"releases\?per_page=(\d+)&page=(\d+)$", p)
    if m:
        n, page = int(m.group(1)), int(m.group(2))
        done(json.dumps(rels[(page - 1) * n:page * n]))
    m = re.match(r"releases/(\d+)$", p)
    if m and method == "PATCH":
        r = next(r for r in rels if r["id"] == int(m.group(1)))
        r.update(body)
        done(json.dumps(r))
    m = re.match(r"releases/assets/(\d+)$", p)
    if m:
        for r in rels:
            for a in list(r["assets"]):
                if a["id"] == int(m.group(1)):
                    if method == "DELETE":
                        r["assets"].remove(a)
                    else:
                        a.update(body)
                    done("" if method == "DELETE" else json.dumps(a))
        done(code=1, err="gh: Not Found (HTTP 404)\n")
    done(code=1, err="fake gh: no answer for %%s %%s\n" %% (method, p))
if args[:2] == ["release", "download"]:
    r = by_tag[args[2]]
    for a in r["assets"]:
        if a["name"] in [args[i + 1] for i, x in enumerate(args) if x == "-p"]:
            open(os.path.join(opt("-D"), a["name"]), "w").write(a["content"])
    done()
if args[:2] in (["release", "upload"], ["release", "create"]):
    files = []
    for x in args[3:]:
        if x.startswith("-"):
            break
        files.append(x)
    if args[1] == "create":
        state["next_id"] = state.get("next_id", 100) + 1
        r = {"id": state["next_id"], "tag_name": args[2], "name": opt("--title"), "body": open(opt("--notes-file")).read(),
             "assets": [], "target_commitish": opt("--target")}
        rels.insert(0, r)
        state.setdefault("refs", {})[args[2]] = opt("--target")
    else:
        r = by_tag[args[2]]
    for f in files:
        state["next_id"] = state.get("next_id", 100) + 1
        r["assets"].append({"id": state["next_id"], "name": os.path.basename(f), "content": open(f).read()})
    done()
done(code=1, err="fake gh: unknown command %%s\n" %% args)
'''


class FakeGitHub:
    """GitHub's releases for the release tool, in a file a stand-in gh reads and changes."""

    def __init__(self, state):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "state.json")
        os.makedirs(os.path.join(self.dir, "bin"))
        gh = os.path.join(self.dir, "bin", "gh")
        with open(gh, "w") as f:
            f.write(FAKE_GH % {"python": sys.executable})
        os.chmod(gh, 0o755)
        self.save(state)

    def save(self, state):
        with open(self.path, "w") as f:
            json.dump(state, f)

    def state(self):
        with open(self.path) as f:
            return json.load(f)

    def run(self, *args):
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "sofa-box-releases.py")] + list(args), capture_output=True,
                           text=True, timeout=60, env=dict(os.environ, FAKE_GH_STATE=self.path, GITHUB_REPOSITORY="krintoxi/sofa",
                                                           PATH=os.path.join(self.dir, "bin") + os.pathsep + os.environ["PATH"]))
        return r.returncode, r.stdout + r.stderr

    def release(self, tag):
        return next((r for r in self.state()["releases"] if r["tag_name"] == tag), None)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestingCardGuard(unittest.TestCase):
    """The card workflow publishes to the testing card only what's at least as new as the card there (a re-run of an old
    run, or an older push that finished late, used to put an older card over a newer one)."""

    def test_the_rule(self):
        rule = releases.may_replace
        asked = []

        def relation(base, head):
            asked.append((base, head))
            return {"later": "ahead", "earlier": "behind", "side": "diverged"}[head]
        self.assertTrue(rule("1.1.55", "abc", None, relation)[0])                        # no testing card yet
        self.assertTrue(rule("1.1.55", "abc", ("1.1.54", "def"), relation)[0])
        self.assertFalse(rule("1.1.53", "abc", ("1.1.54", "def"), relation)[0])          # lower never over higher
        self.assertFalse(rule("1.1.9", "abc", ("1.1.10", "def"), relation)[0])           # (numbers, not text)
        self.assertTrue(rule("1.1.10", "abc", ("1.1.9", "def"), relation)[0])
        self.assertEqual(asked, [])                                                      # versions settle those
        self.assertTrue(rule("1.1.54", "later", ("1.1.54", "def"), relation)[0])         # the same version, later
        self.assertFalse(rule("1.1.54", "earlier", ("1.1.54", "def"), relation)[0])      # ...from an earlier commit
        self.assertTrue(rule("1.1.54", "side", ("1.1.54", "def"), relation)[0])          # (main was rewritten)
        self.assertTrue(rule("1.1.54", "abc1234", ("1.1.54", "abc1234ffff"), relation)[0])   # the same commit
        self.assertTrue(rule("1.1.54", "abc", ("not a version", "def"), relation)[0])
        with self.assertRaises(ValueError):
            rule("1.1", "abc", None, relation)

    def test_what_the_testing_card_is(self):
        there = releases.card_there
        marked = {"name": "Sofa Box OS 1.1.56 (testing): the newest card (2026-11-11)",
                  "body": "<!-- sofa-box-card version=1.1.56 commit=0123456789abcdef0123456789abcdef01234567 -->\nThe testing card"}
        self.assertEqual(there(marked, "fff"), ("1.1.56", "0123456789abcdef0123456789abcdef01234567"))
        old = {"name": "Sofa Box OS 1.1.54: the newest card (2026-11-10)", "body": "The newest card…"}   # (before the mark)
        self.assertEqual(there(old, "4c49b8d"), ("1.1.54", "4c49b8d"))
        self.assertEqual(there({"name": "Something else", "body": ""}, "4c49b8d"), (None, "4c49b8d"))

    def test_the_command_against_github(self):
        gh = FakeGitHub({"releases": [{"id": 1, "tag_name": "sofa-box", "name": "Sofa Box OS 1.1.54: the newest card (2026-11-10)",
                                       "body": "The newest card…", "assets": []}],
                         "refs": {"sofa-box": "4c49b8d5eec8673307b9d710927602fdfb20dedc"},
                         "compare": {"4c49b8d5eec8673307b9d710927602fdfb20dedc...bbb": "behind",
                                     "4c49b8d5eec8673307b9d710927602fdfb20dedc...ccc": "ahead"}})
        try:
            code, out = gh.run("may-replace", "1.1.55", "aaa")
            self.assertEqual(code, 0, out)
            self.assertIn("newer than the testing card's 1.1.54", out)
            self.assertEqual(gh.run("may-replace", "1.1.53", "aaa")[0], 10)
            self.assertEqual(gh.run("may-replace", "1.1.54", "bbb")[0], 10)             # an earlier commit
            self.assertEqual(gh.run("may-replace", "1.1.54", "ccc")[0], 0)
            st = gh.state()
            st["releases"][0]["body"] = "<!-- sofa-box-card version=1.1.57 commit=%s -->\n…" % ("d" * 40)
            gh.save(st)
            code, out = gh.run("may-replace", "1.1.56", "eee")
            self.assertEqual(code, 10, out)
            self.assertIn("Sofa Box OS 1.1.57, newer than 1.1.56", out)
            gh.save({"releases": [], "refs": {}})
            self.assertEqual(gh.run("may-replace", "1.1.55", "aaa")[0], 0)              # the first testing card
            gh.save({"fail": True})
            code, out = gh.run("may-replace", "1.1.55", "aaa")
            self.assertEqual(code, 2, out)                                              # GitHub not answering: stop
            self.assertEqual(gh.run("may-replace", "1.1.55")[0], 2)
        finally:
            gh.close()

    def test_the_workflow(self):
        """One publishing run at a time, queued (never cancelled), and the guard asked before the testing card's files
        are touched. A change to STABLE alone builds no card; the base image's pin and this tool do."""
        wf = read(os.path.join(WORKFLOWS, "sofa-box-image.yml"))
        conc = re.search(r"^concurrency:\n((?:  .*\n)+)", wf, re.M)
        self.assertTrue(conc, "the workflow has no concurrency group")
        self.assertIn("queue: max", conc.group(1))
        self.assertNotIn("cancel-in-progress: true", wf)
        self.assertIn("refs/heads/main", conc.group(1))
        self.assertIn("'sofa-box-releases'", conc.group(1))
        self.assertIn("github.run_id", conc.group(1))                                   # other branches: side by side
        step = wf[wf.index("- name: Publish it (main)"):]
        guard = step.index("sofa-box-releases.py may-replace")
        self.assertLess(guard, step.index("gh release upload sofa-box"))
        self.assertLess(guard, step.index("gh release create sofa-box"))
        self.assertIn('[ "$GUARD" = 0 ] || [ "$GUARD" = 10 ] || exit "$GUARD"', step)
        self.assertIn('if [ "$GUARD" = 10 ]; then', step)
        self.assertIn("<!-- sofa-box-card version=$VER commit=$GITHUB_SHA -->", step)  # what the guard reads next time
        self.assertEqual(step.count("(testing): the newest card ($DAY)"), 2)
        self.assertIn(releases.SAYS_TESTING.replace(releases.PAGE + releases.STABLE, "$STABLE_PAGE"), step)
        self.assertIn('STABLE_PAGE="%s"' % (releases.PAGE + releases.STABLE), step)
        paths = re.search(r"paths:\n((?:      - .*\n)+)", wf).group(1)
        self.assertIn('"!deploy/sofa-box/STABLE"', paths)
        self.assertIn('"tools/sofa-box-base-image.txt"', paths)
        self.assertIn('"tools/sofa-box-releases.py"', paths)
        stable = read(os.path.join(WORKFLOWS, "sofa-box-stable.yml"))
        self.assertIn('paths: ["deploy/sofa-box/STABLE"]', stable)
        self.assertIn("branches: [main]", stable)
        self.assertIn("group: sofa-box-releases", stable)
        self.assertIn("queue: max", stable)
        self.assertIn("python3 tools/sofa-box-releases.py mark-stable", stable)


def card_release(rid, version, card=b"card", good=True, title=None, body=None):
    content = (card * 64).decode()
    sha = hashlib.sha256(content.encode()).hexdigest() if good else "0" * 64
    return {"id": rid, "tag_name": "box-os-v" + version, "name": title or "Sofa Box OS " + version, "target_commitish": "main",
            "body": body if body is not None else ("**Sofa Box OS %s** for the Sofa Box, built 2026-11-10.\n\n**How to use it**\n"
                                                   "1. Download **sofa-box-os-%s.img.xz** below.\n\nWhat's on the card: "
                                                   "sofa-box-os-%s-report.txt.\n" % (version, version, version)),
            "assets": [{"id": rid * 10 + 1, "name": "sofa-box-os-%s.img.xz" % version, "content": content},
                       {"id": rid * 10 + 2, "name": "sofa-box-os-%s.img.xz.sha256" % version,
                        "content": "%s  sofa-box-os-%s.img.xz\n" % (sha, version)},
                       {"id": rid * 10 + 3, "name": "sofa-box-os-%s-report.txt" % version, "content": "Sofa Box OS: %s\n" % version}]}


class StableCard(unittest.TestCase):
    """deploy/sofa-box/STABLE, and the releases made to match it (tools/sofa-box-releases.py mark-stable)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.stable_file = os.path.join(self.tmp, "STABLE")
        self.gh = FakeGitHub({
            "releases": [{"id": 1, "tag_name": "sofa-box", "name": "Sofa Box OS 1.1.55 (testing): the newest card", "body": "…", "assets": []},
                         card_release(2, "1.1.54", b"tested"),
                         card_release(3, "1.1.53", b"older", title="Sofa Box OS 1.1.53 (stable)")],
            "refs": {"sofa-box": "c55", "box-os-v1.1.54": "c54", "box-os-v1.1.53": "c53"}})

    def tearDown(self):
        self.gh.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mark(self, line):
        with open(self.stable_file, "w") as f:
            f.write(stable_says(line))
        return self.gh.run("mark-stable", self.stable_file)

    def test_the_file_in_the_repository(self):
        """It names a version or none (marking one is the owner's), never one ahead of main."""
        v = releases.stable_in(os.path.join(BOX, "STABLE"))
        self.assertTrue(v is None or re.fullmatch(r"\d+\.\d+\.\d+", v), v)
        version = read(os.path.join(BOX, "VERSION")).strip()
        self.assertFalse(v and releases.newer(v, version))
        for bad in ("1.1", "latest", "1.1.54\n1.1.55"):
            with open(self.stable_file, "w") as f:
                f.write("# notes\n%s\n" % bad)
            with self.assertRaises(ValueError):
                releases.stable_in(self.stable_file)

    def test_marking_a_version_stable(self):
        code, out = self.mark("1.1.54")
        self.assertEqual(code, 0, out)
        st = self.gh.release("sofa-box-stable")
        self.assertEqual(st["name"], "Sofa Box OS 1.1.54 (stable): the tested card")
        self.assertEqual(self.gh.state()["refs"]["sofa-box-stable"], "c54")            # its tag: the version's commit
        files = {a["name"]: a["content"] for a in st["assets"]}
        card = (b"tested" * 64).decode()
        self.assertEqual(sorted(files), sorted(releases.STABLE_FILES))
        self.assertEqual(files["sofa-box-stable.img.xz"], card)                        # the same card, byte for byte
        sha = hashlib.sha256(card.encode()).hexdigest()
        self.assertEqual(files["sofa-box-stable.img.xz.sha256"], "%s  sofa-box-stable.img.xz\n" % sha)
        self.assertIn("<!-- sofa-box-stable version=1.1.54 sha256=%s -->" % sha, st["body"])
        self.assertIn("Download **sofa-box-stable.img.xz**", st["body"])               # its own release's how-to
        self.assertIn(releases.PAGE + "box-os-v1.1.54", st["body"])
        own = self.gh.release("box-os-v1.1.54")
        self.assertEqual(own["name"], "Sofa Box OS 1.1.54 (stable)")
        self.assertTrue(own["body"].startswith("<!-- sofa-box-status -->" + releases.SAYS_STABLE))
        old = self.gh.release("box-os-v1.1.53")
        self.assertEqual(old["name"], "Sofa Box OS 1.1.53")                            # it isn't stable any more
        self.assertTrue(old["body"].startswith("<!-- sofa-box-status -->" + releases.SAYS_TESTED))
        self.assertEqual(self.gh.release("sofa-box")["name"], "Sofa Box OS 1.1.55 (testing): the newest card")
        calls = len(self.gh.state()["calls"])
        self.assertEqual(self.mark("1.1.54")[0], 0)                                    # again: nothing to change
        again = self.gh.state()["calls"][calls:]
        self.assertFalse([c for c in again if c[:2] in (["release", "upload"], ["release", "download"])
                          or (c[0] == "api" and "PATCH" in c and "releases/" in c[-3])], again)

    def test_moving_it_on_swaps_the_card_in_place(self):
        st = self.gh.state()
        st["releases"].insert(1, card_release(4, "1.1.58", b"newer"))
        st["refs"]["box-os-v1.1.58"] = "c58"
        self.gh.save(st)
        self.assertEqual(self.mark("1.1.54")[0], 0)
        code, out = self.mark("1.1.58")
        self.assertEqual(code, 0, out)
        stable = self.gh.release("sofa-box-stable")
        self.assertEqual({a["name"]: a["content"] for a in stable["assets"]}["sofa-box-stable.img.xz"], (b"newer" * 64).decode())
        self.assertEqual(sorted(a["name"] for a in stable["assets"]), sorted(releases.STABLE_FILES))   # no next-… left
        self.assertEqual(self.gh.state()["refs"]["sofa-box-stable"], "c58")
        self.assertEqual(self.gh.release("box-os-v1.1.58")["name"], "Sofa Box OS 1.1.58 (stable)")
        self.assertEqual(self.gh.release("box-os-v1.1.54")["name"], "Sofa Box OS 1.1.54")
        self.assertIn(releases.SAYS_TESTED, self.gh.release("box-os-v1.1.54")["body"])

    def test_only_a_numbered_card_can_be_stable(self):
        """A version with no release of its own (merged together with a newer one), or a card that isn't the one its
        SHA-256 says: it stops, and nothing changes."""
        before = self.gh.state()["releases"]
        code, out = self.mark("1.1.56")
        self.assertEqual(code, 1, out)
        self.assertIn("no release of its own", out)
        st = self.gh.state()
        st["releases"].append(card_release(5, "1.1.57", b"broken", good=False))
        st["refs"]["box-os-v1.1.57"] = "c57"
        self.gh.save(st)
        code, out = self.mark("1.1.57")
        self.assertEqual(code, 1, out)
        self.assertIn("isn't the one its SHA-256 says", out)
        self.assertIsNone(self.gh.release("sofa-box-stable"))
        self.assertEqual([r for r in self.gh.state()["releases"] if r["id"] != 5], before)

    def test_none_marked(self):
        """Before anything is marked, the stable link says so (and points at the testing card); marking none again
        later takes the stable card down (its version's own release keeps it) and the mark off."""
        code, out = self.mark("none")
        self.assertEqual(code, 0, out)
        st = self.gh.release("sofa-box-stable")
        self.assertEqual((st["name"], st["assets"]), ("Sofa Box OS: no stable card yet", []))
        self.assertIn(releases.PAGE + "sofa-box", st["body"])
        self.assertEqual(self.gh.release("box-os-v1.1.53")["name"], "Sofa Box OS 1.1.53")
        self.assertEqual(self.mark("1.1.54")[0], 0)
        self.assertEqual(len(self.gh.release("sofa-box-stable")["assets"]), 3)
        self.assertEqual(self.mark("none")[0], 0)
        st = self.gh.release("sofa-box-stable")
        self.assertEqual((st["name"], st["assets"]), ("Sofa Box OS: no stable card yet", []))
        self.assertEqual(self.gh.release("box-os-v1.1.54")["name"], "Sofa Box OS 1.1.54")
        self.assertEqual(len(self.gh.release("box-os-v1.1.54")["assets"]), 3)
        with open(self.stable_file, "w") as f:
            f.write("1.1\n")
        self.assertEqual(self.gh.run("mark-stable", self.stable_file)[0], 2)


class BaseImage(unittest.TestCase):
    """The Raspberry Pi OS the cards are built on: one dated image and its SHA-256, and the build stops on any other."""

    PIN = os.path.join(TOOLS, "sofa-box-base-image.txt")

    def test_the_pin(self):
        text = read(self.PIN)
        url = re.findall(r"(?m)^url=(\S+)$", text)
        sha = re.findall(r"(?m)^sha256=(\S+)$", text)
        self.assertEqual(len(url), 1)
        self.assertRegex(url[0], r"^https://downloads\.raspberrypi\.com/raspios_lite_arm64/images/raspios_lite_arm64-"
                                 r"(\d{4}-\d\d-\d\d)/\1-raspios-[a-z]+-arm64-lite\.img\.xz$")   # dated, not "latest"
        self.assertEqual(len(sha), 1)
        self.assertRegex(sha[0], r"^[0-9a-f]{64}$")
        build = read(os.path.join(TOOLS, "build-sofa-box-image.sh"))
        self.assertNotIn("_latest", build)
        self.assertIn("tools/sofa-box-base-image.txt", build)
        self.assertIn("dpkg-query -W", build)                                           # the packages, in the report
        self.assertIn("== Packages on the card", build)
        self.assertIn("/^== Packages/", read(os.path.join(WORKFLOWS, "sofa-box-image.yml")))

    @unittest.skipUnless(shutil.which("sha256sum") and shutil.which("curl"), "needs sha256sum and curl")
    def test_the_build_stops_if_the_download_isnt_that_image(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "repo", "tools"))
            os.makedirs(os.path.join(tmp, "repo", "deploy", "sofa-box"))
            os.makedirs(os.path.join(tmp, "bin"))
            shutil.copy(os.path.join(TOOLS, "build-sofa-box-image.sh"), os.path.join(tmp, "repo", "tools"))
            with open(os.path.join(tmp, "repo", "deploy", "sofa-box", "VERSION"), "w") as f:
                f.write("1.1.55\n")
            image = os.path.join(tmp, "2026-10-06-raspios-trixie-arm64-lite.img.xz")
            with open(image, "wb") as f:
                f.write(b"not really Raspberry Pi OS")
            for tool, script in (("id", "echo 0"), ("xz", 'echo "xz reached" >&2; exit 3')) + tuple(
                    (t, "exit 1") for t in ("parted", "losetup", "resize2fs", "e2fsck", "chroot")):
                with open(os.path.join(tmp, "bin", tool), "w") as f:
                    f.write("#!/bin/sh\n%s\n" % script)
                os.chmod(os.path.join(tmp, "bin", tool), 0o755)

            def build(sha):
                with open(os.path.join(tmp, "repo", "tools", "sofa-box-base-image.txt"), "w") as f:
                    f.write("# the pin\nurl=https://example.invalid/x.img.xz\nsha256=%s\n" % sha)
                # (the pin must be https; the copy here reads a local file through a curl that serves it)
                with open(os.path.join(tmp, "bin", "curl"), "w") as f:
                    f.write('#!/bin/sh\ncase " $* " in *" -o /dev/null "*) echo "%s"; exit 0;; esac\n'
                            'while [ $# -gt 1 ]; do [ "$1" = -o ] && out="$2"; shift; done\ncp "%s" "$out"\n' % (image, image))
                os.chmod(os.path.join(tmp, "bin", "curl"), 0o755)
                return subprocess.run(["sh", os.path.join(tmp, "repo", "tools", "build-sofa-box-image.sh"), os.path.join(tmp, "out")],
                                      capture_output=True, text=True, timeout=60,
                                      env=dict(os.environ, PATH=os.path.join(tmp, "bin") + os.pathsep + os.environ["PATH"]))
            r = build("0" * 64)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("Stopped:", r.stdout + r.stderr)
            self.assertNotIn("xz reached", r.stderr)                                    # nothing built from it
            with open(image, "rb") as f:
                r = build(hashlib.sha256(f.read()).hexdigest())
            self.assertIn(": OK", r.stdout + r.stderr)
            self.assertIn("xz reached", r.stderr)                                       # it went on to unpack it
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
