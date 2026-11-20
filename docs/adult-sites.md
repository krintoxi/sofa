# Top lists in the Adult section: the sites, and what their terms allow

The Adult section can show the 25 most watched videos of a category at a free site (**Adult → Top lists**). This page
is the record of which sites that is built on, what each site's own terms say, and which sites were left out and why.
It was written on 2026-11-19 from the pages named below, as they read that day. Terms change: before a site is added
or kept, read them again.

## The rules Sofa keeps to, whatever the site

- A site is built in only when its own terms say a third party may list its videos through a documented API or feed
  and show them in its player, and those terms were read.
- Every site is **off** until an admin switches it on (**Adult → Top lists → Sites**). Until then Sofa asks it nothing.
- Sofa's server reads **lists** only: titles, lengths, the address of a picture and of the player. It never asks for,
  stores, converts or passes on a video. The video plays in the **site's own player**, in the owner's browser, straight
  from the site, with the site's notices, advertising and age checks as the site serves them.
- Next to the player is a link to the video's page at the site.
- The pictures on the cards come to the browser straight from the site. Sofa keeps no copy.
- It is part of the Adult section: only for people of this Sofa with the Adult switch on. Never for visitors, guests
  or Kids profiles, never on a public Sofa (the demo switch turns it off whatever the settings say).
- **Kept** keeps a link (title, the picture's address, the site, the day). Not the video.

## Eporner: built in

Read: <https://www.eporner.com/api/v2/> (the API's documentation, with its own "Terms of use" section) and
<https://www.eporner.com/terms/> (the site's terms, "LAST UPDATE: 2026 NOV 18"), both on 2026-11-19.

What they say, in short:

| | |
|---|---|
| May a third party use it? | Yes. The API page: "You are welcome to use this API, the feeds and the player on your website or app." The terms (6.2) say the ban on automated access "does not apply" to the documented public API. No key. |
| Top lists | `GET /api/v2/video/search/` with `order` = `top-weekly`, `top-monthly`, `most-popular` or `top-rated`; `GET /api/v2/categories/` for the categories. A category's list is a search for the category's name in that order (the search takes words, not a category id). |
| The player | Each video has an `embed` address for an iframe. Terms 7.2: "You may place the Embeddable Player only on your own website". Terms 7.3, 7.4 and 7A: the player may not be modified, obscured or built upon; its advertising, labels and notices stay; it must not be a way around an age check or a regional restriction. Where the API page and the terms differ, "the Terms decide". |
| Link back | Every page that shows the player must show "a prominent link back to eporner.com". |
| Downloading | Not allowed: "Do not download, copy or re-host video files". Terms 7A.3: no caching or serving the video outside the player. |
| What it removes | "Read the removed videos at least once a day and take those videos off your site." |
| How often to ask | Replies say how long they stay good (a search: 5 minutes; categories: 1 hour). One request at a time. A 503 is not an empty result. |
| Age rules | "Your site meets the age-verification and child-protection rules that apply to it." |
| Other | Not for training or testing machine-learning systems. The API "can change or end", and permission to use the player can be withdrawn. |

How Sofa meets each:

- **Lists from the documented API only** (`categories/`, `video/search/`, `video/status/`), asked one at a time, kept
  for 30 minutes (categories 12 hours); after a failure not asked again for 5 minutes, and the last list stays up to
  a day. A test checks that nothing else at the site is ever asked for.
- **The player as it is**: an iframe at the `embed` address the API gave, nothing drawn over it, nothing changed, no
  sandboxing that would stop its advertising. Sofa only accepts a player address that is the site's own and belongs to
  the video's id; anything else in a reply is dropped.
- **The link back**: "Watch on Eporner" above the player, to the video's own page, and the site's name on the list.
- **No download**: there is no Save for this site. Sofa's "Save from a link" no longer saves adult videos at all
  (1.5.30): nothing from a link goes to the Adult section, and a video its site marks for adults only is skipped.
- **Removed videos**: lists are read again every half hour, so a removed video leaves with the next reading; once a
  day Sofa asks `video/status/` about every kept link and deletes the ones the site has removed.
- **Age**: these pages exist only behind the Adult switch, which an admin sets per person and which is off for
  everyone to begin with, and only after that person has said themselves that they are 18 or older (asked once,
  kept with the day); and the player is loaded by the browser from the site, so the site's own age check and
  regional rules apply to whoever is watching. Sofa does nothing to get around either.
- Three of the site's category names are not shown on Sofa's page: Teen, Students and Uncategorized.

To weigh before selling a Sofa Box with this in it:

- The API page says "on your website or app"; the terms say the player goes "only on your own website" (7.2), that
  content is "for information and personal use" (5.5), and that no one may "commercially exploit" the site or its
  content (6.2). Sofa ships with every site off, shows no site's content until the owner of the box switches it on,
  and takes no money for or from the site's content. Whether a household's own Sofa is "your own website", and
  whether a box sold with the switch available is within those terms, are questions for a lawyer, not ones this page
  settles. Asking Eporner in writing (their contact page) would settle them.
- Several US states require age verification of sites that carry adult material. The site applies its own checks to
  the player; what a state asks of the maker of a device is again a lawyer's question.

## Left out

| Site | Why |
|---|---|
| XVideos | Read <https://info.xvideos.net/db> and <https://info.xvideos.net/legal/tos> on 2026-11-19. Its only feed for third parties is an export of its whole catalogue (about 7 million rows, 800 MB compressed), with "video URL, thumb URL, tags, duration, title, and embed code" and no view counts or rankings: there is no official way to get "the top 25 of a category". Its terms allow "personal and non-commercial" use only and forbid any "web scraper, offline reader, spider or robot". A top list would mean scraping its pages. |
| Pornhub, RedTube, YouPorn, Tube8, xHamster, SpankBang | Their terms and webmaster pages could not be read while this was built, so nothing is built on them. What each offers third parties, and on what conditions, has to be read first. |

A site can be added later by reading its terms, writing them up here, and adding one entry to `SITES` in
`sofa/toplists.py` with a reader for its API.

## Saving a video

No site here allows it. Eporner forbids downloading in its API terms and in its site terms; XVideos' terms forbid
downloading for any commercial purpose and any automated download. So **Top lists has no Save**, and none is planned
for a site whose terms don't offer one. What can be kept is the link (**Kept**).

A Save would be right for a source that offers a download itself or states a licence that allows keeping a copy (as
the Internet Archive's public-domain films do, which Sofa's Classic Cinema already plays). None of the popular free
adult sites read for this page is such a source.
