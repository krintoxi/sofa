"""Live TV from channel lists (sofa/live.py): passed through Sofa with signed links, and a channel from a list on the
internet can't send Sofa to the home network or to this computer (a list at home, a TV tuner's, can)."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import auth, config, live, store, web


class Upstream(BaseHTTPRequestHandler):
    """A channel list and its channel, as a TV tuner at home serves them."""
    base = ""

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/list.m3u":
            body, ctype = "#EXTM3U\n#EXTINF:-1 group-title=\"News\",Tuner One\n%s/one/index.m3u8\n" % self.base, "audio/x-mpegurl"
        elif self.path == "/one/index.m3u8":
            body, ctype = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nseg1.ts\n", "application/vnd.apple.mpegurl"
        elif self.path == "/one/seg1.ts":
            body, ctype = "G" * 188, "video/mp2t"
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class LiveTV(unittest.TestCase):
    def setUp(self):
        self.up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        Upstream.base = "http://127.0.0.1:%d" % self.up.server_address[1]
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        self.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.before = {k: config.get(k) for k in ("offline", "live_playlists")}
        config.update({"offline": False, "live_playlists": [{"name": "Tuner", "url": Upstream.base + "/list.m3u"}]})
        if not store.q1("SELECT 1 FROM users WHERE name = 'livetest'"):
            auth.create_user("livetest", "password123")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))
        req = urllib.request.Request(self.base + "/api/login", json.dumps({"name": "livetest", "password": "password123"}).encode(),
                                     {"Content-Type": "application/json", "X-Sofa": "1"})
        self.opener.open(req, timeout=20).close()

    def tearDown(self):
        config.update(self.before)
        live.refresh()
        self.httpd.shutdown()
        self.up.shutdown()

    def get(self, path):
        try:
            with self.opener.open(self.base + path, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_through_sofa_and_kept_off_the_home_network(self):
        self.assertEqual(live.refresh(force=True), 1)
        chan = next(c for c in live.all_channels() if c["name"] == "Tuner One")
        self.assertTrue(chan["home"])                                            # a list at home: its channels are too
        status, text = self.get("/live/%s/index.m3u8" % chan["id"])
        self.assertEqual(status, 200)
        seg = [line for line in text.decode().splitlines() if line and not line.startswith("#")]
        self.assertEqual(len(seg), 1)
        self.assertTrue(seg[0].startswith("/live/%s/p/" % chan["id"]))           # every address back through Sofa, signed
        self.assertEqual(self.get(seg[0]), (200, b"G" * 188))
        self.assertEqual(self.get(seg[0][:-3] + "abc")[0], 404)                   # a link Sofa didn't sign: nothing
        live._channels[chan["id"]] = dict(chan, home=False)                       # the same, from a list on the internet:
        self.assertEqual(self.get("/live/%s/index.m3u8" % chan["id"])[0], 502)    # this computer's addresses aren't fetched
        self.assertEqual(self.get(seg[0])[0], 502)

    def test_what_is_at_home(self):
        for url in ("http://127.0.0.1:8091/box/api/action/reboot", "http://192.168.1.1/reboot", "http://10.0.0.2/",
                    "http://172.16.4.4/", "http://[::1]:8090/", "http://169.254.169.254/latest", "http://0.0.0.0/", "nope"):
            self.assertTrue(live.at_home(url), url)
        for url in ("http://8.8.8.8/live.m3u8", "https://1.1.1.1/a/b.ts"):
            self.assertFalse(live.at_home(url), url)
        req = urllib.request.Request("http://8.8.8.8/live.m3u8")
        with self.assertRaises(PermissionError):                                  # a redirect home isn't followed
            live._StayOut().redirect_request(req, None, 302, "Found", {}, "http://192.168.1.1/")
        self.assertIsNotNone(live._StayOut().redirect_request(req, None, 302, "Found", {}, "http://1.1.1.1/b.m3u8"))

    def test_a_name_that_changes_its_answer_gets_nowhere(self):
        """Checked first and connected after, a name could answer an internet address, then this computer's: the
        connection goes only to an address that was checked (DNS rebinding)."""
        port = self.up.server_address[1]
        seen, real = [], live.socket.getaddrinfo

        def lookup(host, *a, **k):
            if host != "rebind.example":
                return real(host, *a, **k)
            seen.append(host)
            ip = "93.184.216.34" if len(seen) == 1 else "127.0.0.1"          # (an internet address the first time)
            return [(live.socket.AF_INET, live.socket.SOCK_STREAM, 6, "", (ip, port))]
        live.socket.getaddrinfo = lookup
        try:
            with self.assertRaises((PermissionError, urllib.error.URLError)) as caught:
                live.fetch("http://rebind.example:%d/one/seg1.ts" % port, home_ok=False, timeout=5)
        finally:
            live.socket.getaddrinfo = real
        self.assertEqual(len(seen), 2)                                            # checked, then looked up to connect
        err = caught.exception
        self.assertIsInstance(getattr(err, "reason", err), PermissionError)
        with self.assertRaises(PermissionError):
            live._connect_out(("127.0.0.1", port), 5)
        # a list at home: fetched as before
        with live.fetch(Upstream.base + "/one/seg1.ts", timeout=5) as r:
            self.assertEqual(r.read(), b"G" * 188)


if __name__ == "__main__":
    unittest.main()
