"""Moving files without leaving half of one behind.

shutil.move renames a file on the same drive (all or nothing) but across drives copies it and then deletes the
original: a crash, or a full disk, in the middle left a cut-off video under its final name, which the next look
took for a different file (and set the real one aside). Here a copy across drives goes to a hidden name next to
the destination, is flushed to the disk, renamed into place in one step, and only then is the original removed.
At any moment the file is whole in one place or the other, so whatever was interrupted simply runs again.
"""
import errno
import os
import shutil

PARTIAL = ".sofa-partial"


def _partial(dest):
    return os.path.join(os.path.dirname(dest), ".%s%s" % (os.path.basename(dest), PARTIAL))


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


def copy_file(src, dest):
    """Copy a file so that `dest` only ever exists complete."""
    tmp = _partial(dest)
    with open(src, "rb") as f, open(tmp, "wb") as g:
        shutil.copyfileobj(f, g, 8 * 1024 * 1024)
        g.flush()
        os.fsync(g.fileno())
    try:
        shutil.copystat(src, tmp)
    except OSError:
        pass
    os.replace(tmp, dest)
    _sync_dir(os.path.dirname(dest) or ".")


def move(src, dest):
    """shutil.move, but never half a file under the final name (see above). Like shutil.move, a `dest` that's an
    existing folder means "into it". Returns where it went."""
    if os.path.isdir(dest):
        dest = os.path.join(dest, os.path.basename(src.rstrip(os.sep)))
    try:
        os.rename(src, dest)
        return dest
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    if os.path.isdir(src) and not os.path.islink(src):
        os.makedirs(dest, exist_ok=True)              # file by file: what's done stays done, the rest goes next time
        for name in os.listdir(src):
            move(os.path.join(src, name), os.path.join(dest, name))
        shutil.rmtree(src, ignore_errors=True)
        return dest
    copy_file(src, dest)
    os.unlink(src)
    return dest


def leftovers(root, older=86400):
    """Hidden partial copies a crash left behind (a day old: nothing's still writing them), and the hidden folders of
    a move between drives that never finished (places.py). Removes them; returns how many."""
    import time
    gone = 0
    for d, dirs, files in os.walk(root):
        for x in [x for x in dirs if x.startswith(".") and x.endswith(".sofa-moving")]:
            p = os.path.join(d, x)
            try:
                if time.time() - os.path.getmtime(p) > older:
                    shutil.rmtree(p)
                    gone += 1
            except OSError:
                pass
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for f in files:
            if f.startswith(".") and f.endswith(PARTIAL):
                p = os.path.join(d, f)
                try:
                    if time.time() - os.path.getmtime(p) > older:
                        os.unlink(p)
                        gone += 1
                except OSError:
                    pass
    return gone
