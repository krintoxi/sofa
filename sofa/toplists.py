"""Top lists in the Adult section: the 25 most watched videos of a category at a free site, from the site's own
documented API, each played in the site's own player.

What Sofa does and doesn't do here:

  * A site is in SITES only when its own terms say a third party may list its videos through its API and show them in
    its player, and they were read (docs/adult-sites.md has what each one says, and the sites left out and why).
  * Every site is off until the owner switches it on (Server, Settings). Until then Sofa asks that site nothing.
  * Sofa's server reads lists only: titles, lengths, the address of a picture and of the player. The video itself is
    never asked for, stored, passed on or converted by Sofa. It plays in the site's player, in the owner's browser,
    straight from the site, with the site's own notices, advertising and age checks, and with a link back to its page.
  * The pictures on the cards come to the browser straight from the site too. Sofa keeps no copy of them.
  * Lists are kept for half an hour (the site asks for five minutes at least) and asked for one at a time, in the
    background: a request to Sofa never waits on the site. A site that doesn't answer leaves the last list in place
    for a day, then an empty page that says so. Nothing is written to Activity about it by name.
  * Kept links (kept_links): the title, the picture's address, the site and the day, for one person. Not the video.
    Once a day Sofa asks the site which of them it has removed, and those go from the list (the site's terms ask for
    that). What was played and not kept is listed for 30 days, and not at all with "Keep no logs" on.
  * It all sits behind the Adult switch: never for visitors, guests, Kids profiles or a public Sofa (web.py).
"""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, net, store

PER_LIST = 25
FRESH = 30 * 60                   # a list is asked for again after this long
STALE = 24 * 3600                 # ... and shown this long when the site doesn't answer
CATS_FRESH = 12 * 3600
RETRY = 5 * 60                    # after a failure, not before this
PLAYED_DAYS = 30                  # what was played and not kept is forgotten after this
MAX_KEPT = 2000

PERIODS = (("week", "This week"), ("month", "This month"), ("all", "All time"), ("rated", "Best rated"))

SITES = {
    "eporner": {
        "name": "Eporner", "home": "https://www.eporner.com/", "host": "eporner.com",
        "api": "https://www.eporner.com/api/v2/", "terms": "https://www.eporner.com/api/v2/#terms",
        "order": {"week": "top-weekly", "month": "top-monthly", "all": "most-popular", "rated": "top-rated"},
        "embed": re.compile(r"^https://www\.eporner\.com/embed/([A-Za-z0-9]{6,20})/$"),
        "id": re.compile(r"^[A-Za-z0-9]{6,20}$"),
        # the site's category names we don't put on a page of Sofa's
        "skip": {"teens", "students", "uncategorized"},
        "save": False,            # the site offers no download to third parties: its terms forbid one
    },
}

_lock = threading.Lock()
_cache = {}                       # (site, kind, cat, period) -> {"at", "tried", "items" | "cats", "error"}
_asking = set()
_queue_lock = threading.Lock()    # one request at a time, to every site (the site's own rule)
fetch_json = None                 # tests put their own reader here: (url) -> the decoded reply


def on():
    """The sites switched on, in SITES' order. None on a public Sofa, whatever its settings say."""
    if config.demo_on():
        return []
    chosen = config.get("adult_sites") or []
    return [s for s in SITES if s in chosen]


def set_on(site, yes):
    if site not in SITES:
        raise ValueError("Sofa doesn't know that site.")
    chosen = [s for s in (config.get("adult_sites") or []) if s in SITES and s != site]
    config.update({"adult_sites": chosen + [site] if yes else chosen})
    if not yes:
        with _lock:
            for k in [k for k in _cache if k[0] == site]:
                del _cache[k]
    store.log("settings", "A site's top lists were switched %s for the Adult section" % ("on" if yes else "off"))


def summary():
    """For the settings: every site Sofa knows, and whether it's on."""
    chosen = on()
    return [{"id": k, "name": s["name"], "home": s["home"], "terms": s["terms"], "on": k in chosen} for k, s in SITES.items()]


def _get(url):
    if fetch_json:
        return fetch_json(url)
    req = urllib.request.Request(url, headers={"User-Agent": "Sofa", "Accept": "application/json"})
    # (one site's address: when its name can't be found, on a network that filters such sites say, that isn't "the
    # internet is down", and mustn't stop Sofa asking everyone else)
    with net.urlopen(req, timeout=12, whole_internet=False) as r:
        return json.loads(r.read(4 * 2**20).decode("utf-8", "replace"))


def _https(url, host):
    """`url` when it's an https address at `host` or under it; else None."""
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return None
    name = (parts.hostname or "").lower()
    if parts.scheme != "https" or not (name == host or name.endswith("." + host)) or parts.username or parts.port:
        return None
    return parts.geturl()


