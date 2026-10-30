"""Keeping the Sofa computer awake while Sofa runs: a Mac that falls asleep takes Sofa off every TV.

macOS: `caffeinate -i -s -w <Sofa's process>`, so the computer doesn't sleep by itself while Sofa runs
(the screen still turns off). Linux: `systemd-inhibit` holds off sleep the same way. It ends by itself
when Sofa stops. Server → Settings → Keep this computer awake turns it off.

Sofa restarts itself in place after an update (same process), so the helper it started before is
remembered in data/cache/awake.pid and reused instead of starting another.
"""
import os
import shutil
import subprocess

from . import config

PID_FILE = os.path.join(config.DATA_DIR, "cache", "awake.pid")
_proc = None


def _command():
    me = str(os.getpid())
    if shutil.which("caffeinate"):
        return ["caffeinate", "-i", "-s", "-w", me]
    if shutil.which("systemd-inhibit") and shutil.which("tail"):
        return ["systemd-inhibit", "--what=sleep:idle", "--who=Sofa", "--why=Sofa is serving videos", "--mode=block",
                "tail", "--pid=" + me, "-f", "/dev/null"]
    return None


def _running_for_us():
    """The helper started for this same process before a restart, if it's still there."""
    try:
        with open(PID_FILE, encoding="utf-8") as f:
            pid = int(f.read().strip())
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return str(os.getpid()) in out and ("caffeinate" in out or "systemd-inhibit" in out)


def status():
    """"on", "off" (the setting), or "unavailable" (no way to do it here)."""
    if not config.get("keep_awake"):
        return "off"
    return "on" if _command() else "unavailable"


def apply():
    """Start or stop keeping awake, to match the setting."""
    global _proc
    if not config.get("keep_awake") or not _command():
        stop()
        return
    if (_proc and _proc.poll() is None) or _running_for_us():
        return
    try:
        _proc = subprocess.Popen(_command(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(_proc.pid))
    except OSError:
        _proc = None


def stop():
    global _proc
    pid = _proc.pid if _proc else None
    if pid is None and _running_for_us():
        with open(PID_FILE, encoding="utf-8") as f:
            pid = int(f.read().strip())
    if pid:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    _proc = None
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


start = apply
