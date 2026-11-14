# Installing Sofa

## The quick way

On Windows, there's an installer: [On Windows](#on-windows). On the computer that will hold your media (a small, quiet one that can stay on is
ideal), open **Terminal** and paste:

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
| A Mac (macOS 11 or newer is easiest), Linux, or Windows 10 (1809) or 11, 64-bit ([below](#on-windows)); or Docker on anything ([below](#in-docker)) | |
| Python 3.8 or newer | Macs: run `xcode-select --install` once if `python3` is missing. Windows: the installer brings its own |
| ffmpeg | Mac: `brew install ffmpeg` (get Homebrew at [brew.sh](https://brew.sh)). Linux: `sudo apt install ffmpeg`. Windows: the installer brings its own |

Sofa runs without ffmpeg, but then only files a device can already play will work.

## By hand

```sh
git clone https://github.com/krintoxi/sofa.git ~/Sofa
cd ~/Sofa
./deploy/install.sh
```

Or just run it in a Terminal window: `cd ~/Sofa && python3 sofa.py serve`. Close the
window and Sofa stops.

## On Windows

Windows 10 (version 1809 or newer) or Windows 11, 64-bit.

1. Download **[sofa-windows-x64-setup.exe](https://github.com/krintoxi/sofa/releases/download/sofa-for-windows/sofa-windows-x64-setup.exe)**
   (the newest; every version has its own under [Releases](https://github.com/krintoxi/sofa/releases), named
   "Sofa 1.5.9" and so on) and open it.
2. **Windows protected your PC?** The installer isn't signed yet, so SmartScreen doesn't know it: **More info**, then
   **Run anyway**. (Its SHA-256 is next to it on the release page.)
3. The installer asks four things:
   - **Where to install:** for you alone, in `%LOCALAPPDATA%\Programs\Sofa`. No administrator needed.
   - **Your library:** where Shows, Movies, Music, Music Videos and the Inbox go. `%USERPROFILE%\Entertainment`
     unless you pick another place; a big drive is a good one (`D:\Media`). More folders, on other drives too, can be
     added later under Server → Storage.
   - **TVs and phones at home:** your other devices reach Sofa over the home network (port 8090, and SSDP and
     Bonjour so they find it), which Windows Firewall blocks until it's allowed. Ticked (the default), Sofa adds one
     rule: Sofa's own Python may accept connections on private networks, never public ones. Windows asks for an
     administrator's permission once. Not ticked, Sofa works on this PC only until you allow it when Windows asks.
   - **Start Sofa when I sign in** (ticked), a desktop icon, and **long paths** (a setting for all of Windows, for
     folders and names longer than 260 characters together; Windows asks for permission).
4. **Start Sofa now** opens it in your browser once it's ready. Create the admin account.

Sofa then lives in the **notification area** (the icons by the clock; in the `^` overflow at first: drag it out to keep
it in view). Its icon is grey while Sofa starts and in Sofa's colours once it runs. **Click it** to open Sofa; its
menu has the address for phones and TVs (`http://<this PC>:8090`), **Restart Sofa**, **Stop Sofa**, **Start with
Windows**, **Open the log**, **Open the Inbox folder** and **Quit Sofa**. Opening **Sofa** from the Start menu starts
it (or, when it runs, opens it).

- **Updating:** Server → Updates → **Update now**, as on a Mac; Sofa starts again by itself. A newer installer can also
  be run over the old one: your accounts, settings and library stay.
- **The log:** `%LOCALAPPDATA%\Programs\Sofa\data\sofa.log` (the menu's **Open the log**).
- **Uninstalling:** Settings → Apps → Sofa → Uninstall. It asks whether to delete Sofa's own data too (accounts,
  watch history, settings, artwork, backups; kept unless you say yes) and removes the firewall rule (Windows asks for
  permission). Your shows, movies and music are never touched.
- **By hand, without the installer:** Python 3.9 or newer from [python.org](https://www.python.org) and ffmpeg
  (`winget install Gyan.FFmpeg`), then in a Command Prompt `git clone https://github.com/krintoxi/sofa.git` (or the
  ZIP from GitHub), `cd sofa`, `python sofa.py serve`. Sofa stops when the window closes; the installer's app is what
  keeps it running, starts it with Windows and opens the firewall.
- **For IT people:** `sofa-windows-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /LIBRARY="D:\Media"` installs
  with no questions (`/NOFIREWALL` leaves the firewall alone; `/TASKS="startup,longpaths"` picks the boxes).

Different from a Mac:

- **It runs while you're signed in** (the same as Plex's Windows app): set Windows to sign you in, or leave the PC
  signed in and locked. Not as a Windows service yet.
- **Keep this computer awake** asks Windows itself; the screen still turns off. With it off, Windows' own sleep
  settings decide (Settings → System → Power).
- **Server → Storage** lists the drives by letter (`E:\`): every drive with a disk in it but the one Windows runs from.
- **Video is converted with x264**, as on Linux; the GPU's encoder isn't used yet.
- Task Manager shows Sofa as **Python** (the app is `pythonw.exe`, the server `python.exe`, both in Sofa's folder).

This has run on GitHub's Windows machines (Windows Server) on every change, installer included, and not yet on a
real Windows PC at home: what was and wasn't tried is in [deploy/windows/README.md](../deploy/windows/README.md#what-has-been-tested-and-how).
If you run it, a [hardware report](https://github.com/krintoxi/sofa/issues/new/choose) helps.

## In Docker

For a computer or NAS that runs Docker (Linux, a Synology or similar, a Windows PC with Docker Desktop: the installer
[above](#on-windows) is simpler there). The
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
- **The graphics chip** converts video in the container too, once the container is given it:
  [The graphics chip in Docker](#the-graphics-chip-in-docker). Without it, Sofa converts with the processor.
- The other commands work through compose: `docker compose run --rm sofa status`, `... backup`, `... inbox`.
  The log: `docker compose logs -f sofa`.

Without compose: `docker run -d --name sofa --init --network host -v ./data:/data -v ./media:/media
ghcr.io/krintoxi/sofa`. To build the image yourself: `docker build -t sofa .` in a clone.

### The graphics chip in Docker

A container sees no graphics chip until it's given one. Give it, and Sofa does the rest: it tries the chip's
encoder for a second, times it, checks its pictures, and uses it only if all three pass. Server → Overview → **This
computer** shows what it found and has the switch.

- **Intel's or AMD's graphics** (VA-API, and Intel's Quick Sync): pass the render node. In `compose.yml`, take the
  `#` off the `devices:` lines; with `docker run`, add `--device /dev/dri`. The node belongs to a group of the
  computer's (`render`, usually) whose number differs from one system to the next: the container's start reads it
  off the node and puts Sofa's user in that group, so there is no number to look up. The amd64 image carries
  Debian's drivers for both makers. If the computer has no `/dev/dri`, its kernel has no driver for the chip.
- **NVIDIA:** install [NVIDIA's container toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  on the computer (`sudo nvidia-ctk runtime configure --runtime=docker`, then restart Docker). In `compose.yml`,
  take the `#` off `gpus: all`; with `docker run`, add `--gpus all`. The image already asks the toolkit for the
  video libraries (`NVIDIA_DRIVER_CAPABILITIES=compute,video,utility`). An older Docker Compose that doesn't know
  `gpus:` takes `runtime: nvidia` and `NVIDIA_VISIBLE_DEVICES: all` under `environment:` instead.
- Then `docker compose up -d` again, and **Test the speed again** on the Server page (Sofa also tests by itself
  when it starts and finds the graphics changed).
- **"This computer's graphics aren't open to Sofa"** on the Server page means the node is there but Sofa's user
  may not use it: a container started as another user (`--user`), or a node owned by root alone. Start the
  container as root (the default: it drops to Sofa's user itself), or add the group by hand with `group_add:`.

What has run where: [Tested hardware](capabilities.md#tested-on). On a NAS, the same lines go in its Docker or
Container Manager screen as a device and, for NVIDIA, a runtime.

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

On Windows, Sofa is `%LOCALAPPDATA%\Programs\Sofa` and its data `...\Sofa\data`; the library is where the installer
put it ([On Windows](#on-windows)).

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

On Windows: the Sofa icon's menu by the clock (Restart Sofa, Stop Sofa, Quit Sofa).

The log is `~/Sofa/data/sofa.log` (Mac), `journalctl --user -u sofa` (Linux) or `...\Sofa\data\sofa.log` (Windows). It stays empty
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
| Windows: phones and TVs can't reach Sofa, this PC can | Windows Firewall: Windows has the home network as **Public** (Settings → Network & internet → your network → Private), or the firewall rule wasn't allowed (run the installer again and allow it). |
| Windows: "Sofa keeps stopping" | The menu's **Open the log**: usually another program on port 8090 (change `port` in `data\config.json`), or an antivirus holding Sofa's files. Then **Start Sofa**. |
| No artwork | Sofa needs internet for artwork. Then see Server → Library → Missing details. |
| A video won't play | See [playback.md](playback.md). |
