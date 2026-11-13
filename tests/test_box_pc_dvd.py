"""Sofa Box OS 1.1.85: Sofa Box OS for a PC on a DVD. The card workflow makes a live DVD from the PC image (the same
system, as it is, in a squashfs; Debian's live-boot in a start of its own; shim and Debian's signed GRUB for UEFI,
GRUB for BIOS), starts it on GitHub as a disc with Secure Boot on and on an older PC, installs from it onto a blank
drive and starts the PC from that drive, before it's published. Sofa Box Imager burns it ("On a DVD").

These check the pieces here, with stand-in drive lists; what's proven on GitHub is in the workflow's runs."""
import json
import os
import shutil
import subprocess
import unittest
from unittest import mock

from tests.test_box_apps_close import BOX, HERE, load
from tests.test_box_memory import tree
from tests.test_box_pc_install import GB, disk, part, windows

boxos = load("boxos")


def read(*path):
    with open(os.path.join(HERE, *path), encoding="utf-8") as f:
        return f.read()


class FromTheDisc(unittest.TestCase):
    """Settings → This box on a PC running from the live DVD: it says so, and installs from there."""

    def at(self, files):
        root = tree(dict({"proc/meminfo": "MemTotal: 4000000 kB\n"}, **files))
        self.addCleanup(shutil.rmtree, root, True)
        patch = mock.patch.object(boxos, "ROOT", root)
        patch.start()
        self.addCleanup(patch.stop)

    LIVE = "BOOT_IMAGE=/live/vmlinuz boot=live nofstab quiet splash\n"

    def test_running_from_the_dvd(self):
        self.at({"proc/cmdline": self.LIVE, "run/live/medium/live/filesystem.size": "3412000000\n"})
        dvd = disk("sr0", 1_512_634_368, tran="sata", model="DVD-RW DVR-221", typ="rom")
        dvd["mountpoint"] = "/run/live/medium"
        d = boxos.install_disks([dvd, windows()], machine="x86_64", used=None)
        self.assertTrue(d["from_stick"])
        self.assertTrue(d["live"])
        self.assertEqual(d["medium"], "DVD")
        self.assertEqual([x["disk"] for x in d["drives"]], ["/dev/nvme0n1"])          # never the DVD drive
        self.assertEqual(d["need"], 7_500_000_000)                                       # (3.4 GB from the disc + 2)
        self.at({"proc/cmdline": self.LIVE, "run/live/medium/live/filesystem.size": "9000000000\n"})
        self.assertEqual(boxos.install_disks([dvd, windows()], machine="x86_64")["need"], 11_000_000_000)

    def test_the_discs_file_on_a_usb_stick(self):
        self.at({"proc/cmdline": self.LIVE})
        stick = disk("sdb", 16 * GB, tran="usb", model="Ultra", rm=True)
        stick["mountpoint"] = "/run/live/medium"                  # (the whole stick is the disc's ISO 9660)
        d = boxos.install_disks([stick, windows()], machine="x86_64", used=3 * GB)
        self.assertEqual((d["from_stick"], d["medium"]), (True, "USB stick"))
        self.assertEqual([x["disk"] for x in d["drives"]], ["/dev/nvme0n1"])          # never the stick it runs from

    def test_not_live_is_as_before(self):
        self.at({"proc/cmdline": "BOOT_IMAGE=/boot/vmlinuz root=UUID=x ro quiet\n"})
        internal = disk("nvme0n1", 512 * GB, tran="nvme", children=[part("nvme0n1p3", "ext4", None, "/")])
        d = boxos.install_disks([internal], machine="x86_64", used=3 * GB)
        self.assertEqual((d["from_stick"], d["live"]), (False, False))

    def test_what_settings_says(self):
        self.at({"proc/cmdline": self.LIVE})
        boxos._stick.clear()
        self.addCleanup(boxos._stick.clear)
        dvd = disk("sr0", GB, typ="rom")
        dvd["mountpoint"] = "/run/live/medium"
        with mock.patch.object(boxos, "_lsblk_disks", return_value=[dvd, windows()]), \
                mock.patch.object(boxos, "_is_pc", return_value=True):
            self.assertEqual(boxos.from_stick(), "DVD")
        js = read("deploy", "sofa-box", "home", "home.js")
        self.assertIn("Sofa Box OS runs from the DVD now, and forgets what's set up here when the PC restarts.", js)
        self.assertIn('b.from_stick === "DVD" ? "a DVD (what\'s set up is forgotten when it restarts)"', js)
        self.assertIn("Leave the ${it} in and the PC on", js)

    def test_the_installer_from_the_disc(self):
        box = read("deploy", "sofa-box", "sofa-box")
        self.assertIn("for at in / /run/live/medium; do", box)             # the disk it runs from: never offered
        self.assertIn("USED=\"$(cat /run/live/medium/live/filesystem.size 2>/dev/null || df", box)
        self.assertIn("grep -qw boot=live /proc/cmdline", box)
        self.assertIn("installed from a %s on %s onto %s", box)
        subprocess.run(["sh", "-n", os.path.join(BOX, "sofa-box")], check=True)


