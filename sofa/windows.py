"""Sofa on Windows: what Windows itself offers in place of the tools Sofa uses on a Mac and on Linux.

Only the standard library (ctypes and winreg), and nothing to install. Safe to import anywhere: off Windows every
function here does nothing and answers None (or False), so the callers keep one path for every system.

    keep_awake(on)      the computer doesn't go to sleep by itself while Sofa runs (caffeinate, systemd-inhibit)
    describe()          CPU, memory and AVX2 (sysctl, /proc/cpuinfo)
    load()              how busy the CPU is, as a load figure (os.getloadavg)
    ipv4s()             this computer's addresses (ifconfig, ip)
    drives()            the drive letters with a disk in them (/Volumes, /media)
    Announcer           Bonjour, by Windows' own DNS-SD service (dns-sd, avahi-publish); Windows 10 1809 or newer
    watch_stop_event()  the Sofa app in the notification area asks the server to stop cleanly (SIGTERM)
    retry_file_moves()  a file that's open somewhere is replaced once it's closed, not refused at once
    restart_code        what the server exits with to be started again at once (os.execv in place)
"""
import os
import socket
import sys
import threading
import time

ON = os.name == "nt"

# The server exits with this when it wants to be started again straight away (after an update): on Windows a
# process can't replace itself the way os.execv does on a Mac or Linux, so the Sofa app that started it does that.
RESTART_CODE = 75
SUPERVISED_ENV = "SOFA_SUPERVISED"            # set by the Sofa app (sofa/winapp.py) for the server it runs
STOP_EVENT_ENV = "SOFA_STOP_EVENT"            # the name of the event that asks the server to stop

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000      # background conversions: the `nice -n 10` of a Mac or Linux
CREATE_NO_WINDOW = 0x08000000

if ON:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
    _k32.SetThreadExecutionState.restype = wintypes.DWORD
    _k32.IsProcessorFeaturePresent.argtypes = [wintypes.DWORD]
    _k32.IsProcessorFeaturePresent.restype = wintypes.BOOL
    _k32.GetLogicalDrives.restype = wintypes.DWORD
    _k32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    _k32.GetDriveTypeW.restype = wintypes.UINT
    _k32.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                           ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                           wintypes.LPWSTR, wintypes.DWORD]
    _k32.GetVolumeInformationW.restype = wintypes.BOOL
    _k32.SetThreadErrorMode.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    _k32.SetThreadErrorMode.restype = wintypes.BOOL
    _k32.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
    _k32.GetSystemTimes.restype = wintypes.BOOL
    _k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.OpenEventW.restype = wintypes.HANDLE
    _k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _k32.WaitForSingleObject.restype = wintypes.DWORD
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    _k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]
    _k32.GlobalMemoryStatusEx.restype = wintypes.BOOL


def retry_file_moves(tries=10, wait=0.1):
    """Windows: a file someone has open (Sofa reading it that moment, an antivirus looking at it, Explorer still copying
    it) can't be replaced or renamed until it's closed, where a Mac or Linux would just do it. From here on os.replace
    and os.rename try again for up to a second before they give up (sofa.py calls this once, as Sofa starts)."""
    if not ON or getattr(os.replace, "sofa_patient", False):
        return False

    def patient(move):
        def again(src, dst, *args, **kwargs):
            for n in range(tries):
                try:
                    return move(src, dst, *args, **kwargs)
                except PermissionError as exc:          # 5: access denied, 32: in use by another process
                    if n == tries - 1 or getattr(exc, "winerror", None) not in (5, 32):
                        raise
                    time.sleep(wait)
        again.sofa_patient = True
        again.__wrapped__ = move
        return again

    os.replace, os.rename = patient(os.replace), patient(os.rename)
    return True


def lower_priority():
    """Popen arguments that run a helper below normal priority (Windows), or {} (elsewhere `nice` does it)."""
    return {"creationflags": BELOW_NORMAL_PRIORITY_CLASS} if ON else {}


# ---------------------------------------------------------------- staying awake

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
_awake = {"want": False, "thread": None}
_awake_changed = threading.Condition()


def _hold_awake():
    """SetThreadExecutionState lasts as long as the thread that asked, so one thread of Sofa's own asks and stays."""
    with _awake_changed:
        _k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        while _awake["want"]:
            _awake_changed.wait()
        _k32.SetThreadExecutionState(ES_CONTINUOUS)
        _awake["thread"] = None


def keep_awake(on):
    """Keep the computer from sleeping by itself while Sofa runs (the screen can still turn off). True if done."""
    if not ON:
        return False
    with _awake_changed:
        _awake["want"] = bool(on)
        if on and _awake["thread"] is None:
            _awake["thread"] = threading.Thread(target=_hold_awake, daemon=True, name="keep-awake")
            _awake["thread"].start()
        _awake_changed.notify_all()
    return True


def keeping_awake():
    return bool(ON and _awake["want"] and _awake["thread"] is not None)


# ---------------------------------------------------------------- what this computer is

