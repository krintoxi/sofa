"""Reading show/episode/movie information out of messy file names."""
import re
import unicodedata

VIDEO_EXT = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".mpg", ".mpeg",
             ".ts", ".m2ts", ".vob", ".divx", ".ogv", ".3gp"}
SUB_EXT = {".srt", ".vtt", ".ass", ".ssa"}
PARTIAL_EXT = {".part", ".crdownload", ".download", ".partial", ".tmp", ".!qb", ".aria2"}

EPISODE = re.compile(r"(?:^|[^a-z0-9])s(\d{1,2})[ ._-]?e(\d{1,3})(?:-?e(\d{1,3}))?", re.I)
EPISODE_X = re.compile(r"(?:^|[^0-9])(\d{1,2})x(\d{2,3})(?![0-9])")
SEASON_DIR = re.compile(r"(?:^|[\s._-])(?:s|season\s*)(\d{1,2})$", re.I)
MOVIE_DIR = re.compile(r"^\[(\d{4})\]\s*(.+)$|^(.+?)\s*\((\d{4})\)$")
MOVIE_NAME = re.compile(r"^(.+?)[\s._(\[-]+((?:19|20)\d{2})(?:[\s._)\]-]|$)")
RELEASE_JUNK = re.compile(
    r"\b(hdtv|xvid|divx|x264|x265|h\.?264|h\.?265|hevc|web[ .-]?dl|webrip|web|bluray|blu-ray|brrip|bdrip|"
    r"dvdrip|hdrip|480p|576p|720p|1080p|2160p|4k|uhd|hdr|10bit|aac\d?(\.\d)?|ac3|dts|ddp?5\.1|atmos|"
    r"lol|dimension|killers|proper|repack|extended|remastered|amzn|nf|hulu|dsnp|internal|limited|"
    r"yify|yts|rarbg|ettv|eztv)\b.*$", re.I)


def clean(text):
    """Turn 'Chuck.Versus.the.Tango.HDTV-LOL' into 'Chuck Versus the Tango'."""
    while re.search(r"\[[^\[\]]*\]", text):
        text = re.sub(r"\[[^\[\]]*\]", " ", text)
    text = text.replace("{", "(").replace("}", ")")
    text = re.sub(r"_amp\b", "&", text)
    text = re.sub(r"_s\b", "'s", text)
    if " " not in text.strip():
        text = text.replace(".", " ")
    text = text.replace("_", " ")
    text = RELEASE_JUNK.sub("", text)
    text = re.sub(r"\(\s*\)", "", text)
    return re.sub(r"\s+", " ", text).strip(" -.&")


def parse_episode(stem):
    """{'s','e','e2','show','title'} for 'Show S01E02 Title' style names, else None."""
    m = EPISODE.search(stem) or EPISODE_X.search(stem)
    if not m:
        return None
    last = int(m.group(3)) if m.re is EPISODE and m.group(3) else None
    return {"s": int(m.group(1)), "e": int(m.group(2)), "e2": last,
            "show": clean(stem[:m.start()]), "title": clean(stem[m.end():])}


def season_of_dir(name):
    name = name.strip()
    if name.lower() == "specials":
        return 0
    m = SEASON_DIR.search(name)
    return int(m.group(1)) if m else None


def parse_movie(name):
    """(title, year) from 'Title (1999)', '[1999] Title' or 'Title.1999.1080p.BluRay'. Year may be None."""
    m = MOVIE_DIR.match(name.strip())
    if m:
        return (m.group(2) or m.group(3)).strip(), int(m.group(1) or m.group(4))
    m = MOVIE_NAME.match(name)
    if m:
        return clean(m.group(1)), int(m.group(2))
    return clean(name), None


def safe_filename(name):
    name = name.replace("/", "-").replace(":", " -").replace("?", "").replace("\\", "-")
    name = re.sub(r'[<>"|*\x00-\x1f]', "", name)
    return re.sub(r"\s+", " ", name).strip(" .")[:180]


def plain(text):
    """'QUIÉN' -> 'QUIEN': accents dropped, however the file system spelled them."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm(name):
    """Comparison key: 'N.C.I.S.' and 'NCIS', 'The Office' and 'Office' match."""
    n = re.sub(r"[^a-z0-9]+", "", plain(name).lower())
    return n[3:] if n.startswith("the") and len(n) > 6 else n


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", plain(text).lower()).strip("-") or "x"
