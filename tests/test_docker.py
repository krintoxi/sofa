"""Sofa in a container (Dockerfile, compose.yml): the first start points the library at /media, and Server → Updates
says to pull a new image instead of swapping files in place."""
import json
import os
import re
import stat
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import auth, config, store, updater, web
from tests.test_server import Client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = "ghcr.io/krintoxi/sofa"


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class TheImage(unittest.TestCase):
    def test_the_files_agree(self):
        """The Dockerfile, compose.yml, the entrypoint and the workflow name the same image, data folder and port."""
        docker, compose, flow = read("Dockerfile"), read("compose.yml"), read(".github/workflows/docker-image.yml")
        self.assertIn("ENV SOFA_DATA=/data", docker)
        self.assertIn("SOFA_CONTAINER=" + IMAGE, docker)
        self.assertNotIn("USER root", docker)
        entry = read(os.path.join("deploy", "docker", "entrypoint.sh"))
        self.assertIn('exec setpriv --reuid="$PUID" --regid="$PGID"', entry)   # Sofa itself never runs as root
        # The graphics chip: the render nodes' own groups are joined (never root's), and nothing else changes.
        self.assertIn('for node in /dev/dri/renderD* /dev/dri/card*; do', entry)
        self.assertIn('[ "$gid" = "0" ] && continue', entry)
        self.assertIn('--groups="$groups"', entry)
        self.assertIn('--clear-groups', entry)                                 # no device passed in: no groups, as before
        self.assertIn("NVIDIA_DRIVER_CAPABILITIES=compute,video,utility", docker)
        self.assertIn("intel-media-va-driver mesa-va-drivers", docker)
        self.assertRegex(compose, r"(?m)^    # devices:\n    #   - /dev/dri:/dev/dri$")     # there, behind a "#": off until wanted
        self.assertRegex(compose, r"(?m)^    # gpus: all$")
        self.assertNotRegex(compose, r"(?m)^    (devices|gpus):")
        self.assertIn("PUID: ${PUID:-1000}", compose)
        self.assertRegex(docker, r"HEALTHCHECK .*\n.*/api/info")
        self.assertIn('ENTRYPOINT ["/opt/sofa/deploy/docker/entrypoint.sh"]', docker)
        self.assertIn("image: %s:latest" % IMAGE, compose)
        self.assertIn("network_mode: host", compose)                 # SSDP, Bonjour and "home network only" need the LAN
        self.assertIn("./data:/data", compose)
        self.assertIn("./media:/media", compose)
        self.assertIn(IMAGE + ":latest", flow)
        self.assertIn("secrets.GITHUB_TOKEN", flow)
        self.assertNotIn("secrets.DOCKER", flow)                       # no secrets beyond GitHub's own token
        ignored = read(".dockerignore").split()
        for name in ("data/", "tests/", ".git", "docs/"):
            self.assertIn(name, ignored)
        self.assertIn("deploy", updater.CODE)                          # the entrypoint comes along with an update

    def test_first_start_points_the_library_at_media(self):
        """Without a config.json the entrypoint writes one for /media and starts `sofa.py serve`; with one, it's left
        exactly as it is."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", tmp]))
        fake = os.path.join(tmp, "bin")
        os.makedirs(fake)
        with open(os.path.join(fake, "python3"), "w") as f:            # stands in for Python: records what it was asked
            f.write('#!/bin/sh\nprintf "%%s\\n" "$@" > "%s"\n' % os.path.join(tmp, "called"))
        os.chmod(os.path.join(fake, "python3"), stat.S_IRWXU)
        data = os.path.join(tmp, "data")
        env = dict(os.environ, SOFA_DATA=data, PATH=fake + os.pathsep + os.environ["PATH"])
        script = os.path.join(ROOT, "deploy", "docker", "entrypoint.sh")
        r = subprocess.run(["sh", script], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(data, "config.json"), encoding="utf-8") as f:
            written = json.load(f)
        self.assertEqual(written["shows"], "/media/Shows")
        self.assertEqual(written["inbox"], "/media/Inbox")
        self.assertEqual(written["drive_folders"], ["/mnt"])            # /media is the library, not a drive
        for key in written:
            self.assertIn(key, config.DEFAULTS)
        with open(os.path.join(tmp, "called"), encoding="utf-8") as f:
            called = f.read().split("\n")
        self.assertEqual(os.path.normpath(called[0]), os.path.join(ROOT, "sofa.py"))
        self.assertEqual(called[1], "serve")
        with open(os.path.join(data, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"port": 9999, "shows": "/somewhere/else"}, f)
        r = subprocess.run(["sh", script, "status"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(data, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"port": 9999, "shows": "/somewhere/else"})
        with open(os.path.join(tmp, "called"), encoding="utf-8") as f:
            self.assertEqual(f.read().split("\n")[1], "status")

    def test_the_commit_comes_from_the_image(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        with mock.patch.object(updater, "is_git_install", return_value=False), \
                mock.patch.object(updater, "STAMP_FILE", os.path.join(tempfile.gettempdir(), "no-such-stamp")), \
                mock.patch.dict(os.environ, {"SOFA_COMMIT": sha}):
            self.assertEqual(updater._local_commit(), sha)
        with mock.patch.object(updater, "is_git_install", return_value=False), \
                mock.patch.object(updater, "STAMP_FILE", os.path.join(tempfile.gettempdir(), "no-such-stamp")), \
                mock.patch.dict(os.environ, {"SOFA_COMMIT": "not a commit"}):
            self.assertIsNone(updater._local_commit())


class UpdatesInAContainer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        if not store.q1("SELECT 1 FROM users WHERE name = 'leo'"):
            auth.create_user("leo", "password123", admin=True)
            auth.create_user("mia", "kidpass123")
        cls.admin = Client(cls.base)
        assert cls.admin.call("/api/login", {"name": "leo", "password": "password123"})[0] == 200

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_update_now_says_to_pull_a_new_image(self):
        with mock.patch.dict(os.environ, {"SOFA_CONTAINER": IMAGE}):
            s = updater.status()
            self.assertEqual((s["container"], s["method"]), (IMAGE, "image"))
            with self.assertRaises(RuntimeError):
                updater.start_update()
            status, body = self.admin.call("/api/admin/update", {"install": True})
        self.assertEqual(status, 409)
        self.assertIn(updater.PULL, body["error"])
        self.assertIn(IMAGE, body["error"])
        self.assertFalse(updater._state["running"])                     # nothing was started
        s = updater.status()
        self.assertFalse(s["container"])
        self.assertIn(s["method"], ("git", "download"))

    def test_the_page_offers_no_button_in_a_container(self):
        js = read(os.path.join("client", "app.js"))
        body = js[js.index("function srvUpdate("):js.index("async function waitForRestart(")]
        self.assertRegex(body, r"u\.available && !u\.running && !image \? `<button[^`]*data-update=\"install\"")
        self.assertIn(updater.PULL, body)


if __name__ == "__main__":
    unittest.main()
