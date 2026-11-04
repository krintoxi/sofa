# Watching away from home

Out of the box Sofa answers only devices on your home network, on this computer, and on Tailscale. Anything
from the wider internet gets "home network only". That's the safe default. There are three ways out, and
you can use more than one:

| | What it is | Good for |
|---|---|---|
| **1. Open to the world** | Your own address (`https://sofa.example.com`, or a free `https://yourname.duckdns.org`), like Jellyfin or Plex: a port on your router, HTTPS, and everyone signs in | Family and friends anywhere, any device, nothing to install |
| **2. A private VPN** | Your own devices join your home network privately (Tailscale, WireGuard) | Just you; nothing exposed at all |
| **3. Cloudflare Tunnel** | No open port: Cloudflare carries it | The web app and the Server page, not watching (see below) |

On a **Sofa Box**, its own Sofa (This box) opens to the world from the TV: [Sofa Box](#on-a-sofa-box).

## 1. Open Sofa to the world

Everything below is built in: **Server → Internet**, five steps on one page. Here's what each step does,
and what to do when one doesn't work.

### Step 1: encryption

Choose **Free certificate from Let's Encrypt**. Over the internet, Sofa answers **only over HTTPS**: a
password never travels in the clear, so there's no "plain http on my IP" mode (that's how other servers
leak accounts).

### Step 2: your address

HTTPS needs a name; a certificate can't be made for a bare IP address that changes. Two ways:

- **A free name from DuckDNS** (one minute): sign in at [duckdns.org](https://www.duckdns.org) (with
  Google, GitHub and others), make a name, copy the **token** it shows, then type `yourname.duckdns.org` and
  paste the token in Sofa. Sofa keeps the name pointing at your home every 10 minutes, so a home address that
  changes is fine. **A DuckDNS name gets its certificate over DNS**: only port 443 needs opening (many
  internet providers block port 80).
- **A domain you own** (`sofa.example.com`): add an **A record** pointing at your home's internet address
  (Sofa shows it under step 3; "what's my IP" sites too). With Cloudflare as your DNS, make it **DNS only**
  (the grey cloud), never proxied (the orange cloud): see [Cloudflare and video](#3-cloudflare-tunnel-and-the-orange-cloud).
  If your home address changes, use a DuckDNS name instead, or your DNS provider's own updater.

Only have an IP address and no name? Use DuckDNS: it's free and gives you a name for that IP. (Sofa's own
certificate, step 1's second choice, works on an IP at home, but every browser warns about it, and Sofa
doesn't accept the internet with it.)

### Step 3: the router

The internet reaches your home at the router, which has to send ports to the Sofa computer:

| On the router (outside) | To the Sofa computer | What for |
|---|---|---|
| **443** (TCP) | Sofa's HTTPS port, **8443** | Everything: the app, watching |
| **80** (TCP) | Sofa's port, **8090** | Let's Encrypt's check for your own domain (not needed for DuckDNS), and sending `http://` visitors on to `https://` |

Switch on **Ask the router to do it**: most home routers do it by themselves when **UPnP** is on in their
settings (Sofa asks again every few hours, as routers forget). Otherwise, set them by hand: in the router's
page (often `192.168.1.1` or `192.168.0.1`), look for **Port forwarding**, **Virtual server**, **NAT** or
**Applications and gaming**, and add the two lines above with the Sofa computer's home address (Server →
Internet shows it). Give the Sofa computer a fixed address there too (**DHCP reservation**), so the
forward still points at it after a restart.

**When it doesn't work** (press **Check from outside**, step 5, to see which):

- **"Your internet provider shares one address between homes"** (carrier-grade NAT, common with mobile,
  satellite and some fibre and cable providers): no port can be opened from your side. Ask the provider for
  a **public IPv4 address** (often free, sometimes a small fee), or use Tailscale (way 2).
