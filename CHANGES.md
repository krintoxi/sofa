# Sofa: what's new

Sofa's own version is in `sofa/__init__.py` and on **Server → Updates**. Sofa Box OS, the Raspberry Pi TV box,
has its own numbers and list: [deploy/sofa-box/CHANGES.md](deploy/sofa-box/CHANGES.md).

A change to Sofa's code (`sofa/`, `client/`, `sofa.py`) gets a new version: raise `__version__`, add a section
here, then `python3 tools/sofa-version.py` (a test checks it was done).

## 1.5.4 (2026-11-10)

- **Licence: PolyForm Noncommercial 1.0.0** (`LICENSE`), copyright EdgeVenture. Sofa stays open to read, use, change
  and share for any noncommercial purpose; selling it, or boxes and services built on it, needs EdgeVenture's licence.
  Versions before this one stay MIT. New at the root: `NOTICE` (the bundled parts and their licences), `TRADEMARKS.md`
  (the names and logos, and what a fork must do) and `CONTRIBUTING.md` (the contributor agreement). An update
  carries `NOTICE` and `TRADEMARKS.md` along with `LICENSE`.

## 1.5.3 (2026-11-10)

- **Quicker on a Sofa box on a Raspberry Pi 3** (the box's light look). Each row of posters is a layer of its own the
  graphics chip slides, instead of being drawn again for each step of its glide to the card in focus. The banner's
  picture stands still: its slow zoom ran for as long as the home page was open, a new frame 60 times a second (the
  banner still changes title). An episode's picture in focus grows at once.
- A row's arrows (for a mouse or a touchpad) are checked only for the row that scrolled, and touched only when they
  change: every row on the page was looked at, at each step of a row's glide (every device).

## 1.5.2 (2026-11-10)

- **Big skips on a Sofa box.** In a video Sofa converts for the box (HEVC on a Raspberry Pi 3, say), a skip further
  than Sofa has converted so far, or back before where it started, has Sofa convert it again from there, as Sofa's
  own player does in the browser. The page tells the box how it asked Sofa for the video, so the box can ask the same
  from another place (Sofa Box OS 1.1.54 and later).

## 1.5.1 (2026-11-10)

- **On a Sofa box, every video plays in the box's player, and the TV answers at once.**
  - Pressing Play or Resume shows the box player's start card straight away (the title, where it resumes from),
    in the same place as the player's own, so nothing else shows before the picture.
  - When the box's player can't open a video, the card says why. The page's own player no longer stands in on a
    box: it's a desktop player near the screen's edges, played by the browser instead of the box's player.
  - Asking the box to play no longer freezes the page (it was a request that waited for mpv to start).
  - `#/play/<id>` plays a title at once over its own page: the box's Home uses it for Resume, and Back from that
    video goes back to the box's Home.
- **Previews** (a few seconds of a title you stop on) have a switch in Look and feel. On a Raspberry Pi 3 box they
  start off, like the trailers and the banner: each is a video the browser plays and draws into the page itself.

## 1.5.0 (2026-11-08)

- **Retro TV's decades are off unless you turn them on.**
  - The 2009–2012, 2000s, 90s, 80s, 70s, 60s and 50s tabs are recordings people made of TV as it aired,
    commercials and all, and nobody has cleared their rights.
  - They now start switched off. An admin can turn them on for their own household (Server → Live TV → The
    decades, as they aired), and the public library's visitors never get them.
  - On a Sofa set up before, they go off too, until someone turns them back on.
  - Classic Cinema stays on, with a switch of its own beside it.
- **Away from home, Live TV never comes through Sofa.**
  - 1.4.6 played a channel straight from where it's streamed when it could, and through Sofa when it couldn't.
    Through Sofa, a channel goes out on the home's connection, past its own country limits, and on a public Sofa
    behind a tunnel it makes Sofa the broadcaster.
  - Now Sofa passes a channel on only at home. Away from home, and for every visitor, a channel plays straight
    from where it's streamed, or it isn't listed.
  - A channel that won't play that way on a device is left out of the list on that device from then on.
- **The public library shares only the channel lists you pick.**
  - "Live TV too" used to share every list. Now each list has its own **Visitors** switch (Server → Live TV).
  - Classic Cinema is shared only with **Classic Cinema too** (Sharing).
  - Visitors no longer see the lists' names or addresses.
  - Visitors can now open Live TV's guide and Classic Cinema's channels when they're shared; before, they got a
    "Sign in" error.
- **Channels that ask for a made-up browser name are hidden.** Some lists give a channel a browser name or a page to
  pretend to come from, to get past a site that wants its stream watched only on its own pages. Those channels are
  left out unless an admin allows them (Server → Live TV).
- **Visitors get an About page:** what's here, privacy, copyright, and where to write. Set the address in Sharing →
  "Copyright notices go to". The page is linked from the footer and from More.
- **Server → Live TV** says plainly what the community channel lists are, and has Retro TV's switches.

## 1.4.6 (2026-11-08)

- **Games, in the browser.** Off a Sofa Box, Sofa has a **Games** page with the box's own games (Gloamwell,
  Ironmaw, Tidewing and the rest). They play full screen with a keyboard or a game controller. Esc that the game
  doesn't use, or the controller's Xbox/PS button, brings you back. On a Sofa Box the Sofa app leaves them out,
  because the box's home screen has them. A public library can share them: **Games too** in Server → Sharing.
