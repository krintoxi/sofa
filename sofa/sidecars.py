"""Details that come with a video, in files next to it. No internet needed.

    <name>.info.json    written by yt-dlp ("Save from a link"): title, upload date, uploader,
                        cast, tags, description
    <name>.nfo          Kodi / Stash / scene-release style XML: title, plot, release date,
    movie.nfo           studio, actors, tags, a poster address
    tvshow.nfo          a show's own (Kodi): plot, genres, first aired, network (show(folder))

read(video) merges them into one dict (the .nfo wins where both say something, since
someone wrote it on purpose). Results are cached by size and modification time.
"""
import json
import os
import re
import threading
import xml.etree.ElementTree as ET

MAX_BYTES = 4 * 2**20
_cache = {}
_lock = threading.Lock()


def _date(text):
    """'20210314', '2021-03-14', '2021-03-14T10:00:00' -> '2021-03-14'; else None."""
    m = re.match(r"^\s*((?:19|20)\d{2})-?(\d{2})-?(\d{2})", str(text or ""))
    if not m or not (1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31):
        return None
    return "%s-%s-%s" % m.groups()


def _names(values):
    out = []
    for v in values or []:
        v = re.sub(r"\s+", " ", str(v)).strip()
        if v and v.lower() not in (x.lower() for x in out):
            out.append(v)
    return out


def _small(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) <= MAX_BYTES
    except OSError:
        return False


def _info_json(path):
    if not _small(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(j, dict):
        return {}
    cast = j.get("cast") or []
    if isinstance(cast, str):
        cast = re.split(r"\s*[,;]\s*", cast)
    return {"title": j.get("title") or j.get("fulltitle"), "date": _date(j.get("upload_date") or j.get("release_date")),
            "studio": j.get("uploader") or j.get("channel") or j.get("creator"),
            "performers": _names(cast if isinstance(cast, list) else []),
            "tags": _names((j.get("tags") or []) + (j.get("categories") or [])),
            "summary": (j.get("description") or "").strip()[:2000] or None,
            "poster_url": j.get("thumbnail") if str(j.get("thumbnail") or "").startswith(("http://", "https://")) else None,
            "link": j.get("webpage_url"), "source": "download"}


def _nfo(path):
    if not _small(path):
        return {}
    try:
        with open(path, "rb") as f:
            raw = f.read()
        if b"<!ENTITY" in raw or b"<!DOCTYPE" in raw:       # no entity tricks in a file we didn't write
            return {}
        root = ET.fromstring(raw)
    except (OSError, ET.ParseError):
        return {}

    def text(*tags):
        for t in tags:
            el = root.find(t)
            if el is not None and (el.text or "").strip():
                return el.text.strip()
        return None
    thumb = text("thumb", "art/poster")
    return {"title": text("title", "originaltitle"), "date": _date(text("premiered", "releasedate", "aired", "year")),
            "studio": text("studio", "label"),
            "performers": _names(a.findtext("name") for a in root.findall("actor")),
            "tags": _names([t.text for t in root.findall("tag") + root.findall("genre") if t.text]),
            "summary": text("plot", "outline"),
            "poster_url": thumb if thumb and thumb.startswith(("http://", "https://")) else None,
            "year": int(text("year")) if (text("year") or "").isdigit() else None,
            "source": "nfo"}


def read(video):
    """Everything the files next to `video` say about it (keys missing when nothing does)."""
    directory, name = os.path.split(video)
    stem = os.path.splitext(name)[0]
    candidates = [os.path.join(directory, stem + ".info.json"), os.path.join(directory, stem + ".nfo"),
                  os.path.join(directory, "movie.nfo")]
    sig = []
    for c in candidates:
        try:
            st = os.stat(c)
            sig.append((c, st.st_size, int(st.st_mtime)))
        except OSError:
            pass
    sig = tuple(sig)
    with _lock:
        hit = _cache.get(video)
        if hit and hit[0] == sig:
            return dict(hit[1])
    merged = {}
    for c in candidates:                               # later (the .nfo files) win
        part = _info_json(c) if c.endswith(".info.json") else _nfo(c)
        for k, v in part.items():
            if v:
                merged[k] = v
        if part.get("source") == "nfo":
            break                                      # the episode's own .nfo beats a folder-wide movie.nfo
    if merged.get("date"):
        merged["year"] = int(merged["date"][:4])
    if merged.get("year") and not 1900 < merged["year"] < 2100:
        merged.pop("year")
    with _lock:
        _cache[video] = (sig, merged)
    return dict(merged)


def show(folder):
    """A show folder's tvshow.nfo (Kodi): {"summary", "genres", "premiered", "network"}, or {}."""
    d = _nfo(os.path.join(folder, "tvshow.nfo"))
    if not d:
        return {}
    return {k: v for k, v in (("summary", d.get("summary")), ("genres", d.get("tags")), ("premiered", d.get("date")),
                              ("network", d.get("studio"))) if v}
