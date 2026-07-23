"""Affix pool with tiers T5..T1 (T1 best) and the rarity-based affix roller."""
from __future__ import annotations

import random
from dataclasses import dataclass

from game.core import Affix, Item, Rarity, Slot, StatMod

WEAPON = frozenset({Slot.WEAPON})
ARMOR = frozenset({Slot.HELMET, Slot.BODY, Slot.GLOVES, Slot.BOOTS})
NON_WEAPON = frozenset(s for s in Slot if s is not Slot.WEAPON)
BOOTS = frozenset({Slot.BOOTS})


@dataclass(frozen=True)
class AffixTier:
    tier: int
    min_ilvl: int
    # (stats "a|b" — one roll shared by all, lo, hi, "flat"|"inc")
    ranges: tuple[tuple[str, float, float, str], ...]


@dataclass(frozen=True)
class AffixFamily:
    family_id: str
    name: str
    is_prefix: bool
    allowed_slots: frozenset[Slot] | None
    tiers: tuple[AffixTier, ...]  # from T5 (worst) to T1 (best)

    def fits(self, item: Item) -> bool:
        if self.allowed_slots is not None and item.slot not in self.allowed_slots:
            return False
        return any(t.min_ilvl <= item.ilvl for t in self.tiers)


def _fam(fid: str, name: str, is_prefix: bool, slots: frozenset[Slot] | None,
         rows: list[tuple[int, list[tuple[str, float, float, str]]]]) -> AffixFamily:
    n = len(rows)
    tiers = tuple(AffixTier(tier=n - i, min_ilvl=r[0], ranges=tuple(r[1]))
                  for i, r in enumerate(rows))
    return AffixFamily(fid, name, is_prefix, slots, tiers)