PF_AVX2_INSTRUCTIONS_AVAILABLE = 40


def describe():
    """{"cpu", "memory", "modern_cpu"} from Windows itself, or None off Windows."""
    if not ON:
        return None
    cpu = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            cpu = str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
    except OSError:
        pass
    mem = _MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    total = mem.ullTotalPhys if _k32.GlobalMemoryStatusEx(ctypes.byref(mem)) else 0
    return {"cpu": cpu, "memory": int(total), "modern_cpu": bool(_k32.IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE))}


_times = []                 # (when, idle, all) snapshots of GetSystemTimes, a few seconds apart, the last minute
_times_lock = threading.Lock()


def _system_times():
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None
    value = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    return value(idle), value(kernel) + value(user)        # (kernel time includes the idle time)


def load():
    """How busy the CPU has been over about the last minute, in cores (what os.getloadavg()[0] says elsewhere),
    or None off Windows and until there are two looks a few seconds apart."""
    if not ON:
        return None
    now, t = time.time(), _system_times()
    if t is None:
        return None
    with _times_lock:
        if not _times or now - _times[-1][0] >= 5:
            _times.append((now, t[0], t[1]))
        while len(_times) > 2 and now - _times[1][0] >= 60:
            _times.pop(0)
        then = _times[0]
    if now - then[0] < 2 or t[1] <= then[2]:
        return None
    busy = 1.0 - float(t[0] - then[1]) / float(t[1] - then[2])
    return max(0.0, min(1.0, busy)) * (os.cpu_count() or 1)


# ---------------------------------------------------------------- the network

def ipv4s():
    """This computer's IPv4 addresses, the one the default route uses first, or None off Windows. (ipconfig's
    output is in the computer's own language, so it isn't read; Windows answers its own name with every address.)"""
    if not ON:
        return None
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))            # nothing is sent: the routing table picks the address
            out.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        out += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    seen, ips = set(), []
    for ip in out:
        if ip not in seen and not ip.startswith(("127.", "169.254.", "0.")):
            seen.add(ip)
            ips.append(ip)
    return ips


# ---------------------------------------------------------------- drives

DRIVE_REMOVABLE, DRIVE_FIXED = 2, 3
SEM_FAILCRITICALERRORS, SEM_NOOPENFILEERRORBOX = 0x0001, 0x8000


def drives():
    """[{"path": "E:\\", "name", "fs", "removable"}]: every drive letter with a disk in it, fixed or removable,
    except the one Windows runs from (its Users folder is the main library's). None off Windows."""
    if not ON:
        return None
    system = (os.environ.get("SystemDrive") or "C:").rstrip("\\").upper()
    old = wintypes.DWORD()
    _k32.SetThreadErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX, ctypes.byref(old))   # no "insert a disk" box
    try:
        mask, out = _k32.GetLogicalDrives(), []
        for i in range(26):
            if not mask & (1 << i):
                continue
            letter = "%s:" % chr(ord("A") + i)
            root = letter + "\\"
            kind = _k32.GetDriveTypeW(root)
            if letter == system or kind not in (DRIVE_REMOVABLE, DRIVE_FIXED):
                continue
            label, fs = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
            if not _k32.GetVolumeInformationW(root, label, 261, None, None, None, fs, 261):
                continue                                   # an empty card reader, a drive that isn't ready
            out.append({"path": root, "name": label.value or letter, "fs": fs.value.lower(),
                        "removable": kind == DRIVE_REMOVABLE})
        return out
    finally:
        _k32.SetThreadErrorMode(old.value, None)


# ---------------------------------------------------------------- Bonjour

DNS_REQUEST_PENDING = 9506
DNS_QUERY_REQUEST_VERSION1 = 1

if ON:
    class _DNS_SERVICE_INSTANCE(ctypes.Structure):
        _fields_ = [("pszInstanceName", wintypes.LPWSTR), ("pszHostName", wintypes.LPWSTR),
                    ("ip4Address", ctypes.POINTER(wintypes.DWORD)), ("ip6Address", ctypes.c_void_p),
                    ("wPort", wintypes.WORD), ("wPriority", wintypes.WORD), ("wWeight", wintypes.WORD),
                    ("dwPropertyCount", wintypes.DWORD), ("keys", ctypes.POINTER(wintypes.LPWSTR)),
                    ("values", ctypes.POINTER(wintypes.LPWSTR)), ("dwInterfaceIndex", wintypes.DWORD)]

    _REGISTER_COMPLETE = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(_DNS_SERVICE_INSTANCE))

    class _DNS_SERVICE_REGISTER_REQUEST(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("InterfaceIndex", wintypes.ULONG),
                    ("pServiceInstance", ctypes.POINTER(_DNS_SERVICE_INSTANCE)),
                    ("pRegisterCompletionCallback", _REGISTER_COMPLETE), ("pQueryContext", ctypes.c_void_p),
                    ("hCredentials", wintypes.HANDLE), ("unicastEnabled", wintypes.BOOL)]


