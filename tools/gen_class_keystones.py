"""S.4 REWORK generator — class ascendancy sub-trees (CLASS_KEYSTONES_TREE_REWORK.md).

Deterministic (no RNG, no time). Emits `data/class_keystones.json`: 37 nodes
(4 classes x 7 + mage 9) that game.tree merges additively on top of the baked
passives_v2 graph. Each node is a class sub-tree passive bought with Class Points
(earned from act-boss first kills), gated by class_req and optional level_req.

Geometry (§1.3): each class sub-tree occupies a ±30° sector around ITS class
start's azimuth, growing inward toward the empty tree center. Layer radii:
entry 120, fork (A1/B1) 95, deep (A2/B2) 70, mechanic/capstone/lock 45.
The center is empty (baked nodes start at r=140), so nothing collides.

Run:  python tools/gen_class_keystones.py
Self-validates shape, ids, stats, flags, exclusivity, level gates, and that
every node has a graph path back to its class start.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# class start node ids in the baked passives_v2 graph (game.tree META), and each
# start's azimuth in degrees (measured from +x, screen y-down). Sub-trees fan
# inward from these anchors.
CLASS_START = {
    "warrior": "n0000",
    "barbarian": "n0004",
    "archer": "n0008",
    "mage": "n0012",
    "cleric": "n0016",
}
CLASS_AZIMUTH = {
    "warrior": -90.0,
    "barbarian": -18.0,
    "archer": 54.0,
    "mage": 126.0,
    "cleric": -162.0,
}

# layer radii (world units), inward from the class start ring (r=140)
R_ENTRY = 120.0
R_FORK = 95.0
R_DEEP = 70.0
R_INNER = 45.0     # mechanic / capstone / mage locks
SECTOR = 24.0      # ± angular spread inside the class sector (deg)

CP_SOURCES = {"goblin_king": 2, "lich_emperor": 2, "lord_of_ash": 2, "the_watcher": 1}

WHITELIST_FLAGS = {"ck_cull_10", "ck_overheal", "ck_fifth_shot", "ck_kill_heal"}

# Stats fields that are flat accumulators read by the engine as s.X/100 (combat/
# skills divide by 100). A "+X% increased" design value maps to a FLAT mod of X
# here — putting it in `inc` would be inert (base is 0, so 0*(1+X/100)=0).
FLAT_PCT_FIELDS = {
    "damage_inc", "aoe_damage_inc", "boss_damage_inc", "dot_damage_inc",
    "cast_speed_inc", "healing_inc", "life_leech",
}
# Real multiplicative-base Stats fields where "increased" uses the `inc` bucket.
INC_FIELDS = {"life", "armor", "evasion", "attack_speed", "move_speed",
              "crit_chance", "crit_multi"}


def m(stat: str, **kw) -> dict:
    """StatMod-shaped dict. Pass flat=/inc=/more= explicitly."""
    d = {"stat": stat}
    d.update(kw)
    return d


# "N% more Damage" is a true multiplicative bucket applied to every damage
# component — the same pattern game.tree uses for glass_cannon. Putting `more`
# on the `damage_inc` accumulator would scale the percentage itself, not the
# damage. tree.mod_lines regroups these back into one "N% more Damage" line.
_DAMAGE_COMPONENTS = ("damage_min", "damage_max", "added_fire", "added_cold", "added_lightning")


def more_damage(pct: float) -> list[dict]:
    return [m(s, more=pct) for s in _DAMAGE_COMPONENTS]


def pos(cls: str, r: float, off_deg: float) -> tuple[float, float]:
    """World coords at radius r, offset off_deg from the class azimuth."""
    az = math.radians(CLASS_AZIMUTH[cls] + off_deg)
    return (round(r * math.cos(az), 2), round(r * math.sin(az), 2))


# Per-class node designs (numbers verbatim from §3.1-§3.5). Each entry:
# (suffix, name, description, mods, flags, level_req, exclusive_group, slot)
# slot picks the (radius, angle-offset) so the layout is a readable fan.
# slot -> (r, off_deg): entry/A1/A2/B1/B2/mech/cap and mage locks 6a/6b/6c.
SLOT_POS = {
    "entry": (R_ENTRY, 0.0),
    "A1": (R_FORK, -SECTOR),
    "A2": (R_DEEP, -SECTOR),
    "B1": (R_FORK, SECTOR),
    "B2": (R_DEEP, SECTOR),
    "mech": (R_DEEP, 0.0),
    "cap": (R_INNER, 0.0),
    "6a": (R_DEEP, -SECTOR * 0.5),
    "6b": (R_DEEP, 0.0),
    "6c": (R_DEEP, SECTOR * 0.5),
}

# edges by slot (within a class); class_start->entry added in build()
SLOT_EDGES = [
    ("entry", "A1"), ("entry", "B1"),
    ("A1", "A2"), ("B1", "B2"),
    ("entry", "mech"), ("mech", "cap"),
    ("A2", "cap"), ("B2", "cap"),
]
# mage variant: no single mech; three locks between entry and cap
SLOT_EDGES_MAGE = [
    ("entry", "A1"), ("entry", "B1"),
    ("A1", "A2"), ("B1", "B2"),
    ("entry", "6a"), ("entry", "6b"), ("entry", "6c"),
    ("6a", "cap"), ("6b", "cap"), ("6c", "cap"),
    ("A2", "cap"), ("B2", "cap"),
]

DESIGNS: dict[str, list[tuple]] = {
    # 3.1 WARRIOR — Bastion (tank -> executioner)
    "warrior": [
        ("entry", "Warpath", "+6% increased Damage, +6% increased Armour",
         [m("damage_inc", flat=6), m("armor", inc=6)], [], 0, None),
        ("A1", "Bulwark", "+12% increased Armour, +5% increased Life",
         [m("armor", inc=12), m("life", inc=5)], [], 0, None),
        ("A2", "Unbreakable", "+20% increased Armour, +30 to Armour",
         [m("armor", inc=20), m("armor", flat=30)], [], 0, None),
        ("B1", "First Blood", "+10% increased Damage, +3% to Critical Strike Chance",
         [m("damage_inc", flat=10), m("crit_chance", flat=3)], [], 0, None),
        ("B2", "Skullcracker", "+20 to Critical Strike Multiplier",
         [m("crit_multi", flat=20)], [], 0, None),
        ("mech", "Executioner", "Enemies below 10% Life die instantly (bosses 5%)",
         [], ["ck_cull_10"], 30, None),
        ("cap", "Avatar of the Bastion",
         "+10% increased Life, +10% increased Damage, 5% more Damage",
         [m("life", inc=10), m("damage_inc", flat=10), *more_damage(5)], [], 50, None),
    ],
    # 3.2 BARBARIAN — Fury (tempo -> blood)
    "barbarian": [
        ("entry", "Bloodlust", "+8% increased Attack Speed, +4% increased Damage",
         [m("attack_speed", inc=8), m("damage_inc", flat=4)], [], 0, None),
        ("A1", "Thick Skin", "+10% increased Life",
         [m("life", inc=10)], [], 0, None),
        ("A2", "Carnage", "+2% Life Leech, +8% increased Damage",
         [m("life_leech", flat=2), m("damage_inc", flat=8)], [], 0, None),
        ("B1", "Raging Torrent", "+10% increased Attack Speed, +5% increased Movement Speed",
         [m("attack_speed", inc=10), m("move_speed", inc=5)], [], 0, None),
        ("B2", "Giant's Blows", "+25 to Critical Strike Multiplier",
         [m("crit_multi", flat=25)], [], 0, None),
        ("mech", "Blood Frenzy", "Life leech overhealing grants temporary Life",
         [], ["ck_overheal"], 30, None),
        ("cap", "Warlord",
         "+12% increased Damage, +8% increased Life, 5% more Damage",
         [m("damage_inc", flat=12), m("life", inc=8), *more_damage(5)], [], 50, None),
    ],
    # 3.3 ARCHER — Deadeye (crit -> rhythm)
    "archer": [
        ("entry", "Keen Eye", "+3% to Critical Strike Chance",
         [m("crit_chance", flat=3)], [], 0, None),
        ("A1", "Light Feet", "+10% increased Evasion, +5% increased Movement Speed",
         [m("evasion", inc=10), m("move_speed", inc=5)], [], 0, None),
        ("A2", "Wind Reader", "+10% increased Attack Speed",
         [m("attack_speed", inc=10)], [], 0, None),
        ("B1", "Deadly Precision", "+30 to Critical Strike Multiplier",
         [m("crit_multi", flat=30)], [], 0, None),
        ("B2", "Serrated Tips", "+12% increased Damage",
         [m("damage_inc", flat=12)], [], 0, None),
        ("mech", "Marked Rhythm", "Every 5th hit is a guaranteed Critical Strike",
         [], ["ck_fifth_shot"], 30, None),
        ("cap", "Windborne Executioner",
         "+10% increased Damage, +5% increased Attack Speed, 5% more Damage",
         [m("damage_inc", flat=10), m("attack_speed", inc=5), *more_damage(5)], [], 50, None),
    ],
    # 3.5 CLERIC — Radiant (sustain -> retribution)
    "cleric": [
        ("entry", "Devotion", "+6% increased Damage, +6% increased Life",
         [m("damage_inc", flat=6), m("life", inc=6)], [], 0, None),
        ("A1", "Sacred Bulwark", "+12% increased Armour",
         [m("armor", inc=12)], [], 0, None),
        ("A2", "Aegis", "+10% increased Armour, +5% increased Life",
         [m("armor", inc=10), m("life", inc=5)], [], 0, None),
        ("B1", "Zealotry", "+8% increased Cast Speed",
         [m("cast_speed_inc", flat=8)], [], 0, None),
        ("B2", "Righteous Might", "+12% increased Damage",
         [m("damage_inc", flat=12)], [], 0, None),
        ("mech", "Light's Harvest", "Killing an enemy restores 2% of maximum Life",
         [], ["ck_kill_heal"], 30, None),
        ("cap", "Ascendant",
         "+10% increased Life, +10% increased Damage, 5% more Damage",
         [m("life", inc=10), m("damage_inc", flat=10), *more_damage(5)], [], 50, None),
    ],
    # 3.4 MAGE — Attunement (glass stays glass: damage/cast, not tank). 9 nodes:
    # entry, A1, A2, B1, B2, three exclusive locks (6a/6b/6c), capstone.
    "mage": [
        ("entry", "Arcane Font", "+6% increased Damage, +5% increased Cast Speed",
         [m("damage_inc", flat=6), m("cast_speed_inc", flat=5)], [], 0, None),
        ("A1", "Deep Reserves", "+8% increased Damage, +4% increased Cast Speed",
         [m("damage_inc", flat=8), m("cast_speed_inc", flat=4)], [], 0, None),
        ("A2", "Quickening", "+10% increased Cast Speed",
         [m("cast_speed_inc", flat=10)], [], 0, None),
        ("B1", "Elemental Focus", "+12% increased Damage",
         [m("damage_inc", flat=12)], [], 0, None),
        ("B2", "Overcharged", "+25 to Critical Strike Multiplier",
         [m("crit_multi", flat=25)], [], 0, None),
        # locks: engine has no per-element outgoing multiplier, so per the rework's
        # honest fallback all three give +20% increased Damage — equal power, the
        # exclusive_group forces a single flavour pick.
        ("6a", "Lock: Flame", "+20% increased Damage (Flame attunement)",
         [m("damage_inc", flat=20)], [], 30, "mage_lock"),
        ("6b", "Lock: Frost", "+20% increased Damage (Frost attunement)",
         [m("damage_inc", flat=20)], [], 30, "mage_lock"),
        ("6c", "Lock: Storm", "+20% increased Damage (Storm attunement)",
         [m("damage_inc", flat=20)], [], 30, "mage_lock"),
        ("cap", "Archon",
         "+10% increased Cast Speed, +10% increased Damage, 5% more Damage",
         [m("cast_speed_inc", flat=10), m("damage_inc", flat=10), *more_damage(5)],
         [], 50, None),
    ],
}


def build() -> dict:
    nodes: list[dict] = []
    edges: list[list[str]] = []
    all_ids: set[str] = set()
    for cls, designs in DESIGNS.items():
        slot_to_id: dict[str, str] = {}
        for i, (slot, name, desc, mods, flags, lvl, excl) in enumerate(designs, start=1):
            nid = f"ck_{cls}_{i}"
            assert nid not in all_ids, f"dup id {nid}"
            all_ids.add(nid)
            slot_to_id[slot] = nid
            r, off = SLOT_POS[slot]
            x, y = pos(cls, r, off)
            node = {
                "id": nid, "class_req": cls, "name": name, "description": desc,
                "x": x, "y": y, "level_req": lvl,
            }
            if excl:
                node["exclusive_group"] = excl
            if mods:
                node["mods"] = mods
            if flags:
                node["flags"] = flags
            nodes.append(node)
        # edges: class_start -> entry, then the class topology
        edges.append([CLASS_START[cls], slot_to_id["entry"]])
        topo = SLOT_EDGES_MAGE if cls == "mage" else SLOT_EDGES
        for a, b in topo:
            edges.append([slot_to_id[a], slot_to_id[b]])
    return {
        "meta": {
            "kind": "class_keystones",
            "game": "Bar of Exile",
            "version": 1,
            "design_ref": "CLASS_KEYSTONES_TREE_REWORK.md §3",
            "point_currency": "class_points",
            "class_point_sources": CP_SOURCES,
            "note": "Class ascendancy sub-trees merged onto passives_v2 by game.tree. "
                    "Bought with Class Points (act-boss first kills). Positions fan "
                    "inward from each class start; center of the main tree is empty.",
        },
        "nodes": nodes,
        "edges": edges,
    }


def _validate(data: dict) -> None:
    nodes = {n["id"]: n for n in data["nodes"]}
    assert len(nodes) == 37, len(nodes)
    # per-class counts
    counts: dict[str, int] = {}
    for n in nodes.values():
        counts[n["class_req"]] = counts.get(n["class_req"], 0) + 1
    assert counts == {"warrior": 7, "barbarian": 7, "archer": 7, "cleric": 7, "mage": 9}, counts
    # ids, class_req, effects, flags, level gates, exclusivity
    excl_count = 0
    for nid, n in nodes.items():
        assert nid.startswith("ck_"), nid
        assert n["class_req"] in CLASS_START, n
        assert n.get("mods") or n.get("flags"), f"{nid} empty effect"
        for fl in n.get("flags", []):
            assert fl in WHITELIST_FLAGS, f"{nid} bad flag {fl}"
        assert n["level_req"] in (0, 30, 50), (nid, n["level_req"])
        if "exclusive_group" in n:
            assert n["exclusive_group"] == "mage_lock" and n["class_req"] == "mage"
            excl_count += 1
    assert excl_count == 3, excl_count
    # edges reference real ck-ids (class starts n00xx are external anchors)
    adj: dict[str, set[str]] = {}
    for a, b in data["edges"]:
        for x in (a, b):
            if x.startswith("ck_"):
                assert x in nodes, f"edge to unknown {x}"
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    # every ck-node reachable from its class start via BFS
    for cls, start in CLASS_START.items():
        seen = {start}
        stack = [start]
        while stack:
            for nb in adj.get(stack.pop(), ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        for nid, n in nodes.items():
            if n["class_req"] == cls:
                assert nid in seen, f"{nid} unreachable from {start}"
    # no two nodes share a position (readability)
    seen_pos: dict[tuple, str] = {}
    for nid, n in nodes.items():
        key = (n["x"], n["y"])
        assert key not in seen_pos, f"{nid} overlaps {seen_pos[key]} at {key}"
        seen_pos[key] = nid


def main() -> None:
    data = build()
    _validate(data)
    out = DATA_DIR / "class_keystones.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    n_flags = sum(1 for n in data["nodes"] if n.get("flags"))
    print(f"wrote {out} — {len(data['nodes'])} nodes, {len(data['edges'])} edges, "
          f"{n_flags} flag nodes, CP sources {data['meta']['class_point_sources']}")


if __name__ == "__main__":
    main()
