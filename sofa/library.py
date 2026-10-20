"""The library index: what's in Shows/ and Movies/, with artwork and descriptions.

Layout Sofa expects (the Inbox organizer produces it):

    Shows/<Show>/Season 1/<Show> S01E01 <Title>.mkv      episodes
    Shows/<Show>/Specials/...                            season 0
    Shows/<Show>/Extras/<anything>.mp4                   extras
    Shows/<Show>/folder.jpg  backdrop.jpg  logo.png      artwork (downloaded if missing)
    Movies/<Title (Year)>/<Title (Year)>.mp4             movies
    Movies/<Collection>/<Title (Year)>/...               collections

Item IDs come from what an item is (show, season, episode), not its file name,
so renaming or converting a file keeps its watch progress.
"""
import hashlib
import os
import re
import threading
import time

from . import config, metadata, music, naming, store

ART = {"poster": ("folder.jpg", "poster.jpg", "folder.png", "poster.png", "cover.jpg"),
       "backdrop": ("backdrop.jpg", "fanart.jpg", "backdrop.png", "background.jpg"),
       "logo": ("logo.png", "clearlogo.png")}
ART_DOWNLOADS_PER_SCAN = 80


class Library:
    def __init__(self):
        self.lock = threading.Lock()
        self.shows, self.movies, self.items = [], [], {}
        self.music = {"tracks": [], "albums": [], "artists": [], "videos": []}
        self.generated = 0
        self.signature = None
        self.scanning = False
        self.last_scan_seconds = 0

    # ------------------------------------------------------------ public views

    def public(self):
        with self.lock:
            return {"generated": self.generated, "shows": self.shows, "movies": self.movies}

    def music_public(self):
        with self.lock:
            return dict(self.music, generated=self.generated)

    def item(self, item_id):
        with self.lock:
            return self.items.get(item_id)

    def counts(self):
        with self.lock:
            return {"shows": len(self.shows), "movies": len(self.movies),
                    "episodes": sum(1 for i in self.items.values() if i["kind"] == "episode"),
                    "extras": sum(1 for i in self.items.values() if i["kind"] == "extra"),
                    "tracks": len(self.music["tracks"]), "albums": len(self.music["albums"]),
                    "music_videos": len(self.music["videos"]),
                    "files": len(self.items)}

    # ------------------------------------------------------------ change detection

    @staticmethod
    def roots():
        return {k: config.path(k) for k in ("shows", "movies", "music", "musicvideos")}

    def current_signature(self):
        h = hashlib.sha1()
        for key, root in sorted(self.roots().items()):
            for d, dirs, _files in os.walk(root):
                dirs[:] = sorted(x for x in dirs if not x.startswith("."))
                try:
                    h.update(("%s|%d\n" % (d, os.stat(d).st_mtime_ns)).encode())
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
            shows, items = [], {}
            root = config.path("shows")
            if os.path.isdir(root):
                for name in sorted(os.listdir(root), key=str.lower):
                    d = os.path.join(root, name)
                    if os.path.isdir(d) and not name.startswith("."):
                        show = self._scan_show(d, name, items)
                        if show:
                            shows.append(show)
            movies = self._scan_movies(config.path("movies"), items)
            tunes = music.scan(self.art_url, items)
            with self.lock:
                self.shows, self.movies, self.items, self.music = shows, movies, items, tunes
                self.generated = int(time.time())
                self.signature = signature
            self.last_scan_seconds = round(time.time() - started, 1)
            n_eps = sum(1 for i in items.values() if i["kind"] == "episode")
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

    def _scan_show(self, show_dir, name, items):
        show_id = "s:" + naming.slug(name)
        episodes, extras, season_art = [], [], {}
        for d, dirs, files in os.walk(show_dir):
            dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x != "metadata")
            rel_parts = os.path.relpath(d, show_dir).split(os.sep)
            dir_season = naming.season_of_dir(rel_parts[0]) if rel_parts[0] != "." else None
            in_extras = rel_parts[0].lower() in ("extras", "featurettes", "behind the scenes", "trailers")
            if dir_season is not None and d == os.path.join(show_dir, rel_parts[0]):
                season_art.setdefault(dir_season, self.find_art(d, "poster"))
            for f in sorted(files):
                stem, ext = os.path.splitext(f)
                if ext.lower() not in naming.VIDEO_EXT or f.startswith("._"):
                    continue
                path = os.path.join(d, f)
                ep = None if in_extras else naming.parse_episode(stem)
                if not ep and dir_season is not None and not in_extras:
                    m = re.match(r"^(?:e|ep|episode)?\s*(\d{1,3})\b", stem, re.I)
                    if m:
                        ep = {"s": dir_season, "e": int(m.group(1)), "e2": None, "title": naming.clean(stem[m.end():])}
                if ep:
                    episodes.append((ep, path))
                else:
                    extras.append(path)
        if not episodes and not extras:
            return None

        info, eps_meta = {}, {}
        show_meta = metadata.tv_show(name) if episodes else None
        if show_meta:
            info = metadata.show_info(show_meta)
            eps_meta = metadata.episodes(show_meta)
        poster = self.find_art(show_dir, "poster")
        backdrop = self.find_art(show_dir, "backdrop")
        if not poster and info.get("poster_url") and self._budget():
            if metadata.download(info["poster_url"], os.path.join(show_dir, "folder.jpg")):
                poster = os.path.join(show_dir, "folder.jpg")
        if not backdrop and info.get("backdrop_url") and self._budget():
            if metadata.download(info["backdrop_url"], os.path.join(show_dir, "backdrop.jpg")):
                backdrop = os.path.join(show_dir, "backdrop.jpg")

        seasons = {}
        seen = set()
        for ep, path in sorted(episodes, key=lambda x: (x[0]["s"], x[0]["e"], x[1])):
            item_id = "e:%s:%d:%d" % (naming.slug(name), ep["s"], ep["e"])
            n = 2
            while item_id in seen:
                item_id = "e:%s:%d:%d:%d" % (naming.slug(name), ep["s"], ep["e"], n)
                n += 1
            seen.add(item_id)
            item = self._media(path, "episode", item_id)
            meta = eps_meta.get((ep["s"], ep["e"]), {})
            if not item["thumb_path"] and meta.get("thumb_url") and self._budget():
                dest = os.path.join(os.path.dirname(path), "metadata", os.path.splitext(os.path.basename(path))[0] + ".jpg")
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if metadata.download(meta["thumb_url"], dest):
                    item["thumb_path"] = dest
            item.update(show_id=show_id, s=ep["s"], e=ep["e"], e2=ep.get("e2"),
                        title=meta.get("title") or ep.get("title") or None, summary=meta.get("summary"),
                        aired=meta.get("aired"), runtime=meta.get("runtime"))
            items[item_id] = item
            seasons.setdefault(ep["s"], []).append(item)
        extra_items = []
        for path in extras:
            title = naming.clean(os.path.splitext(os.path.basename(path))[0]) or "Extra"
            item_id = "x:%s:%s" % (naming.slug(name), naming.slug(title))
            item = self._media(path, "extra", item_id)
            item.update(show_id=show_id, title=title)
            items[item_id] = item
            extra_items.append(item)

        def pub(i):
            out = {k: v for k, v in i.items() if k not in ("path", "thumb_path", "subs")}
            out["thumb"] = self.art_url("shows", i["thumb_path"])
            out["file"] = os.path.basename(i["path"])
            out["subs"] = len(i["subs"])
            return out

        added = max([i["added"] for i in items.values() if i.get("show_id") == show_id] or [0])
        show = {"id": show_id, "name": name, "added": added,
                "poster": self.art_url("shows", poster), "backdrop": self.art_url("shows", backdrop),
                "logo": self.art_url("shows", self.find_art(show_dir, "logo")),
                "seasons": [{"n": n, "poster": self.art_url("shows", season_art.get(n)),
                             "episodes": [pub(i) for i in eps]} for n, eps in sorted(seasons.items())],
                "extras": [pub(i) for i in sorted(extra_items, key=lambda i: i["title"].lower())]}
        show.update({k: info.get(k) for k in ("summary", "genres", "premiered", "ended", "network", "rating", "runtime")})
        return show

    def _scan_movies(self, root, items):
        movies = []
        if not os.path.isdir(root):
            return movies

        def videos_in(d):
            try:
                return [os.path.join(d, f) for f in os.listdir(d)
                        if os.path.splitext(f)[1].lower() in naming.VIDEO_EXT and not f.startswith(".")]
            except OSError:
                return []

        def add(path, title, year, directory, collection):
            item_id = "m:%s:%s" % (naming.slug(title), year or "")
            if item_id in items:
                item_id += ":" + naming.slug(os.path.basename(path))
            item = self._media(path, "movie", item_id)
            poster = self.find_art(directory, "poster") if directory else None
            backdrop = self.find_art(directory, "backdrop") if directory else None
            meta = metadata.movie(title, year) or {}
            if directory and not poster and meta.get("poster_url") and self._budget():
                if metadata.download(meta["poster_url"], os.path.join(directory, "folder.jpg")):
                    poster = os.path.join(directory, "folder.jpg")
            if directory and not backdrop and meta.get("backdrop_url") and self._budget():
                if metadata.download(meta["backdrop_url"], os.path.join(directory, "backdrop.jpg")):
                    backdrop = os.path.join(directory, "backdrop.jpg")
            item.update(title=title, year=year, collection=collection, summary=meta.get("summary"),
                        rating=meta.get("rating"))
            items[item_id] = item
            out = {k: v for k, v in item.items() if k not in ("path", "thumb_path", "subs")}
            out.update(poster=self.art_url("movies", poster or item["thumb_path"]),
                       backdrop=self.art_url("movies", backdrop),
                       logo=self.art_url("movies", self.find_art(directory, "logo") if directory else None),
                       file=os.path.basename(path), subs=len(item["subs"]))
            movies.append(out)

        def visit(d, collection):
            for name in sorted(os.listdir(d), key=str.lower):
                p = os.path.join(d, name)
                if name.startswith("."):
                    continue
                if os.path.isfile(p) and os.path.splitext(name)[1].lower() in naming.VIDEO_EXT:
                    title, year = naming.parse_movie(os.path.splitext(name)[0])
                    add(p, title, year, None, collection)
                elif os.path.isdir(p):
                    vids = videos_in(p)
                    if vids:
                        title, year = naming.parse_movie(name)
                        add(max(vids, key=os.path.getsize), title, year, p, collection)
                    elif collection is None:
                        visit(p, name)
        visit(root, None)
        movies.sort(key=lambda m: ((m.get("collection") or m["title"]).lower(), m.get("year") or 0))
        return movies

    def _budget(self):
        self._downloads += 1
        return self._downloads <= ART_DOWNLOADS_PER_SCAN


LIBRARY = Library()
