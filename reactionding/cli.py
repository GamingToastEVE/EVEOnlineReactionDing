"""Command line interface: ``python -m reactionding <command>``."""

import argparse
import csv
import json
import sys
from pathlib import Path

from . import esi
from . import settings as settings_mod
from .catalog import CALCULATORS, GROUPS, find_items, groups_for
from .client import ApiError, Client
from .engine import MODES, calculate, outputs, warnings

SETTINGS_FILE = "settings.json"


def fmt_isk(value):
    return "-" if value is None else f"{value:,.0f}"


def fmt_unit(value):
    return "-" if value is None else f"{value:,.2f}"


def fmt_pct(value):
    if value is None:
        return "-"
    if value in (float("inf"), float("-inf")) or value != value:
        return "-inf %" if value == float("-inf") else "n/a"
    return f"{value:.2f} %"


def add_settings_args(parser):
    group = parser.add_argument_group("settings (override settings.json)")
    for key, (kind, rule, label) in settings_mod.SCHEMA.items():
        extra = f" [{'|'.join(map(str, rule))}]" if kind in ("enum", "int_enum") else ""
        group.add_argument(f"--{key}", dest=key, metavar="X", help=(label + extra).replace("%", "%%"))
    parser.add_argument("--settings", default=SETTINGS_FILE, help="settings file (default: settings.json)")


def resolve_settings(args):
    base = settings_mod.load(args.settings)
    overrides = {k: getattr(args, k) for k in settings_mod.SCHEMA if getattr(args, k, None) is not None}
    values = settings_mod.normalize(overrides, base)
    values, notes = esi.check_system(values)
    for note in notes:
        print(note, file=sys.stderr)
    return values


def progress_printer(total, enabled):
    state = {"n": 0}

    def tick(*_):
        state["n"] += 1
        if enabled:
            sys.stderr.write(f"\r  {state['n']}/{total} reactions ")
            sys.stderr.flush()
    return tick


SORT_KEYS = [f"{k}_{m}" for k in ("profit", "cost", "profitPercent", "profitPerHour") for m in MODES]


def print_table(rows, sort=None, limit=None):
    by_group = {}
    for row in rows:
        by_group.setdefault(row.group.key, []).append(row)
    sections = [("Top reactions", rows)] if sort else \
        [(GROUPS[k].title, v) for k, v in by_group.items()]
    data = {id(r): r.to_dict() for r in rows}
    for title, section in sections:
        if sort:
            section = sorted(section, key=lambda r: (r.ok, data[id(r)].get(sort) or 0), reverse=True)
        if limit:
            section = section[:limit]
        label = (lambda r: f"{r.name} [{r.group.key}]") if sort else (lambda r: r.name)
        width = max([len(label(r)) for r in section] + [8])
        print(f"\n{title}  (Jita 4-4 live; cost = materials + fees + job cost)")
        header = (f"{'Reaction':<{width}} " + "".join(f"{'Cost ' + m.capitalize():>16}" for m in MODES)
                  + "".join(f"{'Profit ' + m.capitalize():>16}" for m in MODES))
        print(header)
        print("-" * len(header))
        for r in section:
            d = data[id(r)]
            if not r.ok:
                print(f"{label(r):<{width}} ERROR: {r.error}")
                continue
            marks = d.get("notes", []) + [f"{k}: {v}" for k, v in (d.get("missingPrices") or {}).items()]
            flag = "  ! " + "; ".join(marks) if marks else ""
            print(f"{label(r):<{width}} " + "".join(f"{fmt_isk(d['cost_' + m]):>16}" for m in MODES)
                  + "".join(f"{fmt_isk(d['profit_' + m]):>16}" for m in MODES) + flag)


