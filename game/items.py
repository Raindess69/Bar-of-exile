"""Bar of Exile — item bases (weapons, armour, jewellery)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from game.core import Item, Rarity, Slot, StatMod


@dataclass
class ItemBase:
    id: str
    name: str
    slot: Slot
    req_level: int = 1
    implicits: list[StatMod] = field(default_factory=list)
    # weapons
    damage_min: float = 0.0
    damage_max: float = 0.0
    attack_speed: float = 0.0    # weapon APS
    # armour
    armor: float = 0.0
    evasion: float = 0.0
    # class restriction; empty = usable by all classes
    classes: tuple[str, ...] = ()

    @property
    def is_weapon(self) -> bool:
        return self.slot is Slot.WEAPON


def _b(base: ItemBase) -> tuple[str, ItemBase]:
    return base.id, base


BASES: dict[str, ItemBase] = dict([
    # --- swords: balanced ---
    _b(ItemBase("rusted_sword", "Rusted Sword", Slot.WEAPON, 1,
                damage_min=4, damage_max=9, attack_speed=1.2, classes=("warrior",))),
    _b(ItemBase("long_sword", "Long Sword", Slot.WEAPON, 12,
                damage_min=11, damage_max=21, attack_speed=1.25, classes=("warrior",))),
    _b(ItemBase("vaal_blade", "Vaal Blade", Slot.WEAPON, 25,
                damage_min=20, damage_max=38, attack_speed=1.3, classes=("warrior",))),
    # --- bows: fast, lower damage ---
    _b(ItemBase("crude_bow", "Crude Bow", Slot.WEAPON, 1,
                damage_min=3, damage_max=7, attack_speed=1.5, classes=("archer",))),
    _b(ItemBase("hunter_bow", "Hunter Bow", Slot.WEAPON, 12,
                damage_min=8, damage_max=16, attack_speed=1.55, classes=("archer",))),
    _b(ItemBase("imperial_bow", "Imperial Bow", Slot.WEAPON, 25,
                damage_min=15, damage_max=29, attack_speed=1.6, classes=("archer",))),
    # --- staves: slow, high damage, implicit ---
    _b(ItemBase("gnarled_staff", "Gnarled Staff", Slot.WEAPON, 1,
                implicits=[StatMod("life", flat=15)],
                damage_min=6, damage_max=13, attack_speed=0.9, classes=("mage",))),
    _b(ItemBase("runic_staff", "Runic Staff", Slot.WEAPON, 12,
                implicits=[StatMod("added_cold", flat=8)],
                damage_min=15, damage_max=28, attack_speed=0.9, classes=("mage",))),
    _b(ItemBase("vaal_staff", "Vaal Staff", Slot.WEAPON, 25,
                implicits=[StatMod("added_lightning", flat=14)],
                damage_min=26, damage_max=48, attack_speed=0.9, classes=("mage",))),
    # --- axes: heavy, high damage ---
    _b(ItemBase("rusted_axe", "Rusted Axe", Slot.WEAPON, 1,
                damage_min=5, damage_max=11, attack_speed=1.05, classes=("barbarian",))),
    _b(ItemBase("broad_axe", "Broad Axe", Slot.WEAPON, 12,
                damage_min=13, damage_max=26, attack_speed=1.1, classes=("barbarian",))),
    _b(ItemBase("vaal_axe", "Vaal Axe", Slot.WEAPON, 25,
                damage_min=24, damage_max=44, attack_speed=1.1, classes=("barbarian",))),
    # --- maces: slow, steady, holy implicit at top tier ---
    _b(ItemBase("worn_cudgel", "Worn Cudgel", Slot.WEAPON, 1,
                damage_min=5, damage_max=10, attack_speed=0.95, classes=("cleric",))),
    _b(ItemBase("war_mace", "War Mace", Slot.WEAPON, 12,
                damage_min=12, damage_max=22, attack_speed=1.0, classes=("cleric",))),
    _b(ItemBase("vaal_sceptre", "Vaal Sceptre", Slot.WEAPON, 25,
                implicits=[StatMod("added_fire", flat=10)],
                damage_min=22, damage_max=40, attack_speed=1.0, classes=("cleric",))),
    # --- helmets ---
    _b(ItemBase("leather_cap", "Leather Cap", Slot.HELMET, 1, evasion=16)),
    _b(ItemBase("chain_coif", "Chain Coif", Slot.HELMET, 12, armor=26, evasion=26)),
    _b(ItemBase("great_helm", "Great Helm", Slot.HELMET, 25, armor=95,
                classes=("warrior", "barbarian", "cleric"))),
    # --- body armour ---
    _b(ItemBase("leather_vest", "Leather Vest", Slot.BODY, 1, evasion=32)),
    _b(ItemBase("scale_mail", "Scale Mail", Slot.BODY, 12, armor=48, evasion=48)),
    _b(ItemBase("plate_mail", "Plate Mail", Slot.BODY, 25, armor=170,
                classes=("warrior", "barbarian", "cleric"))),
    # --- gloves ---
    _b(ItemBase("leather_gloves", "Leather Gloves", Slot.GLOVES, 1, evasion=10)),
    _b(ItemBase("chain_gloves", "Chain Gloves", Slot.GLOVES, 12, armor=17, evasion=17)),
    _b(ItemBase("plate_gauntlets", "Plate Gauntlets", Slot.GLOVES, 25, armor=60,
                classes=("warrior", "barbarian", "cleric"))),
    # --- boots ---
    _b(ItemBase("leather_boots", "Leather Boots", Slot.BOOTS, 1, evasion=10)),
    _b(ItemBase("chain_boots", "Chain Boots", Slot.BOOTS, 12, armor=17, evasion=17)),
    _b(ItemBase("plate_greaves", "Plate Greaves", Slot.BOOTS, 25, armor=60,
                classes=("warrior", "barbarian", "cleric"))),
    # --- belts ---
    _b(ItemBase("rope_belt", "Rope Belt", Slot.BELT, 1,
                implicits=[StatMod("life", flat=15)])),
    _b(ItemBase("studded_belt", "Studded Belt", Slot.BELT, 12,
                implicits=[StatMod("armor", flat=35)])),
    _b(ItemBase("heavy_belt", "Heavy Belt", Slot.BELT, 25,
                implicits=[StatMod("life", flat=40)])),
    # --- amulets ---
    _b(ItemBase("bone_amulet", "Bone Amulet", Slot.AMULET, 1,
                implicits=[StatMod("life", flat=20)])),
    _b(ItemBase("jade_amulet", "Jade Amulet", Slot.AMULET, 12,
                implicits=[StatMod("life_regen", flat=2)])),
    _b(ItemBase("onyx_amulet", "Onyx Amulet", Slot.AMULET, 25,
                implicits=[StatMod("crit_chance", flat=1.5), StatMod("crit_multi", flat=15)])),
    # --- rings ---
    _b(ItemBase("coral_ring", "Coral Ring", Slot.RING, 1,
                implicits=[StatMod("life", flat=15)])),
    _b(ItemBase("azure_ring", "Azure Ring", Slot.RING, 12,
                implicits=[StatMod("life", flat=20)])),
    _b(ItemBase("ruby_ring", "Ruby Ring", Slot.RING, 25,
                implicits=[StatMod("res_fire", flat=20)])),
])


def make_base_item(base_id: str, ilvl: int) -> Item:
    base = BASES[base_id]
    implicit: list[StatMod] = []
    if base.is_weapon:
        implicit.append(StatMod("damage_min", flat=base.damage_min))
        implicit.append(StatMod("damage_max", flat=base.damage_max))
        implicit.append(StatMod("attack_speed", flat=base.attack_speed - 1.0))
    if base.armor:
        implicit.append(StatMod("armor", flat=base.armor))
    if base.evasion:
        implicit.append(StatMod("evasion", flat=base.evasion))
    implicit.extend(StatMod(m.stat, flat=m.flat, inc=m.inc) for m in base.implicits)
    return Item(
        base_id=base.id, base_name=base.name, slot=base.slot,
        rarity=Rarity.NORMAL, ilvl=ilvl, req_level=base.req_level,
        class_req=base.classes, implicit=implicit,
    )


def random_base(ilvl: int, rng: random.Random, slot: Slot | None = None,
                class_id: str | None = None) -> Item:
    pool = [b for b in BASES.values() if slot is None or b.slot is slot]
    fits = [b for b in pool if b.req_level <= max(ilvl, 1)]
    if not fits:
        lo = min(b.req_level for b in pool)
        fits = [b for b in pool if b.req_level == lo]
    weights = [1.0 / (1.0 + max(ilvl - b.req_level, 0)) for b in fits]
    if class_id is not None:
        # smart loot: off-class bases still drop, but rarely
        weights = [w * (1.0 if not b.classes or class_id in b.classes else 0.2)
                   for w, b in zip(weights, fits)]
    base = rng.choices(fits, weights=weights, k=1)[0]
    return make_base_item(base.id, ilvl)


def weapon_dps(item: Item) -> float:
    if item.slot is not Slot.WEAPON:
        return 0.0
    flats: dict[str, float] = {}
    incs: dict[str, float] = {}
    for m in item.all_mods():
        flats[m.stat] = flats.get(m.stat, 0.0) + m.flat
        incs[m.stat] = incs.get(m.stat, 0.0) + m.inc

    def val(stat: str, base: float = 0.0) -> float:
        return (base + flats.get(stat, 0.0)) * (1 + incs.get(stat, 0.0) / 100)

    avg = (val("damage_min") + val("damage_max")) / 2
    avg += sum(val(s) for s in ("added_fire", "added_cold", "added_lightning", "added_chaos"))
    return round(avg * val("attack_speed", 1.0), 2)


if __name__ == "__main__":
    print("=== Bases by slot ===")
    for slot in Slot:
        bases = [b for b in BASES.values() if b.slot is slot]
        if not bases:
            continue
        print(f"\n[{slot.value}]")
        for b in sorted(bases, key=lambda x: x.req_level):
            extra = ""
            if b.is_weapon:
                extra = f" dmg {b.damage_min:g}-{b.damage_max:g}, aps {b.attack_speed:g}"
            if b.armor or b.evasion:
                extra += f" armour {b.armor:g}, evasion {b.evasion:g}"
            imp = "; ".join(m.describe() for m in b.implicits)
            print(f"  {b.name} (lvl {b.req_level}){extra}" + (f" | {imp}" if imp else ""))

    print("\n=== Weapon DPS (at own req_level) ===")
    for b in BASES.values():
        if b.is_weapon:
            it = make_base_item(b.id, b.req_level)
            print(f"  {b.name:20s} lvl {b.req_level:2d}  dps={weapon_dps(it):6.2f}")

    print("\n=== random_base, ilvl 1..30 ===")
    rng = random.Random(42)
    for i in range(10):
        ilvl = 1 + i * 29 // 9
        it = random_base(ilvl, rng)
        dps = weapon_dps(it)
        tail = f" dps={dps}" if dps else ""
        print(f"  ilvl {ilvl:2d}: {it.display_name()} [{it.slot.value}] req={it.req_level}{tail}")

    it = random_base(20, rng, slot=Slot.RING)
    assert it.slot is Slot.RING
    ws = make_base_item("rusted_sword", 1)
    assert any(m.stat == "attack_speed" and abs(m.flat - 0.2) < 1e-9 for m in ws.implicit)
    assert ws.class_req == ("warrior",)
    assert make_base_item("rope_belt", 1).class_req == ()
    assert make_base_item("plate_mail", 25).class_req == ("warrior", "barbarian", "cleric")

    # smart loot: with class_id="warrior", most weapons rolled must be warrior-usable
    rng2 = random.Random(123)
    usable = 0
    total = 2000
    for _ in range(total):
        it = random_base(25, rng2, slot=Slot.WEAPON, class_id="warrior")
        if not it.class_req or "warrior" in it.class_req:
            usable += 1
    assert usable > total - usable, f"smart loot failed: {usable}/{total} warrior-usable"
    print(f"smart loot: {usable}/{total} warrior-usable weapons")
    print("\nitems OK:", len(BASES), "bases")
