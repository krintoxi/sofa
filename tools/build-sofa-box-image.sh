#!/bin/sh
# Make a Sofa box card: Raspberry Pi OS Lite (64-bit) with the Sofa box already set up, ready to write
# to a microSD card with Raspberry Pi Imager ("Use custom"). For a Pi 3, 4 or 5.
#
#   sudo tools/build-sofa-box-image.sh [OUT_DIR] [--sofa http://192.168.1.20:8090] [--base FILE_OR_URL]
#
#   --sofa   the Sofa computer's address, built in (it still looks for Sofa itself if that changes)
#   --base   another Raspberry Pi OS Lite image (.img or .img.xz) instead of the latest one
#
# On Linux, as root. On an Arm computer (GitHub's ubuntu-24.04-arm, a Pi) it runs the Pi's own programs
# directly; elsewhere it needs qemu-user-static. GitHub builds it (.github/workflows/sofa-box-image.yml)
# and puts it on the releases page.
#
# On the card: the user "sofa" for SSH (no password until you give one; Raspberry Pi Imager's settings
# can, and can turn SSH and Wi-Fi on), and "sofabox", which runs Sofa on the TV.
set -eu
OUT=out SOFA="" BASE="https://downloads.raspberrypi.com/raspios_lite_arm64_latest"
while [ $# -gt 0 ]; do
  case "$1" in
    --sofa) SOFA="${2%/}"; shift ;;
    --base) BASE="$2"; shift ;;
    -*) echo "Unknown option: $1"; exit 1 ;;
    *) OUT="$1" ;;
  esac
  shift
done
[ "$(id -u)" = 0 ] || { echo "Run it with sudo."; exit 1; }
for t in curl xz parted losetup resize2fs e2fsck sha256sum chroot; do
  command -v "$t" >/dev/null || { echo "Needs $t (apt install curl xz-utils parted e2fsprogs)."; exit 1; }
done
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
WORK="$(mktemp -d)"
ROOT="$WORK/root"
LOOP=""

cleanup() {
  set +e
  for m in run sys proc dev/pts dev boot/firmware; do mountpoint -q "$ROOT/$m" && umount -l "$ROOT/$m"; done
  mountpoint -q "$ROOT" && umount -l "$ROOT"
  [ -n "$LOOP" ] && losetup -d "$LOOP"
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

echo "== Raspberry Pi OS Lite"
case "$BASE" in
  http*)
    FINAL="$(curl -fsSIL -o /dev/null -w '%{url_effective}' "$BASE")"
    echo "   $FINAL"
    curl -fL --retry 3 -o "$WORK/base.img.xz" "$FINAL"
    if curl -fsSL -o "$WORK/base.sha256" "$FINAL.sha256"; then
      echo "$(cut -d' ' -f1 "$WORK/base.sha256")  $WORK/base.img.xz" | sha256sum -c -
    else
      echo "   (no checksum published next to it)"
    fi
    SRC="$WORK/base.img.xz" ;;
  *) SRC="$BASE" ;;
esac
case "$SRC" in
  *.xz) xz -dc "$SRC" > "$WORK/sofa-box.img" ;;
  *) cp "$SRC" "$WORK/sofa-box.img" ;;
esac

echo "== Room for the Sofa box (Chromium, mpv…)"
truncate -s +2G "$WORK/sofa-box.img"
parted -s "$WORK/sofa-box.img" resizepart 2 100%
LOOP="$(losetup -fP --show "$WORK/sofa-box.img")"
e2fsck -fy "${LOOP}p2" >/dev/null || true
resize2fs "${LOOP}p2" >/dev/null
mkdir -p "$ROOT"
mount "${LOOP}p2" "$ROOT"
mount "${LOOP}p1" "$ROOT/boot/firmware"
for m in dev dev/pts proc sys run; do mount --bind "/$m" "$ROOT/$m"; done
if [ "$(uname -m)" != aarch64 ]; then
  Q="$(command -v qemu-aarch64-static || true)"
  [ -n "$Q" ] || { echo "Not an Arm computer: needs qemu-user-static (apt install qemu-user-static binfmt-support)."; exit 1; }
  cp "$Q" "$ROOT/usr/bin/"
fi
cp --remove-destination /etc/resolv.conf "$ROOT/etc/resolv.conf"
printf '#!/bin/sh\nexit 101\n' > "$ROOT/usr/sbin/policy-rc.d"           # nothing starts while it's being built
chmod 755 "$ROOT/usr/sbin/policy-rc.d"

echo "== The Sofa box"
mkdir -p "$ROOT/tmp/sofa/deploy" "$ROOT/tmp/sofa/client/vendor"
cp -r "$REPO/deploy/sofa-box" "$ROOT/tmp/sofa/deploy/"
cp -r "$REPO/client/vendor/fonts" "$ROOT/tmp/sofa/client/vendor/"
chroot "$ROOT" /bin/sh -eu -c "
  id -u sofa >/dev/null 2>&1 || getent passwd 1000 >/dev/null || useradd -m -u 1000 -s /bin/bash -G sudo,video,audio,input,netdev sofa
  id -u sofabox >/dev/null 2>&1 || useradd -m -s /bin/bash sofabox
  passwd -l sofabox >/dev/null
  systemctl disable userconfig.service 2>/dev/null || true       # no 'new user name?' questions on the TV
  echo sofabox > /etc/hostname
  sed -i 's/\\braspberrypi\\b/sofabox/g' /etc/hosts
  SOFA_BOX_USER=sofabox sh /tmp/sofa/deploy/sofa-box/install.sh --image $SOFA
  update-initramfs -u -k all >/dev/null 2>&1 || true              # the boot screen from the very start
  apt-get clean
  rm -rf /tmp/sofa /var/lib/apt/lists/*
"
rm -f "$ROOT/usr/sbin/policy-rc.d" "$ROOT/usr/bin/qemu-aarch64-static"
cat > "$ROOT/boot/firmware/sofa-box.txt" <<EOF
Sofa box card, made $(date -u +%Y-%m-%d) from $(basename "${FINAL:-$SRC}").
Sofa: ${SOFA:-found on the home network by itself}
Check it over SSH: sofa-box doctor
EOF
sync

NAME="sofa-box-$(date -u +%Y-%m-%d)"
echo "== Packing $NAME.img.xz"
cleanup_mounts() {
  for m in run sys proc dev/pts dev boot/firmware; do umount "$ROOT/$m"; done
  umount "$ROOT"
  e2fsck -fy "${LOOP}p2" >/dev/null || true
  losetup -d "$LOOP"
  LOOP=""
}
cleanup_mounts
xz -T0 -6 -c "$WORK/sofa-box.img" > "$OUT/$NAME.img.xz"
(cd "$OUT" && sha256sum "$NAME.img.xz" > "$NAME.img.xz.sha256")
ls -lh "$OUT/$NAME.img.xz"
echo "Write it to a card with Raspberry Pi Imager: Choose OS -> Use custom -> $NAME.img.xz"
