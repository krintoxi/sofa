"""Live TV from the Internet Archive (archive.org): channels of free films, classic movies, film noir, westerns,
silent films, cartoons, classic TV and more, each played like a TV channel. A channel is a list of films on a loop,
on the clock: tuning in lands in the middle of what's on, and the next film follows.

The films come straight from archive.org to the screen (not through Sofa). Which films: the most watched of each
category that has one playable video file and a length, leaving out what doesn't belong on a family TV (the
archive's films include exploitation pictures). A channel's list is fetched the first time someone tunes in, and
again after a week; it's kept in data/cache/archive.
"""
import functools
import hashlib
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config, net

CACHE = os.path.join(config.DATA_DIR, "cache", "archive")
UA = "Sofa (github.com/krintoxi/sofa)"
KEEP = 7 * 86400                     # a channel's films, before they're fetched again
FILMS = 30                           # films on a channel
ANCHOR = 1704067200                  # 2024-01-01: where every channel's clock starts (the same for every viewer)

# what doesn't belong on a family TV box (the archive's films include exploitation pictures and scare films)
NOT = (' AND NOT subject:(sex OR sexploitation OR erotic OR erotica OR nudity OR nudist OR adult OR burlesque OR'
       ' "exploitation film" OR exploitation OR drugs OR stag OR pinup OR striptease)'
       ' AND NOT title:(sex OR sexy OR nude OR naked OR nudist OR burlesque OR strip OR striptease OR molester OR'
       ' madness OR erotic OR virgin OR orgy OR lust OR perversion OR porn OR fetish OR xxx OR jailbait OR stripper OR'
       ' playboy OR hentai OR marijuana OR cannabis OR "girls gone wild" OR "rated x" OR adult OR Marlboro OR cigarette OR'
       ' cigarettes OR tobacco)')
NOT_WORDS = re.compile(r"\b(sex|sexy|nude|naked|nudist|burlesque|strip|striptease|strippers?|molest\w*|erotic\w*|orgy|lust|"
                       r"xxx|pervers\w*|porn\w*|fetish\w*|jailbait|playboy|hentai|marijuana|cannabis|girls gone wild|rated x|adults?|"
                       r"marlboro|cigarettes?|tobacco)\b", re.I)

# id, name, the archive search, a colour and a mark for its logo
CHANNELS = [
    ("ia-classics", "Classic Movies", "collection:(feature_films) AND mediatype:(movies) AND year:[1930 TO 1975]", "#C8A24A", "★"),
    ("ia-noir", "Film Noir", "collection:(feature_films OR film_noir) AND subject:(\"film noir\" OR noir) AND year:[1940 TO 1965]", "#5B6B7F", "◐"),
    ("ia-scifi", "Sci-Fi & Horror", "collection:(SciFi_Horror)", "#3FA36B", "✦"),
    ("ia-comedy", "Comedy", "collection:(feature_films) AND subject:(comedy)", "#E2862F", "☺"),
    ("ia-westerns", "Westerns", "collection:(feature_films) AND subject:(western OR westerns)", "#A0522D", "☼"),
    ("ia-silent", "Silent Films", "collection:(silent_films)", "#8A8A8A", "❖"),
    ("ia-cartoons", "Cartoons", "collection:(classic_cartoons)", "#E2483D", "✿"),
    ("ia-tv", "Classic TV", "collection:(classic_tv) AND mediatype:(movies)", "#3D7BE2", "▣"),
    ("ia-docs", "Documentaries", "collection:(prelinger OR documentaries) AND mediatype:(movies)", "#2E9C9A", "◉"),
]
# (cigarette advertising was on TV until 1971: not on this one)
NO_SMOKING = (' AND NOT title:("Virginia Slims" OR Winston OR Salem OR Camel OR Kool OR Newport OR "Lucky Strike" OR'
              ' "Pall Mall" OR Viceroy OR Chesterfield OR Tareyton OR "Benson & Hedges" OR Parliament OR Kent OR Raleigh OR'
              ' smoking OR smoke OR cigar OR cigars)')
# Retro TV: a decade's television as it went out, its shows with two or three of that decade's commercials between them
# (the archive's classic TV, its TV commercials, and from the 80s on, off-air recordings with their own breaks)
def _retro(decade, colour):
    years = "year:[%d TO %d]" % (decade, decade + 9)
    shows = "mediatype:(movies) AND %s AND (collection:(classic_tv)%s)" % (
        years, ' OR title:("VHS Recording" OR "with commercials" OR "Saturday Morning")' if decade >= 1980 else "")
    ads = ('mediatype:(movies) AND %s AND (collection:(classic_tv_commercials) OR subject:("tv commercials" OR'
           ' "television commercials"))' % years)
    ads += NO_SMOKING
    name = "%02ds" % (decade % 100)
    return ("ia-retro%s" % name[:2], "Retro TV: %s" % name, shows, colour, name, ads)


