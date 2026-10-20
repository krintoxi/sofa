"""Music and music videos.

    Music/<Artist>/<Album>/<NN Title>.mp3        albums (folder.jpg / cover.jpg = album art)
    Music/<Artist>/<Title>.mp3                    singles
    Music/sofa-tags.json                          optional: {"Artist/Album/file.mp3": {"genre", "mood", ...}}
    Music Videos/<Artist>/<Title>.mp4             music videos

Titles, artists, albums and track numbers come from the files' own tags when they
have them, otherwise from the folder and file names. Embedded cover art is pulled
into Sofa's cache. Genre and mood power the stations.
"""
import hashlib
import json
import os
import re

from . import config, media, naming

AUDIO_EXT = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".oga", ".opus", ".wma", ".aif", ".aiff", ".alac"}
BROWSER_AUDIO = {"mp3", "m4a", "aac", "wav", "flac", "ogg", "oga", "opus"}
ALBUM_ART = ("folder.jpg", "cover.jpg", "front.jpg", "album.jpg", "folder.png", "cover.png")
TAGS_FILE = "sofa-tags.json"
ART_CACHE = os.path.join(config.DATA_DIR, "cache", "art")
EXTRACT_PER_SCAN = 400


def _num(value):
    m = re.match(r"\s*(\d+)", str(value or ""))
    return int(m.group(1)) if m else None


def _lead_num(filename):
    """Track number from "03 Title.mp3" / "03 - Title.mp3" when the file has no track tag."""
    m = re.match(r"^\s*(\d{1,3})(?:\s*[-._)]\s*|\s+)\S", filename)
    return int(m.group(1)) if m else None


def _clean_title(stem):
    stem = re.sub(r"^\s*\d{1,3}\s*[-._)]\s*", "", stem)          # "03 - Title", "03. Title"
    return naming.clean(stem) if "_" in stem or stem.count(".") > 1 else stem.strip()


def _art_cache(path, budget):
    """URL of the embedded cover of `path`, extracting it once into data/cache/art."""
    st = os.stat(path)
    key = hashlib.sha1(("%s|%d|%d" % (path, st.st_size, int(st.st_mtime))).encode()).hexdigest()[:20]
    dest = os.path.join(ART_CACHE, key + ".jpg")
    if os.path.exists(dest):
        return "/art/cache/%s.jpg" % key
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    os.makedirs(ART_CACHE, exist_ok=True)
    return "/art/cache/%s.jpg" % key if media.extract_art(path, dest) else None


def _frame_cache(path, budget):
    st = os.stat(path)
    key = hashlib.sha1(("frame|%s|%d|%d" % (path, st.st_size, int(st.st_mtime))).encode()).hexdigest()[:20]
    dest = os.path.join(ART_CACHE, key + ".jpg")
    if os.path.exists(dest):
        return "/art/cache/%s.jpg" % key
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    os.makedirs(ART_CACHE, exist_ok=True)
    return "/art/cache/%s.jpg" % key if media.extract_frame(path, dest) else None


