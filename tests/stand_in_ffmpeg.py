#!/usr/bin/env python3
"""A stand-in ffmpeg for computers with no graphics chip to convert with (GitHub's machines, a virtual machine).

It answers as an ffmpeg built with NVIDIA's, Intel's and AMD's encoders would, and behaves as a driver might: an
encoder can work, be missing, refuse one way of being asked, or stop in the middle of a video. A conversion asked
of a chip's encoder that "works" is really done, by the real ffmpeg with x264, so what Sofa gets back is real
video: the playlists, segments and files are the ones a player would be given.

What it proves: Sofa's side of the bargain (what it looks for, the commands it writes, which encoder it picks,
what it does when one fails). What it can't: that NVIDIA's, Intel's or AMD's own encoder takes those commands.
Only the hardware can say that.

    SOFA_STAND_IN=<settings.json> stand_in_ffmpeg.py <ffmpeg's arguments>

settings.json:
    real        the real ffmpeg
    has         encoders to add to `ffmpeg -encoders`           ["h264_nvenc", "h264_vaapi"]
    works       the ones whose conversions succeed               ["h264_nvenc"]
    refuses     per encoder, options its "driver" won't take     {"h264_nvenc": ["p4", "p5"]}
    stops       per encoder, stop by itself (exit 1) once the HLS playlist lists this many segments   {"h264_nvenc": 2}
    stops_now   per encoder, a file: while it exists, the encoder fails as it starts
    decode_cost seconds a decode on the processor takes longer than one on the chip (decode_helps' test)
    spoiled     part of a file's name: any conversion of that file fails, whoever is asked (a damaged file)
    log         a file every call's arguments are added to, one JSON list a line
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

CHIPS = ("h264_nvenc", "h264_qsv", "h264_vaapi", "h264_amf", "h264_videotoolbox")
WITH_VALUE = ("-allow_sw", "-realtime", "-rc", "-cq", "-global_quality", "-low_power", "-qp", "-usage", "-quality",
              "-qp_i", "-qp_p", "-vaapi_device", "-qsv_device", "-hwaccel", "-hwaccel_device")
ERRORS = {"h264_nvenc": "[h264_nvenc @ 0x5] Cannot load libnvidia-encode.so.1", "h264_qsv": "[h264_qsv @ 0x5] Error creating a MFX session: -9.",
          "h264_vaapi": "[AVHWDeviceContext @ 0x5] Failed to initialise VAAPI connection: -1 (unknown libva error).",
          "h264_amf": "[h264_amf @ 0x5] DLL amfrt64.dll failed to open", "h264_videotoolbox": "[h264_videotoolbox @ 0x5] Error: cannot create compression session"}


def main():
    with open(os.environ["SOFA_STAND_IN"], encoding="utf-8") as f:
        conf = json.load(f)
    real, args = conf["real"], sys.argv[1:]
    if conf.get("log"):
        with open(conf["log"], "a", encoding="utf-8") as f:
            f.write(json.dumps(args) + "\n")
    if "-encoders" in args:
        out = subprocess.run([real] + args, capture_output=True, text=True).stdout
        sys.stdout.write(out + "".join(" V....D %-20s a stand-in for the real one (codec h264)\n" % e for e in conf.get("has") or []))
        return 0
    if conf.get("spoiled") and any(conf["spoiled"] in a for a in args) and "-c:v" in args:
        sys.stderr.write("[matroska,webm @ 0x5] Invalid data found when processing input\n")
        return 1
    chip = next((args[i + 1] for i, a in enumerate(args[:-1]) if a == "-c:v" and args[i + 1] in CHIPS and args[i + 1] in (conf.get("has") or [])), None)
    if not chip:
        cost = conf.get("decode_cost")
        if cost and "-hwaccel" not in args and any(a.endswith("decode-check.mkv") for a in args) and "libx265" not in args:
            time.sleep(cost)                         # the processor, decoding: slower than the chip by this much
        return subprocess.run([real] + strip(args)).returncode
    gone = (conf.get("stops_now") or {}).get(chip)
    refused = [o for o in (conf.get("refuses") or {}).get(chip) or [] if o in args]
    if chip not in (conf.get("works") or []) or (gone and os.path.exists(gone)) or refused:
        sys.stderr.write((("[%s @ 0x5] Unable to parse option value \"%s\"" % (chip, refused[0])) if refused else ERRORS[chip]) + "\n")
        return 1
    cmd = strip(args)
    after = (conf.get("stops") or {}).get(chip)
    playlist = args[-1] if args[-1].endswith(".m3u8") else None
    if not after or not playlist:
        return subprocess.run([real] + cmd).returncode
    # a chip that stops in the middle: the conversion at a few times the speed video plays, until the playlist lists
    # `after` segments; then ffmpeg is killed and this exits as a driver that gave up would
    i = cmd.index("-i")
    proc = subprocess.Popen([real] + cmd[:i] + ["-readrate", "4"] + cmd[i:])
    while proc.poll() is None:
        try:
            with open(playlist, encoding="utf-8") as f:
                if len(re.findall(r"#EXTINF", f.read())) >= after:
                    break
        except OSError:
            pass
        time.sleep(0.05)
    if proc.poll() is None:
        proc.send_signal(signal.SIGKILL)
        proc.wait()
    sys.stderr.write("[%s @ 0x5] the device was lost\n" % chip)
    return 1


def strip(args):
    """The same conversion for the real ffmpeg and x264: the chip's own options out, its picture format back to the
    one x264 takes."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else None
        if a in WITH_VALUE:
            i += 2
            continue
        if a == "-b:v" and nxt == "0":
            i += 2
            continue
        if a == "-preset" and nxt in ("p4", "p5", "speed", "balanced"):
            i += 2
            continue
        if a == "-c:v" and nxt in CHIPS:
            out += ["-c:v", "libx264", "-preset", "ultrafast"]
            i += 2
            continue
        if a in ("-vf", "-filter_complex") and nxt:
            out += [a, nxt.replace("format=nv12,hwupload", "format=yuv420p").replace("format=nv12", "format=yuv420p")]
            i += 2
            continue
        out.append(a)
        i += 1
    return out


if __name__ == "__main__":
    sys.exit(main())