# The 2000s first (most asked for): the decade's shows with its commercials, then whole recorded broadcasts, each kind
# on a channel of its own ("as it aired": the commercials, station idents and promos are the ones on the tape)
Y00 = "year:[2000 TO 2009]"
TV00 = "mediatype:(movies) AND %s AND title:(%%s)" % Y00
SAT = ('"Saturday Morning" OR "Kids WB" OR "Kids\' WB" OR "Fox Box" OR "4Kids TV" OR "One Saturday Morning" OR "ABC Kids"'
       ' OR Qubo OR "Discovery Kids" OR "Fox Kids"')
TOONS = 'Toonami OR Miguzi OR "Cartoon Cartoon" OR "Cartoon Network Fridays"'
MUSIC = ('TRL OR "Total Request Live" OR "MTV Hits" OR "VH1 Top 20" OR "Video Countdown" OR "music videos" OR "106 & Park"'
         ' OR MuchMusic OR Fuse')
GAMES = ('G4 OR G4TV OR "X-Play" OR TechTV OR "Electric Playground" OR "Screen Savers" OR "Attack of the Show" OR'
         ' "video game commercials" OR "Nintendo commercials"')
KIDS = '"Cartoon Network" OR Nickelodeon OR "Nick Jr" OR Noggin OR "Disney Channel" OR "Kids WB" OR Toonami OR "Fox Kids" OR Jetix OR "4Kids" OR "PBS Kids" OR "Playhouse Disney" OR "Toon Disney"'
CHANNELS += [_retro(2000, "#00897B"),
             ("ia-kids00", "00s Kids TV", TV00 % KIDS, "#F57C00", "00s"),
             ("ia-sat00", "00s Saturday Mornings", TV00 % SAT, "#FFB300", "SAT"),
             ("ia-toons00", "00s Action Toons", TV00 % TOONS, "#E53935", "ACT"),
             ("ia-air00", "00s On Air", 'mediatype:(movies) AND %s AND title:("with commercials" OR "commercial break" OR'
              ' "full broadcast" OR "VHS Recording" OR "TV recording") AND NOT title:(%s)' % (Y00, KIDS), "#5E35B1", "00s"),
             ("ia-music00", "00s Music TV", TV00 % MUSIC + ' AND NOT title:(dub OR dubbed OR dublado OR "motion comic")',
              "#D81B60", "♪"),
             ("ia-game00", "00s Game TV", TV00 % GAMES, "#43A047", "▶"),
             ("ia-info00", "00s Infomercials", TV00 % 'infomercial OR infomercials OR "As Seen On TV"' +
              ' AND NOT title:(Hellraiser OR horror OR "after dark")', "#6D4C41", "$"),
             _retro(1990, "#7B1FA2"), _retro(1980, "#C2185B"), _retro(1970, "#B5651D"), _retro(1960, "#D9822B"),
             _retro(1950, "#4F7CAC")]


# More of each era: recorded broadcasts (their own breaks in them), kids' TV, music TV and the commercial breaks people
# taped, each era's own. (Titles name what's on the tape: "with commercials", the channel, the block.)
def _tv(y0, y1, words):
    return "mediatype:(movies) AND year:[%d TO %d] AND title:(%s)" % (y0, y1, words)


ON_AIR = ('"with commercials" OR "commercial break" OR "commercial breaks" OR "full broadcast" OR "VHS Recording" OR'
          ' "TV recording" OR "DVR recording" OR "original broadcast" OR "as aired"')
BREAKS = 'commercials OR "commercial compilation" OR "commercial block" OR "ad break"'
KIDS10 = ('"Cartoon Network" OR Nickelodeon OR "Nick Jr" OR "Disney XD" OR "Disney Channel" OR "Disney Junior" OR "The Hub"'
          ' OR "Hub Network" OR Nicktoons OR "Kids WB" OR "PBS Kids" OR Boomerang')
POP10 = ('"VH1 Top 20" OR "MTV Hits" OR Fuse OR "106 & Park" OR "music video countdown" OR MuchMusic OR "Top 40 countdown" OR'
         ' "Attack of the Show" OR "X-Play" OR G4 OR G4TV OR GameTrailers OR "Bonus Round"')
KIDS90 = ('"Fox Kids" OR Nickelodeon OR "Cartoon Network" OR "Disney Afternoon" OR "Kids WB" OR "Nick Jr" OR "Disney Channel"'
          ' OR "One Saturday Morning" OR Snick OR Toonami')
SAT90 = ('"Saturday Morning" OR "Saturday mornings" OR "Fox Kids" OR "Kids WB" OR "One Saturday Morning" OR "CBS Saturday"'
         ' OR "NBC Saturday"')
MUSIC90 = 'MTV OR VH1 OR "120 Minutes" OR "Yo! MTV Raps" OR "Headbangers Ball" OR "Friday Night Videos" OR "Video countdown"'
SAT80 = ('"Saturday Morning" OR "Saturday mornings" OR "Saturday morning cartoons" OR "CBS Saturday" OR "NBC Saturday" OR'
         ' "ABC Saturday"')