- **A Sofa Box page.** Off a box, the menu has a highlighted **Sofa Box**, and phones have it under More. It says
  what the box is, what you need and the three steps, and links to the download.
- **A tunnel Sofa wasn't told about can't pass for home.** `cloudflared`, nginx or Caddy on the same computer brings
  the internet's requests from 127.0.0.1. Until `trust_proxy` is on, Sofa took them for this computer, which counts
  as home. Now a request that carries a proxy's headers gets what the internet gets, and the Activity log says how
  to tell Sofa about the proxy. With `trust_proxy` on, Cloudflare's `CF-Connecting-IP` names the visitor, and
  everyone arriving through the proxy no longer shares one address's connection limit.
- **Away from home, Live TV comes straight from the channel** where the channel allows it (https, no headers of
  its own, not a TV tuner at home). The video no longer uses your home upload, or a tunnel that mustn't carry
  video. If it doesn't play that way on your device, the channel comes through Sofa as before.
- **Visitors' More page** no longer offers Music, which they can't open, or Live TV when it isn't shared.

## 1.4.5 (2026-11-08)

- **On a Sofa Box, the menu down the left feels like a TV app's.**
  - It opens as a solid panel sliding over the page, which dims behind it. It used to grow wider frame by frame,
    which a Pi 3 can't draw smoothly, and faded to see-through over the page.
  - Left from the page goes to the page you're on in the menu, not to whatever item is level with you. Right goes
    back to exactly where you were.
  - Choosing a page takes you into it, and the menu closes. Before, it stayed open over the new page.
  - The page you're on is marked in the accent colour, and who's watching shows at the bottom.
- **The remote's arrows are quicker on big pages.** Finding the next thing to move to asked every card on the page
  for its style on every press; now only the nearest few are asked.

## 1.4.4 (2026-11-08)

- **Updates bring the Roku channel.** Neither the Update button nor `tools/update.sh` brought the `roku/` folder, so
  a Sofa kept up to date by its updates could have no Roku channel, or an old one. On such a Sofa, the Roku
  download (`/roku.zip`, Server → Apps) dropped the connection instead of answering. Now updates bring it, a Sofa
  without it says so, and a test checks that both kinds of update replace the same parts.

## 1.4.3 (2026-11-08)

- **Live TV that ffmpeg plays can't be steered home either.** Two kinds of channel are read by ffmpeg itself, not
  by Sofa: a TV's live channel over DLNA, and a feed that isn't HLS (a raw MPEG-TS stream, repackaged for the
  browser). ffmpeg looked names up and connected by itself, so the checks that keep Live TV off the home network
  didn't cover what it fetched. A channel's playlist, or a redirect, naming a router's page or this computer was
  followed. Now ffmpeg reaches a channel from the internet only through a relay inside Sofa, which connects to
  internet addresses only, and it may open only web addresses. A TV tuner's channels at home play as before. The
  User-Agent and Referer a channel list gives a channel now reach ffmpeg too.
- **On a TV, a link to another site shows a QR code to open it on your phone**, instead of leaving Sofa. This
  covers the EdgeVenture.uk credit, GitHub, and where to get a key. A TV has no browser to come back from.
- **The Fire TV app stays on Sofa's pages.** A page that tries to send it elsewhere gets the same QR code. Picking
  another Sofa in Servers opens it, and the app keeps that one. Fire OS 5 (the 2015 sticks) now follows the same
  rules; it asks the app through an older Android call that the app didn't answer.
- **Roku channel 1.1:**
  - A Roku whose sign-in ran out, or was signed out on the Server page, said "Sofa said no (200)" and stayed
    there. Now it shows a new code to approve.
  - Picking the Sofa it's signed in to (after Sofa was off when the Roku started) goes straight back in, with no
    new code.
  - Sofa's own messages reach the screen ("The server is busy converting…", "Signing in with a phone works at
    home…"), instead of "Sofa said no (503)" or "Getting a code…" for ever.
  - A Sofa at an `https://` address works.
  - A file the Roku turns out not to play as it is gets converted instead, from where it stopped. When a video
    stops with an error, the reason stays on the screen.
  - Continue watching has one row per show, and the next episode once one is finished. A show opens on the episode
    to watch.
  - Finding Sofa doesn't wait on an address that doesn't answer (3 seconds at most).

