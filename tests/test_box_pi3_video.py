"""Sofa Box OS 1.1.80: what a report says about video and drawing on a Pi 3, and a way to try decoding straight to the
screen.

The owner's Pi 3 report KWMMM3 (1.1.73): a converted 1080p video dropped 234 frames, none of them by the decoder; the
kernel refused the video decoder and the graphics chip their own memory (CMA: "cma_alloc … alloc failed", "Failed to
allocate from GEM DMA helper") while it played; and the browser drew everything by the processor. The report couldn't
say how mpv put the picture on the screen, how much of that memory there was, or why the browser had given up on the
chip. Now it does: mpv's video output and its late frames, the CMA and its refusals, chrome://gpu's own "Problems
Detected" and how often the browser's graphics process crashed. Settings → Picture and sound → Decoding offers "Straight
to the screen" (mpv's v4l2m2m, without the copy of every picture through memory) for the owner to try on the Pi.

Nothing here runs on a Pi: what only a Pi can say is what these lines will report there."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

from tests.test_box_apps_close import BOX, HERE, load
from tests.test_box_memory import PI3, tree
from tests.test_box_speed import chrome, free_port

boxos = load("boxos")


def read(*path):
    with open(os.path.join(BOX, *path), encoding="utf-8") as f:
        return f.read()


class WhatTheReportSays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent", SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0",
                         SOFA_BOX_UINPUT="0", SOFA_BOX_MPV=os.path.join(HERE, "tools", "fake_mpv.py"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def test_how_mpv_drew_the_picture(self):
        run = {"at": "10:40:46", "kind": "converted", "started_after": 15, "video-codec": "H.264", "width": 1920,
               "height": 1080, "container-fps": 24, "hwdec-current": "v4l2m2m-copy", "video-bitrate": 4.8e6,
               "audio-codec-name": "aac", "frame-drop-count": 234, "decoder-frame-drop-count": 0,
               "current-vo": "gpu", "current-gpu-context": "wayland", "vo-delayed-frame-count": 51,
               "waits": 3, "waited": 10, "played": 29}
        line = self.agent.Player.ran_line(run)
        self.assertIn("decoded by the video chip (v4l2m2m-copy), drawn by gpu (wayland)", line)
        self.assertIn("dropped 234 frames (0 by the decoder), 51 late on the screen", line)
        self.assertIn("drawn by wlshm,", self.agent.Player.ran_line(dict(run, **{"current-vo": "wlshm", "current-gpu-context": None})))
        for prop in ("current-vo", "current-gpu-context", "vo-delayed-frame-count"):
            self.assertIn(prop, self.agent.Player.PLAY_PROPS)

    def test_the_graphics_chips_own_memory(self):
        root = tree(dict(PI3, **{"proc/meminfo": PI3["proc/meminfo"] + "CmaTotal:  262144 kB\nCmaFree:   22092 kB\n"}))
        self.addCleanup(shutil.rmtree, root, True)
        with mock.patch.object(boxos, "ROOT", root):
            self.assertEqual(boxos.cma_mb(), (256, 21))
        b = {"model": "Raspberry Pi 3 Model B Plus Rev 1.3", "gen": 3, "memory_mb": 903, "cores": 4, "cpu": "4 x Cortex-A53",
             "video": [], "vm": None, "tv_height": 1080}
        with mock.patch.object(self.agent.boxos, "ROOT", root), mock.patch.object(self.agent, "board", return_value=b):
            text = "\n".join(self.agent.memory_lines())
        self.assertIn("the graphics chip's and the video decoder's own memory (CMA): 256 MB, 21 MB free now", text)
        with mock.patch.object(boxos, "ROOT", tree({"proc/meminfo": "MemTotal: 4000000 kB\nCmaTotal: 0 kB\nCmaFree: 0 kB\n"})):
            self.assertIsNone(boxos.cma_mb())                               # (a PC: none set aside)

    def test_the_checks_count_the_kernels_refusals(self):
        script = read("sofa-box")
        self.assertIn("grep -c -E 'cma_alloc: .*alloc failed|Failed to allocate from GEM DMA helper'", script)
        self.assertIn("journalctl -k -b --no-pager", script)
        # the kernel's own lines from KWMMM3 match the pattern
        import re
        pat = re.compile(r"cma_alloc: .*alloc failed|Failed to allocate from GEM DMA helper")
        for line in ("[  341.300210] sofabox kernel: cma: __cma_alloc: linux,cma: alloc failed, req-size: 765 pages, ret: -16",
                     "[  418.532105] sofabox kernel: vc4-drm soc:gpu: [drm] *ERROR* Failed to allocate from GEM DMA helper:"):
            self.assertTrue(pat.search(line), line)
        subprocess.run(["sh", "-n", os.path.join(BOX, "sofa-box")], check=True)

    def test_why_the_browser_draws_by_the_processor(self):
        b = boxos.Browser.__new__(boxos.Browser)
        b.tabs = {}
        info = {"gpu": {"featureStatus": {"gpu_compositing": "disabled_software", "rasterization": "disabled_software",
                                          "video_decode": "disabled_software"},
                        "auxAttributes": {"glRenderer": "VC4 V3D 2.1", "glVersion": "OpenGL ES 2.0 Mesa 25.0.7",
                                          "processCrashCount": 3}}}
        evaluated = []

        def call(method, params=None, session=None, timeout=10):
            if method == "SystemInfo.getInfo":
                return info
            if method == "Target.createTarget":
                self.assertEqual(params, {"url": "chrome://gpu", "background": True})   # behind the page in front
                b.tabs["G"] = {"app": "browser", "session": "s-g"}                       # (the browser attaches it itself)
                return {"targetId": "G"}
            if method == "Runtime.evaluate":
                evaluated.append(session)
                return {"result": {"value": json.dumps({"Problems Detected": ["Accelerated compositing disabled"]})}}
            if method == "Target.closeTarget":
                b.tabs.pop(params["targetId"], None)
                return {}
            raise AssertionError(method)
        b.call = call
        self.assertEqual(b.gpu(), "compositing disabled_software, raster disabled_software, video decode disabled_software "
                                  "(VC4 V3D 2.1; OpenGL ES 2.0 Mesa 25.0.7; its graphics process crashed 3 times)")
        self.assertEqual(b.gpu_problems(), {"Problems Detected": ["Accelerated compositing disabled"]})
        self.assertEqual(evaluated, ["s-g"])
        self.assertEqual(b.tabs, {}, "the page is closed and forgotten")
        agent = read("sofa-box-agent.py")
        self.assertIn("problems = safely(browser.gpu_problems)", agent[agent.index("def report_text"):])

    @unittest.skipUnless(chrome(), "no Chrome or Chromium here")
    def test_chrome_gpu_is_read_from_a_real_browser(self):
        """GPU_PAGE_JS against a real chrome://gpu (this computer's Chrome): the "Problems Detected" headings come back."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        port = free_port()
        p = subprocess.Popen([chrome(), "--headless=new", "--no-first-run", "--remote-debugging-port=%d" % port,
                              "--user-data-dir=" + d, "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(p.wait, 10)
        self.addCleanup(p.terminate)
        for _ in range(100):
            try:
                v = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=2).read())
                break
            except OSError:
                time.sleep(0.2)
        ws = boxos.WebSocket(v["webSocketDebuggerUrl"])
        n = [0]

        def call(m, params=None, session=None):
            n[0] += 1
            msg = dict(id=n[0], method=m, params=params or {}, **({"sessionId": session} if session else {}))
            ws.send(json.dumps(msg))
            while True:
                r = json.loads(ws.recv())
                if r.get("id") == n[0]:
                    return r.get("result") or {}
        t = call("Target.createTarget", {"url": "chrome://gpu", "background": True})["targetId"]
        s = call("Target.attachToTarget", {"targetId": t, "flatten": True})["sessionId"]
        got = None
        for _ in range(40):
            got = call("Runtime.evaluate", {"expression": boxos.GPU_PAGE_JS, "returnByValue": True}, s).get("result", {}).get("value")
            if got:
                break
            time.sleep(0.25)
        problems = json.loads(got)
        self.assertIn("Problems Detected", problems)
        self.assertTrue(all(isinstance(x, list) for x in problems.values()))
        ws.close()


