# Watching away from home

Out of the box Sofa answers only devices on your home network, on this computer, and on
Tailscale. Anything from the wider internet gets "home network only". That's the safe
default. Here are the ways to reach it from outside, best first.

## 1. A private VPN (recommended)

Your phone or laptop joins your home network privately; nothing is exposed to the
internet, and Sofa needs no changes.

- **Tailscale** (free for personal use): install it on the Sofa computer and on your
  devices, then open `http://<sofa's tailscale address>:8090`. The Server page lists
  the address.
- **Headscale**: a self-hosted Tailscale control server, if you'd rather not use
  Tailscale's.
- **WireGuard on your router**: many routers (UniFi, Fritz!Box, OpenWrt, GL.iNet) can run
  a WireGuard server; connect to it and use Sofa's home address.

You still sign in to Sofa as usual.

## 2. Your own address on the internet, with HTTPS (built in)

A normal web address (`https://sofa.example.com`, or a free `https://yourname.duckdns.org`) that
works anywhere, locked with each person's account and password, and encrypted. Sofa does all of it
itself: **Server → Internet**, five steps.

1. **Encryption.** Choose **Free certificate from Let's Encrypt**.
2. **Your address.** Your own domain (point its A record at your home's internet address), or a free
   one: sign in at [duckdns.org](https://www.duckdns.org), make a name, and paste its token. Sofa
   keeps a DuckDNS name pointing at your home every 10 minutes, so a changing home address is fine.
3. **The router.** It has to send two ports to the Sofa computer: **443 → Sofa's HTTPS port (8443)** and
   **80 → Sofa's port (8090)**. Switch on **Ask the router to do it** (UPnP, which most routers have);
   otherwise set those two "port forwards" in the router's own page.
4. **The certificate.** Press **Get the certificate**. Let's Encrypt checks that your address reaches
   this computer (on port 80), then issues a certificate for 90 days. Sofa renews it by itself a month
   before it ends.
5. **Let the internet in.** Switch on **Accept connections from the internet**.

What Sofa does when it's on the internet:

- it answers the internet **only over HTTPS**: plain-HTTP visitors are sent to `https://your-address`
  (and refused if there's no trusted certificate), and browsers are told to always use HTTPS (HSTS);
- every request from the internet must be signed in, and new passwords need 12 characters;
- 8 wrong passwords from one address lock it out for 15 minutes;
- the Server page and all admin changes refuse internet connections: manage it from home or over a VPN;
- pairing TVs, guests, TV sharing (DLNA) and artwork without signing in stay home-network only;
- sign-in cookies are Secure (HTTPS only) and HttpOnly; pages can't be framed by other sites.

At home everything keeps working over plain HTTP too (TV apps, Roku, the Sofa box), and
`https://your-address` works from home as well when your router supports it ("NAT loopback").

**Encryption at home only, without a domain:** choose **Sofa's own certificate** in step 1. Sofa makes a
certificate for this computer's names and addresses; each browser asks once whether to trust it.
Or use **My own certificate files**, for example from `tailscale cert`.

**Already have a reverse proxy** (Caddy, nginx)? That still works: leave Sofa's HTTPS off, set
`"remote": "public"` and `"trust_proxy": true` in `data/config.json`, and let the proxy handle HTTPS.

## 3. Cloudflare Tunnel

No open ports: `cloudflared` connects out to Cloudflare, which serves your hostname.
Good for the web app and the Server page (combine with Cloudflare Access for an extra
login). The catch: Cloudflare's terms limit serving large amounts of video through
its regular network, so heavy streaming this way risks being throttled or flagged.
Use it for browsing and occasional viewing, and a VPN for regular watching.
Settings: `remote: public` and `trust_proxy: true`, as with a reverse proxy (option 2).

## What not to do

Don't forward port 8090 straight to the internet. Without HTTPS, passwords and cookies
travel in the clear.
