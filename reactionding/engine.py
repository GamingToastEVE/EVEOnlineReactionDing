"""Fetches all requested reactions and normalises them into rows."""

import concurrent.futures as cf
from dataclasses import dataclass, field

from .catalog import groups_for
from .client import ApiError, Client


@dataclass
class Row:
    group: object
    item_id: int
    name: str
    source: str
    result: dict = field(default=None, repr=False)
    error: str = ""

    def _get(self, key, default=None):
        return (self.result or {}).get(key, default)

    @property
    def ok(self):
        return self.result is not None

    @property
    def profit(self):
        return self._get("profit")

    @property
    def profit_percent(self):
        return self._get("profit_per")

    @property
    def inputs_total(self):
        return self._get("input_total")

    @property
    def taxes_total(self):
        return self._get("taxes_total")

    @property
    def output_total(self):
        return self._get("output_total")

    @property
    def runs(self):
        return self._get("runs")

    @property
    def profit_per_hour(self):
        """Profit per hour of the configured build window."""
        cycle = self._get("cycle_data") or {}
        minutes = cycle.get("total_time")
        if self.profit is None or not minutes:
            return None
        return self.profit / (minutes / 60.0)

    def to_dict(self, full=False):
        data = {
            "calculator": self.group.calculator,
            "group": self.group.key,
            "groupTitle": self.group.title,
            "id": self.item_id,
            "name": self.name,
            "source": self.source,
            "inputs": self.inputs_total,
            "taxes": self.taxes_total,
            "output": self.output_total,
            "profit": self.profit,
            "profitPercent": self.profit_percent,
            "profitPerHour": self.profit_per_hour,
            "runs": self.runs,
            "error": self.error,
        }
        if full:
            data["result"] = self.result
        return _finite(data)


def _finite(value):
    """Replace +/-Infinity/NaN (used by the calculator page for 0 output) with None."""
    if isinstance(value, float) and value != value or value in (float("inf"), float("-inf")):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


def _match_web(entries, item_id, name, position):
    for entry in entries:
        if entry.get("id") == item_id:
            return entry
    for entry in entries:
        if entry.get("name") == name:
            return entry
    if position < len(entries):
        return entries[position]
    return None


def calculate(settings, groups=None, source="auto", client=None, workers=4, progress=None):
    """Return one Row per reaction.

    source: ``auto`` (API, page data for groups the API cannot handle),
    ``api`` (API only) or ``web`` (page data only).
    """
    client = client or Client()
    groups = groups_for(groups) if groups is None or isinstance(groups[0], str) else groups
    rows = []
    api_jobs = []
    web_groups = []
    for group in groups:
        use = group.source if source == "auto" else source
        if use == "api":
            for item_id, name in group.items:
                row = Row(group, item_id, name, "api")
                rows.append(row)
                api_jobs.append(row)
        else:
            web_groups.append(group)

    web_pages = {}
    for calculator in sorted({g.calculator for g in web_groups}):
        try:
            web_pages[calculator] = client.web_results(calculator, settings)
        except ApiError as exc:
            web_pages[calculator] = exc
    for group in web_groups:
        page = web_pages[group.calculator]
        entries = None if isinstance(page, ApiError) else page.get(group.web_key) or []
        for position, (item_id, name) in enumerate(group.items):
            row = Row(group, item_id, name, "web")
            if entries is None:
                row.error = str(page)
            else:
                row.result = _match_web(entries, item_id, name, position)
                if row.result is None:
                    row.error = "missing in calculator page data"
            rows.append(row)
            if progress:
                progress(row)

    def run(row):
        try:
            row.result = client.api_calculate(row.group, row.item_id, settings)
        except ApiError as exc:
            row.error = str(exc)
        return row

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for row in pool.map(run, api_jobs):
            if progress:
                progress(row)

    order = {g.key: i for i, g in enumerate(groups)}
    rows.sort(key=lambda r: (order[r.group.key], [i for i, _ in r.group.items].index(r.item_id)))
    return rows


def warnings(settings, rows):
    """Plausibility hints the API itself does not give."""
    out = []
    ok = [r for r in rows if r.ok]
    if settings["space"] != "wormhole" and ok and \
            all(not ((r.result.get("taxes") or {}).get("system")) for r in ok):
        out.append(f"System cost is 0 for every reaction - is '{settings['system']}' spelled "
                   "exactly like in game (case-sensitive)?")
    return out
