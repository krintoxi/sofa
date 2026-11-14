"""A stand-in network tuner: what an HDHomeRun answers, on this computer, for the tests.

- Discovery: a UDP socket that answers SiliconDust's discovery packet with its id, tuner count, base and lineup URLs.
- `discover.json` and `lineup.json` over http, with channels in MPEG-2 and H.264, one copy-protected, one that
  points off the home network.
- A channel's address streams a real MPEG-TS clip (made with ffmpeg), as fast as it's read. It has as many tuners
  as it says: one more stream at once is refused with 503, as the box refuses it. `drop_after` bytes, once: the
  stream breaks off, as a weak signal makes it.

It proves Sofa's side of the conversation. No real tuner has heard it yet.
"""
import json
import os
import socket
import struct
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sofa import tuners

DEVICE = 0x1050A1B2


class Tuner:
    def __init__(self, folder, ffmpeg, count=2, seconds=30):
        self.count, self.open, self.drop_after, self.lock = count, 0, None, threading.Lock()
        self.clip = os.path.join(folder, "channel.ts")
        if not os.path.exists(self.clip):
            subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi",
                            "-i", "sine=frequency=440", "-t", str(seconds), "-c:v", "mpeg2video", "-q:v", "6", "-c:a", "mp2",
                            "-f", "mpegts", self.clip], check=True)
        me = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send_json(self, data):
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/discover.json":
                    return self.send_json({"FriendlyName": "Antenna tuner", "ModelNumber": "STAND-IN", "DeviceID": "%08X" % DEVICE,
                                           "TunerCount": me.count, "BaseURL": me.base, "LineupURL": me.base + "/lineup.json"})
                if self.path == "/lineup.json":
                    return self.send_json([
                        {"GuideNumber": "5.1", "GuideName": "KSTN", "VideoCodec": "MPEG2", "AudioCodec": "AC3", "HD": 1, "URL": me.base + "/auto/v5.1"},
                        {"GuideNumber": "2.1", "GuideName": "Channel Two", "VideoCodec": "MPEG2", "AudioCodec": "AC3", "URL": me.base + "/auto/v2.1"},
                        {"GuideNumber": "11.3", "GuideName": "News Now", "VideoCodec": "H264", "AudioCodec": "AAC", "URL": me.base + "/auto/v11.3"},
                        {"GuideNumber": "9.1", "GuideName": "Locked", "DRM": 1, "URL": me.base + "/auto/v9.1"},
                        {"GuideNumber": "12.1", "GuideName": "Elsewhere", "URL": "http://8.8.8.8/auto/v12.1"},
                    ])
                if self.path.startswith("/auto/v"):
                    with me.lock:
                        if me.open >= me.count:
                            self.send_response(503)
                            self.send_header("X-HDHomeRun-Error", "805 All Tuners In Use")
                            self.end_headers()
                            return
                        me.open += 1
                        cut, me.drop_after = me.drop_after, None
                    try:
                        self.send_response(200)
                        self.send_header("Content-Type", "video/mp2t")
                        self.end_headers()
                        sent = 0
                        with open(me.clip, "rb") as f:
                            while True:
                                chunk = f.read(188 * 64)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                sent += len(chunk)
                                if cut and sent >= cut:
                                    self.close_connection = True
                                    break
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    finally:
                        with me.lock:
                            me.open -= 1
                    return
                self.send_response(404)
                self.end_headers()

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = "http://127.0.0.1:%d" % self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.udp_port = self.udp.getsockname()[1]
        threading.Thread(target=self._answer, daemon=True).start()

    def _answer(self):
        while True:
            try:
                data, peer = self.udp.recvfrom(2048)
            except OSError:
                return
            got = tuners.unpack(data)
            if not got or got[0] != tuners.REQUEST:
                continue
            reply = tuners.packet(tuners.REPLY, [(tuners.TAG_TYPE, struct.pack(">I", tuners.TUNER)),
                                                 (tuners.TAG_ID, struct.pack(">I", DEVICE)),
                                                 (tuners.TAG_TUNERS, bytes([self.count])),
                                                 (tuners.TAG_BASE, self.base.encode()),
                                                 (tuners.TAG_LINEUP, (self.base + "/lineup.json").encode())])
            try:
                self.udp.sendto(reply, peer)
            except OSError:
                pass

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.udp.close()
