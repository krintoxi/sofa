"""What a Sofa Box is built on and under which licences (Settings → This box → Credits and licences, drawn from
deploy/sofa-box/home/credits.json), the games whose own data isn't free software kept off every card, and the TV makers'
own steps for turning off their tracking (Settings → Help, from home/tv-tracking.json)."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
import urllib.request

import tests  # noqa: F401  (sets Sofa up for the tests)
from tests import test_sofa_box as box_tests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(ROOT, "deploy", "sofa-box")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


CREDITS = json.loads(read("deploy", "sofa-box", "home", "credits.json"))
TV = json.loads(read("deploy", "sofa-box", "home", "tv-tracking.json"))
GAMES = json.loads(read("deploy", "sofa-box", "games", "games.json"))
PARTS = [p for g in CREDITS["groups"] for p in g["parts"]]
# What the card's build runs (the build script runs install.sh in the card's own system) and the workflow that runs it.
BUILD = ["deploy/sofa-box/install.sh", "tools/build-sofa-box-image.sh", ".github/workflows/sofa-box-image.yml"]


def apt_installs(text):
    """The packages a shell script installs with apt-get or apt (lines continued with a backslash joined, comments off;
    a variable like $PKGS isn't a package)."""
    text = text.replace("\\\n", " ")
    found = set()
    for line in text.splitlines():
        line = line.split(" #", 1)[0]
        for m in re.finditer(r"\bapt(?:-get)?\b(?:\s+-o\s+\S+|\s+-\S+)*\s+install\b([^;&|)]*)", line):
            found.update(w for w in m.group(1).split() if re.match(r"^[a-z0-9][a-z0-9.+-]+$", w))
    return found


def nonfree_games():
    return {p["game"]: p for p in PARTS if p.get("game") and p.get("free") is False}


class Credits(unittest.TestCase):
    def test_every_part_says_what_it_is(self):
        for p in PARTS:
            for k in ("name", "what", "by", "licence", "source"):
                self.assertTrue(p.get(k), "%s: no %s" % (p.get("name"), k))
            self.assertRegex(p["source"], r"^https://[a-z0-9.-]+\.[a-z]{2,}/", p["name"])
        packages = [x for p in PARTS for x in p.get("packages", [])]
        self.assertEqual(len(packages), len(set(packages)), "a package is credited twice")

    def test_every_package_the_box_installs_is_credited(self):
        """Every package install.sh puts on a box (and so on every card) has its line: a new one can't come in
        without its licence and source said."""
        credited = {x for p in PARTS for x in p.get("packages", [])}
        installed = apt_installs(read("deploy", "sofa-box", "install.sh"))
        self.assertGreater(len(installed), 25)
        self.assertEqual(installed - credited, set(), "installed by install.sh but not in home/credits.json")

    def test_every_game_is_credited(self):
        """Each game the box can install has its licence and source, with exactly its own packages, and every one of
        the box's own games is named under them; a game can't ship without its entry."""
        native = {g["id"]: g for g in GAMES["native"]}
        for gid, g in native.items():
            mine = [p for p in PARTS if p.get("game") == gid]
            self.assertTrue(mine, "%s isn't in home/credits.json" % gid)
            self.assertEqual({x for p in mine for x in p.get("packages", [])}, set(g["packages"]), gid)
        self.assertEqual({p["game"] for p in PARTS if p.get("game")} - set(native), set(), "credits for a game the box doesn't have")
        own = next(p for p in PARTS if p.get("games"))
        self.assertEqual(sorted(own["games"]), sorted(g["id"] for g in GAMES["games"]))
        self.assertIn("PolyForm Noncommercial 1.0.0", own["licence"])
        self.assertEqual(own["by"], "EdgeVenture")

    def test_what_is_on_the_card_says_so(self):
        """A game's "On the box" or "Get more games" on the credits page is what install.sh does."""
        installed = apt_installs(read("deploy", "sofa-box", "install.sh"))
        for g in GAMES["native"]:
            on_card = bool(set(g["packages"]) & installed)
            for p in (p for p in PARTS if p.get("game") == g["id"]):
                self.assertEqual(p.get("on_card", True), on_card, g["id"])

    def test_the_fonts_and_scripts_that_come_with_it(self):
        """Every font and script bundled from elsewhere (client/vendor, the home screen's qrcode.js) has its line, and
        each file named there is there."""
        bundled = {os.path.join("client", "vendor", f) for f in os.listdir(os.path.join(ROOT, "client", "vendor"))
                   if os.path.isfile(os.path.join(ROOT, "client", "vendor", f)) and not f.endswith(".map")}
        bundled |= {os.path.join("client", "vendor", "fonts", f) for f in os.listdir(os.path.join(ROOT, "client", "vendor", "fonts"))}
        bundled.add(os.path.join("deploy", "sofa-box", "home", "qrcode.js"))
        named = {f for p in PARTS for f in p.get("files", [])}
        self.assertEqual(bundled - named, set(), "bundled but not in home/credits.json")
        for f in named:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, f)), f)
        self.assertIn("MIT", read("deploy", "sofa-box", "home", "qrcode.js")[:600])
        for name in ("Bricolage-Grotesque", "Instrument-Sans"):
            self.assertIn("SIL Open Font License, Version 1.1", read("client", "vendor", "fonts", "LICENSE-%s.txt" % name))

    def test_sofa_craft_says_luanti(self):
        """Sofa Craft is Luanti: its tile says so, and so do the credits (a rename to "Luanti" is the owner's call)."""
        craft = next(g for g in GAMES["native"] if g["id"] == "luanti")
        self.assertEqual(craft["name"], "Sofa Craft")
        self.assertTrue(craft["about"].startswith("Powered by Luanti"), craft["about"])
        luanti = next(p for p in PARTS if p.get("game") == "luanti" and p["name"] == "Luanti")
        self.assertEqual(luanti["shown_as"], "Sofa Craft, powered by Luanti")
        self.assertIn("LGPL-2.1-or-later", luanti["licence"])
        self.assertEqual(luanti["source"], "https://github.com/luanti-org/luanti")

    def test_the_pages_are_on_the_box(self):
        """Both pages are reached from Settings, and their data files go onto the card with the home screen."""
        js = read("deploy", "sofa-box", "home", "home.js")
        for page in ("#/credits", "#/tv-tracking"):
            self.assertIn('data-go="%s"' % page, js)
        for name in ("credits", "tv-tracking"):
            self.assertIn('pageJson("%s")' % name, js)
        self.assertNotIn("home", re.findall(r"--exclude=(\S+)", read("deploy", "sofa-box", "install.sh")))


