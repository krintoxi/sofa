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

    def card(self, name, raw, digest=None, tag="test"):
        packed = lzma.compress(raw, format=lzma.FORMAT_XZ)
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(packed)
        url = "https://github.com/krintoxi/sofa/releases/download/%s/%s" % (tag, name)
        self.paths[url] = path
        return {"name": name, "size": len(packed), "state": "uploaded", "browser_download_url": url,
                "digest": "sha256:" + (digest or sha(packed)), "updated_at": "2026-11-10T07:38:01Z"}

    @staticmethod
    def release(tag, name, assets, published="2026-11-10T07:38:37Z", draft=False):
        return {"tag_name": tag, "name": name, "draft": draft, "published_at": published,
                "html_url": "https://github.com/krintoxi/sofa/releases/tag/" + tag, "assets": assets}

    def version(self, ver, raw, published="2026-11-10T07:38:37Z"):
        return self.release("box-os-v" + ver, "Sofa Box OS " + ver,
                            [self.card("sofa-box-os-%s.img.xz" % ver, raw, tag="box-os-v" + ver),
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

    def test_a_pc_from_a_usb_stick_has_a_device_and_entries_of_its_own(self):
        """The same Sofa Box OS for a PC (sofa-box-os-X-pc.img.xz beside the card): under a device of its own, so
        Imager offers it only for a PC; marked testing (never tried on a real PC); the Pi's entries as they were."""
        def with_pc(rel, ver, raw):
            rel["assets"].append(self.c.card("sofa-box-os-%s-pc.img.xz" % ver, raw))
            return rel
        pc_new, pc_old = b"PC 1.1.74\n" + bytes(2 << 20), b"PC 1.1.73\n" + bytes(2 << 20)
        rolling = self.c.rolling("1.1.74", self.newest)
        rolling["assets"].append(self.c.card("sofa-box-pc.img.xz", pc_new))
        rels = [with_pc(self.c.version("1.1.74", self.newest), "1.1.74", pc_new),
                with_pc(self.c.version("1.1.73", b"seventy-three" * 99), "1.1.73", pc_old),
                self.c.version("1.1.72", b"seventy-two" * 99), rolling]
        doc = imager.build(rels, {}, keep=3, measure_fn=self.c.measure)
        self.assertEqual(imager.check(doc), [])
        names = [e["name"] for e in doc["os_list"]]
        self.assertEqual(names, ["Sofa Box OS 1.1.74", "Sofa Box OS: earlier versions",
                                 "Sofa Box OS 1.1.74 for a PC (testing)", "Sofa Box OS for a PC: earlier versions"])
        pc = doc["os_list"][2]
        self.assertTrue(pc["url"].endswith("/sofa-box-os-1.1.74-pc.img.xz"))
        self.assertEqual((pc["devices"], pc["architecture"], pc["init_format"]), (["sofa-box-pc-x86_64"], "x86_64", "none"))
        self.assertEqual((pc["extract_size"], pc["extract_sha256"]), (len(pc_new), sha(pc_new)))
        self.assertIn("Not tried on a real PC yet", pc["description"])
        self.assertEqual([x["name"] for x in doc["os_list"][3]["subitems"]], ["Sofa Box OS 1.1.73 for a PC (testing)"])
        self.assertEqual(doc["os_list"][0]["devices"], ["pi5-64bit", "pi4-64bit", "pi3-64bit"])     # (the Pi's, as before)
        self.assertEqual([x["name"] for x in doc["os_list"][1]["subitems"]], ["Sofa Box OS 1.1.73", "Sofa Box OS 1.1.72"])
        devs = doc["imager"]["devices"]
        self.assertEqual([d["name"] for d in devs][-1], "A PC, from a USB stick")
        self.assertEqual(devs[-1]["tags"], ["sofa-box-pc-x86_64"])
        # (the newest PC build is 1.1.74's own file: listed once; a different one is listed as the newest build)
        rolling["assets"][-1] = self.c.card("sofa-box-pc.img.xz", pc_new + b" and a fix")
        doc = imager.build(rels, {}, keep=3, measure_fn=self.c.measure)
        self.assertIn("Sofa Box OS 1.1.74 for a PC, newest build (testing)", [e["name"] for e in doc["os_list"]])
        self.assertEqual(imager.check(doc), [])

    def test_a_dvd_for_sofa_box_imager_only(self):
        """The live DVD (sofa-box-os-X-pc-dvd.iso beside the PC's image): its .iso as it is (size and SHA-256 are
        GitHub's own), under the DVD's tag only, which no device has: Raspberry Pi Imager never offers it."""
        def iso(name, raw):
            path = os.path.join(self.c.dir, name)
            with open(path, "wb") as f:
                f.write(raw)
            url = "https://github.com/krintoxi/sofa/releases/download/test/" + name
            self.c.paths[url] = path
            return {"name": name, "size": len(raw), "state": "uploaded", "browser_download_url": url,
                    "digest": "sha256:" + sha(raw), "updated_at": "2026-11-13T07:38:01Z"}
        new, old = b"DVD 1.1.85\n" + bytes(2048 * 50), b"DVD 1.1.84\n" + bytes(2048 * 40)
        v85, v84 = self.c.version("1.1.85", self.newest), self.c.version("1.1.84", b"eighty-four" * 99)
        v85["assets"].append(iso("sofa-box-os-1.1.85-pc-dvd.iso", new))
        v84["assets"].append(iso("sofa-box-os-1.1.84-pc-dvd.iso", old))
        doc = imager.build([v85, v84], {}, keep=3, measure_fn=self.c.measure)
        self.assertEqual(imager.check(doc), [])
        dvd = [e for e in doc["os_list"] if e.get("devices") == ["sofa-box-pc-dvd"]]
        self.assertEqual([e["name"] for e in dvd], ["Sofa Box OS 1.1.85 for a PC (testing)"])
        self.assertTrue(dvd[0]["url"].endswith("/sofa-box-os-1.1.85-pc-dvd.iso"))
        self.assertEqual((dvd[0]["extract_size"], dvd[0]["image_download_size"], dvd[0]["extract_sha256"]),
                         (len(new), len(new), sha(new)))
        group = doc["os_list"][-1]
        self.assertEqual(group["name"], "Sofa Box OS for a PC on a DVD: earlier versions")
        self.assertEqual([x["name"] for x in group["subitems"]], ["Sofa Box OS 1.1.84 for a PC (testing)"])
        self.assertNotIn("sofa-box-pc-dvd", [t for d in doc["imager"]["devices"] for t in d["tags"]])
        # an .iso without GitHub's digest is read once for it
        del v85["assets"][-1]["digest"]
        raw = lambda url, expect=None: imager.measure_raw(self.c.paths[url], expect)    # noqa: E731
        self.assertEqual(imager.build([v85], {}, measure_fn=self.c.measure, measure_raw_fn=raw)["os_list"][-1]["extract_sha256"],
                         sha(new))
        # the tool's own checks: as it is, an .iso, and the DVD's tag alone
        bad = json.loads(json.dumps(doc))
        e = [x for x in bad["os_list"] if x.get("devices") == ["sofa-box-pc-dvd"]][0]
        e["image_download_size"] -= 1
        e["devices"] = ["sofa-box-pc-dvd", "sofa-box-pc-x86_64"]
        e["url"] = e["url"][:-4] + ".img.xz"
        said = "\n".join(imager.check(bad))
        self.assertIn("burned as it's downloaded", said)
        self.assertIn("the DVD's tag goes alone", said)

    def test_no_pc_device_until_a_release_has_a_pc_image(self):
        doc = imager.build([self.c.version("1.1.73", self.newest)], {}, measure_fn=self.c.measure)
        self.assertEqual([d["name"] for d in doc["imager"]["devices"]], ["Raspberry Pi 5", "Raspberry Pi 4", "Raspberry Pi 3"])
        self.assertEqual(imager.check(doc), [])                    # (a device with nothing listed for it is refused)

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


class RaspberryPisList(unittest.TestCase):
    """The sublist Raspberry Pi's own list in Imager would read from us (os_list alone, the stable card only), its own
    checks, and the preview laid out as their list would show it."""

    def setUp(self):
        self.c = Cards()
        self.addCleanup(self.c.close)
        self.card = b"Sofa Box OS 1.1.54\n" + bytes(3 << 20) + b"end"
        self.v54 = self.c.version("1.1.54", self.card)
        self.v54["assets"].append(self.c.card("sofa-box-os-1.1.54-pc.img.xz", b"PC 1.1.54\n" + bytes(1 << 20)))
        self.v58 = self.c.version("1.1.58", b"newer" * 1000)
        self.rels = [self.c.rolling("1.1.58", b"newer, and a fix" * 1000), self.v58, self.c.stable(self.v54), self.v54,
                     self.c.version("1.1.49", b"older" * 1000)]

    def test_the_stable_card_alone(self):
        sub = imager.sublist(self.rels, {}, measure_fn=self.c.measure)
        self.assertEqual(imager.check(sub, sublist=True), [])
        self.assertEqual(list(sub), ["os_list"], "the boards are Raspberry Pi's: no imager block")
        self.assertEqual(len(sub["os_list"]), 1, "not the testing version, the newest build, a PC's or an earlier one")
        e = sub["os_list"][0]
        self.assertEqual(e["name"], "Sofa Box OS 1.1.54")
        self.assertTrue(e["url"].endswith("/releases/download/box-os-v1.1.54/sofa-box-os-1.1.54.img.xz"),
                        "the version's own card, whose file never changes")
        self.assertEqual((e["extract_size"], e["extract_sha256"]), (len(self.card), sha(self.card)))
        self.assertEqual(e["image_download_sha256"], self.v54["assets"][0]["digest"][len("sha256:"):])
        self.assertEqual(e["image_download_size"], self.v54["assets"][0]["size"])
        self.assertEqual((e["init_format"], e["capabilities"], e["architecture"]), ("none", [], "armv8"))
        self.assertEqual(e["devices"], ["pi5-64bit", "pi4-64bit", "pi3-64bit"])
        self.assertEqual(e["icon"], imager.ICON_40)
        self.assertIn("For a Raspberry Pi 3 B+, 4 or 5, built on Raspberry Pi OS Lite (64-bit).", e["description"])
        self.assertIn("tried on a real box", e["description"])
        # the card already measured for our own list isn't unpacked again
        cache = {}
        imager.build(self.rels, cache, measure_fn=self.c.measure)
        self.assertEqual(imager.sublist(self.rels, cache, measure_fn=no_unpacking), sub)

    def test_nothing_while_no_version_is_stable(self):
        for mark in (self.c.stable(), self.c.stable(self.v54, digest="0" * 64)):
            rels = [r for r in self.rels if r["tag_name"] != "sofa-box-stable"] + [mark]
            with self.assertRaises(imager.NoStable):
                imager.sublist(rels, {}, measure_fn=self.c.measure)
        self.assertTrue(issubclass(imager.NoStable, imager.ListError))

    def test_fewer_boards(self):
        e = imager.sublist(self.rels, {}, measure_fn=self.c.measure, devices=["pi3-64bit"])["os_list"][0]
        self.assertEqual(e["devices"], ["pi3-64bit"])
        self.assertIn("For a Raspberry Pi 3 B+, built on", e["description"])
        e = imager.sublist(self.rels, {}, measure_fn=self.c.measure, devices=["pi3-64bit", "pi5-64bit"])["os_list"][0]
        self.assertEqual(e["devices"], ["pi5-64bit", "pi3-64bit"])
        self.assertIn("For a Raspberry Pi 3 B+ or 5,", e["description"])
        for wrong in (["pi2-32bit"], ["pi3-32bit"], ["sofa-box-pc-x86_64"]):
            with self.assertRaisesRegex(imager.ListError, "the card's boards"):
                imager.sublist(self.rels, {}, measure_fn=self.c.measure, devices=wrong)

    def test_its_own_checks(self):
        good = imager.sublist(self.rels, {}, measure_fn=self.c.measure)

        def problems(change):
            doc = json.loads(json.dumps(good))
            change(doc["os_list"][0])
            return "\n".join(imager.check(doc, sublist=True))

        doc = json.loads(json.dumps(good))
        doc["imager"] = {"devices": imager.DEVICES}
        self.assertIn("os_list alone", "\n".join(imager.check(doc, sublist=True)))
        cases = [
            (lambda e: e.update(name="Sofa Box OS 1.1.58 (testing)"), "only the stable card"),
            (lambda e: e.update(url="https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box.img.xz"),
             "numbered card's own file"),
            (lambda e: e.update(url=e["url"].replace("1.1.54.img.xz", "1.1.54-pc.img.xz")), "numbered card's own file"),
            (lambda e: e.update(url=e["url"].replace("box-os-v1.1.54/", "box-os-v1.1.58/")), "numbered card's own file"),
            (lambda e: e["devices"].append("sofa-box-pc-x86_64"), "isn't one of the card's boards"),
            (lambda e: e["devices"].append("pi2-32bit"), "isn't one of the card's boards"),
            (lambda e: e.pop("image_download_sha256"), "image_download_sha256"),
            (lambda e: e.update(init_format="rpi-preseed"), "init_format must be 'none'"),
            (lambda e: e.update(capabilities=["user_required"]), "capabilities must be empty"),
            (lambda e: e.update(architecture="x86_64"), "architecture must be armv8"),
        ]
        for change, said in cases:
            self.assertIn(said, problems(change))
        # our own list is no sublist (it has the boards, testing versions and a PC's image), and stays as it was
        own = imager.build(self.rels, {}, measure_fn=self.c.measure)
        self.assertEqual(imager.check(own), [])
        self.assertIn("os_list alone", "\n".join(imager.check(own, sublist=True)))
        self.assertFalse(any("image_download_sha256" in e or "capabilities" in e for e in own["os_list"]))

    def test_the_preview_is_laid_out_as_raspberry_pis_list(self):
        p = imager.preview()
        devs = p["imager"]["devices"]
        self.assertEqual([d["name"] for d in devs],
                         ["Raspberry Pi 5", "Raspberry Pi 4", "Raspberry Pi 3", "Raspberry Pi 2", "Raspberry Pi 1",
                          "Raspberry Pi Zero 2 W", "Raspberry Pi Zero", "No filtering"])
        self.assertNotIn("default", devs[0], "the Pi 5 is their default board")
        self.assertTrue(all(d["default"] is False for d in devs[1:]))
        zero2 = [d for d in devs if d["name"] == "Raspberry Pi Zero 2 W"][0]
        self.assertIn("pi3-64bit", zero2["tags"], "the Zero 2 W shares the Pi 3's tags in Raspberry Pi's list")
        [cat] = p["os_list"]
        self.assertEqual(cat["name"], imager.LISTING["category"])
        [entry] = cat["subitems"]
        self.assertEqual(entry, {"name": "Sofa Box OS", "description": imager.LISTING["description"],
                                 "icon": imager.ICON_40, "website": imager.LISTING["website"],
                                 "subitems_url": imager.SUBLIST_URL})
        self.assertEqual(imager.preview("https://example.test/s.json")["os_list"][0]["subitems"][0]["subitems_url"],
                         "https://example.test/s.json")
        with open(os.path.join(HERE, "docs", "launch", "sofa-box-imager-preview.rpi-imager-manifest"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), p, "the preview in docs/launch is the tool's own (preview --out …)")

    def test_the_icon_is_40_by_40(self):
        self.assertTrue(imager.ICON_40.startswith("https://raw.githubusercontent.com/krintoxi/sofa/main/"))
        path = os.path.join(HERE, *imager.ICON_40.split("/main/", 1)[1].split("/"))
        with open(path, "rb") as f:
            head = f.read(24)
        self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")), (40, 40))
        self.assertLess(os.path.getsize(path), 8192, "lightweight, as Raspberry Pi asks")

    def test_the_command_line(self):
        real = imager.measure
        imager.measure = lambda url, expect=None: real(self.c.paths[url], expect)
        self.addCleanup(setattr, imager, "measure", real)
        r, cache, out, sub, view = (os.path.join(self.c.dir, n) for n in
                                    ("releases.json", "cache.json", "list.rpi-imager-manifest", "sub.json", "view.json"))
        said = io.StringIO()
        with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said):
            with open(r, "w") as f:
                json.dump(self.rels, f)
            self.assertEqual(imager.main(["build", "--releases", r, "--cache", cache, "--out", out, "--sublist", sub,
                                          "--boards", "pi3-64bit"]), 0)
            self.assertEqual(imager.main(["check", sub, "--sublist"]), 0)
            self.assertEqual(imager.main(["check", out, "--sublist"]), 1, "our own list isn't a sublist")
            self.assertEqual(imager.main(["preview", "--out", view]), 0)
        with open(sub) as f:
            self.assertEqual(json.load(f)["os_list"][0]["devices"], ["pi3-64bit"])
        with open(view) as f:
            self.assertEqual(json.load(f), imager.preview())
        self.assertIn("Raspberry Pi's list: Sofa Box OS 1.1.54", said.getvalue())
        # while no version is stable: our own list as always, and no sublist
        os.remove(sub)
        with open(r, "w") as f:
            json.dump([x for x in self.rels if x["tag_name"] != "sofa-box-stable"], f)
        said = io.StringIO()
        with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said):
            self.assertEqual(imager.main(["build", "--releases", r, "--cache", cache, "--out", out, "--sublist", sub]), 0)
        self.assertFalse(os.path.exists(sub))
        self.assertIn("No sublist for Raspberry Pi's list", said.getvalue())


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
            self.assertTrue("sofa-box.rpi-imager-manifest" in line or 'pub/next-$N"' in line, line)
        self.assertNotIn("gh release delete", wf)
        # Only the sublist's own step removes anything: its leftovers (next-, old-) and the old file it just renamed
        step = wf[wf.index("- name: Put the sublist for Raspberry Pi's own list"):]
        self.assertIn("N=%s\n" % imager.SUBLIST, step)
        self.assertEqual(wf.count("N="), 1, "one name, the sublist's")
        deletes = [l.strip() for l in wf.splitlines() if "DELETE" in l]
        self.assertEqual(deletes, [
            'for id in $(ids "next-$N") $(ids "old-$N"); do gh api -X DELETE "$R/assets/$id"; done   '
            '# left from a run that stopped',
            'if [ -n "$OLD" ]; then gh api -X DELETE "$R/assets/$OLD"; fi'])
        self.assertTrue(all(l.strip() in step for l in deletes))
        self.assertIn('OLD="$(ids "$N")"', step)
        self.assertLess(step.index('-f name="$N"'), step.index('gh api -X DELETE "$R/assets/$OLD"'),
                        "the new file has the name before the old one goes")

    def test_the_workflow_makes_and_checks_the_sublist(self):
        wf = self.read(".github", "workflows", "sofa-box-imager-list.yml")
        self.assertIn("--sublist pub/%s" % imager.SUBLIST, wf)
        self.assertIn("pub/%s --sublist --schema schema.json" % imager.SUBLIST, wf)
        self.assertTrue(imager.SUBLIST_URL.endswith("/releases/download/sofa-box/" + imager.SUBLIST))

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

    def test_the_request_for_raspberry_pis_list(self):
        """The drafted request (docs/launch): the form's answers are the tool's own, its JSON is what the tool makes
        and passes the sublist's checks, and it says the trademark line."""
        doc = self.read("docs", "launch", "raspberry-pi-imager-listing.md")
        self.assertIn("https://forms.gle/U6JkxVfhHkn5ok2X7", doc)
        for k in ("category", "name", "description", "icon", "website"):
            self.assertIn("`%s`" % imager.LISTING[k], doc, k)
        self.assertIn("`%s`" % imager.SUBLIST_URL, doc)
        self.assertIn("Raspberry Pi is a trademark of Raspberry Pi Ltd", doc)
        self.assertIn("Nothing has been sent", doc)
        blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)```", doc, re.S)]
        entry, subs = blocks[0], blocks[1:]
        self.assertEqual(entry, {k: v for k, v in imager.preview()["os_list"][0]["subitems"][0].items()})
        self.assertEqual(len(subs), 2)
        for s in subs:
            self.assertEqual(imager.check(s, sublist=True), [])
        self.assertEqual([s["os_list"][0]["devices"] for s in subs], [imager.BOARD_TAGS, ["pi3-64bit"]])
        self.assertNotRegex(doc.lower(), r"open[- ]source")
        # what the guide says about Raspberry Pi's list
        guide = self.read("docs", "raspberry-pi-imager.md")
        self.assertIn(imager.SUBLIST_URL, guide)
        self.assertIn("launch/raspberry-pi-imager-listing.md", guide)
        self.assertIn("`1ae2398`", guide, "Imager's main has user_required now")
        self.assertNotIn("There's no `user_required`", guide)
        self.assertIn("Raspberry Pi is a trademark of Raspberry Pi Ltd", self.read("TRADEMARKS.md"))
        self.assertIn("Raspberry Pi is a\ntrademark of Raspberry Pi Ltd", self.read("README.md"))

    def test_the_stable_mark_is_the_one_the_releases_tool_writes(self):
        tool = self.read("tools", "sofa-box-releases.py")
        self.assertIn('TESTING, STABLE = "sofa-box", "sofa-box-stable"', tool)
        self.assertIn(imager.STABLE_MARK.pattern, tool)
