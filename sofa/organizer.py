"""The Inbox: drop files or folders in, Sofa names them properly and files them away.

A dropped item is left alone until it has stopped changing (so half-copied
downloads are never touched). Then every video in it is identified:

* episodes  -> Shows/<Show>/Season N/<Show> SxxEyy <Title>.ext
* movies    -> Movies/<Title (Year)>/<Title (Year)>.ext
* songs     -> Music/<Artist>/<Album>/<NN Title>.ext   (from the file's tags, or "Artist - Title")
* anything in Inbox/Music Videos/ -> Music Videos/<Artist>/<Title>.ext
* anything in Inbox/XXX/ -> Adult/Movies/<Title (Year)>/... or Adult/Shows/<Show>/Season N/...
* a folder of several movies ("Star Wars Collection") -> Movies/<Name> Collection/<Title (Year)>/...
* anything Sofa can't identify, and duplicates, go to Needs Review/ with a note
  on the admin page. Nothing is ever deleted.
"""
import os
import re
import shutil
import time

from . import config, media, metadata, music, naming, places, sidecars, store

SETTLE_SECONDS = 30


_seen = {}   # entry path -> (size, newest mtime) at the last look
DROP_FOLDERS = {"music videos": "musicvideo", "music": "music", "xxx": "adult", "adult": "adult",
                "porn": "adult", "nsfw": "adult"}   # permanent folders inside the Inbox


def _footprint(path):
    total, newest = 0, 0
    if os.path.isfile(path):
        st = os.stat(path)
        return st.st_size, st.st_mtime
    for d, _dirs, files in os.walk(path):
        for f in files:
            try:
                st = os.stat(os.path.join(d, f))
            except OSError:
                continue
            total += st.st_size
            newest = max(newest, st.st_mtime)
    return total, newest


def _still_arriving(path):
    for d, _dirs, files in os.walk(path) if os.path.isdir(path) else [(os.path.dirname(path), [], [os.path.basename(path)])]:
        for f in files:
            if os.path.splitext(f)[1].lower() in naming.PARTIAL_EXT:
                return True
    return False


def pending():
    """Inbox entries and whether Sofa is waiting on them (for the admin page)."""
    inbox = config.path("inbox")
    out = []
    if os.path.isdir(inbox):
        for name in sorted(os.listdir(inbox)):
            p = os.path.join(inbox, name)
            if name.startswith("."):
                continue
            if name.lower() in DROP_FOLDERS and os.path.isdir(p):      # the permanent drop folders: list what's in them
                private = DROP_FOLDERS[name.lower()] == "adult"
                out += [{"name": "%s/%s" % (name, "a private item" if private else n), "private": private,
                         "state": "copying" if _still_arriving(os.path.join(p, n)) else "waiting"}
                        for n in sorted(os.listdir(p)) if not n.startswith(".")]
                continue
            out.append({"name": name, "state": "copying" if _still_arriving(p) else "waiting"})
    return out


def process_inbox():
    """Handle every settled inbox entry. Returns how many videos were filed."""
    inbox = config.path("inbox")
    os.makedirs(inbox, exist_ok=True)
    for folder in ("Music", "Music Videos", "XXX"):
        os.makedirs(os.path.join(inbox, folder), exist_ok=True)
    entries = []
    for name in sorted(os.listdir(inbox)):
        if name.startswith("."):
            continue
        hint = DROP_FOLDERS.get(name.lower())
        if hint and os.path.isdir(os.path.join(inbox, name)):
            entries += [(os.path.join(inbox, name, n), hint) for n in sorted(os.listdir(os.path.join(inbox, name)))
                        if not n.startswith(".")]
        else:
            entries.append((os.path.join(inbox, name), None))
    filed = 0
    for entry, hint in entries:
        if _still_arriving(entry):
            _seen.pop(entry, None)
            continue
        size, newest = _footprint(entry)
        if _seen.get(entry) != (size, newest) or time.time() - newest < SETTLE_SECONDS:
            if entry not in _seen:
                _note_arrival(entry, hint, size)
            _seen[entry] = (size, newest)
            continue
        _seen.pop(entry, None)
        filed += _handle(entry, hint)
    return filed


def _note_arrival(entry, hint, size):
    rel = os.path.relpath(entry, config.path("inbox"))
    count = sum(len(fs) for _d, _s, fs in os.walk(entry)) if os.path.isdir(entry) else 1
    text = "%s in the Inbox (%d file%s, %.1f GB). Waiting until the copy has finished." % (
        "A folder" if os.path.isdir(entry) else "A file", count, "" if count == 1 else "s", size / 1e9)
    if hint == "adult":
        store.log_private("inbox", "Something arrived in Inbox/XXX. Waiting until the copy has finished.",
                          {"entry": rel, "files": count, "bytes": size})
    else:
        store.log("inbox", "\"%s\" arrived: %s" % (rel, text[0].lower() + text[1:]), {"entry": rel, "files": count, "bytes": size})


