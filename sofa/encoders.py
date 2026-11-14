"""Which H.264 encoder converts video on this computer: the graphics chip's when it has one that works, the
processor's (x264) otherwise.

The families:

    h264_videotoolbox   Apple's, on a Mac
    h264_nvenc          NVIDIA's (NVENC), on Linux and Windows
    h264_qsv            Intel Quick Sync, on Linux and Windows
    h264_vaapi          VA-API: Intel's and AMD's graphics on Linux
    h264_amf            AMD's (AMF), on Windows
    libx264             the processor, everywhere

Nothing here is guessed from a name or a model. What Sofa finds:

1. what this ffmpeg was built with (its encoder list);
2. what the system shows: the render nodes in /dev/dri with their maker and whether Sofa's user may open them,
   `nvidia-smi`, and on Windows the graphics adapters by maker;
3. a one-second test conversion with each encoder that could be here. Only one that passes is ever used.

Drivers and ffmpeg versions don't agree on an encoder's options, so each family has a short list of ways to ask
(VARIANTS), most particular first, plainest last; the test keeps the first that works here, once for video made
while someone watches and once for files converted for good. sofa/machine.py then times the ones that passed,
checks their pictures, and remembers the choice; media.py asks pick() for every conversion.

An encoder that fails on a real job (a driver's limit on conversions at once, a graphics reset, a device taken
away) rests for ten minutes and the job goes on with the processor; three failures with no success between and it
isn't used again until the next test (Server → Overview → This computer → Test the speed again, a new ffmpeg, a
new graphics chip, or a restart). A job that fails with the processor too wasn't the chip's fault (a damaged
file): that failure is taken back. Settings has one switch for all of it: `hardware_encoding`.

An ffmpeg with no x264 (one built with Apple's encoder alone) has nothing to go on with, so nothing here applies
to it: its one encoder is always used, as before.

Decoding stays on the processor unless this computer's own test shows the graphics chip decodes HEVC faster
(decode_helps): then HEVC sources, the heavy ones, are decoded there too.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from . import config, hardware, store, windows

SOFTWARE = "libx264"
HARDWARE = ("h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_vaapi", "h264_amf")
NAMES = {"h264_videotoolbox": "Apple VideoToolbox", "h264_nvenc": "NVIDIA NVENC", "h264_qsv": "Intel Quick Sync",
         "h264_vaapi": "VA-API", "h264_amf": "AMD AMF", "libx264": "x264"}
SHORT = {"h264_videotoolbox": "VideoToolbox", "h264_nvenc": "NVENC", "h264_qsv": "Quick Sync", "h264_vaapi": "VA-API",
         "h264_amf": "AMF", "libx264": "x264"}
MAKER = {"h264_nvenc": "NVIDIA", "h264_qsv": "Intel", "h264_amf": "AMD"}       # the adapter an encoder needs (Windows)
REST = 600                  # seconds an encoder rests after failing on a job
GIVE_UP = 3                 # failures in a row before it waits for the next test
ENOUGH = 75                 # frames a second of 1080p: two and a half times as fast as video plays (gentle mode's own line)
DECODE_GAIN = 1.25          # the graphics chip decodes HEVC this much faster than the processor, or it isn't used for it

# The options after `-c:v <encoder>`, for video made while someone watches ("live": steady, capped) and for files
# converted for good ("file": by quality). {rate} is the bit rate for the picture's size; {more} twice that.
VARIANTS = {
    "h264_videotoolbox": [
        {"live": ["-allow_sw", "1", "-realtime", "1", "-b:v", "{rate}", "-maxrate", "16M", "-bufsize", "24M"],
         "file": ["-allow_sw", "1", "-q:v", "62"]},
    ],
    "h264_nvenc": [
        {"live": ["-preset", "p4", "-rc", "vbr", "-cq", "23", "-b:v", "0", "-maxrate", "16M", "-bufsize", "24M"],
         "file": ["-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]},
        {"live": ["-preset", "fast", "-b:v", "{rate}", "-maxrate", "16M", "-bufsize", "24M"],      # before the p1-p7 presets
         "file": ["-preset", "medium", "-b:v", "{more}"]},
        {"live": ["-b:v", "{rate}"], "file": ["-b:v", "{more}"]},
    ],
    "h264_qsv": [
        {"live": ["-preset", "faster", "-b:v", "{rate}", "-maxrate", "16M", "-bufsize", "24M"],
         "file": ["-preset", "medium", "-global_quality", "21"]},
        {"live": ["-b:v", "{rate}"], "file": ["-b:v", "{more}"]},
    ],
    "h264_vaapi": [
        {"live": ["-b:v", "{rate}", "-maxrate", "16M", "-bufsize", "24M"], "file": ["-qp", "21"]},
        {"live": ["-low_power", "1", "-b:v", "{rate}", "-maxrate", "16M", "-bufsize", "24M"],     # chips with only the
         "file": ["-low_power", "1", "-qp", "21"]},                                               # low-power encoder
        {"live": ["-qp", "23"], "file": ["-qp", "21"]},
    ],
    "h264_amf": [
        {"live": ["-usage", "transcoding", "-quality", "speed", "-rc", "vbr_peak", "-b:v", "{rate}", "-maxrate", "16M",
                  "-bufsize", "24M"],
         "file": ["-usage", "transcoding", "-quality", "balanced", "-rc", "cqp", "-qp_i", "21", "-qp_p", "23"]},
        {"live": ["-b:v", "{rate}"], "file": ["-b:v", "{more}"]},
    ],
}

_lock = threading.Lock()
_fails = {}                 # encoder -> {"times": [when, ...], "why"}: failures on real jobs since it last worked
_found = {}                 # what the system shows (read once)


def _ffmpeg():
    from . import media
    return media.tool("ffmpeg")


def _has(name):
    from . import media
    return name in media.encoders()


def name(enc):
    return NAMES.get(enc, enc or "nothing")


# ---------------------------------------------------------------- what the system shows

def _nvidia():
    """{"name", "driver"} from `nvidia-smi` (there when NVIDIA's driver is, and in a container started with NVIDIA's
    runtime), else what /proc says of the driver, else None."""
    if hardware.ROOT:                       # (the tests' made-up /proc and /sys: never this computer's own tools)
        text = hardware._read("/proc/driver/nvidia/version")
        m = re.search(r"Kernel Module\s+([\d.]+)", text)
        return {"name": "NVIDIA graphics", "driver": m.group(1)} if m else None
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            out = subprocess.run([exe, "--query-gpu=name,driver_version", "--format=csv,noheader"], capture_output=True,
                                 text=True, timeout=8)
            line = (out.stdout or "").strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
            if line:
                parts = [p.strip() for p in line.split(",")]
                return {"name": parts[0], "driver": parts[1] if len(parts) > 1 else ""}
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    m = re.search(r"Kernel Module\s+([\d.]+)", hardware._read("/proc/driver/nvidia/version"))
    return {"name": "NVIDIA graphics", "driver": m.group(1)} if m else None


def render_nodes():
    """Linux's render nodes: [{"node": "/dev/dri/renderD128", "maker": "Intel", "open": True}]. "open": Sofa's user may
    read and write it (in a container: the device was passed in, and the user is in the group that owns it)."""
    out = []
    try:
        nodes = sorted(n for n in os.listdir(hardware.ROOT + "/dev/dri") if n.startswith("renderD"))
    except OSError:
        return out
    for n in nodes:
        vendor = hardware._read("/sys/class/drm/%s/device/vendor" % n).strip()
        path = "/dev/dri/" + n
        out.append({"node": path, "maker": hardware.GPU_VENDORS.get(vendor, vendor or "unknown"),
                    "open": os.access(hardware.ROOT + path, os.R_OK | os.W_OK)})
    return out


def found(force=False):
    """What the system shows of its graphics, before anything is tried: {"system", "nodes", "nvidia", "adapters"}."""
    with _lock:
        if force or not _found:
            system = "linux" if hardware.ROOT else ("windows" if windows.ON else "mac" if sys.platform == "darwin" else "linux")
            _found.clear()
            _found.update(system=system, nodes=render_nodes() if system == "linux" else [],
                          nvidia=_nvidia() if system != "mac" else None,
                          adapters=windows.gpus() if system == "windows" else [])
        return dict(_found)


def signature():
    """A line that changes when the graphics do (a card added, a driver updated, a device passed to the container),
    so the test is run again then."""
    f = found()
    return "|".join(["%s:%s:%d" % (n["node"], n["maker"], n["open"]) for n in f["nodes"]]
                    + (["nvidia:%s:%s" % (f["nvidia"]["name"], f["nvidia"]["driver"])] if f["nvidia"] else [])
                    + ["%s:%s" % (a.get("name"), a.get("driver")) for a in f["adapters"]])


def candidates():
    """[(encoder, device or None)]: the hardware encoders worth a test here, in the order they're tried. One this
    ffmpeg has, on a system that shows the hardware it needs. On Linux every render node Sofa may open gets its own
    VA-API try, whoever made the chip: the test decides, not the maker's name."""
    f = found()
    out = []
    if f["system"] == "mac":
        return [("h264_videotoolbox", None)] if _has("h264_videotoolbox") else []
    if f["system"] == "linux":
        nodes = [n for n in f["nodes"] if n["open"]]
        nvidia = f["nvidia"] or any(n["maker"] == "NVIDIA" for n in f["nodes"]) or os.path.exists(hardware.ROOT + "/dev/nvidia0")
        if _has("h264_nvenc") and nvidia:
            out.append(("h264_nvenc", None))
        if _has("h264_qsv"):
            out += [("h264_qsv", n["node"]) for n in nodes if n["maker"] == "Intel"][:1]
        if _has("h264_vaapi"):
            out += [("h264_vaapi", n["node"]) for n in nodes]
        return out
    makers = {a.get("maker") for a in f["adapters"] if a.get("maker")}
    for enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
        if _has(enc) and (not makers or MAKER[enc] in makers or (enc == "h264_nvenc" and f["nvidia"])):
            out.append((enc, None))            # (no adapter list at all: each is simply tried)
    return out


