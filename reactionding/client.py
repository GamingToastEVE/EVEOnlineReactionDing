"""HTTP access to reactions.coalition.space (API + calculator page data)."""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import devalue
from .settings import to_cookies, to_query

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
    """Spaces requests out; the API allows roughly 90 requests / 60 s."""

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
    def __init__(self, base_url=BASE_URL, timeout=60, retries=4, per_second=5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.limiter = RateLimiter(per_second)

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
                last_error = ApiError(exc.code, payload.get("code", "HTTP_ERROR"),
                                      payload.get("error", ""), payload.get("details"))
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

    # --- API -------------------------------------------------------------

    def api_url(self, group, item_id, settings):
        if group.calculator == "hybrid":
            path = f"/api/v1/hybrid/{item_id}"
        else:
            path = f"/api/v1/{group.calculator}/{group.api_type}/{item_id}"
        query = dict(to_query(settings), includeMeta="false")
        return self.base_url + path + "?" + urllib.parse.urlencode(query)

    def api_calculate(self, group, item_id, settings):
        """One reaction from the API. Returns the single result dict."""
        payload = self._get(self.api_url(group, item_id, settings))
        results = payload.get("results") or []
        if not results:
            raise ApiError(200, "EMPTY_RESULT", f"No result for {group.key}/{item_id}")
        return results[0]

    # --- calculator page data ---------------------------------------------

    def web_results(self, calculator, settings):
        """All tables of one calculator page (dict web_key -> list of results)."""
        cookie = "; ".join(f"{k}={urllib.parse.quote(v, safe=' -_.')}"
                           for k, v in to_cookies(settings).items())
        payload = self._get(f"{self.base_url}/{calculator}/__data.json", {"Cookie": cookie})
        nodes = [n for n in devalue.decode_page(payload) if isinstance(n, dict) and "results" in n]
        if not nodes:
            raise ApiError(200, "NO_PAGE_DATA", f"No results in {calculator} page data")
        page = nodes[-1]
        results = page["results"]
        if calculator == "hybrid":
            results = {"hybrid": results}
        # The page echoes the settings it used; make sure our cookies were honoured.
        for key in ("inMarket", "outMarket", "system", "input", "output", "space"):
            sent = to_cookies(settings)[key]
            if key in page and str(page[key]) != sent:
                raise ApiError(200, "SETTINGS_IGNORED",
                               f"Page used {key}={page[key]!r} instead of {sent!r}")
        return results
