"""Web requests (TVmaze, TMDB, GitHub, channel lists) with certificates that work on every Mac.

Every request Sofa makes to the internet goes through here, and none is needed to watch: the
library, the player, the pictures and the app itself are all on the Sofa computer.

- Offline (Server → Settings): nothing leaves the house. No details or artwork lookups, no update
  checks, no yt-dlp, no channel lists.
- With the internet down, Sofa notices on the first failed lookup and stops asking for a few
  minutes, so nothing waits on it (and nothing is remembered as "not found").

Python from python.org ships without the list of trusted certificate authorities until its
"Install Certificates" step is run, so every https:// request fails ("certificate verify
failed"): no artwork, no details, no updates, no yt-dlp. When Python has no authorities of
its own, Sofa uses the system's list instead (macOS: /etc/ssl/cert.pem).
"""
import errno
import os
import socket
import ssl
import time
import urllib.error
import urllib.request

from . import config

SYSTEM_BUNDLES = ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
                  "/etc/pki/tls/certs/ca-bundle.crt", "/opt/homebrew/etc/ca-certificates/cert.pem",
                  "/usr/local/etc/ca-certificates/cert.pem", "/opt/homebrew/etc/openssl@3/cert.pem")
_context = None
last_error = {}          # {"at": time, "message": ...} when a request failed for a reason worth showing


def context():
    global _context
    if _context is None:
        ctx = ssl.create_default_context()
        if not ctx.cert_store_stats().get("x509_ca"):
            for bundle in SYSTEM_BUNDLES:
                if os.path.isfile(bundle):
                    try:
                        ctx.load_verify_locations(cafile=bundle)
                        break
                    except (OSError, ssl.SSLError):
                        continue
            else:
                try:
                    import certifi            # if it happens to be installed
                    ctx.load_verify_locations(cafile=certifi.where())
                except Exception:
                    pass
        _context = ctx
    return _context


class Offline(OSError):
    """Not asked: Sofa is set to work offline, or the internet can't be reached right now."""


DOWN_FOR = 180
_down_until = [0.0]


def offline_mode():
    return bool(config.get("offline"))


def online():
    """May Sofa use the internet now?"""
    return not offline_mode() and time.time() >= _down_until[0]


def _unreachable(exc):
    """The internet itself is out of reach (no name lookups, no route), not one site saying no."""
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, socket.gaierror):
        return True
    return isinstance(reason, OSError) and reason.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN)


def urlopen(req, timeout=20):
    if offline_mode():
        raise Offline("Sofa is set to work offline (Server, Settings)")
    if time.time() < _down_until[0]:
        raise Offline("the internet can't be reached right now")
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=context())
    except urllib.error.HTTPError:
        raise
    except Exception as exc:
        if _unreachable(exc):
            _down_until[0] = time.time() + DOWN_FOR
            raise Offline("the internet can't be reached right now") from exc
        text = str(getattr(exc, "reason", None) or exc)
        if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text:
            last_error.update(at=time.time(), message="Sofa can't check secure web addresses: this Python has no "
                              "certificates. Run \"Install Certificates.command\" in your Python folder (Applications).")
        raise
