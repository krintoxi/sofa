# Sofa: what's new

Sofa's own version is in `sofa/__init__.py` and on **Server → Updates**. Sofa Box OS, the Raspberry Pi TV box,
has its own numbers and list: [deploy/sofa-box/CHANGES.md](deploy/sofa-box/CHANGES.md).

A change to Sofa's code (`sofa/`, `client/`, `sofa.py`) gets a new version: raise `__version__`, add a section
here, then `python3 tools/sofa-version.py` (a test checks it was done).

## 1.2.0 (2026-11-03)

Everything since 1.1.0 (2026-10-30); the version number hadn't moved with it.

- **Open to the world, safely.** HTTPS built in: a free Let's Encrypt certificate for your own domain or a
  free DuckDNS name (checked over DNS, so only port 443 needs opening), the router asked to open its ports
  (UPnP), and **Check from outside** with plain-words reasons when it doesn't work (no DNS record yet,
  carrier-grade NAT, a second router, a wrong certificate). Guide: [docs/remote-access.md](docs/remote-access.md).
- **Safer sign-ins and connections.** Wrong passwords and PINs limited per address and per account,
  remembered across restarts; requests from other sites refused (Origin); the real visitor taken from a
  proxy's last `X-Forwarded-For`; connections capped; upload limits; files moved so a crash never leaves a
  half copy.
- **People:** visitors can ask for an account on the sign-in page; nobody gets in until an admin lets them
  in (or in as Kids).
- **Public library:** share titles with a link; visitors see only those, from anywhere.
- **USB drives on a Sofa Box** join the box's Sofa by themselves, sorted the way the Inbox sorts, with
  links: nothing on the drive is moved, renamed or converted. Episodes named with the folder's initials
  (`BB.S01E01` in `Breaking Bad/`) join that show, in the Inbox too.
- **TVs:** a Fire TV app, a Roku channel (`/roku.zip`), Sofa Boxes (Raspberry Pi), and a focus highlight
  you can see from the sofa; converted video plays without stop-skip-stop on slow devices.
- **Make it yours:** accent colours, animations, a loading screen, Arrange Home; the Street look by default.
- **Phones like an app:** bottom tabs, an install prompt; guests can send to the TV.
- **Watching:** surround sound, Blu-ray/DVD subtitles, two viewers, AirPlay; the computer kept awake while
  Sofa runs.
- **Previews have sound.** The banner on Home, the cards' previews and a title's short trailer used to be
  silent clips, so the speaker button had nothing to turn on. Clips are made again, with the video's sound
  (stereo, each moment fading in and out); a video without sound gets a clip without it.
- **Live TV with a remote.** The channel in focus now shows it (the TV's ring, like posters); it used to show
  nothing, so the remote seemed not to work. On TVs the page says how it works. On a Sofa Box, channels play
  in the box's own player (its video chip), and up and down change the channel.
- **A video the device's player can't start plays in the page, just that one;** the next one tries the
  device's player again (it used to stay on the page's player until the page reloaded).
- **Moving a show can't put it in Adult by accident.** The Move dialog used to open with Adult already chosen
  and a free-text category: one press of Move it (or a stray key in that box) put a show in Adult under an
  odd name. Now nothing is chosen until you choose, and categories are picked from a list (a new one is
  typed on purpose, under Another…).
- **Server → Updates** says which commit runs and when it was made, and which Sofa Box OS this Sofa hands
  to boxes; `tools/update.sh` records the commit it installed.

## 1.1.0 (2026-10-30)

Ready for apps: sign in with your phone, discovery on the network, the API ([docs/api.md](docs/api.md)), and tests.
