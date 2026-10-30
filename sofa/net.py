"""Web requests (TVmaze, TMDB, GitHub, channel lists) with certificates that work on every Mac.

Python from python.org ships without the list of trusted certificate authorities until its
"Install Certificates" step is run, so every https:// request fails ("certificate verify
failed"): no artwork, no details, no updates, no yt-dlp. When Python has no authorities of
its own, Sofa uses the system's list instead (macOS: /etc/ssl/cert.pem).
"""
import os
import ssl
import time
import urllib.request

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


def urlopen(req, timeout=20):
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=context())
    except Exception as exc:
        text = str(getattr(exc, "reason", None) or exc)
        if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text:
            last_error.update(at=time.time(), message="Sofa can't check secure web addresses: this Python has no "
                              "certificates. Run \"Install Certificates.command\" in your Python folder (Applications).")
        raise
