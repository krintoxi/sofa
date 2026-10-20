"""Playing any format: direct when the device can, otherwise ffmpeg on the fly.

direct     the file as-is, with seeking (most MP4s)
remux      same video, new container (MKV/AVI with H.264 -> MP4). Costs almost nothing.
transcode  new video (XviD, MPEG-2, HEVC on devices without it). Uses the Mac's encoder.

Remux and transcode streams start at ?t=<seconds>; the player asks for a new
stream when you skip, so seeking still works.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time

from . import config, store

PROBE_VERSION = 2          # bump when probe() starts recording something new; older cache rows are re-read
_streams = {}
_streams_lock = threading.Lock()
_transcode_slots = None


def tool(name):
    setting = config.get("ffmpeg")
    candidates = []
    if setting and setting != "auto":
        candidates.append(os.path.join(os.path.expanduser(setting), name))
    candidates += [os.path.join(config.APP_DIR, "vendor", "ffmpeg", "bin", name),
                   "/opt/homebrew/bin/" + name, "/usr/local/bin/" + name, shutil.which(name) or ""]
    for c in candidates:
        if c and os.access(c, os.X_OK):
            return c
    return None


def ffmpeg_version():
    exe = tool("ffmpeg")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-hide_banner", "-version"], capture_output=True, text=True, timeout=10).stdout
        return out.split("\n", 1)[0].replace("ffmpeg version ", "").split(" Copyright")[0]
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------- probing

def probe(path, cached_only=False):
    """Stream info from ffprobe, cached by size+mtime. None if ffprobe is missing or the file is unreadable."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    row = store.q1("SELECT size, mtime, info FROM probes WHERE path = ?", path)
    if row and row["size"] == st.st_size and row["mtime"] == int(st.st_mtime):
        info = json.loads(row["info"])
        if info.get("v") == PROBE_VERSION:
            return info
    if cached_only:
        return None
    exe = tool("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
                             capture_output=True, text=True, timeout=60).stdout
        raw = json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    streams = raw.get("streams", [])
    fmt = raw.get("format") or {}
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    for st_ in streams:   # some formats (Ogg, FLAC in Matroska) keep tags on the audio stream
        if st_.get("codec_type") == "audio":
            for k, v in (st_.get("tags") or {}).items():
                tags.setdefault(k.lower(), v)
    info = {
        "v": PROBE_VERSION,
        "tags": {k: tags[k] for k in ("title", "artist", "album_artist", "album", "track", "disc", "date", "genre")
                 if k in tags},
        "art": any((s_.get("disposition") or {}).get("attached_pic") for s_ in streams),
        "duration": float(fmt.get("duration") or 0),
        "container": fmt.get("format_name", ""),
        "video": next(({"codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height"),
                        "index": s["index"]} for s in streams
                       if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None),
        "audio": [{"codec": s.get("codec_name"), "channels": s.get("channels"), "index": s["index"],
                   "lang": (s.get("tags") or {}).get("language"), "default": (s.get("disposition") or {}).get("default")}
                  for s in streams if s.get("codec_type") == "audio"],
        "subs": [{"codec": s.get("codec_name"), "index": s["index"], "lang": (s.get("tags") or {}).get("language"),
                  "title": (s.get("tags") or {}).get("title")}
                 for s in streams if s.get("codec_type") == "subtitle"],
    }
    store.ex("INSERT OR REPLACE INTO probes (path, size, mtime, info) VALUES (?,?,?,?)",
             path, st.st_size, int(st.st_mtime), json.dumps(info))
    return info


TEXT_SUBS = {"subrip", "ass", "ssa", "webvtt", "mov_text", "text"}


def subtitle_tracks(item, info):
    tracks = [{"label": s["lang"], "lang": s["lang"], "source": "file", "path": s["path"]} for s in item.get("subs", [])]
    for s in (info or {}).get("subs", []):
        if s["codec"] in TEXT_SUBS:
            tracks.append({"label": s.get("title") or s.get("lang") or "Subtitles", "lang": s.get("lang") or "und",
                           "source": "embedded", "index": s["index"]})
    return tracks


# ---------------------------------------------------------------- deciding how to play

def plan(item, caps):
    """How a device with these capabilities should play this item."""
    info = probe(item["path"])
    ext = item["ext"]
    container_ok = ext in ("mp4", "m4v", "mov") or (ext == "mkv" and caps.get("mkv")) or (ext == "webm")
    if not info:
        mode = "direct" if container_ok else ("remux" if tool("ffmpeg") else "unsupported")
        return {"mode": mode, "duration": None, "info": None}
    v = (info.get("video") or {}).get("codec")
    audio = info.get("audio") or []
    a = (next((x for x in audio if x.get("default")), audio[0]) if audio else {}).get("codec")
    video_ok = v == "h264" or (v == "hevc" and caps.get("hevc")) or (v in ("vp8", "vp9", "av1") and caps.get("vp9"))
    audio_ok = a in (None, "aac", "mp3", "opus", "vorbis", "flac") or (a in ("ac3", "eac3") and caps.get("ac3"))
    if container_ok and video_ok and audio_ok:
        mode = "direct"
    elif not tool("ffmpeg"):
        mode = "unsupported"
    elif video_ok:
        mode = "remux"
    else:
        mode = "transcode"
    return {"mode": mode, "duration": info.get("duration"), "info": info}


