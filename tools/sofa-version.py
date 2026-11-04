#!/usr/bin/env python3
"""Record which code Sofa's version is: after raising __version__ (sofa/__init__.py) and adding it to CHANGES.md.

    python3 tools/sofa-version.py

tests/test_version.py fails when Sofa's code (sofa/, client/, sofa.py) has changed since the version recorded in
tests/sofa-version.json without a new version, so Server → Updates never shows an old number for new code.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD = os.path.join(ROOT, "tests", "sofa-version.json")
CODE = ("sofa", "client", "sofa.py")


def files():
    """Sofa's code: the files git tracks (a clone), or every file there (a download)."""
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "--", *CODE], capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return sorted(out.stdout.split("\n")[:-1])
    except OSError:
        pass
    found = []
    for top in CODE:
        path = os.path.join(ROOT, top)
        if os.path.isfile(path):
            found.append(top)
        for d, dirs, names in os.walk(path):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            found += [os.path.relpath(os.path.join(d, n), ROOT) for n in names if not n.endswith(".pyc") and n != ".DS_Store"]
    return sorted(found)


def code_hash():
    h = hashlib.sha256()
    for rel in files():
        with open(os.path.join(ROOT, rel), "rb") as f:
            h.update(rel.replace(os.sep, "/").encode() + b"\0" + hashlib.sha256(f.read()).digest())
    return h.hexdigest()


def version():
    with open(os.path.join(ROOT, "sofa", "__init__.py"), encoding="utf-8") as f:
        return re.search(r'__version__ = "([^"]+)"', f.read()).group(1)


def recorded():
    try:
        with open(RECORD, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def on_main():
    """The version recorded on GitHub's main, if git can say: a version that's out already can't take new code."""
    try:
        out = subprocess.run(["git", "-C", ROOT, "show", "origin/main:tests/sofa-version.json"], capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout) if out.returncode == 0 else {}
    except (OSError, ValueError):
        return {}


def main():
    v, rec = version(), recorded()
    out = on_main()
    if out.get("version") == v and out.get("code") != code_hash():
        sys.exit("Sofa %s is on main already, with other code: raise __version__ (and add it to CHANGES.md) first." % v)
    if rec.get("version") and rec["version"] != v and \
            tuple(int(x) for x in v.split(".")) <= tuple(int(x) for x in rec["version"].split(".")):
        sys.exit("Sofa %s isn't newer than %s, the version recorded last: raise __version__ first." % (v, rec["version"]))
    with open(os.path.join(ROOT, "CHANGES.md"), encoding="utf-8") as f:
        if not re.search(r"^## %s\b" % re.escape(v), f.read(), re.M):
            sys.exit("CHANGES.md has no section for %s yet." % v)
    with open(RECORD, "w", encoding="utf-8") as f:
        json.dump({"version": v, "code": code_hash()}, f, indent=1)
        f.write("\n")
    print("Recorded: Sofa %s is this code." % v)


if __name__ == "__main__":
    main()