def closed_nodes():
    """Render nodes that are there but not open to Sofa's user: the one thing a person has to fix by hand."""
    return [n["node"] for n in found()["nodes"] if not n["open"]]


# ---------------------------------------------------------------- an encoder's command line

def rate(height):
    height = height or 720
    return "14M" if height > 1080 else "6M" if height > 720 else "3500k" if height > 480 else "2M"


def _more(r):
    n, unit = re.match(r"(\d+)(\D+)", r).groups()
    return "%d%s" % (int(n) * 2, unit)


def before_input(enc, how=None):
    """ffmpeg's own options an encoder needs ahead of the inputs: which device it is."""
    device = (how or {}).get("device")
    if enc == "h264_vaapi":
        return ["-vaapi_device", device or "/dev/dri/renderD128"]
    if enc == "h264_qsv" and device:
        return ["-qsv_device", device]
    return []


def last_filters(enc):
    """How the filter chain ends: the picture in the form the encoder takes. VA-API wants it sent to the chip
    (hwupload); the others take it from memory."""
    if enc == "h264_vaapi":
        return ["format=nv12", "hwupload"]
    if enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
        return ["format=nv12"]
    return ["format=yuv420p"]


def codec(enc, height, live=True, how=None):
    """`-c:v <encoder>` and its options, in the way that passed this computer's test (`how`: {"live": n, "file": n})."""
    ways = VARIANTS[enc]
    n = (how or {}).get("live" if live else "file") or 0
    r = rate(height)
    return ["-c:v", enc] + [a.format(rate=r, more=_more(r)) for a in ways[min(n, len(ways) - 1)]["live" if live else "file"]]


