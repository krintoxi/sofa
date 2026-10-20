"""Backups of Sofa's own data: accounts, watch progress, favorites and settings.

The media itself is not included (it's far too big, and it's yours to back up).
One file per backup, data/backups/sofa-backup-<date>.tar.gz, made daily at
`backup_time` and on request. Restore with `python3 sofa.py restore <file>`
while the server is stopped.
"""
import datetime
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import time

from . import __version__, config, store

FILES = ("config.json", "live.key")          # small files copied as they are


def folder():
    return os.path.join(config.DATA_DIR, "backups")


def make(reason="scheduled"):
    """Write a backup and prune old ones. Returns its path."""
    os.makedirs(folder(), exist_ok=True)
    os.chmod(folder(), 0o700)                  # backups hold password hashes
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = os.path.join(folder(), "sofa-backup-%s.tar.gz" % stamp)
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "sofa.db")
        src = sqlite3.connect(os.path.join(config.DATA_DIR, "sofa.db"), timeout=30)
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)                    # consistent copy while the server keeps running
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {t: dst.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                  for t in ("users", "progress", "live_favorites")}
        dst.execute("DELETE FROM probes")          # rebuildable cache; keeps the backup small
        dst.commit()
        dst.execute("VACUUM")
        dst.close()
        src.close()
        if ok != "ok":
            raise RuntimeError("database check failed: %s" % ok)
        manifest = {"sofa_version": __version__, "made": int(time.time()), "reason": reason, "counts": counts,
                    "files": {}}
        tmp_target = target + ".part"
        with tarfile.open(tmp_target, "w:gz") as tar:
            for name, path in [("sofa.db", snap)] + [(f, os.path.join(config.DATA_DIR, f)) for f in FILES]:
                if os.path.exists(path):
                    with open(path, "rb") as fh:
                        manifest["files"][name] = hashlib.sha256(fh.read()).hexdigest()
                    tar.add(path, arcname=name)
            data = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo("MANIFEST.json")
            info.size, info.mtime = len(data), int(time.time())
            tar.addfile(info, io.BytesIO(data))
        os.chmod(tmp_target, 0o600)
        os.replace(tmp_target, target)
    prune()
    store.log("backup", "Backed up accounts and watch history (%d people, %d progress entries)"
              % (counts["users"], counts["progress"]), {"file": os.path.basename(target), "reason": reason})
    return target


def prune():
    keep = int(config.get("backup_keep"))
    for old in listing()[keep:]:
        os.remove(old["path"])


def listing():
    try:
        names = sorted((n for n in os.listdir(folder()) if n.startswith("sofa-backup-") and n.endswith(".tar.gz")),
                       reverse=True)
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(folder(), n)
        out.append({"name": n, "path": p, "size": os.path.getsize(p), "made": int(os.path.getmtime(p))})
    return out


def restore(path):
    """Replace the current data with a backup. The current files are kept in data/pre-restore-<date>/."""
    with tarfile.open(path, "r:gz") as tar:
        manifest = json.load(tar.extractfile("MANIFEST.json"))
        aside = os.path.join(config.DATA_DIR, "pre-restore-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        os.makedirs(aside)
        for name in ("sofa.db", "sofa.db-wal", "sofa.db-shm") + FILES:
            p = os.path.join(config.DATA_DIR, name)
            if os.path.exists(p):
                shutil.move(p, os.path.join(aside, name))
        for name, digest in manifest["files"].items():
            data = tar.extractfile(name).read()
            if hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError("%s in the backup is damaged" % name)
            with open(os.path.join(config.DATA_DIR, name), "wb") as fh:
                fh.write(data)
    return manifest, aside


def _due():
    hh, mm = (int(x) for x in str(config.get("backup_time")).split(":"))
    now = datetime.datetime.now()
    today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    latest = listing()[:1]
    last = datetime.datetime.fromtimestamp(latest[0]["made"]) if latest else None
    return now >= today and (last is None or last < today)


def _loop():
    while True:
        try:
            if _due():
                make()
        except Exception as exc:
            store.log("error", "Backup failed: %s" % exc)
        time.sleep(300)


def start():
    threading.Thread(target=_loop, daemon=True, name="backup").start()
