"""Games on a Sofa Box: the open-source games it installs from its list (only those packages, through its root
helper), opens over the home screen and ends with Home held; and the controller daemon's game mode (every
controller the same in each game: keys and a mouse by the buttons' places)."""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
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
        for online in ("fetch(", "XMLHttpRequest", "WebSocket", "<link", "@import", "<script src"):
            self.assertNotIn(online, html)                             # Gloamwell plays offline
        self.assertIn("navigator.getGamepads", html)                   # with a controller,
        self.assertNotRegex(html, r"buttons\[16\]")                    # never Home, which is the box's


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
        probe = self.read("probe", "index.html")                         # the graphics check: for the owner, not on Home
        self.assertNotIn("probe", [g["id"] for g in CATALOG["games"]])
        self.assertIn("../low3d.js", probe)
        self.assertNotRegex(probe, r"""(src|href|url)\s*[=(]\s*["']?(https?:)?//""")
        self.assertEqual(__import__("re").findall(r"fetch\(\"([^\"]+)\"", probe), ["/box/api/info"])   # it asks the box only

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_pages_parse(self):
        """Every page game's own script, the engine, pad.js and the graphics check: no syntax slips."""
        import re
        tmp = tempfile.mkdtemp()
        try:
            pages = [os.path.join(g["id"], "index.html") for g in CATALOG["games"]] + [os.path.join("probe", "index.html")]
            files = [os.path.join(self.GAMES, "low3d.js"), os.path.join(self.GAMES, "pad.js")]
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
  software: pick(box("software"), { cpu: 30 }), none: pick(box("none"), { cpu: 150 }), desktop: pick(box("desktop"), { draws: 1024, fill: 64, cpu: 5 })
};
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
        self.assertEqual(p["pi3"], "gl 1/3")                             # a Pi 3's GPU: small and steady
        self.assertEqual(p["pi3slow"], "gl 0/3")
        self.assertEqual(p["pi4"], "gl 3/5")
        self.assertEqual(p["pi5"], "gl 5/6")
        self.assertTrue(p["software"].startswith("flat "))               # no real GPU: the 2D renderer
        self.assertTrue(p["none"].startswith("flat "))
        self.assertTrue(p["desktop"].startswith("gl 6"))
        steady, late, busy, busy_fps = out["gov"]
        self.assertEqual(steady, 6)                                      # room to spare: up a rung (no further: it stays a while)
        self.assertLess(late, steady)                                    # late frames: down
        self.assertEqual(busy_fps, 30)                                   # the game's own work fills a frame: 30 a second
        self.assertEqual(out["mesh"], [12, 12])
        self.assertEqual(out["path"], [4, 100, 100, 420])


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


if __name__ == "__main__":
    unittest.main()
