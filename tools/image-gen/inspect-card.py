#!/usr/bin/env python3
"""What's on a Sofa box card, read off the image file without starting it or mounting anything.

    inspect-card.py CARD.img > card.json            the facts, as JSON
    inspect-card.py --compare TODAY.json NEW.json   the two side by side, as Markdown

Needs Python 3 (nothing else from PyPI) and debugfs (e2fsprogs) for the root partition; the boot partition (FAT) is
read here. Made for comparing the image-gen prototype (tools/image-gen) with today's card, but reads any
Raspberry Pi OS style card: an MBR, a FAT boot partition and an ext4 root.
"""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

TARGETS = ["sysinit.target", "basic.target", "multi-user.target", "graphical.target", "timers.target",
           "sockets.target", "network-online.target", "bluetooth.target", "getty.target", "default.target"]
WATCH = ["cloud-init", "cloud-init-base", "cloud-init-local", "cloud-config", "cloud-final", "userconfig",
         "rpi-preseed", "sshswitch", "ssh", "regenerate_ssh_host_keys", "ssh-hostkeys-generate", "rpi-resize",
         "systemd-growfs-root", "NetworkManager", "avahi-daemon", "bluetooth", "systemd-networkd", "iwd",
         "systemd-resolved", "rpi-eeprom-update", "sofa-box", "sofa-box-agent", "sofa-box-input", "sofa-box-cec",
         "sofa-box-tune", "sofa-box-first-start"]
FIRMWARE = ["brcm/brcmfmac43430-sdio.bin", "brcm/brcmfmac43455-sdio.bin", "brcm/brcmfmac43456-sdio.bin",
            "brcm/BCM43430A1.hcd", "brcm/BCM4345C0.hcd", "brcm/BCM4345C5.hcd"]


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def partitions(f):
    f.seek(0)
    mbr = f.read(512)
    if mbr[510:512] != b"\x55\xaa":
        raise SystemExit("not an MBR disk image")
    parts = []
    for i in range(4):
        e = mbr[446 + 16 * i:446 + 16 * (i + 1)]
        start, count = u32(e, 8), u32(e, 12)
        if e[4]:
            parts.append({"n": i + 1, "type": "0x%02x" % e[4], "start": start * 512, "bytes": count * 512})
    return "0x%08x" % u32(mbr, 440), parts


