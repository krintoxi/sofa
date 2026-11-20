"""Save this disc (sofa/disc.py): a music CD, a video DVD and a data disc into the library, and what isn't saved.

The discs are made here (tests/disc_images.py): a music CD as a .cue and .bin, a video DVD as an ISO 9660 image
with its tables written by the test and its video from ffmpeg, and that DVD with its packs marked scrambled, as a
copy-protected one's are. No disc drive is used: what asks a real drive (Linux's and Windows's calls, a Mac's CD
folder) is checked as far as it can be without one, and the rest is for a real disc."""
import hashlib
import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import unittest
from unittest import mock

from tests import disc_images
from sofa import cdaudio, config, disc, dvd, fileops, iso9660, media

FFMPEG = media.tool("ffmpeg") and media.tool("ffprobe")


def probe(path, *show):
    out = subprocess.run([media.tool("ffprobe"), "-v", "error", "-show_streams", "-show_chapters", "-show_format", "-of", "json", path],
                         capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout)


class Discs(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="sofa-disc-")
        self.addCleanup(shutil.rmtree, self.work, True)
        self.addCleanup(self.forget)
        self.forget()
        before = {key: config.get(key) for key in ("movies", "shows", "music", "inbox")}      # a library of this test's own
        self.addCleanup(config.update, before)
        config.update({key: os.path.join(self.work, "library", key.capitalize()) for key in before})
        for key in before:
            os.makedirs(config.path(key), exist_ok=True)

    def forget(self):
        with disc._lock:
            disc._known.clear()
            del disc._jobs[:]

    def put_in(self, *paths):
        """These images are in drives now."""
        patch = mock.patch.dict(os.environ, {"SOFA_DISCS": os.pathsep.join(paths)})
        patch.start()
        self.addCleanup(patch.stop)
        p2 = mock.patch.object(disc, "drives", disc._made_drives)       # (this computer's own drive isn't part of the test)
        p2.start()
        self.addCleanup(p2.stop)
        return disc.status(wait=60)["drives"]

    def save(self, drive, ask, wait=120):
        job = disc.save(drive, ask, "the test")
        end = time.time() + wait
        while time.time() < end:
            now = next(j for j in disc.status()["jobs"] if j["id"] == job["id"])
            if now["state"] != "working":
                return now
            time.sleep(0.05)
        self.fail("the save didn't finish")

    def tree(self, key):
        out = []
        for root, dirs, files in os.walk(config.path(key)):
            out += [os.path.relpath(os.path.join(root, f), config.path(key)).replace(os.sep, "/") for f in files]
            out += [os.path.relpath(os.path.join(root, d), config.path(key)).replace(os.sep, "/") + "/" for d in dirs if d.startswith(".")]
        return sorted(out)


class TheDiscsFiles(unittest.TestCase):
    """Reading a disc's files ourselves (sofa/iso9660.py), and from a folder a computer mounted it at."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="sofa-disc-")
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_an_image_and_a_folder_answer_alike(self):
        files = {"VIDEO_TS/VIDEO_TS.IFO": b"a" * 5000, "Home Movies/Beach.mp4": b"b" * 3000, "Notes.txt": b"hello"}
        image = iso9660.Image(disc_images.iso(os.path.join(self.work, "d.iso"), files, label="SUMMER"))
        self.addCleanup(image.close)
        for name, data in files.items():
            path = os.path.join(self.work, "mounted", name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        folder = iso9660.Folder(os.path.join(self.work, "mounted"), "SUMMER")
        for source in (image, folder):
            self.assertEqual(source.label, "SUMMER")
            self.assertEqual(sorted(iso9660.walk(source)), [("Home Movies/Beach.mp4", 3000), ("Notes.txt", 5), ("VIDEO_TS/VIDEO_TS.IFO", 5000)])
            self.assertEqual(source.size("video_ts/video_ts.ifo"), 5000)             # whatever the capitals
            with source.open("Home Movies/Beach.mp4") as f:
                f.seek(2990)
                self.assertEqual(f.read(100), b"b" * 10)
            self.assertIsNone(source.size("VIDEO_TS/NOPE.IFO"))

    def test_not_a_disc(self):
        path = os.path.join(self.work, "x.iso")
        with open(path, "wb") as f:
            f.write(b"\0" * 80000)
        with self.assertRaises(ValueError):
            iso9660.Image(path)


class Packs(unittest.TestCase):
    """A DVD's packs, read by hand: the times in them, and the bits that say a pack is scrambled."""

    def test_a_time_is_read_and_written_back(self):
        pack = bytearray(disc_images.subtitle_pack(1, 123456789))
        (sid, sub, at, pts), = [p for p in dvd.packets(pack) if p[0] == 0xBD]
        self.assertEqual((sid, sub, dvd._stamp(pack, pts)), (0xBD, 0x21, 123456789))
        for value in (0, 1, 90000, (1 << 33) - 1, 0x155555555):
            dvd._set_stamp(pack, pts, value)
            self.assertEqual(dvd._stamp(pack, pts), value)
            self.assertEqual(pack[pts] >> 4, 2)                                    # (the marker bits are as they were)
            self.assertEqual((pack[pts] & 1, pack[pts + 2] & 1, pack[pts + 4] & 1), (1, 1, 1))

    def test_a_scrambled_pack_is_noticed(self):
        pack = bytearray(disc_images.subtitle_pack(0, 9000))
        self.assertFalse(dvd.scrambled(pack))
        at = [p for p in dvd.packets(pack) if p[0] == 0xBD][0][2]
        pack[at + 6] |= 0x10
        self.assertTrue(dvd.scrambled(pack))
        self.assertEqual(dvd.packets(b"\0" * 2048), [])                              # (not a pack at all)

    def test_colours(self):
        self.assertEqual(dvd.rgb([(16, 128, 128), (235, 128, 128)]), ["000000", "ffffff"])


