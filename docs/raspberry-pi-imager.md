# Raspberry Pi Imager and the Sofa Box card

How Sofa Box OS shows up in Raspberry Pi Imager, how it gets into Raspberry Pi's own list, why Imager's settings
stay off for the card, and whether we need our own imager. Checked against Imager 2.0.12 (commit `84b03d9`,
2026-10-08, still the newest release on 2026-11-18), Imager's `main` at `88d84f3` (2026-11-04), Imager 1.8.5 and
1.9.6, rpi-preseed 0.2.1 (`76bb6d2`, 2026-10-30) and userconf-pi 0.19 (`2dec036`).

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

Only "(testing)" entries come after the top one. Sofa Box Imager ([`imager/`](../imager/README.md)) takes the
first entry without "(testing)" as the one to offer.

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

## Raspberry Pi's own list

Our list is the one people open themselves. Raspberry Pi's own list is the one Imager shows everyone, under
**Choose OS**. Third-party systems sit in its categories (Media player OS holds LibreELEC, OSMC, Volumio and
others). Raspberry Pi adds one on request, through a form. The request is drafted, with every answer and the JSON,
in [launch/raspberry-pi-imager-listing.md](launch/raspberry-pi-imager-listing.md). The owner sends it.

### What Raspberry Pi asks for

Sources, all read on 2026-11-18:

- **[F]**: the form, "Request an addition to the Raspberry Pi Imager OS List" (https://forms.gle/U6JkxVfhHkn5ok2X7).
- **[N]**: Imager's notes, `doc/schema-notes.md` at `88d84f3`, "Requesting an addition to the official Raspberry Pi
  Imager OS List" and "Testing Your JSON Files".
- **[P]**: Raspberry Pi's post "How to add your own images to Imager" (2025-12-11).
- **[T]**: Raspberry Pi's trademark rules, last updated 17 June 2026.

| What they ask | Source | Sofa Box OS |
|---|---|---|
| A named point of contact, ideally two: a person's own name and e-mail, not a mailing list | F | **The owner's to fill in.** |
| Correct device annotations | F | Raspberry Pi's own tags, `pi5-64bit`, `pi4-64bit` and `pi3-64bit`, as Raspberry Pi OS Lite (64-bit) has them. Their tags cover more than one board each, so the list can't say "Pi 3 B+" alone (below). |
| The name, in UTF-8, shown in bold | F | `Sofa Box OS`. |
| A category from their list | F | `Media player OS`. |
| An icon: a 40×40 PNG or SVG, lightweight | F, N | `docs/images/sofa-box-os-icon-40.png`, 40×40, under 3 KB. Its address works once it's on `main`. |
| A description | F | Drafted; it names Raspberry Pi only to say what it's for. |
| A "subitem JSON file": a minimal OS list, at most 4 levels deep, following Imager's schema strictly, with no `imager` block | F, N | `sofa-box-imager-sublist.json` (below). One level, checked against the 2.0.12 schema on every run, and against `main`'s by hand. |
| Accurate metadata: sizes and SHA-256s, and compression Imager knows (`.xz` first) | N, P | The card's own sizes and SHA-256, from unpacking it; the packed SHA-256 is GitHub's digest; `.img.xz`. The 1.1.86 card was downloaded and unpacked again on 2026-11-18: both SHA-256s and both sizes match the list. |
| Hosting that can be relied on | N | GitHub Releases. The entry points at the version's own file, which never changes. |
| Tested with Imager itself, in more than one version, before sending: the addresses answer, the SHA-256 matches | N | **Not yet.** The sublist is published by the merge; the [preview list](launch/sofa-box-imager-preview.rpi-imager-manifest) then shows it as their list would, to write a card with on the Mac with the SD card writer before the request goes in. |
| Does the OS have a default password? | F | **"Other"**: none of its four answers fits a card with no default password that takes nothing from Imager (below). |
| Does the OS update itself, unattended? | F | **"Other" today** (below). |
| "Your OS may need to comply with regulatory requirements in territories where Raspberry Pi Imager is available" | F | Nothing more is asked in the form; the two questions above are its security part. |
| "Raspberry Pi" not in the product's name; only with "for", "runs on" and the like; less prominent than our own name | T 3(i), 4(ii), 4(iii) | Met: "Sofa Box OS", "for a Raspberry Pi 3 B+, 4 or 5". |
| "Raspberry Pi is a trademark of Raspberry Pi Ltd" wherever the name is used | T 4(i) | Added to the README, `TRADEMARKS.md`, this page and the request. edgeventure.uk's shop and downloads pages already carry it; its Sofa page and the box's guide don't yet. |
| A licence from them for commercial use of the name | T 4(iv) | Not needed to be listed: the card is free. Selling boxes would need one. |

Raspberry Pi doesn't ask about the licence, how long a version is supported, or how to report a security hole. We
checked them anyway:

- **The licence.** PolyForm Noncommercial 1.0.0 is source-available, not open source. The form doesn't ask. Its
  categories go by purpose, with one of their own for freemium and paid-for systems; Sofa Box OS is free to use, so
  it goes by purpose. The card also carries Raspberry Pi OS's own packages, Widevine (`libwidevinecdm0`) among
  them, from Raspberry Pi's archive. That package has no licence file of its own (the box's credits say "Google's
  own, passed on by Raspberry Pi"), so whether a card of ours may pass it on to everyone is an open question for
  the owner.
- **Security reports.** `SECURITY.md`, and GitHub's private vulnerability reporting, which is switched on.
- **Support and updates.** `SECURITY.md` says the newest version gets fixes and older ones aren't patched. No end
  date is published. That is the owner's to set.

### The sublist

`tools/sofa-box-imager-list.py build --sublist` writes it beside our own list; the workflow puts it on the
`sofa-box` release:

    https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box-imager-sublist.json

- **The stable card alone**, tried on a real box, at its version's own address (`box-os-vX.Y.Z`), whose file never
  changes. Never the testing version, the newest build, an earlier version or a PC's image: Raspberry Pi's "No
  filtering" shows every entry, and a PC's image doesn't belong on an SD card.
- **`os_list` alone.** The boards are Raspberry Pi's; a sublist with an `imager` block is one of their "common
  pitfalls".
- **Each entry** as our own list has it, plus `image_download_sha256` and an empty `capabilities`, as their
  example and most of their entries have. The icon is the 40×40 one.
- **While no version is marked stable**, no sublist is made, and the one on the release stays as it was.
- **Checked on every run** (`check --sublist`): `os_list` alone, our three boards' tags, a numbered card's own
  file, its packed SHA-256, `armv8`, `init_format` `none`, nothing marked testing; then Imager's schema.
- **Put up only when it changes**, by a swap: the new file goes up as `next-…`, the old one is renamed, the new
  one takes the name, and then the old one goes. Its address is missing for a moment at most. (`--clobber`
  deletes before it uploads.)
- **Raspberry Pi copies it in.** The list Imager downloads from them has no `subitems_url` on 2026-11-18: each
  vendor's sublist is read on their side and its entries copied into the list. A new stable version reaches
  everyone when they next read it, and a sublist they can't read leaves an empty group (three vendors' are empty
  that day).