MUSIC80 = 'MTV OR "Friday Night Videos" OR "Solid Gold" OR "American Bandstand" OR "Night Tracks" OR "Video countdown"'
CHANNELS += [
    ("ia-air10", "10s On Air", _tv(2009, 2012, ON_AIR) + " AND NOT title:(%s)" % KIDS10, "#1E88E5", "10s"),
    ("ia-kids10", "10s Kids TV", _tv(2009, 2012, KIDS10), "#FB8C00", "10s"),
    ("ia-pop10", "10s Music & Games", _tv(2009, 2012, POP10), "#8E24AA", "♪"),
    ("ia-ads10", "10s Commercial Breaks", _tv(2009, 2012, BREAKS) + NO_SMOKING, "#00ACC1", "AD"),
    ("ia-ads00", "00s Commercial Breaks", _tv(2000, 2008, BREAKS) + NO_SMOKING, "#26A69A", "AD"),
    ("ia-kids90", "90s Kids TV", _tv(1990, 1999, KIDS90), "#F4511E", "90s"),
    ("ia-sat90", "90s Saturday Mornings", _tv(1990, 1999, SAT90), "#FDD835", "SAT"),
    ("ia-air90", "90s On Air", _tv(1990, 1999, ON_AIR) + " AND NOT title:(%s)" % KIDS90, "#3949AB", "90s"),
    ("ia-music90", "90s Music TV", _tv(1990, 1999, MUSIC90), "#EC407A", "♪"),
    ("ia-ads90", "90s Commercial Breaks", _tv(1990, 1999, BREAKS) + NO_SMOKING, "#7CB342", "AD"),
    ("ia-sat80", "80s Saturday Mornings", _tv(1980, 1989, SAT80), "#FFA000", "SAT"),
    ("ia-air80", "80s On Air", _tv(1980, 1989, ON_AIR), "#5C6BC0", "80s"),
    ("ia-music80", "80s Music TV", _tv(1980, 1989, MUSIC80), "#AB47BC", "♪"),
    ("ia-ads80", "80s Commercial Breaks", _tv(1980, 1989, BREAKS) + NO_SMOKING, "#9CCC65", "AD"),
    ("ia-ads70", "70s Commercial Breaks", _tv(1970, 1979, BREAKS) + NO_SMOKING, "#D4A017", "AD"),
    ("ia-ads60", "60s Commercial Breaks", _tv(1960, 1969, BREAKS) + NO_SMOKING, "#E08A3C", "AD"),
    ("ia-ads50", "50s Commercial Breaks", _tv(1950, 1959, BREAKS) + NO_SMOKING, "#6F93B8", "AD"),
]
RETRO = {c[0] for c in CHANNELS if c[0].startswith("ia-retro") or re.search(r"\d0$", c[0])}
# whole broadcasts, their own commercials in
AIRED = {"ia-kids00", "ia-sat00", "ia-toons00", "ia-air00", "ia-music00", "ia-air10", "ia-kids10", "ia-kids90", "ia-sat90",
         "ia-air90", "ia-music90", "ia-sat80", "ia-air80", "ia-music80"}
BREAK_CHANNELS = {c[0] for c in CHANNELS if c[0].startswith("ia-ads")}
# how long a channel's items may be (seconds): whole recorded tapes run for hours, and short clips aren't programmes
LENGTHS = dict({c: (600, 4 * 3600) for c in AIRED}, **{c: (180, 3600) for c in BREAK_CHANNELS},
               **{"ia-game00": (600, 2 * 3600), "ia-info00": (600, 3600), "ia-pop10": (600, 3 * 3600)})
# Live TV's eras (and Live now, the channel lists of today, which aren't these): a tab each, in this order
ERAS = [("now", "Live now"), ("2010s", "2009–2012"), ("2000s", "2000s"), ("1990s", "90s"), ("1980s", "80s"), ("1970s", "70s"),
        ("1960s", "60s"), ("1950s", "50s"), ("cinema", "Classic Cinema")]


def era(cid):
    if cid not in RETRO:
        return "cinema"
    d = int(re.search(r"(\d)0$", cid).group(1))
    return "2010s" if d == 1 else "2000s" if d == 0 else "19%d0s" % d


# the dial: an era's channels together (the 2000s first, from 2; the 90s from 90, the 80s from 80, and so on)
FIRST = {"2000s": 2, "2010s": 11, "cinema": 20, "1950s": 50, "1960s": 60, "1970s": 70, "1980s": 80, "1990s": 90}
NUMBER = {}
for _c in CHANNELS:
    NUMBER[_c[0]] = FIRST[era(_c[0])] + sum(1 for c in NUMBER if era(c) == era(_c[0]))
