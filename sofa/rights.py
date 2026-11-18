"""A title's rights record: what a video is, who publishes it, and the licence that lets anyone show it.

The public demo (sofa/demo.py, docs/public-demo.md) lists a title only when its record passes check() here; the
seed tool (tools/demo-seed.py) writes the records, and refuses a title without one. Any Sofa shows a record on the
title's page when there is one.

    <video name>.rights.json   next to the video: that video's record
    rights.json                in a show's folder (or a movie's): the record for everything in that folder without
                               its own

    {
      "licence": "CC BY 3.0",                            one of LICENCES below, with its version
      "licence_url": "https://creativecommons.org/licenses/by/3.0/",
      "publisher": "Blender Foundation",                 who made it, or who publishes it
      "source": "https://studio.blender.org/films/...",  the page that says so (https)
      "checked": "2026-11-18",                           when someone read that page
      "credit": "...",                                   CC BY and CC BY-SA: the credit the licence asks for
      "basis": "...",                                    public domain and US government work: why it is
      "changes": "...",                                  what was changed (a conversion for browsers), if anything
      "play_url": "https://.../film.mp4"                 where the video itself plays from, at its publisher
    }
"""
import json
import os
import re
import threading

# The licences a public Sofa may show, safest first. Nothing with NC (noncommercial: the demo promotes a product) or
# ND, and nothing "fair use", "free to watch" or "on YouTube".
LICENCES = (
    ("public-domain", re.compile(r"^Public domain$")),
    ("us-government", re.compile(r"^US government work$")),
    ("cc0", re.compile(r"^CC0 1\.0$")),
    ("cc-by", re.compile(r"^CC BY [1-4]\.[05]$")),
    ("cc-by-sa", re.compile(r"^CC BY-SA [1-4]\.[05]$")),
)
CC_URL = re.compile(r"^https://creativecommons\.org/(licenses/by(-sa)?/[1-4]\.[05]|publicdomain/zero/1\.0)/?$")
DATE = re.compile(r"^20\d\d-[01]\d-[0-3]\d$")
_cache = {}
_lock = threading.Lock()


def kind(record):
    """'public-domain', 'us-government', 'cc0', 'cc-by', 'cc-by-sa', or None for anything else."""
    text = str((record or {}).get("licence") or "").strip()
    return next((k for k, rx in LICENCES if rx.match(text)), None)


def problems(record):
    """What's missing or wrong in a record ([] when a public Sofa may show the title)."""
    if not isinstance(record, dict):
        return ["no rights record"]
    out = []
    k = kind(record)
    if not k:
        out.append("licence %r isn't one a public Sofa may show (public domain, US government work, CC0, CC BY, "
                   "CC BY-SA)" % (record.get("licence") or ""))
    if not str(record.get("publisher") or "").strip():
        out.append("no publisher")
    if not str(record.get("source") or "").startswith("https://"):
        out.append("no https page that states the licence (source)")
    if not DATE.match(str(record.get("checked") or "")):
        out.append("no date the source was read (checked, YYYY-MM-DD)")
    if k in ("cc0", "cc-by", "cc-by-sa"):
        url = str(record.get("licence_url") or "")
        if not CC_URL.match(url):
            out.append("no Creative Commons licence address (licence_url)")
        elif ("/by-sa/" in url) != (k == "cc-by-sa") or ("/zero/" in url) != (k == "cc0"):
            out.append("licence_url is a different licence from %r" % record.get("licence"))
    if k in ("cc-by", "cc-by-sa") and not str(record.get("credit") or "").strip():
        out.append("no credit (CC BY asks for one)")
    if k in ("public-domain", "us-government") and len(str(record.get("basis") or "").strip()) < 12:
        out.append("no basis: why it's in the public domain")
    play = record.get("play_url")
    if play and not str(play).startswith("https://"):
        out.append("play_url isn't https")
    return out


def ok(record):
    return not problems(record)


def _load(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_size, st.st_mtime_ns)
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data = data if isinstance(data, dict) else None
    except (OSError, ValueError):
        data = None
    with _lock:
        _cache[path] = (key, data)
    return data


def read(video):
    """The record for a video: its own, or its folder's."""
    stem = os.path.splitext(video)[0]
    return _load(stem + ".rights.json") or _load(os.path.join(os.path.dirname(video), "rights.json"))


def for_folder(folder):
    return _load(os.path.join(folder, "rights.json")) if folder else None


def public(record):
    """What a title's page shows (and the player needs): the record's own fields, nothing else."""
    if not isinstance(record, dict):
        return None
    keep = ("licence", "licence_url", "publisher", "source", "checked", "credit", "basis", "changes", "play_url")
    out = {k: str(record[k])[:600] for k in keep if record.get(k)}
    out["kind"] = kind(record)
    return out
