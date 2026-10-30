"""HTTPS for Sofa: encrypted connections, at home and from the internet, with nothing else to install.

Server → Settings → Internet and HTTPS picks how (config "https"):
- "letsencrypt": a free certificate for your domain (sofa.example.com, or a free yourname.duckdns.org),
  from Let's Encrypt (acme.py), renewed by itself a month before it runs out;
- "files": your own certificate and key (cert_file, key_file), e.g. from Tailscale or a company;
- "self": a certificate Sofa makes itself, for encryption at home without a domain (browsers ask
  once whether to trust it);
- "off".

Sofa then answers HTTPS on https_port (8443) as well as plain HTTP on its normal port. The router
sends the internet's port 443 to 8443, and port 80 to the normal port, where Let's Encrypt checks the
domain and internet browsers are sent on to HTTPS (upnp.py can set that up on the router).
"""
import json
import os
import socket
import ssl
import threading
import time

from . import acme, config, rsakey, store, x509

DIR = os.path.join(config.DATA_DIR, "tls")
CERT, KEY, ACCOUNT = os.path.join(DIR, "cert.pem"), os.path.join(DIR, "key.pem"), os.path.join(DIR, "account.json")
SELF_CERT, SELF_KEY = os.path.join(DIR, "self-cert.pem"), os.path.join(DIR, "self-key.pem")
RENEW_BEFORE = 30 * 86400
_state = {"step": None, "error": None, "busy": False, "listening": None}
_ctx = {"key": None, "ctx": None}
_lock = threading.Lock()


def mode():
    m = config.get("https") or "off"
    return m if m in ("off", "letsencrypt", "files", "self") else "off"


def files():
    """(certificate, key) paths for the current mode, or None."""
    m = mode()
    if m == "letsencrypt":
        return (CERT, KEY) if os.path.isfile(CERT) and os.path.isfile(KEY) else None
    if m == "files":
        c, k = os.path.expanduser(config.get("cert_file") or ""), os.path.expanduser(config.get("key_file") or "")
        return (c, k) if os.path.isfile(c) and os.path.isfile(k) else None
    if m == "self":
        ensure_self_signed()
        return SELF_CERT, SELF_KEY
    return None


def trusted():
    """Is the certificate one browsers trust without asking (so HSTS and redirects are safe)?"""
    return mode() in ("letsencrypt", "files") and files() is not None


def context():
    """The SSL context for the current certificate, made again when the files change."""
    f = files()
    if not f:
        return None
    key = (f, os.path.getmtime(f[0]), os.path.getmtime(f[1]))
    with _lock:
        if _ctx["key"] != key:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(f[0], f[1])
            ctx.set_alpn_protocols(["http/1.1"])
            _ctx.update(key=key, ctx=ctx)
        return _ctx["ctx"]


def cert_info():
    f = files()
    if not f:
        return None
    try:
        with open(f[0], encoding="utf-8") as fh:
            return x509.info(fh.read())
    except (OSError, ValueError, IndexError) as exc:
        return {"error": "That certificate file can't be read (%s)." % exc}


def status():
    info = cert_info() or {}
    return {"mode": mode(), "domain": config.get("domain") or "", "port": config.get("https_port"),
            "listening": _state["listening"], "names": info.get("names") or [], "not_after": info.get("not_after"),
            "issuer": info.get("issuer"), "file_error": info.get("error"), "step": _state["step"], "error": _state["error"],
            "busy": _state["busy"], "trusted": trusted()}


# ---------------------------------------------------------------- certificates

def _write(path, text, private=False):
    os.makedirs(DIR, exist_ok=True)
    tmp = path + ".new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def self_names():
    from . import dlna
    host = socket.gethostname().split(".")[0]
    return [host + ".local", "localhost"] + dlna.lan_addresses()


def ensure_self_signed():
    """Sofa's own certificate for this computer's names and addresses (made again if they change)."""
    names = self_names()
    try:
        with open(SELF_CERT, encoding="utf-8") as f:
            have = x509.info(f.read())
        if set(names) <= set(have["names"]) and have["not_after"] - time.time() > RENEW_BEFORE and os.path.isfile(SELF_KEY):
            return
    except (OSError, ValueError, IndexError):
        pass
    key = rsakey.generate()
    _write(SELF_KEY, rsakey.to_pem(key), private=True)
    _write(SELF_CERT, x509.self_signed(key, names))