ABOUT = {
    "ia-retro00": "2000s shows as they went out, with the decade's commercials between them.",
    "ia-kids00": "After-school cable off old tapes: Cartoon Network, Nickelodeon, Disney and Noggin, commercials and all.",
    "ia-sat00": "Whole Saturday mornings off the VCR: Kids' WB, Fox Box, 4Kids TV and ABC, bumpers and breaks included.",
    "ia-toons00": "Toonami and Friday-night cartoon blocks, recorded as they aired.",
    "ia-air00": "Evenings of network TV taped off the air: sitcoms, award shows and the breaks between them.",
    "ia-music00": "Music TV as it aired: TRL, 106 & Park, MTV Hits and the countdowns.",
    "ia-game00": "Video game TV: X-Play, Attack of the Show, The Screen Savers and the decade's game ads.",
    "ia-info00": "Late-night infomercials: the knives, the ovens, the music collections and a lot of enthusiasm.",
    "ia-air10": "Evenings of TV recorded off the air from 2009 to 2012: the shows, the specials and the breaks.",
    "ia-kids10": "Cartoon Network, Nickelodeon, Disney XD and PBS Kids, 2009 to 2012, as they aired.",
    "ia-pop10": "Music video countdowns, Fuse and the game shows of G4: X-Play, Attack of the Show.",
    "ia-ads10": "The commercial breaks of 2009 to 2012, back to back.",
    "ia-ads00": "Commercial breaks from the 2000s: the toys, the cereal, the promos.",
    "ia-kids90": "Fox Kids, Nickelodeon, Cartoon Network and the Disney Afternoon, commercials and all.",
    "ia-sat90": "Whole 90s Saturday mornings off the VCR: Fox Kids, Kids' WB, One Saturday Morning.",
    "ia-air90": "90s TV taped off the air: sitcoms, specials, marathons and the breaks between them.",
    "ia-music90": "MTV and VH1 in the 90s: 120 Minutes, Yo! MTV Raps, Pop-Up Video and the countdowns.",
    "ia-ads90": "Commercial breaks from the 90s, back to back.",
    "ia-sat80": "80s Saturday morning cartoons, recorded as they aired.",
    "ia-air80": "80s TV taped off the air: movies of the week, specials and the breaks.",
    "ia-music80": "MTV's first decade, Friday Night Videos and Solid Gold.",
    "ia-ads80": "Commercial breaks from the 80s, back to back.",
    "ia-ads70": "Commercials from the 70s, back to back.",
    "ia-ads60": "Commercials from the 60s, back to back.",
    "ia-ads50": "Commercials from the 50s, back to back.",
    "ia-retro90": "1990s shows as they went out, with the decade's commercials between them.",
    "ia-retro80": "1980s shows as they went out, with the decade's commercials between them.",
    "ia-retro70": "1970s shows as they went out, with the decade's commercials between them.",
    "ia-retro60": "1960s shows as they went out, with the decade's commercials between them.",
    "ia-retro50": "1950s shows as they went out, with the decade's commercials between them.",
    "ia-classics": "Feature films from the 1930s to the 70s: comedies, dramas and adventures.",
    "ia-noir": "Crime pictures from 1940 to 1965: rain, shadows and a client with a problem.",
    "ia-scifi": "Monsters, rockets and things from the swamp.",
    "ia-comedy": "Comedies from the archive's feature films.",
    "ia-westerns": "Westerns: dust, distance and a showdown at the end.",
    "ia-silent": "Silent films, with their music.",
    "ia-cartoons": "Classic cartoons, seven minutes at a time.",
    "ia-tv": "Classic TV episodes from the archive.",
    "ia-docs": "Documentaries and the films they showed in classrooms.",
}
BREAK = 3                            # commercials between two shows on Retro TV
BY_ID = {c[0]: c for c in CHANNELS}
_lock = threading.Lock()
_building = set()
_first = []                          # channels someone is waiting for (Live TV's guide open on their era): fetched next
_wake = threading.Event()
_mem = {}                            # a channel's file -> (how it was when read, its films)
_failed = {}                         # channel -> when its films last didn't load (asked for again after a while)
RETRY = 120


def on():
    return bool(config.get("archive_channels")) and not config.get("offline")


def eras_on():
    """Retro TV's decades: recordings of TV as it went out, its commercials in, that people uploaded to the same public
    library. On unless an admin turns them off (retro_eras); never for the public library's Visitors (available())."""
    return bool(config.get("retro_eras"))


def available(cid, visitor=False):
    """A channel this viewer may tune to: the decades' recordings only when they're on, and never for the public
    library's Visitors; Classic Cinema for Visitors only when it's shared (share_cinema)."""
    if cid not in BY_ID or not on():
        return False
    if cid in RETRO:
        return eras_on() and not visitor
    return not visitor or bool(config.get("share_cinema"))


