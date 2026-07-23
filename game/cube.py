"""Transmutation cube: D2-style recipes over items. UI in ui/cube_panel.py."""
from __future__ import annotations

import random
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from game.core import Affix, Item, Rarity, Slot

from game import statmap
from game.greater_affix import star_mark
from game.item_roller import POOL, reroll_affixes as roll_affixes

try:
    from game.items import random_base as _random_base
except ImportError:
    _random_base = None

MAX_ILVL = 100  # matches progression.MAX_LEVEL


def _amulet_base(ilvl: int, rng: random.Random) -> Item:
    if _random_base is not None:
        return _random_base(ilvl, rng, slot=Slot.AMULET)
    return Item(base_id="cube_amulet", base_name="Amulet", slot=Slot.AMULET,
                rarity=Rarity.NORMAL, ilvl=ilvl, req_level=max(1, ilvl - 2))


@dataclass
class Recipe:
    id: str
    name: str
    check: Callable[[list[Item]], bool]
    apply: Callable[[list[Item], random.Random], list[Item]]


def _reforge(item: Item, rarity: Rarity, rng: random.Random) -> list[Item]:
    out = deepcopy(item)
    out.rarity = rarity
    roll_affixes(out, rng)
    return [out]


def _check_norm3(items: list[Item]) -> bool:
    return (len(items) == 3 and all(i.rarity is Rarity.NORMAL for i in items)
            and len({i.base_id for i in items}) == 1)


def _check_magic3(items: list[Item]) -> bool:
    return len(items) == 3 and all(i.rarity is Rarity.MAGIC for i in items)


def _check_reroll(items: list[Item]) -> bool:
    return (len(items) == 4
            and sum(i.rarity is Rarity.RARE for i in items) == 1
            and sum(i.rarity is Rarity.MAGIC for i in items) == 3)


def _check_rings(items: list[Item]) -> bool:
    return len(items) == 2 and all(i.slot is Slot.RING for i in items)


def _check_upgrade(items: list[Item]) -> bool:
    return len(items) == 3 and items[0].ilvl < MAX_ILVL


def _apply_magic3(items: list[Item], rng: random.Random) -> list[Item]:
    best = max(items, key=lambda i: i.ilvl)
    return _reforge(best, Rarity.RARE, rng)


def _apply_reroll(items: list[Item], rng: random.Random) -> list[Item]:
    rare = next(i for i in items if i.rarity is Rarity.RARE)
    return _reforge(rare, Rarity.RARE, rng)


