"""Calculator settings: defaults, validation and (de)serialisation.

The keys and valid ranges mirror the API documentation of
https://reactions.coalition.space/api (all of them are required there).
"""

import json
from pathlib import Path

DEFAULTS = {
    "inMarket": "Jita",
    "outMarket": "Jita",
    "system": "Ignoitton",
    "input": "buy",
    "output": "sell",
    "brokers": 3.0,
    "sales": 3.6,
    "skill": 5,
    "facility": "large",
    "rigs": 2,
    "space": "nullsec",
    "tax": 1.0,
    "scc": 4.0,
    "duration": 10080,
    "cycles": 50,
    "costIndex": 0.0,
    "prismaticite": 50.0,
}

# Market hubs tracked by the calculator. Other names are not rejected by the API,
# it silently prices everything at 0 ISK - so they are validated here.
MARKETS = ("Jita", "Amarr", "Perimeter")

# key -> (kind, rule, label)
SCHEMA = {
    "inMarket": ("market", MARKETS, "Input market"),
    "outMarket": ("market", MARKETS, "Output market"),
    "system": ("str", None, "Reaction system (cost index lookup)"),
    "input": ("enum", ("buy", "sell"), "Input price method"),
    "output": ("enum", ("buy", "sell"), "Output price method"),
    "brokers": ("float", (0, 10), "Broker fee %"),
    "sales": ("float", (0, 8), "Sales tax %"),
    "skill": ("int_enum", (1, 2, 3, 4, 5), "Reactions skill level"),
    "facility": ("enum", ("medium", "large"), "Refinery size"),
    "rigs": ("int_enum", (0, 1, 2), "Rig tier (0 none, 1 T1, 2 T2)"),
    "space": ("enum", ("nullsec", "lowsec", "wormhole"), "Space"),
    "tax": ("float", (0, 100), "Industry tax %"),
    "scc": ("float", (0, 100), "SCC surcharge %"),
    "duration": ("int", (1, 43200), "Build time (minutes)"),
    "cycles": ("int", (1, 100000), "Cycles"),
    "costIndex": ("float", (0, 100), "Cost index % (wormhole only)"),
    "prismaticite": ("float", (0, 100), "Prismaticite luck %"),
}

ALIASES = {"indyTax": "tax", "sccTax": "scc"}


class SettingsError(ValueError):
    pass


def _coerce(key, value):
    kind, rule, _ = SCHEMA[key]
    if kind == "str":
        value = str(value).strip()
        if not value:
            raise SettingsError(f"{key} must not be empty")
        return value
    if kind == "market":
        canonical = {m.lower(): m for m in rule}.get(str(value).strip().lower())
        if canonical is None:
            raise SettingsError(f"{key} must be one of {', '.join(rule)} (got {value!r})")
        return canonical
    if kind == "enum":
        value = str(value).strip().lower()
        if value not in rule:
            raise SettingsError(f"{key} must be one of {', '.join(rule)} (got {value!r})")
        return value
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{key} must be a number (got {value!r})") from None
    if kind in ("int", "int_enum"):
        if num != int(num):
            raise SettingsError(f"{key} must be an integer (got {value!r})")
        num = int(num)
    if kind == "int_enum":
        if num not in rule:
            raise SettingsError(f"{key} must be one of {', '.join(map(str, rule))} (got {value!r})")
    else:
        lo, hi = rule
        if not lo <= num <= hi:
            raise SettingsError(f"{key} must be between {lo} and {hi} (got {value!r})")
    return num


def normalize(values=None, base=None):
    """Merge ``values`` over ``base`` (default DEFAULTS) and validate every key."""
    merged = dict(base or DEFAULTS)
    for key, value in (values or {}).items():
        key = ALIASES.get(key, key)
        if key not in SCHEMA:
            raise SettingsError(f"Unknown setting '{key}'")
        if value is None or value == "":
            continue
        merged[key] = value
    return {key: _coerce(key, merged[key]) for key in SCHEMA}


def _fmt(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def to_query(settings):
    """Parameters for the API (all keys are sent; costIndex is ignored outside wormholes)."""
    return {key: _fmt(value) for key, value in settings.items()}


def to_cookies(settings):
    """Cookies understood by the web calculator pages."""
    cookies = {"settingsMode": "single"}
    for key, value in settings.items():
        cookies[{"tax": "indyTax", "scc": "sccTax"}.get(key, key)] = _fmt(value)
    return cookies


def load(path):
    path = Path(path)
    if not path.exists():
        return normalize()
    return normalize(json.loads(path.read_text(encoding="utf-8")))


def save(path, settings):
    Path(path).write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
