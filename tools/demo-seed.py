#!/usr/bin/env python3
"""The public demo's seed tool: its free library, its channel list, its config.json. docs/public-demo.md says when
to run what.

    python3 tools/demo-seed.py library MANIFEST --library DIR [--fetch] [--convert]
        Builds the library from a manifest (deploy/demo/library.json is ours): Movies/<Title (Year)>/ and
        Shows/<Show>/Season N/, each video with its rights record (<name>.rights.json, sofa/rights.py), its details
        (.nfo) and a picture taken from the video itself (never a poster from elsewhere). A title without a rights
        record that passes is refused, and nothing of it is written. --fetch downloads a title's download_url when
        it has no file; --convert makes a copy browsers play as it is (H.264 and AAC in MP4) when a file isn't one,
        and says so in the record's "changes".

    python3 tools/demo-seed.py channels CHANNELS --check
        Plays each channel in channels.json the way a browser on another site would: the playlist, a variant and a
        segment, each asked for with an Origin header. A channel whose answers all carry CORS headers gets
        "cors": true and today's date in "checked"; one that doesn't loses them, and the demo leaves it out.
        Without --check: only what can be told without asking (https, no FAST service, a rights note...).

    python3 tools/demo-seed.py check --library DIR [--demo DIR] [--online]
        What the demo will show and leave out, and why: every title's record, every channel. --online also asks
        each title's play_url for a byte range, as a browser's player does. Exits 1 when anything is left out.

    python3 tools/demo-seed.py config --data DIR --library DIR [--demo DIR] [--contact ADDRESS]
        Writes the demo's config.json: the demo switch on, the decades off (with defaults_rev 1), the library and
        demo folders. A config.json that's there already is kept, with only those keys changed.

Standard library only; ffmpeg and ffprobe (for --convert and the pictures) from PATH.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if __name__ == "__main__":                     # (sofa.config reads a data folder: a throwaway one, never a real Sofa's)
    os.environ["SOFA_DATA"] = tempfile.mkdtemp(prefix="sofa-demo-seed-")
    import atexit
    atexit.register(shutil.rmtree, os.environ["SOFA_DATA"], True)

from sofa import __version__, demo, rights  # noqa: E402

AGENT = "Sofa-demo-seed/%s (+https://github.com/krintoxi/sofa)" % __version__   # who's asking, said plainly
ORIGIN = "https://sofa-demo.invalid"           # a site that isn't the channel's: what a browser on the demo sends
PLAYABLE_VIDEO = ("h264", "vp9", "av1")
PLAYABLE_AUDIO = ("aac", "mp3", "opus", "vorbis")
TODAY = datetime.date.today().isoformat()


def say(*a):
    print(*a, flush=True)


def safe(name):
    return re.sub(r'[\\/:*?"<>|]+', " ", str(name)).strip() or "Untitled"


# ---------------------------------------------------------------- video files

def probe(path):
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    out = subprocess.run([exe, "-v", "error", "-show_entries", "format=format_name,duration:stream=codec_type,codec_name",
                          "-of", "json", path], capture_output=True, text=True, timeout=120)
    try:
        return json.loads(out.stdout or "{}")
    except ValueError:
        return None


def plays_as_is(info, path):
    """MP4 or WebM with video and audio browsers play without help."""
    if not info:
        return False
    fmt = (info.get("format") or {}).get("format_name") or ""
    v = [s.get("codec_name") for s in info.get("streams") or [] if s.get("codec_type") == "video"]
    a = [s.get("codec_name") for s in info.get("streams") or [] if s.get("codec_type") == "audio"]
    ext = os.path.splitext(path)[1].lower()
    return (ext in (".mp4", ".m4v", ".webm") and ("mp4" in fmt or "webm" in fmt or "matroska" in fmt)
            and bool(v) and all(c in PLAYABLE_VIDEO for c in v) and all(c in PLAYABLE_AUDIO for c in a))


def convert(src, dest):
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SystemExit("--convert needs ffmpeg on PATH")
    tmp = dest + ".part.mp4"
    subprocess.run([exe, "-v", "error", "-y", "-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264",
                    "-preset", "slow", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", tmp], check=True, timeout=6 * 3600)
    os.replace(tmp, dest)


def picture(video, dest, at=0.2):
    """A still from the video itself (its own licence covers it)."""
    exe = shutil.which("ffmpeg")
    if not exe or os.path.exists(dest):
        return
    info = probe(video) or {}
    try:
        t = float((info.get("format") or {}).get("duration") or 0) * at
    except ValueError:
        t = 0
    subprocess.run([exe, "-v", "error", "-y", "-ss", "%.2f" % max(1.0, t), "-i", video, "-frames:v", "1",
                    "-vf", "scale=1280:-2", "-q:v", "3", dest], timeout=120)


def fetch(url, dest, sha256=None):
    if not url.startswith("https://"):
        raise ValueError("download_url isn't https")
    say("  downloading %s" % url)
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=60) as r, open(dest + ".part", "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            f.write(chunk)
    if sha256 and h.hexdigest() != sha256.lower():
        os.remove(dest + ".part")
        raise ValueError("the download's SHA-256 isn't the manifest's")
    os.replace(dest + ".part", dest)


def nfo(path, root, fields):
    import xml.sax.saxutils as x
    body = "".join("  <%s>%s</%s>\n" % (k, x.escape(str(v)), k) for k, v in fields.items() if v)
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<%s>\n%s</%s>\n' % (root, body, root))


def write_json(path, data):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(path + ".tmp", path)


# ---------------------------------------------------------------- library

def place_video(entry, record, base, args):
    """The title's file at `base` + its extension, as browsers play it: (the record with what was changed, the
    video's path)."""
    src = entry.get("file")
    if src:
        src = os.path.abspath(os.path.expanduser(src))
        if not os.path.isfile(src):
            raise ValueError("file %s isn't there" % src)
    elif entry.get("download_url") and args.fetch:
        ext = os.path.splitext(urllib.parse.urlsplit(entry["download_url"]).path)[1].lower() or ".mp4"
        src = base + ".download" + ext
        if not os.path.exists(src):
            fetch(entry["download_url"], src, entry.get("sha256"))
    else:
        raise ValueError("no file (and no download_url, or --fetch not given)")
    info = probe(src)
    if plays_as_is(info, src):
        dest = base + os.path.splitext(src)[1].lower()
        if ".download." in os.path.basename(src):
            os.replace(src, dest)
        elif os.path.abspath(src) != os.path.abspath(dest):
            shutil.copyfile(src, dest + ".part")
            os.replace(dest + ".part", dest)
    elif args.convert:
        dest = base + ".mp4"
        say("  converting for browsers")
        convert(src, dest)
        note = "Converted to H.264 video and AAC audio in MP4, for browsers; nothing else was changed."
        record = dict(record, changes=" ".join(x for x in (record.get("changes"), note) if x))
    else:
        raise ValueError("not a file browsers play as it is (MP4 or WebM with H.264, VP9 or AV1): use --convert"
                         if info else "ffprobe couldn't read it (is ffmpeg installed?)")
    if ".download." in os.path.basename(src) and os.path.exists(src):
        os.remove(src)
    return record, dest


