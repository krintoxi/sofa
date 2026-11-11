#!/usr/bin/env python3
"""Game controllers on the Sofa box (Xbox, PlayStation, 8BitDo…, over Bluetooth or a USB cable).

Their buttons become key presses on a virtual keyboard, so they work the same in Sofa's TV pages and
in mpv while a video plays:

  D-pad or left stick   arrows (repeating while held, like a remote)
  A (✕)                 OK (Enter)
  B (○), View/Select    Back
  X (□), Start/Menu     play / pause
  Y (△)                 search; while playing, subtitles
  LB, LT                10 seconds back        RB, RT   30 seconds on
  Xbox / PS button      Home

In a game that runs on the box (Games), the controller is the game's: the agent says so in GAME_FILE. Either the
game reads it itself ("pad"), or the game's "controls" (games/games.json) say what each button and stick is: keys,
and a mouse for the sticks, by the buttons' places (bottom, right, left, top), so it's the same on every controller.
Holding Home (the Xbox or PS button) for a second ends the game. Generic USB controllers (the kind with buttons
numbered 1 to 12) work too, with the usual layout of those.

Bluetooth remotes (a Fire TV remote, most "TV remote" style ones) work too. Their keys mostly reach the
box as they are; the ones the browser and mpv don't know are turned into ones they do:

  the middle button (Select)   OK (Enter)
  Home                         the box's home screen, from anywhere
  ≡ (Menu)                     the Sofa bar / an app's menu (F2)
  Back, arrows, ⏯ ⏪ ⏩          as they are

Needs python3-evdev and /dev/uinput (the installer lets the box's user use it).
"""
import ctypes
import ctypes.util
import json
import math
import os
import re
import select
import shlex
import subprocess
import sys
import threading
import time
import urllib.request

AGENT = "http://127.0.0.1:%s" % os.environ.get("SOFA_BOX_PORT", "8091")
FIRST, AGAIN = 0.42, 0.13                  # seconds before an arrow repeats, then between repeats
VOL_AGAIN = 0.2                             # (the volume, held: a little slower)
# the box's volume (its sound, whatever plays): a controller's triggers, a remote's volume keys; the agent sets it and
# shows it on the TV
VOLUME = {"VOLUP": 4, "VOLDOWN": -4, "MUTE": "mute"}
HOLD_HOME = 0.8                            # seconds Home is held to leave a game
# Home held longer, anywhere: the TV's screen starts again. It's the way out of a screen that stopped answering (one
# flat colour after a game, a page that no longer draws) that needs nothing of what's on the TV: this daemon reads the
# controllers and remotes itself, and asks systemd. Under 6 seconds, when an Xbox controller switches itself off.
# Five presses of Home in three seconds count the same, for a remote that says "pressed" and never "held". (A TV's
# own remote, over HDMI-CEC, is one of those, but its keys don't come through here: sofa-box-cec.py types them on a
# keyboard of its own, which this daemon leaves alone like the box's other keyboards. It counts Home itself.)
RESCUE_HOLD, RESCUE_TAPS, RESCUE_WINDOW = 4.0, 5, 3.0
RESCUES = os.path.join(os.environ.get("SOFA_BOX_CONF") or os.path.expanduser("~/.config/sofa-box"), "screen-restarts.log")
GAME_FILE = os.environ.get("SOFA_BOX_GAME_FILE") or os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid(), "sofa-box-game")
WEB_GAME_FILE = GAME_FILE + ".web"          # one of the box's own games in front, in the browser (the agent says)

# Linux button numbers (input-event-codes.h)
BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST = 304, 305, 307, 308
BTN_TL, BTN_TR, BTN_TL2, BTN_TR2, BTN_SELECT, BTN_START, BTN_MODE = 310, 311, 312, 313, 314, 315, 316
BTN_DPAD = {544: "KEY_UP", 545: "KEY_DOWN", 546: "KEY_LEFT", 547: "KEY_RIGHT"}
ABS_X, ABS_Y, ABS_Z, ABS_RZ, ABS_GAS, ABS_BRAKE, ABS_HAT0X, ABS_HAT0Y = 0, 1, 2, 5, 9, 10, 16, 17
ABS_RX, ABS_RY = 3, 4
BTN_THUMBL, BTN_THUMBR = 317, 318
# A generic USB controller's numbered buttons (BTN_TRIGGER, 288, and on), as the codes above: the usual layout of
# those (1 top, 2 right, 3 bottom, 4 left, then L2 R2 L1 R1, Select, Start, the sticks' clicks). Xbox-style codes:
# BTN_NORTH (307) is the left button, BTN_WEST (308) the top one (see Pad).
GENERIC = {288: BTN_WEST, 289: BTN_EAST, 290: BTN_SOUTH, 291: BTN_NORTH, 292: BTN_TL2, 293: BTN_TR2, 294: BTN_TL,
           295: BTN_TR, 296: BTN_SELECT, 297: BTN_START, 298: BTN_THUMBL, 299: BTN_THUMBR, 300: BTN_MODE}