- **The preview.** `tools/sofa-box-imager-list.py preview` writes
  [`launch/sofa-box-imager-preview.rpi-imager-manifest`](launch/sofa-box-imager-preview.rpi-imager-manifest). It
  holds Raspberry Pi's boards as their list has them, and **Media player OS → Sofa Box OS** reading the published
  sublist: what everyone would see, before anyone has seen it.

Our own list (`sofa-box.rpi-imager-manifest`) is unchanged, byte for byte: Sofa Box Imager and owners who open it
keep the testing versions, the earlier ones and the PC's images.

### Boards

Raspberry Pi's list groups boards under its tags:

- `pi3-64bit` is their "Raspberry Pi 3" (Model A+, B, B+, Compute Module 3 / 3+) **and the Zero 2 W**;
- `pi4-64bit` is the Pi 4, the 400 and Compute Module 4;
- `pi5-64bit` is the Pi 5, the 500 and Compute Module 5.

The card was made for the Pi 3 B+, 4 and 5, and has only run on a Pi 3 B+. Whatever the sublist says, Imager will
offer it for a Zero 2 W (512 MB, a mini HDMI port) and a 3 A+ too. `--boards pi3-64bit` makes a sublist for the
Pi 3 alone; which one to send is the owner's choice.

### The two security questions

**Default password.** The form offers: a default password reset at the first start; a password from Imager's
user; a key from Imager's user; or no networking at all. None of them is the card:

- Root, Raspberry Pi OS's first user (`pi`, with no login shell either) and the box's own user (`sofabox`) are all
  locked. SSH isn't enabled: Raspberry Pi OS's `sshswitch` would turn it on only for an `ssh` file on the boot
  partition, and the card has none. The boot partition has no user, `userconf` or first-start script either.
  (Read from the 1.1.86 card on 2026-11-18, with `debugfs`, read-only.)
- Imager writes nothing to the card (`none`).
- What the box opens on the network has secrets the box makes for itself, shown on the TV:
  - the phone remote's one-time codes (eight letters from outside the home, typing paused after ten wrong ones);
  - the setup Wi-Fi's random eight-digit password;
  - Sofa on the box's own random password.

So the answer is "Other", with that in a few lines. The form says Raspberry Pi will then discuss it by e-mail.
Imager's `user_required` (below) would let the answer be "a password from Imager's user", but only with a format
Imager can customise.

**Unattended updates.** The box installs its updates from our releases, from Settings → Software, and weekly by
itself only if its owner turns that on (off by default, the owner's choice). A new version also brings the packages
the box installs up to date from Raspberry Pi OS's archive. The rest of Raspberry Pi OS isn't: `install.sh` turns
off `apt-daily` and `apt-daily-upgrade` so nothing wakes up during a film, and no other job installs Raspberry Pi
OS's security updates. So today the answer is "Other". To answer "Yes, via an established OS package repository",
the card itself has to change, in two ways:

- the box installs Raspberry Pi OS's security updates by itself, when nobody is watching;
- weekly updates come on by default.

That is a change to the box, for its own version and its own Pi test; it isn't made here.


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
3. **`rpi-preseed` later, only on the rpi-image-gen card (`image-gen`), and only with four things:**
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

   Imager 2.0.12 writes `[user]` only when a name or password is filled in, and then always with
   `groups = ["sudo"]`. It has no `user_required`, and rpi-preseed has no such key either. **Imager's `main`
   added it on 2026-10-29** (`1ae2398`, "let an OS require a user account"), in no release yet on 2026-11-18. It is
   one of an OS entry's `capabilities`: the user step can't be skipped, and Imager won't write without a user
   name and password. It only works with a format Imager can customise, so it does nothing with `none`. With
   rpi-preseed and the four things above, it is how every owner would set a password in Imager, and how the
   listing form's "default password" question gets one of its own answers.

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
  - Started: Sofa Box Imager for the Mac, [`imager/`](../imager/README.md) (0.1.0, unsigned, not yet tried
    with a real SD card).
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
  - The Macs exist: two with Apple silicon, and an Intel one with an SD card slot. Start with macOS.
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

Raspberry Pi is a trademark of Raspberry Pi Ltd. Sofa Box OS is made by EdgeVenture for Raspberry Pi computers; it
isn't made or endorsed by Raspberry Pi Ltd.
