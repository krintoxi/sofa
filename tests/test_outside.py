"""Open to the world: Let's Encrypt's DNS check through DuckDNS (no port 80), Check from outside, and a Sofa Box
opening its own Sofa from the TV (Settings → Sofa on this box, from anywhere)."""
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.parse

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import acme, config, ddns, outside

BOX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "sofa-box")


class FakeLetsEncrypt(acme.Client):
    def __init__(self, fail=False):                      # (no directory to fetch, no account)
        self.dir, self.posted, self.fail = {"newOrder": "new"}, [], fail

    def thumbprint(self):
        return "THUMB"

    def post(self, url, payload, retry=True):
        self.posted.append((url, payload))
        if url == "new":
            return json.dumps({"authorizations": ["authz"], "finalize": "fin"}).encode(), {"Location": "order"}
        if url == "authz":
            return json.dumps({"status": "pending", "identifier": {"value": "me.duckdns.org"},
                               "challenges": [{"type": "http-01", "url": "web", "token": "t1"},
                                              {"type": "dns-01", "url": "dns", "token": "t2"}]}).encode(), {}
        if url == "cert":
            return b"PEM CHAIN", {}
        return b"{}", {}

    def _wait(self, url, done=("valid",), failed=("invalid",), timeout=120):
        if url == "order":
            return {"status": "valid", "certificate": "cert"}
        if self.fail:
            raise acme.AcmeError("DNS problem: NXDOMAIN looking up TXT")
        return {"status": "valid"}


class FakeDNS:
    def __init__(self):
        self.calls = []

    def set_txt(self, name, value):
        self.calls.append(("set", name, value))

    def wait_txt(self, name, value):
        self.calls.append(("wait", name, value))

    def clear_txt(self, name):
        self.calls.append(("clear", name))


class DnsCheck(unittest.TestCase):
    def test_the_txt_record_then_lets_encrypt_looks(self):
        le, dns = FakeLetsEncrypt(), FakeDNS()
        self.assertEqual(le.certificate(["me.duckdns.org"], None, b"csr", dns=dns), "PEM CHAIN")
        value = acme.b64(hashlib.sha256(b"t2.THUMB").digest())
        self.assertEqual(dns.calls, [("set", "me.duckdns.org", value), ("wait", "me.duckdns.org", value), ("clear", "me.duckdns.org")])
        self.assertIn(("dns", {}), le.posted)
        self.assertNotIn(("web", {}), le.posted)                       # port 80 never asked for

    def test_the_record_is_cleared_when_it_fails(self):
        le, dns = FakeLetsEncrypt(fail=True), FakeDNS()
        with self.assertRaises(acme.AcmeError):
            le.certificate(["me.duckdns.org"], None, b"csr", dns=dns)
        self.assertEqual(dns.calls[-1], ("clear", "me.duckdns.org"))

    def test_duckdns_txt(self):
        before = {k: config.get(k) for k in ("domain", "duckdns_token")}
        real_open, real_sleep = ddns.net.urlopen, ddns.time.sleep
        asked, answer = [], [b"OK"]

        class Reply(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(req, timeout=20):
            asked.append(req.full_url)
            if "cloudflare-dns.com" in req.full_url:
                return Reply(json.dumps({"Answer": [{"data": '"the-value"'}]}).encode())
            return Reply(answer[0])
        try:
            config.update({"domain": "me.duckdns.org", "duckdns_token": "test-token-1"})
            ddns.net.urlopen, ddns.time.sleep = fake_open, lambda s: None
            self.assertTrue(ddns.active())
            txt = ddns.DuckTXT()
            txt.set_txt("me.duckdns.org", "the-value")
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(asked[-1]).query)
            self.assertEqual((q["domains"], q["token"], q["txt"]), (["me"], ["test-token-1"], ["the-value"]))
            self.assertTrue(txt.wait_txt("me.duckdns.org", "the-value"))
            self.assertIn("_acme-challenge.me.duckdns.org", urllib.parse.unquote(asked[-1]))
            txt.clear_txt("me.duckdns.org")
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(asked[-1]).query, keep_blank_values=True)
            self.assertEqual((q["txt"], q["clear"]), ([""], ["true"]))
            answer[0] = b"KO"
            with self.assertRaises(OSError):
                txt.set_txt("me.duckdns.org", "the-value")
            txt.clear_txt("me.duckdns.org")                              # (never raises)
        finally:
            ddns.net.urlopen, ddns.time.sleep = real_open, real_sleep
            config.update(before)


