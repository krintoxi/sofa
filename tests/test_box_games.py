"""Games on a Sofa Box: the open-source games it installs from its list (only those packages, through its root
helper), opens over the home screen and ends with Home held; and the controller daemon's game mode (every
controller the same in each game: keys and a mouse by the buttons' places)."""
import importlib.util
import json
import re
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)

BOX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "sofa-box")


def load(name, as_name):
    spec = importlib.util.spec_from_file_location(as_name, os.path.join(BOX, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pads = load("sofa-box-input", "sofa_box_input_games")
with open(os.path.join(BOX, "games", "games.json"), encoding="utf-8") as f:
    CATALOG = json.load(f)
CONTROLS = CATALOG["controls"]


def script(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class TheList(unittest.TestCase):
    def test_every_game_is_complete(self):
        for g in CATALOG["native"]:
            for k in ("id", "name", "about", "packages", "run", "controls", "mb", "pi"):
                self.assertIn(k, g, g["id"])
            self.assertTrue(g["controls"] == "pad" or g["controls"] in CONTROLS, g["id"])
            if g.get("icon"):
                self.assertTrue(os.path.isfile(os.path.join(BOX, "games", g["icon"])), g["icon"])
        for g in CATALOG["games"]:                                   # our own games: played with a controller first
            with open(os.path.join(BOX, "games", g["id"], "index.html"), encoding="utf-8") as f:
                page = f.read()
            self.assertTrue("../pad.js" in page or "getGamepads" in page, g["id"] + " doesn't read the controller itself")
        for name, c in CONTROLS.items():
            for action in c["buttons"].values():                      # every key a real one
                for part in action.split("+"):
                    self.assertRegex(part, r"^(KEY|BTN)_[A-Z0-9]+$|^WHEEL_(UP|DOWN)$", name)

    def test_the_shooters(self):
        """AssaultCube and Sauerbraten (Debian's, non-free: Raspberry Pi OS has it on): walk with the left stick,
        look with the right, fire with RT; drawn small enough for a Pi 3, through XWayland."""
        native = {g["id"]: g for g in CATALOG["native"]}
        for gid, height in (("assaultcube", 720), ("sauerbraten", 576)):
            g = native[gid]
            self.assertEqual((g["pi"], g["pi3_height"], g["setup"]), (3, height, gid))
            self.assertEqual(g["env"], {"SDL_VIDEODRIVER": "x11"})
            c = CONTROLS[g["controls"]]
            self.assertEqual((c["left"], c["right"]), ("wasd", "mouse"))
            self.assertEqual((c["buttons"]["south"], c["buttons"]["rt"], c["buttons"]["lt"]), ("KEY_SPACE", "BTN_LEFT", "BTN_RIGHT"))
            self.assertNotIn("KEY_E", c["buttons"].values())             # (E is their map editor)
        self.assertEqual(native["sauerbraten"]["packages"], ["sauerbraten"])
        self.assertEqual(native["assaultcube"]["data"], "../lib/games/assaultcube/packages")
        for g in CATALOG["native"]:
            for k in g.get("env") or {}:
                self.assertRegex(k, r"^SDL_[A-Z0-9_]+$", g["id"])
            if g.get("data"):
                self.assertFalse(os.path.isabs(g["data"]), g["id"])     # (beside the program)


    def test_the_games_in_the_home_screen(self):
        """Each one ("games") is a page of its own in games/<id>/, all in one file, needing nothing from the internet."""
        self.assertIn("gloamwell", [g["id"] for g in CATALOG["games"]])
        for g in CATALOG["games"]:
            for k in ("id", "name", "emoji", "color", "about"):
                self.assertIn(k, g, g["id"])
            self.assertRegex(g["id"], r"^[a-z0-9-]+$")
            page = os.path.join(BOX, "games", g["id"], "index.html")
            self.assertTrue(os.path.isfile(page), page)
            with open(page, encoding="utf-8") as f:
                html = f.read()
            self.assertNotRegex(html, r"""(src|href|url)\s*[=(]\s*["']?(https?:)?//""", g["id"])
        with open(os.path.join(BOX, "games", "gloamwell", "index.html"), encoding="utf-8") as f:
            html = f.read()
        for online in ("fetch(", "XMLHttpRequest", "WebSocket", "<link", "@import"):
            self.assertNotIn(online, html)                             # Gloamwell plays offline
        self.assertEqual(re.findall(r"<script src=\"([^\"]+)\"", html), ["../pad.js"])   # (only pad.js, for a touch screen)
        self.assertIn("navigator.getGamepads", html)                   # with a controller,
        self.assertNotRegex(html, r"buttons\[16\]")                    # never Home, which is the box's


# pad.js in node: a fake navigator.getGamepads() holding the controllers, frames stepped by hand
PADS_JS = r"""
const fs = require("fs");
let now = 1000, rafq = [];
const def = (k, v) => Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
const pads = [null, null, null, null], on = {}, shook = [];
def("window", globalThis); def("navigator", { getGamepads: () => pads }); def("performance", { now: () => now });
def("location", { hash: "" }); def("document", { hidden: false, createElement: () => ({ getContext: () => null }) });
def("addEventListener", (t, f) => (on[t] = on[t] || []).push(f));
def("requestAnimationFrame", cb => rafq.push(cb));
for (const f of process.argv.slice(1)) eval(fs.readFileSync(f, "utf8"));
const frame = (ms) => { now += ms || 16; const q = rafq; rafq = []; for (const cb of q) cb(now); };
const frames = (n, ms) => { for (let i = 0; i < n; i++) frame(ms); };
const mk = (index, id, mapping) => ({ index, id, mapping: mapping == null ? "standard" : mapping, connected: true, axes: [0, 0, 0, 0],
  buttons: Array.from({ length: 17 }, () => ({ pressed: false, value: 0 })),
  vibrationActuator: { playEffect: (k, o) => { shook.push(index + ":" + o.strongMagnitude); return Promise.resolve(); } } });
const XBOX = "Xbox Wireless Controller (STANDARD GAMEPAD Vendor: 045e Product: 0b13)", PS = "DualSense Wireless Controller (STANDARD GAMEPAD Vendor: 054c Product: 0ce6)";
const PRO = "Pro Controller (STANDARD GAMEPAD Vendor: 057e Product: 2009)", BITDO = "8BitDo Ultimate (STANDARD GAMEPAD Vendor: 2dc8 Product: 3106)";
const P = window.SofaPad, out = {}, log = [];
"""


def pads_in_node(test, script, *files):
    """PADS_JS, then the files (from games/), then the script; what it prints last, as JSON."""
    r = subprocess.run(["node", "-e", PADS_JS + script] + [os.path.join(BOX, "games", f) for f in files],
                       capture_output=True, text=True, timeout=60)
    test.assertEqual(r.returncode, 0, r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


class ThePads(unittest.TestCase):
    """pad.js: every controller a player (numbered as they come, joining at any time), while the one-player calls
    follow whichever controller was used last, exactly as before; the box's echo keys still dropped."""

    def node(self, script, *files):
        return pads_in_node(self, script, *files)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_several_controllers(self):
        out = self.node(r"""
P.on((b, how, p) => log.push(b + " " + how + " " + (p ? p.n : "-")));
P.on("joined", p => log.push("joined " + p.n)); P.on("left", p => log.push("left " + p.n));
const two = P.player(2), mine = { 1: [], 2: [] };              // held before anyone joins: the same object for good
P.player(1).on(b => mine[1].push(b)); two.on(b => mine[2].push(b));
out.before = [P.connected(), P.players().length, two.connected(), two.held("a"), P.held("a"), P.kind(), P.label("a"), P.stick().x];
const xbox = mk(0, XBOX), ps = mk(1, PS);                       // two at once (a page's first press shows them all):
pads[0] = xbox; pads[1] = ps; ps.buttons[0].pressed = true;     // the one pressed is player 1
frame(); out.first = log.splice(0);
out.numbers = P.players().map(p => p.n + " " + p.kind());
out.two = [P.player(2) === two, two.kind(), P.kind(), P.label("a")];
ps.buttons[0].pressed = false; frame(); log.length = 0;
xbox.buttons[14].pressed = true; xbox.axes[2] = 0.9; frame();  // the one-player calls follow the one used last
out.follow = [P.kind(), P.label("a"), P.held("left"), P.button("left"), P.stick2().x > 0.8, P.player(1).held("left"), two.held("left"), two.button("left")];
xbox.axes[2] = 0; frames(36);                                    // held: repeats after 380 ms, then every 120
xbox.buttons[14].pressed = false; frame(); out.held = log.splice(0);
xbox.axes[0] = -0.3; frame();                                    // (a stick at -0.3: in use, but no direction yet)
out.small = [P.held("left"), P.stick().x < -0.15 && P.stick().x > -0.2]; xbox.axes[0] = 0; frame();
pads[2] = mk(2, PRO); pads[2].axes[0] = 0.3; frame();            // someone joins later: player 3; a stick resting off
two.on(() => {}); xbox.buttons[1].pressed = true; frame(); xbox.buttons[1].pressed = false;   // the middle doesn't take over
frames(10); out.third = [log.filter(x => x.startsWith("joined")), P.kind(), P.players().length];
pads[2].axes[0] = -0.9; frame(); out.pushed = [P.kind(), P.held("left")]; pads[2].axes[0] = 0; frame();
const odd = mk(3, "USB Gamepad (Vendor: 0079 Product: 0006)", ""); pads[3] = odd; frame();   // a plain USB pad (its D-pad
odd.axes[0] = 0.9; frame(); out.odd = [P.players().length, P.kind(), P.held("right")];      // often an axis): player 4
odd.axes[0] = 0; frame(); pads[3] = null; frame();
xbox.buttons[16].pressed = true; log.length = 0; frames(3); out.home = [log.length, P.held("a")];   // Home: never read
xbox.buttons[16].pressed = false;
P.player(3).rumble(1, 0.5, 50); out.shook = shook.slice();
ps.buttons[1].pressed = true; frame(); log.length = 0;            // player 1 holding B, then gone
pads[1] = null; pads[0] = null; frame(); out.gone = [log.splice(0), P.player(1).connected(), P.players().length, P.connected(), P.kind()];
pads[1] = mk(1, XBOX); frame();                                  // back: the same kind takes its own place first,
pads[0] = mk(0, BITDO); frame();                                 // anyone else the first place free
out.back = [log.splice(0), P.players().map(p => p.n + " " + p.kind()), P.player(2) === two];
out.mine = [mine[1].join(" "), mine[2].join(" ")];
console.log(JSON.stringify(out));
""", "pad.js")
        self.assertEqual(out["before"], [False, 0, False, False, False, None, "A", 0])
        self.assertEqual(out["first"], ["joined 1", "joined 2", "a press 1"])
        self.assertEqual(out["numbers"], ["1 playstation", "2 xbox"])
        self.assertEqual(out["two"], [True, "xbox", "playstation", "✕"])
        self.assertEqual(out["follow"], ["xbox", "A", True, True, True, False, True, True])
        self.assertEqual(out["held"], ["left press 2", "left repeat 2", "left repeat 2", "left release 2"])
        self.assertEqual(out["small"], [False, True])
        self.assertEqual(out["third"], [["joined 3"], "xbox", 3])
        self.assertEqual(out["pushed"], ["nintendo", True])
        self.assertEqual(out["odd"], [4, "other", True])
        self.assertEqual(out["home"], [0, False])
        self.assertEqual(out["shook"], ["2:1"])
        gone, back = out["gone"], out["back"]
        self.assertEqual(gone[0], ["b release 1", "left 1", "left 2"])
        self.assertEqual(gone[1:], [False, 4, True, "nintendo"])
        self.assertEqual(back[0], ["joined 2", "joined 1"])
        self.assertEqual(back[1], ["1 other", "2 xbox", "3 nintendo", "4 null"])   # (player 4's went away)
        self.assertTrue(back[2])
        self.assertEqual(out["mine"], ["a a b b", "left left left left b b"])   # each player's own

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_boxs_echo_keys(self):
        """The box turns every controller's presses into keys too: dropped while any controller is in use, a held
        direction included (the box repeats its arrows), and kept when none is (a remote's keys)."""
        out = self.node(r"""
const key = k => ({ key: k });
const a = mk(0, XBOX), b = mk(1, PS); pads[0] = a; frame(); pads[1] = b; frame();
on.gamepadconnected.forEach(f => f());
out.connected = [P.active(), P.echo(key("ArrowLeft")), P.echo(key("Enter")), P.echo(key("a"))];
frames(30, 100); out.idle = [P.active(), P.echo(key("ArrowLeft"))];
b.buttons[13].pressed = true; frames(30, 100);                   // player 2 holds down for 3 s
out.holding = [P.active(), P.player(2).active(), P.player(1).active(), P.echo(key("ArrowDown"))];
b.buttons[13].pressed = false; frames(30, 100); out.after = P.active();
console.log(JSON.stringify(out));
""", "pad.js")
        self.assertEqual(out["connected"], [True, True, True, False])
        self.assertEqual(out["idle"], [False, False])
        self.assertEqual(out["holding"], [True, True, False, True])
        self.assertFalse(out["after"])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_engines_input_reads_each_player(self):
        """Low3D's Input: who pressed (the player's number, 0 for a key), joined and left, and input.player(n)."""
        out = self.node(r"""
const got = [], kd = k => on.keydown.forEach(f => f({ key: k, code: k, repeat: false, preventDefault() {} }));
const input = new Low3D.Input({ keys: { ArrowLeft: "left", Enter: "a", x: "x" }, on: (b, how, who) => got.push(b + " " + how + " " + who),
  joined: n => got.push("joined " + n), left: n => got.push("left " + n) });
const a = mk(0, XBOX), b = mk(1, PS); pads[0] = a; pads[1] = b; frame();
out.players = [input.players(), input.player(2) === P.player(2), input.player(2).kind(), input.player(7).connected()];
b.buttons[0].pressed = true; frame(); b.buttons[0].pressed = false; frame();
kd("x");                                                           // a key of its own: the keyboard's, player 0
a.buttons[14].pressed = true; frame(); kd("ArrowLeft");            // the box's echo of that press: dropped
frames(10); input.tick(now); a.buttons[14].pressed = false; frame();
out.held = [input.player(1).held("left"), input.player(2).held("left")];
frames(40, 100); kd("ArrowLeft"); frames(6); input.tick(now);     // a remote's arrow, no controller in use: kept
pads[1] = null; frame();
out.got = got;
console.log(JSON.stringify(out));
""", "pad.js", "low3d.js")
        self.assertEqual(out["players"], [[1, 2], True, "playstation", False])
        self.assertEqual(out["held"], [False, False])
        self.assertEqual(out["got"], ["joined 1", "joined 2", "a press 2", "a release 2", "x press 0", "left press 1", "left release 1",
                                      "left press 0", "left 2"])


# a phone or a tablet for pad.js's touch controls: the page's size, its media queries, saved settings, a tilt sensor,
# vibration, and fingers (pointer events) put down, moved and lifted by hand
TOUCH_JS = r"""
const media = { coarse: false }, stored = {}, buzzed = [], fulls = [];
const node = () => ({ style: {}, classList: { add() {}, remove() {}, toggle() {} }, setAttribute() {}, appendChild() {}, getContext: () => null, querySelector: () => null });
def("document", { hidden: false, createElement: node, head: node(), body: node(), querySelector: () => null, addEventListener: (t, f) => (on["doc:" + t] = on["doc:" + t] || []).push(f),
  documentElement: Object.assign(node(), { requestFullscreen: () => { fulls.push(1); return Promise.resolve(); } }) });
def("getComputedStyle", () => ({ paddingTop: "0px", paddingRight: "0px", paddingBottom: "21px", paddingLeft: "0px" }));
def("innerWidth", 844); def("innerHeight", 390); def("devicePixelRatio", 3);
def("matchMedia", q => ({ matches: q === "(pointer: coarse)" ? media.coarse : false }));
def("localStorage", { getItem: k => k in stored ? stored[k] : null, setItem: (k, v) => { stored[k] = String(v); }, removeItem: k => { delete stored[k]; } });
def("screen", { orientation: { angle: 90 } }); def("removeEventListener", (t, f) => { on[t] = (on[t] || []).filter(g => g !== f); });
def("DeviceOrientationEvent", function () {}); navigator.vibrate = ms => { buzzed.push(ms); return true; };
location.pathname = "/box/games/test/";
"""
TOUCH_HELP = r"""
const T = P.touch, canvas = { getBoundingClientRect: () => ({ left: 75, top: 0, width: 693, height: 390 }) };
const finger = (type, id, x, y, kind) => (on[type] || []).forEach(f => f({ type, pointerType: kind || "touch", pointerId: id, clientX: x, clientY: y, target: {} }));
const tap = (x, y, kind) => { finger("pointerdown", 99, x, y, kind); finger("pointerup", 99, x, y, kind); };
const key = k => (on.keydown || []).forEach(f => f({ key: k, code: k, repeat: false, preventDefault() {} }));
const tilt = (beta, gamma) => (on.deviceorientation || []).forEach(f => f({ beta, gamma }));
const painter = () => { const d = []; return { d, disc: () => d.push("o"), ring: () => d.push("O"), bar: () => d.push("|"), text: s => d.push(s) }; };
"""


def touch_in_node(test, script, *files, hash=""):
    """PADS_JS with TOUCH_JS (and the address's #hash) before the files, then TOUCH_HELP and the script."""
    js = PADS_JS.replace('def("location", { hash: "" });', 'def("location", { hash: %s });' % json.dumps(hash), 1)
    js = js.replace("for (const f of process.argv", TOUCH_JS + "for (const f of process.argv", 1) + TOUCH_HELP + script
    r = subprocess.run(["node", "-e", js] + [os.path.join(BOX, "games", f) for f in files], capture_output=True, text=True, timeout=60)
    test.assertEqual(r.returncode, 0, r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


class TheTouchScreen(unittest.TestCase):
    """pad.js's touch controls (SofaPad.touch): on a phone or a tablet the game's own controls are drawn on its picture
    and read as one more player under the button names the games already read; hidden without a touch screen, and
    again when a controller or a key is used; tilt as a stick, off until asked; vibration for rumble; every game with a
    layout of its own and a home-screen app; still offline."""
    GAMES = os.path.join(BOX, "games")

    def node(self, script, *files):
        return touch_in_node(self, script, *(files or ("pad.js",)))

    def read(self, *path):
        with open(os.path.join(self.GAMES, *path), encoding="utf-8") as f:
            return f.read()

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_touch_source_gives_the_button_names(self):
        out = self.node(r"""
P.on((b, how, p) => log.push(b + " " + how + " " + (p ? p.n : "-"))); P.on("joined", p => log.push("joined " + p.n));
T.layout({ stick: "stick", buttons: [["a", "JUMP"], ["x", "HIT"], ["b", "DASH"], ["rt", "RUN"]], tilt: "x" }); T.attach(canvas);
tap(700, 60); frame();                                               // the first touch: shown, and a player of its own
out.shown = [T.on, P.connected(), P.real(), P.players().map(p => p.n + " " + p.kind()), log.splice(0)];
T.frame(false);                                                      // (drawn this frame: the controls take fingers now)
const at = n => T.ctl.find(c => c.label === n);
out.words = T.ctl.map(c => c.pause ? "II" : c.label + " " + c.word);
for (const n of ["A", "X", "B", "RT"]) { const c = at(n); finger("pointerdown", 2, c.x, c.y); frame(); finger("pointerup", 2, c.x, c.y); frame(); }
out.buttons = log.splice(0);
const A = at("A"), X = at("X"); finger("pointerdown", 3, A.x, A.y); finger("pointermove", 3, X.x, X.y); frame();   // a thumb rolls on to X
out.rolled = [P.held("a"), P.held("x")]; finger("pointerup", 3, X.x, X.y); frame(); log.length = 0;
finger("pointerdown", 4, 150, 300); finger("pointermove", 4, 210, 300); frame();   // the stick: where the thumb lands, pushed right
out.stick = [Math.round(P.stick().x * 10) / 10, Math.round(P.stick().y * 10) / 10, P.held("right"), log.splice(0)];
finger("pointerdown", 5, at("A").x, at("A").y); frame(); out.both = [P.held("a"), P.held("right")];   // two thumbs at once
finger("pointerup", 4, 210, 300); finger("pointerup", 5, 0, 0); frame(); out.let = [P.stick().x, P.held("a")]; log.length = 0;
const pz = T.ctl.find(c => c.pause); finger("pointerdown", 6, pz.x, pz.y); frame(); finger("pointerup", 6, pz.x, pz.y); frame();
out.pause = log.splice(0);
out.labels = [P.kind(), P.label("a"), P.label("start"), P.label("rt")];
T.press("x"); frame(); out.menuButton = log.splice(0);               // a menu's own button (WYRD's Salvage): x pressed a moment
P.rumble(0.8, 0.3, 120); P.rumble(0.05, 0.05, 120); out.buzz = buzzed.slice();   // rumble: a buzz (a faint one: none)
const taps = []; T.onTap(t => { taps.push(t.kind + " " + Math.round(t.x) + " " + Math.round(t.dx)); return true; });
tap(600, 120); finger("pointerdown", 7, 560, 100); finger("pointermove", 7, 640, 104); finger("pointerup", 7, 640, 104);
tap(300, 120);                                                       // off the controls: a tap and a swipe, for the game; on the
finger("pointerdown", 9, 300, 200); finger("pointermove", 9, 340, 200); finger("pointerup", 9, 340, 200);   // stick's half a tap
out.taps = taps;                                                     // is still one, a push isn't
const pt = painter(); T.draw(pt, 480, 270); out.drawn = pt.d.filter(x => x.length > 1 && x !== "II").concat(pt.d.filter(x => x === "o").length);
T.layout({ stick: "dpad", buttons: [["a", "CHOOSE"]] }); T.frame(false); log.length = 0;   // a D-pad: four ways, for grids
finger("pointerdown", 8, T.R.sx - 40, T.R.sy + 5); frame(); out.dpad = [P.held("left"), P.button("left"), P.held("down")];
finger("pointermove", 8, T.R.sx + 3, T.R.sy + 40); frame(); out.dpad2 = [P.button("left"), P.button("down")]; finger("pointerup", 8, 0, 0); frame();
out.dlog = log.splice(0).filter(x => !x.startsWith("joined"));
console.log(JSON.stringify(out));
""")
        self.assertEqual(out["shown"], [True, True, False, ["1 touch"], ["joined 1"]])
        self.assertEqual(out["words"], ["A JUMP", "X HIT", "B DASH", "RT RUN", "II"])
        self.assertEqual(out["buttons"], ["a press 1", "a release 1", "x press 1", "x release 1", "b press 1", "b release 1", "rt press 1", "rt release 1"])
        self.assertEqual(out["rolled"], [False, True])
        self.assertEqual(out["stick"][:3], [1, 0, True])
        self.assertEqual(out["stick"][3], ["right press 1"])
        self.assertEqual(out["both"], [True, True])
        self.assertEqual(out["let"], [0, False])
        self.assertEqual(out["pause"], ["start press 1", "start release 1"])
        self.assertEqual(out["labels"], ["touch", "A", "II", "RT"])
        self.assertEqual(out["menuButton"], ["x press 1"])
        self.assertEqual(len(out["buzz"]), 1)
        self.assertEqual(out["taps"], ["tap 600 0", "swipe 640 80", "tap 300 0"])
        self.assertEqual(out["drawn"], ["JUMP", "HIT", "DASH", "RT", "RUN", 7])   # discs: the stick and its knob, 4 buttons, pause
        self.assertEqual(out["dpad"], [True, True, False])
        self.assertEqual(out["dpad2"], [False, True])
        self.assertEqual(out["dlog"], ["left press 1", "down press 1", "left release 1", "down release 1"])   # (in a frame: pad.js's order)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_hidden_without_a_touch_screen(self):
        """No touch screen (the box, a computer): nothing shown, drawn, joined or asked for; a mouse is no touch. A
        controller or a key used hides the controls again, and the next touch brings them back."""
        out = self.node(r"""
T.layout({ stick: "stick", buttons: [["a", "GO"]] }); T.attach(canvas);
const pt = painter(); if (T.frame(false)) T.draw(pt, 480, 270);
tap(400, 200, "mouse"); frames(3);
out.none = [T.on, T.frame(false), pt.d.length, P.connected(), P.players().length, T.can(), fulls.length, Object.keys(stored).length];
media.coarse = true; T.layout({ stick: "stick", buttons: [["a", "GO"]] }); frame();   // a phone: shown from the start
out.phone = [T.on, T.frame(false), P.players().map(p => p.kind()), T.can()];
const xbox = mk(0, XBOX); pads[0] = xbox; frame(); out.padIdle = T.on;   // a controller there but not used: still shown
xbox.buttons[0].pressed = true; frame(); xbox.buttons[0].pressed = false; frame();   // used: the controls go
out.pad = [T.on, T.frame(false), P.kind(), P.connected(), P.real()];
tap(400, 200); out.back = [T.on, P.kind() === "touch" || P.kind() === "xbox"];
key("ArrowLeft"); out.key = [T.on, T.frame(false)];
pads[0] = null; frame(); out.keyed = [P.connected(), P.real()];       // only the touch player, hidden: no controller to name
console.log(JSON.stringify(out));
""")
        self.assertEqual(out["none"], [False, False, 0, False, 0, False, 0, 0])
        self.assertEqual(out["phone"], [True, True, ["touch"], True])
        self.assertTrue(out["padIdle"])
        self.assertEqual(out["pad"], [False, False, "xbox", True, True])
        self.assertTrue(out["back"][0])
        self.assertEqual(out["key"], [False, False])
        self.assertEqual(out["keyed"], [False, False])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_demo_and_a_page_with_no_layout_show_nothing(self):
        out = self.node(r"""
media.coarse = true; tap(400, 200); frame(); out.nolayout = [T.on, P.players().length];   // (the graphics check: no layout)
console.log(JSON.stringify(out));
""")
        self.assertEqual(out["nolayout"], [False, 0])
        out = touch_in_node(self, r"""
media.coarse = true; T.layout({ buttons: [["a", "GO"]] }); tap(400, 200); frame(); out.demo = [T.on, P.players().length];
console.log(JSON.stringify(out));
""", "pad.js", hash="#demo")
        self.assertEqual(out["demo"], [False, 0])                         # the games check: the game plays itself

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_tilt_is_a_stick_when_asked(self):
        out = self.node(r"""
(async () => {
media.coarse = true; T.layout({ stick: "stick", buttons: [["a", "GO"]], tilt: "x" }); T.attach(canvas); frame();
tilt(5, -60); frame(); out.off = [T.wanted(), T.tilting(), P.stick().x];   // off until asked
let ok = null; T.tilt(true).then(v => { ok = v; }); await 0; await 0;
for (let i = 0; i < 20; i++) tilt(5, -60); frame(); const level = P.stick().x;   // held on its side (90°), level
for (let i = 0; i < 25; i++) tilt(22, -60); frame(); const right = P.stick();     // its right side tipped down
for (let i = 0; i < 25; i++) tilt(-12, -60); frame(); const left = P.stick().x;
out.on = [ok, T.tilting(), Math.abs(level) < 0.2, right.x > 0.6, right.y, left < -0.4, stored["sofa:tilt:/box/games/test/"]];
T.frame(false); finger("pointerdown", 1, 150, 300); finger("pointermove", 1, 100, 300); frame();   // a thumb on the stick wins
out.thumb = P.stick().x < -0.6; finger("pointerup", 1, 100, 300);
T.tilt(false); for (let i = 0; i < 5; i++) tilt(22, -60); frame(); out.offAgain = [T.wanted(), P.stick().x, stored["sofa:tilt:/box/games/test/"]];
DeviceOrientationEvent.requestPermission = () => Promise.resolve("denied");      // (an iPhone that says no)
T.tilt(true).then(v => { ok = v; }); await 0; await 0; await 0; out.denied = [ok, T.wanted()];
T.layout({ stick: "dpad", buttons: [["a", "GO"]], tilt: false }); out.noTilt = T.can();
console.log(JSON.stringify(out)); })();
""")
        self.assertEqual(out["off"], [False, False, 0])
        self.assertEqual(out["on"], [True, True, True, True, 0, True, "1"])   # tilt "x": forward and back stay the buttons'
        self.assertTrue(out["thumb"])
        self.assertEqual(out["offAgain"], [False, 0, "0"])
        self.assertEqual(out["denied"], [False, False])
        self.assertFalse(out["noTilt"])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_engines_draw_it_and_take_taps(self):
        """Low3D adds the controls to its UI list only on the frames they show and leaves the game's list as it was;
        its menus and Low2D's are worked by tapping; Low2D's own taps reach a game's tap() in the picture's pixels."""
        out = self.node(r"""
const L2 = window.Low2D, wait = ms => new Promise(r => setTimeout(r, ms));
(async () => {
media.coarse = true; T.layout({ stick: "stick", buttons: [["a", "GO"], ["b", "BACK"]], tilt: "xy" });
const ui = new Low3D.UI(); ui.begin(640, 360); ui.text("LAP 1/3", 4, 4, 2, 0xffffff); const n0 = ui.n;
T.attach(canvas); T.frame(false); T.draw(Low3D.touchPaint(ui), ui.w, ui.h);
out.ui = [n0, ui.n > n0 + 6];
// Low2D: a menu row tapped is chosen; an option's left side goes back a value; outside the panel: back
const cv = { width: 0, height: 0, style: {}, getContext: () => null, getBoundingClientRect: () => ({ left: 75, top: 0, width: 693, height: 390 }) };
const got = [];
const G = L2.game({ id: "touch-test", canvas: cv, update() {}, draw() {}, tap: (x, y) => { got.push("game " + Math.round(x) + " " + Math.round(y)); return true; } });
G.start(); await wait(40); frames(4, 1000 / 60);
const menu = new L2.Menu(G, { top: "title", screens: { title: { items: [{ t: "PLAY", act: "play" }, { t: "OPTIONS", act: "opts" }] },
  opts: { back: "title", items: L2.optionItems() } }, choose: it => got.push("choose " + it.act) });
G.menu = menu; menu.show("title"); menu.box = { x: 122, y: 100, w: 236, h: 70 }; menu.itemsY = 110; menu.lh = 17;
const px = (x, y) => ({ kind: "tap", x: 75 + x * 693 / 480, y: y * 390 / 270, dx: 0, dy: 0, target: {} });
G.tapped(px(200, 108 + 17 + 5));                                     // the second row
menu.show("opts"); out.tiltRow = menu.list.some(it => it.k === "tilt");
menu.box = { x: 122, y: 30, w: 236, h: 200 }; menu.itemsY = 40; menu.lh = 17; G.opts.music = 5;
G.tapped(px(300, 40 + 2)); out.down = G.opts.music; G.tapped(px(352, 40 + 2)); out.music = G.opts.music;   // the value's left half, then right
G.tapped(px(20, 20)); out.at = menu.at;                              // outside the panel: back
menu.hide(); G.tapped(px(240, 135));                                 // no menu: the game's own tap, in its pixels
out.got = got;
console.log(JSON.stringify(out)); })();
""", "pad.js", "low3d.js", "low2d.js")
        self.assertEqual(out["ui"][0], 6)                                  # (the game's six letters)
        self.assertTrue(out["ui"][1])
        self.assertTrue(out["tiltRow"])
        self.assertEqual((out["down"], out["music"]), (4, 5))
        self.assertEqual(out["at"], "title")
        self.assertEqual(out["got"], ["choose opts", "game 240 135"])

    def layouts(self):
        """Each page on the box's list: the layout it gives SofaPad.touch.layout(), read by running that block in node."""
        found = {}
        for g in CATALOG["games"]:
            html = self.read(g["id"], "index.html")
            m = re.search(r"<script>/\* touch:[^\n]*\*/\n(SofaPad\.touch\.layout\(\{.*?\}\);)\n</script>", html, re.S)
            self.assertIsNotNone(m, g["id"] + ": no touch layout")
            found[g["id"]] = (html, m)
        return found

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_every_game_declares_a_layout(self):
        found = self.layouts()
        js = "const out = {}; let at; const SofaPad = { touch: { layout: L => { out[at] = L; } } };\n" + "".join(
            "at = %s; %s\n" % (json.dumps(gid), m.group(1)) for gid, (html, m) in found.items()) + "console.log(JSON.stringify(out));"
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        L = json.loads(r.stdout)
        names = {"a", "b", "x", "y", "lb", "rb", "lt", "rt", "select", "start"}
        for gid, lay in L.items():
            html, m = found[gid]
            self.assertIn(lay.get("stick", "stick"), ("stick", "dpad", "none"), gid)
            self.assertIn(lay.get("tilt", "xy"), ("x", "xy", False), gid)
            if lay.get("none"):
                continue
            buttons = lay["buttons"] + lay.get("top", [])
            self.assertTrue(buttons, gid)
            self.assertLessEqual(len(lay["buttons"]), 8, gid)          # (the corner, a ring of four, three more)
            for b, word in buttons:
                self.assertIn(b, names, gid)
                self.assertTrue(word and word == word.upper() and len(word) <= 8, (gid, word))
                if b not in ("start", "select"):                         # the game reads each button it shows
                    self.assertTrue(re.search(r"""["']%s["']""" % b, html.replace(m.group(1), "")) or gid == "gloamwell", (gid, b))
            self.assertLess(html.index('src="../pad.js"'), m.start(), gid)   # after pad.js, before the game's own script
        self.assertEqual(L["pair-up"].get("none"), True)                  # cards are tapped
        self.assertEqual(L["rune-tactics"]["stick"], "none")                # its tiles are tapped: a D-pad would cover them
        self.assertIn("tap: (x, y) => tapAt(x, y)", found["rune-tactics"][0])          # a tile tapped
        self.assertIn("swipe: (dx, dy) => swipeBy(dx, dy)", found["cosmic-cascade"][0])  # a gem swiped
        self.assertTrue(L["void-drifter"]["look"] and L["ironmaw"]["look"])  # aiming with the right thumb
        if "wyrd" in L:                                                   # (once WYRD is on the list)
            self.assertEqual([b for b, w in L["wyrd"]["buttons"]][:1], ["a"])

    def test_screens_safe_areas_and_the_home_screen(self):
        """Every game: the screen's safe areas reported to it (viewport-fit=cover), and an app for the home screen
        (its manifest and icons, made by tools/game-apps.py from games.json and up to date), all from its own folder."""
        for g in CATALOG["games"]:
            html = self.read(g["id"], "index.html")
            self.assertIn('content="width=device-width, initial-scale=1, viewport-fit=cover"', html, g["id"])
            man = json.loads(self.read(g["id"], "app.webmanifest"))
            self.assertEqual((man["name"], man["start_url"], man["display"]), (g["name"], "./", "fullscreen"), g["id"])
            for icon in man["icons"]:
                self.assertNotRegex(icon["src"], r"[:/]", g["id"])       # its own folder: offline, and the same in the arcade
                with open(os.path.join(self.GAMES, g["id"], icon["src"]), "rb") as f:
                    self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(BOX), "..", "tools", "game-apps.py"), "--check"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pad = self.read("pad.js")                                          # pad.js: offline, and asks only from a tap
        self.assertNotRegex(pad, r"""(src|href|url)\s*[=(]\s*["']?(https?:)?//""")
        for online in ("fetch(", "XMLHttpRequest", "WebSocket", "importScripts", "@import", "<link", "sendBeacon"):
            self.assertNotIn(online, pad)
        self.assertNotRegex(pad, r"buttons\[16\]")                        # Home is still the box's
        self.assertIn('href: "app.webmanifest"', pad)
        with open(os.path.join(BOX, "sofa-box-agent.py"), encoding="utf-8") as f:   # the box serves it as one
            self.assertIn('".webmanifest": "application/manifest+json"', f.read())


class TheLoopAndWhatIsKept(unittest.TestCase):
    """Two things found reading 1.1.64's engine, after it was merged: a game ran slow or fast on a screen that isn't
    60 Hz, and a rung kept for a box under an older version's ladder was read back on the new one."""
    GAMES = os.path.join(BOX, "games")

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_game_runs_at_real_time_on_any_screen(self):
        """The loop's steps were rounded to the frame when a frame was within a fifth of a step of a whole number, and
        what was left over was dropped: 83% of real time at 50 Hz, 120% at 72, 125% at 75. Such a frame's time is
        carried now, never dropped; a 60 Hz screen still gets one step every frame, however its clock wobbles. (A screen
        that's nearly 60 Hz runs on its own beat, within 1.5% of real time: the next test.)"""
        out = pads_in_node(self, r"""
const L = window.Low3D, DT = 1 / 60;
const run = (hz, frames, wobble) => { let acc = 0, n = 0, t = 0, odd = 0; for (let i = 0; i < frames; i++) { const dt = 1 / hz + (wobble ? (i & 1 ? wobble : -wobble) : 0); t += dt; const S = L.wholeSteps(acc, dt, DT, 6); acc = S[1]; n += S[0]; if (S[0] !== 1) odd++; } return [Math.round(n * DT / t * 1000) / 10, odd]; };
out.speed = {}; for (const hz of [50, 59.94, 60, 72, 75, 90, 100, 120, 144]) out.speed[hz] = run(hz, 600)[0];
out.steady = run(60, 600, 0.002)[1];                                  // 60 Hz, each frame 2 ms early or late: one step every frame
out.pause = Array.from(L.wholeSteps(0, 0.25, DT, 6));                 // a long pause isn't caught up on
out.carried = L.wholeSteps(0, 0.02, DT, 6)[1] > 0;                    // (50 Hz: a fifth of a step over, kept for the next frame)
console.log(JSON.stringify(out));
""", "pad.js", "low3d.js")
        for hz, pct in out["speed"].items():
            self.assertTrue(99.5 <= pct <= 100.5, "%s Hz: %s%% of real time" % (hz, pct))
        self.assertEqual(out["steady"], 0)
        self.assertEqual(out["pause"], [6, 0])
        self.assertTrue(out["carried"])
        with open(os.path.join(self.GAMES, "low3d.js"), encoding="utf-8") as f:
            l3 = f.read()
        with open(os.path.join(self.GAMES, "low2d.js"), encoding="utf-8") as f:
            l2 = f.read()
        self.assertIn("const S = wholeSteps(acc, dt, E.DT, 6); acc = S[1];", l3)   # the 3D engine's loop uses it,
        self.assertNotIn("acc = 0.0005", l3)                              # (and no longer drops what's left over)
        self.assertIn("const S = L3.wholeSteps(acc, dt, G.DT, 4); acc = S[1];", l2)   # and the 2D engine's
        # the 2D engine's own loop, frame by frame, on screens of 50, 60, 65, 72 and 75 Hz: ten seconds is 600 steps
        steps = pads_in_node(self, L2_JS + r"""(async () => {
location.hash = "#tier=light&pace=60";
for (const hz of [50, 60, 65, 72, 75]) {
  let ups = 0; const G = L2.game({ id: "hz" + hz, canvas: canvas(), update() { ups++; }, draw() {} });
  G.start(); await wait(40); frames(8, 1000 / hz); ups = 0; frames(hz * 10, 1000 / hz); out[hz] = ups;
}
console.log(JSON.stringify(out)); })().catch(e => { console.error(e); process.exit(1); });""", "pad.js", "low3d.js", "low2d.js")
        for hz, n in steps.items():
            self.assertTrue(598 <= n <= 602, "%s Hz: %s steps in ten seconds" % (hz, n))

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_screen_thats_nearly_60_hz_gets_the_same_steps_every_frame(self):
        """1.1.68 carried all of a frame's time, which is right to the second and, on a screen a little off 60 Hz (59.94
        on a TV, 59.79 on a 1366 x 768 panel, 60.02, 60.32), takes two steps in one frame or none every few seconds: a
        skip, where the loop before it was even. A frame whose own length is a whole number of steps to within 1.5%
        takes exactly that many now, so such a screen runs on its own beat; the rest still run at real time. Ten
        minutes at each rate, the page's clock rounded down to a tenth of a millisecond as the browser hands it over.
        And a clock that wobbles: a frame on the beat lets go, a little at a time, of what the frames off it left
        carried (left alone it wandered until a frame took two steps or none: on a 60.000 Hz screen too, with the
        frame's time off by a tenth of a millisecond, where 1.1.68 was even)."""
        out = pads_in_node(self, r"""
const L = window.Low3D, DT = 1 / 60;
const run = (hz, every) => {                                          // every: one frame in so many drawn (a 30 a second rung: 2)
  let acc = 0, n = 0, last = 0; const seen = {}, total = Math.round(600 * hz / every);
  for (let i = 1; i <= total; i++) { const at = Math.floor(i * every * 10000 / hz) / 10000, S = L.wholeSteps(acc, at - last, DT, 6); last = at; acc = S[1]; n += S[0]; seen[S[0]] = (seen[S[0]] || 0) + 1; }
  return { pct: Math.round(n * DT / last * 10000) / 100, steps: Object.keys(seen).map(Number).sort() };
};
out.near = {}; for (const hz of [59.79, 59.89, 59.94, 59.95, 60, 60.02, 60.317]) out.near[hz] = [run(hz, 1), run(hz, 2)];
out.far = {}; for (const hz of [50, 65, 72, 75, 144]) out.far[hz] = run(hz, 1); for (const hz of [90, 100]) out.far[hz] = run(hz, 2);
out.dropped = Array.from(L.wholeSteps(0.004, 2 / 59.94, DT, 6));      // a frame missed on a 59.94 Hz screen: two steps, and a twentieth of a step of what was carried let go
out.let = [L.wholeSteps(0.0005, DT, DT, 6)[1], L.wholeSteps(-0.0005, DT, DT, 6)[1], L.wholeSteps(-0.004, DT, DT, 6)[1]];
// clocks that wobble (the same numbers every run): steps a frame over ten minutes, after the first two seconds
let seed = 1; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }, norm = () => Math.sqrt(-2 * Math.log(rnd() || 1e-9)) * Math.cos(6.283185307 * rnd());
const wobble = (hz, every, tick, err, s) => {
  seed = s; let acc = 0, n = 0, uneven = 0, last = 0; const usual = Math.round(every * 60 / hz), total = Math.round(600 * hz / every);
  for (let i = 1; i <= total; i++) { const at = Math.floor((i * every / hz + err()) / tick + 1e-9) * tick, S = L.wholeSteps(acc, Math.max(0, at - last), DT, 6); last = at; acc = S[1]; n += S[0]; if (i > 120 && S[0] !== usual) uneven++; }
  return [uneven, Math.round(n * DT / last * 10000) / 100];
};
const off = sd => () => norm() * sd / 1000, late = mean => () => -Math.log(rnd() || 1e-9) * mean / 1000;
out.wobble = {};
for (const sd of [0.05, 0.1, 0.2, 0.5]) out.wobble["60 Hz, off by " + sd + " ms"] = [1, 2, 3].map(s => wobble(60, 1, 0.0001, off(sd), s * 7919));
out.wobble["60 Hz, late by 0.5 ms"] = [1, 2, 3].map(s => wobble(60, 1, 0.0001, late(0.5), s * 7919));
out.wobble["60 Hz, a clock in whole milliseconds, every other frame"] = [wobble(60, 2, 0.001, () => 0, 1)];
out.wobble["59.94 Hz, off by 0.5 ms"] = [1, 2, 3].map(s => wobble(59.94, 1, 0.0001, off(0.5), s * 7919));
out.wobble["120 Hz, every other frame, off by 0.5 ms"] = [1, 2, 3].map(s => wobble(120, 2, 0.0001, off(0.5), s * 7919));
out.pause = Array.from(L.wholeSteps(0, 0.25, DT, 6)); out.exactPause = Array.from(L.wholeSteps(0.003, 0.1, DT, 6));   // (six steps' worth, the most: not on the beat, and not caught up on)
console.log(JSON.stringify(out));
""", "pad.js", "low3d.js")
        for hz, (each, other) in out["near"].items():
            self.assertEqual(each["steps"], [1], "%s Hz: every frame one step" % hz)
            self.assertEqual(other["steps"], [2], "%s Hz, every other frame drawn: two steps each" % hz)
            self.assertTrue(98.5 <= each["pct"] <= 101.5 and each["pct"] == other["pct"], "%s Hz: %s%% of real time" % (hz, each["pct"]))
        self.assertEqual(out["near"]["59.94"][0]["pct"], 99.9)            # (on its own beat: a tenth of a percent slow, as before 1.1.68)
        for hz, r in out["far"].items():
            self.assertTrue(99.8 <= r["pct"] <= 100.2, "%s Hz: %s%% of real time" % (hz, r["pct"]))
        self.assertEqual(out["far"]["50"]["steps"], [1, 2])               # (50 Hz: one, one, one, one, two: as it must be)
        self.assertEqual(out["dropped"][0], 2)
        self.assertAlmostEqual(out["dropped"][1], 0.004 - 1 / 60 / 20, places=9)
        self.assertEqual(out["let"][:2], [0, 0])                          # (under a twentieth of a step: gone)
        self.assertAlmostEqual(out["let"][2], -0.004 + 1 / 60 / 20, places=9)
        for name, runs in out["wobble"].items():
            for uneven, pct in runs:
                self.assertEqual(uneven, 0, "%s: %s uneven frames in ten minutes" % (name, uneven))
                self.assertTrue(99.85 <= pct <= 100.15, "%s: %s%% of real time" % (name, pct))
        self.assertEqual((out["pause"], out["exactPause"]), ([6, 0], [6, 0]))
        # the 2D engine's own loop on a 59.94 Hz screen with that clock: a step every frame for a minute
        even = pads_in_node(self, L2_JS + r"""(async () => {
location.hash = "#tier=light&pace=60";
let ups = 0; const G = L2.game({ id: "ntsc", canvas: canvas(), update() { ups++; }, draw() {} });
G.start(); await wait(40); frames(8, 1000 / 60);
let at = 0, odd = 0; for (let i = 1; i <= 3600; i++) { const t = Math.floor(i * 10000 / 59.94) / 10; ups = 0; frame(t - at); at = t; if (ups !== 1) odd++; }
out.odd = odd;
console.log(JSON.stringify(out)); })().catch(e => { console.error(e); process.exit(1); });""", "pad.js", "low3d.js", "low2d.js")
        self.assertEqual(even["odd"], 0)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_rung_kept_on_another_ladder_is_not_used(self):
        """What a game keeps for a box ("<id>:tune": the rung its governor settled on, and how high it may go) is a
        number on the ladder as it was. 1.1.64 and 1.1.66 changed both ladders, so a box that had played before came
        back on the wrong rung with the wrong top (a Pi 3 with rung 1, top 3 kept: 360 lines at 30, never over 270 at
        60). What's kept says which ladder now, and is used on no other; the box's test result is still used."""
        out = pads_in_node(self, r"""
const store = {}; def("localStorage", { getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } });
def("ImageData", class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } });
def("devicePixelRatio", 2); def("innerWidth", 960); def("innerHeight", 540);
const gl = new Proxy({}, { get: (t, k) => typeof k === "string" && /^[A-Z][A-Z0-9_]+$/.test(k) ? 1 : () => 1 });   // (a GPU that says yes to everything)
const cv = () => ({ classList: { toggle() {}, add() {}, remove() {} }, addEventListener() {}, style: {}, width: 0, height: 0,
  getContext: kind => kind === "webgl" ? gl : { putImageData() {}, drawImage() {} } });
document.createElement = () => cv();
const view = { style: { setProperty() {} } }, L = window.Low3D;
const pi3 = { key: "pi3|VC4|156|4|1", family: "pi3", cores: 4, webgl1: true, software: false, renderer: "VC4 V3D 2.1" }, bench = { cpu: 95, draws: 32, fill: 2, hz: 60, ms: 2000 };
const open = (id, kind) => {                                         // a game opened on that box, as start() leaves it before the first frame
  const E = L.game({ id, kind, view, gl: cv(), flat: cv(), update() {}, draw() {}, resized() {} });
  E.probe = pi3; E.bench = bench; E.plan = kind === "ray" ? L.planRay(pi3, bench) : L.plan(pi3, bench); E.renderer(true);
  return E;
};
const at = E => [E.mode, E.gov.rung, E.gov.top];
out.fresh = [at(open("a", null)), at(open("b", "ray"))];              // nothing kept: where a Pi 3 starts
// kept by 1.1.63 and before (main's ladders then: a Pi 3 on 3D rung 1 of at most 3; drawn by the processor, rung 2 of at most 3)
store["tw:tune"] = JSON.stringify({ key: pi3.key, bench, mode: "gl", rung: 1, top: 3 });
store["im:tune"] = JSON.stringify({ key: pi3.key, bench, mode: "ray", rung: 2, top: 3 });
out.old = [at(open("tw", null)), at(open("im", "ray"))];
// kept by this version, on these ladders: used
const E = open("new", null); E.gov.set(3, "late 20%"); out.kept = JSON.parse(store["new:tune"]);
out.again = at(open("new", null));
out.sig = [L.ladderSig(L.LADDER.gl).split(" ").length, L.ladderSig(L.LADDER.ray).split(" ")[4]];
console.log(JSON.stringify(out));
""", "pad.js", "low3d.js")
        self.assertEqual(out["fresh"], [["gl", 4, 5], ["ray", 4, 6]])
        self.assertEqual(out["old"], out["fresh"])                        # an older version's rungs: not these ladders'
        self.assertEqual((out["kept"]["rung"], out["kept"]["mode"]), (3, "gl"))
        self.assertIn("360@60", out["kept"]["lad"])                       # what's kept says which ladder it's on
        self.assertEqual(out["again"], ["gl", 3, 5])                      # and on that ladder it's used
        self.assertEqual(out["sig"], [9, "135@60"])
        with open(os.path.join(self.GAMES, "low2d.js"), encoding="utf-8") as f:
            l2 = f.read()
        self.assertIn('tune.ladder === look + "/" + pace && tune.sig === sig() && tune.rung != null', l2)   # the 2D engine's too


class EvenFrames(unittest.TestCase):
    """Frames that stay on the screen the same time look smooth: one refresh each at 60 a second on a 60 Hz screen, two
    at 30, three at 40 on a 120 Hz one. The governor draws a frame when the whole number of refreshes nearest the
    rung's interval has passed, learning the refresh from every one; a rung at 40 is offered only where 40 is even."""
    GAMES = os.path.join(BOX, "games")

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_frames_are_the_same_number_of_refreshes_apart(self):
        """A minute at each screen rate and each rung's rate, the refresh times off by up to 0.3 ms and rounded down
        to a tenth of a millisecond as a browser hands them over; the governor told the screen is 60 Hz whatever it
        is, so it has to learn. (1.1.70 drew when the interval less 4 ms had passed: 144 Hz at 40 and every rate at
        240 Hz went three refreshes, four, three.)"""
        out = pads_in_node(self, r"""
const L = window.Low3D;
let seed = 7; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
out.per = {};
for (const hz of [50, 59.94, 60, 75, 120, 144, 240]) for (const fps of [60, 40, 30]) {
  const g = new L.Governor([{ fps }], 0, 0); g.lock = true;
  const per = {}; let last = -1;
  for (let i = 0; i < hz * 60; i++) {
    const t = Math.floor((1000 + i * 1000 / hz + (rnd() - 0.5) * 0.6) * 10) / 10;
    if (g.tick(t)) { if (last >= 0 && i > hz * 2) per[i - last] = (per[i - last] || 0) + 1; last = i; }
  }
  out.per[hz + "@" + fps] = Object.keys(per).map(Number);
}
// a governor too busy for its rate, on a 120 Hz screen: 60, then 40, then 30 (a frame's work keeps the next refreshes waiting)
const lad = L.withForty(L.LADDER.gl, 120), g = new L.Governor(lad, 3, lad.length - 1), ref = 1000 / 120; g.ref = ref;
let t = 1000; const busy = r => lad[g.rung].fps === 60 ? 26 : 40;
for (let n = 0; n < 4000 && g.rung > 1; n++) { if (g.tick(t)) { const w = busy(); g.work(w); t += Math.max(1, Math.ceil(w / ref)) * ref; } else t += ref; }
out.path = g.log.map(l => l.match(/(\d)→(\d)/).slice(1).join(">")); out.fps = lad.map(r => r.fps);
console.log(JSON.stringify(out));
""", "pad.js", "low3d.js")
        want = {"50@60": 1, "50@40": 2, "50@30": 2, "59.94@60": 1, "59.94@30": 2, "60@60": 1, "60@30": 2, "75@60": 1, "75@40": 2, "75@30": 3,
                "120@60": 2, "120@40": 3, "120@30": 4, "144@60": 2, "144@40": 4, "144@30": 5, "240@60": 4, "240@40": 6, "240@30": 8}
        for k, n in want.items():
            self.assertEqual(out["per"][k], [n], "%s Hz: every frame %d refreshes apart" % (k, n))
        self.assertEqual(out["fps"][:4], [30, 30, 40, 60])
        self.assertEqual(out["path"], ["3>2", "2>1"])                     # too busy at 60: 40; too busy at 40: 30

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_rung_at_40_only_where_it_is_even(self):
        """On a 60 Hz screen 40 a second can't be even (one refresh, then two), so no ladder there has it, and what a box
        kept for its rungs stays good; on a screen that's a multiple of 40 each ladder gets one, between its 30s and
        60s, and a box starts on the same picture as before."""
        out = pads_in_node(self, r"""
const L = window.Low3D;
out.on = {}; for (const hz of [50, 60, 72, 75, 80, 90, 100, 119, 120, 144, 160, 165, 240]) out.on[hz] = L.fortyOn(hz);
const at = (lad, hz) => { const l = L.withForty(lad, hz); return l === lad ? null : [l.forty, l[l.forty].h, l[l.forty].fps, l[l.forty - 1].fps, l[l.forty + 1].fps]; };
out.gl = [at(L.LADDER.gl, 60), at(L.LADDER.gl, 120)]; out.ray = at(L.LADDER.ray, 240); out.flat = at(L.LADDER.flat, 120);
out.held = [at(L.heldRay(0, 30), 120), at(L.heldRay(0, 60), 120), at(L.heldRay(135, 0), 120)];
out.same = L.withForty(L.LADDER.gl, 60) === L.LADDER.gl;
const store = {}; def("localStorage", { getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } });
def("ImageData", class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } });
def("devicePixelRatio", 2); def("innerWidth", 960); def("innerHeight", 540);
const gl = new Proxy({}, { get: (t, k) => typeof k === "string" && /^[A-Z][A-Z0-9_]+$/.test(k) ? 1 : () => 1 });
const cv = () => ({ classList: { toggle() {}, add() {}, remove() {} }, addEventListener() {}, style: {}, width: 0, height: 0, getContext: kind => kind === "webgl" ? gl : { putImageData() {}, drawImage() {} } });
document.createElement = () => cv();
const view = { style: { setProperty() {} } };
const pc = { key: "pc|GPU|157|8|8", family: "desktop", cores: 8, webgl1: true, software: false, renderer: "a desktop GPU" };
const open = (id, kind, hz) => { const bench = { cpu: 4, draws: 512, fill: 16, hz, ms: 2000 }, E = L.game({ id, kind, view, gl: cv(), flat: cv(), update() {}, draw() {}, resized() {} });
  E.probe = pc; E.bench = bench; E.plan = kind === "ray" ? L.planRay(pc, bench) : L.plan(pc, bench); E.renderer(true); return E; };
const a = open("a", null, 60), b = open("b", null, 120), c = open("c", "ray", 120);
out.start = [[a.rung.h, a.rung.fps, a.lad.length], [b.rung.h, b.rung.fps, b.lad.length], [c.rung.h, c.rung.fps, c.lad.some(r => r.fps === 40)]];
out.ref = [Math.round(a.gov.ref * 100) / 100, Math.round(b.gov.ref * 100) / 100];
console.log(JSON.stringify(out));
""", "pad.js", "low3d.js")
        on = [int(hz) for hz, yes in out["on"].items() if yes]
        self.assertEqual(sorted(on), [80, 119, 120, 160, 240])
        self.assertIsNone(out["gl"][0])
        self.assertTrue(out["same"])                                      # (the very ladder: its line, and what boxes kept, unchanged)
        self.assertEqual(out["gl"][1], [2, 360, 40, 30, 60])             # the best 30's picture, at 40, between the 30s and the 60s
        self.assertEqual(out["ray"], [2, 135, 40, 30, 60])
        self.assertEqual(out["flat"], [3, 160, 40, 30, 60])
        self.assertEqual(out["held"][:2], [None, None])                   # a rate held: no 40
        self.assertEqual(out["held"][2], [1, 135, 40, 30, 60])            # a size held: at 30, 40 and 60
        a, b, c = out["start"]
        self.assertEqual((a[2] + 1, b[2]), (b[2], b[2]))                  # one rung more at 120 Hz,
        self.assertEqual(a[:2], b[:2])                                    # the same picture to start
        self.assertTrue(c[2])
        self.assertEqual(out["ref"], [16.67, 8.33])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_2d_engine_too(self):
        out = pads_in_node(self, L2_JS + r"""(async () => {
const L3 = window.Low3D, names = l => l.map(name);
out.at60 = names(L3.withForty(L2.ladder("auto", "auto"), 60)); out.at120 = names(L3.withForty(L2.ladder("auto", "auto"), 120));
out.held = [names(L3.withForty(L2.ladder("auto", "60"), 120)), names(L3.withForty(L2.ladder("light", "auto"), 120))];
console.log(JSON.stringify(out)); })().catch(e => { console.error(e); process.exit(1); });""", "pad.js", "low3d.js", "low2d.js")
        self.assertEqual(out["at60"], ["light30", "full30", "light60", "full60", "rich60"])
        self.assertEqual(out["at120"], ["light30", "full30", "full40", "light60", "full60", "rich60"])
        self.assertEqual(out["held"], [["light60", "full60", "rich60"], ["light30", "light40", "light60"]])
        with open(os.path.join(self.GAMES, "low2d.js"), encoding="utf-8") as f:
            l2 = f.read()
        self.assertIn("G.ladder = L3.withForty(ladder(look, pace), G.bench && G.bench.hz);", l2)

    def test_gloamwell_goes_to_a_steady_30_not_60_with_gaps(self):
        """Gloamwell has its own loop: when its fewest extras still run late it draws every other refresh, and its
        stand-in (#slow) waits out its script only, as the engines' do."""
        with open(os.path.join(self.GAMES, "gloamwell", "index.html"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("if (half && last && (now - last) / 1000 < baseDT * 1.5) return;", src)
        self.assertIn("else if (!half) { half = true; paceFail++; paceGood = 0; }", src)
        self.assertIn("if (workAvg < baseDT * 1000 * 0.45 && paceFail < 2)", src)
        self.assertNotIn("getImageData(0, 0, 1, 1); const until", src)   # (the stand-in no longer waits out the browser's drawing)


class TheGamesCheck(unittest.TestCase):
    """The graphics check's games check (probe/): each game opened with #demo in a frame of its page and timed; a game
    says what it chose, and whether it's playing itself, in window.SofaStats (Low3D games get it from the engine)."""
    GAMES = os.path.join(BOX, "games")

    def read(self, *path):
        with open(os.path.join(self.GAMES, *path), encoding="utf-8") as f:
            return f.read()

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_engine_says_how_it_goes(self):
        out = pads_in_node(self, r"""
const cv = () => ({ classList: { toggle() {}, add() {}, remove() {} }, addEventListener() {}, getContext: () => null, style: {} });
const view = { style: { setProperty() {} } }, L = window.Low3D;
location.hash = "#demo";
const E = L.game({ id: "check", view, gl: cv(), flat: cv(), update() {}, draw() {} });
out.before = [E.demo, SofaStats.ready, SofaStats.tier, SofaStats.fps, SofaStats.demo];
E.mode = "gl"; E.gov = new L.Governor(L.LADDER.gl, 3, 5); E.ready = true;   // as it is once tuned to the box
for (let i = 0; i < 100; i++) E.gov.work(4);
SofaStats.demo = true;
out.after = [SofaStats.ready, SofaStats.tier, SofaStats.workMs, SofaStats.demo];
location.hash = "#fps"; out.plain = L.game({ id: "plain", view, gl: cv(), flat: cv(), update() {}, draw() {} }).demo;
console.log(JSON.stringify(out));
""", "pad.js", "low3d.js")
        self.assertEqual(out["before"], [True, False, None, 0, False])
        ready, tier, work, demo = out["after"]
        self.assertEqual((ready, tier, demo), (True, "3D rung 3 of 8", True))
        self.assertTrue(3.9 < work <= 4, work)
        self.assertFalse(out["plain"])

    def test_the_check_page(self):
        import re
        probe = self.read("probe", "index.html")
        self.assertIn('fetch("../games.json")', probe)                  # every game on the list, in turn,
        self.assertIn('"/#demo"', probe)                                # opened to play by itself,
        self.assertIn('setAttribute("inert", "")', probe)              # in a frame that can't take the keys,
        self.assertIn("getGamepads", probe)                             # nor the controller (B stops the check)
        for column in ("Frames a second", "Late (over 25 ms)", "Slowest", "Memory", "It chose"):
            self.assertIn(column, probe)
        self.assertIn("../low3d.js", probe)
        # the games that play by themselves say so, and keep nothing while they do
        for gid in ("tidewing", "cosmic-cascade", "micro-drifters", "shadow-heist", "gloamwell", "cinder-knight", "neon-brawler", "rune-tactics", "void-drifter"):
            html = self.read(gid, "index.html")
            self.assertRegex(html, r"SofaStats(\.demo = true|=\{demo:true\}| = \{ demo: true \})", gid)
        drifters = self.read("micro-drifters", "index.html")
        self.assertIn('new L2.Store("micro-drifters"', drifters)       # (its records, kept by Low2D's Store: nothing in #demo)
        self.assertIn("if (E.demo) return;", self.read("tidewing", "index.html"))
        self.assertIn("if (!P || DEMO) return;", self.read("gloamwell", "index.html"))   # (Gloamwell's demo: no saves)
        self.assertTrue(re.search(r"E\.demo = /demo/\.test\(H\)", self.read("low3d.js")))


class TheEngine(unittest.TestCase):
    """Low3D (games/low3d.js), the box's own game engine: offline, on the controller, and the drawing each box gets."""
    GAMES = os.path.join(BOX, "games")

    def read(self, *path):
        with open(os.path.join(self.GAMES, *path), encoding="utf-8") as f:
            return f.read()

    def test_offline_and_from_the_box(self):
        js = self.read("low3d.js")
        self.assertNotRegex(js, r"""(src|href|url)\s*[=(]\s*["']?(https?:)?//""")
        for online in ("fetch(", "XMLHttpRequest", "WebSocket", "importScripts", "@import", "<link"):
            self.assertNotIn(online, js)
        self.assertNotRegex(js, r"buttons\[16\]")                     # Home is the box's
        on_engine = []
        for g in CATALOG["games"]:
            html = self.read(g["id"], "index.html")
            if "../low3d.js" in html:                                    # pad.js first: the engine's input reads it
                on_engine.append(g["id"])
                self.assertLess(html.index('src="../pad.js"'), html.index('src="../low3d.js"'), g["id"])
                for online in ("fetch(", "XMLHttpRequest", "WebSocket"):
                    self.assertNotIn(online, html, g["id"])
        self.assertIn("tidewing", on_engine)
        self.assertIn("ironmaw", on_engine)
        js2 = self.read("low2d.js")                                      # the 2D engine: offline too, Home never read
        self.assertNotRegex(js2, r"""(src|href|url)\s*[=(]\s*["']?(https?:)?//""")
        for online in ("fetch(", "XMLHttpRequest", "WebSocket", "importScripts", "@import", "<link"):
            self.assertNotIn(online, js2)
        self.assertNotRegex(js2, r"buttons\[16\]")
        on_2d = [g["id"] for g in CATALOG["games"] if "../low2d.js" in self.read(g["id"], "index.html")]
        self.assertIn("cinder-knight", on_2d)
        self.assertIn("neon-brawler", on_2d)
        self.assertIn("micro-drifters", on_2d)
        self.assertIn("shadow-heist", on_2d)
        self.assertIn("rune-tactics", on_2d)
        self.assertIn("void-drifter", on_2d)
        self.assertIn("cosmic-cascade", on_2d)
        for gid in on_2d:                                                 # pad.js, then Low3D, then Low2D on top of it
            html = self.read(gid, "index.html")
            self.assertLess(html.index('src="../pad.js"'), html.index('src="../low3d.js"'), gid)
            self.assertLess(html.index('src="../low3d.js"'), html.index('src="../low2d.js"'), gid)
        probe = self.read("probe", "index.html")                         # the graphics check: for the owner, not on Home
        self.assertNotIn("probe", [g["id"] for g in CATALOG["games"]])
        self.assertIn("../low3d.js", probe)
        self.assertNotRegex(probe, r"""(src|href|url)\s*[=(]\s*["']?(https?:)?//""")
        self.assertEqual(sorted(__import__("re").findall(r"fetch\(\"([^\"]+)\"", probe)), ["../games.json", "/box/api/info"])   # the box only

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_pages_parse(self):
        """Every page game's own script, the engine, pad.js, the graphics check and the maker: no syntax slips."""
        import re
        tmp = tempfile.mkdtemp()
        try:
            pages = [os.path.join(g["id"], "index.html") for g in CATALOG["games"]] + [os.path.join("probe", "index.html"), os.path.join("maker", "index.html")]
            files = [os.path.join(self.GAMES, "low3d.js"), os.path.join(self.GAMES, "low2d.js"), os.path.join(self.GAMES, "pad.js")]
            for page in pages:
                for i, body in enumerate(re.findall(r"<script>(.*?)</script>", self.read(page), re.S)):
                    path = os.path.join(tmp, page.replace(os.sep, "_") + "_%d.js" % i)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(body)
                    files.append(path)
            for path in files:
                r = subprocess.run(["node", "--check", path], capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, path + "\n" + r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_camera_goes_round_two_ways(self):
        """Follow's orbit and action modes. Turning has weight: nothing inside a stick's play, a start that runs up and
        a stop that runs down, and the same turn at 30 frames a second as at 60 (and at 20). A sideways push with a
        little up in it doesn't lift the eye. Orbit never moves by itself; action comes round behind the way walked
        after a rest, not while held for free look, and not when walked straight at. A drag turns by an amount; the
        wheel's zoom is eased and kept within its ends; rising ground or a wall between pulls the eye in (near with it)
        and lets it out slowly. Fixed is as it was, and a frame makes nothing."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
globalThis.screen = { width: 1920, height: 1080 }; globalThis.innerWidth = 960; globalThis.innerHeight = 540;
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, out = {}, r = v => Math.round(v * 1000) / 1000 + 0;
const eyes = [[13.9, 9.3, 0.9, 1.2, 0.66, 0.5], [7, 11, 1.4, 7, 0.72, 8.5], [5.2, 9.5, 1.5, 6, 0.74, 7]];
const make = (mode, o) => new L.Follow(Object.assign({ eyes, mode, h: 0.5 }, o)), cam = L.camera();
// a push held for a second and let go for half of one, at a frame rate
const run = (mode, fps, x, y) => { const f = make(mode), dt = 1 / fps; let first = 0;
  for (let i = 0; i < fps; i++) { f.steer(dt, x, y); f.follow(cam, 0, 0, 0, dt); if (!i) first = f.turn; }
  const held = f.turn; for (let i = 0; i < fps / 2; i++) { f.steer(dt, 0, 0); f.follow(cam, 0, 0, 0, dt); }
  return { first, held, rest: f.turn, h: f.h, tv: f.tv }; };
for (const mode of ["orbit", "action"]) {
  const a = run(mode, 60, 1, 0), b = run(mode, 30, 1, 0), c = run(mode, 20, 1, 0);
  out[mode] = { held: r(a.held), same: Math.abs(a.held - b.held) < 1e-6 && Math.abs(a.rest - b.rest) < 1e-6 && Math.abs(a.rest - c.rest) < 1e-6,
    slowStart: Math.abs(a.first) < 2.4 / 60 / 4, coasts: r(a.rest - a.held), stopped: Math.abs(a.tv) < 0.01,
    play: run(mode, 60, 0.09, 0).held, half: r(run(mode, 60, 0.55, 0).held), lifted: r(run(mode, 60, 0.9, 0.25).h), up: r(run(mode, 60, 0, -1).h) };
}
// walking east (yaw 90°) for five seconds: orbit stays; action comes round behind (the eye to the west: a turn of -90°)
const walk = (mode, yaw, secs, o) => { const f = make(mode); if (o && o.hold) f.hold(true); if (o && o.steered) { f.steer(1 / 60, 1, 0); }
  for (let i = 0; i < secs * 60; i++) { f.heading(yaw, 1); f.follow(cam, 0, 0, 0, 1 / 60); } return r(f.turn); };
out.walk = { orbit: walk("orbit", Math.PI / 2, 5), action: walk("action", Math.PI / 2, 5), early: walk("action", Math.PI / 2, 0.5, { steered: true }) < 0.01,
  free: walk("action", Math.PI / 2, 5, { hold: true }), atEye: walk("action", 0, 5), fps30: (() => { const f = make("action"); for (let i = 0; i < 150; i++) { f.heading(Math.PI / 2, 1); f.follow(cam, 0, 0, 0, 1 / 30); } return Math.abs(f.turn - walk("action", Math.PI / 2, 5)) < 0.02; })() };
{ const f = make("action"); f.behind(Math.PI / 2); out.behind = r(L.U.wrap(f.turn)); }
// a drag, the wheel
{ const f = make("orbit"); f.look(0.5, 0.1); out.look = [r(f.turn), r(f.h)];
  for (let i = 0; i < 40; i++) f.zoom(1); f.follow(cam, 0, 0, 0, 1 / 60); const soon = f.k; for (let i = 0; i < 120; i++) f.follow(cam, 0, 0, 0, 1 / 60);
  out.zoom = [soon > 1 && soon < 1.2, r(f.k), r(Math.hypot(cam.x, cam.z)), r(cam.near)]; for (let i = 0; i < 40; i++) f.zoom(-1); for (let i = 0; i < 120; i++) f.follow(cam, 0, 0, 0, 1 / 60); out.zoomIn = [r(f.k), r(cam.near) < 6.9, r(cam.near) >= 0.5]; }
// a wall four metres behind, then gone; a bank of ground the same
{ const f = make("orbit", { blocked: (x, y, z) => wall && z > 4 }); let wall = true;
  for (let i = 0; i < 60; i++) f.follow(cam, 0, 0, 0, 1 / 60); out.wall = [cam.z < 4, cam.z > 3, r(cam.near) < 8.5 * 0.4, f.k < 0.4];
  wall = false; f.follow(cam, 0, 0, 0, 1 / 60); const one = cam.z; for (let i = 0; i < 300; i++) f.follow(cam, 0, 0, 0, 1 / 60); out.wallGone = [one < 4.5, r(cam.z)];
  const g = make("orbit"), bank = (x, z) => z > 5 ? 20 : 0; for (let i = 0; i < 60; i++) g.follow(cam, 0, 0, 0, 1 / 60, bank); out.bank = [cam.z < 5, cam.z > 3.5, cam.y > 0.6]; }
// fixed: as it was, whatever else is asked of it
{ const f = new L.Follow({ eyes }); f.steer(1, 1, 0); f.heading(1, 1); f.zoom(1); f.follow(cam, 0, 0, 0, 0.016, null); out.fixed = [r(f.turn), r(cam.y), f.k]; f.set("orbit"); out.set = f.mode; }
// nothing made: frames steered and walked once the script engine has settled, counted against the fixed way's
// (whose frame makes nothing: what's left is the counting's own)
{ const ground = () => 0, wall = () => false, way = [0, 0], per = mode => { const f = make(mode, { blocked: wall });
    const go = n => { for (let i = 0; i < n; i++) { f.steer(1 / 60, 0.5, 0.2); f.heading(1, 1); f.follow(cam, i * 0.1, 0, 0, 1 / 60, ground); f.move(1, 0, way); } };
    go(150000); gc(); const m0 = process.memoryUsage().heapUsed; go(20000); return (process.memoryUsage().heapUsed - m0) / 20000; };
  per("action"); const fixed = per("fixed"); out.made = [per("orbit") - fixed < 8, per("action") - fixed < 8]; }
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "--expose-gc", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        for mode in ("orbit", "action"):
            m = out[mode]
            self.assertTrue(m["same"], mode)                                           # (30, 60 and 20 frames a second: one turn)
            self.assertTrue(m["slowStart"] and m["stopped"], mode)
            self.assertLess(m["held"], -2.1); self.assertGreater(m["held"], -2.4)      # (a second pushed right: 2.4 less the run-up)
            self.assertLess(m["coasts"], 0); self.assertGreater(m["coasts"], -0.25)    # (and it runs on a little, then stops)
            self.assertEqual(m["play"], 0)                                             # (inside the stick's play: nothing)
            self.assertLess(m["half"], -0.5); self.assertGreater(m["half"], -1.2)      # (half a push: well under half the speed)
            self.assertEqual(m["lifted"], 0.5)                                         # (sideways with a little up: no lift)
            self.assertGreater(m["up"], 0.9)                                           # (straight up: lower, as ever)
        w = out["walk"]
        self.assertEqual(w["orbit"], 0)                                                # (orbit: never by itself)
        self.assertLess(w["action"], -1.2); self.assertGreater(w["action"], -1.58)    # (action: most of the way behind in 5 s)
        self.assertTrue(w["early"] and w["fps30"])                                     # (not inside the rest after a turn by hand)
        self.assertEqual((w["free"], w["atEye"]), (0, 0))                              # (free look held; walking at the eye)
        self.assertEqual(out["behind"], -1.571)
        self.assertEqual(out["look"], [-0.5, 0.4])
        self.assertEqual(out["zoom"][:2], [True, 1.5]); self.assertEqual(out["zoom"][2:], [15.99, 6.9])   # (farther: near stays)
        self.assertEqual(out["zoomIn"], [0.6, True, True])
        self.assertEqual(out["wall"], [True, True, True, True])
        self.assertTrue(out["wallGone"][0]); self.assertEqual(out["wallGone"][1], 11)  # (out again slowly, to where it was)
        self.assertEqual(out["bank"], [True, True, True])
        self.assertEqual(out["fixed"], [-2.4, 13.9, 1]); self.assertEqual(out["set"], "orbit")
        self.assertEqual(out["made"], [True, True])                                     # (bytes a frame over the fixed way's: none)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_camera_the_player_moves(self):
        """Low3D's Follow: at its first eye and no turn it stands where it's told; turned, the eye goes round and a push
        up on the screen goes away from it; a stick lowers and turns it; to() glides there; a rise behind lifts a lower
        eye; a jump is followed at once and a step a little behind."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
globalThis.screen = { width: 1920, height: 1080 }; globalThis.innerWidth = 960; globalThis.innerHeight = 540;
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, out = {}, r = v => Math.round(v * 1000) / 1000 + 0;
const eyes = [[13.9, 9.3, 0.9, 1.2, 0.66, 0.5], [7, 11, 1.4, 7, 0.72, 8.5], [5.2, 9.5, 1.5, 6, 0.74, 7]];
const f = new L.Follow({ eyes }), cam = L.camera(), at = c => [c.x, c.y, c.z, c.tx, c.ty, c.tz, c.fov, c.near].map(r);
out.high = at(f.follow(cam, 0, 0, 0, 0.016));
f.turn = Math.PI / 2; out.turned = at(f.follow(cam, 0, 0, 0, 0.016)); out.away = f.move(0, -1).map(r);
f.turn = 0; f.steer(1, 0, -1); out.lowered = r(f.h);
f.steer(1, 1, 0); out.turn = r(f.turn);
f.turn = 0; f.h = 0; f.to(1); for (let i = 0; i < 12; i++) f.follow(cam, 0, 0, 0, 1 / 60); out.gliding = r(f.h);
for (let i = 0; i < 60; i++) f.follow(cam, 0, 0, 0, 1 / 60); out.glided = r(f.h);
out.low = at(f.follow(cam, 0, 0, 0, 0.016));
out.overRise = r(f.follow(cam, 0, 0, 0, 0.016, (x, z) => z > 5 ? 9 : 0).y);
f.follow(cam, 50, 0, 0, 0.016); out.jumped = r(cam.tx);
f.follow(cam, 51, 0, 0, 0.016); out.stepped = r(cam.tx);
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["high"], [0, 13.9, 9.3, 0, 0.9, -1.2, 0.66, 0.5])       # (WYRD's eye as it always was)
        self.assertEqual(out["turned"], [9.3, 13.9, 0, -1.2, 0.9, 0, 0.66, 0.5])     # (round to the east, looking west)
        self.assertEqual(out["away"], [-1, 0])                                         # (up on the screen: west, away from it)
        self.assertEqual(out["lowered"], 0.9)
        self.assertEqual(out["turn"], -2.4)                                            # (right: the view turns right)
        self.assertEqual(out["gliding"], 0.5)
        self.assertEqual(out["glided"], 1)
        self.assertEqual(out["low"], [0, 5.2, 9.5, 0, 1.5, -6, 0.74, 7])
        self.assertEqual(out["overRise"], 10.4)
        self.assertEqual(out["jumped"], 50)
        self.assertEqual(out["stepped"], 50.12)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_body_moved_between_poses(self):
        """Rig.bind builds a body once and its Skin moves it: posed, it stands where a body built in that pose stands,
        part by part (what's held and what's built with no joint too); Rig.mix finds the pose between two and keeps
        its own object."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
globalThis.screen = { width: 1920, height: 1080 }; globalThis.innerWidth = 960; globalThis.innerHeight = 540;
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, out = {}, rig = new L.Rig(L.Rig.HUMAN);
const idle = { chest: [0.04, 0, 0], armR: [0.05, 0.14, 0], foreR: [0.25, 0, 0] };
const walk = { y: -0.03, chest: [0.12, 0, 0.12], legR: [0.55, 0, 0], shinR: [-0.15, 0, 0], legL: [-0.45, 0, 0], armR: [-0.5, 0.1, 0], foreR: [0.3, 0, 0], lean: 0.1 };
const body = (m, P) => { rig.pose(P, 1.1, 1.2);
  for (let j = 0; j < rig.n; j++) { rig.at(m, j); m.box(0, -0.1, 0, 0.1, 0.2, 0.1, 0x808080); }
  rig.attach(m, 5, 0, -0.09, -0.1, 0, Math.PI / 2, 0, 0.8); m.box(0, 0, 0, 0.05, 0.6, 0.05, 0xc0c0c0);   // (a blade in the right hand)
  m.at(0, 0, 0); m.box(0, 0, 0, 0.5, 0.02, 0.5, 0x202020); };                                        // (a shadow, with no joint)
const baked = new L.Mesh(2048); body(baked, walk);
const skin = rig.bind(m => body(m, idle));
rig.pose(walk, 1.1, 1.2); skin.pose();
let far = 0, turned = 0;
for (let v = 0; v < baked.n; v++) { for (let i = 0; i < 3; i++) far = Math.max(far, Math.abs(baked.f[v * 5 + i] - skin.mesh.f[v * 5 + i]));
  for (let i = 12; i < 15; i++) turned = Math.max(turned, Math.abs(baked.i8[v * 20 + i] - skin.mesh.i8[v * 20 + i])); }
out.n = [baked.n, skin.n]; out.far = far; out.turned = turned;
const mixed = L.Rig.mix(idle, walk, 0.5);
out.half = { chest: mixed.chest.map(v => Math.round(v * 1000) / 1000), legR: mixed.legR.map(v => Math.round(v * 1000) / 1000), y: Math.round(mixed.y * 1000) / 1000 };
const again = L.Rig.mix(walk, idle, 1, mixed);
out.same = again === mixed; out.cleared = mixed.legR.join(",") + " " + mixed.y + " " + mixed.lean;
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["n"][0], out["n"][1])
        self.assertLess(out["far"], 1e-4)                                  # (every vertex where the baked pose has it)
        self.assertLessEqual(out["turned"], 1)                             # (and facing the same way, to a step of 127)
        self.assertEqual(out["half"], {"chest": [0.08, 0, 0.06], "legR": [0.275, 0, 0], "y": -0.015})
        self.assertTrue(out["same"])
        self.assertEqual(out["cleared"], "0,0,0 0 0")                       # (idle names neither the leg nor y: back to none)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_each_box_gets_its_drawing(self):
        """The GPU's name and the test pick 3D or 2D and the rung to start on; the governor holds the frame rate;
        meshes face out; paths know where their points are."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
globalThis.screen = { width: 1920, height: 1080 }; globalThis.innerWidth = 960; globalThis.innerHeight = 540;
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, out = {};
out.family = ["VC4 V3D 2.1", "V3D 4.2.14.0", "V3D 7.1.7.0", "ANGLE (Broadcom, V3D 4.2.14.0, OpenGL ES 3.1 Mesa 24.2.8)",
  "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)", "llvmpipe (LLVM 15.0.6, 128 bits)",
  "Mali-G52", "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)", ""].map(L.family);
const box = (family, extra) => Object.assign({ webgl1: family !== "none", software: family === "software", family, renderer: family }, extra || {});
const pick = (p, b) => { const r = L.plan(p, b); return r.mode + " " + r.rung + "/" + r.top; };
out.plans = {
  pi3: pick(box("pi3"), { draws: 32, fill: 2, cpu: 95 }), pi3slow: pick(box("pi3"), { draws: 4, fill: 0.25, cpu: 120 }),
  pi4: pick(box("pi4"), { draws: 128, fill: 4, cpu: 40 }), pi5: pick(box("pi5"), { draws: 256, fill: 8, cpu: 20 }),
  software: pick(box("software"), { cpu: 30 }), none: pick(box("none"), { cpu: 150 }), desktop: pick(box("desktop"), { draws: 1024, fill: 64, cpu: 5 }),
  pi3strong: pick(box("pi3"), { draws: 1024, fill: 64, cpu: 60 })
};
out.ladder = L.LADDER.gl;
out.sizes = [[1080, 360], [1080, 540], [1080, 270], [1080, 216], [720, 360], [720, 540], [2160, 360], [1080, 1080]].map(a => L.wholeSize(a[0], a[1]));
// the governor: frames at 60 fps hold; late ones step it down; a busy game drops to a 30 fps rung at once
const lad = L.LADDER.gl, g = new L.Governor(lad, 5, 8), steps = [];
let t = 10000;
for (let i = 0; i < 400; i++) { t += 1000 / 60; g.tick(t); g.work(2); }
steps.push(g.rung);
for (let i = 0; i < 300; i++) { t += i % 2 ? 1000 / 60 : 50; g.tick(t); g.work(4); }
steps.push(g.rung);
const b = new L.Governor(lad, 5, 8);
for (let i = 0; i < 400; i++) { t += i % 3 ? 1000 / 60 : 45; b.tick(t); b.work(20); }
steps.push(b.rung, lad[b.rung].fps);
out.gov = steps;
// a box's every face points out
const m = new L.Mesh(); m.at(3, 0, -2, 0.7); m.box(0, 0, 0, 2, 3, 4, 0xffffff);
let outward = 0; for (let i = 0; i < m.n; i += 3) {
  let cx = 0, cy = 0, cz = 0; for (let k = 0; k < 3; k++) { cx += m.f[(i + k) * 5] / 3; cy += m.f[(i + k) * 5 + 1] / 3; cz += m.f[(i + k) * 5 + 2] / 3; }
  const o = (i + 0) * 20; if (m.i8[o + 12] * (cx - 3) + m.i8[o + 13] * (cy - 1.5) + m.i8[o + 14] * (cz + 2) > 0) outward++;
}
out.mesh = [m.n / 3, outward];
const P = new L.Path([[0, 0], [100, 0], [100, 100], [0, 100]]), at = new Float32Array(5);
P.at(P.s[P.knots[2]], at); out.path = [P.knots.length, Math.round(at[0]), Math.round(at[1]), Math.round(P.len)];
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["family"], ["pi3", "pi4", "pi5", "pi4", "software", "software", "mobile", "desktop", "none"])
        p = out["plans"]
        self.assertEqual(p["pi3"], "gl 4/5")                             # a Pi 3's GPU: the light look at 360 lines and 60 a second
        self.assertEqual(p["pi3slow"], "gl 2/5")                         # slow in the test: the smallest picture, still at 60
        self.assertEqual(p["pi3strong"], "gl 4/5")                       # a strong test never lifts a Pi off its own kind's rungs
        self.assertEqual(p["pi4"], "gl 6/7")                             # the full look from a Pi 4
        self.assertEqual(p["pi5"], "gl 7/8")
        self.assertTrue(p["software"].startswith("flat "))               # no real GPU: the 2D renderer
        self.assertTrue(p["none"].startswith("flat "))
        self.assertTrue(p["desktop"].startswith("gl 8"))
        lad = out["ladder"]                                              # pixels are given up before frames
        self.assertEqual([r["fps"] for r in lad[2:]], [60] * (len(lad) - 2))
        self.assertEqual([lad[0]["fps"], lad[1]["fps"]], [30, 30])
        self.assertEqual(lad[1]["h"], lad[4]["h"])                       # when frames go, they go at the good picture first
        self.assertEqual([r["h"] for r in lad[2:]], sorted(r["h"] for r in lad[2:]))
        self.assertEqual([lad[4]["look"], lad[4]["mirror"] > 0, lad[6]["look"]], [0, True, 1])
        self.assertEqual(out["sizes"], [[360, 3], [540, 2], [270, 4], [216, 5], [360, 2], [720, 1], [360, 6], [1080, 1]])
        steady, late, busy, busy_fps = out["gov"]
        self.assertEqual(steady, 6)                                      # room to spare: up a rung (no further: it stays a while)
        self.assertEqual(busy, 1)                                        # (the good picture at 30, not the smallest)
        self.assertLess(late, steady)                                    # late frames: down
        self.assertEqual(busy_fps, 30)                                   # the game's own work fills a frame: 30 a second
        self.assertEqual(out["mesh"], [12, 12])
        self.assertEqual(out["path"], [4, 100, 100, 420])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_bench_is_there(self):
        """tools/games-bench.mjs, the measure of the page games: it parses, says what it is, and what it can't be."""
        bench = os.path.join(os.path.dirname(os.path.dirname(BOX)), "tools", "games-bench.mjs")
        r = subprocess.run(["node", "--check", bench], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        said = subprocess.run(["node", bench, "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(said.returncode, 0, said.stderr)
        for words in ("--box", "pi3", "What it cannot do: be a Pi", "Every number it prints is from this computer"):
            self.assertIn(words, said.stdout)
        with open(bench, encoding="utf-8") as f:
            src = f.read()
        for scene in ("tidewing", "ironmaw"):                            # the two the owner named, their heavy scenes
            self.assertIn(scene + ": [", src)
        self.assertIn("benchMain", src)                                  # (GLSL keeps names with two underscores for
        self.assertNotIn("__main", src)                                  # itself: a counter named that way broke every shader)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_kit_sheet_is_there(self):
        """tools/kit-sheet.mjs pictures the kit from the maker's own list: it parses and says what it takes."""
        sheet = os.path.join(os.path.dirname(os.path.dirname(BOX)), "tools", "kit-sheet.mjs")
        r = subprocess.run(["node", "--check", sheet], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        said = subprocess.run(["node", sheet, "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(said.returncode, 0, said.stderr)
        for words in ("--root", "--things", "--details", "--light", "--row", "never how fast a box draws it"):
            self.assertIn(words, said.stdout)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_look_bench_is_there(self):
        """tools/look-bench.mjs pictures a game the same way each time: it parses, says what it can't be, and each of
        its place lists is for a game there is, every place with somewhere to stand."""
        tools = os.path.join(os.path.dirname(os.path.dirname(BOX)), "tools")
        bench = os.path.join(tools, "look-bench.mjs")
        r = subprocess.run(["node", "--check", bench], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        said = subprocess.run(["node", bench, "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(said.returncode, 0, said.stderr)
        for words in ("--root", "--rungs", "--gpu on,off", "swiftshader", "--sets", "--clip", "What it cannot do: be a Pi"):
            self.assertIn(words, said.stdout)
        with open(os.path.join(tools, "look-places.json"), encoding="utf-8") as f:
            places = json.load(f)
        games = [k for k in places if k != "about"]
        self.assertTrue(games)
        for game in games:
            spec = places[game]
            self.assertTrue(os.path.isfile(os.path.join(BOX, "games", game, "index.html")), game)
            self.assertTrue(spec["ready"] and spec["places"], game)
            ids = [p["id"] for p in spec["places"]]
            self.assertEqual(len(ids), len(set(ids)), game)
            for p in spec["places"]:
                self.assertTrue(p["name"] and p["run"] and p["set"], p["id"])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_second_way_to_draw(self):
        """Made for a Pi 3's GPU: a still world's light is worked out once and kept in its colours (shadows too, and
        what glows left alone), a chunk's glowing things go in with the rest, high ground behind its cliffs is big
        triangles and nothing is built under the water, the sky's dome stops at the horizon, see-through things are
        written without a call's worth of garbage, and what's written on the screen is a list of quads."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
globalThis.screen = { width: 1920, height: 1080 }; globalThis.innerWidth = 960; globalThis.innerHeight = 540;
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, out = {};
const light = { sun: [0, 1, 0], sunCol: 0x808080, amb: 0x404040, ground: 0x202020 };
const col = (m, i) => [m.u8[i * 20 + 16], m.u8[i * 20 + 17], m.u8[i * 20 + 18], m.i8[i * 20 + 15]];
const m = new L.Mesh(); m.at(0, 0, 0);
m.quad(-1, 0, 1, 1, 0, 1, 1, 0, -1, -1, 0, -1, 0xc86432, 0, -1, 0);      // facing up: the sky's light and the sun's
m.quad(9, 0, 1, 11, 0, 1, 11, 0, -1, 9, 0, -1, 0xc86432, 10, -1, 0);     // the same, where the shade says no sun reaches
m.glow = 127; m.quad(-1, 5, 1, 1, 5, 1, 1, 5, -1, -1, 5, -1, 0x39ff88, 0, 4, 0); m.glow = 0;   // its own light
m.alpha = 254; m.quad(-1, 7, 1, 1, 7, 1, 1, 7, -1, -1, 7, -1, 0xff2e88, 0, 6, 0); m.alpha = 255;  // (the old way to say so)
m.light(light, { shade: (x) => x > 5 ? 0 : 1 });
out.lit = [col(m, 0), col(m, 6), col(m, 12), col(m, 18)];
m.quad(-1, 9, 1, 1, 9, 1, 1, 9, -1, -1, 9, -1, 0x646464, 0, 8, 0); m.light(light);   // built after: lit by the next call, the rest not lit twice
out.again = [col(m, 0), col(m, 24)];
m.s[0] = 1.5; m.s[1] = 2.5; m.s[2] = -3.5; m.v(1, 2, 3, 200, 127);
out.v = [m.f[(m.n - 1) * 5], m.f[(m.n - 1) * 5 + 1], m.f[(m.n - 1) * 5 + 2], m.u8[(m.n - 1) * 20 + 19], m.i8[(m.n - 1) * 20 + 15]];
// a chunk: baked, its glowing things in with the rest
const ch = new L.Chunks(64, 32);
ch.mesh(0, 0).at(0, 0, 0).quad(-1, 0, 1, 1, 0, 1, 1, 0, -1, -1, 0, -1, 0xc86432, 0, -1, 0);
ch.mesh(0, 0, "glow").at(0, 0, 0).quad(-1, 3, 1, 1, 3, 1, 1, 3, -1, -1, 3, -1, 0x39ff88, 0, 2, 0);
const sent = []; ch.upload({ upload: mm => { sent.push(mm); return { n: mm.n, x: 0, y: 0, z: 0, r: 1 }; }, free() {} }, { light });
out.chunk = [ch.baked, sent.length, sent[0].n, col(sent[0], 0), col(sent[0], 6)];
// a tableland: 30 high behind a cliff, the sea round it
const land = new L.Land(256, 32, -6).fill((x, z) => Math.max(Math.abs(x), Math.abs(z)) < 80 ? 30 + Math.sin(x * 0.3) : -6);
const count = o => { const c = new L.Chunks(256, 128); land.mesh(c, () => 0x808080, 0, "base", o); let n = 0, low = 0; c.each(q => { n += q.base.n / 3; for (let i = 0; i < q.base.n; i += 3) if (Math.max(q.base.f[i * 5 + 1], q.base.f[i * 5 + 6], q.base.f[i * 5 + 11]) < -0.3) low++; }); return [n, low]; };
const inner = land.inner({ above: 8, drop: 8 });
out.land = [count(), count({ coarse: inner, under: 0.3 }), inner.reduce((a, b) => a + b, 0), inner[16 * 32 + 16], inner[16 * 32 + 7]];
const dome = L.Kit.dome(); let lowest = 1e9, us = new Set(); for (let i = 0; i < dome.n; i++) { lowest = Math.min(lowest, dome.f[i * 5 + 1]); us.add(dome.u8[i * 20 + 16]); }
out.dome = [dome.n, lowest >= -1e-6, us.has(0) && us.has(255), L.Kit.skyV(0), L.Kit.skyV(Math.PI / 2)];
// a wake: never past the mesh's room, fading to nothing
const tr = new L.Trail(22, 0.01); for (let i = 0; i < 30; i++) tr.step(0.02, i * 2, 0, 1);
const wk = new L.Mesh(60); tr.wake(wk, 0.06, 0xffffff, 0.9, 0.2, 255, 127);
const big = new L.Mesh(2000); tr.wake(big, 0.06, 0xffffff, 0.9, 0.2, 255, 127);
out.wake = [wk.n <= 60, wk.cap, big.n > 200, big.u8[19] > big.u8[(big.n - 18) * 20 + 19], big.i8[15]];
// what's written on the screen
const ui = new L.UI(); ui.begin(640, 360);
ui.rect(0, 0, 10, 10, 0xff2e88, 0.5); ui.hold();
const x1 = ui.text("LAP 1/3", 10, 20, 2, 0xefe6d2);
out.ui = [ui.n, x1 - 10 - 2, ui.width("LAP 1/3", 2), ui.q[16 + 12], ui.q[12]];
ui.rewind(); out.ui.push(ui.n); ui.text("go", 0, 0, 1, 0x39ff88, 1, 0, 0x0b0d10); out.ui.push(ui.n);
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        sun, shade, glow, old = out["lit"]
        self.assertEqual(sun, [150, 75, 37, 0])                          # 200 100 50 × (the sky's 0.25 + the sun's 0.5)
        self.assertEqual(shade, [50, 25, 12, 0])                         # in shadow: the sky's light alone
        self.assertEqual(glow, [0x39, 0xff, 0x88, 127])                  # what glows is left as it is
        self.assertEqual(old, [0xff, 0x2e, 0x88, 127])
        self.assertEqual(out["again"], [[150, 75, 37, 0], [75, 75, 75, 0]])
        self.assertEqual(out["v"], [1.5, 2.5, -3.5, 200, 127])
        baked, meshes, verts, base, lamp = out["chunk"]
        self.assertEqual((baked, meshes, verts), (True, 1, 12))          # one mesh a chunk: its lamp went in with its ground
        self.assertEqual((base, lamp), ([150, 75, 37, 0], [0x39, 0xff, 0x88, 127]))
        (fine, _), (coarse, under), marked, middle, rim = out["land"]
        self.assertLess(coarse, fine * 0.7)                              # the tableland's top: big triangles (its rim stays fine)
        self.assertEqual(under, 0)                                       # nothing built under the water
        self.assertGreater(marked, 100)
        self.assertEqual((middle, rim), (1, 0))                          # (its middle, not the ground by its cliff)
        self.assertEqual(out["dome"], [24 * 8 * 6, True, True, 1, 0])    # down to the horizon and no further
        fits, cap, drew, fades, add = out["wake"]
        self.assertEqual((fits, cap, drew, fades, add), (True, 60, True, True, 127))
        quads, width, measured, colour, held_colour, rewound, shaded = out["ui"]
        self.assertEqual((quads, rewound, shaded), (1 + 6, 1, 1 + 4))    # a quad a letter (none for the space); the held part stays; a shade doubles them
        self.assertEqual(width, measured)
        self.assertEqual((colour, held_colour), (0xefe6d2, 0xff2e88))

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_land_with_height(self):
        """Land (E4): a height anywhere (smooth between the grid's corners, the edge's past it), which way it rises,
        triangles only where it's near or above the water, every one facing up, and banks where it leaves the water,
        each facing the water."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
globalThis.screen = { width: 1920, height: 1080 }; globalThis.innerWidth = 960; globalThis.innerHeight = 540;
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, out = {};
const land = new L.Land(64, 8, -4).fill((x, z) => 10 - Math.hypot(x, z) * 0.5);   // a cone: 10 high, at the water 20 out
out.at = [land.at(0, 0), land.at(20, 0), land.at(4, 4), land.at(100, 100)].map(v => Math.round(v * 100) / 100);
const s = land.slope(10, 0, [0, 0]); out.slope = s.map(v => Math.round(v * 100) / 100);
let tris = 0, up = 0, top = -1e9; land.each(() => 0x808080, 0, 2, (ax, ay, az, bx, by, bz, cx, cy, cz, c, nx, ny) => { tris++; if (ny > 0) up++; top = Math.max(top, ay, by, cy); });
out.tris = [tris, up, top];
const ch = new L.Chunks(64, 32); land.mesh(ch, () => 0x808080, 0); let verts = 0; ch.each(c => verts += c.base.n); out.mesh = verts === tris * 3;
const banks = land.banks(() => 0x808080, 0);
out.banks = [banks.length > 0, banks.every(b => b.nx * b.x + b.nz * b.z > 0), banks.every(b => Math.abs(land.at((b.ax + b.bx) / 2, (b.az + b.bz) / 2)) < 0.6)];
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["at"][:2], [10, 0])
        self.assertAlmostEqual(out["at"][2], 10 - (32 ** 0.5) * 0.5, delta=0.6)   # (between corners: near the cone)
        self.assertLess(out["at"][3], -10)                               # past the edge: the corner's own height
        self.assertEqual(out["slope"], [-0.5, 0])                        # it falls away from the middle
        tris, up, top = out["tris"]
        self.assertEqual(tris, up)
        self.assertTrue(0 < tris < 2 * 8 * 8)                            # the cells near the shore and above it, not the deep water's
        self.assertEqual(top, 10)
        self.assertTrue(out["mesh"])
        self.assertEqual(out["banks"], [True, True, True])               # on the waterline, facing out to the water

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_trees_grown_by_rules(self):
        """Kit.tree (1.1.96): the same seed grows the same tree and another seed another; every kind builds at every
        detail, with more triangles the higher; it stands on its foot, inside the crown it says it has; fruit goes
        into the glow mesh; nothing it builds is NaN; the mesh's own jitter is left as it was."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
globalThis.screen = { width: 1920, height: 1080 }; globalThis.innerWidth = 960; globalThis.innerHeight = 540;
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, K = L.Kit, out = { kinds: {} };
const grow = (o, glow) => { const m = new L.Mesh(64); m.jit = 0.03; const c = K.tree(m, glow || null, 0, 0, 0, 0, 1, o); return { m, c }; };
const bytes = m => Buffer.from(m.buf, 0, m.n * 20).toString("hex");
const a = grow(Object.assign({}, K.TREES.oak, { seed: 5, detail: 2 })), b = grow(Object.assign({}, K.TREES.oak, { seed: 5, detail: 2 })), c = grow(Object.assign({}, K.TREES.oak, { seed: 6, detail: 2 }));
out.same = bytes(a.m) === bytes(b.m); out.other = bytes(a.m) !== bytes(c.m); out.jit = a.m.jit;
for (const k of Object.keys(K.TREES)) {
  const row = [];
  for (const d of [0, 1, 2]) {
    const t = grow(Object.assign({}, K.TREES[k], { seed: 3, detail: d })), o = K.TREES[k], f = t.m.f;
    let bad = 0, low = 1e9, high = -1e9, far = 0;
    for (let i = 0; i < t.m.n; i++) { const x = f[i * 5], y = f[i * 5 + 1], z = f[i * 5 + 2]; if (!(isFinite(x) && isFinite(y) && isFinite(z))) bad++; if (y < low) low = y; if (y > high) high = y; far = Math.max(far, Math.hypot(x - (o.lean || 0) * 0, z)); }
    row.push({ tris: t.m.n / 3, bad, low, high, far, crown: t.c, lean: o.lean || 0 });
  }
  out.kinds[k] = row;
}
const g = new L.Mesh(16), fr = grow(Object.assign({}, K.TREES.oak, { seed: 2, detail: 1, fruit: { col: 0xff4a5a, n: 6 } }), g), gem = new L.Mesh(16);
grow(Object.assign({}, K.TREES.oak, { seed: 2, detail: 1, fruit: { col: [1, 2], n: 5, gem: true } }), gem);
out.fruit = [g.n / 3, gem.n / 3, fr.m.n === grow(Object.assign({}, K.TREES.oak, { seed: 2, detail: 1 })).m.n];
// placed, turned and sized: the same tree, moved
const far = new L.Mesh(64); K.tree(far, null, 10, 2, -4, 1.3, 2, Object.assign({}, K.TREES.fir, { seed: 3, detail: 1 }));
const near = grow(Object.assign({}, K.TREES.fir, { seed: 3, detail: 1 })).m; let hi = -1e9, hi0 = -1e9;
for (let i = 0; i < far.n; i++) { hi = Math.max(hi, far.f[i * 5 + 1]); hi0 = Math.max(hi0, near.f[i * 5 + 1]); }
out.placed = [far.n === near.n, Math.abs((hi - 2) - hi0 * 2) < 1e-3];
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["same"]); self.assertTrue(out["other"])
        self.assertAlmostEqual(out["jit"], 0.03)
        self.assertEqual(sorted(out["kinds"]), ["birch", "crooked", "dead", "fir", "oak"])
        for kind, rows in out["kinds"].items():
            self.assertLess(rows[0]["tris"], rows[1]["tris"], kind); self.assertLess(rows[1]["tris"], rows[2]["tris"], kind)
            self.assertLess(rows[0]["tris"], 70, kind)                   # the plainest: what a Pi 3 can stand in numbers
            self.assertLess(rows[2]["tris"], 500, kind)
            for row in rows:
                radius, start, _narrow, _at, tip = row["crown"]
                self.assertEqual(row["bad"], 0, kind)
                self.assertLess(row["low"], 0.01, kind)                  # its foot is in the ground, not over it
                self.assertLess(row["high"], tip + 0.6, kind); self.assertGreater(row["high"], start, kind)
                self.assertLess(row["far"], radius + row["lean"] + 0.9, kind)
        self.assertEqual(out["fruit"], [6 * 12, 5 * 8, True])            # six boxes, five gems; the leaves the same with or without
        self.assertEqual(out["placed"], [True, True])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_ground_shaded_smooth(self):
        """Land.part(…, {soft}) (1.1.88): the very corners part() makes, no more of them, each with its own normal and
        colour, the same in two chunks that share it; a cliff keeps its flat faces; what's laid with the ground's
        normal (Kit.lay's norm) is lit as the ground under it is."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
globalThis.screen = { width: 1920, height: 1080 }; globalThis.innerWidth = 960; globalThis.innerHeight = 540;
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, out = {};
// rolling ground, and a cliff along x = 10 (6 high within a cell)
const land = new L.Land(40, 16, 0).fill((x, z) => 1.5 * Math.sin(x * 0.3) * Math.cos(z * 0.25) + (x > 10 ? 6 : 0));
const col = (h, steep) => steep > 0.5 ? 0x6a6058 : 0x4a7a36;
const verts = m => { const o = []; for (let i = 0; i < m.n; i++) { const q = i * 20; o.push({ p: [m.f[i * 5], m.f[i * 5 + 1], m.f[i * 5 + 2]], n: [m.i8[q + 12], m.i8[q + 13], m.i8[q + 14]], c: [m.u8[q + 16], m.u8[q + 17], m.u8[q + 18]] }); } return o; };
const flat = verts(land.part(new L.Mesh(), 0, 0, 16, 16, col)), soft = verts(land.part(new L.Mesh(), 0, 0, 16, 16, col, { soft: true }));
const key = v => v.p.map(x => x.toFixed(3)).join(",");
out.same = [flat.length, soft.length, JSON.stringify(flat.map(key).sort()) === JSON.stringify(soft.map(key).sort())];
let up = 0, steepFlat = 0, steep = 0, smoothOnes = 0;
for (let t = 0; t < soft.length; t += 3) {
  const [a, b, c] = [soft[t], soft[t + 1], soft[t + 2]], u = [b.p[0] - a.p[0], b.p[1] - a.p[1], b.p[2] - a.p[2]], v = [c.p[0] - a.p[0], c.p[1] - a.p[1], c.p[2] - a.p[2]];
  const nx = u[1] * v[2] - u[2] * v[1], ny = u[2] * v[0] - u[0] * v[2], nz = u[0] * v[1] - u[1] * v[0], l = Math.hypot(nx, ny, nz);
  if (ny > 0) up++;
  const same = JSON.stringify(a.n) === JSON.stringify(b.n) && JSON.stringify(b.n) === JSON.stringify(c.n);
  if (1 - ny / l > 0.5) { steep++; if (same) steepFlat++; } else if (!same) smoothOnes++;
}
out.faces = [up * 3 === soft.length, steep > 0, steepFlat === steep, smoothOnes > 0];
// two chunks side by side: the corners on their shared edge alike in both
const left = verts(land.part(new L.Mesh(), 0, 0, 8, 8, col, { soft: true })), right = verts(land.part(new L.Mesh(), 8, 0, 16, 8, col, { soft: true }));
const at = (vs, x) => { const o = new Map(); for (const v of vs) if (Math.abs(v.p[0] - x) < 1e-6) o.set(v.p[2].toFixed(3), JSON.stringify([v.n, v.c])); return o; };
const A = at(left, -20 + 8 * 2.5), B = at(right, -20 + 8 * 2.5);
let agree = A.size > 0; for (const [k, v] of A) if (B.get(k) !== v) agree = false;
out.seam = agree;
// a corner's normal is Land.norm's there
const nv = [0, 0, 0], v0 = soft.find(v => Math.abs(v.p[0] - 0) < 1e-6 && Math.abs(v.p[2] - 0) < 1e-6);
land.norm(0, 0, nv); out.norm = [Math.round(nv[0] * 127) === v0.n[0], Math.round(nv[1] * 127) === v0.n[1], Math.round(nv[2] * 127) === v0.n[2]];
// laid with the ground's normal: as many triangles, each corner the ground's normal and its own colour
const P = [-3, -3, 3, -3, 3, 3, -3, 3], on = (x, z) => land.on(x, z), shade = (x, z) => x < 0 ? 0x303030 : 0x909090;
const plain = L.Kit.lay(new L.Mesh(), P, on, shade, 0.03), lit = verts(L.Kit.lay(new L.Mesh(), P, on, shade, 0.03, 0, (x, z, o) => land.norm(x, z, o)));
let ok = true, cols = new Set();
for (const v of lit) { land.norm(v.p[0], v.p[2], nv); if (Math.abs(Math.round(nv[1] * 127) - v.n[1]) > 1) ok = false; cols.add(v.c[0]); }
out.laid = [plain.n === lit.length, ok, cols.size === 2];
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        flat_n, soft_n, same = out["same"]
        self.assertEqual((flat_n, soft_n, same), (16 * 16 * 6, 16 * 16 * 6, True))   # the same corners, as many
        self.assertEqual(out["faces"], [True, True, True, True])         # all facing up; the cliff's flat, the rest smooth
        self.assertTrue(out["seam"])                                     # two chunks give a shared corner the same light
        self.assertEqual(out["norm"], [True, True, True])
        self.assertEqual(out["laid"], [True, True, True])


class TheRaycaster(unittest.TestCase):
    """Low3D's Ray: worlds on a grid drawn a pixel at a time (Ironmaw's), the same on every box."""
    GAMES = os.path.join(BOX, "games")

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_it_draws_and_things_move_in_it(self):
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, out = {};
const ramps = []; for (let r = 0; r < 16; r++) ramps.push([40 + r * 12, 60 + r * 8, 80 + r * 5]);
const pal = new L.Palette(ramps, [14, 15]);
out.glowFull = pal.cmap[(0 << 8) | (14 * 16 + 10)] === pal.cmap[(31 << 8) | (14 * 16 + 10)];   // glowing colours ignore the dark
out.darkIsDark = pal.cmap[(0 << 8) | (3 * 16 + 10)] !== pal.cmap[(31 << 8) | (3 * 16 + 10)];
out.nearNotGlow = !pal.full[pal.near(255, 140, 40)];
// a room 8 x 6: walls round, a step in the middle, the sky over the far half, a door shut in the wall
const m = new L.RayMap(8, 6);
for (let y = 0; y < 6; y++) for (let x = 0; x < 8; x++) { const i = y * 8 + x; if (x === 0 || y === 0 || x === 7 || y === 5) { m.solid[i] = 1; m.wtex[i] = 1; } else { m.ftex[i] = 2; m.ctex[i] = x > 4 ? 255 : 3; m.ceil[i] = 1.2; m.light[i] = 24; } }
m.floor[3 * 8 + 3] = 0.3; m.stex[3 * 8 + 3] = 4;
const T = (k) => L.Tex.make(() => k * 16 + 8);
const ray = new L.Ray(pal); ray.tex = [T(0), T(1), T(2), T(3), T(4)]; ray.sky = { w: 4, h: 4, px: new Uint8Array(16).fill(15 * 16 + 8) };
const W = 64, H = 36, buf = new Uint32Array(W * H); ray.size(W, H, buf);
ray.render(m, { x: 1.5, y: 2.5, z: 0.5, a: 0, pitch: 0, fov: 1.6 });
const at = (x, y) => buf[y * W + x], idxOf = (c) => { for (let L2 = 0; L2 < 32; L2++) for (let i = 0; i < 256; i++) if (pal.cmap[(L2 << 8) | i] === c) return i >> 4; return -1; };
out.wall = idxOf(at(32, 18));                     // straight ahead, at eye height: the far wall
out.floor = idxOf(at(32, 35));                    // down at the bottom: the floor
out.ceiling = idxOf(at(8, 0));                    // top left, over the near half: the ceiling
const depthAhead = ray.depth[18 * W + 32];
ray.render(m, { x: 4.6, y: 2.5, z: 0.5, a: 0, pitch: 0, fov: 1.6 }); out.sky = idxOf(at(32, 1));   // looking over the open half: the sky above it
ray.render(m, { x: 1.5, y: 2.5, z: 0.5, a: 0, pitch: 0, fov: 1.6 });
out.depth = depthAhead > 4 && depthAhead < 7;
let painted = 0; for (let i = 0; i < W * H; i++) if (buf[i]) painted++; out.painted = painted === W * H;
// sight lines, walking, the way round
out.see = [m.see(1.5, 2.5, 0.5, 6.5, 2.5, 0.5), m.see(1.5, 2.5, 0.5, 9, 2.5, 0.5), m.see(1.5, 3.5, 0.1, 5.5, 3.5, 0.1)];   // clear; through a wall; low, across the step
const b = { x: 1.5, y: 1.5, z: 0 }; m.move(b, -1, 0, 0.2, 0.35, 0.6); out.blocked = b.x > 1.15;
const s = { x: 2.6, y: 3.5, z: 0 }; m.move(s, 0.6, 0, 0.2, 0.35, 0.6); out.stepUp = s.x > 3;
m.floor[3 * 8 + 3] = 0.6; const t = { x: 2.6, y: 3.5, z: 0 }; m.move(t, 0.6, 0, 0.2, 0.35, 0.6); out.tooHigh = t.x < 2.9;
const fl = m.flow(6.5, 4.5, 0.35, 0.6); out.flow = [fl[1 * 8 + 1], fl[3 * 8 + 3]];
m.ceil[2 * 8 + 4] = 0; const shut = m.flow(6.5, 2.5, 0.35, 0.6), through = new Uint8Array(48); through[2 * 8 + 4] = 1;
out.door = [shut[2 * 8 + 4], m.flow(6.5, 2.5, 0.35, 0.6, through)[2 * 8 + 4]];
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["glowFull"] and out["darkIsDark"] and out["nearNotGlow"])
        self.assertEqual((out["wall"], out["floor"], out["ceiling"], out["sky"]), (1, 2, 3, 15))
        self.assertTrue(out["depth"] and out["painted"])
        self.assertEqual(out["see"], [True, False, False])
        self.assertTrue(out["blocked"] and out["stepUp"] and out["tooHigh"])
        self.assertEqual(out["flow"][0], 8)                              # 5 across and 3 up, a step at a time
        self.assertEqual(out["flow"][1], -1)                             # the step's now too high to walk up
        self.assertEqual(out["door"][0], -1)                             # a shut door blocks the way
        self.assertGreater(out["door"][1], 0)                            # unless walkers may open it

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_coloured_light_marks_and_walls_you_see_through(self):
        """A cell's tint picks its own colormap (glowing colours stay as they are); marks are stamped into copies of a
        wall's face or a floor's texture, the oldest copy given back when the pool is full; a see-through wall is drawn
        over what's behind it, blocks walking and the way round, but not sight; a line says which face it hit."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, out = {};
const ramps = []; for (let r = 0; r < 16; r++) ramps.push([40 + r * 12, 60 + r * 8, 80 + r * 5]);
const pal = new L.Palette(ramps, [14, 15]); pal.tints([[1.4, 0.6, 0.4]]); pal.maps(0, 0);
out.tinted = pal.cmap.length === 2 * 8192 && pal.cmap[8192 + (31 << 8) + 3 * 16 + 10] !== pal.cmap[(31 << 8) + 3 * 16 + 10];
out.glowSame = pal.cmap[8192 + (10 << 8) + 14 * 16 + 9] === pal.cmap[(10 << 8) + 14 * 16 + 9];
const m = new L.RayMap(8, 6);
for (let y = 0; y < 6; y++) for (let x = 0; x < 8; x++) { const i = y * 8 + x; if (x === 0 || y === 0 || x === 7 || y === 5) { m.solid[i] = 1; m.wtex[i] = 1; } else { m.ftex[i] = 2; m.ctex[i] = 3; m.ceil[i] = 1.2; m.light[i] = 31; } }
const T = (k) => L.Tex.make(() => k * 16 + 8);
const bars = L.Tex.mask((u, v) => (u & 15) < 4 ? 5 * 16 + 8 : 0);
const ray = new L.Ray(pal); ray.tex = [T(0), T(1), T(2), T(3), bars];
const W = 64, H = 36, buf = new Uint32Array(W * H); ray.size(W, H, buf);
const cam = { x: 1.5, y: 2.5, z: 0.5, a: 0, pitch: 0, fov: 1.6 };
ray.render(m, cam); const plain = buf.slice();
for (let i = 0; i < 48; i++) m.tint[i] = 1;
ray.render(m, cam); let changed = 0; for (let i = 0; i < W * H; i++) if (buf[i] !== plain[i]) changed++;
out.tintDraws = changed > W * H * 0.5;
m.tint.fill(0);
// marks: a hole in the far wall where a line straight ahead hits it, a scorch on the floor
const t = m.trace(1.5, 2.5, 0.5, 9, 2.5, 0.5); out.hit = [m.hitI === 2 * 8 + 7, m.hitFace];
const marks = new L.Marks(ray, m, 4);
marks.wall(m.hitI, m.hitFace, 1.5 + 7.5 * t, 2.5, 0.5, { r: 6, kind: "hole" });
out.wallMarked = m.wdec[(2 * 8 + 7) * 4 + 0] > 0;
marks.floor(3.5, 3.5, { r: 40, kind: "scorch" });
let floors = 0; for (let i = 0; i < 48; i++) if (m.fdec[i]) floors++;
out.floorCells = floors;                                   // (a scorch 40 texels across reaches its neighbours)
ray.render(m, cam); let marked = 0; for (let i = 0; i < W * H; i++) if (buf[i] !== plain[i]) marked++;
out.marksDrawn = marked > 0;
out.pool = marks.tex.length - 1;                           // never more copies than it was given
// a row of bars across the room at x = 4: drawn, blocking, seen through
for (let y = 1; y < 5; y++) m.mask[y * 8 + 4] = 4;
m.wdec.fill(0); m.fdec.fill(0);
ray.render(m, cam);
const barCols = new Set(); for (let L2 = 0; L2 < 32; L2++) barCols.add(pal.cmap[(L2 << 8) + 5 * 16 + 8]);
out.barsDrawn = (() => { let n = 0; for (let i = 0; i < W * H; i++) if (barCols.has(buf[i])) n++; return n > 20; })();
const b = { x: 3.5, y: 2.5, z: 0 }; m.move(b, 0.9, 0, 0.2, 0.35, 0.6); out.blocked = b.x < 4;
out.seeThrough = m.see(1.5, 2.5, 0.5, 6.5, 2.5, 0.5);
out.noWay = m.flow(6.5, 2.5, 0.35, 0.6)[2 * 8 + 1];
out.helpers = typeof L.helpersFor({ cores: 4 }) === "number" && L.helpersFor({ cores: 4 }) === 2 && L.helpersFor({ cores: 2 }) === 0;
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["tinted"] and out["glowSame"] and out["tintDraws"])
        self.assertEqual(out["hit"], [True, 0])                          # the far wall's west face
        self.assertTrue(out["wallMarked"] and out["marksDrawn"])
        self.assertGreater(out["floorCells"], 1)
        self.assertLessEqual(out["pool"], 4)
        self.assertTrue(out["barsDrawn"] and out["blocked"] and out["seeThrough"])
        self.assertEqual(out["noWay"], -1)                               # the bars close the room in two
        self.assertTrue(out["helpers"])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_software_picture_gives_up_pixels_before_frames(self):
        """The software-drawn ladder: every rung but the lowest two holds 60 frames a second, and each asks more of the
        processor than the one under it; a Pi 3 starts at 240 x 135 and is shown on 640 x 360; a player can hold the
        picture's size, its rate, or both; far off, a texture goes over to smaller selves that don't crawl."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L = window.Low3D, out = {}, lad = L.LADDER.ray;
out.rates = lad.map(r => r.fps); out.work = lad.map(r => r.h * r.h * r.fps);
out.glow = lad.map(r => r.glow);
const box = (family, cores, soft) => ({ family, cores, webgl1: true, software: !!soft });
const pl = (p, cpu) => { const r = L.planRay(p, { cpu }); return [lad[r.rung].h, lad[r.rung].fps, lad[r.top].h, r.show, r.fx, r.helpers]; };
out.pi3 = pl(box("pi3", 4), 95); out.pi3fast = pl(box("pi3", 4), 20); out.pi3slow = pl(box("pi3", 4), 400);
out.pi4 = pl(box("pi4", 4), 45); out.desk = pl(box("desktop", 8), 4); out.soft = pl(box("desktop", 8, true), 4);
out.heldSize = L.heldRay(135, 0); out.heldRate = L.heldRay(0, 30).map(r => [r.h, r.fps]); out.heldBoth = L.heldRay(180, 60); out.heldNone = L.heldRay(0, 0);
// smaller selves: a fine checker of two shades goes to one colour of the same ramp; a block a quarter light stays a light
const ramps = []; for (let r = 0; r < 16; r++) ramps.push([40 + r * 12, 60 + r * 8, 80 + r * 5]);
const pal = new L.Palette(ramps, [14, 15]); pal.maps(0, 0);
const ray = new L.Ray(pal), W = 96, H = 54, buf = new Uint32Array(W * H); ray.size(W, H, buf);
const checker = L.Tex.make((u, v) => 3 * 16 + ((u + v) & 1 ? 4 : 12));
const lamps = L.Tex.make((u, v) => (u & 3) === 0 && (v & 3) === 0 ? 14 * 16 + 12 : (u & 3) < 2 && (v & 3) < 2 ? 14 * 16 + 12 : 2 * 16 + 5);
const m = new L.RayMap(24, 5);
for (let y = 0; y < 5; y++) for (let x = 0; x < 24; x++) { const i = y * 24 + x; if (x === 0 || y === 0 || x === 23 || y === 4) { m.solid[i] = 1; m.wtex[i] = 1; } else { m.ftex[i] = 2; m.ctex[i] = 3; m.ceil[i] = 1; m.light[i] = 31; } }
ray.tex = [checker, checker, checker, lamps]; ray.dim = 0;
const cam = { x: 1.5, y: 2.5, z: 0.5, a: 0, pitch: 0, fov: 1.6 };
const colours = () => { const far = new Set(); for (let y = 29; y < 33; y++) for (let x = 30; x < 66; x++) far.add(buf[y * W + x]); return far.size; };
ray.far = 0; ray.render(m, cam); ray.flush(); out.crawl = colours();
ray.far = 1; ray.render(m, cam); ray.flush(); out.calm = colours();
const sm = ray.core.smaller(checker);
out.levels = sm.length; out.one = new Set(sm[1]).size; out.sameRamp = sm[1][0] >> 4; out.between = (sm[1][0] & 15) > 4 && (sm[1][0] & 15) < 12; out.sized = sm.every(a => a.length === 4096);
const sl = ray.core.smaller(lamps); out.lampStays = pal.full[sl[2][0]] === 1; out.kept = checker.m === sm;
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["rates"][:2], [30, 30])
        self.assertTrue(all(f == 60 for f in out["rates"][2:]), out["rates"])
        self.assertEqual(out["work"], sorted(out["work"]))                # each rung more work than the last
        self.assertEqual(len(set(out["work"])), len(out["work"]))
        self.assertEqual(out["pi3"], [135, 60, 180, 360, True, 2])        # a Pi 3: 240 x 135 at 60, never over 320 x 180, on a 640 x 360 canvas
        self.assertEqual(out["pi3fast"][:3], [135, 60, 180])              # (a quick test doesn't lift it)
        self.assertEqual(out["pi3slow"][:2], [108, 60])                   # a slow one: the smallest picture, still at 60
        self.assertEqual(out["pi4"][3], 540)
        self.assertEqual((out["desk"][0], out["desk"][3]), (360, 1080))
        self.assertEqual((out["soft"][3], out["soft"][4]), (360, False))  # no GPU: nothing more is asked of the processor than the picture
        self.assertEqual([(r["h"], r["fps"]) for r in out["heldSize"]], [(135, 30), (135, 60)])
        self.assertEqual(out["heldRate"][0], [108, 30]); self.assertEqual(out["heldRate"][-1], [360, 30])
        self.assertTrue(all(f == 30 for _, f in out["heldRate"]))
        self.assertEqual([(r["h"], r["fps"]) for r in out["heldBoth"]], [(180, 60)])
        self.assertIsNone(out["heldNone"])
        self.assertEqual((out["levels"], out["one"], out["sameRamp"]), (5, 1, 3))
        self.assertTrue(out["between"] and out["sized"] and out["lampStays"] and out["kept"], out)
        self.assertGreater(out["crawl"], out["calm"])                     # far off: fewer colours fighting for a pixel
        self.assertLessEqual(out["calm"], 3)                              # (the floor, the ceiling, the wall at the end)

    def test_ironmaw_writes_on_its_own_canvas(self):
        """Nothing of Ironmaw's page lies over its picture (on a Pi 3 the browser puts such a layer together again at
        the TV's size every frame): its numbers, messages, map and flashes are the engine's UI list. Its options hold
        the picture's size and rate and turn the effects on and off, and a slow box starts on the light set."""
        with open(os.path.join(self.GAMES, "ironmaw", "index.html"), encoding="utf-8") as f:
            src = f.read()
        page = src[:src.index("<script>")]
        for gone in ('id="hud"', 'id="tint"', 'id="frost"', 'id="map"', 'id="msg"', 'id="center"', 'id="fps"', 'id="feed"', 'id="board"', "radial-gradient", "#ffd890"):
            self.assertNotIn(gone, src, gone)
        self.assertIn(".screen > * { will-change: transform; }", page)   # a menu's blocks: each a small layer of its own
        self.assertNotIn("background", page[page.index(".screen {"):page.index(".screen > *")])
        self.assertIn('id="picture"', page); self.assertIn('data-do="check"', page)
        for k in ("quality", "lines", "rate", "glow", "lights", "debris", "marks", "weather", "vig", "crisp", "cores", "fps"):
            self.assertRegex(src, r'\{ k: "%s", name: "' % k)
        self.assertIn("tune: () => TUNE", src)
        self.assertIn("const SETS = { light: {", src)
        self.assertIn("ui.begin(W, H)", src); self.assertIn("ui.hold()", src); self.assertIn("ui.rewind()", src)
        self.assertIn('if (still && frozen === still) return false;', src)   # under a menu the picture stands still: nothing drawn, nothing sent
        self.assertIn("E.tell()", src)

    def test_ironmaws_levels_can_be_played_through(self):
        """Each level: one start, every key before its door, the exit (or a great one) reached, every enemy and item
        reached. Walls you see through (H bars, _ railings, G windows, Z fences) are walls to walk into."""
        import re
        with open(os.path.join(self.GAMES, "ironmaw", "index.html"), encoding="utf-8") as f:
            html = f.read()
        block = html[html.index("const LEVELS = {"):html.index("};", html.index("const LEVELS = {"))]
        levels = {m.group(1): re.findall(r'"([^"]*)"', m.group(2)) for m in re.finditer(r"(\w+): \[(.*?)\]", block, re.S)}
        self.assertEqual(list(levels), ["intake", "refinery", "towers", "heart", "cryo", "mine", "pumps", "reactor", "engine"])
        order = html[html.index("const ORDER = ["):html.index("];", html.index("const ORDER = ["))]
        self.assertEqual(re.findall(r'id: "(\w+)"', order), list(levels))           # each map has its place, in order
        solid, masks, doors = set("#%&T|FRWXICKMP"), set("HGZ_"), {"D": None, "Q": "q", "U": "u", "Y": "y", "?": None}
        height = {"O": 0.25, "-": 0.25, "=": 0.5, "^": 0.9, "~": -0.06, "!": -0.06, "J": 0.25, ";": 0.25, "n": -0.08}
        ground_chars, thing_chars, bosses = set(".,:*oO-=^~!L$ijJE;nVA") | set(doors), set("@hgsbwfBzN+mackerl34567quyxtpvSd"), set("wN")
        for name, rows in levels.items():
            w = max(len(r) for r in rows)
            g = [list(r.ljust(w).replace(" ", "#")) for r in rows]
            h = len(g)
            ground, things = {}, []
            for y in range(h):
                for x in range(w):
                    c = g[y][x]
                    if (x in (0, w - 1) or y in (0, h - 1)) and c not in solid:
                        self.fail("%s: open edge at %d,%d" % (name, x, y))
                    if c in solid or c in masks:
                        continue
                    self.assertIn(c, ground_chars | thing_chars, "%s: %r at %d,%d" % (name, c, x, y))
                    if c in thing_chars:
                        things.append((c, x, y))
                        c = next((g[y][xx] for d in range(1, 6) for xx in (x - d, x + d) if 0 <= xx < w and g[y][xx] in ground_chars
                                  and g[y][xx] not in doors and g[y][xx] != "L"), ".")
                    ground[(x, y)] = c
            starts = [(x, y) for c, x, y in things if c == "@"]
            self.assertEqual(len(starts), 1, name)
            keys = set()
            while True:
                seen, todo = {starts[0]}, [starts[0]]
                while todo:
                    x, y = todo.pop()
                    for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if n in seen or n not in ground:
                            continue
                        c, here = ground[n], ground[(x, y)]
                        if c in doors and doors[c] and doors[c] not in keys:
                            continue
                        if c != "L" and here != "L" and height.get(c, 0) > height.get(here, 0) + 0.35:
                            continue
                        seen.add(n); todo.append(n)
                found = {c for c, x, y in things if c in "quy" and (x, y) in seen}
                if found <= keys:
                    break
                keys |= found
            unreached = [(c, x, y) for c, x, y in things if (x, y) not in seen]
            self.assertEqual(unreached, [], name)
            exits = [(x, y) for y in range(h) for x in range(w) if g[y][x] == "X"]
            boss = any(c in bosses for c, x, y in things)
            self.assertTrue(boss or any((ex + dx, ey + dy) in seen for ex, ey in exits for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))), name)
            for d, k in doors.items():                                   # a door that needs a key has its key on the map
                if k and any(d in r for r in rows):
                    self.assertIn(k, {c for c, x, y in things}, name)

    def test_ironmaws_arenas_are_fair(self):
        """Each arena: closed, at least 8 starts (one per fighter), a ring to hold, and from every start every other
        start, the ring and every pickup can be walked to (nobody starts shut in, nothing is out of reach)."""
        import re
        with open(os.path.join(self.GAMES, "ironmaw", "index.html"), encoding="utf-8") as f:
            html = f.read()
        block = html[html.index("const ARENAS = {"):html.index("};", html.index("const ARENAS = {"))]
        arenas = {m.group(1): re.findall(r'"([^"]*)"', m.group(2)) for m in re.finditer(r"(\w+): \[(.*?)\]", block, re.S)}
        listed = html[html.index("const ARENA_LIST = ["):html.index("];", html.index("const ARENA_LIST = ["))]
        self.assertEqual(re.findall(r'id: "(\w+)"', listed), list(arenas))
        self.assertEqual(len(arenas), 6)
        solid, masks = set("#%&T|FRWXICKMP"), set("HGZ_")
        height = {"O": 0.25, "-": 0.25, "=": 0.5, "^": 0.9, "~": -0.06, "!": -0.06, "J": 0.25, ";": 0.25, "n": -0.08}
        ground_chars, thing_chars = set(".,:*oO-=^~!L$ijJE;nVA0812"), set("@+mackerl34567xtpvSd")
        for name, rows in arenas.items():
            w = max(len(r) for r in rows)
            g = [list(r.ljust(w).replace(" ", "#")) for r in rows]
            ground, things = {}, []
            for y in range(len(g)):
                for x in range(w):
                    c = g[y][x]
                    if (x in (0, w - 1) or y in (0, len(g) - 1)) and c not in solid:
                        self.fail("%s: open edge at %d,%d" % (name, x, y))
                    if c in solid or c in masks:
                        continue
                    self.assertIn(c, ground_chars | thing_chars, "%s: %r at %d,%d" % (name, c, x, y))
                    if c in thing_chars:
                        things.append((c, x, y))
                        c = next((g[y][xx] for d in range(1, 6) for xx in (x - d, x + d) if 0 <= xx < w and g[y][xx] in ground_chars and g[y][xx] != "L"), None)
                        self.assertIsNotNone(c, "%s: %r at %d,%d is in a wall" % (name, things[-1][0], x, y))
                    ground[(x, y)] = c
            starts = [(x, y) for c, x, y in things if c == "@"]
            ring = [p for p, c in ground.items() if c == "0"]
            self.assertGreaterEqual(len(starts), 8, name)
            self.assertTrue(ring, name + ": no ring")
            for s in starts:
                seen, todo = {s}, [s]
                while todo:
                    x, y = todo.pop()
                    for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if n in seen or n not in ground:
                            continue
                        c, here = ground[n], ground[(x, y)]
                        if c != "L" and here != "L" and height.get(c, 0) > height.get(here, 0) + 0.35:
                            continue
                        seen.add(n); todo.append(n)
                unreached = [(c, x, y) for c, x, y in things if (x, y) not in seen and c not in "xtpvSd"]
                self.assertEqual(unreached, [], "%s from %s" % (name, s))
                self.assertTrue(all(p in seen for p in ring), "%s: the ring from %s" % (name, s))


# Low2D in node: PADS_JS's window, then the screen and a fake localStorage
L2_JS = r"""
def("innerWidth", 1920); def("innerHeight", 1080); def("devicePixelRatio", 1); def("screen", { width: 1920, height: 1080 });
document.addEventListener = () => {};
const store = {}; def("localStorage", { getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } });
const L2 = window.Low2D, name = t => t.name + t.fps, wait = ms => new Promise(r => setTimeout(r, ms));
const canvas = () => ({ width: 0, height: 0, style: {}, getContext: () => null });
const drawable = () => ({ width: 256, height: 256, style: {}, getContext: () => ({ save() {}, restore() {}, beginPath() {}, rect() {}, clip() {}, clearRect() {}, drawImage() {}, fillRect() {} }) });
"""


class TheEngine2D(unittest.TestCase):
    """Low2D (games/low2d.js), the box's 2D engine on top of Low3D: the looks and the pace each box gets, the governor that
    keeps them steady (stepping down before a stutter shows, never below 30 a second), the fixed-step loop and its
    hit-stop, tiles to move through, the particles' pool, saves that #demo never writes, presses kept for the fixed
    steps, and the picture fitted to the TV at a whole-number scale."""

    def read_game(self, gid):
        with open(os.path.join(BOX, "games", gid, "index.html"), encoding="utf-8") as f:
            return f.read()

    def node(self, script):
        return pads_in_node(self, L2_JS + "(async () => {" + script + "\nconsole.log(JSON.stringify(out)); })().catch(e => { console.error(e); process.exit(1); });",
                            "pad.js", "low3d.js", "low2d.js")

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_looks_and_the_pace_each_box_gets(self):
        out = self.node(r"""
out.ladders = [L2.ladder("auto", "auto"), L2.ladder("auto", "30"), L2.ladder("full", "auto"), L2.ladder("light", "60")].map(l => l.map(name));
const P = (family, cpu, extra, lad) => { lad = lad || L2.TIERS; const r = L2.plan(Object.assign({ family, webgl1: family !== "none", software: family === "software", memory: 4, arch: "" }, extra || {}), { cpu }, 1, lad);
  return name(lad[r.rung]) + " up to " + name(lad[r.top]); };
out.plans = { pi3: P("pi3", 95), pi3steady: P("pi3", 95, null, L2.ladder("auto", "30")), pi4: P("pi4", 30), slow: P("desktop", 80), fast: P("desktop", 5),
  software: P("software", 5), small: P("none", 50, { memory: 1, arch: "arm64" }) };
const slowed = L2.plan({ family: "desktop", webgl1: true, memory: 8, arch: "" }, { cpu: 4 }, 20); out.slowed = name(L2.TIERS[slowed.rung]);   // (#slow=20: a fast box as a slow one)
""")
        self.assertEqual(out["ladders"], [["light30", "full30", "light60", "full60", "rich60"], ["light30", "full30", "rich30"], ["full30", "full60"], ["light60"]])
        p = out["plans"]
        self.assertEqual(p["pi3"], "light60 up to light60")                 # a Pi 3 starts light and stays there at 60,
        self.assertEqual(p["pi3steady"], "light30 up to full30")           # (at a steady 30 there's room for the full look)
        self.assertEqual(p["pi4"], "full60 up to rich60")
        self.assertEqual(p["slow"], "light60 up to full60")
        self.assertEqual(p["fast"], "rich60 up to rich60")                 # a fast processor with a real GPU: the rich look
        self.assertEqual(p["software"], "full60 up to rich60")             # (fast, but no GPU: full)
        self.assertEqual(p["small"], "light60 up to light60")              # a 1 GB ARM board, whatever its GPU says
        self.assertEqual(out["slowed"], "light60")

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_game_says_how_it_ran_for_the_report(self):
        """On the box a page's console errors are what "Send a report" keeps of a page, so a game on Low2D says how it
        ran there: every five minutes of play and when it's left, never off the box, never the demo, never for a few
        seconds' play; and what's counted starts again each time."""
        out = self.node(r"""
const said = [], real = console.error; console.error = (...a) => { said.push(a.join(" ")); };
location.hash = "#tier=light&pace=60"; location.pathname = "/box/games/tell/";
const G = L2.game({ id: "tell", canvas: canvas(), update() {}, draw() {} });
G.start(); await wait(40); frames(4, 1000 / 60);
G.tell(); out.early = said.length;                                    // a few frames in: nothing worth saying yet
frames(60 * 30, 1000 / 60); out.line = G.ran(); G.tell(); out.said = said.slice(); out.left = G.gov.ran.frames;
frames(60 * 320, 1000 / 60); out.byItself = said.length;              // five minutes of play: said without being asked
(on.pagehide || []).forEach(f => f()); out.leaving = said.length;     // and when the game is left
location.pathname = "/games/tell/"; frames(60 * 30, 1000 / 60); G.tell(); out.offBox = said.length;
location.pathname = "/box/games/demo/"; location.hash = "#demo";
const D = L2.game({ id: "demo", canvas: canvas(), update() {}, draw() {} });
D.start(); await wait(40); frames(60 * 30, 1000 / 60); D.tell(); out.demo = said.length;
console.error = real;
""")
        self.assertEqual(out["early"], 0)
        self.assertRegex(out["line"], r"^tell ran: 2D light rung 0 of 0 480x270, 60 fps over (2[89]|30) s \(wanted 60, lowest second 60\), 0 of \d+ frames late, worst 17 ms, work ")
        self.assertEqual(out["said"], [out["line"]])
        self.assertEqual(out["left"], 0)                                    # counted afresh
        self.assertEqual(out["byItself"], 2)
        self.assertEqual(out["leaving"], 3)
        self.assertEqual((out["offBox"], out["demo"]), (3, 3))             # not off the box, and never the demo

    def test_gloamwell_says_how_it_ran_too(self):
        """Gloamwell has an engine of its own; it says the same line for the report: counted while a floor is played,
        said every five minutes and when it's left, on the box only, never the demo."""
        src = self.read_game("gloamwell")
        self.assertIn("govern(dt); ranNote(dt);", src)
        self.assertIn("if (mode !== M_PLAY || document.hidden || irisFn || !(dt > 0) || dt > 0.25) return;", src)
        self.assertIn("if (RAN.secs >= 300) ranTell();", src)
        self.assertIn('addEventListener("pagehide", ranTell);', src)
        self.assertIn("if (DEMO || RAN.secs < 20 || !/^\\/box\\//.test(location.pathname)) return;", src)
        self.assertIn('console.error(ranLine());', src)
        self.assertIn('"gloamwell ran: FX "', src)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_governor_steps_before_a_stutter_and_never_below_30(self):
        out = self.node(r"""
const lad = L2.ladder("auto", "auto"), g = new L2.Governor(lad, 3, 4);
let drawn = 0, late = 0, last = 0;
const run = (secs, work, stop) => { drawn = 0; for (let i = 0; i < secs * 60 && !(stop && stop()); i++) { now += 1000 / 60; if (g.tick(now)) { drawn++; if (last && now - last > 1000 / lad[g.rung].fps * 1.5) late++; last = now; g.work(work); } } };
const at = () => name(lad[g.rung]);
g.hold(0);
run(14, 2); out.up = at();                                           // calm: up to the top (rich)
run(4, 13, () => g.rung < 4); out.down = [at(), g.log[g.log.length - 1], late];   // 13 ms of 16.7 a frame, none late yet: down before it stutters
run(16, 26); out.floor = at();                                        // far too busy: all the way down, then
run(4, 26); out.stays = at();                                         // no lower than a steady 30
run(3, 20); out.drawn30 = drawn;                                      // (every other refresh drawn)
out.path = g.log.map(l => l.match(/(\d)→(\d)/).slice(1).join(">")).join(" ");
const h = new L2.Governor(lad, 4, 4); h.hold(0);
for (let k = 0; k < 2; k++) { for (let i = 0; i < 260; i++) { now += 1000 / 60; if (h.tick(now)) h.work(13); } for (let i = 0; i < 900; i++) { now += 1000 / 60; if (h.tick(now)) h.work(2); } }
out.twice = name(lad[h.rung]);                                        // rich failed twice: not tried a third time
""")
        self.assertEqual(out["up"], "rich60")
        self.assertEqual(out["down"][0], "full60")
        self.assertIn("busy", out["down"][1])                              # down on the work alone,
        self.assertEqual(out["down"][2], 0)                                # before a frame was late
        self.assertEqual(out["path"], "3>4 4>3 3>2 2>1 1>0")               # rich, full, light at 60; then full, light at a steady 30
        self.assertEqual((out["floor"], out["stays"]), ("light30", "light30"))
        self.assertTrue(85 <= out["drawn30"] <= 95, out["drawn30"])         # 3 s at 30 a second: about 90 frames
        self.assertEqual(out["twice"], "full60")

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_loop_hit_stop_and_the_tv(self):
        out = self.node(r"""
let ups = 0;
location.hash = "#tier=full&pace=60";
const G = L2.game({ id: "t1", canvas: canvas(), update() { ups++; }, draw() {} });
G.start(); await wait(40); frames(4, 1000 / 60);
out.ready = G.ready; out.tier = SofaStats.tier; out.box = JSON.parse(localStorage.getItem("sofa:box") || "null") !== null;
ups = 0; frames(120, 1000 / 60); out.at60 = ups;                     // 2 s at 60 a second: 120 steps
G.stop(100); ups = 0; frames(5, 1000 / 60); out.stopped = ups;        // hit-stop: the world holds 100 ms
frames(10, 1000 / 60); out.after = ups;
ups = 0; frames(30, 1000 / 30); out.slowFrames = ups;                 // frames twice as far apart: two steps each
// the TV: 1080p is 4 times 480×270 exactly; 720p isn't a whole number, so it fits as big as it can
G.fit(); out.scale1080 = G.scale; def("innerWidth", 1280); def("innerHeight", 720); G.fit(); out.scale720 = Math.round(G.scale * 100) / 100;
// steady 30: half the frames drawn, the same game speed
location.hash = "#tier=light&pace=30"; let ups2 = 0;
const G2 = L2.game({ id: "t2", canvas: canvas(), update() { ups2++; }, draw() {} });
G2.start(); await wait(40); frames(4, 1000 / 60); ups2 = 0;
frames(120, 1000 / 60); out.at30 = ups2; out.drawn30 = G2.gov.frames;
// presses kept for the fixed steps: taken once, and not when they're stale
const c = G2.control(); G2.pressAt[0].a = performance.now(); out.take = [c.take("a"), c.take("a")];
G2.pressAt[0].b = performance.now() - 300; out.stale = c.take("b", 120);
""")
        self.assertTrue(out["ready"] and out["box"])                        # the box's test, kept for every game (sofa:box)
        self.assertEqual(out["tier"], "2D full, 60 fps (rung 0 of 0)")
        self.assertTrue(118 <= out["at60"] <= 122, out["at60"])
        self.assertLessEqual(out["stopped"], 1)                              # held still,
        self.assertGreaterEqual(out["after"], 7)                             # then on again
        self.assertTrue(58 <= out["slowFrames"] <= 62, out["slowFrames"])
        self.assertEqual((out["scale1080"], out["scale720"]), (4, 2.67))
        self.assertTrue(118 <= out["at30"] <= 122, out["at30"])
        self.assertEqual(out["take"], [True, False])
        self.assertFalse(out["stale"])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_tiles_particles_and_saves(self):
        out = self.node(r"""
const m = new L2.TileMap(12, 8, 16); m.flags[1] = L2.SOLID; m.flags[2] = L2.ONEWAY; m.outside = 1;
for (let x = 0; x < 12; x++) m.t[7 * 12 + x] = 1;                    // the floor's top: y 112
for (let y = 2; y < 7; y++) m.t[y * 12 + 7] = 1;                     // a wall at x 112
for (let x = 1; x < 5; x++) m.t[4 * 12 + x] = 2;                     // a ledge you jump up through: y 64
const b = { x: 40, y: 90, w: 10, h: 20 };
let hit = 0; for (let i = 0; i < 20; i++) hit |= m.move(b, 0, 4);
out.floor = [b.y, !!(hit & L2.DOWN), m.ground(b)];
hit = m.move(b, 200, 0); out.wall = [b.x, !!(hit & L2.RIGHT)];        // a dash at the wall stops at it (no passing through)
b.x = 40; b.y = 112; m.move(b, 0, -60); out.through = b.y;            // up through the ledge,
hit = 0; for (let i = 0; i < 10; i++) hit |= m.move(b, 0, 3); out.onLedge = [b.y, !!(hit & L2.DOWN)];   // and down onto it
m.move(b, 0, 6, true); out.dropped = b.y;                             // (down and jump: through it)
out.touch = m.touch({ x: 120, y: 60, w: 10, h: 20 }, L2.SOLID) >= 0;
// a changed tile: drawn again where it is, the chunk not made again
let painted = 0; m.paint = () => { painted++; }; m.chunks[0] = drawable(); m.dirty[0] = 0; m.set(3, 2, 1); out.repaint = [painted > 0, painted < 30, m.dirty[0]];
// particles: a fixed pool, the tier's share of each burst
const P = new L2.Particles(16, { c: null }); P.emit(0, 0, 40, { c: 0, life: 1 }); P.step(0.01); out.pool = P.alive;
P.clear(); P.k = 0.5; P.emit(0, 0, 10, { c: 0, life: 1 }); P.step(0.01); out.half = P.alive;
// saves: kept, but never in #demo
location.hash = ""; const A = new L2.Store("t-save", () => ({ n: 1, opts: { music: 5 } })); A.data.n = 7; out.saved = A.save();
const B = new L2.Store("t-save", () => ({ n: 1, opts: { music: 5, sound: 3 } })); out.loaded = [B.data.n, B.data.opts.music, B.data.opts.sound];
location.hash = "#demo"; const D = new L2.Store("t-demo", () => ({ n: 1 })); out.demo = [D.save(), localStorage.getItem("t-demo"), new L2.Store("t-save", () => ({ n: 1 })).data.n];
// the pixel font has the controller's buttons in it
out.font = [L2.font.width("A"), L2.font.code("✕", 0), L2.font.code("△", 0), L2.font.wrap("THE HEARTH THAT WARMED THE REACH", 80).length];
""")
        self.assertEqual(out["floor"], [112, True, True])
        self.assertEqual(out["wall"], [107, True])
        self.assertEqual(out["through"], 52)
        self.assertEqual(out["onLedge"], [64, True])
        self.assertGreater(out["dropped"], 64)
        self.assertTrue(out["touch"])
        self.assertEqual(out["repaint"], [True, True, 0])
        self.assertEqual((out["pool"], out["half"]), (16, 5))
        self.assertEqual((out["saved"], out["loaded"]), (True, [7, 5, 3]))   # what was kept over the defaults, new defaults kept
        self.assertEqual(out["demo"], [False, None, 1])                       # #demo: nothing written, nothing read
        self.assertEqual(out["font"], [5, 16, 19, 3])


# the knight in node: the game's own rules (its first script) played from every place it can stand
REACH_JS = r"""
const R = window.CinderRules, TS = R.TS, K = R.K;
function reach(rows, moves) {
  const st = R.parse(rows), map = st.map, W = st.w, H = st.h;
  for (let i = 0; i < map.t.length; i++) { if (map.t[i] === K.CRACK) map.t[i] = K.AIR; if (map.t[i] === K.VEIL && moves.shield) map.t[i] = K.AIR; }
  const solid = (x, y) => (map.flag(x, y) & L2.SOLID) !== 0, hurt = (x, y) => (map.flag(x, y) & L2.HURT) !== 0;
  const stand = (x, y) => x >= 0 && x < W && y >= 1 && y < H && (map.flag(x, y) & (L2.SOLID | L2.ONEWAY)) && !solid(x, y - 1) && !solid(x, y - 2) && !hurt(x, y - 1) && !hurt(x, y - 2);
  const thingAt = new Map(); for (const t of st.things) thingAt.set(t.y * W + t.x, t);
  const start = st.things.find(t => t.c === "@"); let sy = start.y + 1; while (sy < H && !stand(start.x, sy)) sy++;
  const seen = new Set(), clings = new Map(), todo = [], touched = new Set();
  const add = (x, y) => { const k = y * W + x; if (!seen.has(k) && stand(x, y)) { seen.add(k); todo.push(["s", x, y]); } };
  const addCling = k => { const id = k.cling + ":" + Math.floor(k.x / TS) + ":" + Math.floor(k.y / 8); if (!clings.has(id)) { clings.set(id, { x: k.x, y: k.y, s: k.cling }); todo.push(["c", id]); } };
  const touch = (k, out) => { const x0 = Math.floor((k.x - k.w / 2) / TS), x1 = Math.floor((k.x + k.w / 2 - 0.01) / TS), y0 = Math.floor((k.y - k.h) / TS), y1 = Math.floor((k.y - 0.01) / TS);
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) if (thingAt.has(y * W + x)) out.push(y * W + x); };
  const HOLD = [9, 0.12];
  function run(k0, plan) {
    const k = Object.assign({}, k0), inp = { x: plan.x, y: plan.y || 0, jump: false, held: false, dash: false, slow: 1 }, got = [];
    let t = 0, left = false;
    for (let n = 0; n < 200; n++) {
      inp.jump = plan.jumpAt === 0 && n === 0; inp.held = plan.jumpAt === 0 ? t < plan.hold : plan.didDouble && t < plan.hold2; inp.dash = false;
      if (!k.ground) left = true;
      if (plan.double && !plan.didDouble && (plan.double === "apex" ? k.vy >= 0 && t > 0.02 : left && t > 0.06)) { inp.jump = true; plan.didDouble = true; plan.hold2 = t + 9; plan.dt2 = t + 0.3; }
      if (plan.dash && !plan.didDash && (plan.dash === "apex" ? k.vy >= 0 && t > 0.02 && (!plan.double || plan.didDouble && t > plan.dt2) : plan.dash === "early" ? t > 0.08 : left && t > 0.04)) { inp.dash = true; plan.didDash = true; }
      R.step(k, inp, 1 / 60, map, moves); t += 1 / 60;
      if (k.y > H * TS + 40 || map.touch(k, L2.HURT) >= 0) return null;
      touch(k, got);
      if (k.cling && plan.from !== "c") { for (const g of got) touched.add(g); addCling(k); return null; }
      if (k.ground && left && n > 1) { for (const g of got) touched.add(g); return k; }
      if (plan.from === "walk" && k.ground && !left && n > 120) return null;
    }
    return null;
  }
  const landed = k => { if (!k) return; const y = Math.round(k.y / TS), a = Math.floor((k.x - k.w / 2) / TS), b = Math.floor((k.x + k.w / 2 - 0.01) / TS), m = Math.floor(k.x / TS);
    if (stand(m, y)) add(m, y); else { if (stand(a, y)) add(a, y); if (stand(b, y)) add(b, y); } };
  const fresh = (x, y) => { const k = R.knight(x * TS + 8, y * TS); k.ground = true; k.coyote = R.PHYS.coyote; k.air2 = !!moves.double; return k; };
  const DBL = moves.double ? [null, "apex"] : [null], DSH = moves.dash ? [null, "apex", "early"] : [null];
  if (!stand(start.x, sy)) return null;
  add(start.x, sy);
  while (todo.length) {
    const n = todo.pop();
    if (n[0] === "s") {
      const x = n[1], y = n[2], k0 = fresh(x, y), got = []; touch(k0, got); for (const g of got) touched.add(g);
      add(x - 1, y); add(x + 1, y);
      for (const xi of [-1, -0.5, 0, 0.5, 1]) for (const hold of HOLD) for (const d2 of DBL) for (const da of DSH) landed(run(k0, { x: xi, jumpAt: 0, hold, double: d2, dash: da }));
      for (const d of [-1, 1]) if (!stand(x + d, y)) {
        const kr = fresh(x, y); kr.x += d * 7; kr.vx = d * R.PHYS.run; kr.face = d;
        for (const hold of HOLD) for (const d2 of DBL) for (const da of DSH) landed(run(kr, { x: d, jumpAt: 0, hold, double: d2, dash: da }));
        for (const xi of [d, d * 0.5]) for (const d2 of DBL) for (const da of (moves.dash ? [null, "fall"] : [null])) landed(run(k0, { x: xi, jumpAt: -1, hold: 0, double: d2 && "fall", dash: da, from: "walk" }));
      }
    } else {
      const c = clings.get(n[1]), k0 = R.knight(c.x, c.y); k0.cling = c.s; k0.air2 = !!moves.double;
      landed(run(k0, { x: c.s, y: -1, jumpAt: -1, hold: 0, from: "c" })); landed(run(k0, { x: c.s, y: 1, jumpAt: -1, hold: 0, from: "c" }));
      for (const xi of [-c.s, -c.s * 0.5, 0, c.s]) for (const hold of HOLD) for (const d2 of DBL) for (const da of (moves.dash ? [null, "apex"] : [null])) landed(run(k0, { x: xi, jumpAt: 0, hold, double: d2, dash: da }));
    }
  }
  return st.things.map(t => ({ c: t.c, x: t.x, y: t.y, got: touched.has(t.y * W + t.x) }));
}
const all = { double: true, dash: true, climb: true, shield: true }, NEWEST = [null, "dash", "climb", "shield"];
out.stages = R.STAGES.map((s, i) => {
  const moves = R.movesAt(i); let first = reach(s.rows, moves);
  if (s.shrine && first.some(t => t.c === "D" && t.got)) { moves[s.shrine] = true; first = reach(s.rows, moves); }
  const every = reach(s.rows, all), without = Object.assign({}, R.movesAt(i));
  const newest = i < 2 ? null : i < 4 ? "double" : NEWEST[s.region]; if (newest) without[newest] = false;
  const w = newest ? reach(s.rows, without) : null;
  const got = (list, c) => list.filter(t => t.c === c && t.got).length, n = (c) => first.filter(t => t.c === c).length;
  return { id: s.id, region: s.region, exit: got(first, "E") > 0, shards: n("*"), shardsNow: got(first, "*"), shardsAll: got(every, "*"),
    cps: [got(first, "C"), n("C")], boss: n("B"), bossReached: got(first, "B") > 0, shrine: [n("D"), got(first, "D")], foes: first.filter(t => R.FOES[t.c]).map(t => t.c).join(""),
    needs: newest, without: w ? got(w, "E") > 0 : null };
});
out.moves = R.STAGES.map((s, i) => Object.entries(R.movesAt(i)).filter(e => e[1]).map(e => e[0]).join("+"));
"""


class TheCinderKnight(unittest.TestCase):
    """Cinder Knight, on the 2D engine: four regions of four stages, a boss ending each region; every stage can be
    finished with the moves you have by then (and not without the newest one), every brazier reached, three ember
    shards in each (two found on the way, all with every move), eight kinds of foe."""
    GAMES = os.path.join(BOX, "games")

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_every_stage_can_be_finished(self):
        import re
        with open(os.path.join(self.GAMES, "cinder-knight", "index.html"), encoding="utf-8") as f:
            html = f.read()
        rules = re.findall(r"<script>(.*?)</script>", html, re.S)[0]
        self.assertIn("window.CinderRules", rules)
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "rules.js")
            with open(path, "w", encoding="utf-8") as f:
                f.write(rules)
            r = subprocess.run(["node", "-e", PADS_JS + "const L2 = window.Low2D;" + REACH_JS + "console.log(JSON.stringify(out));"]
                               + [os.path.join(self.GAMES, f) for f in ("pad.js", "low3d.js", "low2d.js")] + [path],
                               capture_output=True, text=True, timeout=600)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        stages = out["stages"]
        self.assertEqual([s["id"] for s in stages], ["%d-%d" % (a, b) for a in range(1, 5) for b in range(1, 5)])
        self.assertEqual(out["moves"][0], "")                                 # nothing at the start;
        self.assertEqual(out["moves"][4], "double+dash")                      # the second leap (1-2's shrine) and the dash (Old Charhorn),
        self.assertEqual(out["moves"][8], "double+dash+climb")                # the climb (Brickmaw),
        self.assertEqual(out["moves"][12], "double+dash+climb+shield")        # the ember shield (the Shard Wyrm)
        kinds = set()
        for s in stages:
            sid = s["id"]
            self.assertTrue(s["exit"], sid)                                   # finished with the moves you have then
            self.assertEqual(s["shards"], 3, sid)
            self.assertEqual(s["shardsAll"], 3, sid)                          # every shard can be had,
            self.assertGreaterEqual(s["shardsNow"], 2, sid)                   # two of them on the first time through
            self.assertEqual(s["cps"][0], s["cps"][1], sid)                   # every brazier reached
            self.assertGreaterEqual(s["cps"][1], 2, sid)
            self.assertEqual(s["boss"], 1 if sid.endswith("-4") else 0, sid)  # a boss at the end of each region
            if s["boss"]:
                self.assertTrue(s["bossReached"], sid)
            if s["needs"]:
                self.assertFalse(s["without"], sid + " can be finished without " + s["needs"])
            kinds |= set(s["foes"])
        self.assertEqual(stages[1]["shrine"], [1, 1])                          # 1-2's shrine teaches the second leap
        self.assertEqual(len(kinds), 8, kinds)                                 # eight kinds of foe


class TheWyrd(unittest.TestCase):
    """WYRD (games/wyrd): every model it names is packed in the page, every foe and power it sends down is one it has,
    and the tool that packs the models is there and compiles."""

    def test_its_trees_are_grown_on_the_fuller_look_only(self):
        """WYRD's six trees: each has a grown form from the engine's Kit.tree, asked for only on the fuller look (the
        plain shapes, a Pi 3's and the 2D look's, are built when no detail is asked for), and a template is kept by
        its detail, so a change of rung never shows the other's."""
        with open(os.path.join(BOX, "games", "wyrd", "index.html"), encoding="utf-8") as f:
            page = f.read()
        grown = re.search(r"const GROWN = \[(.*?)\n\];", page, re.S)
        self.assertTrue(grown)
        crowns = re.findall(r'crown: "([a-z]+)"', grown.group(1))
        self.assertEqual(len(crowns), 6)
        self.assertTrue(set(crowns) <= {"round", "tiers", "tall", "caps", "bare"})
        self.assertIn("if (det) { const g = GROWN[tier] || GROWN[0]; L3.Kit.tree(", page)
        self.assertIn("const det = rich() ? (E.rung.h >= 1080 ? 2 : 1) : 0", page)
        self.assertIn('+ v + "d" + det', page)
        self.assertIn('case "tree": treeMesh(m, glowM, nd.x, y, nd.z, nd.tree, nd.s || 1, nd.seed || 1, !nd.on); break;', page)   # (no detail: the plain shapes)

    def test_its_models_and_its_people(self):
        with open(os.path.join(BOX, "games", "wyrd", "index.html"), encoding="utf-8") as f:
            page = f.read()
        block = re.search(r"<script>\s*/\* maker: models \*/\s*// models packed for Low3D[^\n]*\nconst MODELS = (\{.*?\});\s*/\* maker: end \*/\s*</script>", page, re.S)
        self.assertTrue(block, "the packed models")
        models = json.loads(block.group(1))
        for name, m in models.items():
            self.assertEqual(len(m["c"]) > 0 and len(m["box"]), 6, name)
        named = set(re.findall(r'\bmodel: "([a-z]+)"', page)) | set(re.findall(r'putModel\([^,]+, "([a-z]+)"', page))
        for props in re.findall(r"props: \[([^\]]*)\]", page):
            named |= set(re.findall(r'"([a-z]+)"', props))
        for name in named:
            self.assertIn(name, models, name)
        foes = set(re.findall(r"^  ([a-z]+): \{ name: ", page, re.M))
        for kinds in re.findall(r'foes: \[([^\]]*)\], elite: "([a-z]+)"', page):
            for k in re.findall(r'"([a-z]+)"', kinds[0]) + [kinds[1]]:
                self.assertIn(k, foes, k)
        for boss in re.findall(r'boss: "([a-z]+)"', page):
            self.assertIn(boss + ": { name:", page.replace("  ", " "), boss)
        tool = os.path.join(os.path.dirname(os.path.dirname(BOX)), "tools", "low3d-models.py")
        r = subprocess.run(["python3", "-m", "py_compile", tool], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def rules(self, script):
        """WYRD's skilling rules are a script of their own in its page: run them in node, with `R` the rules."""
        with open(os.path.join(BOX, "games", "wyrd", "index.html"), encoding="utf-8") as f:
            page = f.read()
        block = re.search(r"<script>\n(/\* WYRD's skilling rules.*?)</script>", page, re.S)
        self.assertTrue(block, "the rules, in a script of their own")
        r = subprocess.run(["node", "-e", "const module = { exports: {} };\n" + block.group(1) + "\nconst R = module.exports, out = {};\n" + script + "\nconsole.log(JSON.stringify(out));"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout), page

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_five_skills_to_75_in_hours(self):
        """The curve: 75 is the top, each level costs more than the last, the six kinds of ore and tree open on the way,
        and a skill takes hours at a steady pace, not days: the gathering ones about three, the ones that use up what
        was gathered less."""
        out, page = self.rules(r"""
out.skills = R.SKILLS; out.max = R.MAX; out.total = R.TOTAL[R.MAX];
out.rising = R.TOTAL.every((v, i) => i < 2 || v > R.TOTAL[i - 1]) && Array.from({ length: 73 }, (_, i) => R.need(i + 2) > R.need(i + 1)).every(Boolean);
out.levels = [R.levelOf(0), R.levelOf(R.TOTAL[2] - 1), R.levelOf(R.TOTAL[2]), R.levelOf(R.TOTAL[75] - 1), R.levelOf(R.TOTAL[75]), R.levelOf(9e9)];
out.into = [R.into(0), R.into(R.TOTAL[40]), R.into(R.TOTAL[75])];
out.tiers = R.TIER_LVL; out.tierFor = [1, 11, 12, 37, 38, 64, 65, 75].map(R.tierFor);
out.hours = {}; for (const k of ["mine", "wood"]) out.hours[k] = R.hours(k) / 3600;
out.hours.smith = R.hours("smith", { walk: 0.1 }) / 3600; out.hours.fire = R.hours("fire", { walk: 0.1 }) / 3600;
out.slow = R.hours("mine", { tool: () => 0, walk: 0.5 }) / 3600;                // never a better pick, and half the time spent walking
// a delver who mines every level's best rock, a swing at a time, by the rules' own chances
let seed = 7; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
let xp = 0, t = 0, ore = [0, 0, 0, 0, 0, 0];
while (R.levelOf(xp) < R.MAX) { const L = R.levelOf(xp), tier = R.tierFor(L); t += R.swing(tier); if (rnd() < R.chance(L, tier)) { xp += R.GATHER_XP[tier]; ore[tier]++; } }
out.played = t / 3600; out.ore = ore;
// all of it smelted and forged: does Smithing keep up (each kind of ore worked needs its level)?
let sx = 0, short = [];
for (let tier = 0; tier < 6; tier++) { if (R.levelOf(sx) < R.TIER_LVL[tier]) short.push(tier); sx += ore[tier] * (R.SMELT_XP[tier] + R.FORGE_XP[tier]); }
out.smithShort = short; out.smithAfter = R.levelOf(sx);
out.chance = [R.chance(1, 0), R.chance(12, 1), R.chance(75, 5), R.chance(75, 0), R.chance(1, 5)];
out.swing = [R.swing(0), R.swing(5)];
""")
        self.assertEqual(out["skills"], ["mine", "smith", "wood", "fire", "summon"])
        self.assertEqual(out["max"], 75)
        self.assertTrue(250000 < out["total"] < 350000, out["total"])
        self.assertTrue(out["rising"])
        self.assertEqual(out["levels"], [1, 1, 2, 74, 75, 75])
        self.assertEqual(out["into"], [0, 0, 1])
        self.assertEqual(out["tiers"], [1, 12, 24, 38, 52, 65])
        self.assertEqual(out["tierFor"], [0, 0, 1, 2, 3, 4, 5, 5])
        for k in ("mine", "wood"):
            self.assertTrue(2 < out["hours"][k] < 4, (k, out["hours"][k]))
        self.assertTrue(0.75 < out["hours"]["smith"] < 2.5, out["hours"])
        self.assertTrue(0.5 < out["hours"]["fire"] < 2, out["hours"])
        self.assertLess(out["slow"], 8)                                    # the slowest way is still an evening or two
        self.assertTrue(1.5 < out["played"] < 3.5, out["played"])         # (no walking in this one)
        self.assertEqual(out["smithShort"], [])                            # Smithing keeps up with what's mined
        self.assertEqual(out["smithAfter"], 75)
        self.assertEqual(out["chance"][0], 0.55)
        self.assertTrue(out["chance"][0] == out["chance"][1] < out["chance"][2] < out["chance"][3] == 0.95 and out["chance"][4] == 0)
        self.assertLess(out["swing"][1], out["swing"][0])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_creatures_and_mastery(self):
        """Summoning's creatures open in order and binding them all, with a pet's share of the other skills, reaches
        75; every one is a model the page has. Mastery gives a mantle and a weapon for each skill, and the weapon keeps
        two under the best that has dropped, growing when a better one does. The names are the game's own."""
        out, page = self.rules(r"""
out.kin = R.KIN.map(c => [c.id, c.kind, c.lvl, c.model]);
out.bonds = R.KIN.reduce((a, c) => a + c.bond, 0); out.kinship = R.KINSHIP * 4 * R.TOTAL[R.MAX]; out.total = R.TOTAL[R.MAX];
// bound in order as soon as each may be, with nothing else learned: how far does each bond carry?
let xp = 0, stuck = []; for (const c of R.KIN) { if (R.levelOf(xp + R.KINSHIP * 4 * R.TOTAL[c.lvl]) < c.lvl) stuck.push(c.id); xp += c.bond; }
out.stuck = stuck;
out.saddles = R.KIN.filter(c => c.kind === "mount").map(c => [c.saddle.tier, c.saddle.smith >= R.TIER_LVL[c.saddle.tier], c.speed > 1]);
out.pets = R.KIN.filter(c => c.kind === "pet").map(c => [c.found, c.help, c[c.help] || 0]);
out.mastery = R.SKILLS.map(k => [k, R.MASTERY[k].mantle, R.MASTERY[k].weapon, R.MASTERY[k].kind, !!R.MASTERY[k].perk]);
const a = R.masteryWeapon("mine", { p: 30, lvl: 14, tier: 3 }), b = R.masteryWeapon("mine", { p: 58, lvl: 25, tier: 5 });
out.under = [30 - a.p, 58 - b.p, a.lvl, b.lvl, a.kind, a.powers.length];
out.better = [R.betterDrop(null, { p: 1, lvl: 1 }), R.betterDrop({ p: 30, lvl: 14 }, { p: 31, lvl: 10 }), R.betterDrop({ p: 30, lvl: 14 }, { p: 30, lvl: 14 }), R.betterDrop({ p: 30, lvl: 14 }, { p: 12, lvl: 40 })];
out.fire = R.FIRE.map(f => f.lvl); out.can = [R.fireCan(14, "Torch"), R.fireCan(15, "Torch"), R.fireCan(75, "Long burning")];
""")
        self.assertEqual(len(out["kin"]), 8)
        self.assertEqual([c[2] for c in out["kin"]], sorted(c[2] for c in out["kin"]))
        self.assertEqual(out["kin"][0][2], 1)                              # the first may be bound at once
        self.assertEqual({c[1] for c in out["kin"]}, {"pet", "mount"})
        models = json.loads(re.search(r"\nconst MODELS = (\{.*?\});\s*/\* maker: end \*/", page, re.S).group(1))
        for c in out["kin"]:
            self.assertIn(c[3], models, c)
        self.assertGreaterEqual(out["bonds"] + out["kinship"], out["total"] * 0.95)    # binding them all, and a pet's share, is the road to 75
        self.assertLess(out["bonds"], out["total"])                        # …and binding alone is not: the other skills feed it
        self.assertEqual(out["stuck"], [])
        for tier, level_ok, faster in out["saddles"]:
            self.assertTrue(level_ok and faster)
        self.assertEqual(sorted({p[1] for p in out["pets"]}), ["carry", "gather", "learn", "light", "quick"])   # carry, gather, speed and more
        self.assertEqual([m[0] for m in out["mastery"]], ["mine", "smith", "wood", "fire", "summon"])
        self.assertEqual(len({m[1] for m in out["mastery"]} | {m[2] for m in out["mastery"]}), 10)             # ten names, all different
        self.assertEqual({m[3] for m in out["mastery"]}, {"blade", "axe", "bow", "staff"})
        self.assertTrue(all(m[4] for m in out["mastery"]))
        self.assertEqual(out["under"], [2, 2, 14, 25, "axe", 3])
        self.assertEqual(out["better"], [True, True, False, False])
        self.assertEqual(out["fire"], sorted(out["fire"]))
        self.assertEqual(out["can"], [False, True, True])
        # an homage, never a copy: none of that game's own words, and never "skillcape"
        script = "".join(re.findall(r"<script>(.*?)</script>", page, re.S)[1:])
        for word in ("runescape", "osrs", "jagex", "gielinor", "skillcape", "skill cape", "max cape", "lumbridge", "varrock", "falador", "mithril", "adamant", "runite",
                     "rune pickaxe", "tinderbox", "bank chest", "grand exchange", "total level", "magic logs", "yew logs", "willow"):
            self.assertNotIn(word, script.lower(), word)


MAKER_MARK = re.compile(r"/\* maker: ([a-z]+)((?: [a-z]+=[A-Za-z_$][\w$]*(?:,[A-Za-z_$][\w$]*)*)*) \*/(.*?)/\* maker: end \*/", re.S)
RIG_JS = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
globalThis.screen = { width: 1920, height: 1080 }; globalThis.innerWidth = 960; globalThis.innerHeight = 540;
eval(require("fs").readFileSync(process.argv[1], "utf8"));
const L3 = window.Low3D, B = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8")), out = {};
const r3 = a => a.map(v => Math.round(v * 1000) / 1000);
"""


class TheBigWorld(unittest.TestCase):
    """Low3D's parts for a world too big to hold at once, and for a moment worth marking: Stream (chunks made as the eye
    nears and given back as it leaves), Mesh.stamp (a thing made once, set down many times), Land.part (one part of the
    land into a mesh), Confetti and Banners (both in the game's own writing)."""

    def node(self, script):
        r = subprocess.run(["node", "-e", RIG_JS.replace(", B = JSON.parse(require(\"fs\").readFileSync(process.argv[2], \"utf8\"))", "") + script + "\nconsole.log(JSON.stringify(out));",
                            os.path.join(BOX, "games", "low3d.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_world_held_a_neighbourhood_at_a_time(self):
        """Walking 400 m across a streamed world: what's held never grows past the neighbourhood, no frame carries more
        than one step of a chunk's making, every chunk opened is closed again, and nothing is made outside the world."""
        out = self.node(r"""
let held = 0, uploads = 0; const g3 = { upload(m) { held++; uploads++; const b = m.bounds(); return { n: m.n, x: b[0], y: b[1], z: b[2], r: b[3] }; }, free(h) { if (h) held--; }, sees: () => true, still() {} };
const land = new L3.Land(600, 240, 0).fill((x, z) => Math.sin(x * 0.05) * 2 + Math.cos(z * 0.07));
const tree = new L3.Mesh(64); L3.Kit.pine(tree, 0, 0, 0, 1, 0x4a3426, 0x2e5a3a);
let opened = 0, closed = 0, outside = 0, lit = 0;
const st = new L3.Stream({ cell: 30, near: 2, open(c) { opened++; if (Math.abs(c.ix) > 10) outside++; c.data = { trees: [[c.x0 + 5, c.z0 + 5], [c.x0 + 20, c.z0 + 12]] }; }, close(c) { closed++; },
  has: (ix, iz) => Math.abs(ix) <= 10 && Math.abs(iz) <= 10,
  build(c, base, glow, step) { if (step === 0) { land.part(base, land.cellOf(c.x0), land.cellOf(c.z0), land.cellOf(c.x1), land.cellOf(c.z1), () => 0x446644); return false; }
    for (const t of c.data.trees) base.stamp(tree, t[0], land.at(t[0], t[1]), t[1], 1.3, 1.2); glow.at(c.x0 + 3, 1, c.z0 + 3); glow.box(0, 0, 0, 1, 1, 1, 0xff00ff); return true; },
  light: { sun: [0.3, 0.8, 0.2], sunCol: 0xffffff, amb: 0x556677, ground: 0x222222 }, sky() { lit++; return 1; }, verts: 300 });
st.fill(g3, 0, 0);
out.filled = [st.list.length, held, opened]; out.tris = st.base.n / 3; out.ready = !st.pending(0, 0);
let maxHeld = 0, maxSteps = 0, x = 0, behind = 0;
for (let i = 0; i < 4000; i++) { x += 0.1; const s0 = st.steps; st.update(g3, x, 0); maxSteps = Math.max(maxSteps, st.steps - s0); maxHeld = Math.max(maxHeld, held); if (!st.at(x, 0) || st.at(x, 0).state !== 4) behind++; }
out.walk = { maxHeld, maxSteps, behind, outside, open: opened - closed, list: st.list.length };
const c = st.at(100, 0), was = c && c.h; st.fill(g3, 100, 0); const u0 = uploads; st.remake(100, 0); const old = st.at(100, 0).h; st.update(g3, 100, 0); out.kept = st.at(100, 0).h === old;   // (its old mesh is drawn while the new one is made)
for (let i = 0; i < 30; i++) st.update(g3, 100, 0); out.remade = [uploads - u0, st.at(100, 0).h !== old];
st.unload(); out.unloaded = [held, st.list.length > 0]; st.fill(g3, 100, 0); out.back = held;
st.free(); out.freed = [st.list.length, held, opened - closed];
""")
        self.assertEqual(out["filled"], [25, 25, 25])                      # five by five round the eye
        self.assertTrue(out["ready"])
        self.assertGreater(out["tris"], 250)
        w = out["walk"]
        self.assertLessEqual(w["maxHeld"], 36)                              # never more than the neighbourhood and its margin
        self.assertEqual(w["maxSteps"], 1)                                  # one step of one chunk's making a frame
        self.assertEqual(w["behind"], 0)                                    # the ground under the walker was always there
        self.assertEqual(w["outside"], 0)
        self.assertLessEqual(w["open"], 49)
        self.assertTrue(out["kept"])
        self.assertEqual(out["remade"], [1, True])
        self.assertEqual(out["unloaded"], [0, True])
        self.assertEqual(out["back"], 25)
        self.assertEqual(out["freed"], [0, 0, 0])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_thing_made_once_and_stamped(self):
        """A stamp is the thing as building it there would have made it (place, turn, size, the way its faces look),
        with what lights itself left alone by a shade; and a mesh emptied keeps its memory."""
        out = self.node(r"""
const a = new L3.Mesh(8); a.tri(1, 2, 0, 0, 2, 1, 0, 3, 0, 0xff8040); a.glow = 127; a.tri(0, 0, 0, 1, 0, 0, 0, 1, 0, 0x204060);
const b = new L3.Mesh(8); b.stamp(a, 10, 0, 10, Math.PI / 2, 2, 2, 0.5);
const m = new L3.Mesh(8); m.at(10, 0, 10, Math.PI / 2, 2); m.tri(1, 2, 0, 0, 2, 1, 0, 3, 0, 0xff8040);
out.same = [0, 1, 2, 5, 6, 7, 10, 11, 12].every(i => Math.abs(m.f[i] - b.f[i]) < 1e-4) && [12, 13, 14].every(i => Math.abs(m.i8[i] - b.i8[i]) <= 1);
out.shaded = [b.u8[16], b.u8[17], b.u8[18]]; out.lit = [b.u8[3 * 20 + 16], b.u8[3 * 20 + 17], b.u8[3 * 20 + 18], b.i8[3 * 20 + 15]];
out.n = b.n; const cap = b.cap; b.reset(); out.reset = [b.n, b.cap === cap, b.lit];
const c = new L3.Mesh(8); c.add(a, true); out.added = [c.n, c.i8[15], c.i8[3 * 20 + 15]];
const land = new L3.Land(40, 16, 0).fill((x, z) => x * 0.1); const p = new L3.Mesh(64); land.part(p, 4, 4, 8, 6, (h, steep) => steep > 0.5 ? 0xff0000 : 0x00ff00);
let x0 = 1e9, x1 = -1e9, z0 = 1e9, z1 = -1e9, up = true; for (let i = 0; i < p.n; i++) { x0 = Math.min(x0, p.f[i * 5]); x1 = Math.max(x1, p.f[i * 5]); z0 = Math.min(z0, p.f[i * 5 + 2]); z1 = Math.max(z1, p.f[i * 5 + 2]); if (p.i8[i * 20 + 13] <= 0) up = false; }
out.part = [p.n / 3, x0, x1, z0, z1, up, land.cellOf(-10), land.cellOf(0)];
""")
        self.assertTrue(out["same"])
        self.assertEqual(out["shaded"], [127, 64, 32])                      # half as bright
        self.assertEqual(out["lit"], [0x20, 0x40, 0x60, 127])               # its own light: as it was
        self.assertEqual(out["n"], 6)
        self.assertEqual(out["reset"], [0, True, 0])
        self.assertEqual(out["added"], [6, 127, 127])
        self.assertEqual(out["part"], [16, -10, 0, -10, -5, True, 4, 8])    # 4 × 2 cells, two triangles each, facing up

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_paper_in_the_air_and_lines_that_stack(self):
        """Confetti: a fixed pool, thrown and let fall, all of it landed in a few seconds, written as turned blocks into
        the game's own writing. Banners: they come in one after another, each said once, stack down the picture and go."""
        out = self.node(r"""
const ui = new L3.UI(); ui.begin(640, 360);
const c = new L3.Confetti(120); c.burst(320, 360, 80, 700, [0xff0000, 0x00ff00], 7, 0.6); c.rain(640, 80, [0x0000ff], 7);
out.pool = [c.max, c.x.length]; let n = c.step(1 / 60, 540), peak = n, steps = 1; c.draw(ui); out.drawn = ui.n; out.block = [ui.q[8], ui.q[9], ui.q[10], ui.q[11]];
while (n && steps < 2000) { n = c.step(1 / 60, 540); peak = Math.max(peak, n); steps++; }
out.peak = peak; out.seconds = steps / 60; ui.begin(640, 360); c.draw(ui); out.after = ui.n;
const said = [], b = new L3.Banners({ on: (i, o) => said.push(i + ":" + o.title) });
b.push({ title: "Mining 75", text: "mastered", col: 0x4ae8ff, hold: 2 }).push({ title: "A mantle", text: "in your bag", hold: 2 }).push({ title: "A weapon", hold: 2 });
out.busy = b.busy; const seen = []; for (let i = 0; i < 60 * 4; i++) { b.step(1 / 60); if (i === 5 || i === 30 || i === 60) { ui.begin(640, 360); b.draw(ui, 640, 360, 1, 0.1); seen.push(ui.n > 0 ? b.list.filter(x => x.t >= 0).length : 0); } }
out.said = said.slice(); out.seen = seen; out.done = b.busy;
ui.begin(640, 360); b.push({ title: "wide enough to read", text: "x" }); b.step(0.5); b.draw(ui, 640, 360, 2, 0.1); let w = 0; for (let i = 0; i < ui.n; i++) w = Math.max(w, ui.q[i * 16 + 2] - ui.q[i * 16]); out.wide = w; out.upper = b.list[0].title;
""")
        self.assertEqual(out["pool"], [120, 120])
        self.assertEqual(out["peak"], 120)                                  # never more than the pool
        self.assertEqual(out["drawn"], 120)
        self.assertEqual(out["block"], [2, 42, 6, 46])                      # the sheet's block: a turned rectangle each
        self.assertTrue(2 < out["seconds"] < 8, out["seconds"])
        self.assertEqual(out["after"], 0)
        self.assertTrue(out["busy"])
        self.assertEqual(out["said"], ["0:MINING 75", "1:A MANTLE", "2:A WEAPON"])
        self.assertEqual(out["seen"], [1, 2, 3])                            # one, then two, then all three stacked
        self.assertFalse(out["done"])
        self.assertGreater(out["wide"], 200)
        self.assertEqual(out["upper"], "WIDE ENOUGH TO READ")

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_what_is_laid_on_the_ground(self):
        """The ground as it's drawn (Land.on) is each cell's own two triangles, where `at` is smooth between the corners
        and lies off them; a shape laid on it (Kit.lay) faces up, sits its lift over the ground at every corner and
        covers the hull of its points; a shadow (Kit.cast) reaches as far as the thing's height throws it."""
        out = self.node(r"""
const land = new L3.Land(40, 16, 0).fill((x, z) => Math.sin(x * 0.7) * 1.5 + Math.cos(z * 0.9 + x * 0.3));
const g = new L3.Mesh(64); land.part(g, 0, 0, 16, 16, () => 0x446644);
let worst = 0, apart = 0;
for (let t = 0; t < g.n; t += 3) { const x = (g.f[t * 5] + g.f[t * 5 + 5] + g.f[t * 5 + 10]) / 3, y = (g.f[t * 5 + 1] + g.f[t * 5 + 6] + g.f[t * 5 + 11]) / 3, z = (g.f[t * 5 + 2] + g.f[t * 5 + 7] + g.f[t * 5 + 12]) / 3;
  worst = Math.max(worst, Math.abs(land.on(x, z) - y)); apart = Math.max(apart, Math.abs(land.at(x, z) - y)); }
out.on = [g.n / 3, worst < 1e-4, apart > 0.02];
const flat = () => 2, m = new L3.Mesh(64);
L3.Kit.lay(m, [0, 0, 4, 0, 4, 4, 0, 4, 2, 2, 1, 3], flat, () => 0x202020, 0.05);
let up = true, onIt = true, area = 0;
for (let t = 0; t < m.n; t += 3) { const p = k => [m.f[(t + k) * 5], m.f[(t + k) * 5 + 1], m.f[(t + k) * 5 + 2]], a = p(0), b = p(1), c = p(2);
  if (m.i8[t * 20 + 13] <= 100) up = false; for (const q of [a, b, c]) if (Math.abs(q[1] - 2.05) > 1e-5) onIt = false;
  area += Math.abs((b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])) / 2; }
out.lay = [m.n / 3, up, onIt, Math.round(area * 100) / 100];
const s = new L3.Mesh(64); L3.Kit.cast(s, [0, 0, 0, 0.1, 0, 0, 0.1, 0.1, 0, 0, 0.1, 0, 0, 0, 2, 0.1, 0, 2, 0.1, 0.1, 2, 0, 0.1, 2], 1.5, 0, flat, () => 0, 0.05);
let x0 = 9, x1 = -9, z1 = -9; for (let v = 0; v < s.n; v++) { x0 = Math.min(x0, s.f[v * 5]); x1 = Math.max(x1, s.f[v * 5]); z1 = Math.max(z1, s.f[v * 5 + 2]); }
out.cast = r3([x0, x1, z1]); out.none = L3.Kit.lay(new L3.Mesh(8), [0, 0, 1, 1], flat, () => 0).n;
const marks = q => [...new Set(Array.from({ length: q.n }, (_, v) => q.u8[v * 20 + 19]))];
s.light({ sun: [0.3, 0.8, 0.2], sunCol: 0xffffff, amb: 0x556677, ground: 0x222222 });
out.marks = [marks(m), marks(s), s.alpha, L3.Mesh.LAID];
""")
        self.assertEqual(out["on"], [512, True, True])                      # 16 by 16 cells, two triangles each; `at` is off them
        self.assertEqual(out["lay"], [12, True, True, 16])                  # the hull is the square: the two points inside it add nothing
        self.assertEqual(out["cast"], [0, 3.1, 0.1])                         # from its foot to where two metres are thrown
        self.assertEqual(out["none"], 0)                                     # two points are no shape
        self.assertEqual(out["marks"], [[255], [252], 255, 252])             # a cast shadow is marked laid, through the light's working; the mesh goes on as it was

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_house_with_a_frame(self):
        """Kit.house: more of it with each step of detail and never more than a Pi can spare, its windows lit into the
        glow mesh, what's worked on it facing south (its north wall plain), its size as it says, and its chimney's end
        where the house was put, turned and sized."""
        out = self.node(r"""
const make = d => { const m = new L3.Mesh(256), g = new L3.Mesh(64), top = L3.Kit.house(m, g, 10, 1, 20, 0, 1, { seed: 4, detail: d }); return [m.n / 3, g.n / 3, r3(top)]; };
out.h = [make(0), make(1), make(2)];
const m = new L3.Mesh(256), g = new L3.Mesh(64); L3.Kit.house(m, g, 0, 0, 0, 0, 1, { seed: 4, detail: 2 });
let north = 0, south = 0, hi = 0, wide = 0, deep = 0;
for (let t = 0; t < m.n; t += 3) { const y = (m.f[t * 5 + 1] + m.f[t * 5 + 6] + m.f[t * 5 + 11]) / 3, z = (m.f[t * 5 + 2] + m.f[t * 5 + 7] + m.f[t * 5 + 12]) / 3; if (y > 0.6 && y < 3.05) { if (z < -2.05 && z > -2.25) north++; if (z > 2.05 && z < 2.4) south++; } }   // (what's on each long wall)
for (let v = 0; v < m.n; v++) { hi = Math.max(hi, m.f[v * 5 + 1]); wide = Math.max(wide, Math.abs(m.f[v * 5])); deep = Math.max(deep, Math.abs(m.f[v * 5 + 2])); }
out.faces = [north, south]; out.size = r3([hi, wide, deep]);
out.turned = r3(L3.Kit.house(new L3.Mesh(256), null, 0, 0, 0, Math.PI / 2, 2, { seed: 4, detail: 0 }));
const k = n => { const q = new L3.Mesh(64); L3.Kit[n](q, 0, 0, 0, 0, 1); return q.n / 3; };
out.yard = [k("barrel"), k("crate"), k("woodpile"), k("bench")];
""")
        t0, t1, t2 = (h[0] for h in out["h"])
        self.assertTrue(100 < t0 < t1 < t2, out["h"])
        self.assertLessEqual(t1, 300)                                       # the house a Pi 3 is given
        self.assertLessEqual(t2, 420)
        self.assertEqual([h[1] for h in out["h"]], [4, 8, 20])              # two windows; two more in its sides; a lantern by the door
        self.assertEqual(out["h"][2][2], [11.35, 7.2, 19.25])               # the chimney's end: where smoke starts
        self.assertEqual(out["faces"][0], 2)                               # the north wall: the wall, and nothing on it
        self.assertGreater(out["faces"][1], 60)                            # the south wall: beams, the door, windows, shutters
        self.assertEqual(out["size"], [6.17, 2.86, 2.86])
        self.assertEqual(out["turned"], [-1.5, 12.4, -2.7])
        self.assertTrue(all(10 < n < 120 for n in out["yard"]), out["yard"])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_houses_built_other_ways(self):
        """Kit.house's walls of logs, of stone and of planks, each within what a Pi can spare and more than the plainest
        house; a house on stilts stands as high again as they are, its posts in the ground and its chimney's end raised."""
        out = self.node(r"""
const make = (o, d) => { const m = new L3.Mesh(256), g = new L3.Mesh(64), top = L3.Kit.house(m, g, 0, 0, 0, 0, 1, Object.assign({ seed: 4, detail: d }, o)); let lo = 9, hi = -9; for (let v = 0; v < m.n; v++) { lo = Math.min(lo, m.f[v * 5 + 1]); hi = Math.max(hi, m.f[v * 5 + 1]); } return [m.n / 3, r3(top), r3([lo, hi])]; };
out.plain = make({}, 0)[0];
out.walls = ["logs", "stone", "planks"].map(k => [make({ walls: k }, 1)[0], make({ walls: k }, 2)[0]]);
out.flat = make({}, 2); out.up = make({ stilts: 1.5, walls: "planks" }, 2);
""")
        for d1, d2 in out["walls"]:
            self.assertTrue(out["plain"] < d1 <= d2 <= 440, out["walls"])
            self.assertLessEqual(d1, 320)                                   # the house a Pi 3 is given
        self.assertAlmostEqual(out["up"][1][1] - out["flat"][1][1], 1.5, places=2)   # the chimney's end, raised with it
        self.assertLess(out["up"][2][0], 0)                                # the posts go into the ground
        self.assertAlmostEqual(out["up"][2][1] - out["flat"][2][1], 1.5, places=2)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_shadows_of_what_moves(self):
        """GL.shadows: the sun's view is a box seen square on (M4.ortho takes its corners to the picture's); the movers are
        kept in a picture of their own, and the still world has a shader that reads it, with and without the wind, that
        never darkens a laid shadow (Mesh.LAID) or a light of its own, and that's only used while there are shadows."""
        out = self.node(r"""
const o = new Float32Array(16); L3.M4.ortho(o, -2, 2, -3, 3, 10, 50);
const at = (x, y, z) => [o[0] * x + o[4] * y + o[8] * z + o[12], o[1] * x + o[5] * y + o[9] * z + o[13], o[2] * x + o[6] * y + o[10] * z + o[14]];
out.corners = [r3(at(-2, -3, -10)), r3(at(2, 3, -50))];
const src = require("fs").readFileSync(process.argv[1], "utf8");
out.parts = ["const CAST_VS", "const CAST_FS", 'stillShade: () => mk(STILL_VS, STILL_FS, "#define SHADE\\n")', 'stillWindShade: () => mk(STILL_VS, STILL_FS, "#define WIND\\n#define SHADE\\n")',
  "step(0.986, aCol.a) * step(aCol.a, 0.99)", "step(0.5, aNor.w)", "  shadows(o) {", "  caster(h, m) {", "  shadowsDone() {", "  ortho(o, l, r, b, t, n, f) {"].map(x => src.includes(x));
out.only = /sh && \(this\.windy \? this\.prog\("stillWindShade"\) : this\.prog\("stillShade"\)\)/.test(src);
""")
        self.assertEqual(out["corners"], [[-1, -1, -1], [1, 1, 1]])
        self.assertTrue(all(out["parts"]), out["parts"])
        self.assertTrue(out["only"])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_what_gives_way_to_the_wind(self):
        """Mesh.sway marks, by height, which vertices the wind moves (in their alpha: 255 stands still), never with the
        value that means "its own light"; a stamp carries the mark and the light's working leaves it; Mesh.facing lights
        a blade the same on both its sides; and the still world has a second shader that moves what's marked, the first
        left as cheap as it was."""
        out = self.node(r"""
const m = new L3.Mesh(16); m.both(0, 0, 0, 0.1, 0.5, 0, 0.05, 1, 0.02, 0x40a040); m.sway(0.1, 0.9, 1);
const al = []; for (let v = 0; v < m.n; v++) al.push([Math.round(m.f[v * 5 + 1] * 100) / 100, m.u8[v * 20 + 19]]);
out.alpha = al.slice(0, 3);
const q = new L3.Mesh(16); q.both(0, 0, 0, 0.1, 0.5, 0, 0.05, 1, 0.02, 0x40a040); q.sway(0, 255, 1); out.never = Array.from({ length: q.n }, (_, v) => q.u8[v * 20 + 19]).some(a => a >= 252 && a <= 254);
const w = new L3.Mesh(16); w.stamp(m, 5, 0, 5, 1, 2, 2, 0.8); out.stamped = [w.u8[19], w.u8[39], w.u8[59]];
w.light({ sun: [0.3, 0.8, 0.2], sunCol: 0xffffff, amb: 0x556677, ground: 0x222222 }); out.lit = [w.u8[19], w.u8[39], w.u8[59]];
const a = new L3.Mesh(16); a.both(0, 0, 0, 0.1, 0.5, 0, 0.05, 1, 0.02, 0x40a040); a.facing(0, 1, 0); a.light({ sun: [0.3, 0.8, 0.2], sunCol: 0xffffff, amb: 0x556677, ground: 0x222222 });
out.sides = [a.u8[16] === a.u8[3 * 20 + 16], a.u8[17] === a.u8[3 * 20 + 17], a.i8[13]];
const src = require("fs").readFileSync(process.argv[1], "utf8");
out.shader = ["#ifdef WIND", "uniform vec3 uWind", "step(aCol.a, 0.986)",'stillWind: () => mk(STILL_VS, STILL_FS, "#define WIND\\n")', "const GRADE_FS", "  grade(o) {", "  wind(t, reach, gusts) {"].map(x => src.includes(x));
out.plain = /still: \(\) => mk\(STILL_VS, STILL_FS, ""\)/.test(src);
""")
        self.assertEqual(out["alpha"], [[0, 255], [0.5, 127], [1, 0]])      # its foot stands, its tip gives most
        self.assertFalse(out["never"])
        self.assertEqual(out["stamped"], [255, 127, 0])
        self.assertEqual(out["lit"], [255, 127, 0])
        self.assertEqual(out["sides"], [True, True, 127])
        self.assertTrue(all(out["shader"]), out["shader"])
        self.assertTrue(out["plain"])

    def test_wyrd_builds_its_village_from_the_kit(self):
        """WYRD's page: Hearthrim's houses are the engine's, shadows are thrown as each chunk is made and laid on the ground
        as it's drawn, and the square is paved."""
        with open(os.path.join(BOX, "games", "wyrd", "index.html"), encoding="utf-8") as f:
            page = f.read()
        for part in ("L3.Kit.house(m, glowM,", "function castShadows(w, d, base, c)", "L3.Kit.cast(base, P, dx, dz, w.on,", "w.on = (x, z) => land.on(x, z)",
                     "function pave(w, c, base, gc)", 'put("woodpile"', "w.cast = [", "g3.wind(t, rich() && w.over ?", "g3.grade(w.over ? AIRNOW.grade : GRADE.under)", "function patches(w, c, base, gc)", "function lava(w, c, glow)", "function yard(w, d)",
                     "d.land ? LANDS[d.land].house : HOUSES[v]", "movers(g3, t, true, CAST); g3.shadowsDone();", "g3.shadows(null)", "const LANDS = [",
                     'd.deco.push({ kind: "grass"', "sm[1] + p * 3.4"):
            self.assertIn(part, page)
        self.assertNotIn("w.h, col", page)                                 # (what's laid goes on the ground as drawn, not the smooth one)


class TheRig(unittest.TestCase):
    """Low3D's Rig (bodies a pose at a time): where a pose puts each joint, the other side's pose, clips by name, things
    held where a joint is; and the blocks WYRD marks for the maker, which make its bodies on their own."""

    def blocks(self, gid):
        with open(os.path.join(BOX, "games", gid, "index.html"), encoding="utf-8") as f:
            page = f.read()
        out = {}
        for kind, attrs, text in MAKER_MARK.findall(page):
            out[kind] = {"text": text, "attrs": dict(kv.split("=", 1) for kv in attrs.split())}
        return out

    def node(self, script, blocks=None):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "blocks.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(blocks or {}, f)
            r = subprocess.run(["node", "-e", RIG_JS + script + "\nconsole.log(JSON.stringify(out));", os.path.join(BOX, "games", "low3d.js"), path],
                               capture_output=True, text=True, timeout=60)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_where_a_pose_puts_the_joints(self):
        out = self.node(r"""
const rig = new L3.Rig(), at = [0, 0, 0], w = j => r3(rig.where(j, at).slice());
rig.pose({}); out.rest = { head: w("head"), handR: w("handR"), handL: w("handL"), footL: w("footL") };
rig.pose({}, 2); out.tall = w("head");
rig.pose({}, 1, 4); out.broad = { handR: w("handR"), footR: w("footR") };
rig.pose({ armR: [Math.PI / 2, 0, 0] }); out.armUp = w("handR");
rig.pose({ chest: [0.5, 0, 0] }); out.leanChest = w("head");
rig.pose({ y: -0.2 }); out.low = w("hips");
const m = new L3.Mesh(); rig.pose({}); rig.at(m, "head"); out.at = r3(Array.from(m.t.slice(9)));
rig.attach(m, "handR", 0, -0.1, 0.05, 0, 0, 0, 2); out.held = r3(Array.from(m.t.slice(9))); out.heldScale = r3([m.t[0], m.t[4], m.t[8]]);
out.joints = [rig.n, rig.joint("footL"), rig.joint(3)];
out.clips = L3.Rig.clips({ a10: {}, a2: {}, a0: {}, roar: {}, b1: {} });
""")
        self.assertEqual(out["joints"], [15, 14, 3])
        self.assertEqual(out["rest"]["head"], [0, 1.57, 0])                   # hips 0.95, chest 0.1 up, head 0.52 up
        self.assertEqual(out["rest"]["handR"], [-0.21, 0.92, 0])              # the right hand on the body's own right (-x)
        self.assertEqual(out["rest"]["handL"], [0.21, 0.92, 0])
        self.assertEqual(out["rest"]["footL"], [0.1, 0.05, 0])
        self.assertEqual(out["tall"], [0, 3.14, 0])                           # a body twice the size
        self.assertEqual(out["broad"]["handR"], [-0.84, 0.92, 0])             # broad: arms set out by bulk,
        self.assertEqual(out["broad"]["footR"], [-0.2, 0.05, 0])              # legs by its square root
        hx, hy, hz = out["armUp"]                                              # swung forward: the arm points ahead (+z)
        self.assertAlmostEqual(hy, 1.49, places=2)
        self.assertAlmostEqual(hz, 0.57, places=2)
        self.assertGreater(out["leanChest"][2], 0.2)                           # the spine swung forward leans the head ahead
        self.assertEqual(out["low"], [0, 0.75, 0])
        self.assertEqual(out["at"], [0, 1.57, 0])
        self.assertEqual(out["held"], [-0.21, 0.82, 0.05])                    # held in the hand's frame
        self.assertEqual(out["heldScale"], [2, 2, 2])
        self.assertEqual(out["clips"], {"a": ["a0", "a2", "a10"], "roar": ["roar"], "b": ["b1"]})

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_wyrds_bodies_from_its_marked_blocks(self):
        """What WYRD marks for the maker runs on its own (only Low3D and the blocks before it): its walk is one step and
        its mirror, every look bakes every pose, and the rig is Low3D's."""
        b = self.blocks("wyrd")
        self.assertEqual(sorted(b), ["bodies", "models", "poses"])
        self.assertEqual(b["bodies"]["attrs"], {"rig": "RIG", "build": "buildBody", "looks": "FOLK,STYLES"})
        out = self.node(r"""
const a = B.bodies.attrs, f = new Function("L3", B.models.text + B.poses.text + B.bodies.text +
  "\nreturn { POSES, build: " + a.build + ", rig: " + a.rig + ", looks: [" + a.looks + "] };"), G = f(L3), P = G.POSES, rig = G.rig;
const eq = (x, y) => JSON.stringify(x) === JSON.stringify(y);
out.rig = rig instanceof L3.Rig && rig.n;
out.mirror = [eq(rig.mirror(P.walk0), P.walk2), eq(rig.mirror(P.walk1), P.walk3), eq(rig.mirror(P.walk2), P.walk0)];
out.twice = Object.keys(P).filter(k => !eq(rig.mirror(rig.mirror(P[k])), P[k]));
out.clips = L3.Rig.clips(P);
let looks = 0, built = 0, empty = [];
for (const group of G.looks) for (const k of Object.keys(group)) { looks++;
  for (const p of Object.keys(P)) { const m = new L3.Mesh(2048); G.build(m, group[k], p, 1); built++; if (m.n < 300) empty.push(k + "/" + p); } }
out.looks = looks; out.built = built; out.empty = empty; out.poses = Object.keys(P).length;
""", b)
        self.assertEqual(out["rig"], 15)
        self.assertEqual(out["mirror"], [True, True, True])                   # walk2 is walk0 the other way round
        self.assertEqual(out["twice"], [])                                     # mirrored twice: the pose it was
        self.assertEqual(out["clips"]["walk"], ["walk0", "walk1", "walk2", "walk3"])
        self.assertEqual(out["clips"]["swing"], ["swing0", "swing1", "swing2"])
        self.assertEqual(out["poses"], 26)
        self.assertEqual(out["looks"], 17)                                     # six of Hearthrim's folk, ten of the deep's, the Thorn King
        self.assertEqual(out["built"], 17 * 26)
        self.assertEqual(out["empty"], [])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_wyrds_bodies_built_once_move_to_every_pose(self):
        """Every look WYRD marks, built once (Rig.bind) and moved to each pose, stands where the body baked for that
        pose stands: the moves between poses start from the same bodies."""
        b = self.blocks("wyrd")
        out = self.node(r"""
const a = B.bodies.attrs, f = new Function("L3", B.models.text + B.poses.text + B.bodies.text +
  "\nreturn { POSES, build: " + a.build + ", rig: " + a.rig + ", looks: [" + a.looks + "] };"), G = f(L3), P = G.POSES, rig = G.rig;
let far = 0, turned = 0, checked = 0, counts = []; const bow = { foreL: [1.35, 0, 0], armL: [0.2, 0.1, 0] };
for (const group of G.looks) for (const k of Object.keys(group)) { const look = group[k]; if (look.mantle || look.relic) continue;
  const skin = rig.bind(m => G.build(m, look, "idle0", 1), 2048);
  for (const p of Object.keys(P)) {
    const baked = new L3.Mesh(2048); G.build(baked, look, p, 1);
    const pose = look.weapon === "bow" && /^(idle|walk)/.test(p) ? Object.assign({}, P[p], bow) : P[p];
    rig.pose(pose, 1, look.bulk || 1); skin.pose(); checked++;
    if (baked.n !== skin.n) { counts.push(k + "/" + p); continue; }
    for (let v = 0; v < baked.n; v++) { for (let i = 0; i < 3; i++) far = Math.max(far, Math.abs(baked.f[v * 5 + i] - skin.mesh.f[v * 5 + i]));
      for (let i = 12; i < 15; i++) turned = Math.max(turned, Math.abs(baked.i8[v * 20 + i] - skin.mesh.i8[v * 20 + i])); } } }
out.far = far; out.turned = turned; out.checked = checked; out.counts = counts;
""", b)
        self.assertEqual(out["counts"], [])                                    # (the same parts in every pose)
        self.assertGreater(out["checked"], 300)
        self.assertLess(out["far"], 1e-3)
        self.assertLessEqual(out["turned"], 2)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_every_skill_has_an_emblem_of_its_own_on_its_mantle(self):
        """WYRD's five skills each have an emblem (Low3D's Emblem: one shape for a mesh, the HUD and a menu), no two
        alike, every piece inside the square and none bent inwards. A mantle built for a skill carries that emblem in
        every look; the HUD, a banner and a slot of the bag draw the same pieces."""
        b = self.blocks("wyrd")
        out = self.node(r"""
const a = B.bodies.attrs, f = new Function("L3", B.models.text + B.poses.text + B.bodies.text +
  "\nreturn { EMBLEMS, build: " + a.build + ", looks: [" + a.looks + "] };"), G = f(L3), E = G.EMBLEMS;
const all = e => Array.from(e.a).concat(Array.from(e.b));
out.keys = Object.keys(E); out.kind = out.keys.every(k => E[k] instanceof L3.Emblem);
out.unique = new Set(out.keys.map(k => all(E[k]).map(v => Math.round(v * 100)).join(","))).size;
out.inside = out.keys.every(k => all(E[k]).every(v => v >= -1.001 && v <= 1.001));
out.fills = out.keys.map(k => { let x0 = 9, x1 = -9, y0 = 9, y1 = -9; const q = all(E[k]); for (let i = 0; i < q.length; i += 2) { x0 = Math.min(x0, q[i]); x1 = Math.max(x1, q[i]); y0 = Math.min(y0, q[i + 1]); y1 = Math.max(y1, q[i + 1]); } return Math.min(x1 - x0, y1 - y0) > 1.3; });
const three = (q, o) => q[o + 6] === q[o + 4] && q[o + 7] === q[o + 5];
const oneWay = q => { for (let o = 0; o < q.length; o += 8) { const n = three(q, o) ? 3 : 4; let pos = 0, neg = 0;
  for (let i = 0; i < n; i++) { const A = o + i * 2, Bb = o + ((i + 1) % n) * 2, C = o + ((i + 2) % n) * 2, z = (q[Bb] - q[A]) * (q[C + 1] - q[Bb + 1]) - (q[Bb + 1] - q[A + 1]) * (q[C] - q[Bb]); if (z > 1e-6) pos++; else if (z < -1e-6) neg++; }
  if (pos && neg) return false; } return true; };
out.oneWay = out.keys.every(k => oneWay(E[k].a) && oneWay(E[k].b));
const pieces = e => (e.a.length + e.b.length) / 8, tris = e => { let n = 0; for (const q of [e.a, e.b]) for (let o = 0; o < q.length; o += 8) n += three(q, o) ? 1 : 2; return n; };
// on the mantle: so many more triangles with it than without, in each look (a shard's is read from both sides)
const base = G.looks[0][Object.keys(G.looks[0])[0]];
const count = (look, mark, pose) => { const m = new L3.Mesh(4096); G.build(m, Object.assign({}, base, { mantle: { look, col: 0x39ff88, mark } }), pose, 1); return m.n / 3; };
out.sewn = ["signal", "shard", "pyre"].map(look => out.keys.map(k => (count(look, k, "idle0") - count(look, null, "idle0")) / tris(E[k])));
out.running = out.keys.map(k => (count("signal", k, "walk1") - count("signal", null, "walk1")) / tris(E[k]));
// on the HUD: a piece a quad, round the point it's drawn at; in a banner; as a picture in a slot of the bag
const ui = new L3.UI(); ui.begin(320, 180);
out.hud = out.keys.map(k => { const n0 = ui.n; E[k].draw(ui, 100, 60, 10, 0xff0000, 1); let ok = true; for (let i = n0; i < ui.n; i++) for (let j = 0; j < 8; j += 2) { const x = ui.q[i * 16 + j], y = ui.q[i * 16 + j + 1]; if (x < 89.9 || x > 110.1 || y < 49.9 || y > 70.1) ok = false; } return ok && ui.n - n0 === pieces(E[k]); });
const lines = em => { const bn = new L3.Banners(); bn.push({ title: "Mining 75", text: "mastered", col: 0x4ae8ff, emblem: em }); bn.step(1); ui.begin(960, 540); bn.draw(ui, 960, 540, 2); return ui.n; };
out.banner = lines(E.mine) - lines(null) === pieces(E.mine);
const svg = E.fire.svg(0xff2e88); out.svg = [svg.startsWith('<svg class="emblem"'), (svg.match(/<path /g) || []).length, svg.includes("#ff2e88"), !/NaN|undefined/.test(svg)];
const slot = new L3.Slots({ show: () => ({ title: "A mantle", kind: "mantle", col: 0xb06cff, emblem: E.summon }) }).cell({}, 0, null);
out.slot = slot.includes('<svg class="emblem"') && slot.includes("#b06cff");
""", b)
        self.assertEqual(out["keys"], ["mine", "smith", "wood", "fire", "summon"])
        self.assertTrue(out["kind"] and out["inside"] and out["oneWay"])
        self.assertEqual(out["unique"], 5)                                     # no two alike
        self.assertEqual(out["fills"], [True] * 5)                             # each fills its square: it reads small
        self.assertEqual(out["sewn"], [[1] * 5, [2] * 5, [1] * 5])             # signal, shard (both sides), pyre
        self.assertEqual(out["running"], [1] * 5)
        self.assertEqual(out["hud"], [True] * 5)
        self.assertTrue(out["banner"] and out["slot"])
        self.assertEqual(out["svg"], [True, 2, True, True])
        with open(os.path.join(BOX, "games", "wyrd", "index.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("mark: g.mantle.m", page)                               # the mantle worn is built with its skill's emblem
        self.assertIn("emblem: EMBLEMS[k]", page)                             # …and the level-75 banner shows it
        self.assertIn("${EMBLEMS[k].svg(sk.col)}<b>", page)                   # …and each line of the Skills screen

    def test_only_lights_glow(self):
        """Where a game asks for a glow round its lights (GL.bloom), what's merely lit is held under where the glow
        begins (GL.hold): sunlit skin, pale stone and leaves stay out of it. WYRD asks for both together."""
        with open(os.path.join(BOX, "games", "low3d.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("vCol = mix(min(lit, vec3(uCap)), c, max(uTint.a, aNor.w));", js)             # things that move
        self.assertIn("vCol = mix(min(aCol.rgb * uShine, vec3(uCap)), aCol.rgb, aNor.w);", js)      # the still world
        self.assertIn("if (u.uCap) gl.uniform1f(u.uCap, this.held || 8);", js)                      # not held unless asked: as it was
        self.assertRegex(js, r"\n  hold\(k\) \{")
        with open(os.path.join(BOX, "games", "wyrd", "index.html"), encoding="utf-8") as f:
            page = f.read()
        m = re.search(r"const BLOOM = \{ hold: ([\d.]+), from: ([\d.]+), to: ([\d.]+),", page)
        self.assertTrue(m)
        hold, start, full = (float(x) for x in m.groups())
        self.assertLessEqual(hold, start)
        self.assertLess(start, full)
        self.assertLess(page.index("g3.hold(glowOn ? BLOOM.hold : 0);"), page.index("if (glowOn) g3.bloom(BLOOM);"))

    def test_the_maker_is_offline_and_not_on_home(self):
        """The maker's page (games/maker/): for a computer with a mouse, not a game on Home; it reads the games' own
        pages beside it and nothing from anywhere else."""
        with open(os.path.join(BOX, "games", "maker", "index.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertNotIn("maker", [g["id"] for g in CATALOG["games"]])
        self.assertIn('src="../low3d.js"', page)
        self.assertNotRegex(page, r"""(src|href|url)\s*[=(]\s*["']?(https?:)?//""")
        for online in ("XMLHttpRequest", "WebSocket", "@import", "<link"):
            self.assertNotIn(online, page)
        self.assertEqual(sorted(re.findall(r'fetch\("([^"]+)"', page)), ["../", "../games.json"])     # the list, and a game's page beside it
        self.assertIn('fetch("../" + encodeURIComponent(id) + "/index.html")', page)
        self.assertIn(MAKER_MARK.pattern.replace("(.*?)", "([\\s\\S]*?)").replace("/", "\\/"), page)   # the same marks the tests read


class Agent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.bin = os.path.join(cls.dir, "bin")
        os.makedirs(cls.bin)
        cls.played = os.path.join(cls.dir, "played")
        helper = os.path.join(cls.dir, "helper")                     # apt, standing in: "installs" a game's program
        script(helper, 'set -e\nprog=$(python3 -c "import json,sys; print(next(g for g in json.load(open(\'%s\'))[\'native\'] '
                       'if g[\'id\']==sys.argv[1])[\'run\'][0])" "$2")\n'
                       'if [ "$1" = install ]; then printf \'#!/bin/sh\\necho "$@" > %s\\ntrap "exit 0" TERM\\nwhile :; do sleep 0.1; done\\n\' '
                       '> "%s/$prog"; chmod +x "%s/$prog"; else rm -f "%s/$prog"; fi\n'
                       % (os.path.join(BOX, "games", "games.json"), cls.played, cls.bin, cls.bin, cls.bin))
        os.environ.update(SOFA_BOX_GAMES_BIN=cls.bin, SOFA_BOX_GAMES_HELPER=helper, SOFA_BOX_GAME_FILE=os.path.join(cls.dir, "game.json"),
                          SOFA_BOX_GAME_DATA=os.path.join(cls.dir, "data"), XDG_CONFIG_HOME=os.path.join(cls.dir, "config"))
        cls.agent = load("sofa-box-agent", "sofa_box_agent_games")
        cls.toasts = []
        cls.agent.toast = cls.toasts.append
        cls.agent.go = lambda where: None

    @classmethod
    def tearDownClass(cls):
        cls.agent.games.stop("tests")
        for k in ("SOFA_BOX_GAMES_BIN", "SOFA_BOX_GAMES_HELPER", "SOFA_BOX_GAME_FILE", "SOFA_BOX_GAME_DATA", "XDG_CONFIG_HOME"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def wait_job(self):
        for _ in range(100):
            job = self.agent.games.listing()["job"]
            if job and job["state"] != "working":
                return job
            time.sleep(0.05)
        self.fail("the install didn't finish")

    def wait(self, check):
        for _ in range(100):
            if check():
                return True
            time.sleep(0.05)
        return False

    def test_install_play_and_leave(self):
        games = self.agent.games
        listing = games.listing()
        self.assertEqual(len(listing["native"]), len(CATALOG["native"]))
        self.assertFalse(any(g["installed"] for g in listing["native"]))
        with self.assertRaises(ValueError):
            games.change("nethack; rm -rf /", "install")
        with self.assertRaises(ValueError):
            games.play("supertux")                                    # not on the box yet

        games.change("supertux", "install")
        self.assertEqual(self.wait_job()["state"], "done")
        self.assertIn("SuperTux is ready: it's in Games.", self.toasts)
        self.assertTrue(next(g for g in games.listing()["native"] if g["id"] == "supertux")["installed"])

        os.remove(self.played) if os.path.exists(self.played) else None   # (an earlier game's, if it got to say)
        games.play("supertux")                                        # the game reads the controller itself
        self.assertTrue(self.wait(lambda: os.path.exists(self.played)))
        with open(self.played) as f:
            self.assertEqual(f.read().strip(), "--fullscreen")
        with open(os.environ["SOFA_BOX_GAME_FILE"]) as f:
            self.assertEqual(json.load(f), {"id": "supertux", "controls": None})
        self.assertEqual(games.listing()["playing"], "supertux")
        self.agent.go_home()                                          # Home held: the game ends
        self.assertTrue(self.wait(lambda: games.playing is None))
        self.assertTrue(self.wait(lambda: not os.path.exists(os.environ["SOFA_BOX_GAME_FILE"])))

        games.change("supertux", "remove")
        self.assertEqual(self.wait_job()["state"], "done")
        self.assertFalse(next(g for g in games.listing()["native"] if g["id"] == "supertux")["installed"])

    def test_luanti_starts_in_its_world_with_the_box_working_the_controller(self):
        games = self.agent.games
        games.change("luanti", "install")
        self.assertEqual(self.wait_job()["state"], "done")
        os.remove(self.played) if os.path.exists(self.played) else None
        games.play("luanti")
        self.assertTrue(self.wait(lambda: os.path.exists(self.played)))
        with open(self.played) as f:
            args = f.read().split()
        self.assertIn("--go", args)
        world = os.path.join(os.environ["SOFA_BOX_GAME_DATA"], "luanti", "worlds", "Sofa")   # (split at the space)
        self.assertTrue(args[args.index("--world") + 1].startswith(world))
        with open(os.path.join(os.environ["SOFA_BOX_GAME_DATA"], "luanti", "worlds", "Sofa Box", "world.mt")) as f:
            self.assertIn("gameid = minetest", f.read())
        with open(os.environ["SOFA_BOX_GAME_FILE"]) as f:
            self.assertEqual(json.load(f)["controls"], CONTROLS["luanti"])
        games.stop("tests")
        self.assertTrue(self.wait(lambda: games.playing is None))

    def test_a_blank_world_is_mended(self):
        """A crash had left Sofa Craft's world without its game ("Game [] could not be found" at every start after)."""
        games = self.agent.games
        games.change("luanti", "install")
        self.assertEqual(self.wait_job()["state"], "done")
        mt = os.path.join(os.environ["SOFA_BOX_GAME_DATA"], "luanti", "worlds", "Sofa Box", "world.mt")
        os.makedirs(os.path.dirname(mt), exist_ok=True)
        with open(mt, "w") as f:
            f.write("gameid = \nbackend = leveldb\nworld_name = Mine\n")
        games.play("luanti")
        games.stop("tests")
        self.assertTrue(self.wait(lambda: games.playing is None))
        with open(mt) as f:
            text = f.read()
        self.assertIn("gameid = minetest", text)
        self.assertIn("backend = leveldb", text)                          # (its storage stays what it is)
        self.assertIn("world_name = Mine", text)
        self.assertIn("mod_storage_backend = sqlite3", text)
        with open(os.path.join(os.environ["SOFA_BOX_GAME_DATA"], "last-game.log")) as f:
            self.assertIn(", Sofa Craft", f.read())                       # each start marked in the games' log
        games.change("luanti", "remove")
        self.assertEqual(self.wait_job()["state"], "done")

    def test_the_shooters_full_screen_at_the_boards_size(self):
        """AssaultCube and Sauerbraten start through XWayland (its mouse turns them without end), full screen at a
        size the board holds (1024×576 and 1280×720 on a Pi 3, the TV scaling it up; 1080p on a Pi 5), the stick
        turning as fast at any size. Sauerbraten's look for the board is set once, its other settings the player's."""
        games, real, home = self.agent.games, self.agent.board, os.environ.get("HOME")
        os.environ["HOME"] = os.path.join(self.dir, "home")
        os.makedirs(os.environ["HOME"], exist_ok=True)
        data = os.path.join(self.dir, "lib", "games", "assaultcube", "packages")

        def play(gid, gen):
            self.agent.board = lambda: dict(real(), gen=gen, tv_height=1080)
            prog = os.path.join(self.bin, gid)                      # (says what it was started with)
            script(prog, 'echo "$SDL_VIDEODRIVER $@" > %s\ntrap "exit 0" TERM\nwhile :; do sleep 0.1; done\n' % self.played)
            os.remove(self.played) if os.path.exists(self.played) else None
            games.play(gid)
            self.assertTrue(self.wait(lambda: os.path.exists(self.played)))
            with open(self.played) as f:
                said = f.read().split()
            with open(os.environ["SOFA_BOX_GAME_FILE"]) as f:
                speed = json.load(f)["controls"]["mouse_speed"]
            games.stop("tests")
            self.assertTrue(self.wait(lambda: games.playing is None))
            return said, speed

        try:
            games.change("sauerbraten", "install")
            self.assertEqual(self.wait_job()["state"], "done")
            sauer = os.path.join(os.environ["HOME"], ".sauerbraten")
            os.makedirs(sauer)
            with open(os.path.join(sauer, "autoexec.cfg"), "w") as f:
                f.write("bind F9 screenshot\n")                       # (the player's own: kept)
            self.assertEqual(play("sauerbraten", 3), (["x11", "-t1", "-w1024", "-h576"], 3750))
            with open(os.path.join(sauer, "sofa-box.cfg")) as f:
                cfg = f.read()
            self.assertIn("if (=s (getalias sofabox_look) light) [] [", cfg)
            self.assertIn("texreduce 1;", cfg)
            self.assertIn("bind MOUSE2 [zoom 1; onrelease [zoom -1]]", cfg)
            self.assertEqual(cfg.count("["), cfg.count("]"))
            self.assertEqual(play("sauerbraten", 5), (["x11", "-t1", "-w1920", "-h1080"], 2000))
            with open(os.path.join(sauer, "sofa-box.cfg")) as f:
                self.assertIn("(getalias sofabox_look) full) [] [\n  texreduce 0;", f.read())
            with open(os.path.join(sauer, "autoexec.cfg")) as f:
                self.assertEqual(f.read(), "exec sofa-box.cfg\nbind F9 screenshot\n")

            games.change("assaultcube", "install")                   # its maps didn't come: not a game yet
            self.assertEqual(self.wait_job()["state"], "failed")
            self.assertFalse(next(g for g in games.listing()["native"] if g["id"] == "assaultcube")["installed"])
            os.makedirs(data)
            self.assertTrue(next(g for g in games.listing()["native"] if g["id"] == "assaultcube")["installed"])
            init = os.path.join(os.environ["HOME"], ".assaultcube", "config", "init.cfg")
            os.makedirs(os.path.dirname(init))
            with open(init, "w") as f:
                f.write("// automatically written on exit, DO NOT MODIFY\nfullscreen 1\nfullscreendesktop 1\nscr_w 1920\naudio 1\n")
            self.assertEqual(play("assaultcube", 3), (["x11", "-t1", "-w1280", "-h720"], 3000))
            with open(init) as f:
                self.assertEqual(f.read(), "// automatically written on exit, DO NOT MODIFY\nfullscreen 1\nfullscreendesktop 0\n"
                                           "scr_w 1920\naudio 1\n")
            self.assertEqual(play("assaultcube", 5), (["x11", "-t1"], 2000))   # the TV's own size
            with open(init) as f:
                self.assertIn("\nfullscreendesktop 1\n", f.read())
        finally:
            self.agent.board = real
            os.environ["HOME"] = home
            for gid in ("sauerbraten", "assaultcube"):
                games.change(gid, "remove")
                self.wait_job()
            shutil.rmtree(os.path.join(self.dir, "lib"), ignore_errors=True)

    def test_room_and_board(self):
        games = self.agent.games
        real = self.agent.board
        self.agent.board = lambda: dict(real(), gen=3)
        try:
            kart = next(g for g in games.listing()["native"] if g["id"] == "supertuxkart")
            self.assertFalse(kart["fits"])
            with self.assertRaises(ValueError) as e:
                games.change("supertuxkart", "install")
            self.assertIn("Raspberry Pi 4", str(e.exception))
        finally:
            self.agent.board = real

    def test_controllers_heard(self):
        games = self.agent.games
        self.assertEqual(games.heard_pads([{"name": "Xbox Wireless Controller", "kind": "xbox"}]), {"Xbox Wireless Controller"})
        self.assertEqual(games.heard_pads([{"name": "Xbox Wireless Controller", "kind": "xbox"}]), set())   # (said once)
        self.assertEqual(games.listing()["pads"], [{"name": "Xbox Wireless Controller", "kind": "xbox"}])
        games.heard_pads([{"name": "x", "kind": "<script>"}])
        self.assertEqual(games.listing()["pads"][0]["kind"], "generic")

    def test_sleep_and_wake(self):
        """The phone's power button: the box rests on its screensaver; Home (any remote's) wakes it."""
        went, real = [], self.agent.go
        self.agent.go = went.append
        try:
            self.agent.box_sleep()
            self.assertTrue(self.agent.asleep["on"])
            self.assertEqual(went[-1], "#/sleep")
            self.assertTrue(self.agent.go_home())                     # Home while asleep: awake, on Home
            self.assertFalse(self.agent.asleep["on"])
            self.assertEqual(went[-1], "#/")
            self.assertFalse(self.agent.box_wake())                   # (awake already: nothing)
        finally:
            self.agent.go = real

    def test_why_an_install_failed(self):
        self.assertIn("internet", self.agent._apt_why("Err:1 http://deb.debian.org trixie InRelease\n  Temporary failure resolving 'deb.debian.org'"))
        self.assertIn("room", self.agent._apt_why("E: You don't have enough free space in /var/cache/apt/archives/. No space left"))
        self.assertEqual(self.agent._apt_why("E: Unable to locate package flare-game"), "Unable to locate package flare-game")
        self.assertIn("internet", self.agent._apt_why("Downloading game data…\nwget: unable to resolve host address 'github.com'\n"
                                                      "E: Sub-process /usr/bin/dpkg returned an error code (1)"))
        self.assertIn("didn't check out", self.agent._apt_why("Hash mismatch AssaultCube_v1.3.0.2.tar.bz2: expected 9b31…\n"
                                                              "E: Sub-process /usr/bin/dpkg returned an error code (1)"))


class RootHelper(unittest.TestCase):
    """`sofa-box games install <id>`: only the packages the box's own list names, whatever it's asked."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(BOX, "sofa-box")) as f:
            body = f.read().replace("LIB=/usr/local/lib/sofa-box", "LIB=%s" % BOX, 1)
        self.helper = os.path.join(self.dir, "sofa-box")
        with open(self.helper, "w") as f:
            f.write(body)
        os.makedirs(os.path.join(self.dir, "bin"))
        self.log = os.path.join(self.dir, "apt.log")
        script(os.path.join(self.dir, "bin", "apt-get"), 'echo "$@" >> %s\n' % self.log)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_helper(self, *args):
        env = dict(os.environ, PATH=os.path.join(self.dir, "bin") + os.pathsep + os.environ["PATH"])
        return subprocess.run(["sh", self.helper, "games"] + list(args), env=env, capture_output=True, text=True, timeout=30)

    def apt(self):
        try:
            with open(self.log) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def test_its_packages_only(self):
        self.assertEqual(self.run_helper("install", "openttd").returncode, 0)
        self.assertIn("install -y --no-install-recommends openttd openttd-opengfx openttd-opensfx openttd-openmsx", self.apt())
        self.assertEqual(self.run_helper("install", "sauerbraten").returncode, 0)     # (its downloaded 1 GB not kept)
        self.assertIn("-o APT::Keep-Downloaded-Packages=false install -y --no-install-recommends sauerbraten\n", self.apt())
        self.assertEqual(self.run_helper("remove", "openttd").returncode, 0)
        self.assertIn("remove -y --autoremove openttd openttd-opengfx", self.apt())
        before = self.apt()
        for bad in (("install", "supertux; touch /tmp/x"), ("install", "../../etc"), ("install", ""), ("purge", "openttd")):
            self.assertNotEqual(self.run_helper(*bad).returncode, 0, bad)
        self.assertEqual(self.apt(), before)                         # apt never asked


class GameMode(unittest.TestCase):
    """A controller in a game, the same on every controller."""
    RANGES = {0: (-32768, 32767), 1: (-32768, 32767), 3: (-32768, 32767), 4: (-32768, 32767), 2: (0, 255), 5: (0, 255)}

    def test_buttons_by_their_places(self):
        xbox = pads.GameMap(CONTROLS["luanti"], "Xbox Wireless Controller", self.RANGES)
        ps = pads.GameMap(CONTROLS["luanti"], "DualSense Wireless Controller", self.RANGES)
        self.assertEqual(xbox.feed(1, 304, 1), [("key", "KEY_SPACE", 1)])          # A: jump
        self.assertEqual(xbox.feed(1, 304, 2), [])                                 # (held)
        self.assertEqual(xbox.feed(1, 304, 0), [("key", "KEY_SPACE", 0)])
        self.assertEqual(xbox.feed(1, 307, 1), [("key", "KEY_Q", 1)])              # Xbox's X, on the left
        self.assertEqual(ps.feed(1, 308, 1), [("key", "KEY_Q", 1)])                # PlayStation's □, on the left
        self.assertEqual(ps.feed(1, 307, 1), [("key", "KEY_I", 1)])                # △, on top
        self.assertEqual(xbox.feed(3, 5, 250), [("btn", "BTN_LEFT", 1)])           # RT: dig
        self.assertEqual(xbox.feed(3, 5, 100), [])                                 # (let go a little: still down)
        self.assertEqual(xbox.feed(3, 5, 10), [("btn", "BTN_LEFT", 0)])
        self.assertEqual(xbox.feed(1, 310, 1), [("rel", "REL_WHEEL", 1)])          # LB: the next item
        self.assertEqual(xbox.feed(1, 310, 0), [])
        self.assertEqual(xbox.feed(1, 316, 1), [])                                 # Home: the daemon's (held: leave)

    def test_two_keys_at_once(self):
        m = pads.GameMap(CONTROLS["wesnoth"], "Xbox Wireless Controller", self.RANGES)
        self.assertEqual(m.feed(1, 308, 1), [("key", "KEY_LEFTCTRL", 1), ("key", "KEY_E", 1)])   # Y: end the turn
        self.assertEqual(m.feed(1, 308, 0), [("key", "KEY_E", 0), ("key", "KEY_LEFTCTRL", 0)])

    def test_sticks_as_keys_and_as_a_mouse(self):
        m = pads.GameMap(CONTROLS["luanti"], "Xbox Wireless Controller", self.RANGES)
        self.assertEqual(m.feed(3, 1, -30000), [("key", "KEY_W", 1)])              # forward
        self.assertEqual(m.feed(3, 1, -13000), [])                                 # (0.4: still forward)
        self.assertEqual(m.feed(3, 0, 30000), [("key", "KEY_D", 1)])
        self.assertEqual(sorted(m.feed(3, 1, 0)), [("key", "KEY_W", 0)])
        m.feed(3, 3, 32767)                                                        # right stick, all the way right
        self.assertEqual(m.tick(10.0), [])                                         # (the first tick only starts the clock)
        moved = m.tick(10.05)
        self.assertEqual(moved[0][:2], ("rel", "REL_X"))
        self.assertAlmostEqual(moved[0][2], 45, delta=2)                           # 900 a second, for 0.05 s
        m.feed(3, 3, 1000)                                                         # (in the middle: still)
        self.assertEqual(m.tick(10.1), [])
        self.assertEqual(sorted(m.release()), [("key", "KEY_D", 0)])

    def test_a_shooter(self):
        sauer = pads.GameMap(dict(CONTROLS["sauerbraten"], mouse_speed=3750), "Xbox Wireless Controller", self.RANGES)
        self.assertEqual(sauer.feed(3, 2, 250), [("btn", "BTN_RIGHT", 1)])        # LT: zoom while it's held
        self.assertEqual(sauer.feed(3, 2, 0), [("btn", "BTN_RIGHT", 0)])
        self.assertEqual(sauer.feed(1, 307, 1), [("btn", "BTN_MIDDLE", 1)])       # X: the next weapon
        self.assertEqual(sauer.feed(1, 311, 1), [("rel", "REL_WHEEL", -1)])       # RB: so is the wheel
        sauer.feed(3, 3, 32767)
        sauer.tick(20.0)
        self.assertAlmostEqual(sauer.tick(20.05)[0][2], 187, delta=3)              # (as fast drawn at 576 lines)
        ac = pads.GameMap(CONTROLS["assaultcube"], "DualSense Wireless Controller", self.RANGES)
        self.assertEqual(ac.feed(1, 308, 1), [("key", "KEY_R", 1)])               # □: reload
        self.assertEqual(ac.feed(1, 310, 1), [("key", "KEY_G", 1)])               # L1: a grenade
        self.assertEqual(ac.feed(1, 317, 1), [("key", "KEY_LEFTSHIFT", 1)])       # L3: crouch
        self.assertEqual(ac.feed(3, 1, -30000), [("key", "KEY_W", 1)])            # forward

    def test_the_d_pad(self):
        m = pads.GameMap(CONTROLS["neverball"], "Wireless Controller", self.RANGES)
        self.assertEqual(m.feed(3, 16, -1), [("key", "KEY_LEFT", 1)])             # the hat
        self.assertEqual(m.feed(3, 16, 0), [("key", "KEY_LEFT", 0)])
        self.assertEqual(m.feed(1, 545, 1), [("key", "KEY_DOWN", 1)])             # or D-pad buttons
        self.assertEqual(m.feed(1, 545, 0), [("key", "KEY_DOWN", 0)])

    def test_which_controller(self):
        for name, kind in (("Xbox Wireless Controller", "xbox"), ("Microsoft X-Box 360 pad", "xbox"),
                           ("Wireless Controller", "playstation"), ("DualSense Wireless Controller", "playstation"),
                           ("8BitDo Pro 2", "8bitdo"), ("Pro Controller", "nintendo"), ("USB Gamepad", "generic")):
            self.assertEqual(pads.pad_kind(name), kind, name)
        self.assertTrue(pads.is_generic([288, 289, 290, 291, 297], {0: (0, 255), 1: (0, 255)}))
        self.assertFalse(pads.is_generic([304, 305, 288], {0: (0, 255)}))
        self.assertFalse(pads.is_generic([272, 273], {}))                          # a mouse
        self.assertEqual(pads.GENERIC[290], 304)                                   # its button 3, at the bottom: OK

    def test_the_game_file(self):
        real = pads.GAME_FILE
        pads.GAME_FILE = os.path.join(tempfile.mkdtemp(), "game.json")
        try:
            self.assertIsNone(pads.read_game())
            with open(pads.GAME_FILE, "w") as f:
                json.dump({"id": "neverball", "controls": CONTROLS["neverball"]}, f)
            self.assertEqual(pads.read_game()["id"], "neverball")
        finally:
            shutil.rmtree(os.path.dirname(pads.GAME_FILE), ignore_errors=True)
            pads.GAME_FILE = real



MAKER_TEXT_JS = """
globalThis.window = globalThis;
const fs = require("fs"), html = fs.readFileSync(process.argv[1], "utf8");
const at = html.indexOf("/* The maker's hold on a game's page"), from = html.lastIndexOf("<script>", at) + 8, to = html.indexOf("</" + "script>", at);
eval(html.slice(from, to));
const T = window.MakerText, A = JSON.parse(fs.readFileSync(process.argv[2], "utf8")), out = {};
const read = f => fs.readFileSync(f, "utf8");
"""


class TheMaker(unittest.TestCase):
    """The maker's setup and saving (games/maker/): a game's page goes back exactly as it was but for the blocks the
    maker changed, new blocks go into the game's own script, the profile and camera blocks say what the setup was told,
    the two starting pages are pages for the engines beside them, and the box only shows and tests games."""
    GAMES = os.path.join(BOX, "games")

    def node(self, script, args=None):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "args.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(args or {}, f)
            r = subprocess.run(["node", "-e", MAKER_TEXT_JS + script + "\nconsole.log(JSON.stringify(out));",
                                os.path.join(self.GAMES, "maker", "index.html"), path], capture_output=True, text=True, timeout=60)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def parses(self, page, name):
        tmp = tempfile.mkdtemp()
        try:
            for i, body in enumerate(re.findall(r"<script>(.*?)</script>", page, re.S)):
                path = os.path.join(tmp, "%s_%d.js" % (name, i))
                with open(path, "w", encoding="utf-8") as f:
                    f.write(body)
                r = subprocess.run(["node", "--check", path], capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, name + "\n" + r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_a_page_goes_back_as_it_was(self):
        """Every game's page, put back with no change or with each block's own text, is the same to the byte; a change
        to WYRD's poses changes nothing outside the poses block."""
        pages = {g["id"]: os.path.join(self.GAMES, g["id"], "index.html") for g in CATALOG["games"]}
        out = self.node(r"""
out.same = {}; out.marked = {};
for (const id of Object.keys(A.pages)) {
  const p = read(A.pages[id]), b = T.blocks(p);
  let ok = T.splice(p, {}) === p;
  for (const k of Object.keys(b)) ok = ok && T.splice(p, { [k]: b[k].text }) === p;
  out.same[id] = ok; out.marked[id] = Object.keys(b);
}
const p = read(A.pages.wyrd), b = T.blocks(p), was = b.poses.text, now = was.replace(/\bwalk0: \{ /, "walk0: { lean: 0.1, ");
const q = T.splice(p, { poses: now });
out.edit = [now !== was, q.slice(0, b.poses.start) === p.slice(0, b.poses.start), q.slice(q.length - (p.length - b.poses.end)) === p.slice(b.poses.end), q.length - p.length];
""", {"pages": pages})
        self.assertEqual([gid for gid, ok in out["same"].items() if not ok], [])
        self.assertEqual(sorted(out["marked"]["wyrd"]), ["bodies", "models", "poses"])
        self.assertEqual(out["edit"], [True, True, True, len("lean: 0.1, ")])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_new_blocks_go_into_the_games_own_script(self):
        """The profile and camera blocks a page doesn't have yet go after "use strict" in its own script, in every game on
        the box's list; the page still parses, the blocks give back what went in, and saving them again changes nothing.
        A page that already has a PROFILE or CAMERA of its own isn't given a second one."""
        pages = {g["id"]: os.path.join(self.GAMES, g["id"], "index.html") for g in CATALOG["games"]}
        out = self.node(r"""
const P = { type: "rpg3d", look: "flat", players: 2, fps: 30, floor: "pi3", ceiling: "computer", controls: ["pad", "touch"], targets: ["web"], languages: ["en", "ja"], bench: { secs: 15 } };
const C = { way: "follow" };
out.pages = {}; out.back = {};
for (const id of Object.keys(A.pages)) {
  const p = read(A.pages[id]), q = T.splice(p, { profile: T.profileText(P), camera: T.cameraText(C) }), b = T.blocks(q);
  const own = q.lastIndexOf("<script>"), strict = q.indexOf('"use strict";', own), at = q.indexOf("/* maker: profile */");
  out.back[id] = [JSON.stringify(T.value(b.profile.text, "PROFILE")) === JSON.stringify(P), JSON.stringify(T.value(b.camera.text, "CAMERA")) === JSON.stringify(C),
    at > own && (strict < 0 || at > strict), T.splice(q, { profile: T.profileText(P), camera: T.cameraText(C) }) === q, q.length > p.length];
  out.pages[id] = q;
}
const own = read(A.pages.tidewing).replace('"use strict";', '"use strict";\nconst CAMERA = { mine: true };');
try { T.splice(own, { camera: T.cameraText(C) }); out.second = "made"; } catch (e) { out.second = e.message; }
""", {"pages": pages})
        self.assertIn("already has a CAMERA of its own", out["second"])
        for gid, checks in out["back"].items():
            self.assertEqual(checks, [True] * 5, gid)
            self.parses(out["pages"][gid], gid)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_starting_pages(self):
        """A new game starts from one of two pages: Low3D's, or Low2D's on top of it, each loading the engines beside it
        in order, with nothing from the network, its name written safely, and the setup's blocks in its own script."""
        out = self.node(r"""
const P = { type: "platformer", look: "pixel", players: 1, fps: 60, floor: "pi3", ceiling: "pi5", controls: ["pad", "keys"], targets: ["web", "box"], languages: ["en"] };
out.p3 = T.page3d({ id: "my-game", name: "My <Game> \"*/", profile: Object.assign({}, P, { type: "rpg3d", look: "flat" }), camera: { way: "follow" } });
out.p2 = T.page2d({ id: "my-game", name: "My Game", profile: P, camera: { way: "flat" } });
out.v = [out.p3, out.p2].map(p => { const b = T.blocks(p); return [T.value(b.profile.text, "PROFILE").type, T.value(b.camera.text, "CAMERA").way]; });
""")
        for name, page, srcs in (("p3", out["p3"], ["../pad.js", "../low3d.js"]), ("p2", out["p2"], ["../pad.js", "../low3d.js", "../low2d.js"])):
            self.assertTrue(page.startswith("<!doctype html>"), name)
            self.assertEqual(re.findall(r'<script src="([^"]+)"></script>', page), srcs, name)
            self.assertEqual(page.count("<script"), page.count("</script>"), name)
            self.assertNotRegex(page, r"""(src|href|url)\s*[=(]\s*["']?(https?:)?//""")
            for online in ("fetch(", "XMLHttpRequest", "WebSocket", "<link"):
                self.assertNotIn(online, page)
            self.parses(page, name)
        self.assertIn("<title>My &lt;Game&gt; &quot;*/</title>", out["p3"])            # the name, written safely
        self.assertIn('"use strict";\n/* maker: profile */', out["p3"])
        self.assertEqual(out["v"], [["rpg3d", "follow"], ["platformer", "flat"]])
        self.assertIn("L3.game({", out["p3"])
        self.assertIn("L2.game({", out["p2"])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_kit_screen_lists_the_engines_kit(self):
        """The kit screen's list is the engine's Kit: everything it builds into a mesh is on it (what isn't a thing to
        stand in a scene is named as left out), each makes triangles from the engine as it is, the ones with details
        make more the higher, and the line it gives a game calls the Kit by name."""
        script = """
const noop = () => {};
globalThis.window = globalThis; globalThis.addEventListener = noop; globalThis.location = { hash: "" };
globalThis.document = { hidden: false, createElement: () => ({ getContext: () => null }) };
globalThis.screen = { width: 1920, height: 1080 }; globalThis.innerWidth = 960; globalThis.innerHeight = 540;
const fs = require("fs"), html = fs.readFileSync(process.argv[1], "utf8");
eval(fs.readFileSync(process.argv[2], "utf8"));
const at = html.indexOf("/* The kit's list"), from = html.lastIndexOf("<script>", at) + 8, to = html.indexOf("</" + "script>", at);
eval(html.slice(from, to));
const L3 = window.Low3D, KIT = window.MakerKit, out = { things: [], tab: html.includes('data-screen="kit"') && html.includes('id="screen-kit"') };
const used = new Set(KIT.others);
for (const t of KIT) {
  const tris = [];
  for (const d of t.details || [1]) { const m = new L3.Mesh(64), g = new L3.Mesh(16); t.make(L3, m, g, { seed: 2, detail: d }); tris.push(m.n / 3); }
  const code = t.code({ seed: 2, detail: 1 }), fn = /L3\.Kit\.([A-Za-z]+)\(/.exec(code);
  if (fn) used.add(fn[1]);
  out.things.push({ id: t.id, group: t.group, about: !!t.about, tris, fn: fn ? fn[1] : null, known: !!(fn && typeof L3.Kit[fn[1]] === "function") });
}
out.missing = Object.keys(L3.Kit).filter(k => !used.has(k));
out.gone = KIT.others.filter(k => !(k in L3.Kit));
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, os.path.join(self.GAMES, "maker", "index.html"), os.path.join(self.GAMES, "low3d.js")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["tab"])
        self.assertEqual(out["missing"], [])                             # a new Kit part goes on the list, or is named as left out
        self.assertEqual(out["gone"], [])
        ids = [t["id"] for t in out["things"]]
        self.assertEqual(len(ids), len(set(ids)))
        for t in out["things"]:
            self.assertTrue(t["known"] and t["about"] and t["group"], t["id"])
            self.assertTrue(all(n > 0 for n in t["tris"]), t["id"])
            self.assertEqual(t["tris"], sorted(t["tris"]), t["id"])      # a higher detail never has fewer triangles

    def test_the_box_only_shows_and_tests(self):
        """A page the box serves (/box/…) never writes a file: no folder, no page from the computer, no saving. Only a
        Pi 3's budget is given, the one that's been measured."""
        out = self.node(r"""
out.writes = ["/box/games/maker/", "/maker/", "/games/maker/", "/play/maker/"].map(p => T.writes({ pathname: p }));
out.budgets = Object.keys(T.BUDGETS);
out.pi3 = T.BUDGETS.pi3;
""")
        self.assertEqual(out["writes"], [False, True, True, True])
        self.assertEqual(out["budgets"], ["pi3"])
        self.assertEqual(out["pi3"], {"draws": 30, "tris": 15000, "garbage": 300})
        with open(os.path.join(self.GAMES, "maker", "index.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("onBox: !T.writes(location)", page)
        self.assertIn('Maker.saves = () => !Maker.onBox && Maker.source !== "box";', page)   # what's read from the box is only read:
        self.assertIn('if (text == null || !Maker.saves()) delete Maker.changes[kind]', page)  # nothing there counts as unsaved,
        self.assertIn("if (!Maker.saves()) return say(", page)                                 # nothing there saves,
        self.assertIn('$("src-folder").hidden = Maker.onBox || !window.showDirectoryPicker', page)  # and no folder on the box
        self.assertIn('$("src-file").hidden = Maker.onBox', page)
        self.assertIn('$("src-folder").onclick = () => openFolder();', page)                 # (a dialog opens from a click)
        self.assertIn('if (Maker.onBox || Maker.source !== "folder") throw', page)           # a new game: only into a folder
        self.assertIn("if (now !== Maker.page) return say(", page)                             # never over a change made elsewhere


if __name__ == "__main__":
    unittest.main()
