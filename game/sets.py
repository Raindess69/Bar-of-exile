"""Set items (Tier 6 of the 10-tier rarity ladder): green fixed-affix gear that
belongs to a named set. Wearing multiple pieces of one set grants escalating
bonuses at 2 / 3 / 4 pieces equipped.

Mirrors the data-module pattern of game.uniques: frozen dataclasses + a tuple of
hand-designed defs + pure builders/rollers. No file I/O, no Qt, deterministic
(rng passed in). Set bonuses fold into recalc as ordinary StatMods.

Set membership is encoded by `base_id`: every piece uses a dedicated `set_*`
base_id that never collides with game.items.BASES, so `set_id_of(item)` can
recover the owning set from a plain lookup — no new Item field needed.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from game.core import Affix, Item, Rarity, Slot, StatMod


@dataclass(frozen=True)
class PieceDef:
    """One equippable piece of a set. base_id must be globally unique."""
    base_id: str
    base_name: str
    slot: Slot
    mods: tuple[StatMod, ...]  # this piece's own fixed affixes


@dataclass(frozen=True)
class SetDef:
    id: str
    name: str
    min_ilvl: int
    pieces: tuple[PieceDef, ...]
    # threshold -> extra StatMods granted when that many pieces are equipped.
    # Full sets define {2, 3, 4}; a 3-piece set documents the {2, 3} subset.
    bonuses: dict[int, list[StatMod]] = field(default_factory=dict)


# --- hand-designed sets -----------------------------------------------------
SETS: tuple[SetDef, ...] = (
    # 1) Warrior / armour bulwark — stack armour + life, cap out with regen and
    #    boss damage. 4 pieces, full 2/3/4 ladder.
    SetDef("aegis_bulwark", "Aegis of the Bulwark", 20, (
        PieceDef("set_bulwark_helm", "Bulwark Helm", Slot.HELMET,
                 (StatMod("armor", flat=40), StatMod("life", flat=25))),
        PieceDef("set_bulwark_plate", "Bulwark Plate", Slot.BODY,
                 (StatMod("armor", flat=100), StatMod("life", flat=45))),
        PieceDef("set_bulwark_gauntlets", "Bulwark Gauntlets", Slot.GLOVES,
                 (StatMod("armor", flat=30), StatMod("res_fire", flat=12))),
        PieceDef("set_bulwark_greaves", "Bulwark Greaves", Slot.BOOTS,
                 (StatMod("armor", flat=30), StatMod("move_speed", inc=10))),
    ), {
        2: [StatMod("life", flat=40), StatMod("armor", inc=15)],
        3: [StatMod("life", flat=60), StatMod("res_fire", flat=15),
            StatMod("res_cold", flat=15)],
        4: [StatMod("life", flat=100), StatMod("life_regen", flat=5),
            StatMod("boss_damage_inc", flat=20)],
    }),
    # 2) Mage / caster arcanist — life + elemental added damage + global damage.
    #    4 pieces, full 2/3/4 ladder.
    SetDef("arcanist_vestments", "Vestments of the Arcanist", 24, (
        PieceDef("set_arcanist_hood", "Arcanist Hood", Slot.HELMET,
                 (StatMod("life", flat=20), StatMod("added_fire", flat=6))),
        PieceDef("set_arcanist_robe", "Arcanist Robe", Slot.BODY,
                 (StatMod("life", flat=40), StatMod("added_cold", flat=8))),
        PieceDef("set_arcanist_wraps", "Arcanist Wraps", Slot.GLOVES,
                 (StatMod("added_lightning", flat=8), StatMod("crit_chance", flat=2))),
        PieceDef("set_arcanist_pendant", "Arcanist Pendant", Slot.AMULET,
                 (StatMod("life", flat=25), StatMod("damage_inc", flat=10))),
    ), {
        2: [StatMod("added_fire", flat=6), StatMod("added_cold", flat=6),
            StatMod("added_lightning", flat=6)],
        3: [StatMod("damage_inc", flat=15), StatMod("res_fire", flat=10),
            StatMod("res_cold", flat=10), StatMod("res_lightning", flat=10)],
        4: [StatMod("damage_inc", flat=25), StatMod("crit_multi", flat=25),
            StatMod("cast_speed_inc", flat=15)],
    }),
    # 3) Archer / crit hawk — crit, attack speed, evasion, movement. 3 pieces:
    #    documents the {2, 3} subset (no 4-piece tier by design).
    SetDef("hawk_regalia", "Regalia of the Hawk", 24, (
        PieceDef("set_hawk_hood", "Hawk Hood", Slot.HELMET,
                 (StatMod("crit_chance", flat=3), StatMod("evasion", flat=30))),
        PieceDef("set_hawk_grips", "Hawk Grips", Slot.GLOVES,
                 (StatMod("attack_speed", inc=8), StatMod("evasion", flat=20))),
        PieceDef("set_hawk_treads", "Hawk Treads", Slot.BOOTS,
                 (StatMod("move_speed", inc=12), StatMod("evasion", flat=20))),
    ), {
        2: [StatMod("crit_chance", flat=5), StatMod("attack_speed", inc=6)],
        3: [StatMod("crit_multi", flat=30), StatMod("damage_inc", flat=15),
            StatMod("evasion", inc=20)],
    }),
)


# base_id -> owning set id (built once; every base_id is unique across SETS)
_BASE_TO_SET: dict[str, str] = {
    p.base_id: s.id for s in SETS for p in s.pieces
}
_SET_BY_ID: dict[str, SetDef] = {s.id: s for s in SETS}


def get_set(set_id: str) -> SetDef | None:
    return _SET_BY_ID.get(set_id)


def set_id_of(item: Item) -> str | None:
    """Recover the owning set id of an item (None if it is not a set piece)."""
    return _BASE_TO_SET.get(item.base_id)


def build_set_item(set_id: str, piece_index: int, ilvl: int,
                   rng: random.Random | None = None) -> Item:
    """Construct one Rarity.SET Item for the given set + piece.

    rng is accepted for signature parity with the other rollers; set items are
    fully fixed, so it is unused.
    """
    sd = _SET_BY_ID[set_id]
    piece = sd.pieces[piece_index]
    mods = [StatMod(m.stat, flat=m.flat, inc=m.inc, more=m.more) for m in piece.mods]
    affix = Affix(
        id=f"{set_id}_{piece_index}",
        name=sd.name,
        is_prefix=True,
        tier=0,
        mods=mods,
        lines=[m.describe() for m in mods],
    )
    return Item(
        base_id=piece.base_id,
        base_name=piece.base_name,
        slot=piece.slot,
        rarity=Rarity.SET,
        ilvl=ilvl,
        req_level=max(1, sd.min_ilvl),
        name=piece.base_name,
        affixes=[affix],
    )


def roll_set_item(ilvl: int, rng: random.Random) -> Item | None:
    """Pick a random set (min_ilvl <= ilvl) and a random piece. None if none
    qualify. Deterministic under a fixed rng seed."""
    eligible = [s for s in SETS if s.min_ilvl <= ilvl]
    if not eligible:
        return None
    sd = rng.choice(eligible)
    idx = rng.randrange(len(sd.pieces))
    return build_set_item(sd.id, idx, ilvl, rng)


def _equipped_counts(equipped_items: list[Item]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in equipped_items:
        if it is None:
            continue
        sid = set_id_of(it)
        if sid is not None:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def set_bonus_mods(equipped_items: list[Item]) -> list[StatMod]:
    """Union of every bonus StatMod whose piece threshold (2/3/4) is met, across
    all sets represented in the equipped items. Folded into recalc."""
    mods: list[StatMod] = []
    for sid, count in _equipped_counts(equipped_items).items():
        sd = _SET_BY_ID.get(sid)
        if sd is None:
            continue
        for threshold, bonus in sorted(sd.bonuses.items()):
            if count >= threshold:
                mods.extend(bonus)
    return mods


def active_set_summary(equipped_items: list[Item]) -> list[tuple[str, int, int]]:
    """(set_name, equipped_count, total_pieces) for every set with >=1 piece
    equipped — for the UI '2/4 pieces' counter. Ordered by SETS definition."""
    counts = _equipped_counts(equipped_items)
    out: list[tuple[str, int, int]] = []
    for sd in SETS:
        n = counts.get(sd.id, 0)
        if n > 0:
            out.append((sd.name, n, len(sd.pieces)))
    return out


if __name__ == "__main__":
    rng = random.Random(7)
    for sd in SETS:
        print(f"{sd.name} ({sd.id}) — {len(sd.pieces)} pieces, "
              f"bonuses at {sorted(sd.bonuses)}")
        for i, p in enumerate(sd.pieces):
            it = build_set_item(sd.id, i, sd.min_ilvl, rng)
            print(f"  [{p.slot.value:7s}] {it.display_name()}: "
                  + ", ".join(m.describe() for m in it.affixes[0].mods))
    print("sets OK:", len(SETS))