class OnlyWhenAsked(unittest.TestCase):
    """AssaultCube's and Sauerbraten's maps, sounds and pictures aren't free software (free to play, not for commercial
    use): they're never baked into a card, only installed on a box when someone asks for them in Games."""

    def test_they_are_marked(self):
        self.assertEqual(set(nonfree_games()), {"assaultcube", "sauerbraten"})
        for gid, p in nonfree_games().items():
            self.assertIs(p.get("on_card"), False, gid)
            self.assertIn("aren't free software", p["licence"], gid)
            note = next(g for g in GAMES["native"] if g["id"] == gid)["note"]
            self.assertIn("aren't free software", note, gid)

    def test_the_build_never_installs_them(self):
        pkgs = {x for p in nonfree_games().values() for x in p["packages"]}
        for path in BUILD:
            text = read(*path.split("/"))
            self.assertEqual(apt_installs(text) & pkgs, set(), path)
            for gid in nonfree_games():
                self.assertNotIn(gid, text.lower(), "%s mentions %s" % (path, gid))
            self.assertNotIn("games install", text, path)            # (the box's root helper that installs a game)
            self.assertNotIn("/box/api/games", text, path)

    def test_the_build_stops_a_card_that_has_one(self):
        """The card's build checks, after installing everything, that none of them is on it, and stops if one is."""
        script = read("tools", "build-sofa-box-image.sh")
        cmd = re.search(r"python3 -c '([^']*credits\.json[^']*)'", script)
        self.assertTrue(cmd, "the build doesn't read home/credits.json")
        code = cmd.group(1).replace("/usr/local/lib/sofa-box/home/credits.json", os.path.join(BOX, "home", "credits.json"))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(sorted(out), ["assaultcube", "sauerbraten"])
        loop = script[script.index('for p in $NONFREE; do'):]
        self.assertIn("dpkg-query", loop.split("done", 1)[0])
        self.assertIn("exit 1", loop.split("done", 1)[0])

    def test_a_box_installs_one_only_when_asked(self):
        """Only Games' "Get" button starts an install: the home screen asks the agent (a POST only a page of the box
        itself can make), and the agent's only way to the root helper is that request."""
        agent = read("deploy", "sofa-box", "sofa-box-agent.py")
        self.assertEqual(agent.count("games.change("), 1)
        at = agent.index("games.change(")
        self.assertIn('if path == "/box/api/games":', agent[at - 400:at])
        self.assertIn('if self.command == "POST":', agent[at - 400:at])
        self.assertEqual(agent.count('"sofa-box"), "games"]'), 1)         # (sudo sofa-box games <install|remove> <id>)
        js = read("deploy", "sofa-box", "home", "home.js")
        self.assertEqual(js.count('action: "install"'), 1)
        self.assertIn('else if (d.gameGet)', js[:js.index('action: "install"')][-400:])
        for page in ("remote.html", os.path.join("home", "inject.js")):
            self.assertNotIn("/box/api/games", read("deploy", "sofa-box", page))


