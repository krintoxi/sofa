"""Free to keep: films and TV shows anyone may download and keep, from the Internet Archive (archive.org), saved into
Movies and Shows like any other file. The one place Sofa finds free films: the disc page's "Get it free"
(sofa/freecopy.py) and the Adult section's Free to keep (sofa/freeadult.py) use its licence rules and its downloads.

Which films: an item the Archive marks with a public-domain mark, CC0 or a Creative Commons licence (each lets anyone
copy and keep the work; NC ones not for money), or, with no licence given, a film in its Feature Films collection made
before 1929, whose copyright in the United States has run out. The mark is the uploader's word, as on the Archive
itself: Sofa shows it plainly on each film and keeps it with the saved file. Adult films are never offered here (the
Archive's own no-preview collection, and titles or subjects that say sex or nudity): they're only in the Adult section.

What Sofa asks the Archive: its public search (advancedsearch.php) and an item's details (/metadata/<item>), kept six
hours; then the chosen files, from /download/. Only for an admin, only while Sofa may use the internet, never on a
public Sofa. One download at a time, into Movies/<Title (Year)>/ or Shows/<Show>/Season 1/, with an .nfo beside it
saying where it came from and under which licence.
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
IMAGE = "https://archive.org/services/img/"
PAGE = "https://archive.org/details/"
UA = "Sofa (github.com/krintoxi/sofa)"
FRESH = 6 * 3600
OLD_ENOUGH = 1929                 # made before this: its US copyright has run out
MAX_FILE = 8 * 2**30
fetch_json = None                 # tests put their own reader here: (url) -> the decoded reply

MOVIES_Q = ("collection:(feature_films) AND mediatype:(movies) AND -collection:(no-preview) AND "
            "(licenseurl:(*publicdomain* OR *creativecommons*) OR year:[1880 TO %d])" % (OLD_ENOUGH - 1))
SHOWS_Q = ("collection:(classic_tv) AND mediatype:(movies) AND -collection:(no-preview) AND "
           "licenseurl:(*publicdomain* OR *creativecommons*)")
ADULT = re.compile(r"\b(sex\w*|nud(e|es|ie|ist\w*|ity)|naked|erotic\w*|porn\w*|stag|burlesque|strip\w*|xxx|"
                   r"exploitation|sexploitation|no-preview)\b", re.I)
KINDS = (("Film noir", r"noir"), ("Horror", r"horror|monster|zombie|vampire"), ("Science fiction", r"sci-?fi|science fiction|space"),
         ("Westerns", r"western|cowboy"), ("Comedy", r"comed|funny|slapstick"), ("Mystery", r"mystery|detective|sherlock|crime"),
         ("War", r"\bwar\b|world war"), ("Adventure", r"adventure|jungle|tarzan|pirate"), ("Silent films", r"silent"),
         ("Animation", r"animation|cartoon"), ("Musicals", r"musical"), ("Drama", r"drama|romance|melodrama"))
VIDEO = (".mp4", ".m4v", ".mkv", ".ogv", ".mpeg", ".mpg", ".avi", ".webm", ".mov")

_lock = threading.Lock()
_cache = {}                       # key -> {"at", "value"}
_jobs = []                        # the download queue, oldest first
_wake = threading.Event()
_worker = [None]
saved = None                      # called after a file is in place, so the library is read again (web.py sets it)


# ---------------------------------------------------------------- the licence

def free_licence(url):
    """A licence that lets anyone copy and keep the work: its short name, or None."""
    u = (url or "").lower()
    if "publicdomain/mark" in u or "licenses/publicdomain" in u:
        return "Public domain"
    if "publicdomain/zero" in u:
        return "CC0"
    m = re.search(r"creativecommons\.org/licenses/(by(?:-nc)?(?:-sa|-nd)?)/", u)
    return "CC " + m.group(1).upper() if m else None


def year_of(v):
    m = re.search(r"(18|19|20)\d\d", str(v or ""))
    return int(m.group(0)) if m else None


def why_free(doc):
    """Why this Archive item may be copied and kept by anyone, in words, or None."""
    lic = free_licence(doc.get("licenseurl"))
    if lic:
        return lic
    year = year_of(doc.get("year") or doc.get("date"))
    cols = doc.get("collection") or []
    cols = cols if isinstance(cols, list) else [cols]
    if not doc.get("licenseurl") and "feature_films" in cols and year and year < OLD_ENOUGH:
        return "Public domain (made in %d)" % year
    return None


LICENCE_WORDS = {
    "Public domain": "No one owns it any more: anyone may copy, keep and share it.",
    "CC0": "Its maker gave up every right to it: anyone may copy, keep and share it.",
    "CC BY": "Anyone may copy, keep and share it, saying who made it.",
    "CC BY-SA": "Anyone may copy, keep and share it, saying who made it, under the same licence.",
    "CC BY-ND": "Anyone may copy, keep and share it unchanged, saying who made it.",
    "CC BY-NC": "Anyone may copy, keep and share it, not for money, saying who made it.",
    "CC BY-NC-SA": "Anyone may copy, keep and share it, not for money, saying who made it, under the same licence.",
    "CC BY-NC-ND": "Anyone may copy, keep and share it unchanged, not for money, saying who made it.",
}


def licence_words(why):
    if why.startswith("Public domain (made in"):
        return "Made before %d: its copyright in the United States has run out." % OLD_ENOUGH
    return LICENCE_WORDS.get(why, "")


# ---------------------------------------------------------------- asking the Archive

def _get(url, timeout=20):
    if fetch_json:
        return fetch_json(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with net.urlopen(req, timeout=timeout, whole_internet=False) as r:
        return json.loads(r.read(16 * 2**20).decode("utf-8", "replace"))


def _kept(key, make):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit["at"] < FRESH:
            return hit["value"]
    value = make()
    with _lock:
        _cache[key] = {"at": time.time(), "value": value}
    return value


def _text(*parts):
    out = []
    for p in parts:
        if isinstance(p, (list, tuple)):
            out.extend(str(x) for x in p)
        elif p:
            out.append(str(p))
    return " ".join(out).replace("_", " ")


def clean(text, most=600):
    t = re.sub(r"<[^>]+>", " ", str(text or ""))
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    t = re.sub(r"&amp;", "&", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:most].rsplit(" ", 1)[0] + "…" if len(t) > most else t


def kind_of(*parts, default="Drama"):
    text = _text(*parts).lower()
    for name, pat in KINDS:
        if re.search(pat, text):
            return name
    return default


def _bare(title):
    """ "Nosferatu (1922)", "His Girl Friday - 1940" -> the title alone."""
    return re.sub(r"\s*(?:\(\s*|-\s*)?(?:18|19|20)\d\d\s*\)?\s*$", "", str(title or "")).strip() or str(title or "")


def _search(q, rows, fields=("identifier", "title", "year", "date", "licenseurl", "subject", "description", "downloads", "collection")):
    params = [("q", q)] + [("fl[]", f) for f in fields] + [("sort[]", "downloads desc"), ("rows", str(rows)), ("output", "json")]
    return (_get(SEARCH + "?" + urllib.parse.urlencode(params)).get("response") or {}).get("docs") or []


def _film(doc):
    item = str(doc.get("identifier") or "")
    why = why_free(doc)
    if not why or not re.match(r"^[\w.-]{1,120}$", item) or ADULT.search(_text(doc.get("title"), doc.get("subject"), doc.get("collection"))):
        return None
    title = clean(_bare(doc.get("title") or item), 120)
    year = year_of(doc.get("year") or doc.get("date")) or year_of(doc.get("title"))
    tv = "classic_tv" in str(doc.get("collection") or "")
    return {"id": item, "title": title, "year": year, "kind": kind_of(doc.get("subject"), doc.get("title"), default=None if tv else "Drama"),
            "why": why, "about": clean(doc.get("description"), 300), "views": int(doc.get("downloads") or 0),
            "image": IMAGE + item, "page": PAGE + item}


SHOW_CUT = re.compile(r"\s*(?:\b(?:public domain|pd)\b.*|\(?\s*\bTV (?:show|series)\b.*|\bep(?:isode)?\.?\s*\d+\b.*|\(\s*(?:18|19|20)\d\d\s*\)|"
                      r"\s[:\-–]\s.*|\bseason\s*\d+\b.*)$", re.I)


def show_name(title):
    """The show an item belongs to, from its title: "Beverly Hillbillies Ep01 The Clampetts Strike Oil",
    "The Beverly Hillbillies : The Servants" -> "Beverly Hillbillies"; "Bonanza public domain episodes" -> "Bonanza"."""
    t = clean(title, 200)
    for _ in range(3):
        t = SHOW_CUT.sub("", t).strip(" -:–")
    t = re.sub(r"\bepisodes?\b", "", t, flags=re.I).strip(" -:–")
    return re.sub(r"^the\s+", "", t, flags=re.I).strip() or clean(title, 80)


def _key(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "show"


def catalogue(kind="movies"):
    """Movies: [film]. Shows: [show], a show being the Archive items of one series, {"id", "title", "items", ...}.
    Raises OSError when the Archive doesn't answer (nothing is kept then)."""
    def movies():
        out, seen = [], set()
        for doc in _search(MOVIES_Q, 400):
            f = _film(doc)
            k = f and re.sub(r"\W+", "", f["title"].lower()) + str(f["year"] or "")
            if f and k not in seen:
                seen.add(k)
                out.append(f)
        return out

    def shows():
        groups = {}
        for doc in _search(SHOWS_Q, 400):
            f = _film(doc)
            if not f:
                continue
            name = show_name(doc.get("title") or f["id"])
            g = groups.setdefault(_key(name), {"id": _key(name), "title": name, "items": [], "views": 0, "why": f["why"],
                                               "image": f["image"], "about": f["about"], "year": f["year"], "kind": f["kind"]})
            g["items"].append(f["id"])
            g["views"] += f["views"]
            g["year"] = min([y for y in (g["year"], f["year"]) if y] or [None]) if (g["year"] or f["year"]) else None
            if not g["about"] and f["about"]:
                g["about"] = f["about"]
            if g["why"] != f["why"]:
                g["why"] = "Public domain" if all(w.startswith("Public domain") for w in (g["why"], f["why"])) else "Several licences"
        return sorted(groups.values(), key=lambda g: -g["views"])
    kind = "shows" if kind == "shows" else "movies"
    return _kept(("catalogue", kind), shows if kind == "shows" else movies)


