"""Sofa Box OS 1.1.84: Install on this computer. A PC started from the Sofa Box OS USB stick puts it on one of its own
drives from Settings → This box: the drive is picked on the TV and named twice before anything happens, everything on
the stick goes with it (settings, apps, sign-ins, Wi-Fi), and the PC starts from its drive after, by UEFI with Secure
Boot's signed chain or by BIOS.

GitHub proves it on every PC image (the card workflow's pc job): the image started as a USB stick beside a blank drive,
installed through the agent the way the TV does it, then the PC started from that drive alone, with Secure Boot and
with BIOS. These check the pieces here with stand-in drive lists; nothing is erased."""
import json
import os
import shutil
import subprocess
import time
import unittest
from unittest import mock

from tests.test_box_apps_close import BOX, HERE, load
from tests.test_box_memory import tree

boxos = load("boxos")
GB = 10 ** 9


def read(*path):
    with open(os.path.join(HERE, *path), encoding="utf-8") as f:
        return f.read()


def disk(name, size, tran="sata", model="Samsung SSD 870", serial="S5Y1", children=(), ro=False, rm=False, typ="disk"):
    return {"name": name, "path": "/dev/" + name, "size": size, "type": typ, "rm": rm, "ro": ro, "tran": tran,
            "model": model, "serial": serial, "fstype": None, "label": None, "mountpoint": None, "children": list(children)}


def part(name, fstype=None, label=None, mountpoint=None):
    return {"name": name, "path": "/dev/" + name, "size": GB, "type": "part", "fstype": fstype, "label": label,
            "mountpoint": mountpoint}


def stick(**kw):
    return disk("sda", 32 * GB, tran="usb", model="SanDisk Ultra", serial="4C530001", rm=True, children=[
        part("sda1"), part("sda2", "vfat", "SOFABOOT", "/boot/efi"), part("sda3", "ext4", "sofabox", "/")], **kw)


def windows():
    return disk("nvme0n1", 512 * GB, tran="nvme", model="WD Blue SN580", serial="23N1", children=[
        part("nvme0n1p1", "vfat", "SYSTEM"), part("nvme0n1p2"), part("nvme0n1p3", "ntfs", "Windows"),
        part("nvme0n1p4", "ntfs", "Recovery")])


