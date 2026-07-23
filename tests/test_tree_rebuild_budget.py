#!/usr/bin/env python3
"""AUDIT_20 M2 — rebuild() must DROP over-budget nodes, not just clamp the display.

When a point budget shrinks below what is already spent (level regression, or a
retuned class_point_sources / hand-edited save), the excess allocated nodes used
to stay live — permanent free power invisible in the UI. rebuild() now actively
drops the excess (frontier/leaves first, connectivity to the class start kept).

Run: python tests/test_tree_rebuild_budget.py
 or: python -m pytest tests/test_tree_rebuild_budget.py -q
(NOT `python -m tests.x` — the environment has a conflicting site-packages `tests`.)
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from game import tree
from game.core import Hero, Stats


def _hero(class_id="warrior", level=60):
    h = Hero(name="T", stats=Stats(), base_stats=Stats(), class_id=class_id, level=level)
    h.init_hp()
    h.recalc()
    return h


def _ck(cls, n):
    return f"ck_{cls}_{n}"


def _alloc_normal_chain(hero, want):
    """Allocate `want` normal nodes by frontier-walking from the class start."""
    ws = tree.start_id_for(hero.class_id)
    frontier = sorted(tree.ADJ[ws])
    while len([n for n in hero.passives if not tree.is_ck(n)]) < want and frontier:
        nid = frontier.pop(0)
        if tree.NODES[nid].kind == "class_start" or tree.is_ck(nid):
            continue
        if tree.allocate(hero, nid):
            frontier += sorted(tree.ADJ[nid] - set(hero.passives))


def _all_reachable(hero):
    """Every allocated node reachable from the class start over the allocated set."""
    start = tree.start_id_for(hero.class_id)
    alloc = set(hero.passives)
    return tree._reachable(alloc, start) == alloc


# --- 1. Normal-point over-allocation: level regression drops the excess ------ #
def test_normal_over_budget_dropped():
    h = _hero("warrior", level=60)
    _alloc_normal_chain(h, 10)
    spent = tree.points_spent(h)
    assert spent == 10, spent
    assert tree.points_available(h) == 60 - 1 - 10
    mods_full = len(h.passive_mods)

    # regress the level so the budget (level-1) is far below what's spent.
    h.level = 3  # budget = 2 normal points, 10 allocated
    tree.rebuild(h)

    budget = h.level - 1
    spent_after = tree.points_spent(h)
    assert spent_after <= budget, (spent_after, budget)
    assert spent_after == budget, "should keep the full affordable budget"
    assert tree.points_available(h) >= 0
    assert _all_reachable(h), "surviving normal nodes stranded from class start"
    # passive_mods reflect ONLY the kept nodes (the free power is gone).
    assert len(h.passive_mods) < mods_full
    expect = sum(len(tree.NODES[n].mods) for n in h.passives)
    assert len(h.passive_mods) == expect, (len(h.passive_mods), expect)


# --- 2. Class-point over-allocation: shrunk CP budget drops excess ck -------- #
def test_ck_over_budget_dropped():
    # allocate 4 ck nodes legally on a 4-CP budget (trigger (a): later retune).
    h = _hero("warrior", level=60)
    h.class_point_sources = ["goblin_king", "lich_emperor"]  # 2 + 2 = 4 CP
    for n in (1, 2, 3, 4):
        assert tree.allocate(h, _ck("warrior", n)), n
    assert len(tree.ck_allocated(h)) == 4
    assert tree.class_points_available(h) == 0

    # trigger (a): the CP source table shrinks (retune / fewer sources on save).
    h.class_point_sources = ["the_watcher"]  # 1 CP now
    tree.rebuild(h)

    ck_budget = tree.class_points_total(h)
    assert ck_budget == 1
    assert len(tree.ck_allocated(h)) <= ck_budget, tree.ck_allocated(h)
    assert tree.class_points_available(h) >= 0
    # the surviving ck must be the entry (only it anchors to the class start).
    assert tree.ck_allocated(h) == [_ck("warrior", 1)], tree.ck_allocated(h)
    assert _all_reachable(h)


# --- 3. Regression guard: a legal allocation survives rebuild unchanged ------ #
def test_within_budget_untouched():
    # normal + ck both within budget: rebuild must not drop anything.
    h = _hero("warrior", level=60)
    _alloc_normal_chain(h, 5)
    h.class_point_sources = ["goblin_king"]  # 2 CP
    assert tree.allocate(h, _ck("warrior", 1))
    assert tree.allocate(h, _ck("warrior", 2))
    before = list(h.passives)
    pa_before = tree.points_available(h)
    cp_before = tree.class_points_available(h)
    tree.rebuild(h)
    assert h.passives == before, (h.passives, before)
    assert tree.points_available(h) == pa_before
    assert tree.class_points_available(h) == cp_before


# --- 4. Idempotent: rebuild twice == rebuild once --------------------------- #
def test_idempotent_after_drop():
    h = _hero("warrior", level=60)
    _alloc_normal_chain(h, 10)
    h.class_point_sources = ["goblin_king", "lich_emperor"]  # 4 CP
    for n in (1, 2, 3, 4):
        assert tree.allocate(h, _ck("warrior", n))
    # shrink both budgets at once.
    h.level = 4  # normal budget = 3
    h.class_point_sources = ["the_watcher"]  # 1 CP
    tree.rebuild(h)
    snap = (list(h.passives), h.stats.life,
            len(h.passive_mods), len(h.passive_ops))
    tree.rebuild(h)
    assert (list(h.passives), h.stats.life,
            len(h.passive_mods), len(h.passive_ops)) == snap
    # and both budgets are satisfied.
    assert tree.points_spent(h) <= h.level - 1
    assert len(tree.ck_allocated(h)) <= tree.class_points_total(h)
    assert _all_reachable(h)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("ALL TREE-REBUILD-BUDGET TESTS PASSED")
