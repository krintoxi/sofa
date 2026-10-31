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
    "music": "~/Entertainment/Music",
    "musicvideos": "~/Entertainment/Music Videos",
    # Drop anything here; Sofa identifies it and files it into Shows or Movies.
    "inbox": "~/Entertainment/Inbox",
    # Where Sofa puts things it can't identify, for you to look at.
    "review": "~/Entertainment/Needs Review",
    # Adult movies and series: Adult/Movies/<Title>/..., Adult/Shows/<Show>/Season N/...
    # Only people an admin allows (Server page, People) ever see it; never guests, never TVs.
    "adult": "~/Entertainment/Adult",
    # After converting a file to MP4, move the original here (or delete it when keep_originals is false).
    "originals": "~/Entertainment/Converted Originals",
    # More library places on other drives (Server → Storage): [{"id", "name", "path"}], and the one the
    # Inbox files new things into ("" = the main folders above).
    "places": [],
    "file_new_to": "",
    # Where to look for drives plugged into this computer (empty: /Volumes on a Mac, /media and /mnt on Linux).
    "drive_folders": [],
    # Videos an admin deletes from the app go here first (empty it from the Server page, or by hand).
    # Empty: a "Deleted" folder next to the Shows folder (on the same drive, so deleting is instant).
    "deleted": "",
    # Share the library with TVs on the home network (Roku Media Player, VLC, smart TVs).
    "dlna": True,
    # "home": only private networks (Wi-Fi, Tailscale) may connect.
    # "public": also accept internet connections (put Sofa behind HTTPS first, see docs/remote-access.md).
    "remote": "home",
    # Set when a reverse proxy (Caddy, nginx) on this machine forwards to Sofa.
    "trust_proxy": False,
    # Let visitors on the home Wi-Fi watch as "Guest" (their own history, no settings) via /guest.
    "guest_access": True,
    "signups": False,             # "Create an account" on the sign-in page; an admin approves each one
    # Look up show summaries and missing artwork on TVmaze (free, no key).
    "tvmaze": True,
    # Optional: a TMDB API key adds the best movie posters, backdrops, summaries and collections.
    # Without one, Sofa uses the iTunes Store and Wikipedia (no key needed).
    "tmdb_api_key": "",
    # Look up movies without a TMDB key on the iTunes Store and Wikipedia.
    "free_movie_lookup": True,
    # Optional: a ThePornDB (theporndb.net) API token adds artwork and details to the Adult section.
    "theporndb_api_key": "",
    # Tidy the library folders: messy names become "Title (Year)", loose movies in a collection folder get
    # their own folders, and stray "XXX"/"Adult" folders move into the Adult section.
    "tidy_library": True,
    # ffmpeg folder or "auto" (vendor/ffmpeg, Homebrew, PATH).
    "ffmpeg": "auto",
    # Live TV channel lists (M3U). Each: {"name": ..., "url": ...}
    "live_playlists": [],
    # Where updates come from (the Update button on the Server page, and tools/update.sh).
    "update_repo": "krintoxi/sofa",
    "update_branch": "main",
    # Daily backup of accounts, watch history and settings (not the media) into data/backups.
    "backup_time": "01:30",
    "backup_keep": 3,
    # How many live conversions may run at once (each one uses a CPU core or the video encoder).
    "max_transcodes": 2,
    # Convert MKV, AVI and other files that need live conversion into MP4, once, in the background.
    "auto_convert": True,
    "keep_originals": True,
    # The look every device starts with (people can pick their own): midnight, cinema, ocean, forest, grape, oled.
    "theme": "midnight",
    # yt-dlp for "Save from a link": "auto" (Sofa's own copy in data/bin, Homebrew, PATH) or a full path.
    "ytdlp": "auto",
    # Skip downloads bigger than this many GB (0: no limit).
    "download_max_gb": 0,
    # Listen for each season's shared intro and credits so the player can offer "Skip Intro".
    "detect_intros": True,
    # Make the small pictures shown above the seek bar while scrubbing.
    "trickplay": True,
    "previews": True,
    # Gentle mode for older computers: "auto" (on when Sofa finds the computer slow), true or false.
    # Video converted while you watch is then 720p at most, and heavy background work waits for the quiet hours.
    "gentle": "auto",
    "quiet_hours": "01:00-07:00",
    # HTTPS (tls.py): "off", "letsencrypt" (for `domain`), "files" (cert_file + key_file) or "self" (Sofa's own).
    "https": "off",
    "domain": "",
    "https_port": 8443,
    "acme_email": "",
    "acme_directory": "",          # empty: Let's Encrypt itself (tests use their own)
    "cert_file": "",
    "key_file": "",
    # A free yourname.duckdns.org address kept pointing at this home (ddns.py), and asking the router to open
    # its ports for Sofa (upnp.py).
    "duckdns_token": "",
    "upnp": False,
    # Keep the computer from going to sleep by itself while Sofa runs (the screen can still turn off).
    "keep_awake": True,
    # Offline: never use the internet (no details or artwork lookups, update checks, downloads or channel lists).
    "offline": False,
    # Keep no logs: nothing about what happens on this server is written anywhere (activity, server log, histories).
    "no_logs": False,
    # Downloads from sites that want a sign-in or an age check: "safari", "chrome", "firefox", ... (that browser's
    # session on this computer), "file" (data/bin/cookies.txt), or "" for none.
    "ytdlp_cookies": "",          # hover previews: short silent clips, made as they're needed
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