def cmd_calc(args):
    settings = resolve_settings(args)
    groups = groups_for(args.groups)
    total = sum(len(g.items) for g in groups)
    rows = calculate(settings, groups, source=args.source, client=Client(per_second=args.rate),
                     workers=args.workers, progress=progress_printer(total, sys.stderr.isatty()))
    if sys.stderr.isatty():
        sys.stderr.write("\r" + " " * 30 + "\r")
    for warning in warnings(settings, rows):
        print(f"Warning: {warning}", file=sys.stderr)
    if args.format == "json":
        json.dump({"settings": settings, "rows": [r.to_dict(args.full) for r in rows]},
                  sys.stdout, indent=2)
        print()
    elif args.format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(["Calculator", "Group", "Reaction", "Type ID", "Source"]
                        + [f"Cost {m}" for m in MODES] + [f"Profit {m}" for m in MODES]
                        + [f"% prof. {m}" for m in MODES] + ["Runs", "Notes", "Error"])
        for r in rows:
            d = r.to_dict()
            writer.writerow([CALCULATORS[r.group.calculator], r.group.title, r.name, r.item_id, r.source]
                            + [d.get(f"cost_{m}") for m in MODES] + [d.get(f"profit_{m}") for m in MODES]
                            + [d.get(f"profitPercent_{m}") for m in MODES]
                            + [r.runs, "; ".join(d.get("notes", [])), r.error])
    else:
        print_settings(settings)
        print_table(rows, sort=args.sort, limit=args.top)
    return 1 if any(not r.ok for r in rows) else 0


def print_settings(settings):
    s = settings
    print(f"Prices: Jita 4-4 live (ESI)  B: {s['brokers']:g} | S: {s['sales']:g}  Reactions {s['skill']}  "
          f"{s['facility']} refinery  rigs T{s['rigs']}  {s['space']}  {s['system']}  IndyTax {s['tax']:g}  "
          f"SCC {s['scc']:g}  {s['duration']} min  cycles {s['cycles']}  prismaticite {s['prismaticite']:g}"
          + (f"  cost index {s['costIndex']:g}" if s["space"] == "wormhole" else ""))


def cmd_show(args):
    settings = resolve_settings(args)
    hits = find_items(args.query)
    if args.group:
        hits = [h for h in hits if h[0].key == args.group.replace("-", "_")]
    if not hits:
        print(f"No reaction matches '{args.query}'", file=sys.stderr)
        return 1
    exact = [h for h in hits if h[2].lower() == args.query.lower() or str(h[1]) == args.query]
    hits = exact or hits
    names = sorted({h[2] for h in hits})
    if len(names) > 1:
        print("Ambiguous, matches:\n  " + "\n  ".join(names), file=sys.stderr)
        return 1
    client = Client()
    for group, item_id, name in hits:
        rows = calculate(settings, [group], source=args.source, client=client, workers=1)
        row = next(r for r in rows if r.item_id == item_id)
        print(f"\n== {name} ({group.title}, type {item_id}, source: {row.source})")
        if not row.ok:
            print(f"ERROR: {row.error}")
            continue
        res, prices = row.result, row.prices
        print(f"{'Item (price per unit, Jita 4-4)':<36} {'Quantity':>12} {'Buy':>12} {'Split':>12} {'Sell':>12}")
        for label, x in [("", x) for x in res.get("input", [])] + [("Output: ", o) for o in outputs(res)]:
            p = prices.get(x["name"]) or {}
            print(f"{label + x['name']:<36} {x['quantity']:>12,.0f} " +
                  " ".join(f"{fmt_unit(p.get(m)):>12}" for m in MODES))
        for x in res.get("remaining") or []:
            print(f"  left over: {x['name']} x{x['quantity']:,}")
        print(f"\n{'':<26}" + "".join(f"{m.capitalize():>18}" for m in MODES))
        views = {m: row.view(m) for m in MODES}
        for key, title in [("inputs", "Input materials"), ("inputFees", "Market fees inputs"),
                           ("install", "Job cost (system/fac./SCC)"), ("cost", "= Cost"),
                           ("output", "Output value"), ("outputFees", "Market fees output"),
                           ("profit", "= Profit"), ("profitPerHour", "Profit per hour")]:
            print(f"{title:<26}" + "".join(f"{fmt_isk(views[m][key]):>18}" for m in MODES))
        print(f"{'% profit':<26}" + "".join(f"{fmt_pct(views[m]['profitPercent']):>18}" for m in MODES))
        cyc = res.get("cycle_data", {})
        cycle = f"  cycle time {cyc['cycle_time']:,} s" if cyc.get("cycle_time") else ""
        print(f"\nRuns: {row.runs}{cycle}  window {cyc.get('total_time')} min")
        for note in row.to_dict().get("notes", []):
            print(f"Note: {note}")
        for item, note in row.missing_prices.items():
            print(f"Price note: {item}: {note}")
        if group.issue:
            print(f"Note: {group.issue}")
    return 0


