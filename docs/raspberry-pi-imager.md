# Raspberry Pi Imager and the Sofa Box card

How Sofa Box OS shows up in Raspberry Pi Imager, why Imager's settings stay off for the card, and whether we
need our own imager. Checked against Imager 2.0.12 (commit `84b03d9`, 2026-10-08, the newest release on
2026-11-10), Imager 1.8.5 and 1.9.6, rpi-preseed 0.2.1 (`76bb6d2`, 2026-10-30) and userconf-pi 0.19
(`2dec036`).

## Our list

Imager can show a list of operating systems other than Raspberry Pi's own, which Imager calls a **content
repository**. Ours is `sofa-box.rpi-imager-manifest`, beside the newest card at an address that never changes:

    https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box.rpi-imager-manifest

It shows the following:

- **Its own "Choose device" step:** Raspberry Pi 5, 4 and 3. Imager builds that step from the list's
  `imager.devices`, so a list without them leaves the step empty and Next greyed out. The tags are Raspberry
  Pi OS Lite (64-bit)'s own: `pi5-64bit`, `pi4-64bit`, `pi3-64bit`.
- **At the top, the version to keep:**
  - **Sofa Box OS X.Y.Z (stable)**, the version marked stable (tried on a real box: `deploy/sofa-box/STABLE`,
    and the `sofa-box-stable` release, whose notes name the version and its card's SHA-256). The entry points
    at that version's own card (`box-os-vX.Y.Z`), the same file as `sofa-box-stable.img.xz`, whose address
    never changes to another file. A mark that names a version with no card, or another file than its card,
    is ignored.
  - While none is marked: **Sofa Box OS X.Y.Z**, the newest numbered card.
- **Sofa Box OS X.Y.Z (testing)**: the newest version, when it's newer than the stable one.
- **Sofa Box OS X.Y.Z, newest build (testing)**: listed only when the rolling card (`sofa-box`) differs from
  every numbered one, which happens when the box changes on main without a new number.
- **Sofa Box OS: earlier versions**: five more, newest first.

Only "(testing)" entries come after the top one. Sofa Box Imager (`imager/`, on its own branch for now) takes
the first entry without "(testing)" as the one to offer.

Each entry carries the card's packed size, its unpacked size (`extract_size`) and its unpacked SHA-256
(`extract_sha256`), plus the icon (`docs/images/sofa-box-os-icon.png`), the release date, and the release
page behind Imager's (i) button. Imager checks every byte it writes against `extract_sha256`. If they don't
match, Imager stops and spoils the card's first megabyte on purpose, so a damaged or swapped card can't
boot. Every entry has `init_format: "none"` (see [below](#imagers-settings-init_format)).

### How it's made, and kept up to date for every release

- `tools/sofa-box-imager-list.py build` reads the releases from GitHub's API and writes the list:
  - Imager needs each card's unpacked size and SHA-256, which GitHub doesn't give, so each card is unpacked
    once, as it downloads (about two minutes for 1.1.54's 1.37 GB card).
  - The packed file's SHA-256 is checked against GitHub's own `digest` first: a card that isn't what GitHub
    says is refused, and no list is made.
  - The results are kept in `sofa-box.imager-cache.json` beside the list, keyed by the packed SHA-256, so
    no card is unpacked twice. The rolling card, when it's the same file as a numbered one, costs nothing.
- `tools/sofa-box-imager-list.py check` checks the list:
  - Imager's required fields and types;
  - only our three boards, and a card listed for each;
  - `init_format` is `none`;
  - one level of groups;
  - nothing the box's UI never says.
  - The workflow also checks it against Imager's own JSON schema, pinned to 2.0.12's commit and its SHA-256.
- `.github/workflows/sofa-box-imager-list.yml` does both and uploads the list and the cache to the
  `sofa-box` release:
  - It runs after every card the card workflow builds on main, or for a release made by hand, whether that
    run succeeded or failed (it may have swapped the newest card before failing), and after the stable
    workflow (`sofa-box-stable.yml`) marks a version.
  - It also runs when its tool or the workflow itself changes on main (so right after the merge that adds
    it), every Monday, and by hand.
  - It builds from the releases as they are, so the next run puts right a run that went wrong.
  - It doesn't upload when nothing has changed.
  - It never touches the cards, their checksums or the release notes.
- **A new version needs nothing more.** Raise `deploy/sofa-box/VERSION` as before; the list follows within
  a few minutes of the card.

**One gap, and how to close it.** The testing entry points at `sofa-box.img.xz`, whose file changes
whenever main is rebuilt. Between the card workflow swapping that file and this workflow finishing (a few
minutes), a testing entry already in the list carries the old card's SHA-256, and Imager refuses to finish
that write. The numbered entries never have this problem: their files never change.

To close the gap, the card workflow can build the list itself before it swaps the new card in. Run
`tools/sofa-box-imager-list.py` on the new card in `out/`, upload the list as `next-sofa-box.rpi-imager-manifest`,
and swap it together with the card (the swap already does this for every `next-` file). That's a later change to
`sofa-box-image.yml`. The same change should make the release notes' "How to use it" point at the list instead
of **Use custom**. The stable entry and the numbered ones are never affected.

### Opening it (Imager 2.0 or newer, on a Mac or Windows)

- **Double-click the file.** Imager's installer on Windows, and its app on a Mac, register the
  `.rpi-imager-manifest` file type, so double-clicking `sofa-box.rpi-imager-manifest` opens Imager with our
  list, with no question asked. Imager treats a file the owner opened themselves as trusted.
- **App Options → Content Repository → Edit → Use custom URL** (or **Use custom file**), then **Apply &
  Restart**.
- **A link** `rpi-imager://open?repo=<the address above>` opens Imager and asks "Switch to a custom
  repository?". Its Switch button only becomes pressable after 1.5 seconds. This suits a button on
  edgeventure.uk; GitHub's own pages don't make such links clickable.
- **The command line**, which also works in Imager 1.8 and 1.9:
  - Mac: `"/Applications/Raspberry Pi Imager.app/Contents/MacOS/rpi-imager" --repo <address>`
  - Windows: `"C:\Program Files\Raspberry Pi Ltd\Imager\rpi-imager.exe" --repo <address>`

Imager keeps the list only until it closes. It doesn't save it, so it never changes what Imager shows the
next time. While our list is open, the title bar says "Using data from" and the host the list came from.
GitHub sends release downloads on to `release-assets.githubusercontent.com`, so that's the name it shows.
Imager follows the redirect and doesn't refresh the list unless the list asks it to (ours doesn't).

**Not checked on a real Mac or Windows PC yet.** The double-click, the App Options route, the link, and a
write with Imager's check have only been read in Imager's code. The list itself passes Imager 2.0.12's
schema and was built from the real releases: the 1.1.54 card's packed SHA-256 matched GitHub's digest. Its
unpacked size, 5,226,102,784 bytes, is exactly Raspberry Pi OS Lite 2026-10-06's 3,078,619,136 plus the
2 GiB the build adds.

## Imager's settings (`init_format`)

Imager's settings are the user name and password, Wi-Fi, SSH, hostname and locale. Imager only offers them
when the list says how the card takes them, through `init_format`:

| `init_format` | What Imager 2.0.12 writes to the card's boot partition |
|---|---|
| `none` (or `""`) | Nothing. No settings steps are shown. |
| `systemd` | `firstrun.sh`, plus `systemd.run=/boot/firstrun.sh … systemd.unit=kernel-command-line.target` in `cmdline.txt` |
| `cloudinit`, `cloudinit-rpi` | `user-data`, `network-config`, `meta-data`, plus a `ds=nocloud` entry in `cmdline.txt` |
| `rpi-preseed` | `rpi-preseed.toml` only, plus `cfg80211.ieee80211_regdom=XX` in `cmdline.txt` when a Wi-Fi country is set |

Today's card with each Imager:

- **Imager 2.x, our list:** `none`, so Imager writes nothing to the card. The box sets itself up on the TV.
- **Imager 2.x, "Use custom":** also nothing. `OSSelectionStep.qml` calls `setSrc(fileUrl)` with no
  format, so Imager offers no settings.
- **Imager 1.x, our list (`--repo` only):** `"none"` becomes `""` in `setSrc`, so again no settings.
- **Imager 1.x, "Use custom":** the only route that offers the settings. For a local file, Imager 1.8.5 and
  1.9.6 guess:
  - cloud-init if the boot partition has a `user-data` file;
  - otherwise `firstrun.sh` if `issue.txt` mentions pi-gen;
  - otherwise cloud-init.

  Either way a user made there goes through the rename below. Raspberry Pi's own doc says Imager 1.x
  "assumes systemd" for local files, but the code guesses as above. Before Sofa Box OS 1.1.56 that stopped
  the TV screen; since 1.1.56 the box undoes it (below), and the guide says these settings are fine.

### Why a user made by Imager stopped the TV screen (before 1.1.56)

Every route Imager has for making a user ends in Raspberry Pi OS's rename helpers:

- **`firstrun.sh`** calls `/usr/lib/userconf-pi/userconf`.
- **cloud-init:** on 2026-11-03, cards with a cloud-init user hung on the boot screen twice and restarted
  in a loop once. That user went through userconf and cancel-rename.
- **rpi-preseed's `[user]` step:** `src/apply/user.sh` runs `$USERCONF`, which is
  `/usr/lib/userconf-pi/userconf` by default.

`userconf` renames uid 1000 and sets the password, then runs `cancel-rename`, which:

- resets the boot behaviour through `raspi-config nonint do_boot_behaviour` (B3 or B4 when the default
  target is graphical, as the box's is; B1 or B2 otherwise);
- disables `userconfig`;
- **enables and starts `getty@tty1`**, a text login on the screen the box draws on.

That's the 2026-11-03 failure. **Sofa Box OS 1.1.56 fixed it on the box's side:** once Raspberry Pi OS's
first-start tools are done, the box sets its own start-up target again and takes the login off the TV's
screen, at the first start and at every start after (see `deploy/sofa-box/CHANGES.md`). Imager's Wi-Fi,
SSH, time zone, keyboard and hostname are kept. That was made for Imager 1.8 and 1.9's routes; nothing has
been tried yet with a format the list itself would offer.

### Recommendation

1. **Now: `none`.** It's the only format that writes nothing to the card, and the box already does what the
   settings would: it joins Wi-Fi by phone, remote or keyboard, takes its name in the setup, and sets the
   time zone from the phone. Imager's check of the whole card still applies. What owners lose is SSH from
   Imager (the `pi` user has no password), the same as with "Use custom" in Imager 2 today. A format in
   the list would offer Imager's settings to every owner, so it waits for an off-hardware test and a
   real-Pi pass (below), even after 1.1.56.
2. **Not `systemd`.** It boots the first start into `kernel-command-line.target`, which isn't the TV's
   target. `cloudinit` or `cloudinit-rpi` are the formats 1.1.56's fix comes closest to (Imager 1.x's
   cloud-init route), but they're untried with Imager 2's own `user-data`. The box switches cloud-init off
   after its first start (`install.sh`), so settings changed later in Imager would never apply.
3. **`rpi-preseed` later, only on the rpi-image-gen card (`claude/image-gen`), and only with four things:**
   - That card ships no cloud-init, which suits rpi-preseed: its package `Conflicts: cloud-init`, so on
     today's card installing it would remove cloud-init.
   - **The box owns the user step.** rpi-preseed reads the helper's path from the environment
     (`: "${USERCONF:=/usr/lib/userconf-pi/userconf}"` in `src/lib/common.sh`). A drop-in for
     `rpi-preseed.service` with `Environment=USERCONF=/usr/local/lib/sofa-box/userconf` can rename the user
     and set the password without `cancel-rename`. That's not a documented interface, so pin rpi-preseed's
     version and test it. Or the box puts its target back, and `getty@tty1` off, after rpi-preseed and
     before its own screen.
   - **A test off the hardware:**
     - Take the TOML that Imager 2.0.12's generator writes (for nothing, Wi-Fi only, a user and password,
       and everything) and apply it with rpi-preseed's sandbox mode (`RPI_PRESEED_ROOT`) to the card's root
       files.
     - Check the default target, `getty@tty1`, `sofabox` and its sudo rule, and the NetworkManager
       connection.
     - Run `systemd-analyze verify` on the ordering against `sofa-box.service` and the first-start units.
   - **Then one real-Pi pass** (below) before the list says `rpi-preseed`.

   There's no `user_required` key in rpi-preseed 0.2.1 or Imager 2.0.12, despite the earlier plan note.
   Imager writes `[user]` only when a name or password is filled in, and then always with
   `groups = ["sudo"]`.

**What only a real Pi can confirm** (Pi 3 B+ first, then a Pi 4 and a Pi 5, each card written by Imager 2.x
from the list):

- `rpi-preseed.service` finishes before the box's first-start units and its screen, while the card grows
  and the box restarts once. Its run-once marker (`/var/lib/rpi-preseed/applied`) must survive that
  restart.
- With a user set in Imager, the TV screen still comes up, tty1 doesn't take the screen, and SSH works as
  that user.
- With Wi-Fi set in Imager:
  - the box joins it at the first start;
  - the setup skips its own Wi-Fi steps;
  - the country from `cmdline.txt` works with the box's own `wifi-on` (Raspberry Pi OS blocks Wi-Fi until
    a country is set).
- A hostname set in Imager against the box's own name (`sofabox`) and its name on the network.
- How long the first start takes on a Pi 3 B+ with each set of settings.
- That Imager on a Mac and on Windows writes `rpi-preseed.toml` where the card reads it
  (`/boot/firmware/rpi-preseed.toml`).

## Our own imager: fork, build our own, or the list?

The owner wants every Sofa product reachable without sending people to a third party's site. Three ways:

| | The list (done) | Fork Imager | Build our own |
|---|---|---|---|
| What owners install | Raspberry Pi Imager, from raspberrypi.com | "Sofa Box Imager", from us | "Sofa Box Imager", from us |
| Code we keep up | One script and one workflow | All of Imager (Qt 6, C++, QML): every upstream release rebased onto our changes | A small app that does one thing |
| Name and logos | Theirs | Must lose Raspberry Pi's name and marks (Apache-2.0 §6), its URL scheme and file type | Ours from the start |
| Disk writing | Theirs, proven on three systems | Theirs, proven | Ours to get right: the risky part |
| Signing | None needed | Apple Developer ID ($99 a year) plus notarisation; a Windows code-signing certificate | The same |
| Telemetry | Imager reports downloads to Raspberry Pi | Switch off `TELEMETRY_URL` | None |
| Settings for the box | None (`none`) | Imager's wizard, which broke the box before 1.1.56 | Our own: Wi-Fi and a name, written to a file the box reads itself, never a user |

**Recommendation:**

- Ship the list now: it works with the Imager people already have.
- **Build our own, small, in-house, not a fork.**
  - A fork would carry Imager's customisation wizard (the very thing that broke the box), Pi Connect,
    secure boot, fastboot and EEPROM tools, all of which we'd switch off. We'd still rebase a large Qt
    app onto every upstream release.
  - Our own app needs one path: pick the card, write Sofa Box OS (the stable version, or the newest while
    none is marked), check it, eject.
  - It can read this same list (the same JSON) for the card, its size and its SHA-256.
  - Started: Sofa Box Imager for the Mac, in `imager/` on its own branch
    ([krintoxi/sofa#39](https://github.com/krintoxi/sofa/pull/39), a draft).
  - Apache-2.0 lets us reuse parts of Imager's code with its licence and notice, where that's safer than
    writing them anew. Disk handling is the obvious case.

What it takes:

- **Never the wrong disk.** This is the dangerous part: a bug here erases someone's computer, and it can't
  be undone.
  - Removable or external disks only, never the startup disk.
  - Show the card's name and size before writing, and refuse anything larger than an SD card plausibly
    is.
  - Unmount it first, write, read every byte back and check it, then eject.
- **Admin rights to write a disk:** `authopen` on a Mac, an elevated helper on Windows (lock and dismount
  the volumes, then write `\\.\PhysicalDriveN` in whole sectors).
- **Signing:** an Apple Developer ID with notarisation, and a Windows signing certificate. Both are the
  owner's accounts to open. Without them, macOS sends people to Privacy & Security → Open Anyway, and
  Windows shows SmartScreen.
- **Testing on real machines:**
  - The Macs exist: Neo, the iMac with its SD writer, and the M4. Start with macOS.
  - There's no Windows PC in the fleet. A Windows writer that has never written a real card shouldn't
    reach owners, so Windows waits for one, and the list in Raspberry Pi Imager covers Windows until then.

## Later: every EdgeVenture OS and distro in one list

Each product keeps its own list, made from its own releases like this one. One EdgeVenture list, say on
edgeventure.uk, then holds one entry per product with `subitems_url` pointing at that product's list.

- **The top list carries the boards.** Imager reads `imager.devices` only from the top list, so the
  EdgeVenture list carries every board any product supports, and each product's entries name the boards
  they're for.
- **A website button opens it:** `rpi-imager://open?repo=…` opens the whole EdgeVenture list in Imager.
- **Our own imager reads the same list.**
