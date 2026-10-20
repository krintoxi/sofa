#!/bin/sh
# Install Sofa as a background service for the current user.
#   macOS: a LaunchAgent (starts at login, restarts if it stops)
#   Linux: a systemd user service (enable lingering so it runs without a login)
# Usage: ./deploy/install.sh [--label com.example.sofa]
set -e
APP="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="local.sofa.server"
[ "$1" = "--label" ] && LABEL="$2"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "Python 3 is required."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || { echo "Python 3.8 or newer is required."; exit 1; }
mkdir -p "$APP/data"
"$PY" -m py_compile "$APP"/sofa.py "$APP"/sofa/*.py

if ! command -v ffmpeg >/dev/null 2>&1 && [ ! -x "$APP/vendor/ffmpeg/bin/ffmpeg" ]; then
  echo "Note: ffmpeg isn't installed. Sofa will run, but only files a device already supports will play."
  echo "      Install it with 'brew install ffmpeg' (macOS) or your package manager (Linux)."
fi

case "$(uname)" in
  Darwin)
    PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    sed -e "s|__PYTHON__|$PY|" -e "s|__APP__|$APP|g" -e "s|__LABEL__|$LABEL|" "$APP/deploy/macos/sofa.plist.template" > "$PLIST"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "Installed $PLIST"
    ;;
  Linux)
    UNIT="$HOME/.config/systemd/user/sofa.service"
    mkdir -p "$(dirname "$UNIT")"
    sed -e "s|__PYTHON__|$PY|" -e "s|__APP__|$APP|g" "$APP/deploy/linux/sofa.service" > "$UNIT"
    systemctl --user daemon-reload
    systemctl --user enable --now sofa.service
    echo "Installed $UNIT. To keep Sofa running when you're logged out: sudo loginctl enable-linger $USER"
    ;;
  *) echo "Unsupported system; run 'python3 sofa.py serve' yourself."; exit 1 ;;
esac
echo "Sofa is starting. Open http://$(hostname):8090 and create the admin account."
