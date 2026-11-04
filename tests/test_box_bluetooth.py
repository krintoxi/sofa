"""Pairing on a Sofa Box: BlueZ asks for a yes (an Xbox controller's pairing does), and the box's helper
answers: yes while the box is looking for devices, no otherwise."""
import importlib.util
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)

BOX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "sofa-box")

FAKE = r'''#!%(python)s
import sys, time
log = open(%(log)r, "a")
for line in iter(sys.stdin.readline, ""):
    log.write("cmd " + line); log.flush()
    if line.strip() == "default-agent":
        for ask in ("\x1b[0;93m[agent]\x1b[0m Confirm passkey 123456 (yes/no): ", "[agent] Authorize service 0x1124 (yes/no): "):
            sys.stdout.write(ask); sys.stdout.flush()
            log.write("answer " + sys.stdin.readline()); log.flush()
        time.sleep(30)
'''


class PairingHelper(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = os.path.join(self.dir, "log")
        fake = os.path.join(self.dir, "bluetoothctl")
        with open(fake, "w") as f:
            f.write(FAKE % {"python": sys.executable, "log": self.log})
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        os.environ["SOFA_BOX_BLUETOOTHCTL"] = fake
        spec = importlib.util.spec_from_file_location("sofa_box_agent_bt", os.path.join(BOX, "sofa-box-agent.py"))
        self.agent = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.agent)

    def tearDown(self):
        os.environ.pop("SOFA_BOX_BLUETOOTHCTL", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def answers(self, accepting):
        helper = self.agent.PairingHelper(lambda: accepting)
        helper.start()
        for _ in range(100):
            if len(helper.said) >= 2:
                break
            time.sleep(0.05)
        with open(self.log) as f:
            return f.read()

    def test_yes_while_looking(self):
        log = self.answers(True)
        self.assertIn("cmd agent NoInputNoOutput", log)
        self.assertIn("cmd default-agent", log)
        self.assertEqual(log.count("answer yes"), 2)                 # the passkey, then the service

    def test_no_otherwise(self):
        log = self.answers(False)
        self.assertEqual(log.count("answer no"), 2)

    def test_looking_and_just_paired_count(self):
        bt = self.agent.Bluetooth()
        self.assertFalse(bt.accepting())
        bt.until = time.time() + 30
        self.assertTrue(bt.accepting())
        bt.until, bt.pairing_until = 0, time.time() + 60
        self.assertTrue(bt.accepting())


if __name__ == "__main__":
    unittest.main()