class StraightToTheScreen(unittest.TestCase):
    """Settings → Picture and sound → Decoding, on a Pi: Automatic (the copy, as before) or straight to the screen."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        cls.agent = load("sofa-box-agent", SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0",
                         SOFA_BOX_UINPUT="0", SOFA_BOX_MPV=os.path.join(HERE, "tools", "fake_mpv.py"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, ignore_errors=True)

    def args(self, hwdec):
        b = dict(model="Raspberry Pi 3 Model B Plus Rev 1.3", gen=3, memory_mb=905, cores=4, cpu="4 x Cortex-A53", video=[],
                 vm=None, tv_height=1080)
        p = self.agent.Player()
        p.sock_path, p.base = os.path.join(self.conf, "x.sock"), "http://sofa"
        s = dict(self.agent.settings(), hwdec=hwdec)
        with mock.patch.object(self.agent, "board", return_value=b), mock.patch.object(self.agent, "settings", return_value=s), \
                mock.patch.object(self.agent, "mpv_knows", return_value=True):
            args = p._args({"url": "http://sofa/media/x/file", "title": "X"})
        os.remove(p.info_path)
        return args

    def test_its_a_choice_and_mpv_gets_it(self):
        self.assertIn("v4l2m2m", self.agent.CHOICES["hwdec"])
        self.assertIn("--hwdec=v4l2m2m-copy", self.args("auto"))             # (Automatic on a Pi 3: the copy, as before)
        self.assertIn("--hwdec=v4l2m2m", self.args("v4l2m2m"))
        self.assertNotIn("--hwdec=v4l2m2m-copy", self.args("v4l2m2m"))
        home = read("home", "index.html") if os.path.exists(os.path.join(BOX, "home", "index.html")) else ""
        js = read("home", "home.js")
        self.assertIn('${b.board && b.board.gen ? `<section class="card"><h3>Decoding</h3>', js)      # (a Pi only)
        self.assertIn('pick("hwdec", "v4l2m2m", "Straight to the screen")', js)
        self.assertNotIn("untested", js[js.index("<h3>Decoding</h3>"):js.index("<h3>Decoding</h3>") + 600].lower())
        self.assertTrue(home is not None)


if __name__ == "__main__":
    unittest.main()
