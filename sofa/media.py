"""Playing any format: direct when the device can, otherwise ffmpeg on the fly.

direct     the file as-is, with seeking (most MP4s)
remux      same video, new container (MKV/AVI with H.264 -> MP4). Costs almost nothing.
transcode  new video (XviD, MPEG-2, HEVC on devices without it). Uses the Mac's encoder.

Remux and transcode streams start at ?t=<seconds>; the player asks for a new
stream when you skip, so seeking still works.

Each viewer has at most one live conversion: starting a new one (another video, or
a skip) stops their previous ffmpeg, so a closed tab never holds the converter.
ffmpeg's complaints are kept per item and shown on the Server page.
"""
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time

from . import config, store

PROBE_VERSION = 4          # bump when probe() starts recording something new; older cache rows are re-read
_streams = {}
_streams_lock = threading.Lock()
_transcode_slots = None
_owners = {}            # viewer -> function that stops their current conversion
_errors = {}            # item id -> {"at", "message"}: the last thing ffmpeg complained about
_encoders = None


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


def encoders():
    """Names of the video/audio encoders this ffmpeg has (asked once)."""
    global _encoders
    if _encoders is None:
        exe, found = tool("ffmpeg"), set()
        if exe:
            try:
                out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
                found = {line.split()[1] for line in out.splitlines() if line.startswith(" ") and len(line.split()) > 1}
            except (OSError, subprocess.SubprocessError):
                pass
        _encoders = found
    return _encoders


def h264_args(height, live=True):
    """Encoder settings for H.264: the Mac's hardware encoder, or x264 elsewhere (Linux, old builds)."""
    from . import machine                         # measured: on an old Mac, x264 is often faster than VideoToolbox
    height = height or 720
    rate = "14M" if height > 1080 else "6M" if height > 720 else "3500k" if height > 480 else "2M"
    enc = encoders()
    best = machine.best_encoder()
    if best != "h264_videotoolbox" and "libx264" in enc:
        enc = {"libx264"}             # VideoToolbox only once it's checked: on some old Macs it makes damaged pictures
    if "h264_videotoolbox" in enc or not enc:
        args = ["-c:v", "h264_videotoolbox", "-allow_sw", "1"]
        if live:
            return args + ["-realtime", "1", "-b:v", rate, "-maxrate", "16M", "-bufsize", "24M"]
        return args + ["-q:v", "62"]
    if "libx264" in enc:
        if live:   # no "zerolatency": it turns off x264's frame threads, and a few frames of delay don't matter in 4 s segments
            return ["-c:v", "libx264", "-preset", "superfast" if machine.gentle() else "veryfast", "-crf", "21",
                    "-maxrate", "16M", "-bufsize", "24M"]
        return ["-c:v", "libx264", "-preset", "veryfast" if machine.gentle() else "medium", "-crf", "20"]
    return ["-c:v", "mpeg4", "-q:v", "3"]     # last resort: something every ffmpeg has


def hardware_encoder():
    return "h264_videotoolbox" in encoders()


def note_error(item_id, message):
    _errors[item_id] = {"at": int(time.time()), "message": message[-400:]}


def last_error(item_id):
    return _errors.get(item_id)


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
        out = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", "-show_chapters", path],
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
                        "index": s["index"], "profile": s.get("profile"), "pix_fmt": s.get("pix_fmt"),
                        "interlaced": s.get("field_order") not in (None, "progressive", "unknown")} for s in streams
                       if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None),
        "audio": [{"codec": s.get("codec_name"), "channels": s.get("channels"), "index": s["index"],
                   "lang": (s.get("tags") or {}).get("language"), "title": (s.get("tags") or {}).get("title"),
                   "default": (s.get("disposition") or {}).get("default")}
                  for s in streams if s.get("codec_type") == "audio"],
        "subs": [{"codec": s.get("codec_name"), "index": s["index"], "lang": (s.get("tags") or {}).get("language"),
                  "title": (s.get("tags") or {}).get("title")}
                 for s in streams if s.get("codec_type") == "subtitle"],
        "chapters": [{"start": float(c.get("start_time") or 0), "end": float(c.get("end_time") or 0),
                      "title": (c.get("tags") or {}).get("title") or ""} for c in raw.get("chapters") or []][:200],
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


