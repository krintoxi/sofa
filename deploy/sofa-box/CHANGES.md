# Sofa Box OS: what's new

Each version gets its own release on GitHub, "Sofa Box OS X.Y.Z", with its card to download:
<https://github.com/krintoxi/sofa/releases?q=box-os>. The newest card is always at
<https://github.com/krintoxi/sofa/releases/tag/sofa-box>.

A new version: change the number in `deploy/sofa-box/VERSION`, add a section here, and merge to `main`.
GitHub builds the card and makes the release by itself.

## 1.1.23

- **Sofa Craft starts again.** A crash at its first start had left its world without its game, so every start
  after stopped at once ("Game [] could not be found"), with Luanti's own menu to get out of. The box now mends
  the world before each start (its game; its storage only where it's missing), and on a Pi 3 holds it to 30
  frames a second, much lighter. When a game stops as it starts, OK on it tries again.
- **A game gets the box.** When one starts, every page stops (Home too), the apps that aren't Sofa close on a
  1 GB box, and the browser lets go of the memory it can; Home comes back when the game ends.
- **When the box restarts by itself, the next report says why.** Its logs are kept across a restart now (24 MB
  at most; alarms such as "under-voltage" written at once), and a report shows how the start before ended and
  the Pi's own record of its power. The games' log keeps their last few starts, each marked.
- **Short of power, the TV says so** (once): a weak power supply makes a Pi freeze or restart, more so while it
  switches Wi-Fi or plays a game.
- **Retro TV puts the 2000s first** (Sofa 1.2.3), with 00s Kids TV and 00s On Air.

## 1.1.22

- **The setup in two scans.** When your phone gives the box your Wi-Fi, the box also gives it the remote's
  address through the Sofa Box service; once both are back on your Wi-Fi, the Setup Assistant carries on there
  by itself, already the remote: no last code to scan. (A new box makes its own id at its first start, so that
  address is known before it's ever online; the service takes it. Where it can't, the last code is still on
  the TV.)
- **Retro TV.** The App Store has a Retro TV section: Joey Cato's My Retro TVs, a site for each decade from the
  50s to the 2010s, channel-surfing that decade's shows and commercials on an old TV. And Live TV has Sofa's
  own Retro TV channels (Sofa 1.2.2), a decade each, with period commercials between the shows.
- **Fixes from a careful read:** a tap on the phone's touchpad after the pointer has gone to its corner only
  brings it back (it used to press whatever was in the middle of the screen); a video, an app or a game
  starting wakes the box (else the next phone key jumped back to Home); after changing channel in the box's
  player, an archive channel that runs out tunes in again to the channel you were on.
- **Reports say more, and less.** Send a report now lists when the box's player stopped by itself and why, and
  the Bluetooth pairings the box said yes or no to. A looping preview's routine messages are left out (they
  filled the last report), and the same message again is counted, not repeated.

## 1.1.21

- **The setup's phone side is the Sofa Setup Assistant.** The TV's phone panel is "Set up with your phone",
  and each code says what it really does: the first connects your phone to the box (its own Wi-Fi), the second
  opens the Setup Assistant on your phone (not "the remote"), where you choose your Wi-Fi; the last keeps your
  phone as the remote. On the phone, the assistant shows its three steps, and after the Wi-Fi, exactly what
  the last step is.
- **Our games are played with a controller first.** Neon Dodge, Pair Up and Sky Hop read the controller
  straight (the stick too: Sky Hop steers as far as it's pushed), with no wait before a held direction repeats,
  and say its buttons' names (A, or ✕ on a PlayStation controller); keys still work when there's no
  controller. Keys and a mouse stay for the games that have nothing else (Wesnoth, OpenTTD).
- New Sofa Craft worlds keep their mods' data in SQLite too (Luanti's warning about the old way).

## 1.1.20

- **A power button on the phone remote.** It puts the box to rest: what plays stops (its place kept), a game
  ends, and the TV shows the box's screensaver, the time, the weather and the art of what you've been
  watching, crossfading, the clock drifting to a new spot every minute so nothing burns into the TV (still
  pictures on a Pi 3). A touch anywhere on the phone wakes it, and so does any key on a remote or controller.
- **Internet Archive channels in Live TV** (Sofa 1.2.1): classic movies, film noir, westerns, cartoons and
  more, like TV channels, in the box's player; up and down change the channel, the film's name on screen.
