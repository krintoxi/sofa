#!/usr/bin/env python3
"""Convert videos browsers can't play (MKV, AVI, WMV, ...) into web-ready MP4.

    convert.py PATH [PATH ...]                 convert files/folders on this machine
    convert.py --remote media-server PATH ...      convert files that live on another machine
                                               (pulls each file over SSH, converts here, pushes the MP4 back)

Each file is probed first. H.264/HEVC video and AAC audio are copied as-is (a
"remux": fast, no quality loss); anything else is re-encoded to H.264 + AAC.
Text subtitles are saved next to the MP4 as .vtt files. The new MP4 is checked
(same length as the original) before the original is touched.

Originals are moved to a "Converted originals" folder at the top of the given
path (or --originals DIR) unless --delete-originals is passed. Needs ffmpeg and ffprobe where it runs;
the remote side only needs ssh and a POSIX shell.
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

CONVERT_EXT = {".mkv", ".avi", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".m2ts", ".vob", ".divx", ".webm", ".ogv", ".3gp"}
COPY_VIDEO = {"h264"}            # browsers everywhere
COPY_VIDEO_HEVC = {"hevc"}       # Safari/Chrome on newer Macs; re-encode with --no-hevc
COPY_AUDIO = {"aac"}
TEXT_SUBS = {"subrip", "ass", "ssa", "webvtt", "mov_text", "text"}
ORIGINALS = "Converted originals"


def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def tool(name):
    for d in ("/opt/homebrew/bin", "/usr/local/bin"):
        p = os.path.join(d, name)
        if os.access(p, os.X_OK):
            return p
    p = shutil.which(name)
    if not p:
        sys.exit("%s not found. Install it with: brew install ffmpeg" % name)
    return p


FFMPEG, FFPROBE = tool("ffmpeg"), tool("ffprobe")


def probe(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def duration(info):
    try:
        return float(info["format"]["duration"])
    except (KeyError, ValueError):
        return 0.0


def has_encoder(name):
    out = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return (" " + name + " ") in out


def build_command(src, dst, info, args):
    streams = info["streams"]
    video = [s for s in streams if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    if not video:
        raise ValueError("no video stream")
    v = video[0]
    vcodec = v.get("codec_name")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-stats", "-y", "-i", src, "-map", "0:%d" % v["index"]]
    for a in audio:
        cmd += ["-map", "0:%d" % a["index"]]
    plan = []
    if vcodec in COPY_VIDEO or (vcodec in COPY_VIDEO_HEVC and not args.no_hevc):
        cmd += ["-c:v", "copy"]
        if vcodec == "hevc":
            cmd += ["-tag:v", "hvc1"]
        plan.append("copy " + vcodec)
    else:
        if has_encoder("h264_videotoolbox") and not args.software:
            cmd += ["-c:v", "h264_videotoolbox", "-q:v", str(args.quality), "-allow_sw", "1"]
            plan.append("encode %s -> h264 (hardware, q%d)" % (vcodec, args.quality))
        else:
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf)]
            plan.append("encode %s -> h264 (x264, crf %d)" % (vcodec, args.crf))
        cmd += ["-pix_fmt", "yuv420p", "-profile:v", "high"]
    for i, a in enumerate(audio):
        if a.get("codec_name") in COPY_AUDIO:
            cmd += ["-c:a:%d" % i, "copy"]
            plan.append("copy aac")
        else:
            ch = min(int(a.get("channels") or 2), 6)
            cmd += ["-c:a:%d" % i, "aac", "-b:a:%d" % i, "%dk" % (64 * ch if ch > 2 else 192), "-ac:a:%d" % i, str(ch)]
            plan.append("encode %s -> aac" % a.get("codec_name"))
    cmd += ["-map_metadata", "0", "-map_chapters", "0", "-movflags", "+faststart", "-f", "mp4", dst]
    return cmd, ", ".join(plan)


def extract_subs(src, dst_mp4, info):
    """Save text subtitle tracks as <name>.<lang>.vtt next to the MP4. Returns the paths written."""
    written = []
    base = os.path.splitext(dst_mp4)[0]
    subs = [s for s in info["streams"] if s["codec_type"] == "subtitle" and s.get("codec_name") in TEXT_SUBS]
    for n, s in enumerate(subs):
        lang = (s.get("tags") or {}).get("language") or "und"
        name = "%s.%s%s.vtt" % (base, lang, "" if n == 0 else "." + str(n))
        try:
            run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-map", "0:%d" % s["index"], "-c:s", "webvtt", name])
            written.append(name)
        except subprocess.CalledProcessError:
            log("  could not extract subtitle track %d, skipping it" % s["index"])
    return written


def convert_file(src, dst, args):
    """Convert src to dst (both local). Returns list of extra files written (subtitles)."""
    info = probe(src)
    cmd, plan = build_command(src, dst + ".part", info, args)
    log("  %s" % plan)
    if args.dry_run:
        return []
    nice = ["nice", "-n", "10"] if shutil.which("nice") else []
    run(nice + cmd)
    out = probe(dst + ".part")
    d_in, d_out = duration(info), duration(out)
    if d_in and abs(d_in - d_out) > max(2.0, d_in * 0.005):
        os.remove(dst + ".part")
        raise RuntimeError("length check failed: original %.1fs, MP4 %.1fs" % (d_in, d_out))
    os.replace(dst + ".part", dst)
    subs = [] if args.no_subs else extract_subs(src, dst, info)
    return subs


def find_local(paths):
    for p in paths:
        if os.path.isfile(p):
            yield os.path.abspath(p), os.path.dirname(os.path.abspath(p))
            continue
        top = os.path.abspath(p)
        for d, dirs, files in os.walk(top):
            dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x != ORIGINALS)
            for f in sorted(files):
                if os.path.splitext(f)[1].lower() in CONVERT_EXT and not f.startswith("._"):
                    yield os.path.join(d, f), top


def originals_path(src, top, args):
    return os.path.join(args.originals or os.path.join(top, ORIGINALS), os.path.relpath(src, top))


def retire_local(src, top, args):
    if args.delete_originals:
        os.remove(src)
        return "deleted"
    dest = originals_path(src, top, args)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.replace(src, dest)
    return "moved to " + os.path.relpath(dest, top)


# ---------- remote mode: files live on another machine reachable over ssh ----------

def ssh(host, command, capture=True):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", host, command], check=True,
                          capture_output=capture, text=True).stdout


def pull(host, remote, local):
    with open(local, "wb") as f:
        run(["ssh", "-o", "BatchMode=yes", host, "cat " + shlex.quote(remote)], stdout=f)


def push(host, local, remote):
    with open(local, "rb") as f:
        run(["ssh", "-o", "BatchMode=yes", host, "cat > " + shlex.quote(remote)], stdin=f)


def find_remote(host, paths):
    exts = " -o ".join("-iname '*%s'" % e for e in sorted(CONVERT_EXT))
    for p in paths:
        target = '"$HOME"/' + shlex.quote(p[2:]) if p.startswith("~/") else shlex.quote(p)
        single = ssh(host, "test -f %s && cd \"$(dirname %s)\" && echo \"$(pwd)/$(basename %s)\" || true" % (
            target, target, target)).strip()
        if single:
            yield single, os.path.dirname(single)
            continue
        top = ssh(host, "cd %s && pwd" % target).strip()
        out = ssh(host, "find %s -name %s -prune -o -type f \\( %s \\) ! -name '._*' -print" % (
            shlex.quote(top), shlex.quote(ORIGINALS), exts))
        for line in sorted(out.splitlines()):
            yield line, top


def remote_job(host, src, top, work, args):
    name = os.path.basename(src)
    local_src = os.path.join(work, name)
    local_dst = os.path.splitext(local_src)[0] + ".mp4"
    remote_dst = os.path.splitext(src)[0] + ".mp4"
    if ssh(host, "test -e %s && echo yes || true" % shlex.quote(remote_dst)).strip() == "yes":
        log("  skip: %s already exists" % os.path.basename(remote_dst))
        return
    try:
        pull(host, src, local_src)
        subs = convert_file(local_src, local_dst, args)
        if args.dry_run:
            return
        # Push to a .part name, then rename on the far side so a half-copied MP4 never looks finished.
        push(host, local_dst, remote_dst + ".part")
        size = os.path.getsize(local_dst)
        remote_size = int(ssh(host, "stat -f %%z %s 2>/dev/null || stat -c %%s %s" % (
            shlex.quote(remote_dst + ".part"), shlex.quote(remote_dst + ".part"))).strip())
        if remote_size != size:
            raise RuntimeError("copy back failed: %d bytes here, %d there" % (size, remote_size))
        ssh(host, "mv %s %s" % (shlex.quote(remote_dst + ".part"), shlex.quote(remote_dst)))
        for sub in subs:
            push(host, sub, os.path.join(os.path.dirname(src), os.path.basename(sub)))
        if args.delete_originals:
            ssh(host, "rm %s" % shlex.quote(src))
            log("  original deleted")
        else:
            dest = originals_path(src, top, args)
            ssh(host, "mkdir -p %s && mv %s %s" % (shlex.quote(os.path.dirname(dest)), shlex.quote(src), shlex.quote(dest)))
            log("  original moved to %s" % os.path.relpath(dest, top))
    finally:
        for f in os.listdir(work):
            os.remove(os.path.join(work, f))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="files or folders to convert")
    ap.add_argument("--remote", metavar="HOST", help="the paths are on this ssh host; convert here and copy back")
    ap.add_argument("--delete-originals", action="store_true", help="delete originals after a verified conversion")
    ap.add_argument("--originals", metavar="DIR", help="where to keep originals (default: <path>/%s)" % ORIGINALS)
    ap.add_argument("--dry-run", action="store_true", help="show what would happen without converting")
    ap.add_argument("--no-hevc", action="store_true", help="re-encode HEVC to H.264 too (for older Macs)")
    ap.add_argument("--no-subs", action="store_true", help="don't save subtitle tracks as .vtt files")
    ap.add_argument("--software", action="store_true", help="use x264 instead of the Mac's hardware encoder")
    ap.add_argument("--quality", type=int, default=62, help="hardware encoder quality 1-100 (default 62)")
    ap.add_argument("--crf", type=int, default=20, help="x264 quality, lower is better (default 20)")
    args = ap.parse_args()

    jobs = list(find_remote(args.remote, args.paths) if args.remote else find_local(args.paths))
    log("%d file(s) to convert%s" % (len(jobs), " (dry run)" if args.dry_run else ""))
    failed = []
    work = tempfile.mkdtemp(prefix="convert-") if args.remote else None
    try:
        for i, (src, top) in enumerate(jobs, 1):
            log("[%d/%d] %s" % (i, len(jobs), os.path.relpath(src, top)))
            try:
                if args.remote:
                    remote_job(args.remote, src, top, work, args)
                else:
                    dst = os.path.splitext(src)[0] + ".mp4"
                    if os.path.exists(dst):
                        log("  skip: %s already exists" % os.path.basename(dst))
                        continue
                    convert_file(src, dst, args)
                    if not args.dry_run:
                        log("  original " + retire_local(src, top, args))
            except (subprocess.CalledProcessError, RuntimeError, ValueError, OSError) as exc:
                log("  FAILED: %s" % exc)
                failed.append(src)
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
    log("Done: %d converted, %d failed" % (len(jobs) - len(failed), len(failed)))
    for f in failed:
        log("  failed: " + f)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
