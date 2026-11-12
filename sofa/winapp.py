"""Sofa for Windows: the app in the notification area that runs the server, shows that it's running, and opens it.

    pythonw.exe deploy\\windows\\sofa-tray.pyw               start Sofa (already running: open it in the browser)
        --background                                     the same without opening the browser (start with Windows)
        --first-run                                      right after installing: open Sofa once it answers
        --set-library FOLDER                             the installer: the library's folders there (first install only)
        --quit                                           stop Sofa and this app (the installer, before it changes files)
        --status                                         say whether Sofa runs (exit code 0) or not (1)

What it does, in place of what launchd does on a Mac and systemd on Linux:

- runs `python.exe sofa.py serve` from Sofa's folder with no window, its output added to data\\sofa.log, inside a
  Windows job object: when the server is stopped, or this app ends however it ends, Windows ends the server and every
  ffmpeg it started too;
- starts it again when it stops: at once when it asks to be (after an update, windows.RESTART_CODE), otherwise after
  15 seconds (launchd's ThrottleInterval); after five stops in two minutes it waits, and says so;
- stops it cleanly when asked (Quit, signing out, shutting down, the installer): an event the server watches
  (windows.watch_stop_event), so it says goodbye on the network first;
- the icon: grey while Sofa starts or is stopped, Sofa's own colours once it answers. Clicking it opens Sofa. Its menu:
  Open Sofa, the address for phones and TVs, Restart, Start with Windows, Open the log, Open the Inbox folder, Quit;
- Start with Windows is the "Sofa" value under HKCU\\...\\Run (the installer adds it when that box is ticked;
  Task Manager's Startup apps can switch it off too, and the menu shows that).

Only the standard library. Off Windows main() says it's for Windows and stops.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

from . import windows

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("SOFA_DATA", os.path.join(APP, "data"))
LOG = os.path.join(DATA, "sofa.log")
LAUNCHER = os.path.join(APP, "deploy", "windows", "sofa-tray.pyw")
ICONS = os.path.join(APP, "deploy", "windows")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
RUN_VALUE = "Sofa"
WINDOW_CLASS = "SofaWindowsApp"
APP_ID = "EdgeVenture.Sofa"                   # the Start menu shortcut's AppUserModelID too (deploy/windows/sofa.iss)
THROTTLE = 15                 # seconds before starting a server that stopped by itself again
GIVE_UP = (5, 120)            # this many stops within this many seconds: wait for the person instead


def _instance_key():
    """One app per Sofa folder and data folder (a test's own data folder doesn't meet the real one)."""
    import hashlib
    return hashlib.sha1(("%s|%s" % (os.path.normcase(APP), os.path.normcase(os.path.abspath(DATA)))).encode()).hexdigest()[:12]


def python_exe(gui=False):
    """The Python that runs Sofa: the one Sofa for Windows brought (vendor\\python), else the one running this."""
    name = "pythonw.exe" if gui else "python.exe"
    for folder in (os.path.join(APP, "vendor", "python"), os.path.dirname(sys.executable)):
        if os.path.isfile(os.path.join(folder, name)):
            return os.path.join(folder, name)
    return sys.executable


def settings():
    try:
        with open(os.path.join(DATA, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def port():
    try:
        return int(settings().get("port") or 8090)
    except (TypeError, ValueError):
        return 8090


def local_url():
    return "http://localhost:%d/" % port()


def home_addresses():
    """The addresses phones and TVs at home use (the private ones), the default route's first."""
    import re
    return [ip for ip in windows.ipv4s() or [] if ip.startswith(("10.", "192.168."))
            or re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip)]


_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # (never through a proxy Windows has set)


