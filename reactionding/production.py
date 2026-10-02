"""Cost chain (spreadsheet sheet 7) and production planner (sheet 8.1).

Reaction and component recipes come from CCP's official Static Data Export (sde.py),
prices live from ESI (Jita 4-4: Buy = highest buy order, Sell = lowest sell order,
Split = middle).

Material efficiency is applied the way EVE does it, per job:
``max(runs, ceil(runs * quantity * (1 - bonus)))``.
"""

import math
import re

from . import sde
from .market import MODES, prices_by_name

FUEL_BLOCKS = ("Helium Fuel Block", "Hydrogen Fuel Block", "Nitrogen Fuel Block", "Oxygen Fuel Block")

RIG_BONUS = {0: 0.0, 1: 0.02, 2: 0.024}
SPACE_MULTIPLIER = {"nullsec": 1.1, "wormhole": 1.1, "lowsec": 1.0}


def reaction_me(settings):
    """Material bonus of the refinery rigs, e.g. 0.0264 for T2 rigs in nullsec."""
    return RIG_BONUS[settings["rigs"]] * SPACE_MULTIPLIER[settings["space"]]


def job_quantity(per_run, runs, bonus):
    if per_run <= 0 or runs <= 0:
        return 0
    return max(runs, math.ceil(round(runs * per_run * (1 - bonus), 6)))


def load_components(recipes, data=None):
    """T2 and capital T2 components built only from complex reaction products."""
    data = data or sde.load()
    complex_ = {n for n, r in recipes.items() if r["group"] == "complex"}
    return {name: {"name": name, "capital": c["capital"], "outputPerRun": c["out"],
                   "materials": c["in"]}
            for name, c in sorted(data["components"].items()) if set(c["in"]) <= complex_}


def _ordered(recipes, group):
    return sorted(n for n, r in recipes.items() if r["group"] == group)


# --- cost chain (sheet 7) -------------------------------------------------------

def cost_chain(recipes, settings, prices=None, components=None):
    """Material cost per unit when every intermediate is produced yourself."""
    components = components if components is not None else load_components(recipes)
    bonus = reaction_me(settings)
    comp_bonus = settings["componentMe"] / 100.0
    names = set(recipes) | set(components)
    for r in recipes.values():
        names.update(r["in"])
    prices = prices or prices_by_name(sorted(names))

    cost = {}  # name -> {mode: cost per unit}

    def unit_cost(name, mode):
        """Own production cost for reaction products, market price for everything else."""
        if name in cost:
            return cost[name][mode]
        return (prices.get(name) or {}).get(mode)

    def reaction_rows(group):
        rows = []
        for name in _ordered(recipes, group):
            r = recipes[name]
            row_cost, missing = {}, {}
            for mode in MODES:
                total = 0.0
                for mat, qty in r["in"].items():
                    price = unit_cost(mat, mode)
                    note = (prices.get(mat) or {}).get("note") if mat not in cost else None
                    if note or price is None:
                        missing[mat] = note or "no price"
                    price = price or 0.0
                    total += qty * (1 - bonus) * price
                row_cost[mode] = total / r["out"]
            cost[name] = row_cost
            rows.append(_row(name, group, r["out"], row_cost, prices.get(name), missing))
        return rows

    simple = reaction_rows("simple")
    complex_ = reaction_rows("complex")
    hybrid = reaction_rows("hybrid")
    comps = []
    for name, c in components.items():
        row_cost, missing = {}, {}
        for mode in MODES:
            total = 0.0
            for mat, qty in c["materials"].items():
                price = unit_cost(mat, mode)
                if price is None:
                    missing[mat] = "no price"
                price = price or 0.0
                total += qty * (1 - comp_bonus) * price
            row_cost[mode] = total / c["outputPerRun"]
        comps.append(_row(name, "capital" if c["capital"] else "component", c["outputPerRun"],
                          row_cost, prices.get(name), missing))
    return {"simple": simple, "complex": complex_, "hybrid": hybrid,
            "components": [r for r in comps if r["group"] == "component"],
            "capital": [r for r in comps if r["group"] == "capital"],
            "reactionMe": bonus, "componentMe": comp_bonus}