def build_library(args):
    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)
    lib = os.path.abspath(args.library)
    made, refused = 0, []
    for entry in manifest.get("titles") or []:
        name = entry.get("title") or "?"
        record = entry.get("rights")
        if entry.get("hold"):                    # (kept out until someone decides: the manifest says why)
            say("HELD %s: %s" % (name, entry["hold"]))
            continue
        bad = rights.problems(record)
        if bad:
            refused.append((name, bad))
            continue
        try:
            if entry.get("kind") == "show":
                made += build_show(lib, entry, record, args)
            else:
                made += build_movie(lib, entry, record, args)
        except (ValueError, OSError, subprocess.SubprocessError, urllib.error.URLError) as exc:
            refused.append((name, [str(exc)]))
    say("%d video%s in %s" % (made, "" if made == 1 else "s", lib))
    for name, why in refused:
        say("LEFT OUT %s: %s" % (name, "; ".join(why)))
    return 1 if refused else 0


def build_movie(lib, entry, record, args):
    title, year = safe(entry["title"]), entry.get("year")
    base = "%s (%s)" % (title, year) if year else title
    folder = os.path.join(lib, "Movies", base)
    os.makedirs(folder, exist_ok=True)
    say("Movie: %s" % base)
    try:
        record, video = place_video(entry, record, os.path.join(folder, base), args)
    except Exception:
        if not os.listdir(folder):                # (nothing of a title that isn't taken stays behind)
            os.rmdir(folder)
        raise
    write_json(os.path.join(folder, base + ".rights.json"), record)
    nfo(os.path.join(folder, "movie.nfo"), "movie", {"title": entry["title"], "year": year, "plot": entry.get("summary"),
                                                     "studio": record.get("publisher")})
    picture(video, os.path.join(folder, "folder.jpg"))
    return 1


