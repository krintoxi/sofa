# Sofa Box certificates (the secure phone remote)

Each Sofa Box's phone remote is a web page the box serves on the home network. Some phones only open
secure (`https://`) pages, for example an iPhone with Safari's **Not Secure Connection Warning** on. For
those, each box needs a name of its own and a real certificate. This small service gives it both:

- **A name:** `k3x9q2abcd.box.edgeventure.uk`, pointed at the box's address on its home network (like
  `192.168.1.30`). The record is DNS only in Cloudflare, not proxied.
- **A certificate** for that name, from Let's Encrypt. Let's Encrypt checks that the name is ours with
  a DNS record that this service adds to Cloudflare for a moment.

The phone remote at home is then `https://k3x9q2abcd.box.edgeventure.uk:8093`, and every browser
accepts it.

The box makes its own private key and sends only a certificate request, so the key never leaves the
box. The Cloudflare token stays on the Mac that runs this service; boxes never see it.

```
 Sofa Box ──(once a day: its id, its home address, a certificate request)──▶ boxcert.edgeventure.uk
                                                                              (Cloudflare tunnel)
                                                                                     │
                                                                  this service on the iMac (127.0.0.1:8470)
                                                                     │                         │
                                                       Cloudflare DNS (edgeventure.uk)    Let's Encrypt
```

