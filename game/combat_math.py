"""Bar of Exile — shared combat math.

Step 2a (audit refactor): the damage/heal/targeting primitives used by BOTH the
legacy skill effects (game.skills) and the Skills V2 engine (game.skills_v2) were
extracted here VERBATIM from game.skills, with no behavior change. This breaks the
old situation where skills_v2 imported these from the legacy skills module (which
blocked deleting skills.py — audit SK-H4).

Step 2b (separate commit) will unify crit/evasion/leech/kill-hooks across the
auto-attack path (combat.py) and the skill path by having both call one shared
helper that lives here. This module imports only core + ailments (no combat, no
skills, no skills_v2) so it can be imported anywhere without a cycle.
"""
from __future__ import annotations

import json
from pathlib import Path

from game.core import CombatEvent, DamageType, Hero, Monster
from game import ailments

SKILL_REACH = 260.0

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_socket_passives: dict[str, dict] | None = None
MAX_SKILL_SOCKETS = 3

CDR_CAP = 60.0  # cooldown_reduction hard cap, %

# --------------------------------------------------------------------------- #
# Step 2b — SHARED post-damage handling (crit / leech / kill-hooks / cull).
# Both the auto-attack path (combat.CombatSystem) and the skill path (this
# module's _deal) route through these so a stat works identically whether it
# comes from a swing or a cast. Constants were the private tuning of combat.py;
# they live here now as the single source and combat.py imports them.
# --------------------------------------------------------------------------- #
LEECH_CAP_PCT = 12.0        # life_leech capped at 12% of a hit's damage
OVERHEAL_CAP_FRAC = 0.20    # ck_overheal temp-HP buffer cap = 20% max life
OVERHEAL_DECAY_FRAC = 0.02  # ck_overheal temp-HP decay per second
KILL_HEAL_FRAC = 0.02       # ck_kill_heal: fraction of max life restored per kill
CULL_FRAC = 0.10            # ck_cull_10: cull threshold for normal monsters
CULL_FRAC_BOSS = 0.05       # ck_cull_10: bosses cullable at a lower fraction

# Evasion (audit H1): a defensive layer that was a no-op — the stat existed and
# was granted by gear/affixes/classes but nothing ever rolled it. Model it as a
# flat dodge chance with diminishing returns, HARD-CAPPED at EVASION_CHANCE_CAP
# so a stacked archer can't reach 100% (per user directive B: cap immediately).
EVASION_CHANCE_CAP = 75.0   # max % chance to fully avoid an incoming hit
EVASION_SCALE = 250.0       # evasion needed for ~half of the cap (see curve below)


def evasion_chance(evasion: float) -> float:
    """% chance to dodge a hit, from an evasion rating. Smooth diminishing-returns
    curve evasion/(evasion+SCALE) scaled to the cap, so early points feel good and
    it never exceeds EVASION_CHANCE_CAP. evasion<=0 -> 0."""
    if evasion <= 0:
        return 0.0
    return EVASION_CHANCE_CAP * evasion / (evasion + EVASION_SCALE)


def rolls_dodge(hero: Hero, rng) -> bool:
    """True if the hero dodges an incoming hit this roll (audit H1). Capped."""
    if rng is None:
        return False
    return rng.uniform(0, 100) < evasion_chance(hero.stats.evasion)


def crit_mult(hero: Hero, rng, ck_fifth: bool = False,
              bonus_chance: float = 0.0, bonus_multi: float = 0.0) -> tuple[bool, float]:
    """Shared crit roll. Returns (is_crit, damage_mult).

    ``ck_fifth`` (auto-attack only) forces a crit on every 5th hero hit via the
    runtime counter ``hero._ck_hit_counter``; otherwise a normal crit_chance%
    roll applies. Skills pass ck_fifth=False — the fifth-shot keystone is an
    auto-attack identity — but still crit off crit_chance/crit_multi (audit H2).

    ``bonus_chance`` / ``bonus_multi`` are per-cast additions (SK-H2 skill
    talents off_cc / off_cm) folded on top of the hero's base crit stats."""
    s = hero.stats
    is_crit = False
    if ck_fifth and "ck_fifth_shot" in hero.flags:
        cnt = getattr(hero, "_ck_hit_counter", 0) + 1
        setattr(hero, "_ck_hit_counter", cnt)
        if cnt % 5 == 0:
            is_crit = True
    if not is_crit and rng is not None:
        is_crit = rng.uniform(0, 100) < s.crit_chance + bonus_chance
    return is_crit, ((s.crit_multi + bonus_multi) / 100.0 if is_crit else 1.0)


def apply_leech(hero: Hero, gain: float) -> None:
    """Add life to the hero: fill hp to max first; with ck_overheal the overflow
    spills into a temp-HP buffer (capped OVERHEAL_CAP_FRAC of max life) that
    decays over time and absorbs incoming damage. Shared by auto-attack + skills."""
    if gain <= 0:
        return
    if hero.hp < hero.max_hp:
        room = hero.max_hp - hero.hp
        hero.hp = min(hero.max_hp, hero.hp + gain)
        gain -= room
    if gain > 0 and "ck_overheal" in hero.flags and hero.max_hp > 0:
        cap = OVERHEAL_CAP_FRAC * hero.max_hp
        temp = getattr(hero, "_ck_temp_hp", 0.0)
        setattr(hero, "_ck_temp_hp", min(cap, temp + gain))


