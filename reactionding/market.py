"""Live Jita 4-4 prices from EVE's official API (ESI).

For every item: Buy = highest buy order, Sell = lowest sell order in
Jita IV - Moon 4 - Caldari Navy Assembly Plant, Split = middle of both.

Prices are cached for 15 minutes (also on disk, so a restart does not ask ESI again).
While the web interface runs, a background thread refreshes them every 15 minutes.
If ESI is unreachable, the last known prices are used.
"""

import concurrent.futures as cf
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .client import USER_AGENT
from .esi import ESI_URL, EsiError

REGION = 10000002  # The Forge
STATION = 60003760  # Jita IV - Moon 4 - Caldari Navy Assembly Plant
MODES = ("buy", "split", "sell")
CACHE_SECONDS = 15 * 60

_lock = threading.Lock()
_prices = {}  # type_id -> (timestamp, {"buy", "split", "sell"})
_ids = {}  # name -> type_id
_state = {"loaded": False, "fetched": None, "error": None}


def _cache_file():
    return Path.home() / ".cache" / "eve-reaction-ding" / "jita-prices.json"


def _load_cache():
    """Reads the disk cache once (call with _lock held)."""
    if _state["loaded"]:
        return
    _state["loaded"] = True
    try:
        data = json.loads(_cache_file().read_text("utf-8"))
        _ids.update(data.get("ids") or {})
        for k, (ts, prices) in (data.get("prices") or {}).items():
            _prices[int(k)] = (float(ts), prices)
        _state["fetched"] = data.get("fetched")
    except (OSError, ValueError, TypeError):
        pass


def _save_cache():
    with _lock:
        data = {"fetched": _state["fetched"], "ids": dict(_ids),
                "prices": {str(k): [ts, p] for k, (ts, p) in _prices.items()}}
    try:
        path = _cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _get(url, timeout=30, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response), response.headers
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 420 or attempt == retries:
                raise EsiError(f"ESI {url}: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            if attempt == retries:
                raise EsiError(f"ESI {url}: {exc}") from None
        time.sleep(1 + attempt * 2)


def _fetch_one(type_id):
    best_buy, best_sell, page, pages = None, None, 1, 1
    while page <= pages:
        orders, headers = _get(f"{ESI_URL}/markets/{REGION}/orders/?type_id={type_id}"
                               f"&order_type=all&page={page}")
        pages = int(headers.get("X-Pages") or 1)
        for o in orders:
            if o.get("location_id") != STATION:
                continue
            if o["is_buy_order"]:
                best_buy = o["price"] if best_buy is None else max(best_buy, o["price"])
            else:
                best_sell = o["price"] if best_sell is None else min(best_sell, o["price"])
        page += 1
    return _complete(best_buy, best_sell)


def _complete(buy, sell):
    """Prices for all three methods. A missing side takes the price of the other side
    (noted in "note"), so an item without sell orders is not counted as free."""
    note = None
    if buy is None and sell is None:
        return {"buy": None, "split": None, "sell": None, "note": "no orders in Jita 4-4"}
    if sell is None:
        sell, note = buy, "no sell orders in Jita 4-4 - buy price used"
    elif buy is None:
        buy, note = sell, "no buy orders in Jita 4-4 - sell price used"
    return {"buy": buy, "split": (buy + sell) / 2, "sell": sell, "note": note}


def jita_prices(type_ids, workers=12, max_age=CACHE_SECONDS):
    """{type_id: {"buy", "split", "sell", "note"}}; see _complete for missing order sides.

    Prices younger than ``max_age`` seconds come from the cache. If ESI fails, older cached
    prices are used instead of failing."""
    now = time.time()
    with _lock:
        _load_cache()
        missing = [t for t in set(type_ids) if t not in _prices or now - _prices[t][0] > max_age]
    if missing:
        try:
            with cf.ThreadPoolExecutor(max_workers=workers) as pool:
                fetched = list(zip(missing, pool.map(_fetch_one, missing)))
        except EsiError as exc:
            with _lock:
                _state["error"] = str(exc)
                if any(t not in _prices for t in type_ids):
                    raise
        else:
            with _lock:
                for type_id, prices in fetched:
                    _prices[type_id] = (time.time(), prices)
                _state["fetched"], _state["error"] = time.time(), None
            _save_cache()
    with _lock:
        return {t: _prices[t][1] for t in type_ids}


def status():
    """When the prices were last fetched from ESI (for the interface)."""
    with _lock:
        _load_cache()
        fetched = _state["fetched"]
        return {"fetched": fetched, "age": None if fetched is None else round(time.time() - fetched),
                "items": len(_prices), "refreshSeconds": CACHE_SECONDS, "error": _state["error"]}


def start_refresher(interval=CACHE_SECONDS):
    """Background thread: refreshes all known prices every ``interval`` seconds."""
    def loop():
        while True:
            with _lock:
                _load_cache()
                ids = list(_prices)
                oldest = min((ts for ts, _ in _prices.values()), default=0)
            wait = max(30, interval - (time.time() - oldest)) if ids else interval
            time.sleep(wait)
            with _lock:
                ids = list(_prices)
            if ids:
                try:
                    jita_prices(ids, max_age=interval - 30)
                except Exception:  # noqa: BLE001 - keep refreshing, the error shows in status()
                    pass
    thread = threading.Thread(target=loop, name="jita-prices", daemon=True)
    thread.start()
    return thread


def type_ids(names):
    """{name: type_id} for item names (exact in-game names)."""
    with _lock:
        _load_cache()
        unknown = [n for n in set(names) if n not in _ids]
    for i in range(0, len(unknown), 500):
        chunk = unknown[i:i + 500]
        req = urllib.request.Request(f"{ESI_URL}/universe/ids/", data=json.dumps(chunk).encode(),
                                     headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                found = json.load(response).get("inventory_types") or []
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise EsiError(f"ESI name lookup failed: {exc}") from None
        with _lock:
            for t in found:
                _ids[t["name"]] = t["id"]
        _save_cache()
    with _lock:
        return {n: _ids[n] for n in names if n in _ids}


def prices_by_name(names):
    """{name: {"buy", "split", "sell"}} for item names."""
    ids = type_ids(names)
    prices = jita_prices(list(ids.values()))
    empty = {"buy": None, "split": None, "sell": None, "note": "unknown item name"}
    return {n: prices.get(ids.get(n), empty) if n in ids else empty for n in names}
