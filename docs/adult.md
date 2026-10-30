# The Adult section

## Seeing it

**Server → People**, then the **Adult** switch next to each person. It's off for everyone to
begin with, **admins included**, so the first time, switch it on for yourself. (If there's
adult content you can't see, the Server page's Overview says so and has a button for it.)

It's never shown to:

- people with the switch off,
- guests (the QR-code sign-in),
- TVs browsing Sofa without signing in (Roku Media Player, VLC, smart TVs).

Adult videos also stay out of Home, "Continue watching" and search for everyone. The Adult
tab has its own "Continue watching" and its own search box.

## Your own folders are the categories

Every folder at the top of `~/Entertainment/Adult` is a category, with its own button in the
Adult tab. Use whatever names you like:

```
Adult/
  Movies/
    Night Shift (2018)/Night Shift (2018).mp4        a movie in its own folder
    Brazzers.21.03.14.Jane.Doe.Hot.Title.XXX.mp4     or loose
  Hentai/
    Some Series/Episode 01.mp4, Episode 02.mp4       a series (Sofa spots episodes)
    A Movie (2010)/A Movie (2010).mp4
  Series/
    Series Name/Season 1/Series Name S01E01.mp4
  Collections/
    Summer Pack/Scene One.mp4, Scene Two.mp4         a collection
  Amateur/  VR/  Erotic/  ...                        anything else you make
```

Inside any category Sofa recognises single movies, loose videos, **series** (Season folders,
or several files named like episodes: `S01E01`, `1x01`, `Episode 1`) and **collections** (a
folder of several videos).

## Adding things

- **Drop them into `~/Entertainment/Inbox/XXX`.**
  - A single video becomes `Adult/Movies/<Title>/`.
  - A folder named like a category (`Hentai`, `Series`, `Collections`, `Amateur`, `VR`, …)
    moves into `Adult/` **with everything inside it kept as it is**.
  - A folder of several scenes becomes a collection under `Adult/Movies/`.
- **Save from a link.** In the Adult tab (admins), **+ Add a link**: paste the address of a
  video page and Sofa downloads it into the Adult section. See below.
- **Already have an `XXX`, `Adult` or `Porn` folder** in `Movies`, `Shows` or
  `~/Entertainment`? Sofa moves its contents into `Adult/`, keeping its folders as categories.

## Save from a link

The **Server → Downloads** tab, or **+ Add a link** in the Adult tab. The first time, press
**Install yt-dlp**. It's the free, open-source downloader that knows YouTube, Vimeo and well
over a thousand other sites, including the free adult video sites. Sofa keeps it up to date.

- Tick **Put it in the Adult section** for adult videos. Normal videos are filed under Movies.
- Tick **It's a playlist** to save a whole playlist (up to 50 videos).
- Sofa also saves the page's title, date, channel, cast and tags with the video, so it arrives
  with its details already filled in.
- **Send to Sofa from your browser:** drag the "Send to Sofa" button from the Downloads tab to
  your bookmarks bar. On any video page, click it and the box opens with the link filled in.

Only save videos you're allowed to keep.

## Browsing

| | |
|---|---|
| **Categories** | one button per folder (Movies, Hentai, Series, ...) |
| **Studios** | from file names like `Studio.21.03.14.Performer.Name.Title`, `.nfo` files, saved links, ThePornDB |
| **Performers** | same sources; names joined with "And" in file names are recognised too |
| **Tags** | from saved links, `.nfo` files and ThePornDB |
| **Favorites** | press ♥ on a video or a performer |
| **Shuffle / Play all** | on every list: plays one after another |

Pointing at a card (or picking it with the TV remote) plays a short moving preview.

All of that works without any account or key. For real covers and descriptions, add a free
**ThePornDB** token under **Server → Settings**. Wrong or missing details: open the video and
press **Find details**.

## Privacy

- **Blurred artwork.** Adult pictures stay blurred until you point at them or pick them with
  the remote. Switch it off per device under **Theme** at the top.
- **Nothing readable in history.** Adult pages have addresses like `#/movie/am:h19ed4feb57ac`,
  with no titles, so browser history and bookmarks don't give anything away.
- **The Server page doesn't name titles.**
  - Activity says "Added 1 video to Adult".
  - "Watching now" says "something private".
  - Converting and Downloads show "Private video".
  - Files that need a look go to `Needs Review/XXX`.
  - Entries from older versions of Sofa are rewritten the same way when Sofa starts.

## Adult live TV

The free iptv-org channel lists stopped carrying adult channels in January 2024, and there's
no other free, legitimate list Sofa can suggest. If you have an M3U link from a service you
trust, add it under **Server → Live TV** and tick **Adult channels**.
