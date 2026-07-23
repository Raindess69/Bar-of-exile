"""Economy v2 (step 6.1): formula-driven item values, gamble cost, bulk-sell.

item_value derives gold price from base (ilvl + slot), rarity and affix
quality. Affix quality needs the roll fraction q of each explicit affix; we
recover it by looking the affix up in item_roller.POOL and inverting the
statmap mod layout (see _recover_rolled). Unique affixes are inverted against
their UNIQUES def ranges; anything unrecognisable falls back to q = 0.5.
No static price tables, no config files.
"""
from __future__ import annotations

from game.core import Item, Rarity, Slot
from game import statmap
from game.item_roller import POOL
from game.uniques import UNIQUES

_POOL_BY_ID: dict[str, dict] = {a["id"]: a for a in POOL}
_UNIQUE_BY_ID = {u.id: u for u in UNIQUES}

_JEWELRY = (Slot.RING, Slot.AMULET, Slot.BELT)
# 10-tier ladder vendor multipliers (spec vendor_mult column). RELIC/PRIMAL are
# Item.modifier overlays, not rarities — their extra worth is applied on top in
# item_value via _MOD_MULT.
_RARITY_MULT: dict[Rarity, float] = {
    Rarity.SCRAP: 0.25, Rarity.NORMAL: 1.0, Rarity.MAGIC: 2.2, Rarity.RARE: 5.0,
    Rarity.EXALTED: 15.0, Rarity.SET: 20.0, Rarity.UNIQUE: 12.0, Rarity.MYTHIC: 500.0,
}
_MOD_MULT: dict[str, float] = {"relic": 150.0 / 40.0, "primal": 2000.0 / 40.0}


def _q(v: float, lo: float, hi: float) -> float:
    """Roll fraction 0..1 within [lo, hi]; degenerate range counts as perfect."""
    if hi <= lo:
        return 1.0
    return min(1.0, max(0.0, (v - lo) / (hi - lo)))


def _recover_rolled(affix, entry: dict) -> float | None:
    """Invert statmap: pull the rolled value back out of the affix mods."""
    stat = entry["stat"]
    if statmap.is_pair_stat(stat):
        if stat == "damage_flat_physical":
            # mods_for_pair stores lo in damage_min, hi in damage_max
            lo = next((m.flat for m in affix.mods if m.stat == "damage_min"), None)
            hi = next((m.flat for m in affix.mods if m.stat == "damage_max"), None)
            if lo is None or hi is None:
                return None
            return (lo + hi) / 2
        # elemental pairs collapse to one mod whose flat is already the average
        if affix.mods:
            return affix.mods[0].flat
        return None
    # single-value stats: mods_for puts v as flat or inc on the mapped field(s);
    # unknown keys become one inert raw mod carrying v as flat
    if affix.mods:
        m = affix.mods[0]
        return m.flat if m.flat else m.inc
    return None


def _unique_q(affix) -> float:
    """Average roll fraction across a unique's def entries (mods keep def order,
    one shared roll per entry, split stats repeat it)."""
    u = _UNIQUE_BY_ID.get(affix.id)
    if u is None:
        return 0.5
    qs: list[float] = []
    idx = 0
    for stats, lo, hi, kind in u.mods:
        if idx >= len(affix.mods):
            break
        m = affix.mods[idx]
        v = m.flat if kind == "flat" else m.inc
        qs.append(_q(v, lo, hi))
        idx += len(stats.split("|"))
    return sum(qs) / len(qs) if qs else 0.5


def _affix_q(item: Item, affix) -> float:
    entry = _POOL_BY_ID.get(affix.id)
    if entry is not None:
        v = _recover_rolled(affix, entry)
        if v is None:
            return 0.5
        return _q(v, entry["roll_min"], entry["roll_max"])
    if item.rarity is Rarity.UNIQUE:
        return _unique_q(affix)
    return 0.5  # legacy game.affixes ids etc. — flat deterministic fallback


def _affix_score(item: Item, affix) -> float:
    tier_pts = min(5, max(1, 6 - affix.tier))  # T1 best -> 5 pts; unique tier 0 -> 5
    return tier_pts * (0.5 + 0.5 * _affix_q(item, affix))


def item_value(item: Item) -> int:
    """Gold value: base(ilvl, slot) x rarity x affix quality, min 1. A relic/primal
    modifier (Item.modifier) multiplies the final worth per the ladder spec."""
    base = 6.0 + 2.0 * item.ilvl
    if item.slot in _JEWELRY:
        base *= 1.4
    quality = 1.0 + 0.15 * sum(_affix_score(item, a) for a in item.affixes)
    mult = _RARITY_MULT.get(item.rarity, 1.0)
    mult *= _MOD_MULT.get(getattr(item, "modifier", "") or "", 1.0)
    return max(1, int(base * mult * quality))


def gamble_cost(level: int, jewelry: bool = False) -> int:
    """Ferek gambling price (binding formula — do not change)."""
    cost = 40 * level + 15 * level ** 1.35
    if jewelry:
        cost *= 1.5
    return int(round(cost))  # same rounding as game.gamble.gamble_cost


def bulk_sell_threshold(player_level: int) -> int:
    """Items with ilvl below this are junk for one-click bulk sell."""
    return max(2, player_level - 5)


if __name__ == "__main__":
    import random

    from game.item_roller import ItemRoller
    from game.uniques import roll_unique

    plain = Item(base_id="x", base_name="X", slot=Slot.HELMET,
                 rarity=Rarity.NORMAL, ilvl=1)
    assert item_value(plain) == 8, item_value(plain)
    ring = Item(base_id="r", base_name="R", slot=Slot.RING,
                rarity=Rarity.NORMAL, ilvl=1)
    assert item_value(ring) == 11, item_value(ring)  # int(8 * 1.4)
    assert gamble_cost(1) == 55 and gamble_cost(1, jewelry=True) == 82
    assert bulk_sell_threshold(5) == 2 and bulk_sell_threshold(40) == 35

    roller = ItemRoller(random.Random(42))
    for ilvl in (1, 20, 40):
        print(f"=== ilvl {ilvl} (gamble_cost {gamble_cost(ilvl)}) ===")
        seen: dict[Rarity, Item] = {}
        while len(seen) < 3:
            it = roller.roll(ilvl, magic_find=50.0)
            if it.rarity is not Rarity.UNIQUE:
                seen.setdefault(it.rarity, it)
        uniq = roll_unique(ilvl, random.Random(ilvl))
        if uniq is not None:
            seen[Rarity.UNIQUE] = uniq
        for rar in (Rarity.NORMAL, Rarity.MAGIC, Rarity.RARE, Rarity.UNIQUE):
            it = seen.get(rar)
            if it is None:
                continue
            v = item_value(it)
            assert v >= 1 and item_value(it) == v  # deterministic
            print(f"  [{rar.value:6s}] {it.display_name():34s} -> {v} gold")
    print("economy OK")
