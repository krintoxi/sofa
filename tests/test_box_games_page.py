"""Sofa Box OS: the Games page as a store, and what a game's card says.

On a Pi 3 B+ (1.1.73) the owner called the Games page outdated: a grey bar across the top, flat grey cards with a small
icon and two lines of text, the hints drawn over them. It's a store now, in Spotlight's way: behind it, the game the
remote is on (its photograph, playing itself, or for a game from Debian its icon on its colour), its name, a line about
it, who plays and with what; rows below like a console's store (Continue, New, Two or more players, the box's own, from
Debian, more to get, controllers). A row's pictures are small copies, loaded when they come near the screen; on a Pi 3
a press still draws only the ring.

1.1.97 (the owner: "games section looks meh"): the pictures are taken again from the games themselves by a tool
(tools/game-art.mjs: no title screens, no old scenes), each with a square face for a small tile; the box's own games
are shelved by kind; a card says the game's kind, 2D or 3D, who plays and with what, and where it was left, read from
the game's own save by games/shelf.js (the same file Sofa's list in a browser uses); and the page has three looks."""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest

from tests.test_box_speed import BOX, Page, chrome, free_port, get

with open(os.path.join(BOX, "games", "games.json"), encoding="utf-8") as f:
    CATALOG = json.load(f)
ART = os.path.join(BOX, "home", "art", "games")


def jpeg_size(path):
    """(width, height) of a JPEG, from its first frame header."""
    with open(path, "rb") as f:
        data = f.read()
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        kind, n = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if kind in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + n
    raise ValueError(path)


class Pieces(unittest.TestCase):
    def test_every_game_says_who_plays_and_when_it_came(self):
        for g in CATALOG["games"] + CATALOG["native"]:
            self.assertIn(g.get("players"), (1, 2, 3, 4), g["id"])
            self.assertRegex(g.get("added", ""), r"^20\d\d-\d\d-\d\d$", g["id"])
        two = sorted(g["id"] for g in CATALOG["games"] if g["players"] >= 2)
        for gid in two:                                    # (what a game says of itself agrees)
            about = next(g["about"] for g in CATALOG["games"] if g["id"] == gid)
            self.assertTrue(re.search(r"one or two|one to four|two players|player or two|split screen", about) or gid == "gloamwell", gid)
        with open(os.path.join(BOX, "sofa-box-agent.py"), encoding="utf-8") as f:
            agent = f.read()
        self.assertIn('"mb", "pi", "players", "added")', agent)   # the box passes them on for the games from Debian

    def test_every_photograph_has_a_small_copy_for_the_rows(self):
        """A row's tile is about 13 rem wide: on a 1080p TV at twice the page's size, a 640 x 360 picture. The full
        1280 x 720 is only the one behind the page (a Pi 3 keeps every picture it decodes in memory a while)."""
        big = sorted(f for f in os.listdir(ART) if f.endswith(".jpg"))
        self.assertEqual(big, sorted(os.listdir(os.path.join(ART, "small"))))
        self.assertEqual(big, sorted(os.listdir(os.path.join(ART, "icon"))))
        for f in big:
            self.assertEqual(jpeg_size(os.path.join(ART, "small", f)), (640, 360), f)
            self.assertLess(os.path.getsize(os.path.join(ART, "small", f)), os.path.getsize(os.path.join(ART, f)), f)

    def test_the_page_is_its_own_code(self):
        with open(os.path.join(BOX, "home", "home.js"), encoding="utf-8") as f:
            js = f.read()
        with open(os.path.join(BOX, "home", "home.css"), encoding="utf-8") as f:
            css = f.read()
        page = js[js.index("function viewGames()"):js.index("function gameShelf(el)")]
        self.assertNotIn("grid games", page)              # the flat grey cards are gone
        self.assertIn('loading="lazy"', js[js.index("function gpTile("):js.index("function viewGames()")])
        self.assertIn("/box/home/art/games/small/", js)
        self.assertIn('if (el.closest(".gp")) return gameShelf(el);', js)
        # on a Pi 3 the picture behind stands still (a screen-sized layer moving is a frame's work)
        self.assertIn('html:not(.lite)[data-page="games"] .spt-layer.on img { animation: gp-drift', css)
        self.assertIn(".gp .spt-rows { bottom: 2.9rem; }", css)   # the rows end above the hints


def literal(text, at):
    """The { ... } that starts at or after `at` in a page's script, whole (braces matched, strings and comments passed over)."""
    i = text.index("{", at)
    depth, j, quote = 0, i, ""
    while j < len(text):
        c = text[j]
        if quote:
            if c == "\\":
                j += 1
            elif c == quote:
                quote = ""
        elif c in "\"'`":
            quote = c
        elif text.startswith("//", j):
            j = text.index("\n", j)
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if not depth:
                return text[i:j + 1]
        j += 1
    raise ValueError("no end")


