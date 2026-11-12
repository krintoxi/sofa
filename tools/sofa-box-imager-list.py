#!/usr/bin/env python3
"""Sofa Box OS's own list for Raspberry Pi Imager (2.0 or newer).

Imager can open a list of operating systems other than Raspberry Pi's (a "content repository"). Ours shows
Sofa Box OS by name, with its icon, for the Pi 3, 4 and 5 only, and gives Imager the card's size and SHA-256
so Imager checks what it wrote. It never offers Imager's OS customisation (init_format "none"): a user made
there stops the TV screen starting, and the box sets itself up on the TV. docs/raspberry-pi-imager.md says why.

    python3 tools/sofa-box-imager-list.py build --repo krintoxi/sofa --cache CACHE.json --out LIST.rpi-imager-manifest
    python3 tools/sofa-box-imager-list.py check LIST.rpi-imager-manifest [--schema os-list-schema.json]
    python3 tools/sofa-box-imager-list.py measure sofa-box-os-1.1.54.img.xz      (a file or an https URL)

build reads the releases on GitHub ("box-os-vX.Y.Z", one per version; "sofa-box-stable", which names the version
marked stable; "sofa-box", the newest card) and lists, top first: the stable version ("(stable)", tried on a real
box) or, while none is marked, the newest; a newer version than the stable one ("(testing)"); the newest card if it
differs from every numbered one ("newest build (testing)"); and the few versions before, in a group. The top entry
always points at a numbered card, whose file never changes. What Imager needs that GitHub doesn't say (the
unpacked card's size and SHA-256) comes
from unpacking each card once; CACHE.json keeps it, by the packed card's SHA-256, so each card is unpacked
once ever. GitHub's workflow (.github/workflows/sofa-box-imager-list.yml) runs it after every card and puts
the list beside the card on the "sofa-box" release.

Standard library only (Python 3.9+).
"""
import argparse
import hashlib
import json
import lzma
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://api.github.com"
GUIDE = "https://github.com/krintoxi/sofa/blob/main/deploy/sofa-box/README.md"
ICON = "https://raw.githubusercontent.com/krintoxi/sofa/main/docs/images/sofa-box-os-icon.png"
ROLLING_TAG = "sofa-box"
ROLLING_CARD = "sofa-box.img.xz"
VERSION_TAG = re.compile(r"^box-os-v(\d+)\.(\d+)\.(\d+)$")
# The stable card's release (tools/sofa-box-releases.py mark-stable) names its version and its card's SHA-256 here
STABLE_TAG = "sofa-box-stable"
STABLE_MARK = re.compile(r"<!-- sofa-box-stable version=(\d+\.\d+\.\d+) sha256=([0-9a-f]{64}) -->")
KEEP = 5                                      # earlier versions listed under "Earlier versions"
CHUNK = 1 << 20
# The boards the card is for, with Raspberry Pi's own tags for them (the same as Raspberry Pi OS Lite 64-bit's).
# Imager draws its "Choose device" step from these: a list without them leaves that step empty.
DEVICES = [
    {"name": "Raspberry Pi 5", "description": "Raspberry Pi 5", "tags": ["pi5-64bit"]},
    {"name": "Raspberry Pi 4", "description": "Raspberry Pi 4 Model B", "tags": ["pi4-64bit"]},
    {"name": "Raspberry Pi 3", "description": "Raspberry Pi 3 Model B+ (with its own 2.5 A power supply)",
     "tags": ["pi3-64bit"]},
]
BOARD_TAGS = [t for d in DEVICES for t in d["tags"]]
DESCRIPTION = "Your own TV box: Sofa, free Live TV, your streaming apps and games. Raspberry Pi OS Lite (64-bit) underneath."
# The same Sofa Box OS for a PC (x86-64), on a USB stick (the card workflow's job "pc"): listed under a device of its
# own, so Imager offers it only for that, and Sofa Box Imager only under "For a PC". Listed only once a release has one.
PC_DEVICE = {"name": "A PC, from a USB stick",
             "description": "A PC or laptop with an Intel or AMD processor (x86-64): Sofa Box OS starts from a USB stick "
                            "of 8 GB or more and runs from it",
             "tags": ["sofa-box-pc-x86_64"]}
PC_TAGS = list(PC_DEVICE["tags"])
PC_VERSION_CARD = "sofa-box-os-%s-pc.img.xz"
PC_ROLLING_CARD = "sofa-box-pc.img.xz"
PC_DESCRIPTION = ("Sofa Box OS for a PC: written to a USB stick, it starts the PC from the stick and runs from it, "
                  "settings and all. Debian 13 underneath. Not tried on a real PC yet: started on GitHub in QEMU, on "
                  "newer (UEFI) and older (BIOS) PCs.")
