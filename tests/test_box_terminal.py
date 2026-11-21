"""Sofa Box OS 1.1.104: a terminal on the box. Settings → This box → Open the terminal: a small window over the page,
with a shell on the box behind it (the agent's Terminal, on a pseudo-terminal). Only Home's own page reaches it."""
import json
import os
import time
import unittest
import urllib.error
import urllib.request

from tests.test_box_apps_close import BOX, load


def read(*path):
    with open(os.path.join(BOX, *path), encoding="utf-8") as f:
        return f.read()


@unittest.skipIf(os.name == "nt", "a pseudo-terminal: the box is Linux")
class TheShell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = load("sofa-box-agent", SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0")

    def setUp(self):
        self.term = self.agent.Terminal()
        self.addCleanup(self.term.close)

    def until(self, test, wait=10):
        end = time.time() + wait
        while time.time() < end:
            got = self.term.read(0)
            if test(got):
                return got
            time.sleep(0.05)
        self.fail("never: %r" % self.term.read(0))

    def test_a_command_and_what_it_says(self):
        self.term.start()
        self.assertTrue(self.term.running())
        self.term.write(text="echo hel''lo; echo $((6*7))\n")
        got = self.until(lambda r: "hello\r\n" in r["out"].replace("\n", "\r\n") or "\nhello" in r["out"])
        self.assertIn("42", self.until(lambda r: "42" in r["out"])["out"])
        later = self.term.read(got["at"])                                 # (from where it was: only what's new)
        self.assertNotIn("hello", later["out"])

    def test_keys_and_the_end(self):
        self.term.start()
        self.term.write(text="sleep 30\n")
        time.sleep(0.4)
        self.term.write(key="ctrl-c")                                     # (stops what's running)
        self.term.write(text="echo after\n")
        self.until(lambda r: "after" in r["out"])
        with self.assertRaisesRegex(ValueError, "Which key"):
            self.term.write(key="alt-f4")
        self.term.write(text="exit\n")
        self.until(lambda r: not r["running"])
        with self.assertRaisesRegex(ValueError, "isn't open"):
            self.term.write(text="ls\n")

    def test_colours_are_left_out(self):
        self.term.start()
        self.term.write(text="printf '\\033[1;31mred\\033[0m\\n'\n")
        got = self.until(lambda r: "red" in r["out"])
        self.assertNotIn("\x1b", got["out"])


class OnlyFromHome(unittest.TestCase):
    """Reading is a GET, doing is a POST with X-Sofa-Box; a server's page or the phone remote can't reach it."""

    def test_the_route(self):
        agent = load("sofa-box-agent", SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0")
        self.assertTrue(agent.Handler.read_only("/box/api/term"))
        self.assertFalse(any("/box/api/term".startswith(p) for p in agent.Handler.SERVER_PAGE_OK))
        src = read("sofa-box-agent.py")
        self.assertIn('if path == "/box/api/term":', src)
        self.assertIn("return self.send(json.dumps(terminal.read(int((qs.get(\"from\") or [\"0\"])[0] or 0))))", src)

    def test_the_window(self):
        js = read("home", "home.js")
        for text in ('data-term-open="1"', "Open the terminal", 'api("/box/api/term", { action: "open" })', '{ action: "input", text: v + "\\n" }',
                     'data-term-key="ctrl-c"', "e.stopPropagation();", '$(".term-line", w).type = /(password|passphrase)[^:]*:\\s*$/i.test(last) ? "password" : "text";'):
            self.assertIn(text, js)

    def test_the_version(self):
        version = read("VERSION").strip()
        self.assertTrue(read("CHANGES.md").split("\n## ")[1].startswith(version + "\n"))
        self.assertIn("**A terminal on the box.**", read("CHANGES.md"))


if __name__ == "__main__":
    unittest.main()
