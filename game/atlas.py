"""
game/atlas.py - Atlas endgame meta tree (ported from opus_pack, step 2b.6 prep).
Loads data/atlas_tree.json (1001 nodes: start "The Anvil" + 850 small +
130 notable + 20 keystone, 12 meta clusters), manages point allocation,
aggregates meta stats. Pure logic, no UI, deterministic.

HARD CONSTRAINT (master brief): atlas stats/modifiers affect WORLD, LOOT and
ECONOMY only - never hero combat stats. stats() and modifiers() must be
consumed by game.world / loot / economy systems, NOT by Hero.recalc or
game.core.apply_ops (keystone stat names like "rift_timer", "ash_zone_loot"
live in a separate world-level namespace).

Point sources (meta.rules.point_sources): rift tier first clear (+1),
act boss first kill per difficulty (+1), nightmare Lord of Ash first kill (+3).

Serialize AtlasState via to_dict()/from_dict() into save v3
(fields: atlas_points, atlas_allocated).
"""
from __future__ import annotations

import json
import os
from collections import deque

MAX_KEYSTONES = 3

_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "atlas_tree.json")

_TREE: AtlasTree | None = None  # lazy singleton for the real data file


class AtlasTree:
    def __init__(self, data):
        self.meta = data.get("meta", {})
        self.nodes = {n["id"]: n for n in data["nodes"]}
        self.adj = {nid: set() for nid in self.nodes}
        for a, b in data["edges"]:
            self.adj[a].add(b)
            self.adj[b].add(a)
        self.start_id = next(nid for nid, n in self.nodes.items() if n["type"] == "start")
        self.max_keystones = self.meta.get("rules", {}).get("max_keystones", MAX_KEYSTONES)

    @classmethod
    def load(cls, path=None):
        with open(path or _DATA_PATH, "r", encoding="utf-8") as f:
            return cls(json.load(f))


def get_tree() -> AtlasTree:
    """Cached AtlasTree from data/atlas_tree.json (the tree is immutable;
    all mutable state lives in AtlasState)."""
    global _TREE
    if _TREE is None:
        _TREE = AtlasTree.load()
    return _TREE


class AtlasState:
    def __init__(self, tree, points=0):
        self.tree = tree
        self.points = points
        self.allocated = {tree.start_id}

    # ---- queries ----
    def keystone_count(self):
        return sum(1 for nid in self.allocated if self.tree.nodes[nid]["type"] == "keystone")

    def allocated_keystones(self):
        return sorted(nid for nid in self.allocated if self.tree.nodes[nid]["type"] == "keystone")

    def stats(self):
        """Aggregated numeric meta stats from all allocated nodes.
        World/loot/economy scope only - never feed into Hero stats."""
        agg = {}
        for nid in self.allocated:
            for stat, val in self.tree.nodes[nid].get("stats", {}).items():
                agg[stat] = agg.get(stat, 0) + val
        return agg

    def modifiers(self):
        """All keystone modifier ops from allocated keystones. Consumed by the
        world/loot/economy layer (NOT by game.core.apply_ops / Hero.recalc -
        atlas ops use world-level stat names)."""
        mods = []
        for nid in self.allocated_keystones():
            mods.extend(self.tree.nodes[nid].get("modifiers", []))
        return mods

    # ---- allocation ----
    def can_allocate(self, nid):
        if nid not in self.tree.nodes:
            return False, "unknown_node"
        if nid in self.allocated:
            return False, "already_allocated"
        if self.points < 1:
            return False, "no_points"
        if not (self.tree.adj[nid] & self.allocated):
            return False, "not_adjacent"
        node = self.tree.nodes[nid]
        if node["type"] == "keystone" and self.keystone_count() >= self.tree.max_keystones:
            return False, "keystone_limit"
        return True, "ok"

    def allocate(self, nid):
        ok, why = self.can_allocate(nid)
        if ok:
            self.allocated.add(nid)
            self.points -= 1
        return ok, why

    def can_deallocate(self, nid):
        if nid == self.tree.start_id:
            return False, "cannot_remove_start"
        if nid not in self.allocated:
            return False, "not_allocated"
        remaining = self.allocated - {nid}
        seen = {self.tree.start_id}
        q = deque([self.tree.start_id])
        while q:
            for nb in self.tree.adj[q.popleft()]:
                if nb in remaining and nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        if seen != remaining:
            return False, "would_disconnect"
        return True, "ok"

    def deallocate(self, nid):
        ok, why = self.can_deallocate(nid)
        if ok:
            self.allocated.discard(nid)
            self.points += 1
        return ok, why

    # ---- persistence ----
    def to_dict(self):
        return {"points": self.points, "allocated": sorted(self.allocated)}

    @classmethod
    def from_dict(cls, tree, d):
        st = cls(tree, d.get("points", 0))
        # drop unknown node ids defensively (tree regen safety)
        st.allocated = {nid for nid in d.get("allocated", []) if nid in tree.nodes}
        st.allocated.add(tree.start_id)
        return st


if __name__ == "__main__":
    # smoke: real data file loads, allocation walks from The Anvil, roundtrip
    tree = get_tree()
    counts = {}
    for n in tree.nodes.values():
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    assert counts == {"start": 1, "small": 850, "notable": 130, "keystone": 20}, counts
    assert tree.max_keystones == 3

    st = AtlasState(tree, points=5)
    assert st.allocated == {tree.start_id}
    frontier = sorted(tree.adj[tree.start_id])
    assert st.allocate(frontier[0]) == (True, "ok")
    far = next(nid for nid in tree.nodes
               if nid not in st.allocated and not (tree.adj[nid] & st.allocated))
    assert st.can_allocate(far) == (False, "not_adjacent")
    assert st.deallocate(frontier[0]) == (True, "ok")
    assert st.points == 5

    st.allocate(frontier[0])
    st2 = AtlasState.from_dict(tree, st.to_dict())
    assert st2.points == st.points and st2.allocated == st.allocated
    print(f"atlas OK: {len(tree.nodes)} nodes, {sum(len(v) for v in tree.adj.values()) // 2} edges, "
          f"start '{tree.nodes[tree.start_id]['name']}', clusters {len(tree.meta.get('clusters', []))}")
