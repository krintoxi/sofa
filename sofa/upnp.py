"""Asking the home router to send the internet's HTTPS (port 443) and HTTP (port 80) to Sofa, with UPnP
(most home routers do it; it's often called "UPnP" or "NAT-PMP/UPnP" in the router's settings).

443 goes to Sofa's HTTPS port (8443), 80 to its normal port (where Let's Encrypt checks the domain and
browsers are sent on to HTTPS). Nothing here touches the internet: it's a conversation with the router.
Without UPnP, set the same two "port forwards" in the router's own page.
"""
import re
import socket
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import config, store

DEVICES = ("urn:schemas-upnp-org:device:InternetGatewayDevice:2", "urn:schemas-upnp-org:device:InternetGatewayDevice:1")
SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2", "urn:schemas-upnp-org:service:WANIPConnection:1",
            "urn:schemas-upnp-org:service:WANPPPConnection:1")
_last = {"at": None, "ok": None, "message": None, "external_ip": None, "router": None}
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))       # the router is at home: never a proxy


class UpnpError(Exception):
    pass


def discover(timeout=3):
    """Routers that answered an SSDP search: their description addresses."""
    found = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.settimeout(0.5)
        for st in DEVICES:
            s.sendto(("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: %s\r\n\r\n"
                      % st).encode(), ("239.255.255.250", 1900))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                continue
            m = re.search(r"(?im)^LOCATION:\s*(\S+)", data.decode("utf-8", "replace"))
            if m and m.group(1) not in found:
                found.append(m.group(1))
    except OSError:
        pass
    finally:
        s.close()
    return found


def gateway(location):
    """The router's port-forwarding service: {"control", "service", "name", "host"}."""
    with _opener.open(location, timeout=5) as r:
        root = ET.fromstring(r.read())
    ns = {"d": "urn:schemas-upnp-org:device-1-0"}
    name = root.findtext(".//d:friendlyName", default="your router", namespaces=ns)
    for svc in root.iter("{urn:schemas-upnp-org:device-1-0}service"):
        kind = svc.findtext("d:serviceType", namespaces=ns)
        if kind in SERVICES:
            control = urllib.parse.urljoin(location, svc.findtext("d:controlURL", namespaces=ns))
            return {"control": control, "service": kind, "name": name, "host": urllib.parse.urlsplit(location).hostname}
    raise UpnpError("%s doesn't offer port forwarding over UPnP" % name)


def _soap(gw, action, args):
    body = "".join("<%s>%s</%s>" % (k, v, k) for k, v in args)
    envelope = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:%s xmlns:u="%s">%s</u:%s>'
                '</s:Body></s:Envelope>' % (action, gw["service"], body, action))
    req = urllib.request.Request(gw["control"], data=envelope.encode(), method="POST",
                                 headers={"Content-Type": 'text/xml; charset="utf-8"',
                                          "SOAPAction": '"%s#%s"' % (gw["service"], action)})
    try:
        with _opener.open(req, timeout=8) as r:
            text = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        code = re.search(r"<errorCode>(\d+)</errorCode>", text)
        desc = re.search(r"<errorDescription>([^<]*)</errorDescription>", text)
        raise UpnpError("the router said no (%s%s)" % (code.group(1) if code else e.code, ": " + desc.group(1) if desc else ""))
    return dict(re.findall(r"<(New\w+)>([^<]*)</New\w+>", text))


def local_address(router_host):
    """This computer's address on the router's network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((router_host, 1900))
        return s.getsockname()[0]
    finally:
        s.close()


def forward(gw, external, internal, me, what):
    args = [("NewRemoteHost", ""), ("NewExternalPort", external), ("NewProtocol", "TCP"), ("NewInternalPort", internal),
            ("NewInternalClient", me), ("NewEnabled", 1), ("NewPortMappingDescription", "Sofa " + what)]
    try:
        _soap(gw, "AddPortMapping", args + [("NewLeaseDuration", 0)])
    except UpnpError:
        _soap(gw, "AddPortMapping", args + [("NewLeaseDuration", 7 * 86400)])     # routers that want an end date


def open_ports(location=None):
    """Forward 443 → HTTPS port and 80 → Sofa's port on the router. Returns the result (also kept for status())."""
    try:
        locations = [location] if location else discover()
        if not locations:
            raise UpnpError("No router answered. Switch UPnP on in the router's settings, or forward the ports by hand.")
        gw = gateway(locations[0])
        me = local_address(gw["host"])
        forward(gw, 443, config.get("https_port"), me, "HTTPS")
        forward(gw, 80, config.get("port"), me, "web check")
        ip = _soap(gw, "GetExternalIPAddress", []).get("NewExternalIPAddress")
        _last.update(at=int(time.time()), ok=True, external_ip=ip, router=gw["name"],
                     message="%s sends ports 443 and 80 to this computer (%s)." % (gw["name"], me))
        store.log("settings", "The router (%s) forwards ports 443 and 80 to Sofa" % gw["name"])
    except (UpnpError, OSError, ET.ParseError) as exc:
        _last.update(at=int(time.time()), ok=False, message=str(exc)[:300])
    return dict(_last)


def status():
    return dict(_last)


def refresh_loop():
    """Routers forget forwards with an end date, or when they restart: ask again every few hours."""
    time.sleep(90)
    while True:
        if config.get("upnp") and config.get("https") != "off":
            open_ports()
        time.sleep(6 * 3600)


def start():
    import threading
    threading.Thread(target=refresh_loop, daemon=True, name="upnp").start()
