"""Sofa Box OS 1.1.100 and 1.1.102: Save this disc on a box. A disc in the box's USB drive goes into Sofa on this box (its Movies,
Shows or Music) from Home: the box's own Sofa reads the disc and files it (sofa/disc.py, tests/test_disc.py), and the
box's agent passes Home's questions to it.

Checked here with a stand-in for the box's Sofa and by reading the page's script. Not on a Pi, and with no disc drive."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tests.test_box_apps_close import BOX, load


def read(*path):
    with open(os.path.join(BOX, *path), encoding="utf-8") as f:
        return f.read()


class BoxSofa:
    """The box's own Sofa, as the agent uses it."""

    def __init__(self, conf, there=True, starts=True, running=False):
        self.conf, self.there, self.starts, self.running, self.asked = conf, there, starts, running, []

    def available(self):
        return self.there

    def ensure(self, wait=40):
        self.asked.append("start")
        self.running = self.starts
        return self.starts

    def answering(self):
        return self.running

    def sign_in(self):
        self.asked.append("sign in")
        with open(os.path.join(self.conf, "this-box.json"), "w") as f:
            f.write("{}")
        return "token"

    def api(self, path, body=None, timeout=20):
        self.asked.append((path, body))
        if body and body.get("name") == "":
            raise ValueError("Give it a name.")
        return {"drives": [{"id": "sr0", "state": "disc", "kind": "dvd"}], "jobs": []} if body is None else {"ok": True}


class TheAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = load("sofa-box-agent", SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0")

    def with_sofa(self, **how):
        conf = tempfile.mkdtemp(prefix="sofa-box-disc-")
        self.addCleanup(shutil.rmtree, conf, True)
        sofa = BoxSofa(conf, **how)
        for name, value in (("local_sofa", sofa), ("CONF_DIR", conf)):
            patch = mock.patch.object(self.agent, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        return sofa

    def test_a_look_starts_nothing(self):
        """A plain GET only reads (any page in the box's browser can send one): it doesn't start Sofa on the box or
        make the box's account there. Home asks for that with a POST."""
        sofa = self.with_sofa()
        self.assertEqual(self.agent.disc_save(), {"stopped": True, "drives": [], "jobs": []})
        self.assertEqual(sofa.asked, [])
        sofa.running = True                                                          # running, but no account of the box's yet
        self.assertTrue(self.agent.disc_save()["stopped"])
        self.assertEqual(sofa.asked, [])
        self.assertEqual(self.agent.disc_save({"action": "start"}), {"ok": True})
        self.assertEqual(sofa.asked, ["start", "sign in"])
        self.assertEqual(self.agent.disc_save()["drives"][0]["kind"], "dvd")
        js = read("home", "home.js")
        self.assertIn('if (discData.stopped) { await api("/box/api/disc", { action: "start" }); discData = await api("/box/api/disc"); }', js)

    def test_homes_questions_go_to_the_boxs_own_sofa(self):
        sofa = self.with_sofa(running=True)
        self.agent.disc_save({"action": "start"})
        del sofa.asked[:]
        ask = {"action": "save", "drive": "sr0", "to": "movies", "name": "Summer", "titles": [1]}
        self.assertEqual(self.agent.disc_save(ask), {"ok": True})
        self.assertEqual(sofa.asked, ["start", ("/api/admin/disc", ask)])
        with self.assertRaisesRegex(ValueError, "Give it a name"):                   # Sofa's own words reach the TV
            self.agent.disc_save(dict(ask, name=""))
        with self.assertRaisesRegex(ValueError, "Save, stop or names"):
            self.agent.disc_save({"action": "erase"})

    def test_when_the_boxs_sofa_isnt_there(self):
        self.with_sofa(there=False)
        with self.assertRaisesRegex(ValueError, "needs Sofa on this box"):
            self.agent.disc_save()
        self.with_sofa(starts=False)
        with self.assertRaisesRegex(ValueError, "didn't start"):
            self.agent.disc_save({"action": "start"})

    def test_looking_is_a_get_and_saving_a_post(self):
        h = self.agent.Handler
        self.assertTrue(h.read_only("/box/api/disc"))
        self.assertFalse(h.read_only("/box/api/disc/play"))
        src = read("sofa-box-agent.py")
        self.assertIn('return self.send(json.dumps(disc_save(data if self.command == "POST" else None)))', src)

    def test_nothing_the_box_installs_unlocks_a_disc(self):
        """What a box is built from: nothing that decrypts a DVD or a Blu-ray is installed, fetched or named."""
        for name in ("install.sh", "sofa-box", "other-hardware.sh"):
            low = read(name).lower()
            for word in ("libdvdcss", "libdvd-pkg", "libaacs", "libbdplus", "makemkv", "decss", "keydb"):
                self.assertNotIn(word, low, "%s names %s" % (name, word))


class ThePlayersMenu(unittest.TestCase):
    """Menu while a disc from Home's tile plays: Save this disc, in one press, into Sofa on this box."""

    @classmethod
    def setUpClass(cls):
        cls.agent = load("sofa-box-agent", SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0")
        cls.boxos = load("boxos")

    def test_the_disc_goes_with_what_plays(self):
        p = self.boxos.disc_payload({"dev": "/dev/sr0", "kind": "dvd", "label": "HOLIDAY"})
        self.assertEqual(p["disc"], {"drive": "sr0", "kind": "dvd"})

    def player(self, payload):
        pl = self.agent.Player.__new__(self.agent.Player)
        pl.payload, pl.rec, said = payload, None, []
        pl.command = lambda *a: [] if a[:2] == ("get_property", "track-list") else 1
        pl.osd = lambda **k: said.append(k)
        return pl, said

    def test_its_there_for_a_disc_and_not_otherwise(self):
        with mock.patch.object(self.agent, "volume_now", return_value=(50, False)):
            pl, _ = self.player({"disc": {"drive": "sr0", "kind": "dvd"}})
            self.assertEqual(pl.menu_items()[0][0], "Save this disc")
            pl, _ = self.player({"url": "http://x/y.mkv"})
            self.assertNotIn("Save this disc", [i[0] for i in pl.menu_items()])

    def test_ok_saves_it_while_it_plays(self):
        pl, said = self.player({"disc": {"drive": "sr0", "kind": "dvd"}})
        asked = []

        def disc_save(ask=None):
            asked.append(ask)
            if ask is None:
                return {"drives": [{"id": "sr0", "disc": {"kind": "dvd"}}], "jobs": []}
            return {"ok": True} if ask["action"] == "start" else {"ok": True, "job": {"name": "Holiday", "to": "Movies"}}
        with mock.patch.object(self.agent, "disc_save", disc_save), mock.patch.object(self.agent, "playing", return_value=True):
            pl._save_disc("sr0")
        self.assertEqual(asked, [{"action": "start"}, None, {"action": "save", "drive": "sr0", "quick": True}])
        self.assertEqual(said, [{"toast": "Saving Holiday to Movies on this box. Keep watching: it carries on."}])
        src = read("sofa-box-agent.py")
        self.assertIn('items.append(["Save this disc", [(None, "to Sofa on this box")], 0, "disc"])', src)
        self.assertIn("threading.Thread(target=self._save_disc, args=(drive,), daemon=True).start()", src)


class Home(unittest.TestCase):
    def test_the_tile_and_the_page(self):
        js = read("home", "home.js")
        self.assertIn('data-go-disc="1"', js)
        self.assertIn("<b>Save this disc</b><small>To Movies, Shows or Music on this box</small>", js)
        self.assertIn('else if (d.goDisc) { discData = null; location.hash = "#/disc"; }', js)
        self.assertIn('name === "disc" ? viewDisc()', js)
        self.assertIn('TABS.disc = "home"', js)                                     # (Back goes Home)
        for text in ('api("/box/api/disc", ask)', 'api("/box/api/disc", { action: "stop", job: job.id })', "Put a DVD or CD in the disc drive.",
                     "else if (k.problem) body +=", "Leave the disc in."):
            self.assertIn(text, js)
        # a disc that can't be saved (copy-protected) shows why, and no Save button comes after it
        problem = js[js.index("else if (k.problem) body +="):]
        self.assertLess(problem.index("else {"), problem.index('data-disc-do="save"'))
        # every button the page draws is one Home's arrow keys can come back to
        keys = js[js.index("function keyOf(el)"):js.index("function keyOf(el)") + 600]
        for name in ("goDisc", "discDo", "discTo", "discSet", "discTitle", "discTrack"):
            self.assertIn('"%s"' % name, keys)

    def test_the_boxs_user_may_read_the_drive(self):
        self.assertIn("for g in video render input audio bluetooth netdev cdrom; do", read("install.sh"))

    def test_its_in_the_list_of_whats_new(self):
        version = read("VERSION").strip()
        self.assertTrue(read("CHANGES.md").split("\n## ")[1].startswith(version + "\n"))    # the newest section is this version's
        self.assertIn("**Save this disc.**", read("CHANGES.md"))


if __name__ == "__main__":
    unittest.main()