def _files(item, meta):
    """An item's videos: the best file of each (one film in several sizes is one), in the item's own order."""
    groups, order = {}, []
    for f in meta.get("files") or []:
        name = str(f.get("name") or "")
        if not name.lower().endswith(VIDEO) or "/" in name or f.get("source") == "metadata":
            continue
        try:
            size = int(f.get("size") or 0)
        except ValueError:
            size = 0
        if not size or size > MAX_FILE:
            continue
        stem = re.sub(r"(_512kb|\.(ogv|ogg|webm|mp4|m4v|mkv|avi|mov|mpe?g|\d{3,4}p|ia))+$", "", name, flags=re.I)
        rank = (str(f.get("format") or "").lower().startswith("h.264"), name.lower().endswith(".mp4"), size)
        if stem not in groups:
            order.append(stem)
        if stem not in groups or rank > groups[stem][0]:
            groups[stem] = (rank, {"file": name, "size": size, "length": f.get("length"), "title": f.get("title")})
    out = []
    for stem in order:
        f = groups[stem][1]
        f["url"] = FILES + urllib.parse.quote(item) + "/" + urllib.parse.quote(f["file"])
        f["name"] = clean(f.get("title") or stem.replace("_", " "), 120)
        out.append(f)
    return out


def _seconds(v):
    try:
        if ":" in str(v):
            p = [float(x) for x in str(v).split(":")]
            return int(sum(x * 60 ** i for i, x in enumerate(reversed(p))))
        return int(float(v))
    except (TypeError, ValueError):
        return None


