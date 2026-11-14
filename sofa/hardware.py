"""What this computer is, so Sofa uses it well, whatever it is: a Raspberry Pi with 1 GB, four x86-64 cores without AVX2, a PC with
sixteen cores, a container with two of them.

- The processor's cores Sofa may use: not only how many the computer has, but a container's limit (Docker's
  --cpus) and a CPU set (taskset) too. Sofa used to count every core of the computer it was in.
- Its memory, a container's limit counted too, and what's free now.
- The processor by name, on ARM as well ("4 x Cortex-A53": a Pi 3; "4 x Cortex-A76": a Pi 5), and whether its cores
  are of the kind that can convert video quickly (gentle mode is for the ones that can't).
- A Raspberry Pi's model, and whether this is a virtual machine or a container.
- The chips that decode and encode video (Apple's VideoToolbox, VA-API on a PC's graphics, NVIDIA's, the Pi's V4L2
  codecs, Windows' display adapters). Which of them converts video is found by trying (sofa/encoders.py).

Read once (the parts that change, like free memory, each time they're asked). Background work sizes itself by
workers() and threads_each(): spread over the cores, never all of them, and back to one at a time while someone
watches something Sofa converts, or on a small board.
"""
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_info = {}
_lock = threading.Lock()

# ARM's own cores by their part number (/proc/cpuinfo "CPU part", implementer 0x41). The ones before the Cortex-A76
# can't convert 1080p video faster than it plays (a Pi 3's A53, a Pi 4's A72): "slow" here.
ARM_PARTS = {0xb76: "ARM1176", 0xc07: "Cortex-A7", 0xc09: "Cortex-A9", 0xc0f: "Cortex-A15", 0xd03: "Cortex-A53",
             0xd04: "Cortex-A35", 0xd05: "Cortex-A55", 0xd07: "Cortex-A57", 0xd08: "Cortex-A72", 0xd09: "Cortex-A73",
             0xd0a: "Cortex-A75", 0xd0b: "Cortex-A76", 0xd0c: "Neoverse-N1", 0xd0d: "Cortex-A77", 0xd40: "Neoverse-V1",
             0xd41: "Cortex-A78", 0xd44: "Cortex-X1", 0xd46: "Cortex-A510", 0xd47: "Cortex-A710", 0xd48: "Cortex-X2",
             0xd49: "Neoverse-N2", 0xd4b: "Cortex-A78C", 0xd4f: "Neoverse-V2", 0xd80: "Cortex-A520", 0xd81: "Cortex-A720",
             0xd82: "Cortex-X4", 0xd85: "Cortex-X925", 0xd87: "Cortex-A725", 0xd8e: "Neoverse-N3"}
SLOW_PARTS = {0xb76, 0xc07, 0xc09, 0xc0f, 0xd03, 0xd04, 0xd05, 0xd07, 0xd08, 0xd09}
MAKERS = {0x41: "ARM", 0x42: "Broadcom", 0x46: "Fujitsu", 0x48: "HiSilicon", 0x4e: "NVIDIA", 0x51: "Qualcomm",
          0x61: "Apple", 0xc0: "Ampere"}
GPU_VENDORS = {"0x8086": "Intel", "0x1002": "AMD", "0x10de": "NVIDIA", "0x1af4": "virtual"}
ROOT = os.environ.get("SOFA_HW_ROOT", "")          # (tests point this at a folder laid out like /proc and /sys)