def _dnsapi():
    """dnsapi.dll's DNS-SD functions, or None (before Windows 10 1809 they aren't there)."""
    try:
        dll = ctypes.WinDLL("dnsapi")
        construct, register = dll.DnsServiceConstructInstance, dll.DnsServiceRegister
        deregister, free = dll.DnsServiceDeRegister, dll.DnsServiceFreeInstance
    except (OSError, AttributeError):
        return None
    construct.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
                          wintypes.WORD, wintypes.WORD, wintypes.WORD, wintypes.DWORD,
                          ctypes.POINTER(wintypes.LPCWSTR), ctypes.POINTER(wintypes.LPCWSTR)]
    construct.restype = ctypes.POINTER(_DNS_SERVICE_INSTANCE)
    register.argtypes = deregister.argtypes = [ctypes.POINTER(_DNS_SERVICE_REGISTER_REQUEST), ctypes.c_void_p]
    register.restype = deregister.restype = wintypes.DWORD
    free.argtypes = [ctypes.POINTER(_DNS_SERVICE_INSTANCE)]
    free.restype = None
    return {"construct": construct, "register": register, "deregister": deregister, "free": free}


def bonjour_available():
    return bool(ON and _dnsapi())


class Announcer:
    """One service announced by Windows' own mDNS responder (the DNS-SD API in dnsapi.dll, Windows 10 1809 and
    newer): no Bonjour from Apple to install, nothing running beside Sofa. start() waits up to `timeout` seconds
    for Windows to say how it went; status is the Win32 error code it gave (0: announced)."""

    def __init__(self, name, service, port, txt):
        self.name, self.service, self.port, self.txt = name, service, int(port), list(txt)
        self.status, self._done = None, threading.Event()
        self._api = self._instance = self._request = self._callback = None

    def _completed(self, status, _context, instance):
        self.status = int(status)
        if instance:
            try:
                self._api["free"](instance)
            except OSError:
                pass
        self._done.set()

    def start(self, timeout=10):
        if not ON:
            return False
        self._api = _dnsapi()
        if not self._api:
            return False
        keys, values = [], []
        for kv in self.txt:
            k, _, v = kv.partition("=")
            keys.append(k)
            values.append(v)
        key_array = (wintypes.LPCWSTR * max(1, len(keys)))(*keys)
        value_array = (wintypes.LPCWSTR * max(1, len(values)))(*values)
        host = socket.gethostname().split(".")[0] + ".local"
        self._instance = self._api["construct"]("%s.%s.local" % (self.name, self.service), host, None, None,
                                                self.port, 0, 0, len(keys), key_array, value_array)
        if not self._instance:
            return False
        self._callback = _REGISTER_COMPLETE(self._completed)          # (kept: Windows calls it later)
        self._request = _DNS_SERVICE_REGISTER_REQUEST(DNS_QUERY_REQUEST_VERSION1, 0, self._instance, self._callback,
                                                      None, None, False)
        self._done.clear()
        rc = self._api["register"](ctypes.byref(self._request), None)
        if rc != DNS_REQUEST_PENDING:
            self.status = int(rc)
            self._free()
            return False
        self._done.wait(timeout)
        return self.status == 0

    def stop(self, timeout=5):
        if not (ON and self._api and self._request):
            return
        self._done.clear()
        if self._api["deregister"](ctypes.byref(self._request), None) == DNS_REQUEST_PENDING:
            self._done.wait(timeout)
        self._free()

    def _free(self):
        if self._instance:
            self._api["free"](self._instance)
        self._instance = self._request = None


# ---------------------------------------------------------------- being run by the Sofa app

SYNCHRONIZE = 0x00100000
INFINITE = 0xFFFFFFFF


def supervised():
    """True when the Sofa app (sofa/winapp.py) started this server and starts it again when it stops."""
    return bool(ON and os.environ.get(SUPERVISED_ENV))


def watch_stop_event(then):
    """When the Sofa app asks the server to stop (it sets the event named in SOFA_STOP_EVENT), call then().
    False when there's no such event to watch (not run by the app)."""
    name = os.environ.get(STOP_EVENT_ENV) if ON else None
    if not name:
        return False
    handle = _k32.OpenEventW(SYNCHRONIZE, False, name)
    if not handle:
        return False

    def wait():
        try:
            _k32.WaitForSingleObject(handle, INFINITE)
        finally:
            _k32.CloseHandle(handle)
        then()

    threading.Thread(target=wait, daemon=True, name="stop-event").start()
    return True


def start_again(args):
    """Start Sofa again with the new code (after an update), the Windows way: exit with RESTART_CODE when the Sofa
    app runs this server (it starts the next one), otherwise start the next one here and leave. Never returns."""
    sys.stdout.flush()
    sys.stderr.flush()
    if not supervised():
        import subprocess
        subprocess.Popen([sys.executable] + list(args), close_fds=True)
    os._exit(RESTART_CODE if supervised() else 0)
