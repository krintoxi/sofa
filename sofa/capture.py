"""Record from a capture device: what a DVD player (or a VCR, a camcorder) plays, into the library.

A USB video capture stick takes a player's analog picture and sound (the yellow composite plug or S-video, and the
red and white sound) and gives them to the computer as a camera and a microphone would. Sofa records that input as
it plays, in real time, to an MKV in Movies, named from the disc's page. Nothing on the disc is read or decrypted:
the player plays it, as it would to a TV, and Sofa records what comes out. The picture is standard definition, there
is one sound track, and no subtitles or chapters unless the player draws them.

Some discs send an analog copy signal (Macrovision) that makes some capture sticks show a flickering or darkening
picture. Sofa records what the stick gives it and does nothing about that signal.

Inputs, by the computer's own way of listing them (ffmpeg reads each):
  Linux (a Sofa Box)   video4linux devices (/dev/video0...), their sound from ALSA
  Mac                  AVFoundation (a Mac asks once whether Sofa may use a camera: a capture stick is one)
  Windows              DirectShow
The computer's own cameras and screens are left out of the list.

It looks after itself: while it records, ffmpeg says when the picture stands still (a black or blue screen, the
player's menu or "no disc" picture, a paused film) and when the sound goes quiet. A still picture and silence for a
while after the film has run means it has ended: Sofa stops, and trims the still part off the end, and the black or
still part before the film started off the beginning (`film_range`). So: press Record, then Play on the player, and
walk away.

What to buy (`HARDWARE`, shown in the guide): a USB 2.0 video capture stick that works without drivers ("UVC", or
"driver-free"/"plug and play" for Mac, Windows and Linux), with a yellow composite input and, better, an S-video one,
and stereo red and white sound inputs. They cost about $15 to $30. Not an HDMI capture stick: a DVD player's HDMI
output is encrypted (HDCP), so such a stick shows nothing, and getting round that isn't allowed either.
"""
import os
import re
import subprocess
import sys
import threading
import time
import uuid

from . import config, fileops, media, naming, store

LEAVE_OUT = re.compile(r"facetime|built-?in|isight|desk view|iphone|ipad|capture screen|screen \d|integrated|webcam|"
                       r"virtual|obs |snap camera|continuity", re.I)
HARDWARE = {
    "stick": "A USB 2.0 video capture stick (\"USB video grabber\") that works without drivers: look for \"UVC\", or "
             "\"driver-free\" or \"plug and play\" for Mac, Windows and Linux. About $15 to $30.",
    "inputs": "It needs a yellow video input (composite) and red and white sound inputs. One with an S-video input too gives a "
              "sharper picture, if the player has S-video.",
    "cable": "The yellow, red and white cable (\"RCA\" or \"AV\" cable) most DVD players come with, or an S-video cable and the "
             "red and white one.",
    "player": "Any DVD player with yellow (or S-video) and red and white outputs. Most have them; some newer ones only have HDMI.",
    "not": "Not an HDMI capture stick: a DVD player's HDMI output is encrypted (HDCP), so the stick shows nothing, and getting "
           "round that isn't allowed.",
}
STILL = 90                  # seconds of a still picture and quiet after the film: it has ended
TEST = "test"               # SOFA_CAPTURE=test: a made picture and tone in place of a device (the tests, the pictures)
_lock = threading.Lock()
_job = {}                   # the recording, while there is one (and the last one, after)


def _run(cmd, timeout=10):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return out.stdout + out.stderr
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_avfoundation(text):
    """ffmpeg -f avfoundation -list_devices true: ([(index, name)] video, [(index, name)] audio)."""
    video, audio, at = [], [], None
    for line in text.splitlines():
        if "AVFoundation video devices" in line:
            at = video
        elif "AVFoundation audio devices" in line:
            at = audio
        else:
            m = re.search(r"\]\s*\[(\d+)\]\s*(.+?)\s*$", line)
            if m and at is not None:
                at.append((m.group(1), m.group(2)))
    return video, audio


def parse_dshow(text):
    """ffmpeg -f dshow -list_devices true: ([name] video, [name] audio)."""
    video, audio = [], []
    for line in text.splitlines():
        m = re.search(r'"([^"]+)"\s*\((video|audio)\)', line)
        if m:
            (video if m.group(2) == "video" else audio).append(m.group(1))
    return video, audio


