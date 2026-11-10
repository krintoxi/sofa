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
| A Mac (macOS 11 or newer is easiest) or Linux; or Docker on anything ([below](#in-docker)) | Windows only through Docker Desktop |
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

## In Docker

For a computer or NAS that runs Docker (Linux, a Synology or similar, a Windows PC with Docker Desktop). The
image is `ghcr.io/krintoxi/sofa` (Python 3.12 on Debian 13 with Debian's ffmpeg, a non-root user, nothing else),
built by GitHub from every change to main and tagged `latest` and with Sofa's version, for amd64 and arm64.

1. Make a folder for Sofa and put [compose.yml](../compose.yml) in it (or clone the repository: the file is at its
   top).
2. In that folder:

   ```sh
   docker compose up -d
   ```

   The first time this pulls the image (or builds it there when it can't: `docker compose up -d --build`).
3. Open `http://<that computer's address>:8090` from a device at home and create the admin account.

Two folders appear beside the file: `./media`, with `Shows/`, `Movies/`, `Music/`, `Music Videos/`, `Inbox/`,
`Needs Review/`, `Adult/` and `Converted Originals/` (drop new things in `Inbox/`), and `./data`, which is Sofa's
`data/` folder (accounts, watch history, settings, artwork, backups: keep it). Sofa runs inside as the user `1000:1000`
unless you set `PUID` and `PGID` to the user that owns those folders (`PUID=$(id -u) PGID=$(id -g) docker compose up -d`);
folders Docker makes itself on the first start are handed to that user (the container starts as root for that one
step and drops to the user before Sofa runs).
Settings live in `./data/config.json` like everywhere else; the first start writes one that points the library at
`/media`, and it's never overwritten.

What's different from an install on the computer itself:

- **The container uses the computer's own network** (`network_mode: host`), not Docker's bridge: TVs and the Sofa
  apps find Sofa by SSDP, and "home network only", the TV sign-in from your phone and Guest access go by the
  address a request comes from, which behind a bridge would always be Docker's. Sofa's port is the `port` setting
  (8090); there is no port mapping to change. Docker Desktop on a Mac or Windows passes host networking through to
  its virtual machine since Docker Desktop 4.34; without it, the Sofa apps can still be given the address by hand.
- **No Bonjour:** the image has no `avahi` or `dns-sd`, so Sofa isn't announced by mDNS. SSDP still is, and the
  apps and a Sofa Box fall back to it (or to the address you type).
- **Updating is a new image:** `docker compose pull && docker compose up -d`. Server → Updates says when GitHub has
  a newer version and shows this command instead of **Update now** (the files inside an image aren't swapped in
  place). `./data` and `./media` stay as they are.
- **Keep this computer awake** has nothing to work with inside a container (no `caffeinate`, no `systemd-inhibit`);
  the computer's own power settings decide.
- **Another drive:** add it to `volumes` under `/mnt`, for example `- /mnt/bigdisk:/mnt/bigdisk`, and Server →
  Storage sees it (`drive_folders` is `/mnt` in the container; `/media` is the library, not a drive).
- **Hardware encoding:** none in the container (x264 in software), the same as Sofa on Linux today.
- The other commands work through compose: `docker compose run --rm sofa status`, `... backup`, `... inbox`.
  The log: `docker compose logs -f sofa`.

Without compose: `docker run -d --name sofa --init --network host -v ./data:/data -v ./media:/media
ghcr.io/krintoxi/sofa`. To build the image yourself: `docker build -t sofa .` in a clone.

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

The log is `~/Sofa/data/sofa.log` (Mac) or `journalctl --user -u sofa` (Linux). It stays empty
with **Keep no logs** on ([privacy.md](privacy.md)).

**No systemd user session** (a container, a server you reach over SSH where `systemctl --user` says it can't
connect to a bus): the installer still writes `~/.config/systemd/user/sofa.service`, then starts Sofa in the
background for this session instead (log in `~/Sofa/data/sofa.log`). To make it start at boot, either give the
user a session that stays (`sudo loginctl enable-linger $USER`, then log in again and run
`systemctl --user enable --now sofa.service`), or install the unit system-wide (`sudo cp ~/.config/systemd/user/sofa.service
/etc/systemd/system/sofa.service`, add `User=$USER` under `[Service]`, then `sudo systemctl enable --now sofa`).
This was found by running the one-line install in a clean Debian 13 container on 2026-11-10: Sofa 1.5.4's installer
stopped at the bus error, and the fix in this version carries on.

Sofa needs no internet to run or to watch: once it's installed (with ffmpeg), every device at
home can use it with the internet down. Only the install itself, ffmpeg and yt-dlp downloads,
updates and lookups use the internet.

## Something's wrong

| What you see | What to do |
|---|---|
| The page doesn't open | Is the computer awake? On a Mac: System Settings → Energy → "Prevent automatic sleeping". Try `http://localhost:8090` on the computer itself. |
| "Can't convert video yet" on the Server page | Install ffmpeg (`brew install ffmpeg`), then restart Sofa. |
| A TV doesn't list Sofa | Server → Settings → "Share with TVs" must be on; the TV must be on the same Wi-Fi. |
| No artwork | Sofa needs internet for artwork. Then see Server → Library → Missing details. |
| A video won't play | See [playback.md](playback.md). |