def _read(path, limit=1 << 20):
    try:
        with open(ROOT + path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def _sysctl(name):
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- cores and memory

def cgroup_cpus():
    """A container's processor limit in cores (Docker's --cpus 1.5: 1.5), or None when there's none."""
    v2 = _read("/sys/fs/cgroup/cpu.max").split()
    if len(v2) == 2 and v2[0] != "max":
        try:
            return int(v2[0]) / int(v2[1])
        except (ValueError, ZeroDivisionError):
            pass
    try:
        quota, period = int(_read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")), int(_read("/sys/fs/cgroup/cpu/cpu.cfs_period_us"))
        if quota > 0 and period > 0:
            return quota / period
    except ValueError:
        pass
    return None


def cores():
    """The cores Sofa may use: the computer's, fewer in a container with a limit or with a CPU set."""
    n = os.cpu_count() or 1
    if not ROOT:
        try:
            n = min(n, len(os.sched_getaffinity(0)))
        except (AttributeError, OSError):
            pass
    else:
        n = int(os.environ.get("SOFA_HW_CPUS") or n)
    q = cgroup_cpus()
    if q:
        n = min(n, max(1, int(math.ceil(q - 0.01))))
    return max(1, n)


def cgroup_memory():
    """A container's memory limit in bytes, or None."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        v = _read(path).strip()
        if v and v != "max":
            try:
                n = int(v)
            except ValueError:
                continue
            if 0 < n < 1 << 60:                         # (cgroup v1 says "no limit" with a huge number)
                return n
    return None


def _meminfo(key):
    m = re.search(r"^%s:\s+(\d+)" % key, _read("/proc/meminfo"), re.M)
    return int(m.group(1)) * 1024 if m else None


def memory():
    """The memory Sofa can have, in bytes: the computer's, or a container's limit when that's smaller."""
    total = _meminfo("MemTotal")
    if total is None and not ROOT:
        if sys.platform == "darwin":
            total = int(_sysctl("hw.memsize") or 0) or None
        elif sys.platform == "win32":                      # (no sysconf there: Windows' own figure)
            from . import windows
            total = (windows.describe() or {}).get("memory") or None
        else:
            try:
                total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            except (ValueError, OSError, AttributeError):
                total = None
    limit = cgroup_memory()
    return min(x for x in (total, limit) if x) if (total or limit) else 0


_avail = {"at": -1e9, "value": None}


def available():
    """Memory free for something new, in bytes (the kernel's own figure; a container's limit counted), or None.
    (Looked at again after two seconds at most: on a Mac it's a program to run.)"""
    if time.monotonic() - _avail["at"] < 2:
        return _avail["value"]
    _avail.update(at=time.monotonic(), value=_available())
    return _avail["value"]


def _available():
    free = _meminfo("MemAvailable")
    limit = cgroup_memory()
    if limit:
        used = _read("/sys/fs/cgroup/memory.current").strip() or _read("/sys/fs/cgroup/memory/memory.usage_in_bytes").strip()
        try:
            room = limit - int(used)
            free = room if free is None else min(free, room)
        except ValueError:
            pass
    if free is None and sys.platform == "darwin" and not ROOT:
        try:                                            # macOS: free, inactive and purgeable pages are there to be had
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = int(re.search(r"page size of (\d+)", out).group(1))
            pages = sum(int(re.search(r"%s:\s+(\d+)" % k, out).group(1)) for k in
                        ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"))
            free = pages * page
        except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
            free = None
    return free


def pressure():
    """How often anything waited for memory lately (Linux's PSI: the share of the last 10 s and 60 s), or None."""
    m = re.search(r"some avg10=([\d.]+) avg60=([\d.]+)", _read("/proc/pressure/memory"))
    return {"avg10": float(m.group(1)), "avg60": float(m.group(2))} if m else None


def own_memory():
    """Sofa's own process: its memory now and the most it has had, in bytes."""
    now = None
    m = re.search(r"VmRSS:\s+(\d+)", _read("/proc/self/status")) if not ROOT else None
    if m:
        now = int(m.group(1)) * 1024
    elif sys.platform == "darwin":
        try:
            now = int(subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True,
                                     timeout=5).stdout) * 1024
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak = peak if sys.platform == "darwin" else peak * 1024
    except (ImportError, OSError):
        peak = None
    return {"now": now, "peak": peak}


# ---------------------------------------------------------------- what kind of computer

def _arm_cores(cpuinfo):
    """ARM's processors from /proc/cpuinfo: [(maker, part)] for each core."""
    out, maker = [], None
    for line in cpuinfo.splitlines():
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        try:
            if k == "CPU implementer":
                maker = int(v, 16)
            elif k == "CPU part" and maker is not None:
                out.append((maker, int(v, 16)))
        except ValueError:
            continue
    return out


def processor():
    """{"name", "slow"}: the processor by name, and whether its cores are too slow to convert video quickly (an ARM
    core before the Cortex-A76; an Intel or AMD without AVX2, from before about 2013). None when it can't be told."""
    if sys.platform == "win32" and not ROOT:              # Windows' own name for it, and AVX2 (windows.describe)
        from . import windows
        w = windows.describe() or {}
        if w.get("cpu") or w.get("modern_cpu") is not None:
            return {"name": w.get("cpu") or "unknown", "slow": None if w.get("modern_cpu") is None else not w["modern_cpu"]}
        return None
    if sys.platform == "darwin" and not ROOT:
        if platform.machine() == "arm64":
            return {"name": _sysctl("machdep.cpu.brand_string") or "Apple silicon", "slow": False}
        flags = (_sysctl("machdep.cpu.leaf7_features") + " " + _sysctl("machdep.cpu.features")).upper()
        return {"name": _sysctl("machdep.cpu.brand_string") or "Intel", "slow": "AVX2" not in flags}
    text = _read("/proc/cpuinfo")
    m = re.search(r"model name\s*:\s*(.+)", text)
    if m and re.search(r"^flags\s*:", text, re.M):         # Intel and AMD
        return {"name": re.sub(r"\s+", " ", m.group(1)).strip(), "slow": not re.search(r"^flags\s*:.*\bavx2\b", text, re.M)}
    arm = _arm_cores(text)
    if arm:
        kinds = {}
        for maker, part in arm:
            name = ARM_PARTS.get(part) if maker == 0x41 else None
            name = name or ("%s silicon" % MAKERS[maker] if maker == 0x61 else
                            "%s 0x%03x" % (MAKERS.get(maker, "ARM"), part))
            kinds[name] = kinds.get(name, 0) + 1
        slow = all(maker == 0x41 and part in SLOW_PARTS for maker, part in arm)
        return {"name": " + ".join("%d x %s" % (n, k) for k, n in kinds.items()), "slow": slow}
    if m:
        return {"name": re.sub(r"\s+", " ", m.group(1)).strip(), "slow": None}
    return None


def pi_model():
    """"Raspberry Pi 4 Model B Rev 1.4", or None on anything else."""
    m = _read("/proc/device-tree/model").strip("\x00\n ")
    return m if m.startswith("Raspberry Pi") else None


def pi_generation(model=None):
    """3 for a Pi 3 (and a Zero 2, which has its chip), 4, 5; 1 for the first ones and the Zero; 0 elsewhere."""
    m = re.search(r"Raspberry Pi (?:Compute Module )?(\d)|Raspberry Pi (Zero 2)|Raspberry Pi (Zero)", model or pi_model() or "")
    return int(m.group(1)) if m and m.group(1) else 3 if m and m.group(2) else 1 if m else 0


def virtual():
    """"a virtual machine (QEMU)", "a container (Docker)", or None on a computer of its own."""
    container = None
    if os.path.exists(ROOT + "/.dockerenv"):
        container = "Docker"
    elif os.path.exists(ROOT + "/run/.containerenv"):
        container = "Podman"
    else:
        cg = _read("/proc/1/cgroup")
        container = next((n for k, n in (("docker", "Docker"), ("kubepods", "Kubernetes"), ("lxc", "LXC")) if k in cg), None)
    if container:
        return "a container (%s)" % container
    if sys.platform == "darwin" and not ROOT:
        return "a virtual machine" if _sysctl("kern.hv_vmm_present") == "1" else None
    vendor = (_read("/sys/class/dmi/id/sys_vendor") + " " + _read("/sys/class/dmi/id/product_name")).strip()
    for pat, name in ((r"QEMU|KVM", "QEMU"), (r"VMware", "VMware"), (r"VirtualBox|innotek", "VirtualBox"),
                      (r"Microsoft Corporation Virtual|Hyper-V", "Hyper-V"), (r"Xen", "Xen"), (r"Parallels", "Parallels"),
                      (r"Apple Virtualization", "Apple Virtualization"), (r"Google Compute", "Google Cloud"),
                      (r"Amazon EC2", "Amazon EC2")):
        if re.search(pat, vendor):
            return "a virtual machine (%s)" % name
    if re.search(r"^flags\s*:.*\bhypervisor\b", _read("/proc/cpuinfo"), re.M):
        return "a virtual machine"
    return None


def video_chips():
    """The chips this computer has for video, by what they're called: ["VideoToolbox"], ["VA-API: Intel (renderD128)"],
    ["NVIDIA: GeForce RTX 3060 (driver 550.120)"], ["V4L2: bcm2835-codec-decode", ...], on Windows the display adapters
    by name. Empty when everything is on the processor (a VM, most containers). What's listed is what's there: whether
    it converts video is for the one-second test to say (sofa/encoders.py)."""
    if sys.platform == "darwin" and not ROOT:
        return ["VideoToolbox"]
    from . import encoders, windows
    if windows.ON and not ROOT:
        return [a["name"] for a in windows.gpus() if a.get("maker")]
    out = []
    nvidia = encoders._nvidia()
    try:
        nodes = sorted(n for n in os.listdir(ROOT + "/dev/dri") if n.startswith("renderD"))
    except OSError:
        nodes = []
    for n in nodes:
        vendor = _read("/sys/class/drm/%s/device/vendor" % n).strip()
        if GPU_VENDORS.get(vendor) == "NVIDIA" and nvidia:
            continue                               # (the card's own line, below, says more)
        out.append("VA-API: %s (%s)" % (GPU_VENDORS.get(vendor, vendor or "graphics"), n))
    if nvidia:
        card = nvidia["name"][7:] if nvidia["name"].startswith("NVIDIA ") else nvidia["name"]
        out.append("NVIDIA: %s%s" % (card, " (driver %s)" % nvidia["driver"] if nvidia.get("driver") else ""))
    try:
        v4l = sorted(os.listdir(ROOT + "/sys/class/video4linux"), key=lambda x: int(re.sub(r"\D", "", x) or 0))
    except OSError:
        v4l = []
    for n in v4l:
        name = _read("/sys/class/video4linux/%s/name" % n).strip()
        if re.search(r"codec|hevc|h264|dec|enc|isp", name, re.I) and "isp" not in name.lower():
            out.append("V4L2: %s (%s)" % (name, n))
    return out


def describe(force=False):
    """Everything above that doesn't change while Sofa runs (asked once)."""
    with _lock:
        if force or not _info:
            proc = processor() or {}
            model = pi_model()
            _info.clear()
            _info.update(cores=cores(), cpu_count=os.cpu_count() or 1, memory=memory(), cpu=proc.get("name") or "unknown",
                         slow_cores=proc.get("slow"), arch=platform.machine(), pi=model, pi_gen=pi_generation(model),
                         virtual=virtual(), video=video_chips(), cgroup_cpus=cgroup_cpus(), cgroup_memory=cgroup_memory())
        return dict(_info)


def small():
    """A small machine: a Pi 3 or older, or 1 GB or less (what Sofa on a Sofa Box often runs on)."""
    d = describe()
    return 1 <= d["pi_gen"] <= 3 or (d["memory"] or 0) <= 1100 * 2**20


# ---------------------------------------------------------------- spreading work over the cores

_pool = {"ex": None, "size": 0}


def workers(heavy=True):
    """How many background jobs (reading a file's details, taking a picture from a video, resizing artwork) run at
    once: half the cores, at most four, so whoever watches always has the rest. One on a small machine (a Pi 3 on
    a weak supply browns out with all four cores busy, and it plays the video itself), one while Sofa converts
    something for someone to watch, and never more than its free memory takes (a picture from a 4K video can take
    250 MB). `heavy`: jobs that decode video (the light ones aren't limited by memory). SOFA_WORKERS sets it (for
    measuring).

    (Not the load average: these jobs make it themselves, two ffmpegs of two threads are a load of four, and with it
    they went back to one at a time most of the time, a core and a fifth of four busy. They run behind everything
    else anyway, nice 10.)"""
    if os.environ.get("SOFA_WORKERS", "").isdigit():
        return max(1, int(os.environ["SOFA_WORKERS"]))
    d = describe()
    if small():
        return 1
    n = max(1, min(4, d["cores"] // 2))
    try:
        from . import media
        if media.busy():
            return 1
    except Exception:
        pass
    if heavy:
        free = available()
        if free is not None:
            n = min(n, max(1, free // (250 * 2**20)))
    return max(1, int(n))


def threads_each(n=None):
    """ffmpeg's threads for one background job when `n` run at once: the cores shared out, at least one each."""
    return max(1, describe()["cores"] // max(1, n or workers()))


def each(fn, jobs, most=None):
    """fn(job) for every job, in order, up to `most` (workers()) at a time. The results in the jobs' order; the first
    exception is raised once all have run. One at a time is just a loop."""
    jobs = list(jobs)
    n = min(len(jobs), most or workers())
    if n <= 1:
        return [fn(j) for j in jobs]
    with _lock:
        if _pool["ex"] is None or _pool["size"] < n:
            old = _pool["ex"]
            _pool.update(ex=ThreadPoolExecutor(max(n, 4), thread_name_prefix="sofa-work"), size=max(n, 4))
            if old:
                old.shutdown(wait=False)
        ex = _pool["ex"]
    gate = threading.Semaphore(n)

    def run(job):
        with gate:
            return fn(job)
    futures = [ex.submit(run, j) for j in jobs]
    out, err = [], None
    for f in futures:
        try:
            out.append(f.result())
        except Exception as exc:
            out.append(None)
            err = err or exc
    if err:
        raise err
    return out


def deep_size(obj, limit=2000000):
    """About how many bytes `obj` holds, with everything in it (dicts, lists, sets, tuples, strings; each object once),
    looking at `limit` objects at most. For a report: which of Sofa's parts the memory is in."""
    seen, todo, total = set(), [obj], 0
    while todo and len(seen) < limit:
        o = todo.pop()
        if id(o) in seen:
            continue
        seen.add(id(o))
        total += sys.getsizeof(o)
        if isinstance(o, dict):
            todo.extend(o.keys())
            todo.extend(o.values())
        elif isinstance(o, (list, tuple, set, frozenset)):
            todo.extend(o)
    return total


def memory_lines(parts=()):
    """For a report: the machine's memory, Sofa's own, and `parts` [(name, object)] by size, biggest first."""
    d, own, free, p = describe(), own_memory(), available(), pressure()
    mb = lambda n: "?" if n is None else "%d MB" % (n // 2**20)          # noqa: E731
    out = ["Memory: %s free of %s%s; Sofa itself %s (the most it has had: %s)%s" % (
        mb(free), mb(d["memory"]), " (a container's limit)" if d["cgroup_memory"] and d["cgroup_memory"] == d["memory"] else "",
        mb(own["now"]), mb(own["peak"]),
        "; waiting for memory %.1f%% of the last 10 s, %.1f%% of the last minute" % (p["avg10"], p["avg60"]) if p else "")]
    sized = sorted(((name, deep_size(obj)) for name, obj in parts), key=lambda x: -x[1])
    if sized:
        out.append("  In Sofa's memory: " + ", ".join("%s %.1f MB" % (name, n / 2**20) for name, n in sized))
    return out


_libc = {}


def give_back(collect=False):
    """Memory Sofa freed, given back to the system. Python and the C library keep what's freed for later; with many
    threads (one per connection, the background's) that was tens of MB never used again, on a Pi too. On Linux
    (glibc), malloc_trim; `collect`: Python's cycle collector first (after a library read: its old lists go).
    True when something went back."""
    if collect:
        import gc
        gc.collect()
    if not sys.platform.startswith("linux"):
        return False
    if "fn" not in _libc:
        try:
            import ctypes
            _libc["fn"] = ctypes.CDLL(None).malloc_trim
            _libc["fn"].argtypes, _libc["fn"].restype = [ctypes.c_size_t], ctypes.c_int
        except (OSError, AttributeError, ImportError):          # (musl, Alpine: there's no malloc_trim)
            _libc["fn"] = None
    try:
        return bool(_libc["fn"] and _libc["fn"](0))
    except OSError:
        return False


def _give_back_now_and_then():
    """Every half minute; every other minute after the cycle collector (what a request leaves in a cycle waited for
    it: Sofa on a Sofa Box grew a little with every visit, 31 to 38 MB in eight evenings' worth on a 1 GB stand-in)."""
    n = 0
    while True:
        time.sleep(30)
        n += 1
        give_back(collect=n % 4 == 0)


def start():
    threading.Thread(target=_give_back_now_and_then, daemon=True, name="give-back").start()


def summary():
    """One line for people: "6 cores (of 8: a container's limit), 7.6 GB, Apple M2, a container (Docker),
    video: VideoToolbox"."""
    d = describe()
    gb = (d["memory"] or 0) / 2**30
    parts = ["%d core%s%s" % (d["cores"], "" if d["cores"] == 1 else "s",
                              " (of %d)" % d["cpu_count"] if d["cpu_count"] != d["cores"] else ""),
             ("%.1f GB" % gb) if gb >= 1 else "%d MB" % ((d["memory"] or 0) // 2**20), d["cpu"]]
    if d["pi"]:
        parts.append(d["pi"])
    if d["virtual"]:
        parts.append(d["virtual"])
    parts.append("video: " + (", ".join(d["video"]) if d["video"] else "the processor only"))
    return ", ".join(parts)
