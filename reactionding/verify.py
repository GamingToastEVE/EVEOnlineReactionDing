"""Goes through every reaction and checks the data for correctness.

Three checks:

1. catalog  - the reaction list of the program vs. the recipes of the calculator
              (reactions.coalition.space, GET /api/v2/reactions)
2. api      - every reaction is calculated through API v2; errors are reported
3. sde      - recipes (inputs, output quantity, reaction time) of the calculator results are
              compared with CCP's official Static Data Export (developers.eveonline.com)
"""

import statistics

from .catalog import GROUPS
from .client import Client
from .engine import calculate, outputs

# Groups whose result is built from a recipe chain or reprocessing (no 1:1 SDE recipe).
CHAINED = {"chain", "improved_chain", "strong_chain", "refined", "eratic_repro"}


def _issue(kind, group, name, message):
    return {"check": kind, "group": group, "name": name, "message": message, "known": False}


# --- 1. catalog --------------------------------------------------------------

def check_catalog(recipes):
    """recipes: list from GET /api/v2/reactions."""
    site = {r["product"]["typeId"]: r for r in recipes}
    ours = {}
    for group in GROUPS.values():
        if group.key in CHAINED:
            continue  # same items as their base group
        for item_id, name in group.items:
            ours[item_id] = (group.key, name)
    issues = []
    for type_id, r in sorted(site.items(), key=lambda x: x[1]["name"]):
        if type_id not in ours:
            issues.append(_issue("catalog", r.get("reactor", "-"), r["product"]["name"],
                                 "new reaction on the calculator, not in the catalog"))
    for item_id, (key, name) in sorted(ours.items(), key=lambda x: x[1]):
        if item_id not in site:
            issues.append(_issue("catalog", key, name, "in the catalog but not on the calculator"))
        elif site[item_id]["product"]["name"] != name:
            issues.append(_issue("catalog", key, name,
                                 f"calculator calls it {site[item_id]['product']['name']!r}"))
    return issues


# --- 3. SDE ------------------------------------------------------------------

def load_sde():
    """(products, materials, times) from CCP's official SDE (see sde.py).

    products: product type id -> (recipe key, output per run)
    materials: recipe key -> {material name: quantity per run}
    times: recipe key -> reaction time in seconds"""
    from . import sde

    data = sde.load()
    products, materials, times = {}, {}, {}
    for name, r in data["reactions"].items():
        products[r["id"]] = (name, r["out"])
        materials[name] = dict(r["in"])
        times[name] = r["time"]
    return products, materials, times


def _entry(entries, item_id, name, position):
    for entry in entries:
        if entry.get("id") == item_id:
            return entry
    for entry in entries:
        if entry.get("name") == name:
            return entry
    return entries[position] if position < len(entries) else None


def check_sde(pages, sde, max_runs=None):
    """pages: {calculator: {group key: [result, ...]}} in catalog order.
    max_runs: product type id -> run limit of the formula (those jobs cannot use the full time)."""
    max_runs = max_runs or {}
    products, materials, times = sde
    issues = []
    run_seconds = []  # runs * base time; should be about equal for all reactions
    for group in GROUPS.values():
        if group.key in CHAINED:
            continue
        page = pages.get(group.calculator)
        if not page:
            continue
        for pos, (item_id, name) in enumerate(group.items):
            entry = _entry(page.get(group.web_key) or [], item_id, name, pos)
            if not entry:
                continue
            if item_id not in products:
                issues.append(_issue("sde", group.key, name, "no reaction formula in SDE"))
                continue
            blueprint, out_qty = products[item_id]
            recipe = materials.get(blueprint, {})
            runs = entry.get("runs") or 0
            got = {x["name"]: x for x in entry.get("input", [])}
            for mat in sorted(set(recipe) - set(got)):
                issues.append(_issue("sde", group.key, name, f"input {mat} missing"))
            for mat in sorted(set(got) - set(recipe)):
                issues.append(_issue("sde", group.key, name, f"unexpected input {mat}"))
            for mat, base in recipe.items():
                if mat in got and runs:
                    per_run = got[mat]["quantity"] / runs
                    # material bonuses never exceed a few percent
                    if not base * 0.9 <= per_run <= base + 1e-9:
                        issues.append(_issue(
                            "sde", group.key, name,
                            f"{mat}: {per_run:,.2f}/run, CCP SDE says {base}/run"))
            out = sum(x.get("quantity") or 0 for x in outputs(entry) if x.get("name") == name) \
                or (outputs(entry)[0].get("quantity") if outputs(entry) else None)
            if runs and out is not None and out != runs * out_qty:
                issues.append(_issue("sde", group.key, name,
                                     f"output {out:,} != {runs} runs x {out_qty} (SDE)"))
            if runs and blueprint in times and runs != max_runs.get(item_id):
                run_seconds.append((runs * times[blueprint], group.key, name, runs, times[blueprint]))
    if run_seconds:
        median = statistics.median(v for v, *_ in run_seconds)
        for value, group_key, name, runs, base in run_seconds:
            if abs(value - median) / median > 0.1:
                issues.append(_issue("sde", group_key, name,
                                     f"{runs} runs do not fit SDE reaction time {base}s "
                                     f"(off by factor {median / value:.2f})"))
    return issues


def run_all(settings, client=None, workers=4, skip_sde=False, progress=None):
    client = client or Client()
    report = {"issues": [], "stats": {}, "errors": []}
    max_runs = {}
    try:
        recipes = client.recipes()
        max_runs = {r["product"]["typeId"]: r.get("maxRuns") for r in recipes}
        report["issues"] += check_catalog(recipes)
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"recipe list of the calculator: {exc}")
    rows = calculate(settings, client=client, workers=workers, prices=False,
                     progress=(lambda row: progress(row.group, row.name)) if progress else None)
    pages = {}
    for row in rows:
        st = report["stats"].setdefault(row.group.key, {"total": 0, "api_ok": 0})
        st["total"] += 1
        if row.error:
            report["issues"].append(_issue("api", row.group.key, row.name, row.error))
            continue
        st["api_ok"] += 1
        entry = dict(row.result, id=row.item_id, name=row.name)
        pages.setdefault(row.group.calculator, {}).setdefault(row.group.web_key, []).append(entry)
    if not skip_sde:
        try:
            report["issues"] += check_sde(pages, load_sde(), max_runs)
        except Exception as exc:  # network etc.; SDE is an optional extra check
            report["errors"].append(f"SDE check skipped: {exc}")
    return report
