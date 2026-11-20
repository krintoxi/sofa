"""A free copy of the disc's film: when the film is in the public domain (or under a licence that lets anyone copy
it) and the Internet Archive has it, Sofa downloads it from there into Movies, named and with its poster.

Only films the archive itself marks as free to copy are offered: a public domain mark or CC0, a Creative Commons
licence that allows copying, or (with no licence given) a film from the archive's Feature Films collection made
before 1929, whose copyright in the United States has run out. What's asked of archive.org: the film's name and
year, nothing else, and only while Sofa may look things up (not Work offline).
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid

from . import config, fileops, naming, net, store

SEARCH = "https://archive.org/advancedsearch.php"
META = "https://archive.org/metadata/"
FILES = "https://archive.org/download/"
UA = "Sofa (github.com/krintoxi/sofa)"
FREE = re.compile(r"publicdomain|/zero/|creativecommons\.org/licenses/by(-sa)?/", re.I)
OLD_ENOUGH = 1929                                           # (made before: its US copyright has run out)
_lock = threading.Lock()
_job = {}
_found = {}                                                 # (name, year) -> what was found, or None


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with net.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def free(doc):
    """Why this archive.org film may be copied by anyone, or None."""
    lic = str(doc.get("licenseurl") or "")
    if FREE.search(lic):
        return "public domain" if re.search(r"publicdomain|/zero/", lic, re.I) else "a Creative Commons licence"
    year = _year(doc.get("year") or doc.get("date"))
    cols = doc.get("collection") or []
    cols = cols if isinstance(cols, list) else [cols]
    if not lic and "feature_films" in cols and year and year < OLD_ENOUGH:
        return "public domain (made in %d)" % year
    return None


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
    with _lock:
        return dict(_job) or None


def download(name, year=None, who="someone"):
    """Start downloading the free copy of `name` into Movies. Raises ValueError with a plain reason."""
    hit = find(name, year)
    if not hit:
        raise ValueError("The Internet Archive has no free copy of %s." % name)
    full = naming.safe_filename("%s (%s)" % (hit["title"], hit["year"]) if hit["year"] else hit["title"])
    from . import disc
    folder = os.path.join(disc._root("movies"), full)
    ext = os.path.splitext(hit["file"])[1].lower()
    dest = os.path.join(folder, full + ext)
    if os.path.lexists(dest) or (os.path.isdir(folder) and any(os.path.splitext(f)[1].lower() in naming.VIDEO_EXT for f in os.listdir(folder))):
        raise ValueError("%s is already in Movies." % full)
    disc._room(folder, hit["size"] or 2 << 30)
    with _lock:
        if _job.get("state") == "working":
            raise ValueError("A free copy is being downloaded already.")
        _job.clear()
        _job.update(id=uuid.uuid4().hex[:10], name=full, state="working", done=0, total=hit["size"], error=None, why=hit["why"], page=hit["page"])
        job = dict(_job)
    threading.Thread(target=_fetch, args=(job, hit, folder, dest, who), daemon=True, name="free-copy").start()
    return {"ok": True, "name": full}


def _fetch(job, hit, folder, dest, who):
    os.makedirs(folder, exist_ok=True)
    stage = os.path.join(folder, ".sofa-free-%s%s" % (job["id"], os.path.splitext(dest)[1]))
    state, error = "done", None
    try:
        url = FILES + urllib.parse.quote(hit["id"]) + "/" + urllib.parse.quote(hit["file"])
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with net.urlopen(req, timeout=60) as r, open(stage, "xb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                with _lock:
                    if _job.get("id") == job["id"]:
                        _job["done"] += len(chunk)
            out.flush()
            os.fsync(out.fileno())
        fileops.place(stage, dest)
    except FileExistsError:
        state, error = "failed", "A file with that name appeared meanwhile. Sofa doesn't write over a file."
    except Exception as exc:
        state, error = "failed", "The download stopped: %s" % (getattr(exc, "reason", None) or exc)
    finally:
        if os.path.exists(stage):
            os.unlink(stage)
        if state != "done":
            try:
                os.rmdir(folder)
            except OSError:
                pass
    with _lock:
        if _job.get("id") == job["id"]:
            _job.update(state=state, error=error, finished=time.time())
    store.log("disc", ("Saved %s from the Internet Archive (%s)" % (job["name"], job["why"])) if state == "done" else
              "Downloading %s stopped: %s" % (job["name"], error), {"by": who, "from": hit["page"]})
    if state == "done":
        from . import disc
        if disc.saved:
            threading.Thread(target=disc._tell, daemon=True).start()