def build_show(lib, entry, record, args):
    name = safe(entry["title"])
    folder = os.path.join(lib, "Shows", name)
    os.makedirs(folder, exist_ok=True)
    say("Show: %s" % name)
    write_json(os.path.join(folder, "rights.json"), record)
    nfo(os.path.join(folder, "tvshow.nfo"), "tvshow", {"title": entry["title"], "plot": entry.get("summary"),
                                                       "studio": record.get("publisher")})
    n = 0
    for ep in entry.get("episodes") or []:
        rec = ep.get("rights") or record
        bad = rights.problems(rec)
        if bad:
            raise ValueError("episode %s: %s" % (ep.get("title"), "; ".join(bad)))
        s, e = int(ep["season"]), int(ep["episode"])
        season = os.path.join(folder, "Season %d" % s)
        os.makedirs(season, exist_ok=True)
        stem = "%s S%02dE%02d" % (name, s, e)
        rec, video = place_video(ep, rec, os.path.join(season, stem), args)
        write_json(os.path.join(season, stem + ".rights.json"), rec)
        nfo(os.path.join(season, stem + ".nfo"), "episodedetails", {"title": ep.get("title"), "season": s, "episode": e,
                                                                    "plot": ep.get("summary")})
        picture(video, os.path.join(season, stem + ".jpg"), at=0.3)
        n += 1
    first = next((os.path.join(folder, d, f) for d in sorted(os.listdir(folder)) if d.startswith("Season ")
                  for f in sorted(os.listdir(os.path.join(folder, d))) if f.endswith((".mp4", ".webm"))), None)
    if first:
        picture(first, os.path.join(folder, "folder.jpg"))
    return n


# ---------------------------------------------------------------- channels

def ask(url, method="GET", headers=None, limit=1 << 20):
    h = {"User-Agent": AGENT, "Origin": ORIGIN}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(limit), r.geturl()


def cors_ok(headers):
    allow = (headers.get("access-control-allow-origin") or "").strip()
    return allow in ("*", ORIGIN)


def check_channel_online(c):
    """The playlist, a variant and a segment, as a browser on another site asks for them: (ok, why)."""
    try:
        status, headers, body, where = ask(c["url"])
        if not cors_ok(headers):
            return False, "the playlist has no CORS header for other sites"
        text = body.decode("utf-8", "replace")
        if "#EXTM3U" not in text:
            return False, "not an HLS playlist"
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        if "#EXT-X-STREAM-INF" in text and lines:                 # a master playlist: one of its qualities
            variant = urllib.parse.urljoin(where, lines[0])
            if not variant.startswith("https://"):
                return False, "a quality isn't https"
            status, headers, body, where = ask(variant)
            if not cors_ok(headers):
                return False, "a quality's playlist has no CORS header"
            text = body.decode("utf-8", "replace")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        if not lines:
            return False, "no segments"
        seg = urllib.parse.urljoin(where, lines[-1])
        if not seg.startswith("https://"):
            return False, "a segment isn't https"
        status, headers, _, _ = ask(seg, limit=64 * 1024)
        if not cors_ok(headers):
            return False, "a segment has no CORS header"
        return True, "plays in a browser on another site"
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return False, "didn't answer: %s" % str(exc)[:120]


def channels_cmd(args):
    with open(args.channels, encoding="utf-8") as f:
        data = json.load(f)
    chans = data.get("channels") or []
    bad = 0
    for c in chans:
        if args.check:
            fields = demo.channel_problems(dict(c, cors=True, checked=TODAY))      # (all but the check itself)
            if fields:
                ok, why = False, "; ".join(fields)
            else:
                ok, why = check_channel_online(c)
            if ok:
                c.update(cors=True, checked=TODAY)
            else:
                c.pop("cors", None)
            say("%s %s: %s" % ("OK  " if ok else "OUT ", c.get("name"), why))
            bad += not ok
        else:
            why = demo.channel_problems(c)
            say("%s %s%s" % ("OK  " if not why else "OUT ", c.get("name"), (": " + "; ".join(why)) if why else ""))
            bad += bool(why)
    if args.check:
        write_json(args.channels, data)
    return 1 if bad else 0


