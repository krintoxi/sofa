# Folder structure

Sofa reads `Shows/`, `Movies/`, `Music/` and `Music Videos/`, and watches `Inbox/`.
The paths are set in `data/config.json` (`shows`, `movies`, `music`, `musicvideos`,
`inbox`, `review`).

## The easy way: the Inbox

Drop files or whole folders into `Inbox/`. Sofa leaves them alone until the copy has
stopped changing for 30 seconds (and while any `.part`/`.crdownload` file remains), then:

| It sees | It does |
|---|---|
| `Show.Name.S02E05...` or `Show Name 2x05` | `Shows/Show Name/Season 2/Show Name S02E05 <Title>.ext` |
| a folder `Show Name/Season 2/03 - Title.mkv` | the same, using the folder names |
| `Movie.Title.1999.1080p...` or `Movie Title (1999)` | `Movies/Movie Title (1999)/Movie Title (1999).ext` |
| a song (`.mp3`, `.m4a`, `.flac`, `.wav`, ...) | `Music/<Artist>/<Album>/<NN Title>.ext` from its tags, or from a name like `Artist - Title.mp3` |
| anything inside `Inbox/Music Videos/` named `Artist - Title.mp4` (or in an artist folder there) | `Music Videos/<Artist>/<Title>.mp4`; "(Official Video)" and similar are dropped |
| `.srt`/`.vtt` subtitles and `.jpg` thumbnails with the same name | moved along with the video |
| samples, leftovers (`.nfo`, `.txt`) | `Needs Review/Inbox leftovers/` |
| anything it can't identify | `Needs Review/From Inbox/`, with a note on the Server page |
| an exact duplicate of something already filed | `Needs Review/Duplicates/` |

Show names are checked against shows you already have (so `ncis` joins `NCIS`) and
against TVmaze, which also supplies episode titles.

## Doing it by hand

```
Shows/
  Show Name/
    folder.jpg          poster      (downloaded from TVmaze if missing)
    backdrop.jpg        background  (downloaded if missing)
    logo.png            title logo  (optional)
    Season 1/
      folder.jpg        season poster (optional)
      Show Name S01E01 Pilot.mkv
      Show Name S01E01 Pilot.en.srt     subtitles (optional)
      metadata/Show Name S01E01 Pilot.jpg   episode thumbnail (downloaded if missing)
    Specials/           season 0
    Extras/             anything else: featurettes, bloopers
Movies/
  Movie Title (1999)/
    Movie Title (1999).mp4
    folder.jpg  backdrop.jpg  logo.png
  Collection Name/      a folder of movie folders becomes a collection
    Movie One (1980)/...
```

```
Music/
  Artist/
    Album/
      folder.jpg        album cover (otherwise the songs' embedded art is used)
      01 Title.mp3
    Title.mp3           a single
  sofa-tags.json        optional: {"Artist/Album/01 Title.mp3": {"genre": "...", "mood": "..."}}
Music Videos/
  Artist/
    Title.mp4
    Title.jpg           thumbnail (optional; otherwise a frame from the video)
```

For music the folders win: `Music/<Artist>/<Album>/` decides the artist and album even when
the files' tags say otherwise. Genre and mood (from tags or `sofa-tags.json`) become stations.

Every folder directly in `Shows/` is a show, named after the folder. Episode numbers
come from `S01E02`, `1x02`, or a leading number inside a `Season N` folder.

Watch progress is tied to what an item is (show, season, episode), not its file name,
so renaming or converting a file keeps everyone's progress.
