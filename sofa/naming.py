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
ADULT_DIRS = {"xxx", "adult", "adults", "porn", "nsfw", "18+", "x-rated", "xrated"}
# Folder names that are a kind of thing, not one title: kept as categories in the Adult section.
ADULT_CATEGORIES = {"movies", "films", "hentai", "anime", "cartoons", "animated", "series", "shows", "tv", "collections",
                    "scenes", "clips", "amateur", "homemade", "vr", "jav", "compilations", "erotic", "erotica",
                    "softcore", "classics", "vintage", "parodies", "gay", "lesbian", "trans", "fetish", "bdsm",
                    "cams", "webcam", "onlyfans", "studios", "pmv", "hmv", "asmr", "documentaries"}
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
    loose = _loose_episode(stem, season_hint)
    if loose:
        return loose
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


# Names without an SxxEyy that are still clearly episodes:
DASHED = re.compile(r"^(?:\[[^\]]*\]\s*)?(.+?)\s+-\s+(\d{1,4})(?:v\d)?(?=\s*(?:[\[(]|-|$))", re.I)   # "[Group] Frieren - 05 (1080p)"
EP_WORD = re.compile(r"(?:^|[\s._-])(?:ep|episode)[ ._-]?(\d{1,3})(?!\d)", re.I)                     # "Planet Earth II - Ep 1"
HAS_YEAR = re.compile(r"(?:^|[^0-9])(?:19|20)\d{2}(?![0-9])")
AFTER_CODE = re.compile(r"^[\s._-]*(?:hdtv|web|webrip|web-dl|pdtv|dsr|dvdrip|bdrip|brrip|bluray|xvid|divx|x26[45]|h\.?26[45]|"
                        r"720p|1080p|2160p|480p|repack|proper|internal)\b", re.I)


def _loose_episode(stem, season_hint=None):
    """Episodes named the way anime and some downloads are: "Show - 05", "Show Ep 1", "show.205.hdtv"."""
    if HAS_YEAR.search(stem):
        return None                                 # "Mission - 2 (1996)" is a movie
    m = DASHED.match(stem)
    if m and clean(m.group(1)) and not 1900 <= int(m.group(2)) <= 2099:
        rest = stem[m.end():]
        title = clean(re.sub(r"^\s*-\s*", "", rest)) if rest.strip().startswith("-") else None
        return {"s": season_hint or 1, "e": int(m.group(2)), "e2": None,
                "show": clean(re.sub(r"^\[[^\]]*\]\s*", "", m.group(1))), "title": title}
    m = EP_WORD.search(stem)
    if m and int(m.group(1)) and clean(stem[:m.start()]):
        return {"s": season_hint or 1, "e": int(m.group(1)), "e2": None, "show": clean(stem[:m.start()]),
                "title": clean(re.sub(r"^[\s._-]*-?", "", stem[m.end():]))}
    for c in CODE3.finditer(stem):                  # "breaking.bad.205.hdtv": only with release words after it
        s, e = int(c.group(1)), int(c.group(2))
        if s and e and clean(stem[:c.start(1)]) and AFTER_CODE.match(stem[c.end():]) and not NOT_CODE.search(stem[:c.start(1)]):
            return {"s": s, "e": e, "e2": None, "show": clean(stem[:c.start(1)]), "title": None}
    return None


DATED = re.compile(r"^(.+?)[\s._-]((?:19|20)\d{2})[\s._-](\d{2})[\s._-](\d{2})(?!\d)")


def parse_dated(stem):
    """Daily shows: "The Daily Show 2024 03 15" is that show's episode of 15 March 2024 (season 2024)."""
    m = DATED.match(stem)
    if not m or not clean(m.group(1)) or not (1 <= int(m.group(3)) <= 12 and 1 <= int(m.group(4)) <= 31):
        return None
    return {"s": int(m.group(2)), "e": int(m.group(3)) * 100 + int(m.group(4)), "e2": None, "show": clean(m.group(1)),
            "title": None, "date": "%s-%s-%s" % (m.group(2), m.group(3), m.group(4))}


def camera_name(stem):
    """'Video 2023-05-12 14.30' from a phone or camera file name (VID_20230512_143022, IMG_1234, PXL_..., GOPR0042)."""
    m = re.match(r"^(?:VID|IMG|PXL|MOV|MVI|DSC|DJI|GOPR|GH\d|GX\d|Screen Recording|RPReplay)[\s_-]*(\d{8})?[\s_-]*(\d{4,6})?", stem, re.I)
    if not m:
        return None
    if m.group(1):
        d, t = m.group(1), m.group(2) or ""
        return "Video %s-%s-%s%s" % (d[:4], d[4:6], d[6:8], (" %s.%s" % (t[:2], t[2:4])) if len(t) >= 4 else "")
    return "Video %s" % clean(stem)


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


