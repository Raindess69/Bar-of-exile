"""Balance Pass Stage 6.1 regression tests: XP curve + offline rework.

Covers game/progression.py (new xp_to_level, zone_xp_mult, single-source
grant_xp) and game/save.py (tiered offline_progress, no level cap, RAW xp,
magic+ items). Invariants only — no absolute hours-to-100 or calibration-
dependent level numbers. Runnable directly:

    "/e/Python 3.11/python" tests/test_balance_stage6.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import classes, progression as prog, save
from game.core import CombatEvent, Hero, Rarity, Stats


# --- 1. XP curve shape ------------------------------------------------------
def test_xp_curve_shape():
    assert prog.xp_to_level(1) == 0, prog.xp_to_level(1)
    assert prog.xp_to_level(0) == 0  # guards level <= 1

    # strictly increasing across the whole range
    prev = -1
    for lv in range(1, prog.MAX_LEVEL + 1):
        cur = prog.xp_to_level(lv)
        assert cur > prev, f"not strictly increasing at {lv}: {cur} <= {prev}"
        prev = cur

    # geometric tail: late brackets grow FAR faster than early ones
    late = prog.xp_to_level(90) - prog.xp_to_level(89)
    early = prog.xp_to_level(10) - prog.xp_to_level(9)
    ratio = late / early
    assert ratio > 1000, f"tail not steep enough: {ratio}"

    # steeper than the old polynomial 20*(L-1)**2.4, growing toward the tail.
    # Thresholds recalibrated for XP_A=4.55 (20.07 XP calibration dropped it from
    # 60.0, flattening the absolute multiples; the tail-ratio guard above still
    # enforces the geometric shape). x99 must stay well above x50.
    def old(L):
        return 20 * (L - 1) ** 2.4

    x50 = prog.xp_to_level(50) / old(50)
    x99 = prog.xp_to_level(99) / old(99)
    assert x50 >= 5, f"L50 not >= 5x old: {x50}"
    assert x99 >= 50, f"L99 not >= 50x old: {x99}"
    assert x99 > x50 * 5, f"tail must outpace mid: x99={x99} x50={x50}"
    print(f"xp curve shape OK (tail ratio={ratio:.0f}, 50x={x50:.1f}, 99x={x99:.1f})")


# --- 2. zone_xp_mult anti-cheese -------------------------------------------
def test_zone_xp_mult():
    # no penalty fighting up / on-level / within the +5 grace band
    for hl, ml in [(1, 1), (5, 10), (10, 10), (15, 10), (12, 10)]:
        assert prog.zone_xp_mult(hl, ml) == 1.0, (hl, ml, prog.zone_xp_mult(hl, ml))

    # decays once the hero outlevels the zone past the +5 grace
    ml = 10
    assert prog.zone_xp_mult(16, ml) < 1.0  # over = 1
    assert prog.zone_xp_mult(16, ml) == 1.0 - 0.08

    # monotonically non-increasing as hero_level rises
    last = 2.0
    for hl in range(1, 120):
        v = prog.zone_xp_mult(hl, ml)
        assert v <= last + 1e-12, f"not monotone at hl={hl}: {v} > {last}"
        last = v

    # floors at 0.02 and never dips below (deep floor = mandatory-loop wall)
    for hl in range(50, 200):
        v = prog.zone_xp_mult(hl, ml)
        assert v >= 0.02 - 1e-12, (hl, v)
    assert prog.zone_xp_mult(1000, 1) == 0.02
    print("zone_xp_mult anti-cheese OK")


# --- 3. Offline tiered efficiency ------------------------------------------
def test_offline_effective_seconds():
    H = 3600.0
    # fully inside tier 1 (0.60)
    eff3 = save._offline_effective_seconds(3 * H)
    assert abs(eff3 - 3 * H * 0.60) < 1.0, eff3

    # spanning tiers 1+2 at 24h: 8h*0.60 + 16h*0.35
    eff24 = save._offline_effective_seconds(24 * H)
    expect24 = 8 * H * 0.60 + 16 * H * 0.35
    assert abs(eff24 - expect24) < 1.0, (eff24, expect24)

    # beyond 72h caps: no reward past the last boundary
    cap = 8 * H * 0.60 + 16 * H * 0.35 + 48 * H * 0.15
    for hrs in (72, 100, 500):
        eff = save._offline_effective_seconds(hrs * H)
        assert abs(eff - cap) < 1.0, (hrs, eff, cap)

    # zero / negative elapsed -> zero effective
    assert save._offline_effective_seconds(0.0) == 0.0
    assert save._offline_effective_seconds(-100.0) == 0.0

    # gate 6.1: 24h offline effective / 24h online in [0.40, 0.55]
    ratio = eff24 / (24 * H)
    assert 0.40 <= ratio <= 0.55, ratio
    print(f"offline tiered efficiency OK (24h ratio={ratio:.3f})")


# --- 4. Offline: no level cap ----------------------------------------------
def test_offline_no_level_cap():
    hero = classes.make_hero("warrior")
    hero.level = 3
    hero.xp = prog.xp_to_level(3)
    hero.recalc()

    # generous snapshot + long elapsed -> big raw xp payout
    snap = {"xp_per_sec": 5000.0, "gold_per_sec": 1.0, "kills_per_sec": 0.1}
    saved_at = _fixed_now() - 48 * 3600
    off = save.offline_progress(saved_at, hero, zone_id="a1_caves",
                                rng=random.Random(7), rate_snapshot=snap)

    # feed the RAW xp through grant_xp (as the game does) and count real levels
    lvl_before = hero.level
    ev: list[CombatEvent] = []
    prog.grant_xp(hero, off["xp"], ev)
    gained = hero.level - lvl_before
    assert gained > 3, f"old +3 cap appears to still apply: gained={gained}"
    # display estimate should match what grant_xp actually awarded
    assert off["levels_gained"] == gained, (off["levels_gained"], gained)
    print(f"offline no level cap OK (levels_gained={gained})")


# --- 5. M1 single-source xp_gain_inc ---------------------------------------
def test_m1_single_source_xp_gain_inc():
    # Two identical boosted heroes, SAME raw xp -> identical end state
    def boosted():
        h = classes.make_hero("archer")
        h.base_stats.xp_gain_inc = 200.0
        h.level = 5
        h.xp = prog.xp_to_level(5)
        h.recalc()
        assert h.stats.xp_gain_inc == 200.0
        return h

    ha, hb = boosted(), boosted()
    raw = 100000
    prog.grant_xp(ha, raw, [])
    prog.grant_xp(hb, raw, [])
    assert ha.level == hb.level and ha.xp == hb.xp, \
        (ha.level, ha.xp, hb.level, hb.xp)

    # offline_progress returns RAW xp: a hero WITH xp_gain_inc and one WITHOUT
    # get the SAME "xp" field for the same snapshot (multiply happens in grant_xp)
    snap = {"xp_per_sec": 12.0, "gold_per_sec": 3.0, "kills_per_sec": 0.3}
    saved_at = _fixed_now() - 6 * 3600

    plain = classes.make_hero("archer")
    plain.level = 5
    plain.recalc()
    assert plain.stats.xp_gain_inc == 0.0

    boost = classes.make_hero("archer")
    boost.base_stats.xp_gain_inc = 200.0
    boost.level = 5
    boost.recalc()

    off_plain = save.offline_progress(saved_at, plain, zone_id="a1_caves",
                                      rng=random.Random(11), rate_snapshot=snap)
    off_boost = save.offline_progress(saved_at, boost, zone_id="a1_caves",
                                      rng=random.Random(11), rate_snapshot=snap)
    assert off_plain["xp"] == off_boost["xp"], \
        f"offline xp is pre-multiplied: {off_plain['xp']} != {off_boost['xp']}"
    assert off_plain["xp"] > 0

    # sanity: the boosted hero's levels_gained estimate should be >= plain's
    assert off_boost["levels_gained"] >= off_plain["levels_gained"]
    print("M1 single-source xp_gain_inc OK")


# --- 6. Offline items -------------------------------------------------------
def test_offline_items():
    hero = classes.make_hero("mage")
    hero.level = 12
    hero.recalc()
    # high kills_per_sec -> many rolls, so the cap/rarity/sort filters are exercised
    snap = {"xp_per_sec": 8.0, "gold_per_sec": 5.0, "kills_per_sec": 50.0}
    saved_at = _fixed_now() - 24 * 3600
    off = save.offline_progress(saved_at, hero, zone_id="a1_caves",
                                rng=random.Random(3), rate_snapshot=snap)

    items = off["items"]
    assert len(items) <= save.OFFLINE_ITEMS_KEEP, len(items)
    # magic+ only — no NORMAL rarity survives into the kept list
    for it in items:
        assert it.rarity in (Rarity.MAGIC, Rarity.RARE, Rarity.UNIQUE), it.rarity
    # sorted by rarity (best first) then descending ilvl
    keys = [(save._RARITY_ORDER[it.rarity], -it.ilvl) for it in items]
    assert keys == sorted(keys), keys

    # zero elapsed -> empty items, zero xp, zero kills
    off0 = save.offline_progress(_fixed_now(), hero, zone_id="a1_caves",
                                 rng=random.Random(3), rate_snapshot=snap)
    assert off0["items"] == [] and off0["xp"] == 0 and off0["kills"] == 0
    assert off0["gold"] == 0
    print(f"offline items OK (kept={len(items)})")


def _fixed_now():
    # save.offline_progress reads time.time() internally; anchor saved_at to it
    # via a single read so tests stay deterministic within a run.
    import time
    return time.time()


if __name__ == "__main__":
    test_xp_curve_shape()
    test_zone_xp_mult()
    test_offline_effective_seconds()
    test_offline_no_level_cap()
    test_m1_single_source_xp_gain_inc()
    test_offline_items()
    print("test_balance_stage6: ALL OK")
