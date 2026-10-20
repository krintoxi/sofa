#!/bin/bash
# Builds a lean ffmpeg into vendor/ffmpeg for Macs Homebrew no longer supports (macOS 12 and older).
# Uses macOS's own VideoToolbox/AudioToolbox encoders, no external libraries. About 30 minutes on a 2011 iMac.
set -euo pipefail
APP="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="$APP/vendor/ffmpeg"
SRC="$APP/vendor/src"
VER=7.1.1
mkdir -p "$SRC" "$PREFIX"
cd "$SRC"
[ -f ffmpeg-$VER.tar.xz ] || curl -fL --retry 3 -o ffmpeg-$VER.tar.xz "https://ffmpeg.org/releases/ffmpeg-$VER.tar.xz"
shasum -a 256 ffmpeg-$VER.tar.xz
rm -rf ffmpeg-$VER && tar xf ffmpeg-$VER.tar.xz && cd ffmpeg-$VER
./configure --prefix="$PREFIX" --disable-doc --disable-debug --disable-ffplay --disable-x86asm \
  --enable-videotoolbox --enable-audiotoolbox --disable-sdl2 --disable-xlib --disable-libxcb
make -j4
make install
"$PREFIX/bin/ffmpeg" -hide_banner -version | head -1
"$PREFIX/bin/ffmpeg" -hide_banner -encoders | grep -E "h264_videotoolbox|aac_at| aac "
echo BUILD_OK