def _account_key():
    try:
        with open(ACCOUNT, encoding="utf-8") as f:
            return rsakey.from_pem(json.load(f)["key"])
    except (OSError, ValueError, KeyError, IndexError):
        key = rsakey.generate()
        _write(ACCOUNT, json.dumps({"key": rsakey.to_pem(key)}), private=True)
        return key


def obtain(directory=None, context=None):
    """Get (or renew) the Let's Encrypt certificate for the domain. Returns True when it worked."""
    domain = (config.get("domain") or "").strip().lower()
    if not domain:
        _state.update(error="Set the domain first.")
        return False
    with _lock:
        if _state["busy"]:
            return False
        _state.update(busy=True, error=None, step="Starting")
    try:
        client = acme.Client(_account_key(), directory or config.get("acme_directory") or acme.LETS_ENCRYPT, context=context)
        _state["step"] = "Signing up with Let's Encrypt"
        client.account(config.get("acme_email") or None)
        key = rsakey.generate()
        chain = client.certificate([domain], key, x509.csr(key, [domain]), step=lambda t: _state.update(step=t))
        _write(KEY, rsakey.to_pem(key), private=True)
        _write(CERT, chain)
        _state.update(step=None)
        store.log("settings", "Got an HTTPS certificate for %s from Let's Encrypt" % domain)
        return True
    except Exception as exc:
        _state.update(error=str(exc)[:400], step=None)
        store.log("settings", "Couldn't get an HTTPS certificate for %s: %s" % (domain, str(exc)[:200]))
        return False
    finally:
        _state["busy"] = False


def due():
    """Should the Let's Encrypt certificate be got or renewed now?"""
    if mode() != "letsencrypt" or not config.get("domain"):
        return False
    info = cert_info()
    if not info or info.get("error"):
        return True
    return domain_changed(info) or info["not_after"] - time.time() < RENEW_BEFORE


def domain_changed(info):
    return (config.get("domain") or "").strip().lower() not in [n.lower() for n in info.get("names") or []]


# ---------------------------------------------------------------- the HTTPS listener

def _make_server():
    from . import web

    class TLSServer(web.Server):
        def get_request(self):
            sock, addr = self.socket.accept()
            ctx = context()
            if ctx is None:
                sock.close()
                raise OSError("HTTPS is off")
            sock.settimeout(60)
            return ctx.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), addr

        def handle_error(self, request, client_address):
            import sys
            if isinstance(sys.exc_info()[1], (ssl.SSLError, OSError)):
                return          # scanners and old browsers failing the handshake: nothing to report
            super().handle_error(request, client_address)

    return TLSServer(("0.0.0.0", config.get("https_port")), web.Handler)


def _serve():
    while True:
        if mode() != "off" and context() is not None:
            try:
                httpd = _make_server()
            except OSError as exc:
                _state.update(listening=None, error="Can't answer HTTPS on port %s (%s)." % (config.get("https_port"), exc))
                time.sleep(60)
                continue
            _state["listening"] = config.get("https_port")
            threading.Thread(target=_watch_off, args=(httpd,), daemon=True).start()
            httpd.serve_forever()
            httpd.server_close()
            _state["listening"] = None
        time.sleep(5)


def _watch_off(httpd):
    """Stop the listener when HTTPS is switched off or its port changes."""
    port = config.get("https_port")
    while mode() != "off" and config.get("https_port") == port:
        time.sleep(3)
    httpd.shutdown()


def _renew_loop():
    time.sleep(30)
    while True:
        try:
            if due() and not _state["busy"]:
                obtain()
        except Exception as exc:
            _state["error"] = str(exc)[:300]
        time.sleep(6 * 3600 if not _state["error"] else 3600)


def start():
    threading.Thread(target=_serve, daemon=True, name="https").start()
    threading.Thread(target=_renew_loop, daemon=True, name="https-renew").start()
