"""
game/gamble.py - Ferek's Game of Certainties.
D2-style gambling vendor with HoYoverse-style pity on Uniques. Pure logic, no UI.
Deterministic when given a seeded random.Random.

Rarity cascade per roll:
  1) Unique with probability unique_chance(pity); pity +1 per non-unique roll
  2) else Rare with RARE_CHANCE
  3) else Magic (floor - gambling never yields Normal)

Pity math (binding, from master brief):
  base 0.006; soft pity from roll 73: P(n) = 0.006 + 0.12*(n-72) for 73<=n<=79;
  P(80) = 1.0. Expected ~62.3 rolls, consolidated rate ~1.60%.

Keystone hooks (pass ids in the `keystones` set):
  ks_house_rules            cost -20%; BASE unique rate halved (pity ramp unchanged)
  ks_singularity_of_want    hard pity 60; soft pity disabled
  ks_loaded_dice            every 10th lifetime roll is at least Rare
  aks_fereks_silent_partner cost +25% (idle pity gain handled by game loop)
  aks_gilded_grudge         after a Unique, pity resets to 20 instead of 0

Integration (this repo): make_gambled_item() turns a roll() result into an
actual Item through the v2 pipeline (items.random_base + item_roller affixes,
uniques.roll_unique for uniques).
"""
import random

from game.core import Rarity, Slot
from game.item_roller import reroll_affixes
from game.items import random_base
from game.uniques import roll_unique
from game.unique_specials import GAMBLE_COST_MULT, DOUBLE_PITY_STEP

BASE_UNIQUE_RATE = 0.006
SOFT_PITY_START = 73   # first roll number with ramped chance
SOFT_PITY_STEP = 0.12
HARD_PITY = 80
RARE_CHANCE = 0.10
JEWELRY_MULT = 1.5
JEWELRY_SLOTS = ("ring", "amulet")


def gamble_cost(item_level, slot="weapon", keystones=frozenset()):
    """Gold cost of one gamble at the given item level."""
    cost = 40.0 * item_level + 15.0 * (item_level ** 1.35)
    if slot in JEWELRY_SLOTS:
        cost *= JEWELRY_MULT
    if "ks_house_rules" in keystones:
        cost *= 0.80
    if "aks_fereks_silent_partner" in keystones:
        cost *= 1.25
    # the_unbought_victory (gamble_cost_up): equipped unique adds +25% to gamble
    # cost — the boots are won, not bought, and resent being spent near.
    if "gamble_cost_up" in keystones:
        cost *= GAMBLE_COST_MULT
    return max(1, int(round(cost)))


def unique_chance(current_pity_counter, keystones=frozenset()):
    """Chance that the NEXT roll (roll number = pity+1) yields a Unique."""
    n = current_pity_counter + 1
    base = BASE_UNIQUE_RATE
    if "ks_house_rules" in keystones:
        base /= 2.0
    hard = 60 if "ks_singularity_of_want" in keystones else HARD_PITY
    if n >= hard:
        return 1.0
    if "ks_singularity_of_want" in keystones:
        return base  # soft pity disabled
    if n >= SOFT_PITY_START:
        return min(1.0, base + SOFT_PITY_STEP * (n - (SOFT_PITY_START - 1)))
    return base


def make_gambled_item(rarity, item_level, slot="weapon", rng=None,
                      class_id=None):
    """Build the actual Item for a successful roll() via the v2 pipeline.

    rarity: "unique" | "rare" | "magic" (from roll()['rarity']).
    Unique with no eligible base at this ilvl falls back to Rare (same
    unique_gate rule as ItemRoller).
    """
    rng = rng or random.Random()
    if rarity == "unique":
        uniq = roll_unique(item_level, rng, exclude_drop_only=True)
        if uniq is not None:
            return uniq
        rarity = "rare"
    item = random_base(item_level, rng, slot=Slot(slot), class_id=class_id)
    item.rarity = Rarity(rarity)
    reroll_affixes(item, rng, class_id)
    return item


class GambleVendor:
    """Stateful vendor. Serialize with to_dict()/from_dict() into save v3
    (fields: gamble_pity_counter, gamble_stats)."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.pity = 0
        self.lifetime_rolls = 0
        self.stats = {"unique": 0, "rare": 0, "magic": 0, "gold_spent": 0}

    def roll(self, item_level, slot="weapon", gold=None, keystones=frozenset()):
        """Perform one gamble. Returns a result dict; caller subtracts gold
        and generates the actual item of the returned rarity at `item_level`
        (+ any gamble_ilvl_bonus from the atlas) — see make_gambled_item()."""
        cost = gamble_cost(item_level, slot, keystones)
        if gold is not None and gold < cost:
            return {"ok": False, "reason": "not_enough_gold", "cost": cost}
        self.lifetime_rolls += 1
        p_unique = unique_chance(self.pity, keystones)
        if self.rng.random() < p_unique:
            rarity = "unique"
            self.pity = 20 if "aks_gilded_grudge" in keystones else 0
        else:
            # gamblers_paradox (double_pity): pity climbs +2 per non-unique roll
            # instead of +1, reaching the unique guarantee twice as fast.
            self.pity += DOUBLE_PITY_STEP if "double_pity" in keystones else 1
            rarity = "rare" if self.rng.random() < RARE_CHANCE else "magic"
            if rarity == "magic" and "ks_loaded_dice" in keystones and self.lifetime_rolls % 10 == 0:
                rarity = "rare"
        self.stats[rarity] += 1
        self.stats["gold_spent"] += cost
        return {"ok": True, "rarity": rarity, "cost": cost, "pity": self.pity,
                "unique_chance_next": unique_chance(self.pity, keystones)}

    def roll_item(self, item_level, slot="weapon", gold=None,
                  keystones=frozenset(), class_id=None):
        """roll() + item generation in one call. On success the result dict
        gains an 'item' key (game.core.Item)."""
        res = self.roll(item_level, slot, gold, keystones)
        if res["ok"]:
            res["item"] = make_gambled_item(res["rarity"], item_level, slot,
                                            self.rng, class_id)
        return res

    def to_dict(self):
        return {"pity": self.pity, "lifetime_rolls": self.lifetime_rolls, "stats": dict(self.stats)}

    @classmethod
    def from_dict(cls, d, rng=None):
        v = cls(rng)
        v.pity = d.get("pity", 0)
        v.lifetime_rolls = d.get("lifetime_rolls", 0)
        v.stats.update(d.get("stats", {}))
        return v


if __name__ == "__main__":
    # smoke: pity curve endpoints + a few real rolls through the v2 pipeline
    assert unique_chance(0) == 0.006 and unique_chance(79) == 1.0
    assert abs(unique_chance(72) - 0.126) < 1e-9
    assert gamble_cost(1) == 55 and gamble_cost(1, "ring") == 82
    v = GambleVendor(rng=random.Random(20260715))
    for _ in range(12):
        res = v.roll_item(30, slot="weapon", class_id="mage")
        it = res["item"]
        assert it.rarity in (Rarity.MAGIC, Rarity.RARE, Rarity.UNIQUE)
        print(f"[{it.rarity.value}] {it.display_name()} (cost {res['cost']}, pity {res['pity']})")
    ring = v.roll_item(30, slot="ring")["item"]
    assert ring.slot in (Slot.RING,) or ring.rarity is Rarity.UNIQUE
    v2 = GambleVendor.from_dict(v.to_dict())
    assert v2.pity == v.pity and v2.stats == v.stats
    print("gamble OK")
