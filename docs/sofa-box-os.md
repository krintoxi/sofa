# Sofa Box OS: the plan

The Sofa box grows from "a Pi that opens Sofa" into a small TV operating system that replaces a
Fire TV: its own boot screen, a home screen of apps, a browser with ad blocking, an app store of web
apps, games, a file manager and themes. It all runs on Raspberry Pi OS Lite (the box card) on a
Raspberry Pi 3 Model B+ (1 GB), and on any Debian-based small computer.

Status of each part: ☐ not started, ◐ in progress, ☑ done (and tested). Keep this file current; it is
what the next person (or the next conversation) works from. See also [HANDOFF.md](HANDOFF.md).

## What it should feel like

- Turn it on: a **Sofa Box boot screen** (urban / hacker / pirate look, the theme's colours), then
  the **home screen**: big, modern, animated, all workable with a TV remote, a game controller, a
  2.4 GHz keyboard-and-mouse set, or the phone.
- **Home screen:** Continue watching (from Sofa), your apps (Sofa, Edge Music, The LJ Collection,
  Comet Courier, the browser, the store, files, games, settings, and every app you installed), games.
- **Sofa Browser:** a light browser for the TV with ad blocking built in; any site can be put on the
  home screen as an app ("Add to Home").
- **App Store:** pick an app (Pandora, YouTube TV, SomaFM…), press Install: it becomes an app on the
  home screen that opens full screen with no browser around it.
- **Games:** small games that run well on a Pi 3, worked with the remote or a controller.
- **Files:** a simple file manager for downloads and USB drives: look, play, delete, rename, move.
- **Themes:** Street (urban), Terminal (hacker), Pirate, and Sofa; they colour the boot screen and the
  home screen.

## How it's built

One Chromium, full screen (in `cage`, as the box already has), steered by the box's agent through
Chromium's own remote-control interface (the DevTools protocol, on `127.0.0.1:9222` only). Every
screen is a tab the agent opens, brings forward, lists and closes:

```
cage (one full-screen window)
 └─ Chromium --kiosk --remote-debugging-port=9222   (tabs are invisible; the agent switches them)
     ├─ Home        http://127.0.0.1:8091/box/home        always there, the first tab
     ├─ Sofa        http://127.0.0.1:8091/?tv=1           Sofa's TV pages (the box's player for video)
     ├─ apps        https://music.edgeventure.uk, YouTube (TV user agent), Pandora…  a tab each
     └─ browser     any site, with the Sofa bar (address, back, Add to Home)
 mpv               videos from Sofa and from Files, on top of everything
sofa-box-agent.py (127.0.0.1:8091) + boxos.py: the home screen, apps.json, the store, icons, files,
  Sofa Shield, and the DevTools connection (a small WebSocket client, standard library only).
```

- **Why tabs, not windows:** one Chromium process is the lightest on a 1 GB Pi 3; switching is
  instant; music keeps playing in a background tab; and the agent can give each tab what it needs:
  a TV user agent for YouTube's TV site, the Sofa bar, pointer hiding, the Home key. (Tried first: a
  window manager (labwc) with one window per app; Chromium's app windows don't name themselves
  reliably, so switching would have been fragile.)