def decode_before_input(enc, how=None):
    """The input options that decode on the graphics chip an encoder is on (frames come back to memory, so every
    filter still works). ffmpeg goes back to the processor by itself for a stream the chip can't decode."""
    device = (how or {}).get("device")
    if enc == "h264_videotoolbox":
        return ["-hwaccel", "videotoolbox"]
    if enc == "h264_nvenc":
        return ["-hwaccel", "cuda"]
    if enc in ("h264_vaapi", "h264_qsv") and found()["system"] == "linux":
        return ["-hwaccel", "vaapi", "-hwaccel_device", device or "/dev/dri/renderD128"]
    if enc in ("h264_qsv", "h264_amf"):
        return ["-hwaccel", "d3d11va"]
    return []


# ---------------------------------------------------------------- the one-second test

def _run(cmd, timeout=40):
    """(ok, ffmpeg's last complaint)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        return False, "it took too long"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)[:160]
    lines = [l.strip() for l in (r.stderr or "").splitlines() if l.strip()]
    return r.returncode == 0, (lines[-1][:200] if lines else "")


def test_command(enc, how, live, seconds=1, size="1280x720", fps=30, out=None):
    exe = _ffmpeg()
    height = int(size.split("x")[1])
    return ([exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + before_input(enc, how)
            + ["-f", "lavfi", "-i", "testsrc2=size=%s:rate=%d" % (size, fps), "-t", str(seconds),
               "-vf", ",".join(last_filters(enc))] + codec(enc, height, live, how)
            + (["-f", "null", "-"] if out is None else [out]))


def probe(enc, device=None):
    """Try the encoder for one second, each way it can be asked. {"ok", "live", "file", "device", "why"}: the first way
    that works for video made while someone watches and for files; "why" is ffmpeg's last line when none does."""
    if not _ffmpeg() or enc not in VARIANTS:
        return {"ok": False, "why": "no ffmpeg"}
    how = {"device": device} if device else {}
    got, why = {}, ""
    for kind in ("live", "file"):
        for n in range(len(VARIANTS[enc])):
            ok, said = _run(test_command(enc, dict(how, **{kind: n}), kind == "live"))
            if ok:
                got[kind] = n
                break
            why = said or why
        if kind not in got:
            return dict(how, ok=False, why=why or "it didn't start")
    return dict(how, ok=True, why="", **got)


