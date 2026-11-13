#!/bin/sh
# Make Sofa Box OS for a PC on a DVD: a live DVD (ISO 9660) made from the PC image (tools/build-sofa-box-vm-image.sh).
# A PC started from it runs Sofa Box OS from the disc, with what's set up kept in memory until it restarts; Settings →
# This box → Install on this computer puts it on the PC's own drive from there, as from the USB stick.
#
#   sudo tools/build-sofa-box-dvd.sh IMAGE.img OUT_DIR
#
# On Linux, x86-64, as root, with: losetup, mksquashfs (squashfs-tools), xorriso, mkfs.vfat, and the internet (Debian's
# live-boot, for the disc's start). Writes OUT_DIR/<the image's name>-dvd.iso, its .sha256, and a report.
#
# What's on the disc:
# - /live/filesystem.squashfs: the image's own root, as it is, file for file (the same system as on the stick);
# - /live/vmlinuz and /live/initrd.img: the image's Debian kernel (signed), and a start for it with Debian's live-boot,
#   made beside the system in a throwaway layer (the system on the disc doesn't get live-boot: a drive it's installed
#   on is the same as one installed from the stick). live-boot finds the disc, puts the system together in memory
#   (overlayfs over the squashfs), and leaves /etc/fstab alone (nofstab); the image's parts for a disk (its EFI
#   partition, growing the root to the disk) are switched off for that start (systemd.mask=);
# - UEFI: the Microsoft-signed shim and Debian's signed GRUB for a disc (gcdx64.efi.signed, which finds the disc by
#   /.disk/info), in the El Torito EFI image: it starts with Secure Boot on, as the stick does;
# - BIOS: GRUB's El Torito image for a PC BIOS; and an MBR for GRUB, so the same file written to a USB stick starts too.
set -eu
IMG="${1:-}" OUT="${2:-}"
[ -n "$IMG" ] && [ -n "$OUT" ] || { echo "sudo tools/build-sofa-box-dvd.sh IMAGE.img OUT_DIR"; exit 1; }
[ "$(id -u)" = 0 ] || { echo "Run it with sudo."; exit 1; }
for t in losetup mksquashfs xorriso mkfs.vfat chroot sha256sum; do
  command -v "$t" >/dev/null || { echo "Needs $t (apt install squashfs-tools xorriso dosfstools)."; exit 1; }
