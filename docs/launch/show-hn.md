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

Sofa is a self-hosted media server for a household. It's Python's standard library and ffmpeg, nothing else: no framework, no database server, no build step for the web app, one process. It's source-available (PolyForm Noncommercial), free at home; I'll come back to that.

Why it exists: `<YOUR OWN REASON, TWO OR THREE SENTENCES. HN's Show HN page asks for "how and why"; only what's true for you.>`

How it's built, the parts I think are interesting:
- The Inbox: a folder watcher that turns scene-release names, anime names, daily shows by date and camera files into a tidy library (`sofa/naming.py`, with a table of ugly names as its tests). Nothing is ever deleted.
- Skip Intro without a service: chapters when the file has them, otherwise chromaprint fingerprints of neighbouring episodes to find the shared stretch.
- Playback: MP4 served as it is; anything else repackaged or transcoded as it plays, and converted in the background so the next play is instant. On a Mac it times the hardware encoder against x264 first, because some old Macs' encoders draw lines across the picture.
- TV sign-in: the TV shows a code, your phone approves it; the same pairing gives the Fire TV app and the Roku channel their tokens. The phone is then the remote.
- Remote access built in: an ACME client against Let's Encrypt (tested in CI against Pebble), DuckDNS, UPnP, a check from outside. Over the internet it answers only HTTPS and only signed in.
- Sofa Box OS: a Raspberry Pi image that's a whole TV box. One Chromium in cage with every app as a tab, steered over the DevTools protocol by a Python agent; mpv for video with its own Lua OSD; the phone remote is a page the box serves.

The licence: PolyForm Noncommercial 1.0.0, not an OSI licence. Free to use, read, change and share for noncommercial purposes; I keep the right to sell boxes with it. Versions before 1.5.4 are MIT.

What's untested, so nobody is surprised: it runs on a Mac, Linux, Windows (an installer; so far only run on GitHub's Windows machines) and in Docker (one Linux VM so far); no hardware transcoding on Linux; no app in any TV store (sideload, or the box); the box has run on one Pi 3 B+, mine; the Fire TV app and the Roku channel `<ran on a real device on DATE / are built by CI and not yet run on a real device>`. Every line of that, with its evidence: docs/capabilities.md. A comparison with Jellyfin, Plex, Emby and Kodi that tries to be fair: docs/compare.md.

https://github.com/krintoxi/sofa
