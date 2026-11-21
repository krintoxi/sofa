"""Free to keep: adult films that may be downloaded and kept, from the Internet Archive (archive.org).

The Archive marks adult items itself (its `no-preview` collection), and each item says under which terms it was put
there. Sofa lists only adult films whose item says public domain (the Public Domain Mark, CC0) or a Creative Commons
licence: terms that let anyone copy and keep them. That is the uploader's word, as on the Archive itself.

What Sofa does:

  * Asks the Archive's public search and metadata APIs (advancedsearch.php, /metadata/<item>), nothing else, and keeps
    the answer six hours. A request to Sofa waits on the Archive at most once, when a list is asked for the first time.
  * Leaves out, by its title, subjects, description and file name, anything that suggests someone under 18, a family
    member, or no consent, and drawn or animated films (whose characters' ages nobody can vouch for). Better to miss
    a film than to keep one of those.
  * Saves a chosen number of them through Save from a link (sofa/fetch.py), into the Adult section, one at a time,
    skipping what was saved or queued before. Nothing is posted or shared anywhere.
  * Behind the Adult switch, for an admin who said they're 18 or older; never visitors, guests, Kids or a public Sofa.
"""
import json
import re
import threading
import time
import urllib.parse
import urllib.request

from . import freefilms, net

SEARCH = "https://archive.org/advancedsearch.php"
META = "https://archive.org/metadata/"
FRESH = 6 * 3600
MAX_FILE = 4 * 2**30              # a single film larger than this isn't offered
COUNTS = (5, 10, 25, 50)

BASE = "collection:(no-preview) AND mediatype:(movies) AND (licenseurl:*publicdomain* OR licenseurl:*creativecommons*)"
LAST_YEAR = 1977                  # in the US a film published before 1978 without a copyright notice is public domain
CATS = (
    ("vintage", "Vintage and stag films", 'subject:(stag OR "stag film" OR vintage OR "silent film" OR 1920s OR 1930s OR 1940s)'),
    ("pinup", "Pin-up, burlesque and nudie films", 'subject:(pinup OR "pin-up" OR burlesque OR nudie OR striptease OR "Irving Klaw")'),
    ("grindhouse", "Exploitation and grindhouse", "subject:(exploitation OR sexploitation OR grindhouse OR drive-in)"),
    ("fetish", "Fetish and bondage", "subject:(fetish OR bondage OR spanking)"),
    ("all", "Everything free to keep", ""),
)
CAT_NAMES = {c[0]: c[1] for c in CATS}

# Words that keep an item off the page wherever they appear in it (whole words, any case).
NEVER = re.compile(r"\b(" + "|".join((
    r"teens?", r"schools?", r"[eé]coles?", r"colleges?", r"classrooms?", r"campus", r"teenage\w*", r"tee?nie\w*", r"school\s?girls?", r"school\s?boys?", r"students?", r"pupils?", r"young\w*",
    r"youth", r"juniors?", r"lolit\w*", r"loli", r"shota\w*", r"under\s?age\w*", r"minors?", r"child\w*", r"kids?", r"babys?",
    r"barely", r"first\s?time", r"petite\s?girl", r"little\s?girls?", r"virgins?",
    r"incest\w*", r"step\w*", r"mother\w*", r"mom\w*", r"daughters?", r"sisters?", r"brothers?", r"father\w*", r"dad\w*",
    r"aunt\w*", r"uncle\w*", r"cousins?", r"family",
    r"rap(e|ed|ing)", r"forced", r"non.?consen\w*", r"drugg?ed", r"sleeping", r"unconscious", r"abuse\w*",
    r"hidden\s?cam\w*", r"spy\s?cam\w*", r"upskirt\w*", r"voyeur\w*", r"leak\w*", r"revenge",
    r"hentai", r"anime", r"ova", r"animat\w*", r"cartoons?", r"manga", r"3d", r"cgi",
    r"trailers?",
)) + r")\b", re.I)

