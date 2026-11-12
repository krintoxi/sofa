"""The Sofa box on hardware that isn't a Raspberry Pi (docs/hardware.md): install.sh tells a Pi from the rest and only
then runs other-hardware.sh; that script adds Debian's parts (VA-API, firmware, CEC through a USB adapter) and nothing
of the Pi's; the agent and the home page cope without the Pi's power and heat record; `sofa-box widevine` is the chosen
step it says it is; the x86-64 image is built and booted on GitHub as the card is built, and the workflow can publish
nothing; the hardware guide holds the three tables."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(HERE, "deploy", "sofa-box")
TOOLS = os.path.join(HERE, "tools")
DOC = os.path.join(HERE, "docs", "hardware.md")


def read(*parts):
    with open(os.path.join(HERE, *parts), encoding="utf-8") as f:
        return f.read()


def shell_function(script, name):
    """The body of a sh function `name() { … }` from a script, with the `}` that closes it (first column)."""
    m = re.search(r"(?ms)^%s\(\) \{\n(.*?)^\}" % re.escape(name), script)
    assert m, "no function %s" % name
    return m.group(1)


class TellingAPiFromTheRest(unittest.TestCase):
    """install.sh: is_pi() says yes for a Pi's boot files, its apt archive, its name in the device tree or its tools (a
    card being built has no boot files yet, but has the archive); no for a plain Debian PC. SOFA_BOX_HARDWARE overrides."""

    def run_is_pi(self, root, boot="", hardware=""):
        install = read("deploy", "sofa-box", "install.sh")
        body = shell_function(install, "is_pi")
        case = install.split('case "${SOFA_BOX_HARDWARE:-}" in', 1)[1].split("esac", 1)[0]
        script = 'BOOT="%s"\nis_pi() {\n%s}\ncase "${SOFA_BOX_HARDWARE:-}" in%sesac\necho "OTHER=$OTHER"\n' % (boot, body, case)
        env = dict(os.environ, SOFA_BOX_ROOT=root)
        if hardware:
            env["SOFA_BOX_HARDWARE"] = hardware
        out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env, check=True).stdout
        return out.strip() == "OTHER="

    def test_a_pi_and_a_card_being_built(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        self.assertFalse(self.run_is_pi(root), "an empty system is not a Pi")
        self.assertTrue(self.run_is_pi(root, boot="/boot/firmware"), "config.txt found: a Pi")
        os.makedirs(os.path.join(root, "etc", "apt", "sources.list.d"))
        open(os.path.join(root, "etc", "apt", "sources.list.d", "raspi.list"), "w").close()
        self.assertTrue(self.run_is_pi(root), "Raspberry Pi OS's apt archive: a Pi (a card being built, before its boot files)")
        os.remove(os.path.join(root, "etc", "apt", "sources.list.d", "raspi.list"))
        os.makedirs(os.path.join(root, "proc", "device-tree"))
        with open(os.path.join(root, "proc", "device-tree", "model"), "w") as f:
            f.write("Raspberry Pi 3 Model B Plus Rev 1.3\0")
        self.assertTrue(self.run_is_pi(root), "the device tree names a Pi")
        os.remove(os.path.join(root, "proc", "device-tree", "model"))
        os.makedirs(os.path.join(root, "usr", "lib", "userconf-pi"))
        self.assertTrue(self.run_is_pi(root), "Raspberry Pi OS's own tools: a Pi")

    def test_by_hand(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        self.assertTrue(self.run_is_pi(root, hardware="pi"))
        self.assertFalse(self.run_is_pi(root, boot="/boot/firmware", hardware="other"))

    def test_the_pi_path_is_untouched(self):
        """Everything new in install.sh for other hardware is inside the one `if [ -n "$OTHER" ]` block, which calls the
        sibling script; the apt lines, units and files a Pi gets are the same as before (no new apt-get install outside it)."""
        install = read("deploy", "sofa-box", "install.sh")
        self.assertEqual(install.count('if [ -n "$OTHER" ]; then'), 1)
        block = install.split('if [ -n "$OTHER" ]; then', 1)[1].split("\nfi\n", 1)[0]
        self.assertIn('SOFA_BOX_USER="$WHO" SOFA_BOX_HOME="$HOMEDIR" sh "$LIB/other-hardware.sh" ${IMAGE:+--image}', block)
        code = "\n".join(l for l in install.replace(block, "").splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("other-hardware.sh", code)
        self.assertNotIn("apt-get", block)                                     # (the packages live in the sibling script)
        for word in ("vainfo", "va-driver", "chromium.d", "pulse8", "inputattach", "firmware-"):
            self.assertNotIn(word, install, "%s belongs in other-hardware.sh, not on the Pi's path" % word)
        # the block runs after the box's files are copied (so the script is there) and before the services are enabled
        self.assertLess(install.index('(cd "$HERE" && tar cf -'), install.index('if [ -n "$OTHER" ]; then'))
        self.assertLess(install.index('if [ -n "$OTHER" ]; then'), install.index("systemctl daemon-reload"))
        subprocess.run(["sh", "-n", os.path.join(BOX, "install.sh")], check=True)
        subprocess.run(["sh", "-n", os.path.join(BOX, "other-hardware.sh")], check=True)
        subprocess.run(["sh", "-n", os.path.join(BOX, "sofa-box")], check=True)


class DebiansParts(unittest.TestCase):
    """other-hardware.sh adds what Debian has in place of the Pi's parts, each on its own (one missing package stops
    nothing), and never a Pi package."""

    def setUp(self):
        self.script = read("deploy", "sofa-box", "other-hardware.sh")

    def test_va_api_for_mpv_and_chromium(self):
        for p in ("vainfo", "mesa-va-drivers", "intel-media-va-driver", "i965-va-driver"):
            self.assertIn(p, self.script)
        self.assertIn("/etc/chromium.d/sofa-box", self.script)                      # Debian's chromium reads its flags there
        self.assertIn("VaapiVideoDecodeLinuxGL", self.script)
        self.assertIn('for p in "$@"; do apt-get install', self.script)             # one at a time
        self.assertNotIn("libwidevinecdm0", self.script)
        self.assertNotIn("raspberrypi", self.script.lower().replace("not a raspberry pi", "").replace("raspberry pi", ""))

    def test_chromiums_crash_folder(self):
        """Debian 13's Chromium 156 dies at its start without ~/.config/chromium/Crash Reports (seen in the VM with strace):
        the folder is made for the box's user, and only there."""
        self.assertIn('"$HOMEDIR/.config/chromium/Crash Reports"', self.script)
        self.assertIn("install -d -o \"$WHO\"", self.script)
        self.assertNotIn("Crash Reports", read("deploy", "sofa-box", "sofa-box"))          # (the Pi's session as it was)

    def test_cec_only_through_an_adapter(self):
        self.assertIn("ConditionPathExistsGlob=/dev/cec*", self.script)
        self.assertIn("sofa-box-cec.service.d/other-hardware.conf", self.script)     # a drop-in: the Pi's unit as it is
        self.assertIn('ATTRS{idVendor}=="2548"', self.script)                        # Pulse-Eight
        self.assertIn("inputattach --pulse8-cec /dev/%I", self.script)
        self.assertIn('SUBSYSTEM=="cec", TAG+="systemd", ENV{SYSTEMD_WANTS}+="sofa-box-cec.service"', self.script)

    def test_firmware_only_where_apt_has_it(self):
        self.assertIn("apt-cache policy firmware-misc-nonfree", self.script)
        self.assertIn("firmware-iwlwifi", self.script)

    def test_the_doctor_says_what_a_pc_decodes(self):
        box = read("deploy", "sofa-box", "sofa-box")
        doctor = shell_function(box, "doctor")
        pc = doctor.split("  else                       # a PC", 1)[1]
        self.assertIn("vainfo --display drm", pc)
        self.assertIn("videos decode on the processor", pc)
        self.assertIn("no Widevine", pc)
        pi = doctor.split("  else                       # a PC", 1)[0]
        self.assertIn("the Pi's video decoder (H.264) for mpv", pi)                 # the Pi's checks as they were


