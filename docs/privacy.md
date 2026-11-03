# Privacy: offline, and no logs

Sofa is built to be yours: it runs on your computer, for the devices in your home, and it
doesn't need anyone else to work.

## Everything is on the Sofa computer

The web app, its fonts, the video player, the QR code on the Server page, the artwork, the
previews and the library are all served by the Sofa computer itself. A phone, laptop or TV
browser at home asks Sofa for everything and nothing else. With the internet down, every device
at home can still open Sofa and watch everything in the library.

The one exception is **Live TV**: its channels are on the internet, by nature.

## What uses the internet, and only if you want it

| What | Talks to | Switch it off |
|---|---|---|
| Show details and artwork | TVmaze | Server → Settings → Shows from TVmaze |
| Movie details and artwork | iTunes Store and Wikipedia, or TMDB with your key | Server → Settings → Movies from the iTunes Store and Wikipedia; remove the TMDB key |
| Adult covers and details | ThePornDB, only with your token | Remove the token |
| Update checks | GitHub, twice a day | Work offline |
| Save from a link | the site you paste, through yt-dlp | Don't use it, or Work offline |
| Live TV channel lists and channels | iptv-org and the lists you add | Don't use it, or Work offline |

Only the name of a show or movie is sent when looking up details (never who's watching, never
your files). Suggestions ("More like this", "Because you watched") are worked out by Sofa at
home.

### On a Sofa Box

The box itself has no account, no ads and no tracking. What it fetches from the internet, besides the
apps and sites you open on it:

| What | Talks to | Switch it off |
|---|---|---|
| Is a newer Sofa Box OS out? | GitHub, once a day (reads one small file) | — |
| Featured public Sofas | GitHub, once a day | — |
| Sofa Shield's blocklist | GitHub (StevenBlack's list), once a week | Settings → Sofa Shield |
| Update the box | GitHub, only when you press it | — |
| App Store icons | each app's own site, once, the first time the store is opened | — |
| Live TV channel lists | iptv-org | Don't open Live TV |
| The secure (https) phone remote | the Sofa Box certificate service (boxcert.edgeventure.uk), about once a day: a random id and the box's address on your network | Settings → Remotes and Bluetooth → Switch off |

| Send a report | the Sofa Box certificate service, only when you press it (Settings → Help, or "Something wrong?" on the phone remote) | Don't press it |

The secure phone remote's name (random letters) is listed in the public certificate logs, as every
certificate is. Its key stays on the box.

**What a report has in it**, for the Sofa Box team to find what went wrong: the box's version, board and
settings; how its network, Wi-Fi, Bluetooth and phone remotes are doing (the names of your Wi-Fi and
Bluetooth devices among them); where the player was in a video (not what it was); the errors of the
pages open on it and what their video players said; and the box's own logs since it last started.
Before it goes, the box cuts every web address down to its site and first folder, and every file on a
drive down to the drive, and blanks passwords and secrets: no titles, codes or passwords are in it. The
box keeps a copy (`~/.config/sofa-box/last-report.txt`); the service keeps the newest few hundred
reports, under the number the TV shows you.

### Work offline

**Server → Settings → Privacy → Work offline.** Sofa then never uses the internet: no lookups,
no update checks, no downloads, no channel lists. Everything already in the library keeps
working on every device. New things in the Inbox are still filed, with pictures from the videos
themselves. Switch it off again and Sofa looks up what it missed.

### When the internet goes down by itself

Sofa notices on the first lookup that fails and stops trying for a few minutes, so nothing waits
on it. Nothing is marked "not found" because of it: the lookups happen when the internet is back.

## No logs

**Server → Settings → Privacy → Keep no logs.** Nothing about what happens on the server is
written down anywhere:

- no activity list (Server → Activity shows only how many problems there were, never what),
- no server log file (`data/sofa.log`, or the system journal on Linux),
- no Adult details log (`data/logs/private.jsonl`),
- no list of downloads or conversions once they're done (with their titles and links),
- not where anyone signed in from, nor with what device,
- nothing of the above in the nightly backups.

What Sofa keeps, because it's how it works rather than a log: accounts, each person's watch
progress and My List, settings, and the pictures and previews it makes of the library.

### Wipe all logs

**Server → Settings → Privacy → Wipe all logs** erases everything listed above that's already
there, including inside the backups in `data/backups` (they keep accounts, watch progress and
settings). The database is rewritten so the erased rows can't be recovered from its file either.

Good to know: Time Machine (or any other backup of the whole computer) has its own copies of
Sofa's folder from before; Sofa can't reach those.

## Who can see what

- Sofa answers only your home network and Tailscale, unless you change that
  ([remote-access.md](remote-access.md)).
- Every person has their own profile; profiles that can see Adult or run the server are locked
  with a PIN. A **Kids** profile sees only family titles, and leaving it takes the other
  profile's PIN or password.
- Using your phone as the remote goes through the Sofa computer only; only your own screens are
  listed, and nothing about it is kept.
- The Adult section is off for everyone until switched on per person, never shown to guests or
  TVs, and adult titles never appear in addresses, the browser's history or the Server page.
