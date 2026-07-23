#!/usr/bin/env python3
"""S.4 REWORK — class ascendancy sub-tree tests (CLASS_KEYSTONES_TREE_REWORK.md §4).

Covers the merged graph, class/level/exclusive gates, the Class Point economy
(grant + retro-grant + save roundtrip), stat coverage, the four combat flag
hooks, and legacy-save survival.
Run: python tests/test_class_keystones.py  or  python -m pytest tests/test_class_keystones.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from game import tree
from game.combat import (CULL_FRAC, CULL_FRAC_BOSS, KILL_HEAL_FRAC,
                         OVERHEAL_CAP_FRAC, CombatSystem, DamageType)
from game.core import Hero, Monster, Stats
from game.save import hero_from_dict, hero_to_dict


def _hero(class_id="warrior", level=60):
    h = Hero(name="T", stats=Stats(), base_stats=Stats(), class_id=class_id, level=level)
    h.init_hp()
    h.recalc()
    return h


def _ck(cls, n):
    return f"ck_{cls}_{n}"


# ---------------------------------------------------------------------------
# 1. Merge: base tree intact, +37 ck nodes, edges valid, each ck reachable.
# ---------------------------------------------------------------------------
def test_merge_shape():
    ck = [nid for nid, nd in tree.NODES.items() if nd.kind == "ck"]
    assert len(ck) == 37, len(ck)
    # base graph untouched: the 5 class starts + a healthy node count remain.
    starts = [nid for nid, nd in tree.NODES.items() if nd.kind == "class_start"]
    assert len(starts) == 5, starts
    base = [nid for nid, nd in tree.NODES.items()
            if nd.kind not in ("ck",)]
    assert len(base) >= 1002, len(base)  # 1002 baked nodes survive the merge
    # every ck node reaches its own class start through the graph.
    for nid in ck:
        node = tree.NODES[nid]
        start = tree.start_id_for(node.class_req)
        seen, stack = {start}, [start]
        while stack:
            for nb in tree.ADJ.get(stack.pop(), ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        assert nid in seen, f"{nid} unreachable from {start}"


# ---------------------------------------------------------------------------
# 2. class_req: foreign class can't allocate; own class can (given level + CP).
# ---------------------------------------------------------------------------
def test_class_req():
    mage = _hero("mage")
    mage.class_point_sources = ["goblin_king"]  # 2 CP
    # warrior entry node is not even available to a mage
    assert not tree.is_available(mage, _ck("warrior", 1))
    assert not tree.allocate(mage, _ck("warrior", 1))
    # own class entry: available and allocatable
    war = _hero("warrior")
    war.class_point_sources = ["goblin_king"]
    assert tree.is_available(war, _ck("warrior", 1))
    assert tree.allocate(war, _ck("warrior", 1))
    assert _ck("warrior", 1) in war.passives


# ---------------------------------------------------------------------------
# 3. level_req: hero 29 can't take a mech node, hero 30 can.
# ---------------------------------------------------------------------------
def test_level_req():
    # ck_warrior_6 (Executioner) is level_req 30 and hangs off the entry node.
    lo = _hero("warrior", level=29)
    lo.class_point_sources = ["goblin_king", "lich_emperor"]  # 4 CP
    tree.allocate(lo, _ck("warrior", 1))  # entry (level 0)
    assert not tree.allocate(lo, _ck("warrior", 6)), "lvl 29 took a lvl-30 node"
    hi = _hero("warrior", level=30)
    hi.class_point_sources = ["goblin_king", "lich_emperor"]
    tree.allocate(hi, _ck("warrior", 1))
    assert tree.allocate(hi, _ck("warrior", 6)), "lvl 30 couldn't take lvl-30 node"


# ---------------------------------------------------------------------------
# 4. exclusive_group: only one mage_lock node allocatable.
# ---------------------------------------------------------------------------
def test_exclusive_group():
    m = _hero("mage")
    m.class_point_sources = ["goblin_king", "lich_emperor"]  # 4 CP
    tree.allocate(m, _ck("mage", 1))  # entry — locks hang off it
    locks = [nid for nid, nd in tree.NODES.items()
             if nd.exclusive_group == "mage_lock"]
    assert len(locks) == 3, locks
    assert tree.allocate(m, locks[0]), "first lock should allocate"
    assert not tree.allocate(m, locks[1]), "second lock of group allocated"
    assert not tree.allocate(m, locks[2]), "third lock of group allocated"


# ---------------------------------------------------------------------------
# 5. Class Points: grant is deduped; ck spends CP not tree points; no negatives.
# ---------------------------------------------------------------------------
def test_class_point_grant_and_spend():
    h = _hero("warrior")
    assert tree.class_points_total(h) == 0
    assert tree.grant_class_point(h, "goblin_king") == 2
    assert tree.grant_class_point(h, "goblin_king") == 0, "double grant"
    assert tree.class_points_total(h) == 2
    assert tree.grant_class_point(h, "not_a_boss") == 0, "unknown boss granted CP"
    # allocating a ck node spends CP but leaves tree points untouched.
    tp_before = tree.points_available(h)
    assert tree.class_points_available(h) == 2
    assert tree.allocate(h, _ck("warrior", 1))
    assert tree.class_points_available(h) == 1
    assert tree.points_available(h) == tp_before, "ck spent a tree point"
    # spend the last, then can't buy more (never goes negative).
    assert tree.allocate(h, _ck("warrior", 2))
    assert tree.class_points_available(h) == 0
    assert not tree.allocate(h, _ck("warrior", 3)), "bought ck with 0 CP"
    assert tree.class_points_available(h) >= 0


# ---------------------------------------------------------------------------
# 6. Retro-grant + roundtrip of class_point_sources through save/load.
# ---------------------------------------------------------------------------
def test_retro_grant_and_roundtrip():
    h = _hero("cleric")
    # meta says two act bosses already fell (on different difficulties).
    kills = ["goblin_king@normal", "lich_emperor@normal", "goblin_king@cruel"]
    gained = tree.sync_class_points_from_kills(h, kills)
    assert gained == 4, gained  # goblin(2) + lich(2), goblin dedup across diffs
    assert tree.class_points_total(h) == 4
    # idempotent: syncing again grants nothing.
    assert tree.sync_class_points_from_kills(h, kills) == 0
    # roundtrip.
    h2 = hero_from_dict(hero_to_dict(h))
    assert sorted(h2.class_point_sources) == sorted(h.class_point_sources)
    assert tree.class_points_total(h2) == 4


# ---------------------------------------------------------------------------
# 7. Coverage: no ck mod stat is inert (all resolve to real Stats fields).
# ---------------------------------------------------------------------------
def test_no_inert_ck_stats():
    fields = set(vars(Stats()).keys())
    inert = []
    for nid, nd in tree.NODES.items():
        if nd.kind != "ck":
            continue
        for m in nd.mods:
            if m.stat not in fields:
                inert.append((nid, m.stat))
    assert not inert, f"inert ck stats: {inert}"


# ---------------------------------------------------------------------------
# 8. Combat hooks: cull, overheal cap, fifth-shot crit, kill-heal.
# ---------------------------------------------------------------------------
def _combat_hero(flags):
    h = Hero(name="H", stats=Stats(life=100, damage_min=5, damage_max=5,
                                   attack_speed=1.0, crit_chance=0, crit_multi=200),
             base_stats=Stats(), class_id="warrior")
    h.init_hp()
    h.flags = set(flags)
    return h


def _mob(life, is_boss=False):
    m = Monster(name="M", stats=Stats(life=life, armor=0), x=0.0,
                monster_id="t", level=1, is_boss=is_boss, damage_type=DamageType.PHYS)
    m.init_hp()
    return m


def test_hook_cull():
    c = CombatSystem(_combat_hero({"ck_cull_10"}), random.Random(1))
    mob = _mob(100); mob.hp = 9.0; c.monsters.append(mob)
    if mob.hp <= mob.max_hp * CULL_FRAC:
        c._deal(mob, mob.hp + 1.0, DamageType.PHYS, False)
    assert not mob.alive, "9% normal mob not culled"
    boss = _mob(100, is_boss=True); boss.hp = 9.0; c.monsters.append(boss)
    if boss.hp <= boss.max_hp * (CULL_FRAC_BOSS if boss.is_boss else CULL_FRAC):
        c._deal(boss, boss.hp + 1.0, DamageType.PHYS, False)
    assert boss.alive, "boss culled at 9% (should need <=5%)"


def test_hook_overheal_cap():
    h = _combat_hero({"ck_overheal"})
    h.stats.life_leech = 100.0
    c = CombatSystem(h, random.Random(3))
    h.hp = h.max_hp  # full -> all leech overflows to temp HP
    c._apply_leech(1000.0)
    cap = OVERHEAL_CAP_FRAC * h.max_hp
    assert abs(getattr(h, "_ck_temp_hp") - cap) < 1e-9, getattr(h, "_ck_temp_hp")


def test_hook_fifth_shot():
    h = _combat_hero({"ck_fifth_shot"})
    c = CombatSystem(h, random.Random(2))
    crits = []
    for _ in range(10):
        c.events.clear()
        mob = _mob(10_000); c.monsters = [mob]
        c._hero_strike(mob)
        crits.append(any(e.kind == "crit" for e in c.events))
    assert crits == [False, False, False, False, True] * 2, crits


def test_hook_kill_heal():
    h = _combat_hero({"ck_kill_heal"})
    c = CombatSystem(h, random.Random(4))
    h.hp = 50.0
    m = _mob(5); c.monsters = [m]
    c._deal(m, 999.0, DamageType.PHYS, False)  # kill
    assert not m.alive
    assert abs(h.hp - (50.0 + KILL_HEAL_FRAC * h.max_hp)) < 1e-9, h.hp


# ---------------------------------------------------------------------------
# 9. Save/load roundtrip of allocated ck nodes; rebuild refunds unknown ck ids.
# ---------------------------------------------------------------------------
def test_ck_save_roundtrip_and_rebuild():
    h = _hero("archer")
    h.class_point_sources = ["goblin_king", "lich_emperor"]  # 4 CP
    assert tree.allocate(h, _ck("archer", 1))
    assert tree.allocate(h, _ck("archer", 2))
    h2 = hero_from_dict(hero_to_dict(h))
    tree.rebuild(h2)
    assert _ck("archer", 1) in h2.passives and _ck("archer", 2) in h2.passives
    assert tree.class_points_available(h2) == 2  # 4 granted - 2 spent
    # a bogus ck id is dropped on rebuild without crashing (CP refunds).
    h2.passives.append("ck_archer_999")
    tree.rebuild(h2)
    assert "ck_archer_999" not in h2.passives
    assert tree.class_points_available(h2) == 2


# ---------------------------------------------------------------------------
# 10. Legacy save with old v1 skills_v2.keystones loads without crashing.
# ---------------------------------------------------------------------------
def test_legacy_v1_keystones_ignored():
    h = _hero("mage")
    d = hero_to_dict(h)
    d["skills_v2"] = {"keystones": ["some_old_v1_id"], "unlocked": []}
    h2 = hero_from_dict(d)  # must not raise
    tree.rebuild(h2)        # must not raise
    assert "some_old_v1_id" not in h2.passives


# ---------------------------------------------------------------------------
# 11. rebuild re-validates ck gates (SAVE-M2): corrupted/regenerated saves.
#     allocate gates these live, but rebuild (load/migration) did not — a
#     hand-edited or regenerated save could strand illegal ck allocations.
# ---------------------------------------------------------------------------
def test_rebuild_drops_extra_exclusive_group_member():
    # Corrupted save: two mage_lock ck nodes allocated at once (allocate forbids
    # this, but a save edit / data regen could produce it). rebuild keeps one.
    m = _hero("mage", level=30)
    m.class_point_sources = ["goblin_king", "lich_emperor"]  # 4 CP
    # hand-built passives bypassing the allocate gate: entry + two locks.
    m.passives = [_ck("mage", 1), _ck("mage", 6), _ck("mage", 7)]
    assert tree.NODES[_ck("mage", 6)].exclusive_group == "mage_lock"
    assert tree.NODES[_ck("mage", 7)].exclusive_group == "mage_lock"
    tree.rebuild(m)
    locks_left = [nid for nid in tree.ck_allocated(m)
                  if tree.NODES[nid].exclusive_group == "mage_lock"]
    assert len(locks_left) == 1, locks_left
    assert locks_left == [_ck("mage", 6)], "kept the wrong (non-first) lock"
    assert _ck("mage", 1) in m.passives, "dropped the entry node"
    # CP refunded: 4 granted - 2 kept ck = 2 available.
    assert tree.class_points_available(m) == 2, tree.class_points_available(m)


def test_rebuild_drops_ck_over_level_req():
    # Corrupted save: ck_warrior_6 (Executioner) is level_req 30, hero is 29.
    w = _hero("warrior", level=29)
    w.class_point_sources = ["goblin_king"]  # 2 CP
    w.passives = [_ck("warrior", 1), _ck("warrior", 6)]  # entry + lvl-30 node
    assert tree.NODES[_ck("warrior", 6)].level_req == 30
    tree.rebuild(w)
    assert _ck("warrior", 6) not in w.passives, "kept a node above level_req"
    assert _ck("warrior", 1) in w.passives, "dropped the valid entry node"
    # CP refunded: 2 granted - 1 kept ck = 1 available.
    assert tree.class_points_available(w) == 1, tree.class_points_available(w)


def test_rebuild_keeps_valid_ck_untouched():
    # REGRESSION: a valid save (one ck per group, level_req satisfied) survives
    # rebuild unchanged — the new re-validation must not touch legal allocations.
    w = _hero("warrior", level=60)
    w.class_point_sources = ["goblin_king"]  # 2 CP
    w.passives = [_ck("warrior", 1), _ck("warrior", 2)]  # both level_req 0, no group
    before = list(w.passives)
    cp_before = tree.class_points_available(w)
    tree.rebuild(w)
    assert w.passives == before, (w.passives, before)
    assert tree.class_points_available(w) == cp_before == 0, tree.class_points_available(w)
    # idempotent second pass.
    tree.rebuild(w)
    assert w.passives == before


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("ALL CLASS-KEYSTONE TESTS PASSED")
