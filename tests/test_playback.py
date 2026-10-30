"""How video is played on a device: what it can decode, and how big a picture to convert to."""
import unittest

import tests
from sofa import config, machine, media

assert tests.ROOT

HEVC10 = {"codec": "hevc", "pix_fmt": "yuv420p10le", "profile": "Main 10", "height": 1080}
HEVC8 = {"codec": "hevc", "pix_fmt": "yuv420p", "profile": "Main", "height": 1080}


class Capabilities(unittest.TestCase):
    def test_hevc10_needs_its_own_yes(self):
        both = media.caps_from({"hevc": ["1"], "hevc10": ["1"]})
        main_only = media.caps_from({"hevc": ["1"], "hevc10": ["0"]})
        self.assertTrue(media.video_playable(HEVC10, both))
        self.assertFalse(media.video_playable(HEVC10, main_only))
        self.assertTrue(media.video_playable(HEVC8, main_only))

    def test_older_apps_that_dont_say(self):
        caps = media.caps_from({"hevc": ["1"], "mkv": ["1"]})       # no "hevc10": HEVC means both, as before
        self.assertNotIn("hevc10", caps)
        self.assertTrue(media.video_playable(HEVC10, caps))
        self.assertFalse(media.video_playable(HEVC10, media.caps_from({})))


class LivePictureSize(unittest.TestCase):
    def setUp(self):
        config.update({"gentle": True})
        machine._live.clear()
        machine._live.update(key=machine._key(), kinds={})

    def tearDown(self):
        config.update({"gentle": "auto"})

    def test_steps_down_where_it_couldnt_keep_up(self):
        kind = machine.live_kind(HEVC10)
        self.assertIn("hevc10-1080", kind)
        self.assertEqual(media.live_size(HEVC10), (720, kind))           # gentle mode: 720p to begin with
        machine.note_live_speed(kind, 720, 0.8)                         # an old Mac: slower than it plays
        self.assertEqual(media.live_size(HEVC10)[0], 540)
        machine.note_live_speed(kind, 540, 1.9)
        self.assertEqual(media.live_size(HEVC10)[0], 540)
        self.assertEqual(media.live_size(HEVC8)[0], 720)                # another kind of video isn't affected

    def test_someones_own_choice_wins(self):
        machine.note_live_speed(machine.live_kind(HEVC10), 720, 0.5)
        self.assertEqual(media.live_size(HEVC10, 720), (720, None))
        self.assertEqual(media.live_size({"codec": "mpeg4", "height": 480}, 1080)[0], 480)   # never bigger than the file

    def test_faster_x264_settings(self):
        args = media.h264_args(720)
        if "libx264" in args:
            self.assertNotIn("zerolatency", args)                       # it turns off x264's frame threads
            self.assertIn("superfast", args)


if __name__ == "__main__":
    unittest.main()
