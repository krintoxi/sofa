"""The image-gen prototype (tools/image-gen): Sofa Box OS built with Raspberry Pi's rpi-image-gen, beside
tools/build-sofa-box-image.sh. Its workflow can't publish anything and pins rpi-image-gen to a commit; the box is set
up by its own installer, not a copy; the box's own boot settings land on the config.txt and cmdline.txt rpi-image-gen
puts together; and the card reader (inspect-card.py) reads FAT, dpkg's list and systemd's links."""
import importlib.util
import os
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(HERE, "tools", "image-gen")
LAYER_D = os.path.join(GEN, "layer", "sofa-box-os.d")
WORKFLOW = os.path.join(HERE, ".github", "workflows", "sofa-box-image-gen.yml")


def read(*path):
    with open(os.path.join(*path)) as f:
        return f.read()


_spec = importlib.util.spec_from_file_location("inspect_card", os.path.join(GEN, "inspect-card.py"))
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)

# config.txt and cmdline.txt as rpi-image-gen (v2.9.0) puts them together for this card: rpi-device-base's,
# rpi-linux-base's and the security policy's fragments, then the sofa-box-os layer's own (arm_64bit=1; resize).
CONFIG = """# Assembled by rpi-image-gen from layer fragments.
# See http://rptl.io/configtxt

# Run as fast as firmware / board allows
arm_boost=1

# Enable audio (loads snd_bcm2835)
dtparam=audio=on

# Automatically load overlays for detected cameras
camera_auto_detect=1

# Automatically load overlays for detected DSI displays
display_auto_detect=1

# Enable DRM VC4 V3D driver
dtoverlay=vc4-kms-v3d
dtoverlay=

max_framebuffers=2
disable_fw_kms_setup=1
disable_overscan=1

[pi3+]
enable_uart=1
uart_2ndstage=1
[all]

# Automatically load initramfs files, if found
auto_initramfs=1

# fw crypto lock permissions
lock_device_private_key=1

# Start the Pi 3 in 64-bit mode, as Raspberry Pi OS does (the Pi 4 and 5 do by default)
arm_64bit=1
"""
CMDLINE = "console=serial0,115200 console=tty1 root=PARTUUID=1234abcd-02 fsck.repair=yes rootwait resize rootfstype=ext4\n"


class Workflow(unittest.TestCase):
    def test_it_never_publishes(self):
        wf = read(WORKFLOW)
        self.assertIn("permissions:\n  contents: read\n", wf)
        self.assertNotRegex(wf, r"contents: write|gh release (create|upload|edit|delete)|releases/assets|git push")
        self.assertRegex(wf, r"on:\n  workflow_dispatch:\n  push:\n    branches: \[image-gen\]\n\n")
        self.assertIn("retention-days: 7", wf)

    def test_rpi_image_gen_is_pinned_to_a_commit_not_copied(self):
        wf = read(WORKFLOW)
        pin = re.search(r"RPI_IMAGE_GEN_COMMIT: ([0-9a-f]{40})\n", wf)
        self.assertTrue(pin)
        self.assertIn('test "$(git rev-parse HEAD)" = "$RPI_IMAGE_GEN_COMMIT"', wf)
        self.assertIn("checkout " + pin.group(1), read(GEN, "README.md"))      # the README's local build: the same
        self.assertFalse(os.path.exists(os.path.join(GEN, "rpi-image-gen")))
        self.assertRegex(wf, r"GRYPE_VERSION: \d+\.\d+\.\d+\n")
        self.assertIn("sha256sum -c", wf)

    def test_the_card_and_its_report_say_what_they_are(self):
        self.assertIn('NAME="sofa-box-os-$VER-imagegen"', read(GEN, "build.sh"))
        self.assertIn("image-gen prototype", read(GEN, "build.sh"))
        # what the release channel reads from a card's report (stable-channel work, PR #36)
        self.assertIn('echo "Built on: ', read(GEN, "build.sh"))
        self.assertIn('echo "== Packages on the card (', read(GEN, "build.sh"))
        self.assertIn("image-gen prototype", read(LAYER_D, "hooks", "late", "preimage90-sofa-box"))


