#!/bin/sh
# Make a Sofa box card with Raspberry Pi's rpi-image-gen: a prototype beside tools/build-sofa-box-image.sh, which
# stays the way the cards on the releases page are made. See tools/image-gen/README.md.
#
#   tools/image-gen/build.sh --rpi-image-gen DIR [OUT_DIR] [--sofa http://192.168.1.20:8090]
#
#   --rpi-image-gen   a checkout of https://github.com/raspberrypi/rpi-image-gen, at the commit the workflow pins
#                     (.github/workflows/sofa-box-image-gen.yml), its dependencies installed (sudo DIR/install_deps.sh)
#   --sofa            the Sofa computer's address, built in (it still looks for Sofa itself if that changes)
#
# As a normal user (rpi-image-gen runs the build in a user namespace, with podman unshare), on an Arm computer:
# Raspberry Pi OS 64-bit, Debian Bookworm or Trixie arm64, or GitHub's ubuntu-24.04-arm (rpi-image-gen's own CI).
# Writes OUT_DIR/sofa-box-os-VERSION-imagegen.img.xz, its .sha256, its report, the SBOM (SPDX JSON), the package
# list, and, when grype is installed, the CVE report.
set -eu
OUT=out SOFA="" RIG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --rpi-image-gen) RIG="$2"; shift ;;
    --sofa) SOFA="${2%/}"; shift ;;
    -*) echo "Unknown option: $1"; exit 1 ;;
    *) OUT="$1" ;;
  esac
  shift
done
[ -n "$RIG" ] && [ -x "$RIG/rpi-image-gen" ] || { echo "Needs --rpi-image-gen DIR (a checkout of raspberrypi/rpi-image-gen)."; exit 1; }
[ "$(id -u)" != 0 ] || { echo "Run it as a normal user: rpi-image-gen does the rest in a user namespace."; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RIG="$(cd "$RIG" && pwd)"
VER="$(tr -d ' \n' < "$REPO/deploy/sofa-box/VERSION")"
NAME="sofa-box-os-$VER-imagegen"
COMMIT="$(git -C "$RIG" rev-parse HEAD 2>/dev/null || echo unknown)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
WORK="${SOFA_BOX_IMAGE_GEN_WORK:-$OUT/work}"     # rpi-image-gen's work folder: the root, the image, its caches (big)

echo "== Sofa Box OS $VER with rpi-image-gen $COMMIT"
"$RIG/rpi-image-gen" build -S "$HERE" -c sofa-box.yaml -- \
  IGconf_sys_workroot="$WORK" IGconf_image_name="$NAME" IGconf_artefact_version="$VER" \
  IGconf_sofabox_made_with="rpi-image-gen $(echo "$COMMIT" | cut -c1-12)" ${SOFA:+IGconf_sofabox_sofa="$SOFA"}

IMG="$WORK/image-$NAME/$NAME.img"
[ -f "$IMG" ] || { echo "No card was made ($IMG is missing)."; exit 1; }
SBOM="$(find "$WORK" -name '*.sbom' -type f | head -n 1)"
MANIFEST="$(find "$WORK" -path '*/deploy-*' -name manifest -type f | head -n 1)"
[ -n "$MANIFEST" ] || MANIFEST="$(find "$WORK" -name manifest -type f | head -n 1)"

echo "== What's on the card"
# The root partition starts where the MBR's second entry says (in 512-byte sectors).
START="$(od -An -tu4 -j 470 -N 4 "$IMG" | tr -d ' ')"
SPACE="$(/sbin/dumpe2fs -h "$IMG?offset=$((START * 512))" 2>/dev/null | awk -F: '
  /^Block count/ {c=$2} /^Free blocks/ {f=$2} /^Block size/ {b=$2}
  END {printf "%.1fG used, %.1fG free", (c-f)*b/1073741824, f*b/1073741824}')"
REPORT="$OUT/$NAME-report.txt"
{
  echo "Sofa Box OS image-gen prototype: made with Raspberry Pi's rpi-image-gen ($COMMIT), for testing beside"
  echo "today's card. Not a release: the cards on the releases page are still made by tools/build-sofa-box-image.sh."
  cat "$WORK/image-$NAME/report-body.txt" "$WORK/image-$NAME/report-boot.txt"
  echo "Space: $SPACE"
  cat "$WORK/image-$NAME/wifi-before.txt"
} > "$REPORT"

echo "== Packing $NAME.img.xz"
xz -T0 -6 -c "$IMG" > "$OUT/$NAME.img.xz"
(cd "$OUT" && sha256sum "$NAME.img.xz" > "$NAME.img.xz.sha256")
echo "Card: $NAME.img.xz, $(du -h "$OUT/$NAME.img.xz" | cut -f1) packed, $(du -h --apparent-size "$IMG" | cut -f1) written" >> "$REPORT"
[ -z "$SBOM" ] || cp "$SBOM" "$OUT/$NAME.sbom.spdx.json"
[ -z "$MANIFEST" ] || cp "$MANIFEST" "$OUT/$NAME-packages.txt"

if [ -n "$SBOM" ] && command -v grype >/dev/null; then
  echo "== Known vulnerabilities (grype, from the SBOM)"
  if grype "sbom:$OUT/$NAME.sbom.spdx.json" -o json > "$OUT/$NAME-cve.json" &&
     grype "sbom:$OUT/$NAME.sbom.spdx.json" -o table > "$OUT/$NAME-cve.txt"; then
    python3 -I - "$OUT/$NAME-cve.json" >> "$REPORT" <<'EOF'
import collections, json, sys
m = json.load(open(sys.argv[1])).get("matches", [])
by = collections.Counter(x["vulnerability"].get("severity", "Unknown") for x in m)
fixable = sum(1 for x in m if x["vulnerability"].get("fix", {}).get("state") == "fixed")
order = ["Critical", "High", "Medium", "Low", "Negligible", "Unknown"]
print("Known vulnerabilities (grype, from the SBOM): %d matches, %d with a fix released: %s" % (
    len(m), fixable, ", ".join("%s %d" % (s, by[s]) for s in order if by[s])))
EOF
  else
    echo "Known vulnerabilities: grype failed" >> "$REPORT"
  fi
fi
cat "$REPORT"
ls -lh "$OUT"
