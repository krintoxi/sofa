"""Background work: watch the Inbox and library folders, and pre-read file details."""
import json
import os
import threading
import time

from . import archive, artwork, backup, config, dvr, fetch, fileops, hardware, intros, live, machine, media, optimize, organizer, places, previews, store, travel, trickplay, updater
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
    places.auto_drives()                      # drives plugged in already (Sofa on a Sofa Box): in the first read too
    _first_read()
    tidied_at = 0
    while True:
        try:
            if time.time() - tidied_at > 600 and not config.demo_on():   # tidy folders now and then (the demo's are read-only)
                tidied_at = time.time()
                organizer.tidy_library()
                for _key, root in places.roots("shows") + places.roots("movies") + places.roots("adult"):
                    fileops.leftovers(root)       # half copies a crash left (fileops.py)
            filed = organizer.process_inbox()
            places.auto_drives()                  # a drive was just plugged in: sorted into the library (with links)
            linked = sum(organizer.link_drive(p) for p in places.usb())
            if linked:
                LIBRARY.scan("a USB drive was sorted")
                _after_scan()
            elif filed:
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
    hardware.give_back(collect=True)          # the library before this read, and what reading it took: back
    _warm()
    threading.Thread(target=lambda: time.sleep(90) or optimize.auto_enqueue(LIBRARY), daemon=True,
                     name="convert-check").start()


def _warm():
    threading.Thread(target=artwork.warm, args=(LIBRARY,), daemon=True, name="art-warm").start()


def to_read(items, skip=(), busy=False, most=20):
    """The next files for the reading ahead: (batch, first time). Files never read come first; then, when nothing is
    being converted for anyone (`busy`), those an older Sofa read without the detail it keeps now. `skip`: the paths
    that couldn't be read and the items read since the library's list last took them in (their entries still say
    "not read" until then, and the same twenty mustn't be picked again and again)."""
    left = [i for i in items if i.get("path") and i["path"] not in skip and i["id"] not in skip]
    todo = [i for i in left if i.get("read") == 0]
    todo += [i for i in left if "read" not in i and media.probe(i["path"], cached_only=True) is None]     # (music)
    if todo:
        return todo[:most], True
    if busy:
        return [], False
    return [i for i in left if i.get("read", media.PROBE_DETAIL) not in (0, media.PROBE_DETAIL)][:most], False


def _prober():
    """Probe files ahead of time so pressing play (and TV listings) never wait on the disk, and so each title's
    length, picture size and languages are on its card and page without the file being opened for them. Files read
    by an older Sofa are read once more for what it didn't keep (frame rate, HDR, bit rates), one at a time and
    not while someone watches what Sofa converts. What's been read goes onto the library's list every few minutes
    (LIBRARY.refresh), not file by file: each change makes every open app fetch the list again."""
    unreadable, waiting, told = set(), set(), time.time()
    while True:
        if not media.tool("ffprobe"):
            time.sleep(300)
            continue
        # several at once on a computer with the cores for it (hardware.workers: one on a small board, or while
        # someone watches what Sofa converts), each with its half second's pause, as one at a time had
        n = hardware.workers(heavy=False)
        batch, first = to_read(list(LIBRARY.items.values()), unreadable | waiting, media.should_wait(), 20 * n)

        def read(item):
            if media.probe(item["path"], detail=True) is None:
                unreadable.add(item["path"])              # (tried again after a restart, not every five seconds)
            time.sleep(0.5)
        try:
            hardware.each(read, batch, most=n if first else 1)
        except Exception as exc:                  # (one odd file mustn't end the reading ahead)
            print("Reading file details: %r" % exc, flush=True)
        waiting.update(i["id"] for i in batch)
        if waiting and (len(batch) < 20 * n or time.time() - told > 600):      # all read, or ten minutes' worth
            try:
                LIBRARY.refresh(waiting)
            except Exception as exc:
                print("Putting file details on the library: %r" % exc, flush=True)
            waiting, told = set(), time.time()
        time.sleep(5 if batch else 120)


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
    hardware.start()
    media.start()
    live.start()
    dvr.start()
    backup.start()
    threading.Thread(target=_watch, daemon=True, name="watcher").start()
    threading.Thread(target=_prober, daemon=True, name="prober").start()
    optimize.start()
    updater.start()
    intros.start(LIBRARY)
    fetch.start()
    trickplay.start(LIBRARY)
    previews.start(LIBRARY)
    travel.start()
    machine.start()
    archive.start()
