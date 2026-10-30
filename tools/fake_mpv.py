#!/usr/bin/env python3
"""A stand-in for mpv: the Sofa box agent's previews and tests use it where mpv isn't installed.

It shows nothing. It answers mpv's JSON control socket the way the agent uses it (the position moving
on with the clock, pause, seek, quit), and it fetches the start of the video with the same headers
mpv would, so a test can see the box asked Sofa properly. FAKE_MPV_LOG names a file for what it did.
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.request


def main(argv):
    opts, url = {}, None
    for a in argv:
        if a.startswith("--"):
            k, _, v = a[2:].partition("=")
            opts[k] = v
        else:
            url = a
    log = os.environ.get("FAKE_MPV_LOG")

    def note(**kw):
        if log:
            with open(log, "a") as f:
                f.write(json.dumps(kw) + "\n")
    st = {"pos": float(opts.get("start") or 0), "at": time.time(), "paused": False, "quit": False}
    duration = float(os.environ.get("FAKE_MPV_DURATION") or 0) or None

    def pos():
        return st["pos"] if st["paused"] else st["pos"] + (time.time() - st["at"])

    def set_pos(p):
        st["pos"], st["at"] = max(0.0, p), time.time()

    if url and url.startswith("http"):
        headers = {}
        for h in (opts.get("http-header-fields") or "").split(","):
            k, _, v = h.partition(":")
            if k.strip():
                headers[k.strip()] = v.strip().replace("%2C", ",")
        try:
            req = urllib.request.Request(url, headers=dict(headers, Range="bytes=0-1023"))
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=20) as r:
                r.read(1024)
                note(fetched=url, status=r.status, cookie="Cookie" in headers)
        except Exception as exc:
            note(fetched=url, error=str(exc)[:200])
            print("Failed to open %s." % url, file=sys.stderr)
            return 2
    note(started=url, start=st["pos"], args=argv)

    path = opts.get("input-ipc-server")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(8)
    srv.settimeout(0.2)

    def answer(conn):
        buf = b""
        with conn:
            while not st["quit"]:
                try:
                    part = conn.recv(4096)
                except OSError:
                    return
                if not part:
                    return
                buf += part
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    cmd, data = msg.get("command") or [], None
                    name = cmd[0] if cmd else ""
                    if name == "get_property":
                        data = {"time-pos": pos(), "duration": duration, "pause": st["paused"], "frame-drop-count": 0,
                                "decoder-frame-drop-count": 0, "container-fps": 25.0}.get(cmd[1])
                    elif name == "set_property" and cmd[1] == "pause":
                        set_pos(pos())
                        st["paused"] = bool(cmd[2])
                    elif name == "cycle" and cmd[1:] == ["pause"]:
                        set_pos(pos())
                        st["paused"] = not st["paused"]
                    elif name == "seek":
                        set_pos(float(cmd[1]) if len(cmd) > 2 and cmd[2] == "absolute" else pos() + float(cmd[1]))
                    elif name == "quit":
                        st["quit"] = True
                    note(command=cmd)
                    try:
                        conn.sendall((json.dumps({"data": data, "request_id": msg.get("request_id"), "error": "success"}) + "\n").encode())
                    except OSError:
                        return

    while not st["quit"]:
        if duration and pos() >= duration:
            break
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        threading.Thread(target=answer, args=(conn,), daemon=True).start()
    srv.close()
    note(ended=pos())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
