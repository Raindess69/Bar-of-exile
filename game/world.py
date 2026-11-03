"""Bar of Exile — Acts 1-3: zones, monster templates, pack spawner, bosses."""
from __future__ import annotations

import random
from dataclasses import dataclass

from game.core import DamageType, Monster, Stats
from game import mob_rarity, zone_mods


@dataclass
class MonsterTemplate:
    id: str
    name: str
    base_life: float
    base_dmin: float
    base_dmax: float
    attack_speed: float
    move_speed: float
    armor: float
    damage_type: DamageType
    xp_mult: float
    color: str
    size: str  # "small" / "medium" / "large"


TEMPLATES: dict[str, MonsterTemplate] = {t.id: t for t in [
    # --- Act 1 ---
    MonsterTemplate("goblin", "Goblin", 18.0, 3.0, 5.0, 1.4, 78.0, 3.0,
                    DamageType.PHYS, 0.9, "#4fa64f", "small"),
    MonsterTemplate("goblin_shaman", "Goblin Shaman", 22.0, 6.0, 11.0, 0.8, 46.0, 2.0,
                    DamageType.LIGHTNING, 1.4, "#3fbf9f", "medium"),
    MonsterTemplate("orc", "Orc", 36.0, 5.0, 9.0, 1.0, 55.0, 12.0,
                    DamageType.PHYS, 1.2, "#7a8a3a", "medium"),
    MonsterTemplate("orc_brute", "Orc Brute", 64.0, 7.0, 13.0, 0.7, 38.0, 26.0,
                    DamageType.PHYS, 1.6, "#5f6f2f", "large"),
    MonsterTemplate("slime_toxic", "Toxic Slime", 48.0, 3.0, 6.0, 0.6, 24.0, 0.0,
                    DamageType.CHAOS, 1.2, "#66cc33", "small"),
    MonsterTemplate("slime_icy", "Icy Slime", 52.0, 3.0, 6.0, 0.55, 22.0, 5.0,
                    DamageType.COLD, 1.2, "#66bbee", "small"),
    MonsterTemplate("slime_magma", "Magma Slime", 56.0, 4.0, 8.0, 0.6, 24.0, 10.0,
                    DamageType.FIRE, 1.3, "#e05a2a", "small"),
    MonsterTemplate("skeleton", "Skeleton", 26.0, 4.0, 7.0, 1.0, 50.0, 8.0,
                    DamageType.PHYS, 1.0, "#d9d4c5", "medium"),
    MonsterTemplate("skeleton_mage", "Skeleton Mage", 20.0, 6.0, 11.0, 0.8, 44.0, 2.0,
                    DamageType.LIGHTNING, 1.4, "#9a7ad9", "medium"),
    MonsterTemplate("imp", "Imp", 12.0, 3.0, 6.0, 1.6, 92.0, 0.0,
                    DamageType.FIRE, 0.7, "#ff7733", "small"),
    MonsterTemplate("demon", "Demon", 85.0, 9.0, 16.0, 0.8, 45.0, 20.0,
                    DamageType.PHYS, 2.0, "#a3364a", "large"),
    MonsterTemplate("goblin_king", "Goblin King", 240.0, 11.0, 18.0, 0.9, 42.0, 35.0,
                    DamageType.PHYS, 6.0, "#2f9e44", "large"),
    # Act 1 extended roster
    MonsterTemplate("giant_spider", "Giant Spider", 14.0, 3.0, 5.0, 1.5, 82.0, 2.0,
                    DamageType.PHYS, 0.8, "#4a3a2a", "small"),
    MonsterTemplate("plague_rat", "Plague Rat", 10.0, 2.0, 4.0, 1.7, 95.0, 0.0,
                    DamageType.CHAOS, 0.6, "#5a4a3a", "small"),
    MonsterTemplate("wraith", "Wraith", 32.0, 5.0, 9.0, 1.2, 64.0, 0.0,
                    DamageType.COLD, 1.3, "#6a7a9a", "large"),
    MonsterTemplate("zombie", "Zombie", 52.0, 4.0, 8.0, 0.5, 26.0, 14.0,
                    DamageType.PHYS, 1.1, "#5a6a4a", "large"),
    MonsterTemplate("shadow_beast", "Shadow Beast", 28.0, 5.0, 8.0, 1.3, 72.0, 4.0,
                    DamageType.CHAOS, 1.2, "#3a2a4a", "large"),
    MonsterTemplate("living_armor", "Living Armor", 70.0, 6.0, 10.0, 0.6, 32.0, 32.0,
                    DamageType.PHYS, 1.5, "#7a7a8a", "large"),
    MonsterTemplate("gargoyle", "Gargoyle", 44.0, 6.0, 11.0, 1.0, 58.0, 18.0,
                    DamageType.PHYS, 1.4, "#6a6a7a", "large"),
    # --- Act 2 ---
    MonsterTemplate("sand_leaper", "Sand Leaper", 22.0, 4.0, 7.0, 1.5, 88.0, 4.0,
                    DamageType.PHYS, 1.0, "#c8a45a", "small"),
    MonsterTemplate("mummy", "Mummy", 55.0, 5.0, 9.0, 0.6, 28.0, 20.0,
                    DamageType.PHYS, 1.3, "#b8ae8e", "medium"),
    MonsterTemplate("tomb_snake", "Tomb Snake", 20.0, 5.0, 8.0, 1.3, 70.0, 2.0,
                    DamageType.CHAOS, 1.1, "#7a9a4a", "small"),
    MonsterTemplate("dune_bandit", "Dune Bandit", 36.0, 6.0, 10.0, 1.1, 60.0, 14.0,
                    DamageType.PHYS, 1.2, "#a8763e", "medium"),
    MonsterTemplate("scarab_swarm", "Scarab Swarm", 16.0, 3.0, 6.0, 1.8, 75.0, 0.0,
                    DamageType.LIGHTNING, 0.8, "#2f8a7a", "small"),
    MonsterTemplate("vulture_demon", "Vulture Demon", 40.0, 7.0, 12.0, 1.0, 66.0, 8.0,
                    DamageType.PHYS, 1.4, "#8a4a5a", "medium"),
    MonsterTemplate("lich_emperor", "Lich Emperor", 300.0, 14.0, 24.0, 0.7, 32.0, 40.0,
                    DamageType.COLD, 6.5, "#54c7c3", "large"),
    # Act 2 extended roster
    MonsterTemplate("sand_raider", "Sand Raider", 32.0, 5.0, 9.0, 1.2, 66.0, 10.0,
                    DamageType.PHYS, 1.1, "#b8864e", "medium"),
    MonsterTemplate("fallen_shaman", "Fallen Shaman", 24.0, 6.0, 11.0, 0.8, 48.0, 3.0,
                    DamageType.FIRE, 1.3, "#c8763a", "medium"),
    MonsterTemplate("skeleton_v2", "Ancient Skeleton", 30.0, 5.0, 8.0, 1.0, 52.0, 10.0,
                    DamageType.PHYS, 1.1, "#c8c4b5", "medium"),
    MonsterTemplate("cultist", "Cultist", 28.0, 5.0, 9.0, 0.9, 50.0, 6.0,
                    DamageType.CHAOS, 1.2, "#6a4a7a", "medium"),
    MonsterTemplate("dark_knight", "Dark Knight", 75.0, 8.0, 14.0, 0.7, 36.0, 38.0,
                    DamageType.PHYS, 1.6, "#4a3a5a", "large"),
    # --- Act 3 ---
    MonsterTemplate("jungle_stalker", "Jungle Stalker", 26.0, 6.0, 10.0, 1.5, 90.0, 6.0,
                    DamageType.PHYS, 1.1, "#3a7a3a", "small"),
    MonsterTemplate("venom_toad", "Venom Toad", 45.0, 5.0, 9.0, 0.7, 34.0, 6.0,
                    DamageType.CHAOS, 1.2, "#8aa62f", "small"),
    MonsterTemplate("blood_ape", "Blood Ape", 60.0, 8.0, 13.0, 1.1, 62.0, 10.0,
                    DamageType.PHYS, 1.4, "#9a4a3a", "large"),
    MonsterTemplate("temple_guardian", "Temple Guardian", 90.0, 9.0, 15.0, 0.6, 30.0, 40.0,
                    DamageType.PHYS, 1.7, "#b8a86a", "large"),
    MonsterTemplate("cursed_priest", "Cursed Priest", 30.0, 8.0, 14.0, 0.8, 42.0, 4.0,
                    DamageType.CHAOS, 1.5, "#7a4a9a", "medium"),
    MonsterTemplate("fire_serpent", "Fire Serpent", 34.0, 7.0, 12.0, 1.2, 68.0, 8.0,
                    DamageType.FIRE, 1.3, "#e07a2a", "large"),
    MonsterTemplate("orc_warlord", "Orc Warlord", 280.0, 13.0, 21.0, 0.9, 46.0, 45.0,
                    DamageType.PHYS, 5.5, "#6b7a2a", "large"),
    MonsterTemplate("mother_of_slimes", "Mother of Slimes", 340.0, 12.0, 20.0, 0.5, 20.0, 10.0,
                    DamageType.CHAOS, 6.0, "#7ddd3a", "large"),
    MonsterTemplate("lord_of_ash", "Lord of Ash", 380.0, 16.0, 28.0, 0.75, 36.0, 50.0,
                    DamageType.FIRE, 7.0, "#e0492a", "large"),
    # Act 3 extended roster
    MonsterTemplate("temple_golem", "Temple Golem", 95.0, 10.0, 16.0, 0.55, 28.0, 45.0,
                    DamageType.PHYS, 1.7, "#a8987a", "large"),
    MonsterTemplate("insectoid", "Insectoid", 20.0, 5.0, 8.0, 1.6, 86.0, 3.0,
                    DamageType.PHYS, 0.9, "#5a7a4a", "small"),
    MonsterTemplate("minotaur", "Minotaur", 100.0, 11.0, 18.0, 0.8, 40.0, 35.0,
                    DamageType.PHYS, 1.8, "#7a5a4a", "large"),
    MonsterTemplate("abomination", "Abomination", 120.0, 12.0, 20.0, 0.6, 32.0, 28.0,
                    DamageType.CHAOS, 2.0, "#5a4a3a", "large"),
    MonsterTemplate("blood_golem", "Blood Golem", 110.0, 9.0, 15.0, 0.5, 26.0, 42.0,
                    DamageType.PHYS, 1.9, "#9a3a3a", "large"),
    # Act 3 undead_jungle roster (sprites: undead_jungle atlas)
    MonsterTemplate("skeleton_warrior", "Skeleton Warrior", 40.0, 7.0, 12.0, 1.0, 54.0, 14.0,
                    DamageType.PHYS, 1.2, "#c8c4b5", "medium"),
    MonsterTemplate("skeleton_archer", "Skeleton Archer", 30.0, 8.0, 14.0, 1.1, 52.0, 4.0,
                    DamageType.PHYS, 1.2, "#b8b4a5", "medium"),
    MonsterTemplate("undead_jaguar", "Undead Jaguar", 42.0, 8.0, 13.0, 1.5, 92.0, 8.0,
                    DamageType.PHYS, 1.2, "#3a3a4a", "large"),
    MonsterTemplate("vinespawn", "Vinespawn", 70.0, 7.0, 12.0, 0.7, 30.0, 12.0,
                    DamageType.CHAOS, 1.5, "#4a7a3a", "large"),
    MonsterTemplate("cannibal_shaman", "Cannibal Shaman", 38.0, 9.0, 15.0, 0.85, 48.0, 4.0,
                    DamageType.FIRE, 1.5, "#8a5a3a", "medium"),
    MonsterTemplate("rotting_zombie", "Rotting Zombie", 58.0, 6.0, 11.0, 0.55, 28.0, 12.0,
                    DamageType.CHAOS, 1.2, "#5a6a4a", "medium"),
    MonsterTemplate("armored_zombie", "Armored Zombie", 82.0, 7.0, 12.0, 0.6, 34.0, 40.0,
                    DamageType.PHYS, 1.6, "#6a7a6a", "large"),
    MonsterTemplate("skeleton_chieftain", "Skeleton Chieftain", 320.0, 15.0, 25.0, 0.85, 44.0, 42.0,
                    DamageType.PHYS, 6.0, "#c8c4a5", "large"),
    # Act 3 demons_eldritch roster (sprites: demons_eldritch atlas)
    MonsterTemplate("ember_imp", "Ember Imp", 24.0, 6.0, 10.0, 1.5, 88.0, 2.0,
                    DamageType.FIRE, 1.0, "#e0662a", "small"),
    MonsterTemplate("horned_fiend", "Horned Fiend", 68.0, 9.0, 15.0, 0.9, 52.0, 16.0,
                    DamageType.PHYS, 1.5, "#7a3a4a", "large"),
    MonsterTemplate("void_wraith", "Void Wraith", 44.0, 8.0, 14.0, 1.2, 70.0, 0.0,
                    DamageType.COLD, 1.4, "#4a4a6a", "large"),
    MonsterTemplate("gloom_bat", "Gloom Bat", 30.0, 6.0, 11.0, 1.6, 96.0, 2.0,
                    DamageType.CHAOS, 1.0, "#3a2a4a", "small"),
    MonsterTemplate("hell_minotaur", "Hell Minotaur", 105.0, 12.0, 19.0, 0.8, 44.0, 34.0,
                    DamageType.PHYS, 1.8, "#6a2a2a", "large"),
    MonsterTemplate("succubus", "Succubus", 50.0, 9.0, 15.0, 1.1, 64.0, 6.0,
                    DamageType.CHAOS, 1.5, "#a03a6a", "medium"),
    MonsterTemplate("ashen_demon", "Ashen Demon", 60.0, 10.0, 16.0, 0.9, 50.0, 14.0,
                    DamageType.FIRE, 1.5, "#8a4a3a", "large"),
    MonsterTemplate("bone_reaver", "Bone Reaver", 46.0, 9.0, 16.0, 1.1, 60.0, 8.0,
                    DamageType.PHYS, 1.4, "#b0a890", "medium"),
    MonsterTemplate("winged_terror", "Winged Terror", 90.0, 11.0, 18.0, 0.85, 58.0, 18.0,
                    DamageType.PHYS, 1.7, "#4a2a3a", "large"),
    MonsterTemplate("creeping_shadow", "Creeping Shadow", 40.0, 8.0, 14.0, 1.3, 74.0, 0.0,
                    DamageType.CHAOS, 1.3, "#2a2a3a", "large"),
    # Act 3 / endgame eldritch bosses
    MonsterTemplate("abyssal_behemoth", "Abyssal Behemoth", 420.0, 17.0, 29.0, 0.7, 46.0, 48.0,
                    DamageType.PHYS, 7.0, "#3a2a4a", "large"),
    MonsterTemplate("the_watcher", "The Watcher", 400.0, 18.0, 30.0, 0.8, 30.0, 40.0,
                    DamageType.CHAOS, 7.5, "#5a2a5a", "large"),
]}