@unittest.skipUnless(FFMPEG, "ffmpeg makes the DVD's video and packs what's saved")
class VideoDvd(Discs):
    def test_what_is_on_it(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((3,), (2, 2)))
        (d,) = self.put_in(image)
        self.assertEqual((d["kind"], d["label"], d["state"]), ("dvd", "HOME_MOVIES", "disc"))
        self.assertFalse(d["disc"]["protected"])
        one, two = d["disc"]["titles"]
        self.assertEqual((one["n"], one["seconds"], one["chapters"]), (1, 3.0, [0.0]))
        self.assertEqual((two["n"], two["seconds"], two["chapters"]), (2, 4.0, [0.0, 2.0]))
        self.assertEqual([(a["lang"], a["kind"], a["channels"], a["name"]) for a in one["audio"]],
                         [("en", "ac3", 2, "English Dolby Digital stereo"), ("es", "ac3", 2, "Spanish Dolby Digital stereo")])
        self.assertEqual([(s["lang"], s["name"]) for s in one["subs"]], [("en", "English")])
        self.assertEqual((one["video"]["width"], one["video"]["height"], one["video"]["pal"]), (720, 480, False))
        self.assertFalse(any(k.startswith("_") for k in one))                        # (nothing private goes to a page)

    def test_a_movie_with_every_track_and_its_chapters(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((3,), (2, 2)))
        (d,) = self.put_in(image)
        job = self.save(d["id"], {"to": "movies", "name": "Summer at the Lake", "year": "2004", "titles": [2]})
        self.assertEqual((job["state"], job["error"], job["notes"]), ("done", None, []))
        self.assertEqual(self.tree("movies"), ["Summer at the Lake (2004)/Summer at the Lake (2004).mkv"])     # and nothing left behind
        got = probe(os.path.join(config.path("movies"), "Summer at the Lake (2004)", "Summer at the Lake (2004).mkv"))
        kinds = [(s["codec_type"], s["codec_name"], (s.get("tags") or {}).get("language")) for s in got["streams"]]
        self.assertEqual(kinds, [("video", "mpeg2video", None), ("audio", "ac3", "eng"), ("audio", "ac3", "spa"), ("subtitle", "dvd_subtitle", "eng")])
        # two clips, each with its own clock on the disc: one clock in the file, as long as both
        video = got["streams"][0]
        start = float(video["start_time"])
        self.assertAlmostEqual(float(got["format"]["duration"]), 4.0, delta=0.25)
        frames = subprocess.run([media.tool("ffprobe"), "-v", "error", "-select_streams", "v", "-show_entries", "packet=pts_time", "-of", "csv=p=0",
                                 os.path.join(config.path("movies"), "Summer at the Lake (2004)", "Summer at the Lake (2004).mkv")],
                                capture_output=True, text=True, timeout=60).stdout.split()
        times = sorted(float(x.strip(",")) for x in frames)
        self.assertGreater(len(times), 110)                                          # (4 s at 29.97 a second)
        self.assertLess(max(b - a for a, b in zip(times, times[1:])), 0.1)             # no gap, no step back, where the clips meet
        # the chapters where the disc has them, on the file's own clock
        self.assertEqual(len(got["chapters"]), 2)
        self.assertAlmostEqual(float(got["chapters"][1]["start_time"]) - start, 2.0, delta=0.05)
        # the subtitles' colours come from the disc's table (white is its colour 1), and their times with the picture
        text = subprocess.run([media.tool("ffprobe"), "-v", "error", "-select_streams", "s", "-show_entries", "packet=pts_time", "-of", "csv=p=0",
                               os.path.join(config.path("movies"), "Summer at the Lake (2004)", "Summer at the Lake (2004).mkv")],
                              capture_output=True, text=True, timeout=60).stdout.split()
        subs = [round(float(x.strip(",")), 2) for x in text]
        self.assertEqual(subs, [0.07, 1.07, 2.07, 3.07])        # each as long after the picture starts as on the disc; the second clip's 2 s on
        with open(os.path.join(config.path("movies"), "Summer at the Lake (2004)", "Summer at the Lake (2004).mkv"), "rb") as f:
            self.assertIn(b"palette: 000000, ffffff", f.read(20000))
        # the picture and sound are the disc's own, not converted: the same packets as in the disc's stream
        title = dvd.titles(dvd.open_source(image))["titles"][1]
        vob = os.path.join(self.work, "t.vob")
        with open(vob, "wb") as f:
            for chunk in dvd.read_title(dvd.open_source(image), title):
                f.write(chunk)
        digest = lambda p, s: subprocess.run([media.tool("ffmpeg"), "-v", "error", "-i", p, "-map", s, "-c", "copy", "-f", "md5", "-"],
                                             capture_output=True, text=True, timeout=60).stdout.strip()
        mkv = os.path.join(config.path("movies"), "Summer at the Lake (2004)", "Summer at the Lake (2004).mkv")
        self.assertEqual(digest(vob, "0:v"), digest(mkv, "0:v"))
        self.assertEqual(digest(vob, "0:#0x80"), digest(mkv, "0:a:0"))

    def test_episodes_of_a_show(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2,), (2,), (2,)), subtitles=False)
        (d,) = self.put_in(image)
        job = self.save(d["id"], {"to": "shows", "name": "The Garden Tapes", "season": 2, "episode": 4, "titles": [1, 3]})
        self.assertEqual((job["state"], job["items"], job["to"]), ("done", 2, "Shows"))
        self.assertEqual(self.tree("shows"), ["The Garden Tapes/Season 2/The Garden Tapes S02E04.mkv", "The Garden Tapes/Season 2/The Garden Tapes S02E05.mkv"])
        with self.assertRaisesRegex(ValueError, "already has season 2 episode 5"):     # never over what's there
            disc.save(d["id"], {"to": "shows", "name": "the garden tapes", "season": 2, "episode": 5, "titles": [2]})
        job = self.save(d["id"], {"to": "shows", "name": "the garden tapes", "season": 2, "episode": 6, "titles": [2]})
        self.assertIn("The Garden Tapes/Season 2/the garden tapes S02E06.mkv", self.tree("shows"))   # (into the show's own folder)

    def test_a_recorders_sound_pcm_and_mpeg(self):
        """Home DVD recorders and cameras often write PCM or MPEG sound, not Dolby Digital. MPEG goes in as it is; a
        DVD's PCM can't sit in an MKV in its own packing, so the same samples are repacked, none changed."""
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((3,),), subtitles=False, sounds=(("en", "lpcm"), ("de", "mp2"), (None, "ac3")), pal=True)
        (d,) = self.put_in(image)
        title = d["disc"]["titles"][0]
        self.assertEqual([(a["lang"], a["kind"], a["id"], a["name"]) for a in title["audio"]],
                         [("en", "lpcm", 0xA0, "English PCM stereo"), ("de", "mp2", 0xC0, "German MPEG stereo"), (None, "ac3", 0x80, "Dolby Digital stereo (commentary)")])
        self.assertEqual((title["video"]["height"], title["video"]["pal"]), (576, True))
        job = self.save(d["id"], {"to": "movies", "name": "From the Recorder", "titles": [1]})
        self.assertEqual((job["state"], job["error"], job["notes"]), ("done", None, []))
        mkv = os.path.join(config.path("movies"), "From the Recorder", "From the Recorder.mkv")
        got = probe(mkv)
        self.assertEqual([(s["codec_name"], (s.get("tags") or {}).get("language")) for s in got["streams"]],
                         [("mpeg2video", None), ("pcm_s16le", "eng"), ("mp2", "ger"), ("ac3", None)])
        vob = os.path.join(self.work, "t.vob")
        with open(vob, "wb") as f:
            for chunk in dvd.read_title(dvd.open_source(image), dvd.titles(dvd.open_source(image))["titles"][0]):
                f.write(chunk)
        samples = lambda p, s: hashlib.sha256(subprocess.run([media.tool("ffmpeg"), "-v", "error", "-i", p, "-map", s, "-f", "s16le", "-"],
                                                             capture_output=True, timeout=60).stdout).hexdigest()
        self.assertEqual(samples(vob, "0:#0xa0"), samples(mkv, "0:a:0"))               # the PCM: every sample the same
        packets = lambda p, s: subprocess.run([media.tool("ffmpeg"), "-v", "error", "-i", p, "-map", s, "-c", "copy", "-f", "md5", "-"],
                                              capture_output=True, text=True, timeout=60).stdout.strip()
        self.assertEqual(packets(vob, "0:#0x1c0"), packets(mkv, "0:a:1"))              # the MPEG sound: as it is
        self.assertEqual(packets(vob, "0:v"), packets(mkv, "0:v"))

    def test_the_times_in_the_navigation_packs_are_used_when_a_disc_has_them(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2, 2),), navigation=True, subtitles=False)
        title = dvd.titles(dvd.open_source(image))["titles"][0]
        vob = os.path.join(self.work, "t.vob")
        with open(vob, "wb") as f:
            for chunk in dvd.read_title(dvd.open_source(image), title):
                f.write(chunk)
        frames = subprocess.run([media.tool("ffprobe"), "-v", "error", "-select_streams", "v", "-show_entries", "packet=pts_time", "-of", "csv=p=0", vob],
                                capture_output=True, text=True, timeout=60).stdout.split()
        times = sorted(float(x.strip(",")) for x in frames if x.strip(",") != "N/A")
        self.assertAlmostEqual(times[-1] - times[0], 4.0, delta=0.2)
        self.assertLess(max(b - a for a, b in zip(times, times[1:])), 0.1)

    def test_a_folder_laid_out_like_the_disc(self):
        """A Mac and Windows mount a DVD by themselves: Sofa reads the folder it's at."""
        folder = os.path.join(self.work, "MOUNTED")
        disc_images.dvd(folder, self.work, clips=((2,),), folder=True)
        (d,) = self.put_in(folder)
        self.assertEqual((d["kind"], len(d["disc"]["titles"])), ("dvd", 1))
        job = self.save(d["id"], {"to": "movies", "name": "From a Folder", "titles": [1]})
        self.assertEqual(job["state"], "done")
        self.assertEqual(self.tree("movies"), ["From a Folder/From a Folder.mkv"])

    def test_more_than_one_camera_angle_is_said_and_not_saved(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2, 2),), angles=True, subtitles=False)
        (d,) = self.put_in(image)
        self.assertIn("more than one camera angle", d["disc"]["titles"][0]["cant"])
        with self.assertRaisesRegex(ValueError, "camera angle"):
            disc.save(d["id"], {"to": "movies", "name": "Angles", "titles": [1]})
        self.assertEqual(self.tree("movies"), [])

    def test_what_has_to_be_said_first(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2,), (2,)), subtitles=False)
        (d,) = self.put_in(image)
        for ask, why in (({"to": "movies", "name": "", "titles": [1]}, "Give it a name"),
                         ({"to": "movies", "name": "Two", "titles": [1, 2]}, "A movie is one title"),
                         ({"to": "movies", "name": "X", "year": "20x4", "titles": [1]}, "year looks like"),
                         ({"to": "movies", "name": "X", "titles": []}, "Pick what to save"),
                         ({"to": "music", "name": "X", "titles": [1]}, "Movies or Shows"),
                         ({"to": "shows", "name": "X", "season": "one", "titles": [1]}, "are numbers")):
            with self.assertRaisesRegex(ValueError, why):
                disc.save(d["id"], ask)
        with self.assertRaisesRegex(ValueError, "no disc in that drive"):
            disc.save("nowhere", {"to": "movies", "name": "X", "titles": [1]})
        with mock.patch.object(shutil, "disk_usage", return_value=mock.Mock(free=10 << 20)):
            with self.assertRaisesRegex(ValueError, "isn't room"):
                disc.save(d["id"], {"to": "movies", "name": "X", "titles": [1]})
        self.assertEqual(self.tree("movies"), [])

    def test_never_over_a_file_thats_there(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2,),), subtitles=False)
        (d,) = self.put_in(image)
        there = os.path.join(config.path("movies"), "Kept", "Kept.mkv")
        os.makedirs(os.path.dirname(there))
        with open(there, "wb") as f:
            f.write(b"mine")
        with self.assertRaisesRegex(ValueError, "already there"):
            disc.save(d["id"], {"to": "movies", "name": "Kept", "titles": [1]})
        # ...and one that turns up while the disc is being read isn't written over either
        real = fileops.place

        def late(src, dest):
            with open(dest, "wb") as f:
                f.write(b"someone else's")
            return real(src, dest)
        with mock.patch.object(fileops, "place", late):
            job = self.save(d["id"], {"to": "movies", "name": "Raced", "titles": [1]})
        self.assertEqual(job["state"], "failed")
        self.assertIn("doesn't write over a file", job["error"])
        with open(os.path.join(config.path("movies"), "Raced", "Raced.mkv"), "rb") as f:
            self.assertEqual(f.read(), b"someone else's")
        with open(there, "rb") as f:
            self.assertEqual(f.read(), b"mine")
        self.assertEqual(self.tree("movies"), ["Kept/Kept.mkv", "Raced/Raced.mkv"])

    def test_the_disc_pulled_out_in_the_middle(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2,), (2,)), subtitles=False)
        (d,) = self.put_in(image)
        real, calls = dvd._Vobs.read, []

        def pulled(vobs, sector, count):
            calls.append(sector)
            if len(calls) > 1:
                os.environ["SOFA_DISCS"] = ""                                        # the drive is empty now
                raise OSError(5, "Input/output error")
            return real(vobs, sector, count)
        with mock.patch.object(dvd, "CHUNK", 64), mock.patch.object(dvd._Vobs, "read", pulled):
            job = self.save(d["id"], {"to": "shows", "name": "Pulled", "season": 1, "episode": 1, "titles": [1, 2]})
        self.assertEqual((job["state"], job["error"]), ("failed", disc.GONE))
        self.assertEqual(self.tree("shows"), [])                                     # nothing half done, no empty folders
        self.assertFalse(os.path.exists(os.path.join(config.path("shows"), "Pulled")))
        self.assertEqual(disc.status()["drives"], [])

    def test_stopping_it(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2,), (2,)), subtitles=False)
        (d,) = self.put_in(image)
        real = dvd._Vobs.read

        def slow(vobs, sector, count):
            time.sleep(0.2)
            return real(vobs, sector, count)
        with mock.patch.object(dvd, "CHUNK", 32), mock.patch.object(dvd._Vobs, "read", slow):
            job = disc.save(d["id"], {"to": "movies", "name": "Stopped", "titles": [1]})
            with self.assertRaisesRegex(ValueError, "being saved already"):
                disc.save(d["id"], {"to": "movies", "name": "Second", "titles": [2]})
            self.assertTrue(disc.cancel(job["id"]))
            end = time.time() + 20
            while time.time() < end and disc.status()["jobs"][-1]["state"] == "working":
                time.sleep(0.05)
        self.assertEqual(disc.status()["jobs"][-1]["state"], "cancelled")
        self.assertEqual(self.tree("movies"), [])