PREFIXES: list[AffixFamily] = [
    _fam("phys_pct", "Heavy", True, WEAPON, [
        (1,  [("damage_min|damage_max", 15, 29, "inc")]),
        (12, [("damage_min|damage_max", 30, 49, "inc")]),
        (24, [("damage_min|damage_max", 50, 69, "inc")]),
        (36, [("damage_min|damage_max", 70, 89, "inc")]),
        (48, [("damage_min|damage_max", 90, 129, "inc")]),
    ]),
    _fam("phys_flat", "Honed", True, WEAPON, [
        (1,  [("damage_min", 1, 2, "flat"), ("damage_max", 3, 4, "flat")]),
        (12, [("damage_min", 2, 4, "flat"), ("damage_max", 5, 7, "flat")]),
        (24, [("damage_min", 4, 6, "flat"), ("damage_max", 8, 11, "flat")]),
        (36, [("damage_min", 6, 9, "flat"), ("damage_max", 12, 16, "flat")]),
        (48, [("damage_min", 9, 13, "flat"), ("damage_max", 17, 23, "flat")]),
    ]),
    _fam("fire_flat", "Fiery", True, WEAPON, [
        (1,  [("added_fire", 2, 4, "flat")]),
        (12, [("added_fire", 5, 9, "flat")]),
        (24, [("added_fire", 10, 16, "flat")]),
        (36, [("added_fire", 17, 25, "flat")]),
        (48, [("added_fire", 26, 38, "flat")]),
    ]),
    _fam("cold_flat", "Frosted", True, WEAPON, [
        (1,  [("added_cold", 2, 3, "flat")]),
        (12, [("added_cold", 4, 8, "flat")]),
        (24, [("added_cold", 9, 14, "flat")]),
        (36, [("added_cold", 15, 22, "flat")]),
        (48, [("added_cold", 23, 34, "flat")]),
    ]),
    _fam("lightning_flat", "Humming", True, WEAPON, [
        (1,  [("added_lightning", 1, 5, "flat")]),
        (12, [("added_lightning", 2, 11, "flat")]),
        (24, [("added_lightning", 3, 19, "flat")]),
        (36, [("added_lightning", 4, 29, "flat")]),
        (48, [("added_lightning", 5, 45, "flat")]),
    ]),
    _fam("chaos_flat", "Malicious", True, WEAPON, [
        (5,  [("added_chaos", 2, 3, "flat")]),
        (16, [("added_chaos", 4, 7, "flat")]),
        (28, [("added_chaos", 8, 12, "flat")]),
        (40, [("added_chaos", 13, 19, "flat")]),
        (50, [("added_chaos", 20, 29, "flat")]),
    ]),
    _fam("life_flat", "Stalwart", True, NON_WEAPON, [
        (1,  [("life", 10, 19, "flat")]),
        (10, [("life", 20, 34, "flat")]),
        (22, [("life", 35, 54, "flat")]),
        (34, [("life", 55, 79, "flat")]),
        (46, [("life", 80, 109, "flat")]),
    ]),
    _fam("armor_flat", "Reinforced", True, ARMOR, [
        (1,  [("armor", 5, 12, "flat")]),
        (12, [("armor", 13, 30, "flat")]),
        (24, [("armor", 31, 60, "flat")]),
        (36, [("armor", 61, 110, "flat")]),
        (48, [("armor", 111, 180, "flat")]),
    ]),
    _fam("armor_pct", "Plated", True, ARMOR, [
        (1,  [("armor", 10, 19, "inc")]),
        (12, [("armor", 20, 32, "inc")]),
        (24, [("armor", 33, 48, "inc")]),
        (36, [("armor", 49, 67, "inc")]),
        (48, [("armor", 68, 92, "inc")]),
    ]),
    _fam("evasion_flat", "Agile", True, ARMOR, [
        (1,  [("evasion", 5, 12, "flat")]),
        (12, [("evasion", 13, 30, "flat")]),
        (24, [("evasion", 31, 60, "flat")]),
        (36, [("evasion", 61, 110, "flat")]),
        (48, [("evasion", 111, 180, "flat")]),
    ]),
    _fam("evasion_pct", "Nimble", True, ARMOR, [
        (1,  [("evasion", 10, 19, "inc")]),
        (12, [("evasion", 20, 32, "inc")]),
        (24, [("evasion", 33, 48, "inc")]),
        (36, [("evasion", 49, 67, "inc")]),
        (48, [("evasion", 68, 92, "inc")]),
    ]),
    _fam("life_flat2", "Azure", True, None, [
        (1,  [("life", 8, 14, "flat")]),
        (10, [("life", 15, 24, "flat")]),
        (22, [("life", 25, 38, "flat")]),
        (34, [("life", 39, 55, "flat")]),
        (46, [("life", 56, 79, "flat")]),
    ]),
    _fam("regen_pre", "Vital", True, NON_WEAPON, [
        (1,  [("life_regen", 0.5, 1.0, "flat")]),
        (12, [("life_regen", 1.1, 2.0, "flat")]),
        (24, [("life_regen", 2.1, 3.5, "flat")]),
        (36, [("life_regen", 3.6, 5.5, "flat")]),
        (48, [("life_regen", 5.6, 8.0, "flat")]),
    ]),
]

