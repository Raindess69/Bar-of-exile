"""Bar of Exile — passive skill tree v4: 1002 nodes loaded from data/passives_v2.json.

v2 data layout: no shared center node — each class owns a class_start node
(meta.class_start_nodes) that is conceptually pre-allocated and free. Stat keys
live in the shared v2 key space and map through game.statmap; keys without
engine support become inert raw StatMods (apply_mods skips them) and stay
visible in tooltips. Keystones carry an `effect` id + description: the effect
becomes a build flag op ({"op": "flag"}) consumed by Hero.recalc/combat.
"""
from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass, field

from game import statmap
from game.core import STAT_EN, Hero, Stats, StatMod

TREE_VERSION = 4
START_ID = None  # backward-compat: v2 has per-class starts, use start_id_for()

_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "passives_v2.json")
# S.4 rework: class ascendancy sub-trees merged additively on top of the baked
# passives_v2 graph (that file is NEVER regenerated — positions are baked).
_CK_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "data", "class_keystones.json")

# unconditional keystone "more"/"add" op stat -> Stats fields (others stay raw ops)
_OP_STAT_MAP: dict[str, list[str]] = {
    "global_damage": ["damage_min", "damage_max",
                      "added_fire", "added_cold", "added_lightning"],
}
_ENGINE_FIELDS = set(Stats.__dataclass_fields__)

# Stat-side keystone effects (V2 step 4): effect id -> StatMods emitted next to
# the flag op in _load(). Combat/skill/XP-side halves read hero.flags instead
# (game.combat: deadeye, berserker_oath; game.skills: vampiric_pact;
# game.progression: timeworn). Effects not listed here stay flag-only TODOs.
_KEYSTONE_MODS: dict[str, list[StatMod]] = {
    # "+60% increased Damage. -30% maximum Life."
    "glass_cannon": [StatMod(s, inc=60) for s in _OP_STAT_MAP["global_damage"]]
                    + [StatMod("life", more=-30)],
    # "Cannot be stunned. -10% Move Speed." — stun immunity: TODO (no stun system yet)
    "juggernaut": [StatMod("move_speed", more=-10)],
}


@dataclass
class NodeDef:
    id: str
    name: str
    description: str
    branch: str | None           # warrior|barbarian|archer|mage|cleric, None for shared
    kind: str                    # "class_start" | "small" | "notable" | "keystone" | "ck"
    pos: tuple[float, float]     # world coords, tree centered at (0, 0)
    stats: dict = field(default_factory=dict)      # raw json stats (full)
    mods: list[StatMod] = field(default_factory=list)  # incl. inert raw-key mods
    ops: list[dict] = field(default_factory=list)  # keystone flag/set/convert ops
    extra: dict = field(default_factory=dict)      # raw stats with no engine mapping
    # S.4 rework — class sub-tree ("ck") nodes only; None/0/"" on normal nodes:
    class_req: str | None = None       # class that may allocate this ck node
    level_req: int = 0                 # min hero level to allocate (0 = none)
    exclusive_group: str | None = None  # only one node per group may be allocated


NODES: dict[str, NodeDef] = {}
ADJ: dict[str, set[str]] = {}
EDGES: list[tuple[str, str]] = []
EDGE_ARCS: list[dict] = []  # {a,b,cx,cy,r} — render as circular arcs; graph edges too
META: dict = {}


def _map_stats(stats: dict) -> tuple[list[StatMod], dict]:
    """v2 stat keys -> StatMods via statmap; unmapped keys also land in extra
    for tooltip display (their inert mods are still in the list, like items)."""
    mods: list[StatMod] = []
    extra: dict = {}
    for key, val in stats.items():
        mods += statmap.mods_for(key, val)
        if not statmap.has_engine_support(key):
            extra[key] = val
    return mods, extra


def _translate_ops(modifiers: list[dict]) -> tuple[list[StatMod], list[dict]]:
    """Unconditional add/more on known stats -> StatMods; everything else stays raw."""
    mods: list[StatMod] = []
    ops: list[dict] = []
    for op in modifiers:
        kind, stat = op.get("op"), str(op.get("stat", ""))
        if "condition" not in op and kind in ("more", "add"):
            targets = _OP_STAT_MAP.get(stat) or ([stat] if stat in _ENGINE_FIELDS else None)
            if targets:
                if kind == "more":
                    mods += [StatMod(s, more=float(op.get("pct", 0))) for s in targets]
                else:
                    mods += [StatMod(s, flat=float(op.get("value", 0))) for s in targets]
                continue
        ops.append(op)
    return mods, ops


