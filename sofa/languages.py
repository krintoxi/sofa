"""What language a video is in, and how sure Sofa is.

Three kinds of evidence, in this order, and each answer says which it came from:

  "tag"    the track's own language tag in the file ("spa", "es-419", "pt-BR"),
  "title"  the track's own name in the file ("Español Latino", "English 5.1"),
  "name"   markers in the file's or folder's name ("[eng+spa]", "LAT", "Dual Audio", "VOSE").

A name says what a file holds, not which track is which: with two unnamed tracks and "[eng+spa]" the title has
English and Spanish, and neither track is labelled. Nothing else is used: the language a title was made in is a
fact about the title, not the file (a dubbed copy has one track, in another language), so it's shown apart and
never stands in for a track.

Codes are two letters where there is one ("es"), with a region when the file says so ("es-419" Latin America,
"es-ES" Spain, "pt-BR").
"""

import os
import re
import unicodedata

# (code, three-letter codes, English name, Spanish name, other names it goes by in tags and file names)
_TABLE = (
    ("en", "eng", "English", "Inglés", "ingles english"),
    ("es", "spa esp", "Spanish", "Español", "espanol spanish castellano castilian"),
    ("fr", "fre fra", "French", "Francés", "francais french frances"),
    ("de", "ger deu", "German", "Alemán", "deutsch german aleman"),
    ("it", "ita", "Italian", "Italiano", "italiano italian"),
    ("pt", "por", "Portuguese", "Portugués", "portugues portuguese"),
    ("ja", "jpn jap", "Japanese", "Japonés", "japanese japones nihongo"),
    ("ko", "kor", "Korean", "Coreano", "korean coreano"),
    ("zh", "chi zho cmn", "Chinese", "Chino", "chinese mandarin chino mandarin"),
    ("yue", "yue", "Cantonese", "Cantonés", "cantonese cantones"),
    ("ru", "rus", "Russian", "Ruso", "russian ruso"),
    ("ar", "ara", "Arabic", "Árabe", "arabic arabe"),
    ("hi", "hin", "Hindi", "Hindi", "hindi"),
    ("nl", "dut nld", "Dutch", "Neerlandés", "dutch nederlands neerlandes holandes"),
    ("sv", "swe", "Swedish", "Sueco", "swedish svenska sueco"),
    ("da", "dan", "Danish", "Danés", "danish dansk danes"),
    ("no", "nor nob nno", "Norwegian", "Noruego", "norwegian norsk noruego"),
    ("fi", "fin", "Finnish", "Finés", "finnish suomi fines"),
    ("pl", "pol", "Polish", "Polaco", "polish polski polaco"),
    ("tr", "tur", "Turkish", "Turco", "turkish turkce turco"),
    ("he", "heb", "Hebrew", "Hebreo", "hebrew hebreo"),
    ("el", "gre ell", "Greek", "Griego", "greek griego"),
    ("cs", "cze ces", "Czech", "Checo", "czech cesky checo"),
    ("hu", "hun", "Hungarian", "Húngaro", "hungarian magyar hungaro"),
    ("th", "tha", "Thai", "Tailandés", "thai tailandes"),
    ("ca", "cat", "Catalan", "Catalán", "catalan catala"),
    ("gl", "glg", "Galician", "Gallego", "galician galego gallego"),
    ("eu", "baq eus", "Basque", "Euskera", "basque euskera euskara vasco"),
    ("ro", "rum ron", "Romanian", "Rumano", "romanian romana rumano"),
    ("uk", "ukr", "Ukrainian", "Ucraniano", "ukrainian ucraniano"),
    ("bg", "bul", "Bulgarian", "Búlgaro", "bulgarian bulgaro"),
    ("hr", "hrv", "Croatian", "Croata", "croatian hrvatski croata"),
    ("sr", "srp", "Serbian", "Serbio", "serbian srpski serbio"),
    ("sk", "slo slk", "Slovak", "Eslovaco", "slovak eslovaco"),
    ("sl", "slv", "Slovenian", "Esloveno", "slovenian esloveno"),
    ("vi", "vie", "Vietnamese", "Vietnamita", "vietnamese vietnamita"),
    ("id", "ind", "Indonesian", "Indonesio", "indonesian indonesio bahasa"),
    ("ms", "may msa", "Malay", "Malayo", "malay malayo"),
    ("tl", "tgl fil", "Filipino", "Filipino", "filipino tagalog"),
    ("fa", "per fas", "Persian", "Persa", "persian farsi persa"),
    ("ur", "urd", "Urdu", "Urdu", "urdu"),
    ("bn", "ben", "Bengali", "Bengalí", "bengali"),
    ("ta", "tam", "Tamil", "Tamil", "tamil"),
    ("te", "tel", "Telugu", "Telugu", "telugu"),
    ("ml", "mal", "Malayalam", "Malayalam", "malayalam"),
    ("is", "ice isl", "Icelandic", "Islandés", "icelandic islandes"),
    ("et", "est", "Estonian", "Estonio", "estonian estonio"),
    ("lv", "lav", "Latvian", "Letón", "latvian leton"),
    ("lt", "lit", "Lithuanian", "Lituano", "lithuanian lituano"),
    ("la", "lat", "Latin", "Latín", "latin"),
)
NOT_A_LANGUAGE = ("", "und", "unk", "zxx", "mul", "mis", "qaa", "nolang", "null", "none")