- **Sofa looks like a TV app on the box** (Sofa 1.2.1): its menu is a rail down the left edge, opening into
  names when the remote goes into it, with no scroll bars and the row in focus gliding to the middle.

## 1.1.19

- **Xbox controllers pair.** An Xbox Series controller (and others) asks the box to say yes to the pairing;
  nothing on the box answered, so it stopped blinking as if paired and the box said it didn't pair. The box
  now keeps a pairing helper running that says yes while it's looking for devices (and no otherwise), is
  pairable while looking, lets a controller pair again, and loads what Bluetooth LE controllers need.
- **The TV's remote over HDMI (CEC) stops restarting.** Its service needed `ir-keytable`, which the card
  didn't have, so it crashed every few seconds; it's on the card now, and the service runs without it too.
- **Every code on the setup's first screen shows whole.** The remote's code ran under the bar at the
  bottom on a 1080p TV: the steps are one row now, the code fits the screen's height, and there's room
  for TVs that trim their edges.
- **The pointer stays out of the way, and it's the box's own.** It used to sit in the middle of the screen
  from the first start. Now it's somewhere only while the phone's touchpad is used: it starts from the
  middle, moves with the box's own acceleration (precise when slow, across the TV when quick), goes to a
  corner after a few seconds, and hides at once when a remote key is pressed. It's white with a pink glow,
  pink over what can be pressed. The phone's touchpad shows where your finger is.
- **Live TV in the box's player.** Channels play on the Pi's video chip, with "Tuning in to…"; up and down
  (or Page Up/Down) change the channel, with its name on the screen.
- **Sofa on this box is Sofa 1.2.0**, the version number catching up with everything since 1.1.0 (what's in
  it: [CHANGES.md](../../CHANGES.md)). Its Server → Updates says which commit runs and when it was made.

## 1.1.18

- **The setup is shorter and goes on by itself.** Once your phone is the remote on your Wi-Fi (the four
  codes on Hello), the TV moves on to **Your box** by itself, and joining Wi-Fi at the Internet step
  does the same. No asking for the Wi-Fi again, and no Bluetooth step: speakers, headphones and more
  controllers wait for **Settings → Remotes and Bluetooth** or **Games**, and the end of the setup says
  so. **Start**, **Next** and **Back** stay at the bottom of the screen, never below its edge.
- **Sofa Craft is on every box.** An endless world of blocks to explore, mine, build and craft in,
  first in Games, with its own picture, straight into your world with the controller. It's Luanti, the
  open-source block game, on the card from the start (a box that updates gets it too).

## 1.1.17

- **Gloamwell, the box's own game** (Games → On the box): an action-RPG dungeon crawler, made for the TV and
  the controller. The Great Wick at the bottom of Wickhollow's well has gone out; go down and find out why.
  - Three to play: the **Warden** (shield and blade), the **Ashcaller** (fire from the well) and the
    **Stalker** (knives from the dark), each with an attack, a roll and two skills.
  - Every floor is new each time you go down: rooms, monsters that get stronger the deeper you are, urns and
    chests, torches and a brazier to light. Four places below, each with its own creatures, and a guardian on
    every fourth floor who seals the stair down. Past the sixteenth, the floors go on.
  - Gold, tonics and gear: weapons, armor and charms, plain to relic, with their own powers. Hesk's stall in
    the village buys and sells; the shrine mends you; the rope (or Homeward Ash) brings you back up, and the
    well takes you straight to the deepest floor you've reached.
  - Played with any controller from the start, the hints showing its own buttons (A B X Y, or ✕ ○ □ △ on a
    PlayStation one); a keyboard works too. It's drawn in pixel art at a small size and scaled up, so it runs
    smoothly on a Pi 3, and needs no internet. Your Wickbearer is kept on the box: Continue picks up where you
    left. Hold Home to leave, as in any game.

## 1.1.16

- **Games is a games mode.** Free, open-source games that run on the box itself, installed from Games →
  **Get more games** with one press (a few minutes) and played full screen, **offline**: SuperTux, Flare (a
  dark-fantasy action RPG), Luanti (an open block world: it starts straight in your world), Neverball,
  Battle for Wesnoth, OpenTTD, and SuperTuxKart on a Pi 4 or 5. Each shows the room it takes, and the box
  checks there's room first; **Remove a game** takes it off again.
