"""Local HTTP server that receives Dota 2's Game State Integration POSTs.

IMPORTANT: the exact raw JSON key names Dota uses for the 'draft' section
are NOT confirmed from documentation (only a C# wrapper library's abstracted
property names are known publicly, not the literal wire format). This server
does not assume a schema - it captures every payload verbatim as a
GSI_PAYLOAD event in the per-run diagnostic log (event_log.py) so the real
shape can be inspected once a live match is played with GSI enabled.
`latest_raw` exposes the full parsed JSON for draft_matcher.py to attempt a
best-effort read from.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import event_log


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
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.latest_raw = None
        self._lock = threading.Lock()
        self._httpd = None
        self._thread = None

    def _on_payload(self, data):
        with self._lock:
            self.latest_raw = data
        event_log.log("GSI_PAYLOAD", data=data)

    def start(self):
        # Guarded: HTTPServer's bind raises OSError if the port is already
        # taken (e.g. a stray instance from an earlier crashed run still
        # holding it). Since the hub and overlay now share one process,
        # letting this propagate would take down the whole tray-resident
        # app instead of just this feature - log and continue with no GSI
        # server instead, matching this codebase's "auxiliary failure is
        # silent" convention.
        try:
            self._httpd = HTTPServer((self.host, self.port), _Handler)
        except OSError as e:
            event_log.log("ERROR", where="gsi_server_start", exc_type=type(e).__name__, message=str(e))
            return
        self._httpd.gsi_server = self
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
