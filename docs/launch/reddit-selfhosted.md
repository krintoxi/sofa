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

**Ask feedback on:** the one-line install on Linux; the Inbox's naming on real file names; what a Pi 4, a Pi 5, a
Fire TV stick or a Roku actually do; whether the comparison page is fair.

---

**Sofa: a small self-hosted media server for a household, not a homelab (Mac or Linux, Python + ffmpeg, no account anywhere). Source-available.**

I've been building Sofa for my own house and it's at the point where I'd like strangers to break it. It's source-available (PolyForm Noncommercial), free to run and change at home; more on that at the end.

The idea: you drop files in a folder and they come out named, filed and with posters, and every TV, phone and laptop in the house gets a streaming-service-looking library of your own stuff. It runs on an old Mac or a Linux box with Python and ffmpeg and nothing else to install (one line in Terminal), and there's no account with me or anyone.

What it does that I haven't seen done quite this way:
- an Inbox that files download-style names (`the.show.s01e01.1080p.mkv` → The Show, Season 1, Episode 1), attaches subtitles and posters that came along, and never deletes anything;
- the TV signs in by showing a code you approve on your phone; your phone is then the remote for any screen;
- profiles, Kids profiles (family titles only), 4-digit PINs, guests by QR code on your Wi-Fi;
- Skip Intro / Recap / Credits worked out from chapters or by listening to neighbouring episodes;
- remote access built in: your own domain or a free DuckDNS name, a Let's Encrypt certificate it gets and renews, UPnP, a check from outside; or Tailscale;
- a share link that gives friends a view-only copy with just the titles you picked;
- a "Work offline" switch and a list of everything that touches the internet, each with its own switch.

There's also Sofa Box OS, a Raspberry Pi card that turns a Pi into a TV box with Sofa built in, the streaming apps, games and your phone as the remote. That part is beta: it has run on exactly one Pi 3 B+, mine.

Honest limits: Mac, Linux or Docker (the image is new and has run on one Linux VM so far), no native Windows, no hardware transcoding on Linux. No app in any TV store: on a TV you use its browser, sideload my Fire TV app or Roku channel (built by CI, never run on a real device by anyone who wrote it down), or use the Pi box. It's weeks old and made by one person, with about 400 automated tests doing the rest.

The licence: PolyForm Noncommercial 1.0.0. Free to run, read, change and share at home; selling it, or boxes with it, needs a licence from me. That isn't open source by the OSI definition and I'm not going to pretend otherwise; I chose it so I can sell pre-built boxes without someone else selling "Sofa" boxes first. If that's a dealbreaker, fair enough, and Jellyfin is excellent.

What I'd love: someone to run the one-line install on Linux and tell me where it breaks; anyone with a Pi 4 or 5, a Fire TV stick or a Roku to try the beta parts; and opinions on the comparison page I wrote against Jellyfin, Plex, Emby and Kodi, which tries to be fair.

GitHub: https://github.com/krintoxi/sofa (the README has a 30-second demo). What works today, with the evidence for each line: docs/capabilities.md. What's missing: docs/roadmap.md.
