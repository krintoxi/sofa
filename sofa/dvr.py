"""Recording TV: from the household's own tuners, into the household's own library.

What can be recorded: a channel at home, which means a tuner's (sofa/tuners.py) or a channel list kept on the home
network. Never a channel list from the internet, never Classic Cinema or the Retro TV decades (those aren't Live TV
channels at all: sofa/archive.py), never for the public library: a recording is the household's.

Three ways to ask:

- **Now:** what's on a channel, from now to the end of the programme the guide shows (an hour when there's no guide).
- **A programme:** one showing from the guide (or a channel and two times).
- **A series:** every showing of a title the guide lists, on one channel or any; new episodes only if asked; the last
  N kept. A repeat of an episode already recorded (the same season and episode) isn't recorded again.

Before and after each one, a little more is recorded (padding: a minute before, three after, unless set otherwise),
because programmes rarely start and end on the minute. Padding gives way: it never makes two recordings clash. A tuner
box has a number of tuners; the programmes planned on it never ask for more at once than that (plan(), by their own
times): the first asked for keeps its tuner, one-offs before a series', and the rest wait as "conflicts" (with what
they clash with) until a tuner is free for them. When a recording is due and every tuner is taken, one that's only
recording its extra minutes after the end stops there; a recording's minutes before its start wait for a tuner. A
tuner someone is watching on is a tuner taken too (tuners.busy).

A recording is the channel's own stream, copied as it comes (ffmpeg -c copy, MPEG-TS): no conversion, no loss, little
work for the computer. If the stream breaks off, Sofa opens it again and joins the parts. When it's done, the file goes
into the Inbox under a name the Inbox reads like any other ("Night Court S03E07 Tonight.ts", "The News Hour
2026-11-13.ts", "Casablanca (1942).ts"), and the Inbox files it with its artwork and details as it files everything
(sofa/organizer.py tells this module where it went: filed()). Keep-last-N then puts older episodes of a series in
Deleted, where they stay until someone empties it.
"""
import os
import re
import shutil
import subprocess
import threading
import time

from . import config, fileops, guide, naming, store, tuners

TICK = 15
EXPAND_EVERY = 600
RESTARTS = 3                     # a stream that breaks off is opened again this many times
_lock = threading.Lock()
_procs = {}                      # recording id -> {"proc", "part", "parts", "restarts"}
_state = {"expanded": 0}
_recorded = {"version": -1, "paths": set()}
_version = [0]


def _table():
    store.ex("""CREATE TABLE IF NOT EXISTS recordings (
        id INTEGER PRIMARY KEY, channel TEXT NOT NULL, channel_name TEXT, tuner TEXT, title TEXT NOT NULL, sub TEXT,
        about TEXT, season INTEGER, episode INTEGER, year INTEGER, movie INTEGER NOT NULL DEFAULT 0,
        start INTEGER NOT NULL, stop INTEGER NOT NULL, before INTEGER NOT NULL, after INTEGER NOT NULL, rule INTEGER,
        state TEXT NOT NULL, why TEXT, inbox TEXT, path TEXT, size INTEGER, user_id INTEGER, created INTEGER NOT NULL)""")
    store.ex("""CREATE TABLE IF NOT EXISTS recording_rules (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, channel TEXT, new_only INTEGER NOT NULL DEFAULT 0,
        keep INTEGER NOT NULL DEFAULT 0, before INTEGER, after INTEGER, user_id INTEGER, created INTEGER NOT NULL)""")


def folder():
    return os.path.join(config.DATA_DIR, "recordings")


def pads():
    """(seconds before, seconds after) by default: the settings are in minutes."""
    return (int(float(config.get("dvr_pad_before") or 0) * 60), int(float(config.get("dvr_pad_after") or 0) * 60))


# ---------------------------------------------------------------- what can be recorded

def recordable(chan):
    """Why a channel can't be recorded, or None when it can: a channel at home (a tuner's, or a list on the home
    network), never one from the internet."""
    if not chan:
        return "There's no such channel."
    if not chan.get("home"):
        return "Only channels at home can be recorded: a tuner's, or a channel list on your own network."
    return None


def _channel(cid):
    from . import live
    return live.channel(cid)


def _changed():
    _version[0] += 1


# ---------------------------------------------------------------- asking

