# Sofa Box OS with rpi-image-gen (a prototype)

A second way to make the Sofa box card, beside [`tools/build-sofa-box-image.sh`](../build-sofa-box-image.sh), which
still makes every card on the releases page. Here the card is built from Raspberry Pi OS's own packages with
Raspberry Pi's [rpi-image-gen](https://github.com/raspberrypi/rpi-image-gen), instead of downloading Raspberry Pi
OS Lite ("latest") and changing it. It is a prototype: nothing here publishes a release, and only a card tested on a
real Pi should ever replace today's.

## What's different from today's card

- **The base is built, not downloaded.** Debian Trixie arm64 plus Raspberry Pi's repository
  (archive.raspberrypi.com), the same packages Raspberry Pi OS is made of, chosen in
  [`config/sofa-box.yaml`](config/sofa-box.yaml) and [`layer/sofa-box-os.yaml`](layer/sofa-box-os.yaml).
  Today's card starts from whatever Raspberry Pi OS Lite image is "latest" on the day.
- **No cloud-init, no userconf-pi, no first-start user questions.** Raspberry Pi Imager's OS customisation has
  nothing on this card to act on through cloud-init; see the pull request for what each Imager version does.
- **The same box, set up the same way.** The box's own installer, `deploy/sofa-box/install.sh --image`, runs in the
  card's root exactly as `build-sofa-box-image.sh` runs it ([`customize50-sofa-box`](layer/sofa-box-os.d/hooks/customize50-sofa-box)),
  unchanged. rpi-image-gen builds in its own PID namespace, where `systemctl` doesn't see a chroot, so the installer
  runs with `SYSTEMD_OFFLINE=1` (what `systemctl` does in a chroot anyway). `config.txt` and `cmdline.txt` only exist
  once rpi-image-gen puts them together from its layers, so the box's own `sofa-box setup-boot` runs on them then
  ([`late/preimage90-sofa-box`](layer/sofa-box-os.d/hooks/late/preimage90-sofa-box)).
- **What Raspberry Pi OS Lite brings without being asked** had to be named: Avahi, polkit, wpa_supplicant,
  `raspberrypi-net-mods`, `busybox` for the initramfs, the sound cards' profiles, `locales` and more (the list, with
  why each, is in [`layer/sofa-box-os.yaml`](layer/sofa-box-os.yaml)). The comparison with today's card shows what's
  still left out (compilers, cloud-init, cron, the camera apps, Raspberry Pi Connect…).
- **One card for a Pi 3 B+, 4 or 5.** rpi-image-gen's `rpi3` device layer (the 64-bit `v8` kernel, the boot
  firmware for every board, Wi-Fi and Bluetooth firmware), plus the Pi 5's own kernel as a package, and
  `arm_64bit=1` as on Raspberry Pi OS. (rpi-image-gen's own Pi 5 kernel layer isn't used: it makes the root
  filesystem's blocks 16 KB, which a Pi 3 or 4 can't read.)
- **Raspberry Pi OS's own first start**, from its `raspberrypi-sys-mods` package: the card grows to fill the SD card,
  gets a new disk id and new SSH host keys. SSH is off; an empty file named `ssh` on the boot partition turns it on.
  As pi-gen does, `rpi-resize.service` is enabled and `/etc/machine-id` says `uninitialized` (left empty, systemd
  wouldn't count the start as the first).
- **Users:** `pi` (uid 1000, no password: nobody can sign in until one is set) and `sofabox`, which runs Sofa on the
  TV, as on today's card.

## Building it

GitHub builds it on its Arm computers ([the workflow](../../.github/workflows/sofa-box-image-gen.yml)), by hand
or on every push to the `claude/image-gen` branch, and keeps it for a week under the run's **Artifacts**
(`sofa-box-card-imagegen`):

- `sofa-box-os-VERSION-imagegen.img.xz` and its `.sha256`: the card;
- `…-report.txt`: what's on it (the same lines as today's report, saying "image-gen prototype");
- `….sbom.spdx.json`: the software bill of materials (rpi-image-gen's, made with syft);
- `…-cve.txt` and `…-cve.json`: known vulnerabilities in those packages (grype, from the SBOM);
- `…-comparison.md` and the two `…-facts.json`: this card next to today's card of the same version.

On an Arm computer of your own (Raspberry Pi OS 64-bit, or Debian Bookworm or Trixie arm64), as a normal user:

```
git clone https://github.com/raspberrypi/rpi-image-gen.git ~/rpi-image-gen
git -C ~/rpi-image-gen checkout d2d5705bcb37284c4b08c0ce43c039b1f1004e25    # the commit the workflow pins
sudo ~/rpi-image-gen/install_deps.sh
tools/image-gen/build.sh --rpi-image-gen ~/rpi-image-gen out --sofa http://192.168.1.20:8090
```

`--sofa` is optional, as for today's card. rpi-image-gen does the build in a user namespace (`podman unshare`): no
`sudo` for the build itself.

## Reading a card without a Pi

[`inspect-card.py`](inspect-card.py) reads a card image (`.img`) without starting it or mounting it: its partitions,
the boot partition's files, `config.txt` and `cmdline.txt`, the packages, the services enabled at boot, the users
(whether each has a password, never the password), and what's there for the first start. It needs Python 3 and
`debugfs` (e2fsprogs; on a Mac, `brew install e2fsprogs`).

```
python3 tools/image-gen/inspect-card.py today.img > today.json
python3 tools/image-gen/inspect-card.py new.img > new.json
python3 tools/image-gen/inspect-card.py --compare today.json new.json
```