def _handle(entry, hint=None):
    if hint == "adult" and os.path.isdir(entry):
        target = _adult_folder_target(entry)
        if target:                                   # a category ("Hentai") or a collection: keep its shape
            n = sum(1 for _d, _s, fs in os.walk(entry) for f in fs if os.path.splitext(f)[1].lower() in naming.VIDEO_EXT)
            _merge_into(entry, target)
            store.log_private("inbox", "Added a folder of %d video%s to Adult" % (n, "" if n == 1 else "s"),
                              {"folder": entry, "into": target, "videos": n, "why": "a folder named like a category or a collection keeps its shape"})
            return n
    wanted = naming.VIDEO_EXT | music.AUDIO_EXT
    videos = []
    if os.path.isfile(entry):
        if os.path.splitext(entry)[1].lower() in wanted:
            videos.append(entry)
    else:
        for d, dirs, files in os.walk(entry):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for f in files:
                if os.path.splitext(f)[1].lower() in wanted and not f.startswith("._"):
                    videos.append(os.path.join(d, f))
    filed = 0
    del _filed_now[:]
    collection = _collection_of(entry, videos) if hint != "musicvideo" else None
    if videos and hint != "adult":
        store.log("inbox", "Sorting \"%s\": %d file%s%s" % (os.path.basename(entry), len(videos), "" if len(videos) == 1 else "s",
                  ", as the collection \"%s\"" % collection if collection else ""), {"entry": entry, "files": [os.path.basename(v) for v in videos][:50]})
    elif hint == "adult":
        store.log_private("review", "Nothing to play in a private item; it goes to Needs Review", {"entry": entry})
    else:
        store.log("review", "Nothing to play in \"%s\"; it goes to Needs Review" % os.path.basename(entry), {"entry": entry})
    for v in sorted(videos):
        is_audio = os.path.splitext(v)[1].lower() in music.AUDIO_EXT
        if not is_audio and _is_sample(v):
            if hint == "adult":
                store.log_private("inbox", "Skipped a sample file", {"file": v})
            else:
                store.log("inbox", "Skipped a sample file: %s" % os.path.basename(v), {"file": v})
            continue
        try:
            if is_audio and hint != "adult":
                filed += 1 if _file_song(v) else 0
            elif hint == "musicvideo":
                filed += 1 if _file_music_video(v, entry) else 0
            elif not is_audio:
                filed += 1 if _file_video(v, entry, adult=hint == "adult", collection=collection) else 0
        except OSError as exc:
            if hint == "adult":
                store.log_private("review", "Couldn't move a private file (%s)" % exc.strerror, {"file": v, "error": str(exc)})
            else:
                store.log("review", "Couldn't move %s: %s" % (os.path.basename(v), exc), {"file": v})
    _sweep_leftovers(entry, private=hint == "adult", filed=_filed_now)
    return filed


def _adult_folder_target(entry):
    """Where a folder dropped in Inbox/XXX goes as a whole: Adult/<Category> for "Hentai", "Series",
    "Collections" and the like; Adult/Movies/<Name> for a pack of several scenes. None: file it piece by piece."""
    from .library import Library
    name = os.path.basename(entry)
    root = config.path("adult")
    if name.lower() in naming.ADULT_CATEGORIES:
        return os.path.join(root, name[:1].upper() + name[1:])
    if Library.looks_like_show(entry) or naming.season_of_dir(name) is not None:
        return None
    try:
        subs = [os.path.join(entry, s) for s in os.listdir(entry) if os.path.isdir(os.path.join(entry, s))]
    except OSError:
        return None
    vids = [os.path.join(entry, f) for f in os.listdir(entry) if os.path.splitext(f)[1].lower() in naming.VIDEO_EXT]
    if any(_has_video(s) for s in subs) or len(Library.movie_groups(vids)) >= 2:
        return os.path.join(root, "Movies", naming.safe_filename(naming.clean(name) or name))
    return None


def _has_video(d):
    for _dd, _ss, fs in os.walk(d):
        if any(os.path.splitext(f)[1].lower() in naming.VIDEO_EXT for f in fs):
            return True
    return False


def _merge_into(src, dest):
    """Move everything in folder `src` into `dest`, keeping sub-folders; nothing is overwritten."""
    os.makedirs(dest, exist_ok=True)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dest, name)
        if os.path.isdir(s) and os.path.isdir(d):
            _merge_into(s, d)
        else:
            shutil.move(s, _free_name(d) if os.path.exists(d) else d)
    if not [n for n in os.listdir(src) if n != ".DS_Store"]:
        shutil.rmtree(src, ignore_errors=True)


def _collection_of(entry, videos):
    """'Star Wars Collection' when a dropped folder holds several different movies (not episodes)."""
    if not os.path.isdir(entry):
        return None
    titles = set()
    for v in videos:
        stem = os.path.splitext(os.path.basename(v))[0]
        if os.path.splitext(v)[1].lower() not in naming.VIDEO_EXT or naming.parse_episode(stem) or _is_sample(v):
            continue
        titles.add(naming.norm(naming.strip_part(naming.parse_movie(stem)[0])))
    name = os.path.basename(entry)
    if len(titles) < 2 or naming.parse_episode(name) or naming.season_of_dir(name) is not None:
        return None
    first_words = {t[:4] for t in titles}
    if naming.COLLECTION_WORDS.search(name) or len(first_words) == 1:
        return naming.safe_filename(naming.collection_name(name))
    return None


def _is_sample(path):
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    return ("sample" in re.split(r"[^a-z]+", stem) or "trailer" in stem) and os.path.getsize(path) < 150 * 2**20


def _folder_hint(video, entry):
    """Name of the folder the video came in (inside the inbox), minus season/quality noise."""
    rel = os.path.relpath(os.path.dirname(video), os.path.dirname(entry)) if os.path.isdir(entry) else "."
    parts = [p for p in rel.split(os.sep) if p not in (".", "")]
    for p in reversed(parts):
        if naming.season_of_dir(p) is not None:
            continue
        p = re.sub(r"[\s._-]*(s\d{1,2}(e\d+)?|season[\s._-]*\d{1,2}|complete)\b.*$", "", p, flags=re.I)
        p = naming.clean(p)
        if p:
            return p
    return None


