#!/usr/bin/env python3
"""Sofa home media server.

    python3 sofa.py serve              run the server (what the background service does)
    python3 sofa.py scan               re-read the library now
    python3 sofa.py inbox              file away whatever is in the Inbox now
    python3 sofa.py adduser NAME       add a viewer (--admin for an admin)
    python3 sofa.py passwd NAME        change someone's password
    python3 sofa.py status             show what the server sees
    python3 sofa.py backup             back up accounts, watch history and settings now
    python3 sofa.py restore FILE       restore a backup (stop the server first)
"""
import getpass
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sofa import __version__, auth, backup, config, dlna, organizer, store, watcher, web  # noqa: E402
from sofa.library import LIBRARY  # noqa: E402


def ask_password():
    while True:
        a = getpass.getpass("Password (8+ characters): ")
        if len(a) < 8:
            print("Too short.")
            continue
        if getpass.getpass("Again: ") == a:
            return a
        print("Those didn't match.")


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    config.load()
    for key in ("shows", "movies", "inbox"):
        os.makedirs(config.path(key), exist_ok=True)

    if cmd == "serve":
        print("Sofa %s: reading the library..." % __version__, flush=True)
        LIBRARY.scan("server start")
        print("Library: %s" % json.dumps(LIBRARY.counts()), flush=True)
        dlna.start()
        watcher.start()
        print("Open http://%s:%d on any device at home." % ((dlna.lan_addresses() or ["localhost"])[0], config.get("port")),
              flush=True)
        if auth.user_count() == 0:
            print("No accounts yet: the first person to open that address creates the admin account.", flush=True)
        web.serve()
    elif cmd == "scan":
        LIBRARY.scan("command line")
        print(json.dumps(LIBRARY.counts()))
    elif cmd == "inbox":
        organizer.SETTLE_SECONDS = 0
        organizer.process_inbox()          # first look records sizes
        print("Filed %d video(s)." % organizer.process_inbox())
        for a in store.recent_activity(10, kinds={"inbox", "review"}):
            print(" -", a["message"])
    elif cmd in ("adduser", "passwd"):
        if not rest:
            print("Usage: sofa.py %s NAME" % cmd)
            return 2
        name = rest[0]
        row = store.q1("SELECT id FROM users WHERE name = ?", name)
        if cmd == "adduser":
            if row:
                print("%s already exists." % name)
                return 1
            auth.create_user(name, ask_password(), admin="--admin" in rest)
            print("Added %s." % name)
        else:
            if not row:
                print("No account named %s." % name)
                return 1
            auth.set_password(row["id"], ask_password())
            print("Password changed; %s will need to sign in again." % name)
    elif cmd == "backup":
        print("Saved %s" % backup.make("command line"))
    elif cmd == "restore":
        if not rest or not os.path.isfile(rest[0]):
            print("Usage: sofa.py restore data/backups/sofa-backup-....tar.gz  (stop the server first)")
            return 2
        manifest, aside = backup.restore(rest[0])
        print("Restored the backup from %s (%s). The previous data is in %s. Start the server again."
              % (time.strftime("%Y-%m-%d %H:%M", time.localtime(manifest["made"])),
                 ", ".join("%d %s" % (v, k) for k, v in manifest["counts"].items()), aside))
    elif cmd == "status":
        LIBRARY.scan("status check")
        print(json.dumps(web.admin_status(), indent=2, default=str))
    else:
        print("Unknown command %r.\n%s" % (cmd, __doc__))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
