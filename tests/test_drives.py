"""USB drives on a Sofa Box: plugged in, they join the box's Sofa by themselves (auto_drives) and are sorted the way
the Inbox sorts, with links on the box (places.py, organizer.link_drive): nothing on the drive moved or renamed."""
import os
import shutil
import tempfile
import unittest

from tests import video
from sofa import config, optimize, organizer, places
from sofa.library import LIBRARY as LIB


class Drives(unittest.TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="sofa-media-")
        self.drive = os.path.join(self.media, "KINGSTON")
        d = self.drive
        video(os.path.join(d, "Films", "Ronin (1998)", "Ronin.1998.1080p.mkv"))        # a movie in its own folder
        with open(os.path.join(d, "Films", "Ronin (1998)", "Ronin.1998.1080p.en.srt"), "w") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
        video(os.path.join(d, "Films", "Arrival.2016.mp4"))                             # a loose movie in a folder
        video(os.path.join(d, "Some.Comedy.2020.mkv"))                                   # loose, right on the drive
        video(os.path.join(d, "Alien (1979)", "alien.mkv"))                              # a movie's folder at the top
        for e in (1, 2, 3):                                                              # a show, named like episodes
            video(os.path.join(d, "Downloads", "The.Expanse.S01E0%d.720p.mkv" % e))
        video(os.path.join(d, "TV", "Severance", "Season 1", "Severance.S01E01.mkv"))  # a "TV" folder of shows
        video(os.path.join(d, "TV", "Severance", "Season 1", "Severance.S01E02.mkv"))
        video(os.path.join(d, "Breaking Bad (2008)", "Season 1", "BB.S01E01.mkv"))       # the folder says which show
        video(os.path.join(d, "Breaking Bad (2008)", "Season 1", "Breaking.Bad.S01E02.mkv"))
        video(os.path.join(d, "XXX", "Private.Clip.2021.mkv"))                         # never shown from a drive
        video(os.path.join(d, "System Volume Information", "x.mkv"))
        video(os.path.join(d, "Music", "Artist - Song.mp3"))                             # music stays in Files
        self.before = {k: config.get(k) for k in ("places", "drive_folders", "auto_drives", "drives_ignored")}
        config.update({"drive_folders": [self.media], "auto_drives": True, "drives_ignored": [], "places": []})
        self.real_is_drive = places._is_drive
        places._is_drive = lambda path: os.path.dirname(path) == self.media              # (folders here, not mounts)

    def tearDown(self):
        places._is_drive = self.real_is_drive
        for p in places.extra():
            if p.get("drive"):
                shutil.rmtree(p["path"], ignore_errors=True)
        config.update(self.before)
        LIB.scan("tests")
        shutil.rmtree(self.media, ignore_errors=True)

    def files(self):
        return sorted(os.path.relpath(os.path.join(dp, f), self.drive) for dp, _d, fs in os.walk(self.drive) for f in fs)

    def titles(self):
        return {m["title"] for m in LIB.movies}

    def test_a_drive_joins_by_itself_and_is_sorted(self):
        before = self.files()
        added = places.auto_drives()
        self.assertEqual(len(added), 1)
        self.assertEqual(places.auto_drives(), [])                                       # once
        place = places.by_id(added[0])
        self.assertEqual(place["drive"], self.drive)
        self.assertEqual(place["path"], places.tree_for(added[0]))
        self.assertEqual(place["name"], "KINGSTON")
        self.assertTrue(organizer.link_drive(place))
        self.assertEqual(organizer.link_drive(place), 0)                                 # nothing changed since
        LIB.scan("tests")
        movies = {m["title"]: m for m in LIB.movies}
        for title in ("Ronin", "Arrival", "Some Comedy", "Alien"):
            self.assertIn(title, movies)
            self.assertEqual(movies[title]["place"], added[0])
        shows = {s.get("name") or s.get("title") for s in LIB.shows}
        for name in ("The Expanse", "Severance", "Breaking Bad"):
            self.assertIn(name, shows)
        expanse = next(s for s in LIB.shows if (s.get("name") or s.get("title")) == "The Expanse")
        self.assertEqual(sum(len(x["episodes"]) for x in expanse["seasons"]), 3)
        everything = " ".join([m["title"] for m in LIB.movies] + [s.get("name") or s.get("title") or "" for s in LIB.shows])
        self.assertNotIn("Private", everything)                                         # adult folders stay out
        self.assertNotIn("Song", everything)
        self.assertEqual(self.files(), before)                                           # nothing made, moved or renamed
        ronin = os.path.join(place["path"], "Movies", "Ronin (1998)")
        self.assertTrue(os.path.islink(os.path.join(ronin, "Ronin (1998).mkv")))         # named as the Inbox names it
        self.assertTrue(os.path.islink(os.path.join(ronin, "Ronin (1998).en.srt")))      # with its subtitles
        self.assertEqual(places.status(LIB)["places"][-1]["counts"]["movies"], 4)
        self.assertTrue(places.status(LIB)["places"][-1]["usb"])

        with self.assertRaises(ValueError):                                              # nothing filed or moved onto it
            places.set_target(added[0])
        self.assertEqual(optimize.enqueue([LIB.item(movies["Ronin"]["id"]) or {"path": os.path.join(ronin, "Ronin (1998).mkv")}]), 0)
        self.assertFalse([i for i in optimize.candidates(LIB) if places.on_usb(i["path"])])

        video(os.path.join(self.drive, "Films", "Collateral (2004)", "Collateral.2004.mkv"))   # something new on it
        os.remove(os.path.join(self.drive, "Films", "Arrival.2016.mp4"))                 # and something gone
        self.assertTrue(organizer.link_drive(place))
        LIB.scan("tests")
        self.assertIn("Collateral", self.titles())
        self.assertNotIn("Arrival", self.titles())
        self.assertFalse(os.path.exists(os.path.join(place["path"], "Movies", "Arrival (2016)")))   # its folder too

        shutil.move(self.drive, self.drive + "-away")                                    # unplugged: out of the library
        self.assertEqual(places.usb(), [])
        self.assertTrue(LIB.changed())
        LIB.scan("tests")
        self.assertNotIn("Ronin", self.titles())
        shutil.move(self.drive + "-away", self.drive)                                    # back: the same place again
        self.assertEqual(places.auto_drives(), [])
        self.assertEqual(organizer.link_drive(place), 0)
        LIB.scan("tests")
        self.assertIn("Ronin", self.titles())

        places.remove(added[0])                                                          # an admin stops using it:
        self.assertEqual(places.auto_drives(), [])                                       # it doesn't come back by itself
        self.assertIn(os.path.abspath(self.drive), config.get("drives_ignored"))
        self.assertFalse(os.path.exists(place["path"]))                                  # its links are gone, its files not
        self.assertEqual(len(self.files()), len(before))

    def test_a_drive_read_as_it_was_before_is_sorted_now(self):
        config.update({"places": [{"id": "usbold1234", "name": "KINGSTON", "path": self.drive, "as_is": True}]})
        self.assertEqual(places.auto_drives(), [])
        place = places.by_id("usbold1234")
        self.assertEqual(place["drive"], self.drive)
        self.assertNotIn("as_is", place)
        self.assertTrue(organizer.link_drive(place))
        LIB.scan("tests")
        self.assertIn("Ronin", self.titles())

    def test_off_on_a_computer(self):
        config.update({"auto_drives": False})
        self.assertEqual(places.auto_drives(), [])


if __name__ == "__main__":
    unittest.main()
