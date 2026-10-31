#!/bin/sh
# Turn a Raspberry Pi (or any small Debian-based computer) on the TV into a Sofa box: it starts straight
# into Sofa, full screen, plays videos with its own player (mpv), and works with the TV's remote, a game
# controller and your phone.
#
# On the Pi, with the Sofa computer's address (Sofa's Server page shows this line under Apps):
#   curl -fsSL http://192.168.1.20:8090/sofa-box/install.sh | sudo sh -s http://192.168.1.20:8090
# or from a copy of Sofa:
#   sudo sh deploy/sofa-box/install.sh [http://192.168.1.20:8090]
#
# Works on Raspberry Pi OS (Bookworm or Bullseye, Lite or with a desktop) and other Debian/Ubuntu
# systems. A card set up with LCD-show for a small 3.5-inch screen is fixed up: the TV gets its full
# picture back (LCD-show shrinks it to 480x320) and the small screen is switched off. Running it again
# updates the box.
#
# What it sets up:
#   sofa-box-agent.service   finds Sofa, plays videos (mpv), the box's settings, the previews (port 8091)
#   sofa-box.service         Sofa full screen on the TV (Chromium in "cage", or X on older systems)
#   sofa-box-input.service   game controllers as a remote
#   sofa-box-cec.service     the TV's own remote over HDMI (VIERA Link, Anynet+, SimpLink…)
#   sofa-box                 a command: doctor, status, choose, pair-controller, tv-on, desktop…
set -e
[ "$(id -u)" = 0 ] || { echo "Run it with sudo."; exit 1; }

SOFA="" IMAGE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --image) IMAGE=1 ;;                         # building a card image (tools/build-sofa-box-image.sh): don't start anything
    http://*|https://*) SOFA="${1%/}" ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

WHO="${SOFA_BOX_USER:-${SUDO_USER:-$(getent passwd 1000 | cut -d: -f1)}}"
[ -n "$WHO" ] && [ "$WHO" != root ] || { echo "Run it with sudo from your own account (not as root)."; exit 1; }
HOMEDIR="$(getent passwd "$WHO" | cut -d: -f6)"
UIDN="$(id -u "$WHO")"
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo .)"
LIB=/usr/local/lib/sofa-box
CONF="$HOMEDIR/.config/sofa-box"
BOOT=""
for d in /boot/firmware /boot; do [ -f "$d/config.txt" ] && { BOOT="$d"; break; }; done
. /etc/os-release 2>/dev/null || true
say() { printf '\n== %s\n' "$*"; }
have_pkg() { apt-cache policy "$1" 2>/dev/null | grep -q 'Candidate: [0-9]'; }

say "Installing what the Sofa box needs (a few minutes)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends python3 python3-pil python3-evdev mpv curl avahi-utils v4l-utils bluez \
  fonts-dejavu-core sudo
apt-get install -y --no-install-recommends fonts-noto-color-emoji 2>/dev/null || true             # the home screen's and games' emoji
apt-get install -y --no-install-recommends libwidevinecdm0 2>/dev/null || true                    # DRM (Netflix…) where Raspberry Pi OS has it
if have_pkg cage; then
  SCREEN=wayland
  apt-get install -y --no-install-recommends cage
else                                            # Raspbian Buster and older: no cage, so a bare X screen
  SCREEN=x11
  apt-get install -y --no-install-recommends xserver-xorg xinit x11-xserver-utils
fi
apt-get install -y --no-install-recommends chromium 2>/dev/null || apt-get install -y --no-install-recommends chromium-browser
apt-get install -y --no-install-recommends pipewire-pulse wireplumber 2>/dev/null || true           # sound to the TV
apt-get install -y --no-install-recommends network-manager 2>/dev/null || true                    # Wi-Fi from the TV
apt-get install -y --no-install-recommends plymouth plymouth-label 2>/dev/null || true            # the boot screen
apt-get install -y --no-install-recommends systemd-zram-generator 2>/dev/null \
  || apt-get install -y --no-install-recommends zram-tools 2>/dev/null || true                    # more room in 1 GB

