"""Sofa Box OS 1.1.106: report PCZ2UC said Sofa's page had two files not found (404) and not which, so nothing could
be done about them. A failed load now names its address, and a report keeps the name of a Sofa or box route
(/api/pair/…, /box/api/info) where it used to keep only the first folder (/api/…). Titles, ids and keys after it
stay out, as they always have."""
import collections
import importlib.util
import os
import sys
import unittest

from tests.test_box_apps_close import load

BOX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "sofa-box")


@unittest.skipIf(os.name == "nt", "the box is Linux")
class WhichFileWasMissing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = load("sofa-box-agent", SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0")

    def test_the_routes_name_and_nothing_after_it(self):
        s = self.agent.scrub
        self.assertEqual(s("http://sofa-1.localhost:8091/api/pair/start"), "http://sofa-1.localhost:8091/api/pair/…")
        self.assertEqual(s("http://sofa-1.localhost:8091/api/item/abc123?t=9"), "http://sofa-1.localhost:8091/api/item/…")
        self.assertEqual(s("http://127.0.0.1:8091/box/api/info"), "http://127.0.0.1:8091/box/api/info")
        self.assertEqual(s("http://127.0.0.1:8091/box/api/weather?city=Leeds"), "http://127.0.0.1:8091/box/api/weather/…")
        self.assertEqual(s("http://sofa-1.localhost:8091/api"), "http://sofa-1.localhost:8091/api")
        # (as before, for everything else: the site and its first folder)
        self.assertEqual(s("https://www.youtube.com/watch?v=abc123"), "https://www.youtube.com/watch/…")
        self.assertEqual(s("http://sofa-1.localhost:8091/?tv=1"), "http://sofa-1.localhost:8091//…")
        self.assertEqual(s("http://sofa-1.localhost:8091/client/Some%20Film.jpg"), "http://sofa-1.localhost:8091/client/…")

    def test_a_failed_load_says_which_file(self):
        sys.path.insert(0, BOX)
        try:
            spec = importlib.util.spec_from_file_location("boxos_routes", os.path.join(BOX, "boxos.py"))
            boxos = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(boxos)
        finally:
            sys.path.remove(BOX)
        b = boxos.Browser.__new__(boxos.Browser)
        b.notes, b.tabs = collections.deque(maxlen=150), {"t": {"session": "s1", "app": "sofa"}}
        e = {"entry": {"level": "error", "source": "network", "url": "http://sofa-1.localhost:8091/api/pair/start",
                       "text": "Failed to load resource: the server responded with a status of 404 (Not Found)"}}
        b._note("Log.entryAdded", e, "s1")
        b._note("Log.entryAdded", e, "s1")
        self.assertEqual(len(b.notes), 1)
        line = self.agent.scrub(b.notes[0])
        self.assertTrue(line.endswith("404 (Not Found) http://sofa-1.localhost:8091/api/pair/… (×2)"), line)


if __name__ == "__main__":
    unittest.main()