def kill_heal(hero: Hero) -> None:
    """ck_kill_heal: a kill (by swing OR cast) restores KILL_HEAL_FRAC max life."""
    if "ck_kill_heal" in hero.flags and hero.alive and hero.max_hp > 0:
        hero.hp = min(hero.max_hp, hero.hp + KILL_HEAL_FRAC * hero.max_hp)


def load_socket_passives() -> dict[str, dict]:
    """id -> passive def, from data/skill_socket_passives.json."""
    global _socket_passives
    if _socket_passives is None:
        try:
            with open(_DATA_DIR / "skill_socket_passives.json", encoding="utf-8") as f:
                raw = json.load(f)
            _socket_passives = {p["id"]: p for p in raw.get("passives", [])}
        except (OSError, ValueError, KeyError):
            _socket_passives = {}
    return _socket_passives


def _alive_in_range(hero: Hero, monsters: list[Monster], radius: float) -> list[Monster]:
    return [m for m in monsters if m.alive and abs(m.x - hero.x) <= radius]


def _deal(hero: Hero, mob: Monster, pct: float, dtype: DamageType,
          events: list[CombatEvent], is_area: bool = False,
          ailment: tuple[str, float] | None = None,
          rng=None) -> None:
    s = hero.stats
    base = (s.damage_min + s.damage_max) / 2 + getattr(s, f"added_{dtype.value}", 0.0)
    res = getattr(mob.stats, f"res_{dtype.value}", 0.0)
    dmg = max(0.0, base * pct * (1 - res / 100))
    # v3 idle stats: global / area / boss %-increased damage
    dmg *= 1 + s.damage_inc / 100.0
    if is_area:
        dmg *= 1 + s.aoe_damage_inc / 100.0
    if mob.is_boss:
        dmg *= 1 + s.boss_damage_inc / 100.0
    if "plaguebearer" in hero.flags:
        dmg *= 1 - ailments.PLAGUEBEARER_DIRECT_PENALTY
    dmg *= ailments.damage_taken_mult(mob)
    # socketed skill passive: flat damage bonus + leech accumulation for this cast
    ctx = getattr(hero, "_skill_ctx", None)
    if ctx is not None:
        dmg *= 1 + ctx["damage_inc"] / 100.0
        ctx["dealt"] += dmg
    # 2b: skills crit too (audit H2). Only when an rng is supplied — legacy
    # effects that call _deal without one keep their old deterministic behaviour.
    # SK-H2: skill talents can add crit chance/multi for this cast via ctx.
    is_crit = False
    if rng is not None:
        bc = ctx.get("crit_chance", 0.0) if ctx else 0.0
        bm = ctx.get("crit_multi", 0.0) if ctx else 0.0
        is_crit, cmult = crit_mult(hero, rng, ck_fifth=False,
                                   bonus_chance=bc, bonus_multi=bm)
        dmg *= cmult
    mob.hp -= dmg
    events.append(CombatEvent("crit" if is_crit else "damage",
                              x=mob.x, value=dmg, dtype=dtype))
    # v3.1: ailment chances come from SKILLS only
    if ailment is not None and rng is not None and mob.alive:
        kind, chance = ailment
        hit = ailments.try_apply_on_hit(
            mob, dmg, dtype, {f"{kind}_chance_pct": chance},
            {"dot_damage_inc_pct": s.dot_damage_inc}, hero.flags, rng)
        if "shock" in hit and "storm_herald" in hero.flags:
            ailments.spread_shock(mob, getattr(hero, "_monsters_ref", []))
    # 2b: leech on skill damage (audit M2) — same cap/overheal as auto-attack.
    # SK-H2: talent lifesteal_pct (utl_leech) adds to the hit's leech via ctx.
    leech_pct = min(s.life_leech, LEECH_CAP_PCT)
    if ctx is not None and ctx.get("lifesteal", 0.0):
        leech_pct = min(leech_pct + ctx["lifesteal"], LEECH_CAP_PCT)
    gain = dmg * leech_pct / 100.0
    # ck_cull_10: finish a target left below the cull threshold after this hit
    # (audit M1 — skills cull too now). Bosses cullable at the lower fraction.
    if "ck_cull_10" in hero.flags and mob.alive and mob.max_hp > 0:
        frac = CULL_FRAC_BOSS if mob.is_boss else CULL_FRAC
        if mob.hp <= mob.max_hp * frac:
            mob.hp = 0.0
    if mob.hp <= 0 and mob.alive:
        mob.alive = False
        mob.anim = "dead"
        mob.anim_t = 0.0  # restart the corpse fade timer (combat._set_anim parity)
        events.append(CombatEvent("kill", x=mob.x, text=mob.name))
        gain += s.life_on_kill
        kill_heal(hero)  # ck_kill_heal on skill kills too (audit M1)
    if gain > 0:
        apply_leech(hero, gain)


def _raw_heal(hero: Hero, amount: float, events: list[CombatEvent]) -> None:
    healed = min(hero.max_hp - hero.hp, amount)
    if healed <= 0:
        return
    hero.hp += healed
    events.append(CombatEvent("heal", x=hero.x, value=healed))


def _heal(hero: Hero, pct: float, events: list[CombatEvent]) -> None:
    # v3: healing_inc scales every heal received
    amount = hero.max_hp * pct * (1 + hero.stats.healing_inc / 100.0)
    # keystone: vampiric_pact "Healing from other sources halved"
    # (leech doubling: TODO, leech stat not wired into combat yet)
    if "vampiric_pact" in hero.flags:
        amount /= 2
    healed = min(hero.max_hp - hero.hp, amount)
    hero.hp += healed
    events.append(CombatEvent("heal", x=hero.x, value=healed))
