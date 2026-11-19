"""What language a title is in: from its tracks' tags, their names, and the file's name, and what stays unknown."""
import os
import shutil
import subprocess
import unittest

import tests
from sofa import config, details, languages, media
from sofa.library import LIBRARY

assert tests.ROOT


class Tags(unittest.TestCase):
    def test_every_way_a_file_writes_a_language(self):
        for tag, code in (("spa", "es"), ("es", "es"), ("ES", "es"), ("es-419", "es-419"), ("es_MX", "es-MX"), ("eng", "en"),
                          ("fre", "fr"), ("fra", "fr"), ("pt-BR", "pt-BR"), ("por", "pt"), ("jpn", "ja"), ("Spanish", "es"),
                          ("chi", "zh"), ("zho", "zh"), ("ger", "de"), ("deu", "de")):
            self.assertEqual(languages.norm(tag), code, tag)

    def test_no_language_is_none_not_a_guess(self):
        for tag in ("und", "", None, "zxx", "mul", "mis", "qaa", "xx", "klingon"):
            self.assertIsNone(languages.norm(tag), tag)

    def test_names_in_english_and_spanish(self):
        self.assertEqual(languages.name("es"), "Spanish")
        self.assertEqual(languages.name("es", spanish=True), "Español")
        self.assertEqual(languages.name("en", spanish=True), "Inglés")
        self.assertEqual(languages.name("es-419"), "Spanish (Latin America)")
        self.assertEqual(languages.name("es-419", spanish=True), "Español (Latinoamérica)")
        self.assertEqual(languages.base("es-419"), "es")


class TrackNames(unittest.TestCase):
    def test_a_tracks_own_name(self):
        for title, code in (("Español Latino", "es-419"), ("Castellano", "es-ES"), ("English 5.1", "en"), ("Latino", "es-419"),
                            ("Spanish (Latin America)", "es-419"), ("Japanese", "ja"), ("Português Brasileiro", "pt-BR")):
            self.assertEqual(languages.from_title(title), code, title)

    def test_a_name_that_says_nothing_of_language(self):
        for title in ("Director's commentary", "Surround 5.1", "DTS-HD MA 5.1", "Commentary with Lat Lee", "", None, "Stereo"):
            self.assertIsNone(languages.from_title(title), title)

    def test_the_tag_first_then_the_name(self):
        self.assertEqual(languages.track({"lang": "spa", "title": None}), ("es", "tag"))
        self.assertEqual(languages.track({"lang": "spa", "title": "Latino 5.1"}), ("es-419", "tag"))   # which Spanish
        self.assertEqual(languages.track({"lang": "und", "title": "Español Latino"}), ("es-419", "title"))
        self.assertEqual(languages.track({"lang": None, "title": "Commentary"}), (None, None))
        self.assertEqual(languages.track({"lang": "eng", "title": "Español"}), ("en", "tag"))          # the tag stands