def _row(name, group, out, cost, market, missing):
    market = dict(market or {"note": "no price"})
    missing = dict(missing)
    if market.get("note"):
        missing[name] = market["note"]
    market = {m: market.get(m) for m in MODES}
    profit = {m: (market[m] - cost[m]) if market[m] is not None else None for m in MODES}
    return {
        "name": name, "group": group, "outputPerRun": out,
        "price": market, "cost": cost, "profit": profit,
        "margin": {m: (market[m] / cost[m] - 1) * 100 if market[m] and cost[m] else None for m in MODES},
        "profitPerRun": {m: profit[m] * out if profit[m] is not None else None for m in MODES},
        "missingPrices": dict(sorted(missing.items())),
    }


# --- production planner (sheet 8.1) ---------------------------------------------

def parse_stock(text):
    """Item list pasted from EVE (inventory, contracts, ...): 'Name<TAB>Quantity...' per line.

    Also accepts 'Name;Quantity', 'Name,Quantity' and 'Quantity x Name'. Quantities may use
    '.', ',' or spaces as thousands separators. Repeated items are added up."""
    stock = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"\t|;|\s{2,}", line)
        name, qty = None, None
        if len(parts) >= 2:
            name, qty = parts[0].strip(), _number(parts[1])
        if qty is None:
            m = re.match(r"^([\d.,' ]+)\s*x\s+(.+)$", line)
            if m:
                name, qty = m.group(2).strip(), _number(m.group(1))
        if qty is None:
            m = re.match(r"^(.+?)[\s,]+([\d.,' ]+)$", line)
            if m:
                name, qty = m.group(1).strip(), _number(m.group(2))
        if name and qty is not None:
            stock[name] = stock.get(name, 0) + qty
    return stock


def _number(text):
    digits = re.sub(r"[.,'  ]", "", str(text).strip())
    return int(digits) if digits.isdigit() else None


def plan(recipes, settings, state, prices=None, components=None):
    """Production plan: complex/hybrid jobs -> simple jobs -> moon goo + fuel to buy.

    state = {"runsPerJob": 544, "jobs": {reaction: jobs}, "components": {component: units},
             "stock": "pasted text"}
    """
    components = components if components is not None else load_components(recipes)
    runs = int(state.get("runsPerJob") or 544)
    jobs_manual = {k: int(v) for k, v in (state.get("jobs") or {}).items() if int(v or 0) > 0}
    comp_plan = {k: int(v) for k, v in (state.get("components") or {}).items() if int(v or 0) > 0}
    stock = parse_stock(state.get("stock", ""))
    bonus = reaction_me(settings)
    comp_bonus = settings["componentMe"] / 100.0
    unknown = sorted(k for k in list(jobs_manual) + list(comp_plan)
                     if k not in recipes and k not in components)

    # 1. components -> complex reaction products needed
    comp_need = {}
    for name, units in comp_plan.items():
        c = components.get(name)
        if not c:
            continue
        comp_runs = math.ceil(units / c["outputPerRun"])
        for mat, qty in c["materials"].items():
            comp_need[mat] = comp_need.get(mat, 0) + job_quantity(qty, comp_runs, comp_bonus)

    # 2. complex / hybrid jobs (manual + automatic for components)
    top = []
    jobs = {}
    for group in ("complex", "hybrid"):
        for name in _ordered(recipes, group):
            r = recipes[name]
            per_job = runs * r["out"]
            need = comp_need.get(name, 0)
            short = max(need - stock.get(name, 0), 0)
            auto = math.ceil(short / per_job) if short else 0
            manual = jobs_manual.get(name, 0)
            total = manual + auto
            jobs[name] = total
            if total or need:
                top.append({"name": name, "group": group, "componentNeed": need,
                            "stock": stock.get(name, 0), "autoJobs": auto, "manualJobs": manual,
                            "jobs": total, "output": total * per_job})

    # 3. simple reactions needed by those jobs
    simple_need = {}
    for name, n in jobs.items():
        if not n:
            continue
        for mat, qty in recipes[name]["in"].items():
            if recipes.get(mat, {}).get("group") == "simple":
                simple_need[mat] = simple_need.get(mat, 0) + n * job_quantity(qty, runs, bonus)
    simple = []
    for name in _ordered(recipes, "simple"):
        r = recipes[name]
        per_job = runs * r["out"]
        need = simple_need.get(name, 0)
        short = max(need - stock.get(name, 0), 0)
        n = math.ceil(short / per_job) + jobs_manual.get(name, 0)
        jobs[name] = n
        if need or n:
            simple.append({"name": name, "need": need, "stock": stock.get(name, 0), "short": short,
                           "jobs": n, "output": n * per_job, "surplus": n * per_job - short})

    # 4. raw materials (moon goo, fuel blocks, hybrid inputs) for all jobs
    raw_need = {}
    for name, n in jobs.items():
        if not n:
            continue
        for mat, qty in recipes[name]["in"].items():
            if recipes.get(mat, {}).get("group") == "simple":
                continue  # produced above
            raw_need[mat] = raw_need.get(mat, 0) + n * job_quantity(qty, runs, bonus)

    names = set(raw_need) | {t["name"] for t in top} | set(comp_plan) | set(jobs_manual)
    prices = prices or prices_by_name(sorted(names))
    shopping = []
    totals = {m: 0.0 for m in MODES}
    missing = {}
    for name in sorted(raw_need, key=lambda n: (n in FUEL_BLOCKS, n)):
        need = raw_need[name]
        have = stock.get(name, 0)
        buy = max(need - have, 0)
        p = prices.get(name) or {}
        cost = {m: buy * p[m] if p.get(m) is not None else None for m in MODES}
        if p.get("note"):
            missing[name] = p["note"]
        for m in MODES:
            totals[m] += cost[m] or 0.0
        shopping.append({"name": name, "need": need, "stock": have, "toBuy": buy,
                         "price": {m: p.get(m) for m in MODES}, "cost": cost})
    value = {m: 0.0 for m in MODES}
    for t in top:
        p = prices.get(t["name"]) or {}
        t["value"] = {m: t["output"] * p[m] if p.get(m) is not None else None for m in MODES}
        for m in MODES:
            value[m] += t["value"][m] or 0.0
    return {"runsPerJob": runs, "reactionMe": bonus, "componentMe": comp_bonus,
            "top": top, "simple": simple, "shopping": shopping, "shoppingTotal": totals,
            "productionValue": value, "stockItems": len(stock), "unknown": unknown,
            "missingPrices": missing, "prices": prices, "jobsPerReaction": jobs}


