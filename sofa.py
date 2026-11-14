#!/usr/bin/env python3
"""Sofa home media server.

    python3 sofa.py serve              run the server (what the background service does)
    python3 sofa.py scan               re-read the library now
    python3 sofa.py inbox              file away whatever is in the Inbox now
    python3 sofa.py adduser NAME       add a viewer (--admin for an admin)
    python3 sofa.py passwd NAME        change someone's password
    python3 sofa.py status             show what the server sees
    python3 sofa.py encoders           test this computer's video conversion now: the graphics chip, the processor
    python3 sofa.py backup             back up accounts, watch history and settings now
    python3 sofa.py restore FILE       restore a backup (stop the server first)
    python3 sofa.py selftest           start the parts of Sofa once, without serving (updates use it)
"""
import getpass
import json
import os
import subprocess
import sys
import tarfile
import threading
import time

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
CODE = ("sofa", "client", "deploy", "tools", "docs", "integrations", "sofa.py", "README.md", "LICENSE", "NOTICE", "TRADEMARKS.md", ".gitignore")


def _swapper():
    """sofa/swap.py, loaded on its own (only the standard library), from wherever it is now: an update cut off
    between two renames may have sofa/ itself moved aside, in .sofa-old (whose copy, the version before's, wrote
    the swap's journal and is tried first)."""
    import importlib.util
    for where in (os.path.join(APP, ".sofa-old"), APP):
        path = os.path.join(where, "sofa", "swap.py")
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location("sofa_swap_at_start", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def finish_swap():
    """An update swaps Sofa's code by renames (sofa/swap.py). Cut off part way (a power cut, a restart), the version
    before is put back here, whole, before anything of the new code is loaded."""
    for name in os.listdir(APP):
        if name.startswith(".sofa-restore-"):                     # (a saved copy being unpacked when it was cut off)
            import shutil
            shutil.rmtree(os.path.join(APP, name), ignore_errors=True)
    if not any(os.path.lexists(os.path.join(APP, n)) for n in (".sofa-old", ".sofa-new", ".sofa-old-done", ".sofa-undone")):
        return
    try:
        mod = _swapper()
        if mod and mod.recover(APP):
            print("An update was cut off part way, so the version before was put back.", flush=True)
            data = os.environ.get("SOFA_DATA", os.path.join(APP, "data"))
            try:
                os.remove(os.path.join(data, "update-check.json"))     # (no new version to watch)
            except OSError:
                pass
    except Exception as exc:
        print("Finishing an update didn't work: %r" % (exc,), flush=True)


def restore_snapshot(snapshot):
    """The code from a saved copy (data/backups/code-*.tar.gz), switched in by renames like an update."""
    import tempfile
    with tempfile.TemporaryDirectory(dir=APP, prefix=".sofa-restore-") as tmp:
        with tarfile.open(snapshot) as tar:
            for t in tar.getmembers():
                if t.name.startswith("/") or ".." in t.name.split("/"):
                    raise RuntimeError("the saved copy has odd paths: %s" % t.name)
            tar.extractall(tmp)
        mod = _swapper()
        if mod is None:
            raise RuntimeError("sofa/swap.py is missing")
        mod.replace_with(APP, tmp, [n for n in CODE if os.path.lexists(os.path.join(tmp, n))])


def watch_update():
    """Right after an update, data/update-check.json is there. If the new version keeps stopping
    (a fourth start within its first minute and a half), go back to the version before by itself.
    Only the standard library here, so this works however broken the new code is."""
    data = os.environ.get("SOFA_DATA", os.path.join(APP, "data"))
    mark = os.path.join(data, "update-check.json")
    try:
        with open(mark, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return
    m["starts"] = int(m.get("starts", 0)) + 1
    if m["starts"] <= 3:
        with open(mark, "w", encoding="utf-8") as f:
            json.dump(m, f)
        return
    print("Sofa %s keeps stopping: going back to %s." % (m.get("to") or "(new)", m.get("from") or "the version before"), flush=True)
    try:
        if m.get("commit") and os.path.isdir(os.path.join(APP, ".git")):
            subprocess.run(["git", "-C", APP, "reset", "--hard", m["commit"]], check=True, capture_output=True)
        elif m.get("snapshot") and os.path.isfile(m["snapshot"]):
            restore_snapshot(m["snapshot"])
        with open(os.path.join(data, "update-rolled-back.json"), "w", encoding="utf-8") as f:
            json.dump({"at": int(time.time()), "to": m.get("to"), "back_to": m.get("from")}, f)
    except Exception as exc:
        print("Going back didn't work: %r. The old code is in %s." % (exc, m.get("snapshot")), flush=True)
    finally:
        try:
            os.remove(mark)
        except OSError:
            pass
    again = [os.path.join(APP, "sofa.py")] + sys.argv[1:]
    if os.name == "nt":                  # no execv in place on Windows (sofa/windows.py says how instead)
        sys.path.insert(0, APP)
        from sofa import windows
        windows.start_again(again)
    os.execv(sys.executable, [sys.executable] + again)


def utf8_on_windows():
    """Windows: Sofa runs in Python's UTF-8 mode, so text is UTF-8 the way it is on a Mac or Linux (names of shows,
    the log's arrows, files written without naming an encoding), not the PC's old code page. A Python started
    without it starts Sofa again with it."""
    if os.name != "nt" or sys.flags.utf8_mode or os.environ.get("SOFA_NO_UTF8_RESTART"):
        return
    env = dict(os.environ, PYTHONUTF8="1", SOFA_NO_UTF8_RESTART="1")
    try:
        sys.exit(subprocess.call([sys.executable, "-X", "utf8", os.path.abspath(__file__)] + sys.argv[1:], env=env))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    utf8_on_windows()
if __name__ == "__main__" and sys.argv[1:2] == ["serve"]:
    finish_swap()
    watch_update()

from sofa import __version__, apps, auth, awake, ddns, tls, upnp, backup, config, discovery, dlna, organizer, store, updater, watcher, web, windows  # noqa: E402
from sofa.library import LIBRARY  # noqa: E402

windows.retry_file_moves()          # (Windows only: see sofa/windows.py)


class Stamped:
    """Every line Sofa writes to its log (data/sofa.log in the background) starts with the date and time.
    With "Keep no logs" on (Server → Privacy) nothing is written at all."""
    quiet = staticmethod(lambda: False)

    def __init__(self, stream):
        self.stream, self.fresh = stream, True

    def write(self, text):
        if self.quiet():
            return len(text)
        parts = []
        for line in text.splitlines(True):
            if self.fresh:
                parts.append(time.strftime("[%Y-%m-%d %H:%M:%S] "))
            parts.append(line)
            self.fresh = line.endswith("\n")
        self.stream.write("".join(parts))
        return len(text)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def thread_crashed(args):
    """A background part of Sofa stopped with an error: the whole story goes in the log, a line in Activity."""
    import traceback
    if args.exc_type is SystemExit:
        return
    print("Error in %s:\n%s" % (args.thread.name if args.thread else "a background task",
                                "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))), file=sys.stderr, flush=True)
    try:
        store.log("error", "%s stopped: %s" % (args.thread.name if args.thread else "A background task", args.exc_value))
    except Exception:
        pass


def stop_cleanly():
    """What SIGTERM does on a Mac or Linux, for Windows: Sofa says goodbye on the network and stops."""
    print("Sofa is stopping (asked by the Sofa app).", flush=True)
    for part in (discovery.stop, awake.stop, lambda: dlna.notify("ssdp:byebye")):
        try:
            part()
        except Exception:
            pass
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


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
    for key in ("shows", "movies", "music", "musicvideos", "inbox"):
        os.makedirs(config.path(key), exist_ok=True)

    if cmd == "serve":
        Stamped.quiet = staticmethod(store.no_logs)
        sys.stdout, sys.stderr = Stamped(sys.stdout), Stamped(sys.stderr)
        threading.excepthook = thread_crashed
        if windows.watch_stop_event(stop_cleanly):        # Windows: the Sofa app asks for a clean stop this way
            print("Run by the Sofa app in the notification area.", flush=True)
        print("Python %s at %s" % (sys.version.split()[0], sys.executable), flush=True)
        # Answer straight away; the library is read in the background (a big one takes a while).
        print("Sofa %s is starting." % __version__, flush=True)
        for part in (dlna.start, discovery.start, watcher.start, apps.start, awake.start, tls.start, ddns.start, upnp.start):
            try:
                part()
            except Exception as exc:     # keep going: the Server page is how anyone finds out what's wrong
                print("Starting %s failed: %r" % (part.__module__, exc), flush=True)
                store.log("error", "Starting %s: %s" % (part.__module__, exc))
        print("Open http://%s:%d on any device at home." % ((dlna.lan_addresses() or ["localhost"])[0], config.get("port")),
              flush=True)
        confirm = threading.Timer(90, updater.confirm_update)   # it ran for a minute and a half: the update is good
        confirm.daemon = True
        confirm.start()
        if auth.user_count() == 0:
            print("No accounts yet: the first person to open that address creates the admin account.", flush=True)
        web.serve()
    elif cmd == "scan":
        LIBRARY.scan("command line")
        print(json.dumps(LIBRARY.counts()))
    elif cmd == "inbox":
        organizer.SETTLE_SECONDS = 0
        organizer.process_inbox()          # first look records sizes
        print("Filed %d item(s)." % organizer.process_inbox())
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
    elif cmd == "selftest":
        # Before Sofa switches to a new version, the running one asks the new one to do this.
        import urllib.request
        srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        for path in ("/healthz", "/", "/client/app.js", "/client/sofa.css"):
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (srv.server_address[1], path), timeout=30) as r:
                if r.status != 200:
                    raise SystemExit("%s answered %d" % (path, r.status))
        LIBRARY.scan("checking a new version", quick=True)
        srv.shutdown()
        print("SELFTEST OK %s %s" % (__version__, json.dumps(LIBRARY.counts())))
    elif cmd == "status":
        LIBRARY.scan("status check")
        print(json.dumps(web.admin_status(), indent=2, default=str))
    elif cmd == "encoders":
        from sofa import machine
        print("\n".join(machine.report(test=True)))
    else:
        print("Unknown command %r.\n%s" % (cmd, __doc__))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
