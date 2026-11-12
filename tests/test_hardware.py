"""Sofa 1.5.8: Sofa sizes itself to the computer it runs on, and uses its cores.

- What the computer is (sofa/hardware.py): the cores Sofa may use (a container's limit and a CPU set count), its
  memory (a container's limit counts), the processor by name on ARM too, a Pi's model, a VM or a container, the
  chips for video. ARM was all "an older processor" before (only Intel's AVX2 was looked for), so gentle mode was on
  for a Pi 5, an ARM server and Docker on a Mac with Apple silicon.
- Background work spread over the cores (workers): file details, pictures taken from videos, artwork; one at a time
  on a small board or while someone watches what Sofa converts. A library read took its ~120 pictures one at a time.
- A library read no longer grows as the square of the library (each show looked at every item read so far), and reads
  each folder once (a season's folder was read again for every episode in it).
- Memory: what Sofa frees goes back to the system; Live TV's channels share what they have in common; the details of
  videos with nothing next to them aren't kept; one conversion at a time on a computer with 2 GB or less.

Stand-in /proc and /sys trees; no Pi needed. The measured numbers are in CHANGES.md."""
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests import ROOT
from sofa import hardware, library, live, machine, media, places, report, sidecars


def tree(files):
    root = tempfile.mkdtemp(prefix="sofa-hw-", dir=ROOT)
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    return root


def arm(part, n=4, maker="0x41"):
    return "".join("processor\t: %d\nFeatures\t: fp asimd\nCPU implementer\t: %s\nCPU part\t: %s\n\n" % (i, maker, part)
                   for i in range(n))


PI3 = {"proc/cpuinfo": arm("0xd03"), "proc/meminfo": "MemTotal:  925000 kB\nMemAvailable:  400000 kB\n",
       "proc/device-tree/model": "Raspberry Pi 3 Model B Plus Rev 1.3\0",
       "sys/class/video4linux/video10/name": "bcm2835-codec-decode\n", "sys/class/video4linux/video11/name": "bcm2835-codec-encode\n",
       "sys/class/video4linux/video12/name": "bcm2835-codec-isp\n"}
PI5 = {"proc/cpuinfo": arm("0xd0b"), "proc/meminfo": "MemTotal:  8000000 kB\nMemAvailable:  7000000 kB\n",
       "proc/device-tree/model": "Raspberry Pi 5 Model B Rev 1.0\0", "sys/class/video4linux/video19/name": "rpi-hevc-dec\n"}
X86 = {"proc/cpuinfo": "processor\t: 0\nmodel name\t: Intel(R) Core(TM) i5-8500 CPU @ 3.00GHz\nflags\t\t: fpu sse2 avx avx2\n\n",
       "proc/meminfo": "MemTotal:  16000000 kB\nMemAvailable:  12000000 kB\n"}