def eras(visitor=False):
    """Live TV's tabs for this viewer: Live now and Classic Cinema, and the decades when they're on."""
    if not on():
        return []
    return [{"id": e, "name": n} for e, n in ERAS if e in ("now", "cinema") or (eras_on() and not visitor)]


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with net.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
# what a tape's title says about the tape, not the programme
NOISE = re.compile(r"""(?ix)
   \b(vhs|dvd|dvr|tv)\s*(recording|rip|recorded|tape|capture)s?\b
 | \bfull\s+(broadcast|programming|episode)s?\b | \bcomplete\s+(tv\s+)?(broadcast|series|episode|block)s?\b
 | \b(with|w/|w/o|without)\s+(original\s+)?commercials?\b | \bwoc\b | \bnearly\s+complete\b
 | \b(original|first)\s+(air(ing|ed)?|broadcast)\b | \bbroadcast\b | \btaped\b | \bas\s+aired\b | \bclip\b | \bhq\b | \b(avi|mp4|mkv)\b
 | \btape\s*\#?\s*\d+\b | \btape\b | \bvhs\b | \(ctv\) | \brecorded\s+on\b.*$ | \bpt\.?\s*\d+\b | \bpart\s+\d+(\s+of\s+\d+)?\b
""")

@functools.lru_cache(maxsize=8192)
def tidy(raw):
    """A tape's title -> (the programme's name, when it aired as text or None). (Kept: the guide asks for every
    programme's, every time it's drawn.)"""
    t = " " + re.sub(r"[_]+", " ", unicodedata.normalize("NFKC", raw)) + " "   # (𝐁𝐨𝐥𝐝 letters: plain ones)
    aired = None
    pats = [
        (r"\b%s\s+(\d{1,2})(st|nd|rd|th)?,?\s+((19|20)\d\d)\b" % MON, lambda m: (m.group(1)[:3], int(m.group(2)), m.group(4))),
        (r"\b((19|20)\d\d)[.\-/](\d\d)[.\-/](\d\d)\b", lambda m: (MONTHS[int(m.group(3)) - 1] if 1 <= int(m.group(3)) <= 12 else None, int(m.group(4)), m.group(1))),
        (r"\b(\d{1,2})/(\d{1,2})/((19|20)\d\d)\b", lambda m: (MONTHS[int(m.group(1)) - 1] if 1 <= int(m.group(1)) <= 12 else None, int(m.group(2)), m.group(3))),
        (r"\b%s\s+((19|20)\d\d)\b" % MON, lambda m: (m.group(1)[:3], None, m.group(2))),
        (r"\b(early|late|mid|summer|winter|spring|fall|autumn)[\s-]+((19|20)\d\d)\b", lambda m: (m.group(1).lower(), None, m.group(2))),
        (r"\b((19|20)\d\d)\s+(summer|winter|spring|fall|autumn)\b", lambda m: (m.group(3).lower(), None, m.group(1))),
        (r"\b(\d\d)-(\d\d)-(\d\d)\b", lambda m: (MONTHS[int(m.group(1)) - 1] if 1 <= int(m.group(1)) <= 12 else None, int(m.group(2)),
                                               ("20" if int(m.group(3)) < 30 else "19") + m.group(3))),
    ]
    for pat, get in pats:
        m = re.search(pat, t, re.I)
        if m:
            mon, day, year = get(m)
            mon = mon.lower() if mon else mon
            if mon in MONTHS:
                aired = "%s %s%s" % (mon.capitalize(), ("%d, " % day) if day else "", year)
            elif mon:
                aired = "%s %s" % (mon.capitalize(), year)
            else:
                aired = year
            t = t[:m.start()] + " " + t[m.end():]
            break
    t = NOISE.sub(" ", t)
    if aired:                                              # (more of the dates and times: "; Feb. 27", "6:0")
        t = re.sub(r"\b%s\s*\d{0,2}\b" % MON, " ", t, flags=re.I)
    t = re.sub(r"\b\d{1,2}:\d{0,2}\s*([ap]\.?m\.?)?(?=\W|$)", " ", t, flags=re.I)
    t = re.sub(r"\b\d{1,2}/\d{1,2}\b", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—:|;,#.")      # (tidy first: the year checks look at the ends)
    if not aired:                                          # a year in brackets or at either end: when it aired
        y = (re.search(r"\(\s*((19|20)\d\d)\b[^)]*\)", t) or re.search(r"\s[-–—]\s*((19|20)\d\d)\s*$", t)
             or re.search(r"^\s*((19|20)\d\d)\s+(?=\S+\s+\S+)", t)
             or (len(t.split()) >= 4 and re.search(r"\s((19|20)\d\d)\s*$", t)))
        if y:
            aired = y.group(1)
            inner = y.group(0)
            t = t.replace(inner, " " + (inner.replace(y.group(1), "").strip("( )") if inner.strip().startswith("(") else "") + " ")
    t = re.sub(r"\((\s|block|blocks|#|\d|/|,|\.)*\)", " ", t, flags=re.I)   # brackets left with nothing in them
    t = re.sub(r"\(\s*\)|\[\s*\]", " ", t)
    t = re.sub(r"\(([^()]*)$", r"\1", t)                  # an unclosed bracket (a cut-off title)
    t = re.sub(r"\s*[-–—:|;,#]\s*(?=[-–—:|;,#)\]]|$)", " ", t)   # separators left dangling
    t = re.sub(r"^\s*[-–—:|;,#(]+\s*", "", t)
    t = re.sub(r"\s*;\s*|\s+:\s+", " · ", t)
    t = re.sub(r"(\s*·\s*)+(?=$|\s*[-–—)])", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—:|;,#.·\"'")
    t = re.sub(r"\(\s*\)", "", t).strip()
    t = re.sub(r"\s+\.\s+", " · ", t)                     # ("Nickelodeon . Spongebob")
    t = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", t))
    t = re.sub(r"(\s+\b(from|to|on|in|of|at|and|the|between|through)\b)+\s*$", "", t, flags=re.I)   # (its dates went)
    t = t.strip(" -–—:|;,#.·")
    t = t[:1].upper() + t[1:]
    if len(t) < 3:
        t = raw.strip()
    return t, aired


def shown(f):
    """A programme as Live TV shows it: its name, and when it aired (a recorded tape) or its year (a film)."""
    if f.get("ad"):
        return {"title": "Commercials", "aired": None, "year": None}
    title, aired = tidy(f["title"])
    year = f.get("year")
    if year and re.search(r"\b%s\b" % re.escape(str(year)), title):
        year = None                                         # ("Toonami from 2001", not "Toonami from 2001 (2001)")
    return {"title": title, "aired": aired, "year": year}


def group(cid):
    """Live TV's name for the channel's group: Sofa's own lineup (where the films come from isn't on the screen)."""
    return "Retro TV" if cid in RETRO else "Classic Cinema"


def logo(cid):
    """A channel's logo: its colour, its mark and its name (an SVG, made here)."""
    _id, name, _q, colour, mark = BY_ID[cid][:5]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
           '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="#111"/></linearGradient></defs>'
           '<rect width="320" height="200" rx="18" fill="url(#g)"/>'
           '<text x="28" y="92" font-size="%d" font-weight="800" fill="#fff" font-family="sans-serif">%s</text>'
           '<text x="28" y="150" font-size="34" font-weight="700" fill="#fff" font-family="sans-serif">%s</text>'
           '<text x="28" y="182" font-size="18" fill="#fff" opacity=".7" font-family="sans-serif">%s</text></svg>'
           % (colour, 64 if len(mark) == 1 else 56, mark, name.replace("&", "&amp;"), group(cid)))
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)


