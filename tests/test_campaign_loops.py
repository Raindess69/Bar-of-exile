"""4-loop campaign regression tests: mandatory Normal→Cruel→Merciless→Nightmare
replay with per-difficulty mlvl_offset, campaign-zone auto-advance chain, and the
difficulty gate.

Invariants only — no absolute hours-to-100 or XP_A-dependent numbers. Covers the
design contract behind Variant 1 (100 unreachable on a single loop) + Variant A
(load transfer: offset carries difficulty, monster_mult lowered so melee doesn't
death-wall). The rule under test throughout: mlvl_offset feeds combat scaling and
zone_xp_mult's effective level ONLY — never the zone/difficulty gate checks.

Runnable directly:  python tests/test_campaign_loops.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import progression as prog, world


# --- 1. Difficulty table shape ---------------------------------------------
def test_four_loops_defined():
    ids = [d.id for d in prog.DIFFICULTIES]
    assert ids == ["normal", "cruel", "merciless", "nightmare"], ids

    # mlvl_offset is monotonically increasing and starts at 0 on Normal
    offs = [d.mlvl_offset for d in prog.DIFFICULTIES]
    assert offs[0] == 0, offs
    assert offs == sorted(offs) and len(set(offs)) == len(offs), offs

    # xp_mult and loot rise with difficulty; unlock level gates climb too
    assert [d.xp_mult for d in prog.DIFFICULTIES] == \
        sorted(d.xp_mult for d in prog.DIFFICULTIES)
    assert [d.unlock_hero_level for d in prog.DIFFICULTIES] == \
        sorted(d.unlock_hero_level for d in prog.DIFFICULTIES)
    print("four loops defined OK")


def test_variant_a_load_transfer():
    """Variant A: difficulty is carried by mlvl_offset, and monster_mult is kept
    modest so the two don't stack into a melee death-wall. This is a COARSE
    structural guard — real survivability is validated by tools/sim.py, not here.
    We assert two things about the campaign finale (mlvl 58):

      1. the offset-only per-hit climb (holding monster_mult fixed) is a
         controlled ramp per loop, not a runaway — this is the Variant A lever;
      2. monster_mult itself stays modest (no loop multiplies raw by a huge
         constant on top of the offset), so the combined finale hit vs Normal
         lands far below the naive ~90x stack that would wipe melee."""
    base = 58  # Act-3 finale monster level (lord_of_ash zone); m = level-1
    normal = prog.DIFFICULTIES[0]
    ref_offset = world.mob_dmg_mult(base - 1)
    ref_combined = ref_offset * normal.monster_mult
    for d in prog.DIFFICULTIES[1:]:
        # (1) offset-only ramp: each loop's finale mob hits harder purely from the
        # higher effective level, but the ramp stays single-digit across all loops.
        offset_ratio = world.mob_dmg_mult(base + d.mlvl_offset - 1) / ref_offset
        assert 1.0 < offset_ratio < 5.0, (d.id, round(offset_ratio, 2))
        # (2) monster_mult stays modest — offset is the carrier, not a big raw mult.
        assert d.monster_mult <= 5.0, (d.id, d.monster_mult)
        # combined finale hit vs Normal: well below the naive ~90x blowup.
        combined = world.mob_dmg_mult(base + d.mlvl_offset - 1) * d.monster_mult
        assert combined / ref_combined < 20.0, (d.id, round(combined / ref_combined, 1))
    print("variant A load transfer OK")


# --- 2. Campaign-zone chain -------------------------------------------------
def test_campaign_zones_are_acts_1_to_3():
    for z in world.CAMPAIGN_ZONES:
        assert z.act <= 3, (z.id, z.act)
    # sorted by (act, monster_level); first is the lowest-level act-1 zone
    lvls = [(z.act, z.monster_level) for z in world.CAMPAIGN_ZONES]
    assert lvls == sorted(lvls), lvls
    assert world.first_campaign_zone() is world.CAMPAIGN_ZONES[0]
    print("campaign zones = acts 1-3 OK")


def test_next_campaign_zone_walks_then_stops():
    z = world.first_campaign_zone()
    seen = [z.id]
    while True:
        nxt = world.next_campaign_zone(z)
        if nxt is None:
            break
        seen.append(nxt.id)
        z = nxt
    # walked every campaign zone exactly once, in order, terminating at the finale
    assert len(seen) == len(world.CAMPAIGN_ZONES), (len(seen),
                                                    len(world.CAMPAIGN_ZONES))
    assert seen == [zz.id for zz in world.CAMPAIGN_ZONES], seen
    assert z is world.CAMPAIGN_ZONES[-1]
    # the finale zone hosts the FINAL_ACT_BOSS
    assert z.boss_template_id == prog.FINAL_ACT_BOSS_ID, z.boss_template_id
    print("next_campaign_zone walk+stop OK")


def test_act4_and_rifts_excluded_from_chain():
    campaign_ids = {z.id for z in world.CAMPAIGN_ZONES}
    act4 = [z for z in world.ZONES if z.act >= 4]
    assert act4, "expected Act 4 zones to exist"
    for z in act4:
        assert z.id not in campaign_ids, z.id
        assert world.next_campaign_zone(z) is None, z.id  # unknown -> no chain
    print("act4/rifts excluded OK")


# --- 3. Difficulty gate (Variant 1: loops are mandatory) --------------------
def test_difficulty_gate_needs_boss_and_level():
    finale = prog.FINAL_ACT_BOSS_ID
    # Normal always open, no prerequisites
    assert prog.difficulty_unlocked("normal", [], 1)

    # Cruel needs BOTH the level req AND lord_of_ash killed on Normal
    cruel = next(d for d in prog.DIFFICULTIES if d.id == "cruel")
    assert not prog.difficulty_unlocked("cruel", [], cruel.unlock_hero_level)
    assert not prog.difficulty_unlocked(
        "cruel", [f"{finale}@normal"], cruel.unlock_hero_level - 1)  # under-level
    assert prog.difficulty_unlocked(
        "cruel", [f"{finale}@normal"], cruel.unlock_hero_level)

    # Merciless needs the finale killed specifically on Cruel (not Normal)
    merc = next(d for d in prog.DIFFICULTIES if d.id == "merciless")
    assert not prog.difficulty_unlocked(
        "merciless", [f"{finale}@normal"], merc.unlock_hero_level)
    assert prog.difficulty_unlocked(
        "merciless", [f"{finale}@normal", f"{finale}@cruel"], merc.unlock_hero_level)
    print("difficulty gate boss+level OK")


# --- 4. mlvl_offset never leaks into gate checks ---------------------------
def test_offset_not_in_zone_gate():
    """zone_unlocked keys off the RAW zone monster_level, so a high loop can
    always re-enter its own early zones (offset only scales combat + xp decay)."""
    # a level-30 hero on Nightmare (offset +40) must still be able to enter the
    # act-1 opener (raw mlvl 1) — the gate must ignore the offset entirely.
    z0 = world.first_campaign_zone()
    assert prog.zone_unlocked(30, z0.monster_level)
    # gate signature takes only (hero_level, zone_monster_level): no offset param
    import inspect
    params = list(inspect.signature(prog.zone_unlocked).parameters)
    assert params == ["hero_level", "zone_monster_level"], params
    print("offset not in zone gate OK")


# --- 5. Effective-level XP decay wall (Variant 1) --------------------------
def test_low_loop_is_a_dead_end():
    """Farming a low loop past its effective band decays XP toward the 2% floor,
    while the matching higher loop keeps you in the grace band at full XP. This
    asymmetry is what makes the loops the way forward rather than out-levelling."""
    finale_base = 58
    hero = 90  # well past Normal's finale band
    # Normal (offset 0): eff mlvl 58, hero 90 -> deep into decay
    low = prog.zone_xp_mult(hero, finale_base + prog.DIFFICULTIES[0].mlvl_offset)
    # Nightmare (offset +40): eff mlvl 98, hero 90 -> inside grace, full XP
    high = prog.zone_xp_mult(hero, finale_base + prog.DIFFICULTIES[-1].mlvl_offset)
    assert high == 1.0, high
    assert low < 0.5, low            # low loop is heavily taxed
    assert low <= high, (low, high)
    # floor really is the deeper 0.02, not the old 0.10
    assert prog.zone_xp_mult(1000, 1) == 0.02
    print("low loop dead-end OK")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all campaign-loop tests passed")