GENERIC_AXES = {ABS_Z: ABS_RX, ABS_RZ: ABS_RY}         # (their right stick: not triggers)
KEYS = ("KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_ENTER", "KEY_BACK", "KEY_PLAYPAUSE", "KEY_SLASH",
        "KEY_REWIND", "KEY_FASTFORWARD")


KEY_A, KEY_SELECT, KEY_HOMEPAGE, KEY_BACK, KEY_MENU, KEY_COMPOSE, KEY_OK = 30, 353, 172, 158, 139, 127, 352
KEY_MUTE, KEY_VOLUMEDOWN, KEY_VOLUMEUP = 113, 114, 115
REMOTE_KEYS = {KEY_SELECT: "KEY_ENTER", KEY_OK: "KEY_ENTER", KEY_MENU: "KEY_F2", KEY_COMPOSE: "KEY_F2", KEY_HOMEPAGE: "HOME",
               KEY_VOLUMEUP: "VOLUP", KEY_VOLUMEDOWN: "VOLDOWN", KEY_MUTE: "MUTE"}
PASS = ("KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_ENTER", "KEY_BACK", "KEY_ESC", "KEY_F2", "KEY_PLAYPAUSE",
        "KEY_PLAY", "KEY_PAUSE", "KEY_REWIND", "KEY_FASTFORWARD", "KEY_NEXTSONG", "KEY_PREVIOUSSONG", "KEY_STOP",
        "KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE", "KEY_SEARCH", "KEY_BACKSPACE")


def is_remote(name, keys):
    """A TV-style remote (not a keyboard, not a game controller): it has Select, Home or Back, and no letters."""
    return not name.startswith("Sofa box") and BTN_SOUTH not in keys and KEY_A not in keys and \
        any(k in keys for k in (KEY_SELECT, KEY_HOMEPAGE, KEY_BACK, KEY_OK))


class Remote:
    """One Bluetooth remote: its key events in, the box's out (testable without one)."""

    def __init__(self, names):
        self.names = names                                  # key number -> "KEY_…" (evdev's own table)

    def feed(self, etype, code, value):
        """[(key name, value)] to send on, or [("HOME", 1)]."""
        if etype != 1:
            return []
        to = REMOTE_KEYS.get(code) or self.names.get(code)
        if to == "HOME":
            return [("HOME", 1)] if value == 1 else []
        if to in VOLUME:                                    # (held: the remote's own repeats, 2)
            return [(to, 1)] if value in (1, 2) and (to != "MUTE" or value == 1) else []
        return [(to, value)] if to in PASS else []


def is_playstation(name):
    """PlayStation pads call themselves "Wireless Controller" (so do Xbox ones, with "Xbox" first)."""
    return not re.search(r"Xbox|Microsoft|8BitDo", name, re.I) and \
        bool(re.search(r"Wireless Controller|DualSense|DualShock|PLAYSTATION|PS[345]|Sony", name, re.I))


def pad_kind(name):
    """Which kind a controller is, by its name: for the TV (its buttons' names) and the games."""
    if re.search(r"xbox|microsoft|x-box", name, re.I):
        return "xbox"
    if is_playstation(name):
        return "playstation"
    if re.search(r"8bitdo", name, re.I):
        return "8bitdo"
    if re.search(r"pro controller|joy-con|nintendo", name, re.I):
        return "nintendo"
    return "generic"


def is_generic(keys, axes):
    """A controller without the gamepad buttons' codes: numbered buttons and a stick."""
    return BTN_SOUTH not in keys and any(288 <= k <= 299 for k in keys) and ABS_X in axes


