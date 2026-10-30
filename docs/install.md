# Installing Sofa

## The quick way

On the computer that will hold your media (a Mac mini is ideal), open **Terminal** and paste:

```sh
curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/tools/get-sofa.sh | sh
```

It will:

1. download Sofa into `~/Sofa`,
2. install **ffmpeg** with Homebrew if you have Homebrew (ffmpeg lets MKV, AVI and other
   files play on every device),
3. make the `~/Entertainment/Inbox` folder,
4. start Sofa in the background, and set it to start again whenever the computer restarts.

Then open `http://localhost:8090` on that computer, or `http://<its address>:8090` from any
device at home, and create the admin account. The Server page shows the exact address.

Want Sofa somewhere else? Add the folder at the end:
`curl -fsSL .../get-sofa.sh | sh -s -- /Volumes/Media/Sofa`

## What you need

| | |
|---|---|
| A Mac (macOS 11 or newer is easiest) or Linux | Windows isn't supported |
| Python 3.8 or newer | Macs: run `xcode-select --install` once if `python3` is missing |
| ffmpeg | Mac: `brew install ffmpeg` (get Homebrew at [brew.sh](https://brew.sh)). Linux: `sudo apt install ffmpeg` |

Sofa runs without ffmpeg, but then only files a device can already play will work.

## By hand

```sh
git clone https://github.com/krintoxi/sofa.git ~/Sofa
cd ~/Sofa
./deploy/install.sh
```

Or just run it in a Terminal window: `cd ~/Sofa && python3 sofa.py serve`. Close the
window and Sofa stops.

## Where things are

| | |
|---|---|
| `~/Sofa` | Sofa itself |
| `~/Sofa/data` | accounts, watch history, settings, artwork cache, backups. Keep this. |
| `~/Entertainment/Inbox` | drop new things here |
| `~/Entertainment/Shows`, `Movies`, `Music`, `Music Videos`, `Adult` | your library |
| `~/Entertainment/Needs Review` | what Sofa couldn't identify |
| `~/Entertainment/Converted Originals` | originals of files Sofa converted to MP4 |

Your media can live on an external drive: change the folders in `~/Sofa/data/config.json`
(for example `"shows": "/Volumes/Media/Shows"`) and restart Sofa.

## Starting, stopping, restarting

On a Mac:

```sh
launchctl kickstart -k gui/$(id -u)/local.sofa.server     # restart
launchctl bootout gui/$(id -u)/local.sofa.server          # stop (until the next login)
```

On Linux:

```sh
systemctl --user restart sofa
```

The log is `~/Sofa/data/sofa.log` (Mac) or `journalctl --user -u sofa` (Linux).

## Something's wrong

| What you see | What to do |
|---|---|
| The page doesn't open | Is the computer awake? On a Mac: System Settings → Energy → "Prevent automatic sleeping". Try `http://localhost:8090` on the computer itself. |
| "Can't convert video yet" on the Server page | Install ffmpeg (`brew install ffmpeg`), then restart Sofa. |
| A TV doesn't list Sofa | Server → Settings → "Share with TVs" must be on; the TV must be on the same Wi-Fi. |
| No artwork | Sofa needs internet for artwork. Then see Server → Library → Missing details. |
| A video won't play | See [playback.md](playback.md). |
