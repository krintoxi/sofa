"""Putting the Sofa app on a Fire TV over the network (sofa/adb.py, sofa/apps.py), against a pretend
Fire TV that checks the protocol, the signatures and the key the way a real one does."""
import io
import json
import os
import time
import unittest
import zipfile

import tests
from sofa import adb, apps
from tests.fake_firetv import FakeFireTV, decode_public_key, verify

assert tests.ROOT


def fake_apk(size=300 * 1024):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00")
        z.writestr("classes.dex", os.urandom(size))           # random: doesn't compress, so it's really this big
    return out.getvalue()


def wait(ip, seen=None, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = apps.install_status(ip)
        if seen is not None:
            seen.add(s["state"])
        if s["state"] in ("done", "failed"):
            return s
        time.sleep(0.05)
    raise AssertionError("the install didn't finish")


class FireTvInstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.apk = fake_apk()
        os.makedirs(os.path.dirname(apps.FIRETV_APK), exist_ok=True)
        with open(apps.FIRETV_APK, "wb") as f:
            f.write(cls.apk)
        with open(apps.FIRETV_INFO, "w") as f:
            json.dump({"version": 7, "size": len(cls.apk), "at": 1}, f)
        cls.key = adb.key()                     # made once (a few seconds), then kept

    def tearDown(self):
        adb.PORT = 5555
        apps._jobs.clear()

    def test_key_is_one_adbd_accepts(self):
        n, e = decode_public_key(adb.public_key(self.key).rstrip(b"\x00"))
        self.assertEqual((n, e), (self.key["n"], 65537))
        self.assertEqual(n.bit_length(), 2048)
        token = os.urandom(20)
        self.assertTrue(verify(n, e, token, adb.sign(self.key, token)))
        self.assertEqual(adb.key(), self.key)                 # kept, not made again

    def test_install_asks_once_then_remembers(self):
        for maxdata in (4096, 256 * 1024):
            with self.subTest(maxdata=maxdata):
                tv = FakeFireTV(maxdata=maxdata)
                adb.PORT = tv.port
                seen = set()
                self.assertTrue(apps.start_install("127.0.0.1", "leo"))
                s = wait("127.0.0.1", seen)
                self.assertEqual(s["state"], "done", s.get("message"))
                self.assertIn("approve", seen)                # the TV asked "Allow?"
                self.assertEqual(tv.installed[apps.PACKAGE], self.apk)
                self.assertIn("am start -n " + apps.ACTIVITY, tv.commands)
                self.assertEqual(tv.files, {})                # the copy in /data/local/tmp was removed
                apps._jobs.clear()
                apps.start_install("127.0.0.1", "leo")        # an update: no question this time
                self.assertEqual(wait("127.0.0.1")["state"], "done")
                self.assertEqual(tv.asked, 1)
                tv.close()

    def test_not_allowed(self):
        tv = FakeFireTV(approve=False)
        adb.PORT = tv.port
        apps.start_install("127.0.0.1", "leo")
        s = wait("127.0.0.1")
        self.assertEqual(s["state"], "failed")
        self.assertIn("didn't allow", s["message"])
        self.assertEqual(tv.installed, {})
        tv.close()

    def test_adb_debugging_off(self):
        tv = FakeFireTV()
        adb.PORT = tv.port
        tv.close()                                            # nothing listening there now
        apps.start_install("127.0.0.1", "leo")
        s = wait("127.0.0.1")
        self.assertEqual(s["state"], "failed")
        self.assertIn("ADB debugging", s["message"])


if __name__ == "__main__":
    unittest.main()
