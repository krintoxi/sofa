"""RSA keys with the standard library only: made here, signed with here, saved as the PEM files every
program reads. Used for HTTPS certificates (acme.py, x509.py) and the Fire TV installer (adb.py).

A key is a dict: {"n", "e", "d", "p", "q"} (big integers).
"""
import base64
import hashlib
import random

from . import der

_rng = random.SystemRandom()
_SMALL_PRIMES = [p for p in range(3, 2000) if all(p % d for d in range(2, int(p ** 0.5) + 1))]
DIGEST_INFO = {"sha1": bytes.fromhex("3021300906052b0e03021a05000414"),
               "sha256": bytes.fromhex("3031300d060960864801650304020105000420")}


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
        n = _rng.getrandbits(bits) | (3 << (bits - 2)) | 1          # top two bits set: p*q has all the bits
        if all(n % p for p in _SMALL_PRIMES) and (n - 1) % e and _probable_prime(n):
            return n


def generate(bits=2048):
    """A new key (a few seconds on an old computer)."""
    e = 65537
    while True:
        p, q = _prime(bits // 2, e), _prime(bits // 2, e)
        n = p * q
        if p != q and n.bit_length() == bits:
            return {"n": n, "e": e, "d": pow(e, -1, (p - 1) * (q - 1)), "p": max(p, q), "q": min(p, q)}


def size(key):
    return (key["n"].bit_length() + 7) // 8


def sign_digest(key, digest, hash_name):
    """PKCS#1 v1.5 signature of an already-made digest."""
    t = DIGEST_INFO[hash_name] + digest
    em = b"\x00\x01" + b"\xff" * (size(key) - len(t) - 3) + b"\x00" + t
    m = int.from_bytes(em, "big")
    if key.get("p") and key.get("q"):            # the quick way (Chinese remainder theorem)
        p, q, d = key["p"], key["q"], key["d"]
        m1, m2 = pow(m, d % (p - 1), p), pow(m, d % (q - 1), q)
        s = m2 + q * ((pow(q, -1, p) * (m1 - m2)) % p)
    else:
        s = pow(m, key["d"], key["n"])
    return s.to_bytes(size(key), "big")


def sign(key, data, hash_name="sha256"):
    return sign_digest(key, hashlib.new(hash_name, data).digest(), hash_name)


def verify(n, e, data, signature, hash_name="sha256"):
    em = pow(int.from_bytes(signature, "big"), e, n).to_bytes((n.bit_length() + 7) // 8, "big")
    t = DIGEST_INFO[hash_name] + hashlib.new(hash_name, data).digest()
    return em == b"\x00\x01" + b"\xff" * (len(em) - len(t) - 3) + b"\x00" + t


# ---------------------------------------------------------------- files

def public_der(key):
    """SubjectPublicKeyInfo (what certificates and requests carry)."""
    return der.seq(der.seq(der.oid("1.2.840.113549.1.1.1"), der.null()),
                   der.bits(der.seq(der.integer(key["n"]), der.integer(key["e"]))))


def private_der(key):
    """PKCS#1 RSAPrivateKey."""
    n, e, d, p, q = key["n"], key["e"], key["d"], key["p"], key["q"]
    return der.seq(*[der.integer(x) for x in (0, n, e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p))])


def pem(data, label):
    body = base64.encodebytes(data).decode().replace("\n", "")
    return "-----BEGIN %s-----\n%s\n-----END %s-----\n" % (label, "\n".join(body[i:i + 64] for i in range(0, len(body), 64)), label)


def unpem(text, label=None):
    """The bytes of the first PEM block (of `label`, if given)."""
    lines, inside = [], False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("-----BEGIN ") and (label is None or label in line):
            inside = True
        elif line.startswith("-----END ") and inside:
            break
        elif inside:
            lines.append(line)
    return base64.b64decode("".join(lines))


def to_pem(key):
    return pem(private_der(key), "RSA PRIVATE KEY")


def from_pem(text):
    values = [der.read_integer(v) for t, v in der.children(der.parse(unpem(text, "RSA PRIVATE KEY"))[1])]
    return {"n": values[1], "e": values[2], "d": values[3], "p": values[4], "q": values[5]}


def jwk(key):
    """The public key as a JSON Web Key (for Let's Encrypt)."""
    def b64(n):
        return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
    return {"e": b64(key["e"]), "kty": "RSA", "n": b64(key["n"])}
