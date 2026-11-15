#!/usr/bin/env python3
"""Each page game's home-screen app: games/<id>/app.webmanifest and its icons (icon-192.png, icon-512.png), made from
games.json, so a phone or a tablet can add a game to its home screen and open it full screen, on its side.

pad.js points a page at these when a touch screen is used (nowhere else: the box and computers never ask for them).
The icon is drawn here in pixels, nothing from outside: the game's two letters in the engines' own 5x7 letters (read
from low3d.js), in bone on ink, over a bar of the game's colour. Python's own library only.

    python3 tools/game-apps.py           write them all again (after adding a game to games.json)
    python3 tools/game-apps.py --check   say what's missing or out of date, change nothing (exit 1 if anything is)
"""
import json
import os
import re
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMES = os.path.join(ROOT, "deploy", "sofa-box", "games")
INK, BONE = (0x0B, 0x0D, 0x10), (0xEF, 0xE6, 0xD2)
# (the canvas games are 16:9 and want a phone on its side; Pair Up is page cards and fits either way)
ANY_WAY = {"pair-up"}


def glyphs():
    with open(os.path.join(GAMES, "low3d.js"), encoding="utf-8") as f:
        js = f.read()
    block = js[js.index("const GLYPHS = {"):]
    block = block[:block.index("};")]
    return {k: [int(n) for n in v.split(",")] for k, v in re.findall(r"""(?:^|[\s,{])["']?([A-Z0-9])["']?: \[([\d, ]+)\]""", block)}


def letters(name):
    """Two letters: the first of each word, or the first two of one word."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    s = (words[0][0] + words[1][0]) if len(words) > 1 else words[0][:2]
    return s.upper()


def png(w, h, px):
    raw = b"".join(b"\x00" + bytes(px[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def icon(size, name, colour, G):
    """Full bleed (a launcher's mask may cut the corners: everything that matters is in the middle 70%)."""
    col = tuple(int(colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    px = bytearray(INK * (size * size))
    def rect(x0, y0, x1, y1, c):
        for y in range(max(0, y0), min(size, y1)):
            row = y * size * 3
            for x in range(max(0, x0), min(size, x1)):
                px[row + x * 3:row + x * 3 + 3] = bytes(c)
    s = letters(name)
    k = max(1, round(size * 0.052))                      # one of the letters' pixels
    w, h = (len(s) * 6 - 1) * k, 7 * k
    x0, y0 = (size - w) // 2, (size - h) // 2 - k
    for i, ch in enumerate(s):
        rows = G.get(ch, G["0"])
        for y in range(7):
            for b in range(5):
                if (rows[y] >> (4 - b)) & 1:
                    X, Y = x0 + (i * 6 + b) * k, y0 + y * k
                    rect(X + k // 3, Y + k // 3, X + k + k // 3, Y + k + k // 3, col)   # (its shadow, in the game's colour)
                    rect(X, Y, X + k, Y + k, BONE)
    bar = max(2, round(size * 0.035))
    rect(x0, y0 + h + 2 * k, x0 + w, y0 + h + 2 * k + bar, col)
    return png(size, size, px)


def manifest(g):
    return {
        "name": g["name"], "short_name": g["name"], "description": g["about"],
        "start_url": "./", "scope": "./", "display": "fullscreen",
        "orientation": "any" if g["id"] in ANY_WAY else "landscape",
        "background_color": "#0b0d10", "theme_color": "#0b0d10",
        "icons": [{"src": "icon-%d.png" % n, "sizes": "%dx%d" % (n, n), "type": "image/png", "purpose": "any maskable"} for n in (192, 512)],
    }


def wanted():
    with open(os.path.join(GAMES, "games.json"), encoding="utf-8") as f:
        cat = json.load(f)
    G = glyphs()
    for g in cat["games"]:
        d = os.path.join(GAMES, g["id"])
        yield os.path.join(d, "app.webmanifest"), (json.dumps(manifest(g), indent=2, ensure_ascii=False) + "\n").encode()
        for n in (192, 512):
            yield os.path.join(d, "icon-%d.png" % n), icon(n, g["name"], g["color"], G)


def pixels(data):
    """A PNG's size and pixels, unpacked (zlib packs the same pixels differently from one build to the next)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return data
    at, idat, head = 8, b"", b""
    while at < len(data):
        n, kind = struct.unpack(">I4s", data[at:at + 8])
        if kind == b"IHDR":
            head = data[at + 8:at + 8 + n]
        elif kind == b"IDAT":
            idat += data[at + 8:at + 8 + n]
        at += 12 + n
    return head + zlib.decompress(idat)


def main():
    check, bad = "--check" in sys.argv, 0
    for path, data in wanted():
        try:
            with open(path, "rb") as f:
                have = f.read()
            same = have == data or (path.endswith(".png") and pixels(have) == pixels(data))
        except (OSError, struct.error, zlib.error):
            same = False
        if same:
            continue
        bad += 1
        print(("out of date: " if check else "wrote ") + os.path.relpath(path, ROOT))
        if not check:
            with open(path, "wb") as f:
                f.write(data)
    return 1 if check and bad else 0


if __name__ == "__main__":
    sys.exit(main())
