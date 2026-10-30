"""HTTP access to reactions.coalition.space API v2 (https://reactions.coalition.space/api).

API v1 and the calculator page data used by older versions were removed by the site.
Results are converted into the shape the rest of the program works with:
{"runs", "input": [{name, quantity}], "output": [{name, quantity}], "taxes": {...},
 "cycle_data": {"total_time": minutes}, "v2": <original totals>}."""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .settings import to_query

BASE_URL = "https://reactions.coalition.space"
# Cloudflare answers the default Python user agent with "error code: 1010".
USER_AGENT = "EVEOnlineReactionDing/1.0 (+https://github.com/GamingToastEVE/EVEOnlineReactionDing)"


class ApiError(RuntimeError):
    def __init__(self, status, code, message, details=None):
        super().__init__(f"HTTP {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


class RateLimiter:
    """Spaces requests out; API v2 allows 120 requests per minute and IP."""

    def __init__(self, per_second):
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self.lock = threading.Lock()
        self.next_slot = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next_slot)
            self.next_slot = slot + self.interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


class Client:
    CACHE_SECONDS = 600  # the site refreshes its prices/indices every 30 minutes

    def __init__(self, base_url=BASE_URL, timeout=60, retries=4, per_second=1.8):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.limiter = RateLimiter(min(per_second, 1.9))
        self._cache = {}
        self._cache_lock = threading.Lock()
        self._slugs = None

    def _get(self, url, headers=None):
        request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        request_headers.update(headers or {})
        last_error = None
        for attempt in range(self.retries + 1):
            self.limiter.wait()
            request = urllib.request.Request(url, headers=request_headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                try:
                    payload = json.loads(body)
                except ValueError:
                    payload = {"error": body.strip()[:200], "code": "HTTP_ERROR"}
                err = payload.get("error") if isinstance(payload.get("error"), dict) else payload
                last_error = ApiError(exc.code, err.get("code", payload.get("code", "HTTP_ERROR")),
                                      err.get("message", payload.get("error", "")), err.get("details"))
                if exc.code not in (429, 500, 502, 503, 504):
                    raise last_error from None
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = ApiError(0, "NETWORK_ERROR", str(exc))
                delay = 2 ** (attempt + 1)
            if attempt < self.retries:
                time.sleep(delay)
        raise last_error

    # --- API v2 ------------------------------------------------------------

    def _cached(self, url):
        now = time.monotonic()
        with self._cache_lock:
            hit = self._cache.get(url)
            if hit and now - hit[0] < self.CACHE_SECONDS:
                return hit[1]
        data = self._get(url)
        with self._cache_lock:
            self._cache[url] = (time.monotonic(), data)
        return data

    def recipes(self):
        """All reaction recipes of the site (GET /api/v2/reactions)."""
        return self._cached(f"{self.base_url}/api/v2/reactions")

    def slug(self, item_id, name):
        """Slug of a reaction by product type id (or name)."""
        if self._slugs is None:
            table = {}
            for r in self.recipes():
                table[r["product"]["typeId"]] = r["slug"]
                table[r["product"]["name"]] = r["slug"]
                table[r["name"]] = r["slug"]
            self._slugs = table
        found = self._slugs.get(item_id) or self._slugs.get(name)
        if not found:
            raise ApiError(404, "NOT_FOUND", f"{name} ({item_id}) is not a reaction of the calculator")
        return found

    def api_url(self, group, item_id, settings, name=""):
        from .catalog import v2_view

        view, output = v2_view(group)
        query = dict(to_query(settings), view=view)
        if output != "product":
            query["output"] = output
        return f"{self.base_url}/api/v2/profits/{self.slug(item_id, name)}?" + urllib.parse.urlencode(query)

    def api_calculate(self, group, item_id, settings, name=""):
        """One reaction (GET /api/v2/profits/{slug}) in the program's result shape."""
        return convert_v2(self._cached(self.api_url(group, item_id, settings, name)))

    def web_results(self, calculator, settings):
        raise ApiError(410, "REMOVED", "the calculator page data is not used any more (API v2 replaces it)")


def convert_v2(d):
    """API v2 calculation -> result dict used by engine/verify/sheetcheck."""
    item = lambda x: {"name": x["name"], "id": x.get("typeId"), "quantity": x["quantity"]}  # noqa: E731
    job = d.get("jobCost") or {}
    totals = d.get("totals") or {}
    seconds = totals.get("slotSeconds") or (d.get("runTimeSeconds") or 0) * (d.get("runs") or 0)
    return {
        "name": d.get("name"), "slug": d.get("slug"), "view": d.get("view"), "runs": d.get("runs"),
        "input": [item(x) for x in d.get("inputs") or []],
        "output": [item(x) for x in d.get("outputs") or []],
        "surplus": [item(x) for x in d.get("surplus") or []],
        "chain": d.get("chain"),
        "taxes": {"system": job.get("systemCost"), "total": {"install": job.get("total") or 0.0}},
        "cycle_data": {"total_time": seconds / 60.0 if seconds else None},
        "warnings": d.get("warnings") or [],
        "v2": totals,
    }
