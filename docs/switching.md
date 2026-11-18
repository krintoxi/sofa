# Coming from Plex, Jellyfin or Emby

Since **Sofa 1.5.18**, Sofa brings in what everyone watched: the titles they finished, where they stopped in the ones
they didn't, and what they liked. Each person's history goes into their own Sofa profile. You see what matched
before anything is written, and doing it again later changes nothing that's already in Sofa.

It doesn't move files, and it doesn't need Plex or Jellyfin stopped. Run both side by side for as long as you like,
and import again whenever you want to catch up.

## What comes along

| | Watched | Where you stopped | Likes |
|---|---|---|---|
| **Plex, a copy of its database** | Everyone's | Everyone's | Movies and shows rated 4 stars or more (8 of 10) |
| **Plex, its address and a token** | Everyone's (from Plex's watch history) | Only the token's own account | The token's own account, as above |
| **Jellyfin or Emby, its address and an API key** | Everyone's | Everyone's | Favourites and thumbs-up, movies and shows |
| **Jellyfin, its database** | Everyone's | Everyone's | As above |

Why Plex's address gives less: Plex keeps each account's places for that account's own sign-in, and getting another
account's sign-in goes through plex.tv. Sofa never talks to plex.tv and never asks for a Plex.tv password, so it
reads what the server will tell the token you give it. A copy of Plex's database has everyone's, which is why it's
first in the list.

Left out, on purpose or because Sofa has nowhere to put it yet:

- **Ratings below 4 stars, and ratings of single episodes.** Sofa's likes are a yes or nothing, for a movie or a show.
- **How many times** something was watched, and the full history log. Sofa keeps one state per title: watched, or a
  place to carry on from.
- **Music.** Only shows and movies come along.
- **Playlists, collections, watchlists, Plex's online watchlist and "Discover" history.** They're not in Sofa (or
  they're on plex.tv, which Sofa doesn't use).
- **Audio and subtitle choices** per title.
- **People's accounts.** Make the profiles in Sofa first (Server → People); a profile needs a password of its own, and
  Sofa won't copy anyone's.
- **Emby's database.** Emby comes along through its address and an API key.

## Before you start

1. **Profiles.** Add a profile in Sofa for everyone whose history you want (Server → People). Children's profiles get
   **Kids** switched on. A profile with the same name as the Plex or Jellyfin user is picked for it by itself; you
   can change any of them.
2. **The library.** The titles have to be in Sofa's library to be matched: point Sofa's folders at the same files
   (`"shows"` and `"movies"` in `data/config.json`; see [install.md](install.md)), add the drive under
   **Server → Storage** ([storage.md](storage.md)), or copy them in. Let Sofa finish reading them (Server → Library).
   - If Plex or Jellyfin keeps using the **same folders**, switch off **Tidy folders automatically** (Server →
     Library) first. Tidying renames folders with download-style names (`Heat.1995.1080p` becomes `Heat (1995)`),
     and the other server would lose track of them.
3. **Kids titles.** A Kids profile only gets history for titles it can watch in Sofa: rated for children, or with
   Kids or Family in their genres, or allowed by you on the title's page (**For kids**). The dry run lists what it
   left out; allow those titles, then read again.

## Doing it

**Server → People → Coming from Plex or Jellyfin → Bring history from Plex or Jellyfin.**

1. **Pick where from**, and fill in what that needs:
   - **Plex, a copy of its database:** where `com.plexapp.plugins.library.db` is on the Sofa computer. Plex keeps it in
     `Plug-in Support/Databases` inside its own folder: on a Mac `~/Library/Application Support/Plex Media Server`, on
     Linux `/var/lib/plexmediaserver/Library/Application Support/Plex Media Server`, on Windows
     `%LOCALAPPDATA%\Plex Media Server`, in Plex's Docker image `/config/Library/Application Support/Plex Media Server`.
     If Plex runs on another computer, or Sofa can't read Plex's folder, copy that file (and the `-wal` file beside
     it, if there is one) to the Sofa computer first.
   - **Plex, its address and a token:** Plex's address (like `http://192.168.1.20:32400`) and a token. In Plex's web
     app, open any movie's ⋯ menu → **Get Info** → **View XML**; the token is the `X-Plex-Token` at the end of the
     address of the page that opens (Plex's help page "Finding an authentication token" shows it).
   - **Jellyfin or Emby, its address and an API key:** the address (like `http://192.168.1.20:8096`) and a key you make
     for Sofa: Jellyfin's **Dashboard → API Keys → +**; in Emby, the dashboard (the gear) → **Advanced → API Keys →
     New API Key**. Delete the key there afterwards if you like.
   - **Jellyfin, its database:** Jellyfin's data folder: `/var/lib/jellyfin/data` on Linux, `/config/data` in its
     Docker image, `%PROGRAMDATA%\Jellyfin\Server\data` on Windows. Sofa finds `jellyfin.db` (Jellyfin 10.11 and later)
     or `library.db` with `jellyfin.db` beside it (10.10 and earlier) there.
2. **Folders (optional).** If the other server names the same files by different folders, say how, one line each:

   ```
   /data/movies => /Volumes/Media/Movies
   /data/tv => /Volumes/Media/Shows
   D:\Media => /mnt/media
   ```

   That's usual when one of them runs in Docker, or on another computer. Without it, Sofa still finds a file by its
   folder and file name wherever it is, then by ids, then by title.
3. **Read it.** Nothing is written. For each Plex or Jellyfin user you see how many titles have history, how many
   were found in Sofa and how, what isn't in Sofa, the conflicts, and what was left out for that profile. Pick the
   Sofa profile each one goes to, or **Nobody**.
4. **Import.** The button says how many places and likes it will write.

From the command line, the same thing (a dry run unless you add `--write`; `--list` names the titles):

```
python3 sofa.py import plex-db "/path/to/com.plexapp.plugins.library.db" --map "/data/movies=>/Volumes/Media/Movies"
python3 sofa.py import jellyfin http://192.168.1.20:8096 --user "dad=>Dad" --user "guest=>" --write
python3 sofa.py import --help
```

A token or key is asked for without showing it (or read from `SOFA_IMPORT_TOKEN`), never taken on the command line.

## How titles are matched

In this order, each one only for what the one before didn't find:

1. **The file.** The other server's path, through your folder lines, compared with Sofa's files. The extension
   doesn't count (Sofa's background conversion turns a `.mkv` into an `.mp4` of the same name), nor capital letters,
   nor which way the slashes lean, nor how a Mac spells an accented letter. With no exact match, the same folder and
   file name anywhere in Sofa's library counts, if only one file has them.
