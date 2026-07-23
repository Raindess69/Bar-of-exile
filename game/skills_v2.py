"""Bar of Exile — Skills V2 (Gem Souls) engine.

Data-driven auto-cast engine living BESIDE the legacy game.skills. Behaviour is
dispatched from data (type + tags + params) rather than one function per skill.
All actual damage flows through game.skills._deal so the shared damage formula
  (base + Σflat) × (1 + Σinc/100) × Π(1 + more/100)
and its idle-stat / ailment / leech / kill-heal handling stay in one place.

S.1 scope only: loading, ranks/skill-xp, loadout defaulting, and the combat
tick. Save migration, main.py wiring, keystones, tomes, awakening gold-sink and
UI are OUT of scope (S.2-S.6) and intentionally not implemented here.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

from game.core import CombatEvent, DamageType, Hero, Monster
# Reuse the shared combat helpers — same layer, never duplicate the damage math.
# Step 2a: these now live in game.combat_math (extracted verbatim from the legacy
# game.skills) so this engine no longer depends on the legacy module for them.
from game.combat_math import CDR_CAP, _alive_in_range, _deal, _heal  # noqa: F401
from game import buffs  # SK-H3: aura / cast-buff params -> real Stats mods

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# rank/xp tuning (mirrors data/skills_v2.json meta)
RANK_CAP = 20
AWAKENED_RANK_CAP = 25
PER_RANK_MORE_PCT = 4
SXP_EQUIPPED_MULT = 0.6
SXP_LEECH_MULT = 0.25   # unequipped-but-unlocked skills get 25% of the equipped grant

# Loadout rework: the primary (auto-attack replacer) stays separate and always
# equipped; every OTHER skill type (spender / aura / utility / ultimate) shares
# ONE common pool of skill slots. You pick at most len(SKILL_SLOT_LEVELS) skills
# total, regardless of type — want an aura, you spend a slot that could have held
# a spender. Slots open at these hero levels: 1 / 25 / 50 / 75 (up to 4 at 75).
SKILL_SLOT_LEVELS = (1, 25, 50, 75)
MAX_SKILL_SLOTS = len(SKILL_SLOT_LEVELS)

# rotation heuristics
PACK_ULT_THRESHOLD = 4          # cast ultimate on packs of this many+
UTILITY_HEAL_THRESHOLD = 0.70   # only self-heal below this hp fraction

# default ailment application chances by kind (analogous to legacy skills.py)
_AILMENT_CHANCE = {
    "poison": 80.0,
    "bleed": 60.0,
    "ignite": 40.0,
    "shock": 30.0,
    "freeze": 100.0,
    "stun": 25.0,
}


@dataclass
class SkillV2:
    id: str
    name: str
    class_id: str
    type: str                 # primary | spender | aura | utility | ultimate
    tags: list[str]
    damage_type: DamageType
    unlock_level: int
    cooldown_s: float
    base_damage_pct: float
    hits: int
    per_rank_more_pct: float
    per_rank_secondary_pct: float
    rank_cap: int
    range_px: float
    effect: str
    params: dict


_skills_cache: dict[str, SkillV2] | None = None
_talents_cache: dict | None = None


# --------------------------------------------------------------------------- #
# loading / lookups
# --------------------------------------------------------------------------- #
def load_skills_v2() -> dict[str, SkillV2]:
    """id -> SkillV2 (cached), from data/skills_v2.json."""
    global _skills_cache
    if _skills_cache is None:
        with open(_DATA_DIR / "skills_v2.json", encoding="utf-8") as f:
            raw = json.load(f)
        out: dict[str, SkillV2] = {}
        for s in raw.get("skills", []):
            out[s["id"]] = SkillV2(
                id=s["id"], name=s["name"], class_id=s["class"], type=s["type"],
                tags=list(s.get("tags", [])),
                damage_type=DamageType(s["damage_type"]),
                unlock_level=int(s["unlock_level"]), cooldown_s=float(s["cooldown_s"]),
                base_damage_pct=float(s["base_damage_pct"]),
                hits=int(s["hits"]), per_rank_more_pct=float(s["per_rank_more_pct"]),
                per_rank_secondary_pct=float(s["per_rank_secondary_pct"]),
                rank_cap=int(s["rank_cap"]), range_px=float(s["range_px"]),
                effect=s.get("effect", ""), params=dict(s.get("params", {})),
            )
        _skills_cache = out
    return _skills_cache


def load_talents_v2() -> dict:
    """Raw dict from data/skill_talents_v2.json (tiers + pools), cached."""
    global _talents_cache
    if _talents_cache is None:
        with open(_DATA_DIR / "skill_talents_v2.json", encoding="utf-8") as f:
            _talents_cache = json.load(f)
    return _talents_cache


def _class_skills(class_id: str) -> list[SkillV2]:
    """All skills of a class, in unlock (json) order."""
    return [s for s in load_skills_v2().values() if s.class_id == class_id]


# --------------------------------------------------------------------------- #
# ranks / skill-xp
# --------------------------------------------------------------------------- #
def sxp_need(rank: int) -> int:
    """Skill-xp threshold FOR reaching `rank`: floor(40 * rank**1.7). need(1)=0."""
    if rank <= 1:
        return 0
    return int(math.floor(40 * rank ** 1.7))


def _total_need(rank: int) -> int:
    """Cumulative skill-xp required to be AT `rank` (Σ sxp_need(2..rank))."""
    return sum(sxp_need(r) for r in range(2, rank + 1))


def rank_from_sxp(sxp: int, cap: int = RANK_CAP) -> int:
    """Cumulative rank from accumulated sxp. Rank 1 at sxp>=0, grows while the
       cumulative threshold for the next rank is met, capped at `cap`."""
    rank = 1
    while rank < cap and _total_need(rank + 1) <= sxp:
        rank += 1
    return rank


def skill_rank(hero: Hero, sid: str) -> int:
    """Current rank of a skill for a hero (awakened skills reach cap 25)."""
    sv = getattr(hero, "skills_v2", None) or {}
    sxp = int(sv.get("sxp", {}).get(sid, 0))
    cap = AWAKENED_RANK_CAP if sid in sv.get("awakened", []) else RANK_CAP
    return rank_from_sxp(sxp, cap)


def _talent_options(skill: SkillV2) -> dict[int, list[tuple[dict, float]]]:
    """tier_rank -> list of (option, juice) available to this skill.

    Options are filtered by the skill's tags via each option's optional
    `tags_any` (an option with no tags_any is universal). The player's stored
    choice_idx indexes into this filtered list.
    """
    talents = load_talents_v2()
    tags = set(skill.tags)
    out: dict[int, list[tuple[dict, float]]] = {}
    for tier in talents["tiers"]:
        pool = talents["pools"][tier["pool"]]
        juice = float(tier.get("juice", 1.0))
        opts: list[tuple[dict, float]] = []
        for opt in pool:
            ta = opt.get("tags_any")
            if ta and not (set(ta) & tags):
                continue
            opts.append((opt, juice))
        out[int(tier["rank"])] = opts
    return out


def _talent_mods(hero: Hero, skill: SkillV2) -> dict[str, float]:
    """Aggregate the mod values from the hero's chosen talents for this skill,
       scaled by each tier's juice."""
    sv = getattr(hero, "skills_v2", None) or {}
    chosen = sv.get("talents", {}).get(skill.id, {})
    if not chosen:
        return {}
    opts_by_tier = _talent_options(skill)
    agg: dict[str, float] = {}
    for tier_str, idx in chosen.items():
        try:
            rank = int(tier_str)
            idx = int(idx)
        except (TypeError, ValueError):
            continue
        opts = opts_by_tier.get(rank, [])
        if 0 <= idx < len(opts):
            opt, juice = opts[idx]
            for k, v in opt.get("mods", {}).items():
                agg[k] = agg.get(k, 0.0) + v * juice
    return agg


