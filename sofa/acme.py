"""Free HTTPS certificates from Let's Encrypt (the ACME protocol, RFC 8555), standard library only.

Let's Encrypt checks that you control the domain by fetching a token from
http://<domain>/.well-known/acme-challenge/<token>: Sofa answers it on its normal port (the router
sends port 80 there). The certificate lasts 90 days; tls.py renews it a month before it ends.

Tested against Pebble, Let's Encrypt's own test server (tests/test_https.py).
"""
import base64
import hashlib
import json
import time
import urllib.error
import urllib.request

from . import rsakey

LETS_ENCRYPT = "https://acme-v02.api.letsencrypt.org/directory"
LETS_ENCRYPT_STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"
challenges = {}            # token -> key authorization, served by web.py while Let's Encrypt looks


class AcmeError(Exception):
    pass


def b64(data):
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Client:
    def __init__(self, account_key, directory=LETS_ENCRYPT, context=None, opener=None):
        self.key, self.context = account_key, context
        self.open = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout, context=context))
        self.dir = self._json(self._request(directory)[0])
        self.kid, self.nonce = None, None

    def _request(self, url, data=None, method=None):
        headers = {"User-Agent": "Sofa", "Content-Type": "application/jose+json"}
        req = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data is not None else "GET"))
        try:
            with self.open(req, 30) as r:
                return r.read(), r.headers, r.status
        except urllib.error.HTTPError as e:
            body = e.read()
            if e.headers.get("Replay-Nonce"):
                self.nonce = e.headers["Replay-Nonce"]
            try:
                problem = json.loads(body.decode("utf-8"))
            except ValueError:
                problem = {"detail": body.decode("utf-8", "replace")[:200]}
            raise AcmeError("%s: %s" % (problem.get("type", e.code), problem.get("detail", "")), problem) from None

    @staticmethod
    def _json(body):
        return json.loads(body.decode("utf-8")) if body else {}

    def _nonce(self):
        if self.nonce:
            n, self.nonce = self.nonce, None
            return n
        return self._request(self.dir["newNonce"], method="HEAD")[1]["Replay-Nonce"]

    def post(self, url, payload, retry=True):
        """A signed request (payload None: "POST-as-GET")."""
        protected = {"alg": "RS256", "nonce": self._nonce(), "url": url}
        if self.kid:
            protected["kid"] = self.kid
        else:
            protected["jwk"] = rsakey.jwk(self.key)
        p64 = b64(json.dumps(protected))
        body64 = "" if payload is None else b64(json.dumps(payload))
        jws = {"protected": p64, "payload": body64, "signature": b64(rsakey.sign(self.key, (p64 + "." + body64).encode()))}
        try:
            body, headers, status = self._request(url, json.dumps(jws).encode())
        except AcmeError as e:
            if retry and "badNonce" in str(e):          # a stale nonce: one more go with a fresh one
                return self.post(url, payload, retry=False)
            raise
        self.nonce = headers.get("Replay-Nonce")
        return body, headers

    def thumbprint(self):
        jwk = rsakey.jwk(self.key)
        return b64(hashlib.sha256(json.dumps({"e": jwk["e"], "kty": "RSA", "n": jwk["n"]}, separators=(",", ":"),
                                             sort_keys=True).encode()).digest())

    def account(self, email=None):
        payload = {"termsOfServiceAgreed": True}
        if email:
            payload["contact"] = ["mailto:" + email]
        _, headers = self.post(self.dir["newAccount"], payload)
        self.kid = headers["Location"]

    def _wait(self, url, done=("valid",), failed=("invalid",), timeout=120):
        end = time.time() + timeout
        while True:
            body, _ = self.post(url, None)
            obj = self._json(body)
            if obj.get("status") in done:
                return obj
            if obj.get("status") in failed:
                raise AcmeError(_why(obj), obj)
            if time.time() > end:
                raise AcmeError("Let's Encrypt took too long (%s)" % obj.get("status"))
            time.sleep(2)

    def certificate(self, names, cert_key, csr_der, step=lambda text: None):
        """Ask for a certificate for `names` (domains), proving control over HTTP; returns the PEM chain."""
        step("Asking Let's Encrypt for a certificate")
        body, headers = self.post(self.dir["newOrder"], {"identifiers": [{"type": "dns", "value": n} for n in names]})
        order, order_url = self._json(body), headers["Location"]
        for authz_url in order["authorizations"]:
            authz = self._json(self.post(authz_url, None)[0])
            if authz.get("status") == "valid":
                continue
            ch = next((c for c in authz["challenges"] if c["type"] == "http-01"), None)
            if not ch:
                raise AcmeError("Let's Encrypt didn't offer the web check (http-01)")
            challenges[ch["token"]] = ch["token"] + "." + self.thumbprint()
            try:
                step("Let's Encrypt is checking that %s reaches this computer" % authz["identifier"]["value"])
                self.post(ch["url"], {})
                self._wait(authz_url)
            finally:
                challenges.pop(ch["token"], None)
        step("Getting the certificate")
        self.post(order["finalize"], {"csr": b64(csr_der)})
        order = self._wait(order_url, failed=("invalid",))
        return self.post(order["certificate"], None)[0].decode("utf-8")


def _why(obj):
    """Let's Encrypt's reason in plain words, as far as it says."""
    for ch in obj.get("challenges") or []:
        err = ch.get("error") or {}
        if err:
            detail = err.get("detail", "")
            if "connection" in detail.lower() or "timeout" in detail.lower():
                return ("Let's Encrypt couldn't reach this computer at your address (%s). Check that the router sends "
                        "port 80 to this computer, and that the domain points at your home's internet address." % detail[:160])
            return detail[:300]
    err = obj.get("error") or {}
    return err.get("detail") or "Let's Encrypt said no (%s)" % obj.get("status")
