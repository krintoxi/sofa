#!/bin/sh
# Install Sofa on this computer, in one go.
#
#     curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/tools/get-sofa.sh | sh
#
# It puts Sofa in ~/Sofa (or the folder you name: ... | sh -s -- /path/to/folder), makes the
# ~/Entertainment folders, and starts Sofa as a background service that comes back after a
# restart. Already have Sofa? This updates it instead (same as tools/update.sh).
set -e
REPO="${SOFA_REPO:-krintoxi/sofa}"
BRANCH="${SOFA_BRANCH:-main}"
APP="${1:-$HOME/Sofa}"

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nSorry, the install stopped: %s\n' "$*" >&2; exit 1; }

if [ -f "$APP/sofa.py" ]; then
  say "Sofa is already in $APP, so this updates it"
  exec sh "$APP/tools/update.sh" "$APP"
fi

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  [ "$(uname)" = "Darwin" ] && fail "Python 3 is needed. Run  xcode-select --install  (or install it from python.org), then run this again."
  fail "Python 3 is needed. Install it with your package manager (for example: sudo apt install python3), then run this again."
fi

say "Downloading Sofa into $APP"
if command -v git >/dev/null 2>&1; then
  git clone --depth 1 --branch "$BRANCH" "https://github.com/$REPO.git" "$APP" || fail "the download didn't work (are you online?)"
else
  command -v curl >/dev/null 2>&1 || fail "curl or git is needed to download Sofa"
  mkdir -p "$APP"
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" | tar xz -C "$APP" --strip-components 1 \
    || fail "the download didn't work (are you online?)"
fi

if ! command -v ffmpeg >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/ffmpeg ] && [ ! -x /usr/local/bin/ffmpeg ]; then
  say "One more thing you'll want: ffmpeg (it lets MKV, AVI and other files play everywhere)"
  if [ "$(uname)" = "Darwin" ]; then
    if command -v brew >/dev/null 2>&1; then
      echo "    Installing it with Homebrew..."; brew install ffmpeg || echo "    That didn't work; run  brew install ffmpeg  yourself later."
    else
      echo "    Install Homebrew from https://brew.sh, then run:  brew install ffmpeg"
    fi
  else
    echo "    Install it with your package manager, for example:  sudo apt install ffmpeg"
  fi
fi

mkdir -p "$HOME/Entertainment/Inbox"
say "Starting Sofa as a background service"
sh "$APP/deploy/install.sh"
say "All done. Open http://localhost:8090 on this computer (or this computer's address from any device at home) and create your admin account."
