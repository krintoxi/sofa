"""Sofa 1.5.39: what ripping programs leave, dropped in the Inbox. A disc's titles named title_t00.mkv become the film
(named after their folder) and its extras; a ripped DVD (an .iso, or a folder with VIDEO_TS in it) becomes one movie
with every sound and subtitle track and the chapters, its own files kept in Deleted; a show's disc goes to Needs
Review, to be opened with Save from a folder or disc image."""
import os
import shutil
import tempfile
import time
import unittest

from tests import LIBRARY, disc_images
from sofa import config, disc, media, organizer

FFMPEG = media.tool("ffmpeg") and media.tool("ffprobe")


class Rips(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="sofa-rips-")
        self.addCleanup(shutil.rmtree, self.work, True)
        before = {k: config.get(k) for k in ("movies", "inbox", "review")}
        self.addCleanup(config.update, before)
        config.update({k: os.path.join(self.work, "library", k.capitalize()) for k in before})
        for k in before:
            os.makedirs(config.path(k), exist_ok=True)
        self.addCleanup(self.forget)

    def forget(self):
        with disc._lock:
            del disc._jobs[:]
            disc._inbox.clear()

    def drop(self, rel, size=2048):
        p = os.path.join(config.path("inbox"), rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"\0" * size)

    def sort(self):
        for _ in range(3):                                   # (a DVD at a time: the next one goes the next time round)
            for e in sorted(os.listdir(config.path("inbox"))):
                organizer._handle(os.path.join(config.path("inbox"), e))
            end = time.time() + 120
            while time.time() < end and (disc._inbox or any(j["state"] == "working" for j in disc._jobs)):
                time.sleep(0.1)

    def tree(self, key):
        root = config.path(key)
        return sorted(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/") for d, _, fs in os.walk(root) for f in fs)

    def test_a_discs_titles_are_its_film_and_its_extras(self):
        self.drop("Heat (1995)/title_t00.mkv", 9000)
        self.drop("Heat (1995)/title_t01.mkv", 3000)
        self.drop("Heat (1995)/title_t02.mkv", 2000)
        self.drop("THE_MATRIX/B1_t00.mkv", 5000)
        self.drop("ARRIVAL_2016/title00.mkv", 5000)
        self.sort()
        self.assertEqual(self.tree("movies"), ["Arrival (2016)/Arrival (2016).mkv", "Heat (1995)/Extras/Heat (1995) - Extra 1.mkv",
                                               "Heat (1995)/Extras/Heat (1995) - Extra 2.mkv", "Heat (1995)/Heat (1995).mkv", "The Matrix/The Matrix.mkv"])
        with open(os.path.join(config.path("movies"), "Heat (1995)", "Heat (1995).mkv"), "rb") as f:
            self.assertEqual(len(f.read()), 9000)                                   # (the longest is the film)

    def test_a_title_on_its_own_says_nothing(self):
        self.drop("title_t00.mkv")
        self.sort()
        self.assertEqual(self.tree("movies"), [])
        self.assertEqual(self.tree("review"), ["From Inbox/title_t00.mkv"])

    def test_named_files_are_filed_as_ever(self):
        self.drop("Heat.1995.1080p/Heat.1995.1080p.mkv")
        self.drop("Heat.1995.1080p/title_t03.mkv", 100)                          # (beside a named one: left to the usual rules)
        self.sort()
        self.assertIn("Heat (1995)/Heat (1995).mkv", self.tree("movies"))

    @unittest.skipUnless(FFMPEG, "ffmpeg makes the DVD and packs the movie")
    def test_a_ripped_dvd_becomes_one_movie(self):
        inbox = config.path("inbox")
        disc_images.dvd(os.path.join(inbox, "Summer at the Lake (2004)"), self.work, clips=((3,), (1,)), folder=True)
        disc_images.dvd(os.path.join(inbox, "ARRIVAL_2016.iso"), self.work, clips=((2,),), subtitles=False)
        os.makedirs(os.path.join(inbox, "Old Tape"))
        disc_images.dvd(os.path.join(inbox, "Old Tape", "Old Tape.iso"), self.work, clips=((2,),), subtitles=False)
        self.sort()
        self.assertEqual(self.tree("movies"), ["Arrival (2016)/Arrival (2016).mkv", "Old Tape/Old Tape.mkv",
                                               "Summer at the Lake (2004)/Summer at the Lake (2004).mkv"])
        self.assertEqual(os.listdir(inbox), [])
        deleted = organizer.deleted_root()
        self.assertTrue(os.path.exists(os.path.join(deleted, "Inbox", "ARRIVAL_2016.iso")))           # (kept a while, as deleted things are)
        self.assertTrue(os.path.exists(os.path.join(deleted, "Inbox", "Summer at the Lake (2004)", "VIDEO_TS", "VIDEO_TS.IFO")))
        import json
        import subprocess
        got = json.loads(subprocess.run([media.tool("ffprobe"), "-v", "error", "-show_streams", "-of", "json",
                                         os.path.join(config.path("movies"), "Summer at the Lake (2004)", "Summer at the Lake (2004).mkv")],
                                        capture_output=True, text=True).stdout)
        self.assertEqual([s["codec_type"] for s in got["streams"]], ["video", "audio", "audio", "subtitle"])

    @unittest.skipUnless(FFMPEG, "ffmpeg makes the DVD")
    def test_a_shows_disc_and_a_scrambled_one_go_to_needs_review(self):
        inbox = config.path("inbox")
        disc_images.dvd(os.path.join(inbox, "Friends Season 1 Disc 1"), self.work, clips=((1,),), subtitles=False, folder=True)
        disc_images.dvd(os.path.join(inbox, "Copied Straight Off"), self.work, clips=((2,),), subtitles=False, folder=True, protected=True)
        self.sort()
        self.assertEqual(self.tree("movies"), [])
        review = self.tree("review")
        self.assertIn("From Inbox/Friends Season 1 Disc 1/VIDEO_TS/VIDEO_TS.IFO", review)
        self.assertIn("From Inbox/Copied Straight Off/VIDEO_TS/VIDEO_TS.IFO", review)

    def test_what_counts_as_a_ripped_dvd(self):
        inbox = config.path("inbox")
        self.drop("A Film.iso")
        self.drop("Film Folder/VIDEO_TS/VIDEO_TS.IFO")
        self.drop("Deeper/Disc/VIDEO_TS/VIDEO_TS.IFO")
        self.drop("Just Video/film.mkv")
        self.assertEqual(disc.rip_source(os.path.join(inbox, "A Film.iso")), os.path.join(inbox, "A Film.iso"))
        self.assertEqual(disc.rip_source(os.path.join(inbox, "Film Folder")), os.path.join(inbox, "Film Folder"))
        self.assertEqual(disc.rip_source(os.path.join(inbox, "Film Folder", "VIDEO_TS")), os.path.join(inbox, "Film Folder"))
        self.assertEqual(disc.rip_source(os.path.join(inbox, "Deeper")), os.path.join(inbox, "Deeper", "Disc"))
        self.assertIsNone(disc.rip_source(os.path.join(inbox, "Just Video")))
        for name in ("title_t00", "B1_t03", "title00", "VTS_01_1", "Title 1", "t05", "DISC1", "track 3"):
            self.assertTrue(organizer.RIP_NAME.match(name), name)
        for name in ("Heat (1995)", "Heat.1995.1080p", "The Office S01E01", "Titanic", "Disco Inferno"):
            self.assertFalse(organizer.RIP_NAME.match(name), name)


if __name__ == "__main__":
    unittest.main()
