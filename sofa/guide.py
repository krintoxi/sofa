"""The guide: what's on each channel, and when, from XMLTV.

XMLTV is the format guide data comes in everywhere: a file or an address that lists channels (`<channel id=...>`
with their names) and programmes (`<programme start=... stop=... channel=...>` with a title, an episode's title,
a description, a season and episode, a year). A household gives Sofa its own (Server → Live TV → Guide: an
address or a file, config "guide_sources"); Sofa reads it a few times a day and keeps the next two weeks.

A source's channels are matched to Live TV's by what they have in common: the id a channel list gave (`tvg-id`),
a tuner's channel number ("5.1") among the source's names for a channel, or the channel's name itself.

The guide is for the household: it isn't given to the public library's Visitors.
"""
import datetime
import io
import os
import re
import threading
import time
import xml.etree.ElementTree as ET

from . import config, store

REFRESH_EVERY = 6 * 3600
KEEP_DAYS = 14
MAX_BYTES = 96 * 2**20
_lock = threading.Lock()
_state = {"at": 0, "sources": {}}


def _table():
    store.ex("""CREATE TABLE IF NOT EXISTS guide (
        channel TEXT NOT NULL, start INTEGER NOT NULL, stop INTEGER NOT NULL, title TEXT NOT NULL, sub TEXT, about TEXT,
        season INTEGER, episode INTEGER, year INTEGER, movie INTEGER NOT NULL DEFAULT 0, fresh INTEGER NOT NULL DEFAULT 0)""")
    store.ex("CREATE INDEX IF NOT EXISTS guide_when ON guide (channel, start)")


def sources():
    return [dict(s) for s in config.get("guide_sources") or []]


def when(stamp):
    """XMLTV's time ("20261113183000 -0500", "202611131830") as seconds since 1970, or None."""
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})?\s*([+-]\d{4})?", (stamp or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, s, zone = m.groups()
    try:
        t = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0), tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    if zone:
        t -= datetime.timedelta(hours=int(zone[1:3]), minutes=int(zone[3:5])) * (1 if zone[0] == "+" else -1)
    return int(t.timestamp())


