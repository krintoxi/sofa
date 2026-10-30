# Sofa for Roku

A Roku channel for Sofa: Continue watching, Shows and Movies, a show's episodes by season, and
Roku's own player. Files the Roku plays itself (MKV and MP4 with H.264, HEVC on 4K Rokus, AAC and
Dolby sound) play as they are; the rest is converted by Sofa as it plays. Watch progress is shared
with Sofa everywhere else.

## Installing it on a Roku

Roku only installs channels from its store, or "sideloaded" ones on a Roku in developer mode. Sofa
isn't in the store, so:

1. **Developer mode.** On the Roku's remote press **Home** three times, **Up** twice, then
   **Right, Left, Right, Left, Right**. Accept the agreement, choose a password (any), and the Roku
   restarts. It then shows an address, like `http://192.168.1.40`.
2. **Get the channel.** On a computer at home, open Sofa's address with `/roku.zip` on the end, for
   example `http://192.168.1.20:8090/roku.zip` (the Server page shows yours under **Apps**). It
   downloads `sofa-roku.zip`.
3. **Install it.** On the same computer, open the Roku's address (from step 1), sign in as `rokudev`
   with the password you chose, press **Upload**, pick `sofa-roku.zip`, then **Install with zip**.
   Sofa opens on the TV.
4. **First time:** pick your Sofa (it's found on the network by itself, or type its address), then
   approve the code the TV shows on your phone (Sofa → your picture → Pair a TV).

Updating: the same steps 2-3 with a newer zip. The sign-in is kept. A Roku keeps one sideloaded
channel at a time.

## On the remote

- **OK** opens a show or plays; **Back** goes back (and stops playing, keeping your place).
- **\*** (options) on Home: use a different Sofa, or sign out.
- In the player: Roku's own controls (◀◀ ▶▶, the **\*** menu for subtitles and sound).

## How it's made

SceneGraph and BrightScript, no build step: `manifest`, `source/main.brs`, and everything else in
`components/` (`MainScene` is the channel; `ApiTask` talks to Sofa off the screen's thread;
`DiscoveryTask` finds Sofa with an SSDP search). It uses Sofa's API (`docs/api.md`): pairing, a
token in the `Authorization` header (the player sends it too), `/api/library`, `/api/progress`,
`/api/play` and `/api/hls`.

Messages go to the Roku's debug console: `telnet <roku address> 8085`.

To check it without a Roku: `npx brighterscript --rootDir roku --createPackage false` (syntax), or
run it in the brs-node emulator (`npx brs-cli sofa-roku.zip -e`, then press keys with
`curl -X POST localhost:8060/keypress/Select`).
