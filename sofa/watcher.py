"""Background work: watch the Inbox and library folders, and pre-read file details."""
import threading
import time

from . import artwork, backup, live, media, organizer, store
from .library import LIBRARY

INTERVAL = 20


def _watch():
    while True:
        try:
            filed = organizer.process_inbox()
            if filed:
                LIBRARY.scan("%d new from Inbox" % filed)
                _warm()
            elif LIBRARY.changed():
                LIBRARY.scan("files changed")
                _warm()
        except Exception as exc:   # keep watching whatever happens
            store.log("error", "Library watcher: %s" % exc)
        time.sleep(INTERVAL)


def _warm():
    threading.Thread(target=artwork.warm, args=(LIBRARY,), daemon=True, name="art-warm").start()


def _prober():
    """Probe files ahead of time so pressing play (and TV listings) never wait on the disk."""
    while True:
        if not media.tool("ffprobe"):
            time.sleep(300)
            continue
        todo = [i["path"] for i in list(LIBRARY.items.values()) if media.probe(i["path"], cached_only=True) is None]
        for path in todo[:20]:
            media.probe(path)
            time.sleep(0.5)
        time.sleep(5 if todo else 120)


def start():
    media.start()
    live.start()
    backup.start()
    threading.Thread(target=_watch, daemon=True, name="watcher").start()
    threading.Thread(target=_prober, daemon=True, name="prober").start()
    _warm()
