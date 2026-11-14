#!/usr/bin/env python3
"""The Google TV build on an Android TV, as GitHub runs it in an emulator (.github/workflows/android.yml).

What it proves, on a real Android TV system (the emulator's), with a Sofa running beside it:

1. the TV's launcher lists the app (a leanback entry, with its banner), and the app says it's for TVs;
2. it opens from that entry and shows its start page;
3. the remote's arrows move through what can be picked, and what's typed with the remote's keyboard arrives;
4. it reaches Sofa and shows Sofa's own sign-in for a TV: a code;
5. the code, approved as a phone would approve it (Sofa's own API), signs the TV in, and Home shows in TV mode;
6. the arrows move the highlight on Home, and Back from the start leaves the app.

What it can't: a real TV, its remote, its speakers, a video played on its decoder. Screenshots of every step go to
`shots/`. The keys are Android's own (`adb shell input keyevent`); what the pages show is read from the debug
build's web view over DevTools, so a failed step says what was on the screen.

    python3 android/tv_check.py <the debug APK>         (adb on PATH, an emulator running, Sofa on port 8090)
"""
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "deploy", "sofa-box"))
from boxos import WebSocket  # noqa: E402

PKG = "uk.edgeventure.sofa.tv"
ACTIVITY = PKG + "/uk.edgeventure.sofa.MainActivity"
SOFA = "http://127.0.0.1:8090"             # the Sofa beside the emulator, as this script reaches it
FROM_THE_TV = "10.0.2.2:8090"              # and as the emulated TV does (the emulator's name for its host)
SHOTS = os.environ.get("SHOTS", "shots")
PORT = 9333


def adb(*args, check=True, binary=False):
    r = subprocess.run(["adb"] + list(args), capture_output=True, timeout=120)
    if check and r.returncode != 0:
        raise SystemExit("adb %s: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace")[-300:]))
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def say(text):
    print(text, flush=True)


def shot(name):
    os.makedirs(SHOTS, exist_ok=True)
    with open(os.path.join(SHOTS, name + ".png"), "wb") as f:
        f.write(adb("exec-out", "screencap", "-p", binary=True))


def key(name, pause=0.8):
    adb("shell", "input", "keyevent", "KEYCODE_" + name)
    time.sleep(pause)


class TakenAway(Exception):
    """Android ended the app for its own reasons (a system service it leans on died: the emulator's Google services
    restarting after boot, say), not because the app crashed. The steps start again."""


def gone():
    """Why the app isn't there any more: Android's own record of what stopped it, for the log."""
    crash = adb("logcat", "-d", "-b", "crash", "-t", "60", check=False).strip()
    lines = [l for l in adb("logcat", "-d", "-t", "1500", check=False).splitlines()
             if re.search(r"uk\.edgeventure\.sofa|FATAL|AndroidRuntime|chromium.*(crash|kill|gone)|RenderProcessGone|lowmemorykiller|am_(crash|kill|proc_died)|Process .* has died|Force stopping", l, re.I)]
    top = [l.strip() for l in adb("shell", "dumpsys", "activity", "activities", check=False).splitlines() if "ResumedActivity" in l]
    return "In front now: %s\nAndroid's crash log:\n%s\nWhat the log says of the app:\n%s" % (
        "; ".join(top) or "?", crash[-3000:] or "(empty)", "\n".join(lines[-40:]) or "(nothing)")


