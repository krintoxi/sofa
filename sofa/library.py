"""The library index: what's in Shows/, Movies/ and Adult/, with artwork and descriptions.

Layout Sofa expects (the Inbox organizer produces it):

    Shows/<Show>/Season 1/<Show> S01E01 <Title>.mkv      episodes
    Shows/<Show>/Specials/...                            season 0
    Shows/<Show>/Extras/<anything>.mp4                   extras
    Shows/<Show>/folder.jpg  backdrop.jpg  logo.png      artwork (downloaded if missing)
    Movies/<Title (Year)>/<Title (Year)>.mp4             movies
    Movies/<Collection>/<Title (Year)>/...               collections
    Adult/Movies/<Title>/...  Adult/Shows/<Show>/...     the adult section (same shapes)

It also copes with what people actually have: show folders named like
"The.Sopranos.1999.S01-S06.1080p", episodes named "101 Pilot", and a
collection folder holding several loose movies.

Item IDs come from what an item is (show, season, episode), not its file name,
so renaming or converting a file keeps its watch progress.
"""
import hashlib
import json
import os
import threading
import time

from . import config, media, metadata, music, naming, sidecars, store

ART = {"poster": ("folder.jpg", "poster.jpg", "folder.png", "poster.png", "cover.jpg"),
       "backdrop": ("backdrop.jpg", "fanart.jpg", "backdrop.png", "background.jpg"),
       "logo": ("logo.png", "clearlogo.png")}
ART_DOWNLOADS_PER_SCAN = 250       # per scan; the watcher scans again until everything has its artwork
EPISODE_STILLS_PER_SCAN = 120      # episode pictures taken from the video: slower, so a separate allowance
STILLS = os.path.join(config.DATA_DIR, "cache", "stills.json")   # adult pictures already taken from the middle
EXTRAS_DIRS = ("extras", "featurettes", "behind the scenes", "trailers", "bonus", "deleted scenes")
SERIES_DIRS = ("shows", "series", "tv", "tv shows", "tv series")
NOT_CATEGORIES = ("metadata", "performers")
PRIVATE = ("path", "thumb_path", "subs")


def private_key(text):
    """An ID part for the Adult section that doesn't spell out the title (URLs, logs, browser history)."""
    return "h" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def _jpeg_size(path):
    """(width, height) of a JPEG file, read from its header; None for anything else."""
    try:
        with open(path, "rb") as f:
            data = f.read(131072)
    except OSError:
        return None
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF or marker == 0x01 or 0xD0 <= marker <= 0xD8:
            i += 1 if marker == 0xFF else 2
            continue
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def _tidy_title(title):
    """'pilot' -> 'Pilot' for titles that came from an all-lowercase file name."""
    if not title:
        return None
    return title[:1].upper() + title[1:] if title.islower() else title