def skill_more_mult(hero: Hero, sid: str) -> float:
    """MORE multiplier for a skill's damage. Per the frozen formula each MORE
       source is its own factor: Π(1+more/100), not one additive bucket.
       Talent 'inc' is applied separately at cast time (see _effective_pct)."""
    skills = load_skills_v2()
    skill = skills.get(sid)
    if skill is None:
        return 1.0
    rank = skill_rank(hero, sid)
    per_rank_more = skill.per_rank_more_pct * (rank - 1)
    talent_more = _talent_mods(hero, skill).get("more_dmg_pct", 0.0)
    return (1.0 + per_rank_more / 100.0) * (1.0 + talent_more / 100.0)


# --------------------------------------------------------------------------- #
# unlocks / loadout
# --------------------------------------------------------------------------- #
def unlocked_by_level(class_id: str, level: int) -> list[str]:
    """Ids of a class's skills with unlock_level <= level, in unlock order."""
    return [s.id for s in _class_skills(class_id) if s.unlock_level <= level]


def slots_open(level: int) -> int:
    """How many common skill slots are open at a hero level (1/25/50/75)."""
    return sum(1 for lv in SKILL_SLOT_LEVELS if level >= lv)


def loadout_slots_open(level: int) -> dict:
    """Which loadout slots are open at a hero level. `primary` is always 1;
       `slots` is the size of the common pool open at this level."""
    return {"primary": 1, "slots": slots_open(level)}


def _first_unslotted(class_id: str, unlocked: list[str], used: set[str],
                     exclude_primary: bool = True) -> str | None:
    """First unlocked, not-yet-used skill of the class (any non-primary type)."""
    for s in _class_skills(class_id):
        if s.id in unlocked and s.id not in used:
            if exclude_primary and s.type == "primary":
                continue
            return s.id
    return None