@dataclass
class Zone:
    id: str
    name: str
    act: int
    monster_level: int
    templates: list[str]
    pack_size: tuple[int, int]
    spawn_interval: float
    boss_template_id: str | None
    bg_theme: str  # "beach" / "swamp" / "forest" / "cave" / "ruins" / "desert" / "tomb" / "jungle" / "temple"
    flavor: str = ""  # one-line lore blurb, shown in zone UI later


ZONES: list[Zone] = [
    # Act 1 - Coast to Ruins
    Zone("a1_shore", "Twilight Shore", 1, 1,
         ["goblin", "slime_icy", "plague_rat", "giant_spider"], (2, 4), 6.0, None, "beach",
         flavor="Kael's fleets broke on these rocks; Vharos keeps what the tide forgets."),
    Zone("a1_swamp", "Rotting Swamp", 1, 4,
         ["slime_toxic", "plague_rat", "zombie", "venom_toad"], (2, 4), 5.5, None, "swamp",
         flavor="The coast drowned when Kael fell; now the marsh chews slowly on its bones."),
    Zone("a1_forest", "Darkroot Forest", 1, 8,
         ["orc", "skeleton", "giant_spider", "shadow_beast", "wraith"], (3, 5), 5.0, None, "forest",
         flavor="No sun has pierced these boughs since the Sundering split the coast."),
    Zone("a1_caves", "Ember Caves", 1, 13,
         ["imp", "slime_magma", "gargoyle", "living_armor"], (2, 4), 5.0, None, "cave",
         flavor="Here the Ember Below breathes close, and the stone sweats fire."),
    Zone("a1_ruins", "Ruins of the Firstborn", 1, 18,
         ["demon", "skeleton_mage", "wraith", "gargoyle", "living_armor"], (2, 3), 5.5,
         "goblin_king", "ruins",
         flavor="Kael's first temples, now a throne of filth for a goblin crowned in rust."),
    # Act 2 - Desert and Tombs
    Zone("a2_wastes", "Stony Wastes", 2, 22,
         ["sand_leaper", "dune_bandit", "sand_raider", "scarab_swarm"], (2, 4), 5.5, None, "desert",
         flavor="Where Sar-Hazan begins, even Kael's roads surrendered to the sand."),
    Zone("a2_dunes", "Far Dunes", 2, 26,
         ["sand_leaper", "sand_raider", "dune_bandit", "fallen_shaman", "vulture_demon"], (3, 5), 5.0,
         None, "desert",
         flavor="The dunes of Sar-Hazan drift over armies that never marched home."),
    Zone("a2_lost_city", "Lost City", 2, 30,
         ["dune_bandit", "sand_raider", "cultist", "fallen_shaman"], (2, 4), 5.0,
         None, "desert",
         flavor="A jewel of Kael, buried the night Sar-Hazan swallowed its name."),
    Zone("a2_crypts", "Serpent Crypts", 2, 34,
         ["tomb_snake", "mummy", "skeleton_v2", "cultist", "wraith"], (2, 4), 5.0,
         None, "tomb",
         flavor="The priest-kings of Sar-Hazan bound serpents to guard their sleep."),
    Zone("a2_great_tomb", "Great Tomb", 2, 38,
         ["mummy", "skeleton_v2", "dark_knight", "cultist", "wraith"], (2, 3), 5.5,
         "lich_emperor", "tomb",
         flavor="The last emperor of Sar-Hazan refused death; death obliged him anyway."),
    # Act 3 - Jungle and Temples
    Zone("a3_jungle_edge", "Jungle's Edge", 3, 40,
         ["jungle_stalker", "venom_toad", "insectoid", "undead_jaguar", "gloom_bat"], (2, 4), 5.5, None, "jungle",
         flavor="Beyond Sar-Hazan the green begins, and Kael's maps go silent."),
    Zone("a3_deep_canopy", "Deep Canopy", 3, 44,
         ["jungle_stalker", "blood_ape", "vinespawn", "cannibal_shaman", "undead_jaguar"], (3, 5), 5.0,
         None, "jungle",
         flavor="The jungle remembers gods older than Kael, and feeds them still."),
    Zone("a3_warcamp", "Orc Warcamp", 3, 48,
         ["orc", "orc_brute", "blood_ape", "hell_minotaur"], (2, 4), 5.0,
         "orc_warlord", "jungle",
         flavor="Gromm'kar's warhorns sound where the empire once collected its tithes."),
    Zone("a3_sunken_temple", "Sunken Temple", 3, 52,
         ["temple_guardian", "temple_golem", "cultist", "cursed_priest", "void_wraith"], (2, 4), 5.0,
         None, "temple",
         flavor="Vharos drowned this temple long ago; its priests never noticed."),
    Zone("a3_slime_pits", "Slime Pits", 3, 55,
         ["slime_toxic", "slime_magma", "vinespawn", "abomination", "bone_reaver"], (3, 5), 5.0,
         "mother_of_slimes", "jungle",
         flavor="Something beneath the temples birthed, and birthed, and never stopped."),
    Zone("a3_ashen_sanctum", "Ashen Sanctum", 3, 58,
         ["cursed_priest", "ashen_demon", "horned_fiend", "ember_imp", "succubus"], (2, 3), 5.5,
         "lord_of_ash", "temple",
         flavor="Here the Ember Below found a door, and the Lord of Ash walked through."),
    # Act 4 - The Abyss (endgame gate, eldritch)
    Zone("a4_bone_wastes", "Bone Wastes", 4, 61,
         ["skeleton_warrior", "skeleton_archer", "armored_zombie", "bone_reaver", "creeping_shadow"], (3, 5), 5.0,
         "skeleton_chieftain", "tomb",
         flavor="Where the dead of every age were dragged, and none stayed buried."),
    Zone("a4_demon_rift", "Demon Rift", 4, 64,
         ["horned_fiend", "winged_terror", "hell_minotaur", "void_wraith", "gloom_bat"], (2, 4), 5.5,
         "abyssal_behemoth", "cave",
         flavor="The Ember Below tore wide, and the things beneath poured up."),
    Zone("a4_the_eye", "The Sleepless Eye", 4, 68,
         ["creeping_shadow", "void_wraith", "succubus", "ashen_demon", "winged_terror"], (2, 3), 6.0,
         "the_watcher", "temple",
         flavor="Something older than Vessara opened its eye, and has not blinked since."),
]