def _season_hint(video):
    return naming.season_of_dir(os.path.basename(os.path.dirname(video)))


def _existing_show(name):
    """The folder of a show already in the library, in any place (so new episodes join it there)."""
    if not name:
        return None
    key = naming.norm(name)
    for _ak, root in places.roots("shows"):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for d in names:
            if os.path.isdir(os.path.join(root, d)) and naming.norm(d) == key:
                return os.path.join(root, d)
    return None


def _new_root(key):
    """Where something new goes: the place chosen under Server → Storage (the main folders by default)."""
    return places.section(key, places.target())


def _resolve_show(name, year=None):
    """(The show's folder, in whichever place it is or goes, and its TVmaze details), or None when Sofa isn't confident."""
    if not name:
        return None
    existing = _existing_show(name)
    if existing:
        return existing, None
    show = metadata.tv_show(name, year)
    if show:
        canonical = show.get("name") or name
        a, b = naming.norm(canonical), naming.norm(name)
        if a and b and (a.startswith(b) or b.startswith(a)):
            return _existing_show(canonical) or os.path.join(_new_root("shows"), naming.safe_filename(canonical)), show
        return None
    return os.path.join(_new_root("shows"), naming.safe_filename(name.title() if name.islower() else name)), None


def _file_video(video, entry, adult=False, collection=None):
    stem, ext = os.path.splitext(os.path.basename(video))
    folder = _folder_hint(video, entry)
    ep = naming.parse_episode(stem, _season_hint(video), in_show=bool(folder))
    if not ep and not adult:
        ep = naming.parse_dated(stem)               # "The Daily Show 2024 03 15"
    shows_root = os.path.join(_new_root("adult"), "Shows") if adult else _new_root("shows")
    side = sidecars.read(video)
    if ep and adult:
        show_name = naming.safe_filename(naming.show_name(ep["show"] or folder or "Unsorted")[0])
        code = "S%02dE%02d" % (ep["s"], ep["e"])
        new = naming.safe_filename("%s %s %s" % (show_name, code, ep["title"]) if ep["title"] else "%s %s" % (show_name, code))
        dest = os.path.join(shows_root, show_name, "Season %d" % ep["s"], new + ext.lower())
        return _move(video, dest, "Added 1 episode to Adult", private=True,
                     why="episode %s read from the name %r; series %r from %s" % (code, stem, show_name, "the name" if ep["show"] else "the folder"))
    if ep:
        name, year = naming.show_name(ep["show"] or folder or "")   # "Doctor.Who.2005" is "Doctor Who" (2005)
        if not name:
            return _to_review(video, "This looks like an episode, but the name doesn't say of which show. Rename it like "
                                     "\"Show Name S01E02.mkv\" and drop it in the Inbox again.")
        resolved = _resolve_show(name, year) or (os.path.join(_new_root("shows"), naming.safe_filename(
            (name.title() if name.islower() else name) + (" (%d)" % year if year else ""))), None)
        show_dir, show_meta = resolved
        show_name = os.path.basename(show_dir)
        title = ep["title"]
        if show_meta:
            meta = metadata.episodes(show_meta).get((ep["s"], ep["e"]))
            title = (meta or {}).get("title") or title
        code = "S%02dE%02d" % (ep["s"], ep["e"]) + ("-E%02d" % ep["e2"] if ep.get("e2") else "")
        folder = "Specials" if ep["s"] == 0 else "Season %d" % ep["s"]
        new = naming.safe_filename("%s %s %s" % (show_name, code, title) if title else "%s %s" % (show_name, code))
        dest = os.path.join(show_dir, folder, new + ext.lower())
        return _move(video, dest, "Added %s %s to Shows" % (show_name, code),
                     why="episode %s read from the name %r; show %r %s" % (
                         code, stem, show_name, "matched on TVmaze" if show_meta else "already in Shows" if _existing_show(show_name)
                         else "from the %s (no TVmaze match)" % ("name" if ep["show"] else "folder")))

    title, year = naming.parse_movie(stem)
    title = naming.strip_part(title)
    if not year and folder and not collection:
        t2, y2 = naming.parse_movie(os.path.basename(os.path.dirname(video)))
        if y2:
            title, year = t2, y2
    if adult:
        scene = naming.parse_scene(stem)
        title = side.get("title") or scene.get("title") or title
        year = side.get("year") or year or scene.get("year")
        if not side.get("title") and scene.get("studio") and scene.get("date"):     # a dated scene release
            title = "%s %s %s" % (scene["studio"], scene["date"], scene["title"] or "")
        if not year:
            year = (metadata.movie(title, None, adult=True) or {}).get("year")
        name = naming.safe_filename("%s (%d)" % (title.strip(), year) if year and str(year) not in title else title.strip()) or "Untitled"
        dest = os.path.join(_new_root("adult"), "Movies", name, name + ext.lower())
        return _move(video, dest, "Added 1 video to Adult", private=True,
                     why="title %r from %s" % (title, "the saved link/.nfo" if side.get("title") else "the scene name" if scene.get("studio") else "the file name"))
    how = "the file name %r" % stem if naming.parse_movie(stem)[1] else "the folder name" if year else "?"
    if side.get("title") and not naming.parse_movie(stem)[1] and side.get("year"):    # saved from a link
        title, year = naming.clean(side["title"]), side["year"]
        how = "the saved link's details"
    if not year:
        meta = metadata.movie(title, None)
        if meta and meta.get("year"):
            title, year = meta.get("canonical") or title, meta["year"]
            how = "an online lookup of %r (%s)" % (title, meta.get("source") or "online")
    camera = naming.camera_name(stem)
    if camera and not year:                      # a phone or camera clip: the Home Videos collection
        name = naming.safe_filename(camera)
        dest = os.path.join(_new_root("movies"), "Home Videos", name, name + ext.lower())
        return _move(video, dest, "Added %s to Movies (Home Videos)" % name, why="a phone or camera file name (%r)" % stem)
    if not title or len(re.sub(r"[^A-Za-z]", "", title)) < 2:
        return _to_review(video, "Couldn't tell what this is from its name. Name episodes like \"Show S01E02\" and movies "
                                 "like \"Title (1999)\", then drop it in the Inbox again.")
    name = naming.safe_filename("%s (%d)" % (title, year) if year else title)
    if not year:
        how = "the title %r (no year in the name, and no match online: Find details on its page fixes that)" % title
    part = re.search(r"\b(?:cd|disc|part)[\s._-]*(\d)\b", stem, re.I)
    base = os.path.join(_new_root("movies"), collection) if collection else _new_root("movies")
    dest = os.path.join(base, name, name + (" - part%s" % part.group(1) if part else "") + ext.lower())
    return _move(video, dest, "Added %s to Movies%s" % (name, " (%s)" % collection if collection else ""),
                 why="movie: title and year from %s%s" % (how, "; part of the collection %r" % collection if collection else ""))


