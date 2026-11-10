"""Sofa Box OS's list for Raspberry Pi Imager (tools/sofa-box-imager-list.py): what goes in it from GitHub's
releases, the unpacked sizes and SHA-256s Imager checks the card against, unpacking each card once, refusing a
card that isn't what GitHub says, the checks on a finished list, and the workflow and guide that use it."""
import contextlib
import hashlib
import importlib.util
import io
import json
import lzma
import os
import re
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(HERE, "tools", "sofa-box-imager-list.py")
spec = importlib.util.spec_from_file_location("sofa_box_imager_list", TOOL)
imager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imager)


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Cards:
    """Tiny .img.xz "cards" in a folder, and GitHub-shaped releases pointing at them."""

    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.paths = {}                             # each card's https address -> its file here

    def measure(self, url, expect=None):
        return imager.measure(self.paths[url], expect)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def card(self, name, raw, digest=None):
        packed = lzma.compress(raw, format=lzma.FORMAT_XZ)
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(packed)
        url = "https://github.com/krintoxi/sofa/releases/download/test/" + name
        self.paths[url] = path
        return {"name": name, "size": len(packed), "state": "uploaded", "browser_download_url": url,
                "digest": "sha256:" + (digest or sha(packed)), "updated_at": "2026-11-10T07:38:01Z"}

    @staticmethod
    def release(tag, name, assets, published="2026-11-10T07:38:37Z", draft=False):
        return {"tag_name": tag, "name": name, "draft": draft, "published_at": published,
                "html_url": "https://github.com/krintoxi/sofa/releases/tag/" + tag, "assets": assets}

    def version(self, ver, raw, published="2026-11-10T07:38:37Z"):
        return self.release("box-os-v" + ver, "Sofa Box OS " + ver,
                            [self.card("sofa-box-os-%s.img.xz" % ver, raw),
                             {"name": "sofa-box-os-%s-report.txt" % ver, "size": 10, "state": "uploaded",
                              "browser_download_url": "x"}], published)

    def rolling(self, ver, raw, day="2026-11-10"):
        return self.release("sofa-box", "Sofa Box OS %s (testing): the newest card (%s)" % (ver, day),
                            [self.card("sofa-box.img.xz", raw)], "2026-11-02T22:45:57Z")

    def stable(self, version_release=None, ver=None, digest=None):
        """The "sofa-box-stable" release as tools/sofa-box-releases.py leaves it: marking VERSION_RELEASE's card
        (or ver and digest as given), or with no stable card yet."""
        rel = self.release("sofa-box-stable", "Sofa Box OS: no stable card yet", [])
        rel["body"] = "No Sofa Box OS card is marked stable yet (tried on a real box)."
        if version_release or ver:
            if version_release:
                ver = version_release["tag_name"][len("box-os-v"):]
                digest = digest or version_release["assets"][0]["digest"][len("sha256:"):]
            rel["name"] = "Sofa Box OS %s (stable): the tested card" % ver
            rel["body"] = "<!-- sofa-box-stable version=%s sha256=%s -->\nThe **stable** card." % (ver, digest)
            rel["assets"] = [self.card("sofa-box-stable.img.xz", b"a copy")]
        return rel


def no_unpacking(*_):
    raise AssertionError("a card was unpacked again")


