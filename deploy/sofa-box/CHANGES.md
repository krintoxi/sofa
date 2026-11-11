# Sofa Box OS: what's new

Each version gets its own release on GitHub, "Sofa Box OS X.Y.Z", with its card to download:
<https://github.com/krintoxi/sofa/releases?q=box-os>. The newest card (testing) is always at
<https://github.com/krintoxi/sofa/releases/tag/sofa-box>, and the stable card (tried on a real box) at
<https://github.com/krintoxi/sofa/releases/tag/sofa-box-stable>.

A new version: change the number in `deploy/sofa-box/VERSION`, add a section here, and merge to `main`.
GitHub builds the card and makes the release by itself.

## 1.1.61

The setup, from what a 1.1.60 card did on a real Raspberry Pi 3 B+ (2026-11-11: it set up and worked, "a bit buggy").

- **The phone asks for the Wi-Fi's password in the middle of the screen.** Pick your Wi-Fi in the Setup Assistant and
  a sheet opens over the list, in the middle of what the phone shows with its keyboard up, with the field ready to
  type in. It was a box under the list, at the bottom of the page: on an iPhone that's where the keyboard's bar sits,
  with "Passwords" on it. The field is plain text now and nothing about it says "password" to the phone, so no saved
  passwords and no "Use Strong Password?" come up; what you type shows (Hide covers it), so a slip is seen before
  Join. Curly quotes, long dashes and "…" that a phone's keyboard puts in are put back as typed.
- **After Join, one path.** The same sheet says what happens next: the box is joining, your phone goes back to your
  Wi-Fi, and either the page carries on by itself or one last code on the TV is scanned. A wrong password comes back
  to the phone too, in the sheet, with what was typed there to put right (the page went on saying "the box is
  joining"); the TV keeps saying why once the box's own Wi-Fi is back (it said so for a few seconds only).
- **The TV doesn't lose its place when the box's clock is set right.** A new card's clock starts weeks behind (the
  day its system was made) and is set right when the box is first online: seconds after it joins your Wi-Fi, in the
  middle of the setup, 36 days at once on the Pi. The TV took "joined a moment ago" for "a month ago": the setup's
  last step turned into the plain first code ("scan with your phone's camera, or open … and type …"), and the
  remote's secure address was taken for gone, so the code on the TV could change under the phone's camera. The box
  now keeps its "how long ago" on a clock that never jumps, on the TV's page too, and asks for the remote's secure
  address every 5 seconds just after joining, as it was meant to.
- **After the join the TV says what happened, then what to do, once:** "✓ The box is on <your Wi-Fi>", then "Last
  step: scan this with your phone's camera", then "✓ Your phone is the remote, and the box is online" with all four
  steps ticked. With the Sofa Box service out of reach, the plain code shows after a minute (it was five minutes with
  no code at all).
- **Sofa is looked for as soon as the box is on your Wi-Fi**, and every few seconds for two minutes. By then the
  box had gone down to a look a minute, so Home could open after the setup without the Sofa that was there.
- **The box's own Wi-Fi starts once.** It went up, and three seconds later down and up again with its address
  server (NetworkManager's hotspot command, then two changes that needed a second start), just as the TV showed the
  code to join it. It's made whole, then started; the TV shows its code only once it's up.
- **Short of power: the setup says so**, between Back and Next, as soon as the Pi records it (looked at every 15
  seconds until the setup is done). A weak supply shows in the first minutes, when the Wi-Fi starts sending; Home
  said so only after the setup. A report's first lines now say it in words: what happened, whether it's still
  happening, what to do.

## 1.1.60

- **Sofa Box OS on other hardware** (docs/hardware.md): an old PC or laptop, a mini PC, a virtual machine, another board.
  - `install.sh` tells a Raspberry Pi from the rest (its boot files, its apt archive, its name in the device tree, its
    tools; `SOFA_BOX_HARDWARE=pi|other` by hand). A Pi gets exactly what it got: every new line is inside one block that
    runs only elsewhere, and the card's build is untouched.
  - **Plain Debian 13 (Trixie), x86-64 and arm64:** `other-hardware.sh` adds what Debian has in place of the Pi's parts.
    VA-API decoding for mpv and Chromium (Intel and AMD graphics; `/etc/chromium.d/sofa-box`), Debian's firmware packages
    for a laptop's Wi-Fi, graphics and sound where apt has them, and HDMI-CEC only through a Pulse-Eight USB adapter
    (the CEC service waits for a `/dev/cec` instead of restarting for ever). Debian 13's Chromium dies at its start
    without a `~/.config/chromium/Crash Reports` folder, so the box's user gets one; in a VM Chromium draws with its own
    software renderer. No power or heat note without the Pi's record; About says which system the box is built on.
  - **`sudo sofa-box widevine`** (x86-64): Widevine for the DRM apps from Google Chrome's own package, into where Debian's
    Chromium looks. A chosen step, never part of an image; `sofa-box doctor` says whether it's there, and what the graphics
    chip decodes.
  - **A virtual-machine image** (`tools/build-sofa-box-vm-image.sh`): Debian 13 from Debian's archive, GRUB for UEFI and
    BIOS on one disk, the very same `install.sh --image` as a card; the root grows to the disk, SSH keys are made on each
    machine. GitHub builds it and boots it in QEMU both ways (`.github/workflows/sofa-box-vm.yml`), proving the box's
    helper, Sofa on the box, the TV's screen and the phone remote answer, with the console logs as the run's artifact.
    Nothing is released. The same `.img.xz` written to a USB stick starts a real PC.
  - The hardware guide also assesses other boards (Orange Pi 5 and 3B, ROCK 5 and ZERO 3, Libre Computer, Banana Pi,
    Android TV boxes, NUC-class mini PCs, Macs under UTM) from the vendors' and distributions' documentation, with
    sources and dates, and ends with the capabilities matrix by platform, claiming only what is proven.

## 1.1.59

- **Licence.** Sofa, Sofa Box OS and the box's own games are now under the PolyForm Noncommercial License 1.0.0
  (copyright EdgeVenture): free to use, change and share for noncommercial purposes, at home above all; selling
  boxes or services built on them needs EdgeVenture's licence. Credits and licences (Settings → This box → About)
  says so for the three Sofa entries; every other part on the card keeps its own licence, as before. Cards before
  this one stay under the MIT licence they came with. The names and logos are trademarks (`TRADEMARKS.md`).


## 1.1.58

- **Credits and licences** (Settings → This box → About): every part on the card and every game the box can install,
  with what it does, who makes it, its licence and where its source is. OK on one shows its source as a code to open
  on your phone. The few parts that aren't free software say so: the Pi's start-up firmware, the Wi-Fi and Bluetooth
  firmware, Widevine (for the DRM apps), and AssaultCube's and Sauerbraten's maps, sounds and pictures.
  - It's drawn from one file, `home/credits.json`. The tests check it against every package install.sh puts on a box
    and every game on the list, so nothing new comes in without its licence and source.
- **Sofa Craft, powered by Luanti:** its tile and the credits say what it is (Luanti, with its Minetest Game).
- **AssaultCube and Sauerbraten are never on a card.** Their maps, sounds and pictures are free to play but not free
  software (not for commercial use), so a box installs them only when someone asks for them in Games. A test fails if
  the card's build ever installs them, and the build itself stops if one is on a card. Games no longer calls every
  game open source: those two say their data isn't free software.
- **Your TV's own tracking** (Settings → Help): many smart TVs work out what's on their screen, this box's picture too,
  and send it to their maker ("ACR"). Brand by brand (Samsung, LG, Vizio, Sony, TCL, Hisense, Roku TV, Google TV and
  Fire TV sets): where to turn it off, and the advertising settings next to it, from each maker's own help pages, with
  a code to open them on your phone. Menu names change between models and years, and the page says so.
- **Only what the box can prove:**
  - Sofa Shield keeps known ad and tracker sites out (not every ad: those from the same site as what you watch still
    show).
  - The secure phone remote: what you tap and type isn't kept (the service's log has only the time and address of
    each request).
  - Send a report leaves out what the box plays, cuts web addresses short, and blanks passwords and codes (it used to
    say "no titles", but an app's own error messages go as the app wrote them).
  - The guide and docs/privacy.md: the box keeps no usage statistics and tells no one what you watch but the Sofa you
    play it from; Live TV on a new box starts with Classic Cinema and only the channel lists you add.

## 1.1.57

- **Home answers the remote quicker on a Raspberry Pi 3.** In a test browser set up like a Pi 3's (its light look),
  the presses along Home's rows and down to the next now have the browser draw (raster) about a twelfth of what it
  did, and work out styles about a fifth as often. Effect by effect:
  - **The rows slide on the graphics chip.** A row gliding to the app in focus was drawn again for each step of the
    glide. Now each row is a layer of its own that the graphics chip slides, and a press no longer splits the row
    into new layers around the tile in focus (each drawn again from nothing, twice a press).
  - **App icons at the size Home draws them.** The box keeps each site's own icon, often 512 or 1024 pixels across,
    for a tile 150 pixels wide: the Pi decoded up to fifty times the pixels it showed, and again whenever it drew
    them. The box now makes a copy at the tile's size once (192 pixels; 384 on a 4K TV), and the browser keeps it.
  - **An icon's look is worked out once.** Whether an icon is white on clear (it gets the app's colour behind it)
    was found by reading the whole picture back each time Home showed it, often in the middle of a press, as icons
    arrived while a row scrolled. Now once per icon, when the box is quiet, and remembered.
  - **Nothing moves on a press in the light look.** An app's icon still lifts in the tile in focus, the tabs and
    switches still change, a sheet still opens: at once, instead of over a fifth of a second (each movement was a
    layer made for the moment and dropped after).
  - **The background that never showed isn't drawn** (every board, the same picture on the TV): the page's own
    background is drawn over it. It was a layer the size of the screen for nothing, and on the full look two glows
    moving for ever, a new frame 60 times a second while Home sat still.
  - **The clock** redraws when the minute changes (every 10 s before), and Settings' parts that refresh every 2.5 s
    are made only when they're on the screen, the phone's codes once.
- **Sofa's pages on a Pi 3** (with Sofa 1.5.3): the rows of posters slide the same way, and the banner's slow zoom no
  longer keeps the graphics chip busy for as long as Sofa's home is open.
- **A report says how quickly each page answers**, page by page: Home, Settings, the App Store, Sofa's own pages. For
  each, how many presses answered within 0.05, 0.1 and 0.25 s, the slowest, and for the slow ones where the time
  went: waiting for the page to be free, the page's own code for the key, or drawing the answer. It also says whether
  the browser draws with the Pi's graphics chip. The measure no longer disappears when Home loads again.

## 1.1.56

