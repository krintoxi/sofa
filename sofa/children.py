"""The programs Sofa starts (ffmpeg to watch, record and convert; yt-dlp; whatever they start in turn), when Sofa
starts again in place.

On a Mac or Linux, Restart and an update start Sofa again in the same process (os.execv: updater.restart). What it
had started is still running and still its own, but the new code knows nothing of it. A recording's copy went on
writing a part nobody would file, holding its tuner; the rest stopped only once what they wrote to was gone (a pipe,
a folder the new start clears), if it was. So the first thing Sofa does as it serves is end them (end_leftovers): all
but the recordings it takes over (sofa/dvr.py: hand_over, take_over), which carry on without losing a moment.

A full stop doesn't need this: launchd, systemd and Docker end everything a service started, and on Windows the Sofa
app's job object does (sofa/winapp.py), so there a restart starts with nothing left over.
"""
import os
import signal
import subprocess
import time


def _parents():
    """{process: its parent} for every process on the computer (Linux: /proc; a Mac: ps)."""
    out = {}
    if os.path.isdir("/proc/self/task"):
        for name in os.listdir("/proc"):
            if name.isdigit():
                try:
                    with open("/proc/%s/stat" % name, "rb") as f:
                        stat = f.read()
                    out[int(name)] = int(stat[stat.rindex(b")") + 2:].split()[1])     # "pid (name) state ppid ..."
                except (OSError, ValueError, IndexError):
                    pass
        return out
    try:
        ps = subprocess.Popen(["ps", "-A", "-o", "pid=,ppid="], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              stdin=subprocess.DEVNULL, text=True)
        text = ps.communicate(timeout=10)[0]
    except (OSError, subprocess.SubprocessError):
        return out
    for line in text.splitlines():
        pid, _, ppid = line.strip().partition(" ")
        if pid.isdigit() and ppid.strip().isdigit() and int(pid) != ps.pid:
            out[int(pid)] = int(ppid.strip())
    return out


def descendants(root=None, keep=()):
    """The processes `root` (this one) started, and the ones they started, but `keep` and what those started."""
    root = root or os.getpid()
    below = {}
    for pid, ppid in _parents().items():
        below.setdefault(ppid, []).append(pid)
    out, todo, keep = [], [root], set(keep) | {root}
    while todo:
        for pid in below.get(todo.pop(), ()):
            if pid not in keep:
                keep.add(pid)
                out.append(pid)
                todo.append(pid)
    return out


def _gone(pid):
    """True once `pid` has ended (and been waited for, when it was this process's own)."""
    try:
        if os.waitpid(pid, os.WNOHANG)[0]:
            return True
    except ChildProcessError:
        pass                                  # not this process's own (a helper's helper): gone when it isn't there
    except OSError:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return True                           # (someone else's by now)
    return False


def end_leftovers(keep=(), grace=3.0):
    """End what an earlier Sofa in this same process started (it started again in place), but `keep`: asked to stop,
    then, after `grace` seconds, made to. Returns how many there were. Nothing to do on Windows (see above)."""
    if os.name == "nt":
        return 0
    found = descendants(keep=keep)
    there = len(found)
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 1.0)):
        for pid in found:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        end = time.time() + wait
        while time.time() < end:
            found = [pid for pid in found if not _gone(pid)]
            if not found:
                break
            time.sleep(0.05)
        if not found:
            break
    return there
