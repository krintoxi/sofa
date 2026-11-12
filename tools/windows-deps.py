#!/usr/bin/env python3
"""What Sofa for Windows brings along: Python and ffmpeg, downloaded once and checked byte for byte.

    python tools/windows-deps.py --ffmpeg            vendor/ffmpeg/bin (ffmpeg.exe, ffprobe.exe and their DLLs)
    python tools/windows-deps.py --python            vendor/python (Python's own embeddable build, pythonw.exe too)
    python tools/windows-deps.py --python --ffmpeg   both (what the installer carries)

Both come from where their makers publish them, at a fixed version and with the SHA-256 written below, so a
download that isn't exactly that file is refused. To move to a newer version: change the version, the address and
the hash together (the hash of the new file: `shasum -a 256` or PowerShell's `Get-FileHash`), then let the Windows
jobs run.

- Python: the "embeddable package" from python.org (the interpreter, its standard library in a .zip, no installer,
  no registry entries, nothing outside its folder). Sofa needs nothing beyond the standard library.
- ffmpeg: Gyan Doshi's "full, shared" Windows build of a released ffmpeg (the one ffmpeg.org links to for Windows):
  libx264, chromaprint for Skip Intro, and the GPU encoders. GPL v3; its licence and where its source is are put
  beside it (vendor/ffmpeg/LICENSE.txt, SOURCE.txt). ffplay isn't taken: Sofa never opens a window.

Downloads are kept in build/windows/downloads (or --cache) so a second run doesn't fetch them again. Only the standard
library; runs on any computer (the files are unpacked, never run).
"""
import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PYTHON = {
    "version": "3.14.10",
    "url": "https://www.python.org/ftp/python/3.14.10/python-3.14.10-embed-amd64.zip",
    "sha256": "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159",
}
FFMPEG = {
    "version": "9.0.2",
    "url": "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-full_build-shared.zip",
    "sha256": "8d31e162f1616e37aab3fa2db991b97e1b8dbeb1c8465fd81a81be16ff91b328",
    "source": "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz",
    "build": "https://www.gyan.dev/ffmpeg/builds/ (full build, shared libraries)",
}


def fetch(spec, cache):
    """The file at spec["url"], from the cache or downloaded, refused unless its SHA-256 is spec["sha256"]."""
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, spec["url"].rsplit("/", 1)[1])
    if not (os.path.isfile(path) and sha256(path) == spec["sha256"]):
        print("Downloading %s" % spec["url"], flush=True)
        tmp = path + ".part"
        req = urllib.request.Request(spec["url"], headers={"User-Agent": "Sofa build (https://github.com/krintoxi/sofa)"})
        with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        got = sha256(tmp)
        if got != spec["sha256"]:
            os.remove(tmp)
            raise SystemExit("%s isn't the file we expect (SHA-256 %s, not %s); nothing was unpacked."
                             % (spec["url"], got, spec["sha256"]))
        os.replace(tmp, path)
    return path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _fresh(folder):
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)


def unpack_python(archive, dest):
    """The embeddable Python in dest, told where Sofa is: its ._pth file names the folders on its path (it ignores
    PYTHONPATH and the current folder), and Sofa's own folder is two up from vendor/python."""
    _fresh(dest)
    with zipfile.ZipFile(archive) as z:
        z.extractall(dest)
    pth = [n for n in os.listdir(dest) if n.endswith("._pth")]
    if len(pth) != 1:
        raise SystemExit("the Python download has no ._pth file; nothing to set up")
    path = os.path.join(dest, pth[0])
    with open(path, encoding="utf-8") as f:
        lines = [line.rstrip("\r\n") for line in f]
    if "..\\.." not in lines:
        lines.insert(2, "..\\..")
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    for name in ("python.exe", "pythonw.exe"):
        if not os.path.isfile(os.path.join(dest, name)):
            raise SystemExit("the Python download has no %s" % name)


def unpack_ffmpeg(archive, dest):
    """ffmpeg.exe, ffprobe.exe and the DLLs they load in dest/bin; the licence and README beside them."""
    _fresh(os.path.join(dest, "bin"))
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if info.is_dir() or len(parts) < 2 or ".." in parts:
                continue
            name = parts[-1]
            if parts[-2] == "bin" and (name.endswith(".dll") or name in ("ffmpeg.exe", "ffprobe.exe")):
                target = os.path.join(dest, "bin", name)
            elif len(parts) == 2 and name in ("LICENSE", "README.txt"):
                target = os.path.join(dest, "LICENSE.txt" if name == "LICENSE" else name)
            else:
                continue
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        if not os.path.isfile(os.path.join(dest, "bin", name)):
            raise SystemExit("the ffmpeg download has no %s" % name)
    with open(os.path.join(dest, "SOURCE.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write("ffmpeg %s for Windows, as Sofa for Windows carries it.\n\n"
                "Built by Gyan Doshi: %s\n"
                "Downloaded from: %s\n"
                "SHA-256 of that download: %s\n"
                "ffmpeg's source code for this version: %s\n\n"
                "ffmpeg is free software under the GNU General Public License, version 3 (LICENSE.txt), and is not\n"
                "part of Sofa; Sofa runs it as a separate program. The libraries in this build and their own\n"
                "licences are listed in README.txt.\n"
                % (FFMPEG["version"], FFMPEG["build"], FFMPEG["url"], FFMPEG["sha256"], FFMPEG["source"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--python", action="store_true", help="put Python in <vendor>/python")
    ap.add_argument("--ffmpeg", action="store_true", help="put ffmpeg in <vendor>/ffmpeg")
    ap.add_argument("--vendor", default=os.path.join(APP, "vendor"), help="where (default: vendor/ in this folder)")
    ap.add_argument("--cache", default=os.path.join(APP, "build", "windows", "downloads"), help="keep downloads here")
    args = ap.parse_args(argv)
    if not (args.python or args.ffmpeg):
        ap.error("say what to fetch: --python, --ffmpeg or both")
    if args.python:
        unpack_python(fetch(PYTHON, args.cache), os.path.join(args.vendor, "python"))
        print("Python %s in %s" % (PYTHON["version"], os.path.join(args.vendor, "python")), flush=True)
    if args.ffmpeg:
        unpack_ffmpeg(fetch(FFMPEG, args.cache), os.path.join(args.vendor, "ffmpeg"))
        print("ffmpeg %s in %s" % (FFMPEG["version"], os.path.join(args.vendor, "ffmpeg")), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