## 1.4.2 (2026-11-08)

- **Live TV's era tabs work.** Choosing an era (clicking 90s, or OK on it with a remote) did nothing since 1.4.0:
  the guide stayed on the 2000s. A test now checks that every button the page's click handlers act on reaches
  them.
- **An update can't leave Sofa broken.** The Update button (and `tools/update.sh`) deleted the old code, then
  copied the new; a power cut in those seconds left no code at all, and Sofa couldn't start, or go back. Now the
  new version is copied beside the old one, checked there, and switched in by renames, and the old one is let go
  only once the new one has passed its test start. Cut off at any point, Sofa's next start puts the version
  before back, whole. Code that doesn't compile never touches the version you have.
- **Server → Updates says which commit Sofa runs**, even when GitHub didn't answer the question: the download
  itself says. (An update that didn't work used to record the new commit anyway.)
- **Live TV opens on what you're looking at.** On a new Sofa, Retro TV's channels were fetched one at a time, ten
  seconds apart, so an era could say "Getting this channel ready…" for ten minutes. Now the era you open is
  fetched first, without the pauses (the 90s' six channels in about a minute), and the guide looks again every few
  seconds until they're there. The warm-up goes in the dial's order, so the 2000s, where Live TV opens, come first.
- **A year that's in a programme's name isn't said twice** ("Toonami from 2001", not "Toonami from 2001 2001").
- **The guide is ten times quicker to make** (16 ms to 1.6 ms on a Mac with 47 channels): programme names and each
  channel's films are kept in memory, and read again only when they change.
- **Live TV can't be steered home by a name that changes its answer.** The check that a channel from the internet
  doesn't lead into the home network looked a name up, then connected, and a name could answer differently the
  second time. Now the connection goes to an address that was checked.
- **With previews off, the banner doesn't ask again** for a clip that won't be made (it asked at every turn).

## 1.4.1 (2026-11-08)

- **Retro TV and Classic Cinema favourites are kept.** Their ★ went nowhere (only a channel list's channels could be
  favourites), so the star lit up and was gone after a reload.
- **In Live TV's guide, Right at the end of a row stays there**, instead of jumping up to the eras.
- **A channel from the internet can't send Sofa into the home network.** A channel list's playlist (or a redirect)
  naming a router's page, this computer, or a Sofa box's own controls isn't fetched any more; a list at home (a TV
  tuner's) still is.
- **A power cut can't stop Sofa starting.** Settings are on the disk before they're in place, and a config.json
  that was cut off half way (from before) is kept aside instead of stopping Sofa at every start. Channel lists are
  saved whole or not at all.
- **Quicker first answers on a Raspberry Pi.** The database's tables were made again for every new connection to
  the server; now once.
- **Watch positions are numbers.** One that wasn't ("NaN") was kept, and that profile's places couldn't be read.
- Fixing an Adult title's details takes an admin who may see the Adult section, as everything else about it does.
- **Fire TV app:** Sofa's sign-in goes only to Sofa, never with a video from another address, and only Sofa's own
  pages can start the player.

## 1.4.0 (2026-11-08)

- **Live TV by era.** Live TV opens on tabs across the top: **Live now** (today's channels, from the channel
  lists), **2009–2012**, the **2000s**, the **90s**, **80s**, **70s**, **60s** and **50s**, **Classic Cinema**,
  and your **Favorites**. An era shows its guide; Live now shows today's channels by group, with a search.
- **Seventeen more channels (39 in all).** 2009–2012: On Air, Kids TV (Cartoon Network, Nickelodeon, Disney XD,
  PBS Kids), Music & Games (Fuse, the countdowns, X-Play) and Commercial Breaks. The 90s: Kids TV, Saturday
  Mornings, On Air, Music TV (MTV, VH1) and Commercial Breaks. The 80s: Saturday Mornings, On Air, Music TV
  (MTV's first decade, Friday Night Videos) and Commercial Breaks. The 2000s, 70s, 60s and 50s: Commercial
  Breaks. The dial keeps an era together: the 2000s are 2 to 10, 2009–2012 are 11 to 14, Classic Cinema 20 to
  28, the 90s from 90, the 80s from 80, the 70s 70, the 60s 60 and the 50s 50.
- **Programmes by their own names.** A tape's title says what's on the tape ("Noggin VHS Recording Clip -
  February 18, 2004"); the guide, the player and the box's banner say **Noggin**, aired **Feb 18, 2004**.
- **The eras' TV is in English** (the tapes come from everywhere), with **no cigarette ads** (they were on TV
  until 1971) and no tapes marked adult.
- **The guide on a TV** has the room: the eras sit beside Live TV's name, the help line is gone (the keys are
  under what's on), and six channels show at once on a 720p screen.
- **On a Sofa box**, Home shows more at once: six or seven posters across with the next row in view, and the
  rows' arrows only for the phone's touchpad pointer.

## 1.3.0 (2026-11-08)

- **Live TV has a guide.** Retro TV and Classic Cinema by the clock, as on a TV: each channel
  with its number and the next two hours; above them, what's on the channel in focus, with a picture of it (a
  muted preview of the channel on a computer), how long is left and what's next. Up and down go through the
  channels at the same time of day, left and right through a channel's programmes, OK watches; typing a
  channel's number goes straight to it, and **Flip** tunes to one at random. Live TV opens on Retro TV until
  you have favourites. Built to be light: a Raspberry Pi 3 draws it.
- **Five more 2000s channels, whole tapes as they aired:** 00s Saturday Mornings (Kids' WB, Fox Box, 4Kids TV,
  ABC), 00s Action Toons (Toonami, Cartoon Network Fridays), 00s Music TV (TRL, 106 & Park, MTV Hits), 00s Game
  TV (X-Play, G4, TechTV) and 00s Infomercials. The 2000s are channels 2 to 9, the older decades 10 to 14, and
  the film channels, now **Classic Cinema**, 20 to 28.
- Channels have variety: three of one series at most (not twenty parts of one upload). The family filter knows
  a few more words.
- **A tape that won't play is skipped:** the next one plays.
- **On a Sofa Box, Sofa opens on something to watch.** At home it goes straight in as Guest (when the house
  has guests on): the library, Live TV and Retro TV, no sign-in first. Home then offers **Make this TV yours**:
  sign in with your phone, no typing ("Not now" puts it away for three days). Signing out (or Leave) shows
  the sign-in screen, which has Watch as a guest too.
- On a TV, **Use a name and password instead** stays on the password form (it used to go back to the code).
- Pictures decode off to the side (banners, posters, logos): the remote never waits for one.
- **"Something went wrong (501)"** on the request after one Sofa had turned down (a refused sign-in, then the
  next try): the turned-down request's body was left on the connection. Fixed.

## 1.2.5 (2026-11-07)

- **Retro TV channels tune in.** Since they came (1.2.2), choosing one said it wasn't available: Sofa's address
  for what's on a channel took only letters, and every Retro TV channel has digits in its name (Retro TV: 60s,
  00s Kids TV…). The Internet Archive's film channels weren't affected.

## 1.2.4 (2026-11-07)

- **Every archive channel says what's on.** Sofa fetches each channel's films in the background, one after
  another; an item whose title the archive gives as a list stopped that at the third channel, so only Classic
  Movies and Film Noir were ready (the others fetched theirs when tuned to, and their cards said nothing). Those
  titles are read (and filtered) like the others now, and a channel that fails waits for the next round without
  stopping the rest.

## 1.2.3 (2026-11-07)

- **Retro TV puts the 2000s first, with three channels:** Retro TV: 00s (shows with the decade's commercials),
  **00s Kids TV** (whole recorded kids' TV, Nick Jr., Cartoon Network, Noggin, Disney, with the commercials they
  went out with) and **00s On Air** (recorded broadcasts with their breaks: King of the Hill and Futurama in 2002,
  Comedy Central in 2005, award shows…). Retro TV has its own group in Live TV.

## 1.2.2 (2026-11-04)

- **Retro TV in Live TV.** A channel for each decade from the 50s to the 00s: its TV shows as they went out,
  with two or three of that decade's commercials between them (the Internet Archive's classic TV, its TV
  commercials, and from the 80s on, off-air recordings with their own breaks), on the clock like the other
  archive channels. The card says what's on ("Commercials, then Mister Ed").
- **Live TV is quicker on small boxes.** The list draws 60 channels and adds more as you get near the end
  (it used to draw 600 at once, a lot for a Raspberry Pi 3). Archive channels say what's on now.
- Film Noir keeps to its classic years (1940 to 1965); a channel whose search changes fetches its films again.
- The family filter on archive channels knows a few more words.

## 1.2.1 (2026-11-04)

- **Live TV has Internet Archive channels:** Classic Movies, Film Noir, Sci-Fi & Horror, Comedy, Westerns,
  Silent Films, Cartoons, Classic TV and Documentaries, free films from archive.org, each played like a TV
  channel: thirty films on a loop, on the clock, so tuning in lands in the middle of what's on and the next film
  follows. Only films with one playable video and a length, and nothing that doesn't belong on a family TV
  (the archive's films include exploitation pictures). The films come straight from archive.org to the screen.

- **On a Sofa Box, Sofa looks like a TV app.** The menu is a rail down the left edge: icons, opening into their
  names when the remote goes into it (Left), with Search at the top and who's watching at the bottom; every
  section is there (Music, Live TV, Server too). No scroll bars, and the row in focus glides to the middle of
  the screen.

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
