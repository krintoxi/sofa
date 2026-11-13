#!/bin/sh
# Boot a Sofa box x86-64 disk image in QEMU and prove it works: the box's helper answers on 127.0.0.1:8091, Sofa on
# the box answers /api/info on its port (8095), the TV's screen (cage with Chromium) is up, the phone remote answers
# from outside, and the console log says so. GitHub runs it on every image it builds (.github/workflows/sofa-box-vm.yml);
# it runs on any Linux with QEMU (with KVM it takes a few minutes; without, longer).
#
#   sudo tools/boot-sofa-box-vm.sh IMAGE.img OUT_DIR [--firmware uefi|uefi-secure|bios] [--timeout SECONDS] [--disk 16G]
#   sudo tools/boot-sofa-box-vm.sh IMAGE.img OUT_DIR --firmware uefi --install-onto 16G [--then "uefi-secure bios"]
#   sudo tools/boot-sofa-box-vm.sh DISC.iso OUT_DIR [--firmware …] [--install-onto 16G --then uefi]
#
# uefi-secure: OVMF with Secure Boot on and Microsoft's keys enrolled, as on most PCs sold with Windows (q35, SMM).
#
# --disk: the copy is made that big first, like the image written to a bigger USB stick, and the checks include that
# the box's root has grown to fill it at the first start.
#
# --install-onto SIZE: Install on this computer. The copy is a USB stick (xHCI) in a PC with a blank drive of SIZE
# (virtio, /dev/vda); inside, the checks ask the box's agent for its drives and install on that one the way Settings
# does on the TV (/box/api/install), then switch off. Then the PC starts from its drive alone, once for each
# firmware in --then (Secure Boot, then BIOS, unless it says otherwise), with the usual checks, and that the root is
# the drive's and fills it. Logs: console-install-<firmware>.log, console-installed-<firmware>.log.
#
# DISC.iso: the live DVD (tools/build-sofa-box-dvd.sh), started as a disc in the PC's DVD drive. The test's changes go
# on a copy of the disc as a small layer of their own (/live/zz-proof.squashfs, which live-boot puts over the system)
# and in its GRUB menu; the checks add that it runs from the disc. With --install-onto, the install is from the disc.
# Logs: console-dvd-<firmware>.log, console-install-dvd-<firmware>.log, console-installed-dvd-<firmware>.log.
#
# It never touches the image: it boots a copy, with two changes a test needs: the kernel's console on the serial port
# (so the log is a file) and a small service that runs the checks inside the VM, prints "SOFA-BOX-PROOF …" lines and
# switches the VM off. Exit 0 when every check passed; the console log is OUT_DIR/console-<firmware>.log.
set -eu
IMG="" OUT="" FW=uefi TIMEOUT=900 DISK="" ONTO="" THEN="uefi-secure bios"
while [ $# -gt 0 ]; do
  case "$1" in
    --firmware) FW="$2"; shift ;;
    --disk) DISK="$2"; shift ;;
    --install-onto) ONTO="$2"; shift ;;
    --then) THEN="$2"; shift ;;
    --timeout) TIMEOUT="$2"; shift ;;
    -*) echo "Unknown option: $1"; exit 1 ;;
    *) if [ -z "$IMG" ]; then IMG="$1"; else OUT="$1"; fi ;;
  esac
  shift
done
[ -n "$IMG" ] && [ -n "$OUT" ] || { echo "sudo tools/boot-sofa-box-vm.sh IMAGE.img OUT_DIR [--firmware uefi|bios]"; exit 1; }
[ "$(id -u)" = 0 ] || { echo "Run it with sudo (it mounts the copy to add the test's service)."; exit 1; }
for t in qemu-system-x86_64 losetup; do command -v "$t" >/dev/null || { echo "Needs $t (apt install qemu-system-x86 ovmf)."; exit 1; }; done
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
WORK="$(mktemp -d)"
COPY="$WORK/test.img"
LOG="$OUT/console-$FW.log"
LOOP=""
cleanup() {
  set +e
  for d in "$WORK/m" "$WORK/sq" "$WORK/iso"; do mountpoint -q "$d" && umount "$d"; done
  [ -n "$LOOP" ] && losetup -d "$LOOP"
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

echo "== A copy of $(basename "$IMG"), with the test's service in it ($FW)"
DVD="" KIND=""
case "$IMG" in *.iso) DVD=yes KIND="dvd-" ;; esac
mkdir -p "$WORK/m"
M="$WORK/m"
if [ -n "$DVD" ]; then                       # the disc: the test's files in a layer of their own, and its GRUB menu
  for t in xorriso mksquashfs; do command -v "$t" >/dev/null || { echo "Needs $t (apt install xorriso squashfs-tools)."; exit 1; }; done
  mkdir -p "$WORK/iso" "$WORK/sq" "$M/etc/default" "$M/usr/local/lib/sofa-box" "$M/etc/systemd/system"
  mount -o loop,ro "$IMG" "$WORK/iso"
  mount -o loop,ro "$WORK/iso/live/filesystem.squashfs" "$WORK/sq"
  cp "$WORK/sq/etc/default/grub" "$M/etc/default/grub"
  cp "$WORK/iso/boot/grub/grub.cfg" "$WORK/grub.cfg"
  umount "$WORK/sq"
  umount "$WORK/iso"
  echo yes > "$M/etc/sofa-box-vm-dvd"                                      # (and check it runs from the disc)
  GRUBCFG="$WORK/grub.cfg"