def cmd_chain(args):
    from . import production, sde

    settings = resolve_settings(args)
    recipes = sde.production_recipes()
    chain = production.cost_chain(recipes, settings)
    print(f"Cost chain (like sheet 7): material cost per unit when you react everything yourself.\n"
          f"Prices Jita 4-4 live, reaction ME {chain['reactionMe'] * 100:.2f} %, "
          f"component ME {chain['componentMe'] * 100:.0f} %. No job cost or market fees.")
    for key, title in [("simple", "Simple Reactions"), ("complex", "Complex Reactions"),
                       ("hybrid", "Hybrid Reactions"), ("components", "T2 Components"),
                       ("capital", "Capital T2 Components")]:
        if args.only and key not in args.only:
            continue
        rows = chain[key]
        width = max(len(r["name"]) for r in rows)
        print(f"\n{title}")
        header = (f"{'Item':<{width}}" + "".join(f"{'Jita ' + m.capitalize():>13}" for m in MODES)
                  + "".join(f"{'Cost ' + m.capitalize():>13}" for m in MODES)
                  + "".join(f"{'Profit ' + m.capitalize():>13}" for m in MODES))
        print(header)
        print("-" * len(header))
        for r in rows:
            flag = "  ! " + "; ".join(f"{k}: {v}" for k, v in r["missingPrices"].items()) \
                if r["missingPrices"] else ""
            print(f"{r['name']:<{width}}" + "".join(f"{fmt_unit(r['price'][m]):>13}" for m in MODES)
                  + "".join(f"{fmt_unit(r['cost'][m]):>13}" for m in MODES)
                  + "".join(f"{fmt_unit(r['profit'][m]):>13}" for m in MODES) + flag)
    return 0


def cmd_plan(args):
    from . import production, sde

    settings = resolve_settings(args)
    state = json.loads(Path(args.plan).read_text("utf-8")) if Path(args.plan).exists() else {}
    if args.stock:
        state["stock"] = Path(args.stock).read_text("utf-8")
    for spec in args.job or []:
        name, _, n = spec.rpartition("=")
        state.setdefault("jobs", {})[name.strip()] = int(n)
    for spec in args.component or []:
        name, _, n = spec.rpartition("=")
        state.setdefault("components", {})[name.strip()] = int(n)
    if args.runs:
        state["runsPerJob"] = args.runs
    result = production.plan(sde.production_recipes(), settings, state)
    if args.save:
        Path(args.plan).write_text(json.dumps(state, indent=2), encoding="utf-8")
    for name in result["unknown"]:
        print(f"Warning: unknown item '{name}'", file=sys.stderr)
    print(f"Production plan ({result['runsPerJob']} runs per job, reaction ME "
          f"{result['reactionMe'] * 100:.2f} %, {result['stockItems']} stock items)")
    print(f"\n{'Complex / hybrid':<30} {'for comp.':>10} {'stock':>12} {'auto':>6} {'manual':>6} {'jobs':>6} "
          f"{'output':>12}" + "".join(f"{'Value ' + m.capitalize():>18}" for m in MODES))
    for t in result["top"]:
        print(f"{t['name']:<30} {t['componentNeed']:>10,} {t['stock']:>12,} {t['autoJobs']:>6} "
              f"{t['manualJobs']:>6} {t['jobs']:>6} {t['output']:>12,.0f}"
              + "".join(f"{fmt_isk(t['value'][m]):>18}" for m in MODES))
    print(f"\n{'Simple reaction':<30} {'need':>12} {'stock':>12} {'jobs':>6} {'output':>12} {'surplus':>10}")
    for x in result["simple"]:
        print(f"{x['name']:<30} {x['need']:>12,} {x['stock']:>12,} {x['jobs']:>6} {x['output']:>12,.0f} "
              f"{x['surplus']:>10,.0f}")
    print(f"\n{'Shopping list':<30} {'need':>12} {'stock':>12} {'to buy':>12}"
          + "".join(f"{'Cost ' + m.capitalize():>18}" for m in MODES))
    for x in result["shopping"]:
        print(f"{x['name']:<30} {x['need']:>12,} {x['stock']:>12,} {x['toBuy']:>12,}"
              + "".join(f"{fmt_isk(x['cost'][m]):>18}" for m in MODES))
    print(f"{'Total':<69}" + "".join(f"{fmt_isk(result['shoppingTotal'][m]):>18}" for m in MODES))
    for item, note in result["missingPrices"].items():
        print(f"Price note: {item}: {note}")
    return 0


