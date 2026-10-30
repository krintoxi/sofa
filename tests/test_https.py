"""HTTPS: Sofa's own certificates, a certificate from Let's Encrypt's test server (Pebble), the HTTPS
listener, and never a password in the clear from the internet.

The Let's Encrypt test needs Pebble (go install github.com/letsencrypt/pebble/v2/cmd/pebble@v2.6.0) and
its source folder (for its test certificates): PEBBLE=/path/to/pebble PEBBLE_DIR=/path/to/pebble-source,
and "sofa.test" pointing at 127.0.0.1 in /etc/hosts. Without them that test is skipped."""
import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

import tests
from sofa import auth, config, der, rsakey, tls, web, x509

assert tests.ROOT


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Crypto(unittest.TestCase):
    def test_keys_requests_and_certificates(self):
        key = rsakey.generate()
        self.assertEqual(rsakey.from_pem(rsakey.to_pem(key)), key)
        self.assertTrue(rsakey.verify(key["n"], key["e"], b"hello", rsakey.sign(key, b"hello")))
        cert = x509.self_signed(key, ["imac.local", "192.168.1.20"])
        info = x509.info(cert)
        self.assertEqual(info["names"], ["imac.local", "192.168.1.20"])
        self.assertGreater(info["not_after"], time.time() + 700 * 86400)
        req = der.children(der.parse(x509.csr(key, ["sofa.example.com"]))[1])
        self.assertTrue(rsakey.verify(key["n"], key["e"], der.tlv(0x30, req[0][1]), req[2][1][1:]))   # signed by its key


class Listener(unittest.TestCase):
    """Sofa's own certificate and the HTTPS listener; plain HTTP from the internet is turned away."""

    def setUp(self):
        self.port = free_port()
        config.update({"https": "self", "https_port": self.port})
        self.assertIsNotNone(tls.context())                 # makes Sofa's own certificate
        self.httpd = tls._make_server()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        config.update({"https": "off", "https_port": 8443})

    def test_https_answers_with_sofas_own_certificate(self):
        ctx = ssl.create_default_context(cafile=tls.SELF_CERT)
        ctx.check_hostname = False                          # its names are this computer's, not 127.0.0.1's alias
        with urllib.request.urlopen("https://127.0.0.1:%d/api/info" % self.port, context=ctx, timeout=10) as r:
            self.assertTrue(json.loads(r.read())["sofa"])
            self.assertIsNone(r.headers.get("Strict-Transport-Security"))   # not for a certificate browsers ask about

    def test_internet_gets_no_plain_http(self):
        http = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        real = auth.network_of
        auth.network_of = lambda ip: "internet"              # as if from outside the house
        config.update({"remote": "public"})
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with self.assertRaises(urllib.error.HTTPError) as e:
                opener.open("http://127.0.0.1:%d/api/info" % http.server_address[1], timeout=10)
            self.assertEqual(e.exception.code, 403)
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen("https://127.0.0.1:%d/api/info" % self.port, context=ctx, timeout=10) as r:
                self.assertEqual(r.status, 200)              # the same, encrypted: fine
        finally:
            auth.network_of = real
            config.update({"remote": "home"})
            http.shutdown()
            http.server_close()


