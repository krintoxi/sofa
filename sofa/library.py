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
import os
import threading
import time

from . import config, media, metadata, music, naming, store

ART = {"poster": ("folder.jpg", "poster.jpg", "folder.png", "poster.png", "cover.jpg"),
       "backdrop": ("backdrop.jpg", "fanart.jpg", "backdrop.png", "background.jpg"),
       "logo": ("logo.png", "clearlogo.png")}
ART_DOWNLOADS_PER_SCAN = 120
EXTRAS_DIRS = ("extras", "featurettes", "behind the scenes", "trailers", "bonus", "deleted scenes")
PRIVATE = ("path", "thumb_path", "subs")


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
        self.music = {"tracks": [], "albums": [], "artists": [], "videos": []}
        self.generated = 0
        self.signature = None
        self.scanning = False
        self.last_scan_seconds = 0

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

    def scan(self, reason="manual"):
        if self.scanning:
            return False
        self.scanning = True
        started = time.time()
        try:
            signature = self.current_signature()
            self._downloads = 0
            self._dirs = {}
            items = {}
            shows = self._scan_shows(config.path("shows"), items, "shows")
            movies = self._scan_movies(config.path("movies"), items, "movies")
            adult_root = config.path("adult")
            adult = {"shows": self._scan_shows(os.path.join(adult_root, "Shows"), items, "adult", prefix="a", adult=True),
                     "movies": self._scan_movies(adult_root, items, "adult", prefix="a", adult=True, skip=("shows",))}
            tunes = music.scan(self.art_url, items)
            with self.lock:
                self.shows, self.movies, self.items, self.music, self.adult = shows, movies, items, tunes, adult
                self.dirs = self._dirs
                self.generated = int(time.time())
                self.signature = signature
            self.last_scan_seconds = round(time.time() - started, 1)
            n_eps = sum(1 for i in items.values() if i["kind"] == "episode" and not i.get("adult"))
            store.log("scan", "Library updated: %d shows, %d episodes, %d movies, %d songs, %d music videos"
                      % (len(shows), n_eps, len(movies), len(tunes["tracks"]), len(tunes["videos"])),
                      {"reason": reason, "seconds": self.last_scan_seconds})
            return True
        finally:
            self.scanning = False

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
        return {"id": item_id, "kind": kind, "ext": ext.lower()[1:], "size": st.st_size,
                "added": int(st.st_mtime), "thumb_path": thumb, "subs": subs, "path": path}

    def _budget(self):
        self._downloads += 1
        return self._downloads <= ART_DOWNLOADS_PER_SCAN

    def _fetch_art(self, url, dest):
        return bool(url) and self._budget() and metadata.download(url, dest)

    def _grab_still(self, video, dest):
        """A frame from the video as artwork, for things no service knows (home videos, adult scenes)."""
        if os.path.exists(dest) or not media.tool("ffmpeg") or not self._budget():
            return os.path.exists(dest)
        info = media.probe(video, cached_only=True) or {}
        at = max(12.0, (info.get("duration") or 0) * 0.15)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        return media.extract_frame(video, dest, at)

    @staticmethod
    def _videos(directory):
        try:
            return sorted(os.path.join(directory, f) for f in os.listdir(directory)
                          if os.path.splitext(f)[1].lower() in naming.VIDEO_EXT and not f.startswith("."))
        except OSError:
            return []

    # ------------------------------------------------------------ shows

    def _scan_shows(self, root, items, art_key, prefix="", adult=False):
        shows = []
        if not os.path.isdir(root):
            return shows
        for name in sorted(os.listdir(root), key=str.lower):
            d = os.path.join(root, name)
            if os.path.isdir(d) and not name.startswith("."):
                show = self._scan_show(d, name, items, art_key, prefix, adult)
                if show:
                    shows.append(show)
        return shows

    def _scan_show(self, show_dir, folder, items, art_key="shows", prefix="", adult=False):
        name, year = naming.show_name(folder)
        slug = naming.slug(name)
        show_id = prefix + "s:" + slug
        episodes, extras, season_art = [], [], {}
        for d, dirs, files in os.walk(show_dir):
            dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x != "metadata")
            rel_parts = [p for p in os.path.relpath(d, show_dir).split(os.sep) if p != "."]
            seasons_seen = [naming.season_of_dir(p) for p in rel_parts]
            dir_season = next((s for s in reversed(seasons_seen) if s is not None), None)
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
        if not poster and adult and episodes and self._grab_still(episodes[0][1], os.path.join(show_dir, "folder.jpg")):
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
            item = self._media(path, "episode", item_id)
            meta = eps_meta.get((ep["s"], ep["e"]), {})
            if not item["thumb_path"] and meta.get("thumb_url"):
                dest = os.path.join(os.path.dirname(path), "metadata", os.path.splitext(os.path.basename(path))[0] + ".jpg")
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if self._fetch_art(meta["thumb_url"], dest):
                    item["thumb_path"] = dest
            item.update(show_id=show_id, show_name=name, s=ep["s"], e=ep["e"], e2=ep.get("e2"), adult=adult,
                        title=meta.get("title") or _tidy_title(ep.get("title")), summary=meta.get("summary"),
                        aired=meta.get("aired"), runtime=meta.get("runtime"))
            items[item_id] = item
            seasons.setdefault(ep["s"], []).append(item)
        extra_items = []
        for path in extras:
            title = naming.clean(os.path.splitext(os.path.basename(path))[0]) or "Extra"
            item_id = "%sx:%s:%s" % (prefix, slug, naming.slug(title))
            item = self._media(path, "extra", item_id)
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
        sizes = {v: os.path.getsize(v) for v in videos}
        biggest = max(sizes.values())
        groups = {}
        for v in videos:
            stem = os.path.splitext(os.path.basename(v))[0]
            if sizes[v] < biggest * 0.2 or "sample" in stem.lower().split():
                continue
            title, year = naming.parse_movie(stem)
            groups.setdefault((naming.norm(naming.strip_part(title)), year), []).append(v)
        return groups

    def _scan_movies(self, root, items, art_key, prefix="", adult=False, skip=()):
        movies = []
        if not os.path.isdir(root):
            return movies

        def add(path, title, year, directory, collection):
            item_id = "%sm:%s:%s" % (prefix, naming.slug(title), year or "")
            if item_id in items:
                item_id += ":" + naming.slug(os.path.basename(path))
            item = self._media(path, "movie", item_id)
            fix = metadata.override(item_id)
            meta = metadata.movie(title, year, fix, adult=adult) or {}
            poster = self.find_art(directory, "poster") if directory else None
            backdrop = self.find_art(directory, "backdrop") if directory else None
            if directory and not poster and self._fetch_art(meta.get("poster_url"), os.path.join(directory, "folder.jpg")):
                poster = os.path.join(directory, "folder.jpg")
            if directory and not backdrop and self._fetch_art(meta.get("backdrop_url"), os.path.join(directory, "backdrop.jpg")):
                backdrop = os.path.join(directory, "backdrop.jpg")
            if not poster and not item["thumb_path"]:
                dest = (os.path.join(directory, "folder.jpg") if directory else
                        os.path.join(os.path.dirname(path), "metadata", os.path.splitext(os.path.basename(path))[0] + ".jpg"))
                if (meta.get("poster_url") and self._fetch_art(meta["poster_url"], dest)) or self._grab_still(path, dest):
                    if directory:
                        poster = dest
                    else:
                        item["thumb_path"] = dest
            shown = meta.get("canonical") or title
            item.update(title=shown, year=year or meta.get("year"), collection=collection or meta.get("collection"),
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
                main = max(files, key=os.path.getsize)
                title, year = naming.parse_movie(os.path.splitext(os.path.basename(main))[0])
                add(main, naming.strip_part(title), year, None, collection)

        def collection_label(name):
            return naming.collection_name(name) if naming.COLLECTION_WORDS.search(name) else naming.clean(name) or name

        def visit(d, collection, depth=0):
            try:
                names = sorted(os.listdir(d), key=str.lower)
            except OSError:
                return
            files = [os.path.join(d, n) for n in names if not n.startswith(".")
                     and os.path.splitext(n)[1].lower() in naming.VIDEO_EXT and os.path.isfile(os.path.join(d, n))]
            if files:
                loose(files, collection)
            for name in names:
                p = os.path.join(d, name)
                if name.startswith(".") or not os.path.isdir(p) or name == "metadata" or (depth == 0 and name.lower() in skip):
                    continue
                if depth == 0 and adult and name.lower() == "movies":
                    visit(p, None, 0)
                    continue
                vids = self._videos(p)
                groups = self.movie_groups(vids)
                if len(groups) >= 2:                       # a collection folder of loose movies
                    loose(vids, collection or collection_label(name))
                    visit_subdirs(p, collection or collection_label(name), depth + 1)
                elif vids:
                    title, year = naming.parse_movie(name)
                    main = max(vids, key=os.path.getsize)
                    if not year:
                        t2, y2 = naming.parse_movie(os.path.splitext(os.path.basename(main))[0])
                        if y2:
                            title, year = t2, y2
                    add(main, naming.strip_part(title), year, p, collection)
                elif depth < 3:
                    visit(p, collection or collection_label(name), depth + 1)

        def visit_subdirs(d, collection, depth):
            for name in sorted(os.listdir(d), key=str.lower):
                p = os.path.join(d, name)
                if os.path.isdir(p) and not name.startswith(".") and name != "metadata":
                    vids = self._videos(p)
                    if vids:
                        title, year = naming.parse_movie(name)
                        add(max(vids, key=os.path.getsize), naming.strip_part(title), year, p, collection)

        visit(root, None)
        movies.sort(key=lambda m: ((m.get("collection") or m["title"]).lower(), m.get("year") or 0))
        return movies


LIBRARY = Library()
