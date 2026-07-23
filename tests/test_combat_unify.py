#!/usr/bin/env python3
"""Tests for the 2b damage-unification + evasion (audit H1/H2/M1/M2).

Verifies the shared combat_math helpers behave identically on the skill path
(_deal) and that evasion actually rolls with its cap. Run:
  python tests/test_combat_unify.py   (NOT via -m)
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from game import combat_math as cm
from game.combat import CombatSystem
from game.core import CombatEvent, DamageType, Hero, Monster, Stats


class Roll:
    """Deterministic rng. uniform() returns a preset (or cycles a list)."""
    def __init__(self, value=0.0):
        self._vals = value if isinstance(value, list) else None
        self._i = 0
        self.value = value

    def uniform(self, a, b):
        if self._vals is not None:
            v = self._vals[self._i % len(self._vals)]
            self._i += 1
            return v
        return self.value


def _hero(**stat):
    base = dict(life=1000, damage_min=10, damage_max=10, attack_speed=1.0,
                crit_chance=0.0, crit_multi=200.0)
    base.update(stat)
    h = Hero(name="H", stats=Stats(**base), base_stats=Stats(), class_id="mage")
    h.init_hp()
    h.flags = set()
    h.skills_v2 = {}
    return h


def _mob(life=100, is_boss=False):
    m = Monster(name="M", stats=Stats(life=life), x=0.0, monster_id="t",
                level=1, is_boss=is_boss, damage_type=DamageType.PHYS)
    m.init_hp()
    return m


# --- H2: skills crit ------------------------------------------------------- #
def test_skill_crit_applies():
    # crit_chance 100 -> the skill hit MUST crit (mult 200% => double damage).
    h = _hero(crit_chance=100.0, crit_multi=200.0)
    m = _mob(10_000)
    ev: list[CombatEvent] = []
    cm._deal(h, m, 1.0, DamageType.PHYS, ev, rng=Roll(0.0))
    dealt = 10_000 - m.hp
    # base avg dmg = 10, *2 crit = 20
    assert abs(dealt - 20.0) < 1e-6, dealt
    assert any(e.kind == "crit" for e in ev), "no crit event on skill hit"


def test_skill_no_crit_when_zero_chance():
    h = _hero(crit_chance=0.0)
    m = _mob(10_000)
    ev: list[CombatEvent] = []
    cm._deal(h, m, 1.0, DamageType.PHYS, ev, rng=Roll(50.0))
    assert abs((10_000 - m.hp) - 10.0) < 1e-6
    assert all(e.kind != "crit" for e in ev)


# --- M2: skills leech ------------------------------------------------------ #
def test_skill_leech_heals_hero():
    h = _hero(life_leech=10.0)  # 10% of hit dmg back as life (cap 12%)
    h.hp = 500.0
    m = _mob(10_000)
    ev: list[CombatEvent] = []
    cm._deal(h, m, 1.0, DamageType.PHYS, ev, rng=Roll(50.0))  # 10 dmg, no crit
    # gain = 10 * 10% = 1.0
    assert abs(h.hp - 501.0) < 1e-6, h.hp


# --- M1: skill kills fire ck_kill_heal + ck_cull_10 ------------------------ #
def test_skill_kill_heal():
    h = _hero(); h.flags = {"ck_kill_heal"}; h.hp = 500.0
    m = _mob(5)
    cm._deal(h, m, 1.0, DamageType.PHYS, [], rng=Roll(50.0))
    assert not m.alive
    assert abs(h.hp - (500.0 + 0.02 * h.max_hp)) < 1e-6, h.hp


def test_skill_cull():
    h = _hero(); h.flags = {"ck_cull_10"}
    m = _mob(100); m.hp = 8.0  # below 10% -> culled by the hit
    cm._deal(h, m, 0.01, DamageType.PHYS, [], rng=Roll(50.0))
    assert not m.alive, "skill did not cull a sub-threshold mob"
    # boss cull threshold is 5%
    b = _mob(100, is_boss=True); b.hp = 8.0
    cm._deal(h, b, 0.01, DamageType.PHYS, [], rng=Roll(50.0))
    assert b.alive, "boss wrongly culled at 8% (threshold 5%)"


# --- H1: evasion ----------------------------------------------------------- #
def test_evasion_curve_and_cap():
    assert cm.evasion_chance(0) == 0.0
    assert cm.evasion_chance(-5) == 0.0
    # monotonic and always under the cap
    prev = -1.0
    for e in (10, 100, 500, 2000, 10_000, 10_000_000):
        c = cm.evasion_chance(e)
        assert c > prev, "evasion chance not monotonic"
        assert c <= cm.EVASION_CHANCE_CAP + 1e-9, c
        prev = c


def test_evasion_dodges_hit():
    # Huge evasion -> ~cap%. A roll below the chance dodges (no damage), a roll
    # above it lands.
    h = _hero(evasion=1_000_000.0)
    dodged = CombatSystem(h, Roll(0.0))  # uniform 0 < chance -> dodge
    mob = _mob(100); dodged.monsters = [mob]
    h.hp = 500.0
    dodged._monster_strike(mob)
    assert h.hp == 500.0, "evasive hero took damage on a dodged hit"
    assert any(e.kind == "miss" for e in dodged.events)

    # roll above the cap -> lands
    landed = CombatSystem(_hero(evasion=1_000_000.0), Roll(99.9))
    h2 = landed.hero; h2.hp = 500.0
    mob2 = _mob(100)
    mob2.stats.damage_min = mob2.stats.damage_max = 20.0
    landed.monsters = [mob2]
    landed._monster_strike(mob2)
    assert h2.hp < 500.0, "no-evasion-outcome hit dealt no damage"


def test_zero_evasion_never_dodges():
    h = _hero(evasion=0.0)
    assert not cm.rolls_dodge(h, Roll(0.0))


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("test_combat_unify OK")


if __name__ == "__main__":
    _run()