def _migrate_legacy_loadout(loadout: dict) -> None:
    """In place: fold a pre-rework loadout (actives[3] + aura/utility/ultimate)
       into the common `slots` pool, preserving order and dropping dups. Called
       from _autofill before filling, so old saves upgrade transparently."""
    if "slots" in loadout and "actives" not in loadout:
        return  # already new shape
    pool: list[str] = []
    seen: set[str] = set()
    for sid in loadout.get("actives", []):
        if sid and sid not in seen:
            pool.append(sid); seen.add(sid)
    for key in ("aura", "utility", "ultimate"):
        sid = loadout.get(key)
        if sid and sid not in seen:
            pool.append(sid); seen.add(sid)
    loadout["slots"] = pool
    for key in ("actives", "aura", "utility", "ultimate"):
        loadout.pop(key, None)


def _autofill_loadout(class_id: str, level: int, loadout: dict,
                      unlocked: list[str]) -> None:
    """Fill any empty open pool slots with the first suitable unlocked skill, in
       place. Never overwrites an existing pick. Migrates legacy loadouts first."""
    _migrate_legacy_loadout(loadout)
    used: set[str] = set()
    if loadout.get("primary"):
        used.add(loadout["primary"])
    else:
        # primary = first skill of the class (always a primary)
        cls = _class_skills(class_id)
        loadout["primary"] = cls[0].id if cls else None
        if loadout["primary"]:
            used.add(loadout["primary"])

    n_open = slots_open(level)
    slots = loadout.setdefault("slots", [])
    # drop any stale/duplicate ids, keep order
    clean: list[str] = []
    for sid in slots:
        if sid and sid not in used and sid in unlocked:
            clean.append(sid); used.add(sid)
    # trim to what's open (a shrunk level shouldn't leave over-slotted skills)
    slots[:] = clean[:n_open]
    # top up empty open slots with the next suitable unlocked skill
    while len(slots) < n_open:
        pick = _first_unslotted(class_id, unlocked, used)
        if not pick:
            break
        slots.append(pick); used.add(pick)


def default_skills_v2(class_id: str, level: int) -> dict:
    """A valid default skills_v2 block for a new hero / v4->v5 migration."""
    unlocked = unlocked_by_level(class_id, level)
    loadout: dict = {"primary": None, "slots": []}
    _autofill_loadout(class_id, level, loadout, unlocked)
    return {
        "unlocked": unlocked,
        "loadout": loadout,
        "priority": list(loadout["slots"]),
        "sxp": {},
        "talents": {},
        "awakened": [],
        "tomes_read": 0,
    }


# NOTE: "keystones" was the v1 keystone prototype (S.4 rework moved class
# keystones into the passive tree). save.py drops the stale key on load; it must
# NOT be required here or ensure_skills_v2's subset check fails on every real
# save and wipes the block back to defaults (sxp/talents/awakening/tomes lost).
_REQUIRED_KEYS = {"unlocked", "loadout", "priority", "sxp", "talents",
                  "awakened", "tomes_read"}


def ensure_skills_v2(hero: Hero) -> None:
    """Idempotent: seed a default block if missing/broken, otherwise top up
       newly unlocked skills and newly opened slots. Safe to call every tick."""
    sv = getattr(hero, "skills_v2", None)
    if not sv or not _REQUIRED_KEYS <= set(sv) or not sv.get("loadout"):
        hero.skills_v2 = default_skills_v2(hero.class_id, hero.level)
        return
    unlocked = unlocked_by_level(hero.class_id, hero.level)
    for sid in unlocked:
        if sid not in sv["unlocked"]:
            sv["unlocked"].append(sid)
    _autofill_loadout(hero.class_id, hero.level, sv["loadout"], sv["unlocked"])
    for sid in sv["loadout"]["slots"]:
        if sid and sid not in sv["priority"]:
            sv["priority"].append(sid)


def _equipped_ids(sv: dict) -> list[str]:
    """All skill ids currently in the loadout (primary + the common pool)."""
    lo = sv.get("loadout", {})
    out: list[str] = []
    if lo.get("primary"):
        out.append(lo["primary"])
    for sid in lo.get("slots", []):
        if sid:
            out.append(sid)
    # dedup preserving order
    seen: set[str] = set()
    return [x for x in out if not (x in seen or seen.add(x))]


