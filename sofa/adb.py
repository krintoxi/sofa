"""Putting Sofa's app on a Fire TV from the Sofa computer, over the home network.

This is a small client for ADB, the Android Debug Bridge: the same protocol Android Studio and the
`adb` tool use, which a Fire TV answers on port 5555 once "ADB debugging" is on (Settings → My Fire TV
→ Developer options). Standard library only, so the Sofa computer needs no Android tools.

The first time, the Fire TV asks on screen whether to allow this computer ("Allow USB debugging?");
with "Always allow from this computer" ticked it doesn't ask again. Sofa's key for that lives in
data/adb/ (like adb's own ~/.android/adbkey) and never leaves the Sofa computer.

The protocol: https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/protocol.txt
(messages), SYNC.TXT (copying files), and adb's auth.cpp (an RSA key, signed tokens).
"""
import base64
import json
import os
import random
import socket
import struct
import time

from . import config

PORT = 5555
CNXN, AUTH, OPEN, OKAY, CLSE, WRTE = 0x4E584E43, 0x48545541, 0x4E45504F, 0x59414B4F, 0x45534C43, 0x45545257
VERSION = 0x01000000                  # the oldest version: every Fire TV speaks it (we send checksums)
MAXDATA = 256 * 1024
AUTH_TOKEN, AUTH_SIGNATURE, AUTH_RSAPUBLICKEY = 1, 2, 3
SHA1_DIGESTINFO = bytes.fromhex("3021300906052b0e03021a05000414")
KEY_FILE = os.path.join(config.DATA_DIR, "adb", "sofa-adbkey.json")
_rng = random.SystemRandom()


class AdbError(Exception):
    pass


class NotAllowed(AdbError):
    """The Fire TV said no, or nobody answered its question."""


# ---------------------------------------------------------------- the key (RSA, 2048 bits)

_SMALL_PRIMES = [p for p in range(3, 2000) if all(p % d for d in range(2, int(p ** 0.5) + 1))]


def _probable_prime(n, rounds=24):
    d, s = n - 1, 0
    while not d & 1:
        d >>= 1
        s += 1
    for _ in range(rounds):
        x = pow(_rng.randrange(2, n - 1), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits, e):
    while True:
        n = _rng.getrandbits(bits) | (3 << (bits - 2)) | 1          # top two bits set: p*q has all 2048
        if all(n % p for p in _SMALL_PRIMES) and (n - 1) % e and _probable_prime(n):
            return n


def new_key(bits=2048):
    e = 65537
    while True:
        p, q = _prime(bits // 2, e), _prime(bits // 2, e)
        n = p * q
        if p != q and n.bit_length() == bits:
            return {"n": n, "e": e, "d": pow(e, -1, (p - 1) * (q - 1))}


def key():
    """Sofa's ADB key, made the first time (a few seconds)."""
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            k = json.load(f)
        return {"n": int(k["n"], 16), "e": int(k["e"]), "d": int(k["d"], 16)}
    except (OSError, ValueError, KeyError):
        pass
    k = new_key()
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"n": "%x" % k["n"], "e": k["e"], "d": "%x" % k["d"]}, f)
    return k


def sign(k, token):
    """What adb does: RSA_sign(NID_sha1, token) - the token stands in for the SHA-1 digest."""
    size = (k["n"].bit_length() + 7) // 8
    t = SHA1_DIGESTINFO + token
    em = b"\x00\x01" + b"\xff" * (size - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), k["d"], k["n"]).to_bytes(size, "big")


def public_key(k, name="sofa@sofa"):
    """Android's own format for it (android_pubkey_encode), base64, then " user@host"."""
    n, words = k["n"], k["n"].bit_length() // 32
    n0inv = (-pow(n % 2 ** 32, -1, 2 ** 32)) % 2 ** 32
    rr = pow(2, 2 * words * 32, n)
    blob = struct.pack("<II", words, n0inv) + n.to_bytes(words * 4, "little") + rr.to_bytes(words * 4, "little") \
        + struct.pack("<I", k["e"])
    return base64.b64encode(blob) + b" " + name.encode() + b"\x00"


# ---------------------------------------------------------------- talking to the device

