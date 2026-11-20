# The Sofa API (for apps)

What the Fire TV app, the Roku channel and the Sofa box use, and what any other app can use. This
is **API version 1**: things are only added to it. Anything that would break an app gets a new
version number (in `/api/info` and the Bonjour record), and the old one keeps working.

Everything is plain HTTP and JSON on the Sofa computer's port (8090 unless changed), at home or
over Tailscale.

## Finding Sofa

- **Bonjour (mDNS):** service type `_sofa._tcp`, with `version`, `api` and `path` in its TXT record.
  Android: `NsdManager`; Apple: `NWBrowser`; Linux: `avahi-browse -rt _sofa._tcp`.
- **SSDP:** an `M-SEARCH` for `ST: urn:sofa-media:device:Sofa:1` to `239.255.255.250:1900` is
  answered with `LOCATION: http://<address>:<port>/api/info`, even when TV sharing is off. For
  devices without Bonjour (Roku).
- Or the person types the address the Server page shows.

`GET /api/info` (no sign-in) proves it's Sofa:

```json
{"sofa": true, "name": "Sofa", "version": "1.1.0", "api": 1, "port": 8090, "id": "cf648b1d-..."}
```

`id` stays the same for the computer, so an app can remember which Sofa it was paired with.

## Signing in: pairing

Nobody should type a password with a remote. An app shows a code; someone approves it on a phone.

1. `POST /api/pair/start` with `{"name": "Living room"}` → `{"code": "482917", "poll": "<secret>", "expires": 600, "url": "http://…/#/pair/482917"}`.
   Show the code (as `482 917`) and a QR code of `url`.
2. Every 2 seconds: `GET /api/pair/poll?poll=<secret>` → `{"state": "waiting"}`, then
   `{"state": "approved", "token": "<token>", "user": {…}}` once someone approved it (Sofa on a
   phone: **Pair a TV**, or scan the QR), or `{"state": "expired"}` (start again).
3. From then on send `Authorization: Bearer <token>` with every request. The token lasts like a
   browser sign-in and shows under Server → People → Signed-in devices, where it can be signed out.

