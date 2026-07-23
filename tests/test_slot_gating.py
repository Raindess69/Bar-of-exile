"""E.4 — rarity contract + affix slot-gating validator (ECONOMY_IDLE_SPEC §E.4).

The data (`data/affixes_v2.json`) and roller already implement the canon; these
tests LOCK the contract as a regression invariant so a future data edit can't
silently break it. Four guarantees:

  1. Rarity affix-count contract: Common=0, Magic 1-2, Rare 3-6 (10k rolls).
  2. Matrix health: every family in >=2 slots (move_speed exempt by design),
     every slot serves >=6 families (rolls never degenerate).
  3. Hard prohibitions from the spec: move_speed only on boots, attack_speed
     never on boots. No affix ever lands on a slot outside its `_slots`.
  4. Corrupt over-limit line respects slot-gating too (cube._make_corrupt_line).
"""
import random
from collections import defaultdict

from game.core import Item, Rarity, Slot
from game.item_roller import POOL, _FAMILY_OF
from game.loot import make_item

# Families intentionally single-slot by ITEMS/E.4 canon (move_speed is boots-only
# on purpose; phys flat/inc live on the weapon only in this data set).
_SINGLE_SLOT_OK = {"move_speed", "phys_flat", "phys_inc"}

# Slot enum values that participate in gear rolls.
_GEAR_SLOTS = [s.value for s in Slot]


def _family_slots() -> dict[str, set[str]]:
    fs: dict[str, set[str]] = defaultdict(set)
    for a in POOL:
        fs[a["family"]].update(a["_slots"])  # _slots already alias-resolved
    return fs


def _slot_families() -> dict[str, set[str]]:
    sf: dict[str, set[str]] = defaultdict(set)
    for a in POOL:
        for s in a["_slots"]:
            sf[s].add(a["family"])
    return sf


# ---------------------------------------------------------------- matrix health

def test_every_family_has_at_least_two_slots():
    offenders = {f: sorted(ss) for f, ss in _family_slots().items()
                 if len(ss) < 2 and f not in _SINGLE_SLOT_OK}
    assert not offenders, f"families with <2 slots (not exempt): {offenders}"


def test_every_gear_slot_serves_at_least_six_families():
    sf = _slot_families()
    thin = {s: len(sf.get(s, set())) for s in _GEAR_SLOTS if len(sf.get(s, set())) < 6}
    assert not thin, f"slots with <6 families (rolls degenerate): {thin}"


def test_hard_prohibitions():
    fs = _family_slots()
    assert fs.get("move_speed", set()) == {"boots"}, \
        f"move_speed must be boots-only, got {sorted(fs.get('move_speed', []))}"
    assert "boots" not in fs.get("attack_speed", set()), \
        "attack_speed must NEVER roll on boots"
    assert "gloves" not in fs.get("move_speed", set()), \
        "move_speed must NEVER roll on gloves"


# ---------------------------------------------------- rarity affix-count contract

def test_rarity_affix_count_contract():
    rng = random.Random(1337)
    counts = {Rarity.NORMAL: set(), Rarity.MAGIC: set(), Rarity.RARE: set()}
    for _ in range(10_000):
        it = make_item(40, rng)
        if it.rarity in counts:
            counts[it.rarity].add(len(it.affixes))
    assert counts[Rarity.NORMAL] <= {0}, f"Common must have 0 affixes, saw {counts[Rarity.NORMAL]}"
    assert counts[Rarity.MAGIC] and counts[Rarity.MAGIC] <= {1, 2}, \
        f"Magic must be 1-2, saw {sorted(counts[Rarity.MAGIC])}"
    assert counts[Rarity.RARE] and counts[Rarity.RARE] <= {3, 4, 5, 6}, \
        f"Rare must be 3-6, saw {sorted(counts[Rarity.RARE])}"


# ----------------------------------------------------------- gating on live rolls

def test_no_affix_lands_on_illegal_slot():
    """10k rolls: every rolled affix's family must be legal for the item's slot.

    Uniques are exempt by spec (their fixed stats bypass the gated pool), so only
    Magic/Rare drops — the ones drawn from the slot pool — are checked.
    """
    rng = random.Random(2024)
    fam_slots = _family_slots()
    violations = []
    for _ in range(10_000):
        it = make_item(40, rng)
        if it.rarity not in (Rarity.MAGIC, Rarity.RARE):
            continue
        slot = it.slot.value
        for a in it.affixes:
            fam = _FAMILY_OF.get(a.id, a.id)
            if slot not in fam_slots.get(fam, set()):
                violations.append((slot, fam, a.id))
    assert not violations, f"affixes on illegal slots: {violations[:10]}"


def test_corrupt_line_respects_slot_gating():
    """The cube over-limit line must draw only from the item's own slot pool."""
    from game import cube

    rng = random.Random(99)
    fam_slots = _family_slots()
    checked = 0
    for _ in range(3_000):
        # a fresh rare item on a random slot, high ilvl so corrupt pool is broad
        slot = rng.choice(list(Slot))
        it = Item(base_id="t", base_name="T", slot=slot, rarity=Rarity.RARE, ilvl=80)
        added = cube._make_corrupt_line(it, rng)
        if added is None:
            continue
        checked += 1
        fam = _FAMILY_OF.get(added.id, added.id)
        assert slot.value in fam_slots.get(fam, set()), \
            f"corrupt line {added.id} (fam {fam}) illegal on {slot.value}"
    assert checked > 100, f"expected many corrupt lines, only checked {checked}"
