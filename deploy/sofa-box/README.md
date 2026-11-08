# The Sofa Box (a Raspberry Pi on the TV)

Your own TV box, in place of a Fire TV: a Raspberry Pi on the TV that starts on its own home screen,
with Sofa, free Live TV, your streaming apps, a browser, an app store, games and a file manager. No
ads, no account, and nothing watching what you watch; the TV itself never needs to be online.

> **Sofa Box OS, Sofa App, Sofa Server: which is which?** **Sofa Box OS** is the system on the Pi (this
> guide). It has the **Sofa App** built in, the part you watch with. Your own shows and movies live on a
> **Sofa Server**, a program on a computer that stays on; the box opens yours, a friend's, or a small
> one on the box itself. You don't need a Sofa Server for Live TV or streaming apps.
> [The three parts, side by side](../../README.md#three-parts-sofa-server-sofa-app-and-sofa-box-os)

**[⬇ Download Sofa Box OS](https://github.com/krintoxi/sofa/releases/tag/sofa-box)** (the newest card) ·
[Every version](https://github.com/krintoxi/sofa/releases?q=box-os) · [What's new](CHANGES.md)

<img src="../../docs/images/box-home.jpg" alt="The Sofa Box home screen: the time and a hello, Open Sofa and Live TV, the weather, and a Watch row with Sofa, Live TV and YouTube" width="100%">

- **Sofa from anywhere:** your Sofa Server at home, a Sofa Server on the internet (a share link someone
  sent you), **Sofa on the box itself** (no other computer needed), or your Jellyfin, Emby or Plex server.
  It plays with the box's own player (mpv, on the Pi's video chip), so most files play as they are.
- **Free Live TV** has its own tile, and works with no server at all.
- **Streaming apps** (Netflix, YouTube, Prime Video, Disney+, Max, Hulu…), our own (Edge Music,
  The LJ Collection, LJ Fragrances) and anything else from the **App Store** open full screen, with
  no browser around them. **Home** brings you back; they keep playing.
- **USB drives and DVDs:** plug in a drive and its videos, music and pictures are in Files; put a
  DVD or music CD in a USB disc drive and play it from Home.
- **Browser**, with **Sofa Shield** keeping ads and trackers out of the whole box. On any site, the
  **Sofa bar** (Menu key, or the mouse at the top edge) has **Add to Home**: the site becomes an app.
- **Games** that run well on the box, **Files** for downloads and USB drives, and **themes**: Street,
  Terminal, Pirate or Sofa, for the home screen and the boot screen.

## What you need

- A **Raspberry Pi 3 Model B+**, 4 or 5, and its power supply. A Pi 3 needs the proper 2.5 A
  supply: a phone charger makes it slow down and stutter.
- A **microSD card**, 8 GB or more (a 32 GB card is plenty).
- An **HDMI cable** to the TV (micro-HDMI on a Pi 4/5), and if you can, a **network cable** to the
  router (better for video than Wi-Fi).
- Something to work it, any of (nothing else needed):
  - **your phone** (iPhone or Android): the box shows a QR code; the phone becomes its remote, keyboard
    and touchpad (see [The phone remote](#the-phone-remote));
  - **a Fire TV remote** (or another Bluetooth remote): hold its **Home** button for 10 seconds during
    the setup, and it pairs by itself. Its power and volume buttons keep working the TV as before;
  - **the TV's own remote**, through the HDMI cable (HDMI-CEC; Panasonic calls it VIERA Link). A
    universal remote set to the TV works as well as the original;
  - **a 2.4 GHz keyboard and mouse** (the kind with one small USB dongle): plug in the dongle and they
    work straight away, the easiest for the first start and for typing in the browser;
  - **a game controller** (Xbox, PlayStation, 8BitDo…), over Bluetooth or a USB cable;
  - a cheap "air mouse" remote with a USB dongle (it acts as a keyboard and mouse).

## Setting it up: the ready-made card (easiest)

1. Download **`sofa-box.img.xz`** from the
   [newest card](https://github.com/krintoxi/sofa/releases/tag/sofa-box), under **Assets**. GitHub
   makes it again every time the box changes. Each version also has a release of its own that stays,
   "Sofa Box OS 1.1.1" and so on ([every version](https://github.com/krintoxi/sofa/releases?q=box-os)).
   The release's title says which version the newest card is.
2. Install **Raspberry Pi Imager** (raspberrypi.com/software) on your computer and open it.
   Choose your Pi, then **Choose OS → Use custom** and pick the file, then your card.
3. When it asks about **OS customisation**, you can press **Edit settings** to add your Wi-Fi, and
   a user name and password with SSH under Services (only needed to look inside the box later). Or
   press **No**: a network cable needs nothing.
4. Write it, put the card in the Pi, plug in HDMI (and the network cable), then power.
5. The TV shows the Sofa Box boot screen, then the **setup** (see below). The first start takes a
   few minutes.
6. **Open Sofa** from Home. The first time it asks where from (see below); after that it opens
   straight away, or asks each time if you prefer.
7. **Sign in:** your Sofa Server shows a code and a QR code. On your phone, open Sofa, press your
   picture, then **Pair a TV**, and type the code (or scan the QR). Sofa on the box signs itself in.

From then on the box starts on its home screen whenever it's switched on.

### The setup (the first start)

A new card's **first start takes a few minutes** (the card grows to fill the SD card and the box sets
itself up), and it may restart once by itself. Its boot screen says so: just wait.

<img src="../../docs/images/box-setup.jpg" alt="Setup: Hello. Let's set up your Sofa Box. Your phone (a QR code), A remote or controller, Keyboard and mouse" width="100%">

1. **Hello:** pick up whatever's in your hand.
   - **Phone (the Sofa Setup Assistant):** point its camera at the code on the TV: the first connects your
     phone to the box, the next opens the Setup Assistant, where you choose your Wi-Fi. Once the box and your
     phone are back on your Wi-Fi, the assistant carries on by itself as the remote (if it can't, the TV
     shows one last code to scan).
   - **Fire TV remote** (or another Bluetooth remote, or a game controller): put it in pairing mode.
     For a Fire TV remote, hold **Home** for 10 seconds. It pairs by itself.
   - **Keyboard and mouse:** plug in the dongle.
   Once your phone is the remote on your Wi-Fi, the setup goes on by itself (to **Your box**): nothing
   to press. With a remote or a keyboard, press **Start** (it's always at the bottom of the screen).
2. **Internet** (only when the box isn't online yet): a network cable needs nothing. For Wi-Fi, pick
   your network and type the password; the phone's **Keyboard** tab types it, which is easier than a
   remote. Once it's connected, the setup goes on by itself.
3. **Your box:** its name (on the boot screen), the **time zone** (your phone sets it when it
   connects), and its look.
4. **Apps:** tick the streaming apps you use; they go on Home, ready to sign in.

Speakers, headphones and more controllers wait until you want them: **Settings → Remotes and
Bluetooth**, or **Games** for controllers.

**No cable and no Wi-Fi yet?** After a few seconds, the box makes its own Wi-Fi, "Sofa Box 1234". The TV
takes you through four steps, one code at a time, and says under each what it's waiting for:

1. **Join the box's Wi-Fi:** scan the code with your phone's camera. Once your phone has joined, this
   code goes and the next one shows.
2. **Open the remote:** scan the new code. (Some phones open the remote by themselves after step 1.)
3. **Give the box your Wi-Fi:** the remote opens on its **Wi-Fi** tab; pick your home Wi-Fi and type its
   password. The box leaves its own Wi-Fi to join yours, and your phone goes back to your Wi-Fi. The TV
   shows "The box is joining…", then either that it's connected or why not (the password, say). If it
   didn't work, the box's own Wi-Fi comes back with the same name and password: join it again and retry.
4. **Keep the remote:** once it's connected, **scan the code on the TV** to carry on. At home the remote
   has the box's own secure address (`https://…box.edgeventure.uk:8093`, see
   [The phone remote](#the-phone-remote)).

A step that went too fast or a phone that dropped off: **Show the code again** under the step brings it
back.

**An iPhone that only opens secure pages** (**Settings → Apps → Safari → Not Secure Connection
Warning** on): Safari refuses the box's page on its own Wi-Fi ("HTTPS only"), so switch that setting off
for the setup and back on afterwards. At home the remote is `https://`, which it opens either way. If the
TV still shows a plain `http://` address at home, wait a moment for it to change, or see the router note
under [The phone remote](#the-phone-remote).

**The setup says it couldn't make its own Wi-Fi?** Plug a network cable from your router into the box:
the code to scan shows within seconds. Or write the card again, and in Raspberry Pi Imager press
**Edit settings**, tick **Configure wireless LAN**, type your Wi-Fi's name and password and pick your
**Wireless LAN country**: the box then joins your Wi-Fi by itself. (Before Sofa Box OS 1.0.1 the setup
showed a spinner for ever in this case.)

Later on, if the router is off for a while (a power cut, a restart), a box that knows your Wi-Fi waits
for it to come back. Only after three minutes with no network does it make its own Wi-Fi again (handy
if you've moved house), and after ten quiet minutes on it, it looks for your Wi-Fi again.

### The phone remote

<img src="../../docs/images/box-phone-remote.jpg" alt="The phone remote: a round pad with OK, Back, Home, Menu, playback and volume buttons, and Remote, Keyboard, Touchpad and Wi-Fi tabs" width="260" align="right">

There's nothing to install from an app store: **the box serves the remote itself**.

- **Connect a phone:** scan the QR code on the TV with the phone's camera (Settings → Remotes and
  Bluetooth shows it any time). Or open the address under it and type the four numbers. The phone
  needs to be on the same Wi-Fi as the box.
- **Keep it like an app:**
  - **iPhone:** in Safari, tap **Share** (the square with the arrow), then **Add to Home Screen**.
    It gets the box's skull icon, and opens full screen like any app.
  - **Android:** in Chrome, open the **⋮** menu, then **Add to Home screen**.
  - The remote shows this tip itself, once.
- **Using it:**
  - Swipe on the big pad to move, tap the middle for **OK** (or tap an edge, or hold it to keep
    going). Then **Back**, **Home**, **Menu**, play/pause and skip, and volume.
  - **Keyboard** types into the box: a search, an address, a password.
  - **Touchpad** is a mouse, for the odd website that needs one.
  - **Wi-Fi** changes the box's network.
- **Several phones** can be remotes at once. Settings → **Forget phones** makes them all scan again.
- **Good to know:**
  - It works at home only; a phone from outside never gets in.
  - If your router gives the box a new address, scan the code again. Reserving the box's address
    in the router stops that. (With the secure remote below, its name follows the box, so the phone
    keeps working.)
- **Secure (https) at home.** Some phones only open secure pages, for example an iPhone with
  **Settings → Apps → Safari → Not Secure Connection Warning** on. So once the box is online, its remote
  has a secure address through the **Sofa Box service's relay**:
  `https://boxcert.edgeventure.uk/r/k3x9q2abcd/`. The QR code on the TV uses it by itself, and it works
  from anywhere, at home or away (the phone's taps go to the service and on to the box, which keeps a
  connection open to it).
  - The phone still needs the TV's code: the QR code's long one (24 characters). Typing the four
    digits works at home only, so nobody can guess at them from the internet.
  - What passes through the service: your phone's taps, typing and the box's answers, on their way.
    Nothing is kept. To reach the box the service only needs its random id.
  - No certificate or name per box, so no Let's Encrypt limits, and it works with routers that block
    names pointing at home addresses ("DNS rebinding protection").
  - **Settings → Remotes and Bluetooth** shows how it's doing, and **Switch off** turns it off (phones
    at home then use plain `http://`).
  - The old way, a name and certificate per box (`https://k3x9q2abcd.box.edgeventure.uk:8093`, home
    only), is still there: `"remote_link": "certificate"` in the box's settings.json.
  - How the service works, and how to run it: [deploy/box-certs](../box-certs/README.md).
<br clear="right">

## Setting it up on the card you already have

The installer works on Raspberry Pi OS (Lite or with a desktop) and on other Debian or Ubuntu
systems. From the Pi's own keyboard and screen, or over SSH (`ssh you@raspberrypi.local`), run:

```
curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/deploy/sofa-box/install.sh | sudo sh
```

It gets everything from GitHub, so no Sofa Server is needed. To start with your Sofa Server
already on the box's list, add its address at the end (Sofa's **Server → Overview → Apps** shows the
whole line ready to copy):

```
curl -fsSL https://raw.githubusercontent.com/krintoxi/sofa/main/deploy/sofa-box/install.sh | sudo sh -s http://192.168.1.20:8090
```

It takes about 10 minutes on a Pi 3, then Sofa appears on the TV. Restart once when it says so.

- **A card set up for a small 3.5-inch screen (LCD-show)** squeezes the TV's picture down to
  480 × 320 to copy it onto the little screen. The installer undoes that: the TV gets its full
  picture back, and the small screen's driver is switched off. The old settings are kept as
  `config.txt.before-sofa-box` on the card's boot partition.
- **A desktop** (Raspberry Pi OS with desktop) is switched off so Sofa can have the screen.
  `sudo sofa-box desktop` brings it back; `sudo sofa-box appliance` gives the screen to Sofa again.
- **An old system** without the `cage` screen program (Raspbian Buster and older) gets a bare X
  screen instead. It works, but the ready-made card is faster and gets updates.

Running the same line again later updates the box.

## Try it on your computer first

You can see the box before there's a Pi: the TV pages as the box shows them (at the TV's size), a
remote, its settings and its boot screen. From the Sofa folder on any computer with Python and
Pillow (`pip3 install pillow`):

```
python3 tools/sofa-box-preview.py
```

It opens the preview in your browser. To use another computer's Sofa, add its address
(`python3 tools/sofa-box-preview.py http://192.168.1.20:8090`). `--slow` makes it behave like a
Pi 3. Videos open in mpv in a window if mpv is installed (on a Mac: `brew install mpv`).

## Using it

### The home screen

Everything starts here. **Home** comes back to it from anywhere: the remote's Home (on many TV
remotes it's the Home or Menu button, sent over HDMI), a controller's Xbox/PS button, **F1** or the
Windows key on a keyboard, or **Home** on the Sofa bar.

- **The top:** the time and the day, a hello, and what to do next: **Resume** what you were watching
  in Sofa (its picture behind), **Open Sofa** and **Live TV**. Beside it, **the weather**: now, the
  next 24 hours' high and low, and the next few hours, for the city of the box's time zone until you
  pick a town in **Settings → Weather on Home** (also °C or °F, or Off).
- **Opening an app** shows its icon while it loads, and the TV switches to it once it's ready
  (not to a blank page). One that's open already comes straight back.
- **Watch:** Sofa, Live TV and your streaming apps, as big cards. **Plugged in:** USB drives and a disc,
  when there's one. **Continue watching** from the Sofa it opens with.
- **Your apps:** everything else. OK opens one. **Menu** on an app moves it, hides it or removes it.
- **Open now:** what's still open (music keeps playing); OK goes back to it, ✕ closes it.
- **Typing** anything on Home searches the web.

### Opening Sofa: where from

<img src="../../docs/images/box-chooser.jpg" alt="Where's your Sofa? Four cards: Sofa at home, Sofa on the internet, This box, Other servers" width="100%">

The first time you open Sofa, the box asks **where's your Sofa?**

- **Sofa at home:** the Sofa Servers the box found on your network, or type an address.
- **Sofa on the internet:** paste a **share link** someone sent you (their public library), or your
  own Sofa's address when it's on the internet. Free public Sofas are listed here too when there are
  any (the list comes from GitHub, so new ones show up by themselves).
- **This box:** no server, and you don't want one? Sofa runs on the box itself. It has **free Live
  TV** straight away, and plays videos on the box (in Videos → Sofa Library) and on USB drives laid
  out as a Sofa Library. It signs itself in.
- **Other servers:** Jellyfin, Emby or Plex. The box finds them on your network, or type the address.
  They open as they are, with the Sofa bar.

Then: **every time**, or **ask me each time**. Settings → Sofa changes that, and lists every server
you've added (open one, make it the one Sofa opens with, or remove it). Inside Sofa, your name →
**Servers** switches too. You stay signed in to each one.

The **Live TV** tile opens Live TV in the Sofa it opens with, or in Sofa on the box. Channels play in the
box's own player: up and down change the channel. Live TV has a tab for each era: **Live now** (today's
channels, from the free channel lists), **2009–2012**, the **2000s**, **90s**, **80s**, **70s**, **60s**,
**50s**, and **Classic Cinema** (classic movies, film noir, westerns, silent films, cartoons, classic TV,
documentaries). The eras are TV as it went out, most of it whole recorded broadcasts with their own
commercials: Kids TV, Saturday Mornings, On Air, Music TV, Commercial Breaks and more (39 channels; the 2000s
on 2 to 10, 2009–2012 on 11 to 14, Classic Cinema on 20 to 28, the 90s from 90, the 80s from 80 and so on).
Each era has a **guide**, as on a TV: up and down go through the channels, OK watches, a channel's number goes
straight to it, and Flip picks one. While a channel plays, its banner says what's on and what's next.

### USB drives and discs

Plug in a USB drive and it's ready in a moment: a toast says so, it shows on Home under **Plugged
in**, and Files lists it. Videos and music play in the box's player; pictures open full screen.

If you use **Sofa on this box** (This box), the drive's shows and movies also join its library by
themselves, with posters and Continue watching: nothing to add in Sofa. Sofa sorts the drive the way
its Inbox sorts, with links on the box, so every show and movie on it is found whatever the folders are
called, and nothing on the drive is moved, renamed or changed
([docs/storage.md](../../docs/storage.md#a-usb-drive-sorted-for-you-sofa-on-a-sofa-box)).

A **DVD, Blu-ray or music CD** in a USB disc drive shows on Home too: OK plays it (DVD menus work with
the arrows and OK). Store-bought DVDs and Blu-rays are usually copy-protected; the box doesn't come
with the extra software some of them need, so those may not play. A Pi 3 may need a powered USB hub
for a disc drive.

### The App Store

<img src="../../docs/images/box-store.jpg" alt="The App Store: Edge Music, The LJ Collection, and the streaming apps" width="70%">

Pick an app and press OK: it's on Home, and it opens full screen with no browser around it. Sign in
the first time, as on any TV. **Any website** at the bottom puts any address on Home. Each app shows
its own icon (the box fetches it from the app's site the first time you open the store).

Apps marked **DRM** (Netflix, Disney+, Prime Video, Max, Spotify…) use copy protection, which the box
has (Widevine). On a Pi 3 their picture may be smaller than on a Fire TV, and a service can refuse
to play in the box's browser; a Pi 4 or 5 does better.

### The browser and the Sofa bar

**Browser** on Home: type an address or a search. On any site, press **Menu** (or move the mouse to
the top edge) for the Sofa bar: **Home**, **Back**, **Reload**, the address, **Add to Home** (the
site becomes an app on Home) and **Close**. Downloads go to **Files → Downloads**.

<img src="../../docs/images/box-bar.jpg" alt="The Sofa bar over a page: Home, Back, Reload, the address, Add to Home, Close" width="70%">

**Sofa Shield** (Settings) keeps ads and trackers out of every app and site on the box, with a list
of known ad and tracking sites that brings itself up to date every week.

### Files and games

<img src="../../docs/images/box-files.jpg" alt="Files: Downloads, Videos, Music, Pictures, and the files in Downloads" width="70%">

**Files** shows Downloads, Videos, Music, Pictures and any USB drive you plug in. OK plays a video or
song in the box's player, or shows a picture; **Menu** renames, moves or deletes.

**Games** is for playing on the TV with a controller:

- **Connect a controller** there (it shows how to put an Xbox, PlayStation, 8BitDo or other controller in
  pairing mode); a USB cable or a controller's own dongle works as soon as it's in. The box knows which
  kind it is and says so.
- **Get more games**: free, open-source games the box installs when you press OK (a few minutes, from
  Debian's archive), then plays **without the internet**: SuperTux (a platformer), Flare (a dark-fantasy
  action RPG), Neverball, Battle for Wesnoth, OpenTTD, two first-person shooters (AssaultCube, and Cube 2:
  Sauerbraten, a 1 GB download), and SuperTuxKart on a Pi 4 or 5. Each says how much room it takes;
  **Remove a game** frees it. On a Pi 3 the shooters draw smaller and the TV scales them up.
- **Sofa Craft** is on every box from the start: an endless world of blocks to explore, mine, build and
  craft in, straight into your world with the controller. It's built on Luanti, the open-source block
  game (with its Minetest Game).
- **Every game works with the controller from the start**, the same on every controller (the buttons go by
  their place: an Xbox controller's A is a PlayStation controller's ✕). Games made for controllers read it
  themselves; for the others the box works the controller for them: the sticks walk, look or move the
  pointer, the buttons are the game's keys and clicks.
- **To come back from a game, hold Home** (the Xbox or PS button, or a remote's Home) for a second.
- **Gloamwell**, the box's own game: a dark-fantasy dungeon crawler. Go down the well under the village of
  Wickhollow as a Warden, an Ashcaller or a Stalker, through six zones of floors (each one made as you go
  down), each with its own creatures and a guardian every fourth floor, and on past the last. Fight with a
  blade and three skills, roll out of the way, spend a talent point each level, and find gear in five
  rarities, sets among them. Back in the village: Hesk's stall, Vesk's forge (better your gear), your
  strongbox, and the notice board's tasks. Make your Wickbearer as you like (name, origin, look); the gear you
  wear shows. Besides fighting: Woodcutting, Mining, Crafting and Hunting (Ysolde's tasks), and mounts to win,
  some that fly. Three Wickbearers can be kept; one from the first Gloamwell moves into the first free one. It plays offline with its own music (quiet unless you turn it up), with the
  controller from the start (the hints show its buttons: A B X Y, or ✕ ○ □ △) or a keyboard.
- **Tidewing**, a race over open water in low-poly 3D: a skimmer through the gates of six courses against three
  rivals, carving to fill your boost. It's built on the box's own game engine (Low3D, `games/low3d.js`), which
  tunes each game to the box: 3D at a size it holds steady on a Pi 3, sharper on a Pi 4 or 5, and the same world
  in 2D on a box without a real GPU. The graphics check (`127.0.0.1:8091/box/games/probe/` in the box's browser)
  shows what it found.
- **Ironmaw**, an old-style shooter in a foundry under the ice: four levels, five weapons, keys, lifts and
  secrets. The left stick moves, the right stick turns, RT fires, LT aims, A opens doors. It's drawn by the
  processor, so it plays on a Pi 3 with or without a GPU, and sharper on a Pi 4 or 5.
- More of the box's own games, each a page that plays offline with the controller: **Cinder Knight** (a
  platformer), **Shadow Heist** (stealth), **Rune Tactics** (turn-based tactics), **Micro Drifters** (top-down
  racing), **Neon Brawler** (a beat 'em up), **Void Drifter** (mining and upgrades in space), **Cosmic Cascade**
  (a falling-gems puzzle), and the small ones, **Neon Dodge**, **Pair Up** and **Sky Hop**.

### Settings and themes

**Settings** on Home has the following.

- The look (**Street**, **Terminal**, **Pirate** or **Sofa**, for the home screen and the boot screen),
  and the box's name.
- **Sofa:** which servers it plays from.
- **Sofa on this box, from anywhere:** opens the box's own Sofa (This box) to the internet, like Sofa
  on any computer: type a free DuckDNS address (and its token) or your own domain, press **Open it to
  the internet**, and the box does every step itself, showing each: the router (UPnP), the
  certificate, letting the internet in, and a check from outside. If the router won't take the
  request, it says which ports to forward to the box. **Make it home only** closes it again
  ([docs/remote-access.md](../../docs/remote-access.md#on-a-sofa-box)).
- **Sofa Shield**, picture and sound, and Wi-Fi.
- **Remotes and Bluetooth:** the phone remote's QR code, and remotes, controllers, speakers and
  headphones.
- **Time zone**, and which apps show on Home.
- **Software:**
  - Which **Sofa Box OS** version it has (also under **About this box**). When a newer one is out,
    it says so here (the box looks on GitHub once a day).
  - **Update the box** gets the newest version from GitHub and restarts by itself (a few minutes).
  - **Reset to how it came** wipes everything of the owner's and starts at the setup again. Your
    apps, sign-ins, Wi-Fi, Bluetooth devices and files all go. Use it before giving or selling a box
    to someone.
- **Help → Send a report:** when something doesn't work (a black screen, a controller that won't
  show), it sends the box's checks and what it has logged since it started to the Sofa Box team, and
  the TV shows the report's number: give it to whoever helps you. No titles, passwords or codes are in
  it ([what's in it](../../docs/privacy.md#on-a-sofa-box)). A box that restarted by itself: send one
  after; it says how the start before ended, and whether the Pi was short of power (a weak power supply
  is the usual reason). When the TV's Settings are out of reach, the phone remote has it too, under
  its buttons: **Something wrong? Send a report**. On a computer: `sudo sofa-box report` shows it.

<img src="../../docs/images/box-themes.jpg" alt="The four themes: Street, Terminal, Pirate and Sofa" width="100%">

The boot screen follows the theme (a new box: Street, the first), with Sofa Box OS's version under the word,
lines ticking by while it starts, and the box's name at the bottom:

<img src="../../docs/images/box-boot.jpg" alt="The four boot screens: SOFA BOX in each theme, OS 1.1.1 under it, and Living room at the bottom" width="100%">

- **Picture:** Automatic, 1080p or 720p. On Automatic the box watches for dropped frames and asks for
  720p by itself if 1080p is too much.
- **Sound:** "TV or soundbar", or "AV receiver" to send surround as it is to a receiver. **Sound at
  start** is the box's few soft notes as it starts; Off leaves them out.

### Keyboard and mouse

A 2.4 GHz keyboard-and-mouse set works as soon as its dongle is in. The arrows, **Enter** (OK) and
**Esc** or **Backspace** (Back) work everywhere; the pointer appears when the mouse moves and hides
when it's still; right-click on an app is its **Menu**.

**The TV's remote:** turn CEC on in the TV's settings. On a Panasonic (like the TC-60AS530U):
**Menu → Setup → VIERA Link Settings → VIERA Link: On**. Samsung calls it Anynet+, LG SimpLink,
Sony Bravia Sync. Then, with the TV showing the box: arrows move, **OK** opens and plays (and
skips an intro when Skip Intro shows), **Return/Back** goes back, ▶ ‖ plays and pauses, ◀◀ ▶▶
skip, the numbers jump through a video (5 = halfway).

**A game controller:** **Settings → Pair a controller**, then put the controller in pairing mode
(Xbox: hold the small pair button on top until the Xbox button flashes fast; PlayStation: hold
Share/Create and PS). A USB cable works without pairing.

| Button | Does |
|---|---|
| D-pad or left stick | move (like a remote's arrows) |
| A (✕ on PlayStation) | OK: open, play, press |
| B (○) or View/Select | Back |
| X (□) | play / pause |
| Y (△) | search; while playing, subtitles |
| Menu/Start (Options on PlayStation) | options: on Home, an app's (move, hide, remove); in an app, the box's bar; while a video plays, its options (subtitles, sound, speed, volume), chosen with the D-pad |
| LB / RB | 10 seconds back / 30 seconds on |
| LT / RT (L2 / R2) | volume down / up (held: on and on); the TV shows it. In the box's own games they're the game's (and so is Start) |
| Xbox / PS button | Home (in a game: hold it for a second to come back) |

A remote's or a keyboard-remote's own volume and mute keys set the box's volume too, as do the phone
remote's. Generic USB controllers (buttons numbered 1 to 12) work too, with the usual layout of those. In a game
from Games, the controller is the game's ([Files and games](#files-and-games)).

## Good to know

**It adapts to the board and the TV by itself.** It checks which Pi it is (3, 4 or 5, or a Compute
Module), how much memory it has, and the TV's picture:

| | Pi 3 B+ / Zero 2 (1 GB or less) | Pi 4 / Pi 5 |
|---|---|---|
| Look | Light: no glows, soft shadows or slide-ins | Full |
| Apps open besides Home | 2 | 3 (2 GB), 4 (4 GB), 6 (8 GB) |
| Video | H.264 on its own decoder; Sofa converts HEVC for it | HEVC as it is |
| Picture | 1080p | 4K when the TV is 4K |

Settings → Picture and sound → **Performance** can say Light or Full instead of Automatic. If 1080p
drops frames, the box asks for 720p by itself.

**Made for small boards.** The box runs well on a Raspberry Pi 3 B+ (1 GB). Whatever's on the TV gets
the box first:

- **Apps behind the one in front are frozen**, so they use no processor. Anything playing music keeps
  playing. Sofa stays awake to hear your phone's **Play on**.
- On 1 GB, two apps stay open besides Home; opening a third closes the oldest one that isn't playing.
- **The screen, the remotes and the video player come first** for the processor and the card. The
  box's own background jobs (finding servers, USB drives, Bluetooth) slow down or wait while a video
  plays. Sofa on the box runs at the lowest priority.
- **The system is kept quiet:**
  - no maintenance jobs while you watch;
  - logs small (24 MB at most) and written to the card every half minute, so a restart doesn't lose
    them;
  - swap is compressed memory, never the card;
  - the processor speeds up as soon as you press something.
- **On a Pi 3, the home screen keeps its look** without the effects that are slow to draw (big glows
  and soft shadows). The browser keeps its cache in memory and fetches nothing in the background.


- **Picture cut off at the edges?** That's the TV zooming in (overscan). On a Panasonic, turn
  **16:9 Overscan** off (Menu → Picture → Screen Settings); other TVs call it "Just Scan",
  "Screen Fit" or "Full Pixel".
- **Keep the TV off the internet.** With a Sofa box the TV needs no Wi-Fi or network cable, so it
  can't report what's on its screen (many smart TVs do, "ACR") or show ads.
- **Something not right?** Over SSH: **`sofa-box doctor`**. It checks the power supply, the
  services, the connection to Sofa, the TV, the video chip, sound and the remotes, and says what
  to do about anything wrong. `sofa-box logs` shows what the box has been saying.
- **What the Pi 3 plays as it is:** H.264 up to 1080p, in MP4 or MKV, with AAC, AC-3 or E-AC-3
  sound. Sofa converts HEVC (x265) and anything bigger than 1080p for it, as it does for any TV.

## What's on the box

| | |
|---|---|
| `sofa-box-agent.service` | the home screen, apps, store, files; finds Sofa; plays videos with mpv; opens apps as tabs of the box's one Chromium (over its DevTools port, `127.0.0.1` only); all on `127.0.0.1:8091`, only for the box itself. For phones on your network: the phone remote on port 8092 (`http://`) and 8093 (`https://`, with the box's certificate), and, only while the box's own setup Wi-Fi is on, its sign-in page on port 80 |
| `sofa-box.service` | the TV's screen: Chromium full screen in `cage` (a screen that shows one window), starting on the home screen |
| `sofa-box-input.service` | game controllers as a remote |
| `sofa-box-cec.service` | the TV remote's buttons over HDMI-CEC |
| `sofa-box-shield.timer` | Sofa Shield's list of ad and tracker sites, brought up to date every week |
| `/usr/local/bin/sofa-box` | `doctor`, `status`, `logs`, `choose`, `pair-controller`, `tv-on`, `shield`, `desktop` |

Installed apps are in `~/.config/sofa-box/apps.json` (their icons next to it); the store's list is
`store.json` in this folder. How it all fits together: [docs/sofa-box-os.md](../../docs/sofa-box-os.md).

The files are in `/usr/local/lib/sofa-box`, the box's settings in `~/.config/sofa-box/settings.json`
of the user it runs as. To remove it all:
`sudo sofa-box shield off`, `sudo systemctl disable --now sofa-box sofa-box-agent sofa-box-input sofa-box-cec sofa-box-shield.timer`, then delete those
files and `/etc/systemd/system/sofa-box*.service`.

## Making the card yourself

The ready-made card is built by GitHub from this folder ([the workflow](../../.github/workflows/sofa-box-image.yml)).
To build one yourself, on Linux:

```
sudo tools/build-sofa-box-image.sh out --sofa http://192.168.1.20:8090
```

`--sofa` builds your Sofa's address in (optional: the box finds Sofa by itself). On a computer that
isn't Arm it needs `qemu-user-static`. The card has Raspberry Pi OS's own `pi` user for SSH (no
password until Raspberry Pi Imager's settings give it a name and password) and `sofabox`, which runs
Sofa on the TV. Each build writes a report of what's on the card next to it.

### Versions

Sofa Box OS has a version number of its own, in [`VERSION`](VERSION) (like `1.0.0`), with what's new in
[`CHANGES.md`](CHANGES.md). The box shows it on its boot screen and in Settings, and the card is named
after it (`sofa-box-os-1.0.0.img.xz`).

- Every change to the box merged into `main` makes a new **newest card**
  ([releases/tag/sofa-box](https://github.com/krintoxi/sofa/releases/tag/sofa-box); its file is always
  `sofa-box.img.xz`, so the link never changes). The new card uploads beside the old one and only then
  takes its place, so the download is never missing.
- The first time `main` has a new number, GitHub also makes the release **Sofa Box OS X.Y.Z** (tag
  `box-os-vX.Y.Z`) with that card and its part of CHANGES.md, and keeps it.
- So a new version is: raise the number in `VERSION` (1.0.1 for fixes, 1.1.0 for something new), add a
  section at the top of `CHANGES.md`, merge.
- Neither release is marked "Latest" on GitHub: that one stays the Fire TV app's, because Sofa
  downloads the app from there.
