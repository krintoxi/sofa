"""A free address for Sofa: yourname.duckdns.org, kept pointing at your home's internet address.

Homes' internet addresses change now and then; DuckDNS (free, no ads) follows them when told. Sign in at
duckdns.org, make a name, copy the token into Server → Settings → Internet: Sofa tells DuckDNS your
address every 10 minutes (only that, and only while it isn't set to work offline).
"""
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
