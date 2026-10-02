"""Reaction and component recipes from CCP's official Static Data Export (SDE).

https://developers.eveonline.com/static-data publishes the game data as a zip of JSONL
files (~100 MB). Only ``blueprints.jsonl`` (~190 KB compressed) is needed, so it is read
with HTTP range requests; item names come from ESI. The result is cached per SDE build in
the user's cache folder. ``data/sde_recipes.json`` ships a copy for offline use.
"""

import io
import json
import urllib.request
import zipfile
from importlib import resources
from pathlib import Path

from .client import USER_AGENT
from .esi import ESI_URL, EsiError

SDE_BASE = "https://developers.eveonline.com/static-data/tranquility"


class _HttpFile(io.RawIOBase):
    """Read-only, seekable view of a remote file using HTTP range requests."""

    def __init__(self, url):
        self.url, self.pos = url, 0
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as response:
            self.size = int(response.headers["Content-Length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, buffer):
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(buffer), self.size) - 1
        req = urllib.request.Request(self.url, headers={"User-Agent": USER_AGENT,
                                                        "Range": f"bytes={self.pos}-{end}"})
        with urllib.request.urlopen(req, timeout=120) as response:
            data = response.read()
        buffer[:len(data)] = data
        self.pos += len(data)
        return len(data)


def _cache_dir():
    path = Path.home() / ".cache" / "eve-reaction-ding"
    path.mkdir(parents=True, exist_ok=True)
    return path


def latest_build():
    req = urllib.request.Request(f"{SDE_BASE}/latest.jsonl", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().splitlines()[0])["buildNumber"]


def _names(ids):
    names = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 1000):
        req = urllib.request.Request(f"{ESI_URL}/universe/names/", data=json.dumps(ids[i:i + 1000]).encode(),
                                     headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as response:
            names.update({x["id"]: x["name"] for x in json.load(response)})
    return names


def build_recipes(build):
    """Download blueprints of one SDE build and turn them into named recipes."""
    url = f"{SDE_BASE}/eve-online-static-data-{build}-jsonl.zip"
    archive = zipfile.ZipFile(io.BufferedReader(_HttpFile(url), buffer_size=1 << 20))
    blueprints = [json.loads(line) for line in archive.read("blueprints.jsonl").splitlines() if line]

    reactions = {}
    for bp in blueprints:
        act = (bp.get("activities") or {}).get("reaction")
        if act and act.get("products"):
            product = act["products"][0]
            reactions[product["typeID"]] = {
                "out": product["quantity"], "time": act.get("time"),
                "in": {m["typeID"]: m["quantity"] for m in act.get("materials", [])}}
    products = set(reactions)
    components = {}
    for bp in blueprints:
        act = (bp.get("activities") or {}).get("manufacturing")
        if not act or not act.get("products") or not act.get("materials"):
            continue
        mats = {m["typeID"]: m["quantity"] for m in act["materials"]}
        # T2 / capital T2 components: built only from reaction products
        if set(mats) <= products and any(reactions[t]["in"] for t in mats):
            product = act["products"][0]
            components[product["typeID"]] = {"out": product["quantity"], "in": mats}

    ids = set(reactions) | set(components)
    for r in list(reactions.values()) + list(components.values()):
        ids.update(r["in"])
    names = _names(ids)

    def named(r):
        return {"out": r["out"], "time": r.get("time"), "in": {names[t]: q for t, q in r["in"].items()}}

    return {
        "build": build,
        "source": url,
        "reactions": {names[t]: dict(named(r), id=t) for t, r in reactions.items()},
        "components": {names[t]: dict(named(r), id=t, capital=names[t].startswith("Capital "))
                       for t, r in components.items()},
    }


_loaded = {}


def load(refresh=True):
    """Recipes of the latest SDE build (cached on disk); falls back to the shipped copy."""
    if "data" in _loaded:
        return _loaded["data"]
    data = None
    if refresh:
        try:
            build = latest_build()
            path = _cache_dir() / f"sde-recipes-{build}.json"
            if path.exists():
                data = json.loads(path.read_text("utf-8"))
            else:
                data = build_recipes(build)
                path.write_text(json.dumps(data), encoding="utf-8")
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, EsiError):
            data = None  # offline or format changed: use the shipped copy
    if data is None:
        data = json.loads(resources.files("reactionding").joinpath("data/sde_recipes.json").read_text("utf-8"))
        data["offline"] = True
    _loaded["data"] = data
    return data


def production_recipes(data=None):
    """Simple, complex and hybrid reaction recipes in the shape production.py expects."""
    from .catalog import GROUPS

    data = data or load()
    recipes = {}
    for key in ("simple", "complex", "hybrid"):
        for _, name in GROUPS[key].items:
            r = data["reactions"].get(name)
            if r:
                recipes[name] = {"group": key, "out": float(r["out"]),
                                 "in": {k: float(v) for k, v in r["in"].items()}}
    return recipes
