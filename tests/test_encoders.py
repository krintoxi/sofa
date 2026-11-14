"""Sofa 1.5.12: the graphics chip converts video on Linux and Windows too (sofa/encoders.py).

NVIDIA's NVENC, Intel's Quick Sync, VA-API on Intel's and AMD's graphics and AMD's AMF, beside Apple's VideoToolbox:

- what Sofa looks for (render nodes with their maker and whether its user may open them, NVIDIA's driver, Windows'
  display adapters) and which encoders are then worth a one-second test;
- the choice: a chip's encoder that passed and converts well faster than video plays, else the fastest; the
  household's switch; an encoder resting after it failed on a job;
- the commands, family by family: the device ahead of the inputs, how the filters end, the options that passed;
- what happens when a chip's encoder fails: as it starts, in the middle of a stream, in a file conversion.

No such chip is in any machine these tests run on. The first three parts need none. The last runs with a stand-in
ffmpeg (tests/stand_in_ffmpeg.py) that answers as a driver would and does the real conversion with x264, so the
playlists and files checked here are real video; it proves Sofa's side, not NVIDIA's, Intel's or AMD's. On a Mac
the real VideoToolbox is tried too.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests import ROOT
from sofa import config, encoders, hardware, machine, media, optimize, windows

HERE = os.path.dirname(os.path.abspath(__file__))
ALL = {"h264_nvenc", "h264_qsv", "h264_vaapi", "h264_amf", "h264_videotoolbox", "libx264", "libx265", "aac"}


def node(n=128, maker="Intel", open=True):
    return {"node": "/dev/dri/renderD%d" % n, "maker": maker, "open": open}


def system(kind="linux", nodes=(), nvidia=None, adapters=()):
    return {"system": kind, "nodes": list(nodes), "nvidia": nvidia, "adapters": list(adapters)}


NVIDIA = {"name": "NVIDIA GeForce RTX 3060", "driver": "550.120"}
ITEM = {"id": "x1", "path": "/nowhere/film.mkv", "ext": "mkv", "title": "Film"}
INFO = {"video": {"index": 0, "codec": "mpeg2video", "height": 1080}, "audio": [{"index": 1, "codec": "aac", "channels": 2}],
        "subs": [{"index": 2, "codec": "hdmv_pgs_subtitle"}], "duration": 60}


class Clean(unittest.TestCase):
    """Each test starts from nothing remembered and leaves nothing behind."""

    def setUp(self):
        saved = (media._encoders, dict(machine._result), dict(encoders._found), config.get("hardware_encoding"), config.get("ffmpeg"))

        def restore():
            media._encoders = saved[0]
            machine._result.clear()
            machine._result.update(saved[1])
            encoders._found.clear()
            encoders._found.update(saved[2])
            encoders.forget_failures()
            config.update({"hardware_encoding": saved[3], "ffmpeg": saved[4]})
        self.addCleanup(restore)
        machine._result.clear()
        encoders.forget_failures()
        config.update({"hardware_encoding": True})

    def on(self, found, has=ALL):
        """This computer shows `found`, and its ffmpeg was built with `has`."""
        p = mock.patch.object(encoders, "found", lambda force=False: dict(found))
        p.start()
        self.addCleanup(p.stop)
        media._encoders = set(has)

    def remembered(self, best, how=None, decode=False, speeds=None):
        """The test has run here and chose `best`."""
        machine._result.clear()
        machine._result.update(key=machine._key(), at=int(time.time()), best=best, how={best: how or {}} if best else {},
                               speeds=speeds or ({best: 300.0, "libx264": 120.0} if best else {}), damaged=[], decode=decode, why={})


class WhatSofaLooksFor(Clean):
    def tree(self, files):
        root = tempfile.mkdtemp(prefix="sofa-gpu-", dir=ROOT)
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
        p = mock.patch.object(hardware, "ROOT", root)
        p.start()
        self.addCleanup(p.stop)
        return root

    def test_a_render_node_by_its_maker(self):
        self.tree({"dev/dri/renderD128": "", "dev/dri/card0": "", "sys/class/drm/renderD128/device/vendor": "0x8086\n",
                   "dev/dri/renderD129": "", "sys/class/drm/renderD129/device/vendor": "0x1002\n",
                   "dev/dri/renderD130": "", "sys/class/drm/renderD130/device/vendor": "0x1af4\n"})
        self.assertEqual([(n["node"], n["maker"], n["open"]) for n in encoders.render_nodes()],
                         [("/dev/dri/renderD128", "Intel", True), ("/dev/dri/renderD129", "AMD", True),
                          ("/dev/dri/renderD130", "virtual", True)])
        found = encoders.found(force=True)
        self.assertEqual((found["system"], len(found["nodes"]), found["nvidia"]), ("linux", 3, None))

    @unittest.skipIf(os.name == "nt" or getattr(os, "geteuid", lambda: 1)() == 0, "file modes: not on Windows, and root may open anything")
    def test_a_node_sofas_user_may_not_open(self):
        root = self.tree({"dev/dri/renderD128": "", "sys/class/drm/renderD128/device/vendor": "0x8086\n"})
        os.chmod(os.path.join(root, "dev/dri/renderD128"), 0)
        self.assertFalse(encoders.render_nodes()[0]["open"])
        encoders.found(force=True)
        media._encoders = set(ALL)
        self.assertEqual(encoders.candidates(), [])                    # nothing to try: it would only fail
        self.assertEqual(encoders.closed_nodes(), ["/dev/dri/renderD128"])    # and the Server page says what to do
        self.assertEqual(machine.status()["closed"], ["/dev/dri/renderD128"])

    def test_nvidias_driver(self):
        self.tree({"proc/driver/nvidia/version": "NVRM version: NVIDIA UNIX x86_64 Kernel Module  550.120  Fri Sep 13 10:10:01 UTC 2026\n"})
        self.assertEqual(encoders.found(force=True)["nvidia"], {"name": "NVIDIA graphics", "driver": "550.120"})
        self.assertEqual(hardware.video_chips(), ["NVIDIA: graphics (driver 550.120)"])
        media._encoders = set(ALL)
        self.assertEqual(encoders.candidates(), [("h264_nvenc", None)])

    def test_nothing_there(self):
        self.tree({"proc/cpuinfo": "processor\t: 0\n"})
        self.assertEqual(encoders.found(force=True), system())
        media._encoders = set(ALL)
        self.assertEqual(encoders.candidates(), [])

    def test_the_line_that_says_the_graphics_changed(self):
        self.on(system(nodes=[node()]))
        one = encoders.signature()
        self.on(system(nodes=[node()], nvidia=NVIDIA))
        two = encoders.signature()
        self.on(system(nodes=[node()], nvidia=dict(NVIDIA, driver="560.35")))
        self.assertEqual(len({one, two, encoders.signature()}), 3)       # a card added, a driver updated: tested again
        self.on(system(nodes=[node(open=False)]))
        self.assertNotEqual(encoders.signature(), one)                    # and a device opened to Sofa
        self.assertIn(encoders.signature(), machine._key())

    def test_windows_adapters_by_maker(self):
        m = windows.gpu_maker
        self.assertEqual(m(r"PCI\VEN_10DE&DEV_2504"), "NVIDIA")
        self.assertEqual(m("pci\\ven_8086&dev_46d1"), "Intel")
        self.assertEqual(m("pci\\ven_1002&dev_15bf"), "AMD")
        self.assertEqual(m("", "Advanced Micro Devices, Inc.", "AMD Radeon(TM) Graphics"), "AMD")
        self.assertEqual(m("", "Intel Corporation", "Intel(R) UHD Graphics 770"), "Intel")
        self.assertIsNone(m("", "Microsoft", "Microsoft Basic Display Adapter"))
        self.assertIsNone(m(r"VMBUS\{da0a7802-e377-4aac-8e77-0558eb1073f8}", "Microsoft", "Microsoft Hyper-V Video"))

    @unittest.skipUnless(windows.ON, "Windows' own list of display adapters")
    def test_on_windows_the_registry_is_read(self):
        adapters = windows.gpus()
        self.assertIsInstance(adapters, list)
        for a in adapters:
            self.assertTrue(a["name"])
            self.assertIn(a["maker"], ("NVIDIA", "Intel", "AMD", None))
        found = encoders.found(force=True)
        self.assertEqual((found["system"], found["adapters"]), ("windows", adapters))


class WhatIsWorthATest(Clean):
    def test_linux(self):
        self.on(system(nodes=[node()]))
        self.assertEqual(encoders.candidates(), [("h264_qsv", "/dev/dri/renderD128"), ("h264_vaapi", "/dev/dri/renderD128")])
        self.on(system(nodes=[node(maker="AMD")]))
        self.assertEqual(encoders.candidates(), [("h264_vaapi", "/dev/dri/renderD128")])        # Quick Sync is Intel's
        self.on(system(nvidia=NVIDIA))
        self.assertEqual(encoders.candidates(), [("h264_nvenc", None)])
        self.on(system(nodes=[node(128, "NVIDIA"), node(129, "Intel")], nvidia=NVIDIA))           # a card and the processor's own graphics
        self.assertEqual(encoders.candidates(), [("h264_nvenc", None), ("h264_qsv", "/dev/dri/renderD129"),
                                                 ("h264_vaapi", "/dev/dri/renderD128"), ("h264_vaapi", "/dev/dri/renderD129")])
        self.on(system(nodes=[node(maker="virtual")]))            # a VM's: tried all the same (the test decides, not the name)
        self.assertEqual(encoders.candidates(), [("h264_vaapi", "/dev/dri/renderD128")])

    def test_only_what_this_ffmpeg_has(self):
        self.on(system(nodes=[node()], nvidia=NVIDIA), has={"libx264", "h264_vaapi"})
        self.assertEqual(encoders.candidates(), [("h264_vaapi", "/dev/dri/renderD128")])
        self.on(system(nodes=[node()], nvidia=NVIDIA), has={"libx264"})
        self.assertEqual(encoders.candidates(), [])

    def test_windows(self):
        gpu = lambda name, maker: {"name": name, "maker": maker, "driver": "1"}     # noqa: E731
        self.on(system("windows", adapters=[gpu("NVIDIA GeForce RTX 3060", "NVIDIA")]))
        self.assertEqual(encoders.candidates(), [("h264_nvenc", None)])
        self.on(system("windows", adapters=[gpu("Intel(R) UHD Graphics", "Intel"), gpu("AMD Radeon RX 6600", "AMD")]))
        self.assertEqual(encoders.candidates(), [("h264_qsv", None), ("h264_amf", None)])
        self.on(system("windows", adapters=[gpu("Microsoft Basic Display Adapter", None)]))      # no maker known: each is tried
        self.assertEqual(encoders.candidates(), [("h264_nvenc", None), ("h264_qsv", None), ("h264_amf", None)])
        self.on(system("windows"), has={"libx264", "h264_amf"})
        self.assertEqual(encoders.candidates(), [("h264_amf", None)])

    def test_a_mac(self):
        self.on(system("mac"))
        self.assertEqual(encoders.candidates(), [("h264_videotoolbox", None)])
        self.on(system("mac"), has={"libx264"})
        self.assertEqual(encoders.candidates(), [])


class TheChoice(Clean):
    def test_the_chip_when_its_well_faster_than_video_plays(self):
        c = encoders.choose
        self.assertEqual(c({"h264_qsv": 240.0, "libx264": 410.0}), "h264_qsv")      # the processor is left to everything else
        self.assertEqual(c({"h264_videotoolbox": 55.0, "libx264": 80.0}), "libx264")    # a slow chip: the faster way, as before
        self.assertEqual(c({"h264_nvenc": 500.0, "h264_qsv": 240.0, "libx264": 300.0}), "h264_nvenc")
        self.assertEqual(c({"h264_videotoolbox": 300.0, "libx264": 90.0}, damaged=["h264_videotoolbox"]), "libx264")
        self.assertEqual(c({"h264_vaapi": None, "libx264": 60.0}), "libx264")
        self.assertEqual(c({"h264_vaapi": 30.0}), "h264_vaapi")                         # no x264 in this ffmpeg
        self.assertIsNone(c({"h264_vaapi": None}))
        self.assertIsNone(c({}))

    def test_for_each_conversion(self):
        self.on(system(nvidia=NVIDIA))
        self.assertEqual(encoders.pick(), "libx264")                    # not tested yet: never a chip that hasn't passed
        self.remembered("h264_nvenc")
        self.assertEqual(encoders.pick(), "h264_nvenc")
        self.assertTrue(media.hardware_encoder())
        self.assertEqual(media.encoder_label(), "NVIDIA NVENC (the graphics chip)")
        self.assertEqual(encoders.pick(software=True), "libx264")       # a job done again after the chip gave up
        config.update({"hardware_encoding": False})                     # the household's switch
        self.assertEqual((encoders.pick(), media.hardware_encoder()), ("libx264", False))
        self.assertEqual(media.encoder_label(), "x264 (the processor)")
        st = machine.status()
        self.assertEqual((st["hardware_encoding"], st["using"], st["hardware"], st["best"]), (False, "libx264", ["h264_nvenc"], "h264_nvenc"))
        config.update({"hardware_encoding": True})
        self.assertEqual(machine.status()["using"], "h264_nvenc")
        self.remembered("libx264")
        self.assertEqual(encoders.pick(), "libx264")

    def test_an_ffmpeg_with_apples_encoder_alone(self):
        """One built from Apple's own parts (tools/build-ffmpeg.sh), on four x86-64 cores without AVX2 whose chip has
        no working encoder: the test finds nothing that works, and VideoToolbox's software side converts, as before."""
        self.on(system("mac"), has={"h264_videotoolbox", "aac"})
        self.assertEqual(encoders.pick(), "h264_videotoolbox")          # (as before: nothing else could convert at all)
        self.assertEqual(media.encoder_plan(1080)["codec"][:4], ["-c:v", "h264_videotoolbox", "-allow_sw", "1"])
        machine._result.update(key=machine._key(), best=None, speeds={"h264_videotoolbox": None}, damaged=[], how={}, why={})
        self.assertEqual(encoders.pick(), "h264_videotoolbox")
        self.assertEqual(media.encoder_plan(1080, live=False)["codec"], ["-c:v", "h264_videotoolbox", "-allow_sw", "1", "-q:v", "62"])
        self.assertIsNone(encoders.fallback("h264_videotoolbox"))       # nothing to go on with: a failure is a failure, as before
        self.assertIsNone(encoders.pick(software=True))
        config.update({"hardware_encoding": False})                     # no switch takes the only encoder away
        self.assertEqual(encoders.pick(), "h264_videotoolbox")
        config.update({"hardware_encoding": True})
        for _ in range(encoders.GIVE_UP):
            encoders.failed("h264_videotoolbox")
        self.assertEqual(encoders.pick(), "h264_videotoolbox")          # nor does resting
        st = machine.status()
        self.assertEqual((st["using"], st["best"], st["speeds"]), ("h264_videotoolbox", None, {"h264_videotoolbox": None}))
        self.on(system("mac"), has={"h264_videotoolbox", "libx264"})
        self.assertEqual(encoders.fallback("h264_videotoolbox"), "libx264")
        self.assertIsNone(encoders.fallback("libx264"))
        self.on(system(), has={"aac"})
        self.assertIsNone(encoders.pick())
        self.assertEqual(media.encoder_plan(1080)["codec"], ["-c:v", "mpeg4", "-q:v", "3"])

    def test_an_encoder_that_failed_rests(self):
        self.on(system(nvidia=NVIDIA))
        self.remembered("h264_nvenc")
        now = [1000.0]
        with mock.patch.object(encoders.time, "time", lambda: now[0]):
            encoders.failed("h264_nvenc", "the device was lost")
            self.assertTrue(encoders.resting("h264_nvenc"))
            self.assertEqual(encoders.pick(), "libx264")
            self.assertEqual(machine.status()["resting"]["h264_nvenc"], {"count": 1, "why": "the device was lost", "until_test": False})
            now[0] += encoders.REST + 1
            self.assertEqual(encoders.pick(), "h264_nvenc")             # ten minutes on: tried again
            encoders.failed("h264_nvenc")
            encoders.worked("h264_nvenc")                               # a conversion that went through: forgiven
            self.assertEqual(encoders.failures(), {})
            for _ in range(encoders.GIVE_UP):
                encoders.failed("h264_nvenc")
            now[0] += 30 * 86400
            self.assertTrue(encoders.resting("h264_nvenc"))             # three in a row: not until the next test
            self.assertTrue(machine.status()["resting"]["h264_nvenc"]["until_test"])
            encoders.failed("libx264")                                  # (the processor's is never "resting")
            self.assertNotIn("libx264", encoders.failures())
            encoders.forget_failures()
            encoders.failed("h264_nvenc")
            now[0] += encoders.REST + 1
            encoders.failed("h264_nvenc")
            encoders.forgiven("h264_nvenc")                             # that one wasn't its fault: taken back,
            self.assertEqual(encoders.failures()["h264_nvenc"]["count"], 1)
            self.assertFalse(encoders.resting("h264_nvenc"))            # and the rest it was having is the earlier one's
            encoders.forgiven("h264_nvenc")
            self.assertEqual(encoders.failures(), {})
            encoders.forgiven("h264_nvenc")                             # (nothing to take back: nothing happens)


