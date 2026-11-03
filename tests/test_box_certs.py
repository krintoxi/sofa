"""The Sofa Box certificate service (deploy/box-certs): boxes register, get a name pointed at their home address,
and certificates for exactly that name; Cloudflare's API and Let's Encrypt are stood in for (the whole thing
against Let's Encrypt's own test server, Pebble, is in deploy/box-certs/README.md)."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAVE_OPENSSL = shutil.which("openssl") is not None


def load(conf_dir):
    os.environ["SOFA_CERTS_DIR"] = conf_dir
    spec = importlib.util.spec_from_file_location("sofa_box_certs", os.path.join(HERE, "deploy", "box-certs", "sofa-box-certs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCA:
    """A certificate authority of our own, for the stand-in Let's Encrypt (and the box tests)."""

    def __init__(self, folder):
        self.dir = folder
        self.key, self.cert = os.path.join(folder, "ca.key"), os.path.join(folder, "ca.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", self.key, "-out", self.cert, "-days", "2",
                        "-subj", "/CN=Sofa test CA", "-addext", "basicConstraints=critical,CA:TRUE",
                        "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-addext", "subjectKeyIdentifier=hash"],
                       check=True, capture_output=True)

    def sign(self, csr_pem, days=90):
        """A server certificate for the request's name (as Let's Encrypt would make it)."""
        work = tempfile.mkdtemp(dir=self.dir)
        csr, ext, out = (os.path.join(work, n) for n in ("csr.pem", "ext.cnf", "cert.pem"))
        with open(csr, "w") as f:
            f.write(csr_pem if isinstance(csr_pem, str) else csr_pem.decode())
        text = subprocess.run(["openssl", "req", "-in", csr, "-noout", "-text"], capture_output=True, text=True, check=True).stdout
        name = text.split("DNS:")[1].split()[0].strip(",") if "DNS:" in text else text.split("CN = ")[1].split()[0]
        with open(ext, "w") as f:
            f.write("subjectAltName=DNS:%s\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n"
                    "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n" % name)   # (newer Pythons insist)
        subprocess.run(["openssl", "x509", "-req", "-in", csr, "-CA", self.cert, "-CAkey", self.key, "-CAcreateserial",
                        "-out", out, "-days", str(days), "-extfile", ext], check=True, capture_output=True)
        with open(out) as f:
            return f.read()


class FakeAcme:
    def __init__(self, ca):
        self.ca, self.asked = ca, []

    def issue(self, csr_der, dns):
        pem = subprocess.run(["openssl", "req", "-inform", "DER"], input=csr_der, capture_output=True, check=True).stdout.decode()
        name = sorted(certs.csr_names(pem))[0]
        dns.set_txt("_acme-challenge." + name, "proof")
        dns.clear_txt("_acme-challenge." + name)
        self.asked.append(name)
        return self.ca.sign(pem)


class FakeCloudflareAPI(BaseHTTPRequestHandler):
    """Cloudflare's API, for one zone, in memory."""
    records, calls = {}, []

    def log_message(self, *args):
        pass

    def out(self, result, ok=True, status=200):
        body = json.dumps({"success": ok, "errors": [] if ok else [{"message": "no"}], "result": result}).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if self.headers.get("Authorization") != "Bearer test-token":
            self.out(None, False, 403)
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/zones":
            return self.out([{"id": "z1"}] if q.get("name") == "edgeventure.uk" else [])
        self.out([r for r in self.records.values() if r["type"] == q.get("type") and r["name"] == q.get("name")])

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))

    def do_POST(self):
        if self.authorized():
            b = self.body()
            b["id"] = str(len(self.calls) + 1)
            self.records[b["id"]] = b
            self.calls.append(("POST", b["type"], b["name"], b["content"]))
            self.out(b)

    def do_PUT(self):
        if self.authorized():
            b = self.body()
            b["id"] = self.path.rsplit("/", 1)[1]
            self.records[b["id"]] = b
            self.calls.append(("PUT", b["type"], b["name"], b["content"]))
            self.out(b)

    def do_DELETE(self):
        if self.authorized():
            r = self.records.pop(self.path.rsplit("/", 1)[1], None)
            self.calls.append(("DELETE", r and r["type"], r and r["name"], None))
            self.out({})


certs = None


