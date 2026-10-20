"""DLNA/UPnP media server so TVs find Sofa on their own.

Roku Media Player, VLC (Fire TV, phones, computers), Samsung/LG/Sony TVs and game
consoles list it as a media server. DLNA has no logins, so it only answers
devices on the home network and can be switched off on the admin page.
"""
import email.utils
import hashlib
import html
import re
import socket
import struct
import subprocess
import threading
import time
import uuid
import zlib
from urllib.parse import quote

from . import config, live
from .library import LIBRARY

SSDP_ADDR, SSDP_PORT = "239.255.255.250", 1900
UDN = "uuid:" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "sofa." + socket.gethostname()))
DLNA_FLAGS = "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"
STREAM_FLAGS = "DLNA.ORG_OP=00;DLNA.ORG_CI=1;DLNA.ORG_FLAGS=01700000000000000000000000000000"
MIME = {"mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime", "mkv": "video/x-matroska",
        "webm": "video/webm", "avi": "video/x-msvideo"}
TV_DIRECT = {"mp4", "m4v", "mov", "mkv"}
AUDIO_MIME = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac", "flac": "audio/flac", "wav": "audio/wav",
              "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg", "wma": "audio/x-ms-wma",
              "aif": "audio/aiff", "aiff": "audio/aiff", "alac": "audio/mp4"}   # most TVs play these when the video is H.264
TYPES = ["upnp:rootdevice", UDN, "urn:schemas-upnp-org:device:MediaServer:1",
         "urn:schemas-upnp-org:service:ContentDirectory:1", "urn:schemas-upnp-org:service:ConnectionManager:1"]

_tree = {"version": None, "objects": {}}
_tree_lock = threading.Lock()
_running = False


def lan_addresses():
    out = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True).stdout
    ips = re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out)
    return [ip for ip in ips if ip.startswith(("10.", "192.168.")) or re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip)]


def tailscale_addresses():
    out = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True).stdout
    return [ip for ip in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out)
            if re.match(r"100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.", ip)]


def _oid(*parts):
    return hashlib.sha1("/".join(str(p) for p in parts).encode()).hexdigest()[:16]