def cmd_list(args):
    for group in groups_for(args.groups):
        print(f"\n{group.title}  [{group.key}, source: {group.source}]")
        if group.issue:
            print(f"  ! {group.issue}")
        for item_id, name in group.items:
            print(f"  {item_id:>6}  {name}")
    return 0


def cmd_settings(args):
    current = settings_mod.load(args.settings)
    if args.set:
        changes = {}
        for pair in args.set:
            if "=" not in pair:
                print(f"Use key=value, got '{pair}'", file=sys.stderr)
                return 2
            key, value = pair.split("=", 1)
            changes[key.strip()] = value.strip()
        current = settings_mod.normalize(changes, current)
        settings_mod.save(args.settings, current)
        print(f"Saved {args.settings}")
    if args.reset:
        current = settings_mod.normalize()
        settings_mod.save(args.settings, current)
        print(f"Reset {args.settings}")
    for key, (_, _, label) in settings_mod.SCHEMA.items():
        print(f"  {key:<13} {current[key]!s:<18} {label}")
    return 0


def cmd_verify(args):
    from .verify import run_all

    settings = resolve_settings(args)
    total = sum(len(g.items) for g in GROUPS.values())
    print(f"Checking {total} reactions in {len(GROUPS)} groups against API, calculator page"
          + ("" if args.skip_sde else " and EVE SDE") + " ...", file=sys.stderr)
    report = run_all(settings, client=Client(per_second=args.rate), workers=args.workers,
                     skip_sde=args.skip_sde, progress=progress_printer(total, sys.stderr.isatty()))
    if sys.stderr.isatty():
        sys.stderr.write("\r" + " " * 30 + "\r")
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
        return 1 if any(not i["known"] for i in report["issues"]) or report["errors"] else 0
    print(f"\n{'Group':<16} {'Reactions':>9} {'API ok':>7} {'= page':>7}  Program uses")
    for key, st in report["stats"].items():
        g = GROUPS[key]
        print(f"{key:<16} {st['total']:>9} {st['api_ok']:>7} {st['match']:>7}  "
              f"{'API' if g.source == 'api' else 'calculator page (fallback)'}")
    for err in report["errors"]:
        print(f"ERROR: {err}")
    known = [i for i in report["issues"] if i["known"]]
    new = [i for i in report["issues"] if not i["known"]]
    if known:
        print("\nKnown API problems (handled by the calculator page fallback):")
        for key in dict.fromkeys(i["group"] for i in known):
            count = sum(1 for i in known if i["group"] == key)
            print(f"  {key}: {count} reactions - {GROUPS[key].issue}")
    if new:
        print(f"\n{len(new)} findings:")
        for i in new:
            print(f"  [{i['check']}] {i['group']}: {i['name']}: {i['message']}")
    else:
        print("\nNo new findings.")
    return 1 if new or report["errors"] else 0