class Pad:
    """One controller: its events in, key presses out (testable without one)."""

    def __init__(self, name="", ranges=None):
        self.ranges = ranges or {}                          # axis -> (min, max)
        ps = is_playstation(name)
        # A OK, B Back, X play/pause, Y search (subtitles in the player), LB/RB back/forward, the Xbox button Home,
        # Menu (Start, Options) the options for what's in focus, LT/RT the volume (held: on and on), View Back
        self.buttons = {BTN_SOUTH: "KEY_ENTER", BTN_EAST: "KEY_BACK", BTN_SELECT: "KEY_BACK",
                        BTN_START: "KEY_F2", BTN_TL: "KEY_REWIND", BTN_TR: "KEY_FASTFORWARD", BTN_MODE: "HOME",
                        # Xbox-style drivers give X as 307; PlayStation's square is 308 (and triangle 307)
                        BTN_NORTH: "KEY_SLASH" if ps else "KEY_PLAYPAUSE", BTN_WEST: "KEY_PLAYPAUSE" if ps else "KEY_SLASH"}
        self.axes = {}
        self.dirs = {}                                      # arrow -> when it next repeats
        self.triggers = {ABS_Z: False, ABS_RZ: False, ABS_GAS: False, ABS_BRAKE: False}
        self.trigger_buttons = set()                        # (pads whose triggers are buttons, BTN_TL2 / BTN_TR2)
        self.web_game = False                               # the box's own game in front: it reads the triggers and
        #                                                     Start itself (the volume and the options stay out of it)
        self.dpad_buttons = set()

    def _level(self, code, value):
        lo, hi = self.ranges.get(code, (-32768, 32767))
        mid, half = (lo + hi) / 2.0, (hi - lo) / 2.0 or 1
        return (value - mid) / half

    def held(self):
        """The arrows held now (D-pad buttons, the hat, or the left stick past 60%)."""
        out = set(self.dpad_buttons)
        hx, hy = self.axes.get(ABS_HAT0X, 0), self.axes.get(ABS_HAT0Y, 0)
        sx, sy = self._level(ABS_X, self.axes[ABS_X]) if ABS_X in self.axes else 0, \
            self._level(ABS_Y, self.axes[ABS_Y]) if ABS_Y in self.axes else 0
        if hy < 0 or sy < -0.6:
            out.add("KEY_UP")
        if hy > 0 or sy > 0.6:
            out.add("KEY_DOWN")
        if hx < 0 or sx < -0.6:
            out.add("KEY_LEFT")
        if hx > 0 or sx > 0.6:
            out.add("KEY_RIGHT")
        if self.web_game:
            return out
        if self.triggers[ABS_Z] or self.triggers[ABS_BRAKE] or BTN_TL2 in self.trigger_buttons:
            out.add("VOLDOWN")
        if self.triggers[ABS_RZ] or self.triggers[ABS_GAS] or BTN_TR2 in self.trigger_buttons:
            out.add("VOLUP")
        return out

    def feed(self, etype, code, value, now):
        """One event; returns the keys to press now."""
        out = []
        if etype == 1:                                      # EV_KEY
            if code in BTN_DPAD:
                (self.dpad_buttons.add if value else self.dpad_buttons.discard)(BTN_DPAD[code])
            elif code in (BTN_TL2, BTN_TR2):
                (self.trigger_buttons.add if value else self.trigger_buttons.discard)(code)
            elif value == 1 and code in self.buttons and not (self.web_game and code == BTN_START):
                out.append(self.buttons[code])
        elif etype == 3:                                    # EV_ABS
            if code in self.triggers:
                lo, hi = self.ranges.get(code, (0, 255))
                self.triggers[code] = (value - lo) > 0.6 * ((hi - lo) or 1)
            else:
                self.axes[code] = value
        held = self.held()
        for k in held:
            if k not in self.dirs:
                out.append(k)
                self.dirs[k] = now + FIRST
        for k in list(self.dirs):
            if k not in held:
                del self.dirs[k]
        return out

    def next_due(self):
        """When an arrow held next repeats (None: none held)."""
        return min(self.dirs.values()) if self.dirs else None

    def due(self, now):
        """Arrows held long enough to repeat."""
        out = []
        for k, at in self.dirs.items():
            if now >= at:
                out.append(k)
                self.dirs[k] = now + (VOL_AGAIN if k in VOLUME else AGAIN)
        return out


# ---------------------------------------------------------------- in a game

STICK_KEYS = {"arrows": ("KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT"), "wasd": ("KEY_W", "KEY_S", "KEY_A", "KEY_D")}
PLACES = {BTN_SOUTH: "south", BTN_EAST: "east", BTN_TL: "lb", BTN_TR: "rb", BTN_TL2: "lt", BTN_TR2: "rt",
          BTN_SELECT: "select", BTN_START: "start", BTN_THUMBL: "l3", BTN_THUMBR: "r3"}


SPAN = 32767                                # the stick pointer's positions: 0 to SPAN across the screen


