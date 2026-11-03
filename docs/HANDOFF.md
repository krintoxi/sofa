# Handoff

For whoever picks this up next (a person, or a new Claude conversation). Read this first, then the
plan you're continuing. Updated 2026-11-02 (Sofa Box OS versions).

## Where things are

- **Repo:** `krintoxi/sofa` (public). Working branch: `claude/playback-metadata-adult-themes`.
  `main` is at the same commit as the branch unless this file says otherwise.
- **Sofa** is a self-hosted media server: Python standard library only (`sofa/`), a web app with no
  build step (`client/app.js`, `client/sofa.css`, `client/index.html`), tests in `tests/`.
- **The owner's setup:** Sofa runs on a 2011 iMac (macOS Ventura). TV: Panasonic TC-60AS530U (its
  remote is lost). The Sofa box is a **Raspberry Pi 3 Model B+** with a 32 GB card.
- **Other repos of the owner's** that the box links to (private; never copy their code into this
  public repo): `krintoxi/EdgeVentureMusic` (music.edgeventure.uk), `krintoxi/TheLJCollection`
  (theljcollection.com, showroom.php / manager.php), `krintoxi/Snail` (the game "Comet Courier",
  address to confirm), `krintoxi/TheLJCollectionApp` (iOS app).

## What's done (recent)

- Sofa box: `deploy/sofa-box/`: the agent (`sofa-box-agent.py`: finds Sofa, proxies its TV pages with
  a native-player bridge, plays with mpv, Box settings API, previews), boot screen (`sofa-box-art.py`,
  Plymouth), controllers (`sofa-box-input.py`), HDMI-CEC (`sofa-box-cec.py`), installer
  (`install.sh`), the `sofa-box` command (doctor, setup-boot…), the card builder
  (`tools/build-sofa-box-image.sh`, GitHub workflow `sofa-box-image.yml` on ubuntu-24.04-arm).
- Make it yours: accent colours, animations, loading screen, Arrange Home (per profile, `users.prefs`).
- Create an account on the sign-in page, let in by an admin (`users.pending`).
- HTTPS / Let's Encrypt / UPnP / DuckDNS; Fire TV app install from Silk; mobile; guests casting.

## Sofa Box OS: done in this round (2026-10-31)

Home screen with apps, store, browser + Sofa bar, Sofa Shield, Files, games, four themes, first-start
steps, skull logo, themed boot screen; one Chromium steered over DevTools; tests incl. a real headless
Chromium. The card builds with all of it (report in sofa-box-os.md) and everything is merged into
`main` (2026-11-02). Not yet: a first boot on the owner's Pi 3 B+, the browser's own list of open tabs,
Comet Courier's address, a `box-v1` release (the owner publishes it on the website).

## Sofa Box OS versions (2026-11-02)

- Sofa Box OS has its own number in `deploy/sofa-box/VERSION` (1.0.0 now) and its notes in
  `deploy/sofa-box/CHANGES.md`. The box shows it in Settings; the card is `sofa-box-os-<version>.img.xz`.
- On `main` the card workflow publishes the newest card as `sofa-box` (file always `sofa-box.img.xz`;
  the release is kept and its files swapped: uploaded as `next-…`, then each old one deleted and the new
  one renamed, so the link never breaks; the tag is moved to the new commit)
  and, the first time `main` has a new number, the release **Sofa Box OS X.Y.Z** (tag `box-os-vX.Y.Z`),
  kept for good. Neither is "latest" (the Fire TV app's release keeps that). A new version: raise
  `VERSION`, add its section to `CHANGES.md`, merge.
- The README starts with a Sofa Box OS section and download links; so does the box's guide.
- The box reads `VERSION` on main once a day (`newest_version()` in the agent; off in tests with
  `SOFA_BOX_NEWEST=0`); Settings → Software says when a newer one is ready.
- Fixes: `sofa-box update` and `factory-reset` started from the TV now run as their own systemd unit
  (`systemd-run`), so restarting or stopping the agent no longer cuts them off; a set-up box that knows
  a Wi-Fi waits 3 minutes before making its own, and leaves it after 10 quiet minutes
  (`Network.tick`); the home screen says "Starting Sofa…" while Sofa on the box starts.

## Sofa Box OS 1.0.1 (2026-11-03): the setup's phone code on a box with no network

- The owner's first boot: the setup's phone QR code was a spinner for ever. With no cable and Raspberry Pi
  Imager's settings skipped, Raspberry Pi OS starts with Wi-Fi off (pi-gen writes `WirelessEnabled=false`
  to `/var/lib/NetworkManager/NetworkManager.state`, or blocks it with rfkill, until a country is set),
  so `nmcli device wifi hotspot` failed and nothing said so.
- Now: `sofa-box wifi-on` (root; run by `sofa-box tune` at every start, before NetworkManager, and by the
  installer, also into the card) turns it on; the agent runs `nmcli radio wifi on` before the hotspot,
  turns PMF off on the hotspot (iPhones can't join the Pi's with it), retries every 45 s, and the setup
  shows why it failed and what to do. `setup_state` keeps working if one part (Bluetooth…) fails.
- The card's report shows the Wi-Fi state Raspberry Pi OS left and the one the card starts with.
- Not tried on a Pi yet: this is the explanation that fits; the next card's report confirms the state.

## Sofa Box OS 1.0.2 (2026-11-03): the setup Wi-Fi as a captive portal

