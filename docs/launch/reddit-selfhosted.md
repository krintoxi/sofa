# r/selfhosted: the project introduction

**Where it goes:** r/selfhosted's weekly **New Project Megathread**, as a comment, not a standalone post. The
megathread's own text (u/AutoModerator, "New Project Megathread - Week of 14 May 2026", read from a 2026-05-16
snapshot): "This weekly thread is the new official home for sharing your new projects (younger than three months)
with the community", "all new projects can only be posted here", "Standalone new project posts will be removed",
"You can post here ANY day of the week". Sofa's repository dates from October 2026, so it is a new project there until
late January 2027. Read the subreddit's sidebar on the day; the moderators revisited the rules in April 2026.

**Who posts:** the owner, from their own account. This file is a draft. Nothing in this repository posts anything.

**Attach:** `docs/images/demo.gif` (or the three screenshots `docs/images/home.jpg`, `docs/images/show.jpg`,
`docs/images/box-home.jpg` where a comment can't carry a GIF).

**Ask feedback on:** a week of Linux or Docker as a daily server; the Inbox's naming on real file names; what a Pi 4, a
Pi 5, a Fire TV stick, a Roku or a Windows PC actually do; whether the comparison page is fair.

---

**Sofa: a small self-hosted media server for a household, not a homelab (Mac, Windows, Linux or Docker; no account anywhere). Source-available.**

I make Sofa, and it's at the point where I'd like strangers to break it. It's source-available (PolyForm Noncommercial), free to run and change at home; more on that at the end.

The idea: you drop files in a folder and they come out named, filed and with posters, and every TV, phone and laptop in the house gets a library of your own stuff that looks like a streaming service. It's one process, Python's standard library and ffmpeg, and there's no account with me or anyone.

What it does that I haven't seen done quite this way:
- an Inbox that files download-style names (`the.show.s01e01.1080p.mkv` → The Show, Season 1, Episode 1), attaches the subtitles and posters that came along, and never deletes anything;
- the TV signs in by showing a code you approve on your phone; the phone is then the remote for any screen;
- profiles, Kids profiles (family titles only), 4-digit PINs, guests by QR code on your Wi-Fi;
- Skip Intro, Recap and Credits worked out from chapters, or by comparing the sound of neighbouring episodes;
- remote access built in: your own domain or a free DuckDNS name, a Let's Encrypt certificate it gets and renews, UPnP, a check from outside; or Tailscale;
- a share link that gives friends a view-only copy with just the titles you picked;
- a "Work offline" switch, and a list of everything that touches the internet, each with its own switch.

There's also Sofa Box OS: a Raspberry Pi card (or a USB stick for a PC) that makes a TV box with Sofa built in, your streaming apps, fourteen small games and your phone as the remote. That part is beta: it has run on exactly one Pi 3 B+, mine.

Install: one line on a Mac or Linux, `docker compose up -d` (amd64 and arm64, host networking), or an installer on Windows.

Honest limits: hardware transcoding on Linux and Windows (NVENC, Quick Sync, VA-API, AMF) is in the code and tested against a stand-in, and has run on no real NVIDIA, Intel or AMD chip yet; it falls back to x264 when an encoder fails its own test. Macs use VideoToolbox. No app in any TV store: on a TV you use its browser, sideload the Fire TV app or the Roku channel (both built by CI, and nobody has written down a run on a real device yet), or use the Pi box. Docker has run on one Linux VM and the Windows installer only on GitHub's Windows machines. The repo is a month old with one maintainer, and about 600 automated tests run on every push.

The licence: PolyForm Noncommercial 1.0.0. Free to run, read, change and share at home; selling it, or boxes with it, needs a licence from me. That isn't open source by the OSI definition and I'm not going to pretend otherwise; I chose it so I can sell pre-built boxes without someone else selling "Sofa" boxes first. If that's a dealbreaker, fair enough, and Jellyfin is excellent.

What I'd love: someone to run it on Linux or in Docker for a week and tell me where it breaks; anyone with a Pi 4 or 5, a Fire TV stick, a Roku or a Windows PC to try the parts I can't; and opinions on the comparison with Jellyfin, Plex, Emby and Kodi in the repo, which tries to be fair.

GitHub: https://github.com/krintoxi/sofa (the README opens with a 40-second demo and the install lines). What works today, with the evidence for each line: docs/capabilities.md. What's missing: docs/roadmap.md.