def answering(timeout=2):
    try:
        with _direct.open("http://127.0.0.1:%d/healthz" % port(), timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def log(message):
    """A line of the app's own in data\\sofa.log, stamped like the server's (none with Keep no logs on)."""
    if settings().get("no_logs"):
        return
    line = (time.strftime("[%Y-%m-%d %H:%M:%S] ") + "Sofa app: " + message + "\n").encode("utf-8")
    try:
        os.makedirs(DATA, exist_ok=True)
        fd = open_append(LOG)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError:
        pass


def open_append(path):
    """A file descriptor that only ever adds at the end, whoever else writes: the server (its output) and this app
    share data\\sofa.log. (Python's "a" on Windows moves to the end and then writes, so two writers overwrite each
    other's lines; a handle with append access alone is what O_APPEND is on a Mac or Linux.)"""
    if not windows.ON:
        return os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    import msvcrt
    handle = _k32.CreateFileW(path, FILE_APPEND_DATA | SYNCHRONIZE, FILE_SHARE_ALL, None, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, None)
    if not handle or handle == INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    return msvcrt.open_osfhandle(handle, os.O_WRONLY)


# ---------------------------------------------------------------- first run: where the library lives

def set_library(folder):
    """Right after the first install: the library's folders under `folder` (Shows, Movies, Music, ...), unless
    Sofa has settings already (an update, or a reinstall that kept data\\). True if they were set."""
    if os.path.exists(os.path.join(DATA, "config.json")) or not folder:
        return False
    from . import config
    folder = os.path.abspath(os.path.expanduser(folder))
    names = {"shows": "Shows", "movies": "Movies", "music": "Music", "musicvideos": "Music Videos", "inbox": "Inbox",
             "review": "Needs Review", "adult": "Adult", "originals": "Converted Originals"}
    config.load()
    config.update({k: os.path.join(folder, v) for k, v in names.items()})
    for k in ("shows", "movies", "music", "musicvideos", "inbox"):
        os.makedirs(config.path(k), exist_ok=True)
    return True


def inbox_folder():
    folder = settings().get("inbox") or "~/Entertainment/Inbox"
    return os.path.abspath(os.path.expanduser(folder))


# ---------------------------------------------------------------- start with Windows

def startup_command():
    return '"%s" "%s" --background' % (python_exe(gui=True), LAUNCHER)


def starts_with_windows():
    """The Run value is there and Task Manager hasn't switched it off (StartupApproved: an odd first byte is off)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
    except OSError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as k:
            data = winreg.QueryValueEx(k, RUN_VALUE)[0]
        return not (isinstance(data, bytes) and data and data[0] % 2 == 1)
    except OSError:
        return True


def set_starts_with_windows(on):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if on:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except OSError:
                pass
    try:                                    # Task Manager's "Disabled" would otherwise win over the menu
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_VALUE)
    except OSError:
        pass


# ---------------------------------------------------------------- the server, in a job object

if windows.ON:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                      "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.CreateEventW.restype = wintypes.HANDLE
    _k32.SetEvent.argtypes = [wintypes.HANDLE]
    _k32.SetEvent.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.CreateMutexW.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _k32.WaitForSingleObject.restype = wintypes.DWORD
    _k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.HANDLE]
    _k32.CreateFileW.restype = wintypes.HANDLE
    INVALID_HANDLE = ctypes.c_void_p(-1).value

FILE_APPEND_DATA, SYNCHRONIZE, FILE_SHARE_ALL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL = 0x0004, 0x00100000, 0x7, 4, 0x80
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
ERROR_ALREADY_EXISTS = 183


class Server:
    """`python.exe sofa.py serve` (or `command`), windowless, in a job object of its own."""

    def __init__(self, command=None, cwd=APP, log_path=LOG):
        self.command = command or [python_exe(), "-X", "utf8", os.path.join(APP, "sofa.py"), "serve"]
        self.cwd, self.log_path = cwd, log_path
        self.proc = self._job = self._event = None
        self._event_name = None

    def start(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self._job = _k32.CreateJobObjectW(None, None)
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        _k32.SetInformationJobObject(self._job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info))
        self._event_name = "Local\\SofaStop-%d-%d" % (os.getpid(), int(time.time() * 1000))
        self._event = _k32.CreateEventW(None, True, False, self._event_name)
        env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        env[windows.SUPERVISED_ENV] = "1"
        env[windows.STOP_EVENT_ENV] = self._event_name
        out = open_append(self.log_path)
        try:
            # CREATE_NO_WINDOW: a console nobody sees, which every ffmpeg the server starts shares (no windows flash
            # up). The server is in the job before its first ffmpeg: Python takes a good part of a second to start.
            self.proc = subprocess.Popen(self.command, cwd=self.cwd, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                         stderr=subprocess.STDOUT, creationflags=windows.CREATE_NO_WINDOW)
        finally:
            os.close(out)
        if not _k32.AssignProcessToJobObject(self._job, int(self.proc._handle)):
            log("couldn't put the server in a job object (error %d); its ffmpegs may outlive it" % ctypes.get_last_error())
        return self.proc.pid

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def exit_code(self):
        return None if self.proc is None else self.proc.poll()

    def stop(self, timeout=15):
        """Ask the server to stop (it says goodbye on the network), then end whatever is left in the job."""
        if self.proc is not None and self.proc.poll() is None and self._event:
            _k32.SetEvent(self._event)
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                pass
        self.close()

    def close(self):
        if self._job:
            _k32.TerminateJobObject(self._job, 1)
            _k32.CloseHandle(self._job)
            self._job = None
        if self._event:
            _k32.CloseHandle(self._event)
            self._event = None
        if self.proc is not None:
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                pass


class Keeper:
    """Keeps the server running: starts it, notices it stopped, starts it again (or doesn't, and says why)."""

    def __init__(self, server_factory=Server, throttle=THROTTLE, give_up=GIVE_UP):
        self.factory, self.throttle, self.give_up = server_factory, throttle, give_up
        self.server, self.stops, self.next_start, self.wanted = None, [], None, False
        self.state = "stopped"            # stopped, starting, running, waiting (to start again), failing

    def start(self):
        self.wanted, self.next_start, self.stops = True, None, []
        self._launch()

    def _launch(self):
        if self.server:
            self.server.close()
        self.server = self.factory()
        pid = self.server.start()
        self.state = "starting"
        log("started the server (process %s)" % pid)

    def stop(self, timeout=15):
        self.wanted, self.next_start = False, None
        if self.server:
            self.server.stop(timeout)
            self.server = None
        self.state = "stopped"

    def restart(self):
        self.stop()
        self.start()

    def tick(self, now=None, answering=answering):
        """Called every second or so; `answering` says whether the server answers (the app asks in the background,
        so a busy server never holds up the icon). Returns the state."""
        now = now or time.time()
        if not self.wanted:
            return self.state
        if self.server and self.server.running():
            if self.state == "starting" and answering():
                self.state = "running"
            return self.state
        if self.next_start is not None:
            if now >= self.next_start:
                self.next_start = None
                self._launch()
            return self.state
        code = self.server.exit_code() if self.server else None
        if code == windows.RESTART_CODE:
            log("the server asked to be started again (an update)")
            self._launch()
            return self.state
        self.stops = [t for t in self.stops if now - t < self.give_up[1]] + [now]
        if len(self.stops) >= self.give_up[0]:
            log("the server stopped %d times in %d seconds (last code %s); waiting for Start Sofa from the menu"
                % (len(self.stops), self.give_up[1], code))
            self.wanted, self.state = False, "failing"
            if self.server:
                self.server.close()
            return self.state
        log("the server stopped (code %s); starting it again in %d seconds" % (code, self.throttle))
        self.next_start, self.state = now + self.throttle, "waiting"
        return self.state


# ---------------------------------------------------------------- the notification area

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_TIMER, WM_NULL = 0x0002, 0x0010, 0x0111, 0x0113, 0x0000
WM_CONTEXTMENU, WM_ENDSESSION, WM_APP = 0x007B, 0x0016, 0x8000
WM_TRAY, WM_OPEN, WM_QUIT_APP = WM_APP + 1, WM_APP + 2, WM_APP + 3
NIN_SELECT, NIN_KEYSELECT = 0x0400, 0x0401
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x01, 0x02, 0x04, 0x10, 0x80
NIIF_INFO, NIIF_WARNING, NIIF_RESPECT_QUIET_TIME = 0x01, 0x02, 0x80
MF_STRING, MF_GRAYED, MF_CHECKED, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
IMAGE_ICON, LR_LOADFROMFILE, SM_CXSMICON, SM_CYSMICON = 1, 0x10, 49, 50

ID_OPEN, ID_ADDRESS, ID_STATE, ID_TOGGLE, ID_RESTART, ID_STARTUP, ID_LOG, ID_INBOX, ID_QUIT = range(100, 109)

if windows.ON:
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _s32 = ctypes.WinDLL("shell32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class _WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    class _NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                    ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                    ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                    ("dwInfoFlags", wintypes.DWORD), ("guidItem", _GUID), ("hBalloonIcon", wintypes.HICON)]

    class _MSG(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", wintypes.POINT),
                    ("lPrivate", wintypes.DWORD)]

    _k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _k32.GetModuleHandleW.restype = wintypes.HMODULE
    _u32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
    _u32.RegisterClassExW.restype = wintypes.ATOM
    _u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                     wintypes.HINSTANCE, ctypes.c_void_p]
    _u32.CreateWindowExW.restype = wintypes.HWND
    _u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _u32.DefWindowProcW.restype = LRESULT
    _u32.DestroyWindow.argtypes = [wintypes.HWND]
    _u32.DestroyWindow.restype = wintypes.BOOL
    _u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _u32.PostMessageW.restype = wintypes.BOOL
    _u32.PostQuitMessage.argtypes = [ctypes.c_int]
    _u32.PostQuitMessage.restype = None
    _u32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _u32.GetMessageW.restype = wintypes.BOOL
    _u32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
    _u32.TranslateMessage.restype = wintypes.BOOL
    _u32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
    _u32.DispatchMessageW.restype = LRESULT
    _u32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    _u32.SetTimer.restype = ctypes.c_size_t
    _u32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    _u32.RegisterWindowMessageW.restype = wintypes.UINT
    _u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _u32.FindWindowW.restype = wintypes.HWND
    _u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _u32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _u32.CreatePopupMenu.restype = wintypes.HMENU
    _u32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    _u32.AppendMenuW.restype = wintypes.BOOL
    _u32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
    _u32.SetMenuDefaultItem.restype = wintypes.BOOL
    _u32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.HWND, ctypes.c_void_p]
    _u32.TrackPopupMenu.restype = ctypes.c_int
    _u32.DestroyMenu.argtypes = [wintypes.HMENU]
    _u32.DestroyMenu.restype = wintypes.BOOL
    _u32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _u32.SetForegroundWindow.restype = wintypes.BOOL
    _u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _u32.GetCursorPos.restype = wintypes.BOOL
    _u32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _u32.LoadImageW.restype = wintypes.HANDLE
    _u32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _u32.GetSystemMetrics.restype = ctypes.c_int
    _u32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    _u32.MessageBoxW.restype = ctypes.c_int
    _s32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]
    _s32.Shell_NotifyIconW.restype = wintypes.BOOL