- On the owner's iPhone the second QR code (http://10.42.0.1:8092/r/<code>) failed: Safari's "Not Secure
  Connection Warning" (HTTPS only) refuses http:// pages. A certificate can't help there (the box is offline).
- Now the hotspot is a captive portal: `/etc/NetworkManager/dnsmasq-shared.d/sofa-box.conf` answers every
  name with 10.42.0.1, and the agent serves a page on port 80 while the hotspot is on (`Captive`,
  `CaptiveHandler`; `AmbientCapabilities=CAP_NET_BIND_SERVICE` in sofa-box-agent.service). The phone's sign-in
  sheet opens it, it goes to `/join`, which pairs a phone on 10.42.0.x without the code (the Wi-Fi's password
  is on the TV: the same proof) and opens the remote.
- To confirm on the owner's iPhone: that the sheet opens and loads with HTTPS-only on (expected: captive
  sheets take http://).
- Next (asked of the owner): HTTPS for the remote at home, with a real certificate per box from a small
  service on the owner's servers, since the remote at home is plain http:// too.

## What's in progress

- **Sofa anywhere** (2026-11-02, built; waiting for the owner's OK to merge and for a try on the Pi):
  - public libraries with a share link (`sofa/sharing.py`, Server → Sharing);
  - adding and switching servers: Sofa, Jellyfin, Emby, Plex (`deploy/sofa-box/boxservers.py`, and the
    app's Servers menu);
  - a box that works with no server: Sofa on the box, Live TV, USB drives, DVD;
  - the box's store, icons, Home and first setup;
  - Server page fixes (`sofa/slow.py`) and a Restart button;
  - sound on previews;
  - the card on GitHub Releases (`sofa-box`), and the install command from GitHub;
  - the phone → box mpv error (`--profile=fast` on Bookworm's mpv);
  - the box's setup with only a phone or a Fire TV remote: setup steps, the phone remote
    (`remote.html`, port 8092), Bluetooth auto-pairing, its own Wi-Fi when offline, time zone,
    Update and Reset.

  The owner plans to **sell pre-built Sofa Boxes**: [sofa-box-product.md](sofa-box-product.md).

  The plan, the status of each part and what's left: [sofa-anywhere.md](sofa-anywhere.md).

- **Sofa Box OS** (home screen, apps, store, browser, ad blocking, files, games, themes):
  [sofa-box-os.md](sofa-box-os.md) has the plan, the status of each part and what's next ("Where it
  stands"). Code: `deploy/sofa-box/boxos.py` (apps, store, files, DevTools client),
  `deploy/sofa-box/home/` (the home screen and the Sofa bar), `deploy/sofa-box/games/`,
  `deploy/sofa-box/store.json`.
- To confirm with the owner: the address of Comet Courier (krintoxi/Snail) for the store.
- Not started: subtitle downloads, notifications, watch together, photos, HDHomeRun recording.

## How to work on it

- Tests: `python3 -m unittest discover -s tests -t .` (about 30 s; the box tests use real mpv if it's
  installed, else `tools/fake_mpv.py`). `node --check client/app.js`. `sh -n` and `shellcheck -s sh`
  on shell scripts. GitHub Actions runs the tests on every push.
- See the box without a Pi: `python3 tools/sofa-box-preview.py [sofa address]` (port 8091).
- A demo Sofa for screenshots: `SOFA_DATA=<folder> python3 sofa.py serve`; Playwright with the
  preinstalled Chromium drives the UI (scripts were kept in the session's scratchpad, not the repo).
- The card: push to the branch (changes under `deploy/sofa-box/` or the builder) builds it on GitHub
  and keeps it a week as an artifact. On `main`, the workflow also publishes it as the release
  `sofa-box`, and as `box-os-v<VERSION>` when that number is new (never marked "latest": the Fire TV
  app's release keeps that). Publishing a release tagged `box-v…` or `box-os-v…` on the website
  attaches a card to it too.
- The box's pieces:
  - `boxservers.py`: the server list, and what answers at an address;
  - each Sofa at `http://<id>.localhost:8091`;
  - `/box/api/*` answers only the home screen's own address, and POSTs need `X-Sofa-Box: 1`.
  Each build writes a report (versions, services, boot settings, space) to the run's summary page.

## Rules the owner set

- Commit messages end with:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01WmiRVGH4T6P2N5fApcittN` (a new conversation uses
  its own session link). No model names in commits or PRs.
- Push the working branch with `git push -u origin <branch>`. **Ask the owner before every merge to
  main**; then `git fetch`, check `git merge-base --is-ancestor origin/main HEAD`, `git push origin HEAD:main`.
- No pull requests unless asked.
- Adult content: never put adult titles in logs, URLs, the activity list or the box's player title.
- Python 3.8/3.9 compatible for Sofa; the box's scripts must run on Python 3.7+.
- Never `pkill -f` a pattern that also matches your own shell; use anchored `pgrep -f '^python3 …$'`.
- Docs are written for beginners: plain words, short steps, screenshots in `docs/images/`.

## Known limits of the cloud environment

- The git proxy refuses pushing **tags** and the GitHub API refuses creating refs/releases (403):
  releases are made by the workflow (GITHUB_TOKEN) or the owner on the website.
- Repository settings (description, website link) can't be changed from a cloud session (403): the
  owner does it on the website. The website link is set to the newest card's release page.
- GitHub Actions log downloads are blocked; the workflows print what matters as job-summary notices,
  readable with `gh api repos/krintoxi/sofa/check-runs/<job id>/annotations`.
