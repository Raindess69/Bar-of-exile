"""Bar of Exile — shared core. All game/* modules import types ONLY from here."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

TICK_DT = 0.05  # 20 TPS
RES_CAP = 75.0
MF_CAP = 150.0  # spec E.3: item_rarity (magic find) hard cap, %
IQ_CAP = 100.0  # spec E.3: item_quantity hard cap, % (multiplies drop chance)


class DamageType(str, Enum):
    PHYS = "phys"
    FIRE = "fire"
    COLD = "cold"
    LIGHTNING = "lightning"
    CHAOS = "chaos"


class Rarity(str, Enum):
    # 10-tier ladder (data/rarity_ladder.json). The four classic tiers keep their
    # exact string values so every existing save round-trips unchanged; SCRAP /
    # EXALTED / SET / MYTHIC are the new enum members. RELIC and PRIMAL are NOT
    # rarities — they are Item.modifier overlays on a UNIQUE / MYTHIC base (spec:
    # "модификатор поверх уников, не строки лут-таблицы"), so weights can't break.
    SCRAP = "scrap"        # tier 1: 0 affixes, salvage fodder
    NORMAL = "normal"      # tier 2: 0 affixes
    MAGIC = "magic"        # tier 3: 1-2 affixes
    RARE = "rare"          # tier 4: 3-6 affixes (unchanged contract)
    EXALTED = "exalted"    # tier 5: 4-6 affixes, tier-floor 3, +1 implicit
    SET = "set"            # tier 6: fixed green set piece (game.sets)
    UNIQUE = "unique"      # tier 7: fixed hand-made (game.uniques)
    MYTHIC = "mythic"      # tier 9: fixed uber (game.mythics)


# Item.modifier overlay codes (tiers 8 & 10). Empty string = no overlay.
MOD_NONE = ""
MOD_RELIC = "relic"    # tier 8: foil unique — rolls x[1.15,1.30] + 1 rare affix
MOD_PRIMAL = "primal"  # tier 10: perfect roll on a unique/mythic, star_floor 3


RARITY_COLORS = {
    Rarity.SCRAP: "#6b6b6b",
    Rarity.NORMAL: "#c8c8c8",
    Rarity.MAGIC: "#8888ff",
    Rarity.RARE: "#ffff77",
    Rarity.EXALTED: "#b06af5",
    Rarity.SET: "#5fce62",
    Rarity.UNIQUE: "#af6025",
    Rarity.MYTHIC: "#e0483a",
}

# Ladder order for floors / sorting / lifts. Index = ascending desirability.
# RELIC/PRIMAL are overlays, not entries here.
RARITY_LADDER = [Rarity.SCRAP, Rarity.NORMAL, Rarity.MAGIC, Rarity.RARE,
                 Rarity.EXALTED, Rarity.SET, Rarity.UNIQUE, Rarity.MYTHIC]
RARITY_RANK = {r: i for i, r in enumerate(RARITY_LADDER)}


class Slot(str, Enum):
    WEAPON = "weapon"
    HELMET = "helmet"
    BODY = "body"
    GLOVES = "gloves"
    BOOTS = "boots"
    BELT = "belt"
    AMULET = "amulet"
    RING = "ring"


# Canonical stat names (keys in Stats and in affixes):
# life, damage_min, damage_max, attack_speed, crit_chance, crit_multi,
# armor, evasion, res_fire, res_cold, res_lightning, res_chaos, move_speed,
# life_regen, added_fire, added_cold, added_lightning, added_chaos
@dataclass
class Stats:
    life: float = 50.0
    damage_min: float = 2.0
    damage_max: float = 5.0
    attack_speed: float = 1.0        # attacks per second
    crit_chance: float = 5.0         # %
    crit_multi: float = 150.0        # %
    armor: float = 0.0
    evasion: float = 0.0
    res_fire: float = 0.0
    res_cold: float = 0.0
    res_lightning: float = 0.0
    res_chaos: float = 0.0
    move_speed: float = 60.0         # px/sec along the strip
    life_regen: float = 0.0          # hp/sec
    added_fire: float = 0.0          # flat elemental damage added to attacks
    added_cold: float = 0.0
    added_lightning: float = 0.0
    added_chaos: float = 0.0
    # v3 idle stats (all additive %, flat bucket; 0 = no effect)
    damage_inc: float = 0.0          # global %-increased damage (attacks+skills)
    aoe_damage_inc: float = 0.0      # area skills only
    boss_damage_inc: float = 0.0     # vs is_boss targets
    dot_damage_inc: float = 0.0      # ailment DoT scaler
    healing_inc: float = 0.0         # all heals received
    cast_speed_inc: float = 0.0      # spell-kind skill cooldowns
    cooldown_reduction: float = 0.0  # all skill cooldowns (cap CDR_CAP)
    life_leech: float = 0.0          # % of hero hit damage returned as life
    life_on_kill: float = 0.0        # flat life per kill
    gold_find: float = 0.0           # % more gold from kills
    item_rarity: float = 0.0         # shifts drop rarity (added to magic find)
    item_quantity: float = 0.0       # E.3: % more drops (multiplies drop chance, cap IQ_CAP)
    xp_gain_inc: float = 0.0         # % increased experience

    def copy(self) -> "Stats":
        return Stats(**vars(self))


# stats whose flat values are percentages ("+24% to Fire Resistance")
_PERCENT_FLAT = frozenset({
    "crit_chance", "crit_multi",
    "res_fire", "res_cold", "res_lightning", "res_chaos",
})


@dataclass
class StatMod:
    stat: str            # Stats field name
    flat: float = 0.0
    inc: float = 0.0     # increased % (additive bucket)
    more: float = 0.0    # more/less % (multiplicative bucket; keystones)

    def describe(self) -> str:
        if self.flat:
            v = int(self.flat) if self.flat == int(self.flat) else round(self.flat, 1)
            pct = "%" if self.stat in _PERCENT_FLAT else ""
            return f"+{v}{pct} to {STAT_EN.get(self.stat, self.stat)}"
        if self.inc:
            return f"{int(self.inc)}% increased {STAT_EN.get(self.stat, self.stat)}"
        word = "more" if self.more >= 0 else "less"
        return f"{int(abs(self.more))}% {word} {STAT_EN.get(self.stat, self.stat)}"


STAT_EN = {
    "life": "Life",
    "damage_min": "minimum Damage", "damage_max": "maximum Damage",
    "attack_speed": "Attack Speed", "crit_chance": "Critical Strike Chance",
    "crit_multi": "Critical Strike Multiplier", "armor": "Armour", "evasion": "Evasion",
    "res_fire": "Fire Resistance", "res_cold": "Cold Resistance",
    "res_lightning": "Lightning Resistance", "res_chaos": "Chaos Resistance",
    "move_speed": "Movement Speed", "life_regen": "Life Regeneration per second",
    "added_fire": "Fire Damage", "added_cold": "Cold Damage",
    "added_lightning": "Lightning Damage", "added_chaos": "Chaos Damage",
    "damage_inc": "Damage", "aoe_damage_inc": "Area Damage",
    "boss_damage_inc": "Damage against Bosses",
    "dot_damage_inc": "Damage over Time", "healing_inc": "Healing",
    "cast_speed_inc": "Cast Speed", "cooldown_reduction": "Cooldown Recovery",
    "life_leech": "Life Leech", "life_on_kill": "Life gained on Kill",
    "gold_find": "Gold Find", "item_rarity": "Item Rarity",
    "item_quantity": "Item Quantity",
    "xp_gain_inc": "Experience Gained",
}


def apply_mods(base: Stats, mods: list[StatMod]) -> Stats:
    """(base + Σflat) × (1 + Σinc/100) × Π(1 + more/100)"""
    out = base.copy()
    flats: dict[str, float] = {}
    incs: dict[str, float] = {}
    mores: dict[str, float] = {}
    for m in mods:
        flats[m.stat] = flats.get(m.stat, 0.0) + m.flat
        incs[m.stat] = incs.get(m.stat, 0.0) + m.inc
        if m.more:
            mores[m.stat] = mores.get(m.stat, 1.0) * (1 + m.more / 100)
    for stat in set(flats) | set(incs) | set(mores):
        if not hasattr(out, stat):
            continue  # display-only stat (no engine support yet, e.g. v2 chance mods)
        cur = getattr(out, stat)
        val = (cur + flats.get(stat, 0.0)) * (1 + incs.get(stat, 0.0) / 100)
        setattr(out, stat, val * mores.get(stat, 1.0))
    for r in ("res_fire", "res_cold", "res_lightning", "res_chaos"):
        setattr(out, r, min(getattr(out, r), RES_CAP))
    return out


# --- keystone ops (interpreted AFTER apply_mods, in Hero.recalc) ---
# Supported here: "set" (stat_final -> hard override), "flag" (boolean build flag),
# "convert" (damage conversion, consumed by combat). "add"/"more" are translated
# into StatMods by game.tree before they reach recalc. Unknown ops are kept but ignored.
def apply_ops(stats: Stats, ops: list[dict], flags: set[str]) -> Stats:
    for op in ops:
        kind = op.get("op")
        if kind == "set":
            stat = str(op.get("stat", ""))
            if stat.endswith("_final"):
                stat = stat[:-6]
            if hasattr(stats, stat):
                setattr(stats, stat, float(op.get("value", 0)))
        elif kind == "flag":
            if op.get("value", True):
                flags.add(str(op.get("stat", "")))
    return stats


@dataclass
class Affix:
    id: str
    name: str            # "Tyrannical"
    is_prefix: bool
    tier: int            # T1 is best
    mods: list[StatMod]
    lines: list[str] = field(default_factory=list)  # pre-rendered display (v2 roller); empty -> describe mods
    # E.5 greater-affix: 0 = normal, 1-4 = ★ tiers. A star scales this line's
    # rolled magnitude above roll_max (breaks the tier cap). Set by the roller
    # via game.greater_affix; NOT influenced by magic find. Serialized in saves.
    stars: int = 0


@dataclass
class Item:
    base_id: str
    base_name: str       # "Long Sword"
    slot: Slot
    rarity: Rarity
    ilvl: int
    req_level: int = 1
    name: str = ""       # full name with affixes / unique name
    class_req: tuple[str, ...] = ()  # empty = usable by all classes
    implicit: list[StatMod] = field(default_factory=list)
    affixes: list[Affix] = field(default_factory=list)
    # weapons: base damage is stored in implicit via damage_min/damage_max mods
    # Corruption (cube rework step 1): level 0..3, and the over-limit lines it
    # grants. corrupted_lines are ordinary Affixes (live gear pool, via statmap)
    # kept SEPARATE from `affixes` so they render red and bypass prefix/suffix
    # limits — but they still count in recalc through all_mods().
    corruption: int = 0
    corrupted_lines: list[Affix] = field(default_factory=list)
    # 10-tier ladder overlay (tiers 8 & 10): "" | MOD_RELIC | MOD_PRIMAL. A
    # modifier does NOT change rarity — it decorates a UNIQUE/MYTHIC base with a
    # foil/rainbow frame and stat boosts already baked into the affixes at roll
    # time. Serialized (omitted when empty for back-compat with old saves).
    modifier: str = ""

    def all_mods(self) -> list[StatMod]:
        mods = list(self.implicit)
        for a in self.affixes:
            mods.extend(a.mods)
        for a in self.corrupted_lines:
            mods.extend(a.mods)
        return mods

    def display_name(self) -> str:
        return self.name or self.base_name


@dataclass
class Entity:
    name: str
    stats: Stats
    x: float = 0.0
    hp: float = 0.0
    max_hp: float = 0.0
    alive: bool = True
    attack_cd: float = 0.0
    facing: int = 1      # 1 right, -1 left
    anim: str = "walk"   # walk/attack/hurt/dead — for the renderer
    anim_t: float = 0.0

    def init_hp(self) -> None:
        self.max_hp = self.stats.life
        self.hp = self.max_hp


@dataclass
class Monster(Entity):
    monster_id: str = ""
    level: int = 1
    xp_reward: int = 5
    damage_type: DamageType = DamageType.PHYS
    is_boss: bool = False
    loot_bonus: float = 0.0


@dataclass
class Hero(Entity):
    class_id: str = "berserker"
    level: int = 1
    xp: int = 0
    gold: int = 0
    base_stats: Stats = field(default_factory=Stats)  # class base + growth, WITHOUT gear
    equipment: dict[str, Item | None] = field(default_factory=dict)  # key = Slot.value
    inventory: list[Item] = field(default_factory=list)
    stash: list[Item] = field(default_factory=list)  # shared storage, NOT counted in recalc
    skill_cds: dict[str, float] = field(default_factory=dict)
    active_skills: list[str] = field(default_factory=list)  # selected skill ids (max 3 slots)
    skill_talents: dict[str, str] = field(default_factory=dict)  # tier -> chosen talent id
    # per-skill socketed passives: skill_id -> {socket_index: passive_id}. Named
    # skill_runes so a future rune system can reuse the same save field.
    skill_runes: dict[str, dict[str, str]] = field(default_factory=dict)
    # Skills V2 (Gem Souls) state — unlocked/loadout/priority/sxp/talents/
    # keystones/awakened/tomes_read. Seeded by game.skills_v2.ensure_skills_v2;
    # serialized at SAVE_VERSION 5 (S.2). Empty dict = not yet seeded.
    skills_v2: dict = field(default_factory=dict)
    damage_type: DamageType = DamageType.PHYS
    passives: list[str] = field(default_factory=list)  # allocated passive node ids (serialized)
    bonus_points: int = 0  # extra passive points from act-boss first kills (serialized)
    # Class Points (S.4 rework): separate currency for the class sub-trees, earned
    # ONLY from act-boss first kills (PoE-lab style). This holds the boss ids that
    # have already granted CP (dedup guard). available_cp = Σgrants − Σallocated ck.
    # Serialized. Allocated ck-nodes live in `passives` alongside normal nodes.
    class_point_sources: list[str] = field(default_factory=list)
    # rebuilt at runtime by the passive tree module (game.tree), NOT serialized:
    passive_mods: list[StatMod] = field(default_factory=list)
    passive_ops: list[dict] = field(default_factory=list)   # keystone set/flag/convert ops
    flags: set[str] = field(default_factory=set)            # build flags from tree keystones
    # SK-H3 active auras + timed buffs, rebuilt each tick by game.skills_v2 from
    # the equipped auras and cast buff skills. NOT serialized (re-derived on load).
    buff_mods: list[StatMod] = field(default_factory=list)
    # covenant_of_the_hunt: StatMods stolen from slain Rare mobs, each with its
    # own expiry. Rebuilt/ticked by game.combat; folded into recalc. NOT
    # serialized (transient 20s buffs, re-earned in play).
    _stolen_mods: list[StatMod] = field(default_factory=list)
    # E.1 permanent gold-bought idle upgrades: {upgrade_id: level}. Serialized.
    # Effects fold into existing aggregates in recalc (gold_find / xp_gain_inc);
    # up_sxp / up_offline are read directly by skills_v2 / save. Empty = none bought.
    idle_upgrades: dict = field(default_factory=dict)
    # E.2 how many stash tabs the hero has unlocked (starts at 1). Serialized.
    stash_tabs_owned: int = 1

    def recalc(self) -> None:
        mods: list[StatMod] = []
        for it in self.equipment.values():
            if it:
                mods.extend(it.all_mods())
        mods.extend(self.passive_mods)
        mods.extend(self.buff_mods)  # SK-H3: aura / timed-buff stat bonuses
        mods.extend(self._stolen_mods)  # covenant_of_the_hunt: timed rare-mob steal
        # Unique special mechanics (game.unique_specials): stat specials fold in
        # here as ordinary StatMods; flag specials are added to self.flags below.
        # Lazy import — unique_specials -> uniques -> core would be circular.
        from game import unique_specials as _us
        _special_ids = _us.active_special_ids(self)
        mods.extend(_us.mods_for(_special_ids))
        # Tier 6 set bonuses: equipped pieces of the same set grant escalating
        # StatMods at 2/3/4 pieces. Lazy import (game.sets -> core would loop);
        # defensive so a missing module never breaks recalc.
        try:
            from game import sets as _sets
            equipped = [it for it in self.equipment.values() if it]
            mods.extend(_sets.set_bonus_mods(equipped))
        except Exception:
            pass
        keep_ratio = self.hp / self.max_hp if self.max_hp > 0 else 1.0
        self.flags = set()
        self.stats = apply_ops(apply_mods(self.base_stats, mods), self.passive_ops, self.flags)
        self.flags |= _us.flags_for(_special_ids)
        # E.1: fold permanent idle-upgrade bonuses into the EXISTING aggregates
        # (single-source, no new raw keys). up_gold -> gold_find (online+offline),
        # up_xp -> xp_gain_inc. up_sxp/up_offline are read at their own call sites.
        ups = getattr(self, "idle_upgrades", None)
        if ups:
            from game import idle_upgrades as _iu
            self.stats.gold_find += _iu.gold_find_bonus_pct(ups)
            self.stats.xp_gain_inc += _iu.xp_gain_bonus_pct(ups)
        # spec E.3: magic find hard cap (mirrors RES_CAP for resists)
        if self.stats.item_rarity > MF_CAP:
            self.stats.item_rarity = MF_CAP
        # spec E.3: item quantity hard cap (100% -> at most double drop chance)
        if self.stats.item_quantity > IQ_CAP:
            self.stats.item_quantity = IQ_CAP
        elif self.stats.item_quantity < 0.0:
            self.stats.item_quantity = 0.0
        # SK-H3: buff flags (immune_stun / cannot_die) survive the flags reset.
        self.flags |= getattr(self, "_buff_flags", set())
        self.max_hp = self.stats.life
        self.hp = self.max_hp * keep_ratio


# --- combat events (for rendering damage numbers etc.) ---
@dataclass
class CombatEvent:
    kind: str            # "damage" | "crit" | "kill" | "heal" | "levelup" | "loot"
    x: float
    value: float = 0.0
    dtype: DamageType = DamageType.PHYS
    text: str = ""
    origin: float | None = None  # caster x for travelling projectile VFX (e.g. fireball)
    target: object | None = None  # monster the projectile VFX homes onto / explodes on
    class_id: str = ""   # caster class, so the renderer can pick its base projectile


DTYPE_COLORS = {
    DamageType.PHYS: "#ffffff",
    DamageType.FIRE: "#ff6633",
    DamageType.COLD: "#66ccff",
    DamageType.LIGHTNING: "#ffee55",
    DamageType.CHAOS: "#cc66ff",
}


def roll(a: float, b: float, rng: random.Random | None = None) -> float:
    r = rng or random
    return r.uniform(a, b)


if __name__ == "__main__":
    base = Stats()
    mods = [StatMod("life", flat=20), StatMod("life", inc=10), StatMod("res_fire", flat=90)]
    s = apply_mods(base, mods)
    assert s.life == (50 + 20) * 1.1, s.life
    assert s.res_fire == RES_CAP
    print(StatMod("life", flat=12).describe())
    print(StatMod("attack_speed", inc=14).describe())
    print(StatMod("res_fire", flat=24).describe())
    h = Hero(name="Test", stats=base.copy(), base_stats=base.copy())
    h.init_hp()
    h.recalc()
    assert h.max_hp == base.life
    h.passive_mods = [StatMod("life", flat=30)]
    h.recalc()
    assert h.max_hp == base.life + 30, h.max_hp
    # stash items must NOT affect stats
    stashed = Item(base_id="x", base_name="X", slot=Slot.RING, rarity=Rarity.NORMAL,
                   ilvl=1, class_req=("warrior",), implicit=[StatMod("life", flat=100)])
    h.stash.append(stashed)
    h.recalc()
    assert h.max_hp == base.life + 30, h.max_hp
    assert stashed.class_req == ("warrior",) and Item("y", "Y", Slot.RING, Rarity.NORMAL, 1).class_req == ()
    # more-bucket: (50+30) * 1.0 * 1.5 = 120
    h.passive_mods = [StatMod("life", flat=30), StatMod("life", more=50)]
    h.recalc()
    assert h.max_hp == (base.life + 30) * 1.5, h.max_hp
    # more stacks multiplicatively: 1.5 * 0.5 = 0.75
    h.passive_mods = [StatMod("life", more=50), StatMod("life", more=-50)]
    h.recalc()
    assert abs(h.max_hp - base.life * 0.75) < 1e-9, h.max_hp
    # keystone ops: set armor_final=0 + flag
    h.passive_mods = [StatMod("armor", flat=100)]
    h.passive_ops = [{"op": "set", "stat": "armor_final", "value": 0},
                     {"op": "flag", "stat": "chaos_immune", "value": True}]
    h.recalc()
    assert h.stats.armor == 0.0 and "chaos_immune" in h.flags
    # set life_final=1 (Chaos Inoculation)
    h.passive_ops = [{"op": "set", "stat": "life_final", "value": 1}]
    h.recalc()
    assert h.max_hp == 1.0, h.max_hp
    h.passive_ops = []
    print(StatMod("attack_speed", more=25).describe())
    print(StatMod("armor", more=-50).describe())
    print("core OK:", s.life, s.res_fire, h.max_hp)