# --------------------------------------------------------------------------- #
# combat tick
# --------------------------------------------------------------------------- #
def _effective_cd(hero: Hero, skill: SkillV2) -> float:
    """Base cooldown reduced by CDR (cap 60%), talent cooldown, and — for
       spell-y classes — cast speed.

    Primary skills carry ``cooldown_s == 0`` in data because the design calls
    them "auto-attack replacers, no cooldown". That does NOT mean "castable 20×
    per second" — it means they fire at the hero's ATTACK RATE. Returning the
    attack interval here keeps a stray primary cast (if one ever reaches the
    rotation) in lockstep with the auto-attack instead of machine-gunning."""
    if skill.cooldown_s <= 0:
        aps = max(hero.stats.attack_speed, 0.05)
        if skill.class_id in ("mage", "cleric") and hero.stats.cast_speed_inc > 0:
            aps *= 1 + hero.stats.cast_speed_inc / 100.0
        return 1.0 / aps
    s = hero.stats
    cd = skill.cooldown_s * (1 - min(s.cooldown_reduction, CDR_CAP) / 100.0)
    tm = _talent_mods(hero, skill)
    cd_talent = tm.get("cooldown_pct", 0.0)
    if cd_talent:
        cd *= 1 + cd_talent / 100.0
    # SK-H2: attack_speed_pct (off_as) shortens the effective cooldown too, so a
    # faster-attacking build recasts sooner (skills have no separate swing timer).
    as_talent = tm.get("attack_speed_pct", 0.0)
    if as_talent:
        cd /= 1 + as_talent / 100.0
    if skill.class_id in ("mage", "cleric") and s.cast_speed_inc > 0:
        cd /= 1 + s.cast_speed_inc / 100.0
    return max(cd, 0.25)


def _effective_pct(hero: Hero, skill: SkillV2) -> float:
    """Per-hit damage fraction: base%/100 × MORE-mult × (1 + talent inc)."""
    pct = skill.base_damage_pct / 100.0 * skill_more_mult(hero, skill.id)
    inc = _talent_mods(hero, skill).get("inc_dmg_pct", 0.0)
    if inc:
        pct *= 1 + inc / 100.0
    return pct


def _ailment_from(hero: Hero, skill: SkillV2) -> tuple[str, float] | None:
    """Derive an (kind, chance) ailment for _deal from the skill's params/tags.

    SK-H1 fix: ignite/shock used to require tag combos no skill had
    (`fire`+`dot`) or a param only the primary `spark` carried — so both
    ailments were dead along with storm_herald/pyromaniac. They now fall back to
    the skill's ELEMENT: any fire skill can ignite, any lightning skill can
    shock. Explicit poison/bleed/freeze/stun params still take priority so a
    skill that names its ailment keeps it."""
    p, tags = skill.params, skill.tags
    dt = skill.damage_type
    kind: str | None = None
    if "poison_pct" in p or "poison_stacks" in p or "poison" in tags:
        kind = "poison"
    elif "bleed_pct" in p or "bleed_stacks" in p or "bleed" in tags:
        kind = "bleed"
    elif "freeze" in p or "chill" in p or "freeze" in tags or "chill" in tags:
        kind = "freeze"
    elif "stun_s" in p or "stun" in tags:
        kind = "stun"
    elif "ignite" in p or ("fire" in tags and "dot" in tags) or dt == DamageType.FIRE:
        kind = "ignite"
    elif "shock_pct" in p or "shock" in tags or dt == DamageType.LIGHTNING:
        kind = "shock"
    if kind is None:
        return None
    chance = _AILMENT_CHANCE[kind]
    if kind == "shock" and "shock_pct" in p:
        chance = float(p["shock_pct"])
    chance += _talent_mods(hero, skill).get("ailment_chance_pct", 0.0)
    return (kind, chance)


def _nearest_in(hero: Hero, monsters: list[Monster], radius: float) -> Monster | None:
    tgts = _alive_in_range(hero, monsters, radius)
    return min(tgts, key=lambda m: abs(m.x - hero.x)) if tgts else None


def _build_skill_ctx(hero: Hero, skill: SkillV2) -> dict:
    """Per-cast context consumed by combat_math._deal (SK-H2). Carries talent
    crit/lifesteal onto every hit of this cast. Reuses the socket-passive ctx
    shape (damage_inc/dealt) so both sources compose."""
    tm = _talent_mods(hero, skill)
    return {
        "damage_inc": 0.0,   # socket passives fold in via skills.py path; skills_v2 talents use inc at _effective_pct
        "dealt": 0.0,
        "crit_chance": tm.get("crit_chance_pct", 0.0),
        "crit_multi": tm.get("crit_multi_pct", 0.0),
        "lifesteal": tm.get("lifesteal_pct", 0.0),
    }