# ---------------------------------------------------------------- live streams

def stream_command(item, mode, start, info, fmt="mp4", out="pipe:1"):
    exe = tool("ffmpeg")
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", "%.3f" % start]
    if mode == "audio":   # music in a format the browser can't play: AAC in fragmented MP4
        return cmd + ["-i", item["path"], "-map", "0:a:0", "-vn", "-sn", "-dn", "-c:a", "aac", "-b:a", "256k",
                      "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", out]
    cmd += ["-i", item["path"], "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]
    audio = (info or {}).get("audio") or []
    a = audio[0]["codec"] if audio else None
    if mode == "remux":
        cmd += ["-c:v", "copy"]
        if (info or {}).get("video", {}).get("codec") == "hevc":
            cmd += ["-tag:v", "hvc1"]
    else:
        height = ((info or {}).get("video") or {}).get("height") or 720
        cmd += ["-c:v", "h264_videotoolbox", "-allow_sw", "1", "-realtime", "1",
                "-b:v", "6M" if height > 720 else "3500k", "-maxrate", "9M", "-bufsize", "12M",
                "-pix_fmt", "yuv420p", "-vf", "scale='min(1920,iw)':-2"]
    if a in ("aac", "mp3"):
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]
    if fmt == "mp4":
        cmd += ["-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", out]
    elif fmt == "mpegts":
        cmd += ["-f", "mpegts", out]
    else:   # hls: `out` is the session folder
        cmd += ["-f", "hls", "-hls_time", "4", "-hls_list_size", "0", "-hls_playlist_type", "event",
                "-hls_flags", "independent_segments", "-hls_segment_filename", os.path.join(out, "seg%05d.ts"),
                os.path.join(out, "index.m3u8")]
    return cmd


def _slot(mode):
    global _transcode_slots
    if _transcode_slots is None:
        _transcode_slots = threading.BoundedSemaphore(max(1, int(config.get("max_transcodes"))))
    slot = _transcode_slots if mode == "transcode" else None
    if slot and not slot.acquire(timeout=5):
        raise RuntimeError("busy")
    return slot


def run_stream(item, mode, start, info, out, who, fmt="mp4"):
    """Pipe ffmpeg's output to `out` until done or the viewer leaves."""
    slot = _slot(mode)
    key = "%s-%s" % (id(out), time.time())
    proc = subprocess.Popen(stream_command(item, mode, start, info, fmt), stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, bufsize=0)
    with _streams_lock:
        _streams[key] = {"item": item["id"], "title": item.get("title"), "mode": mode, "who": who,
                         "started": int(time.time())}
    try:
        while True:
            chunk = proc.stdout.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        proc.kill()
        proc.wait()
        with _streams_lock:
            _streams.pop(key, None)
        if slot:
            slot.release()


def note_direct(item, who):
    """Direct plays are short range requests; remember them briefly so the admin page can show them."""
    with _streams_lock:
        _streams["direct-%s-%s" % (who, item["id"])] = {"item": item["id"], "title": item.get("title"), "mode": "direct",
                                                       "who": who, "started": int(time.time()), "direct": True}


def active_streams():
    now = time.time()
    with _streams_lock:
        for k in [k for k, v in _streams.items() if v.get("direct") and now - v["started"] > 120]:
            _streams.pop(k)
        return list(_streams.values())


# ---------------------------------------------------------------- HLS (Safari, iPhone, iPad)

_hls = {}
_hls_lock = threading.Lock()
HLS_IDLE = 90


def hls_dir():
    return os.path.join(config.DATA_DIR, "cache", "hls")