def _apply_rings(items: list[Item], rng: random.Random) -> list[Item]:
    ilvl = max(1, (items[0].ilvl + items[1].ilvl) // 2)
    return _reforge(_amulet_base(ilvl, rng), Rarity.MAGIC, rng)


def _apply_upgrade(items: list[Item], rng: random.Random) -> list[Item]:
    out = deepcopy(items[0])
    out.ilvl = min(out.ilvl + 5, MAX_ILVL)
    return [out]


RECIPES: list[Recipe] = [
    Recipe("norm3_magic", "3 Normal (same base) -> Magic", _check_norm3,
           lambda items, rng: _reforge(items[0], Rarity.MAGIC, rng)),
    Recipe("magic3_rare", "3 Magic -> Rare", _check_magic3, _apply_magic3),
    Recipe("rare_reroll", "3 Magic + Rare -> reroll Rare", _check_reroll, _apply_reroll),
    Recipe("rings_amulet", "2 Rings -> Magic Amulet", _check_rings, _apply_rings),
    Recipe("ilvl_up", "3 items -> +5 item level (first item)", _check_upgrade,
           _apply_upgrade),
]


def has_corrupted(items: list[Item]) -> bool:
    """A corrupted item (corruption>=1) is locked out of every normal recipe;
    only further corruption accepts it. Single source of truth for the gate so
    the UI button (cube_panel) and transmute() agree."""
    return any(getattr(it, "corruption", 0) >= 1 for it in items)


def transmute(items: list[Item], rng: random.Random) -> tuple[list[Item] | None, str]:
    # cube step 1 gate: a corrupted item is locked out of every normal recipe
    # (3->1, ilvl_up, ...). Only further corruption accepts it.
    if has_corrupted(items):
        return None, "Corrupted items can only be corrupted further"
    for recipe in RECIPES:
        if recipe.check(items):
            return recipe.apply(items, rng), recipe.name
    return None, "No recipe matches"


# ===================================================================== #
#  CUBE REWORK STEP 1 — CORRUPTION (see CUBE_CORRUPTION_SPEC.md)         #
# ===================================================================== #
# One source of truth for every number the recipe rolls AND the UI shows.
# Tune the tables/costs here; the tooltip text is generated from the same
# constant, so it can never disagree with the roll (§5, §8).

# Gold cost per corruption level attempt: index 0 = Corrupt I, 1 = II, 2 = III.
CORRUPT_COST = [250, 1000, 2500]

# Outcome codes (stable ids — do not rename after commit, §6.6):
OUT_LINE = "line"        # ✨ over-limit affix added
OUT_DESTROY = "destroy"  # 💀 / 💨 item removed forever
OUT_DEGRADE = "degrade"  # 🎲 existing values re-rolled down
OUT_NOTHING = "nothing"  # 😐 corruption mark only

MAX_CORRUPTION = 3

# level (current corruption 0/1/2) -> rarity -> [(outcome, percent)], summing 100.
# level 0 (Corrupt I) is rarity-dependent; I/II and above use the "*" fallback.
# 10-tier ladder: higher tiers = scarier gamble (less chance of a free line, more
# chance of destruction) — EXALTED/SET/MYTHIC mirror RARE/UNIQUE odds, and a "*"
# fallback guarantees corruption_table() never KeyErrors on a new rarity.
CORRUPTION_TABLE: dict[int, dict] = {
    0: {
        Rarity.SCRAP:  [(OUT_LINE, 50), (OUT_DESTROY, 25), (OUT_DEGRADE, 15), (OUT_NOTHING, 10)],
        Rarity.NORMAL: [(OUT_LINE, 50), (OUT_DESTROY, 25), (OUT_DEGRADE, 15), (OUT_NOTHING, 10)],
        Rarity.MAGIC:  [(OUT_LINE, 25), (OUT_DESTROY, 40), (OUT_DEGRADE, 20), (OUT_NOTHING, 15)],
        Rarity.RARE:   [(OUT_LINE, 10), (OUT_DESTROY, 50), (OUT_DEGRADE, 25), (OUT_NOTHING, 15)],
        Rarity.EXALTED:[(OUT_LINE, 8),  (OUT_DESTROY, 55), (OUT_DEGRADE, 22), (OUT_NOTHING, 15)],
        Rarity.SET:    [(OUT_LINE, 6),  (OUT_DESTROY, 55), (OUT_DEGRADE, 24), (OUT_NOTHING, 15)],
        Rarity.UNIQUE: [(OUT_LINE, 5),  (OUT_DESTROY, 50), (OUT_DEGRADE, 25), (OUT_NOTHING, 20)],
        Rarity.MYTHIC: [(OUT_LINE, 4),  (OUT_DESTROY, 60), (OUT_DEGRADE, 21), (OUT_NOTHING, 15)],
        "*":           [(OUT_LINE, 10), (OUT_DESTROY, 50), (OUT_DEGRADE, 25), (OUT_NOTHING, 15)],
    },
    1: {"*": [(OUT_LINE, 25), (OUT_DESTROY, 75)]},
    2: {"*": [(OUT_LINE, 5),  (OUT_DESTROY, 95)]},
}

_ROMAN = ["I", "II", "III"]
# label text per outcome, for the chance tooltip (§5). Corrupt I uses the rich
# words; higher levels are a pure gamble (improve / VAPORIZED).
_LABELS_L0 = {OUT_LINE: "extra line", OUT_DESTROY: "DESTROYED",
              OUT_DEGRADE: "values drop", OUT_NOTHING: "no effect"}
_LABELS_HI = {OUT_LINE: "improve", OUT_DESTROY: "VAPORIZED"}

_POOL_BY_ID = {a["id"]: a for a in POOL}


@dataclass
class CorruptResult:
    outcome: str            # OUT_* code
    item: Item | None       # mutated item, or None when destroyed
    level: int = 0          # corruption level BEFORE this roll (0/1/2)
    added: Affix | None = None  # the over-limit line on OUT_LINE


def corruption_table(level: int, rarity: Rarity) -> list[tuple[str, int]]:
    """Outcome distribution for a roll at `level` (0/1/2) on `rarity`.

    L2: a fully-corrupted item (level >= MAX_CORRUPTION) has no table entry;
    clamp to the last defined level so callers never KeyError. The UI already
    gates via can_corrupt — this is defense-in-depth for direct callers."""
    by = CORRUPTION_TABLE[min(level, MAX_CORRUPTION - 1)]
    return by.get(rarity) or by["*"]


def corrupt_cost(item: Item) -> int:
    """Gold price of the NEXT corruption on this item."""
    return CORRUPT_COST[min(item.corruption, len(CORRUPT_COST) - 1)]


def can_corrupt(item: Item) -> tuple[bool, str]:
    """Gate: corruption 3 is terminal. Returns (ok, reason-if-not)."""
    if getattr(item, "corruption", 0) >= MAX_CORRUPTION:
        return False, "Already fully corrupted (III)"
    return True, ""


def corruption_chance_text(level: int, rarity: Rarity) -> str:
    """UI panel text, generated from CORRUPTION_TABLE (single source of truth)."""
    table = corruption_table(level, rarity)
    labels = _LABELS_L0 if level == 0 else _LABELS_HI
    parts = [f"{pct}% {labels[code]}" for code, pct in table]
    return f"Corrupt {_ROMAN[level]}: " + " / ".join(parts)


def _pick_outcome(table: list[tuple[str, int]], rng: random.Random) -> str:
    r = rng.random() * 100.0
    cum = 0.0
    for code, pct in table:
        cum += pct
        if r < cum:
            return code
    return table[-1][0]


def _affix_from_entry(entry: dict, rng: random.Random) -> Affix:
    """Build a live-pool affix (statmap only — no raw keys, grabля №10)."""
    stat = entry["stat"]
    if statmap.is_pair_stat(stat):
        x = rng.randint(entry["roll_min"], entry["roll_max"])
        y = rng.randint(entry["roll_min"], entry["roll_max"])
        lo, hi = min(x, y), max(x, y)
        mods = statmap.mods_for_pair(stat, lo, hi)
        line = entry["display"].replace("{lo}", str(lo)).replace("{hi}", str(hi))
    else:
        v = rng.randint(entry["roll_min"], entry["roll_max"])
        mods = statmap.mods_for(stat, v)
        line = entry["display"].replace("{v}", str(v))
    return Affix(id=entry["id"], name=entry["name"], is_prefix=entry["type"] == "prefix",
                 tier=entry["_tier"], mods=mods, lines=[line])


def _make_corrupt_line(item: Item, rng: random.Random) -> Affix | None:
    """✨ over-limit line: a random live-pool affix for the slot at item ilvl,
    ignoring prefix/suffix limits and family collisions (§2)."""
    slot = item.slot.value
    cands = [a for a in POOL if slot in a["_slots"] and a["ilvl_req"] <= item.ilvl]
    if not cands:
        return None
    weights = [a["weight"] for a in cands]
    entry = rng.choices(cands, weights=weights, k=1)[0]
    return _affix_from_entry(entry, rng)


def _degrade_pool_affix(affix: Affix, entry: dict, rng: random.Random) -> None:
    """🎲 re-roll one pool affix into [tier-min, current] — never higher.

    E.5: a greater-affix keeps its ★ count (affix.stars is untouched) and the
    line's ★ mark is re-applied — corruption degrades the magnitude, not the
    star tier, so a starred line survives corrupt-reroll visibly starred.
    """
    stat = entry["stat"]
    rmin = entry["roll_min"]
    mark = star_mark(getattr(affix, "stars", 0))
    nums = re.findall(r"-?\d+", affix.lines[0]) if affix.lines else []
    if statmap.is_pair_stat(stat):
        if len(nums) < 2:
            return
        cur_lo, cur_hi = int(nums[0]), int(nums[1])
        new_lo = min(rng.randint(rmin, max(rmin, cur_lo)), cur_lo)
        new_hi = min(rng.randint(new_lo, max(new_lo, cur_hi)), cur_hi)
        affix.mods = statmap.mods_for_pair(stat, new_lo, new_hi)
        affix.lines = [mark + entry["display"].replace("{lo}", str(new_lo)).replace("{hi}", str(new_hi))]
    else:
        if not nums:
            return
        cur = int(nums[0])
        new_v = min(rng.randint(rmin, max(rmin, cur)), cur)
        affix.mods = statmap.mods_for(stat, new_v)
        affix.lines = [mark + entry["display"].replace("{v}", str(new_v))]


def _degrade_unique(item: Item, rng: random.Random) -> None:
    """🎲 for uniques: shrink each positive mod into its lower half (×0.5..1.0).
    Penalty mods (negative / `more`) are left untouched so a downgrade can never
    accidentally *soften* a drawback into a buff (§2)."""
    for a in item.affixes:
        for m in a.mods:
            f = rng.uniform(0.5, 1.0)
            if m.flat > 0:
                m.flat = round(m.flat * f, 1)
            if m.inc > 0:
                m.inc = round(m.inc * f, 1)


def _degrade_item(item: Item, rng: random.Random) -> None:
    for affix in list(item.affixes) + list(item.corrupted_lines):
        entry = _POOL_BY_ID.get(affix.id)
        if entry is not None:
            _degrade_pool_affix(affix, entry, rng)
    if item.rarity is Rarity.UNIQUE:
        _degrade_unique(item, rng)


def corrupt_item(item: Item, rng: random.Random) -> CorruptResult:
    """Roll one corruption on `item` and APPLY the result in place (§2-§4).

    Does NOT deduct gold, delete the item, or save — the caller performs those
    around this call as one atomic unit (§6.1/§6.2/§6.4). On OUT_DESTROY the
    item is returned unmutated with item=None so the caller removes it through
    the single deletion path.
    """
    level = item.corruption
    if level >= MAX_CORRUPTION:
        # L2: terminal — never re-roll or push corruption past III (defense in
        # depth; the UI already blocks this via can_corrupt).
        return CorruptResult(OUT_NOTHING, item, level=level)
    table = corruption_table(level, item.rarity)
    code = _pick_outcome(table, rng)
    if code == OUT_DESTROY:
        return CorruptResult(OUT_DESTROY, None, level=level)
    added: Affix | None = None
    if code == OUT_LINE:
        added = _make_corrupt_line(item, rng)
        if added is None:
            code = OUT_NOTHING  # no valid affix for this slot -> just the mark
        else:
            item.corrupted_lines.append(added)
    elif code == OUT_DEGRADE:
        _degrade_item(item, rng)
    item.corruption = level + 1
    return CorruptResult(code, item, level=level, added=added)


def corrupt_flash_text(result: CorruptResult, item_name: str) -> str:
    """Result banner for the flash queue (§5)."""
    code = result.outcome
    if code == OUT_LINE and result.added is not None:
        line = result.added.lines[0] if result.added.lines else result.added.name
        return f"✨ CORRUPTED: +{line}!"
    if code == OUT_DESTROY:
        if result.level == 0:
            return f"💀 {item_name} was DESTROYED"
        return f"💨 {item_name} VAPORIZED"
    if code == OUT_DEGRADE:
        return f"🎲 {item_name} degraded..."
    return f"😐 {item_name} survived corruption"


if __name__ == "__main__":
    from game.loot import make_item

    rng = random.Random(7)

    def drop(ilvl: int, rarity: Rarity) -> Item:
        it = make_item(ilvl, rng)
        it.rarity = rarity
        roll_affixes(it, rng)
        return it

    def fmt(it: Item) -> str:
        mods = "; ".join(m.describe() for a in it.affixes for m in a.mods)
        return (f"[{it.rarity.value}] {it.display_name()} "
                f"({it.base_name}, {it.slot.value}, ilvl {it.ilvl})"
                + (f" | {mods}" if mods else ""))

    norm = drop(20, Rarity.NORMAL)
    norm3 = [deepcopy(norm) for _ in range(3)]
    magic3 = [drop(20 + i, Rarity.MAGIC) for i in range(3)]
    reroll4 = [drop(25, Rarity.MAGIC) for _ in range(3)] + [drop(30, Rarity.RARE)]
    rings = [drop(14, Rarity.MAGIC), drop(18, Rarity.NORMAL)]
    for r in rings:
        r.slot = Slot.RING
        r.base_id, r.base_name = "coral_ring", "Coral Ring"
        roll_affixes(r, rng)
    upgrade3 = [drop(98, Rarity.RARE), drop(5, Rarity.NORMAL), drop(6, Rarity.MAGIC)]

    cases = [norm3, magic3, reroll4, rings, upgrade3]
    for items in cases:
        result, name = transmute(items, rng)
        print(f"=== {name} ===")
        for it in items:
            print("  in : " + fmt(it))
        assert result is not None
        for it in result:
            print("  out: " + fmt(it))
        print()

    out, _ = transmute(norm3, rng)
    assert out[0].rarity is Rarity.MAGIC and out[0].base_id == norm.base_id
    out, _ = transmute(magic3, rng)
    assert out[0].rarity is Rarity.RARE and out[0].ilvl == 22
    out, _ = transmute(reroll4, rng)
    assert out[0].rarity is Rarity.RARE and out[0].ilvl == 30
    out, _ = transmute(rings, rng)
    assert out[0].slot is Slot.AMULET and out[0].rarity is Rarity.MAGIC and out[0].ilvl == 16
    out, _ = transmute(upgrade3, rng)
    assert out[0].ilvl == MAX_ILVL and out[0].rarity is Rarity.RARE
    result, msg = transmute([norm], rng)
    assert result is None and msg == "No recipe matches"
    print("cube OK:", len(RECIPES), "recipes")
