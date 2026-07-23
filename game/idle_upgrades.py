"""E.1 — Idle upgrades (permanent gold-bought gold-sink).

Pure logic module, stdlib-only (math). No import of core/save/main so it stays
trivially testable and side-effect free. State is a plain ``dict[str, int]``
(upgrade id -> level) that the parent stores under ``hero.idle_upgrades``.

Spec: docs/ECONOMY_IDLE_SPEC.md §E.1. Cost is geometric, rounded UP to the
nearest 10:  ``cost(lvl) = ceil(base * growth**lvl / 10) * 10``.

INTEGRATION HOOKS (parent session wires these — this module touches nothing else):

* ``xp_gain_bonus_pct``  -> add into the SAME aggregate as ``Stats.xp_gain_inc``
  (game/core.py:83) wherever mob-kill XP is granted online. Fold as
  ``xp_gain_inc + xp_gain_bonus_pct(ups)`` — do NOT add a new raw stat key.
* ``gold_find_bonus_pct`` -> add into the ``Stats.gold_find`` aggregate
  (game/core.py:81). MUST be folded in BOTH the online kill-gold path AND the
  offline path (game/save.py offline_progress / its gold snapshot ~line 312) —
  audit L4 found these diverge; apply in both so offline gold respects it too.
* ``skill_xp_bonus_pct`` -> scale the sxp granted in
  game/skills_v2.grant_skill_xp (line ~842): multiply ``base``/``leech`` by
  ``(1 + skill_xp_bonus_pct(ups)/100)``.
* ``offline_efficiency_mult`` -> multiply the tier factors in
  game/save.py (OFFLINE_TIERS 0.60/0.35/0.15, _offline_effective_seconds) by
  this multiplier (1.0..1.20). Multiplicative, per spec.

All getters accept the raw upgrades dict and never raise on garbage input.
"""
from __future__ import annotations

import math
from typing import Dict, Tuple


# --------------------------------------------------------------------------- #
# upgrade table (single source of truth)
# --------------------------------------------------------------------------- #
class Upgrade:
    """Static description of one idle upgrade line."""

    __slots__ = ("id", "name", "base", "growth", "max_lvl",
                 "per_level_effect", "description")

    def __init__(self, id, name, base, growth, max_lvl,
                 per_level_effect, description):
        self.id = id
        self.name = name
        self.base = base
        self.growth = growth
        self.max_lvl = max_lvl
        self.per_level_effect = per_level_effect  # units per level (e.g. 0.5 = +0.5%)
        self.description = description


UPGRADES: Dict[str, Upgrade] = {
    "up_xp": Upgrade(
        "up_xp", "Combat Experience", 400, 1.09, 100, 0.5,
        "+0.5% experience per mob (into xp_gain_inc)."),
    "up_gold": Upgrade(
        "up_gold", "Greed", 500, 1.10, 100, 0.4,
        "+0.4% gold per mob, online AND offline (into gold_find)."),
    "up_sxp": Upgrade(
        "up_sxp", "Skill Mastery", 750, 1.12, 50, 0.5,
        "+0.5% skill experience (sxp)."),
    "up_offline": Upgrade(
        "up_offline", "Night Watch", 1000, 1.15, 40, 0.5,
        "+0.5% offline efficiency (multiplicative to the 0.60/0.35/0.15 tiers)."),
}

# stable display order
UPGRADE_ORDER = ("up_xp", "up_gold", "up_sxp", "up_offline")


# --------------------------------------------------------------------------- #
# cost / affordability / purchase
# --------------------------------------------------------------------------- #
def cost(upgrade_id: str, current_lvl: int) -> int:
    """Gold cost to buy the NEXT level (current_lvl -> current_lvl+1).

    Geometric, rounded UP to the nearest 10:
        ceil(base * growth**current_lvl / 10) * 10

    Returns 0 when there is no next level (unknown id, or at/over max lvl).
    Negative/garbage current_lvl is clamped to 0.
    """
    up = UPGRADES.get(upgrade_id)
    if up is None:
        return 0
    try:
        lvl = int(current_lvl)
    except (TypeError, ValueError):
        lvl = 0
    if lvl < 0:
        lvl = 0
    if lvl >= up.max_lvl:
        return 0
    raw = up.base * (up.growth ** lvl)
    return int(math.ceil(raw / 10.0)) * 10


