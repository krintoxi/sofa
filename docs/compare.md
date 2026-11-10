# Sofa, Jellyfin or Plex?

For a person choosing a home media server. Written on 2026-11-10 against **Sofa 1.5.4**, Jellyfin 12 and Plex as
sold that month. Sofa's column comes from this repository's code and tests ([capabilities.md](capabilities.md) has
the evidence for each line); the other two from their own documentation and announcements. Things change: if a line
is out of date, [open an issue](https://github.com/krintoxi/sofa/issues/new/choose) and it gets fixed.

**The short version.** Jellyfin and Plex are big, mature servers with an app in every TV's store. Sofa is a small
one, made for a household rather than a homelab: you drop files in a folder, they come out named and with posters,
the TV signs in by approving it on your phone, and nothing about it needs an account with anyone. It runs on a Mac
or a Linux computer with Python and ffmpeg and nothing else to install, and it comes with its own TV box for a
Raspberry Pi. It is also three weeks old, made by one person, and has no store apps. **Don't pick Sofa to replace
Jellyfin feature for feature. Pick it if you want less to run, and the box.**

## Side by side

| | **Sofa** | **Jellyfin** | **Plex** |
|---|---|---|---|
| **Price** | Free for noncommercial use. No paid tier. | Free. Donations. | Free with limits; **Plex Pass** $6.99 a month, $69.99 a year, or $749.99 once (lifetime, since 2026-07-01). Remote streaming of your own library needs a Pass or the **Remote Watch Pass** ($1.99 a month) since April 2025. |
| **Licence** | Source-available: **PolyForm Noncommercial 1.0.0**. Read it, change it, share it, run it at home; selling it or boxes with it needs EdgeVenture's licence. Not an open-source licence by the OSI's definition. | **Open source** (GPL-2.0). | Proprietary. |
| **An account with the maker** | None. Accounts live in your own Sofa. | None. | Required (plex.tv), for the server and for every watcher. |
| **Where the server runs** | **Mac or Linux**, Python 3.8+ and ffmpeg. One line in Terminal. **No Windows, no Docker image, no NAS packages** yet ([roadmap](roadmap.md)). | Windows, macOS, Linux, Docker, FreeBSD, most NAS brands. | Windows, macOS, Linux, Docker, NAS brands, NVIDIA Shield. |
| **Getting your files in** | Drop them in an **Inbox**, download-style names and all: Sofa names them, files them into Shows and Movies, attaches subtitles and posters that came along, and deletes nothing. | You name and sort the folders ([their naming guide](https://jellyfin.org/docs/general/server/media/shows/)), or run Sonarr/Radarr in front. | You name and sort the folders ([their naming guide](https://support.plex.tv/articles/naming-and-organizing-your-tv-show-files/)), or run Sonarr/Radarr in front. |
| **Artwork and details** | TVmaze (shows), the iTunes Store and Wikipedia (movies), TMDB with your own free key, `.nfo` files; a still from the video when nothing is found. | TMDB, TheTVDB, OMDb and more, through plugins. | Plex's own service. |
| **Playing anything** | ffmpeg adapts MKV, HEVC, 10-bit and the rest as they play, and converts them to MP4 in the background so they play as they are next time. Hardware encoding on Macs (VideoToolbox); on Linux it's software. | ffmpeg transcodes on the fly. **Hardware transcoding is free** (Intel, AMD, NVIDIA). | Transcodes on the fly. Hardware transcoding needs **Plex Pass**. |
| **Skip Intro, Next episode** | Built in: from chapters, or by listening to neighbouring episodes (ffmpeg's chromaprint). Skip Recap and Skip Credits too. | Through a plugin (Intro Skipper); media segments are in the server since 10.10. | Intro and credits detection need **Plex Pass**. |
| **Subtitles** | What comes with the file, or next to it; sizes, outline, timing. **No subtitle downloads.** | OpenSubtitles plugin. | Built-in downloads. |
| **The player on a TV** | TV mode in any TV browser; Sofa's own Fire TV app and Roku channel, **sideloaded**, served by your own server; the Sofa Box. **No app in any store**, and no dated run of the Fire TV app or the Roku channel on a real device yet ([tested on](capabilities.md#tested-on)). | Apps in the Android TV, Fire TV, Roku, Apple TV, LG, Samsung and Kodi stores. | Apps everywhere. |
| **Phones and laptops** | The web app, installable as an app (Add to Home Screen). | Web app and native apps (Jellyfin, Swiftfin, Finamp, Infuse works too). | Web app and native apps. |
| **Who's watching** | Profiles with their own Continue watching, **Kids profiles** (family titles only, no Live TV, no Server page), 4-digit PINs on profiles that run the server, **guests by QR code** on your Wi-Fi. | Users with parental ratings and library access per user. | Plex Home with managed users (some parts Pass). |
| **The TV signs in how** | A code on the TV, approved on your phone (or scan the QR code). | Name and password on the TV (Quick Connect code from a signed-in app). | Four-letter link code at plex.tv/link. |
| **Your phone as the remote** | Built in, for any screen that has Sofa open, at home. | Through apps (cast to a signed-in client). | Plex apps' "Play on". |
| **Live TV** | M3U channel lists you add (none come with it), and **Classic Cinema**: free classic films from a public archive, on a clock, with a guide. **No tuner, no recording.** | Tuners (HDHomeRun and more), M3U lists, a guide and **DVR, free**. | Tuners and DVR with Plex Pass; Plex's own ad-supported channels free. |
| **Music** | Albums, artists, stations, likes, a queue. No playlists of your own, no lyrics. | Full music library; Finamp app. | Plexamp (Pass for the best of it). |
| **Photos** | None. | Yes. | Yes (taken out of the TV apps in 2025). |
| **Away from home** | Built in: your own domain or a free DuckDNS name, a Let's Encrypt certificate Sofa gets and renews, the router asked over UPnP, a check from outside. Or Tailscale. Over the internet Sofa answers only over HTTPS and only signed in. | Yourself: a reverse proxy, certificates, your router; or Tailscale. | Through Plex's relay or direct; paid since April 2025 for your own library. |
| **Sharing with friends** | A **public library**: pick titles, send a link; visitors see only those and can only watch. | Make them an account. | Plex friends, through plex.tv. |
| **Privacy** | No account, no analytics, no telemetry; **Work offline** switch; [everything that touches the internet, with its switch](privacy.md). | No account, no telemetry. | An account, usage reporting, Plex's own ad-supported content in the same apps. Your server's details live with Plex. |
| **Plugins** | None. | Many. | Few left. |
| **A ready-made TV box** | **Sofa Box OS**: a Raspberry Pi card with Sofa built in, free Live TV, the streaming apps, games and your phone as the remote. Run on one Pi 3 B+ so far ([status](capabilities.md#sofa-box-os)). | None of its own (Kodi on LibreELEC with the Jellyfin add-on is the usual route). | None of its own. |
| **Behind it** | One person, since October 2026; over 400 automated tests. | A large volunteer project since 2018. | A company since 2010. |
| **Tested where** | Daily on one Mac; Linux by GitHub's test machines only; the box on one Pi 3 B+. | Everywhere. | Everywhere. |

Emby isn't in the table: it sits between Jellyfin and Plex (Jellyfin began as a fork of it), with a paid Premiere tier
for hardware transcoding and the TV apps.

## Pick Sofa if

- you want the server on a Mac (an old one is fine) or a Linux computer with nothing to install but ffmpeg;
- your files arrive messy and you'd rather not name and sort them by hand;
- the people watching are a household, not users: profiles, Kids, PINs, a TV that signs in from your phone;
- you want no account with anyone, and an off switch for everything that uses the internet;
- you want a TV box with no ads and no tracking of its own, and you're happy with a Raspberry Pi, a beta, and one
  maintainer's pace.

## Pick Jellyfin if

- you need Windows, Docker or a NAS;
- you want an app from the TV's own store, on every TV;
- you record TV from a tuner, or you want photos, a plugin, or a client of your choice;
- you want open source in the strict sense, a large community and years of history.

## Pick Plex if

- you want the most polished apps on the most devices and don't mind the account and the price;
- you watch from away from home a lot and don't want to set anything up for it.

## What Sofa doesn't do yet

The list, in order, with what's untested, is in [roadmap.md](roadmap.md). The biggest gaps against the other two:
no Windows or Docker, no store apps, no tuner or recording, no subtitle downloads, no photos, no plugins, one tester
on one Raspberry Pi.
