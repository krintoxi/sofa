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


class LeavingAGame(unittest.TestCase):
    """Home (or the Xbox button held) from a game: Home came back as a white screen now and then, Sofa Craft most."""

    def browser(self, answers):
        b = boxos.Browser.__new__(boxos.Browser)
        b.tabs = {"h": {"app": "home", "session": "s", "url": "http://127.0.0.1:8091/box/home#/games"}}
        b.front, b.calls = "h", []

        def call(method, params=None, session=None, timeout=10):
            b.calls.append(method)
            if method == "Runtime.evaluate":
                a = answers.pop(0) if answers else True
                if isinstance(a, Exception):
                    raise a
                return {"result": {"value": a}}
            if method == "Target.createTarget":
                return {"targetId": "new"}
            return {}
        b.call = call
        b.activate = lambda t: (b.calls.append("activate:" + t), setattr(b, "front", t))
        b.close = lambda t: (b.calls.append("close:" + t), b.tabs.pop(t, None))
        return b

    def test_home_that_shows_is_left_alone(self):
        b = self.browser([True])
        self.assertTrue(b.revive("h", settle=0))
        self.assertEqual(b.calls, ["Runtime.evaluate"])

    def test_a_white_home_loads_again(self):
        real = boxos.time.sleep
        boxos.time.sleep = lambda s: None
        try:
            b = self.browser([False, False, True])
            self.assertTrue(b.revive("h", settle=0))
            self.assertIn("Page.reload", b.calls)
            self.assertIn("Page.setWebLifecycleState", b.calls)
            self.assertNotIn("Target.createTarget", b.calls)
            dead = self.browser([OSError("gone")] * 30)                           # never answers: a new Home
            self.assertTrue(dead.revive("h", settle=0))
            self.assertIn("close:h", dead.calls)
            self.assertIn("Target.createTarget", dead.calls)
            self.assertEqual(dead.tabs["new"]["app"], "home")
            self.assertIn("activate:new", dead.calls)
        finally:
            boxos.time.sleep = real

    def test_home_is_checked_each_time_it_comes_back(self):
        src = open(os.path.join(BOX, "boxos.py"), encoding="utf-8").read()
        home = src[src.index("    def home(self):"):src.index("    def alive(")]
        self.assertIn("target=self.revive", home)


if __name__ == "__main__":
    unittest.main()
