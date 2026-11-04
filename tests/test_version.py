"""Sofa's version goes up with its code: Server → Updates shows the number, and people go by it."""
import importlib.util
import os
import re
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import __version__

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("sofa_version_tool", os.path.join(ROOT, "tools", "sofa-version.py"))
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class Version(unittest.TestCase):
    def test_changes_has_this_version_first(self):
        with open(os.path.join(ROOT, "CHANGES.md"), encoding="utf-8") as f:
            first = re.search(r"^## (\d+\.\d+\.\d+)", f.read(), re.M)
        self.assertEqual(first.group(1), __version__, "CHANGES.md's newest section isn't Sofa's version")

    def test_new_code_gets_a_new_version(self):
        rec = tool.recorded()
        self.assertEqual(rec.get("version"), __version__,
                         "Sofa is %s but the code recorded is %s's: run python3 tools/sofa-version.py"
                         % (__version__, rec.get("version")))
        self.assertEqual(rec.get("code"), tool.code_hash(),
                         "Sofa's code (sofa/, client/, sofa.py) changed since %s was recorded: raise __version__ in "
                         "sofa/__init__.py, add it to CHANGES.md, then run python3 tools/sofa-version.py" % __version__)

    def test_updates_says_which_commit_and_which_box_os(self):
        from sofa import updater
        s = updater.status()
        self.assertEqual(s["current"], __version__)
        with open(os.path.join(ROOT, "deploy", "sofa-box", "VERSION"), encoding="utf-8") as f:
            self.assertEqual(s["box_os"], f.read().strip())
        if s["commit"]:                                           # (a git clone here: the commit's own date)
            self.assertRegex(s["commit_date"] or "", r"^\d{4}-\d\d-\d\dT")


if __name__ == "__main__":
    unittest.main()
