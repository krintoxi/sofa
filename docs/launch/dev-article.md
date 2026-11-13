# DEV Community article

**Where:** dev.to, tags `python`, `selfhosted`, `raspberrypi`, `showdev`. Cover image: `docs/images/social-preview.png`.
**DEV's content policy** (dev.to/terms, section 11, read 2026-11-10): content must not be "designed primarily for the
purposes of promotion or creating backlinks", and "Posts must contain substantial content — they may not merely
reference an external link that contains the full post." This article is the full text, with the repository linked
once at the end. **Who posts:** the owner, from their own account.

---

# I built a home media server with nothing but Python's standard library and ffmpeg

`<YOUR OWN REASON FOR MAKING IT, TWO OR THREE SENTENCES: what you wanted at home and why the existing servers weren't it. Only what's true for you.>` Jellyfin is excellent; every part of it was bigger than one house needed. So Sofa has one constraint that shaped everything else: **Python's standard library and ffmpeg, nothing else to install.** It's source-available (PolyForm Noncommercial), free to run at home; I'll come back to that at the end. This is what the constraint did to the design.

## One process, no framework

Sofa is `http.server` with a thread pool, SQLite through `sqlite3`, and a web app in one `app.js` with no build step. That sounds like a toy. It has held up: a 7,500-file library goes to the browser as about 100 KB gzipped, long pages draw as you scroll, and a 2011 iMac serves four screens at once. The win isn't speed. It's that `curl -fsSL …/get-sofa.sh | sh` is the whole install on a Mac or a Linux box (Windows gets an installer that brings its own Python and ffmpeg, and Docker a `compose.yml`), and an update is a swap of one folder that rolls back by itself if the new version falls over three times in its first minute.

## The Inbox

The feature people use most is a folder. Drop `the.sopranos.s01e01.1080p.bluray.x265-GROUP.mkv` in `~/Entertainment/Inbox` and, thirty seconds after it stops changing, it's `Shows/The Sopranos/Season 1/The Sopranos S01E01 Pilot.mkv`, with the subtitle file that came with it renamed alongside and the poster that was in the folder attached. `sofa/naming.py` is the ugliest file in the repository on purpose: scene names, `Show 2x05`, `[Group] Anime - 05 [1080p]`, daily shows by date, `Movie CD1/CD2`, phone videos by timestamp, collections of several movies in one folder. Each rule has a test with the ugly name beside the right answer. The rule above all the others: **nothing is ever deleted.** Leftovers go to a Deleted folder you empty when you're sure; anything it can't read goes to Needs Review with a note.

## Adapting formats as they play

MP4 with H.264 and AAC plays everywhere, so that's the target. An MKV with the same streams inside is repackaged on the fly (`-c copy`, milliseconds). HEVC, 10-bit, DTS and the old codecs are transcoded as they play, and a background job converts them to MP4 so the next play is instant. The part that had to be right was deciding *how* to encode: on a Mac, Sofa times `h264_videotoolbox` against `libx264` on first run, because some older Macs' hardware encoder draws lines across the picture, and it never uses it there. On Linux it's x264 in software for now; hardware transcoding there is on the list, not in the code. If a file converts slower than it plays (a 1080p HEVC episode on that 2011 iMac), the player waits once for a few seconds of buffer instead of stalling every few seconds, then drops the picture a size, and remembers that for the next file like it.

## Skip Intro without a cloud

Chapters when the file has them. Otherwise ffmpeg's chromaprint fingerprints the first minutes of neighbouring episodes and Sofa looks for the shared stretch; the result is cached and the button appears already selected when the intro starts. Credits the same way, from the end. No service, no uploads.

## The TV signs in on your phone

Typing a password with a remote is the worst thing about every TV app, so Sofa's TV page shows a six-digit code and a QR code; you approve it in Sofa on your phone and pick who's watching. The same pairing endpoint hands the Fire TV app and the Roku channel their tokens. Once a TV is paired, your phone is its remote: pause, skip, scrub, next episode, through the server, at home.

