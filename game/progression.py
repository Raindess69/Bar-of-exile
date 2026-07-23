"""Bar of Exile — XP curve, level-ups, difficulties, zone unlocks."""
from __future__ import annotations

from dataclasses import dataclass

from game.core import CombatEvent, Hero, Stats

MAX_LEVEL = 100  # historical anchor: item ilvl ceiling (cube.MAX_ILVL), the
# "you finished the intended arc" mark, and difficulty math. NOT a hard level
# cap anymore — see LEVEL_CAP.

# Stage 6.6: leveling is uncapped. Post-100 each level still grants +1 passive
# point (tree.points_available scales with level, and the 1002-node tree is sized
# for exactly this). None = no ceiling; the geometric XP tail makes each post-100
# level a long-horizon goal on its own.
LEVEL_CAP: int | None = None

# Stage 6.1: idle/AFK XP curve — polynomial × mild geometric. The polynomial
# keeps early-game dopamine; the geometric tail (XP_G) is what makes level 100
# a ~168h floor and post-100 scaling effectively endless. Calibrate ONLY XP_A
# via tools/sim.py (median class to 100 at 160–180h); XP_E/XP_G define the shape
# and must not be touched to tune pacing.
XP_A = 7.0  # recalibrated 2026-07-21 via tools/sim.py 4-loop sweep (profile P3:
# monster_mult 1.25/1.5/1.8, offsets 10/20/30). KEY FINDING: with the mandatory
# 4-loop campaign, time-to-100 PLATEAUS at ~135-143h across XP_A in [6.5, 9.5] —
# the binding pace constraint is no longer XP but the Nightmare boss wall (the
# lord_of_ash gate opens only once gear can break it), exactly the intended
# gear-gated grindwall. XP_A therefore tunes the EARLY ramp, not the 100-mark:
# 7.0 sits at the low end of the plateau (median-to-100 ~142h clean, higher for
# real players vs greedy auto-equip; L50 ~9h) for a gentle early curve + long
# 70→100 endgame chase. Below ~6 the early game collapses into a walk; above ~9
# it only slows the early ramp without moving 100. Retune ONLY this constant.
XP_E = 2.6
XP_G = 1.05


def xp_to_level(level: int) -> int:
    if level <= 1:
        return 0
    return int(XP_A * (level - 1) ** XP_E * XP_G ** (level - 1))


def zone_xp_mult(hero_level: int, monster_level: int) -> float:
    """Anti-cheese + mandatory-loop wall: farming zones far below your level
    decays XP toward a near-zero floor, so out-levelling the current difficulty's
    effective monster level is a dead end — the way forward is the next loop
    (higher mlvl_offset), which keeps you inside the grace band. No penalty for
    fighting up-level.

    Grace band = monster_level + 5 (full XP). Past it, -8%/level down to a 2%
    floor (was 10%): the deeper floor is what makes reaching 100 on a single
    lower loop effectively impossible, per the 4-loop design."""
    over = max(0, hero_level - monster_level - 5)
    return max(0.02, 1.0 - 0.08 * over)


def grant_xp(hero: Hero, amount: int, events: list[CombatEvent]) -> bool:
    # v3: xp_gain_inc from gear/tree
    s = getattr(hero, "stats", None)
    if s is not None and s.xp_gain_inc:
        amount = int(amount * (1 + s.xp_gain_inc / 100.0))
    # keystone: timeworn "XP gain -10%" (+1 to all skill levels: TODO, skill ranks in 2b.4)
    if "timeworn" in getattr(hero, "flags", set()):
        amount = int(amount * 0.9)
    hero.xp += amount
    leveled = False
    while (LEVEL_CAP is None or hero.level < LEVEL_CAP) \
            and hero.xp >= xp_to_level(hero.level + 1):
        hero.level += 1
        leveled = True
        events.append(CombatEvent("levelup", x=hero.x, text=f"Level {hero.level}!"))
    return leveled


@dataclass
class Difficulty:
    id: str
    name: str
    monster_mult: float
    xp_mult: float
    loot_bonus: float
    unlock_hero_level: int
    # Mandatory-loop model: each difficulty raises the EFFECTIVE monster level of
    # every zone by this offset, so beating the campaign again on a higher tier is
    # the only way to keep out-levelling the XP-decay wall. 0 = Normal (base mlvl).
    mlvl_offset: int = 0


DIFFICULTIES: list[Difficulty] = [
    # Mandatory-loop model (Variant A, "load transfer"): each loop raises the
    # EFFECTIVE monster level (mlvl_offset) as the primary difficulty carrier and
    # keeps monster_mult MODEST — mlvl_offset x monster_mult both hit the same
    # `raw` term, so a large mult collapses the armor curve A/(A+4R) and wipes
    # melee. Calibrated 2026-07-21 via tools/sim.py 4-loop mult sweep (P1..P4):
    # mult 1.0 = walk (100 in ~40h), mult >=1.9 = impassable (nobody reaches 100),
    # 1.25/1.5/1.8 (P3) is the sweet spot — ranged clear all 4 loops to 100 but
    # pay hundreds of boss wipes on the Nightmare finales (gear-gated grindwall,
    # per the design directive). Offsets 10/20/30 anchor on the campaign finale
    # (mlvl 58) to keep hero_level within the XP grace band each loop.
    #            id          name        mon_mult xp_mult loot  unlock  mlvl_off
    Difficulty("normal",    "Normal",     1.0,    1.0,    0.0,    1,     0),
    Difficulty("cruel",     "Cruel",      1.25,   1.6,   20.0,   20,    10),
    Difficulty("merciless", "Merciless",  1.5,    2.5,   50.0,   40,    20),
    Difficulty("nightmare", "Nightmare",  1.8,    4.0,  100.0,   60,    30),
]


