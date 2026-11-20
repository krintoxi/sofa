# Sofa: what's new

Sofa's own version is in `sofa/__init__.py` and on **Server → Updates**. Sofa Box OS, the Raspberry Pi TV box,
has its own numbers and list: [deploy/sofa-box/CHANGES.md](deploy/sofa-box/CHANGES.md).

A change to Sofa's code (`sofa/`, `client/`, `sofa.py`) gets a new version: raise `__version__`, add a section
here, then `python3 tools/sofa-version.py` (a test checks it was done).


## 1.5.39 (2026-11-20)

What ripping programs leave, dropped in the Inbox, is filed properly:

- **A disc's titles named like title_t00.mkv** (B1_t00.mkv, title00.mkv, VTS_01_1.mkv...) in a folder: the longest is
  the film, named after the folder ("Heat (1995)", or a disc label like THE_MATRIX or ARRIVAL_2016), and the others go
  into its folder's Extras, where they don't show up as films of their own. One on its own in the Inbox goes to Needs
  Review, since nothing says what it is: they used to become a film called "title t00".
- **A whole ripped DVD**: an .iso, or the folder a program saved the disc to (with VIDEO_TS in it), becomes one movie
  with every sound and subtitle track and the chapters, nothing converted (Sofa's own disc reader). The DVD's files
  go to Deleted once it's saved, kept a while as anything deleted is. Its VOB pieces used to become a film called
  "VTS 01 1", and an .iso went to Needs Review.
- A disc of a show's episodes (its name says Season, S01 or Complete) goes to Needs Review, to be opened with Save
  from a folder or disc image and its titles given their episodes. A copy whose video is still scrambled goes there
  too, with the reason.
- Tried with made rips and discs (`tests/test_inbox_rips.py`); not yet with a real ripping program's output.

## 1.5.37 (2026-11-20)

Free channels from the start.

- **Sofa's free channels.** Live TV has channels from the first minute, on a Sofa Box with no server and on any
  Sofa: 18 channels their broadcasters stream free, for anyone, on their own websites. News (Bloomberg TV, Newsmax,
  Scripps News, Court TV, Cheddar News, Yahoo Finance, FOX Weather, DW News, Al Jazeera English), classic TV (Retro
  TV Network, Heartland, Rev'n) and Spanish-language news (France 24 Español, Canal Once, ADN Noticias, TeleFórmula,
  América TeVé, TVN). With Classic Cinema and the decades, a new box has a full Live TV before any list is added.
- **Each one checked**: an https stream from the broadcaster's own servers, its page and publisher written down,
  played the way a browser on another site would (`tools/demo-seed.py channels sofa/freechannels.json --check`).
  Never a FAST service's stream (Pluto, Samsung TV Plus, Plex, The Roku Channel, Tubi, Xumo...), a made-up browser
  name, or a channel blocked outside its country.
- **Numbered after a household's own**: from 101 on a Sofa with no lists, else from the next hundred after them, so
  no number anyone knows moves.
- **Server → Live TV** shows them as a list of their own, **Sofa's free channels**: **On / Off** (it's never
  removed, only switched off) and **Visitors** (off until an admin turns it on; Visitors then play them straight
  from the broadcaster). Never adult. Not on the public demo, which keeps its own list.
- The rules for every channel list now also catch a FAST service's feed by its address (`.../...Samsung/...`), any
  address at mjh.nz, and Pluto's short links.

## 1.5.36 (2026-11-19)

Saving adult videos: back, and more of it.

- **Free to keep** (Adult → Free to keep, admins): adult films anyone may download and keep, from the Internet
  Archive. Pick a kind (vintage and stag films, pin-up and burlesque, exploitation, fetish, or everything) and how
  many (5, 10, 25 or 50), and **Save into Adult**, or save them one by one. Only films the Archive itself marks adult
  and its uploader marks public domain or Creative Commons, and old enough to be free (before 1978): a recent studio's
  film marked "free" isn't the uploader's to give. Anything whose title, subjects, description or file name suggests
  someone under 18, family, no consent, or drawn characters is left out. What was saved before is skipped. Progress
  is on the page.
- **Save from a link saves adult videos again.** 1.5.30 took it out; it's back: **+ Add a link** in Adult, **Put it
  in the Adult section** in the Save box, **+ Add a link to Adult** and **Send to Sofa (Adult)** on Server →
  Downloads. Saved adult videos go to `Inbox/XXX` and are filed in Adult; Activity names no title or link. yt-dlp is
  no longer told to skip videos its site rates for adults.
- **Several links at once**, one a line, and **how many** of a playlist, a channel or a page of videos to save (5,
  10, 25 or 50).
- Only for an admin who can see Adult and said they're 18 or older; never visitors, guests, Kids or a public Sofa.
- An empty Adult section shows its Top lists, Kept and Free to keep pages instead of only "Nothing here yet".


## 1.5.35 (2026-11-20)

Adult Live TV's categories make sense. (On top of 1.5.31, Adult Live TV's working channels only.)

- **Seen on the owner's Sofa (read-only):** Adult Live TV's categories were News, Movies, Kids, Bangla, Lifestyle,
  Music. One of three lists marked Adult, named "Github xxx", is ordinary TV: 94 channels, 89 in ordinary groups (BBC
  News, cartoons, Bollywood, Bangla stations), none with an adult group or name. The two real adult lists give no
  groups at all, so their 42 channels were all "Everything else".
- **A list marked Adult that is ordinary TV is no longer on the Adult page.** Ten or more channels, four in five in
  ordinary groups, and not one group or name that says adult. Its channels stay out of Live TV (the owner said
  Adult) until the owner says which it is; the Adult page and Server → Live TV say so under its name, and pressing
  **Adult** puts them in Live TV. A channel it shares with an ordinary list stays in Live TV (it used to leave it), and
  its channels aren't checked ahead of others as adult ones.
- **Categories by network.** The real adult channels are grouped by the first word their names share ("XXX",
  "CamNet": three or more channels), else by their list's own group, else **Other channels**. Never by the words
  after it. Biggest first, then All channels; the same category pane as Live TV.
- Seen in Chrome on a Mac with stand-in lists shaped like the owner's (invented names). Not on the owner's Sofa, a TV
  or a Sofa Box.

## 1.5.34 (2026-11-19)

