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
- On `main` the card workflow publishes the newest card as `sofa-box` (file always `sofa-box.img.xz`)
  and, the first time `main` has a new number, the release **Sofa Box OS X.Y.Z** (tag `box-os-vX.Y.Z`),
  kept for good. Neither is "latest" (the Fire TV app's release keeps that). A new version: raise
  `VERSION`, add its section to `CHANGES.md`, merge.
- The README starts with a Sofa Box OS section and download links; so does the box's guide.
- Fixes: `sofa-box update` and `factory-reset` started from the TV now run as their own systemd unit
  (`systemd-run`), so restarting or stopping the agent no longer cuts them off; a set-up box that knows
  a Wi-Fi waits 3 minutes before making its own, and leaves it after 10 quiet minutes
  (`Network.tick`); the home screen says "Starting Sofa…" while Sofa on the box starts.

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
  releases are made by the owner on the website.
- GitHub Actions log downloads are blocked; the workflows print what matters as job-summary notices,
  readable with `gh api repos/krintoxi/sofa/check-runs/<job id>/annotations`.
