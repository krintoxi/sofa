"""USB drives on a Sofa Box: plugged in, they join the box's Sofa by themselves (auto_drives), read as they are
(places.py "as_is", library.py _scan_drive): their own folders, nothing on them moved or renamed."""
import os
import shutil
import tempfile
import unittest

from tests import video
from sofa import config, places
from sofa.library import LIBRARY as LIB


class Drives(unittest.TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="sofa-media-")
        self.drive = os.path.join(self.media, "KINGSTON")
        d = self.drive
        video(os.path.join(d, "Films", "Heat (1995)", "Heat.1995.1080p.mkv"))          # a movie in its own folder
        video(os.path.join(d, "Films", "Arrival.2016.mp4"))                             # a loose movie in a folder
        video(os.path.join(d, "Some.Comedy.2020.mkv"))                                   # loose, right on the drive
        video(os.path.join(d, "Alien (1979)", "alien.mkv"))                              # a movie's folder at the top
        for e in (1, 2, 3):                                                              # a show, named like episodes
            video(os.path.join(d, "Downloads", "The.Expanse.S01E0%d.720p.mkv" % e))
        video(os.path.join(d, "TV", "Severance", "Season 1", "Severance.S01E01.mkv"))  # a "TV" folder of shows
        video(os.path.join(d, "TV", "Severance", "Season 1", "Severance.S01E02.mkv"))
        video(os.path.join(d, "Breaking Bad (2008)", "BB.S01E01.mkv"))                 # a show folder's own name stands
        video(os.path.join(d, "Breaking Bad (2008)", "BB.S01E02.mkv"))
        video(os.path.join(d, "XXX", "Private.Clip.2021.mkv"))                         # never shown from a drive
        video(os.path.join(d, "System Volume Information", "x.mkv"))
        self.before = {k: config.get(k) for k in ("places", "drive_folders", "auto_drives", "drives_ignored")}
        config.update({"drive_folders": [self.media], "auto_drives": True, "drives_ignored": []})
        self.real_is_drive = places._is_drive
        places._is_drive = lambda path: os.path.dirname(path) == self.media              # (folders here, not mounts)

    def tearDown(self):
        places._is_drive = self.real_is_drive
        config.update(self.before)
        LIB.scan("tests")
        shutil.rmtree(self.media, ignore_errors=True)

    def files(self):
        return sorted(os.path.relpath(os.path.join(dp, f), self.drive) for dp, _d, fs in os.walk(self.drive) for f in fs)

    def test_a_drive_joins_by_itself_as_it_is(self):
        before = self.files()
        added = places.auto_drives()
        self.assertEqual(len(added), 1)
        self.assertEqual(places.auto_drives(), [])                                       # once
        place = places.by_id(added[0])
        self.assertTrue(place["as_is"])
        self.assertEqual(place["name"], "KINGSTON")
        LIB.scan("tests")
        movies = {m["title"]: m for m in LIB.movies}
        for title in ("Heat", "Arrival", "Some Comedy", "Alien"):
            self.assertIn(title, movies)
            self.assertEqual(movies[title]["place"], added[0])
        shows = {s.get("name") or s.get("title") for s in LIB.shows}
        self.assertIn("The Expanse", shows)
        self.assertIn("Severance", shows)
        self.assertIn("Breaking Bad", shows)
        everything = " ".join([m["title"] for m in LIB.movies] + [s.get("name") or s.get("title") or "" for s in LIB.shows])
        self.assertNotIn("Private", everything)                                         # adult folders stay out
        self.assertEqual(self.files(), before)                                           # nothing made, moved or renamed
        self.assertEqual(places.status(LIB)["places"][-1]["counts"]["movies"], 4)

        with self.assertRaises(ValueError):                                              # nothing filed or moved onto it
            places.set_target(added[0])

        shutil.move(self.drive, self.drive + "-away")                                    # unplugged: out of the library
        self.assertTrue(LIB.changed())
        LIB.scan("tests")
        self.assertNotIn("Heat", {m["title"] for m in LIB.movies})
        shutil.move(self.drive + "-away", self.drive)                                    # back: the same place again
        self.assertEqual(places.auto_drives(), [])
        LIB.scan("tests")
        self.assertIn("Heat", {m["title"] for m in LIB.movies})

        places.remove(added[0])                                                          # an admin stops using it:
        self.assertEqual(places.auto_drives(), [])                                       # it doesn't come back by itself
        self.assertIn(os.path.abspath(self.drive), config.get("drives_ignored"))

    def test_off_on_a_computer(self):
        config.update({"auto_drives": False})
        self.assertEqual(places.auto_drives(), [])