def item(item_id):
    """One Archive item in full: its details, its licence, its videos. None when it isn't free to keep (any more)."""
    if not re.match(r"^[\w.-]{1,120}$", item_id or ""):
        return None

    def make():
        meta = _get(META + urllib.parse.quote(item_id))
        m = meta.get("metadata") or {}
        doc = dict(m, identifier=item_id)
        f = _film(doc)
        if not f:
            return None
        files = _files(item_id, meta)
        if not files:
            return None
        f.update(about=clean(m.get("description"), 2000), files=files, length=_seconds(files[0].get("length")) if len(files) == 1 else None,
                 words=licence_words(f["why"]), licence_url=m.get("licenseurl") or None,
                 who=clean(m.get("creator") or m.get("director") or "", 120) or None)
        return f
    return _kept(("item", item_id), make)


def show(show_id):
    """A show of the catalogue with its items' episodes: {"title", "episodes": [{"item", "file", "name", "n"}], ...}."""
    hit = next((s for s in catalogue("shows") if s["id"] == show_id), None)
    if not hit:
        return None
    eps = []
    for iid in hit["items"][:24]:
        it = item(iid)
        if not it:
            continue
        for k, f in enumerate(it["files"]):
            title = it["title"] if len(it["files"]) == 1 else f["name"]
            m = re.search(r"\bep(?:isode)?\.?\s*(\d{1,3})\b", title, re.I) or re.search(r"\bep(?:isode)?\.?\s*(\d{1,3})\b", f["file"], re.I)
            eps.append({"item": iid, "file": f["file"], "url": f["url"], "size": f["size"], "why": it["why"], "page": it["page"],
                        "name": re.sub(r"^.*?\bep(?:isode)?\.?\s*\d{1,3}\b\s*[:\-–]?\s*", "", title, flags=re.I).strip() or title,
                        "n": int(m.group(1)) if m else None})
    used = set()
    for e in eps:                                     # (a number two parts both claim: the first keeps it)
        if e["n"] in used:
            e["n"] = None
        elif e["n"]:
            used.add(e["n"])
    nxt = 1
    for e in eps:                                     # (no number of its own: the next free one, in the Archive's order)
        if not e["n"]:
            while nxt in used:
                nxt += 1
            e["n"], nxt = nxt, nxt + 1
            used.add(e["n"])
    for e in eps:                                     # ("Bonanza - Death on Sun Mountain": the episode's own name)
        e["name"] = re.sub(r"^\s*(?:the\s+)?%s\s*[:\-–]\s*" % re.escape(hit["title"]), "", e["name"], flags=re.I).strip() or e["name"]
    eps.sort(key=lambda e: e["n"])
    return dict(hit, episodes=eps)


