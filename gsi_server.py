"""Local HTTP server that receives Dota 2's Game State Integration POSTs.

IMPORTANT: the exact raw JSON key names Dota uses for the 'draft' section
are NOT confirmed from documentation (only a C# wrapper library's abstracted
property names are known publicly, not the literal wire format). This server
does not assume a schema - it captures every payload verbatim to a JSONL file
so the real shape can be inspected once a live match is played with GSI
enabled. `latest_raw` exposes the full parsed JSON for draft_matcher.py to
attempt a best-effort read from.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        self.server.gsi_server._on_payload(data)
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silence default stderr request logging


class GSIServer:
    def __init__(self, host, port, captures_path="gsi_captures.jsonl"):
        self.host = host
        self.port = port
        self.captures_path = captures_path
        self.latest_raw = None
        self._lock = threading.Lock()
        self._httpd = None
        self._thread = None

    def _on_payload(self, data):
        with self._lock:
            self.latest_raw = data
        with open(self.captures_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

    def start(self):
        self._httpd = HTTPServer((self.host, self.port), _Handler)
        self._httpd.gsi_server = self
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
