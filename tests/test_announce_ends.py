"""Sofa 1.5.45: Sofa's announcement on the home network ends with Sofa, however Sofa ends. A Sofa that was killed used
to leave its announcer running, and a network collected a dozen dead "Sofa (n)" that a Sofa Box listed."""
import os
import signal
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def running(marker):
    out = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if marker in line and "sh -c" not in line]


@unittest.skipIf(os.name == "nt", "Windows announces Sofa itself, for as long as Sofa runs")
class TheAnnouncer(unittest.TestCase):
    def test_it_ends_when_sofa_is_killed(self):
        marker = "%d" % (100000 + (os.getpid() * 7 + int(time.time())) % 800000)      # (a length of sleep only this test uses)
        code = ("import sys, subprocess; sys.path.insert(0, %r); from sofa import discovery; "
                "subprocess.Popen(discovery._tied(['sleep', '7%s'])); import time; time.sleep(60)") % (HERE, marker)
        sofa = subprocess.Popen([sys.executable, "-c", code], env=dict(os.environ, SOFA_DATA=os.path.join(HERE, ".no-data-here")))
        self.addCleanup(lambda: sofa.poll() is None and sofa.kill())
        end = time.time() + 10
        while time.time() < end and not running("sleep 7" + marker):
            time.sleep(0.1)
        self.assertTrue(running("sleep 7" + marker), "the stand-in announcer never started")
        os.kill(sofa.pid, signal.SIGKILL)                  # (no atexit, no stop(): killed)
        sofa.wait()
        end = time.time() + 10
        while time.time() < end and running("sleep 7" + marker):
            time.sleep(0.2)
        self.assertEqual(running("sleep 7" + marker), [])

    def test_the_real_command_is_tied(self):
        from sofa import discovery
        cmd = discovery._tied(["dns-sd", "-R", "Sofa", "_sofa._tcp", "local", "8090"])
        self.assertEqual(cmd[:2], ["sh", "-c"])
        self.assertIn("kill -0 %d" % os.getpid(), cmd[2])
        self.assertIn("dns-sd -R Sofa _sofa._tcp local 8090", cmd[2])


if __name__ == "__main__":
    unittest.main()
