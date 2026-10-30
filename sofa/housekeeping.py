"""Sofa's own files in data/cache: how much space they use, and freeing it.

Everything here is made again when it's needed: pictures resized for screens, scrubbing
previews, hover clips. Details found online are kept (they take a while to look up again);
only failed lookups can be forgotten, so Sofa asks again now instead of tomorrow.
"""
import json
import os
import shutil
import threading
import time

from . import artwork, media, metadata, naming, organizer, places, previews, store, travel, trickplay

REBUILDABLE = {"pictures sized for screens": artwork.CACHE, "scrubbing previews": trickplay.CACHE,
               "hover previews": previews.CACHE, "travel copies": travel.CACHE}
_sizes = {}
_lock = threading.Lock()


def _size(folder):
    total = 0
    for d, _dirs, files in os.walk(folder):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return total


def usage(max_age=600):
    """{"parts": {name: bytes}, "bytes": total}, measured at most every ten minutes."""
    with _lock:
        if time.time() - _sizes.get("at", 0) > max_age:
            parts = {name: _size(folder) for name, folder in REBUILDABLE.items()}
            _sizes.update(at=time.time(), parts=parts, bytes=sum(parts.values()))
        return {"parts": _sizes["parts"], "bytes": _sizes["bytes"]}


def free_space():
    for name, folder in REBUILDABLE.items():
        shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(trickplay.CACHE, exist_ok=True)
    open(os.path.join(trickplay.CACHE, trickplay.VERSION), "w").close()
    _sizes.clear()
    store.log("settings", "Freed the space used by Sofa's own pictures and previews (they're made again as needed)")


def retry_lookups():
    """Forget the lookups that found nothing, so the next scan asks again."""
    n = 0
    try:
        names = os.listdir(metadata.CACHE)
    except OSError:
        names = []
    for name in names:
        p = os.path.join(metadata.CACHE, name)
        try:
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("_miss"):
                    os.remove(p)
                    n += 1
        except (OSError, ValueError, AttributeError):
            pass
    store.log("settings", "Asked again for details Sofa couldn't find before (%d)" % n)
    return n


# ---------------------------------------------------------------- the same thing more than once

SUB_EXT = (".srt", ".vtt", ".ass", ".ssa", ".sub", ".idx")


def _better(item):
    """Which copy to keep: the sharper picture, then one every device plays as it is (MP4), then the bigger file."""
    if not item.get("height"):
        info = media.probe(item["path"]) or {}          # only duplicates are looked at this closely
        item["height"] = (info.get("video") or {}).get("height")
    return (item.get("height") or 0, item.get("ext") in ("mp4", "m4v"), item.get("size") or 0)


def _hand_over_subtitles(spare, keep):
    """Subtitles that came with the spare copy go to the one kept (unless it has that language already)."""
    folder, spare_stem = os.path.split(os.path.splitext(spare)[0])
    keep_stem = os.path.splitext(keep)[0]
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if name.startswith(spare_stem + ".") and name.lower().endswith(SUB_EXT):
            target = keep_stem + name[len(spare_stem):]
            if not os.path.exists(target):
                os.rename(os.path.join(folder, name), target)


def duplicates(library):
    """Episodes and movies that are in the library more than once (outside the Adult section): for each, the
    copies, best first. The best is kept; the others can go to Deleted."""
    groups = {}
    for item in list(library.items.values()):
        if item.get("adult") or item.get("kind") not in ("episode", "movie") or not item.get("path"):
            continue
        if item["kind"] == "episode":
            key = ("e", item.get("show_id"), item.get("s"), item.get("e"), item.get("e2"))
        else:
            entry = library.find(item["id"]) or {}
            key = ("m", naming.slug(entry.get("title") or item.get("title") or ""), entry.get("year"))
        groups.setdefault(key, []).append(item)
    out = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=_better, reverse=True)
        first = items[0]
        if key[0] == "e":
            show = library.find(first.get("show_id")) or {}
            label = "%s S%02dE%02d" % (show.get("name") or first.get("show_name") or "", first["s"], first["e"])
        else:
            entry = library.find(first["id"]) or {}
            label = "%s%s" % (entry.get("title") or first.get("title"), " (%s)" % entry["year"] if entry.get("year") else "")
        out.append({"key": "|".join(str(k) for k in key), "title": label, "kind": key[0] == "e" and "episode" or "movie",
                    "spare": sum(i.get("size") or 0 for i in items[1:]),
                    "copies": [{"id": i["id"], "file": os.path.basename(i["path"]), "size": i.get("size"),
                                "height": i.get("height"), "ext": i.get("ext"),
                                "where": (places.place_of(i["path"]) or {}).get("name") or "This computer"} for i in items]})
    return sorted(out, key=lambda g: -g["spare"])


def drop_duplicates(library, keys=None):
    """Keep the best copy of each (or of the groups in `keys`) and put the others in Deleted. Returns (copies, bytes)."""
    n = freed = 0
    for g in duplicates(library):
        if keys is not None and g["key"] not in keys:
            continue
        keep = library.item(g["copies"][0]["id"])
        for c in g["copies"][1:]:
            item = library.item(c["id"])
            if not item or not os.path.isfile(item["path"]) or not keep:
                continue
            same_name = os.path.splitext(item["path"])[0] == os.path.splitext(keep["path"])[0]
            if not same_name:
                _hand_over_subtitles(item["path"], keep["path"])
            if same_name:                          # Heat.mkv next to Heat.mp4: its subtitles and poster stay for the one kept
                organizer._put_aside(item["path"])
            else:
                organizer.relocate(item["path"], {"kind": "delete"})
            n += 1
            freed += c.get("size") or 0
    if n:
        store.log("library", "Put %d spare cop%s in Deleted (%s)" % (n, "y" if n == 1 else "ies", _gb(freed)))
    return n, freed


def _gb(b):
    return "%.1f GB" % (b / 1e9) if b >= 1e8 else "%d MB" % max(1, b // 1000000)
