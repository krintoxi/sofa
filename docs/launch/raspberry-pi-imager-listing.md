# Sofa Box OS in Raspberry Pi Imager's own list: the request (draft)

A draft for the owner to send. **Nothing has been sent.** Raspberry Pi takes requests through one form, "Request an
addition to the Raspberry Pi Imager OS List" (https://forms.gle/U6JkxVfhHkn5ok2X7), linked from Imager's own
documentation (`doc/schema-notes.md` in `raspberrypi/rpi-imager`, "Requesting an addition to the official Raspberry
Pi Imager OS List"). What they ask for, and how Sofa Box OS meets each point, is in
[raspberry-pi-imager.md](../raspberry-pi-imager.md#raspberry-pis-own-list). Everything below was read on
2026-11-18.

Raspberry Pi reviews the request against two "listing prerequisites" (a named point of contact, ideally two, and
correct device annotations) and replies by e-mail. Their news post on the list says the team will "verify its
compatibility" before it goes in.

## Before it goes in, in this order

1. **Merge the pull request that adds this file.** The list's workflow then publishes the sublist (below) at its
   address, and the 40 px icon goes live at its address on `main`. Neither exists before the merge.
2. **Open both addresses** and check they answer: the sublist, and the icon.
3. **Try it in Raspberry Pi Imager**, the way everyone would see it. The preview list in this folder,
   `sofa-box-imager-preview.rpi-imager-manifest`, is laid out like Raspberry Pi's: their boards, then **Media player
   OS → Sofa Box OS**, which reads the published sublist. Open it with this link (Imager 2.0 or newer asks "Switch
   to a custom repository?"), or download the file and double-click it:

       rpi-imager://open?repo=https://raw.githubusercontent.com/krintoxi/sofa/main/docs/launch/sofa-box-imager-preview.rpi-imager-manifest

   Choose **Raspberry Pi 3**, then **Media player OS → Sofa Box OS → Sofa Box OS 1.1.86**, write a card, and start the
   Pi 3 B+ from it. Imager checks every byte it writes against the list; a card that boots to the setup is the test.
   Their notes also ask for "multiple Imager versions": Imager 1.8 and 1.9 take a list with `--repo` (the command is
   in [raspberry-pi-imager.md](../raspberry-pi-imager.md#opening-it-imager-20-or-newer-on-a-mac-or-windows)).
   The link, `--repo` with this file, and the sublist's address (a redirect from github.com to GitHub's download
   host, which Imager follows) have been read in Imager's code, not tried in a real Imager.
4. **Decide the open points** at the end of this page.
5. **Send the form**, with the answers below.

## The answers, in the form's order

| Question | Answer |
|---|---|
| Email | The owner's own address: Raspberry Pi replies there, and sends a copy of the answers. |
| What is the name of the OS you want to add? | `Sofa Box OS` |
| What Category should your OS be added to? | `Media player OS` |
| What is the website for your OS? | `https://github.com/krintoxi/sofa` |
| What is the icon URL for your OS? (40x40px PNG or SVG) | `https://raw.githubusercontent.com/krintoxi/sofa/main/docs/images/sofa-box-os-icon-40.png` |
| What is the description of your OS? | `Your own TV box: Sofa, free Live TV, your streaming apps and games, set up from your phone.` |
| What is the URL of your subitem JSON file? | `https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box-imager-sublist.json` |
| Does your OS come with a default password? | **Other**, with the text below |
| Does your OS come with an unattended update mechanism? | **Other**, with the text below (or one of their answers, if the box changes first: see the open points) |
| Point of contact 1 name | A person's own name: the form says "This should be a shipping name of an individual. Mailing list IDs will not be accepted." |
| Point of contact 1 e-mail | That person's address. |
| Point of contact 2 name and e-mail | Optional: "ideally two". |

With "Other", Raspberry Pi says it will write within 20 UK working days to discuss it. The texts below are ready for
that reply.

### No default password

None of the form's four answers is true of the card: it has no default password, it doesn't rely on Imager for one
(the list gives Imager nothing to customise), and it does use the network. So "Other", and this. The accounts and
SSH were read from the 1.1.86 card itself on 2026-11-18:

> Sofa Box OS has no default password, and no account anyone can sign in with. Root, Raspberry Pi OS's first user
> and the box's own user are all locked, and SSH is off. Imager writes nothing to the card (init_format "none"): the
> box sets itself up on the TV, with a phone. What the box opens on the home network is guarded by secrets each box
> makes for itself: the phone remote pairs with a one-time code shown on the TV (from outside the home, eight
> letters, and typing pauses after ten wrong tries); the box's own Wi-Fi during setup has a random eight-digit
> password shown on the TV; and Sofa on the box gets a random password of its own. Reports go to the repository's
> private vulnerability reporting, or hello@edgeventure.uk.

### Updates

Today the honest answer is "Other", and this:

> Updates come from our GitHub releases, through the box's own Settings → Software. The default channel only
> installs versions that have passed on a real box. Installing a new version also brings the packages the box
> installs up to their newest in Raspberry Pi OS's archive (the browser, the player, the network manager, Bluetooth,
> sudo, curl and the rest). Updating weekly by itself is a switch, off unless the owner turns it on. The rest of
> Raspberry Pi OS (the kernel and the base system) is brought up to date by writing a new card.

If the box first gets Raspberry Pi OS's own security updates and weekly updates on by default (see the open points),
the answer becomes "Yes, via an established OS package repository (eg, Debian, Ubuntu, Fedora)", and this text is
rewritten to match.

## The JSON

### The entry Raspberry Pi adds to their list

They make it from the form's answers, under **Media player OS**, beside LibreELEC, OSMC and the others. This is
the form's answers in their list's format, as the preview has it. The list Imager downloads from Raspberry Pi
(`os_list_imagingutility_v4.json`) has no `subitems_url` at all on 2026-11-18: each vendor's sublist is read on
their side and its entries copied in. So what everyone sees is our sublist as it was the last time they read it,
and three vendors' entries in it are empty groups that day (Batocera.linux, IPFire and one signage player). How
often they read it, and how their reader takes GitHub's redirect, are questions for their reply.

```json
{
  "name": "Sofa Box OS",
  "description": "Your own TV box: Sofa, free Live TV, your streaming apps and games, set up from your phone.",
  "icon": "https://raw.githubusercontent.com/krintoxi/sofa/main/docs/images/sofa-box-os-icon-40.png",
  "website": "https://github.com/krintoxi/sofa",
  "subitems_url": "https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box-imager-sublist.json"
}
```

### The sublist it reads, as it is with Sofa Box OS 1.1.86

`tools/sofa-box-imager-list.py build --sublist` makes it from the releases, and the list's workflow puts it up
again whenever another version is marked stable. It holds only the stable card, at its own numbered address,
whose file never changes. It never holds the testing version, the newest build or a PC's image. Its `os_list`
stands alone: the boards are Raspberry Pi's. The sizes and SHA-256s are the card's own; the packed one is GitHub's
digest of the file, and the stable mark names the same one.

```json
{
  "os_list": [
    {
      "name": "Sofa Box OS 1.1.86",
      "description": "Your own TV box: Sofa, free Live TV, your streaming apps and games. For a Raspberry Pi 3 B+, 4 or 5, built on Raspberry Pi OS Lite (64-bit). The stable version, tried on a real box.",
      "icon": "https://raw.githubusercontent.com/krintoxi/sofa/main/docs/images/sofa-box-os-icon-40.png",
      "url": "https://github.com/krintoxi/sofa/releases/download/box-os-v1.1.86/sofa-box-os-1.1.86.img.xz",
      "extract_size": 5226102784,
      "extract_sha256": "a819a87637854e993c7135fe7c154f764612981a5d4fd05f1424d03c92a5b29f",
      "image_download_size": 1380899568,
      "release_date": "2026-11-14",
      "init_format": "none",
      "devices": [
        "pi5-64bit",
        "pi4-64bit",
        "pi3-64bit"
      ],
      "architecture": "armv8",
      "website": "https://github.com/krintoxi/sofa/releases/tag/box-os-v1.1.86",
      "image_download_sha256": "fa101d8092e6f2b775d802c0969ee8417c828971571e17ff622ce02376ee4825",
      "capabilities": []
    }
  ]
}
```

### The same with the Pi 3 alone

If the owner lists only the board the card has run on (an open point below), the sublist names only
`pi3-64bit`. The workflow's build line takes `--boards pi3-64bit` for that:

```json
{
  "os_list": [
    {
      "name": "Sofa Box OS 1.1.86",
      "description": "Your own TV box: Sofa, free Live TV, your streaming apps and games. For a Raspberry Pi 3 B+, built on Raspberry Pi OS Lite (64-bit). The stable version, tried on a real box.",
      "icon": "https://raw.githubusercontent.com/krintoxi/sofa/main/docs/images/sofa-box-os-icon-40.png",
      "url": "https://github.com/krintoxi/sofa/releases/download/box-os-v1.1.86/sofa-box-os-1.1.86.img.xz",
      "extract_size": 5226102784,
      "extract_sha256": "a819a87637854e993c7135fe7c154f764612981a5d4fd05f1424d03c92a5b29f",
      "image_download_size": 1380899568,
      "release_date": "2026-11-14",
      "init_format": "none",
      "devices": [
        "pi3-64bit"
      ],
      "architecture": "armv8",
      "website": "https://github.com/krintoxi/sofa/releases/tag/box-os-v1.1.86",
      "image_download_sha256": "fa101d8092e6f2b775d802c0969ee8417c828971571e17ff622ce02376ee4825",
      "capabilities": []
    }
  ]
}
```

## Open points for the owner

1. **Who the contacts are.** One person's name and e-mail at least, two ideally. The form turns down mailing
   lists, so `hello@edgeventure.uk` alone isn't enough.
2. **Which boards.** Raspberry Pi's tags don't name boards one by one:
   - `pi3-64bit` is their "Raspberry Pi 3" (Model A+, B, B+ and Compute Module 3 / 3+) **and the Zero 2 W**, which
     has 512 MB;
   - `pi4-64bit` is the Pi 4, the 400 and Compute Module 4;
   - `pi5-64bit` is the Pi 5, the 500 and Compute Module 5.

   The card has only run on a Pi 3 B+. Three boards (as our own list has them) or the Pi 3 alone, with the Zero 2 W
   and the 3 A+ offered it either way.
3. **The updates answer.** Change the box first, or send "Other" with the text above. The change is in the
   pull request's notes: Raspberry Pi OS's security updates installed by the box, at a time nobody is watching, and
   weekly updates on by default. Weekly updates being off was the owner's own choice.
4. **How long a version gets fixes.** `SECURITY.md` says only the newest version gets fixes. The form doesn't ask
   for a support period. The UK's rules for connected products sold to consumers do, so it is needed before boxes
   are sold there.
5. **The category and the website.** `Media player OS` fits best. The website can be edgeventure.uk's Sofa page
   instead of the repository.
6. **Widevine on the card.** The card carries Raspberry Pi's `libwidevinecdm0` (Google's DRM module, for the
   streaming apps), installed from Raspberry Pi's archive. Its package has no licence file, and the box's credits
   call it "Google's own, passed on by Raspberry Pi". The form doesn't ask, but a listed card is passed on to
   everyone. Whether a card of ours may pass it on is a question for a lawyer, or for Raspberry Pi when they write.

Raspberry Pi is a trademark of Raspberry Pi Ltd. Sofa Box OS is made by EdgeVenture for Raspberry Pi computers; it
isn't made or endorsed by Raspberry Pi Ltd.
