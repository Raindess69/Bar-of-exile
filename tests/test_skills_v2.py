"""Unit tests for game.skills_v2 (S.1 contract §§1-8).

Run from repo root:  python tests/test_skills_v2.py
(NOT `python -m tests.x` — the environment has a conflicting site-packages `tests`.)
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import classes
from game.core import CombatEvent, DamageType, Monster, Stats
from game import skills_v2 as SV


def _mk_hero(class_id, level=30):
    hero = classes.make_hero(class_id)
    hero.level = level
    classes.apply_level_growth(hero)
    SV.ensure_skills_v2(hero)
    return hero


def _pack(hero, n=6, life=500):
    ms = [Monster(name=f"M{i}", stats=Stats(life=life, res_fire=10, res_cold=10,
                                            res_lightning=10, res_chaos=10),
                  x=hero.x + 20 + i * 20, monster_id="m", level=5, xp_reward=20)
          for i in range(n)]
    for m in ms:
        m.init_hp()
    return ms


# --- 1. data --------------------------------------------------------------- #
def test_data():
    skills = SV.load_skills_v2()
    assert len(skills) == 80, f"expected 80 skills, got {len(skills)}"
    by_class = {}
    for s in skills.values():
        by_class.setdefault(s.class_id, []).append(s)
        assert isinstance(s.damage_type, DamageType)
    assert set(by_class) == {"warrior", "barbarian", "archer", "mage", "cleric"}
    for cid, lst in by_class.items():
        assert len(lst) == 16, f"{cid} has {len(lst)} skills, expected 16"
    talents = SV.load_talents_v2()
    assert "tiers" in talents and "pools" in talents
    print("1. data OK")


# --- 2. sxp / ranks -------------------------------------------------------- #
def test_ranks():
    assert SV.sxp_need(1) == 0
    assert SV.sxp_need(2) == int(math.floor(40 * 2 ** 1.7))
    # monotonic non-decreasing rank as sxp grows
    prev = 0
    for sxp in range(0, 200000, 1000):
        r = SV.rank_from_sxp(sxp)
        assert r >= prev, "rank must not decrease as sxp grows"
        assert 1 <= r <= 20
        prev = r
    assert SV.rank_from_sxp(0) == 1
    assert SV.rank_from_sxp(10 ** 9) == 20, "must cap at 20"
    assert SV.rank_from_sxp(10 ** 9, cap=25) == 25, "awakened cap 25"
    print("2. sxp/ranks OK")


# --- 3. MORE bucket -------------------------------------------------------- #
def test_more_mult():
    hero = _mk_hero("warrior")
    sid = "slash"
    hero.skills_v2["sxp"][sid] = 0
    assert abs(SV.skill_more_mult(hero, sid) - 1.0) < 1e-9, "rank1 -> 1.0"
    # push to rank 6
    while SV.skill_rank(hero, sid) < 6:
        hero.skills_v2["sxp"][sid] += 1000
    assert SV.skill_rank(hero, sid) == 6
    base_mult = SV.skill_more_mult(hero, sid)
    assert abs(base_mult - 1.20) < 1e-9, f"rank6 -> 1.20, got {base_mult}"
    # add an offense talent with more_dmg_pct (off_more = +10% more)
    opts = SV._talent_options(SV.load_skills_v2()[sid])
    idx = next(i for i, (o, _) in enumerate(opts[5]) if o["id"] == "off_more")
    hero.skills_v2["talents"][sid] = {"5": idx}
    with_talent = SV.skill_more_mult(hero, sid)
    assert with_talent > base_mult, "talent more is its own factor"
    # frozen formula: each MORE source is its own factor, Π(1+more/100)
    # rank6 per-rank 20% -> 1.20, talent +10% -> 1.10, product 1.32
    assert abs(with_talent - (1.0 + 0.04 * 5) * 1.10) < 1e-9
    print("3. MORE bucket OK")


# --- 4. damage grows with rank -------------------------------------------- #
def _burst_damage(hero, sid, seed=1):
    """Total damage from casting one skill once against a fresh pack."""
    rng = random.Random(seed)
    ms = _pack(hero, n=4, life=10 ** 9)
    events = []
    sk = SV.load_skills_v2()[sid]
    SV._cast(hero, sk, ms, events, rng)
    return sum(e.value for e in events if e.kind == "damage")


def test_damage_grows_with_rank():
    hero = _mk_hero("mage")
    sid = "fire_bolt"
    hero.skills_v2["sxp"][sid] = 0
    low = _burst_damage(hero, sid)
    while SV.skill_rank(hero, sid) < 15:
        hero.skills_v2["sxp"][sid] += 2000
    high = _burst_damage(hero, sid)
    assert high > low, f"rank15 dmg {high} should exceed rank1 {low}"
    print("4. damage grows with rank OK")


# --- 5. damage never drops with any talent (acceptance §9) ---------------- #
def test_any_talent_not_worse():
    hero = _mk_hero("archer")
    sid = "poison_arrow"  # proj/dot/poison — hits several talent filters
    hero.skills_v2["sxp"][sid] = 20000
    base = _burst_damage(hero, sid)
    opts = SV._talent_options(SV.load_skills_v2()[sid])
    for tier, choices in opts.items():
        for idx in range(len(choices)):
            hero.skills_v2["talents"][sid] = {str(tier): idx}
            dmg = _burst_damage(hero, sid)
            assert dmg >= base - 1e-6, (
                f"talent tier{tier} idx{idx} reduced dps: {dmg} < {base}")
    hero.skills_v2["talents"][sid] = {}
    print("5. any talent not worse OK")


# --- 6. tick casts, deals, sets cd ---------------------------------------- #
def test_tick():
    hero = _mk_hero("warrior")
    for s in SV._equipped_ids(hero.skills_v2):
        hero.skills_v2["sxp"][s] = 3000
    ms = _pack(hero, n=5, life=10 ** 6)
    rng = random.Random(3)
    events = []
    for _ in range(40):
        SV.tick_skills_v2(hero, ms, events, 0.05, rng)
    casts = [e for e in events if e.kind == "skill"]
    dmg = sum(e.value for e in events if e.kind == "damage")
    assert casts, "expected at least one skill cast"
    assert all(e.text for e in casts), "cast events must carry a skill id"
    assert dmg > 0, "expected damage to be dealt"
    assert any(v > 0 for v in hero.skill_cds.values()), "a cooldown should be set"
    print("6. tick casts/deals/cd OK")


# --- 7. skill-xp grant ----------------------------------------------------- #
def test_grant_skill_xp():
    hero = _mk_hero("barbarian")
    sv = hero.skills_v2
    equipped = SV._equipped_ids(sv)
    # ensure at least one unlocked-but-unequipped skill exists
    unequipped = [s for s in sv["unlocked"] if s not in equipped]
    assert unequipped, "expected an unlocked-but-unequipped skill for the test"
    mob_xp = 100
    SV.grant_skill_xp(hero, mob_xp)
    exp_eq = int(math.floor(mob_xp * 0.6))
    exp_un = int(math.floor(mob_xp * 0.6 * 0.25))
    assert sv["sxp"][equipped[0]] == exp_eq, sv["sxp"][equipped[0]]
    assert sv["sxp"][unequipped[0]] == exp_un, sv["sxp"][unequipped[0]]
    # ranks rise with accumulation
    sid = equipped[0]
    r0 = SV.skill_rank(hero, sid)
    for _ in range(500):
        SV.grant_skill_xp(hero, 1000)
    assert SV.skill_rank(hero, sid) > r0, "rank should climb with sxp"
    print("7. grant_skill_xp OK")


# --- 8. default / ensure --------------------------------------------------- #
def test_default_ensure():
    for cid in ("warrior", "barbarian", "archer", "mage", "cleric"):
        d = SV.default_skills_v2(cid, 1)
        cls_first = SV._class_skills(cid)[0].id
        assert d["loadout"]["primary"] == cls_first, cid
        assert SV._REQUIRED_KEYS <= set(d)
    # new hero gets seeded
    hero = classes.make_hero("mage")
    hero.skills_v2 = {}
    SV.ensure_skills_v2(hero)
    assert hero.skills_v2["loadout"]["primary"] == "fire_bolt"
    # idempotent
    snap = dict(hero.skills_v2["loadout"])
    SV.ensure_skills_v2(hero)
    assert dict(hero.skills_v2["loadout"]) == snap, "ensure must be idempotent"
    # level-up opens pool slots and fills them
    hero2 = _mk_hero("warrior", level=1)
    assert SV.slots_open(1) == 1, "one pool slot open at level 1"
    assert SV.loadout_slots_open(1)["slots"] == 1
    # at level 1 only the primary is unlocked, so the open pool slot stays empty
    assert [s for s in hero2.skills_v2["loadout"]["slots"] if s] == []
    hero2.level = 30
    classes.apply_level_growth(hero2)
    SV.ensure_skills_v2(hero2)
    assert SV.slots_open(30) == 2, "second slot open at 25"
    filled = [s for s in hero2.skills_v2["loadout"]["slots"] if s]
    assert len(filled) == 2, "pool fills to 2 after level 25"
    print("8. default/ensure OK")


# --- 8b. legacy loadout migration ----------------------------------------- #
def test_legacy_loadout_migration():
    """An old save's actives[3]+aura+utility+ultimate folds into the pool."""
    hero = _mk_hero("warrior", level=80)
    un = hero.skills_v2["unlocked"]
    skills = SV.load_skills_v2()
    spenders = [s for s in un if skills[s].type == "spender"][:3]
    aura = next(s for s in un if skills[s].type == "aura")
    util = next(s for s in un if skills[s].type == "utility")
    ult = next(s for s in un if skills[s].type == "ultimate")
    hero.skills_v2["loadout"] = {"primary": un[0], "actives": list(spenders),
                                 "aura": aura, "utility": util, "ultimate": ult}
    hero.skills_v2["priority"] = list(spenders)
    SV.ensure_skills_v2(hero)
    lo = hero.skills_v2["loadout"]
    assert "actives" not in lo and "aura" not in lo, "legacy keys removed"
    assert len(lo["slots"]) == SV.slots_open(80) == 4, "trimmed to open pool size"
    # order preserved: actives first, then aura/util/ult in that order
    assert lo["slots"][:3] == spenders, "actives keep their order at the front"
    assert lo["slots"][3] == aura, "aura folds in after actives"
    print("8b. legacy migration OK")


