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

The Server page's "Sofa can't reach secure websites" is about the sites Sofa itself asks (details, artwork,
updates). A Live TV channel whose own certificate has run out, is for another name or is one it signed itself
is that channel's fault: it's turned away as before, and says nothing about this computer.
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


def certificate_fault(exc):
    """What's wrong with the certificate a site showed ("unknown", "expired", "early", "name", "self"), or None when
    the request failed for another reason."""
    reason = getattr(exc, "reason", exc)
    text = (getattr(reason, "verify_message", None) or "") + " " + str(reason)
    if not isinstance(reason, ssl.SSLCertVerificationError) and "certificate verify failed" not in text \
            and "CERTIFICATE_VERIFY_FAILED" not in text:
        return None
    low = text.lower()
    if "not yet valid" in low:
        return "early"
    if "expired" in low:
        return "expired"
    if "mismatch" in low or "doesn't match" in low or "not valid for" in low:
        return "name"
    if "self signed" in low or "self-signed" in low:
        return "self"
    return "unknown"


def _own_fault(fault):
    """The words for the Server page when a site Sofa itself chose can't be checked, or None when it's the site's."""
    if fault == "unknown":
        if not context().cert_store_stats().get("x509_ca"):
            return ("Sofa can't check secure web addresses: this Python has no certificates. Run \"Install "
                    "Certificates.command\" in your Python folder (Applications).")
        return ("Sofa couldn't check a secure web address: this computer's list of certificate authorities doesn't "
                "have the one that site uses. Updating the system (or Python) brings a newer list.")
    if fault in ("early", "expired"):
        return ("Sofa couldn't check a secure web address: its certificate's dates don't fit this computer's clock "
                "(%s). Is the date and time right?" % time.strftime("%Y-%m-%d %H:%M"))
    return None


def urlopen(req, timeout=20, handlers=(), whole_internet=True):
    """`handlers`: more urllib handlers (live.py's, which checks where a redirect goes). `whole_internet` False: an
    address someone else chose (a channel in a list, a list's own address). Thousands of those come and go, and one
    whose name no longer exists says nothing about the internet: it doesn't make Sofa stop asking, and it's asked
    even while Sofa has stopped asking the rest."""
    if offline_mode():
        raise Offline("Sofa is set to work offline (Server, Settings)")
    if whole_internet and time.time() < _down_until[0]:
        raise Offline("the internet can't be reached right now")
    try:
        if handlers:                          # (live.py's own https handler, when it brings one, has this context)
            own = any(isinstance(h, urllib.request.HTTPSHandler) for h in handlers)
            base = () if own else (urllib.request.HTTPSHandler(context=context()),)
            r = urllib.request.build_opener(*base, *handlers).open(req, timeout=timeout)
        else:
            r = urllib.request.urlopen(req, timeout=timeout, context=context())
        if whole_internet and last_error and str(getattr(req, "full_url", req)).startswith("https://"):
            last_error.clear()                # a site of Sofa's own was checked and answered: nothing to show any more
        return r
    except urllib.error.HTTPError:
        raise
    except Exception as exc:
        if whole_internet and _unreachable(exc):
            _down_until[0] = time.time() + DOWN_FOR
            raise Offline("the internet can't be reached right now") from exc
        # (an address someone else chose, a channel's or a list's, says nothing about this computer: thousands of
        # those come and go, and some always have a certificate that ran out or is for another name)
        message = _own_fault(certificate_fault(exc)) if whole_internet else None
        if message:
            last_error.update(at=time.time(), message=message)
        raise
