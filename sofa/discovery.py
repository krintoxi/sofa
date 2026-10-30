"""Letting apps find Sofa on the home network: the Fire TV app, the Roku channel and the Sofa box.

Bonjour (mDNS): Sofa announces "_sofa._tcp" with the tools the system already has (dns-sd on a Mac,
avahi-publish on Linux), so nothing extra is installed. SSDP: dlna.py also answers a Sofa-specific
search (urn:sofa-media:device:Sofa:1), for devices without Bonjour (Roku), even with TV sharing off.
Either way the app then asks /api/info, which needs no sign-in.
"""
import atexit
import os
import shutil
import subprocess
import threading
import time

from . import __version__, config

SERVICE = "_sofa._tcp"
API_VERSION = 1
PIDFILE = os.path.join(config.DATA_DIR, "cache", "mdns.pid")
_proc = [None]


def _command():
    name, port = config.get("name") or "Sofa", str(config.get("port"))
    txt = ["version=%s" % __version__, "api=%d" % API_VERSION, "path=/"]
    if shutil.which("dns-sd"):                                   # macOS
        return ["dns-sd", "-R", name, SERVICE, "local", port] + txt
    if shutil.which("avahi-publish-service"):                    # Linux with Avahi
        return ["avahi-publish-service", name, SERVICE, port] + txt
    return None


def _forget_leftover():
    """A announcer from a Sofa that didn't stop cleanly would make this one "Sofa (2)"."""
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip() or 0)
        if pid > 1:
            cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5).stdout
            if SERVICE in cmd:
                os.kill(pid, 15)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def stop():
    p = _proc[0]
    _proc[0] = None
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
    try:
        os.remove(PIDFILE)
    except OSError:
        pass


def _loop():
    _forget_leftover()
    while True:
        cmd = _command()
        if not cmd:
            return
        try:
            _proc[0] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            os.makedirs(os.path.dirname(PIDFILE), exist_ok=True)
            with open(PIDFILE, "w") as f:
                f.write(str(_proc[0].pid))
            _proc[0].wait()                          # it runs for as long as Sofa does
        except OSError:
            return
        if _proc[0] is None:                         # stopped on purpose
            return
        time.sleep(30)                               # it stopped by itself: announce again shortly


def start():
    atexit.register(stop)
    threading.Thread(target=_loop, daemon=True, name="bonjour").start()


def info():
    from . import dlna
    return {"sofa": True, "name": config.get("name") or "Sofa", "version": __version__, "api": API_VERSION,
            "port": config.get("port"), "id": dlna.UDN.replace("uuid:", "")}