class Layer(unittest.TestCase):
    def test_the_box_is_set_up_by_its_own_installer(self):
        self.assertIn("install.sh --image", read(LAYER_D, "hooks", "customize50-sofa-box"))
        self.assertIn("sofa-box\" setup-boot", read(LAYER_D, "hooks", "late", "preimage90-sofa-box"))
        for _, _, files in os.walk(GEN):                       # reused from deploy/sofa-box, never copied here
            self.assertNotIn("install.sh", files)
            self.assertNotIn("sofa-box", files)

    def test_no_cloud_init_no_userconf_one_card_for_pi_3_4_and_5(self):
        layer = read(GEN, "layer", "sofa-box-os.yaml").split("\n---\n", 1)[1]
        packages = re.findall(r"^    - ([a-z0-9.+-]+)", layer, re.M)
        for gone in ("cloud-init", "rpi-cloud-init-mods", "userconf-pi"):
            self.assertNotIn(gone, packages)
        for needed in ("linux-image-rpi-2712", "raspberrypi-sys-mods", "polkitd", "wpasupplicant", "avahi-daemon"):
            self.assertIn(needed, packages)
        config = read(GEN, "config", "sofa-box.yaml")
        self.assertIn("  layer: rpi3\n", config)
        self.assertIn("  devid_scheme: partuuid\n", config)
        self.assertNotIn("rpi-linux-2712", config)            # its 16 KB blocks: a Pi 3 or 4 couldn't read the root
        self.assertIn("  user1sudo: passwd\n", config)         # (none would remove sudo, which the box's rules need)

    def test_a_pi_3_starts_64_bit_and_the_card_grows(self):
        self.assertIn("systemctl enable rpi-resize.service", read(LAYER_D, "hooks", "customize50-sofa-box"))
        self.assertIn("SYSTEMD_OFFLINE=1", read(LAYER_D, "hooks", "customize50-sofa-box"))
        self.assertIn("\narm_64bit=1\n", read(LAYER_D, "for", "rpi-boot-firmware", "config.txt.d", "90-sofa-box"))
        fragment = read(LAYER_D, "for", "linux-base", "cmdline.d", "90-sofa-box")
        self.assertEqual(len(fragment.splitlines()), 1)        # rpi-image-gen takes one line per fragment
        self.assertIn("+resize", fragment.split())

    def test_no_serial_console_uart(self):
        # rpi-image-gen's fragments turn the UART on for the Pi 3 B+, 4, 5 and Zero 2 W; on a Pi 3, enable_uart=1 holds
        # the GPU's core clock at its lowest. Empty fragments of the same names take them out, as on Raspberry Pi OS.
        d = os.path.join(LAYER_D, "for", "rpi-boot-firmware", "config.txt.d")
        for name in ("60-rpi-pi02", "61-rpi-pi3plus", "62-rpi-pi4", "63-rpi-pi5"):
            self.assertEqual(os.path.getsize(os.path.join(d, name)), 0, name)

    def test_hooks_are_executable(self):
        for hook in ("customize50-sofa-box", "late/customize90-report", "late/preimage90-sofa-box",
                     "postimage50-mbr-boot-code"):
            self.assertTrue(os.access(os.path.join(LAYER_D, "hooks", hook), os.X_OK), hook)