class TheCommands(Clean):
    def command(self, best, how=None, info=INFO, decode=False, **kw):
        self.remembered(best, how, decode)
        return media.stream_command(ITEM, "transcode", 12.5, info, "hls", "/tmp/out", **kw)

    def vf(self, cmd):
        return cmd[cmd.index("-vf") + 1]

    def after(self, cmd, enc):
        i = cmd.index(enc)
        return cmd[i + 1:cmd.index("-g")]

    def test_va_api(self):
        self.on(system(nodes=[node(129)]))
        cmd = self.command("h264_vaapi", {"live": 0, "file": 0, "device": "/dev/dri/renderD129"})
        self.assertEqual(cmd[cmd.index("-vaapi_device"):][:2], ["-vaapi_device", "/dev/dri/renderD129"])
        self.assertLess(cmd.index("-vaapi_device"), cmd.index("-i"))                   # ffmpeg's own option: ahead of the inputs
        self.assertTrue(self.vf(cmd).endswith("scale=-2:'min(ih,1080)',format=nv12,hwupload"))
        self.assertEqual(self.after(cmd, "h264_vaapi"), ["-b:v", "6M", "-maxrate", "16M", "-bufsize", "24M"])
        cmd = self.command("h264_vaapi", {"live": 1, "file": 1, "device": "/dev/dri/renderD129"})      # the low-power way passed
        self.assertEqual(self.after(cmd, "h264_vaapi")[:2], ["-low_power", "1"])
        self.assertNotIn("-hwaccel", cmd)

    def test_nvenc_quick_sync_and_amf(self):
        self.on(system(nodes=[node()], nvidia=NVIDIA))
        cmd = self.command("h264_nvenc", {"live": 0, "file": 0})
        self.assertEqual(self.after(cmd, "h264_nvenc"), ["-preset", "p4", "-rc", "vbr", "-cq", "23", "-b:v", "0", "-maxrate", "16M", "-bufsize", "24M"])
        self.assertTrue(self.vf(cmd).endswith(",format=nv12"))
        self.assertFalse({"-vaapi_device", "-qsv_device"} & set(cmd))
        cmd = self.command("h264_nvenc", {"live": 1, "file": 1})                       # an older ffmpeg's presets
        self.assertEqual(self.after(cmd, "h264_nvenc")[:4], ["-preset", "fast", "-b:v", "6M"])
        cmd = self.command("h264_qsv", {"live": 0, "file": 0, "device": "/dev/dri/renderD128"})
        self.assertEqual(cmd[cmd.index("-qsv_device") + 1], "/dev/dri/renderD128")
        self.assertEqual(self.after(cmd, "h264_qsv"), ["-preset", "faster", "-b:v", "6M", "-maxrate", "16M", "-bufsize", "24M"])
        self.on(system("windows"))
        cmd = self.command("h264_qsv", {"live": 0, "file": 0})                          # Windows: no device to name
        self.assertNotIn("-qsv_device", cmd)
        cmd = self.command("h264_amf", {"live": 0, "file": 0})
        self.assertEqual(self.after(cmd, "h264_amf")[:6], ["-usage", "transcoding", "-quality", "speed", "-rc", "vbr_peak"])

    def test_apples_as_it_always_was(self):
        self.on(system("mac"))
        cmd = self.command("h264_videotoolbox", {"live": 0, "file": 0})
        self.assertEqual(self.after(cmd, "h264_videotoolbox"), ["-allow_sw", "1", "-realtime", "1", "-b:v", "6M", "-maxrate", "16M", "-bufsize", "24M"])
        self.assertTrue(self.vf(cmd).endswith(",format=yuv420p"))
        self.assertEqual(encoders.codec("h264_videotoolbox", 1080, live=False), ["-c:v", "h264_videotoolbox", "-allow_sw", "1", "-q:v", "62"])

    def test_the_processor(self):
        self.on(system(nvidia=NVIDIA))
        cmd = self.command("libx264")
        self.assertEqual(self.after(cmd, "libx264")[:4], ["-preset", cmd[cmd.index("libx264") + 2], "-crf", "21"])
        self.assertTrue(self.vf(cmd).endswith(",format=yuv420p"))
        cmd = self.command("h264_nvenc", software=True)                 # the chip was chosen; this job is done by the processor
        self.assertIn("libx264", cmd)
        self.assertNotIn("h264_nvenc", cmd)
        cmd = self.command("h264_nvenc", encoder="libx264")
        self.assertNotIn("h264_nvenc", cmd)

    def test_the_picture_size_sets_the_rate(self):
        self.assertEqual([encoders.rate(h) for h in (2160, 1080, 720, 480, 360, None)], ["14M", "6M", "3500k", "2M", "2M", "3500k"])
        self.assertEqual(encoders.codec("h264_nvenc", 720, True, {"live": 2}), ["-c:v", "h264_nvenc", "-b:v", "3500k"])
        self.assertEqual(encoders.codec("h264_nvenc", 720, False, {"file": 2}), ["-c:v", "h264_nvenc", "-b:v", "7000k"])

    def test_subtitles_drawn_on_go_to_the_chip_too(self):
        self.on(system(nodes=[node()]))
        cmd = self.command("h264_vaapi", {"device": "/dev/dri/renderD128"}, burn=2)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertTrue(graph.endswith("format=nv12,hwupload[v]"))
        self.assertIn("overlay=", graph)
        self.remembered("h264_vaapi", {"device": "/dev/dri/renderD128"})
        cmd = media.stream_command(ITEM, "remux", 0, INFO, "hls", "/tmp/out", burn=2)      # a remux that has to draw: it converts
        self.assertIn("h264_vaapi", cmd)
        self.assertTrue(media.converts("remux", INFO, 2))
        self.assertFalse(media.converts("remux", INFO, None))

    def test_a_repackaged_video_asks_nothing_of_the_chip(self):
        self.on(system(nodes=[node()]))
        self.remembered("h264_vaapi", {"device": "/dev/dri/renderD128"})
        cmd = media.stream_command(ITEM, "remux", 0, INFO, "hls", "/tmp/out")
        self.assertFalse({"-vaapi_device", "h264_vaapi", "-vf"} & set(cmd))
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "copy")

    def test_hevc_decoded_on_the_chip_only_where_that_measured_faster(self):
        self.on(system(nodes=[node()]))
        hevc = dict(INFO, video={"index": 0, "codec": "hevc", "height": 1080, "pix_fmt": "yuv420p10le"})
        how = {"device": "/dev/dri/renderD128"}
        cmd = self.command("h264_vaapi", how, hevc, decode=True)
        i = cmd.index("-hwaccel")
        self.assertEqual(cmd[i:i + 4], ["-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128"])
        self.assertLess(i, cmd.index("-i"))
        self.assertNotIn("-hwaccel", self.command("h264_vaapi", how, hevc, decode=False))        # not measured faster: the processor
        self.assertNotIn("-hwaccel", self.command("h264_vaapi", how, INFO, decode=True))         # not HEVC: nothing to gain
        self.assertNotIn("-hwaccel", self.command("h264_vaapi", how, hevc, decode=True, software=True))
        self.on(system(nvidia=NVIDIA))
        self.assertEqual(encoders.decode_before_input("h264_nvenc"), ["-hwaccel", "cuda"])
        self.on(system("windows"))
        self.assertEqual(encoders.decode_before_input("h264_qsv"), ["-hwaccel", "d3d11va"])
        self.assertEqual(encoders.decode_before_input("h264_amf"), ["-hwaccel", "d3d11va"])
        self.assertEqual(encoders.decode_before_input("h264_videotoolbox"), ["-hwaccel", "videotoolbox"])
        self.assertEqual(encoders.decode_before_input("libx264"), [])

    def test_where_only_the_codec_can_be_given(self):
        self.on(system(nodes=[node()], nvidia=NVIDIA))
        self.remembered("h264_vaapi", {"device": "/dev/dri/renderD128"})
        self.assertEqual(media.h264_args(720, live=False)[:2], ["-c:v", "libx264"])      # VA-API needs its own filters
        self.remembered("h264_nvenc")
        self.assertEqual(media.h264_args(720, live=False)[:2], ["-c:v", "h264_nvenc"])

    def test_a_file_converted_for_good(self):
        self.on(system(nodes=[node()]))
        self.remembered("h264_qsv", {"live": 0, "file": 0, "device": "/dev/dri/renderD128"})
        info = {"video": {"index": 0, "codec": "mpeg4", "height": 480}, "audio": [{"index": 1, "codec": "mp3", "channels": 2}], "subs": []}
        cmd, how = optimize.build_command("/nowhere/old.avi", "/nowhere/old.mp4.sofa-part", info)
        i = cmd.index("h264_qsv")
        self.assertEqual(cmd[i + 1:i + 5], ["-preset", "medium", "-global_quality", "21"])
        self.assertLess(cmd.index("-qsv_device"), cmd.index("-i"))
        self.assertEqual(cmd[cmd.index("-vf") + 1], "format=nv12")
        self.assertIn("(Quick Sync)", how)
        cmd, how = optimize.build_command("/nowhere/old.avi", "/nowhere/old.mp4.sofa-part", info, software=True)
        self.assertIn("libx264", cmd)
        self.assertFalse({"h264_qsv", "-qsv_device"} & set(cmd))
        self.assertNotIn("(", how.split(",")[0])

    def test_the_second_part_of_a_stream_has_names_of_its_own(self):
        self.on(system())
        cmd = media.stream_command(ITEM, "transcode", 20.0, INFO, "hls", "/tmp/out", software=True, part=1)
        self.assertEqual(cmd[cmd.index("-bsf:v") + 1], "dump_extra=freq=keyframe")      # its parameters at every key frame
        self.assertEqual(cmd[cmd.index("-hls_fmp4_init_filename") + 1], "init1.mp4")
        self.assertEqual((cmd[cmd.index("-hls_segment_filename") + 1], cmd[-1]), ("/tmp/out/alt%05d.m4s", "/tmp/out/index1.m3u8"))
        cmd = media.stream_command(ITEM, "transcode", 20.0, INFO, "hls", "/tmp/out")
        self.assertNotIn("-bsf:v", cmd)
        self.assertEqual((cmd[cmd.index("-hls_fmp4_init_filename") + 1], cmd[-1]), ("init.mp4", "/tmp/out/index.m3u8"))
        for name, ok in (("index.m3u8", True), ("init.mp4", True), ("init1.mp4", True), ("seg00002.m4s", True), ("alt00002.m4s", True),
                         ("index1.m3u8", False), ("init2.mp4", False), ("../index.m3u8", False), ("alt2.m4s", False)):
            self.assertEqual(bool(media.HLS_FILE.fullmatch(name)), ok, name)       # the first part's playlist is Sofa's own business


