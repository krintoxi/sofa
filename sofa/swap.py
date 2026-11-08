"""Swapping Sofa's code for another version, so that a power cut part way can't leave it broken.

The new code is first copied beside the old, on the same disk (.sofa-new). Then each part is switched by renames:
the old one moved aside into .sofa-old, the new one moved in. sofa.py, the file every start runs, is replaced in one
step, first, so a start always finds one. Only once the new version has passed its test start is .sofa-old let go:
renamed .sofa-old-done in one step, then deleted.

Cut off part way (a power cut, the computer restarting), the next start of Sofa (sofa.py serve) finds .sofa-old and
puts it back, whole: the version before, as it was. Running recover() twice does no harm, so a cut during that is
fine too.

Only the standard library, and nothing else of Sofa's: sofa.py loads this before the rest of Sofa, from wherever it
is at that moment (sofa/ itself may be the part that was moved aside). tools/update.sh runs it too:
    python3 sofa/swap.py swap APP NEW      python3 sofa/swap.py commit APP      python3 sofa/swap.py undo APP
"""
import json
import os
import shutil
import sys

OLD, NEW, DONE, UNDONE = ".sofa-old", ".sofa-new", ".sofa-old-done", ".sofa-undone"
JOURNAL = ".sofa-swap.json"           # in .sofa-old: what the new version added (taken away again on undo)


def _sync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _sync_all():
    if hasattr(os, "sync"):
        os.sync()


def _remove(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.lexists(path):
        os.remove(path)


def _order(names):
    """sofa.py first: a start always finds one (the new one, which knows to finish or undo a swap)."""
    return sorted(names, key=lambda n: (n != "sofa.py", n))


def stage(app, src, names):
    """Copy the parts of `src` named in `names` beside the old code (app/.sofa-new), on the card before this
    returns. Nothing of the running version is touched yet."""
    new = os.path.join(app, NEW)
    _remove(new)
    os.makedirs(new)
    for name in names:
        s = os.path.join(src, name)
        if os.path.isdir(s) and not os.path.islink(s):
            shutil.copytree(s, os.path.join(new, name), symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
        elif os.path.isfile(s):
            shutil.copy2(s, os.path.join(new, name))
    _sync_all()
    return new


def swap(app):
    """Switch every part staged in app/.sofa-new in, the old ones kept in app/.sofa-old until commit()."""
    new, old = os.path.join(app, NEW), os.path.join(app, OLD)
    if os.path.lexists(old):
        raise RuntimeError("an earlier update wasn't finished. Restart Sofa, then try again")
    names = _order(os.listdir(new))
    os.makedirs(old)
    with open(os.path.join(old, JOURNAL), "w", encoding="utf-8") as f:
        json.dump({"added": [n for n in names if not os.path.lexists(os.path.join(app, n))]}, f)
        f.flush()
        os.fsync(f.fileno())
    _sync_dir(old)
    _sync_dir(app)
    for name in names:
        cur, nxt, keep = os.path.join(app, name), os.path.join(new, name), os.path.join(old, name)
        if os.path.isdir(nxt) and not os.path.islink(nxt):
            if os.path.lexists(cur):
                os.rename(cur, keep)
            os.rename(nxt, cur)
        else:
            if os.path.isfile(cur) and not os.path.islink(cur):
                try:
                    os.link(cur, keep)              # (the old file stays where it is until the new one replaces it)
                except OSError:
                    shutil.copy2(cur, keep)         # (a disk without hard links)
            elif os.path.lexists(cur):
                os.rename(cur, keep)
            os.replace(nxt, cur)
    _sync_dir(old)
    _sync_dir(app)
    os.rmdir(new)


def commit(app):
    """The new version works: let the old one go (one rename, then the deleting, which may be cut off safely)."""
    old, done = os.path.join(app, OLD), os.path.join(app, DONE)
    if os.path.isdir(old):
        _remove(done)
        os.rename(old, done)
        _sync_dir(app)
    for leftover in (done, os.path.join(app, NEW), os.path.join(app, UNDONE)):
        _remove(leftover)


def undo(app):
    """Put the old version back, whole, from app/.sofa-old. Done twice (cut off the first time), it carries on."""
    old, aside = os.path.join(app, OLD), os.path.join(app, UNDONE)
    if not os.path.isdir(old):
        return False
    try:
        with open(os.path.join(old, JOURNAL), encoding="utf-8") as f:
            added = json.load(f).get("added") or []
    except (OSError, ValueError):
        added = []
    os.makedirs(aside, exist_ok=True)
    for name in added:                              # the new version's own parts, which the old one didn't have
        if os.path.basename(name) == name and os.path.lexists(os.path.join(app, name)):
            _remove(os.path.join(aside, name))
            os.rename(os.path.join(app, name), os.path.join(aside, name))
    for name in _order(n for n in os.listdir(old) if n != JOURNAL):
        keep, cur = os.path.join(old, name), os.path.join(app, name)
        if os.path.isdir(keep) and not os.path.islink(keep):
            if os.path.lexists(cur):
                _remove(os.path.join(aside, name))
                os.rename(cur, os.path.join(aside, name))
            os.rename(keep, cur)
        else:
            if os.path.isdir(cur) and not os.path.islink(cur):
                _remove(os.path.join(aside, name))
                os.rename(cur, os.path.join(aside, name))
            if os.path.lexists(cur) and os.path.samefile(keep, cur):
                os.remove(keep)                     # (cut off before the new file came: the old one is still there)
            else:
                os.replace(keep, cur)
    _sync_dir(app)
    _remove(os.path.join(old, JOURNAL))
    os.rmdir(old)
    _sync_dir(app)
    for leftover in (aside, os.path.join(app, NEW), os.path.join(app, DONE)):
        _remove(leftover)
    return True


def recover(app):
    """At Sofa's start: a swap cut off part way is undone; what a finished one left behind is cleared away.
    True when the version before was put back."""
    back = undo(app)
    for leftover in (NEW, DONE, UNDONE):
        _remove(os.path.join(app, leftover))
    return back


def replace_with(app, src, names):
    """The whole switch in one go (going back to a saved copy of the code): staged, swapped, kept."""
    stage(app, src, names)
    swap(app)
    commit(app)


if __name__ == "__main__":
    what = sys.argv[1:2]
    if what == ["swap"] and len(sys.argv) >= 4:
        stage(sys.argv[2], sys.argv[3], sys.argv[4:] or sorted(os.listdir(sys.argv[3])))
        swap(sys.argv[2])
    elif what == ["commit"] and len(sys.argv) == 3:
        commit(sys.argv[2])
    elif what == ["undo"] and len(sys.argv) == 3:
        sys.exit(0 if undo(sys.argv[2]) else 1)
    else:
        sys.exit(__doc__.strip().splitlines()[-1])
