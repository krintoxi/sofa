# Sofa

A small, self-hosted home media server. Drop shows and movies into a folder; Sofa names
them, files them, finds artwork and plays them on every screen in the house: browsers,
phones, smart TVs, Roku and Fire TV. Free live TV channels too.

Sofa is plain Python (standard library only) plus ffmpeg. It runs comfortably on a
2011 iMac.

## What it does

- **Drop-in library.** Put anything in `Inbox/`, even `chuck.s02e05.hdtv-lol.mp4`.
  Sofa waits for the copy to finish, works out what it is, renames it and files it
  under `Shows/` or `Movies/`. Things it can't identify go to `Needs Review/` with a
  note. Nothing is ever deleted.
- **Plays any format.** MP4 plays as-is. MKV, AVI and friends are repackaged or
  converted as they stream, only when the device needs it. Seeking works.
- **Every screen.** A web app with resume, "next up", subtitles and a TV-remote mode;
  DLNA so Roku Media Player, VLC and smart TVs find it on their own; HLS for iPhone,
  iPad and Safari.
- **Accounts.** Everyone gets a sign-in and their own "continue watching". Logins are
  throttled, passwords are hashed, admin pages stay at home.
- **Live TV.** Add M3U channel lists (for example the free lists at
  [iptv-org](https://github.com/iptv-org/iptv)) and watch with channel logos,
  groups, favorites and channel up/down.
- **Artwork and details** from TVmaze (no key needed), and TMDB for movies if you add a key.

## Folder layout

```
Entertainment/
  Inbox/          drop anything here
  Shows/          Show Name/Season 1/Show Name S01E01 Title.mkv
  Movies/         Movie Title (1999)/Movie Title (1999).mp4
  Needs Review/   what Sofa couldn't identify, with a note on the Server page
```

More in [docs/folder-structure.md](docs/folder-structure.md).

## Install

Requirements: Python 3.8+ and ffmpeg (optional, but needed to play formats a device
doesn't support).

```sh
git clone <this repo> ~/Sofa
cd ~/Sofa
./deploy/install.sh          # macOS: LaunchAgent; Linux: systemd user service
```

Then open `http://<this computer>:8090` on any device at home. The first person to
open it creates the admin account.

Run by hand instead: `python3 sofa.py serve`. Other commands: `scan`, `inbox`,
`adduser NAME [--admin]`, `passwd NAME`, `status`.

## Watching away from home

Sofa only accepts connections from your home network and Tailscale by default. Read
[docs/remote-access.md](docs/remote-access.md) before changing that: it compares a
private VPN (recommended), a secure public address, and Cloudflare Tunnel.

## Settings

`data/config.json` (created on first run). Most things can be changed on the Server
page. See `sofa/config.py` for every option.

## Tools

`tools/convert.py` converts files to MP4 for good, if you'd rather not convert on the
fly (useful for very slow servers). It can run on a faster machine against files on
the server over SSH.

## Layout of this repository

```
sofa.py              command line entry point
sofa/                server: library, inbox organizer, streaming, DLNA, live TV, accounts
client/              web app (no build step)
deploy/              install script, macOS LaunchAgent, Linux systemd unit
integrations/        optional extras (IRONGATE control-panel integration)
tools/               convert.py
docs/                remote access, folder structure
```

## License

MIT. hls.js (client/vendor) is Apache-2.0.
