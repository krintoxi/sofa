"""The Server page's "Sofa can't reach secure websites": only for a site Sofa itself asks (details, artwork,
updates), never because one Live TV channel shows a certificate that's its own fault. Every certificate is
still checked: the channel is turned away either way, and says why.

The secure site here is a little server on this computer with a certificate it signed itself."""
import http.server
import ssl
import threading
import time
import unittest
import urllib.error
import urllib.request

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import config, live, net, tls


class Hello(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def failure(message):
    """What urllib raises when a certificate fails its check for this reason."""
    exc = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: %s (_ssl.c:1129)" % message)
    exc.verify_message = message
    return urllib.error.URLError(exc)


class SecureSites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config.update({"https": "self"})
        tls.context()                                       # makes a certificate signed by itself
        config.update({"https": "off"})
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(tls.SELF_CERT, tls.SELF_KEY)
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hello)
        cls.httpd.socket = ctx.wrap_socket(cls.httpd.socket, server_side=True)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = "https://127.0.0.1:%d/" % cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.offline = config.get("offline")
        config.update({"offline": False})
        net.last_error.clear()
        self.real = urllib.request.urlopen

    def tearDown(self):
        urllib.request.urlopen = self.real
        config.update({"offline": self.offline})
        net.last_error.clear()

    def test_a_channel_with_a_bad_certificate_is_turned_away_and_blames_nobody_else(self):
        with self.assertRaises(urllib.error.URLError) as caught:
            net.urlopen(urllib.request.Request(self.url), timeout=10, whole_internet=False)
        self.assertEqual(net.last_error, {})                 # nothing for the Server page
        self.assertIn(net.certificate_fault(caught.exception), ("self", "name"))
        self.assertIn("certificate", live.why_not(caught.exception))        # the channel's own reason, in words

    def test_each_fault_has_its_name_and_other_failures_have_none(self):
        for message, fault in (("unable to get local issuer certificate", "unknown"), ("certificate has expired", "expired"),
                               ("certificate is not yet valid", "early"), ("self signed certificate", "self"),
                               ("Hostname mismatch, certificate is not valid for 'tv.example'.", "name")):
            self.assertEqual(net.certificate_fault(failure(message)), fault, message)
        self.assertIsNone(net.certificate_fault(urllib.error.URLError(OSError("Connection refused"))))
        self.assertEqual(live.why_not(failure("certificate has expired")), "its certificate has run out")
        self.assertEqual(live.why_not(urllib.error.URLError(OSError("Connection refused"))), "it can't be reached")

    def test_a_site_of_sofas_own_says_what_is_wrong_here(self):
        def fails_with(message):
            def opened(*a, **k):
                raise failure(message)
            urllib.request.urlopen = opened
            net.last_error.clear()
            with self.assertRaises(urllib.error.URLError):
                net.urlopen(urllib.request.Request("https://api.example/"), timeout=5)
            return net.last_error.get("message") or ""
        self.assertIn("certificate authorities", fails_with("unable to get local issuer certificate"))
        self.assertIn("clock", fails_with("certificate is not yet valid"))
        self.assertIn("clock", fails_with("certificate has expired"))
        self.assertEqual(fails_with("Hostname mismatch, certificate is not valid for 'api.example'."), "")   # that site's fault
        # ...and the same failures from a channel's address: nothing
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(failure("unable to get local issuer certificate"))
        net.last_error.clear()
        with self.assertRaises(urllib.error.URLError):
            net.urlopen(urllib.request.Request("https://tv.example/a.m3u8"), timeout=5, whole_internet=False)
        self.assertEqual(net.last_error, {})

    def test_it_goes_once_a_secure_site_answers(self):
        net.last_error.update(at=time.time(), message="Sofa couldn't check a secure web address")

        class Answer:
            def close(self):
                pass
        urllib.request.urlopen = lambda *a, **k: Answer()
        net.urlopen(urllib.request.Request("https://tv.example/a.m3u8"), timeout=5, whole_internet=False)
        self.assertTrue(net.last_error)                      # (a channel answering says nothing either way)
        net.urlopen(urllib.request.Request("https://api.example/"), timeout=5)
        self.assertEqual(net.last_error, {})


if __name__ == "__main__":
    unittest.main()
