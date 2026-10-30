"""Working out what a file is from its name."""
import unittest

import tests
from sofa import naming

assert tests.ROOT                   # tests/__init__ set up a throwaway data folder before sofa was imported


class Episodes(unittest.TestCase):
    CASES = [
        ("The.Sopranos.S01E01.1080p.BluRay.x265-RARBG", None, False, (1, 1)),
        ("the sopranos 1x01 pilot", None, False, (1, 1)),
        ("Breaking Bad - S02E05 - Breakage", None, False, (2, 5)),
        ("breaking.bad.205.hdtv.xvid", None, False, (2, 5)),
        ("[SubsPlease] Frieren - 05 (1080p) [ABCD1234]", None, False, (1, 5)),
        ("One Piece - 1071 [1080p]", None, False, (1, 1071)),
        ("Show Name Season 2 Episode 3", None, False, (2, 3)),
        ("Show.Name.S03.E04.720p", None, False, (3, 4)),
        ("Planet Earth II - Ep 1 - Islands", None, False, (1, 1)),
        ("Episode 05", 1, True, (1, 5)),
        ("Stranger Things 4x09", None, False, (4, 9)),
        ("mr.robot.s02e01", None, False, (2, 1)),
    ]

    def test_season_and_episode(self):
        for stem, hint, in_show, want in self.CASES:
            with self.subTest(stem):
                ep = naming.parse_episode(stem, hint, in_show=in_show)
                self.assertIsNotNone(ep, stem)
                self.assertEqual((ep["s"], ep["e"]), want)

    def test_double_episode(self):
        ep = naming.parse_episode("Friends.S01E01-E02")
        self.assertEqual((ep["s"], ep["e"], ep.get("e2")), (1, 1, 2))

    def test_movies_are_not_episodes(self):
        for stem in ("Heat.1995.1080p.BluRay.x264", "Blade Runner 2049 (2017)", "1917.2019.1080p", "2001.A.Space.Odyssey.1968"):
            with self.subTest(stem):
                self.assertIsNone(naming.parse_episode(stem))

    def test_daily_show_by_date(self):
        ep = naming.parse_dated("The.Daily.Show.2024.03.15.720p")
        self.assertEqual((ep["s"], ep["e"]), (2024, 315))


class Movies(unittest.TestCase):
    CASES = [
        ("Heat.1995.1080p.BluRay.x264", ("Heat", 1995)),
        ("Inception (2010) [1080p] [YTS.MX]", ("Inception", 2010)),
        ("The.Matrix.Reloaded.2003.REMASTERED.1080p", ("The Matrix Reloaded", 2003)),
        ("Blade Runner 2049 (2017)", ("Blade Runner 2049", 2017)),
        ("2001.A.Space.Odyssey.1968", ("2001 A Space Odyssey", 1968)),
        ("1917.2019.1080p", ("1917", 2019)),
        ("Dune Part Two 2024 2160p WEB-DL", ("Dune Part Two", 2024)),
        ("Amelie", ("Amelie", None)),
    ]

    def test_title_and_year(self):
        for stem, want in self.CASES:
            with self.subTest(stem):
                self.assertEqual(naming.parse_movie(stem), want)

    def test_show_folder_names(self):
        self.assertEqual(naming.show_name("The.Sopranos.1999.S01-S06.Complete.Series.1080p.BluRay.x265-HOSTILE"), ("The Sopranos", 1999))
        self.assertEqual(naming.show_name("Westworld Season 1")[0], "Westworld")

    def test_camera_videos(self):
        self.assertEqual(naming.camera_name("VID_20230512_143022"), "Video 2023-05-12 14.30")
        self.assertIsNone(naming.camera_name("Heat (1995)"))


if __name__ == "__main__":
    unittest.main()


class ShowDetailsFromFiles(unittest.TestCase):
    """A Kodi tvshow.nfo, and an episode's own .nfo, when no lookup service knows the show (or offline)."""

    def test_tvshow_nfo_and_episode_nfo(self):
        import os
        from sofa import sidecars
        folder = os.path.join(tests.ROOT, "nfo-show")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "tvshow.nfo"), "w") as f:
            f.write("<tvshow><title>Harbor Lights</title><plot>A small town by the sea.</plot><genre>Drama</genre>"
                    "<genre>Mystery</genre><premiered>2019-09-02</premiered><studio>Northwind</studio></tvshow>")
        ep = tests.video(os.path.join(folder, "Season 1", "Harbor Lights S01E01.mp4"))
        with open(ep[:-4] + ".nfo", "w") as f:
            f.write("<episodedetails><title>The Fog</title><plot>It rolls in.</plot><aired>2019-09-02</aired></episodedetails>")
        self.assertEqual(sidecars.show(folder), {"summary": "A small town by the sea.", "genres": ["Drama", "Mystery"],
                                                 "premiered": "2019-09-02", "network": "Northwind"})
        side = sidecars.read(ep)
        self.assertEqual((side["title"], side["summary"], side["date"]), ("The Fog", "It rolls in.", "2019-09-02"))
