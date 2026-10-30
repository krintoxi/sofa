"""HTTP: the web app, its JSON API, media streaming, artwork and DLNA."""
import email.utils
import gzip
import html
import json
import os
import platform
import re
import shutil
import sys
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

import threading

from . import (__version__, artwork, auth, backup, config, dlna, fetch, housekeeping, intros, live, media, metadata, music,
               kids, machine, net, optimize, organizer, places, previews, report, screens, store, trickplay, updater,
               travel, uploads)
from .library import LIBRARY

CLIENT_DIR = os.path.join(config.APP_DIR, "client")
STARTED = time.time()
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css",
        ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml", ".webp": "image/webp", ".vtt": "text/vtt; charset=utf-8", ".ico": "image/x-icon",
        ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
        ".webm": "video/webm", ".avi": "video/x-msvideo", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
        ".flac": "audio/flac", ".wav": "audio/wav", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
        ".wma": "audio/x-ms-wma", ".aif": "audio/aiff", ".aiff": "audio/aiff", ".alac": "audio/mp4",
        ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8", ".webmanifest": "application/manifest+json"}
HOME_NETS = ("local", "lan", "tailnet")


class Handler(BaseHTTPRequestHandler):
    server_version = "Sofa/%s" % __version__
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("SOFA_DEBUG"):
            sys.stderr.write("%s %s\n" % (self.client_ip(), fmt % args))

    # ------------------------------------------------------------ request context

    def client_ip(self):
        peer = self.client_address[0]
        if config.get("trust_proxy") and auth.network_of(peer) == "local":
            fwd = self.headers.get("X-Forwarded-For", "")
            if fwd:
                return fwd.split(",")[0].strip()
        return peer

    def is_https(self):
        return config.get("trust_proxy") and self.headers.get("X-Forwarded-Proto") == "https"

    def token(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return c[auth.SESSION_COOKIE].value if auth.SESSION_COOKIE in c else None

    def setup(self):
        super().setup()
        self._user = False

    def user(self):
        if self._user is False:
            self._user = auth.session_user(self.token())
        return self._user

    def host_header(self):
        return "%s:%d" % (self.connection.getsockname()[0], config.get("port"))

    # ------------------------------------------------------------ responses

    def send_body(self, data, ctype="text/plain; charset=utf-8", status=200, headers=None):
        if isinstance(data, str):
            data = data.encode("utf-8")
        headers = dict(headers or {})
        if len(data) > 4096 and ctype.split(";")[0] in ("application/json", "text/plain", "text/html", "text/css", "text/javascript") \
                and "gzip" in (self.headers.get("Accept-Encoding") or "") and "Content-Disposition" not in headers:
            data = gzip.compress(data, compresslevel=5)      # the library is ~10x smaller: matters on TV sticks and Wi-Fi
            headers.update({"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def json(self, obj, status=200, headers=None):
        h = {"Cache-Control": "no-store"}
        h.update(headers or {})
        self.send_body(json.dumps(obj, separators=(",", ":")), "application/json", status, h)

    def error(self, status, message):
        self.json({"error": message}, status)

    def body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 65536:
            return None
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None

    def may_switch(self, u):
        return bool(u) and not u.get("guest") and self.network() in HOME_NETS

    def session_cookie(self, token, max_age):
        parts = ["%s=%s" % (auth.SESSION_COOKIE, token), "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=%d" % max_age]
        if self.is_https():
            parts.append("Secure")
        return "; ".join(parts)

    # ------------------------------------------------------------ gatekeeping

    def network(self):
        return auth.network_of(self.client_ip())

    def gate(self):
        """False (after replying) when this connection isn't allowed at all."""
        self._user = False   # connections are reused; look the user up again for every request
        if not auth.allowed_network(self.network()):
            self.send_body("Sofa is set to accept connections from your home network only.", status=403)
            return False
        return True

    def need_user(self, admin=False):
        u = self.user()
        if not u:
            self.error(401, "Sign in to continue.")
            return None
        if admin and not u["admin"]:
            self.error(403, "Only admins can do that.")
            return None
        if admin and self.network() == "internet":
            self.error(403, "Admin settings are only available from home or over Tailscale.")
            return None
        return u

    def dlna_allowed(self):
        return config.get("dlna") and self.network() in HOME_NETS

    # ------------------------------------------------------------ methods

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.gate():
            return
        url = urlsplit(self.path)
        path, qs = unquote(url.path), parse_qs(url.query)
        if path == "/healthz":
            return self.json({"ok": True, "name": config.get("name"), "version": __version__,
                              "uptime": int(time.time() - STARTED), "library": LIBRARY.counts()})
        if path in ("/", "/index.html"):
            return self.static("index.html")
        if path == "/guest":
            return self.guest_entry()
        if path.startswith("/client/"):
            return self.static(path[len("/client/"):])
        if path.startswith("/dlna/"):
            return self.dlna_get(path)
        if path.startswith("/art/"):
            return self.art(path[len("/art/"):], qs)
        if path.startswith("/media/"):
            return self.media_get(path, qs)
        if path.startswith("/live/"):
            return self.live_get(path)
        if path.startswith("/api/"):
            return self.api_get(path, qs)
        self.send_body("Not found", status=404)

    def do_POST(self):
        if not self.gate():
            return
        path = unquote(urlsplit(self.path).path)      # IDs in the address ("e:the-sopranos:1:1") arrive %-encoded
        if path.startswith("/dlna/"):
            if not self.dlna_allowed():
                return self.send_body("Not found", status=404)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(length, 65536)).decode("utf-8", "replace")
            action = (self.headers.get("SOAPACTION") or "").strip('"').split("#")[-1]
            args = {k: html.unescape(v) for k, v in re.findall(r"<(?:\w+:)?(\w+)>([^<]*)</(?:\w+:)?\1>", body)}
            status, xml = dlna.control(path, action, args, self.host_header())
            return self.send_body(xml, 'text/xml; charset="utf-8"', status)
        if self.headers.get("X-Sofa") != "1":
            return self.error(400, "Missing X-Sofa header.")
        if path == "/api/admin/upload":                # a file sent from a phone or laptop: streamed, not read as JSON
            return self.upload()
        data = self.body_json()
        if data is None:
            return self.error(400, "Couldn't read the request.")
        self.api_post(path, data)

    def upload(self):
        u = self.need_user(admin=True)
        if not u:
            self.close_connection = True
            return
        qs = parse_qs(urlsplit(self.path).query)
        try:
            size = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            size = -1
        adult = (qs.get("adult") or [""])[0] == "1"
        if size < 0:
            return self.error(411, "The upload didn't say how big it is.")
        if adult and not u.get("adult"):
            return self.error(403, "Switch the Adult section on for yourself first (Server, People).")
        try:
            uploads.receive(self.rfile, (qs.get("name") or [""])[0], size, adult, u["name"])
        except ValueError as exc:
            self.close_connection = True          # the rest of the file is still coming: don't read it
            return self.error(400, str(exc))
        except (OSError, ConnectionError) as exc:
            self.close_connection = True
            return self.error(500, "The upload didn't finish: %s" % exc)
        return self.json({"ok": True})

    def do_SUBSCRIBE(self):
        self.send_response(200)
        self.send_header("SID", "uuid:sofa-%d" % int(time.time() * 1000))
        self.send_header("TIMEOUT", "Second-1800")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_UNSUBSCRIBE(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ------------------------------------------------------------ guests

    def guest_ok(self):
        return config.get("guest_access") and self.network() in ("local", "lan")

    def guest_entry(self):
        """The address on the guest QR code: sign straight in as Guest, then open the app."""
        if not self.guest_ok():
            msg = ("Guest access is switched off." if not config.get("guest_access")
                   else "Guest access works on the home Wi-Fi. Connect to it and scan the code again.")
            page = ('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sofa</title>'
                    '<body style="background:#0A0E1A;color:#EDEFF6;font:17px/1.5 system-ui;display:grid;place-items:center;'
                    'min-height:90vh;margin:0;padding:24px;text-align:center"><div><h1 style="margin:0 0 8px">Sofa</h1>'
                    '<p>%s</p></div>' % msg)
            return self.send_body(page, "text/html; charset=utf-8", 403)
        user = auth.guest_user()
        token = auth.start_session(user["id"], self.client_ip(), self.headers.get("User-Agent"))
        store.log("login", "A guest joined from %s" % self.client_ip())
        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", self.session_cookie(token, auth.GUEST_HOURS * 3600))
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ------------------------------------------------------------ static, art, files

    def static(self, rel):
        rel = os.path.normpath(rel)
        full = os.path.join(CLIENT_DIR, rel)
        if rel.startswith("..") or not os.path.isfile(full):
            return self.send_body("Not found", status=404)
        with open(full, "rb") as f:
            data = f.read()
        self.send_body(data, MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream"),   # bundled fonts and libraries: kept a week
                       headers={"Cache-Control": "private, max-age=604800" if rel.startswith(("vendor" + os.sep, "icons" + os.sep)) else "no-cache"})

    def art(self, rest, qs):
        if not self.user() and self.network() not in HOME_NETS:   # TVs fetch artwork without signing in
            return self.error(401, "Sign in to continue.")
        if rest.split("/")[0].partition("~")[0] == "adult" and not (self.user() or {}).get("adult"):
            return self.send_body("Not found", status=404)
        full = artwork.file_for("/art/" + rest)
        if not full:
            return self.send_body("Not found", status=404)
        width = (qs.get("w") or [""])[0]
        if width.isdigit():
            full = artwork.resized(full, int(width))
        self.send_file(full, cache="private, max-age=604800")

    def send_file(self, full, cache=None, dlna_headers=False, download=None):
        size = os.path.getsize(full)
        ctype = MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        start, end = 0, size - 1
        rng = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Last-Modified", email.utils.formatdate(os.path.getmtime(full), usegmt=True))
        if cache:
            self.send_header("Cache-Control", cache)
        if dlna_headers:
            self.send_header("transferMode.dlna.org", "Streaming")
            self.send_header("contentFeatures.dlna.org", dlna.DLNA_FLAGS)
        if download:                                  # saved as a file, under a tidy name
            plain = re.sub(r'[^\x20-\x7e]|["\\]', "_", download)
            self.send_header("Content-Disposition", "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (plain, quote(download)))
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(full, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass   # players drop connections while seeking

    def owner(self):
        """Who a live conversion belongs to: one per browser session, or per TV."""
        tok = self.token()
        return ("web:" + auth._token_key(tok)[:16]) if tok else "tv:" + self.client_ip()

    def stream(self, item, mode, start, who, dlna_headers=False, audio_index=None, max_height=None):
        info = media.probe(item["path"])
        fmt = "mpegts" if dlna_headers else "mp4"   # TVs handle MPEG-TS streams most reliably
        self.send_response(200)
        self.send_header("Content-Type", "video/mpeg" if fmt == "mpegts" else "video/mp4")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if dlna_headers:
            self.send_header("transferMode.dlna.org", "Streaming")
            self.send_header("contentFeatures.dlna.org", dlna.STREAM_FLAGS)
        self.end_headers()
        self.close_connection = True
        if self.command == "HEAD":
            return
        try:
            media.run_stream(item, mode, start, info, self.wfile, who, fmt, owner=self.owner(), audio_index=audio_index,
                             max_height=max_height)
        except (RuntimeError, OSError):
            pass

    # ------------------------------------------------------------ DLNA

    def dlna_get(self, path):
        if not self.dlna_allowed():
            return self.send_body("Not found", status=404)
        xml = 'text/xml; charset="utf-8"'
        if path == "/dlna/device.xml":
            return self.send_body(dlna.device_xml(self.host_header()), xml)
        if path == "/dlna/cds.xml":
            return self.send_body(dlna.CDS_XML, xml)
        if path == "/dlna/cms.xml":
            return self.send_body(dlna.CMS_XML, xml)
        if path == "/dlna/icon.png":
            return self.send_body(dlna.icon_png(), "image/png")
        if path.startswith("/dlna/live/"):
            chan = live.channel(path[len("/dlna/live/"):])
            if not chan or chan.get("adult") or not media.tool("ffmpeg"):
                return self.send_body("Not found", status=404)
            return self.stream({"id": "live:" + chan["id"], "path": chan["url"], "title": chan["name"]}, "remux", 0,
                               "TV at " + self.client_ip(), dlna_headers=True)
        if path.startswith("/dlna/media/"):
            item = LIBRARY.item(path[len("/dlna/media/"):])
            if not item or item.get("adult"):
                return self.send_body("Not found", status=404)
            who = "TV at " + self.client_ip()
            if dlna.tv_plan(item) == "direct" or not media.tool("ffmpeg"):
                media.note_direct(item, who)
                return self.send_file(item["path"], dlna_headers=True)
            mode = media.plan(item, {})["mode"]
            return self.stream(item, "remux" if mode in ("remux", "direct") else "transcode", 0, who, dlna_headers=True)
        self.send_body("Not found", status=404)

    # ------------------------------------------------------------ live TV

    def live_get(self, path):
        u = self.need_user()
        if not u:
            return
        m = re.match(r"^/live/([0-9a-f]{12})/(index\.m3u8|p/([\w.=-]+))$", path)
        chan = live.channel(m.group(1)) if m else None
        if not chan or (chan.get("adult") and not u.get("adult")) or u.get("kids"):
            return self.send_body("Not found", status=404)
        url = chan["url"] if m.group(2) == "index.m3u8" else live.unpack(m.group(3))
        if not url:
            return self.send_body("Not found", status=404)
        try:
            resp = live.open_upstream(url, chan)
        except Exception:
            return self.send_body("The channel didn't answer.", status=502)
        with resp:
            if live.is_playlist(resp, resp.geturl()):
                text = resp.read(4 * 2**20).decode("utf-8", "replace")
                return self.send_body(live.rewrite_playlist(text, resp.geturl(), chan["id"]),
                                      "application/vnd.apple.mpegurl", headers={"Cache-Control": "no-cache"})
            if m.group(2) == "index.m3u8":
                # Not HLS (a raw MPEG-TS or MP4 feed): have ffmpeg repackage it as HLS.
                resp.close()
                if not media.tool("ffmpeg"):
                    return self.send_body("This channel needs ffmpeg on the server.", status=503)
                try:
                    sid = media.hls_start({"id": "live:" + chan["id"], "path": chan["url"], "title": chan["name"]},
                                          "remux", 0, u["name"], owner=self.owner())
                except (RuntimeError, OSError):
                    return self.send_body("The server is busy. Try again in a moment.", status=503)
                self.send_response(302)
                self.send_header("Location", "/media/hls/%s/index.m3u8" % sid)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", resp.headers.get("Content-Type") or "video/mp2t")
            if resp.headers.get("Content-Length"):
                self.send_header("Content-Length", resp.headers["Content-Length"])
            else:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    # ------------------------------------------------------------ media for signed-in users

    def media_get(self, path, qs):
        u = self.need_user()
        if not u:
            return
        h = re.match(r"^/media/hls/([0-9a-f]{20})/([\w.]+)$", path)
        if h:
            f = media.hls_file(h.group(1), h.group(2))
            if not f:
                return self.send_body("Not found", status=404)
            ctype = ("application/vnd.apple.mpegurl" if f.endswith(".m3u8") else "video/mp2t" if f.endswith(".ts")
                     else "video/mp4")
            with open(f, "rb") as fh:
                data = fh.read()
            if f.endswith(".m3u8"):   # start at the beginning, not the "live" end of a playlist still being written
                data = data.replace(b"#EXTM3U\n", b"#EXTM3U\n#EXT-X-START:TIME-OFFSET=0,PRECISE=YES\n", 1)
            return self.send_body(data, ctype, headers={"Cache-Control": "no-cache"})
        m = re.match(r"^/media/([^/]+)/(file|stream|travel\.mp4|preview\.mp4|subs/(\d+)\.vtt|trick\.json|trick/(\d{1,3})\.jpg)$", path)
        item = self.visible_item(m.group(1), u) if m else None
        if not item:
            return self.send_body("Not found", status=404)
        kind = m.group(2)
        if kind == "trick.json":
            info = trickplay.meta(item)
            if not info:
                trickplay.want(item)
            return self.json(info or {"pending": bool(config.get("trickplay"))})
        if kind == "preview.mp4":
            f = previews.for_request(item, hd=bool((qs.get("hd") or [""])[0]))
            return self.send_file(f, cache="private, max-age=604800") if f else self.send_body("Not ready", status=503)
        if kind.startswith("trick/"):
            f = trickplay.sheet(item, int(m.group(4)))
            return self.send_file(f, cache="private, max-age=604800") if f else self.send_body("Not found", status=404)
        if kind == "travel.mp4":                     # a travel copy, to keep on this device
            f = travel.copy_path(item)
            return self.send_file(f, download=download_name(item, ".mp4")) if f else self.send_body("Not ready", status=404)
        if kind == "file":
            if (qs.get("download") or [""])[0] == "1":
                return self.send_file(item["path"], download=download_name(item, os.path.splitext(item["path"])[1].lower()))
            if (qs.get("trailer") or [""])[0] != "1":         # a trailer on a title's page isn't "watching"
                media.note_direct(item, u["name"])
            return self.send_file(item["path"])
        if kind == "stream":
            mode = (qs.get("mode") or ["remux"])[0]
            mode = mode if mode in ("remux", "transcode", "audio") else "remux"
            start = float((qs.get("t") or ["0"])[0] or 0)
            if not media.tool("ffmpeg"):
                return self.error(503, "This server can't convert video yet (ffmpeg isn't installed).")
            audio = (qs.get("audio") or [""])[0]
            who = u["name"] + (" (trailer)" if (qs.get("trailer") or [""])[0] == "1" else "")
            return self.stream(item, mode, max(0.0, start), who, audio_index=int(audio) if audio.isdigit() else None,
                               max_height=int(qs["h"][0]) if (qs.get("h") or [""])[0] in ("480", "720", "1080") else None)
        tracks = media.subtitle_tracks(item, media.probe(item["path"]))
        n = int(m.group(3))
        if n >= len(tracks):
            return self.send_body("Not found", status=404)
        offset = float((qs.get("offset") or ["0"])[0] or 0)
        self.send_body(media.subtitle_vtt(item, tracks[n], offset), "text/vtt; charset=utf-8",
                       headers={"Cache-Control": "private, max-age=3600"})

    # ------------------------------------------------------------ API

    def api_get(self, path, qs):
        if path == "/api/session":
            u = self.user()
            return self.json({"name": config.get("name"), "version": __version__, "user": u, "theme": config.get("theme"),
                              "offline": net.offline_mode(),
                              "needs_setup": auth.user_count() == 0, "network": self.network(),
                              "remote": config.get("remote"), "guest_available": bool(self.guest_ok()),
                              "profiles": self.may_switch(u) and len(auth.profiles()),
                              "kids_profiles": bool(u and u.get("admin") and store.q1("SELECT 1 FROM users WHERE kids = 1"))})
        u = self.need_user(admin=path.startswith("/api/admin/"))
        if not u:
            return
        if path == "/api/profiles":
            if not self.may_switch(u):
                return self.error(403, "Switching profiles works at home, from a signed-in profile.")
            ps = auth.profiles()
            if u.get("kids"):                          # from a Kids profile every other one asks for its code
                ps = [dict(p, locked=p["locked"] or not p["kids"]) for p in ps]
            return self.json({"profiles": ps, "me": u["id"]})
        if path == "/api/library":
            if (qs.get("since") or [""])[0] == str(LIBRARY.generated) and LIBRARY.generated:
                return self.json({"same": True})              # the once-a-minute check: nothing new, nothing to send
            out = slim_library(u)
            out["reading"] = not LIBRARY.generated          # just started: the first read isn't done yet
            if u.get("admin"):
                out["places"] = [{"id": "", "name": "This computer", "connected": True}] + \
                    [{"id": p["id"], "name": p["name"], "connected": places.connected(p)} for p in places.extra()]
            out["likes"] = [r["item"] for r in store.q("SELECT item FROM likes WHERE user_id = ? ORDER BY at DESC", u["id"])
                            if u.get("adult") or not r["item"].startswith(("am:", "as:", "ae:", "ax:", "perf:"))]
            return self.json(out)
        if path.startswith("/api/live") and u.get("kids"):
            return self.error(403, "Live TV isn't on for this profile.")
        if path == "/api/live":
            return self.json(live.listing(u["id"], adult=u.get("adult")))
        if path == "/api/music":
            out = LIBRARY.music_public()
            out["likes"] = [r["item"] for r in store.q("SELECT item FROM music_likes WHERE user_id = ? ORDER BY at DESC", u["id"])]
            out["recent"] = [r["item"] for r in store.q("SELECT item FROM music_plays WHERE user_id = ? ORDER BY at DESC LIMIT 60",
                                                         u["id"])]
            return self.json(out)
        m = re.match(r"^/api/travel/(.+)$", path)
        if m:                                         # can this device keep this video as it is, or does it need a travel copy?
            item = self.visible_item(m.group(1), u)
            if not item or item["kind"] not in ("episode", "movie", "extra", "musicvideo"):
                return self.error(404, "That video isn't in the library any more.")
            caps = {k: (qs.get(k) or ["0"])[0] == "1" for k in ("mkv", "hevc", "ac3", "vp9")}
            info = media.probe(item["path"]) or {}
            st = travel.status(item)
            copy_size = st.pop("size", None)
            return self.json(dict(st, copy_size=copy_size, direct=media.plan(item, caps)["mode"] == "direct",
                                  size=item.get("size"), duration=info.get("duration"), ext=item.get("ext")))
        if path == "/api/screen/wait":             # this page, waiting to be told what to play (the phone remote)
            return self.json({"commands": screens.wait((qs.get("id") or [""])[0][:40], (qs.get("name") or [""])[0],
                                                       u["id"], (qs.get("tv") or [""])[0] == "1")})
        if path == "/api/screens":                 # this person's other open screens
            return self.json({"screens": screens.listing(u["id"], exclude=(qs.get("me") or [""])[0])})
        if path == "/api/progress":
            rows = store.q("SELECT item, t, d, done, at FROM progress WHERE user_id = ?", u["id"])
            return self.json({r["item"]: {"t": r["t"], "d": r["d"], "done": bool(r["done"]), "at": r["at"]} for r in rows})
        m = re.match(r"^/api/play/(.+)$", path)
        if m:
            item = self.visible_item(m.group(1), u)
            if not item:
                return self.error(404, "That video isn't in the library any more.")
            caps = {k: (qs.get(k) or ["0"])[0] == "1" for k in ("mkv", "hevc", "ac3", "vp9")}
            if item["kind"] == "track":
                direct = music.playable_directly(item) or not media.tool("ffmpeg")
                return self.json({"mode": "direct" if direct else "audio", "duration": item.get("duration"),
                                  "url": "/media/%s/%s" % (item["id"], "file" if direct else "stream?mode=audio"),
                                  "subtitles": []})
            p = media.plan(item, caps)
            trailer = (qs.get("trailer") or [""])[0] == "1"
            if item["kind"] == "episode" and not trailer:
                intros.want(item)
                trickplay.want(item)
            base = "/media/%s/" % item["id"]
            tracks = media.subtitle_tracks(item, p["info"])
            out = {"mode": p["mode"], "duration": p["duration"], "why": p.get("why") or [],
                   "audio": media.audio_tracks(p["info"]), "error": media.last_error(item["id"]),
                   "markers": intros.for_player(item["id"]),
                   "intro_status": "looking" if item["kind"] == "episode" and not intros.for_player(item["id"]) else None,
                   "url": base + ("file" if p["mode"] == "direct" else "stream?mode=" + p["mode"]),
                   "subtitles": [{"label": t["label"] or "Subtitles", "lang": t["lang"] or "und",
                                  "url": "%ssubs/%d.vtt" % (base, i)} for i, t in enumerate(tracks)]}
            if p["mode"] == "unsupported":
                out["message"] = ("This file needs converting to play here, and ffmpeg isn't installed on the "
                                  "server yet. An admin can install it from the Server page.")
            # A trailer on a title's page: the file as it is, or repackaged on the fly (cheap); converting it
            # would load a slow server for a few minutes of background, so the short preview clip plays instead.
            out["trailer"] = ("direct" if p["mode"] == "direct" else "stream" if p["mode"] == "remux" or
                              (p["mode"] == "transcode" and not machine.gentle() and not media.should_wait()) else "clip")
            return self.json(out)
        m = re.match(r"^/api/hls/(.+)$", path)
        if m:
            item = self.visible_item(m.group(1), u)
            if not item:
                return self.error(404, "That video isn't in the library any more.")
            if not media.tool("ffmpeg"):
                return self.error(503, "This server can't convert video yet (ffmpeg isn't installed).")
            mode = (qs.get("mode") or ["remux"])[0]
            try:
                sid = media.hls_start(item, mode if mode in ("remux", "transcode") else "remux",
                                      max(0.0, float((qs.get("t") or ["0"])[0] or 0)), u["name"],
                                      replace=(qs.get("replace") or [None])[0], owner=self.owner(),
                                      audio_index=int(qs["audio"][0]) if (qs.get("audio") or [""])[0].isdigit() else None,
                                      max_height=int(qs["h"][0]) if (qs.get("h") or [""])[0] in ("480", "720", "1080") else None)
            except RuntimeError:
                return self.error(503, "The server is busy converting other videos for other people. Try again in a moment.")
            except OSError as exc:
                return self.error(500, "ffmpeg couldn't start: %s" % exc)
            return self.json({"url": "/media/hls/%s/index.m3u8" % sid, "session": sid})
        if path == "/api/admin/status":
            return self.json(admin_status())
        if path == "/api/admin/convert":
            return self.json(optimize.status(LIBRARY))
        if path == "/api/admin/duplicates":
            return self.json({"groups": housekeeping.duplicates(LIBRARY)})
        if path == "/api/admin/upload/check":          # before sending a file: will it be taken?
            try:
                size = int((qs.get("size") or ["0"])[0])
            except ValueError:
                size = 0
            adult = (qs.get("adult") or [""])[0] == "1"
            if adult and not u.get("adult"):
                return self.error(403, "Switch the Adult section on for yourself first (Server, People).")
            problem = uploads.check(uploads.safe_name((qs.get("name") or [""])[0]), size, adult)
            return self.json({"ok": not problem, "problem": problem})
        if path == "/api/admin/update":
            return self.json(updater.status())
        if path == "/api/admin/intros":
            return self.json(intros.status(LIBRARY))
        if path == "/api/admin/storage":
            return self.json(places.status(LIBRARY))
        if path == "/api/admin/report":            # a text file to send when asking for help
            private = bool(u.get("adult")) and (qs.get("adult") or [""])[0] == "1"
            text = report.build(u["name"], include_private=private)
            store.log("settings", "%s downloaded a report%s" % (u["name"], " with Adult details" if private else ""))
            return self.send_body(text, headers={"Content-Disposition": 'attachment; filename="sofa-report-%s.txt"' % time.strftime("%Y-%m-%d-%H%M"),
                                                 "Cache-Control": "no-store"})
        if path == "/api/admin/missing":
            return self.json({"items": [m for m in LIBRARY.missing_details() if u.get("adult") or not m.get("adult")]})
        if path == "/api/admin/downloads":
            return self.json(fetch.status(viewer_adult=u.get("adult")))
        if path == "/api/admin/match":
            entry = LIBRARY.find((qs.get("id") or [""])[0])
            if not entry:
                return self.error(404, "That isn't in the library any more.")
            query = ((qs.get("q") or [""])[0] or entry.get("name") or entry.get("title") or "").strip()
            year = (qs.get("year") or [""])[0]
            try:
                if "seasons" in entry and not entry.get("adult"):
                    found = metadata.search_shows(query)
                else:
                    found = metadata.search_movies(query, int(year) if year.isdigit() else None, adult=entry.get("adult"))
            except Exception as exc:
                return self.error(502, "Couldn't reach the lookup service. Is this computer online? (%s)" % str(exc)[:80])
            return self.json({"query": query, "results": found, "current": metadata.override(entry["id"]),
                              "source": entry.get("source"), "keys": {"tmdb": bool(config.get("tmdb_api_key")),
                                                                     "tpdb": bool(config.get("theporndb_api_key"))}})
        self.error(404, "Unknown request.")

    def api_post(self, path, data):
        ip = self.client_ip()
        if path == "/api/setup":
            if auth.user_count() > 0:
                return self.error(409, "This server is already set up. Sign in instead.")
            if self.network() not in HOME_NETS:
                return self.error(403, "Set up Sofa from a device at home.")
            problem = auth.validate_new(data.get("name"), data.get("password"))
            if problem:
                return self.error(400, problem)
            user = auth.create_user(data["name"], data["password"], admin=True)
            store.log("account", "Created admin account \"%s\"" % user["name"])
            token = auth.start_session(user["id"], ip, self.headers.get("User-Agent"))
            return self.json({"ok": True}, headers={"Set-Cookie": self.session_cookie(token, auth.SESSION_DAYS * 86400)})
        if path == "/api/login":
            if auth.throttled(ip):
                return self.error(429, "Too many attempts. Wait 15 minutes and try again.")
            row = auth.login(data.get("name"), data.get("password"), ip)
            if not row:
                return self.error(401, "That name and password don't match.")
            token = auth.start_session(row["id"], ip, self.headers.get("User-Agent"))
            store.log("login", "%s signed in from %s" % (row["name"], self.network_label()), {"ip": ip})
            return self.json({"ok": True}, headers={"Set-Cookie": self.session_cookie(token, auth.SESSION_DAYS * 86400)})
        if path == "/api/profiles/switch":           # "Who's watching?": from one signed-in profile to another, at home
            u = self.user()
            if not self.may_switch(u):
                return self.error(403, "Switching profiles works at home, from a signed-in profile.")
            target = next((p for p in auth.profiles() if p["id"] == data.get("id")), None)
            if not target:
                return self.error(404, "That profile isn't there any more.")
            leaving_kids = u.get("kids") and not target["kids"]        # out of a Kids profile: always that profile's code
            if (target["locked"] or leaving_kids) and target["id"] != u["id"]:
                if auth.throttled(ip):
                    return self.error(429, "Too many tries. Wait 15 minutes and try again.")
                if not auth.check_code(target["id"], data.get("code")):
                    auth.record_failure(ip)
                    return self.error(403, "That PIN isn't right." if target["pin"] else "That password isn't right.")
            auth.end_session(self.token())
            token = auth.start_session(target["id"], ip, self.headers.get("User-Agent"))
            store.log("login", "%s is watching on %s" % (target["name"], self.network_label()), {"ip": ip})
            return self.json({"ok": True}, headers={"Set-Cookie": self.session_cookie(token, auth.SESSION_DAYS * 86400)})
        if path == "/api/profile":                    # your own avatar and PIN
            u = self.user()
            if not u or u.get("guest"):
                return self.error(403, "Sign in first.")
            try:
                if "pin" in data:
                    row = store.q1("SELECT pw FROM users WHERE id = ?", u["id"])
                    if not auth.check_password(str(data.get("password") or ""), row["pw"]):
                        return self.error(403, "Type your password to change the PIN.")
                auth.set_profile(u["id"], avatar=data.get("avatar"), pin=data.get("pin"))
            except (ValueError, TypeError) as exc:
                return self.error(400, str(exc))
            return self.json({"ok": True})
        if path == "/api/guest":
            if not self.guest_ok():
                return self.error(403, "Guest access works on the home Wi-Fi only.")
            user = auth.guest_user()
            token = auth.start_session(user["id"], ip, self.headers.get("User-Agent"))
            store.log("login", "A guest joined from %s" % ip)
            return self.json({"ok": True}, headers={"Set-Cookie": self.session_cookie(token, auth.GUEST_HOURS * 3600)})
        if path == "/api/logout":
            auth.end_session(self.token())
            return self.json({"ok": True}, headers={"Set-Cookie": self.session_cookie("", 0)})

        u = self.need_user(admin=path.startswith("/api/admin/"))
        if not u:
            return
        m = re.match(r"^/api/travel/(.+)$", path)
        if m:
            item = self.visible_item(m.group(1), u)
            if not item:
                return self.error(404, "That video isn't in the library any more.")
            travel.want(item)
            return self.json({"ok": True})
        if path == "/api/screen/state":
            screens.report(str(data.get("id") or "")[:40], u["id"], data.get("state") or {})
            return self.json({"ok": True})
        m = re.match(r"^/api/screens/([\w-]{1,40})$", path)
        if m:
            cmd = data.get("command") or {}
            if cmd.get("item") and not self.visible_item(cmd["item"], u):
                return self.error(404, "That video isn't in the library any more.")
            if not screens.send(m.group(1), u["id"], cmd, data.get("name")):
                return self.error(404, "That screen isn't open any more.")
            return self.json({"ok": True})
        m = re.match(r"^/api/progress/(.+)$", path)
        if m:
            item_id = m.group(1)
            if data.get("clear"):
                store.ex("DELETE FROM progress WHERE user_id = ? AND item = ?", u["id"], item_id)
            else:
                store.ex("INSERT OR REPLACE INTO progress (user_id, item, t, d, done, at) VALUES (?,?,?,?,?,?)",
                         u["id"], item_id, float(data.get("t") or 0), float(data.get("d") or 0),
                         1 if data.get("done") else 0, int(time.time() * 1000))
            return self.json({"ok": True})
        if path == "/api/admin/intros":
            intros.recheck()
            return self.json({"ok": True})
        if path == "/api/admin/relocate":            # an admin moves or deletes something that's out of place
            key, target = data.get("id") or "", data.get("target") or {}
            item, entry = LIBRARY.item(key), LIBRARY.find(key)
            thing = item or entry
            if not thing or (thing.get("adult") and not u.get("adult")):
                return self.error(404, "That isn't in the library any more.")
            if target.get("kind") == "adult" and not u.get("adult"):
                return self.error(403, "Switch the Adult section on for yourself first (Server, People).")
            try:
                if item:
                    message = organizer.relocate(item["path"], target, private=bool(item.get("adult")))
                elif entry.get("seasons") is not None and LIBRARY.dirs.get(key):
                    message = organizer.relocate_show(LIBRARY.dirs[key], target, private=bool(entry.get("adult")))
                else:
                    return self.error(400, "This can't be moved from here.")
            except ValueError as exc:
                return self.error(400, str(exc))
            except OSError as exc:
                return self.error(500, "Couldn't move it: %s" % (exc.strerror or exc))
            LIBRARY.drop(key)
            LIBRARY.scan("moved from the app", quick=True)
            return self.json({"ok": True, "message": message})
        if path == "/api/admin/cache":
            if data.get("free"):
                housekeeping.free_space()
            if data.get("retry_details"):
                n = housekeeping.retry_lookups()
                threading.Thread(target=LIBRARY.scan, args=("looking up details again",), daemon=True).start()
                return self.json({"ok": True, "forgotten": n})
            return self.json(dict(housekeeping.usage(max_age=0), ok=True))
        if path == "/api/admin/machine":              # test this computer's video conversion again
            threading.Thread(target=machine.measure, kwargs={"force": True}, daemon=True).start()
            return self.json({"ok": True})
        if path == "/api/admin/storage":              # drives: use one, stop using it, file new things there, move a title
            try:
                if data.get("add"):
                    a = data["add"]
                    places.add(a.get("path") or "", a.get("name"), bool(a.get("new_here")))
                    threading.Thread(target=LIBRARY.scan, args=("a drive was added",), daemon=True).start()
                if data.get("remove"):
                    places.remove(data["remove"])
                    threading.Thread(target=LIBRARY.scan, args=("a drive was removed",), daemon=True).start()
                if "new_to" in data:
                    places.set_target(data.get("new_to") or "")
                if data.get("move"):
                    m = data["move"]
                    entry = LIBRARY.find(m.get("id") or "")
                    folder = LIBRARY.dirs.get(m.get("id") or "")
                    if not entry or (entry.get("adult") and not u.get("adult")):
                        return self.error(404, "That isn't in the library any more.")
                    if not folder:
                        return self.error(400, "This movie isn't in a folder of its own, so it can't be moved yet.")
                    key = "adult" if entry.get("adult") else ("shows" if entry.get("seasons") is not None else "movies")
                    places.move(folder, key, m.get("to") or "", entry.get("name") or entry.get("title"), private=bool(entry.get("adult")))
            except ValueError as exc:
                return self.error(400, str(exc))
            return self.json(dict(places.status(LIBRARY), ok=True))
        if path == "/api/admin/deleted":
            if data.get("empty"):
                organizer.empty_deleted()
            return self.json(dict(organizer.deleted_summary(), ok=True))
        if path == "/api/admin/pictures":           # take new pictures from the videos: one title, or everything
            entry_id = data.get("id")
            if entry_id:
                entry = LIBRARY.find(entry_id)
                if not entry or (entry.get("adult") and not u.get("adult")):
                    return self.error(404, "That isn't in the library any more.")
            LIBRARY.new_pictures(entry_id)
            threading.Thread(target=LIBRARY.scan, args=("new pictures",), daemon=True).start()
            if entry_id and entry.get("adult"):
                store.log_private("settings", "%s asked for new pictures of a private video" % u["name"])
            else:
                store.log("settings", "%s asked for new pictures of %s" % (
                    u["name"], ("\"%s\"" % (entry.get("name") or entry.get("title"))) if entry_id else "the whole library"))
            return self.json({"ok": True})
        m = re.match(r"^/api/admin/markers/(.+)$", path)
        if m:
            item = LIBRARY.item(m.group(1))
            kind = data.get("kind")
            if not item or kind not in ("intro", "recap", "credits"):
                return self.error(400, "Unknown video or marker.")
            if data.get("clear"):
                intros.clear_marker(item["id"], kind)
            elif data.get("season"):
                try:
                    start, end = float(data["start"]), float(data["end"])
                except (KeyError, TypeError, ValueError):
                    return self.error(400, "Give a start and an end.")
                n = intros.set_for_season(LIBRARY, item, kind, start, end)
                return self.json({"ok": True, "episodes": n, "markers": intros.for_player(item["id"])})
            else:
                try:
                    start, end = float(data["start"]), float(data["end"])
                except (KeyError, TypeError, ValueError):
                    return self.error(400, "Give a start and an end.")
                if not 0 <= start < end:
                    return self.error(400, "The end has to come after the start.")
                intros.set_marker(item["id"], kind, start, end, "manual")
            return self.json({"ok": True, "markers": intros.for_player(item["id"])})
        m = re.match(r"^/api/like/(.{1,200})$", path)
        if m:
            key = m.group(1)
            item = LIBRARY.item(key) or LIBRARY.find(key)
            adultish = key.startswith("perf:") or bool(item and item.get("adult"))
            if (not item and not key.startswith(("perf:", "studio:"))) or (adultish and not u.get("adult")):
                return self.error(404, "That isn't in the library any more.")
            if data.get("on"):
                store.ex("INSERT OR REPLACE INTO likes (user_id, item, at) VALUES (?,?,?)", u["id"], key, int(time.time() * 1000))
            else:
                store.ex("DELETE FROM likes WHERE user_id = ? AND item = ?", u["id"], key)
            return self.json({"ok": True})
        if path == "/api/hls/stop":
            media.hls_stop_owner(self.owner())
            return self.json({"ok": True})
        if path.startswith("/api/live") and u.get("kids"):
            return self.error(403, "Live TV isn't on for this profile.")
        m = re.match(r"^/api/live/favorite/([0-9a-f]{12})$", path)
        if m:
            if data.get("on"):
                store.ex("INSERT OR IGNORE INTO live_favorites (user_id, channel) VALUES (?,?)", u["id"], m.group(1))
            else:
                store.ex("DELETE FROM live_favorites WHERE user_id = ? AND channel = ?", u["id"], m.group(1))
            return self.json({"ok": True})
        m = re.match(r"^/api/music/(like|played)/(.+)$", path)
        if m:
            item = LIBRARY.item(m.group(2))
            if not item or item["kind"] not in ("track", "musicvideo"):
                return self.error(404, "That song isn't in the library any more.")
            now = int(time.time() * 1000)
            if m.group(1) == "like":
                if data.get("on"):
                    store.ex("INSERT OR REPLACE INTO music_likes (user_id, item, at) VALUES (?,?,?)", u["id"], item["id"], now)
                else:
                    store.ex("DELETE FROM music_likes WHERE user_id = ? AND item = ?", u["id"], item["id"])
            else:
                store.ex("INSERT OR REPLACE INTO music_plays (user_id, item, at) VALUES (?,?,?)", u["id"], item["id"], now)
                store.ex("""DELETE FROM music_plays WHERE user_id = ? AND item NOT IN
                            (SELECT item FROM music_plays WHERE user_id = ? ORDER BY at DESC LIMIT 200)""", u["id"], u["id"])
            return self.json({"ok": True})
        if path == "/api/admin/guest/clear":
            auth.clear_guest()
            store.log("account", "%s cleared the guest history" % u["name"])
            return self.json({"ok": True})
        if path == "/api/admin/live":
            try:
                if data.get("add"):
                    live.add_playlist(data["add"].get("name") or "", data["add"].get("url") or "", bool(data["add"].get("adult")))
                    store.log("live", "%s added the channel list \"%s\"" % (u["name"], data["add"].get("name") or data["add"].get("url")))
                if data.get("remove"):
                    live.remove_playlist(data["remove"])
                    store.log("live", "%s removed a channel list" % u["name"])
            except ValueError as exc:
                return self.error(400, str(exc))
            count = live.refresh(force=bool(data.get("refresh") or data.get("add")))
            return self.json({"ok": True, "channels": count})
        if path == "/api/admin/backup":
            try:
                made = backup.make("requested by %s" % u["name"])
            except Exception as exc:
                return self.error(500, "The backup failed: %s" % exc)
            return self.json({"ok": True, "file": os.path.basename(made)})
        if path == "/api/admin/scan":
            LIBRARY.scan("requested by %s" % u["name"])
            return self.json({"ok": True, "library": LIBRARY.counts()})
        if path == "/api/admin/inbox":
            filed = organizer.process_inbox()
            return self.json({"ok": True, "filed": filed})
        if path == "/api/admin/users":
            problem = auth.validate_new(data.get("name"), data.get("password"))
            if problem:
                return self.error(400, problem)
            try:
                user = auth.create_user(data["name"], data["password"], admin=bool(data.get("admin")))
            except Exception:
                return self.error(409, "Someone already has that name.")
            if data.get("adult"):
                auth.set_adult(user["id"], True)
            store.log("account", "%s added %s \"%s\"" % (u["name"], "admin" if data.get("admin") else "viewer", user["name"]))
            return self.json({"ok": True})
        if path == "/api/admin/convert":
            if data.get("all"):
                n = optimize.enqueue(optimize.candidates(LIBRARY), "requested by %s" % u["name"])
                return self.json({"ok": True, "queued": n})
            if data.get("items"):
                items = [i for i in (LIBRARY.item(x) for x in data["items"]) if i]
                return self.json({"ok": True, "queued": optimize.enqueue(items, "requested by %s" % u["name"])})
            if data.get("retry"):
                optimize.retry(optimize.path_of(data["retry"]))
            if data.get("cancel"):
                optimize.cancel(optimize.path_of(data["cancel"]))
            if data.get("clear"):
                optimize.clear_finished()
            if data.get("redo_damaged"):
                optimize.damaged_redo()
            return self.json({"ok": True})
        if path == "/api/admin/downloads":
            try:
                if data.get("install_ytdlp"):
                    fetch.start_install()
                    return self.json({"ok": True, "installing": True})
                if data.get("add"):
                    add = data["add"]
                    if add.get("adult") and not u.get("adult"):
                        return self.error(403, "Switch the Adult section on for yourself first (Server, People).")
                    fetch.add(add.get("url"), bool(add.get("adult")), bool(add.get("playlist")))
                    if not fetch.tool():
                        return self.json({"ok": True, "note": "Queued. Install yt-dlp below so Sofa can start downloading."})
            except ValueError as exc:
                return self.error(400, str(exc))
            except Exception as exc:
                return self.error(502, "Couldn't install yt-dlp: %s" % str(exc)[:150])
            if data.get("retry"):
                fetch.retry(data["retry"])
            if data.get("cancel"):
                fetch.cancel(data["cancel"])
            if data.get("clear"):
                fetch.clear_finished()
            return self.json({"ok": True})
        if path == "/api/admin/update":
            if data.get("install"):
                if not updater.start_update():
                    return self.error(409, "An update is already running.")
                store.log("update", "%s started an update" % u["name"])
                return self.json({"ok": True, "status": updater.status()})
            return self.json(updater.check(force=True))
        if path == "/api/admin/match":
            entry = LIBRARY.find(data.get("id") or "")
            if not entry:
                return self.error(404, "That isn't in the library any more.")
            if data.get("clear"):
                choice = None
            elif data.get("none"):
                choice = {"none": True}
            elif data.get("pick"):
                src, sid = data["pick"].get("source"), data["pick"].get("id")
                if src not in ("tvmaze", "tmdb", "itunes", "tpdb") or not str(sid).replace("-", "").isalnum():
                    return self.error(400, "Pick one of the results.")
                choice = {src: sid}
            elif (data.get("title") or "").strip():
                choice = {"title": data["title"].strip()[:120]}
                if str(data.get("year") or "").isdigit():
                    choice["year"] = int(data["year"])
            else:
                return self.error(400, "Pick a result, or type a title.")
            metadata.set_override(entry["id"], choice)
            folder = LIBRARY.dirs.get(entry["id"])
            if folder and not data.get("keep_art"):
                for kind in ("poster", "backdrop"):
                    old = LIBRARY.find_art(folder, kind)
                    if old:
                        os.replace(old, os.path.splitext(old)[0] + ".before-fix" + os.path.splitext(old)[1])
            if entry.get("adult"):
                store.log_private("settings", "%s fixed the details of a private video" % u["name"])
            else:
                store.log("settings", "%s fixed the details for \"%s\"" % (u["name"], entry.get("name") or entry.get("title")))
            threading.Thread(target=LIBRARY.scan, args=("details fixed",), daemon=True).start()
            return self.json({"ok": True})
        m = re.match(r"^/api/admin/users/(\d+)/kids$", path)
        if m:
            target = store.q1("SELECT name, admin FROM users WHERE id = ?", int(m.group(1)))
            if target and target["admin"] and data.get("on"):
                return self.error(400, "An admin's profile can't be a Kids profile.")
            auth.set_kids(int(m.group(1)), bool(data.get("on")))
            store.log("account", "%s made \"%s\" %s" % (u["name"], target["name"] if target else "?",
                                                         "a Kids profile" if data.get("on") else "an ordinary profile"))
            return self.json({"ok": True})
        if path == "/api/admin/kids":                # allow or block one show or movie for Kids profiles
            entry = LIBRARY.find(str(data.get("id") or ""))
            if not entry or entry.get("adult"):
                return self.error(404, "That isn't in the library any more.")
            allow = data.get("allow")
            kids.choose(entry["id"], None if allow is None else bool(allow))
            return self.json({"ok": True})
        m = re.match(r"^/api/admin/users/(\d+)/adult$", path)
        if m:
            auth.set_adult(int(m.group(1)), bool(data.get("on")))
            target = store.q1("SELECT name FROM users WHERE id = ?", int(m.group(1)))
            store.log("account", "%s %s the Adult section for \"%s\"" % (
                u["name"], "opened" if data.get("on") else "closed", target["name"] if target else "?"))
            return self.json({"ok": True})
        m = re.match(r"^/api/admin/users/(\d+)/(password|delete)$", path)
        if m:
            uid = int(m.group(1))
            target = store.q1("SELECT id, name, admin FROM users WHERE id = ?", uid)
            if not target:
                return self.error(404, "No such account.")
            if m.group(2) == "password":
                if len(data.get("password") or "") < 8:
                    return self.error(400, "Use a password of at least 8 characters.")
                auth.set_password(uid, data["password"])
                store.log("account", "%s changed the password for \"%s\"" % (u["name"], target["name"]))
                return self.json({"ok": True})
            if uid == u["id"]:
                return self.error(400, "You can't remove your own account.")
            if target["admin"] and store.q1("SELECT COUNT(*) AS n FROM users WHERE admin = 1")["n"] <= 1:
                return self.error(400, "Keep at least one admin.")
            auth.delete_user(uid)
            store.log("account", "%s removed \"%s\"" % (u["name"], target["name"]))
            return self.json({"ok": True})
        if path == "/api/admin/settings":
            allowed = {k: data[k] for k in ("name", "dlna", "tvmaze", "tmdb_api_key", "theporndb_api_key", "max_transcodes",
                                            "guest_access", "auto_convert", "keep_originals", "tidy_library",
                                            "free_movie_lookup", "theme", "detect_intros", "trickplay", "previews",
                                            "ytdlp_cookies", "gentle", "quiet_hours", "offline", "no_logs") if k in data}
            if "gentle" in allowed and allowed["gentle"] not in (True, False, "auto"):
                allowed.pop("gentle")
            if "quiet_hours" in allowed and not re.match(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$", str(allowed["quiet_hours"])):
                return self.error(400, "Quiet hours look like 01:00-07:00.")
            if "ytdlp_cookies" in allowed and allowed["ytdlp_cookies"] not in fetch.BROWSERS + ("file", ""):
                allowed.pop("ytdlp_cookies")
            if "name" in allowed:
                allowed["name"] = str(allowed["name"]).strip()[:40] or "Sofa"
            for k in ("dlna", "tvmaze", "guest_access", "auto_convert", "keep_originals", "tidy_library", "free_movie_lookup",
                      "detect_intros", "trickplay", "previews", "offline", "no_logs"):
                if k in allowed:
                    allowed[k] = bool(allowed[k])
            for k in ("tmdb_api_key", "theporndb_api_key"):
                if k in allowed:
                    allowed[k] = re.sub(r"[^\w.\-|]", "", str(allowed[k]))[:400]
            if "max_transcodes" in allowed:
                allowed["max_transcodes"] = max(1, min(8, int(allowed["max_transcodes"] or 1)))
            if "theme" in allowed and allowed["theme"] not in THEMES:
                allowed.pop("theme")
            if any(k in allowed for k in ("tmdb_api_key", "theporndb_api_key", "free_movie_lookup")):
                metadata.forget("movie2-")
                metadata.forget("adult-")
                threading.Thread(target=LIBRARY.scan, args=("lookup settings changed",), daemon=True).start()
            if allowed.get("auto_convert"):
                threading.Thread(target=optimize.auto_enqueue, args=(LIBRARY,), daemon=True).start()
            if allowed.get("offline") is False and net.offline_mode():
                threading.Thread(target=LIBRARY.scan, args=("back online",), daemon=True).start()   # look up what was missed
            config.update(allowed)
            store.log("settings", "%s changed settings: %s" % (u["name"], ", ".join(sorted(allowed))))
            return self.json({"ok": True, "settings": public_settings()})
        if path == "/api/admin/duplicates":          # keep the best copy, the others to Deleted
            keys = None if data.get("all") else [str(k) for k in data.get("keys") or []]
            n, freed = housekeeping.drop_duplicates(LIBRARY, keys)
            if n:
                threading.Thread(target=LIBRARY.scan, args=("duplicates removed",), daemon=True).start()
            return self.json({"ok": True, "copies": n, "freed": freed})
        if path == "/api/admin/privacy":
            if data.get("wipe"):                  # erase every log, here and in the backups
                store.wipe_logs()
                cleaned = backup.scrub_logs()
                if not store.no_logs():
                    store.log("settings", "%s wiped all logs" % u["name"])
                return self.json({"ok": True, "backups": cleaned})
            return self.error(400, "Nothing to do.")
        self.error(404, "Unknown request.")

    def visible_item(self, item_id, user):
        """A library item this person may play (adult items only for people allowed to see them)."""
        item = LIBRARY.item(item_id)
        if not item or (item.get("adult") and not (user or {}).get("adult")):
            return None
        if (user or {}).get("kids") and item.get("kind") in ("episode", "movie", "extra") \
                and not kids.allowed(LIBRARY.find(item.get("show_id") or item["id"])):   # music is fine
            return None
        return item

    def network_label(self):
        return {"local": "this computer", "lan": "the home network", "tailnet": "Tailscale",
                "internet": "the internet"}[self.network()]


THEMES = ("midnight", "cinema", "ocean", "forest", "grape", "oled")


def download_name(item, ext):
    """A tidy file name for a video saved to a device: "Heat (1995).mp4", "The Sopranos S01E01 Pilot.mkv"."""
    if item["kind"] == "episode":
        show = LIBRARY.find(item.get("show_id")) or {}
        name = "%s S%02dE%02d%s" % (show.get("name") or item.get("show_name") or "", item["s"], item["e"],
                                    " " + item["title"] if item.get("title") else "")
    else:
        entry = LIBRARY.find(item["id"]) or {}
        title = entry.get("title") or item.get("title") or os.path.splitext(os.path.basename(item["path"]))[0]
        name = "%s (%s)" % (title, entry["year"]) if entry.get("year") else title
    return re.sub(r'[\x00-\x1f/\\:*?"<>|]+', " ", name).strip()[:150] + ext


def public_settings():
    s = config.all_settings()
    for k in ("tmdb_api_key", "theporndb_api_key"):
        s[k] = "set" if s.get(k) else ""
    return s


def admin_status():
    shows_root = config.path("shows")
    try:
        du = shutil.disk_usage(shows_root)
        disk = {"free": du.free, "total": du.total}
    except OSError:
        disk = None
    return {
        "server": {"name": config.get("name"), "version": __version__, "started": int(STARTED),
                   "host": platform.node(), "python": platform.python_version(), "ffmpeg": media.ffmpeg_version(),
                   "port": config.get("port"), "lan": dlna.lan_addresses(), "tailscale": dlna.tailscale_addresses(),
                   "remote": config.get("remote"), "dlna": config.get("dlna")},
        "library": dict(LIBRARY.counts(), generated=LIBRARY.generated, scanning=LIBRARY.scanning,
                        scan_seconds=LIBRARY.last_scan_seconds, disk=disk, missing=len(LIBRARY.missing_details()),
                        folders={k: config.path(k).replace(os.path.expanduser("~"), "~", 1)
                                 for k in ("shows", "movies", "music", "musicvideos", "adult", "inbox", "review",
                                           "originals")},
                        deleted=organizer.deleted_summary(), previews=previews.status(LIBRARY),
                        deleted_folder=organizer.deleted_root().replace(os.path.expanduser("~"), "~", 1),
                        cache=housekeeping.usage()),
        "internet_problem": net.last_error.get("message") if time.time() - net.last_error.get("at", 0) < 86400 else None,
        "privacy": {"no_logs": store.no_logs(), "offline": net.offline_mode(), "online": net.online(),
                    "problems_unlogged": store.problems_unlogged[0]},
        "machine": machine.status(),
        "convert": optimize.status(),
        "update": updater.status(),
        "encoder": "Apple hardware (VideoToolbox)" if media.hardware_encoder() else
                   ("x264 (software)" if "libx264" in media.encoders() else None),
        "streams": media.active_streams(),
        "inbox": organizer.pending(),
        "review": store.recent_activity(20, kinds={"review"}),
        "activity": store.recent_activity(150),
        "users": auth.list_users(),
        "settings": public_settings(),
        "backups": [{k: b[k] for k in ("name", "size", "made")} for b in backup.listing()[:5]],
        "guest": {"enabled": config.get("guest_access"),
                  "links": ["http://%s:%d/guest" % (ip, config.get("port")) for ip in dlna.lan_addresses()]},
        "backup_folder": backup.folder().replace(os.path.expanduser("~"), "~", 1),
    }


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)):
            return                      # the device went away mid-answer (a closed tab, a TV turned off): nothing wrong here
        super().handle_error(request, client_address)


_slim = {}
_slim_lock = threading.Lock()


def slim_library(u):
    """The library as the web app needs it: no empty fields, no file details for non-admins, episodes
    without their show's name and id (the app knows which show they're in). Made once per library read."""
    key = (LIBRARY.generated, bool(u.get("adult")), bool(u.get("admin")), bool(u.get("kids")), kids.version[0])
    with _slim_lock:
        if key in _slim:
            return dict(_slim[key])
    admin = bool(u.get("admin"))

    def clean(d, drop=()):
        return {k: v for k, v in d.items() if not (v is None or v is False or (isinstance(v, (str, list)) and not v))
                and k not in drop and (admin or k != "file")}

    def show(s):
        return dict(clean(s, ("seasons", "extras")),
                    seasons=[dict(clean(se, ("episodes",)), n=se["n"], episodes=[clean(e, ("show_id", "show_name", "ext", "size", "adult"))
                                                                                  for e in se["episodes"]]) for se in s["seasons"]],
                    extras=[clean(x, ("show_id", "show_name", "ext", "size", "adult")) for x in s["extras"]])
    lib = LIBRARY.public(adult=u.get("adult"))
    picked = kids.choices()
    shows, movies = lib["shows"], lib["movies"]
    if u.get("kids"):                              # a Kids profile: family titles only
        shows = [s for s in shows if kids.allowed(s, picked)]
        movies = [m for m in movies if kids.allowed(m, picked)]
    out = {"generated": lib["generated"], "shows": [show(s) for s in shows],
           "movies": [clean(m, ("ext", "size")) for m in movies]}
    if admin:                                      # what Kids profiles see, for the "For kids" button
        out["for_kids"] = [x["id"] for x in shows + movies if kids.allowed(x, picked)]
        out["kids_choices"] = picked
    if "adult" in lib:
        out["adult"] = dict(lib["adult"], shows=[show(s) for s in lib["adult"]["shows"]],
                            movies=[clean(m, ("ext", "size")) for m in lib["adult"]["movies"]])
    with _slim_lock:
        for k in [k for k in _slim if k[0] != LIBRARY.generated]:
            del _slim[k]
        _slim[key] = out
    return dict(out)


def serve():
    try:
        httpd = Server(("0.0.0.0", config.get("port")), Handler)
    except OSError as exc:
        print("Can't answer on port %d (%s). Is another copy of Sofa, or another program, using it?"
              % (config.get("port"), exc), flush=True)
        raise
    try:
        httpd.serve_forever()
    finally:
        dlna.notify("ssdp:byebye")
