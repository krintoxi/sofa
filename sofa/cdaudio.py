"""Reading a music CD: its tracks, the names it carries, and the sound itself, exactly as it's on the disc.

A CD's sound is 44 100 samples a second, two channels, 16 bits, in frames of 2352 bytes, 75 to the second. Sofa
reads those frames itself (there's no copy protection on a music CD to speak of, and nothing here would get round
any) and hands them to ffmpeg only to pack as FLAC, which keeps every bit.

Where the frames come from depends on the computer, and each is one small class answering the same questions
(`tracks`, `text()`, `read(frame, count)`):

  Mac       the CD shows up as a folder of .aiff files, one a track (the system's own doing): those are read.
  Linux     the drive is asked (the kernel's CDROMREADTOCENTRY and CDROMREADAUDIO), as on a Sofa Box.
  Windows   the drive is asked (IOCTL_CDROM_READ_TOC and IOCTL_CDROM_RAW_READ).
  an image  a .cue and its .bin, which is how the tests make a CD, and a way to save one from a file.

Names: a disc's own text (CD-Text) where the drive gives it, and otherwise a lookup at MusicBrainz by the disc's
table of contents alone (no key, no account, switched off in Settings), `lookup`.
"""
import base64
import hashlib
import json
import os
import plistlib
import re
import struct
import urllib.parse
import urllib.request

FRAME = 2352
PER_SECOND = 75
LOOKUP = "https://musicbrainz.org/ws/2/discid/"
AGENT = {"User-Agent": "Sofa home media server (https://github.com/krintoxi/sofa)"}


class Disc:
    """What every kind below is: `tracks` = [{"n", "start" (frame), "frames", "audio"}], `leadout` (frame)."""
    tracks, leadout = (), 0

    def text(self):
        """The names the disc itself carries: {"artist", "album", "titles": {n: title}, "artists": {n: artist}}."""
        return {}

    def read(self, frame, count):
        raise NotImplementedError

    def close(self):
        pass

    def seconds(self, track):
        return track["frames"] / float(PER_SECOND)


def _finish(tracks, leadout):
    """Each track's length, from where the next starts."""
    tracks = sorted(tracks, key=lambda t: t["start"])
    for i, t in enumerate(tracks):
        t["frames"] = (tracks[i + 1]["start"] if i + 1 < len(tracks) else leadout) - t["start"]
    return [t for t in tracks if t["frames"] > 0]


# ---------------------------------------------------------------- an image: .cue and .bin

class CueBin(Disc):
    def __init__(self, cue):
        folder = os.path.dirname(os.path.abspath(cue))
        with open(cue, encoding="utf-8", errors="replace") as f:
            lines = [x.strip() for x in f.read().splitlines()]
        self._text = {"titles": {}, "artists": {}}
        tracks, current, binfile = [], None, None
        for line in lines:
            m = re.match(r'^(\w+)\s+(?:"(.*)"|(\S+))(?:\s+(\S+))?', line)
            if not m:
                continue
            word, value, kind = m.group(1).upper(), m.group(2) if m.group(2) is not None else m.group(3), (m.group(4) or "").upper()
            if word == "FILE":
                if binfile is not None or kind not in ("BINARY", "MOTOROLA"):
                    raise ValueError("Sofa reads a CD image that is one .bin file with its .cue.")
                binfile, self.swap = os.path.join(folder, value), kind == "MOTOROLA"
            elif word == "TRACK":
                current = {"n": int(value), "audio": kind == "AUDIO", "start": None}
                tracks.append(current)
            elif word == "INDEX" and current is not None and int(value) == 1:
                mm, ss, ff = (int(x) for x in (m.group(4) or "0:0:0").split(":"))
                current["start"] = (mm * 60 + ss) * PER_SECOND + ff
            elif word == "TITLE":
                if current is None:
                    self._text["album"] = value
                else:
                    self._text["titles"][current["n"]] = value
            elif word == "PERFORMER":
                if current is None:
                    self._text["artist"] = value
                else:
                    self._text["artists"][current["n"]] = value
        if not binfile or not tracks or any(t["start"] is None for t in tracks):
            raise ValueError("That .cue names no tracks Sofa can read.")
        self.f = open(binfile, "rb")
        self.leadout = os.path.getsize(binfile) // FRAME
        self.tracks = _finish(tracks, self.leadout)

    def text(self):
        return self._text

    def read(self, frame, count):
        self.f.seek(frame * FRAME)
        data = self.f.read(count * FRAME)
        if len(data) < count * FRAME:
            raise OSError("The image ends before the track does.")
        if self.swap:
            data = _swap(data)
        return data

    def close(self):
        self.f.close()


