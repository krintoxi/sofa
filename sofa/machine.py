"""What this computer can do, so Sofa fits it: four x86-64 cores without AVX2 and ten Apple silicon cores get different settings.

Once (and again when ffmpeg or the graphics change), Sofa finds the H.264 encoders that work here and times a short
1080p conversion with each: the graphics chip's (Apple's VideoToolbox, NVIDIA's NVENC, Intel's Quick Sync, VA-API on
Intel's and AMD's graphics, AMD's AMF: sofa/encoders.py) and the processor's (x264). A chip's encoder is only timed
after a one-second conversion with it has worked, and is used when it makes whole pictures and converts comfortably
faster than video plays; otherwise the fastest one is, the processor included. Old Macs running a newer macOS often
have no working hardware encoder, and x264 is then the better choice. It also checks that the pictures come out
right: on old Macs with patched graphics (OpenCore), VideoToolbox can make video with purple or green lines across
it, and is then never used.

Gentle mode (automatic on slow computers, or set under Server → Settings):
- video converted while someone watches is 720p at most,
- heavy background work (converting files to MP4, hover previews and scrubbing pictures made ahead
  of time, finding intros) waits for the quiet hours (1:00-7:00 by default). Whatever someone is
  watching right now is still done straight away.
"""
import json
import os
import platform
import re
import subprocess
import threading
import time

from . import config, encoders, media, store, windows

CACHE = os.path.join(config.DATA_DIR, "cache", "machine.json")
TEST_SECONDS, TEST_FPS = 4, 30
_lock = threading.Lock()
_result = {}


def describe():
    """CPU model, the cores Sofa may use, memory, and whether the CPU can convert video quickly (hardware.py: on
    Intel and AMD, AVX2, from about 2013; on ARM, a Cortex-A76 or newer, Apple's, a server's: a Pi 3's or a Pi 4's
    cores are too slow, a Pi 5's aren't). ARM was all "old" here before (only AVX2 was looked for), so gentle mode
    was on for a Pi 5, an ARM server and Docker on a Mac with Apple silicon."""
    from . import hardware
    d = hardware.describe()
    return {"cpu": d["cpu"], "cores": d["cores"], "memory": d["memory"],
            "modern_cpu": None if d["slow_cores"] is None else not d["slow_cores"],
            "system": "%s %s" % (platform.system(), platform.mac_ver()[0] or platform.release())}


def _time_encoder(name, how=None):
    """Frames per second for a 1080p test conversion with this encoder, or None if it doesn't work here."""
    exe = media.tool("ffmpeg")
    if name == "h264_videotoolbox":          # (without -allow_sw: a Mac with no hardware encoder must fail here)
        args = ["-vf", "format=yuv420p", "-c:v", "h264_videotoolbox", "-realtime", "1", "-b:v", "6M"]
    elif name == "libx264":
        args = ["-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-crf", "21"]
    else:
        args = ["-vf", ",".join(encoders.last_filters(name))] + encoders.codec(name, 1080, True, how)
    cmd = ([exe, "-hide_banner", "-loglevel", "error", "-nostdin"] + encoders.before_input(name, how)
           + ["-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=%d" % TEST_FPS, "-t", str(TEST_SECONDS)] + args + ["-f", "null", "-"])
    started = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return round(TEST_SECONDS * TEST_FPS / max(0.01, time.time() - started), 1)