def _alsa_cards(path="/proc/asound/cards"):
    """[(card id, name)] of the sound cards (a capture stick is one)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    return re.findall(r"^\s*\d+\s+\[(\w+)\s*\]:\s*[^-]*-\s*(.+?)\s*$", text, re.M)


def _like(a, b):
    words = lambda s: {w for w in re.findall(r"[a-z0-9]{3,}", s.lower()) if w not in ("usb", "video", "audio", "device")}
    return bool(words(a) & words(b))


def devices(sysfs="/sys/class/video4linux"):
    """The capture inputs: [{"id", "name", "audio": the sound input that goes with it, or None}]."""
    if os.environ.get("SOFA_CAPTURE") == TEST:
        return [{"id": TEST, "name": "Test picture", "audio": TEST}]
    exe = media.tool("ffmpeg")
    out = []
    if sys.platform == "darwin" and exe:
        video, audio = parse_avfoundation(_run([exe, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]))
        for i, name in video:
            if LEAVE_OUT.search(name):
                continue
            sound = next((a for a in audio if _like(a[1], name)), None)
            out.append({"id": "av:%s" % i, "name": name, "audio": "av:%s" % sound[0] if sound else None})
    elif os.name == "nt" and exe:
        video, audio = parse_dshow(_run([exe, "-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"]))
        for name in video:
            if LEAVE_OUT.search(name):
                continue
            sound = next((a for a in audio if _like(a, name)), None)
            out.append({"id": "ds:" + name, "name": name, "audio": "ds:" + sound if sound else None})
    else:
        try:
            nodes = sorted(n for n in os.listdir(sysfs) if re.match(r"^video\d+$", n))
        except OSError:
            nodes = []
        cards = _alsa_cards()
        for n in nodes:
            def read(name):
                try:
                    with open(os.path.join(sysfs, n, name), encoding="utf-8", errors="replace") as f:
                        return f.read().strip()
                except OSError:
                    return ""
            name = read("name") or n
            if read("index") not in ("", "0") or LEAVE_OUT.search(name) or re.search(r"bcm2835|codec|isp|hevc|rpi|unicam", name, re.I):
                continue                                    # (a device's second node, the Pi's own video blocks)
            card = next((c for c in cards if _like(c[1], name)), None) or (cards[-1] if len(cards) > 1 and "usb" in cards[-1][1].lower() else None)
            out.append({"id": "v4l:/dev/" + n, "name": name, "audio": "alsa:hw:CARD=%s" % card[0] if card else None})
    return out


def _inputs(device, audio):
    """ffmpeg's input options for a device and its sound."""
    if device == TEST:
        return ["-re", "-f", "lavfi", "-i", "testsrc=size=720x480:rate=30000/1001", "-re", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    if device.startswith("av:"):
        return ["-f", "avfoundation", "-framerate", "29.97", "-video_size", "720x480", "-i",
                "%s:%s" % (device[3:], audio[3:] if audio and audio.startswith("av:") else "none")]
    if device.startswith("ds:"):
        return ["-f", "dshow", "-rtbufsize", "64M", "-i", "video=%s" % device[3:] + (":audio=%s" % audio[3:] if audio and audio.startswith("ds:") else "")]
    if device.startswith("v4l:"):
        args = ["-f", "v4l2", "-thread_queue_size", "512", "-i", device[4:]]
        if audio and audio.startswith("alsa:"):
            args += ["-f", "alsa", "-thread_queue_size", "1024", "-ac", "2", "-i", audio[5:]]
        return args
    raise ValueError("Which capture device?")


EVENT = re.compile(r"\b(black_start|black_end|freeze_start|freeze_end|silence_start|silence_end)\s*:\s*(-?\d+(?:\.\d+)?)")


def events(text):
    """What ffmpeg's detectors said, in order: [(kind, seconds)]."""
    return [(m.group(1), float(m.group(2))) for m in EVENT.finditer(text or "")]


def film_range(evts, total):
    """(start, end) of the film in a recording `total` seconds long: past a black or still picture it began with (the
    player's start, its menu, "press play"), and up to the still picture or black it ended on (the menu again, the
    player's own screen), when that runs to the end."""
    start, end = 0.0, float(total)
    opened = {}
    spans = []                                           # (kind, start, end or None)
    for kind, t in evts:
        what, edge = kind.split("_")
        if edge == "start":
            opened[what] = t
        elif what in opened:
            spans.append((what, opened.pop(what), t))
    for what, t in opened.items():
        spans.append((what, t, None))
    for what, a, b in spans:
        if what in ("black", "freeze") and a <= 1.0 and b and b < total - 1:
            start = max(start, b)                       # (it began on a still or black picture)
    for what, a, b in spans:
        if what in ("black", "freeze") and b is None and a > start + 5:
            end = min(end, a)                           # (it ended on one, to the end)
    return max(0.0, start - 0.5), min(float(total), end + 1.0)


def status():
    with _lock:
        j = dict(_job)
    j.pop("proc", None)
    if j.get("state") == "working":
        j["seconds_done"] = int(time.time() - j["started"])
        try:
            j["size"] = os.path.getsize(j["stage"])
        except (OSError, KeyError):
            j["size"] = 0
    j.pop("stage", None)
    j.pop("said", None)
    return {"devices": devices(), "job": j or None, "hardware": HARDWARE}


def preview(device):
    """A look through the capture device before recording: {"picture": JPEG bytes or None, "moving": a picture that
    isn't one colour, "sound": the loudest it got in dB, or None}. About two seconds."""
    found = next((d for d in devices() if d["id"] == device), None)
    if not found:
        raise ValueError("That capture device isn't plugged in now.")
    with _lock:
        if _job.get("state") == "working":
            raise ValueError("It's recording now.")
    import tempfile
    folder = tempfile.mkdtemp(prefix="sofa-look-")
    shot = os.path.join(folder, "look.jpg")
    cmd = [media.tool("ffmpeg"), "-v", "info", "-y"] + [x for x in _inputs(device, found.get("audio")) if x != "-re"]
    vmap, amap = "0:v:0", ("1:a:0" if device == TEST or (found.get("audio") or "").startswith("alsa:") else "0:a:0?")
    cmd += ["-t", "2", "-map", vmap, "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG,scale=480:-2", "-update", "1", "-q:v", "4", shot,
            "-t", "2", "-map", amap, "-af", "volumedetect", "-f", "null", "-"]
    try:
        run = subprocess.run(cmd, capture_output=True, timeout=20)
        text = run.stderr.decode("utf-8", "replace")
        picture = open(shot, "rb").read() if os.path.exists(shot) else None
    except (OSError, subprocess.SubprocessError):
        text, picture = "", None
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
    peak = re.findall(r"max_volume:\s*(-?[\d.]+) dB", text)
    ys = [float(x) for x in re.findall(r"YAVG=([\d.]+)", text)]
    return {"picture": picture, "moving": bool(ys) and 12 < sum(ys) / len(ys) < 245, "sound": float(peak[-1]) if peak else None,
            "said": "" if picture else (text.strip().splitlines() or [""])[-1][:200]}


def start(device, name, year="", minutes=0, who="someone"):
    """Record `device` for `minutes` (to the end of the film, from the disc's length; 0: until stopped, six hours at
    most) into Movies/<Name (Year)>/. Raises ValueError with a plain reason."""
    found = next((d for d in devices() if d["id"] == device), None)
    if not found:
        raise ValueError("That capture device isn't plugged in now.")
    if not media.tool("ffmpeg"):
        raise ValueError("Sofa needs ffmpeg to record, and it isn't installed on this computer.")
    name = naming.safe_filename(str(name or "").strip())[:120].strip(" .")
    if not name:
        raise ValueError("Give it a name.")
    year = str(year or "").strip()
    if year and not re.match(r"^(19|20)\d\d$", year):
        raise ValueError("The year looks like 1999.")
    try:
        minutes = max(0, min(360, int(float(minutes or 0))))
    except (TypeError, ValueError):
        raise ValueError("How long is a number of minutes.")
    full = "%s (%s)" % (name, year) if year else name
    from . import disc
    folder = os.path.join(disc._root("movies"), full)
    dest = os.path.join(folder, full + ".mkv")
    if os.path.lexists(dest):
        raise ValueError("%s is already there. Sofa doesn't write over a file." % full)
    disc._room(folder, (minutes or 180) * 60 * 450000)      # (about 3.5 Mbit/s, sound included)
    with _lock:
        if _job.get("state") == "working":
            raise ValueError("Something is being recorded already.")
        os.makedirs(folder, exist_ok=True)
        stage = os.path.join(folder, ".sofa-capture-%s.mkv" % uuid.uuid4().hex[:8])
        cmd = [media.tool("ffmpeg"), "-v", "error", "-y"] + _inputs(device, found.get("audio")) + ["-map", "0:v:0"]
        cmd += ["-map", "1:a:0"] if device == TEST or (found.get("audio") or "").startswith("alsa:") else (["-map", "0:a:0?"])
        cmd += ["-t", str(minutes * 60 if minutes else 6 * 3600),
                "-vf", "yadif=deint=interlaced,format=yuv420p,blackdetect=d=2:pix_th=0.10,freezedetect=n=0.003:d=%d" % min(STILL, 20),
                "-af", "silencedetect=n=-45dB:d=%d" % min(STILL, 20), "-g", "48"] + \
            media.h264_args(480, live=True) + ["-c:a", "aac", "-b:a", "192k", "-ac", "2", "-metadata", "title=" + full, "-f", "matroska", stage]
        cmd[cmd.index("-v") + 1] = "info"               # (the detectors speak at "info")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _job.clear()
        _job.update(id=uuid.uuid4().hex[:10], name=full, device=found["name"], state="working", started=time.time(),
                    minutes=minutes, stage=stage, dest=dest, error=None, proc=proc, stopping=False, ended=None, said="", picture=None)
        job = dict(_job)
    threading.Thread(target=_wait, args=(job, who), daemon=True, name="capture").start()
    return {"ok": True, "name": full}


def stop():
    """Stop recording now and keep what was recorded (pressed when the film ends)."""
    with _lock:
        proc = _job.get("proc") if _job.get("state") == "working" else None
        if proc:
            _job["stopping"] = True
    if not proc:
        return False
    try:
        proc.stdin.write(b"q")                             # (ffmpeg's own "stop": the file is finished properly)
        proc.stdin.flush()
    except OSError:
        proc.terminate()
    return True


def _listen(job):
    """What ffmpeg says while it records: kept, and a film that has ended (a still picture and quiet for a while, after
    some minutes of film) stops the recording."""
    proc, said = job["proc"], []
    for raw in iter(proc.stderr.readline, b""):
        line = raw.decode("utf-8", "replace")
        if EVENT.search(line) or "rror" in line:
            said.append(line.strip())
        with _lock:
            if _job.get("id") != job["id"]:
                continue
            _job["said"] = "\n".join(said[-400:])
            ev = events(_job["said"])
            now = time.time() - job["started"]
            fz = [(k, t) for k, t in ev if k.startswith("freeze")]
            sl = [k for k, _ in ev if k.startswith("silence")]
            freeze_open = bool(fz) and fz[-1][0] == "freeze_start"
            still = fz[-1][1] if freeze_open else None
            quiet_open = sl[-1:] == ["silence_start"]
            _job["picture"] = "still" if freeze_open else "moving"
            if still is not None and quiet_open and now > 300 and now - still > STILL and not _job["stopping"]:
                _job["ended"] = still
                _job["stopping"] = True
                try:
                    proc.stdin.write(b"q")
                    proc.stdin.flush()
                except OSError:
                    pass
    return "\n".join(said)


def _trim(job, said, seconds):
    """Cut the still or black part before and after the film off the recording (no picture is converted again)."""
    a, b = film_range(events(said), seconds)
    if a < 2 and b > seconds - 2:
        return None
    out = job["stage"] + ".trim.mkv"
    run = subprocess.run([media.tool("ffmpeg"), "-v", "error", "-y", "-ss", "%.2f" % a, "-i", job["stage"], "-t", "%.2f" % (b - a),
                          "-map", "0", "-c", "copy", "-f", "matroska", out], capture_output=True, timeout=3600)
    if run.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 100000:
        os.replace(out, job["stage"])
        return (a, b)
    if os.path.exists(out):
        os.unlink(out)
    return None


def _wait(job, who):
    proc = job["proc"]
    err = _listen(job)
    code = proc.wait()
    state, error = "done", None
    seconds = time.time() - job["started"]
    ok = os.path.exists(job["stage"]) and os.path.getsize(job["stage"]) > 100000
    if not ok:
        state = "failed"
        error = ("The capture device gave nothing to record: is the player on, playing, and plugged in to it? (%s)" %
                 ((err.strip().splitlines() or ["no reason given"])[-1][:160]))
    elif code not in (0, 255) and not _job.get("stopping") and seconds < job["minutes"] * 60 - 30:
        error = "The recording stopped early (the device went away?). What was recorded is kept."
    if ok:
        trimmed = _trim(job, err, seconds)
        if trimmed:
            with _lock:
                if _job.get("id") == job["id"]:
                    _job["trimmed"] = [round(trimmed[0]), round(trimmed[1])]
        try:
            fileops.place(job["stage"], job["dest"])
        except FileExistsError:
            state, error = "failed", "A file with that name appeared meanwhile. Sofa doesn't write over a file: the recording is in %s." % job["stage"]
    else:
        try:
            os.unlink(job["stage"])
        except OSError:
            pass
        try:
            os.rmdir(os.path.dirname(job["dest"]))
        except OSError:
            pass
    with _lock:
        if _job.get("id") == job["id"]:
            _job.update(state=state, error=error, finished=time.time(), seconds=int(seconds), proc=None)
    store.log("disc", ("Recorded %s from %s" % (job["name"], job["device"])) if state == "done" else
              "Recording %s stopped: %s" % (job["name"], error), {"by": who})
    if state == "done":
        from . import disc
        if disc.saved:
            threading.Thread(target=disc._tell, daemon=True).start()