def _video(site, v):
    """One entry of a site's reply as Sofa keeps it, or None when it isn't what the site's API says it is (the
    player's address and the page's are the site's own, nowhere else)."""
    s = SITES[site]
    m = s["embed"].match(str(v.get("embed") or ""))
    page = _https(v.get("url"), s["host"])
    if not m or not page or m.group(1) != str(v.get("id") or ""):
        return None
    thumb = _https((v.get("default_thumb") or {}).get("src"), s["host"])
    try:
        length, views = int(v.get("length_sec") or 0), int(v.get("views") or 0)
    except (TypeError, ValueError):
        length, views = 0, 0
    quality = v.get("quality") if isinstance(v.get("quality"), dict) else {}
    return {"site": site, "id": m.group(1), "title": re.sub(r"\s+", " ", str(v.get("title") or "")).strip()[:200] or "Untitled",
            "length": max(0, length), "views": max(0, views), "rate": str(v.get("rate") or "")[:5],
            "added": str(v.get("added") or "")[:10], "embed": m.group(0), "url": page, "thumb": thumb,
            "quality": str(quality.get("max") or "")[:8]}


def _read(site, kind, cat, period):
    s = SITES[site]
    if kind == "cats":
        reply = _get(s["api"] + "categories/")
        cats = [{"slug": str(c.get("slug"))[:60], "name": str(c.get("name"))[:60]} for c in reply.get("categories") or []
                if isinstance(c, dict) and re.match(r"^[a-z0-9][a-z0-9-]{0,58}$", str(c.get("slug") or "")) and c.get("name")
                and c["slug"] not in s["skip"]]
        return {"cats": cats}
    words = next((c["name"] for c in (_cache.get((site, "cats", "", "")) or {}).get("cats") or [] if c["slug"] == cat), None)
    query = {"query": words or "all", "per_page": PER_LIST, "page": 1, "order": s["order"][period], "thumbs": "default",
             "thumbsize": "big", "fields": "quality", "format": "json"}
    reply = _get(s["api"] + "video/search/?" + urllib.parse.urlencode(query))
    items = [x for x in (_video(site, v) for v in (reply.get("videos") or [])[:PER_LIST] if isinstance(v, dict)) if x]
    return {"items": items}


def _work(key):
    site, kind, cat, period = key
    try:
        with _queue_lock:
            got = _read(site, kind, cat, period)
        got.update(at=time.time(), tried=time.time(), error=False)
        with _lock:
            _cache[key] = got
            for k in sorted(_cache, key=lambda k: _cache[k].get("tried", 0))[:-200]:     # (never more than 200 lists)
                del _cache[k]
    except Exception:                                       # the site is down, slow or says something else: quietly
        with _lock:
            had = _cache.get(key) or {}
            _cache[key] = dict(had, tried=time.time(), error=True)
    finally:
        with _lock:
            _asking.discard(key)


def _ask(key, fresh, wait=False):
    """What's kept for `key`, and a reading started in the background when it's old. Never waits (but `wait`: tests)."""
    now = time.time()
    with _lock:
        have = _cache.get(key)
        due = not have or (now - have.get("at", 0) > fresh and now - have.get("tried", 0) > (RETRY if have.get("error") else 0))
        start = due and key not in _asking
        if start:
            _asking.add(key)
    if start:
        t = threading.Thread(target=_work, args=(key,), daemon=True, name="adult-top")
        t.start()
        if wait:
            t.join(20)
            with _lock:
                have, start = _cache.get(key), False
    return have, bool(start or key in _asking)


def listing(site, cat="", period="week", wait=False):
    """{"state": "ready" | "reading" | "down", "items", "cats", "at"} for one list. `cat`: a category's slug, or ""
    for the whole site."""
    if site not in on():
        return None
    period = period if period in SITES[site]["order"] else "week"
    cats, _ = _ask((site, "cats", "", ""), CATS_FRESH, wait)
    names = (cats or {}).get("cats") or []
    if cat and not any(c["slug"] == cat for c in names):
        cat = "" if names else cat                          # (a category the site no longer has: the whole site)
        if not names:
            return {"state": "reading" if not cats or not cats.get("error") else "down", "items": [], "cats": [], "cat": cat,
                    "period": period}
    have, asking = _ask((site, "list", cat, period), FRESH, wait)
    now = time.time()
    items = (have or {}).get("items") if have and now - have.get("at", 0) < STALE else None
    state = "ready" if items is not None else "reading" if asking or not have else "down"
    return {"state": state, "items": items or [], "cats": names, "cat": cat, "period": period,
            "at": int(have["at"]) if have and have.get("at") else None, "old": bool(have and have.get("error") and items is not None)}


def find(site, vid):
    """A video Sofa has listed (so its addresses were checked as the site's own), by id; or None."""
    with _lock:
        for (s, kind, _c, _p), got in _cache.items():
            if s == site and kind == "list":
                for it in got.get("items") or []:
                    if it["id"] == vid:
                        return dict(it)
    return None


# ---------------------------------------------------------------- kept links

