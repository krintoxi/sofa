"""Sofa Craft (Luanti) with a controller, and leaving a game without a white screen (Sofa Box OS 1.1.52).

On a real Pi the right stick didn't turn Sofa Craft's camera: Luanti (Debian's 5.10, an X program) hides the pointer
and puts it back in the middle of the screen every frame, turning by how far it had gone, and the box's screen (cage)
can't put an X program's pointer anywhere (no pointer constraints), so the camera stopped at the edge of the TV."""
import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")


def load(name, as_name):
    spec = importlib.util.spec_from_file_location(as_name, os.path.join(BOX, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pads = load("sofa-box-input", "sofa_box_input_craft")
boxos = load("boxos", "boxos_craft")
with open(os.path.join(BOX, "games", "games.json"), encoding="utf-8") as f:
    CATALOG = json.load(f)
CONTROLS = CATALOG["controls"]
RANGES = {0: (-32768, 32767), 1: (-32768, 32767), 3: (-32768, 32767), 4: (-32768, 32767), 2: (0, 255), 5: (0, 255)}
MID = pads.SPAN // 2


class SofaCraftControls(unittest.TestCase):
    def test_the_layout(self):
        c = CONTROLS["luanti"]
        self.assertEqual((c["left"], c["right"]), ("wasd", "look"))
        b = c["buttons"]
        self.assertEqual((b["south"], b["east"], b["north"], b["west"]), ("KEY_SPACE", "KEY_LEFTSHIFT", "KEY_I", "KEY_Q"))
        self.assertEqual(b["start"], "KEY_ESC")                                   # the menu on Start, not on B
        self.assertNotIn("KEY_ESC", [b["east"]])
        self.assertEqual((b["rt"], b["lt"]), ("BTN_LEFT", "BTN_RIGHT"))         # dig, place

    def test_b_is_held_to_sneak(self):
        m = pads.GameMap(CONTROLS["luanti"], "Xbox Wireless Controller", RANGES)
        self.assertEqual(m.feed(1, 305, 1), [("key", "KEY_LEFTSHIFT", 1)])
        self.assertEqual(m.feed(1, 305, 2), [])
        self.assertEqual(m.feed(1, 305, 0), [("key", "KEY_LEFTSHIFT", 0)])

    def test_the_right_stick_turns_the_camera(self):
        """Playing (the pointer hidden): the stick holds the pointer off the middle by its push, and the middle in
        turn, so the game reads a turn each time; let go, the pointer is back in the middle and the camera stops."""
        m = pads.GameMap(CONTROLS["luanti"], "Xbox Wireless Controller", RANGES, hidden=lambda: True)
        self.assertEqual(m.tick(1.0), [])                                         # nothing pushed
        m.feed(3, 3, 32767)                                                       # all the way right
        self.assertTrue(m.moving())
        first = m.tick(1.0)
        self.assertEqual([k for k, *_ in first], ["abs", "abs"])
        x, y = first[0][2], first[1][2]
        self.assertGreater(x, MID)
        self.assertAlmostEqual(y, MID, delta=2)
        self.assertAlmostEqual((x - MID) / pads.SPAN * 1920, 900 / 30.0, delta=1.5)   # speed/30 pixels at full push
        self.assertEqual(m.tick(1.005), [])                                       # (one move every 12 ms at most)
        self.assertEqual(m.tick(1.02), [("abs", "ABS_X", MID), ("abs", "ABS_Y", MID)])   # the middle in turn
        self.assertEqual(m.tick(1.04)[0][2], x)
        m.feed(3, 3, 9000)                                                        # pushed less: a smaller turn
        smaller = m.tick(1.06)
        smaller = smaller if smaller[0][2] != MID else m.tick(1.08)
        self.assertLess(smaller[0][2] - MID, x - MID)
        m.feed(3, 3, 0)                                                           # let go
        self.assertTrue(m.moving())                                               # (one more tick: back to the middle)
        self.assertEqual(m.tick(1.2), [("abs", "ABS_X", MID), ("abs", "ABS_Y", MID)])
        self.assertFalse(m.moving())
        self.assertEqual(m.tick(1.3), [])

    # An Xbox Wireless Controller over Bluetooth, as the kernel's plain HID driver gives it (the owner's, 045E:0B13):
    # the left stick on ABS_X and ABS_Y, the right stick on ABS_Z (2) and ABS_RZ (5), the triggers on ABS_GAS (9) and
    # ABS_BRAKE (10); every stick 0 to 65535, resting at 32768
    BT = {0: (0, 65535), 1: (0, 65535), 2: (0, 65535), 5: (0, 65535), 9: (0, 1023), 10: (0, 1023), 16: (-1, 1), 17: (-1, 1)}
    KEYS = [304, 305, 307, 308, 310, 311, 314, 315, 316, 317, 318]

    def test_which_axes_are_the_right_stick(self):
        """From what a controller says it has, never from where its sticks are as it's found (one may be held)."""
        self.assertEqual(pads.stick_axes(self.KEYS, self.BT), {2: 3, 5: 4})                      # over Bluetooth: Z and RZ, the triggers elsewhere
        self.assertEqual(pads.stick_axes(self.KEYS, RANGES), {})                                 # over a cable (xpad: RX and RY, triggers on Z and RZ): as it was
        plain = {0: (0, 255), 1: (0, 255), 2: (0, 255), 5: (0, 255)}
        self.assertEqual(pads.stick_axes(self.KEYS + [312, 313], plain), {2: 3, 5: 4})           # triggers that are buttons
        self.assertEqual(pads.stick_axes(self.KEYS, plain), {})                                  # nothing says which: as it was
        signed = {0: (-32768, 32767), 1: (-32768, 32767), 2: (-32768, 32767), 5: (-32768, 32767)}
        self.assertEqual(pads.stick_axes(self.KEYS, signed), {2: 3, 5: 4})                       # nought in the middle of Z and RZ: a stick's range
        self.assertEqual(pads.stick_axes(self.KEYS, {0: (-32768, 32767), 1: (-32768, 32767), 2: (0, 1023), 5: (0, 1023)}), {})   # triggers alone
        self.assertEqual(pads.stick_axes(self.KEYS, {0: (0, 255), 1: (0, 255), 2: (0, 255)}), {})   # (only one of the two)

    def test_an_xbox_controller_over_bluetooth_turns_the_camera_and_digs(self):
        """On a real Pi 3 (1.1.60) Sofa Craft walked but its camera didn't turn and nothing could be mined: the right
        stick's axes were read as the triggers, and a stick at rest is a trigger half pulled, so dig and place were
        held down from its first move and the stick turned nothing."""
        moved = pads.stick_axes(self.KEYS, self.BT)
        ranges = {moved.get(c, c): r for c, r in self.BT.items()}
        m = pads.GameMap(CONTROLS["luanti"], "Xbox Wireless Controller", ranges, hidden=lambda: True)
        feed = lambda code, value: m.feed(3, moved.get(code, code), value)                   # (as the daemon's loop does)
        self.assertEqual(feed(2, 32768) + feed(5, 32768), [])                                 # at rest: nothing pressed
        self.assertEqual(feed(2, 65535), [])                                                  # pushed right: no button
        self.assertTrue(m.moving())
        look = m.tick(1.0)
        self.assertEqual([k for k, *_ in look], ["abs", "abs"])                              # the camera turns
        self.assertGreater(look[0][2], MID)
        feed(2, 32768)
        self.assertEqual(feed(9, 1023), [("btn", "BTN_LEFT", 1)])                             # RT digs
        self.assertEqual(feed(9, 0), [("btn", "BTN_LEFT", 0)])
        self.assertEqual(feed(10, 1023), [("btn", "BTN_RIGHT", 1)])                           # LT places
        self.assertEqual(feed(10, 0), [("btn", "BTN_RIGHT", 0)])
        self.assertEqual(feed(0, 0), [("key", "KEY_A", 1)])                                   # the left stick still walks
        # as it was: the same events, not moved, press both and turn nothing
        was = pads.GameMap(CONTROLS["luanti"], "Xbox Wireless Controller", self.BT, hidden=lambda: True)
        self.assertEqual(was.feed(3, 2, 32768) + was.feed(3, 5, 32768), [("btn", "BTN_RIGHT", 1), ("btn", "BTN_LEFT", 1)])
        self.assertFalse(was.moving())

    def test_on_home_its_right_stick_is_not_the_volume(self):
        moved = pads.stick_axes(self.KEYS, self.BT)
        pad = pads.Pad("Xbox Wireless Controller", {moved.get(c, c): r for c, r in self.BT.items()})
        self.assertEqual(pad.feed(3, moved.get(2, 2), 65535, 10.0), [])                       # the right stick, pushed right
        self.assertEqual(pad.feed(3, moved.get(5, 5), 65535, 10.1), [])
        self.assertEqual(pad.feed(3, 9, 1023, 10.2), ["VOLUP"])                               # the triggers still are
        was = pads.Pad("Xbox Wireless Controller", self.BT)
        self.assertEqual(was.feed(3, 2, 65535, 10.0), ["VOLDOWN"])                            # (as it was)

    def test_the_daemon_moves_the_axes_where_it_finds_the_controller(self):
        src = open(os.path.join(BOX, "sofa-box-input.py"), encoding="utf-8").read()
        self.assertIn("moved = GENERIC_AXES if generic else stick_axes(keys, ranges)", src)
        self.assertNotIn("info.value", src[src.index("generic = is_generic(keys, ranges)"):src.index("pads[path] = [dev")])   # (not from a reading as it's found)
        self.assertIn("ranges = {moved.get(c, c): r for c, r in ranges.items()}", src)
        self.assertIn("code = moved.get(ev.code, ev.code) if ev.type == 3 else", src)

    def test_in_its_menus_the_stick_is_a_mouse(self):
        shown = [False]
        m = pads.GameMap(CONTROLS["luanti"], "Xbox Wireless Controller", RANGES, hidden=lambda: not shown[0])
        m.feed(3, 3, 32767)
        self.assertEqual(m.tick(5.0)[0][0], "abs")
        shown[0] = True                                                           # the inventory opened
        m.tick(5.02)
        moved = m.tick(5.07)
        self.assertEqual(moved[0][:2], ("rel", "REL_X"))
        self.assertGreater(moved[0][2], 0)
        unknown = pads.GameMap(CONTROLS["luanti"], "Xbox Wireless Controller", RANGES)   # can't tell: a mouse, as before
        unknown.feed(3, 3, 32767)
        unknown.tick(9.0)
        self.assertEqual(unknown.tick(9.05)[0][:2], ("rel", "REL_X"))

    def test_the_daemon_makes_the_stick_pointer_and_asks_x(self):
        src = open(os.path.join(BOX, "sofa-box-input.py"), encoding="utf-8").read()
        self.assertIn('name="Sofa box stick pointer"', src)
        self.assertIn("hidden=xcursor.hidden", src)
        self.assertIn('elif kind == "abs":', src)
        x = pads.XCursor()
        x.dpy, x.failed_at = None, 0.0
        pads.XCursor.display = staticmethod(lambda: ":99")
        x._open = lambda: None                                                    # no X here: it says it can't tell
        self.assertIsNone(x.hidden(100.0))
        self.assertIsNone(x.hidden(100.1))                                        # (not asked again at once)


# (Leaving a game: Home coming back as a white screen, and what the box does about it, is tests/test_box_white_screen.py.)


if __name__ == "__main__":
    unittest.main()
