#!/usr/bin/env python3
"""Sofa Box OS's cards on GitHub's releases page, for the card workflows (.github/workflows/sofa-box-image.yml and
sofa-box-stable.yml), through the GitHub CLI (gh, signed in). There are three kinds of release:

- "sofa-box", the testing card: always the newest card from main, its files always named sofa-box.img.xz and so on;
- "box-os-vX.Y.Z", each version's own card: made once, the first time main has that number, and kept;
- "sofa-box-stable", the stable card: the version deploy/sofa-box/STABLE names (tried on a real box), copied from its
  own release, its files always named sofa-box-stable.img.xz and so on.

  tools/sofa-box-releases.py may-replace VERSION COMMIT
      May this card (VERSION, built from COMMIT) become the testing card? Exit 0: yes. Exit 10: no, the testing card
      there now is newer: a higher version, or the same version from a later commit (a re-run of an older run, or an
      older push that finished late). A lower version never replaces a higher one.
  tools/sofa-box-releases.py mark-stable [STABLE_FILE]
      Makes the releases match deploy/sofa-box/STABLE: that version's own release is titled "(stable)", the release
      "sofa-box-stable" holds its card (checked against the version's SHA-256), and a version that was stable before
      loses the mark. Stops (exit 1) if the version has no release with a card: only a numbered card can be stable.

Exit 2: GitHub didn't answer as expected (nothing more was changed). Standard library only.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.environ.get("GITHUB_REPOSITORY") or "krintoxi/sofa"
TESTING, STABLE = "sofa-box", "sofa-box-stable"
PAGE = "https://github.com/%s/releases/tag/" % REPO
CARD_MARK = re.compile(r"<!-- sofa-box-card version=(\d+\.\d+\.\d+) commit=([0-9a-f]{7,40}) -->")
STABLE_MARK = re.compile(r"<!-- sofa-box-stable version=(\d+\.\d+\.\d+) sha256=([0-9a-f]{64}) -->")
STATUS = re.compile(r"<!-- sofa-box-status -->.*?<!-- /sofa-box-status -->\n*", re.S)
STABLE_FILES = ("sofa-box-stable.img.xz", "sofa-box-stable.img.xz.sha256", "sofa-box-stable-report.txt")

# A numbered release's first line: what it is now
SAYS_TESTING = "**Testing**: not tried on a real box yet. The tested card is the stable one: " + PAGE + STABLE
SAYS_STABLE = ("**Stable**: tried on a real box. Boxes on Stable (the default) are offered this version, and its card is "
               "also the stable card: " + PAGE + STABLE)
SAYS_TESTED = "**Tested**: tried on a real box; it was the stable version before a newer one. The stable card now: " + PAGE + STABLE


class GitHubError(Exception):
    pass


def version_key(v):
    if not isinstance(v, str) or not re.match(r"^\d+\.\d+\.\d+$", v):
        return None
    return tuple(int(x) for x in v.split("."))


def newer(a, b):
    ka, kb = version_key(a), version_key(b)
    return bool(ka and kb and ka > kb)


# ---------------------------------------------------------------- the testing card never goes backwards

def card_there(release, tag_commit):
    """The version and commit of the testing card there now: from the mark in its notes, or (a release from before the
    mark) its title and the commit its tag is on."""
    m = CARD_MARK.search(release.get("body") or "")
    if m:
        return m.group(1), m.group(2)
    t = re.search(r"Sofa Box OS (\d+\.\d+\.\d+)", release.get("name") or "")
    return (t.group(1) if t else None), tag_commit


def may_replace(version, commit, there, relation):
    """(yes, why): whether a card of `version` built from `commit` may replace the testing card. `there` is the version
    and commit of the card there now (None: no card yet); relation(base, head) says how two commits are related on
    GitHub ("ahead": head came after base; "behind", "identical", "diverged"), asked only for the same version."""
    if not version_key(version):
        raise ValueError("%r isn't a version" % version)
    have, at = there or (None, None)
    if not version_key(have):
        return True, "there's no testing card yet" if not there else "the testing card there now has no version"
    if newer(have, version):
        return False, "the testing card is Sofa Box OS %s, newer than %s: it stays" % (have, version)
    if newer(version, have):
        return True, "Sofa Box OS %s is newer than the testing card's %s" % (version, have)
    if not at or at.startswith(commit) or commit.startswith(at):
        return True, "the same version, from the same commit"
    if relation(at, commit) == "behind":
        return False, "the testing card is Sofa Box OS %s from a later commit (%s): it stays" % (have, at[:7])
    return True, "the same version, from a later commit"


# ---------------------------------------------------------------- GitHub, through gh

def gh(*args, data=None):
    p = subprocess.run(["gh"] + list(args), input=data, capture_output=True, text=True)
    if p.returncode != 0:
        raise GitHubError((p.stderr or p.stdout or "gh %s failed" % args[0]).strip())
    return p.stdout


def api(path, method="GET", body=None):
    """GitHub's REST API: the JSON it answers ({} for nothing), or None if it isn't there (404)."""
    args = ["api", "-X", method, path] + (["--input", "-"] if body is not None else [])
    try:
        out = gh(*args, data=json.dumps(body) if body is not None else None)
    except GitHubError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise
    return json.loads(out) if out.strip() else {}


def release(tag):
    return api("repos/%s/releases/tags/%s" % (REPO, tag))


def tag_commit(tag):
    ref = api("repos/%s/git/refs/tags/%s" % (REPO, tag)) or {}
    return (ref.get("object") or {}).get("sha")


def releases():
    out, page = [], 1
    while True:
        got = api("repos/%s/releases?per_page=100&page=%d" % (REPO, page)) or []
        out += got
        if len(got) < 100:
            return out
        page += 1


def edit(rel, name, body):
    if (rel.get("name"), rel.get("body") or "") != (name, body):
        api("repos/%s/releases/%d" % (REPO, rel["id"]), "PATCH", {"name": name, "body": body})
        print("  %s: %s" % (rel["tag_name"], name))


def put_files(tag, paths):
    """The release's files replaced by these, the download never missing: the new ones go up beside the old ones
    (next-…, the slow part), then each old one goes and its new one takes its name, a second or two apart."""
    for a in release(tag)["assets"]:
        if a["name"].startswith("next-"):                    # left from a run that stopped
            api("repos/%s/releases/assets/%d" % (REPO, a["id"]), "DELETE")
    staging = tempfile.mkdtemp()
    try:
        staged = []
        for p in paths:
            staged.append(os.path.join(staging, "next-" + os.path.basename(p)))
            shutil.copyfile(p, staged[-1])
        gh("release", "upload", tag, *staged, "-R", REPO)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    assets = {a["name"]: a["id"] for a in release(tag)["assets"]}
    for name in (os.path.basename(p) for p in paths):        # one at a time, the card first
        old, new = assets.get(name), assets.get("next-" + name)
        if new is None:
            continue
        if old is not None:
            api("repos/%s/releases/assets/%d" % (REPO, old), "DELETE")
        api("repos/%s/releases/assets/%d" % (REPO, new), "PATCH", {"name": name})


# ---------------------------------------------------------------- the stable card

def stable_in(path):
    """The version deploy/sofa-box/STABLE marks stable, or None ("none"). Anything else there is a mistake."""
    with open(path, encoding="utf-8") as f:
        lines = [x.strip() for x in f if x.strip() and not x.lstrip().startswith("#")]
    if len(lines) != 1 or not (lines[0] == "none" or version_key(lines[0])):
        raise ValueError("%s needs one line that's a version (like 1.1.54) or none, not %r" % (path, lines))
    return None if lines[0] == "none" else lines[0]


def with_status(body, says):
    """A numbered release's notes with its first line saying what it is now (or nothing), in place of the one it had."""
    rest = STATUS.sub("", body or "").lstrip("\n")
    return ("<!-- sofa-box-status -->%s<!-- /sofa-box-status -->\n\n" % says if says else "") + rest


