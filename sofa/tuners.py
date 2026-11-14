"""Tuners at home: an HDHomeRun on the network gives Live TV its channels, by their own numbers.

A network tuner is a small box on the home network with an antenna or a cable in it. It answers three questions,
and Sofa asks no more of it:

- "Who's there?": a UDP broadcast on port 65001 (SiliconDust's published discovery packet), or `discover.json` at
  an address someone typed. The answer: its id, its name, how many tuners it has, where its channel list is.
- "What can you tune?": `lineup.json`: each channel's number ("5.1"), name, whether it's HD, the codecs, and the
  address that plays it (an MPEG-TS stream over http). Channels marked copy-protected are left out: they don't play.
- A channel's address, opened, is that channel, live, for as long as it's read. Each one open uses one of the box's
  tuners; when all are busy the box says so, and so does Sofa (free()).

Nothing is used until an admin says so: a tuner found on the network is listed as found, and its channels join
Live TV when it's switched on (config "tuners"). A tuner is only ever at a home address; its channels are "home"
channels (sofa/live.py): never listed for the public library's Visitors, never played away from home through this
Sofa, never looked at by the channel checker (a look would take a tuner from someone).

Written to SiliconDust's documentation and tried against a stand-in (tests/stand_in_tuner.py). No real HDHomeRun
has met this code yet.
"""
import hashlib
import json
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
import zlib

from . import config, store

PORT = 65001
REQUEST, REPLY = 0x0002, 0x0003
TAG_TYPE, TAG_ID, TAG_TUNERS, TAG_LINEUP, TAG_BASE = 0x01, 0x02, 0x10, 0x27, 0x2A
TUNER, ANY = 0x00000001, 0xFFFFFFFF
_lock = threading.Lock()
_found = {}                 # id -> device, as last seen on the network
_lineups = {}               # id -> (when, channels)
LINEUP_EVERY = 6 * 3600


# ---------------------------------------------------------------- the discovery packet

def packet(kind, tags):
    """type, length, then tag-length-value triples, then the Ethernet CRC of all of it, little-endian. A length of
    128 or more takes two bytes: the low seven bits with the top bit set, then the rest."""
    def size(n):
        return bytes([n]) if n < 128 else bytes([0x80 | (n & 0x7F), n >> 7])
    body = b"".join(bytes([tag]) + size(len(value)) + value for tag, value in tags)
    frame = struct.pack(">HH", kind, len(body)) + body
    return frame + struct.pack("<I", zlib.crc32(frame) & 0xFFFFFFFF)


def unpack(data):
    """(type, {tag: value}) from a packet, or None when it isn't one (wrong length, wrong CRC)."""
    if len(data) < 8:
        return None
    kind, n = struct.unpack(">HH", data[:4])
    if len(data) != 4 + n + 4 or struct.unpack("<I", data[-4:])[0] != zlib.crc32(data[:-4]) & 0xFFFFFFFF:
        return None
    tags, i, body = {}, 0, data[4:4 + n]
    while i + 2 <= len(body):
        tag, size = body[i], body[i + 1]
        i += 2
        if size & 0x80:                              # lengths of 128 and more take two bytes
            if i >= len(body):
                return None
            size = (size & 0x7F) | (body[i] << 7)
            i += 1
        tags[tag] = body[i:i + size]
        i += size
    return kind, tags


def _home(url):
    from . import live
    return bool(url) and url.startswith(("http://", "https://")) and live.at_home(url)


