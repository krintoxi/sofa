"""Sofa starting again in place (Restart on the Server page, an update) on a Mac or Linux: nothing the start before
left running is left running, and a recording goes on through it without missing a moment (sofa/children.py;
sofa/dvr.py hand_over and take_over; sofa/updater.py restart).

The first test starts some programs, replaces itself with os.execv as Sofa does, and ends what's left. The second
runs Sofa itself in a process of its own, as launchd or systemd runs it, with a stand-in tuner (tests/stand_in_tuner.py):
one of its channels is watched, another recorded, and Restart is pressed. Windows starts Sofa again as another
process, inside a job object that ends everything the old one started (sofa/winapp.py), so neither runs there.
"""
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import urllib.request

from tests import ROOT
from sofa import children, media
from tests.stand_in_tuner import Tuner
from tests.test_server import Client

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = media.tool("ffmpeg")
POSIX = os.name != "nt"

AGAIN = textwrap.dedent('''
    import json, os, subprocess, sys, time
    sys.path.insert(0, sys.argv[1])
    from sofa import children
    if sys.argv[2] == "before":
        plain = subprocess.Popen(["sleep", "60"])
        stubborn = subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                                     "print(1, flush=True); time.sleep(60)"], stdout=subprocess.PIPE)
        stubborn.stdout.readline()
        parent = subprocess.Popen(["sh", "-c", "sleep 60 & wait"])
        kept = subprocess.Popen(["sleep", "60"])
        end = time.time() + 10
        while len(children.descendants()) < 5 and time.time() < end:
            time.sleep(0.05)
        pids = {"kept": kept.pid, "others": [p for p in children.descendants() if p != kept.pid]}
        os.execv(sys.executable, [sys.executable, sys.argv[0], sys.argv[1], "after", json.dumps(pids)])
    pids = json.loads(sys.argv[3])
    began = time.time()
    ended = children.end_leftovers(keep={pids["kept"]}, grace=0.5)
    took = time.time() - began
    left = children.descendants()
    os.kill(pids["kept"], 9)
    os.waitpid(pids["kept"], 0)
    print(json.dumps(dict(pids, ended=ended, left=left, took=took)))
''')


def running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(out) and not out.startswith("Z")                 # (a zombie has ended; it's only waiting to be told)


def command(pid):
    return subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(POSIX, "Windows starts Sofa again as another process (see above)")