def _apply_effect(hero: Hero, skill: SkillV2, monsters: list[Monster],
                  events: list[CombatEvent], rng: random.Random) -> None:
    """Generic, data-driven damage dispatch (type + tags + params)."""
    if skill.base_damage_pct <= 0:
        return
    pct = _effective_pct(hero, skill)
    dtype = skill.damage_type
    ailment = _ailment_from(hero, skill)
    targets = _alive_in_range(hero, monsters, skill.range_px)
    if not targets:
        return
    targets.sort(key=lambda m: abs(m.x - hero.x))
    tm = _talent_mods(hero, skill)
    # SK-H2: extra_targets (tmp_extra) widens splits and AoE target caps.
    extra = int(tm.get("extra_targets", 0))
    hits = max(1, skill.hits + (extra if skill.type == "primary" else 0))
    is_aoe = "aoe" in skill.tags or bool(skill.params.get("aoe"))
    # SK-H2: crit/lifesteal talents ride along on every hit via the cast ctx.
    prev_ctx = getattr(hero, "_skill_ctx", None)
    hero._skill_ctx = _build_skill_ctx(hero, skill)
    try:
        if is_aoe:
            max_t = skill.params.get("max_targets")
            if max_t:
                max_t += extra  # SK-H2: extra_targets also raises the AoE cap
            pool = targets[:max_t] if max_t else targets
            for _ in range(hits):
                for m in pool:
                    if m.alive:
                        _deal(hero, m, pct, dtype, events, is_area=True,
                              ailment=ailment, rng=rng)
        elif skill.type == "primary" and hits > 1:
            # split: one hit per nearest target, overflow onto the nearest
            for i in range(hits):
                alive = [m for m in targets if m.alive]
                if not alive:
                    break
                tgt = alive[i] if i < len(alive) else alive[0]
                _deal(hero, tgt, pct, dtype, events, ailment=ailment, rng=rng)
        else:
            tgt = next((m for m in targets if m.alive), None)
            if tgt:
                for _ in range(hits):
                    if tgt.alive:
                        _deal(hero, tgt, pct, dtype, events, ailment=ailment, rng=rng)
    finally:
        hero._skill_ctx = prev_ctx


def _cast(hero: Hero, skill: SkillV2, monsters: list[Monster],
          events: list[CombatEvent], rng: random.Random) -> None:
    target = _nearest_in(hero, monsters, skill.range_px)
    events.append(CombatEvent(
        "skill", x=target.x if target else hero.x, text=skill.id,
        origin=hero.x if target else None, target=target,
        dtype=skill.damage_type, class_id=hero.class_id))
    if skill.base_damage_pct > 0:
        _apply_effect(hero, skill, monsters, events, rng)
    else:
        # buff-only spender/ultimate (e.g. Avatar of War): S.1 sets a flag
        hero.flags.add(skill.id)
    hero.skill_cds[skill.id] = _effective_cd(hero, skill)


def _ready(hero: Hero, sid: str) -> bool:
    return hero.skill_cds.get(sid, 0.0) <= 0.0


def _slotted_of_type(sv: dict, skills: dict[str, SkillV2], stype: str) -> list[str]:
    """Ids in the common pool whose skill type is `stype`, in slot order."""
    return [sid for sid in sv.get("loadout", {}).get("slots", [])
            if sid and sid in skills and skills[sid].type == stype]


def _try_utility(hero: Hero, monsters: list[Monster], events: list[CombatEvent],
                 rng: random.Random, skills: dict[str, SkillV2]) -> None:
    # any utility skill sitting in the common pool self-casts on its own cooldown
    for sid in _slotted_of_type(hero.skills_v2, skills, "utility"):
        if not _ready(hero, sid):
            continue
        sk = skills[sid]
        p = sk.params
        if "heal_pct" in p:
            if hero.hp < UTILITY_HEAL_THRESHOLD * hero.max_hp:
                events.append(CombatEvent("skill", x=hero.x, text=sk.id, origin=hero.x))
                _heal(hero, p["heal_pct"] / 100.0, events)
                hero.skill_cds[sid] = _effective_cd(hero, sk)
        else:
            # buff / trap / echo — S.1 stub: emit + flag, no complex logic
            events.append(CombatEvent("skill", x=hero.x, text=sk.id, origin=hero.x))
            hero.flags.add(sid)
            hero.skill_cds[sid] = _effective_cd(hero, sk)


def _rotate(hero: Hero, monsters: list[Monster], events: list[CombatEvent],
            rng: random.Random, skills: dict[str, SkillV2], reach: float) -> None:
    sv = hero.skills_v2
    in_reach = _alive_in_range(hero, monsters, reach)
    boss = any(getattr(m, "is_boss", False) for m in in_reach)
    pack = len(in_reach)

    # 1) ultimate (from the pool) on bosses / packs
    for ult in _slotted_of_type(sv, skills, "ultimate"):
        if _ready(hero, ult) and (boss or pack >= PACK_ULT_THRESHOLD):
            if _alive_in_range(hero, monsters, skills[ult].range_px) or skills[ult].base_damage_pct <= 0:
                _cast(hero, skills[ult], monsters, events, rng)
                return

    # 2) spenders, priority order first, then any remaining slotted spender
    spenders = _slotted_of_type(sv, skills, "spender")
    ordered = [s for s in sv.get("priority", []) if s in spenders]
    for s in spenders:
        if s not in ordered:
            ordered.append(s)
    for sid in ordered:
        if _ready(hero, sid):
            sk = skills[sid]
            if _alive_in_range(hero, monsters, sk.range_px):
                _cast(hero, sk, monsters, events, rng)
                return

    # NOTE: primary is intentionally NOT cast here. A primary skill is the
    # "auto-attack replacer" (design §2) — combat.CombatSystem._hero_strike
    # already fires it at the hero's attack rate with crit / cleave / leech, and
    # scales it by primary_growth_mult() below so its rank & talents still count.
    # Casting it from the rotation too would double the damage AND spam it every
    # tick (its data cooldown is 0), which is exactly the bug we are fixing.