- **Raspberry Pi Imager's settings no longer stop the box.** A user name and password typed into Imager's OS
  customisation (Imager 1.8 and 1.9 offer it for a card picked with Use custom; Imager 2 doesn't) left the TV on the
  boot screen, or showing a login, instead of Sofa. Raspberry Pi OS makes that user with its own tools at the first
  start, and they end by setting the box to start into a text console and putting a login on the TV's screen, which
  stops Sofa there. Now the box puts both back as soon as they're done, at the first start and at every start after,
  and Sofa comes up on the TV: the setup, as on a card written with no settings.
  - Imager's other settings are kept: your Wi-Fi (the box joins it by itself, so the setup's first code is for your
    home network), SSH, the time zone, the keyboard and the box's name on the network.
  - Imager's name for the box rewrote the list of names Sofa Shield keeps out, and Shield was off without saying so.
    The box keeps a copy and puts it back.
  - The first start's own work from Imager's settings (fetching package lists) gets what the TV leaves of the
    processor.
  - Reset to how it came forgets the Wi-Fi Imager gave it too.
  - `sofa-box doctor` says if the box starts into anything but the TV's screen, and the card's report lists Raspberry Pi
    OS's first-start tools.
- **Home says when the box is short of power, or hot.** The Pi keeps a record of both, and the box only said so in its
  reports (and in a two-second message). Now Home has a calm note: "The box is short of power" (it can freeze or
  restart: use its official power supply, plugged into the wall, with a short cable) or "The box got hot and slowed
  itself down" (leave air around it). It shows once a start, until you leave Home, and never takes the remote's first
  press. **Settings → Help** says it all along, or that power and heat have been fine since the box started.
- **The right address under the setup's code.** Beside the code to scan, the TV said "or open <address> and type
  <code>". With the secure phone remote on (the default), that address was the Sofa Box service's, which won't take a
  typed code ("Away from home, scan the code on the TV"). Now it's the box's own address at home, and when the box
  doesn't know that one, the TV just asks you to scan.

## 1.1.55

- **Stable and testing.** A box now gets its updates from one of two channels (Settings → Software).
  **Stable**, the default: only a version that has been tried on a real box, the one named in
  `deploy/sofa-box/STABLE`. **Testing**: main's newest, as soon as it's merged, which is what every box got until
  now. A box on Stable is offered the stable version only, and only when it's newer than its own.
  - **Update the box installs exactly the version it offers.** Before, it ran main's installer, which took
    whatever was newest on main that minute. Now a box on Stable gets the files of the stable version's own
    release (its tag, `box-os-vX.Y.Z`), installed by that version's own installer; a box on Testing gets main's
    newest, as before. Neither ever goes back to an older version than it has.
  - Software says which version this box has (the stable one, or a testing one), and what each channel has on
    GitHub now.
  - No version is marked stable yet: until the owner marks one, a box on Stable is offered nothing.
  - A box older than 1.1.55 doesn't know the channels: its next update still takes main's newest, and from then on
    it follows Stable. A new box set up with the one-line install gets the stable version.
