#!/usr/bin/env python3
"""Sofa Box certificates: real HTTPS for each Sofa Box's phone remote at home.

Each box gets a name of its own, <id>.box.edgeventure.uk, pointed (DNS only) at its address on the home
network, and a Let's Encrypt certificate for that name. The box makes its own key and sends only a certificate
request (CSR). This service proves the name to Let's Encrypt with a DNS record (DNS-01) on Cloudflare, so the
boxes never hold the Cloudflare token.

    python3 sofa-box-certs.py serve     the service (127.0.0.1:8470; the Cloudflare tunnel makes it public)
    python3 sofa-box-certs.py check     the token, the zone, openssl and Let's Encrypt, changing nothing
    python3 sofa-box-certs.py try       a test certificate from Let's Encrypt's staging, for test-<random>.<base>

Setting it up on a Mac: deploy/box-certs/README.md. Python 3.8+ and the openssl command; nothing to install.

What a box sends: a random id and secret it got here, its address on its home network (like 192.168.1.30), and
certificate requests. What's kept (boxes.json): the id, a hash of the secret, that address, and when its
certificate was made. Nothing about what anyone watches.

Reports: when someone presses Send a report on a box (Settings -> Help), it sends its checks and recent logs here
(/v1/report), with no titles in them; they're kept in reports/ for us to read, the newest few hundred.

The relay (Relay, /r/<box id>/): the phone remote from anywhere, with no certificate or name per box. A box keeps a
request open here (/v1/relay/poll, signed with its secret); a phone's requests to /r/<box id>/... go down it to the
remote on the box, and the box's answers come back (/v1/relay/answer). Nothing is kept. The remote's page comes from
this service, not from the box, and only data, the icon and the pairing link pass through, each phone's sign-in
kept to its box's path: a box can't put script on this address. A phone still needs the TV's code, here only the
QR code's long one.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.environ.get("SOFA_CERTS_DIR") or os.path.expanduser("~/.config/sofa-box-certs")
DEFAULTS = {
    "zone": "edgeventure.uk",                     # the Cloudflare zone
    "base": "box.edgeventure.uk",                 # boxes are <id>.<base>
    "listen": "127.0.0.1:8470",                   # the tunnel's public hostname points here
    "acme": "https://acme-v02.api.letsencrypt.org/directory",
    "acme_staging": "https://acme-staging-v02.api.letsencrypt.org/directory",
    "acme_ca": "",                                # a CA file for the ACME server (tests: Pebble's)
    "email": "",                                  # Let's Encrypt's notices (optional)
    "cloudflare_api": "https://api.cloudflare.com/client/v4",
    "doh": "https://cloudflare-dns.com/dns-query",  # to see the DNS record is out ("" waits "settle" seconds instead)
    "settle": 10,
    "new_per_week": 45,                           # Let's Encrypt: 50 new certificates a week per registered domain
    "register_per_ip_day": 10,
    "register_per_day": 500,
    "report_max": 200000,                         # a report's size (characters)
    "relay_base": "https://boxcert.edgeventure.uk",   # where phones open a box's remote (boxes are told: it can change)
    "reach_per_hour": 20,                         # "Check from outside" (a Sofa, or a box's Sofa), from one address
    "reports_per_day": 10,                        # from one box (or one address, for a box with no id yet)
    "reports_kept": 300,
}


class CertError(Exception):
    pass


def config():
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(DIR, "config.json"), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    return cfg


def cloudflare_token():
    token = os.environ.get("CF_API_TOKEN")
    if not token:
        try:
            with open(os.path.join(DIR, "cloudflare-token"), encoding="utf-8") as f:
                token = f.read().strip()
        except FileNotFoundError:
            pass
    if not token:
        raise CertError("No Cloudflare token: put it in %s (see README.md)." % os.path.join(DIR, "cloudflare-token"))
    return token


def write_private(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())
    os.replace(tmp, path)


def b64u(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def openssl(args, data=None):
    try:
        p = subprocess.run(["openssl"] + args, input=data, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CertError("openssl: %s" % exc)
    if p.returncode != 0:
        raise CertError("openssl %s: %s" % (args[0], p.stderr.decode(errors="replace").strip()[-300:]))
    return p.stdout


def http(method, url, body=None, headers=None, ctx=None, timeout=60):
    data = body if body is None or isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()
    except (OSError, ValueError) as exc:
        raise CertError("%s: %s" % (urllib.parse.urlsplit(url).netloc, exc))


def csr_names(pem):
    """The names a certificate request asks for, after checking its signature."""
    text = openssl(["req", "-noout", "-text", "-verify"], pem.encode() if isinstance(pem, str) else pem).decode(errors="replace")
    names = set(re.findall(r"DNS:([A-Za-z0-9.*-]+)", text))
    m = re.search(r"Subject:.*?CN\s*=\s*([A-Za-z0-9.*-]+)", text)
    if m:
        names.add(m.group(1))
    return {n.lower() for n in names}


def not_after(pem):
    """When a certificate (the first in a PEM chain) runs out, in seconds since 1970."""
    out = openssl(["x509", "-noout", "-enddate"], pem.encode() if isinstance(pem, str) else pem).decode()
    return ssl.cert_time_to_seconds(out.strip().split("=", 1)[1])


class Acme:
    """Just enough of ACME (RFC 8555) for one name with DNS-01; signing by the openssl command."""

    def __init__(self, directory, key_path, email="", ca=""):
        self.url, self.key_path, self.email = directory, key_path, email
        self.ctx = ssl.create_default_context(cafile=ca) if ca else None
        self.dir, self.kid, self.nonce, self.lock = None, None, None, threading.Lock()
        if not os.path.exists(key_path):
            write_private(key_path, openssl(["genrsa", "2048"]))
        text = openssl(["rsa", "-in", key_path, "-noout", "-text"]).decode()
        mod = re.search(r"modulus:\s*\n((?:[ \t]+[0-9a-fA-F:]+\n?)+)", text)
        exp = re.search(r"publicExponent:\s*(\d+)", text)
        if not (mod and exp):
            raise CertError("Couldn't read the Let's Encrypt account key %s." % key_path)
        n = bytes.fromhex(re.sub(r"[\s:]", "", mod.group(1))).lstrip(b"\0")
        e = int(exp.group(1))
        self.jwk = {"e": b64u(e.to_bytes((e.bit_length() + 7) // 8, "big")), "kty": "RSA", "n": b64u(n)}
        self.thumbprint = b64u(hashlib.sha256(json.dumps(self.jwk, sort_keys=True, separators=(",", ":")).encode()).digest())

    def directory(self):
        if not self.dir:
            status, _, body = http("GET", self.url, ctx=self.ctx)
            if status != 200:
                raise CertError("Let's Encrypt's directory: %d" % status)
            self.dir = json.loads(body)
        return self.dir

    def _nonce(self):
        if self.nonce:
            nonce, self.nonce = self.nonce, None
            return nonce
        _, headers, _ = http("HEAD", self.directory()["newNonce"], ctx=self.ctx)
        return headers.get("Replay-Nonce")

    def post(self, url, payload, again=True):
        """A signed request; payload None is POST-as-GET."""
        protected = {"alg": "RS256", "nonce": self._nonce(), "url": url}
        if self.kid:
            protected["kid"] = self.kid
        else:
            protected["jwk"] = self.jwk
        head = b64u(json.dumps(protected).encode())
        body = "" if payload is None else b64u(json.dumps(payload).encode())
        sig = b64u(openssl(["dgst", "-sha256", "-sign", self.key_path], ("%s.%s" % (head, body)).encode()))
        status, headers, out = http("POST", url, {"protected": head, "payload": body, "signature": sig},
                                    {"Content-Type": "application/jose+json"}, self.ctx)
        self.nonce = headers.get("Replay-Nonce")
        if status == 400 and again and b"badNonce" in out:
            return self.post(url, payload, False)
        if status >= 400:
            raise CertError("Let's Encrypt said %d: %s" % (status, out.decode(errors="replace")[:400]))
        return status, headers, out

    def account(self):
        if not self.kid:
            payload = {"termsOfServiceAgreed": True}
            if self.email:
                payload["contact"] = ["mailto:" + self.email]
            _, headers, _ = self.post(self.directory()["newAccount"], payload)
            self.kid = headers.get("Location")

    def poll(self, url, want, what, tries=40):
        for _ in range(tries):
            obj = json.loads(self.post(url, None)[2])
            if obj.get("status") in want:
                return obj
            if obj.get("status") == "invalid":
                raise CertError("Let's Encrypt refused %s: %s" % (what, json.dumps(obj)[:500]))
            time.sleep(2)
        raise CertError("Let's Encrypt took too long with %s." % what)

    def issue(self, csr_der, dns):
        """A certificate (PEM, with its chain) for the name in the request, proved with a DNS record."""
        with self.lock:                                       # one at a time: the nonce and Let's Encrypt's limits
            names = sorted(csr_names(openssl(["req", "-inform", "DER"], csr_der)))
            self.account()
            _, headers, body = self.post(self.directory()["newOrder"], {"identifiers": [{"type": "dns", "value": n} for n in names]})
            order_url, order = headers.get("Location"), json.loads(body)
            for authz_url in order["authorizations"]:
                authz = json.loads(self.post(authz_url, None)[2])
                if authz["status"] == "valid":
                    continue
                challenge = next((c for c in authz["challenges"] if c["type"] == "dns-01"), None)
                if not challenge:
                    raise CertError("Let's Encrypt offered no DNS check.")
                value = b64u(hashlib.sha256((challenge["token"] + "." + self.thumbprint).encode()).digest())
                record = "_acme-challenge." + authz["identifier"]["value"]
                try:                                          # (cleared even if adding it half failed)
                    dns.set_txt(record, value)
                    dns.wait_txt(record, value)
                    self.post(challenge["url"], {})
                    self.poll(authz_url, ("valid",), "the name check")
                finally:
                    dns.clear_txt(record)
            self.poll(order_url, ("ready", "valid"), "the order")
            self.post(order["finalize"], {"csr": b64u(csr_der)})
            done = self.poll(order_url, ("valid",), "the certificate")
            return self.post(done["certificate"], None)[2].decode()


class Cloudflare:
    """The zone's DNS records, with an API token that can only edit this zone's DNS."""

    def __init__(self, token, zone, api, doh="", settle=10):
        self.token, self.zone, self.api, self.doh, self.settle = token, zone, api.rstrip("/"), doh, settle
        self._zid = None

    def call(self, method, path, body=None):
        status, _, out = http(method, self.api + path, body, {"Authorization": "Bearer " + self.token,
                                                               "Content-Type": "application/json"})
        try:
            data = json.loads(out or b"{}")
        except ValueError:
            data = {}
        if status >= 400 or not data.get("success"):
            raise CertError("Cloudflare (%d): %s" % (status, json.dumps(data.get("errors") or out.decode(errors="replace")[:200])))
        return data.get("result")

    def zone_id(self):
        if not self._zid:
            found = self.call("GET", "/zones?" + urllib.parse.urlencode({"name": self.zone}))
            if not found:
                raise CertError("Cloudflare has no zone %s for this token." % self.zone)
            self._zid = found[0]["id"]
        return self._zid

    def records(self, name, kind):
        return self.call("GET", "/zones/%s/dns_records?%s" % (self.zone_id(), urllib.parse.urlencode({"type": kind, "name": name}))) or []

    def set_a(self, name, ip):
        body = {"type": "A", "name": name, "content": ip, "ttl": 120, "proxied": False,
                "comment": "Sofa Box (sofa-box-certs)"}
        found = self.records(name, "A")
        if found and found[0].get("content") == ip:
            return
        if found:
            self.call("PUT", "/zones/%s/dns_records/%s" % (self.zone_id(), found[0]["id"]), body)
        else:
            self.call("POST", "/zones/%s/dns_records" % self.zone_id(), body)

    def set_txt(self, name, value):
        self.call("POST", "/zones/%s/dns_records" % self.zone_id(), {"type": "TXT", "name": name, "content": '"%s"' % value, "ttl": 60})

    def clear_txt(self, name):
        for r in self.records(name, "TXT"):
            try:
                self.call("DELETE", "/zones/%s/dns_records/%s" % (self.zone_id(), r["id"]))
            except CertError:
                pass

    def wait_txt(self, name, value, limit=120):
        if not self.doh:
            time.sleep(self.settle)
            return
        until = time.time() + limit
        while time.time() < until:
            try:
                status, _, out = http("GET", self.doh + "?" + urllib.parse.urlencode({"name": name, "type": "TXT"}),
                                      headers={"Accept": "application/dns-json"}, timeout=10)
                if status == 200 and any(value in a.get("data", "") for a in json.loads(out).get("Answer", [])):
                    return
            except (CertError, ValueError):
                pass
            time.sleep(3)


def private_ipv4(ip):
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return a.is_private and not (a.is_loopback or a.is_link_local or a.is_unspecified or a.is_multicast)


class Boxes:
    """boxes.json: id -> {secret (its sha256), made, ip, ip_at, issued, expires}."""

    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()
        try:
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        except FileNotFoundError:
            self.data = {}

    def save(self):
        write_private(self.path, json.dumps(self.data, indent=1, sort_keys=True))


class Service:
    def __init__(self, cfg, dns, acme, now=time.time):
        self.cfg, self.dns, self.acme, self.now = cfg, dns, acme, now
        self.relay = Relay(now)
        self.boxes = Boxes(os.path.join(DIR, "boxes.json"))
        self.made = []                                        # (when, client ip) of registrations, for the limits
        self.new_certs = []                                   # when a box's first certificate was made
        self.reported = []                                    # (when, who) of reports, for the limit

    def name(self, box_id):
        return "%s.%s" % (box_id, self.cfg["base"])

    def register(self, client):
        now = self.now()
        self.made = [(t, c) for t, c in self.made if now - t < 86400]
        if sum(1 for _, c in self.made if c == client) >= self.cfg["register_per_ip_day"] or len(self.made) >= self.cfg["register_per_day"]:
            raise Limit("Too many new boxes from here today. Try again tomorrow.")
        alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
        with self.boxes.lock:
            box_id = "".join(secrets.choice(alphabet) for _ in range(10))
            while box_id in self.boxes.data:
                box_id = "".join(secrets.choice(alphabet) for _ in range(10))
            secret = secrets.token_hex(24)
            self.boxes.data[box_id] = {"secret": hashlib.sha256(secret.encode()).hexdigest(), "made": int(now)}
            self.boxes.save()
        self.made.append((now, client))
        return {"id": box_id, "secret": secret, "name": self.name(box_id)}

    def box(self, data):
        box = self.boxes.data.get(str(data.get("id") or ""))
        given = hashlib.sha256(str(data.get("secret") or "").encode()).hexdigest()
        if not box or not hmac.compare_digest(box["secret"], given):
            raise Refused("Unknown box.")
        return box

    def address(self, data):
        box = self.box(data)
        ip = str(data.get("ip") or "")
        if not private_ipv4(ip):
            raise Refused("Only an address on a home network (like 192.168.1.30).")
        if box.get("ip") != ip or self.now() - box.get("ip_at", 0) > 43200:
            self.dns.set_a(self.name(data["id"]), ip)
            with self.boxes.lock:
                box.update(ip=ip, ip_at=int(self.now()))
                self.boxes.save()
        return {"ok": True, "name": self.name(data["id"]), "ip": ip}

    def cert(self, data):
        box = self.box(data)
        name = self.name(data["id"])
        pem = str(data.get("csr") or "")
        if "BEGIN CERTIFICATE REQUEST" not in pem or len(pem) > 8000:
            raise Refused("That isn't a certificate request.")
        if csr_names(pem) != {name}:
            raise Refused("A box's request can only be for its own name, %s." % name)
        now = self.now()
        if box.get("issued") and now - box["issued"] < 7 * 86400 and box.get("expires", 0) - now > 20 * 86400:
            raise Limit("This box got a certificate this week; it lasts until %s." %
                        time.strftime("%Y-%m-%d", time.gmtime(box["expires"])))
        first = not box.get("issued")
        if first:
            self.new_certs = [t for t in self.new_certs if now - t < 7 * 86400]
            if len(self.new_certs) >= self.cfg["new_per_week"]:
                raise Limit("Many new boxes this week (Let's Encrypt's limit). The box tries again tomorrow.")
        chain = self.acme.issue(openssl(["req", "-outform", "DER"], pem.encode()), self.dns)
        expires = not_after(chain)
        if first:
            self.new_certs.append(now)
        with self.boxes.lock:
            box.update(issued=int(now), expires=int(expires))
            self.boxes.save()
        return {"ok": True, "name": name, "cert": chain, "expires": int(expires)}


    def reach(self, data, client):
        """Does a Sofa answer from the internet? Asked from here, outside the home: only Sofa's /api/info, only at a
        public address (the one checked is the one connected to: no name that changes its mind), a few times an hour
        from one asker; it says only what happened, nothing from the far end."""
        p = urllib.parse.urlsplit(str(data.get("url") or ""))
        if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
            raise Refused("An address like https://sofa.example.com.")
        try:
            port = p.port or (443 if p.scheme == "https" else 80)
        except ValueError:
            raise Refused("That port isn't a number.")
        now = self.now()
        with self.boxes.lock:
            self.reached = [(t, c) for t, c in getattr(self, "reached", []) if now - t < 3600]
            if sum(1 for _, c in self.reached if c == client) >= self.cfg["reach_per_hour"]:
                raise Limit("Checked a lot from here this hour. Try again later.")
            self.reached.append((now, client))
        try:
            ips = [a[4][0] for a in socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)]
        except OSError:
            return {"ok": False, "why": "name", "message": "%s doesn't lead anywhere yet: its DNS record isn't there (or hasn't spread yet)." % p.hostname}
        public = [ip for ip in ips if ipaddress.ip_address(ip.split("%")[0]).is_global]
        if not public:
            return {"ok": False, "why": "private", "message": "%s points at a home-network address, not at your home's internet address." % p.hostname}
        ip = public[0]
        try:
            raw = socket.create_connection((ip, port), timeout=8)
        except OSError:
            return {"ok": False, "why": "closed", "ip": ip, "message": "Nothing answers at %s on port %d from the internet: the router isn't sending "
                    "that port to Sofa (or the internet provider shares one address between homes)." % (ip, port)}
        try:
            if p.scheme == "https":
                try:
                    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=p.hostname)
                except ssl.SSLError as exc:
                    raw.close()
                    return {"ok": False, "why": "certificate", "ip": ip, "message": "It answers, but its certificate isn't valid for %s (%s)." % (p.hostname, exc.reason or "rejected")}
            else:
                sock = raw
            sock.settimeout(8)
            sock.sendall(("GET /api/info HTTP/1.1\r\nHost: %s\r\nUser-Agent: Sofa outside check\r\nConnection: close\r\n\r\n" % p.hostname).encode())
            reply = b""
            while len(reply) < 65536:                  # (Connection: close: the whole short answer, then the end)
                chunk = sock.recv(4096)
                if not chunk:
                    break
                reply += chunk
            sock.close()
        except OSError as exc:
            return {"ok": False, "why": "closed", "ip": ip, "message": "The connection broke off (%s)." % exc}
        status_line = reply.split(b"\r\n", 1)[0].decode("latin-1")
        sofa = status_line.split(" ")[1:2] == ["200"] and re.search(rb'"sofa"\s*:\s*true', reply.partition(b"\r\n\r\n")[2]) is not None
        return {"ok": sofa, "why": None if sofa else "not-sofa", "ip": ip,
                "message": "Sofa answers from the internet." if sofa else "Something answers there, but it isn't Sofa (%s)." % status_line[:60]}

    def relay_poll(self, data):
        self.box(data)
        wait = RELAY_WAIT if data.get("wait") is None else max(0.0, min(RELAY_WAIT, float(data["wait"])))
        return {"requests": self.relay.poll(str(data["id"]), wait),
                "base": "%s/r/%s" % (self.cfg["relay_base"].rstrip("/"), data["id"])}

    def relay_answer(self, data):
        self.box(data)
        a = data.get("answer") or {}
        ok = self.relay.answer(str(data["id"]), str(data.get("rid") or ""),
                               {"status": int(a.get("status") or 502), "headers": [list(h)[:2] for h in (a.get("headers") or [])][:20],
                                "body": str(a.get("body") or "")})
        return {"ok": ok}

    def report(self, data, client):
        """A box's report (Settings -> Help -> Send a report), kept for us to read. A box with an id signs it with
        its secret; one without (at home without the secure remote, say) is counted by its address."""
        text = str(data.get("report") or "")
        if not text.strip() or len(text) > self.cfg["report_max"]:
            raise Refused("That isn't a report.")
        who = "box-" + str(data["id"]) if data.get("id") else "ip-" + client
        if data.get("id"):
            self.box(data)
        now = self.now()
        with self.boxes.lock:
            self.reported = [(t, w) for t, w in self.reported if now - t < 86400]
            if sum(1 for _, w in self.reported if w == who) >= self.cfg["reports_per_day"]:
                raise Limit("This box sent a lot of reports today. Try again tomorrow.")
            self.reported.append((now, who))
        code = "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(6))
        folder = os.path.join(DIR, "reports")
        when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now))
        write_private(os.path.join(folder, "%s-%s.txt" % (time.strftime("%Y%m%d-%H%M%S", time.gmtime(now)), code)),
                      "Report %s, %s, from %s\n\n%s\n" % (code, when, data.get("id") or "a box with no id", text))
        kept = sorted(f for f in os.listdir(folder) if f.endswith(".txt"))
        for old in kept[:-self.cfg["reports_kept"]]:
            os.remove(os.path.join(folder, old))
        return {"ok": True, "report": code}


RELAY_WAIT, RELAY_ANSWER, RELAY_ONLINE = 25, 20, 45   # a box's wait for phones; a phone's for the box; "online"


class Relay:
    """Phones' requests to a box's remote, queued for the box's open request, and its answers back to them."""

    def __init__(self, now=time.time):
        self.cond, self.now = threading.Condition(), now
        self.queues, self.seen, self.answers, self.owner = {}, {}, {}, {}

    def online(self, box_id):
        return self.now() - self.seen.get(box_id, 0) < RELAY_ONLINE

    def poll(self, box_id, wait=RELAY_WAIT):
        """The box asking for what phones want of it: at once if something's waiting, else within `wait` seconds."""
        end = time.time() + wait
        with self.cond:
            self.seen[box_id] = self.now()
            while not self.queues.get(box_id) and time.time() < end:
                self.cond.wait(max(0.0, end - time.time()))
            q = self.queues.get(box_id, [])
            out, self.queues[box_id] = q[:16], q[16:]
            self.seen[box_id] = self.now()
            return out

    def ask(self, box_id, request, wait=RELAY_ANSWER):
        """A phone's request: the box's answer, or None if it's not online, or "late" if it didn't answer in time."""
        if not self.online(box_id):
            return None
        rid = secrets.token_hex(8)
        with self.cond:
            q = self.queues.setdefault(box_id, [])
            if len(q) >= 64:
                raise Limit("The box is busy. Try again in a moment.")
            q.append(dict(request, rid=rid))
            self.answers[rid], self.owner[rid] = None, box_id
            self.cond.notify_all()
            end = time.time() + wait
            while self.answers.get(rid) is None and time.time() < end:
                self.cond.wait(max(0.0, end - time.time()))
            answer = self.answers.pop(rid, None)
            self.owner.pop(rid, None)
            if answer is None:
                self.queues[box_id] = [r for r in self.queues.get(box_id, []) if r["rid"] != rid]
            return answer or "late"

    def answer(self, box_id, rid, answer):
        with self.cond:
            if self.owner.get(rid) != box_id or rid not in self.answers:
                return False                               # not its own, or the phone stopped waiting
            self.answers[rid] = answer
            self.cond.notify_all()
            return True


