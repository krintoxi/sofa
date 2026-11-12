#!/usr/bin/env python3
"""Sofa for Windows, put together for the installer: build/windows/Sofa holds what goes on the PC.

    python tools/windows-build.py                  build/windows/Sofa, and build/windows/installed-commit
    iscc /DAppVersion=<version> deploy\\windows\\sofa.iss      (on Windows: the installer, from that folder)

What's in it: Sofa's code, exactly the parts an update replaces (CODE, the same list as sofa/updater.py's), and in
vendor\\ the Python and ffmpeg it runs with (tools/windows-deps.py: fixed versions, checked byte for byte). Never
data\\: accounts, settings and history are made on the PC and never shipped. .github/workflows/windows.yml runs this
on GitHub's Windows machines; it runs anywhere (nothing in it is started, only copied).
"""
import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = ("sofa", "client", "deploy", "tools", "docs", "integrations", "roku", "sofa.py", "README.md", "LICENSE",
        "NOTICE", "TRADEMARKS.md", ".gitignore")          # sofa/updater.py's CODE (a test checks they're the same)
LEAVE_OUT = ("__pycache__", "*.pyc", ".DS_Store")


def version():
    with open(os.path.join(APP, "sofa", "__init__.py"), encoding="utf-8") as f:
        return re.search(r'__version__ = "([^"]+)"', f.read()).group(1)


def commit():
    sha = os.environ.get("GITHUB_SHA") or ""
    if not sha:
        try:
            sha = subprocess.run(["git", "-C", APP, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30).stdout.strip()
        except OSError:
            sha = ""
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else ""


def deps():
    spec = importlib.util.spec_from_file_location("windows_deps", os.path.join(APP, "tools", "windows-deps.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stage(out, cache=None):
    """Sofa as it goes on the PC, in <out>/Sofa. Returns that folder."""
    dest = os.path.join(out, "Sofa")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for name in CODE:
        src = os.path.join(APP, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, name), ignore=shutil.ignore_patterns(*LEAVE_OUT))
        elif os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest, name))
    d = deps()
    vendor = os.path.join(dest, "vendor")
    cache = cache or os.path.join(out, "downloads")
    d.unpack_python(d.fetch(d.PYTHON, cache), os.path.join(vendor, "python"))
    d.unpack_ffmpeg(d.fetch(d.FFMPEG, cache), os.path.join(vendor, "ffmpeg"))
    sha = commit()
    with open(os.path.join(out, "installed-commit"), "w", encoding="utf-8") as f:
        f.write(sha)                     # (data\installed-commit on the PC: Server → Updates says which commit runs)
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join(APP, "build", "windows"))
    ap.add_argument("--cache", help="where downloads are kept (default: <out>/downloads)")
    args = ap.parse_args(argv)
    dest = stage(args.out, args.cache)
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _ds, fs in os.walk(dest) for f in fs)
    print("Sofa %s for Windows in %s (%d MB)" % (version(), dest, size // (1024 * 1024)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
