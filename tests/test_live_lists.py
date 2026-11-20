"""Live TV and the Server page stay quick whatever the channels and their lists are doing: no request waits on a
list's own server, a channel that can't be found isn't "the internet is down", a list can be switched off and on,
and the Server page's status never queues behind a part that's stuck."""
import contextlib
import io
import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import auth, config, live, net, store, updater, web


class Air(BaseHTTPRequestHandler):
    """Two channel lists and their channels, as a server at home gives them; one list and one channel can be slow."""
    base = ""
    slow = {}                   # path -> seconds it waits before it answers
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        Air.seen.append(self.path)
        time.sleep(Air.slow.get(self.path, 0))
        hls = "application/vnd.apple.mpegurl"
        if self.path in ("/news.m3u", "/films.m3u"):
            kind = self.path[1:-4]
            body, ctype = "#EXTM3U\n" + "".join('#EXTINF:-1 group-title="%s",%s %d\n%s/%s%d/index.m3u8\n' % (
                kind.title(), kind.title(), n, self.base, kind, n) for n in (1, 2, 3)), "audio/x-mpegurl"
        elif self.path.endswith("/index.m3u8"):
            body, ctype = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nseg1.ts\n", hls
        elif self.path.endswith(".ts"):
            body, ctype = "G" * 188, "video/mp2t"
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = body.encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:                             # (whoever asked stopped waiting: that's the test)
            pass


class Someone:
    def __init__(self, base, name):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))
        self.call("/api/login", {"name": name, "password": "password123"})

    def call(self, path, data=None):
        req = urllib.request.Request(self.base + path, None if data is None else json.dumps(data).encode(),
                                     {"Content-Type": "application/json", "X-Sofa": "1"})
        try:
            with self.opener.open(req, timeout=30) as r:
                body = r.read()
                return r.status, json.loads(body) if body[:1] in (b"{", b"[") else body
        except urllib.error.HTTPError as e:
            return e.code, e.read()