def tree():
    """Folders TVs browse: Shows > Show > Season > episodes, and Movies."""
    lib = LIBRARY.public()
    with _tree_lock:
        tunes = LIBRARY.music_public()
        version = (lib["generated"], len(live.all_channels()), len(live.favorites_anyone()))
        if _tree["version"] == version:
            return _tree["objects"]
        objs = {}

        def container(oid, parent, title, art=None):
            objs[oid] = {"kind": "container", "title": title, "parent": parent, "children": [], "art": art}
            if parent is not None:
                objs[parent]["children"].append(oid)
            return oid

        def item(parent, title, media, art=None):
            oid = _oid("item", media["id"])
            objs[oid] = {"kind": "item", "title": title, "parent": parent, "id": media["id"], "ext": media["ext"],
                         "size": media.get("size"), "thumb": media.get("thumb") or art, "runtime": media.get("runtime")}
            objs[parent]["children"].append(oid)

        container("0", None, config.get("name"))
        shows = container("shows", "0", "Shows")
        movies = container("movies", "0", "Movies")
        for show in lib["shows"]:
            sid = container(_oid("show", show["id"]), shows, show["name"], show.get("poster"))
            for season in sorted(show["seasons"], key=lambda s: (s["n"] == 0, s["n"])):
                label = "Specials" if season["n"] == 0 else "Season %d" % season["n"]
                cid = container(_oid("season", show["id"], season["n"]), sid, label, season.get("poster") or show.get("poster"))
                for ep in season["episodes"]:
                    num = "%d" % ep["e"] + ("-%d" % ep["e2"] if ep.get("e2") else "")
                    item(cid, "%s. %s" % (num, ep.get("title") or "Episode " + num), ep, show.get("backdrop"))
            if show.get("extras"):
                cid = container(_oid("extras", show["id"]), sid, "Extras", show.get("poster"))
                for x in show["extras"]:
                    item(cid, x["title"], x, show.get("backdrop"))
        for m in lib["movies"]:
            item(movies, "%s (%s)" % (m["title"], m["year"]) if m.get("year") else m["title"], m, m.get("poster"))
        if tunes["tracks"]:
            mroot = container("music", "0", "Music")
            by_album = {}
            for t in tunes["tracks"]:
                by_album.setdefault(t["album_id"], []).append(t)
            for ar in tunes["artists"]:
                arc = container(_oid("artist", ar["id"]), mroot, ar["name"], ar.get("art"))
                for al in [a for a in tunes["albums"] if a["artist_id"] == ar["id"]]:
                    alc = container(_oid("album", al["id"]), arc, al["title"], al.get("art"))
                    for tid in al["tracks"]:
                        t = LIBRARY.item(tid)
                        if not t:
                            continue
                        oid = _oid("track", tid)
                        objs[oid] = {"kind": "item", "audio": True, "title": t["title"], "parent": alc, "id": tid,
                                     "ext": t["ext"], "size": t.get("size"), "thumb": t.get("art"),
                                     "artist": t["artist"], "album": t["album"], "seconds": t.get("duration"),
                                     "n": t.get("n")}
                        objs[alc]["children"].append(oid)
        if tunes["videos"]:
            vroot = container("musicvideos", "0", "Music Videos")
            for v in tunes["videos"]:
                parent = _oid("mvartist", v["artist_id"])
                if parent not in objs:
                    container(parent, vroot, v["artist"])
                item(parent, v["title"], {**v, "size": None, "runtime": None})
        chans = live.all_channels()
        if chans:
            tv = container("live", "0", "Live TV")
            favs = live.favorites_anyone()
            groups = {}
            if favs:
                groups["Favorites"] = [c for c in chans if c["id"] in favs]
            for c in sorted(chans, key=lambda c: c["name"].lower()):
                groups.setdefault(c["group"], []).append(c)
            for g in ["Favorites"] + sorted(k for k in groups if k != "Favorites"):
                if g not in groups:
                    continue
                gid = container(_oid("live", g), tv, g)
                for c in groups[g]:
                    oid = _oid("chan", g, c["id"])
                    objs[oid] = {"kind": "item", "title": c["name"], "parent": gid, "live": c["id"], "thumb": None}
                    objs[gid]["children"].append(oid)
        _tree["version"], _tree["objects"] = version, objs
        return objs


def update_id():
    return LIBRARY.generated % 2**31


# ---------------------------------------------------------------- XML

def device_xml(host):
    return """<?xml version="1.0" encoding="utf-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0" xmlns:dlna="urn:schemas-dlna-org:device-1-0">
 <specVersion><major>1</major><minor>0</minor></specVersion>
 <URLBase>http://%(host)s/</URLBase>
 <device>
  <deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType>
  <friendlyName>%(name)s</friendlyName>
  <manufacturer>Sofa</manufacturer><modelName>Sofa media server</modelName><modelNumber>1</modelNumber>
  <UDN>%(udn)s</UDN>
  <dlna:X_DLNADOC>DMS-1.50</dlna:X_DLNADOC>
  <presentationURL>http://%(host)s/</presentationURL>
  <iconList><icon><mimetype>image/png</mimetype><width>120</width><height>120</height><depth>24</depth><url>/dlna/icon.png</url></icon></iconList>
  <serviceList>
   <service><serviceType>urn:schemas-upnp-org:service:ContentDirectory:1</serviceType>
    <serviceId>urn:upnp-org:serviceId:ContentDirectory</serviceId>
    <SCPDURL>/dlna/cds.xml</SCPDURL><controlURL>/dlna/cds/control</controlURL><eventSubURL>/dlna/cds/event</eventSubURL></service>
   <service><serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
    <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
    <SCPDURL>/dlna/cms.xml</SCPDURL><controlURL>/dlna/cms/control</controlURL><eventSubURL>/dlna/cms/event</eventSubURL></service>
  </serviceList>
 </device>
</root>""" % {"host": host, "name": html.escape(config.get("name")), "udn": UDN}