# What Imager may do to the card. "none": nothing (no user, no Wi-Fi, no SSH from Imager's settings).
INIT_FORMAT = "none"
INIT_FORMATS = ("", "none", "systemd", "cloudinit", "cloudinit-rpi", "rpi-preseed")   # Imager 2.0.12's own
REQUIRED = ("name", "description", "icon", "url", "extract_size", "extract_sha256", "image_download_size",
            "release_date", "devices")
NEVER_SAID = ("internet archive", "archive.org", "adult")          # the box's UI never says these


class ListError(Exception):
    pass


# ---------------------------------------------------------------------------------------------- GitHub
def _get(url, token=None, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "sofa-box-imager-list",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), r.headers.get("Link", "")


def github_releases(repo, token=None):
    """Every release of REPO, newest first, as GitHub's API gives them (drafts only with a token that sees them)."""
    out, url = [], "%s/repos/%s/releases?per_page=100" % (API, repo)
    while url:
        body, link = _get(url, token)
        out.extend(json.loads(body))
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return out


# ---------------------------------------------------------------------------------------------- measuring
def _open(src):
    """A local file, or a public https download. No token: GitHub sends release downloads on to a signed
    address that refuses one."""
    if re.match(r"^https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "sofa-box-imager-list"})
        return urllib.request.urlopen(req, timeout=120)
    return open(src, "rb")


def measure(src, expect_sha256=None):
    """Unpack an .img.xz as it streams in. Returns the packed size and SHA-256 and the unpacked ones (what
    Imager calls image_download_size, extract_size and extract_sha256)."""
    packed, unpacked = hashlib.sha256(), hashlib.sha256()
    sizes = {"packed": 0, "unpacked": 0, "streams": 0}
    state = {"dec": lzma.LZMADecompressor(format=lzma.FORMAT_XZ), "fed": False}

    def feed(buf):
        # The card is mostly empty space: a megabyte packed can be hundreds unpacked, so each step's output
        # is held to a few megabytes. An xz file can also hold several streams one after another (with
        # zero padding between them): each gets a fresh decompressor.
        while True:
            dec = state["dec"]
            if dec.eof:
                buf = (dec.unused_data + buf).lstrip(b"\0")
                sizes["streams"] += 1
                state["dec"], state["fed"] = lzma.LZMADecompressor(format=lzma.FORMAT_XZ), False
                dec = state["dec"]
                if not buf:
                    return
            if buf:
                state["fed"] = True
            out = dec.decompress(buf, max_length=8 * CHUNK)
            buf = b""
            unpacked.update(out)
            sizes["unpacked"] += len(out)
            if dec.eof:
                continue
            if dec.needs_input:
                return

    with _open(src) as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            packed.update(chunk)
            sizes["packed"] += len(chunk)
            feed(chunk)
    dec = state["dec"]
    if dec.eof:
        feed(b"")
    if state["fed"] or sizes["streams"] == 0:
        raise ListError("%s: the xz file ends early" % src)
    packed_size, unpacked_size = sizes["packed"], sizes["unpacked"]
    got = packed.hexdigest()
    if expect_sha256 and got != expect_sha256:
        raise ListError("%s: packed SHA-256 %s, GitHub says %s" % (src, got, expect_sha256))
    return {"image_download_size": packed_size, "image_sha256": got,
            "extract_size": unpacked_size, "extract_sha256": unpacked.hexdigest()}


# ---------------------------------------------------------------------------------------------- the list
def _digest(asset):
    d = asset.get("digest") or ""
    return d[len("sha256:"):] if d.startswith("sha256:") else ""


def _asset(release, name):
    for a in release.get("assets") or []:
        if a.get("name") == name and a.get("state", "uploaded") == "uploaded":
            return a
    return None


def _day(stamp):
    return (stamp or "")[:10]


def _version_key(v):
    return tuple(int(x) for x in v.split("."))


def cards(releases, version_card="sofa-box-os-%s.img.xz", rolling_card=ROLLING_CARD):
    """(numbered, rolling): the numbered cards newest first, and the newest card (or None). Each is a dict
    with version, tag, asset, page and day. The Pi's cards, or with PC_VERSION_CARD and PC_ROLLING_CARD, a PC's."""
    numbered, rolling = [], None
    for rel in releases:
        if rel.get("draft"):
            continue
        tag = rel.get("tag_name") or ""
        m = VERSION_TAG.match(tag)
        if m:
            ver = "%s.%s.%s" % m.groups()
            a = _asset(rel, version_card % ver)
            if a:
                numbered.append({"version": ver, "tag": tag, "asset": a, "page": rel.get("html_url") or "",
                                 "day": _day(rel.get("published_at") or a.get("updated_at"))})
        elif tag == ROLLING_TAG:
            a = _asset(rel, rolling_card)
            if a:
                m = re.search(r"Sofa Box OS (\d+\.\d+\.\d+)", rel.get("name") or "")
                rolling = {"version": m.group(1) if m else "", "tag": tag, "asset": a,
                           "page": rel.get("html_url") or "", "day": _day(a.get("updated_at"))}
    numbered.sort(key=lambda c: _version_key(c["version"]), reverse=True)
    return numbered, rolling


def stable(releases, numbered, log=lambda s: None):
    """The numbered card marked stable (tried on a real box), or None while none is. The "sofa-box-stable" release
    names the version and its card's SHA-256; that version's own card must be that very file."""
    for rel in releases:
        if rel.get("tag_name") != STABLE_TAG or rel.get("draft"):
            continue
        m = STABLE_MARK.search(rel.get("body") or "")
        if not m:
            return None
        for c in numbered:
            if c["version"] == m.group(1):
                if _digest(c["asset"]) and _digest(c["asset"]) != m.group(2):
                    log("Sofa Box OS %s is marked stable with another card (%s): not listed as stable"
                        % (c["version"], m.group(2)))
                    return None
                return c
        log("Sofa Box OS %s is marked stable, but has no card of its own: not listed as stable" % m.group(1))
    return None


def _sums(card, cache, measure_fn, log):
    """What Imager needs for this card, from CACHE (by the packed SHA-256) or by unpacking it once."""
    a = card["asset"]
    key = _digest(a)
    hit = cache.get(key) if key else None
    if hit and hit.get("image_download_size") == a.get("size"):
        return hit
    log("unpacking %s (%s bytes) once, for its size and SHA-256" % (a["name"], a.get("size")))
    got = measure_fn(a["browser_download_url"], key or None)
    if a.get("size") is not None and got["image_download_size"] != a["size"]:
        raise ListError("%s: %d bytes came, GitHub says %d" % (a["name"], got["image_download_size"], a["size"]))
    cache[got["image_sha256"]] = {k: got[k] for k in ("image_download_size", "extract_size", "extract_sha256")}
    return cache[got["image_sha256"]]


def _entry(name, description, card, sums, devices=None, architecture="armv8"):
    return {
        "name": name,
        "description": description,
        "icon": ICON,
        "url": card["asset"]["browser_download_url"],
        "extract_size": sums["extract_size"],
        "extract_sha256": sums["extract_sha256"],
        "image_download_size": sums["image_download_size"],
        "release_date": card["day"],
        "init_format": INIT_FORMAT,
        "devices": list(devices or BOARD_TAGS),
        "architecture": architecture,
        "website": card["page"] or GUIDE,
    }


def build(releases, cache, measure_fn=None, keep=KEEP, log=lambda s: None):
    """The list, from GitHub's releases. CACHE (a dict) gains what had to be unpacked."""
    measure_fn = measure_fn or measure
    numbered, rolling = cards(releases)
    if not numbered and not rolling:
        raise ListError("no Sofa Box OS card on any release")
    os_list, listed = [], []
    steady = stable(releases, numbered, log)
    # On top, the version to keep: the stable one, or the newest while none is marked. Only "(testing)" entries
    # come after it at the top level (Sofa Box Imager takes the first entry without "(testing)" as the one to offer).
    if steady:
        os_list.append(_entry("Sofa Box OS %s (stable)" % steady["version"], DESCRIPTION + " Tried on a real box.",
                              steady, _sums(steady, cache, measure_fn, log)))
        listed.append(steady)
        if numbered[0] is not steady:
            n = numbered[0]
            os_list.append(_entry("Sofa Box OS %s (testing)" % n["version"],
                                  "The newest version, not tried on a real box yet. The stable one above is the one "
                                  "to keep.", n, _sums(n, cache, measure_fn, log)))
            listed.append(n)
    elif numbered:
        os_list.append(_entry("Sofa Box OS %s" % numbered[0]["version"], DESCRIPTION, numbered[0],
                              _sums(numbered[0], cache, measure_fn, log)))
        listed.append(numbered[0])
    # The newest card is the newest version's own file until the box changes on main without a new number.
    # Only then is it listed, as what it is: rebuilt from main, for trying fixes.
    digests = {_digest(c["asset"]) for c in numbered} - {""}
    if rolling and (not digests or _digest(rolling["asset"]) not in digests):
        ver = rolling["version"] or (numbered[0]["version"] if numbered else "")
        name = "Sofa Box OS %s, newest build (testing)" % ver if ver else "Sofa Box OS, newest build (testing)"
        desc = ("Built %s from every change since the last version number, for trying fixes early. It hasn't been "
                "tried on a real box: the version at the top is the one to keep." % rolling["day"])
        os_list.append(_entry(name, desc, rolling, _sums(rolling, cache, measure_fn, log)))
    earlier = [_entry("Sofa Box OS %s" % c["version"], "An earlier version, to go back to if a newer one misbehaves.",
                      c, _sums(c, cache, measure_fn, log)) for c in [c for c in numbered if c not in listed][:keep]]
    if earlier:
        os_list.append({"name": "Sofa Box OS: earlier versions",
                        "description": "%d earlier versions, newest first." % len(earlier),
                        "icon": ICON, "website": "https://github.com/krintoxi/sofa/releases?q=box-os",
                        "subitems": earlier})
    pc = pc_entries(releases, cache, measure_fn, keep, log)
    devices = DEVICES + ([PC_DEVICE] if pc else [])
    return {"imager": {"devices": [dict(d, matching_type="exclusive") for d in devices]}, "os_list": os_list + pc}


def pc_entries(releases, cache, measure_fn, keep=KEEP, log=lambda s: None):
    """A PC's Sofa Box OS (USB sticks), from the same releases: the newest version's, the newest build when it differs,
    and the versions before, in a group. All "(testing)": none has been tried on a real PC yet (the stable mark is
    the Pi card's, tried on a real Pi). Empty while no release has one."""
    numbered, rolling = cards(releases, PC_VERSION_CARD, PC_ROLLING_CARD)
    out = []

    def entry(name, desc, c):
        return _entry(name, desc, c, _sums(c, cache, measure_fn, log), PC_TAGS, "x86_64")
    if numbered:
        out.append(entry("Sofa Box OS %s for a PC (testing)" % numbered[0]["version"], PC_DESCRIPTION, numbered[0]))
    digests = {_digest(c["asset"]) for c in numbered} - {""}
    if rolling and (not digests or _digest(rolling["asset"]) not in digests):
        ver = rolling["version"] or (numbered[0]["version"] if numbered else "")
        out.append(entry("Sofa Box OS %s for a PC, newest build (testing)" % ver if ver else
                         "Sofa Box OS for a PC, newest build (testing)",
                         "Built %s from every change since the last version number, for trying fixes early." % rolling["day"],
                         rolling))
    earlier = [entry("Sofa Box OS %s for a PC (testing)" % c["version"],
                     "An earlier version, to go back to if a newer one misbehaves.", c) for c in numbered[1:keep + 1]]
    if earlier:
        out.append({"name": "Sofa Box OS for a PC: earlier versions",
                    "description": "%d earlier versions, newest first." % len(earlier),
                    "icon": ICON, "website": "https://github.com/krintoxi/sofa/releases?q=box-os",
                    "subitems": earlier})
    return out


# ---------------------------------------------------------------------------------------------- checking
def check(doc, schema=None):
    """Problems with a list (empty when it's right): Imager's required fields and types, our own rules (only
    our boards, no customisation, nothing the box never says), and Imager's JSON schema when given (it needs
    the jsonschema package)."""
    bad = []
    if not isinstance(doc, dict) or not isinstance(doc.get("os_list"), list) or not doc["os_list"]:
        return ["no os_list"]
    devices = ((doc.get("imager") or {}).get("devices")) or []
    if not devices:
        bad.append("imager.devices is empty: Imager's 'Choose device' step would have nothing in it")
    tags = set()
    for d in devices:
        if not d.get("name") or not d.get("description") or not d.get("tags"):
            bad.append("device %r: needs name, description and tags" % d.get("name"))
        tags.update(d.get("tags") or [])

    used = set()

    def leaf(e, where):
        for k in REQUIRED:
            if k not in e:
                bad.append("%s: no %s" % (where, k))
        for k in ("extract_size", "image_download_size"):
            if not isinstance(e.get(k), int) or isinstance(e.get(k), bool) or e.get(k, 0) <= 0:
                bad.append("%s: %s must be a whole number of bytes" % (where, k))
        if isinstance(e.get("extract_size"), int) and isinstance(e.get("image_download_size"), int) \
                and e["extract_size"] <= e["image_download_size"]:
            bad.append("%s: extract_size must be the unpacked size (bigger than the download)" % where)
        if not re.match(r"^[0-9a-f]{64}$", str(e.get("extract_sha256", ""))):
            bad.append("%s: extract_sha256 must be 64 lowercase hex digits" % where)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(e.get("release_date", ""))):
            bad.append("%s: release_date must be YYYY-MM-DD" % where)
        for k in ("url", "icon"):
            if not str(e.get(k, "")).startswith("https://"):
                bad.append("%s: %s must be https" % (where, k))
        if not str(e.get("url", "")).endswith(".img.xz"):
            bad.append("%s: url must be an .img.xz card" % where)
        if e.get("init_format", "") not in INIT_FORMATS:
            bad.append("%s: init_format %r isn't one Imager knows (it drops the entry)" % (where, e.get("init_format")))
        elif e.get("init_format") != INIT_FORMAT:
            bad.append("%s: init_format must be %r: the list offers none of Imager's settings until they've been "
                       "tried on a real box (docs/raspberry-pi-imager.md)" % (where, INIT_FORMAT))
        devs = e.get("devices")
        if not isinstance(devs, list) or not devs:
            bad.append("%s: devices must list the boards" % where)
        else:
            for t in devs:
                if t not in tags:
                    bad.append("%s: device %r isn't in imager.devices" % (where, t))
            used.update(devs)

    for i, e in enumerate(doc["os_list"]):
        where = "os_list[%d] %s" % (i, e.get("name", "?"))
        if "subitems" in e:
            if not e.get("name") or not e.get("description") or not isinstance(e["subitems"], list) or not e["subitems"]:
                bad.append("%s: a group needs a name, a description and subitems" % where)
                continue
            for j, s in enumerate(e["subitems"]):
                if "subitems" in s or "subitems_url" in s:
                    bad.append("%s/%d: one level of groups only (Imager before 1.7 mishandles more)" % (where, j))
                else:
                    leaf(s, "%s/%d %s" % (where, j, s.get("name", "?")))
        else:
            leaf(e, where)
    for d in devices:
        if not set(d.get("tags") or []) & used:
            bad.append("device %r: no card is listed for it" % d.get("name"))

    text = json.dumps(doc).lower()
    for word in NEVER_SAID:
        if word in text:
            bad.append("the list says %r" % word)

    if schema is not None:
        import jsonschema                                           # only where it's installed (the workflow)
        for err in sorted(jsonschema.Draft7Validator(schema).iter_errors(doc), key=lambda e: list(e.path)):
            bad.append("schema: %s: %s" % ("/".join(str(p) for p in err.path), err.message))
    return bad