Adult Live TV shows only channels that play.

- **One plain list of what played lately.** Adult Live TV lists, by name and without categories, only the channels
  Sofa saw play in the last two days. A channel whose last look got no video leaves at once and comes back when it
  plays again.
- **Its channels are looked at first.** An adult channel not looked at lately goes ahead of every other channel in the
  background check (still a few at a time, one site at a time). Opening the page starts the check.
- **It says how it stands.** With nothing to show yet: how many of its channels were checked so far (the page fills in
  by itself), or that none played at the last look, or that checking is off. Server → Live TV says under each adult
  list how many of its channels play, didn't, or aren't checked yet.
- **A list that can't be read says why plainly**, for every list: a site name that doesn't exist any more, a page that
  answered 404, a site that took too long, a certificate that ran out.
- The rules are as before: adult channels only in the Adult section, for people allowed it who confirmed their age, at
  home, never for visitors, Kids profiles, guests, a TV on the network or a public Sofa.

## 1.5.33 (2026-11-19)

Two lawful ways to keep a disc Sofa can't read (a copy-protected DVD), on its page:

- **Get it free**, when the film is free to keep and the Internet Archive has it: public domain, CC0, or a Creative
  Commons licence that allows copying (as the archive marks it), or a feature film made before 1929. Sofa downloads
  it into Movies, named and with its poster. His Girl Friday, Night of the Living Dead, Nosferatu and The General are;
  a studio film from 2000 isn't, and isn't offered. What's asked of archive.org: the film's name and year.
- **Record it from a DVD player**: any DVD player, its yellow, red and white plugs in a USB video capture stick, the
  stick in the Sofa computer or a Sofa Box. Sofa records what the player plays, in real time, into Movies, named from
  the disc's page and stopping by itself at the film's length (or on Stop; what's recorded is kept). Standard
  definition, one sound track. Nothing on the disc is decrypted: the player plays it as it would to a TV. Some discs
  send an analog copy signal (Macrovision) that makes some sticks' picture flicker; Sofa does nothing about it.
  **Record from a capture device…** is on the Server page too, for a VCR or a camcorder. The computer's own cameras
  and screens aren't offered.
- Tried with a stand-in for the capture stick and archive.org's own answers. **No capture stick has been tried yet**
  (Linux's, the Mac's and Windows's device lists are read from their real formats in the tests), and no free film was
  downloaded in full.

## 1.5.32 (2026-11-19)

- **A disc in the drive shows on Home** (admins), and opens a page of its own that looks like a movie's: what it is,
  found as a library movie is (a DVD labelled RULES_OF_ENGAGEMENT is "Rules of Engagement", 2000, with its poster
  and summary; a label with a year in it, "Summer at the Lake 2004", gives the year), how long, its chapters, its
  sound and subtitle tracks, and what else is on the disc.
- **Save to Movies in one press**, from that page: the disc's film (its longest title) under the name found for it.
  A music CD: Save to Music, named as the disc's own text has it. The full choices (episodes, another title, the
  names) are a press further, as before.
- **Watch the DVD in Sofa's player**: Play on its page, or on any title of it. Sofa reads it as it saves it (the same
  reader) and converts it as it plays, so it plays in every browser. **Save this disc** is in the player's bar while
  it plays: one press, and it saves while you watch.
- **Save from a folder or disc image**: a DVD copied to the computer as a folder (with VIDEO_TS in it), an .iso, or a
  music CD's .cue. It shows up like a disc in the drive, with its page, Play and Save, and is saved the same way: every
  sound and subtitle track, the chapters, nothing converted. On the Server page, and on a copy-protected disc's page.
- **A copy-protected disc's message is shorter**, and points to that: "This DVD is copy-protected, so Sofa can't read
  its video. Already have it as a folder or a disc image? Save from a folder or disc image files it like any other."
  Sofa still doesn't decrypt a disc.
- Tried on the iMac's own drive with a commercial DVD in it (through a copy of this version on another port; the
  iMac's Sofa wasn't touched): found and named with its poster, every track listed, said to be copy-protected. Play
  and both kinds of Save were tried on made discs. Not on a Pi, and not on Windows with a real drive.

## 1.5.30 (2026-11-19)

The Adult section.

- **More on every video.** Under a card: the file's size, its sound's languages ("EN + ES") and CC; who's in it
  comes first in its line. A video's page lists its languages, above **This file**; so does a series' page and its
  episodes.
- **Sort and filter.** Two more sorts, **Largest** and **Best picture**; filters by picture (4K, 1080p, 720p, SD),
  length, the sound's language, and played or not, each with how many and only the choices that list has.
