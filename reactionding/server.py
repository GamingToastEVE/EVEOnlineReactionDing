"""Small local web server for the browser interface (stdlib only)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from . import settings as settings_mod
from .catalog import CALCULATORS, GROUPS
from .client import ApiError, Client
from .engine import _finite, calculate, warnings


def make_handler(settings_path):
    client = Client()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, status, body, content_type="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(_finite(body)).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > 64 * 1024:
                raise ValueError("request too large")
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                html = resources.files("reactionding").joinpath("web/index.html").read_bytes()
                return self._send(200, html, "text/html; charset=utf-8")
            if self.path == "/api/meta":
                return self._send(200, {
                    "settings": settings_mod.load(settings_path),
                    "defaults": settings_mod.DEFAULTS,
                    "schema": {k: {"kind": v[0], "rule": v[1], "label": v[2]}
                               for k, v in settings_mod.SCHEMA.items()},
                    "calculators": CALCULATORS,
                    "groups": [{"key": g.key, "calculator": g.calculator, "title": g.title,
                                "source": g.source, "issue": g.issue,
                                "items": [list(i) for i in g.items]} for g in GROUPS.values()],
                })
            self._send(404, {"error": "not found"})

        def do_POST(self):
            try:
                body = self._body()
                if self.path == "/api/settings":
                    values = settings_mod.normalize(body.get("settings"))
                    with lock:
                        settings_mod.save(settings_path, values)
                    return self._send(200, {"settings": values})
                if self.path == "/api/calc":
                    values = settings_mod.normalize(body.get("settings"))
                    groups = [GROUPS[k] for k in body.get("groups") or GROUPS if k in GROUPS]
                    source = body.get("source", "auto")
                    if source not in ("auto", "api", "web"):
                        raise settings_mod.SettingsError("source must be auto, api or web")
                    rows = calculate(values, groups, source=source, client=client)
                    return self._send(200, {"settings": values,
                                            "warnings": warnings(values, rows),
                                            "rows": [r.to_dict(full=True) for r in rows]})
            except (settings_mod.SettingsError, ValueError) as exc:
                return self._send(400, {"error": str(exc)})
            except ApiError as exc:
                return self._send(502, {"error": str(exc)})
            self._send(404, {"error": "not found"})

    return Handler


def serve(host="127.0.0.1", port=8765, settings_path="settings.json"):
    server = ThreadingHTTPServer((host, port), make_handler(settings_path))
    print(f"EVE Reaction Ding running at http://{host}:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