def picture_subtitles(info):
    """Subtitle tracks stored as pictures (Blu-ray, DVD): [{"index", "label", "lang"}]. They're drawn onto the
    video when chosen."""
    out = []
    for s in (info or {}).get("subs", []):
        if s.get("codec") in IMAGE_SUBS:
            lang = s.get("lang") if s.get("lang") not in (None, "und") else None
            name = LANGS.get(lang, lang.upper()) if lang else "Subtitles"
            out.append({"index": s["index"], "lang": lang or "und",
                        "label": name + (" · " + s["title"] if s.get("title") and s["title"].lower() not in name.lower() else "")})
    return out


# ---------------------------------------------------------------- deciding how to play

BROWSER_PIX = (None, "yuv420p", "yuvj420p", "nv12")
DIRECT_AUDIO = (None, "aac", "mp3", "opus", "vorbis", "flac")


def default_audio(info, chosen=None):
    """The sound track to play: the one the viewer chose (by stream index), else the file's default."""
    audio = (info or {}).get("audio") or []
    if chosen is not None:
        pick = next((x for x in audio if x["index"] == chosen), None)
        if pick:
            return pick
    return next((x for x in audio if x.get("default")), audio[0]) if audio else None


LANGS = {"eng": "English", "spa": "Spanish", "fre": "French", "fra": "French", "ger": "German", "deu": "German",
         "ita": "Italian", "por": "Portuguese", "jpn": "Japanese", "kor": "Korean", "chi": "Chinese", "zho": "Chinese",
         "rus": "Russian", "dut": "Dutch", "nld": "Dutch", "swe": "Swedish", "dan": "Danish", "nor": "Norwegian",
         "fin": "Finnish", "pol": "Polish", "tur": "Turkish", "ara": "Arabic", "hin": "Hindi", "heb": "Hebrew",
         "gre": "Greek", "ell": "Greek", "cze": "Czech", "ces": "Czech", "hun": "Hungarian", "tha": "Thai"}


def audio_tracks(info):
    """Sound tracks for the player's menu: [{"index", "label", "lang", "default"}]."""
    out = []
    for i, a in enumerate((info or {}).get("audio") or []):
        lang = a.get("lang") if a.get("lang") not in (None, "und") else None
        ch = a.get("channels") or 0
        layout = "5.1" if ch == 6 else "7.1" if ch == 8 else "Stereo" if ch == 2 else "Mono" if ch == 1 else ""
        bits = [LANGS.get(lang, lang.upper()) if lang else "Track %d" % (i + 1), a.get("title") or "",
                " ".join(x for x in ((a.get("codec") or "").upper().replace("EAC3", "Dolby Digital+").replace("AC3", "Dolby Digital"),
                                     layout) if x)]
        label = bits[0] + "".join(" · " + b for b in bits[1:] if b and b.lower() not in bits[0].lower())
        out.append({"index": a["index"], "label": label, "lang": lang or "und", "default": a is default_audio(info)})
    return out


CAPS = ("mkv", "hevc", "hevc10", "ac3", "vp9")


def caps_from(qs):
    """A device's capabilities from a query string ("hevc=1&mkv=0…&maxh=720"). Only what it said: missing keys
    stay missing. maxh: the tallest picture it plays smoothly (a Raspberry Pi 3 box: 720 or 1080)."""
    caps = {k: (qs.get(k) or ["0"])[0] == "1" for k in CAPS if k in qs or k != "hevc10"}
    maxh = (qs.get("maxh") or [""])[0]
    if maxh.isdigit() and 240 <= int(maxh) <= 4320:
        caps["maxh"] = int(maxh)
    return caps


def ten_bit(video):
    return "10" in ((video or {}).get("pix_fmt") or "") or "10" in ((video or {}).get("profile") or "")