def hls_start(item, mode, start, who, replace=None):
    """Start segmenting from `start` seconds. Returns a session id."""
    if replace:
        hls_stop(replace)
    info = probe(item["path"])
    slot = _slot(mode)
    sid = hashlib.sha1(("%s|%s|%s" % (item["id"], start, time.time())).encode()).hexdigest()[:20]
    folder = os.path.join(hls_dir(), sid)
    os.makedirs(folder, exist_ok=True)
    proc = subprocess.Popen(stream_command(item, mode, start, info, "hls", folder),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with _hls_lock:
        _hls[sid] = {"proc": proc, "dir": folder, "seen": time.time(), "slot": slot}
    with _streams_lock:
        _streams["hls-" + sid] = {"item": item["id"], "title": item.get("title"), "mode": mode, "who": who,
                                  "started": int(time.time())}
    return sid


def hls_file(sid, name):
    """Path of a playlist/segment once ffmpeg has written it (waits up to 20s), else None."""
    if not re.fullmatch(r"(index\.m3u8|seg\d{5}\.ts)", name):
        return None
    with _hls_lock:
        s = _hls.get(sid)
        if s:
            s["seen"] = time.time()
    if not s:
        return None
    path = os.path.join(s["dir"], name)
    deadline = time.time() + 20
    while time.time() < deadline:
        if os.path.exists(path) and (name.endswith(".m3u8") or _segment_done(s, name)):
            return path
        if s["proc"].poll() is not None and not os.path.exists(path):
            return None
        time.sleep(0.25)
    return None


def _segment_done(s, name):
    """A segment is complete once the playlist lists it (ffmpeg adds it after closing the file)."""
    try:
        with open(os.path.join(s["dir"], "index.m3u8"), encoding="utf-8") as f:
            return name in f.read()
    except OSError:
        return False


def hls_stop(sid):
    with _hls_lock:
        s = _hls.pop(sid, None)
    if not s:
        return
    s["proc"].kill()
    s["proc"].wait()
    if s["slot"]:
        s["slot"].release()
    shutil.rmtree(s["dir"], ignore_errors=True)
    with _streams_lock:
        _streams.pop("hls-" + sid, None)


def _hls_reaper():
    while True:
        time.sleep(30)
        with _hls_lock:
            idle = [sid for sid, s in _hls.items() if time.time() - s["seen"] > HLS_IDLE]
        for sid in idle:
            hls_stop(sid)


def start():
    """Server-only background work (not for one-off commands)."""
    shutil.rmtree(hls_dir(), ignore_errors=True)
    threading.Thread(target=_hls_reaper, daemon=True, name="hls-reaper").start()


# ---------------------------------------------------------------- subtitles

_TS = re.compile(r"(\d{1,2}:)?(\d{2}):(\d{2})[.,](\d{3})")


def _seconds(m):
    h = int(m.group(1)[:-1]) if m.group(1) else 0
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000


def _stamp(sec):
    sec = max(0.0, sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%06.3f" % (h, m, s)


def to_vtt(text, offset=0.0):
    """SRT or WebVTT text -> WebVTT, shifted back by `offset` seconds (for streams that start mid-way)."""
    src = text.replace("\r\n", "\n").lstrip("﻿").split("\n")
    lines = []
    for i, line in enumerate(src):
        if "-->" in line:
            stamps = list(_TS.finditer(line))
            if len(stamps) >= 2:
                line = "%s --> %s" % (_stamp(_seconds(stamps[0]) - offset), _stamp(_seconds(stamps[1]) - offset))
        elif re.fullmatch(r"\d+", line.strip()) and i + 1 < len(src) and "-->" in src[i + 1]:
            continue   # SRT cue numbers
        lines.append(line)
    body = "\n".join(lines)
    if not body.startswith("WEBVTT"):
        body = "WEBVTT\n\n" + body
    return body


def subtitle_vtt(item, track, offset):
    cache_dir = os.path.join(config.DATA_DIR, "cache", "subs")
    os.makedirs(cache_dir, exist_ok=True)
    if track["source"] == "file":
        ext = os.path.splitext(track["path"])[1].lower()
        if ext in (".srt", ".vtt"):
            with open(track["path"], encoding="utf-8", errors="replace") as f:
                return to_vtt(f.read(), offset)
        src, selector = track["path"], "0:s:0"
    else:
        src, selector = item["path"], "0:%d" % track["index"]
    st = os.stat(src)
    key = hashlib.sha1(("%s|%s|%d|%d" % (src, selector, st.st_size, st.st_mtime)).encode()).hexdigest()
    cached = os.path.join(cache_dir, key + ".vtt")
    if not os.path.exists(cached):
        exe = tool("ffmpeg")
        if not exe:
            return "WEBVTT\n"
        subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-map", selector,
                        "-f", "webvtt", cached], timeout=300)
    try:
        with open(cached, encoding="utf-8", errors="replace") as f:
            return to_vtt(f.read(), offset)
    except OSError:
        return "WEBVTT\n"


def extract_art(path, dest):
    """Save a file's embedded cover picture (MP3/M4A/FLAC artwork) as a JPEG. True on success."""
    exe = tool("ffmpeg")
    if not exe:
        return False
    tmp = dest + ".part.jpg"
    try:
        subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-map", "0:v:0", "-frames:v", "1",
                        "-vf", "scale='min(800,iw)':-2", "-q:v", "3", tmp], timeout=60, check=True)
        os.replace(tmp, dest)
        return True
    except (OSError, subprocess.SubprocessError):
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def extract_frame(path, dest, at=12.0):
    """A still from a video (for music videos without a thumbnail)."""
    exe = tool("ffmpeg")
    if not exe:
        return False
    tmp = dest + ".part.jpg"
    try:
        subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-ss", "%.1f" % at, "-i", path,
                        "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "4", tmp], timeout=60, check=True)
        os.replace(tmp, dest)
        return True
    except (OSError, subprocess.SubprocessError):
        if os.path.exists(tmp):
            os.remove(tmp)
        return False