VIDEO_FORMATS = {"h.264", "h.264 ia", "mpeg4", "512kb mpeg4", "matroska", "webm", "ogg video"}
_lock = threading.Lock()
_cache = {}                       # (cat, n) -> {"at", "items"} | {"at", "error"}
fetch_json = None                 # tests put their own reader here: (url) -> the decoded reply


def _get(url):
    if fetch_json:
        return fetch_json(url)
    req = urllib.request.Request(url, headers={"User-Agent": "Sofa", "Accept": "application/json"})
    with net.urlopen(req, timeout=20, whole_internet=False) as r:
        return json.loads(r.read(8 * 2**20).decode("utf-8", "replace"))


def free_licence(url):
    """A licence that lets anyone copy and keep the work: its short name, or None (Free to keep's reading)."""
    return freefilms.free_licence(url)


def _text(*parts):
    out = []
    for p in parts:
        if isinstance(p, (list, tuple)):
            out.extend(str(x) for x in p)
        elif p:
            out.append(str(p))
    return " ".join(out).replace("_", " ")


def blocked(*parts):
    return bool(NEVER.search(_text(*parts)))


OLD = re.compile(r"\b(1[89]\d\d|19[0-6]\d|197[0-7]|19[0-7]0s|stag|silent|nudie|peep\s?show|burlesque|pin.?up|vintage)\b", re.I)
NEW = re.compile(r"\b(197[89]|19[89]\d|20\d\d|19[89]0s|vhs|dvd|blu.?ray|hd|1080p|720p|4k|uncut|onlyfans|camgirl|webcam)\b", re.I)


def old_enough(year, *parts):
    """An item says its licence itself, and some say "free" of a recent studio's film, which isn't the uploader's to
    give. Sofa keeps to what's old enough to be free in the first place: a year before 1978, or words that say an
    old film (a decade, a stag or silent film), and nothing that says a recent one (VHS, DVD, HD, a later year)."""
    text = _text(*parts)
    try:
        y = int(str(year or "")[:4])
    except ValueError:
        y = 0
    if y > LAST_YEAR or NEW.search(text):
        return False
    return 1800 < y <= LAST_YEAR or bool(OLD.search(text))


STEM = re.compile(r"(_512kb|\.(ogv|ogg|webm|mp4|m4v|mkv|avi|mov|mpe?g|\d{3,4}p|vp9|ia))+$", re.I)


def _films(item, meta):
    """An item's films: the best video file of each (an item may hold one film in several sizes, or several films)."""
    groups = {}
    for f in meta.get("files") or []:
        name, fmt = f.get("name") or "", (f.get("format") or "").lower()
        if fmt not in VIDEO_FORMATS or "/" in name or blocked(name):
            continue
        try:
            size = int(f.get("size") or 0)
        except ValueError:
            size = 0
        if not size or size > MAX_FILE:
            continue
        stem = STEM.sub("", name)                       # (one film in several sizes: one stem)
        mp4 = name.lower().endswith(".mp4")
        best = groups.get(stem)
        if best is None or (mp4, size) > (best["mp4"], best["size"]):
            groups[stem] = {"name": name, "size": size, "mp4": mp4, "length": f.get("length")}
    out = []
    for stem, f in sorted(groups.items()):
        out.append({"url": "https://archive.org/download/%s/%s" % (urllib.parse.quote(item), urllib.parse.quote(f["name"])),
                    "file": f["name"], "size": f["size"], "stem": stem})
    return out


def _search(cat, rows):
    q = BASE + (" AND (%s)" % dict((c[0], c[2]) for c in CATS)[cat] if dict((c[0], c[2]) for c in CATS).get(cat) else "")
    params = [("q", q), ("fl[]", "identifier"), ("fl[]", "title"), ("fl[]", "licenseurl"), ("fl[]", "subject"),
              ("fl[]", "description"), ("fl[]", "year"), ("sort[]", "downloads desc"), ("rows", str(rows)), ("output", "json")]
    return (_get(SEARCH + "?" + urllib.parse.urlencode(params)).get("response") or {}).get("docs") or []