def video_playable(video, caps):
    """Can a browser with these capabilities decode this video stream?"""
    if not video:
        return True
    v = video.get("codec")
    if v == "h264":   # 10-bit and 4:2:2 H.264 ("Hi10P") decode in VLC but in no browser or TV
        return video.get("pix_fmt") in BROWSER_PIX and "10" not in (video.get("profile") or "")
    if v == "hevc":
        if ten_bit(video) and "hevc10" in caps:      # older apps don't say: then HEVC means both
            return bool(caps.get("hevc") and caps.get("hevc10"))
        return bool(caps.get("hevc"))
    if v in ("vp8", "vp9", "av1"):
        return bool(caps.get("vp9"))
    return False


def plan(item, caps):
    """How a device with these capabilities should play this item, and why (for the Server page)."""
    info = probe(item["path"])
    ext = item["ext"]
    container_ok = ext in ("mp4", "m4v", "mov") or (ext == "mkv" and caps.get("mkv")) or (ext == "webm" and caps.get("vp9"))
    if not info:
        mode = "transcode" if tool("ffmpeg") else ("direct" if container_ok else "unsupported")
        return {"mode": mode, "duration": None, "info": None, "why": ["the file couldn't be read ahead of time"]}
    video = info.get("video")
    a = (default_audio(info) or {}).get("codec")
    video_ok = video_playable(video, caps)
    too_tall = bool(caps.get("maxh") and video and (video.get("height") or 0) > caps["maxh"] * 1.1)
    if too_tall:
        video_ok = False
    audio_ok = a in DIRECT_AUDIO or (a in ("ac3", "eac3") and caps.get("ac3"))
    why = []
    if not container_ok:
        why.append(ext.upper() + " file")
    if too_tall:
        why.append("%sp picture (this device plays up to %sp)" % (video.get("height"), caps["maxh"]))
    elif not video_ok:
        why.append(describe_video(video) + " video")
    if not audio_ok:
        why.append((a or "unknown").upper() + " sound")
    if container_ok and video_ok and audio_ok:
        mode = "direct"
    elif not tool("ffmpeg"):
        mode = "unsupported"
    elif video_ok:
        mode = "remux"
    else:
        mode = "transcode"
    return {"mode": mode, "duration": info.get("duration"), "info": info, "why": why,
            "max_height": caps.get("maxh") if mode == "transcode" and caps.get("maxh") else None}


def describe_video(video):
    if not video:
        return "no"
    name = {"h264": "H.264", "hevc": "HEVC", "mpeg4": "XviD/DivX", "msmpeg4v3": "DivX 3", "mpeg2video": "MPEG-2",
            "vc1": "VC-1", "wmv3": "WMV", "av1": "AV1", "vp9": "VP9"}.get(video.get("codec"), (video.get("codec") or "?").upper())
    pix = video.get("pix_fmt") or ""
    if "10" in pix or "10" in (video.get("profile") or ""):
        name += " 10-bit"
    elif "444" in pix or "422" in pix:
        name += " 4:%s:%s" % (pix[4], pix[5])
    return name


def needs_conversion(item, caps=None):
    """True when the file won't play as-is on an ordinary browser or TV (so converting it once is worth it)."""
    return plan(item, caps or {"hevc": True})["mode"] != "direct"


# ---------------------------------------------------------------- live streams

LOOSE_TIMESTAMPS = ("avi", "mpg", "mpeg", "vob", "ts", "m2ts", "flv", "wmv", "divx", "3gp")


def live_size(video, max_height=None, others=0):
    """(height, kind) for converting this video while it plays. Someone's own choice (the player's Picture
    setting) is kept; otherwise 1080p, 720p in gentle mode, or smaller where this computer couldn't keep up
    with this kind of video before (machine.live_height), and a size smaller for each other video being
    converted for someone else right now (two at once share the computer)."""
    from . import machine
    src = (video or {}).get("height") or 720
    if max_height:
        return min(max_height, 1080, src), None
    kind = machine.live_kind(video)
    height = machine.live_height(kind, min(machine.max_live_height(), 1080, src))
    for _ in range(others):
        height = next((h for h in machine.LADDER if h < height), height)
    return height, kind


