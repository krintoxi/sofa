# Roadmap, and what Sofa doesn't do yet

Written on 2026-11-10, at **Sofa 1.5.4** and **Sofa Box OS 1.1.60**. Sofa is made by one person; the order below is
the plan, not a promise, and it changes when a real device disagrees with it. What has shipped is in
[CHANGES.md](../CHANGES.md) and [the box's changelog](../deploy/sofa-box/CHANGES.md); what works today, with the
evidence, is in [capabilities.md](capabilities.md).

## Known limitations today

Read this before you install, so nothing surprises you.

- **The server runs on a Mac or Linux only.** No Windows, no Docker image, no NAS packages. Python and ffmpeg are
  all it needs, and the one-line install is tested on Macs; on Linux the test suite runs on every push, but nobody has
  written down running it as a daily server there yet.
- **No app in any TV store.** On a TV you use its browser, or sideload Sofa's own Fire TV app or Roku channel, or
  use a Sofa Box. The Fire TV app and the Roku channel are built by GitHub and **no run on a real device is on record**.
  Fire OS 8 (Vega) sticks can't sideload anything.
- **The Sofa Box has run on one Raspberry Pi 3 Model B+**, the owner's. A Pi 4 or 5 has never run it; the DRM apps
  (Netflix, Disney+…), USB drives, discs and HDMI-CEC are built and tested in software and have not been tried on a real
  box; the newest card the Pi has booted is 1.1.49, so the one TV player, the update channels and the first-boot fixes of
  1.1.53 to 1.1.60 meet a Pi for the first time at the next test. **No card is marked stable yet.**
- **The PC and virtual-machine image** (1.1.60) has booted on GitHub's machines under UEFI and BIOS, never on a real PC.
- **Live TV** plays channel lists you add and Classic Cinema from a public archive. There is no tuner support and no
  recording. Retro TV's decades (recordings of TV as it aired) are switched off unless an admin turns them on, because
  nobody has cleared their rights.
- **Not built:** subtitle downloads, watch-together, photos, TV recording, a caption editor, playlists in Music, lyrics,
  plugins, Plex or Jellyfin history import.
- **The secure phone remote** for a box passes through EdgeVenture's relay (the code is in `deploy/box-certs/`); it
  can be switched off, and the plain http remote works at home without it.
- **One maintainer, one tester.** Issues get read; there is no support line.

## Now: the next few releases

1. **Prove the box on hardware.** The owner tests the current card on the Pi 3 B+; the first card that passes is
   marked **stable** (`deploy/sofa-box/STABLE`), and boxes on the Stable channel start getting updates. Then a Pi 4 and
   a Pi 5 pass, each written down in [capabilities.md](capabilities.md#tested-on). If you have one of those, a
   [hardware report](https://github.com/krintoxi/sofa/issues/new/choose) is the most useful thing you can send.
2. **A Docker image, and Linux as a daily server.** The most asked-for gap. One `docker compose up` with the library
   folders mounted, host networking for DLNA and the TV sign-in, and a written pass on a Debian or Ubuntu machine.
   This also gives Windows users a way in (Docker Desktop), without a native Windows build.
3. **The TV apps on real devices.** The Fire TV app and the Roku channel run on a real stick and a real Roku, with what
   played and what didn't written down; the Fire OS 7/8 check published where people install from; a move from the
   public signing key in the repository to a private one (a one-time reinstall).
4. **The Pi 3 under 100 ms a key press**, measured on the Pi from its own reports (1.1.57 did the work; the Pi hasn't
   measured it yet).
5. **Raspberry Pi Imager's own list.** Sofa Box OS by name in Imager's OS menu, once a stable card exists. Until then
   the `sofa-box.rpi-imager-manifest` file does it.
6. **A public demo** you can open without installing anything: a Sofa with a free library, run as its own instance.

## Next

- A **Google TV** build (tested on an Onn 4K Pro), with the package registered before Google's 2027 developer
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

- A native Windows server (Docker is the route).
- Accounts with EdgeVenture, a cloud, ads, telemetry, or "premium" features. Playback stays free.
- Android apps on the Sofa Box, or a front panel for a small screen.

## How to help

- Run it and say what happened: [a bug report or a hardware report](https://github.com/krintoxi/sofa/issues/new/choose),
  with the box's **Send a report** code if it's a box. Testers for a Pi 4, a Pi 5, a Fire TV stick, a Roku, an Android
  phone as the box's remote, and Linux as a daily server are the ones most needed.
- Fixes and improvements are welcome under [CONTRIBUTING.md](../CONTRIBUTING.md); open an issue first for anything
  bigger than a fix.
