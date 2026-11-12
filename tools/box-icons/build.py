#!/usr/bin/env python3
"""Sofa Box icons: the styles drawn here (glossy.js, drawn.js, styles.js), baked to pictures for Home.

    python3 tools/box-icons/build.py                  every picture
    python3 tools/box-icons/build.py glossy frame-over   only those styles or pictures (the others are left as
                                                      they are: Chrome's pictures differ a little each time)

Writes deploy/sofa-box/home/art/icons/<style>/<size>/<id>.webp at 192 pixels (the tiles) and 512 (the big one behind
Home), and each style's housing for other companies' apps (frame-under.webp, frame-over.webp: frames.js), with node and Chrome (headless, over DevTools; CHROME= another one). The box only shows these pictures: none of
the gloss, glow or shadow is drawn on a Pi. Run it again after changing a drawing, and commit the pictures with it.
"""
import base64, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, "deploy", "sofa-box", "home", "art", "icons")
SIZES = (192, 512)
ONLY = set(sys.argv[1:])
CHROME = os.environ.get("CHROME") or next((c for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                                                        shutil.which("google-chrome"), shutil.which("chromium")) if c and os.path.exists(c)), None)

spec = importlib.util.spec_from_file_location("boxos_icons", os.path.join(REPO, "deploy", "sofa-box", "boxos.py"))
boxos = importlib.util.module_from_spec(spec); spec.loader.exec_module(boxos)      # (its small WebSocket client)


def node(*args):
    return subprocess.run(["node", os.path.join(HERE, "sheet.js"), *args], check=True, capture_output=True, text=True).stdout


def main():
    if not CHROME:
        sys.exit("No Chrome found: CHROME=/path/to/chrome")
    have = json.loads(node("--list"))
    styles, ids = have["styles"], have["ids"] + have["frames"]
    tmp = tempfile.mkdtemp(prefix="sofa-icons-")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    chrome = subprocess.Popen([CHROME, "--headless=new", "--no-first-run", "--user-data-dir=" + os.path.join(tmp, "profile"),
                               "--hide-scrollbars", "--remote-debugging-port=%d" % port, "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(150):
            try:
                tab = next(t for t in json.loads(op.open("http://127.0.0.1:%d/json/list" % port, timeout=3).read()) if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        ws = boxos.WebSocket(tab["webSocketDebuggerUrl"]); ws.sock.settimeout(60); n = [0]

        def call(method, **params):
            n[0] += 1; ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
            while True:
                r = json.loads(ws.recv())
                if r.get("id") == n[0]:
                    if "error" in r:
                        raise RuntimeError(method + ": " + json.dumps(r["error"]))
                    return r.get("result", {})

        call("Page.enable")
        call("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
        made = 0
        for size in SIZES:
            page = os.path.join(tmp, "sheet-%d.html" % size)
            with open(page, "w") as f:
                f.write(node(str(size)))
            call("Emulation.setDeviceMetricsOverride", width=size * len(ids), height=size * len(styles), deviceScaleFactor=1, mobile=False)
            call("Page.navigate", url="file://" + page)
            time.sleep(2.5)
            for row, style in enumerate(styles):
                os.makedirs(os.path.join(OUT, style, str(size)), exist_ok=True)
                for col, app in enumerate(ids):
                    if ONLY and style not in ONLY and app not in ONLY:
                        continue
                    shot = call("Page.captureScreenshot", format="webp", quality=92,
                                clip={"x": col * size, "y": row * size, "width": size, "height": size, "scale": 1})
                    with open(os.path.join(OUT, style, str(size), app + ".webp"), "wb") as f:
                        f.write(base64.b64decode(shot["data"]))
                    made += 1
        print("%d pictures in %s" % (made, os.path.relpath(OUT, REPO)))
    finally:
        chrome.terminate()
        try:
            chrome.wait(10)
        except subprocess.TimeoutExpired:
            chrome.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