def primary_growth_mult(hero: Hero) -> float:
    """Damage multiplier the equipped primary's ranks + talents contribute to the
    hero's auto-attack (MORE bucket × talent inc). 1.0 when no primary / rank 1
    / no talents. Base_damage_pct is deliberately excluded — the auto-attack IS
    the primary's base hit, so folding it in would double-count."""
    sv = getattr(hero, "skills_v2", None)
    if not sv:
        return 1.0
    sid = sv.get("loadout", {}).get("primary")
    if not sid:
        return 1.0
    skills = load_skills_v2()
    skill = skills.get(sid)
    if skill is None:
        return 1.0
    mult = skill_more_mult(hero, sid)
    inc = _talent_mods(hero, skill).get("inc_dmg_pct", 0.0)
    if inc:
        mult *= 1 + inc / 100.0
    return mult


# --------------------------------------------------------------------------- #
# UI-facing helpers (S.6): equip / priority / talents / rank progress.
# All are pure state mutators on hero.skills_v2 — the panel never touches the
# dict directly, so every rule (slot type, unlock gate, talent rank gate) lives
# here and stays testable without Qt.
# --------------------------------------------------------------------------- #

# which loadout slot family a skill type belongs to. After the rework only the
# primary is special; every other type shares the common "slots" pool.
_TYPE_TO_SLOT = {
    "primary": "primary",
    "spender": "slots",
    "aura": "slots",
    "utility": "slots",
    "ultimate": "slots",
}

RESPEC_GOLD_PER_LEVEL = 100   # §3: respec one skill's talents = 100 × hero level


def slot_family_for(sid: str) -> str | None:
    """The loadout slot family ('primary' or 'slots') a skill belongs to, or
       None if the id is unknown."""
    sk = load_skills_v2().get(sid)
    return _TYPE_TO_SLOT.get(sk.type) if sk else None


def can_equip(hero: Hero, sid: str) -> tuple[bool, str]:
    """(ok, reason). A skill is equippable when it exists, is unlocked, and —
       for non-primary skills — the common pool has a free (or replaceable) slot
       at the hero's level. Any skill type competes for the same pool now, so the
       only gate besides the skill's own unlock is 'is a pool slot open at all'."""
    sk = load_skills_v2().get(sid)
    if sk is None:
        return False, "unknown skill"
    sv = getattr(hero, "skills_v2", None) or {}
    if sid not in sv.get("unlocked", []):
        return False, f"unlocks at level {sk.unlock_level}"
    if _TYPE_TO_SLOT[sk.type] == "primary":
        return True, ""
    n_open = slots_open(hero.level)
    if n_open <= 0:
        return False, f"skill slot opens at level {SKILL_SLOT_LEVELS[0]}"
    # already slotted -> re-equip is a no-op move, always allowed
    if sid in sv.get("loadout", {}).get("slots", []):
        return True, ""
    return True, ""  # a full pool replaces the last slot, so equip never blocks


def equip_skill(hero: Hero, sid: str, slot_idx: int | None = None) -> bool:
    """Put a skill into the loadout. Primaries go to the primary slot. Every
       other type goes into the common pool: `slot_idx` picks the slot (0-based);
       if None, fills the first open empty slot, else replaces the last open one.
       Returns True on success. A skill already in the pool is MOVED, not
       duplicated. Keeps `priority` in sync."""
    ok, _ = can_equip(hero, sid)
    if not ok:
        return False
    sv = hero.skills_v2
    lo = sv["loadout"]
    fam = _TYPE_TO_SLOT[load_skills_v2()[sid].type]
    if fam == "primary":
        lo["primary"] = sid
        _sync_priority(sv)
        return True
    n_open = slots_open(hero.level)
    if n_open <= 0:
        return False
    slots = lo.setdefault("slots", [])
    # remove any existing copy so we never double-slot the same skill
    if sid in slots:
        slots.remove(sid)
    if slot_idx is None:
        if len(slots) < n_open:
            slots.append(sid)            # fill next empty slot
        else:
            slots[n_open - 1] = sid       # all full: replace the last open slot
    else:
        if not (0 <= slot_idx < n_open):
            return False
        if slot_idx < len(slots):
            slots[slot_idx] = sid
        else:
            slots.append(sid)   # gap-free pool: land in the next empty slot
    # keep pool within the open count
    del slots[n_open:]
    _sync_priority(sv)
    return True


def unequip_skill(hero: Hero, sid: str) -> bool:
    """Remove a skill from the common pool (primary can't be emptied — it always
       has a default). Returns True if something changed."""
    sv = getattr(hero, "skills_v2", None)
    if not sv:
        return False
    lo = sv["loadout"]
    slots = lo.get("slots", [])
    if sid in slots:
        slots.remove(sid)
        _sync_priority(sv)
        return True
    return False


