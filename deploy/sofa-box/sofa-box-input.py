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

Needs python3-evdev and /dev/uinput (the installer lets the box's user use it).
"""
import json
import os
import re
import select
import sys
import time
import urllib.request

AGENT = "http://127.0.0.1:%s" % os.environ.get("SOFA_BOX_PORT", "8091")
FIRST, AGAIN = 0.42, 0.13                  # seconds before an arrow repeats, then between repeats

# Linux button numbers (input-event-codes.h)
BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST = 304, 305, 307, 308
BTN_TL, BTN_TR, BTN_TL2, BTN_TR2, BTN_SELECT, BTN_START, BTN_MODE = 310, 311, 312, 313, 314, 315, 316
BTN_DPAD = {544: "KEY_UP", 545: "KEY_DOWN", 546: "KEY_LEFT", 547: "KEY_RIGHT"}
ABS_X, ABS_Y, ABS_Z, ABS_RZ, ABS_GAS, ABS_BRAKE, ABS_HAT0X, ABS_HAT0Y = 0, 1, 2, 5, 9, 10, 16, 17
KEYS = ("KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_ENTER", "KEY_BACK", "KEY_PLAYPAUSE", "KEY_SLASH",
        "KEY_REWIND", "KEY_FASTFORWARD")


def is_playstation(name):
    """PlayStation pads call themselves "Wireless Controller" (so do Xbox ones, with "Xbox" first)."""
    return not re.search(r"Xbox|Microsoft|8BitDo", name, re.I) and \
        bool(re.search(r"Wireless Controller|DualSense|DualShock|PLAYSTATION|PS[345]|Sony", name, re.I))


class Pad:
    """One controller: its events in, key presses out (testable without one)."""

    def __init__(self, name="", ranges=None):
        self.ranges = ranges or {}                          # axis -> (min, max)
        ps = is_playstation(name)
        self.buttons = {BTN_SOUTH: "KEY_ENTER", BTN_EAST: "KEY_BACK", BTN_SELECT: "KEY_BACK",
                        BTN_START: "KEY_PLAYPAUSE", BTN_TL: "KEY_REWIND", BTN_TL2: "KEY_REWIND",
                        BTN_TR: "KEY_FASTFORWARD", BTN_TR2: "KEY_FASTFORWARD", BTN_MODE: "HOME",
                        # Xbox-style drivers give X as 307; PlayStation's square is 308 (and triangle 307)
                        BTN_NORTH: "KEY_SLASH" if ps else "KEY_PLAYPAUSE", BTN_WEST: "KEY_PLAYPAUSE" if ps else "KEY_SLASH"}
        self.axes = {}
        self.dirs = {}                                      # arrow -> when it next repeats
        self.triggers = {ABS_Z: False, ABS_RZ: False, ABS_GAS: False, ABS_BRAKE: False}
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
        return out

    def feed(self, etype, code, value, now):
        """One event; returns the keys to press now."""
        out = []
        if etype == 1:                                      # EV_KEY
            if code in BTN_DPAD:
                (self.dpad_buttons.add if value else self.dpad_buttons.discard)(BTN_DPAD[code])
            elif value == 1 and code in self.buttons:
                out.append(self.buttons[code])
        elif etype == 3:                                    # EV_ABS
            if code in self.triggers:
                lo, hi = self.ranges.get(code, (0, 255))
                on = (value - lo) > 0.6 * ((hi - lo) or 1)
                if on and not self.triggers[code]:
                    out.append("KEY_REWIND" if code in (ABS_Z, ABS_BRAKE) else "KEY_FASTFORWARD")
                self.triggers[code] = on
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

    def due(self, now):
        """Arrows held long enough to repeat."""
        out = []
        for k, at in self.dirs.items():
            if now >= at:
                out.append(k)
                self.dirs[k] = now + AGAIN
        return out


def home():
    try:
        req = urllib.request.Request(AGENT + "/box/api/home", data=json.dumps({}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3).close()
    except Exception:
        pass


def main():
    try:
        from evdev import InputDevice, UInput, ecodes, list_devices
    except ImportError:
        sys.exit("python3-evdev is missing: sudo apt install python3-evdev")
    kb = UInput({ecodes.EV_KEY: [ecodes.ecodes[k] for k in KEYS]}, name="Sofa box controllers")
    pads, last_scan = {}, 0

    def press(name):
        if name == "HOME":
            return home()
        code = ecodes.ecodes[name]
        kb.write(ecodes.EV_KEY, code, 1)
        kb.write(ecodes.EV_KEY, code, 0)
        kb.syn()

    while True:
        now = time.time()
        if now - last_scan > 3:                             # controllers come and go (Bluetooth)
            last_scan = now
            for path in list_devices():
                if path in pads:
                    continue
                try:
                    dev = InputDevice(path)
                    keys = dev.capabilities().get(ecodes.EV_KEY, [])
                except OSError:
                    continue
                if BTN_SOUTH in keys and "Sofa box" not in dev.name:
                    ranges = {code: (info.min, info.max) for code, info in dev.capabilities().get(ecodes.EV_ABS, [])}
                    pads[path] = (dev, Pad(dev.name, ranges))
                    print("Controller: %s" % dev.name, file=sys.stderr, flush=True)
        ready = select.select([d.fd for d, _ in pads.values()], [], [], 0.03)[0] if pads else (time.sleep(0.5) or [])
        for path, (dev, pad) in list(pads.items()):
            if dev.fd in ready:
                try:
                    for ev in dev.read():
                        for k in pad.feed(ev.type, ev.code, ev.value, time.time()):
                            press(k)
                except OSError:                             # switched off or out of range
                    del pads[path]
                    continue
            for k in pad.due(time.time()):
                press(k)


if __name__ == "__main__":
    main()
