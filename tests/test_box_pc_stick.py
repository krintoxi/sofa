"""Sofa Box OS for a PC, on a USB stick: the image the card workflow builds beside every card and publishes on the same
releases, what's on it (no login anyone could know, Secure Boot's signed boot chain), the three starts it must pass in
QEMU before it's published, and the list's entries for it. What's proven on GitHub (the build and the starts) is in
the workflow's runs; these check that it's asked for, here, without building anything."""
import os
import re
import subprocess
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(HERE, "tools")


def read(*path):
    with open(os.path.join(HERE, *path), encoding="utf-8") as f:
        return f.read()


class TheImage(unittest.TestCase):
    def test_no_login_anyone_could_know(self):
        """As on the Pi card: no password for "sofa" and SSH off, unless a test build asks for one (--password)."""
        build = read("tools", "build-sofa-box-vm-image.sh")
        self.assertNotIn("sofa:sofabox", build)
        self.assertIn("usermod -p '!' sofa", build)
        self.assertIn("systemctl disable ssh.service ssh.socket", build)
        self.assertIn("--password) PASSWORD=", build)
        self.assertIn("echo 'sofa:$PASSWORD' | chpasswd", build)                # (only a test build's)
        self.assertNotIn("Login: sofa / sofabox", build)

    def test_secure_boot_as_most_pcs_come(self):
        build = read("tools", "build-sofa-box-vm-image.sh")
        self.assertRegex(build, r"INCLUDE=\"[^\"]*grub-efi-amd64-signed,shim-signed")
        self.assertIn("--removable --no-nvram --uefi-secure-boot", build)
        boot = read("tools", "boot-sofa-box-vm.sh")
        self.assertIn("OVMF_CODE_4M.secboot.fd", boot)
        self.assertIn("OVMF_VARS_4M.ms.fd", boot)                                 # Microsoft's keys enrolled
        self.assertIn("-machine q35,smm=on", boot)
        proof = read("tools", "sofa-box-vm-proof.sh")
        self.assertIn("SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c", proof)
        self.assertIn("secure boot: fail", proof)

    def test_it_grows_to_fill_the_stick(self):
        boot = read("tools", "boot-sofa-box-vm.sh")
        self.assertIn('truncate -s "$DISK" "$COPY"', boot)
        self.assertIn("sofa-box-vm-disk-bytes", boot)
        proof = read("tools", "sofa-box-vm-proof.sh")
        self.assertIn('say "grown: fail', proof)
        for f in ("build-sofa-box-vm-image.sh", "boot-sofa-box-vm.sh", "sofa-box-vm-proof.sh"):
            subprocess.run(["sh", "-n", os.path.join(TOOLS, f)], check=True)


class PublishedBesideTheCard(unittest.TestCase):
    def setUp(self):
        self.wf = read(".github", "workflows", "sofa-box-image.yml")
        self.pc = self.wf[self.wf.index("\n  pc:\n"):]

    def test_built_and_started_three_ways_before_its_published(self):
        pc = self.pc
        self.assertIn("needs: card", pc)
        self.assertIn("runs-on: ubuntu-24.04\n", pc)                              # (x86-64: it runs the image's programs)
        self.assertIn("sudo tools/build-sofa-box-vm-image.sh out --size 4G", pc)
        starts = [pc.index("--firmware " + fw) for fw in ("uefi --disk 16G", "bios", "uefi-secure")]
        publish = pc.index("- name: Publish it (main)")
        self.assertTrue(all(i < publish for i in starts), "each start comes before publishing")
        self.assertNotRegex(pc[:publish], r"--firmware[^\n]*\n\s*continue-on-error")   # (a failed start stops the job)
        for path in ("tools/build-sofa-box-vm-image.sh", "tools/boot-sofa-box-vm.sh", "tools/sofa-box-vm-proof.sh"):
            self.assertIn('- "%s"' % path, self.wf)                               # (a change to them builds it)

    def test_never_beside_another_commits_card(self):
        pc = self.pc[self.pc.index("- name: Publish it (main)"):]
        self.assertIn("if: github.event_name != 'release' && github.ref == 'refs/heads/main'", pc)
        self.assertIn('grep -q "sofa-box-card version=$VER commit=$GITHUB_SHA"', pc)   # the testing card is this run's
        self.assertIn('[ "$TARGET" = "$GITHUB_SHA" ] && [ "$HAS" = 0 ]', pc)          # the version's release is this run's
        for name in ("sofa-box-pc.img.xz", "sofa-box-pc.img.xz.sha256", "sofa-box-pc-report.txt",
                     "sofa-box-os-$VER-pc.img.xz", "sofa-box-os-$VER-pc-report.txt"):
            self.assertIn(name, pc)
        self.assertIn("next-", pc)                                                # (the link never breaks: next- then renamed)
        self.assertIn("not tried on a real PC yet", pc)

    def test_the_card_jobs_own_steps_are_as_they_were(self):
        card = self.wf[self.wf.index("\n  card:\n"):self.wf.index("\n  pc:\n")]
        self.assertIn("python3 tools/sofa-box-releases.py may-replace", card)
        self.assertIn('gh release create "box-os-v$VER"', card)
        self.assertNotIn("pc.img.xz", card)


class TheList(unittest.TestCase):
    def test_a_device_of_its_own_and_the_imager_reads_it(self):
        tool = read("tools", "sofa-box-imager-list.py")
        self.assertIn('"tags": ["sofa-box-pc-x86_64"]', tool)
        self.assertIn('PC_VERSION_CARD = "sofa-box-os-%s-pc.img.xz"', tool)
        self.assertIn('PC_ROLLING_CARD = "sofa-box-pc.img.xz"', tool)
        swift = read("imager", "Sources", "ImagerKit", "CardList.swift")
        self.assertIn('case .pc: return ["sofa-box-pc-x86_64"]', swift)          # (the app's tag is the list's)
        ver = tuple(int(x) for x in read("imager", "VERSION").strip().split("."))
        self.assertGreaterEqual(ver, (0, 2, 0))                                  # (For a PC since 0.2.0)


if __name__ == "__main__":
    unittest.main()
