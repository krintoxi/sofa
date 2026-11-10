#!/bin/bash
# Builds "Sofa Box Imager.app" (Apple silicon and Intel in one) and a zip of it, in imager/build/.
#
#   imager/scripts/build-app.sh            release build, signed ad hoc only (…-mac-unsigned.zip)
#   BUILD=42 imager/scripts/build-app.sh   CI passes its run number as the bundle's build number
#
# Signed and notarised (…-mac.zip, opens on any Mac with no warning), when these are set:
#   SIGN_IDENTITY="Developer ID Application"   a Developer ID Application identity in the keychain search list
#   TEAM_ID=L3R62A4K37                          the team the signature must carry (checked after signing)
#   NOTARY_PROFILE=sofa-box-imager              a notarytool keychain profile (xcrun notarytool store-credentials), or
#   NOTARY_KEY=AuthKey.p8 NOTARY_KEY_ID=… NOTARY_ISSUER=…   an App Store Connect API key (what GitHub uses)
# With SIGN_IDENTITY alone it's signed but not notarised (…-mac-signed.zip): for checking, not for handing out.
# Without SIGN_IDENTITY the app is signed ad hoc only (codesign --sign -: no identity, no keys), which Apple silicon
# needs to run it at all; a downloaded copy is then blocked by Gatekeeper until its owner allows it in System
# Settings -> Privacy & Security. README.md ("Signing") has the rest.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(tr -d ' \n' < VERSION)"
BUILD="${BUILD:-1}"
APP="build/Sofa Box Imager.app"
ARCHS=(--arch arm64 --arch x86_64)

swift build -c release "${ARCHS[@]}" --product SofaBoxImager
BIN="$(swift build -c release "${ARCHS[@]}" --show-bin-path)/SofaBoxImager"
lipo -info "$BIN"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/SofaBoxImager"
sed -e "s/@VERSION@/$VERSION/" -e "s/@BUILD@/$BUILD/" Resources/Info.plist > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"

# Sofa's own typefaces (SIL Open Font License 1.1), with their licences.
mkdir -p "$APP/Contents/Resources/Fonts"
cp ../client/vendor/fonts/bricolage-grotesque-latin-opsz-normal.woff2 ../client/vendor/fonts/instrument-sans-latin-wght-normal.woff2 \
   ../client/vendor/fonts/LICENSE-Bricolage-Grotesque.txt ../client/vendor/fonts/LICENSE-Instrument-Sans.txt \
   "$APP/Contents/Resources/Fonts/"

# The icon: Sofa's own (client/icons/icon-512.png), at every size macOS asks for.
ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
SRC=../client/icons/icon-512.png
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); [ "$d" -le 512 ] && sips -z "$d" "$d" "$SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
cp "$SRC" "$ICONSET/icon_256x256@2x.png"
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

IDENTITY="${SIGN_IDENTITY:-}"
KIND=unsigned
if [ -z "$IDENTITY" ]; then
  codesign --force --sign - --timestamp=none "$APP"
else
  # The hardened runtime and a secure timestamp, which notarisation requires. No entitlements: the app isn't
  # sandboxed (a sandboxed app can't write a raw disk) and its one privileged step is Apple's own authopen.
  codesign --force --options runtime --timestamp --sign "$IDENTITY" "$APP"
  KIND=signed
  TEAM="$(codesign -dv "$APP" 2>&1 | sed -n 's/^TeamIdentifier=//p')"
  if [ -n "${TEAM_ID:-}" ] && [ "$TEAM" != "$TEAM_ID" ]; then
    echo "Signed by team '$TEAM', not $TEAM_ID: refusing it." >&2
    exit 1
  fi
  codesign -dv "$APP" 2>&1 | grep -E '^(Authority|TeamIdentifier|Runtime Version|Timestamp)=' || true
fi
codesign --verify --strict --deep --verbose=2 "$APP"

if [ "$KIND" = signed ] && { [ -n "${NOTARY_PROFILE:-}" ] || [ -n "${NOTARY_KEY:-}" ]; }; then
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    AUTH=(--keychain-profile "$NOTARY_PROFILE")
  else
    AUTH=(--key "$NOTARY_KEY" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER")
  fi
  SUBMIT="build/notarise-$VERSION.zip"
  rm -f "$SUBMIT"
  ditto -c -k --keepParent "$APP" "$SUBMIT"
  echo "Sending it to Apple's notary service (a few minutes)…"
  xcrun notarytool submit "$SUBMIT" "${AUTH[@]}" --wait --timeout 30m --output-format json > build/notarisation.json || true
  cat build/notarisation.json; echo
  STATUS="$(plutil -extract status raw -o - build/notarisation.json 2>/dev/null || echo unknown)"
  if [ "$STATUS" != Accepted ]; then
    ID="$(plutil -extract id raw -o - build/notarisation.json 2>/dev/null || true)"
    [ -z "$ID" ] || xcrun notarytool log "$ID" "${AUTH[@]}" || true
    echo "Apple's notary service said: $STATUS" >&2
    exit 1
  fi
  rm -f "$SUBMIT"
  # The ticket goes into the app itself, so a Mac that's offline the first time it opens it still trusts it.
  xcrun stapler staple "$APP"
  xcrun stapler validate "$APP"
  spctl --assess --type execute --verbose=2 "$APP"
  KIND=notarised
fi

case "$KIND" in
  notarised) ZIP="build/Sofa-Box-Imager-$VERSION-mac.zip" ;;
  signed)    ZIP="build/Sofa-Box-Imager-$VERSION-mac-signed.zip" ;;
  *)         ZIP="build/Sofa-Box-Imager-$VERSION-mac-unsigned.zip" ;;
esac
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
echo "Built $APP ($VERSION, build $BUILD, $KIND) and $ZIP"