# ---------------------------------------------------------------- adult scene names

SCENE_DATED = re.compile(
    r"^(?P<studio>[A-Za-z0-9][\w&'+!-]*(?:[ ._][A-Za-z][\w&'+!-]*){0,3}?)[ ._-]+"
    r"(?P<y>(?:19|20)?\d{2})[ ._-](?P<m>\d{2})[ ._-](?P<d>\d{2})[ ._-]+(?P<rest>.+)$")
SCENE_JUNK = re.compile(r"\b(xxx|mp4|wmv|sd|hd|fhd|uhd|4k|2160p|1080p|720p|480p|360p)\b.*$", re.I)
NAME_JOIN = re.compile(r"\s*(?:,|&|\band\b|\bx\b|\bwith\b|\bfeat\.?)\s*", re.I)


def _looks_like_name(text):
    words = text.split()
    return 1 <= len(words) <= 3 and all(w[:1].isupper() and w.replace("'", "").replace("-", "").isalpha() for w in words)


def _split_names(text):
    return [n.strip() for n in NAME_JOIN.split(text) if n.strip()]


def parse_scene(stem, known_performers=()):
    """Studio, date, performers and title from the ways adult scenes are usually named.

        Brazzers.21.03.14.Jane.Doe.And.John.Roe.Hot.Title.XXX.1080p.MP4-WRB
        [Studio] Jane Doe, John Roe - Hot Title (2019)
        Studio - Jane Doe - Hot Title
        Jane Doe - Hot Title

    Performers already known to the library are recognised anywhere at the start of a name;
    otherwise two-word names joined by "And" or "&" are taken as performers.
    Returns {"studio", "date", "year", "performers", "title"} (values may be None / []).
    """
    out = {"studio": None, "date": None, "year": None, "performers": [], "title": None}
    text = stem.strip()
    m = SCENE_DATED.match(text)
    if m and 1 <= int(m.group("m")) <= 12 and 1 <= int(m.group("d")) <= 31:
        y = int(m.group("y"))
        y = y if y > 1900 else (2000 + y if y < 70 else 1900 + y)
        out["studio"] = clean(m.group("studio").replace(".", " "))
        out["date"] = "%04d-%s-%s" % (y, m.group("m"), m.group("d"))
        out["year"] = y
        rest = clean(SCENE_JUNK.sub("", m.group("rest").replace(".", " ").replace("_", " ")))
        out["performers"], out["title"] = _performers_first(rest, known_performers)
        return out
    b = re.match(r"^\[(?P<studio>[^\]]+)\]\s*(?P<rest>.+)$", text)
    if b:
        out["studio"] = clean(b.group("studio"))
        text = b.group("rest")
    title, year = parse_movie(text)
    out["year"] = year
    parts = [p.strip() for p in re.split(r"\s+-\s+", SCENE_JUNK.sub("", title)) if p.strip()]
    if len(parts) >= 3 and not out["studio"]:
        out["studio"], parts = parts[0], parts[1:]
    if len(parts) >= 2:
        names = _split_names(parts[0])
        known = {norm(k) for k in known_performers}
        if names and all(norm(n) in known or _looks_like_name(n) for n in names):
            out["performers"], parts = names, parts[1:]
    rest = " - ".join(parts)
    if not out["performers"]:
        out["performers"], rest = _performers_first(rest, known_performers)
    out["title"] = rest or None
    return out


def _performers_first(rest, known_performers):
    """(performers, title) from 'Jane Doe And John Roe Hot Title'."""
    found, words = [], rest.split()
    known = sorted({k for k in known_performers if k}, key=len, reverse=True)
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:])
        hit = next((k for k in known if norm(chunk).startswith(norm(k)) and
                    norm(" ".join(words[i:i + len(k.split())])) == norm(k)), None)
        if hit:
            found.append(" ".join(words[i:i + len(hit.split())]))
            i += len(hit.split())
        elif found or re.match(r"^\S+\s+\S+\s+(?:and|&)\s+", chunk, re.I):
            # an unknown name joined to the others with "and": take two words as a name
            if i + 1 < len(words) and _looks_like_name(" ".join(words[i:i + 2])) and (
                    found and words[i - 1].lower() in ("and", "&") or re.match(r"^\S+\s+\S+\s+(?:and|&)\s+", chunk, re.I)):
                found.append(" ".join(words[i:i + 2]))
                i += 2
            else:
                break
        else:
            break
        if i < len(words) and words[i].lower() in ("and", "&", ","):
            i += 1
        elif found and i < len(words) and not any(norm(" ".join(words[i:])).startswith(norm(k)) for k in known):
            break
    return found, " ".join(words[i:]) or None