# --- 9. UI helpers: equip / priority / talents (S.6) ----------------------- #
def test_equip_and_slots():
    hero = _mk_hero("warrior", level=30)   # 2 pool slots open (1 + 25)
    sv = hero.skills_v2
    skills = SV.load_skills_v2()
    # any non-primary type lands in the common pool
    spenders = [s.id for s in SV._class_skills("warrior")
                if skills[s.id].type == "spender" and s.id in sv["unlocked"]]
    assert spenders, "warrior should have unlocked spenders by 30"
    assert SV.slot_family_for(spenders[0]) == "slots"
    ok = SV.equip_skill(hero, spenders[0], slot_idx=0)
    assert ok and sv["loadout"]["slots"][0] == spenders[0]
    # an aura shares the SAME pool (rework: no separate aura slot)
    auras = [s.id for s in SV._class_skills("warrior")
             if skills[s.id].type == "aura" and s.id in sv["unlocked"]]
    if auras:
        assert SV.slot_family_for(auras[0]) == "slots"
        assert SV.equip_skill(hero, auras[0], slot_idx=1)
        assert auras[0] in sv["loadout"]["slots"]
    # same skill re-equipped elsewhere is MOVED, not duplicated
    SV.equip_skill(hero, spenders[0], slot_idx=1)
    assert sv["loadout"]["slots"].count(spenders[0]) == 1
    # primary always equippable, goes to primary slot
    prim = SV._class_skills("warrior")[0].id
    assert SV.equip_skill(hero, prim)
    assert sv["loadout"]["primary"] == prim
    # a locked (not-unlocked) skill can't equip
    locked = next(s.id for s in SV._class_skills("warrior")
                  if s.id not in sv["unlocked"])
    assert not SV.can_equip(hero, locked)[0]
    assert not SV.equip_skill(hero, locked)
    print("9. equip/slots OK")