def _scpd(actions, variables):
    acts = "".join("<action><name>%s</name><argumentList>%s</argumentList></action>" % (name, "".join(
        "<argument><name>%s</name><direction>%s</direction><relatedStateVariable>%s</relatedStateVariable></argument>" % a
        for a in args)) for name, args in actions)
    vs = "".join('<stateVariable sendEvents="%s"><name>%s</name><dataType>%s</dataType></stateVariable>' % (ev, n, t)
                 for n, t, ev in variables)
    return ('<?xml version="1.0" encoding="utf-8"?><scpd xmlns="urn:schemas-upnp-org:service-1-0">'
            "<specVersion><major>1</major><minor>0</minor></specVersion><actionList>%s</actionList>"
            "<serviceStateTable>%s</serviceStateTable></scpd>" % (acts, vs))


CDS_XML = _scpd([
    ("Browse", [("ObjectID", "in", "A_ARG_TYPE_ObjectID"), ("BrowseFlag", "in", "A_ARG_TYPE_BrowseFlag"),
                ("Filter", "in", "A_ARG_TYPE_Filter"), ("StartingIndex", "in", "A_ARG_TYPE_Index"),
                ("RequestedCount", "in", "A_ARG_TYPE_Count"), ("SortCriteria", "in", "A_ARG_TYPE_SortCriteria"),
                ("Result", "out", "A_ARG_TYPE_Result"), ("NumberReturned", "out", "A_ARG_TYPE_Count"),
                ("TotalMatches", "out", "A_ARG_TYPE_Count"), ("UpdateID", "out", "A_ARG_TYPE_UpdateID")]),
    ("GetSearchCapabilities", [("SearchCaps", "out", "SearchCapabilities")]),
    ("GetSortCapabilities", [("SortCaps", "out", "SortCapabilities")]),
    ("GetSystemUpdateID", [("Id", "out", "SystemUpdateID")]),
], [("A_ARG_TYPE_ObjectID", "string", "no"), ("A_ARG_TYPE_BrowseFlag", "string", "no"),
    ("A_ARG_TYPE_Filter", "string", "no"), ("A_ARG_TYPE_Index", "ui4", "no"), ("A_ARG_TYPE_Count", "ui4", "no"),
    ("A_ARG_TYPE_SortCriteria", "string", "no"), ("A_ARG_TYPE_Result", "string", "no"),
    ("A_ARG_TYPE_UpdateID", "ui4", "no"), ("SearchCapabilities", "string", "no"),
    ("SortCapabilities", "string", "no"), ("SystemUpdateID", "ui4", "yes")])

CMS_XML = _scpd([
    ("GetProtocolInfo", [("Source", "out", "SourceProtocolInfo"), ("Sink", "out", "SinkProtocolInfo")]),
    ("GetCurrentConnectionIDs", [("ConnectionIDs", "out", "CurrentConnectionIDs")]),
], [("SourceProtocolInfo", "string", "yes"), ("SinkProtocolInfo", "string", "yes"),
    ("CurrentConnectionIDs", "string", "yes")])


