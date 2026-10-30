# Folder structure

Sofa reads `Shows/`, `Movies/`, `Music/`, `Music Videos/` and `Adult/`, and watches `Inbox/`.
The paths are set in `data/config.json` (`shows`, `movies`, `music`, `musicvideos`,
`adult`, `inbox`, `review`, `originals`).

## The easy way: the Inbox

Drop files or whole folders into `Inbox/`. Sofa leaves them alone until the copy has
stopped changing for 30 seconds (and while any `.part`/`.crdownload` file remains), then:

| It sees | It does |
|---|---|
| `Show.Name.S02E05...` or `Show Name 2x05` | `Shows/Show Name/Season 2/Show Name S02E05 <Title>.ext` |
| a folder `Show Name/Season 2/03 - Title.mkv` | the same, using the folder names |
| `Show Name 101 Title.avi` inside a show folder (`101` = season 1, episode 1) | the same tidy name |
| `[Group] Show Name - 05 [1080p].mkv` (anime), `Show.Name.205.HDTV`, `Show Name Ep 3` | `Shows/Show Name/Season 1/...` (or the season in the name) |
| a daily show by date: `The.Daily.Show.2024.03.15...` | `Shows/The Daily Show/Season 2024/...` |
| a phone or camera video: `VID_20230512_143000.mp4`, `IMG_1234.MOV`, `PXL_...`, `GOPR0042.MP4` | `Movies/Home Videos/Video 2023-05-12 14.30/...` (the date and time when the name has them) |
| `Movie.Title.1999.1080p...` or `Movie Title (1999)` | `Movies/Movie Title (1999)/Movie Title (1999).ext` |
| a movie with no year in its name | its year is looked up (iTunes Store, Wikipedia or TMDB); if nobody knows it, it's filed under its own name |
| a folder of several different movies (`Star Wars Collection`, `The Lord of the Rings Trilogy`) | `Movies/Star Wars Collection/<Title (Year)>/...`, one folder per movie |
| `Movie CD1.avi` and `Movie CD2.avi` | kept together as one movie |
| anything inside `Inbox/XXX/` | `Adult/Movies/<Title (Year)>/...`, or `Adult/Shows/<Show>/Season N/...` when named like an episode |
| a song (`.mp3`, `.m4a`, `.flac`, `.wav`, ...) | `Music/<Artist>/<Album>/<NN Title>.ext` from its tags, or from a name like `Artist - Title.mp3` |
| anything inside `Inbox/Music Videos/` named `Artist - Title.mp4` (or in an artist folder there) | `Music Videos/<Artist>/<Title>.mp4`; "(Official Video)" and similar are dropped |
| `.srt`/`.vtt` subtitles and `.jpg` thumbnails with the same name | moved along with the video |
| subtitles in a `Subs` folder or named `English.srt`, `2_English.srt` | attached to the video as `<video>.en.srt` (one per language) |
| `poster.jpg`, `cover.jpg`, `folder.jpg` / `fanart.jpg`, `backdrop.jpg` | become the title's cover / background |
| samples, `.txt`, `.nfo`, `.url`, `.exe` and other download leftovers | set aside in `Deleted/Inbox/` (never thrown away; empty it from the Server page) |
| anything else left over | `Needs Review/Inbox leftovers/` |
| anything with no usable name at all | `Needs Review/From Inbox/`, with a note on the Server page |
| an exact duplicate of something already filed | `Needs Review/Duplicates/` |

Show names are checked against shows you already have (so `ncis` joins `NCIS`) and
against TVmaze, which also supplies episode titles. A show TVmaze doesn't know (or with the
internet off) is still filed, under its tidied name.

## Tidying what's already there

Put things straight into `Shows/` or `Movies/` with download-style names? With **Tidy
folders automatically** on (Server → Library; on by default), Sofa straightens them every
ten minutes:

| Before | After |
|---|---|
| `Shows/The.Sopranos.1999.S01-S06.1080p.BluRay.x265-HOSTILE/` | `Shows/The Sopranos (1999)/` |
| `Movies/Heat.1995.1080p.BluRay/` | `Movies/Heat (1995)/` |
| `Movies/Star Wars Collection/` with loose `.mkv` files in it | each movie in its own `Title (Year)` folder inside it |
| a folder named `XXX`, `Adult` or `Porn` in `Shows/`, `Movies/` or `~/Entertainment` | moved into the Adult section |

Nothing is deleted, and everyone's watch progress stays put. Episode files themselves keep
their names; Sofa reads `S01E01`, `1x01`, `101`, `Episode 1` and `Season 1 Episode 1`.

## Fixing one thing from the app

Something in the wrong place? Admins open it and press **Manage** (on a movie or show page,
or the **⋯** next to an episode):

- **Move it somewhere else**: say what it really is (a movie with its title and year, an
  episode of a show, an Adult category, or Needs Review). Sofa renames it and files it there,
  with its subtitles and saved details.
- **Delete it**: it goes to the **Deleted** folder, next to your Shows and Movies folders
  (normally `~/Entertainment/Deleted`), in the same folders it came from. It's gone for good
  only when you press **Empty it for good** under **Server → Library** (or empty the folder
  yourself). To get something back, move it from there into the Inbox.
- **Take new pictures from the video**: for pictures Sofa took itself that show the wrong
  moment. Covers from TVmaze, TMDB, ThePornDB or ones you added are never replaced.
  **Server → Library → Take new pictures for everything** does the whole library.

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
Adult/                  only for people allowed to see it (Server → People)
  Movies/               every folder here is a category: Movies, Hentai, Series, Collections, ...
    Title (2019)/Title (2019).mp4
  Hentai/
    Some Series/Episode 01.mp4
  Series/
    Series/Season 1/Series S01E01.mp4
```

See [adult.md](adult.md) for how categories, series and collections are recognised.

Wrong details or artwork? Open the show or movie and press **Find details**. Your choice is
kept in `data/overrides.json`, and any `folder.jpg` you put in a folder yourself always wins.

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

Every folder directly in `Shows/` is a show, named after the folder (download junk like
"1080p BluRay x265" and "Complete Series" is ignored). Episode numbers come from `S01E02`,
`1x02`, `102`, or a leading number inside a `Season N` folder.

Watch progress is tied to what an item is (show, season, episode), not its file name,
so renaming or converting a file keeps everyone's progress.