def _insert(chan, start, stop, title, user=None, rule=None, show=None, before=None, after=None):
    _table()
    b, a = pads()
    show = show or {}
    rid = store.ex("""INSERT INTO recordings (channel, channel_name, tuner, title, sub, about, season, episode, year, movie,
                      start, stop, before, after, rule, state, user_id, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   chan["id"], chan.get("name"), chan.get("tuner"), title[:200], show.get("sub"), show.get("about"),
                   show.get("season"), show.get("episode"), show.get("year"), int(bool(show.get("movie"))), int(start), int(stop),
                   b if before is None else int(before), a if after is None else int(after), rule, "scheduled",
                   (user or {}).get("id"), int(time.time())).lastrowid
    _changed()
    return rid


def record(channel_id, start, stop, title=None, user=None, before=None, after=None):
    """One recording, by channel and times."""
    chan = _channel(channel_id)
    why = recordable(chan)
    if why:
        raise ValueError(why)
    if stop <= start or stop - start > 12 * 3600:
        raise ValueError("A recording is from one time to a later one, twelve hours at most.")
    if stop < time.time():
        raise ValueError("That has already been on.")
    show = guide.at(channel_id, start + 1) or {}
    if show and abs(show["start"] - start) > 300:
        show = {}                                   # (the times don't match a programme: it's the household's own slot)
    rid = _insert(chan, start, stop, title or show.get("title") or chan["name"], user, show=show, before=before, after=after)
    plan()
    return get(rid)


def record_now(channel_id, user=None):
    """What's on a channel, from now to the end of the programme (an hour without a guide)."""
    chan = _channel(channel_id)
    why = recordable(chan)
    if why:
        raise ValueError(why)
    now = int(time.time())
    show = guide.at(channel_id, now) or {}
    stop = show.get("stop") or now + 3600
    rid = _insert(chan, now, stop, show.get("title") or chan["name"], user, show=show, before=0)
    plan()
    return get(rid)


def record_programme(channel_id, start, user=None):
    """One showing from the guide."""
    show = next((p for p in guide.on(channel_id, start - 60, start + 60) if p["start"] == int(start)), None)
    if not show:
        raise ValueError("The guide has nothing starting then on that channel.")
    chan = _channel(channel_id)
    why = recordable(chan)
    if why:
        raise ValueError(why)
    if _existing(channel_id, show["start"]):
        raise ValueError("That's being recorded already.")
    rid = _insert(chan, show["start"], show["stop"], show["title"], user, show=show)
    plan()
    return get(rid)


def add_rule(title, channel_id=None, new_only=False, keep=0, user=None):
    """A series: every showing of `title` (on one channel, or any channel at home)."""
    _table()
    title = (title or "").strip()
    if not title:
        raise ValueError("Which programme?")
    if channel_id:
        why = recordable(_channel(channel_id))
        if why:
            raise ValueError(why)
    rid = store.ex("INSERT INTO recording_rules (title, channel, new_only, keep, user_id, created) VALUES (?,?,?,?,?,?)",
                   title[:200], channel_id or None, int(bool(new_only)), max(0, int(keep or 0)), (user or {}).get("id"), int(time.time())).lastrowid
    expand(force=True)
    return dict(store.q1("SELECT * FROM recording_rules WHERE id = ?", rid))


def remove_rule(rule_id):
    """A series stops: what it planned and hasn't started is cancelled; what it recorded stays."""
    _table()
    store.ex("UPDATE recordings SET state = 'cancelled' WHERE rule = ? AND state IN ('scheduled', 'conflict')", rule_id)
    store.ex("DELETE FROM recording_rules WHERE id = ?", rule_id)
    _changed()
    plan()


def cancel(recording_id):
    """A planned recording is cancelled; one under way stops, and what it has is kept and filed."""
    _table()
    row = get(recording_id)
    if not row:
        raise ValueError("There's no such recording.")
    if row["state"] == "recording":
        with _lock:
            p = _procs.get(recording_id)
        store.ex("UPDATE recordings SET stop = ? WHERE id = ?", int(time.time()) - row["after"] - 1, recording_id)
        if p:
            p["stopping"] = True
            p["proc"].terminate()
    elif row["state"] in ("scheduled", "conflict"):
        store.ex("UPDATE recordings SET state = 'cancelled' WHERE id = ?", recording_id)
    _changed()
    plan()
    return get(recording_id)


def _existing(channel_id, start):
    return store.q1("SELECT id FROM recordings WHERE channel = ? AND start = ? AND state NOT IN ('cancelled', 'failed')",
                    channel_id, int(start))


def expand(force=False, now=None):
    """Plan what the series ask for, from the guide: each showing not already planned, new ones only where asked, and
    never an episode (season and episode) that's planned or recorded already."""
    _table()
    now = int(now or time.time())
    if not force and now - _state["expanded"] < EXPAND_EVERY:
        return 0
    _state["expanded"] = now
    added = 0
    for rule in store.q("SELECT * FROM recording_rules"):
        for show in guide.showings(rule["title"], rule["channel"], now):
            chan = _channel(show["channel"])
            if recordable(chan) or _existing(show["channel"], show["start"]):
                continue
            if rule["new_only"] and not show["fresh"]:
                continue
            if show["season"] is not None and show["episode"] is not None and store.q1(
                    """SELECT id FROM recordings WHERE title = ? COLLATE NOCASE AND season = ? AND episode = ?
                       AND state IN ('scheduled', 'conflict', 'recording', 'done', 'filed')""",
                    show["title"], show["season"], show["episode"]):
                continue
            _insert(chan, show["start"], show["stop"], show["title"], {"id": rule["user_id"]}, rule=rule["id"], show=show,
                    before=rule["before"], after=rule["after"])
            added += 1
    if added:
        plan()
    return added


# ---------------------------------------------------------------- tuners for each

def _window(r):
    """From the extra minutes before to the extra minutes after."""
    return r["start"] - r["before"], r["stop"] + r["after"]


def _core(r):
    """The programme itself: what tuners are planned by (padding gives way)."""
    return r["start"], r["stop"]


def _most_at_once(rows, start, stop):
    """How many of `rows` (already given a tuner) overlap one another at the busiest moment within start..stop."""
    edges = []
    for r in rows:
        a, b = _core(r)
        a, b = max(a, start), min(b, stop)
        if a < b:
            edges += [(a, 1), (b, -1)]
    most = n = 0
    for _t, d in sorted(edges, key=lambda e: (e[0], e[1])):
        n += d
        most = max(most, n)
    return most


def plan(now=None):
    """Give each planned recording a tuner, box by box: what's recording keeps its tuner, then one-offs, then a
    series', each in the order it was asked for. One that would need more tuners than its box has waits as a
    "conflict", saying what it clashes with. Returns the conflicts."""
    _table()
    now = int(now or time.time())
    rows = [dict(r) for r in store.q("SELECT * FROM recordings WHERE state IN ('scheduled', 'conflict', 'recording')")]
    conflicts = []
    for device in {r["tuner"] for r in rows if r["tuner"]}:
        dev = tuners.device(device)
        count = int((dev or {}).get("tuners") or 0)
        mine = sorted((r for r in rows if r["tuner"] == device and _window(r)[1] > now),
                      key=lambda r: (r["state"] != "recording", r["rule"] is not None, r["created"], r["id"]))
        given = []
        for r in mine:
            a, b = _core(r)
            if r["state"] == "recording" or _most_at_once(given, a, b) < count:
                given.append(r)
                if r["state"] == "conflict":
                    store.ex("UPDATE recordings SET state = 'scheduled', why = NULL WHERE id = ?", r["id"])
                continue
            clash = [g["title"] for g in given if _core(g)[0] < b and _core(g)[1] > a]
            why = ("%s has %d tuner%s, and they're taken then by %s." % ((dev or {}).get("name") or "The tuner", count,
                   "" if count == 1 else "s", ", ".join(clash) or "other recordings")) if dev else "That tuner isn't on this Sofa any more."
            store.ex("UPDATE recordings SET state = 'conflict', why = ? WHERE id = ?", why, r["id"])
            conflicts.append(dict(r, state="conflict", why=why))
    return conflicts


# ---------------------------------------------------------------- recording

def file_name(r):
    """What the Inbox will read: "Show S03E07 Title", "Show 2026-11-13", "Film (1942)", "Film"."""
    title = naming.safe_filename(r["title"]) or "Recording"
    if r["movie"]:
        return "%s (%d)" % (title, r["year"]) if r["year"] else title
    if r["season"] is not None and r["episode"] is not None:
        sub = naming.safe_filename(r["sub"] or "")
        return ("%s S%02dE%02d %s" % (title, r["season"], r["episode"], sub)).strip()
    return "%s %s" % (title, time.strftime("%Y-%m-%d", time.localtime(r["start"])))


def _command(url, seconds, out):
    from . import media
    return [media.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", url,
            "-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-c", "copy", "-t", "%d" % max(1, seconds), "-f", "mpegts", out]


def _begin(r, now):
    """Open the channel and start copying it, to the end of the window."""
    from . import media
    chan = _channel(r["channel"])
    if recordable(chan):
        return _fail(r, "The channel isn't there any more.")
    if not media.tool("ffmpeg"):
        return _fail(r, "Recording needs ffmpeg on this computer.")
    if r["tuner"] and r["state"] != "recording" and tuners.free(r["tuner"]) <= 0:   # (opened again: it has its tuner)
        freed = _end_padding(r["tuner"], now)       # one only recording its extra minutes gives its tuner up
        if not freed:
            if now < r["start"]:
                return None                         # (its own extra minutes before: they wait for a tuner)
            return _fail(r, "Every tuner was in use when it began (someone watching, or another recording).")
    os.makedirs(folder(), exist_ok=True)
    with _lock:
        p = _procs.setdefault(r["id"], {"parts": [], "restarts": 0})
    part = os.path.join(folder(), "%d-%d.ts" % (r["id"], len(p["parts"]) + 1))
    p["parts"].append(part)
    p["asked"] = max(1, _window(r)[1] - now)
    p["proc"] = subprocess.Popen(_command(chan["url"], p["asked"], part), stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
    if r["state"] != "recording":
        store.ex("UPDATE recordings SET state = 'recording', why = NULL WHERE id = ?", r["id"])
        store.log("live", "Recording %s on %s" % (r["title"], r["channel_name"] or "a channel"))
        _changed()
    return True


def _end_padding(device, now):
    """Stop the recordings on this tuner box that are past their programme's end (in their extra minutes). How many."""
    n = 0
    with _lock:
        running = list(_procs.items())
    for rid, p in running:
        r = get(rid)
        if r and r["tuner"] == device and r["stop"] <= now and p["proc"].poll() is None and not p.get("stopping"):
            p["stopping"] = True
            p["proc"].terminate()
            try:
                p["proc"].wait(5)
            except subprocess.TimeoutExpired:
                p["proc"].kill()
            n += 1
    return n


def _fail(r, why):
    store.ex("UPDATE recordings SET state = 'failed', why = ? WHERE id = ?", why[:300], r["id"])
    store.log("live", "Couldn't record %s: %s" % (r["title"], why[:200]))
    _changed()
    return False


def _whole(p):
    """The part just made has all the time it was asked for (the copy ended because it was done, not cut off)."""
    from . import media
    part = p["parts"][-1]
    if not os.path.exists(part) or not os.path.getsize(part):
        return False
    got = (media.probe(part) or {}).get("duration") or 0
    return got >= p["asked"] - 3


def _join(parts, out):
    """The parts of a recording one after another, as one file (MPEG-TS joins as it is)."""
    parts = [p for p in parts if os.path.exists(p) and os.path.getsize(p) > 0]
    if len(parts) == 1:
        os.replace(parts[0], out)
        return
    with open(out, "wb") as f:
        for p in parts:
            with open(p, "rb") as src:
                shutil.copyfileobj(src, f, 1 << 20)


def _finish(r, p):
    """The copy is done: the parts joined, the file into the Inbox under the name the Inbox reads."""
    made = [x for x in p["parts"] if os.path.exists(x) and os.path.getsize(x) > 0]
    if not made:
        for x in p["parts"]:
            if os.path.exists(x):
                os.remove(x)
        return _fail(r, "Nothing came from the channel.")
    joined = os.path.join(folder(), "%d.ts" % r["id"])
    _join(made, joined)
    for x in p["parts"]:
        if os.path.exists(x) and x != joined:
            os.remove(x)
    inbox = config.path("inbox")
    os.makedirs(inbox, exist_ok=True)
    name = file_name(r) + ".ts"
    dest = os.path.join(inbox, name)
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(inbox, "%s (%d).ts" % (file_name(r), n))
        n += 1
    size = os.path.getsize(joined)
    fileops.move(joined, dest)
    store.ex("UPDATE recordings SET state = 'done', inbox = ?, size = ?, why = ? WHERE id = ?", os.path.basename(dest), size,
             ("The stream broke off and was opened again %d time%s." % (p["restarts"], "" if p["restarts"] == 1 else "s"))
             if p["restarts"] else None, r["id"])
    store.log("live", "Recorded %s (%.1f GB): in the Inbox to be filed" % (r["title"], size / 1e9))
    _changed()
    return True


def tick(now=None):
    """Once every few seconds: plan the series, follow what's running, give out tuners, begin what's due. What's
    running is followed first, so a recording that has just ended gives its tuner back before the next one asks."""
    _table()
    now = int(now or time.time())
    expand(now=now)
    _follow(now)
    plan(now)
    for r in [dict(x) for x in store.q("SELECT * FROM recordings WHERE state = 'scheduled' ORDER BY start")]:
        a, _b = _window(r)
        if r["stop"] <= now:
            _fail(r, "Sofa wasn't running when it was on.")
        elif a <= now:
            _begin(r, now)
    keep_last()


def _follow(now):
    """The copies running: one that broke off is opened again (on the tuner it had), one that's done is finished."""
    with _lock:
        running = list(_procs.items())
    for rid, p in running:
        if p["proc"].poll() is None:
            continue
        r = get(rid)
        if not r:
            with _lock:
                _procs.pop(rid, None)
            continue
        left = _window(r)[1] - now
        if left > 20 and not p.get("stopping") and p["restarts"] < RESTARTS and not _whole(p):
            p["restarts"] += 1                       # the stream broke off: once more, into the next part
            store.log("live", "The recording of %s broke off; opening the channel again" % r["title"])
            _begin(r, now)
            continue
        with _lock:
            _procs.pop(rid, None)
        _finish(r, p)


def keep_last():
    """A series that keeps its last N: the older ones it recorded go to Deleted (which someone empties when sure)."""
    from . import organizer
    for rule in store.q("SELECT id, keep FROM recording_rules WHERE keep > 0"):
        old = store.q("SELECT * FROM recordings WHERE rule = ? AND state = 'filed' ORDER BY start DESC LIMIT -1 OFFSET ?",
                      rule["id"], rule["keep"])
        for r in old:
            if r["path"] and os.path.exists(r["path"]):
                organizer._put_aside(r["path"])
            store.ex("UPDATE recordings SET state = 'deleted' WHERE id = ?", r["id"])
            store.log("live", "Kept the last %d of %s: %s went to Deleted" % (rule["keep"], r["title"], os.path.basename(r["path"] or "")))
            _changed()


def filed(src, dest):
    """The Inbox moved `src` to `dest` (sofa/organizer.py). If it was a recording, remember where it is now."""
    if os.path.dirname(os.path.abspath(src)) != os.path.abspath(config.path("inbox")):
        return
    try:
        _table()
        row = store.q1("SELECT id FROM recordings WHERE inbox = ? AND state = 'done'", os.path.basename(src))
    except Exception:
        return
    if row:
        store.ex("UPDATE recordings SET state = 'filed', path = ? WHERE id = ?", dest, row["id"])
        _changed()


def recorded_paths():
    """Where the recordings are in the library: never shown to the public library's Visitors."""
    if _recorded["version"] != _version[0]:
        _table()
        _recorded["paths"] = {os.path.abspath(r["path"]) for r in store.q("SELECT path FROM recordings WHERE path IS NOT NULL")}
        _recorded["version"] = _version[0]
    return _recorded["paths"]


def is_recording(path):
    return bool(path) and os.path.abspath(path) in recorded_paths()


# ---------------------------------------------------------------- for people

def get(recording_id):
    _table()
    r = store.q1("SELECT * FROM recordings WHERE id = ?", recording_id)
    return dict(r) if r else None


def recording_now():
    _table()
    return [dict(r) for r in store.q("SELECT * FROM recordings WHERE state = 'recording'")]


def listing():
    """For Live TV → Recordings: what's coming (conflicts first), what's recording, what's done, and the series."""
    _table()
    rows = [dict(r) for r in store.q("SELECT * FROM recordings WHERE state != 'cancelled' ORDER BY start DESC LIMIT 400")]
    for r in rows:
        r.pop("path", None)                          # (where it is in the library is the library's business)
    return {"recordings": rows, "rules": [dict(r) for r in store.q("SELECT * FROM recording_rules ORDER BY title")],
            "pad": dict(zip(("before", "after"), pads()))}


def _loop():
    while True:
        try:
            if config.get("tuners") or store.q1("SELECT 1 FROM recordings WHERE state IN ('scheduled', 'recording') LIMIT 1"):
                tick()
        except Exception as exc:
            store.log("error", "Recording: %s" % exc)
        time.sleep(TICK)


def start():
    _table()
    # what was recording when Sofa stopped: its parts are kept; it's marked so nobody waits for it
    for r in store.q("SELECT id, title FROM recordings WHERE state = 'recording'"):
        store.ex("UPDATE recordings SET state = 'failed', why = ? WHERE id = ?", "Sofa stopped while it was recording.", r["id"])
    threading.Thread(target=_loop, daemon=True, name="dvr").start()
