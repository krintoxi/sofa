#!/bin/sh
# Turn a Raspberry Pi (or any small Debian-based computer) on the TV into a Sofa box: it starts straight
# into Sofa, full screen, plays videos with its own player (mpv), and works with the TV's remote, a game
# controller and your phone.
#
# On the Pi (it gets everything from GitHub; no Sofa computer needed):
#   curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/deploy/sofa-box/install.sh | sudo sh
# Add a Sofa computer's address at the end to start with that one (the box finds Sofa at home by itself too):
#   curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/deploy/sofa-box/install.sh | sudo sh -s http://192.168.1.20:8090
# or from a copy of Sofa:
#   sudo sh deploy/sofa-box/install.sh [http://192.168.1.20:8090]
#
# Works on Raspberry Pi OS (Trixie, Bookworm or Bullseye, Lite or with a desktop) and other Debian/Ubuntu
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
# A Raspberry Pi (its boot files, its own apt archive, or its name in the device tree), or not: a PC, a virtual machine
# or another board gets what Debian has in place of the Pi's parts (other-hardware.sh, docs/hardware.md). A card being
# built counts as a Pi even before its boot files are in place. SOFA_BOX_HARDWARE=pi|other says so by hand.
is_pi() {
  R="${SOFA_BOX_ROOT:-}"                                                   # (tests point this at a folder of their own)
  [ -n "$BOOT" ] && return 0
  grep -qs 'Raspberry Pi' "$R/proc/device-tree/model" && return 0
  [ -f "$R/etc/apt/sources.list.d/raspi.list" ] && return 0
  [ -f "$R/usr/lib/raspberrypi-sys-mods/firstboot" ] || [ -d "$R/usr/lib/userconf-pi" ] || [ -f "$R/usr/bin/vcgencmd" ]
}
case "${SOFA_BOX_HARDWARE:-}" in
  pi) OTHER="" ;;
  other) OTHER=1 ;;
  *) if is_pi; then OTHER=""; else OTHER=1; fi ;;
esac
. /etc/os-release 2>/dev/null || true
say() { printf '\n== %s\n' "$*"; }
have_pkg() { apt-cache policy "$1" 2>/dev/null | grep -q 'Candidate: [0-9]'; }

say "Installing what the Sofa box needs (a few minutes)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends python3 python3-pil python3-evdev mpv curl avahi-utils v4l-utils bluez \
  fonts-dejavu-core sudo udisks2 eject
apt-get install -y --no-install-recommends ffmpeg 2>/dev/null || true                             # Sofa on the box (This box): reading videos, some Live TV
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
apt-get install -y --no-install-recommends xwayland 2>/dev/null || true                           # games made for X, in cage
apt-get install -y --no-install-recommends ir-keytable 2>/dev/null || true                        # the TV's remote over HDMI (CEC): its keys once
apt-get install -y --no-install-recommends luanti luanti-game-minetest 2>/dev/null || true         # Sofa Craft (Games), there from the start
apt-get install -y --no-install-recommends network-manager 2>/dev/null || true                    # Wi-Fi from the TV
apt-get install -y --no-install-recommends dnsmasq-base rfkill iw 2>/dev/null || true             # the box's own Wi-Fi at its setup
apt-get install -y --no-install-recommends plymouth plymouth-label 2>/dev/null || true            # the boot screen
apt-get install -y --no-install-recommends systemd-zram-generator 2>/dev/null \
  || apt-get install -y --no-install-recommends zram-tools 2>/dev/null || true                    # more room in 1 GB