- **Controllers, recognised.** Games asks for a controller when none is connected, with how to pair an Xbox,
  PlayStation, 8BitDo or other one, and shows which kind is connected; a toast says so when one turns on.
  Generic USB controllers (buttons numbered 1 to 12) work now too, on the box's pages as well.
- **Every game works with the controller from the start, the same on every controller.** Games made for
  controllers read it themselves. For the others, the box works it for them, by the buttons' places (an
  Xbox controller's A is a PlayStation controller's ✕): the sticks walk, look around or move the pointer,
  the triggers click, the buttons are the game's keys (Luanti: jump, inventory, dig and place; Wesnoth: click,
  end the turn).
- **Hold Home for a second to come back from a game** (the Xbox or PS button, or a remote's Home).
- The card has XWayland, for games made for X; when a game stops as it starts, **Send a report** includes
  what it said.

## 1.1.15

- **USB drives are sorted like the Inbox sorts, without touching them.** Plug a drive into the box and Sofa
  on the box finds every show and movie on it, whatever its folders are called: episodes named like
  `Show.S01E02` anywhere on it join their show, folders like Movies, TV or Downloads are looked inside, and
  anything it can't identify still shows, named after the file. It's done with links in a folder on the
  box, named as the Inbox names things: nothing on the drive is moved, renamed, converted or deleted, and
  its posters stay on the box. Only what changed on the drive is looked at again; something removed drops
  out with its posters. Drives the box already had are sorted this way by themselves.
- **Episodes named with initials** (`BB.S01E01` in a `Breaking Bad` folder) join the folder's show, on drives
  and in the Inbox (they used to make a show called "BB").
- **Sofa on this box, from anywhere** (Settings): the box's own Sofa opens to the internet from the TV, like
  Sofa on any computer: a DuckDNS address or your own domain, the router asked to send the ports, a Let's
  Encrypt certificate, the internet let in, and a check from outside, each step on screen. A box that's
  open starts its Sofa when it starts. **Make it home only** closes it.
- **Sofa, open to the world:**
  - A DuckDNS address gets its certificate over DNS (DuckDNS's check record), so only port 443 needs
    opening; many internet providers block port 80.
  - **Check from outside** (Server → Internet) asks the Sofa Box service whether your address answers with
    Sofa from the internet, and says what's wrong when it doesn't (no DNS record yet, a home address,
    nothing answering, a wrong certificate, something that isn't Sofa).
  - It warns when the internet provider shares one address between homes (carrier-grade NAT) or there's a
    second router in front: no port can be opened then, and a VPN like Tailscale is the way in.
  - The guide, [docs/remote-access.md](../../docs/remote-access.md), is new: each step, the ports to
    forward, and what to do when the router or the provider is in the way.

## 1.1.14

- **The secure phone remote goes through the Sofa Box service's relay.** The QR code to keep the remote is
  `https://boxcert.edgeventure.uk/r/<box>/…`: a secure address every phone opens, at home or away. The box
  keeps a connection open to the service, and the phone's taps reach the box through it. It replaces a name
  and a Let's Encrypt certificate for every box, which had limits (50 new boxes a week for all of
  edgeventure.uk) and didn't work behind routers that block names pointing at home addresses.
  - The phone still needs the TV's code: through the relay, only the QR code's long one (24 characters);
    typing the four digits works at home only, so they can't be guessed at from the internet.
  - The remote's page comes from the service, not from boxes, and each phone's sign-in is kept to its box:
    one box can't reach another through the shared address.
  - Nothing is kept by the service; Settings → Remotes and Bluetooth switches it off.
- The phone remote page uses relative addresses (the same page at home and through the relay), and says
  "Can't reach the box" when the relay says the box is offline (not "type the code").

## 1.1.13

- **The setup's apps step is short.** Eight apps most people use (Netflix, YouTube, Prime Video, Disney+, Max,
  Hulu, Apple TV+, Spotify), all on one screen, no scrolling; the App Store has the rest. "Add N and finish"
  counts only the ones that aren't on Home yet.
- **Home scrolls like a TV's home screen.** Down brings the next row up under the top bar, title and all, the
  same place every time (it used to stop wherever the tile just fitted, often under the hints at the bottom);
  along a row, the next tile peeks in; Up goes back row by row (it used to jump to the top bar), and the top
  bar only from the first row. Smooth on every board, a Pi 3 too: the scrolling is the graphics chip's work.
- **Apps are easier with a remote.** On sites made for a mouse, the arrows move between links and buttons (the
  browser's spatial navigation), with a ring showing where you are, even on sites that hide it. Pages that
  scroll do so smoothly. Sofa's pages on the box scroll smoothly too.
- **Sharper app icons.** The box looks harder for each app's own icon (where sites keep one without saying),
  measures what it finds and keeps the sharpest; YouTube, Netflix, Spotify and Prime Video get their official
  ones. Icons have a soft shine and edge, and the one in focus lifts. Boxes fetch their apps' icons again once.
  (Fetching icons also no longer stops for good at the first site that hangs up part way.)

## 1.1.12

From setting up 1.1.11:

- **No "no network, making its own Wi-Fi" just after your phone gives the box your Wi-Fi.** Between its own
  Wi-Fi and yours the box has no address for a moment, and the TV took that for a box with no network yet.
  It now says what's happening: joining your Wi-Fi, then "Connected to … Getting the box's address there",
  then the code for the remote; or, if joining didn't work, why, and that its own Wi-Fi is coming back.
- **Fewer blank moments while the box starts.** The boot screen used to go before the box's helper was ready,
  leaving a still or black screen while the browser waited for it (long on a first start). It now stays,
  moving, until the helper answers (a minute at most), and Home follows at once. Home is dark from its very
  first frame, not blank while it loads.

## 1.1.11

- **Resuming no longer sits on a blank black screen.** When you resume something Sofa converts for the box, it
  first converts from where you left off, which can take a while; the box's player showed black meanwhile, as
  if it had hung. Its screen now says "Resuming … at 23:14", then that Sofa is getting it ready, and after 25
  seconds that Back stops it; the words go as soon as the picture moves.
- **When the box's player can't start a video, the page's own player now gets one it can play.** It used to
  ask Sofa for what the box's player plays (MKV, surround sound), which the browser can't: another black
  screen. Trailers on Sofa's pages on the box had the same problem.

## 1.1.10

- **USB drives join Sofa on the box by themselves.** Plug a drive in and, if you use Sofa on this box (This
  box), its shows and movies are in Sofa within moments, with posters and Continue watching: nothing to add
  by hand. Sofa reads the drive as it is: show folders and episodes named like `Show.S01E02` are shows (a
  "TV" or "Shows" folder holds shows), the rest are movies, loose or in folders. Nothing on the drive is
  moved or renamed; Adult and XXX folders are left out. Unplugged, its titles drop out until it's back, with
  everyone's progress kept. Server → Storage shows it as "USB, as it is"; Stop using keeps it out.

## 1.1.9

A look through every part of the box:

- **Bluetooth at the setup.** Remotes and controllers didn't show up. Every two seconds the box asked about each
  device near it one by one (a process each: dozens in a busy room, too much for a Pi 3); it now asks
  bluetoothd once for all of them. Bluetooth is switched on (unblocked) at every start, as Wi-Fi already
  was, and a device that only says what it is in its Bluetooth LE "appearance" (a remote control, a gamepad)
  is recognised by that too.
- **Quicker starts.** cloud-init (which applies Raspberry Pi Imager's settings) ran its five steps at every
  start, on a Pi 3 at the same time as the browser starting; it now switches itself off after the first.
- **Less work in the background.** The box looked for USB drives and discs by running lsblk every four
  seconds, all day; it now reads two small files and runs it only when something's plugged in or out.
- **The setup's first step fits on the TV.** The QR code and what to do sit side by side, and the whole step
  shows without scrolling (the title was cut off at the top). The setup's layout also no longer leaked onto
  the rest of the page.
- **Games show their names** (the tiles only had room for the line about them).
- **Apps whose icon is empty or white show properly.** An icon with nothing in it (some sites have one) shows
  the app's first letter on its colour; a white logo on clear gets the app's colour behind it, not white.

## 1.1.8

- **A new Home.** At the top: the time, big, the day, a hello, and what to do next (Resume what you
  were watching, with its picture behind; Open Sofa; Live TV). Beside it, **the weather**: now, the
  high and low for the next 24 hours, and the next few hours, drawn in the box's look. It's for the
  city of the box's time zone until you pick a town (Settings → Weather on Home, where °C or °F and
  Off are too). From MET Norway, Norway's weather service: free, no account, asked every half hour.
- **No blank page when an app opens.** The TV used to switch to a new app's empty page while it
  loaded. Now the app loads behind Home, which shows its icon ("Opening YouTube…"), and the TV
  switches once the app has something to show (8 seconds at most). An app that's open already comes
  straight back.
- **The first start says it's the slow one.** A new card's boot screen says the first start takes a
  few minutes and that the box may restart once by itself: just wait. Only on that start.
- Home starts with the pointer hidden (it shows when a mouse or the phone's touchpad moves it).

## 1.1.7

- **Send a report.** Settings → Help → **Send a report** (or, on the phone remote, **Something wrong?
  Send a report** under the buttons, for when the TV's menus are out of reach) sends the Sofa Box team
  what the box checks and has logged since it started, and the TV shows the report's number. In it:
  the version, board and settings, the network, Wi-Fi, Bluetooth and phone remotes, where the player
  was (not what it played), the errors of the pages open on it, and what their video players said:
  which decoder plays (the Pi's own or the processor) and why one stopped. Web addresses are cut to
  their site, files on drives to the drive, and passwords blanked: no titles, codes or passwords. It
  goes only when you press it, twice. Send it before restarting the box: a restart clears the logs.
- **Sofa on the box starts in the box's own theme.** The Sofa App has the Street theme now, and starts
  with it everywhere (a server's owner can still pick another for everyone, and each screen its own);
  on a Sofa box, it takes the box's theme.

## 1.1.6

From setting up 1.1.5 on a Pi 3:

- **The phone remote's volume buttons work.** They used a tool the box doesn't have (`pactl`); they use
  PipeWire's own (`wpctl`) now.
- **YouTube plays more smoothly on a Pi 3.** Its video chip plays H.264 only; YouTube sent VP9 or AV1, which its
  processor had to decode. On a Pi 3 (or older), pages are told those two can't play, so sites send H.264. A
  Pi 4 or 5 is left to choose.
- **The setup doesn't show the Wi-Fi step once the box is online** (your phone gave it your Wi-Fi, or a cable):
  Start goes on to Bluetooth.
- **On the box's own Wi-Fi, the phone page only sets up the Wi-Fi:** no remote tabs, and no "Add to Home
  Screen" (that page stops working once the box joins yours). The full remote, and the tip, come with the
  last code.
- **After joining your Wi-Fi, the TV waits for the box's secure address** (up to three minutes) instead of
  showing the plain one first. If getting it fails just after joining, the box tries again in 30 seconds, not
  an hour later. Where only the plain address works, the TV says how to let an iPhone open it.

## 1.1.5

- **Joining your Wi-Fi at the setup no longer loops back to "connecting".** To join your Wi-Fi, the box
  switches its own off and looks for yours. Meanwhile its 10-second network check saw a box with no Wi-Fi
  that had been "offline" for minutes, and brought the box's own Wi-Fi straight back, in the middle of the
  join, every time. It now leaves the Wi-Fi alone while a join is going on (and only one join runs at once),
  and brings its own Wi-Fi back only if the join didn't work.
- **The setup shows one code at a time, and says what it's waiting for.** Four steps on the TV, the one in
  front highlighted and the done ones ticked: join the box's Wi-Fi, open the remote, give the box your
  Wi-Fi, keep the remote. Each step shows only its own code, and goes by itself once it's done: the Wi-Fi
  code as soon as a phone joins the box's Wi-Fi, the remote's code as soon as the remote is open on it.
  Under each: "Waiting for your phone to join…", "Waiting for the remote to open on your phone…",
  "Waiting for your Wi-Fi details…", "The box is joining …: looking for it, then connecting". "Show the
  code again" buttons bring a code back. (Before, two codes sat side by side, hard to scan, and the second
  said "Didn't open? Scan this", as if phones opened the remote by themselves after the first; many don't.)
- **A sound when the box starts:** four soft notes with the opening. Settings → Picture and sound → Sound
  at start switches it off.

## 1.1.4

- **Apps fill the TV.** YouTube and other apps opened as a small square in the top-left corner of the TV. The
  box drew them at half size with doubled pixels, to look bigger from the sofa; on the Pi the doubling didn't
  take, which left a quarter of the screen. Apps now get the whole TV at its own resolution, like on any
  computer (ordinary websites look a little smaller; apps made for TVs are made for exactly that).

Still being looked into on a real box: the iPhone's sign-in sheet not opening by itself, and Bluetooth remotes
and controllers not showing up.

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