def marks(all_releases, stable):
    """What changes on the numbered releases: [(release, new title, new notes)]. The stable one says so in its title
    and its first line; one that was stable before says it was tested; the rest stay as they are."""
    out = []
    for r in all_releases:
        m = re.match(r"^box-os-v(\d+\.\d+\.\d+)$", r.get("tag_name") or "")
        if not m:
            continue
        name, body = r.get("name") or "", r.get("body") or ""
        plain = re.sub(r"\s*\(stable\)\s*$", "", name)
        if m.group(1) == stable:
            new = (plain + " (stable)", with_status(body, SAYS_STABLE))
        elif plain != name or SAYS_STABLE in body:
            new = (plain, with_status(body, SAYS_TESTED))
        else:
            continue
        if new != (name, body):
            out.append((r, new[0], new[1]))
    return out


def stable_notes(version, sha, own):
    """The stable release's notes: what it is, then its own release's (how to use it, what's new), for its file names."""
    head = ("<!-- sofa-box-stable version=%s sha256=%s -->\n" % (version, sha) +
            "The **stable** card for the **Sofa Box** (Raspberry Pi 3 B+, 4 or 5): **Sofa Box OS %s**, tried on a real box. "
            "Its file is always `sofa-box-stable.img.xz`, so this link never changes. It's the card of the version's own "
            "release, %s (SHA-256 `%s`).\n\nThe newest card, not tried on a real box yet, is the testing one: %s\n\n"
            % (version, PAGE + "box-os-v" + version, sha, PAGE + TESTING))
    rest = STATUS.sub("", own.get("body") or "").replace("sofa-box-os-%s" % version, "sofa-box-stable")
    return head + rest.lstrip("\n")


NO_STABLE_NOTES = ("No Sofa Box OS card is marked stable yet (tried on a real box). Until one is, the newest card is the "
                   "testing one: %s\n\nThe version marked stable is named in "
                   "https://github.com/%s/blob/main/deploy/sofa-box/STABLE." % (PAGE + TESTING, REPO))