def _file_song(path):
    stem, ext = os.path.splitext(os.path.basename(path))
    tags = (media.probe(path) or {}).get("tags") or {}
    artist = (tags.get("album_artist") or tags.get("artist") or "").strip()
    title = (tags.get("title") or "").strip()
    if not artist and " - " in stem:
        artist, _, title = stem.partition(" - ")
        artist, title = artist.strip(), music._clean_title(title)
    if not artist:
        return _to_review(path, "Couldn't tell who this song is by. Add artist tags, or name it like "
                                "\"Artist - Title.mp3\", then drop it in the Inbox again.", sub="Music")
    title = title or music._clean_title(stem)
    root = config.path("music")
    existing = next((d for d in (os.listdir(root) if os.path.isdir(root) else [])
                     if naming.norm(d) == naming.norm(artist)), None)
    artist_dir = existing or naming.safe_filename(artist)
    album = (tags.get("album") or "").strip()
    n = music._num(tags.get("track"))
    name = naming.safe_filename(("%02d %s" % (n, title)) if n else title)
    folder = os.path.join(root, artist_dir, naming.safe_filename(album)) if album else os.path.join(root, artist_dir)
    return _move(path, os.path.join(folder, name + ext.lower()), "Added %s by %s to Music" % (title, artist_dir))


def _file_music_video(path, entry):
    stem, ext = os.path.splitext(os.path.basename(path))
    parent = os.path.basename(os.path.dirname(path))
    if " - " in stem:
        artist, _, title = stem.partition(" - ")
    elif os.path.isdir(entry) and parent.lower() not in DROP_FOLDERS:
        artist, title = parent, stem
    else:
        return _to_review(path, "Name music videos like \"Artist - Title.mp4\" (or put them in a folder named "
                                "after the artist inside Inbox/Music Videos).", sub="Music Videos")
    title = re.sub(r"\s*[\(\[](official|music|lyric|hd|4k)[^\)\]]*[\)\]]", "", title, flags=re.I).strip()
    artist, title = naming.safe_filename(artist.strip()), naming.safe_filename(title)
    dest = os.path.join(config.path("musicvideos"), artist, title + ext.lower())
    return _move(path, dest, "Added the %s video \"%s\" to Music Videos" % (artist, title))


_filed_now = []        # (original path, new path) of the videos filed from the drop being handled


def _move(src, dest, message, private=False, why=None):
    if os.path.exists(dest):
        if os.path.getsize(dest) == os.path.getsize(src):
            return _to_review(src, "Already in the library: %s" % os.path.relpath(dest, os.path.dirname(config.path("shows"))),
                              sub="Duplicates", private=private)
        return _to_review(src, "A different file already has this name: %s" % os.path.basename(dest), private=private)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    stem_src = os.path.splitext(src)[0]
    stem_dest = os.path.splitext(dest)[0]
    shutil.move(src, dest)
    _filed_now.append((src, dest))
    for f in os.listdir(os.path.dirname(src)):     # subtitles and thumbnails that share the name
        p = os.path.join(os.path.dirname(src), f)
        base, ext = os.path.splitext(p)
        if base == stem_src or base.startswith(stem_src + "."):
            if ext.lower() in naming.SUB_EXT or ext.lower() in (".jpg", ".png", ".nfo", ".json"):
                suffix = base[len(stem_src):]
                target = stem_dest + suffix + ext.lower()
                if ext.lower() in (".jpg", ".png"):
                    target = os.path.join(os.path.dirname(dest), "metadata", os.path.basename(stem_dest) + ext.lower())
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                if not os.path.exists(target):
                    shutil.move(p, target)
    detail = {"from": src, "to": dest}
    if why:
        detail["why"] = why
    if private:
        store.log_private("inbox", message, detail)
    else:
        store.log("inbox", message, detail)
    return True


