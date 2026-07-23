"""Bar of Exile — Stage 6.5 zone auto-mods ("map mods").

Standalone, data-driven pool of danger+reward zone modifiers (data/zone_mods.json).
PoE-style: each mod adds danger to a zone's spawns and buys a matching ZONE-LOCAL
reward rider (xp / drop_qty / gold ONLY — never global hero stats).

This module is pure logic: no imports from world/ui/main (avoids circular deps),
deterministic given a seeded rng. world.py will call the hooks here later:
  - roll_mods() on zone (re)arm,
  - apply_to_monster() on each spawned Monster,
  - reward_multipliers() / danger_reward_summary() for reward payout and the UI line.
NOT wired into the game yet — that is a separate step owned by the main session.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Activation gate (doc 6.5): hero lvl >= 25 OR act >= 2.
ACTIVATION_HERO_LEVEL = 25
ACTIVATION_ACT = 2

# Per-act mod-count probability tables (doc 6.5). Keyed by act; each maps
# count -> probability (sums to 1.0). +1 slot on Cruel+ is applied on top.
_COUNT_TABLES: dict[int, dict[int, float]] = {
    2: {0: 0.50, 1: 0.35, 2: 0.15},
    3: {1: 0.40, 2: 0.40, 3: 0.20},
    4: {2: 0.60, 3: 0.40},
}

# Difficulties that grant the "+1 slot" bonus (Cruel and beyond).
_EXTRA_SLOT_DIFFICULTIES = frozenset({"cruel", "merciless"})

_cache: dict | None = None  # id -> mod dict


def load_zone_mods() -> dict:
    """Load & cache the mod pool as {id: mod_dict} from data/zone_mods.json."""
    global _cache
    if _cache is None:
        with open(_DATA_DIR / "zone_mods.json", encoding="utf-8") as f:
            raw = json.load(f)
        _cache = {m["id"]: m for m in raw.get("mods", [])}
    return _cache


def all_mod_ids() -> list[str]:
    """Every mod id in pool order (stable, for pickers/UI)."""
    return list(load_zone_mods().keys())


def is_active(hero_level: int, act: int) -> bool:
    """Activation gate: zone mods arm when hero lvl >= 25 OR act >= 2."""
    return hero_level >= ACTIVATION_HERO_LEVEL or act >= ACTIVATION_ACT


def _weighted_choice(table: dict[int, float], rng: random.Random) -> int:
    """Pick a key from {value: probability}. Deterministic given rng."""
    r = rng.random()
    acc = 0.0
    last = 0
    for count, p in table.items():
        acc += p
        last = count
        if r < acc:
            return count
    return last  # float rounding guard


def roll_mod_count(act: int, difficulty_id: str, rng: random.Random) -> int:
    """How many mods to arm for a zone this (re)arm. Per-act table + Cruel+ slot.

    Acts outside 2..4 clamp to the nearest defined table (act < 2 -> Act2's,
    act > 4 -> Act4's) so post-Act4 / rift callers still get a sane roll.
    """
    key = 2 if act < 2 else 4 if act > 4 else act
    count = _weighted_choice(_COUNT_TABLES[key], rng)
    if difficulty_id in _EXTRA_SLOT_DIFFICULTIES:
        count += 1
    return count


def roll_mods(act: int, difficulty_id: str, rng: random.Random) -> list[str]:
    """Pick `roll_mod_count` DISTINCT mod ids for a zone. Never exceeds pool size."""
    n = roll_mod_count(act, difficulty_id, rng)
    ids = all_mod_ids()
    n = min(n, len(ids))
    if n <= 0:
        return []
    return rng.sample(ids, n)


def danger_reward_summary(mod_ids: list[str]) -> tuple[float, float]:
    """Total DANGER % and total REWARD % for the `DANGER +X% -> REWARD +Y%` line.

    Danger = sum of each mod's danger_pct. Reward = sum of each rider's pct.
    Both are additive display figures; reward_multipliers() is the number that
    actually pays out (product of riders per bucket).
    """
    pool = load_zone_mods()
    danger = 0.0
    reward = 0.0
    for mid in mod_ids:
        mod = pool.get(mid)
        if not mod:
            continue
        danger += float(mod.get("danger_pct", 0))
        reward += float(mod.get("reward", {}).get("pct", 0))
    return danger, reward


def reward_multipliers(mod_ids: list[str]) -> dict:
    """Zone-local reward multipliers {"xp": m, "drop_qty": m, "gold": m}.

    Product of each active rider (1 + pct/100) in its bucket. Always >= 1.0.
    HARD RULE (doc 6.5): these scale zone-local xp/drop/gold ONLY, never global
    hero stats — the caller multiplies the zone's payout by these, nothing else.
    """
    pool = load_zone_mods()
    out = {"xp": 1.0, "drop_qty": 1.0, "gold": 1.0}
    for mid in mod_ids:
        mod = pool.get(mid)
        if not mod:
            continue
        reward = mod.get("reward", {})
        kind = reward.get("kind")
        if kind in out:
            out[kind] *= 1 + float(reward.get("pct", 0)) / 100
    return out


def apply_to_monster(monster, mod_ids: list[str]) -> None:
    """Apply danger effects to a freshly spawned Monster, mutating in place.

    Defensive by design (getattr/setattr): a missing Stats field or Monster
    attribute is skipped, never raised — so this stays safe as the schema evolves
    and as world.py wires it in. Effect kinds:
      - stat_mult / stat_add: scale/offset a Stats field (life re-syncs max_hp/hp).
      - spawn:  set a spawner-facing flag+attr on the Monster (horde/champions) —
                the spawner reads these; per-monster call is a no-op on stats.
      - flag:   set a combat-facing flag+attr (burning/toxic/unstable) for the
                combat layer to consume later.
      - hero:   affects the hero, not the monster — recorded via hero_effects()
                instead; ignored here.
    """
    pool = load_zone_mods()
    stats = getattr(monster, "stats", None)
    touched_life = False
    for mid in mod_ids:
        mod = pool.get(mid)
        if not mod:
            continue
        for eff in mod.get("effects", []):
            kind = eff.get("kind")
            if kind == "stat_mult" and stats is not None:
                stat = eff["stat"]
                if hasattr(stats, stat):
                    setattr(stats, stat, getattr(stats, stat) * float(eff["mult"]))
                    touched_life = touched_life or stat == "life"
            elif kind == "stat_add" and stats is not None:
                stat = eff["stat"]
                if hasattr(stats, stat):
                    setattr(stats, stat, getattr(stats, stat) + float(eff["add"]))
                    touched_life = touched_life or stat == "life"
            elif kind in ("spawn", "flag"):
                # Runtime marker attrs read by the spawner / combat layer later.
                if "flag" in eff:
                    setattr(monster, eff["flag"], True)
                if "attr" in eff:
                    setattr(monster, eff["attr"], eff.get("value"))
            # kind == "hero": not a monster effect; see hero_effects().
    # Re-sync hit points if we changed life AFTER init_hp() already ran.
    if touched_life and stats is not None and getattr(monster, "max_hp", 0):
        keep = monster.hp / monster.max_hp if monster.max_hp > 0 else 1.0
        monster.max_hp = stats.life
        monster.hp = monster.max_hp * keep


def _spawn_effect_value(mod_ids: list[str], attr: str, default: float,
                        combine: str) -> float:
    """Aggregate a spawner-facing effect value (kind=="spawn") across mods.
    combine="mult" multiplies (pack size), "sum" adds (extra champion packs)."""
    pool = load_zone_mods()
    acc = 1.0 if combine == "mult" else 0.0
    for mid in mod_ids:
        mod = pool.get(mid)
        if not mod:
            continue
        for eff in mod.get("effects", []):
            if eff.get("kind") == "spawn" and eff.get("attr") == attr:
                v = float(eff.get("value", default))
                acc = acc * v if combine == "mult" else acc + v
    return acc


def pack_size_mult(mod_ids: list[str]) -> float:
    """Product of horde-style pack-size multipliers (zm_pack_mult), 1.0 if none."""
    return _spawn_effect_value(mod_ids, "zm_pack_mult", 1.0, "mult")


def extra_champion_packs(mod_ids: list[str]) -> int:
    """Sum of champions-mod extra champion packs (zm_extra_champ_packs), 0 if none."""
    return int(_spawn_effect_value(mod_ids, "zm_extra_champ_packs", 0.0, "sum"))


def hero_effects(mod_ids: list[str]) -> list[dict]:
    """Danger effects that target the HERO, not monsters (e.g. draining's leech).

    Returns the raw effect dicts (kind == "hero") so the wiring layer can apply
    them to the hero's zone-local combat context. Kept separate from
    apply_to_monster so per-monster spawn stays cheap and side-effect-free on the hero.
    """
    pool = load_zone_mods()
    out: list[dict] = []
    for mid in mod_ids:
        mod = pool.get(mid)
        if not mod:
            continue
        for eff in mod.get("effects", []):
            if eff.get("kind") == "hero":
                out.append(eff)
    return out


if __name__ == "__main__":
    pool = load_zone_mods()
    assert len(pool) == 12, f"expected 12 mods, got {len(pool)}"

    # Activation gate.
    assert not is_active(10, 1)
    assert is_active(25, 1)
    assert is_active(10, 2)

    for act in (2, 3, 4):
        rng = random.Random(1234 + act)
        ids = roll_mods(act, "normal", rng)
        assert len(ids) == len(set(ids)), "mods must be distinct"
        danger, reward = danger_reward_summary(ids)
        mult = reward_multipliers(ids)
        assert all(v >= 1.0 for v in mult.values()), mult
        print(f"Act {act}: {len(ids)} mods {ids}")
        print(f"  DANGER +{danger:.0f}% -> REWARD +{reward:.0f}%  mults={mult}")

    # Cruel adds a slot vs Normal on the same seed/act.
    r_norm = random.Random(7)
    r_cruel = random.Random(7)
    n_norm = roll_mod_count(3, "normal", r_norm)
    n_cruel = roll_mod_count(3, "cruel", r_cruel)
    assert n_cruel == n_norm + 1, (n_norm, n_cruel)

    # apply_to_monster is defensive: a bare object with a Stats-like shape works,
    # and unknown/absent fields never raise. Use a tiny duck-typed stand-in.
    class _S:
        life = 100.0
        damage_min = 5.0
        damage_max = 9.0
        move_speed = 30.0
        attack_speed = 1.0
        crit_chance = 5.0
        armor = 10.0

    class _M:
        def __init__(self):
            self.stats = _S()
            self.max_hp = 100.0
            self.hp = 100.0

    m = _M()
    apply_to_monster(m, ["ferocity", "vitality", "deadly", "armored",
                         "horde", "burning", "unstable", "champions"])
    assert abs(m.stats.damage_min - 5.0 * 1.30) < 1e-9, m.stats.damage_min
    assert abs(m.stats.life - 140.0) < 1e-9, m.stats.life
    assert abs(m.max_hp - 140.0) < 1e-9, m.max_hp  # re-synced after life change
    assert abs(m.stats.crit_chance - 15.0) < 1e-9, m.stats.crit_chance
    assert abs(m.stats.armor - 15.0) < 1e-9, m.stats.armor
    assert getattr(m, "zm_horde") is True and getattr(m, "zm_pack_mult") == 1.30
    assert getattr(m, "zm_fire_pct") == 0.20
    assert getattr(m, "zm_explode_pct") == 0.30
    assert getattr(m, "zm_extra_champ_packs") == 2

    # Hero-targeted effect (draining) is surfaced separately, not on the monster.
    he = hero_effects(["draining", "ferocity"])
    assert len(he) == 1 and he[0]["stat"] == "life_leech" and he[0]["mult"] == 0.70

    # unknown ids are ignored everywhere (defensive).
    assert danger_reward_summary(["nope"]) == (0.0, 0.0)
    assert reward_multipliers(["nope"]) == {"xp": 1.0, "drop_qty": 1.0, "gold": 1.0}

    print("zone_mods OK")