NAMES, NAMES_ES = {}, {}
_BY3, _BY_WORD = {}, {}
for _code, _threes, _en, _es, _words in _TABLE:
    NAMES[_code], NAMES_ES[_code] = _en, _es
    for _t in _threes.split():
        _BY3[_t] = _code
    for _w in _words.split():
        _BY_WORD[_w] = _code
_BY2 = {c: c for c in NAMES if len(c) == 2}
_BY3["lat"] = "la"          # (as a language tag: Latin. In a file's name "LAT" is Latin American Spanish, below.)

REGIONS = {"es-419": ("Spanish (Latin America)", "Español (Latinoamérica)"), "es-ES": ("Spanish (Spain)", "Español (España)"),
           "es-MX": ("Spanish (Mexico)", "Español (México)"), "pt-BR": ("Portuguese (Brazil)", "Portugués (Brasil)"),
           "pt-PT": ("Portuguese (Portugal)", "Portugués (Portugal)"), "fr-CA": ("French (Canada)", "Francés (Canadá)"),
           "en-GB": ("English (UK)", "Inglés (Reino Unido)"), "en-US": ("English (US)", "Inglés (EE. UU.)"),
           "zh-TW": ("Chinese (Traditional)", "Chino (tradicional)"), "zh-CN": ("Chinese (Simplified)", "Chino (simplificado)")}
_REGION_OF = {"419": "419", "la": "419", "latam": "419", "es": "ES", "mx": "MX", "br": "BR", "pt": "PT", "ca": "CA", "gb": "GB",
              "uk": "GB", "us": "US", "tw": "TW", "hant": "TW", "cn": "CN", "hans": "CN"}
# a track's name that says where its Spanish (or Portuguese, or French) is from
_REGION_WORDS = (("es", "419", ("latino", "latina", "latinoamerica", "latinoamericano", "latam", "latin america", "latin american", "lat")),
                 ("es", "MX", ("mexico", "mexicano", "mexican")),
                 ("es", "ES", ("castellano", "castilian", "espana", "european spanish", "spain", "peninsular")),
                 ("pt", "BR", ("brasil", "brazil", "brasileiro", "brazilian", "dublado")),
                 ("fr", "CA", ("quebec", "quebecois", "canadien", "canadian french", "vfq")))


def _plain(text):
    """Lower case, no accents: "Español" -> "espanol"."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(text or "")) if not unicodedata.combining(c)).lower().strip()


def base(code):
    """ "es-419" -> "es". """
    return (code or "").partition("-")[0]


def name(code, spanish=False):
    """ "es-419" -> "Spanish (Latin America)"; a code Sofa has no name for comes back in capitals."""
    if not code:
        return ""
    if code in REGIONS:
        return REGIONS[code][1 if spanish else 0]
    table = NAMES_ES if spanish else NAMES
    return table.get(base(code)) or code.upper()


def norm(tag):
    """A language tag as files write them ("spa", "es", "es-419", "pt_BR", "Spanish") -> "es", "es-419", "pt-BR";
    None when it names no language ("und", "", "zxx") or one Sofa doesn't know."""
    t = _plain(tag).replace("_", "-")
    if t in NOT_A_LANGUAGE:
        return None
    head, _, rest = t.partition("-")
    code = _BY2.get(head) or _BY3.get(head) or _BY_WORD.get(head)
    if not code:
        return None
    region = _REGION_OF.get(rest.split("-")[-1]) if rest else None
    if region and "%s-%s" % (code, region) in REGIONS:
        return "%s-%s" % (code, region)
    return code