def decode_helps(enc, how, folder):
    """True when this computer's graphics chip decodes 1080p 10-bit HEVC well faster than its processor, and the
    pictures are the same. Tried with a four-second clip made here (libx265), each way three times and the quickest
    kept (one run is mostly noise: another program busy for a moment tips it); without that encoder, not tried and
    not used."""
    args = decode_before_input(enc, how)
    exe = _ffmpeg()
    if not args or not exe or not _has("libx265"):
        return False
    os.makedirs(folder, exist_ok=True)
    clip = os.path.join(folder, "decode-check.mkv")
    try:
        ok, _ = _run([exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                      "testsrc2=size=1920x1080:rate=30", "-t", "4", "-c:v", "libx265", "-preset", "ultrafast",
                      "-x265-params", "log-level=error", "-pix_fmt", "yuv420p10le", clip], timeout=180)
        if not ok:
            return False

        def timed(extra):
            best = None
            for _ in range(3):
                started = time.time()
                ok, _said = _run([exe, "-hide_banner", "-loglevel", "error", "-nostdin"] + extra
                                 + ["-i", clip, "-vf", "format=yuv420p", "-f", "null", "-"], timeout=120)
                if not ok:
                    return None
                best = min(best or 1e9, time.time() - started)
            return best
        chip, cpu = timed(args), timed([])
        if not chip or not cpu or cpu / chip < DECODE_GAIN:
            return False
        # the same pictures, whichever decoded them (a chip that draws lines across its video is never used for it)
        r = subprocess.run([exe, "-hide_banner", "-nostdin"] + args + ["-i", clip, "-i", clip, "-lavfi",
                            "[0:v]format=yuv420p[a];[1:v]format=yuv420p[b];[a][b]psnr=shortest=1", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=120, errors="replace")
        m = re.search(r"PSNR .*average:([\d.]+|inf)", r.stderr or "")
        return bool(m) and (m.group(1) == "inf" or float(m.group(1)) >= 40)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    finally:
        if os.path.exists(clip):
            os.remove(clip)


# ---------------------------------------------------------------- failures on real jobs

def failed(enc, why=""):
    """A conversion with this encoder stopped by itself. It rests; the job goes on with the processor."""
    if enc not in HARDWARE:
        return
    with _lock:
        f = _fails.setdefault(enc, {"times": []})
        f["times"].append(time.time())
        f["why"] = (why or "")[:200]
        count = len(f["times"])
    store.log("settings", "%s stopped while converting a video%s. %s" % (
        name(enc), (": " + why[:160]) if why else "",
        "It isn't used again until this computer is tested again (Server → Overview → This computer)." if count >= GIVE_UP
        else "Sofa carries on with the processor, and tries it again in ten minutes."))


def worked(enc):
    with _lock:
        _fails.pop(enc, None)


def forgiven(enc):
    """The job failed with the processor as well: it wasn't the chip (a damaged file, a missing one). Its last
    failure is taken back."""
    with _lock:
        f = _fails.get(enc)
        if f:
            f["times"].pop()
            if not f["times"]:
                del _fails[enc]


def resting(enc):
    """True while an encoder that failed on a job isn't to be used."""
    with _lock:
        f = _fails.get(enc)
        return bool(f) and (len(f["times"]) >= GIVE_UP or time.time() - f["times"][-1] < REST)


def fallback(enc):
    """The encoder a job goes on with when `enc`, a chip's, gives up: the processor's. None when `enc` isn't a
    chip's, or this ffmpeg has no x264: then there's nothing to carry on with, and a failure is just a failure."""
    return SOFTWARE if enc in HARDWARE and _has(SOFTWARE) else None


def forget_failures():
    with _lock:
        _fails.clear()


def failures():
    """{encoder: {"count", "at", "why"}} for the ones that failed since they last worked."""
    with _lock:
        return {k: {"count": len(v["times"]), "at": v["times"][-1], "why": v.get("why") or ""} for k, v in _fails.items()}


# ---------------------------------------------------------------- the choice

def allowed():
    """The household's switch: use the graphics chip for converting (on unless turned off)."""
    return config.get("hardware_encoding") is not False


def choose(speeds, damaged=()):
    """The encoder to use, from what the test measured ({encoder: frames a second of 1080p, or None}). A graphics
    chip's that makes whole pictures and converts comfortably faster than video plays (ENOUGH) is used, the fastest
    of them: it leaves the processor to everything else. Otherwise whichever is fastest, the processor included."""
    working = {k: v for k, v in speeds.items() if v and k not in damaged}
    if not working:
        return None
    chips = {k: v for k, v in working.items() if k in HARDWARE and v >= ENOUGH}
    return max(chips, key=chips.get) if chips else max(working, key=working.get)


def pick(software=False):
    """The encoder for one conversion, starting now: the measured choice, unless it's switched off, resting after a
    failure, or the caller needs the processor (`software`: a job being done again after the chip gave up)."""
    from . import machine
    best = machine.best_encoder()
    if not software and best in HARDWARE and allowed() and not resting(best) and _has(best):
        return best
    if _has(SOFTWARE):
        return SOFTWARE
    if not software and _has("h264_videotoolbox"):
        return "h264_videotoolbox"          # an ffmpeg built with Apple's encoder alone: the only way there is (its
    return None                             # software side, `-allow_sw`, converts where the chip can't); no switch takes it away

