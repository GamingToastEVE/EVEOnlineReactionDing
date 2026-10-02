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


def _side(result, key):
    """(value, market fees) of the input or output side of one calculator result."""
    market = (result.get("taxes") or {}).get("market") or {}
    fees = (market.get("total") or {}).get("inputs" if key == "input" else "output") or 0.0
    return result.get(f"{key}_total") or 0.0, fees


@dataclass
class Row:
    """One reaction. The calculator is asked twice: once with buy prices for the inputs and
    sell prices for the output (``a``), once the other way round (``b``). Every combination of
    Jita Buy / Split / Sell is composed from these two; Split is the middle of Buy and Sell
    (prices and market fees)."""

    group: object
    item_id: int
    name: str
    source: str
    a: dict = field(default=None, repr=False)  # input buy, output sell
    b: dict = field(default=None, repr=False)  # input sell, output buy
    error: str = ""
    modes: tuple = ("buy", "sell")  # (input method, output method) used for the properties

    @property
    def result(self):
        return self.a

    @property
    def ok(self):
        return self.a is not None and self.b is not None

    def view(self, input_mode=None, output_mode=None):
        """Totals for one combination of input and output price method."""
        if not self.ok:
            return None
        input_mode = input_mode or self.modes[0]
        output_mode = output_mode or self.modes[1]
        sides = {
            "input": {"buy": _side(self.a, "input"), "sell": _side(self.b, "input")},
            "output": {"sell": _side(self.a, "output"), "buy": _side(self.b, "output")},
        }
        for side in sides.values():
            side["split"] = tuple((x + y) / 2 for x, y in zip(side["buy"], side["sell"]))
        inputs, input_fees = sides["input"][input_mode]
        output, output_fees = sides["output"][output_mode]
        install = ((self.a.get("taxes") or {}).get("total") or {}).get("install") or 0.0
        taxes = install + input_fees + output_fees
        profit = output - inputs - taxes
        minutes = (self.a.get("cycle_data") or {}).get("total_time")
        return {
            "inputs": inputs, "inputFees": input_fees, "output": output, "outputFees": output_fees,
            "install": install, "taxes": taxes, "profit": profit,
            "profitPercent": profit / output * 100 if output else None,
            "profitPerHour": profit / (minutes / 60.0) if minutes else None,
        }

    def _view_value(self, key):
        v = self.view()
        return v[key] if v else None

    @property
    def profit(self):
        return self._view_value("profit")

    @property
    def profit_percent(self):
        return self._view_value("profitPercent")

    @property
    def inputs_total(self):
        return self._view_value("inputs")

    @property
    def taxes_total(self):
        return self._view_value("taxes")

    @property
    def output_total(self):
        return self._view_value("output")

    @property
    def profit_per_hour(self):
        return self._view_value("profitPerHour")

    @property
    def runs(self):
        return (self.a or {}).get("runs")

    def unit_prices(self):
        """{item name: {"buy": p, "split": p, "sell": p}} per unit, inputs and output."""
        prices = {}
        for item_a, item_b in zip(self.a.get("input", []), self.b.get("input", [])):
            qty = item_a.get("quantity") or 0
            if qty:
                buy, sell = item_a["price"] / qty, item_b["price"] / qty
                prices[item_a["name"]] = {"buy": buy, "split": (buy + sell) / 2, "sell": sell}
        for out_a, out_b in zip(outputs(self.a), outputs(self.b)):
            qty = out_a.get("quantity") or 0
            if qty:
                sell, buy = out_a["price"] / qty, out_b["price"] / qty
                prices[out_a["name"]] = {"buy": buy, "split": (buy + sell) / 2, "sell": sell}
        return prices

    def to_dict(self, full=False):
        data = {
            "calculator": self.group.calculator,
            "group": self.group.key,
            "groupTitle": self.group.title,
            "id": self.item_id,
            "name": self.name,
            "source": self.source,
            "inputMethod": self.modes[0],
            "outputMethod": self.modes[1],
            "inputs": self.inputs_total,
            "taxes": self.taxes_total,
            "output": self.output_total,
            "profit": self.profit,
            "profitPercent": self.profit_percent,
            "profitPerHour": self.profit_per_hour,
            "runs": self.runs,
            "error": self.error,
        }
        if full and self.ok:
            data["views"] = {f"{i}|{o}": self.view(i, o) for i in MODES for o in MODES}
            data["prices"] = self.unit_prices()
            data["result"] = self.a
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
    """Return one Row per reaction (see Row for how Buy / Split / Sell are derived).

    source: ``auto`` (API, page data for groups the API cannot handle),
    ``api`` (API only) or ``web`` (page data only).
    """
    client = client or Client()
    groups = groups_for(groups) if groups is None or isinstance(groups[0], str) else groups
    modes = (settings["input"], settings["output"])
    variants = {"a": dict(settings, input="buy", output="sell"),
                "b": dict(settings, input="sell", output="buy")}
    rows, api_jobs, web_groups = [], [], []
    for group in groups:
        use = group.source if source == "auto" else source
        if use == "api":
            for item_id, name in group.items:
                row = Row(group, item_id, name, "api", modes=modes)
                rows.append(row)
                api_jobs += [(row, "a"), (row, "b")]
        else:
            web_groups.append(group)

    web_pages = {}
    for calculator in sorted({g.calculator for g in web_groups}):
        for key, values in variants.items():
            try:
                web_pages[calculator, key] = client.web_results(calculator, values)
            except ApiError as exc:
                web_pages[calculator, key] = exc
    for group in web_groups:
        for position, (item_id, name) in enumerate(group.items):
            row = Row(group, item_id, name, "web", modes=modes)
            for key in variants:
                page = web_pages[group.calculator, key]
                if isinstance(page, ApiError):
                    row.error = str(page)
                    continue
                entry = _match_web(page.get(group.web_key) or [], item_id, name, position)
                if entry is None:
                    row.error = "missing in calculator page data"
                setattr(row, key, entry)
            rows.append(row)
            if progress:
                progress(row)

    def run(job):
        row, key = job
        try:
            setattr(row, key, client.api_calculate(row.group, row.item_id, variants[key]))
        except ApiError as exc:
            row.error = str(exc)
        return job

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for row, key in pool.map(run, api_jobs):
            if progress and key == "b":
                progress(row)

    for row in rows:
        if row.ok and _quantities(row.a) != _quantities(row.b):
            row.error = "calculator returned different quantities for buy and sell prices"
            row.b = None
    order = {g.key: i for i, g in enumerate(groups)}
    rows.sort(key=lambda r: (order[r.group.key], [i for i, _ in r.group.items].index(r.item_id)))
    return rows


def _quantities(result):
    return ([(x.get("name"), x.get("quantity")) for x in result.get("input", [])],
            [(x.get("name"), x.get("quantity")) for x in outputs(result)], result.get("runs"))


def warnings(settings, rows):
    """Plausibility hints the API itself does not give."""
    out = []
    ok = [r for r in rows if r.ok]
    if settings["space"] != "wormhole" and ok and \
            all(not ((r.a.get("taxes") or {}).get("system")) for r in ok):
        out.append(f"System cost is 0 for every reaction - is '{settings['system']}' spelled "
                   "exactly like in game (case-sensitive)?")
    return out