else
  case "$IMG" in
    *.xz) xz -dc "$IMG" > "$COPY" ;;
    *) cp --sparse=always "$IMG" "$COPY" ;;
  esac
  if [ -n "$DISK" ]; then                    # a bigger "stick" than the image: the end of it is empty, as on a real one
    truncate -s "$DISK" "$COPY"
  fi
  LOOP="$(losetup -fP --show "$COPY")"
  mount "${LOOP}p3" "$M"
  GRUBCFG="$M/boot/grub/grub.cfg"
fi
[ -n "$DISK" ] && stat -c %s "$COPY" > "$M/etc/sofa-box-vm-disk-bytes"   # (the checks compare the root with it)
[ "$FW" = uefi-secure ] && echo on > "$M/etc/sofa-box-vm-secure-boot"     # (and check Secure Boot really was on)
[ -n "$ONTO" ] && echo /dev/vda > "$M/etc/sofa-box-vm-install-to"         # (install on the blank drive, then off)
# the kernel and systemd talk on the serial port (the log), and the boot screen stays out of the way (in GRUB's
# settings too, so the drive it's installed on, whose list is made again, does the same)
for f in "$GRUBCFG" "$M/etc/default/grub"; do
  sed -i -E 's/\b(quiet|splash)\b ?//g; s/(console=tty3)/\1 console=ttyS0,115200n8 systemd.show_status=1 plymouth.enable=0/' "$f"
  grep -q 'console=ttyS0' "$f" || { echo "Couldn't put the console on the serial port ($f changed?)."; exit 1; }
done
install -m 755 "$HERE/sofa-box-vm-proof.sh" "$M/usr/local/lib/sofa-box/vm-proof.sh"
cat > "$M/etc/systemd/system/sofa-box-vm-proof.service" <<'EOF'
[Unit]
Description=Sofa box: the VM boot test (only on a test copy of the image)
After=sofa-box-agent.service sofa-box.service network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/lib/sofa-box/vm-proof.sh
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=1800

[Install]
WantedBy=multi-user.target
EOF
mkdir -p "$M/etc/systemd/system/multi-user.target.wants"
ln -sf /etc/systemd/system/sofa-box-vm-proof.service "$M/etc/systemd/system/multi-user.target.wants/sofa-box-vm-proof.service"
if [ -n "$DVD" ]; then
  COPY="$WORK/test.iso"
  mksquashfs "$M" "$WORK/proof.squashfs" -noappend -quiet -no-progress -all-root
  xorriso -indev "$IMG" -outdev "$COPY" -boot_image any replay \
    -map "$WORK/proof.squashfs" /live/zz-proof.squashfs -map "$GRUBCFG" /boot/grub/grub.cfg 2>&1 | tail -n 3
  [ -s "$COPY" ] || { echo "Couldn't make the test's copy of the disc."; exit 1; }
  rm -rf "$M"
  mkdir -p "$M"
else
  umount "$M"
  losetup -d "$LOOP"
  LOOP=""
fi
# The copy as the PC sees it: a disc in its DVD drive, or the stick (a disk; on USB when it's installed from)
if [ -n "$DVD" ]; then
  set -- -drive "if=none,id=media,media=cdrom,readonly=on,format=raw,file=$COPY" -device ide-cd,drive=media,bootindex=1
else
  set -- -drive "if=none,id=media,format=raw,file=$COPY" -device usb-storage,bus=xhci.0,drive=media,bootindex=1
