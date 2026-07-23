"""S.0 generator — Skills V2 data.

Deterministic (no RNG). Encodes the compact 80-skill spec from
`новый приколы/SKILLS_MECHANICS_V2.md` §6 plus the talent pools from §3, and
emits `data/skills_v2.json` + `data/skill_talents_v2.json`. Read-only from
engine code — it never imports game/* (rule: game/* <-> tools/* isolation).

Run:  python tools/gen_skills_v2.py
Self-validates: 16 skills/class, type quota 1P/9S/2A/2U/2Ult, unlock levels
match the canonical ladder, ids unique.

Loadout rework 21.07: the auto-attack is a SINGLE base attack per class (the L1
skill — Slash / Savage Chop / Quick Shot / Fire Bolt / Holy Bolt), keeping each
class's element. The 3 former "extra primaries" per class are now normal spender
skills with a cooldown (cd ≈ base%/20, clamped 4..8) — everything that is not
the base attack is a skill.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Canonical unlock ladder — same for every class (§2), applied positionally to
# the 16 skills listed per class below.
UNLOCK_LADDER = [1, 2, 4, 6, 8, 11, 14, 17, 20, 24, 28, 32, 36, 42, 48, 55]

# Per-rank growth (§3): +4% more skill damage, +2% secondary per rank, 1..20.
PER_RANK_MORE_PCT = 4
PER_RANK_SECONDARY_PCT = 2
RANK_CAP = 20


def _slug(name: str) -> str:
    s = name.lower().replace("'", "").replace("-", " ")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def _mana(kind: str, cd: float, base: int) -> int:
    """Deprecated (mana removed — idle-game vestige, audit M4/SK-M2). Kept as a
    no-op returning 0 so any stale caller stays valid; skills no longer emit a
    mana_cost field."""
    return 0


# Compact skill spec, per class, IN UNLOCK ORDER (index -> UNLOCK_LADDER).
# Fields: (name, kind, tags, damage_type, base_pct, cd_s, hits, effect, params)
# kind in {primary, spender, aura, utility, ultimate}
# damage_type in {phys, fire, cold, lightning, chaos}  (holy->phys, arcane/
#   poison->chaos, light->lightning; original element kept as a tag)
def _s(name, kind, tags, dt, base, cd, effect, params=None, hits=1):
    return {
        "name": name, "kind": kind, "tags": tags, "dt": dt,
        "base": base, "cd": cd, "hits": hits, "effect": effect,
        "params": params or {},
    }


CLASSES: dict[str, list[dict]] = {
    "warrior": [
        _s("Slash", "primary", ["phys", "melee"], "phys", 100, 0,
           "100% weapon damage."),
        _s("Cleave", "spender", ["phys", "melee", "aoe"], "phys", 170, 6,
           "Hits enemies in a frontal arc (up to 3).",
           {"aoe": True, "max_targets": 3, "shape": "arc"}),
        _s("War Cry", "utility", ["buff"], "phys", 0, 20,
           "Battle shout: +20% damage for 8s.",
           {"buff_dmg_pct": 20, "duration_s": 8}),
        _s("Shield Bash", "spender", ["phys", "stun"], "phys", 140, 8,
           "140% damage, stuns for 1.5s.", {"stun_s": 1.5}),
        _s("Precise Strike", "spender", ["phys", "crit"], "phys", 90, 5,
           "90% damage with +15% crit chance.", {"crit_chance_pct": 15}),
        _s("Shockwave", "spender", ["phys", "aoe"], "phys", 200, 10,
           "200% damage in a line.", {"aoe": True, "shape": "line"}),
        _s("Defiance", "aura", ["armor"], "phys", 0, 0,
           "Aura: +25% armor.", {"reserve_pct": 25, "armor_pct": 25}),
        _s("Sunder", "spender", ["phys", "bleed"], "phys", 85, 4,
           "85% damage, bleeds for 40% over 4s.",
           {"bleed_pct": 40, "bleed_s": 4}),
        _s("Blade Storm", "spender", ["phys", "aoe"], "phys", 45, 12,
           "Spin: 6x45% to all nearby.", {"aoe": True}, hits=6),
        _s("Second Wind", "utility", ["heal"], "phys", 0, 30,
           "Heal 25% of max life.", {"heal_pct": 25}),
        _s("Executioner's Swing", "spender", ["phys", "cull"], "phys", 110, 6,
           "110% damage, +50% vs enemies below 30% HP.",
           {"cull_bonus_pct": 50, "cull_threshold": 30}),
        _s("Earthquake", "spender", ["phys", "aoe", "dot"], "phys", 240, 14,
           "240% damage, leaves burning ground.",
           {"aoe": True, "ground_dot": True}),
        _s("Battle Standard", "aura", ["buff"], "phys", 0, 0,
           "Aura: +15% damage, +10% attack speed.",
           {"reserve_pct": 25, "buff_dmg_pct": 15, "buff_as_pct": 10}),
        _s("Rupture", "spender", ["bleed"], "phys", 150, 9,
           "150% damage, bleeds stack up to 3x.", {"bleed_stacks": 3}),
        _s("Avatar of War", "ultimate", ["phys"], "phys", 0, 75,
           "10s: +60% more damage, immune to stun.",
           {"duration_s": 10, "more_dmg_pct": 60, "immune_stun": True}),
        _s("Undying Rage", "ultimate", ["phys"], "phys", 0, 90,
           "8s: cannot die, +40% attack speed.",
           {"duration_s": 8, "cannot_die": True, "buff_as_pct": 40}),
    ],
    "barbarian": [
        _s("Savage Chop", "primary", ["phys", "melee"], "phys", 105, 0,
           "105% weapon damage."),
        _s("Leap Slam", "spender", ["phys", "move", "aoe"], "phys", 160, 8,
           "Leap to target, 160% AoE on landing.",
           {"aoe": True, "movement": True}),
        _s("Battle Roar", "utility", ["buff"], "phys", 0, 18,
           "Fear nearby foes, +15% damage.",
           {"buff_dmg_pct": 15, "duration_s": 8, "fear": True}),
        _s("Whirlwind", "spender", ["phys", "aoe"], "phys", 55, 10,
           "Spin 3s: 55% per hit to all nearby.",
           {"aoe": True, "channel_s": 3}),
        _s("Frenzy", "spender", ["phys", "melee"], "phys", 100, 5,
           "Builds Frenzy: +4% attack speed per stack (max 5).",
           {"stack_as_pct": 4, "max_stacks": 5}),
        _s("Bloodthirst", "spender", ["phys", "leech"], "phys", 180, 9,
           "180% damage, heal 30% of damage dealt.", {"leech_of_hit_pct": 30}),
        _s("Berserker Rage", "aura", ["buff"], "phys", 0, 0,
           "Aura: +20% attack speed, -10% armor.",
           {"reserve_pct": 25, "buff_as_pct": 20, "armor_pct": -10}),
        _s("Rampage", "spender", ["phys"], "phys", 95, 5,
           "95% damage; kills grant +10% move/attack speed 4s.",
           {"on_kill_as_pct": 10, "on_kill_ms_pct": 10, "duration_s": 4}),
        _s("Seismic Slam", "spender", ["phys", "aoe"], "phys", 220, 11,
           "220% damage in a cone.", {"aoe": True, "shape": "cone"}),
        _s("Ancestral Spirit", "utility", ["buff"], "phys", 0, 25,
           "A ghost copies your next spender.", {"echo_next": True}),
        _s("Skullsplitter", "spender", ["phys", "crit"], "phys", 130, 7,
           "130% slow swing, +30% crit multi.", {"crit_multi_pct": 30}),
        _s("Ancient Fury", "spender", ["phys", "aoe"], "phys", 50, 13,
           "6x50% to random nearby targets.", {"aoe": True, "random": True},
           hits=6),
        _s("Bloodlust", "aura", ["leech"], "phys", 0, 0,
           "Aura: 8% lifesteal.", {"reserve_pct": 25, "lifesteal_pct": 8}),
        _s("Decapitate", "spender", ["phys"], "phys", 320, 15,
           "320% damage to a single target.", {}),
        _s("Wrath of the Ancients", "ultimate", ["phys"], "phys", 0, 80,
           "Summon 3 ancestors for 12s.",
           {"duration_s": 12, "summon": 3}),
        _s("Undying Fury", "ultimate", ["phys", "aoe"], "phys", 0, 90,
           "10s: free Whirlwind, +30% more damage.",
           {"duration_s": 10, "more_dmg_pct": 30}),
    ],
    "archer": [
        _s("Quick Shot", "primary", ["phys", "proj"], "phys", 95, 0,
           "95% weapon damage.", {"projectile": True}),
        _s("Poison Arrow", "spender", ["proj", "dot", "poison"], "chaos", 120, 7,
           "120% + 60% poison over 5s.",
           {"projectile": True, "poison_pct": 60, "poison_s": 5}),
        _s("Mark for Death", "utility", ["debuff"], "phys", 0, 15,
           "Target takes +25% damage for 10s.",
           {"debuff_taken_pct": 25, "duration_s": 10}),
        _s("Split Arrow", "spender", ["phys", "proj", "aoe"], "phys", 70, 4,
           "70% to 3 targets.",
           {"projectile": True, "aoe": True, "max_targets": 3}),
        _s("Rain of Arrows", "spender", ["phys", "proj", "aoe"], "phys", 30, 10,
           "30% x8 over an area.", {"projectile": True, "aoe": True}, hits=8),
        _s("Explosive Arrow", "spender", ["phys", "proj", "aoe"], "phys", 190, 9,
           "190% blast.", {"projectile": True, "aoe": True}),
        _s("Hawk Eye", "aura", ["crit"], "phys", 0, 0,
           "Aura: +20% crit chance.",
           {"reserve_pct": 25, "crit_chance_pct": 20}),
        _s("Piercing Shot", "spender", ["phys", "proj"], "phys", 100, 5,
           "100% damage, pierces 2 targets.",
           {"projectile": True, "pierce": 2}),
        _s("Barrage", "spender", ["phys", "proj"], "phys", 45, 8,
           "45% x5 rapid shots.", {"projectile": True}, hits=5),
        _s("Caltrops", "utility", ["trap", "dot"], "phys", 0, 20,
           "Trap: slows and damages over time.",
           {"trap": True, "slow": True}),
        _s("Lightning Arrow", "spender", ["proj", "light"], "lightning", 90, 5,
           "90% + chains to 1 target.", {"projectile": True, "chain": 1}),
        _s("Snipe", "spender", ["phys", "proj"], "phys", 350, 14,
           "350% charged single shot.", {"projectile": True}),
        _s("Wind Dancer", "aura", ["buff"], "phys", 0, 0,
           "Aura: +15% attack speed, +10% evade.",
           {"reserve_pct": 25, "buff_as_pct": 15, "evade_pct": 10}),
        _s("Toxic Volley", "spender", ["proj", "dot", "poison", "aoe"], "chaos",
           110, 12, "Poison AoE, stacks up to 3x.",
           {"projectile": True, "aoe": True, "poison_stacks": 3}),
        _s("Arrow Storm", "ultimate", ["phys", "proj", "aoe"], "phys", 25, 75,
           "8s: rain 25% x many over the field.",
           {"projectile": True, "aoe": True, "duration_s": 8}),
        _s("Phantom Volley", "ultimate", ["phys", "proj"], "phys", 0, 90,
           "10s: clones fire alongside you.",
           {"projectile": True, "duration_s": 10, "clones": True}),
    ],
    "mage": [
        _s("Fire Bolt", "primary", ["fire", "proj"], "fire", 100, 0,
           "100% fire damage.", {"projectile": True}),
        _s("Ice Nova", "spender", ["cold", "aoe"], "cold", 150, 8,
           "150% AoE, chills enemies.", {"aoe": True, "chill": True}),
        _s("Frost Ward", "utility", ["buff"], "cold", 0, 25,
           "12s: +60% armour.",
           {"duration_s": 12, "buff_armor_inc": 60}),
        _s("Spark", "spender", ["light", "proj"], "lightning", 80, 4,
           "80% + 5% shock chance.", {"projectile": True, "shock_pct": 5}),
        _s("Fireball", "spender", ["fire", "aoe", "proj"], "fire", 200, 7,
           "200% fire blast.", {"projectile": True, "aoe": True}),
        _s("Chain Lightning", "spender", ["light", "proj"], "lightning", 130, 9,
           "130%, chains to 3 targets.", {"projectile": True, "chain": 3}),
        _s("Elemental Attunement", "aura", ["buff"], "fire", 0, 0,
           "Aura: +15% elemental damage.",
           {"reserve_pct": 25, "ele_dmg_pct": 15}),
        _s("Frost Bolt", "spender", ["cold", "proj"], "cold", 95, 5,
           "95% + slow.", {"projectile": True, "slow": True}),
        _s("Meteor", "spender", ["fire", "aoe"], "fire", 300, 13,
           "300% delayed impact.", {"aoe": True, "delayed": True}),
        _s("Time Warp", "utility", ["buff"], "cold", 0, 22,
           "8s: +25% cast speed.", {"duration_s": 8, "buff_as_pct": 25}),
        _s("Arcane Missile", "spender", ["arcane", "proj"], "chaos", 85, 4,
           "85% x2 arcane bolts.", {"projectile": True}, hits=2),
        _s("Frost Beam", "spender", ["cold"], "cold", 60, 12,
           "Channel 3s: 60% per tick.", {"channel_s": 3}),
        _s("Archmage", "aura", ["buff"], "fire", 0, 0,
           "Aura: +25% increased damage.",
           {"aura": True, "buff_damage_inc": 25}),
        _s("Arcane Orb", "spender", ["arcane", "aoe"], "chaos", 180, 11,
           "180% + pulses.", {"aoe": True, "pulses": True}),
        _s("Cataclysm", "ultimate", ["fire", "aoe"], "fire", 0, 85,
           "10s: meteors rain down.", {"duration_s": 10, "aoe": True}),
        _s("Mirror Image", "ultimate", ["arcane"], "chaos", 0, 90,
           "12s: 2 clones cast your primary.",
           {"duration_s": 12, "clones": 2}),
    ],
    "cleric": [
        _s("Holy Bolt", "primary", ["holy", "proj"], "fire", 95, 0,
           "95% holy damage.", {"projectile": True}),
        _s("Consecration", "spender", ["holy", "aoe", "dot"], "fire", 70, 10,
           "Holy ground: 70%/s for 5s.",
           {"aoe": True, "ground_dot": True, "dot_s": 5}),
        _s("Heal", "utility", ["heal"], "phys", 0, 18,
           "Heal 30% of max life.", {"heal_pct": 30}),
        _s("Smite", "spender", ["holy"], "fire", 110, 6,
           "110% slow swing."),
        _s("Holy Nova", "spender", ["holy", "aoe"], "fire", 160, 9,
           "160% burst around you.", {"aoe": True}),
        _s("Divine Hammer", "spender", ["holy", "stun"], "fire", 190, 10,
           "190% + stun 1s.", {"stun_s": 1}),
        _s("Blessing of Might", "aura", ["buff"], "phys", 0, 0,
           "Aura: +12% damage, +8% attack speed.",
           {"reserve_pct": 25, "buff_dmg_pct": 12, "buff_as_pct": 8}),
        _s("Radiant Lance", "spender", ["holy"], "fire", 100, 5,
           "100% damage, pierces.", {"pierce": 2}),
        _s("Wrath of Light", "spender", ["holy"], "fire", 90, 8,
           "90% x3 beams.", {}, hits=3),
        _s("Divine Shield", "utility", ["buff"], "phys", 0, 28,
           "6s: absorb up to 40% max life.",
           {"duration_s": 6, "absorb_pct": 40}),
        _s("Judgement", "spender", ["holy"], "fire", 105, 5,
           "105%; every 4th hit deals +100%.",
           {"combo_every": 4, "combo_bonus_pct": 100}),
        _s("Purifying Flame", "spender", ["holy", "fire"], "fire", 220, 12,
           "220% holy fire.", {}),
        _s("Sanctuary", "aura", ["buff"], "phys", 0, 0,
           "Aura: -12% damage taken, +1% life/s.",
           {"reserve_pct": 25, "dmg_taken_pct": -12, "life_regen_pct": 1}),
        _s("Celestial Strike", "spender", ["holy"], "fire", 280, 14,
           "280% to a single target.", {}),
        _s("Avatar of Light", "ultimate", ["holy"], "fire", 0, 80,
           "10s: +50% more damage, heal on hit.",
           {"duration_s": 10, "more_dmg_pct": 50, "heal_on_hit": True}),
        _s("Last Rites", "ultimate", ["holy", "aoe"], "fire", 500, 95,
           "Nuke: 500% to all on screen.", {"aoe": True, "all_screen": True}),
    ],
}

# Loadout unlocks (§2) — hero level at which each slot opens.
LOADOUT_SLOTS = {
    "primary": 1,
    "actives": [5, 12, 20],
    "aura": 16,
    "utility": 9,
    "ultimate": 30,
}

# Skill Tomes (§2)
TOME = {
    "base_drop_rate": 1 / 220,
    "pity_safe": True,
    "unlock_max_over_hero": 10,
    "dup_to_sxp_base": 500,  # x act
}

# Awakening (§3)
AWAKENING = {
    "req_rank": 20,
    "req_hero_level": 60,
    "gold_cost_base": 25000,  # x act
    "extra_ranks": 5,         # 21..25
    "more_per_rank_pct": 4,
    "extra_talent_tier_rank": 25,
}

# Rotation ranges (§5), px. Cleric uses medium.
RANGES = {"melee": 48, "medium": 140, "ranged": 260}
CLASS_RANGE = {
    "warrior": "melee", "barbarian": "melee", "cleric": "medium",
    "archer": "ranged", "mage": "ranged",
}


# ── Talent pools (§3) ────────────────────────────────────────────────────────
# tags_any (if present): entry only offered for skills carrying one of these
# tags. Untagged entries are always eligible. The engine (S.1) filters each
# pool by the skill's tags, then offers 3 per tier (rank 5/10/15/20); the
# rank-20 tier serves 1.5x "juiced" versions.
TALENT_POOLS = {
    "offense": [
        {"id": "off_more", "name": "Overpower", "desc": "+10% more damage",
         "mods": {"more_dmg_pct": 10}},
        {"id": "off_as", "name": "Frenzied", "desc": "+12% attack speed",
         "mods": {"attack_speed_pct": 12}},
        {"id": "off_cc", "name": "Deadly Aim", "desc": "+20% crit chance",
         "mods": {"crit_chance_pct": 20}},
        {"id": "off_cm", "name": "Brutality", "desc": "+30% crit multiplier",
         "mods": {"crit_multi_pct": 30}},
    ],
    "tempo": [
        {"id": "tmp_cd", "name": "Quickened", "desc": "-25% cooldown",
         "mods": {"cooldown_pct": -25}},
        {"id": "tmp_extra", "name": "Ricochet",
         "desc": "+1 chain / pierce / target",
         "mods": {"extra_targets": 1},
         "tags_any": ["aoe", "proj", "melee"]},
        {"id": "tmp_inc", "name": "Amplify", "desc": "+15% increased damage",
         "mods": {"inc_dmg_pct": 15}},
        {"id": "tmp_mana", "name": "Efficient", "desc": "-8% skill cooldown",
         "mods": {"cooldown_pct": -8}},
    ],
    "utility": [
        {"id": "utl_dur", "name": "Lingering", "desc": "+20% effect duration",
         "mods": {"duration_pct": 20}},
        {"id": "utl_leech", "name": "Bloodthirsty", "desc": "+10% lifesteal",
         "mods": {"lifesteal_pct": 10}, "tags_any": ["melee"]},
        {"id": "utl_projspd", "name": "Swift Shot",
         "desc": "+15% projectile speed",
         "mods": {"proj_speed_pct": 15}, "tags_any": ["proj"]},
        {"id": "utl_radius", "name": "Expansive", "desc": "+25% radius",
         "mods": {"radius_pct": 25}, "tags_any": ["aoe"]},
        {"id": "utl_ailment", "name": "Virulent", "desc": "+15% ailment chance",
         "mods": {"ailment_chance_pct": 15},
         "tags_any": ["dot", "bleed", "poison", "fire", "cold", "light"]},
    ],
}

# Which pool feeds which rank tier, and the juice multiplier for rank 20.
TALENT_TIERS = [
    {"rank": 5, "pool": "offense", "juice": 1.0},
    {"rank": 10, "pool": "tempo", "juice": 1.0},
    {"rank": 15, "pool": "utility", "juice": 1.0},
    {"rank": 20, "pool": "offense", "juice": 1.5},
]


def build_skills() -> dict:
    skills = []
    for class_id, spec in CLASSES.items():
        rng = CLASS_RANGE[class_id]
        for i, sk in enumerate(spec):
            unlock = UNLOCK_LADDER[i]
            sid = _slug(sk["name"])
            skills.append({
                "id": sid,
                "name": sk["name"],
                "class": class_id,
                "type": sk["kind"],
                "tags": sk["tags"],
                "damage_type": sk["dt"],
                "unlock_level": unlock,
                "cooldown_s": sk["cd"],
                "base_damage_pct": sk["base"],
                "hits": sk["hits"],
                "per_rank_more_pct": PER_RANK_MORE_PCT,
                "per_rank_secondary_pct": PER_RANK_SECONDARY_PCT,
                "rank_cap": RANK_CAP,
                "range_class": rng,
                "range_px": RANGES[rng],
                "effect": sk["effect"],
                "params": sk["params"],
            })
    return {
        "meta": {
            "kind": "skills_v2",
            "game": "Bar of Exile",
            "version": 1,
            "source": "новый приколы/SKILLS_MECHANICS_V2.md §6",
            "total_skills": len(skills),
            "per_class": 16,
            "unlock_ladder": UNLOCK_LADDER,
            "sxp_need_formula": "floor(40 * rank^1.7)",
            "rank_cap": RANK_CAP,
            "per_rank_more_pct": PER_RANK_MORE_PCT,
            "sxp_per_kill_equipped": 0.6,
            "sxp_leech_unequipped": 0.25,
            "loadout_slots": LOADOUT_SLOTS,
            "ranges_px": RANGES,
            "tome": TOME,
            "awakening": AWAKENING,
            "damage": "(base+Σflat) × (1+Σinc/100) × Π(1+more/100)",
        },
        "skills": skills,
    }


def build_talents() -> dict:
    return {
        "meta": {
            "kind": "skill_talents_v2",
            "game": "Bar of Exile",
            "version": 1,
            "source": "новый приколы/SKILLS_MECHANICS_V2.md §3",
            "rule": ("Per skill, each tier offers 3 options drawn from its "
                     "pool, filtered by the skill's tags (tags_any). Rank-20 "
                     "tier serves 1.5x juiced values. Pick 1 of 3."),
            "respec_gold": "100 * hero_level",
        },
        "tiers": TALENT_TIERS,
        "pools": TALENT_POOLS,
    }


# ── Validation ───────────────────────────────────────────────────────────────
def validate(skills_doc: dict) -> None:
    skills = skills_doc["skills"]
    quota = {"primary": 1, "spender": 9, "aura": 2, "utility": 2, "ultimate": 2}
    valid_dt = {"phys", "fire", "cold", "lightning", "chaos"}
    seen_ids = set()
    for class_id in CLASSES:
        cls = [s for s in skills if s["class"] == class_id]
        assert len(cls) == 16, f"{class_id}: {len(cls)} skills, want 16"
        counts: dict[str, int] = {}
        for s in cls:
            counts[s["type"]] = counts.get(s["type"], 0) + 1
        assert counts == quota, f"{class_id}: type quota {counts} != {quota}"
        got_unlocks = sorted(s["unlock_level"] for s in cls)
        assert got_unlocks == sorted(UNLOCK_LADDER), \
            f"{class_id}: unlock levels {got_unlocks} != ladder"
    for s in skills:
        assert s["id"] not in seen_ids, f"duplicate id {s['id']}"
        seen_ids.add(s["id"])
        assert s["damage_type"] in valid_dt, \
            f"{s['id']}: bad damage_type {s['damage_type']}"
        assert s["tags"], f"{s['id']}: no tags"
    assert len(skills) == 80, f"total {len(skills)} != 80"
    print(f"  validation OK: 80 skills, 16/class, quota 1P/9S/2A/2U/2Ult, "
          f"{len(seen_ids)} unique ids")


def main() -> None:
    skills_doc = build_skills()
    talents_doc = build_talents()
    validate(skills_doc)

    skills_path = DATA_DIR / "skills_v2.json"
    talents_path = DATA_DIR / "skill_talents_v2.json"
    with open(skills_path, "w", encoding="utf-8") as f:
        json.dump(skills_doc, f, ensure_ascii=False, indent=1)
    with open(talents_path, "w", encoding="utf-8") as f:
        json.dump(talents_doc, f, ensure_ascii=False, indent=1)
    print(f"  wrote {skills_path.name} ({len(skills_doc['skills'])} skills)")
    print(f"  wrote {talents_path.name} "
          f"({len(TALENT_POOLS)} pools, {len(TALENT_TIERS)} tiers)")


if __name__ == "__main__":
    main()