class Device:
    def __init__(self, host, port=None, timeout=8):
        self.host, self.port, self.timeout = host, port or PORT, timeout
        self.sock = None
        self.maxdata = 4096
        self.next_id = 0
        self.inbox = {}               # our stream id -> bytes the device sent on it

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _send(self, cmd, a0, a1, data=b""):
        self.sock.sendall(struct.pack("<6I", cmd, a0, a1, len(data), sum(data) & 0xFFFFFFFF, cmd ^ 0xFFFFFFFF) + data)

    def _read(self, n):
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise AdbError("the Fire TV closed the connection")
            out += chunk
        return out

    def _recv(self):
        cmd, a0, a1, length, _check, magic = struct.unpack("<6I", self._read(24))
        if magic != cmd ^ 0xFFFFFFFF:
            raise AdbError("the Fire TV's answer was garbled")
        return cmd, a0, a1, self._read(length) if length else b""

    def connect(self, k, asking=None, wait=120):
        """Connect and sign in. `asking()` is called when the Fire TV shows its "Allow?" question."""
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._send(CNXN, VERSION, MAXDATA, b"host::\x00")
        signed = offered = False
        while True:
            cmd, a0, a1, data = self._recv()
            if cmd == CNXN:
                self.maxdata = max(256, min(a1, MAXDATA))
                self.sock.settimeout(self.timeout)
                return data.rstrip(b"\x00").decode("utf-8", "replace")
            if cmd != AUTH or a0 != AUTH_TOKEN:
                continue
            if not signed:                         # known from before ("Always allow")?
                signed = True
                self._send(AUTH, AUTH_SIGNATURE, 0, sign(k, data))
            elif not offered:                      # no: ask on the TV
                offered = True
                if asking:
                    asking()
                self.sock.settimeout(wait)
                self._send(AUTH, AUTH_RSAPUBLICKEY, 0, public_key(k))
            else:
                raise NotAllowed("the Fire TV didn't allow it")

    def _open(self, destination):
        self.next_id += 1
        mine = self.next_id
        self.inbox[mine] = b""
        self._send(OPEN, mine, 0, destination.encode() + b"\x00")
        while True:
            cmd, a0, a1, data = self._recv()
            if a1 != mine:
                continue
            if cmd == OKAY:
                return mine, a0
            if cmd == CLSE:
                raise AdbError("the Fire TV refused %s" % destination.split(":")[0])

    def _pump(self, mine, theirs, until):
        """Handle what the device sends until `until(cmd)` says stop; returns that command."""
        while True:
            cmd, a0, a1, data = self._recv()
            if a1 != mine:
                continue
            if cmd == WRTE:
                self.inbox[mine] += data
                self._send(OKAY, mine, theirs)
                if until(WRTE):
                    return WRTE
            elif cmd in (OKAY, CLSE) and until(cmd):
                return cmd
            elif cmd == CLSE:
                raise AdbError("the Fire TV ended the transfer early")

    def _write(self, mine, theirs, data):
        for i in range(0, len(data), self.maxdata):
            self._send(WRTE, mine, theirs, data[i:i + self.maxdata])
            self._pump(mine, theirs, lambda c: c == OKAY)

    def shell(self, command):
        """Run a command on the device; returns what it printed."""
        mine, theirs = self._open("shell:" + command)
        self._pump(mine, theirs, lambda c: c == CLSE)
        self._send(CLSE, mine, theirs)
        return self.inbox.pop(mine).decode("utf-8", "replace")

    def push(self, data, path, progress=None):
        """Copy `data` (bytes) to `path` on the device."""
        mine, theirs = self._open("sync:")
        spec = ("%s,%d" % (path, 0o100644)).encode()
        out = bytearray(b"SEND" + struct.pack("<I", len(spec)) + spec)
        done = 0
        for i in range(0, len(data), 64 * 1024):            # the sync protocol's largest piece
            chunk = data[i:i + 64 * 1024]
            out += b"DATA" + struct.pack("<I", len(chunk)) + chunk
            while len(out) >= self.maxdata:
                self._write(mine, theirs, bytes(out[:self.maxdata]))
                del out[:self.maxdata]
            done += len(chunk)
            if progress:
                progress(done / max(1, len(data)))
        out += b"DONE" + struct.pack("<I", int(time.time()))
        self._write(mine, theirs, bytes(out))
        self._pump(mine, theirs, lambda c: c == WRTE and len(self.inbox[mine]) >= 8)
        reply = self.inbox[mine]
        if reply[:4] != b"OKAY":
            length = struct.unpack("<I", reply[4:8])[0] if len(reply) >= 8 else 0
            self._pump(mine, theirs, lambda c: c == WRTE and len(self.inbox[mine]) >= 8 + length)
            raise AdbError("copying failed: %s" % self.inbox[mine][8:8 + length].decode("utf-8", "replace"))
        self._send(WRTE, mine, theirs, b"QUIT" + struct.pack("<I", 0))   # done; its answer to this doesn't matter
        self._send(CLSE, mine, theirs)
