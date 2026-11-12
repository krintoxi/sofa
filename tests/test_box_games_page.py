"""Sofa Box OS: the Games page as a store.

On a Pi 3 B+ (1.1.73) the owner called the Games page outdated: a grey bar across the top, flat grey cards with a small
icon and two lines of text, the hints drawn over them. It's a store now, in Spotlight's way: behind it, the game the
remote is on (its photograph, playing itself, or for a game from Debian its icon on its colour), its name, a line about
it, who plays and with what; rows below like a console's store (Continue, New, Two or more players, the box's own, from
Debian, more to get, controllers). A row's pictures are small copies, loaded when they come near the screen; on a Pi 3
a press still draws only the ring."""
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
        web = [g["id"] for g in CATALOG["games"]]
        self.assertEqual(rows["own"], web)
        newest = sorted(CATALOG["games"] + CATALOG["native"], key=lambda g: g["added"], reverse=True)
        self.assertEqual(rows["new"][0], newest[0]["id"])  # (no game from Debian is on a Mac: the newest of the box's own)
        self.assertEqual(sorted(rows["two"]), sorted(g["id"] for g in CATALOG["games"] if g["players"] >= 2))
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
        p.value("localStorage.removeItem('sofa:games:recent'); 1")

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
        self.assertEqual(p.value("document.querySelector('#sptText .spt-kicker').textContent"), "New on the box")
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


if __name__ == "__main__":
    unittest.main()