def from_title(title):
    """The language a track's own name gives ("Español Latino" -> "es-419", "English 5.1" -> "en"), or None:
    only when the name starts with a language's name or is a language tag, so "Director's commentary" and
    "Surround 5.1" say nothing."""
    t = _plain(title)
    if not t:
        return None
    words = re.findall(r"[a-z]+|\d+", t)
    if not words:
        return None
    code = _BY_WORD.get(words[0]) or (norm(words[0]) if len(words[0]) == 3 and len(words) <= 3 else None)
    region = None
    for lang, reg, said in _REGION_WORDS:
        if any(re.search(r"\b%s\b" % re.escape(s), t) for s in said if s != "lat" or code == "es"):
            if code in (None, lang) and (code or words[0] in said):
                code, region = lang, reg
                break
    if not code:
        return None
    return "%s-%s" % (code, region) if region and "%s-%s" % (code, region) in REGIONS else code


# ---------------------------------------------------------------- a file's or folder's name

# words release names use for a language (only looked for in brackets or after the year: never in the title)
_NAME_WORDS = {
    "lat": "es-419", "latino": "es-419", "latam": "es-419", "castellano": "es-ES", "esp": "es", "spa": "es", "spanish": "es",
    "espanol": "es", "eng": "en", "english": "en", "ingles": "en", "ing": "en", "fre": "fr", "fra": "fr", "french": "fr",
    "truefrench": "fr", "vff": "fr", "vfq": "fr-CA", "ger": "de", "deu": "de", "german": "de", "ita": "it", "italian": "it",
    "por": "pt", "portuguese": "pt", "dublado": "pt-BR", "jpn": "ja", "jap": "ja", "japanese": "ja", "kor": "ko",
    "korean": "ko", "rus": "ru", "russian": "ru", "chi": "zh", "chinese": "zh", "mandarin": "zh", "hin": "hi", "hindi": "hi"}
# subtitles, not sound: "VOSE" is the original sound with Spanish subtitles
_SUB_WORDS = {"vose": "es", "vosi": "en", "vostfr": "fr", "subesp": "es", "subespanol": "es", "subtitulado": "es", "subeng": "en",
              "engsub": "en", "engsubs": "en", "esub": "en", "esubs": "en", "subita": "it", "subfrench": "fr", "subpt": "pt"}
_SUB_LEAD = ("sub", "subs", "subbed", "subtitles", "subtitulos", "subt")
# after an episode's code or a date comes the episode's own title ("Psych S05E12 Dual Spires", "The News Hour
# 2026-11-14 Spanish Class"): there only what can't be a title's word counts, until the picture size or the source
_SURE = ("lat", "latino", "latam", "castellano", "esp", "spa", "eng", "vose", "vosi", "vostfr", "subesp", "subespanol",
         "subtitulado", "dublado", "truefrench", "vff", "vfq", "jpn", "ger", "deu", "fre", "rus", "kor")
_EPISODE = re.compile(r"(?<![a-z0-9])(?:s\d{1,4}e\d{1,4}|\d{1,2}x\d{2,3}|(?:19|20)\d\d[ ._-]\d\d[ ._-]\d\d)(?![a-z0-9])", re.I)
_RELEASE = re.compile(r"(?<![a-z0-9])(?:(?:480|576|720|1080|2160)[pi]|4k|blu-?ray|b[dr]rip|web-?(?:dl|rip)?|hdtv|dvdrip|remux|[xh]\.?26[45]|hevc|xvid)(?![a-z0-9])", re.I)
_TAIL = re.compile(r"(?<![a-z0-9])(?:(?:19|20)\d\d|s\d{1,4}e\d{1,4}|\d{1,2}x\d{2,3}|(?:480|576|720|1080|2160)[pi]|4k)(?![a-z0-9])", re.I)
_GROUP = re.compile(r"\[([^\]]*)\]|\(([^)]*)\)|\{([^}]*)\}")


def _combo(text):
    """A group that is nothing but language codes ("eng+spa", "EN-ES", "en, es, fr"): its languages, else None."""
    parts = [p for p in re.split(r"[\s+,/&._-]+", _plain(text)) if p]
    if len(parts) < 2:
        return None
    out = []
    for p in parts:
        code = _BY2.get(p) if len(p) == 2 else (_BY3.get(p) if p != "lat" else "es-419") if len(p) == 3 else None
        if not code:
            return None
        out.append(code)
    return out