class TheDrives(unittest.TestCase):
    """What Settings → This box offers: the PC's own drives, never the stick, each with what's on it, and why not."""

    def at(self, files=None):
        root = tree(dict({"proc/meminfo": "MemTotal: 4000000 kB\n"}, **(files or {})))
        self.addCleanup(shutil.rmtree, root, True)
        patch = mock.patch.object(boxos, "ROOT", root)
        patch.start()
        self.addCleanup(patch.stop)
        return root

    def test_a_pc_from_the_stick_lists_its_own_drives(self):
        self.at()
        tiny = disk("sdb", 4 * GB, tran="usb", model="Old Stick", serial="X1", rm="1")       # (older lsblk: "1", not true)
        hdd = disk("sdc", 2 * 10 ** 12, model="ST2000DM008", serial="ZFL1", children=[part("sdc1", "ext4", "Films")])
        others = [disk("zram0", 2 * GB, tran=None, model=None, serial=None), disk("sr0", GB, tran="sata", typ="rom"),
                  disk("loop0", 8 * GB, tran=None, typ="loop")]
        d = boxos.install_disks([stick(), windows(), tiny, hdd] + others, machine="x86_64", used=int(3.3 * GB))
        self.assertTrue(d["pc"])
        self.assertTrue(d["from_stick"])
        self.assertEqual([x["disk"] for x in d["drives"]], ["/dev/sdc", "/dev/nvme0n1", "/dev/sdb"])   # biggest first; can't, last
        nvme = d["drives"][1]
        self.assertEqual((nvme["model"], nvme["size"], nvme["serial"], nvme["usb"], nvme["why_not"]),
                         ("WD Blue SN580", 512 * GB, "23N1", False, None))
        self.assertEqual(nvme["has"], ["SYSTEM", "Windows", "Recovery"])                  # (its labels: Windows is on it)
        self.assertEqual(d["drives"][0]["has"], ["Films"])
        self.assertEqual(d["drives"][2]["why_not"], "Too small: 4 GB, and it needs 8 GB.")
        self.assertTrue(d["drives"][2]["usb"])
        self.assertNotIn("/dev/sda", [x["disk"] for x in d["drives"]])                  # never the stick it runs from
        self.assertEqual(boxos.install_disks([stick(), windows()], machine="x86_64", used=20 * GB)["need"], 22 * GB)

    def test_a_drive_in_use_or_read_only_isnt_offered(self):
        self.at()
        home = disk("sdb", 256 * GB, children=[part("sdb1", "ext4", None, "/home")])
        swap = disk("sdc", 256 * GB, children=[part("sdc1", "swap", None, "[SWAP]")])
        locked = disk("sdd", 256 * GB, ro=True)
        opened = disk("sde", 64 * GB, tran="usb", children=[part("sde1", "exfat", "PHOTOS", "/media/sofabox/PHOTOS")])
        why = {x["disk"]: x["why_not"] for x in boxos.install_disks([stick(), home, swap, locked, opened], machine="x86_64",
                                                                    used=3 * GB)["drives"]}
        self.assertEqual(why["/dev/sdb"], "In use (/home).")
        self.assertEqual(why["/dev/sdc"], "In use ([SWAP]).")
        self.assertEqual(why["/dev/sdd"], "It can't be written to.")
        self.assertIsNone(why["/dev/sde"])                     # (opened in Files: the installer closes it first)

    def test_only_a_pc_running_from_a_stick(self):
        self.at()
        internal = disk("nvme0n1", 512 * GB, tran="nvme", children=[part("nvme0n1p2", "vfat", None, "/boot/efi"),
                                                                    part("nvme0n1p3", "ext4", None, "/")])
        d = boxos.install_disks([internal, disk("sda", 256 * GB)], machine="x86_64", used=3 * GB)
        self.assertTrue(d["pc"])
        self.assertFalse(d["from_stick"])                      # (installed already: it runs from its own drive)
        self.assertFalse(boxos.install_disks([stick(), windows()], machine="aarch64", used=3 * GB)["from_stick"])
        self.at({"proc/device-tree/model": "Raspberry Pi 5 Model B Rev 1.0\0"})
        self.assertFalse(boxos.install_disks([stick(), windows()], machine="x86_64", used=3 * GB)["pc"])

    def test_the_stick_remembers_the_drive(self):
        self.at({"etc/sofa-box-installed-onto": json.dumps({"disk": "/dev/nvme0n1", "serial": "23N1", "model": "WD Blue SN580"})})
        d = boxos.install_disks([stick(), windows()], machine="x86_64", used=3 * GB)
        self.assertTrue(d["drives"][0]["installed"])
        other = windows()
        other["serial"] = "99Z9"                               # (the same name on another PC: not this drive)
        self.assertFalse(boxos.install_disks([stick(), other], machine="x86_64", used=3 * GB)["drives"][0]["installed"])

    def test_how_its_going(self):
        root = self.at()
        self.assertIsNone(boxos.install_status())
        os.makedirs(os.path.join(root, "run"))
        status = os.path.join(root, "run", "sofa-box-install.json")
        with open(status, "w") as f:
            json.dump({"state": "running", "step": "copy", "percent": 40, "disk": "/dev/sdb", "message": "Copying", "at": int(time.time())}, f)
        self.assertEqual(boxos.installing(), "/dev/sdb")
        with open(status, "w") as f:                           # ten minutes without a word: it stopped (power, a kill)
            json.dump({"state": "running", "step": "copy", "percent": 40, "disk": "/dev/sdb", "message": "Copying", "at": int(time.time()) - 700}, f)
        self.assertEqual(boxos.install_status()["state"], "failed")
        self.assertIsNone(boxos.installing())

    def test_files_leaves_the_drive_alone_and_the_sticks_boot_part_out(self):
        self.at()
        flat = [dict(part("sda2", "vfat", "SOFABOOT", "/boot/efi"), parent_tran="usb", parent_hotplug=True),
                dict(part("sdb1", "ext4", "sofabox", "/media/sofabox/sofabox"), parent_tran="usb", parent_hotplug=True),
                dict(part("sdc1", "exfat", "PHOTOS", "/media/sofabox/PHOTOS"), parent_tran="usb", parent_hotplug=True)]
        with mock.patch.object(boxos, "_lsblk", return_value=flat), mock.patch.object(boxos, "installing", return_value="/dev/sdb"):
            self.assertEqual([d["dev"] for d in boxos.devices()["drives"]], ["/dev/sdc1"])

    def test_about_says_where_it_runs_from(self):
        self.at({"etc/sofa-box-installed": "Sofa Box OS 1.1.84, installed from a USB stick on 2026-11-12 onto WD Blue SN580\n"})
        self.assertTrue(boxos.installed_note().startswith("Sofa Box OS 1.1.84, installed"))


