"""Live TV from channel lists (sofa/live.py): passed through Sofa with signed links, and a channel from a list on the
internet can't send Sofa to the home network or to this computer (a list at home, a TV tuner's, can)."""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import auth, config, live, media, store, web


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
        elif self.path in ("/one/seg1.ts", "/raw.ts"):
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

    def test_ffmpeg_reads_a_channel_from_the_internet_through_the_relay(self):
        """A raw feed (repackaged as HLS) and a DLNA TV's live channel: ffmpeg gets the relay; a tuner's, as before."""
        live._channels["0123456789ab"] = {"id": "0123456789ab", "name": "Raw", "url": Upstream.base + "/raw.ts",
                                         "group": "News", "home": False, "headers": {}}
        got = []

        def fake_stream(handler, item, *a, **k):
            got.append(item)
            handler.send_body("ok")
        real = live._home_ip
        with mock.patch.object(live, "_home_ip", lambda ip: False if ip == "127.0.0.1" else real(ip)), \
                mock.patch.object(media, "hls_start", lambda item, *a, **k: got.append(item) or "abc"), \
                mock.patch.object(media, "tool", lambda name: "/usr/bin/" + name), \
                mock.patch.object(web.Handler, "dlna_allowed", lambda handler: True), \
                mock.patch.object(web.Handler, "stream", fake_stream):
            self.get("/live/0123456789ab/index.m3u8")                          # (sent on to the HLS of session "abc")
            self.assertEqual(self.get("/dlna/live/0123456789ab"), (200, b"ok"))
        self.assertEqual(len(got), 2)
        for item in got:
            self.assertEqual(item["input_opts"][:2], ["-http_proxy", live.relay()])
        self.assertEqual(live.ffmpeg_input(dict(live._channels["0123456789ab"], home=True)), [])

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


class Home6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