IMAGE_SUBS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}


def audio_args(audio, fmt, caps=None):
    """Sound for video Sofa adapts: as it is when the device plays it (AAC; Dolby Digital and Dolby Digital
    Plus on devices that take them, surround and all); surround from anything else (DTS, TrueHD, FLAC 5.1)
    as Dolby Digital Plus 5.1 for those devices; otherwise AAC stereo, which everything plays."""
    caps = caps or {}
    a, channels = (audio or {}).get("codec"), (audio or {}).get("channels") or 2
    dolby = caps.get("ac3") and fmt != "mp4"      # ffmpeg can't start a streamed MP4 with Dolby sound (HLS and TS are fine)
    if a == "aac" or (a == "mp3" and fmt != "hls") or (a in ("ac3", "eac3") and dolby):
        return ["-c:a", "copy"]
    smooth = ["-af", "aresample=async=1:first_pts=0"]
    if channels > 2 and dolby:
        return ["-c:a", "eac3", "-b:a", "640k", "-ac", "6"] + smooth
    return ["-c:a", "aac", "-b:a", "192k", "-ac", "2"] + smooth


def stream_command(item, mode, start, info, fmt="mp4", out="pipe:1", audio_index=None, max_height=None, caps=None,
                   burn=None, others=0):
    """The ffmpeg command for playing `item` from `start` seconds. `burn`: a picture-based subtitle track
    (Blu-ray PGS, DVD) to draw onto the video, since no player shows those from a converted stream."""
    exe = tool("ffmpeg")
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if item.get("ext") in LOOSE_TIMESTAMPS:
        cmd += ["-fflags", "+genpts+discardcorrupt"]   # AVI and MPEG often lack timestamps ffmpeg needs for MP4
    if start > 0:
        cmd += ["-ss", "%.3f" % start]
    if mode == "audio":   # music in a format the browser can't play: AAC in fragmented MP4
        return cmd + ["-i", item["path"], "-map", "0:a:0", "-vn", "-sn", "-dn", "-c:a", "aac", "-b:a", "256k",
                      "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", out]
    video = (info or {}).get("video") or {}
    audio = default_audio(info, audio_index)
    sub = next((x for x in (info or {}).get("subs") or [] if x["index"] == burn and x.get("codec") in IMAGE_SUBS), None)
    if sub and video.get("index") is not None:
        mode = "transcode"
    v_in = "0:%d" % video["index"] if video.get("index") is not None else "0:v:0?"
    cmd += ["-i", item["path"]]
    if mode == "remux":
        cmd += ["-map", v_in, "-c:v", "copy"] + (["-tag:v", "hvc1"] if video.get("codec") == "hevc" else [])
    else:
        top = live_size(video, max_height, others)[0]
        filters = (["yadif"] if video.get("interlaced") else []) + ["scale=-2:'min(ih,%d)'" % top, "format=yuv420p"]
        if sub:     # subtitles drawn on, from the bottom up (a cropped film keeps them in the picture)
            graph = "[0:%d][0:%d]overlay=x=(main_w-overlay_w)/2:y=main_h-overlay_h:eof_action=pass,%s[v]" % (
                video["index"], sub["index"], ",".join(filters))
            cmd += ["-filter_complex", graph, "-map", "[v]"]
        else:
            cmd += ["-map", v_in, "-vf", ",".join(filters)]
        cmd += h264_args(top) + ["-g", "48"]
    cmd += ["-map", "0:%d" % audio["index"] if audio else "0:a:0?", "-sn", "-dn"]
    cmd += audio_args(audio, fmt, caps)
    cmd += ["-max_muxing_queue_size", "4096", "-avoid_negative_ts", "make_zero"]
    if fmt == "mp4":
        cmd += ["-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", out]
    elif fmt == "mpegts":
        cmd += ["-f", "mpegts", out]
    else:   # hls: `out` is the session folder. fMP4 segments, so HEVC works on Apple devices too.
        cmd += ["-f", "hls", "-hls_time", "4", "-hls_list_size", "0", "-hls_playlist_type", "event",
                "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4",
                "-hls_flags", "independent_segments", "-hls_segment_filename", os.path.join(out, "seg%05d.m4s"),
                os.path.join(out, "index.m3u8")]
    return cmd


