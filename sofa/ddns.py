"""A free address for Sofa: yourname.duckdns.org, kept pointing at your home's internet address.

Homes' internet addresses change now and then; DuckDNS (free, no ads) follows them when told. Sign in at
duckdns.org, make a name, copy the token into Server → Settings → Internet: Sofa tells DuckDNS your
address every 10 minutes (only that, and only while it isn't set to work offline).
"""
import json
import socket
import threading
import time
import urllib.parse
import urllib.request

from . import config, net, store

_last = {"at": None, "ok": None, "message": None}


def subdomain():
    d = (config.get("domain") or "").strip().lower()
    return d[:-len(".duckdns.org")] if d.endswith(".duckdns.org") else None


def active():
    return bool(config.get("duckdns_token") and subdomain())


def update():
    if not active():
        return dict(_last)
    url = "https://www.duckdns.org/update?" + urllib.parse.urlencode(
        {"domains": subdomain(), "token": config.get("duckdns_token"), "ip": ""})
    try:
        with net.urlopen(urllib.request.Request(url, headers={"User-Agent": "Sofa"}), timeout=20) as r:
            answer = r.read().decode("utf-8", "replace").strip()
        ok = answer.startswith("OK")
        if ok != _last["ok"]:
            store.log("settings", "DuckDNS: %s" % ("%s points at this home" % config.get("domain") if ok else
                                                  "the name or token wasn't accepted"))
        _last.update(at=int(time.time()), ok=ok, message=None if ok else "DuckDNS didn't accept that name and token.")
    except net.Offline as exc:
        _last.update(at=int(time.time()), ok=None, message=str(exc))
    except OSError as exc:
        _last.update(at=int(time.time()), ok=False, message="DuckDNS couldn't be reached (%s)." % exc)
    return dict(_last)


class DuckTXT:
    """Let's Encrypt's DNS check through DuckDNS: its TXT record (DuckDNS answers it for _acme-challenge.<name> too).
    A DuckDNS address gets its certificate this way with no open port 80, which many internet providers block."""

    def _call(self, extra):
        url = "https://www.duckdns.org/update?" + urllib.parse.urlencode(dict({"domains": subdomain(), "token": config.get("duckdns_token")}, **extra))
        with net.urlopen(urllib.request.Request(url, headers={"User-Agent": "Sofa"}), timeout=20) as r:
            if not r.read().decode("utf-8", "replace").strip().startswith("OK"):
                raise OSError("DuckDNS didn't accept the DNS check (is the token right?)")

    def set_txt(self, name, value):
        self._call({"txt": value})

    def clear_txt(self, name):
        try:
            self._call({"txt": "", "clear": "true"})
        except OSError:
            pass

    def wait_txt(self, name, value, limit=180):
        """Until the internet's DNS has the record (asked over HTTPS from Cloudflare's resolver), then a little more."""
        q = "https://cloudflare-dns.com/dns-query?" + urllib.parse.urlencode({"name": "_acme-challenge." + name, "type": "TXT"})
        end = time.time() + limit
        while time.time() < end:
            try:
                req = urllib.request.Request(q, headers={"Accept": "application/dns-json", "User-Agent": "Sofa"})
                with net.urlopen(req, timeout=10) as r:
                    answers = json.loads(r.read()).get("Answer") or []
                if any(value in a.get("data", "") for a in answers):
                    time.sleep(5)
                    return True
            except (OSError, ValueError):
                pass
            time.sleep(5)
        return False                                   # Let's Encrypt may see it anyway: it asks DuckDNS itself


def points_here(public_ip):
    """Does the domain lead to this home's internet address?"""
    domain = (config.get("domain") or "").strip()
    if not domain or not public_ip:
        return None
    try:
        return public_ip in {a[4][0] for a in socket.getaddrinfo(domain, None, socket.AF_INET)}
    except OSError:
        return False


def status():
    return dict(_last, active=active())


def _loop():
    time.sleep(20)
    while True:
        update()
        time.sleep(600)


def start():
    threading.Thread(target=_loop, daemon=True, name="duckdns").start()
