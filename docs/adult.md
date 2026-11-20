# The Adult section

## Seeing it

**Server → People**, then the **Adult** switch next to each person. It's off for everyone to
begin with, **admins included**, so the first time, switch it on for yourself. (If there's
adult content you can't see, the Server page's Overview says so and has a button for it.)

**Each person is asked once whether they are 18 or older**, the first time they open Adult after the switch is
on for them. Until they say so themselves, nothing adult is sent to their profile. Sofa keeps the day they
answered, and **Server → People** shows it. An admin can't answer for someone else. After updating to 1.5.30,
people who already had Adult are asked once too; do it in a browser (the TV apps can't ask, and show no Adult
section until it's answered).

It's never shown to:

- people with the switch off,
- guests (the QR-code sign-in),
- TVs browsing Sofa without signing in (Roku Media Player, VLC, smart TVs).

Adult videos also stay out of Home, "Continue watching" and search for everyone. The Adult
tab has its own "Continue watching" and its own search box.

## The Adult tab

It has its own front page, like Home: a featured strip, then **Continue watching**, **New
arrivals**, a row for **each of your categories** (Movies, Hentai, Shows, ...), **Your
favorites**, **Studios**, **Performers**, and everything at the bottom. Each category's page
splits into its **Series**, **Collections** and **Videos**.

## Your own folders are the categories

Every folder at the top of `~/Entertainment/Adult` is a category, with its own button and row
in the Adult tab, named the way you named the folder. Use whatever names you like:

```
Adult/
  Movies/
    Night Shift (2018)/Night Shift (2018).mp4        a movie in its own folder
    Brazzers.21.03.14.Jane.Doe.Hot.Title.XXX.mp4     or loose
  Hentai/
    Some Series/Episode 01.mp4, Episode 02.mp4       a series (Sofa spots episodes)
    A Movie (2010)/A Movie (2010).mp4
  Series/
    Series Name/Season 1/Series Name S01E01.mp4
  Collections/
    Summer Pack/Scene One.mp4, Scene Two.mp4         a collection
  Amateur/  VR/  Erotic/  ...                        anything else you make
```

Inside any category Sofa recognises single movies, loose videos, **series** (Season folders,
or several files named like episodes: `S01E01`, `1x01`, `Episode 1`) and **collections** (a
folder of several videos).

## Adding things

- **Drop them into `~/Entertainment/Inbox/XXX`.**
  - A single video becomes `Adult/Movies/<Title>/`.
  - A folder named like a category (`Hentai`, `Series`, `Collections`, `Amateur`, `VR`, …)
    moves into `Adult/` **with everything inside it kept as it is**.
  - A folder of several scenes becomes a collection under `Adult/Movies/`.
- **Already have an `XXX`, `Adult` or `Porn` folder** in `Movies`, `Shows` or
  `~/Entertainment`? Sofa moves its contents into `Adult/`, keeping its folders as categories.

## Not from a link

Sofa's **Save from a link** (Server → Downloads) doesn't save adult videos: nothing from a link goes to the Adult
section, and a video its site marks as for adults only is skipped. The free adult sites' terms forbid downloading
their videos. Videos an older Sofa saved that way stay where they are, with the details that came with them. To
watch what's popular at a site without keeping it, see **Top lists** below.

## Browsing

| | |
|---|---|
| **Categories** | one button and one row per folder (Movies, Hentai, Shows, ...) |
| **Studios** | from file names like `Studio.21.03.14.Performer.Name.Title`, `.nfo` files, ThePornDB |
| **Performers** | same sources; names joined with "And" in file names are recognised too |
| **Tags** | from `.nfo` files and ThePornDB |
| **Favorites** | press ♥ on a video or a performer |
| **Shuffle / Play all** | on every list: plays one after another |

Each video's picture is a frame from **the middle of the video** (not the opening logo or a
black frame), shown in a wide card like the video itself. Pictures that came with the video
(an `.nfo` file, ThePornDB, or a `folder.jpg` you put there) are used instead.
Pointing at a card plays a short preview of the video (with the TV remote: picking it).
Pictures stuck on a bad moment: **Manage → Take new pictures from the video** on its page.

All of that works without any account or key. For real covers and descriptions, add a free
**ThePornDB** token under **Server → Settings**. Wrong or missing details: open the video and
press **Find details**.

