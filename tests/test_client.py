"""Checks on the app's own JavaScript (client/app.js) that need no browser."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ClickHandlers(unittest.TestCase):
    def test_every_button_the_handler_knows_reaches_it(self):
        """The page's click handlers start from the nearest element matching a list of [data-…] attributes, then
        act on t.dataset.… . A name missing from that list is a button that does nothing: Live TV's era tabs were
        (pressing 90s, or OK on it, left the guide on the 2000s)."""
        with open(os.path.join(ROOT, "client", "app.js"), encoding="utf-8") as f:
            js = f.read()
        handlers = list(re.finditer(r'\ndocument\.addEventListener\("click", e => \{\n\s*const t = e\.target\.closest\("([^"]+)"\)', js))
        self.assertGreaterEqual(len(handlers), 2)
        for m in handlers:
            listed = set(re.findall(r"\[data-([a-z0-9-]+)\]", m.group(1)))
            body = js[m.end():js.find("\n});", m.end())]
            used = {re.sub(r"[A-Z]", lambda c: "-" + c.group(0).lower(), n)
                    for n in re.findall(r"\bif \(t\.dataset\.([A-Za-z0-9]+)\)", body)}
            line = js[:m.start()].count("\n") + 2
            self.assertEqual(sorted(used - listed), [], "app.js:%d acts on these but its list leaves them out" % line)
        self.assertIn("era", {n for m in handlers for n in re.findall(r"\[data-([a-z0-9-]+)\]", m.group(1))})


class OneFunctionOneName(unittest.TestCase):
    def test_no_two_top_level_functions_share_a_name(self):
        """The app is one script: of two top-level functions with the same name, only the later one runs. From 1.3.0
        to 1.5.16 Live TV's guide (guideRows) replaced the episode guide under a season, so a show's page stopped
        with an error until Live TV's guide had been opened."""
        with open(os.path.join(ROOT, "client", "app.js"), encoding="utf-8") as f:
            names = re.findall(r"^(?:async )?function\*? ?([A-Za-z0-9_$]+)\(", f.read(), re.M)
        self.assertTrue(names)
        self.assertEqual(sorted({n for n in names if names.count(n) > 1}), [])

if __name__ == "__main__":
    unittest.main()
