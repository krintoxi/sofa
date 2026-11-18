"""Repackaged video (the picture copied as it is, as for an MKV in a browser) can only start on a keyframe. Asked to
start at 5.03 seconds in a file with a keyframe every 2 seconds, it starts at the one before: Sofa says so, and the
stream's first picture is the file's picture there, so the player's clock, the subtitles and a room watching together
count from the right place. (A file's pictures often start a few hundredths of a second in, as here with Mac's
ffmpeg: keyframes at 0.023, 2.023, 4.023 and so on. Those are the places a player counts in, so the test reads them
from the file itself rather than writing them down.)"""
import json
import os
import subprocess
import threading
import time
import unittest

from tests import LIBRARY
from tests.test_access import Client
from sofa import auth, media, store, web
from sofa.library import LIBRARY as LIB


def frame(path, at=None):
    """One picture, small and grey, as bytes: the file's at `at` seconds (decoded exactly there), or its first."""
    cmd = [media.tool("ffmpeg"), "-v", "error"] + (["-ss", "%.3f" % at] if at is not None else []) + \
          ["-i", path, "-frames:v", "1", "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"]
    return subprocess.run(cmd, capture_output=True, check=True).stdout


def keyframes(path):
    """Every keyframe's place in a file's video (seconds from its start), read the long way: every packet."""
    out = subprocess.run([media.tool("ffprobe"), "-v", "error", "-of", "json", "-show_entries", "format=start_time",
                          "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags", path], capture_output=True, text=True).stdout
    data = json.loads(out)
    s0 = float(data["format"].get("start_time") or 0)
    return sorted(float(p["pts_time"]) - s0 for p in data["packets"] if "K" in p["flags"])


@unittest.skipUnless(media.tool("ffmpeg") and media.tool("ffprobe"), "needs ffmpeg")
class RepackagedStart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(LIBRARY, "Movies", "Keyframes (2022)", "Keyframes (2022).flv")
        os.makedirs(os.path.dirname(cls.path), exist_ok=True)
        subprocess.run([media.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=30", "-f", "lavfi", "-i", "sine=duration=30",
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "50", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                        cls.path], check=True)
        LIB.scan("tests")
        cls.item = next(i for k, i in LIB.items.items() if "keyframes" in k)
        cls.kfs = keyframes(cls.path)
        assert len(cls.kfs) == 15, cls.kfs                      # (one every 2 seconds for 30 seconds)

    def before(self, t):
        return max(k for k in self.kfs if k <= t + 0.001)

    def test_the_keyframe_before_a_place(self):
        k4 = self.kfs[2]                                         # the third: about 4 seconds in
        self.assertTrue(3.9 <= k4 <= 4.2, self.kfs)
        self.assertAlmostEqual(media.keyframe_before(self.path, 5.03), k4, places=3)
        self.assertAlmostEqual(media.keyframe_before(self.path, k4), k4, places=3)          # on one: that one
        self.assertAlmostEqual(media.keyframe_before(self.path, k4 - 0.01), self.kfs[1], places=3)
        self.assertAlmostEqual(media.keyframe_before(self.path, 21.9), self.before(21.9), places=3)
        self.assertIsNone(media.keyframe_before(self.path, 0))
        self.assertIsNone(media.keyframe_before("http://example.invalid/a.mkv", 10))

    def test_the_stream_starts_where_sofa_says(self):
        sid = media.hls_start(self.item, "remux", 5.03, "test")
        try:
            self.assertAlmostEqual(media.hls_from(sid), self.kfs[2], places=3)
            folder = os.path.join(media.hls_dir(), sid)
            end = time.time() + 20
            while time.time() < end and not os.path.exists(os.path.join(folder, "seg00001.m4s")):
                time.sleep(0.2)
            with open(os.path.join(folder, "init.mp4"), "rb") as a, open(os.path.join(folder, "seg00000.m4s"), "rb") as b, \
                    open(os.path.join(folder, "first.mp4"), "wb") as out:
                out.write(a.read() + b.read())                    # (a segment plays after its init part)
            got = frame(os.path.join(folder, "first.mp4"))
            self.assertEqual(got, frame(self.path, self.kfs[2] - 0.01))   # the file's picture at that keyframe
            self.assertNotEqual(got, frame(self.path, self.kfs[2] + 1))
        finally:
            media.hls_stop(sid)
        # converting (not copying) starts where it's asked: nothing to say
        sid = media.hls_start(self.item, "transcode", 5.03, "test", max_height=180)
        try:
            self.assertEqual(media.hls_from(sid), 5.03)
        finally:
            media.hls_stop(sid)

    def test_the_route_says_where(self):
        httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            if not store.q1("SELECT 1 FROM users WHERE name = ?", "rs-viewer"):
                auth.create_user("rs-viewer", "password123")
            c = Client("http://127.0.0.1:%d" % httpd.server_address[1])
            self.assertEqual(c.call("/api/login", {"name": "rs-viewer", "password": "password123"})[0], 200)
            status, h = c.call("/api/hls/%s?mode=remux&t=9.5" % self.item["id"].replace(":", "%3A"))
            self.assertEqual(status, 200, h)
            self.assertAlmostEqual(h["start"], self.before(9.5), places=3)
            media.hls_stop(h["session"])
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
