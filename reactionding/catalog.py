"""Catalog of every reaction known to reactions.coalition.space.

Each group corresponds to one table of the web calculator. ``source`` says
where the program gets the numbers from by default:

* ``api`` - the public API (https://reactions.coalition.space/api/v1)
* ``web`` - the calculator page data (same engine, settings sent as cookies)

``web`` is only used where a sweep over all reactions showed that the API
rejects or miscalculates the group (see ``issue``). Run
``python -m reactionding verify`` to re-check this against the live API.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Group:
    key: str
    calculator: str  # hybrid | composite | biochemical
    api_type: str  # path segment of the API endpoint
    web_key: str  # key in the calculator page data
    title: str
    source: str = "api"
    issue: str = ""
    items: tuple = field(default=(), compare=False)


ITEMS = {
    "hybrid": [
        (30306, "Methanofullerene"),
        (30303, "Fulleroferrocene"),
        (30304, "PPD Fullerene Fibers"),
        (30305, "Fullerene Intercalated Graphite"),
        (30307, "Lanthanum Metallofullerene"),
        (30308, "Scandium Metallofullerene"),
        (30309, "Graphene Nanoribbons"),
        (30310, "Carbon-86 Epoxy Resin"),
        (30311, "C3-FTM Acid"),
    ],
    "simple": [
        (16663, "Caesarium Cadmide"),
        (16659, "Carbon Polymers"),
        (16660, "Ceramic Powder"),
        (16655, "Crystallite Alloy"),
        (16668, "Dysporite"),
        (16656, "Fernite Alloy"),
        (16669, "Ferrofluid"),
        (17769, "Fluxed Condensates"),
        (16665, "Hexite"),
        (16666, "Hyperflurite"),
        (16667, "Neo Mercurite"),
        (16662, "Platinum Technite"),
        (16657, "Rolled Tungsten Alloy"),
        (16658, "Silicon Diborite"),
        (16664, "Solerium"),
        (16661, "Sulfuric Acid"),
        (16654, "Titanium Chromide"),
        (17959, "Vanadium Hafnite"),
        (17960, "Prometium"),
        (33336, "Thulium Hafnite"),
        (33337, "Promethium Mercurite"),
        (57453, "Carbon Fiber"),
        (57455, "Thermosetting Polymer"),
        (57454, "Oxy-Organic Solvents"),
    ],
    "complex": [
        (16671, "Titanium Carbide"),
        (16670, "Crystalline Carbonide"),
        (16673, "Fernite Carbide"),
        (16672, "Tungsten Carbide"),
        (16678, "Sylramic Fibers"),
        (16679, "Fullerides"),
        (16680, "Phenolic Composites"),
        (16681, "Nanotransistors"),
        (16682, "Hypersynaptic Fibers"),
        (16683, "Ferrogel"),
        (17317, "Fermionic Condensates"),
        (33361, "Plasmonic Metamaterials"),
        (33360, "Terahertz Metamaterials"),
        (33359, "Photonic Metamaterials"),
        (33362, "Nonlinear Metamaterials"),
        (57456, "Pressurized Oxidizers"),
        (57457, "Reinforced Carbon Fiber"),
    ],
    "chain": [
        (16671, "Titanium Carbide"),
        (16670, "Crystalline Carbonide"),
        (16673, "Fernite Carbide"),
        (16672, "Tungsten Carbide"),
        (16678, "Sylramic Fibers"),
        (16679, "Fullerides"),
        (16680, "Phenolic Composites"),
        (16681, "Nanotransistors"),
        (16682, "Hypersynaptic Fibers"),
        (16683, "Ferrogel"),
        (17317, "Fermionic Condensates"),
        (33361, "Plasmonic Metamaterials"),
        (33360, "Terahertz Metamaterials"),
        (33359, "Photonic Metamaterials"),
        (33362, "Nonlinear Metamaterials"),
        (57456, "Pressurized Oxidizers"),
        (57457, "Reinforced Carbon Fiber"),
    ],
    "unrefined": [
        (32821, "Unrefined Vanadium Hafnite"),
        (32822, "Unrefined Platinum Technite"),
        (32823, "Unrefined Solerium"),
        (32824, "Unrefined Caesarium Cadmide"),
        (32825, "Unrefined Hexite"),
        (32826, "Unrefined Rolled Tungsten Alloy"),
        (32827, "Unrefined Titanium Chromide"),
        (32828, "Unrefined Fernite Alloy"),
        (32829, "Unrefined Crystallite Alloy"),
        (29664, "Unrefined Hyperflurite"),
        (29663, "Unrefined Ferrofluid"),
        (29662, "Unrefined Prometium"),
        (29661, "Unrefined Neo Mercurite"),
        (29660, "Unrefined Dysporite"),
        (29659, "Unrefined Fluxed Condensates"),
        (33339, "Unrefined Thulium Hafnite"),
        (33338, "Unrefined Promethium Mercurite"),
    ],
    "refined": [
        (32821, "Unrefined Vanadium Hafnite"),
        (32822, "Unrefined Platinum Technite"),
        (32823, "Unrefined Solerium"),
        (32824, "Unrefined Caesarium Cadmide"),
        (32825, "Unrefined Hexite"),
        (32826, "Unrefined Rolled Tungsten Alloy"),
        (32827, "Unrefined Titanium Chromide"),
        (32828, "Unrefined Fernite Alloy"),
        (32829, "Unrefined Crystallite Alloy"),
        (29664, "Unrefined Hyperflurite"),
        (29663, "Unrefined Ferrofluid"),
        (29662, "Unrefined Prometium"),
        (29661, "Unrefined Neo Mercurite"),
        (29660, "Unrefined Dysporite"),
        (29659, "Unrefined Fluxed Condensates"),
        (33339, "Unrefined Thulium Hafnite"),
        (33338, "Unrefined Promethium Mercurite"),
    ],
    "eratic": [
        (90283, "Unrefined Tritanium"),
        (90284, "Unrefined Pyerite"),
        (90286, "Unrefined Mexallon"),
        (90289, "Unrefined Isogen"),
        (90292, "Unrefined Nocxium"),
        (90294, "Unrefined Zydrine"),
        (90296, "Unrefined Megacyte"),
        (90298, "Unrefined Morphite"),
    ],
    "eratic_repro": [
        (90283, "Unrefined Tritanium"),
        (90284, "Unrefined Pyerite"),
        (90286, "Unrefined Mexallon"),
        (90289, "Unrefined Isogen"),
        (90292, "Unrefined Nocxium"),
        (90294, "Unrefined Zydrine"),
        (90296, "Unrefined Megacyte"),
        (90298, "Unrefined Morphite"),
    ],
    "synth": [
        (28688, "Pure Synth Drop Booster"),
        (28689, "Pure Synth Exile Booster"),
        (28690, "Pure Synth Frentix Booster"),
        (28691, "Pure Synth Mindflood Booster"),
        (28692, "Pure Synth Sooth Sayer Booster"),
        (28693, "Pure Synth X-Instinct Booster"),
        (28686, "Pure Synth Blue Pill Booster"),
        (28687, "Pure Synth Crash Booster"),
    ],
    "standard": [
        (25252, "Pure Standard Frentix Booster"),
        (25330, "Pure Standard Drop Booster"),
        (25331, "Pure Standard Exile Booster"),
        (25332, "Pure Standard Mindflood Booster"),
        (25333, "Pure Standard X-Instinct Booster"),
        (25334, "Pure Standard Sooth Sayer Booster"),
        (25237, "Pure Standard Blue Pill Booster"),
        (25242, "Pure Standard Crash Booster"),
    ],
    "improved": [
        (25335, "Pure Improved Crash Booster"),
        (25336, "Pure Improved Drop Booster"),
        (25337, "Pure Improved Exile Booster"),
        (25338, "Pure Improved Mindflood Booster"),
        (25339, "Pure Improved Frentix Booster"),
        (25340, "Pure Improved X-Instinct Booster"),
        (25341, "Pure Improved Sooth Sayer Booster"),
        (25241, "Pure Improved Blue Pill Booster"),
    ],
    "improved_chain": [
        (25335, "Pure Improved Crash Booster"),
        (25336, "Pure Improved Drop Booster"),
        (25337, "Pure Improved Exile Booster"),
        (25338, "Pure Improved Mindflood Booster"),
        (25339, "Pure Improved Frentix Booster"),
        (25340, "Pure Improved X-Instinct Booster"),
        (25341, "Pure Improved Sooth Sayer Booster"),
        (25241, "Pure Improved Blue Pill Booster"),
    ],
    "strong": [
        (25283, "Pure Strong Blue Pill Booster"),
        (25342, "Pure Strong Crash Booster"),
        (25343, "Pure Strong Drop Booster"),
        (25344, "Pure Strong Exile Booster"),
        (25345, "Pure Strong Mindflood Booster"),
        (25346, "Pure Strong Frentix Booster"),
        (25347, "Pure Strong X-Instinct Booster"),
        (25348, "Pure Strong Sooth Sayer Booster"),
    ],
    "strong_chain": [
        (25283, "Pure Strong Blue Pill Booster"),
        (25342, "Pure Strong Crash Booster"),
        (25343, "Pure Strong Drop Booster"),
        (25344, "Pure Strong Exile Booster"),
        (25345, "Pure Strong Mindflood Booster"),
        (25346, "Pure Strong Frentix Booster"),
        (25347, "Pure Strong X-Instinct Booster"),
        (25348, "Pure Strong Sooth Sayer Booster"),
    ],
    "molecular": [
        (57460, "Axosomatic Neurolink Enhancer"),
        (57461, "Cogni-Emotive Neurolink Enhancer"),
        (57469, "Goal-Orienting Neurolink Stabilizer"),
        (57459, "Hypnagogic Neurolink Enhancer"),
        (57463, "Isotropic Neofullerene Alpha-3"),
        (57464, "Isotropic Neofullerene Beta-6"),
        (57465, "Isotropic Neofullerene Gamma-9"),
        (57458, "Meta-Operant Neurolink Enhancer"),
        (57467, "Reaction-Orienting Neurolink Stabilizer"),
        (57462, "Sense-Heuristic Neurolink Enhancer"),
        (57468, "Stress-Responding Neurolink Stabilizer"),
        (57466, "Ultradian-Cycling Neurolink Stabilizer"),
    ],
}

_GROUPS = [
    ("hybrid", "hybrid", "hybrid", "hybrid", "Hybrid Reactions", "api", ""),
    ("simple", "composite", "simple", "simple", "Simple Reactions", "api", ""),
    ("complex", "composite", "complex", "complex", "Complex Reactions", "api", ""),
    ("chain", "composite", "chain", "chain", "Complex Chain Reactions", "api", ""),
    ("unrefined", "composite", "unrefined", "unrefined",
     "Unrefined Reactions (not reprocessed)", "api", ""),
    ("refined", "composite", "refined", "refined",
     "Unrefined Reactions (55% Efficiency)", "api", ""),
    ("eratic", "composite", "eratic", "eratic",
     "Unrefined Mineral Reactions (no reprocessing)", "web",
     "API uses a 3600s reaction time instead of 360s (SDE), so runs are 10x too low"),
    ("eratic_repro", "composite", "eratic-repro", "eratic_repro",
     "Unrefined Mineral Reactions (MAX Refine 90.63%)", "web",
     "API rejects every id with TYPE_ID_MISMATCH"),
    ("synth", "biochemical", "synth", "synth", "Synth Booster Reactions", "api", ""),
    ("standard", "biochemical", "standard", "standard", "Standard Booster Reactions", "web",
     "API rejects every id with TYPE_ID_MISMATCH"),
    ("improved", "biochemical", "improved", "improved", "Improved Booster Reactions", "web",
     "API rejects every id with TYPE_ID_MISMATCH"),
    ("improved_chain", "biochemical", "improved_chain", "improved_chain",
     "Improved Booster Chain Reactions", "web",
     "API rejects every id with TYPE_ID_MISMATCH"),
    ("strong", "biochemical", "strong", "strong", "Strong Booster Reactions", "api", ""),
    ("strong_chain", "biochemical", "strong_chain", "strong_chain",
     "Strong Booster Chain Reactions", "web",
     "API does not resolve the chain (returns the plain Strong Booster inputs)"),
    ("molecular", "biochemical", "molecular", "molecular", "Molecular-Forging Reactions", "api", ""),
]

GROUPS = {
    key: Group(key, calc, api_type, web_key, title, source, issue, tuple(ITEMS[key]))
    for key, calc, api_type, web_key, title, source, issue in _GROUPS
}

CALCULATORS = {
    "hybrid": "Hybrid Reactions",
    "composite": "Composite Reactions",
    "biochemical": "Biochemical Reactions",
}


def groups_for(names=None):
    """Resolve group or calculator names (None = everything) to Group objects."""
    if not names:
        return list(GROUPS.values())
    out = []
    for name in names:
        name = name.strip().lower().replace("-", "_")
        if name in GROUPS:
            picked = [GROUPS[name]]
        elif name in CALCULATORS:
            picked = [g for g in GROUPS.values() if g.calculator == name]
        else:
            raise KeyError(
                f"Unknown group '{name}'. Valid: {', '.join(list(CALCULATORS) + list(GROUPS))}"
            )
        out.extend(g for g in picked if g not in out)
    return out


def find_items(query):
    """Find (group, id, name) entries by numeric id or case-insensitive name substring."""
    query = str(query).strip().lower()
    hits = []
    for g in GROUPS.values():
        for item_id, name in g.items:
            if query == str(item_id) or query in name.lower():
                hits.append((g, item_id, name))
    return hits