SUFFIXES: list[AffixFamily] = [
    _fam("attack_speed", "of Alacrity", False, WEAPON, [
        (1,  [("attack_speed", 5, 7, "inc")]),
        (12, [("attack_speed", 8, 10, "inc")]),
        (24, [("attack_speed", 11, 14, "inc")]),
        (36, [("attack_speed", 15, 19, "inc")]),
        (48, [("attack_speed", 20, 26, "inc")]),
    ]),
    _fam("crit_chance", "of Precision", False, WEAPON, [
        (1,  [("crit_chance", 10, 14, "inc")]),
        (12, [("crit_chance", 15, 21, "inc")]),
        (24, [("crit_chance", 22, 29, "inc")]),
        (36, [("crit_chance", 30, 38, "inc")]),
        (48, [("crit_chance", 39, 49, "inc")]),
    ]),
    _fam("crit_multi", "of Destruction", False, WEAPON, [
        (1,  [("crit_multi", 8, 12, "flat")]),
        (12, [("crit_multi", 13, 19, "flat")]),
        (24, [("crit_multi", 20, 27, "flat")]),
        (36, [("crit_multi", 28, 37, "flat")]),
        (48, [("crit_multi", 38, 49, "flat")]),
    ]),
    _fam("res_fire", "of the Salamander", False, NON_WEAPON, [
        (1,  [("res_fire", 6, 11, "flat")]),
        (12, [("res_fire", 12, 17, "flat")]),
        (24, [("res_fire", 18, 23, "flat")]),
        (36, [("res_fire", 24, 29, "flat")]),
        (48, [("res_fire", 30, 38, "flat")]),
    ]),
    _fam("res_cold", "of the Walrus", False, NON_WEAPON, [
        (1,  [("res_cold", 6, 11, "flat")]),
        (12, [("res_cold", 12, 17, "flat")]),
        (24, [("res_cold", 18, 23, "flat")]),
        (36, [("res_cold", 24, 29, "flat")]),
        (48, [("res_cold", 30, 38, "flat")]),
    ]),
    _fam("res_lightning", "of the Storm", False, NON_WEAPON, [
        (1,  [("res_lightning", 6, 11, "flat")]),
        (12, [("res_lightning", 12, 17, "flat")]),
        (24, [("res_lightning", 18, 23, "flat")]),
        (36, [("res_lightning", 24, 29, "flat")]),
        (48, [("res_lightning", 30, 38, "flat")]),
    ]),
    _fam("res_chaos", "of the Viper", False, NON_WEAPON, [
        (5,  [("res_chaos", 4, 7, "flat")]),
        (16, [("res_chaos", 8, 11, "flat")]),
        (28, [("res_chaos", 12, 15, "flat")]),
        (40, [("res_chaos", 16, 20, "flat")]),
        (50, [("res_chaos", 21, 26, "flat")]),
    ]),
    _fam("move_speed", "of the Fox", False, BOOTS, [
        (1,  [("move_speed", 10, 14, "inc")]),
        (12, [("move_speed", 15, 19, "inc")]),
        (24, [("move_speed", 20, 24, "inc")]),
        (36, [("move_speed", 25, 29, "inc")]),
        (48, [("move_speed", 30, 35, "inc")]),
    ]),
    _fam("regen_suf", "of the Spring", False, NON_WEAPON, [
        (1,  [("life_regen", 0.3, 0.7, "flat")]),
        (12, [("life_regen", 0.8, 1.4, "flat")]),
        (24, [("life_regen", 1.5, 2.4, "flat")]),
        (36, [("life_regen", 2.5, 3.9, "flat")]),
        (48, [("life_regen", 4.0, 6.0, "flat")]),
    ]),
    _fam("life_pct2", "of the Magus", False, None, [
        (1,  [("life", 5, 9, "inc")]),
        (12, [("life", 10, 15, "inc")]),
        (24, [("life", 16, 22, "inc")]),
        (36, [("life", 23, 30, "inc")]),
        (48, [("life", 31, 40, "inc")]),
    ]),
]

RARE_FIRST = [
    "Doom", "Storm", "Blood", "Dread", "Soul", "Death", "Plague", "Shadow",
    "Grim", "Viper", "Raven", "Skull", "Woe", "Ghoul", "Ember",
]
RARE_SECOND = [
    "Fang", "Grip", "Song", "Bane", "Bite", "Brand", "Claw", "Veil",
    "Whisper", "Howl", "Mark", "Coil", "Shroud", "Call", "Roar",
]