class TheDisc(unittest.TestCase):
    """tools/build-sofa-box-dvd.sh: what goes on the disc, and how it starts."""

    def setUp(self):
        self.sh = read("tools", "build-sofa-box-dvd.sh")
        subprocess.run(["sh", "-n", os.path.join(HERE, "tools", "build-sofa-box-dvd.sh")], check=True)

    def test_the_same_system_as_the_stick(self):
        sh = self.sh
        self.assertIn('LOOP="$(losetup -rfP --show "$IMG")"', sh)              # (the image, read-only)
        self.assertIn('mksquashfs "$ROOT" "$ISO/live/filesystem.squashfs"', sh)   # its root as it is
        overlay = sh.index("mount -t overlay overlay")
        self.assertLess(sh.index("mksquashfs"), overlay)                          # squashed before anything is added
        self.assertIn("live-boot live-boot-initramfs-tools", sh[overlay:])        # live-boot only in the throwaway layer
        self.assertIn("mkinitramfs -o /tmp/initrd.img", sh)
        self.assertIn('du -sx --block-size=1 "$ROOT"', sh)                       # (what installing from it copies)

    def test_it_starts_like_the_stick(self):
        sh = self.sh
        for f in ("usr/lib/shim/shimx64.efi.signed", "usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed",
                  "usr/lib/grub/i386-pc/boot_hybrid.img", "grub-mkimage -O i386-pc-eltorito", '"$ISO/.disk/info"',
                  "-b boot/grub/i386-pc/eltorito.img", "--efi-boot boot/grub/efi.img", "--grub2-mbr"):
            self.assertIn(f, sh)
        self.assertIn('[ "$BOOTS" = 2 ] || { echo "The disc should start two ways', sh)
        self.assertIn('[ "$SIZE" -lt 4700000000 ]', sh)
        live = sh[sh.index("LIVEARGS="):].split("\n", 1)[0]
        for arg in ("boot=live", "nofstab", "systemd.mask=boot-efi.mount", "systemd.mask=systemd-repart.service",
                    "systemd.mask=systemd-growfs-root.service"):
            self.assertIn(arg, live)
        # the stick's EFI partition "nofail": the disc has none, and a damaged one never stops the box
        self.assertIn("/boot/efi  vfat  umask=0077,nofail", read("tools", "build-sofa-box-vm-image.sh"))


class ProvenOnGitHub(unittest.TestCase):
    def test_started_as_a_disc_and_installed_from_before_its_published(self):
        wf = read(".github", "workflows", "sofa-box-image.yml")
        pc = wf[wf.index("\n  pc:\n"):]
        publish = pc.index("- name: Publish it (main)")
        steps = [pc.index(s) for s in ("sudo tools/build-sofa-box-dvd.sh out/*-x86_64.img out",
                                       "out/*-x86_64-dvd.iso out/boot --firmware uefi-secure",
                                       "out/*-x86_64-dvd.iso out/boot --firmware bios",
                                       "out/*-x86_64-dvd.iso out/boot --firmware uefi --install-onto 16G --then uefi")]
        self.assertEqual(steps, sorted(steps))
        self.assertTrue(all(i < publish for i in steps))
        self.assertIn("squashfs-tools xorriso", pc)
        for name in ("sofa-box-pc-dvd.iso", "sofa-box-pc-dvd.iso.sha256", "sofa-box-pc-dvd-report.txt",
                     'sofa-box-os-$VER-pc-dvd.iso'):
            self.assertIn(name, pc[publish:])
        self.assertIn("dvd-uefi-secure dvd-bios install-dvd-uefi installed-dvd-uefi", pc)
        self.assertIn('- "tools/build-sofa-box-dvd.sh"', wf)
        boot = read("tools", "boot-sofa-box-vm.sh")
        self.assertIn("-boot_image any replay", boot)
        self.assertIn("/live/zz-proof.squashfs", boot)
        self.assertIn("media=cdrom", boot)
        self.assertIn('rm -f "$M/etc/sofa-box-vm-install-to" "$M/etc/sofa-box-vm-secure-boot" "$M/etc/sofa-box-vm-dvd"', boot)
        proof = read("tools", "sofa-box-vm-proof.sh")
        self.assertIn('say "dvd: fail', proof)
        for f in ("boot-sofa-box-vm.sh", "sofa-box-vm-proof.sh"):
            subprocess.run(["sh", "-n", os.path.join(HERE, "tools", f)], check=True)


class TheImagerBurnsIt(unittest.TestCase):
    def test_on_a_dvd(self):
        kit = read("imager", "Sources", "ImagerKit", "CardList.swift")
        self.assertIn('case .dvd: return ["sofa-box-pc-dvd"]', kit)
        burn = read("imager", "Sources", "ImagerMac", "Burn.swift")
        self.assertIn('["burn", file.path, "-device", device, "-noaddpmap", "-nooptimizeimage", "-verifyburn", "-eject", "-puppetstrings"]', burn)
        self.assertIn("throw BurnError.wrongDownload", burn)
        lst = read("tools", "sofa-box-imager-list.py")
        self.assertIn('DVD_TAGS = ["sofa-box-pc-dvd"]', lst)
        self.assertIn('DVD_VERSION_CARD = "sofa-box-os-%s-pc-dvd.iso"', lst)


if __name__ == "__main__":
    unittest.main()
