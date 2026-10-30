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


    def test_a_box_says_how_tall_it_plays(self):
        self.assertEqual(media.caps_from({"maxh": ["720"]})["maxh"], 720)
        self.assertNotIn("maxh", media.caps_from({"maxh": ["99999"]}))       # nonsense: ignored
        self.assertNotIn("maxh", media.caps_from({"maxh": ["abc"]}))

    def test_too_tall_for_the_box_is_converted_down(self):
        h264 = {"video": {"codec": "h264", "pix_fmt": "yuv420p", "profile": "High", "height": 2160}, "duration": 60,
                "audio": [{"codec": "aac", "index": 1}]}
        item = {"path": "/nowhere/film.mp4", "ext": "mp4"}
        real = media.probe
        media.probe = lambda path, **kw: h264
        try:
            p = media.plan(item, media.caps_from({"maxh": ["1080"], "mkv": ["1"]}))
            self.assertEqual((p["mode"], p["max_height"]), ("transcode", 1080))
            self.assertIn("2160p picture", " ".join(p["why"]))
            h264["video"]["height"] = 1080
            self.assertEqual(media.plan(item, media.caps_from({"maxh": ["1080"]}))["mode"], "direct")
        finally:
            media.probe = real


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

    def test_a_size_smaller_when_someone_else_is_converting_too(self):
        self.assertEqual(media.live_size(HEVC8)[0], 720)
        self.assertEqual(media.live_size(HEVC8, others=1)[0], 540)
        self.assertEqual(media.live_size(HEVC8, 480, others=1)[0], 480)      # someone's own choice stays

    def test_someones_own_choice_wins(self):
        machine.note_live_speed(machine.live_kind(HEVC10), 720, 0.5)
        self.assertEqual(media.live_size(HEVC10, 720), (720, None))
        self.assertEqual(media.live_size({"codec": "mpeg4", "height": 480}, 1080)[0], 480)   # never bigger than the file

    def test_faster_x264_settings(self):
        args = media.h264_args(720)
        if "libx264" in args:
            self.assertNotIn("zerolatency", args)                       # it turns off x264's frame threads
            self.assertIn("superfast", args)


def pgs_box(w, h, x, y, bw, bh, start, end):
    """A Blu-ray subtitle file (PGS .sup) showing a white box from `start` to `end` seconds."""
    import struct

    def seg(kind, pts, data):
        return b"PG" + struct.pack(">IIBH", int(pts * 90000), 0, kind, len(data)) + data
    line = b"\x00" + struct.pack(">H", 0xC000 | bw) + b"\x01" + b"\x00\x00"     # bw pixels of colour 1, end of line
    rle = line * bh
    show = (seg(0x16, start, struct.pack(">HHBHBBBB", w, h, 0x10, 0, 0x80, 0, 0, 1) + struct.pack(">HBBHH", 0, 0, 0, x, y)) +
            seg(0x17, start, struct.pack(">BBHHHH", 1, 0, x, y, bw, bh)) +
            seg(0x14, start, struct.pack(">BB", 0, 0) + bytes([1, 235, 128, 128, 255])) +
            seg(0x15, start, struct.pack(">HBB", 0, 0, 0xC0) + struct.pack(">I", len(rle) + 4)[1:] + struct.pack(">HH", bw, bh) + rle) +
            seg(0x80, start, b""))
    hide = (seg(0x16, end, struct.pack(">HHBHBBBB", w, h, 0x10, 1, 0x00, 0, 0, 0)) +
            seg(0x17, end, struct.pack(">BBHHHH", 1, 0, x, y, bw, bh)) + seg(0x80, end, b""))
    return show + hide


@unittest.skipUnless(media.tool("ffmpeg") and media.tool("ffprobe"), "needs ffmpeg")
class ConvertingForReal(unittest.TestCase):
    """A small file with 5.1 sound and DVD subtitles (pictures), through the real ffmpeg."""

    @classmethod
    def setUpClass(cls):
        import os
        import subprocess
        d = os.path.join(tests.ROOT, "real")
        os.makedirs(d, exist_ok=True)
        sup = os.path.join(d, "s.sup")
        with open(sup, "wb") as f:
            f.write(pgs_box(640, 360, 220, 300, 200, 40, start=0.0, end=5.0))
        cls.path = os.path.join(d, "Film (2020).mkv")
        subprocess.run([media.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "color=c=black:s=640x360:r=25:d=6",
                        "-f", "lavfi", "-i", "sine=f=440:d=6", "-i", sup,
                        "-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "flac", "-ac", "6", "-c:s", "copy", cls.path], check=True)
        cls.info = media.probe(cls.path)
        cls.item = {"id": "m:film:2020", "path": cls.path, "ext": "mkv", "title": "Film"}

    def run_ffmpeg(self, out, **kw):
        import subprocess
        cmd = media.stream_command(self.item, "remux", 0, self.info, "mp4", out=out, **kw)
        subprocess.run([cmd[0], "-y"] + cmd[1:], check=True, capture_output=True)
        return media.probe(out) or {}

    def test_picture_subtitles_are_offered_and_drawn_on(self):
        import os
        import subprocess
        subs = media.picture_subtitles(self.info)
        self.assertEqual(len(subs), 1)
        plain = os.path.join(tests.ROOT, "real", "plain.mp4")
        drawn = os.path.join(tests.ROOT, "real", "drawn.mp4")
        self.run_ffmpeg(plain, max_height=360)
        self.run_ffmpeg(drawn, max_height=360, burn=subs[0]["index"])

        def brightness(path):                          # the average of a frame at 2 s, where the subtitle is
            raw = subprocess.run([media.tool("ffmpeg"), "-v", "error", "-ss", "2", "-i", path, "-frames:v", "1",
                                  "-vf", "format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
            return sum(raw) / max(1, len(raw))
        self.assertLess(brightness(plain), 20)           # a black picture...
        self.assertGreater(brightness(drawn), brightness(plain) + 0.5)   # ...with white letters drawn on

    def test_surround_kept_for_dolby_devices(self):
        import os
        import subprocess
        folder = os.path.join(tests.ROOT, "real", "hls")
        os.makedirs(folder, exist_ok=True)
        cmd = media.stream_command(self.item, "remux", 0, self.info, "hls", out=folder, caps={"ac3": True})
        subprocess.run([cmd[0], "-y"] + cmd[1:], check=True, capture_output=True)
        a = (media.probe(os.path.join(folder, "index.m3u8")) or {}).get("audio") or [{}]
        self.assertEqual((a[0].get("codec"), a[0].get("channels")), ("eac3", 6))      # 5.1 for a TV that takes Dolby
        out = os.path.join(tests.ROOT, "real", "stereo.mp4")
        a = (self.run_ffmpeg(out, caps={}).get("audio") or [{}])[0]
        self.assertEqual((a.get("codec"), a.get("channels")), ("aac", 2))              # stereo for everyone else
        out = os.path.join(tests.ROOT, "real", "single-file.mp4")
        a = (self.run_ffmpeg(out, caps={"ac3": True}).get("audio") or [{}])[0]
        self.assertEqual(a.get("codec"), "aac")                                         # one streamed MP4: can't hold Dolby


if __name__ == "__main__":
    unittest.main()
