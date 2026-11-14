# Sofa: what's new

Sofa's own version is in `sofa/__init__.py` and on **Server → Updates**. Sofa Box OS, the Raspberry Pi TV box,
has its own numbers and list: [deploy/sofa-box/CHANGES.md](deploy/sofa-box/CHANGES.md).

A change to Sofa's code (`sofa/`, `client/`, `sofa.py`) gets a new version: raise `__version__`, add a section
here, then `python3 tools/sofa-version.py` (a test checks it was done).

## 1.5.13 (2026-11-14, a draft)

- **Tuners at home** (`sofa/tuners.py`): an HDHomeRun, or anything that answers as one, found on the network
  (SiliconDust's discovery packet) or by its address. Listed off until an admin turns it on; then its channels are in
  Live TV by their own numbers, after the lists' (so no channel a household knows moves). Copy-protected channels are
  left out; MPEG-2 channels (most over-the-air TV) are converted as they play, deinterlaced. A tuner's channel is at
  home: never a Visitor's, never played away from home through Sofa, never looked at by the channel checker. Works
  with offline mode on.
- **The guide** (`sofa/guide.py`): XMLTV from an address or a file, read every six hours, two weeks kept, matched to
  channels by id, tuner number or name. A file that declares its own entities is refused.
- **Recording** (`sofa/dvr.py`): now, a programme, a slot, or a series (new episodes only, keep the last N, no
  repeats of an episode already recorded). Padding (1 and 3 minutes) that gives way instead of clashing; conflicts
  across a box's tuners, said with what they clash with; a stream that breaks off is opened again and the parts
  joined. The file (the channel's own stream, copied) goes into the Inbox under a name it reads, and the Inbox files
  it. Channels at home only (a tuner's, a list on the home network): never a list from the internet, never the Retro
  TV decades or Classic Cinema. **A recording is never shown to the public library's Visitors**, even when its show
  is shared.
- The API is in `docs/tuners-and-recording.md`. **No screens yet, and no real tuner has run any of it**: it's tested
  against a stand-in tuner (`tests/stand_in_tuner.py`) with real ffmpeg recordings.
- Live TV's channel lists kept on the home network are now fetched directly (no proxy) and in offline mode too:
  offline is about the internet.

## 1.5.12 (2026-11-13)

- **The graphics chip converts video on Linux and Windows too.** Beside Apple's VideoToolbox on a Mac: NVIDIA's
  **NVENC**, Intel's **Quick Sync** and **VA-API** (Intel's and AMD's graphics) on Linux; NVENC, Quick Sync and AMD's
  **AMF** on Windows (`sofa/encoders.py`). Nothing to set up, and nothing is guessed from a name:
  - **What's there:** what this ffmpeg was built with; the render nodes in `/dev/dri`, by maker, and whether Sofa's
    user may open them; NVIDIA's driver (`nvidia-smi`); Windows' display adapters, by maker.
  - **A one-second conversion** with each encoder that could be here. Drivers and ffmpeg versions don't agree on an
    encoder's options, so each is asked in up to three ways and the first that works is kept. Then the timing and
    the check of its pictures Sofa already did for VideoToolbox.
  - **The choice, for every conversion:** a chip's encoder that passed and converts well faster than video plays (75
    frames a second of 1080p) is used, the fastest of them; it leaves the processor to everything else. Otherwise
    the fastest way, the processor included.
  - **When a chip's encoder stops on a video,** Sofa carries on with the processor. A stream being watched goes on
    from where it was, in the same playlist, so the player keeps playing; a stream that hadn't begun, and a file
    being converted for good, start again. The encoder rests for ten minutes, and after three failures in a row
    isn't used until the next test. A video that fails with the processor too isn't held against the chip.
  - **One switch:** Server → Overview → This computer → **Convert with the graphics chip**. It appears once a chip's
    encoder has passed here. The panel lists each encoder tried, its speed or why it doesn't work, and the one in use.
  - **HEVC is decoded by the chip as well** only where this computer's own measurement shows that to be faster. On
    an A18 Pro it's slower (255 frames a second against the processor's 350), so it stays on the processor there.
  - `python3 sofa.py encoders` runs the test now and prints what it found.
- **In Docker:** give the container the chip (`devices: /dev/dri` for Intel's and AMD's, `gpus: all` for NVIDIA:
  both are in `compose.yml` behind a `#`), and its start puts Sofa's user in the group that owns the render node by
  itself. The amd64 image carries Debian's VA-API drivers for both makers (it grows by Mesa's size; the arm64 image
  is as it was). `docs/install.md`, "The graphics chip in Docker".
