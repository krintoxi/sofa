"""The Inbox: drop files or folders in, Sofa names them properly and files them away.

A dropped item is left alone until it has stopped changing (so half-copied
downloads are never touched). Then every video in it is identified:

* episodes  -> Shows/<Show>/Season N/<Show> SxxEyy <Title>.ext
* movies    -> Movies/<Title (Year)>/<Title (Year)>.ext
* songs     -> Music/<Artist>/<Album>/<NN Title>.ext   (from the file's tags, or "Artist - Title")
* anything in Inbox/Music Videos/ -> Music Videos/<Artist>/<Title>.ext
* anything Sofa can't identify, and duplicates, go to Needs Review/ with a note
  on the admin page. Nothing is ever deleted.
"""
import os
import re
import shutil
import time

from . import config, media, metadata, music, naming, store

SETTLE_SECONDS = 30


_seen = {}   # entry path -> (size, newest mtime) at the last look
DROP_FOLDERS = {"music videos": "musicvideo", "music": "music"}   # permanent folders inside the Inbox


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
            if not name.startswith("."):
                out.append({"name": name, "state": "copying" if _still_arriving(os.path.join(inbox, name)) else "waiting"})
    return out


def process_inbox():
    """Handle every settled inbox entry. Returns how many videos were filed."""
    inbox = config.path("inbox")
    os.makedirs(inbox, exist_ok=True)
    for folder in ("Music", "Music Videos"):
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
            _seen[entry] = (size, newest)
            continue
        _seen.pop(entry, None)
        filed += _handle(entry, hint)
    return filed


def _handle(entry, hint=None):
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
    for v in sorted(videos):
        is_audio = os.path.splitext(v)[1].lower() in music.AUDIO_EXT
        if not is_audio and _is_sample(v):
            continue
        try:
            if is_audio:
                filed += 1 if _file_song(v) else 0
            elif hint == "musicvideo":
                filed += 1 if _file_music_video(v, entry) else 0
            else:
                filed += 1 if _file_video(v, entry) else 0
        except OSError as exc:
            store.log("review", "Couldn't move %s: %s" % (os.path.basename(v), exc), {"file": v})
    _sweep_leftovers(entry)
    return filed


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
    root = config.path("shows")
    if not os.path.isdir(root) or not name:
        return None
    key = naming.norm(name)
    for d in os.listdir(root):
        if os.path.isdir(os.path.join(root, d)) and naming.norm(d) == key:
            return d
    return None


def _resolve_show(name):
    """Folder name to use under Shows/, or None when Sofa isn't confident."""
    if not name:
        return None
    existing = _existing_show(name)
    if existing:
        return existing, None
    show = metadata.tv_show(name)
    if show:
        canonical = show.get("name") or name
        a, b = naming.norm(canonical), naming.norm(name)
        if a and b and (a.startswith(b) or b.startswith(a)):
            return _existing_show(canonical) or naming.safe_filename(canonical), show
        return None
    return naming.safe_filename(name.title() if name.islower() else name), None


def _file_video(video, entry):
    stem, ext = os.path.splitext(os.path.basename(video))
    ep = naming.parse_episode(stem)
    if not ep and _season_hint(video) is not None:
        m = re.match(r"^(?:e|ep|episode)?\s*(\d{1,3})\b", stem, re.I)
        if m:
            ep = {"s": _season_hint(video), "e": int(m.group(1)), "e2": None, "show": "", "title": naming.clean(stem[m.end():])}
    if ep:
        resolved = _resolve_show(ep["show"] or _folder_hint(video, entry))
        if not resolved:
            return _to_review(video, "Couldn't tell which show this episode belongs to. Rename it like "
                                     "\"Show Name S01E02.mkv\" and drop it in the Inbox again.")
        show_name, show_meta = resolved
        title = ep["title"]
        if show_meta:
            meta = metadata.episodes(show_meta).get((ep["s"], ep["e"]))
            title = (meta or {}).get("title") or title
        code = "S%02dE%02d" % (ep["s"], ep["e"]) + ("-E%02d" % ep["e2"] if ep.get("e2") else "")
        folder = "Specials" if ep["s"] == 0 else "Season %d" % ep["s"]
        new = naming.safe_filename("%s %s %s" % (show_name, code, title) if title else "%s %s" % (show_name, code))
        dest = os.path.join(config.path("shows"), show_name, folder, new + ext.lower())
        return _move(video, dest, "Added %s %s to Shows" % (show_name, code))

    title, year = naming.parse_movie(stem)
    if not year:
        hint = _folder_hint(video, entry)
        if hint:
            t2, y2 = naming.parse_movie(os.path.basename(os.path.dirname(video)))
            if y2:
                title, year = t2, y2
    if not year:
        meta = metadata.movie(title, None)
        if meta and meta.get("year"):
            title, year = meta.get("canonical") or title, meta["year"]
    if not year:
        return _to_review(video, "Couldn't tell what this is. Name episodes like \"Show S01E02\" and movies "
                                 "like \"Title (1999)\", then drop it in the Inbox again.")
    folder = naming.safe_filename("%s (%d)" % (title, year))
    dest = os.path.join(config.path("movies"), folder, folder + ext.lower())
    return _move(video, dest, "Added %s to Movies" % folder)


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


def _move(src, dest, message):
    if os.path.exists(dest):
        if os.path.getsize(dest) == os.path.getsize(src):
            return _to_review(src, "Already in the library: %s" % os.path.relpath(dest, os.path.dirname(config.path("shows"))),
                              sub="Duplicates")
        return _to_review(src, "A different file already has this name: %s" % os.path.basename(dest))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    stem_src = os.path.splitext(src)[0]
    stem_dest = os.path.splitext(dest)[0]
    shutil.move(src, dest)
    for f in os.listdir(os.path.dirname(src)):     # subtitles and thumbnails that share the name
        p = os.path.join(os.path.dirname(src), f)
        base, ext = os.path.splitext(p)
        if base == stem_src or base.startswith(stem_src + "."):
            if ext.lower() in naming.SUB_EXT or ext.lower() in (".jpg", ".png"):
                suffix = base[len(stem_src):]
                target = stem_dest + suffix + ext.lower()
                if ext.lower() in (".jpg", ".png"):
                    target = os.path.join(os.path.dirname(dest), "metadata", os.path.basename(stem_dest) + ext.lower())
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                if not os.path.exists(target):
                    shutil.move(p, target)
    store.log("inbox", message, {"from": os.path.basename(src), "to": dest})
    return True


def _to_review(path, why, sub="From Inbox"):
    dest_dir = os.path.join(config.path("review"), sub)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(path))
    n = 2
    while os.path.exists(dest):
        base, ext = os.path.splitext(os.path.basename(path))
        dest = os.path.join(dest_dir, "%s (%d)%s" % (base, n, ext))
        n += 1
    shutil.move(path, dest)
    store.log("review", why, {"file": os.path.basename(path), "now_in": dest})
    return False


def _sweep_leftovers(entry):
    """Once the videos are out, move whatever remains of a dropped folder to Needs Review."""
    if not os.path.exists(entry):
        return
    if os.path.isdir(entry):
        remaining = [f for _d, _dirs, files in os.walk(entry) for f in files if f != ".DS_Store"]
        if not remaining:
            shutil.rmtree(entry, ignore_errors=True)   # only empty folders and Finder litter
            return
    dest = os.path.join(config.path("review"), "Inbox leftovers", os.path.basename(entry))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest):
        shutil.move(entry, dest)
        store.log("review", "Moved leftover files from \"%s\" to Needs Review" % os.path.basename(entry), {"now_in": dest})
