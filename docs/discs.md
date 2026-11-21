# Save this disc

Put a DVD or CD in the disc drive of the computer Sofa runs on (a built-in drive or a USB one), open **Server →
Overview**, and the **Disc drive** panel shows what's in it. **Save this disc** asks where it goes and what it's
called, and then it's in your library like any other file. On a Sofa Box the same thing is on Home, beside the
disc's tile, and saves into Sofa on this box.

| The disc | What you get | Where |
|---|---|---|
| Music CD | One FLAC file a track: every bit of the disc's sound, checked against what was read. Named and tagged. | `Music/<Artist>/<Album>/01 Title.flac` |
| Video DVD, not copy-protected | An MKV of the title you pick: the disc's own picture and sound (nothing converted), every sound and subtitle track with its language, the chapters. | `Movies/<Title (Year)>/`, or `Shows/<Show>/Season N/` as episodes |
| Data disc | Its videos, music and subtitles, copied. | The Inbox, where Sofa files them |
| Copy-protected DVD, any Blu-ray | Nothing. The page says it's copy-protected. | |

## Copy-protected discs

Most DVDs from a shop scramble their video (CSS), and every commercial Blu-ray does (AACS). Sofa does not save
these, and has nothing in it that could: no descrambler, no keys, and nothing that fetches or calls one. In the
United States, getting round a disc's copy protection is circumvention under 17 U.S.C. 1201, even to copy a disc you
own for yourself, and giving people a tool for it is a second offence. That is the whole reason, and it's why the
page says so plainly instead of failing in some quieter way.

How Sofa tells, without undoing anything:

- **What the disc says in the clear.** A DVD's video is a run of 2048-byte packs, and each packet's header has two
  bits saying whether its contents are scrambled. Sofa reads those bits: a few places along the longest titles when
  the disc goes in, and every pack as it saves.
- **The disc's own copyright record**, where the system lets Sofa ask the drive for it (Linux and Windows): none, CSS
  or CPRM.
- **A drive that won't hand the video over.** A drive refuses to read a protected disc's video until it has been
  unlocked. Sofa never sends the unlocking handshake, so a refusal is taken as protection.
- **A Blu-ray** is recognised by its folders and stopped at once, protected or not: Sofa doesn't read Blu-ray video.

A scrambled pack met in the middle of a save ends it, and nothing of that title is kept.

## Who reads the disc

Sofa's own code does: `sofa/iso9660.py` (the disc's files, from the folder the computer mounted it at, or straight
from the drive), `sofa/dvd.py` (a DVD's tables and packs) and `sofa/cdaudio.py` (a CD's table of contents, its text
and its sound). ffmpeg, which Sofa already needs, only packs what was read: a title's stream into an MKV, a track's
sound into FLAC.

That is on purpose. The usual DVD library (libdvdread, behind ffmpeg's and mpv's own DVD support) loads a decrypting
library by itself on any computer that has one installed. Sofa's reader never does, on anyone's computer.

**One function reads a title's stream:** `dvd.read_title(source, title)` in `sofa/dvd.py`. It yields the title's
packs in playing order, in the clear, or raises `dvd.Protected`. Everything that saves a title calls it by that
name, so it is the one place to change how a title is read. Sofa ships nothing else to put there.

## When Sofa can't read the disc

A copy-protected disc's page offers two lawful ways to keep it:

- **Get it free**: if the film is in the public domain (or under a licence that lets anyone copy it) and the
  Internet Archive has it, Sofa downloads it into Movies. Only what the archive marks as free to copy is offered (a
  public domain mark, CC0, a Creative Commons licence that allows copying), or a feature film made before 1929.
- **Record it from a DVD player**: a DVD player's analog outputs (the yellow video plug, or S-video, and the red and
  white sound) into a USB video capture stick plugged into the Sofa computer or a Sofa Box. Sofa records what the
  player plays, in real time, into Movies. Standard definition, one sound track, no subtitles or chapters unless the
  player draws them. Nothing on the disc is decrypted. Some discs send an analog copy signal (Macrovision) that makes
  some sticks' picture flicker or darken; Sofa records what the stick gives it and does nothing about that signal. On
  a Mac, the first recording asks whether Sofa may use a camera: a capture stick counts as one.

  The page walks through it: what to buy, plugging the stick in (Sofa notices it), connecting the player (yellow to
  yellow, red and white to red and white; S-video for a sharper picture), a look through the stick to check the picture
  and sound, then the name. Press Record, then Play on the player: Sofa starts with the film, stops by itself when it
  has ended (a still picture and quiet for a minute and a half), and trims the player's own screens off both ends.

  **What to buy:** a USB 2.0 video capture stick ("USB video grabber") that works without drivers ("UVC", "driver-free"
  or "plug and play" for Mac, Windows and Linux), with a yellow composite input, ideally an S-video one too, and red
  and white sound inputs; about $15 to $30. **Not an HDMI capture stick**: a DVD player's HDMI output is encrypted
  (HDCP), so such a stick shows nothing, and getting round that isn't allowed.

## Names for a music CD

First the names the disc carries itself (CD-Text), where the drive gives them. Otherwise type them, or press **Look
the names up**: Sofa asks MusicBrainz, sending where the disc's tracks start (that's how MusicBrainz knows a disc)
and nothing else. No key or account. **Server → Settings → Music CD names from MusicBrainz** switches it off, and
Work offline does too.

## While it saves

- The drive is only read, and opened shared: nothing is locked, unmounted or ejected, so that the disc can still be
  played (made that way; not tried with a player running).
- A disc or drive pulled out in the middle ends the save with a message. What was already finished stays; what was
  half done is removed.
- Nothing is written over a file that's there. A name that's taken is said before anything is read.
- One disc at a time. Stop ends it and keeps what was finished.
- A DVD needs about three times its title's size free while it's saved (the stream, then the file), and gives two
  thirds back.

## Not saved yet

A DVD title filmed from more than one camera angle (listed, with that reason), DVD menus, DVD-Audio, Video CDs, and
home-made Blu-rays. A CD is read once, with three tries at a scratch: there's no second-opinion check against other
people's copies of the same disc.

## What has been tried

- Discs made for the tests: a music CD's image, an unprotected DVD's image, and one with its packs marked scrambled.
- A DVD authored by dvdauthor (another program's tables), read by Sofa's reader.
- A made DVD image mounted on a Mac, saved from where the Mac put it.
- A save slowed to a minute and a half while the library was tidied and read again every few seconds.
- Linux 6.12 in a virtual machine with two emulated USB disc drives: both found, the DVD read from `/dev/sr0` and
  saved, the marked one refused.

- One real disc: a commercial, copy-protected DVD in an iMac's built-in drive. Its titles, chapters and tracks were
  read correctly, it was said to be copy-protected, and nothing was saved.

**Not yet:** saving a real unprotected DVD, and any music CD from hardware on any system: the Mac's CD folder,
Linux's and Windows's calls for a CD's sound, and CD-Text are written from their documentation and tested against
stand-ins. Windows has no real drive behind it.

To try an image with no drive, start Sofa with `SOFA_DISCS=/path/to/disc.iso` (or a `.cue`): it shows as a disc. On
a Mac, a disc image you've mounted shows as one too.