# ---------------------------------------------------------------- check

def records(lib):
    """(video, record) for every video in the library."""
    for top in ("Movies", "Shows"):
        for d, _dirs, names in os.walk(os.path.join(lib, top)):
            for n in sorted(names):
                if os.path.splitext(n)[1].lower() in (".mp4", ".m4v", ".webm", ".mkv", ".mov", ".avi"):
                    path = os.path.join(d, n)
                    yield path, rights.read(path)


def check_cmd(args):
    out = 0
    lib = os.path.abspath(args.library)
    for path, rec in records(lib):
        why = rights.problems(rec)
        rel = os.path.relpath(path, lib)
        if not why and not (rec or {}).get("play_url"):
            why = ["no play_url: plays only with demo_serve_files on (not through a Cloudflare tunnel)"] \
                if not args.serve_files else []
        if not why and args.online and rec.get("play_url"):
            try:
                status, headers, _, _ = ask(rec["play_url"], headers={"Range": "bytes=0-1"}, limit=16)
                if status != 206 and "bytes" not in (headers.get("accept-ranges") or ""):
                    why = ["play_url doesn't answer byte ranges (no seeking)"]
                elif not (headers.get("content-type") or "").startswith(("video/", "application/octet-stream")):
                    why = ["play_url isn't a video (%s)" % headers.get("content-type")]
            except (OSError, urllib.error.URLError) as exc:
                why = ["play_url didn't answer: %s" % str(exc)[:100]]
        say("%s %s%s" % ("OK  " if not why else "OUT ", rel, (": " + "; ".join(why)) if why else ""))
        out |= bool(why)
    if args.demo:
        for c in demo.read_channel_list(os.path.join(args.demo, "channels.json")):
            why = demo.channel_problems(c)
            say("%s channel %s%s" % ("OK  " if not why else "OUT ", c.get("name"), (": " + "; ".join(why)) if why else ""))
            out |= bool(why)
    return 1 if out else 0


# ---------------------------------------------------------------- config.json

def config_cmd(args):
    path = os.path.join(args.data, "config.json")
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    lib = os.path.abspath(args.library)
    data.update({"demo": True, "retro_eras": False, "defaults_rev": 1, "share_on": True, "share_all": True,
                 "public_open": True, "share_cinema": False, "archive_channels": False,
                 "shows": lib + "/Shows", "movies": lib + "/Movies", "music": lib + "/Music",
                 "musicvideos": lib + "/Music Videos", "inbox": lib + "/Inbox", "review": lib + "/Needs Review",
                 "adult": lib + "/Adult", "originals": lib + "/Converted Originals"})
    if args.demo:
        data["demo_folder"] = args.demo
    if args.contact:
        data["share_contact"] = args.contact
    data.setdefault("share_title", "Sofa demo")
    os.makedirs(args.data, exist_ok=True)
    write_json(path, data)
    say("Wrote %s" % path)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="The public demo's library, channel list and config.json.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("library")
    a.add_argument("manifest")
    a.add_argument("--library", required=True)
    a.add_argument("--fetch", action="store_true")
    a.add_argument("--convert", action="store_true")
    a = sub.add_parser("channels")
    a.add_argument("channels")
    a.add_argument("--check", action="store_true")
    a = sub.add_parser("check")
    a.add_argument("--library", required=True)
    a.add_argument("--demo")
    a.add_argument("--online", action="store_true")
    a.add_argument("--serve-files", action="store_true", help="the demo will serve its own copies (demo_serve_files)")
    a = sub.add_parser("config")
    a.add_argument("--data", required=True)
    a.add_argument("--library", required=True)
    a.add_argument("--demo")
    a.add_argument("--contact")
    args = p.parse_args(argv)
    return {"library": build_library, "channels": channels_cmd, "check": check_cmd, "config": config_cmd}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
