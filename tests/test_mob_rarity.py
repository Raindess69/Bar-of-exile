"""E.6 — monster rarity tiers (Common/Magic/Rare). ECONOMY_IDLE_SPEC §E.6.

Locks the 3-tier ladder that generalises the old champion flag: tier roll ratio,
stat/xp/loot multipliers, Rare guaranteed drop + rarity floor, and the migration
invariant (Rare == old champion numbers, no double-stacking).
"""
import random
from collections import Counter

from game import mob_rarity, world
from game.core import Monster, Rarity, Stats
from game.loot import roll_drop


def _mob(life=100.0, dmin=10.0, dmax=20.0, xp=50, level=30):
    m = Monster(name="Orc", stats=Stats(life=life, damage_min=dmin, damage_max=dmax),
                monster_id="orc", level=level, xp_reward=xp)
    m.rarity_tier = mob_rarity.COMMON
    m.rarity_tier_bonus = 0
    m.loot_bonus = 0.0
    m.init_hp()
    return m


# ---------------------------------------------------------------- tier roll ratio

def test_roll_tier_ratio_seeded():
    rng = random.Random(1337)
    c = Counter(mob_rarity.roll_tier(rng) for _ in range(20_000))
    # magic:rare spawn shares are 0.12:0.03 => ~4:1
    ratio = c[mob_rarity.MAGIC] / c[mob_rarity.RARE]
    assert 3.3 < ratio < 4.8, f"magic:rare ratio {ratio:.2f} off (want ~4)"
    assert set(c) == {mob_rarity.MAGIC, mob_rarity.RARE}, "roll_tier must never return COMMON"


# --------------------------------------------------------- multipliers on the mob

def test_apply_tier_multiplies_stats():
    for tier in (mob_rarity.MAGIC, mob_rarity.RARE):
        td = mob_rarity.TIERS[tier]
        m = _mob()
        base_life, base_dmax, base_xp = m.stats.life, m.stats.damage_max, m.xp_reward
        world._apply_mob_tier(m, tier)
        assert abs(m.stats.life - base_life * td.life_mult) < 1e-6
        assert abs(m.stats.damage_max - base_dmax * td.dmg_mult) < 1e-6
        assert m.xp_reward == max(1, int(base_xp * td.xp_mult))
        assert m.loot_bonus == td.loot_bonus
        assert m.rarity_tier_bonus == td.rarity_tier_bonus
        assert m.rarity_tier == tier
        assert m.max_hp == m.stats.life  # init_hp re-ran
        assert m.name.startswith(td.name_prefix.strip())


def test_common_apply_is_noop():
    m = _mob()
    before = (m.stats.life, m.xp_reward, m.loot_bonus, m.name)
    world._apply_mob_tier(m, mob_rarity.COMMON)
    assert (m.stats.life, m.xp_reward, m.loot_bonus, m.name) == before
    assert m.rarity_tier == mob_rarity.COMMON


# --------------------------------------------------- migration: Rare == champion

def test_rare_migrates_champion_numbers_no_double_stack():
    """The legacy _promote_champion must equal applying the RARE tier exactly."""
    a, b = _mob(), _mob()
    world._apply_mob_tier(a, mob_rarity.RARE)
    world._promote_champion(b)
    assert a.stats.life == b.stats.life
    assert a.stats.damage_max == b.stats.damage_max
    assert a.rarity_tier_bonus == b.rarity_tier_bonus == world.CHAMPION_RARITY_TIER
    assert a.is_champion and b.is_champion  # Rare keeps the legacy flag
    # numbers trace back to the CHAMPION_* constants (single source of truth)
    base = _mob()
    assert abs(a.stats.life - base.stats.life * world.CHAMPION_LIFE_MULT) < 1e-6


def test_magic_is_not_champion():
    m = _mob()
    world._apply_mob_tier(m, mob_rarity.MAGIC)
    assert not m.is_champion, "Magic tier must NOT set the legacy champion flag"
    assert m.rarity_tier_bonus == 0, "Magic does not lift drop rarity floor"


# ------------------------------------------------------ Rare guaranteed drop/floor

def test_rare_guarantees_a_drop():
    m = _mob()
    world._apply_mob_tier(m, mob_rarity.RARE)
    assert getattr(m, "guaranteed_drop", False)
    rng = random.Random(7)
    # every single roll must yield an item despite the base 10% chance gate
    assert all(roll_drop(m, m.level, rng) is not None for _ in range(200))


def test_rare_drop_floor_at_least_magic():
    m = _mob()
    world._apply_mob_tier(m, mob_rarity.RARE)
    rng = random.Random(11)
    rarities = [roll_drop(m, m.level, rng).rarity for _ in range(400)]
    assert all(r is not Rarity.NORMAL for r in rarities), \
        "Rare-tier mob (+1 tier bonus) must never drop a plain Common item"


def test_common_mob_drop_unchanged():
    """A Common mob's drop path is byte-identical to pre-E.6 (no guaranteed flag)."""
    m = _mob()
    rng_a = random.Random(3)
    got = sum(roll_drop(m, m.level, rng_a) is not None for _ in range(5000))
    # base DROP_CHANCE 0.10 => ~500/5000; just assert it's gated (not guaranteed)
    assert 350 < got < 650, f"common drop rate drifted: {got}/5000"


# ----------------------------------------------------------- spawn integration

def test_spawner_produces_all_three_tiers_act2():
    """A live Act 2+ spawner eventually yields common, magic AND rare mobs."""
    zone = next(z for z in world.ZONES if z.act >= 2)
    sp = world.Spawner(zone, rng=random.Random(42))
    tiers = Counter()
    monsters = []
    for _ in range(400):
        sp._spawn_pack(monsters, base_x=0.0)
        for m in monsters:
            tiers[mob_rarity.tier_of(m)] += 1
        monsters = [m for m in monsters if not m.is_boss][:0]  # reset pool
    assert tiers[mob_rarity.COMMON] > 0
    assert tiers[mob_rarity.MAGIC] > 0, f"no magic mobs spawned: {dict(tiers)}"
    assert tiers[mob_rarity.RARE] > 0, f"no rare mobs spawned: {dict(tiers)}"