def _pick_tier(fam: AffixFamily, ilvl: int, rng: random.Random) -> AffixTier:
    avail = [t for t in fam.tiers if t.min_ilvl <= ilvl]
    weights = [2 ** (t.tier - 1) for t in avail]  # T1 (best) is the rarest
    return rng.choices(avail, weights=weights)[0]


def _roll_mods(tier: AffixTier, rng: random.Random) -> list[StatMod]:
    mods: list[StatMod] = []
    for stats, lo, hi, kind in tier.ranges:
        if float(lo).is_integer() and float(hi).is_integer():
            val: float = rng.randint(int(lo), int(hi))
        else:
            val = round(rng.uniform(lo, hi), 1)
        for stat in stats.split("|"):
            mods.append(StatMod(stat, flat=val) if kind == "flat" else StatMod(stat, inc=val))
    return mods


def _make_affix(fam: AffixFamily, ilvl: int, rng: random.Random) -> Affix:
    tier = _pick_tier(fam, ilvl, rng)
    return Affix(id=f"{fam.family_id}_t{tier.tier}", name=fam.name,
                 is_prefix=fam.is_prefix, tier=tier.tier, mods=_roll_mods(tier, rng))


def roll_affixes(item: Item, rng: random.Random) -> None:
    item.affixes = []
    if item.rarity not in (Rarity.MAGIC, Rarity.RARE):
        item.name = item.base_name
        return
    if item.rarity == Rarity.MAGIC:
        count, max_p, max_s = rng.randint(1, 2), 1, 1
    else:
        count, max_p, max_s = rng.randint(4, 6), 3, 3
    pre_pool = [f for f in PREFIXES if f.fits(item)]
    suf_pool = [f for f in SUFFIXES if f.fits(item)]
    n_pre = n_suf = 0
    for _ in range(count):
        cand: list[AffixFamily] = []
        if n_pre < max_p:
            cand.extend(pre_pool)
        if n_suf < max_s:
            cand.extend(suf_pool)
        if not cand:
            break
        fam = rng.choice(cand)
        if fam.is_prefix:
            pre_pool.remove(fam)
            n_pre += 1
        else:
            suf_pool.remove(fam)
            n_suf += 1
        item.affixes.append(_make_affix(fam, item.ilvl, rng))
    item.affixes.sort(key=lambda a: (not a.is_prefix, a.tier))
    if item.rarity == Rarity.MAGIC:
        pre = next((a for a in item.affixes if a.is_prefix), None)
        suf = next((a for a in item.affixes if not a.is_prefix), None)
        parts = ([pre.name] if pre else []) + [item.base_name] + ([suf.name] if suf else [])
        item.name = " ".join(parts)
    else:
        item.name = f"{rng.choice(RARE_FIRST)} {rng.choice(RARE_SECOND)}"


if __name__ == "__main__":
    rng = random.Random(42)
    bases = [
        ("long_sword", "Long Sword", Slot.WEAPON),
        ("iron_helm", "Iron Helm", Slot.HELMET),
        ("leather_boots", "Leather Boots", Slot.BOOTS),
        ("bone_ring", "Bone Ring", Slot.RING),
        ("chainmail", "Chainmail", Slot.BODY),
    ]
    for rarity in (Rarity.MAGIC, Rarity.RARE):
        print(f"=== {rarity.value.upper()} ===")
        for i in range(5):
            bid, bname, slot = bases[i % len(bases)]
            it = Item(base_id=bid, base_name=bname, slot=slot, rarity=rarity,
                      ilvl=rng.choice([5, 20, 40, 60]))
            roll_affixes(it, rng)
            assert it.affixes, it
            print(f"{it.display_name()}  [{bname}, {slot.value}, ilvl {it.ilvl}]")
            for a in it.affixes:
                kind = "P" if a.is_prefix else "S"
                print(f"   {kind}T{a.tier} {a.id}: " + "; ".join(m.describe() for m in a.mods))
        print()
    print("affixes OK")
