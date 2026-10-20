# Sofa with IRONGATE

IRONGATE is a self-hosted web-hosting stack with a control panel that watches
every node's background services. Sofa needs nothing from it, but fits in neatly:

1. **Service name.** Install Sofa with a label the panel treats as yours, so it shows
   up under the node's background services with status, logs and restart:

   ```sh
   ./deploy/install.sh --label com.example.sofa
   ```

   (Use whichever prefix your panel's `OWN_PREFIXES` lists.)

2. **Health check.** `GET http://<node>:8090/healthz` (no sign-in) returns
   `{"ok": true, "version": ..., "uptime": ..., "library": {...}}` for monitoring.

3. **Remote access.** Keep Sofa on the node's home network and reach it over the fleet's
   Tailscale. Don't route video through an IRONGATE Cloudflare tunnel; see
   [docs/remote-access.md](../../docs/remote-access.md) for why.

4. **Panel guide.** Add a page to the panel's `docs/panel-guides/` describing where Sofa lives on your node,
   its address, and how to restart it (keep your addresses out of public repos).
