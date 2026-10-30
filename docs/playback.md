# Playing videos

## How Sofa plays a file

| The file | What Sofa does | Cost |
|---|---|---|
| MP4 with H.264 (most downloads) | sends it as it is | nothing |
| MKV, or AVI with H.264 | repackages it as it plays | almost nothing |
| HEVC / x265 | as it is on devices that play HEVC (Macs, iPhones, recent TVs); converted for the rest | small |
| XviD, DivX, MPEG-2, VC-1, 10-bit H.264 | converted as it plays (H.264) | the Mac's video chip does it |
| DTS, TrueHD, AC3 sound | turned into AAC stereo as it plays | tiny |

The little "Repackaged" or "Converted" label in the player tells you which one is
happening; hover it to see why.

## Converting to MP4 for good

Adapting a file every time it plays works, but converting it **once** is better: it starts
instantly, seeks instantly, and works on every device.

Sofa does this by itself, in the background, one file at a time, and pauses whenever
someone is watching something that needs live conversion. It's on by default:
**Server → Converting**.

- **Convert new files automatically**: anything new that needs it is converted a minute or
  two after it arrives.
- **Convert all now**: for files that were there before.
- **Keep the originals** (on by default): each original is moved to
  `~/Entertainment/Converted Originals`, in the same folders as before. Once you're happy,
  turn this off to have originals deleted instead, or empty that folder yourself.

What converting keeps: the picture (copied as it is when it's H.264 or HEVC, so no quality is
lost), every sound track (the first one also as AAC stereo so everything can play it),
text subtitles, chapters. Picture subtitles from Blu-rays (PGS) can't go into an MP4; the
original keeps them.

You can also convert one file from the player: if a video stops, admins get a **Convert
this file to MP4** button.

## The player

| | |
|---|---|
| **Skip Intro / Skip Recap** | appears while the intro or recap plays |
| **Next episode** | appears when the credits start, with a 10 second countdown; "Watch credits" stays |
| Scrubbing | hover the seek bar to see a preview picture |
| Episodes | the list button, or `E` |
| Audio and subtitles | the CC button, or `C`. Sofa remembers your language. |
| Options (gear) | autoplay next episode, skip intros by themselves, "Are you still watching?", **Night mode** (loud scenes quieter and voices clearer, worked out on the device; not on iPhone and iPad), **sleep timer** (end of this episode, 30 min, 1 hour), **picture** for converted video (Auto, 1080p, 720p, 480p: lower is lighter for the Sofa computer and for Wi-Fi), speed, subtitle size, what's playing and why |
| Picture in picture | the button, or `P` |
| Phones | tap to show the controls, double-tap left or right to skip 10 seconds |

All the keys: press `?` in the player.

### How Sofa knows where the intro is

1. **Chapters**: many MKV files have chapters called "Intro", "Opening", "Recap" or "Credits".
2. **Listening**: in the background, Sofa compares the first ten minutes and the last five
   of neighbouring episodes of a season. The stretch that sounds the same in both is the
   intro (or the credits). This needs at least two episodes of a season.

This runs in the background, a season at a time. **Whatever someone starts watching is done
first**, so a show's intros usually appear within a minute or two of pressing Play. Progress
is on **Server → Library → Skip Intro** ("seasons checked", "episodes with Skip Intro"),
with a button to listen to everything again.

Admins can correct it in the player's Options (gear):
- **Wrong intro** removes a bad one.
- **Mark the intro by hand**: "Starts here", then "Ends here" for **this episode** or for the
  **whole season** (handy when every episode opens the same way).

The intro and credits show as light marks on the seek bar, and the scrubbing preview says
"Intro" or "Credits" over them. Turn the whole thing off in `data/config.json`
(`"detect_intros": false`).

### Hover previews

Point at a card with the mouse and a bigger card opens over it, playing a few seconds of the
video (three short moments, silent), with **Play**, **More info** and ♥. With a TV remote, the
card you're on plays its preview in place. Sofa makes each clip the first time someone points
at it (a second or two) and, in the background, for every movie and each show's first episode.
About 300 KB each, in `~/Sofa/data/cache/previews`. Off with `"previews": false`.

### Trailers

Open a show or a movie (**More info**) and after a moment three minutes of it play behind the
title, from somewhere in the middle (never the opening, never the end), silent until you press
the speaker. A show's trailer comes from a random episode of its first season, so it gives
nothing away. Files your device plays as they are cost the Sofa computer nothing; others are
repackaged as they play (cheap); a file that would need converting on a slow computer (Gentle
mode) plays its short preview clip instead. Off per device under **Theme → Trailers**.

### Scrubbing previews

Sofa makes preview pictures (320 px wide, one every 10 seconds) for each video, in the
background, starting with what people are watching. They're stored in
`~/Sofa/data/cache/trickplay`, never next to your media. Off with `"trickplay": false`.

### Old computers: Gentle mode and the encoder check

A minute after starting (and again whenever ffmpeg changes), Sofa times a short 1080p conversion
with each way this computer has (Apple's VideoToolbox and x264) and uses the faster one that
**works properly**: it also compares the result with the original, because on some older Macs
running a newer macOS (OpenCore) VideoToolbox makes video with purple or green lines across it.
There Sofa never uses it, previews are made again, and **Server → Overview → This computer** offers
to convert again, from the originals it kept, any MP4 it made with it before.

**Gentle mode** turns on by itself on a slow computer (or set it on or off there): video converted
while someone watches is 720p at most, and converting files, making previews ahead of time and
finding intros wait for the **quiet hours** (1:00 to 7:00, changeable). Whatever someone is
watching is still done straight away.

### Space

**Server → Library → Free up space** deletes Sofa's own resized pictures, scrubbing previews
and hover clips (they're made again as needed). Your media is never touched. **Look up missing
details again** makes Sofa ask the internet again now for titles it found nothing about,
instead of waiting a day.

## A video won't play

1. **Look at the message.** If ffmpeg complained, the player shows what it said, and so does
   **Server → Activity → Playback problems**.
2. **Convert it.** Admins: the **Convert this file to MP4** button, or Server → Converting.
3. **Is it complete?** A half-downloaded file plays in VLC up to the break, but conversion
   stops there. Download it again.
4. **"Can't convert video yet"** on the Server page means ffmpeg isn't installed:
   `brew install ffmpeg`, then restart Sofa.
5. **Busy?** Server → Converting → "At the same time" sets how many people can watch
   converted video at once. A Mac with Apple silicon handles 3 or 4 easily.