class FileNames(unittest.TestCase):
    def says(self, *names):
        got = languages.from_names(*names)
        return got["audio"], got["subs"], got["dual"] or got["multi"]

    def test_markers(self):
        self.assertEqual(self.says("Coco (2017) [Dual Audio]"), ([], [], True))
        self.assertEqual(self.says("Coco.2017.1080p.BluRay.LAT.ENG.x264"), (["es-419", "en"], [], False))
        self.assertEqual(self.says("Movie (2001) [eng+spa]"), (["en", "es"], [], False))
        self.assertEqual(self.says("Movie (2001) [EN+ES]"), (["en", "es"], [], False))
        self.assertEqual(self.says("Naruto S01E01 [Dual-Audio][JPN+ENG] 720p"), (["ja", "en"], [], True))
        self.assertEqual(self.says("La Casa de Papel S01E01 CASTELLANO 1080p"), (["es-ES"], [], False))
        self.assertEqual(self.says("Show.S01E02.1080p.MULTi"), ([], [], True))
        self.assertEqual(self.says("Show S01E02 English Breakfast 720p WEB LAT"), (["es-419"], [], False))
        self.assertEqual(self.says("Doblada S01E01 Dual Audio"), ([], [], True))
        self.assertEqual(self.says("Show S03E01 SUB ESP"), ([], ["es"], False))
        self.assertEqual(self.says("Movie (2010) (Spanish Dub)"), (["es"], [], False))

    def test_subtitle_markers_are_not_sound(self):
        self.assertEqual(self.says("El.Hoyo.2019.VOSE.1080p"), ([], ["es"], False))
        self.assertEqual(self.says("Amelie 2001 FRENCH 1080p SUB ESP"), (["fr"], ["es"], False))

    def test_a_title_is_not_a_marker(self):
        for name in ("Dual (2013)", "Spanish Affair (2014)", "The Italian Job (1969)", "Latino (1985)", "Its No Game (2010) 720p",
                     "Do It (2019) [it]", "Movie.2010.720p.DTS.ES", "Roma.2018.1080p.NF.WEB-DL.DDP5.1.x264-NTG",
                     "The English Patient (1996)", "2001 A Space Odyssey (1968)", "Psych S05E12 Dual Spires",
                     "Show S02E03 French Lessons", "The News Hour 2026-11-14 Spanish Class", "Show S01E04 Amor por Siempre",
                     "Show 2x07 The Italian Job"):                               # (an episode's own title)
            self.assertEqual(self.says(name), ([], [], False), name)

    def test_the_folders_name_counts_too(self):
        self.assertEqual(self.says("Episode 01", "Season 1", "Naruto [Dual Audio] [jpn+spa]"), (["ja", "es"], [], True))

    def test_subtitle_files_endings(self):
        for tail, want in (("es", ("es", set())), ("es.forced", ("es", {"forced"})), ("spa.sdh", ("es", {"sdh"})),
                           ("English", ("en", set())), ("forced", (None, {"forced"})), ("en.hi", ("en", {"sdh"})),
                           ("hi", ("hi", set())), ("pt-BR", ("pt-BR", set())), ("", (None, set()))):
            self.assertEqual(languages.sidecar(tail), want, tail)


def audio(*tracks):
    return {"audio": [{"lang": lang, "title": title, "index": i + 1} for i, (lang, title) in enumerate(tracks)], "subs": []}


class Together(unittest.TestCase):
    """Tags, track names and file names put together, and what's sent with each title."""

    def test_two_tagged_tracks_are_dual(self):
        got = languages.of(audio(("eng", None), ("spa", None)), ("Coco (2017)",))
        self.assertEqual((got["a"], got["named"], got["tracks"]), (["en", "es"], [], 2))
        self.assertEqual(languages.compact(got), {"a": ["en", "es"]})

    def test_unnamed_tracks_and_a_name_that_says_which_languages(self):
        got = languages.of(audio((None, None), ("und", None)), ("Coco (2017) [eng+spa]",))
        self.assertEqual((got["a"], got["named"]), (["en", "es"], ["en", "es"]))
        self.assertEqual([t["code"] for t in got["audio"]], [None, None])       # which track is which: not known
        self.assertEqual(languages.compact(got), {"a": ["en", "es"], "by": "name"})

    def test_one_unnamed_track_and_one_language_in_the_name(self):
        got = languages.of(audio((None, None)), ("Coco (2017) 1080p LAT",))
        self.assertEqual(got["audio"], [{"code": "es-419", "by": "name"}])
        self.assertEqual(languages.compact(got), {"a": ["es-419"], "by": "name"})

    def test_tags_win_over_the_name(self):
        got = languages.of(audio(("eng", None)), ("Coco (2017) 1080p LAT",))     # (tagged English: stays English)
        self.assertEqual((got["a"], got["named"]), (["en"], []))

    def test_unnamed_and_nothing_in_the_name_stays_unknown(self):
        got = languages.of(audio((None, None), (None, None)), ("Coco (2017)",))
        self.assertEqual((got["a"], got["tracks"]), ([], 2))
        self.assertEqual(languages.compact(got), {"n": 2})                       # "2 audio tracks", no language named
        self.assertIsNone(languages.compact(languages.of(audio((None, None)), ("Coco (2017)",))))

    def test_dual_audio_in_the_name_and_unnamed_tracks(self):
        got = languages.compact(languages.of(audio(("und", None), ("und", None)), ("Coco (2017) [Dual Audio]",)))
        self.assertEqual(got, {"n": 2, "dual": True})
        one = languages.compact(languages.of(audio(("spa", None)), ("Coco (2017) [Dual Audio]",)))
        self.assertEqual(one, {"a": ["es"]})                                     # the file has one track: not dual

    def test_before_the_file_is_read_the_name_is_all_there_is(self):
        got = languages.compact(languages.of(None, ("Coco.2017.1080p.LAT.ENG",)))
        self.assertEqual(got, {"a": ["es-419", "en"], "by": "name"})
        self.assertIsNone(languages.compact(languages.of(None, ("Coco (2017)",))))

    def test_subtitles_inside_and_beside(self):
        info = dict(audio(("eng", None)), subs=[{"lang": "spa", "title": None}, {"lang": None, "title": "English SDH"}])
        got = languages.of(info, ("Film (2020)",), [{"lang": "fr.forced", "path": "/x/Film (2020).fr.forced.srt"}])
        self.assertEqual(got["s"], ["es", "en", "fr"])
        self.assertEqual([s["by"] for s in got["subs"]], ["tag", "title", "file"])

    def test_a_shows_languages_from_its_episodes(self):
        eps = [{"a": ["ja", "es-419"]}, {"a": ["ja", "es"]}, {"a": ["ja"], "s": ["en"]}, None]
        self.assertEqual(languages.gather(eps), {"a": ["ja", "es"], "s": ["en"], "some": {"ja": 3, "es": 2}})
        self.assertIsNone(languages.gather([None, {}]))


