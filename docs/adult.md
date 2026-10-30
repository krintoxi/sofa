# The Adult section

## Turning it on for someone

**Server → People**, then the **Adult** switch next to each person. It's off for everyone to
begin with, admins included. Only people with it on see the **Adult** tab.

It's never shown to:

- people with the switch off,
- guests (the QR-code sign-in),
- TVs browsing Sofa without signing in (Roku Media Player, VLC, smart TVs).

Adult videos also stay out of Home, "Continue watching" and search for everyone. They have
their own "Continue watching" inside the Adult tab.

## Adding things

Drop them into **`~/Entertainment/Inbox/XXX`**. Sofa files them like this:

```
Adult/
  Movies/
    Movie Title (2019)/Movie Title (2019).mp4     movies and single scenes (the year is optional)
  Shows/
    Series Name/Season 1/Series Name S01E01.mp4   anything named like an episode (S01E01)
```

Already have a folder called **XXX**, **Adult** or **Porn** inside `Movies`, `Shows` or
`~/Entertainment`? Sofa moves it into the Adult section by itself (with "Tidy folders" on,
which is the default). You can also put files straight into `~/Entertainment/Adult` in the
layout above.

## Artwork and details

- Without anything set up, Sofa takes a still from each video as its poster.
- With a free **ThePornDB** token (**Server → Settings**), Sofa looks up covers,
  backgrounds, descriptions, studio and cast. Get one at
  [theporndb.net](https://theporndb.net/user/api-tokens).
- With a TMDB key, adult movies TMDB knows about get its artwork.
- Wrong or missing match: open the item and press **Find details**.

## Adult live TV

The free iptv-org channel lists stopped carrying adult channels in January 2024, and
there's no other free, legitimate list Sofa can suggest. If you have an M3U link from a
service you trust, add it under **Server → Live TV** and tick **Adult channels**. Those
channels then only appear for people with Adult switched on, and never on TVs.
Channels in any list whose group is "XXX", "Adult" or "18+" are treated the same way.
