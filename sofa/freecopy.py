"""A free copy of the disc's film: when the film is in the public domain (or under a licence that lets anyone copy
it) and the Internet Archive has it, Sofa downloads it from there into Movies, named and with its poster.

Only films the archive itself marks as free to copy are offered: a public domain mark or CC0, a Creative Commons
licence that allows copying, or (with no licence given) a film from the archive's Feature Films collection made
before 1929, whose copyright in the United States has run out. What's asked of archive.org: the film's name and
year, nothing else, and only while Sofa may look things up (not Work offline).

The licence rules and the download are Free to keep's (sofa/freefilms.py): one place Sofa gets free films from. The
disc page keeps to the licences that allow any use (no NC or ND), as it always has.
"""
import os
import re
import urllib.parse

from . import config, freefilms, naming

SEARCH = freefilms.SEARCH
META = freefilms.META
FILES = freefilms.FILES
UA = freefilms.UA
OLD_ENOUGH = freefilms.OLD_ENOUGH
_found = {}                                                 # (name, year) -> what was found, or None
_last = [None, None, None]                                           # the disc page's own download (an id in Free to keep's queue)


def _get(url, timeout=20):
    return freefilms._get(url, timeout)


def free(doc):
    """Why this archive.org film may be copied by anyone, or None (Free to keep's reading, any use allowed only)."""
    why = freefilms.why_free(doc)
    if not why or why.startswith("CC BY-N") or "-ND" in why or "-NC" in why:
        return None
    if why.startswith("Public domain (made in"):
        return why[0].lower() + why[1:]
    return "public domain" if why in ("Public domain", "CC0") else "a Creative Commons licence"


def _year(v):
    m = re.search(r"(18|19|20)\d\d", str(v or ""))
    return int(m.group(0)) if m else None


def _video(files):
    """The file to download: the best H.264 MP4 the archive keeps, else its MPEG-4, else the original."""
    vids = [f for f in files if str(f.get("name", "")).lower().endswith((".mp4", ".m4v", ".mkv", ".mpeg", ".mpg", ".avi", ".ogv"))]
    rank = lambda f: (str(f.get("format", "")).startswith("h.264"), str(f["name"]).lower().endswith(".mp4"), int(f.get("size") or 0))
    return max(vids, key=rank) if vids else None


def find(name, year=None, get=_get):
    """The film on archive.org, free to copy: {"id", "title", "year", "why", "file", "size", "page"}, or None."""
    if not name or config.get("offline"):
        return None
    key = (naming.norm(name), year)
    if key in _found:
        return _found[key]
    q = 'title:(%s) AND mediatype:(movies)' % re.sub(r'[^\w\s]', " ", name)
    try:
        docs = get(SEARCH + "?" + urllib.parse.urlencode([("q", q), ("rows", "50"), ("output", "json"), ("sort[]", "downloads desc"), ("fl[]", "identifier"),
                                                          ("fl[]", "title"), ("fl[]", "year"), ("fl[]", "date"), ("fl[]", "licenseurl"),
                                                          ("fl[]", "collection"), ("fl[]", "downloads")])).get("response", {}).get("docs") or []
    except Exception:
        return None                                          # (not remembered: asked again next time)
    best = None
    for d in sorted(docs, key=lambda d: -int(d.get("downloads") or 0)):
        title = str(d.get("title") or "")
        y = _year(d.get("year") or d.get("date"))
        bare = re.sub(r"\s*(?:\(\s*|-\s*)?(?:18|19|20)\d\d\s*\)?\s*$", "", title)      # ("Nosferatu (1922)", "His Girl Friday - 1940")
        y = y or _year(title[len(bare):])
        if naming.norm(bare) != naming.norm(name) or (year and y and abs(int(year) - y) > 1):
            continue
        why = free(d)
        if not why:
            continue
        try:
            meta = get(META + urllib.parse.quote(d["identifier"]))
        except Exception:
            continue
        f = _video(meta.get("files") or [])
        if f:
            best = {"id": d["identifier"], "title": bare, "year": y, "why": why, "file": f["name"], "size": int(f.get("size") or 0),
                    "page": "https://archive.org/details/" + d["identifier"]}
            break
    _found[key] = best
    return best


def status():
    """The disc page's free copy, as it goes (from Free to keep's queue)."""
    if not _last[0]:
        return None
    job = next((j for j in freefilms.status()["jobs"] if j["id"] == _last[0]), None)
    if not job:
        return None
    return {"id": job["id"], "name": job["name"], "state": job["state"] if job["state"] != "queued" else "working",
            "done": job["done"], "total": job["size"], "error": job["error"], "why": _last[1], "page": _last[2]}


def download(name, year=None, who="someone"):
    """Start downloading the free copy of `name` into Movies. Raises ValueError with a plain reason."""
    hit = find(name, year)
    if not hit:
        raise ValueError("The Internet Archive has no free copy of %s." % name)
    full = naming.safe_filename("%s (%s)" % (hit["title"], hit["year"]) if hit["year"] else hit["title"])
    dest = freefilms.where("movie", hit["title"], hit["year"], ext=os.path.splitext(hit["file"])[1].lower() or ".mp4")
    folder = os.path.dirname(dest)
    if os.path.lexists(dest) or (os.path.isdir(folder) and any(os.path.splitext(f)[1].lower() in naming.VIDEO_EXT for f in os.listdir(folder))):
        raise ValueError("%s is already in Movies." % full)
    from . import disc
    disc._room(folder, hit["size"] or 2 << 30)
    if any(j["state"] in ("queued", "working") and j["id"] == _last[0] for j in freefilms.status()["jobs"]):
        raise ValueError("A free copy is being downloaded already.")
    url = FILES + urllib.parse.quote(hit["id"]) + "/" + urllib.parse.quote(hit["file"])
    freefilms.queue([{"url": url, "dest": dest, "size": hit["size"], "kind": "movie", "item": hit["id"], "name": full,
                      "info": {"title": hit["title"], "year": hit["year"], "why": hit["why"], "page": hit["page"]}}], who)
    job = next((j for j in reversed(freefilms.status()["jobs"]) if j["item"] == hit["id"]), None)
    _last[0], _last[1], _last[2] = (job or {}).get("id"), hit["why"], hit["page"]
    return {"ok": True, "name": full}
