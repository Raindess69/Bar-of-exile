#!/usr/bin/env python3
"""Tests for SK-H1 (ignite/shock now apply) + SK-H2 (revived talent mods).
Run: python tests/test_skills_talents.py  (NOT via -m).
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from game import skills_v2 as SV
from game import combat_math as cm
from game.core import CombatEvent, DamageType, Hero, Monster, Stats


class Roll:
    def __init__(self, value=0.0):
        self.value = value

    def uniform(self, a, b):
        return self.value

    def random(self):
        return self.value


def _hero():
    h = Hero(name="H", stats=Stats(life=1000, damage_min=10, damage_max=10,
                                   crit_chance=0.0, crit_multi=200.0),
             base_stats=Stats(), class_id="mage")
    h.init_hp()
    h.flags = set()
    h.skills_v2 = {"sxp": {}, "talents": {}, "awakened": []}
    return h


def _skill(**kw):
    d = dict(id="t", name="T", class_id="mage", type="spender", tags=[],
             damage_type=DamageType.FIRE, unlock_level=1, cooldown_s=5.0,
             base_damage_pct=100.0, hits=1, per_rank_more_pct=4,
             per_rank_secondary_pct=2, rank_cap=20, range_px=200.0,
             effect="", params={})
    d.update(kw)
    return SV.SkillV2(**d)


# --- SK-H1: ignite / shock fall back to the skill's element ---------------- #
def test_fire_skill_ignites():
    h = _hero()
    sk = _skill(damage_type=DamageType.FIRE, tags=["fire"])
    a = SV._ailment_from(h, sk)
    assert a and a[0] == "ignite", a


def test_lightning_skill_shocks():
    h = _hero()
    sk = _skill(damage_type=DamageType.LIGHTNING, tags=["light"])
    a = SV._ailment_from(h, sk)
    assert a and a[0] == "shock", a


def test_explicit_ailment_beats_element():
    # a fire skill that explicitly poisons stays poison
    h = _hero()
    sk = _skill(damage_type=DamageType.FIRE, tags=["fire"], params={"poison_pct": 50})
    a = SV._ailment_from(h, sk)
    assert a and a[0] == "poison", a


def test_phys_skill_no_element_ailment():
    h = _hero()
    sk = _skill(damage_type=DamageType.PHYS, tags=["melee"])
    assert SV._ailment_from(h, sk) is None


# --- SK-H2: crit / lifesteal talents ride the cast ctx --------------------- #
def test_ctx_crit_chance_makes_skill_crit():
    h = _hero()  # base crit_chance 0
    h._skill_ctx = {"damage_inc": 0.0, "dealt": 0.0,
                    "crit_chance": 100.0, "crit_multi": 0.0}
    m = Monster(name="M", stats=Stats(life=10_000), x=0.0, monster_id="t",
                level=1, damage_type=DamageType.PHYS); m.init_hp()
    ev = []
    cm._deal(h, m, 1.0, DamageType.PHYS, ev, rng=Roll(0.0))
    assert any(e.kind == "crit" for e in ev), "ctx crit_chance did not force a crit"
    # 10 base * 200% crit_multi = 20
    assert abs((10_000 - m.hp) - 20.0) < 1e-6, 10_000 - m.hp


def test_ctx_lifesteal_heals():
    h = _hero(); h.hp = 500.0
    h._skill_ctx = {"damage_inc": 0.0, "dealt": 0.0, "crit_chance": 0.0,
                    "crit_multi": 0.0, "lifesteal": 10.0}
    m = Monster(name="M", stats=Stats(life=10_000), x=0.0, monster_id="t",
                level=1, damage_type=DamageType.PHYS); m.init_hp()
    cm._deal(h, m, 1.0, DamageType.PHYS, [], rng=Roll(50.0))
    # 10 dmg * 10% lifesteal = 1.0
    assert abs(h.hp - 501.0) < 1e-6, h.hp


def test_extra_targets_widens_aoe_cap():
    # extra_targets should raise a capped AoE's pool. We check the param math via
    # a crafted skill + monkeypatched talents.
    h = _hero()
    sk = _skill(tags=["aoe"], params={"aoe": True, "max_targets": 1})
    # inject a talent choice that grants extra_targets by faking _talent_mods
    orig = SV._talent_mods
    SV._talent_mods = lambda hero, skill: {"extra_targets": 2}
    try:
        ms = [Monster(name=f"M{i}", stats=Stats(life=10_000), x=float(i * 5),
                      monster_id="t", level=1, damage_type=DamageType.FIRE)
              for i in range(4)]
        for m in ms:
            m.init_hp()
        ev = []
        SV._apply_effect(h, sk, ms, ev, Roll(50.0))
        hurt = sum(1 for m in ms if m.hp < m.max_hp)
        assert hurt == 3, f"max_targets 1 + extra 2 -> 3 hit, got {hurt}"
    finally:
        SV._talent_mods = orig


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("test_skills_talents OK")


if __name__ == "__main__":
    _run()
