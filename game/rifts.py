"""Bar of Exile — Stage 6.6: endless rifts.

Infinite instanced zones unlocked after killing lord_of_ash on a difficulty.
Each tier is a fresh Zone built on the fly from the Act 4 monster pool, scaled
harder and juicier than the one before:

    mlvl          = 62 + 2 * tier          (tier 1..inf)
    kills_to_boss  = 60 + 10 * tier
    zone mods      = forced 3..5, +1 forced mod every 5 tiers
    rewards        = rift-only ilvl 71+ drops, unique pity x1.5, gold x(1+0.06*tier)

Progression: clear the rift boss -> tier+1; die 3x in one rift -> tier-1 (floor 1).
Difficulty gates are untouched — rifts sit past the Act 3 gate as optional endgame.

This module is DATA/LOGIC only: it builds Zone objects and reward params. Wiring
(spawner override for kills_to_boss, UI entry, save of rift_tier) is done by the
caller. Kept import-light: only game.world (Zone/templates) + game.zone_mods.
"""
from __future__ import annotations

import math
import random

from game import world, zone_mods

# Unlock: rifts open once the Act 3 finale boss is dead on any difficulty.
UNLOCK_BOSS_ID = "lord_of_ash"

# Sentinel zone id the waypoint panel emits to request entering the rift (as
# opposed to a real world zone id). main._on_zone_select dispatches on it.
RIFT_ZONE_ID = "__rift__"

RIFT_BASE_MLVL = 62
RIFT_MLVL_PER_TIER = 2
RIFT_BASE_KILLS = 60
RIFT_KILLS_PER_TIER = 10
RIFT_MIN_MODS = 3
RIFT_MAX_MODS = 5
RIFT_FORCED_MOD_EVERY = 5      # +1 forced mod slot every N tiers
RIFT_MIN_ILVL = 71            # rift-only floor: T0 affix tier only rolls here
UNIQUE_PITY_MULT = 1.5
GOLD_PER_TIER = 0.06
DEATHS_TO_DEMOTE = 3

# M4d: entering a rift costs gold, scaled with tier so the endless reward-inflation
# (mlvl->gold, gold_mult, ilvl-floor, unique-pity) is no longer a pure net-positive
# treadmill. Geometric so it eventually outpaces the linear gold_mult, giving high
# tiers a real affordability wall instead of infinite free farm. Tier 1 is a token
# fee; the cost only bites once you push deep. Rounded up to the nearest 100.
RIFT_ENTRY_BASE = 2000
RIFT_ENTRY_GROWTH = 1.12

# Rift monster pool = the full Act 4 roster (hardest templates in the game).
_RIFT_TEMPLATES = [
    "skeleton_warrior", "skeleton_archer", "armored_zombie", "bone_reaver",
    "creeping_shadow", "horned_fiend", "winged_terror", "hell_minotaur",
    "void_wraith", "gloom_bat", "succubus", "ashen_demon",
]
# Rift bosses cycle through the Act 4 bosses so the fight varies by tier.
_RIFT_BOSSES = ["skeleton_chieftain", "abyssal_behemoth", "the_watcher"]


def is_unlocked(boss_first_kills: list[str]) -> bool:
    """Rifts are available once lord_of_ash is dead on ANY difficulty."""
    return any(k.startswith(f"{UNLOCK_BOSS_ID}@") for k in (boss_first_kills or []))


def rift_mlvl(tier: int) -> int:
    return RIFT_BASE_MLVL + RIFT_MLVL_PER_TIER * max(1, tier)


def rift_kills_to_boss(tier: int) -> int:
    return RIFT_BASE_KILLS + RIFT_KILLS_PER_TIER * max(1, tier)


def rift_mod_count(tier: int) -> int:
    """3..5 mods, plus one extra forced slot every RIFT_FORCED_MOD_EVERY tiers,
    capped by how many distinct mods exist in the pool."""
    extra = (max(1, tier) - 1) // RIFT_FORCED_MOD_EVERY
    n = RIFT_MAX_MODS + extra
    n = max(RIFT_MIN_MODS, min(n, len(zone_mods.all_mod_ids())))
    return n


def rift_mods(tier: int, rng: random.Random) -> list[str]:
    """Forced zone mods for a rift tier (always active, unlike overworld rolls)."""
    n = rift_mod_count(tier)
    ids = zone_mods.all_mod_ids()
    return rng.sample(ids, min(n, len(ids)))


def gold_mult(tier: int) -> float:
    return 1.0 + GOLD_PER_TIER * max(1, tier)


def rift_entry_cost(tier: int) -> int:
    """Gold price to enter a rift at `tier`. Geometric in tier, rounded up to the
    nearest 100 so deep dives eventually outpace the linear gold reward and stop
    being a free treadmill. Tier 1 == RIFT_ENTRY_BASE."""
    raw = RIFT_ENTRY_BASE * (RIFT_ENTRY_GROWTH ** (max(1, tier) - 1))
    return int(math.ceil(raw / 100.0)) * 100


def can_afford_rift(tier: int, gold: int) -> bool:
    return gold >= rift_entry_cost(tier)