SCHEMA = """
CREATE TABLE IF NOT EXISTS kept_links (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, site TEXT NOT NULL, vid TEXT NOT NULL,
  title TEXT NOT NULL, thumb TEXT, url TEXT NOT NULL, embed TEXT NOT NULL, length INTEGER NOT NULL DEFAULT 0,
  kept INTEGER NOT NULL DEFAULT 0, at INTEGER NOT NULL, PRIMARY KEY (user_id, site, vid));
"""
_made = [None]


def _table():
    if _made[0] != config.DATA_DIR:
        store.db().executescript(SCHEMA)
        _made[0] = config.DATA_DIR


def _row(r):
    return {"site": r["site"], "id": r["vid"], "title": r["title"], "thumb": r["thumb"], "url": r["url"], "embed": r["embed"],
            "length": r["length"], "kept": bool(r["kept"]), "at": r["at"], "site_name": (SITES.get(r["site"]) or {}).get("name")}


def note(user_id, site, vid, keep=None):
    """Someone played a listed video (keep None), or keeps it or lets it go (True, False). Only a video Sofa listed,
    or one already in this person's list, can be noted: the addresses kept are the ones Sofa checked."""
    _table()
    if site not in SITES or not SITES[site]["id"].match(str(vid or "")):
        return None
    have = store.q1("SELECT * FROM kept_links WHERE user_id = ? AND site = ? AND vid = ?", user_id, site, vid)
    if keep is False:
        if have:                                            # (still in "played lately" until that runs out)
            store.ex("UPDATE kept_links SET kept = 0 WHERE user_id = ? AND site = ? AND vid = ?", user_id, site, vid)
        return _row(dict(have, kept=0)) if have else None
    it = find(site, vid) if site in on() else None
    if not it and not have:
        return None
    if keep is None and store.no_logs():                    # "Keep no logs": what was played isn't written down
        return _row(have) if have else dict(it, kept=False, at=0)
    now = int(time.time())
    if have:
        store.ex("UPDATE kept_links SET kept = ?, at = ? WHERE user_id = ? AND site = ? AND vid = ?",
                 1 if keep or have["kept"] else 0, now if keep and not have["kept"] else have["at"], user_id, site, vid)
    else:
        if keep and store.q1("SELECT COUNT(*) AS n FROM kept_links WHERE user_id = ? AND kept = 1", user_id)["n"] >= MAX_KEPT:
            raise ValueError("That's %d kept already. Let some go first." % MAX_KEPT)
        store.ex("INSERT INTO kept_links (user_id, site, vid, title, thumb, url, embed, length, kept, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 user_id, site, vid, it["title"], it["thumb"], it["url"], it["embed"], it["length"], 1 if keep else 0, now)
    return _row(store.q1("SELECT * FROM kept_links WHERE user_id = ? AND site = ? AND vid = ?", user_id, site, vid))


def kept(user_id):
    """This person's kept links, newest first, then what they played lately and didn't keep. Only of sites still on."""
    _table()
    live = on()
    store.ex("DELETE FROM kept_links WHERE kept = 0 AND at < ?", int(time.time()) - PLAYED_DAYS * 86400)
    rows = [_row(r) for r in store.q("SELECT * FROM kept_links WHERE user_id = ? ORDER BY at DESC", user_id) if r["site"] in live]
    return {"kept": [r for r in rows if r["kept"]], "played": [r for r in rows if not r["kept"]][:100]}


def one(user_id, site, vid):
    """A video to play: from a list, or from this person's kept links."""
    if site not in on():
        return None
    it = find(site, vid)
    if it:
        return it
    _table()
    r = store.q1("SELECT * FROM kept_links WHERE user_id = ? AND site = ? AND vid = ?", user_id, site, vid)
    return _row(r) if r else None


def drop_removed():
    """Once a day: ask each site that's on which of the links people keep it has removed, and let those go (the
    site's terms: what it removes leaves here too). A site that doesn't answer removes nothing."""
    _table()
    gone = 0
    for site in on():
        ids = [r["vid"] for r in store.q("SELECT DISTINCT vid FROM kept_links WHERE site = ?", site)]
        for n in range(0, len(ids), 100):
            try:
                with _queue_lock:
                    reply = _get(SITES[site]["api"] + "video/status/?" + urllib.parse.urlencode({"id": ",".join(ids[n:n + 100])}))
            except Exception:
                break
            for v in reply.get("videos") or []:
                if isinstance(v, dict) and v.get("status") in ("removed", "unknown") and v.get("id") in ids:
                    store.ex("DELETE FROM kept_links WHERE site = ? AND vid = ?", site, v["id"])
                    gone += 1
    return gone


def _loop():
    time.sleep(600)
    while True:
        try:
            if on():
                drop_removed()
        except Exception:
            pass
        time.sleep(86400)


def start():
    threading.Thread(target=_loop, daemon=True, name="adult-top-removals").start()