say "Copying the Sofa box files"
if [ ! -f "$HERE/sofa-box-agent.py" ]; then        # run through curl: the box (and Sofa) come from GitHub
  FETCHED="$(mktemp -d)"
  BRANCH="${SOFA_BOX_BRANCH:-main}"
  REF="refs/heads/$BRANCH" STABLE=""
  # A new box starts on the stable version (deploy/sofa-box/STABLE: tried on a real box), from its own release, once
  # one is marked. SOFA_BOX_BRANCH, or a Sofa box already (an update from a box older than 1.1.55): that branch's newest.
  if [ -z "${SOFA_BOX_BRANCH:-}" ] && [ ! -f "$LIB/VERSION" ]; then
    STABLE="$(curl -fsSL -m 30 https://raw.githubusercontent.com/krintoxi/sofa/main/deploy/sofa-box/STABLE 2>/dev/null \
      | tr -d '\r ' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | head -n 1)"
    if [ -n "$STABLE" ] && curl -fsS -m 30 -o /dev/null "https://raw.githubusercontent.com/krintoxi/sofa/box-os-v$STABLE/deploy/sofa-box/VERSION"; then
      REF="refs/tags/box-os-v$STABLE"
    else
      STABLE=""                                     # (none marked, or no release of its own: main's newest)
    fi
  fi
  if curl -fsSL "https://codeload.github.com/krintoxi/sofa/tar.gz/$REF" | tar xz -C "$FETCHED" 2>/dev/null \
      && [ -f "$(ls -d "$FETCHED"/*/deploy/sofa-box 2>/dev/null | head -n 1)/sofa-box-agent.py" ]; then
    HERE="$(ls -d "$FETCHED"/*/deploy/sofa-box | head -n 1)"
    if [ -n "$STABLE" ]; then                       # that version's own installer, with its own files
      say "Sofa Box OS $STABLE (stable)"
      exec sh "$HERE/install.sh" ${SOFA:+"$SOFA"}
    fi
  elif [ -n "$SOFA" ] && curl -fsSL "$SOFA/sofa-box.tar.gz" | tar xz -C "$FETCHED"; then
    HERE="$FETCHED/sofa-box"                         # no GitHub: from the Sofa computer instead
  else
    echo "Couldn't get the Sofa box from GitHub${SOFA:+ or from $SOFA}. Is the Pi online?"; exit 1
  fi
fi
mkdir -p "$LIB/fonts"
(cd "$HERE" && tar cf - --exclude=README.md --exclude=__pycache__ .) | (cd "$LIB" && tar xf -)
if [ -d "$HERE/../../client/vendor/fonts" ]; then  # Sofa's own typefaces, for the home screen and the boot screen
  cp "$HERE/../../client/vendor/fonts/"*.woff2 "$HERE/../../client/vendor/fonts/"LICENSE* "$LIB/fonts/" 2>/dev/null || true
fi
if [ -f "$HERE/../../sofa.py" ]; then              # Sofa itself, for "This box" (no Sofa computer needed)
  rm -rf "$LIB/sofa-server" && mkdir -p "$LIB/sofa-server"
  (cd "$HERE/../.." && tar cf - --exclude=__pycache__ sofa.py sofa client LICENSE) | (cd "$LIB/sofa-server" && tar xf -)
fi                                                  # (from a Sofa computer's archive it's in sofa-server/ already)
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
printf 'uinput\nuhid\n' > /etc/modules-load.d/sofa-box.conf      # (uhid: Bluetooth LE controllers, an Xbox Series one)
modprobe uinput 2>/dev/null || true
modprobe uhid 2>/dev/null || true
if [ -f /etc/bluetooth/main.conf ]; then          # controllers that pair again (an Xbox one does) and connect quickly
  for kv in "JustWorksRepairing = always" "FastConnectable = true"; do
    k="${kv%% *}"
    if grep -qE "^#?[[:space:]]*$k[[:space:]]*=" /etc/bluetooth/main.conf; then
      sed -i -E "s|^#?[[:space:]]*$k[[:space:]]*=.*|$kv|" /etc/bluetooth/main.conf
    else
      sed -i "/^\[General\]/a $kv" /etc/bluetooth/main.conf
    fi
  done
