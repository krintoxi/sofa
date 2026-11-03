# Sofa Box OS: what's new

Each version gets its own release on GitHub, "Sofa Box OS X.Y.Z", with its card to download:
<https://github.com/krintoxi/sofa/releases?q=box-os>. The newest card is always at
<https://github.com/krintoxi/sofa/releases/tag/sofa-box>.

A new version: change the number in `deploy/sofa-box/VERSION`, add a section here, and merge to `main`.
GitHub builds the card and makes the release by itself.

## 1.0.1

- **The setup's phone code no longer waits for ever on a box with no network.** A card written without
  Raspberry Pi Imager's settings starts with Wi-Fi switched off (Raspberry Pi OS does that until a
  country is set), so the box couldn't make its own Wi-Fi for the phone, and the setup's spinner never
  ended. The box now switches Wi-Fi on by itself at every start.
- If the box still can't make its own Wi-Fi, the setup says so, with what to do (a network cable, or a
  USB keyboard), instead of a spinner. It keeps trying by itself.
- iPhones can join the box's own Wi-Fi (the Pi's Wi-Fi chip needed one setting changed for them).

## 1.0.0

The first numbered Sofa Box OS.

- **Setup without a controller.** The first screen shows a QR code: scan it with a phone and the phone
  is the remote, keyboard and touchpad. A Fire TV remote pairs by holding Home for 10 seconds. With no
  cable and no Wi-Fi, the box makes its own Wi-Fi so the phone can reach it and give it the home Wi-Fi.
- **The setup:** Hello (what you're holding), Internet, Bluetooth, Your box (name, time zone, look), Apps.
- **Sofa from anywhere:** a Sofa at home, a share link on the internet, Sofa on the box itself (free
  Live TV, USB drives, no other computer), or Jellyfin, Emby or Plex. Ask every time, or remember.
- **USB drives, DVDs, Blu-rays and music CDs** play from Home.
- **Popular streaming apps** in the App Store, with proper icons, and a new Home.
- **Made for small boards:** it finds out what it runs on (Pi 3, 4 or 5; 1 to 8 GB) and adapts; the
  app in front gets the box, apps in the background sleep.
- **Fills the TV:** pages are drawn at the TV's full size (the setup was a small square in a corner).
- **Settings → Software:** which Sofa Box OS it is, a note when a newer one is out, Update the box, and
  Reset to how it came (for a new owner).
- **Fixes in this version:** Update and Reset no longer stop half way; after a power cut or a router
  restart, a box that knows its Wi-Fi waits for it instead of switching to its own; opening Sofa on the
  box the first time says it's starting.