def _slot(mode):
    global _transcode_slots
    if _transcode_slots is None:
        _transcode_slots = threading.BoundedSemaphore(max(1, int(config.get("max_transcodes"))))
    slot = _transcode_slots if mode == "transcode" else None
    if slot and not slot.acquire(timeout=10):
        raise RuntimeError("busy")
    return slot


def _claim(owner, stop):
    """`owner` starts something new: stop whatever they were converting before."""
    if not owner:
        return
    with _streams_lock:
        old = _owners.get(owner)
        _owners[owner] = stop
    if old and old is not stop:
        old()


def _release(owner, stop):
    with _streams_lock:
        if owner and _owners.get(owner) is stop:
            del _owners[owner]


def _collect_stderr(proc, item):
    """Keep the last lines ffmpeg printed; record them if it failed on its own (not because we stopped it)."""
    tail = collections.deque(maxlen=8)

    def read():
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if line:
                tail.append(line)
        proc.stderr.close()
        code = proc.wait()
        if code not in (0, -9, -15, 255) and tail and not getattr(proc, "sofa_stopped", False):
            msg = " / ".join(tail)
            note_error(item["id"], msg)
            if item.get("adult"):
                store.log_private("playback", "A private video couldn't be converted for playing")
            else:
                store.log("playback", "Couldn't convert %s for playing: %s" % (item.get("title") or item["id"], tail[-1][:200]),
                          {"item": item["id"], "ffmpeg": msg[-600:]})
    threading.Thread(target=read, daemon=True, name="ffmpeg-stderr").start()


def _stop_proc(proc):
    proc.sofa_stopped = True
    try:
        proc.kill()
    except OSError:
        pass