def channels(visitor=False):
    """The channels this viewer may watch, for Live TV's list (Retro TV and Classic Cinema), with what's on now where
    the films are known."""
    if not on():
        return []
    out = []
    for c in sorted(CHANNELS, key=lambda c: NUMBER[c[0]]):
        if not available(c[0], visitor):
            continue
        ch = {"id": c[0], "name": c[1], "group": group(c[0]), "logo": logo(c[0]), "era": era(c[0]),
              "archive": True, "number": NUMBER[c[0]], "about": ABOUT.get(c[0], ""), "color": c[3], "aired": c[0] in AIRED}
        fl = _saved(c[0])
        if fl:
            on_now = _on(fl, time.time())
            later = next((f for f in on_now["next"] if not f.get("ad")), None)
            ch.update(now=_name(on_now["film"]) + (", then " + _name(later) if on_now["film"].get("ad") and later else ""),
                      next=_name(later) if later else None)
        out.append(ch)
    return out


def guide(at=None, hours=3, visitor=False):
    """Live TV's guide: every channel's programmes from the one on now to `hours` ahead, from the films Sofa has (it
    never waits on the archive; a channel not fetched yet has none). The commercials after a show are the show's, as
    in a TV guide."""
    at = time.time() if at is None else at
    out = []
    for ch in channels(visitor):
        fl = _saved(ch["id"]) or []
        shows = [f for f in fl if not f.get("ad")]
        out.append(dict(ch, programs=_programmes(fl, at, hours) if fl else [], tapes=len(shows),
                        hours=round(sum(f["length"] for f in shows) / 3600)))
    return out


def _programmes(fl, at, hours):
    blocks, t = [], 0
    for f in fl:
        if f.get("ad") and blocks:
            blocks[-1][1] += f["length"]
        else:
            blocks.append([t, f["length"], f])
        t += f["length"]
    total = t
    pos = (at - ANCHOR) % total
    base = at - pos                                         # when this round of the channel's films began
    i = next((k for k, b in enumerate(blocks) if b[0] <= pos < b[0] + b[1]), len(blocks) - 1)
    if blocks[i - 1][0] + blocks[i - 1][1] - (total if i == 0 else 0) + base > at - 1800 and len(blocks) > 1:
        i, base = (i - 1, base) if i else (len(blocks) - 1, base - total)       # (the half hour's start: the one before)
    out = []
    while len(out) < 48:
        start, length, f = blocks[i]
        out.append(dict(shown(f), start=int(base + start), end=int(base + start + length), id=f["id"]))
        if base + start + length >= at + hours * 3600:
            break
        i += 1
        if i == len(blocks):
            i, base = 0, base + total
    return out


def _name(f):
    s = shown(f)
    when = s["aired"] or (str(s["year"]) if s["year"] else "")
    return s["title"] + (" (%s)" % when if when else "")