def copy_card(version, own, work):
    """The version's card, its checksum and its report, downloaded from its own release under the stable names, the
    card checked against its SHA-256. The paths, and the SHA-256."""
    have = {a["name"] for a in own.get("assets") or []}
    card, sums, report = "sofa-box-os-%s.img.xz" % version, "sofa-box-os-%s.img.xz.sha256" % version, "sofa-box-os-%s-report.txt" % version
    if card not in have or sums not in have:
        raise SystemExit("Sofa Box OS %s's release has no card (%s and its .sha256): only a numbered card can be the stable one."
                         % (version, card))
    gh("release", "download", "box-os-v" + version, "-p", card, "-p", sums, "-p", report, "-D", work, "--clobber", "-R", REPO)
    with open(os.path.join(work, sums), encoding="utf-8") as f:
        want = f.read().split()[0].lower()
    h = hashlib.sha256()
    with open(os.path.join(work, card), "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() != want:
        raise SystemExit("Sofa Box OS %s's card isn't the one its SHA-256 says (%s): nothing changed." % (version, want))
    paths = [os.path.join(work, n) for n in STABLE_FILES]
    os.replace(os.path.join(work, card), paths[0])
    with open(paths[1], "w", encoding="utf-8") as f:
        f.write("%s  %s\n" % (want, STABLE_FILES[0]))
    if os.path.exists(os.path.join(work, report)):
        os.replace(os.path.join(work, report), paths[2])
    else:
        paths.pop()
    return paths, want


def mark_stable(path):
    version = stable_in(path)
    print("deploy/sofa-box/STABLE: %s" % (version or "none"))
    own = release("box-os-v" + version) if version else None
    if version and not own:
        raise SystemExit("Sofa Box OS %s has no release of its own (box-os-v%s): only a numbered card can be the stable one. "
                         "The versions with cards: https://github.com/%s/releases?q=box-os" % (version, version, REPO))
    there = release(STABLE)
    if version:
        m = STABLE_MARK.search((there or {}).get("body") or "")
        names = {a["name"] for a in (there or {}).get("assets") or []}
        work = tempfile.mkdtemp()
        try:
            if m and m.group(1) == version and STABLE_FILES[0] in names:
                sha, paths = m.group(2), None                   # (it holds this card already)
            else:
                paths, sha = copy_card(version, own, work)
            title = "Sofa Box OS %s (stable): the tested card" % version
            notes = stable_notes(version, sha, own)
            commit = tag_commit("box-os-v" + version) or own.get("target_commitish") or "main"
            if not there:
                with open(os.path.join(work, "notes.md"), "w", encoding="utf-8") as f:
                    f.write(notes)
                gh("release", "create", STABLE, *paths, "-R", REPO, "--target", commit, "--latest=false", "--title", title,
                   "--notes-file", os.path.join(work, "notes.md"))
                print("  %s: %s (made)" % (STABLE, title))
            else:
                if paths:
                    put_files(STABLE, paths)
                if commit:
                    api("repos/%s/git/refs/tags/%s" % (REPO, STABLE), "PATCH", {"sha": commit, "force": True})
                edit(there, title, notes)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    elif not there:
        work = tempfile.mkdtemp()
        try:
            with open(os.path.join(work, "notes.md"), "w", encoding="utf-8") as f:
                f.write(NO_STABLE_NOTES)
            gh("release", "create", STABLE, "-R", REPO, "--target", os.environ.get("GITHUB_SHA") or "main", "--latest=false",
               "--title", "Sofa Box OS: no stable card yet", "--notes-file", os.path.join(work, "notes.md"))
            print("  %s: no stable card yet (made)" % STABLE)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    else:
        for a in there.get("assets") or []:                     # none marked any more: no stable card to download
            if a["name"] in STABLE_FILES:
                api("repos/%s/releases/assets/%d" % (REPO, a["id"]), "DELETE")
        edit(there, "Sofa Box OS: no stable card yet", NO_STABLE_NOTES)
    for r, name, body in marks(releases(), version):
        edit(r, name, body)
    return 0


def main(argv):
    try:
        if len(argv) == 3 and argv[0] == "may-replace":
            rel = release(TESTING)
            there = card_there(rel, tag_commit(TESTING)) if rel else None

            def relation(base, head):
                c = api("repos/%s/compare/%s...%s" % (REPO, base, head))
                if not c or not c.get("status"):
                    raise GitHubError("GitHub couldn't compare %s with %s" % (base, head))
                return c["status"]
            ok, why = may_replace(argv[1], argv[2], there, relation)
            print(("This card becomes the testing card: " if ok else "The testing card stays as it is: ") + why + ".")
            return 0 if ok else 10
        if argv[:1] == ["mark-stable"] and len(argv) <= 2:
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            return mark_stable(argv[1] if len(argv) == 2 else os.path.join(here, "deploy", "sofa-box", "STABLE"))
    except (GitHubError, ValueError, KeyError) as exc:
        print("Stopped: %s" % exc, file=sys.stderr)
        return 2
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