class Widevine(unittest.TestCase):
    """`sofa-box widevine`: x86-64 only, from Google Chrome's own package, only when asked, into where Chromium looks."""

    def setUp(self):
        self.box = read("deploy", "sofa-box", "sofa-box")
        self.fn = shell_function(self.box, "widevine")

    def test_only_when_asked_and_only_x86(self):
        self.assertIn("  widevine) widevine ;;", self.box)
        self.assertNotIn("widevine", read("deploy", "sofa-box", "install.sh").lower().split("# the browser's rules", 1)[1]
                         .split("mkdir -p \"$HOMEDIR/Downloads\"", 1)[0])
        self.assertNotIn("sofa-box widevine", read("deploy", "sofa-box", "install.sh").split("say \"Installing", 1)[1].split("Done.", 1)[0])
        self.assertIn('[ "$ARCH" = amd64 ] || [ "$ARCH" = x86_64 ] ||', self.fn)
        self.assertIn("google-chrome-stable_current_amd64.deb", self.box)
        self.assertIn("https://www.google.com/chrome/terms/", self.fn)

    def test_where_it_goes(self):
        self.assertIn("/usr/lib/chromium/WidevineCdm", self.fn)
        self.assertIn('.config/sofa-box/browser/WidevineCdm/$VER', self.fn)
        self.assertIn("latest-component-updated-widevine-cdm", self.fn)
        self.assertIn("_platform_specific/linux_x64/libwidevinecdm.so", self.fn)
        self.assertIn("dpkg-deb -x", self.fn)

    def test_a_stand_in_package(self):
        """With a package of our own (SOFA_BOX_CHROME_DEB), the files land where Chromium looks, owned by the box's user."""
        if not shutil.which("dpkg-deb") or sys.platform == "darwin":
            self.skipTest("needs dpkg-deb on Linux")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        pkg = os.path.join(tmp, "pkg")
        cdm = os.path.join(pkg, "opt", "google", "chrome", "WidevineCdm")
        os.makedirs(os.path.join(cdm, "_platform_specific", "linux_x64"))
        os.makedirs(os.path.join(pkg, "DEBIAN"))
        with open(os.path.join(cdm, "manifest.json"), "w") as f:
            json.dump({"version": "4.10.2891.0"}, f)
        with open(os.path.join(cdm, "_platform_specific", "linux_x64", "libwidevinecdm.so"), "wb") as f:
            f.write(b"\x7fELF-not-really")
        with open(os.path.join(pkg, "DEBIAN", "control"), "w") as f:
            f.write("Package: fake-chrome\nVersion: 1\nArchitecture: all\nMaintainer: test\nDescription: a stand-in\n")
        subprocess.run(["dpkg-deb", "-b", pkg, os.path.join(tmp, "chrome.deb")], check=True, capture_output=True)
        # the function as a script, with the paths it writes to pointed at the folder (root isn't needed then)
        home = os.path.join(tmp, "home")
        os.makedirs(os.path.join(home, ".config", "sofa-box", "browser"))
        fn = self.fn.replace('"/usr/lib/chromium/WidevineCdm"', '"%s/usr/lib/chromium/WidevineCdm"' % tmp) \
            .replace("systemctl try-restart sofa-box", "true").replace('chown -R "$WHO:"', "true")
        script = 'set -e\nCHROME_DEB="file://%s/chrome.deb"\nwidevine() {\n%s}\nwidevine\n' % (tmp, fn)
        fake = os.path.join(tmp, "bin")
        os.makedirs(fake)
        with open(os.path.join(fake, "getent"), "w") as f:
            f.write("#!/bin/sh\necho 'sofabox:x:1001:1001::%s:/bin/sh'\n" % home)
        with open(os.path.join(fake, "systemctl"), "w") as f:
            f.write("#!/bin/sh\necho sofabox\n")
        for n in ("getent", "systemctl"):
            os.chmod(os.path.join(fake, n), 0o755)
        env = dict(os.environ, PATH=fake + ":" + os.environ["PATH"])
        out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(os.path.exists(os.path.join(tmp, "usr", "lib", "chromium", "WidevineCdm", "_platform_specific", "linux_x64", "libwidevinecdm.so")))
        self.assertTrue(os.path.exists(os.path.join(home, ".config", "sofa-box", "browser", "WidevineCdm", "4.10.2891.0", "manifest.json")))
        with open(os.path.join(home, ".config", "sofa-box", "browser", "WidevineCdm", "latest-component-updated-widevine-cdm")) as f:
            self.assertIn("4.10.2891.0", json.load(f)["Path"])
        self.assertIn("Widevine 4.10.2891.0 is in place", out.stdout)