2. **IMDb, TMDB or TVDB ids.** Sofa reads them from folder and file names (`{imdb-tt0113277}`, `[tmdbid-949]`,
   `[tvdbid-81189]`), from `.nfo` files beside the video (`movie.nfo`, `tvshow.nfo`), and from the details Sofa saved
   when it looked the title up. An episode is found by its show's ids, then its season and episode number.
3. **The title.** A movie by its title and year (a year either side when that's the only one); an episode by its
   show's name, then season and episode. Specials are season 0. Two episodes in one file (`S01E03-E04`) are one title
   in Sofa: both come to it, and the newer state wins.

**Conflicts** are shown, never guessed: two titles in Sofa that could both be the one (two films of the same name and
no year to choose by), and places where Sofa's is newer.

## What's written, and what isn't

- **Never over something newer.** A title someone already started or finished in Sofa keeps Sofa's state when it's
  newer than the other server's. The check is made again as each one is written, so a film someone is watching right
  now isn't touched.
- **Dates come along.** Continue watching and Next up keep the order people watched things in.
- **No date, no overwrite.** A place the other server kept no date for goes only where Sofa has nothing for that
  title.
- **Likes are only added**, never taken away.
- **Again changes nothing.** A second import of the same history writes nothing; the dry run counts those titles as
  already in Sofa.
- **Profiles stay as they are.** Kids stays Kids and an Adult switch stays where it was. Adult titles only go to
  profiles whose Adult switch is on, and are never named in the dry run to an admin whose own switch is off.
- **Activity** gets one line: how many places and likes, for how many profiles. No titles.

## What Sofa keeps

Nothing about Plex, Jellyfin or Emby. A token or key is used for that one read and isn't written anywhere: not the
settings, not the log, not a backup. A database is read from a private copy (SQLite's own backup, so a running
server is fine), made in Sofa's own data folder and deleted as soon as it's read; the original is only ever read. What was read stays in Sofa's
memory until you import it or start again, and for an hour at most. The browser remembers the form (where from, the
address, the folders) for next time, never the token or key.

## How it was tested

`tests/test_history.py` builds each source and a deliberately untidy Sofa library: a converted file, a renamed one,
ids in a folder name and in an `.nfo`, a film and its remake, two films of the same name, a two-episode file, a
special, an Adult title, a Kids profile, and titles that aren't there at all. Plex's database and both of Jellyfin's
are made with the tables and columns their servers make; stand-in Plex and Jellyfin servers answer as theirs do. On
Plex's database, 21 of the 24 titles with history are found: 7 by the file, 6 by id, 8 by title; the other 3 are the
two-of-the-same-name conflict and two titles that aren't in Sofa.

Against the real thing, in throwaway containers (2026-11-18):

- **Jellyfin 12.4.0**, its API and its `jellyfin.db`, and **Jellyfin 10.10.7**'s `library.db`: two users (one with a
  parental limit), watched, partway and favourite titles, imported into a separate Sofa with renamed and converted
  files. All three found 7 of 7 the same way, the import wrote what the dry run said, and a second import wrote
  nothing.
- **Plex Media Server 1.43.5**: the database it makes, read as it is (with its write-ahead file and its own sorting
  rules), and a copy with history written into its real tables.

Not yet: **a real Plex library with real history** (Plex's matched ids are stored as tags of type 314, which Plex
doesn't document; Plex users' own queries agree), **a real Emby server**, and Plex through its address against a
real server. If you switch, a line in [Discussions](https://github.com/krintoxi/sofa/discussions) saying what
matched and what didn't helps the next person.