MAKERS = {"samsung": "samsung.com", "lg": "lg.com", "vizio": "vizio.com", "roku": "roku.com", "google": "google.com",
          "sony": "sony.com", "tcl": "tcl.com", "hisense": "hisense-usa.com", "firetv": "amazon.com"}


class TvTracking(unittest.TestCase):
    def test_each_brand_from_its_makers_own_pages(self):
        self.assertEqual([b["id"] for b in TV["brands"]], list(MAKERS))
        for b in TV["brands"]:
            self.assertTrue(b["name"] and b["kind"] and b["steps"] and b["sources"], b["id"])
            for s in b["sources"]:
                host = urllib.parse.urlsplit(s["url"]).hostname
                self.assertTrue(s["url"].startswith("https://") and (host == MAKERS[b["id"]] or host.endswith("." + MAKERS[b["id"]])),
                                "%s: %s isn't the maker's own" % (b["id"], s["url"]))
                self.assertTrue(s["title"], b["id"])

    def test_it_says_menus_change(self):
        self.assertIn("Menu names change between models and years", TV["caveat"])
        self.assertIn("can't switch it off for you", TV["about"])
        self.assertTrue(TV["offline"]["title"] and TV["offline"]["text"])


@unittest.skipUnless(box_tests.chrome(), "needs Chrome or Chromium")
class TheTwoPages(unittest.TestCase):
    """The pages on the box's own home screen, in Chromium: every line and brand there, OK showing the rest with its
    page as a code, Back going back to Settings."""
    setUpClass = box_tests.BoxBrowser.__dict__["setUpClass"]
    tearDownClass = box_tests.BoxBrowser.__dict__["tearDownClass"]
    apps = box_tests.BoxBrowser.__dict__["apps"]
    page_value = box_tests.BoxBrowser.page_value

    def until(self, expression, want, seconds=20):
        end, got = time.time() + seconds, None
        while time.time() < end:
            try:
                got = self.page_value("/box/home", expression)
                if got == want:
                    return got
            except (StopIteration, OSError):
                pass
            time.sleep(0.3)
        self.assertEqual(got, want, expression)

    def key(self, name):
        self.page_value("/box/home", "document.dispatchEvent(new KeyboardEvent('keydown', {key: %s, bubbles: true}))" % json.dumps(name))

    def test_credits_and_the_tvs_own_tracking(self):
        self.until("!!window.document.querySelector('.tabs a')", True, 90)
        self.page_value("/box/home", "location.hash = '#/settings/box'")
        self.until("!!document.querySelector('[data-go=\"#/credits\"]')", True)
        self.page_value("/box/home", "document.querySelector('[data-go=\"#/credits\"]').click()")
        self.until("document.querySelectorAll('.credit').length", len(PARTS))
        self.until("document.querySelector('.f') && document.querySelector('.f').id", "cr-system-0")
        luanti = "cr-games-%d" % next(i for i, p in enumerate(next(g for g in CREDITS["groups"] if g["id"] == "games")["parts"]) if p["name"] == "Luanti")
        self.page_value("/box/home", "document.getElementById(%s).click()" % json.dumps(luanti))
        self.until("document.querySelector('.sheet .addr') && document.querySelector('.sheet .addr').textContent", "github.com/luanti-org/luanti")
        self.assertEqual(self.page_value("/box/home", "document.querySelector('.sheet .sheet-note').textContent"), "Sofa Craft, powered by Luanti")
        self.assertTrue(self.page_value("/box/home", "!!document.querySelector('.sheet .qr svg')"))
        self.key("Escape")
        self.until("!!document.querySelector('.sheet')", False)
        self.key("Escape")
        self.until("location.hash", "#/settings/box")

        self.page_value("/box/home", "location.hash = '#/settings/help'")
        self.until("!!document.querySelector('[data-go=\"#/tv-tracking\"]')", True)
        self.page_value("/box/home", "document.querySelector('[data-go=\"#/tv-tracking\"]').click()")
        self.until("document.querySelectorAll('.tile.brand').length", len(TV["brands"]))
        self.page_value("/box/home", "document.querySelector('[data-tv-brand=\"lg\"]').click()")
        lg = next(b for b in TV["brands"] if b["id"] == "lg")
        self.until("document.querySelectorAll('.sheet .tv-steps li').length", len(lg["steps"]))
        self.until("document.querySelector('#tvPage b').textContent", lg["sources"][0]["title"])
        self.page_value("/box/home", "document.querySelector('.sheet [data-sheet=\"page:2\"]').click()")
        self.until("document.querySelector('#tvPage b').textContent", lg["sources"][2]["title"])
        self.assertIn("Menu names change", self.page_value("/box/home", "document.querySelector('.sheet').textContent"))
        self.key("Escape")
        self.key("Escape")
        self.until("location.hash", "#/settings/help")


if __name__ == "__main__":
    unittest.main()
