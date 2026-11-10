#!/bin/sh
# Boot a Sofa box x86-64 disk image in QEMU and prove it works: the box's helper answers on 127.0.0.1:8091, Sofa on
# the box answers /api/info on its port (8095), the TV's screen (cage with Chromium) is up, the phone remote answers
# from outside, and the console log says so. GitHub runs it on every image it builds (.github/workflows/sofa-box-vm.yml);
# it runs on any Linux with QEMU (with KVM it takes a few minutes; without, longer).
#
#   sudo tools/boot-sofa-box-vm.sh IMAGE.img OUT_DIR [--firmware uefi|bios] [--timeout SECONDS]
#
# It never touches the image: it boots a copy, with two changes a test needs: the kernel's console on the serial port
# (so the log is a file) and a small service that runs the checks inside the VM, prints "SOFA-BOX-PROOF …" lines and
# switches the VM off. Exit 0 when every check passed; the console log is OUT_DIR/console-<firmware>.log.
set -eu
IMG="" OUT="" FW=uefi TIMEOUT=900
while [ $# -gt 0 ]; do
  case "$1" in
    --firmware) FW="$2"; shift ;;
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
cleanup() { set +e; mountpoint -q "$WORK/m" && umount "$WORK/m"; [ -n "$LOOP" ] && losetup -d "$LOOP"; rm -rf "$WORK"; }
trap cleanup EXIT INT TERM

echo "== A copy of $(basename "$IMG"), with the test's service in it ($FW)"
case "$IMG" in
  *.xz) xz -dc "$IMG" > "$COPY" ;;
  *) cp --sparse=always "$IMG" "$COPY" ;;
esac
LOOP="$(losetup -fP --show "$COPY")"
mkdir -p "$WORK/m"
mount "${LOOP}p3" "$WORK/m"
M="$WORK/m"
# the kernel and systemd talk on the serial port (the log), and the boot screen stays out of the way
sed -i -E 's/\b(quiet|splash)\b ?//g; s/(console=tty3)/\1 console=ttyS0,115200n8 systemd.show_status=1 plymouth.enable=0/' "$M/boot/grub/grub.cfg"
grep -q 'console=ttyS0' "$M/boot/grub/grub.cfg" || { echo "Couldn't put the console on the serial port (grub.cfg changed?)."; exit 1; }
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
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
EOF
mkdir -p "$M/etc/systemd/system/multi-user.target.wants"
ln -sf /etc/systemd/system/sofa-box-vm-proof.service "$M/etc/systemd/system/multi-user.target.wants/sofa-box-vm-proof.service"
umount "$M"
losetup -d "$LOOP"
LOOP=""

echo "== QEMU ($FW$([ -w /dev/kvm ] && echo ', KVM' || echo ', no KVM: slow'))"
ACCEL="tcg,thread=multi"
[ -w /dev/kvm ] && ACCEL=kvm
FWARGS=""
if [ "$FW" = uefi ]; then
  CODE="$(ls /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/x64/OVMF_CODE.4m.fd 2>/dev/null | head -n 1 || true)"
  VARS="$(ls /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd /usr/share/edk2/x64/OVMF_VARS.4m.fd 2>/dev/null | head -n 1 || true)"
  [ -n "$CODE" ] && [ -n "$VARS" ] || { echo "No OVMF firmware (apt install ovmf)."; exit 1; }
  cp "$VARS" "$WORK/vars.fd"
  FWARGS="-drive if=pflash,format=raw,readonly=on,file=$CODE -drive if=pflash,format=raw,file=$WORK/vars.fd"
fi
: > "$LOG"
# shellcheck disable=SC2086
timeout --foreground -k 10 "$TIMEOUT" qemu-system-x86_64 -accel "$ACCEL" -cpu max -m 2048 -smp 2 -display none \
  -serial "file:$LOG" -no-reboot $FWARGS \
  -drive "file=$COPY,format=raw,if=virtio" \
  -device virtio-vga -device virtio-rng-pci \
  -netdev user,id=n0,hostfwd=tcp:127.0.0.1:18092-:8092 -device virtio-net-pci,netdev=n0 \
  -monitor none &
QEMU=$!
# From outside, like a phone on the home network: the phone remote on port 8092 (the only port a box opens to its network
# at home; the helper's 8091 is for the box itself). Asked until it answers or the VM has gone.
OUTSIDE=no
while kill -0 "$QEMU" 2>/dev/null; do
  if curl -fs -m 3 -o /dev/null http://127.0.0.1:18092/; then OUTSIDE=yes; break; fi
  sleep 3
done
wait "$QEMU" 2>/dev/null || true
echo "== What the VM said (SOFA-BOX-PROOF lines of $LOG)"
grep -a 'SOFA-BOX-PROOF' "$LOG" || echo "(none: it never got that far)"
echo "SOFA-BOX-PROOF outside: phone remote on 8092 from the host: $OUTSIDE" | tee -a "$LOG"
FAILS=$(grep -a -c 'SOFA-BOX-PROOF .*: fail' "$LOG" || true)
if grep -aq 'SOFA-BOX-PROOF done' "$LOG" && [ "$FAILS" = 0 ] && [ "$OUTSIDE" = yes ]; then
  echo "Proven ($FW): the box started, its helper and Sofa answer, the TV's screen is up, the phone remote answers from outside."
else
  echo "Not proven ($FW): $FAILS failed check(s), outside=$OUTSIDE, done=$(grep -aq 'SOFA-BOX-PROOF done' "$LOG" && echo yes || echo no). See $LOG."
  exit 1
fi