def rift_boss_id(tier: int) -> str:
    return _RIFT_BOSSES[(max(1, tier) - 1) % len(_RIFT_BOSSES)]


def make_rift_zone(tier: int) -> world.Zone:
    """Build a fresh Zone for a rift tier. act=4 so kills_to_boss/champion/mob
    scaling all use the hardest-act code paths; the caller overrides the spawner's
    kills_to_boss with rift_kills_to_boss(tier)."""
    tier = max(1, tier)
    mlvl = rift_mlvl(tier)
    # Keep only templates that actually exist in the world registry (defensive).
    templates = [t for t in _RIFT_TEMPLATES if t in world.TEMPLATES] or \
        list(world.ZONES[-1].templates)
    boss = rift_boss_id(tier)
    if boss not in world.TEMPLATES:
        boss = world.ZONES[-1].boss_template_id
    return world.Zone(
        id=f"rift_t{tier}",
        name=f"Rift — Tier {tier}",
        act=4,
        monster_level=mlvl,
        templates=templates,
        pack_size=(3, 5),
        spawn_interval=5.0,
        boss_template_id=boss,
        bg_theme="temple",
        flavor=f"A tear in the Abyss. Tier {tier}: it deepens each time you close one.",
    )


class RiftState:
    """Tracks the player's rift run: current tier, deaths this rift, save I/O.
    Advancement/demotion is decided by the caller on boss-kill / death events."""

    def __init__(self, tier: int = 1, deaths: int = 0):
        self.tier = max(1, tier)
        self.deaths = max(0, deaths)

    def on_boss_kill(self) -> int:
        """Clear -> next tier, deaths reset. Returns the new tier."""
        self.tier += 1
        self.deaths = 0
        return self.tier

    def on_death(self) -> int:
        """3 deaths in one rift -> drop a tier (floor 1), deaths reset. Returns tier."""
        self.deaths += 1
        if self.deaths >= DEATHS_TO_DEMOTE:
            self.tier = max(1, self.tier - 1)
            self.deaths = 0
        return self.tier

    def to_dict(self) -> dict:
        return {"tier": self.tier, "deaths": self.deaths}

    @classmethod
    def from_dict(cls, d: dict | None) -> "RiftState":
        d = d or {}
        return cls(tier=int(d.get("tier", 1)), deaths=int(d.get("deaths", 0)))


if __name__ == "__main__":
    rng = random.Random(7)

    # scaling monotonic + matches the doc formulas
    assert rift_mlvl(1) == 64 and rift_mlvl(5) == 72, rift_mlvl(5)
    assert rift_kills_to_boss(1) == 70 and rift_kills_to_boss(10) == 160
    for t in range(1, 20):
        assert rift_mlvl(t + 1) > rift_mlvl(t)
        assert rift_kills_to_boss(t + 1) > rift_kills_to_boss(t)

    # mod count: 5 base, +1 every 5 tiers, capped by pool size
    assert rift_mod_count(1) == 5, rift_mod_count(1)
    assert rift_mod_count(6) == 6, rift_mod_count(6)
    assert rift_mod_count(100) <= len(zone_mods.all_mod_ids())
    mods = rift_mods(3, rng)
    assert len(mods) == len(set(mods)) == rift_mod_count(3)

    # gold scales with tier
    assert abs(gold_mult(1) - 1.06) < 1e-9 and abs(gold_mult(10) - 1.60) < 1e-9

    # M4d entry cost: tier 1 == base, strictly monotonic, rounds up to 100,
    # geometric so it eventually dwarfs the linear gold_mult reward.
    assert rift_entry_cost(1) == RIFT_ENTRY_BASE, rift_entry_cost(1)
    for t in range(1, 60):
        assert rift_entry_cost(t + 1) > rift_entry_cost(t)
        assert rift_entry_cost(t) % 100 == 0
    assert can_afford_rift(1, RIFT_ENTRY_BASE) and not can_afford_rift(1, RIFT_ENTRY_BASE - 1)
    assert rift_entry_cost(50) > gold_mult(50) * 10000  # cost outgrows linear reward

    # zone build is valid + uses act-4 hard paths
    z = make_rift_zone(4)
    assert z.act == 4 and z.monster_level == rift_mlvl(4)
    assert z.boss_template_id in world.TEMPLATES
    assert all(t in world.TEMPLATES for t in z.templates)
    assert world.kills_to_boss  # sanity: world exposes the fn the caller overrides

    # unlock gate
    assert not is_unlocked([])
    assert is_unlocked(["lord_of_ash@normal"])
    assert is_unlocked(["lord_of_ash@cruel", "skeleton_chieftain@normal"])

    # progression: clear advances, 3 deaths demote (floor 1), save round-trips
    st = RiftState(tier=3)
    assert st.on_boss_kill() == 4 and st.deaths == 0
    assert st.on_death() == 4 and st.on_death() == 4
    assert st.on_death() == 3 and st.deaths == 0  # 3rd death demotes
    floor = RiftState(tier=1)
    for _ in range(3):
        floor.on_death()
    assert floor.tier == 1  # never below 1
    rt = RiftState.from_dict(RiftState(tier=7, deaths=2).to_dict())
    assert rt.tier == 7 and rt.deaths == 2

    print("rifts OK")
