# The Sofa box (a Raspberry Pi on the TV)

A Raspberry Pi plugged into the TV that starts straight into Sofa, full screen, every time it's
switched on. No app store, no account, nothing on it but Sofa's TV pages. The TV doesn't need its
own internet at all.

## What you need

- A **Raspberry Pi 4 or 5** (a Pi 3 works, best at 720p), its power supply, a microSD card (16 GB
  or more) and an HDMI cable (micro-HDMI on a Pi 4/5).
- To control it, any of:
  - **the TV's own remote**, through the HDMI cable (HDMI-CEC; Panasonic calls it VIERA Link),
  - **your phone**: in Sofa on the phone, the **Play on** button (the screen icon at the top)
    sends a video to the "Sofa box" and turns the phone into its remote,
  - **a game controller** (Xbox, PlayStation, 8BitDo…), over Bluetooth or a USB cable,
  - a cheap "air mouse" remote with a USB dongle (it acts as a keyboard).

## Setting it up

1. **Make the card.** On a computer, install Raspberry Pi Imager (raspberrypi.com/software), choose
   your Pi, **Raspberry Pi OS Lite (64-bit)**, and the card. Press **Edit settings**: a host name
   (`sofabox`), a user name and password, your Wi-Fi (or use an Ethernet cable: better for video),
   and under Services **Enable SSH**. Write it.
2. **Start the Pi** on the TV (card in, HDMI to the TV, then power). Give it two minutes.
3. **Connect to it** from the Mac's Terminal: `ssh <your user name>@sofabox.local`.
4. **Install** with one line (use your Sofa computer's address; Sofa's Server page shows it under
   **Apps**):

   ```
   curl -fsSL http://192.168.1.20:8090/sofa-box/install.sh | sudo sh -s http://192.168.1.20:8090
   ```

   It takes a few minutes, then Sofa appears on the TV.
5. **Sign in:** the TV shows a code and a QR code. On your phone, open Sofa, press your picture,
   then **Pair a TV**, and type the code (or scan the QR).

From then on the Pi opens Sofa by itself whenever it's switched on. If the Sofa computer is off,
it waits for it. If there's more than one Sofa, it asks once.

## The TV's remote (HDMI-CEC)

Turn CEC on in the TV's settings. On a Panasonic (like the TC-60AS530U): **Menu → Setup → VIERA Link
Settings → VIERA Link: On**. Samsung: Anynet+. LG: SimpLink. Sony: Bravia Sync.

Then, with the TV showing the Pi's input: arrows move, **OK** opens and plays, **Return/Back** goes
back, ▶ ‖ plays and pauses, ◀◀ ▶▶ skip, the numbers jump through a video (5 = halfway), channel
up/down change live TV channels.

`sofa-box tv-on` (over SSH) wakes the TV and switches it to the Pi.

## A game controller

Over SSH: `sofa-box pair-controller`, then put the controller in pairing mode when it says so.
It reconnects by itself afterwards (press its Home/Xbox/PS button). A USB cable works without
pairing.

| Button | Does |
|---|---|
| D-pad or left stick | move (like a remote's arrows) |
| A (✕ on PlayStation) | OK: open, play, press |
| B (○) or View/Select | Back |
| X (□) or Start/Menu | play / pause |
| LB, LT | 10 seconds back |
| RB, RT | 30 seconds on |
| Y (△) | search; while playing, subtitles and sound |

The same works in Sofa on any computer with a controller plugged in.

## Good to know

- **Picture cut off at the edges?** That's the TV zooming in (overscan). On a Panasonic, turn
  **16:9 Overscan** off (Menu → Picture → Screen Settings); other TVs call it "Just Scan",
  "Screen Fit" or "Full Pixel".
- **Keep the TV off the internet.** With a Sofa box, the TV needs no Wi-Fi or network cable: then
  it can't report what's on its screen (many smart TVs do, "ACR"), and it won't update itself.
- **Use another Sofa computer:** `sofa-box choose` over SSH, then pick it on the TV.
- **What's it doing:** `sofa-box status`; the logs: `journalctl -u sofa-box -u sofa-box-finder -u sofa-box-cec -e`.
- **Videos** play as they are when the Pi can (H.264; HEVC on a Pi 4/5 when its browser can),
  and Sofa converts the rest, like for any browser.

## What's on the Pi

| | |
|---|---|
| `sofa-box.service` | Chromium in kiosk mode inside `cage` (a screen that shows one window), on the TV |
| `sofa-box-finder.service` | the start page on `127.0.0.1:8091`: finds Sofa (Bonjour, SSDP, or the address it had) and opens it |
| `sofa-box-cec.service` | turns the TV remote's buttons (HDMI-CEC, via `cec-ctl`) into key presses |
| `/usr/local/bin/sofa-box` | `pair-controller`, `choose`, `tv-on`, `status` |

The files are in `/usr/local/lib/sofa-box`. To remove it all:
`sudo systemctl disable --now sofa-box sofa-box-finder sofa-box-cec`, then delete those files and
`/etc/systemd/system/sofa-box*.service`.
