#!/bin/sh
# Sets up the Sofa Box certificate service on a Mac that's always on (it runs at login, and again if it stops).
#   sh deploy/box-certs/install-mac.sh          install or update it
#   sh deploy/box-certs/install-mac.sh remove   stop it and remove it (keeps ~/.config/sofa-box-certs)
# The Cloudflare token isn't part of this: put it in ~/.config/sofa-box-certs/cloudflare-token (README.md, step 2).
set -e
LABEL=uk.edgeventure.sofa-box-certs
APP="$HOME/Library/Application Support/SofaBoxCerts"
CONF="$HOME/.config/sofa-box-certs"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/sofa-box-certs.log"
HERE="$(cd "$(dirname "$0")" && pwd)"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
if [ "${1:-}" = remove ]; then
  rm -f "$PLIST"
  rm -rf "$APP"
  echo "Removed. (The token, the account key and boxes.json stay in $CONF.)"
  exit 0
fi

PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "Needs python3 (xcode-select --install, or Homebrew's python)."; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 8))' || { echo "Needs Python 3.8 or newer ($PY is older)."; exit 1; }
command -v openssl >/dev/null || { echo "Needs the openssl command."; exit 1; }

mkdir -p "$APP" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
mkdir -p "$CONF" && chmod 700 "$CONF"
cp "$HERE/sofa-box-certs.py" "$APP/sofa-box-certs.py"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$APP/sofa-box-certs.py</string>
    <string>serve</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

if [ ! -s "$CONF/cloudflare-token" ]; then
  echo "Installed, but not started: no Cloudflare token yet. Put it in $CONF/cloudflare-token (README.md, step 2), then run this again."
  exit 0
fi
chmod 600 "$CONF/cloudflare-token"
"$PY" "$APP/sofa-box-certs.py" check || { echo "Fix what 'check' says (above), then run this again."; exit 1; }
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"
sleep 2
if curl -fsS -m 5 http://127.0.0.1:8470/v1/health >/dev/null; then
  echo "Running on http://127.0.0.1:8470. Next: the tunnel's public hostname (README.md, step 4). Its log: $LOG"
else
  echo "It didn't answer yet; its log: $LOG"
fi
