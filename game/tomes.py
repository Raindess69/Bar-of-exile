"""Bar of Exile — Skill Tomes (S.5, Gem Souls layer).

A Skill Tome is a rare mob drop (§2/§3 of SKILLS_MECHANICS_V2.md): base 1/220
per mob, act-scaled, pity-safe. Reading one unlocks a random still-locked class
skill up to +10 levels above the hero; if nothing is left to unlock it converts
to skill XP (500 × act) poured into an equipped skill instead.

Scope here is LOGIC ONLY — the tome is NOT an Item and is never put in the
inventory. Dropping a tome in-game is just an event/counter; the main session
decides how to surface it (a "Skill Tome!" flash) and where to hook the roll.

State lives in `hero.skills_v2` (already saved at save v5). This module touches
ONLY these keys: `unlocked` (list[str]), `sxp` (dict), `tomes_read` (int).
All randomness flows through a passed random.Random — no global random.
"""
from __future__ import annotations

import math
import random

from game.core import Hero
# Same layer; reuse skill data + equipped-loadout lookup, never duplicate them.
from game.skills_v2 import _equipped_ids, load_skills_v2

# base drop chance per mob. Tomes are a rare, pleasant "new skill!" moment — NOT
# a steady stream. Lowered from the original 1/220 (felt spammy in play) so a
# tome lands roughly every ~30-60 min of active play in early acts.
TOME_BASE_RATE = 1 / 600

# how far above the hero's level a tome can reach when unlocking (§2)
TOME_UNLOCK_OVERSHOOT = 10

# skill XP granted by a duplicate (nothing left to unlock) tome, per act (§2)
TOME_DUP_SXP_PER_ACT = 500

# pity is a SAFETY NET, not a steady accelerator. It stays OFF (pure base rate)
# until a dry streak passes PITY_START_MULT × the mean interval, then ramps to a
# hard guarantee at PITY_MULT × the mean interval. This kills the old behaviour
# where the ramp started at zero and pushed the effective rate way above base.
PITY_START_MULT = 3   # dry streak below this × mean interval = pure base rate
PITY_MULT = 5         # dry streak at this × mean interval = guaranteed drop


def _act_rate(act: int) -> float:
    """Per-mob drop chance scaled by act (act 1 = base, higher acts drop more)."""
    return TOME_BASE_RATE * max(1, int(act))


def roll_tome_drop(hero: Hero, act: int, rng: random.Random, pity: int = 0) -> bool:
    """True if this mob drops a Skill Tome.

    Chance = act-scaled base rate for the first PITY_START_MULT× mean interval
    (no inflation), then a soft-pity ramp toward a hard guarantee at PITY_MULT×.
    Deterministic for a given rng state.
    """
    rate = _act_rate(act)
    mean = 1.0 / rate
    pity_start = PITY_START_MULT * mean
    pity_cap = math.ceil(PITY_MULT * mean)
    if pity >= pity_cap:
        return True
    if pity <= pity_start:
        return rng.random() < rate  # pure base rate, no pity inflation yet
    # soft pity only in the tail: ramp base_rate -> 1.0 across [start, cap]
    frac = (pity - pity_start) / (pity_cap - pity_start)
    chance = rate + (1.0 - rate) * frac
    return rng.random() < chance


def readable_tome_targets(hero: Hero) -> list[str]:
    """Ids of the hero's class skills a tome could still unlock — locked and with
       `unlock_level <= hero.level + 10`, in unlock (json) order."""
    sv = getattr(hero, "skills_v2", None) or {}
    unlocked = set(sv.get("unlocked", []))
    cap = hero.level + TOME_UNLOCK_OVERSHOOT
    return [s.id for s in load_skills_v2().values()
            if s.class_id == hero.class_id
            and s.unlock_level <= cap
            and s.id not in unlocked]


def read_tome(hero: Hero, act: int, rng: random.Random) -> dict:
    """Consume one tome. Unlock a random reachable locked skill, or — if there is
       nothing left to unlock — convert to skill XP (500 × act) on an equipped
       skill. Increments `tomes_read` either way. Returns a result descriptor."""
    sv = hero.skills_v2
    # L6: a hand-edited / corrupt save could carry a negative or non-int
    # tomes_read; floor at 0 so the lifetime counter can never persist below zero.
    try:
        prior = max(0, int(sv.get("tomes_read", 0)))
    except (TypeError, ValueError):
        prior = 0
    sv["tomes_read"] = prior + 1

    targets = readable_tome_targets(hero)
    if targets:
        sid = rng.choice(targets)
        sv.setdefault("unlocked", []).append(sid)
        skill = load_skills_v2()[sid]
        return {"kind": "unlock", "skill_id": sid, "name": skill.name}

    # duplicate-safe: pour skill XP into a random equipped skill (§2)
    amount = TOME_DUP_SXP_PER_ACT * max(1, int(act))
    sxp = sv.setdefault("sxp", {})
    equipped = _equipped_ids(sv)
    if not equipped:
        equipped = list(sv.get("unlocked", []))
    sid = rng.choice(equipped) if equipped else None
    if sid is not None:
        sxp[sid] = sxp.get(sid, 0) + amount
    return {"kind": "sxp", "amount": amount, "skill_id": sid}


# --------------------------------------------------------------------------- #
# smoke test: python game/tomes.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    from game import classes

    rng = random.Random(1)
    hero = classes.make_hero("warrior")
    hero.level = 1
    classes.apply_level_growth(hero)
    from game.skills_v2 import ensure_skills_v2
    ensure_skills_v2(hero)
    print("targets @ lvl1:", readable_tome_targets(hero))
    print("guaranteed by pity:", roll_tome_drop(hero, 1, rng, pity=10 ** 6))
    print("read:", read_tome(hero, 2, rng))
    print("tomes.py smoke OK")