@unittest.skipUnless(FFMPEG, "ffmpeg makes the DVD's video")
class CopyProtected(Discs):
    """A disc whose packs say they're scrambled. (Only the flag is set here: there's no CSS in the test to undo, and
    nothing in Sofa that would.)"""

    def test_it_says_so_and_stops(self):
        image = os.path.join(self.work, "film.iso")
        disc_images.dvd(image, self.work, clips=((3,),), protected=True)
        (d,) = self.put_in(image)
        self.assertTrue(d["disc"]["protected"])
        self.assertEqual(d["disc"]["problem"], disc.PROTECTED % "DVD")
        self.assertIn("copy-protected", d["disc"]["problem"])
        with mock.patch.object(subprocess, "Popen") as popen, mock.patch.object(subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "copy-protected"):
                disc.save(d["id"], {"to": "movies", "name": "A Film", "year": "1999", "titles": [1]})
            self.assertFalse(popen.called or run.called)                             # ffmpeg is never started
        self.assertEqual(self.tree("movies"), [])

    def test_a_scrambled_pack_met_while_saving_ends_it_with_nothing_kept(self):
        """The look beforehand reads a few places; a disc scrambled only elsewhere is caught as it's read."""
        image = os.path.join(self.work, "film.iso")
        disc_images.dvd(image, self.work, clips=((3,),), protected=True)
        with mock.patch.object(dvd, "sample", return_value=None):
            (d,) = self.put_in(image)
        self.assertFalse(d["disc"]["protected"])
        packed = []
        with mock.patch.object(disc, "_ffmpeg", lambda *a, **k: packed.append(a)):
            job = self.save(d["id"], {"to": "movies", "name": "A Film", "year": "1999", "titles": [1]})
        self.assertEqual((job["state"], job["error"], job["files"]), ("failed", disc.PROTECTED % "DVD", []))
        self.assertEqual(packed, [])
        self.assertEqual(self.tree("movies"), [])
        self.assertFalse(os.path.exists(os.path.join(config.path("movies"), "A Film (1999)")))

    def test_the_reader_itself_refuses(self):
        image = os.path.join(self.work, "film.iso")
        disc_images.dvd(image, self.work, clips=((2,),), protected=True, subtitles=False)
        source = dvd.open_source(image)
        title = dvd.titles(source)["titles"][0]
        self.assertEqual(dvd.sample(source, title), "protected")
        with self.assertRaises(dvd.Protected):
            for _ in dvd.read_title(source, title):
                pass

    def test_a_drive_that_wont_hand_the_video_over(self):
        """A drive refuses to read a protected disc's video until it's been unlocked, which Sofa never does."""
        image = os.path.join(self.work, "film.iso")
        disc_images.dvd(image, self.work, clips=((2,),), subtitles=False)
        with mock.patch.object(dvd._Vobs, "read", side_effect=OSError(5, "Input/output error")):
            (d,) = self.put_in(image)
        self.assertTrue(d["disc"]["protected"])
        self.assertEqual(d["disc"]["problem"], disc.WONT_READ)

    def test_the_discs_own_word(self):
        image = os.path.join(self.work, "film.iso")
        disc_images.dvd(image, self.work, clips=((2,),), subtitles=False)
        with mock.patch.object(disc, "_copyright", return_value=1):                    # the drive says: CSS
            (d,) = self.put_in(image)
        self.assertEqual((d["disc"]["protected"], d["disc"]["problem"]), (True, disc.PROTECTED % "DVD"))

    def test_a_blu_ray(self):
        image = disc_images.iso(os.path.join(self.work, "bd.iso"), {"BDMV/index.bdmv": b"INDX0200", "AACS/Unit_Key_RO.inf": b"x"}, label="A_FILM")
        (d,) = self.put_in(image)
        self.assertEqual((d["kind"], d["disc"]["protected"], d["disc"]["problem"]), ("bluray", True, disc.BLURAY))
        with self.assertRaisesRegex(ValueError, "Blu-ray"):
            disc.save(d["id"], {"to": "movies", "name": "A Film", "titles": [1]})

    def test_nothing_in_sofa_unlocks_a_disc(self):
        """No decryption library is named, loaded or fetched anywhere in Sofa's code or the box's, and the drive is
        never sent the handshake that unlocks a protected disc (DVD_AUTH, or SCSI's SEND KEY and REPORT KEY)."""
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for folder in ("sofa", "client"):
            for root, _, files in os.walk(os.path.join(here, folder)):
                for name in files:
                    if not name.endswith((".py", ".js")) or "vendor" in root:
                        continue
                    with open(os.path.join(root, name), encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    low = text.lower()
                    for word in ("dvdcss", "libaacs", "makemkv", "decss", "keydb", "dvd_auth", "0x5392", "libbdplus"):
                        if name in ("dvd.py",) and word == "dvdcss":
                            continue                                                 # (where it says why Sofa's reader isn't libdvdread)
                        self.assertNotIn(word, low, "%s names %s" % (name, word))
        with open(os.path.join(here, "sofa", "cdaudio.py"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("0xA3", text.replace("0xAA", ""))                             # SEND KEY
        self.assertNotIn("0xA4", text)                                                 # REPORT KEY
        self.assertEqual(text.count("bytes([0x43,"), 1)                                # the one SCSI command sent: READ TOC


@unittest.skipUnless(FFMPEG, "ffmpeg packs the tracks as FLAC")
class MusicCd(Discs):
    def test_what_is_on_it(self):
        cue, sounds = disc_images.audio_cd(self.work)
        (d,) = self.put_in(cue)
        self.assertEqual((d["kind"], d["label"]), ("cd", "Made For Testing"))
        self.assertEqual([(t["n"], t["seconds"], t["title"]) for t in d["disc"]["tracks"]],
                         [(1, 2.0, "First Light"), (2, 3.0, "Second Wind"), (3, 1.5, "Third Rail")])
        self.assertEqual((d["disc"]["artist"], d["disc"]["album"], d["disc"]["named"]), ("The Made Ups", "Made For Testing", True))

    def test_every_track_bit_for_bit_named_and_tagged(self):
        cue, sounds = disc_images.audio_cd(self.work)
        (d,) = self.put_in(cue)
        job = self.save(d["id"], {"artist": "The Made Ups", "album": "Made For Testing", "year": "2001",
                                  "tracks": {"1": "First Light", "2": "Second Wind", "3": "Third Rail"}})
        self.assertEqual((job["state"], job["error"], job["to"]), ("done", None, "Music"))
        folder = os.path.join(config.path("music"), "The Made Ups", "Made For Testing")
        self.assertEqual(sorted(os.listdir(folder)), ["01 First Light.flac", "02 Second Wind.flac", "03 Third Rail.flac"])
        for n, name in enumerate(sorted(os.listdir(folder))):
            path = os.path.join(folder, name)
            pcm = subprocess.run([media.tool("ffmpeg"), "-v", "error", "-i", path, "-f", "s16le", "-"], capture_output=True, timeout=60).stdout
            self.assertEqual(hashlib.sha256(pcm).hexdigest(), hashlib.sha256(sounds[n]).hexdigest())    # every bit of the disc's sound
            self.assertEqual(disc._flac_md5(path), hashlib.md5(sounds[n]).digest())
            got = probe(path)
            self.assertEqual((got["streams"][0]["codec_name"], got["streams"][0]["sample_rate"], got["streams"][0]["channels"]), ("flac", "44100", 2))
            tags = {k.lower(): v for k, v in got["format"]["tags"].items()}
            self.assertEqual((tags["artist"], tags["album"], tags["track"], tags["date"]), ("The Made Ups", "Made For Testing", "%d/3" % (n + 1), "2001"))
        self.assertEqual(tags["title"], "Third Rail")
        with self.assertRaisesRegex(ValueError, "already there"):                    # the same disc again: nothing written over
            disc.save(d["id"], {"artist": "the made ups", "album": "Made For Testing", "tracks": {"2": "Second Wind"}})

    def test_some_tracks_and_a_disc_with_no_names(self):
        cue, sounds = disc_images.audio_cd(self.work, text=False)
        (d,) = self.put_in(cue)
        self.assertEqual((d["disc"]["named"], d["disc"]["tracks"][0]["title"]), (False, ""))
        with self.assertRaisesRegex(ValueError, "who it's by"):
            disc.save(d["id"], {"artist": "", "album": "", "tracks": {"1": ""}})
        job = self.save(d["id"], {"artist": "Somebody", "album": "A Tape: Side/One?", "tracks": {"3": ""}})
        self.assertEqual(job["state"], "done")
        self.assertEqual(self.tree("music"), ["Somebody/A Tape - Side-One/03 Track 3.flac"])

    def test_a_file_that_didnt_come_out_the_same_isnt_kept(self):
        cue, sounds = disc_images.audio_cd(self.work)
        (d,) = self.put_in(cue)
        with mock.patch.object(disc, "_flac_md5", return_value=b"\0" * 16):
            job = self.save(d["id"], {"artist": "X", "album": "Y", "tracks": {"1": "One"}})
        self.assertEqual(job["state"], "failed")
        self.assertIn("didn't come out the same", job["error"])
        self.assertEqual(self.tree("music"), [])

    def test_looking_the_names_up(self):
        cue, sounds = disc_images.audio_cd(self.work, text=False)
        (d,) = self.put_in(cue)
        asked = []

        def fetch(url):
            asked.append(url)
            return {"releases": [{"title": "Made For Testing", "date": "2001-05-01", "artist-credit": [{"name": "The Made Ups"}],
                                  "media": [{"tracks": [{"position": 1, "title": "First Light"}, {"position": 2, "title": "Second Wind"},
                                                        {"position": 3, "title": "Third Rail"}]}]}]}
        with self.assertRaisesRegex(ValueError, "switched off"):                     # (the tests run offline)
            disc.names(d["id"], fetch)
        self.assertEqual(asked, [])
        config.update({"offline": False, "disc_lookup": True})
        self.addCleanup(config.update, {"offline": True})
        got = disc.names(d["id"], fetch)
        self.assertEqual((got["artist"], got["album"], got["year"], got["titles"]["2"]), ("The Made Ups", "Made For Testing", "2001", "Second Wind"))
        # what's sent is where the tracks start and nothing else: MusicBrainz's own disc id and table of contents
        self.assertTrue(asked[0].startswith("https://musicbrainz.org/ws/2/discid/"))
        self.assertIn("?toc=1+3+637+150+300+525&", asked[0])
        config.update({"disc_lookup": False})
        self.addCleanup(config.update, {"disc_lookup": True})
        with self.assertRaisesRegex(ValueError, "switched off"):
            disc.names(d["id"], fetch)
        self.assertEqual(len(asked), 1)

    def test_the_disc_id_is_musicbrainzs(self):
        """The worked example in MusicBrainz's own description of the disc id (a six-track CD)."""
        starts = [150, 15363, 32314, 46592, 63414, 80489]
        code, toc = cdaudio.disc_id(([s - 150 for s in starts], 95462 - 150))
        self.assertEqual(code, "49HHV7Eb8UKF3aQiNmu1GR8vKTY-")
        self.assertEqual(toc, "1 6 95462 150 15363 32314 46592 63414 80489")


class MusicCdOnEachComputer(unittest.TestCase):
    """What asks a real drive, as far as it goes without one."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="sofa-disc-")
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_a_macs_cd_folder(self):
        """A Mac shows a music CD as a folder of .aiff files (little-endian inside, "sowt") and a .TOC.plist."""
        sounds = [disc_images.tone(1, 300), disc_images.tone(2, 500)]
        for n, pcm in enumerate(sounds, 1):
            comm = struct.pack(">hIh", 2, len(pcm) // 4, 16) + b"\x40\x0e\xac\x44\0\0\0\0\0\0" + b"sowt" + b"\0\0"
            body = b"AIFC" + b"FVER" + struct.pack(">II", 4, 0xA2805140) + b"COMM" + struct.pack(">I", len(comm)) + comm + \
                b"SSND" + struct.pack(">III", len(pcm) + 8, 0, 0) + pcm
            with open(os.path.join(self.work, "%d Audio Track.aiff" % n), "wb") as f:
                f.write(b"FORM" + struct.pack(">I", len(body)) + body)
        with open(os.path.join(self.work, ".TOC.plist"), "wb") as f:
            plistlib.dump({"Sessions": [{"First Track": 1, "Last Track": 2, "Leadout Block": 375, "Track Array": [
                {"Point": 1, "Start Block": 150, "Data": False}, {"Point": 2, "Start Block": 225, "Data": False}]}]}, f)
        cd = cdaudio.MacVolume(self.work)
        self.addCleanup(cd.close)
        self.assertEqual([(t["n"], t["frames"]) for t in cd.tracks], [(1, 75), (2, 150)])
        self.assertEqual(cd.read(0, 75), sounds[0])
        self.assertEqual(cd.read(75 + 10, 20), sounds[1][10 * 2352:30 * 2352])
        self.assertEqual(cd.addresses, ([0, 75], 225))

    def test_big_endian_aiff(self):
        pcm = disc_images.tone(1, 300)
        big = cdaudio._swap(pcm)
        comm = struct.pack(">hIh", 2, len(pcm) // 4, 16) + b"\x40\x0e\xac\x44\0\0\0\0\0\0"
        body = b"AIFF" + b"COMM" + struct.pack(">I", len(comm)) + comm + b"SSND" + struct.pack(">III", len(big) + 8, 0, 0) + big
        with open(os.path.join(self.work, "1 Track.aiff"), "wb") as f:
            f.write(b"FORM" + struct.pack(">I", len(body)) + body)
        cd = cdaudio.MacVolume(self.work)
        self.addCleanup(cd.close)
        self.assertEqual(cd.read(0, 75), pcm)

    def test_the_discs_own_text(self):
        """CD-Text as a drive hands it over: 18-byte packs, a name running from one pack into the next."""
        def packs(kind, texts):
            data = b"".join(t.encode("latin-1") + b"\0" for t in texts)
            out, track, n = b"", 0, 0
            for i in range(0, len(data), 12):
                piece = data[i:i + 12].ljust(12, b"\0")
                out += bytes([kind, track, n, 0]) + piece + b"\0\0"
                track += data[i:i + 12].count(b"\0")
                n += 1
            return out
        raw = b"\0\0\0\0" + packs(0x80, ["Made For Testing", "First Light", "Second Wind"]) + packs(0x81, ["The Made Ups", "\t", "A Guest"])
        raw = struct.pack(">H", len(raw) - 2) + raw[2:]
        self.assertEqual(cdaudio.cd_text(raw), {"album": "Made For Testing", "artist": "The Made Ups",
                                                "titles": {1: "First Light", 2: "Second Wind"}, "artists": {1: "The Made Ups", 2: "A Guest"}})
        self.assertEqual(cdaudio.cd_text(b""), {"titles": {}, "artists": {}})

    def test_the_drives_numbers_are_the_systems_own(self):
        """Linux's (linux/cdrom.h) and Windows's (ntddcdrm.h, ntddcdvd.h) request numbers and layouts."""
        self.assertEqual((cdaudio.CDROMREADTOCHDR, cdaudio.CDROMREADTOCENTRY, cdaudio.CDROMREADAUDIO), (0x5305, 0x5306, 0x530E))
        self.assertEqual((cdaudio.CDROM_DRIVE_STATUS, cdaudio.CDROM_DISC_STATUS, cdaudio.DVD_READ_STRUCT), (0x5326, 0x5327, 0x5390))
        self.assertEqual((cdaudio.IOCTL_CDROM_READ_TOC, cdaudio.IOCTL_CDROM_RAW_READ, cdaudio.IOCTL_CDROM_READ_TOC_EX, cdaudio.IOCTL_DVD_READ_STRUCTURE),
                         (0x24000, 0x2403E, 0x24054, 0x335140))
        self.assertEqual(struct.calcsize("BBBxixxxx"), 12)                             # struct cdrom_tocentry

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux's own calls")
    def test_a_linux_drive_asked_through_the_kernel(self):
        """The table of contents and the sound, with the kernel's answers stood in for (no drive on the test machine)."""
        import fcntl
        pcm = disc_images.tone(2, 440)
        toc = {1: (0, 0), 2: (75, 0), 3: (150, 4), 0xAA: (400, 0)}                     # (track 3 is data: left out)

        def ioctl(fd, request, arg=0, *more):
            if request == cdaudio.CDROMREADTOCHDR:
                arg[0], arg[1] = 1, 3
            elif request == cdaudio.CDROMREADTOCENTRY:
                self.assertEqual(arg[2], cdaudio.CDROM_LBA)
                lba, control = toc[arg[0]]
                arg[1] = control << 4 | 1
                struct.pack_into("i", arg, 4, lba)
            elif request == cdaudio.CDROMREADAUDIO:
                import ctypes
                ctypes.memmove(arg.buf, pcm[arg.lba * 2352:(arg.lba + arg.nframes) * 2352], arg.nframes * 2352)
            else:
                raise OSError(25, "not asked in this test")
            return 0
        with mock.patch.object(fcntl, "ioctl", ioctl), mock.patch.object(os, "open", return_value=99), mock.patch.object(os, "close"):
            cd = cdaudio.LinuxDrive("/dev/sr0")
            self.assertEqual([(t["n"], t["start"], t["frames"]) for t in cd.tracks], [(1, 0, 75), (2, 75, 75)])
            self.assertEqual(cd.addresses, ([0, 75, 150], 400))
            self.assertEqual(cd.read(10, 60), pcm[10 * 2352:70 * 2352])
            self.assertEqual(cd.text(), {})

    def test_a_linux_drives_list(self):
        sysfs = os.path.join(self.work, "block")
        for name, vendor, model in (("sr0", "HL-DT-ST", "DVDRAM GP65NB60"), ("sr1", "ASUS", "SDRW-08D2S-U"), ("sda", "x", "y")):
            os.makedirs(os.path.join(sysfs, name, "device"))
            for k, v in (("vendor", vendor), ("model", model)):
                with open(os.path.join(sysfs, name, "device", k), "w") as f:
                    f.write(v + "   \n")
        image = disc_images.iso(os.path.join(self.work, "d.iso"), {"VIDEO_TS/VIDEO_TS.IFO": b"x"}, label="HOLIDAY")
        real = iso9660.Image
        with mock.patch.object(cdaudio, "linux_status", lambda dev: {"/dev/sr0": "data", "/dev/sr1": "empty"}[dev]), \
                mock.patch.object(disc, "_linux_mounts", return_value={}), \
                mock.patch.object(iso9660, "Image", lambda dev: real(image)):
            found = disc._linux_drives(sysfs)
        self.assertEqual([(d["id"], d["name"], d["state"], d["kind"], d["label"]) for d in found],
                         [("sr0", "HL-DT-ST DVDRAM GP65NB60", "disc", "dvd", "HOLIDAY"), ("sr1", "ASUS SDRW-08D2S-U", "empty", None, "")])

    def test_a_macs_drive_list(self):
        mounted = os.path.join(self.work, "HOLIDAY")
        os.makedirs(os.path.join(mounted, "VIDEO_TS"))
        answers = {"/sbin/mount": "/dev/disk3s1 on / (apfs, local)\n/dev/disk6 on %s (udf, local, nodev, nosuid, read-only, noowners)\n" % mounted,
                   "/usr/bin/drutil": " Vendor   Product           Rev \n HL-DT-ST DVDRW  GA32N      KE06\n\n           Type: DVD-R                Name: /dev/disk6\n"}
        with mock.patch.object(disc, "_run", lambda cmd, timeout=8: (0, answers[cmd[0]])):
            (d,) = disc._mac_drives()
        self.assertEqual((d["id"], d["name"], d["state"], d["kind"], d["label"], d["mount"]),
                         ("disk6", "HL-DT-ST DVDRW GA32N", "disc", "dvd", "HOLIDAY", mounted))
        answers["/sbin/mount"] = "/dev/disk3s1 on / (apfs, local)\n"
        answers["/usr/bin/drutil"] = " Vendor   Product           Rev \n HL-DT-ST DVDRW  GA32N      KE06\n\n           Type: No Media Inserted\n"
        with mock.patch.object(disc, "_run", lambda cmd, timeout=8: (0, answers[cmd[0]])):
            (d,) = disc._mac_drives()
        self.assertEqual((d["state"], d["name"], d["kind"]), ("empty", "HL-DT-ST DVDRW GA32N", None))


class DataDisc(Discs):
    def test_its_videos_and_music_go_to_the_inbox(self):
        files = {"Holiday 2009/Beach Day.mp4": b"v" * 70000, "Holiday 2009/Beach Day.srt": b"1\n", "Songs/Demo.mp3": b"m" * 9000,
                 "autorun.inf": b"x", "Photos/1.jpg": b"j" * 100, ".hidden.mp4": b"h"}
        image = disc_images.iso(os.path.join(self.work, "data.iso"), files, label="BACKUP_2009")
        (d,) = self.put_in(image)
        self.assertEqual((d["kind"], d["label"]), ("data", "BACKUP_2009"))
        self.assertEqual([(f["path"], f["size"]) for f in d["disc"]["files"]],
                         [("Holiday 2009/Beach Day.mp4", 70000), ("Holiday 2009/Beach Day.srt", 2), ("Songs/Demo.mp3", 9000)])
        job = self.save(d["id"], {"name": "Backup 2009"})
        self.assertEqual((job["state"], job["to"]), ("done", "Inbox"))
        self.assertEqual(self.tree("inbox"), ["Backup 2009/Holiday 2009/Beach Day.mp4", "Backup 2009/Holiday 2009/Beach Day.srt", "Backup 2009/Songs/Demo.mp3"])
        with open(os.path.join(config.path("inbox"), "Backup 2009", "Holiday 2009", "Beach Day.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"v" * 70000)
        with self.assertRaisesRegex(ValueError, "already has"):
            disc.save(d["id"], {"name": "Backup 2009"})
        shutil.rmtree(os.path.join(config.path("inbox"), "Backup 2009"))

    def test_a_disc_with_nothing_to_save(self):
        image = disc_images.iso(os.path.join(self.work, "data.iso"), {"setup.exe": b"x" * 10}, label="DRIVERS")
        (d,) = self.put_in(image)
        self.assertEqual(d["disc"]["problem"], "There are no videos or music on this disc.")
        with self.assertRaisesRegex(ValueError, "no videos or music"):
            disc.save(d["id"], {"name": "x"})


@unittest.skipUnless(FFMPEG, "ffmpeg makes the DVD's video and packs what's saved")
class OverTheWeb(Discs):
    """The Server page's side of it: /api/admin/disc, for admins only."""

    @classmethod
    def setUpClass(cls):
        import threading
        from sofa import auth, store, web
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        for name, admin in (("disc-admin", True), ("disc-kid", False)):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123", admin=admin)
        from tests.test_server import Client
        cls.admin, cls.other = Client(cls.base), Client(cls.base)
        assert cls.admin.call("/api/login", {"name": "disc-admin", "password": "password123"})[0] == 200
        assert cls.other.call("/api/login", {"name": "disc-kid", "password": "password123"})[0] == 200

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_see_it_save_it_watch_it_go(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2,),))
        self.put_in(image)
        self.assertEqual(self.other.call("/api/admin/disc")[0], 403)                 # not an admin: not theirs to see
        self.assertEqual(self.other.call("/api/admin/disc", {"action": "save", "drive": "image1", "to": "movies", "name": "X", "titles": [1]})[0], 403)
        status, got = self.admin.call("/api/admin/disc")
        self.assertEqual((status, got["drives"][0]["kind"], got["drives"][0]["disc"]["titles"][0]["seconds"]), (200, "dvd", 2.0))
        status, got = self.admin.call("/api/admin/disc", {"action": "save", "drive": "image1", "to": "movies", "name": "", "titles": [1]})
        self.assertEqual((status, got["error"]), (400, "Give it a name."))
        status, got = self.admin.call("/api/admin/disc", {"action": "save", "drive": "image1", "to": "movies", "name": "By the Web", "year": "2010", "titles": [1]})
        self.assertEqual((status, got["job"]["state"], got["job"]["to"]), (200, "working", "Movies"))
        end = time.time() + 60
        while time.time() < end:
            job = self.admin.call("/api/admin/disc")[1]["jobs"][-1]
            if job["state"] != "working":
                break
            time.sleep(0.05)
        self.assertEqual((job["state"], job["name"]), ("done", "By the Web (2010)"))
        self.assertEqual(self.tree("movies"), ["By the Web (2010)/By the Web (2010).mkv"])
        self.assertEqual(self.admin.call("/api/admin/disc", {"action": "stop", "job": job["id"]})[1], {"ok": False})   # (it's done)
        self.assertEqual(self.admin.call("/api/admin/disc", {"action": "eject"})[0], 400)
        self.assertEqual(self.admin.call("/api/admin/disc", {"action": "names", "drive": "image1"})[0], 400)      # (offline, and no CD)
        # the Server page's status carries it, and the lookup has its switch
        status, got = self.admin.call("/api/admin/status")
        self.assertEqual(got["disc"]["drives"][0]["label"], "HOME_MOVIES")
        self.assertIs(got["settings"]["disc_lookup"], True)
        self.admin.call("/api/admin/settings", {"disc_lookup": False})
        self.addCleanup(config.update, {"disc_lookup": True})
        self.assertIs(config.get("disc_lookup"), False)

    def test_watching_it_over_the_web(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((4,),), subtitles=False)
        self.put_in(image)
        self.assertEqual(self.other.call("/api/admin/disc", {"action": "play", "drive": "image1"})[0], 403)
        status, p = self.admin.call("/api/admin/disc", {"action": "play", "drive": "image1"})
        self.assertEqual((status, p["title"]), (200, 1))
        import urllib.request
        req = urllib.request.Request(self.base + p["url"])
        with self.admin.opener.open(req, timeout=20) as r:
            text = r.read().decode()
            self.assertEqual(r.headers["Content-Type"], "application/vnd.apple.mpegurl")
        self.assertTrue(text.startswith("#EXTM3U\n#EXT-X-START:TIME-OFFSET=0"))
        with self.admin.opener.open(urllib.request.Request(self.base + p["url"].replace("index.m3u8", "seg00000.ts")), timeout=20) as r:
            self.assertEqual(r.headers["Content-Type"], "video/mp2t")
        try:
            self.other.opener.open(urllib.request.Request(self.base + p["url"]), timeout=20)
            self.fail("someone who isn't an admin got the disc's stream")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)
        self.assertEqual(self.admin.call("/api/admin/disc/playing?session=" + p["session"])[0], 200)
        self.assertEqual(self.admin.call("/api/admin/disc", {"action": "play_stop", "session": p["session"]})[1], {"ok": True})
        try:
            self.admin.opener.open(urllib.request.Request(self.base + "/api/admin/disc/poster?drive=image1"), timeout=20)
            self.fail("a picture for a disc nothing was found for")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_the_library_is_read_again_after_a_save(self):
        from sofa import watcher
        with open(os.path.join(os.path.dirname(os.path.abspath(watcher.__file__)), "watcher.py"), encoding="utf-8") as f:
            self.assertIn('disc.saved = lambda: LIBRARY.scan("a disc was saved")', f.read())
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2,),), subtitles=False)
        (d,) = self.put_in(image)
        calls = []
        with mock.patch.object(disc, "saved", lambda: calls.append(1)):
            self.save(d["id"], {"to": "movies", "name": "Scanned", "titles": [1]})
            with self.assertRaises(ValueError):
                disc.save(d["id"], {"to": "movies", "name": "Scanned", "titles": [1]})
        end = time.time() + 10                                                       # (on its own time: the job is done first)
        while not calls and time.time() < end:
            time.sleep(0.02)
        self.assertEqual(calls, [1])

    def test_a_job_is_over_before_the_library_is_read(self):
        """Reading a big library again takes a while: the page mustn't sit at 100%, nor the next disc wait, for it."""
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2,), (2,)), subtitles=False)
        (d,) = self.put_in(image)
        reading, let_go = [], []

        def slow_read():
            reading.append(1)
            while not let_go:
                time.sleep(0.02)
        with mock.patch.object(disc, "saved", slow_read):
            job = self.save(d["id"], {"to": "movies", "name": "First", "titles": [1]})
            self.assertEqual(job["state"], "done")                                   # though the library is still being read
            job = self.save(d["id"], {"to": "movies", "name": "Second", "titles": [2]})
            self.assertEqual(job["state"], "done")
            let_go.append(1)

    def test_a_shows_folder_gets_the_name_tidying_would_give_it(self):
        """So Sofa's own tidying (every ten minutes) doesn't rename the folder under a save that's still running."""
        from sofa import naming
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((2,),), subtitles=False)
        (d,) = self.put_in(image)
        self.save(d["id"], {"to": "shows", "name": "the.garden.tapes.2004", "season": 1, "episode": 1, "titles": [1]})
        (folder,) = os.listdir(config.path("shows"))
        show, year = naming.show_name(folder)
        self.assertEqual(naming.safe_filename(show + (" (%d)" % year if year else "")), folder)     # nothing left for tidying to do
        self.assertEqual(os.listdir(os.path.join(config.path("shows"), folder, "Season 1")), [folder + " S01E01.mkv"])


