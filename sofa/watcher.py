"""Background work: watch the Inbox and library folders, and pre-read file details."""
import json
import os
import threading
import time

from . import artwork, backup, fetch, intros, live, machine, media, optimize, organizer, previews, store, trickplay, updater
from .library import LIBRARY

INTERVAL = 20


def _first_read():
    """Right after Sofa starts: the library from what's already saved (seconds), then a full read
    that fetches missing details and pictures. The web server is already answering meanwhile."""
    for quick in (True, False):
        try:
            LIBRARY.scan("server start", quick=quick)
            print("Library%s: %s (%.0f s)" % (" (from saved details)" if quick else "",
                                              json.dumps(LIBRARY.counts()), LIBRARY.last_scan_seconds), flush=True)
        except Exception as exc:
            print("Reading the library failed: %r" % exc, flush=True)
            store.log("error", "Reading the library: %s" % exc)
    _after_scan()


def _watch():
    _first_read()
    tidied_at = 0
    while True:
        try:
            if time.time() - tidied_at > 600:     # tidy folders now and then, not every 20 seconds
                tidied_at = time.time()
                organizer.tidy_library()
            filed = organizer.process_inbox()
            if filed:
                LIBRARY.scan("%d new from Inbox" % filed)
                _after_scan()
            elif LIBRARY.changed():
                LIBRARY.scan("files changed")
                _after_scan()
            elif LIBRARY.art_pending or (LIBRARY.art_waiting and machine.heavy_ok()):   # more artwork than one scan does
                LIBRARY.scan("fetching more artwork")
                _warm()
        except Exception as exc:   # keep watching whatever happens
            store.log("error", "Library watcher: %s" % exc)
        time.sleep(INTERVAL)


def _after_scan():
    _warm()
    threading.Thread(target=lambda: time.sleep(90) or optimize.auto_enqueue(LIBRARY), daemon=True,
                     name="convert-check").start()


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
    from . import uploads
    uploads.clean()                      # pieces of uploads cut off by a restart
    try:
        from . import config
        store.scrub_private([config.path("adult"), os.path.join(config.path("inbox"), "XXX"),
                             os.path.join(config.path("review"), "XXX")])
    except Exception as exc:
        store.log("error", "Tidying the activity log: %s" % exc)
    try:
        store.decode_saved_ids()
    except Exception as exc:
        store.log("error", "Fixing saved watch positions: %s" % exc)
    media.start()
    live.start()
    backup.start()
    threading.Thread(target=_watch, daemon=True, name="watcher").start()
    threading.Thread(target=_prober, daemon=True, name="prober").start()
    optimize.start()
    updater.start()
    intros.start(LIBRARY)
    fetch.start()
    trickplay.start(LIBRARY)
    previews.start(LIBRARY)
    machine.start()
