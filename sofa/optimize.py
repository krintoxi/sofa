"""Converting files for good, on the server itself.

Live conversion (media.py) adapts a file every time it's played. For MKV, AVI and
friends it's better to convert once: the result plays directly everywhere, seeks
instantly and costs nothing afterwards. This queue does that in the background,
one file at a time, giving way whenever someone is watching something that needs
live conversion.

* H.264 (8-bit) and HEVC video are copied as they are (fast, no quality loss).
  Anything else (XviD, MPEG-2, VC-1, 10-bit H.264) is re-encoded with the Mac's
  hardware encoder, or x264 elsewhere.
* The first sound track becomes AAC stereo so every device can play it; Dolby
  Digital tracks are kept alongside for Apple TVs and receivers.
* Text subtitles stay inside the MP4. Picture subtitles (Blu-ray PGS) can't, and
  are dropped; the original keeps them.
* The new MP4 is checked (same length) before the original is moved to
  "Converted Originals" (or deleted, if the admin chose that).

Watch progress is tied to what an item is, not its file name, so nobody loses
their place.
"""
import os
import re
import shutil
import subprocess
import threading
import time

from . import config, media, places, store

VIDEO_KINDS = ("episode", "movie", "extra", "musicvideo")
COPY_AUDIO = ("aac", "mp3", "ac3", "eac3")
TEXT_SUBS = ("subrip", "ass", "ssa", "webvtt", "mov_text", "text")
_wake = threading.Event()
_current = {}           # the conversion in progress: {"path", "progress", "proc"}
_lock = threading.Lock()


def _table():
    store.ex("""CREATE TABLE IF NOT EXISTS conversions (
        path TEXT PRIMARY KEY, item TEXT, title TEXT, state TEXT NOT NULL, added INTEGER NOT NULL,
        started INTEGER, finished INTEGER, error TEXT, before INTEGER, after INTEGER, how TEXT)""")


# ---------------------------------------------------------------- what to convert

def candidates(library):
    """Library videos that don't play as-is on an ordinary browser or TV (needs probes; unprobed files are skipped)."""
    out = []
    for item in list(library.items.values()):
        if item["kind"] not in VIDEO_KINDS:
            continue
        info = media.probe(item["path"], cached_only=True)
        if info is None and item["ext"] in ("mp4", "m4v"):
            continue
        if info is None or media.needs_conversion(item):
            out.append(item)
    return out


PRIVATE = "Private video"


def label(item):
    if item.get("adult"):
        return PRIVATE
    if item["kind"] == "episode":
        return "%s S%02dE%02d" % (item.get("show_name") or "", item["s"], item["e"])
    return item.get("title") or os.path.basename(item["path"])


def enqueue(items, reason="requested"):
    _table()
    added = 0
    for item in items:
        row = store.q1("SELECT state FROM conversions WHERE path = ?", item["path"])
        if row and row["state"] in ("queued", "working", "done"):
            continue
        store.ex("INSERT OR REPLACE INTO conversions (path, item, title, state, added) VALUES (?,?,?,?,?)",
                 item["path"], item["id"], label(item), "queued", int(time.time()))
        added += 1
    if added:
        store.log("convert", "%d file(s) queued for converting to MP4 (%s)" % (added, reason))
        _wake.set()
    return added


def auto_enqueue(library):
    """After a scan: queue new files that need it, when the admin has switched automatic converting on."""
    if not config.get("auto_convert") or not media.tool("ffmpeg"):
        return 0
    _table()
    known = {r["path"] for r in store.q("SELECT path FROM conversions")}
    return enqueue([i for i in candidates(library) if i["path"] not in known], "automatic")


def path_of(rid):
    """The file behind a queue row number (the page refers to rows by number, not by file path)."""
    _table()
    row = store.q1("SELECT path FROM conversions WHERE rowid = ?", int(rid))
    return row["path"] if row else None


def cancel(path):
    _table()
    store.ex("DELETE FROM conversions WHERE path = ? AND state IN ('queued', 'failed')", path)
    with _lock:
        if _current.get("path") == path and _current.get("proc"):
            _current["cancelled"] = True
            _current["proc"].kill()


def retry(path):
    _table()
    store.ex("UPDATE conversions SET state = 'queued', error = NULL WHERE path = ? AND state = 'failed'", path)
    _wake.set()


def clear_finished():
    _table()
    store.ex("DELETE FROM conversions WHERE state IN ('done', 'failed', 'gone')")