class ThePage(unittest.TestCase):
    """The Server page's panel and dialog (client/app.js), as far as reading the script goes."""

    def test_what_it_says(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "client", "app.js"), encoding="utf-8") as f:
            js = f.read()
        for text in ('data-disc-save="${esc(x.id)}">Save this disc</button>', "${discPanel(d.disc)}", 'api("/api/admin/disc", ask)',
                     '{ action: "names", drive: id }', '{ action: "stop", job: stop.dataset.discStop }', 'srvSwitch("disc_lookup"',
                     "Or save one you have as a folder or a disc image.", "k.problem || discLine(k)",
                     "Asks MusicBrainz, sending only where this disc's tracks start."):
            self.assertIn(text, js)
        for text in ("function viewDisc(id)", "return banner + discHome() + waiting", 'else if (name === "disc" && session.user.admin)', '{ action: "save", drive: id, quick: true }',
                     '{ action: "play", drive: id, title: title || null }', "Player.openDisc(p)", 'a === "disc-save" && discOn',
                     '{ action: "play_stop", session: discOn.session }', "In the disc drive", "This disc is copy-protected"):
            self.assertIn(text, js)
        with open(os.path.join(here, "client", "index.html"), encoding="utf-8") as f:
            self.assertIn('data-act="disc-save"', f.read())
        # a copy-protected disc's page has neither Play nor Save
        page = js[js.index("function viewDisc(id)"):js.index("async function discQuick(")]
        cant = page[page.index("const actions = k.problem ?"):]
        self.assertLess(cant.index("disc-cant"), cant.index("data-disc-play"))
        self.assertLess(cant.index(": `<div class=\"actions\">"), cant.index("data-disc-quick"))
        # a disc with a problem (copy-protected, a Blu-ray, nothing on it) gets its reason and no Save
        self.assertIn('${k && !k.problem ? `<button class="btn" data-disc-save=', js)
        self.assertIn("if (x.disc && !x.disc.problem && !d.disc.jobs.some(j => j.state === \"working\")) alerts.push(", js)