def remote_page():
    """The phone remote's page, served by this service itself (next to it once installed; in the repo, the box's)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "remote.html"), os.path.join(here, "..", "sofa-box", "remote.html")):
        try:
            with open(p, "rb") as f:
                return f.read()
        except OSError:
            continue
    return b"<!doctype html><title>Sofa Box</title><p>The remote isn't installed here."


class Refused(Exception):
    status = 403


class Limit(Exception):
    status = 429


class Handler(BaseHTTPRequestHandler):
    service = None
    protocol_version = "HTTP/1.1"
    timeout = 120

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), fmt % args))

    def client(self):
        peer = self.client_address[0]
        return (self.headers.get("CF-Connecting-IP") or peer) if peer in ("127.0.0.1", "::1") else peer

    def reply(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/r/"):
            return self.phone()
        if self.path == "/v1/ip":                         # a home's internet address, as the internet sees it
            return self.reply(200, {"ip": self.client()})
        if self.path == "/v1/health":
            return self.reply(200, {"ok": True, "base": self.service.cfg["base"]})
        self.reply(404, {"error": "Not here."})

    # -- the relay: a phone's side
    PHONE_PATHS = re.compile(r"^/(api/[a-z/]{1,40}|r/[0-9a-f]{24}|icon\.png|icon-512\.png|manifest\.json)$")
    PAGE_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")

    def raw(self, status, body, ctype, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def phone(self):
        parts = urllib.parse.urlsplit(self.path)
        m = re.match(r"^/r/([a-z2-9]{10})(/.*)?$", parts.path)
        if not m or m.group(1) not in self.service.boxes.data:
            return self.raw(404, b"Not here.", "text/plain; charset=utf-8")
        box_id, rest, base = m.group(1), m.group(2), "/r/%s/" % m.group(1)
        if rest is None:                                  # (relative links in the page need the slash)
            return self.raw(301, b"", "text/plain", [("Location", base + ("?" + parts.query if parts.query else ""))])
        if rest == "/" and self.command == "GET":         # the page: this service's own copy, never the box's
            return self.raw(200, remote_page(), "text/html; charset=utf-8", [("Content-Security-Policy", self.PAGE_CSP)])
        if not self.PHONE_PATHS.match(rest):
            return self.raw(404, b"Not here.", "text/plain; charset=utf-8")
        if rest == "/api/pair":                           # the TV's four digits: at home only (too few to be guessed at)
            return self.raw(403, json.dumps({"error": "Away from home, scan the code on the TV: typing it works at home only."}).encode(),
                            "application/json")
        size = int(self.headers.get("Content-Length") or 0)
        if size > 65536:
            return self.raw(413, b'{"error":"Too big."}', "application/json")
        body = self.rfile.read(size) if size else b""
        cookie = "; ".join(c.strip() for c in (self.headers.get("Cookie") or "").split(";") if c.strip().startswith("sofa_remote="))
        headers = {k: v for k, v in (("Cookie", cookie), ("Content-Type", self.headers.get("Content-Type")),
                                     ("X-Sofa-Remote", self.headers.get("X-Sofa-Remote")),
                                     ("User-Agent", (self.headers.get("User-Agent") or "")[:200])) if v}
        try:
            answer = self.service.relay.ask(box_id, {"method": self.command, "path": rest + ("?" + parts.query if parts.query else ""),
                                                      "headers": headers, "body": base64.b64encode(body).decode()})
        except Limit as exc:
            return self.raw(429, json.dumps({"error": str(exc)}).encode(), "application/json")
        if answer is None or answer == "late":
            msg = "The Sofa Box isn't online right now." if answer is None else "The Sofa Box didn't answer in time."
            return self.raw(503 if answer is None else 504, json.dumps({"error": msg, "offline": answer is None}).encode(), "application/json")
        try:
            data = base64.b64decode(answer.get("body") or "")
        except ValueError:
            data = b""
        out = []
        for k, v in answer.get("headers") or []:
            k, v = str(k), str(v)
            if k.lower() == "set-cookie" and v.startswith("sofa_remote="):   # the phone's sign-in: for this box's path only
                out.append(("Set-Cookie", re.sub(r"(?i);\s*Path=[^;]*", "", v) + "; Path=%s; Secure" % base))
            elif k.lower() == "location" and v.startswith("/") and not v.startswith("//"):
                out.append(("Location", base + v.lstrip("/")))
        ctype = ("image/png" if rest.endswith(".png") else "application/manifest+json" if rest.endswith(".json")
                 else "text/plain; charset=utf-8" if rest.startswith("/r/") else "application/json")
        out.append(("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"))
        return self.raw(answer.get("status") or 502, data, ctype, out)

    def do_POST(self):
        if self.path.startswith("/r/"):
            return self.phone()
        size = int(self.headers.get("Content-Length") or 0)
        limit = 3 * self.service.cfg["report_max"] if self.path == "/v1/report" else 4 * 1024 * 1024 if self.path == "/v1/relay/answer" else 16384
        if size > limit:
            return self.reply(413, {"error": "Too big."})
        try:
            data = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            return self.reply(400, {"error": "Not JSON."})
        route = {"/v1/register": lambda: self.service.register(self.client()), "/v1/address": lambda: self.service.address(data),
                 "/v1/cert": lambda: self.service.cert(data), "/v1/report": lambda: self.service.report(data, self.client()),
                 "/v1/reach": lambda: self.service.reach(data, self.client()),
                 "/v1/relay/poll": lambda: self.service.relay_poll(data),
                 "/v1/relay/answer": lambda: self.service.relay_answer(data)}.get(self.path)
        if not route:
            return self.reply(404, {"error": "Not here."})
        try:
            return self.reply(200, route())
        except (Refused, Limit) as exc:
            return self.reply(exc.status, {"error": str(exc)})
        except CertError as exc:
            self.log_message("%s: %s", self.path, exc)
            return self.reply(502, {"error": "The certificate couldn't be made now; the box tries again later."})


def build(cfg, staging=False):
    dns = Cloudflare(cloudflare_token(), cfg["zone"], cfg["cloudflare_api"], cfg["doh"], cfg["settle"])
    url = cfg["acme_staging"] if staging else cfg["acme"]
    acme = Acme(url, os.path.join(DIR, "account-staging.key" if staging else "account.key"), cfg["email"], cfg["acme_ca"])
    return dns, acme


def serve(cfg):
    dns, acme = build(cfg)
    Handler.service = Service(cfg, dns, acme)
    host, port = cfg["listen"].rsplit(":", 1)
    server = ThreadingHTTPServer((host, int(port)), Handler)
    server.daemon_threads = True
    print("Sofa Box certificates for *.%s on http://%s (Ctrl+C stops)" % (cfg["base"], cfg["listen"]), file=sys.stderr, flush=True)
    server.serve_forever()


def check(cfg):
    ok = True

    def say(good, text):
        nonlocal ok
        ok = ok and good
        print(("  ok   " if good else "  NO   ") + text)
    try:
        say(True, "openssl: " + openssl(["version"]).decode().strip())
    except CertError as exc:
        say(False, str(exc))
    try:
        dns, acme = build(cfg)
        say(True, "Cloudflare token found")
        say(True, "Cloudflare zone %s: %s" % (cfg["zone"], dns.zone_id()))
        say(bool(dns.records(cfg["base"], "A") is not None), "Cloudflare DNS records readable for %s" % cfg["base"])
        say("newOrder" in acme.directory(), "Let's Encrypt answers (%s)" % cfg["acme"])
    except CertError as exc:
        say(False, str(exc))
    print("All good." if ok else "Something to fix (above).")
    return 0 if ok else 1


def try_staging(cfg):
    """A real run against Let's Encrypt's staging (its certificates aren't trusted; nothing counts against the limits)."""
    dns, acme = build(cfg, staging=True)
    name = "test-%s.%s" % (secrets.token_hex(3), cfg["base"])
    work = os.path.join(DIR, "try")
    os.makedirs(work, exist_ok=True)
    key = os.path.join(work, "key.pem")
    openssl(["req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
             "-pkeyopt", "ec_param_enc:named_curve",  # LibreSSL (macOS) writes the curve out in full otherwise; Let's Encrypt refuses that
             "-nodes", "-keyout", key, "-out", os.path.join(work, "csr.pem"), "-subj", "/CN=" + name])
    with open(os.path.join(work, "csr.pem"), "rb") as f:
        der = openssl(["req", "-outform", "DER"], f.read())
    print("Asking Let's Encrypt (staging) for %s; about a minute…" % name)
    chain = acme.issue(der, dns)
    with open(os.path.join(work, "cert.pem"), "w") as f:
        f.write(chain)
    print("Got it, until %s: %s" % (time.strftime("%Y-%m-%d", time.gmtime(not_after(chain))), os.path.join(work, "cert.pem")))
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "serve"
    cfg = config()
    try:
        if cmd == "serve":
            return serve(cfg)
        if cmd == "check":
            return check(cfg)
        if cmd == "try":
            return try_staging(cfg)
    except CertError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv) or 0)