At its setup, the box isn't online yet, so it can't use any of this. There it uses its own Wi-Fi as a
"captive portal" instead (see the box's README), which needs no certificate.

## What it needs

- A Mac (or Linux computer) that's always on: here, the iMac that runs Cubaintel.com.
- Python 3.8 or newer and the `openssl` command. A Mac with Apple's Command Line Tools has both
  (`xcode-select --install`). Nothing else to install.
- The `edgeventure.uk` zone in Cloudflare, and the Cloudflare tunnel already on that iMac.

## Setting it up

### 1. Get this folder onto the iMac

From a copy of the Sofa repository on the iMac (`git clone https://github.com/krintoxi/sofa`, or
`git pull` in one you have), the files are in `deploy/box-certs/`.

### 2. A Cloudflare token that can only change edgeventure.uk's DNS

1. Sign in at **dash.cloudflare.com**. Then click the person icon at the top right → **My Profile** →
   **API Tokens** → **Create Token**.
2. Next to **Edit zone DNS**, press **Use template**.
3. Under **Zone Resources**, choose **Include → Specific zone → edgeventure.uk**. Leave the rest.
4. **Continue to summary** → **Create Token**, and copy the token (Cloudflare shows it once).
5. On the iMac, in Terminal, save it in a file only you can read:

   ```sh
   mkdir -p ~/.config/sofa-box-certs && chmod 700 ~/.config/sofa-box-certs
   pbpaste > ~/.config/sofa-box-certs/cloudflare-token && chmod 600 ~/.config/sofa-box-certs/cloudflare-token
   ```

Keep the token out of chats, email and the repository. If it gets out, delete it in Cloudflare
(**API Tokens → Roll** or **Delete**) and make a new one.

### 3. Install the service

```sh
sh deploy/box-certs/install-mac.sh
```

It copies the service to `~/Library/Application Support/SofaBoxCerts/`, runs `check`, and starts it
now and at every login. If anything's missing, `check` shows what:

```
  ok   openssl: LibreSSL 3.3.6
  ok   Cloudflare token found
  ok   Cloudflare zone edgeventure.uk: 0123abcd…
  ok   Cloudflare DNS records readable for box.edgeventure.uk
  ok   Let's Encrypt answers (https://acme-v02.api.letsencrypt.org/directory)
All good.
```

A real test, if you like: a certificate from Let's Encrypt's **staging** service. Its certificates
aren't trusted, and this doesn't count against any limits.

```sh
python3 ~/Library/Application\ Support/SofaBoxCerts/sofa-box-certs.py try
```

### 4. Its public address in the Cloudflare tunnel

The boxes reach it at `https://boxcert.edgeventure.uk`. That's a public hostname on the tunnel the iMac
already runs.

- **A tunnel managed in the dashboard:** go to **Zero Trust** → **Networks** → **Tunnels**, open the
  iMac's tunnel, then **Public Hostname** → **Add a public hostname**:
  - Subdomain `boxcert`, Domain `edgeventure.uk`.
  - Service type **HTTP**, URL `localhost:8470`.
  - Save.
- **A tunnel with a `config.yml` on the iMac:** add the rule above the last (catch-all) one, then
  restart `cloudflared`:

  ```yaml
    - hostname: boxcert.edgeventure.uk
      service: http://localhost:8470
  ```

  ```sh
  cloudflared tunnel route dns <tunnel name> boxcert.edgeventure.uk
  ```

Check it from anywhere:

```sh
curl https://boxcert.edgeventure.uk/v1/health
```

It should answer `{"ok": true, "base": "box.edgeventure.uk"}`.

### 5. That's all

Boxes with Sofa Box OS 1.1.1 or later get their name and certificate a minute or two after they're
online (1.1.0: within about 10 minutes). On the TV, **Settings → Remotes and Bluetooth** shows **Secure
phone remote: on, at …**, and the phone remote's QR code is the `https://` address from then on.

## Running it

- **Log:** `~/Library/Logs/sofa-box-certs.log` (one line per request).
- **Its files** (back these up), in `~/.config/sofa-box-certs/`:
  - `cloudflare-token`;
  - `account.key`, the Let's Encrypt account;
  - `boxes.json`: each box's id, a hash of its secret, its home address, and when its certificate was made.
- **Update it:** `git pull`, then `sh deploy/box-certs/install-mac.sh` again.
- **Stop it and remove it:** `sh deploy/box-certs/install-mac.sh remove`.
- **Settings:** `~/.config/sofa-box-certs/config.json` (optional). Any of the keys in `DEFAULTS` at
  the top of `sofa-box-certs.py`, like `{"email": "you@example.com"}` for Let's Encrypt's notices.

## Limits and good to know

- **Let's Encrypt's limit.** Let's Encrypt makes at most **50 new certificates a week for
  `edgeventure.uk`**, counting all its names; renewals don't count. The service makes at most 45 a week
  for new boxes (`new_per_week`). Beyond that, a new box simply tries again the next day. Selling more
  boxes a week than that needs a rate-limit increase from Let's Encrypt (a form on their site) or a
  domain just for the boxes.
- **Each box renews by itself** a month before its certificate runs out, and at most once a week.
- **Only home addresses.** The service refuses to point a name at anything but a private address
  (`10.x`, `172.16–31.x`, `192.168.x`), so nobody can aim an `edgeventure.uk` name at a public site.
- **New boxes per day:** at most 10 from one internet address and 500 in all.
- **Routers that block it.** Some routers refuse DNS answers that point at home addresses ("DNS
  rebinding protection": some Fritz!Box, pfSense and ISP routers). The box notices: its remote stays
  plain `http://`, and Settings says why.
- **Public names.** Every certificate is listed in the public Certificate Transparency logs, so the box
  names (random letters) are public. Their addresses are home ones, which mean nothing from outside.

## Trying it without Let's Encrypt (for development)

`tests/test_box_certs.py` stands in for Cloudflare and Let's Encrypt. For the whole real exchange,
run Let's Encrypt's test server **Pebble** and its DNS server locally:

```sh
go install github.com/letsencrypt/pebble/v2/cmd/pebble@latest github.com/letsencrypt/pebble/v2/cmd/pebble-challtestsrv@latest
```

Then point `acme` (and `acme_ca`) in `config.json` at Pebble, and `cloudflare_api` at a stand-in that
passes TXT records to `pebble-challtestsrv`'s `/set-txt`. That's how this service was checked
end to end: a box registered, got its address record and a certificate for exactly its name, and served
its remote over TLS 1.3.