def listing(cat="vintage", n=25):
    """Up to n films of a category that may be kept: [{"title", "item", "page", "licence", "url", "size", "year"}]."""
    cat = cat if cat in CAT_NAMES else "vintage"
    n = n if n in COUNTS else 25
    with _lock:
        hit = _cache.get((cat, n))
        if hit and time.time() - hit["at"] < FRESH and "items" in hit:
            return {"cat": cat, "n": n, "items": hit["items"]}
    try:
        items, seen = [], set()
        for doc in _search(cat, max(n * 3, 30)):
            item = str(doc.get("identifier") or "")
            lic = free_licence(doc.get("licenseurl"))
            if not re.match(r"^[\w.-]{1,120}$", item) or not lic or \
                    blocked(doc.get("title"), doc.get("subject"), doc.get("description"), item) or \
                    not old_enough(doc.get("year"), doc.get("title"), doc.get("subject"), doc.get("description")):
                continue
            meta = _get(META + urllib.parse.quote(item))
            m = meta.get("metadata") or {}
            if not free_licence(m.get("licenseurl")) or "no-preview" not in _text(m.get("collection")) or \
                    blocked(m.get("title"), m.get("subject"), m.get("description")) or \
                    not old_enough(m.get("year") or m.get("date"), m.get("title"), m.get("subject"), m.get("description")):
                continue                                # (the item itself says so too, or it's left out)
            films = _films(item, meta)
            for f in films:
                stem = f["stem"].replace("_", " ").strip()
                title = str(doc.get("title") or item) if len(films) == 1 or len(stem) < 4 or stem.isdigit() else stem
                key = re.sub(r"\W+", "", title.lower())
                if key in seen:                         # (the same film in two items)
                    continue
                seen.add(key)
                items.append({"title": title[:160], "item": item, "page": "https://archive.org/details/" + item,
                              "licence": lic, "url": f["url"], "size": f["size"], "year": str(doc.get("year") or "")[:4]})
                if len(items) >= n:
                    break
            if len(items) >= n:
                break
    except Exception as exc:                            # (the Archive is busy or out of reach: say so, keep no answer)
        return {"cat": cat, "n": n, "items": [], "error": "The Internet Archive didn't answer (%s). Try again in a while." % str(exc)[:80]}
    with _lock:
        _cache[(cat, n)] = {"at": time.time(), "items": items}
    return {"cat": cat, "n": n, "items": items}


def save(cat, n, only=None):
    """Queue the films of a list (or just the `only` addresses among them) for saving into Adult. What was saved or
    queued before is skipped. {"queued", "skipped"}."""
    from . import fetch, store
    fetch._table()
    got = listing(cat, n)
    if got.get("error"):
        raise ValueError(got["error"])
    queued = skipped = 0
    for it in got["items"]:
        if only is not None and it["url"] not in only:
            continue
        if store.q1("SELECT 1 FROM downloads WHERE url = ? AND state != 'failed'", it["url"]):
            skipped += 1
            continue
        title = it["title"] if not it["year"] or it["year"] in it["title"] else "%s (%s)" % (it["title"], it["year"])
        fetch.add(it["url"], adult=True, title=title,
                  details={"year": it["year"] or (re.search(r"\b(1[89]\d\d|19[0-7]\d)\b", it["title"]) or [None, None])[1],
                           "page": it["page"], "studio": "Internet Archive", "tags": ["Free to keep", it["licence"]],
                           "summary": "From the Internet Archive (%s), %s." % (it["page"], it["licence"])})
        queued += 1
    return {"queued": queued, "skipped": skipped}


def cats():
    return [{"id": c[0], "name": c[1]} for c in CATS]
