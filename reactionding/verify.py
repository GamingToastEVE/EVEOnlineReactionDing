"""Goes through every reaction and checks the data for correctness.

Three independent checks:

1. catalog  - the reaction list of the program vs. the live calculator pages
2. api      - every reaction is requested from the API; the answer is compared
              with the calculator page (same engine, same settings)
3. sde      - recipes (inputs, output quantity, reaction time) are compared with
              CCP's official Static Data Export (developers.eveonline.com)
"""

import statistics

from .catalog import GROUPS
from .client import ApiError, Client
from .engine import _match_web

# Groups whose page result is built from a recipe chain (no 1:1 SDE recipe).
CHAINED = {"chain", "improved_chain", "strong_chain", "refined", "eratic_repro"}


def _issue(kind, group, name, message):
    return {"check": kind, "group": group, "name": name, "message": message}


# --- 1. catalog --------------------------------------------------------------

def check_catalog(pages):
    issues = []
    for group in GROUPS.values():
        page = pages.get(group.calculator)
        if page is None or isinstance(page, Exception):
            continue
        entries = page.get(group.web_key)
        if entries is None:
            issues.append(_issue("catalog", group.key, "-", "group missing on calculator page"))
            continue
        page_names = [e.get("name") for e in entries]
        ours = [name for _, name in group.items]
        for name in sorted(set(page_names) - set(ours)):
            issues.append(_issue("catalog", group.key, name, "new reaction on page, not in catalog"))
        for name in sorted(set(ours) - set(page_names)):
            issues.append(_issue("catalog", group.key, name, "in catalog but not on page"))
        page_ids = {e.get("name"): e.get("id") for e in entries if e.get("id")}
        for item_id, name in group.items:
            if name in page_ids and page_ids[name] != item_id:
                issues.append(_issue("catalog", group.key, name,
                                     f"id {item_id} differs from page id {page_ids[name]}"))
    return issues


# --- 2. API vs page ------------------------------------------------------------

def check_api(client, settings, pages, workers=4, progress=None):
    import concurrent.futures as cf

    jobs = [(g, i, n, pos) for g in GROUPS.values() for pos, (i, n) in enumerate(g.items)]

    def run(job):
        group, item_id, name, _ = job
        try:
            return job, client.api_calculate(group, item_id, settings), None
        except ApiError as exc:
            return job, None, exc

    issues, stats = [], {}
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for (group, item_id, name, pos), api, err in pool.map(run, jobs):
            st = stats.setdefault(group.key, {"total": 0, "api_ok": 0, "match": 0})
            st["total"] += 1
            if progress:
                progress(group, name)
            if err:
                issues.append(_issue("api", group.key, name, f"API error: {err.code} {err.message}"))
                continue
            st["api_ok"] += 1
            page = pages.get(group.calculator)
            if page is None or isinstance(page, Exception):
                continue
            web = _match_web(page.get(group.web_key) or [], item_id, name, pos)
            if web is None:
                continue
            diffs = []
            for key in ("runs", "input_total", "output_total", "taxes_total", "profit"):
                a, w = api.get(key), web.get(key)
                if isinstance(a, (int, float)) and isinstance(w, (int, float)):
                    if abs(a - w) > max(1.0, abs(w) * 1e-6):
                        diffs.append(f"{key} api={a:,.2f} page={w:,.2f}")
            api_inputs = sorted(x.get("name") for x in api.get("input", []))
            web_inputs = sorted(x.get("name") for x in web.get("input", []))
            if api_inputs != web_inputs:
                diffs.append("different input materials")
            if diffs:
                issues.append(_issue("api", group.key, name, "API != calculator page: " + "; ".join(diffs)))
            else:
                st["match"] += 1
    return issues, stats


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


def check_sde(pages, sde):
    products, materials, times = sde
    issues = []
    run_seconds = []  # runs * base time; should be equal for all reactions
    for group in GROUPS.values():
        if group.key in CHAINED:
            continue
        page = pages.get(group.calculator)
        if page is None or isinstance(page, Exception):
            continue
        for pos, (item_id, name) in enumerate(group.items):
            entry = _match_web(page.get(group.web_key) or [], item_id, name, pos)
            if not entry or item_id not in products:
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
            out = (entry.get("output") or {}).get("quantity")
            if runs and out is not None and out != runs * out_qty:
                issues.append(_issue("sde", group.key, name,
                                     f"output {out:,} != {runs} runs x {out_qty} (SDE)"))
            if runs and blueprint in times:
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
    pages = {}
    for calculator in ("hybrid", "composite", "biochemical"):
        try:
            pages[calculator] = client.web_results(calculator, settings)
        except ApiError as exc:
            pages[calculator] = exc
    report = {"issues": [], "stats": {}, "errors": []}
    for calc, page in pages.items():
        if isinstance(page, Exception):
            report["errors"].append(f"calculator page {calc}: {page}")
    report["issues"] += check_catalog(pages)
    api_issues, report["stats"] = check_api(client, settings, pages, workers, progress)
    report["issues"] += api_issues
    if not skip_sde:
        try:
            report["issues"] += check_sde(pages, load_sde())
        except Exception as exc:  # network etc.; SDE is an optional extra check
            report["errors"].append(f"SDE check skipped: {exc}")
    # API problems in groups that already use the page data are handled ("known").
    for issue in report["issues"]:
        issue["known"] = issue["check"] == "api" and GROUPS[issue["group"]].source == "web"
    return report