- **What changes on a Mac:** where VideoToolbox passes its test and converts at two and a half times the speed
  video plays, it is used even when x264 measures faster. On Apple silicon that's a change: an A18 Pro and an M4
  both measured x264 the faster of the two (110 to 190 and 343 frames a second against VideoToolbox's 90 to 101),
  and used it. Server → Overview → This computer → **Convert with the graphics chip**, off, brings x264 back. A Mac
  whose chip has no working encoder, or draws lines across the picture, converts exactly as before.
- **What has run where** (`docs/capabilities.md`, "The graphics chip's encoders"): VideoToolbox on two Apple chips.
  **NVENC, Quick Sync, VA-API and AMF have not run on a real chip:** we have no NVIDIA card and no Intel or AMD
  graphics under Linux or Windows. Their detection, choice, commands and every failure are tested with a stand-in
  ffmpeg that behaves as a driver might and converts for real with x264 (`tests/stand_in_ffmpeg.py`); a render node
  that can't convert has been tried for real in the Docker image on a Linux VM; the switch in the middle of a
  stream has played through in Chrome. An encoder is only ever used after its own test passes on that computer, so
  an untested one can fail its test and leave x264 in charge; it can't break playing.
- A restart shows the last test's result on the Server page at once, not a minute later.

## 1.5.11 (2026-11-13)

- **Hardware by what it is, not by what it's sold as.** The README, the docs, the issue and pull request templates,
  comments and tests name a computer by its parts: the processor's family and what it can do (x86-64 with or without
  AVX2, a Cortex-A53, Apple silicon), cores, memory, graphics or video encoder, and the system. Never a model and a
  year: two machines with the same parts behave the same. A Raspberry Pi keeps its board's name, with the chip beside
  it.
  - `docs/capabilities.md`'s table is **Tested hardware** now (the old links to "Tested on" still land on it), with
    the hardware in its first column and what ran on it in the second.
  - The hardware report asks for the processor, cores, memory, graphics and system of anything that isn't a Pi.
  - `tests/test_hardware_wording.py` fails when a model and year comes back. Changelog entries before this one stay
    as they were written.
  - Nothing Sofa does has changed: in `sofa/`, only comments.

## 1.5.10 (2026-11-12)

