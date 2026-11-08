"""What a power cut can leave behind (a Sofa box on a weak supply): Sofa still starts, and its files are whole."""
import json
import os
import shutil
import tempfile
import threading
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import config, store


class Durability(unittest.TestCase):
    def test_a_damaged_config_doesnt_stop_sofa(self):
        """config.json cut off half way (written before writes were made safe) made Sofa fail at every start."""
        real = config.CONFIG_PATH, config.DATA_DIR, config._config
        folder = tempfile.mkdtemp()
        try:
            config.DATA_DIR, config.CONFIG_PATH = folder, os.path.join(folder, "config.json")
            with open(config.CONFIG_PATH, "w") as f:
                f.write('{"name": "Living ro')
            config.load()
            self.assertEqual(config.get("name"), "Sofa")                               # it starts, as it came
            self.assertTrue(os.path.exists(config.CONFIG_PATH + ".damaged"))         # (what was there, kept)
            config.update({"name": "Living room"})
            with open(config.CONFIG_PATH) as f:
                self.assertEqual(json.load(f)["name"], "Living room")
            self.assertFalse(os.path.exists(config.CONFIG_PATH + ".tmp"))
        finally:
            config.CONFIG_PATH, config.DATA_DIR, config._config = real
            shutil.rmtree(folder, ignore_errors=True)

    def test_tables_are_made_once_per_database(self):
        """Every connection to the web server is a thread with its own database connection: the tables are made for
        the first one only (several milliseconds each on a Pi), and again for a file that was replaced."""
        path = os.path.join(config.DATA_DIR, "sofa.db")
        real = store.SCHEMA
        store.SCHEMA = real + "\nCREATE TABLE IF NOT EXISTS schema_runs (n INTEGER); INSERT INTO schema_runs VALUES (1);"
        store._ready.discard(store._key(path))

        def runs():
            box = []
            t = threading.Thread(target=lambda: box.append(store.q1("SELECT COUNT(*) AS n FROM schema_runs")["n"]))
            t.start()
            t.join()
            return box[0]
        try:
            first = runs()                                                         # a new connection: made
            for _ in range(5):
                self.assertEqual(runs(), first)                                    # the next ones: just opened
            store._ready.discard(store._key(path))                                 # (as if the file were new)
            self.assertEqual(runs(), first + 1)
        finally:
            store.SCHEMA = real
            store.ex("DROP TABLE IF EXISTS schema_runs")


if __name__ == "__main__":
    unittest.main()
