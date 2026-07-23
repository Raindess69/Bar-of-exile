#!/usr/bin/env python3
"""Plain-assert tests for game/atlas.py + integrity of data/atlas_tree.json.
Ported from opus_pack. Run: python tests/test_atlas.py"""
import os
import sys
from collections import deque

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from game.atlas import AtlasState, AtlasTree, get_tree


def synthetic_tree():
    nodes = [
        {"id": "start", "type": "start", "name": "The Anvil", "stats": {}},
        {"id": "s1", "type": "small", "name": "S1", "stats": {"gold_find_inc_pct": 3}},
        {"id": "s2", "type": "small", "name": "S2", "stats": {"gold_find_inc_pct": 2}},
        {"id": "n1", "type": "notable", "name": "N1", "stats": {"xp_gain_inc_pct": 6}},
        {"id": "k1", "type": "keystone", "name": "K1", "stats": {}, "modifiers": [{"op": "flag", "stat": "f1", "value": True}]},
        {"id": "k2", "type": "keystone", "name": "K2", "stats": {}, "modifiers": []},
        {"id": "k3", "type": "keystone", "name": "K3", "stats": {}, "modifiers": []},
        {"id": "k4", "type": "keystone", "name": "K4", "stats": {}, "modifiers": []},
    ]
    edges = [["start", "s1"], ["s1", "s2"], ["s2", "n1"], ["n1", "k1"], ["n1", "k2"], ["n1", "k3"], ["n1", "k4"]]
    return AtlasTree({"meta": {"rules": {"max_keystones": 3}}, "nodes": nodes, "edges": edges})


def test_allocation_rules():
    st = AtlasState(synthetic_tree(), points=10)
    assert st.can_allocate("n1") == (False, "not_adjacent")
    assert st.allocate("s1") == (True, "ok")
    assert st.allocate("s1") == (False, "already_allocated")
    assert st.allocate("missing") == (False, "unknown_node")
    assert st.allocate("s2") == (True, "ok")
    assert st.allocate("n1") == (True, "ok")
    assert st.points == 7


def test_no_points():
    st = AtlasState(synthetic_tree(), points=0)
    assert st.can_allocate("s1") == (False, "no_points")


def test_keystone_limit():
    st = AtlasState(synthetic_tree(), points=10)
    for nid in ("s1", "s2", "n1", "k1", "k2", "k3"):
        assert st.allocate(nid)[0], nid
    assert st.can_allocate("k4") == (False, "keystone_limit")
    assert st.keystone_count() == 3
    assert st.allocated_keystones() == ["k1", "k2", "k3"]
    assert {"op": "flag", "stat": "f1", "value": True} in st.modifiers()


def test_deallocation_connectivity():
    st = AtlasState(synthetic_tree(), points=10)
    for nid in ("s1", "s2", "n1"):
        st.allocate(nid)
    assert st.can_deallocate("start") == (False, "cannot_remove_start")
    assert st.can_deallocate("k1") == (False, "not_allocated")
    assert st.can_deallocate("s1") == (False, "would_disconnect")
    assert st.deallocate("n1") == (True, "ok")
    assert st.points == 8


def test_stats_and_serialization():
    st = AtlasState(synthetic_tree(), points=10)
    st.allocate("s1")
    st.allocate("s2")
    assert st.stats() == {"gold_find_inc_pct": 5}
    d = st.to_dict()
    st2 = AtlasState.from_dict(synthetic_tree(), d)
    assert st2.points == st.points and st2.allocated == st.allocated


def test_from_dict_drops_unknown_ids():
    tree = synthetic_tree()
    st = AtlasState.from_dict(tree, {"points": 4, "allocated": ["s1", "ghost_node"]})
    assert st.allocated == {"start", "s1"}
    assert st.points == 4


def test_real_atlas_file():
    path = os.path.join(ROOT, "data", "atlas_tree.json")
    tree = AtlasTree.load(path)
    counts = {}
    for n in tree.nodes.values():
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    assert counts == {"start": 1, "small": 850, "notable": 130, "keystone": 20}, counts
    # full connectivity
    seen, q = {tree.start_id}, deque([tree.start_id])
    while q:
        for nb in tree.adj[q.popleft()]:
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    assert len(seen) == len(tree.nodes)
    # keystones gated behind exactly one notable
    for nid, n in tree.nodes.items():
        if n["type"] == "keystone":
            assert len(tree.adj[nid]) == 1
            assert tree.nodes[next(iter(tree.adj[nid]))]["type"] == "notable"
    assert tree.max_keystones == 3


def test_get_tree_cached_default_path():
    t1 = get_tree()
    t2 = get_tree()
    assert t1 is t2
    assert len(t1.nodes) == 1001
    assert t1.nodes[t1.start_id]["name"] == "The Anvil"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("ALL ATLAS TESTS PASSED")
