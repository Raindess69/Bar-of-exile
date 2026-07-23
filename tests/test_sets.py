"""Tests for game.sets (Tier 6 set items).

Runnable both ways:
    python tests/test_sets.py
    pytest tests/test_sets.py
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.core import Rarity, Slot, Stats
from game.sets import (
    SETS,
    active_set_summary,
    build_set_item,
    roll_set_item,
    set_bonus_mods,
    set_id_of,
)


def _real_stat(mod) -> bool:
    return hasattr(Stats(), mod.stat)


def test_set_defs_valid():
    """Every set: distinct slots per piece, bonuses at 2/3(/4), real Stats fields."""
    assert len(SETS) >= 3, len(SETS)
    seen_ids: set[str] = set()
    seen_bases: set[str] = set()
    for sd in SETS:
        assert sd.id not in seen_ids, f"duplicate set id {sd.id}"
        seen_ids.add(sd.id)
        assert 3 <= len(sd.pieces) <= 4, (sd.id, len(sd.pieces))
        slots = [p.slot for p in sd.pieces]
        assert len(slots) == len(set(slots)), f"{sd.id}: pieces share a slot {slots}"
        for p in sd.pieces:
            assert isinstance(p.slot, Slot)
            assert p.base_id not in seen_bases, f"duplicate base_id {p.base_id}"
            seen_bases.add(p.base_id)
            for m in p.mods:
                assert _real_stat(m), f"{sd.id}/{p.base_id}: bad stat {m.stat}"
        # bonuses: at least the 2 and 3 thresholds; every mod uses a real field
        assert 2 in sd.bonuses and 3 in sd.bonuses, (sd.id, sorted(sd.bonuses))
        for thr, bonus in sd.bonuses.items():
            assert thr in (2, 3, 4), (sd.id, thr)
            assert bonus, f"{sd.id}: empty bonus at {thr}"
            for m in bonus:
                assert _real_stat(m), f"{sd.id} bonus@{thr}: bad stat {m.stat}"
    print(f"set defs OK: {len(SETS)} sets, {len(seen_bases)} unique piece bases")


def test_build_and_recover():
    """build_set_item -> Rarity.SET, correct slot/affixes; set_id_of recovers it."""
    rng = random.Random(1)
    for sd in SETS:
        for i, p in enumerate(sd.pieces):
            it = build_set_item(sd.id, i, sd.min_ilvl, rng)
            assert it.rarity is Rarity.SET, it.rarity
            assert it.slot is p.slot
            assert it.base_id == p.base_id
            assert len(it.affixes) == 1 and it.affixes[0].tier == 0
            # fixed affixes carried onto the item, pre-rendered lines present
            assert len(it.affixes[0].mods) == len(p.mods)
            assert it.affixes[0].lines and all("{" not in ln for ln in it.affixes[0].lines)
            assert set_id_of(it) == sd.id
    print("build + set_id_of OK")


def test_set_id_of_non_set():
    """A non-set item (unknown base_id) recovers None."""
    from game.items import make_base_item
    plain = make_base_item("rusted_sword", 5)
    assert set_id_of(plain) is None
    print("set_id_of(non-set) -> None OK")


def test_bonus_thresholds():
    """1 piece -> no bonus; 2 -> 2-set; 4 -> 2+3+4; two sets counted apart."""
    full = [sd for sd in SETS if len(sd.pieces) >= 4][0]
    rng = random.Random(2)
    pieces = [build_set_item(full.id, i, full.min_ilvl, rng)
              for i in range(len(full.pieces))]

    # 1 piece -> nothing
    assert set_bonus_mods(pieces[:1]) == []

    # 2 pieces -> exactly the 2-set bonus
    got2 = set_bonus_mods(pieces[:2])
    assert got2 == full.bonuses[2], (got2, full.bonuses[2])

    # 4 pieces -> union of 2 + 3 + 4
    got4 = set_bonus_mods(pieces[:4])
    expect4 = full.bonuses[2] + full.bonuses[3] + full.bonuses[4]
    assert got4 == expect4, (len(got4), len(expect4))
    # sanity: a stat that only the 4-bonus grants shows up
    stats4 = {m.stat for m in full.bonuses[4]}
    assert stats4 <= {m.stat for m in got4}

    # two different sets counted independently
    other = next(sd for sd in SETS if sd.id != full.id)
    mixed = pieces[:2] + [build_set_item(other.id, 0, other.min_ilvl, rng)]
    got = set_bonus_mods(mixed)
    # full's 2-set bonus present; other has only 1 piece so no bonus from it
    assert all(m in got for m in full.bonuses[2])
    assert set_bonus_mods([mixed[2]]) == []
    print("bonus thresholds OK")


def test_active_summary():
    full = [sd for sd in SETS if len(sd.pieces) >= 4][0]
    rng = random.Random(3)
    pieces = [build_set_item(full.id, i, full.min_ilvl, rng) for i in range(4)]
    summ = active_set_summary(pieces[:3])
    assert (full.name, 3, len(full.pieces)) in summ
    # nothing equipped -> empty
    assert active_set_summary([]) == []
    print("active_set_summary OK")


def test_roll_determinism():
    """Same seed -> identical set piece choices; None below lowest min_ilvl."""
    lo = min(sd.min_ilvl for sd in SETS)
    a = [roll_set_item(50, random.Random(555)) for _ in range(1)]
    b = [roll_set_item(50, random.Random(555)) for _ in range(1)]
    ra, rb = a[0], b[0]
    assert ra is not None and rb is not None
    assert (ra.base_id, ra.slot, ra.rarity) == (rb.base_id, rb.slot, rb.rarity)
    assert set_id_of(ra) is not None
    # below the lowest set's min_ilvl -> None
    assert roll_set_item(lo - 1, random.Random(9)) is None
    print("roll determinism + gating OK")


if __name__ == "__main__":
    test_set_defs_valid()
    test_build_and_recover()
    test_set_id_of_non_set()
    test_bonus_thresholds()
    test_active_summary()
    test_roll_determinism()
    print("test_sets: ALL OK")