class FromOutside(unittest.TestCase):
    def test_a_shared_address(self):
        self.assertFalse(outside.shared_address("8.8.8.8", "8.8.8.8"))
        self.assertTrue(outside.shared_address("100.72.1.9", "8.8.8.8"))      # carrier-grade NAT
        self.assertTrue(outside.shared_address("192.168.0.10", "8.8.8.8"))    # a second router in front
        self.assertTrue(outside.shared_address("8.8.4.4", "8.8.8.8"))
        self.assertIsNone(outside.shared_address(None, "8.8.8.8"))

    def test_offline_it_says_so(self):
        result = outside.check()
        self.assertFalse(result["busy"])
        self.assertIn("offline", result["error"])
        self.assertEqual(outside.status()["error"], result["error"])


class FakeLocalSofa:
    """The box's own Sofa, answering /api/admin/internet the way it does while it opens to the internet."""

    def __init__(self, data, certificate=None):
        self.data, self.calls, self.certificate = data, [], certificate or {"trusted": True}
        self.state = {"upnp": {}, "https": {}, "outside": {}}

    def available(self):
        return True

    def configured(self):
        return True

    def answering(self):
        return True

    def public(self):
        return False

    def ensure(self, seconds):
        return True

    def api(self, path, body=None, timeout=20):
        if body:
            self.calls.append(body)
            if body.get("open_ports"):
                self.state["upnp"] = {"at": 1}
            if body.get("get_certificate"):
                self.state["https"] = dict(self.certificate)
            if body.get("check_outside"):
                self.state["outside"] = {"at": 2, "reach": {"ok": True}}
        return json.loads(json.dumps(self.state))


class ThisBox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("sofa_box_agent_outside", os.path.join(BOX, "sofa-box-agent.py"))
        cls.agent = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.agent)

    def setUp(self):
        self.data = tempfile.mkdtemp()
        with open(os.path.join(self.data, "config.json"), "w") as f:
            json.dump({"port": 8095}, f)
        self.real = self.agent.local_sofa, self.agent.time.sleep
        self.agent.time.sleep = lambda s: None
        self.agent.thisbox_net.update(step=None, error=None, busy=False)

    def tearDown(self):
        self.agent.local_sofa, self.agent.time.sleep = self.real

    def test_every_step_in_order(self):
        sofa = self.agent.local_sofa = FakeLocalSofa(self.data)
        self.agent.thisbox_open("me.duckdns.org", "test-token-2")
        self.assertEqual(self.agent.thisbox_net, {"step": None, "error": None, "busy": False})
        self.assertEqual(sofa.calls, [{"https": "letsencrypt", "domain": "me.duckdns.org", "upnp": True, "open_ports": True,
                                       "duckdns_token": "test-token-2"},
                                      {"get_certificate": True}, {"remote": "public"}, {"check_outside": True}])

    def test_no_certificate_no_internet(self):
        sofa = self.agent.local_sofa = FakeLocalSofa(self.data, {"error": "Port 80 doesn't reach the box"})
        self.agent.thisbox_open("sofa.example.com", "")
        self.assertIn("Port 80", self.agent.thisbox_net["error"])
        self.assertNotIn({"remote": "public"}, sofa.calls)
        self.assertFalse(self.agent.thisbox_net["busy"])

    def test_what_it_asks_for(self):
        self.agent.local_sofa = FakeLocalSofa(self.data)
        self.assertFalse(self.agent.thisbox_action({"action": "open", "domain": "not an address"})["ok"])
        self.assertIn("token", self.agent.thisbox_action({"action": "open", "domain": "me.duckdns.org"})["message"])
        status = self.agent.thisbox_status()
        self.assertTrue(status["running"])
        self.assertEqual(status["port"], 8095)


if __name__ == "__main__":
    unittest.main()
