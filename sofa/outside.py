"""Server → Internet → Check from outside: does Sofa answer from the internet?

Only when an admin presses it. The Sofa Box service (deploy/box-certs, on the internet) is asked two things: this
home's internet address as the internet sees it (/v1/ip), and whether https://<your address>/api/info answers
from there (/v1/reach). Comparing the first with the router's own idea of its address shows an internet provider
that shares one address between homes (CGNAT): then no port can be opened, and Tailscale or a VPN is the way in.
"""
import ipaddress
import json
import threading
import time
import urllib.request

from . import config, net, upnp

_last = {"at": None, "busy": False}
_lock = threading.Lock()
SHARED = ipaddress.ip_network("100.64.0.0/10")        # carrier-grade NAT: the provider's, not yours


def _service():
    return config.get("check_service").rstrip("/")


def _call(path, body=None):
    req = urllib.request.Request(_service() + path, None if body is None else json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "Sofa"})
    with net.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def shared_address(router_ip, public_ip):
    """True when the router's internet address isn't the one the internet sees (CGNAT, or a second router)."""
    if not router_ip or not public_ip:
        return None
    try:
        ip = ipaddress.ip_address(router_ip)
    except ValueError:
        return None
    return router_ip != public_ip or ip in SHARED or ip.is_private


def check():
    with _lock:
        if _last["busy"]:
            return dict(_last)
        _last["busy"] = True
    result = {"at": int(time.time()), "busy": False}
    try:
        public_ip = _call("/v1/ip").get("ip")
        router_ip = (upnp.status() or {}).get("external_ip")
        result.update(public_ip=public_ip, router_ip=router_ip, shared=shared_address(router_ip, public_ip))
        domain = (config.get("domain") or "").strip()
        if domain:
            result["reach"] = _call("/v1/reach", {"url": "https://" + domain})
    except net.Offline as exc:
        result["error"] = str(exc)
    except Exception as exc:                       # (whatever it is, the check isn't left "busy")
        result["error"] = "The check couldn't be done just now (%s)." % str(exc)[:120]
    with _lock:
        _last.clear()
        _last.update(result)
    return dict(_last)


def status():
    with _lock:
        return dict(_last)
