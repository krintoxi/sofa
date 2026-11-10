#!/bin/sh
# The Sofa box on hardware that isn't a Raspberry Pi: an x86-64 PC or laptop, a mini PC, a virtual machine, another
# board running plain Debian 13 (Trixie) or Ubuntu. install.sh runs this (as root, after the box's files are in place)
# only when it finds no Raspberry Pi; a Pi, and a Pi card being built, never come here. docs/hardware.md says what
# each step is for, and what is proven where.
#
#   sh other-hardware.sh [--image]      (install.sh does; --image: building a disk image, nothing to start)
#
# It adds what Debian has in place of the Pi's own parts, and nothing of the Pi's:
#   - VA-API: the video decoder of Intel and AMD graphics, for mpv (hwdec auto-safe picks it) and Chromium
#     (/etc/chromium.d/sofa-box: Debian's chromium reads its flags from there);
#   - the Linux firmware packages a PC or laptop needs for Wi-Fi, Bluetooth, graphics and sound, when the system's
#     apt sources have Debian's non-free-firmware component (they do on Debian 13's own installer; nothing is added);
#   - the TV's remote over HDMI-CEC only with a Pulse-Eight USB adapter (PCs' HDMI ports have no CEC): the kernel's
#     pulse8-cec driver is attached when one is plugged in, and the CEC service starts when a /dev/cec appears;
#   - Widevine for the DRM apps is a separate, chosen step: `sudo sofa-box widevine` (docs/hardware.md).
set -e
[ "$(id -u)" = 0 ] || { echo "Run it with sudo."; exit 1; }
IMAGE=""
[ "${1:-}" = --image ] && IMAGE=1
LIB="${SOFA_BOX_LIB:-/usr/local/lib/sofa-box}"
export DEBIAN_FRONTEND=noninteractive
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
try() { for p in "$@"; do apt-get install -y --no-install-recommends "$p" >/dev/null 2>&1 || echo "   (no package $p here)"; done; }

echo "   (not a Raspberry Pi: a PC, a virtual machine or another board; $ARCH)"
echo "   Video decoding (VA-API) for mpv and Chromium"
try vainfo libva-drm2 libva-wayland2 mesa-va-drivers                # AMD (and Intel through Mesa where it applies)
case "$ARCH" in
  amd64) try intel-media-va-driver                                   # Intel Broadwell (2014) and newer
         try i965-va-driver ;;                                       # Intel Sandy Bridge (2011) to Broadwell
esac
# Debian's chromium reads /etc/chromium.d/*: VA-API decoding on Wayland (cage), and the graphics chip even when
# Chromium's own list would rule it out (old laptops). Without a decoder these flags change nothing.
mkdir -p /etc/chromium.d
cat > /etc/chromium.d/sofa-box <<'EOF'
# Sofa box (other-hardware.sh): the graphics chip decodes video where Linux has a VA-API driver for it
export CHROMIUM_FLAGS="$CHROMIUM_FLAGS --enable-features=VaapiVideoDecodeLinuxGL,VaapiIgnoreDriverChecks --ignore-gpu-blocklist"
EOF

echo "   Firmware for Wi-Fi, Bluetooth, graphics and sound (where apt has Debian's non-free-firmware)"
if apt-cache policy firmware-misc-nonfree 2>/dev/null | grep -q 'Candidate: [0-9]'; then
  try firmware-misc-nonfree firmware-iwlwifi firmware-realtek firmware-atheros firmware-brcm80211 firmware-linux-nonfree
  case "$ARCH" in
    amd64) try firmware-amd-graphics firmware-intel-graphics firmware-sof-signed firmware-intel-sound intel-microcode amd64-microcode ;;
  esac
else
  echo "   (no non-free-firmware in apt's sources: a laptop's Wi-Fi or sound may need it; see docs/hardware.md)"
fi

echo "   The TV's remote over HDMI-CEC: only with a Pulse-Eight USB adapter"
try inputattach                                                      # binds the adapter's serial line to the kernel's CEC driver
# A PC's HDMI has no CEC, so the CEC service would start, find nothing and start again every 5 seconds for ever:
# it waits for a /dev/cec instead, and udev starts it when one appears (the Pi's unit stays as it is).
mkdir -p /etc/systemd/system/sofa-box-cec.service.d
cat > /etc/systemd/system/sofa-box-cec.service.d/other-hardware.conf <<'EOF'
# Sofa box on a PC (other-hardware.sh): HDMI-CEC only through an adapter, when one is there
[Unit]
ConditionPathExistsGlob=/dev/cec*
EOF
cat > /etc/systemd/system/sofa-box-pulse8@.service <<'EOF'
[Unit]
Description=Sofa box: a Pulse-Eight USB-CEC adapter on /dev/%I, as the kernel's CEC device
BindsTo=dev-%i.device
After=dev-%i.device

[Service]
ExecStartPre=-/sbin/modprobe pulse8-cec
ExecStart=/usr/bin/inputattach --pulse8-cec /dev/%I
Restart=on-failure
RestartSec=5
EOF
cat > /etc/udev/rules.d/61-sofa-box-cec.rules <<'EOF'
# Sofa box (other-hardware.sh): a Pulse-Eight USB-CEC adapter (2548:1001, 2548:1002) becomes /dev/cecN through the
# kernel's pulse8-cec driver; any /dev/cec starts the TV-remote service.
ACTION=="add", SUBSYSTEM=="tty", ATTRS{idVendor}=="2548", ATTRS{idProduct}=="100[12]", TAG+="systemd", ENV{SYSTEMD_WANTS}+="sofa-box-pulse8@%k.service"
ACTION=="add", SUBSYSTEM=="cec", TAG+="systemd", ENV{SYSTEMD_WANTS}+="sofa-box-cec.service"
EOF
[ -n "$IMAGE" ] || udevadm control --reload 2>/dev/null || true

# What this computer decodes in hardware, for the record (a VM has no decoder; see `sofa-box doctor`).
if [ -z "$IMAGE" ] && command -v vainfo >/dev/null 2>&1; then
  if V="$(vainfo --display drm 2>/dev/null | grep -oE 'VAProfile(H264|HEVC|VP9|AV1)[A-Za-z0-9_]*' | sed 's/VAProfile//' | sort -u | paste -sd, -)" && [ -n "$V" ]; then
    echo "   Decodes in hardware: $V"
  else
    echo "   (no VA-API decoder seen: videos decode on the processor; a VM has none)"
  fi
fi
echo "   DRM apps (Netflix, Disney+…) need Widevine, which Debian's Chromium doesn't have: sudo sofa-box widevine (x86-64; docs/hardware.md)."