def _to_review(path, why, sub="From Inbox", private=False):
    dest_dir = os.path.join(config.path("review"), "XXX", sub) if private else os.path.join(config.path("review"), sub)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(path))
    n = 2
    while os.path.exists(dest):
        base, ext = os.path.splitext(os.path.basename(path))
        dest = os.path.join(dest_dir, "%s (%d)%s" % (base, n, ext))
        n += 1
    shutil.move(path, dest)
    if private:
        store.log_private("review", "A private file needs a look (in Needs Review/XXX/%s)" % sub, {"file": path, "now_in": dest, "why": why})
    else:
        store.log("review", why, {"file": os.path.basename(path), "now_in": dest})
    return False


SUB_LANGS = {"english": "en", "eng": "en", "spanish": "es", "espanol": "es", "español": "es", "spa": "es", "french": "fr",
             "fre": "fr", "fra": "fr", "german": "de", "ger": "de", "deu": "de", "italian": "it", "ita": "it", "portuguese": "pt",
             "por": "pt", "brazilian": "pt-BR", "dutch": "nl", "dut": "nl", "russian": "ru", "rus": "ru", "japanese": "ja",
             "jpn": "ja", "chinese": "zh", "chi": "zh", "korean": "ko", "kor": "ko", "arabic": "ar", "ara": "ar", "swedish": "sv",
             "danish": "da", "norwegian": "no", "finnish": "fi", "polish": "pl", "turkish": "tr", "greek": "el", "hebrew": "he"}


def _sub_lang(path):
    words = re.findall(r"[a-zà-ÿ]+", os.path.splitext(os.path.basename(path))[0].lower())
    for w in reversed(words):
        if w in SUB_LANGS:
            return SUB_LANGS[w] + (".sdh" if "sdh" in words or "hi" in words else "") + (".forced" if "forced" in words else "")
        if len(w) == 2 and w in SUB_LANGS.values():
            return w
    return "und"


def _attach_subtitles(entry, filed):
    """Subtitles left in a dropped folder ("Subs/English.srt", "Subs/Show.S01E02/2_English.srt") go next to
    their video, named so Sofa offers them in the player."""
    if not filed:
        return
    codes = {}
    for src, dest in filed:
        ep = naming.parse_episode(os.path.splitext(os.path.basename(dest))[0], in_show=True)
        if ep:
            codes[(ep["s"], ep["e"])] = dest
    for d, _dirs, files in os.walk(entry):
        for f in files:
            if os.path.splitext(f)[1].lower() not in naming.SUB_EXT:
                continue
            p = os.path.join(d, f)
            target = None
            if len(filed) == 1:
                target = filed[0][1]
            else:
                ep = naming.parse_episode(os.path.relpath(p, entry).replace(os.sep, " "), in_show=True)
                target = codes.get((ep["s"], ep["e"])) if ep else None
            if not target:
                continue
            base = os.path.splitext(target)[0] + "." + _sub_lang(p)
            dest, n = base + os.path.splitext(f)[1].lower(), 2
            while os.path.exists(dest):
                dest, n = "%s-%d%s" % (base, n, os.path.splitext(f)[1].lower()), n + 1
            try:
                shutil.move(p, dest)
            except OSError:
                pass


ART_NAMES = {"poster": "folder", "folder": "folder", "cover": "folder", "fanart": "backdrop", "backdrop": "backdrop",
             "background": "backdrop", "logo": "logo", "clearlogo": "logo"}


def _attach_artwork(entry, filed):
    """A poster.jpg / fanart.jpg / movie.nfo that came with a single movie goes with it."""
    if len(filed) != 1:
        return
    dest_dir = os.path.dirname(filed[0][1])
    if dest_dir in places.all_section_roots():
        return                                     # not in a folder of its own
    for d, _dirs, files in os.walk(entry):
        for f in files:
            base, ext = os.path.splitext(f.lower())
            p = os.path.join(d, f)
            if base == "movie" and ext == ".nfo":
                target = os.path.join(dest_dir, "movie.nfo")
            elif base in ART_NAMES and ext in (".jpg", ".jpeg", ".png"):
                kind = ART_NAMES[base]
                target = os.path.join(dest_dir, kind + (".png" if kind == "logo" else ".jpg"))
                if ext == ".png" and kind != "logo":
                    target = os.path.join(dest_dir, kind + ".png")
            else:
                continue
            if not os.path.exists(target):
                try:
                    shutil.move(p, target)
                except OSError:
                    pass


JUNK_EXT = (".nfo", ".txt", ".url", ".website", ".lnk", ".exe", ".sfv", ".md5", ".nzb", ".torrent", ".srr", ".sub.idx",
            ".db", ".ini", ".log", ".html", ".htm", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".dat")