def _saved(cid):
    """The channel's films as kept, without asking the archive (None: not fetched yet). Read again only when its
    file changed (Live TV's list and guide ask for every channel's)."""
    path = _path(cid)
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size, st.st_ino)
    hit = _mem.get(path)
    if hit and hit[0] == key:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            fl = json.load(f).get("films") or None
    except (OSError, ValueError):
        return None
    _mem[path] = (key, fl)
    return fl


def _fresh(cid):
    try:
        return time.time() - os.path.getmtime(_path(cid)) < KEEP and _saved(cid) is not None
    except OSError:
        return False


def seconds(length):
    """'1:17:26', '95 min', '123.4' -> seconds (None when it can't be read)."""
    s = str(length or "").strip().lower()
    m = re.match(r"^(\d+)\s*min", s)
    if m:
        return int(m.group(1)) * 60
    if re.match(r"^[\d:.]+$", s):
        parts = [float(p) for p in s.split(":") if p]
        total = 0.0
        for p in parts:
            total = total * 60 + p
        return int(total) if total else None
    return None


def _text(v):
    """A metadata field as text: the archive gives some (a title, the subjects) as a list."""
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return str(v or "")


def _film(identifier, shortest=120, longest=None, english=False):
    """One item's film: its one playable video file (an MP4, the smaller copy where there are two), and its length."""
    d = _get("https://archive.org/metadata/%s" % urllib.parse.quote(identifier))
    meta, files = d.get("metadata") or {}, d.get("files") or []
    lang = _text(meta.get("language")).lower()
    if english and (lang and not re.search(r"\b(en|eng|english)\b", lang)
                    or re.search(r"[\u3040-\u30ff\u4e00-\u9fff\u0400-\u04ff\u0900-\u097f]", _text(meta.get("title")))):
        return None
    title = meta.get("title")
    title = title[0] if isinstance(title, list) and title else title
    title = title.strip() if isinstance(title, str) and title.strip() else identifier
    if NOT_WORDS.search(_text(meta.get("title"))) or NOT_WORDS.search(_text(meta.get("subject"))):
        return None
    vids = [f for f in files if f.get("name", "").lower().endswith(".mp4") and seconds(f.get("length"))]
    originals = {f.get("original") for f in vids if f.get("original")}
    sources = [f for f in vids if f.get("source") == "original"] or vids
    if len({f["name"] for f in sources} - originals) > 2:      # a bundle of many videos, not one film
        return None
    if not vids:
        return None
    best = sorted(vids, key=lambda f: (int(f.get("height") or 480) > 720, -int(f.get("size") or 0) if int(f.get("height") or 480) <= 720 else int(f.get("size") or 0)))[0]
    length = seconds(best.get("length"))
    if not length or length < shortest or (longest and length > longest):
        return None
    year = re.match(r"\d{4}", str(meta.get("year") or meta.get("date") or ""))
    return {"id": identifier, "title": re.sub(r"\s+", " ", title).strip()[:120], "year": int(year.group(0)) if year else None,
            "url": "https://archive.org/download/%s/%s" % (urllib.parse.quote(identifier), urllib.parse.quote(best["name"])),
            "length": length}


def _search(q, rows):
    url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
        [("q", q + NOT), ("fl[]", "identifier"), ("fl[]", "title"), ("rows", str(rows)), ("sort[]", "downloads desc"), ("output", "json")])
    return [d for d in _get(url).get("response", {}).get("docs", []) if not NOT_WORDS.search(_text(d.get("title")))]


def _varied(docs, most=3):
    """No more than `most` of one series (titles alike but for their dates and numbers: "X-Play 2008.11.26"), so a
    channel has variety, not twenty parts of one upload."""
    seen, out = {}, []
    for d in docs:
        key = " ".join(re.sub(r"[^a-z ]+", " ", _text(d.get("title")).lower()).split()[:3])
        if seen.get(key, 0) < most:
            seen[key] = seen.get(key, 0) + 1
            out.append(d)
    return out


def _pick(docs, want, shortest=120, longest=None, english=False):
    out = []
    with ThreadPoolExecutor(6) as pool:
        for f in pool.map(lambda d: _safe_film(d["identifier"], shortest, longest, english), docs):
            if f and len(out) < want:
                out.append(f)
    return out


def _build(cid):
    c, english = BY_ID[cid], cid in RETRO
    if len(c) < 6:                                        # (recorded tapes: long, and their own ads in them)
        shortest, longest = LENGTHS.get(cid, (120, None))
        return _pick(_varied(_search(c[2], FILMS * 4)), FILMS, shortest=shortest, longest=longest, english=english)
    shows = _pick(_varied(_search(c[2], 80)), 20, shortest=300, longest=5400, english=english)   # shows, and the decade's ads
    ads = [dict(a, ad=True) for a in _pick(_search(c[5], 120), 40, shortest=10, longest=300, english=english)]
    if not ads:
        return shows
    out = []
    for n, show in enumerate(shows):
        out.append(show)
        out += [ads[(n * BREAK + k) % len(ads)] for k in range(BREAK)]
    return out