class WhatTheDiscIs(Discs):
    """A DVD's page in Sofa looks like a movie's: its label as words, and the film found as a library movie's is."""

    def test_a_label_as_words(self):
        for label, words in (("RULES_OF_ENGAGEMENT", "Rules of Engagement"), ("DVD_VIDEO", "DVD Video"), ("Star_Wars_IV", "Star Wars IV"), ("THE_MATRIX_WS", "The Matrix"), ("toy.story.2", "Toy Story 2"),
                             ("LORD_OF_THE_RINGS_DISC_1", "Lord of the Rings"), ("", "")):
            self.assertEqual(disc.tidy_label(label), words)
        for generic in ("DVD_VIDEO", "Home Movies", "DISC1", "VIDEO_TS", "20041225", "Untitled"):
            self.assertTrue(disc.GENERIC.match(disc.tidy_label(generic)), generic)
        self.assertFalse(disc.GENERIC.match("Rules of Engagement"))

    def test_the_film_is_found_and_its_poster_kept(self):
        from sofa import metadata
        config.update({"offline": False})
        self.addCleanup(config.update, {"offline": True})
        asked = []

        def movie(title, year):
            asked.append(title)
            return {"canonical": "Rules of Engagement", "year": 2000, "summary": "A court-martial.", "poster_url": "https://example.invalid/p.jpg", "source": "Wikipedia"}

        def download(url, dest, replace=False):
            with open(dest, "wb") as f:
                f.write(b"\xff\xd8" + b"x" * 600)
            return True
        with mock.patch.object(metadata, "movie", movie), mock.patch.object(metadata, "download", download), mock.patch.object(disc, "ART", self.work):
            g = disc._guess("RULES_OF_ENGAGEMENT")
            self.assertEqual((g["name"], g["year"], g["summary"], g["poster"], g["found"]), ("Rules of Engagement", 2000, "A court-martial.", True, "Wikipedia"))
            self.assertEqual(asked, ["Rules of Engagement"])
            self.assertEqual(disc._guess("DVD_VIDEO")["name"], "DVD Video")                  # (a label that names nothing: not asked)
            self.assertEqual(asked, ["Rules of Engagement"])
        config.update({"offline": True})
        with mock.patch.object(metadata, "movie", movie):
            self.assertEqual(disc._guess("RULES_OF_ENGAGEMENT"), {"name": "Rules of Engagement", "year": None, "summary": None, "poster": False, "found": False})
        self.assertEqual(asked, ["Rules of Engagement"])                                     # (offline: nothing asked)

    @unittest.skipUnless(FFMPEG, "ffmpeg makes the DVD's video")
    def test_one_press_saves_the_film_by_its_name(self):
        image = os.path.join(self.work, "film.iso")
        disc_images.dvd(image, self.work, clips=((1,), (3,), (2,)), subtitles=False, label="SUMMER_AT_THE_LAKE")
        with mock.patch.object(disc, "_guess", lambda label: {"name": "Summer at the Lake", "year": 2004, "summary": None, "poster": False, "found": "Wikipedia"}):
            (d,) = self.put_in(image)
        self.assertEqual(d["disc"]["guess"]["name"], "Summer at the Lake")
        self.assertNotIn("_poster", d["disc"]["guess"])
        self.assertEqual(disc.quick(disc._known[d["id"]]["disc"]), {"to": "movies", "name": "Summer at the Lake", "year": 2004, "titles": [2]})   # (the longest)
        job = self.save(d["id"], {"quick": True})
        self.assertEqual((job["state"], job["name"]), ("done", "Summer at the Lake (2004)"))
        self.assertEqual(self.tree("movies"), ["Summer at the Lake (2004)/Summer at the Lake (2004).mkv"])
        self.assertAlmostEqual(float(probe(os.path.join(config.path("movies"), job["name"], job["name"] + ".mkv"))["format"]["duration"]), 3, delta=0.4)
        with self.assertRaisesRegex(ValueError, "already there"):                          # pressed again: nothing written over
            disc.save(d["id"], {"quick": True})

    @unittest.skipUnless(FFMPEG, "ffmpeg packs the tracks")
    def test_one_press_for_a_cd_and_a_data_disc(self):
        cue, _ = disc_images.audio_cd(self.work, tracks=((1, "One"), (1, "Two")))
        image = disc_images.iso(os.path.join(self.work, "data.iso"), {"Trip/Beach.mp4": b"v" * 3000}, label="TRIP_2009")
        cd, data = self.put_in(cue, image)
        self.assertEqual(disc.quick(disc._known[cd["id"]]["disc"]), {"artist": "The Made Ups", "album": "Made For Testing", "tracks": {"1": "One", "2": "Two"}})
        self.assertEqual(disc.quick(disc._known[data["id"]]["disc"]), {"name": "Trip 2009"})
        self.assertEqual(self.save(cd["id"], {"quick": True})["state"], "done")
        self.assertEqual(self.tree("music"), ["The Made Ups/Made For Testing/01 One.flac", "The Made Ups/Made For Testing/02 Two.flac"])