Every `POST` also needs the header `X-Sofa: 1` and a JSON body (`{}` when there's nothing to send).
A `401` means the token was signed out: pair again.

## Who's watching

- `GET /api/session` → `{"user": {"id", "name", "admin", "adult", "kids", "avatar", "pin"}, "name", "version", "profiles": <count or false>}`
- `GET /api/profiles` → `{"profiles": [{"id", "name", "avatar", "locked", "pin", "kids"}], "me": <id>}`
- `POST /api/profiles/switch` `{"id": 3, "code": "1234"}` (code only for locked profiles) → `{"ok": true, "token": "<new token>"}`:
  use the new token from then on.

## The library

- Every movie and episode in the library's list may carry `"langs": {"a": ["en", "es-419"], "s": ["es"], "n": 2,
  "by": "name", "dual": true}`: its sound's languages, its subtitles', how many sound tracks when more than the
  languages say, `"by": "name"` when a language is only from the file's name, `"dual"` when a name says two or more and
  the file hasn't said which. A show's `langs` gathers its episodes' (`"some": {"es": 12}`: in 12 of them), and its
  `"each"` is the `langs` of every episode that has none of its own (most of a show's episodes are alike, so it's said
  once; an episode Sofa knows nothing of has `"langs": null`). Left out
  when Sofa knows nothing. `"original"` is the language the title was made in, from TVmaze or TMDB.
- `GET /api/details/<item id>?<the same device answers as /api/play>` → that file in full (Sofa 1.5.23):
  `{"read", "video": {"quality", "width", "height", "codec", "hdr", "fps", "bit_rate"}, "audio": [{"code", "by", "name",
  "codec", "layout", "bit_rate", "title", "default", "commentary"}], "subs": [{"code", "by", "name", "kind": "text" |
  "picture" | "file", "format", "forced", "sdh"}], "languages", "original", "file": {"size", "ext", "duration",
  "bit_rate", "chapters", "added", "modified"}, "play": {"mode", "why"}, "has": {"intro", "scrub"}}`. Unlike
  `/api/play` it starts nothing (no Skip Intro search, no scrubbing pictures).
- `GET /api/library` → `{"generated", "shows": [...], "movies": [...], "likes": [...], "adult": {...} (only for adult profiles)}`.
- The Adult section's top lists (only for a profile with Adult on; 404 for anyone else and on a public Sofa):
  `GET /api/adult/top` → `{"sites": [{"id", "name", "on", "home", "terms"}], "periods"}`;
  `GET /api/adult/top/<site>?cat=<slug>&period=week|month|all|rated` → `{"state": "ready"|"reading"|"down", "items", "cats"}`
  (never waits on the site: ask again while it says `reading`); `GET /api/adult/top/<site>/v/<id>` → one video
  (`embed` is the site's own player); `GET /api/adult/kept` → `{"kept", "played"}`;
  `POST /api/adult/kept` `{"site", "id", "keep": true|false}` (no `keep`: it was played);
  `POST /api/admin/adult-sites` `{"site", "on"}` (admins).
- `user.adult` in `/api/session` is true only when an admin switched Adult on for the person **and** the person has
  said they are 18 or older. `user.adult_ask` is true while the switch is on and they haven't: show them the
  question and send `POST /api/adult/age` `{"ok": true}` on their yes.
  `GET /api/library?since=<generated>` answers `{"same": true}` when nothing changed: ask that
  once a minute.
- A show: `id`, `name`, `poster`, `backdrop`, `logo`, `summary`, `genres`, `premiered`, `network`,
  `rating`, `added`, `seasons: [{"n", "poster", "episodes": [...]}]`, `extras`, and when known
  `missing`, `next_air`.
- A movie: `id`, `title`, `year`, `poster`, `backdrop`, `summary`, `genres`, `runtime`,
  `certificate`, `collection`, `added`, `duration`, `height`.
- An episode: `id`, `s`, `e` (`e2` for double episodes), `title`, `summary`, `aired`, `thumb`,
  `runtime`, `duration`, `height`, `subs`.
- Empty fields are left out. Pictures (`poster`, `thumb`, …) are paths like `/art/shows/…?v=…`:
  add `&w=480` for a picture that wide. Pictures load without signing in at home (TV picture
  loaders can't send headers).

## Watch progress

- `GET /api/progress` → `{"<item id>": {"t": seconds, "d": duration, "done": bool, "at": ms}}`
- `POST /api/progress/<item id>` `{"t": 1234.5, "d": 3600, "done": false}` (every 10 seconds or
  so while playing, and when stopping), or `{"clear": true}`.

## Playing

1. `GET /api/play/<item id>?mkv=1&hevc=1&hevc10=0&ac3=1&vp9=0&maxh=1080` (say what the device plays
   itself; `hevc10` is 10-bit HEVC, and when it's left out `hevc` counts for both; `maxh`, if given, is
   the tallest picture it plays smoothly, and taller videos are converted down to it) →
   `{"mode": "direct" | "remux" | "transcode", "url", "duration", "audio": [...], "subtitles": [{"label", "lang", "url"}], "markers": [{"kind": "intro" | "credits" | "recap", "start", "end"}], "max_height"}`
   (`max_height`: `maxh` when the video is converted because of it; pass it on as `h` below).
   Each of `audio` is `{"index", "label", "lang", "default", "code", "by", "codec", "layout"}` and each of
   `subtitles` also has `"code"`, `"forced"` and `"sdh"` (Sofa 1.5.23): `lang` is the file's own tag (`"spa"`,
   `"und"`), `code` is Sofa's reading of it (`"es"`, `"es-419"`, or `null`: not labelled) and `by` how it knows
   (`"tag"`, `"title"`: the track's name, `"name"`: the file's name). `label` is in English, ready to show; build
   your own from `code` to name languages in the device's language. Pass `audio=<index>` to `/api/hls` or the
   stream for another sound track.
2. `direct`: play `url` (`/media/<id>/file`, supports `Range`). Otherwise ask for HLS:
   `GET /api/hls/<id>?mode=<mode>&t=<start seconds>&h=720` → `{"url": "/media/hls/…/index.m3u8"}`
   (or play `/media/<id>/stream?mode=<mode>&t=<start>` as one MP4 stream).
   - The stream starts at `t`: position 0 in it is `t` seconds into the video. Subtitles for it:
     add `?offset=<t>` to their `url`. `duration` from step 1 is the whole video's.
   - The playlist grows while Sofa converts (an HLS "EVENT" playlist): start at its beginning, and
     don't speed up or jump to catch a "live" edge. When the player runs out, wait for ~10 seconds
     of video before going on, rather than stopping every few seconds.
   - `h` (360, 480, 540, 720, 1080) caps the picture. Without it Sofa picks the tallest picture this
     computer converted that kind of video fast enough at before.
3. Subtitles: each `url` is WebVTT. Scrubbing pictures: `/media/<id>/trick.json`, then
   `/media/<id>/trick/<n>.jpg`.

Media addresses take the same `Authorization` header (ExoPlayer: `DefaultHttpDataSource` request
properties; Roku: `HttpHeaders` on the content node).

## Sofa's apps

- `GET /api/apps` → `{"firetv": {"version", "size", "at"} | null, "fetching", "error", "offline"}`: the
  Fire TV app the Sofa computer keeps (`/firetv` serves it).
- `POST /api/apps/firetv/install` (signed in, at home) installs or updates it on the device asking,
  over ADB (port 5555, "ADB debugging" on); `GET /api/apps/firetv/install` says how it's going:
  `{"state": "preparing" | "connecting" | "approve" | "copying" | "installing" | "opening" | "done" | "failed", "message", "progress"}`.
- Inside the app, `SofaNative.appVersion()` is its build; Sofa offers "Update" when `firetv.version` is newer.

## Being a screen (the phone remote)

An app on a TV can be told what to play by the person's phone:

- `GET /api/screen/wait?id=<random id for this app>&name=Living%20room&tv=1` waits up to 25 seconds
  and returns `{"commands": [...]}`: `{"cmd": "play", "item": "<id>", "t": 0?}`, `toggle`, `pause`,
  `resume`, `seek` (`t`), `skip` (`by`), `next`, `stop`. Ask again straight away.
- `POST /api/screen/state` `{"id": "<same id>", "state": {"item", "t", "d", "paused"}}` every few
  seconds while playing (and `{}` when stopped), so the phone's remote shows it.