class XCursor:
    """Whether the pointer on the games' screen (XWayland) is hidden now: a game turning its camera with the mouse hides
    it, and shows it in its menus. Asked of X itself (XFixes); None when it can't be told."""

    class Image(ctypes.Structure):
        _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short), ("width", ctypes.c_ushort), ("height", ctypes.c_ushort),
                    ("xhot", ctypes.c_ushort), ("yhot", ctypes.c_ushort), ("serial", ctypes.c_ulong),
                    ("pixels", ctypes.POINTER(ctypes.c_ulong)), ("atom", ctypes.c_ulong), ("name", ctypes.c_char_p)]

    def __init__(self):
        self.dpy, self.at, self.was, self.failed_at = None, 0.0, None, 0.0

    @staticmethod
    def display():
        run_dir = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
        try:
            with open(os.path.join(run_dir, "sofa-box-display"), encoding="utf-8") as f:
                for line in f:
                    k, _, v = line.strip().partition("=")
                    if k == "DISPLAY" and v:
                        return v
        except OSError:
            pass
        return os.environ.get("DISPLAY")

    def _open(self):
        x11, xf = ctypes.util.find_library("X11"), ctypes.util.find_library("Xfixes")
        if not (x11 and xf):
            return None
        self.x, self.xf = ctypes.CDLL(x11), ctypes.CDLL(xf)
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XFree.argtypes = [ctypes.c_void_p]
        self.xf.XFixesQueryExtension.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        self.xf.XFixesGetCursorImage.restype = ctypes.POINTER(XCursor.Image)
        self.xf.XFixesGetCursorImage.argtypes = [ctypes.c_void_p]
        name = self.display()
        dpy = self.x.XOpenDisplay(name.encode() if name else None)
        if not dpy:
            return None
        a, b = ctypes.c_int(), ctypes.c_int()
        return dpy if self.xf.XFixesQueryExtension(dpy, ctypes.byref(a), ctypes.byref(b)) else None

    def hidden(self, now=None):
        now = time.time() if now is None else now
        if now - self.at < 0.25:                         # (asked four times a second at most)
            return self.was
        self.at = now
        try:
            if self.dpy is None:
                if now - self.failed_at < 5:
                    return None
                self.dpy = self._open()
                if self.dpy is None:
                    self.failed_at = now
                    return None
            img = self.xf.XFixesGetCursorImage(self.dpy)
            if not img:
                self.was = None
                return None
            im = img.contents
            n = min(int(im.width) * int(im.height), 4096)
            self.was = n == 0 or all((im.pixels[i] >> 24) & 0xFF == 0 for i in range(n))   # nothing to see: hidden
            self.x.XFree(img)
        except (OSError, AttributeError, ValueError):
            self.dpy, self.was, self.failed_at = None, None, now
        return self.was