fi
echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' > /etc/udev/rules.d/60-sofa-box-uinput.rules
udevadm control --reload 2>/dev/null || true
[ -e /dev/uinput ] && chgrp input /dev/uinput && chmod 660 /dev/uinput || true
echo "options bluetooth disable_ertm=1" > /etc/modprobe.d/sofa-box-controllers.conf      # older Xbox controller firmware
SYSTEMCTL="$(command -v systemctl)"
cat > /etc/sudoers.d/sofa-box <<EOF
# The Sofa box's settings on the TV can restart it and change its boot screen; Games installs the games on its list.
$WHO ALL=(root) NOPASSWD: $SYSTEMCTL restart sofa-box sofa-box-agent, $SYSTEMCTL reboot, $LIB/sofa-box apply-boot *, $LIB/sofa-box shield *, \
  $LIB/sofa-box timezone *, $LIB/sofa-box update, $LIB/sofa-box factory-reset, $LIB/sofa-box report, \
  $LIB/sofa-box games *
EOF
chmod 440 /etc/sudoers.d/sofa-box
visudo -cf /etc/sudoers.d/sofa-box >/dev/null || { rm -f /etc/sudoers.d/sofa-box; echo "   (couldn't set up sudo for the box's settings)"; }
if [ -d /etc/polkit-1/rules.d ]; then
  cat > /etc/polkit-1/rules.d/50-sofa-box.rules <<EOF
// The Sofa box's settings on the TV choose the Wi-Fi; USB drives and discs open by themselves.
polkit.addRule(function (action, subject) {
  if (subject.user == "$WHO" && (action.id.indexOf("org.freedesktop.NetworkManager.") == 0 ||
      action.id.indexOf("org.freedesktop.udisks2.") == 0)) return polkit.Result.YES;
});
EOF
fi
if [ -d /etc/polkit-1/localauthority ]; then
  mkdir -p /etc/polkit-1/localauthority/50-local.d
  printf '[Sofa box Wi-Fi and drives]\nIdentity=unix-user:%s\nAction=org.freedesktop.NetworkManager.*;org.freedesktop.udisks2.*\nResultAny=yes\nResultInactive=yes\nResultActive=yes\n' "$WHO" \
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
# the sign-in page of the box's own Wi-Fi (at its setup) is on port 80, like a hotel's
AmbientCapabilities=CAP_NET_BIND_SERVICE
# the player (mpv) runs from here: ahead of everything but the screen
Nice=-5
CPUWeight=800
IOWeight=800
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
ExecStartPre=-+$LIB/sofa-box before-screen
ExecStart=$LIB/sofa-box kiosk
# what's on the TV comes first: the screen and the browser get the processor and the card before anything else,
# and are the last thing the kernel stops when memory runs out
Nice=-5
CPUWeight=1000
IOWeight=1000
OOMScoreAdjust=-500
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
Nice=-10
CPUWeight=900

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
Nice=-10
CPUWeight=900

[Install]
WantedBy=multi-user.target
EOF

# Sofa Shield, kept up to date every week (sites that serve ads change).
cat > /etc/systemd/system/sofa-box-shield.service <<EOF
[Unit]
Description=Sofa box: Sofa Shield's blocklist, brought up to date
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'grep -q "^# >>> Sofa Shield" /etc/hosts && $LIB/sofa-box shield update || true'
Nice=19
CPUWeight=10
IOSchedulingClass=idle
EOF
cat > /etc/systemd/system/sofa-box-shield.timer <<EOF
[Unit]
Description=Sofa box: Sofa Shield, every week

[Timer]
OnCalendar=weekly
RandomizedDelaySec=6h
Persistent=true

[Install]
WantedBy=timers.target
EOF