@unittest.skipUnless(FFMPEG, "ffmpeg converts the disc as it plays")
class FromAFolderOrImage(Discs):
    """Save from a folder or disc image: a DVD copied to the computer, an .iso, a CD's .cue, saved as a disc is."""

    def test_add_save_and_take_away(self):
        folder = os.path.join(self.work, "Summer at the Lake")
        disc_images.dvd(folder, self.work, clips=((2,),), subtitles=False, folder=True) if FFMPEG else os.makedirs(os.path.join(folder, "VIDEO_TS"))
        before = config.get("disc_sources")
        self.addCleanup(config.update, {"disc_sources": before})
        patch = mock.patch.dict(os.environ, {"SOFA_DISCS": ""})
        patch.start()
        self.addCleanup(patch.stop)
        r = disc.add_source(os.path.join(folder, "VIDEO_TS"))                              # (VIDEO_TS itself: its folder)
        self.assertEqual(config.get("disc_sources"), [folder])
        self.assertEqual(disc.add_source(folder), r)                                        # (twice: once)
        self.assertEqual(config.get("disc_sources"), [folder])
        (d,) = [x for x in disc._made_drives() if x["id"] == r["drive"]]
        self.assertEqual((d["name"], d["kind"], d["copy"]), ("Folder", "dvd", True))
        if FFMPEG:
            with mock.patch.object(disc, "drives", disc._made_drives):
                (shown,) = disc.status(wait=60)["drives"]
                self.assertTrue(shown["copy"])
                job = self.save(r["drive"], {"quick": True})
            self.assertEqual(job["state"], "done")
            self.assertEqual(self.tree("movies"), ["Summer at the Lake/Summer at the Lake.mkv"])
        self.assertEqual(disc.remove_source(r["drive"]), {"ok": True})
        self.assertEqual(config.get("disc_sources"), [])
        self.assertEqual(disc.remove_source(r["drive"]), {"ok": False})

    def test_what_it_takes(self):
        for path, why in (("/nowhere/at/all", "nothing at"), (self.work, "no VIDEO_TS"), (__file__, "an .iso")):
            with self.assertRaisesRegex(ValueError, why):
                disc.add_source(path)
        iso = disc_images.iso(os.path.join(self.work, "a.iso"), {"VIDEO_TS/VIDEO_TS.IFO": b"x"})
        self.assertEqual(disc.source_path(iso), iso)

    def test_a_copy_protected_disc_points_there(self):
        self.assertIn("Save from a folder or disc image", disc.PROTECTED)
        self.assertIn("Save from a folder or disc image", disc.WONT_READ)
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "client", "app.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn('${k.protected ? `<div class="actions"><button class="btn" data-disc-source="1">Save from a folder or disc image…</button></div>` : ""}', js)
        self.assertIn('{ action: "add_source", path: form.elements.path.value }', js)