# ---------------------------------------------------------------- saving

def _root(key):
    from . import disc
    return disc._root(key)


def where(kind, title, year=None, show_title=None, n=None, ext=".mp4"):
    """Where a saved film or episode goes: Movies/<Title (Year)>/<Title (Year)>.ext or
    Shows/<Show>/Season 1/<Show> S01E05 <Episode>.ext."""
    if kind == "movie":
        full = naming.safe_filename("%s (%s)" % (title, year) if year else title)[:120]
        return os.path.join(_root("movies"), full, full + ext)
    show = naming.safe_filename(show_title or "Show")[:100]
    name = naming.safe_filename("%s S01E%02d %s" % (show, n or 1, title))[:150].rstrip()
    return os.path.join(_root("shows"), show, "Season 1", name + ext)


def _nfo(dest, kind, info):
    """What the saved file is and where it came from, beside it (Sofa reads it, and so do other players)."""
    def el(tag, value):
        v = str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return "  <%s>%s</%s>\n" % (tag, v, tag) if v else ""
    root = "movie" if kind == "movie" else "episodedetails"
    body = (el("title", info.get("title")) + el("year", info.get("year")) + el("plot", info.get("about")) +
            el("genre", info.get("kind")) + el("studio", "Internet Archive") + el("tag", "Free to keep") +
            el("source", info.get("page")) + el("licence", info.get("why")) + el("licenseurl", info.get("licence_url")))
    path = os.path.splitext(dest)[0] + ".nfo"
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<%s>\n%s</%s>\n' % (root, body, root))


def queue(entries, who="someone"):
    """Put films or episodes in the download queue: entries are {"url", "dest", "size", "kind", "name", "item",
    "info"}. What's in place already or waiting already is skipped. {"queued", "skipped"}."""
    if net.offline_mode():
        raise ValueError("Sofa is set to work offline (Server, Settings), so it can't download anything.")
    queued = skipped = 0
    with _lock:
        waiting = {j["dest"] for j in _jobs if j["state"] in ("queued", "working")}
        for e in entries:
            if e["dest"] in waiting or os.path.lexists(e["dest"]):
                skipped += 1
                continue
            _jobs.append(dict(e, id=uuid.uuid4().hex[:10], state="queued", done=0, error=None, who=who, at=time.time()))
            waiting.add(e["dest"])
            queued += 1
        del _jobs[:max(0, len(_jobs) - 300)]
    _start()
    _wake.set()
    return {"queued": queued, "skipped": skipped}


