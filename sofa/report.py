"""A report to send when asking for help: Server → Activity → Download a report.

One plain-text file with what's needed to understand what Sofa is doing: versions and tools,
settings (passwords, keys and tokens left out), folders, the library, what's in the Inbox and
Needs Review, the queues, recent playback problems, the activity log with its details, and the
end of the server log (data/sofa.log). Adult file names are in it only when the admin ticks
"Include Adult details".
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import time

from . import (__version__, auth, config, fetch, intros, live, media, optimize, organizer, previews, store,
               updater)
from .library import LIBRARY

SECRET_WORDS = ("key", "token", "password", "secret", "pin")


def _when(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else "-"


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _size(n):
    return "%.1f GB" % (n / 1e9) if n >= 1e8 else "%.1f MB" % (n / 1e6)


def _tree(root, private, limit=400):
    """Files under root (relative paths, sizes, dates). Adult parts are summed up unless `private`."""
    lines = []
    if not os.path.isdir(root):
        return ["(not there)"]
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        rel = os.path.relpath(d, root)
        if not private and (rel.split(os.sep)[0] in ("XXX", "Adult")):
            n = sum(len(fs) for _d, _s, fs in os.walk(d))
            lines.append("%s/  (%d private file%s, names not included)" % (rel, n, "" if n == 1 else "s"))
            dirs[:] = []
            continue
        for f in sorted(files):
            if f.startswith("."):
                continue
            p = os.path.join(d, f)
            try:
                st = os.stat(p)
                lines.append("%s  %s  %s" % (os.path.normpath(os.path.join(rel, f)), _size(st.st_size), _when(st.st_mtime)))
            except OSError as exc:
                lines.append("%s  (can't read: %s)" % (os.path.join(rel, f), exc.strerror))
            if len(lines) >= limit:
                return lines + ["... (more not listed)"]
    return lines or ["(empty)"]


def _folder(key, path):
    try:
        du = shutil.disk_usage(path)
        free = "%s free of %s" % (_size(du.free), _size(du.total))
    except OSError:
        free = "?"
    return "%-12s %s  [%s%s, %s]" % (key, path, "exists" if os.path.isdir(path) else "MISSING",
                                      ", writable" if os.access(path, os.W_OK) else ", NOT writable" if os.path.isdir(path) else "", free)


def build(admin_name, include_private=False):
    out = []
    add = out.append

    def section(title):
        add("")
        add("=" * 78)
        add(title)
        add("=" * 78)

    add("Sofa report for \"%s\", made %s by %s" % (config.get("name"), _when(time.time()), admin_name))
    add("Passwords, PINs, keys and tokens are not in this report. Adult file names: %s."
        % ("INCLUDED (the admin asked for them)" if include_private else "not included"))

    section("Sofa and this computer")
    from . import web
    u = updater.status()
    add("Sofa %s, %s install%s, running since %s" % (__version__, u.get("method"), (", commit " + u["commit"][:10]) if u.get("commit") else "",
                                                     _when(web.STARTED)))
    add("Updates: latest on GitHub %s; available: %s; last check %s%s" % (u.get("latest") or "?", u.get("available"), _when(u.get("checked")),
                                                                         ("; " + u["rolled_back"]) if u.get("rolled_back") else ""))
    if u.get("error"):
        add("Last update problem: %s" % u["error"])
    add("Python %s at %s" % (sys.version.split()[0], sys.executable))
    mac = platform.mac_ver()[0]
    add("System: %s%s, %s, %d CPUs" % (platform.platform(), (" (macOS %s)" % mac) if mac else "", platform.machine(), os.cpu_count() or 0))
    add("Folders: app %s, data %s" % (config.APP_DIR, config.DATA_DIR))

    section("Tools")
    ff = media.tool("ffmpeg")
    add("ffmpeg: %s  %s" % (ff or "NOT FOUND", (_run([ff, "-version"]).splitlines() or [""])[0] if ff else ""))
    enc = media.encoders()
    add("  video encoders: %s" % ", ".join(sorted(e for e in enc if "264" in e or "265" in e or "hevc" in e)) or "?")
    add("ffprobe: %s" % (media.tool("ffprobe") or "NOT FOUND"))
    add("sips (macOS pictures): %s" % ("yes" if os.access(media.SIPS, os.X_OK) else "no"))
    add("git: %s" % (shutil.which("git") or "no"))
    yt = fetch.tool()
    add("yt-dlp: %s  version %s  run as %s" % (yt or "not installed", fetch.version() if yt else "-", " ".join(fetch._cmd(yt)) if yt else "-"))
    if fetch.install_state.get("error"):
        add("  last install problem: %s" % fetch.install_state["error"])

    section("Settings (data/config.json)")
    for k, v in sorted(config.all_settings().items()):
        if any(w in k.lower() for w in SECRET_WORDS):
            v = "(set)" if v else "(not set)"
        add("%s = %s" % (k, json.dumps(v)))

    section("Folders")
    for key in ("inbox", "shows", "movies", "adult", "music", "musicvideos", "review", "originals"):
        add(_folder(key, config.path(key)))
    add(_folder("deleted", organizer.deleted_root()))

    section("Library")
    add("Counts: %s" % json.dumps(LIBRARY.counts()))
    add("Last read %s, took %ss; reading now: %s; more artwork to fetch: %s" % (_when(LIBRARY.generated), LIBRARY.last_scan_seconds,
                                                                               LIBRARY.scanning, LIBRARY.art_pending))
    for where, why in getattr(LIBRARY, "last_problems", []) or []:
        add("Couldn't read: %s (%s)" % (where, why))
    missing = LIBRARY.missing_details()
    add("Without details: %d" % len(missing))
    for m in missing[:60]:
        if include_private or not m.get("adult"):
            add("  %s: %s%s" % (m["kind"], m["title"], " (%s)" % m["year"] if m.get("year") else ""))
    add("Hover previews: %s" % json.dumps(previews.status(LIBRARY)))
    try:
        st = intros.status(LIBRARY)
        add("Skip Intro: %s" % json.dumps({k: st.get(k) for k in ("seasons", "checked", "intros", "credits", "method", "working")}))
    except Exception as exc:
        add("Skip Intro: (%s)" % exc)

    section("Inbox now (what's waiting, and the files)")
    for p in organizer.pending():
        add("  %s: %s" % (p["name"], p["state"]))
    for line in _tree(config.path("inbox"), include_private):
        add("  " + line)

    section("Needs Review now")
    for line in _tree(config.path("review"), include_private):
        add("  " + line)

    section("Deleted folder")
    add(json.dumps(organizer.deleted_summary()))

    section("Converting to MP4")
    try:
        c = optimize.status(LIBRARY)
        add("Counts: %s" % json.dumps(c.get("counts")))
        for r in c.get("rows", [])[:80]:
            add("  %s | %s | %s%s" % (r.get("state"), r.get("title"), r.get("how") or "", " | " + r["error"] if r.get("error") else ""))
    except Exception as exc:
        add("(%s)" % exc)

    section("Downloads (Save from a link)")
    try:
        d = fetch.status(viewer_adult=include_private)
        for r in d.get("rows", [])[:80]:
            if r.get("adult") and not include_private:
                add("  %s | a private download%s" % (r.get("state"), " | " + r["error"] if r.get("error") else ""))
            else:
                add("  %s | %s | %s%s" % (r.get("state"), r.get("title") or "", r.get("url") or "", " | " + r["error"] if r.get("error") else ""))
    except Exception as exc:
        add("(%s)" % exc)

    section("Live TV lists")
    try:
        for p in live.listing(None, adult=True).get("playlists", []):
            add("  %s: %s channels%s" % (p.get("name"), p.get("count"), " | problem: " + p["error"] if p.get("error") else ""))
    except Exception as exc:
        add("(%s)" % exc)

    section("Playback now, and recent playback problems")
    for s in media.active_streams():
        add("  watching: %s" % json.dumps(s))
    for item_id, e in sorted(media._errors.items(), key=lambda kv: -kv[1]["at"])[:40]:
        item = LIBRARY.item(item_id) or {}
        if item.get("adult") and not include_private:
            add("  %s  a private video: %s" % (_when(e["at"]), e["message"][-300:]))
        else:
            add("  %s  %s: %s" % (_when(e["at"]), item.get("path") or item_id, e["message"][-300:]))

    section("People")
    for p in auth.list_users():
        add("  %s%s%s%s, last seen %s" % (p["name"], " (admin)" if p["admin"] else "", " (guest)" if p["guest"] else "",
                                          " (Adult on)" if p["adult"] else "", _when(p.get("seen"))))

    section("Activity (newest first, with details)")
    for r in store.q("SELECT * FROM activity ORDER BY id DESC LIMIT 2000"):
        detail = r["detail"] or ""
        add("%s  %-9s %s%s" % (_when(r["at"]), r["kind"], r["message"], ("  " + detail) if detail and detail != '{"private": true}' else ""))

    if include_private:
        section("Adult details (data/logs/private.jsonl, newest last)")
        try:
            with open(store.PRIVATE_LOG, encoding="utf-8") as f:
                lines = f.readlines()[-1500:]
            for line in lines:
                e = json.loads(line)
                add("%s  %-9s %s  %s" % (_when(e["at"]), e["kind"], e["message"], json.dumps(e.get("detail"))))
        except (OSError, ValueError):
            add("(none yet)")

    section("Server log (the end of data/sofa.log)")
    try:
        with open(os.path.join(config.DATA_DIR, "sofa.log"), encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-600:]
        out.extend(line.rstrip("\n") for line in tail)
    except OSError:
        add("(no data/sofa.log: Sofa may be running in a Terminal window instead of in the background)")
    add("")
    add("-- end of the report --")
    return "\n".join(out) + "\n"
