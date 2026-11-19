"""Sofa in Spanish (client/es.js): the everyday pages in Spanish on a device that asks for it, nothing extra in English.

- Without a browser: every English key in es.js is still what client/app.js or index.html says (a change of wording
  there is noticed here), every entry has its Spanish, and a pattern's Spanish uses what its English catches.
- In Chrome (skipped where there's none): the app in English asks for no es.js; in Spanish the pages are in Spanish
  and the library's own words (a show called "Home", a movie called "Play") are left alone.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

import tests
from tests import LIBRARY, video
from sofa import auth, store, web
from sofa.library import LIBRARY as LIB

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(HERE, "client", name), encoding="utf-8") as f:
        return f.read()


ES = read("es.js")
STRING = r'"((?:[^"\\]|\\.)*)"'


def block(name, close):
    start = ES.index("const %s = " % name)
    return ES[start:ES.index(close, start)]


def unquote(s):
    return json.loads('"%s"' % s)


WORDS = {unquote(k): unquote(v) for k, v in re.findall(STRING + r":\s*" + STRING, block("WORDS", "\n  };"))}
PATTERNS = [(unquote(a), unquote(b)) for a, b in re.findall(r"\[" + STRING + r",\s*" + STRING + r"\]", block("PATTERNS", "\n  ];"))]
# The English, as the app's source has it: what's inside its quotes and templates, with the escapes taken out.
SOURCE = re.sub(r"\s+", " ", (read("app.js") + read("index.html")).replace('\\"', '"').replace("&quot;", '"'))
# Put together as the page is drawn (two pieces of the source side by side), so not in the source in one piece.
JOINED = {"Skipped the intro": ("Skipped the ", "intro"), "Skipped the recap": ("Skipped the ", "recap"),
          "Stops at the end of this episode.": ("Stops at the end of this ", "episode"),
          "Stops at the end of this video.": ("Stops at the end of this ", "video"),
          "No shows match. Try clearing the filter.": ("No shows match.", " Try clearing the filter."),
          "Filter shows": ("Filter ${kind}",), "Filter movies": ("Filter ${kind}",),
          "Added to My List.": ('"Added to "', "My List"),
          "Intro": ('intro: "Intro"',), "Recap": ('recap: "Recap"',), "Credits": ('credits: "Credits"',),
          "Space or K": ("Space or K",), "0 to 9": ("0 to 9",)}


# Fixed words of patterns that the app makes from pieces too small to look for alone, and where they come from.
PIECED = {"1 result for": 'plural(total, "result")', "Special E": '"Special "', "to now": '"now"',
          "Someone asked for an account": '"Someone"', "people asked for an account": '" people"',
          "s later than the file says": '"later"', "s earlier than the file says": '"earlier"',
          "file won't play on this device by itself": "file won't play on this device by itself", "about": '", about "',
          "Off by itself on this box": "Off by itself on this box", "Start": '" Start: "'}


class TheTable(unittest.TestCase):
    def test_what_the_app_pieces_together_is_still_there(self):
        self.assertEqual([k for k, where in PIECED.items() if where not in SOURCE], [])

    def test_it_was_read(self):
        self.assertGreater(len(WORDS), 300)
        self.assertGreater(len(PATTERNS), 60)

    def test_every_key_is_still_the_apps_english(self):
        gone = []
        for key in WORDS:
            pieces = JOINED.get(key) or (key,)
            if not all(p in SOURCE for p in pieces):
                gone.append(key)
        self.assertEqual(gone, [], "client/es.js has Spanish for words the app no longer says: change the key to the new English")

    def test_every_patterns_fixed_words_are_still_the_apps(self):
        gone = []
        for en, _es in PATTERNS:
            for piece in re.split(r"\{n?\}", en):
                piece = piece.strip(" ()\"·,.:")
                # (a piece the app puts together from shorter ones: each of those is looked for)
                parts = [piece] if piece in SOURCE or piece in PIECED else [x.strip(" \".,:") for x in re.split(r"(?<=[.,;:]) ", piece)]
                gone += [(en, x) for x in parts if len(x) >= 4 and x not in SOURCE and x not in PIECED]
        self.assertEqual(gone, [])

    def test_every_entry_has_spanish_and_a_patterns_spanish_uses_what_it_catches(self):
        self.assertEqual([k for k, v in WORDS.items() if not v.strip()], [])
        for en, es in PATTERNS:
            caught = len(re.findall(r"\{n?\}", en))
            used = {int(n) for n in re.findall(r"\{(\d)\}", es)}
            self.assertEqual(used, set(range(1, caught + 1)), en)

    def test_the_page_loads_it_only_when_asked(self):
        html = read("index.html")
        loader = html[html.index("/* Spanish:"):html.index('<script src="/client/app.js">')]
        self.assertIn('localStorage.getItem("sofa.lang")', loader)
        self.assertIn("navigator.language", loader)
        self.assertEqual(html.count("/client/es.js"), 1)                       # (only inside that choice)
        self.assertIn("/client/es.js", loader)
        self.assertFalse("/client/es.js" in read("app.js"), "app.js mustn't load it: English would pay for it")


def chrome():
    from tests.test_box_speed import chrome as found
    return found() or os.environ.get("SOFA_TEST_CHROME")


@unittest.skipIf(os.name == "nt", "drives Chrome with the box's own DevTools client, which reads POSIX-only parts of os")
class InABrowser(unittest.TestCase):
    """The app in Chrome, in English and then in Spanish, with a library whose titles are the app's own words."""

    @classmethod
    def setUpClass(cls):
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        from tests.test_box_speed import Page, free_port
        cls.made = [os.path.join(LIBRARY, "Shows", "Home"), os.path.join(LIBRARY, "Shows", "Episodes"),
                    os.path.join(LIBRARY, "Movies", "Play (2011)"), os.path.join(LIBRARY, "Movies", "Search (2018)")]
        video(os.path.join(cls.made[0], "Season 1", "Home S01E01.mp4"))
        video(os.path.join(cls.made[0], "Season 1", "Home S01E02 Watched.mp4"))
        video(os.path.join(cls.made[1], "Season 1", "Episodes S01E01.mp4"))
        video(os.path.join(cls.made[2], "Play (2011).mp4"))
        video(os.path.join(cls.made[3], "Search (2018).mp4"))
        LIB.scan("tests", quick=True)
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        if not store.q1("SELECT 1 FROM users WHERE name = 'Guest'"):
            auth.create_user("Guest", "password123", admin=True)             # (a person named as a word the app uses)
        cls.dir = tempfile.mkdtemp(prefix="sofa-spanish-chrome-")
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--window-size=1280,800",
                                       "--lang=en-US", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), cls.base + "/"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.page = Page(cls.devtools, "127.0.0.1")
        cls.page.call("Network.enable")
        cls.wait("document.querySelector('form, .card') !== null")
        cls.page.value("""fetch("/api/login", {method: "POST", headers: {"Content-Type": "application/json", "X-Sofa": "1"},
                          body: JSON.stringify({name: "Guest", password: "password123"})}).then(r => r.status)""")
        cls.page.value("localStorage.setItem('sofa.splash', '\"off\"'); localStorage.setItem('sofa.trailers', 'false'); 1")

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        cls.chrome.terminate()
        cls.chrome.wait(10)
        cls.httpd.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)
        for d in cls.made:
            shutil.rmtree(d, True)
        LIB.scan("tests", quick=True)

    @classmethod
    def wait(cls, ready, what=None):
        for _ in range(300):
            if cls.page.value(ready):
                return
            time.sleep(0.1)
        raise AssertionError("never: %s" % (what or ready))

    def open(self, lang, hash_="#/"):
        """The app loaded afresh in `lang` ("en", "es"); the addresses it asked for while loading."""
        p = self.page
        p.value("localStorage.setItem('sofa.lang', %s); 1" % json.dumps(json.dumps(lang)))
        p.events = []
        p.call("Page.navigate", {"url": self.base + "/?l=%s%d%s" % (lang, time.time() * 1000 % 100000, hash_)})
        self.wait("document.querySelector('.card') !== null || document.querySelector('.hero h1') !== null", "the library on the page")
        time.sleep(0.5)
        p.value("1")
        return [e["params"]["request"]["url"] for e in p.events if e.get("method") == "Network.requestWillBeSent"]

    def go(self, hash_, ready):
        self.page.value("location.hash = %s; 1" % json.dumps(hash_))
        self.wait(ready, hash_)
        time.sleep(0.3)

    def texts(self, selector):
        return self.page.value("[...document.querySelectorAll(%s)].map(e => e.textContent.replace(/\\s+/g, ' ').trim())" % json.dumps(selector))

    def test_english_loads_nothing_more(self):
        asked = self.open("en")
        self.assertTrue(any(u.endswith("/client/app.js") for u in asked), asked)
        self.assertFalse([u for u in asked if "es.js" in u])
        self.assertEqual(self.page.value("document.documentElement.lang"), "en")
        self.assertEqual(self.page.value("typeof window.SofaSpanish"), "undefined")
        self.assertIn("Movies", self.texts("header nav a, .bar a"))

    def test_spanish_pages_and_the_librarys_own_words(self):
        asked = self.open("es")
        self.assertTrue([u for u in asked if u.endswith("/client/es.js")], asked)
        self.assertEqual(self.page.value("document.documentElement.lang"), "es")
        nav = self.texts("header nav a, .bar a")
        for word in ("Inicio", "Series", "Películas", "Mi lista"):
            self.assertIn(word, nav)
        lines = self.texts(".card.wide .t2")                                   # Home's rows: "S1 E2, Watched" is that episode's title
        self.assertTrue(any(t.endswith(", Watched") for t in lines), lines)
        self.assertTrue(any(t.endswith(", Episodio 1") for t in lines), lines)
        self.go("#/shows", "document.querySelectorAll('.card .t1').length >= 2")
        self.assertEqual(self.texts(".page-head h1"), ["Series"])
        names = self.texts(".card .t1")
        self.assertIn("Home", names)                                           # the show called Home: not "Inicio"
        self.assertIn("Episodes", names)
        self.assertNotIn("Inicio", names)
        self.assertIn("1 temporada, 2 episodios", self.texts(".card .t2"))
        self.assertEqual(self.page.value("document.querySelector('#pageFilter').placeholder"), "Filtra por nombre, género, canal o año")
        self.go("#/movies", "document.querySelectorAll('.card .t1').length >= 2")
        names = self.texts(".card .t1")
        self.assertIn("Play", names)                                           # the movie called Play: not "Reproducir"
        self.assertIn("Search", names)
        self.go("#/movie/" + "m%3Aplay%3A2011", "document.querySelector('.hero h1') !== null")
        self.assertEqual(self.texts(".hero h1"), ["Play"])
        buttons = self.texts(".hero .actions .btn")
        self.assertIn("Reproducir", buttons)
        self.assertIn("+ Mi lista", buttons)
        self.assertIn("Marcar como visto", buttons)
        self.go("#/show/" + "s%3Ahome", "document.querySelectorAll('.episode').length >= 2")
        self.assertEqual(self.texts(".hero h1"), ["Home"])
        titles = self.texts(".episode h3")
        self.assertTrue(any(t.endswith("Episodio 1") for t in titles), titles)  # (an episode with no title: the app's word)
        self.assertTrue(any(t.endswith("Watched") for t in titles), titles)    # (an episode called Watched: its own)
        self.assertEqual(self.texts(".seasons button"), ["Temporada 1"])
        self.assertEqual(self.texts(".who .name, #who .name"), ["Guest"])      # the person called Guest: not "Invitado"
        self.go("#/search/zzzz", "document.querySelector('.search-page .count') !== null")
        self.assertIn("0 resultados para «zzzz»", self.texts(".search-page .count"))
        self.assertEqual(self.page.value("window.confirm.toString().includes('say(')"), True)

    def test_the_choice_is_under_theme(self):
        self.open("en")
        self.page.value("document.querySelector('#lookBtn').click(); 1")
        self.wait("document.querySelector('[data-lang-pick=\"es\"]') !== null", "the Language row")
        self.assertEqual(self.texts("[data-lang-pick]"), ["Device", "English", "Español"])
        self.page.value("document.querySelector('[data-lang-pick=\"es\"]').click(); 1")
        self.wait("document.documentElement.lang === 'es' && document.querySelector('.card') !== null", "the page again, in Spanish")
        self.assertEqual(self.page.value("JSON.parse(localStorage.getItem('sofa.lang'))"), "es")


if __name__ == "__main__":
    unittest.main()