def _damaged(name, how=None):
    """True when this encoder's pictures don't match what went in (lines, smears): it's then not used."""
    exe = media.tool("ffmpeg")
    if name == "h264_videotoolbox":
        args = ["-vf", "format=yuv420p", "-c:v", "h264_videotoolbox", "-allow_sw", "1", "-b:v", "8M"]
    elif name == "libx264":
        args = ["-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]
    else:                                   # (a 1080p picture's bit rate for a 720p one: what's lost is the encoder's fault)
        args = ["-vf", ",".join(encoders.last_filters(name))] + encoders.codec(name, 1080, True, how)
    source = "testsrc2=size=1280x720:rate=25"
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = os.path.join(os.path.dirname(CACHE), "encoder-check-%s.mp4" % name)
    try:
        subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + encoders.before_input(name, how)
                       + ["-f", "lavfi", "-i", source, "-t", "2"] + args + [tmp], capture_output=True, timeout=120, check=True)
        r = subprocess.run([exe, "-hide_banner", "-nostdin", "-i", tmp, "-f", "lavfi", "-i", source, "-lavfi",
                            "[0:v]format=yuv420p,settb=1/25,setpts=N[a];[1:v]format=yuv420p,settb=1/25,setpts=N[b];"
                            "[a][b]psnr=shortest=1", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return True
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    m = re.search(r"PSNR .*average:([\d.]+|inf) min:([\d.]+|inf)", r.stderr or "")
    if not m:
        return False                  # couldn't compare (an old ffmpeg): trust it
    avg, low = [float("inf") if v == "inf" else float(v) for v in m.groups()]
    return avg < 33 or low < 28            # good encoders: about 38-45; one thin line across the picture: about 32


def _key():
    """What the remembered test belongs to: this ffmpeg, and these graphics (a card added, a driver updated or a
    device passed to the container: tested again)."""
    exe = media.tool("ffmpeg") or ""
    try:
        return "3|%s|%d|%s" % (exe, os.path.getmtime(exe), encoders.signature())
    except OSError:
        return "3|%s|%s" % (exe, encoders.signature())


def _said(speeds, tried, damaged):
    out = []
    for k in list(speeds) + [k for k in tried if k not in speeds]:
        v = speeds.get(k)
        out.append("%s %s" % (encoders.name(k), "makes damaged pictures here" if k in damaged else ("%s frames/s" % v) if v
                              else "doesn't work here"))
    return ", ".join(out) or "no H.264 encoder"


def measure(force=False):
    """Find the encoders that work (a one-second try each), time them (once per ffmpeg and set of graphics) and
    remember which to use."""
    with _lock:
        if not force:
            try:
                with open(CACHE, encoding="utf-8") as f:
                    saved = json.load(f)
                if saved.get("key") == _key():
                    _result.update(saved)
                    return dict(_result)
            except (OSError, ValueError):
                pass
        if not media.tool("ffmpeg"):
            return {}
        encoders.found(force=True)
        encoders.forget_failures()
        enc = media.encoders()
        tried = {}                          # hardware encoder -> how it was asked, or why it doesn't work here
        for name, device in encoders.candidates():
            if tried.get(name, {}).get("ok"):
                continue                    # (a second render node: the first that works is the one)
            tried[name] = encoders.probe(name, device)
        how = {k: {x: v[x] for x in ("live", "file", "device") if x in v} for k, v in tried.items() if v.get("ok")}
        speeds = {name: _time_encoder(name, how.get(name)) for name in list(how) + [encoders.SOFTWARE]
                  if name in enc and (name in how or name == encoders.SOFTWARE)}
        for name in tried:
            speeds.setdefault(name, None)
        damaged = [name for name, v in speeds.items() if v and _damaged(name, how.get(name))]
        best = encoders.choose(speeds, damaged)
        decode = bool(best in encoders.HARDWARE and encoders.decode_helps(best, how.get(best), os.path.dirname(CACHE)))
        _result.clear()
        _result.update(key=_key(), at=int(time.time()), speeds=speeds, best=best, damaged=damaged, how=how, decode=decode,
                       why={k: v.get("why") or "" for k, v in tried.items() if not v.get("ok")})
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump(_result, f)
        except OSError:
            pass
        store.log("settings", "Tested this computer's video conversion: %s. Using %s%s." % (
            _said(speeds, tried, damaged), encoders.name(best) if best else "the fallback",
            ", and the graphics chip to decode HEVC" if decode else ""))
        return dict(_result)


def _remembered():
    if not _result:
        try:
            with open(CACHE, encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("key") == _key():
                _result.update(saved)
        except (OSError, ValueError):
            pass
    return _result


def best_encoder():
    """The H.264 encoder the test chose, once measured (None until then: media falls back to its usual choice)."""
    return _remembered().get("best")


def how(name):
    """The way an encoder was asked when it passed its test here: {"live": n, "file": n, "device": ...}."""
    return (_remembered().get("how") or {}).get(name) or {}


def decodes(name):
    """True when the graphics chip `name` is on decodes HEVC faster than the processor here (measured)."""
    r = _remembered()
    return bool(r.get("decode")) and r.get("best") == name


def gentle():
    """Gentle mode: "auto" (on for slow computers), or on/off from Server → Settings."""
    setting = config.get("gentle")
    if setting in (True, False):
        return setting
    d = describe_cached()
    speeds = [v for v in (_result.get("speeds") or {}).values() if v]
    slow_encode = bool(speeds) and max(speeds) < 75          # can't convert 1080p comfortably faster than real time
    return d.get("modern_cpu") is False or (d.get("cores") or 1) <= 2 or slow_encode


_described = {}


def describe_cached():
    if not _described:
        _described.update(describe())
    return _described


def max_live_height():
    return 720 if gentle() else 1080


def quiet_now():
    """Inside the quiet hours (for heavy background work in gentle mode)."""
    try:
        a, b = (config.get("quiet_hours") or "01:00-07:00").split("-")
        start, end = [int(x.split(":")[0]) * 60 + int(x.split(":")[1]) for x in (a, b)]
    except (ValueError, IndexError):
        start, end = 60, 420
    now = time.localtime()
    m = now.tm_hour * 60 + now.tm_min
    return start <= m < end if start < end else (m >= start or m < end)


def heavy_ok():
    """May heavy background work start now? Always on a capable computer; in gentle mode only in the quiet hours."""
    return not gentle() or quiet_now()


# What converting while someone watches really manages here. A 1080p HEVC 10-bit episode can be too much
# for an old Mac at 720p (it then keeps stopping to wait for the next part), so Sofa remembers how fast
# each kind of video converted, and next time picks the tallest picture it can make faster than it plays.

LIVE = os.path.join(config.DATA_DIR, "cache", "live-speed.json")
LADDER = (1080, 720, 540, 360)
SMOOTH = 1.25               # this much faster than the video plays: no waiting, even on a busy evening
FORGET = 7 * 86400          # try the bigger picture again after a week (other things may have been running)
_live_lock = threading.Lock()
_live = {}


def _live_table():
    if not _live:
        try:
            with open(LIVE, encoding="utf-8") as f:
                saved = json.load(f)
            _live.update(saved if saved.get("key") == _key() else {})
        except (OSError, ValueError):
            pass
        _live.setdefault("key", _key())
        _live.setdefault("kinds", {})
    return _live


def live_kind(video):
    """"hevc10-1080|libx264|gentle": the source (codec, bit depth, size) and how it's converted here."""
    h = (video or {}).get("height") or 720
    size = min((2160, 1080, 720, 480, 360), key=lambda b: abs(b - h))
    return "%s%s-%d|%s%s" % ((video or {}).get("codec") or "?", "10" if media.ten_bit(video) else "", size,
                             encoders.pick() or "x264", "|gentle" if gentle() else "")


def note_live_speed(kind, height, speed):
    """A live conversion of this kind at this height made `speed` seconds of video per second."""
    if not kind or not speed:
        return
    with _live_lock:
        t = _live_table()["kinds"].setdefault(kind, {})
        old = t.get(str(height))
        if old and time.time() - old["at"] < FORGET:
            speed = (old["speed"] + speed) / 2
        t[str(height)] = {"speed": round(speed, 2), "at": int(time.time())}
        try:
            os.makedirs(os.path.dirname(LIVE), exist_ok=True)
            with open(LIVE, "w", encoding="utf-8") as f:
                json.dump(_live, f)
        except OSError:
            pass


def live_height(kind, top):
    """The tallest picture, up to `top`, that this kind of video converted smoothly at (or hasn't been tried at)."""
    with _live_lock:
        seen = dict(_live_table()["kinds"].get(kind) or {})
    for h in [top] + [h for h in LADDER if h < top]:
        s = seen.get(str(h))
        if not s or time.time() - s["at"] > FORGET or s["speed"] >= SMOOTH:
            return h
    return min(top, LADDER[-1])


def status():
    from . import hardware
    d = dict(describe_cached())
    hw = hardware.describe()
    d.update(board=hw["pi"] or hw["virtual"], video=hw["video"], cpu_count=hw["cpu_count"])
    _remembered()                                 # (what the last test found, before this start's own has run)
    d.update(speeds=_result.get("speeds") or {}, best=_result.get("best"), measured=_result.get("at"), damaged=_result.get("damaged") or [],
             gentle=gentle(), gentle_setting=config.get("gentle"), quiet_hours=config.get("quiet_hours") or "01:00-07:00",
             quiet_now=quiet_now(), max_live_height=max_live_height())
    # the graphics chip: what was found, each encoder that was tried and what came of it, the one in use now, the switch
    fails = encoders.failures()
    d.update(closed=encoders.closed_nodes(), why=_result.get("why") or {},
             names=dict(encoders.NAMES), hardware=[k for k in (_result.get("speeds") or {}) if k in encoders.HARDWARE],
             hardware_encoding=encoders.allowed(), using=encoders.pick(), decode=bool(_result.get("decode")),
             resting={k: {"count": v["count"], "why": v.get("why") or "", "until_test": v["count"] >= encoders.GIVE_UP}
                      for k, v in fails.items() if encoders.resting(k)})
    with _live_lock:
        d["live"] = {k: dict(v) for k, v in _live_table()["kinds"].items()}
    return d


def report(test=False):
    """What Sofa converts video with here, in lines for people (`python3 sofa.py encoders`, which tests first)."""
    from . import hardware
    if test:
        measure(force=True)
    r = _remembered()
    lines = ["This computer: " + hardware.summary()]
    f = encoders.found()
    for n in f["nodes"]:
        lines.append("Graphics: %s, %s%s" % (n["node"], n["maker"], "" if n["open"] else
                                             " (not open to this user: add it to the group that owns the node)"))
    if f["nvidia"]:
        lines.append("Graphics: %s%s" % (f["nvidia"]["name"], ", driver " + f["nvidia"]["driver"] if f["nvidia"].get("driver") else ""))
    for a in f["adapters"]:
        lines.append("Graphics: %s" % a.get("name"))
    if not media.tool("ffmpeg"):
        return lines + ["No ffmpeg: nothing is converted."]
    lines.append("ffmpeg %s, with: %s" % (media.ffmpeg_version(), ", ".join(
        encoders.name(e) for e in list(encoders.HARDWARE) + [encoders.SOFTWARE] if e in media.encoders()) or "no H.264 encoder"))
    why, damaged = r.get("why") or {}, r.get("damaged") or []
    for k, v in (r.get("speeds") or {}).items():
        lines.append("  %-20s %s" % (encoders.name(k), "makes damaged pictures here: not used" if k in damaged
                                     else "%s frames a second of 1080p" % v if v
                                     else "doesn't work here" + (" (%s)" % why[k] if why.get(k) else "")))
    using = encoders.pick()
    lines.append("Converting with: %s%s" % (
        "%s (the graphics chip)" % encoders.name(using) if using in encoders.HARDWARE and (r.get("speeds") or {}).get(using)
        else "x264 (the processor)" if using == encoders.SOFTWARE else encoders.name(using) if using else "nothing: no H.264 encoder",
        "" if encoders.allowed() else " (the graphics chip is switched off in Settings)"))
    if r.get("decode"):
        lines.append("HEVC is decoded by the graphics chip too: it measured faster here.")
    return lines


def start():
    if not config.get("machine_test"):
        return

    def run():
        time.sleep(45)                    # after the library's first read
        try:
            measure()
        except Exception as exc:
            store.log("error", "Testing this computer's video conversion: %s" % exc)
    threading.Thread(target=run, daemon=True, name="machine-test").start()