def make(path, tracks, subs=(), video=("testsrc=s=320x240:r=24:d=2", "libx264")):
    """A real small video: `tracks` [(language tag or None, track name or None, channels)]."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cmd = [media.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", video[0]]
    for i, _t in enumerate(tracks):
        cmd += ["-f", "lavfi", "-i", "sine=f=%d:d=2" % (330 + 110 * i)]
    srt = None
    if subs:
        srt = path + ".srt"
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,500\nHola\n")
        for _s in subs:
            cmd += ["-i", srt]
    cmd += ["-map", "0:v"]
    for i, (lang, title, ch) in enumerate(tracks):
        cmd += ["-map", "%d:a" % (i + 1), "-ac:a:%d" % i, str(ch)]
        if lang:
            cmd += ["-metadata:s:a:%d" % i, "language=" + lang]
        if title:
            cmd += ["-metadata:s:a:%d" % i, "title=" + title]
    for i, (lang, title) in enumerate(subs):
        cmd += ["-map", "%d:s" % (len(tracks) + 1 + i)]
        if lang:
            cmd += ["-metadata:s:s:%d" % i, "language=" + lang]
        if title:
            cmd += ["-metadata:s:s:%d" % i, "title=" + title]
    subprocess.run(cmd + ["-c:v", video[1], "-preset", "ultrafast", "-c:a", "aac", "-c:s", "srt", path], check=True, timeout=120)
    if srt:
        os.remove(srt)
    return path


@unittest.skipUnless(media.tool("ffmpeg") and media.tool("ffprobe"), "needs ffmpeg")
class RealFiles(unittest.TestCase):
    """Real small files made with ffmpeg, in the library: read by ffprobe, scanned, and shown."""

    @classmethod
    def setUpClass(cls):
        movies, shows = config.path("movies"), config.path("shows")
        cls.made = [os.path.join(movies, n) for n in ("Dos Voces (2020)", "Sin Nombre (2021) [eng+spa]", "Una Voz (2022) 1080p LAT",
                                                      "Nada Dicho (2023)", "Solo Ingles (2019) LAT")]
        cls.made.append(os.path.join(shows, "Doblada [Dual Audio]"))
        m = cls.made
        cls.dual = make(os.path.join(m[0], "Dos Voces (2020).mkv"), [("eng", None, 6), ("spa", "Español Latino", 2)],
                        subs=[("spa", None), (None, "English SDH")])
        with open(os.path.join(m[0], "Dos Voces (2020).fr.forced.srt"), "w") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nBonjour\n")
        cls.unnamed = make(os.path.join(m[1], "Sin Nombre (2021).mkv"), [(None, None, 2), (None, None, 2)])
        cls.one = make(os.path.join(m[2], "Una Voz (2022) 1080p LAT.mkv"), [(None, None, 2)])
        cls.silent = make(os.path.join(m[3], "Nada Dicho (2023).mp4"), [(None, None, 1)])          # MP4 writes "und"
        cls.tagged = make(os.path.join(m[4], "Solo Ingles (2019) LAT.mkv"), [("eng", None, 2)])
        cls.eps = [make(os.path.join(m[5], "Season 01", "Doblada S01E0%d.mkv" % n), tracks)
                   for n, tracks in ((1, [("jpn", None, 2), ("spa", None, 2)]), (2, [("jpn", None, 2)]))]
        LIBRARY.scan("tests", quick=True)                        # before anything is read: names only
        cls.before = {m_["title"]: m_.get("langs") for m_ in LIBRARY.public()["movies"]}
        for path in (cls.dual, cls.unnamed, cls.one, cls.silent, cls.tagged) + tuple(cls.eps):
            assert media.probe(path, detail=True), path
        LIBRARY.scan("tests", quick=True)

    @classmethod
    def tearDownClass(cls):
        for d in cls.made:
            shutil.rmtree(d, True)
        LIBRARY.scan("tests", quick=True)

    def movie(self, title):
        return next(m for m in LIBRARY.public()["movies"] if m["title"] == title)

    def test_ffprobe_says_nothing_for_an_unnamed_track(self):
        self.assertIn(media.probe(self.unnamed)["audio"][0]["lang"], (None, "und"))
        self.assertEqual(media.probe(self.silent)["audio"][0]["lang"], "und")

    def test_before_a_file_is_read_only_its_name_speaks(self):
        self.assertEqual(self.before["Sin Nombre"], {"a": ["en", "es"], "by": "name"})
        self.assertEqual(self.before["Una Voz"], {"a": ["es-419"], "by": "name"})
        self.assertEqual(self.before["Dos Voces"], {"s": ["fr"]})               # (the subtitle file beside it)
        self.assertIsNone(self.before["Nada Dicho"])

    def test_the_library_lists_each_titles_languages(self):
        self.assertEqual(self.movie("Dos Voces")["langs"], {"a": ["en", "es-419"], "s": ["es", "en", "fr"]})
        self.assertEqual(self.movie("Sin Nombre")["langs"], {"a": ["en", "es"], "by": "name"})
        self.assertEqual(self.movie("Una Voz")["langs"], {"a": ["es-419"], "by": "name"})
        self.assertNotIn("langs", self.movie("Nada Dicho"))                      # unknown: nothing said, nothing sent
        self.assertEqual(self.movie("Solo Ingles")["langs"], {"a": ["en"]})      # tagged English: the name doesn't undo it
        for m in LIBRARY.public()["movies"]:
            self.assertFalse({"names", "read", "path"} & set(m), m["title"])     # (what stays on the server)

    def test_a_shows_languages_are_its_episodes(self):
        show = next(s for s in LIBRARY.public()["shows"] if s["name"].startswith("Doblada"))
        self.assertEqual(show["langs"], {"a": ["ja", "es"], "some": {"es": 1}})
        eps = show["seasons"][0]["episodes"]
        self.assertEqual([e.get("langs") for e in eps], [{"a": ["ja", "es"]}, {"a": ["ja"]}])
        self.assertNotIn("each", show["langs"])                                  # (no two alike: each says its own)

    def test_a_show_in_two_places_is_trimmed_once_it_is_whole(self):
        from sofa.library import Library
        ep = lambda s, n, langs: {"id": "e:x:%d:%d" % (s, n), "e": n, "langs": langs}
        part = lambda s, langs: Library._show_langs({"id": "s:x", "added": 1, "extras": [], "seasons": [
            {"n": s, "poster": None, "episodes": [ep(s, 1, langs), ep(s, 2, dict(langs)), ep(s, 3, dict(langs))]}]}, trim=False)
        here, drive = part(1, {"a": ["en"]}), part(2, {"a": ["es"]})
        self.assertNotIn("each", here["langs"])                                  # (a part: every episode says its own)
        whole = Library._show_langs(Library._merge_shows([here], [drive])[0])
        self.assertEqual(whole["langs"]["a"], ["en", "es"])
        self.assertEqual(whole["langs"]["some"], {"en": 3, "es": 3})
        said = [e.get("langs", whole["langs"].get("each")) for se in whole["seasons"] for e in se["episodes"]]
        self.assertEqual(said, [{"a": ["en"]}] * 3 + [{"a": ["es"]}] * 3)        # season 2 keeps its Spanish

    def test_the_reading_ahead_moves_on(self):
        from sofa import watcher
        items = [{"id": "m:%d" % n, "path": "/x/%d.mkv" % n, "read": 0} for n in range(100)] + \
                [{"id": "o:%d" % n, "path": "/x/o%d.mkv" % n, "read": 1} for n in range(30)]
        first, new = watcher.to_read(items, most=20)
        again, _ = watcher.to_read(items, {i["id"] for i in first}, most=20)     # (the list hasn't taken them in yet)
        self.assertEqual((len(first), len(again), new), (20, 20, True))
        self.assertFalse({i["id"] for i in first} & {i["id"] for i in again})
        done = {i["id"] for i in items if i["read"] == 0}
        old, new = watcher.to_read(items, done, most=20)                         # then the older readings, made again
        self.assertEqual((len(old), new, old[0]["id"]), (20, False, "o:0"))
        self.assertEqual(watcher.to_read(items, done, busy=True), ([], False))   # ...but not while Sofa converts for someone
        self.assertEqual(watcher.to_read(items, done | {"/x/o0.mkv"}, most=1)[0][0]["id"], "o:1")   # (an unreadable file)

    def test_adult_names_are_never_kept(self):
        where = os.path.join(config.path("adult"), "Movies", "Thing (2020)")
        languages.remember(where, "Thing.2020.1080p.LAT")
        self.assertNotIn(where, languages.remembered())

    def test_what_a_shows_episodes_share_is_said_once(self):
        from sofa.library import Library
        ep = lambda n, langs="-": dict({"id": "e:x:1:%d" % n}, **({} if langs == "-" else {"langs": langs}))
        both = {"a": ["ja", "es"]}
        show = Library._show_langs({"seasons": [{"n": 1, "episodes": [ep(1, both), ep(2, dict(both)), ep(3, {"a": ["ja"]}), ep(4)]}]})
        self.assertEqual(show["langs"], {"a": ["ja", "es"], "some": {"ja": 3, "es": 2}, "each": both})
        self.assertEqual([e.get("langs", "each") for e in show["seasons"][0]["episodes"]], ["each", "each", {"a": ["ja"]}, None])
        again = Library._show_langs(dict(show))                                  # read back the same (the reading ahead)
        self.assertEqual(again["langs"], show["langs"])
        self.assertIs(again["seasons"][0]["episodes"][0], show["seasons"][0]["episodes"][0])   # unchanged entries: the same
        plain = Library._show_langs({"seasons": [{"n": 1, "episodes": [ep(1), ep(2)]}]})
        self.assertNotIn("langs", plain)
        self.assertEqual([("langs" in e) for e in plain["seasons"][0]["episodes"]], [False, False])

    def test_a_file_read_after_the_scan_reaches_the_list_without_another_scan(self):
        path = make(os.path.join(config.path("movies"), "Tarde (2018)", "Tarde (2018).mkv"), [("spa", None, 2), ("eng", None, 2)])
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        LIBRARY.scan("tests", quick=True)
        late = self.movie("Tarde")
        self.assertNotIn("langs", late)
        self.assertIsNone(late["duration"])
        before = LIBRARY.generated
        self.assertFalse(LIBRARY.refresh([late["id"]]))                          # not read yet: nothing changes
        self.assertEqual(LIBRARY.generated, before)
        media.probe(path, detail=True)
        self.assertTrue(LIBRARY.refresh([late["id"], "m:not-there:"]))
        self.assertIsNot(self.movie("Tarde"), late)                              # a new entry: the old one isn't touched
        self.assertNotIn("langs", late)
        self.assertEqual(self.movie("Tarde")["langs"], {"a": ["es", "en"]})
        self.assertEqual(self.movie("Tarde")["duration"], 2)
        self.assertGreater(LIBRARY.generated, before)
        self.assertEqual(LIBRARY.item(late["id"])["read"], media.PROBE_DETAIL)
        self.assertFalse(LIBRARY.refresh([late["id"]]))                          # nothing new: the apps aren't told again

    def test_a_changed_file_is_read_again(self):
        path = make(os.path.join(config.path("movies"), "Cambia (2017)", "Cambia (2017).mkv"), [("eng", None, 2)])
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        media.probe(path, detail=True)
        LIBRARY.scan("tests", quick=True)
        self.assertEqual(self.movie("Cambia")["langs"], {"a": ["en"]})
        make(path, [("eng", None, 2), ("spa", None, 6)])
        os.utime(path, (1, 1_600_000_000))                                       # (a different time, whatever the clock)
        LIBRARY.scan("tests", quick=True)
        item = LIBRARY.item(self.movie("Cambia")["id"])
        self.assertEqual(item["read"], 0)                                        # the old reading isn't this file's
        self.assertNotIn("langs", item)
        media.probe(path, detail=True)
        LIBRARY.refresh([item["id"]])
        self.assertEqual(self.movie("Cambia")["langs"], {"a": ["en", "es"]})

    def test_an_older_reading_is_used_until_it_is_made_again(self):
        from sofa import store
        row = store.q1("SELECT info FROM probes WHERE path = ?", self.tagged)
        import json
        old = {k: v for k, v in json.loads(row["info"]).items() if k not in ("d", "bit_rate")}
        store.ex("UPDATE probes SET info = ? WHERE path = ?", json.dumps(old), self.tagged)
        self.addCleanup(media.probe, self.tagged, detail=True)
        self.assertNotIn("d", media.probe(self.tagged))                          # as it is: playing doesn't wait
        self.assertNotIn("d", media.probe(self.tagged, cached_only=True, detail=True))
        LIBRARY.scan("tests", quick=True)
        item = LIBRARY.item(self.movie("Solo Ingles")["id"])
        self.assertEqual((item["read"], item["langs"]), (1, {"a": ["en"]}))      # its languages are known already
        self.assertEqual(media.probe(self.tagged, detail=True)["d"], media.PROBE_DETAIL)

    def test_the_players_menu_names_tracks_by_language(self):
        item = LIBRARY.item(self.movie("Dos Voces")["id"])
        tracks = media.audio_tracks(media.probe(self.dual), item)
        self.assertEqual([(t["code"], t["by"], t["lang"]) for t in tracks], [("en", "tag", "eng"), ("es-419", "tag", "spa")])
        self.assertEqual(tracks[0]["label"], "English · AAC 5.1")
        self.assertEqual(tracks[1]["label"], "Spanish (Latin America) · AAC Stereo")
        subs = media.subtitle_tracks(item, media.probe(self.dual))
        self.assertEqual([(s["code"], s["label"]) for s in subs],
                         [("fr", "French · forced"), ("es", "Spanish"), ("en", "English · SDH")])
        unnamed = media.audio_tracks(media.probe(self.unnamed), LIBRARY.item(self.movie("Sin Nombre")["id"]))
        self.assertEqual([(t["code"], t["label"]) for t in unnamed], [(None, "Track 1 · AAC Stereo"), (None, "Track 2 · AAC Stereo")])
        one = media.audio_tracks(media.probe(self.one), LIBRARY.item(self.movie("Una Voz")["id"]))
        self.assertEqual([(t["code"], t["by"]) for t in one], [("es-419", "name")])

    def test_a_titles_details(self):
        m = self.movie("Dos Voces")
        d = details.for_item(LIBRARY.item(m["id"]), media.caps_from({"mkv": ["1"]}), m, admin=True)
        self.assertTrue(d["read"])
        self.assertEqual((d["video"]["quality"], d["video"]["codec"], d["video"]["fps"]), ("240p", "H.264 4:4:4", 24.0))
        self.assertEqual([(a["name"], a["layout"], a["codec"], a["by"]) for a in d["audio"]],
                         [("English", "5.1", "AAC", "tag"), ("Spanish (Latin America)", "Stereo", "AAC", "tag")])
        self.assertEqual([(s["name"], s["kind"], s["forced"], s["sdh"]) for s in d["subs"]],
                         [("Spanish", "text", False, False), ("English", "text", False, True), ("French", "file", True, False)])
        self.assertEqual(d["file"]["size"], os.path.getsize(self.dual))
        self.assertEqual(d["file"]["name"], "Dos Voces (2020).mkv")
        self.assertGreater(d["file"]["bit_rate"], 0)
        self.assertEqual(d["play"]["mode"], "transcode")                       # (4:4:4 colour: no browser plays it)
        self.assertNotIn("name", details.for_item(LIBRARY.item(m["id"]), {}, m)["file"])      # not an admin: no file name
        unnamed = self.movie("Sin Nombre")
        d = details.for_item(LIBRARY.item(unnamed["id"]), {}, unnamed)
        self.assertEqual([a["code"] for a in d["audio"]], [None, None])
        self.assertEqual(d["languages"]["named"], ["en", "es"])

    def test_how_big_a_picture_is_called(self):
        for w, h, want in ((3840, 2160, "4K"), (3840, 1600, "4K"), (1920, 1080, "1080p"), (1920, 800, "1080p"),
                           (1280, 720, "720p"), (1280, 534, "720p"), (720, 576, "576p"), (720, 480, "480p"), (640, 360, "360p")):
            self.assertEqual(details.quality({"width": w, "height": h}), want, (w, h))


def movie(title):
    return next(m for m in LIBRARY.public()["movies"] if m["title"] == title)


@unittest.skipUnless(media.tool("ffmpeg") and media.tool("ffprobe"), "needs ffmpeg")
class Tidied(unittest.TestCase):
    """Sofa gives files and folders tidy names, and the old ones are where the languages were written."""

    def test_a_name_sofa_tidies_away_is_remembered(self):
        from sofa import organizer
        movies = config.path("movies")
        make(os.path.join(movies, "Ordenada.2016.1080p.BluRay.[jpn+spa]", "ordenada.2016.mkv"), [(None, None, 2), (None, None, 2)])
        self.addCleanup(shutil.rmtree, os.path.join(movies, "Ordenada (2016)"), True)
        self.addCleanup(shutil.rmtree, os.path.join(movies, "Ordenada.2016.1080p.BluRay.[jpn+spa]"), True)
        config.update({"tidy_library": True})
        self.addCleanup(config.update, {"tidy_library": False})
        organizer.tidy_library()                                                 # "Ordenada (2016)": the marker is gone
        self.assertTrue(os.path.isdir(os.path.join(movies, "Ordenada (2016)")))
        LIBRARY.scan("tests", quick=True)
        self.assertEqual(movie("Ordenada")["langs"], {"a": ["ja", "es"], "by": "name"})
        inbox = os.path.join(config.path("inbox"), "Llegada.2015.1080p.LAT.mkv")
        make(inbox, [(None, None, 2)])
        from unittest import mock
        with mock.patch.object(organizer, "SETTLE_SECONDS", 0):
            organizer.process_inbox()                                            # (seen once, then filed)
            organizer.process_inbox()
        self.addCleanup(shutil.rmtree, os.path.join(movies, "Llegada (2015)"), True)
        LIBRARY.scan("tests", quick=True)
        self.assertEqual(movie("Llegada")["langs"], {"a": ["es-419"], "by": "name"})
        self.assertEqual(os.listdir(os.path.join(movies, "Llegada (2015)")), ["Llegada (2015).mkv"])
        languages.remember("/somewhere/Plain (2001).mkv", "Plain.2001.1080p.x264")    # says nothing: nothing kept
        self.assertNotIn("/somewhere/Plain (2001).mkv", languages.remembered())


if __name__ == "__main__":
    unittest.main()
