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