_ZONES_BY_ID = {z.id: z for z in ZONES}


def get_zone(zone_id: str) -> Zone:
    return _ZONES_BY_ID[zone_id]


# --- 6.3 Zone length per act ---------------------------------------------------
# Zone boss requires kills_to_boss(act, zone_pos) trash kills. zone_pos is the
# zone's 0-based position within its act, ordered by monster_level (0..N-1). The
# (1 + 0.25*pos) factor extends naturally past pos 2 for acts with 5-6 zones.
def kills_to_boss(act: int, zone_pos: int) -> int:
    return round(24 * (1.6 ** (act - 1)) * (1 + 0.25 * zone_pos))


def _build_zone_positions() -> dict[str, int]:
    """Map zone id -> 0-based index within its act, ordered by monster_level."""
    by_act: dict[int, list[Zone]] = {}
    for z in ZONES:
        by_act.setdefault(z.act, []).append(z)
    pos: dict[str, int] = {}
    for zs in by_act.values():
        for i, z in enumerate(sorted(zs, key=lambda z: z.monster_level)):
            pos[z.id] = i
    return pos


_ZONE_POS = _build_zone_positions()


def zone_pos(zone: Zone) -> int:
    return _ZONE_POS.get(zone.id, 0)


# --- Campaign order (auto-advance) --------------------------------------------
# The "campaign" is Acts 1-3, ending at the difficulty-gate boss (lord_of_ash in
# a3_ashen_sanctum). Act 4 is optional endgame reached manually from the
# waypoint, so it is deliberately excluded from the auto-advance chain.
CAMPAIGN_ZONES: list[Zone] = sorted(
    [z for z in ZONES if z.act <= 3], key=lambda z: (z.act, z.monster_level))