def _entry(oid, obj, host):
    e = html.escape
    url = lambda p: "http://%s%s" % (host, quote(p))
    if obj["kind"] == "container":
        art = '<upnp:albumArtURI dlna:profileID="JPEG_TN">%s</upnp:albumArtURI>' % e(url(obj["art"]) + "?w=480") if obj.get("art") else ""
        return ('<container id="%s" parentID="%s" restricted="1" childCount="%d"><dc:title>%s</dc:title>'
                "<upnp:class>object.container.storageFolder</upnp:class>%s</container>"
                % (e(oid), e(obj["parent"] or "-1"), len(obj["children"]), e(obj["title"]), art))
    if obj.get("audio"):
        secs = int(obj.get("seconds") or 0)
        res = '<res protocolInfo="http-get:*:%s:%s"%s%s>%s</res>' % (
            AUDIO_MIME.get(obj["ext"], "audio/mpeg"), DLNA_FLAGS, ' size="%d"' % obj["size"] if obj.get("size") else "",
            ' duration="%d:%02d:%02d.000"' % (secs // 3600, secs // 60 % 60, secs % 60) if secs else "",
            e(url("/dlna/media/" + obj["id"])))
        art = '<upnp:albumArtURI dlna:profileID="JPEG_TN">%s</upnp:albumArtURI>' % e(url(obj["thumb"]) + "?w=480") if obj.get("thumb") else ""
        return ('<item id="%s" parentID="%s" restricted="1"><dc:title>%s</dc:title><upnp:class>object.item.audioItem.musicTrack</upnp:class>'
                '<upnp:artist>%s</upnp:artist><dc:creator>%s</dc:creator><upnp:album>%s</upnp:album>%s%s%s</item>'
                % (e(oid), e(obj["parent"]), e(obj["title"]), e(obj["artist"]), e(obj["artist"]), e(obj["album"]),
                   '<upnp:originalTrackNumber>%d</upnp:originalTrackNumber>' % obj["n"] if obj.get("n") else "", art, res))
    if obj.get("live"):
        return ('<item id="%s" parentID="%s" restricted="1"><dc:title>%s</dc:title>'
                '<upnp:class>object.item.videoItem.videoBroadcast</upnp:class>'
                '<res protocolInfo="http-get:*:video/mpeg:%s">%s</res></item>'
                % (e(oid), e(obj["parent"]), e(obj["title"]), STREAM_FLAGS, e(url("/dlna/live/" + obj["live"]))))
    item = LIBRARY.item(obj["id"])
    direct = obj["ext"] in TV_DIRECT and _tv_video_ok(item)
    if direct:
        res = '<res protocolInfo="http-get:*:%s:%s"%s%s>%s</res>' % (
            MIME.get(obj["ext"], "video/mp4"), DLNA_FLAGS, ' size="%d"' % obj["size"] if obj.get("size") else "",
            ' duration="%d:%02d:00.000"' % divmod(int(obj["runtime"]), 60) if obj.get("runtime") else "",
            e(url("/dlna/media/" + obj["id"])))
    else:
        res = '<res protocolInfo="http-get:*:video/mp4:%s">%s</res>' % (STREAM_FLAGS, e(url("/dlna/media/" + obj["id"])))
    art = '<upnp:albumArtURI dlna:profileID="JPEG_TN">%s</upnp:albumArtURI>' % e(url(obj["thumb"]) + "?w=480") if obj.get("thumb") else ""
    return ('<item id="%s" parentID="%s" restricted="1"><dc:title>%s</dc:title>'
            "<upnp:class>object.item.videoItem</upnp:class>%s%s</item>" % (e(oid), e(obj["parent"]), e(obj["title"]), art, res))


def _tv_video_ok(item):
    from . import media
    if not item:
        return False
    info = media.probe(item["path"], cached_only=True)
    if not info:
        return item["ext"] in ("mp4", "m4v", "mkv")
    return (info.get("video") or {}).get("codec") in ("h264", "hevc")


def tv_plan(item):
    """'direct' or 'transcode' for a TV asking for this item over DLNA."""
    if item["kind"] == "track":
        return "direct"
    return "direct" if item["ext"] in TV_DIRECT and _tv_video_ok(item) else "transcode"


def browse(args, host):
    objs = tree()
    oid = args.get("ObjectID", "0")
    obj = objs.get(oid)
    if obj is None:
        return None
    start = int(args.get("StartingIndex") or 0)
    count = int(args.get("RequestedCount") or 0)
    if args.get("BrowseFlag") == "BrowseMetadata":
        entries, total = [_entry(oid, obj, host)], 1
    else:
        kids = obj.get("children", [])
        total = len(kids)
        page = kids[start:start + count] if count else kids[start:]
        entries = [_entry(k, objs[k], host) for k in page]
    didl = ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">'
            + "".join(entries) + "</DIDL-Lite>")
    return {"Result": didl, "NumberReturned": len(entries), "TotalMatches": total, "UpdateID": update_id()}


def soap(service, action, values):
    body = "".join("<%s>%s</%s>" % (k, html.escape(str(v)), k) for k, v in values.items())
    return ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            '<u:%sResponse xmlns:u="urn:schemas-upnp-org:service:%s:1">%s</u:%sResponse></s:Body></s:Envelope>'
            % (action, service, body, action))


