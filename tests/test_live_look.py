"""Live TV by category, the Adult section's own channels, and a quicker change of channel: lists' groups fold into a
short set in a fixed order, the same channel from several lists is one row with the others standing by, a list marked
Adult leaves Live TV for the Adult section (never a Visitor's, a Kids profile's, or anyone's away from home), the
channels next to the one tuned in are made ready, and a Sofa Box gets channels to go up and down through however
long the list is."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import auth, config, live, store, web
from tests.test_box_speed import Page, chrome, free_port
from tests.test_live_lists import Someone

MAIN = [("SPORTS", "", "Field One (720p)", "a1"), ("Sports", "", "Field Two [Geo-blocked]", "a2"), ("News;Business", "wire.xx", "Wire", "a3"),
        ("General", "", "Harbor News 24", "a4"), ("Undefined", "", "Plain", "a5"), ("Kids\U0001F388", "", "Toons", "a6"),
        ("Coastal", "", "Shore One", "a7"), ("COASTAL", "", "Shore Two", "a8"), ("Other", "", "Corner", "a9")]
SECOND = [("News", "wire.xx", "Wire", "b3"), ("News", "wire.yy", "Wire", "b4")]
LATE = [("", "", "Late One", "x1"), ("", "", "Late Two", "x2"), ("Undefined", "", "Plain", "a5")]
LONG = [("News", "", "Long %03d" % n, "n%d" % n) for n in range(700)]


class Air(BaseHTTPRequestHandler):
    base = ""
    seen = []
    gone = set()                # channels that answer 404

    def log_message(self, *args):
        pass

    def do_GET(self):
        Air.seen.append(self.path)
        if self.path in Air.gone:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        lists = {"/main.m3u": MAIN, "/second.m3u": SECOND, "/late.m3u": LATE, "/long.m3u": LONG}
        if self.path in lists:
            body, ctype = "#EXTM3U\n" + "".join('#EXTINF:-1 tvg-id="%s" group-title="%s",%s\n%s/%s/index.m3u8\n' % (t, g, n, self.base, p)
                                                for g, t, n, p in lists[self.path]), "audio/x-mpegurl"
        elif self.path.endswith("/index.m3u8"):
            body, ctype = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nseg1.ts\n", "application/vnd.apple.mpegurl"
        else:
            body, ctype = "G" * 188, "video/mp2t"
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def setUpModule():
    Air.up = ThreadingHTTPServer(("127.0.0.1", 0), Air)
    Air.base = "http://127.0.0.1:%d" % Air.up.server_address[1]
    threading.Thread(target=Air.up.serve_forever, daemon=True).start()
    Air.httpd = web.Server(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=Air.httpd.serve_forever, daemon=True).start()
    Air.sofa = "http://127.0.0.1:%d" % Air.httpd.server_address[1]
    Air.before = {k: config.get(k) for k in ("offline", "live_playlists", "live_check", "archive_channels", "retro_eras")}
    for name, admin in (("look-admin", True), ("look-plain", False), ("look-kid", False), ("look-boss", True)):
        if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
            auth.create_user(name, "password123", admin=admin)
    store.ex("UPDATE users SET adult = 1, adult_ok = 1 WHERE name = 'look-admin'")
    store.ex("UPDATE users SET kids = 1 WHERE name = 'look-kid'")
    Air.home_ip = live._home_ip


def tearDownModule():
    live._home_ip = Air.home_ip
    live._home.clear()
    config.update(Air.before)
    live._health.clear()
    live.refresh()
    Air.httpd.shutdown()
    Air.up.shutdown()


def lists(late_adult=True, long=False):
    """The household's lists; the stand-in on this computer plays the internet (a list at home is never made ready
    ahead, and never played away from home)."""
    live._home_ip = lambda ip: False
    live._home.clear()
    config.update({"offline": False, "live_check": True, "archive_channels": False, "retro_eras": False, "live_playlists":
                   [{"name": "Long", "url": Air.base + "/long.m3u"}] if long else
                   [{"name": "Main", "url": Air.base + "/main.m3u"}, {"name": "Second", "url": Air.base + "/second.m3u"},
                    {"name": "Late list", "url": Air.base + "/late.m3u", "adult": late_adult}]})
    live._health.clear()
    live._streak.clear()
    live._health_state.update(loaded=True, wanted=0.0, asked={}, dirty=False)
    with live._warm_lock:
        live._warm.clear()
    live.refresh(force=True)
    with live._warm_lock:
        live._near_at.clear()
    store.ex("DELETE FROM live_favorites")
    Air.seen.clear()
    Air.gone.clear()


def uid(name):
    return store.q1("SELECT id FROM users WHERE name = ?", name)["id"]


def cid(path):
    return next(c["id"] for c in live.all_channels(adult=True) if c["url"].endswith("/%s/index.m3u8" % path))


class Categories(unittest.TestCase):
    def setUp(self):
        lists()

    def test_a_lists_groups_fold_into_a_short_set_in_a_fixed_order(self):
        for group, name, want in (("News;Business", "", "News"), ("SPORTS", "", "Sports"), ("Kids\U0001F388", "", "Kids"), ("Classic", "", "Movies"),
                                  ("Religious", "", "Faith"), ("General", "Harbor News 24", "News"), ("Undefined", "Plain", live.REST),
                                  ("", "Kids Corner", "Kids"), ("COASTAL", "", "Coastal"), ("Coastal", "", "Coastal"), ("All", "", live.REST),
                                  ("Undefined;Music", "", "Music"), ("Talk & Lifestyle\U0001F335", "", "Lifestyle")):
            self.assertEqual(live.category(group, name), want, (group, name))
        got = live.listing(uid("look-plain"))
        self.assertEqual(got["cats"], ["News", "Sports", "Kids", "Coastal", live.REST])     # known ones, a list's own, the rest
        by = {c["name"]: c for c in got["channels"]}
        self.assertEqual([c["group"] for c in got["channels"]], sorted((c["group"] for c in got["channels"]), key=got["cats"].index))
        self.assertEqual((by["Field One"]["group"], by["Field Two"]["group"]), ("Sports", "Sports"))   # (and no list's marks in a name)
        self.assertEqual((by["Harbor News 24"]["group"], by["Corner"]["group"]), ("News", live.REST))
        self.assertEqual({by["Shore One"]["group"], by["Shore Two"]["group"]}, {"Coastal"})
        self.assertEqual(live.tidy_name("Canal Wire (1080p) [Not 24/7]"), "Canal Wire")

    def test_the_same_channel_from_two_lists_is_one_row_and_the_other_stands_by(self):
        me = uid("look-plain")
        wires = [c for c in live.listing(me)["channels"] if c["name"] == "Wire"]
        self.assertEqual(len(wires), 2)                                           # (wire.yy only shares the name: its own row)
        one = next(c for c in wires if c["id"] == cid("a3"))
        self.assertEqual(one["alt"], [cid("b3")])
        self.assertEqual(live.channel(cid("a3"))["number"], live.channel(cid("b3"))["number"])
        self.assertNotEqual(one["number"], next(c for c in wires if c is not one)["number"])
        numbers = [c["number"] for c in live.listing(me)["channels"]]
        self.assertEqual(numbers, list(range(live.FIRST_NUMBER, live.FIRST_NUMBER + len(numbers))))   # in the order shown, no gaps
        # the first stops answering: the other is the row; both: it's left out, and counted once
        live.mark(cid("a3"), False, "it answered 404", at_once=True)
        row = next(c for c in live.listing(me)["channels"] if c["number"] == one["number"])
        self.assertEqual((row["id"], row.get("alt")), (cid("b3"), None))
        live.mark(cid("b3"), False, "it answered 404", at_once=True)
        got = live.listing(me)
        self.assertEqual((got["down"], [c for c in got["channels"] if c["number"] == one["number"]]), (1, []))
        live._health.clear()
        # a favourite is the channel, whichever list it came from
        viewer = Someone(Air.sofa, "look-plain")
        self.assertEqual(viewer.call("/api/live/favorite/" + cid("b3"), {"on": True})[0], 200)
        self.assertTrue(next(c for c in live.listing(me)["channels"] if c["id"] == cid("a3"))["fav"])
        self.assertEqual(viewer.call("/api/live/favorite/" + cid("a3"), {"on": False})[0], 200)
        self.assertFalse(store.q("SELECT 1 FROM live_favorites WHERE user_id = ?", me))


class Adult(unittest.TestCase):
    def setUp(self):
        lists()

    def test_an_adult_lists_channels_are_in_the_adult_section_and_nowhere_else(self):
        late = {"Late One", "Late Two", "Plain"}                                  # (Plain is in the main list too: adult in any, adult)
        for who in ("look-plain", "look-admin"):
            self.assertFalse(late & {c["name"] for c in live.listing(uid(who), adult=who == "look-admin")["channels"]}, who)
        mine = live.listing(uid("look-admin"), adult=True, only_adult=True)
        self.assertEqual({c["name"] for c in mine["channels"]}, late)
        self.assertEqual([p["name"] for p in mine["playlists"]], ["Late list"])
        self.assertEqual(sorted(c["number"] for c in mine["channels"]), [live.ADULT_FIRST, live.ADULT_FIRST + 1, live.ADULT_FIRST + 2])
        # the two dials never meet: nothing next to an adult channel is anything else, nor the other way round
        self.assertTrue(all(c["adult"] for c in live.near(live.channel(cid("x1")))))
        self.assertFalse(any(n.get("adult") for c in live.all_channels(adult=False) for n in live.near(c)))
        # not for a profile that can't see Adult, a Visitor, or anyone away from home (they're never sent out through Sofa)
        self.assertFalse(late & {c["name"] for c in live.listing(uid("look-plain"), adult=False, only_adult=True)["channels"]})
        self.assertEqual(live.listing(0, adult=True, public_only=True, direct_only=True, only_adult=True)["channels"], [])
        self.assertEqual(live.listing(uid("look-admin"), adult=True, direct_only=True, only_adult=True)["channels"], [])

    def test_over_the_web_only_someone_who_may_see_adult_gets_them(self):
        admin, plain, kid = (Someone(Air.sofa, n) for n in ("look-admin", "look-plain", "look-kid"))
        got = admin.call("/api/live?adult=1")[1]
        self.assertEqual((got["adult"], len(got["channels"]), got["eras"]), (True, 3, []))
        self.assertFalse(any(c["adult"] for c in admin.call("/api/live")[1]["channels"]))
        self.assertFalse(any(c["adult"] for c in plain.call("/api/live?adult=1")[1]["channels"]))
        self.assertEqual(kid.call("/api/live?adult=1")[0], 403)
        late = cid("x1")
        self.assertEqual(admin.call("/live/%s/index.m3u8" % late)[0], 200)
        self.assertEqual(plain.call("/live/%s/index.m3u8" % late)[0], 404)
        self.assertEqual(kid.call("/live/%s/index.m3u8" % late)[0], 404)
        Air.seen.clear()
        plain.call("/api/live/warm", {"ids": [late]})                             # (nor made ready for them)
        time.sleep(0.4)
        self.assertNotIn("/x1/index.m3u8", Air.seen)

    def test_marking_a_list_adult_moves_its_channels_and_ends_sharing_it(self):
        lists(late_adult=False)
        me, url = uid("look-plain"), Air.base + "/late.m3u"
        before = {c["name"]: c["number"] for c in live.listing(me)["channels"]}
        self.assertIn("Late One", before)                                         # as added without the box ticked: in Live TV
        self.assertTrue(next(p for p in live.listing(me)["playlists"] if p["url"] == url)["adultish"] is False)
        live.set_public(url, True)
        boss, admin = Someone(Air.sofa, "look-boss"), Someone(Air.sofa, "look-admin")
        self.assertEqual(boss.call("/api/admin/live", {"adult": {"url": url, "on": True}})[0], 403)    # (an admin who can't see Adult)
        self.assertEqual(admin.call("/api/admin/live", {"adult": {"url": url, "on": True}})[0], 200)
        after = {c["name"]: c["number"] for c in live.listing(me)["channels"]}
        self.assertFalse({"Late One", "Late Two", "Plain"} & set(after))
        self.assertEqual(len(set(after.values())), len(after))
        entry = next(p for p in live.playlists() if p["url"] == url)
        self.assertEqual((entry["adult"], entry.get("public")), (True, None))
        self.assertEqual(admin.call("/api/admin/live", {"public": {"url": url, "on": True}})[0], 400)
        self.assertFalse(any("Late list" in (a.get("message") or "") for a in store.recent_activity(30)))
        # a list whose name or address says what it is: the Server page asks (Sofa doesn't decide for the admin)
        self.assertTrue(live.adultish("My XXX channels"))
        self.assertTrue(live.adultish("Evening", "https://lists.example/adult-tv.m3u"))
        self.assertFalse(live.adultish("Adulthood documentaries", "https://lists.example/docs.m3u"))

    def test_an_adult_list_added_or_failing_is_not_named_in_the_log(self):
        admin = Someone(Air.sofa, "look-admin")
        self.assertEqual(admin.call("/api/admin/live", {"add": {"name": "Velvet Nights", "url": Air.base + "/late.m3u", "adult": True}})[0], 200)
        config.update({"live_playlists": [{"name": "Velvet Nights", "url": "http://127.0.0.1:9/gone.m3u", "adult": True}]})
        live.refresh(force=True)
        said = [a.get("message") or "" for a in store.recent_activity(30)]
        self.assertTrue(any("an adult channel list" in m for m in said))
        self.assertFalse(any("Velvet" in m for m in said))


class ChannelChange(unittest.TestCase):
    def setUp(self):
        lists()

    def playlists_asked(self, path):
        return Air.seen.count("/%s/index.m3u8" % path)

    def test_the_channels_next_to_the_one_tuned_in_are_made_ready(self):
        viewer = Someone(Air.sofa, "look-plain")
        order = [c for c in live.listing(uid("look-plain"))["channels"]]
        at = next(i for i, c in enumerate(order) if c["name"] == "Field One")
        up, down = order[at - 1], order[at + 1]
        self.assertEqual(viewer.call("/live/%s/index.m3u8" % order[at]["id"])[0], 200)
        end = time.time() + 5
        while time.time() < end and not all(live.warmed(live.channel(c["id"])["url"]) for c in (up, down)):
            time.sleep(0.05)
        self.assertTrue(all(live.warmed(live.channel(c["id"])["url"]) for c in (up, down)))
        asked = len(Air.seen)
        status, body = viewer.call("/live/%s/index.m3u8" % down["id"])           # the change of channel: no trip to its server
        self.assertEqual((status, body[:7]), (200, b"#EXTM3U"))
        self.assertIn(b"/live/%s/p/" % down["id"].encode(), body)
        self.assertEqual(len([p for p in Air.seen[asked:] if p == "/%s/index.m3u8" % live.channel(down["id"])["url"].split("/")[-2]]), 0)

    def test_only_tuning_in_makes_them_ready_not_every_few_seconds_of_watching(self):
        """A player asks for a live channel's playlist again every few seconds. That isn't tuning in: the channels next
        to it are asked once, not for as long as someone watches."""
        viewer = Someone(Air.sofa, "look-plain")
        order = live.listing(uid("look-plain"))["channels"]
        at = next(i for i, c in enumerate(order) if c["name"] == "Field One")
        paths = ["/%s/index.m3u8" % live.channel(order[i]["id"])["url"].split("/")[-2] for i in (at - 1, at + 1)]
        for n in range(4):
            self.assertEqual(viewer.call("/live/%s/index.m3u8" % order[at]["id"])[0], 200)
            time.sleep(0.5)
            with live._warm_lock:
                live._warm.clear()                                                # (as if four seconds had gone by each time)
        self.assertEqual([Air.seen.count(p) for p in paths], [1, 1])

    def test_what_was_made_ready_is_kept_a_few_seconds_only(self):
        url = live.channel(cid("a1"))["url"]
        live.warm([live.channel(cid("a1"))])
        end = time.time() + 5
        while time.time() < end and not live.warmed(url):
            time.sleep(0.05)
        self.assertTrue(live.warmed(url))
        with live._warm_lock:
            live._warm[url] = (time.time() - live.WARM_FOR - 1,) + live._warm[url][1:]
        self.assertIsNone(live.warmed(url))                                       # (a live playlist moves on with every part)

    def test_a_tuner_and_a_list_at_home_are_never_asked_ahead(self):
        """Asking a tuner for a channel takes the tuner: nothing at home is fetched before someone tunes in."""
        chan = dict(live.channel(cid("a2")), home=True)
        live.warm([chan, dict(live.channel(cid("a4")), tuner=True)])
        live.mark(cid("a6"), False, "it answered 404", at_once=True)
        live.warm([live.channel(cid("a6"))])                                      # (nor one that's known not to answer)
        time.sleep(0.5)
        self.assertEqual([self.playlists_asked(p) for p in ("a2", "a4", "a6")], [0, 0, 0])


BOX = """window.__played = []; window.SofaBox = {};
window.SofaNative = { play: s => { window.__played.push(JSON.parse(s)); }, caps: () => "{}", status: () => "{}", servers: () => "[]",
                      appVersion: () => "0", control: () => "", choose: () => "" };"""


class InABrowser(unittest.TestCase):
    STUB = ""

    @classmethod
    def setUpClass(cls):
        if cls is InABrowser:
            raise unittest.SkipTest("the two below")
        if not chrome():
            raise unittest.SkipTest("no Chrome or Chromium here")
        cls.dir = tempfile.mkdtemp(prefix="sofa-look-")
        cls.devtools = free_port()
        cls.chrome = subprocess.Popen([chrome(), "--headless=new", "--no-sandbox", "--no-first-run", "--disable-gpu", "--mute-audio",
                                       "--window-size=1280,720", "--remote-debugging-port=%d" % cls.devtools,
                                       "--user-data-dir=" + os.path.join(cls.dir, "profile"), "about:blank"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.page = Page(cls.devtools, "about:blank")
        cls.page.call("Page.enable")
        if cls.STUB:
            cls.page.call("Page.addScriptToEvaluateOnNewDocument", {"source": cls.STUB})

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        cls.chrome.terminate()
        try:
            cls.chrome.wait(10)
        except subprocess.TimeoutExpired:
            cls.chrome.kill()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def open(self, who, where, tv=True):
        p = self.page
        p.call("Page.navigate", {"url": Air.sofa + "/client/manifest.webmanifest"})
        time.sleep(0.4)
        p.value("fetch('/api/logout',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},body:'{}'}).then(()=>1,()=>0)")
        self.assertEqual(p.value("fetch('/api/login',{method:'POST',headers:{'X-Sofa':'1','Content-Type':'application/json'},"
                                 "body:JSON.stringify({name:%s,password:'password123'})}).then(r=>r.status)" % json.dumps(who)), 200)
        p.value("localStorage.clear(); sessionStorage.setItem('sofaPicked','1'); localStorage.setItem('sofa.liveEra','\"now\"');"
                "localStorage.setItem('sofa.tv','%s'); localStorage.setItem('sofa.installAsk', Date.now()); 1" % ("true" if tv else "false"))
        p.call("Page.navigate", {"url": Air.sofa + "/?t=%f%s" % (time.time(), where)})
        self.until("document.querySelectorAll('#dRows .g-row').length > 0")
        return p

    def until(self, expression, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if self.page.value(expression):
                return
            time.sleep(0.15)
        self.fail("never true: " + expression)


class StandingBy(InABrowser):
    """The page's own player, on a TV's browser: the same channel from another list is tried before giving up."""

    def wire(self):
        """The row of the channel two lists carry (wire.xx): the one it plays from first, and the one standing by. Two
        rows are called Wire, and which list comes first goes by the lists' addresses, so the row is found by channel."""
        pair = {cid("a3"): "/a3/index.m3u8", cid("b3"): "/b3/index.m3u8"}
        shown = [i for i in self.page.value("[...document.querySelectorAll('#dRows [data-live]')].map(b => b.dataset.live)") if i in pair]
        self.assertEqual(len(shown), 1)                                           # (one row for the two)
        return shown[0], pair.pop(shown[0]), list(pair.values())[0]

    def tune(self, row):
        self.page.value("document.querySelector('#dRows [data-live=\"%s\"]').click()" % row)

    def test_when_a_channel_doesnt_play_the_same_one_from_another_list_does(self):
        lists()
        p = self.open("look-plain", "#/live")
        row, first, spare = self.wire()
        Air.gone.add(first)
        self.tune(row)
        end = time.time() + 15
        while time.time() < end and spare not in Air.seen:
            time.sleep(0.1)
        asked = [x for x in Air.seen if x in (first, spare)]
        self.assertEqual((asked[0], asked[-1]), (first, spare))                   # (the player asks a second time before it gives up on one)
        self.assertEqual(asked.index(spare), asked.count(first))                  # (the first, then the other: never back)
        time.sleep(1.5)
        self.assertTrue(p.value("document.querySelector('.p-error').hidden"))
        self.assertIn("Wire", p.value("document.querySelector('.p-show').textContent"))
        self.assertTrue(live.down(row))                                           # (and the one that didn't is left out from now on)

    def test_when_neither_plays_it_says_so_after_trying_each_once(self):
        lists()
        Air.gone.update({"/a3/index.m3u8", "/b3/index.m3u8"})
        p = self.open("look-plain", "#/live")
        self.tune(self.wire()[0])
        self.until("!document.querySelector('.p-error').hidden", 20)
        self.assertIn("isn't available right now", p.value("document.querySelector('.p-error').textContent"))
        time.sleep(1)
        tries = [Air.seen.count(x) for x in ("/a3/index.m3u8", "/b3/index.m3u8")]
        self.assertTrue(1 <= tries[0] <= 2 and tries[1] == tries[0], tries)       # (each as often as the other: the stand-in isn't tuned twice)