@unittest.skipUnless(HAVE_OPENSSL, "needs the openssl command")
class BoxCerts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global certs
        cls.dir = tempfile.mkdtemp()
        certs = cls.certs = load(cls.dir)
        cls.ca = TestCA(cls.dir)
        cls.cf = ThreadingHTTPServer(("127.0.0.1", 0), FakeCloudflareAPI)
        threading.Thread(target=cls.cf.serve_forever, daemon=True).start()
        cls.cf_url = "http://127.0.0.1:%d" % cls.cf.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.cf.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        FakeCloudflareAPI.records.clear()
        del FakeCloudflareAPI.calls[:]
        self.clock = [time.time()]                                                # (the stand-in certificates use the real date)
        self.cfg = dict(self.certs.DEFAULTS, cloudflare_api=self.cf_url, doh="", settle=0)
        self.dns = self.certs.Cloudflare("test-token", "edgeventure.uk", self.cf_url, "", 0)
        self.acme = FakeAcme(self.ca)
        try:
            os.remove(os.path.join(self.dir, "boxes.json"))
        except FileNotFoundError:
            pass
        self.service = self.certs.Service(self.cfg, self.dns, self.acme, now=lambda: self.clock[0])

    def csr(self, name):
        key = os.path.join(self.dir, "box.key")
        return subprocess.run(["openssl", "req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                               "-keyout", key, "-subj", "/CN=" + name, "-addext", "subjectAltName=DNS:" + name],
                              capture_output=True, text=True, check=True).stdout

    def test_a_box_gets_its_name_and_certificate(self):
        box = self.service.register("203.0.113.5")
        self.assertRegex(box["id"], r"^[a-z2-9]{10}$")
        self.assertEqual(box["name"], box["id"] + ".box.edgeventure.uk")
        with open(os.path.join(self.dir, "boxes.json")) as f:
            self.assertNotIn(box["secret"], f.read())                                # only its hash is kept
        self.assertEqual(oct(os.stat(os.path.join(self.dir, "boxes.json")).st_mode & 0o777), "0o600")
        out = self.service.address(dict(box, ip="192.168.1.30"))
        self.assertEqual(out["ip"], "192.168.1.30")
        self.assertIn(("POST", "A", box["name"], "192.168.1.30"), FakeCloudflareAPI.calls)
        a = [r for r in FakeCloudflareAPI.records.values() if r["type"] == "A"][0]
        self.assertFalse(a["proxied"])                                               # DNS only: Cloudflare can't proxy a home address
        got = self.service.cert(dict(box, csr=self.csr(box["name"])))
        self.assertIn("BEGIN CERTIFICATE", got["cert"])
        self.assertGreater(got["expires"], self.clock[0])
        self.assertEqual(self.acme.asked, [box["name"]])
        self.assertEqual([r for r in FakeCloudflareAPI.records.values() if r["type"] == "TXT"], [])   # the proof is cleared

    def test_only_its_own_name_and_only_with_its_secret(self):
        box = self.service.register("203.0.113.5")
        other = self.service.register("203.0.113.6")
        with self.assertRaises(self.certs.Refused):
            self.service.cert(dict(box, csr=self.csr(other["name"])))
        with self.assertRaises(self.certs.Refused):
            self.service.cert(dict(box, csr=self.csr("www.edgeventure.uk")))
        with self.assertRaises(self.certs.Refused):
            self.service.address(dict(box, secret="nope", ip="192.168.1.30"))
        with self.assertRaises(self.certs.Refused):
            self.service.cert(dict(box, csr="not a request"))
        self.assertEqual(self.acme.asked, [])

    def test_only_home_addresses(self):
        box = self.service.register("203.0.113.5")
        for ip in ("8.8.8.8", "127.0.0.1", "169.254.1.1", "0.0.0.0", "192.168.1.300", "fe80::1", "edgeventure.uk"):
            with self.assertRaises(self.certs.Refused, msg=ip):
                self.service.address(dict(box, ip=ip))
        for ip in ("192.168.0.5", "10.0.0.9", "172.20.1.2"):
            self.service.address(dict(box, ip=ip))
        self.assertEqual([c[3] for c in FakeCloudflareAPI.calls], ["192.168.0.5", "10.0.0.9", "172.20.1.2"])

    def test_the_same_address_isnt_sent_to_cloudflare_again(self):
        box = self.service.register("203.0.113.5")
        self.service.address(dict(box, ip="192.168.1.30"))
        self.service.address(dict(box, ip="192.168.1.30"))
        self.assertEqual(len(FakeCloudflareAPI.calls), 1)
        self.clock[0] += 13 * 3600                                                  # but twice a day it makes sure
        self.service.address(dict(box, ip="192.168.1.30"))
        self.assertEqual(len(FakeCloudflareAPI.calls), 1)                         # (Cloudflare had it already: no change)

    def test_limits(self):
        for _ in range(10):
            self.service.register("203.0.113.5")
        with self.assertRaises(self.certs.Limit):
            self.service.register("203.0.113.5")
        self.service.register("203.0.113.6")                                       # someone else still can
        box = self.service.register("203.0.113.7")
        self.service.cert(dict(box, csr=self.csr(box["name"])))
        with self.assertRaises(self.certs.Limit):                                  # one a week while it's fresh
            self.service.cert(dict(box, csr=self.csr(box["name"])))
        self.clock[0] += 75 * 86400                                                # weeks before it runs out: again
        self.service.cert(dict(box, csr=self.csr(box["name"])))
        self.cfg["new_per_week"] = 1                                               # Let's Encrypt's weekly limit for new names
        newer = self.service.register("203.0.113.8")
        self.service.cert(dict(newer, csr=self.csr(newer["name"])))               # the week's one new box
        newest = self.service.register("203.0.113.9")
        with self.assertRaises(self.certs.Limit):
            self.service.cert(dict(newest, csr=self.csr(newest["name"])))
        self.clock[0] += 8 * 86400                                                 # next week
        self.service.cert(dict(newest, csr=self.csr(newest["name"])))

    def test_reports(self):
        folder = os.path.join(self.dir, "reports")
        shutil.rmtree(folder, ignore_errors=True)
        box = self.service.register("203.0.113.5")
        out = self.service.report(dict(box, report="Sofa Box OS 1.1.7\nthe checks"), "203.0.113.5")
        self.assertRegex(out["report"], r"^[A-Z2-9]{6}$")                        # the code the TV shows, to ask about it
        (name,) = os.listdir(folder)
        self.assertTrue(name.endswith(out["report"] + ".txt"))
        self.assertEqual(os.stat(os.path.join(folder, name)).st_mode & 0o777, 0o600)
        with open(os.path.join(folder, name)) as f:
            self.assertIn("from %s" % box["id"], f.read())
        with self.assertRaises(self.certs.Refused):                               # only with its secret
            self.service.report(dict(box, secret="nope", report="x"), "203.0.113.5")
        with self.assertRaises(self.certs.Refused):
            self.service.report(dict(box, report=""), "203.0.113.5")
        with self.assertRaises(self.certs.Refused):
            self.service.report(dict(box, report="x" * (self.cfg["report_max"] + 1)), "203.0.113.5")
        self.service.report({"report": "a box with no id"}, "198.51.100.1")       # counted by its address
        for _ in range(9):
            self.service.report(dict(box, report="again"), "203.0.113.5")
        with self.assertRaises(self.certs.Limit):                                  # ten a day
            self.service.report(dict(box, report="again"), "203.0.113.5")
        self.service.report({"report": "someone else"}, "203.0.113.5")            # (a box with no id, on the same address)
        self.cfg["reports_kept"] = 3
        self.clock[0] += 86400
        self.service.report(dict(box, report="tomorrow"), "203.0.113.5")
        self.assertEqual(len(os.listdir(folder)), 3)                               # the newest few hundred are kept

    def test_over_http(self):
        self.certs.Handler.service = self.service
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.certs.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % server.server_address[1]

        def post(path, body, headers=None):
            req = urllib.request.Request(base + path, json.dumps(body).encode(), dict({"Content-Type": "application/json"}, **(headers or {})))
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            with urllib.request.urlopen(base + "/v1/health", timeout=10) as r:
                self.assertEqual(json.loads(r.read())["base"], "box.edgeventure.uk")
            for _ in range(10):                                                    # behind the tunnel: the real address counts
                self.assertEqual(post("/v1/register", {}, {"CF-Connecting-IP": "198.51.100.9"})[0], 200)
            self.assertEqual(post("/v1/register", {}, {"CF-Connecting-IP": "198.51.100.9"})[0], 429)
            status, box = post("/v1/register", {}, {"CF-Connecting-IP": "198.51.100.10"})
            self.assertEqual(status, 200)
            self.assertEqual(post("/v1/address", dict(box, ip="8.8.8.8"))[0], 403)
            status, out = post("/v1/cert", dict(box, csr=self.csr(box["name"])))
            self.assertEqual(status, 200)
            self.assertIn("BEGIN CERTIFICATE", out["cert"])
            status, out = post("/v1/report", dict(box, report="line\n" * 20000))       # bigger than the other requests
            self.assertEqual((status, len(out["report"])), (200, 6))
            self.assertEqual(post("/v1/address", dict(box, ip="10.0.0.2", pad="x" * 20000))[0], 413)
            self.assertEqual(post("/v1/nothing", {})[0], 404)
        finally:
            server.shutdown()
            server.server_close()

    def test_the_lets_encrypt_account_key(self):
        acme = self.certs.Acme("http://127.0.0.1:9/dir", os.path.join(self.dir, "account.key"))
        modulus = subprocess.run(["openssl", "rsa", "-in", acme.key_path, "-noout", "-modulus"], capture_output=True, text=True,
                                 check=True).stdout.strip().split("=")[1]
        import base64
        n = base64.urlsafe_b64decode(acme.jwk["n"] + "==")
        self.assertEqual(n.hex().upper(), modulus.upper().lstrip("0") if modulus.startswith("00") else modulus.upper())
        self.assertEqual(acme.jwk["e"], "AQAB")
        self.assertEqual(oct(os.stat(acme.key_path).st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