def cmd_check_sheet(args):
    try:
        from .sheetcheck import check_workbook
    except ImportError:
        print("check-sheet needs openpyxl: pip install openpyxl", file=sys.stderr)
        return 2
    print("Loading base recipes from the API and reading the workbook ...", file=sys.stderr)
    report = check_workbook(args.file, client=Client(per_second=args.rate))
    if args.json:
        json.dump({"errors": report["errors"],
                   "sheets": {k: [vars(f) for f in v] for k, v in report["sheets"].items()}},
                  sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        for err in report["errors"]:
            print(f"ERROR: {err}")
        for sheet, findings in report["sheets"].items():
            print(f"\n== {sheet}: " + (f"{len(findings)} findings" if findings else "OK"))
            for f in findings:
                print(f"  {f.cell:<14} {f.reaction}: {f.message}")
                if f.fix and args.fixes:
                    print(f"  {'':<14} suggested: {f.fix}")
    return 1 if report["errors"] or any(report["sheets"].values()) else 0


def cmd_serve(args):
    from .server import serve

    serve(args.host, args.port, args.settings, open_browser=args.open)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="reactionding",
                                description="EVE Online reactions profit calculator "
                                            "(data from reactions.coalition.space). "
                                            "Without a command the web interface opens.")
    sub = p.add_subparsers(dest="command", required=True)

    calc = sub.add_parser("calc", help="profit table for all (or selected) reactions")
    calc.add_argument("groups", nargs="*", help="group or calculator names (default: all)")
    calc.add_argument("--source", choices=("auto", "api", "web"), default="auto")
    calc.add_argument("--sort", choices=SORT_KEYS, metavar="KEY",
                      help="one ranked list, e.g. profit_split, profit_buy, cost_sell, profitPercent_split")
    calc.add_argument("--top", type=int, help="only show the best N rows")
    calc.add_argument("--format", choices=("table", "csv", "json"), default="table")
    calc.add_argument("--full", action="store_true", help="json: include full calculation detail")
    calc.add_argument("--workers", type=int, default=4)
    calc.add_argument("--rate", type=float, default=5.0, help="max API requests per second")
    add_settings_args(calc)
    calc.set_defaults(func=cmd_calc)

    show = sub.add_parser("show", help="detailed breakdown of one reaction")
    show.add_argument("query", help="reaction name (or part of it) or type id")
    show.add_argument("--group", help="limit to one group, e.g. strong_chain")
    show.add_argument("--source", choices=("auto", "api", "web"), default="auto")
    add_settings_args(show)
    show.set_defaults(func=cmd_show)

    lst = sub.add_parser("list", help="list all known reactions")
    lst.add_argument("groups", nargs="*")
    lst.set_defaults(func=cmd_list)

    st = sub.add_parser("settings", help="show or change saved settings")
    st.add_argument("--set", nargs="+", metavar="KEY=VALUE")
    st.add_argument("--reset", action="store_true")
    st.add_argument("--settings", default=SETTINGS_FILE)
    st.set_defaults(func=cmd_settings)

    ver = sub.add_parser("verify", help="check every reaction: API vs calculator page vs EVE SDE")
    ver.add_argument("--skip-sde", action="store_true")
    ver.add_argument("--json", action="store_true")
    ver.add_argument("--workers", type=int, default=4)
    ver.add_argument("--rate", type=float, default=5.0)
    add_settings_args(ver)
    ver.set_defaults(func=cmd_verify)

    chk = sub.add_parser("check-sheet",
                         help="check the reaction formulas of a spreadsheet (.xlsx) against the website")
    chk.add_argument("file")
    chk.add_argument("--fixes", action="store_true", help="print suggested corrected formulas")
    chk.add_argument("--json", action="store_true")
    chk.add_argument("--rate", type=float, default=5.0)
    chk.set_defaults(func=cmd_check_sheet)

    ch = sub.add_parser("chain", help="cost chain like sheet 7 (moon goo -> reactions -> T2 components)")
    ch.add_argument("only", nargs="*", help="simple, complex, hybrid, components, capital")
    add_settings_args(ch)
    ch.set_defaults(func=cmd_chain)

    pl = sub.add_parser("plan", help="production planner like sheet 8.1")
    pl.add_argument("--plan", default="planner.json", help="plan file (default: planner.json)")
    pl.add_argument("--job", action="append", metavar="REACTION=JOBS", help="e.g. 'Fullerides=2'")
    pl.add_argument("--component", action="append", metavar="COMPONENT=UNITS",
                    help="e.g. 'Antimatter Reactor Unit=1000'")
    pl.add_argument("--stock", metavar="FILE", help="text file with items copied from EVE")
    pl.add_argument("--runs", type=int, help="runs per reaction job (default 544)")
    pl.add_argument("--save", action="store_true", help="store the given jobs/stock in the plan file")
    add_settings_args(pl)
    pl.set_defaults(func=cmd_plan)

    srv = sub.add_parser("serve", help="start the web interface")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8765)
    srv.add_argument("--settings", default=SETTINGS_FILE)
    srv.add_argument("--open", action="store_true", help="open the interface in the web browser")
    srv.set_defaults(func=cmd_serve)
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        # started without arguments (e.g. double-clicked .exe): open the web interface
        argv = ["serve", "--open"]
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except settings_mod.SettingsError as exc:
        print(f"Invalid setting: {exc}", file=sys.stderr)
        return 2
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2
    except ApiError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1


def run():
    """Process entry point (python -m reactionding and the .exe)."""
    import os

    try:
        code = main()
        sys.stdout.flush()
    except BrokenPipeError:
        # Output was piped into a program that stopped reading (e.g. `| head`).
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 0
    sys.exit(code)
