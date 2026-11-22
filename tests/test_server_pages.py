"""The Server page, option by option: what a real household's Sofa showed going wrong there, and what a pass through
every tab in a browser found. Converting on a Mac without Apple's video chip, pictures made while files move, the
count of titles without details, the Deleted folder after keeping the best copy, a switch that showed its old state
(and turned on again when pressed to turn off), drives a Mac hides, and in the page itself: what someone types kept
through the page's redraw, the remote's place kept after pressing a switch, and no flood of requests while the server
is out of reach."""
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests import LIBRARY, video
from sofa import artwork, auth, config, encoders, places, slow, store, web
from sofa.library import LIBRARY as LIB
from tests.test_box_speed import Page, chrome, free_port
from tests.test_server import Client


class ConvertingOnAMacWithoutTheChip(unittest.TestCase):
    """An Intel Mac from before Apple's video chip (Leo's iMac): ffmpeg has VideoToolbox, whose software side converts,
    but takes no -q:v. Every file failed with "Nothing was written into output file" (412 of them)."""

    @staticmethod
    def fake_run(cmd, timeout=40):
        if "-q:v" in cmd:
            return False, "[out#0/null @ 0x1] Nothing was written into output file, because at least one of its streams received no packets."
        return True, ""

    def test_the_test_finds_the_way_that_works(self):
        with mock.patch.object(encoders, "_ffmpeg", return_value="/usr/bin/ffmpeg"), mock.patch.object(encoders, "_run", self.fake_run):
            got = encoders.probe("h264_videotoolbox")
        self.assertTrue(got["ok"], got)
        self.assertEqual(got.get("live"), 0)
        cmd = encoders.codec("h264_videotoolbox", 720, live=False, how=got)
        self.assertNotIn("-q:v", cmd)
        self.assertIn("-b:v", cmd)
        self.assertIn("-allow_sw", cmd)

    def test_a_mac_with_the_chip_keeps_converting_by_quality(self):
        with mock.patch.object(encoders, "_ffmpeg", return_value="/usr/bin/ffmpeg"), \
                mock.patch.object(encoders, "_run", return_value=(True, "")):
            got = encoders.probe("h264_videotoolbox")
        self.assertEqual((got["ok"], got["file"]), (True, 0))
        self.assertIn("-q:v", encoders.codec("h264_videotoolbox", 720, live=False, how=got))

    def test_the_last_test_is_done_again(self):
        """The old test's answer (no way that works) was remembered: it's asked again with the new way."""
        from sofa import machine
        self.assertTrue(machine._key().startswith("4|"))


class PicturesWhileFilesMove(unittest.TestCase):
    def test_a_picture_gone_since_it_was_listed(self):
        """'art-warm stopped: No such file or directory: .../folder.jpg': one picture moved away stopped the rest."""
        gone = os.path.join(tempfile.mkdtemp(), "folder.jpg")
        with mock.patch.object(artwork.media, "tool", return_value="/usr/bin/ffmpeg"):
            self.assertEqual(artwork.resized(gone, artwork.WIDTHS[0]), gone)


class AnAdultDownloadThatFails(unittest.TestCase):
    def test_its_reason_is_kept_in_the_private_log(self):
        """"A download for Adult didn't work", twice in a day, and nowhere a reason once the list was cleared."""
        from sofa import fetch
        fetch._table()
        jid = store.ex("INSERT INTO downloads (url, adult, playlist, state, added) VALUES ('https://example.invalid/v', 1, 0, 'queued', ?)",
                       int(time.time()))
        if not isinstance(jid, int):
            jid = store.q1("SELECT MAX(id) AS id FROM downloads")["id"]
        job = dict(store.q1("SELECT * FROM downloads WHERE id = ?", jid))
        seen = []
        with mock.patch.object(fetch, "_command", side_effect=OSError("yt-dlp isn't there")), \
                mock.patch.object(store, "log_private", lambda kind, message, detail=None: seen.append((message, detail))):
            fetch._run_one(job)
        self.assertEqual(seen[-1][0], "A download for Adult didn't work")
        self.assertIn("yt-dlp isn't there", (seen[-1][1] or {}).get("why", ""))


