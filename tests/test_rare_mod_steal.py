#!/usr/bin/env python3
"""Tier C — covenant_of_the_hunt rare mod steal tests.

On killing a Rare monster with `rare_mod_steal` equipped, the hero steals one of
its affixes (derived from the rare's own power in game.unique_specials) for
STEAL_DURATION seconds, capped at STEAL_MAX simultaneous steals. The stolen
StatMods live on hero._stolen_mods (folded into recalc); game.combat owns their
expiry via _tick_stolen.

Run:
  python tests/test_rare_mod_steal.py   (NOT via -m)
or:
  python -m pytest tests/test_rare_mod_steal.py -q
"""
import os
import random
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from game import mob_rarity
from game.combat import CombatSystem
from game.core import DamageType, Hero, Monster, Stats
from game.uniques import UNIQUES, _build
from game.unique_specials import STEAL_MAX, STEAL_DURATION, steal_mod_from

_COVENANT = next(u for u in UNIQUES if u.id == "covenant_of_the_hunt")


def _hero(with_covenant=False):
    h = Hero(name="H", stats=Stats(life=1000, damage_min=50, damage_max=50,
                                   attack_speed=1.0), base_stats=Stats(life=1000),
             class_id="warrior")
    h.init_hp()
    h.flags = set()
    h.skills_v2 = {}
    if with_covenant:
        # equip the real unique so `rare_mod_steal` is re-derived by recalc every
        # time (a bare hero.flags entry would be wiped on the first recalc).
        item = _build(_COVENANT, 30, random.Random(1))
        h.equipment = {item.slot.value: item}
    h.recalc()
    return h


def _rare(monster_id="orc", tier=mob_rarity.RARE, **stat):
    base = dict(life=200, damage_min=20, damage_max=30, attack_speed=1.0, armor=80.0)
    base.update(stat)
    m = Monster(name="R", stats=Stats(**base), x=0.0, monster_id=monster_id,
                level=10, is_boss=False, damage_type=DamageType.PHYS)
    m.init_hp()
    m.rarity_tier = tier
    return m


def _kill(cs, mob):
    cs.monsters = [mob]
    cs._deal(mob, mob.hp + 1.0, DamageType.PHYS, False)


# --- steal_mod_from always yields a usable StatMod --------------------------- #
def test_steal_pool_never_empty():
    rng = __import__("random").Random(1)
    for _ in range(20):
        mod = steal_mod_from(_rare(), rng)
        assert mod.stat and (mod.flat or mod.inc or mod.more)


# --- killing a Rare with the flag grants exactly one steal ------------------- #
def test_rare_kill_grants_one_steal():
    h = _hero(with_covenant=True)
    cs = CombatSystem(h)
    _kill(cs, _rare())
    assert len(cs._stolen) == 1
    assert len(h._stolen_mods) == 1
    # the stolen mod is now live in recalc (mods list carries it).
    assert h._stolen_mods[0] in h._stolen_mods


# --- without the flag, no steal even on a Rare kill -------------------------- #
def test_no_flag_no_steal():
    h = _hero()  # no rare_mod_steal
    cs = CombatSystem(h)
    _kill(cs, _rare())
    assert cs._stolen == []
    assert h._stolen_mods == []


# --- a Common/Magic kill never steals, even with the flag -------------------- #
def test_non_rare_kill_no_steal():
    h = _hero(with_covenant=True)
    cs = CombatSystem(h)
    _kill(cs, _rare(tier=mob_rarity.COMMON))
    _kill(cs, _rare(tier=mob_rarity.MAGIC))
    assert cs._stolen == []


# --- steals cap at STEAL_MAX (oldest drops when a new one exceeds the cap) ---- #
def test_steal_caps_at_max():
    h = _hero(with_covenant=True)
    cs = CombatSystem(h)
    for _ in range(STEAL_MAX + 4):
        _kill(cs, _rare())
    assert len(cs._stolen) == STEAL_MAX
    assert len(h._stolen_mods) == STEAL_MAX


# --- steals expire after STEAL_DURATION and recalc drops them ---------------- #
def test_steal_expires():
    h = _hero(with_covenant=True)
    cs = CombatSystem(h)
    _kill(cs, _rare())
    assert len(cs._stolen) == 1

    cs._tick_stolen(STEAL_DURATION - 1.0)   # still alive
    assert len(cs._stolen) == 1

    cs._tick_stolen(2.0)                     # pushes past expiry
    assert cs._stolen == []
    assert h._stolen_mods == []


# --- staggered steals expire independently ----------------------------------- #
def test_staggered_steal_expiry():
    h = _hero(with_covenant=True)
    cs = CombatSystem(h)
    _kill(cs, _rare())
    cs._tick_stolen(STEAL_DURATION - 5.0)    # first steal has 5s left
    _kill(cs, _rare())                       # second steal fresh (20s)
    cs._tick_stolen(6.0)                     # first expires, second survives
    assert len(cs._stolen) == 1
    assert len(h._stolen_mods) == 1


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("test_rare_mod_steal OK")


if __name__ == "__main__":
    _run()