class Lists(unittest.TestCase):
    def setUp(self):
        Air.slow, Air.seen = {}, []
        self.up = ThreadingHTTPServer(("127.0.0.1", 0), Air)
        self.up.daemon_threads = True
        Air.base = "http://127.0.0.1:%d" % self.up.server_address[1]
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        self.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.before = {k: config.get(k) for k in ("offline", "live_playlists", "live_check", "archive_channels")}
        self.news, self.films = Air.base + "/news.m3u", Air.base + "/films.m3u"
        config.update({"offline": False, "live_check": False, "archive_channels": False,
                       "live_playlists": [{"name": "News", "url": self.news}]})
        for name, admin in (("lists-admin", True), ("lists-viewer", False)):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123", admin=admin)
        self.admin, self.viewer = Someone(self.base, "lists-admin"), Someone(self.base, "lists-viewer")
        self.kept = (live.ADD_WAIT, live.TUNE_TIMEOUT, net._down_until[0])
        live._status.clear()
        live._home.clear()
        live._errors.clear()
        self.assertEqual(live.refresh(force=True), 3)
        Air.seen = []

    def tearDown(self):
        self.settle()
        live.ADD_WAIT, live.TUNE_TIMEOUT, net._down_until[0] = self.kept
        config.update(self.before)
        live._status.clear()
        live._home.clear()
        live._errors.clear()
        live.refresh(download=False)
        self.httpd.shutdown()
        self.httpd.server_close()
        self.up.shutdown()
        self.up.server_close()

    def settle(self, seconds=10):
        until = time.time() + seconds
        while live.reading() and time.time() < until:
            time.sleep(0.02)
        self.assertFalse(live.reading())

    def names(self, who=None):
        status, out = (who or self.viewer).call("/api/live")
        self.assertEqual(status, 200)
        return sorted(c["name"] for c in out["channels"]), out

    # ------------------------------------------------------------ no request waits on a list's own server

    def test_adding_a_list_answers_before_a_slow_list_has_come(self):
        Air.slow = {"/films.m3u": 1.5}
        live.ADD_WAIT = 0.2
        began = time.time()
        status, out = self.admin.call("/api/admin/live", {"add": {"name": "Films", "url": self.films}})
        self.assertEqual(status, 200)
        self.assertLess(time.time() - began, 1.2)                   # (the list itself takes 1.5 s)
        self.assertTrue(out["reading"])
        self.assertEqual(out["channels"], 3)                        # what was there is still there meanwhile
        status, server = self.admin.call("/api/live?for=server")
        self.assertTrue(server["reading"])
        self.settle()
        self.assertEqual(len(self.names()[0]), 6)                   # ...and the new list's channels arrive by themselves
        self.assertEqual(Air.seen.count("/news.m3u"), 0)            # only the new list was fetched, not every list again

    def test_a_quick_list_is_there_when_adding_it_answers(self):
        status, out = self.admin.call("/api/admin/live", {"add": {"name": "Films", "url": self.films}})
        self.assertEqual((status, out["channels"], out["reading"]), (200, 6, False))

    def test_a_list_that_never_came_isnt_asked_for_by_every_request(self):
        gone = Air.base + "/gone.m3u"
        self.admin.call("/api/admin/live", {"add": {"name": "Missing", "url": gone}})
        self.settle()
        status, server = self.admin.call("/api/live?for=server")
        row = next(p for p in server["playlists"] if p["url"] == gone)
        self.assertIn("404", row["error"])                          # the Server page says what went wrong with it
        Air.seen = []
        self.admin.call("/api/admin/live", {"switch": {"url": self.news, "on": False}})
        self.admin.call("/api/admin/live", {"switch": {"url": self.news, "on": True}})
        self.admin.call("/api/admin/live", {"public": {"url": self.news, "on": True}})
        self.admin.call("/api/admin/live", {"check": True})
        self.admin.call("/api/admin/live", {"remove": gone})
        self.assertEqual([p for p in Air.seen if p.endswith(".m3u")], [])     # none of them fetched a list
        status, server = self.admin.call("/api/live?for=server")
        self.assertEqual([p["name"] for p in server["playlists"] if not p.get("builtin")], ["News"])

    def test_a_request_doesnt_wait_on_a_download_going_on(self):
        Air.slow = {"/news.m3u": 1.5}
        live.refresh_soon(force=True)                               # (the hourly reading, say, on a slow list)
        time.sleep(0.1)
        began = time.time()
        status, done = self.admin.call("/api/admin/live", {"switch": {"url": self.news, "on": False}})
        self.assertEqual((status, done["channels"]), (200, 0))
        self.assertLess(time.time() - began, 1.0)
        self.settle()
        self.assertEqual(self.names()[0], [])                       # ...and the download ending doesn't switch it back on

    def test_one_reading_of_the_lists_at_a_time(self):
        Air.slow = {"/news.m3u": 0.4}
        live.refresh_soon(force=True)
        live.refresh_soon(force=True)                               # asked again meanwhile: read once more after, not at once
        live.refresh_soon(only=self.news)
        self.assertTrue(live.reading())
        self.settle()
        self.assertEqual(Air.seen.count("/news.m3u"), 2)

    # ------------------------------------------------------------ a list on and off

    def test_a_list_switched_off_leaves_live_tv_and_comes_back(self):
        self.admin.call("/api/admin/live", {"add": {"name": "Films", "url": self.films}})
        self.settle()
        names, out = self.names()
        self.assertEqual(len(names), 6)
        rev = out["rev"]
        self.assertEqual(self.viewer.call("/api/live?rev=1"), (200, {"rev": rev}))
        status, done = self.admin.call("/api/admin/live", {"switch": {"url": self.films, "on": False}})
        self.assertEqual((status, done["channels"]), (200, 3))
        names, out = self.names()
        self.assertEqual(names, ["News 1", "News 2", "News 3"])     # for everyone, at once
        self.assertEqual(len(self.names(self.admin)[0]), 3)
        self.assertNotEqual(self.viewer.call("/api/live?rev=1")[1]["rev"], rev)   # a TV with Live TV loaded finds out
        status, server = self.admin.call("/api/live?for=server")
        row = next(p for p in server["playlists"] if p["url"] == self.films)
        self.assertEqual((row["off"], row["count"]), (True, 3))     # still on the Server page, with what it holds
        self.assertEqual(next(p for p in config.get("live_playlists") if p["url"] == self.films).get("off"), True)
        self.admin.call("/api/admin/live", {"switch": {"url": self.films, "on": True}})
        self.assertEqual(len(self.names()[0]), 6)
        self.assertNotIn("off", next(p for p in config.get("live_playlists") if p["url"] == self.films))
        status, out = self.admin.call("/api/admin/live", {"switch": {"url": "http://nowhere.example/x.m3u", "on": False}})
        self.assertEqual(status, 400)
        self.assertEqual(self.viewer.call("/api/admin/live", {"switch": {"url": self.films, "on": False}})[0], 403)

    def test_the_server_page_gets_the_lists_and_no_channels(self):
        status, server = self.admin.call("/api/live?for=server")
        self.assertEqual(status, 200)
        self.assertNotIn("channels", server)
        self.assertEqual([(p["name"], p["count"], p["off"]) for p in server["playlists"] if not p.get("builtin")], [("News", 3, False)])
        self.assertEqual(server["health"]["total"], 3)
        status, mine = self.viewer.call("/api/live?for=server")     # (anyone else asking that way: Live TV as it is for them)
        self.assertEqual(len(mine["channels"]), 3)

    # ------------------------------------------------------------ a channel isn't the internet

    def test_a_channel_whose_name_is_gone_doesnt_turn_the_internet_off(self):
        real = socket.getaddrinfo

        def lookup(host, *a, **k):
            if host == "gone.invalid":
                raise socket.gaierror(8, "nodename nor servname provided, or not known")
            return real(host, *a, **k)
        chan = {"id": "0" * 12, "url": "http://gone.invalid/live/index.m3u8", "home": False, "headers": {}}
        socket.getaddrinfo = lookup
        try:
            self.assertEqual(live.probe(chan, timeout=3), (False, "it can't be reached"))
            with self.assertRaises(OSError):
                live.open_upstream(chan["url"], chan, timeout=3)
        finally:
            socket.getaddrinfo = real
        self.assertTrue(net.online())                               # one channel's name, not the internet
        cid = live.all_channels()[0]["id"]
        self.assertEqual(self.viewer.call("/live/%s/index.m3u8" % cid)[0], 200)

    def test_channels_play_while_sofa_has_stopped_asking_the_internet(self):
        net._down_until[0] = time.time() + 180                      # (a lookup of a film's details just failed that way)
        self.assertFalse(net.online())
        home = live._home_ip
        live._home_ip = lambda ip: False                            # the stand-in on this computer plays the internet
        try:
            chan = dict(live.all_channels()[0], home=False)
            self.assertEqual(live.probe(chan, timeout=3), (True, ""))
        finally:
            live._home_ip = home
        with self.assertRaises(net.Offline):                        # ...and everything else still waits, as before
            net.urlopen(urllib.request.Request(Air.base + "/news.m3u"), timeout=3)

    def test_someone_tuning_in_to_a_channel_that_hangs_hears_soon(self):
        cid = next(c["id"] for c in live.all_channels() if c["name"] == "News 1")
        Air.slow = {"/news1/index.m3u8": 3}
        live.TUNE_TIMEOUT = 0.5
        began = time.time()
        self.assertEqual(self.viewer.call("/live/%s/index.m3u8" % cid)[0], 502)
        self.assertLess(time.time() - began, 2.5)


