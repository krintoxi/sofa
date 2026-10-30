"""What this computer can do, so Sofa fits it: a 2011 iMac and a new Mac mini get different settings.

Once (and again when ffmpeg changes), Sofa times a short 1080p conversion with each H.264 encoder
this ffmpeg has (Apple's VideoToolbox, x264) and uses the faster one. Old Macs running a newer macOS
often have no working hardware encoder, and x264 is then the better choice. It also checks that the
pictures come out right: on old Macs with patched graphics (OpenCore), VideoToolbox can make video
with purple or green lines across it, and is then never used.

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

from . import config, media, store

CACHE = os.path.join(config.DATA_DIR, "cache", "machine.json")
TEST_SECONDS, TEST_FPS = 4, 30
_lock = threading.Lock()
_result = {}


def _sysctl(name):
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def describe():
    """CPU model, cores, memory and whether the CPU is from before ~2013 (no AVX2)."""
    cpu, avx2 = platform.processor() or "", None
    if platform.system() == "Darwin":
        cpu = _sysctl("machdep.cpu.brand_string") or cpu
        if platform.machine() == "arm64":
            avx2 = True                                   # Apple silicon: modern
        else:
            flags = (_sysctl("machdep.cpu.leaf7_features") + " " + _sysctl("machdep.cpu.features")).upper()
            avx2 = "AVX2" in flags
        mem = int(_sysctl("hw.memsize") or 0)
    else:
        try:
            with open("/proc/cpuinfo") as f:
                text = f.read()
            m = re.search(r"model name\s*:\s*(.+)", text)
            cpu = m.group(1).strip() if m else cpu
            avx2 = " avx2" in text
        except OSError:
            pass
        try:
            mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (ValueError, OSError, AttributeError):
            mem = 0
    return {"cpu": re.sub(r"\s+", " ", cpu or "unknown"), "cores": os.cpu_count() or 1, "memory": mem,
            "modern_cpu": avx2, "system": "%s %s" % (platform.system(), platform.mac_ver()[0] or platform.release())}


def _time_encoder(name):
    """Frames per second for a 1080p test conversion with this encoder, or None if it doesn't work here."""
    exe = media.tool("ffmpeg")
    args = {"h264_videotoolbox": ["-c:v", "h264_videotoolbox", "-realtime", "1", "-b:v", "6M"],
            "libx264": ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-crf", "21"]}[name]
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi", "-i",
           "testsrc2=size=1920x1080:rate=%d" % TEST_FPS, "-t", str(TEST_SECONDS), "-vf", "format=yuv420p"] + args + ["-f", "null", "-"]
    started = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return round(TEST_SECONDS * TEST_FPS / max(0.01, time.time() - started), 1)


def _damaged(name):
    """True when this encoder's pictures don't match what went in (lines, smears): it's then not used."""
    exe = media.tool("ffmpeg")
    args = {"h264_videotoolbox": ["-c:v", "h264_videotoolbox", "-allow_sw", "1", "-b:v", "8M"],
            "libx264": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]}[name]
    source = "testsrc2=size=1280x720:rate=25"
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = os.path.join(os.path.dirname(CACHE), "encoder-check-%s.mp4" % name)
    try:
        subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", source, "-t", "2",
                        "-vf", "format=yuv420p"] + args + [tmp], capture_output=True, timeout=120, check=True)
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
    exe = media.tool("ffmpeg") or ""
    try:
        return "2|%s|%d" % (exe, os.path.getmtime(exe))
    except OSError:
        return "2|" + exe


def measure(force=False):
    """Time the encoders (once per ffmpeg) and remember which is faster."""
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
        enc = media.encoders()
        speeds = {name: _time_encoder(name) for name in ("h264_videotoolbox", "libx264") if name in enc}
        damaged = [name for name, v in speeds.items() if v and _damaged(name)]
        working = {k: v for k, v in speeds.items() if v and k not in damaged}
        best = max(working, key=working.get) if working else None
        _result.clear()
        _result.update(key=_key(), at=int(time.time()), speeds=speeds, best=best, damaged=damaged)
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump(_result, f)
        except OSError:
            pass
        store.log("settings", "Tested this computer's video conversion: %s. Using %s." % (
            ", ".join("%s %s" % ({"h264_videotoolbox": "Apple VideoToolbox", "libx264": "x264"}[k],
                                 "makes damaged pictures here" if k in damaged else ("%s frames/s" % v) if v else "doesn't work")
                      for k, v in speeds.items()) or "no H.264 encoder", {"h264_videotoolbox": "VideoToolbox", "libx264": "x264"}.get(best, "the fallback")))
        return dict(_result)


def best_encoder():
    """The H.264 encoder to use, once measured (None until then: media falls back to its usual choice)."""
    if not _result:
        try:
            with open(CACHE, encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("key") == _key():
                _result.update(saved)
        except (OSError, ValueError):
            pass
    return _result.get("best")


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


def status():
    d = dict(describe_cached())
    d.update(speeds=_result.get("speeds") or {}, best=_result.get("best"), measured=_result.get("at"), damaged=_result.get("damaged") or [],
             gentle=gentle(), gentle_setting=config.get("gentle"), quiet_hours=config.get("quiet_hours") or "01:00-07:00",
             quiet_now=quiet_now(), max_live_height=max_live_height())
    return d


def start():
    def run():
        time.sleep(45)                    # after the library's first read
        try:
            measure()
        except Exception as exc:
            store.log("error", "Testing this computer's video conversion: %s" % exc)
    threading.Thread(target=run, daemon=True, name="machine-test").start()
