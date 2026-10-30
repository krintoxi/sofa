# Updating Sofa

## The button

**Server → Updates → Update now.** Sofa checks GitHub for a new version twice a day; when
there is one, the Server page shows a dot on **Updates** and a note on **Overview**.

What happens when you press it:

1. Sofa backs up its data (accounts, watch history, settings) into `~/Sofa/data/backups`.
2. It saves a copy of the current version: `data/backups/code-<version>-<date>.tar.gz`.
3. It downloads the new version (with git if you installed with git, otherwise as a
   download from GitHub) and replaces **only Sofa's own program files**.
4. It checks the new version, then restarts itself. The page reloads after about a minute.

If anything fails, the old version keeps running and the Updates tab says why.

## The Terminal command (works with every version)

For a copy of Sofa that's older than the Update button, or if the button ever fails:

```sh
curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/tools/update.sh | sh
```

It finds your Sofa folder by itself (`~/Sofa`, or wherever the background service points).
If yours is somewhere unusual, name it:

```sh
curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/tools/update.sh | sh -s -- /path/to/Sofa
```

It stops Sofa, saves the same two backups, updates, checks the new version, and starts
Sofa again.

## Sofa didn't come back after an update

Right after starting, Sofa answers within a few seconds and shows "Sofa is reading your
library" until your shows appear. If the page doesn't open at all after a couple of minutes:

1. **See what Sofa says.** In Terminal on the Sofa computer:

   ```sh
   tail -n 40 ~/Sofa/data/sofa.log
   ```

2. **Start it again** (Mac):

   ```sh
   launchctl kickstart -k gui/$(id -u)/local.sofa.server
   ```

   On Linux: `systemctl --user restart sofa`.

3. **Update again with the Terminal command** above. It works even when Sofa isn't running,
   and it picks up any fix made since.

4. Still stuck? **Go back** to the version before (below), and open an issue on GitHub with
   the last lines of `sofa.log`.

## What an update never touches

- your media: everything in `~/Entertainment` (or wherever your folders are),
- `~/Sofa/data`: accounts, watch history, likes, settings, fixed matches, artwork cache, backups,
- `~/Sofa/vendor`: a home-built ffmpeg, if you made one.

If you had edited Sofa's code yourself and installed with git, your edits are put aside
with `git stash`, not thrown away (`git stash list` shows them).

## Going back

Unpack the code copy over the Sofa folder, then start Sofa again:

```sh
cd ~/Sofa && tar xzf data/backups/code-<version>-<date>.tar.gz
```

```sh
~/Sofa/deploy/install.sh
```

`ls ~/Sofa/data/backups` lists the copies. Your data is unaffected either way.
