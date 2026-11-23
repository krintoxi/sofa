"""Sofa Box OS 1.1.105: from report PCZ2UC (a Pi 3 B+ on 1.1.104, 2026-11-23). Pairing the phone during the setup
crashed when two writes of the paired phones met (each took the other's half-written file); and the Sofa chooser kept
every Sofa it had ever found, test servers long gone among them."""
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from tests.test_box_apps_close import load


@unittest.skipIf(os.name == "nt", "the box is Linux")
class TheReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = load("sofa-box-agent", SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0")

    def test_two_writes_of_one_file_at_once(self):
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, True)
        path, errors = os.path.join(work, "phones.json"), []

        def write(n):
            try:
                for i in range(40):
                    self.agent.write_durably(path, '{"phone": %d, "at": %d}' % (n, i), 0o600)
            except Exception as exc:
                errors.append(exc)
        ts = [threading.Thread(target=write, args=(n,)) for n in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errors, [])
        with open(path) as f:
            self.assertTrue(f.read().startswith('{"phone": '))                   # (whole, from one of them)
        self.assertEqual(os.listdir(work), ["phones.json"])                       # (nothing half-written left)

    def test_a_sofa_that_stopped_answering_leaves_the_chooser(self):
        a = self.agent
        answers = {"http://10.0.0.11:8090": {"sofa": True}, "http://10.0.0.11:8797": None, "http://10.0.0.9:8791": None}
        with mock.patch.dict(a.found, {b: {"name": "Sofa"} for b in answers}, clear=True), mock.patch.object(a, "info", lambda b: answers[b]):
            a.gone.clear()
            a.forget_gone(keep=("http://10.0.0.9:8791",))
            self.assertEqual(len(a.found), 3)                                     # (one look: not yet)
            a.forget_gone(keep=("http://10.0.0.9:8791",))
            self.assertEqual(sorted(a.found), ["http://10.0.0.11:8090", "http://10.0.0.9:8791"])   # (the chosen one stays)
            answers["http://10.0.0.11:8090"] = None
            a.forget_gone()
            answers["http://10.0.0.11:8090"] = {"sofa": True}                     # (back in time: it stays)
            a.forget_gone()
            self.assertIn("http://10.0.0.11:8090", a.found)


if __name__ == "__main__":
    unittest.main()