- **The Sofa bar:** added to every page that isn't Sofa's own (in a separate script world, so sites
  can't see or break it): appears when the pointer touches the top edge or on the remote's Menu key;
  Home, Back, Reload, the address (in the browser), Add to Home, Close.
- **Home key:** in every tab (added script), on the remote (CEC Root Menu → Home), on controllers
  (Xbox/PS button), and over mpv (its key map). All go to `POST /box/api/home`.
- **Memory:** at most 4 app tabs stay open; opening a fifth closes the one used longest ago that
  isn't playing sound.
- **Ad blocking ("Sofa Shield"):** a hosts blocklist for the whole box, refreshed weekly through a
  root helper (`sofa-box shield on|off|update`); on/off in Settings, with how many were blocked.
- **Installed apps:** `~/.config/sofa-box/apps.json`; icons in `~/.config/sofa-box/icons/` (from the
  site's manifest, apple-touch-icon or favicon).
- **Store catalogue:** `deploy/sofa-box/store.json` (curated; DRM ones say so). DRM (Netflix, Disney+,
  Prime, Spotify) needs Widevine: the installer adds `libwidevinecdm0` where Raspberry Pi OS has it; on
  a Pi 3 those services may stutter or refuse.
- **Keyboard and mouse:** 2.4 GHz sets are plain USB keyboards/mice: they work as soon as they're
  plugged in. The pointer hides after a few seconds without movement; type-to-search on the home
  screen; Backspace/Esc = Back.
- **Without the DevTools connection** (the preview on a computer, tests): opening an app gives its
  address back and the page opens it itself.

## Our own apps (live addresses)

| App | Address | Notes |
|---|---|---|
| Sofa | `http://127.0.0.1:8091/` | through the agent (the box's player) |
| Edge Music | `https://music.edgeventure.uk` | repo krintoxi/EdgeVentureMusic |
| The LJ Collection: Showroom | `https://theljcollection.com/showroom.php` | repo krintoxi/TheLJCollection |
| The LJ Collection: Manager | `https://theljcollection.com/manager.php` | needs its sign-in |
| LJ Fragrances | `https://ljfragrances.uk` | |
| Comet Courier (Snail) | **to confirm** | repo krintoxi/Snail; static game, its own IRONGATE site |
| EdgeVenture | `https://edgeventure.uk` | repo krintoxi/EdgeVenture |
| Glossy Gold Toilet guide | `https://edgeventure.uk/tguide/` | on EdgeVenture |

Private repos stay private: the box opens these at their addresses; nothing from them is copied here.

## Parts and status

1. ☑ **Shell:** Chromium with the DevTools port in the kiosk session; the agent's DevTools client
   (open, bring forward, list, close tabs; per-tab user agent; added scripts; the Sofa bar; Home key).
2. ☑ **Home screen** (`deploy/sofa-box/home/`): rows, focus and animations, remote/keyboard/mouse,
   Continue watching from Sofa, running apps, first-start setup.
3. ☑ **Apps:** apps.json, install/remove/move, icon fetching, launching and focusing, TV user agent.
4. ☑ **App Store:** store.json catalogue, store page, Install, "Add any site".
5. ◐ **Sofa Browser:** a start page (search, address, bookmarks), sites in tabs with the Sofa bar
   (address, Back, Reload, Add to Home), downloads to ~/Downloads.
6. ☑ **Sofa Shield:** hosts blocklist, root helper, weekly refresh, settings switch, counter.
7. ☑ **Files:** agent API (list/open/delete/rename/move within Downloads, Music, Videos, USB drives),
   file manager page; open videos/music in mpv, pictures full screen.
8. ☑ **Games:** a few small original games bundled (offline), remote and controller friendly.
9. ☑ **Themes:** Street, Terminal, Pirate, Sofa: home screen and boot screen.
10. ☑ **Boot screen:** "Sofa Box" Plymouth theme in the chosen style (glitch logo, boot ticker).
11. ◐ **Installer and card:** the DevTools port in the kiosk, Widevine, Sofa Shield's helper, the new
   files; the card builds it all.
12. ☐ **Preview:** `tools/sofa-box-preview.py` shows the home screen, store, files and games.
13. ◐ **Tests and docs:** agent API tests (apps, store, files), README for the box.

## Where it stands (2026-10-31)

- Done and tested (tests/test_sofa_box.py: BoxOS, SofaShield, BoxBrowser with a real headless Chromium):
  the home screen and its pages, apps.json, the store, Files, games, the DevTools tab control, the Sofa
  bar (Home, Back, Reload, address, Add to Home, Close), Sofa Shield, browser policies, Home keys from
  the TV remote (CEC Root Menu), controllers and mpv.
- Browser: sites open as tabs with the Sofa bar; the start page is the home screen's Browser page. Not
  yet: a list of open tabs to switch between inside the browser (the home screen's "Open now" row
  does it for now).
- Themes: all four on the home screen and the boot screen ("SOFA BOX", lines ticking by; checked in
  real Plymouth under Xvfb). The Sofa Box logo is a **skull and crossbones in every theme** (the
  owner's wish): paint drips on Street, a screen's corners on Terminal, plain on Pirate and Sofa. The
  Sofa app keeps its couch.
- Installer/card: written, not yet run on the card builder with the new parts (push a change under
  deploy/sofa-box to build it; check the report on the run's page).
- Docs: deploy/sofa-box/README.md describes the home screen, store, browser and Sofa bar, Files,
  games, Settings and themes, with screenshots (docs/images/box-*.jpg).

## Not doing (for now)

- A front panel on a small screen (the MHS35 isn't part of the box any more).
- Native (non-web) apps; Android apps.
