#!/usr/bin/env python3
"""The TV's own remote for the Sofa box, over HDMI-CEC (Panasonic calls it VIERA Link, Samsung Anynet+,
LG SimpLink, Sony Bravia Sync).

The Pi tells the TV it's a player called "Sofa"; the TV then sends the remote's buttons down the HDMI
cable while the Pi's input is showing. This turns them into key presses for the browser: arrows, OK
(Enter), Back/Return (the browser's Back), play/pause, rewind/fast-forward, numbers, channel up/down.

Needs: cec-ctl (package v4l-utils), python3-evdev (for a virtual keyboard), root (for /dev/uinput).
"""
import glob
import re
import subprocess
import sys
import time

# CEC "user control" codes -> Linux key names. https://www.cec-o-matic.com (User Control Codes)
KEYS = {
    0x00: "KEY_ENTER", 0x01: "KEY_UP", 0x02: "KEY_DOWN", 0x03: "KEY_LEFT", 0x04: "KEY_RIGHT",
    0x0D: "KEY_BACK", 0x91: "KEY_BACK",                       # Exit / Return, and CEC 2.0's Back: the browser's Back
    0x45: "KEY_BACK",                                         # Stop: leave the video
    0x44: "KEY_PLAYPAUSE", 0x46: "KEY_PLAYPAUSE", 0x61: "KEY_PLAYPAUSE",
    0x48: "KEY_REWIND", 0x49: "KEY_FASTFORWARD",
    0x30: "KEY_PAGEUP", 0x31: "KEY_PAGEDOWN",                 # channel up/down: live TV
}
KEYS.update({0x20 + n: "KEY_%d" % n for n in range(10)})
PRESSED = re.compile(r"USER_CONTROL_PRESSED")
UI_CMD = re.compile(r"ui-cmd:.*\((0x[0-9a-fA-F]+)\)")
MENU_REQUEST = re.compile(r"Received from (\w[\w ]*?) to .*: MENU_REQUEST")
POWER_REQUEST = re.compile(r"Received from (\w[\w ]*?) to .*: GIVE_DEVICE_POWER_STATUS")


def adapter():
    """The /dev/cecN on the HDMI port that's connected to the TV."""
    for dev in sorted(glob.glob("/dev/cec*")):
        out = subprocess.run(["cec-ctl", "-d", dev], capture_output=True, text=True).stdout
        m = re.search(r"Physical Address\s*:\s*([0-9a-f.]+)", out)
        if m and m.group(1) != "f.f.f.f":
            return dev
    return None


def quiet_kernel_remote():
    """The kernel can turn CEC buttons into keys itself (rc-cec), but misses OK and Back; this does them all,
    so the kernel's keymap is emptied (no double presses)."""
    for rc in glob.glob("/sys/class/rc/rc*"):
        try:
            with open(rc + "/protocols") as f:
                if "cec" not in f.read():
                    continue
        except OSError:
            continue
        subprocess.run(["ir-keytable", "-c", "-s", rc.rsplit("/", 1)[1]], capture_output=True)


def keys_from(lines):
    """CEC monitor output -> key names (a generator; testable without a TV)."""
    pressed = False
    for line in lines:
        if PRESSED.search(line):
            pressed = True
            m = UI_CMD.search(line)               # some cec-ctl versions put it on the same line
            if not m:
                continue
        else:
            m = UI_CMD.search(line) if pressed else None
        if m:
            pressed = False
            code = int(m.group(1), 16)
            if code in KEYS:
                yield KEYS[code]
        elif not line.startswith((" ", "\t")):
            pressed = False


def main():
    try:
        from evdev import UInput, ecodes
    except ImportError:
        sys.exit("python3-evdev is missing: sudo apt install python3-evdev")
    dev = None
    while not dev:
        dev = adapter()
        if not dev:
            time.sleep(10)                      # the TV is off or not connected yet
    subprocess.run(["cec-ctl", "-d", dev, "--playback", "--osd-name", "Sofa"], capture_output=True)
    quiet_kernel_remote()
    ui = UInput({ecodes.EV_KEY: sorted({ecodes.ecodes[k] for k in KEYS.values()})}, name="Sofa box TV remote")
    mon = subprocess.Popen(["cec-ctl", "-d", dev, "--monitor"], stdout=subprocess.PIPE, text=True, bufsize=1)

    def lines():
        for line in mon.stdout:
            # Some TVs only send the remote's buttons to a player that says its menu is open.
            m = MENU_REQUEST.search(line)
            if m:
                subprocess.run(["cec-ctl", "-d", dev, "--to", "0", "--menu-status", "menu-state=activated"], capture_output=True)
            if POWER_REQUEST.search(line):
                subprocess.run(["cec-ctl", "-d", dev, "--to", "0", "--report-power-status", "pwr-state=on"], capture_output=True)
            yield line

    for name in keys_from(lines()):
        key = ecodes.ecodes[name]
        ui.write(ecodes.EV_KEY, key, 1)
        ui.write(ecodes.EV_KEY, key, 0)
        ui.syn()
    sys.exit("cec-ctl stopped")                 # systemd starts this again


if __name__ == "__main__":
    main()
