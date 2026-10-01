"""Minimal decoder for SvelteKit's ``devalue`` format used by ``__data.json``."""

_SPECIAL = {
    -1: None,  # undefined
    -2: None,  # null
    -3: float("nan"),
    -4: float("inf"),
    -5: float("-inf"),
    -6: -0.0,
}


def unflatten(values):
    if isinstance(values, int):
        return _SPECIAL[values]
    cache = {}

    def hydrate(index):
        if index in _SPECIAL:
            return _SPECIAL[index]
        if index in cache:
            return cache[index]
        value = values[index]
        if isinstance(value, list):
            if value and isinstance(value[0], str):
                tag = value[0]
                if tag in ("Set",):
                    result = [hydrate(i) for i in value[1:]]
                elif tag in ("Map",):
                    result = {hydrate(k): hydrate(v) for k, v in zip(value[1::2], value[2::2])}
                elif tag in ("Date", "BigInt", "RegExp"):
                    result = value[1]
                else:
                    raise ValueError(f"Unsupported devalue tag {tag!r}")
                cache[index] = result
                return result
            result = []
            cache[index] = result
            result.extend(hydrate(i) for i in value)
            return result
        if isinstance(value, dict):
            result = {}
            cache[index] = result
            for key, i in value.items():
                result[key] = hydrate(i)
            return result
        cache[index] = value
        return value

    return hydrate(0)


def decode_page(payload):
    """Return the decoded data of every node of a ``__data.json`` payload."""
    if payload.get("type") != "data":
        raise ValueError(f"Unexpected page payload type {payload.get('type')!r}")
    nodes = []
    for node in payload.get("nodes", []):
        if node and node.get("type") == "data":
            nodes.append(unflatten(node["data"]))
        else:
            nodes.append(None)
    return nodes
