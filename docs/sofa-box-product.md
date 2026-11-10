# Selling Sofa Boxes

Notes for making pre-built Sofa Boxes to sell: a TV box with no ads and no tracking, instead of a Fire
TV or the others. They cover what's ready, how to prepare each box, what a box connects to (so the
promise is accurate), and what's still to do before selling.

## What a buyer gets out of the box

1. They plug the box into the TV, and into the router or not, and switch it on.
2. The **setup** starts on the TV. They work it with what they have:
   - their phone (scan the QR code: it's the remote, nothing to install);
   - a Bluetooth remote held in pairing mode (it pairs by itself);
   - or a keyboard dongle.
3. With no cable and no Wi-Fi, the box makes its own Wi-Fi so the phone can reach it and give it
   the home Wi-Fi.
4. Then they pick their streaming apps, and they're on Home. Free Live TV and **Sofa on the box**
   work without any server. Their own Sofa, a share link, Jellyfin, Emby or Plex can be added any
   time.

Nothing about one box is shared with another:

- the box's Wi-Fi password and the phone codes are made on each box, at random;
- Sofa on the box gets its own account, made by that box;
- SSH is off on the card (Raspberry Pi Imager can switch it on for a box you keep yourself).

## Preparing a box to sell

1. Write a numbered card, like `sofa-box-os-1.0.0.img.xz` from
   [its Sofa Box OS release](https://github.com/krintoxi/sofa/releases?q=box-os), to a good card
   (32 GB, A1/A2). A numbered one stays the same, so every box in a batch is alike and you know which
   version a customer has (Settings → About this box). The
   [newest card](https://github.com/krintoxi/sofa/releases/tag/sofa-box) changes with every fix (it's the testing
   card). Sell the stable one: the release titled "(stable)", tried on a real box
   ([the stable card](https://github.com/krintoxi/sofa/releases/tag/sofa-box-stable)).
2. Boot it once on a TV, and check it reaches the setup. If you set anything up to test it, use
   Settings → Software → **Reset to how it came**. The reset also restarts it into the setup.
3. Switch it off at the setup screen, and box it.

**Hardware:**

- A **Pi 4 (2 GB or more) or a Pi 5** is the one to sell. It plays 1080p in the streaming apps,
  and HEVC in Sofa.
- A Pi 3 B+ works, but it's slow in the streaming apps and limited to H.264.
- Use the official power supply, a case with a fan or a heatsink, and a short HDMI cable.
- A Bluetooth remote in the box makes the first minute easiest. Any "TV remote" style one works, a
  Fire TV one included.

## What the box connects to

The box itself sends nothing about what anyone watches, and keeps no usage statistics. These are the
connections it makes:

| What | Where | When |
|---|---|---|
| Free public Sofas list | raw.githubusercontent.com (this repo's `deploy/sofa-box/servers.json`) | once a day |
| App icons | each app's own website | the first time the App Store opens |
| Sofa Shield's blocklist | raw.githubusercontent.com (StevenBlack/hosts) | once a week |
| The time | the Debian time servers (NTP) | at start |
| Updates | GitHub (this repo) | only when someone presses **Update the box** |
| Live TV channel lists (Sofa on the box) | iptv-org.github.io | twice a day, once it's been opened |
| Apps | their own services (Netflix, YouTube…) | when they're opened, as on any TV |

Chromium is set up so it never signs in, syncs, sends statistics, translates, or offers to save
passwords (`/etc/chromium/policies/managed/sofa-box.json`). It still keeps Safe Browsing's lists
of dangerous sites up to date, like any browser. To switch that off too, add
`"SafeBrowsingProtectionLevel": 0` to that file.

## Still to do before selling

- **Try it on real hardware:**
  - the setup with a phone and with a Fire TV remote;
  - the box's own Wi-Fi;
  - USB drives and a DVD drive;
  - the apps people will try first (Netflix, YouTube, Prime Video, Disney+). Note which ones play
    well on the board you sell.
- **Updates:** today they come only when someone presses **Update the box**. For boxes in other
  people's homes, decide on automatic updates (a weekly check, perhaps) and on a release that's
  been tested, rather than every change on `main`.
- **Names and logos:** the App Store lists other companies' services by name, and the box fetches
  each one's own icon from its website, as a browser's "Add to Home Screen" does. Before selling,
  check what you may say about them on the box and in adverts. Never print their logos on the
  packaging.
- **Support:** a way for buyers to get help, and `sofa-box doctor`'s report for it (over SSH, or a
  "Send a report" button to add).
- **The box's name:** every card is called `sofabox` on the network. Two boxes in one home become
  `sofabox` and `sofabox-2` by themselves.
