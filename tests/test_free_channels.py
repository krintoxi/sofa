"""Sofa's own free channels (sofa/freechannels.json): Live TV from the start, on a Sofa Box with no server and on
any Sofa. Only channels their broadcasters stream free on their own websites, checked; numbered after a household's
own so nobody's numbers move; switched off (never removed) on the Server page; never adult; for Visitors only when
an admin says so, and then straight from the broadcaster."""
import json
import os
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import config, demo, live, store

KEYS = ("live_playlists", "free_channels", "free_channels_public", "offline", "live_check", "archive_channels", "retro_eras", "demo")


def the_file():
    with open(live.FREE_FILE, encoding="utf-8") as f:
        return json.load(f)["channels"]


class FreeChannels(unittest.TestCase):
    def setUp(self):
        self.before = {k: config.get(k) for k in KEYS}
        config.update({"live_playlists": [], "free_channels": True, "free_channels_public": False, "offline": False,
                       "live_check": False, "archive_channels": False, "retro_eras": False, "demo": False})
        live.refresh(force=True, download=False)

    def tearDown(self):
        config.update(self.before)
        for f in ("a.m3u",):
            try:
                os.remove(live._saved_as("http://lists.example/" + f))
            except OSError:
                pass
        live.refresh(force=True, download=False)

    def names(self, **kw):
        return [c["name"] for c in live.listing(0, **kw)["channels"]]

    def test_every_channel_in_the_file_passes_the_rules_and_was_checked(self):
        chans = the_file()
        self.assertGreaterEqual(len(chans), 15)
        for c in chans:
            self.assertEqual(demo.channel_problems(c), [], c["name"])
            self.assertTrue(c["url"].startswith("https://"))
        self.assertEqual(len({c["url"] for c in chans}), len(chans))

    def test_a_new_sofa_with_no_lists_has_them_numbered_from_101_in_the_files_order(self):
        self.assertTrue(config.DEFAULTS["free_channels"])
        got = {c["name"]: c["number"] for c in live.all_channels()}
        self.assertEqual([got[c["name"]] for c in the_file()], list(range(101, 101 + len(the_file()))))
        row = next(p for p in live.summary()["playlists"] if p["url"] == live.FREE_URL)
        self.assertEqual((row["name"], row["count"], row["builtin"], row["off"]), (live.FREE_NAME, len(the_file()), True, False))
        self.assertIn("News", live.listing(0)["cats"])

    def test_a_households_own_numbers_dont_move(self):
        with open(live._saved_as("http://lists.example/a.m3u"), "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n" + "".join('#EXTINF:-1 group-title="News",Local %d\nhttps://tv.example/%d.m3u8\n' % (n, n) for n in range(150)))
        config.update({"live_playlists": [{"name": "Mine", "url": "http://lists.example/a.m3u"}], "free_channels": False})
        live.refresh(force=True, download=False)
        mine = {c["name"]: c["number"] for c in live.all_channels()}
        config.update({"free_channels": True})
        live.refresh(force=True, download=False)
        both = {c["name"]: c["number"] for c in live.all_channels()}
        self.assertEqual({k: v for k, v in both.items() if k.startswith("Local")}, mine)
        self.assertEqual(min(v for k, v in both.items() if not k.startswith("Local")), 301)    # (the next hundred after 250)

    def test_switched_off_not_removed_and_never_adult(self):
        live.set_on(live.FREE_URL, False)
        live.refresh(force=True, download=False)
        self.assertFalse(any(c.get("free") for c in live.all_channels()))
        row = next(p for p in live.summary()["playlists"] if p["url"] == live.FREE_URL)
        self.assertEqual((row["off"], row["count"]), (True, len(the_file())))       # (still there, with what it holds)
        live.set_on(live.FREE_URL, True)
        live.remove_playlist(live.FREE_URL)                                       # (Remove: off, kept)
        self.assertFalse(config.get("free_channels"))
        self.assertEqual(config.get("live_playlists"), [])                      # (never written into the admin's lists)
        with self.assertRaises(ValueError):
            live.set_adult(live.FREE_URL, True)

    def test_visitors_only_when_an_admin_says_so_and_straight_from_the_broadcaster(self):
        self.assertEqual(live.listing(0, public_only=True, direct_only=True)["channels"], [])
        live.set_public(live.FREE_URL, True)
        live.refresh(force=True, download=False)
        got = live.listing(0, public_only=True, direct_only=True)["channels"]
        self.assertEqual(len(got), len(the_file()))
        self.assertTrue(all(c["src"].startswith("https://") for c in got))

    def test_not_on_the_public_demo(self):
        config.update({"demo": True})
        try:
            live.refresh(force=True, download=False)
            self.assertFalse(any(c.get("free") for c in live.all_channels()))
            self.assertFalse(any(p["url"] == live.FREE_URL for p in live.summary()["playlists"]))
        finally:
            config.update({"demo": False})

    def test_a_feed_made_for_a_fast_service_is_refused_by_its_address(self):
        base = dict(the_file()[0])
        for url in ("https://d2.cloudfront.net/v1/master/x/WNNationalSamsung/WNNationalSamsung.m3u8",
                    "https://c.mjh.nz/abc-news.m3u8", "https://jmp2.uk/plu-1.m3u8"):
            self.assertTrue(any("FAST" in p for p in demo.channel_problems(dict(base, url=url))), url)


if __name__ == "__main__":
    unittest.main()
