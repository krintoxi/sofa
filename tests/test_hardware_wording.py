"""Hardware is named by what it is (processor family and features, cores, memory, graphics or encoder, system),
never by a computer's model and year: the README, the docs, the web app's text, comments and tests.

Left alone: the changelogs (history stays as it was written), the box's games, and the names a computer gives
itself on the network (the box shows "Living Room iMac" for a Sofa it found, because that is what the household
calls it)."""
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KINDS = (".md", ".py", ".js", ".html", ".yml", ".sh", ".iss", ".brs", ".kt", ".txt")
SKIP = ("CHANGES.md", "deploy/sofa-box/CHANGES.md", "imager/CHANGES.md", "deploy/sofa-box/games/", "tests/test_hardware_wording.py")
MAC = r"(?:i?Mac(?:Book)?(?: (?:mini|Pro|Air|Studio))?)"
MODELS = [
    re.compile(r"\b(?:19|20)\d\d[- ]" + MAC + r"\b"),                              # "2011 iMac", "2015 MacBook Pro"
    re.compile(r"\b" + MAC + r"[ ,(]+(?:early|mid|late)?[- ]?(?:19|20)\d\d\b", re.I),   # "iMac (Mid 2011)"
    re.compile(r"\b(?:early|mid|late)[- ](?:19|20)\d\d\b", re.I),                  # "Late 2013"
    re.compile(r"\b(?:ThinkPad|ThinkCentre|OptiPlex|Latitude|EliteDesk|ProDesk|Chromebox|Beelink|Minisforum)\b"),
    re.compile(r"\bNUC[ -]?\d"),                                                   # "NUC 7", "NUC11"
    re.compile(r"\biPhone \d|\bGalaxy S\d|\bPixel \d"),                            # a phone by its model
]


def tracked():
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files"], capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.split("\n")[:-1]
    except OSError:
        pass
    found = []
    for d, dirs, names in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", "vendor", "build", "node_modules", "data")]
        found += [os.path.relpath(os.path.join(d, n), ROOT).replace(os.sep, "/") for n in names]
    return found


class HardwareByWhatItIs(unittest.TestCase):
    def test_no_computer_is_named_by_model_and_year(self):
        seen = []
        for rel in tracked():
            if not rel.endswith(KINDS) or rel.startswith(SKIP) or "/vendor/" in rel:
                continue
            try:
                with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as f:
                    lines = f.read().split("\n")
            except OSError:
                continue
            for n, line in enumerate(lines, 1):
                if len(line) > 4000:                 # a packed asset on one line, not prose
                    continue
                for rx in MODELS:
                    m = rx.search(line)
                    if m:
                        seen.append("%s:%d: %s" % (rel, n, m.group(0)))
        self.assertEqual(seen, [], "name the hardware (processor, cores, memory, graphics, system), not the model")

    def test_the_patterns_catch_what_they_are_for(self):
        for text in ("used daily on a 2011 iMac", "a 2015 MacBook Pro", "iMac (Mid 2011)", "a Late 2013 one", "a NUC 7",
                     "an OptiPlex", "iPhone 15 as the remote"):
            self.assertTrue(any(rx.search(text) for rx in MODELS), text)
        for text in ("four Intel cores without AVX2 (Sandy Bridge)", "Raspberry Pi 3 Model B+ (BCM2837B0)", "an Intel N100",
                     "Apple silicon (A18 Pro, 6 cores, 8 GB)", "a phone with iOS Safari", "macOS 13", "since 2015"):
            self.assertFalse(any(rx.search(text) for rx in MODELS), text)

    def test_the_capabilities_page_has_a_tested_hardware_table(self):
        with open(os.path.join(ROOT, "docs", "capabilities.md"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("## Tested hardware", page)
        self.assertIn('<a id="tested-on"></a>', page)                 # the links made before the table was renamed
        table = page.split("## Tested hardware", 1)[1]
        self.assertIn("| Hardware | Running | Last version tested | When | By whom |", table)
        for spec in ("BCM2837B0, 4 x Cortex-A53, 1 GB", "x86-64 without AVX2", "Apple silicon", "arm64, virtual", "x86-64, virtual"):
            self.assertIn(spec, table)
        rows = [l for l in table.split("\n") if l.startswith("| **")]
        self.assertGreaterEqual(len(rows), 15)
        for row in rows:                                              # every row: six cells, the hardware first
            self.assertEqual(len(re.findall(r"(?<!\\)\|", row)), 7, row[:80])


if __name__ == "__main__":
    unittest.main()