STATE_TEXT = {"starting": "Sofa is starting", "running": "Sofa is running", "stopped": "Sofa is stopped",
              "waiting": "Sofa stopped; starting it again shortly", "failing": "Sofa keeps stopping (see the log)"}


class TrayApp:
    def __init__(self, keeper, open_when_ready=False, welcome=False):
        self.keeper, self.open_when_ready, self.welcome = keeper, open_when_ready, welcome
        self.hwnd, self.icon_added, self.shown_state, self.healthy = None, False, None, False
        self._proc = WNDPROC(self._wndproc)          # (kept: Windows calls it for as long as the window lives)
        small = (_u32.GetSystemMetrics(SM_CXSMICON) or 16, _u32.GetSystemMetrics(SM_CYSMICON) or 16)
        self.icons = {name: _u32.LoadImageW(None, os.path.join(ICONS, name), IMAGE_ICON, small[0], small[1], LR_LOADFROMFILE)
                      for name in ("sofa.ico", "sofa-stopped.ico")}

    # -- the window that receives the icon's clicks

    def create(self):
        hinst = _k32.GetModuleHandleW(None)
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = WINDOW_CLASS + _instance_key()
        wc.hIcon = wc.hIconSm = self.icons["sofa.ico"]
        _u32.RegisterClassExW(ctypes.byref(wc))
        # A plain hidden window (not a message-only one): only top-level windows hear that Explorer started again.
        self.hwnd = _u32.CreateWindowExW(0, wc.lpszClassName, "Sofa", 0, 0, 0, 0, 0, None, None, hinst, None)
        self.taskbar_created = _u32.RegisterWindowMessageW("TaskbarCreated")
        _u32.SetTimer(self.hwnd, 1, 1000, None)
        self.add_icon()

    def _nid(self, flags):
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd, nid.uID, nid.uFlags = self.hwnd, 1, flags
        nid.uCallbackMessage = WM_TRAY
        return nid

    def add_icon(self):
        nid = self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP)
        nid.hIcon = self.icons["sofa-stopped.ico"]
        nid.szTip = STATE_TEXT.get(self.keeper.state, "Sofa")
        self.icon_added = bool(_s32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        if self.icon_added:
            nid.uVersion = 4                                # NOTIFYICON_VERSION_4: keyboard and clicks as events
            _s32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))
        self.shown_state = None

    def update_icon(self, state):
        if not self.icon_added:
            self.add_icon()                                 # (Explorer wasn't there yet when the app started)
        if not self.icon_added or state == self.shown_state:
            return
        nid = self._nid(NIF_ICON | NIF_TIP | NIF_SHOWTIP)
        nid.hIcon = self.icons["sofa.ico" if state == "running" else "sofa-stopped.ico"]
        tip = STATE_TEXT.get(state, "Sofa")
        addresses = home_addresses()
        if state == "running" and addresses:
            tip += " at http://%s:%d" % (addresses[0], port())
        nid.szTip = tip[:127]
        _s32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        self.shown_state = state

    def balloon(self, title, text, warning=False):
        if not self.icon_added:
            return
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle, nid.szInfo = title[:63], text[:255]
        nid.dwInfoFlags = (NIIF_WARNING if warning else NIIF_INFO) | NIIF_RESPECT_QUIET_TIME
        _s32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def remove_icon(self):
        if self.icon_added:
            _s32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))
            self.icon_added = False

    # -- what happens

    def open_sofa(self):
        os.startfile(local_url())

    def _health(self):
        while True:
            self.healthy = bool(self.keeper.wanted) and answering()
            time.sleep(2)

    def tick(self):
        before = self.keeper.state
        state = self.keeper.tick(answering=lambda: self.healthy)
        if state == "running" and before != "running":
            if self.open_when_ready:
                self.open_when_ready = False
                self.open_sofa()
            if self.welcome:
                self.welcome = False
                addresses = home_addresses()
                self.balloon("Sofa is running", "Click the Sofa icon to open it. Phones and TVs at home: %s" % (
                    "http://%s:%d" % (addresses[0], port()) if addresses else "this computer's address, port %d" % port()))
        if state == "failing" and before != "failing":
            self.balloon("Sofa keeps stopping", "It stopped five times in two minutes, so it's left stopped. "
                         "Right-click the Sofa icon: Open the log, or Start Sofa.", warning=True)
        self.update_icon(state)

    def menu(self):
        state = self.keeper.state
        m = _u32.CreatePopupMenu()
        _u32.AppendMenuW(m, MF_STRING, ID_OPEN, "Open Sofa")
        _u32.SetMenuDefaultItem(m, ID_OPEN, False)
        _u32.AppendMenuW(m, MF_STRING | MF_GRAYED, ID_STATE, STATE_TEXT.get(state, "Sofa"))
        addresses = home_addresses()
        if addresses:
            _u32.AppendMenuW(m, MF_STRING | MF_GRAYED, ID_ADDRESS, "Phones and TVs at home: http://%s:%d" % (addresses[0], port()))
        _u32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        if self.keeper.wanted:
            _u32.AppendMenuW(m, MF_STRING, ID_RESTART, "Restart Sofa")
            _u32.AppendMenuW(m, MF_STRING, ID_TOGGLE, "Stop Sofa")
        else:
            _u32.AppendMenuW(m, MF_STRING, ID_TOGGLE, "Start Sofa")
        _u32.AppendMenuW(m, MF_STRING | (MF_CHECKED if starts_with_windows() else 0), ID_STARTUP, "Start with Windows")
        _u32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        _u32.AppendMenuW(m, MF_STRING, ID_LOG, "Open the log")
        _u32.AppendMenuW(m, MF_STRING, ID_INBOX, "Open the Inbox folder")
        _u32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        _u32.AppendMenuW(m, MF_STRING, ID_QUIT, "Quit Sofa")
        return m

    def show_menu(self, x=None, y=None):
        if x is None:
            pt = wintypes.POINT()
            _u32.GetCursorPos(ctypes.byref(pt))
            x, y = pt.x, pt.y
        m = self.menu()
        _u32.SetForegroundWindow(self.hwnd)                 # (or the menu doesn't close when you click elsewhere)
        choice = _u32.TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, x, y, 0, self.hwnd, None)
        _u32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        _u32.DestroyMenu(m)
        if choice:
            self.command(choice)

    def command(self, choice):
        if choice == ID_OPEN:
            self.open_sofa()
        elif choice == ID_RESTART:
            self.keeper.restart()
        elif choice == ID_TOGGLE:
            if self.keeper.wanted:
                self.keeper.stop()
            else:
                self.keeper.start()
        elif choice == ID_STARTUP:
            set_starts_with_windows(not starts_with_windows())
        elif choice == ID_LOG:
            if not os.path.exists(LOG):
                log("the log was opened from the menu")
            os.startfile(LOG)
        elif choice == ID_INBOX:
            os.makedirs(inbox_folder(), exist_ok=True)
            os.startfile(inbox_folder())
        elif choice == ID_QUIT:
            self.quit()
        self.tick()

    def quit(self, timeout=15):
        log("quitting (the server is asked to stop)")
        self.keeper.stop(timeout)
        self.remove_icon()
        if self.hwnd:
            _u32.DestroyWindow(self.hwnd)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event in (NIN_SELECT, NIN_KEYSELECT):
                    self.open_sofa()
                elif event == WM_CONTEXTMENU:
                    self.show_menu(ctypes.c_short(wparam & 0xFFFF).value, ctypes.c_short((wparam >> 16) & 0xFFFF).value)
                return 0
            if msg == WM_TIMER:
                self.tick()
                return 0
            if msg == WM_OPEN:
                if self.keeper.state == "running":
                    self.open_sofa()
                else:
                    self.open_when_ready = True
                    if not self.keeper.wanted:
                        self.keeper.start()
                return 0
            if msg in (WM_QUIT_APP, WM_CLOSE):
                self.quit()
                return 0
            if msg == WM_ENDSESSION and wparam:                # signing out or shutting down: Windows waits briefly
                self.quit(timeout=3)
                return 0
            if msg == WM_DESTROY:
                _u32.PostQuitMessage(0)
                return 0
            if msg == getattr(self, "taskbar_created", None):
                self.add_icon()
                return 0
        except Exception as exc:                               # never let one click end the app
            log("the app hit a problem: %r" % (exc,))
        return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self):
        self.create()
        threading.Thread(target=self._health, daemon=True, name="health").start()
        try:
            self.keeper.start()
        except OSError as exc:
            log("couldn't start the server: %r" % (exc,))
            self.keeper.wanted, self.keeper.state = False, "failing"
        msg = _MSG()
        while _u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _u32.TranslateMessage(ctypes.byref(msg))
            _u32.DispatchMessageW(ctypes.byref(msg))
        self.keeper.stop()
        self.remove_icon()