class WithoutThePisRecord(unittest.TestCase):
    """The agent on a PC: no vcgencmd (the power watch stops quietly, Home shows no note), the board is "this computer",
    About says which system it's built on."""

    @classmethod
    def setUpClass(cls):
        cls.conf = tempfile.mkdtemp()
        old = {k: os.environ.get(k) for k in ("SOFA_BOX_CONF", "SOFA_BOX_DEVTOOLS", "SOFA_BOX_CAPTIVE_PORT", "SOFA_BOX_UINPUT")}
        os.environ.update(SOFA_BOX_CONF=cls.conf, SOFA_BOX_DEVTOOLS="0", SOFA_BOX_CAPTIVE_PORT="0", SOFA_BOX_UINPUT="0")
        try:
            spec = importlib.util.spec_from_file_location("sofa_box_agent_other_hardware", os.path.join(BOX, "sofa-box-agent.py"))
            cls.agent = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.agent)
        finally:
            for k, v in old.items():
                os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.conf, True)

    def test_no_power_record_no_note(self):
        a = self.agent
        real = a.run
        a.run = lambda cmd, timeout=10, **kw: (127, "") if cmd[:1] == ["vcgencmd"] else real(cmd, timeout, **kw)
        try:
            with mock.patch.object(a.time, "sleep"):          # (the module is everyone's: patched and put back)
                a.watch_power()                               # returns at once: not a Pi
        finally:
            a.run = real
        self.assertIsNone(a.power["note"])
        self.assertIn("power", a.box_info())
        self.assertIsNone(a.box_info()["power"])
        self.assertIn("powerLine()", read("deploy", "sofa-box", "home", "home.js"))
        self.assertIn("if (!powerShown.done && !powerShown.note && data.power)", read("deploy", "sofa-box", "home", "home.js"))

    def test_this_computer_and_its_system(self):
        a = self.agent
        if a.board()["gen"]:
            self.skipTest("running on a Raspberry Pi")
        self.assertEqual(a.board()["model"], "this computer")
        self.assertFalse(a.slow_board())
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(os.path.join(tmp, "os-release"), "w") as f:
            f.write('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nNAME="Debian GNU/Linux"\nID=debian\n')
        os.environ["SOFA_BOX_OS_RELEASE"] = os.path.join(tmp, "os-release")
        try:
            self.assertEqual(a.os_name(), "Debian GNU/Linux 13 (trixie)")
            self.assertEqual(a.box_info()["os"], "Debian GNU/Linux 13 (trixie)")
        finally:
            del os.environ["SOFA_BOX_OS_RELEASE"]
        home = read("deploy", "sofa-box", "home", "home.js")
        self.assertIn('Built on ${esc(b.os || "Raspberry Pi OS")}', home)
        # the games that need a Pi generation: any other computer is up to it (gen 0)
        self.assertIn("return gen == 0 or gen >= g.get(\"pi\", 3)", read("deploy", "sofa-box", "sofa-box-agent.py"))


