#!/usr/bin/env python3
"""The Sofa box's start page: finds Sofa on the home network and sends the TV's browser there.

Runs on the Raspberry Pi at http://127.0.0.1:8091 (only for the Pi itself). The kiosk browser opens it
at start; it shows "Looking for Sofa…", and as soon as the Sofa computer answers it goes to Sofa's TV
pages (http://<sofa>/?tv=1). Sofa is found three ways: the address saved last time, Bonjour
(avahi-browse, "_sofa._tcp"), and an SSDP search that Sofa answers. With more than one Sofa, it asks.

Standard library only (Python 3.7+).
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8091
SAVED = os.path.expanduser("~/.config/sofa-box/server")
SOFA_ST = "urn:sofa-media:device:Sofa:1"

found = {}            # url -> name
state = {"chosen": None}
lock = threading.Lock()


def info(base):
    """Sofa's /api/info at `base`, or None."""
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/api/info", timeout=3) as r:
            j = json.loads(r.read().decode("utf-8"))
        return j if j.get("sofa") else None
    except Exception:
        return None


def saved():
    try:
        with open(SAVED, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def save(url):
    os.makedirs(os.path.dirname(SAVED), exist_ok=True)
    with open(SAVED, "w", encoding="utf-8") as f:
        f.write(url + "\n")


def add(base):
    base = base.rstrip("/")
    with lock:
        if base in found:
            return
    j = info(base)
    if j:
        with lock:
            if j.get("id") and any(n.get("id") == j["id"] for n in found.values()):
                return                  # the same Sofa at another of its addresses
            found[base] = {"name": j.get("name") or "Sofa", "id": j.get("id")}


def bonjour():
    """Addresses from avahi-browse ("=;eth0;IPv4;Sofa;_sofa._tcp;local;imac.local;192.168.1.20;8090;…")."""
    try:
        out = subprocess.run(["avahi-browse", "-rtp", "_sofa._tcp"], capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    hits = []
    for line in out.splitlines():
        parts = line.split(";")
        if len(parts) > 8 and parts[0] == "=" and parts[2] == "IPv4":
            hits.append("http://%s:%s" % (parts[7], parts[8]))
    return hits


def ssdp():
    """Addresses from Sofa's answer to an SSDP search (LOCATION: http://ip:port/api/info)."""
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: %s\r\n\r\n" % SOFA_ST).encode()
    hits = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.settimeout(1.0)
        s.sendto(msg, ("239.255.255.250", 1900))
        until = time.time() + 3
        while time.time() < until:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                continue
            m = re.search(r"(?im)^LOCATION:\s*(https?://[^/\s]+)", data.decode("utf-8", "replace"))
            if m:
                hits.append(m.group(1))
    except OSError:
        pass
    finally:
        s.close()
    return hits


def look():
    while True:
        last = saved()
        if last:
            add(last)
        for base in bonjour() + ssdp():
            add(base)
        with lock:
            if state["chosen"] is None:
                if last and last.rstrip("/") in found:
                    state["chosen"] = last.rstrip("/")
                elif len(found) == 1:
                    state["chosen"] = next(iter(found))
                    save(state["chosen"])
        time.sleep(4)


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Sofa box</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:radial-gradient(circle at 25% 20%,#1F2638,#0A0E1A 70%);
color:#F5F1E8;font:28px/1.4 system-ui,sans-serif}
main{width:min(1100px,90vw)}h1{font-size:72px;margin:0 0 8px;color:#F4B740}p{color:#9AA3B8;margin:0 0 28px}
button,input{font:inherit;border-radius:18px;border:2px solid #2A3247;background:#151A28;color:#F5F1E8;padding:18px 26px;margin:0 16px 16px 0}
button:focus,input:focus{outline:none;border-color:#F4B740;background:#F4B740;color:#1A1405}
input:focus{background:#151A28;color:#F5F1E8}.dots::after{content:"";animation:d 1.5s steps(4) infinite}
@keyframes d{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}}
</style></head><body><main><h1>Sofa</h1><p id="msg" class="dots">Looking for Sofa on your home network</p><div id="list"></div>
<form id="f" hidden><input id="addr" placeholder="Or type its address, like 192.168.1.20" size="34"><button>Go</button></form></main>
<script>
const go = url => { location.href = url + "/?tv=1"; };
let shown = "", started = Date.now();
async function poll() {
  try {
    const s = await (await fetch("/state")).json();
    if (s.chosen) { document.getElementById("msg").textContent = "Opening " + s.name + "…"; return go(s.chosen); }
    const key = JSON.stringify(s.found);
    if (key !== shown) {
      shown = key;
      const list = document.getElementById("list");
      list.innerHTML = s.found.map(x => `<button data-url="${x.url}">${x.name} <small>${x.url}</small></button>`).join("");
      if (s.found.length) { document.getElementById("msg").textContent = "Which Sofa?"; document.getElementById("msg").className = ""; list.querySelector("button").focus(); }
    }
    if (Date.now() - started > 20000 && !s.found.length) {
      document.getElementById("msg").textContent = "No Sofa found yet. Is the Sofa computer on? Still looking";
      document.getElementById("f").hidden = false;
    }
  } catch (e) {}
  setTimeout(poll, 1500);
}
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-url]"); if (!b) return;
  await fetch("/choose", { method: "POST", body: b.dataset.url }); go(b.dataset.url);
});
document.getElementById("f").addEventListener("submit", async e => {
  e.preventDefault();
  const r = await (await fetch("/choose", { method: "POST", body: document.getElementById("addr").value })).json();
  if (r.url) go(r.url); else document.getElementById("msg").textContent = "There's no Sofa at that address.";
});
// Arrow keys (the TV remote, a controller) move between the buttons.
document.addEventListener("keydown", e => {
  const all = [...document.querySelectorAll("button,input")].filter(x => x.offsetParent);
  const i = all.indexOf(document.activeElement);
  if (e.key === "ArrowDown" || e.key === "ArrowRight") { (all[i + 1] || all[0]).focus(); e.preventDefault(); }
  if (e.key === "ArrowUp" || e.key === "ArrowLeft") { (all[i - 1] || all[all.length - 1]).focus(); e.preventDefault(); }
});
// A game controller: D-pad moves, A presses.
let was = {};
(function pad() {
  const p = navigator.getGamepads ? [...navigator.getGamepads()].find(Boolean) : null;
  if (p) {
    const k = { 12: "ArrowUp", 13: "ArrowDown", 14: "ArrowLeft", 15: "ArrowRight" };
    p.buttons.forEach((b, i) => {
      if (b.pressed && !was[i]) {
        if (k[i]) document.dispatchEvent(new KeyboardEvent("keydown", { key: k[i] }));
        else if (i === 0 && document.activeElement) document.activeElement.click();
      }
      was[i] = b.pressed;
    });
  }
  requestAnimationFrame(pad);
})();
poll();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send(self, body, ctype="application/json"):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/state"):
            with lock:
                chosen = state["chosen"]
                out = {"chosen": chosen, "name": (found.get(chosen) or {}).get("name") if chosen else None,
                       "found": [{"url": u, "name": v["name"]} for u, v in sorted(found.items())]}
            return self.send(json.dumps(out))
        if "choose=1" in self.path:                   # http://127.0.0.1:8091/?choose=1: pick again
            with lock:
                state["chosen"] = None
        return self.send(PAGE, "text/html; charset=utf-8")

    def do_POST(self):
        typed = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", "replace").strip().rstrip("/")
        if typed and not typed.startswith(("http://", "https://")):
            typed = "http://" + typed
        tries = [typed] if re.search(r":\d+$", typed) else [typed + ":8090", typed]
        url = next((t for t in tries if typed and info(t)), None)
        if url:
            save(url)
            add(url)
            with lock:
                state["chosen"] = url
        return self.send(json.dumps({"url": url}))

    def log_message(self, *args):
        pass


def main():
    threading.Thread(target=look, daemon=True).start()
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print("Sofa box finder on http://127.0.0.1:%d" % PORT, file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