_CAMPAIGN_IDX = {z.id: i for i, z in enumerate(CAMPAIGN_ZONES)}


def first_campaign_zone() -> Zone:
    """Act 1 opener — where a new difficulty loop begins."""
    return CAMPAIGN_ZONES[0]


def next_campaign_zone(zone: Zone) -> Zone | None:
    """The next zone in Act 1-3 order, or None if `zone` is the finale (or not a
    campaign zone, e.g. an Act 4 / rift instance)."""
    i = _CAMPAIGN_IDX.get(zone.id)
    if i is None or i + 1 >= len(CAMPAIGN_ZONES):
        return None
    return CAMPAIGN_ZONES[i + 1]


# --- 6.4 Mob scaling per act ---------------------------------------------------
# linear x geometric, accelerating; mirrors the XP curve so difficulty and reward
# stay coupled. m = monster level - 1 (matches the (level-1) convention below), so
# both mults are exactly 1.0 at mlvl 1 and scaling is continuous at the low end.
def mob_life_mult(m: int) -> float:
    return (1 + 0.32 * m) * 1.022 ** m


def mob_dmg_mult(m: int) -> float:
    return (1 + 0.20 * m) * 1.016 ** m


XP_BASE = 6.0
XP_GROWTH = 0.18  # retained for game.save offline-xp estimate (world does not use it here)

