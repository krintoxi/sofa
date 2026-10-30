# Sofa

A small, self-hosted home media server. Drop shows, movies and music into a folder;
Sofa names them, files them, finds artwork and plays them on every screen in the house:
browsers, phones, smart TVs, Roku and Fire TV. Free live TV channels too.

Sofa is plain Python (standard library only) plus ffmpeg. It runs happily on a Mac mini,
and still runs on a 2011 iMac.

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

Drop files or whole folders into **`~/Entertainment/Inbox`**. Sofa waits until the copy
finishes, works out what each file is, renames it and files it:

| You drop | Sofa files it as |
|---|---|
| `the.sopranos.s01e01.1080p.mkv` | `Shows/The Sopranos/Season 1/The Sopranos S01E01 The Sopranos.mkv` |
| a folder `The Sopranos Complete Series` with `Season 1/101 Pilot.avi` | the same tidy layout |
| `Heat.1995.1080p.BluRay.mkv` | `Movies/Heat (1995)/Heat (1995).mkv` |
| a folder `Star Wars Collection` with several movies | `Movies/Star Wars Collection/<each movie in its own folder>` |
| anything in **`Inbox/XXX`** | the **Adult** section; folders like `Hentai` or `Series` keep their shape (see below) |
| songs | `Music/<Artist>/<Album>/` |

Anything Sofa can't work out goes to **`Needs Review`**, with a note on the Server page.
Nothing is ever deleted. More: [docs/folder-structure.md](docs/folder-structure.md).

### Things that just work

- **Any file plays.** MP4 plays as it is. MKV, AVI, HEVC and 10-bit files are adapted for
  each device as they play, and Sofa also **converts them to MP4 in the background** so they
  play instantly next time. The originals are kept until you say otherwise.
  [docs/playback.md](docs/playback.md)
- **A proper player.** Skip Intro / Skip Recap / Skip Credits, "Next episode" when the
  credits start, previews while you scrub, an episode list, sound-track and subtitle
  choice, picture-in-picture, speed, keyboard shortcuts (press `?`), and double-tap to skip
  on phones.
- **Artwork and details.** Shows from TVmaze; movies from the iTunes Store and Wikipedia
  (or TMDB, with a free key, for the best posters and collections); `.nfo` files next to your
  videos are read too. Episodes without a picture get a well-chosen still from the video.
  Wrong match, or none? Click **Find details** on the show or movie and pick the right one.
- **Genres.** Movies and Shows can be browsed by genre (Comedy, Horror, Science Fiction, ...),
  and Home has a row for your biggest genres.
- **Save from a link.** Paste the address of a video page (YouTube, Vimeo and well over a
  thousand other sites); Sofa downloads it with the free yt-dlp tool and files it.
  Server → Downloads.
- **Tidy folders.** Download-style names ("Heat.1995.1080p.BluRay") are tidied, collections
  get a folder per movie, and stray "XXX" folders move into the Adult section.
- **Everyone has their own sign-in** and their own "continue watching". Guests on your Wi-Fi
  scan a QR code on the Server page.
- **Themes.** Press **Theme** at the top: Midnight, Cinema, Ocean, Forest, Grape or Pure black,
  plus subtitle size and TV mode. Each device keeps its own.
- **TVs.** On Fire TV, open Sofa in the **Silk** browser: it switches to TV mode, and the
  remote works like Netflix (OK on Skip Intro skips, ◀ ▶ seek with a preview, Back closes
  panels first). Roku Media Player, VLC and most smart TVs also find Sofa by themselves.
  [docs/tv.md](docs/tv.md)
- **Music**, with albums, artists, stations, likes and a queue. **Live TV** from free channel lists.

### The Adult section

**First, switch it on for yourself:** **Server → People → Adult**. It's off for everyone at
first, admins included; guests and TVs never see it.

- **Your folders are the categories.** Every folder in `~/Entertainment/Adult` (Movies,
  Hentai, Series, Collections, anything you make) gets its own button in the Adult tab.
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
| Overview | addresses to watch from, who's watching, the Inbox, anything that needs you |
| Library | folders, rescan, **missing details** (fix them in a click), Skip Intro progress, Needs Review |
| Converting | the convert-to-MP4 queue with progress; automatic converting on/off |
| Downloads | save videos from links; install yt-dlp; the "Send to Sofa" bookmark |
| Live TV | channel lists |
| People | accounts, Adult access, guests |
| Settings | name, theme, TV sharing, TMDB key, ThePornDB token, backups |
| Updates | version, **Update now** |
| Activity | everything Sofa did, filterable |

---

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

## Layout of this repository

```
sofa.py              command line entry point
sofa/                server: library, inbox, streaming, converter, intro finder, DLNA, live TV, accounts, updater
client/              web app (no build step)
deploy/              install script, macOS LaunchAgent, Linux systemd unit
tools/               get-sofa.sh, update.sh, convert.py
docs/                install, updating, folders, playback, TV, adult, remote access
```

## License

MIT. hls.js (client/vendor) is Apache-2.0.