def _sync_priority(sv: dict) -> None:
    """Keep `priority` mirroring the pool's slot order. After the rework the slot
       order IS the cast priority (▲/▼ move the skill within the pool), so there
       is no independent priority list to preserve — it always equals the live
       non-empty slots in order."""
    sv["priority"] = [s for s in sv["loadout"].get("slots", []) if s]


def move_priority(hero: Hero, sid: str, delta: int) -> bool:
    """Shift a pool skill up (-1) or down (+1) in the rotation priority AND in
       the slot order. Returns True if the order changed."""
    sv = getattr(hero, "skills_v2", None)
    if not sv:
        return False
    _sync_priority(sv)
    slots = sv["loadout"].get("slots", [])
    if sid not in slots:
        return False
    i = slots.index(sid)
    j = i + delta
    if not (0 <= j < len(slots)):
        return False
    slots[i], slots[j] = slots[j], slots[i]
    _sync_priority(sv)
    return True


def rank_progress(hero: Hero, sid: str) -> tuple[int, int, int]:
    """(rank, sxp_into_current_rank, sxp_needed_for_next). At the cap the last
       two are (0, 0) so a bar can render 'MAX'."""
    sv = getattr(hero, "skills_v2", None) or {}
    sxp = int(sv.get("sxp", {}).get(sid, 0))
    cap = AWAKENED_RANK_CAP if sid in sv.get("awakened", []) else RANK_CAP
    rank = rank_from_sxp(sxp, cap)
    if rank >= cap:
        return rank, 0, 0
    floor = _total_need(rank)
    ceil = _total_need(rank + 1)
    return rank, sxp - floor, ceil - floor


def talent_tiers_for(hero: Hero, sid: str) -> list[dict]:
    """A view of a skill's 4 talent tiers for the panel:
       [{rank, unlocked, chosen_idx, options:[{id,name,desc}]}]. `unlocked` is
       True once the skill's rank has reached the tier rank."""
    sk = load_skills_v2().get(sid)
    if sk is None:
        return []
    sv = getattr(hero, "skills_v2", None) or {}
    chosen = sv.get("talents", {}).get(sid, {})
    rank = skill_rank(hero, sid)
    opts_by_tier = _talent_options(sk)
    out: list[dict] = []
    for tier in load_talents_v2()["tiers"]:
        r = int(tier["rank"])
        opts = opts_by_tier.get(r, [])
        ci = chosen.get(str(r))
        out.append({
            "rank": r,
            "unlocked": rank >= r,
            "chosen_idx": int(ci) if ci is not None else None,
            "options": [{"id": o["id"], "name": o.get("name", o["id"]),
                         "desc": o.get("desc", "")} for o, _ in opts],
        })
    return out


def can_pick_talent(hero: Hero, sid: str, tier_rank: int) -> bool:
    """True if the skill's rank has reached this talent tier."""
    return skill_rank(hero, sid) >= tier_rank


def pick_talent(hero: Hero, sid: str, tier_rank: int, idx: int) -> bool:
    """Choose option `idx` for a skill's talent tier (gated on rank). Overwrites
       any previous pick for that tier. Returns True on success."""
    if not can_pick_talent(hero, sid, tier_rank):
        return False
    tiers = {t["rank"]: t for t in talent_tiers_for(hero, sid)}
    tier = tiers.get(tier_rank)
    if not tier or not (0 <= idx < len(tier["options"])):
        return False
    sv = hero.skills_v2
    sv.setdefault("talents", {}).setdefault(sid, {})[str(tier_rank)] = idx
    return True


def respec_talents(hero: Hero, sid: str) -> tuple[bool, str]:
    """Clear one skill's talent picks for `100 × hero level` gold (§3). Ranks and
       skill-xp are untouched. Returns (ok, message)."""
    sv = getattr(hero, "skills_v2", None)
    if not sv or not sv.get("talents", {}).get(sid):
        return False, "no talents to respec"
    cost = RESPEC_GOLD_PER_LEVEL * max(1, hero.level)
    if hero.gold < cost:
        return False, f"need {cost} gold"
    hero.gold -= cost
    sv["talents"][sid] = {}
    return True, f"respec: -{cost} gold"


def _refresh_aura_buffs(hero: Hero, skills: dict[str, SkillV2]) -> None:
    """SK-H3: fold every equipped AURA's params into real stats via game.buffs.
    Auras are always-on while equipped (no cooldown/duration), so their StatMods
    live in hero.buff_mods and core.recalc adds them alongside gear/passives.
    With the loadout rework an aura is just a skill occupying a common slot, so
    zero, one, or several auras may be present — all of them fold in together.
    Called every tick before the early-out so auras hold even with no mobs in
    range.

    Recalcs only when the set of slotted auras actually changes, so we don't
    thrash recalc every tick (cheap identity check on the aura-id tuple)."""
    sv = hero.skills_v2
    auras = tuple(_slotted_of_type(sv, skills, "aura"))
    prev = getattr(hero, "_active_aura", None)
    if auras == prev:
        return  # no change -> stats already reflect these auras
    hero._active_aura = auras
    mods: list = []
    flags: set = set()
    for aid in auras:
        sk = skills.get(aid)
        if sk:
            mods.extend(buffs.buff_mods_for(sk.params, hero.level))
            flags |= buffs.buff_flags_for(sk.params)
    hero.buff_mods = mods
    hero._buff_flags = flags
    hero.recalc()


