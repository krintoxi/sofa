#!/usr/bin/env python3
"""Makes the xz test fixtures for XZUnpacker (Tests/ImagerKitTests/Fixtures/mixed-*.xz) with the real `xz`.

The input is made here, the same every time: zeros, text, a few random bytes, a repeating pattern with small changes,
and counters. It isn't kept; the tests know its size and SHA-256, printed below. Each fixture packs it with different
xz options, so the unpacker meets every check type, odd literal and position settings, a tiny dictionary, many blocks
with their sizes in the headers, the largest preset, and a filter it must refuse. `random-first.xz` packs 160 KiB of
random bytes followed by the same input: LZMA2 stores random bytes as they are, so it holds stored chunks both with a
dictionary reset (the block's first) and without, then packed chunks that must bring new settings.

    python3 imager/scripts/xz-fixtures.py        (needs xz 5.2 or newer on the PATH)
"""
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "Tests", "ImagerKitTests", "Fixtures")

VARIANTS = {
    "mixed-crc32.xz": ["-6", "-C", "crc32"],
    "mixed-nocheck.xz": ["-6", "-C", "none"],
    "mixed-sha256.xz": ["-6", "-C", "sha256"],
    "mixed-lc1lp3pb4.xz": ["--lzma2=preset=6,lc=1,lp=3,pb=4"],
    "mixed-dict4k.xz": ["--lzma2=preset=6,dict=4KiB"],
    "mixed-blocks.xz": ["-6", "-T1", "--block-size=64KiB"],
    "mixed-9e.xz": ["-9e"],
    "mixed-x86.xz": ["--x86", "--lzma2=preset=6"],
}
RANDOM_FIRST = ("random-first.xz", ["-6"])


def xorshift(seed):
    x = seed
    while True:
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        yield x


def make_input():
    r = xorshift(2026_11_15)
    out = bytearray()
    out += bytes(256 * 1024)
    words = [b"sofa", b"box", b"imager", b"stick", b"card", b"disk", b"write", b"read", b"back", b"check", b"the",
             b"a", b"of", b"windows", b"linux", b"block", b"stream", b"index"]
    text = bytearray()
    while len(text) < 48 * 1024:
        text += words[next(r) % len(words)] + (b"\n" if next(r) % 9 == 0 else b" ")
    out += text[:48 * 1024]
    out += bytes(next(r) & 0xFF for _ in range(4 * 1024))
    pattern = bytearray(next(r) & 0xFF for _ in range(4096))
    for i in range(64):
        pattern[next(r) % 4096] = next(r) & 0xFF
        out += pattern
    for i in range(16 * 1024):
        out += i.to_bytes(4, "little")
    return bytes(out)


def pack(name, args, data):
    packed = subprocess.run(["xz", "--stdout", "--keep"] + args, input=data, stdout=subprocess.PIPE, check=True).stdout
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(packed)
    print(f"{name}: {len(packed)} bytes ({' '.join(args)})")


def main():
    data = make_input()
    print(f"input: {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()}")
    for name, args in VARIANTS.items():
        pack(name, args, data)
    r = xorshift(160)
    first = bytes(next(r) & 0xFF for _ in range(160 * 1024)) + data
    print(f"random first: {len(first)} bytes, sha256 {hashlib.sha256(first).hexdigest()}")
    pack(*RANDOM_FIRST, first)


if __name__ == "__main__":
    sys.exit(main())
