#!/bin/sh
# Make a Sofa box disk image for an x86-64 PC or virtual machine: plain Debian 13 (Trixie) with the Sofa box set up by
# the same install.sh a card gets, run the same way (SOFA_BOX_USER=sofabox … install.sh --image). It boots with UEFI
# and with BIOS (GRUB both ways, on one GPT disk), so the one image serves UTM, VirtualBox, VMware, Proxmox and QEMU,
# and written to a USB stick it starts a real PC. docs/hardware.md says how to use it and what is proven.
#
#   sudo tools/build-sofa-box-vm-image.sh [OUT_DIR] [--sofa http://192.168.1.20:8090] [--size 8G] [--password WORD]
#
# On Linux, x86-64, as root, with: mmdebstrap, Debian's archive keyring (tools/debian-archive-keyring.txt pins the
# package that holds it, and it's fetched when the host hasn't got Trixie's key), sfdisk, losetup, mkfs.vfat, mkfs.ext4,
# qemu-img, xz. GitHub builds and boots it (.github/workflows/sofa-box-vm.yml).
#
# Writes OUT_DIR/sofa-box-os-VERSION-x86_64.img (raw, for the boot test and USB sticks; also .img.xz),
# sofa-box-os-VERSION-x86_64.qcow2.xz (for virtual machines), their .sha256, and a report like the card's.
#
# On the image: the user "sofa" (uid 1000, sudo) and "sofabox", which runs Sofa on the TV. As on the Pi card, "sofa"
# has no password and SSH is off: a copy written to a USB stick for someone's PC has no login anyone could know.
# --password WORD (a test build of your own, for a VM): "sofa" gets that password, to be changed at the first login
# (Ctrl+Alt+F2 gives a console), and SSH is on. The root partition grows to the disk at the first start
# (systemd-repart and x-systemd.growfs): a 4 GB image written to a 32 GB stick has the 32 GB.
set -eu
OUT=out SOFA="" SIZE=8G PASSWORD=""
while [ $# -gt 0 ]; do
  case "$1" in
    --sofa) SOFA="${2%/}"; shift ;;
    --size) SIZE="$2"; shift ;;
    --password) PASSWORD="$2"; shift ;;
    -*) echo "Unknown option: $1"; exit 1 ;;
    *) OUT="$1" ;;
  esac
  shift
done
[ "$(id -u)" = 0 ] || { echo "Run it with sudo."; exit 1; }
[ "$(uname -m)" = x86_64 ] || { echo "An x86-64 computer builds this image (it runs the image's own programs)."; exit 1; }
for t in mmdebstrap sfdisk losetup mkfs.vfat mkfs.ext4 qemu-img xz sha256sum chroot curl; do
  command -v "$t" >/dev/null || { echo "Needs $t (apt install mmdebstrap fdisk dosfstools e2fsprogs qemu-utils xz-utils)."; exit 1; }
done
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VER="$(tr -d ' \n' < "$REPO/deploy/sofa-box/VERSION" 2>/dev/null || true)"
VER="${VER:-0.0.0}"
NAME="sofa-box-os-$VER-x86_64"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
WORK="$(mktemp -d)"
ROOT="$WORK/root"
IMG="$WORK/$NAME.img"
LOOP=""
MIRROR="${SOFA_BOX_DEBIAN_MIRROR:-https://deb.debian.org/debian}"
SECURITY="${SOFA_BOX_DEBIAN_SECURITY:-https://security.debian.org/debian-security}"
COMPONENTS="main contrib non-free-firmware"