fi

ACCEL="tcg,thread=multi"
[ -w /dev/kvm ] && ACCEL=kvm
fw_args() {                  # fw_args FIRMWARE NAME: QEMU's firmware arguments, with a fresh copy of its variables
  FWARGS=""
  if [ "$1" = uefi-secure ]; then
    CODE="$(ls /usr/share/OVMF/OVMF_CODE_4M.secboot.fd /usr/share/OVMF/OVMF_CODE.secboot.fd 2>/dev/null | head -n 1 || true)"
    VARS="$(ls /usr/share/OVMF/OVMF_VARS_4M.ms.fd /usr/share/OVMF/OVMF_VARS.ms.fd 2>/dev/null | head -n 1 || true)"
    [ -n "$CODE" ] && [ -n "$VARS" ] || { echo "No Secure Boot OVMF with Microsoft's keys (apt install ovmf)."; exit 1; }
    cp "$VARS" "$WORK/vars-$2.fd"
    FWARGS="-machine q35,smm=on -global driver=cfi.pflash01,property=secure,value=on -drive if=pflash,format=raw,unit=0,readonly=on,file=$CODE -drive if=pflash,format=raw,unit=1,file=$WORK/vars-$2.fd"
  elif [ "$1" = uefi ]; then
    CODE="$(ls /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/x64/OVMF_CODE.4m.fd 2>/dev/null | head -n 1 || true)"
    VARS="$(ls /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd /usr/share/edk2/x64/OVMF_VARS.4m.fd 2>/dev/null | head -n 1 || true)"
    [ -n "$CODE" ] && [ -n "$VARS" ] || { echo "No OVMF firmware (apt install ovmf)."; exit 1; }
    cp "$VARS" "$WORK/vars-$2.fd"
    FWARGS="-drive if=pflash,format=raw,readonly=on,file=$CODE -drive if=pflash,format=raw,file=$WORK/vars-$2.fd"
  fi
}
# boot NAME FIRMWARE OUTSIDE DRIVE-ARGS…: one start, its log OUT_DIR/console-NAME.log; OUTSIDE=yes: the phone remote
# must answer from the host too. Returns 0 when every check inside passed.
boot() {
  NAME="$1" BFW="$2" WANT_OUTSIDE="$3"
  shift 3
  LOG="$OUT/console-$NAME.log"
  echo "== QEMU ($NAME: $BFW$([ -w /dev/kvm ] && echo ', KVM' || echo ', no KVM: slow'))"
  fw_args "$BFW" "$NAME"
  : > "$LOG"
  # The TV: a real display (a VNC server nobody looks at, on a free port), so the virtio screen has a connected output
  # for cage and Chromium to draw on (with no display at all, Chromium never came up), and QEMU's monitor, which
  # takes a screenshot of it (screendump) once the box is up: OUT_DIR/screen-NAME.png (or .ppm).
  VNC="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]-5900); s.close()')"
  MON="$WORK/monitor-$NAME.sock"
  # shellcheck disable=SC2086
  timeout --foreground -k 10 "$TIMEOUT" qemu-system-x86_64 -accel "$ACCEL" -cpu max -m 2048 -smp 2 \
    -display "vnc=127.0.0.1:$VNC" -serial "file:$LOG" -no-reboot $FWARGS "$@" \
    -device virtio-vga -device virtio-rng-pci \
    -netdev user,id=n0,hostfwd=tcp:127.0.0.1:18092-:8092 -device virtio-net-pci,netdev=n0 \
    -monitor "unix:$MON,server,nowait" &
  QEMU=$!
  # From outside, like a phone on the home network: the phone remote on port 8092 (the only port a box opens to its
  # network at home; the helper's 8091 is for the box itself). Asked until it answers or the VM has gone. The in-VM
  # checks print "SOFA-BOX-PROOF screen" once the TV's screen is up (or has given up): the screenshot is taken then.
  OUTSIDE=no SHOT=no
  while kill -0 "$QEMU" 2>/dev/null; do
    if [ "$OUTSIDE" = no ] && curl -fs -m 3 -o /dev/null http://127.0.0.1:18092/; then OUTSIDE=yes; fi
    if [ "$SHOT" = no ] && grep -aq 'SOFA-BOX-PROOF screen' "$LOG"; then screenshot "$NAME" && SHOT=yes || SHOT=failed; fi
    sleep 3
  done
  wait "$QEMU" 2>/dev/null || true
  echo "Screenshot: $SHOT$(ls "$OUT"/screen-"$NAME".* 2>/dev/null | sed 's/^/ /')"
  echo "== What the VM said (SOFA-BOX-PROOF and SOFA-BOX-LOG lines of $LOG)"
  grep -a -E 'SOFA-BOX-(PROOF|LOG)' "$LOG" | sed 's/^.*vm-proof.sh\[[0-9]*\]: //' || echo "(none: it never got that far)"
  [ "$WANT_OUTSIDE" = yes ] && echo "SOFA-BOX-PROOF outside: phone remote on 8092 from the host: $OUTSIDE" | tee -a "$LOG"
  FAILS=$(grep -a -c 'SOFA-BOX-PROOF .*: fail' "$LOG" || true)
  if grep -aq 'SOFA-BOX-PROOF done' "$LOG" && [ "$FAILS" = 0 ] && { [ "$WANT_OUTSIDE" = no ] || [ "$OUTSIDE" = yes ]; }; then
    echo "Proven ($NAME): every check passed."
  else
    echo "Not proven ($NAME): $FAILS failed check(s), outside=$OUTSIDE, done=$(grep -aq 'SOFA-BOX-PROOF done' "$LOG" && echo yes || echo no). See $LOG."
    return 1
  fi
}
screenshot() {               # the TV's picture now, through QEMU's monitor
  rm -f "$WORK/screen.ppm"
  python3 - "$MON" "$WORK/screen.ppm" <<'EOF' 2>/dev/null || return 1
import socket, sys, time
s = socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect(sys.argv[1]); time.sleep(0.5)
try: s.recv(4096)
except OSError: pass
s.sendall(("screendump %s\n" % sys.argv[2]).encode()); time.sleep(3); s.close()
EOF
  [ -s "$WORK/screen.ppm" ] || return 1
  if command -v convert >/dev/null 2>&1 && convert "$WORK/screen.ppm" "$OUT/screen-$1.png" 2>/dev/null; then :
  else cp "$WORK/screen.ppm" "$OUT/screen-$1.ppm"; fi
}
mark_drive() {               # mark_drive FIRMWARE: what the checks on the installed drive expect of its next start
  LOOP="$(losetup -fP --show "$TARGET")"
  mount "${LOOP}p3" "$M"
  rm -f "$M/etc/sofa-box-vm-install-to" "$M/etc/sofa-box-vm-secure-boot" "$M/etc/sofa-box-vm-dvd"
  [ "$1" = uefi-secure ] && echo on > "$M/etc/sofa-box-vm-secure-boot"
  stat -c %s "$TARGET" > "$M/etc/sofa-box-vm-disk-bytes"            # (its root fills the drive)
  echo /dev/vda > "$M/etc/sofa-box-vm-installed"                    # (and is the drive's, installed from the stick)
  umount "$M"
  losetup -d "$LOOP"
  LOOP=""
}

