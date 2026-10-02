"""Monthly multi-stage production planner with tracking (pipeline like sheet 8.1).

One reaction job (544 runs by default) takes about a month, so production runs as a
pipeline. Every month can start a new *run* (the month's orders). How long a run takes
depends on what is ordered - 1 to 3 months:

    stage 1  month M     simple and hybrid reactions (raw materials only), plus the simple
                         reactions needed for the run's complex reactions
    stage 2  month M+1   complex reactions of the run (from the stage 1 output)
    stage 3  month M+2   components of the run (from the stage 2 output)

So a month shows stage 3 of the run started in M-2, stage 2 of the run from M-1 and
stage 1 of the run started in M. Reaction
slots are limited: jobs carried over that are already running come first, then stage 2,
then carried jobs that were not started, then stage 1. Jobs that do not fit are postponed.

Every month can start a new complete run from zero (its orders); a month without orders
starts nothing new. Per month the user tracks started / finished jobs and purchases
(quantity and price paid). Closing a month carries unfinished and postponed jobs into the
next month and can repeat the month's orders as the next run. The stock is pasted from EVE
at the start of every month.

campaign = {
  "runsPerJob": 544, "slots": 30,
  "months": [{
    "id": "2026-10", "closed": False,
    "orders": {"jobs": {reaction: jobs}, "components": {component: units}},
    "stock": "pasted EVE inventory",
    "carry": [{"stage": 2, "name": reaction, "count": n, "started": n}],
    "track": {"<stage>|<name>": {"started": n, "done": n}},
    "bought": {item: {"qty": n, "price": isk per unit}},
  }]
}
"""

import datetime
import math

from .market import MODES, prices_by_name
from .production import FUEL_BLOCKS, job_quantity, parse_stock, reaction_me

STAGE_NAMES = {1: "Simple + hybrid reactions", 2: "Complex reactions", 3: "Components"}


def new_campaign(today=None):
    today = today or datetime.date.today()
    return {"runsPerJob": 544, "slots": 30, "months": [new_month(f"{today.year}-{today.month:02d}")]}


def new_month(month_id, orders=None):
    return {"id": month_id, "closed": False,
            "orders": orders or {"jobs": {}, "components": {}},
            "stock": "", "carry": [], "track": {}, "bought": {}, "checks": {}}


def next_month_id(month_id):
    year, month = map(int, month_id.split("-"))
    return f"{year + (month == 12)}-{month % 12 + 1:02d}"


def _orders(campaign, index):
    if 0 <= index < len(campaign["months"]):
        o = campaign["months"][index].get("orders") or {}
        return ({k: int(v) for k, v in (o.get("jobs") or {}).items() if int(v or 0) > 0},
                {k: int(v) for k, v in (o.get("components") or {}).items() if int(v or 0) > 0})
    return {}, {}


def _component_need(components, comp_orders, comp_bonus):
    """Complex products needed to build the ordered components."""
    need = {}
    for name, units in comp_orders.items():
        c = components.get(name)
        if not c:
            continue
        runs = math.ceil(units / c["outputPerRun"])
        for mat, qty in c["materials"].items():
            need[mat] = need.get(mat, 0) + job_quantity(qty, runs, comp_bonus)
    return need


def _wave_reaction_jobs(recipes, components, campaign, index, comp_bonus, stock=None):
    """Complex jobs of one run: ordered jobs + jobs for the run's components.

    The component share is reduced by ``stock`` (only known for the month being executed)."""
    runs = int(campaign.get("runsPerJob") or 544)
    jobs, comps = _orders(campaign, index)
    need = _component_need(components, comps, comp_bonus)
    stock = stock or {}
    result = {}
    for name, r in recipes.items():
        if r["group"] != "complex":
            continue
        short = max(need.get(name, 0) - stock.get(name, 0), 0)
        auto = math.ceil(short / (runs * r["out"])) if short else 0
        total = jobs.get(name, 0) + auto
        if total:
            result[name] = {"ordered": jobs.get(name, 0), "auto": auto, "forComponents": need.get(name, 0)}
    return result


