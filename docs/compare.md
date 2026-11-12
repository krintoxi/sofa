# Where Sofa fits: Jellyfin, Plex, Emby, Kodi, and the box against a Fire TV

For a person choosing a home media server, or a TV box. Written on 2026-11-10 against **Sofa 1.5.4** and **Sofa Box
OS 1.1.60**. Sofa's column comes from this repository's code and tests ([capabilities.md](capabilities.md) has the
evidence for each line); the others from their own pages, cited with the date they were read. Things change: if a
line is out of date, [open an issue](https://github.com/krintoxi/sofa/issues/new/choose) and it gets fixed.

**The short version.** Jellyfin, Plex and Emby are mature servers with an app in every TV's store, and Kodi is a
player you build a setup around. Sofa is a server made for a household rather than a homelab: drop files in a folder
and they come out named with posters, the TV signs in by approving it on your phone, your phone is the remote, there
are no accounts with anyone, and it comes with its own TV box for a Raspberry Pi. It runs on a Mac or a Linux computer
with Python and ffmpeg and nothing else, or in Docker. It is also weeks old, made by one person, source-available rather than open
source, without hardware transcoding on Linux, without an Android TV or Apple TV app, and untested on a Pi 4 or 5.
**Sofa does not do everything Jellyfin does, and doesn't try to.** Pick it for less to run, a household's habits, and
the box.

## Servers, side by side

| | **Sofa** | **Jellyfin** | **Plex** | **Emby** | **Kodi / LibreELEC** |
|---|---|---|---|---|---|
| **What it's for** | A household's own streaming service at home, and its own TV box | A full media server for people who run their own | A media server and a streaming service in one product | A media server, between Jellyfin and Plex | A player for one screen (LibreELEC: a whole OS for it), with add-ons for servers |
| **Price** | Free for noncommercial use. No paid tier. | Free. Donations. | Free with limits; **Plex Pass** $6.99 a month, $69.99 a year, or $749.99 once (the lifetime price since 2026-07-01); remote streaming of your own library needs a Pass or the **Remote Watch Pass** at $1.99 a month since April 2025 [¹](#sources) | Free with limits; **Emby Premiere** $4.99 a month, $54 a year, $119 once [²](#sources) | Free |
| **Licence** | Source-available: **PolyForm Noncommercial 1.0.0** (not an open-source licence by the OSI's definition). Read, change, share, run at home; selling it or boxes with it needs EdgeVenture's licence | Open source (GPL-2.0) [³](#sources) | Proprietary | Proprietary (the server); some apps open source | Open source (GPL-2.0-or-later) [⁴](#sources) |
| **Hardware for the server** | A Mac (an old one is fine), a Windows 10 or 11 PC (an installer, since 1.5.8; not yet run on a real PC), a Linux computer, or Docker (`ghcr.io/krintoxi/sofa`, with a `compose.yml`; how a NAS runs it). **No NAS packages** | Windows, macOS, Linux, Docker, FreeBSD, most NAS brands | Windows, macOS, Linux, Docker, NAS brands, NVIDIA Shield | Windows, macOS, Linux, Docker, NAS brands | No server: Kodi plays from folders, shares or another server |
| **Library and metadata** | An **Inbox**: drop files with download-style names and Sofa names them, files them into Shows and Movies, attaches subtitles and posters that came along, and deletes nothing. Details from TVmaze, the iTunes Store and Wikipedia, TMDB with your key, `.nfo` files; a still from the video when nothing is found | You name and sort folders by their guide; metadata from TMDB, TheTVDB and plugins | You name and sort folders by their guide; Plex's own metadata service | You name and sort folders; its own scrapers | You name and sort folders; scrapers per library |
| **Formats and transcoding** | MP4 served as it is; MKV repackaged; HEVC, 10-bit, DTS and old codecs converted as they play and converted to MP4 in the background for next time. **Hardware encoding on Macs only** (VideoToolbox); software x264 on Linux | Transcodes on the fly; hardware acceleration (QSV, NVENC, AMF, VAAPI, VideoToolbox, RKMPP) at no charge [⁵](#sources) | Transcodes on the fly; hardware transcoding needs Plex Pass | Transcodes on the fly; hardware transcoding needs Premiere [²](#sources) | Plays almost anything itself; no transcoding (the client decodes) |
| **Skip Intro** | Built in: from chapters, or by listening to neighbouring episodes (chromaprint). Recap and Credits too | Media segments in the server; detection through a plugin | Intro and credits detection need Plex Pass | Premiere | Add-ons |
| **Live TV** | M3U channel lists you add (none come with it), and Classic Cinema: free classic films on a clock with a guide. **No tuner, no recording** | Tuners (HDHomeRun and more), M3U, a guide, DVR, free | Tuners and DVR with Plex Pass; Plex's own ad-supported channels | Tuners, guide and DVR with Premiere | PVR add-ons for tuners and IPTV |
| **TV apps** | **None in any store.** TV mode in any TV's browser; Sofa's own Fire TV app and Roku channel, sideloaded and served by your own server, with **no run on a real device on record**; or the Sofa Box | Android TV, Fire TV, Roku, Apple TV, LG, Samsung, Kodi add-on | Everywhere | Android TV, Fire TV, Roku, Apple TV, LG, Samsung | Kodi itself is the TV app (Android TV, Fire TV, LibreELEC on a Pi or PC) |
| **Phone as the remote** | Built in: with Sofa open on any screen, your phone plays there, pauses, skips, scrubs; the TV signs in by a code you approve on the phone | Through its apps (cast to a signed-in client) | Plex apps' "Play on" | Through its apps | Kore, the official remote app |
| **A whole TV box OS** | **Sofa Box OS** on a Raspberry Pi (run on one Pi 3 B+ so far): its own home screen, Sofa built in, the streaming apps, games, phone remote | None of its own | None of its own | None of its own | **LibreELEC**: Kodi as the OS on a Pi or PC; no streaming apps with DRM |
| **Privacy and accounts** | No account with anyone; no analytics or telemetry; a **Work offline** switch; [every internet use listed with its switch](privacy.md) | No account, no telemetry | A plex.tv account for the server and every watcher; ad-supported content in the same apps | An Emby account for Premiere and Emby Connect; optional otherwise | None |
| **Setup** | One line in Terminal, then the first account in the browser; the Inbox does the rest | Install, a wizard, libraries by folder; Docker for most | Install, a plex.tv account, claim the server | Install, a wizard | Install Kodi, add sources, set scrapers; LibreELEC: write a card |
| **Behind it** | One person, since October 2026; over 400 automated tests | A large volunteer project since 2018 | A company since 2010 | A small company | A foundation and volunteers since 2003 |

## The box, against what it replaces

| | **Sofa Box OS on a Raspberry Pi** | **A Fire TV stick** | **Channels DVR** (as a TV-first alternative) |
|---|---|---|---|
| **What it is** | A card that turns a Pi 3 B+ (Pi 4 and 5 untested) into a TV box: its own home screen, Sofa, the streaming apps full screen, free Live TV from lists you add and Classic Cinema, games, USB drives and discs, your phone as the remote | Amazon's streaming stick with its own store and remote | A paid DVR server with its own apps, for tuners and TV Everywhere channels |
| **Price** | The Pi, a card and a supply; the software is free for noncommercial use | $30 to $85 depending on the model (Amazon's list prices; they vary) | $8 a month or $80 a year [⁶](#sources), plus an HDHomeRun or a cable login |
| **Accounts and ads** | No account; no ads of its own; nothing counts what you watch; a hosts-file blocker for the whole box | An Amazon account; a home screen with ads and sponsored rows | An account; no ads of its own |
| **Streaming apps** | Netflix, YouTube, Disney+, Prime Video and about fifty more as full-screen web apps in one browser; Widevine from Raspberry Pi OS. **YouTube seen on the Pi 3; the DRM apps have never been opened on any Pi** ([status](capabilities.md#sofa-box-os)); 1080p at most on Linux browsers, less on a Pi 3 | Every app in Amazon's store, in 4K with HDR on the 4K models | Not an app platform |
| **Your own files** | Sofa, built in: from your server, a share link, or Sofa on the box itself (USB drives); Jellyfin, Emby and Plex as web apps | Through each server's app | Through Channels' own library |
| **Sideloading** | Not needed: it's a browser | Fire OS 7 and 8 only; the new Vega sticks can't [⁷](#sources) | — |
| **Remote** | Your phone (nothing to install), a Fire TV remote, a controller, the TV's own remote over HDMI-CEC (CEC untested) | Its remote | Apps |
| **Tested** | One Pi 3 B+, one iPhone, one Xbox controller ([tested on](capabilities.md#tested-on)) | Millions | — |

## Pick Sofa if

- you want the server on a Mac or a Linux computer with nothing to install but ffmpeg;
- your files arrive messy and you'd rather not name and sort them by hand;
- the people watching are a household: profiles, Kids, PINs, a TV that signs in from your phone;
- you want no account with anyone, and an off switch for everything that uses the internet;
- you want a TV box with no ads and no tracking of its own, and you're happy with a Raspberry Pi, a beta, and one
  maintainer's pace.

## Pick Jellyfin, Plex or Emby if

- you need a NAS package (Sofa on a NAS is its Docker image), or a Windows server that has years of use behind it
  (Sofa's Windows installer is new in 1.5.8);
- you want an app from the TV's own store on every TV, or hardware transcoding on a Linux box;
- you record TV from a tuner, or want photos, plugins, or a client of your choice;
- you want open source in the strict sense (Jellyfin), or the most polished apps on the most devices and don't mind
  the account and the price (Plex).

## Pick Kodi or LibreELEC if

- you want one screen's player, every format, every add-on, and you're happy to set it up and keep it.

## What Sofa doesn't do yet

The list, in order, is in [roadmap.md](roadmap.md). The biggest gaps against the others: no NAS
packages, a Windows version that's new, no store apps, no hardware transcoding on Linux, no tuner or recording, no subtitle downloads, no photos, no plugins,
and one tester on one Raspberry Pi.

## Sources

1. Plex, "New Lifetime Plex Pass pricing" (plex.tv/blog/new-lifetime-plex-pass-pricing, read 2026-11-10): $749.99 from
   2026-07-01; Plex Pass $6.99 a month, $69.99 a year; Remote Watch Pass $1.99 a month. Remote streaming paid since
   Plex's April 2025 changes (plex.tv/blog/important-2025-plex-updates).
2. Emby, emby.media/premiere.html (read 2026-11-10): $4.99 a month, $54 a year, $119 once; hardware transcoding, DVR
   and full app access are Premiere features.
3. Jellyfin's licence: github.com/jellyfin/jellyfin, `LICENSE` (GPL-2.0).
4. Kodi's licence: github.com/xbmc/xbmc, `LICENSE.md` (GPL-2.0-or-later); LibreELEC: github.com/LibreELEC/LibreELEC.tv.
5. Jellyfin, "Hardware acceleration" (jellyfin.org/docs/general/post-install/transcoding/hardware-acceleration, read
   2026-11-10): QSV, NVENC, AMF, VAAPI, VideoToolbox, RKMPP; Jellyfin has no paid tier.
6. Channels, "Subscription" (getchannels.com/docs/getting-started/quick-start-guide/subscription, read 2026-11-10):
   "$8/month or $80/year".
7. Amazon's Vega OS (Fire OS 8) runs no Android packages; see Amazon's developer documentation for Vega, and the note
   in [tv.md](tv.md).