class TheImageAndItsBoot(unittest.TestCase):
    """tools/build-sofa-box-vm-image.sh: Debian 13 from Debian's own archive with its key checked, install.sh run as the
    card's build runs it, GRUB for BIOS and UEFI, a root that grows; tools/boot-sofa-box-vm.sh boots a copy in QEMU and
    the in-VM checks print what the workflow greps; the workflow builds on push to the branch and by hand, reads only,
    keeps artifacts a week and publishes no release."""

    def test_the_build_is_the_cards_build(self):
        build = read("tools", "build-sofa-box-vm-image.sh")
        card = read("tools", "build-sofa-box-image.sh")
        self.assertIn("SOFA_BOX_USER=sofabox sh /tmp/sofa/deploy/sofa-box/install.sh --image $SOFA", build)
        self.assertIn("SOFA_BOX_USER=sofabox sh /tmp/sofa/deploy/sofa-box/install.sh --image $SOFA", card)
        self.assertIn('cp -r "$REPO/client" "$REPO/sofa" "$REPO/sofa.py" "$REPO/LICENSE" "$ROOT/tmp/sofa/"', build)   # Sofa itself, for "This box"
        self.assertIn("policy-rc.d", build)
        self.assertIn("mmdebstrap --arch=amd64", build)
        self.assertIn("non-free-firmware", build)
        self.assertIn('[ "$(uname -m)" = x86_64 ]', build)
        # Debian's key: the host's, or the pinned package checked against its SHA-256
        pin = read("tools", "debian-archive-keyring.txt")
        self.assertRegex(pin, r"(?m)^url=https://deb\.debian\.org/debian/pool/main/d/debian-archive-keyring/debian-archive-keyring_[0-9.]+_all\.deb$")
        self.assertRegex(pin, r"(?m)^sha256=[0-9a-f]{64}$")
        self.assertIn("sha256sum -c -", build)
        # BIOS and UEFI from one GPT disk, and a root that grows
        self.assertIn("type=21686148-6449-6E6F-744E-656564454649", build)                 # BIOS boot partition
        self.assertIn("type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B", build)                 # EFI system partition
        self.assertIn("type=4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709", build)                 # x86-64 root (systemd-repart's)
        self.assertIn("grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=sofabox --removable --no-nvram", build)
        self.assertIn("grub-install --target=i386-pc", build)
        self.assertIn("x-systemd.growfs", build)
        self.assertIn("/etc/repart.d/50-root.conf", build)
        self.assertIn("quiet splash plymouth.ignore-serial-consoles logo.nologo vt.global_cursor_default=0 loglevel=3 console=tty3", build)
        # no shared secrets: SSH keys at the first start, an empty machine-id, the games whose data isn't free never on it
        self.assertIn('rm -f "$ROOT/etc/ssh/ssh_host_"*', build)
        self.assertIn("ssh-keygen -A", build)
        self.assertIn(": > /etc/machine-id", build)
        self.assertIn("for p in $NONFREE; do", build)
        self.assertIn('"$NAME.qcow2.xz"', build)
        self.assertIn('"$NAME.img.xz"', build)
        for f in ("build-sofa-box-vm-image.sh", "boot-sofa-box-vm.sh", "sofa-box-vm-proof.sh"):
            subprocess.run(["sh", "-n", os.path.join(TOOLS, f)], check=True)
            self.assertTrue(os.access(os.path.join(TOOLS, f), os.X_OK), f + " isn't executable")
        self.assertTrue(os.access(os.path.join(BOX, "other-hardware.sh"), os.X_OK))

    def test_the_boot_proves_what_the_docs_claim(self):
        boot = read("tools", "boot-sofa-box-vm.sh")
        proof = read("tools", "sofa-box-vm-proof.sh")
        self.assertIn("console=ttyS0,115200n8", boot)                                     # the log is the serial port
        self.assertIn("sofa-box-vm-proof.service", boot)
        self.assertIn("-drive if=pflash", boot)                                           # UEFI with OVMF
        self.assertIn("hostfwd=tcp:127.0.0.1:18092-:8092", boot)                          # the phone remote, from outside
        self.assertIn("SOFA-BOX-PROOF .*: fail", boot)
        for what in ("agent:", "home api:", "home page:", "sofa:", "screen:", "phone remote:", "done"):
            self.assertIn('say "%s' % what, proof)
        self.assertIn("/box/api/info", proof)
        self.assertIn("/api/info", proof)
        self.assertIn("Host: box.localhost", proof)                                       # starts Sofa on the box
        self.assertIn("http://127.0.0.1:9222/json/version", proof)                        # the TV's screen is up
        self.assertIn("systemctl poweroff", proof)

    def test_the_workflow(self):
        wf = read(".github", "workflows", "sofa-box-vm.yml")
        self.assertIn("runs-on: ubuntu-24.04", wf)
        self.assertIn("permissions:\n  contents: read", wf)
        self.assertIn("workflow_dispatch:", wf)
        self.assertIn('branches: ["other-hardware"]', wf)
        self.assertIn("sudo tools/build-sofa-box-vm-image.sh out", wf)
        self.assertIn("--firmware uefi", wf)
        self.assertIn("--firmware bios", wf)
        self.assertIn("actions/upload-artifact@v4", wf)
        self.assertIn("retention-days: 7", wf)
        self.assertIn("out/boot/*.log", wf)
        for word in ("gh release", "softprops", "release:"):
            self.assertNotIn(word, wf)
        self.assertIn("99-kvm4all.rules", wf)