class TheAgent(unittest.TestCase):
    """/box/api/install: the drive the TV said yes to, and only that drive, as it was listed."""

    def setUp(self):
        self.agent = load("sofa-box-agent")
        self.info = boxos.install_disks([stick(), windows()], machine="x86_64", used=3 * GB)
        self.ran = []
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(self.agent, "run", side_effect=lambda cmd, t=20: self.ran.append(cmd) or (0, "")).start()

        class Now:                                             # (the thread, at once)
            def __init__(self, target=None, daemon=None):
                self.target = target

            def start(self):
                self.target()
        mock.patch.object(self.agent.threading, "Thread", Now).start()

    def ask(self, **change):
        return self.agent.start_install(self.info, dict({"disk": "/dev/nvme0n1", "serial": "23N1", "size": 512 * GB}, **change))

    def test_the_drive_said_yes_to(self):
        r = self.ask()
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.ran, [["sudo", "-n", os.path.join(BOX, "sofa-box"), "install-to-disk", "/dev/nvme0n1", "--yes"]])
        self.assertIn("WD Blue SN580", r["message"])
        self.assertLessEqual(abs(r["started"] - time.time()), 2)

    def test_anything_else_is_refused(self):
        for change, words in (({"serial": "OTHER"}, "isn't there as it was"), ({"size": 256 * GB}, "isn't there as it was"),
                              ({"disk": "/dev/sda"}, "isn't there as it was"),            # the stick itself: never listed
                              ({"disk": "/dev/sda; reboot"}, "isn't there as it was")):
            r = self.ask(**change)
            self.assertFalse(r["ok"])
            self.assertIn(words, r["message"])
        self.info["drives"][0]["why_not"] = "In use (/home)."
        self.assertEqual(self.ask()["message"], "In use (/home).")
        self.info["drives"][0]["why_not"] = None
        self.info["status"] = {"state": "running"}
        self.assertIn("already", self.ask()["message"])
        self.info["status"], self.info["from_stick"] = None, False
        self.assertIn("USB stick", self.ask()["message"])
        self.assertEqual(self.ran, [])

    def test_its_route_reads_with_get_and_starts_with_post(self):
        src = read("deploy", "sofa-box", "sofa-box-agent.py")
        self.assertIn('"/box/api/install"))', src)            # a GET only reads (READ_ONLY)
        self.assertIn('start_install(info, data) if self.command == "POST" else info', src)
        self.assertIn('"from_stick": not board()["gen"] and boxos.from_stick()', src)