cleanup() {
  set +e
  for m in run sys proc dev/pts dev boot/efi; do mountpoint -q "$ROOT/$m" && umount -l "$ROOT/$m"; done
  mountpoint -q "$ROOT" && umount -l "$ROOT"
  [ -n "$LOOP" ] && losetup -d "$LOOP"
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

echo "== Debian's archive key"
# Trixie's archive key: the host's keyring if it has it (Debian 13, or a debian-archive-keyring new enough), else
# the pinned keyring package from Debian's own archive, checked against its SHA-256 (tools/debian-archive-keyring.txt).
PIN="$REPO/tools/debian-archive-keyring.txt"
KEYRING=""
for k in /usr/share/keyrings/debian-archive-keyring.gpg; do
  if [ -f "$k" ] && gpg --no-default-keyring --keyring "$k" --list-keys 2>/dev/null | grep -q 'trixie'; then KEYRING="$k"; fi
done
if [ -z "$KEYRING" ]; then
  URL="$(sed -n 's/^url=//p' "$PIN" | head -n 1)"; SUM="$(sed -n 's/^sha256=//p' "$PIN" | head -n 1)"
  [ -n "$URL" ] && echo "$SUM" | grep -Eq '^[0-9a-f]{64}$' || { echo "No url= and sha256= lines in $PIN."; exit 1; }
  curl -fsSL --retry 3 -o "$WORK/keyring.deb" "$URL"
  echo "$SUM  $WORK/keyring.deb" | sha256sum -c - || { echo "Stopped: $(basename "$URL") isn't the package with SHA-256 $SUM."; exit 1; }
  mkdir -p "$WORK/keyring" && dpkg-deb -x "$WORK/keyring.deb" "$WORK/keyring"
  KEYRING="$WORK/keyring/usr/share/keyrings/debian-archive-keyring.gpg"
  echo "   $(basename "$URL") (pinned)"
else
  echo "   $KEYRING (this computer's)"
fi

echo "== The disk ($SIZE): GPT, for BIOS and UEFI"
truncate -s "$SIZE" "$IMG"
# 1: GRUB's BIOS boot partition; 2: the EFI system partition; 3: the root, with the type systemd-repart grows (x86-64 root)
sfdisk -q "$IMG" <<EOF
label: gpt
size=1MiB, type=21686148-6449-6E6F-744E-656564454649, name=bios
size=256MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name=esp
type=4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709, name=root
EOF
LOOP="$(losetup -fP --show "$IMG")"
mkfs.vfat -F 32 -n SOFABOOT "${LOOP}p2" >/dev/null
mkfs.ext4 -q -L sofabox "${LOOP}p3"
ESP_UUID="$(blkid -s UUID -o value "${LOOP}p2")"
ROOT_UUID="$(blkid -s UUID -o value "${LOOP}p3")"
mkdir -p "$ROOT"
mount "${LOOP}p3" "$ROOT"

echo "== Debian 13 (Trixie) from $MIRROR"
# What Debian itself needs to start on a PC or in a VM (the Sofa box's own packages come from install.sh, as on a card)
# (shim-signed and grub-efi-amd64-signed: Microsoft-signed shim and Debian-signed GRUB, so a PC with Secure Boot on,
# as most sold with Windows are, starts the stick as it is; Debian's kernel is signed already)
INCLUDE="linux-image-amd64,grub-efi-amd64,grub-efi-amd64-signed,shim-signed,grub-pc-bin,initramfs-tools,systemd-sysv,systemd-repart,dbus,zstd,ca-certificates,\
systemd-timesyncd,sudo,openssh-server,pciutils,usbutils,dosfstools,e2fsprogs,efibootmgr,wireless-regdb,qemu-guest-agent,intel-microcode,amd64-microcode,\
firmware-linux-free,firmware-misc-nonfree,firmware-iwlwifi,firmware-realtek,firmware-atheros,firmware-brcm80211,\
firmware-amd-graphics,firmware-intel-graphics,firmware-sof-signed,firmware-intel-sound"
mmdebstrap --arch=amd64 --variant=important --mode=root --keyring="$KEYRING" --include="$INCLUDE" \
  --aptopt='Acquire::Retries "3"' --dpkgopt='path-exclude=/usr/share/doc/*/*' --dpkgopt='path-include=/usr/share/doc/*/copyright' \
  trixie "$ROOT" \
  "deb $MIRROR trixie $COMPONENTS" \
  "deb $MIRROR trixie-updates $COMPONENTS" \
  "deb $SECURITY trixie-security $COMPONENTS"
mkdir -p "$ROOT/boot/efi"
mount "${LOOP}p2" "$ROOT/boot/efi"
for m in dev dev/pts proc sys run; do mount --bind "/$m" "$ROOT/$m"; done
cp --remove-destination /etc/resolv.conf "$ROOT/etc/resolv.conf"
printf '#!/bin/sh\nexit 101\n' > "$ROOT/usr/sbin/policy-rc.d"           # nothing starts while it's being built
chmod 755 "$ROOT/usr/sbin/policy-rc.d"

echo "== The computer's own files: fstab, hostname, users, the root that grows"
cat > "$ROOT/etc/fstab" <<EOF
UUID=$ROOT_UUID  /         ext4  defaults,noatime,x-systemd.growfs  0  1
UUID=$ESP_UUID  /boot/efi  vfat  umask=0077                        0  2
EOF
mkdir -p "$ROOT/etc/repart.d"
cat > "$ROOT/etc/repart.d/50-root.conf" <<'EOF'
# Sofa box: the root partition takes the whole disk at the first start (a bigger VM disk, a USB stick)
[Partition]
Type=root
EOF
echo sofabox > "$ROOT/etc/hostname"
printf '127.0.0.1\tlocalhost\n127.0.1.1\tsofabox\n\n::1\tlocalhost ip6-localhost ip6-loopback\nff02::1\tip6-allnodes\nff02::2\tip6-allrouters\n' > "$ROOT/etc/hosts"
# GRUB: a quiet start into the boot screen, as on the Pi's cmdline.txt; no menu; found by any UEFI (removable path)
cat > "$ROOT/etc/default/grub" <<'EOF'
GRUB_DEFAULT=0
GRUB_TIMEOUT=0
GRUB_TIMEOUT_STYLE=hidden
GRUB_DISTRIBUTOR="Sofa Box OS"
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash plymouth.ignore-serial-consoles logo.nologo vt.global_cursor_default=0 loglevel=3 console=tty3"
GRUB_CMDLINE_LINUX=""
GRUB_GFXPAYLOAD_LINUX=keep
GRUB_DISABLE_OS_PROBER=true
GRUB_DISABLE_RECOVERY=true
EOF
mkdir -p "$ROOT/tmp/sofa/deploy"
cp -r "$REPO/deploy/sofa-box" "$ROOT/tmp/sofa/deploy/"
cp -r "$REPO/client" "$REPO/sofa" "$REPO/sofa.py" "$REPO/LICENSE" "$ROOT/tmp/sofa/"     # Sofa itself too, for "This box"

echo "== The Sofa box (install.sh --image, as on a card)"
chroot "$ROOT" /bin/sh -eu -c "
  getent passwd 1000 >/dev/null || useradd -m -u 1000 -s /bin/bash sofa
  for g in sudo video audio input netdev render plugdev; do getent group \$g >/dev/null && usermod -aG \$g sofa || true; done
  if [ -n '$PASSWORD' ]; then                                      # (a test build: a login, changed at the first one)
    echo 'sofa:$PASSWORD' | chpasswd
    passwd -e sofa >/dev/null
  else
    usermod -p '!' sofa                                          # no password: no login anyone could know
  fi
  id -u sofabox >/dev/null 2>&1 || useradd -m -s /bin/bash sofabox
  passwd -l sofabox >/dev/null
  SOFA_BOX_USER=sofabox sh /tmp/sofa/deploy/sofa-box/install.sh --image $SOFA
  systemctl enable systemd-repart.service qemu-guest-agent.service >/dev/null 2>&1 || true
  if [ -n '$PASSWORD' ]; then systemctl enable ssh.service >/dev/null 2>&1 || true
  else systemctl disable ssh.service ssh.socket >/dev/null 2>&1 || true; fi
  grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=sofabox --removable --no-nvram --uefi-secure-boot >/dev/null
  grub-install --target=i386-pc '$LOOP' >/dev/null
  update-grub 2>/dev/null
  update-initramfs -u -k all >/dev/null 2>&1 || true              # the boot screen from the very start
  apt-get clean
  rm -rf /tmp/sofa /var/lib/apt/lists/* /etc/machine-id /var/lib/dbus/machine-id
  : > /etc/machine-id                                              # a first start of its own, like a new card
"
rm -f "$ROOT/usr/sbin/policy-rc.d"
# SSH's host keys are made on each computer at its first start, never shared by every copy of the image
rm -f "$ROOT/etc/ssh/ssh_host_"*
cat > "$ROOT/etc/systemd/system/sofa-box-ssh-keys.service" <<'EOF'
[Unit]
Description=Sofa box: this computer's own SSH host keys, at its first start
Before=ssh.service
ConditionPathExists=!/etc/ssh/ssh_host_ed25519_key

[Service]
Type=oneshot
ExecStart=/usr/bin/ssh-keygen -A

[Install]
WantedBy=multi-user.target
EOF
ln -sf /etc/systemd/system/sofa-box-ssh-keys.service "$ROOT/etc/systemd/system/multi-user.target.wants/sofa-box-ssh-keys.service"

echo "== What's on the image"
REPORT="$WORK/report.txt"
chroot "$ROOT" /bin/sh -c '
  echo "Sofa Box OS: $(cat /usr/local/lib/sofa-box/VERSION 2>/dev/null || echo missing) for x86-64 PCs and virtual machines"
  echo "System: $(. /etc/os-release; echo "$PRETTY_NAME"), kernel $(ls /boot/vmlinuz-* | sed "s|.*/vmlinuz-||" | tr "\n" " ")"
  dpkg-query -W -f="\${Package} \${Version}\n" cage chromium mpv ffmpeg plymouth python3 pipewire-pulse network-manager \
    vainfo mesa-va-drivers intel-media-va-driver i965-va-driver inputattach grub-efi-amd64 grub-efi-amd64-signed shim-signed grub-pc-bin systemd-repart luanti \
    2>/dev/null | sed "s/^/  /"
  echo "Sofa on the box (This box): $(cat /usr/local/lib/sofa-box/sofa-server/sofa/__init__.py 2>/dev/null | grep -o "__version__ = .*" || echo missing)"
  echo "Services: $(for s in sofa-box sofa-box-agent sofa-box-input sofa-box-cec sofa-box-tune systemd-repart ssh; do printf "%s=%s " $s "$(systemctl is-enabled $s 2>/dev/null)"; done)"
  echo "Starts into: $(systemctl get-default), a login on the TV (getty@tty1): $(systemctl is-enabled getty@tty1 2>/dev/null)"
  echo "Boot screen: $(plymouth-set-default-theme 2>/dev/null)  GRUB: $(grep -c menuentry /boot/grub/grub.cfg) entries, EFI: $(ls /boot/efi/EFI/BOOT 2>/dev/null | tr "\n" " ")"
  echo "Kernel command line: $(sed -n "s/^GRUB_CMDLINE_LINUX_DEFAULT=//p" /etc/default/grub)"
  echo "Chromium flags (/etc/chromium.d/sofa-box): $(grep -o -- "--[a-z-]*=[A-Za-z,]*" /etc/chromium.d/sofa-box | tr "\n" " ")"
  echo "HDMI-CEC: $(systemctl show -p ConditionPathExistsGlob --value sofa-box-cec 2>/dev/null; grep -c . /etc/udev/rules.d/61-sofa-box-cec.rules) udev lines"
  case "$(passwd -S sofa | awk "{print \$2}")" in L|NP) LOGIN="no password, as on the Pi card" ;; *) LOGIN="a password to change at the first login" ;; esac
  echo "Users: sofa (uid 1000, $LOGIN; SSH $(systemctl is-enabled ssh 2>/dev/null)), sofabox ($(id -nG sofabox | tr " " ","))"
  echo "Box files: $(ls /usr/local/lib/sofa-box | tr "\n" " ")"
  echo "Space: $(df -h / | tail -n 1 | awk "{print \$3\" used, \"\$4\" free\"}")"