class List(unittest.TestCase):
    def setUp(self):
        self.c = Cards()
        self.addCleanup(self.c.close)
        # a card of mostly empty space, like the real one: it packs small and unpacks large
        self.newest = b"Sofa Box OS 1.1.54\n" + bytes(3 << 20) + b"end"

    def test_the_newest_version_first_with_what_imager_checks(self):
        rels = [self.c.version("1.1.9", b"nine" * 1000, "2026-11-03T13:23:58Z"),
                self.c.rolling("1.1.54", self.newest),
                self.c.version("1.1.54", self.newest),
                self.c.version("1.1.10", b"ten" * 1000, "2026-11-03T19:09:26Z"),
                self.c.release("firetv-17", "Sofa for Fire TV (build 17)", [])]
        doc = imager.build(rels, {}, keep=2, measure_fn=self.c.measure)
        self.assertEqual(imager.check(doc), [])
        top = doc["os_list"][0]
        self.assertEqual(top["name"], "Sofa Box OS 1.1.54")
        self.assertTrue(top["url"].endswith("sofa-box-os-1.1.54.img.xz"), "the numbered card, whose file never changes")
        self.assertEqual(top["extract_size"], len(self.newest))
        self.assertEqual(top["extract_sha256"], sha(self.newest))
        self.assertEqual(top["image_download_size"], os.path.getsize(self.c.paths[top["url"]]))
        self.assertEqual(top["release_date"], "2026-11-10")
        self.assertEqual(top["init_format"], "none", "Imager offers none of its settings for the card")
        self.assertEqual(top["devices"], ["pi5-64bit", "pi4-64bit", "pi3-64bit"])
        self.assertEqual(top["website"], "https://github.com/krintoxi/sofa/releases/tag/box-os-v1.1.54")
        # the newest card is the same file as 1.1.54's: listed once
        self.assertEqual(len(doc["os_list"]), 2)
        group = doc["os_list"][1]
        self.assertEqual([s["name"] for s in group["subitems"]], ["Sofa Box OS 1.1.10", "Sofa Box OS 1.1.9"],
                         "by number, not as text (1.1.10 is newer than 1.1.9)")
        self.assertEqual(group["subitems"][1]["release_date"], "2026-11-03")
        # the boards Imager's first step offers, with Raspberry Pi OS's own tags
        devs = doc["imager"]["devices"]
        self.assertEqual([d["name"] for d in devs], ["Raspberry Pi 5", "Raspberry Pi 4", "Raspberry Pi 3"])
        self.assertTrue(all(d["matching_type"] == "exclusive" and d["description"] for d in devs))

    def test_the_newest_build_is_listed_only_when_it_differs(self):
        rels = [self.c.version("1.1.54", self.newest), self.c.rolling("1.1.54", self.newest + b" and a fix", "2026-11-12")]
        doc = imager.build(rels, {}, measure_fn=self.c.measure)
        self.assertEqual(imager.check(doc), [])
        self.assertEqual([e["name"] for e in doc["os_list"]],
                         ["Sofa Box OS 1.1.54", "Sofa Box OS 1.1.54, newest build (testing)"])
        testing = doc["os_list"][1]
        self.assertTrue(testing["url"].endswith("/sofa-box.img.xz"))
        self.assertEqual(testing["extract_sha256"], sha(self.newest + b" and a fix"))
        self.assertIn("2026-11-10", testing["description"])

    def test_the_stable_version_on_top(self):
        v54, v58 = self.c.version("1.1.54", self.newest), self.c.version("1.1.58", b"newer" * 1000)
        older = [self.c.version("1.1.%d" % n, b"v%d" % n * 1000) for n in (49, 50, 51)]
        rels = [self.c.rolling("1.1.58", b"newer" * 1000), v58, self.c.stable(v54), v54] + older
        doc = imager.build(rels, {}, keep=5, measure_fn=self.c.measure)
        self.assertEqual(imager.check(doc), [])
        self.assertEqual([e["name"] for e in doc["os_list"]],
                         ["Sofa Box OS 1.1.54 (stable)", "Sofa Box OS 1.1.58 (testing)", "Sofa Box OS: earlier versions"])
        top = doc["os_list"][0]
        self.assertTrue(top["url"].endswith("/sofa-box-os-1.1.54.img.xz"), "its own card, not sofa-box-stable's copy")
        self.assertEqual(top["extract_sha256"], sha(self.newest))
        self.assertIn("Tried on a real box", top["description"])
        self.assertIn("not tried on a real box", doc["os_list"][1]["description"])
        self.assertEqual([s["name"] for s in doc["os_list"][2]["subitems"]],
                         ["Sofa Box OS 1.1.51", "Sofa Box OS 1.1.50", "Sofa Box OS 1.1.49"])
        # Sofa Box Imager offers the first top entry without "(testing)": the stable one
        self.assertEqual([e["name"] for e in doc["os_list"] if "(testing)" not in e["name"]][0], top["name"])

    def test_the_newest_is_the_stable_one(self):
        v54 = self.c.version("1.1.54", self.newest)
        doc = imager.build([self.c.stable(v54), v54, self.c.rolling("1.1.54", self.newest)], {}, measure_fn=self.c.measure)
        self.assertEqual([e["name"] for e in doc["os_list"]], ["Sofa Box OS 1.1.54 (stable)"])

    def test_a_stable_mark_that_doesnt_match_is_ignored(self):
        v54, v58 = self.c.version("1.1.54", self.newest), self.c.version("1.1.58", b"newer" * 1000)
        for mark in (self.c.stable(v54, digest="0" * 64),         # another file than 1.1.54's own card
                     self.c.stable(ver="1.1.40", digest="1" * 64),  # a version with no card here
                     self.c.stable()):                               # none marked (STABLE says "none")
            logged = []
            doc = imager.build([v58, mark, v54], {}, measure_fn=self.c.measure, log=logged.append)
            self.assertEqual(imager.check(doc), [])
            self.assertEqual(doc["os_list"][0]["name"], "Sofa Box OS 1.1.58", "the newest, as while none is marked")
            self.assertEqual(doc["os_list"][1]["subitems"][0]["name"], "Sofa Box OS 1.1.54")
            if mark["body"].startswith("<!--"):
                self.assertTrue(any("not listed as stable" in s for s in logged))

    def test_only_the_newest_build_when_nothing_is_numbered(self):
        doc = imager.build([self.c.rolling("1.0.0", b"first" * 100)], {}, measure_fn=self.c.measure)
        self.assertEqual(imager.check(doc), [])
        self.assertEqual([e["name"] for e in doc["os_list"]], ["Sofa Box OS 1.0.0, newest build (testing)"])

    def test_each_card_is_unpacked_once(self):
        rels = [self.c.version("1.1.54", self.newest), self.c.version("1.1.49", b"older" * 500)]
        cache = {}
        first = imager.build(rels, cache, measure_fn=self.c.measure)
        self.assertEqual(len(cache), 2)
        again = imager.build(rels, json.loads(json.dumps(cache)), measure_fn=no_unpacking)
        self.assertEqual(again, first)
        # a cache entry for another file of the same name (a different size) isn't trusted
        key = rels[0]["assets"][0]["digest"][len("sha256:"):]
        cache[key]["image_download_size"] += 1
        with self.assertRaises(AssertionError):
            imager.build(rels, cache, measure_fn=no_unpacking)

    def test_a_card_that_isnt_what_github_says_is_refused(self):
        rel = self.c.version("1.1.54", self.newest)
        rel["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(imager.ListError, "packed SHA-256"):
            imager.build([rel], {}, measure_fn=self.c.measure)
        rel = self.c.version("1.1.55", self.newest)
        path = self.c.paths[rel["assets"][0]["browser_download_url"]]
        with open(path, "rb") as f:
            cut = f.read()[:-40]
        with open(path, "wb") as f:
            f.write(cut)
        rel["assets"][0].update(size=len(cut), digest="sha256:" + sha(cut))
        with self.assertRaisesRegex(imager.ListError, "ends early"):
            imager.build([rel], {}, measure_fn=self.c.measure)

    def test_drafts_and_releases_without_a_card_are_left_out(self):
        rels = [self.c.version("1.1.54", self.newest),
                dict(self.c.version("1.2.0", b"draft" * 100), draft=True),
                self.c.release("box-os-v1.1.60", "Sofa Box OS 1.1.60", []),
                self.c.release("box-v1", "an old tag", [self.c.card("sofa-box.img.xz", b"x" * 100)])]
        doc = imager.build(rels, {}, measure_fn=self.c.measure)
        self.assertEqual([e["name"] for e in doc["os_list"]], ["Sofa Box OS 1.1.54"])
        with self.assertRaisesRegex(imager.ListError, "no Sofa Box OS card"):
            imager.build(rels[1:], {}, measure_fn=self.c.measure)

    def test_a_card_in_several_xz_streams(self):
        a, b = b"first part " * 5000, bytes(1 << 20) + b"second part"
        path = os.path.join(self.c.dir, "joined.img.xz")
        with open(path, "wb") as f:
            f.write(lzma.compress(a) + bytes(8) + lzma.compress(b))     # zero padding between streams, as xz allows
        got = imager.measure(path)
        self.assertEqual(got["extract_size"], len(a + b))
        self.assertEqual(got["extract_sha256"], sha(a + b))
        with open(path, "rb") as f:
            self.assertEqual(got["image_sha256"], sha(f.read()))

    def test_the_command_line(self):
        rels = [self.c.version("1.1.54", self.newest)]
        real = imager.measure
        imager.measure = lambda url, expect=None: real(self.c.paths[url], expect)
        self.addCleanup(setattr, imager, "measure", real)
        r, cache, out = (os.path.join(self.c.dir, n) for n in ("releases.json", "cache.json", "list.rpi-imager-manifest"))
        with open(r, "w") as f:
            json.dump(rels, f)
        said = io.StringIO()
        with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said):
            self.assertEqual(imager.main(["build", "--releases", r, "--cache", cache, "--out", out]), 0)
            self.assertEqual(imager.main(["check", out]), 0)
        self.assertIn("unpacking sofa-box-os-1.1.54.img.xz", said.getvalue())
        self.assertIn("Sofa Box OS 1.1.54", said.getvalue())
        with open(out) as f:
            self.assertEqual(json.load(f)["os_list"][0]["extract_sha256"], sha(self.newest))
        with open(cache) as f:
            self.assertEqual(len(json.load(f)), 1)