def from_names(*names):
    """What the names of a file and its folders say: {"audio": [codes], "subs": [codes], "dual": bool, "multi": bool}.
    Only what's in brackets or after the year, the episode code or the picture size: "Dual (2013)" is a title, and
    "Spanish Affair (2014)" isn't in Spanish because of its name."""
    audio, subs, dual, multi = [], [], False, False

    def add(to, code):
        if code and code not in to and not (base(code) == code and any(base(x) == code for x in to)):
            to[:] = [x for x in to if not (x == base(code) and x != code)] + [code]     # "es" then "es-419": the closer one

    for raw in names:
        text = _plain(raw)
        if not text:
            continue
        chunks, m = [], re.search(r"\((?:19|20)\d\d\)", text) or _TAIL.search(text)    # ("2001 A Space Odyssey (1968)")
        ep = _EPISODE.search(text)
        if ep and (m is None or ep.start() <= m.start() or _EPISODE.match(text, m.start())):
            m = ep
        else:
            ep = None
        for g in _GROUP.finditer(text):
            inner = next(x for x in g.groups() if x is not None)
            if m is None or g.start() < m.start():
                chunks.append((inner, False))
        if m and ep:                                      # an episode: its title (only the sure words), then the rest
            tail = text[m.end():]
            cut = _RELEASE.search(tail)
            for g in _GROUP.finditer(tail[:cut.start()] if cut else tail):
                chunks.append((next(x for x in g.groups() if x is not None), False))
            chunks.append((_GROUP.sub(" ", tail[:cut.start()] if cut else tail), True))
            if cut:
                chunks.append((tail[cut.start():], False))
        elif m:
            chunks.append((text[m.end():], False))
        for chunk, title in chunks:
            for g in [x for grp in _GROUP.findall(chunk) for x in grp if x] + ([] if title else [chunk]):
                for code in _combo(g) or ():
                    add(audio, code)
            words = re.findall(r"[a-z0-9]+", chunk)
            sub_next = False
            for i, w in enumerate(words):
                nxt = words[i + 1] if i + 1 < len(words) else ""
                if title and not (w in _SURE or w in ("dualaudio", "2audio") or (w == "dual" and nxt == "audio")
                                  or (w in _SUB_LEAD and nxt in _SURE)):
                    sub_next = False
                    continue
                if w == "dual" or (w in ("2audio", "dualaudio")):
                    dual = True
                elif w in ("multi", "multiaudio", "multilang", "multilanguage") or (w == "multi" and nxt == "audio"):
                    multi = True
                elif w in _SUB_WORDS:
                    add(subs, _SUB_WORDS[w])
                elif w in _SUB_LEAD:
                    sub_next = True
                    continue
                elif w in _NAME_WORDS:
                    add(subs if sub_next else audio, _NAME_WORDS[w])
                sub_next = False
    return {"audio": audio, "subs": subs, "dual": dual, "multi": multi}


# ---------------------------------------------------------------- names Sofa tidied away

def remember(path, *old_names):
    """Sofa is giving a file or folder a tidy name ("Coco.2017.1080p.LAT.ENG.mkv" -> "Coco (2017).mkv"): what the old
    name said of its languages is kept for where it is now, or the tidying would lose it. Only names that say
    something; never anything of the Adult section (its names stay in its own folders)."""
    said = [n for n in old_names if n and any(from_names(n).values())]
    if not said:
        return
    from . import config, places, store
    here = os.path.abspath(path)
    for root in [config.path("adult")] + [r for _k, r in places.roots("adult")]:
        if root and (here + os.sep).startswith(os.path.abspath(root) + os.sep):
            return
    try:
        row = store.q1("SELECT said FROM name_said WHERE path = ?", path)
        have = (row["said"].split("\n") if row else [])
        store.ex("INSERT OR REPLACE INTO name_said (path, said) VALUES (?,?)", path,
                 "\n".join((have + [n for n in said if n not in have])[-4:]))
    except Exception:
        pass                                              # (a help, not a need: the tidying goes on)


def remembered():
    """{path: [old names]} of everything remember() kept: read once a scan."""
    from . import store
    try:
        return {r["path"]: r["said"].split("\n") for r in store.q("SELECT path, said FROM name_said")}
    except Exception:
        return {}


# ---------------------------------------------------------------- a subtitle file's ending

SUB_FLAGS = {"forced": "forced", "forzado": "forced", "forzados": "forced", "sdh": "sdh", "cc": "sdh", "hi": "sdh"}


def sidecar(tail):
    """A subtitle file's ending after the video's name ("es", "es.forced", "spa.sdh", "English") ->
    (code or None, {"forced", "sdh"})."""
    code, flags = None, set()
    for part in [p for p in re.split(r"[.\s_]+", tail or "") if p]:
        flag = SUB_FLAGS.get(part.lower())
        got = None if code else (norm(part) or from_title(part))
        if got and not (flag and len(part) == 2 and flags):
            code = got
        elif flag:
            flags.add(flag)
    return code, flags