def status(library=None):
    _table()
    rows = [dict(r) for r in store.q("""SELECT rowid AS rid, * FROM conversions ORDER BY
             CASE state WHEN 'working' THEN 0 WHEN 'queued' THEN 1 WHEN 'failed' THEN 2 ELSE 3 END,
             COALESCE(finished, added) DESC LIMIT 80""")]
    with _lock:
        for r in rows:
            if r["path"] == _current.get("path"):
                r["progress"] = _current.get("progress", 0)
    for r in rows:                                    # the page needs no file paths, and private rows no details
        r.pop("path", None)
        if r["title"] == PRIVATE:
            r["error"] = "see the Adult section" if r.get("error") else None
            r["how"] = None
    counts = {s: store.q1("SELECT COUNT(*) AS n FROM conversions WHERE state = ?", s)["n"]
              for s in ("queued", "working", "done", "failed")}
    saved = store.q1("SELECT SUM(before - after) AS n FROM conversions WHERE state = 'done'")["n"] or 0
    out = {"rows": rows, "counts": counts, "saved": saved, "auto": bool(config.get("auto_convert")),
           "keep_originals": bool(config.get("keep_originals")), "originals": config.path("originals"),
           "hardware": media.hardware_encoder(), "waiting_for_viewers": bool(_current.get("waiting"))}
    if library is not None:
        known = {r["path"]: r["state"] for r in store.q("SELECT path, state FROM conversions")}
        out["candidates"] = sum(1 for i in candidates(library) if known.get(i["path"]) not in ("queued", "working", "done"))
    return out


# ---------------------------------------------------------------- converting one file

