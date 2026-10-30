"""The Sofa box (deploy/sofa-box): the TV remote over HDMI-CEC, read from cec-ctl's output."""
import importlib.util
import os
import unittest

import tests

assert tests.ROOT
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("sofa_box_cec", os.path.join(HERE, "deploy", "sofa-box", "sofa-box-cec.py"))
cec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cec)

MONITOR = """Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):
\tui-cmd: Up (0x01)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_RELEASED (0x45)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):
\tui-cmd: Select (0x00)
Received from TV to Playback Device 1 (0 to 4): MENU_REQUEST (0x8d):
\tmenu-req: query (0x02)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44): ui-cmd: Exit (0x0d)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):
\tui-cmd: Number 5 (0x25)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):
\tui-cmd: F1 (Blue) (0x71)
Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):
\tui-cmd: Play (0x44)
"""


class TvRemote(unittest.TestCase):
    def test_buttons_become_keys(self):
        keys = list(cec.keys_from(MONITOR.splitlines(True)))
        self.assertEqual(keys, ["KEY_UP", "KEY_ENTER", "KEY_BACK", "KEY_5", "KEY_PLAYPAUSE"])   # Blue: nothing

    def test_menu_request_is_noticed(self):
        self.assertTrue(any(cec.MENU_REQUEST.search(line) for line in MONITOR.splitlines()))


if __name__ == "__main__":
    unittest.main()
