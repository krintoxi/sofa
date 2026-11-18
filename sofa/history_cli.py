"""python3 sofa.py import: bring watch history from Plex, Jellyfin or Emby into Sofa from the command line.

    python3 sofa.py import plex-db PATH        a copy of Plex's com.plexapp.plugins.library.db (every Plex user)
    python3 sofa.py import plex URL            Plex's address; the token is asked for, hidden (or SOFA_IMPORT_TOKEN)
    python3 sofa.py import jellyfin URL        Jellyfin's or Emby's address; the API key is asked for, hidden
                                               (or SOFA_IMPORT_TOKEN)
    python3 sofa.py import jellyfin-db PATH    Jellyfin's data folder, or its jellyfin.db or library.db

    --map "FROM=>TO"     where the source's folders are on this computer (as many as needed):
                         --map "/data/movies=>/Volumes/Media/Movies"
    --user "NAME=>PROFILE"   whose history goes to which Sofa profile (as many as needed); without it, a source user
                         goes to the Sofa profile of the same name, if there is one. "NAME=>" leaves someone out.
    --write              import. Without it nothing is written: it says what would happen (a dry run).
    --list               with the dry run, every title that didn't match or conflicts, not just the counts

A token or key is never taken on the command line (it would stay in the shell's history), never written anywhere,
and used for this one read only.
"""
import getpass
import os
import sys

from . import history


def _pairs(values, what):
    out = []
    for v in values:
        for sep in ("=>", "->", "→", "="):
            if sep in v:
                a, _, b = v.partition(sep)
                out.append((a.strip(), b.strip()))
                break
        else:
            raise history.Problem("%s needs FROM=>TO, not %r." % (what, v))
    return out


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    source, rest = argv[0], argv[1:]
    if source not in history.SOURCES:
        print("Unknown source %r: plex-db, plex, jellyfin or jellyfin-db.\n%s" % (source, __doc__))
        return 2
    where, maps, users, write, listing = None, [], [], False, False
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--map", "--user") and i + 1 < len(rest):
            (maps if a == "--map" else users).append(rest[i + 1])
            i += 2
            continue
        if a == "--write":
            write = True
        elif a == "--list":
            listing = True
        elif a.startswith("--"):
            print("Unknown option %r.\n%s" % (a, __doc__))
            return 2
        elif where is None:
            where = a
        else:
            print("One source at a time (%r is extra)." % a)
            return 2
        i += 1
    if not where:
        print("Say where: a file or folder for %s." % source if source.endswith("-db") else
              "Say where: the server's address, like http://192.168.1.20:8096.")
        return 2
    try:
        secret = None
        if not source.endswith("-db"):
            secret = os.environ.get("SOFA_IMPORT_TOKEN") or getpass.getpass(
                "Plex token (hidden): " if source == "plex" else "Jellyfin or Emby API key (hidden): ")
        pairs = history.parse_map(_pairs(maps, "--map"))
        from .library import LIBRARY
        if not LIBRARY.generated:
            LIBRARY.scan("history import", quick=True)
        data = history.read(source, path=where if source.endswith("-db") else None,
                            url=None if source.endswith("-db") else where, secret=secret)
        secret = None
        mapping = history.suggest(data["users"])
        names = {p["name"].casefold(): p["id"] for p in history.profiles()}
        for name, profile in _pairs(users, "--user"):
            keys = [u["key"] for u in data["users"] if str(u["name"]).casefold() == name.casefold() or u["key"] == name]
            if not keys:
                raise history.Problem("Nobody called %r in %s (there's %s)." % (
                    name, data["source"], ", ".join(u["name"] for u in data["users"]) or "nobody"))
            if profile and profile.casefold() not in names:
                raise history.Problem("No Sofa profile called %r." % profile)
            for k in keys:
                mapping[k] = names.get(profile.casefold()) if profile else None
        plan = history.plan(data, mapping, pairs)
        print(report(history.summary(plan, adult_ok=False), listing))
        if not write:
            print("\nNothing was written. Add --write to import.")
            return 0
        done = history.apply(plan)
        print("\nImported: %d watched or started, %d likes, for %d profile%s." % (
            done["progress"], done["likes"], done["profiles"], "" if done["profiles"] == 1 else "s"))
        return 0
    except history.Problem as exc:
        print(exc)
        return 1


def report(s, listing=False):
    lines = ["%s (%s): %d titles with history, %d found in Sofa (%d by path, %d by id, %d by title)." % (
        s["source"], s["how"], s["titles"], s["found"], s["by"]["path"], s["by"]["ids"], s["by"]["title"])]
    lines += ["  " + n for n in s["notes"]]
    for u in s["users"]:
        to = u["profile_name"] or "nobody (left out)"
        flag = " [had limits there]" if u["kids"] else ""
        lines.append("\n%s%s -> %s" % (u["name"], flag, to))
        m = u["matched"]
        lines.append("  %d titles: %d by path, %d by id, %d by title; %d not in Sofa; %d conflicts; %d skipped" % (
            u["titles"], m["path"], m["ids"], m["title"], u["unmatched"], u["conflicts"], u["skipped"]))
        if u["profile"]:
            lines.append("  to write: %d; already the same in Sofa: %d" % (u["new"], u["same"]))
        if listing:
            for t in u["lists"]["unmatched"]:
                lines.append("    not in Sofa: %s" % t)
            for c in u["lists"]["conflicts"] + u["lists"]["skipped"]:
                lines.append("    %s: %s" % (c["title"], c["why"]))
    lines.append("\nIn all: %d places to write, %d likes to add." % (s["writes"], s["likes"]))
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
