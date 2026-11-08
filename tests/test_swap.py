"""Updates switch Sofa's code by renames (sofa/swap.py): cut off at any point, the version before comes back whole."""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import config, swap, updater

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = ["sofa", "client", "sofa.py", "README.md"]


def tree(path):
    """Every file under path, with its contents (what a version is, for these tests)."""
    out = {}
    for d, dirs, files in os.walk(path):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            p = os.path.join(d, f)
            with open(p, encoding="utf-8") as fh:
                out[os.path.relpath(p, path)] = fh.read()
    return out


def write(root, files):
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)


OLD = {"sofa.py": "print('old')\n", "sofa/__init__.py": '__version__ = "1.0"\n', "sofa/web.py": "old = 1\n",
       "client/app.js": "// old\n", "README.md": "old\n", "data/config.json": "{}\n"}
NEW = {"sofa.py": "print('new')\n", "sofa/__init__.py": '__version__ = "2.0"\n', "sofa/web.py": "new = 2\n",
       "sofa/added.py": "x = 1\n", "client/app.js": "// new\n", "client/new.css": "a{}\n", "README.md": "new\n",
       "docs/new.md": "a new part of the code\n"}


class Cut(Exception):
    """The power going off."""


class Swap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app, self.src = os.path.join(self.tmp, "app"), os.path.join(self.tmp, "src")
        write(self.app, OLD)
        write(self.src, NEW)
        self.names = NAMES + ["docs"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def code(self):
        return {k: v for k, v in tree(self.app).items() if not k.startswith(("data/", ".sofa-"))}

    def test_a_swap_switches_everything_and_leaves_nothing_behind(self):
        swap.stage(self.app, self.src, self.names)
        self.assertEqual(tree(self.app)["sofa.py"], OLD["sofa.py"])         # (staged: nothing of the old touched)
        swap.swap(self.app)
        swap.commit(self.app)
        self.assertEqual(self.code(), NEW)
        self.assertEqual(tree(self.app)["data/config.json"], "{}\n")
        self.assertEqual(sorted(os.listdir(self.app)), ["README.md", "client", "data", "docs", "sofa", "sofa.py"])

    def test_undo_after_a_swap(self):
        swap.stage(self.app, self.src, self.names)
        swap.swap(self.app)
        self.assertTrue(swap.undo(self.app))
        self.assertEqual(self.code(), {k: v for k, v in OLD.items() if not k.startswith("data/")})
        self.assertEqual(sorted(os.listdir(self.app)), ["README.md", "client", "data", "sofa", "sofa.py"])
        self.assertFalse(swap.undo(self.app))                              # (nothing left to undo)

    def _cut_after(self, n, fn, *args):
        """Run fn with the power going off after its n-th rename, replace or link."""
        calls = [0]
        real = {name: getattr(os, name) for name in ("rename", "replace", "link")}

        def counted(name):
            def f(*a, **k):
                if calls[0] >= n:
                    raise Cut()
                calls[0] += 1
                return real[name](*a, **k)
            return f
        with mock.patch.object(swap.os, "rename", counted("rename")), \
                mock.patch.object(swap.os, "replace", counted("replace")), \
                mock.patch.object(swap.os, "link", counted("link")):
            try:
                fn(*args)
                return False
            except Cut:
                return True

    def test_cut_off_anywhere_the_version_before_comes_back_whole(self):
        old_code = {k: v for k, v in OLD.items() if not k.startswith("data/")}
        n = 0
        while True:
            shutil.rmtree(self.app)
            write(self.app, OLD)
            swap.stage(self.app, self.src, self.names)
            if not self._cut_after(n, swap.swap, self.app):
                break                                                     # (the swap got all the way through)
            self.assertTrue(os.path.isfile(os.path.join(self.app, "sofa.py")), "a start finds sofa.py (cut at %d)" % n)
            # the next start: and that cut off too, at every point, before a start after it
            m = 0
            while self._cut_after(m, swap.recover, self.app):
                m += 1
                self.assertTrue(os.path.isfile(os.path.join(self.app, "sofa.py")))
                self.assertLess(m, 50)
            swap.recover(self.app)
            self.assertEqual(self.code(), old_code, "cut after %d renames" % n)
            self.assertEqual(sorted(os.listdir(self.app)), ["README.md", "client", "data", "sofa", "sofa.py"])
            n += 1
        self.assertGreater(n, 5)
        swap.commit(self.app)                                             # (the new version's test start passed)
        swap.recover(self.app)
        self.assertEqual(self.code(), NEW)

    def test_a_cut_while_deleting_the_old_copy_keeps_the_new_version(self):
        swap.stage(self.app, self.src, self.names)
        swap.swap(self.app)
        os.rename(os.path.join(self.app, swap.OLD), os.path.join(self.app, swap.DONE))    # (cut right after this)
        swap.recover(self.app)
        self.assertEqual(self.code(), NEW)
        self.assertFalse(any(n.startswith(".sofa-") for n in os.listdir(self.app)))

    def test_sofa_py_puts_the_version_before_back_at_its_start(self):
        """End to end: sofa.py serve, started on a box whose update was cut off with sofa/ moved aside."""
        for name in ("sofa.py", "sofa/swap.py"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                text = f.read()
            write(self.app, {name: text})
            write(self.src, {name: text})
        before = self.code()
        swap.stage(self.app, self.src, self.names)
        # cut off right after sofa/ was moved aside: sofa.py is the new one, and there's no sofa/ at all
        k = 0
        while True:
            shutil.rmtree(self.app)
            write(self.app, {**OLD, **{k2: v for k2, v in before.items()}})
            swap.stage(self.app, self.src, self.names)
            self.assertTrue(self._cut_after(k, swap.swap, self.app))
            if not os.path.isdir(os.path.join(self.app, "sofa")):
                break
            k += 1
        data = os.path.join(self.tmp, "data")
        os.makedirs(data)
        with open(os.path.join(data, "update-check.json"), "w") as f:
            json.dump({"from": "1.0", "to": "2.0", "starts": 0}, f)
        r = subprocess.run([sys.executable, os.path.join(self.app, "sofa.py"), "serve"], capture_output=True, text=True,
                           timeout=60, env=dict(os.environ, SOFA_DATA=data, PYTHONPATH=""), cwd=self.tmp)
        self.assertIn("the version before was put back", r.stdout)
        self.assertEqual(self.code(), before)
        self.assertFalse(any(n.startswith(".sofa-") for n in os.listdir(self.app)))
        self.assertFalse(os.path.exists(os.path.join(data, "update-check.json")))


class Updater(unittest.TestCase):
    """Sofa's own Update button, on a download install: staged, checked, switched; a failed check changes nothing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = os.path.join(self.tmp, "app")
        write(self.app, {"sofa.py": "print('old')\n", "sofa/__init__.py": '__version__ = "1.0"\n', "README.md": "old\n"})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tarball(self, files, sha="ab" * 20):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": sha}) as tar:
            for rel, text in files.items():
                data = text.encode()
                info = tarfile.TarInfo("sofa-main/" + rel)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    def run_update(self, files):
        with mock.patch.object(config, "APP_DIR", self.app), \
                mock.patch.object(updater, "_get", lambda url, timeout=20: self.tarball(files)), \
                mock.patch.object(updater, "_repo", lambda: ("krintoxi/sofa", "main")):
            return updater._update_download()

    def test_a_download_is_switched_in_and_says_its_commit(self):
        sha = self.run_update({"sofa.py": "print('new')\n", "sofa/__init__.py": '__version__ = "2.0"\n', "README.md": "new\n"})
        self.assertEqual(sha, "ab" * 20)                                   # (from the download, not GitHub's API)
        self.assertEqual(tree(self.app)["sofa.py"], "print('new')\n")
        self.assertTrue(os.path.isdir(os.path.join(self.app, swap.OLD)))   # (kept until the test start passes)
        with mock.patch.object(config, "APP_DIR", self.app):
            updater._go_back(None, None)                                  # the test start failed: back it goes
        self.assertEqual(tree(self.app)["sofa.py"], "print('old')\n")
        self.assertEqual(sorted(os.listdir(self.app)), ["README.md", "sofa", "sofa.py"])

    def test_code_that_doesnt_compile_never_touches_the_old_version(self):
        with self.assertRaises(Exception):
            self.run_update({"sofa.py": "print('new'\n", "sofa/__init__.py": '__version__ = "2.0"\n'})
        with mock.patch.object(config, "APP_DIR", self.app):
            updater._go_back(None, None)
        self.assertEqual(tree(self.app), {"sofa.py": "print('old')\n", "sofa/__init__.py": '__version__ = "1.0"\n',
                                          "README.md": "old\n"})


if __name__ == "__main__":
    unittest.main()