class TheCards(unittest.TestCase):
    """What a card says is true of the game: taken from its page, not from memory."""

    @classmethod
    def setUpClass(cls):
        cls.pages = {}
        for g in CATALOG["games"]:
            with open(os.path.join(BOX, "games", g["id"], "index.html"), encoding="utf-8") as f:
                cls.pages[g["id"]] = f.read()

    def test_every_game_has_its_facts(self):
        kinds = ["adventure", "action", "racing", "mind", "arcade"]
        with open(os.path.join(BOX, "games", "shelf.js"), encoding="utf-8") as f:
            shelf = f.read()
        self.assertEqual(re.findall(r'\["([a-z]+)", "[^"]+"\]', shelf[shelf.index("const KINDS"):shelf.index("const WITH")]), kinds)
        for g in CATALOG["games"]:
            self.assertIn(g.get("shelf"), kinds, g["id"])
            self.assertTrue(g.get("kind") and len(g["kind"]) <= 16, g["id"])
            self.assertTrue(g.get("line") and len(g["line"]) <= 48 and g["line"].endswith("."), g["id"])   # a card's one line
            self.assertEqual(g["with"][:3], ["controller", "keys", "touch"], g["id"])
        for kind in kinds:
            self.assertGreaterEqual(sum(g["shelf"] == kind for g in CATALOG["games"]), 2, kind)    # no shelf of one
        self.assertIn(CATALOG["featured"], [g["id"] for g in CATALOG["games"]])
        with open(os.path.join(BOX, "sofa-box-agent.py"), encoding="utf-8") as f:
            self.assertIn('"featured": self.catalog().get("featured")', f.read())                 # the box passes it on

    def test_2d_or_3d_is_the_engine_the_page_loads(self):
        for g in CATALOG["games"]:
            scripts = re.findall(r'<script src="\.\./([a-z0-9]+\.js)"', self.pages[g["id"]])
            self.assertEqual(g["dim"], "3D" if "low3d.js" in scripts and "low2d.js" not in scripts else "2D", g["id"])

    def test_played_with_is_what_the_page_reads(self):
        """Controller: the page reads one. Keys: it listens for them. Touch: it declares a layout (pad.js). The TV's
        remote (arrows, OK and Back, nothing else): only a game whose layout asks for no more than A and B."""
        for g in CATALOG["games"]:
            page = self.pages[g["id"]]
            self.assertTrue("../pad.js" in page or "getGamepads" in page, g["id"])
            self.assertTrue("keydown" in page or "low2d.js" in page or "low3d.js" in page, g["id"])
            m = re.search(r"SofaPad\.touch\.layout\((\{.*?\})\);?\s*\n", page, re.S)
            self.assertTrue(m, g["id"])
            r = subprocess.run(["node", "-e", "console.log(JSON.stringify(%s))" % m.group(1)], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            lay = json.loads(r.stdout)
            simple = bool(lay.get("none")) or all(b in ("a", "b") for b, _ in lay.get("buttons", []) + lay.get("top", []))
            self.assertEqual("remote" in g["with"], simple, g["id"])

    def test_where_a_game_was_left_is_read_from_what_the_game_keeps(self):
        """Each game's own fresh save, taken from its page: never played says nothing; a step on, set in that same
        save, says where. A game that renames what it keeps fails here."""
        P, fresh = self.pages, {}
        for gid in ("cinder-knight", "shadow-heist", "micro-drifters", "neon-brawler", "void-drifter", "cosmic-cascade"):
            fresh[gid] = literal(P[gid], P[gid].index('L2.Store("%s", () => (' % gid))
        fresh["rune-tactics"] = literal(P["rune-tactics"], P["rune-tactics"].index("const fresh = () => ("))
        self.assertIn('new L2.Store("rune-tactics", fresh)', P["rune-tactics"])
        for gid, fn in (("tidewing", "function fresh() { return "), ("ironmaw", "function fresh() { return "), ("wyrd", "function freshSave() { return "),
                        ("halogen", "function fresh() { return ")):
            fresh[gid] = literal(P[gid], P[gid].index(fn) + len(fn) - 1)
            self.assertIn('const SAVE = "%s";' % gid, P[gid])
        slot = literal(P["cinder-knight"], P["cinder-knight"].index("function freshSlot() {\n  return ") + 24)
        camp = literal(P["rune-tactics"], P["rune-tactics"].index("const newCamp = () => ("))
        self.assertRegex(P["wyrd"], r"const d = \{ name, look, kind, level: 1,")               # a delver: a name and a level
        self.assertIn("save.slots[slotNo] = d; save.last = slotNo; store();", P["wyrd"])
        self.assertRegex(P["gloamwell"], r"const s = \{ v: 2, cls: P\.cls, lvl: P\.lvl, xp: P\.xp, gold: P\.gold, deepest: P\.deepest,")
        self.assertIn('SLOTKEY = i => "gloamwell-slot-" + i', P["gloamwell"])
        for gid, key in (("neon-dodge", "neonDodgeHi"), ("sky-hop", "skyHopHi"), ("pair-up", "pairBest")):
            self.assertIn('localStorage.setItem("%s"' % key, P[gid])
        # the ends a line counts towards are the game's own
        self.assertIn("SAVE.reached = Math.max(SAVE.reached, L.hi + 1)", P["shadow-heist"])
        self.assertIn("if (B.node === 14) { SAVE.wins.campaigns++;", P["rune-tactics"])
        self.assertIn("for (let i = 0; i < 60; i++) if (puzzleOpen(i)", P["cosmic-cascade"])
        self.assertIn('SAVE.deepest >= 4 ? "ALL THE WAY" : "ZONE " + Math.max(1, SAVE.deepest + (SAVE.runs ? 1 : 0))', P["void-drifter"])
        for gid, words in (("shadow-heist", "twelve heists"), ("rune-tactics", "fifteen-battle"), ("neon-brawler", "five stages"),
                           ("cosmic-cascade", "sixty puzzle boards"), ("tidewing", "twelve courses"), ("ironmaw", "nine levels"), ("halogen", "six races")):
            self.assertIn(words, next(g["about"] for g in CATALOG["games"] if g["id"] == gid))
        js = """
const S = require(process.argv[1]), F = {%s}, slot = () => (%s), camp = () => (%s), out = {};
const store = {}, get = k => (k in store ? store[k] : null), put = (k, v) => { store[k] = typeof v === "string" ? v : JSON.stringify(v); };
const say = id => { const w = S.where(id, get); return w ? [w.line, w.pct == null ? null : w.pct] : null; };
for (const id in F) put(id, F[id]());
out.fresh = Object.fromEntries(S.saved.map(id => [id, say(id)]));
const step = (id, f) => { const s = F[id](); f(s); put(id, s); return say(id); };
out.wyrd = step("wyrd", s => { s.slots[1] = { name: "Wren", look: {}, kind: "blade", level: 12 }; s.slots[2] = { name: "Ash", look: {}, kind: "bow", level: 30 }; s.last = 1; });
out.wyrdFar = step("wyrd", s => { s.slots[1] = { name: "Wren", level: 12 }; s.slots[2] = { name: "Ash", level: 30 }; });      // (none being played: the one furthest on)
out.cinder = step("cinder-knight", s => { s.slots[0] = slot(); s.slots[0].reached = 3; s.slot = 0; });
out.cinderDone = step("cinder-knight", s => { s.slots[2] = slot(); s.slots[2].done = true; s.slot = 2; });
out.heist = step("shadow-heist", s => { s.reached = 4; s.heists = 9; });
out.heistAll = step("shadow-heist", s => { s.reached = 12; });
out.rune = step("rune-tactics", s => { s.camp = camp(); s.camp.done = { 0: 1, 1: 1, 2: 1 }; });
out.runeBegun = step("rune-tactics", s => { s.camp = camp(); });
out.runeWon = step("rune-tactics", s => { s.wins.campaigns = 1; });
out.micro = step("micro-drifters", s => { s.cups.city = { easy: 3 }; s.cups.snow = { easy: 1 }; s.races = 9; });
out.microRaces = step("micro-drifters", s => { s.races = 1; });
out.brawler = step("neon-brawler", s => { s.reached = 2; s.best = 400; });
out.brawlerBest = step("neon-brawler", s => { s.best = 400; });
out.voidRun = step("void-drifter", s => { s.runs = 3; s.deepest = 1; });
out.voidAll = step("void-drifter", s => { s.runs = 9; s.deepest = 4; });
out.cascade = step("cosmic-cascade", s => { for (let i = 0; i < 15; i++) s.solved[i] = 1; });
out.cascadeBest = step("cosmic-cascade", s => { s.endless.score = 1240; });
out.tide = step("tidewing", s => { s.open = 6; s.cups.tide = 1; });
out.iron = step("ironmaw", s => { s.reached = 4; });
out.halogen = step("halogen", s => { s.best["ring-zero"] = { place: 2, time: 61.4 }; s.best["hill-drop"] = { place: 1, time: 74.0 }; });
put("gloamwell-slot-0", { v: 2, cls: 0, lvl: 3, deepest: 2 }); put("gloamwell-slot-2", { v: 2, cls: 1, lvl: 9, deepest: 6 });
out.gloam = say("gloamwell");
put("neonDodgeHi", "412"); put("skyHopHi", "88"); put("pairBest", "11");
out.small = [say("neon-dodge"), say("sky-hop"), say("pair-up")];
put("wyrd", "{not json"); put("tidewing", "[1,2]"); put("ironmaw", JSON.stringify({ reached: "far" }));
out.broken = [say("wyrd"), say("tidewing"), say("ironmaw"), say("no-such-game"), say("constructor")];
out.saved = S.saved;
console.log(JSON.stringify(out));
""" % (", ".join('"%s": () => (%s)' % (k, v) for k, v in fresh.items()), slot, camp)
        r = subprocess.run(["node", "-e", js, os.path.join(BOX, "games", "shelf.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(sorted(out["saved"]), sorted(g["id"] for g in CATALOG["games"]))      # a reader for every game
        self.assertEqual(out["fresh"], {g["id"]: None for g in CATALOG["games"]})              # never played: nothing said
        self.assertEqual(out["wyrd"], ["Wren, level 12", None])
        self.assertEqual(out["halogen"], ["2 of 6 races run", 33])
        self.assertEqual(out["wyrdFar"], ["Ash, level 30", None])
        self.assertEqual(out["cinder"], ["Stage 4", None])
        self.assertEqual(out["cinderDone"], ["Finished", 100])
        self.assertEqual(out["heist"], ["4 of 12 heists pulled", 33])
        self.assertEqual(out["heistAll"], ["All 12 heists pulled", 100])
        self.assertEqual(out["rune"], ["3 of 15 battles won", 20])
        self.assertEqual(out["runeBegun"], ["Campaign begun", 0])
        self.assertEqual(out["runeWon"], ["Campaign won", 100])
        self.assertEqual(out["micro"], ["2 cups with a medal", None])
        self.assertEqual(out["microRaces"], ["1 race run", None])
        self.assertEqual(out["brawler"], ["Stage 3 of 5", 40])
        self.assertEqual(out["brawlerBest"], ["Best: 400", None])
        self.assertEqual(out["voidRun"], ["Zone 2 reached", None])
        self.assertEqual(out["voidAll"], ["All the way through", 100])
        self.assertEqual(out["cascade"], ["15 of 60 boards solved", 25])
        self.assertEqual(out["cascadeBest"], ["Best: 1240", None])
        self.assertEqual(out["tide"], ["6 of 12 courses open", 50])
        self.assertEqual(out["iron"], ["Level 4 of 9", 33])
        self.assertEqual(out["gloam"], ["Level 9, down to floor 6", None])                      # the hero furthest on
        self.assertEqual(out["small"], [["Best: 412", None], ["Best: 88", None], ["Best: 11 turns", None]])
        self.assertEqual(out["broken"], [None, None, None, None, None])                         # a save that isn't one: as good as none

    def test_the_pictures_are_taken_from_the_games(self):
        """tools/game-art.mjs opens each game and photographs it at the moment its recipe says: a recipe and three
        pictures a game (the one behind the page, a row's small copy, a square face for a small tile)."""
        tools = os.path.join(os.path.dirname(os.path.dirname(BOX)), "tools")
        with open(os.path.join(tools, "game-art.json"), encoding="utf-8") as f:
            recipes = json.load(f)
        ids = [g["id"] for g in CATALOG["games"]]
        self.assertEqual([k for k in recipes if k != "about"], ids)
        for gid in ids:
            self.assertEqual(jpeg_size(os.path.join(ART, gid + ".jpg")), (1280, 720), gid)
            self.assertEqual(jpeg_size(os.path.join(ART, "icon", gid + ".jpg")), (256, 256), gid)
            self.assertLess(os.path.getsize(os.path.join(ART, gid + ".jpg")), 200 * 1024, gid)      # (a Pi 3 decodes it as the remote rests)
            self.assertLess(os.path.getsize(os.path.join(ART, "icon", gid + ".jpg")), 24 * 1024, gid)
            self.assertNotRegex(json.dumps(recipes[gid]), r"https?:|fetch\(|import\(", gid)        # nothing from outside
        r = subprocess.run(["node", os.path.join(tools, "game-art.mjs"), "--check"], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(BOX, "home", "home.js"), encoding="utf-8") as f:
            js = f.read()
        listed = re.search(r"const GAME_ART = new Set\(\[(.*?)\]\)", js, re.S).group(1)
        self.assertEqual(sorted(re.findall(r'"([a-z-]+)"', listed)), sorted(ids))                  # Home knows which have one

    def test_home_puts_the_games_in_an_order_worth_seeing(self):
        """Home's row used to open on the three smallest games (the list's own order). Now: what was played last, the
        featured one, then the newest; the row's pictures are the small copies, and Classic's tiles show a face."""
        with open(os.path.join(BOX, "home", "home.js"), encoding="utf-8") as f:
            js = f.read()
        fn = js[js.index("function gamesInOrder() {"):js.index("function gpPoster(g)")]
        r = subprocess.run(["node", "-e", """
let recent = [];
const games = { featured: "c", games: [{ id: "a", added: "2026-01-01" }, { id: "b", added: "2026-03-01" }, { id: "c", added: "2026-02-01" }, { id: "d", added: "2026-04-01" }] };
const recentGames = () => recent;
%s
const out = [gamesInOrder().map(g => g.id).join("")];
recent = [{ id: "a" }, { id: "gone" }, null]; out.push(gamesInOrder().map(g => g.id).join(""));
console.log(JSON.stringify(out));""" % fn], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["cdba", "acdb"])
        spot = js[js.index("function viewSpotlight()"):js.index("function shelfOf(el)")]
        self.assertIn('gamesInOrder().map(g => GAME_ART.has(g.id) ? sptArt(`data-game="${esc(g.id)}"`, "/box/home/art/games/small/"', spot)
        self.assertNotIn('"/box/home/art/games/" + g.id + ".jpg", g.name)', spot)        # (the full picture is only the one behind)
        self.assertIn('src="/box/home/art/games/icon/${esc(g.id)}.jpg"', js)             # Classic's tiles
        with open(os.path.join(BOX, "home", "index.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertLess(html.index('<script src="/box/games/shelf.js">'), html.index('<script src="/box/home/home.js">'))


class GamesPage(unittest.TestCase):
    """In a browser, with the box's agent: the full look (a Pi 4 or 5, a PC)."""
    SLOW = "0"

    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.dir = tempfile.mkdtemp()
        conf, run = os.path.join(cls.dir, "conf"), os.path.join(cls.dir, "run")
        os.makedirs(os.path.join(conf, "icons"))
        os.makedirs(run)
        with open(os.path.join(run, "sofa-box-display"), "w") as f:
            f.write("SCALE=2\n")
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"server": None, "welcomed": True, "weather": "off", "boot_sound": "off"}, f)
        cls.port, cls.devtools = free_port(), free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1920,1080",
                                       "--remote-debugging-port=%d" % cls.devtools, "--user-data-dir=" + os.path.join(cls.dir, "profile"),
                                       cls.base + "/box/home"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.agent = subprocess.Popen([sys.executable, os.path.join(BOX, "sofa-box-agent.py")], stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cls.dir, SOFA_BOX_CONF=conf, SOFA_BOX_PORT=str(cls.port), SOFA_BOX_SLOW=cls.SLOW,
                                              SOFA_BOX_DEVTOOLS=str(cls.devtools), XDG_RUNTIME_DIR=run, SOFA_BOX_UINPUT="0", SOFA_BOX_ICONS="0",
                                              SOFA_BOX_HOTSPOT="0", SOFA_BOX_CERTS="0", SOFA_BOX_NEWEST="0", SOFA_BOX_CAPTIVE_PORT="0",
                                              SOFA_BOX_REMOTE_PORT=str(free_port())))
        for _ in range(300):
            try:
                if json.loads(get(cls.base + "/box/api/apps", 5)[2]).get("devtools"):
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        cls.page = Page(cls.devtools, "/box/home")

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        cls.agent.terminate()
        cls.chrome.terminate()
        cls.agent.wait(10)
        cls.chrome.wait(10)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def games(self, recent=None):
        p = self.page
        p.call("Page.navigate", {"url": self.base + "/box/home?t=%d#/games" % time.time()})
        for _ in range(100):
            if p.value("!!document.querySelector('#view .gp .spt-track .tile')"):
                break
            time.sleep(0.1)
        if recent is not None:
            p.value("localStorage.setItem('sofa:games:recent', %s); location.reload(); 1" % json.dumps(json.dumps([{"id": g} for g in recent])))
            time.sleep(0.5)
            for _ in range(100):
                if p.value("!!document.querySelector('#view .gp .spt-track .tile')"):
                    break
                time.sleep(0.1)
        time.sleep(1.5)                                   # (the opening, then the page as it stays)
        return p

    def rows(self, p):
        return json.loads(p.value("""JSON.stringify([...document.querySelectorAll('#view .gp .spt-row')].map(r => [r.dataset.row,
            [...r.querySelectorAll('.tile')].map(t => t.dataset.game || t.dataset.play || t.dataset.gameGet || t.dataset.gameRemove || (t.dataset.btLook ? 'look' : ''))]))"""))

    def test_a_store_of_rows(self):
        p = self.games(recent=[])
        rows = dict(self.rows(p))
        self.assertNotIn("continue", rows)                # nothing played yet on this box
        order = [r for r, _ in self.rows(p)]
        kinds = ["adventure", "action", "racing", "mind", "arcade"]
        self.assertEqual(order[:7], ["featured"] + kinds + ["together"])      # the big one, then the box's own by kind
        self.assertEqual(rows["featured"][0], CATALOG["featured"])
        self.assertEqual(len(rows["featured"]), 5)                            # (then the newest: a row of one leaves Right nowhere to go)
        newest = sorted(CATALOG["games"], key=lambda g: g["added"], reverse=True)
        self.assertIn(newest[0]["id"], rows["featured"])
        for kind in kinds:                                                     # every game of the box's own on one shelf, once
            self.assertEqual(rows[kind], [g["id"] for g in CATALOG["games"] if g["shelf"] == kind], kind)
        self.assertEqual(sorted(sum((rows[k] for k in kinds), [])), sorted(g["id"] for g in CATALOG["games"]))
        self.assertEqual(sorted(rows["together"]), sorted(g["id"] for g in CATALOG["games"] if g["players"] >= 2))
        self.assertEqual(rows["look"], ["", "", ""])                           # the page's three looks, its last row
        line = p.value("document.querySelector('#view .gp [data-row=adventure] [data-game=wyrd] small').textContent")
        self.assertEqual(line, "Action RPG · 3D · 1 player")                   # what a card says under its name
        self.assertEqual(rows["get"], [g["id"] for g in CATALOG["native"]])
        self.assertEqual(rows["pads"], ["look"])
        self.assertEqual(p.value("document.querySelectorAll('#view .grid.games, #view .pads-card').length"), 0)
        small = json.loads(p.value("JSON.stringify([...document.querySelectorAll('#view .gp .spt-pic > img')].map(i => [i.getAttribute('src'), i.loading]))"))   # (the photographs: a poster's icon is the game's own)
        self.assertTrue(small and all("/box/home/art/games/small/" in s and how == "lazy" for s, how in small), small)
        self.assertEqual(p.value("getComputedStyle(document.querySelector('.top .clock')).visibility"), "hidden")   # one clock
        self.assertEqual(p.value("document.documentElement.classList.contains('spt-on')"), True)

    def test_continue_is_what_was_played_last(self):
        p = self.games(recent=["ironmaw", "nothing-like-it", "tidewing"])
        rows = self.rows(p)
        self.assertEqual(rows[0], ["continue", ["ironmaw", "tidewing"]])   # first, in the order played; one that isn't here left out
        self.assertEqual(p.value("document.activeElement.dataset.game"), "ironmaw")
        self.assertNotIn("featured", dict(rows))                           # (Continue is the first row then)
        p.value("localStorage.removeItem('sofa:games:recent'); 1")

    def test_a_card_says_where_the_game_was_left(self):
        """From the game's own save, at the same address as Home: here one the game's own page wrote. Tidewing keeps
        its save when a race ends; its test hook runs one."""
        p = self.page
        p.call("Page.navigate", {"url": self.base + "/box/games/tidewing/index.html?t=%d#test" % time.time()})
        ready = "document.readyState === 'complete' && !!(window.TW && TW.startRace) && (!window.SofaStats || SofaStats.ready !== false)"
        for _ in range(900):                              # (a slow machine with no GPU: the game takes its time to be ready)
            if p.value(ready):
                break
            time.sleep(0.1)
        self.assertIsNone(p.value("localStorage.getItem('tidewing')"))
        for _ in range(300):                              # into a race, as the bench does it; asked again until it has begun
            p.value("if (TW.state !== 'race') { if (TW.state !== 'intro' && TW.state !== 'countdown') TW.startRace(0); for (const r of TW.racers) r.ai = true; if (TW.go) TW.go(); } 1")
            if p.value("TW.state === 'race'"):
                break
            time.sleep(0.2)
        self.assertEqual(p.value("TW.state"), "race")
        time.sleep(0.5)
        p.value("TW.finishNow(); 1")
        for _ in range(900):                              # the game keeps it itself, when the race ends
            if p.value("!!localStorage.getItem('tidewing')"):
                break
            time.sleep(0.1)
        self.assertTrue(p.value("!!localStorage.getItem('tidewing')"), "Tidewing kept nothing: its state is " + str(p.value("TW.state")))
        kept = json.loads(p.value("localStorage.getItem('tidewing')"))
        self.assertEqual(sorted(kept), ["best", "craft", "cups", "ghost", "open", "opts", "trial", "v"])
        want = "%d of 12 courses open" % kept["open"] if kept["open"] > 1 else "First course run"
        pct = "%d%%" % round(100 * kept["open"] / 12)
        p = self.games(recent=["tidewing"])
        self.assertEqual(p.value("document.querySelector('#view .gp [data-row=continue] [data-game=tidewing] small').textContent"), want)
        for _ in range(40):
            if "Continue" in (p.value("(document.querySelector('#sptText .spt-ok') || {}).textContent") or ""):
                break
            time.sleep(0.1)
        self.assertEqual(p.value("document.querySelector('#sptText .spt-ok').textContent.trim()"), "OKContinue: " + want)
        self.assertEqual(p.value("document.querySelector('#sptText .spt-kicker').textContent"), "Pick up where you left it")
        self.assertEqual(p.value("document.querySelector('#sptText .spt-bar i').style.width"), pct)
        p.value("localStorage.removeItem('sofa:games:recent'); localStorage.removeItem('tidewing'); 1")

    def test_the_featured_games_own_save_is_read(self):
        """WYRD keeps a delver's whole bag and gear: its save is the biggest there is. Here the game makes one itself
        (a new delver, through its test hook), and Home reads it, quickly, for the game in focus."""
        p = self.page
        p.call("Page.navigate", {"url": self.base + "/box/games/wyrd/index.html?t=%d#test" % time.time()})
        for _ in range(600):
            if p.value("!!(window.WY && WY.E && WY.E.ready && WY.H)"):
                break
            time.sleep(0.1)
        p.value("localStorage.removeItem('wyrd'); 1")
        name = p.value("WY.begin()")
        p.value("WY.level(12); WY.sim(0.2); 1")
        for _ in range(100):                              # (the game keeps it itself)
            if "level" in (p.value("localStorage.getItem('wyrd')") or ""):
                break
            time.sleep(0.1)
        raw = p.value("localStorage.getItem('wyrd')")
        kept = json.loads(raw)
        level = kept["slots"][kept["last"]]["level"]
        self.assertEqual(kept["slots"][kept["last"]]["name"], name)
        self.assertLess(len(raw), 64 * 1024)              # (read on the press that reaches it: small enough to)
        p = self.games(recent=["wyrd"])
        took = p.value("(() => { const t = performance.now(); for (let i = 0; i < 50; i++) SofaShelf.where('wyrd', k => localStorage.getItem(k)); return (performance.now() - t) / 50; })()")
        self.assertLess(took, 2, "reading WYRD's save took %.2f ms" % took)
        want = "%s, level %d" % (name, level)
        self.assertEqual(p.value("document.querySelector('#view .gp [data-row=continue] [data-game=wyrd] small').textContent"), want)
        for _ in range(40):
            if "Continue" in (p.value("(document.querySelector('#sptText .spt-ok') || {}).textContent") or ""):
                break
            time.sleep(0.1)
        self.assertEqual(p.value("document.querySelector('#sptText .spt-ok').textContent.trim()"), "OKContinue: " + want)
        # back from a game with Home still loaded (the box: a game is another tab): what it says is read again
        p.value("""(() => { const s = JSON.parse(localStorage.getItem('wyrd')); s.slots[s.last].level = 13; localStorage.setItem('wyrd', JSON.stringify(s)); })(); 1""")
        p.value("document.dispatchEvent(new Event('visibilitychange')); 1")
        want = "%s, level 13" % name
        for _ in range(60):
            if p.value("(document.querySelector('#view .gp [data-row=continue] [data-game=wyrd] small') || {}).textContent") == want:
                break
            time.sleep(0.1)
        self.assertEqual(p.value("document.querySelector('#view .gp [data-row=continue] [data-game=wyrd] small').textContent"), want)
        print("WYRD's own save: %d bytes, read in %.3f ms" % (len(raw), took), file=sys.stderr)
        p.value("localStorage.removeItem('sofa:games:recent'); localStorage.removeItem('wyrd'); 1")

    def test_three_looks_one_markup(self):
        p = self.games(recent=[])
        self.assertEqual(p.value("document.querySelector('#view .gp').dataset.look"), "marquee")
        before = p.value("document.querySelector('#view .gp [data-row=adventure]').innerHTML")
        wide = p.value("document.querySelector('#view .gp [data-row=adventure] .gp-tile').offsetWidth")
        for look, narrower in (("shelf", True), ("index", False)):
            p.value("document.querySelector('#view .gp [data-gp-look=%s]').click(); 1" % look)
            for _ in range(50):
                if p.value("document.querySelector('#view .gp').dataset.look") == look:
                    break
                time.sleep(0.1)
            self.assertEqual(p.value("document.querySelector('#view .gp').dataset.look"), look)
            self.assertEqual(p.value("localStorage.getItem('sofa:games:look')"), look)                  # kept on the box
            self.assertEqual(p.value("document.querySelector('#view .gp [data-row=adventure]').innerHTML"), before, look)   # the same cards
            self.assertEqual(p.value("document.querySelector('#view .gp [data-row=adventure] .gp-tile').offsetWidth") < wide, narrower, look)
            self.assertEqual(p.value("document.querySelector('#view .gp [data-gp-look=%s]').getAttribute('aria-pressed')" % look), "true")
        p.value("localStorage.removeItem('sofa:games:look'); 1")

    def test_the_game_in_focus_is_behind_the_page(self):
        """Its photograph, big, behind; its name, a line about it, who plays and with what, over it; and for a game from
        Debian with no photograph, its icon on its colour."""
        p = self.games(recent=[])
        for _ in range(30):
            if p.value("!!document.querySelector('#sptBg .spt-layer.on img')"):
                break
            time.sleep(0.1)
        gid = p.value("document.activeElement.dataset.game")
        g = next(x for x in CATALOG["games"] if x["id"] == gid)
        self.assertEqual(p.value("document.querySelector('#sptBg .spt-layer.on img').getAttribute('src')"), "/box/home/art/games/%s.jpg" % gid)
        self.assertEqual(p.value("document.querySelector('#sptText .spt-title').textContent"), g["name"])
        chips = json.loads(p.value("JSON.stringify([...document.querySelectorAll('#sptText .spt-chips span')].map(s => s.textContent))"))
        self.assertIn({1: "1 player", 2: "1 or 2 players", 4: "1 to 4 players"}[g["players"]], chips)
        self.assertEqual(chips[:2], [g["kind"], g["dim"]])                     # its kind first, then 2D or 3D
        self.assertEqual(chips[3:], [{"controller": "Controller", "keys": "Keyboard", "touch": "Touch", "remote": "TV remote"}[w] for w in g["with"]])
        self.assertEqual(p.value("document.querySelector('#sptText .spt-kicker').textContent"), "Featured")
        self.assertEqual(p.value("document.querySelector('#sptText .spt-ok').textContent.trim()"), "OKPlay")   # (never played here)
        # down to the games to get: a poster, and behind, its icon on its colour
        p.value("document.querySelector('#view .gp [data-game-get]').scrollIntoView(); 1")
        for _ in range(8):
            if p.value("!!document.activeElement.dataset.gameGet"):
                break
            p.press("ArrowDown", 40)
        self.assertTrue(p.value("!!document.activeElement.dataset.gameGet"))
        self.assertTrue(p.value("!!document.activeElement.querySelector('.gp-poster')"))
        for _ in range(40):                               # (a Pi 3's look: the words change once the remote has rested, 1.2 s)
            if p.value("document.querySelector('#sptText .spt-kicker').textContent") == "Get it, free":
                break
            time.sleep(0.1)
        self.assertEqual(p.value("document.querySelector('#sptText .spt-kicker').textContent"), "Get it, free")
        self.assertTrue(p.value("!!document.querySelector('#sptBg .spt-layer.on .spt-field')"))


class GamesPageLight(GamesPage):
    """A Pi 3 (the light look): a press draws only the ring, and the picture behind stands still."""
    SLOW = "1"

    def test_a_press_draws_no_row_again(self):
        p = self.games(recent=[])
        for _ in range(100):
            if p.value("document.documentElement.classList.contains('lite')"):
                break
            time.sleep(0.1)
        pair = None
        for _ in range(6):
            time.sleep(1.6)                               # (the picture and words of the last press land once the remote rests: 1.2 s)
            if p.drawn_again(lambda: None, 0.5):
                continue
            pair = [len(p.drawn_again(lambda: p.press(key, code))) for key, code in (("ArrowRight", 39), ("ArrowLeft", 37))]
            if max(pair) <= 2:
                break
        self.assertIsNotNone(pair, "the page never came to rest")
        self.assertLessEqual(max(pair), 2, "the row was drawn again when the focus moved: %s pieces" % pair)
        self.assertEqual(p.value("getComputedStyle(document.querySelector('#sptBg .spt-layer.on img') || document.body).animationName"), "none")

    def test_a_press_draws_no_row_again_in_any_look(self):
        """Shelf and Index are the same cards laid out another way: the Pi 3's rule holds in each."""
        p = self.games(recent=[])
        for look in ("shelf", "index"):
            p.value("localStorage.setItem('sofa:games:look', %s); 1" % json.dumps(look))
            p = self.games(recent=[])
            self.assertEqual(p.value("document.querySelector('#view .gp').dataset.look"), look)
            self.assertTrue(p.value("document.documentElement.classList.contains('lite')"))
            pair = None
            for _ in range(6):
                time.sleep(1.6)
                if p.drawn_again(lambda: None, 0.5):
                    continue
                pair = [len(p.drawn_again(lambda: p.press(key, code))) for key, code in (("ArrowRight", 39), ("ArrowLeft", 37))]
                if max(pair) <= 2:
                    break
            self.assertIsNotNone(pair, look + ": the page never came to rest")
            self.assertLessEqual(max(pair), 2, "%s: the row was drawn again when the focus moved: %s pieces" % (look, pair))
        p.value("localStorage.removeItem('sofa:games:look'); 1")


if __name__ == "__main__":
    unittest.main()