- **Update by itself every week** (Settings → Software; off unless you switch it on, and Stable only): once a week,
  at night (3 to 5 o'clock where the box is), with nothing playing and no game open, the box installs a new
  stable version if there is one. One that didn't take (no internet, say) is tried again the next night, three
  nights at most.
- **The releases page says which card is which.** The newest card (`sofa-box`, the same link as ever) is the
  **testing** card now. The **stable** card is at <https://github.com/krintoxi/sofa/releases/tag/sofa-box-stable>
  (its file always `sofa-box-stable.img.xz`), copied from the stable version's own release, which is titled
  "(stable)". Marking a version stable is a one-line change to `deploy/sofa-box/STABLE` (the guide's "Stable and
  testing"); only a numbered card can be stable.
- **The same system on a card from the same commit, any day.** Cards are built on one dated Raspberry Pi OS Lite
  image, pinned with its SHA-256 in `tools/sofa-box-base-image.txt` (2026-10-06, the one 1.1.54's card was built
  on), and the build stops if the download isn't that image. It used to take whatever Raspberry Pi OS was newest
  that day. The packages the installer adds still come from apt on the day, so each card's report now ends with
  every package on it and its exact version.
- **Cards are published one at a time, and never backwards.** Merges close together used to build at once and
  race over the newest card's files, and the last to finish won, even when it was older. Now they queue, in order,
  and a card replaces the testing card only if it's at least as new.


## 1.1.54

- **Big skips work in videos Sofa converts for the box** (HEVC on a Pi 3, or anything else the box can't play as it
  is). Such a video comes as a stream Sofa makes as you watch, from where you started, and the box's player could
  only go as far as Sofa had got: Page Up's 5 minutes, several quick presses of right, the number keys, the phone
  remote's line or Skip intro past that point, or going back before where it started, could stall or land somewhere
  else. Now the box has Sofa convert it again from where you're going, as Sofa's own web player does, and it plays
  on from there.
  - The line goes there at once. While Sofa gets it ready (a few seconds), the picture holds still and a note in the
    middle of the screen says so; play and pause meanwhile are for when it's there. If Sofa can't (busy converting
    for someone else), the TV says so and the video goes on where it was.
  - Skips into what Sofa has converted already go there at once, as before.
  - Your place is saved from the new place on, the phone remote's line shows it all along, and subtitles keep time.
  - The number keys go through the player screen now (1 is 10% in, 5 halfway, 0 the start), so they work in these
    videos too.
  - It takes Sofa 1.5.2 or newer (its page tells the box how it asked Sofa for the video); with an older Sofa, skips
    work as before.
- **No more waiting on mpv now and then.** Two questions to the box's player at the same moment (where it is, and a
  key or the phone remote) could leave one of them waiting two seconds for an answer that had already come.

## 1.1.53

- **One player for every video, made for the TV.** Sofa's films and episodes, Live TV, USB drives and discs all play
  in the box's own player (mpv) with a screen of its own in Sofa's look: the title and where it resumes from, then a
  panel with the time line, how long is left and when it ends, Skip intro, Live TV's channel banner, the options
  menu, the volume. Everything sits inside the part of the picture every TV shows (5% in from each edge), at 720p
  and 1080p alike.
  - **The "ugly player" was most likely mpv's own desktop controls.** They came up whenever the pointer moved over the video
    (the phone's touchpad, a stick, the box tidying the pointer away) and stayed, because the box parks the pointer
    in the bottom right corner: right on mpv's control bar, which hugs the bottom edge a TV crops. mpv's own text
    ("Resuming…", the volume, the banner) sat in the top left corner, also in the cropped part. Now mpv has no
    pointer at all and draws only the box's screen.
  - **The phone remote works the same player the same way.** Its OK, arrows and play/pause are the player screen's
    keys, as on the TV's remote; up and down show where you are (on Live TV they change the channel: before, they
    went to the page behind the video), and its keys work the options menu while it's open.
  - **The other player was the page's.** When mpv couldn't start a video, Sofa played it in the page instead (and that
    title in the page from then on): a desktop player whose buttons sit 20 pixels from the screen's edges, played
    by the browser instead of the box's player. On the box it now says what went wrong, on the same card, instead.
- **Resume starts where you left off.** A video Sofa converts for the box (HEVC on a Pi 3) started up to half a minute
  late: mpv took Sofa's playlist, still being written, for live TV and began three segments from its end, ignoring
  Sofa's "start at the beginning", and the place it then saved was off by as much. It starts at its first segment
  now. Resuming any video also starts at once at the nearest frame mpv can show, instead of decoding seconds of video
  first to be exact.
- **No other screen before the picture.** The moment you press Play or Resume, the TV shows the player's start card
  (the page draws it, mpv's own takes over in the same place); before, the page sat unchanged until mpv appeared.
  **Resume on Home** plays straight away with Sofa 1.5.1 (it used to open the title's page and wait for a second
  press), and Back from it goes back to Home.
- **Quicker.** OK, the arrows and Back are answered inside the player (each used to start a program that asked the
  box, which then asked mpv): pausing took 28 ms and takes 1.5 ms on a fast computer, more on a Pi. Skipping several
  times quickly is one jump, not a queue of them. The first video after a start no longer waits for mpv to be asked
  what it can do (done when the box starts). On a Pi 3, Sofa's pages no longer play trailers and previews in the
  browser while you browse (Look and feel can turn them back on): in a scripted minute of browsing, the browser
  played 10 videos and used 16.8 s of processor time before, none and 4.5 s now (on a fast computer, without its
  video hardware). Starting a video no longer freezes the page while it asks the box.
- mpv's messages lose any web address before they reach the screen, the box's log or a report (an address names the
  title), and the player screen's file saying what's playing is deleted when it stops. The box answers a key's request properly when it comes with a body, so the next request on that
  connection isn't lost.

## 1.1.52

- **Sofa Craft with a controller.** The right stick turns the camera now. Sofa Craft (Luanti, an X program) hides the
  pointer and puts it back in the middle of the screen every frame, turning by how far it had gone; the box's
  screen can't put an X program's pointer anywhere, so the camera stopped at the edge of the TV. The stick now holds
  a pointer of its own off the middle by how far it's pushed, and back in the middle in turn: Sofa Craft reads a
  turn each time. In its menus (the inventory, a chest: the pointer showing) the stick moves the pointer as before.
  B sneaks (held) instead of opening the menu; Start opens the menu. Games says which button does what.
- **Leaving a game or an app no longer ends on a white screen.** Home, brought back after a game (or from an app),
  is checked a moment later: if it shows nothing it loads again, and if it doesn't answer at all a new Home takes
  its place.

## 1.1.51

- **The setup carries on after a restart.** On a Pi 3, joining the home Wi-Fi at the setup could restart the box,
  and the setup then began again from its first screen. Raspberry Pi OS restarts a Pi whose system stops answering
  for a minute (its watchdog), and at that moment the setup was making the Wi-Fi chip do everything at once: it
  switched from the box's own Wi-Fi to the home one while Bluetooth looked for remotes non-stop on the same chip. Now
  Bluetooth rests while the box joins. If the box restarts anyway, it waits for the home Wi-Fi it was given (it made
  its own again after 15 seconds, before a Pi 3 had joined, which took the chip off the home Wi-Fi), remembers that
  it joined, and the TV goes on at the last step, keeping the phone as the remote. The phone's link to carry on with
  still works after the restart, and the phone waits for the box for up to seven minutes.
- **The Setup Assistant opens on the phone.** The box's own Wi-Fi had the same name every time a box was set up
  (from its Wi-Fi chip), so a phone used for an earlier setup remembered it, and its sign-in sheet didn't open by
  itself. Each card now names it afresh. Its sign-in page is up before a phone can join, and the Wi-Fi has no IPv6.
  When a phone has joined, the TV shows the code to scan at once instead of waiting for a sheet that might not come.
- **The setup opens by itself on a new box,** even when the box's helper is slow to answer at the first start.
- **After the setup, Home.** Finishing landed on Home with Open Sofa in focus, so the OK pressed again while the apps
  went on opened Sofa, and "Where's your Sofa?". OK rests for two seconds after Finish. "Where's your Sofa?" comes up
  only when Sofa itself is opened; Live TV, on Home, never asks: it plays from the Sofa that opens, else the last one,
  else Sofa on the box.
- **"Where's your Sofa?" says which Sofa is which.** Each one found at home shows its computer's name and kind (from
  what it announces on the network: "Marielyss iMac"), how many films and shows it has, and its address in small
  type; the same Sofa found at two addresses is one entry, and the one Sofa last opened is marked. At its foot:
  ask each time Sofa opens, or go straight in (also in Settings → Sofa).
- **Typing the Wi-Fi password on the TV.** A bigger field you can read from the sofa, with the letters showing (Hide
  hides them) and how many there are; even rows of bigger keys; Join at the end of the keyboard's last row, a press
  or two from any key. Back closes it (at the setup, Back did nothing there).
- **A new phone remote.** A bigger pad that lights the edge you press, labelled Back, Home and Menu just under it,
  the player's and the volume's buttons in two bars, a tab bar that stays put. The Setup Assistant shows its steps as
  a bar, Wi-Fi networks with their signal, and the password under the one you picked, with Show.
- **The remote answers quicker.** Buttons press when they're touched, not when the finger lifts (a tap's tenth of a
  second or so); a shorter swipe is a step; a held arrow repeats sooner and faster. On the box, each press is
  answered at once and done in order (measured here: the phone's answer 21 ms before, 1 ms now, with the browser
  taking 8 ms a call), the browser gets the key without waiting for a round trip first, answers go out in one
  packet (Nagle's algorithm held a second one until the phone acknowledged the first, up to 200 ms on a phone), and
  through the relay presses are done on the box itself, with two requests always waiting at the service.

## 1.1.50

- **Cosmic Cascade, a whole puzzle game.** Gems fall one at a time; three or more of a colour in any line clear (a
  wild gem stands in for any), and chains follow. Endless, faster with each level; sixty puzzle boards in six
  chapters, each made to be solvable with the gems it gives (with a hint that works out a way from where you are);
  versus, two players or against the computer at three levels, where big clears and chains send stones across and
  a long round ends with the sky falling; and a board of the day. Hold a gem for later; a full star meter fires a
  beam down a column. Best score, highest level, longest chain, puzzles solved, the day's board and wins against
  the computer are kept on the box (the old "HI" label is gone). It's on the box's 2D engine now, and holds 60
  frames a second at a Pi 3's pace.
- **Void Drifter:** darts dive at you instead of circling for ever just out of reach (a fight could never end), and
  missiles are quick enough to catch them.

## 1.1.49

- **Void Drifter, a whole space run.** Four zones (the Outer Belt, the Hive Reaches, the Glass Nebula, the Deep), each
  a map of sectors where you choose the route: fights in waves, asteroid fields to mine, events with choices (a
  distress call that may be a trap, a derelict to strip, a trader drone, an ion storm, a smuggler's cache) and shops,
  then a boss: the Maw lunges and spits rock, the Hive Carrier sends its swarm, the Prism sweeps beams and fires
  rings, the Dreadnought broadsides, fires missiles and charges a beam across the sector. Six weapons, levelled up
  at shops; eight modules (shield, magnet, drone, armour, thrusters, salvager, nanites, overclock). Five kinds of
  foe. Ships unlocked between runs: the Wasp, the Bulwark and the Spectre. Fly with one stick and aim with the
  other, or let A aim at what's nearest. Two ships together; a downed one comes back when the other flies close.
  Your best score and furthest zone are kept on the box. It's on the box's 2D engine now.

## 1.1.48

- **Rune Tactics, a whole tactics game.** A campaign of fifteen battles on a map whose roads branch: meadows,
  marshes, ashlands, frostfell, ruins and a crypt, three of them bosses (the Bog King pulls heroes in with his
  tongue, the Emberwyrm breathes a row of fire, the Hollow Crown raises its dead and slips away when crowded), and
  two to hold for a set number of rounds. Five heroes who level up and learn spells: Kael (shield bash, guard,
  cleave), Lyra (pin shot, volley), Orin (firebolt, flame wall, meteor), Sefa (mend, bless, revive) and Vesk
  (frost, gust, chain lightning). High ground, cover, fire that spreads, water to freeze, pits to shove foes into.
  Ten kinds of foe, each with a trick: goblins, bone archers, brutes that shove, shamans that heal, wolves that
  flank, slimes that split, fire imps, golems that can't be moved, wraiths that drain, bombers that go off. The
  campaign is saved between battles; skirmishes on fields made up each time; two players taking turns. It's on
  the box's 2D engine now.

## 1.1.47

- **Shadow Heist, a whole stealth game.** Twelve heists in three buildings: Ashcombe Manor (carpets, libraries,
  a jewelled egg), the Coppergate Bank (marble, cameras, the gold vault) and Halcyon Tower (metal floors, server
  racks, the chairman's safe), each laid out from its own seed and harder than the last. Light worked out a tile
  at a time round the walls: switch a room's lamps off to hide in it, until a guard notices and puts them back on.
  Noise from your pace and the floor you're on. Guards with torches who hear and come to look, search, chase,
  radio each other and call for help; cameras that sweep. Smoke, a noise-maker, lock picks and a jammer. Stars for
  the loot you take, ranks for never being seen and never raising the alarm, records kept on the box. Two thieves
  together: a second controller joins on the heist screen or mid-heist, and frees a caught partner. It's on the
  box's 2D engine now.

## 1.1.46

- **Micro Drifters, a whole racing game.** Twelve tracks in four settings, each with its own weather: Harbour Loop,
  Market Run (rain) and Skyline Sprint (a figure of eight over a bridge at sundown) in the city; Dune Rally, Canyon
  Jump (a sandstorm, and a gap to clear) and Mesa Mirage in the desert; Pine Ridge, Frozen Lake (across the ice) and
  Avalanche Pass (switchbacks in a blizzard) in the snow; Neon Strip, Dockside (a storm, and a canal to jump) and
  Midnight Express (fog, over the overpass) at night, with headlights, street lamps and neon. Skid marks and tyre
  ruts stay for the race; cones, drums and snowmen get knocked flying. Four cars that drive differently (Pip,
  Brute, Scout, and Bolt, unlocked by winning a cup); drifts that charge a boost; rocket starts; jumps, ice, oil,
  puddles, mud and boost pads. One to four players on one screen with bots filling a field of six: a championship
  of four cups and a fifth for champions, at Club, Pro or Legend; quick races; time trials against the ghost of your
  best lap; Knockout. Best laps, best races, medals and the longest drift are kept on the box. It's on the box's 2D
  engine now: the cars are drawn a pixel at a time at every angle, and the tracks are painted as they load.

## 1.1.45

- **Neon Brawler, a whole beat 'em up.** Five stages through a city at night: Rain Street, the Neon Market, the Night
  Train, the Foundry Docks and Skyline Tower, each with its own look (rain, lanterns, the city rushing past the
  train's windows, containers under work lamps, a roof under the great neon sign). Three fighters to choose from:
  Vex (even all round, a four-hit chain ending in a roundhouse), Brick (slow and heavy, throws harder, slams the
  ground) and Juno (quick, a five-hit chain and a spinning kick). Eight kinds of foe (punks, knife-wielding slicers,
  bruisers who grab, runners who charge, tossers who throw bottles, riot police behind shields, flying drones,
  wreckers with sledgehammers) and four bosses: Diesel, Razor, Hammerhead and Vox, each with moves of their own and
  angrier below half. Chains that end in a launch, juggles, grabs with knees and throws, pipes, bats and bottles,
  a special meter (or a special that costs a little health when it isn't full), hit-stop and shake. Two players
  together: a second controller joins at any time with Start. Your best score, best combo and the furthest stage
  are kept on the box. It's on the box's 2D engine now: the fighters are drawn from their bones a pose at a time.
- **The 2D engine's light** can be cleared each frame (`Light.begin(fill, true)`), so a see-through dark stays as dark
  as it's asked for.

## 1.1.44

- **Tidewing 2.** Six new waters, twelve in all: Stormwall (a gale under the cliffs, with rain, lightning and a
  big swell), Glasswater Lagoon (a reef-ringed lagoon at night where the water glows), Floe Run (ice cliffs, floes
  and snow), Riverrun Gorge (up a river between red-rock walls), Ember Atoll (round a smoking volcano, ash on the
  wind) and Drowned Arcades (a sunken city's arches in clear shallows). Three cups of four races with points for
  every place: a trophy opens the next cup and wins a skimmer. Four skimmers that handle differently (the even
  Wren, the quick-turning Swift, the fast Gannet, the heavy Albatross). Time trials against the ghost of your best
  lap, kept on the box. Ride close behind another for its slipstream, and jump the crests of the swell: both fill
  your boost. With two controllers, two players race on one screen, a view each, with the three rivals.
- **The box's game engine** has ground with height for its 3D worlds (`Land`: drawn by the GPU, or painted and
  stood up on the 2D sea) and draws a split screen in 3D and on the 2D sea.

## 1.1.43

- **Cinder Knight, a whole adventure.** Four regions of four stages: the Sootwood, the Sunken Kilns, the Glasswater
  Deep and the Hearthspire, each ending in a boss (Old Charhorn, Brickmaw, the Shard Wyrm and the Snuffer). A boss's
  bar shows only once you're in its room, and its gates shut behind you until it falls.
  - Braziers to rise at, three ember shards hidden in every stage (behind cracked walls, up high, behind frost
    veils), and a forge on the Ember Road to spend them on: blade, heart, glow and draughts.
  - Moves learned as you go: the second leap (from a shrine in 1-2), then the cinder dash, the wall climb and the
    ember shield, one from each boss. Each is needed in the next region, and some shards wait until you can come
    back for them.
  - Eight kinds of foe: cinderlings, ashbats, husks with spears, kiln grubs, spouters, shardbacks (their crystal
    front turns your blade), glass wisps and snuff shades.
  - Dark but readable: torches, braziers and the knight's own glow light the way, in colour; layered backgrounds;
    a world map, three journeys kept on the box, your best times, and its own music. Every stage can be finished
    with the moves you have by then (a test plays them all).
  - `#demo` has it play itself (for the games check), keeping nothing.
- **The box's 2D engine (Low2D, `games/low2d.js`).** Built on the box's game engine, for the box's games in pixels:
  a crisp picture fitted to the TV, a fixed-step loop, tiles drawn once and copied after, layered backgrounds,
  particles, light and shadow with coloured glows, screen shake and hit-stop, a pixel font, and the title, pause,
  options and saves in one look, controller first. Cinder Knight is the first game on it; the box's other small
  page games move onto it as each is made better.
  - Three looks (light, full, rich), each at 60 frames a second or a steady 30. The box picks (a Pi 3 starts light)
    and a governor keeps it steady, stepping down before a stutter shows. A steady 30 is better than an uneven 60,
    so a box that can't hold 60 keeps the full look at a steady 30, and nothing goes below 30.
  - Options in every game on it: **Look** and **Frames**, "for this box" or held, the same in the box's browser,
    in Sofa or on a website. The box's test runs once for all the games on it.
  - Depth (a block's side receding into the screen), a layer in front of the camera, reflections in still water,
    and the camera's moments (it leans in when a boss enters, and tilts with a hard blow).
- **For the games' makers:** `games/ENGINE.md` has a section on Low2D; `#tier=light|full|rich` and `#pace=60|30`
  hold a look and a pace for checks.

## 1.1.42

- **Gloamwell for two.** A second controller joins at any time: Start on it (or A when the screen asks). Its player
  brings one of the three Wickbearers or makes a new one, and plays beside the first on the same screen, with their
  own gear, loot (marked in their colour), XP, belt, skills, familiar and half of the HUD, and their own menus (one
  at a time in the village). Kills and the notice board's tasks count for both. The camera keeps both in view and
  neither can walk off the screen. A fallen Wickbearer comes back when the other holds A beside them; if both fall,
  the descent ends. The foes are tougher for two. Either can leave from their pause menu (when the first leaves, the
  second plays on as the first), and both are kept. The keyboard is the first player's.
  - Each controller is read on its own. The box's echo of a press (the keys it makes for its own menus) is dropped
    only when that same button was just pressed, so a keyboard's keys still count while someone else plays.
- **Gloamwell's guardians, reworked.** Each has a room of its own, an entrance (A or Start cuts it short), and a
  last stand below a quarter of its HP, with a move kept for the end:
  - Old Mire rises out of the mire. The cistern's roof drips mud where a mark shows first; at the last it
    belly-flops twice, a wave from each landing.
  - Mother Tallow rises out of her own wax as four great candles catch, one by one. The candles weep lines of hot
    wax; at the last she melts, burning where she walks, and the candles spit fire.
  - The Moth Regent comes down through a column of dust. Moths drift round the room, stinging and dimming your lamp;
    at the last there are more of them, and an eclipse covers two dives.
  - Sister Knell tolls three times, nearer each time, and is there. Old bells fall from the belfry's roof; at the
    last her bell cracks (a second, slower wave) and she sings a requiem: three blinks, a ring of orbs from each.
  - The Kilnfather comes down among vents that wake one after another. They erupt in turn; at the last two at a
    time, his slam sends fire out along eight lines, and he melts down in three rings of fire.
  - The Gloamheart beats three times, its veins answering, before its eye opens. The veins pulse with its beat, one
    set and then the other, so there's always a way through; at the last, a nova of three waves.
  - The whole room is in view once its guardian wakes, the guardian carries a light of its own, and its bar marks
    a half and a quarter. Saves are as before.
- **Gloamwell is smoother on a Pi 3.** A frame takes about half the work it did: words and the HUD are drawn once
  and copied, the floor's still lights and its shadows are made ready ahead, and the floor's pictures are copied
  whole. The effects setting (Auto) steps down within a second or two when frames come late, and on its lightest
  step draws the dark at a quarter of the screen's size and leaves out the crowd's shadows. With each frame made to
  take 20 times as long (about a Pi 3), a big fight with every effect takes 13 ms a frame and runs at 59 frames a
  second (it took 20 to 26 ms, at 38 to 49 frames a second); on the lightest step, 11 ms (it took 18). Two players
  in a big fight, and the guardians' last stands, run at 59 too. A real Pi 3 is still to check.
- **`#demo` has Gloamwell play itself**, for the games check: a Wickbearer who can't fall, fighting on the sixth
  floor. It keeps nothing.
- **`#slow=N` makes each of Gloamwell's frames take N times as long**, as on a processor N times slower, so a fast
  computer can stand in for a Pi. Chrome's own slowdown is no good for this: it stretches short frames only a few
  times over (about 3× when it says 10×).

## 1.1.41

- **Ironmaw's arena.** Six arenas of its own: the Crucible round a lava pit, the Coldyard under falling snow, the
  Catwalks over a smelter (steam pads throw you up to the walkways), Rivet Row's tight halls, the flooded Pumpworks,
  and Kiln Ring, two bases across a lava moat. Four ways to play: everyone for themselves, two crews (Ember and
  Frost), holding the ring, and the Last Shift, everyone together against the foundry's waves. Up to seven bots of
  five skills, each with a way of fighting and weapons it likes: they find their way round the fire, go for what
  they need, dodge, and lead their shots. Up to four players share the screen, each with a controller and a view
  of their own, and anyone joins from the arena screen with a press. Streaks are called out, every match ends with
  a table, and the box keeps your best on each arena. A Pi 3 plays up to five bots and two players.
- **The box's game engine** draws split screens (a picture a view, each with a helper where there are cores to
  spare), swaps a sprite's colours for a crew, and finds ways round fire.

## 1.1.40

- **Ironmaw 2: the Ice.** A second episode under the foundry: Cryo Labs, the Glacier Mine, the Drowned Pumpworks
  (wading slows you), the Reactor (take its key and the alarms start), and the Frost Engine, where the Coldheart
  waits: its core shields it until it opens to fire, and below half it calls its drones and the vents breathe
  frost. Four new enemies (drones that fly, bulwarks whose plates turn shots from the front, sappers that lob
  bombs, and the Coldheart) and two new weapons (the Nailstorm, six barrels that wind up, and the Frost lance, a
  beam of cold through everything in its way). The four foundry levels get windows, vents and flickering lamps.
- **More to see, and to hear, in Ironmaw.** Light has colour (warm by the lava, cold in the Ice, green in the
  reactor, red when the alarm sounds), walls and floors keep rivet holes, scorch, blood and frost, grates, bars,
  railings, windows and fences are see-through, steam vents breathe, lamps flicker and spark, snow falls in the
  yards. Enemies walk in four steps, show their attacks coming with a glow, and break into glowing slag in a big
  blast; spent rivets and shells bounce; the view dips when you land and shakes with a blast (Options: Screen
  shake); footsteps sound like the floor; every sound comes from where it happens. Specks right at the eye no
  longer fill the screen.
- **The box's game engine draws on every core.** On a Pi (four cores), two helpers draw strips of Ironmaw's
  picture at the same time as the page runs the game (Options: Drawing, to keep it on one). The page stays at a
  steady 60 a second while they draw. `#demo` has Ironmaw play itself (for the games check), and `#slow=N` is
  for checks: Chrome's own slowdown stretches a frame's work only about 3× when it says 10×.

## 1.1.39

- **The box's own games can tell controllers apart.** Each controller is a player, numbered as it connects (when
  several turn up at once, the one pressed first is player 1), and a game can let someone join at any time. A
  player whose controller goes away keeps the place for when it comes back.
  - Games for one player follow whichever controller was used last, so any controller works them; before, most of
    them heard only the first one.
  - Holding a direction on the D-pad for more than two and a half seconds let the box's own repeated arrow keys
    through as well, so a list could move two places at a time. A held direction now counts as the controller in
    use.
- **A games check, to measure the box.** The graphics check (`127.0.0.1:8091/box/games/probe/` in the box's
  browser) has a Games check: it plays each of the box's own games for 15 seconds in turn and shows on the TV how
  each one ran: frames a second, late frames (more than 25 ms apart), the slowest frame, the game's own work each
  frame, memory, and the rung the game chose. A starts it, B stops it or goes back. On a Pi 3 it is the measure of
  each game.
  - Games can play by themselves for it (`#demo` in their address): Tidewing (riding behind a rival), Cosmic
    Cascade, Micro Drifters and Shadow Heist do now. The others are measured on their title screen, and the table
    says which. A game playing by itself takes no controller and saves nothing.
  - Memory: the box's free memory while each game runs (`/box/api/info` gives it now, `memory_free`), and the
    page's script memory where the browser gives that exactly (Chromium can round it and refresh it only every
    20 minutes; the check notices and says so).
- **For the games' makers:** `pad.js` has `SofaPad.players()`, `SofaPad.player(n)` and the `joined` and `left`
  events; Low3D's `Input` says who pressed and has `input.player(n)`; Low3D games report their rung to the check
  (`window.SofaStats`). `games/ENGINE.md` says how.

## 1.1.38

- **A new box comes with no channel lists.**
  - The box's own Sofa used to add two community channel lists, English and Spanish, by itself.
  - Now Live TV starts with Classic Cinema, and you add the lists you want from Live TV, one press each.
  - Boxes set up before keep their lists.
- **The guide no longer suggests a user name in Raspberry Pi Imager.** Setting one there stops the box's own screen
  from starting. Step 3 now says to leave it unticked; a fix is on the way.
- **With Sofa 1.5.0:**
  - Retro TV's decades are off until someone turns them on in the box's Sofa (Server → Live TV).
  - Away from home, Live TV plays only straight from where each channel is streamed.

## 1.1.37

- **No black arrow in the middle of the screen at the start.** As soon as anything on the box can point (the phone
  remote's touchpad, a controller's stick), the screen's shell draws its own black arrow mid-screen. Nothing hid it
  until the pointer first moved, which usually meant until a controller was used. Now Home, once it's on the screen,
  has the box put the pointer in its corner, which hands it to the page, and the page hides it. Pages also ignore
  that move, so the box's own pointer doesn't flash up for it.

## 1.1.36

- **Settings, as on a TV.** What there is to set is a list down the left, and the one you're on shows beside it:
  Wi-Fi and network, Remotes and Bluetooth, Sofa, Picture and sound, Home screen, Sofa Shield, This box, Software,
  Help.
  - It used to be one page of 13 cards, over 5,000 pixels tall. Only the part on screen is drawn now (78 elements
    instead of 259), so a Pi 3 answers the remote quickly there.
  - New data redraws only that part, not the whole page 4 or 5 times as it opened.
  - Back comes out to the list, and Left from a part goes to its place in the list.
- **Settings didn't open sometimes** ("Cannot read properties of undefined (reading 'on')" in a report). It was drawn
  between its two answers from the box, before the Sofa Shield one.
- **A keyboard on the TV.** OK on any field (the box's name, a town for the weather, an address, a Wi-Fi password)
  opens a keyboard you type on with the remote or a controller, with capitals, numbers and symbols. A real keyboard
  types into it too.
- **Wi-Fi.** One list, in Settings and at setup: signal bars, a lock, and the one it's on marked. Picking one opens
  its password on the TV's keyboard (Show to see it), and how the joining goes shows right there: "Joining…", then
  connected, or "The password isn't right" with the password kept to fix. Settings used to say "The TV shows how it
  goes", and then didn't show it.
- **Setup's first screen** puts the phone first and biggest (the easiest way), with the remote and a keyboard beside
  it and drawn icons instead of emoji. The Internet step no longer says "Looking for Wi-Fi…" for ever when there's
  none to find.
- **Reports tell heat from power.** A Pi that slowed down because it got hot (`0x80000`) was reported as short of
  power, with advice about the power supply. Now it says it got hot and to give it air. Short of power still says to
  use the official supply.
- **Each page opens at its top** (the browser kept the old place after a restart of the home screen).
- **Sofa 1.4.5:** Sofa's menu down the left glides open over the page and dims it, goes to the page you're on, and
  goes back to where you were.

## 1.1.35

- **Sofa 1.4.3.** On the TV, a link to another site (the EdgeVenture.uk credit, GitHub) shows a QR code to open it
  on your phone, instead of leaving Sofa for a page with no way back but Home. Live TV channels that ffmpeg plays
  can't be steered into the home network.

## 1.1.34

- **Gloamwell: gems, familiars, hidden vaults and omens.**
  - **Gems.** Rubies, sapphires, emeralds, topazes and amethysts, each chipped, clear or radiant, turn up as you
    mine (with a chime and a burst of their colour) and on the deep's stronger creatures. Gear now comes with
    sockets (finer gear with more), and Vesk's forge has a third page, GEMS: set a gem, take one out, punch a
    new socket, or fuse three of a grade into one of the next (Crafting XP). A gem does one thing in a weapon
    (a ruby: more damage; a sapphire: a chance to chill; an emerald: to poison), another in armour or a helm,
    and a third in a charm or a ring. Sockets show as coloured dots on the gear, and gems in gear you sell or
    break down come back to your pouch.
  - **Familiars**, a new page among your character's (FAMILIARS): a cellar rat that fetches gold and tonics and
    digs up more (Ysolde, for hunt marks), a lantern moth that lights your way and gathers gold (caged in a
    hidden vault), and, from fallen champions, an emberwisp that spits fire at your foes and a mire toadling
    that lobs poison.
  - **Hidden vaults.** Now and then a cracked wall over a room hides a small vault: dust drifts from the
    crack, a draught gives it away, and a blow breaks it open on a chest, gold, and sometimes gems or the moth.
  - **Omens.** From the third floor down a floor can have one, told as you arrive: the dark runs deep (less
    light, more XP), a blood moon (a red dark, harder foes, more elites and gold), the swarm (many more, weaker
    foes), a gilded floor (a gilded thief runs from you spilling coins; catch it before it slips away and its
    sack bursts), and the restless dead (what you kill may rise again).
- **Gloamwell's engine.**
  - **The camera** trails you a little and looks ahead where you're going, instead of being nailed to you.
  - **An effects governor:** the game watches its own frames, and on a box that can't keep up it sheds the
    extras step by step (motes, then the coloured glows, then some particles), never climbing back to a step
    that ran late twice, and remembering where it settled. Options has VISUAL EFFECTS: AUTO, FULL or LIGHT. `#fps`
    in the address shows the step.
  - **Sound from where it happens:** a creature's sounds come from its side of the screen, quieter far off,
    and the well echoes: long in the cistern and the belfry, short in the tight halls, none in the village.
  - **Light that flares:** blasts, critical hits, levels, legends and vaults throw a moment of light into the dark.
  - **Between floors** the dark closes in on you, and opens again on the new floor.
  - As before: all of it is drawn and made in the page, offline. 60 frames a second with the processor slowed
    ten times; slowed thirty times, it drops one step and holds 55 to 61.

## 1.1.33

- **Edge Music opens as a TV app.** The box now opens it at `https://music.edgeventure.uk/?client=sofabox`, and
  Edge Music answers with its TV layout: straight to the player, remote-sized buttons with a clear focus ring, the
  arrows moving between them, and the remote's Back closing the full player, a menu or a dialog before it leaves
  the page. Things that need a phone or a computer (saving songs to the device, files from "this device", app
  installs, Creator Studio) are left out on the TV. A box that installed Edge Music before gets the new address by
  itself; nothing else on it changes.

## 1.1.32

- **The controllers' service rests when nothing is held.** It woke 33 times a second whenever a controller was on,
  even untouched; now twice, and right when a held arrow repeats (a stick that's a game's mouse still moves it
  smoothly). It also opened every keyboard, the TV's remote over HDMI and the box's own devices again every three
  seconds, to see whether they were controllers; now once, and again only when one changes.
- **Sofa 1.4.2**: Live TV's era tabs work again (choosing an era did nothing), the era you open is fetched first,
  a quicker guide, and updates a power cut can't break ([Sofa's changes](../../CHANGES.md)).

## 1.1.31

- **Gloamwell goes deeper.**
  - **XP you can see.** Every gain rises at the side of the screen with its skill's picture (Woodcutting,
    Mining, Crafting, Hunting, and the fight's own), and the skill you're training stays in view with how far
    it is to the next level. A new level brings fireworks, a pillar of light, and what it lets you do now ("YOU
    CAN CUT PALEROOT NOW"). Each stroke throws chips and sparks, what you take pops up, a clean stroke doubles
    it ("PERFECT!"), and now and then there's a bird's nest in the roots or a geode in the vein.
  - **Legends**, a sixth kind of gear, pink: eight things of old Wickhollow with powers you can see.
    Embertongue sets foes alight, the Quiet Bell tolls every fourth blow and stuns all around, Stormwick's
    blows leap as lightning, Mother's Needle looses ghost moths, Graveweave's bones take a heavy blow for you,
    the Crown of the Drowned chills what strikes you, the Heartseeker Band heals every eighth kill, and the
    Last Lamp reaches further and makes foes in its light smoulder. Guardians and champions carry them most
    often; a legend on the floor shows as a tall pink beam.
  - **New creatures:** the lampwraith, which drinks your lamp's light as it comes; the hookfiend, which throws
    a hook along a line it shows you and hauls you in (roll to slip it); the spore mother and her pods; and,
    in the Gloam Heart, a mirror shade of you that rolls and strikes as you do.
  - **Elites' powers:** frostbound (its blows slow you), bloodthirsty (it heals as it hurts you), stormcalled
    (lightning falls where it points), and warded (a ward to break first, which comes back). Deeper down, an
    elite can have two.
  - **Champions:** now and then a floor holds one, named ("Grisk the Gnawer"), twice the size, with two
    powers, its own bar at the top, and a champion's spoils.
  - **The fight, felt:** a swing leaves a fading crescent in the weapon's colours, blows land with a star of
    light, numbers spring up (critical hits large), creatures break apart into their own pixels, kills in
    quick succession make a streak worth XP at its end, the screen's edges redden when you're low, and each
    place below has its own dust, wax flakes, spores or motes on the air.
  - As before: all of it is drawn and made in the page, offline, and it stays smooth on a Pi 3.

## 1.1.30

- **Setup's end is calm.** The boot screen's rebuild (a minute of a Pi 3's whole processor) started within five
  seconds of pressing Finish, just as Home, the apps and Sofa loaded: the box's busiest moment, and the one when a
  box was seen to restart by itself. Now it waits three minutes after the setup (or after the box starts), until
  nothing plays and the processor isn't busy, and runs as a service of its own at the lowest priority, on one
  core, instead of inside the box's player service.
- **No web page can work the box.** The box's own controls (factory reset, restart, update, forget the phones,
  pair Bluetooth, go Home, the player's keys) answered a plain GET, so any site the box's browser opened (an app
  from the store) could set them off with a picture pointed at them. Now they take only a POST from the box's own
  pages; a GET only reads.
- **The phone remote's four digits can't be worked through.** After ten wrong codes typed in ten minutes, typed
  codes rest for ten minutes and the code changes; the QR code on the TV (now always its long link) keeps
  working. Connections to the phone remote that send nothing close after two minutes.
- **Reports arrive from a box that isn't registered yet.** A box whose id the Sofa Box service hadn't taken (it
  was offline at first, or the service said no) sent its report with that id, and the service answered "Unknown
  box". It sends it without the id now.
- **No limit on new boxes from one home.** The Sofa Box service took ten new boxes a day from one home, so a card
  flashed after that had no remote from away and no reports. It takes them all now (and a box asking again with
  its own id gets the same one back). The service on the iMac needs the new `sofa-box-certs.py` for this.
- **Sofa 1.4.1**: Retro TV favourites are kept, the guide's Right key stays in its row, and more (Sofa's
  CHANGES.md).

## 1.1.29

- **The setup is kept, whatever happens.** A box that restarted by itself a few seconds after its setup was
  finished could ask for the whole setup again: its settings were saved, but not yet on the card. Now
  settings, Home's apps, the Sofa servers, the phones that are remotes and the box's id are on the card before
  the box goes on. And a setup that's interrupted carries on at the step it was at, not from the start.
- **The boot screen is made once, gently.** Choosing a theme and a name rebuilds the Pi's start-up files (a
  minute of the whole processor on a Pi 3, at the end of the setup, when the box was busiest). Now it waits
  until the setup is done and nothing plays, does it once for both, at the lowest priority, and writes it out
  to the card before it's finished.
- **The setup's codes, polished.** When your phone joins the box's own Wi-Fi, it opens the Setup Assistant by
  itself (a sheet pops up), so the TV no longer flashes the second code (a plain http:// address, which an
  iPhone's camera may not open): it says the Setup Assistant is opening, and shows the code only if it doesn't
  (or when asked). In that sheet, the Setup Assistant says what's next: the sheet closes by itself when the box
  joins your Wi-Fi, then the camera and the TV's last code.
- **After the box joins your Wi-Fi,** the last code is the secure one only: the TV waits for it (up to five
  minutes, saying so when it takes long) instead of showing a plain address first, and the box looks for it
  every five seconds instead of thirty. The phone that carried on by itself has a link of its own, so scanning
  the TV's code at the same moment no longer uses it up.
- **Live TV by era** (Sofa 1.4.0): Live now, 2009–2012, the 2000s, 90s, 80s, 70s, 60s, 50s and Classic Cinema,
  with 17 more channels and programmes by their own names.

## 1.1.28

- **Tidewing, a 3D game made for the box.** Race a skimmer, a small hover-craft with a wing, low over open water
  through the gates of six courses, three laps against three rivals. Carve through the turns to fill your boost,
  pick up sparks, hit the boost pads, keep off the rocks. Low-poly islands and craft, a sea that moves on a Pi 4 or
  5, music made as it plays. It's in Games, with the controller from the start (A B X Y, or ✕ ○ □ △), and keeps
  your best times on the box.
- **Ironmaw, an old-style shooter made for the box.** The Ironmaw foundry under the ice has gone quiet, and its
  furnaces are still burning. Fight through four levels of rooms and corridors, keys and doors, lifts, lava and
  secrets, with five weapons against five kinds of enemy, the Furnace Warden at the end. It's made for the
  controller: the left stick moves, the right stick turns and looks, RT fires, LT aims, LB and RB change weapon,
  A opens doors, B turns you round, Y shows the map. A little aim help is there (Options can take it off), and the
  controller rumbles. It's drawn a pixel at a time, so a Pi 3 plays it whether or not it has a GPU; a Pi 4 or 5
  draws it sharper, with a glow round fire and lights.
- **The box's own games have a game engine.** Low3D (`games/low3d.js`) finds out what the box's browser can draw,
  tests it once (about two seconds), and starts at a size and distance the box holds steady. While you play it
  keeps the frame rate steady: a smaller picture, or 30 frames a second, when it must, and a sharper one when
  there's room. On a box without a real GPU (or one Chromium won't use) it draws the same world in 2D. It can also
  draw a world a pixel at a time, as Ironmaw does: rooms and corridors with floors at any height, doors and lifts,
  light that fades into the dark. Each new game on it gets that, the controller (the right stick, triggers and
  rumble too), menus and sound from the start (`games/ENGINE.md`).
- **A graphics check.** In the box's browser, `127.0.0.1:8091/box/games/probe/` shows what the browser gives the
  box's games: the GPU (a Pi 3's is VC4, a Pi 4's V3D 4.2, a Pi 5's V3D 7.1), WebGL, a short test, the setting a
  game would start on, and a scene drawn that way with its frame rate. Tidewing's "This box" shows the same.

## 1.1.27

- **Two first-person shooters in Games → Get more games**, free and open source, from Debian like the others,
  played offline against the computer's bots with a controller from the start:
  - **AssaultCube**: fast, with a realistic look: rifles, pistols and grenades in close maps. Its maps come from
    AssaultCube's own site as it installs (about 50 MB, checked against what Debian expects).
  - **Sauerbraten** (Cube 2): a fast arena shooter: big jumps, rockets and rifles, bot matches and its
    single-player levels. About a 1 GB download.
  - The left stick walks, the right one looks, **RT fires** and **LT aims** (Sauerbraten zooms while it's held),
    A jumps, B and Start open its menu; in AssaultCube X reloads, Y swaps weapons, LB throws a grenade and L3
    crouches; LB and RB (or X) change weapon in Sauerbraten. In Sauerbraten's menus the right stick is the
    pointer and RT chooses; AssaultCube's take the D-pad and A.
  - Both start full screen. **On a Pi 3** they draw smaller and the TV scales them up (Sauerbraten 1024×576 with a
    lighter look, AssaultCube 1280×720), and the stick turns as fast as at full size; on a Pi 4 or 5 they draw
    at up to 1080p, with Sauerbraten's own look. The size is the box's each time; anything else you change in
    their options stays (Sauerbraten's look until the card goes into another kind of board).
  - They run through XWayland: the box's screen can't hold a Wayland game's mouse still, so it would stop turning
    at the edge of the TV.
- A game the box downloads no longer leaves its packages behind on the card (Sauerbraten's would have taken
  another gigabyte).

## 1.1.26

- **Sofa's own Retro TV and Classic Cinema are the box's.** The App Store no longer lists the outside retro TV
  sites or an archive film site, and the browser's start page no longer has an archive shortcut: they were
  websites made for a mouse, and Live TV now does it with the remote, a guide and the 2000s first.
- **The box keeps itself quick, on any board.** Every page it opens (Home, Sofa, apps) measures how long each
  press of the remote takes to show on the TV. On a board that has the full look by itself, the box takes the
  light look when a fifth of the presses take a tenth of a second or more (as the player takes 720p when 1080p
  drops frames), and says so; choosing a look in Settings → Performance starts it over. A report shows each
  page's numbers, so a slow screen can be fixed from what the box saw.
- Pictures on Home and in Sofa are decoded off to the side, so a banner changing or a row filling in never
  holds up the remote.
- **A controller does more.** **LT and RT set the volume** (held: on and on), and the TV shows it, over the
  video or whatever page is open; a remote's own volume and mute keys and the phone remote's set the box's
  volume the same way. **Menu** (Start, Options) opens the options for what's in focus: on Home an app's, in
  an app the box's bar, and **while a video plays, its options**: subtitles, the sound track, speed and
  volume, chosen with the D-pad, in the player itself. X still plays and pauses; LB and RB still skip. In the
  box's own games (Gloamwell and the rest) the triggers and Start stay the game's.
- **Live TV has a channel banner, as on a TV:** the channel's number and name, what's on and what's next, when
  a programme begins and when you change channel. Sofa 1.3.0's guide picks the channel: Retro TV's 2000s are
  channels 2 to 9.

## 1.1.25

- **Gloamwell, bigger.** Six zones now, 24 floors down to the Gloamheart and more below it: the Sunken Belfry
  and the Cinderworks are new, with Sister Knell and the Kilnfather. Every guardian has its own moves, warned
  of on the ground, and grows desperate at half its HP. Thirteen kinds of creature (hounds that charge and
  stun themselves on walls, shield-bearers to go round, toads that spit, worms from below, oozes that split,
  bell-ringers that raise the dead, wisps), and crowned ones with a power of their own.
- **And deeper.** A third skill at level 5 (RT), a talent point each level for a tree of twelve, gear in five
  places and five rarities (sets among them, and relics with a power each); what you wear changes how you
  look. In Wickhollow: Vesk's forge betters your gear, a strongbox keeps it, and the notice board has tasks.
  Three saves; a Wickbearer from before moves into the first free one.
- **Make your own Wickbearer:** a name (typed with the controller), an origin that gives a head start, skin,
  hair and its colour, a beard, scar or paint, and the colour of your clothes. What you wear shows: every
  armour and helm has its own look, the weapon is in your hand, the Warden carries a shield, and rare,
  relic and set pieces have their trim, a cape and a glow.
- **Skills besides fighting:** Woodcutting (the village's trees and the great roots below), Mining (the
  veins in the walls, a metal for each zone), Crafting at Vesk's forge (bars, better hatchets and picks,
  weapons, armour, helms and rings, tonics and oil), and Hunting: Ysolde the huntress sets a creature to
  hunt, and pays in hunt marks for her mask, rare finds, and a mount. Each skill levels up to 60.
- **Mounts to win:** eight, from the guardians (now and then), from Ysolde, and one you make. L3 (the left
  stick, pressed) rides and gets down. The four that fly cross water, lava, wax and spikes.
- **Better to look at and listen to, still smooth on a Pi 3:** your lamp throws shadows past walls, torches
  flicker, water and lava move, blows spark and shake, and it has its own quiet music (Sound and options: the
  two volumes, the shake, the controller's rumble). As light to run as before: everything is drawn once and
  copied after.
- **Seven more of the box's own games:** Cinder Knight, Shadow Heist, Rune Tactics, Micro Drifters, Neon
  Brawler, Void Drifter and Cosmic Cascade, and longer Neon Dodge and Sky Hop. Each plays with the controller
  (its buttons named as yours shows them, ✕ ○ □ △ too), and draws its letters and glows once, not every frame.
  Fixed on the way: Rune Tactics and Shadow Heist didn't start, a controller couldn't start a race, Sky Hop's
  platforms scrolled away, glows wiped out what was under them, and guards saw through walls on screen.

## 1.1.23

- **Sofa Craft starts again.** A crash at its first start had left its world without its game, so every start
  after stopped at once ("Game [] could not be found"), with Luanti's own menu to get out of. The box now mends
  the world before each start (its game; its storage only where it's missing), and on a Pi 3 holds it to 30
  frames a second, much lighter. When a game stops as it starts, OK on it tries again.
- **A game gets the box.** When one starts, every page stops (Home too), the apps that aren't Sofa close on a
  1 GB box, and the browser lets go of the memory it can; Home comes back when the game ends.
- **When the box restarts by itself, the next report says why.** Its logs are kept across a restart now (24 MB
  at most; alarms such as "under-voltage" written at once), and a report shows how the start before ended and
  the Pi's own record of its power. The games' log keeps their last few starts, each marked.
- **Short of power, the TV says so** (once): a weak power supply makes a Pi freeze or restart, more so while it
  switches Wi-Fi or plays a game.
- **Retro TV puts the 2000s first** (Sofa 1.2.3), with 00s Kids TV and 00s On Air.

## 1.1.22

- **The setup in two scans.** When your phone gives the box your Wi-Fi, the box also gives it the remote's
  address through the Sofa Box service; once both are back on your Wi-Fi, the Setup Assistant carries on there
  by itself, already the remote: no last code to scan. (A new box makes its own id at its first start, so that
  address is known before it's ever online; the service takes it. Where it can't, the last code is still on
  the TV.)
- **Retro TV.** The App Store has a Retro TV section: Joey Cato's My Retro TVs, a site for each decade from the
  50s to the 2010s, channel-surfing that decade's shows and commercials on an old TV. And Live TV has Sofa's
  own Retro TV channels (Sofa 1.2.2), a decade each, with period commercials between the shows.
- **Fixes from a careful read:** a tap on the phone's touchpad after the pointer has gone to its corner only
  brings it back (it used to press whatever was in the middle of the screen); a video, an app or a game
  starting wakes the box (else the next phone key jumped back to Home); after changing channel in the box's
  player, an archive channel that runs out tunes in again to the channel you were on.
- **Reports say more, and less.** Send a report now lists when the box's player stopped by itself and why, and
  the Bluetooth pairings the box said yes or no to. A looping preview's routine messages are left out (they
  filled the last report), and the same message again is counted, not repeated.

## 1.1.21

- **The setup's phone side is the Sofa Setup Assistant.** The TV's phone panel is "Set up with your phone",
  and each code says what it really does: the first connects your phone to the box (its own Wi-Fi), the second
  opens the Setup Assistant on your phone (not "the remote"), where you choose your Wi-Fi; the last keeps your
  phone as the remote. On the phone, the assistant shows its three steps, and after the Wi-Fi, exactly what
  the last step is.
- **Our games are played with a controller first.** Neon Dodge, Pair Up and Sky Hop read the controller
  straight (the stick too: Sky Hop steers as far as it's pushed), with no wait before a held direction repeats,
  and say its buttons' names (A, or ✕ on a PlayStation controller); keys still work when there's no
  controller. Keys and a mouse stay for the games that have nothing else (Wesnoth, OpenTTD).
- New Sofa Craft worlds keep their mods' data in SQLite too (Luanti's warning about the old way).

## 1.1.20

- **A power button on the phone remote.** It puts the box to rest: what plays stops (its place kept), a game
  ends, and the TV shows the box's screensaver, the time, the weather and the art of what you've been
  watching, crossfading, the clock drifting to a new spot every minute so nothing burns into the TV (still
  pictures on a Pi 3). A touch anywhere on the phone wakes it, and so does any key on a remote or controller.
- **Internet Archive channels in Live TV** (Sofa 1.2.1): classic movies, film noir, westerns, cartoons and
  more, like TV channels, in the box's player; up and down change the channel, the film's name on screen.
- **Sofa looks like a TV app on the box** (Sofa 1.2.1): its menu is a rail down the left edge, opening into
  names when the remote goes into it, with no scroll bars and the row in focus gliding to the middle.

## 1.1.19

- **Xbox controllers pair.** An Xbox Series controller (and others) asks the box to say yes to the pairing;
  nothing on the box answered, so it stopped blinking as if paired and the box said it didn't pair. The box
  now keeps a pairing helper running that says yes while it's looking for devices (and no otherwise), is
  pairable while looking, lets a controller pair again, and loads what Bluetooth LE controllers need.
- **The TV's remote over HDMI (CEC) stops restarting.** Its service needed `ir-keytable`, which the card
  didn't have, so it crashed every few seconds; it's on the card now, and the service runs without it too.
- **Every code on the setup's first screen shows whole.** The remote's code ran under the bar at the
  bottom on a 1080p TV: the steps are one row now, the code fits the screen's height, and there's room
  for TVs that trim their edges.
- **The pointer stays out of the way, and it's the box's own.** It used to sit in the middle of the screen
  from the first start. Now it's somewhere only while the phone's touchpad is used: it starts from the
  middle, moves with the box's own acceleration (precise when slow, across the TV when quick), goes to a
  corner after a few seconds, and hides at once when a remote key is pressed. It's white with a pink glow,
  pink over what can be pressed. The phone's touchpad shows where your finger is.
- **Live TV in the box's player.** Channels play on the Pi's video chip, with "Tuning in to…"; up and down
  (or Page Up/Down) change the channel, with its name on the screen.
- **Sofa on this box is Sofa 1.2.0**, the version number catching up with everything since 1.1.0 (what's in
  it: [CHANGES.md](../../CHANGES.md)). Its Server → Updates says which commit runs and when it was made.

## 1.1.18

- **The setup is shorter and goes on by itself.** Once your phone is the remote on your Wi-Fi (the four
  codes on Hello), the TV moves on to **Your box** by itself, and joining Wi-Fi at the Internet step
  does the same. No asking for the Wi-Fi again, and no Bluetooth step: speakers, headphones and more
  controllers wait for **Settings → Remotes and Bluetooth** or **Games**, and the end of the setup says
  so. **Start**, **Next** and **Back** stay at the bottom of the screen, never below its edge.
- **Sofa Craft is on every box.** An endless world of blocks to explore, mine, build and craft in,
  first in Games, with its own picture, straight into your world with the controller. It's Luanti, the
  open-source block game, on the card from the start (a box that updates gets it too).

## 1.1.17

- **Gloamwell, the box's own game** (Games → On the box): an action-RPG dungeon crawler, made for the TV and
  the controller. The Great Wick at the bottom of Wickhollow's well has gone out; go down and find out why.
  - Three to play: the **Warden** (shield and blade), the **Ashcaller** (fire from the well) and the
    **Stalker** (knives from the dark), each with an attack, a roll and two skills.
  - Every floor is new each time you go down: rooms, monsters that get stronger the deeper you are, urns and
    chests, torches and a brazier to light. Four places below, each with its own creatures, and a guardian on
    every fourth floor who seals the stair down. Past the sixteenth, the floors go on.
  - Gold, tonics and gear: weapons, armor and charms, plain to relic, with their own powers. Hesk's stall in
    the village buys and sells; the shrine mends you; the rope (or Homeward Ash) brings you back up, and the
    well takes you straight to the deepest floor you've reached.
  - Played with any controller from the start, the hints showing its own buttons (A B X Y, or ✕ ○ □ △ on a
    PlayStation one); a keyboard works too. It's drawn in pixel art at a small size and scaled up, so it runs
    smoothly on a Pi 3, and needs no internet. Your Wickbearer is kept on the box: Continue picks up where you
    left. Hold Home to leave, as in any game.

## 1.1.16

- **Games is a games mode.** Free, open-source games that run on the box itself, installed from Games →
  **Get more games** with one press (a few minutes) and played full screen, **offline**: SuperTux, Flare (a
  dark-fantasy action RPG), Luanti (an open block world: it starts straight in your world), Neverball,
  Battle for Wesnoth, OpenTTD, and SuperTuxKart on a Pi 4 or 5. Each shows the room it takes, and the box
  checks there's room first; **Remove a game** takes it off again.
- **Controllers, recognised.** Games asks for a controller when none is connected, with how to pair an Xbox,
  PlayStation, 8BitDo or other one, and shows which kind is connected; a toast says so when one turns on.
  Generic USB controllers (buttons numbered 1 to 12) work now too, on the box's pages as well.
- **Every game works with the controller from the start, the same on every controller.** Games made for
  controllers read it themselves. For the others, the box works it for them, by the buttons' places (an
  Xbox controller's A is a PlayStation controller's ✕): the sticks walk, look around or move the pointer,
  the triggers click, the buttons are the game's keys (Luanti: jump, inventory, dig and place; Wesnoth: click,
  end the turn).
- **Hold Home for a second to come back from a game** (the Xbox or PS button, or a remote's Home).
- The card has XWayland, for games made for X; when a game stops as it starts, **Send a report** includes
  what it said.

## 1.1.15

- **USB drives are sorted like the Inbox sorts, without touching them.** Plug a drive into the box and Sofa
  on the box finds every show and movie on it, whatever its folders are called: episodes named like
  `Show.S01E02` anywhere on it join their show, folders like Movies, TV or Downloads are looked inside, and
  anything it can't identify still shows, named after the file. It's done with links in a folder on the
  box, named as the Inbox names things: nothing on the drive is moved, renamed, converted or deleted, and
  its posters stay on the box. Only what changed on the drive is looked at again; something removed drops
  out with its posters. Drives the box already had are sorted this way by themselves.
- **Episodes named with initials** (`BB.S01E01` in a `Breaking Bad` folder) join the folder's show, on drives
  and in the Inbox (they used to make a show called "BB").
- **Sofa on this box, from anywhere** (Settings): the box's own Sofa opens to the internet from the TV, like
  Sofa on any computer: a DuckDNS address or your own domain, the router asked to send the ports, a Let's
  Encrypt certificate, the internet let in, and a check from outside, each step on screen. A box that's
  open starts its Sofa when it starts. **Make it home only** closes it.
- **Sofa, open to the world:**
  - A DuckDNS address gets its certificate over DNS (DuckDNS's check record), so only port 443 needs
    opening; many internet providers block port 80.
  - **Check from outside** (Server → Internet) asks the Sofa Box service whether your address answers with
    Sofa from the internet, and says what's wrong when it doesn't (no DNS record yet, a home address,
    nothing answering, a wrong certificate, something that isn't Sofa).
  - It warns when the internet provider shares one address between homes (carrier-grade NAT) or there's a
    second router in front: no port can be opened then, and a VPN like Tailscale is the way in.
  - The guide, [docs/remote-access.md](../../docs/remote-access.md), is new: each step, the ports to
    forward, and what to do when the router or the provider is in the way.

## 1.1.14

- **The secure phone remote goes through the Sofa Box service's relay.** The QR code to keep the remote is
  `https://boxcert.edgeventure.uk/r/<box>/…`: a secure address every phone opens, at home or away. The box
  keeps a connection open to the service, and the phone's taps reach the box through it. It replaces a name
  and a Let's Encrypt certificate for every box, which had limits (50 new boxes a week for all of
  edgeventure.uk) and didn't work behind routers that block names pointing at home addresses.
  - The phone still needs the TV's code: through the relay, only the QR code's long one (24 characters);
    typing the four digits works at home only, so they can't be guessed at from the internet.
  - The remote's page comes from the service, not from boxes, and each phone's sign-in is kept to its box:
    one box can't reach another through the shared address.
  - Nothing is kept by the service; Settings → Remotes and Bluetooth switches it off.
- The phone remote page uses relative addresses (the same page at home and through the relay), and says
  "Can't reach the box" when the relay says the box is offline (not "type the code").

## 1.1.13

- **The setup's apps step is short.** Eight apps most people use (Netflix, YouTube, Prime Video, Disney+, Max,
  Hulu, Apple TV+, Spotify), all on one screen, no scrolling; the App Store has the rest. "Add N and finish"
  counts only the ones that aren't on Home yet.
- **Home scrolls like a TV's home screen.** Down brings the next row up under the top bar, title and all, the
  same place every time (it used to stop wherever the tile just fitted, often under the hints at the bottom);
  along a row, the next tile peeks in; Up goes back row by row (it used to jump to the top bar), and the top
  bar only from the first row. Smooth on every board, a Pi 3 too: the scrolling is the graphics chip's work.
- **Apps are easier with a remote.** On sites made for a mouse, the arrows move between links and buttons (the
  browser's spatial navigation), with a ring showing where you are, even on sites that hide it. Pages that
  scroll do so smoothly. Sofa's pages on the box scroll smoothly too.
- **Sharper app icons.** The box looks harder for each app's own icon (where sites keep one without saying),
  measures what it finds and keeps the sharpest; YouTube, Netflix, Spotify and Prime Video get their official
  ones. Icons have a soft shine and edge, and the one in focus lifts. Boxes fetch their apps' icons again once.
  (Fetching icons also no longer stops for good at the first site that hangs up part way.)

## 1.1.12

From setting up 1.1.11:

- **No "no network, making its own Wi-Fi" just after your phone gives the box your Wi-Fi.** Between its own
  Wi-Fi and yours the box has no address for a moment, and the TV took that for a box with no network yet.
  It now says what's happening: joining your Wi-Fi, then "Connected to … Getting the box's address there",
  then the code for the remote; or, if joining didn't work, why, and that its own Wi-Fi is coming back.
- **Fewer blank moments while the box starts.** The boot screen used to go before the box's helper was ready,
  leaving a still or black screen while the browser waited for it (long on a first start). It now stays,
  moving, until the helper answers (a minute at most), and Home follows at once. Home is dark from its very
  first frame, not blank while it loads.

## 1.1.11

- **Resuming no longer sits on a blank black screen.** When you resume something Sofa converts for the box, it
  first converts from where you left off, which can take a while; the box's player showed black meanwhile, as
  if it had hung. Its screen now says "Resuming … at 23:14", then that Sofa is getting it ready, and after 25
  seconds that Back stops it; the words go as soon as the picture moves.
- **When the box's player can't start a video, the page's own player now gets one it can play.** It used to
  ask Sofa for what the box's player plays (MKV, surround sound), which the browser can't: another black
  screen. Trailers on Sofa's pages on the box had the same problem.

## 1.1.10

- **USB drives join Sofa on the box by themselves.** Plug a drive in and, if you use Sofa on this box (This
  box), its shows and movies are in Sofa within moments, with posters and Continue watching: nothing to add
  by hand. Sofa reads the drive as it is: show folders and episodes named like `Show.S01E02` are shows (a
  "TV" or "Shows" folder holds shows), the rest are movies, loose or in folders. Nothing on the drive is
  moved or renamed; Adult and XXX folders are left out. Unplugged, its titles drop out until it's back, with
  everyone's progress kept. Server → Storage shows it as "USB, as it is"; Stop using keeps it out.

## 1.1.9

A look through every part of the box:

- **Bluetooth at the setup.** Remotes and controllers didn't show up. Every two seconds the box asked about each
  device near it one by one (a process each: dozens in a busy room, too much for a Pi 3); it now asks
  bluetoothd once for all of them. Bluetooth is switched on (unblocked) at every start, as Wi-Fi already
  was, and a device that only says what it is in its Bluetooth LE "appearance" (a remote control, a gamepad)
  is recognised by that too.
- **Quicker starts.** cloud-init (which applies Raspberry Pi Imager's settings) ran its five steps at every
  start, on a Pi 3 at the same time as the browser starting; it now switches itself off after the first.
- **Less work in the background.** The box looked for USB drives and discs by running lsblk every four
  seconds, all day; it now reads two small files and runs it only when something's plugged in or out.
- **The setup's first step fits on the TV.** The QR code and what to do sit side by side, and the whole step
  shows without scrolling (the title was cut off at the top). The setup's layout also no longer leaked onto
  the rest of the page.
- **Games show their names** (the tiles only had room for the line about them).
- **Apps whose icon is empty or white show properly.** An icon with nothing in it (some sites have one) shows
  the app's first letter on its colour; a white logo on clear gets the app's colour behind it, not white.

## 1.1.8

- **A new Home.** At the top: the time, big, the day, a hello, and what to do next (Resume what you
  were watching, with its picture behind; Open Sofa; Live TV). Beside it, **the weather**: now, the
  high and low for the next 24 hours, and the next few hours, drawn in the box's look. It's for the
  city of the box's time zone until you pick a town (Settings → Weather on Home, where °C or °F and
  Off are too). From MET Norway, Norway's weather service: free, no account, asked every half hour.
- **No blank page when an app opens.** The TV used to switch to a new app's empty page while it
  loaded. Now the app loads behind Home, which shows its icon ("Opening YouTube…"), and the TV
  switches once the app has something to show (8 seconds at most). An app that's open already comes
  straight back.
- **The first start says it's the slow one.** A new card's boot screen says the first start takes a
  few minutes and that the box may restart once by itself: just wait. Only on that start.
- Home starts with the pointer hidden (it shows when a mouse or the phone's touchpad moves it).

## 1.1.7

- **Send a report.** Settings → Help → **Send a report** (or, on the phone remote, **Something wrong?
  Send a report** under the buttons, for when the TV's menus are out of reach) sends the Sofa Box team
  what the box checks and has logged since it started, and the TV shows the report's number. In it:
  the version, board and settings, the network, Wi-Fi, Bluetooth and phone remotes, where the player
  was (not what it played), the errors of the pages open on it, and what their video players said:
  which decoder plays (the Pi's own or the processor) and why one stopped. Web addresses are cut to
  their site, files on drives to the drive, and passwords blanked: no titles, codes or passwords. It
  goes only when you press it, twice. Send it before restarting the box: a restart clears the logs.
- **Sofa on the box starts in the box's own theme.** The Sofa App has the Street theme now, and starts
  with it everywhere (a server's owner can still pick another for everyone, and each screen its own);
  on a Sofa box, it takes the box's theme.

## 1.1.6

From setting up 1.1.5 on a Pi 3:

- **The phone remote's volume buttons work.** They used a tool the box doesn't have (`pactl`); they use
  PipeWire's own (`wpctl`) now.
- **YouTube plays more smoothly on a Pi 3.** Its video chip plays H.264 only; YouTube sent VP9 or AV1, which its
  processor had to decode. On a Pi 3 (or older), pages are told those two can't play, so sites send H.264. A
  Pi 4 or 5 is left to choose.
- **The setup doesn't show the Wi-Fi step once the box is online** (your phone gave it your Wi-Fi, or a cable):
  Start goes on to Bluetooth.
- **On the box's own Wi-Fi, the phone page only sets up the Wi-Fi:** no remote tabs, and no "Add to Home
  Screen" (that page stops working once the box joins yours). The full remote, and the tip, come with the
  last code.
- **After joining your Wi-Fi, the TV waits for the box's secure address** (up to three minutes) instead of
  showing the plain one first. If getting it fails just after joining, the box tries again in 30 seconds, not
  an hour later. Where only the plain address works, the TV says how to let an iPhone open it.

## 1.1.5

- **Joining your Wi-Fi at the setup no longer loops back to "connecting".** To join your Wi-Fi, the box
  switches its own off and looks for yours. Meanwhile its 10-second network check saw a box with no Wi-Fi
  that had been "offline" for minutes, and brought the box's own Wi-Fi straight back, in the middle of the
  join, every time. It now leaves the Wi-Fi alone while a join is going on (and only one join runs at once),
  and brings its own Wi-Fi back only if the join didn't work.
- **The setup shows one code at a time, and says what it's waiting for.** Four steps on the TV, the one in
  front highlighted and the done ones ticked: join the box's Wi-Fi, open the remote, give the box your
  Wi-Fi, keep the remote. Each step shows only its own code, and goes by itself once it's done: the Wi-Fi
  code as soon as a phone joins the box's Wi-Fi, the remote's code as soon as the remote is open on it.
  Under each: "Waiting for your phone to join…", "Waiting for the remote to open on your phone…",
  "Waiting for your Wi-Fi details…", "The box is joining …: looking for it, then connecting". "Show the
  code again" buttons bring a code back. (Before, two codes sat side by side, hard to scan, and the second
  said "Didn't open? Scan this", as if phones opened the remote by themselves after the first; many don't.)
- **A sound when the box starts:** four soft notes with the opening. Settings → Picture and sound → Sound
  at start switches it off.

## 1.1.4

- **Apps fill the TV.** YouTube and other apps opened as a small square in the top-left corner of the TV. The
  box drew them at half size with doubled pixels, to look bigger from the sofa; on the Pi the doubling didn't
  take, which left a quarter of the screen. Apps now get the whole TV at its own resolution, like on any
  computer (ordinary websites look a little smaller; apps made for TVs are made for exactly that).

Still being looked into on a real box: the iPhone's sign-in sheet not opening by itself, and Bluetooth remotes
and controllers not showing up.

## 1.1.3

- **The phone's Remote tab works.** Taps and swipes on its round pad went nowhere: the pad shared its name in
  the page with the Touchpad tab's icon, and the page wired the pad up to the icon. Back, Home and the other
  buttons were fine. Checked in an iPhone's Safari: taps, OK and swipes all reach the box.
- **No confusing code swap after you give the box your Wi-Fi.** While it joins, the TV no longer shows the
  codes for the box's own Wi-Fi (they're about to stop working). Once it's joined, the TV waits the few
  seconds for the secure code instead of showing the plain one first and then swapping it.

Still being looked into on a real box: the iPhone's sign-in sheet not opening by itself, Bluetooth remotes and
controllers not showing up, and some apps (YouTube) opening in a small square in the corner of the TV.

## 1.1.2

Fixes from setting up a real box with an iPhone:

- **Joining your Wi-Fi at the setup.** The box now looks for your Wi-Fi before it joins it: just off its own
  Wi-Fi it couldn't see any network yet, and joining could fail for that alone. It answers the phone first and
  then leaves. The TV shows "Joining…", then either that it's connected, with the new code to scan right
  there, or exactly why not (the password isn't right, it can't see that Wi-Fi).
- **No phone left stranded.** The box's own Wi-Fi keeps the same name and password from one time to the next
  (it used to make a new password every time), so after a try that didn't work, your phone can join it again.
  When the phone loses the box, the remote says what to do (scan the code on the TV again) instead of only
  "Can't reach the box".
- **The phone's Remote tab** (arrows, OK, Back) sends its keys straight to the page on the TV, the way the
  Touchpad's clicks already got through. OK carries a real Enter, which some pages need to press a button.
- **Remotes and game controllers over Bluetooth** go to the screen through a device that's now a full keyboard;
  with only a handful of keys it may not have been taken for one.

Still being looked into on a real box: the iPhone's sign-in sheet not opening by itself on the box's own Wi-Fi,
and Bluetooth remotes and controllers not showing up during the setup.

## 1.1.1

- **The secure phone remote is there right after the setup.** When you give a new box your Wi-Fi during its
  setup, it now asks for its name and certificate straight away (it used to wait up to 10 minutes). Until
  then the remote on your home Wi-Fi was a plain http:// page, which iPhones with Safari's Not Secure
  Connection Warning on refuse, halfway through the setup. A box that comes online any other way (a cable
  plugged in later, a router back from a restart) notices within 30 seconds.
- **The boot screen shows the version**, small under SOFA BOX ("OS 1.1.1"). It follows the box's updates.
- **A new box's boot screen is all Street**, the default theme. Until a theme was picked, it had Street's
  colours with another theme's lettering and logo.
- Certificate requests from a Mac's openssl (LibreSSL) name their curve, so Let's Encrypt accepts them.

## 1.1.0

- **A secure (https) phone remote at home.** Once the box is online it gets a name of its own,
  `<random>.box.edgeventure.uk`, pointed at its address on your network, and a real certificate for it,
  from the Sofa Box certificate service. Phones whose browser only opens secure pages (an iPhone with
  Safari's Not Secure Connection Warning on) can use the remote at home. The QR code uses the new address
  by itself; where the router blocks such names, it stays http://. Settings → Remotes and Bluetooth shows
  it and can switch it off. The box sends only a random id and its home address; its key stays on the box.

## 1.0.2

- **The remote opens by itself at the setup.** The box's own Wi-Fi now works like a hotel's: when a phone
  joins it (the first QR code), the phone pops up its sign-in sheet, and the sheet is the remote, already
  paired. The second QR code is only needed if it doesn't open.
- That sheet takes the box's page even on an iPhone with Safari's "Not Secure Connection Warning"
  (HTTPS only) switched on, which refused it ("Navigation failed… HTTPS-Only").

## 1.0.1

- **The setup's phone code no longer waits for ever on a box with no network.** A card written without
  Raspberry Pi Imager's settings starts with Wi-Fi switched off (Raspberry Pi OS does that until a
  country is set), so the box couldn't make its own Wi-Fi for the phone, and the setup's spinner never
  ended. The box now switches Wi-Fi on by itself at every start.
- If the box still can't make its own Wi-Fi, the setup says so, with what to do (a network cable, or a
  USB keyboard), instead of a spinner. It keeps trying by itself.
- iPhones can join the box's own Wi-Fi (the Pi's Wi-Fi chip needed one setting changed for them).

## 1.0.0

The first numbered Sofa Box OS.

- **Setup without a controller.** The first screen shows a QR code: scan it with a phone and the phone
  is the remote, keyboard and touchpad. A Fire TV remote pairs by holding Home for 10 seconds. With no
  cable and no Wi-Fi, the box makes its own Wi-Fi so the phone can reach it and give it the home Wi-Fi.
- **The setup:** Hello (what you're holding), Internet, Bluetooth, Your box (name, time zone, look), Apps.
- **Sofa from anywhere:** a Sofa at home, a share link on the internet, Sofa on the box itself (free
  Live TV, USB drives, no other computer), or Jellyfin, Emby or Plex. Ask every time, or remember.
- **USB drives, DVDs, Blu-rays and music CDs** play from Home.
- **Popular streaming apps** in the App Store, with proper icons, and a new Home.
- **Made for small boards:** it finds out what it runs on (Pi 3, 4 or 5; 1 to 8 GB) and adapts; the
  app in front gets the box, apps in the background sleep.
- **Fills the TV:** pages are drawn at the TV's full size (the setup was a small square in a corner).
- **Settings → Software:** which Sofa Box OS it is, a note when a newer one is out, Update the box, and
  Reset to how it came (for a new owner).
- **Fixes in this version:** Update and Reset no longer stop half way; after a power cut or a router
  restart, a box that knows its Wi-Fi waits for it instead of switching to its own; opening Sofa on the
  box the first time says it's starting.