# Champions/elites (Act 2+): tougher packs whose drops the loot layer can upgrade.
# E.6 generalises this into a 3-tier ladder (game.mob_rarity): the champion is now
# the RARE tier, with a gentler MAGIC tier below it. CHAMPION_* kept as the RARE
# migration source of truth; mob_rarity.TIERS[RARE] mirrors these exact numbers.
CHAMPION_CHANCE = 0.06        # per non-boss spawn in act >= 2 (magic+rare combined)
CHAMPION_LIFE_MULT = 2.2      # +120% life
CHAMPION_DMG_MULT = 1.4       # +40% damage
CHAMPION_RARITY_TIER = 1      # +1 rarity weight tier on drops (read later by loot.py)


def scale_monster(tpl: MonsterTemplate, level: int, difficulty_mult: float,
                  rng: random.Random | None = None) -> Monster:
    r = rng or random
    m = level - 1
    life_mult = mob_life_mult(m) * difficulty_mult
    dmg_mult = mob_dmg_mult(m) * difficulty_mult
    var = r.uniform(0.9, 1.1)
    stats = Stats(
        life=tpl.base_life * life_mult * var,
        damage_min=tpl.base_dmin * dmg_mult,
        damage_max=tpl.base_dmax * dmg_mult,
        attack_speed=tpl.attack_speed,
        move_speed=tpl.move_speed,
        armor=tpl.armor * (1 + 0.10 * (level - 1)),
    )
    is_boss = tpl.xp_mult >= 5.0
    # XP rides the same accelerating family as life (life_mult^0.8) so hard mobs
    # pay fairly; replaces the old linear (1 + XP_GROWTH*(level-1)) factor.
    xp_mult_from_life = mob_life_mult(m) ** 0.8
    mon = Monster(
        name=tpl.name,
        stats=stats,
        facing=-1,
        monster_id=tpl.id,
        level=level,
        xp_reward=max(1, int(XP_BASE * tpl.xp_mult * xp_mult_from_life)),
        damage_type=tpl.damage_type,
        is_boss=is_boss,
        loot_bonus=2.0 if is_boss else 0.0,
    )
    # Runtime-only flags (Monster is a slot-less dataclass). loot.py reads these
    # via getattr; NOT wired into loot.py here per stage 6.4 ownership rules.
    mon.is_champion = False
    mon.rarity_tier_bonus = 0
    mon.rarity_tier = mob_rarity.COMMON  # E.6 default; _apply_mob_tier elevates
    mon.init_hp()
    return mon