def save_movie(item_id, who="someone"):
    it = item(item_id)
    if not it:
        raise ValueError("That film isn't free to keep at the Internet Archive (any more).")
    f = it["files"][0] if len(it["files"]) == 1 else max(it["files"], key=lambda f: f["size"])
    dest = where("movie", it["title"], it["year"], ext=os.path.splitext(f["file"])[1].lower() or ".mp4")
    folder = os.path.dirname(dest)
    if os.path.isdir(folder) and any(os.path.splitext(x)[1].lower() in naming.VIDEO_EXT for x in os.listdir(folder)):
        return {"queued": 0, "skipped": 1}
    return queue([{"url": f["url"], "dest": dest, "size": f["size"], "kind": "movie", "item": item_id, "name": it["title"],
                   "info": {k: it.get(k) for k in ("title", "year", "about", "why", "page", "licence_url", "kind")}}], who)


def save_show(show_id, only=None, who="someone"):
    s = show(show_id)
    if not s or not s["episodes"]:
        raise ValueError("That show isn't free to keep at the Internet Archive (any more).")
    entries = []
    for e in s["episodes"]:
        if only and e["file"] not in only:
            continue
        dest = where("episode", e["name"], show_title=s["title"], n=e["n"], ext=os.path.splitext(e["file"])[1].lower() or ".mp4")
        entries.append({"url": e["url"], "dest": dest, "size": e["size"], "kind": "episode", "item": show_id, "name": e["name"],
                        "info": {"title": e["name"], "year": s.get("year"), "about": "", "why": e["why"], "page": e["page"]}})
    return queue(entries, who)


def status():
    """The queue for the pages: by film or show, how far each is."""
    with _lock:
        jobs = [{k: j[k] for k in ("id", "kind", "item", "name", "state", "done", "size", "error")} for j in _jobs]
    by = {}
    for j in jobs:
        b = by.setdefault(j["item"], {"done": 0, "size": 0, "files": 0, "left": 0, "failed": 0})
        b["done"] += j["done"] if j["state"] != "done" else j["size"]
        b["size"] += j["size"] or 0
        b["files"] += 1
        b["left"] += j["state"] in ("queued", "working")
        b["failed"] += j["state"] == "failed"
    return {"jobs": jobs[-60:], "items": by}


def _start():
    with _lock:
        if _worker[0] and _worker[0].is_alive():
            return
        _worker[0] = threading.Thread(target=_loop, daemon=True, name="free-films")
        _worker[0].start()


def _next():
    with _lock:
        for j in _jobs:
            if j["state"] == "queued":
                j["state"] = "working"
                return j
    return None


def _loop():
    while True:
        job = _next()
        if not job:
            _wake.wait(60)
            _wake.clear()
            continue
        _fetch(job)


def _fetch(job):
    dest = job["dest"]
    folder = os.path.dirname(dest)
    stage = os.path.join(folder, ".sofa-free-%s%s" % (job["id"], os.path.splitext(dest)[1]))
    state, error = "done", None
    try:
        os.makedirs(folder, exist_ok=True)
        req = urllib.request.Request(job["url"], headers={"User-Agent": UA})
        with net.urlopen(req, timeout=60, whole_internet=False) as r, open(stage, "xb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                with _lock:
                    job["done"] += len(chunk)
            out.flush()
            os.fsync(out.fileno())
        fileops.place(stage, dest)
        _nfo(dest, job["kind"], job.get("info") or {})
    except FileExistsError:
        state, error = "failed", "A file with that name appeared meanwhile. Sofa doesn't write over a file."
    except Exception as exc:
        state, error = "failed", "The download stopped: %s" % str(getattr(exc, "reason", None) or exc)[:200]
    finally:
        if os.path.exists(stage):
            os.unlink(stage)
        if state != "done":
            try:
                os.rmdir(folder)
            except OSError:
                pass
    with _lock:
        job.update(state=state, error=error, finished=time.time())
    info = job.get("info") or {}
    store.log("download", ("Saved %s from the Internet Archive (%s)" % (job["name"], info.get("why"))) if state == "done"
              else "Saving %s from the Internet Archive stopped: %s" % (job["name"], error), {"by": job.get("who"), "from": info.get("page")})
    if state == "done" and saved:
        try:
            saved()
        except Exception:
            pass
