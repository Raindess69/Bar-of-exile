#!/usr/bin/env python3
"""Regression tests for AUDIT_20 #H3 — elemental resist must floor at 0.

The bug: a monster's elem resist >100% produced NEGATIVE elemental damage,
which (a) HEALED the target on the elem-only path and (b) on the auto-attack
strike path let that negative elem term cancel out the unrelated physical hit.

The fix in game/combat.py:
  * _mitigate_elem() returns max(0.0, raw*(1-res/100)) — res>100% => 0, never <0.
  * _strike_damage() runs each elem component through _mitigate_elem (already
    floored) and SUMS into total, so a floored-at-0 elem can never subtract phys.

These tests pin that invariant. Run:
  python tests/test_combat_elem_floor.py   (NOT via -m)
or:
  python -m pytest tests/test_combat_elem_floor.py -q
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from game.combat import CombatSystem, _mitigate_elem, _mitigate_phys
from game.core import DamageType, Hero, Monster, Stats


def _hero(**stat):
    base = dict(life=1000, damage_min=10, damage_max=10, attack_speed=1.0,
                crit_chance=0.0, crit_multi=200.0)
    base.update(stat)
    h = Hero(name="H", stats=Stats(**base), base_stats=Stats(), class_id="mage")
    h.init_hp()
    h.flags = set()
    h.skills_v2 = {}
    return h


def _mob(life=100, **stat):
    # NB: the RES_CAP (75%) clamp lives in apply_mods, NOT the Stats ctor, so we
    # can hand the mob an "impossible" >100% resist directly to exercise H3.
    m = Monster(name="M", stats=Stats(life=life, **stat), x=0.0, monster_id="t",
                level=1, is_boss=False, damage_type=DamageType.PHYS)
    m.init_hp()
    return m


# --- H3a: the mitigation helper itself floors at zero ---------------------- #
def test_mitigate_elem_floors_at_zero():
    mob = _mob(res_fire=200.0)  # 200% resist would give raw*(1-2) = -raw
    # >100% resist must yield EXACTLY 0.0, never a negative (heal).
    out = _mitigate_elem(100.0, mob.stats, DamageType.FIRE)
    assert out == 0.0, f"res>100%% did not floor at 0, got {out}"
    assert out >= 0.0

    # sanity: 0% resist passes raw through untouched, 50% halves it.
    clean = _mob(res_fire=0.0)
    assert _mitigate_elem(100.0, clean.stats, DamageType.FIRE) == 100.0
    half = _mob(res_fire=50.0)
    assert _mitigate_elem(100.0, half.stats, DamageType.FIRE) == 50.0

    # exactly 100% resist -> 0 (boundary), and non-positive raw -> 0.
    full = _mob(res_fire=100.0)
    assert _mitigate_elem(100.0, full.stats, DamageType.FIRE) == 0.0
    assert _mitigate_elem(0.0, clean.stats, DamageType.FIRE) == 0.0


# --- H3b: an over-100% resist can never heal via the strike path ----------- #
def test_elem_resist_never_heals_via_strike():
    # Hero deals 100 phys + 50 fire; mob has 200% fire resist and no armor.
    h = _hero(added_fire=50.0)
    mob = _mob(res_fire=200.0, armor=0.0)
    cs = CombatSystem(h)

    dmg = cs._strike_damage(mob, phys=100.0, mult=1.0)

    phys_mit = _mitigate_phys(100.0, mob.stats.armor)  # 100 (no armor)
    # The floored fire term (0) must not have subtracted anything from phys.
    assert dmg >= phys_mit - 1e-9, (
        f"negative fire ate phys: dmg={dmg} < phys_mit={phys_mit}")
    assert abs(dmg - phys_mit) < 1e-9, (
        f"fire should contribute exactly 0, dmg={dmg} phys_mit={phys_mit}")
    assert dmg > 0.0, "over-resist wrongly drove total damage to <=0"


# --- H3c: partial resist — one elem obliterated, the other + phys intact --- #
def test_multi_elem_partial_resist():
    # fire fully over-resisted (200% -> 0), cold not resisted (0% -> full).
    h = _hero(added_fire=50.0, added_cold=40.0)
    mob = _mob(res_fire=200.0, res_cold=0.0, armor=0.0)
    cs = CombatSystem(h)

    dmg = cs._strike_damage(mob, phys=100.0, mult=1.0)

    phys_mit = _mitigate_phys(100.0, mob.stats.armor)          # 100
    cold_mit = _mitigate_elem(40.0, mob.stats, DamageType.COLD)  # 40
    fire_mit = _mitigate_elem(50.0, mob.stats, DamageType.FIRE)  # 0
    assert fire_mit == 0.0
    # total is phys + cold only; the obliterated fire subtracts nothing.
    assert abs(dmg - (phys_mit + cold_mit)) < 1e-9, (
        f"total {dmg} != phys+cold {phys_mit + cold_mit} (fire={fire_mit})")
    assert dmg > phys_mit, "cold failed to add on top of phys"


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("test_combat_elem_floor OK")


if __name__ == "__main__":
    _run()