def build_command(src, dst, info):
    """The ffmpeg command, and a short description ("copy HEVC, AAC stereo + Dolby Digital")."""
    video = info.get("video")
    if not video:
        raise ValueError("there's no video in this file")
    cmd = [media.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if os.path.splitext(src)[1].lower()[1:] in media.LOOSE_TIMESTAMPS:
        cmd += ["-fflags", "+genpts"]
    cmd += ["-i", src, "-map", "0:%d" % video["index"]]
    how = []
    if media.video_playable(video, {"hevc": True}):
        cmd += ["-c:v", "copy"] + (["-tag:v", "hvc1"] if video["codec"] == "hevc" else [])
        how.append("copy " + media.describe_video(video))
    else:
        filters = (["yadif"] if video.get("interlaced") else []) + ["format=yuv420p"]
        cmd += media.h264_args(video.get("height"), live=False) + ["-vf", ",".join(filters), "-profile:v", "high"]
        how.append("%s to H.264%s" % (media.describe_video(video), " (hardware)" if media.hardware_encoder() else ""))

    audio = info.get("audio") or []
    first = media.default_audio(info)
    order = ([first] if first else []) + [a for a in audio if a is not first]
    n = 0
    for a in order:
        codec = a.get("codec")
        if a is first and codec not in ("aac", "mp3"):     # everyone can play AAC stereo: make it track 1
            cmd += ["-map", "0:%d" % a["index"], "-c:a:%d" % n, "aac", "-b:a:%d" % n, "192k", "-ac:a:%d" % n, "2"]
            how.append("%s to AAC stereo" % (codec or "sound").upper())
            n += 1
            if codec not in COPY_AUDIO:
                continue
        if codec in COPY_AUDIO:
            cmd += ["-map", "0:%d" % a["index"], "-c:a:%d" % n, "copy"]
        else:
            ch = min(int(a.get("channels") or 2), 6)
            cmd += ["-map", "0:%d" % a["index"], "-c:a:%d" % n, "aac", "-b:a:%d" % n, "%dk" % (96 * ch if ch > 2 else 192),
                    "-ac:a:%d" % n, str(ch)]
        if a.get("lang"):
            cmd += ["-metadata:s:a:%d" % n, "language=%s" % a["lang"]]
        n += 1
    if n:
        cmd += ["-disposition:a:0", "default"] + sum((["-disposition:a:%d" % i, "0"] for i in range(1, n)), [])
    subs = [s for s in info.get("subs") or [] if s.get("codec") in TEXT_SUBS]
    for i, s in enumerate(subs):
        cmd += ["-map", "0:%d" % s["index"], "-c:s:%d" % i, "mov_text"]
        if s.get("lang"):
            cmd += ["-metadata:s:s:%d" % i, "language=%s" % s["lang"]]
    if subs:
        how.append("%d subtitle track%s" % (len(subs), "" if len(subs) == 1 else "s"))
    cmd += ["-map_metadata", "0", "-map_chapters", "0", "-max_muxing_queue_size", "4096",
            "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", "-f", "mp4", dst]
    return cmd, ", ".join(how)


def _originals_dest(src):
    """Where an original goes: the same place under Converted Originals (Shows/X/Season 1/... keeps its shape)."""
    place = places.place_of(src)                  # on a drive: that drive's own Converted Originals (no copying across)
    home = place["path"] if place else os.path.dirname(config.path("shows"))
    rel = os.path.relpath(src, home)
    if rel.startswith(".."):
        rel = os.path.basename(src)
    return os.path.join(os.path.join(place["path"], "Converted Originals") if place else config.path("originals"), rel)


def convert(path, item_id=None):
    """Convert one file. Raises on failure; returns (new path, description)."""
    info = media.probe(path)
    if not info:
        raise ValueError("ffprobe couldn't read the file (is it damaged, or still copying?)")
    stem = os.path.splitext(path)[0]
    dest = stem + ".mp4"
    part = stem + ".mp4.sofa-part"
    cmd, how = build_command(path, part, info)
    with _lock:
        _current.update(path=path, progress=0.0, how=how)
    proc = subprocess.Popen((["nice", "-n", "10"] if shutil.which("nice") else []) + cmd,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    with _lock:
        _current["proc"] = proc
    total = info.get("duration") or 0
    for line in proc.stdout:
        m = re.match(r"out_time_(?:us|ms)=(\d+)", line.strip())
        if m and total:
            with _lock:
                _current["progress"] = min(0.999, int(m.group(1)) / 1e6 / total)
    err = proc.stderr.read()
    code = proc.wait()
    try:
        if _current.get("cancelled"):
            raise InterruptedError("cancelled")
        if code != 0:
            raise RuntimeError((err.strip().splitlines() or ["ffmpeg stopped (code %d)" % code])[-1][:300])
        out = media.probe(part)
        got = (out or {}).get("duration") or 0
        if not out or (total and abs(total - got) > max(2.0, total * 0.005)):
            raise RuntimeError("the new file is %.0fs long but the original is %.0fs, so it was kept" % (got, total))
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise
    if config.get("keep_originals"):
        keep = _originals_dest(path)
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        shutil.move(path, keep)
    else:
        os.remove(path)
    if os.path.exists(dest) and dest != path:      # an older MP4 with the same name: keep it aside too
        shutil.move(dest, _originals_dest(dest) + ".older.mp4")
    os.replace(part, dest)
    return dest, how


def _run_one(row):
    path = row["path"]
    if not os.path.exists(path):
        store.ex("UPDATE conversions SET state = 'gone', finished = ? WHERE path = ?", int(time.time()), path)
        return
    before = os.path.getsize(path)
    store.ex("UPDATE conversions SET state = 'working', started = ?, error = NULL, before = ? WHERE path = ?",
             int(time.time()), before, path)
    try:
        dest, how = convert(path, row["item"])
    except InterruptedError:
        store.ex("DELETE FROM conversions WHERE path = ?", path)
        store.log("convert", "Stopped converting %s" % ("a private video" if row["title"] == PRIVATE else row["title"]))
    except Exception as exc:
        store.ex("UPDATE conversions SET state = 'failed', finished = ?, error = ? WHERE path = ?",
                 int(time.time()), str(exc)[:400], path)
        if row["title"] == PRIVATE:
            store.log_private("convert", "Couldn't convert a private video")
        else:
            store.log("convert", "Couldn't convert %s: %s" % (row["title"], str(exc)[:200]), {"file": path})
    else:
        after = os.path.getsize(dest)
        store.ex("UPDATE conversions SET state = 'done', finished = ?, after = ?, how = ? WHERE path = ?",
                 int(time.time()), after, how, path)
        if row["title"] == PRIVATE:
            store.log_private("convert", "Converted a private video to MP4")
        else:
            store.log("convert", "Converted %s to MP4 (%s)" % (row["title"], how), {"file": dest})
    finally:
        with _lock:
            _current.clear()


def _loop():
    _table()
    store.ex("UPDATE conversions SET state = 'queued' WHERE state = 'working'")    # interrupted by a restart
    while True:
        _wake.wait(60)
        _wake.clear()
        while media.tool("ffmpeg"):
            if media.busy():               # someone is watching something converted live: they come first
                with _lock:
                    _current["waiting"] = True
                time.sleep(20)
                continue
            with _lock:
                _current.pop("waiting", None)
            row = store.q1("SELECT * FROM conversions WHERE state = 'queued' ORDER BY added, path LIMIT 1")
            if not row:
                break
            _run_one(dict(row))


def start():
    threading.Thread(target=_loop, daemon=True, name="converter").start()