class GameMap:
    """A controller in a game that doesn't take controllers well itself: its buttons and sticks as the game's keys
    and a mouse, as the game's "controls" say (games/games.json), by the buttons' places, so a PlayStation
    controller's ✕ is an Xbox controller's A. Held is held (a key stays down while its button is)."""

    def __init__(self, controls, name="", ranges=None, hidden=None):
        self.c, self.ranges = controls, ranges or {}
        # "look": a stick that turns a game's camera (Luanti). Such a game hides the pointer and puts it back in the
        # middle of the screen every frame, turning by how far it had gone; the box's screen (cage) can't do that for
        # an X game (no pointer constraints), so the camera stopped at the edge of the TV. Instead the stick holds the
        # pointer off the middle by how far it's pushed (an absolute pointer), and back to the middle in turn, so the
        # game reads a turn each time whether its own putting-back works or not. In its menus (the pointer showing)
        # the stick is an ordinary mouse.
        self.hidden = hidden or (lambda: None)
        self.look_at, self.flip, self.look_t = None, False, 0.0
        ps = is_playstation(name)
        self.places = dict(PLACES)
        self.places.update({BTN_NORTH: "north" if ps else "west", BTN_WEST: "west" if ps else "north"})
        self.buttons = controls.get("buttons") or {}
        self.speed = float(controls.get("mouse_speed") or 1300)  # pixels a second, the stick all the way over
        self.axes, self.down, self.dirs, self.dpad, self.frac, self.last = {}, {}, {}, set(), [0.0, 0.0], None

    def _level(self, code, value=None):
        lo, hi = self.ranges.get(code, (0, 255) if code in (ABS_Z, ABS_RZ, ABS_GAS, ABS_BRAKE) else (-32768, 32767))
        v = self.axes.get(code, (lo + hi) / 2.0) if value is None else value
        if code in (ABS_Z, ABS_RZ, ABS_GAS, ABS_BRAKE):
            return (v - lo) / float((hi - lo) or 1)
        return (v - (lo + hi) / 2.0) / (((hi - lo) / 2.0) or 1)

    @staticmethod
    def _out(name, value):
        return ("btn" if name.startswith("BTN_") else "key", name, value)

    def _button(self, place, on):
        action = self.buttons.get(place)
        if not action:
            return []
        if on and place not in self.down:
            if action in ("WHEEL_UP", "WHEEL_DOWN"):
                self.down[place] = []
                return [("rel", "REL_WHEEL", 1 if action == "WHEEL_UP" else -1)]
            self.down[place] = action.split("+")             # "KEY_LEFTCTRL+KEY_E": both, in that order
            return [self._out(k, 1) for k in self.down[place]]
        if not on and place in self.down:
            return [self._out(k, 0) for k in reversed(self.down.pop(place))]
        return []

    def _held(self, which, want):
        keys = STICK_KEYS.get(self.c.get(which))
        if not keys:
            return []
        now = {k for d, k in zip(("up", "down", "left", "right"), keys) if d in want}
        had = self.dirs.get(which, set())
        self.dirs[which] = now
        return [("key", k, 1) for k in sorted(now - had)] + [("key", k, 0) for k in sorted(had - now)]

    def _stick(self, which, ax, ay):
        x, y = self._level(ax), self._level(ay)
        had = {d for d, k in zip(("up", "down", "left", "right"), STICK_KEYS.get(self.c.get(which), ())) if k in self.dirs.get(which, set())}
        on = lambda d, v: v > (0.35 if d in had else 0.5)   # (a little less to let go: no flicker at the edge)
        return {d for d, v in (("up", -y), ("down", y), ("left", -x), ("right", x)) if on(d, v)}

    def _dpad(self):
        want = {BTN_DPAD[c].split("_")[1].lower() for c in self.dpad}
        hx, hy = self.axes.get(ABS_HAT0X, 0), self.axes.get(ABS_HAT0Y, 0)
        want |= {d for d, on in (("up", hy < 0), ("down", hy > 0), ("left", hx < 0), ("right", hx > 0)) if on}
        return want

    def feed(self, etype, code, value):
        """One event; returns [("key"|"btn", name, 1 or 0), ("rel", axis, amount)]."""
        if etype == 1:                                      # EV_KEY (2 is held: nothing new)
            if code in BTN_DPAD:
                (self.dpad.add if value else self.dpad.discard)(code)
                return self._held("dpad", self._dpad())
            place = self.places.get(code)
            return self._button(place, value != 0) if place and value != 2 else []
        if etype != 3:
            return []
        self.axes[code] = value
        if code in (ABS_HAT0X, ABS_HAT0Y):
            return self._held("dpad", self._dpad())
        if code in (ABS_Z, ABS_BRAKE, ABS_RZ, ABS_GAS):
            place = "lt" if code in (ABS_Z, ABS_BRAKE) else "rt"
            level = self._level(code)
            return self._button(place, level > (0.3 if place in self.down else 0.5))
        if code in (ABS_X, ABS_Y):
            return self._held("left", self._stick("left", ABS_X, ABS_Y))
        if code in (ABS_RX, ABS_RY):
            return self._held("right", self._stick("right", ABS_RX, ABS_RY))
        return []

    def moving(self):
        """A stick that's the mouse, pushed: the mouse moves by itself, so tick() wants calling often."""
        return self.look_at is not None or any(self.c.get(which) in ("mouse", "look") and math.hypot(self._level(ax), self._level(ay)) >= 0.15
                                               for which, (ax, ay) in (("left", (ABS_X, ABS_Y)), ("right", (ABS_RX, ABS_RY))))

    def _look(self, x, y, mag, now=0.0):
        """The stick pointer's place: off the middle by the push (up to speed/30 pixels of a 1920×1080 screen), and
        the middle every other tick; the middle once more when the stick's let go."""
        mid = SPAN // 2
        if mag < 0.15:
            if self.look_at is None:
                return []
            self.look_at = None
            return [("abs", "ABS_X", mid), ("abs", "ABS_Y", mid)]
        if now - self.look_t < 0.012:                       # (a move every 12 ms at most: one a frame or so)
            return []
        self.look_t = now
        self.flip = not self.flip
        if not self.flip:
            at = (mid, mid)
        else:
            reach = ((min(mag, 1.0) - 0.15) / 0.85) ** 1.6 * self.speed / 30.0
            at = (mid + int(x / mag * reach / 1920.0 * SPAN), mid + int(y / mag * reach / 1080.0 * SPAN))
        self.look_at = at
        return [("abs", "ABS_X", at[0]), ("abs", "ABS_Y", at[1])]

    def tick(self, now):
        """The mouse, moved by a stick that's its mouse: faster the further it's pushed."""
        if not self.moving():
            self.last = None                                # (from still, the next tick starts from now: no jump)
            return []
        dt, self.last = (0.0 if self.last is None else min(0.1, now - self.last)), now
        out = []
        for which, (ax, ay) in (("left", (ABS_X, ABS_Y)), ("right", (ABS_RX, ABS_RY))):
            kind = self.c.get(which)
            if kind not in ("mouse", "look"):
                continue
            x, y = self._level(ax), self._level(ay)
            mag = math.hypot(x, y)
            if kind == "look":
                if self.hidden():                           # playing: the camera turns
                    out += self._look(x, y, mag, now)
                    continue
                if self.look_at is not None:                # into a menu: an ordinary mouse from here
                    self.look_at = None
            if mag < 0.15:
                continue
            step = ((min(mag, 1.0) - 0.15) / 0.85) ** 1.8 * self.speed * dt
            self.frac[0] += x / mag * step
            self.frac[1] += y / mag * step
            ix, iy = int(self.frac[0]), int(self.frac[1])
            self.frac[0] -= ix
            self.frac[1] -= iy
            out += ([("rel", "REL_X", ix)] if ix else []) + ([("rel", "REL_Y", iy)] if iy else [])
        return out

    def release(self):
        """Everything let go (the game ended, or the controller went)."""
        out = [self._out(k, 0) for place in list(self.down) for k in reversed(self.down.pop(place))]
        for which in list(self.dirs):
            out += [("key", k, 0) for k in sorted(self.dirs.pop(which))]
        return out