## Sorting, filtering, and the list

Every list of videos sorts by **Newest**, **Release date**, **Name**, **Longest**, **Largest** and **Best picture**,
and narrows by **picture** (4K, 1080p, 720p, SD), **length**, the **sound's language** and **played or not**. Each
filter shows only the choices that list has, with how many. **Cards / List** switches between the cards and a list
with a row per video: who's in it, its tags, its length, picture, size, languages and the day it was added.

Under each card: the file's size, its sound's languages ("EN + ES" for two) and **CC** when it has subtitles. A
video's page has the languages in full and **This file**: the picture, every sound and subtitle track, the file's
size and length, and how this device gets it.

**Preview sound on / off** (next to the search box) is the sound of the short preview a card plays when you point
at it.

Performers and tags also come from a file's own tags (the artist and genre written into an MP4 or MKV) when nothing
else names them. They show after Sofa has read the file and scanned again.

## Top lists from a free site

**Adult → Top lists** shows the 25 most watched videos of a category at a free site: this week, this month, of all
time, or the best rated. It is **off** until an admin switches a site on (**Sites**, at the foot of that page).

- Sofa asks the site's own public API for the lists, and nothing else.
- A video plays in **the site's own player**, in your browser, straight from the site, with the site's own
  advertising and notices. Sofa doesn't fetch, keep, convert or pass on the video, and there is no Save: the sites'
  terms don't allow one.
- Above the player, **Watch on …** opens the video's page at the site.
- **Keep** keeps the link: the title, the picture's address, the site and the day. **Adult → Kept** lists them by
  day, with what you played lately and didn't keep (forgotten after 30 days; with **Keep no logs** on, what you
  played isn't listed at all). A video the site removes goes from
  Kept too.
- Only people with the Adult switch see any of it. Never visitors, guests or Kids profiles, and never a public Sofa.
- A site's player is made for a mouse or a finger. On a TV or a Sofa Box it may not answer the remote.

Which sites, what their terms say and which were left out: [adult-sites.md](adult-sites.md).

## Privacy

- **Nothing readable in history.** Adult pages have addresses like `#/movie/am:h19ed4feb57ac`,
  with no titles, so browser history and bookmarks don't give anything away.
- **Top lists and Kept** have addresses with a video's id, never its title, and Activity never names a site.
- **The Server page doesn't name titles.**
  - Activity says "Added 1 video to Adult".
  - "Watching now" says "something private".
  - Converting and Downloads show "Private video".
  - Files that need a look go to `Needs Review/XXX`.
  - Entries from older versions of Sofa are rewritten the same way when Sofa starts.

## Adult live TV

The free iptv-org channel lists stopped carrying adult channels in January 2024, and there's
no other free, legitimate list Sofa can suggest. If you have an M3U link from a service you
trust, add it under **Server → Live TV** and tick **Adult channels** (a list that's already there has an
**Adult** switch; the page says so when a list's name looks adult and isn't marked).

A list marked Adult has its own page, **Adult → Live TV**, and its channels are nowhere else:

- Not in Live TV, for anyone. Only people allowed to see the Adult section get the page.
- Never for visitors (marking a list Adult ends sharing it), Kids profiles or guests, and never for a TV on the network.
- At home only: adult channels are never sent out through Sofa, and never play away from home.
- Activity doesn't name an adult list, "Watching now" says "something private", and a Sofa Box's player and its
  phone remote show the channel's number, not its name.
- A channel is adult when any list holding it is, whichever list was added first.

**Only channels that play are shown.** Adult lists are short-lived: most of their channels are gone or broken at any
time. The page is one plain list, by name, of the channels Sofa saw play in the last two days, and nothing else:

- Sofa looks at an adult channel it hasn't seen lately before anything else, a few at a time, never two at once on the
  same site, the way a viewer at home opens it. One that plays is looked at again a day later.
- A channel whose last look got no video leaves the page at once, and is back as soon as a look, or someone watching
  it, gets video again.
- With none to show yet, the page says how far Sofa has got ("1 of 42 so far") and fills in by itself, or that none
  played when Sofa last looked, or that checking is switched off.
- **Server → Live TV** says under each adult list how many of its channels play, how many didn't and how many aren't
  checked yet. A list that can't be read says why in plain words, such as a site name that doesn't exist any more.