def plan_month(recipes, components, settings, campaign, index, prices=None):
    """Everything for one month: stages, slot usage, shopping list, tracking state, totals."""
    month = campaign["months"][index]
    runs = int(campaign.get("runsPerJob") or 544)
    slots = int(campaign.get("slots") or 0)
    bonus = reaction_me(settings)
    comp_bonus = settings["componentMe"] / 100.0
    stock = parse_stock(month.get("stock", ""))
    available = dict(stock)  # consumed step by step

    def take(name, qty):
        have = available.get(name, 0)
        used = min(have, qty)
        available[name] = have - used
        return used

    # stage 3: components of the run from M-2 plus carried components (no reaction slots).
    # Only as many as the complex products in stock allow.
    track = month.get("track") or {}
    comp_units = {}
    for c in month.get("carry") or []:
        if int(c["stage"]) == 3:
            comp_units[c["name"]] = comp_units.get(c["name"], 0) + int(c["count"])
    for name, units in _orders(campaign, index - 2)[1].items():
        comp_units[name] = comp_units.get(name, 0) + units
    stage3 = []
    for name, units in sorted(comp_units.items()):
        c = components.get(name)
        if not c:
            continue
        per_run = c["outputPerRun"]
        runs_wanted = math.ceil(units / per_run)
        runs_possible = runs_wanted
        for mat, qty in c["materials"].items():
            while runs_possible and job_quantity(qty, runs_possible, comp_bonus) > available.get(mat, 0):
                runs_possible -= 1
        buildable = min(units, runs_possible * per_run)
        inputs = []
        for mat, qty in c["materials"].items():
            need = job_quantity(qty, runs_wanted, comp_bonus)
            used = take(mat, job_quantity(qty, math.ceil(buildable / per_run), comp_bonus)) if buildable else 0
            inputs.append({"name": mat, "need": need, "fromStock": used, "missing": need - used})
        done = min(int((track.get(f"3|{name}") or {}).get("done") or 0), units)
        stage3.append({"stage": 3, "key": f"3|{name}", "name": name, "units": units, "buildable": buildable,
                       "blocked": units - buildable, "done": done, "inputs": inputs})

    # reaction job lines: (stage, name) -> line
    lines = {}

    def line(stage, name, wave):
        key = f"{stage}|{name}"
        if key not in lines:
            lines[key] = {"key": key, "stage": stage, "name": name, "wave": wave, "count": 0,
                          "running": 0, "carried": 0, "ordered": 0, "auto": 0, "forComponents": 0}
        return lines[key]

    for c in month.get("carry") or []:
        if int(c["stage"]) == 3:
            continue
        ln = line(int(c["stage"]), c["name"], "carried")
        ln["count"] += int(c["count"])
        ln["carried"] += int(c["count"])
        ln["running"] += int(c.get("started") or 0)

    # stage 2: complex reactions of the run from M-1 (stock reduces the component share)
    for name, j in _wave_reaction_jobs(recipes, components, campaign, index - 1, comp_bonus, available).items():
        ln = line(2, name, index - 1)
        ln["count"] += j["ordered"] + j["auto"]
        ln.update(ordered=j["ordered"], auto=j["auto"], forComponents=j["forComponents"])

    # stage 1: simple reactions for the complex / hybrid jobs of wave M (run next month)
    next_jobs = _wave_reaction_jobs(recipes, components, campaign, index, comp_bonus)
    simple_need = {}
    for name, j in next_jobs.items():
        n = j["ordered"] + j["auto"]
        for mat, qty in recipes[name]["in"].items():
            if recipes.get(mat, {}).get("group") == "simple":
                simple_need[mat] = simple_need.get(mat, 0) + n * job_quantity(qty, runs, bonus)

    simple_inputs = lambda name: {mat: job_quantity(qty, runs, bonus)  # noqa: E731
                                  for mat, qty in recipes[name]["in"].items()
                                  if recipes.get(mat, {}).get("group") == "simple"}
    used = 0

    def room(n):
        return n if not slots else max(min(n, slots - used), 0)

    for ln in lines.values():
        ln.update(scheduled=ln["running"], blocked=0, postponed=0)
        used += ln["running"]

    # stage 2 runs only with the simple products that are really in stock (finished last month)
    for want_carried in (True, False):
        for ln in sorted((x for x in lines.values() if x["stage"] == 2), key=lambda x: x["name"]):
            pending = (ln["carried"] - ln["running"]) if want_carried else (ln["count"] - ln["carried"])
            if pending <= 0:
                continue
            per_job = simple_inputs(ln["name"])
            feasible = min([available.get(m, 0) // q for m, q in per_job.items()] or [pending])
            ready = min(pending, feasible)
            n = room(ready)
            for mat, q in per_job.items():
                take(mat, n * q)
            ln["scheduled"] += n
            ln["blocked"] += pending - ready
            ln["postponed"] += ready - n
            used += n

    # stage 1: simple reactions for the complex jobs of this month's run, on the stock that is left
    for name, need in simple_need.items():
        r = recipes[name]
        short = max(need - available.get(name, 0), 0)
        jobs = math.ceil(short / (runs * r["out"]))
        if jobs:
            ln = line(1, name, index)
            ln.setdefault("scheduled", 0)
            ln.setdefault("blocked", 0)
            ln.setdefault("postponed", 0)
            ln["count"] += jobs
            ln["auto"] += jobs
            ln["need"] = need
    ordered_now, _ = _orders(campaign, index)
    for name, n in ordered_now.items():
        if recipes.get(name, {}).get("group") in ("simple", "hybrid"):  # one-month runs
            ln = line(1, name, index)
            ln.setdefault("scheduled", 0)
            ln.setdefault("blocked", 0)
            ln.setdefault("postponed", 0)
            ln["count"] += n
            ln["ordered"] += n
    for want_carried in (True, False):
        for ln in sorted((x for x in lines.values() if x["stage"] == 1), key=lambda x: x["name"]):
            pending = (ln["carried"] - ln["running"]) if want_carried else (ln["count"] - ln["carried"])
            if pending <= 0:
                continue
            n = room(pending)
            ln["scheduled"] += n
            ln["postponed"] += pending - n
            used += n

    for ln in lines.values():
        ln["outputPerJob"] = runs * recipes[ln["name"]]["out"]
        tr = track.get(ln["key"]) or {}
        # never more than there are jobs (typos in the tracking fields)
        ln["done"] = min(int(tr.get("done") or 0), ln["count"])
        ln["started"] = min(max(int(tr.get("started") or 0), ln["running"], ln["done"]), ln["count"])

    # raw materials and fuel for the jobs installed this month (stage 2 simple inputs come from stock)
    raw_need = {}
    for ln in lines.values():
        to_install = ln["scheduled"] - ln["running"]
        if to_install <= 0:
            continue
        for mat, qty in recipes[ln["name"]]["in"].items():
            if ln["stage"] == 2 and recipes.get(mat, {}).get("group") == "simple":
                continue
            raw_need[mat] = raw_need.get(mat, 0) + to_install * job_quantity(qty, runs, bonus)

    names = set(raw_need) | {ln["name"] for ln in lines.values()} | {s["name"] for s in stage3}
    prices = prices or prices_by_name(sorted(names))
    bought = month.get("bought") or {}

    shopping = []
    totals = {m: 0.0 for m in MODES}
    spent = 0.0
    for name in sorted(raw_need, key=lambda n: (n in FUEL_BLOCKS, n)):
        need = raw_need[name]
        have = take(name, need)
        to_buy = need - have
        p = prices.get(name) or {}
        b = bought.get(name) or {}
        qty_bought = int(b.get("qty") or 0)
        paid = float(b.get("price") or 0)
        spent += qty_bought * paid
        remaining = max(to_buy - qty_bought, 0)
        cost = {m: remaining * p[m] if p.get(m) is not None else None for m in MODES}
        for m in MODES:
            totals[m] += cost[m] or 0.0
        shopping.append({"name": name, "kind": "raw", "need": need, "stock": have, "toBuy": to_buy,
                         "bought": qty_bought, "paid": paid, "remaining": remaining,
                         "price": {m: p.get(m) for m in MODES}, "cost": cost, "note": p.get("note")})

    def value(name, qty):
        p = prices.get(name) or {}
        return {m: qty * p[m] if p.get(m) is not None else None for m in MODES}

    produced = {m: 0.0 for m in MODES}
    planned_value = {m: 0.0 for m in MODES}
    for ln in lines.values():
        ln["value"] = value(ln["name"], ln["scheduled"] * ln["outputPerJob"])
        ln["doneValue"] = value(ln["name"], ln["done"] * ln["outputPerJob"])
        for m in MODES:
            planned_value[m] += ln["value"][m] or 0.0
            produced[m] += ln["doneValue"][m] or 0.0
    for s3 in stage3:
        s3["value"] = value(s3["name"], s3["buildable"])
        s3["doneValue"] = value(s3["name"], s3["done"])
        for m in MODES:
            planned_value[m] += s3["value"][m] or 0.0
            produced[m] += s3["doneValue"][m] or 0.0

    stages = {stage: sorted((ln for ln in lines.values() if ln["stage"] == stage), key=lambda x: x["name"])
              for stage in (1, 2)}
    result = {
        "month": month["id"], "index": index, "closed": month.get("closed", False),
        "runsPerJob": runs, "slots": slots, "slotsUsed": used, "reactionMe": bonus,
        "stage1": stages[1], "stage2": stages[2], "stage3": stage3,
        "blocked": sum(ln["blocked"] for ln in lines.values()),
        "shopping": shopping, "shoppingTotal": totals, "spent": spent,
        "plannedValue": planned_value, "producedValue": produced,
        "postponed": sum(ln["postponed"] for ln in lines.values()),
        "stockItems": len(stock),
        "missingPrices": {n: p["note"] for n, p in prices.items() if (p or {}).get("note")},
        "waves": {"stage1": _wave_label(campaign, index), "stage2": _wave_label(campaign, index - 1),
                  "stage3": _wave_label(campaign, index - 2)},
    }
    result["checklist"] = checklist(month, result)
    return result


def checklist(month, plan):
    """To-do list for the month. Items tick themselves when the tracking says so; every item can
    also be ticked by hand (stored in month["checks"])."""
    checks = month.get("checks") or {}
    items = []

    def add(key, text, auto=False):
        items.append({"key": key, "text": text, "auto": bool(auto), "done": bool(auto or checks.get(key))})

    add("stock", f"Paste the stock of {month['id']} from EVE", plan["stockItems"] > 0)
    if plan["shopping"]:
        add("buy", f"Buy the shopping list ({len(plan['shopping'])} items, Copy for Multibuy)",
            all(x["remaining"] == 0 for x in plan["shopping"]))
    for stage in (2, 1):
        for ln in plan[f"stage{stage}"]:
            new_jobs = ln["scheduled"] - ln["running"]
            if new_jobs > 0:
                add(f"install|{ln['key']}", f"Stage {stage}: install {new_jobs} × {ln['name']}",
                    ln["started"] >= ln["scheduled"])
    for s3 in plan["stage3"]:
        if s3["buildable"]:
            add(f"build|{s3['key']}", f"Stage 3: build {s3['buildable']} × {s3['name']}", s3["done"] >= s3["buildable"])
    if plan["blocked"]:
        add("blocked", f"{plan['blocked']} jobs blocked: simple products missing in stock - they move to next month")
    jobs = plan["stage1"] + plan["stage2"]
    if jobs:
        add("deliver", "Deliver all finished jobs and mark them as done",
            all(ln["done"] >= ln["scheduled"] for ln in jobs))
    add("close", f"Close {month['id']} (unfinished jobs move to the next month)", month.get("closed"))
    return items


def _wave_label(campaign, index):
    return campaign["months"][index]["id"] if 0 <= index < len(campaign["months"]) else None


def close_month(campaign, index, plan, repeat_orders=False):
    """Close month ``index`` and open the next one.

    Unfinished and postponed jobs are carried over. ``repeat_orders`` starts the same orders
    again as a new run in the next month; otherwise the next month starts without a new run."""
    month = campaign["months"][index]
    carry = []
    for ln in plan["stage1"] + plan["stage2"]:
        unfinished = ln["count"] - ln["done"]
        if unfinished > 0:
            # jobs already started keep running in the next month (no new materials needed)
            running = max(min(ln["started"] - ln["done"], unfinished), 0)
            carry.append({"stage": ln["stage"], "name": ln["name"], "count": unfinished, "started": running})
    for s3 in plan["stage3"]:
        if s3["units"] - s3["done"] > 0:
            carry.append({"stage": 3, "name": s3["name"], "count": s3["units"] - s3["done"], "started": 0})
    month["closed"] = True
    month["summary"] = {"spent": plan["spent"], "producedValue": plan["producedValue"],
                        "jobsDone": sum(ln["done"] for ln in plan["stage1"] + plan["stage2"]),
                        "unitsBuilt": sum(s3["done"] for s3 in plan["stage3"]),
                        "jobsCarried": sum(c["count"] for c in carry)}
    if index == len(campaign["months"]) - 1:
        nxt = new_month(next_month_id(month["id"]), orders=_copy_orders(month) if repeat_orders else None)
        nxt["carry"] = carry
        campaign["months"].append(nxt)
    else:
        campaign["months"][index + 1]["carry"] = carry
    return campaign


def _copy_orders(month):
    o = month.get("orders") or {}
    return {"jobs": dict(o.get("jobs") or {}), "components": dict(o.get("components") or {})}


def overview(campaign):
    """Per month: jobs done, money spent, value produced (stored when the month was closed)."""
    rows = []
    for m in campaign["months"]:
        s = m.get("summary") or {}
        rows.append({"month": m["id"], "closed": m.get("closed", False),
                     "jobsDone": s.get("jobsDone"), "jobsCarried": s.get("jobsCarried"),
                     "spent": s.get("spent"), "producedValue": s.get("producedValue"),
                     "profit": {k: v - (s.get("spent") or 0) for k, v in (s.get("producedValue") or {}).items()}})
    return rows
