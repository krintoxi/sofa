"""Reading show/episode/movie information out of messy file names."""
import re
import unicodedata

VIDEO_EXT = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".mpg", ".mpeg",
             ".ts", ".m2ts", ".vob", ".divx", ".ogv", ".3gp"}
SUB_EXT = {".srt", ".vtt", ".ass", ".ssa"}
PARTIAL_EXT = {".part", ".crdownload", ".download", ".partial", ".tmp", ".!qb", ".aria2"}

EPISODE = re.compile(r"(?:^|[^a-z0-9])s(\d{1,2})[ ._-]?e(\d{1,3})(?:-?e(\d{1,3}))?", re.I)
EPISODE_X = re.compile(r"(?:^|[^0-9])(\d{1,2})x(\d{2,3})(?![0-9])")
EPISODE_WORDS = re.compile(r"(?:^|[^a-z])season[ ._-]*(\d{1,2})[ ._,-]*(?:episode|ep)[ ._-]*(\d{1,3})", re.I)
EPISODE_ONLY = re.compile(r"(?:^|[\s._-])(?:e|ep|episode|chapter|part)[ ._-]?(\d{1,3})(?!\d)", re.I)
CODE3 = re.compile(r"(?:^|[\s._-])(\d{1,2})(\d{2})(?=$|[\s._-])")          # "Sopranos 101 Pilot" = S01E01
NOT_CODE = re.compile(r"(?:[hx][ ._]?|ddp?|aac|dts|mp)$", re.I)                  # H.264, x265, DDP5.1 ...
ADULT_DIRS = {"xxx", "adult", "adults", "porn", "nsfw", "18+", "x-rated", "xrated", "erotic"}
COLLECTION_WORDS = re.compile(
    r"\b(collection|saga|trilogy|quadrilogy|pentalogy|hexalogy|anthology|box[ ._-]?set|boxset|complete|pack|"
    r"movies|films|duology|series)\b", re.I)
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


def parse_episode(stem, season_hint=None, in_show=False):
    """{'s','e','e2','show','title'} for 'Show S01E02 Title' style names, else None.

    `season_hint` (the file is in a "Season 2" folder) and `in_show` (it's inside a show's folder)
    allow looser names: "Episode 5", "05 - Title", "Sopranos 101 Pilot".
    """
    m = EPISODE.search(stem) or EPISODE_X.search(stem) or EPISODE_WORDS.search(stem)
    if m:
        last = int(m.group(3)) if m.re is EPISODE and m.group(3) else None
        return {"s": int(m.group(1)), "e": int(m.group(2)), "e2": last,
                "show": clean(stem[:m.start()]), "title": clean(stem[m.end():])}
    if season_hint is None and not in_show:
        return None
    bare = RELEASE_JUNK.sub("", stem)
    for c in CODE3.finditer(bare):
        s, e = int(c.group(1)), int(c.group(2))
        if not e or not s or 1900 <= s * 100 + e <= 2099 or NOT_CODE.search(bare[:c.start(1)]):
            continue
        if season_hint is not None and s != season_hint:
            continue
        return {"s": s, "e": e, "e2": None, "show": clean(bare[:c.start(1)]), "title": clean(bare[c.end():])}
    if season_hint is not None:
        m = re.match(r"^\s*(\d{1,3})(?!\d)", bare) or EPISODE_ONLY.search(bare)
        if m and int(m.group(1)):
            return {"s": season_hint, "e": int(m.group(1)), "e2": None, "show": clean(bare[:m.start()]),
                    "title": clean(bare[m.end():])}
    return None


def show_name(folder):
    """('The Sopranos', 1999) from 'The.Sopranos.1999.S01-S06.Complete.Series.1080p.BluRay.x265-HOSTILE'."""
    text = clean(folder)
    year = None
    m = re.search(r"\(?\b((?:19|20)\d{2})\b\)?", text)
    if m and text[:m.start()].strip(" -.("):
        year = int(m.group(1))
        text = text[:m.start()]
    text = re.sub(r"[\s._-]*\b(?:the[\s._-]+)?(?:complete|full)\b.*$", "", text, flags=re.I)
    text = re.sub(r"[\s._-]*\b(?:(?:seasons?|series|temporadas?)[\s._-]*\d{1,2}(?:[\s._-]*(?:-|to|&)[\s._-]*\d{1,2})?"
                  r"|s\d{1,2}(?:[\s._-]*(?:-|to|&)[\s._-]*s?\d{1,2})?)\b.*$", "", text, flags=re.I)
    text = text.strip(" -.&,(")
    return (text or clean(folder) or folder), year


def collection_name(folder):
    """'Star Wars Collection' from 'Star.Wars.Movie.Collection.1977-2019.1080p'."""
    text = clean(folder)
    text = re.sub(r"\(?\b(?:19|20)\d{2}\s*[-–]\s*(?:19|20)?\d{2}\b\)?", "", text)
    text = re.sub(r"\b(?:I{1,3}|IV|V|VI{0,3}|IX|\d)\s*[-–]\s*(?:I{1,3}|IV|V|VI{0,3}|IX|\d)\b", "", text)
    text = re.sub(r"\b\d{1,2}[\s-]*(?:film|movie)s?\b", "", text, flags=re.I)
    text = COLLECTION_WORDS.sub("", text)
    text = re.sub(r"\b(?:the\s+)?(?:movie|film|complete|ultimate|all)\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -.&,()")
    return (text + " Collection") if text else clean(folder)


def strip_part(title):
    """'Kill Bill CD1' and 'Kill Bill CD2' are one movie in two files."""
    return re.sub(r"[\s._-]*\b(?:cd|disc|disk|dvd|part|pt)[\s._-]*\d\b.*$", "", title, flags=re.I).strip() or title


def is_adult_dir(name):
    return name.strip().lower() in ADULT_DIRS


SEASON_ANY = re.compile(r"(?:^|[\s._-])(?:season|temporada|series|saison|staffel)[\s._-]*(\d{1,2})(?!\d)|(?:^|[\s._-])s(\d{1,2})(?![\de])",
                        re.I)


def season_of_dir(name):
    """2 for "Season 2", "S02", "The Sopranos Season 2 (2000) 1080p"; 0 for "Specials"; else None."""
    name = name.strip()
    if name.lower() in ("specials", "season 0", "season 00"):
        return 0
    m = SEASON_DIR.search(name) or SEASON_ANY.search(name)
    return int(m.group(1) or m.group(2)) if m else None


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
