# Handoff

For whoever picks this up next (a person, or a new Claude conversation). Read this first, then the
plan you're continuing. Updated 2026-10-31.

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
Chromium. Not yet: the card built with all of it confirmed on real hardware (the owner's Pi 3 B+), the
browser's own list of open tabs, Comet Courier's address.

## What's in progress

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
  and keeps it a week as an artifact; publishing a release tagged `box-v…` on the website attaches it.
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
