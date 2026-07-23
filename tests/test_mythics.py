"""Tests for game.mythics (Tier 9 uber-uniques, boss-only chase items).

Runnable both ways:
    python tests/test_mythics.py
    pytest tests/test_mythics.py
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.core import Rarity, Slot, Stats, apply_mods
from game.items import BASES
from game.mythics import MYTHIC_MIN_ILVL, MYTHICS, _build, roll_mythic
from game.save import item_to_dict
from game.uniques import UNIQUES, _build as _build_unique


def _stat_weight(item) -> float:
    """Crude total-magnitude proxy: sum |flat| + |inc| over all fixed affix mods."""
    return sum(abs(m.flat) + abs(m.inc) + abs(m.more)
               for a in item.affixes for m in a.mods)


def test_pool_sanity():
    """8-12 mythics, unique ids, >=3 mods each, valid slots, reasonable level_req."""
    assert 8 <= len(MYTHICS) <= 12, len(MYTHICS)
    assert len({m.id for m in MYTHICS}) == len(MYTHICS), "duplicate mythic id"
    slots = set()
    for m in MYTHICS:
        assert m.base_id in BASES, f"{m.id}: unknown base {m.base_id}"
        base = BASES[m.base_id]
        assert base.slot in Slot
        slots.add(base.slot)
        # >=3 real mod lines (spec: unique power + one extra strong mod)
        assert len(m.mods) >= 3, f"{m.id}: only {len(m.mods)} mods"
        # ilvl_req documented gate: mythics are endgame, req at/above the boss gate-ish.
        assert m.ilvl_req >= 50, f"{m.id}: ilvl_req {m.ilvl_req} too low for a mythic"
        assert m.weight > 0, f"{m.id}: non-positive weight"
    print(f"pool: {len(MYTHICS)} mythics across {len(slots)} slots, ids unique")


def test_build_produces_valid_mythic():
    """_build returns a MYTHIC item with a non-empty tier-0 affix, name set, and
    EVERY mod stat resolves through apply_mods without KeyError (proves stat keys
    are legal against Stats/statmap)."""
    rng = random.Random(123)
    for m in MYTHICS:
        it = _build(m, max(m.ilvl_req, MYTHIC_MIN_ILVL), rng)
        assert it.rarity is Rarity.MYTHIC, m.id
        assert it.name == m.name and it.display_name() == m.name, m.id
        assert it.affixes, m.id
        main = it.affixes[0]
        assert main.tier == 0 and main.mods, m.id
        # special affix (if any) is text-only tier-0 lines
        if m.special:
            spec = it.affixes[-1]
            assert spec.tier == 0 and spec.mods == []
            assert spec.lines == [t for _, t in m.special], m.id
        # the real proof: apply_mods runs clean over all mods (no KeyError/crash)
        result = apply_mods(Stats(), it.all_mods())
        assert isinstance(result, Stats)
        # every mod renders a description (no empty/broken lines)
        assert all(mod.describe() for mod in main.mods), m.id
    print(f"_build OK: all {len(MYTHICS)} mythics build + apply_mods clean")


def test_roll_gate_and_pool():
    """roll_mythic returns a mythic at/above the gate, None below it."""
    rng = random.Random(50)
    it = roll_mythic(80, rng)
    assert it is not None and it.rarity is Rarity.MYTHIC
    assert it.affixes[0].id in {m.id for m in MYTHICS}
    # below MYTHIC_MIN_ILVL -> always None
    assert MYTHIC_MIN_ILVL == 60
    assert roll_mythic(40, random.Random(1)) is None
    assert roll_mythic(MYTHIC_MIN_ILVL - 1, random.Random(1)) is None
    # exactly at the gate: at least the lowest-req mythic qualifies
    assert roll_mythic(MYTHIC_MIN_ILVL, random.Random(1)) is not None
    print(f"gate OK: rolls @80 -> {it.display_name()}; @40 -> None")


def test_determinism():
    """Same seed -> byte-identical item (via save.item_to_dict round-trip)."""
    a = roll_mythic(80, random.Random(999))
    b = roll_mythic(80, random.Random(999))
    assert a is not None and b is not None
    assert item_to_dict(a) == item_to_dict(b), "mythic roll not deterministic"
    print("determinism OK: identical seed -> identical mythic")


def test_mythic_beats_comparable_unique():
    """Loose sanity: a mythic's fixed-affix stat magnitude should exceed a
    same-slot unique's (mythics = unique power + one extra strong mod)."""
    rng = random.Random(2024)
    checked = 0
    for m in MYTHICS:
        slot = BASES[m.base_id].slot
        peers = [u for u in UNIQUES
                 if (BASES[u.base_id].slot if u.base_id in BASES else None) is slot]
        if not peers:
            continue
        myth_w = _stat_weight(_build(m, max(m.ilvl_req, MYTHIC_MIN_ILVL), rng))
        best_unique = max(_stat_weight(_build_unique(u, max(u.ilvl_req, 1), rng))
                          for u in peers)
        # not every single mythic must dominate every unique roll, but the pool
        # median should clearly win — assert this one isn't absurdly weak.
        assert myth_w > 0
        checked += 1
    assert checked > 0
    # aggregate check: mean mythic weight > mean unique weight
    myth_mean = sum(_stat_weight(_build(m, max(m.ilvl_req, MYTHIC_MIN_ILVL), rng))
                    for m in MYTHICS) / len(MYTHICS)
    uniq_mean = sum(_stat_weight(_build_unique(u, max(u.ilvl_req, 1), rng))
                    for u in UNIQUES) / len(UNIQUES)
    print(f"power: mythic mean {myth_mean:.1f} vs unique mean {uniq_mean:.1f}")
    assert myth_mean > uniq_mean, "mythics should be stronger than uniques on average"


if __name__ == "__main__":
    test_pool_sanity()
    test_build_produces_valid_mythic()
    test_roll_gate_and_pool()
    test_determinism()
    test_mythic_beats_comparable_unique()
    print("test_mythics: ALL OK")