def _apply_mob_tier(mon: Monster, tier: str) -> None:
    """E.6: elevate a spawned mob to a MAGIC/RARE tier (game.mob_rarity.TIERS).

    Multiplies life/dmg/xp, adds the loot rider + rarity-floor lift, and keeps the
    legacy `is_champion` flag TRUE for the RARE tier so existing readers (and the
    champion-pack zone mod) behave unchanged. COMMON is a no-op.
    """
    td = mob_rarity.TIERS.get(tier)
    if td is None or tier == mob_rarity.COMMON:
        return
    mon.rarity_tier = tier
    mon.name = f"{td.name_prefix}{mon.name}"
    mon.stats.life *= td.life_mult
    mon.stats.damage_min *= td.dmg_mult
    mon.stats.damage_max *= td.dmg_mult
    mon.xp_reward = max(1, int(mon.xp_reward * td.xp_mult))
    mon.loot_bonus += td.loot_bonus
    mon.rarity_tier_bonus = td.rarity_tier_bonus
    mon.is_champion = tier == mob_rarity.RARE
    mon.guaranteed_drop = td.guaranteed_drop
    mon.init_hp()


def _promote_champion(mon: Monster) -> None:
    """Back-compat shim: promote straight to the RARE tier (old champion)."""
    _apply_mob_tier(mon, mob_rarity.RARE)


