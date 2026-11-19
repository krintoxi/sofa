"""An ffmpeg that draws purple lines across every picture it resizes (one built without the assembler, on a
processor without AVX2): Sofa notices with a gray picture, asks that ffmpeg in the way that's right, and makes
again, once, the clips and seek-bar pictures made before it knew.

The ffmpeg here is a stand-in around the real one. It spoils the colours of whatever it resizes unless it's told
-cpuflags, as the faulty build does. What that proves: Sofa's check, the commands it writes and the making again.
That -cpuflags -mmxext puts the real faulty build right was measured on the computer that has it (CHANGES.md)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import config, media, optimize, previews, trickplay

REAL = shutil.which("ffmpeg")
STAND_IN = '''#!%s
import os, sys
args = sys.argv[1:]
if "-cpuflags" in args:                       # asked the right way: the real ffmpeg, as it is
    n = args.index("-cpuflags")
    del args[n:n + 2]
else:                                         # resizing spoils the colours
    args = [a.replace("scale=", "lutyuv=u=255:v=255,scale=") if "scale=" in a else a for a in args]
os.execv(%r, [%r] + args)
'''


def colour(path):
    """The two colour values (U, V) of the top left of a video's or picture's first frame (a sheet's first picture):
    128, 128 is gray."""
    raw = subprocess.run([REAL, "-v", "error", "-i", path, "-frames:v", "1", "-vf", "crop=160:90:0:0,scale=16:16",
                          "-pix_fmt", "yuv444p", "-f", "rawvideo", "-"], capture_output=True, timeout=60).stdout
    return sum(raw[256:512]) / 256, sum(raw[512:768]) / 256


@unittest.skipUnless(REAL and shutil.which("ffprobe") and os.name != "nt", "needs ffmpeg")
class Striped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.folder = os.path.join(cls.dir, "bin")
        os.makedirs(cls.folder)
        with open(os.path.join(cls.folder, "ffmpeg"), "w") as f:
            f.write(STAND_IN % (sys.executable, REAL, REAL))
        os.chmod(os.path.join(cls.folder, "ffmpeg"), 0o755)
        os.symlink(shutil.which("ffprobe"), os.path.join(cls.folder, "ffprobe"))
        # a gray video bigger than a clip or a sheet, so both are resized
        cls.video = os.path.join(cls.dir, "gray.mkv")
        subprocess.run([REAL, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=1280x720:r=12:d=70",
                        "-c:v", "mpeg4", "-q:v", "8", "-g", "12", cls.video], check=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.saved = (config.get("ffmpeg"), previews.CACHE, trickplay.CACHE, media._encoders)
        config.update({"ffmpeg": self.folder})
        media._steady.clear()
        media._encoders = None
        previews.CACHE, trickplay.CACHE = tempfile.mkdtemp(dir=self.dir), tempfile.mkdtemp(dir=self.dir)
        previews._failed.clear()
        trickplay._failed.clear()

    def tearDown(self):
        config.update({"ffmpeg": self.saved[0]})
        previews.CACHE, trickplay.CACHE, media._encoders = self.saved[1:]
        media._steady.clear()

    def test_the_gray_picture_finds_it_and_the_way_round_it(self):
        self.assertEqual(media.tool("ffmpeg"), os.path.join(self.folder, "ffmpeg"))
        self.assertIs(media._resizes_right(media.tool("ffmpeg"), []), False)
        self.assertEqual(media.steady(), ["-cpuflags", "-mmxext"])
        self.assertTrue(media.striped())
        config.update({"ffmpeg": self.saved[0]})            # an ffmpeg that resizes right is asked as it always was
        media._steady.clear()
        self.assertEqual(media.steady(), [])
        self.assertFalse(media.striped())

    def test_an_ffmpeg_that_cant_be_asked_is_left_alone(self):
        self.assertIsNone(media._resizes_right(os.path.join(self.dir, "no such ffmpeg"), []))
        self.assertIsNone(media._resizes_right("/usr/bin/true", []))        # (says nothing: no verdict, no option)

    def test_a_clip_and_a_sheet_come_out_in_their_colours(self):
        item = {"path": self.video, "id": "gray", "title": "Gray"}
        self.assertTrue(previews.make(item))
        self.assertTrue(trickplay.make(item))
        for made in (previews.clip(item), trickplay.sheet(item, 0)):
            u, v = colour(made)
            self.assertTrue(120 < u < 136 and 120 < v < 136, (made, u, v))

    def test_without_the_option_this_test_would_see_the_lines(self):
        item = {"path": self.video, "id": "gray", "title": "Gray"}
        media._steady[(media.tool("ffmpeg"), os.path.getmtime(media.tool("ffmpeg")))] = []     # as Sofa asked before
        self.assertTrue(previews.make(item))
        self.assertTrue(trickplay.make(item))
        for made in (previews.clip(item), trickplay.sheet(item, 0)):
            u, v = colour(made)
            self.assertTrue(u > 200 and v > 200, (made, u, v))

    def test_every_command_that_resizes_asks_that_way(self):
        info = media.probe(self.video)
        cmd, _how = optimize.build_command(self.video, os.path.join(self.dir, "out.mp4"), info)
        self.assertEqual(cmd[1:3], ["-cpuflags", "-mmxext"])
        play = media.stream_command({"path": self.video, "id": "gray", "ext": "mkv"}, "transcode", 0, info)
        self.assertEqual(play[1:3], ["-cpuflags", "-mmxext"])
        still = os.path.join(self.dir, "still.jpg")
        self.assertTrue(media.extract_frame(self.video, still, at=5))
        u, v = colour(still)
        self.assertTrue(120 < u < 136 and 120 < v < 136, (u, v))

    def test_what_was_made_before_is_made_again_once(self):
        old_clip = os.path.join(previews.CACHE, "0123456789abcdef0123.mp4")
        old_sheets = os.path.join(trickplay.CACHE, "0123456789abcdef0123")
        os.makedirs(old_sheets)
        for p in (old_clip, os.path.join(old_sheets, "sheet000.jpg"), os.path.join(trickplay.CACHE, trickplay.VERSION)):
            open(p, "w").close()
        self.assertTrue(previews.again_if_striped())
        self.assertTrue(trickplay.again_if_striped())
        self.assertFalse(os.path.exists(old_clip))
        self.assertFalse(os.path.exists(old_sheets))
        self.assertTrue(os.path.exists(os.path.join(trickplay.CACHE, trickplay.VERSION)))     # (its own mark stays)
        item = {"path": self.video, "id": "gray", "title": "Gray"}
        self.assertTrue(previews.make(item))
        self.assertTrue(trickplay.make(item))
        self.assertFalse(previews.again_if_striped())                                      # once: the new ones stay
        self.assertFalse(trickplay.again_if_striped())
        self.assertTrue(previews.clip(item))
        self.assertTrue(trickplay.sheet(item, 0))

    def test_an_ffmpeg_that_resizes_right_keeps_what_it_made(self):
        config.update({"ffmpeg": self.saved[0]})
        media._steady.clear()
        old_clip = os.path.join(previews.CACHE, "0123456789abcdef0123.mp4")
        old_sheets = os.path.join(trickplay.CACHE, "0123456789abcdef0123")
        os.makedirs(old_sheets)
        open(old_clip, "w").close()
        self.assertFalse(previews.again_if_striped())
        self.assertFalse(trickplay.again_if_striped())
        self.assertTrue(os.path.exists(old_clip))
        self.assertTrue(os.path.isdir(old_sheets))


if __name__ == "__main__":
    unittest.main()
