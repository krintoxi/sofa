"""Files dropped in the Inbox end up in the right place, with their subtitles, and junk set aside."""
import os
import unittest

from tests import LIBRARY, video
from sofa import config, organizer


def drop(rel, size=2048):
    return video(os.path.join(config.path("inbox"), rel), size)


def exists(rel):
    return os.path.exists(os.path.join(LIBRARY, rel))


class Inbox(unittest.TestCase):
    def file(self, rel, hint=None):
        entry = os.path.join(config.path("inbox"), rel.split("/")[0])
        organizer._handle(entry, hint)

    def test_episode(self):
        drop("Breaking.Bad.S02E05.720p.HDTV.x264.mkv")
        self.file("Breaking.Bad.S02E05.720p.HDTV.x264.mkv")
        self.assertTrue(exists("Shows/Breaking Bad/Season 2/Breaking Bad S02E05.mkv"))

    def test_anime_episode(self):
        drop("[SubsPlease] Frieren - 05 (1080p) [ABCD1234].mkv")
        self.file("[SubsPlease] Frieren - 05 (1080p) [ABCD1234].mkv")
        self.assertTrue(exists("Shows/Frieren/Season 1/Frieren S01E05.mkv"))

    def test_movie_with_subtitle_and_poster(self):
        drop("Heat.1995.1080p.BluRay-GRP/Heat.1995.1080p.BluRay-GRP.mkv")
        folder = os.path.join(config.path("inbox"), "Heat.1995.1080p.BluRay-GRP")
        with open(os.path.join(folder, "Heat.1995.1080p.BluRay-GRP.spa.srt"), "w") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nHola\n")
        with open(os.path.join(folder, "poster.jpg"), "wb") as f:
            f.write(b"\xff\xd8\xff")
        with open(os.path.join(folder, "RARBG.txt"), "w") as f:
            f.write("junk")
        self.file("Heat.1995.1080p.BluRay-GRP")
        self.assertTrue(exists("Movies/Heat (1995)/Heat (1995).mkv"))
        self.assertTrue(exists("Movies/Heat (1995)/Heat (1995).spa.srt"))      # follows the video (Spanish)
        self.assertTrue(exists("Movies/Heat (1995)/folder.jpg"))
        self.assertFalse(exists("Needs Review/Inbox leftovers/Heat.1995.1080p.BluRay-GRP/RARBG.txt"))

    def test_movie_without_a_year(self):
        drop("Amelie.mkv")
        self.file("Amelie.mkv")
        self.assertTrue(exists("Movies/Amelie/Amelie.mkv"))

    def test_phone_video(self):
        drop("VID_20230512_143000.mp4")
        self.file("VID_20230512_143000.mp4")
        self.assertTrue(exists("Movies/Home Videos/Video 2023-05-12 14.30/Video 2023-05-12 14.30.mp4"))

    def test_adult_stays_in_adult(self):
        drop("XXX/Some.Scene.2021.mp4")
        organizer._handle(os.path.join(config.path("inbox"), "XXX", "Some.Scene.2021.mp4"), "adult")
        found = [os.path.join(d, f) for d, _s, fs in os.walk(config.path("adult")) for f in fs if f.endswith(".mp4")]
        self.assertTrue(found, "nothing was filed in Adult")
        self.assertFalse(any(f.endswith("Some.Scene.2021.mp4") for d, _s, fs in os.walk(config.path("movies")) for f in fs))


if __name__ == "__main__":
    unittest.main()
