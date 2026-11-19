"""Discs made for the tests: an ISO 9660 image, a video DVD (its .IFO tables written here, its video from ffmpeg),
and a music CD's image (.cue and .bin). Nothing here is Sofa's own reader, so the two can't agree by accident on
anything but the formats themselves (and tests/test_disc.py reads a disc made by dvdauthor too, when it's there)."""
import math
import os
import struct
import subprocess

SECTOR = 2048


# ---------------------------------------------------------------- an ISO 9660 image

def _both32(n):
    return struct.pack("<I", n) + struct.pack(">I", n)


def _both16(n):
    return struct.pack("<H", n) + struct.pack(">H", n)


def _record(name, lba, size, is_dir):
    name = name if isinstance(name, bytes) else name.encode("ascii")
    r = bytes([0]) + _both32(lba) + _both32(size) + bytes([126, 1, 1, 0, 0, 0, 0]) + bytes([2 if is_dir else 0, 0, 0]) + \
        _both16(1) + bytes([len(name)]) + name
    r += b"\x00" * ((len(r) + 1) % 2)
    return bytes([len(r) + 1]) + r


def iso(path, files, label="SOFA_TEST"):
    """Write an ISO 9660 image: `files` is {"VIDEO_TS/VIDEO_TS.IFO": bytes, ...} (bytes, or a path to read)."""
    tree = {"": {}}
    for name in sorted(files):
        parts = name.split("/")
        for i in range(1, len(parts)):
            tree.setdefault("/".join(parts[:i]), {})
            tree["/".join(parts[:i - 1])][parts[i - 1]] = None
        tree["/".join(parts[:-1])][parts[-1]] = name
    dirs = sorted(tree, key=lambda d: (d.count("/") + (1 if d else 0), d))
    size_of = lambda name: os.path.getsize(files[name]) if isinstance(files[name], str) else len(files[name])
    at = 20                                             # 16 PVD, 17 end, 18 and 19 the path tables
    dir_lba = {}
    for d in dirs:
        dir_lba[d] = at
        at += 1
    file_lba = {}
    for name in sorted(files):
        file_lba[name] = at
        at += (size_of(name) + SECTOR - 1) // SECTOR or 1
    total = at
    with open(path, "wb") as f:
        f.write(b"\x00" * 16 * SECTOR)
        root = _record(b"\x00", dir_lba[""], SECTOR, True)
        table_l = table_m = b""
        for n, d in enumerate(dirs):
            name = d.split("/")[-1].encode("ascii") or b"\x00"
            parent = dirs.index("/".join(d.split("/")[:-1])) + 1 if d else 1
            pad = b"\x00" * (len(name) % 2)
            table_l += bytes([len(name), 0]) + struct.pack("<IH", dir_lba[d], parent) + name + pad
            table_m += bytes([len(name), 0]) + struct.pack(">IH", dir_lba[d], parent) + name + pad
        pvd = b"\x01CD001\x01\x00" + b" " * 32 + label.encode("ascii").ljust(32) + b"\x00" * 8 + _both32(total) + b"\x00" * 32 + \
            _both16(1) + _both16(1) + _both16(SECTOR) + _both32(len(table_l)) + struct.pack("<II", 18, 0) + struct.pack(">II", 19, 0) + \
            root + b" " * (128 * 4 + 37 * 3) + b"0" * 16 + b"\x00" + b"0" * 16 + b"\x00" + b"0" * 16 + b"\x00" + b"0" * 16 + b"\x00" + b"\x01\x00"
        f.write(pvd.ljust(SECTOR, b"\x00"))
        f.write((b"\xffCD001\x01").ljust(SECTOR, b"\x00"))
        f.write(table_l.ljust(SECTOR, b"\x00"))
        f.write(table_m.ljust(SECTOR, b"\x00"))
        for d in dirs:
            parent = "/".join(d.split("/")[:-1])
            body = _record(b"\x00", dir_lba[d], SECTOR, True) + _record(b"\x01", dir_lba[parent if d else ""], SECTOR, True)
            for name, full in sorted(tree[d].items()):
                if full is None:
                    body += _record(name, dir_lba[(d + "/" + name) if d else name], SECTOR, True)
                else:
                    body += _record(name + ";1", file_lba[full], size_of(full), False)
            assert len(body) <= SECTOR, "too many files in one folder for this little writer"
            f.write(body.ljust(SECTOR, b"\x00"))
        for name in sorted(files):
            data = files[name]
            if isinstance(data, str):
                with open(data, "rb") as g:
                    data = g.read()
            f.write(data)
            f.write(b"\x00" * (-len(data) % SECTOR if data else SECTOR))
    return path