SCAN = 3.0                                  # seconds between looks for controllers that came (Bluetooth)
GAME_CHECK = 0.5                            # seconds between looks at which game is open


class HomeKey:
    """Home, held or pressed over and over, on any controller or remote: in a game, held for HOLD_HOME it leaves the
    game; anywhere, held for RESCUE_HOLD (or RESCUE_TAPS presses within RESCUE_WINDOW) it starts the TV's screen again."""

    def __init__(self):
        self.down, self.left, self.taps, self.rescued = {}, set(), [], -1e9

    def key(self, path, value, now):
        """A Home key or button of the device at `path`: 1 down, 0 up (2, a keyboard's own repeat, says nothing new)."""
        if value == 1:
            self.down[path] = now
            self.taps = [t for t in self.taps if now - t <= RESCUE_WINDOW] + [now]
        elif value == 0:
            self.down.pop(path, None)
            self.left.discard(path)

    def gone(self, path):
        self.down.pop(path, None)
        self.left.discard(path)

    def clear(self):
        """A game opened or ended: a Home still held leaves nothing more; held on, it still starts the screen again."""
        self.left = set(self.down)

    def due(self, now, game):
        """What Home asks for now: "leave" (the game, once for each hold), "rescue" (the TV's screen again), or None."""
        held = [t for t in self.down.values() if now - t >= RESCUE_HOLD]
        taps = [t for t in self.taps if now - t <= RESCUE_WINDOW]
        if held or len(taps) >= RESCUE_TAPS:
            self.down.clear()
            self.left.clear()
            self.taps = []
            if now - self.rescued < 30:                     # (it's starting already)
                return None
            self.rescued = now
            return "rescue"
        if game:
            for path, t in self.down.items():
                if now - t >= HOLD_HOME and path not in self.left:
                    self.left.add(path)
                    return "leave"
        return None


def rescue(why):
    """The TV's screen (and the box's helper) started again by systemd; written down for the next report."""
    line = "%s the TV's screen started again (%s)" % (time.strftime("%Y-%m-%d %H:%M:%S"), why)
    print(line, file=sys.stderr, flush=True)
    try:
        os.makedirs(os.path.dirname(RESCUES), exist_ok=True)
        with open(RESCUES, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    cmd = shlex.split(os.environ.get("SOFA_BOX_RESCUE", "")) or ["sudo", "-n", "systemctl", "restart", "sofa-box", "sofa-box-agent"]
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        print("The TV's screen couldn't be started again: %s" % exc, file=sys.stderr, flush=True)


def next_wait(now, game_at, last_scan, pads, game, home_down, home_left=()):
    """How long the loop may sleep: until a held arrow repeats, a held Home leaves a game or starts the screen again,
    or the next look at the game and the controllers. Only a stick that's the mouse, pushed, needs it often (smooth).
    Idle, the box's controllers wake it twice a second (it used to be 33 times, even with nothing held)."""
    at = min(game_at + GAME_CHECK, last_scan + SCAN)
    for entry in pads.values():
        pad, gm = entry[1], entry[3]
        if gm is not None:
            if gm.moving():
                at = min(at, now + 0.012)
        elif not game:
            due = pad.next_due()
            if due is not None:
                at = min(at, due)
    for path, t in home_down.items():
        at = min(at, t + (HOLD_HOME if game and path not in home_left else RESCUE_HOLD))
    return max(0.0, at - now)


class Seen:
    """Input devices looked at already that aren't controllers or remotes (keyboards, the TV's remote over HDMI,
    the box's own devices): not opened again at every look, until they change. A device that comes back is a new
    node (another inode), and udev giving it its permissions changes its ctime: both are looked at again."""

    def __init__(self):
        self.known = {}

    @staticmethod
    def _key(path):
        st = os.stat(path)
        return st.st_ino, st.st_ctime_ns, st.st_rdev

    def new(self, paths):
        """The paths worth opening: (path, key), key for skip()."""
        out = []
        for path in paths:
            try:
                key = self._key(path)
            except OSError:
                continue
            if self.known.get(path) != key:
                out.append((path, key))
        for path in set(self.known) - set(paths):
            del self.known[path]
        return out

    def skip(self, path, key):
        self.known[path] = key


def read_game():
    """The game that's open, and its controls (None: none open)."""
    try:
        with open(GAME_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def tell_pads(pads):
    """The agent hears which controllers are connected (Games shows them, by kind)."""
    def send():
        try:
            req = urllib.request.Request(AGENT + "/box/api/pads", data=json.dumps({"pads": pads}).encode(),
                                         headers={"Content-Type": "application/json", "X-Sofa-Box": "1"})
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3).close()
        except Exception:
            pass
    threading.Thread(target=send, daemon=True).start()


def volume(by):
    """The box's volume, up or down (or mute); the agent shows it on the TV."""
    def send():
        try:
            req = urllib.request.Request(AGENT + "/box/api/volume", data=json.dumps({"by": by}).encode(),
                                         headers={"Content-Type": "application/json", "X-Sofa-Box": "1"})
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5).close()
        except Exception:
            pass
    threading.Thread(target=send, daemon=True).start()


