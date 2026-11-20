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
    return {"devices": devices(), "job": j or None}


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
        cmd += ["-t", str(minutes * 60 if minutes else 6 * 3600), "-vf", "yadif=deint=interlaced,format=yuv420p"] + \
            media.h264_args(480, live=True) + ["-c:a", "aac", "-b:a", "192k", "-ac", "2", "-metadata", "title=" + full, "-f", "matroska", stage]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _job.clear()
        _job.update(id=uuid.uuid4().hex[:10], name=full, device=found["name"], state="working", started=time.time(),
                    minutes=minutes, stage=stage, dest=dest, error=None, proc=proc, stopping=False)
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


def _wait(job, who):
    proc = job["proc"]
    err = proc.stderr.read().decode("utf-8", "replace")
    code = proc.wait()
    state, error = "done", None
    seconds = time.time() - job["started"]
    ok = os.path.exists(job["stage"]) and os.path.getsize(job["stage"]) > 100000
    if not ok:
        state = "failed"
        error = ("The capture device gave nothing to record: is the player on, playing, and plugged in to it? (%s)" %
                 ((err.strip().splitlines() or ["no reason given"])[-1][:160]))
    elif code not in (0, 255) and not job["stopping"] and seconds < job["minutes"] * 60 - 30:
        error = "The recording stopped early (the device went away?). What was recorded is kept."
    if ok:
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