class DrivesAMacHides(unittest.TestCase):
    MOUNT = ("/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)\n"
             "/dev/disk3s5 on /Volumes/Recovery (apfs, local, journaled, nobrowse)\n"
             "/dev/disk6s1 on /Volumes/Films (exfat, local, nodev, nosuid, noowners, noatime)\n")

    def test_the_recovery_volume_is_not_a_drive(self):
        root = tempfile.mkdtemp()
        for name in ("Recovery", "Films"):
            os.makedirs(os.path.join(root, name))
        text = self.MOUNT.replace("/Volumes", root)
        from sofa import windows
        with mock.patch.object(places, "_mount_text", return_value=text), mock.patch.object(windows, "ON", False), \
                mock.patch.object(places, "_drive_folders", return_value=[root]):
            got = places._mounted()
        self.assertEqual([(n, fs) for n, _p, fs in got], [("Films", "exfat")])


class Status(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        video(os.path.join(LIBRARY, "Movies", "Nowhere Film (1990)", "Nowhere Film (1990).mp4"))
        video(os.path.join(LIBRARY, "Adult", "Movies", "Studio.21.03.14.Jane.Doe.Title.mp4"))
        LIB.scan("tests")
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        if not store.q1("SELECT 1 FROM users WHERE name = 'pages-admin'"):
            auth.create_user("pages-admin", "password123", admin=True)
        cls.admin = Client(cls.base)
        assert cls.admin.call("/api/login", {"name": "pages-admin", "password": "password123"})[0] == 200

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_the_count_of_titles_without_details_is_the_list(self):
        """The Library tab said 5 while its list had 4: the count took in the Adult section's, which the list leaves
        out for someone who hasn't switched it on."""
        status, listed = self.admin.call("/api/admin/missing")
        self.assertEqual(status, 200)
        self.assertTrue(any(m["adult"] for m in LIB.missing_details()))
        self.assertEqual(self.admin.call("/api/admin/status")[1]["library"]["missing"], len(listed["items"]))

    def test_a_switch_shows_what_it_was_set_to(self):
        """The page asks for the status straight after a change, and got one from up to 1.5 s before it: the switch
        showed its old state, and pressed again it was set the same way again (Offline, Share with TVs, Keep no
        logs all stayed on)."""
        before = config.get("tidy_library")
        try:
            for on in (False, True, False):
                self.admin.call("/api/admin/status")
                self.assertEqual(self.admin.call("/api/admin/settings", {"tidy_library": on})[0], 200)
                self.assertEqual(self.admin.call("/api/admin/status")[1]["settings"]["tidy_library"], on)
        finally:
            config.update({"tidy_library": before})

    def test_one_worked_out_during_a_change_is_not_kept(self):
        web._status.update(at=0.0, value=None)
        real = web._admin_status

        def slow_one():
            value = real()
            web.status_changed()             # a change lands while this one is being worked out
            return value
        with mock.patch.object(web, "_admin_status", slow_one):
            web.admin_status()
        self.assertEqual(web._status["at"], 0.0)

    def test_the_deleted_folder_counts_what_keeping_the_best_put_there(self):
        """Keep the best moved the spare copy to Deleted, and the Deleted panel said 0 files (no Empty button) for
        two minutes."""
        slow.cached("deleted", 120, lambda: {"folder": "", "files": 0, "bytes": 0})
        time.sleep(0.2)
        self.assertEqual(self.admin.call("/api/admin/duplicates", {"keys": ["nothing"]})[0], 200)
        with slow._lock:
            self.assertFalse(slow._parts["deleted"]["has"])


def shim_on_path():
    return bool(chrome())


@unittest.skipUnless(shim_on_path(), "no Chrome or Chromium here")
class InThePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.sofa = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        if not store.q1("SELECT 1 FROM users WHERE name = 'pages-admin'"):
            auth.create_user("pages-admin", "password123", admin=True)
        cls.dir = tempfile.mkdtemp(prefix="sofa-pages-")
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--mute-audio",
                                       "--disable-renderer-backgrounding", "--disable-background-timer-throttling", "--window-size=1280,800", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), "about:blank"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.page = Page(cls.devtools, "about:blank")
        cls.page.call("Page.enable")
        cls.page.call("Network.enable")
        cls.before = {k: config.get(k) for k in ("dlna",)}

    @classmethod
    def tearDownClass(cls):
        config.update(cls.before)
        cls.page.close()
        cls.chrome.terminate()
        try:
            cls.chrome.wait(10)
        except subprocess.TimeoutExpired:
            cls.chrome.kill()
        shutil.rmtree(cls.dir, ignore_errors=True)
        cls.httpd.shutdown()

    def open(self, where, tv=False):
        p = self.page
        p.call("Page.navigate", {"url": self.sofa + "/client/manifest.webmanifest"})
        time.sleep(0.4)
        self.assertEqual(p.value("fetch('/api/login',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},"
                                 "body:JSON.stringify({name:'pages-admin',password:'password123'})}).then(r=>r.status)"), 200)
        p.value("localStorage.clear(); sessionStorage.setItem('sofaPicked','1'); localStorage.setItem('sofa.tv','%s');"
                "localStorage.setItem('sofa.installAsk', Date.now()); 1" % ("true" if tv else "false"))
        p.call("Page.navigate", {"url": self.sofa + "/?t=%f%s" % (time.time(), where)})
        self.until("document.querySelector('.admin .srv-tabs') && !/Loading/.test(document.querySelector('.admin').innerText)")
        return p

    def until(self, expression, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            if self.page.value(expression):
                return
            time.sleep(0.15)
        self.fail("never true: %s (focus: %s)" % (expression, self.page.value(
            "(document.activeElement.outerHTML || '').slice(0, 160)")))

    def enter(self):
        for kind in ("keyDown", "keyUp"):
            self.page.call("Input.dispatchKeyEvent", dict({"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                                                           "nativeVirtualKeyCode": 13}, **({"text": "\r"} if kind == "keyDown" else {})))
        time.sleep(0.3)

    def redrawn(self):
        """Wait for the page's next redraw (every 10 s): a mark on the old page is gone."""
        self.page.value("document.querySelector('.admin .srv-tabs').dataset.old = '1'; 1")
        self.until("!document.querySelector('.admin .srv-tabs').dataset.old", timeout=25)

    def test_what_someone_types_stays_through_the_redraw(self):
        """Every 10 s the page was drawn again and what was typed in a form went (a Live TV list's link, a new
        person's name, a key, the quiet hours), with the focus. Only Internet and Sharing were kept."""
        p = self.open("#/server/people")
        p.value("(() => { const f = document.querySelector('#addUser'); f.name.value = 'typed-name'; f.admin.checked = true;"
                " f.querySelector('button').focus(); return 1 })()")
        self.redrawn()
        self.assertEqual(p.value("[document.querySelector('#addUser').name.value, document.querySelector('#addUser').admin.checked,"
                                 " document.activeElement.closest('form') && document.activeElement.closest('form').id]"),
                         ["typed-name", True, "addUser"])
        p.value("document.querySelector('#addUser').name.focus(); 1")      # typing: not drawn again under someone's fingers
        p.value("document.querySelector('.admin .srv-tabs').dataset.old = '1'; 1")
        time.sleep(11.5)
        self.assertTrue(p.value("document.querySelector('.admin .srv-tabs').dataset.old === '1' && document.activeElement.name === 'name'"))

    def test_the_remote_stays_on_a_switch_it_pressed(self):
        """On a TV, pressing a switch drew the page again and the focus went nowhere: the next press did nothing."""
        config.update({"dlna": False})
        p = self.open("#/server/settings", tv=True)
        p.value("document.querySelector('[data-setting=dlna]').focus(); 1")
        self.enter()
        self.until("document.activeElement && document.activeElement.dataset.setting === 'dlna'"
                   " && document.activeElement.getAttribute('aria-checked') === 'true'")
        self.assertTrue(config.get("dlna"))
        self.enter()
        self.until("document.activeElement && document.activeElement.getAttribute('aria-checked') === 'false'")
        self.assertFalse(config.get("dlna"))

    def test_a_new_password_says_it_was_saved(self):
        """New password under People said nothing when it worked: no way to tell it had."""
        if not store.q1("SELECT 1 FROM users WHERE name = 'pages-other'"):
            auth.create_user("pages-other", "password123")
        p = self.open("#/server/people")
        p.value("window.prompt = () => 'another-password-9'; [...document.querySelectorAll('[data-user-pass]')]"
                ".find(b => b.dataset.userName === 'pages-other').click(); 1")
        self.until("document.querySelector('#toast.on') && /pages-other signs in with the new password/.test(document.querySelector('#toast').textContent)")
        row = store.q1("SELECT * FROM users WHERE name = 'pages-other'")
        self.assertTrue(auth.check_password("another-password-9", row["password"] if "password" in row.keys() else row["pw"]))

    def test_someone_added_with_enter_shows_at_once(self):
        """Typed and sent with Enter, the focus is still in the box: the page is drawn again all the same."""
        store.ex("DELETE FROM users WHERE name = 'pages-entered'")
        p = self.open("#/server/people")
        p.value("(() => { const f = document.querySelector('#addUser'); f.name.value = 'pages-entered'; f.password.value = 'password123';"
                " f.password.focus(); return 1 })()")
        self.enter()
        self.until("[...document.querySelectorAll('[data-user-del]')].some(b => b.dataset.userName === 'pages-entered')", timeout=6)
        self.assertEqual(p.value("document.querySelector('#addUser').name.value"), "")

    def test_the_page_stays_where_it_was_scrolled(self):
        """Putting the focus back must not scroll the page to it."""
        p = self.open("#/server/settings")
        p.value("document.querySelector('[data-setting=no_logs]').focus({preventScroll: true});"
                " scrollTo(0, document.documentElement.scrollHeight); 1")
        y = p.value("scrollY")
        self.assertGreater(y, 100)
        self.redrawn()
        self.assertEqual(p.value("scrollY"), y)

    def test_clearing_guest_history_says_so(self):
        p = self.open("#/server/people")
        p.value("window.confirm = () => true; document.querySelector('[data-guest-clear]').click(); 1")
        self.until("document.querySelector('#toast.on') && /Guests start afresh/.test(document.querySelector('#toast').textContent)")

    def test_no_flood_while_the_server_is_out_of_reach(self):
        """Another tab picked while the server didn't answer (restarting, Wi-Fi gone, signed out) asked again at once,
        hundreds of times a second."""
        p = self.open("#/server/settings")
        p.call("Fetch.enable", {"patterns": [{"urlPattern": "*/api/admin/*"}]})
        p.value("window.__n = 0; const of = window.fetch; window.fetch = (u, o) => { if (String(u).includes('/api/admin/')) __n++;"
                " return of(u, o); }; location.hash = '#/server/people'; 1")
        end = time.time() + 4
        while time.time() < end:            # every ask answered "not now"
            for m in [e for e in p.events if e.get("method") == "Fetch.requestPaused"]:
                p.events.remove(m)
                p.call("Fetch.fulfillRequest", {"requestId": m["params"]["requestId"], "responseCode": 503,
                                                "body": "eyJlcnJvciI6ImRvd24ifQ=="})
            p.value("1")
            time.sleep(0.02)
        asked = p.value("__n")
        p.call("Fetch.disable")
        self.assertLess(asked, 10)


if __name__ == "__main__":
    unittest.main()