say "Copying the Sofa box files"
FILES="sofa-box sofa-box-agent.py sofa-box-input.py sofa-box-cec.py sofa-box-art.py finder.html preview.html mpv-input.conf"
FONTS="bricolage-grotesque-latin-opsz-normal.woff2 instrument-sans-latin-wght-normal.woff2 LICENSE-Bricolage-Grotesque.txt LICENSE-Instrument-Sans.txt"
mkdir -p "$LIB/fonts"
for f in $FILES; do
  if [ -f "$HERE/$f" ]; then cp "$HERE/$f" "$LIB/$f"
  elif [ -n "$SOFA" ]; then curl -fsSL "$SOFA/sofa-box/$f" -o "$LIB/$f"
  else echo "Can't find $f. Give the Sofa computer's address: sudo sh install.sh http://192.168.1.20:8090"; exit 1
  fi
done
for f in $FONTS; do                              # Sofa's own typefaces, for the boot screen
  if [ -f "$HERE/../../client/vendor/fonts/$f" ]; then cp "$HERE/../../client/vendor/fonts/$f" "$LIB/fonts/$f"
  elif [ -n "$SOFA" ]; then curl -fsSL "$SOFA/client/vendor/fonts/$f" -o "$LIB/fonts/$f" || true
  fi
done
chmod 755 "$LIB" "$LIB"/sofa-box "$LIB"/*.py
ln -sf "$LIB/sofa-box" /usr/local/bin/sofa-box
rm -f "$LIB/sofa-box-finder.py"                  # the first Sofa box's start page: the agent does it now

mkdir -p "$CONF"
if [ -n "$SOFA" ]; then                          # the Sofa it came from: use that one (it still looks if that moves)
  python3 - "$CONF/settings.json" "$SOFA" <<'EOF'
import json, sys
path, url = sys.argv[1], sys.argv[2]
try:
    s = json.load(open(path))
except (OSError, ValueError):
    s = {}
s["server"] = url
json.dump(s, open(path, "w"), indent=1)
EOF
fi
chown -R "$WHO:" "$CONF"

say "Letting the box's user use the screen, the keys, Bluetooth and Wi-Fi"
for g in video render input audio bluetooth netdev; do getent group "$g" >/dev/null && usermod -aG "$g" "$WHO" || true; done
echo uinput > /etc/modules-load.d/sofa-box.conf
modprobe uinput 2>/dev/null || true
echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' > /etc/udev/rules.d/60-sofa-box-uinput.rules
udevadm control --reload 2>/dev/null || true
[ -e /dev/uinput ] && chgrp input /dev/uinput && chmod 660 /dev/uinput || true
echo "options bluetooth disable_ertm=1" > /etc/modprobe.d/sofa-box-controllers.conf      # older Xbox controller firmware
SYSTEMCTL="$(command -v systemctl)"
cat > /etc/sudoers.d/sofa-box <<EOF
# The Sofa box's settings on the TV can restart it and change its boot screen.
$WHO ALL=(root) NOPASSWD: $SYSTEMCTL restart sofa-box sofa-box-agent, $SYSTEMCTL reboot, $LIB/sofa-box apply-boot *
EOF
chmod 440 /etc/sudoers.d/sofa-box
visudo -cf /etc/sudoers.d/sofa-box >/dev/null || { rm -f /etc/sudoers.d/sofa-box; echo "   (couldn't set up sudo for the box's settings)"; }
if [ -d /etc/polkit-1/rules.d ]; then
  cat > /etc/polkit-1/rules.d/50-sofa-box.rules <<EOF
// The Sofa box's settings on the TV choose the Wi-Fi.
polkit.addRule(function (action, subject) {
  if (subject.user == "$WHO" && action.id.indexOf("org.freedesktop.NetworkManager.") == 0) return polkit.Result.YES;
});
EOF
fi
if [ -d /etc/polkit-1/localauthority ]; then
  mkdir -p /etc/polkit-1/localauthority/50-local.d
  printf '[Sofa box Wi-Fi]\nIdentity=unix-user:%s\nAction=org.freedesktop.NetworkManager.*\nResultAny=yes\nResultInactive=yes\nResultActive=yes\n' "$WHO" \
    > /etc/polkit-1/localauthority/50-local.d/50-sofa-box.pkla
fi
mkdir -p /var/lib/systemd/linger && touch "/var/lib/systemd/linger/$WHO"      # its sound (PipeWire) runs from the start

say "Starting Sofa on the TV at every start ($SCREEN)"
systemctl disable --now sofa-box-finder.service 2>/dev/null || true
rm -f /etc/systemd/system/sofa-box-finder.service
cat > /etc/systemd/system/sofa-box-agent.service <<EOF
[Unit]
Description=Sofa box: finds Sofa, plays videos, the box's settings (127.0.0.1:8091)
After=network-online.target avahi-daemon.service
Wants=network-online.target

[Service]
User=$WHO
Environment=XDG_RUNTIME_DIR=/run/user/$UIDN
ExecStart=/usr/bin/python3 $LIB/sofa-box-agent.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/sofa-box.service <<EOF
[Unit]
Description=Sofa box: Sofa full screen on the TV
After=systemd-user-sessions.service plymouth-start.service plymouth-quit.service sofa-box-agent.service
Wants=sofa-box-agent.service
Conflicts=getty@tty1.service plymouth-quit.service
OnFailure=plymouth-quit.service

[Service]
User=$WHO
PAMName=login
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
StandardInput=tty-fail
StandardOutput=journal
StandardError=journal
UtmpIdentifier=tty1
UtmpMode=user
Environment=SOFA_BOX_SCREEN=$SCREEN
ExecStartPre=-+/usr/bin/plymouth quit --retain-splash
ExecStart=$LIB/sofa-box kiosk
Restart=always
RestartSec=2

[Install]
WantedBy=graphical.target
EOF

cat > /etc/systemd/system/sofa-box-input.service <<EOF
[Unit]
Description=Sofa box: game controllers as a remote
After=bluetooth.target

[Service]
User=$WHO
SupplementaryGroups=input
ExecStart=/usr/bin/python3 $LIB/sofa-box-input.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/sofa-box-cec.service <<EOF
[Unit]
Description=Sofa box: the TV's remote over HDMI-CEC
After=sofa-box.service

[Service]
ExecStart=/usr/bin/python3 $LIB/sofa-box-cec.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# A desktop (Raspberry Pi OS with desktop, or LCD-show's) would take the screen: the Sofa box takes it.
# `sofa-box desktop` gives it back.
for dm in lightdm gdm3 sddm; do
  if systemctl is-enabled "$dm" >/dev/null 2>&1; then systemctl disable "$dm"; echo "   (turned off the $dm desktop; 'sofa-box desktop' brings it back)"; fi
done

if [ -n "$BOOT" ]; then
  say "Setting up the Raspberry Pi ($BOOT)"
  "$LIB/sofa-box" setup-boot "$BOOT"
fi

if command -v plymouth-set-default-theme >/dev/null 2>&1; then
  say "The boot screen"
  if [ -n "$IMAGE" ]; then "$LIB/sofa-box" apply-boot "$CONF/settings.json" --no-initramfs || true
  else "$LIB/sofa-box" apply-boot "$CONF/settings.json" || true
  fi
fi
if dpkg -s systemd-zram-generator >/dev/null 2>&1; then
  printf '[zram0]\nzram-size = ram / 2\ncompression-algorithm = zstd\n' > /etc/systemd/zram-generator.conf
elif [ -f /etc/default/zramswap ]; then
  sed -i -E 's/^#?PERCENT=.*/PERCENT=50/' /etc/default/zramswap
fi

systemctl daemon-reload
systemctl set-default graphical.target >/dev/null
systemctl enable sofa-box-agent.service sofa-box.service sofa-box-input.service sofa-box-cec.service
if [ -z "$IMAGE" ]; then
  systemctl restart sofa-box-agent.service sofa-box-input.service sofa-box-cec.service
  systemctl restart sofa-box.service
fi

echo
echo "Done. Sofa opens on the TV now and every time the box starts."
echo "  - Sign in: the TV shows a code; approve it on your phone (Sofa -> your picture -> Pair a TV)."
echo "  - The TV's own remote works through HDMI (turn on VIERA Link / Anynet+ / SimpLink / CEC on the TV)."
echo "  - A game controller: sofa-box pair-controller.   Is everything right?  sofa-box doctor"
if [ -n "$BOOT" ] && ! cmp -s "$BOOT/config.txt" "$BOOT/config.txt.before-sofa-box" 2>/dev/null; then
  echo "  - Restart once for the screen settings: sudo reboot"
fi