class TheInstaller(unittest.TestCase):
    """sofa-box install-to-disk: what it refuses, and how it copies and starts."""

    def run_it(self, *args):
        p = subprocess.run(["sh", os.path.join(BOX, "sofa-box"), "install-to-disk"] + list(args), capture_output=True, text=True,
                           timeout=30, env=dict(os.environ, SOFA_BOX_ON_ITS_OWN="1"))
        return p.returncode, p.stdout + p.stderr

    def test_it_asks_for_a_whole_drive_and_a_yes(self):
        for args in ((), ("/dev/sda1", "--yes"), ("/dev/loop0", "--yes"), ("/dev/sda; reboot", "--yes"), ("sda", "--yes"),
                     ("/dev/sda\n/dev/sdb", "--yes")):
            code, out = self.run_it(*args)
            self.assertEqual(code, 2, args)
            self.assertIn("Which drive?", out)
        code, out = self.run_it("/dev/nvme0n1")
        self.assertEqual(code, 2)
        self.assertIn("Everything on /dev/nvme0n1 is erased", out)
        if os.getuid() != 0:
            code, out = self.run_it("/dev/nvme0n1", "--yes")
            self.assertEqual(code, 1)
            self.assertIn("As root", out)

    def test_it_checks_the_drive_itself(self):
        box = read("deploy", "sofa-box", "sofa-box")
        fn = box[box.index("install_to_disk() {"):]
        fn = fn[:fn.index("\n}\n")]
        checks = ['[ "$(uname -m)" = x86_64 ] && [ ! -e /proc/device-tree/model ]', '[ -b "$DISK" ]',
                  '[ "$(lsblk -dno TYPE "$DISK")" = disk ]', '! root_disk | grep -qx "$DISK"', 'lsblk -dno RO "$DISK"',
                  "findmnt -rno TARGET -S", "swapon --show=NAME", "/holders", '[ "$SIZE" -ge "$NEED" ]']
        partition = fn.index("STEP=partition")
        for c in checks:
            self.assertIn(c, fn)
            self.assertLess(fn.index(c), partition, c)          # every check before anything is written
        self.assertLess(fn.index("unshare -m --propagation slave"), fn.index("trap install_end EXIT"))

    def test_it_copies_the_root_alone_and_starts_both_ways(self):
        box = read("deploy", "sofa-box", "sofa-box")
        for line in ('mount --bind / "$F"', 'mount --make-private "$F"', 'mount -o remount,bind,ro "$F"', 'cp -a "$F/." "$T/"',
                     "--bootloader-id=sofabox --removable --no-nvram --uefi-secure-boot", 'grub-install --target=i386-pc "$DISK"',
                     'grep -q "root=UUID=$ROOT_UUID" "$T/boot/grub/grub.cfg"', '> "$T/etc/sofa-box-installed"',
                     "> /etc/sofa-box-installed-onto", "label: gpt", "name=bios", "size=256MiB", "name=root"):
            self.assertIn(line, box)
        self.assertIn('on_its_own install-to-disk "${2:-}" "${3:-}"', box)     # its own service: the agent can restart
        self.assertIn('"$0" "$@"\n}', box)                                       # (and on_its_own passes the drive on)
        self.assertIn("$LIB/sofa-box install-to-disk *", read("deploy", "sofa-box", "install.sh"))
        self.assertRegex(read("tools", "build-sofa-box-vm-image.sh"), r"INCLUDE=\"[^\"]*,efibootmgr,")
        subprocess.run(["sh", "-n", os.path.join(BOX, "sofa-box")], check=True)


class OnTheTV(unittest.TestCase):
    def test_the_card_the_drive_and_two_yeses(self):
        js = read("deploy", "sofa-box", "home", "home.js")
        self.assertIn('head("This box", "Its name, its clock, and what it is.") + (b.from_stick ? installCard() : "")', js)
        sure = js[js.index("function instSure(d, n)"):]
        sure = sure[:sure.index("\n  }\n")]
        second = sure[sure.index(": `<h3>Sure?"):]
        self.assertLess(second.index('data-sheet="close">No, keep it'), second.index('data-sheet="yes">Yes, erase'))   # starts on No
        self.assertIn("if (n === 1) return instSure(d, 2);", sure)
        self.assertIn('api("/box/api/install", { disk: d.disk, serial: d.serial, size: d.size })', sure)
        self.assertIn("(Windows too)", js)


class ProvenOnGitHub(unittest.TestCase):
    def test_installed_then_started_from_the_drive_before_its_published(self):
        wf = read(".github", "workflows", "sofa-box-image.yml")
        pc = wf[wf.index("\n  pc:\n"):]
        step = pc.index("--firmware uefi --install-onto 16G")
        self.assertLess(step, pc.index("- name: Publish it (main)"))
        self.assertIn("installed-uefi-secure installed-bios", pc)
        boot = read("tools", "boot-sofa-box-vm.sh")
        self.assertIn('THEN="uefi-secure bios"', boot)
        self.assertIn("usb-storage,bus=xhci.0,drive=media,bootindex=1", boot)
        self.assertIn("grep -aq 'SOFA-BOX-PROOF install: ok'", boot)
        proof = read("tools", "sofa-box-vm-proof.sh")
        self.assertIn('"$AGENT/box/api/install"', proof)            # the way the TV does it
        self.assertIn('say "installed: fail', proof)
        for f in ("boot-sofa-box-vm.sh", "sofa-box-vm-proof.sh"):
            subprocess.run(["sh", "-n", os.path.join(HERE, "tools", f)], check=True)


if __name__ == "__main__":
    unittest.main()