def home():
    try:
        req = urllib.request.Request(AGENT + "/box/api/home", data=json.dumps({}).encode(),
                                     headers={"Content-Type": "application/json", "X-Sofa-Box": "1"})
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3).close()
    except Exception:
        pass


def main():
    try:
        from evdev import InputDevice, UInput, ecodes, list_devices
    except ImportError:
        sys.exit("python3-evdev is missing: sudo apt install python3-evdev")
    # every key of a keyboard, not only the ones it sends: udev calls a device a keyboard (and the screen, cage, then
    # listens to it) only when it has the whole first row of keys
    keys = set(range(ecodes.KEY_ESC, ecodes.KEY_MICMUTE + 1)) | {ecodes.ecodes[k] for k in set(KEYS) | set(PASS)}
    kb = UInput({ecodes.EV_KEY: sorted(keys)}, name="Sofa box controllers")
    ptr = [None]                                            # a mouse, for the games that want one (made when needed)
    pads, remotes, last_scan = {}, {}, 0                    # path -> [device, Pad, generic?, GameMap in a game]
    seen = Seen()
    names = {v: k for k, v in ecodes.ecodes.items() if k.startswith("KEY_")}
    game, game_at, told, told_at, hk = None, 0, None, 0, HomeKey()

    def send(name, value):
        if name == "HOME":
            return home()
        if name in VOLUME:
            return volume(VOLUME[name]) if value else None
        kb.write(ecodes.EV_KEY, ecodes.ecodes[name], value)
        kb.syn()

    def press(name):
        if name == "HOME":
            return home()
        if name in VOLUME:
            return volume(VOLUME[name])
        code = ecodes.ecodes[name]
        kb.write(ecodes.EV_KEY, code, 1)
        kb.write(ecodes.EV_KEY, code, 0)
        kb.syn()

    stick = [None]                                          # an absolute pointer, for the "look" sticks
    xcursor = XCursor()

    def stick_pointer():
        if stick[0] is None:
            stick[0] = UInput({ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT],
                               ecodes.EV_ABS: [(ecodes.ABS_X, (0, 0, SPAN, 0, 0, 0)), (ecodes.ABS_Y, (0, 0, SPAN, 0, 0, 0))],
                               ecodes.EV_REL: [ecodes.REL_WHEEL]}, name="Sofa box stick pointer")
        return stick[0]

    def pointer():
        if ptr[0] is None:
            ptr[0] = UInput({ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE],
                             ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL]}, name="Sofa box pointer")
        return ptr[0]

    def emit(events):
        to = set()
        for kind, name, value in events:
            code = ecodes.ecodes.get(name)
            if code is None:
                continue
            if kind == "key":
                kb.write(ecodes.EV_KEY, code, value)
                to.add(kb)
            elif kind == "abs":
                dev = stick_pointer()
                dev.write(ecodes.EV_ABS, code, value)
                to.add(dev)
            else:
                dev = pointer()
                dev.write(ecodes.EV_KEY if kind == "btn" else ecodes.EV_REL, code, value)
                to.add(dev)
        for dev in to:
            dev.syn()

    def controls():
        return (game or {}).get("controls")

    def take(path):
        """A controller into the game that's open: the game's controls, and nothing else gets its events."""
        entry = pads[path]
        entry[1].dirs.clear()
        if controls():
            try:
                entry[0].grab()
            except OSError:
                pass
            entry[3] = GameMap(controls(), entry[0].name, entry[4], hidden=xcursor.hidden)

    def give_back(path):
        entry = pads[path]
        if entry[3]:
            emit(entry[3].release())
            entry[3] = None
            try:
                entry[0].ungrab()
            except OSError:
                pass

    while True:
        now = time.time()
        if now - game_at >= GAME_CHECK:                     # a game opened or ended (the agent says)
            game_at = now
            web = os.path.exists(WEB_GAME_FILE)
            for entry in pads.values():
                entry[1].web_game = web
            g = read_game()
            if (g or {}).get("id") != (game or {}).get("id"):
                for path in list(pads):
                    give_back(path)
                game = g
                hk.clear()
                if game:
                    if controls() and any(v.get("left") in ("mouse", "look") or v.get("right") in ("mouse", "look") for v in [controls()]):
                        pointer()
                    if controls() and "look" in (controls().get("left"), controls().get("right")):
                        stick_pointer()                     # (a new device takes a moment to be picked up)
                    for path in list(pads):
                        take(path)
                print("Game: %s" % (game["id"] if game else "ended"), file=sys.stderr, flush=True)
        if now - last_scan >= SCAN:                         # controllers come and go (Bluetooth)
            last_scan = now
            for path, key in seen.new([p for p in list_devices() if p not in pads and p not in remotes]):
                try:
                    dev = InputDevice(path)
                    caps = dev.capabilities()
                    keys = caps.get(ecodes.EV_KEY, [])
                except OSError:
                    continue                                # (not ready yet: looked at again next time)
                if is_remote(dev.name, keys):
                    try:
                        dev.grab()                          # its keys come from here now, translated
                    except OSError:
                        continue
                    remotes[path] = (dev, Remote(names))
                    print("Remote: %s" % dev.name, file=sys.stderr, flush=True)
                    continue
                ranges = {code: (info.min, info.max) for code, info in caps.get(ecodes.EV_ABS, [])}
                generic = is_generic(keys, ranges)
                if generic:
                    ranges = {GENERIC_AXES.get(c, c): r for c, r in ranges.items()}
                if (BTN_SOUTH in keys or generic) and "Sofa box" not in dev.name:
                    pads[path] = [dev, Pad(dev.name, ranges), generic, None, ranges]
                    print("Controller: %s (%s)" % (dev.name, pad_kind(dev.name)), file=sys.stderr, flush=True)
                    if game:
                        take(path)
                else:
                    seen.skip(path, key)                    # (a keyboard, the box's own: not opened again)
                    dev.close()
            now_pads = sorted(({"name": d.name, "kind": pad_kind(d.name)} for d, *_ in pads.values()), key=lambda p: p["name"])
            if now_pads != told or now - told_at > 30:
                tell_pads(now_pads)
                told, told_at = now_pads, now
        fds = [e[0].fd for e in pads.values()] + [d.fd for d, _ in remotes.values()]
        wait = next_wait(time.time(), game_at, last_scan, pads, game, hk.down, hk.left)
        ready = select.select(fds, [], [], wait)[0] if fds else (time.sleep(wait) or [])
        now = time.time()
        for path, (dev, remote) in list(remotes.items()):
            if dev.fd in ready:
                try:
                    for ev in dev.read():
                        if ev.type == 1 and ev.code == KEY_HOMEPAGE:
                            hk.key(path, ev.value, now)     # held: leaves a game, then starts the screen again
                            if game:
                                continue
                        for name, value in remote.feed(ev.type, ev.code, ev.value):
                            send(name, value)
                except OSError:                             # asleep, or out of range: found again when it's back
                    del remotes[path]
                    hk.gone(path)
        for path, entry in list(pads.items()):
            dev, pad, generic, gm = entry[0], entry[1], entry[2], entry[3]
            if dev.fd in ready:
                try:
                    for ev in dev.read():
                        code = ev.code if not generic else GENERIC.get(ev.code, ev.code) if ev.type == 1 \
                            else GENERIC_AXES.get(ev.code, ev.code) if ev.type == 3 else ev.code
                        home_button = ev.type == 1 and code == BTN_MODE
                        if home_button:                     # held: leaves a game, then starts the screen again
                            hk.key(path, ev.value, now)
                        if game:
                            if gm and not home_button:
                                emit(gm.feed(ev.type, code, ev.value))
                            continue                        # ("pad": the game reads it itself)
                        for k in pad.feed(ev.type, code, ev.value, now):
                            press(k)
                except OSError:                             # switched off or out of range
                    if gm:
                        emit(gm.release())
                    del pads[path]
                    hk.gone(path)
                    continue
            if gm:
                emit(gm.tick(now))
            elif not game:
                for k in pad.due(now):
                    press(k)
        asked = hk.due(now, bool(game))
        if asked == "leave":
            print("Home held: leaving the game", file=sys.stderr, flush=True)
            home()
        elif asked == "rescue":
            rescue("Home held for %d seconds, or pressed %d times, on a controller or a remote" % (RESCUE_HOLD, RESCUE_TAPS))


if __name__ == "__main__":
    main()