def soap_fault(code, text):
    return ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><s:Fault><faultcode>s:Client</faultcode>'
            '<faultstring>UPnPError</faultstring><detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0">'
            "<errorCode>%d</errorCode><errorDescription>%s</errorDescription></UPnPError></detail></s:Fault>"
            "</s:Body></s:Envelope>" % (code, text))


def control(path, action, args, host):
    """(status, xml) for a SOAP request."""
    if path == "/dlna/cds/control":
        if action == "Browse":
            result = browse(args, host)
            return (200, soap("ContentDirectory", action, result)) if result else (500, soap_fault(701, "No such object"))
        if action == "GetSystemUpdateID":
            return 200, soap("ContentDirectory", action, {"Id": update_id()})
        if action == "GetSearchCapabilities":
            return 200, soap("ContentDirectory", action, {"SearchCaps": ""})
        if action == "GetSortCapabilities":
            return 200, soap("ContentDirectory", action, {"SortCaps": ""})
    if path == "/dlna/cms/control":
        if action == "GetProtocolInfo":
            src = ",".join("http-get:*:%s:*" % m for m in sorted(set(MIME.values())))
            return 200, soap("ConnectionManager", action, {"Source": src, "Sink": ""})
        if action == "GetCurrentConnectionIDs":
            return 200, soap("ConnectionManager", action, {"ConnectionIDs": "0"})
    return 500, soap_fault(401, "Invalid Action")


_icon = None


def icon_png():
    """120x120 amber square (generated; no image files needed)."""
    global _icon
    if _icon is None:
        w = h = 120
        raw = (b"\x00" + bytes((0xF4, 0xB7, 0x40)) * w) * h
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        _icon = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return _icon


# ---------------------------------------------------------------- SSDP discovery

def _usn(nt):
    return UDN if nt == UDN else "%s::%s" % (UDN, nt)


def _local_ip_for(peer):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((peer, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def _listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("", SSDP_PORT))
    for ip in lan_addresses():
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(SSDP_ADDR) + socket.inet_aton(ip))
        except OSError:
            pass
    while True:
        data, peer = sock.recvfrom(4096)
        if not config.get("dlna"):
            continue
        text = data.decode("utf-8", "replace")
        if not text.startswith("M-SEARCH"):
            continue
        st = (re.search(r"(?im)^ST:\s*(.+?)\s*$", text) or [None, ""])[1]
        targets = TYPES if st == "ssdp:all" else [st] if st in TYPES else []
        if not targets:
            continue
        here = _local_ip_for(peer[0])
        for nt in targets:
            reply = ("HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\nDATE: %s\r\nEXT:\r\n"
                     "LOCATION: http://%s:%d/dlna/device.xml\r\nSERVER: Sofa/1.0 UPnP/1.0 DLNADOC/1.50\r\n"
                     "ST: %s\r\nUSN: %s\r\nContent-Length: 0\r\n\r\n"
                     % (email.utils.formatdate(usegmt=True), here, config.get("port"), nt, _usn(nt)))
            sock.sendto(reply.encode(), peer)


def notify(kind="ssdp:alive"):
    for ip in lan_addresses():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
            for nt in TYPES:
                msg = ("NOTIFY * HTTP/1.1\r\nHOST: %s:%d\r\nCACHE-CONTROL: max-age=1800\r\n"
                       "LOCATION: http://%s:%d/dlna/device.xml\r\nNT: %s\r\nNTS: %s\r\n"
                       "SERVER: Sofa/1.0 UPnP/1.0 DLNADOC/1.50\r\nUSN: %s\r\n\r\n"
                       % (SSDP_ADDR, SSDP_PORT, ip, config.get("port"), nt, kind, _usn(nt)))
                s.sendto(msg.encode(), (SSDP_ADDR, SSDP_PORT))
        except OSError:
            pass
        finally:
            s.close()


def _announcer():
    while True:
        if config.get("dlna"):
            notify()
        time.sleep(60)


def start():
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_listener, daemon=True, name="ssdp-listen").start()
    threading.Thread(target=_announcer, daemon=True, name="ssdp-announce").start()
