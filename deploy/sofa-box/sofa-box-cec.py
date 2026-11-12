#!/usr/bin/env python3
"""The TV's own remote for the Sofa box, over HDMI-CEC (Panasonic calls it VIERA Link, Samsung Anynet+,
LG SimpLink, Sony Bravia Sync).

The Pi tells the TV it's a player called "Sofa"; the TV then sends the remote's buttons down the HDMI
cable while the Pi's input is showing. This turns them into key presses for the browser: arrows, OK
(Enter), Back/Return (the browser's Back), play/pause, rewind/fast-forward, numbers, channel up/down. Home goes to the
box's agent instead (`home`), so it brings Home forward whatever is in front; typed as a key only if the agent doesn't
answer.

Needs: cec-ctl (package v4l-utils), python3-evdev (for a virtual keyboard), root (for /dev/uinput).
"""
import glob
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request

AGENT = "http://127.0.0.1:%s" % os.environ.get("SOFA_BOX_PORT", "8091")

# CEC "user control" codes -> Linux key names. https://www.cec-o-matic.com (User Control Codes)
KEYS = {
    0x00: "KEY_ENTER", 0x01: "KEY_UP", 0x02: "KEY_DOWN", 0x03: "KEY_LEFT", 0x04: "KEY_RIGHT",
    0x0D: "KEY_BACK", 0x91: "KEY_BACK",                       # Exit / Return, and CEC 2.0's Back: the browser's Back
    0x09: "KEY_HOMEPAGE",                                     # Root Menu (Home, on many remotes): the Sofa Box home screen
    0x0A: "KEY_MENU", 0x11: "KEY_MENU",                       # Setup Menu, Contents Menu: the Sofa bar / an app's options
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


# Home pressed five times in three seconds starts the TV's screen again: the way out of a screen that stopped
# answering, for someone with only the TV's own remote in hand. (A controller's or a Bluetooth remote's Home, held, does
# it in sofa-box-input.py; that daemon never opens this one's keyboard, so the TV's remote is counted here.) Over
# HDMI-CEC a button is "pressed", again and again on some TVs while it's held, never "held": so presses, not a hold.
RESCUE_TAPS, RESCUE_WINDOW = 5, 3.0


class HomeTaps:
    def __init__(self):
        self.at, self.rescued = [], -1e9

    def press(self, now):
        """Home was pressed: True when that makes RESCUE_TAPS within RESCUE_WINDOW (not again while it's starting)."""
        self.at = [t for t in self.at if now - t <= RESCUE_WINDOW] + [now]
        if len(self.at) < RESCUE_TAPS:
            return False
        self.at = []
        if now - self.rescued < 30:
            return False
        self.rescued = now
        return True


def rescue(why):
    """The TV's screen (and the box's helper) started again by systemd, and written down where a report reads it
    (the box user's own folder: SOFA_BOX_CONF, set in this service; the file stays that user's)."""
    line = "%s the TV's screen started again (%s)" % (time.strftime("%Y-%m-%d %H:%M:%S"), why)
    print(line, file=sys.stderr, flush=True)
    conf = os.environ.get("SOFA_BOX_CONF")
    if conf and os.path.isdir(conf):
        path = os.path.join(conf, "screen-restarts.log")
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            owner = os.stat(conf)
            if os.stat(path).st_uid != owner.st_uid:
                os.chown(path, owner.st_uid, owner.st_gid)
        except OSError:
            pass
    cmd = shlex.split(os.environ.get("SOFA_BOX_RESCUE", "")) or ["systemctl", "restart", "sofa-box", "sofa-box-agent"]
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        print("The TV's screen couldn't be started again: %s" % exc, file=sys.stderr, flush=True)


def run_keys(names, press, taps=None, rescue=rescue, clock=time.monotonic):
    """Each key from the TV's remote typed on the box's keyboard (`press`), and Home counted on its way."""
    taps = taps or HomeTaps()
    for name in names:
        press(name)
        if name == "KEY_HOMEPAGE" and taps.press(clock()):
            rescue("Home pressed %d times on the TV's own remote" % RESCUE_TAPS)


def home(open_=None):
    """Home, through the agent: True once it has it. (A key typed into the page in front could be kept by a site, a
    dialog or the player; the agent brings Home forward itself.)"""
    req = urllib.request.Request(AGENT + "/box/api/home", data=b"{}", headers={"Content-Type": "application/json", "X-Sofa-Box": "1"})
    try:
        (open_ or urllib.request.build_opener(urllib.request.ProxyHandler({})).open)(req, timeout=3).close()
        return True
    except Exception:
        return False


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
        try:
            subprocess.run(["ir-keytable", "-c", "-s", rc.rsplit("/", 1)[1]], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):     # (no ir-keytable: the TV's remote still works, maybe twice for some keys)
            print("ir-keytable isn't installed: the kernel's own CEC keys stay on", file=sys.stderr, flush=True)
            return


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

    def press(name):
        if name == "KEY_HOMEPAGE" and home():
            return
        key = ecodes.ecodes[name]
        ui.write(ecodes.EV_KEY, key, 1)
        ui.write(ecodes.EV_KEY, key, 0)
        ui.syn()

    run_keys(keys_from(lines()), press)
    sys.exit("cec-ctl stopped")                 # systemd starts this again


if __name__ == "__main__":
    main()