class TheHardwareGuide(unittest.TestCase):
    """docs/hardware.md: the Pi assumptions table, the boards table with sources and dates, and the capabilities matrix
    with every box capability against every platform, Works / Partly / No / Untested."""

    def setUp(self):
        self.doc = read("docs", "hardware.md")

    def test_the_assumptions_table(self):
        part = self.doc.split("## 2.", 1)[0]
        self.assertIn("| Assumption", part)
        for a in ("config.txt", "cmdline.txt", "vcgencmd", "libwidevinecdm0", "rpi-eeprom", "v4l2m2m", "userconf-pi", "cloud-init",
                  "raspi-config", "hotspot", "/dev/cec", "Bluetooth", "`pi` user", "zram", "home.js"):
            self.assertIn(a, part, a)

    def test_the_boards_table(self):
        part = self.doc.split("## 4.", 1)[1].split("## 5.", 1)[0]
        for b in ("Orange Pi 5", "Orange Pi 3B", "ROCK 5", "ZERO 3", "Libre Computer", "Banana Pi", "Android TV box", "NUC", "Apple Silicon"):
            self.assertIn(b, part, b)
        self.assertIn("| Board", part)
        self.assertRegex(part, r"20\d\d-\d\d-\d\d")                                  # dated
        self.assertIn("https://", part)                                              # sourced
        self.assertIn("community, untested", part.lower())

    def test_the_matrix(self):
        part = self.doc.split("## 5.", 1)[1]
        head = next(line for line in part.splitlines() if line.startswith("| Capability"))
        for col in ("Pi 3 B+", "Pi 4", "Pi 5", "x86-64 PC", "VM"):
            self.assertIn(col, head)
        rows = [line.split("|")[1].strip() for line in part.splitlines() if line.startswith("| ") and not line.startswith("| Capability")]
        for cap in ("home screen", "Sofa", "Live TV", "without DRM", "with DRM", "Games, the box's own pages", "Games, native", "Phone remote",
                    "Controllers", "CEC", "Bluetooth", "USB", "DVD", "hotspot", "Updates"):
            self.assertTrue(any(cap.lower() in r.lower() for r in rows), cap)
        cells = re.findall(r"\| (Works|Partly|No|Untested)\b", part)
        self.assertGreater(len(cells), 60)
        self.assertIn("Untested", cells)                                             # only what's proven is claimed


if __name__ == "__main__":
    unittest.main()
