"""Moving files can be interrupted (a crash, a power cut, a full disk) without leaving half a file under its final
name, and the next try neither duplicates nor sets aside anything (fileops.py)."""
import errno
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tests import video
from sofa import config, fileops, organizer, store


def other_drive(real=os.rename):
    """os.rename that fails across "drives" the way it does between two disks (EXDEV)."""
    def rename(src, dest):
        if "/drive-b/" in dest and "/drive-b/" not in src:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real(src, dest)
    return rename


class Moves(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sofa-moves-")
        self.a, self.b = os.path.join(self.root, "drive-a"), os.path.join(self.root, "drive-b")
        os.makedirs(self.a)
        os.makedirs(self.b)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_crash_half_way_leaves_nothing_under_the_name(self):
        src = video(os.path.join(self.a, "Heat.1995.mkv"), size=3 * 1024 * 1024)
        dest = os.path.join(self.b, "Movies", "Heat (1995)", "Heat (1995).mkv")
        os.makedirs(os.path.dirname(dest))
        real_copy = shutil.copyfileobj

        def crash(f, g, length=0):                    # half the bytes, then the power goes
            g.write(f.read(1024 * 1024))
            raise OSError(errno.EIO, "power cut")
        with mock.patch("os.rename", other_drive()), mock.patch("shutil.copyfileobj", crash):
            with self.assertRaises(OSError):
                fileops.move(src, dest)
        self.assertFalse(os.path.exists(dest))        # never half a film under its name
        self.assertTrue(os.path.exists(src))          # the original, whole, where it was
        self.assertEqual(os.path.getsize(src), 3 * 1024 * 1024)
        with mock.patch("os.rename", other_drive()), mock.patch("shutil.copyfileobj", real_copy):
            fileops.move(src, dest)                   # the next try: done, once
        self.assertEqual(os.path.getsize(dest), 3 * 1024 * 1024)
        self.assertFalse(os.path.exists(src))
        self.assertEqual([f for f in os.listdir(os.path.dirname(dest))], ["Heat (1995).mkv"])   # no partial left

    def test_folders_across_drives_go_file_by_file(self):
        folder = os.path.join(self.a, "Show")
        video(os.path.join(folder, "Season 1", "e1.mkv"))
        video(os.path.join(folder, "Season 1", "e2.mkv"))
        with mock.patch("os.rename", other_drive()):
            fileops.move(folder, os.path.join(self.b, "Show"))
        self.assertEqual(sorted(os.listdir(os.path.join(self.b, "Show", "Season 1"))), ["e1.mkv", "e2.mkv"])
        self.assertFalse(os.path.exists(folder))

    def test_leftovers_from_a_crash_are_swept(self):
        stale = os.path.join(self.b, ".Heat (1995).mkv.sofa-partial")
        moving = os.path.join(self.b, ".Heat (1995).sofa-moving")
        video(stale)
        os.makedirs(moving)
        old = 2 * 86400
        for p in (stale, moving):
            t = os.path.getmtime(p) - old
            os.utime(p, (t, t))
        fresh = video(os.path.join(self.b, ".Other.mkv.sofa-partial"))     # still being written: left alone
        self.assertEqual(fileops.leftovers(self.b), 2)
        self.assertEqual(os.listdir(self.b), [os.path.basename(fresh)])


class InboxRetries(unittest.TestCase):
    """The Inbox filing a movie onto another drive, interrupted and run again: filed once, nothing set aside."""

    def test_filed_once_after_a_crash(self):
        drive = tempfile.mkdtemp(prefix="sofa-drive-b-")
        movies = os.path.join(drive, "drive-b", "Movies")
        os.makedirs(movies)
        src = video(os.path.join(config.path("inbox"), "Arrival.2016.1080p.mkv"), size=2 * 1024 * 1024)
        review = config.path("review")
        before = set(os.listdir(review)) if os.path.isdir(review) else set()
        real_copy = shutil.copyfileobj
        try:
            def crash(f, g, length=0):
                g.write(f.read(1024))
                raise OSError(errno.ENOSPC, "No space left on device")
            with mock.patch.object(organizer, "_new_root", lambda key: movies), mock.patch("os.rename", other_drive()), \
                    mock.patch("shutil.copyfileobj", crash), mock.patch.object(store, "log"):
                with self.assertRaises(OSError):
                    organizer._file_video(src, src)
            with mock.patch.object(organizer, "_new_root", lambda key: movies), mock.patch("os.rename", other_drive()), \
                    mock.patch("shutil.copyfileobj", real_copy), mock.patch.object(store, "log"):
                self.assertTrue(organizer._file_video(src, src))
            filed = os.path.join(movies, "Arrival (2016)", "Arrival (2016).mkv")
            self.assertEqual(os.path.getsize(filed), 2 * 1024 * 1024)
            self.assertFalse(os.path.exists(src))
            self.assertEqual(set(os.listdir(review)) if os.path.isdir(review) else set(), before)   # nothing set aside
        finally:
            shutil.rmtree(drive, ignore_errors=True)