# The browser's rules: downloads in ~/Downloads, DuckDuckGo, no sign-in, no password or translate
# questions, nothing sent to Google about use.
for d in /etc/chromium/policies/managed /etc/opt/chrome/policies/managed; do
  mkdir -p "$d"
  cat > "$d/sofa-box.json" <<EOF
{
  "DownloadDirectory": "$HOMEDIR/Downloads",
  "PromptForDownloadLocation": false,
  "DefaultSearchProviderEnabled": true,
  "DefaultSearchProviderName": "DuckDuckGo",
  "DefaultSearchProviderKeyword": "ddg",
  "DefaultSearchProviderSearchURL": "https://duckduckgo.com/?q={searchTerms}",
  "DefaultSearchProviderSuggestURL": "https://duckduckgo.com/ac/?q={searchTerms}&type=list",
  "BrowserSignin": 0,
  "SyncDisabled": true,
  "PasswordManagerEnabled": false,
  "TranslateEnabled": false,
  "MetricsReportingEnabled": false,
  "SpellCheckServiceEnabled": false,
  "BackgroundModeEnabled": false,
  "AutoplayAllowed": true,
  "DefaultNotificationsSetting": 2,
  "DefaultGeolocationSetting": 2
}
EOF
done
mkdir -p "$HOMEDIR/Downloads" "$HOMEDIR/Videos" "$HOMEDIR/Music" "$HOMEDIR/Pictures"
chown "$WHO:" "$HOMEDIR/Downloads" "$HOMEDIR/Videos" "$HOMEDIR/Music" "$HOMEDIR/Pictures"

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
say "Tuning the system for the TV (a small board stays quick)"
# Memory: swap is compressed memory (zram), never the card; the kernel uses it early rather than stalling.
cat > /etc/sysctl.d/90-sofa-box.conf <<EOF
vm.swappiness = 100
vm.page-cluster = 0
vm.vfs_cache_pressure = 50
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10
EOF
sysctl -q -p /etc/sysctl.d/90-sofa-box.conf 2>/dev/null || true
systemctl disable --now dphys-swapfile 2>/dev/null || true               # swapping to the SD card freezes everything
# Logs kept across a restart, small (24 MB), so a report says how the start before ended (a box that restarted by
# itself: power, or a crash); written every half minute, and alarms (like "under-voltage") at once.
mkdir -p /etc/systemd/journald.conf.d /var/log/journal
printf '[Journal]\nStorage=persistent\nSystemMaxUse=24M\nSystemMaxFileSize=4M\nSyncIntervalSec=30s\n' > /etc/systemd/journald.conf.d/sofa-box.conf
# No maintenance jobs waking up while someone watches: package lists, manual pages, disk checks.
for t in apt-daily.timer apt-daily-upgrade.timer man-db.timer dpkg-db-backup.timer e2scrub_all.timer; do
  systemctl disable --now "$t" >/dev/null 2>&1 || true
done
# The processor speeds up as soon as something's pressed, and stays up while it's used (sofa-box tune).
cat > /etc/systemd/system/sofa-box-tune.service <<EOF
[Unit]
Description=Sofa box: a quick processor for the TV, Wi-Fi switched on, and the TV's screen the box's
Before=NetworkManager.service sofa-box-agent.service
After=systemd-rfkill.service

[Service]
Type=oneshot
ExecStart=$LIB/sofa-box tune

[Install]
WantedBy=multi-user.target
EOF
# A new card's first start is the slow one (the card grows to fill the SD card, keys are made, the browser sets
# itself up): its boot screen says so, and to wait. Only then: systemd counts a start as the first until it has
# gone all the way through once (a card still "uninitialized" in /etc/machine-id).
FIRST_START_NOTE="The first start takes a few minutes, and the box may restart once by itself. Just wait: it carries on."
cat > /etc/systemd/system/sofa-box-first-start.service <<EOF
[Unit]
Description=Sofa box: the first start's note on the boot screen
ConditionFirstBoot=yes
DefaultDependencies=no
After=plymouth-start.service systemd-remount-fs.service
Before=sysinit.target first-boot-complete.target

[Service]
Type=oneshot
ExecStart=-/usr/bin/plymouth display-message "--text=$FIRST_START_NOTE"
RemainAfterExit=yes