class Library:
    def __init__(self):
        self.lock = threading.Lock()
        self.shows, self.movies, self.items = [], [], {}
        self.adult = {"shows": [], "movies": []}
        self.dirs = {}          # show/movie id -> its folder (for fixing artwork); never sent to browsers
        self.known_performers = set()
        self.art_pending = False
        self._art_failed = set()           # addresses and files that didn't work this session: don't retry every scan
        self.music = {"tracks": [], "albums": [], "artists": [], "videos": []}
        self.generated = 0      # 0 until the first read after starting has finished
        self.signature = None
        self.scanning = False
        self.quick = False
        self.last_scan_seconds = 0
        self._scan_lock = threading.Lock()
        self._problems = []
        self._stills = {}

    # ------------------------------------------------------------ public views

    def public(self, adult=False):
        with self.lock:
            out = {"generated": self.generated, "shows": self.shows, "movies": self.movies}
            if adult:
                out["adult"] = self.adult
            return out

    def music_public(self):
        with self.lock:
            return dict(self.music, generated=self.generated)

    def item(self, item_id):
        with self.lock:
            return self.items.get(item_id)

    def find(self, entry_id):
        """A show or movie entry (as listed in public()) by id, from any section."""
        with self.lock:
            for group in (self.shows, self.movies, self.adult["shows"], self.adult["movies"]):
                for x in group:
                    if x["id"] == entry_id:
                        return x
        return None

    def counts(self):
        with self.lock:
            return {"shows": len(self.shows), "movies": len(self.movies),
                    "episodes": sum(1 for i in self.items.values() if i["kind"] == "episode" and not i.get("adult")),
                    "extras": sum(1 for i in self.items.values() if i["kind"] == "extra"),
                    "adult": len(self.adult["shows"]) + len(self.adult["movies"]),
                    "tracks": len(self.music["tracks"]), "albums": len(self.music["albums"]),
                    "music_videos": len(self.music["videos"]),
                    "files": len(self.items)}

    def missing_details(self):
        """Shows and movies Sofa found nothing about (for the Server page's "Fix details" list)."""
        with self.lock:
            out = [{"id": s["id"], "kind": "show", "title": s["name"], "adult": s.get("adult", False)}
                   for s in self.shows + self.adult["shows"] if not s.get("source")]
            out += [{"id": m["id"], "kind": "movie", "title": m["title"], "year": m.get("year"), "adult": m.get("adult", False)}
                    for m in self.movies + self.adult["movies"] if not m.get("source")]
        return out

    # ------------------------------------------------------------ change detection

    @staticmethod
    def roots():
        return {k: config.path(k) for k in ("shows", "movies", "music", "musicvideos", "adult")}

    def current_signature(self):
        h = hashlib.sha1()
        for key, root in sorted(self.roots().items()):
            for d, dirs, _files in os.walk(root):
                dirs[:] = sorted(x for x in dirs if not x.startswith("."))
                try:
                    h.update(("%s|%d\n" % (d, os.stat(d).st_mtime_ns)).encode())
                except OSError:
                    pass
        try:
            h.update(str(os.stat(metadata.OVERRIDES).st_mtime_ns).encode())
        except OSError:
            pass
        return h.hexdigest()

    def changed(self):
        return self.current_signature() != self.signature

    # ------------------------------------------------------------ scanning

    def scan(self, reason="manual", quick=False):
        """Read the folders again. `quick`: only from details and pictures already saved (no internet,
        no new pictures), which takes seconds; right after starting, Sofa does that, then a full scan."""
        if not self._scan_lock.acquire(blocking=False):
            return False
        self.scanning, self.quick = True, quick
        metadata.saved_only(quick)
        started = time.time()
        try:
            signature = self.current_signature()
            self._downloads = self._stills_made = 0
            self._problems = []
            self._stills = self._load_stills()
            self._dirs = {}
            self._renames = {}
            self._known = set(self.known_performers)
            people = os.path.join(config.path("adult"), "Performers")
            try:
                self._known.update(n for n in os.listdir(people) if not n.startswith("."))
            except OSError:
                pass
            items = {}
            shows = self._scan_shows(config.path("shows"), items, "shows")
            movies = self._scan_movies(config.path("movies"), items, "movies")
            a_shows, a_movies = self._scan_adult(config.path("adult"), items)
            adult = {"shows": a_shows, "movies": a_movies,
                     "categories": sorted({x["category"] for x in a_shows + a_movies},
                                          key=lambda c: (c != "Movies", c != "Series", c.lower()))}
            try:
                tunes = music.scan(self.art_url, items, quick=quick)
            except Exception as exc:
                self._problem(config.path("music"), exc)
                tunes = self.music
            with self.lock:
                self.shows, self.movies, self.items, self.music, self.adult = shows, movies, items, tunes, adult
                self.dirs = self._dirs
                self.known_performers = self._known
                self.generated = int(time.time())
                self.signature = signature
            self.art_pending = not quick and (self._downloads > ART_DOWNLOADS_PER_SCAN
                                              or self._stills_made > EPISODE_STILLS_PER_SCAN)
            self._save_stills()
            self._migrate_ids()
            self.last_scan_seconds = round(time.time() - started, 1)
            if self._problems:
                where, err = self._problems[0]
                store.log("error", "Couldn't read %d file(s) or folder(s) in the library, for example %s (%s)."
                          % (len(self._problems), where, err))
            if not quick:
                n_eps = sum(1 for i in items.values() if i["kind"] == "episode" and not i.get("adult"))
                store.log("scan", "Library updated: %d shows, %d episodes, %d movies, %d songs, %d music videos"
                          % (len(shows), n_eps, len(movies), len(tunes["tracks"]), len(tunes["videos"])),
                          {"reason": reason, "seconds": self.last_scan_seconds})
            return True
        finally:
            metadata.saved_only(False)
            self.scanning = self.quick = False
            self._scan_lock.release()

    def _problem(self, path, exc, adult=False):
        """Something in the library that couldn't be read (a broken link, a folder Sofa may not open):
        skip it, carry on, and say so once at the end of the scan."""
        if self.quick:
            return                  # the full scan right after says it
        where = "a file in the Adult section" if adult else path
        why = (getattr(exc, "strerror", None) or str(exc))[:200]
        self._problems.append((where, why))
        print("Library: couldn't read %s (%s)" % (where, why), flush=True)

    def _load_stills(self):
        try:
            with open(STILLS, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_stills(self):
        try:
            os.makedirs(os.path.dirname(STILLS), exist_ok=True)
            with open(STILLS + ".part", "w", encoding="utf-8") as f:
                json.dump(self._stills, f)
            os.replace(STILLS + ".part", STILLS)
        except OSError:
            pass

    @staticmethod
    def art_url(key, path):
        if not path:
            return None
        return "/art/%s/%s" % (key, os.path.relpath(path, config.path(key)).replace(os.sep, "/"))

    @staticmethod
    def find_art(directory, kind):
        for name in ART[kind]:
            p = os.path.join(directory, name)
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def sidecars(directory, stem):
        thumb, subs = None, []
        for cand in (os.path.join(directory, "metadata", stem + ".jpg"), os.path.join(directory, stem + ".jpg"),
                     os.path.join(directory, stem + "-thumb.jpg")):
            if os.path.isfile(cand):
                thumb = cand
                break
        try:
            names = os.listdir(directory)
        except OSError:
            names = []
        for n in sorted(names):
            base, ext = os.path.splitext(n)
            if ext.lower() in naming.SUB_EXT and (base == stem or base.startswith(stem + ".")):
                lang = base[len(stem) + 1:] or "und"
                subs.append({"lang": lang, "path": os.path.join(directory, n)})
        return thumb, subs

    def _media(self, path, kind, item_id):
        st = os.stat(path)
        directory, name = os.path.split(path)
        stem, ext = os.path.splitext(name)
        thumb, subs = self.sidecars(directory, stem)
        info = media.probe(path, cached_only=True) or {}
        return {"id": item_id, "kind": kind, "ext": ext.lower()[1:], "size": st.st_size,
                "added": int(st.st_mtime), "thumb_path": thumb, "subs": subs, "path": path,
                "duration": round(info["duration"]) if info.get("duration") else None,
                "height": (info.get("video") or {}).get("height")}

    def _migrate_ids(self):
        """Adult IDs used to contain the title; move everyone's progress (and the rest) to the new ones, once."""
        if not self._renames or store.migrated("adult-private-ids"):
            return
        for old, new in self._renames.items():
            for table in ("progress", "likes", "markers", "conversions"):
                try:
                    store.ex("UPDATE OR IGNORE %s SET item = ? WHERE item = ?" % table, new, old)
                except Exception:
                    pass        # a table that doesn't exist yet
            fix = metadata.override(old)
            if fix:
                metadata.set_override(new, fix)
                metadata.set_override(old, None)

    def _budget(self, episode=False):
        if self.quick:
            return False
        if episode:
            self._stills_made += 1
            return self._stills_made <= EPISODE_STILLS_PER_SCAN
        self._downloads += 1
        return self._downloads <= ART_DOWNLOADS_PER_SCAN

    def _ready(self, dest):
        """Can artwork be saved at `dest`? (Not on a read-only drive, or in a folder Sofa may not write to.)"""
        folder = os.path.dirname(dest)
        if folder in self._art_failed:
            return False
        try:
            os.makedirs(folder, exist_ok=True)
            if os.access(folder, os.W_OK):
                return True
        except OSError:
            pass
        self._art_failed.add(folder)
        return False

    def _fetch_art(self, url, dest, episode=False):
        if self.quick or not url or url in self._art_failed or not self._ready(dest) or not self._budget(episode):
            return False
        if metadata.download(url, dest):
            return True
        self._art_failed.add(url)
        return False

    def _grab_still(self, video, dest, where=0.15, episode=False, replace=False):
        """A frame from the video as artwork, for things no service knows (home videos, adult videos,
        episodes without a picture). `where`: how far in (episodes: past the intro; adult: the middle)."""
        if os.path.exists(dest) and not replace:
            return True
        if self.quick or video in self._art_failed or not media.tool("ffmpeg") or not self._ready(dest) \
                or not self._budget(episode):
            return False
        info = media.probe(video, cached_only=True) or media.probe(video) or {}
        at = max(12.0, (info.get("duration") or 0) * where)
        if media.extract_frame(video, dest, at):
            return True
        self._art_failed.add(video)
        return False

    def _adult_still(self, video, art, dest):
        """Adult videos get a picture from the middle. Pictures an older Sofa took near the start
        are replaced once; covers from ThePornDB, a saved link or you are left alone."""
        if art and not self._old_grab(art, video):
            return art
        target = art or dest
        if self._grab_still(video, target, 0.5, replace=bool(art)):
            self._stills[target] = "middle"
            return target
        return art

    def _old_grab(self, art, video):
        if self.quick or art in self._stills:
            return False
        info = media.probe(video, cached_only=True) or media.probe(video) or {}
        v = info.get("video") or {}
        if not (v.get("width") and v.get("height")):
            return False                       # can't tell yet (ffprobe missing, or unreadable)
        size, w = _jpeg_size(art), min(1280, v["width"])
        if size and size[0] == w and abs(size[1] - v["height"] * w / v["width"]) <= 2:
            return True                        # exactly the video's frame size: a frame Sofa grabbed
        self._stills[art] = "keep"
        return False

    @staticmethod
    def _videos(directory):
        try:
            return sorted(os.path.join(directory, f) for f in os.listdir(directory)
                          if os.path.splitext(f)[1].lower() in naming.VIDEO_EXT and not f.startswith("."))
        except OSError:
            return []

    # ------------------------------------------------------------ the Adult section

    @staticmethod
    def looks_like_show(d):
        """A folder of episodes: it has Season folders, or several videos named like episodes."""
        try:
            names = os.listdir(d)
        except OSError:
            return False
        if any(naming.season_of_dir(n) is not None and os.path.isdir(os.path.join(d, n)) for n in names):
            return True
        stems = [os.path.splitext(n)[0] for n in names if os.path.splitext(n)[1].lower() in naming.VIDEO_EXT]
        eps = [s for s in stems if naming.parse_episode(s) or naming.EPISODE_ONLY.search(s)]
        return len(eps) >= 2 and len(eps) >= len(stems) * 0.6

    def _scan_adult(self, root, items):
        """Every folder at the top of Adult/ is a category ("Movies", "Hentai", "Series", "Collections", ...).
        Inside one: movie folders, loose videos, collections (a folder of movie folders) and series
        (folders of episodes) are all recognised. Loose videos right in Adult/ go under "Movies"."""
        shows, movies = [], []
        if not os.path.isdir(root):
            return shows, movies

        def tag(entries, category):
            for e in entries:
                e["category"] = category
                for s in e.get("seasons", []):
                    for ep in s["episodes"]:
                        items[ep["id"]]["category"] = category
                if e["id"] in items:
                    items[e["id"]]["category"] = category
            return entries

        def show(d, folder, category):
            found = self._scan_show_safely(d, folder, items, "adult", prefix="a", adult=True)
            if found:
                shows.extend(tag([found], category))

        def category(name, p):
            subdirs = [s for s in os.listdir(p) if os.path.isdir(os.path.join(p, s)) and not s.startswith(".")]
            vids = self._videos(p)
            if name.lower() in SERIES_DIRS:
                for s in sorted(subdirs, key=str.lower):
                    show(os.path.join(p, s), s, "Series")
                return
            if vids and len(self.movie_groups(vids)) == 1 and not any(self._videos(os.path.join(p, s)) for s in subdirs) \
                    and not self.looks_like_show(p):
                singles.append(name)                      # a single movie folder sitting at the top
                return
            if self.looks_like_show(p):                   # a series sitting at the top
                show(p, name, "Series")
                return
            series = [s for s in subdirs if self.looks_like_show(os.path.join(p, s))]
            for s in sorted(series, key=str.lower):
                show(os.path.join(p, s), s, name)
            movies.extend(tag(self._scan_movies(p, items, "adult", prefix="a", adult=True,
                                                skip=tuple(s.lower() for s in series)), name))

        top_files, singles = [], []
        try:
            names = sorted(os.listdir(root), key=str.lower)
        except OSError as exc:
            self._problem(root, exc)
            names = []
        for name in names:
            p = os.path.join(root, name)
            if name.startswith(".") or name.lower() in NOT_CATEGORIES:
                continue
            if os.path.isfile(p):
                if os.path.splitext(name)[1].lower() in naming.VIDEO_EXT:
                    top_files.append(p)
                continue
            if os.path.isdir(p):
                try:
                    category(name, p)
                except Exception as exc:
                    self._problem(p, exc, adult=True)
        if top_files or singles:
            movies += tag(self._scan_movies(root, items, "adult", prefix="a", adult=True, only=set(singles),
                                            files=top_files), "Movies")
        return shows, movies

    # ------------------------------------------------------------ shows

    def _scan_shows(self, root, items, art_key, prefix="", adult=False):
        shows = []
        if not os.path.isdir(root):
            return shows
        try:
            names = sorted(os.listdir(root), key=str.lower)
        except OSError as exc:
            self._problem(root, exc, adult)
            return shows
        for name in names:
            d = os.path.join(root, name)
            if os.path.isdir(d) and not name.startswith("."):
                show = self._scan_show_safely(d, name, items, art_key, prefix, adult)
                if show:
                    shows.append(show)
        return shows

    def _scan_show_safely(self, show_dir, folder, items, art_key="shows", prefix="", adult=False):
        """One show that can't be read doesn't stop the rest of the library."""
        try:
            return self._scan_show(show_dir, folder, items, art_key, prefix, adult)
        except Exception as exc:
            self._problem(show_dir, exc, adult)
            return None

    def _scan_show(self, show_dir, folder, items, art_key="shows", prefix="", adult=False):
        name, year = naming.show_name(folder)
        slug = naming.slug(name)
        if adult:
            old_slug, slug = slug, private_key(slug)
            self._renames[prefix + "s:" + old_slug] = prefix + "s:" + slug
        show_id = prefix + "s:" + slug
        episodes, extras, season_art = [], [], {}
        try:
            flat = not any(naming.season_of_dir(n) is not None for n in os.listdir(show_dir)
                           if os.path.isdir(os.path.join(show_dir, n)))
        except OSError:
            flat = False
        for d, dirs, files in os.walk(show_dir):
            dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x != "metadata")
            rel_parts = [p for p in os.path.relpath(d, show_dir).split(os.sep) if p != "."]
            seasons_seen = [naming.season_of_dir(p) for p in rel_parts]
            dir_season = next((s for s in reversed(seasons_seen) if s is not None), None)
            if dir_season is None and flat and not rel_parts:
                dir_season = 1                            # "Show/Episode 01.mkv" with no Season folders
            in_extras = any(p.lower() in EXTRAS_DIRS for p in rel_parts)
            if rel_parts and seasons_seen[0] is not None and len(rel_parts) == 1:
                season_art.setdefault(seasons_seen[0], self.find_art(d, "poster"))
            for f in sorted(files):
                stem, ext = os.path.splitext(f)
                if ext.lower() not in naming.VIDEO_EXT or f.startswith("."):
                    continue
                path = os.path.join(d, f)
                ep = None if in_extras else naming.parse_episode(stem, dir_season, in_show=True)
                if ep:
                    episodes.append((ep, path))
                else:
                    extras.append(path)
        if not episodes and not extras:
            return None

        fix = metadata.override(show_id)
        info, eps_meta = {}, {}
        show_meta = metadata.tv_show(name, year, fix) if episodes and not adult else None
        if show_meta:
            info = metadata.show_info(show_meta)
            eps_meta = metadata.episodes(show_meta)
            if info.get("canonical") and (fix or naming.norm(info["canonical"]) == naming.norm(name)):
                name = info["canonical"]
        poster = self.find_art(show_dir, "poster")
        backdrop = self.find_art(show_dir, "backdrop")
        if not poster and self._fetch_art(info.get("poster_url"), os.path.join(show_dir, "folder.jpg")):
            poster = os.path.join(show_dir, "folder.jpg")
        if not backdrop and self._fetch_art(info.get("backdrop_url"), os.path.join(show_dir, "backdrop.jpg")):
            backdrop = os.path.join(show_dir, "backdrop.jpg")
        if adult and episodes:
            poster = self._adult_still(episodes[0][1], poster, os.path.join(show_dir, "folder.jpg"))
        elif not poster and episodes and not show_meta and self._grab_still(episodes[0][1], os.path.join(show_dir, "folder.jpg")):
            poster = os.path.join(show_dir, "folder.jpg")

        seasons = {}
        seen = set()
        for ep, path in sorted(episodes, key=lambda x: (x[0]["s"], x[0]["e"], x[1])):
            item_id = "%se:%s:%d:%d" % (prefix, slug, ep["s"], ep["e"])
            n = 2
            while item_id in seen:
                item_id = "%se:%s:%d:%d:%d" % (prefix, slug, ep["s"], ep["e"], n)
                n += 1
            seen.add(item_id)
            if adult:
                self._renames["%se:%s:%d:%d" % (prefix, old_slug, ep["s"], ep["e"])] = item_id
            try:
                item = self._media(path, "episode", item_id)
            except OSError as exc:
                self._problem(path, exc, adult)
                continue
            meta = eps_meta.get((ep["s"], ep["e"]), {})
            dest = os.path.join(os.path.dirname(path), "metadata", os.path.splitext(os.path.basename(path))[0] + ".jpg")
            if adult:
                item["thumb_path"] = self._adult_still(path, item["thumb_path"], dest)
            elif not item["thumb_path"] and (self._fetch_art(meta.get("thumb_url"), dest, episode=True)
                                             or self._grab_still(path, dest, 0.3, episode=True)):
                item["thumb_path"] = dest
            item.update(show_id=show_id, show_name=name, s=ep["s"], e=ep["e"], e2=ep.get("e2"), adult=adult,
                        title=meta.get("title") or _tidy_title(ep.get("title")), summary=meta.get("summary"),
                        aired=meta.get("aired"), runtime=meta.get("runtime"))
            items[item_id] = item
            seasons.setdefault(ep["s"], []).append(item)
        extra_items = []
        for path in extras:
            title = naming.clean(os.path.splitext(os.path.basename(path))[0]) or "Extra"
            item_id = "%sx:%s:%s" % (prefix, slug, private_key(title) if adult else naming.slug(title))
            try:
                item = self._media(path, "extra", item_id)
            except OSError as exc:
                self._problem(path, exc, adult)
                continue
            item.update(show_id=show_id, show_name=name, title=title, adult=adult)
            items[item_id] = item
            extra_items.append(item)

        def pub(i):
            out = {k: v for k, v in i.items() if k not in PRIVATE}
            out["thumb"] = self.art_url(art_key, i["thumb_path"])
            out["file"] = os.path.basename(i["path"])
            out["subs"] = len(i["subs"])
            return out

        self._dirs[show_id] = show_dir
        added = max([i["added"] for i in items.values() if i.get("show_id") == show_id] or [0])
        show = {"id": show_id, "name": name, "added": added, "adult": adult, "folder": folder,
                "poster": self.art_url(art_key, poster), "backdrop": self.art_url(art_key, backdrop),
                "logo": self.art_url(art_key, self.find_art(show_dir, "logo")),
                "seasons": [{"n": n, "poster": self.art_url(art_key, season_art.get(n)),
                             "episodes": [pub(i) for i in eps]} for n, eps in sorted(seasons.items())],
                "extras": [pub(i) for i in sorted(extra_items, key=lambda i: i["title"].lower())]}
        show.update({k: info.get(k) for k in ("summary", "genres", "premiered", "ended", "network", "rating", "runtime",
                                               "source")})
        if year and not show.get("premiered"):
            show["premiered"] = "%d-01-01" % year
        return show

    # ------------------------------------------------------------ movies

    @staticmethod
    def movie_groups(videos):
        """Split a folder's videos into movies: {key: [paths]}. Two parts of one movie (CD1/CD2) stay together;
        small files next to a big one (samples, featurettes) don't count as movies of their own."""
        if not videos:
            return {}
        sizes = {v: _size(v) for v in videos}
        sizes = {v: n for v, n in sizes.items() if n >= 0}       # a broken link or a file that just went away
        if not sizes:
            return {}
        biggest = max(sizes.values())
        groups = {}
        for v in sizes:
            stem = os.path.splitext(os.path.basename(v))[0]
            if sizes[v] < biggest * 0.2 or "sample" in stem.lower().split():
                continue
            title, year = naming.parse_movie(stem)
            groups.setdefault((naming.norm(naming.strip_part(title)), year), []).append(v)
        return groups

    def _scan_movies(self, root, items, art_key, prefix="", adult=False, skip=(), only=None, files=None):
        """`only`/`files`: look at just these top-level folders and these loose files (the Adult root)."""
        movies = []
        if not os.path.isdir(root):
            return movies

        def add(path, title, year, directory, collection):
            try:
                add_one(path, title, year, directory, collection)
            except Exception as exc:     # one unreadable file doesn't stop the rest
                self._problem(path, exc, adult)

        def add_one(path, title, year, directory, collection):
            item_id = "%sm:%s:%s" % (prefix, naming.slug(title), year or "")
            if item_id in items:
                item_id += ":" + naming.slug(os.path.basename(path))
            stem = os.path.splitext(os.path.basename(path))[0]
            side, scene = {}, {}
            if adult:
                old_id = item_id
                basis = os.path.basename(directory) if directory else stem
                item_id = "%sm:%s" % (prefix, private_key(basis))
                n = 2
                while item_id in items:
                    item_id = "%sm:%s" % (prefix, private_key("%s|%d" % (basis, n)))
                    n += 1
                self._renames[old_id] = item_id
                side = sidecars.read(path)
                scene = naming.parse_scene(stem, self._known)
                if not (scene.get("studio") or scene.get("date")) and directory:
                    scene = naming.parse_scene(os.path.basename(directory), self._known)
                title = side.get("title") or scene.get("title") or title
                year = year if year and not scene.get("date") else (side.get("year") or scene.get("year") or year)
            item = self._media(path, "movie", item_id)
            fix = metadata.override(item_id)
            meta = metadata.movie(title, year, fix, adult=adult) or {}
            if not adult:  # an .nfo next to a movie fills in what the lookups didn't find
                side = sidecars.read(path)
                for k, v in (("summary", side.get("summary")), ("genres", side.get("tags")), ("studio", side.get("studio"))):
                    if v and not meta.get(k):
                        meta[k] = v
                if side and not meta.get("source"):
                    meta["source"] = "Saved with the file"
            if adult:      # details: a fix or ThePornDB first, then the files next to it, then the name
                for k in ("summary", "studio", "date", "performers", "poster_url"):
                    if not meta.get(k) and side.get(k):
                        meta[k] = side[k]
                meta.setdefault("genres", side.get("tags") or [])
                meta["studio"] = meta.get("studio") or scene.get("studio")
                meta["date"] = meta.get("date") or scene.get("date")
                meta["performers"] = meta.get("performers") or scene.get("performers") or []
                self._known.update(meta["performers"])
                if not meta.get("source") and side:
                    meta["source"] = "Saved with the file" if side.get("source") == "nfo" else "Saved from a link"
            poster = self.find_art(directory, "poster") if directory else None
            backdrop = self.find_art(directory, "backdrop") if directory else None
            if directory and not poster and self._fetch_art(meta.get("poster_url"), os.path.join(directory, "folder.jpg")):
                poster = os.path.join(directory, "folder.jpg")
            if directory and not backdrop and self._fetch_art(meta.get("backdrop_url"), os.path.join(directory, "backdrop.jpg")):
                backdrop = os.path.join(directory, "backdrop.jpg")
            dest = (os.path.join(directory, "folder.jpg") if directory else
                    os.path.join(os.path.dirname(path), "metadata", os.path.splitext(os.path.basename(path))[0] + ".jpg"))
            if not poster and not item["thumb_path"] and meta.get("poster_url") and self._fetch_art(meta["poster_url"], dest):
                art = dest
            elif adult and not side and not meta.get("poster_url"):
                art = self._adult_still(path, poster or item["thumb_path"], dest)
            elif not poster and not item["thumb_path"] and self._grab_still(path, dest, 0.5 if adult else 0.15):
                art = dest
            else:
                art = None
            if art and directory:
                poster = art
            elif art:
                item["thumb_path"] = art
            shown = meta.get("canonical") or title
            item.update(title=shown, year=year or meta.get("year") or (int(meta["date"][:4]) if meta.get("date") else None),
                        collection=collection or meta.get("collection"),
                        summary=meta.get("summary"), rating=meta.get("rating"), adult=adult,
                        **{k: meta.get(k) for k in ("genres", "runtime", "tagline", "certificate", "studio",
                                                    "performers", "date", "source")})
            items[item_id] = item
            self._dirs[item_id] = directory
            out = {k: v for k, v in item.items() if k not in PRIVATE}
            out.update(poster=self.art_url(art_key, poster or item["thumb_path"]),
                       backdrop=self.art_url(art_key, backdrop),
                       logo=self.art_url(art_key, self.find_art(directory, "logo") if directory else None),
                       file=os.path.basename(path), subs=len(item["subs"]))
            movies.append(out)

        def loose(videos, collection):
            for key, files in self.movie_groups(videos).items():
                main = max(files, key=_size)
                title, year = naming.parse_movie(os.path.splitext(os.path.basename(main))[0])
                add(main, naming.strip_part(title), year, None, collection)

        def collection_label(name):
            return naming.collection_name(name) if naming.COLLECTION_WORDS.search(name) else naming.clean(name) or name

        def visit(d, collection, depth=0):
            try:
                names = sorted(os.listdir(d), key=str.lower)
            except OSError:
                return
            here = [os.path.join(d, n) for n in names if not n.startswith(".")
                    and os.path.splitext(n)[1].lower() in naming.VIDEO_EXT and os.path.isfile(os.path.join(d, n))]
            if depth == 0 and files is not None:
                here = files
            if here:
                loose(here, collection)
            for name in names:
                p = os.path.join(d, name)
                if name.startswith(".") or not os.path.isdir(p) or name == "metadata" or (depth == 0 and name.lower() in skip):
                    continue
                if depth == 0 and only is not None and name not in only:
                    continue
                vids = self._videos(p)
                groups = self.movie_groups(vids)
                if len(groups) >= 2:                       # a collection folder of loose movies
                    loose(vids, collection or collection_label(name))
                    visit_subdirs(p, collection or collection_label(name), depth + 1)
                elif vids:
                    title, year = naming.parse_movie(name)
                    main = max(vids, key=_size)
                    if not year:
                        t2, y2 = naming.parse_movie(os.path.splitext(os.path.basename(main))[0])
                        if y2:
                            title, year = t2, y2
                    add(main, naming.strip_part(title), year, p, collection)
                elif depth < 3:
                    visit(p, collection or collection_label(name), depth + 1)

        def visit_subdirs(d, collection, depth):
            try:
                names = sorted(os.listdir(d), key=str.lower)
            except OSError:
                return
            for name in names:
                p = os.path.join(d, name)
                if os.path.isdir(p) and not name.startswith(".") and name != "metadata":
                    vids = self._videos(p)
                    if vids:
                        title, year = naming.parse_movie(name)
                        add(max(vids, key=_size), naming.strip_part(title), year, p, collection)

        visit(root, None)
        movies.sort(key=lambda m: ((m.get("collection") or m["title"]).lower(), m.get("year") or 0))
        return movies


LIBRARY = Library()
