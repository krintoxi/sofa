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
  with a PIN.
- The Adult section is off for everyone until switched on per person, never shown to guests or
  TVs, and adult titles never appear in addresses, the browser's history or the Server page.