def episode_of(numbers):
    """(season, episode) from a programme's `<episode-num>` lines: xmltv_ns ("2.6.0/1": the third season's seventh,
    counted from nothing) or what's printed on screen ("S03E07")."""
    for system, text in numbers:
        text = (text or "").strip()
        if system == "xmltv_ns":
            parts = [p.split("/")[0].strip() for p in text.split(".")]
            if len(parts) >= 2 and parts[1].isdigit():
                return (int(parts[0]) + 1 if parts[0].isdigit() else None), int(parts[1]) + 1
        m = re.search(r"S(\d{1,4})\s*E(\d{1,4})", text, re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def parse(data):
    """({xmltv channel id: [its names]}, [programme, ...]) from an XMLTV document (bytes). A document that declares
    entities of its own is refused: they're how a small file is made to fill a computer's memory."""
    if len(data) > MAX_BYTES:
        raise ValueError("that guide is too big (%d MB)" % (len(data) // 2**20))
    if b"<!ENTITY" in data[:1 << 16]:
        raise ValueError("that guide declares entities of its own, which Sofa doesn't read")
    names, shows = {}, []
    for _event, el in ET.iterparse(io.BytesIO(data), events=("end",)):
        if el.tag == "channel":
            names[el.get("id") or ""] = [(n.text or "").strip() for n in el.findall("display-name") if (n.text or "").strip()]
            el.clear()
        elif el.tag == "programme":
            start, stop, title = when(el.get("start")), when(el.get("stop")), (el.findtext("title") or "").strip()
            if start and stop and stop > start and title:
                season, episode = episode_of([(n.get("system") or "", n.text) for n in el.findall("episode-num")])
                kinds = " ".join((c.text or "").lower() for c in el.findall("category"))
                year = re.match(r"\d{4}", (el.findtext("date") or "").strip())
                shows.append({"channel": el.get("channel") or "", "start": start, "stop": stop, "title": title[:200],
                              "sub": (el.findtext("sub-title") or "").strip()[:200] or None,
                              "about": (el.findtext("desc") or "").strip()[:1200] or None, "season": season, "episode": episode,
                              "year": int(year.group(0)) if year else None,
                              "movie": bool(re.search(r"\bmovie\b|\bfilm\b", kinds)) and episode is None,
                              "fresh": el.find("new") is not None or (el.find("previously-shown") is None and el.find("premiere") is not None)})
            el.clear()
    return names, shows


def _plain(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def match(names, channels):
    """{xmltv channel id: Sofa channel id}: by the id a channel list gave, a tuner's number, or the name."""
    by_tvg, by_number, by_name = {}, {}, {}
    for c in channels:
        if c.get("tvg"):
            by_tvg.setdefault(c["tvg"], c["id"])
        if c.get("guide_number"):
            by_number.setdefault(c["guide_number"], c["id"])
        by_name.setdefault(_plain(c.get("name")), c["id"])
    out = {}
    for xid, shown in names.items():
        got = by_tvg.get(xid)
        for n in shown:
            got = got or by_number.get(n) or by_number.get(n.split(" ")[0])
        for n in shown + [xid]:
            got = got or by_name.get(_plain(n))
        if got:
            out[xid] = got
    return out


def _read(source):
    from . import live
    where = source.get("url") or source.get("path") or ""
    if where.startswith(("http://", "https://")):
        with live.fetch(where, timeout=60) as r:          # (on the internet: not in offline mode; at home: always)
            data = r.read(MAX_BYTES + 1)
    else:
        with open(os.path.expanduser(where), "rb") as f:
            data = f.read(MAX_BYTES + 1)
    if data[:2] == b"\x1f\x8b":                      # (guides are often gzipped)
        import gzip
        data = gzip.decompress(data)
    return data


def refresh(force=False):
    """Read the household's guide sources again (every few hours, or now) and keep the next two weeks."""
    from . import live
    if not sources():
        return 0
    with _lock:
        if not force and time.time() - _state["at"] < REFRESH_EVERY:
            return None
        _state["at"] = time.time()
    _table()
    chans = live.all_channels(adult=True)
    now, total = int(time.time()), 0
    rows = []
    for s in sources():
        where = s.get("url") or s.get("path") or ""
        try:
            names, shows = parse(_read(s))
            to = match(names, chans)
            mine = [p for p in shows if p["channel"] in to and p["stop"] > now - 3600 and p["start"] < now + KEEP_DAYS * 86400]
            rows += [(to[p["channel"]], p["start"], p["stop"], p["title"], p["sub"], p["about"], p["season"], p["episode"],
                      p["year"], int(p["movie"]), int(p["fresh"])) for p in mine]
            _state["sources"][where] = {"channels": len(to), "of": len(names), "programmes": len(mine), "at": now, "error": None}
            total += len(mine)
        except Exception as exc:
            _state["sources"][where] = {"channels": 0, "of": 0, "programmes": 0, "at": now, "error": str(exc)[:200]}
            store.log("live", "Couldn't read the guide at %s: %s" % (where[:80], str(exc)[:160]))
    if rows:
        db = store.db()
        with db:
            db.execute("DELETE FROM guide")
            db.executemany("INSERT INTO guide (channel, start, stop, title, sub, about, season, episode, year, movie, fresh) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return total


def on(channel_id, start=None, stop=None):
    """What a channel shows between two times (now and six hours on, unless given), in order."""
    _table()
    start = int(start if start is not None else time.time())
    stop = int(stop if stop is not None else start + 6 * 3600)
    return [dict(r) for r in store.q("SELECT * FROM guide WHERE channel = ? AND stop > ? AND start < ? ORDER BY start",
                                     channel_id, start, stop)]


def at(channel_id, moment=None):
    """The programme on a channel at a moment (now), or None."""
    moment = int(moment if moment is not None else time.time())
    _table()
    r = store.q1("SELECT * FROM guide WHERE channel = ? AND start <= ? AND stop > ? ORDER BY start DESC LIMIT 1", channel_id, moment, moment)
    return dict(r) if r else None


def showings(title, channel_id=None, after=None):
    """Every time a title is on from now (on one channel, or any), for a series to be recorded from."""
    _table()
    after = int(after if after is not None else time.time())
    sql, args = "SELECT * FROM guide WHERE title = ? COLLATE NOCASE AND stop > ?", [title, after]
    if channel_id:
        sql += " AND channel = ?"
        args.append(channel_id)
    return [dict(r) for r in store.q(sql + " ORDER BY start", *args)]


def status():
    return {"sources": [dict(_state["sources"].get(s.get("url") or s.get("path") or "", {}), where=s.get("url") or s.get("path"))
                        for s in sources()], "updated": _state["at"] or None}
