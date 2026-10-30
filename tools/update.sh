#!/bin/sh
# Update Sofa to the newest version from GitHub.
#
# Your shows, movies and music are not touched, and neither are your accounts, watch
# history, settings or artwork (they live in Sofa's data/ folder, which this script
# leaves alone). It saves a copy of the old code and of data/ first, so you can go back.
#
# Easiest, from any Terminal window (works with every version of Sofa):
#     curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/tools/update.sh | sh
#
# Or, if your Sofa folder isn't ~/Sofa, say where it is:
#     curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/tools/update.sh | sh -s -- /path/to/Sofa
#
# Newer versions also have an "Update" button on the Server page that does the same thing.
set -e
REPO="${SOFA_REPO:-krintoxi/sofa}"
BRANCH="${SOFA_BRANCH:-main}"
STAMP="$(date +%Y-%m-%d_%H%M%S)"

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nSorry, the update stopped: %s\nNothing of yours was changed.\n' "$*" >&2; exit 1; }

# ---- 1. find the Sofa folder
APP="$1"
if [ -z "$APP" ]; then
  HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"
  for c in "$HERE/.." "$HOME/Sofa" "$HOME/sofa" "$HOME/Applications/Sofa" "/opt/sofa"; do
    [ -f "$c/sofa.py" ] && [ -d "$c/sofa" ] && APP="$(cd "$c" && pwd)" && break
  done
fi
if [ -z "$APP" ]; then   # look where the background service points
  for f in "$HOME"/Library/LaunchAgents/*sofa*.plist "$HOME/.config/systemd/user/sofa.service"; do
    [ -f "$f" ] || continue
    P="$(grep -o '/[^<> ]*/sofa\.py' "$f" | head -1)"
    [ -n "$P" ] && [ -f "$P" ] && APP="$(dirname "$P")" && break
  done
fi
[ -n "$APP" ] && [ -f "$APP/sofa.py" ] || fail "couldn't find your Sofa folder. Run it again with the folder at the end, like: sh update.sh ~/Sofa"
say "Updating Sofa in $APP"
OLD="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$APP/sofa/__init__.py" 2>/dev/null)"
echo "    Current version: ${OLD:-unknown}"

# ---- 2. stop the background service while the files change
LABEL=""
case "$(uname)" in
  Darwin)
    for f in "$HOME"/Library/LaunchAgents/*.plist; do
      [ -f "$f" ] && grep -q "$APP/sofa.py" "$f" 2>/dev/null && LABEL="$(basename "$f" .plist)" && break
    done
    [ -n "$LABEL" ] && { say "Stopping Sofa ($LABEL)"; launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true; } ;;
  Linux)
    if systemctl --user cat sofa.service >/dev/null 2>&1; then say "Stopping Sofa"; systemctl --user stop sofa.service || true; LABEL=sofa; fi ;;
esac

# ---- 3. back up the old code and data/ (not your media)
mkdir -p "$APP/data/backups"
say "Saving a copy of the current version in data/backups"
( cd "$APP" && tar czf "data/backups/code-${OLD:-old}-$STAMP.tar.gz" --exclude ./data --exclude ./vendor --exclude ./.git --exclude '__pycache__' . )
( cd "$APP/data" && tar czf "backups/data-before-update-$STAMP.tar.gz" --exclude ./cache --exclude ./backups . ) || true

# ---- 4. get the new code
if [ -d "$APP/.git" ] && command -v git >/dev/null 2>&1; then
  say "Downloading the new version with git"
  cd "$APP"
  git fetch "https://github.com/$REPO.git" "$BRANCH" || fail "git couldn't download the update (are you online?)"
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    git stash push -m "Local changes saved by update.sh $STAMP" >/dev/null && echo "    Your own edits to Sofa's code were saved (git stash list)."
  fi
  git merge --ff-only FETCH_HEAD 2>/dev/null || git checkout -B "$BRANCH" FETCH_HEAD
else
  command -v curl >/dev/null 2>&1 || fail "curl is needed to download the update"
  say "Downloading the new version from GitHub"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" -o "$TMP/sofa.tar.gz" || fail "the download didn't work (are you online?)"
  mkdir "$TMP/new" && tar xzf "$TMP/sofa.tar.gz" -C "$TMP/new" --strip-components 1
  [ -f "$TMP/new/sofa.py" ] && [ -f "$TMP/new/sofa/__init__.py" ] || fail "the download doesn't look like Sofa"
  say "Replacing Sofa's code (data/ and vendor/ stay as they are)"
  for name in sofa client deploy tools docs integrations sofa.py README.md LICENSE .gitignore; do
    [ -e "$TMP/new/$name" ] || continue
    rm -rf "$APP/$name"
    cp -R "$TMP/new/$name" "$APP/$name"
  done
fi

# ---- 5. check it, then start it again
PY="$(command -v python3 || true)"
[ -n "$PY" ] || fail "python3 isn't installed"
"$PY" -m py_compile "$APP"/sofa.py "$APP"/sofa/*.py || fail "the new version didn't pass its check. Your old code is in data/backups/code-${OLD:-old}-$STAMP.tar.gz"
NEW="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$APP/sofa/__init__.py")"
if [ -n "$LABEL" ]; then
  say "Starting Sofa again"
  if [ "$LABEL" = "sofa" ] || [ "$LABEL" = "local.sofa.server" ]; then sh "$APP/deploy/install.sh" >/dev/null
  else sh "$APP/deploy/install.sh" --label "$LABEL" >/dev/null; fi
else
  echo "    Sofa isn't installed as a background service here; start it with:  cd \"$APP\" && python3 sofa.py serve"
fi
say "Done. Sofa ${OLD:-} -> ${NEW:-new version}. Your library, accounts and settings are untouched."