def tick_skills_v2(hero: Hero, monsters: list[Monster], events: list[CombatEvent],
                   dt: float, rng: random.Random) -> None:
    """Rotation AI for one tick (drop-in replacement for game.skills.tick_skills)."""
    for sid in list(hero.skill_cds):
        if hero.skill_cds[sid] > 0:
            hero.skill_cds[sid] = max(0.0, hero.skill_cds[sid] - dt)
    if not hero.alive:
        return
    sv = getattr(hero, "skills_v2", None)
    if not sv or not sv.get("loadout"):
        return
    # SK-H1/H3: storm_herald's shock-spread (in combat_math._deal) needs the live
    # monster list on the hero; it was never assigned, so the keystone was dead.
    hero._monsters_ref = monsters
    skills = load_skills_v2()
    # SK-H3: aura stat bonuses are always-on while equipped — refresh them before
    # the "no monsters in range" early-out so the aura never blinks off.
    _refresh_aura_buffs(hero, skills)
    equipped = [s for s in _equipped_ids(sv) if s in skills]
    reach = max((skills[s].range_px for s in equipped), default=0.0)
    if reach <= 0 or not _alive_in_range(hero, monsters, reach):
        return
    # auras: passive presence flag (kept for keystone-style flag readers)
    for aura in _slotted_of_type(sv, skills, "aura"):
        hero.flags.add(aura)
    # utility self-cast (own cooldown, independent of the damage rotation)
    _try_utility(hero, monsters, events, rng, skills)
    # exactly one damage skill this tick, like the legacy engine
    _rotate(hero, monsters, events, rng, skills, reach)


# --------------------------------------------------------------------------- #
# skill-xp accrual (call from main._on_kill)
# --------------------------------------------------------------------------- #
def grant_skill_xp(hero: Hero, mob_xp: int) -> None:
    """§3: equipped skills += floor(mob_xp*0.6); other unlocked skills get 25%
       of that. Ranks are recomputed lazily via skill_rank."""
    sv = getattr(hero, "skills_v2", None)
    if not sv:
        return
    # E.1 up_sxp: scale skill xp by the permanent idle-upgrade bonus (single mult).
    ups = getattr(hero, "idle_upgrades", None)
    if ups:
        from game import idle_upgrades as _iu
        mob_xp = int(mob_xp * (1.0 + _iu.skill_xp_bonus_pct(ups) / 100.0))
    base = int(math.floor(mob_xp * SXP_EQUIPPED_MULT))
    leech = int(math.floor(mob_xp * SXP_EQUIPPED_MULT * SXP_LEECH_MULT))
    sxp = sv.setdefault("sxp", {})
    equipped = set(_equipped_ids(sv))
    for sid in equipped:
        sxp[sid] = sxp.get(sid, 0) + base
    for sid in sv.get("unlocked", []):
        if sid not in equipped:
            sxp[sid] = sxp.get(sid, 0) + leech


# --------------------------------------------------------------------------- #
# smoke test: python -m game.skills_v2
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    from game import classes

    rng = random.Random(7)
    for cid in ("warrior", "barbarian", "archer", "mage", "cleric"):
        hero = classes.make_hero(cid)
        hero.level = 30
        classes.apply_level_growth(hero)
        ensure_skills_v2(hero)
        # give every equipped skill some ranks so scaling shows
        for sid in _equipped_ids(hero.skills_v2):
            hero.skills_v2["sxp"][sid] = 3000
        monsters = [
            Monster(name=f"Mob{i}", stats=__import__("game.core", fromlist=["Stats"]).Stats(
                life=400, res_fire=20, res_cold=20, res_lightning=20, res_chaos=20),
                x=hero.x + 30 + i * 30, monster_id="mob", level=10, xp_reward=20)
            for i in range(6)
        ]
        monsters[0].is_boss = True
        for m in monsters:
            m.init_hp()
        events: list[CombatEvent] = []
        for _ in range(100):
            for m in monsters:  # keep the pack alive to observe casting
                if m.hp < m.max_hp * 0.2:
                    m.hp = m.max_hp
                    m.alive = True
            tick_skills_v2(hero, monsters, events, 0.05, rng)
        casts = [e for e in events if e.kind == "skill"]
        dmg = sum(e.value for e in events if e.kind == "damage")
        cast_ids = sorted({e.text for e in casts})
        print(f"{cid:9} lvl{hero.level}: casts={len(casts)} dmg={dmg:8.0f} "
              f"loadout={_equipped_ids(hero.skills_v2)} fired={cast_ids}")
    print("skills_v2 smoke OK")
