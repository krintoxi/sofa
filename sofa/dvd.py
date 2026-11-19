"""Reading a video DVD: what's on it (titles, lengths, chapters, sound and subtitle tracks) and a title's stream.

Sofa's own reader, a few hundred lines, and on purpose not somebody's library. The usual one (libdvdread, which
ffmpeg's and mpv's DVD support are built on) quietly loads libdvdcss when the computer has it and decrypts as it
reads; Sofa saving a disc must never do that on anyone's computer, so nothing here goes near either. It reads what
the DVD-Video format puts in the clear: the .IFO files (the disc's table of contents) and the .VOB files (MPEG
program streams, 2048 bytes a pack).

Copy-protected discs. A commercial DVD's video is scrambled (CSS). Sofa has nothing that descrambles it and isn't
going to: in the United States getting round it is circumvention (17 U.S.C. 1201), even for a copy of your own disc.
Every pack's header says in the clear whether its contents are scrambled, so Sofa can tell, says so, and stops:
`read_title` raises `Protected` at the first scrambled pack, and nothing of that title is kept.

THE ONE PLACE A TITLE'S STREAM IS READ is `read_title(source, title)`: it yields the title's packs, in order, in
the clear, or raises. Everything that saves a title (sofa/disc.py) goes through `dvd.read_title`, so that is the
function to replace to read a title some other way. Sofa ships nothing else to put there.

What it doesn't do: titles filmed from more than one camera angle (their packs are interleaved on the disc), and
menus. A title like that is listed with the reason, and not saved.
"""
import struct

from . import iso9660

SECTOR = 2048
CHUNK = 512                 # packs read at a time (1 MB)
CLOCK = 90000               # a DVD's timestamps: 90 000 to the second
WRAP = 1 << 33
AUDIO_FORMATS = {0: "ac3", 2: "mp2", 3: "mp2", 4: "lpcm", 6: "dts"}
AUDIO_NAMES = {"ac3": "Dolby Digital", "mp2": "MPEG", "lpcm": "PCM", "dts": "DTS"}
AUDIO_BASE = {"ac3": 0x80, "dts": 0x88, "lpcm": 0xA0, "mp2": 0xC0}     # where each kind's tracks sit in the stream
AUDIO_NOTES = {2: "for the visually impaired", 3: "commentary", 4: "commentary 2"}
SUB_NOTES = {2: "large", 3: "for children", 5: "closed captions", 6: "closed captions, large", 7: "closed captions, for children",
             9: "forced", 13: "commentary", 14: "commentary, large", 15: "commentary, for children"}


class NotVideo(ValueError):
    """Not a video DVD Sofa can read (no VIDEO_TS, or its table of contents is damaged)."""


class Protected(Exception):
    """The disc's video is scrambled: copy protection. Sofa stops here."""


def _u16(b, at):
    return struct.unpack_from(">H", b, at)[0]


def _u32(b, at):
    return struct.unpack_from(">I", b, at)[0]


def _bcd(x):
    return (x >> 4) * 10 + (x & 15)


def _time(b, at):
    """A playback time as the disc writes it (hours, minutes, seconds, frames, each two decimal digits; the frames'
    top two bits say 25 or 30 a second), in seconds."""
    h, m, s, f = b[at], b[at + 1], b[at + 2], b[at + 3]
    rate = 25.0 if (f >> 6) == 1 else 30000 / 1001.0
    return _bcd(h) * 3600 + _bcd(m) * 60 + _bcd(s) + _bcd(f & 0x3F) / rate


def _lang(b, at):
    code = b[at:at + 2]
    return code.decode("ascii").lower() if len(code) == 2 and code.isalpha() else None


def _read(source, path):
    with source.open(path) as f:
        return f.read(8 << 20)                          # (a table of contents is a few kB; 8 MB is far past any)


def _ifo(source, name, magic):
    for ext in (".IFO", ".BUP"):                        # (.BUP: the disc's own spare copy, for a scratch on the first)
        try:
            data = _read(source, "VIDEO_TS/" + name + ext)
        except (OSError, ValueError):
            continue
        if data[:12] == magic:
            return data
    raise NotVideo("This disc's table of contents can't be read (VIDEO_TS/%s.IFO)." % name)


