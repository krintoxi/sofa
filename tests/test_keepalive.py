"""One connection, several requests (browsers keep connections open): a request Sofa turns down before reading its
body mustn't leave the body behind to be taken for the next request (that one used to fail: "Unsupported method")."""
import http.client
import json
import threading
import unittest

import tests  # noqa: F401  (sets Sofa up for the tests)
from sofa import web


class KeepAlive(unittest.TestCase):
    def setUp(self):
        self.httpd = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_a_body_turned_down_unread(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        body = json.dumps({"name": "nobody", "password": "not-this-one"})
        conn.request("POST", "/api/login", body, {"Content-Type": "application/json"})      # no X-Sofa: turned down
        r = conn.getresponse()
        r.read()
        self.assertEqual(r.status, 400)
        conn.request("POST", "/api/login", body, {"Content-Type": "application/json", "X-Sofa": "1"})
        r = conn.getresponse()
        r.read()
        self.assertIn(r.status, (401, 403, 429), r.reason)       # an answer about the sign-in, not about the last body
        conn.close()

    def test_still_kept_alive_when_read(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        body = json.dumps({"name": "nobody", "password": "not-this-one"})
        for _ in range(2):
            conn.request("POST", "/api/login", body, {"Content-Type": "application/json", "X-Sofa": "1"})
            r = conn.getresponse()
            r.read()
            self.assertIn(r.status, (401, 403, 429))
            self.assertFalse(r.will_close)
        conn.close()


if __name__ == "__main__":
    unittest.main()