def said_flags(t):
    """A subtitle track's flags, its own or in its name ("English SDH", "Forzados"): (forced, sdh)."""
    title = _plain(t.get("title"))
    return (bool(t.get("forced") or re.search(r"\bforc|\bforz", title)),
            bool(t.get("sdh") or re.search(r"\b(sdh|cc|hearing|sordos)\b", title)))


# ---------------------------------------------------------------- a title's languages

def track(t):
    """One sound or subtitle track from sofa.media.probe -> (code or None, "tag" | "title" | None)."""
    code = norm(t.get("lang"))
    if code:
        named = from_title(t.get("title"))             # "spa" named "Latino": the name says which Spanish
        if named and base(named) == code and named != code:
            return named, "tag"
        return code, "tag"
    code = from_title(t.get("title"))
    return (code, "title") if code else (None, None)


def _unique(codes):
    out = []
    for c in codes:
        if c and c not in out:
            out.append(c)
    return out


def of(info, names=(), side_subs=()):
    """A title's languages from what Sofa has read of its file (`info`: sofa.media.probe, or None when it hasn't been
    read yet), its names, and the subtitle files beside it:

        {"audio": [{"code", "by"}] one per sound track (code None: unknown),
         "subs": [{"code", "by"}] one per subtitle track and file,
         "a": [codes] the sound's languages, "s": [codes] the subtitles',
         "named": [codes] those of "a" known only from a name, "sub_named": [...],
         "tracks": how many sound tracks (None: not read yet), "dual": a name says two or more}
    """
    said = from_names(*names)
    audio = [dict(zip(("code", "by"), track(t))) for t in (info or {}).get("audio") or []]
    subs = [dict(zip(("code", "by"), track(t))) for t in (info or {}).get("subs") or []]
    for s in side_subs:
        code = sidecar(s.get("lang") if s.get("lang") != "und" else "")[0]
        subs.append({"code": code, "by": "file" if code else None})
    a = _unique(x["code"] for x in audio)
    named = []
    unknown = [x for x in audio if not x["code"]]
    extra = [c for c in said["audio"] if not any(base(c) == base(k) for k in a)]
    if info is None or not audio:
        named = extra if info is None else []
    elif unknown and extra and len(extra) <= len(unknown):
        named = extra
        if len(unknown) == 1 and len(extra) == 1:        # one unnamed track, one language in the name: that's the one
            unknown[0].update(code=extra[0], by="name")
    s = _unique(x["code"] for x in subs)
    sub_named = [c for c in said["subs"] if not any(base(c) == base(k) for k in s)]
    if info is not None and not any(not x["code"] for x in subs):
        sub_named = []                                   # every subtitle track is named: the file's own word stands
    return {"audio": audio, "subs": subs, "a": a + named, "s": s + sub_named, "named": named, "sub_named": sub_named,
            "tracks": len(audio) if info is not None else None,
            "dual": bool(said["dual"] or said["multi"] or len(said["audio"]) > 1)}


def compact(found):
    """What goes on a title in the library's list (small: there's one for every file): {"a": [...], "s": [...],
    "n": sound tracks when more than the languages say, "by": "name" when a language is only from a name,
    "dual": True when a name says two or more and the file hasn't said which}. None when there's nothing to say."""
    out = {}
    if found["a"]:
        out["a"] = found["a"]
    if found["s"]:
        out["s"] = found["s"]
    if (found["tracks"] or 0) > max(1, len(found["a"])):
        out["n"] = found["tracks"]
    if found["named"]:
        out["by"] = "name"
    if found["dual"] and len(found["a"]) < 2 and (found["tracks"] is None or found["tracks"] > 1):
        out["dual"] = True
    return out or None


def gather(entries):
    """A show's languages from its episodes' (their `compact` values): each language most episodes first, and how
    many episodes have it when not all do: {"a": [...], "s": [...], "some": {code: episodes}, "by": "name"}."""
    counts, sub_counts, total, by_name = {}, {}, 0, False
    for e in entries:
        total += 1
        for c in _unique(base(x) for x in (e or {}).get("a") or []):
            counts[c] = counts.get(c, 0) + 1
        for c in _unique(base(x) for x in (e or {}).get("s") or []):
            sub_counts[c] = sub_counts.get(c, 0) + 1
        by_name = by_name or (e or {}).get("by") == "name"
    if not counts and not sub_counts:
        return None
    out = {"a": sorted(counts, key=lambda c: -counts[c]), "s": sorted(sub_counts, key=lambda c: -sub_counts[c])}
    some = {c: n for c, n in counts.items() if n < total}
    if some:
        out["some"] = some
    if by_name:
        out["by"] = "name"
    return {k: v for k, v in out.items() if v}
