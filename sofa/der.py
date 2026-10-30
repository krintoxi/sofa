"""Just enough ASN.1 DER to make and read keys, certificate requests and certificates (for HTTPS and the
Fire TV installer), so Sofa needs no crypto library: the standard library has none for this.

Encoding: each function returns the bytes of one value. Reading: parse(data) -> (tag, value bytes, rest),
children(seq_bytes) -> [(tag, value), ...].
"""
import time

SEQUENCE, SET, INTEGER, BIT_STRING, OCTET_STRING, NULL, OID, UTF8, PRINTABLE, UTCTIME, GENTIME = (
    0x30, 0x31, 0x02, 0x03, 0x04, 0x05, 0x06, 0x0C, 0x13, 0x17, 0x18)


def tlv(tag, value):
    n = len(value)
    if n < 0x80:
        length = bytes([n])
    else:
        body = n.to_bytes((n.bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(body)]) + body
    return bytes([tag]) + length + value


def integer(n):
    """A non-negative INTEGER."""
    body = n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big")
    while len(body) > 1 and body[0] == 0 and body[1] < 0x80:     # shortest form, a 0 in front only when needed
        body = body[1:]
    return tlv(INTEGER, body)


def seq(*items):
    return tlv(SEQUENCE, b"".join(items))


def set_of(*items):
    return tlv(SET, b"".join(sorted(items)))


def null():
    return tlv(NULL, b"")


def octets(b):
    return tlv(OCTET_STRING, b)


def bits(b):
    return tlv(BIT_STRING, b"\x00" + b)


def utf8(s):
    return tlv(UTF8, s.encode("utf-8"))


def boolean(v):
    return tlv(0x01, b"\xff" if v else b"\x00")


def oid(dotted):
    parts = [int(x) for x in dotted.split(".")]
    out = bytearray([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        chunk = [p & 0x7F]
        p >>= 7
        while p:
            chunk.append(0x80 | (p & 0x7F))
            p >>= 7
        out += bytes(reversed(chunk))
    return tlv(OID, bytes(out))


def explicit(n, inner):
    """[n] EXPLICIT (context-specific, constructed)."""
    return tlv(0xA0 | n, inner)


def implicit(n, raw, constructed=False):
    """[n] IMPLICIT: the inner value's bytes under a context tag."""
    return tlv((0xA0 if constructed else 0x80) | n, raw)


def gentime(t):
    """A time: UTCTime up to 2049, GeneralizedTime after (as X.509 says)."""
    tm = time.gmtime(t)
    if tm.tm_year < 2050:
        return tlv(UTCTIME, time.strftime("%y%m%d%H%M%SZ", tm).encode())
    return tlv(GENTIME, time.strftime("%Y%m%d%H%M%SZ", tm).encode())


# ---------------------------------------------------------------- reading

def parse(data):
    """The first value in `data`: (tag, value, rest)."""
    tag, first = data[0], data[1]
    if first < 0x80:
        length, start = first, 2
    else:
        count = first & 0x7F
        length, start = int.from_bytes(data[2:2 + count], "big"), 2 + count
    return tag, data[start:start + length], data[start + length:]


def children(value):
    out = []
    while value:
        tag, v, value = parse(value)
        out.append((tag, v))
    return out


def read_integer(value):
    return int.from_bytes(value, "big", signed=False)


def read_time(tag, value):
    """Seconds since 1970 from a UTCTime or GeneralizedTime."""
    import calendar
    text = value.decode()
    fmt = "%y%m%d%H%M%SZ" if tag == UTCTIME else "%Y%m%d%H%M%SZ"
    return calendar.timegm(time.strptime(text, fmt))
