# Roadmap, and what Sofa doesn't do yet

Written on 2026-11-10, at **Sofa 1.5.4** and **Sofa Box OS 1.1.60**. Sofa is made by one person; this is the order
of work, not a promise, and there are no dates. What has shipped is in [CHANGES.md](../CHANGES.md) and
[the box's changelog](../deploy/sofa-box/CHANGES.md); what works today, with the evidence for each line, is in
[capabilities.md](capabilities.md).

## Known limitations today

Read this before you install, so nothing surprises you.

- **The server runs on a Mac, on Linux, on Windows, or in Docker.** No NAS packages (the Docker image is how a NAS
  runs it). Python and ffmpeg are all it needs; the Windows installer brings both. Sofa for Windows (1.5.9) has run on
  GitHub's Windows machines, installer included, and not yet on a real PC; it runs while you're signed in, not as a
  Windows service, and it isn't signed yet. The one-line install
  is used daily on Macs; on Linux the test suite runs on every push, and the install was run in a clean Debian 13
  system with systemd for the record (Sofa 1.5.5, the tested-on table in [capabilities.md](capabilities.md#tested-on));
  the Docker image has run on one Linux virtual machine (arm64) and nowhere else yet. Nobody has written down
  running Sofa as a daily server on Linux or in Docker.
- **No hardware transcoding on Linux.** Sofa encodes with Apple's VideoToolbox on Macs and with x264 in software
  everywhere else; there is no VAAPI, Quick Sync or NVENC path yet. Files a device plays as they are aren't
  transcoded at all, and the background conversion to MP4 makes the second play free.
- **No app in any TV store.** On a TV you use its browser, sideload Sofa's own Fire TV app or Roku channel, or use a
  Sofa Box. There is no Android TV, Google TV, Apple TV, Samsung or LG app. The Fire TV app and the Roku channel are
  built by GitHub and **no run on a real device is on record**. Fire OS 8 (Vega) sticks can't sideload anything.
- **The Sofa Box has run on one Raspberry Pi 3 Model B+**, the owner's. A Pi 4 or 5 has never run it; the DRM apps
  (Netflix, Disney+…), USB drives, discs and HDMI-CEC are built and tested in software and have not been tried on a real
  box; the newest card the Pi has booted is 1.1.49, so the one TV player, the update channels and the first-boot fixes of
  1.1.53 to 1.1.60 meet a Pi for the first time at the next test. **No card is marked stable yet.**
- **The Mac card writer** (`imager/`) has written a card to a disk image in its tests and never to a real SD card.
- **The PC and virtual-machine image** (1.1.60) has booted on GitHub's machines under UEFI and BIOS, never on a real PC.
- **Live TV** plays channel lists you add and Classic Cinema from a public film archive. There is no tuner support and
  no recording. Retro TV's decades (recordings of TV as it aired, played straight from a public video library) are
  on unless an admin turns them off, and never reach the public library's visitors.
- **Not built:** subtitle downloads, watch-together, photos, TV recording, a caption editor, playlists in Music, lyrics,
  plugins, Plex or Jellyfin history import.
- **The secure phone remote** for a box passes through EdgeVenture's relay (the code is in `deploy/box-certs/`); it
  can be switched off, and the plain http remote works at home without it.
- **The licence isn't an open-source licence.** PolyForm Noncommercial 1.0.0: free to use, read, change and share for
  noncommercial purposes; commercial use needs EdgeVenture's licence. Versions before 1.5.4 stay MIT.
- **One maintainer, one tester.** Issues get read; there is no support line.

## Done

The last few weeks, from the changelogs:

- **Sofa 1.5.x:** Retro TV's decades off unless turned on (1.5.0), then on by default again (1.5.6); away from
  home, Live TV plays straight from the channel and never through your Sofa; every video on a box plays in the
  box's own player with its start card; big skips in converted video; the Pi 3 quicker (rows as layers the graphics
  chip slides); the licence, `NOTICE`, `TRADEMARKS.md`, `CONTRIBUTING.md`.
- **Sofa Box OS 1.1.5x and 1.1.60:** a stable and a testing update channel with weekly updates off by default; the
  first start survives Raspberry Pi Imager's settings; Home says when the Pi is short of power or hot; credits and
  licences for every part on the card, and where each TV brand hides its own tracking switch; Sofa Box OS by name in
  Raspberry Pi Imager through the box's own list; the Mac card writer (beta); the x86-64 PC and VM image; the
  `rpi-image-gen` prototype; thirteen games of its own on two engines, with several controllers.
- **The record:** [capabilities.md](capabilities.md) with its tested-on table, [hardware.md](hardware.md), the issue
  templates, this page and [compare.md](compare.md).
- **Sofa 1.5.5: Sofa in Docker.** A `Dockerfile` and a `compose.yml` on the computer's own network, the image
  published as `ghcr.io/krintoxi/sofa` by GitHub; in a container, Updates says to pull the new image.

## Next

In order. Each one ends with a line in the tested-on table.

1. **The stable card.** The owner tests the current card on the Pi 3 B+; the first card that passes is marked stable
   (`deploy/sofa-box/STABLE`), and boxes on the Stable channel start getting updates.
2. **A Pi 4 and a Pi 5 pass**, including what HEVC and 4K actually do there. If you have one, a
   [hardware report](https://github.com/krintoxi/sofa/issues/new/choose) is the most useful thing you can send.
3. **The DRM apps on a real box:** Netflix, Disney+, Prime Video, Max, Spotify opened on a Pi, with what played, at what
   size, written down.
4. **The Fire TV app and the Roku channel on real devices**, with the Fire OS 7/8 check published where people install
   from, and a move from the public signing key in the repository to a private one (a one-time reinstall).
5. **The Mac card writer's first real SD card**, and **a real PC** for the x86-64 image.
6. **The Pi 3 under 100 ms a key press**, measured on the Pi from its own reports (1.1.57 did the work).
7. **Raspberry Pi Imager's own OS list**, once a stable card exists.
8. **A public demo** you can open without installing anything: a Sofa with a free library, run as its own instance.

## Later

- **Linux and Docker written up as a daily server** (the image exists since Sofa 1.5.5; a week of real use on a
  Linux box or a NAS, with what went wrong, is what's missing).
- **Hardware transcoding on Linux** (VAAPI and Quick Sync first), measured on a real machine.
- A **Google TV** build, tested on a cheap Google TV box, with the package registered before Google's 2027 developer
  verification.
- **Google's arm64 Chrome** on the Pi 4 and Pi 5 for the DRM apps where Raspberry Pi OS's Chromium falls short.
- **Games:** your phone as a controller, a light and a full tier per game, freeing the home screen's graphics memory
  while a native game runs.
- The phone remote's relay encrypted end to end, and moved to its own machine.
- **Subtitle downloads**, **watch-together**, a **caption editor**, and the Roku channel brought level with the Fire TV app.
- Roku store certification; a Fire OS 8 (Vega) app if Amazon's web-view route allows a server of your own.
- **Plex and Jellyfin history import** (what you've watched, where you were).
- **HDHomeRun** recording.
- A native **Apple TV** app (tvOS has no web view, so it has to be native).

## Not planned

- Accounts with EdgeVenture, a cloud, ads, telemetry, or "premium" features. Playback stays free.
- Android apps on the Sofa Box, or a front panel for a small screen.

## How to help

- Run it and say what happened: [a bug report or a hardware report](https://github.com/krintoxi/sofa/issues/new/choose),
  with the box's **Send a report** code if it's a box. Testers for a Pi 4, a Pi 5, a Fire TV stick, a Roku, an Android
  phone as the box's remote, and Linux as a daily server are the ones most needed.
- Fixes and improvements are welcome under [CONTRIBUTING.md](../CONTRIBUTING.md); open an issue first for anything
  bigger than a fix.