def test_slot_gates_by_level():
    # no pool slot before level 1... trivially always >=1, so test the ladder:
    # a 3rd/4th slot is gated by level 50 / 75.
    assert SV.slots_open(1) == 1
    assert SV.slots_open(24) == 1 and SV.slots_open(25) == 2
    assert SV.slots_open(49) == 2 and SV.slots_open(50) == 3
    assert SV.slots_open(74) == 3 and SV.slots_open(75) == 4
    assert SV.slots_open(100) == 4, "caps at 4 slots"
    # equipping a 3rd skill is refused until the pool grows
    hero = _mk_hero("mage", level=30)   # 2 slots
    sv = hero.skills_v2
    skills = SV.load_skills_v2()
    pool_skills = [s.id for s in SV._class_skills("mage")
                   if skills[s.id].type != "primary" and s.id in sv["unlocked"]]
    assert len(pool_skills) >= 3
    SV.equip_skill(hero, pool_skills[0], slot_idx=0)
    SV.equip_skill(hero, pool_skills[1], slot_idx=1)
    # a 3rd equip with no idx replaces the last slot (pool is full at 2)
    SV.equip_skill(hero, pool_skills[2])
    assert len(sv["loadout"]["slots"]) == 2, "pool stays at 2 open slots"
    assert pool_skills[2] in sv["loadout"]["slots"]
    # grow to level 50 -> 3rd slot opens
    hero.level = 50
    classes.apply_level_growth(hero)
    SV.ensure_skills_v2(hero)
    assert SV.slots_open(50) == 3
    print("10. slot gates OK")


