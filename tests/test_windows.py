"""Sofa on Windows (sofa/windows.py, sofa/winapp.py, tools/windows-deps.py, deploy/windows).

The parts that are plain logic run everywhere: the app's keeping the server running (with a stand-in server), what
the installer's Python and ffmpeg are unpacked to, where ffmpeg is looked for, how a restart is asked for. The rest
runs only on Windows (GitHub's Windows machines, .github/workflows/tests.yml): Windows' own Bonjour, staying awake,
the drive letters, the port being Sofa's alone, the server in a job object stopped cleanly, and the app in the
notification area started, asked and quit the way the Start menu, "start with Windows" and the installer do it."""
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile
from unittest import mock

import tests
from sofa import config, media, places, windows, winapp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = os.name == "nt"


def load_deps():
    spec = importlib.util.spec_from_file_location("windows_deps", os.path.join(ROOT, "tools", "windows-deps.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for(check, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.5)
    return False


def answers(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------- everywhere

class FakeServer:
    """What Keeper sees of a server: started, running or not, and the code it stopped with."""
    made = []

    def __init__(self):
        self.code, self.started, self.stopped = None, 0, False
        FakeServer.made.append(self)

    def start(self):
        self.started += 1
        return 1000 + len(FakeServer.made)

    def running(self):
        return self.code is None and not self.stopped

    def exit_code(self):
        return self.code

    def stop(self, timeout=15):
        self.stopped = True

    def close(self):
        pass


class KeepingItRunning(unittest.TestCase):
    """winapp.Keeper: what launchd's KeepAlive and ThrottleInterval do on a Mac, done by the app on Windows."""

    def setUp(self):
        FakeServer.made = []
        self.keeper = winapp.Keeper(FakeServer, throttle=15, give_up=(5, 120))

    def test_starting_then_running_once_it_answers(self):
        self.keeper.start()
        self.assertEqual(self.keeper.tick(now=100, answering=lambda: False), "starting")
        self.assertEqual(self.keeper.tick(now=101, answering=lambda: True), "running")
        self.assertEqual(self.keeper.tick(now=102, answering=lambda: False), "running")   # busy isn't stopped
        self.assertEqual(len(FakeServer.made), 1)

    def test_an_update_starts_it_again_at_once(self):
        self.keeper.start()
        FakeServer.made[-1].code = windows.RESTART_CODE
        self.keeper.tick(now=100, answering=lambda: False)
        self.assertEqual(len(FakeServer.made), 2)                 # no waiting: the new code starts straight away
        self.assertEqual(self.keeper.state, "starting")

    def test_a_stop_by_itself_waits_fifteen_seconds(self):
        self.keeper.start()
        FakeServer.made[-1].code = 1
        self.assertEqual(self.keeper.tick(now=100), "waiting")
        self.assertEqual(self.keeper.tick(now=110), "waiting")
        self.assertEqual(len(FakeServer.made), 1)
        self.assertEqual(self.keeper.tick(now=115.5, answering=lambda: False), "starting")
        self.assertEqual(len(FakeServer.made), 2)

    def test_five_stops_in_two_minutes_and_it_waits_for_you(self):
        self.keeper.start()
        now = 100
        for _ in range(4):
            FakeServer.made[-1].code = 1
            self.assertEqual(self.keeper.tick(now=now), "waiting")
            now += 16
            self.keeper.tick(now=now, answering=lambda: False)
        FakeServer.made[-1].code = 1
        self.assertEqual(self.keeper.tick(now=now), "failing")
        self.assertFalse(self.keeper.wanted)
        self.assertEqual(self.keeper.tick(now=now + 60), "failing")       # left stopped
        self.keeper.start()                                                  # Start Sofa from the menu
        self.assertEqual(self.keeper.state, "starting")

    def test_stop_and_restart(self):
        self.keeper.start()
        first = FakeServer.made[-1]
        self.keeper.restart()
        self.assertTrue(first.stopped)
        self.assertEqual(len(FakeServer.made), 2)
        self.keeper.stop()
        self.assertTrue(FakeServer.made[-1].stopped)
        self.assertEqual(self.keeper.tick(now=500), "stopped")
        self.assertEqual(len(FakeServer.made), 2)


class Restarting(unittest.TestCase):
    """After an update Sofa starts again with the new code: in place elsewhere, by the app on Windows."""

    def test_run_by_the_app_it_asks_the_app(self):
        with mock.patch.object(windows, "supervised", lambda: True), \
                mock.patch("os._exit", side_effect=SystemExit) as leave, mock.patch("subprocess.Popen") as popen:
            with self.assertRaises(SystemExit):
                windows.start_again(["sofa.py", "serve"])
        leave.assert_called_once_with(windows.RESTART_CODE)
        popen.assert_not_called()

    def test_run_by_hand_it_starts_the_next_one_itself(self):
        with mock.patch.object(windows, "supervised", lambda: False), \
                mock.patch("os._exit", side_effect=SystemExit) as leave, mock.patch("subprocess.Popen") as popen:
            with self.assertRaises(SystemExit):
                windows.start_again(["sofa.py", "serve"])
        leave.assert_called_once_with(0)
        self.assertEqual(popen.call_args[0][0], [sys.executable, "sofa.py", "serve"])


class WhereFfmpegIs(unittest.TestCase):
    def test_the_ffmpeg_sofa_brought_comes_first(self):
        app = tempfile.mkdtemp(prefix="sofa-app-")
        exe = os.path.join(app, "vendor", "ffmpeg", "bin", "ffmpeg.exe" if WINDOWS else "ffmpeg")
        os.makedirs(os.path.dirname(exe))
        with open(exe, "wb") as f:
            f.write(b"stand-in")
        os.chmod(exe, 0o755)
        with mock.patch.object(config, "APP_DIR", app), mock.patch("shutil.which", lambda name: None):
            self.assertEqual(media.tool("ffmpeg"), exe)
            self.assertFalse((media.tool("ffprobe") or "").startswith(app))      # (not there: not made up)

    def test_background_work_gives_way(self):
        cmd, extra = media.gently(["ffmpeg", "-i", "x"])
        if WINDOWS:
            self.assertEqual((cmd, extra), (["ffmpeg", "-i", "x"], {"creationflags": windows.BELOW_NORMAL_PRIORITY_CLASS}))
        else:
            self.assertEqual(extra, {})
            self.assertEqual(cmd[-3:], ["ffmpeg", "-i", "x"])


class Drives(unittest.TestCase):
    def test_inside_a_folder_or_a_drive(self):
        base = os.path.abspath(os.sep)                            # / here, C:\ on Windows: ends in a separator
        self.assertTrue(places._within(os.path.join(base, "Sofa Library"), base))
        self.assertTrue(places._within(base, base))
        lib = os.path.join(base, "Media", "Sofa")
        self.assertTrue(places._within(os.path.join(lib, "Shows"), lib))
        self.assertFalse(places._within(os.path.join(base, "Media", "Sofa Two"), lib))


class WhatTheInstallerCarries(unittest.TestCase):
    """tools/windows-deps.py with stand-in downloads: Python told where Sofa is, ffmpeg without ffplay, and a download
    that isn't the expected file refused."""

    def setUp(self):
        self.deps = load_deps()
        self.dir = tempfile.mkdtemp(prefix="sofa-deps-")

    def zip(self, name, members):
        path = os.path.join(self.dir, name)
        with zipfile.ZipFile(path, "w") as z:
            for n, data in members.items():
                z.writestr(n, data)
        return path

    def test_python_finds_sofa(self):
        archive = self.zip("py.zip", {"python.exe": "x", "pythonw.exe": "x", "python314.zip": "x",
                                      "python314._pth": "python314.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n"})
        dest = os.path.join(self.dir, "vendor", "python")
        self.deps.unpack_python(archive, dest)
        with open(os.path.join(dest, "python314._pth"), encoding="utf-8", newline="") as f:
            lines = f.read().split("\r\n")
        self.assertEqual(lines[:3], ["python314.zip", ".", "..\\.."])
        self.assertIn("#import site", lines)                       # (site stays off: nothing from outside)
        self.deps.unpack_python(archive, dest)                     # again: the same, not a second line
        with open(os.path.join(dest, "python314._pth"), encoding="utf-8") as f:
            self.assertEqual(f.read().count("..\\.."), 1)

    def test_ffmpeg_without_ffplay_and_with_its_licence(self):
        top = "ffmpeg-9.0.2-full_build-shared/"
        archive = self.zip("ff.zip", {top + "bin/ffmpeg.exe": "x", top + "bin/ffprobe.exe": "x", top + "bin/ffplay.exe": "x",
                                      top + "bin/avcodec-63.dll": "x", top + "LICENSE": "GPL", top + "README.txt": "libs",
                                      top + "include/libavcodec/avcodec.h": "x", top + "doc/ffmpeg.html": "x"})
        dest = os.path.join(self.dir, "vendor", "ffmpeg")
        self.deps.unpack_ffmpeg(archive, dest)
        self.assertEqual(sorted(os.listdir(os.path.join(dest, "bin"))), ["avcodec-63.dll", "ffmpeg.exe", "ffprobe.exe"])
        self.assertEqual(sorted(os.listdir(dest)), ["LICENSE.txt", "README.txt", "SOURCE.txt", "bin"])
        with open(os.path.join(dest, "SOURCE.txt"), encoding="utf-8") as f:
            source = f.read()
        self.assertIn(self.deps.FFMPEG["source"], source)
        self.assertIn("GNU General Public License", source)

    def test_a_download_that_isnt_the_one_is_refused(self):
        path = os.path.join(self.dir, "thing.zip")
        with open(path, "wb") as f:
            f.write(b"not what we pinned")
        spec = {"url": "file:" + urllib.request.pathname2url(path), "sha256": "0" * 64}
        cache = os.path.join(self.dir, "cache")
        with self.assertRaises(SystemExit):
            self.deps.fetch(spec, cache)
        self.assertEqual(os.listdir(cache), [])                     # nothing kept
        spec["sha256"] = hashlib.sha256(b"not what we pinned").hexdigest()
        self.assertTrue(os.path.isfile(self.deps.fetch(spec, cache)))

    def test_the_installer_carries_what_an_update_replaces(self):
        from sofa import updater
        spec = importlib.util.spec_from_file_location("windows_build", os.path.join(ROOT, "tools", "windows-build.py"))
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        self.assertEqual(build.CODE, updater.CODE)
        with open(os.path.join(ROOT, "deploy", "windows", "sofa.iss"), encoding="utf-8") as f:
            iss = f.read()
        for name in updater.CODE:                     # the uninstaller takes away everything an update may have added
            self.assertIn('Name: "{app}\\%s"' % name, iss)

    def test_pinned_versions_have_hashes(self):
        for spec in (self.deps.PYTHON, self.deps.FFMPEG):
            self.assertRegex(spec["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(spec["url"].startswith("https://"))
            self.assertIn(spec["version"], spec["url"])


class FirstRun(unittest.TestCase):
    """The installer's last page: where the library lives, written once (an update or a reinstall keeps it)."""

    def test_first_run_sets_the_library(self):
        root = tempfile.mkdtemp(prefix="sofa-first-")
        data, media_dir = os.path.join(root, "data"), os.path.join(root, "My Media")
        with mock.patch.object(winapp, "DATA", data), mock.patch.object(config, "DATA_DIR", data), \
                mock.patch.object(config, "CONFIG_PATH", os.path.join(data, "config.json")), \
                mock.patch.object(config, "_config", None):
            self.assertTrue(winapp.set_library(media_dir))
            self.assertEqual(config.get("shows"), os.path.join(media_dir, "Shows"))
            self.assertTrue(os.path.isdir(os.path.join(media_dir, "Inbox")))
            self.assertFalse(winapp.set_library(os.path.join(root, "Elsewhere")))     # settings there already: kept
        config.load()                                                                  # (the tests' own settings back)


class WhatsSkippedOnWindows(unittest.TestCase):
    def test_only_the_box_is_left_out(self):
        for name in ("test_server", "test_inbox", "test_playback", "test_fileops", "test_swap", "test_live", "test_windows",
                     "test_access", "test_https", "test_drives", "test_durability", "test_previews"):
            self.assertIsNone(tests.windows_skip("tests." + name), name)
        for name in ("tests.test_box_games", "tests.test_sofa_box", "tests.test_outside.ThisBox.test_anything"):
            self.assertIn("Linux", tests.windows_skip(name))


# ---------------------------------------------------------------- on Windows

@unittest.skipUnless(WINDOWS, "Windows only (these are Windows' own APIs)")
class WindowsItself(unittest.TestCase):
    def test_what_this_computer_is(self):
        d = windows.describe()
        self.assertGreater(d["memory"], 512 * 1024 * 1024)
        self.assertTrue(d["cpu"])
        self.assertIn(d["modern_cpu"], (True, False))

    def test_how_busy(self):
        del windows._times[:]
        windows.load()                                           # the first look
        time.sleep(2.5)
        load = windows.load()                                    # how busy since then
        self.assertIsNotNone(load)
        self.assertGreaterEqual(load, 0)
        self.assertLessEqual(load, os.cpu_count())

    def test_addresses(self):
        ips = windows.ipv4s()
        self.assertTrue(ips)
        self.assertFalse([ip for ip in ips if ip.startswith("127.")])

    def test_drives_but_not_the_system_one(self):
        system = os.environ.get("SystemDrive", "C:").upper()
        for d in windows.drives():
            self.assertFalse(d["path"].upper().startswith(system))
            self.assertTrue(d["path"].endswith(":\\"))

    def test_staying_awake(self):
        self.assertTrue(windows.keep_awake(True))
        self.assertTrue(wait_for(windows.keeping_awake, 5))
        windows.keep_awake(False)
        self.assertTrue(wait_for(lambda: not windows.keeping_awake(), 5))

    def test_bonjour_by_windows_itself(self):
        if not windows.bonjour_available():
            self.skipTest("no DNS-SD API in this Windows (older than 10 1809)")
        a = windows.Announcer("Sofa test %d" % os.getpid(), "_sofa._tcp", 8090, ["version=1", "api=1", "path=/"])
        try:
            self.assertTrue(a.start(), "Windows answered %s" % a.status)
        finally:
            a.stop()

    def test_a_file_being_read_is_replaced_once_its_closed(self):
        import threading
        folder = tempfile.mkdtemp(prefix="sofa-replace-")
        target, new = os.path.join(folder, "live-health.json"), os.path.join(folder, "live-health.json.tmp")
        for path, text in ((target, "old"), (new, "new")):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        real = os.replace
        reader = open(target, encoding="utf-8")                  # someone reading it, for a moment
        threading.Timer(0.5, reader.close).start()
        try:
            self.assertTrue(windows.retry_file_moves())
            os.replace(new, target)                               # waits for the reader, then replaces
        finally:
            os.replace, os.rename = real, getattr(os.rename, "__wrapped__", os.rename)
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "new")

    def test_the_port_is_sofas_alone(self):
        from sofa import web
        first = web.Server(("127.0.0.1", 0), web.Handler)
        try:
            with self.assertRaises(OSError):
                web.Server(("127.0.0.1", first.server_address[1]), web.Handler)
        finally:
            first.server_close()


def _alive(pid):
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x1000, False, pid)                      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
        return code.value == 259                                 # STILL_ACTIVE
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def _data_folder(port):
    """A data folder of its own with a config.json: its own port, the library inside it, nothing from the internet."""
    root = tempfile.mkdtemp(prefix="sofa-winapp-")
    data, lib = os.path.join(root, "data"), os.path.join(root, "Library")
    os.makedirs(data)
    conf = {k: os.path.join(lib, v) for k, v in {"shows": "Shows", "movies": "Movies", "music": "Music",
                                                  "musicvideos": "Music Videos", "inbox": "Inbox", "review": "Needs Review",
                                                  "adult": "Adult", "originals": "Converted Originals"}.items()}
    conf.update(port=port, offline=True, dlna=False, machine_test=False, keep_awake=False, tvmaze=False,
                free_movie_lookup=False, auto_convert=False, previews=False, trickplay=False, detect_intros=False)
    with open(os.path.join(data, "config.json"), "w", encoding="utf-8") as f:
        json.dump(conf, f)
    return root, data


@unittest.skipUnless(WINDOWS, "Windows only (a job object, a named event)")
class TheServerInAJob(unittest.TestCase):
    def test_a_clean_stop_and_nothing_left(self):
        port = free_port()
        root, data = _data_folder(port)
        log = os.path.join(data, "sofa.log")
        with mock.patch.dict(os.environ, {"SOFA_DATA": data}):
            server = winapp.Server([sys.executable, "-X", "utf8", os.path.join(ROOT, "sofa.py"), "serve"], cwd=ROOT,
                                   log_path=log)
            server.start()
        try:
            self.assertTrue(wait_for(lambda: answers(port), 60), "the server didn't answer")
            with open(log, encoding="utf-8") as f:
                self.assertIn("Run by the Sofa app", f.read())
            server.stop()
            self.assertEqual(server.exit_code(), 0)                    # it stopped itself, cleanly
            with open(log, encoding="utf-8") as f:
                self.assertIn("Sofa is stopping (asked by the Sofa app).", f.read())
            self.assertFalse(answers(port))
        finally:
            server.close()

    def test_what_it_started_ends_with_it(self):
        log = os.path.join(tempfile.mkdtemp(prefix="sofa-job-"), "out.log")
        child = "import subprocess, sys, time; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); " \
                "print(p.pid, flush=True); time.sleep(120)"
        server = winapp.Server([sys.executable, "-c", child], cwd=ROOT, log_path=log)
        server.start()
        try:
            self.assertTrue(wait_for(lambda: open(log).read().strip().isdigit(), 30))
            grandchild = int(open(log).read().strip())
            self.assertTrue(_alive(grandchild))
        finally:
            server.stop(timeout=1)                     # (it doesn't watch the event: the job ends it, and its child)
        self.assertTrue(wait_for(lambda: not _alive(grandchild), 10), "the server's own child outlived it")


@unittest.skipUnless(WINDOWS, "Windows only (the app in the notification area)")
class TheApp(unittest.TestCase):
    """deploy/windows/sofa-tray.pyw as the Start menu, "start with Windows" and the installer run it."""

    def run_app(self, data, *args, wait=False):
        env = dict(os.environ, SOFA_DATA=data)
        cmd = [sys.executable, os.path.join(ROOT, "deploy", "windows", "sofa-tray.pyw")] + list(args)
        if wait:
            return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
        return subprocess.Popen(cmd, env=env, creationflags=windows.CREATE_NO_WINDOW)

    def test_started_asked_and_quit(self):
        port = free_port()
        root, data = _data_folder(port)
        app = self.run_app(data, "--background")
        try:
            self.assertTrue(wait_for(lambda: answers(port), 90), "Sofa didn't answer under the app")
            self.assertEqual(self.run_app(data, "--status", wait=True).returncode, 0)
            second = self.run_app(data, "--background", wait=True)          # a second start: the first one stays
            self.assertEqual(second.returncode, 0)
            self.assertIsNone(app.poll())
            quit = self.run_app(data, "--quit", wait=True)
            self.assertEqual(quit.returncode, 0, quit.stdout + quit.stderr)
            self.assertEqual(app.wait(30), 0)
            self.assertFalse(answers(port))
            self.assertEqual(self.run_app(data, "--status", wait=True).returncode, 1)
            with open(os.path.join(data, "sofa.log"), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("Sofa app: started the server", text)
            self.assertIn("Sofa is stopping (asked by the Sofa app).", text)
        finally:
            if app.poll() is None:
                app.kill()

    def test_start_with_windows(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, winapp.RUN_KEY) as k:
                before = winreg.QueryValueEx(k, winapp.RUN_VALUE)[0]
        except OSError:
            before = None
        try:
            winapp.set_starts_with_windows(True)
            self.assertTrue(winapp.starts_with_windows())
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, winapp.RUN_KEY) as k:
                self.assertIn("--background", winreg.QueryValueEx(k, winapp.RUN_VALUE)[0])
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, winapp.APPROVED_KEY) as k:     # off in Task Manager
                winreg.SetValueEx(k, winapp.RUN_VALUE, 0, winreg.REG_BINARY, b"\x03" + b"\x00" * 11)
            self.assertFalse(winapp.starts_with_windows())
            winapp.set_starts_with_windows(True)                                         # the menu turns it on again
            self.assertTrue(winapp.starts_with_windows())
            winapp.set_starts_with_windows(False)
            self.assertFalse(winapp.starts_with_windows())
        finally:
            if before is not None:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, winapp.RUN_KEY) as k:
                    winreg.SetValueEx(k, winapp.RUN_VALUE, 0, winreg.REG_SZ, before)


if __name__ == "__main__":
    unittest.main()
