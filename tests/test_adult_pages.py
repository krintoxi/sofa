"""The Adult section's pages in a browser: a card's facts, the sorts, the filters and the list; a site's top lists, its
own player with the link back, and kept links. The site is a stand-in function and the browser can reach nothing but
this computer, so no test loads anything from the internet."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import auth, config, store, toplists, web
from tests.test_adult_top import Site
from tests.test_box_speed import Page, chrome, free_port


def scene(n, title, height, minutes, size, langs, **more):
    return dict({"id": "am:h%012x" % n, "kind": "movie", "adult": True, "title": title, "category": "Movies", "added": 1790000000 + n,
                 "height": height, "duration": minutes * 60, "size": size, "langs": {"a": langs}, "year": 2020 + n % 5}, **more)


SCENES = [scene(1, "Blue Hour", 2160, 38, 9_000_000_000, ["en", "es"], performers=["Amber", "Sage"], studio="North Room", genres=["Story", "Travel"]),
          scene(2, "Second Take", 1080, 12, 2_000_000_000, ["en"], performers=["Indigo"], studio="Low Tide"),
          scene(3, "After Rain", 1080, 7, 1_200_000_000, ["ja"]),
          scene(4, "Room 12", 720, 24, 700_000_000, ["en"], studio="North Room"),
          scene(5, "Night Bus", 480, 4, 90_000_000, ["es"])]


class AdultPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        for name, admin in (("pages-admin", True), ("pages-plain", False)):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123", admin=admin)
        cls.admin_id = store.q1("SELECT id FROM users WHERE name = 'pages-admin'")["id"]
        auth.set_adult(cls.admin_id, True)
        auth.confirm_age(cls.admin_id)
        cls.before = {k: config.get(k) for k in ("adult_sites",)}
        cls.lib = (web.LIBRARY.adult, web.LIBRARY.generated)
        web.LIBRARY.adult, web.LIBRARY.generated = {"shows": [], "movies": SCENES, "categories": ["Movies"]}, time.time()
        cls.site = Site()
        toplists.fetch_json = cls.site
        cls.dir = tempfile.mkdtemp(prefix="sofa-adult-")
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--mute-audio",
                                       "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",     # nothing but this computer
                                       "--window-size=1280,800", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), "about:blank"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.page = Page(cls.devtools, "about:blank")
        cls.page.call("Page.enable")
        cls.who = None

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        cls.chrome.terminate()
        try:
            cls.chrome.wait(10)
        except subprocess.TimeoutExpired:
            cls.chrome.kill()
        shutil.rmtree(cls.dir, ignore_errors=True)
        web.LIBRARY.adult, web.LIBRARY.generated = cls.lib
        toplists.fetch_json = None
        toplists._cache.clear()
        config.update(cls.before)
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        config.update({"adult_sites": []})
        toplists._cache.clear()
        toplists._table()
        store.ex("DELETE FROM kept_links")

    def open(self, hash_, who="pages-admin", wait=".adult-page"):
        p = self.page
        p.call("Page.navigate", {"url": self.base + "/client/manifest.webmanifest"})
        time.sleep(0.4)
        if who != type(self).who:
            p.value("fetch('/api/logout',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},body:'{}'}).then(()=>1,()=>0)")
            status = p.value("fetch('/api/login',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},"
                             "body:JSON.stringify({name:%s,password:'password123'})}).then(r=>r.status)" % json.dumps(who))
            self.assertEqual(status, 200)
            type(self).who = who
        p.value("localStorage.clear(); sessionStorage.setItem('sofaPicked','1'); localStorage.setItem('sofa.tv','false'); 1")
        p.call("Page.navigate", {"url": self.base + "/?t=%f%s" % (time.time(), hash_)})
        self.until("!!document.querySelector(%s)" % json.dumps(wait))
        return p

    def until(self, expression, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if self.page.value(expression):
                return
            time.sleep(0.15)
        self.fail("never true: " + expression)

    def click(self, selector, value=None):
        pick = "[...document.querySelectorAll(%s)]" % json.dumps(selector)
        if value is not None:
            pick += ".filter(b => b.dataset.v === %s || b.textContent.trim().startsWith(%s))" % (json.dumps(value), json.dumps(value))
        self.assertTrue(self.page.value("(() => { const b = %s[0]; if (b) b.click(); return !!b; })()" % pick), selector)
        time.sleep(0.3)

    def titles(self, selector=".adult-page .card.scene .t1"):
        return self.page.value("[...document.querySelectorAll(%s)].map(e => e.textContent)" % json.dumps(selector))

    # ------------------------------------------------------------ what's in the library

    def test_a_cards_facts_the_sorts_the_filters_and_the_list(self):
        p = self.open("#/adult/category/Movies")
        self.assertEqual(self.titles(), ["Night Bus", "Room 12", "After Rain", "Second Take", "Blue Hour"])       # newest first
        facts = p.value("[...document.querySelectorAll('.adult-page .card.scene')].map(c => [c.querySelector('.t2').textContent,"
                        " [...c.querySelectorAll('.scene-facts i')].map(i => i.textContent).join('|')])")
        self.assertEqual(facts[4], ["Amber, Sage · North Room", "9 GB|EN + ES"])
        self.assertEqual(facts[2][1], "1 GB|Japanese")
        self.click("[data-asort=largest]")
        self.assertEqual(self.titles()[0], "Blue Hour")
        self.click("[data-asort=picture]")
        self.assertEqual(self.titles()[:3], ["Blue Hour", "Second Take", "After Rain"])
        self.click("[data-afilter=pic]", "1080p")
        self.assertEqual(sorted(self.titles()), ["After Rain", "Second Take"])
        self.click("[data-afilter=lang]", "ja")
        self.assertEqual(self.titles(), ["After Rain"])
        self.assertIn("1 of 5", p.value("document.querySelector('.scene-filters .count').textContent"))
        self.click("[data-afilter=pic]", "")
        self.click("[data-afilter=lang]", "")
        self.click("[data-afilter=len]", "Under 10 min")
        self.assertEqual(sorted(self.titles()), ["After Rain", "Night Bus"])
        self.click("[data-afilter=len]", "")
        self.click("[data-aview=list]")
        rows = p.value("[...document.querySelectorAll('.scene-list a.scene-row')].map(r => [...r.querySelectorAll('.sr-name b, .sr-n, .sr-s')]"
                       ".map(e => e.textContent.trim()).slice(0, 5).join('|'))")
        self.assertEqual(rows[0], "Blue Hour|38:00|4K|9 GB|EN + ES")
        self.assertEqual(len(rows), 5)
        self.assertEqual(p.value("localStorage.getItem('sofa.aview')"), '"list"')      # (the list is how it stays)

    # ------------------------------------------------------------ a site's top lists

    def test_top_lists_from_the_switch_to_the_sites_player_to_kept(self):
        p = self.open("#/adult/top", wait=".top-sites")
        self.assertEqual(self.site.asked, [])                                          # off: the site hasn't been asked a thing
        self.assertFalse(p.value("!!document.querySelector('.top-item')"))
        self.click("[data-top-site=eporner]")
        self.until("document.querySelectorAll('.top-item').length > 0")
        self.assertEqual(p.value("document.querySelectorAll('.top-item').length"), 22)
        self.assertEqual(p.value("document.querySelector('.top-item .rank-badge').textContent"), "1")
        self.assertEqual(p.value("[...document.querySelectorAll('.top-cats button')].map(b => b.textContent)"), ["Everything", "Massage", "Outdoor"])
        self.click(".top-cats button", "Massage")
        self.until("location.hash === '#/adult/top/eporner/massage' && document.querySelectorAll('.top-item').length > 0")
        self.click(".top-item a.card")
        self.until("!!document.querySelector('.top-player iframe')")
        self.assertEqual(p.value("location.hash"), "#/adult/top/eporner/v/Vid00000000")         # (an id, never a title)
        self.assertEqual(p.value("document.querySelector('.top-player iframe').getAttribute('src')"), "https://www.eporner.com/embed/Vid00000000/")
        back = p.value("(a => [a.textContent, a.href, a.target, a.rel])(document.querySelector('.top-under a.btn.primary'))")
        self.assertEqual(back, ["Watch on Eporner", "https://www.eporner.com/video-Vid00000000/title/", "_blank", "noopener noreferrer"])
        self.assertFalse(p.value("!!document.querySelector('.top-player video, .top-under [data-download], .top-under [data-add-link]')"))
        self.click(".top-under [data-keep]")
        self.until("document.querySelector('.top-under [data-keep]').getAttribute('aria-pressed') === 'true'")
        self.assertTrue(p.value("!!document.querySelector('.top-player iframe')"))     # (keeping it doesn't start the player again)
        p.value("location.hash = '#/adult/kept'")
        self.until("document.querySelectorAll('.top-item').length > 0")
        self.assertEqual(p.value("document.querySelector('.adult-page .collection-title').textContent.trim().split(' ')[0]"), "Today")
        self.assertEqual(self.titles(".top-item .t1"), ["Title 0"])
        for url in self.site.asked:
            self.assertRegex(url, r"^https://www\.eporner\.com/api/v2/(categories/$|video/search/\?)")

    def test_asked_once_if_18_or_older_before_any_of_it_shows(self):
        store.ex("UPDATE users SET adult_ok = NULL WHERE id = ?", self.admin_id)
        try:
            p = self.open("#/adult/category/Movies", wait=".age-ask")
            self.assertFalse(p.value("!!document.querySelector('.adult-page, .card.scene')"))
            self.assertFalse(p.value("document.querySelector('#navAdult').hidden"))
            self.click("[data-adult-age]")
            self.until("!!document.querySelector('.adult-page')")
            self.assertFalse(p.value("!!document.querySelector('.age-ask')"))
            self.assertIsNotNone(store.q1("SELECT adult_ok FROM users WHERE id = ?", self.admin_id)["adult_ok"])
        finally:
            auth.confirm_age(self.admin_id)

    def test_no_adult_switch_no_page(self):
        p = self.open("#/adult/top", who="pages-plain", wait="#view")
        time.sleep(0.6)
        self.assertFalse(p.value("!!document.querySelector('.adult-page, .top-sites, .top-item')"))


if __name__ == "__main__":
    unittest.main()
