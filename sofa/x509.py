"""Certificates for HTTPS, standard library only: the request Let's Encrypt signs (a CSR), a certificate
Sofa signs itself (for encryption at home without a domain), and reading a certificate's names and dates."""
import hashlib
import ipaddress
import os
import time

from . import der, rsakey

SHA256_RSA = der.seq(der.oid("1.2.840.113549.1.1.11"), der.null())
CN, SAN, BASIC, KEY_USAGE, EXT_KEY_USAGE = "2.5.4.3", "2.5.29.17", "2.5.29.19", "2.5.29.15", "2.5.29.37"


def _name(common_name):
    return der.seq(der.set_of(der.seq(der.oid(CN), der.utf8(common_name))))


def _alt_names(names):
    out = []
    for n in names:
        try:
            out.append(der.tlv(0x87, ipaddress.ip_address(n).packed))      # iPAddress
        except ValueError:
            out.append(der.tlv(0x82, n.encode("idna")))                    # dNSName
    return der.seq(der.oid(SAN), der.octets(der.seq(*out)))


def csr(key, names):
    """A certificate signing request for `names` (the first is the main one), as DER."""
    info = der.seq(der.integer(0), _name(names[0]), rsakey.public_der(key),
                   der.implicit(0, der.seq(der.oid("1.2.840.113549.1.9.14"), der.set_of(der.seq(_alt_names(names)))),
                                constructed=True))
    return der.seq(info, SHA256_RSA, der.bits(rsakey.sign(key, info)))


def self_signed(key, names, days=825):
    """A certificate for `names` signed by its own key, as PEM (browsers ask once whether to trust it)."""
    now = int(time.time())
    key_id = hashlib.sha1(der.seq(der.integer(key["n"]), der.integer(key["e"]))).digest()
    extensions = der.seq(
        _alt_names(names),
        der.seq(der.oid("2.5.29.14"), der.octets(der.octets(key_id))),                              # subject key id
        der.seq(der.oid("2.5.29.35"), der.octets(der.seq(der.implicit(0, key_id)))),                # authority key id
        der.seq(der.oid(BASIC), der.boolean(True), der.octets(der.seq())),                         # not a CA
        der.seq(der.oid(KEY_USAGE), der.boolean(True), der.octets(der.tlv(der.BIT_STRING, b"\x05\xa0"))),   # sign, encipher keys
        der.seq(der.oid(EXT_KEY_USAGE), der.octets(der.seq(der.oid("1.3.6.1.5.5.7.3.1")))))      # a web server
    tbs = der.seq(der.explicit(0, der.integer(2)), der.integer(int.from_bytes(os.urandom(16), "big") >> 1),
                  SHA256_RSA, _name(names[0]), der.seq(der.gentime(now - 3600), der.gentime(now + days * 86400)),
                  _name(names[0]), rsakey.public_der(key), der.explicit(3, extensions))
    return rsakey.pem(der.seq(tbs, SHA256_RSA, der.bits(rsakey.sign(key, tbs))), "CERTIFICATE")


def info(pem_text):
    """{"names", "not_before", "not_after", "issuer"} of the first certificate in a PEM file."""
    cert = der.children(der.parse(rsakey.unpem(pem_text, "CERTIFICATE"))[1])
    tbs = der.children(cert[0][1])
    i = 1 if tbs[0][0] == 0xA0 else 0              # version is optional
    issuer, validity, subject = tbs[i + 2], tbs[i + 3], tbs[i + 4]
    times = der.children(validity[1])
    out = {"not_before": der.read_time(*times[0]), "not_after": der.read_time(*times[1]),
           "issuer": _common_name(issuer[1]), "names": []}
    for tag, value in tbs[i + 6:]:
        if tag != 0xA3:
            continue
        for _t, ext in der.children(der.children(value)[0][1]):
            parts = der.children(ext)
            if parts[0][1] == der.oid(SAN)[2:]:
                for t, v in der.children(der.children(parts[-1][1])[0][1]):
                    out["names"].append(v.decode() if t == 0x82 else str(ipaddress.ip_address(v)))
    if not out["names"]:
        out["names"] = [_common_name(subject[1])]
    return out


def _common_name(name_value):
    for _t, rdn in der.children(name_value):
        for _t2, atv in der.children(rdn):
            parts = der.children(atv)
            if parts[0][1] == der.oid(CN)[2:]:
                return parts[1][1].decode("utf-8", "replace")
    return ""