class Checks(unittest.TestCase):
    def setUp(self):
        c = Cards()
        self.addCleanup(c.close)
        self.doc = imager.build([c.version("1.1.54", b"card" * 2000), c.version("1.1.49", b"old" * 2000)], {}, measure_fn=c.measure)
        self.assertEqual(imager.check(self.doc), [])

    def problems(self, change):
        doc = json.loads(json.dumps(self.doc))
        change(doc)
        return "\n".join(imager.check(doc))

    def test_imager_needs_the_boards(self):
        # Imager draws "Choose device" from the list's own imager.devices: without them the step is empty
        self.assertIn("imager.devices is empty", self.problems(lambda d: d.pop("imager")))
        self.assertIn("isn't in imager.devices", self.problems(lambda d: d["os_list"][0]["devices"].append("pi2-32bit")))

    def test_no_customisation(self):
        def preseed(d):
            d["os_list"][0]["init_format"] = "rpi-preseed"
        self.assertIn("init_format must be 'none'", self.problems(preseed))

        def unknown(d):
            d["os_list"][0]["init_format"] = "firstrun"
        self.assertIn("isn't one Imager knows", self.problems(unknown))

    def test_imagers_fields(self):
        def upper(d):
            d["os_list"][0]["extract_sha256"] = d["os_list"][0]["extract_sha256"].upper()
        self.assertIn("64 lowercase hex", self.problems(upper))
        self.assertIn("no release_date", self.problems(lambda d: d["os_list"][0].pop("release_date")))

        def packed_size(d):
            d["os_list"][0]["extract_size"] = d["os_list"][0]["image_download_size"]
        self.assertIn("unpacked size", self.problems(packed_size))

        def nested(d):
            d["os_list"][1]["subitems"][0]["subitems"] = []
        self.assertIn("one level of groups", self.problems(nested))

    def test_nothing_the_box_never_says(self):
        def say(d):
            d["os_list"][0]["description"] += " From the Internet Archive."
        self.assertIn("internet archive", self.problems(say))

    @unittest.skipUnless(os.environ.get("SOFA_IMAGER_SCHEMA"), "set SOFA_IMAGER_SCHEMA to Imager's os-list-schema.json")
    def test_imagers_own_schema(self):
        with open(os.environ["SOFA_IMAGER_SCHEMA"]) as f:
            schema = json.load(f)
        self.assertEqual(imager.check(self.doc, schema), [])