# ---------------------------------------------------------------- one app per Sofa folder

def _other_window():
    return _u32.FindWindowW(WINDOW_CLASS + _instance_key(), None)


def _wait_for_exit(hwnd, timeout):
    pid = wintypes.DWORD()
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = _k32.OpenProcess(0x00100000, False, pid.value)          # SYNCHRONIZE
    if not handle:
        return True
    try:
        return _k32.WaitForSingleObject(handle, int(timeout * 1000)) == 0
    finally:
        _k32.CloseHandle(handle)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="sofa-tray", description="Sofa for Windows, in the notification area.")
    ap.add_argument("--background", action="store_true", help="don't open the browser (start with Windows)")
    ap.add_argument("--first-run", action="store_true", help="right after installing: open Sofa when it's ready")
    ap.add_argument("--set-library", metavar="FOLDER", help="the folder for Shows, Movies, Music and the Inbox "
                                                              "(only when Sofa has no settings yet), then stop")
    ap.add_argument("--quit", action="store_true", help="stop Sofa and this app, and wait until they have")
    ap.add_argument("--status", action="store_true", help="exit code 0 when Sofa runs, 1 when it doesn't")
    args = ap.parse_args(argv)
    if args.set_library is not None:
        if set_library(args.set_library):
            log("the library is in %s" % args.set_library)
        return 0
    if not windows.ON:
        print("This is Sofa's app for Windows. On a Mac or Linux, see docs/install.md.")
        return 2
    mutex = _k32.CreateMutexW(None, False, "Local\\SofaApp-" + _instance_key())
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    other = _other_window() if already else None
    if args.status:
        up = answering()
        print("Sofa is %s (%s)." % ("running" if up else "not answering", local_url()))
        return 0 if up else 1
    if args.quit:
        if not other:
            return 0
        _u32.PostMessageW(other, WM_QUIT_APP, 0, 0)
        return 0 if _wait_for_exit(other, 60) else 1
    if already:
        if other and not args.background:
            _u32.PostMessageW(other, WM_OPEN, 0, 0)            # the one running opens Sofa (or will, once it answers)
        return 0
    try:                  # the Start menu's Sofa and this app are one app to Windows: its name on notifications
        ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (OSError, AttributeError):
        pass
    app = TrayApp(Keeper(), open_when_ready=not args.background, welcome=not args.background)
    app.run()
    _k32.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
