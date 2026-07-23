"""Bar of Exile — hero classes: base stats and per-level growth."""
from __future__ import annotations

from dataclasses import dataclass

from game.core import DamageType, Hero, Slot, Stats


@dataclass
class ClassDef:
    id: str
    name: str
    base: Stats
    growth: dict[str, float]
    damage_type: DamageType
    description: str


CLASSES: dict[str, ClassDef] = {
    "warrior": ClassDef(
        id="warrior",
        name="Warrior",
        base=Stats(
            life=82.0,
            damage_min=4.0, damage_max=9.0,
            attack_speed=0.9, crit_chance=5.0, crit_multi=150.0,
            armor=18.0, evasion=5.0,
            move_speed=58.0, life_regen=1.2, life_leech=4.0,
            boss_damage_inc=100.0,
        ),
        growth={
            "life": 9.0,
            "damage_min": 0.9, "damage_max": 1.5,
            "armor": 4.5, "life_regen": 0.25,
            "boss_damage_inc": 5.0,
        },
        damage_type=DamageType.PHYS,
        description="Sword and shield. A balanced melee tank with solid life and armor.",
    ),
    "barbarian": ClassDef(
        id="barbarian",
        name="Barbarian",
        base=Stats(
            life=74.0,
            damage_min=6.0, damage_max=13.0,
            attack_speed=0.8, crit_chance=7.0, crit_multi=160.0,
            armor=8.0, evasion=8.0,
            move_speed=60.0, life_regen=0.5, life_leech=5.0,
            boss_damage_inc=80.0,
        ),
        growth={
            "life": 9.5,
            "damage_min": 1.1, "damage_max": 1.8,
            "armor": 2.5, "crit_chance": 0.1,
            "boss_damage_inc": 3.0,
        },
        damage_type=DamageType.PHYS,
        description="Two-handed fury. Devastating swings and raw life, but little armor.",
    ),
    "archer": ClassDef(
        id="archer",
        name="Archer",
        base=Stats(
            life=55.0,
            damage_min=2.0, damage_max=6.0,
            attack_speed=1.3, crit_chance=9.0, crit_multi=160.0,
            armor=4.0, evasion=20.0,
            move_speed=66.0,
        ),
        growth={
            "life": 4.0,
            "damage_min": 0.4, "damage_max": 0.8,
            "attack_speed": 0.012, "crit_chance": 0.25, "evasion": 3.0,
        },
        damage_type=DamageType.PHYS,
        description="Bow at range. Fast attacks, deadly crits and evasion.",
    ),
    "mage": ClassDef(
        id="mage",
        name="Mage",
        base=Stats(
            life=42.0,
            damage_min=1.0, damage_max=4.0,
            attack_speed=1.0, crit_chance=6.0, crit_multi=150.0,
            armor=2.0, evasion=6.0,
            move_speed=60.0,
            added_lightning=5.0, added_fire=2.0,
        ),
        growth={
            "life": 3.0,
            "damage_min": 0.2, "damage_max": 0.4,
            "added_lightning": 1.25, "added_fire": 0.6,
        },
        damage_type=DamageType.LIGHTNING,
        description="Staff caster. Fragile, but scorches everything with lightning and fire.",
    ),
    "cleric": ClassDef(
        id="cleric",
        name="Cleric",
        base=Stats(
            life=68.0,
            damage_min=2.5, damage_max=6.0,
            attack_speed=0.95, crit_chance=5.0, crit_multi=150.0,
            armor=12.0, evasion=5.0,
            move_speed=58.0, life_regen=1.6, life_leech=3.0,
            added_fire=2.0, boss_damage_inc=90.0,
        ),
        growth={
            "life": 9.0,
            "damage_min": 0.6, "damage_max": 1.0,
            "armor": 4.0, "life_regen": 0.2,
            "added_fire": 0.9, "boss_damage_inc": 3.0,
        },
        damage_type=DamageType.FIRE,
        description="Mace and holy flame. A durable fighter who mends his own wounds.",
    ),
}


def make_hero(class_id: str, name: str = "") -> Hero:
    cd = CLASSES[class_id]
    hero = Hero(
        name=name or cd.name,
        stats=cd.base.copy(),
        class_id=class_id,
        base_stats=cd.base.copy(),
        damage_type=cd.damage_type,
        equipment={s.value: None for s in Slot},
    )
    hero.init_hp()
    hero.recalc()
    return hero


def apply_level_growth(hero: Hero) -> None:
    cd = CLASSES[hero.class_id]
    base = cd.base.copy()
    lv = hero.level - 1
    for stat, per in cd.growth.items():
        setattr(base, stat, getattr(base, stat) + per * lv)
    hero.base_stats = base
    hero.recalc()
    hero.hp = hero.max_hp


if __name__ == "__main__":
    for cid in CLASSES:
        h = make_hero(cid)
        h.level = 10
        apply_level_growth(h)
        s = h.stats
        print(f"{h.name} (lvl {h.level}): hp={h.hp:.0f}/{h.max_hp:.0f} "
              f"dmg={s.damage_min:.1f}-{s.damage_max:.1f} aps={s.attack_speed:.2f} "
              f"crit={s.crit_chance:.1f}% armor={s.armor:.0f} eva={s.evasion:.0f} "
              f"regen={s.life_regen:.1f} "
              f"+ltn={s.added_lightning:.1f} +fire={s.added_fire:.1f} "
              f"slots={sorted(h.equipment)}")
    print("classes OK")