class ServerPage(unittest.TestCase):
    def test_looking_for_updates_twice_doesnt_wait_on_itself(self):
        """The update check with a fresh answer called status() with the lock status() takes: that thread waited on
        itself for ever, and every Server page after it (they show the update's status) waited behind it."""
        before = dict(updater._state)
        updater._state.update(checked=int(time.time()), latest="0.0.1", latest_commit="", error=None)
        got = []
        t = threading.Thread(target=lambda: got.append(updater.check()), daemon=True)
        t.start()
        t.join(10)
        try:
            self.assertFalse(t.is_alive(), "the update check is waiting on its own lock")
            self.assertEqual(got[0]["latest"], "0.0.1")
            self.assertTrue(updater._lock.acquire(timeout=1))       # (and left the lock free for the Server page)
            updater._lock.release()
        finally:
            updater._state.clear()
            updater._state.update(before)

    def test_a_stuck_status_doesnt_queue_every_server_page_behind_it(self):
        wait, last = web.STATUS_WAIT, dict(web._status)
        web.STATUS_WAIT = 0.2
        web._status.update(at=0.0, value={"server": {"name": "the last answer"}})
        self.assertTrue(web._status_lock.acquire(timeout=5))        # someone is working it out, and is stuck
        try:
            began = time.time()
            got = web.admin_status()
            self.assertEqual((got["server"]["name"], got["stale"]), ("the last answer", True))   # ...and the page says so
            self.assertLess(time.time() - began, 2)
        finally:
            web._status_lock.release()
            web.STATUS_WAIT = wait
            web._status.clear()
            web._status.update(last)

    def test_a_connection_turned_away_is_said_in_the_log_once_a_minute(self):
        httpd = web.Server(("127.0.0.1", 0), web.Handler)
        try:
            said = io.StringIO()
            with contextlib.redirect_stderr(said):
                httpd.refused("192.0.2.7", 48, True)
                httpd.refused("192.0.2.7", 48, True)
            text = said.getvalue()
            self.assertEqual(text.count("Busy: turned away"), 1)
            self.assertIn("48 are open from 192.0.2.7 already", text)
            self.assertIn(" x ", web.stacks())                      # where each thread is: file, line, function
        finally:
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
