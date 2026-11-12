"""Sofa Box OS 1.1.74: memory and the processor first, sized to the box it runs on.

Measured on a 1 GB, four-core stand-in for a Pi 3 (Chromium 156 under cage, the box's own flags, the real agent and
This box's Sofa): a film playing over Home left 148 MB free, 236 MB now. The player read 120 MB ahead (and kept 50 MB
behind) on every box: 284 MB for mpv, 165 MB with a read-ahead sized to 1 GB. Chromium made the address bar's pop-ups
as pages of their own at its start, even in kiosk mode where there is no address bar: one renderer, 34 MB. The agent
sat on 78 MB after a visit to Sofa, of which Python used 8: what it frees now goes back to the box. And a box short of
memory closes the apps out of sight behind Home at once, not after their half minute.

These tests use stand-in /proc and /sys trees (a Pi 3, a Pi 5, a PC in a VM), the agent's own Player and a stand-in
DevTools; nothing here needs a Pi. What it measured is in deploy/sofa-box/CHANGES.md."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from tests.test_box_apps_close import BOX, HERE, browser, load, tabs

boxos = load("boxos")


def tree(files):
    """A folder laid out like /: {"proc/cpuinfo": "...", ...}."""
    root = tempfile.mkdtemp(prefix="sofa-box-hw-")
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    return root


def arm(part, n=4, maker="0x41"):
    return "".join("processor\t: %d\nBogoMIPS\t: 108.00\nFeatures\t: fp asimd\nCPU implementer\t: %s\nCPU part\t: %s\n\n"
                   % (i, maker, part) for i in range(n))


PI3 = {"proc/cpuinfo": arm("0xd03") + "Hardware\t: BCM2835\nModel\t: Raspberry Pi 3 Model B Plus Rev 1.3\n",
       "proc/meminfo": "MemTotal:         925000 kB\nMemAvailable:     150000 kB\nSwapTotal:  462000 kB\nSwapFree:  420000 kB\n",
       "proc/pressure/memory": "some avg10=3.50 avg60=1.25 avg300=0.40 total=123\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
       "proc/device-tree/model": "Raspberry Pi 3 Model B Plus Rev 1.3\0",
       "sys/class/video4linux/video10/name": "bcm2835-codec-decode\n",
       "sys/class/video4linux/video11/name": "bcm2835-codec-encode\n",
       "sys/class/video4linux/video12/name": "bcm2835-codec-isp\n"}
PI5 = {"proc/cpuinfo": arm("0xd0b"), "proc/meminfo": "MemTotal:  8000000 kB\nMemAvailable: 7000000 kB\n",
       "sys/class/video4linux/video19/name": "rpi-hevc-dec\n"}
PC_VM = {"proc/cpuinfo": "processor\t: 0\nmodel name\t: Intel(R) N100\nflags\t\t: fpu sse2 avx2 hypervisor\n\n" * 4,
         "proc/meminfo": "MemTotal:  3900000 kB\nMemAvailable: 2000000 kB\n",
         "dev/dri/renderD128": "", "sys/class/drm/renderD128/device/vendor": "0x8086\n",
         "sys/class/dmi/id/sys_vendor": "QEMU\n", "sys/class/dmi/id/product_name": "Standard PC (Q35 + ICH9, 2009)\n"}


class TheHardware(unittest.TestCase):
    def at(self, files):
        root = tree(files)
        self.addCleanup(shutil.rmtree, root, True)
        return mock.patch.object(boxos, "ROOT", root)

    def test_a_pi_3_its_cores_and_its_decoder(self):
        with self.at(PI3):
            self.assertEqual(boxos.processor(), "4 x Cortex-A53")
            self.assertEqual(boxos.video_chips(), ["bcm2835-codec-decode (video10)"])   # (not the encoder, not the ISP)
            self.assertIsNone(boxos.virtual())
            self.assertEqual((boxos.memory_mb(), boxos.available_mb(), boxos.swap_used_mb()), (903, 146, 41))
            self.assertEqual(boxos.pressure(), (3.5, 1.25))

    def test_a_pi_5_and_a_pc_in_a_vm(self):
        with self.at(PI5):
            self.assertEqual(boxos.processor(), "4 x Cortex-A76")
            self.assertEqual(boxos.video_chips(), ["rpi-hevc-dec (video19)"])
        with self.at(PC_VM):
            self.assertEqual(boxos.processor(), "Intel(R) N100")
            self.assertEqual(boxos.video_chips(), ["VA-API: Intel (renderD128)"])
            self.assertEqual(boxos.virtual(), "a VM (QEMU)")
        with self.at({"proc/cpuinfo": arm("0x000", maker="0x61")}):           # (a VM on a Mac with Apple silicon)
            self.assertEqual(boxos.processor(), "4 x Apple silicon")

    def test_who_holds_the_memory(self):
        procs = {"proc/10/cmdline": "/usr/lib/chromium/chromium\0--type=renderer\0--lang=en-US\0",
                 "proc/10/smaps_rollup": "Rss: 200000 kB\nPss:  120000 kB\n",
                 "proc/11/cmdline": "/usr/lib/chromium/chromium\0--type=renderer\0",
                 "proc/11/smaps_rollup": "Pss:  60000 kB\n",
                 "proc/12/cmdline": "/usr/lib/chromium/chromium\0--kiosk\0",
                 "proc/12/smaps_rollup": "Pss:  70000 kB\n",
                 "proc/13/cmdline": "mpv\0--fs\0http://127.0.0.1:8091/media/x\0", "proc/13/smaps_rollup": "Pss: 165000 kB\n",
                 "proc/14/cmdline": "/usr/bin/python3\0/usr/local/lib/sofa-box/sofa-box-agent.py\0",
                 "proc/14/smaps_rollup": "Pss:  40000 kB\n",
                 "proc/15/cmdline": "/usr/bin/python3\0/usr/local/lib/sofa-box/sofa-server/sofa.py\0serve\0",
                 "proc/15/smaps_rollup": "Pss:  30000 kB\n",
                 "proc/16/cmdline": "/usr/sbin/sshd\0", "proc/1/cmdline": "/sbin/init\0"}   # (root's: no smaps to read)
        with self.at(procs):
            self.assertEqual(boxos.memory_users(), [("the browser's pages", 175, 2), ("the player (mpv)", 161, 1),
                                                    ("the browser", 68, 1), ("the box's agent", 39, 1), ("Sofa on this box", 29, 1)])

    def test_freed_memory_goes_back_and_never_breaks_anything(self):
        self.assertIn(boxos.give_back(), (True, False))                       # (False on a Mac: no malloc_trim)
        self.assertIn(boxos.give_back(), (True, False))

    def test_the_cycle_collector_once_a_minute_before_it(self):
        import gc
        clock = [1000.0]
        with mock.patch.object(boxos, "_libc", {"collected": 0.0, "fn": None}), \
                mock.patch.object(boxos.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(gc, "collect") as collect:
            for step in (0, 5, 30, 59, 61, 65, 125):                         # (the agent asks every 5 s)
                clock[0] = 1000.0 + step
                boxos.give_back()
        self.assertEqual(collect.call_count, 3)                               # at 0, 61 and 125 s


class ThePlayer(unittest.TestCase):
    """mpv's read-ahead by the box's memory, and its decoding threads by its cores."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent", SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0",
                         SOFA_BOX_UINPUT="0", SOFA_BOX_MPV=os.path.join(HERE, "tools", "fake_mpv.py"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def args(self, **board):
        b = dict(model="Raspberry Pi 3 Model B Plus Rev 1.3", gen=3, memory_mb=905, cores=4, cpu="4 x Cortex-A53", video=[],
                 vm=None, tv_height=1080)
        b.update(board)
        p = self.agent.Player()
        p.sock_path, p.base = os.path.join(self.conf, "x.sock"), "http://sofa"
        with mock.patch.object(self.agent, "board", return_value=b), \
                mock.patch.dict(os.environ, {"SOFA_BOX_MPV": os.path.join(HERE, "tools", "fake_mpv.py")}):
            args = p._args({"url": "http://sofa/media/m%3Aheat%3A1995/file", "title": "Heat"})
        os.remove(p.info_path)
        return args

    def test_the_read_ahead_fits_the_box(self):
        self.assertEqual(boxos.mpv_cache(905), ["--demuxer-max-bytes=48MiB", "--demuxer-max-back-bytes=16MiB"])
        self.assertEqual(boxos.mpv_cache(1900), ["--demuxer-max-bytes=96MiB", "--demuxer-max-back-bytes=32MiB"])
        self.assertEqual(boxos.mpv_cache(3800), ["--demuxer-max-bytes=150MiB", "--demuxer-max-back-bytes=50MiB"])
        self.assertEqual(boxos.mpv_cache(15800), ["--demuxer-max-bytes=256MiB", "--demuxer-max-back-bytes=64MiB"])
        small = self.args()
        self.assertIn("--demuxer-max-bytes=48MiB", small)
        self.assertIn("--demuxer-max-back-bytes=16MiB", small)
        self.assertNotIn("--demuxer-max-bytes=120MiB", small)                  # (1.1.70's, on every box)
        self.assertIn("--demuxer-max-bytes=256MiB", self.args(model="this computer", gen=0, memory_mb=7800, cores=8))

    def test_decoding_threads_are_the_cores_it_has(self):
        self.assertIn("--vd-lavc-threads=4", self.args())
        self.assertIn("--vd-lavc-threads=1", self.args(model="Raspberry Pi Zero W Rev 1.1", gen=1, memory_mb=430, cores=1))
        self.assertFalse([a for a in self.args(model="this computer", gen=0, memory_mb=7800, cores=8)
                          if a.startswith("--vd-lavc-threads")])               # (a PC: mpv's own choice)


class ShortOfMemory(unittest.TestCase):
    """Short of memory, the apps out of sight behind Home close at once; never Home, Sofa or one that plays."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent", SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0",
                         SOFA_BOX_UINPUT="0")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def setUp(self):
        self.agent.LOW_MEMORY.clear()
        self.agent._low["said"] = -1e9

    def run_check(self, free, b):
        b.connected = lambda: True
        with mock.patch.object(self.agent, "browser", b), mock.patch.object(self.agent.boxos, "available_mb", return_value=free), \
                mock.patch.object(b, "tidy", wraps=lambda grace, now=None, wait=2.0: boxos.Browser.tidy(b, grace, now=now, wait=0)), \
                mock.patch.object(self.agent.boxos, "memory_users", return_value=[("the browser's pages", 410, 3)]), \
                mock.patch.object(self.agent, "board", return_value={"memory_mb": 905}):
            return self.agent.memory_check(now=1000.0)

    def test_an_app_just_left_closes_at_once(self):
        now = 1000.0
        b = browser(tabs(now, tube={"app": "youtube", "session": "s-tube", "left": now - 3, "frozen": True},
                         music={"app": "music", "session": "s-music", "left": now - 3}), playing=("s-music",))
        line = self.run_check(80, b)                                           # (a 1 GB box: short under 100 MB)
        self.assertEqual(sorted(b.tabs), ["h", "music", "sofa"])               # 3 s out of sight was enough; music plays on
        self.assertIn("80 MB free; closed youtube (the browser's pages 410 MB)", line)
        self.assertEqual(list(self.agent.LOW_MEMORY), [line])

    def test_plenty_of_memory_nothing_closes_and_its_said_once_a_minute(self):
        now = 1000.0
        b = browser(tabs(now, tube={"app": "youtube", "session": "s-tube", "left": now - 3, "frozen": True}))
        self.assertIsNone(self.run_check(400, b))
        self.assertIn("tube", b.tabs)                                         # (after its half minute, as in 1.1.70)
        b = browser(tabs(now), front="tube")                                  # short, but the app is the one in front
        self.assertIn("90 MB free (the browser's pages", self.run_check(90, b))
        self.assertIsNone(self.run_check(90, b))                               # (the same again within the minute: not said)
        self.assertEqual(len(self.agent.LOW_MEMORY), 1)
        self.assertEqual(self.agent.low_memory_mb(), max(100, self.agent.board()["memory_mb"] // 10))

    def test_the_report_says_what_the_memory_and_processor_are_doing(self):
        root = tree(dict(PI3, **{"proc/77/cmdline": "mpv\0x\0", "proc/77/smaps_rollup": "Pss: 165000 kB\n"}))
        self.addCleanup(shutil.rmtree, root, True)
        b = {"model": "Raspberry Pi 3 Model B Plus Rev 1.3", "gen": 3, "memory_mb": 903, "cores": 4, "cpu": "4 x Cortex-A53",
             "video": ["bcm2835-codec-decode (video10)"], "vm": None, "tv_height": 1080}
        self.agent.LOW_MEMORY.append("21:04:10 92 MB free; closed youtube")
        with mock.patch.object(self.agent.boxos, "ROOT", root), mock.patch.object(self.agent, "board", return_value=b), \
                mock.patch.object(self.agent, "slow_board", return_value=True):
            lines = self.agent.memory_lines()
        text = "\n".join(lines)
        self.assertEqual(lines[0], "== Memory and processor")
        for want in ("memory: 903 MB, 146 MB free now; compressed (zram) in use: 41 MB; waited for memory 3.5% of the last 10 s",
                     "who holds it: the player (mpv) 161 MB", "memory ran low (under 100 MB free): 21:04:10 92 MB free; closed youtube",
                     "processor: 4 x Cortex-A53, 4 cores, load ", "video decoding: bcm2835-codec-decode (video10); "
                     "the player reads 48 MB ahead and keeps 16 MB behind, 4 threads"):
            self.assertIn(want, text)
        with open(os.path.join(BOX, "sofa-box-agent.py"), encoding="utf-8") as f:
            agent = f.read()
        self.assertIn("lines = safely(memory_lines)", agent[agent.index("def report_text"):])   # (in what Send a report sends)


class TheBrowsersPopUps(unittest.TestCase):
    """The address bar's pop-ups stay unmade, on every box (the light look's flags or not)."""

    def session(self, settings):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        fake = os.path.join(d, "bin")
        os.makedirs(fake)
        os.makedirs(os.path.join(d, ".config", "sofa-box"))
        with open(os.path.join(d, ".config", "sofa-box", "settings.json"), "w") as f:
            json.dump(settings, f)
        for name, body in (("chromium", 'printf "%s\\n" "$@" > "$OUT"; kill -TERM $PPID; exit 0'), ("curl", "exit 0")):
            with open(os.path.join(fake, name), "w") as f:
                f.write("#!/bin/sh\n" + body + "\n")
            os.chmod(os.path.join(fake, name), 0o755)
        out = os.path.join(d, "args")
        os.makedirs(os.path.join(d, "run"))
        subprocess.run(["sh", os.path.join(BOX, "sofa-box"), "session"], timeout=60, capture_output=True,
                       env=dict(os.environ, HOME=d, PATH=fake + os.pathsep + os.environ["PATH"], OUT=out, WAYLAND_DISPLAY="wayland-0",
                                XDG_RUNTIME_DIR=os.path.join(d, "run"), SOFA_BOX_SCALE="2"))
        with open(out) as f:
            return f.read().split("\n")

    @unittest.skipUnless(os.path.exists("/proc/meminfo"), "the kiosk session reads /proc (Linux)")
    def test_not_made_on_a_small_box_or_a_big_one(self):
        for perf in ("light", "full"):
            args = self.session({"performance": perf})
            self.assertIn("--disable-features=Translate,MediaRouter,HardwareMediaKeyHandling,WebUIOmniboxPopup,"
                          "WebUIOmniboxAimPopup,WebUIOmniboxFullPopup,PreloadTopChromeWebUI", args, perf)
            self.assertEqual("--enable-low-end-device-mode" in args, perf == "light")


if __name__ == "__main__":
    unittest.main()