def _sweep_leftovers(entry, private=False, filed=()):
    """Once the videos are out: subtitles join their video, release clutter (.nfo, .txt, links,
    samples, screenshots) goes to the Deleted folder, and only what's left goes to Needs Review."""
    if not os.path.exists(entry):
        return
    if os.path.isdir(entry):
        _attach_subtitles(entry, filed)
        _attach_artwork(entry, filed)
        clutter = []
        for d, _dirs, files in os.walk(entry):
            for f in files:
                p = os.path.join(d, f)
                low = f.lower()
                if f == ".DS_Store" or f.startswith("._"):
                    os.remove(p)
                elif low.endswith(JUNK_EXT) or (os.path.splitext(low)[1] in naming.VIDEO_EXT and _is_sample(p)):
                    clutter.append(p)
        for p in clutter:
            try:
                _put_aside(p)
            except OSError:
                pass
        if clutter:
            note = "Put %d leftover file%s (.nfo, .txt, samples, ...) in the Deleted folder" % (len(clutter), "" if len(clutter) == 1 else "s")
            if private:
                store.log_private("inbox", note, {"files": clutter[:30]})
            else:
                store.log("inbox", note, {"files": [os.path.basename(c) for c in clutter][:30]})
        remaining = [f for _d, _dirs, files in os.walk(entry) for f in files]
        if not remaining:
            shutil.rmtree(entry, ignore_errors=True)   # nothing left but empty folders
            return
    dest = os.path.join(config.path("review"), *(["XXX"] if private else []), "Inbox leftovers", os.path.basename(entry))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest):
        shutil.move(entry, dest)
        if private:
            store.log_private("review", "Moved leftover files of a private item to Needs Review/XXX", {"entry": entry, "now_in": dest})
        else:
            store.log("review", "Moved leftover files from \"%s\" to Needs Review" % os.path.basename(entry), {"now_in": dest})


# ---------------------------------------------------------------- tidying what's already in the library

def tidy_library():
    """Put existing folders into the shape Sofa expects. Returns how many things it moved or renamed.

    * "XXX", "Adult", "Porn" folders inside Shows/, Movies/ or next to them go to the Inbox's XXX
      folder, which files them into the Adult section.
    * A collection folder with loose movies ("Star Wars Collection/Star.Wars.1977.mkv, ...") gets a
      folder per movie, and a tidy name.
    * Movie folders named like downloads ("Heat.1995.1080p.BluRay") become "Heat (1995)".
    * Show folders named like downloads ("The.Sopranos.S01-S06.1080p") become "The Sopranos".
    Nothing is deleted, and watch progress stays (it isn't tied to file names).
    """
    if not config.get("tidy_library"):
        return 0
    done = 0
    try:
        done += _adopt_adult_folders()
        for _ak, root in places.roots("movies"):
            done += _tidy_movies(root)
        for _ak, root in places.roots("shows"):
            done += _tidy_shows(root)
    except OSError as exc:
        store.log("error", "Tidying the library: %s" % exc)
    return done


