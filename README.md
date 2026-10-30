# Sofa

A small, self-hosted home media server. Drop shows, movies and music into a folder;
Sofa names them, files them, finds artwork and plays them on every screen in the house:
browsers, phones, smart TVs, Roku and Fire TV. Free live TV channels too.

A project by [EdgeVenture.uk](https://edgeventure.uk).

Sofa is plain Python (standard library only) plus ffmpeg. It runs happily on a Mac mini,
and still runs on a 2011 iMac (it notices an older computer and goes easy on it).

**Yours, at home.** Everything Sofa needs comes with it: the app, its fonts and its player run
from the Sofa computer, so every device at home can watch with the internet down. The internet
is only used for optional extras (looking up artwork, updates, saving from links, live TV), and
**Work offline** switches even that off. **Keep no logs** and **Wipe all logs** leave nothing
behind. [docs/privacy.md](docs/privacy.md)

---

## Install (5 minutes)

You need a Mac or Linux computer that stays on. Open **Terminal** and paste this line:

```sh
curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/tools/get-sofa.sh | sh
```

That's it. It puts Sofa in `~/Sofa`, installs ffmpeg if Homebrew is there, and starts
Sofa in the background (it starts again by itself after a restart).

Then, on any phone, laptop or TV browser at home, open:

```
http://<this computer's name or address>:8090
```

The first person to open it creates the admin account. Done.

<details><summary>Prefer to do it by hand?</summary>

```sh
git clone https://github.com/krintoxi/sofa.git ~/Sofa
cd ~/Sofa
./deploy/install.sh          # macOS: a LaunchAgent; Linux: a systemd user service
brew install ffmpeg          # macOS (on Linux: sudo apt install ffmpeg)
```

Or run it in a Terminal window instead of in the background: `python3 sofa.py serve`.
More detail, and what to do if something goes wrong: [docs/install.md](docs/install.md).
</details>

## Update

**Easiest:** open Sofa, go to **Server → Updates**, and press **Update now**.

**Older copy of Sofa without that button?** Paste this in Terminal on the Sofa computer:

```sh
curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/tools/update.sh | sh
```

Either way, **only Sofa's own program files change**. Your shows, movies, music, accounts,
watch history and settings are left exactly as they are, and a copy of the old version is
saved first so you can always go back. Details: [docs/updating.md](docs/updating.md).

---

## Using it

### Adding things to watch

Drop files or whole folders into **`~/Entertainment/Inbox`**, or send them from any phone or
laptop at home with **Send files from this device** (Server → Overview, admins). Sofa waits until
the copy finishes, works out what each file is, renames it and files it:

| You drop | Sofa files it as |
|---|---|
| `the.sopranos.s01e01.1080p.mkv` | `Shows/The Sopranos/Season 1/The Sopranos S01E01 The Sopranos.mkv` |
| a folder `The Sopranos Complete Series` with `Season 1/101 Pilot.avi` | the same tidy layout |
| `Heat.1995.1080p.BluRay.mkv` | `Movies/Heat (1995)/Heat (1995).mkv` |
| a folder `Star Wars Collection` with several movies | `Movies/Star Wars Collection/<each movie in its own folder>` |
| anything in **`Inbox/XXX`** | the **Adult** section; folders like `Hentai` or `Series` keep their shape (see below) |
| songs | `Music/<Artist>/<Album>/` |

It copes with the usual mess: anime names (`[Group] Show - 05`), `Show.205.hdtv`, daily shows
by date, phone and camera videos (filed in **Movies/Home Videos**), movies with no year,
subtitles and posters that came along (attached to the right video), and samples and
`.txt`/`.nfo`-style junk (set aside in Deleted, never thrown away). Only things with no
usable name at all go to **`Needs Review`**, with a note on the Server page. Nothing is ever
deleted. More: [docs/folder-structure.md](docs/folder-structure.md).

### Things that just work

- **Any file plays.** MP4 plays as it is. MKV, AVI, HEVC and 10-bit files are adapted for
  each device as they play, and Sofa also **converts them to MP4 in the background** so they
  play instantly next time. The originals are kept until you say otherwise.
  [docs/playback.md](docs/playback.md)
- **Hover previews.** Point at anything and a bigger card plays a few seconds of it, with Play
  and More info. On a TV, the card you're on plays in place.
- **Trailers.** Open a show or movie (More info) and, after a moment, three minutes of it from
  somewhere in the middle play behind the title. Sound off until you turn it on; off per device
  under Theme.
- **A proper player.** Skip Intro / Skip Recap / Skip Credits, "Next episode" when the
  credits start, previews while you scrub, an episode list, sound-track and subtitle
  choice, **Night mode** (loud scenes quieter, voices clearer), picture quality for converted
  video, a sleep timer, picture-in-picture, speed, keyboard shortcuts (press `?`), and
  double-tap to skip on phones.
- **Take it with you.** **Download** on a movie or an episode saves it to your phone or laptop for a
  trip. A file the device plays as it is downloads as it is; anything else (MKV, AVI, ...) gets a
  **travel copy** first (720p MP4 with its subtitles, about 1 GB an hour), made on the Sofa computer
  in the background. Copies are deleted after two weeks.
- **Sofa as an app.** On an iPhone or iPad: Safari → Share → **Add to Home Screen**, and Sofa opens
  full screen with its own icon. On Android and computers: the browser's menu → Add to Home screen /
  Install (Theme → This device says how on each).
- **Your phone is the remote.** With Sofa open on the TV, press the screen button at the top of
  Sofa on your phone, pick the TV, and Play sends things there; a bar on the phone pauses,
  skips, scrubs, goes to the next episode and stops. Works for any of your screens, at home,
  through the Sofa computer only. [docs/tv.md](docs/tv.md)
- **Artwork and details.** Shows from TVmaze; movies from the iTunes Store and Wikipedia
  (or TMDB, with a free key, for the best posters and collections); `.nfo` files next to your
  videos are read too. Episodes without a picture get a well-chosen still from the video, and a
  title no service knows gets a cover made from one (the whole frame, with its name), not a
  narrow slice of a wide picture.
  Wrong match, or none? Click **Find details** on the show or movie and pick the right one.
- **Surprise me** on Movies and Shows picks something you haven't watched (from the genre or filter
  you're on), and Home has **Something short** and **Movies you haven't seen** rows that change daily.
- **Genres and filters.** Movies and Shows can be browsed by genre (Comedy, Animation, Anime,
  Science Fiction, ...), narrowed by a filter box (name, genre, network, year) and by what you've
  watched. A genre page also lists titles with its name in the title (Adventure Time under
  Adventure). Home has a row for your biggest genres.
- **Save from a link.** Paste the address of a video page (YouTube, Vimeo and well over a
  thousand other sites); Sofa downloads it with the free yt-dlp tool and files it.
  Server → Downloads.
- **Tidy folders.** Download-style names ("Heat.1995.1080p.BluRay") are tidied, collections
  get a folder per movie, and stray "XXX" folders move into the Adult section.
- **More room on other drives.** Plug in a flash drive or an external SSD and press **Use this
  drive** (Server → Storage): its shows and movies join the one library, new things can go there,
  and **Manage → Move it to another drive** makes room on the computer. [docs/storage.md](docs/storage.md)
- **Fix things from the app (admins).** **Manage** on any movie, show or episode: move it
  (it's really a movie, an episode, adult, ...), delete it (to a Deleted folder you empty
  when you're sure), or take new pictures from the video.
- **Who's watching?** Everyone has their own profile, with their own "continue watching" and
  My List. The TV asks who's watching when Sofa opens; profiles that can see Adult or run the
  server are locked with a 4-digit PIN. Guests on your Wi-Fi scan a QR code on the Server page.
- **Kids profiles.** Switch **Kids** on for a profile (Server → People): it sees only family
  titles (rated for children, or Kids and Family genres), never Adult, Live TV or the Server
  page, and leaving it takes the other profile's PIN. **For kids** on any show or movie page
  allows or blocks that title.
- **Suggestions.** "More like this" on every show and movie, and "Because you watched …" rows on
  Home, worked out at home from genres, collections, networks and years (nothing is sent anywhere).
- **Light on old hardware.** The web app downloads the library compressed (a 7,500-file library is
  about 100 KB), long pages draw as you scroll, TV sticks get lighter motion, and Sofa's background
  work (converting, previews, Skip Intro) waits while the computer is busy.
- **My List**, **search as you type** (with pictures; arrow keys and the remote work in it), and
  a **banner on Home that plays** a few seconds of the featured title (off per device under Theme).
- **Home keeps up.** **New episodes** of shows you watch get their own row (and a "New" on the
  show), **Coming up** shows when the next one airs, and anything can be taken out of **Continue
  watching** (✕ on its card, or on its page) until you watch it again.
- **Episode guide.** A show's page lists the episodes that have aired but aren't in your library,
  whole seasons you don't have, and the next episode to air (from the episode list TVmaze already
  gave; shows still on the air are looked at again every few days).
- **Subtitles your way.** Out of sync? **Options → Subtitle timing** moves them half a second at a
  time. On a dark box or outlined, four sizes. **Hide spoilers** (under Theme) blurs pictures and
  descriptions of episodes you haven't watched.
- **Made for old Macs too.** Sofa times this computer's video conversion and uses the faster way
  that works properly (on some older Macs Apple's hardware converter draws lines across the
  picture; Sofa checks, and never uses it there). On a slow computer, **Gentle mode** keeps video
  converted while you watch at 720p and saves heavy background work for the quiet hours (1-7 am).
  Server → Overview → This computer.
- **Themes.** Press **Theme** at the top: Midnight, Cinema, Ocean, Forest, Grape or Pure black,
  plus subtitle size and TV mode. Each device keeps its own.
- **TVs.** On Fire TV, open Sofa in the **Silk** browser: it switches to TV mode (the whole menu
  fits, with Search and your profile at the end), and the remote works like Netflix (OK on Skip
  Intro skips, ◀ ▶ seek with a preview, Back closes panels first). Roku Media Player, VLC and most
  smart TVs also find Sofa by themselves.
  [docs/tv.md](docs/tv.md)
- **Music**, with albums, artists, stations, likes and a queue. **Live TV** from free channel lists.

### The Adult section

**First, switch it on for yourself:** **Server → People → Adult**. It's off for everyone at
first, admins included; guests and TVs never see it.

- **Its own front page**: a featured strip and a row per category (Movies, Hentai, Shows, ...),
  plus new arrivals, favorites, studios and performers.
- **Your folders are the categories.** Every folder in `~/Entertainment/Adult` (Movies,
  Hentai, Shows, Collections, anything you make) gets its own button and row in the Adult tab.
  Series and collections inside them are recognised.
- **Browse** by category, studio, performer and tag, keep favorites (♥), search, shuffle,
  and get moving previews on hover or remote focus. All of it works offline, from file
  names, `.nfo` files and saved links. A free ThePornDB token adds real covers.
- **Add** by dropping files or whole folders into `Inbox/XXX`, or with **+ Add a link**.
- **Pictures from the middle** of each video, in wide cards, unless the video came with its own.
- **Private:** addresses don't contain titles, and the Server page never names adult titles.

Adult live TV: the free iptv-org lists dropped adult channels in January 2024, so add an M3U
link you trust and tick **Adult channels**. [docs/adult.md](docs/adult.md)

### The Server page (admins)

| Tab | What's there |
|---|---|
| Overview | addresses to watch from, who's watching, the Inbox, anything that needs you, this computer (speed, Gentle mode, quiet hours) |
| Storage | where the library is (this computer and drives), where new things go, drives to add, moves between drives |
| Library | folders, rescan, **missing details** (fix them in a click), **duplicates** (keep the best copy), new pictures, free up space, the Deleted folder, Skip Intro progress, Needs Review |
| Converting | the convert-to-MP4 queue with progress; automatic converting on/off |
| Downloads | save videos from links; install yt-dlp; use a browser's sign-in; the "Send to Sofa" bookmark |
| Live TV | channel lists |
| People | accounts, Adult access, Kids profiles, guests |
| Settings | **privacy** (keep no logs, wipe all logs, work offline), name, theme, TV sharing, TMDB key, ThePornDB token, backups |
| Updates | version, **Update now** |
| Activity | everything Sofa did, filterable |

---

## Something not right?

**Server → Activity → Download a report** gives you one text file with what's needed to see
what's going on: version, tools, settings (no passwords, PINs or keys), folders, what's in the
Inbox and Needs Review and why, the activity log and the server log. Adult file names are only in
it if you tick the box. Send it to whoever helps you; you can give it straight to Claude.

## Watching away from home

Sofa only answers your home network and Tailscale by default. Read
[docs/remote-access.md](docs/remote-access.md) before changing that.

## Settings file

`~/Sofa/data/config.json` (made on first run). Almost everything is on the Server page;
see `sofa/config.py` for every option.

## Command line

`python3 sofa.py serve | scan | inbox | status | backup | restore FILE | adduser NAME [--admin] | passwd NAME`

## Tools

- `tools/get-sofa.sh` installs Sofa. `tools/update.sh` updates it.
- `tools/convert.py` converts files to MP4 by hand, even on another computer over SSH
  (Sofa's own background converter usually makes this unnecessary).

## Tests

`python3 -m unittest discover -s tests -t .` from the Sofa folder (standard library only; it uses a
throwaway library and data folder, never yours, and no internet). GitHub runs them on every push.

## Layout of this repository

```
sofa.py              command line entry point
sofa/                server: library, inbox, streaming, converter, intro finder, DLNA, live TV, accounts, updater
client/              web app (no build step)
deploy/              install script, macOS LaunchAgent, Linux systemd unit
tools/               get-sofa.sh, update.sh, convert.py
docs/                install, updating, folders, storage (drives), playback, TV, adult, privacy, remote access, api (for apps)
tests/               the tests
```

## License

MIT. Bundled in `client/vendor`: hls.js (Apache-2.0), qrcode-generator (MIT), and the Bricolage
Grotesque and Instrument Sans fonts (SIL Open Font License 1.1, licenses next to them).