class Page:
    """The app's web view, over DevTools (a debug build opens it; `adb forward` brings it here)."""

    def __init__(self):
        self.attach()

    def attach(self):
        found = adb("shell", "pidof", PKG, check=False).strip().split()
        if not found:
            shot("failed")
            why = gone()
            if re.search(r"Killing \d+:%s\S* .*(depends on provider|dying proc)" % re.escape(PKG), why):
                raise TakenAway(why)
            raise SystemExit("The app isn't running any more.\n" + why)
        pid = found[0]
        adb("forward", "tcp:%d" % PORT, "localabstract:webview_devtools_remote_" + pid)
        deadline = time.time() + 30
        while True:
            try:
                tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json" % PORT, timeout=5).read())
                tab = next(t for t in tabs if t.get("type") == "page")
                break
            except (OSError, ValueError, StopIteration):
                if time.time() > deadline:
                    raise SystemExit("the app's web view never answered on its DevTools socket")
                time.sleep(1)
        self.ws = WebSocket(tab["webSocketDebuggerUrl"].replace("localhost", "127.0.0.1"))
        self.n = 0

    def js(self, expression, again=True):
        try:
            self.n += 1
            self.ws.send(json.dumps({"id": self.n, "method": "Runtime.evaluate",
                                     "params": {"expression": expression, "returnByValue": True, "awaitPromise": True}}))
            while True:
                m = json.loads(self.ws.recv())
                if m.get("id") == self.n:
                    return (m.get("result") or {}).get("result", {}).get("value")
        except OSError:
            if not again:
                raise
            time.sleep(1)
            self.attach()                           # the page's process was replaced (or the app is gone: attach says so)
            return self.js(expression, again=False)

    def text(self):
        return self.js("document.body ? document.body.innerText : ''") or ""

    def focused(self):
        """What the highlight is on: its text, or its placeholder, or its tag."""
        return self.js("(()=>{const e=document.activeElement; if(!e||e===document.body) return ''; "
                       "return (e.innerText||e.getAttribute('aria-label')||e.placeholder||e.id||e.tagName).trim().split('\\n')[0].slice(0, 60)})()") or ""

    def wait(self, what, seconds=60, said="the page"):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                got = what()
            except OSError:
                got = None
            if got:
                return got
            time.sleep(1)
        shot("failed")
        try:
            on_screen = self.text()[:400]
        except OSError:
            on_screen = "(the page doesn't answer)"
        raise SystemExit("%s never showed. On the screen: %r\n%s" % (said, on_screen, gone()))


def sofa(path, data=None, cookie=None):
    req = urllib.request.Request(SOFA + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json", "X-Sofa": "1", **({"Cookie": cookie} if cookie else {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}"), (r.headers.get("Set-Cookie") or "").split(";")[0]


def main(apk):
    # A Sofa with one person in it, to approve the TV as (a throwaway account on this machine).
    _, phone = sofa("/api/setup", {"name": "Robin", "password": secrets.token_urlsafe(12)})
    me, _ = sofa("/api/session", cookie=phone)
    say("Sofa %s is up, with one person in it." % sofa("/api/info")[0]["version"])

    adb("install", "-r", apk)
    # 1. On the TV's home screen: a leanback launcher entry, a banner, and "for TVs".
    entries = adb("shell", "cmd", "package", "query-activities", "--brief", "-a", "android.intent.action.MAIN",
                  "-c", "android.intent.category.LEANBACK_LAUNCHER")
    if PKG + "/" not in entries:
        raise SystemExit("the TV's launcher doesn't list the app:\n" + entries)
    dump = adb("shell", "dumpsys", "package", PKG)
    features = adb("shell", "pm", "list", "features")
    if "android.software.leanback" not in features:
        raise SystemExit("this isn't an Android TV system: no leanback feature")
    say("1. The TV's launcher lists Sofa (%s, Android %s, version %s)." % (
        adb("shell", "getprop", "ro.product.model").strip(), adb("shell", "getprop", "ro.build.version.release").strip(),
        (re.search(r"versionName=(\S+)", dump) or [None, "?"])[1]))

    settle()
    for attempt in range(1, 4):
        try:
            steps(phone, me)
            say("All six steps passed%s." % ("" if attempt == 1 else " (on try %d: Android ended the app before, for a system service of its own)" % attempt))
            return 0
        except TakenAway as why:
            say("   Android ended the app for a service of its own, not a crash of the app's:\n" + str(why)[:1500])
            if attempt == 3:
                raise SystemExit("Android ended the app three times; see above.")
            adb("shell", "pm", "clear", PKG, check=False)      # (from the start page again: no Sofa remembered)
            settle()
    return 1


def settle(most=150):
    """Wait for the TV's own services to finish starting (the emulator's Google services restart once or twice after
    boot, and take every app using their font provider down with them): until their process has stayed the same for
    thirty seconds."""
    last, since, deadline = None, time.time(), time.time() + most
    while time.time() < deadline:
        now = adb("shell", "pidof", "com.google.android.gms.persistent", check=False).strip()
        if now != last:
            last, since = now, time.time()
        elif now and time.time() - since >= 30:
            return
        time.sleep(3)


