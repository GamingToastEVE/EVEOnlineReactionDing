"""Live Jita 4-4 prices from EVE's official API (ESI).

For every item: Buy = highest buy order, Sell = lowest sell order in
Jita IV - Moon 4 - Caldari Navy Assembly Plant, Split = middle of both.
"""

import concurrent.futures as cf
import json
import threading
import time
import urllib.error
import urllib.request

from .client import USER_AGENT
from .esi import ESI_URL, EsiError

REGION = 10000002  # The Forge
STATION = 60003760  # Jita IV - Moon 4 - Caldari Navy Assembly Plant
MODES = ("buy", "split", "sell")
CACHE_SECONDS = 300

_lock = threading.Lock()
_prices = {}  # type_id -> (timestamp, {"buy", "split", "sell"})
_ids = {}  # name -> type_id


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


def jita_prices(type_ids, workers=12):
    """{type_id: {"buy", "split", "sell", "note"}}; see _complete for missing order sides."""
    now = time.time()
    with _lock:
        missing = [t for t in set(type_ids) if t not in _prices or now - _prices[t][0] > CACHE_SECONDS]
    if missing:
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            for type_id, prices in zip(missing, pool.map(_fetch_one, missing)):
                with _lock:
                    _prices[type_id] = (time.time(), prices)
    with _lock:
        return {t: _prices[t][1] for t in type_ids}


def type_ids(names):
    """{name: type_id} for item names (exact in-game names)."""
    with _lock:
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
    with _lock:
        return {n: _ids[n] for n in names if n in _ids}


def prices_by_name(names):
    """{name: {"buy", "split", "sell"}} for item names."""
    ids = type_ids(names)
    prices = jita_prices(list(ids.values()))
    empty = {"buy": None, "split": None, "sell": None, "note": "unknown item name"}
    return {n: prices.get(ids.get(n), empty) if n in ids else empty for n in names}