if [ -z "$ONTO" ]; then
  if [ -n "$DVD" ]; then
    boot "dvd-$FW" "$FW" yes "$@"
    echo "Proven (dvd-$FW): the box started from the disc, its helper and Sofa answer, the TV's screen is up, the phone remote answers from outside."
  else
    boot "$FW" "$FW" yes -drive "file=$COPY,format=raw,if=virtio"
    echo "Proven ($FW): the box started, its helper and Sofa answer, the TV's screen is up, the phone remote answers from outside."
  fi
  exit 0
fi
# Install on this computer: the stick (USB) or the disc, started first, and a blank drive; then the drive alone
TARGET="$WORK/drive.img"
truncate -s "$ONTO" "$TARGET"
boot "install-$KIND$FW" "$FW" no -device qemu-xhci,id=xhci "$@" \
  -drive "if=none,id=drive,format=raw,file=$TARGET" -device virtio-blk-pci,drive=drive,bootindex=2
grep -aq 'SOFA-BOX-PROOF install: ok' "$LOG" || { echo "Not installed: no 'install: ok' in $LOG."; exit 1; }
RC=0
for fw in $THEN; do
  mark_drive "$fw"
  boot "installed-$KIND$fw" "$fw" yes -drive "file=$TARGET,format=raw,if=virtio" || RC=1
done
[ "$RC" = 0 ] && echo "Proven: installed from the $([ -n "$DVD" ] && echo disc || echo stick) onto a blank $ONTO drive, which then started the PC by itself ($THEN)."
exit "$RC"