def preview(recipes, settings, state, components=None, prices=None):
    """Quick cost/profit estimate for a whole run (used by the plan creator).

    Costs = all materials to buy for every stage (minus stock). Value = what comes out at
    the end: the ordered components, complex/hybrid products not used for them and the
    ordered simple reactions. Job install costs and market fees are not included."""
    components = components if components is not None else load_components(recipes)
    result = plan(recipes, settings, state, prices=prices, components=components)
    prices, runs = result["prices"], result["runsPerJob"]
    manual = {k: int(v) for k, v in (state.get("jobs") or {}).items() if int(v or 0) > 0}
    comps = {k: int(v) for k, v in (state.get("components") or {}).items() if int(v or 0) > 0}
    products = {}
    for name, units in comps.items():
        if name in components:
            products[name] = products.get(name, 0) + units
    for t in result["top"]:
        rest = t["output"] - t["componentNeed"]
        if rest > 0:
            products[t["name"]] = products.get(t["name"], 0) + rest
    for name, n in manual.items():
        if recipes.get(name, {}).get("group") == "simple":
            products[name] = products.get(name, 0) + n * runs * recipes[name]["out"]
    value = {m: 0.0 for m in MODES}
    lines = []
    for name, qty in sorted(products.items()):
        p = prices.get(name) or {}
        v = {m: qty * p[m] if p.get(m) is not None else None for m in MODES}
        for m in MODES:
            value[m] += v[m] or 0.0
        lines.append({"name": name, "quantity": qty, "value": v})
    cost = result["shoppingTotal"]
    stages = 3 if comps else 2 if any(t["group"] == "complex" and t["jobs"] for t in result["top"]) else 1
    jobs = sum(result["jobsPerReaction"].values())
    return {"cost": cost, "value": value, "products": lines,
            "profit": {m: value[m] - cost[m] for m in MODES},
            "margin": {m: (value[m] / cost[m] - 1) * 100 if cost[m] else None for m in MODES},
            "months": stages, "jobs": jobs, "shoppingItems": len(result["shopping"]),
            "unknown": result["unknown"], "missingPrices": result["missingPrices"]}