class WorkflowAndGuide(unittest.TestCase):
    def read(self, *path):
        with open(os.path.join(HERE, *path), encoding="utf-8") as f:
            return f.read()

    def test_the_workflow_puts_only_the_list_beside_the_card(self):
        wf = self.read(".github", "workflows", "sofa-box-imager-list.yml")
        self.assertIn('workflows: ["Sofa box card", "Sofa box stable card"]', wf,
                      "it runs after every card, and after a version is marked stable")
        self.assertIn("name: Sofa box card\n", self.read(".github", "workflows", "sofa-box-image.yml"))
        self.assertIn("name: Sofa box stable card\n", self.read(".github", "workflows", "sofa-box-stable.yml"))
        self.assertIn("tools/sofa-box-imager-list.py build", wf)
        self.assertIn("tools/sofa-box-imager-list.py check", wf)
        uploads = [l for l in wf.splitlines() if "gh release upload" in l]
        self.assertTrue(uploads)
        for line in uploads:
            self.assertNotIn(".img.xz", line, "the cards are the card workflow's alone")
            self.assertIn("sofa-box.rpi-imager-manifest", line)
        self.assertNotIn("gh release delete", wf)
        self.assertNotIn("DELETE", wf)

    def test_the_schema_is_imagers_own_pinned(self):
        wf = self.read(".github", "workflows", "sofa-box-imager-list.yml")
        m = re.search(r"raw\.githubusercontent\.com/raspberrypi/rpi-imager/([0-9a-f]{40})/doc/json-schema/os-list-schema\.json", wf)
        self.assertTrue(m, "pinned to one commit")
        self.assertRegex(wf, r"[0-9a-f]{64}\s+schema\.json")

    def test_the_guide_opens_the_list(self):
        guide = self.read("deploy", "sofa-box", "README.md")
        self.assertIn("sofa-box.rpi-imager-manifest", guide)
        self.assertIn("https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box.rpi-imager-manifest", guide)
        self.assertIn("App Options", guide)
        self.assertIn('"**(stable)**"', guide, "the guide says which entry to keep")

    def test_the_stable_mark_is_the_one_the_releases_tool_writes(self):
        tool = self.read("tools", "sofa-box-releases.py")
        self.assertIn('TESTING, STABLE = "sofa-box", "sofa-box-stable"', tool)
        self.assertIn(imager.STABLE_MARK.pattern, tool)
