"""HTTP: the web app, its JSON API, media streaming, artwork and DLNA."""
import email.utils
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
from urllib.parse import parse_qs, unquote, urlsplit

import threading

from . import (__version__, artwork, auth, backup, config, dlna, fetch, intros, live, media, metadata, music, optimize,
               organizer, store, trickplay, updater)
from .library import LIBRARY

CLIENT_DIR = os.path.join(config.APP_DIR, "client")
STARTED = time.time()
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css",
        ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml", ".webp": "image/webp", ".vtt": "text/vtt; charset=utf-8", ".ico": "image/x-icon",
        ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
        ".webm": "video/webm", ".avi": "video/x-msvideo", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
        ".flac": "audio/flac", ".wav": "audio/wav", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
        ".wma": "audio/x-ms-wma", ".aif": "audio/aiff", ".aiff": "audio/aiff", ".alac": "audio/mp4"}
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
        path = urlsplit(self.path).path
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
        data = self.body_json()
        if data is None:
            return self.error(400, "Couldn't read the request.")
        self.api_post(path, data)

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
        self.send_body(data, MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream"),
                       headers={"Cache-Control": "no-cache"})

    def art(self, rest, qs):
        if not self.user() and self.network() not in HOME_NETS:   # TVs fetch artwork without signing in
            return self.error(401, "Sign in to continue.")
        if rest.startswith("adult/") and not (self.user() or {}).get("adult"):
            return self.send_body("Not found", status=404)
        full = artwork.file_for("/art/" + rest)
        if not full:
            return self.send_body("Not found", status=404)
        width = (qs.get("w") or [""])[0]
        if width.isdigit():
            full = artwork.resized(full, int(width))
        self.send_file(full, cache="private, max-age=604800")

    def send_file(self, full, cache=None, dlna_headers=False):
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

    def stream(self, item, mode, start, who, dlna_headers=False, audio_index=None):
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
            media.run_stream(item, mode, start, info, self.wfile, who, fmt, owner=self.owner(), audio_index=audio_index)
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
        if not chan or (chan.get("adult") and not u.get("adult")):
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
        m = re.match(r"^/media/([^/]+)/(file|stream|subs/(\d+)\.vtt|trick\.json|trick/(\d{1,3})\.jpg)$", path)
        item = self.visible_item(m.group(1), u) if m else None
        if not item:
            return self.send_body("Not found", status=404)
        kind = m.group(2)
        if kind == "trick.json":
            info = trickplay.meta(item)
            if not info:
                trickplay.want(item)
            return self.json(info or {"pending": bool(config.get("trickplay"))})
        if kind.startswith("trick/"):
            f = trickplay.sheet(item, int(m.group(4)))
            return self.send_file(f, cache="private, max-age=604800") if f else self.send_body("Not found", status=404)
        if kind == "file":
            media.note_direct(item, u["name"])
            return self.send_file(item["path"])
        if kind == "stream":
            mode = (qs.get("mode") or ["remux"])[0]
            mode = mode if mode in ("remux", "transcode", "audio") else "remux"
            start = float((qs.get("t") or ["0"])[0] or 0)
            if not media.tool("ffmpeg"):
                return self.error(503, "This server can't convert video yet (ffmpeg isn't installed).")
            audio = (qs.get("audio") or [""])[0]
            return self.stream(item, mode, max(0.0, start), u["name"], audio_index=int(audio) if audio.isdigit() else None)
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
                              "needs_setup": auth.user_count() == 0, "network": self.network(),
                              "remote": config.get("remote"), "guest_available": bool(self.guest_ok())})
        u = self.need_user(admin=path.startswith("/api/admin/"))
        if not u:
            return
        if path == "/api/library":
            out = LIBRARY.public(adult=u.get("adult"))
            out["likes"] = [r["item"] for r in store.q("SELECT item FROM likes WHERE user_id = ? ORDER BY at DESC", u["id"])
                            if u.get("adult") or not r["item"].startswith(("am:", "as:", "ae:", "ax:", "perf:"))]
            return self.json(out)
        if path == "/api/live":
            return self.json(live.listing(u["id"], adult=u.get("adult")))
        if path == "/api/music":
            out = LIBRARY.music_public()
            out["likes"] = [r["item"] for r in store.q("SELECT item FROM music_likes WHERE user_id = ? ORDER BY at DESC", u["id"])]
            out["recent"] = [r["item"] for r in store.q("SELECT item FROM music_plays WHERE user_id = ? ORDER BY at DESC LIMIT 60",
                                                         u["id"])]
            return self.json(out)
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
            if item["kind"] == "episode":
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
                                      audio_index=int(qs["audio"][0]) if (qs.get("audio") or [""])[0].isdigit() else None)
            except RuntimeError:
                return self.error(503, "The server is busy converting other videos for other people. Try again in a moment.")
            except OSError as exc:
                return self.error(500, "ffmpeg couldn't start: %s" % exc)
            return self.json({"url": "/media/hls/%s/index.m3u8" % sid, "session": sid})
        if path == "/api/admin/status":
            return self.json(admin_status())
        if path == "/api/admin/convert":
            return self.json(optimize.status(LIBRARY))
        if path == "/api/admin/update":
            return self.json(updater.status())
        if path == "/api/admin/intros":
            return self.json(intros.status(LIBRARY))
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
            return self.json({"ok": True})
        if path == "/api/admin/downloads":
            try:
                if data.get("install_ytdlp"):
                    return self.json({"ok": True, "version": fetch.install()})
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
                                            "free_movie_lookup", "theme", "detect_intros", "trickplay") if k in data}
            if "name" in allowed:
                allowed["name"] = str(allowed["name"]).strip()[:40] or "Sofa"
            for k in ("dlna", "tvmaze", "guest_access", "auto_convert", "keep_originals", "tidy_library", "free_movie_lookup",
                      "detect_intros", "trickplay"):
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
            config.update(allowed)
            store.log("settings", "%s changed settings: %s" % (u["name"], ", ".join(sorted(allowed))))
            return self.json({"ok": True, "settings": public_settings()})
        self.error(404, "Unknown request.")

    def visible_item(self, item_id, user):
        """A library item this person may play (adult items only for people allowed to see them)."""
        item = LIBRARY.item(item_id)
        if not item or (item.get("adult") and not (user or {}).get("adult")):
            return None
        return item

    def network_label(self):
        return {"local": "this computer", "lan": "the home network", "tailnet": "Tailscale",
                "internet": "the internet"}[self.network()]


THEMES = ("midnight", "cinema", "ocean", "forest", "grape", "oled")


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
                                           "originals")}),
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


def serve():
    httpd = Server(("0.0.0.0", config.get("port")), Handler)
    try:
        httpd.serve_forever()
    finally:
        dlna.notify("ssdp:byebye")