class OnTheBox(InABrowser):
    """In a browser, as a Sofa Box's page: what the box's player is handed."""
    STUB = BOX

    def test_up_and_down_have_channels_to_go_through_in_a_list_of_any_length(self):
        """A list of more than 600 channels used to hand the box the one channel alone: up and down did nothing."""
        lists(long=True)
        p = self.open("look-plain", "#/live")
        p.value("document.querySelectorAll('#dRows [data-live]')[5].click()")
        self.until("window.__played.length > 0")
        sent = p.value("(() => { const x = window.__played[0]; return [x.channels.length, x.channels[x.at].name, x.title,"
                       " x.channels[(x.at + 1) % 600].name, x.channels[(x.at + 599) % 600].name, x.channels[0].name, x.adult]; })()")
        self.assertEqual(sent, [600, "Long 005", "Long 005", "Long 006", "Long 004", "Long 405", False])

    def test_an_adult_channels_name_stays_on_the_adult_page(self):
        lists()
        p = self.open("look-admin", "#/adult/live")
        self.assertEqual(p.value("document.querySelector('h1').textContent"), "Adult Live TV")
        self.assertEqual(p.value("document.title"), p.value("document.title").replace("Late", ""))
        names = p.value("[...document.querySelectorAll('#dRows .d-name')].map(n => n.textContent)")
        self.assertEqual(sorted(names), ["Late One", "Late Two", "Plain"])
        p.value("document.querySelector('#dRows [data-live]').click()")
        self.until("window.__played.length > 0")
        sent = p.value("(() => { const x = window.__played[0]; return [x.adult, x.title, x.sub, x.channels.map(c => c.name + '|' + c.group).join(',')]; })()")
        self.assertEqual(sent[:3], [True, "Channel %d" % live.ADULT_FIRST, ""])
        self.assertNotIn("Late", sent[3])
        self.assertNotIn("Plain", sent[3])
        # ...and Live TV itself has none of them, for the same person
        p = self.open("look-admin", "#/live")
        p.value("document.querySelector('#dial [data-group=\"All\"]').click()")
        self.until("document.querySelector('#dial [data-group=\"All\"]').getAttribute('aria-pressed') === 'true'")
        names = p.value("[...document.querySelectorAll('#dRows .d-name')].map(n => n.textContent)")
        self.assertFalse({"Late One", "Late Two", "Plain"} & set(names))
        self.assertIn("Corner", names)


if __name__ == "__main__":
    unittest.main()
