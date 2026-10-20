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

## 2. A secure public address

For a normal URL (`https://sofa.example.com`) that works without a VPN app. This is how
most Plex and Jellyfin servers are reached; it's fine when done properly:

1. Put Sofa behind a reverse proxy that handles HTTPS. [Caddy](https://caddyserver.com)
   gets certificates automatically:

   ```
   sofa.example.com {
       reverse_proxy 127.0.0.1:8090
   }
   ```

2. Forward port 443 on your router to the proxy (only 443, never 8090).
3. In `data/config.json` set `"remote": "public"` and `"trust_proxy": true`, then
   restart Sofa.

What Sofa does in this mode:

- every request from the internet must be signed in;
- sign-in cookies are marked Secure (HTTPS only) and HttpOnly;
- 8 wrong passwords from one address lock it out for 15 minutes;
- the Server page and all admin actions refuse internet connections: manage the
  server from home or over a VPN;
- TV sharing (DLNA) and artwork-without-sign-in stay home-network only.

Use long, unique passwords for every account, and keep Sofa and the proxy up to date.

## 3. Cloudflare Tunnel

No open ports: `cloudflared` connects out to Cloudflare, which serves your hostname.
Good for the web app and the Server page (combine with Cloudflare Access for an extra
login). The catch: Cloudflare's terms limit serving large amounts of video through
its regular network, so heavy streaming this way risks being throttled or flagged.
Use it for browsing and occasional viewing, and a VPN for regular watching.
Settings are the same as option 2 (`remote: public`, `trust_proxy: true`).

## What not to do

Don't forward port 8090 straight to the internet. Without HTTPS, passwords and cookies
travel in the clear.