# ---------------------------------------------------------------- a video DVD

def ffmpeg():
    from sofa import media
    return media.tool("ffmpeg")


SOUND = {"ac3": ["ac3", "-b:a", "128k"], "lpcm": ["pcm_s16be"], "mp2": ["mp2", "-b:a", "128k"]}


def clip(path, seconds=4, sounds=("ac3", "ac3"), pal=False, freq=440):
    """A DVD's video file from ffmpeg: MPEG-2 video and a sound track of each kind in `sounds` (Dolby Digital, PCM
    or MPEG, as recorders and cameras write them), in 2048-byte packs."""
    size, rate = ("720x576", "25") if pal else ("720x480", "30000/1001")
    cmd = [ffmpeg(), "-v", "fatal", "-y", "-f", "lavfi", "-i", "testsrc=size=%s:rate=%s:duration=%s" % (size, rate, seconds)]
    for i in range(len(sounds)):
        cmd += ["-f", "lavfi", "-i", "sine=frequency=%d:sample_rate=48000:duration=%s" % (freq * (i + 1), seconds)]
    cmd += ["-map", "0:v"] + [x for i in range(len(sounds)) for x in ("-map", "%d:a" % (i + 1))]
    cmd += ["-c:v", "mpeg2video", "-b:v", "1500k", "-g", "15", "-aspect", "4:3", "-ac", "2"]
    for i, kind in enumerate(sounds):
        cmd += ["-c:a:%d" % i, SOUND[kind][0]] + [x.replace("-b:a", "-b:a:%d" % i) for x in SOUND[kind][1:]]
    cmd += ["-f", "dvd", path]
    subprocess.run(cmd, check=True, timeout=180)
    with open(path, "rb") as f:
        data = f.read()
    assert len(data) % SECTOR == 0 and data[:4] == b"\x00\x00\x01\xba"
    return data


def _stamp(prefix, v):
    return bytes([prefix << 4 | ((v >> 30) & 7) << 1 | 1, (v >> 22) & 0xFF, ((v >> 15) & 0x7F) << 1 | 1, (v >> 7) & 0xFF, (v & 0x7F) << 1 | 1])


def _pack_head(scr):
    v = (1 << 46) | ((scr >> 30) & 7) << 43 | 1 << 42 | ((scr >> 15) & 0x7FFF) << 27 | 1 << 26 | (scr & 0x7FFF) << 11 | 1 << 10 | 1
    return b"\x00\x00\x01\xba" + v.to_bytes(6, "big") + b"\x01\x89\xc3\xf8"


def subtitle_pack(track, pts, shown=2.0):
    """One whole subtitle (a small box, 16 by 4) as a pack of sub-stream 0x20 + `track`, shown at `pts` for `shown` s."""
    line = b"\x00\x01"                                    # (one run to the end of the line, in colour 1)
    rle = line * 2 + line * 2                             # the top field's two lines, then the bottom field's
    ctrl_at = 4 + len(rle)
    seq2 = ctrl_at + 24
    ctrl = struct.pack(">HH", 0, seq2) + b"\x01" + b"\x03\x32\x10" + b"\x04\xff\xf0" + \
        b"\x05" + bytes([0x06, 0x40, 0x73, 0x06, 0x40, 0x67]) + b"\x06" + struct.pack(">HH", 4, 4 + len(line) * 2) + b"\xff"
    assert len(ctrl) == 24
    ctrl += struct.pack(">HH", int(shown * 90000 / 1024), seq2) + b"\x02\xff"
    spu = struct.pack(">HH", 4 + len(rle) + len(ctrl), ctrl_at) + rle + ctrl
    payload = bytes([0x20 + track]) + spu
    pes = b"\x00\x00\x01\xbd" + struct.pack(">H", 3 + 5 + len(payload)) + b"\x81\x80\x05" + _stamp(2, pts) + payload
    pack = _pack_head(pts) + pes
    pad = SECTOR - len(pack) - 6
    return pack + b"\x00\x00\x01\xbe" + struct.pack(">H", pad) + b"\xff" * pad


