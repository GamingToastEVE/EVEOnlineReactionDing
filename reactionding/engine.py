"""Fetches all requested reactions and normalises them into rows."""

import concurrent.futures as cf
from dataclasses import dataclass, field

from .catalog import groups_for
from .client import ApiError, Client


MODES = ("buy", "split", "sell")


def outputs(result):
    """Output items of a result as a list (reprocessing groups return several)."""
    out = (result or {}).get("output") or []
    return out if isinstance(out, list) else [out]


@dataclass
class Row:
    """One reaction. Quantities and job install cost come from the reactions calculator,
    prices live from ESI (Jita 4-4): Buy = highest buy order, Sell = lowest sell order,
    Split = middle of both.

    Cost = input materials + market fees on the inputs + job install cost (system cost
    index, facility tax, SCC). Profit = output value - market fees on the output - cost.
    Market fees follow the calculator: buying inputs with buy orders costs broker fee,
    selling the output with sell orders costs broker fee + sales tax, selling into buy
    orders costs sales tax. Split is the middle of the Buy and Sell results."""

    group: object
    item_id: int
    name: str
    source: str
    result: dict = field(default=None, repr=False)
    error: str = ""
    prices: dict = field(default=None, repr=False)  # item name -> {"buy", "split", "sell"}
    brokers: float = 0.0  # percent
    sales: float = 0.0  # percent
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return self.result is not None and self.prices is not None

    @property
    def missing_prices(self):
        """{item: note} for items without Jita buy and/or sell orders."""
        names = [x["name"] for x in self.result.get("input", [])] + [x["name"] for x in outputs(self.result)]
        return {n: (self.prices.get(n) or {}).get("note") or "no price" for n in sorted(set(names))
                if not self.prices.get(n) or self.prices[n].get("note")}

    def _value(self, items, mode):
        return sum(x.get("quantity", 0) * ((self.prices.get(x["name"]) or {}).get(mode) or 0.0)
                   for x in items)

    def view(self, mode):
        if not self.ok:
            return None
        if mode == "split":
            buy, sell = self.view("buy"), self.view("sell")
            return {k: (buy[k] + sell[k]) / 2 if buy[k] is not None and sell[k] is not None else None
                    for k in buy}
        b, s = self.brokers / 100.0, self.sales / 100.0
        inputs = self._value(self.result.get("input", []), mode)
        output = self._value(outputs(self.result), mode)
        input_fees = inputs * b if mode == "buy" else 0.0
        output_fees = output * (b + s) if mode == "sell" else output * s
        install = ((self.result.get("taxes") or {}).get("total") or {}).get("install") or 0.0
        cost = inputs + input_fees + install
        profit = output - output_fees - cost
        minutes = (self.result.get("cycle_data") or {}).get("total_time")
        return {"inputs": inputs, "inputFees": input_fees, "install": install, "cost": cost,
                "output": output, "outputFees": output_fees, "profit": profit,
                "profitPercent": profit / output * 100 if output else None,
                "profitPerHour": profit / (minutes / 60.0) if minutes else None}

    def _views(self):
        return {m: self.view(m) for m in MODES} if self.ok else {}

    @property
    def runs(self):
        return (self.result or {}).get("runs")

    def to_dict(self, full=False):
        views = self._views()
        data = {
            "calculator": self.group.calculator,
            "group": self.group.key,
            "groupTitle": self.group.title,
            "id": self.item_id,
            "name": self.name,
            "source": self.source,
            "runs": self.runs,
            "error": self.error,
            "notes": list(self.notes),
        }
        for m in MODES:
            v = views.get(m) or {}
            data[f"cost_{m}"] = v.get("cost")
            data[f"profit_{m}"] = v.get("profit")
            data[f"profitPercent_{m}"] = v.get("profitPercent")
            data[f"profitPerHour_{m}"] = v.get("profitPerHour")
        if self.ok:
            data["missingPrices"] = self.missing_prices
        if full and self.ok:
            data["views"] = views
            data["prices"] = {x["name"]: self.prices.get(x["name"])
                              for x in self.result.get("input", []) + outputs(self.result)}
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


def calculate(settings, groups=None, source="auto", client=None, workers=4, progress=None,
              prices=True):
    """Return one Row per reaction.

    source: ``auto`` (API, page data for groups the API cannot handle),
    ``api`` (API only) or ``web`` (page data only).
    prices: attach live Jita prices from ESI (needed for cost/profit).
    """
    client = client or Client()
    groups = groups_for(groups) if groups is None or isinstance(groups[0], str) else groups
    rows, api_jobs, web_groups = [], [], []
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

    if prices:
        attach_prices(rows, settings)
        compare_with_ccp(rows)
    order = {g.key: i for i, g in enumerate(groups)}
    rows.sort(key=lambda r: (order[r.group.key], [i for i, _ in r.group.items].index(r.item_id)))
    return rows


# groups whose calculator result is the plain recipe (no chain / reprocessing on top)
PLAIN_GROUPS = {"hybrid", "simple", "complex", "unrefined", "eratic", "synth", "standard", "improved",
                "strong", "molecular"}


def compare_with_ccp(rows):
    """Note reactions where the calculator uses a different recipe than CCP's official SDE."""
    from . import sde

    try:
        official = sde.load()["reactions"]
    except Exception:  # recipes are an extra check only
        return
    for row in rows:
        if not row.result or row.group.key not in PLAIN_GROUPS or row.name not in official:
            continue
        runs = row.result.get("runs") or 0
        recipe = official[row.name]["in"]
        got = {x["name"]: x["quantity"] / runs for x in row.result.get("input", []) if runs}
        for name in sorted(set(recipe) | set(got)):
            base, per_run = recipe.get(name), got.get(name)
            if base is None or per_run is None or not base * 0.9 <= per_run <= base + 1e-9:
                row.notes.append(f"calculator uses {per_run or 0:,.1f} {name}/run, CCP recipe says "
                                 f"{base or 0:g} - quantities and cost of this row are off")


def attach_prices(rows, settings):
    from . import market
    from .esi import EsiError

    names = set()
    for row in rows:
        if row.result:
            names.update(x["name"] for x in row.result.get("input", []))
            names.update(x["name"] for x in outputs(row.result))
    try:
        table = market.prices_by_name(sorted(names))
    except EsiError as exc:
        for row in rows:
            if row.result:
                row.error = f"Jita prices unavailable: {exc}"
        return
    for row in rows:
        if row.result:
            row.prices = table
            row.brokers, row.sales = settings["brokers"], settings["sales"]


def warnings(settings, rows):
    """Plausibility hints the API itself does not give."""
    out = []
    ok = [r for r in rows if r.ok]
    if settings["space"] != "wormhole" and ok and \
            all(not ((r.result.get("taxes") or {}).get("system")) for r in ok):
        out.append(f"System cost is 0 for every reaction - is '{settings['system']}' spelled "
                   "exactly like in game (case-sensitive)?")
    return out
