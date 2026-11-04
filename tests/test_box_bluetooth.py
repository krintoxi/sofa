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



class Handoff(unittest.TestCase):
    """The setup in two scans: a new box makes its own id offline, and gives the phone on its own Wi-Fi the remote's
    address through the relay, where the phone carries on once the box is on the home Wi-Fi."""

    def test_own_id_and_the_address(self):
        conf = tempfile.mkdtemp()
        os.environ["SOFA_BOX_CONF"] = conf
        try:
            spec = importlib.util.spec_from_file_location("sofa_box_agent_handoff", os.path.join(BOX, "sofa-box-agent.py"))
            agent = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(agent)
            acct = agent.secure_remote.account()
            self.assertRegex(acct["id"], r"^[abcdefghijkmnpqrstuvwxyz23456789]{10}$")
            self.assertRegex(acct["secret"], r"^[0-9a-f]{48}$")
            self.assertTrue(acct["unregistered"])
            self.assertEqual(agent.secure_remote.account()["id"], acct["id"])          # the same one, kept
            link = "0123456789abcdef01234567"
            self.assertEqual(agent.secure_remote.handoff(link), "%s/r/%s/r/%s" % (agent.SecureRemote.SERVICE, acct["id"], link))
        finally:
            os.environ.pop("SOFA_BOX_CONF", None)
            shutil.rmtree(conf, ignore_errors=True)


class ReportNotes(unittest.TestCase):
    """Send a report: a looping clip's routine events stay out, the same message again is counted, errors stay in."""

    def test_quiet_notes(self):
        sys.path.insert(0, BOX)
        try:
            spec = importlib.util.spec_from_file_location("boxos_notes", os.path.join(BOX, "boxos.py"))
            boxos = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(boxos)
        finally:
            sys.path.remove(BOX)
        b = boxos.Browser.__new__(boxos.Browser)
        b.notes, b.tabs = __import__("collections").deque(maxlen=150), {"t": {"session": "s1", "app": "sofa"}}
        loop = {"events": [{"value": '{"event":"kEnded"}'}, {"value": '{"event":"kSeek","seek_target":0.0}'}]}
        for _ in range(5):
            b._note("Media.playerEventsAdded", loop, "s1")
        self.assertEqual(list(b.notes), [])                              # a looping preview: nothing
        err = {"errors": [{"errorType": "PipelineStatus", "code": 3}]}
        for _ in range(3):
            b._note("Media.playerErrorsRaised", err, "s1")
        self.assertEqual(len(b.notes), 1)
        self.assertTrue(b.notes[0].endswith("sofa playerErrorsRaised: PipelineStatus 3 (×3)"), b.notes[0])


if __name__ == "__main__":
    unittest.main()