- **Sofa knows the computer it's on, and uses its cores.** It used to count every core of the computer it was in and
  call every ARM processor an older one. Now (`sofa/hardware.py`), read once at the start:
  - the cores Sofa may use: a container's limit (Docker's `--cpus`) and a CPU set count, not only the computer's;
  - its memory, a container's limit (`-m`) counted too, and what's free now;
  - the processor by name on ARM as well ("4 x Cortex-A53" on a Pi 3, "4 x Cortex-A76" on a Pi 5, "4 x Apple
    silicon" in Docker on a Mac), and whether its cores can convert video quickly;
  - a Raspberry Pi's model, a virtual machine's or a container's name, and the chips that decode and encode video
    (VideoToolbox, VA-API by maker, the Pi's V4L2 codecs). The Server page's **This computer** panel shows them.
- **Gentle mode is for slow processors again, not for ARM.** Only Intel's AVX2 was looked for, so a Pi 5, an ARM
  server and Docker on a Mac with Apple silicon were "an older processor" and in gentle mode all day (15 pictures a
  library read instead of 120, the heavy work only at night). Now an ARM core before the Cortex-A76 counts as slow
  (a Pi 3's and a Pi 4's: gentle, as before); a Pi 5's, a server's and Apple's don't. Intel and AMD: AVX2, as before.
- **Background work is spread over the cores** (reading files' details, the pictures taken from videos, a movie's
  or show's own cover checked against its video, artwork resized for the screens): half the cores, four at most, so
  whoever watches has the rest; **one at a time on a small board** (a Pi 3, or 1 GB: it plays the video itself, and
  four busy cores brown out a weak supply), and one while Sofa converts something for someone; never more than its
  free memory takes. Each ffmpeg gets its share of the cores and runs behind whoever watches (`nice`).
  - Measured on a stand-in for a Pi 4 or 5, not a Pi (a Linux VM on this Mac with four of its cores and 4 GB): 300
    shows of 10 episodes, 800 movies with covers of their own, offline, gentle mode off, one full read from nothing
    (120 pictures taken from episodes each time). 1.5.7: 96 to 135 s (three runs: the Mac was busy with other
    work), one core busy. 1.5.8: 65 and 75 s with the two it chose, 1.8 cores busy; 52 s made to use four, 2.8
    cores; 84 s made to use one. Most of a first read was covers checked one at a time against their videos
    (ffprobe each: 100 of 135 s); they're checked several at once now, the ids still given in order.
  - The pictures themselves, 24 from a video: 5.8 s one at a time, 2.9 s two at once, 2.2 s four at once.
  - On a 1 GB stand-in (one at a time, as on a Pi 3) the same read takes what it took: 80 s on both.
- **A library read is lighter.** Each show looked at every item read so far to find when it was added: that grew as
  the square of the library, a third of a quick read of 22,000 files. And every episode's folder was read again for
  it (a season of 20 episodes: 20 times), its pictures looked for one by one: on a drive, a seek each. Now each
  folder is read once a read. The quick read of 22,000 files on this Mac: 18.1 million function calls to 7.8
  million, 25,000 folder listings to 3,000; 9.7 to 11.2 s before and 4.0 to 6.1 s after, back to back (the Mac was
  busy with other work, so the times are rough, the counts aren't).
- **Memory goes back.** What Sofa frees goes back to the system (Python and the C library keep it for later;
  `malloc_trim` on Linux), after each library read and every half minute, after Python's cycle collector every other
  minute (what a request leaves in a reference cycle waited for it). Sofa on a Sofa Box, on a 1 GB stand-in: 28 MB
  instead of 40; over ten rounds of an evening (Sofa, two apps, Home), 28 to 31 MB, where 1.5.7 grew 31 to 38 in eight.
  - Live TV's channels share what thousands of them have in common (their list's name, their group, no headers of
    their own): 10,000 channels held 10.4 MB, now 8.9.
  - The details read from the files next to a video (`.nfo`, `.info.json`) aren't kept for a video with none (most of
    them), and at most 20,000 are.
  - **One conversion for watching at a time on a computer with 2 GB or less, or two cores**, whatever the setting:
    one 1080p conversion held up to 402 MB on a four-core stand-in, so two can't fit in 1 GB.
- **A report says it** (Server → Activity → Download a report): `This computer` (cores, of how many, memory, the
  processor, a Pi's model, a VM or container, video chips), `Background work` (how many at a time, ffmpeg's threads,
  conversions at once against the setting, gentle mode), `Memory` (free of how much, Sofa's own now and the most it
  has had, how often anything waited for memory lately on Linux) and `In Sofa's memory` (the library, Live TV's
  channels and checks, the archive's channels, the files' details, by size).
- `SOFA_WORKERS` sets how many at a time (for measuring).
- On Windows (1.5.9), the processor, its AVX2 and the memory come from Windows itself, and a still taken from a video
  runs below normal priority there as everywhere else.
- The report hint (Server → Activity) says to send it to whoever helps you.

## 1.5.9 (2026-11-12)

- **Sofa for Windows.** An installer for Windows 10 (1809) and 11, 64-bit, that brings its own Python and ffmpeg
  ([docs/install.md, "On Windows"](docs/install.md#on-windows); how it's made: [deploy/windows](deploy/windows/README.md)).
  - It installs for you alone (no administrator needed) and asks where your library goes. Before Windows asks for
    permission, a page says what the one firewall rule is for: Sofa's own Python may take connections from TVs and
    phones on private networks, never public ones.
  - Sofa waits by the clock. Click its icon to open it; its menu has the address for phones and TVs, Restart, Stop,
    Start with Windows, the log and the Inbox folder. It starts when you sign in (unless that's unticked), starts again
    if it stops, and stops cleanly on Quit, signing out and shutting down, with every ffmpeg it started.
  - Uninstall it from Settings → Apps: it asks before deleting Sofa's own data and never touches your library.
  - GitHub builds it from every change and runs it once (installed, started, asked for its page, quit, uninstalled)
    before keeping it. On main each version gets a release (`sofa-v1.5.9`), and `sofa-for-windows` always has the
    newest. It isn't signed yet, so SmartScreen asks: More info, Run anyway.
- **The server itself on Windows**, with one code base (what only Windows needs is in `sofa/windows.py`):
  - ffmpeg is found as `ffmpeg.exe`: Sofa's own, winget's, Chocolatey's, Scoop's, or on PATH.
  - Pictures were made with `nice`, which Windows doesn't have: they weren't saved. Background work now runs below
    normal priority there instead.
  - Bonjour through Windows' own DNS-SD service (no Apple Bonjour needed), staying awake through Windows itself, the
    drive letters under Server → Storage, the CPU and memory from Windows, how busy the computer is (Windows has no
    load average), and the addresses phones use.
  - Video converted for iPhones, iPads and Safari (HLS) had its first part written to the wrong folder on Windows
    (ffmpeg looks for "/" in the playlist's path), so it wouldn't have played: ffmpeg is given those paths with "/".
  - A file that's open somewhere (Sofa reading it that moment, an antivirus, Explorer still copying it) is replaced or
    renamed once it's closed, waiting up to a second, instead of failing at once as Windows otherwise does.
  - After an update the app starts the new version (a Windows process can't replace itself). Sofa's port is its own:
    a second Sofa can't quietly share it. Text is UTF-8, as on a Mac.
- **Everywhere:** SSDP keeps answering after a reply nobody took (Windows reports those as an error on the next read,
  which stopped the listener).
- Sofa's tests run on GitHub's Windows machines too (Python 3.9 and 3.12, and the installer's 3.14); the box's tests
  are skipped there, with the reason. `tests/test_windows.py` covers the app, the job object, the clean stop and
  Windows' own APIs.
- Not on a real Windows PC yet: GitHub's Windows Server machines are the only ones that have run it.

## 1.5.7 (2026-11-11)

- **Live TV has one look: the bar of eras, then a guide.** Live now, your starred channels and what a search finds
  are now a dial in the guide's own shape, the way Classic Cinema and the decades have looked all along: a row a
  channel with its number and one bar, and the channel in view up top with its logo. The grid of logo cards is gone.
  - The bar of eras is always there, with **Live now** as one of the eras, whether or not Classic Cinema and the
    decades are switched on.
  - Every channel has a number. Sofa's own lineup keeps 2 to 99; a channel list's channels start at 101, by group
    and name, and a number is the same channel for everyone (a profile that can't see a channel sees a gap). Type a
    number on Live TV and it tunes there; a Sofa Box's player shows the number in its banner.
  - On a TV the page no longer scrolls under the remote: the rows scroll and the channel in view stays in view.
    Right from a row is its star (OK makes it a favorite); **Flip** tunes to one at random.
  - Lighter on a Raspberry Pi 3: no picture in a row (the grid loaded sixty logos at a time), one logo at a time
    for the channel in view, rows drawn as the remote comes near them.
- **Channels that don't answer are left out.** Free channels come and go, and a list is full of ones that are gone.
  - Sofa looks at each channel now and then, the way a viewer at home opens it: its playlist, one quality, and the
    first bytes of the newest part. A few at a time, never two at once at the same site, one at a time on a slow
    computer, and only while someone has opened Live TV here in the last week.
  - A channel that misses two looks in a row is left out of everyone's list, and of the list TVs on the network get.
    It's looked at again every few hours and is back by itself when it answers.
  - Tune in to one that doesn't answer and it's out at once. When a channel starts and then won't play, the player
    tells Sofa, which looks itself before believing it (and never on a Visitor's say-so).
  - A favorite stays in your list, marked **Not answering right now**.
  - An admin sees how many are left out, with **Show them anyway**, on Live TV; **Server → Live TV** has the switch
    (**Leave out channels that don't answer**, on by default), how far the looking has got, and **Look now**.
  - When the home's own internet drops (several sites in a row unreachable, nothing answering in between), nothing
    is marked and what was marked on the way is taken back.
  - What's remembered is in `data/live-health.json`: channel ids and verdicts, no names and no addresses. Nothing
    about it is written to the activity log but one line with the count.
  - Unchanged: a channel from the internet can't lead Sofa into the home network; away from home and for Visitors a
    channel plays straight from where it's streamed or not at all; channels that ask for a made-up browser name
    stay out, and aren't looked at, unless an admin allowed them.
- For other apps: `/api/live` gives each channel a `number`, marks the ones shown though they don't answer with
  `down`, and gives an admin `down` (how many) and `health`; `/api/live?down=1` (an admin) lists them anyway;
  `POST /api/live/failed/<id>` asks Sofa to look at a channel next; the setting is `live_check`.
- Tried in a browser on a Mac at a TV's size and a phone's, with a stand-in channel list. Not on a Raspberry Pi and
  not against the public lists.

## 1.5.6 (2026-11-11)

- **Retro TV's decades are on by default again.**
  - The 2009–2012, 2000s, 90s, 80s, 70s, 60s and 50s tabs (TV as it went out: Saturday mornings, music TV, kids'
    channels, commercials and all) are back in Live TV without anyone having to find a switch. From 1.5.0 to 1.5.5
    they were off unless turned on.
  - A Sofa that updates gets them switched on once. An "off" saved by 1.5.0 to 1.5.5 was that version's default,
    and Sofa can't tell it from a choice. Turn them off in **Server → Live TV → Retro TV** (The decades, as they
    aired) and they stay off.
  - Unchanged: the recordings play straight from a public video library to the screen and never through Sofa,
    which keeps no copy; the public library's visitors never get them; **Work offline** turns them off with the
    rest of Live TV's Retro TV.

## 1.5.5 (2026-11-10)

- **Sofa in Docker.** A `Dockerfile` (Python 3.12 on Debian 13 with Debian's ffmpeg, a non-root user, nothing else)
  and a `compose.yml`: `docker compose up -d` with `./data` for Sofa's data and `./media` for the library, on the
  computer's own network so TVs find it and the home-network rules work. The image is published as
  `ghcr.io/krintoxi/sofa` on every change to main (`.github/workflows/docker-image.yml`). The first start writes a
  `config.json` that points the library at `/media` (`deploy/docker/entrypoint.sh`).
- In a container, **Server → Updates** says to pull the new image (`docker compose pull && docker compose up -d`)
  instead of offering **Update now**, and the API refuses to swap files in place; the Updates tab shows the commit
  the image was built from.

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
