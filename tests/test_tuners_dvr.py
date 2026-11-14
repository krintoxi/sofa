"""Sofa 1.5.13 (draft): tuners at home, the guide, and recording (sofa/tuners.py, sofa/guide.py, sofa/dvr.py).

A stand-in tuner (tests/stand_in_tuner.py) answers as an HDHomeRun does: discovery over UDP, its channel list, a
channel's stream as real MPEG-TS, a limit of two streams at once. The recordings are real: ffmpeg copies the stream,
the Inbox files the result. No real tuner has run any of it yet.
"""
import json
import os
import shutil
import struct
import tempfile
import time
import unittest

from tests import ROOT
from sofa import config, dvr, guide, live, media, naming, organizer, sharing, store, tuners
from tests.stand_in_tuner import DEVICE, Tuner

FFMPEG = media.tool("ffmpeg")


class Packets(unittest.TestCase):
    def test_the_discovery_request_is_siliconDusts(self):
        ask = tuners.packet(tuners.REQUEST, [(tuners.TAG_TYPE, struct.pack(">I", tuners.TUNER)),
                                             (tuners.TAG_ID, struct.pack(">I", tuners.ANY))])
        self.assertEqual(ask.hex(), "0002000c0104000000010204ffffffff4e507f35")      # the packet as published, CRC and all

    def test_a_reply_is_read_and_a_damaged_one_isnt(self):
        reply = tuners.packet(tuners.REPLY, [(tuners.TAG_ID, struct.pack(">I", DEVICE)), (tuners.TAG_TUNERS, b"\x04"),
                                             (tuners.TAG_BASE, b"http://192.168.1.50:80" + b"/" * 120)])   # a long tag: two-byte length
        kind, tags = tuners.unpack(reply)
        self.assertEqual((kind, tags[tuners.TAG_TUNERS], len(tags[tuners.TAG_BASE])), (tuners.REPLY, b"\x04", 142))
        self.assertIsNone(tuners.unpack(reply[:-1] + bytes([reply[-1] ^ 1])))       # a wrong CRC
        self.assertIsNone(tuners.unpack(reply[:10]))
        self.assertIsNone(tuners.unpack(b""))


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class WithATuner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="sofa-tuner-", dir=ROOT)
        cls.box = Tuner(cls.folder, FFMPEG)

    @classmethod
    def tearDownClass(cls):
        cls.box.close()
        shutil.rmtree(cls.folder, True)

    def setUp(self):
        self.before = {k: config.get(k) for k in ("tuners", "guide_sources", "dvr_pad_before", "dvr_pad_after", "live_playlists", "offline")}
        config.update({"tuners": [], "guide_sources": [], "live_playlists": [], "offline": True})
        tuners._lineups.clear()
        dvr._table()
        guide._table()
        for t in ("recordings", "recording_rules", "guide"):
            store.ex("DELETE FROM %s" % t)
        dvr._changed()
        self.box.drop_after = None

    def tearDown(self):
        with dvr._lock:
            running = list(dvr._procs.values())
            dvr._procs.clear()
        for p in running:
            if p["proc"].poll() is None:
                p["proc"].kill()
            p["proc"].wait()
        config.update(self.before)
        tuners._lineups.clear()
        live.refresh()

    def on(self):
        """The stand-in, found and switched on, its channels in Live TV."""
        found = tuners.find(timeout=1.0, to="127.0.0.1", port=self.box.udp_port)
        self.assertEqual([(t["id"], t["seen"], t["on"]) for t in found], [("%08X" % DEVICE, True, False)])
        tuners.switch("%08X" % DEVICE, True)
        live.refresh(force=True)
        return {c["guide_number"]: c for c in live.all_channels() if c.get("tuner")}

    # ---------------------------------------------------------------- tuners

    def test_found_on_the_network_and_off_until_turned_on(self):
        found = tuners.find(timeout=1.0, to="127.0.0.1", port=self.box.udp_port)
        t = found[0]
        self.assertEqual((t["name"], t["tuners"], t["base"]), ("Antenna tuner", 2, self.box.base))
        live.refresh(force=True)
        self.assertEqual([c for c in live.all_channels() if c.get("tuner")], [])    # found, not used
        chans = self.on()
        self.assertEqual(sorted(chans), ["11.3", "2.1", "5.1"])                    # copy-protected and off-network left out
        self.assertEqual([c["guide_number"] for c in tuners.channels()], ["2.1", "5.1", "11.3"])   # in their own order
        self.assertTrue(all(c["home"] and c["tuner"] == "%08X" % DEVICE for c in chans.values()))
        self.assertTrue(tuners.needs_converting(chans["5.1"]))
        self.assertFalse(tuners.needs_converting(chans["11.3"]))
        self.assertEqual(tuners.status()[0]["free"], 2)

    def test_by_its_address_too(self):
        d = tuners.add(self.box.base.replace("http://", ""))
        self.assertEqual((d["id"], d["tuners"]), ("%08X" % DEVICE, 2))
        self.assertTrue(tuners.known()[0]["on"])
        with self.assertRaises(ValueError):
            tuners.add("8.8.8.8")                                                    # never an address off the home network

    def test_never_for_visitors_never_away_never_looked_at(self):
        chans = self.on()
        cid = chans["5.1"]["id"]
        me = store.q1("SELECT id FROM users LIMIT 1")
        uid = me["id"] if me else 0
        self.assertIn(cid, [c["id"] for c in live.listing(uid)["channels"]])
        self.assertNotIn(cid, [c["id"] for c in live.listing(uid, public_only=True)["channels"]])
        self.assertNotIn(cid, [c["id"] for c in live.listing(uid, direct_only=True)["channels"]])
        self.assertNotIn(cid, [c["id"] for c in live._due(time.time())[0]])                  # a look would take a tuner
        row = next(c for c in live.listing(uid)["channels"] if c["id"] == cid)
        self.assertEqual((row["guide_number"], row["recordable"]), ("5.1", True))

    def test_works_offline(self):
        config.update({"offline": True})
        self.assertTrue(self.on())                                                   # offline is about the internet

    # ---------------------------------------------------------------- the guide

    def xmltv(self, programmes, name="guide.xml"):
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?>\n<tv>\n<channel id="kstn.us"><display-name>KSTN</display-name><display-name>5.1</display-name></channel>\n'
                    '<channel id="two"><display-name>2.1 Channel Two</display-name></channel>\n'
                    '<channel id="nobody"><display-name>Not here</display-name></channel>\n')
            for p in programmes:
                f.write(p + "\n")
            f.write("</tv>\n")
        config.update({"guide_sources": [{"path": path}]})
        return path

    @staticmethod
    def stamp(t):
        return time.strftime("%Y%m%d%H%M%S +0000", time.gmtime(t))

    def show(self, chan, start, stop, title, sub=None, ep=None, new=False, movie=False, year=None):
        return ('<programme start="%s" stop="%s" channel="%s"><title>%s</title>%s%s%s%s%s</programme>' % (
            self.stamp(start), self.stamp(stop), chan, title, "<sub-title>%s</sub-title>" % sub if sub else "",
            '<episode-num system="xmltv_ns">%s</episode-num>' % ep if ep else "", "<new/>" if new else "",
            "<category>Movie</category>" if movie else "", "<date>%d</date>" % year if year else ""))

    def test_the_guide_is_read_and_matched(self):
        chans = self.on()
        now = int(time.time()) // 60 * 60
        self.xmltv([self.show("kstn.us", now - 600, now + 1200, "Night Court", "Tonight", "2.6.0/1", new=True),
                    self.show("two", now, now + 7200, "Casablanca", movie=True, year=1942),
                    self.show("nobody", now, now + 600, "Lost")])
        self.assertEqual(guide.refresh(force=True), 2)
        on = guide.at(chans["5.1"]["id"])
        self.assertEqual((on["title"], on["sub"], on["season"], on["episode"], on["fresh"]), ("Night Court", "Tonight", 3, 7, 1))
        film = guide.at(chans["2.1"]["id"])
        self.assertEqual((film["movie"], film["year"]), (1, 1942))
        self.assertEqual(guide.status()["sources"][0]["channels"], 2)

    def test_the_guide_reads_times_and_refuses_entities(self):
        self.assertEqual(guide.when("20261113183000 -0500"), guide.when("20261113233000 +0000"))
        self.assertEqual(guide.episode_of([("onscreen", "S03E07")]), (3, 7))
        self.assertEqual(guide.episode_of([("xmltv_ns", ".4.")]), (None, 5))
        with self.assertRaises(ValueError):
            guide.parse(b'<?xml version="1.0"?><!DOCTYPE tv [<!ENTITY a "aaaa">]><tv>&a;</tv>')

    # ---------------------------------------------------------------- planning

    def test_two_tuners_three_programmes(self):
        chans = self.on()
        now = int(time.time()) + 3600
        a = dvr.record(chans["5.1"]["id"], now, now + 1800, "First")
        b = dvr.record(chans["2.1"]["id"], now, now + 1800, "Second")
        c = dvr.record(chans["11.3"]["id"], now + 600, now + 1200, "Third")
        self.assertEqual([dvr.get(x["id"])["state"] for x in (a, b, c)], ["scheduled", "scheduled", "conflict"])
        self.assertIn("2 tuners", dvr.get(c["id"])["why"])
        self.assertIn("First", dvr.get(c["id"])["why"])
        dvr.cancel(a["id"])
        self.assertEqual(dvr.get(c["id"])["state"], "scheduled")                     # a tuner came free

    def test_padding_never_makes_a_clash(self):
        chans = self.on()
        now = int(time.time()) + 3600
        config.update({"dvr_pad_before": 2, "dvr_pad_after": 5})
        a = dvr.record(chans["5.1"]["id"], now, now + 1800, "One")
        b = dvr.record(chans["2.1"]["id"], now, now + 1800, "Two")
        c = dvr.record(chans["5.1"]["id"], now + 1800, now + 3600, "Right after")    # back to back with One
        self.assertEqual(dvr.get(c["id"])["state"], "scheduled")
        self.assertEqual((dvr.get(a["id"])["before"], dvr.get(a["id"])["after"]), (120, 300))

    def test_a_series_new_ones_no_repeats_on_a_home_channel(self):
        chans = self.on()
        now = int(time.time()) // 60 * 60 + 3600
        self.xmltv([self.show("kstn.us", now, now + 1800, "Night Court", "Tonight", "2.6.0/1", new=True),
                    self.show("two", now + 7200, now + 9000, "Night Court", "Tonight", "2.6.0/1"),            # the same one again
                    self.show("kstn.us", now + 86400, now + 88200, "Night Court", "Later", "2.7.0/1", new=True),
                    self.show("kstn.us", now + 172800, now + 174600, "Night Court", "Old one", "0.1.0/1")])   # not new
        guide.refresh(force=True)
        rule = dvr.add_rule("night court", new_only=True)
        rows = store.q("SELECT title, season, episode, channel FROM recordings WHERE rule = ? ORDER BY start", rule["id"])
        self.assertEqual([(r["season"], r["episode"]) for r in rows], [(3, 7), (3, 8)])
        self.assertEqual(dvr.expand(force=True), 0)                                     # nothing twice
        dvr.remove_rule(rule["id"])
        self.assertEqual(store.q1("SELECT COUNT(*) AS n FROM recordings WHERE state = 'scheduled'")["n"], 0)

    def test_only_channels_at_home(self):
        self.on()
        self.assertIsNotNone(dvr.recordable({"id": "x", "url": "https://example.com/a.m3u8", "home": False}))
        self.assertIsNotNone(dvr.recordable(None))
        with self.assertRaises(ValueError):
            dvr.record("ia-westerns", int(time.time()) + 60, int(time.time()) + 120)  # Classic Cinema isn't Live TV's to record
        with self.assertRaises(ValueError):
            dvr.add_rule("Anything", channel_id="000000000000")

    def test_names_the_inbox_reads(self):
        base = {"title": "Night Court", "sub": "Tonight", "season": 3, "episode": 7, "movie": 0, "year": None,
                "start": time.mktime((2026, 11, 13, 20, 0, 0, 0, 0, -1))}
        self.assertEqual(dvr.file_name(base), "Night Court S03E07 Tonight")
        self.assertEqual(dvr.file_name(dict(base, season=None, episode=None)), "Night Court 2026-11-13")
        self.assertEqual(dvr.file_name(dict(base, title="Casablanca", movie=1, year=1942)), "Casablanca (1942)")
        odd = dvr.file_name(dict(base, title="A/B: C?", movie=1))
        self.assertEqual(odd, naming.safe_filename("A/B: C?"))
        self.assertNotIn("/", odd)

    # ---------------------------------------------------------------- recording for real

    def run_until(self, rid, states, seconds=60):
        deadline = time.time() + seconds
        while time.time() < deadline:
            dvr.tick()
            r = dvr.get(rid)
            if r["state"] in states:
                return r
            time.sleep(0.5)
        self.fail("still %s: %s" % (dvr.get(rid)["state"], dvr.get(rid)["why"]))

    def test_a_recording_is_made_filed_and_kept_from_visitors(self):
        chans = self.on()
        now = int(time.time())
        cid = chans["5.1"]["id"]
        self.xmltv([self.show("kstn.us", now - 60, now + 8, "Night Court", "Tonight", "2.6.0/1", new=True)])
        guide.refresh(force=True)
        config.update({"dvr_pad_before": 0, "dvr_pad_after": 0})
        r = dvr.record_now(cid)
        self.assertEqual((r["title"], r["season"], r["episode"], r["tuner"]), ("Night Court", 3, 7, "%08X" % DEVICE))
        r = self.run_until(r["id"], ("done", "failed"))
        self.assertEqual(r["state"], "done", r["why"])
        self.assertEqual(r["inbox"], "Night Court S03E07 Tonight.ts")
        inbox = os.path.join(config.path("inbox"), r["inbox"])
        info = media.probe(inbox)
        self.assertEqual(info["video"]["codec"], "mpeg2video")                       # the channel's own stream, as it came
        self.assertGreater(info["duration"], 4)
        organizer._handle(inbox)                                                      # the Inbox files it as it files anything
        r = dvr.get(r["id"])
        self.assertEqual(r["state"], "filed")
        self.assertIn(os.path.join("Shows", "Night Court", "Season 3", "Night Court S03E07"), r["path"])
        self.assertTrue(os.path.exists(r["path"]))
        self.addCleanup(shutil.rmtree, os.path.join(config.path("shows"), "Night Court"), True)
        self.assertTrue(dvr.is_recording(r["path"]))
        item = {"id": "x", "kind": "episode", "path": r["path"], "show_id": "s:night-court"}
        self.assertFalse(sharing.item_shared(item, type("L", (), {"find": lambda self, i: {"id": i}})()))
        self.assertNotIn("path", dvr.listing()["recordings"][0])

    def test_a_stream_that_breaks_off_is_opened_again(self):
        chans = self.on()
        now = int(time.time())
        config.update({"dvr_pad_before": 0, "dvr_pad_after": 0})
        self.box.drop_after = 188 * 64 * 40                                           # about half a megabyte, then gone
        r = dvr.record(chans["2.1"]["id"], now, now + 27, "Channel Two")
        r = self.run_until(r["id"], ("done", "failed"), seconds=90)
        self.assertEqual(r["state"], "done", r["why"])
        self.assertIn("opened again 1 time", r["why"])
        self.assertTrue(r["inbox"].startswith("Channel Two 20"))                     # no guide: the channel and the day
        whole = os.path.join(config.path("inbox"), r["inbox"])
        self.addCleanup(lambda: os.path.exists(whole) and os.remove(whole))
        self.assertGreater(media.probe(whole)["duration"], 20)
        self.assertEqual([f for f in os.listdir(dvr.folder()) if f.startswith("%d" % r["id"])], [])   # its parts are gone

    def test_every_tuner_taken_and_a_tail_gives_way(self):
        chans = self.on()
        now = int(time.time())
        config.update({"dvr_pad_before": 0, "dvr_pad_after": 0})
        a = dvr.record(chans["5.1"]["id"], now, now + 25, "A")
        b = dvr.record(chans["2.1"]["id"], now, now + 25, "B")
        dvr.tick()
        self.assertEqual([dvr.get(x["id"])["state"] for x in (a, b)], ["recording", "recording"])
        self.assertEqual(tuners.free("%08X" % DEVICE), 0)
        store.ex("UPDATE recordings SET stop = ? WHERE id = ?", now - 1, a["id"])     # A is now only in its extra minutes
        c = dvr.record(chans["11.3"]["id"], now, now + 25, "C")
        dvr.tick()
        self.assertEqual(dvr.get(c["id"])["state"], "recording")                      # A gave its tuner up

    def test_keep_the_last_two(self):
        self.on()
        rule = dvr.add_rule("Daily", keep=2)
        made = []
        for n in range(3):
            path = os.path.join(config.path("shows"), "Daily", "Season 2026", "Daily S2026E111%d.ts" % n)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"\0" * 1000)
            store.ex("INSERT INTO recordings (channel, title, start, stop, before, after, rule, state, path, created) "
                     "VALUES ('c', 'Daily', ?, ?, 0, 0, ?, 'filed', ?, 0)", 1000 + n, 2000 + n, rule["id"], path)
            made.append(path)
        self.addCleanup(shutil.rmtree, os.path.join(config.path("shows"), "Daily"), True)
        self.addCleanup(shutil.rmtree, organizer.deleted_root(), True)
        dvr.keep_last()
        self.assertEqual([os.path.exists(p) for p in made], [False, True, True])     # the oldest went to Deleted
        self.assertEqual(store.q1("SELECT state FROM recordings WHERE path = ?", made[0])["state"], "deleted")
        aside = [f for _d, _s, fs in os.walk(organizer.deleted_root()) for f in fs]
        self.assertIn(os.path.basename(made[0]), aside)


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class TheServerPage(unittest.TestCase):
    """The API: an admin adds the tuner and the guide; a household member records; a Kids profile can't; nothing of
    it for anyone signed in from the internet."""

    @classmethod
    def setUpClass(cls):
        import threading
        from sofa import auth, web
        from tests.test_server import Client
        cls.folder = tempfile.mkdtemp(prefix="sofa-tuner-api-", dir=ROOT)
        cls.box = Tuner(cls.folder, FFMPEG)
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        for name, admin in (("dvr-admin", True), ("dvr-kid", False)):
            if not store.q1("SELECT 1 FROM users WHERE name = ?", name):
                auth.create_user(name, "password123", admin=admin)
        kid = store.q1("SELECT id FROM users WHERE name = 'dvr-kid'")["id"]
        auth.set_kids(kid, True)
        cls.admin, cls.kid = Client(base), Client(base)
        assert cls.admin.call("/api/login", {"name": "dvr-admin", "password": "password123"})[0] == 200
        assert cls.kid.call("/api/login", {"name": "dvr-kid", "password": "password123"})[0] == 200
        cls.before = {k: config.get(k) for k in ("tuners", "guide_sources")}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.box.close()
        config.update(cls.before)
        live.refresh()
        shutil.rmtree(cls.folder, True)

    def test_tuner_guide_and_a_recording_through_the_api(self):
        status, got = self.admin.call("/api/admin/tuners", {"add": self.box.base.replace("http://", "")})
        self.assertEqual(status, 200, got)
        self.assertEqual((got["tuners"][0]["on"], got["tuners"][0]["channels"], got["tuners"][0]["free"]), (True, 3, 2))
        status, chans = self.admin.call("/api/live")
        mine = {c["guide_number"]: c for c in chans["channels"] if c.get("tuner")}
        self.assertEqual(sorted(mine), ["11.3", "2.1", "5.1"])
        start = int(time.time()) + 7200
        status, got = self.admin.call("/api/dvr", {"slot": {"channel": mine["5.1"]["id"], "start": start, "stop": start + 1800, "title": "Late film"}})
        self.assertEqual((status, got["recording"]["state"], got["recording"]["title"]), (200, "scheduled", "Late film"))
        status, listing = self.admin.call("/api/dvr")
        self.assertIn("Late film", [r["title"] for r in listing["recordings"]])
        self.assertEqual(self.kid.call("/api/dvr")[0], 404)                         # a Kids profile sees no recordings,
        self.assertEqual(self.kid.call("/api/dvr", {"now": mine["5.1"]["id"]})[0], 403)    # and records nothing
        self.assertEqual(self.kid.call("/api/admin/tuners", {"find": True})[0], 403)
        status, got = self.admin.call("/api/dvr", {"cancel": listing["recordings"][0]["id"]})
        self.assertEqual(got["recording"]["state"], "cancelled")
        self.assertEqual(self.admin.call("/api/dvr", {"now": "000000000000"})[0], 400)     # not a channel at home
        self.assertEqual(self.admin.call("/api/admin/tuners", {"guide_add": "/no/such/guide.xml"})[0], 400)


if __name__ == "__main__":
    unittest.main()
