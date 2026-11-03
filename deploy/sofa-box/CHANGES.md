# Sofa Box OS: what's new

Each version gets its own release on GitHub, "Sofa Box OS X.Y.Z", with its card to download:
<https://github.com/krintoxi/sofa/releases?q=box-os>. The newest card is always at
<https://github.com/krintoxi/sofa/releases/tag/sofa-box>.

A new version: change the number in `deploy/sofa-box/VERSION`, add a section here, and merge to `main`.
GitHub builds the card and makes the release by itself.

## 1.1.3

- **The phone's Remote tab works.** Taps and swipes on its round pad went nowhere: the pad shared its name in
  the page with the Touchpad tab's icon, and the page wired the pad up to the icon. Back, Home and the other
  buttons were fine. Checked in an iPhone's Safari: taps, OK and swipes all reach the box.
- **No confusing code swap after you give the box your Wi-Fi.** While it joins, the TV no longer shows the
  codes for the box's own Wi-Fi (they're about to stop working). Once it's joined, the TV waits the few
  seconds for the secure code instead of showing the plain one first and then swapping it.

Still being looked into on a real box: the iPhone's sign-in sheet not opening by itself, Bluetooth remotes and
controllers not showing up, and some apps (YouTube) opening in a small square in the corner of the TV.

## 1.1.2

Fixes from setting up a real box with an iPhone:

- **Joining your Wi-Fi at the setup.** The box now looks for your Wi-Fi before it joins it: just off its own
  Wi-Fi it couldn't see any network yet, and joining could fail for that alone. It answers the phone first and
  then leaves. The TV shows "Joining…", then either that it's connected, with the new code to scan right
  there, or exactly why not (the password isn't right, it can't see that Wi-Fi).
- **No phone left stranded.** The box's own Wi-Fi keeps the same name and password from one time to the next
  (it used to make a new password every time), so after a try that didn't work, your phone can join it again.
  When the phone loses the box, the remote says what to do (scan the code on the TV again) instead of only
  "Can't reach the box".
- **The phone's Remote tab** (arrows, OK, Back) sends its keys straight to the page on the TV, the way the
  Touchpad's clicks already got through. OK carries a real Enter, which some pages need to press a button.
- **Remotes and game controllers over Bluetooth** go to the screen through a device that's now a full keyboard;
  with only a handful of keys it may not have been taken for one.

Still being looked into on a real box: the iPhone's sign-in sheet not opening by itself on the box's own Wi-Fi,
and Bluetooth remotes and controllers not showing up during the setup.

## 1.1.1

- **The secure phone remote is there right after the setup.** When you give a new box your Wi-Fi during its
  setup, it now asks for its name and certificate straight away (it used to wait up to 10 minutes). Until
  then the remote on your home Wi-Fi was a plain http:// page, which iPhones with Safari's Not Secure
  Connection Warning on refuse, halfway through the setup. A box that comes online any other way (a cable
  plugged in later, a router back from a restart) notices within 30 seconds.
- **The boot screen shows the version**, small under SOFA BOX ("OS 1.1.1"). It follows the box's updates.
- **A new box's boot screen is all Street**, the default theme. Until a theme was picked, it had Street's
  colours with another theme's lettering and logo.
- Certificate requests from a Mac's openssl (LibreSSL) name their curve, so Let's Encrypt accepts them.

## 1.1.0

- **A secure (https) phone remote at home.** Once the box is online it gets a name of its own,
  `<random>.box.edgeventure.uk`, pointed at its address on your network, and a real certificate for it,
  from the Sofa Box certificate service. Phones whose browser only opens secure pages (an iPhone with
  Safari's Not Secure Connection Warning on) can use the remote at home. The QR code uses the new address
  by itself; where the router blocks such names, it stays http://. Settings → Remotes and Bluetooth shows
  it and can switch it off. The box sends only a random id and its home address; its key stays on the box.

## 1.0.2

- **The remote opens by itself at the setup.** The box's own Wi-Fi now works like a hotel's: when a phone
  joins it (the first QR code), the phone pops up its sign-in sheet, and the sheet is the remote, already
  paired. The second QR code is only needed if it doesn't open.
- That sheet takes the box's page even on an iPhone with Safari's "Not Secure Connection Warning"
  (HTTPS only) switched on, which refused it ("Navigation failed… HTTPS-Only").

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