def discover(timeout=1.5, to=None, port=None):
    """Ask the network who's a tuner. [{"id", "address", "base", "lineup", "tuners"}], one per box that answered."""
    port = port or PORT
    out, seen = [], set()
    ask = packet(REQUEST, [(TAG_TYPE, struct.pack(">I", TUNER)), (TAG_ID, struct.pack(">I", ANY))])
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.3)
        for address in ([to] if to else ["255.255.255.255"]):
            try:
                s.sendto(ask, (address, port))
            except OSError:
                pass
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, peer = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            got = unpack(data)
            if not got or got[0] != REPLY or len(got[1].get(TAG_ID, b"")) != 4:
                continue
            tags = got[1]
            did = "%08X" % struct.unpack(">I", tags[TAG_ID])[0]
            if did in seen:
                continue
            seen.add(did)
            base = tags.get(TAG_BASE, b"").decode("utf-8", "replace") or "http://%s" % peer[0]
            lineup = tags.get(TAG_LINEUP, b"").decode("utf-8", "replace") or base.rstrip("/") + "/lineup.json"
            if not _home(base) or not _home(lineup):   # a "tuner" that points off the home network: not one
                continue
            out.append({"id": did, "address": peer[0], "base": base.rstrip("/"), "lineup": lineup,
                        "tuners": tags[TAG_TUNERS][0] if tags.get(TAG_TUNERS) else 1})
    except OSError:
        pass
    finally:
        try:
            s.close()
        except (OSError, UnboundLocalError):
            pass
    return out


def _json(url, timeout=6):
    """A tuner's answer. Only ever an address at home, asked directly: no proxy, and offline mode (which is about the
    internet) doesn't stop it."""
    if not _home(url):
        raise ValueError("A tuner is on the home network; that address isn't.")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(url, headers={"User-Agent": "Sofa"}), timeout=timeout) as r:
        return json.loads(r.read(4 * 2**20).decode("utf-8", "replace"))


def read(address):
    """A tuner at a typed address ("192.168.1.50", "hdhomerun.local"): what its discover.json says."""
    base = address.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    d = _json(base + "/discover.json")
    if not isinstance(d, dict) or not (d.get("DeviceID") or d.get("LineupURL")):
        raise ValueError("That address didn't answer as a tuner does.")
    lineup = d.get("LineupURL") or base + "/lineup.json"
    if not _home(lineup):
        raise ValueError("That tuner's channel list isn't on the home network.")
    return {"id": str(d.get("DeviceID") or hashlib.sha1(base.encode()).hexdigest()[:8]).upper(),
            "address": urllib.parse.urlsplit(base).hostname, "base": (d.get("BaseURL") or base).rstrip("/"), "lineup": lineup,
            "tuners": int(d.get("TunerCount") or 1), "name": str(d.get("FriendlyName") or "Tuner")[:60],
            "model": str(d.get("ModelNumber") or "")[:40]}


# ---------------------------------------------------------------- the ones this Sofa knows

def known():
    """The tuners an admin has looked at: [{"id", "name", "base", "lineup", "tuners", "on"}] (config "tuners")."""
    return [dict(t) for t in config.get("tuners") or []]


def using():
    return [t for t in known() if t.get("on")]


def device(device_id):
    return next((t for t in known() if t["id"] == device_id), None)


def _save(devices):
    config.update({"tuners": devices})


def find(timeout=1.5, to=None, port=None):
    """Look on the network now. Boxes found are remembered as found (off) so the page can offer them; ones already
    known keep their switch and get their new address if it changed. Returns every known tuner, with "seen"."""
    seen = {}
    for d in discover(timeout, to, port):
        try:
            more = read(d["base"])
        except Exception:
            more = {}
        seen[d["id"]] = dict(d, name=more.get("name") or "Tuner " + d["id"], model=more.get("model") or "",
                             tuners=more.get("tuners") or d["tuners"])
    with _lock:
        _found.clear()
        _found.update(seen)
    devices = known()
    by_id = {t["id"]: t for t in devices}
    for did, d in seen.items():
        if did in by_id:
            by_id[did].update(base=d["base"], lineup=d["lineup"], tuners=d["tuners"], name=by_id[did].get("name") or d["name"])
        else:
            devices.append({"id": did, "name": d["name"], "model": d["model"], "base": d["base"], "lineup": d["lineup"],
                            "tuners": d["tuners"], "on": False})
            store.log("live", "A tuner is on the network: %s (%d tuner%s). Live TV → Tuners turns it on." % (
                d["name"], d["tuners"], "" if d["tuners"] == 1 else "s"))
    _save(devices)
    return [dict(t, seen=t["id"] in seen) for t in devices]