def is_maxed(upgrades: Dict[str, int], upgrade_id: str) -> bool:
    up = UPGRADES.get(upgrade_id)
    if up is None:
        return True
    return _lvl(upgrades, upgrade_id) >= up.max_lvl


def can_buy(upgrades: Dict[str, int], upgrade_id: str, gold: int) -> bool:
    """True iff the upgrade exists, is not maxed, and gold covers the next cost."""
    up = UPGRADES.get(upgrade_id)
    if up is None:
        return False
    lvl = _lvl(upgrades, upgrade_id)
    if lvl >= up.max_lvl:
        return False
    try:
        gold = int(gold)
    except (TypeError, ValueError):
        return False
    return gold >= cost(upgrade_id, lvl)


def buy(upgrades: Dict[str, int], upgrade_id: str,
        gold: int) -> Tuple[Dict[str, int], int, bool]:
    """Attempt to buy one level. Returns (new_upgrades, new_gold, ok).

    Atomic and non-mutating: the input dict is never modified in place; on
    success a NEW dict (sanitized) is returned with the level incremented and
    gold decremented by exactly ``cost``. On failure (unknown/maxed/too poor)
    returns a sanitized copy, the unchanged gold, and ok=False. Gold never goes
    negative.
    """
    clean = sanitize(upgrades)
    try:
        gold = int(gold)
    except (TypeError, ValueError):
        gold = 0
    if not can_buy(clean, upgrade_id, gold):
        return clean, gold, False
    price = cost(upgrade_id, clean.get(upgrade_id, 0))
    new_ups = dict(clean)
    new_ups[upgrade_id] = new_ups.get(upgrade_id, 0) + 1
    return new_ups, gold - price, True


# --------------------------------------------------------------------------- #
# effect getters (fold into EXISTING single-source aggregates — no raw keys)
# --------------------------------------------------------------------------- #
def xp_gain_bonus_pct(upgrades: Dict[str, int]) -> float:
    """+% experience per mob. up_xp lvl100 -> 50.0."""
    return _lvl(upgrades, "up_xp") * UPGRADES["up_xp"].per_level_effect


def gold_find_bonus_pct(upgrades: Dict[str, int]) -> float:
    """+% gold per mob (online AND offline). up_gold lvl100 -> 40.0."""
    return _lvl(upgrades, "up_gold") * UPGRADES["up_gold"].per_level_effect


def skill_xp_bonus_pct(upgrades: Dict[str, int]) -> float:
    """+% skill xp (sxp). up_sxp lvl50 -> 25.0."""
    return _lvl(upgrades, "up_sxp") * UPGRADES["up_sxp"].per_level_effect


def offline_efficiency_mult(upgrades: Dict[str, int]) -> float:
    """Multiplier for offline tier factors. up_offline lvl40 -> 1.20."""
    pct = _lvl(upgrades, "up_offline") * UPGRADES["up_offline"].per_level_effect
    return 1.0 + pct / 100.0


# --------------------------------------------------------------------------- #
# serialization
# --------------------------------------------------------------------------- #
def sanitize(raw) -> Dict[str, int]:
    """Coerce arbitrary save data into a clean {id: lvl} dict.

    Drops unknown ids, clamps levels to [0, max_lvl], coerces values to int.
    None / non-dict / garbage -> {}. Old saves (no field) -> {}.
    """
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for key, val in raw.items():
        up = UPGRADES.get(key)
        if up is None:
            continue
        try:
            lvl = int(val)
        except (TypeError, ValueError):
            continue
        if lvl <= 0:
            continue
        out[key] = min(lvl, up.max_lvl)
    return out


# --------------------------------------------------------------------------- #
# internal helpers
# --------------------------------------------------------------------------- #
def _lvl(upgrades, upgrade_id: str) -> int:
    """Safe level read: clamps to [0, max], tolerates garbage/None."""
    up = UPGRADES.get(upgrade_id)
    if up is None or not isinstance(upgrades, dict):
        return 0
    try:
        lvl = int(upgrades.get(upgrade_id, 0))
    except (TypeError, ValueError):
        return 0
    if lvl < 0:
        return 0
    return min(lvl, up.max_lvl)