REAL = media.tool("ffmpeg")
REAL_PROBE = media.tool("ffprobe")


@unittest.skipUnless(REAL and REAL_PROBE and os.name == "posix", "needs ffmpeg, and a system where a script can stand in for it")
class WithAStandInForTheChip(Clean):
    """A computer whose ffmpeg has NVIDIA's, Intel's and AMD's encoders, as far as Sofa can tell. The conversions are
    real (x264 underneath); the driver's behaviour is the stand-in's."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="sofa-standin-", dir=ROOT)
        launcher = os.path.join(cls.folder, "ffmpeg")
        with open(launcher, "w") as f:
            f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, os.path.join(HERE, "stand_in_ffmpeg.py")))
        os.chmod(launcher, 0o755)
        os.symlink(REAL_PROBE, os.path.join(cls.folder, "ffprobe"))
        cls.clip = os.path.join(cls.folder, "clip.mkv")                  # 24 seconds, small: quick to convert, long enough to stop in
        subprocess.run([REAL, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24", "-f", "lavfi", "-i",
                        "sine=frequency=440", "-t", "24", "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-b:a", "64k", cls.clip], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, True)

    def setUp(self):
        super().setUp()
        self.conf = os.path.join(self.folder, "stand-in.json")
        self.log = os.path.join(self.folder, "calls.log")
        self.gone = os.path.join(self.folder, "chip-gone")
        for f in (self.log, self.gone):
            if os.path.exists(f):
                os.remove(f)
        p = mock.patch.dict(os.environ, {"SOFA_STAND_IN": self.conf})
        p.start()
        self.addCleanup(p.stop)
        config.update({"ffmpeg": self.folder})
        self.assertEqual(media.tool("ffmpeg"), os.path.join(self.folder, "ffmpeg"))
        self.item = {"id": "clip1", "path": self.clip, "ext": "mkv", "title": "Clip"}
        self.addCleanup(lambda: [media.hls_stop(sid) for sid in list(media._hls)])

    def chip(self, has=("h264_nvenc", "h264_qsv", "h264_vaapi"), works=("h264_nvenc",), **more):
        with open(self.conf, "w") as f:
            json.dump(dict({"real": REAL, "has": list(has), "works": list(works), "log": self.log}, **more), f)
        media._encoders = None                                           # ask this ffmpeg again
        self.assertTrue(set(has) <= media.encoders())

    def calls(self):
        with open(self.log) as f:
            return [json.loads(l) for l in f if l.strip()]

    def playlist(self, sid, until="#EXT-X-ENDLIST", timeout=90):
        deadline = time.time() + timeout
        text = ""
        while time.time() < deadline:
            path = media.hls_file(sid, "index.m3u8")
            if path:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                if until in text:
                    return text
            time.sleep(0.2)
        self.fail("the playlist never got %s:\n%s" % (until, text))

    def frames(self, *files):
        """(pictures the real ffprobe decodes from these files read one after another, what it complained of)."""
        if len(files) > 1:
            whole = os.path.join(self.folder, "whole.mp4")
            with open(whole, "wb") as out:
                for name in files:
                    with open(name, "rb") as f:
                        out.write(f.read())
            files = (whole,)
        got = subprocess.run([REAL_PROBE, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
                              "-of", "csv=p=0", files[0]], capture_output=True, text=True, timeout=120)
        self.assertEqual(got.returncode, 0, got.stderr[-400:])
        return int(got.stdout.split()[0].strip(",")), got.stderr.strip()

    def played(self, sid, text):
        """What a player gets: every file the playlist names, through Sofa's own door; then the whole stream read by
        the real ffprobe from the playlist. (seconds the playlist lists, pictures decoded, ffprobe's complaints)."""
        names = set(re.findall(r'URI="([^"]+)"', text)) | {l for l in text.split("\n") if l and not l.startswith("#")}
        for name in names:
            self.assertTrue(media.hls_file(sid, name), name)
        frames, said = self.frames(os.path.join(media._hls[sid]["dir"], "index.m3u8"))
        return sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", text)), frames, said

    def test_the_test_finds_the_one_that_works(self):
        self.on(system(nodes=[node()], nvidia=NVIDIA), has=())
        self.chip()
        with mock.patch.object(machine, "_time_encoder", lambda name, how=None: {"h264_nvenc": 300.0, "libx264": 140.0}[name]), \
                mock.patch.object(machine, "_damaged", lambda name, how=None: False), \
                mock.patch.object(encoders, "decode_helps", lambda *a: False):
            got = machine.measure(force=True)
        self.assertEqual(got["best"], "h264_nvenc")
        self.assertEqual(got["speeds"], {"h264_nvenc": 300.0, "libx264": 140.0, "h264_qsv": None, "h264_vaapi": None})
        self.assertEqual(got["how"], {"h264_nvenc": {"live": 0, "file": 0}})
        self.assertIn("MFX session", got["why"]["h264_qsv"])              # why not, in ffmpeg's own words, for the Server page
        self.assertIn("VAAPI", got["why"]["h264_vaapi"])
        tried = [c[c.index("-c:v") + 1] for c in self.calls() if "-c:v" in c and "testsrc2=size=1280x720:rate=30" in c]
        self.assertEqual(sorted(set(tried)), ["h264_nvenc", "h264_qsv", "h264_vaapi"])        # each had its one-second try
        st = machine.status()
        self.assertEqual((st["using"], st["hardware"], st["best"]), ("h264_nvenc", ["h264_nvenc", "h264_qsv", "h264_vaapi"], "h264_nvenc"))
        self.assertEqual(machine.measure()["best"], "h264_nvenc")          # remembered: not tested again
        self.on(system(nodes=[node()], nvidia=dict(NVIDIA, driver="999.1")), has=media.encoders())
        machine._result.clear()
        self.assertIsNone(machine.best_encoder())                          # another driver: what was remembered no longer counts

    def test_the_timing_and_the_picture_check_run_with_a_chips_encoder(self):
        self.on(system(nvidia=NVIDIA), has=())
        self.chip()
        with mock.patch.object(machine, "TEST_SECONDS", 1):
            self.assertGreater(machine._time_encoder("h264_nvenc", {"live": 0, "file": 0}), 1)
            self.assertIsNone(machine._time_encoder("h264_qsv", {}))
        self.assertFalse(machine._damaged("h264_nvenc", {"live": 0, "file": 0}))
        self.assertTrue(machine._damaged("h264_vaapi", {"device": "/dev/dri/renderD128"}))      # it made nothing at all

    def test_a_driver_that_wont_be_asked_one_way_is_asked_the_next(self):
        self.on(system(nvidia=NVIDIA), has=())
        self.chip(refuses={"h264_nvenc": ["p4", "p5"]})
        self.assertEqual(encoders.probe("h264_nvenc"), {"ok": True, "why": "", "live": 1, "file": 1})
        self.chip(refuses={"h264_nvenc": ["p4", "p5", "fast", "medium"]})
        self.assertEqual(encoders.probe("h264_nvenc"), {"ok": True, "why": "", "live": 2, "file": 2})
        self.chip(works=())
        got = encoders.probe("h264_nvenc")
        self.assertEqual((got["ok"], "libnvidia-encode" in got["why"]), (False, True))
        got = encoders.probe("h264_vaapi", "/dev/dri/renderD128")
        self.assertEqual((got["ok"], got["device"]), (False, "/dev/dri/renderD128"))

    def test_a_stream_the_chip_converts(self):
        self.on(system(nvidia=NVIDIA), has=())
        self.chip()
        self.remembered("h264_nvenc", {"live": 0, "file": 0})
        sid = media.hls_start(self.item, "transcode", 0, "someone")
        text = self.playlist(sid)
        self.assertNotIn("DISCONTINUITY", text)
        seconds, frames, said = self.played(sid, text)
        self.assertAlmostEqual(seconds, 24, delta=1.5)
        self.assertEqual((frames, said), (24 * 24, ""))                   # every picture of the 24 seconds
        self.assertEqual(media._streams["hls-" + sid]["encoder"], "h264_nvenc")
        asked = [c for c in self.calls() if "h264_nvenc" in c and "-hls_time" in c]
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0][asked[0].index("h264_nvenc") + 1:][:2], ["-preset", "p4"])
        self.assertFalse(encoders.resting("h264_nvenc"))

    def test_a_chip_that_fails_as_it_starts(self):
        self.on(system(nvidia=NVIDIA), has=())
        self.chip(stops_now={"h264_nvenc": self.gone})
        self.remembered("h264_nvenc", {"live": 0, "file": 0})
        open(self.gone, "w").close()                                     # passed its test; gone when the film starts
        sid = media.hls_start(self.item, "transcode", 4, "someone")
        text = self.playlist(sid)
        self.assertNotIn("DISCONTINUITY", text)                          # nothing had been made: one stream, by the processor
        self.assertNotIn("init1.mp4", text)
        seconds, frames, said = self.played(sid, text)
        self.assertAlmostEqual(seconds, 20, delta=1.5)
        self.assertEqual((frames, said), (20 * 24, ""))
        self.assertEqual(media._streams["hls-" + sid]["encoder"], "libx264")
        self.assertTrue(encoders.resting("h264_nvenc"))
        self.assertEqual(encoders.pick(), "libx264")                     # and the next one doesn't try the chip
        self.assertIsNone(media.last_error(self.item["id"]))             # nobody is told the video couldn't be converted
        media.hls_stop(sid)
        sid = media.hls_start(self.item, "transcode", 0, "someone")
        self.playlist(sid)
        self.assertEqual(len([c for c in self.calls() if "h264_nvenc" in c and "-hls_time" in c]), 1)

    def test_a_chip_that_stops_in_the_middle(self):
        self.on(system(nvidia=NVIDIA), has=())
        self.chip(stops={"h264_nvenc": 2})                               # two segments in, the device is lost
        self.remembered("h264_nvenc", {"live": 0, "file": 0})
        sid = media.hls_start(self.item, "transcode", 0, "someone")
        text = self.playlist(sid)
        self.assertEqual(text.count("#EXT-X-DISCONTINUITY"), 1)
        self.assertEqual(text.count("#EXTM3U"), 1)
        first, second = text.split("#EXT-X-DISCONTINUITY")
        self.assertIn('#EXT-X-MAP:URI="init.mp4"', first)
        self.assertIn("seg00000.m4s", first)
        self.assertTrue(second.lstrip().startswith('#EXT-X-MAP:URI="init1.mp4"'))    # another encoder's video: its own start
        self.assertIn("alt00000.m4s", second)
        self.assertNotIn("seg0", second)
        seconds, frames, said = self.played(sid, text)
        self.assertAlmostEqual(seconds, 24, delta=1.5)                   # the whole film, though the chip made a third of it
        made = sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", first))
        again = [c for c in self.calls() if "libx264" in c and "-hls_time" in c]
        self.assertEqual(len(again), 1)
        self.assertAlmostEqual(float(again[0][again[0].index("-ss") + 1]), made, delta=0.01)      # from where the chip stopped
        self.assertIn("dump_extra=freq=keyframe", again[0])
        # Each part is whole, read as a player that follows the playlist reads it: its own start, then its segments.
        folder = media._hls[sid]["dir"]
        part = lambda init, lines: [os.path.join(folder, init)] + [os.path.join(folder, l) for l in lines.split("\n") if l.endswith(".m4s")]   # noqa: E731
        self.assertEqual(self.frames(*part("init.mp4", first)), (round(made * 24), ""))
        self.assertEqual(self.frames(*part("init1.mp4", second)), (round((24 - made) * 24), ""))
        # ffmpeg's own reader (what the box's mpv is built on) keeps the first start: it plays on without a complaint,
        # after passing over the second part's first segment of picture.
        self.assertEqual(said, "")
        self.assertGreaterEqual(frames, 24 * 24 - 4 * 24)
        s = media._hls[sid]
        self.assertEqual((s["encoder"], s["chip"], s["kind"]), ("libx264", False, None))        # (a mixed stream teaches nothing)
        self.assertTrue(encoders.resting("h264_nvenc"))

    def test_a_stream_in_one_piece(self):
        self.on(system(nvidia=NVIDIA), has=())
        self.chip(stops_now={"h264_nvenc": self.gone})
        self.remembered("h264_nvenc", {"live": 0, "file": 0})
        open(self.gone, "w").close()
        info = media.probe(self.clip)
        out = io.BytesIO()
        media.run_stream(self.item, "transcode", 0, info, out, "someone", fmt="mp4")
        self.assertGreater(len(out.getvalue()), 20000)                   # nothing had been sent: the same stream, by the processor
        self.assertEqual(out.getvalue()[4:8], b"ftyp")
        self.assertTrue(encoders.resting("h264_nvenc"))
        kinds = [c[c.index("-c:v") + 1] for c in self.calls() if "frag_keyframe+empty_moov+default_base_moof" in c]
        self.assertEqual(kinds, ["h264_nvenc", "libx264"])

    def test_a_file_the_chip_gives_up_on_is_converted_by_the_processor(self):
        self.on(system(nvidia=NVIDIA), has=())
        self.chip(stops_now={"h264_nvenc": self.gone})
        self.remembered("h264_nvenc", {"live": 0, "file": 0})
        open(self.gone, "w").close()
        src = os.path.join(config.path("movies"), "Old Film (1999)", "Old Film (1999).mkv")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        shutil.copy(self.clip, src)
        self.addCleanup(shutil.rmtree, os.path.dirname(src), True)
        dest, how = optimize.convert(src)
        self.assertTrue(dest.endswith(".mp4") and os.path.exists(dest))
        self.assertEqual(media.probe(dest)["video"]["codec"], "h264")
        self.assertNotIn("NVENC", how)
        self.assertEqual(encoders.failures()["h264_nvenc"]["count"], 1)
        kinds = [c[c.index("-c:v") + 1] for c in self.calls() if "-progress" in c]
        self.assertEqual(kinds, ["h264_nvenc", "libx264"])
        os.remove(self.gone)                                             # the chip is back, and rested: the next file is its
        encoders.forget_failures()
        shutil.copy(self.clip, src)
        dest, how = optimize.convert(src)
        self.assertIn("(NVENC)", how)
        self.assertEqual(encoders.failures(), {})

    def test_a_damaged_file_isnt_the_chips_fault(self):
        self.on(system(nvidia=NVIDIA), has=())
        self.chip(spoiled="spoiled-film")                                # whoever converts this one fails
        self.remembered("h264_nvenc", {"live": 0, "file": 0})
        bad = os.path.join(self.folder, "spoiled-film.mkv")
        shutil.copy(self.clip, bad)
        item = {"id": "bad1", "path": bad, "ext": "mkv", "title": "Spoiled"}
        sid = media.hls_start(item, "transcode", 0, "someone")
        deadline = time.time() + 30
        while time.time() < deadline and (media._hls[sid]["chip"] or media._hls[sid]["proc"].poll() is None or encoders.failures()):
            time.sleep(0.1)
        self.assertEqual(media._hls[sid]["encoder"], "libx264")          # the processor was tried,
        self.assertEqual(encoders.failures(), {})                         # it failed too, so the chip isn't blamed
        self.assertEqual(encoders.pick(), "h264_nvenc")
        self.assertIsNone(media.hls_file(sid, "index.m3u8"))             # and the player is told there's nothing, as before
        deadline = time.time() + 10
        while time.time() < deadline and not media.last_error("bad1"):
            time.sleep(0.1)
        self.assertIn("Invalid data", media.last_error("bad1")["message"])       # and the Server page says why
        out = io.BytesIO()
        media.run_stream(item, "transcode", 0, media.probe(bad), out, "someone", fmt="mp4")
        self.assertEqual((out.getvalue(), encoders.failures()), (b"", {}))
        src = os.path.join(config.path("movies"), "Spoiled (1999)", "spoiled-film (1999).mkv")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        shutil.copy(self.clip, src)
        self.addCleanup(shutil.rmtree, os.path.dirname(src), True)
        with self.assertRaises(RuntimeError):
            optimize.convert(src)
        self.assertEqual(encoders.failures(), {})
        self.assertTrue(os.path.exists(src))                             # the file is where it was

    @unittest.skipUnless(REAL and "libx265" in subprocess.run([REAL, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout,
                         "this ffmpeg can't make the HEVC clip the decoding test uses")
    def test_decoding_is_the_chips_only_when_it_measured_faster(self):
        self.on(system(nvidia=NVIDIA), has=())
        self.chip(decode_cost=1.5)                                       # the processor takes this much longer to decode
        self.assertTrue(encoders.decode_helps("h264_nvenc", {}, os.path.join(self.folder, "cache")))
        self.chip(decode_cost=0)
        with mock.patch.object(encoders, "DECODE_GAIN", 3.0):             # (no faster: left to the processor)
            self.assertFalse(encoders.decode_helps("h264_nvenc", {}, os.path.join(self.folder, "cache")))
        self.chip(has=("h264_nvenc",))
        media._encoders = media.encoders() - {"libx265"}
        self.assertFalse(encoders.decode_helps("h264_nvenc", {}, os.path.join(self.folder, "cache")))    # no clip to try with: not used
        self.assertFalse(os.path.exists(os.path.join(self.folder, "cache", "decode-check.mkv")))


@unittest.skipUnless(REAL, "needs ffmpeg")
class OnThisComputer(Clean):
    """The real test, on whatever these tests run on: this ffmpeg, this system's graphics, nothing stood in for.
    What it finds is printed, so a run's log says what that machine has."""

    def test_only_what_passed_is_ever_used(self):
        media._encoders = None
        self.addCleanup(lambda: os.path.exists(machine.CACHE) and os.remove(machine.CACHE))
        with mock.patch.object(machine, "TEST_SECONDS", 1), mock.patch.object(encoders, "decode_helps", lambda *a: False):
            lines = machine.report(test=True)
        sys.stderr.write("\n    " + "\n    ".join(lines) + "\n")
        got = dict(machine._result)
        tried = [name for name, _device in encoders.candidates()]
        self.assertEqual(sorted(set(tried)), sorted(k for k in got["speeds"] if k in encoders.HARDWARE))
        for name in got["why"]:
            self.assertIsNone(got["speeds"][name])                     # one that failed its one-second try is never timed,
            self.assertNotEqual(got["best"], name)                     # and never chosen
        for name in got["how"]:
            self.assertIn(name, encoders.HARDWARE)
        if got["best"]:
            self.assertTrue(got["speeds"][got["best"]])
            self.assertNotIn(got["best"], got["damaged"])
        if "libx264" in media.encoders():
            self.assertTrue(got["speeds"]["libx264"])                  # the processor's encoder always works,
            if not any(got["speeds"].get(k) for k in encoders.HARDWARE):
                self.assertEqual((got["best"], encoders.pick()), ("libx264", "libx264"))      # and is what's used with no chip
        self.assertIn(encoders.pick(), (got["best"], "libx264", "h264_videotoolbox"))
        self.assertTrue(any(l.startswith("Converting with: ") for l in lines))


@unittest.skipUnless(sys.platform == "darwin" and REAL and "h264_videotoolbox" in subprocess.run(
    [REAL, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout, "a Mac whose ffmpeg has Apple's encoder")
class OnAMacsOwnChip(Clean):
    """The real thing, where there is one: Apple's VideoToolbox on the Mac these tests run on."""

    def test_it_passes_its_test_and_converts_a_stream(self):
        media._encoders = None
        got = encoders.probe("h264_videotoolbox")
        self.assertEqual((got["ok"], got["live"], got["file"]), (True, 0, 0))
        self.assertEqual(encoders.candidates(), [("h264_videotoolbox", None)])
        folder = tempfile.mkdtemp(prefix="sofa-vt-", dir=ROOT)
        self.addCleanup(shutil.rmtree, folder, True)
        clip = os.path.join(folder, "clip.mkv")
        subprocess.run([REAL, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24", "-f", "lavfi", "-i",
                        "sine=frequency=440", "-t", "12", "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", clip], check=True)
        self.remembered("h264_videotoolbox", {"live": 0, "file": 0})
        sid = media.hls_start({"id": "vt1", "path": clip, "ext": "mkv", "title": "Clip"}, "transcode", 0, "someone")
        self.addCleanup(media.hls_stop, sid)
        deadline, text = time.time() + 60, ""
        while time.time() < deadline and "#EXT-X-ENDLIST" not in text:
            path = media.hls_file(sid, "index.m3u8")
            if path:
                with open(path) as f:
                    text = f.read()
            time.sleep(0.2)
        self.assertIn("#EXT-X-ENDLIST", text)
        self.assertNotIn("DISCONTINUITY", text)
        self.assertEqual(media._streams["hls-" + sid]["encoder"], "h264_videotoolbox")
        out = subprocess.run([REAL_PROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,height:stream_tags=encoder",
                              "-of", "json", os.path.join(media._hls[sid]["dir"], "index.m3u8")], capture_output=True, text=True, timeout=60)
        stream = json.loads(out.stdout)["streams"][0]
        self.assertEqual((stream["codec_name"], stream["height"]), ("h264", 720))
        self.assertFalse(encoders.resting("h264_videotoolbox"))


if __name__ == "__main__":
    unittest.main()