@unittest.skipUnless(FFMPEG, "ffmpeg converts the disc as it plays")
class WatchingTheDisc(Discs):
    """Play: a DVD's title in Sofa's player, read by the one reader and converted as it plays."""

    def test_it_plays_and_stops(self):
        image = os.path.join(self.work, "home.iso")
        disc_images.dvd(image, self.work, clips=((6,), (2, 2)), subtitles=False)
        (d,) = self.put_in(image)
        read = []
        real = dvd.read_title

        def counted(*a, **k):
            read.append(1)
            return real(*a, **k)
        with mock.patch.object(dvd, "read_title", counted):
            p = disc.play(d["id"])
        self.assertEqual(read, [1])                                                          # (through the one reader)
        self.assertEqual((p["title"], p["seconds"], p["name"], p["drive"]), (1, 6.0, "Home Movies", d["id"]))
        self.assertTrue(p["url"].startswith("/api/admin/disc/play/") and p["url"].endswith("/index.m3u8"))
        end = time.time() + 30
        while time.time() < end and disc.play_status(p["session"])["playing"]:
            time.sleep(0.2)
        listing = open(disc.play_file(p["session"], "index.m3u8")).read()
        self.assertIn("#EXT-X-ENDLIST", listing)
        seg = disc.play_file(p["session"], "seg00000.ts")
        got = probe(seg)
        self.assertEqual(sorted(x["codec_name"] for x in got["streams"]), ["aac", "h264"])
        for name in ("../../etc/passwd", "index.m3u8x", "seg1.ts", "x.mkv"):
            self.assertIsNone(disc.play_file(p["session"], name))
        self.assertIsNone(disc.play_file("0" * 20, "index.m3u8"))
        self.assertTrue(disc.play_stop(p["session"]))
        self.assertFalse(os.path.exists(os.path.dirname(seg)))                               # nothing left behind
        self.assertIsNone(disc.play_file(p["session"], "index.m3u8"))
        p2 = disc.play(d["id"], 2)
        self.assertEqual((p2["title"], p2["seconds"]), (2, 4.0))
        disc.play(d["id"], 1)                                                                # one at a time: the last one goes
        self.assertEqual(disc.play_status(p2["session"]), {"playing": False})
        disc.play_stop()
        with self.assertRaisesRegex(ValueError, "isn't on the disc"):
            disc.play(d["id"], 9)

    def test_a_copy_protected_disc_isnt_played_either(self):
        image = os.path.join(self.work, "film.iso")
        disc_images.dvd(image, self.work, clips=((2,),), protected=True, subtitles=False)
        (d,) = self.put_in(image)
        with mock.patch.object(subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "copy-protected, so Sofa can't read its video"):
                disc.play(d["id"])
            self.assertFalse(popen.called)
        with mock.patch.object(dvd, "sample", return_value=None):                            # scrambled only further in
            self.forget()
            (d,) = self.put_in(image)
        p = disc.play(d["id"]) if False else None
        try:
            p = disc.play(d["id"])
        except ValueError as exc:
            self.assertIn("copy-protected", str(exc))                                        # (caught before anything was made)
        if p:
            end = time.time() + 20
            while time.time() < end and disc.play_status(p["session"])["playing"]:
                time.sleep(0.1)
            self.assertIn("copy-protected", disc.play_status(p["session"])["error"] or "")
            disc.play_stop()


class PlacingAFile(unittest.TestCase):
    def test_never_over_one_thats_there(self):
        work = tempfile.mkdtemp(prefix="sofa-disc-")
        self.addCleanup(shutil.rmtree, work, True)
        src, dest = os.path.join(work, ".new"), os.path.join(work, "film.mkv")
        with open(src, "wb") as f:
            f.write(b"new")
        with open(dest, "wb") as f:
            f.write(b"old")
        with self.assertRaises(FileExistsError):
            fileops.place(src, dest)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b"old")
        os.unlink(dest)
        fileops.place(src, dest)
        self.assertEqual(os.listdir(work), ["film.mkv"])
        # a drive with no links (exFAT, FAT): still never over a file
        with open(src, "wb") as f:
            f.write(b"newer")
        if os.name != "nt":
            with mock.patch.object(os, "link", side_effect=OSError(1, "Operation not permitted")):
                with self.assertRaises(FileExistsError):
                    fileops.place(src, dest)
                os.unlink(dest)
                fileops.place(src, dest)
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), b"newer")


if __name__ == "__main__":
    unittest.main()
