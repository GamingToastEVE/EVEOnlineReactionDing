"""Small client for EVE Online's official API (ESI, https://esi.evetech.net).

Used to validate the reaction system name: the reactions calculator matches the
name case-sensitively and silently uses a cost index of 0 for unknown systems.
"""

import json
import threading
import time
import urllib.error
import urllib.request

from .client import USER_AGENT
from .settings import SettingsError

ESI_URL = "https://esi.evetech.net/latest"
_lock = threading.Lock()
_systems = {}  # lower-case name -> (id, name) or None
_indices = {"time": 0.0, "data": {}}


class EsiError(RuntimeError):
    pass


def _request(path, body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(ESI_URL + path, data=data, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json",
        **({"Content-Type": "application/json"} if data else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise EsiError(f"ESI request {path} failed: {exc}") from None


def status():
    return _request("/status/")


def resolve_system(name):
    """(system_id, exact in-game name) for a solar system name, any case; None if unknown."""
    key = name.strip().lower()
    with _lock:
        if key in _systems:
            return _systems[key]
    systems = _request("/universe/ids/", [name.strip()]).get("systems") or []
    hit = next(((s["id"], s["name"]) for s in systems if s["name"].lower() == key), None)
    with _lock:
        _systems[key] = hit
    return hit


def reaction_cost_index(system_id, max_age=3600):
    """Current reaction cost index of a system as a fraction (0.1029 = 10.29 %)."""
    with _lock:
        fresh = time.time() - _indices["time"] < max_age
    if not fresh:
        data = {}
        for entry in _request("/industry/systems/", timeout=60):
            for ci in entry.get("cost_indices", []):
                if ci.get("activity") == "reaction":
                    data[entry["solar_system_id"]] = ci.get("cost_index", 0.0)
        with _lock:
            _indices.update(time=time.time(), data=data)
    with _lock:
        return _indices["data"].get(system_id, 0.0)


def check_system(settings):
    """Return (settings, notes). Fixes the spelling of the system name via ESI.

    Raises SettingsError for a system that does not exist. Network problems are
    reported as a note and leave the settings unchanged.
    """
    notes = []
    try:
        hit = resolve_system(settings["system"])
    except EsiError as exc:
        return settings, [f"Could not check system name with ESI ({exc})"]
    if hit is None:
        raise SettingsError(f"System '{settings['system']}' does not exist in EVE Online (checked with ESI)")
    system_id, name = hit
    if name != settings["system"]:
        notes.append(f"System name corrected to '{name}'")
        settings = dict(settings, system=name)
    if settings["space"] != "wormhole":
        try:
            notes.append(f"Reaction cost index {name}: {reaction_cost_index(system_id) * 100:.2f} %")
        except EsiError:
            pass
    return settings, notes
