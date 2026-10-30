#!/usr/bin/env python3
"""See the Sofa box on this computer before putting it on a Raspberry Pi.

    python3 tools/sofa-box-preview.py                       # Sofa on this computer (port 8090)
    python3 tools/sofa-box-preview.py http://192.168.1.20:8090
    python3 tools/sofa-box-preview.py --shots docs/images   # a picture of the boot screen, then stop

It runs the box's own agent here (on port 8091) with its own settings folder, so nothing of yours is
changed, and opens the preview: the TV (Sofa's TV pages as the box shows them, at the TV's size), a
remote, Box settings, and the boot screen (try the themes). Videos open in mpv in a window if mpv is
installed (on a Mac: brew install mpv); without it a stand-in plays them silently, so the TV and the
phone remote still behave as they would on the box.

Needs Python 3, and Pillow (pip3 install pillow) for the boot screen's pictures.
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
BOX = os.path.join(HERE, "..", "deploy", "sofa-box")


def get(url, timeout=5):
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=timeout) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser(description="Preview the Sofa box on this computer.")
    ap.add_argument("server", nargs="?", default="http://127.0.0.1:8090", help="Sofa's address (default: this computer)")
    ap.add_argument("--port", type=int, default=8091, help="the box agent's port (default 8091, as on the box)")
    ap.add_argument("--slow", action="store_true", help="act like a Raspberry Pi 3 (720p and lighter effects)")
    ap.add_argument("--shots", metavar="DIR", help="save a picture of the boot screen, then stop")
    ap.add_argument("--no-open", action="store_true", help="don't open the browser")
    a = ap.parse_args()

    if importlib.util.find_spec("PIL") is None:
        sys.exit("The boot screen's pictures need Pillow: pip3 install pillow")
    try:
        get(a.server.rstrip("/") + "/api/info")
    except Exception:
        print("Note: Sofa isn't answering at %s yet; the TV shows the box's \"Looking for Sofa\" page until it does." % a.server)

    conf = tempfile.mkdtemp(prefix="sofa-box-preview-")
    with open(os.path.join(conf, "settings.json"), "w") as f:
        json.dump({"server": a.server.rstrip("/")}, f)
    env = dict(os.environ, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(a.port))
    if a.slow:
        env["SOFA_BOX_SLOW"] = "1"
    if shutil.which("mpv"):
        env["SOFA_BOX_MPV_ARGS"] = "--fs=no --autofit=60% " + env.get("SOFA_BOX_MPV_ARGS", "")
    else:
        env["SOFA_BOX_MPV"] = os.path.join(HERE, "fake_mpv.py")
        print("mpv isn't installed: videos play silently in a stand-in.")
    agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], env=env)
    base = "http://127.0.0.1:%d" % a.port
    try:
        for _ in range(50):
            try:
                get(base + "/box/state", 1)
                break
            except Exception:
                time.sleep(0.2)
        if a.shots:
            os.makedirs(a.shots, exist_ok=True)
            with open(os.path.join(a.shots, "box-boot.png"), "wb") as f:
                f.write(get(base + "/box/splash.png?phase=0.45"))
            print("Saved the boot screen in", a.shots)
            return
        print("The Sofa box preview: %s/box/preview   (Ctrl+C to stop)" % base)
        if not a.no_open:
            webbrowser.open(base + "/box/preview")
        agent.wait()
    except KeyboardInterrupt:
        pass
    finally:
        agent.terminate()
        shutil.rmtree(conf, ignore_errors=True)


if __name__ == "__main__":
    main()
