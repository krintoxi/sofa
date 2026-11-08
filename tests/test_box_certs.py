"""The Sofa Box certificate service (deploy/box-certs): boxes register, get a name pointed at their home address,
and certificates for exactly that name; Cloudflare's API and Let's Encrypt are stood in for (the whole thing
against Let's Encrypt's own test server, Pebble, is in deploy/box-certs/README.md)."""
import importlib.util
import json
import os
import shutil
import socket
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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


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

    def test_a_box_brings_its_own_id(self):
        """Made at its first start, offline: its phone remote's address through the relay is known at its setup."""
        own = {"id": "ab2cd3ef4g", "secret": "5e" * 24}
        box = self.service.register("203.0.113.5", own)
        self.assertEqual((box["id"], box["secret"]), (own["id"], own["secret"]))
        self.service.box(own)                                                     # (its secret works)
        same = self.service.register("203.0.113.5", own)                          # asked again (the answer got lost)
        self.assertEqual((same["id"], same["secret"]), (own["id"], own["secret"]))
        again = self.service.register("203.0.113.6", dict(own, secret="6f" * 24))  # taken, by another: a new one
        self.assertNotEqual(again["id"], own["id"])
        self.assertNotEqual(again["secret"], own["secret"])
        for odd in ({"id": "ABCDEFGHJK", "secret": "5e" * 24}, {"id": "ab2cd3ef4l", "secret": "5e" * 24},
                    {"id": "zz2cd3ef4g", "secret": "short"}):
            self.assertNotEqual(self.service.register("203.0.113.7", odd)["id"], odd["id"])

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
        for _ in range(25):                                                        # card after card from one home: no limit
            self.service.register("203.0.113.5")
        self.service.made = []                                                     # (another day)
        self.cfg.update(register_per_ip_day=3, register_per_day=6)                 # limits, for whoever sets them
        own = {"id": "cd2ef3gh4j", "secret": "7a" * 24}
        self.service.register("203.0.113.5", own)
        for _ in range(4):
            self.assertEqual(self.service.register("203.0.113.5", own)["id"], own["id"])   # asking again isn't a new box
        self.service.register("203.0.113.5")
        self.service.register("203.0.113.5")
        with self.assertRaises(self.certs.Limit):                                  # three from one address
            self.service.register("203.0.113.5")
        for n in range(3):
            self.service.register("203.0.113.%d" % (20 + n))
        with self.assertRaises(self.certs.Limit):                                  # six for the whole service
            self.service.register("203.0.113.30")
        self.cfg.update(register_per_ip_day=0, register_per_day=5000)
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

    def test_the_relay(self):
        """A phone's requests to /r/<box>/ reach the box through its open request and its answers come back; the page
        is the service's own; the phone's sign-in is kept to the box's path; four digits are refused; an offline box
        says so."""
        import base64
        self.certs.Handler.service = self.service
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.certs.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        box = self.service.register("203.0.113.5")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

        def phone(path, body=None, headers=None):
            req = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode(),
                                         dict({"Content-Type": "application/json", "X-Sofa-Remote": "1"}, **(headers or {})))
            try:
                with opener.open(req, timeout=30) as r:
                    return r.status, dict(r.headers), r.read()
            except urllib.error.HTTPError as e:
                return e.code, dict(e.headers), e.read()
        seen, stop = [], threading.Event()

        def the_box():                                    # a box: asks, answers like its remote would
            while not stop.is_set():
                got = self.service.relay_poll(dict(box, wait=1))
                for req in got["requests"]:
                    seen.append(req)
                    if req["path"].startswith("/r/"):
                        answer = {"status": 302, "headers": [["Location", "/"], ["Set-Cookie", "sofa_remote=" + "a" * 48 + "; Path=/; HttpOnly"],
                                                             ["X-Other", "dropped"]], "body": ""}
                    else:
                        answer = {"status": 200, "headers": [], "body": base64.b64encode(b'{"ok":true,"paired":true}').decode()}
                    self.service.relay_answer(dict(box, rid=req["rid"], answer=answer))
        try:
            status, _, _ = phone("/r/%s/api/state" % box["id"])
            self.assertEqual(status, 503)                                              # not online yet: says so
            t = threading.Thread(target=the_box, daemon=True)
            t.start()
            time.sleep(0.3)
            status, headers, page = phone("/r/%s" % box["id"])
            self.assertEqual((status, headers["Location"]), (301, "/r/%s/" % box["id"]))
            status, headers, page = phone("/r/%s/" % box["id"])
            self.assertEqual(status, 200)
            self.assertIn(b"<title>", page)                                            # the service's own page
            self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
            self.assertEqual(seen, [])                                                 # (the box wasn't asked for it)
            status, headers, _ = phone("/r/%s/r/%s" % (box["id"], "0123456789abcdef01234567"))
            self.assertEqual(status, 302)
            self.assertEqual(headers["Location"], "/r/%s/" % box["id"])                 # back to this box's page
            self.assertIn("Path=/r/%s/; Secure" % box["id"], headers["Set-Cookie"])     # the sign-in: this box's path only
            self.assertNotIn("X-Other", headers)
            self.assertEqual(seen[-1]["headers"].get("Cookie"), None)
            status, headers, body = phone("/r/%s/api/key" % box["id"], {"k": "up"}, {"Cookie": "sofa_remote=%s; other=x" % ("a" * 48)})
            self.assertEqual((status, json.loads(body)["ok"]), (200, True))
            self.assertEqual(headers["Content-Type"], "application/json")               # data, never a page from the box
            self.assertEqual(seen[-1]["headers"]["Cookie"], "sofa_remote=" + "a" * 48)  # only the remote's own cookie
            self.assertEqual(json.loads(base64.b64decode(seen[-1]["body"])), {"k": "up"})
            self.assertEqual(phone("/r/%s/r/1234" % box["id"])[0], 404)                  # four digits: not through here
            self.assertEqual(phone("/r/%s/api/pair" % box["id"], {"code": "1234"})[0], 403)
            self.assertEqual(phone("/r/%s/evil.html" % box["id"])[0], 404)
            self.assertEqual(phone("/r/nobodyhere/")[0], 404)
            with self.assertRaises(self.certs.Refused):                                # a box answers with its secret
                self.service.relay_poll(dict(box, secret="nope"))
        finally:
            stop.set()
            server.shutdown()
            server.server_close()

    def test_an_odd_size_is_too_big(self):
        """Content-Length: -1 would read until the connection closes (a thread held for minutes): refused as too big."""
        for odd in ("-1", "abc", "1e9"):
            self.assertGreater(self.certs.content_length({"Content-Length": odd}), 4 * 1024 * 1024, odd)
        self.assertEqual(self.certs.content_length({}), 0)
        self.assertEqual(self.certs.content_length({"Content-Length": "120"}), 120)

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
            for _ in range(12):                                                    # one home, card after card: all taken
                self.assertEqual(post("/v1/register", {}, {"CF-Connecting-IP": "198.51.100.9"})[0], 200)
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
            req = urllib.request.Request(base + "/v1/ip", headers={"CF-Connecting-IP": "198.51.100.7"})
            with urllib.request.urlopen(req, timeout=10) as r:                     # Check from outside: the home's address
                self.assertEqual(json.loads(r.read()), {"ip": "198.51.100.7"})
        finally:
            server.shutdown()
            server.server_close()

    def test_the_outside_check(self):
        class FakeSofa(BaseHTTPRequestHandler):
            answer = b'{"sofa": true, "name": "Sofa"}'

            def do_GET(self):
                self.send_response(200 if self.path == "/api/info" else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(self.answer)))
                self.end_headers()
                self.wfile.write(self.answer)

            def log_message(self, *a):
                pass
        sofa = ThreadingHTTPServer(("127.0.0.1", 0), FakeSofa)
        threading.Thread(target=sofa.serve_forever, daemon=True).start()
        spare = socket.socket()
        spare.bind(("127.0.0.1", 0))
        port, closed = sofa.server_address[1], spare.getsockname()[1]
        spare.close()
        sock = self.certs.socket
        real_lookup, real_connect = sock.getaddrinfo, sock.create_connection
        homes = {"sofa.example.com": "8.8.8.8", "home.example.com": "192.168.1.20"}

        def lookup(host, port_, *a, **k):              # (names here stand for ones on the internet; no real lookups:
            if host in homes:                          # on a Mac they leave threads that crash the tests' later forks)
                return [(sock.AF_INET, sock.SOCK_STREAM, 6, "", (homes[host], port_))]
            if host == "127.0.0.1":                    # (create_connection's own lookup: no DNS for a number)
                return real_lookup(host, port_, *a, **k)
            raise sock.gaierror(8, "nodename nor servname provided, or not known")

        def connect(address, timeout=None, *a, **k):
            return real_connect(("127.0.0.1", address[1]) if address[0] == "8.8.8.8" else address, timeout)
        sock.getaddrinfo, sock.create_connection = lookup, connect
        reach = lambda url, who="198.51.100.4": self.service.reach({"url": url}, who)
        try:
            for bad in ("ftp://sofa.example.com", "https://me:pw@sofa.example.com", "nothing"):
                with self.assertRaises(self.certs.Refused):
                    reach(bad)
            out = reach("http://sofa.example.com:%d" % port)
            self.assertEqual((out["ok"], out["ip"]), (True, "8.8.8.8"))
            self.assertEqual(reach("http://home.example.com")["why"], "private")       # never a home address
            self.assertEqual(reach("http://nowhere.invalid")["why"], "name")
            self.assertEqual(reach("http://sofa.example.com:%d" % closed)["why"], "closed")
            self.assertEqual(reach("https://sofa.example.com:%d" % port)["why"], "certificate")
            FakeSofa.answer = b"<html>Router login</html>"
            self.assertEqual(reach("http://sofa.example.com:%d" % port)["why"], "not-sofa")
            for _ in range(self.cfg["reach_per_hour"] - 6):     # (six so far: a refused address doesn't count)
                reach("http://home.example.com")
            with self.assertRaises(self.certs.Limit):                                  # a few times an hour
                reach("http://home.example.com")
            self.assertEqual(reach("http://home.example.com", "198.51.100.5")["why"], "private")
        finally:
            sock.getaddrinfo, sock.create_connection = real_lookup, real_connect
            sofa.shutdown()
            sofa.server_close()

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