def with_subtitles(vob, tracks=1, every=1.0, first=0.6):
    """`vob` with a subtitle on each of `tracks` every `every` seconds, each put in before the pack it's shown with."""
    from sofa import dvd
    out, due = bytearray(), first
    for i in range(0, len(vob), SECTOR):
        pack = vob[i:i + SECTOR]
        for sid, sub, at, pts in dvd.packets(pack):
            if 0xE0 <= sid <= 0xEF and pts is not None and dvd._stamp(pack, pts) / 90000.0 >= due:
                for t in range(tracks):
                    out += subtitle_pack(t, int(due * 90000))
                due += every
        out += pack
    return bytes(out)


def scramble_flag(vob, every=3):
    """`vob` with every few video packs marked scrambled, as a protected disc's are (the flag only: these packs' contents
    are untouched, there's no CSS here to undo)."""
    from sofa import dvd
    out, n = bytearray(vob), 0
    for i in range(0, len(out), SECTOR):
        for sid, sub, at, pts in dvd.packets(out[i:i + SECTOR]):
            if 0xE0 <= sid <= 0xEF:
                n += 1
                if n % every == 0:
                    out[i + at + 6] |= 0x10
    return bytes(out)


def with_navigation(vob):
    """`vob` with each navigation pack saying when its stretch starts and ends (ffmpeg leaves those empty)."""
    from sofa import dvd
    out, navs, first_pts = bytearray(vob), [], {}
    for i in range(0, len(out), SECTOR):
        pack = out[i:i + SECTOR]
        for sid, sub, at, pts in dvd.packets(pack):
            if sid == 0xBF and sub == 0:
                navs.append(i + at)
            elif 0xE0 <= sid <= 0xEF and pts is not None and navs and navs[-1] not in first_pts:
                first_pts[navs[-1]] = dvd._stamp(pack, pts)
    times = [first_pts.get(n) for n in navs]
    for k, n in enumerate(navs):
        if times[k] is None:
            continue
        later = [t for t in times[k + 1:] if t is not None]
        end = later[0] if later else times[k] + 45000
        struct.pack_into(">II", out, n + 19, times[k], end)
    return bytes(out)