class Spot(BaseHTTPRequestHandler):
    """A web server that notes every path asked of it. Here, 127.0.0.1 plays the internet and [::1] the home network."""
    seg, other, seen = b"", "", None

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.seen.append(self.path)
        here = "http://%s:%d" % (self.headers.get("Host", "").rsplit(":", 1)[0], self.server.server_address[1])
        if self.path == "/redirect.ts":
            self.send_response(302)
            self.send_header("Location", self.other + "/seg.ts")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.endswith(".m3u8"):
            where = self.other if self.path == "/home.m3u8" else here
            body = ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n#EXTINF:1.0,\n%s/seg.ts\n#EXT-X-ENDLIST\n"
                    % where).encode()
            ctype = "application/vnd.apple.mpegurl"
        else:
            body, ctype = self.seg or b"x", "video/mp2t"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Relay(unittest.TestCase):
    """ffmpeg reads a channel from the internet itself (a DLNA TV's live channel, a feed that isn't HLS): only through
    Sofa's relay, which goes to the internet and never home, whatever the channel's playlists or redirects name."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.home = Home6(("::1", 0), Spot)
        except OSError:
            raise unittest.SkipTest("no IPv6 loopback here")
        cls.out = ThreadingHTTPServer(("127.0.0.1", 0), Spot)
        cls.out_url = "http://127.0.0.1:%d" % cls.out.server_address[1]
        cls.home_url = "http://[::1]:%d" % cls.home.server_address[1]
        Spot.other = cls.home_url
        for srv in (cls.out, cls.home):
            threading.Thread(target=srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.out.shutdown()
        cls.home.shutdown()

    def setUp(self):
        Spot.seen, Spot.seg = [], b""
        real = live._home_ip
        self._real = real
        live._home_ip = lambda ip: False if ip == "127.0.0.1" else real(ip)     # (127.0.0.1 plays the internet)

    def tearDown(self):
        live._home_ip = self._real

    def ask(self, raw):
        host, port = live.relay()[len("http://"):].split(":")
        with socket.create_connection((host, int(port)), 10) as s:
            s.sendall(raw)
            out = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    return out
                out += chunk
                if raw.startswith(b"CONNECT") and out.endswith(b"\r\n\r\n") and b"200" in out.split(b"\r\n")[0]:
                    s.sendall(b"GET /a.ts HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
                    raw = b""

    def test_the_relay_goes_out_and_never_home(self):
        out_hp, home_hp = self.out_url[len("http://"):], self.home_url[len("http://"):]
        r = self.ask(b"GET %s/a.ts HTTP/1.1\r\nHost: %s\r\nConnection: keep-alive\r\n\r\n" % (self.out_url.encode(), out_hp.encode()))
        self.assertTrue(r.startswith(b"HTTP/1.0 200") or r.startswith(b"HTTP/1.1 200"), r[:80])
        self.assertTrue(r.endswith(b"x"))
        r = self.ask(b"CONNECT %s HTTP/1.1\r\nHost: %s\r\n\r\n" % (out_hp.encode(), out_hp.encode()))
        self.assertIn(b"200 Connection established", r)                         # a tunnel (https), to the internet
        self.assertTrue(r.endswith(b"x"))
        self.assertEqual(Spot.seen, ["/a.ts", "/a.ts"])
        for raw in (b"GET %s/a.ts HTTP/1.1\r\nHost: x\r\n\r\n" % self.home_url.encode(),
                    b"CONNECT %s HTTP/1.1\r\nHost: x\r\n\r\n" % home_hp.encode(),
                    b"CONNECT 127.0.0.2:8091 HTTP/1.1\r\n\r\n", b"GET http://192.168.1.1/ HTTP/1.1\r\n\r\n"):
            self.assertTrue(self.ask(raw).startswith(b"HTTP/1.1 403"), raw)
        for raw in (b"GET /a.ts HTTP/1.1\r\nHost: x\r\n\r\n", b"CONNECT nope HTTP/1.1\r\n\r\n",
                    b"GET file:///etc/passwd HTTP/1.1\r\n\r\n", b"nonsense\r\n\r\n"):
            self.assertTrue(self.ask(raw).startswith(b"HTTP/1.1 400"), raw)
        self.assertEqual(Spot.seen, ["/a.ts", "/a.ts"])                          # home was never reached

    def test_ffmpeg_options(self):
        opts = live.ffmpeg_input({"home": False, "headers": {"ua": "VLC/3", "referer": "https://tv.example/"}})
        self.assertEqual(opts[:4], ["-http_proxy", live.relay(), "-protocol_whitelist", live.FFMPEG_PROTOCOLS])
        self.assertEqual(opts[4:], ["-user_agent", "VLC/3", "-referer", "https://tv.example/"])
        self.assertEqual(live.ffmpeg_input({"home": True, "headers": {}}), [])    # a tuner at home: as before
        item = {"id": "live:x", "path": "http://1.1.1.1/a.ts", "input_opts": opts}
        cmd = media.stream_command(item, "remux", 0, None, "mpegts")
        self.assertLess(cmd.index("-http_proxy"), cmd.index("-i"))
        with mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*", "http_proxy": "http://elsewhere:1"}):
            env = media._env(item)
        self.assertFalse({"no_proxy", "NO_PROXY", "http_proxy"} & set(env))
        self.assertIsNone(media._env({"path": "/films/a.mkv"}))

    def test_ffmpeg_itself_never_reaches_home(self):
        exe = media.tool("ffmpeg")
        if not exe:
            self.skipTest("no ffmpeg here")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        seg = os.path.join(tmp, "seg.ts")
        subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi", "-i",
                        "testsrc=size=64x48:rate=10", "-t", "1", "-c:v", "mpeg2video", "-f", "mpegts", seg],
                       check=True, timeout=60)
        with open(seg, "rb") as f:
            Spot.seg = f.read()
        opts = live.ffmpeg_input({"home": False})

        def play(url, input_opts):
            return subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-nostdin"] + input_opts +
                                  ["-i", url, "-f", "null", "-"], capture_output=True, timeout=60,
                                  env=media._env({"input_opts": input_opts}) if input_opts else None).returncode

        self.assertEqual(play(self.out_url + "/out.m3u8", opts), 0)               # the internet: plays, through the relay
        self.assertEqual(Spot.seen, ["/out.m3u8", "/seg.ts"])
        for path in ("/home.m3u8", "/redirect.ts"):                                # a playlist or a redirect naming home
            Spot.seen = []
            play(self.out_url + path, opts)
            self.assertEqual(Spot.seen, [path], path)                             # (home never asked)
        Spot.seen = []
        play(self.out_url + "/home.m3u8", [])                                     # (without the relay, ffmpeg goes home:
        self.assertIn("/seg.ts", Spot.seen[1:])                                   # what the relay is there for)


if __name__ == "__main__":
    unittest.main()
