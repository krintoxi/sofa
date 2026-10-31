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

```
labwc (Wayland compositor, what Raspberry Pi OS itself uses; cage as the fallback)
 ├─ Home         Chromium, kiosk, http://127.0.0.1:8091/box/home   (title "Sofa Box")
 ├─ Apps         Chromium --app=<url>, one window each, full screen, no browser around them
 │                (one shared "apps" profile; apps that need a TV user agent get their own)
 ├─ Sofa         an app like the others: http://127.0.0.1:8091/ (Sofa's TV pages via the agent)
 ├─ Browser      Chromium, normal window (tabs, address bar), its own profile, Sofa Browser
 │                extension (Home, Add to Home), policies (start page, search, downloads)
 └─ mpv          videos from Sofa and from Files, on top of everything
sofa-box-agent.py (127.0.0.1:8091): Sofa's pages + the box's player (done), and now also the home
  screen, apps.json, the store catalogue, icons, files, themes, launching and switching apps.
```

- **Window switching:** labwc keybinds: **Home** (remote/keyboard), **Super** and **F1** bring the home
  screen forward (`sofa-box home`); **Alt+Tab** and the remote's Menu key switch between open apps;
  volume keys work. Apps keep running behind the home screen (music keeps playing).
  `wlrctl` (foreign-toplevel) focuses and closes windows by title.
- **Ad blocking ("Sofa Shield"):** a hosts blocklist for the whole box (every app and the browser),
  refreshed weekly by the agent through a root helper; on/off in Settings. In the browser, optionally
  uBlock Origin Lite through Chromium policy for cosmetic filtering.
- **Installed apps:** `~/.config/sofa-box/apps.json`: `{id, name, url, icon, color, ua, zoom}`;
  icons cached in `~/.config/sofa-box/icons/` (from the site's manifest, apple-touch-icon or favicon).
- **Store catalogue:** `deploy/sofa-box/store.json` in this repo (curated; each entry says whether it
  needs DRM). DRM (Netflix, Disney+, Prime, Spotify) needs Widevine: the installer adds
  `libwidevinecdm0` where Raspberry Pi OS has it; on a Pi 3 those services may stutter or refuse.
- **Keyboard and mouse:** 2.4 GHz sets are plain USB keyboards/mice: they work as soon as they're
  plugged in. The home screen and Sofa hide the pointer after a few seconds without movement and show
  it again when the mouse moves; type-to-search on the home screen; Esc/Backspace = Back.
- **First start:** a setup on the home screen: language-free steps for Wi-Fi (typing is easy with
  the keyboard), finding Sofa, the theme and the box's name. Controllers can be paired after.

## Our own apps (live addresses)

| App | Address | Notes |
|---|---|---|
| Sofa | `http://127.0.0.1:8091/` | through the agent (the box's player) |
| Edge Music | `https://music.edgeventure.uk` | repo krintoxi/EdgeVentureMusic |
| The LJ Collection: Showroom | `https://theljcollection.com/showroom.php` | repo krintoxi/TheLJCollection |
| The LJ Collection: Manager | `https://theljcollection.com/manager.php` | needs its sign-in |
| LJ Fragrances | `https://ljfragrances.uk` | |
| Comet Courier (Snail) | **to confirm** | repo krintoxi/Snail; static game, hosted on IRONGATE |

Private repos stay private: the box opens these at their addresses; nothing from them is copied here.

## Parts and status

1. ☐ **Shell:** labwc session (rc.xml, autostart, window rules, keybinds), `sofa-box home/open/close`,
   wlrctl; cage fallback (Home only, no switching). Pointer hiding.
2. ☐ **Home screen** (`deploy/sofa-box/home/`): rows, focus and animations, remote/keyboard/mouse,
   Continue watching from Sofa, running apps, first-start setup.
3. ☐ **Apps:** apps.json, install/remove/move, icon fetching, launching and focusing, TV user agent.
4. ☐ **App Store:** store.json catalogue, store page, Install, "Add any site".
5. ☐ **Sofa Browser:** browser profile + policies, the extension (Home, Add to Home), start page.
6. ☐ **Sofa Shield:** hosts blocklist, root helper, weekly refresh, settings switch, counter.
7. ☐ **Files:** agent API (list/open/delete/rename/move within Downloads, Music, Videos, USB drives),
   file manager page; open videos/music in mpv, pictures full screen.
8. ☐ **Games:** a few small original games bundled (offline), remote and controller friendly.
9. ☐ **Themes:** Street, Terminal, Pirate, Sofa: home screen and boot screen.
10. ☐ **Boot screen:** "Sofa Box" Plymouth theme in the chosen style (glitch logo, boot ticker).
11. ☐ **Installer and card:** labwc, wlrctl, Widevine, policies, extension; the card builds it all.
12. ☐ **Preview:** `tools/sofa-box-preview.py` shows the home screen, store, files and games.
13. ☐ **Tests and docs:** agent API tests (apps, store, files), README for the box.

## Not doing (for now)

- A front panel on a small screen (the MHS35 isn't part of the box any more).
- Native (non-web) apps; Android apps.