def _pgc(b, at):
    """One program chain: its cells (where on the disc, how long, which angle), where each chapter starts, which
    sound and subtitle tracks play, and the subtitles' colours."""
    programs, cells_n = b[at + 2], b[at + 3]
    audio = []
    for i in range(8):
        v = _u16(b, at + 0x0C + i * 2)
        audio.append((v >> 8) & 7 if v & 0x8000 else None)
    subs = []
    for i in range(32):
        v = _u32(b, at + 0x1C + i * 4)
        subs.append(((v >> 24) & 0x1F, (v >> 16) & 0x1F, (v >> 8) & 0x1F, v & 0x1F) if v & 0x80000000 else None)
    palette = [tuple(b[at + 0xA4 + i * 4 + 1:at + 0xA4 + i * 4 + 4]) for i in range(16)]       # (Y, Cr, Cb)
    pmap, cpb = _u16(b, at + 0xE6), _u16(b, at + 0xE8)
    entry = [b[at + pmap + i] for i in range(programs)] if pmap else []
    cells = []
    for i in range(cells_n if cpb else 0):
        c = at + cpb + i * 24
        cells.append({"mode": b[c] >> 6, "type": (b[c] >> 4) & 3, "interleaved": bool(b[c] & 4),
                      "seconds": _time(b, c + 4), "first": _u32(b, c + 8), "last": _u32(b, c + 20)})
    return {"seconds": _time(b, at + 4), "audio": audio, "subs": subs, "palette": palette, "entry": entry, "cells": cells}


def _title_set(source, n):
    """Title set `n` (VTS_nn_0.IFO): its tracks, its program chains, and which of them each of its titles plays."""
    b = _ifo(source, "VTS_%02d_0" % n, b"DVDVIDEO-VTS")
    v0, v1 = b[0x200], b[0x201]
    pal = (v0 >> 4) & 3 == 1
    width = (720, 704, 352, 352)[(v1 >> 2) & 3]
    height = ((576, 576, 576, 288) if pal else (480, 480, 480, 240))[(v1 >> 2) & 3]
    video = {"pal": pal, "wide": (v0 >> 2) & 3 == 3, "width": width, "height": height}
    audio = []
    for i in range(min(_u16(b, 0x202), 8)):
        a = 0x204 + i * 8
        kind = AUDIO_FORMATS.get(b[a] >> 5)
        audio.append({"kind": kind, "lang": _lang(b, a + 2) if (b[a] >> 2) & 3 == 1 else None, "channels": (b[a + 1] & 7) + 1,
                      "bits": (16, 20, 24, 16)[b[a + 1] >> 6], "note": AUDIO_NOTES.get(b[a + 5])})
    subs = []
    for i in range(min(_u16(b, 0x254), 32)):
        s = 0x256 + i * 6
        subs.append({"lang": _lang(b, s + 2) if b[s] & 3 == 1 else None, "note": SUB_NOTES.get(b[s + 5])})
    chains = {}
    at = _u32(b, 0xCC) * SECTOR
    if at and at + 8 <= len(b):
        for i in range(_u16(b, at)):
            off = _u32(b, at + 8 + i * 8 + 4)
            if at + off + 0xEC <= len(b):
                chains[i + 1] = _pgc(b, at + off)
    titles = {}
    at = _u32(b, 0xC8) * SECTOR
    if at and at + 8 <= len(b):
        count, end = _u16(b, at), _u32(b, at + 4) + 1
        offs = [_u32(b, at + 8 + i * 4) for i in range(count)]
        for i, off in enumerate(offs):
            stop = min([o for o in offs if o > off] + [end])
            titles[i + 1] = [(_u16(b, at + p), _u16(b, at + p + 2)) for p in range(off, stop - 3, 4)]   # (chain, program)
    return {"video": video, "audio": audio, "subs": subs, "chains": chains, "titles": titles}


def _track_name(t):
    from . import languages
    words = [languages.name(t["lang"]) if t.get("lang") else ""]
    if t.get("kind"):
        words.append("%s %s" % (AUDIO_NAMES.get(t["kind"], ""), {1: "mono", 2: "stereo", 6: "5.1", 7: "6.1", 8: "7.1"}.get(t["channels"], "")))
    if t.get("note"):
        words.append("(%s)" % t["note"])
    return " ".join(w.strip() for w in words if w.strip())