def _bcd_time(seconds, pal=False):
    rate = 25 if pal else 30
    whole = int(seconds)
    frames = min(rate - 1, int(round((seconds - whole) * rate)))
    b = lambda n: (n // 10) << 4 | n % 10
    return bytes([b(whole // 3600), b(whole // 60 % 60), b(whole % 60), (1 if pal else 3) << 6 | b(frames)])


def _pgc(cells, programs, sounds, subs, pal, palette):                 # sounds: each track's kind
    """cells: [(first sector, last sector, seconds, angle block mode)], programs: [first cell of each chapter]."""
    head = bytearray(0xEC)
    head[2], head[3] = len(programs), len(cells)
    head[4:8] = _bcd_time(sum(c[2] for c in cells), pal)
    for i, kind in enumerate(sounds):                                  # (a track's number counts among its own kind)
        struct.pack_into(">H", head, 0x0C + i * 2, 0x8000 | list(sounds[:i]).count(kind) << 8)
    for i in range(subs):
        struct.pack_into(">I", head, 0x1C + i * 4, 0x80000000 | i << 24 | i << 16 | i << 8 | i)
    for i, (y, cr, cb) in enumerate(palette):
        head[0xA4 + i * 4:0xA8 + i * 4] = bytes([0, y, cr, cb])
    pmap = bytes(programs) + b"\x00" * (len(programs) % 2)
    cpb = b"".join(bytes([mode << 6 | (1 << 4 if mode else 0), 0, 0, 0]) + _bcd_time(sec, pal) + struct.pack(">IIII", a, 0, b, b) for a, b, sec, mode in cells)
    pos = b"".join(struct.pack(">HBB", 1, 0, i + 1) for i in range(len(cells)))
    struct.pack_into(">HHH", head, 0xE6, 0xEC, 0xEC + len(pmap), 0xEC + len(pmap) + len(cpb))
    return bytes(head) + pmap + cpb + pos


PALETTE = [(16, 128, 128), (235, 128, 128), (81, 240, 90), (145, 34, 54)] + [(16, 128, 128)] * 12   # black, white, red, green


def title_set(titles, pal=False, wide=False, sounds=(("en", "ac3"), ("es", "ac3")), subs=("en",)):
    """A title set's table (VTS_nn_0.IFO). titles: [{"cells": [(first, last, seconds)], "chapters": [cell numbers]}]."""
    b = bytearray(4 * SECTOR)
    b[0:12] = b"DVDVIDEO-VTS"
    b[0x200] = 0x40 | (0x10 if pal else 0) | (0x0C if wide else 0)
    struct.pack_into(">H", b, 0x202, len(sounds))
    for i, (lang, kind) in enumerate(sounds):
        code = {"ac3": 0, "mp2": 2, "lpcm": 4, "dts": 6}[kind]
        b[0x204 + i * 8:0x20C + i * 8] = bytes([code << 5 | (4 if lang else 0), 0x01]) + (lang or "\x00\x00").encode() + bytes([0, 3 if i == 2 else 1, 0, 0])
    struct.pack_into(">H", b, 0x254, len(subs))
    for i, lang in enumerate(subs):
        b[0x256 + i * 6:0x25C + i * 6] = bytes([1 if lang else 0, 0]) + (lang or "\x00\x00").encode() + bytes([0, 1])
    struct.pack_into(">II", b, 0xC8, 1, 2)                 # the titles' chapters in sector 1, the program chains in 2
    ptt = bytearray(struct.pack(">HHI", len(titles), 0, 0))
    lists = b""
    for n, t in enumerate(titles):
        ptt += struct.pack(">I", 8 + 4 * len(titles) + len(lists))
        lists += b"".join(struct.pack(">HH", n + 1, p + 1) for p in range(len(t["chapters"])))
    ptt += lists
    struct.pack_into(">I", ptt, 4, len(ptt) - 1)
    b[SECTOR:SECTOR + len(ptt)] = ptt
    table = bytearray(struct.pack(">HHI", len(titles), 0, 0))
    chains = b""
    for n, t in enumerate(titles):
        table += struct.pack(">BBHI", 0x80 | (n + 1), 0, 0, 8 + 8 * len(titles) + len(chains))
        chains += _pgc([(c[0], c[1], c[2], c[3] if len(c) > 3 else 0) for c in t["cells"]], t["chapters"], [kind for _, kind in sounds], len(subs), pal, PALETTE)
    table += chains
    struct.pack_into(">I", table, 4, len(table) - 1)
    b[2 * SECTOR:2 * SECTOR + len(table)] = table
    return bytes(b)


def manager(titles):
    """The disc's own table (VIDEO_TS.IFO). titles: [(title set, title within it, chapters, angles)]."""
    b = bytearray(2 * SECTOR)
    b[0:12] = b"DVDVIDEO-VMG"
    struct.pack_into(">I", b, 0xC4, 1)
    t = bytearray(struct.pack(">HHI", len(titles), 0, 8 + 12 * len(titles) - 1))
    for vts, ttn, chapters, angles in titles:
        t += struct.pack(">BBHHBBI", 0x3C, angles, chapters, 0, vts, ttn, 0)
    b[SECTOR:SECTOR + len(t)] = t
    return bytes(b)


def dvd(path, work, clips=((4,), (2, 2)), protected=False, subtitles=True, navigation=False, angles=False, folder=False, pal=False, label="HOME_MOVIES",
        sounds=(("en", "ac3"), ("es", "ac3"))):
    """A video DVD's image at `path` (or, with `folder`, a folder laid out like the disc), in one title set.
    `clips`: for each title, the seconds of each of its clips: every clip is made on its own, so its clock starts
    again, as on a home-made disc of several recordings. Returns the titles as they were made."""
    vobs, titles, at = b"", [], 0
    for n, lengths in enumerate(clips):
        cells = []
        for k, seconds in enumerate(lengths):
            data = clip(os.path.join(work, "clip-%d-%d.vob" % (n, k)), seconds, sounds=[kind for _, kind in sounds], pal=pal, freq=440 + 110 * n)
            if subtitles:
                data = with_subtitles(data)
            if navigation:
                data = with_navigation(data)
            if protected:
                data = scramble_flag(data)
            cells.append((at, at + len(data) // SECTOR - 1, float(seconds)) + ((1 + min(k, 2),) if angles and len(lengths) > 1 else ()))
            at += len(data) // SECTOR
            vobs += data
        titles.append({"cells": cells, "chapters": [i + 1 for i in range(len(cells))]})
    files = {"VIDEO_TS/VIDEO_TS.IFO": manager([(1, n + 1, len(t["chapters"]), 2 if angles and len(t["cells"]) > 1 else 1) for n, t in enumerate(titles)]),
             "VIDEO_TS/VTS_01_0.IFO": title_set(titles, pal=pal, sounds=sounds, subs=("en",) if subtitles else ()), "VIDEO_TS/VTS_01_1.VOB": vobs}
    files["VIDEO_TS/VIDEO_TS.BUP"], files["VIDEO_TS/VTS_01_0.BUP"] = files["VIDEO_TS/VIDEO_TS.IFO"], files["VIDEO_TS/VTS_01_0.IFO"]
    if folder:
        os.makedirs(os.path.join(path, "VIDEO_TS"), exist_ok=True)
        for name, data in files.items():
            with open(os.path.join(path, name), "wb") as f:
                f.write(data)
    else:
        iso(path, files, label=label)
    return titles


# ---------------------------------------------------------------- a music CD

def tone(seconds, freq):
    """CD sound (44 100 samples a second, two channels, 16 bits), a whole number of the disc's 2352-byte frames."""
    frames = int(seconds * 75)
    n = frames * 588
    out = bytearray()
    for i in range(n):
        v = int(12000 * math.sin(2 * math.pi * freq * i / 44100.0))
        out += struct.pack("<hh", v, -v // 2)
    return bytes(out)


def audio_cd(folder, tracks=((2, "First Light"), (3, "Second Wind"), (1.5, "Third Rail")), artist="The Made Ups", album="Made For Testing",
             text=True, name="disc"):
    """A music CD's image: `name`.bin (the tracks' sound, end to end) and `name`.cue (where each starts, and, with
    `text`, the names the disc carries). Returns (the .cue's path, each track's sound)."""
    sounds, at, cue = [], 0, ['FILE "%s.bin" BINARY' % name]
    if text:
        cue = ['PERFORMER "%s"' % artist, 'TITLE "%s"' % album] + cue
    for n, (seconds, title) in enumerate(tracks, 1):
        pcm = tone(seconds, 220 * n)
        cue.append("  TRACK %02d AUDIO" % n)
        if text:
            cue += ['    TITLE "%s"' % title, '    PERFORMER "%s"' % artist]
        cue.append("    INDEX 01 %02d:%02d:%02d" % (at // 75 // 60, at // 75 % 60, at % 75))
        at += len(pcm) // 2352
        sounds.append(pcm)
    with open(os.path.join(folder, name + ".bin"), "wb") as f:
        f.write(b"".join(sounds))
    with open(os.path.join(folder, name + ".cue"), "w", encoding="utf-8") as f:
        f.write("\n".join(cue) + "\n")
    return os.path.join(folder, name + ".cue"), sounds