def run_stream(item, mode, start, info, out, who, fmt="mp4", owner=None, audio_index=None, max_height=None, caps=None,
               burn=None):
    """Pipe ffmpeg's output to `out` until done, the viewer leaves, or they start something else."""
    holder = {}
    stop = lambda: holder.get("proc") and _stop_proc(holder["proc"])   # noqa: E731
    _claim(owner, stop)
    slot = _slot(mode)
    key = "%s-%s" % (id(out), time.time())
    try:
        proc = subprocess.Popen(stream_command(item, mode, start, info, fmt, audio_index=audio_index, max_height=max_height,
                                               caps=caps, burn=burn, others=_converting()), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0)
    except OSError:
        if slot:
            slot.release()
        _release(owner, stop)
        raise
    holder["proc"] = proc
    _collect_stderr(proc, item)
    with _streams_lock:
        _streams[key] = {**_shown(item), "mode": mode, "who": who,
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
        _stop_proc(proc)
        proc.wait()
        _release(owner, stop)
        with _streams_lock:
            _streams.pop(key, None)
        if slot:
            slot.release()


def _shown(item):
    """What the Server page's "Watching now" may say about an item: nothing for the Adult section."""
    if item.get("adult"):
        return {"item": None, "title": "something private"}
    return {"item": item["id"], "title": item.get("title")}


def note_direct(item, who):
    """Direct plays are short range requests; remember them briefly so the admin page can show them."""
    with _streams_lock:
        _streams["direct-%s-%s" % (who, item["id"])] = {**_shown(item), "mode": "direct",
                                                       "who": who, "started": int(time.time()), "direct": True}


def active_streams():
    now = time.time()
    with _streams_lock:
        for k in [k for k, v in _streams.items() if v.get("direct") and now - v["started"] > 120]:
            _streams.pop(k)
        return list(_streams.values())


def busy():
    """True while someone is watching something Sofa is converting live (background work waits)."""
    return any(not s.get("direct") for s in active_streams())


def overloaded():
    """The computer is working hard already (an old Mac converting a film for someone, say)."""
    try:
        return os.getloadavg()[0] > max(1.5, (os.cpu_count() or 2) * 0.8)
    except (OSError, AttributeError):
        return False


def should_wait():
    """Background extras (converting, previews, Skip Intro, downloads) wait for a quiet moment."""
    return busy() or overloaded()


# ---------------------------------------------------------------- HLS (every browser: natively on Apple, hls.js elsewhere)

_hls = {}
_hls_lock = threading.Lock()
HLS_IDLE = 90
HLS_FILE = re.compile(r"(index\.m3u8|init\.mp4|seg\d{5}\.(?:ts|m4s))")


def hls_dir():
    return os.path.join(config.DATA_DIR, "cache", "hls")


def _converting():
    """How many videos are being converted live for people right now."""
    with _streams_lock:
        return sum(1 for v in _streams.values() if v.get("mode") == "transcode" and not v.get("direct"))


def hls_start(item, mode, start, who, replace=None, owner=None, audio_index=None, max_height=None, caps=None, burn=None):
    """Start segmenting from `start` seconds. Returns a session id."""
    if replace:
        hls_stop(replace)
    info = probe(item["path"]) if not item["path"].startswith(("http://", "https://")) else None
    sid = hashlib.sha1(("%s|%s|%s" % (item["id"], start, time.time())).encode()).hexdigest()[:20]
    stop = lambda: hls_stop(sid)   # noqa: E731
    _claim(owner, stop)
    slot = _slot(mode)
    folder = os.path.join(hls_dir(), sid)
    os.makedirs(folder, exist_ok=True)
    if burn is not None and any(x["index"] == burn for x in picture_subtitles(info)):
        mode = "transcode"                           # drawing subtitles on means converting
    others = _converting()
    height, kind = live_size((info or {}).get("video"), max_height, others) if mode == "transcode" else (None, None)
    try:
        proc = subprocess.Popen(stream_command(item, mode, start, info, "hls", folder, audio_index=audio_index, max_height=height,
                                               caps=caps, burn=burn),
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError:
        if slot:
            slot.release()
        _release(owner, stop)
        raise
    _collect_stderr(proc, item)
    with _hls_lock:
        _hls[sid] = {"proc": proc, "dir": folder, "seen": time.time(), "slot": slot, "owner": owner, "stop": stop,
                     "started": time.time(), "kind": kind if not others else None, "height": height}   # shared: not learned from
    with _streams_lock:
        _streams["hls-" + sid] = {**_shown(item), "mode": mode, "who": who, "height": height,
                                  "started": int(time.time())}
    return sid


def _speed(s):
    """Seconds of video made per second spent converting (None until it's been going a while)."""
    playlist = os.path.join(s["dir"], "index.m3u8")
    try:
        # Finished: it took until the playlist's last change. Still going: until now.
        took = (os.path.getmtime(playlist) if s["proc"].poll() is not None else time.time()) - s["started"]
        if took < 20:
            return None
        with open(playlist, encoding="utf-8") as f:
            made = sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", f.read()))
    except (OSError, ValueError):
        return None
    return made / took


def hls_file(sid, name):
    """Path of a playlist/segment once ffmpeg has written it (waits up to 25s), else None."""
    if not HLS_FILE.fullmatch(name):
        return None
    with _hls_lock:
        s = _hls.get(sid)
        if s:
            s["seen"] = time.time()
    if not s:
        return None
    path = os.path.join(s["dir"], name)
    deadline = time.time() + 25
    while time.time() < deadline:
        if os.path.exists(path) and (name.endswith(".m3u8") or _segment_done(s, name)):
            return path
        if s["proc"].poll() is not None and not os.path.exists(path):
            return None
        time.sleep(0.2)
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
    if s.get("height"):                       # remember how well this went, for the next one like it
        from . import machine
        speed = _speed(s)
        if speed and s.get("kind"):
            machine.note_live_speed(s["kind"], s["height"], speed)
    _stop_proc(s["proc"])
    s["proc"].wait()
    if s["slot"]:
        s["slot"].release()
    _release(s["owner"], s["stop"])
    shutil.rmtree(s["dir"], ignore_errors=True)
    with _streams_lock:
        _streams.pop("hls-" + sid, None)


def hls_stop_owner(owner):
    with _hls_lock:
        mine = [sid for sid, s in _hls.items() if s["owner"] == owner]
    for sid in mine:
        hls_stop(sid)


def _hls_reaper():
    while True:
        time.sleep(30)
        with _hls_lock:
            idle = [sid for sid, s in _hls.items() if time.time() - s["seen"] > HLS_IDLE]
            running = [(sid, s) for sid, s in _hls.items() if s.get("height")]
        for sid in idle:
            hls_stop(sid)
        for sid, s in running:                  # for "Watching now": how far ahead of the viewer it keeps
            speed = _speed(s)
            with _streams_lock:
                if speed and "hls-" + sid in _streams:
                    _streams["hls-" + sid]["speed"] = round(speed, 1)


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


SIPS = "/usr/bin/sips"


def save_image(src, dest, max_width, fmt="jpeg"):
    """Write `src` (any image) to `dest` as JPEG or PNG, at most `max_width` px wide. True on success.

    On macOS this uses the system's own `sips`. Some ffmpeg builds (the one compiled for the
    2011 iMac among them) produce striped, purple JPEGs when they scale and encode in one step.
    """
    tmp = dest + ".part." + ("png" if fmt == "png" else "jpg")
    try:
        if os.access(SIPS, os.X_OK):
            out = subprocess.run([SIPS, "-g", "pixelWidth", src], capture_output=True, text=True, timeout=30).stdout
            width = int(re.search(r"pixelWidth:\s*(\d+)", out).group(1))
            cmd = [SIPS, "-s", "format", fmt] + (["-s", "formatOptions", "80"] if fmt == "jpeg" else [])
            if width > max_width:
                cmd += ["--resampleWidth", str(max_width)]
            subprocess.run(["nice", "-n", "10"] + cmd + [src, "--out", tmp], capture_output=True, timeout=60, check=True)
        else:
            exe = tool("ffmpeg")
            if not exe:
                return False
            cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", src,
                   "-vf", "scale='min(%d,iw)':-2" % max_width]
            cmd += ["-compression_level", "9"] if fmt == "png" else ["-q:v", "4"]
            subprocess.run(["nice", "-n", "10"] + cmd + [tmp], capture_output=True, timeout=60, check=True)
        if not os.path.getsize(tmp):
            raise OSError("empty image")
        os.replace(tmp, dest)
        return True
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def _grab(cmd_tail, path, dest, max_width):
    """Run ffmpeg to write one lossless PNG still, then turn it into the JPEG at `dest`."""
    exe = tool("ffmpeg")
    if not exe:
        return False
    still = dest + ".still.png"
    try:
        subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + cmd_tail(path) + [still],
                       capture_output=True, timeout=60, check=True)        # quiet: file names stay out of the log
        return os.path.exists(still) and save_image(still, dest, max_width)
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        if os.path.exists(still):
            os.remove(still)


def extract_art(path, dest):
    """Save a file's embedded cover picture (MP3/M4A/FLAC artwork) as a JPEG. True on success."""
    return _grab(lambda p: ["-i", p, "-map", "0:v:0", "-frames:v", "1"], path, dest, 800)


def extract_frame(path, dest, at=12.0):
    """A good still from a video, around `at` seconds: ffmpeg's thumbnail filter looks at about four
    seconds of frames and picks the most typical one, so no black frames, fades or motion blur."""
    def cmd(p):
        return ["-ss", "%.1f" % at, "-i", p, "-an", "-sn", "-vf", "thumbnail=96", "-frames:v", "1", "-update", "1"]
    return _grab(cmd, path, dest, 1280) or _grab(lambda p: ["-ss", "%.1f" % at, "-i", p, "-frames:v", "1"], path, dest, 1280)