def titles(source):
    """What's on a video DVD: {"label", "titles": [...]}. Each title: its number, length in seconds, chapters (where
    each starts, in seconds), sound and subtitle tracks, the picture, how big it is on the disc, and, when Sofa can't
    save it, why (`cant`). Private keys (`_cells` and the rest) are what `read_title` reads it by."""
    try:
        names = {n.upper() for n in source.names("VIDEO_TS")}
    except OSError as exc:
        raise NotVideo("The disc can't be read: %s" % (exc.strerror or exc))
    if "VIDEO_TS.IFO" not in names and "VIDEO_TS.BUP" not in names:
        raise NotVideo("There's no video on this disc that a DVD player would play.")
    b = _ifo(source, "VIDEO_TS", b"DVDVIDEO-VMG")
    at = _u32(b, 0xC4) * SECTOR
    if not at or at + 8 > len(b):
        raise NotVideo("This disc's table of contents has no titles.")
    sets, out = {}, []
    for i in range(_u16(b, at)):
        e = at + 8 + i * 12
        if e + 12 > len(b):
            break
        angles, vts, ttn = b[e + 1], b[e + 6], b[e + 7]
        if vts not in sets:
            try:
                sets[vts] = _title_set(source, vts)
            except NotVideo:
                sets[vts] = None
        ts = sets[vts]
        if not ts or ttn not in ts["titles"]:
            continue
        parts = ts["titles"][ttn]
        order = []                                       # the title's program chains, in the order it plays them
        for chain, _ in parts:
            if chain in ts["chains"] and chain not in order:
                order.append(chain)
        if not order:
            continue
        cells, chapters, starts, cant, began = [], [], {}, None, 0.0
        for chain in order:
            pgc = ts["chains"][chain]
            t = began
            for n, c in enumerate(pgc["cells"], 1):
                starts[(chain, n)] = t
                if c["mode"] or c["type"] or c["interleaved"]:
                    cant = "It was filmed from more than one camera angle, which Sofa can't save yet."
                cells.append(c)
                t += c["seconds"]
            began = t
        for chain, program in parts:
            pgc = ts["chains"].get(chain)
            if pgc and 0 < program <= len(pgc["entry"]):
                when = starts.get((chain, pgc["entry"][program - 1]))
                if when is not None and (not chapters or when > chapters[-1] + 0.5):
                    chapters.append(round(when, 3))
        if angles > 1:
            cant = "It was filmed from more than one camera angle, which Sofa can't save yet."
        first = ts["chains"][order[0]]
        audio = []
        for n, a in enumerate(ts["audio"]):
            where = first["audio"][n]
            if where is not None and a["kind"]:
                audio.append(dict(a, id=AUDIO_BASE[a["kind"]] + where, name=_track_name(a)))
        subs, seen = [], set()
        for n, s in enumerate(ts["subs"]):
            where = first["subs"][n]
            if where is None:
                continue
            sid = 0x20 + (where[1] if ts["video"]["wide"] else where[0])     # (a wide picture: the track drawn for it)
            if sid not in seen:
                seen.add(sid)
                subs.append(dict(s, id=sid, name=_track_name(s)))
        size = sum(c["last"] - c["first"] + 1 for c in cells) * SECTOR
        out.append({"n": i + 1, "seconds": round(sum(c["seconds"] for c in cells), 3), "chapters": chapters or [0.0],
                    "audio": audio, "subs": subs, "video": ts["video"], "size": size, "cant": cant,
                    "_set": vts, "_cells": [(c["first"], c["last"], c["seconds"]) for c in cells], "_palette": first["palette"]})
    return {"label": getattr(source, "label", None) or "DVD", "titles": out}


def public(title):
    """A title as the pages are told about it (no private keys)."""
    return {k: v for k, v in title.items() if not k.startswith("_")}