def _swap(data):
    out = bytearray(data)
    out[0::2], out[1::2] = data[1::2], data[0::2]
    return bytes(out)


# ---------------------------------------------------------------- a Mac: the CD as a folder of .aiff files

def _aiff(path):
    """Where the sound is in an AIFF file: (offset, bytes, big-endian?). A Mac's CD files are AIFF-C, little-endian
    ("sowt"); plain AIFF is big-endian."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"FORM" or head[8:12] not in (b"AIFF", b"AIFC"):
            raise ValueError("Not an AIFF file: %s" % os.path.basename(path))
        big, at = True, 12
        while True:
            f.seek(at)
            chunk = f.read(8)
            if len(chunk) < 8:
                raise ValueError("No sound in %s" % os.path.basename(path))
            name, size = chunk[:4], struct.unpack(">I", chunk[4:])[0]
            if name == b"COMM" and head[8:12] == b"AIFC":
                big = f.read(22)[18:22] != b"sowt"
            if name == b"SSND":
                offset = struct.unpack(">I", f.read(8)[:4])[0]
                return at + 16 + offset, size - 8 - offset, big
            at += 8 + size + (size & 1)


class MacVolume(Disc):
    def __init__(self, folder):
        self.folder, self.files = folder, {}
        found = []
        for name in os.listdir(folder):
            m = re.match(r"^(\d+) .*\.aiff?$", name, re.I)
            if m:
                found.append((int(m.group(1)), os.path.join(folder, name)))
        if not found:
            raise ValueError("There are no tracks on it.")
        starts, self._absolute = {}, False
        try:
            with open(os.path.join(folder, ".TOC.plist"), "rb") as f:
                toc = plistlib.load(f)
            for s in toc.get("Sessions") or []:
                for t in s.get("Track Array") or []:
                    starts[int(t["Point"])] = int(t["Start Block"])
                self._leadout = int(s.get("Leadout Block") or 0)
            self._absolute = bool(starts) and min(starts.values()) >= 150     # (counted from the disc's very start)
        except (OSError, ValueError, KeyError, TypeError, plistlib.InvalidFileException):
            starts = {}
        at, tracks = 0, []
        for n, path in sorted(found):
            offset, size, big = _aiff(path)
            frames = size // FRAME
            self.files[n] = (path, offset, big, at)
            tracks.append({"n": n, "start": at, "frames": frames, "audio": True})
            at += frames
        self.tracks, self.leadout, self._open = tracks, at, None
        if starts and all(t["n"] in starts for t in tracks):                  # the disc's real addresses, for the lookup
            off = 150 if self._absolute else 0
            self.addresses = ([starts[t["n"]] - off for t in tracks], self._leadout - off)

    def read(self, frame, count):
        for n, (path, offset, big, at) in self.files.items():
            t = next(x for x in self.tracks if x["n"] == n)
            if at <= frame < at + t["frames"]:
                if self._open is None or self._open[0] != path:
                    self.close()
                    self._open = (path, open(path, "rb"))
                f = self._open[1]
                f.seek(offset + (frame - at) * FRAME)
                data = f.read(count * FRAME)
                if len(data) < count * FRAME:
                    raise OSError("The disc stopped answering.")
                return _swap(data) if big else data
        raise OSError("No such place on the disc.")

    def close(self):
        if self._open:
            self._open[1].close()
            self._open = None


# ---------------------------------------------------------------- CD-Text, as a drive hands it over

def cd_text(raw):
    """A disc's CD-Text (the drive's answer to READ TOC, format 5: 18-byte packs after a 4-byte header) as
    {"artist", "album", "titles": {n: title}, "artists": {n: artist}}. Only the first language, and plain 8-bit text."""
    kinds = (0x80, 0x81)                                       # titles, performers
    text = {0x80: {}, 0x81: {}}
    packs = [raw[i:i + 18] for i in range(4, len(raw) - 17, 18)]
    carry = {}
    for p in packs:
        kind, track, block = p[0], p[1] & 0x7F, (p[3] >> 4) & 7
        if kind not in kinds or block != 0 or p[3] & 0x80:      # (16-bit text, and other languages: left)
            continue
        data = carry.get(kind, b"") + p[4:16]
        while b"\x00" in data:
            one, _, data = data.partition(b"\x00")
            value = text[kind].get(track - 1, "") if one == b"\t" else one.decode("latin-1").strip()   # (a tab: "as the one before")
            if value:
                text[kind][track] = value
            track += 1
        carry[kind] = data
    out = {"titles": {n: t for n, t in text[0x80].items() if n > 0}, "artists": {n: t for n, t in text[0x81].items() if n > 0}}
    if text[0x80].get(0):
        out["album"] = text[0x80][0]
    if text[0x81].get(0):
        out["artist"] = text[0x81][0]
    return out


# ---------------------------------------------------------------- Linux: the drive, asked through the kernel

# (the numbers and layouts are the kernel's, include/uapi/linux/cdrom.h and scsi/sg.h)
CDROMREADTOCHDR, CDROMREADTOCENTRY, CDROMREADAUDIO = 0x5305, 0x5306, 0x530E
CDROM_DRIVE_STATUS, CDROM_DISC_STATUS, DVD_READ_STRUCT, SG_IO = 0x5326, 0x5327, 0x5390, 0x2285
CDROM_LBA, CDROM_LEADOUT, CDROM_DATA_TRACK = 0x01, 0xAA, 0x04
CDS_NO_INFO, CDS_NO_DISC, CDS_TRAY_OPEN, CDS_DRIVE_NOT_READY, CDS_DISC_OK = 0, 1, 2, 3, 4
CDS_AUDIO, CDS_MIXED = 100, 105


class LinuxDrive(Disc):
    def __init__(self, dev):
        import fcntl
        self.dev, self._ioctl = dev, fcntl.ioctl
        self.fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)      # (shared, read-only: a player can have it open too)
        try:
            head = bytearray(2)
            self._ioctl(self.fd, CDROMREADTOCHDR, head)
            tracks = []
            for n in list(range(head[0], head[1] + 1)) + [CDROM_LEADOUT]:
                entry = bytearray(struct.pack("BBBxixxxx", n, 0, CDROM_LBA, 0))   # struct cdrom_tocentry
                self._ioctl(self.fd, CDROMREADTOCENTRY, entry)
                control = entry[1] >> 4
                lba = struct.unpack_from("i", entry, 4)[0]
                if n == CDROM_LEADOUT:
                    self.leadout = lba
                else:
                    tracks.append({"n": n, "start": lba, "audio": not control & CDROM_DATA_TRACK})
            self.tracks = [t for t in _finish(tracks, self.leadout) if t["audio"]]
            self.addresses = ([t["start"] for t in tracks], self.leadout)
        except Exception:
            os.close(self.fd)
            raise

    def read(self, frame, count):
        import ctypes

        class ReadAudio(ctypes.Structure):                       # struct cdrom_read_audio
            _fields_ = [("lba", ctypes.c_int), ("format", ctypes.c_ubyte), ("nframes", ctypes.c_int), ("buf", ctypes.c_void_p)]
        out = bytearray()
        while count:
            n = min(count, 25)
            buf = ctypes.create_string_buffer(n * FRAME)
            ask = ReadAudio(frame, CDROM_LBA, n, ctypes.cast(buf, ctypes.c_void_p))
            self._ioctl(self.fd, CDROMREADAUDIO, ask)
            out += buf.raw
            frame += n
            count -= n
        return bytes(out)

    def text(self):
        """CD-Text, by the SCSI command READ TOC/PMA/ATIP with format 5 (a read: the kernel lets it through)."""
        import ctypes

        class SgIo(ctypes.Structure):                            # struct sg_io_hdr
            _fields_ = [("interface_id", ctypes.c_int), ("dxfer_direction", ctypes.c_int), ("cmd_len", ctypes.c_ubyte),
                        ("mx_sb_len", ctypes.c_ubyte), ("iovec_count", ctypes.c_ushort), ("dxfer_len", ctypes.c_uint),
                        ("dxferp", ctypes.c_void_p), ("cmdp", ctypes.c_void_p), ("sbp", ctypes.c_void_p),
                        ("timeout", ctypes.c_uint), ("flags", ctypes.c_uint), ("pack_id", ctypes.c_int),
                        ("usr_ptr", ctypes.c_void_p), ("status", ctypes.c_ubyte), ("masked_status", ctypes.c_ubyte),
                        ("msg_status", ctypes.c_ubyte), ("sb_len_wr", ctypes.c_ubyte), ("host_status", ctypes.c_ushort),
                        ("driver_status", ctypes.c_ushort), ("resid", ctypes.c_int), ("duration", ctypes.c_uint),
                        ("info", ctypes.c_uint)]
        try:
            size = 8192
            data, sense = ctypes.create_string_buffer(size), ctypes.create_string_buffer(32)
            cmd = ctypes.create_string_buffer(bytes([0x43, 0, 5, 0, 0, 0, 0, size >> 8, size & 0xFF, 0]), 10)
            hdr = SgIo(ord("S"), -3, 10, 32, 0, size, ctypes.cast(data, ctypes.c_void_p), ctypes.cast(cmd, ctypes.c_void_p),
                       ctypes.cast(sense, ctypes.c_void_p), 10000)       # (-3: SG_DXFER_FROM_DEV)
            self._ioctl(self.fd, SG_IO, hdr)
            if hdr.status:
                return {}
            got = struct.unpack_from(">H", data.raw, 0)[0] + 2
            return cd_text(data.raw[:min(got, size)])
        except (OSError, ValueError):
            return {}

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


def linux_status(dev):
    """What a Linux drive says is in it: "empty", "open", "audio", "mixed", "data", or None (it won't say)."""
    import fcntl
    try:
        fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        drive = fcntl.ioctl(fd, CDROM_DRIVE_STATUS, 0)
        if drive in (CDS_NO_DISC, CDS_TRAY_OPEN, CDS_DRIVE_NOT_READY):
            return "open" if drive == CDS_TRAY_OPEN else "empty"
        disc = fcntl.ioctl(fd, CDROM_DISC_STATUS, 0)
        if disc == CDS_NO_DISC:
            return "empty"
        return "audio" if disc == CDS_AUDIO else "mixed" if disc == CDS_MIXED else "data"
    except OSError:
        return None
    finally:
        os.close(fd)


def linux_copyright(dev):
    """A DVD's own word on copy protection, read from the disc by the drive (DVD_READ_STRUCT, the copyright
    structure): 0 none, 1 CSS, 2 CPRM; None when the drive won't say. Asking is all this does: Sofa never sends a
    drive the keys or the handshake that unlock a protected disc."""
    import fcntl
    try:
        fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        ask = bytearray(struct.pack("BBBB", 1, 0, 0, 0))         # struct dvd_copyright: type DVD_STRUCT_COPYRIGHT, layer 0
        fcntl.ioctl(fd, DVD_READ_STRUCT, ask)
        return ask[2]
    except OSError:
        return None
    finally:
        os.close(fd)


# ---------------------------------------------------------------- Windows: the drive, asked through DeviceIoControl

def _ctl(base, function, method, access):
    return base << 16 | access << 14 | function << 2 | method


IOCTL_CDROM_READ_TOC = _ctl(2, 0x0000, 0, 1)                     # (ntddcdrm.h)
IOCTL_CDROM_RAW_READ = _ctl(2, 0x000F, 2, 1)
IOCTL_CDROM_READ_TOC_EX = _ctl(2, 0x0015, 0, 1)
IOCTL_DVD_READ_STRUCTURE = _ctl(0x33, 0x0450, 0, 1)              # (ntddcdvd.h)


class WindowsDrive(Disc):
    def __init__(self, letter):
        import ctypes
        from ctypes import wintypes
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.CreateFileW.restype = wintypes.HANDLE
        self.k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.k.CloseHandle.argtypes = [wintypes.HANDLE]
        # GENERIC_READ, shared for reading and writing (nobody is shut out), OPEN_EXISTING
        self.h = self.k.CreateFileW("\\\\.\\%s:" % letter[0], 0x80000000, 3, None, 3, 0, None)
        if self.h in (None, wintypes.HANDLE(-1).value):
            raise OSError("The drive can't be opened.")
        try:
            raw = self._ask(IOCTL_CDROM_READ_TOC, b"", 4 + 100 * 8)
            tracks = []
            for i in range(raw[3] - raw[2] + 2):
                e = raw[4 + i * 8:12 + i * 8]
                lba = (e[5] * 60 + e[6]) * PER_SECOND + e[7] - 150            # (minutes, seconds, frames from the disc's start)
                if e[2] == CDROM_LEADOUT:
                    self.leadout = lba
                else:
                    tracks.append({"n": e[2], "start": lba, "audio": not e[1] & CDROM_DATA_TRACK})
            self.tracks = [t for t in _finish(tracks, self.leadout) if t["audio"]]
            self.addresses = ([t["start"] for t in tracks], self.leadout)
        except Exception:
            self.close()
            raise

    def _ask(self, code, given, size):
        import ctypes
        from ctypes import wintypes
        out, got = ctypes.create_string_buffer(size), wintypes.DWORD(0)
        ok = self.k.DeviceIoControl(self.h, code, given or None, len(given), out, size, ctypes.byref(got), None)
        if not ok:
            raise OSError("The drive didn't answer (error %d)." % ctypes.get_last_error())
        return out.raw[:got.value]

    def read(self, frame, count):
        out = bytearray()
        while count:
            n = min(count, 20)
            ask = struct.pack("<qII", frame * 2048, n, 2)        # RAW_READ_INFO: the place (in 2048s), frames, CDDA
            data = self._ask(IOCTL_CDROM_RAW_READ, ask, n * FRAME)
            if len(data) < n * FRAME:
                raise OSError("The disc stopped answering.")
            out += data
            frame += n
            count -= n
        return bytes(out)

    def text(self):
        try:
            raw = self._ask(IOCTL_CDROM_READ_TOC_EX, bytes([5, 0, 0, 0]), 8192)   # CDROM_READ_TOC_EX: format CD-Text
            return cd_text(raw)
        except OSError:
            return {}

    def close(self):
        try:
            self.k.CloseHandle(self.h)
        except Exception:
            pass


def windows_copyright(letter):
    """As `linux_copyright`, on Windows (IOCTL_DVD_READ_STRUCTURE, DvdCopyrightDescriptor)."""
    try:
        d = WindowsDrive.__new__(WindowsDrive)
        import ctypes
        from ctypes import wintypes
        d.k = ctypes.WinDLL("kernel32", use_last_error=True)
        d.k.CreateFileW.restype = wintypes.HANDLE
        d.k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        d.k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        d.k.CloseHandle.argtypes = [wintypes.HANDLE]
        d.h = d.k.CreateFileW("\\\\.\\%s:" % letter[0], 0x80000000, 3, None, 3, 0, None)
        if d.h in (None, wintypes.HANDLE(-1).value):
            return None
        try:
            raw = d._ask(IOCTL_DVD_READ_STRUCTURE, struct.pack("<qIIB7x", 0, 1, 0, 0), 8)   # DVD_READ_STRUCTURE
            return raw[4] if len(raw) >= 5 else None
        finally:
            d.close()
    except (OSError, AttributeError, ValueError):
        return None


# ---------------------------------------------------------------- names from MusicBrainz

def disc_id(addresses):
    """MusicBrainz's name for a disc, worked out from where its tracks start: (the id, the "toc" to ask with)."""
    starts, leadout = addresses
    offsets = [leadout + 150] + [s + 150 for s in starts]
    text = "%02X%02X" % (1, len(starts)) + "".join("%08X" % (offsets[i] if i < len(offsets) else 0) for i in range(100))
    digest = hashlib.sha1(text.encode("ascii")).digest()
    code = base64.b64encode(digest, b"._").decode("ascii").replace("=", "-")
    return code, "1 %d %s" % (len(starts), " ".join(str(o) for o in offsets))


def _fetch(url):
    from . import net
    with net.urlopen(urllib.request.Request(url, headers=dict(AGENT, Accept="application/json")), timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def lookup(disc, fetch=_fetch):
    """This disc's names from MusicBrainz, or {}. What's sent: where the disc's tracks start, and nothing else."""
    tracks = list(disc.tracks)
    addresses = getattr(disc, "addresses", None) or ([t["start"] for t in tracks], disc.leadout)
    code, toc = disc_id(addresses)
    try:
        data = fetch(LOOKUP + code + "?toc=" + urllib.parse.quote(toc.replace(" ", "+"), safe="+") + "&inc=recordings+artist-credits&fmt=json")
    except Exception:
        return {}
    for release in data.get("releases") or []:
        for medium in release.get("media") or []:
            got = medium.get("tracks") or []
            if len(got) != len(addresses[0]):
                continue
            credit = lambda x: "".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in x.get("artist-credit") or [])
            out = {"album": release.get("title") or "", "artist": credit(release), "titles": {}, "artists": {},
                   "year": (release.get("date") or "")[:4]}
            for i, t in enumerate(got, 1):
                n = int(t.get("position") or i)
                out["titles"][n] = t.get("title") or ""
                if credit(t) and credit(t) != out["artist"]:
                    out["artists"][n] = credit(t)
            return out
    return {}