class At(unittest.TestCase):
    def at(self, files, cpus=4):
        root = tree(files)
        self.addCleanup(shutil.rmtree, root, True)
        patches = [mock.patch.object(hardware, "ROOT", root), mock.patch.dict(os.environ, {"SOFA_HW_CPUS": str(cpus)}),
                   mock.patch.object(hardware, "_info", {}), mock.patch.object(hardware, "_avail", {"at": -1e9, "value": None}),
                   mock.patch.object(machine, "_described", {})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class WhatTheComputerIs(At):
    def test_a_pi_3_is_small_and_its_cores_are_slow(self):
        self.at(PI3)
        d = hardware.describe()
        self.assertEqual((d["cpu"], d["slow_cores"], d["pi_gen"], d["cores"]), ("4 x Cortex-A53", True, 3, 4))
        self.assertEqual(d["pi"], "Raspberry Pi 3 Model B Plus Rev 1.3")
        self.assertEqual(d["video"], ["V4L2: bcm2835-codec-decode (video10)", "V4L2: bcm2835-codec-encode (video11)"])
        self.assertTrue(hardware.small())
        self.assertEqual(hardware.workers(), 1)                          # a Pi 3: one at a time, as before
        self.assertIs(machine.describe()["modern_cpu"], False)
        self.assertTrue(machine.gentle())

    def test_a_pi_5_isnt_an_older_processor(self):
        self.at(PI5)
        self.assertEqual(hardware.describe()["cpu"], "4 x Cortex-A76")
        self.assertIs(machine.describe()["modern_cpu"], True)            # (it was False: no AVX2 on ARM)
        with mock.patch.object(machine, "_result", {}), mock.patch.object(hardware, "available", return_value=7 * 2**30):
            self.assertFalse(machine.gentle())
            self.assertEqual(hardware.workers(), 2)                      # half the cores: the rest for whoever watches
        self.assertIn("Raspberry Pi 5 Model B Rev 1.0", hardware.summary())

    def test_intel_and_amd_by_avx2_as_before(self):
        self.at(X86, cpus=6)
        self.assertEqual((hardware.describe()["cpu"], hardware.describe()["slow_cores"]),
                         ("Intel(R) Core(TM) i5-8500 CPU @ 3.00GHz", False))
        self.at(dict(X86, **{"proc/cpuinfo": X86["proc/cpuinfo"].replace(" avx2", "")}))
        self.assertTrue(hardware.describe()["slow_cores"])                # (a 2011 iMac's)
        self.at({"proc/cpuinfo": arm("0x000", maker="0x61")})              # Docker on a Mac with Apple silicon
        self.assertEqual(hardware.describe()["cpu"], "4 x Apple silicon")
        self.assertFalse(hardware.describe()["slow_cores"])

    def test_a_containers_limits_count(self):
        self.at(dict(X86, **{"sys/fs/cgroup/cpu.max": "150000 100000\n", "sys/fs/cgroup/memory.max": "1073741824\n",
                             "sys/fs/cgroup/memory.current": "805306368\n", ".dockerenv": ""}), cpus=12)
        d = hardware.describe()
        self.assertEqual((d["cores"], d["cpu_count"] > 0, d["memory"]), (2, True, 2**30))    # 1.5 cores: two to use
        self.assertEqual(hardware.available(), 2**28)                     # its limit less what it uses (256 MB)
        self.assertEqual(d["virtual"], "a container (Docker)")
        self.at(dict(X86, **{"sys/fs/cgroup/cpu.max": "max 100000\n", "sys/fs/cgroup/memory.max": "max\n"}), cpus=12)
        self.assertEqual((hardware.cores(), hardware.memory()), (12, 16000000 * 1024))

    def test_a_virtual_machine(self):
        self.at(dict(X86, **{"sys/class/dmi/id/sys_vendor": "QEMU\n", "sys/class/dmi/id/product_name": "Standard PC\n"}))
        self.assertEqual(hardware.virtual(), "a virtual machine (QEMU)")
        self.at(dict(X86, **{"dev/dri/renderD128": "", "sys/class/drm/renderD128/device/vendor": "0x1002\n"}))
        self.assertEqual(hardware.video_chips(), ["VA-API: AMD (renderD128)"])


class SpreadOverTheCores(At):
    def test_workers_by_cores_memory_and_whos_watching(self):
        self.at(X86, cpus=16)
        with mock.patch.object(hardware, "available", return_value=8 * 2**30):
            with mock.patch.object(os, "getloadavg", return_value=(30.0, 30.0, 30.0)):
                self.assertEqual(hardware.workers(), 4)                    # never more than four (its own load: still four)
            self.assertEqual(hardware.threads_each(4), 4)
            with mock.patch.object(media, "busy", return_value=True):
                self.assertEqual(hardware.workers(), 1)                    # someone watches what Sofa converts
        with mock.patch.object(hardware, "available", return_value=600 * 2**20):
            self.assertEqual(hardware.workers(), 2)                        # 600 MB free: two pictures from 4K at most
            self.assertEqual(hardware.workers(heavy=False), 4)

    def test_each_runs_them_side_by_side_in_order(self):
        at_once, most, lock = [0], [0], threading.Lock()

        def job(n):
            with lock:
                at_once[0] += 1
                most[0] = max(most[0], at_once[0])
            time.sleep(0.15)
            with lock:
                at_once[0] -= 1
            return n * n
        started = time.monotonic()
        self.assertEqual(hardware.each(job, range(6), most=3), [0, 1, 4, 9, 16, 25])
        self.assertEqual(most[0], 3)
        self.assertLess(time.monotonic() - started, 0.6)                   # (two rounds, not six)
        most[0] = 0
        self.assertEqual(hardware.each(job, range(3), most=1), [0, 1, 4])
        self.assertEqual(most[0], 1)

    def test_one_that_fails_doesnt_stop_the_rest(self):
        done = []

        def job(n):
            if n == 1:
                raise OSError("unreadable")
            done.append(n)
        with self.assertRaises(OSError):
            hardware.each(job, range(4), most=2)
        self.assertEqual(sorted(done), [0, 2, 3])


class LibraryRead(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sofa-show-", dir=ROOT)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.show = os.path.join(self.dir, "Stand In Show")
        for e in range(1, 7):
            path = os.path.join(self.show, "Season 1", "Stand In Show S01E%02d.mp4" % e)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"\0" * 1024)
        with open(os.path.join(self.show, "Season 1", "Stand In Show S01E02.en.srt"), "w") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nHi\n")

    def read(self, workers):
        at_once, most, lock = [0], [0], threading.Lock()

        def frame(video, dest, at=12.0):                                   # a picture from the video, taken slowly
            with lock:
                at_once[0] += 1
                most[0] = max(most[0], at_once[0])
            time.sleep(0.1)
            with open(dest, "wb") as f:
                f.write(b"\xff\xd8 still")
            with lock:
                at_once[0] -= 1
            return True
        lib = library.Library()
        with mock.patch.object(places, "roots", side_effect=lambda key: [(key, self.dir)] if key == "shows" else []), \
                mock.patch.object(library.music, "scan", return_value={"tracks": [], "albums": [], "artists": [], "videos": []}), \
                mock.patch.object(media, "extract_frame", side_effect=frame), mock.patch.object(media, "tool", return_value="ffmpeg"), \
                mock.patch.object(machine, "heavy_ok", return_value=True), mock.patch.object(hardware, "workers", return_value=workers):
            self.assertTrue(lib.scan("tests"))
        return lib, most[0]

    def test_pictures_from_the_videos_taken_side_by_side(self):
        lib, most = self.read(3)
        self.assertEqual(most, 3)
        eps = [i for i in lib.items.values() if i["kind"] == "episode"]
        self.assertEqual(len(eps), 6)
        for ep in eps:                                                    # each its own picture, where it always went
            self.assertEqual(ep["thumb_path"], os.path.join(os.path.dirname(ep["path"]), "metadata",
                                                            os.path.basename(ep["path"])[:-4] + ".jpg"))
            self.assertTrue(os.path.exists(ep["thumb_path"]))
        show = lib.shows[0]
        self.assertEqual(show["added"], max(ep["added"] for ep in eps))    # (its own episodes', not every item's)
        self.assertEqual([len(e["subs"]) if isinstance(e["subs"], list) else e["subs"]
                          for e in show["seasons"][0]["episodes"]], [0, 1, 0, 0, 0, 0])   # (its subtitles, read from the listing)
        self.assertIsNone(lib._ls)                                         # (the listings go with the read)
        again, _ = self.read(3)                                            # read again: the pictures are found, not taken
        self.assertEqual(sorted(i["thumb_path"] for i in again.items.values()), sorted(ep["thumb_path"] for ep in eps))

    def test_one_at_a_time_is_the_same_library(self):
        lib, most = self.read(1)
        self.assertEqual(most, 1)
        self.assertEqual(len([i for i in lib.items.values() if i.get("thumb_path")]), 6)

    def test_movies_covers_decided_side_by_side_with_the_same_ids(self):
        """A movie's own cover (no service knows it) is looked at against the video, which is read for its size: one
        movie at a time, that was most of a first read. Now several at once, at the end of the folder; the ids are
        taken in order as before, so two movies of the same name keep theirs."""
        for where in ("Movies", "Movies again"):               # (a cover looked at once is remembered: two of each)
            for name in ("Heat (1995)", "Heat (1995) Extended", "Ronin (1998)", "Tenet (2020)", "Up (2009)"):
                os.makedirs(os.path.join(self.dir, where, name))
                with open(os.path.join(self.dir, where, name, name + ".mp4"), "wb") as f:
                    f.write(b"\0" * 1024)
                with open(os.path.join(self.dir, where, name, "poster.jpg"), "wb") as f:
                    f.write(b"\xff\xd8 not a still")
        at_once, most, lock = [0], [0], threading.Lock()

        def probe(path, cached_only=False):
            if cached_only:
                return None
            with lock:
                at_once[0] += 1
                most[0] = max(most[0], at_once[0])
            time.sleep(0.1)
            with lock:
                at_once[0] -= 1
            return {"video": {"width": 1920, "height": 1080}, "duration": 5400}

        def read(workers, where):
            most[0] = 0
            lib = library.Library()
            movies = os.path.join(self.dir, where)
            with mock.patch.object(places, "roots", side_effect=lambda key: [(key, movies)] if key == "movies" else []), \
                    mock.patch.object(library.music, "scan", return_value={"tracks": [], "albums": [], "artists": [], "videos": []}), \
                    mock.patch.object(media, "probe", side_effect=probe), mock.patch.object(media, "tool", return_value="ffmpeg"), \
                    mock.patch.object(machine, "heavy_ok", return_value=True), mock.patch.object(hardware, "workers", return_value=workers):
                self.assertTrue(lib.scan("tests"))
            return lib, most[0]
        one, n1 = read(1, "Movies")
        three, n3 = read(3, "Movies again")
        self.assertEqual((n1, n3), (1, 3))
        ids = sorted(m["id"] for m in one.movies)
        self.assertEqual(sorted(m["id"] for m in three.movies), ids)
        self.assertEqual(len(ids), 5)
        self.assertIn("m:heat:1995", ids)
        self.assertEqual(len([i for i in ids if i.startswith("m:heat:1995")]), 2)    # (the second Heat: an id of its own)
        for m in three.movies:                                            # (their own covers: not Sofa's pictures, kept)
            self.assertTrue(m["poster"].split("?")[0].endswith("/poster.jpg"), m)
            self.assertFalse(m["poster_still"])
        self.assertEqual([m["title"] for m in three.movies], [m["title"] for m in one.movies])

    def test_a_folder_is_read_once_and_again_after_sofa_writes_in_it(self):
        lib = library.Library()
        lib._ls, lib._ls_owner = {}, threading.get_ident()
        folder = os.path.join(self.show, "Season 1")
        with mock.patch.object(os, "scandir", wraps=os.scandir) as scans:
            first = lib._files(folder)
            lib._files(folder)
            self.assertEqual(scans.call_count, 1)
            with open(os.path.join(folder, "poster.jpg"), "wb") as f:
                f.write(b"x")
            self.assertIsNone(lib.find_art(folder, "poster"))              # (as it was read)
            lib._wrote(os.path.join(folder, "poster.jpg"))
            self.assertEqual(lib.find_art(folder, "poster"), os.path.join(folder, "poster.jpg"))
            self.assertEqual(scans.call_count, 2)
        self.assertNotIn("poster.jpg", first)
        other = []
        t = threading.Thread(target=lambda: other.append(lib._files(folder)))   # another thread: the folder itself
        t.start()
        t.join()
        self.assertEqual(other, [None])


class LessMemory(unittest.TestCase):
    def test_channels_share_what_they_have_in_common(self):
        text = "#EXTM3U\n" + "".join('#EXTINF:-1 tvg-id="c%d" group-title="News",Channel %d\nhttps://example.com/%d.m3u8\n' % (i, i, i)
                                     for i in range(3))
        a, b, c = live.parse_m3u(text, "My " + "list")
        self.assertIs(a["group"], b["group"])
        self.assertIs(a["playlist"], c["playlist"])
        self.assertIs(a["headers"], b["headers"])                         # (none of its own: one empty dict for all)
        self.assertEqual(a["headers"], {})
        ua = live.parse_m3u('#EXTINF:-1,X\n#EXTVLCOPT:http-user-agent=Box/1\nhttps://example.com/x.m3u8\n', "L")[0]
        self.assertEqual(ua["headers"], {"ua": "Box/1"})
        self.assertEqual(live.NO_HEADERS, {})

    def test_videos_with_nothing_next_to_them_arent_kept(self):
        d = tempfile.mkdtemp(dir=ROOT)
        self.addCleanup(shutil.rmtree, d, True)
        bare, told = os.path.join(d, "Bare.mp4"), os.path.join(d, "Told.mp4")
        for p in (bare, told):
            open(p, "wb").close()
        with open(os.path.join(d, "Told.nfo"), "w") as f:
            f.write("<movie><title>Told</title><plot>Something.</plot></movie>")
        self.assertEqual(sidecars.read(bare), {})
        self.assertNotIn(bare, sidecars._cache)
        self.assertEqual(sidecars.read(told).get("title"), "Told")
        self.assertIn(told, sidecars._cache)
        with mock.patch.object(sidecars, "MAX_KEPT", 1):
            sidecars._cache["/older.mp4"] = ((), {})
            sidecars._cache.pop(told)
            sidecars.read(told)
            self.assertEqual(list(sidecars._cache), [told])               # (the one read longest ago went)

    def test_one_conversion_at_a_time_on_a_small_computer(self):
        with mock.patch.object(hardware, "describe", return_value={"memory": 905 * 2**20, "cores": 4}):
            self.assertEqual(media.max_transcodes(), 1)
        with mock.patch.object(hardware, "describe", return_value={"memory": 16 * 2**30, "cores": 8}):
            self.assertEqual(media.max_transcodes(), 2)                   # (the setting, as before)
        with mock.patch.object(hardware, "describe", return_value={"memory": 16 * 2**30, "cores": 2}):
            self.assertEqual(media.max_transcodes(), 1)

    def test_freed_memory_goes_back(self):
        self.assertIn(hardware.give_back(), (True, False))                # (False on a Mac: no malloc_trim)
        self.assertIn(hardware.give_back(collect=True), (True, False))
        self.assertGreater(hardware.deep_size({"a": ["x" * 1000, 2]}), 1000)


class TheReport(unittest.TestCase):
    def test_it_says_what_the_computer_is_and_where_the_memory_is(self):
        text = report.build("leo")
        for want in ("This computer: ", " cores", "video: ", "Background work: ", "ffmpeg with ", "conversions for watching at once: ",
                     "Memory: ", "Sofa itself ", "In Sofa's memory: ", "the library ", "Live TV's channels "):
            self.assertIn(want, text)


if __name__ == "__main__":
    unittest.main()
