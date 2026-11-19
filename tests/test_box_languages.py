"""The Sofa Box's player names a video's sound and subtitle tracks by language, and starts in the one chosen last time.

The box's agent with no mpv behind it (its answers are written here): nothing in this file has run on a Raspberry Pi.
"""
import importlib.util
import os
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("sofa_box_agent_languages", os.path.join(HERE, "deploy", "sofa-box", "sofa-box-agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

FILE = [{"type": "video", "id": 1},
        {"type": "audio", "id": 1, "lang": "eng", "selected": True}, {"type": "audio", "id": 2, "lang": "spa", "title": "Latino"},
        {"type": "sub", "id": 1, "external": True, "title": "0.vtt"}, {"type": "sub", "id": 2, "external": True, "title": "1.vtt"},
        {"type": "sub", "id": 3, "lang": "fre", "forced": True}, {"type": "sub", "id": 4}]


def player(payload, tracks=FILE):
    p = agent.Player()
    p.payload = payload
    p.command = lambda *c: tracks if c == ("get_property", "track-list") else None
    return p


class TheMenu(unittest.TestCase):
    def test_tracks_in_sofas_words(self):
        p = player({"audio": [{"label": "English · Dolby Digital 5.1"}, {"label": "Spanish (Latin America) · AAC Stereo"}],
                    "subtitles": [{"label": "French · forced", "url": "x"}, {"label": "Spanish", "url": "y"}]})
        self.assertEqual(p._tracks("audio"), [(1, "English · Dolby Digital 5.1", True), (2, "Spanish (Latin America) · AAC Stereo", False)])
        self.assertEqual([n for _, n, _ in p._tracks("sub")], ["French · forced", "Spanish", "French (forced)", "Track 4"])

    def test_an_older_sofa_or_a_converted_video_goes_by_the_file(self):
        p = player({"subtitles": [{"url": "x"}]})                # (no names sent; one subtitle sent, two in mpv: not matched)
        self.assertEqual([n for _, n, _ in p._tracks("audio")], ["English", "Spanish · Latino"])
        self.assertEqual([n for _, n, _ in p._tracks("sub")], ["0.vtt", "1.vtt", "French (forced)", "Track 4"])
        one = player({"audio": []}, [{"type": "audio", "id": 1}])
        self.assertEqual(one._tracks("audio"), [(1, "Track 1", False)])

    def test_the_menus_choice_is_kept_for_the_next_video(self):
        kept = {}
        real = agent.settings, agent.save_settings
        agent.settings, agent.save_settings = (lambda: dict(kept)), (lambda **c: kept.update(c))
        try:
            p = player({})
            p.osd = lambda **w: None
            p.menu = {"items": [["Sound", [(1, "English"), (2, "Spanish · Latino")], 0, "aid"]], "at": 0, "used": 0}
            p.menu_key("right")
            self.assertEqual(kept, {"alang": "es"})
            p.menu_key("right")                                  # back to English
            self.assertEqual(kept, {"alang": "en"})
        finally:
            agent.settings, agent.save_settings = real

    def test_the_language_chosen_last_time(self):
        self.assertEqual(agent.lang_codes("es"), ["es", "spa"])
        self.assertEqual(agent.lang_codes("spa"), ["es", "spa"])
        self.assertEqual(agent.lang_codes("es-419"), ["es", "spa"])
        self.assertEqual(agent.lang_codes("fr"), ["fr", "fra", "fre"])
        for odd in ("", None, "xx", "--script=evil", "es,--fs"):
            self.assertEqual(agent.lang_codes(odd), [], odd)


if __name__ == "__main__":
    unittest.main()