def test_priority_reorder():
    hero = _mk_hero("archer", level=50)   # 3 slots
    sv = hero.skills_v2
    skills = SV.load_skills_v2()
    spenders = [s.id for s in SV._class_skills("archer")
                if skills[s.id].type == "spender" and s.id in sv["unlocked"]][:2]
    SV.equip_skill(hero, spenders[0], slot_idx=0)
    SV.equip_skill(hero, spenders[1], slot_idx=1)
    slots_before = list(sv["loadout"]["slots"])
    assert len(slots_before) >= 2
    top = slots_before[0]
    # move the top one down; it should swap with index 1 in BOTH slots & priority
    assert SV.move_priority(hero, top, +1)
    assert sv["loadout"]["slots"][1] == top
    assert sv["priority"][1] == top
    # can't move past the ends
    assert not SV.move_priority(hero, sv["loadout"]["slots"][0], -1)
    print("11. priority reorder OK")


def test_talent_pick_and_respec():
    hero = _mk_hero("cleric", level=30)
    sid = SV._equipped_ids(hero.skills_v2)[0]
    hero.skills_v2["sxp"][sid] = 0
    # tier 5 locked at rank 1
    assert not SV.can_pick_talent(hero, sid, 5)
    assert not SV.pick_talent(hero, sid, 5, 0)
    # rank up past 5, now pickable
    while SV.skill_rank(hero, sid) < 5:
        hero.skills_v2["sxp"][sid] += 2000
    assert SV.can_pick_talent(hero, sid, 5)
    assert SV.pick_talent(hero, sid, 5, 1)
    assert hero.skills_v2["talents"][sid]["5"] == 1
    tiers = SV.talent_tiers_for(hero, sid)
    t5 = next(t for t in tiers if t["rank"] == 5)
    assert t5["unlocked"] and t5["chosen_idx"] == 1
    # respec: needs gold, clears picks, keeps ranks
    hero.gold = 0
    assert not SV.respec_talents(hero, sid)[0], "no gold -> refused"
    hero.gold = 10 ** 6
    r_before = SV.skill_rank(hero, sid)
    ok, _ = SV.respec_talents(hero, sid)
    assert ok and not hero.skills_v2["talents"][sid]
    assert SV.skill_rank(hero, sid) == r_before, "respec keeps ranks"
    print("12. talent pick/respec OK")


def test_rank_progress():
    hero = _mk_hero("mage", level=30)
    sid = "fire_bolt"
    hero.skills_v2["sxp"][sid] = 0
    rank, into, need = SV.rank_progress(hero, sid)
    assert rank == 1 and into == 0 and need > 0
    # dump enough for max rank -> (cap, 0, 0)
    hero.skills_v2["sxp"][sid] = 10 ** 9
    rank, into, need = SV.rank_progress(hero, sid)
    assert rank == SV.RANK_CAP and into == 0 and need == 0
    print("13. rank progress OK")


if __name__ == "__main__":
    test_data()
    test_ranks()
    test_more_mult()
    test_damage_grows_with_rank()
    test_any_talent_not_worse()
    test_tick()
    test_grant_skill_xp()
    test_default_ensure()
    test_legacy_loadout_migration()
    test_equip_and_slots()
    test_slot_gates_by_level()
    test_priority_reorder()
    test_talent_pick_and_respec()
    test_rank_progress()
    print("\nALL SKILLS_V2 TESTS PASSED")
