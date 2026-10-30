"""Finding intros, recaps and end credits, so the player can offer "Skip Intro".

Two ways, best first:

1. Chapters. Many MKV files name them ("Intro", "Opening", "Recap", "Credits").
2. Listening. Episodes of a season share the same theme song and the same
   credits music. Sofa takes an audio fingerprint of the first ten minutes and
   the last five of neighbouring episodes and looks for a long stretch that
   sounds the same in both. A 15 to 150 second match near the start is the intro;
   a match near the end is the credits.

Fingerprints come from ffmpeg's Chromaprint muxer when this ffmpeg has it, else
from a small pure-Python fingerprint (energy, brightness and noisiness, compared
over time), which works the same way, just a little less sharply.

Results are kept in the database, so each season is listened to once. An admin
can clear a wrong marker from the player.
"""
import collections
import hashlib
import math
import re
import subprocess
import threading
import time
from array import array

from . import config, media, store

INTRO_WINDOW = 600          # seconds at the start of an episode to look in
CREDITS_WINDOW = 300        # seconds at the end
MIN_INTRO, MAX_INTRO = 15, 150
MIN_CREDITS = 15
CHAPTER_KINDS = [("recap", re.compile(r"\b(recap|previously)\b", re.I)),
                 ("intro", re.compile(r"\b(intro|opening|op|title sequence|main titles?)\b", re.I)),
                 ("credits", re.compile(r"\b(credits|ending|ed|outro|end titles?)\b", re.I))]
_wake = threading.Event()
_urgent = []                 # seasons someone is watching right now: these go first
_state = {"working": None}


def _table():
    store.ex("""CREATE TABLE IF NOT EXISTS markers (
        item TEXT NOT NULL, kind TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL, source TEXT,
        PRIMARY KEY (item, kind))""")
    store.ex("CREATE TABLE IF NOT EXISTS marker_scans (season TEXT PRIMARY KEY, signature TEXT, at INTEGER)")


def markers(item_id):
    _table()
    return [{"kind": r["kind"], "start": r["start"], "end": r["end"], "source": r["source"]}
            for r in store.q("SELECT * FROM markers WHERE item = ? ORDER BY start", item_id)]


def set_marker(item_id, kind, start, end, source):
    _table()
    store.ex("INSERT OR REPLACE INTO markers (item, kind, start, end, source) VALUES (?,?,?,?,?)",
             item_id, kind, round(start, 2), round(end, 2), source)


def clear_marker(item_id, kind):
    """An admin said this marker is wrong: forget it, and don't find it again by listening."""
    _table()
    store.ex("INSERT OR REPLACE INTO markers (item, kind, start, end, source) VALUES (?,?,0,0,'cleared')", item_id, kind)


def for_player(item_id):
    return [m for m in markers(item_id) if m["source"] != "cleared" and m["end"] > m["start"]]


# ---------------------------------------------------------------- chapters

def from_chapters(item, info):
    found = {}
    for c in (info or {}).get("chapters") or []:
        for kind, rx in CHAPTER_KINDS:
            if rx.search(c["title"]) and c["end"] - c["start"] >= 5 and kind not in found:
                found[kind] = (c["start"], c["end"])
                break
    return found


# ---------------------------------------------------------------- fingerprints

def _has_chromaprint():
    exe = media.tool("ffmpeg")
    if not exe:
        return False
    if not hasattr(_has_chromaprint, "v"):
        try:
            out = subprocess.run([exe, "-hide_banner", "-muxers"], capture_output=True, text=True, timeout=20).stdout
            _has_chromaprint.v = " chromaprint " in out
        except (OSError, subprocess.SubprocessError):
            _has_chromaprint.v = False
    return _has_chromaprint.v