def _load() -> None:
    with open(_DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    META.update(data["meta"])
    start_class = {v: k for k, v in (META.get("class_start_nodes") or {}).items()}
    for n in data["nodes"]:
        stats = n.get("stats") or {}
        mods, extra = _map_stats(stats)
        m2, ops = _translate_ops(n.get("modifiers") or [])
        mods += m2
        if n["type"] == "keystone" and n.get("effect"):
            ops.append({"op": "flag", "stat": n["effect"]})
            mods += _KEYSTONE_MODS.get(n["effect"], [])
        cluster = n.get("cluster") or ""
        branch = (start_class.get(n["id"]) if n["type"] == "class_start"
                  else cluster[:-5] if cluster.endswith("_core") else None)
        name = n.get("name") or (_pretty_key(next(iter(stats))) if stats else "Passive")
        NODES[n["id"]] = NodeDef(
            id=n["id"], name=name, description=n.get("description") or "",
            branch=branch, kind=n["type"],
            pos=(float(n["x"]), float(n["y"])),
            stats=stats, mods=mods, ops=ops, extra=extra)
    for a, b in data["edges"]:
        EDGES.append((a, b))
        ADJ.setdefault(a, set()).add(b)
        ADJ.setdefault(b, set()).add(a)
    for arc in data.get("edge_arcs") or []:
        EDGE_ARCS.append(arc)
        a, b = arc["a"], arc["b"]
        ADJ.setdefault(a, set()).add(b)
        ADJ.setdefault(b, set()).add(a)
    for nid in NODES:
        ADJ.setdefault(nid, set())


# S.4 rework: class-point grant table (boss_id -> CP), filled by _load_class_keystones.
CLASS_POINT_SOURCES: dict[str, int] = {}


def _load_class_keystones() -> None:
    """Merge data/class_keystones.json additively: add ck-nodes + their edges on
    top of the baked passives_v2 graph. passives_v2.json is untouched. ck-nodes
    carry class_req/level_req/exclusive_group and emit their effects as StatMods +
    flag ops (flags land in hero.flags via recalc, consumed by combat)."""
    try:
        with open(_CK_DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return  # no sub-tree data yet — main tree still works
    CLASS_POINT_SOURCES.clear()
    CLASS_POINT_SOURCES.update(data.get("meta", {}).get("class_point_sources", {}))
    for n in data["nodes"]:
        nid = n["id"]
        mods: list[StatMod] = []
        for md in n.get("mods", []):
            mods.append(StatMod(md["stat"], flat=float(md.get("flat", 0.0)),
                                inc=float(md.get("inc", 0.0)),
                                more=float(md.get("more", 0.0))))
        ops = [{"op": "flag", "stat": fl} for fl in n.get("flags", [])]
        NODES[nid] = NodeDef(
            id=nid, name=n.get("name", nid), description=n.get("description", ""),
            branch=n.get("class_req"), kind="ck",
            pos=(float(n["x"]), float(n["y"])),
            stats={}, mods=mods, ops=ops, extra={},
            class_req=n.get("class_req"), level_req=int(n.get("level_req", 0)),
            exclusive_group=n.get("exclusive_group"))
    for a, b in data["edges"]:
        EDGES.append((a, b))
        ADJ.setdefault(a, set()).add(b)
        ADJ.setdefault(b, set()).add(a)
    for nid in NODES:
        ADJ.setdefault(nid, set())


def start_id_for(class_id: str) -> str:
    """Class start node id (conceptually pre-allocated, free, not in passives)."""
    sid = (META.get("class_start_nodes") or {}).get(class_id)
    if sid in NODES:
        return sid
    return next(nid for nid, n in NODES.items() if n.kind == "class_start")


# ------------------------------------------------------------------ API
def _normal_passives(hero: Hero) -> list[str]:
    """Allocated non-ck nodes — the ones that spend regular tree points. ck nodes
    live in hero.passives too but are paid for with Class Points (separate pool)."""
    return [nid for nid in hero.passives if not is_ck(nid)]


def points_spent(hero: Hero) -> int:
    return len(_normal_passives(hero))  # class start is free; ck nodes use CP


def points_available(hero: Hero) -> int:
    bonus = int(getattr(hero, "bonus_points", 0))
    return max(0, hero.level - 1 + bonus - len(_normal_passives(hero)))


def is_ck(node_id: str) -> bool:
    """True if node_id is a class sub-tree node (bought with Class Points)."""
    n = NODES.get(node_id)
    return n is not None and n.kind == "ck"


def class_points_total(hero: Hero) -> int:
    """Total Class Points ever granted to this hero (sum over recorded sources)."""
    return sum(CLASS_POINT_SOURCES.get(src, 0)
               for src in getattr(hero, "class_point_sources", []))


def ck_allocated(hero: Hero) -> list[str]:
    """Allocated class sub-tree node ids (subset of hero.passives)."""
    return [nid for nid in hero.passives if is_ck(nid)]


def class_points_available(hero: Hero) -> int:
    """Class Points left to spend = total granted − ck nodes already allocated."""
    return max(0, class_points_total(hero) - len(ck_allocated(hero)))


def grant_class_point(hero: Hero, boss_id: str) -> int:
    """Record a CP-granting act-boss kill on the hero (idempotent, deduped by
    boss id — CP is earned once per boss ever, not once per difficulty). Returns
    the CP gained (0 if the boss grants none or was already recorded)."""
    if boss_id not in CLASS_POINT_SOURCES:
        return 0
    srcs = getattr(hero, "class_point_sources", None)
    if srcs is None:
        srcs = []
        hero.class_point_sources = srcs
    if boss_id in srcs:
        return 0
    srcs.append(boss_id)
    return CLASS_POINT_SOURCES[boss_id]


def sync_class_points_from_kills(hero: Hero, boss_first_kills) -> int:
    """Retro-grant (§1.6): for each act boss already killed (any difficulty, per
    meta['boss_first_kills'] keys 'boss_id@difficulty'), ensure its CP is on the
    hero. Keeps old saves from losing progress. Returns total CP newly granted."""
    seen = {key.split("@", 1)[0] for key in (boss_first_kills or [])}
    return sum(grant_class_point(hero, bid) for bid in seen)


def is_allocated(hero: Hero, node_id: str) -> bool:
    return node_id in hero.passives


def _ck_gates_ok(hero: Hero, node: NodeDef) -> bool:
    """S.4 rework gates for a ck node: right class, level_req met, and no other
    node from its exclusive_group already allocated."""
    if node.class_req and node.class_req != hero.class_id:
        return False
    if node.level_req and hero.level < node.level_req:
        return False
    grp = node.exclusive_group
    if grp:
        for nid in hero.passives:
            other = NODES.get(nid)
            if other is not None and other is not node \
                    and other.exclusive_group == grp:
                return False
    return True


def is_available(hero: Hero, node_id: str) -> bool:
    """Adjacent to the allocated subgraph (own class start is pre-allocated).
    ck (class sub-tree) nodes additionally check class/level/exclusive gates."""
    node = NODES.get(node_id)
    if node is None or node.kind == "class_start" or node_id in hero.passives:
        return False
    if node.kind == "ck" and not _ck_gates_ok(hero, node):
        return False
    anchors = set(hero.passives) | {start_id_for(hero.class_id)}
    return bool(ADJ.get(node_id, set()) & anchors)


def allocate(hero: Hero, node_id: str) -> bool:
    if not is_available(hero, node_id):
        return False
    # ck (class sub-tree) nodes spend Class Points; normal nodes spend tree points.
    if is_ck(node_id):
        if class_points_available(hero) <= 0:
            return False
    elif points_available(hero) <= 0:
        return False
    hero.passives.append(node_id)
    _apply(hero)
    return True


def path_to(hero: Hero, node_id: str) -> list[str]:
    """Shortest unallocated path from the allocated subgraph to node_id (inclusive),
    PoE-style: hovering a far node shows the travel cost. [] if unreachable/taken.
    Class starts (own and foreign) are never part of a path; keystones need no
    special-casing — every v2 keystone has degree 1, a natural dead end."""
    node = NODES.get(node_id)
    if node is None or node.kind == "class_start" or node_id in hero.passives:
        return []
    # ck (class sub-tree) and normal nodes never mix in one path: a ck target is
    # reached only through ck nodes, a normal target only through normal nodes.
    # (ck nodes wire solely to their class_start + each other, so they can never
    # be transit to the main tree anyway; this keeps the travel cost honest.)
    target_is_ck = node.kind == "ck"
    anchors = set(hero.passives) | {start_id_for(hero.class_id)}
    prev: dict[str, str | None] = {a: None for a in anchors}
    q = deque(anchors)
    while q:
        cur = q.popleft()
        for nb in ADJ.get(cur, ()):
            if nb in prev or NODES[nb].kind == "class_start":
                continue
            if (NODES[nb].kind == "ck") != target_is_ck:
                continue
            prev[nb] = cur
            if nb == node_id:
                path: list[str] = []
                walk: str | None = nb
                while walk is not None and walk not in anchors:
                    path.append(walk)
                    walk = prev[walk]
                path.reverse()
                return path
            q.append(nb)
    return []


def allocate_path(hero: Hero, node_id: str) -> int:
    """Allocate the whole shortest path to node_id, as many nodes as points allow.
    Returns how many nodes were taken."""
    taken = 0
    for nid in path_to(hero, node_id):
        if not allocate(hero, nid):
            break
        taken += 1
    return taken


def deallocate(hero: Hero, node_id: str) -> bool:
    """Refund a node if the remaining allocated subgraph stays connected to the
    hero's class start."""
    if node_id not in hero.passives:
        return False
    remaining = set(hero.passives) - {node_id}
    if remaining and _reachable(remaining, start_id_for(hero.class_id)) != remaining:
        return False
    hero.passives.remove(node_id)
    _apply(hero)
    return True


def _reachable(allocated: set[str], start_id: str) -> set[str]:
    """Allocated nodes reachable from start_id walking only start+allocated."""
    seen: set[str] = set()
    stack = [start_id]
    visited = {start_id}
    while stack:
        for nb in ADJ.get(stack.pop(), ()):
            if nb in allocated and nb not in visited:
                visited.add(nb)
                seen.add(nb)
                stack.append(nb)
    return seen


def _dist_from_start(kept: set[str], start_id: str) -> dict[str, int]:
    """BFS hop-distance from start over the kept subgraph (start = 0). Nodes not
    reachable are absent from the dict — used to prefer dropping the deepest."""
    dist = {start_id: 0}
    q = deque([start_id])
    while q:
        cur = q.popleft()
        for nb in ADJ.get(cur, ()):
            if nb in kept and nb not in dist:
                dist[nb] = dist[cur] + 1
                q.append(nb)
    return dist


def _drop_over_budget(kept: set[str], start_id: str, pool: set[str],
                      over: int) -> set[str]:
    """Drop `over` nodes drawn from `pool` (a subset of `kept`), preferring
    frontier/leaves so the surviving allocation stays reachable from start_id
    (never strands nodes, never drops the start). Deterministic: at each step
    picks the droppable node deepest from start, ties broken by id. Mirrors the
    connectivity guard `deallocate` uses."""
    kept = set(kept)
    while over > 0:
        dist = _dist_from_start(kept, start_id)
        best: tuple[tuple[int, str], str] | None = None
        for nid in pool:
            if nid not in kept:
                continue
            rest = kept - {nid}
            # only drop if the rest stays fully reachable (no stranding)
            if rest and _reachable(rest, start_id) != rest:
                continue
            key = (dist.get(nid, -1), nid)
            if best is None or key > best[0]:
                best = (key, nid)
        if best is None:
            break  # nothing safely droppable (shouldn't happen for a leafy pool)
        kept.discard(best[1])
        over -= 1
    return kept


def rebuild(hero: Hero) -> None:
    """Rebuild mods/ops from hero.passives (after load). Drops unknown ids (= auto
    refund of pre-v4 trees, incl. the old "start"/1001-node ids), duplicates,
    class starts, and anything disconnected from the hero's class start (cross-save
    class weirdness can't strand points). Idempotent.

    Also re-validates ck (class sub-tree) nodes against the allocation gates that
    only the live `allocate` path enforces — regenerated data or a hand-edited save
    could otherwise strand a ck node whose level_req now exceeds the hero level, or
    two ck nodes from the same exclusive_group both allocated. Both are dropped here
    (Class Points auto-refund via class_points_available's recount), matching the
    foreign-class ck drop above.

    Finally re-checks the POINT BUDGET (M2): if a budget shrank below what is
    already spent — normal points (level regression / bonus loss) or Class Points
    (retuned class_point_sources) — the excess allocated nodes are actively DROPPED
    (deepest/frontier-first, connectivity to the class start preserved), not merely
    clamped to 0 in the display. Without this, over-budget nodes would keep their
    StatMods live = permanent free power invisible in the UI. Idempotent."""
    seen: set[str] = set()
    seen_groups: set[str] = set()
    valid: list[str] = []
    for nid in hero.passives:
        node = NODES.get(nid)
        if node is None or node.kind == "class_start" or nid in seen:
            continue
        if node.kind == "ck":
            # ck nodes of a foreign class can't be kept (cross-save class change):
            # drop them so their Class Points auto-refund.
            if node.class_req and node.class_req != hero.class_id:
                continue
            # level_req regressed below what the save recorded (data regen / edit):
            # drop so the node can't sit allocated above the hero's level.
            if node.level_req and hero.level < node.level_req:
                continue
            # exclusive_group: keep only the first allocated node per group,
            # drop the rest (deterministic by hero.passives order).
            grp = node.exclusive_group
            if grp:
                if grp in seen_groups:
                    continue
                seen_groups.add(grp)
        seen.add(nid)
        valid.append(nid)
    keep = _reachable(set(valid), start_id_for(hero.class_id))
    kept = {nid for nid in valid if nid in keep}

    # M2: enforce the SAME budgets the counters use. If spent > budget for either
    # pool, drop the excess (frontier/leaves first) instead of clamping display.
    start = start_id_for(hero.class_id)
    normal_kept = {nid for nid in kept if not is_ck(nid)}
    ck_kept = {nid for nid in kept if is_ck(nid)}
    normal_budget = max(0, hero.level - 1 + int(getattr(hero, "bonus_points", 0)))
    ck_budget = class_points_total(hero)
    if len(normal_kept) > normal_budget:
        kept = _drop_over_budget(kept, start, normal_kept,
                                 len(normal_kept) - normal_budget)
    if len(ck_kept) > ck_budget:
        kept = _drop_over_budget(kept, start, ck_kept, len(ck_kept) - ck_budget)

    hero.passives[:] = [nid for nid in valid if nid in kept]
    _apply(hero)


def _apply(hero: Hero) -> None:
    mods: list[StatMod] = []
    ops: list[dict] = []
    for nid in hero.passives:
        node = NODES[nid]
        mods += node.mods
        ops += node.ops
    hero.passive_mods = mods
    hero.passive_ops = ops
    hero.recalc()


# ------------------------------------------------------------------ display
def _pretty_key(key: str) -> str:
    for suf in ("_inc_pct", "_flat", "_pct"):
        if key.endswith(suf):
            key = key[: -len(suf)]
            break
    return key.replace("_", " ").title()


def _pretty_stat(key: str, val) -> str:
    if key.endswith("_inc_pct"):
        return f"{val}% increased {_pretty_key(key)}"
    if key.endswith("_pct"):
        return f"+{val}% {_pretty_key(key)}"
    return f"+{val} {_pretty_key(key)}"


def mod_lines(mods: list[StatMod]) -> list[str]:
    """Human-readable mod lines; merges damage min/max groups, handles 'reduced'.
    Inert raw-key mods (no engine field) are skipped — extra covers their display."""
    out: list[str] = []
    i = 0
    while i < len(mods):
        m = mods[i]
        if m.stat not in _ENGINE_FIELDS:
            i += 1
            continue
        if m.stat == "damage_min" and i + 1 < len(mods) and mods[i + 1].stat == "damage_max":
            nxt = mods[i + 1]
            if m.inc and nxt.inc == m.inc:
                word = "increased" if m.inc > 0 else "reduced"
                out.append(f"{int(abs(m.inc))}% {word} Damage")
                i += 2
                continue
            if m.more and nxt.more == m.more:
                n = 2
                while (i + n < len(mods) and mods[i + n].stat.startswith("added_")
                       and mods[i + n].more == m.more):
                    n += 1
                word = "more" if m.more > 0 else "less"
                out.append(f"{int(abs(m.more))}% {word} Damage")
                i += n
                continue
        if m.inc < 0:
            out.append(f"{int(abs(m.inc))}% reduced {STAT_EN.get(m.stat, m.stat)}")
        else:
            out.append(m.describe())
        i += 1
    return out


def node_lines(node: NodeDef) -> list[str]:
    """Tooltip stat lines: mapped mods + prettified unmapped raw stats.
    Keystones and class starts show their description. ck (class sub-tree) nodes
    show their mod lines, falling back to the description for flag-only nodes."""
    if node.kind in ("keystone", "class_start"):
        return [node.description] if node.description else []
    if node.kind == "ck":
        lines = mod_lines(node.mods)
        return lines if lines else ([node.description] if node.description else [])
    return mod_lines(node.mods) + [_pretty_stat(k, v) for k, v in node.extra.items()]


_load()
_load_class_keystones()


if __name__ == "__main__":
    counts: dict[str, int] = {}
    for n in NODES.values():
        counts[n.kind] = counts.get(n.kind, 0) + 1
    # baked passives_v2: 1002 nodes / 1376 edges. S.4 rework merges 37 ck nodes
    # + 49 ck edges on top (data/class_keystones.json).
    assert len(NODES) == 1002 + 37 and len(EDGES) == 1376 + 49, (len(NODES), len(EDGES))
    assert counts == {"class_start": 5, "small": 867,
                      "notable": 110, "keystone": 20, "ck": 37}, counts

    # edge_arcs: render-as-arc subset of edges[]; every pair is a graph edge
    assert len(EDGE_ARCS) == 768, len(EDGE_ARCS)
    edge_set = {frozenset(e) for e in EDGES}
    for arc in EDGE_ARCS:
        assert frozenset((arc["a"], arc["b"])) in edge_set, arc
        assert arc["b"] in ADJ[arc["a"]], arc
        assert all(k in arc for k in ("cx", "cy", "r")), arc

    # per-class connectivity: BFS with foreign class starts impassable
    class_ids = list(META["class_start_nodes"])
    assert len(class_ids) == 5
    starts = {start_id_for(c) for c in class_ids}
    for cid in class_ids:
        sid = start_id_for(cid)
        assert NODES[sid].kind == "class_start", (cid, sid)
        seen, stack = {sid}, [sid]
        while stack:
            for nb in ADJ[stack.pop()]:
                if nb not in seen and (nb not in starts or nb == sid):
                    seen.add(nb)
                    stack.append(nb)
        frac = len(seen) / len(NODES)
        print(f"{cid}: start {sid}, reaches {len(seen)}/{len(NODES)} ({frac:.1%})")
        assert frac > 0.9, (cid, frac)
    assert start_id_for("no_such_class") in starts, "fallback broken"

    # keystones: flag op from effect id, degree 1 (natural dead ends)
    for n in NODES.values():
        if n.kind == "keystone":
            assert len(ADJ[n.id]) == 1, f"{n.id} has {len(ADJ[n.id])} edges"
            assert any(op.get("op") == "flag" for op in n.ops), f"{n.id} has no flag op"
            assert node_lines(n), f"{n.id} tooltip empty"

    # v3 passive pool: every stat key must resolve through statmap (no inert
    # raw mods left over — extra stays empty for all nodes)
    unsupported = sorted({k for n in NODES.values() for k in n.stats
                          if not statmap.has_engine_support(k)})
    assert not unsupported, unsupported
    assert not any(n.extra for n in NODES.values()), "unexpected extra keys"

    hero = Hero(name="T", stats=Stats(), base_stats=Stats(), class_id="warrior")
    hero.init_hp()
    hero.recalc()
    hero.level = 10
    ws = start_id_for("warrior")
    assert points_available(hero) == 9
    assert not allocate(hero, ws), "own class start allocatable"
    assert not allocate(hero, start_id_for("mage")), "foreign class start allocatable"

    far = next(nid for nid in NODES
               if NODES[nid].kind == "small" and ws not in ADJ[nid]
               and not ADJ[nid] & starts and len(path_to(hero, nid)) >= 7)
    assert not allocate(hero, far), "connectivity skipped"

    # allocate chain from warrior start
    frontier = sorted(ADJ[ws])
    while len(hero.passives) < 6 and frontier:
        nid = frontier.pop(0)
        if allocate(hero, nid):
            frontier += sorted(ADJ[nid] - set(hero.passives))
    assert len(hero.passives) == 6 and points_available(hero) == 3
    assert points_spent(hero) == 6, "start counted as spent?"
    assert hero.passive_mods, "no mods after 6 allocations"
    assert not allocate(hero, hero.passives[0]), "double allocation"

    # engine-mapped stats actually move: path to a life node, life goes up
    hero.level = 60
    life0 = hero.stats.life
    life_node = min((nid for nid, n in NODES.items()
                     if "life_inc_pct" in n.stats and nid not in hero.passives
                     and path_to(hero, nid)),
                    key=lambda nid: len(path_to(hero, nid)))
    lp = allocate_path(hero, life_node)
    assert lp and is_allocated(hero, life_node), "life path failed"
    assert hero.stats.life > life0, "life mod inert"
    for nid in reversed(hero.passives[len(hero.passives) - lp:]):
        assert deallocate(hero, nid), nid
    hero.level = 10

    hero.bonus_points += 3
    assert points_available(hero) == 6, "bonus points ignored"
    hero.bonus_points -= 3

    # keystone gate REMOVED: allocatable at level 1, costs 1 point like any node
    ks = next(n for n in NODES.values() if n.kind == "keystone")
    gate = Hero(name="G", stats=Stats(), base_stats=Stats(), class_id="mage")
    gate.init_hp()
    gate.recalc()
    gate.level = 1
    gate.bonus_points = 1
    gate.passives.append(next(iter(ADJ[ks.id])))  # hacked adjacency, fine for the test
    _apply(gate)
    gate.bonus_points = 2
    assert is_available(gate, ks.id)
    assert allocate(gate, ks.id), "keystone refused at lvl 1 (gate not removed?)"
    assert points_available(gate) == 0
    effect = next(op["stat"] for op in ks.ops if op.get("op") == "flag")
    assert effect in gate.flags, f"keystone flag {effect} not applied"

    # deallocate: leaf ok, cut vertex refused
    leaf = hero.passives[-1]
    mid = hero.passives[0]
    rem = set(hero.passives) - {mid}
    if _reachable(rem, ws) != rem:
        assert not deallocate(hero, mid), "cut vertex deallocated"
    assert deallocate(hero, leaf) and leaf not in hero.passives
    assert points_available(hero) == 4

    # path_to / allocate_path: cross-cluster travel like PoE
    hero.level = 60
    p = path_to(hero, far)
    assert p and p[-1] == far and far not in hero.passives
    assert all(nid not in hero.passives for nid in p), "path revisits allocated"
    assert all(NODES[nid].kind != "class_start" for nid in p), "path uses class start"
    got = allocate_path(hero, far)
    assert got == len(p) and is_allocated(hero, far), (got, len(p))
    # keystone reachable by path; degree-1 means it can only be the final node
    ks2 = next(n for n in NODES.values() if n.kind == "keystone" and not is_allocated(hero, n.id))
    kp = path_to(hero, ks2.id)
    assert kp and kp[-1] == ks2.id
    assert all(NODES[nid].kind != "keystone" for nid in kp[:-1]), "keystone used as travel"
    for nid in reversed(list(hero.passives[len(hero.passives) - got:])):
        assert deallocate(hero, nid), nid
    hero.level = 10

    # rebuild = migration auto-refund: v1 ids ("start", "war_m1"...) and garbage dropped
    island = next(nid for nid in NODES if NODES[nid].kind == "small"
                  and not ADJ[nid] & (set(hero.passives) | {ws}))
    hero.passives += ["start", "war_m1", "ct_life", "ks_chaos_inoculation",
                      "bogus", ws, hero.passives[0], island]
    rebuild(hero)
    assert "start" not in hero.passives and "war_m1" not in hero.passives
    assert island not in hero.passives, "disconnected node kept"
    assert ws not in hero.passives and len(hero.passives) == 5
    assert points_available(hero) == 10 - 1 - 5, "refund math off"
    snap = (hero.stats.life, len(hero.passive_mods), len(hero.passive_ops))
    rebuild(hero)
    assert snap == (hero.stats.life, len(hero.passive_mods), len(hero.passive_ops))

    gc = next(n for n in NODES.values() if n.kind == "keystone" and "Glass" in n.name)
    assert node_lines(gc) == [gc.description], gc.id

    print("nodes:", len(NODES), counts, "| edges:", len(EDGES))
    print("hero:", points_spent(hero), "spent,", points_available(hero), "avail")
    for nid in hero.passives[:4]:
        print(" -", NODES[nid].name, "|", "; ".join(node_lines(NODES[nid])))
    print("keystone sample:", ks.name, "|", "; ".join(node_lines(ks)))
    print("tree OK")