- **Cards or a list.** A row per video: performers and studio, tags, length, picture, size, languages, added.
- **Preview sound on / off**, next to the search box (the previews have had sound since they were remade; the switch
  was only on a title's banner).
- **Performers and tags from the file's own tags** (artist, genre) when no .nfo, saved link or name gives them.
- **"I am 18 or older", once for each person.** An admin's Adult switch now lets a person be asked; the Adult
  section opens for them when they say themselves that they are 18 or older. Until then the server sends their
  profile nothing adult. Sofa keeps the day, and Server → People shows it. **People who already had Adult are asked
  once after this update**, in a browser: the Fire TV and Roku apps can't ask, and show no Adult section until it's
  answered. This is a person's own word, not a check of their age.
- **Top lists** (Adult → Top lists): the 25 most watched videos of a category at a free site, this week, this month,
  all time or best rated. **Off until an admin switches a site on.** Sofa reads the site's public API for the lists;
  a video plays in the site's own player, in your browser, straight from the site, with a link to its page there.
  Sofa never fetches, keeps or passes on the video. One site is built in, Eporner, whose terms allow exactly this;
  [docs/adult-sites.md](docs/adult-sites.md) has what its terms say, how Sofa keeps to them, and the sites left out
  and why.
- **Kept** (Adult → Kept): keep a link from a top list (title, the picture's address, the site, the day), listed by
  day, with what you played lately and didn't keep. Once a day Sofa asks the site which it has removed, and those go.
- **No Save for those videos.** The sites' terms forbid downloading, so there is none.
- **Save from a link no longer saves adult videos.** Gone: **+ Add a link** in the Adult section, "Put it in the
  Adult section", "+ Add a link to Adult" and the "Send to Sofa (Adult)" bookmark (an old one now gets a plain
  answer). A video its site marks as for adults only is skipped (yt-dlp's `--age-limit 17`), which also skips
  age-restricted videos at other sites such as YouTube. Links an older Sofa had queued for Adult are not downloaded.
  Videos already saved stay, with their details. The free adult sites' terms forbid downloading their videos, and
  Sofa Boxes are to be sold.
- Only for people with the Adult switch: never visitors, guests, Kids profiles or a public Sofa. A request to Sofa
  never waits on the site (lists are read in the background and kept half an hour), and a site that's down is a page
  that says so.
- Tested with a stand-in for the site (`tests/test_adult_top.py`, `tests/test_adult_pages.py`): nothing in the tests
  reaches the internet. **Not done:** the real site's player has not been opened from Sofa, so whether it plays inside
  Sofa's page (and whether the site asks for an age check there) is unseen; nothing was seen on a TV, a Sofa Box, a
  phone in the hand or Safari. Seen in Chrome on a Mac only.
## 1.5.29 (2026-11-19)

- **Save this disc.** Put a DVD or CD in the Sofa computer's disc drive (built in, or on USB) and **Server → Overview**
  shows what it is and what's on it, with **Save this disc**: where it goes and what it's called, then it's in the
  library like any other file. No other program needed.
  - **A music CD:** each track becomes a FLAC file with every bit of the disc's sound (each file is checked against
    what was read before it's kept), named and tagged, in `Music/<Artist>/<Album>/`. Names come from the disc's own
    text where it has any; **Look the names up** asks MusicBrainz (no key; what's sent is where the disc's tracks
    start, nothing else; Server → Settings → **Music CD names from MusicBrainz** switches it off).
  - **A video DVD that isn't copy-protected** (home-made discs, and the few sold without protection): the title you
    pick becomes an MKV with the disc's own picture and sound as they are, every sound and subtitle track with its
    language, and the chapters. As a movie (`Movies/<Title (Year)>/`), or several titles as a show's episodes from
    the season and episode you give. Several clips on one title, each with its own clock on the disc, come out as one
    that plays through.
  - **A data disc:** its videos, music and subtitles are copied to the Inbox, where Sofa files them as usual.
- **Copy-protected discs are not saved.** A commercial DVD (CSS) or a Blu-ray (AACS) is said to be copy-protected, on
  the page, and has no Save. Sofa has nothing that undoes copy protection and doesn't fetch or call anything that
  does: in the United States that is circumvention (17 U.S.C. 1201), whoever owns the disc. It tells by what the disc
  says in the clear (each pack of video is marked scrambled or not, and Linux and Windows let Sofa ask the drive for
  the disc's own copyright record), checks again on every pack as it reads, and never sends a drive the handshake
  that unlocks a disc.
- **Sofa's own reader.** The disc is read by Sofa's code (`sofa/dvd.py`, `sofa/cdaudio.py`, `sofa/iso9660.py`: the
  DVD's tables, its packs, a CD's frames), and ffmpeg only packs what was read. Not the usual DVD library, on
  purpose: it loads a decrypting library by itself on a computer that has one. One function reads a title's stream
  (`dvd.read_title`), and that is the one place to change how a title is read.
- **Careful with the disc and the library.** The drive is only read, and opened shared: never locked, unmounted or
  ejected, so that the disc can still be played (made that way; not tried with a player running). A disc or drive
  pulled out in the middle ends the save with a plain message: what was finished stays, what was half done is
  removed. Nothing is written over a file that's there, and a save can be stopped. One disc at a time; the library
  is read again when each save ends, without the next disc waiting for it.
- **Not saved yet:** a DVD title filmed from more than one camera angle (it's listed, with that reason), DVD menus,
  DVD-Audio, Video CDs, and Blu-rays of any kind.
- **Proven on:** discs made for the tests (a music CD's image, an unprotected DVD's image and one with its packs
  marked scrambled; `tests/test_disc.py`, on Python 3.9, 3.12 and 3.13, ffmpeg 7.1 and 9.0, a Mac and Debian); a DVD
  authored by dvdauthor, read by Sofa's reader; a made DVD image mounted on a Mac and saved from where the Mac put
  it; a save slowed to a minute and a half while the library was tidied and read again every few seconds; PCM and
  MPEG sound as recorders write them; and Linux 6.12 in a virtual machine with two emulated USB disc drives: found, asked for their status and the
  disc's copyright record, the DVD read from `/dev/sr0` and saved, the marked one refused. The kernel's own header
  agrees with the numbers Linux is asked with.
- **One real disc so far:** a commercial, copy-protected DVD in an iMac's built-in drive (macOS 13, Python 3.9). Its
  titles, chapters, sound and subtitle tracks were read correctly, it was said to be copy-protected, and nothing was
  saved.
- **Not yet:** saving a real unprotected DVD, and any music CD from hardware on any system (a virtual drive can't
  hold one): a Mac's CD folder, Linux's and Windows's calls for a CD's sound and CD-Text are written from their
  documentation and tested against stand-ins. Windows has no real drive behind it.

## 1.5.28 (2026-11-19)

- **Previews with purple and green lines are put right.** On some computers every picture ffmpeg resized came out
  striped: the clip that plays when you point at a card, the little pictures above the seek bar, and a video converted
  to a smaller size while you watch. A picture kept at its own size was fine, which is why some previews looked
  perfect and others didn't. The cause is the ffmpeg, not the video: one built without the assembler
  (`--disable-x86asm`, as `tools/build-ffmpeg.sh` builds it) resizes, on the processor we saw it on, with a routine
  that is wrong. 10-bit, HDR and odd sizes had nothing to do with it.
- **Sofa asks its ffmpeg once, with a plain gray picture,** whether it resizes right. If not, every command that makes
  or resizes a picture tells it not to use that part of the processor (`-cpuflags -mmxext`); an ffmpeg that resizes
  right is asked exactly as before. Activity says so once.
- **What was already made is made again by itself,** once, and only on a computer whose ffmpeg failed that check: the
  clips and the seek-bar pictures there are cleared and come back as they're asked for and in the background. Nothing
  to delete by hand; elsewhere nothing is remade. A browser kept a clip or a sheet for a week: their addresses now
  carry Sofa's version, so the ones it kept aren't shown after an update.
- **"Sofa can't reach secure websites" no longer comes up because of a Live TV channel.** The Server page showed it
  (and blamed Python's certificates) whenever any one address failed its certificate check, and Sofa looks at
  channels to leave out the ones that are off the air: among a few thousand there are always some whose certificate
  ran out, is for another name or is one they signed themselves. Now it's only for a site Sofa itself asks (details, artwork, updates), it says
  which of three things is wrong (Python has no certificates, this computer's list of authorities is old, or its
  clock is off), and it goes once such a site answers. Every certificate is still checked, and a channel with a bad
  one is still turned away; its reason now says so ("its certificate has run out") instead of "it can't be reached".
- Measured on an iMac from 2011 (Core i5-2400S, macOS 13, ffmpeg 7.1.1 built there): at least 36 of 38 resized clips
  and 39 of 43 sampled seek-bar sheets had lines, none of 39 clips kept at their size, none of 163 thumbnails and covers (those
  go through macOS's own resizer). With the option, a clip, a sheet and a 20-second conversion of the same film come
  out clean in the same time (3.6 s, 2.3 s, 6.4 s; before 3.7 s, 2.7 s, 6.4 s). Its Python reached every site Sofa
  asks; 61 of 1,945 channel hosts failed their certificate check. This version's own code, run there beside
  the server on a made gray video, found the fault in half a second and made a clean clip and sheet; the server
  itself is still on 1.5.26, so its library hasn't been remade yet. Tests: `tests/test_resizing.py` (with a stand-in ffmpeg that spoils what it resizes),
  `tests/test_secure_sites.py`.
## 1.5.27 (2026-11-19)

- **Live TV has a new page.** Live now is three parts side by side: the categories with how many channels each holds,
  the channels of the one you chose (a row a channel: its logo, its number, its name), and the channel in view in its
  own pane. On a computer or a phone the channel plays in that pane without sound while you look around ("No picture
  here" turns that off); a TV and a Sofa Box show its logo there. On a remote, left goes to the categories and right
  comes back to the channel. A phone gets the pane, then the categories in a row, then the channels.
- **Categories you can use.** Lists name their groups every which way and put a third of their channels in "General"
  or "Undefined". Sofa now folds them into a short set in a fixed order (News, Sports, Movies, Series, Entertainment,
  Kids, Music, Documentary, Lifestyle, Learning, Faith, Shopping), then a list's own groups (a country, a language),
  then **Everything else**; **★ Favorites** and **Last watched** come first. "SPORTS" and "Sports" are one, emoji
  are gone, "News;Business" is News, a channel in a catch-all group goes by its name where the name says what it is,
  and a group called "All" no longer makes a second All button. Names lose a list's marks ("(720p)",
  "[Not 24/7]"). The same channel from two lists, or in two picture sizes, is one row: the first that answers plays,
  and when it doesn't the player in a browser tries the other before giving up (a Sofa Box's own player doesn't yet). Channel numbers follow the new order, so they
  changed once with this version.
- **Adult Live TV.** A channel list marked **Adult** has its own page in the Adult section (**Adult → Live TV**), and
  its channels are nowhere else: not in Live TV (they used to be mixed in for anyone allowed to see Adult), never for
  visitors, Kids profiles or guests, never for a TV on the network, and never away from home. Server → Live TV has
  an **Adult** switch on every list (it was only a box to tick when adding one), says so when a list's name looks
  adult and isn't marked, and ticks the box by itself for such a name. Marking a list Adult ends sharing it with
  visitors. An adult list isn't named in Activity, "Watching now" says "something private", and a Sofa Box's player
  and its phone remote get the channel's number, not its name. A channel is adult when any list holding it is.
  Adult channels are numbered from 9001, so adding them moves no other channel's number.
- **Changing channel.**
  - **On a Sofa Box, up and down did nothing in a list of more than 600 channels** (the box was handed the one channel
    alone): it now gets the 600 around the one you're on.
  - When you tune in, Sofa fetches the playlists of the channels next up and next down, once (a few hundred bytes
    each, no video), so the next change starts from what's already there. It helps while you flip through channels:
    in a browser, on stand-in channels 250 ms away, the first picture came in about 0.45 s instead of 0.67 s when the
    next change came within four seconds. A change after watching for a while takes as long as it did. Never for a
    tuner or a list at home.
  - Up and down now go through the channels in the order the page shows them.

## 1.5.26 (2026-11-19)

- **Sofa in Spanish.** On a phone, computer or TV set to Spanish, the pages you use every day are in Spanish: the
  header and menus, Home, Shows, Movies, a show's or movie's page with its file's details, search, My List, signing in, Who's watching, Theme,
  Play on, downloads, and the player with its sound, subtitle and options menus. Dates, counts ("3 temporadas, 24
  episodios") and genres too. Latin American Spanish, "tú".
- **Language names follow it too** (1.5.25 went by the device alone): with Español chosen, tracks and the language filter
  say Inglés, Español (Latinoamérica), Francés.
- **Your choice, per device:** Theme → **Language**: Device, English or Español. A Sofa Box's browser is set to
  English, so that's where to pick Español on a box.
- **What stays as it is.** A show called "Home" is still "Home", a movie called "Play" is still "Play", and so are
  episode titles, descriptions, file names and people's names: only Sofa's own words change.
- **English costs nothing more.** The Spanish is one file (`client/es.js`) that only a device asking for Spanish
  fetches. It puts into Spanish what the page draws, as it's drawn, so the pages themselves are written once.
- **Still in English:** the Server pages and the admin's Manage and Find details, Live TV's guide and recordings,
  Games, Music, the Adult section, watching together, a Sofa Box's own Home screen and its player's screen, and the Fire
  TV and Roku apps. A sound or subtitle track's own name stays as the file has it.
- Tested in Chrome in both languages with a library whose titles are the app's own words, and every Spanish entry is
  checked against the app's English, so a change of wording is noticed (`tests/test_spanish.py`). Timed with the
  processor slowed sixfold, English and Spanish in turn on a library of 13 files: Home to Movies in 23 ms and 24 ms.
  Not timed on a Raspberry Pi or a large library, and the Spanish hasn't been read by a second Spanish speaker.

## 1.5.25 (2026-11-19)

- **Sofa says what language each title is in.** A movie's or show's card is marked when it has two or more ("EN + ES")
  or one that isn't your library's usual language; its page lists the sound's languages and the subtitles'; the Movies
  and Shows pages filter by language and by "Two or more"; and the player's menu lists tracks by language ("Spanish
  (Latin America) · AAC Stereo", "French · forced") where it listed the file's raw tag ("spa", "fr.forced").
  Languages are named in the device's language: English and Spanish are Sofa's own words, the rest the browser's.
- **How it knows, and what it won't guess.** A track's language tag first; then the track's own name ("Español
  Latino"); then markers in the file's or folder's name (`[eng+spa]`, `LAT`, `CASTELLANO`, `Dual Audio`, `VOSE`, `SUB
  ESP`), only in brackets or after the year, never in the title's own words. What's from a name is marked so (a dashed
  mark, "from the file's name"), and with two unlabelled tracks the title has both languages while neither track is
  labelled. A tag wins over a name. A track nothing labels is "not labelled". The language a title was made in (TVmaze,
  TMDB) is shown apart as "Made in" and never stands in for a track: your copy may be dubbed.
- **Tidy names keep what the old ones said.** The Inbox and the tidying rename "Coco.2017.1080p.LAT.ENG" to "Coco
  (2017)": the languages in the old name are kept with the title now. Names tidied before this version are gone.
- **This file, in full.** Under a movie's page, and under each episode's new **Details**: resolution and HDR, the
  video's and sound's formats, channels, bit rates, every sound and subtitle track, size, length, chapters, when it was
  added, and whether this device plays it as it is or Sofa repackages or converts it, with the reason.
- **Your language is remembered across files.** A sound track chosen in Spanish is kept as Spanish, whichever way the
  next file tags it (`spa`, `es`, `es-419`); earlier choices still count. A Sofa Box's Menu names tracks the same way,
  and the box keeps the sound language chosen there for the next file it plays as it is (both with the next Sofa Box
  OS, and not yet run on a box; a video Sofa converts for the box still has one sound track and no choice in its
  Menu).
- **Existing libraries are read in the background**, a few files at a time and not while Sofa converts for someone,
  and the list the apps fetch changes once every ten minutes at most while that goes on, not once a file. Files Sofa
  had read before are read once more for the frame rate, HDR and bit rates; until then their pages show what was known.
  A file that changes is read again.
- For apps: `langs` on the library's titles, `code` and `by` on `/api/play`'s tracks, and `GET /api/details/<id>`
  ([docs/api.md](docs/api.md)). The words of the apps themselves are still English only.
- Tested with real small files made with ffmpeg: tagged, named and unlabelled tracks, subtitle files, a tidied
  folder and an Inbox drop (`tests/test_languages.py`), and the box's Menu (`tests/test_box_languages.py`, without mpv).
  Not tried: a real disc rip with Dolby Vision or DTS-HD, and no Raspberry Pi has run it.

## 1.5.24 (2026-11-19)

- **The Server page no longer stops answering after "Check for updates".** Sofa looks for a new version by itself two
  minutes after it starts and every twelve hours. If an admin had pressed **Check for updates** less than twelve hours
  before one of those, that look waited on its own lock for ever, and every Server page after it waited behind it
  (they show the update's status): "The server is taking too long to answer", then, once that device had 48 requests
  waiting, **503** for everything it asked, Live TV included, until Sofa was restarted. Fixed, and the Server page's
  status no longer queues behind one that's stuck: after five seconds it shows the last one.
- **One channel that's gone no longer switches Live TV off.** Sofa stops asking the internet for three minutes when a
  name can't be looked up, which is right for its own lookups and wrong for channels: free lists always hold a few
  channels whose site no longer exists. Sofa looking at one of those (or someone tuning in to it) turned every
  channel into "The channel didn't answer" for three minutes, hid working channels that were tuned in to meanwhile,
  stopped the look at the channels after a few dozen, and made a list added just then come up empty ("the internet
  can't be reached right now"). A channel or a list that can't be found is now only that channel's or that list's news.
- **Channel lists on and off.** Each list on **Server → Live TV** has an **On / Off** switch: off, the list stays
  there and none of its channels are in Live TV, for anyone; on, they're back. (The only switch there was
  **Visitors**, which is about the public library's visitors and changes nothing at home.) A TV or another browser
  with Live TV already loaded picks the change up the next time Live TV is opened, not five minutes later.
- **Adding, removing or switching a list never waits on a list's server.** These used to download every list again
  before answering, one after the other, up to 30 seconds each; a list that had never downloaded was tried again by
  every such click. Now the channels are put together from the lists as saved, a new list is fetched behind the
  answer (the page says "Sofa is reading it now" if it takes more than three seconds), and one reading runs at a time.
- **The Server page asks for the lists, not the channels.** Every ten seconds it fetched the whole of Live TV (about
  a megabyte with 5,700 channels) to show two short lines.
- **A channel that says nothing** is given up on after 10 seconds when someone tunes in, not 20, and Live TV itself
  gives up asking after 30 seconds instead of showing "Loading channels…" for ever.
- **When Sofa is too busy to answer, the log says so**: a connection turned away (503) writes one line a minute at
  most, with where each request is waiting (file and line in Sofa's own code, nothing of anyone's). `kill -USR1`
  writes the same on a Mac or Linux.
- Tested in `tests/test_live_lists.py`.

## 1.5.23 (2026-11-19)

- **Games is a shelf of real cards.** The page was fourteen grey cards with an emoji each. Now the game you were
  last in (or WYRD, the featured one) is across the top with its picture, and the rest are in rows by kind:
  Adventures, Action, Racing, Puzzles and tactics, Quick ones. A card is the game's own picture (taken from the game
  playing), its name, a line, its kind, 2D or 3D, who plays and with what, and **where you left it**, read from the
  game's own save in this browser ("Wren, level 12", "4 of 12 heists pulled"). Continue lists what you played last.
- **Three looks**, chosen at the top of the page and kept on this device: Marquee (wide pictures), Shelf (covers)
  and Index (a list). On a phone a card is a picture beside its words, so three fit a screen.
- The note that the games want a keyboard or a controller is gone: they have had touch controls since Sofa Box OS
  1.1.93, and each card says what a game is played with.
- Sofa serves the games' pictures at `/games/art/` (the Sofa Box's own, from its Home), to the same people as the
  games.

## 1.5.22 (2026-11-18)

- **A daily show's episodes are episodes.** The Inbox has long filed a show by date ("The Daily Show 2024 03 15", a
  recording of the news) as `Season 2024/The Daily Show S2024E315`: season the year, episode the month and day. The
  library couldn't read that code back (it reads seasons of up to two digits) and listed every one as an **extra** of
  the show: not among its episodes, and with no Skip intro. Now they're
  that day's episodes, with their date, in order. Those filed already are read right on the next scan, and so is a
  dated name put in a show's folder by hand ("The News Hour 2026-11-14.ts"), and a "Season 2026" folder.
- **Named by their day.** The apps name such an episode by its day ("Fri, Nov 13", or "Nov 13 · Storm Watch" when it
  has a title) and its season by its year ("2026"), not "S2026 E1113" or "Episode 1113". What follows the date in a
  file's name is the episode's title.
- **Recordings without an episode number** carry the guide's title for that day into their name ("The News Hour
  2026-11-13 Storm Watch"), and a second showing of the same title recorded that day is named with its time ("…
  11.00 PM"): the news at six and at eleven had one name, and the Inbox couldn't file the second.
- Tested with a real recording from the stand-in tuner, filed by the Inbox and read back by the library
  (`tests/test_tuners_dvr.py`), the names (`tests/test_naming.py`), and a daily show's page on the Sofa Box
  (`tests/test_box_recording.py`).

## 1.5.21 (2026-11-18)

- **A tunnel or proxy anywhere at home passes on the internet, not the home network.** Sofa took a proxy's headers
  (`X-Forwarded-For`, `CF-Connecting-IP` and the like) as a sign of the internet only when the connection came from
  this computer. A tunnel in its own Docker container connects from an address like `172.18.0.3`, which is the home
  network to Sofa. So everything through it counted as home: anyone on the internet could create the first admin
  account on a new Sofa, join as a guest, pair a TV, reach DLNA, or use a stolen admin cookie. The same went for a
  proxy on another machine at home, or a server passing the internet on over Tailscale. Now a request with a
  proxy's headers never counts as where the proxy is, whatever address it comes from, unless Sofa was told about
  the proxy (`trust_proxy`). When told, Sofa takes the visitor's address from the proxy, as before; a proxy that
  isn't this computer can't pass for it. A browser, a TV and the Sofa apps send none of these headers, so nothing
  changes for them.
- With `trust_proxy`, a proxy in a container or on another machine is held only to the overall connection limit,
  not the per-address one, as one on this computer already was (everyone's connections come from its address).
- Tested against a server whose connections come from a container's address (`tests/test_access.py`): through a
  tunnel's headers the admin, setup, guest, pairing and DLNA stay shut; the same address without them is home.
  `docs/remote-access.md` and `docs/install.md` ("In Docker") say what to set.

## 1.5.20 (2026-11-18)

- **Recordings plays what's recorded.** A recording that's in the library has **Play** (or **Resume**, with how much is
  left) in Live TV → Recordings. On a Sofa Box it plays in the box's own player, from where it was left, with Skip intro
  when Sofa found one. Recordings gives the library's item for it, never where the file is.
- **Live TV on a TV, by the remote.** Each row of Recordings is one press from the next. OK on a recorded one plays it,
  and OK on one that's coming or recording says what can be done with it: don't record it, stop it, watch the channel,
  stop the series. The Record dialog's series choices are buttons OK changes ("The series: new episodes only",
  "Keep the last 5"). On the Sofa Box the check box and the drop-down they replace held the remote. A remote's REC (or
  R) on a programme in Antenna opens Record for it, the rest of it when it's on now.
- **The series after REC records that showing once.** REC records from the moment it's pressed. Asking for the series
  after it planned the same showing again, on a second tuner. Now a showing that's being recorded, or planned within
  its times, isn't recorded twice, and "Record it" in Antenna says so.
- **For the Sofa Box's own player** (Sofa Box OS 1.1.92): a tuner's channel goes by its own number (5.1, not Sofa's
  own 102), up and down go through the tuners in their own order, and each channel says whether it may be recorded
  (at home, and never for a Visitor, a Kids profile or a guest). The box's player then has the guide and REC.
- Tested against the stand-in tuner, in a browser through the Sofa Box's own agent, by the keys only
  (`tests/test_box_recording.py`). No real tuner or TV has run it.

## 1.5.19 (2026-11-18)

- **Watch together.** Two or more people on the same Sofa watch one title in step, each on their own screen. In the
  player, the people button (or W) starts a room: six letters, a link, and the link as a QR code. The others join
  from their profile's menu (Watch together) or by opening the link, signed in as themselves. A Visitor from the
  share link can't join, nor a guest from the guest QR code. People join mid-film and leave at any time, and the
  panel lists who's in the room. There's no chat.
- **The host steers.** Play, pause, skips, the next episode and the speed follow the host, who can let everyone
  steer. Everyone keeps their own sound track, subtitles and volume. For someone who doesn't steer, Play only joins
  back in where the room is. When the host leaves, the room passes to whoever joined next; the host can also end it
  for everyone. Closing the player leaves the room, and so does the sleep timer. On a screen that steers, a pause
  from headphones or a keyboard's media keys pauses the room too; one a phone makes by itself when it's locked
  doesn't (untried on a real phone).
- **In step by itself.** The room keeps one timeline on Sofa's clock, not a list of presses, so a screen that joins
  late or lost its connection for a while reads where the film is now. Each screen lines its clock up with Sofa's
  with short requests, and an answer that took more than 0.3 s doesn't count for long: it asks again every 2 seconds
  until one comes back quickly (a late answer could put it a second out while it thought it was in step). Four times
  a second it checks how far off it is: a small gap is closed by playing up to 8% faster or slower (browsers keep the
  pitch; nobody has listened to it on a real TV yet), and a big one by a jump. Just after joining or a skip, a
  smaller gap is jumped too.
- **Measured** with two Chrome browsers on one Mac, each signed in as a different profile, playing a real video
  through Sofa over the Mac's own network (`tests/test_together_screens.py`; three runs, other work on the Mac at a
  load of 4 to 7). Each page wrote down where its video was ten times a second, and the two were compared at the
  same moments, counting only while both were playing:
  - steady play: 3–13 ms apart at the median, 40 ms at most;
  - joining mid-film: within 0.1 s after 1.1–1.3 s, then 9–21 ms apart at the median, 0.1 s at most;
  - after the host skipped a minute: within 0.1 s after 0.1–0.2 s, then 4–6 ms at the median, 30 ms at most;
  - paused: 8–18 ms apart; at 1.25× speed, 2–5 ms at the median, 13 ms at most;
  - video Sofa repackages as it plays (HLS): joining, within 0.15 s after 1.1 s; after a skip of a minute and a half,
    past what Sofa had made (both screens start again there), within 0.15 s after 2.2 s, then 9–22 ms at the median,
    79 ms at most;
  - the two screens' ideas of Sofa's clock 0.1–0.5 ms apart; with the joining screen's first four answers held back
    2 seconds, in step after 10.3–10.5 s and 1–8 ms apart;
  - the room's panel on screen 21–63 ms after W; on a TV's remote, the people button is 4 presses from Play.
  Screenshots of both screens after a skip in repackaged video showed the test picture's clock one frame (40 ms)
  apart, about the time between the two screenshots. These are one computer's numbers over its own loopback. Two
  real devices over Wi-Fi haven't been measured, nor has a TV stick's panel time.
- **Repackaged video knows where it starts.** Video Sofa repackages as it plays (an MKV in a browser, for one) is
  copied as it is, so it can only start on a keyframe, one every 2 to 10 seconds in most films. Asked to start at
  5:03, it started at the keyframe before (say 5:00) while the player counted from 5:03: the clock and the subtitles
  were out by up to a keyframe's distance after every skip, and in a room two screens could be seconds apart and
  both think they were in step. Sofa now finds that keyframe first, starts on it and says so (`start` in
  `/api/hls`), and the player counts from there and starts the picture at the place asked for. When the page starts
  a video in the Fire TV app or the Sofa Box's player, it passes the true place on too (their clock and subtitles);
  the box's own far skips still count from the place asked for until its agent reads `start` as well.
  `tests/test_repackaged_start.py` checks the first picture is the file's picture at that keyframe.
- **Kids profiles** join only rooms whose title their rules allow. A room that moves on to a title a Kids profile
  can't watch takes that profile out, and says why. A code that's wrong too often makes that profile wait a few
  minutes.
- **Wherever the player works.** Rooms go through Sofa's own server and nothing else (`sofa/together.py`): at home,
  over Tailscale, or from the internet over HTTPS. When Sofa answers the internet, the panel also gives the link for
  away from home. Rooms are kept in memory only: nothing is written down, and a restart ends them.
- **On TVs:** Silk on a Fire TV uses the web app's player as usual. In the Fire TV app, a room's video plays in the
  app's page player rather than Android's, which can't follow a room to a fraction of a second; that's built and
  hasn't run in the app. The app can't start a room yet. The Sofa Box's own player doesn't take part yet: Watch
  together isn't offered on a box, and a room's link opened there says so.
- **Messages in a player that fills the screen** (on a TV, or after F) now show: they were drawn outside the player,
  which full screen hides. That's a room's ("Den paused") and Sofa's own ("Skipped the intro"). Checked with the page
  told it's full screen; headless Chrome won't go full screen, and no TV has shown one yet.
- **Never the Adult section:** a room doesn't play a title from it (the code would show it to whoever has it, on
  their TV), and a host who puts one on leaves the room.
- Tested in `tests/test_together.py` (the room's rules, through the running server) and
  `tests/test_together_screens.py` (two browsers). No real TV or phone has been in a room yet.

## 1.5.18 (2026-11-18)

- **Coming from Plex, Jellyfin or Emby** (Server → People → Coming from Plex or Jellyfin, or `python3 sofa.py import`).
  Everyone's watched titles, where they stopped and what they liked go into the Sofa profiles you pick, read from a
  copy of Plex's database, Plex's address and a token (the token's own account in full, the other accounts' watched
  titles), Jellyfin's or Emby's address and an API key, or Jellyfin's database (`jellyfin.db` from 10.11,
  `library.db` before). A rating of four stars or more, a favourite or a thumbs-up becomes a like.
- **Matched by the file first:** the other server's path through folder lines you give (`/data/movies =>
  /Volumes/Media/Movies`), whatever the extension, case, slashes or accents; then IMDb, TMDB or TVDB ids from folder
  and file names, `.nfo` files and the details Sofa saved; then a movie's title and year, or a show, season and episode.
- **A dry run first:** per person, what was found and how, what isn't in Sofa, the conflicts (two titles that could be
  the one; Sofa's place is newer), and what was left out for a Kids profile or a profile without Adult. Nothing is
  written until Import.
- **The import** writes in one go, with the other server's dates (Continue watching keeps its order), never over a
  newer place in Sofa (checked again as it writes), and adds likes without taking any away. A second import writes
  nothing. Kids profiles stay Kids and get family titles only; Adult titles go only to profiles with Adult on.
- **Nothing about the other server is kept:** a token or key is used for the one read and written nowhere; a database
  is read from a private copy, deleted straight after; what was read is forgotten at the import, or after an hour.
  Sofa never asks for a Plex.tv password and never talks to plex.tv.
- Tested with fixture databases made with each server's own tables and stand-in Plex and Jellyfin servers
  (`tests/test_history.py`), and in throwaway containers against Jellyfin 12.4.0 (API and database), Jellyfin 10.10.7
  (database) and Plex Media Server 1.43.5's own database. **Not yet against a real Plex library with history, or a
  real Emby server.** [Coming from Plex, Jellyfin or Emby](docs/switching.md)

## 1.5.17 (2026-11-18)

- **The public demo:** a Sofa anyone can open without installing anything, with only a free library, run as its own
  instance ([docs/public-demo.md](docs/public-demo.md)). One switch, `SOFA_DEMO=1` (or `"demo": true` in
  config.json), turns it on and holds it in code (`sofa/demo.py`):
  - **Nobody is at home.** Every request counts as the internet, whatever address it comes from (a tunnel in
    another container looks like the home network). So there's no admin, setup, sign-in, sign-up, guest, pairing
    or profile switching over the web, from anywhere; everyone is the public library's Visitor. The demo is run
    from its files and the command line.
  - **Its settings are locked** (`config.DEMO_LOCKED`): config.json and the Server page can't change them while
    it's on. Among them: the decades and Classic Cinema off, no lookups (a free film mustn't get a copyrighted
    poster), no tidying, Inbox, uploads, downloads or conversions, no DLNA, UPnP or DuckDNS.
  - **Only titles with a rights record that passes:** public domain, a US government work, CC0, CC BY or CC BY-SA,
    each with its publisher, the page that says so and the day it was read; a credit for CC BY; a reason for public
    domain. Each plays as it is, by default from its publisher's own address, so no video goes through the demo's
    server. Nothing is converted, repackaged or relayed.
  - **Live TV only from the demo's own channel list**, each channel checked: https, CORS headers on its playlist,
    a quality and a segment, no made-up browser name or referrer, no FAST service's stream, nothing geo-blocked, a
    publisher and a rights note. The relay never answers.
  - **No trackers, in code:** a content policy names no other site for scripts, styles, fonts or pictures; a
    visitor's sign-in keeps neither the address nor the browser. Games may reach nothing but this server.
  - **Rate limits** per visitor, and on new visitor sign-ins; **a nightly reset** of what visitors leave behind.
  - The Sofa Box link is off the Live TV page, and the box's page doesn't offer free Live TV there.
- **Rights records on any Sofa** (`sofa/rights.py`): a `<video>.rights.json` next to a video, or `rights.json` in its
  folder, shows on the title's page: the licence, who publishes it, the credit, what was changed.
- **The seed tool** (`tools/demo-seed.py`): builds the free library from a manifest and refuses any title without a
  record that passes; checks channels the way a browser on another site plays them; writes the demo's config.json.
  Ours (`deploy/demo/library.json`) starts with four titles from Wikimedia Commons, and holds a fifth for a lawyer's
  view. `deploy/demo/compose.yml` runs the demo in Docker, read-only and on its own network.
- **A show's page opens again.** Since 1.3.0 Live TV's guide and the episode guide under a season had the same
  function name in the app, so the second replaced the first, and a show's page stopped with an error until Live
  TV's guide had been opened. The episode guide has its own name now, and a test fails if two of the app's
  functions share one.
- The Sofa Box page says "source-available", not "open source".
- Tested on a Mac as a scratch instance bound to 127.0.0.1 with a read-only library, and by
  `tests/test_public_demo.py` (each guardrail, the seed tool, and the pages in Chrome). The compose recipe has not
  been run in Docker; nothing is public.
## 1.5.16 (2026-11-18)

- **A Sofa box gets the file as it is.** A device whose player is mpv says so (`mpv=1`: Sofa Box OS 1.1.91), and Sofa
  then sends it AVI, TS, M2TS, WMV and MPEG files and DTS, TrueHD and PCM sound as they are; with `sd=1` (four cores or
  more) a standard-definition picture in MPEG-2, MPEG-4 (XviD, DivX) or VC-1 too. They were repackaged or converted as
  for a browser, which can't play them, and the box waited for it. Browsers, the Fire TV app and boxes before 1.1.91 say
  neither, and nothing changes for them.
- On a Sofa box, the page passes on to the box's player how Sofa sends a video and why (for the box's reports).

## 1.5.15 (2026-11-14)

- **A recording goes on through Restart and updates.** Before, a restart called a recording failed while its copy
  went on writing a part nobody would file, holding its tuner to the end of the programme. Now on a Mac or Linux,
  where Sofa starts again in the same process, the new start takes the copy over and nothing is missed. On Windows,
  where it starts again as another process, the recording carries on in a new part as soon as Sofa is back, and
  says how many seconds that missed. Only a full stop, Sofa not running at all, still marks one failed.
- **Nothing else outlives a restart** (`sofa/children.py`). On a Mac or Linux the new start first ends whatever the
  one before left running: what someone was watching, a conversion, a download. Some of those used to stop on their
  own a moment later, when what they wrote to was gone; now it's the same every time.
- Tested on a Mac with Sofa in a process of its own, the stand-in tuner and real ffmpeg: Restart pressed while one
  channel is watched and another recorded (`tests/test_restart_in_place.py`). On Windows the tests cover only the
  new part (GitHub's machines run them); no Windows PC has run it.

## 1.5.14 (2026-11-14)

- **Live TV → Antenna:** the tuners' channels on the clock, by their own numbers (2.1, 5.1, 11.3), from the guide.
  OK on what's on now watches it; OK on a later programme records it: that one, or the series (new episodes only,
  the last few kept), a film just the once. ◀ ▶ past a row's ends go two hours back and on, a week ahead at most;
  digits go to a channel by its own number. Set to record: a red dot; a series' next one: a red ring.
- **Live TV → Recordings:** recording now (Stop), clashes and what they clash with, coming up, the series, and what's
  recorded (being filed, in the library, or why not). Not for Visitors, Kids profiles or guests.
- **REC in the player** on a channel at home: from now to the end of the programme (an hour without a guide);
  again, it stops, and what's recorded is filed. The R key too. Not yet in the Sofa Box's own player.
- **Server → Live TV → Tuners at home:** look on the network or give an address, switch a tuner on or off, remove
  it; the guide's sources and what they matched; the minutes before and after each recording (0–15, 0–30).
- The player calls a tuner's channel by its own number, and when one doesn't come in it says the tuners may all be
  in use or the signal gone, not that free channels come and go.
- Offline, Live TV keeps the channels at home (a tuner's, a list on the home network) instead of saying it needs
  the internet.
- Tested in a browser against the stand-in tuner (`tests/test_tuner_screens.py`). **No real tuner or TV has run it.**

## 1.5.13 (2026-11-14)

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
  across a box's tuners, said with what they clash with; a stream that breaks off is opened again on the tuner it
  had and the parts joined; a recording that has just ended gives its tuner back before the next one begins. The
  file (the channel's own stream, copied) goes into the Inbox under a name it reads, and the Inbox files it.
  Channels at home only (a tuner's, a list on the home network): never a list from the internet, never the Retro TV
  decades or Classic Cinema. **A recording is never shown to the public library's Visitors**, even when its show
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
