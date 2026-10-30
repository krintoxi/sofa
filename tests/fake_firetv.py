"""A pretend Fire TV for the tests: the device side of ADB on a local port. It checks signatures and
public keys the way adbd does, asks "Allow?" (answered by `approve`), keeps copied files, and answers
`pm install`, `am start` and `rm` like Android."""
import base64
import os
import socket
import struct
import threading
import time

CNXN, AUTH, OPEN, OKAY, CLSE, WRTE = 0x4E584E43, 0x48545541, 0x4E45504F, 0x59414B4F, 0x45534C43, 0x45545257
SHA1_DIGESTINFO = bytes.fromhex("3021300906052b0e03021a05000414")


def decode_public_key(text):
    """android_pubkey_decode, plus the checks older devices make on n0inv and rr."""
    blob = base64.b64decode(text.split(b" ")[0])
    words, n0inv = struct.unpack("<II", blob[:8])
    n = int.from_bytes(blob[8:8 + words * 4], "little")
    rr = int.from_bytes(blob[8 + words * 4:8 + words * 8], "little")
    e = struct.unpack("<I", blob[8 + words * 8:12 + words * 8])[0]
    assert (n0inv * n) % 2 ** 32 == 2 ** 32 - 1, "n0inv is wrong"
    assert rr == pow(2, 2 * words * 32, n), "rr is wrong"
    return n, e


def verify(n, e, token, sig):
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes((n.bit_length() + 7) // 8, "big")
    t = SHA1_DIGESTINFO + token
    return em == b"\x00\x01" + b"\xff" * (len(em) - len(t) - 3) + b"\x00" + t


class FakeFireTV:
    def __init__(self, approve=True, maxdata=4096, port=0):
        self.approve, self.maxdata = approve, maxdata
        self.keys, self.files, self.installed, self.commands = [], {}, {}, []
        self.asked = 0
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", port))
        self.server.listen(4)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self):
        try:
            self.server.shutdown(socket.SHUT_RDWR)        # wakes the waiting accept(); close() alone doesn't on Linux
        except OSError:
            pass
        self.server.close()

    def _accept(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    @staticmethod
    def _send(conn, cmd, a0, a1, data=b""):
        conn.sendall(struct.pack("<6I", cmd, a0, a1, len(data), sum(data) & 0xFFFFFFFF, cmd ^ 0xFFFFFFFF) + data)

    @staticmethod
    def _recv(conn):
        head = b""
        while len(head) < 24:
            part = conn.recv(24 - len(head))
            if not part:
                raise EOFError
            head += part
        cmd, a0, a1, length, check, magic = struct.unpack("<6I", head)
        assert magic == cmd ^ 0xFFFFFFFF, "bad magic"
        data = b""
        while len(data) < length:
            data += conn.recv(length - len(data))
        assert check == sum(data) & 0xFFFFFFFF, "bad checksum"
        return cmd, a0, a1, data

    def _serve(self, conn):
        try:
            cmd, version, maxdata, banner = self._recv(conn)
            assert cmd == CNXN and banner.startswith(b"host::")
            token = os.urandom(20)
            self._send(conn, AUTH, 1, 0, token)
            while True:
                cmd, kind, _, data = self._recv(conn)
                assert cmd == AUTH
                if kind == 2 and any(verify(n, e, token, data) for n, e in self.keys):
                    break
                if kind == 2:
                    token = os.urandom(20)
                    self._send(conn, AUTH, 1, 0, token)
                    continue
                assert kind == 3 and data.endswith(b"\x00")
                n, e = decode_public_key(data.rstrip(b"\x00"))
                self.asked += 1
                time.sleep(0.5)                               # someone reading the question on the TV
                if not self.approve:
                    self._send(conn, AUTH, 1, 0, os.urandom(20))
                    continue
                self.keys.append((n, e))
                break
            self._send(conn, CNXN, 0x01000000, self.maxdata, b"device::ro.product.model=AFTMM;\x00")
            streams = {}
            while True:
                cmd, a0, a1, data = self._recv(conn)
                if cmd == OPEN:
                    mine = 100 + a0
                    dest = data.rstrip(b"\x00").decode()
                    self._send(conn, OKAY, mine, a0)
                    if dest.startswith("shell:"):
                        out = self._shell(dest[6:])
                        if out:
                            self._send(conn, WRTE, mine, a0, out.encode())
                            self._recv(conn)                      # their OKAY
                        self._send(conn, CLSE, mine, a0)
                    else:
                        streams[mine] = {"buf": b"", "theirs": a0, "path": None, "file": b""}
                elif cmd == WRTE:
                    assert len(data) <= self.maxdata, "a piece bigger than the device said it takes"
                    s = streams[a1]
                    self._send(conn, OKAY, a1, a0)
                    s["buf"] += data
                    self._sync(conn, a1, s)
        except (EOFError, OSError):
            pass
        finally:
            conn.close()

    def _sync(self, conn, mine, s):
        while len(s["buf"]) >= 8:
            word, length = s["buf"][:4], struct.unpack("<I", s["buf"][4:8])[0]
            if word in (b"SEND", b"DATA") and len(s["buf"]) < 8 + length:
                return
            if word == b"SEND":
                s["path"] = s["buf"][8:8 + length].decode().rsplit(",", 1)[0]
                s["buf"] = s["buf"][8 + length:]
            elif word == b"DATA":
                s["file"] += s["buf"][8:8 + length]
                s["buf"] = s["buf"][8 + length:]
            elif word == b"DONE":
                self.files[s["path"]] = s["file"]
                s["buf"] = s["buf"][8:]
                self._send(conn, WRTE, mine, s["theirs"], b"OKAY\x00\x00\x00\x00")
            elif word == b"QUIT":
                s["buf"] = b""
                self._send(conn, CLSE, mine, s["theirs"])
            else:
                raise AssertionError("unknown sync request %r" % word)

    def _shell(self, command):
        self.commands.append(command)
        parts = command.split()
        if parts[:2] == ["pm", "install"]:
            data = self.files.get(parts[-1])
            if data is None:
                return "Failure [INSTALL_FAILED_INVALID_URI]\n"
            self.installed["uk.edgeventure.sofa"] = data
            return "Success\n"
        if parts[:1] == ["rm"]:
            self.files.pop(parts[-1], None)
            return ""
        if parts[:2] == ["am", "start"]:
            return "Starting: Intent { cmp=%s }\n" % parts[-1]
        return ""
