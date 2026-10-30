#!/bin/sh
# Turn a Raspberry Pi into a Sofa box: it starts straight into Sofa, full screen on the TV.
# Raspberry Pi OS Lite (Bookworm or newer), a Pi 4 or 5 (a Pi 3 manages 720p).
#
# On the Pi, with the Sofa computer's address (Sofa's Server page shows it under Apps):
#   curl -fsSL http://192.168.1.20:8090/sofa-box/install.sh | sudo sh -s http://192.168.1.20:8090
# or from a copy of Sofa on the Pi:
#   sudo sh deploy/sofa-box/install.sh [http://192.168.1.20:8090]
#
# What it sets up:
#   sofa-box.service         Chromium in kiosk mode (in "cage", a one-window screen) on the TV
#   sofa-box-finder.service  the start page: finds Sofa (Bonjour, SSDP) and opens it
#   sofa-box-cec.service     the TV's own remote over HDMI-CEC (VIERA Link, Anynet+, SimpLink…)
#   sofa-box                 a command: pair-controller, choose, tv-on, status
set -e
[ "$(id -u)" = 0 ] || { echo "Run it with sudo."; exit 1; }
WHO="${SUDO_USER:-$(getent passwd 1000 | cut -d: -f1)}"
[ -n "$WHO" ] && [ "$WHO" != root ] || { echo "Run it with sudo from your own account (not as root)."; exit 1; }
HOMEDIR="$(getent passwd "$WHO" | cut -d: -f6)"
SOFA="${1:-}"
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo .)"
LIB=/usr/local/lib/sofa-box

echo "== Installing what the Sofa box needs (a few minutes)"
apt-get update -qq
apt-get install -y --no-install-recommends cage avahi-utils v4l-utils ir-keytable python3 python3-evdev bluez \
  pipewire-pulse wireplumber fonts-dejavu-core curl
apt-get install -y --no-install-recommends chromium 2>/dev/null || apt-get install -y --no-install-recommends chromium-browser

echo "== Copying the Sofa box files"
mkdir -p "$LIB"
for f in sofa-box sofa-box-finder.py sofa-box-cec.py; do
  if [ -f "$HERE/$f" ]; then cp "$HERE/$f" "$LIB/$f"
  elif [ -n "$SOFA" ]; then curl -fsSL "$SOFA/sofa-box/$f" -o "$LIB/$f"
  else echo "Can't find $f. Give the Sofa computer's address: sudo sh install.sh http://192.168.1.20:8090"; exit 1
  fi
done
chmod 755 "$LIB"/*
ln -sf "$LIB/sofa-box" /usr/local/bin/sofa-box

if [ -n "$SOFA" ]; then                 # the Sofa it came from: use that one (it still looks if that moves)
  mkdir -p "$HOMEDIR/.config/sofa-box"
  echo "${SOFA%/}" > "$HOMEDIR/.config/sofa-box/server"
  chown -R "$WHO:" "$HOMEDIR/.config/sofa-box"
fi
usermod -aG video,render,input,audio "$WHO"
# Older Xbox controller firmware needs this to pair over Bluetooth.
echo "options bluetooth disable_ertm=1" > /etc/modprobe.d/sofa-box-controllers.conf

echo "== Starting Sofa on the TV at every start"
cat > /etc/systemd/system/sofa-box-finder.service <<EOF
[Unit]
Description=Sofa box: finds Sofa on the home network (start page on 127.0.0.1:8091)
After=network-online.target avahi-daemon.service
Wants=network-online.target

[Service]
User=$WHO
ExecStart=/usr/bin/python3 $LIB/sofa-box-finder.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/sofa-box.service <<EOF
[Unit]
Description=Sofa box: Sofa full screen on the TV
After=systemd-user-sessions.service plymouth-quit-wait.service sofa-box-finder.service
Wants=sofa-box-finder.service
Conflicts=getty@tty1.service

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
Environment=XDG_SESSION_TYPE=wayland
ExecStart=$LIB/sofa-box kiosk
Restart=always
RestartSec=2

[Install]
WantedBy=graphical.target
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

# A desktop (Raspberry Pi OS with desktop) would take the screen: the Sofa box takes it instead.
for dm in lightdm gdm3 sddm; do
  if systemctl is-enabled "$dm" >/dev/null 2>&1; then systemctl disable "$dm"; echo "   (turned off the $dm desktop)"; fi
done
systemctl daemon-reload
systemctl set-default graphical.target >/dev/null
systemctl enable sofa-box-finder.service sofa-box.service sofa-box-cec.service
systemctl restart sofa-box-finder.service sofa-box-cec.service
systemctl restart sofa-box.service

echo
echo "Done. Sofa opens on the TV now and every time the Pi starts."
echo "  - Sign in: the TV shows a code; approve it on your phone (Sofa -> your picture -> Pair a TV)."
echo "  - The TV's own remote works through HDMI (turn on VIERA Link / Anynet+ / SimpLink / CEC on the TV)."
echo "  - A game controller: run  sofa-box pair-controller"
echo "  - Another Sofa computer later: run  sofa-box choose"