def _same(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.abspath(a) == os.path.abspath(b)


def _free_name(path):
    n, base = 2, path
    while os.path.exists(path):
        path = "%s (%d)" % (base, n)
        n += 1
    return path


def _adopt_adult_folders():
    adult, moved = config.path("adult"), 0
    drop = os.path.join(config.path("inbox"), "XXX")
    for root in (config.path("shows"), config.path("movies"), os.path.dirname(config.path("shows"))):
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            p = os.path.join(root, name)
            if not os.path.isdir(p) or not naming.is_adult_dir(name) or _same(p, adult) or _same(p, drop):
                continue
            if os.path.abspath(adult).startswith(os.path.abspath(p) + os.sep):
                continue
            # Its folders (Movies, Hentai, Series, Collections, ...) become categories just as they are.
            moved += len([c for c in os.listdir(p) if not c.startswith(".")])
            _merge_into(p, adult)
            store.log_private("inbox", "Moved the \"%s\" folder from %s into the Adult section, keeping its folders" % (
                name, os.path.basename(root)))
    return moved


def _video_files(d):
    try:
        return [os.path.join(d, f) for f in os.listdir(d) if os.path.splitext(f)[1].lower() in naming.VIDEO_EXT
                and not f.startswith(".") and os.path.isfile(os.path.join(d, f))]
    except OSError:
        return []


def _move_with_sidecars(video, dest_dir, new_stem):
    """Move a video (and its subtitles/thumbnail) into dest_dir, renamed to new_stem."""
    src_dir, name = os.path.split(video)
    stem, ext = os.path.splitext(name)
    os.makedirs(dest_dir, exist_ok=True)
    target = os.path.join(dest_dir, new_stem + ext.lower())
    if os.path.exists(target):
        return False
    shutil.move(video, target)
    for f in os.listdir(src_dir):
        base, e = os.path.splitext(f)
        if (base == stem or base.startswith(stem + ".")) and (e.lower() in naming.SUB_EXT or e.lower() in (".jpg", ".png", ".nfo")):
            dest = os.path.join(dest_dir, new_stem + base[len(stem):] + e.lower())
            if not os.path.exists(dest):
                shutil.move(os.path.join(src_dir, f), dest)
    return True


def _movie_stem(video):
    title, year = naming.parse_movie(os.path.splitext(os.path.basename(video))[0])
    title = naming.strip_part(title)
    if not year:
        meta = metadata.movie(title, None) or {}
        year = meta.get("year")
    return naming.safe_filename("%s (%d)" % (title, year) if year else title), title


def _tidy_movies(root):
    from .library import Library
    if not os.path.isdir(root):
        return 0
    done = 0
    loose = Library.movie_groups(_video_files(root))
    for files in loose.values():                      # loose movies right in Movies/: one folder each
        if len(files) == 1:
            stem, _ = _movie_stem(files[0])
            if "(" in stem and _move_with_sidecars(files[0], os.path.join(root, stem), stem):
                done += 1
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if name.startswith(".") or not os.path.isdir(d):
            continue
        vids = _video_files(d)
        groups = Library.movie_groups(vids)
        if len(groups) >= 2:                          # a collection with loose movies in it
            for files in groups.values():
                if len(files) != 1:
                    continue
                stem, _ = _movie_stem(files[0])
                if _move_with_sidecars(files[0], os.path.join(d, stem), stem):
                    done += 1
            nice = naming.safe_filename(naming.collection_name(name))
            if nice and nice != name and not os.path.exists(os.path.join(root, nice)):
                os.rename(d, os.path.join(root, nice))
                done += 1
            store.log("inbox", "Gave each movie in \"%s\" its own folder" % (nice or name))
        elif vids:                                    # one movie: tidy the folder name
            title, year = naming.parse_movie(name)
            nice = naming.safe_filename("%s (%d)" % (naming.strip_part(title), year)) if year else None
            if nice and nice != name and not os.path.exists(os.path.join(root, nice)):
                os.rename(d, os.path.join(root, nice))
                store.log("inbox", "Renamed the movie folder \"%s\" to \"%s\"" % (name, nice))
                done += 1
        else:                                         # a collection of movie folders
            for sub in sorted(os.listdir(d)):
                sd = os.path.join(d, sub)
                if os.path.isdir(sd) and not sub.startswith(".") and _video_files(sd):
                    title, year = naming.parse_movie(sub)
                    nice = naming.safe_filename("%s (%d)" % (naming.strip_part(title), year)) if year else None
                    if nice and nice != sub and not os.path.exists(os.path.join(d, nice)):
                        os.rename(sd, os.path.join(d, nice))
                        done += 1
    return done


def _tidy_shows(root):
    if not os.path.isdir(root):
        return 0
    done = 0
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if name.startswith(".") or not os.path.isdir(d):
            continue
        show, year = naming.show_name(name)
        nice = naming.safe_filename(show + (" (%d)" % year if year else ""))
        if not nice or nice == name:
            continue
        target = os.path.join(root, nice)
        if os.path.exists(target):
            continue
        os.rename(d, target)
        store.log("inbox", "Renamed the show folder \"%s\" to \"%s\"" % (name, nice))
        done += 1
    return done


# ---------------------------------------------------------------- moving and deleting from the app

SIDE_EXT = tuple(naming.SUB_EXT) + (".jpg", ".png", ".nfo", ".json")
LIBRARY_KEYS = ("shows", "movies", "adult")


def _sidecars_of(video):
    """Subtitles, .nfo, .info.json and pictures that belong to `video`."""
    d, name = os.path.split(video)
    stem = os.path.splitext(name)[0]
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        names = []
    for f in names:
        p = os.path.join(d, f)
        base, ext = os.path.splitext(f)
        if p != video and (base == stem or base.startswith(stem + ".")) and ext.lower() in SIDE_EXT and os.path.isfile(p):
            out.append(p)
    still = os.path.join(d, "metadata", stem + ".jpg")
    if os.path.isfile(still):
        out.append(still)
    return out


def _free_path(path):
    base, ext = os.path.splitext(path) if os.path.isfile(path) or os.path.splitext(path)[1] else (path, "")
    n = 2
    while os.path.exists(path):
        path = "%s (%d)%s" % (base, n, ext)
        n += 1
    return path


def deleted_root():
    return config.path("deleted") if config.get("deleted") else os.path.join(os.path.dirname(config.path("shows")), "Deleted")


def _videos_under(d, limit=2):
    found = []
    for dd, _dirs, files in os.walk(d):
        found += [os.path.join(dd, f) for f in files if os.path.splitext(f)[1].lower() in naming.VIDEO_EXT]
        if len(found) >= limit:
            break
    return found


def _own_folder(video):
    """The biggest folder that holds nothing but this video (a movie's own folder, with its poster)."""
    roots = set(places.all_section_roots(LIBRARY_KEYS))
    d, top = os.path.dirname(os.path.abspath(video)), None
    while _in_library(d) and d not in roots and _videos_under(d) == [os.path.abspath(video)]:
        top, d = d, os.path.dirname(d)
    return top


def _deleted_for(path):
    """The Deleted folder on the same drive as `path`."""
    return os.path.join(places.place_of(path)["path"], "Deleted") if places.place_of(path) else deleted_root()


def _put_aside(path):
    """Move a file or folder into the Deleted folder, keeping where it was (Deleted/Movies/..., Deleted/XXX/...)."""
    rel = os.path.basename(path)
    candidates = [(k, root) for k in LIBRARY_KEYS for _ak, root in places.roots(k)] + [(k, config.path(k)) for k in ("review", "inbox")]
    for key, root in candidates:
        root = os.path.abspath(root)
        if os.path.abspath(path).startswith(root + os.sep):
            rel = os.path.join("XXX" if key == "adult" else os.path.basename(root), os.path.relpath(path, root))
            break
    dest = _free_path(os.path.join(_deleted_for(path), rel))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(path, dest)
    return dest


def _in_library(path):
    p = os.path.abspath(path)
    return any(p.startswith(r + os.sep) for r in places.all_section_roots(LIBRARY_KEYS))


def _tidy_after(folder):
    """A folder left without any video (a movie's folder with just its poster) goes to Deleted too."""
    roots = set(places.all_section_roots(LIBRARY_KEYS))
    d, top = os.path.abspath(folder), None
    while _in_library(d) and d not in roots and os.path.isdir(d) and not _has_video(d):
        top, d = d, os.path.dirname(d)
    if top:
        _put_aside(top)


def _year(value):
    try:
        y = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return y if 1880 <= y <= 2100 else None


def relocate(path, target, private=False):
    """An admin says this video is out of place. `target`: {"kind": "movie", "title", "year"} |
    {"kind": "episode", "show", "season", "episode"} | {"kind": "adult", "category", "title"} |
    {"kind": "review"} | {"kind": "delete"}. Returns a sentence saying where it went."""
    if not _in_library(path) or not os.path.isfile(path):
        raise ValueError("Sofa can only move videos that are in the library.")
    kind = target.get("kind")
    src_dir = os.path.dirname(path)
    stem, ext = os.path.splitext(os.path.basename(path))
    ext = ext.lower()
    if kind == "delete":
        own = _own_folder(path)
        if own:                                     # its own folder, poster and all
            _put_aside(own)
        else:
            for p in _sidecars_of(path) + [path]:
                _put_aside(p)
            _tidy_after(src_dir)
        if private:
            store.log_private("library", "Moved a private video to the Deleted folder")
        else:
            store.log("library", "Moved %s to the Deleted folder" % os.path.basename(path))
        return "Moved to the Deleted folder. You can get it back from there until it's emptied."
    if kind == "review":
        sub = os.path.join("XXX", "From the app") if private else "From the app"
        dest = os.path.join(config.path("review"), sub, stem + ext)
        where = "Needs Review"
    elif kind == "movie":
        title = naming.safe_filename((target.get("title") or "").strip())
        if not title:
            raise ValueError("Type the movie's title.")
        year = _year(target.get("year"))
        name = "%s (%d)" % (title, year) if year else title
        dest = os.path.join(places.section("movies", places.place_of(path)), name, name + ext)
        where = "Movies, as %s" % name
    elif kind == "episode":
        show = (target.get("show") or "").strip()
        try:
            s, e = int(target.get("season")), int(target.get("episode"))
        except (TypeError, ValueError):
            raise ValueError("Type the season and episode numbers.")
        if not show or s < 0 or e < 1:
            raise ValueError("Type the show's name, the season and the episode.")
        show_dir = _existing_show(show) or os.path.join(places.section("shows", places.place_of(path)), naming.safe_filename(show))
        show_name = os.path.basename(show_dir)
        code = "S%02dE%02d" % (s, e)
        dest = os.path.join(show_dir, "Specials" if s == 0 else "Season %d" % s, "%s %s%s" % (show_name, code, ext))
        where = "Shows, as %s %s" % (show_name, code)
    elif kind == "adult":
        category = naming.safe_filename((target.get("category") or "").strip()) or "Movies"
        title = naming.safe_filename((target.get("title") or "").strip() or naming.clean(stem) or stem) or "Untitled"
        dest = os.path.join(places.section("adult", places.place_of(path)), category, title, title + ext)
        where = "Adult, %s" % category
        private = True
    else:
        raise ValueError("Choose where it goes.")
    if _same(dest, path):
        return "It's already there."
    if os.path.exists(dest):
        raise ValueError("There's already a video with that name there: %s" % os.path.basename(dest))
    old_still = os.path.join(src_dir, "metadata", stem + ".jpg")
    _move(path, dest, "Moved a private video to %s" % where.split(",")[0] if private else
          "Moved %s to %s" % (os.path.basename(path), where), private=private)
    if os.path.isfile(old_still):                  # its picture, if Sofa took one, goes along
        new_still = os.path.join(os.path.dirname(dest), "metadata", os.path.splitext(os.path.basename(dest))[0] + ".jpg")
        if not os.path.exists(new_still):
            os.makedirs(os.path.dirname(new_still), exist_ok=True)
            shutil.move(old_still, new_still)
    _tidy_after(src_dir)
    return "Moved to %s." % ("the Adult section" if kind == "adult" else where)


def relocate_show(folder, target, private=False):
    """Move or delete a whole show's folder: {"kind": "shows"} | {"kind": "adult", "category"} | {"kind": "delete"}."""
    if not _in_library(folder) or not os.path.isdir(folder):
        raise ValueError("Sofa can only move shows that are in the library.")
    kind, name = target.get("kind"), os.path.basename(folder)
    if kind == "delete":
        _put_aside(folder)
        if private:
            store.log_private("library", "Moved a private series to the Deleted folder")
        else:
            store.log("library", "Moved the show %s to the Deleted folder" % name)
        return "Moved to the Deleted folder. You can get it back from there until it's emptied."
    if kind == "shows":
        dest, where = os.path.join(places.section("shows", places.place_of(folder)), name), "Shows"
    elif kind == "adult":
        category = naming.safe_filename((target.get("category") or "").strip()) or "Series"
        dest, where, private = os.path.join(places.section("adult", places.place_of(folder)), category, name), "the Adult section", True
    else:
        raise ValueError("Choose where it goes.")
    if _same(dest, folder):
        return "It's already there."
    if os.path.exists(dest):
        raise ValueError("There's already a folder called %s there." % name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(folder, dest)
    if private:
        store.log_private("library", "Moved a series to %s" % where)
    else:
        store.log("library", "Moved the show %s to %s" % (name, where))
    return "Moved to %s." % where


def _deleted_folders():
    return [deleted_root()] + [os.path.join(p["path"], "Deleted") for p in places.extra() if places.connected(p)]


def deleted_summary():
    files = size = 0
    for root in _deleted_folders():
        for d, _dirs, fs in os.walk(root):
            for f in fs:
                try:
                    size += os.path.getsize(os.path.join(d, f))
                    files += 1
                except OSError:
                    pass
    return {"folder": deleted_root(), "files": files, "bytes": size}


def empty_deleted():
    n = 0
    for root in _deleted_folders():
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            p = os.path.join(root, name)
            try:
                shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
                n += 1
            except OSError:
                pass
    store.log("library", "Emptied the Deleted folder")
    return n