def fingerprint(path, start, length):
    """(codes, seconds per code) for `length` seconds of sound from `start`."""
    exe = media.tool("ffmpeg")
    base = ["nice", "-n", "15", exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", "%.2f" % max(0, start),
            "-t", "%.2f" % length, "-i", path, "-vn", "-sn", "-dn", "-ac", "1"]
    if _has_chromaprint():
        out = subprocess.run(base + ["-f", "chromaprint", "-fp_format", "raw", "-"], capture_output=True, timeout=600).stdout
        codes = array("I")
        codes.frombytes(out[:len(out) // 4 * 4])
        return list(codes), 4096 / 3 / 11025          # Chromaprint's step: a third of 4096 samples at 11025 Hz
    rate, frame = 8000, 1000                            # 0.125 s per code
    out = subprocess.run(base + ["-ar", str(rate), "-f", "s16le", "-"], capture_output=True, timeout=600).stdout
    pcm = array("h")
    pcm.frombytes(out[:len(out) // 2 * 2])
    energy, bright, noisy = [], [], []
    for i in range(0, len(pcm) - frame, frame):
        w = pcm[i:i + frame]
        energy.append(math.log1p(sum(x * x for x in w) / frame))
        bright.append(math.log1p(sum((w[k] - w[k - 1]) ** 2 for k in range(1, frame, 2)) / frame))
        noisy.append(sum(1 for k in range(1, frame) if (w[k] >= 0) != (w[k - 1] >= 0)))
    codes = []
    for t in range(len(energy)):
        c = 0
        for b, f in enumerate((energy, bright, noisy)):
            for lag in range(1, 9):
                if t >= lag and f[t] > f[t - lag]:
                    c |= 1 << (b * 8 + lag - 1)
        codes.append(c if energy[t] > 3 else 0)        # silence matches everything: leave it out
    return codes, frame / rate


def _bits(x):
    return bin(x).count("1")


def best_match(a, b, period, tolerance=None):
    """Longest stretch where fingerprint b sounds like fingerprint a: (start_a, start_b, seconds) or None."""
    if not a or not b:
        return None
    tolerance = tolerance if tolerance is not None else (6 if period < 0.124 else 5)
    common = collections.Counter(a + b)
    noise = {v for v, n in common.items() if n > (len(a) + len(b)) * 0.04} | {0}
    where = collections.defaultdict(list)
    for i, v in enumerate(a):
        if v not in noise:
            where[v].append(i)
    shifts = collections.Counter()
    for j, v in enumerate(b):
        for i in where.get(v, ()):
            shifts[i - j] += 1
    best = None
    gap_allowed = int((3.5 if period < 0.124 else 1.5) / period)   # the home-made fingerprint needs tighter runs
    for shift, _n in shifts.most_common(25):
        run_start, last_hit, i0 = None, None, max(0, shift)
        for i in range(i0, min(len(a), len(b) + shift)):
            hit = _bits(a[i] ^ b[i - shift]) <= tolerance and a[i] not in noise
            if hit:
                if run_start is None or i - last_hit > gap_allowed:
                    run_start = i
                last_hit = i
                length = (last_hit - run_start + 1) * period
                if not best or length > best[2]:
                    best = (run_start * period, (run_start - shift) * period, length)
    return best


# ---------------------------------------------------------------- whole seasons

def analyze_season(episodes):
    """episodes: library items of one season, in order. Stores what it finds."""
    durations = {}
    for ep in episodes:
        info = media.probe(ep["path"])
        durations[ep["id"]] = (info or {}).get("duration") or 0
        for kind, (s, e) in from_chapters(ep, info).items():
            if not _cleared(ep["id"], kind):
                set_marker(ep["id"], kind, s, e, "chapters")
    need = [ep for ep in episodes if durations[ep["id"]] > 300]
    if len(need) < 2:
        return
    prints = {}

    def fp(ep, where):
        key = (ep["id"], where)
        if key not in prints:
            d = durations[ep["id"]]
            if where == "start":
                prints[key] = fingerprint(ep["path"], 0, min(INTRO_WINDOW, d * 0.4)) + (0.0,)
            else:
                begin = max(d * 0.6, d - CREDITS_WINDOW)
                prints[key] = fingerprint(ep["path"], begin, d - begin) + (begin,)
        return prints[key]

    for a, b in zip(need, need[1:]):
        for where, lo, hi, kind in (("start", MIN_INTRO, MAX_INTRO, "intro"), ("end", MIN_CREDITS, CREDITS_WINDOW, "credits")):
            if all(_known(x["id"], kind) for x in (a, b)):
                continue
            ca, period, off_a = fp(a, where)
            cb, _, off_b = fp(b, where)
            m = best_match(ca, cb, period)
            if not m or not (lo <= m[2] <= hi):
                continue
            for ep, start in ((a, off_a + m[0]), (b, off_b + m[1])):
                end = start + m[2]
                if kind == "credits" and durations[ep["id"]] - end < 8:
                    end = durations[ep["id"]]
                if not _known(ep["id"], kind):
                    set_marker(ep["id"], kind, start, end, "audio")
        for ep in (a,):
            prints.pop((ep["id"], "start"), None)
            prints.pop((ep["id"], "end"), None)


def _known(item_id, kind):
    return store.q1("SELECT 1 FROM markers WHERE item = ? AND kind = ?", item_id, kind) is not None


def _cleared(item_id, kind):
    return store.q1("SELECT 1 FROM markers WHERE item = ? AND kind = ? AND source = 'cleared'", item_id, kind) is not None


def season_key(item):
    return "%s|%d" % (item["show_id"], item["s"]) if item.get("kind") == "episode" and item.get("s") else None


def want(item):
    """Someone started an episode: look at its season next (if it hasn't been)."""
    key = season_key(item)
    if key and key not in _urgent:
        _urgent.append(key)
        _wake.set()


def set_for_season(library, item, kind, start, end):
    """The same intro (or credits) for every episode of this episode's season."""
    key = season_key(item)
    eps = [i for i in list(library.items.values()) if season_key(i) == key] if key else [item]
    for ep in eps:
        set_marker(ep["id"], kind, start, end, "manual")
    return len(eps)


def recheck():
    """Listen to every season again (keeps markers set by hand)."""
    _table()
    store.ex("DELETE FROM marker_scans")
    store.ex("DELETE FROM markers WHERE source = 'audio'")
    _wake.set()


def status(library):
    _table()
    seasons = list(_seasons(library))
    done = {r["season"]: r["signature"] for r in store.q("SELECT season, signature FROM marker_scans")}
    checked = sum(1 for key, sig, _eps in seasons if done.get(key) == sig)
    found = store.q1("SELECT COUNT(*) AS n FROM markers WHERE kind = 'intro' AND end > start")["n"]
    credits = store.q1("SELECT COUNT(*) AS n FROM markers WHERE kind = 'credits' AND end > start")["n"]
    working = _state.get("working")
    if working:
        show = library.find(working.split("|")[0]) or {}
        working = "%s, season %s" % (show.get("name", "a show") if not show.get("adult") else "a private show", working.split("|")[1])
    return {"seasons": len(seasons), "checked": checked, "intros": found, "credits": credits, "working": working,
            "enabled": bool(config.get("detect_intros")), "method": "Chromaprint" if _has_chromaprint() else "built-in"}


def _seasons(library):
    groups = collections.defaultdict(list)
    for item in list(library.items.values()):
        if item["kind"] == "episode" and item.get("s"):
            groups["%s|%d" % (item["show_id"], item["s"])].append(item)
    for key, eps in sorted(groups.items()):
        eps.sort(key=lambda i: i["e"])
        sig = hashlib.sha1("|".join("%s:%d" % (e["id"], e["size"]) for e in eps).encode()).hexdigest()[:16]
        yield key, sig, eps


def _analyze(key, sig, eps):
    row = store.q1("SELECT signature FROM marker_scans WHERE season = ?", key)
    if row and row["signature"] == sig:
        return
    _state["working"] = key
    try:
        analyze_season(eps)
    except Exception as exc:
        store.log("error", "Looking for intros: %s" % str(exc)[:150])
    finally:
        _state["working"] = None
    store.ex("INSERT OR REPLACE INTO marker_scans (season, signature, at) VALUES (?,?,?)", key, sig, int(time.time()))


def _loop(library):
    _table()
    _wake.wait(60)
    while True:
        _wake.clear()
        try:
            if config.get("detect_intros") and media.tool("ffmpeg"):
                seasons = {key: (sig, eps) for key, sig, eps in _seasons(library)}
                while _urgent:                           # what people are watching first, busy or not
                    key = _urgent.pop(0)
                    if key in seasons:
                        _analyze(key, *seasons[key])
                for key, (sig, eps) in seasons.items():
                    if _urgent:
                        break                            # someone started something: go back and do that first
                    while media.busy() and not _urgent:
                        time.sleep(30)
                    _analyze(key, sig, eps)
                if _urgent:
                    continue
        except Exception as exc:
            store.log("error", "Intro finder: %s" % exc)
        _wake.wait(1800)


def poke():
    _wake.set()


def start(library):
    threading.Thread(target=_loop, args=(library,), daemon=True, name="intros").start()