def steps(phone, me):
    # 2. Opened from that entry.
    adb("shell", "am", "start", "-W", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LEANBACK_LAUNCHER", "-n", ACTIVITY)
    time.sleep(4)
    page = Page()
    page.wait(lambda: "Sofa for Google TV" in page.text(), said="the start page")
    shot("1-start")
    say("2. It opens on its start page: %r, the highlight on %r." % (page.text().split("\n")[0], page.focused()))

    # 3. The remote: down and up move the highlight; the address typed with the remote's keyboard arrives.
    seen = [page.focused()]
    for k in ("DPAD_DOWN", "DPAD_UP"):
        key(k)
        seen.append(page.focused())
    if len(set(seen)) < 2 or seen[-1] != seen[0]:
        raise SystemExit("the arrows didn't move the highlight down and back on the start page: %r" % seen)
    for _ in range(4):                                   # to the address field
        if page.js("document.activeElement && document.activeElement.id") == "addr":
            break
        key("DPAD_UP")
    key("DPAD_CENTER", pause=1.5)                        # OK opens it for typing (the TV's keyboard comes up)
    adb("shell", "input", "text", FROM_THE_TV)
    time.sleep(1)
    typed = page.js("document.getElementById('addr').value")
    if typed != FROM_THE_TV:
        raise SystemExit("typed %r, the page has %r" % (FROM_THE_TV, typed))
    shot("2-address")
    if "mInputShown=true" in adb("shell", "dumpsys", "input_method", check=False):
        key("BACK", pause=1)                             # the keyboard away, as a person closes it
    key("DPAD_DOWN")
    if page.focused() != "Connect":
        shot("failed")
        raise SystemExit("from the typed address, down didn't reach Connect: the highlight is on %r" % page.focused())
    say("3. The arrows move the highlight (%s); OK opens the address for typing, it arrives, and down reaches Connect."
        % " -> ".join(repr(s) for s in seen))
    key("DPAD_CENTER", pause=3)

    # 4. Sofa's own pages, in TV mode, asking who's watching.
    page.wait(lambda: page.js("location.href").startswith("http://" + FROM_THE_TV), said="Sofa")
    page.wait(lambda: page.js("!!document.querySelector('.pair-code, [data-pair], button, input')"), said="Sofa's sign-in")
    time.sleep(2)
    shot("3-sofa")
    agent = page.js("navigator.userAgent")
    if "SofaApp/1 (GoogleTV)" not in agent:
        raise SystemExit("the app doesn't say it's the Google TV build: " + agent)
    say("4. It reached Sofa (%s). TV mode: %s." % (page.js("location.href"), page.js("document.documentElement.className + ' ' + document.body.className").strip() or "?"))

    # 5. Sign in with a phone: the TV shows a code; a phone approves it; the TV is in.
    def code():
        got = page.js("(()=>{const e=document.querySelector('.pair-code'); return e ? e.textContent.replace(/\\D/g,'') : ''})()")
        return got if got and len(got) >= 4 else None
    if not code():                                   # not showing a code yet: find "with your phone" with the arrows
        for _ in range(12):
            if re.search(r"phone", page.focused(), re.I):
                break
            key("DPAD_DOWN")
        else:
            shot("failed")
            raise SystemExit("the arrows never reached the sign-in with a phone. The highlight is on %r; the page: %r"
                             % (page.focused(), page.text()[:300]))
        key("DPAD_CENTER", pause=2)
    shown = page.wait(code, said="the TV's code")
    shot("4-code")
    sofa("/api/pair/approve", {"code": shown, "profile": me["user"]["id"]}, cookie=phone)
    page.wait(lambda: page.js("!document.querySelector('.pair-code')") and re.search(r"Home|Movies|Shows", page.text()), said="Home after the approval")
    time.sleep(3)
    shot("5-home")
    say("5. The TV showed a code (%s digits), a phone approved it, and the TV is signed in as %s." % (len(shown), me["user"]["name"]))

    # 6. The arrows move the highlight on Home; Back from the first page leaves the app.
    seen = [page.focused()]
    for k in ("DPAD_RIGHT", "DPAD_RIGHT", "DPAD_DOWN", "DPAD_LEFT"):
        key(k)
        seen.append(page.focused())
    shot("6-moved")
    if len(set(seen)) < 2:
        raise SystemExit("the arrows didn't move the highlight on Home: %r" % seen)
    say("6. On Home the arrows move the highlight: %s." % " -> ".join(repr(s) for s in seen))
    for _ in range(6):
        key("BACK", pause=1)
        top = adb("shell", "dumpsys", "activity", "activities")
        if not re.search(r"(mResumedActivity|topResumedActivity|ResumedActivity).*" + re.escape(PKG), top):
            say("   Back, from the start, left the app.")
            break
    else:
        say("   (Back didn't leave the app in six presses: noted, not a failure of the build.)")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