def add(address):
    """A tuner by its address, typed by an admin: known and switched on."""
    d = read(address)
    devices = [t for t in known() if t["id"] != d["id"]]
    devices.append({"id": d["id"], "name": d["name"], "model": d.get("model") or "", "base": d["base"], "lineup": d["lineup"],
                    "tuners": d["tuners"], "on": True})
    _save(devices)
    _lineups.pop(d["id"], None)
    store.log("live", "Tuner added: %s (%d tuner%s)" % (d["name"], d["tuners"], "" if d["tuners"] == 1 else "s"))
    return d


def switch(device_id, on):
    devices = known()
    if not any(t["id"] == device_id for t in devices):
        raise ValueError("That tuner isn't on this Sofa.")
    _save([dict(t, on=bool(on)) if t["id"] == device_id else t for t in devices])
    _lineups.pop(device_id, None)


def remove(device_id):
    _save([t for t in known() if t["id"] != device_id])
    _lineups.pop(device_id, None)


# ---------------------------------------------------------------- its channels

def lineup(dev, force=False):
    """A tuner's channels, as Live TV keeps channels (sofa/live.py): its numbers and names, the address that plays
    each, marked "home" and with the tuner they're on. Asked every few hours; the last answer is kept if it's away."""
    now = time.time()
    with _lock:
        cached = _lineups.get(dev["id"])
    if cached and not force and now - cached[0] < LINEUP_EVERY:
        return cached[1]
    try:
        rows = _json(dev["lineup"])
    except Exception as exc:
        store.log("live", "Couldn't read the tuner \"%s\"'s channels: %s" % (dev.get("name") or dev["id"], str(exc)[:160]))
        return cached[1] if cached else []
    out = []
    for r in rows if isinstance(rows, list) else []:
        url = str(r.get("URL") or "")
        if not _home(url) or r.get("DRM") or "drm" in str(r.get("Tags") or "").lower():
            continue                                  # (copy-protected, or pointing off the home network: left out)
        number, name = str(r.get("GuideNumber") or "").strip(), str(r.get("GuideName") or "").strip()
        out.append({"id": hashlib.sha1(url.encode()).hexdigest()[:12], "url": url, "name": name or "Channel " + number,
                    "guide_number": number, "logo": None, "group": "Antenna", "tvg": None, "geo": False, "adult": False,
                    "headers": {}, "playlist": dev.get("name") or "Tuner", "home": True, "tuner": dev["id"],
                    "hd": bool(r.get("HD")), "video": str(r.get("VideoCodec") or "").upper(), "audio": str(r.get("AudioCodec") or "").upper()})
    out.sort(key=lambda c: ([int(x) if x.isdigit() else 0 for x in c["guide_number"].replace("-", ".").split(".")], c["name"]))
    with _lock:
        _lineups[dev["id"]] = (now, out)
    return out


def channels(force=False):
    """Every channel of the tuners in use."""
    out = []
    for dev in using():
        out += lineup(dev, force)
    return out


def needs_converting(chan):
    """True for a channel no browser plays as it comes: MPEG-2 video (most over-the-air TV), which is also
    interlaced. Sofa converts those as they play; H.264 and HEVC channels are repackaged."""
    return (chan or {}).get("video") in ("MPEG2", "MPEG-2", "")


# ---------------------------------------------------------------- how many are busy

def busy(device_id):
    """Tuners of this box in use right now: one for each channel of its being watched through Sofa, one for each
    recording being made. (Something else in the house using the box isn't counted: the box says so itself.)"""
    from . import dvr, live, media
    watching = 0
    for s in media.active_streams():
        cid = str(s.get("item") or "")
        if cid.startswith("live:"):
            chan = live.channel(cid[5:])
            if chan and chan.get("tuner") == device_id:
                watching += 1
    return watching + sum(1 for r in dvr.recording_now() if r.get("tuner") == device_id)


def free(device_id):
    dev = device(device_id)
    return max(0, int(dev["tuners"]) - busy(device_id)) if dev else 0


def status():
    """For Live TV → Tuners: every known tuner with its switch, its channel count, and how many tuners are free."""
    with _lock:
        seen = set(_found)
    return [dict(t, seen=t["id"] in seen, channels=len(lineup(t)) if t.get("on") else 0,
                 free=free(t["id"]) if t.get("on") else 0) for t in known()]