class Router(unittest.TestCase):
    """UPnP: a pretend router that, like some real ones, wants port forwards with an end date."""

    def test_forwards_443_and_80_to_sofa(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from sofa import upnp
        forwards = []

        class FakeRouter(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = (b'<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
                        b'<friendlyName>Test Router</friendlyName><deviceList><device><deviceList><device><serviceList><service>'
                        b'<serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>'
                        b'<controlURL>/ctl/IPConn</controlURL></service></serviceList></device></deviceList></device>'
                        b'</deviceList></device></root>')
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                text = self.rfile.read(int(self.headers["Content-Length"])).decode()
                action = self.headers["SOAPAction"].split("#")[1].strip('"')
                if action == "AddPortMapping" and "<NewLeaseDuration>0<" in text:
                    body, code = b"<s:Fault><detail><errorCode>725</errorCode><errorDescription>OnlyPermanentLeasesSupported"\
                                 b"</errorDescription></detail></s:Fault>", 500
                elif action == "AddPortMapping":
                    import re
                    forwards.append({k: v for k, v in re.findall(r"<(New\w+)>([^<]*)<", text)})
                    body, code = b"<u:AddPortMappingResponse/>", 200
                else:
                    body, code = b"<NewExternalIPAddress>203.0.113.7</NewExternalIPAddress>", 200
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        router = ThreadingHTTPServer(("127.0.0.1", 0), FakeRouter)
        threading.Thread(target=router.serve_forever, daemon=True).start()
        try:
            r = upnp.open_ports("http://127.0.0.1:%d/rootDesc.xml" % router.server_address[1])
            self.assertTrue(r["ok"], r["message"])
            self.assertEqual(r["external_ip"], "203.0.113.7")
            self.assertEqual([(f["NewExternalPort"], f["NewInternalPort"]) for f in forwards],
                             [("443", str(config.get("https_port"))), ("80", str(config.get("port")))])
            self.assertEqual(forwards[0]["NewLeaseDuration"], str(7 * 86400))
            self.assertEqual(forwards[0]["NewInternalClient"], "127.0.0.1")
        finally:
            router.shutdown()
            router.server_close()


PEBBLE, PEBBLE_DIR = os.environ.get("PEBBLE"), os.environ.get("PEBBLE_DIR")


def resolves(name):
    try:
        return socket.gethostbyname(name) == "127.0.0.1"
    except OSError:
        return False


@unittest.skipUnless(PEBBLE and PEBBLE_DIR and resolves("sofa.test"), "needs Pebble and sofa.test -> 127.0.0.1")
class LetsEncrypt(unittest.TestCase):
    def test_certificate_from_pebble_then_https_with_it(self):
        http = web.Server(("127.0.0.1", 0), web.Handler)          # where Pebble checks the domain
        threading.Thread(target=http.serve_forever, daemon=True).start()
        acme_port, mgmt_port = free_port(), free_port()
        cfg = {"pebble": {"listenAddress": "127.0.0.1:%d" % acme_port, "managementListenAddress": "127.0.0.1:%d" % mgmt_port,
                          "certificate": os.path.join(PEBBLE_DIR, "test/certs/localhost/cert.pem"),
                          "privateKey": os.path.join(PEBBLE_DIR, "test/certs/localhost/key.pem"),
                          "httpPort": http.server_address[1], "tlsPort": free_port(), "ocspResponderURL": "",
                          "externalAccountBindingRequired": False}}
        conf = os.path.join(tempfile.mkdtemp(dir=tests.ROOT), "pebble.json")
        with open(conf, "w") as f:
            json.dump(cfg, f)
        env = dict(os.environ, PEBBLE_VA_NOSLEEP="1", PEBBLE_WFE_NONCEREJECT="0")
        pebble = subprocess.Popen([PEBBLE, "-config", conf], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            trust = ssl.create_default_context(cafile=os.path.join(PEBBLE_DIR, "test/certs/pebble.minica.pem"))
            trust.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)    # Pebble's own test certificate is minimal
            for _ in range(50):
                try:
                    urllib.request.urlopen("https://localhost:%d/dir" % acme_port, context=trust, timeout=2).close()
                    break
                except OSError:
                    time.sleep(0.2)
            config.update({"https": "letsencrypt", "domain": "sofa.test", "acme_email": "",
                           "acme_directory": "https://localhost:%d/dir" % acme_port})
            self.assertTrue(tls.due())
            self.assertTrue(tls.obtain(context=trust), tls.status()["error"])
            self.assertEqual(tls.cert_info()["names"], ["sofa.test"])
            self.assertFalse(tls.due())                                  # 90 days to go: nothing to do

            # Pebble's own root, then a real HTTPS connection to Sofa checked against it, by name
            root = urllib.request.urlopen("https://localhost:%d/roots/0" % mgmt_port, context=trust, timeout=5).read()
            ca = os.path.join(tests.ROOT, "pebble-root.pem")
            with open(ca, "wb") as f:
                f.write(root)
            port = free_port()
            config.update({"https_port": port})
            httpd = tls._make_server()
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                direct = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                     urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ca)))
                with direct.open("https://sofa.test:%d/api/info" % port, timeout=10) as r:
                    self.assertTrue(json.loads(r.read())["sofa"])
                    self.assertIn("max-age", r.headers.get("Strict-Transport-Security") or "")
            finally:
                httpd.shutdown()
                httpd.server_close()
        finally:
            pebble.kill()
            pebble.wait()
            http.shutdown()
            http.server_close()
            config.update({"https": "off", "domain": "", "acme_directory": "", "https_port": 8443})


if __name__ == "__main__":
    unittest.main()