class Spawner:
    MAX_ALIVE = 12
    REARM_MULT = 0.75  # re-farm: boss re-arms at 0.75x its kills_to_boss (rounded)

    def __init__(self, zone: Zone, difficulty_mult: float = 1.0,
                 rng: random.Random | None = None,
                 mod_ids: list[str] | None = None,
                 kills_to_boss_override: int | None = None,
                 mlvl_offset: int = 0):
        self.zone = zone
        self.difficulty_mult = difficulty_mult
        # Mandatory-loop model: higher difficulties raise the EFFECTIVE monster
        # level (life/damage/armor/xp all scale off it) so a fresh campaign loop
        # keeps out-pacing the XP-decay wall. Applied ONLY to combat scaling here,
        # never to zone_unlocked/gate checks (those stay on the raw monster_level,
        # or high loops would lock their own early zones).
        self.mlvl_offset = mlvl_offset
        self.rng = rng or random.Random()
        self.timer = zone.spawn_interval  # first pack spawns immediately
        self.kills = 0
        # 6.6: rifts pass their own kills_to_boss (60+10*tier); overworld zones
        # compute it from act + position (6.3).
        self.kills_to_boss = (kills_to_boss_override if kills_to_boss_override
                              else kills_to_boss(zone.act, zone_pos(zone)))
        self.rearm_kills = max(1, round(self.REARM_MULT * self.kills_to_boss))
        self.boss_spawned = False
        self.boss_killed = False
        self._rearm_at: int | None = None
        self.notice: str | None = None  # one-shot message for the UI to flash
        # 6.5: zone auto-mods. mod_ids is rolled+persisted by the caller (it knows
        # hero level + save state); the spawner just applies danger on spawn and
        # exposes the zone-local reward multipliers for the kill handler to use.
        self.mod_ids = list(mod_ids or [])
        self.reward_mults = zone_mods.reward_multipliers(self.mod_ids)
        self._pack_mult = zone_mods.pack_size_mult(self.mod_ids)
        self._extra_champ_packs = zone_mods.extra_champion_packs(self.mod_ids)

    def notify_kill(self, monster: Monster | None = None) -> None:
        self.kills += 1
        if monster is not None and monster.is_boss:
            self.boss_killed = True
            self._rearm_at = None
        if (self._rearm_at is not None and not self.boss_killed
                and self.kills >= self._rearm_at):
            self.boss_spawned = False
            self._rearm_at = None
            tpl = TEMPLATES[self.zone.boss_template_id]
            self.notice = f"The {tpl.name} returns..."

    def boss_despawned(self) -> None:
        """Boss vanished without dying (e.g. cleared off-screen): re-farm to re-arm.
        Re-arm threshold is 0.75x this zone's kills_to_boss (rounded), per 6.3."""
        if self.boss_spawned and not self.boss_killed and self._rearm_at is None:
            self._rearm_at = self.kills + self.rearm_kills

    def _spawn_pack(self, monsters: list[Monster], base_x: float) -> None:
        lo, hi = self.zone.pack_size
        n = self.rng.randint(lo, hi)
        # 6.5 horde: larger packs on juiced zones.
        n = round(n * self._pack_mult)
        alive = sum(1 for m in monsters if m.alive)
        n = min(n, self.MAX_ALIVE - alive)
        # 6.5 champions mod: extra champion packs raise the promotion odds.
        champ_chance = CHAMPION_CHANCE
        if self.zone.act >= 2 and self._extra_champ_packs:
            champ_chance = min(1.0, CHAMPION_CHANCE + 0.10 * self._extra_champ_packs)
        for i in range(n):
            tpl = TEMPLATES[self.rng.choice(self.zone.templates)]
            mon = scale_monster(tpl, self.zone.monster_level + self.mlvl_offset,
                                self.difficulty_mult, self.rng)
            mon.x = base_x + i * 18 + self.rng.uniform(-6, 6)
            # 6.4 / E.6: Act 2+ mobs roll an elite tier. champ_chance gates WHETHER
            # to elevate; roll_tier splits the magic:rare ratio within that.
            if self.zone.act >= 2 and self.rng.random() < champ_chance:
                _apply_mob_tier(mon, mob_rarity.roll_tier(self.rng))
            # 6.5: zone auto-mod danger applied per spawn (safe no-op if no mods).
            if self.mod_ids:
                zone_mods.apply_to_monster(mon, self.mod_ids)
            monsters.append(mon)

    def _spawn_boss(self, monsters: list[Monster], base_x: float) -> None:
        tpl = TEMPLATES[self.zone.boss_template_id]
        boss = scale_monster(tpl, self.zone.monster_level + self.mlvl_offset,
                             self.difficulty_mult, self.rng)
        boss.is_boss = True
        boss.loot_bonus = 2.0
        boss.x = base_x + self.rng.uniform(0, 10)
        # 6.5: zone mods juice the boss too (danger stacks, reward is zone-local).
        if self.mod_ids:
            zone_mods.apply_to_monster(boss, self.mod_ids)
        monsters.append(boss)
        self.boss_spawned = True

    def tick(self, dt: float, monsters: list[Monster], hero_x: float,
             view_width: float) -> None:
        base_x = hero_x + view_width
        if (self.zone.boss_template_id and not self.boss_spawned
                and not self.boss_killed and self.kills >= self.kills_to_boss):
            self._spawn_boss(monsters, base_x)
            return
        self.timer += dt
        if self.timer < self.zone.spawn_interval:
            return
        if sum(1 for m in monsters if m.alive) >= self.MAX_ALIVE:
            return
        self.timer = 0.0
        self._spawn_pack(monsters, base_x)