def available_difficulties(hero_level: int) -> list[Difficulty]:
    return [d for d in DIFFICULTIES if hero_level >= d.unlock_hero_level]


# Difficulty gate boss: killing Lord of Ash (world.py: a3_ashen_sanctum, the
# Act 3 finale) unlocks the next difficulty. Act 4 zones are optional endgame
# past this gate and deliberately do NOT change it. boss_first_kills keys are
# "monster_id@difficulty_id". Kept here so game/* stays import-light.
FINAL_ACT_BOSS_ID = "lord_of_ash"
FINAL_ACT_BOSS_NAME = "Lord of Ash"

_DIFF_BY_ID = {d.id: d for d in DIFFICULTIES}


def difficulty_unlocked(diff_id: str, boss_first_kills: list[str],
                        hero_level: int) -> bool:
    """Normal is always unlocked; each next difficulty needs the final act boss
    killed on the previous difficulty AND the level requirement."""
    diff = _DIFF_BY_ID.get(diff_id)
    if diff is None:
        return False
    if hero_level < diff.unlock_hero_level:
        return False
    idx = DIFFICULTIES.index(diff)
    if idx == 0:
        return True
    prev = DIFFICULTIES[idx - 1]
    return f"{FINAL_ACT_BOSS_ID}@{prev.id}" in boss_first_kills


def unlock_hint(diff_id: str) -> str:
    """'Defeat <Boss> on <Difficulty>' for locked tiers, '' for Normal/unknown."""
    diff = _DIFF_BY_ID.get(diff_id)
    if diff is None or diff is DIFFICULTIES[0]:
        return ""
    prev = DIFFICULTIES[DIFFICULTIES.index(diff) - 1]
    return f"Defeat {FINAL_ACT_BOSS_NAME} on {prev.name}"


def zone_unlocked(hero_level: int, zone_monster_level: int) -> bool:
    return hero_level >= zone_monster_level - 2


def xp_progress(hero: Hero) -> tuple[int, int, float]:
    # Stage 6.6: leveling is uncapped, so there's always a next level to fill —
    # only a hard LEVEL_CAP (normally None) shows a full/"maxed" bar.
    if LEVEL_CAP is not None and hero.level >= LEVEL_CAP:
        return 0, 0, 1.0
    cur = xp_to_level(hero.level)
    need = xp_to_level(hero.level + 1) - cur
    into = max(0, hero.xp - cur)
    frac = min(1.0, into / need) if need > 0 else 1.0
    return into, need, frac


if __name__ == "__main__":
    print("Level | total XP | to next")
    for lv in range(1, 21):
        print(f"{lv:>5} | {xp_to_level(lv):>8} | {xp_to_level(lv + 1) - xp_to_level(lv):>6}")

    hero = Hero(name="Test", stats=Stats())
    hero.init_hp()
    events: list[CombatEvent] = []
    kills = 0
    while hero.level < 10:
        grant_xp(hero, 8, events)
        kills += 1
    into, need, frac = xp_progress(hero)
    print(f"\nKills at 8 XP each to reach level 10: {kills}, xp={hero.xp}")
    print(f"Progress: {into}/{need} ({frac:.0%})")
    print("Level-ups:", [e.text for e in events])
    assert len(events) == 9 and events[-1].text == "Level 10!"

    for lv in (1, 20, 40, 60):
        names = ", ".join(d.name for d in available_difficulties(lv))
        print(f"Level {lv}: {names}")

    assert zone_unlocked(1, 3) and not zone_unlocked(1, 4)
    # Stage 6.6: leveling is uncapped — a level-100 hero still has a next level to
    # fill (non-zero need), NOT a maxed bar.
    into100, need100, frac100 = xp_progress(Hero(name="Cap", stats=Stats(), level=MAX_LEVEL))
    assert need100 > 0 and frac100 < 1.0, (into100, need100, frac100)
    # grant_xp can push a hero past 100 (no hard cap)
    over = Hero(name="Over", stats=Stats(), level=100)
    over.xp = xp_to_level(100)
    grant_xp(over, xp_to_level(103) - xp_to_level(100), [])
    assert over.level >= 102, over.level

    # difficulty gating: boss kill on previous difficulty + level requirement
    assert difficulty_unlocked("normal", [], 1)
    assert not difficulty_unlocked("cruel", [], 99)
    assert not difficulty_unlocked("cruel", ["lord_of_ash@normal"], 19)
    assert difficulty_unlocked("cruel", ["lord_of_ash@normal"], 20)
    assert not difficulty_unlocked("merciless", ["lord_of_ash@normal"], 99)
    assert difficulty_unlocked("merciless",
                               ["lord_of_ash@normal", "lord_of_ash@cruel"], 40)
    assert difficulty_unlocked(
        "nightmare",
        ["lord_of_ash@normal", "lord_of_ash@cruel", "lord_of_ash@merciless"], 60)
    assert not difficulty_unlocked("bogus", [], 99)
    assert unlock_hint("cruel") == "Defeat Lord of Ash on Normal"
    assert unlock_hint("nightmare") == "Defeat Lord of Ash on Merciless"
    assert unlock_hint("normal") == ""
    print("difficulty gate OK")
    print("progression OK")