def _safe_film(identifier, shortest=120, longest=None, english=False):
    try:
        return _film(identifier, shortest, longest, english)
    except (OSError, ValueError, KeyError):
        return None


def _path(cid):
    """(Named for the channel's search too: a changed search fetches its films again, without waiting a week.)"""
    c = BY_ID[cid]
    return os.path.join(CACHE, "%s-%s.json" % (cid, hashlib.sha1((c[2] + (c[5] if len(c) > 5 else "")).encode()).hexdigest()[:8]))


def films(cid, wait=True):
    """The channel's films, from the cache, or fetched now (a few seconds) when there are none or they're old."""
    if cid not in BY_ID:
        raise KeyError(cid)
    try:
        with open(_path(cid), encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = None
    if saved and saved.get("films") and time.time() - saved.get("at", 0) < KEEP:
        return saved["films"]
    with _lock:
        if cid in _building:
            return (saved or {}).get("films") or []
        _building.add(cid)
    try:
        fresh = _build(cid) if (wait or not saved) else None
    except (OSError, ValueError) as exc:
        if saved and saved.get("films"):
            return saved["films"]                           # (the archive not answering: last week's list)
        raise OSError("Its programmes didn't load just now (%s)." % exc)
    finally:
        with _lock:
            _building.discard(cid)
    if fresh:
        os.makedirs(CACHE, exist_ok=True)
        tmp = _path(cid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"at": int(time.time()), "films": fresh}, f)
        os.replace(tmp, _path(cid))
        return fresh
    return (saved or {}).get("films") or []


def want(cids):
    """Live TV's guide is open on these channels: the ones not fetched yet are fetched next, one after the other,
    without the warm-up's pauses. (On a new box the era in view is ready in a minute, instead of its turn coming
    in the ten minutes the whole warm-up takes.)"""
    soon = time.time() - RETRY
    new = [c for c in cids if available(c) and _saved(c) is None and _failed.get(c, 0) < soon]
    if not new or not on():
        return
    with _lock:
        for c in new:
            if c not in _first and c not in _building:
                _first.append(c)
    _wake.set()


def _wanted():
    with _lock:
        return _first.pop(0) if _first else None


def _warm():
    """Every channel's films, ready before anyone tunes in (a few seconds each, a channel at a time, with a pause
    between), then kept fresh. A channel someone is waiting for goes first (want())."""
    _wake.wait(120)                                         # (Sofa reads its library first, unless Live TV is opened)
    _wake.clear()
    todo, next_round = [], 0.0
    while True:
        cid = _wanted()
        waited_for = cid is not None
        if cid is None:
            if not todo and time.time() >= next_round:
                todo, next_round = sorted((c for c in BY_ID if available(c)), key=NUMBER.get), time.time() + 6 * 3600   # (the dial's order)
            while todo and cid is None:
                c = todo.pop(0)
                cid = None if _fresh(c) else c              # (fetched already, for someone waiting: no pause for it)
        if cid is None:
            _wake.wait(max(1.0, next_round - time.time()) if not todo else 1.0)
            _wake.clear()
            continue
        _warm_one(cid)
        if not waited_for:
            _wake.wait(10)                                  # (the pause between channels, cut short when someone waits)
            _wake.clear()


def _warm_one(cid):
    """One channel; one that fails (the archive down, an odd item) waits for the next round, the rest go on."""
    if not available(cid):
        return
    try:
        films(cid)
        _failed.pop(cid, None)
    except (OSError, ValueError):
        _failed[cid] = time.time()
    except Exception as e:                               # (never the end of the others: it used to stop them all)
        _failed[cid] = time.time()
        print("Archive channel %s: %s: %s" % (cid, type(e).__name__, e), file=sys.stderr, flush=True)


def _warm_once(pause=0):
    """Each channel in turn, now."""
    for cid in BY_ID:
        _warm_one(cid)
        time.sleep(pause)


def start():
    threading.Thread(target=_warm, daemon=True, name="archive-channels").start()


def now(cid, at=None, ahead=6):
    """What's on: the film, where in it (seconds), and the ones after it, on the channel's clock."""
    fl = films(cid)
    if not fl:
        raise OSError("This channel has nothing to show just now.")
    r = _on(fl, at if at is not None else time.time(), ahead)
    tidy_up = lambda f: f if f.get("ad") else dict(f, **{k: v for k, v in shown(f).items() if k != "year"})
    r.update(film=tidy_up(r["film"]), next=[tidy_up(f) for f in r["next"]])  # (the player shows the programme's own name)
    return dict(r, channel=cid, name=BY_ID[cid][1], number=NUMBER[cid], era=era(cid))


def _on(fl, at, ahead=6):
    total = sum(f["length"] for f in fl)
    pos = (at - ANCHOR) % total
    i = 0
    while pos >= fl[i]["length"]:
        pos -= fl[i]["length"]
        i += 1
    order = [fl[(i + k) % len(fl)] for k in range(min(ahead, len(fl)))]
    return {"film": order[0], "offset": int(pos), "left": int(order[0]["length"] - pos), "next": order[1:]}