class Fat:
    """Just enough FAT16/FAT32 to list folders and read files."""

    def __init__(self, f, offset):
        self.f, self.off = f, offset
        bs = self.read(0, 512)
        self.bps, self.spc, rsv, nfats = u16(bs, 11), bs[13], u16(bs, 14), bs[16]
        self.rootents, tot16, fat16, tot32 = u16(bs, 17), u16(bs, 19), u16(bs, 22), u32(bs, 32)
        self.fatsz = fat16 or u32(bs, 36)
        self.rootclus = u32(bs, 44) if not fat16 else None
        self.fat_start = rsv * self.bps
        self.root_start = self.fat_start + nfats * self.fatsz * self.bps
        root_bytes = ((self.rootents * 32 + self.bps - 1) // self.bps) * self.bps
        self.data_start = self.root_start + root_bytes
        clusters = ((tot16 or tot32) * self.bps - self.data_start) // (self.bps * self.spc)
        self.kind = 12 if clusters < 4085 else 16 if clusters < 65525 else 32
        if self.kind == 12:
            raise ValueError("FAT12 boot partition")
        self.cbytes = self.bps * self.spc

    def read(self, pos, n):
        self.f.seek(self.off + pos)
        return self.f.read(n)

    def chain(self, c):
        seen = set()
        while c and 2 <= c and c not in seen:
            seen.add(c)
            yield c
            if self.kind == 32:
                c = u32(self.read(self.fat_start + c * 4, 4), 0) & 0x0FFFFFFF
                c = None if c >= 0x0FFFFFF8 else c
            else:
                c = u16(self.read(self.fat_start + c * 2, 2), 0)
                c = None if c >= 0xFFF8 else c

    def data(self, first, size=None):
        out = b"".join(self.read(self.data_start + (c - 2) * self.cbytes, self.cbytes) for c in self.chain(first))
        return out if size is None else out[:size]

    def listdir(self, cluster=None):
        if cluster is None:
            raw = self.data(self.rootclus) if self.kind == 32 else self.read(self.root_start, self.rootents * 32)
        else:
            raw = self.data(cluster)
        out, lfn = [], {}
        for i in range(0, len(raw) - 31, 32):
            e = raw[i:i + 32]
            if e[0] == 0:
                break
            if e[0] == 0xE5:
                lfn = {}
                continue
            if e[11] == 0x0F:
                lfn[e[0] & 0x1F] = (e[1:11] + e[14:26] + e[28:32]).decode("utf-16-le", "replace").split("\x00")[0]
                continue
            if e[11] & 0x08:
                lfn = {}
                continue
            if lfn:
                name = "".join(lfn[k] for k in sorted(lfn))
            else:
                base, ext = e[0:8].decode("latin-1").rstrip(), e[8:11].decode("latin-1").rstrip()
                base = base.lower() if e[12] & 0x08 else base
                ext = ext.lower() if e[12] & 0x10 else ext
                name = base + ("." + ext if ext else "")
            lfn = {}
            if name in (".", ".."):
                continue
            out.append({"name": name, "dir": bool(e[11] & 0x10), "cluster": (u16(e, 20) << 16) | u16(e, 26),
                        "size": u32(e, 28)})
        return out


def debugfs_path():
    for p in [os.environ.get("DEBUGFS"), shutil.which("debugfs"), "/sbin/debugfs", "/usr/sbin/debugfs",
              "/opt/homebrew/opt/e2fsprogs/sbin/debugfs", "/usr/local/opt/e2fsprogs/sbin/debugfs"]:
        if p and os.path.exists(p):
            return p
    raise SystemExit("needs debugfs (e2fsprogs)")


class Ext4:
    def __init__(self, img, offset):
        self.dbg, self.spec = debugfs_path(), "%s?offset=%d" % (img, offset)

    def run(self, cmd):
        r = subprocess.run([self.dbg, "-R", cmd, self.spec], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

    def cat(self, path):
        out, err = self.run("cat " + path)
        return None if "not found" in err or "File not found" in out else out

    def exists(self, path):
        out, err = self.run("stat " + path)
        return "not found" not in err and "Inode:" in out

    def ls(self, path):
        out, err = self.run("ls -p " + path)
        names = []
        for line in out.splitlines():
            bits = line.split("/")
            if len(bits) > 6 and bits[5] not in (".", ".."):
                names.append(bits[5])
        return names

    def rdump(self, path, dest):
        self.run("rdump %s %s" % (path, dest))
        return os.path.join(dest, os.path.basename(path))

    def stats(self):
        out, _ = self.run("stats")
        kv = {}
        for line in out.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                kv[k.strip()] = v.strip()
        bs = int(kv.get("Block size", "4096"))
        return {"block_size": bs, "bytes": int(kv.get("Block count", "0")) * bs,
                "free_bytes": int(kv.get("Free blocks", "0")) * bs}


def packages(status):
    pk, cur = {}, {}
    for line in (status or "").splitlines() + [""]:
        if not line.strip():
            if cur.get("Status", "").endswith(" installed"):
                pk[cur["Package"]] = cur.get("Version", "")
            cur = {}
        elif line[0] not in " \t" and ":" in line:
            k, v = line.split(":", 1)
            cur[k] = v.strip()
    return pk


def units(folder):
    """Enabled units (symlinks in *.wants / *.requires), masked units, and the default target, from a dumped
    /etc/systemd/system (or the static wants in /usr/lib/systemd/system)."""
    wants, masked, default = {}, [], None
    if not os.path.isdir(folder):
        return wants, masked, default
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if os.path.islink(p):
            target = os.readlink(p)
            if target == "/dev/null":
                masked.append(name)
            elif name == "default.target":
                default = os.path.basename(target)
        elif os.path.isdir(p) and (name.endswith(".wants") or name.endswith(".requires")):
            wants[name] = sorted(os.listdir(p))
    return wants, masked, default


def inspect(img):
    facts = {"file": os.path.basename(img), "image_bytes": os.path.getsize(img)}
    with open(img, "rb") as f:
        facts["disk_id"], parts = partitions(f)
        facts["partitions"] = parts
        boot = next(p for p in parts if p["type"] in ("0x0c", "0x0b", "0x0e", "0x06"))
        root = next(p for p in parts if p["type"] == "0x83")
        fat = Fat(f, boot["start"])
        top = fat.listdir()
        files = {e["name"]: e for e in top}
        sub = {e["name"]: fat.listdir(e["cluster"]) for e in top if e["dir"]}
        b = {"fat": fat.kind, "files": sorted(n for n, e in files.items() if not e["dir"] and not n.endswith(".dtb")),
             "dirs": {n: len(v) for n, v in sub.items()}, "dtbs": sorted(n for n in files if n.endswith(".dtb")),
             "bytes_used": sum(e["size"] for e in top) + sum(e["size"] for v in sub.values() for e in v)}
        for name in ("config.txt", "cmdline.txt", "sofa-box.txt", "issue.txt"):
            if name in files:
                b[name] = fat.data(files[name]["cluster"], files[name]["size"]).decode("utf-8", "replace")
        facts["boot"] = b
    fs = Ext4(img, root["start"])
    facts["root"] = fs.stats()
    facts["root"]["used_bytes"] = facts["root"]["bytes"] - facts["root"]["free_bytes"]
    facts["packages"] = packages(fs.cat("/var/lib/dpkg/status"))
    tmp = tempfile.mkdtemp(prefix="inspect-card-")
    try:
        etc = fs.rdump("/etc/systemd/system", tmp)
        wants, masked, default = units(etc)
        os.makedirs(os.path.join(tmp, "usr"), exist_ok=True)
        lib = fs.rdump("/usr/lib/systemd/system", os.path.join(tmp, "usr"))
        static, _, _ = units(lib)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    facts["enabled"] = wants
    facts["static_wants"] = {t: v for t, v in static.items() if t[:-6] in TARGETS or t[:-9] in TARGETS}
    facts["masked"] = masked
    facts["default_target"] = default
    enabled_units = {u for v in wants.values() for u in v}
    static_units = {u for v in static.values() for u in v}
    facts["watched_units"] = {u: ("enabled" if u + ".service" in enabled_units else
                                  "static" if u + ".service" in static_units else
                                  "masked" if u + ".service" in masked else
                                  "present" if fs.exists("/usr/lib/systemd/system/%s.service" % u) or
                                  fs.exists("/etc/systemd/system/%s.service" % u) else "absent")
                              for u in WATCH}
    shadow = {}
    for line in (fs.cat("/etc/shadow") or "").splitlines():     # only whether there's a password, never the hash
        bits = line.split(":")
        if len(bits) > 1:
            pw = bits[1]
            shadow[bits[0]] = "none (empty)" if pw == "" else "locked" if pw[:1] in ("!", "*") else "set"
    groups = {}
    for line in (fs.cat("/etc/group") or "").splitlines():
        bits = line.split(":")
        if len(bits) == 4:
            for m in filter(None, bits[3].split(",")):
                groups.setdefault(m, []).append(bits[0])
    users = []
    for line in (fs.cat("/etc/passwd") or "").splitlines():
        bits = line.split(":")
        if len(bits) == 7 and (int(bits[2]) >= 1000 and int(bits[2]) < 65534 or bits[2] == "0"):
            users.append({"name": bits[0], "uid": int(bits[2]), "shell": bits[6], "password": shadow.get(bits[0], "?"),
                          "groups": sorted(groups.get(bits[0], []))})
    facts["users"] = users
    sudoers = fs.ls("/etc/sudoers.d")
    facts["sudoers.d"] = sorted(sudoers)
    os_release = fs.cat("/usr/lib/os-release") or fs.cat("/etc/os-release") or ""     # (/etc's is a symlink)
    facts["os"] = next((l.split("=", 1)[1].strip('"') for l in os_release.splitlines() if l.startswith("PRETTY_NAME=")), "?")
    facts["hostname"] = (fs.cat("/etc/hostname") or "").strip()
    facts["machine_id"] = (fs.cat("/etc/machine-id") or "").strip()
    facts["fstab"] = [l for l in (fs.cat("/etc/fstab") or "").splitlines() if l.strip() and not l.startswith("#")]
    facts["first_start"] = {
        "cloud-init installed": "cloud-init" in facts["packages"],
        "cloud-init switched off for good (/etc/cloud/cloud-init.disabled)": fs.exists("/etc/cloud/cloud-init.disabled"),
        "userconf-pi installed": "userconf-pi" in facts["packages"],
        "rpi-cloud-init-mods installed": "rpi-cloud-init-mods" in facts["packages"],
        "rpi-preseed installed": "rpi-preseed" in facts["packages"],
        "Imager's firstrun helper (raspberrypi-sys-mods imager_custom)": fs.exists("/usr/lib/raspberrypi-sys-mods/imager_custom"),
        "first-start resize in the initramfs (resize_early)": fs.exists("/usr/share/initramfs-tools/scripts/local-premount/resize_early"),
    }
    facts["kernels"] = sorted(fs.ls("/usr/lib/modules"))
    facts["firmware"] = {n: fs.exists("/usr/lib/firmware/" + n) for n in FIRMWARE}
    facts["box_version"] = (fs.cat("/usr/local/lib/sofa-box/VERSION") or "").strip()
    return facts


def mib(n):
    return "%.0f MiB" % (n / 1048576.0)


def compare(a, b):
    out = []
    w = out.append
    w("| | %s | %s |" % (a["file"], b["file"]))
    w("|---|---|---|")
    rows = [
        ("Sofa Box OS", a["box_version"], b["box_version"]),
        ("Base", a["os"], b["os"]),
        ("Written to the card", mib(a["image_bytes"]), mib(b["image_bytes"])),
        ("Boot partition (FAT%s / FAT%s)" % (a["boot"]["fat"], b["boot"]["fat"]),
         "%s, %s used" % (mib(a["partitions"][0]["bytes"]), mib(a["boot"]["bytes_used"])),
         "%s, %s used" % (mib(b["partitions"][0]["bytes"]), mib(b["boot"]["bytes_used"]))),
        ("Root partition (before the first start grows it)",
         "%s, %s used, %s free" % (mib(a["root"]["bytes"]), mib(a["root"]["used_bytes"]), mib(a["root"]["free_bytes"])),
         "%s, %s used, %s free" % (mib(b["root"]["bytes"]), mib(b["root"]["used_bytes"]), mib(b["root"]["free_bytes"]))),
        ("Packages", str(len(a["packages"])), str(len(b["packages"]))),
        ("Kernels", " ".join(a["kernels"]), " ".join(b["kernels"])),
        ("Starts into", str(a["default_target"]), str(b["default_target"])),
        ("Host name", a["hostname"], b["hostname"]),
        ("machine-id (\"uninitialized\" = first start)", a["machine_id"], b["machine_id"]),
        ("Users", "; ".join("%s (uid %d, password %s)" % (u["name"], u["uid"], u["password"]) for u in a["users"]),
         "; ".join("%s (uid %d, password %s)" % (u["name"], u["uid"], u["password"]) for u in b["users"])),
        ("sudoers.d", " ".join(a["sudoers.d"]), " ".join(b["sudoers.d"])),
        ("cmdline.txt", "`%s`" % a["boot"].get("cmdline.txt", "").strip(), "`%s`" % b["boot"].get("cmdline.txt", "").strip()),
        ("fstab", "<br>".join("`%s`" % l for l in a["fstab"]), "<br>".join("`%s`" % l for l in b["fstab"])),
    ]
    for k in a["first_start"]:
        rows.append((k, "yes" if a["first_start"][k] else "no", "yes" if b["first_start"].get(k) else "no"))
    for k in a["firmware"]:
        rows.append(("firmware " + k, "yes" if a["firmware"][k] else "no", "yes" if b["firmware"].get(k) else "no"))
    for k in a["watched_units"]:
        if a["watched_units"][k] != "absent" or b["watched_units"].get(k) != "absent":
            rows.append(("unit %s" % k, a["watched_units"][k], b["watched_units"].get(k, "absent")))
    for r in rows:
        w("| %s | %s | %s |" % r)

    pa, pb = a["packages"], b["packages"]
    only_a, only_b = sorted(set(pa) - set(pb)), sorted(set(pb) - set(pa))
    differ = sorted(p for p in set(pa) & set(pb) if pa[p] != pb[p])
    w("\n### Packages only on %s (%d)\n\n%s" % (a["file"], len(only_a), " ".join("`%s`" % p for p in only_a) or "none"))
    w("\n### Packages only on %s (%d)\n\n%s" % (b["file"], len(only_b), " ".join("`%s`" % p for p in only_b) or "none"))
    w("\n### Same package, another version (%d)\n" % len(differ))
    for p in differ:
        w("- `%s`: %s → %s" % (p, pa[p], pb[p]))

    w("\n### Units enabled at boot (symlinks in /etc/systemd/system)\n")
    for t in sorted(set(a["enabled"]) | set(b["enabled"])):
        ua, ub = set(a["enabled"].get(t, [])), set(b["enabled"].get(t, []))
        both = sorted(ua & ub)
        w("- **%s**: both: %s%s%s" % (t, " ".join(both) or "none",
                                       "; only %s: %s" % (a["file"], " ".join(sorted(ua - ub))) if ua - ub else "",
                                       "; only %s: %s" % (b["file"], " ".join(sorted(ub - ua))) if ub - ua else ""))
    ma, mb = set(a["masked"]), set(b["masked"])
    w("- **masked**: both: %s; only %s: %s; only %s: %s" % (" ".join(sorted(ma & mb)) or "none", a["file"],
                                                            " ".join(sorted(ma - mb)) or "none", b["file"],
                                                            " ".join(sorted(mb - ma)) or "none"))

    w("\n### Boot partition files\n")
    fa, fb = set(a["boot"]["files"]), set(b["boot"]["files"])
    w("- both: %s" % " ".join(sorted(fa & fb)))
    w("- only %s: %s" % (a["file"], " ".join(sorted(fa - fb)) or "none"))
    w("- only %s: %s" % (b["file"], " ".join(sorted(fb - fa)) or "none"))
    w("- device trees: %d and %d; only %s: %s; only %s: %s" % (
        len(a["boot"]["dtbs"]), len(b["boot"]["dtbs"]), a["file"], " ".join(sorted(set(a["boot"]["dtbs"]) - set(b["boot"]["dtbs"]))) or "none",
        b["file"], " ".join(sorted(set(b["boot"]["dtbs"]) - set(a["boot"]["dtbs"]))) or "none"))
    w("- folders: %s and %s" % (a["boot"]["dirs"], b["boot"]["dirs"]))
    for name in ("config.txt",):
        w("\n### %s\n" % name)
        for card in (a, b):
            w("%s:\n\n```\n%s\n```" % (card["file"], card["boot"].get(name, "(none)").strip()))
    return "\n".join(out) + "\n"


def main(argv):
    if len(argv) == 4 and argv[1] == "--compare":
        a, b = (json.load(open(p)) for p in argv[2:4])
        sys.stdout.write(compare(a, b))
    elif len(argv) == 2:
        json.dump(inspect(argv[1]), sys.stdout, indent=1, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