def scan(art_url, items):
    """Read Music/ and Music Videos/. Adds playable entries to `items`; returns the public view."""
    root = config.path("music")
    budget = [EXTRACT_PER_SCAN]
    try:
        with open(os.path.join(root, TAGS_FILE), encoding="utf-8") as f:
            extra_tags = json.load(f)
    except (OSError, ValueError):
        extra_tags = {}

    tracks, albums, artists = [], {}, {}
    if os.path.isdir(root):
        for d, dirs, files in os.walk(root):
            dirs[:] = sorted(x for x in dirs if not x.startswith("."))
            stems = {naming.norm(os.path.splitext(x)[0]): x for x in files}
            for f in sorted(files):
                ext = os.path.splitext(f)[1].lower()
                if ext not in AUDIO_EXT or f.startswith("._"):
                    continue
                path = os.path.join(d, f)
                rel = os.path.relpath(path, root)
                parts = rel.split(os.sep)
                info = media.probe(path) or {}
                tags = info.get("tags") or {}
                # The folders are the truth (Music/<Artist>/<Album>/...); tags only fill in for loose files.
                artist = (parts[0] if len(parts) > 1 else
                          (tags.get("album_artist") or tags.get("artist") or "")).strip() or "Unknown artist"
                album = (parts[1] if len(parts) > 2 else ("" if len(parts) > 1 else tags.get("album") or "")).strip() \
                    or "Singles"
                title = (tags.get("title") or "").strip() or _clean_title(os.path.splitext(f)[0])
                # A copied tag can name a different song in the same folder; then the file name is right.
                twin = stems.get(naming.norm(title))
                if twin and twin != f and naming.norm(title) != naming.norm(os.path.splitext(f)[0]):
                    title = _clean_title(os.path.splitext(f)[0])
                extra = extra_tags.get(rel.replace(os.sep, "/"), {})
                artist_name = artist
                ar_id = "ar:" + naming.slug(artist_name)
                al_id = "al:%s:%s" % (naming.slug(artist_name), naming.slug(album))
                tid = "t:%s:%s:%s" % (naming.slug(artist_name), naming.slug(album), naming.slug(title))
                n = 2
                while tid in items:
                    tid = "t:%s:%s:%s:%d" % (naming.slug(artist_name), naming.slug(album), naming.slug(title), n)
                    n += 1
                st = os.stat(path)
                folder_art = next((os.path.join(d, a) for a in ALBUM_ART if os.path.isfile(os.path.join(d, a))), None)
                art = art_url("music", folder_art) if folder_art else (_art_cache(path, budget) if info.get("art") else None)
                item = {"id": tid, "kind": "track", "path": path, "ext": ext[1:], "size": st.st_size,
                        "added": int(st.st_mtime), "title": title, "artist": artist_name, "artist_id": ar_id,
                        "album": album, "album_id": al_id, "n": _num(tags.get("track")) or _lead_num(os.path.splitext(f)[0]), "disc": _num(tags.get("disc")),
                        "year": _num((tags.get("date") or "")[:4]), "duration": round(info.get("duration") or 0, 1),
                        "genre": extra.get("genre") or tags.get("genre"), "mood": extra.get("mood"),
                        "energy": extra.get("energy"), "tags": extra.get("tags") or [], "language": extra.get("language"),
                        "art": art, "subs": [], "thumb_path": None}
                items[tid] = item
                tracks.append(item)
                a = albums.setdefault(al_id, {"id": al_id, "title": album, "artist": artist_name, "artist_id": ar_id,
                                              "year": None, "art": None, "tracks": [], "added": 0})
                a["tracks"].append(item)
                a["added"] = max(a["added"], item["added"])
                a["year"] = a["year"] or item["year"]
                if folder_art and not a["art"]:
                    a["art"] = art
                artists.setdefault(ar_id, {"id": ar_id, "name": artist_name, "albums": set(), "tracks": 0, "art": None})
                artists[ar_id]["albums"].add(al_id)
                artists[ar_id]["tracks"] += 1

    for a in albums.values():
        a["tracks"].sort(key=lambda t: (t["disc"] or 1, t["n"] or 999, t["title"].lower()))
        a["art"] = a["art"] or next((t["art"] for t in a["tracks"] if t["art"]), None)
        for t in a["tracks"]:
            t["art"] = t["art"] or a["art"]
    for ar in artists.values():
        own = sorted((albums[x] for x in ar["albums"]), key=lambda a: (a["title"] == "Singles", -(a["year"] or 0)))
        ar["art"] = next((a["art"] for a in own if a["art"]), None)

    videos = []
    vroot = config.path("musicvideos")
    if os.path.isdir(vroot):
        for d, dirs, files in os.walk(vroot):
            dirs[:] = sorted(x for x in dirs if not x.startswith("."))
            for f in sorted(files):
                stem, ext = os.path.splitext(f)
                if ext.lower() not in naming.VIDEO_EXT or f.startswith("._"):
                    continue
                path = os.path.join(d, f)
                parts = os.path.relpath(path, vroot).split(os.sep)
                if len(parts) > 1:
                    artist, title = parts[0], _clean_title(stem)
                else:
                    artist, _, title = stem.partition(" - ")
                    artist, title = (artist.strip(), title.strip()) if title else ("Unknown artist", stem)
                vid = "v:%s:%s" % (naming.slug(artist), naming.slug(title))
                while vid in items:
                    vid += "-2"
                thumb_file = next((p for p in (os.path.join(d, stem + ".jpg"), os.path.join(d, "metadata", stem + ".jpg"))
                                   if os.path.isfile(p)), None)
                info = media.probe(path) or {}
                st = os.stat(path)
                item = {"id": vid, "kind": "musicvideo", "path": path, "ext": ext.lower()[1:], "size": st.st_size,
                        "added": int(st.st_mtime), "title": title, "artist": artist, "artist_id": "ar:" + naming.slug(artist),
                        "duration": round(info.get("duration") or 0, 1),
                        "thumb": art_url("musicvideos", thumb_file) if thumb_file else _frame_cache(path, budget),
                        "subs": [], "thumb_path": None}
                items[vid] = item
                videos.append(item)

    pub_track = lambda t: {k: t[k] for k in ("id", "title", "artist", "artist_id", "album", "album_id", "n", "year",
                                              "duration", "genre", "mood", "energy", "tags", "language", "art", "ext",
                                              "added")}
    return {
        "tracks": [pub_track(t) for t in sorted(tracks, key=lambda t: (t["artist"].lower(), t["album"].lower(), t["n"] or 999))],
        "albums": sorted(({k: (v if k != "tracks" else [t["id"] for t in v]) for k, v in a.items()} for a in albums.values()),
                         key=lambda a: (a["artist"].lower(), a["title"] == "Singles", a["title"].lower())),
        "artists": sorted(({**ar, "albums": len(ar["albums"])} for ar in artists.values()), key=lambda a: a["name"].lower()),
        "videos": [{k: v[k] for k in ("id", "title", "artist", "artist_id", "duration", "thumb", "added", "ext")}
                   for v in sorted(videos, key=lambda v: (v["artist"].lower(), v["title"].lower()))],
    }


def playable_directly(item):
    return item["ext"] in BROWSER_AUDIO