class TheLeftovers(unittest.TestCase):
    def test_what_the_start_before_left_is_ended_all_but_what_is_kept(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            script = os.path.join(tmp, "again.py")
            with open(script, "w", encoding="utf-8") as f:
                f.write(AGAIN)
            out = subprocess.run([sys.executable, script, APP, "before"], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        self.assertEqual(len(got["others"]), 4, got)                 # sleep; one that won't stop when asked; sh and its sleep
        self.assertEqual((got["ended"], got["left"]), (4, [got["kept"]]))
        self.assertLess(got["took"], 3)                              # asked, then after half a second made to
        end = time.time() + 5
        while any(running(p) for p in got["others"]) and time.time() < end:
            time.sleep(0.1)
        self.assertEqual([p for p in got["others"] if running(p)], [])


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@unittest.skipUnless(POSIX and FFMPEG, "a Mac or Linux with ffmpeg")
class RestartPressed(unittest.TestCase):
    """Someone watches channel 2.1, 5.1 is being recorded, and an admin presses Restart. Before this, the watching
    ffmpeg ran on for good (its tuner never given back), and the recording was called failed while its ffmpeg went
    on writing a part nobody would file."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="sofa-restart-", dir=ROOT)
        self.box = Tuner(self.folder, FFMPEG, seconds=60)
        self.box.pace = True
        self.addCleanup(self.box.close)
        data, lib = os.path.join(self.folder, "data"), os.path.join(self.folder, "Entertainment")
        os.makedirs(data)
        conf = {k: os.path.join(lib, v) for k, v in {
            "shows": "Shows", "movies": "Movies", "music": "Music", "musicvideos": "Music Videos", "inbox": "Inbox",
            "review": "Needs Review", "adult": "Adult", "originals": "Converted Originals"}.items()}
        self.port = free_port()
        conf.update(name="Sofa restart test", port=self.port, offline=True, tvmaze=False, free_movie_lookup=False,
                    dlna=False, previews=False, trickplay=False, detect_intros=False, auto_convert=False, keep_awake=False,
                    dvr_pad_before=0, dvr_pad_after=0)
        with open(os.path.join(data, "config.json"), "w", encoding="utf-8") as f:
            json.dump(conf, f)
        self.inbox = conf["inbox"]
        # Nothing announced on the network: Bonjour's helpers here are stand-ins that only wait.
        shims = os.path.join(self.folder, "bin")
        os.makedirs(shims)
        for name in ("dns-sd", "avahi-publish-service"):
            with open(os.path.join(shims, name), "w") as f:
                f.write("#!/bin/sh\nexec sleep 3600\n")
            os.chmod(os.path.join(shims, name), 0o755)
        env = dict(os.environ, SOFA_DATA=data, PATH=shims + os.pathsep + os.environ.get("PATH", ""))
        self.log = os.path.join(self.folder, "sofa.log")
        with open(self.log, "wb") as out:
            self.sofa = subprocess.Popen([sys.executable, os.path.join(APP, "sofa.py"), "serve"], cwd=APP, env=env,
                                         stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        self.addCleanup(self.stop_sofa)
        self.base = "http://127.0.0.1:%d" % self.port
        self.admin = Client(self.base)
        self.wait_for(lambda: self.answers(), "Sofa didn't answer")

    def stop_sofa(self):
        left = children.descendants(self.sofa.pid)
        if self.sofa.poll() is None:
            self.sofa.terminate()
            try:
                self.sofa.wait(10)
            except subprocess.TimeoutExpired:
                self.sofa.kill()
                self.sofa.wait()
        for pid in left:                    # (no supervisor here to end what it started, as launchd or systemd would)
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        import shutil
        shutil.rmtree(self.folder, True)

    def answers(self):
        try:
            with urllib.request.urlopen(self.base + "/healthz", timeout=2) as r:
                return r.status == 200
        except OSError:
            return False

    def wait_for(self, ok, why, seconds=40):
        end = time.time() + seconds
        while time.time() < end:
            if self.sofa.poll() is not None:
                self.fail("Sofa stopped: " + self.tail())
            if ok():
                return
            time.sleep(0.2)
        self.fail(why + ": " + self.tail())

    def tail(self):
        with open(self.log, encoding="utf-8", errors="replace") as f:
            return f.read()[-2000:]

    def recording(self, rid):
        return next(r for r in self.admin.call("/api/dvr")[1]["recordings"] if r["id"] == rid)

    def test_restart_ends_what_was_watched_and_the_recording_goes_on(self):
        password = secrets.token_urlsafe(18)
        self.assertEqual(self.admin.call("/api/setup", {"name": "restart-admin", "password": password})[0], 200)
        status, got = self.admin.call("/api/admin/tuners", {"add": self.box.base.replace("http://", "")})
        self.assertEqual(status, 200, got)
        chans = {c["guide_number"]: c for c in self.admin.call("/api/live")[1]["channels"] if c.get("tuner")}

        status, got = self.admin.call("/api/dvr", {"now": chans["5.1"]["id"]})                 # 5.1 recorded
        self.assertEqual(status, 200, got)
        rid = got["recording"]["id"]
        self.wait_for(lambda: self.box.open == 1, "the recording didn't open 5.1")
        began = time.time()
        with self.admin.opener.open(self.base + "/live/%s/index.m3u8" % chans["2.1"]["id"], timeout=40) as r:   # 2.1 watched
            self.assertIn(b"#EXTM3U", r.read())
        self.wait_for(lambda: self.box.open == 2, "watching didn't open 2.1")
        helpers = {pid: command(pid) for pid in children.descendants(self.sofa.pid)}
        copying = [pid for pid, cmd in helpers.items() if "ffmpeg" in cmd and "mpegts" in cmd and "recordings" in cmd]
        watching = [pid for pid, cmd in helpers.items() if "ffmpeg" in cmd and "hls" in cmd]
        self.assertEqual((len(copying), len(watching)), (1, 1), helpers)
        started = self.admin.call("/api/admin/status")[1]["server"]["started"]

        time.sleep(1.5)                                                                     # (STARTED is in seconds)
        status, got = self.admin.call("/api/admin/restart", {})
        self.assertEqual(status, 200, got)

        def again():
            status, s = self.admin.call("/api/admin/status") if self.answers() else (0, None)
            return status == 200 and s["server"]["started"] > started
        self.wait_for(again, "Sofa didn't start again")
        self.assertIsNone(self.sofa.poll())                                                 # the same process, new code
        self.wait_for(lambda: not running(watching[0]), "the ffmpeg someone was watching is still running", seconds=10)
        self.wait_for(lambda: self.box.open == 1, "the watched channel's tuner wasn't given back", seconds=10)
        self.assertTrue(running(copying[0]))                                                # the recording's copy goes on
        self.assertEqual(self.recording(rid)["state"], "recording")
        self.assertIn(copying[0], children.descendants(self.sofa.pid))
        self.assertRegex(self.tail(), r"Ended \d+ programs? the last start left running")

        time.sleep(3)
        status, got = self.admin.call("/api/dvr", {"cancel": rid})
        stopped = time.time()
        self.assertEqual(status, 200, got)
        self.wait_for(lambda: self.recording(rid)["state"] in ("done", "failed", "filed"), "the recording wasn't finished", seconds=40)
        r = self.recording(rid)
        self.assertIn(r["state"], ("done", "filed"), r.get("why"))
        self.assertIsNone(r.get("why"))                                                     # nothing missed
        self.assertEqual(self.box.open, 0)
        files = [os.path.join(d, n) for d, _, names in os.walk(os.path.dirname(self.inbox)) for n in names if n.endswith(".ts")]
        self.assertEqual(len(files), 1, files)
        self.assertGreater(media.probe(files[0])["duration"], stopped - began - 3)           # through the restart, no gap
        self.assertEqual([p for p in children.descendants(self.sofa.pid) if "ffmpeg" in command(p)], [])


if __name__ == "__main__":
    unittest.main()
