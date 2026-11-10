# Show HN

**Gate:** not before the owner has tested a card on the Pi and marked it stable, and not before the Fire TV app and the
Roku channel have each run once on a real device (see [checklist.md](checklist.md)). The Sofa Server can go first with
the box called beta.

**HN's own rules** (news.ycombinator.com/showhn.html, read 2026-11-10): "The project must be something you've worked
on personally and which you're around to discuss." "If your work isn't ready for users to try out, please don't do a
Show HN." "Please don't ask friends to upvote or comment." "Share something that is deeply personal and interesting to
you. Explain how and why."

**When:** Tuesday to Thursday, 8 to 10 am US Eastern. Stay at the keyboard for six hours. Answer the licence
question once, calmly, and link the comparison. **Who posts:** the owner, from their own account.

## Title (under 80 characters; pick one)

- `Show HN: Sofa – a home media server in Python's stdlib and ffmpeg, plus a Pi TV box` (79)
- `Show HN: Sofa – drop files in a folder, get your own streaming service at home` (77)

## First comment

Sofa is a self-hosted media server I built for my family. It's Python's standard library and ffmpeg, nothing else: no framework, no database server, no build step for the web app, one process. It's source-available (PolyForm Noncommercial), free at home; I'll come back to that.

Why it exists: I wanted my kids to find their cartoons on the TV without me naming files for an hour first, and I didn't want an account with a company in the middle of my living room. Jellyfin is excellent; every part of it was bigger than my house needed.

How it's built, the parts I think are interesting:
- The Inbox: a folder watcher that turns scene-release names, anime names, daily shows by date and camera files into a tidy library (`sofa/naming.py`, about 60 tests of ugly names). Nothing is ever deleted.
- Skip Intro without a service: chapters when the file has them, otherwise chromaprint fingerprints of neighbouring episodes to find the shared stretch.
- Playback: MP4 served as it is; anything else repackaged or transcoded as it plays, and converted in the background so it's instant next time; hardware encoding on Macs after Sofa times the encoders on that machine (some old Macs' encoders draw lines; it checks).
- TV sign-in: the TV shows a code, your phone approves it; the same pairing gives the Fire TV app and the Roku channel their tokens. Your phone is then the remote.
- Remote access built in: ACME against Let's Encrypt (tested in CI against Pebble), DuckDNS, UPnP, an outside check; over the internet it answers only HTTPS and only signed in.
- Sofa Box OS: a Raspberry Pi image that's a whole TV box. One Chromium in cage with every app as a tab, steered over the DevTools protocol by a Python agent; mpv for video with its own Lua OSD; the phone remote is a page the box serves; a stable and a testing update channel.

The licence: PolyForm Noncommercial 1.0.0, not an OSI licence. Free to use, read, change and share for noncommercial purposes; I keep the right to sell boxes with it. Versions before 1.5.4 are MIT.

What's untested, so nobody is surprised: Mac, Linux or Docker (the image has run on one Linux VM; no native Windows; no hardware transcoding on Linux); no app in any TV store (sideload, or the box); the box has run on one Pi 3 B+, mine; the Fire TV app and the Roku channel are built by CI and <STATE: run on a real device on DATE / not yet>; the DRM apps on the box <STATE>. The whole list, with what the evidence is for each line: docs/capabilities.md. A comparison with Jellyfin, Plex, Emby and Kodi that tries to be fair: docs/compare.md.

https://github.com/krintoxi/sofa
