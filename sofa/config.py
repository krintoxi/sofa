"""Settings live in data/config.json. Missing keys fall back to DEFAULTS."""
import copy
import json
import os
import threading

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("SOFA_DATA", os.path.join(APP_DIR, "data"))
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULTS = {
    # What TVs and the web page call this server.
    "name": "Sofa",
    "port": 8090,
    # The well-defined library layout. Shows/<Show>/Season N/..., Movies/<Title (Year)>/...
    "shows": "~/Entertainment/Shows",
    "movies": "~/Entertainment/Movies",
    # Drop anything here; Sofa identifies it and files it into Shows or Movies.
    "inbox": "~/Entertainment/Inbox",
    # Where Sofa puts things it can't identify, for you to look at.
    "review": "~/Entertainment/Needs Review",
    # Share the library with TVs on the home network (Roku Media Player, VLC, smart TVs).
    "dlna": True,
    # "home": only private networks (Wi-Fi, Tailscale) may connect.
    # "public": also accept internet connections (put Sofa behind HTTPS first, see docs/remote-access.md).
    "remote": "home",
    # Set when a reverse proxy (Caddy, nginx) on this machine forwards to Sofa.
    "trust_proxy": False,
    # Look up show summaries and missing artwork on TVmaze (free, no key).
    "tvmaze": True,
    # Optional: a TMDB API key adds movie posters and summaries.
    "tmdb_api_key": "",
    # ffmpeg folder or "auto" (vendor/ffmpeg, Homebrew, PATH).
    "ffmpeg": "auto",
    # Live TV channel lists (M3U). Each: {"name": ..., "url": ...}
    "live_playlists": [],
    # Daily backup of accounts, watch history and settings (not the media) into data/backups.
    "backup_time": "01:30",
    "backup_keep": 14,
    # How many live conversions may run at once (each one uses a CPU core or the video encoder).
    "max_transcodes": 1,
}

_lock = threading.Lock()
_config = None


def path(key):
    return os.path.expanduser(get(key))


def load():
    global _config
    with _lock:
        data = {}
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            pass
        merged = copy.deepcopy(DEFAULTS)
        merged.update(data)
        _config = merged
        if not os.path.exists(CONFIG_PATH):
            _write(merged)
    return _config


def get(key):
    if _config is None:
        load()
    return _config[key]


def all_settings():
    if _config is None:
        load()
    return dict(_config)


def update(changes):
    if _config is None:
        load()
    with _lock:
        for k, v in changes.items():
            if k in DEFAULTS:
                _config[k] = v
        _write(_config)


def _write(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CONFIG_PATH)
