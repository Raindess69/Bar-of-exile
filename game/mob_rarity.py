"""E.6 — monster rarity tiers (Common / Magic / Rare).

ECONOMY_IDLE_SPEC §E.6. The game already had a single champion flag; this
GENERALISES it into a 3-tier ladder instead of building a parallel system:
the old champion BECOMES the Rare tier (its balance-verified multipliers are
migrated verbatim so the death-wall tuning is untouched), and a gentler Magic
tier is inserted between Common and Rare.

Pure data + rng only — no PyQt, no engine imports beyond the rng. world.py rolls
a tier at spawn and applies the multipliers; loot.py already lifts drop rarity by
`rarity_tier_bonus`; ui/render.py reads OUTLINE_COLOR for the sprite outline.

Balance note: the spec's raw Rare numbers (life ×6, xp ×5) predate the death-wall
pass and are HARSHER than the shipped champion. Per the spec's own directive
("мигрировать его бонусы, не строить вторую систему") the Rare tier keeps the
champion's verified ×2.2 / ×1.4 here; the harsher table is left for a future
sim-backed tuning pass, not applied blind.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

COMMON = "common"
MAGIC = "magic"
RARE = "rare"


@dataclass(frozen=True)
class TierDef:
    tier: str
    spawn_chance: float      # share within a spawn roll (act-gated by caller)
    life_mult: float
    dmg_mult: float
    xp_mult: float           # multiplies the mob's xp_reward
    loot_bonus: float        # ADDED to Monster.loot_bonus (drop-chance rider)
    rarity_tier_bonus: int   # drop rarity floor lift (read by loot._lift_rarity)
    guaranteed_drop: bool    # Rare always yields >=1 item
    outline: str | None      # sprite outline hex, None for Common
    name_prefix: str         # display prefix on the mob name


# Rare == the migrated champion (game.world CHAMPION_* were 2.2 / 1.4 / +1.0 / +1).
# Magic is a new, gentle middle tier. Spawn chances follow the spec table but are
# gated to act >= 2 by world.py (act 1 stays all-Common for the early ramp).
TIERS: dict[str, TierDef] = {
    COMMON: TierDef(COMMON, 0.85, 1.0, 1.0, 1.0, 0.0, 0, False, None, ""),
    MAGIC:  TierDef(MAGIC, 0.12, 1.5, 1.2, 1.5, 0.5, 0, False, "#4a90ff", "Magic "),
    RARE:   TierDef(RARE, 0.03, 2.2, 1.4, 1.9, 1.0, 1, True, "#ffd24a", "Rare "),
}

# Convenience lookups for the renderer / tests.
OUTLINE_COLOR = {t: d.outline for t, d in TIERS.items()}


def roll_tier(rng: random.Random) -> str:
    """Pick a tier for one elevated spawn (caller decides WHETHER to elevate).

    Returns MAGIC or RARE weighted by their relative spawn shares. COMMON is the
    default handled by the caller — this only splits the "not common" outcome so
    callers that already gate on an elite chance get the right magic:rare ratio.
    """
    weights = [TIERS[MAGIC].spawn_chance, TIERS[RARE].spawn_chance]
    return rng.choices([MAGIC, RARE], weights=weights, k=1)[0]


def tier_of(mon) -> str:
    """Read a monster's tier flag (default COMMON for un-elevated / legacy mobs)."""
    return getattr(mon, "rarity_tier", COMMON)
