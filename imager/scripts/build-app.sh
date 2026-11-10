#!/bin/bash
# Builds "Sofa Box Imager.app" (Apple silicon and Intel in one) and a zip of it, in imager/build/.
#
#   imager/scripts/build-app.sh            release build
#   BUILD=42 imager/scripts/build-app.sh   CI passes its run number as the bundle's build number
#
# The app is signed ad hoc only (codesign --sign -: no identity, no keys), which Apple silicon needs to run it at
# all. It is NOT signed with a Developer ID or notarised: a downloaded copy is blocked by Gatekeeper until the owner
# allows it in System Settings -> Privacy & Security. README.md ("Signing") says what proper signing needs.
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

codesign --force --sign - --timestamp=none "$APP"
codesign --verify --strict --verbose=2 "$APP"

ZIP="build/Sofa-Box-Imager-$VERSION-mac-unsigned.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
echo "Built $APP ($VERSION, build $BUILD) and $ZIP"
