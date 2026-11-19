"""Reading a disc's files: from the folder the computer mounted it at, or straight from the drive or an image.

A DVD or data disc is an ISO 9660 filesystem (DVD-Video is always a "bridge" disc: UDF and ISO 9660 side by side, the
same files in both). A Mac and Windows mount a disc by themselves, and so does a Sofa Box for a data disc: there the
files are simply read (`Folder`). Where nothing mounted it (a video DVD on a Sofa Box, an image file), `Image` reads
the ISO 9660 side itself: the volume descriptor, the folders, each file's place on the disc. Reading only: nothing
here opens a drive to write, locks its tray, or keeps anyone else from reading it.

Both answer the same questions (`names`, `size`, `open`), so what reads a DVD or copies a data disc doesn't care which.
"""
import os
import struct

SECTOR = 2048


class Folder:
    """A disc the computer mounted (or any folder laid out like one)."""

    def __init__(self, root, label=None):
        self.root = root
        self.label = label or os.path.basename(root.rstrip("/\\")) or "Disc"

    def _path(self, path):
        """The real path of `path` whatever its capitals (a disc's names are capitals; a mount may show them lower)."""
        at = self.root
        for part in [p for p in path.replace("\\", "/").split("/") if p]:
            hit = os.path.join(at, part)
            if not os.path.lexists(hit):
                try:
                    same = [n for n in os.listdir(at) if n.lower() == part.lower()]
                except OSError:
                    same = []
                if not same:
                    return None
                hit = os.path.join(at, same[0])
            at = hit
        return at

    def names(self, path=""):
        """What's in a folder: {name: (is a folder, size)}."""
        at = self._path(path)
        out = {}
        if at is None:
            return out
        with os.scandir(at) as it:
            for e in it:
                try:
                    out[e.name] = (e.is_dir(), 0 if e.is_dir() else e.stat().st_size)
                except OSError:
                    continue
        return out

    def size(self, path):
        at = self._path(path)
        return os.path.getsize(at) if at and os.path.isfile(at) else None

    def open(self, path):
        at = self._path(path)
        if at is None:
            raise FileNotFoundError(path)
        return open(at, "rb")

    def close(self):
        pass


class _Extents:
    """A file on the disc: one or more runs of bytes of the image, read as one."""

    def __init__(self, image, runs):
        self.image, self.runs, self.pos = image, runs, 0    # runs: [(offset in the image, length)]
        self.length = sum(n for _, n in runs)

    def seek(self, pos, whence=0):
        self.pos = pos if whence == 0 else self.pos + pos if whence == 1 else self.length + pos
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.length - self.pos
        out, at = [], 0
        for start, length in self.runs:
            if n <= 0:
                break
            if self.pos < at + length:
                skip = self.pos - at
                take = min(n, length - skip)
                got = self.image.pread(start + skip, take)
                out.append(got)
                self.pos += len(got)
                n -= len(got)
                if len(got) < take:
                    break
            at += length
        return b"".join(out)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Image:
    """The ISO 9660 filesystem of a drive (/dev/sr0, \\\\.\\D:) or an image file, read here."""

    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb", buffering=0)               # (read-only, and shared: playback can read it meanwhile)
        self._dirs = {}
        root = label = None
        joliet = None
        for n in range(16, 48):                              # the volume descriptors, from sector 16
            d = self._sector(n)
            if len(d) < SECTOR or d[1:6] != b"CD001":
                break
            if d[0] == 255:
                break
            if d[0] == 1 and root is None:
                root = d[156:190]
                label = d[40:72].decode("ascii", "replace").strip()
            if d[0] == 2 and d[88:91] in (b"%/@", b"%/C", b"%/E"):   # Joliet: the long names, in UCS-2
                joliet = d[156:190]
        if root is None:
            self.f.close()
            raise ValueError("There's no ISO 9660 filesystem on it.")
        self.label = label or "Disc"
        self.wide = joliet is not None
        self._root = self._record(joliet or root)

    def _sector(self, n, count=1):
        self.f.seek(n * SECTOR)
        want, got = count * SECTOR, b""
        while len(got) < want:                               # (a raw device may hand back less than asked)
            more = self.f.read(want - len(got))
            if not more:
                break
            got += more
        return got

    def pread(self, offset, n):
        """`n` bytes at `offset`, asked of the drive in whole sectors (a drive read raw takes nothing else)."""
        first = offset // SECTOR
        data = self._sector(first, (offset + n + SECTOR - 1) // SECTOR - first)
        return data[offset - first * SECTOR:offset - first * SECTOR + n]

    def _record(self, r):
        return {"lba": struct.unpack_from("<I", r, 2)[0], "size": struct.unpack_from("<I", r, 10)[0], "flags": r[25]}

    def _read_dir(self, rec):
        key = rec["lba"]
        if key in self._dirs:
            return self._dirs[key]
        data = self._sector(rec["lba"], (min(rec["size"], 64 << 20) + SECTOR - 1) // SECTOR)
        out, at = {}, 0
        while at < len(data):
            n = data[at]
            if n == 0:                                       # (a record never crosses a sector: on to the next one)
                at = (at // SECTOR + 1) * SECTOR
                continue
            r = data[at:at + n]
            at += n
            if len(r) < 34:
                break
            raw = r[33:33 + r[32]]
            if raw in (b"\x00", b"\x01"):                    # this folder, and its parent
                continue
            name = raw.decode("utf-16-be", "replace") if self.wide else raw.decode("ascii", "replace")
            name = name.split(";")[0].rstrip(".") if not (r[25] & 2) else name
            e = self._record(r)
            have = out.get(name)
            if have and not (r[25] & 2):                     # a file in several pieces (over 4 GB): the next piece
                have["runs"].append((e["lba"] * SECTOR, e["size"]))
                have["size"] += e["size"]
            else:
                e["runs"] = [(e["lba"] * SECTOR, e["size"])]
                out[name] = e
        self._dirs[key] = out
        return out

    def _find(self, path):
        rec = self._root
        for part in [p for p in path.replace("\\", "/").split("/") if p]:
            if not rec["flags"] & 2:
                return None
            entries = self._read_dir(rec)
            rec = entries.get(part) or next((e for n, e in entries.items() if n.lower() == part.lower()), None)
            if rec is None:
                return None
        return rec

    def names(self, path=""):
        rec = self._find(path)
        if rec is None or not rec["flags"] & 2:
            return {}
        return {n: (bool(e["flags"] & 2), 0 if e["flags"] & 2 else e["size"]) for n, e in self._read_dir(rec).items()}

    def size(self, path):
        rec = self._find(path)
        return rec["size"] if rec and not rec["flags"] & 2 else None

    def open(self, path):
        rec = self._find(path)
        if rec is None or rec["flags"] & 2:
            raise FileNotFoundError(path)
        return _Extents(self, rec["runs"])

    def close(self):
        try:
            self.f.close()
        except OSError:
            pass


def walk(source, top=""):
    """Every file on a disc, as (path, size), folders first to last."""
    try:
        entries = sorted(source.names(top).items())
    except OSError:
        return
    for name, (is_dir, size) in entries:
        path = (top + "/" + name) if top else name
        if is_dir:
            yield from walk(source, path)
        else:
            yield path, size