done
mkdir -p "$OUT"
NAME="$(basename "$IMG" .img)-dvd"
WORK="$(mktemp -d)"
ROOT="$WORK/root" LIVE="$WORK/live" ISO="$WORK/iso"
LOOP="" EFILOOP=""
cleanup() {
  set +e
  for m in run sys proc dev/pts dev; do mountpoint -q "$LIVE/$m" && umount "$LIVE/$m"; done
  mountpoint -q "$LIVE" && umount "$LIVE"
  mountpoint -q "$WORK/efi" && umount "$WORK/efi"
  mountpoint -q "$ROOT" && umount "$ROOT"
  [ -n "$LOOP" ] && losetup -d "$LOOP"
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

echo "== The system: $(basename "$IMG")'s root, as it is"
mkdir -p "$ROOT" "$LIVE" "$WORK/up" "$WORK/wk" "$ISO/live" "$ISO/.disk" "$ISO/boot/grub/i386-pc" "$ISO/EFI/boot" "$WORK/efi"
LOOP="$(losetup -rfP --show "$IMG")"
mount -o ro "${LOOP}p3" "$ROOT"
VER="$(tr -d ' \n' < "$ROOT/usr/local/lib/sofa-box/VERSION")"
KVER="$(ls "$ROOT/lib/modules" | sort -V | tail -n 1)"
[ -f "$ROOT/boot/vmlinuz-$KVER" ] || { echo "No kernel for $KVER on the image."; exit 1; }
for f in usr/lib/shim/shimx64.efi.signed usr/lib/shim/mmx64.efi.signed usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed \
         usr/lib/grub/i386-pc/boot_hybrid.img usr/lib/grub/i386-pc/cdboot.img etc/default/grub; do
  [ -f "$ROOT/$f" ] || { echo "The image has no /$f (shim-signed, grub-efi-amd64-signed and grub-pc-bin are on it?)."; exit 1; }
done
mksquashfs "$ROOT" "$ISO/live/filesystem.squashfs" -noappend -comp zstd -Xcompression-level 19 -b 1M -no-progress -quiet
du -sx --block-size=1 "$ROOT" | cut -f1 > "$ISO/live/filesystem.size"      # (what installing from it copies)
cp "$ROOT/boot/vmlinuz-$KVER" "$ISO/live/vmlinuz"

echo "== Its start from a disc: live-boot, in a layer of its own (the system above stays as it is)"
mount -t overlay overlay -o "lowerdir=$ROOT,upperdir=$WORK/up,workdir=$WORK/wk" "$LIVE"
for m in dev dev/pts proc sys run; do mount --bind "/$m" "$LIVE/$m"; done
cp --remove-destination /etc/resolv.conf "$LIVE/etc/resolv.conf"
printf '#!/bin/sh\nexit 101\n' > "$LIVE/usr/sbin/policy-rc.d"
chmod 755 "$LIVE/usr/sbin/policy-rc.d"
sed -i 's/^update_initramfs=.*/update_initramfs=no/' "$LIVE/etc/initramfs-tools/update-initramfs.conf"   # (one start, made below)
chroot "$LIVE" /bin/sh -eu -c "
  apt-get -o Acquire::Retries=3 update -qq
  DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y -qq --no-install-recommends live-boot live-boot-initramfs-tools >/dev/null
  mkinitramfs -o /tmp/initrd.img '$KVER'
  grub-mkimage -O i386-pc-eltorito -p /boot/grub -o /tmp/eltorito.img biosdisk iso9660 part_msdos part_gpt normal search configfile linux echo test all_video gfxterm
  dpkg-query -W -f='\${Package} \${Version}\n' live-boot live-boot-initramfs-tools > /tmp/live-boot.txt
"
cp "$LIVE/tmp/live-boot.txt" "$WORK/live-boot.txt"
cp "$LIVE/tmp/initrd.img" "$ISO/live/initrd.img"
cp "$LIVE/tmp/eltorito.img" "$ISO/boot/grub/i386-pc/eltorito.img"
for m in run sys proc dev/pts dev; do umount "$LIVE/$m"; done
umount "$LIVE"

echo "== UEFI (Secure Boot's signed chain) and BIOS"
cp "$ROOT/usr/lib/shim/shimx64.efi.signed" "$ISO/EFI/boot/bootx64.efi"
cp "$ROOT/usr/lib/shim/mmx64.efi.signed" "$ISO/EFI/boot/mmx64.efi"
cp "$ROOT/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed" "$ISO/EFI/boot/grubx64.efi"
cp "$ROOT"/usr/lib/grub/i386-pc/*.mod "$ROOT"/usr/lib/grub/i386-pc/*.lst "$ISO/boot/grub/i386-pc/"
# The El Torito EFI image: a small FAT disk with the same three files (the firmware starts shim from it; Debian's GRUB
# for a disc then finds the disc itself by /.disk/info and reads /boot/grub/grub.cfg there)
truncate -s 8M "$ISO/boot/grub/efi.img"
mkfs.vfat -n SOFAEFI "$ISO/boot/grub/efi.img" >/dev/null
mount -o loop "$ISO/boot/grub/efi.img" "$WORK/efi"
mkdir -p "$WORK/efi/EFI/boot"
cp "$ISO/EFI/boot/bootx64.efi" "$ISO/EFI/boot/mmx64.efi" "$ISO/EFI/boot/grubx64.efi" "$WORK/efi/EFI/boot/"
umount "$WORK/efi"
echo "Sofa Box OS $VER for a PC (x86-64), a live DVD, made $(date -u +%Y-%m-%d)" > "$ISO/.disk/info"
# The start: the image's own kernel line (its quiet boot screen), and the live system's parts
CMDLINE="$(sed -n 's/^GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"$/\1/p' "$ROOT/etc/default/grub")"
LIVEARGS="boot=live nofstab systemd.mask=boot-efi.mount systemd.mask=systemd-repart.service systemd.mask=systemd-growfs-root.service"
cat > "$ISO/boot/grub/grub.cfg" <<EOF
# Sofa Box OS $VER, a live DVD. Esc as it starts shows this menu.
set default=0
set timeout=0
set timeout_style=hidden
if [ "\$grub_platform" = pc ]; then insmod all_video; fi
set gfxpayload=keep
menuentry "Sofa Box OS" {
  linux /live/vmlinuz $LIVEARGS $CMDLINE
  initrd /live/initrd.img
}
menuentry "Sofa Box OS (basic graphics, for a PC whose screen stays dark)" {
  linux /live/vmlinuz $LIVEARGS $CMDLINE nomodeset
  initrd /live/initrd.img
}
EOF
cat > "$ISO/README.txt" <<EOF
Sofa Box OS $VER for a PC (x86-64), a live DVD.
Start the PC from the disc (its start menu key as it starts: F12, F11, F10, F8 or Esc). It runs Sofa Box OS from the
disc, newer PCs and older ones, Secure Boot on or off; what you set up is kept until the PC restarts. To keep it:
Settings, This box, Install on this computer (the drive you pick is erased).
EOF

echo "== The disc: ISO 9660, a DVD and a USB stick both"
xorriso -as mkisofs -iso-level 3 -l -J -joliet-long -R \
  -V SOFABOX -A "Sofa Box OS $VER" -publisher "Sofa" \
  -b boot/grub/i386-pc/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
  --grub2-mbr "$ROOT/usr/lib/grub/i386-pc/boot_hybrid.img" \
  --efi-boot boot/grub/efi.img -efi-boot-part --efi-boot-image --protective-msdos-label \
  -o "$OUT/$NAME.iso" "$ISO" 2>&1 | grep -v -E '^(xorriso|Drive current|Media current|Media status|Media summary|Added to ISO|Writing to|libisofs: NOTE).*' || true
[ -s "$OUT/$NAME.iso" ] || { echo "No disc was made."; exit 1; }
BOOTS="$(xorriso -indev "$OUT/$NAME.iso" -report_el_torito plain 2>/dev/null | grep -c '^El Torito boot img :' || true)"
[ "$BOOTS" = 2 ] || { echo "The disc should start two ways (BIOS and UEFI); it has $BOOTS."; exit 1; }
(cd "$OUT" && sha256sum "$NAME.iso" > "$NAME.iso.sha256")
SIZE="$(stat -c %s "$OUT/$NAME.iso")"
[ "$SIZE" -lt 4700000000 ] || { echo "The disc is $SIZE bytes: more than a DVD holds."; exit 1; }
{ echo "Sofa Box OS $VER for a PC (x86-64), a live DVD: $NAME.iso, $((SIZE / 1000000)) MB (a DVD holds 4,700)"
  echo "System: $(basename "$IMG")'s root, $(($(cat "$ISO/live/filesystem.size") / 1000000)) MB, in a $(($(stat -c %s "$ISO/live/filesystem.squashfs") / 1000000)) MB squashfs (zstd)"
  echo "Kernel: $KVER (Debian's, signed); its start for a disc: $(tr '\n' ' ' < "$WORK/live-boot.txt")"
  echo "Starts: BIOS (GRUB, El Torito) and UEFI (shim and Debian's signed GRUB for a disc, so Secure Boot on or off)"
  echo "Kernel line: $LIVEARGS $CMDLINE"; } > "$OUT/$NAME-report.txt"
cat "$OUT/$NAME-report.txt"
