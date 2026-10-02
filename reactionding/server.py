"""Small local web server for the browser interface (stdlib only)."""

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from pathlib import Path

from . import esi, production, sde, tracker
from . import settings as settings_mod
from .catalog import CALCULATORS, GROUPS
from .client import ApiError, Client
from .engine import _finite, calculate, warnings


def make_handler(settings_path):
    client = Client()
    lock = threading.Lock()
    planner_path = Path(settings_path).with_name("planner.json")
    campaign_path = Path(settings_path).with_name("campaign.json")
    cache = {}

    def recipes():
        """Official CCP recipes (loaded once per program start)."""
        with lock:
            if "recipes" not in cache:
                data = sde.load()
                cache["sde"] = {"build": data.get("build"), "offline": bool(data.get("offline"))}
                cache["recipes"] = sde.production_recipes(data)
                cache["components"] = production.load_components(cache["recipes"], data)
            return cache["recipes"], cache["components"]

    def load_plan():
        try:
            return json.loads(planner_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {"runsPerJob": 544, "jobs": {}, "components": {}, "stock": ""}

    def load_campaign():
        try:
            return json.loads(campaign_path.read_text("utf-8"))
        except (OSError, ValueError):
            return tracker.new_campaign()

    def save_campaign(campaign):
        with lock:
            campaign_path.write_text(json.dumps(campaign, indent=1), encoding="utf-8")

    def campaign_from(body):
        campaign = body.get("campaign")
        if not isinstance(campaign, dict) or not campaign.get("months"):
            raise ValueError("campaign missing")
        return campaign

    def month_index(body, campaign):
        index = int(body.get("index", len(campaign["months"]) - 1))
        if not 0 <= index < len(campaign["months"]):
            raise ValueError("month index out of range")
        return index

    def checked_settings(body):
        values = settings_mod.normalize(body.get("settings"))
        return esi.check_system(values)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, status, body, content_type="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(_finite(body)).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # browser tab closed or reloaded while we were calculating

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > 4 * 1024 * 1024:
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
            if self.path == "/api/planner/meta":
                rec, comps = recipes()
                return self._send(200, {
                    "plan": load_plan(),
                    "complex": sorted(n for n, r in rec.items() if r["group"] == "complex"),
                    "hybrid": sorted(n for n, r in rec.items() if r["group"] == "hybrid"),
                    "simple": sorted(n for n, r in rec.items() if r["group"] == "simple"),
                    "campaign": load_campaign(),
                    "components": [n for n, c in comps.items() if not c["capital"]],
                    "capital": [n for n, c in comps.items() if c["capital"]],
                    "sde": cache.get("sde"),
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
                    values, notes = esi.check_system(values)
                    groups = [GROUPS[k] for k in body.get("groups") or GROUPS if k in GROUPS]
                    source = body.get("source", "auto")
                    if source not in ("auto", "api", "web"):
                        raise settings_mod.SettingsError("source must be auto, api or web")
                    rows = calculate(values, groups, source=source, client=client)
                    return self._send(200, {"settings": values,
                                            "warnings": warnings(values, rows),
                                            "notes": notes,
                                            "rows": [r.to_dict(full=True) for r in rows]})
                if self.path == "/api/chain":
                    values, notes = checked_settings(body)
                    rec, comps = recipes()
                    return self._send(200, {"notes": notes, "sde": cache.get("sde"),
                                            "chain": production.cost_chain(rec, values, components=comps)})
                if self.path in ("/api/campaign/plan", "/api/campaign/close", "/api/campaign/reopen"):
                    campaign = campaign_from(body)
                    index = month_index(body, campaign)
                    rec, comps = recipes()
                    notes = []
                    if self.path == "/api/campaign/reopen":
                        months = campaign["months"]
                        nxt = months[index + 1] if index + 1 < len(months) else None
                        if nxt and (index + 2 < len(months) or nxt.get("track") or nxt.get("bought")
                                    or nxt.get("stock") or any((nxt.get("orders") or {}).values())):
                            raise ValueError("The next month is already in use - it cannot be undone.")
                        if nxt:
                            months.pop()
                        months[index]["closed"] = False
                        months[index].pop("summary", None)
                    values, notes = checked_settings(body)
                    plan = tracker.plan_month(rec, comps, values, campaign, index)
                    if self.path == "/api/campaign/close":
                        tracker.close_month(campaign, index, plan, repeat_orders=bool(body.get("repeat")))
                        index += 1
                        plan = tracker.plan_month(rec, comps, values, campaign, index)
                    save_campaign(campaign)
                    return self._send(200, {"notes": notes, "campaign": campaign, "index": index, "plan": plan,
                                            "overview": tracker.overview(campaign),
                                            "stageNames": tracker.STAGE_NAMES})
                if self.path == "/api/plan":
                    values, notes = checked_settings(body)
                    state = body.get("plan") or {}
                    if body.get("save"):
                        with lock:
                            planner_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
                    rec, comps = recipes()
                    return self._send(200, {"notes": notes, "sde": cache.get("sde"),
                                            "plan": production.plan(rec, values, state, components=comps)})
            except (settings_mod.SettingsError, ValueError) as exc:
                return self._send(400, {"error": str(exc)})
            except ApiError as exc:
                return self._send(502, {"error": str(exc)})
            except Exception as exc:  # never leave the browser waiting without an answer
                return self._send(500, {"error": f"Internal error: {exc!r}"})
            self._send(404, {"error": "not found"})

    return Handler


def serve(host="127.0.0.1", port=8765, settings_path="settings.json", open_browser=False):
    url = f"http://{host}:{port}/"
    try:
        server = ThreadingHTTPServer((host, port), make_handler(settings_path))
    except OSError:
        # Port taken - most likely the program is already running (second double-click).
        print(f"Port {port} is in use, opening {url}")
        if open_browser:
            webbrowser.open(url)
        return
    print(f"EVE Reaction Ding running at {url}  (close this window or press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
