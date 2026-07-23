#!/usr/bin/env python3
"""Plain-assert tests for the 6 simple keystone effects (V2 step 4):
glass_cannon, juggernaut, deadeye, berserker_oath, vampiric_pact, timeworn.
Run: python tests/test_keystones.py  or  python -m tests.test_keystones"""
import os
import random
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from game import tree
from game.combat import DEADEYE_MORE, DEADEYE_RANGE, CombatSystem
from game.combat_math import _heal
from game.core import CombatEvent, Hero, Monster, Stats
from game.progression import grant_xp


def _keystone(effect: str) -> tree.NodeDef:
    return next(n for n in tree.NODES.values() if n.kind == "keystone"
                and any(op.get("op") == "flag" and op.get("stat") == effect
                        for op in n.ops))


def _alloc_keystone(effect: str) -> tuple[tree.NodeDef, Hero, Stats]:
    """Allocate the keystone on a real hero via its (hacked-adjacent) neighbor,
    like the tree.py __main__ smoke. Returns (node, hero, stats before keystone)."""
    ks = _keystone(effect)
    hero = Hero(name="T", stats=Stats(), base_stats=Stats(), class_id="warrior")
    hero.init_hp()
    hero.recalc()
    hero.bonus_points = 2
    hero.passives.append(next(iter(tree.ADJ[ks.id])))  # hacked adjacency, fine for tests
    tree._apply(hero)
    before = hero.stats.copy()
    assert tree.allocate(hero, ks.id), f"could not allocate {ks.id}"
    return ks, hero, before


def _flag_hero(effect: str | None, hp_frac: float = 1.0, **base) -> Hero:
    """Hero with a keystone flag set via passive_ops (survives recalc)."""
    hero = Hero(name="T", stats=Stats(), base_stats=Stats(**base), class_id="archer")
    if effect:
        hero.passive_ops = [{"op": "flag", "stat": effect}]
    hero.recalc()
    hero.init_hp()
    hero.hp = hero.max_hp * hp_frac
    return hero


def _strike_value(effect: str | None, distance: float, hp_frac: float = 1.0,
                  seed: int = 1) -> float:
    hero = _flag_hero(effect, hp_frac, damage_min=10, damage_max=20, crit_chance=0)
    cs = CombatSystem(hero, random.Random(seed))
    mob = Monster(name="Dummy", stats=Stats(life=10000, armor=0),
                  x=hero.x + distance, monster_id="dummy", level=1)
    mob.init_hp()
    cs.monsters.append(mob)
    cs._hero_strike(mob)
    return cs.events[0].value


def test_glass_cannon():
    ks, hero, before = _alloc_keystone("glass_cannon")
    assert any(m.stat == "damage_min" and m.inc == 60 for m in ks.mods), ks.mods
    assert any(m.stat == "damage_max" and m.inc == 60 for m in ks.mods), ks.mods
    assert any(m.stat == "life" and m.more == -30 for m in ks.mods), ks.mods
    # end-to-end: flag lands in hero.flags through real tree allocation
    assert "glass_cannon" in hero.flags
    # more-bucket is multiplicative -> exactly -30% life whatever the neighbor adds
    assert abs(hero.max_hp - before.life * 0.7) < 1e-9, (hero.max_hp, before.life)
    # inc-bucket is additive -> account for any inc the neighbor node carries
    inc0 = sum(m.inc for m in hero.passive_mods if m.stat == "damage_min") - 60
    factor = (100 + inc0 + 60) / (100 + inc0)
    assert abs(hero.stats.damage_min - before.damage_min * factor) < 1e-9


def test_juggernaut():
    ks, hero, before = _alloc_keystone("juggernaut")
    assert any(m.stat == "move_speed" and m.more == -10 for m in ks.mods), ks.mods
    assert "juggernaut" in hero.flags
    assert abs(hero.stats.move_speed - before.move_speed * 0.9) < 1e-9


def test_timeworn_xp_penalty():
    events: list[CombatEvent] = []
    hero = _flag_hero("timeworn")
    grant_xp(hero, 100, events)
    assert hero.xp == 90, hero.xp
    plain = _flag_hero(None)
    grant_xp(plain, 100, events)
    assert plain.xp == 100, plain.xp


def test_deadeye_distant_bonus():
    far = _strike_value("deadeye", DEADEYE_RANGE + 50)
    near = _strike_value("deadeye", DEADEYE_RANGE - 50)
    assert abs(far - near * DEADEYE_MORE) < 1e-9, (far, near)
    # no flag -> no bonus at any range
    assert abs(_strike_value(None, DEADEYE_RANGE + 50) - near) < 1e-9


def test_berserker_oath_missing_life():
    full = _strike_value("berserker_oath", 50, hp_frac=1.0)
    half = _strike_value("berserker_oath", 50, hp_frac=0.5)
    # +2% per 1% missing life -> x2.0 at 50% hp
    assert abs(half - full * 2.0) < 1e-9, (full, half)
    assert abs(_strike_value(None, 50, hp_frac=0.5) - full) < 1e-9


def test_vampiric_pact_halves_healing():
    def cast(effect):
        hero = _flag_hero(effect, hp_frac=0.4, life=100)
        events: list[CombatEvent] = []
        _heal(hero, 0.10, events)
        return hero, events[0]
    plain, ev_p = cast(None)
    pact, ev_v = cast("vampiric_pact")
    assert ev_p.value == 10.0 and plain.hp == 50.0, (ev_p.value, plain.hp)
    assert ev_v.value == 5.0 and pact.hp == 45.0, (ev_v.value, pact.hp)
    # overheal: event carries the actual healed amount, not the raw roll
    top = _flag_hero(None, life=100)
    top.hp = top.max_hp - 2
    events: list[CombatEvent] = []
    _heal(top, 0.10, events)
    assert events[0].value == 2.0 and top.hp == top.max_hp


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("ALL KEYSTONE TESTS PASSED")
