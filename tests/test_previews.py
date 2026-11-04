"""Preview clips (cards, the banner on Home, a title's trailer when there's nothing better) have the video's
sound; a video without sound gets a clip without it."""
import os
import shutil
import subprocess
import tempfile
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import media, previews


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class Clips(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def make_video(self, name, sound):
        path = os.path.join(self.dir, name)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:r=24:d=70"]
        if sound:
            cmd += ["-f", "lavfi", "-i", "sine=f=440:d=70", "-ac", "6", "-c:a", "aac"]   # (5.1: the clip is stereo)
        subprocess.run(cmd + ["-c:v", "libx264", "-preset", "ultrafast", "-shortest", path], check=True, timeout=120)
        return path

    def test_sound_when_the_video_has_it(self):
        for name, sound in (("with sound.mkv", True), ("silent.mkv", False)):
            item = {"path": self.make_video(name, sound)}
            self.assertTrue(previews.make(item), name)
            info = media.probe(previews.clip(item))
            self.assertEqual(bool(info.get("audio")), sound, name)
            if sound:
                self.assertEqual(info["audio"][0]["channels"], 2)
            self.assertGreater(info.get("duration") or 0, 8)              # three moments of 3 seconds


if __name__ == "__main__":
    unittest.main()