if __name__ == "__main__":
    rng = random.Random(42)

    print("=== Zones ===")
    assert len(ZONES) == 19
    assert sum(1 for z in ZONES if z.act == 3) == 6
    assert sum(1 for z in ZONES if z.act == 4) == 3
    for z in ZONES:
        boss = TEMPLATES[z.boss_template_id].name if z.boss_template_id else "-"
        print(f"  [{z.id}] {z.name}: mlvl {z.monster_level}, theme {z.bg_theme}, "
              f"pack {z.pack_size}, boss: {boss}")
        assert get_zone(z.id) is z
        assert z.flavor and len(z.flavor) <= 120, z.id
        for tid in z.templates:
            assert tid in TEMPLATES, tid

    print("\n=== Pack spawns (3 zones) ===")
    for zid in ("a1_shore", "a1_forest", "a1_ruins"):
        zone = get_zone(zid)
        sp = Spawner(zone, difficulty_mult=1.0, rng=random.Random(7))
        monsters: list[Monster] = []
        sp.tick(0.05, monsters, hero_x=100.0, view_width=800.0)
        print(f"  {zone.name}: pack of {len(monsters)}:")
        for m in monsters:
            print(f"    {m.name} lvl{m.level} hp={m.hp:.0f} "
                  f"dmg={m.stats.damage_min:.1f}-{m.stats.damage_max:.1f} "
                  f"x={m.x:.0f} xp={m.xp_reward}")
        assert all(m.x > 100.0 for m in monsters)

    print("\n=== kills_to_boss per zone (6.3) ===")
    # a1_ruins is pos 4 within Act 1 (5 zones), so kills_to_boss = round(24*(1+0.25*4)) = 48.
    for z in ZONES:
        p = zone_pos(z)
        ktb = kills_to_boss(z.act, p)
        print(f"  [{z.id}] act{z.act} pos{p}: kills_to_boss={ktb}")
        sp_chk = Spawner(z, rng=random.Random(1))
        assert sp_chk.kills_to_boss == ktb
        assert sp_chk.rearm_kills == max(1, round(0.75 * ktb))
    # spec table anchors (pos 0/1/2)
    assert [kills_to_boss(1, p) for p in (0, 1, 2)] == [24, 30, 36]
    assert [kills_to_boss(2, p) for p in (0, 1, 2)] == [38, 48, 58]
    assert [kills_to_boss(3, p) for p in (0, 1, 2)] == [61, 77, 92]
    assert [kills_to_boss(4, p) for p in (0, 1, 2)] == [98, 123, 147]

    print("\n=== Boss after kills_to_boss kills ===")
    zone = get_zone("a1_ruins")
    sp = Spawner(zone, rng=rng)
    monsters = []
    for _ in range(sp.kills_to_boss):
        sp.notify_kill()
    sp.tick(0.05, monsters, hero_x=0.0, view_width=800.0)
    assert sp.boss_spawned and monsters and monsters[0].is_boss
    b = monsters[0]
    assert b.name == "Goblin King"
    print(f"  {b.name} lvl{b.level} hp={b.hp:.0f} "
          f"dmg={b.stats.damage_min:.1f}-{b.stats.damage_max:.1f} xp={b.xp_reward}")
    sp.notify_kill(b)
    assert sp.boss_killed

    print("\n=== Act 2 boss ===")
    zone = get_zone("a2_great_tomb")
    assert zone.boss_template_id == "lich_emperor"
    lich = scale_monster(TEMPLATES["lich_emperor"], zone.monster_level, 1.0, rng)
    assert lich.is_boss and lich.name == "Lich Emperor"
    print(f"  {lich.name} lvl{lich.level} hp={lich.hp:.0f} "
          f"dmg={lich.stats.damage_min:.1f}-{lich.stats.damage_max:.1f} xp={lich.xp_reward}")

    print("\n=== Act 3 bosses ===")
    assert get_zone("a3_warcamp").boss_template_id == "orc_warlord"
    assert get_zone("a3_slime_pits").boss_template_id == "mother_of_slimes"
    zone = get_zone("a3_ashen_sanctum")
    assert zone.boss_template_id == "lord_of_ash"
    for tid, zid in (("orc_warlord", "a3_warcamp"),
                     ("mother_of_slimes", "a3_slime_pits"),
                     ("lord_of_ash", "a3_ashen_sanctum")):
        z = get_zone(zid)
        b = scale_monster(TEMPLATES[tid], z.monster_level, 1.0, rng)
        assert b.is_boss
        print(f"  {b.name} lvl{b.level} hp={b.hp:.0f} "
              f"dmg={b.stats.damage_min:.1f}-{b.stats.damage_max:.1f} "
              f"xp={b.xp_reward} type={b.damage_type.value}")
    ash = scale_monster(TEMPLATES["lord_of_ash"], 58, 1.0, rng)
    assert ash.name == "Lord of Ash" and ash.damage_type == DamageType.FIRE

    print("\n=== Scaling (levels 1/10/18) ===")
    for tid in ("goblin", "slime_magma", "demon"):
        tpl = TEMPLATES[tid]
        for lvl in (1, 10, 18):
            m = scale_monster(tpl, lvl, 1.0, rng)
            print(f"  {m.name} lvl{lvl}: hp={m.hp:.0f} "
                  f"dmg={m.stats.damage_min:.1f}-{m.stats.damage_max:.1f} "
                  f"armor={m.stats.armor:.0f} xp={m.xp_reward} type={m.damage_type.value}")

    m1 = scale_monster(TEMPLATES["goblin"], 5, 1.0, random.Random(1))
    m2 = scale_monster(TEMPLATES["goblin"], 5, 2.0, random.Random(1))
    assert m2.max_hp > m1.max_hp * 1.9
    print("\nworld OK")