' > "$REPORT" 2>&1 || true
chroot "$ROOT" dpkg-query -W -f='${db:Status-Abbrev} ${binary:Package} ${Version}\n' 2>/dev/null \
  | awk '$1 == "ii" { print "  " $2 " " $3 }' > "$WORK/packages.txt" || true
# the games whose data isn't free software are never on an image, as on a card
NONFREE="$(chroot "$ROOT" python3 -c 'import json; print(" ".join(p for g in json.load(open("/usr/local/lib/sofa-box/home/credits.json"))["groups"] for x in g["parts"] if x.get("game") and x.get("free") is False for p in x["packages"]))')"
for p in $NONFREE; do
  if chroot "$ROOT" dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q " installed$"; then
    echo "$p is on the image: its data isn't free software, so only a box installs it, when someone asks."; exit 1
  fi
done
echo "Not on the image (their data isn't free; a box installs them when asked): $NONFREE" >> "$REPORT"
echo "Built from: Debian trixie at $MIRROR on $(date -u +%Y-%m-%d) (packages at their versions of that day, listed below)" >> "$REPORT"
cat "$REPORT"
echo "Packages: $(wc -l < "$WORK/packages.txt" | tr -d ' '), each with its version in the report"
cat > "$ROOT/boot/efi/sofa-box.txt" <<EOF
Sofa Box OS $VER for x86-64 PCs and virtual machines, made $(date -u +%Y-%m-%d) from Debian 13 (Trixie).
Sofa: ${SOFA:-found on the home network by itself}
$([ -n "$PASSWORD" ] && echo "Login: sofa, with the password it was built with (change it at the first login; Ctrl+Alt+F2 or SSH)." || echo "No login: like the Pi card, nobody can sign in to it (no password, SSH off). The box sets itself up on the TV.")
Written to a USB stick (Sofa Box Imager, Raspberry Pi Imager, balenaEtcher or dd), it starts a PC from the stick and runs from it.
EOF
sync