- **Two routers** (the provider's box in front of yours): put the provider's box in **bridge mode** (or "modem
  only"), or forward the ports on both.
- **Port 443 blocked by the provider:** forward another outside port (say **8443 → 8443**) and use
  `https://yourname.duckdns.org:8443`.
- **Port 80 blocked:** use a DuckDNS name (its certificate comes over DNS).
- **It works from outside but not from home:** the router doesn't do "NAT loopback" (hairpinning). At home,
  use Sofa's home address as before; the internet address works everywhere else.

### Step 4: the certificate

Press **Get the certificate**. Let's Encrypt checks the address is yours (over port 80 for your own domain,
over DNS for DuckDNS) and gives Sofa a certificate for 90 days. Sofa renews it by itself a month before
it ends.

### Step 5: let the internet in, and check from outside

Switch on **Accept connections from the internet**, then press **Check from outside**. That asks the Sofa
Box service (out on the internet) two things: what your home's address is, as the internet sees it, and
whether `https://your-address` answers with Sofa. It sends only your address, and only when you press it.
It also tells you when your provider shares one address between homes (above).

### What Sofa does when it's open to the world

- answers the internet **only over HTTPS**; `http://` visitors are sent to `https://` (and browsers are told
  to always use HTTPS);
- every request from the internet must be signed in, and new passwords need 12 characters;
- wrong passwords and PINs are limited: 8 from one address, and 20 at one account from anywhere, in 15
  minutes (remembered across restarts);
- the Server page and all admin changes refuse internet connections: manage it from home or over a VPN;
- pairing TVs, guests, TV sharing (DLNA) and artwork without signing in stay home-network only;
- requests that come from other websites are refused; connections are capped (256 at once, 48 from one
  address); sign-in cookies are Secure and HttpOnly; pages can't be framed by other sites.

**Family and friends making their own accounts:** in **Server → People**, switch on **Let people ask for an
account**. The sign-in page then has **Create an account**: they choose their own name and password and say
who they are. Nobody gets in until you **Let in** (or **Let in as Kids**, or **Turn down**).

### On a Sofa Box

A Sofa Box runs its own Sofa (**This box**: free Live TV and the USB drives plugged into it). To open it to
the world: **Settings → Sofa on this box, from anywhere**. Type the address (a DuckDNS name and its token,
or your own domain), press **Open it to the internet**, and the box does steps 1 to 5 by itself, showing
each: the address, the router (UPnP), the certificate, the internet let in, and the check from outside. If
the router doesn't take the request, the TV says exactly which ports to forward to the box. A box that's
open starts its Sofa when it starts, so it stays reachable; **Make it home only** closes it again.

The box's phone remote is separate: it already works from anywhere through the Sofa Box service's relay,
with nothing to open (see the Sofa Box README).

## 2. A private VPN

Your phone or laptop joins your home network privately; nothing is exposed to the internet, and Sofa needs
no changes.

- **Tailscale** (free for personal use): install it on the Sofa computer and on your devices, then open
  `http://<sofa's tailscale address>:8090`. The Server page lists the address. Works even when your provider
  shares one address between homes.
- **Headscale**: a self-hosted Tailscale control server, if you'd rather not use Tailscale's.
- **WireGuard on your router**: many routers (UniFi, Fritz!Box, OpenWrt, GL.iNet) can run a WireGuard server;
  connect to it and use Sofa's home address.

You still sign in to Sofa as usual.

## 3. Cloudflare Tunnel, and the orange cloud

No open ports: `cloudflared` connects out to Cloudflare, which serves your hostname. It's fine for the web
app and the Server page (with Cloudflare Access for an extra sign-in). **Not for watching:** Cloudflare's
terms let only its paid services (Stream and the like) carry video and other large files, so streaming
through a free tunnel, or through a name with the orange cloud (proxied), risks being slowed down or the
account flagged; uploads through it stop at 100 MB. A name with the **grey cloud (DNS only)** is just DNS:
video goes straight from your router to the viewer, and that's fine.

Settings for a tunnel: `"remote": "public"` and `"trust_proxy": true` in `data/config.json`, as with a
reverse proxy.

**Already have a reverse proxy** (Caddy, nginx)? Leave Sofa's HTTPS off, set `"remote": "public"` and
`"trust_proxy": true`, and let the proxy handle HTTPS. Sofa takes the visitor's address from the **last**
`X-Forwarded-For` entry (the one your proxy adds), so a visitor can't pass for your home network.

## What not to do

Don't forward port 8090 straight to the internet, and don't use the orange cloud or a tunnel for watching.
Without HTTPS, passwords and cookies travel in the clear.