GNU_SED = subprocess.run(["sed", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0


@unittest.skipUnless(GNU_SED, "the box's boot setup uses GNU sed (Raspberry Pi OS has it; a Mac doesn't)")
class BootSettings(unittest.TestCase):
    """The late preimage hook: the box's own `sofa-box setup-boot` on the files rpi-image-gen put together."""

    def test_setup_boot_on_rpi_image_gens_files(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        root, out = os.path.join(tmp, "root"), os.path.join(tmp, "out")
        boot, lib = os.path.join(root, "boot", "firmware"), os.path.join(root, "usr", "local", "lib", "sofa-box")
        os.makedirs(boot)
        os.makedirs(lib)
        for name in ("sofa-box", "VERSION"):
            shutil.copy(os.path.join(HERE, "deploy", "sofa-box", name), lib)
        with open(os.path.join(boot, "config.txt"), "w") as f:
            f.write(CONFIG)
        with open(os.path.join(boot, "cmdline.txt"), "w") as f:
            f.write(CMDLINE)
        env = dict(os.environ, IGconf_image_outputdir=out, IGconf_sofabox_made_with="rpi-image-gen (test)")
        r = subprocess.run(["bash", os.path.join(LAYER_D, "hooks", "late", "preimage90-sofa-box"), root], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        words = read(boot, "cmdline.txt").split()
        for w in ("resize", "rootfstype=ext4", "root=PARTUUID=1234abcd-02", "quiet", "splash", "console=tty3",
                  "plymouth.ignore-serial-consoles", "logo.nologo", "vt.global_cursor_default=0", "loglevel=3"):
            self.assertIn(w, words)
        self.assertNotIn("console=tty1", words)
        config = read(boot, "config.txt")
        self.assertIn("\ndtparam=audio=off\n", config)
        self.assertNotIn("dtparam=audio=on", config)
        self.assertTrue(config.endswith("\ndisable_splash=1\n"))   # after the last [all]: for every board
        self.assertEqual(read(boot, "config.txt.before-sofa-box"), CONFIG)
        self.assertIn("image-gen prototype", read(boot, "sofa-box.txt"))
        self.assertEqual(read(root, "etc", "machine-id"), "uninitialized\n")   # a first start, as on Raspberry Pi OS
        self.assertIn("config.txt changes: < dtparam=audio=on > dtparam=audio=off > disable_splash=1",
                      read(out, "report-boot.txt"))


def fat16(files):
    """A small FAT16 partition: files is [(name, data)], in the root folder, one cluster each."""
    bps, spc, rsv, nfats, rootents, total, fatsz = 512, 4, 1, 2, 512, 20000, 20
    img = bytearray(total * bps)
    struct.pack_into("<HBHBHHxHxxxxxxxxI", img, 11, bps, spc, rsv, nfats, rootents, total, fatsz, 0)
    img[510:512] = b"\x55\xaa"
    fat = rsv * bps
    root = fat + nfats * fatsz * bps
    data = root + rootents * 32
    struct.pack_into("<HH", img, fat, 0xFFF8, 0xFFFF)
    slot = root
    for n, (name, body) in enumerate(files):
        cluster = 2 + n
        struct.pack_into("<H", img, fat + cluster * 2, 0xFFFF)
        at = data + (cluster - 2) * bps * spc
        img[at:at + len(body)] = body
        base, _, ext = name.partition(".")
        if len(base) > 8 or name != name.upper() and name != name.lower():
            u = name.encode("utf-16-le") + b"\x00\x00"                    # long name: 13 characters an entry,
            parts = [u[i:i + 26].ljust(26, b"\xff") for i in range(0, len(u), 26)]   # the last part first
            for seq in range(len(parts), 0, -1):
                p = parts[seq - 1]
                first = seq | (0x40 if seq == len(parts) else 0)
                img[slot:slot + 32] = bytes([first]) + p[0:10] + b"\x0f\x00\x00" + p[10:22] + b"\x00\x00" + p[22:26]
                slot += 32
            short, case = ("~%d" % n).ljust(8).encode() + b"TXT", 0
        else:
            short, case = base.upper().ljust(8).encode() + ext.upper().ljust(3).encode(), 0x18 if name == name.lower() else 0
        img[slot:slot + 32] = short + bytes([0x20, case]) + bytes(13) + struct.pack("<HI", cluster, len(body))
        slot += 32
    return bytes(img)


class DiskId(unittest.TestCase):
    """parted (Raspberry Pi OS's first start) gives an MBR with no boot code a new disk id, and the card then can't
    find its root: the post-image hook puts two bytes of boot code in, and touches nothing else."""

    def test_boot_code_in_and_nothing_else_changed(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        img = os.path.join(tmp, "card.img")
        mbr = bytearray(512)
        struct.pack_into("<I", mbr, 440, 0x549A4867)
        mbr[446:462] = bytes([0x80, 0, 0, 0, 0x0C]) + bytes(3) + struct.pack("<II", 16384, 1048576)
        mbr[510:512] = b"\x55\xaa"
        with open(img, "wb") as f:
            f.write(bytes(mbr) + bytes(4096))
        env = dict(os.environ, IGconf_image_name="card", IGconf_image_suffix="img")
        hook = os.path.join(LAYER_D, "hooks", "postimage50-mbr-boot-code")
        for _ in range(2):                                      # a second run changes nothing
            subprocess.run(["bash", hook, tmp], env=env, check=True, stdout=subprocess.PIPE)
        with open(img, "rb") as f:
            out = f.read()
        self.assertEqual(out[:2], b"\xeb\xfe")
        self.assertEqual(out[2:], bytes(mbr)[2:] + bytes(4096))


class CardReader(unittest.TestCase):
    def test_fat16_names_and_files(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, "boot.img")
        with open(path, "wb") as f:
            f.write(fat16([("config.txt", b"arm_64bit=1\n"), ("kernel_2712.img", b"kernel"), ("BOOTCODE.BIN", b"x")]))
        with open(path, "rb") as f:
            fat = card.Fat(f, 0)
            self.assertEqual(fat.kind, 16)
            entries = {e["name"]: e for e in fat.listdir()}
            self.assertEqual(sorted(entries), ["BOOTCODE.BIN", "config.txt", "kernel_2712.img"])
            e = entries["config.txt"]
            self.assertEqual(fat.data(e["cluster"], e["size"]), b"arm_64bit=1\n")

    def test_cve_summary_counts_each_cve_once(self):
        def match(cve, pkg, sev, state="not-fixed"):
            return {"vulnerability": {"id": cve, "severity": sev, "fix": {"state": state}},
                    "artifact": {"name": pkg, "upstreams": [{"name": "linux"}] if pkg.startswith("linux") else []}}
        report = {"matches": [match("CVE-1", "linux-image-rpi-v8", "High"), match("CVE-1", "linux-image-rpi-2712", "High"),
                              match("CVE-2", "chromium", "Critical", "wont-fix"), match("CVE-3", "curl", "Low")]}
        line = card.cve_summary(report)
        self.assertTrue(line.startswith("3 CVEs (4 matches): Critical 1, High 1, Low 1;"), line)
        self.assertIn("not-fixed 2, wont-fix 1", line)
        self.assertIn("most in: linux 1", line)

    def test_dpkg_status(self):
        status = ("Package: mpv\nStatus: install ok installed\nVersion: 0.40.0-3\n\n"
                  "Package: cloud-init\nStatus: deinstall ok config-files\nVersion: 25.2\n\n"
                  "Package: chromium\nStatus: install ok installed\nVersion: 1:156\nDescription: a\n b\n")
        self.assertEqual(card.packages(status), {"mpv": "0.40.0-3", "chromium": "1:156"})

    def test_systemd_links(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        os.makedirs(os.path.join(tmp, "multi-user.target.wants"))
        os.symlink("/usr/lib/systemd/system/avahi-daemon.service", os.path.join(tmp, "multi-user.target.wants", "avahi-daemon.service"))
        os.symlink("/usr/lib/systemd/system/graphical.target", os.path.join(tmp, "default.target"))
        os.symlink("/dev/null", os.path.join(tmp, "sshd-keygen.service"))
        wants, masked, default = card.units(tmp)
        self.assertEqual(wants, {"multi-user.target.wants": ["avahi-daemon.service"]})
        self.assertEqual((masked, default), (["sshd-keygen.service"], "graphical.target"))


if __name__ == "__main__":
    unittest.main()