[Install]
WantedBy=sysinit.target
EOF
# cloud-init (Raspberry Pi Imager's settings, if any) does its work at the first start; after that it would only run
# its five steps again at every start, in the browser's way on a small board. It switches itself off once it's done.
# Imager's user name and password end with Raspberry Pi OS's cancel-rename, which takes the TV's screen from Sofa (a
# text console, a login on tty1): `sofa-box own-screen` gives it back, at every start (tune) and once cloud-init is
# done. Its last step (apt-get for Imager's "packages", Imager's keyboard) gets what the TV leaves of the processor.
mkdir -p /etc/systemd/system/cloud-final.service.d
cat > /etc/systemd/system/cloud-final.service.d/sofa-box.conf <<EOF
[Service]
ExecStartPre=-$SYSTEMCTL set-property --runtime cloud-init-main.service CPUWeight=10 IOWeight=10
ExecStartPost=-/bin/sh -c "mkdir -p /etc/cloud && touch /etc/cloud/cloud-init.disabled"
ExecStartPost=-$LIB/sofa-box own-screen
EOF
# The box's own Wi-Fi (at its setup) works like a hotel's: every name is the box, so a phone that joins opens its
# sign-in sheet by itself, and the sheet opens the phone remote (sofa-box-agent.py, Captive).
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
printf '# Sofa box: on its own Wi-Fi every name is the box (its sign-in page opens the phone remote)\naddress=/#/10.42.0.1\n' \
  > /etc/NetworkManager/dnsmasq-shared.d/sofa-box.conf
"$LIB/sofa-box" wifi-on ${IMAGE:+--files} || true   # Wi-Fi on even with no country set: the box's own Wi-Fi at its setup
if dpkg -s systemd-zram-generator >/dev/null 2>&1; then
  printf '[zram0]\nzram-size = ram / 2\ncompression-algorithm = zstd\n' > /etc/systemd/zram-generator.conf
elif [ -f /etc/default/zramswap ]; then
  sed -i -E 's/^#?PERCENT=.*/PERCENT=50/' /etc/default/zramswap
fi

if [ -n "$OTHER" ]; then
  say "Not a Raspberry Pi: what Debian has in place of the Pi's parts"
  SOFA_BOX_USER="$WHO" SOFA_BOX_HOME="$HOMEDIR" sh "$LIB/other-hardware.sh" ${IMAGE:+--image} \
    || echo "   (some of it couldn't be set up; sofa-box doctor says what's there)"
fi

# tty1 is the TV's screen, and Sofa's: no login there. (systemd's own presets turn one on at a card's first start, and
# it only ever lost to Sofa's screen; Raspberry Pi OS's cancel-rename turns it on too: `sofa-box own-screen`.)
mkdir -p /etc/systemd/system-preset
echo "disable getty@.service" > /etc/systemd/system-preset/10-sofa-box.preset
systemctl daemon-reload
systemctl set-default graphical.target >/dev/null
systemctl disable getty@tty1.service >/dev/null 2>&1 || true
systemctl enable sofa-box-agent.service sofa-box.service sofa-box-input.service sofa-box-cec.service sofa-box-shield.timer sofa-box-tune.service \
  sofa-box-first-start.service
if ! grep -q '^# >>> Sofa Shield' /etc/hosts; then
  say "Sofa Shield (ad blocking for the whole box)"
  "$LIB/sofa-box" shield on || echo "   (no blocklist now: Settings → Sofa Shield turns it on later)"
fi
if [ -z "$IMAGE" ]; then
  systemctl restart sofa-box-agent.service sofa-box-input.service sofa-box-cec.service
  systemctl restart sofa-box.service
fi

echo
echo "Done. The Sofa Box opens on the TV now and every time the box starts."
echo "  - Opening Sofa asks where from: a Sofa at home, a share link, Sofa on this box, Jellyfin, Emby or Plex."
echo "  - Sign in: the TV shows a code; approve it on your phone (Sofa -> your picture -> Pair a TV)."
echo "  - The TV's own remote works through HDMI (turn on VIERA Link / Anynet+ / SimpLink / CEC on the TV)."
echo "  - A game controller: sofa-box pair-controller.   Is everything right?  sofa-box doctor"
if [ -n "$BOOT" ] && ! cmp -s "$BOOT/config.txt" "$BOOT/config.txt.before-sofa-box" 2>/dev/null; then
  echo "  - Restart once for the screen settings: sudo reboot"
fi