echo "== Packing"
for m in run sys proc dev/pts dev boot/efi; do umount "$ROOT/$m"; done
umount "$ROOT"
e2fsck -fy "${LOOP}p3" >/dev/null || true
losetup -d "$LOOP"
LOOP=""
cp --sparse=always "$IMG" "$OUT/$NAME.img"
qemu-img convert -f raw -O qcow2 "$IMG" "$OUT/$NAME.qcow2"
xz -T0 -6 -c "$OUT/$NAME.qcow2" > "$OUT/$NAME.qcow2.xz"
xz -T0 -6 -c "$IMG" > "$OUT/$NAME.img.xz"
rm -f "$OUT/$NAME.qcow2"
(cd "$OUT" && sha256sum "$NAME.qcow2.xz" "$NAME.img.xz" > "$NAME.sha256")
{ cat "$REPORT"
  echo "Image: $NAME.qcow2.xz ($(du -h "$OUT/$NAME.qcow2.xz" | cut -f1) packed) for virtual machines; $NAME.img.xz ($(du -h "$OUT/$NAME.img.xz" | cut -f1)) for USB sticks and converters; $SIZE unpacked"
  echo; echo "== Packages on the image ($(wc -l < "$WORK/packages.txt" | tr -d ' ')), with their versions (dpkg-query -W)"; cat "$WORK/packages.txt"; } > "$OUT/$NAME-report.txt"
ls -lh "$OUT/$NAME.qcow2.xz" "$OUT/$NAME.img.xz"
echo "A VM: unpack the .qcow2.xz and add it as the disk (UTM, Proxmox, QEMU), or convert it (VirtualBox, VMware): docs/hardware.md"