class _Vobs:
    """A title set's video files (VTS_nn_1.VOB, _2, ...), which the disc's addresses count as one run of packs."""

    def __init__(self, source, n):
        self.source, self.parts, self.total, self.open_at = source, [], 0, None
        for i in range(1, 10):
            path = "VIDEO_TS/VTS_%02d_%d.VOB" % (n, i)
            size = source.size(path)
            if not size:
                break
            self.parts.append((self.total, size // SECTOR, path))
            self.total += size // SECTOR

    def read(self, sector, count):
        out = []
        for start, length, path in self.parts:
            if count <= 0:
                break
            if start <= sector < start + length:
                if self.open_at is None or self.open_at[0] != path:
                    self.close()
                    self.open_at = (path, self.source.open(path))
                f = self.open_at[1]
                take = min(count, start + length - sector)
                f.seek((sector - start) * SECTOR)
                data = f.read(take * SECTOR)
                if len(data) < take * SECTOR:
                    raise OSError("The disc stopped answering.")
                out.append(data)
                sector += take
                count -= take
        if count:
            raise OSError("The disc ends before this title does.")
        return b"".join(out)

    def close(self):
        if self.open_at:
            try:
                self.open_at[1].close()
            except OSError:
                pass
            self.open_at = None


def _stamp(b, at):
    """The 33-bit timestamp written in five bytes at `at`."""
    return ((b[at] >> 1) & 7) << 30 | b[at + 1] << 22 | (b[at + 2] >> 1) << 15 | b[at + 3] << 7 | b[at + 4] >> 1


def _set_stamp(b, at, v):
    b[at] = (b[at] & 0xF1) | ((v >> 30) & 7) << 1
    b[at + 1] = (v >> 22) & 0xFF
    b[at + 2] = ((v >> 15) & 0x7F) << 1 | 1
    b[at + 3] = (v >> 7) & 0xFF
    b[at + 4] = (v & 0x7F) << 1 | 1


def packets(pack):
    """The packets in one pack: (stream, sub-stream or None, offset of the packet, offset of its timestamp or None).
    Empty for a pack that isn't an MPEG-2 program stream pack."""
    out = []
    if pack[0:4] != b"\x00\x00\x01\xba" or pack[4] & 0xC0 != 0x40:
        return out
    at = 14 + (pack[13] & 7)
    while at + 6 <= len(pack) and pack[at] == 0 and pack[at + 1] == 0 and pack[at + 2] == 1:
        sid, length = pack[at + 3], pack[at + 4] << 8 | pack[at + 5]
        if sid == 0xBD or 0xC0 <= sid <= 0xEF:
            head = pack[at + 8] if at + 9 <= len(pack) else 0
            pts = at + 9 if at + 14 <= len(pack) and pack[at + 7] & 0x80 else None
            sub = pack[at + 9 + head] if sid == 0xBD and at + 9 + head < len(pack) else None
            out.append((sid, sub, at, pts))
        elif sid == 0xBF:
            out.append((sid, pack[at + 6] if at + 6 < len(pack) else None, at, None))
        elif sid not in (0xBB, 0xBE):
            break
        at += 6 + length
    return out


def _first_picture(data, start):
    """The time on the first picture from `start` on in a run of packs, or None."""
    for i in range(start, len(data), SECTOR):
        pack = data[i:i + SECTOR]
        for sid, _, _, pts in packets(pack):
            if 0xE0 <= sid <= 0xEF and pts is not None:
                return _stamp(pack, pts)
    return None


def scrambled(pack):
    """Does this pack say its contents are scrambled? (Two bits in each packet's header, written in the clear.)"""
    return any(sid != 0xBF and pack[at + 6] & 0x30 for sid, _, at, _ in packets(pack))


def read_title(source, title, seen=None, cancelled=None):
    """A title's stream: its packs, in playing order, as chunks of whole 2048-byte packs in the clear.

    THE SEAM. This is the only reader of a title's video in Sofa, and what saves a title calls it as
    `dvd.read_title`. It reads the title's cells off the disc as they are. A disc whose packs say they're scrambled
    is copy-protected: this raises `Protected` at the first such pack and yields no more. Sofa has no descrambler and
    ships none; whoever swaps this function for another reader answers for what theirs does.

    Timestamps: a disc restarts its clock where it likes between cells (a home-made disc of several clips does at
    every clip). The packs are handed on with one clock running through the whole title, so what's saved plays in
    step and its chapters land where they should. `seen`, when given, collects what was found on the way:
    {"streams": {(stream, sub-stream): packs}, "start": the first picture's time on that clock, "first": the
    earliest time on any picture or sound track, and "subs": the
    subtitle packs since the caller last emptied it, as (track, time or None for one that carries on, the pack).
    """
    vobs = _Vobs(source, title["_set"])
    shift, last_end, begun, played, started, firsts = 0, None, None, 0.0, set(), set()
    streams = seen.setdefault("streams", {}) if seen is not None else {}
    try:
        for first, last, seconds in title["_cells"]:
            fresh, at = True, first
            while at <= last:
                if cancelled and cancelled():
                    return
                count = min(CHUNK, last - at + 1)
                data = bytearray(vobs.read(at, count))
                for i in range(0, len(data), SECTOR):
                    pack = memoryview(data)[i:i + SECTOR]
                    found = packets(pack)
                    if not found:
                        continue
                    nav = None
                    for sid, sub, p, pts in found:
                        if sid == 0xBF:
                            if sub == 0 and p + 27 <= SECTOR:               # the navigation pack: when this stretch starts and ends
                                nav = (_u32(pack, p + 19), _u32(pack, p + 23))
                            continue
                        if pack[p + 6] & 0x30:
                            raise Protected()
                    if fresh:                                              # a new cell: does the disc's clock carry on?
                        fresh = False
                        if nav and nav[1] > nav[0]:
                            if last_end is not None:
                                shift = (last_end - nav[0]) % WRAP
                        else:                    # no times in the navigation packs: by the picture's own first time
                            shows = _first_picture(data, i)
                            if shows is not None and begun is None:
                                begun = shows
                            elif shows is not None:
                                due = (begun + int(played * CLOCK)) % WRAP
                                if abs((shows + shift - due + WRAP // 2) % WRAP - WRAP // 2) > CLOCK // 4:
                                    shift = (due - shows) % WRAP
                    if nav and nav[1] > nav[0]:
                        last_end = (nav[1] + shift) % WRAP
                    for sid, sub, p, pts in found:
                        if sid == 0xBF:
                            continue
                        key = (sid, sub if sid == 0xBD else None)
                        streams[key] = streams.get(key, 0) + 1
                        if pts is None:
                            continue
                        when = (_stamp(pack, pts) + shift) % WRAP
                        if shift:
                            _set_stamp(pack, pts, when)
                            if pack[p + 7] & 0x40 and pts + 10 <= SECTOR:   # (a decoding time after the showing time)
                                _set_stamp(pack, pts + 5, (_stamp(pack, pts + 5) + shift) % WRAP)
                        if seen is not None:
                            if key not in firsts and (sid != 0xBD or (sub is not None and sub >= 0x80)):
                                firsts.add(key)                             # the earliest time on any picture or sound
                                if "first" not in seen or (when - seen["first"] + WRAP // 2) % WRAP < WRAP // 2:
                                    seen["first"] = when
                            if 0xE0 <= sid <= 0xEF and "start" not in seen:
                                seen["start"] = when
                            if sid == 0xBD and sub is not None and 0x20 <= sub <= 0x3F:
                                started.add(sub)
                                seen.setdefault("subs", []).append((sub, when, bytes(pack)))
                    if seen is not None and started:                        # a subtitle that runs on into this pack
                        for sid, sub, p, pts in found:
                            if sid == 0xBD and pts is None and sub in started:
                                seen.setdefault("subs", []).append((sub, None, bytes(pack)))
                yield data
                at += count
            played += seconds
    finally:
        vobs.close()


def sample(source, title, spots=6, packs=48):
    """A quick look at a title before anyone waits for it: packs from a few places along it. "protected" when one
    says it's scrambled, "unreadable" when the drive won't hand them over (which a drive does for a protected disc it
    hasn't been unlocked for, and Sofa never unlocks one), else None."""
    vobs = _Vobs(source, title["_set"])
    cells = title["_cells"]
    total = sum(b - a + 1 for a, b, _ in cells)
    try:
        for k in range(spots):
            want, at = total * k // spots, None
            for a, b, _ in cells:
                if want < b - a + 1:
                    at = a + want
                    count = min(packs, b - at + 1)
                    break
                want -= b - a + 1
            if at is None:
                continue
            try:
                data = vobs.read(at, count)
            except OSError:
                return "unreadable"
            for i in range(0, len(data), SECTOR):
                if scrambled(data[i:i + SECTOR]):
                    return "protected"
    finally:
        vobs.close()
    return None


def rgb(palette):
    """The subtitles' sixteen colours as the disc gives them (Y, Cr, Cb), as "rrggbb"."""
    out = []
    for y, cr, cb in palette:
        r = 1.164 * (y - 16) + 1.596 * (cr - 128)
        g = 1.164 * (y - 16) - 0.813 * (cr - 128) - 0.391 * (cb - 128)
        b = 1.164 * (y - 16) + 2.018 * (cb - 128)
        out.append("%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in (r, g, b)))
    return out


def open_source(path):
    """A disc's files from a folder (a mounted disc, or a folder holding VIDEO_TS) or from a drive or image."""
    import os
    return iso9660.Folder(path) if os.path.isdir(path) else iso9660.Image(path)
