#!/usr/bin/env python3
"""Tier C — corrosion debuff (slime armour-shred) tests.

Corrosion lives entirely in game/combat.py: slime-family attackers add a stack
on each landed hit (capped), each stack shaves the hero's EFFECTIVE armour for
that hit only (never mutates hero.stats, so it is recalc-safe), stacks clear in
one shot once CORROSION_DURATION elapses since the last stack, and the
`corrosion_immune` build flag (the_quarantine_rolls) negates the whole thing.

Run:
  python tests/test_corrosion.py   (NOT via -m)
or:
  python -m pytest tests/test_corrosion.py -q
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from game.combat import (
    CombatSystem, _is_slime,
    CORROSION_PER_STACK, CORROSION_MAX_STACKS, CORROSION_DURATION,
)
from game.core import DamageType, Hero, Monster, Stats


def _hero(**stat):
    base = dict(life=1000, damage_min=10, damage_max=10, attack_speed=1.0,
                crit_chance=0.0, crit_multi=200.0, armor=100.0)
    base.update(stat)
    h = Hero(name="H", stats=Stats(**base), base_stats=Stats(), class_id="warrior")
    h.init_hp()
    h.flags = set()
    h.skills_v2 = {}
    return h


def _mob(monster_id="slime", **stat):
    base = dict(life=100, damage_min=10, damage_max=10, attack_speed=1.0,
                crit_chance=0.0, crit_multi=100.0)
    base.update(stat)
    m = Monster(name="M", stats=Stats(**base), x=0.0, monster_id=monster_id,
                level=1, is_boss=False, damage_type=DamageType.PHYS)
    m.init_hp()
    return m


# --- slime detection --------------------------------------------------------- #
def test_is_slime_family():
    assert _is_slime(_mob(monster_id="slime"))
    assert _is_slime(_mob(monster_id="slime_green"))
    assert _is_slime(_mob(monster_id="mother_of_slimes"))
    assert not _is_slime(_mob(monster_id="orc_warlord"))
    assert not _is_slime(_mob(monster_id=""))


# --- a slime hit adds a stack; stacks cap at CORROSION_MAX_STACKS ------------ #
def test_slime_hits_add_and_cap_stacks():
    h = _hero()
    cs = CombatSystem(h)
    slime = _mob()
    for i in range(CORROSION_MAX_STACKS + 3):
        cs._monster_strike(slime)
    assert cs._corrosion_stacks == CORROSION_MAX_STACKS
    assert cs._corrosion_t == CORROSION_DURATION


# --- a non-slime hit never adds a stack -------------------------------------- #
def test_non_slime_adds_no_stack():
    h = _hero()
    cs = CombatSystem(h)
    orc = _mob(monster_id="orc_warlord")
    for _ in range(5):
        cs._monster_strike(orc)
    assert cs._corrosion_stacks == 0


# --- stacks clear in one shot after the duration lapses ---------------------- #
def test_corrosion_decays_after_duration():
    h = _hero()
    cs = CombatSystem(h)
    cs._monster_strike(_mob())
    assert cs._corrosion_stacks == 1

    # a sub-duration tick keeps the stack alive...
    cs._tick_corrosion(CORROSION_DURATION - 0.5)
    assert cs._corrosion_stacks == 1

    # ...and the tick that pushes past the deadline clears everything.
    cs._tick_corrosion(1.0)
    assert cs._corrosion_stacks == 0
    assert cs._corrosion_t == 0.0


# --- a fresh stack refreshes the timer (does not decay mid-fight) ------------ #
def test_stack_refreshes_timer():
    h = _hero()
    cs = CombatSystem(h)
    cs._monster_strike(_mob())
    cs._tick_corrosion(CORROSION_DURATION - 0.1)  # almost expired
    cs._monster_strike(_mob())                    # refresh
    assert cs._corrosion_t == CORROSION_DURATION
    cs._tick_corrosion(0.2)                        # would have expired w/o refresh
    assert cs._corrosion_stacks == 2


# --- corrosion_immune negates stacking entirely ----------------------------- #
def test_immune_takes_no_stacks():
    h = _hero()
    h.flags = {"corrosion_immune"}
    cs = CombatSystem(h)
    for _ in range(5):
        cs._monster_strike(_mob())
    assert cs._corrosion_stacks == 0


# --- stacks shave EFFECTIVE armour but never mutate hero.stats --------------- #
def test_corrosion_never_mutates_hero_stats():
    h = _hero(armor=100.0)
    cs = CombatSystem(h)
    for _ in range(CORROSION_MAX_STACKS):
        cs._monster_strike(_mob())
    # hero.stats.armor is untouched (recalc-safe); the shred is per-hit only.
    assert h.stats.armor == 100.0
    # sanity: the tunable actually shaves something at max stacks.
    shave = 1.0 - CORROSION_PER_STACK * CORROSION_MAX_STACKS
    assert 0.0 <= shave < 1.0


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("test_corrosion OK")


if __name__ == "__main__":
    _run()