## Letting yourself in from outside, and friends in

Remote access is where self-hosted projects usually say "set up a reverse proxy". Sofa does it itself: a free DuckDNS name or your own domain, a Let's Encrypt certificate it requests and renews (the ACME client is tested in CI against Pebble, Let's Encrypt's test server), a UPnP request to the router, and a check from outside that tells you what the internet sees. Over the internet it answers only HTTPS and only signed in. For friends there's a share link: a view-only copy of Sofa with just the titles you picked.

## The box: a kiosk that is a TV

Then the TV itself. Sofa Box OS is a Raspberry Pi image that's a whole TV box: Raspberry Pi OS Lite, one Chromium under `cage` (a Wayland kiosk compositor), and every streaming app is a tab of that one browser. A Python agent steers it over the DevTools protocol: it opens apps as tabs, brings the home screen back on the Home key, parks the pointer, injects a bar for Back and Home into pages that have none, and watches memory so a Pi 3 with 1 GB doesn't fall over. Video never goes through the browser: `mpv` plays it on the Pi's video chip, with its own on-screen display written in Lua so the time line, Skip Intro and the volume all stay inside the part of the picture every TV shows.

The phone remote is a page the box serves. Setup is a QR code on the TV; with no cable the box makes its own Wi-Fi, the phone joins it through a captive portal, and hands over the home Wi-Fi. A Fire TV remote pairs by holding Home. A controller works everywhere, as a remote and in the games.

## The stable channel

A TV box that updates itself needs to be careful about what it updates to. Boxes read two small files from the repository: the newest version and a `STABLE` pointer. The Stable channel installs exactly the version named there, and nothing until the owner has tested that card on a real Pi and written its number in; the Testing channel follows main. Weekly updates run at night, only when nothing is playing, and are off until you switch them on. Right now `STABLE` says `none`, because no card has had its hardware pass yet. That's the honest state, and the box's own Settings page says so.

## What was hard

Three things. First, **first boot on a Raspberry Pi**: Raspberry Pi Imager's "set a user" option runs a tool on first start that switches the system to a text console, which killed the TV screen; it took booting the card's root file system in a container on a Mac to see it and to prove the fix without an evening of SD cards for every try. Second, **a Pi 3 is slow in ways a laptop can't fake**: Chrome's CPU throttle doesn't slow painting or decoding, so the speed work had to be measured with counters (how many times a row re-rasters per key press), not milliseconds, and then checked from the box's own reports. Third, **saying only what's true**: with one tester and one Pi, the capabilities page marks every line Works, Beta or Untested on hardware, with the test or the report that says so. It's less exciting than a feature list. It's also the only page I'd trust from a project this young.

## Tests instead of a team

There's one maintainer, so there are more than 600 tests, and GitHub runs them on every push with real ffmpeg, real mpv, a real headless Chrome and that Pebble server, on Linux and on Windows. The box's games are played by a headless Chromium in CI. It's the only way one maintainer ships a media server and a TV operating system and sleeps.

## What it isn't

No hardware transcoding on Linux, a Windows installer and a Docker image that are days old (the installer has run on GitHub's Windows machines, the image on one Linux VM), no app in any TV store, no tuner or DVR, no photos, no plugins. And it's source-available (PolyForm Noncommercial 1.0.0) rather than open source: free to use, read, change and share for noncommercial purposes, while I keep the right to sell boxes with it; versions before 1.5.4 are MIT. The repository has a comparison with Jellyfin, Plex, Emby and Kodi that tries hard to be fair: it says "pick Jellyfin, Plex or Emby if you need a NAS package, an app from the TV's own store, or hardware transcoding on a Linux box", and I mean it.

If you try it, the thing I most want to hear is what broke on your machine: https://github.com/krintoxi/sofa
