"""Sofa's tests: python3 -m unittest discover -s tests (from the Sofa folder).

They use a throwaway data folder and library in a temporary directory, never the real ones, and
don't touch the internet (Sofa is set to work offline for them). Standard library only, so they
run with the same Python that runs Sofa.
"""
import atexit
import os
import shutil
import tempfile

ROOT = tempfile.mkdtemp(prefix="sofa-tests-")
LIBRARY = os.path.join(ROOT, "Entertainment")
os.environ["SOFA_DATA"] = os.path.join(ROOT, "data")       # before anything from sofa is imported

from sofa import config  # noqa: E402

config.load()
config.update(dict({k: os.path.join(LIBRARY, v) for k, v in {
    "shows": "Shows", "movies": "Movies", "music": "Music", "musicvideos": "Music Videos", "inbox": "Inbox",
    "review": "Needs Review", "adult": "Adult", "originals": "Converted Originals"}.items()},
    port=0, offline=True, tvmaze=False, free_movie_lookup=False, dlna=False, previews=False, trickplay=False,
    detect_intros=False, auto_convert=False))
for key in ("shows", "movies", "inbox", "review", "adult"):
    os.makedirs(config.path(key), exist_ok=True)


def video(path, size=2048):
    """A stand-in video file (the tests that need a real one make it with ffmpeg)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)
    return path


def cleanup():
    shutil.rmtree(ROOT, ignore_errors=True)


atexit.register(cleanup)


# ---------------------------------------------------------------- Windows

# Sofa's server runs on Windows (deploy/windows), and every test of it runs there too (.github/workflows/tests.yml).
# What can't, and why: a module, a class or one test, by the start of its name. These modules aren't even imported
# on Windows (the box's agent reads POSIX-only parts of `os` as it loads).
BOX = ("Sofa Box OS is Linux (Debian on a Raspberry Pi or a PC): its agent, scripts and card tools run on the box "
       "and on GitHub's Linux machines, never on a Windows PC")
WINDOWS_SKIPS = {
    "tests.test_box_": BOX,
    "tests.test_sofa_box": BOX,
    "tests.test_sofa_craft_controls": BOX,
    "tests.test_image_gen": BOX,
    "tests.test_outside.ThisBox": BOX,
    "tests.test_box_certs": ("the box certificate service (deploy/box-certs) runs on our Linux server: it checks "
                             "POSIX file modes and reads openssl's output"),
}


def windows_skip(name):
    """Why the module (a key without a class: also any module whose name starts with it), the class or the test
    `name` doesn't run on Windows, or None."""
    whole = [k for k in WINDOWS_SKIPS if "." not in k[len("tests."):] and name.startswith(k)]
    if whole:
        return WINDOWS_SKIPS[max(whole, key=len)]
    parts = name.split(".")
    for n in (len(parts), len(parts) - 1):            # the test itself, then its class
        if ".".join(parts[:n]) in WINDOWS_SKIPS and n >= 3:
            return WINDOWS_SKIPS[".".join(parts[:n])]
    return None


def load_tests(loader, standard_tests, pattern):
    """unittest's discovery of this folder comes here (python -m unittest discover -s tests). Elsewhere it finds
    the tests as it always does; on Windows, what WINDOWS_SKIPS names is reported as skipped, with its reason."""
    import fnmatch
    import unittest
    here = os.path.dirname(os.path.abspath(__file__))
    top, pattern = os.path.dirname(here), pattern or "test*.py"
    if os.name != "nt":
        standard_tests.addTests(loader.discover(start_dir=here, pattern=pattern, top_level_dir=top))
        return standard_tests
    for filename in sorted(os.listdir(here)):
        if not filename.endswith(".py") or not fnmatch.fnmatch(filename, pattern):
            continue
        module = "tests." + filename[:-3]
        reason = windows_skip(module)
        if reason:                                   # not imported at all
            skipped = type("OnWindows", (unittest.TestCase,), {"test_skipped": unittest.skip(reason)(lambda self: None)})
            skipped.__module__ = module
            standard_tests.addTest(skipped("test_skipped"))
            continue
        suite = loader.discover(start_dir=here, pattern=filename, top_level_dir=top)
        for test in _each(suite):
            cls, name = type(test), getattr(test, "_testMethodName", None)
            why_class = windows_skip("%s.%s" % (cls.__module__, cls.__name__))
            if why_class:
                cls.__unittest_skip__, cls.__unittest_skip_why__ = True, why_class     # (its setUpClass too)
            elif name and windows_skip(test.id()):
                setattr(cls, name, unittest.skip(windows_skip(test.id()))(getattr(cls, name)))
        standard_tests.addTests(suite)
    return standard_tests


def _each(suite):
    for t in suite:
        if hasattr(t, "__iter__"):
            yield from _each(t)
        else:
            yield t