# ---------------------------------------------------------------------------------------------- command line
def _load_json(path, default):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _write_json(path, doc):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="make the list from GitHub's releases")
    b.add_argument("--repo", default="krintoxi/sofa")
    b.add_argument("--releases", help="releases JSON already fetched (instead of asking GitHub)")
    b.add_argument("--cache", required=True, help="sizes and SHA-256s already worked out (read, then updated)")
    b.add_argument("--out", required=True)
    b.add_argument("--keep", type=int, default=KEEP, help="earlier versions to list (default %d)" % KEEP)
    c = sub.add_parser("check", help="check a list")
    c.add_argument("list")
    c.add_argument("--schema", help="Raspberry Pi Imager's os-list-schema.json (needs the jsonschema package)")
    m = sub.add_parser("measure", help="the sizes and SHA-256s of one card")
    m.add_argument("card")
    a = p.parse_args(argv)
    log = lambda s: print(s, file=sys.stderr, flush=True)                           # noqa: E731
    try:
        if a.cmd == "measure":
            print(json.dumps(measure(a.card), indent=2))
        elif a.cmd == "check":
            schema = _load_json(a.schema, None) if a.schema else None
            bad = check(_load_json(a.list, None), schema)
            for line in bad:
                print(line)
            if bad:
                return 1
            print("%s: right" % a.list)
        else:
            token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            releases = _load_json(a.releases, None) if a.releases else github_releases(a.repo, token)
            cache = _load_json(a.cache, {})
            try:
                doc = build(releases, cache, keep=a.keep, log=log)
            finally:
                _write_json(a.cache, cache)                     # what was unpacked is kept even if a later card failed
            bad = check(doc)
            if bad:
                raise ListError("the list came out wrong:\n  " + "\n  ".join(bad))
            _write_json(a.out, doc)
            for e in doc["os_list"]:
                for s in e.get("subitems", [e]):
                    log("%s  %s  %s" % (s["release_date"], s["name"], s["url"]))
    except (ListError, OSError, ValueError) as e:
        print("sofa-box-imager-list: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
