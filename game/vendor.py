"""Vendor hourly shop: rolls a stock of items via game.loot, sells them for gold."""
from __future__ import annotations

import inspect
import random
from dataclasses import dataclass, field

from game.core import Hero, Item, Rarity
from game.economy import item_value

from game.item_roller import reroll_affixes as roll_affixes
from game.loot import _make_base
from game.save import item_from_dict, item_to_dict

try:
    from game.uniques import roll_unique as _roll_unique
except ImportError:
    _roll_unique = None

REFRESH_SEC = 3600
STOCK_SIZE = 8
BUYBACK_SIZE = 5
RARITY_WEIGHTS = {Rarity.NORMAL: 50.0, Rarity.MAGIC: 35.0,
                  Rarity.RARE: 14.0, Rarity.UNIQUE: 1.0}
STOCK_MARKUP = 4  # spec 6.3: vendor sells at 4x item_value


def _accepts_class_id(fn) -> bool:
    try:
        return "class_id" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _call_with_class_id(fn, *args, class_id: str | None = None, **kwargs):
    if class_id is not None and _accepts_class_id(fn):
        return fn(*args, class_id=class_id, **kwargs)
    return fn(*args, **kwargs)


def price(item: Item) -> int:
    return item_value(item) * STOCK_MARKUP


def _roll_stock_item(ilvl: int, rng: random.Random,
                     class_id: str | None = None) -> Item:
    rarity = rng.choices(list(RARITY_WEIGHTS),
                         weights=list(RARITY_WEIGHTS.values()))[0]
    if rarity is Rarity.UNIQUE and _roll_unique is not None:
        uniq = _call_with_class_id(_roll_unique, ilvl, rng, class_id=class_id)
        if uniq is not None:
            return uniq
        rarity = Rarity.RARE
    item = _make_base(ilvl, rng)
    item.rarity = rarity if rarity is not Rarity.UNIQUE else Rarity.RARE
    _call_with_class_id(roll_affixes, item, rng, class_id=class_id)
    return item


@dataclass
class Vendor:
    stock: list[Item] = field(default_factory=list)
    last_refresh: float = 0.0  # epoch seconds; 0.0 = stock never rolled
    # last items sold this visit, newest first; NOT serialized (cleared on close)
    buyback: list[Item] = field(default_factory=list)

    def refresh(self, ilvl: int, rng: random.Random, now: float,
                class_id: str | None = None) -> None:
        self.stock = [_roll_stock_item(ilvl, rng, class_id)
                      for _ in range(STOCK_SIZE)]
        self.last_refresh = now

    def maybe_refresh(self, ilvl: int, rng: random.Random, now: float,
                      class_id: str | None = None) -> bool:
        if self.last_refresh > 0.0 and now - self.last_refresh < REFRESH_SEC:
            return False
        self.refresh(ilvl, rng, now, class_id)
        return True

    def seconds_to_refresh(self, now: float) -> int:
        if self.last_refresh <= 0.0:
            return 0
        return max(0, int(self.last_refresh + REFRESH_SEC - now))

    def buy(self, hero: Hero, index: int) -> Item | None:
        """Deducts gold and returns the item; caller decides inventory vs stash."""
        if not 0 <= index < len(self.stock):
            return None
        cost = price(self.stock[index])
        if hero.gold < cost:
            return None
        hero.gold -= cost
        return self.stock.pop(index)

    def sell(self, hero: Hero, item: Item) -> int:
        """Vendor buys any item at item_value; returns the gold paid."""
        gold = item_value(item)
        hero.gold += gold
        self.buyback.insert(0, item)
        del self.buyback[BUYBACK_SIZE:]
        return gold

    def buy_back(self, hero: Hero, index: int) -> Item | None:
        """Deducts gold and returns the item; caller puts it into inventory."""
        if not 0 <= index < len(self.buyback):
            return None
        cost = item_value(self.buyback[index])  # same price it was sold for
        if hero.gold < cost:
            return None
        hero.gold -= cost
        return self.buyback.pop(index)

    def clear_buyback(self) -> None:
        self.buyback.clear()


def vendor_to_dict(v: Vendor) -> dict:
    return {
        "last_refresh": v.last_refresh,
        "stock": [item_to_dict(it) for it in v.stock],
    }


def vendor_from_dict(d: dict) -> Vendor:
    return Vendor(
        stock=[item_from_dict(it) for it in d.get("stock", [])],
        last_refresh=d.get("last_refresh", 0.0),
    )


if __name__ == "__main__":
    from game.core import Stats

    rng = random.Random(11)
    v = Vendor()
    now = 1_000_000.0

    # never rolled -> restocks regardless of the hour
    assert v.maybe_refresh(20, rng, now) is True
    assert len(v.stock) == STOCK_SIZE
    assert v.maybe_refresh(20, rng, now + 10) is False
    assert v.maybe_refresh(20, rng, now + REFRESH_SEC - 1) is False
    assert v.seconds_to_refresh(now + 10) == REFRESH_SEC - 10
    assert v.maybe_refresh(20, rng, now + REFRESH_SEC) is True
    assert len(v.stock) == STOCK_SIZE

    # rarity distribution: unique must stay genuinely rare (~1%)
    counts: dict[Rarity, int] = {r: 0 for r in Rarity}
    total = 0
    for i in range(400):
        v.refresh(20, rng, now + i)
        for it in v.stock:
            counts[it.rarity] += 1
            total += 1
    assert total == 400 * STOCK_SIZE
    uniq_share = counts[Rarity.UNIQUE] / total
    assert 0.002 <= uniq_share <= 0.03, uniq_share
    assert counts[Rarity.NORMAL] > counts[Rarity.MAGIC] > counts[Rarity.RARE]

    # buying: exact deduction, refuses when poor or index is bad
    v.refresh(20, rng, now)
    hero = Hero(name="Buyer", stats=Stats(), base_stats=Stats())
    first = v.stock[0]
    cost = price(first)
    assert cost == item_value(first) * 4  # spec 6.3
    hero.gold = cost - 1
    assert v.buy(hero, 0) is None and hero.gold == cost - 1
    hero.gold = cost + 37
    bought = v.buy(hero, 0)
    assert bought is first and hero.gold == 37
    assert len(v.stock) == STOCK_SIZE - 1
    assert v.buy(hero, len(v.stock)) is None and v.buy(hero, -1) is None
    assert bought not in hero.inventory  # caller decides inventory vs stash

    # selling: sell then buy_back is gold-neutral and returns the same object
    gold_before = hero.gold
    paid = v.sell(hero, bought)
    assert paid == item_value(bought) and paid >= 1
    assert hero.gold == gold_before + paid
    assert v.buyback[0] is bought
    got = v.buy_back(hero, 0)
    assert got is bought and hero.gold == gold_before
    assert not v.buyback

    # buyback caps at 5, newest first
    sold = [_make_base(20, rng) for _ in range(7)]
    for it in sold:
        v.sell(hero, it)
    assert len(v.buyback) == 5
    assert v.buyback == list(reversed(sold[-5:]))

    # buy_back refused when poor or index is bad: gold unchanged, item stays
    hero.gold = 0
    kept = len(v.buyback)
    assert v.buy_back(hero, 0) is None and hero.gold == 0
    assert v.buy_back(hero, kept) is None and v.buy_back(hero, -1) is None
    assert len(v.buyback) == kept and v.buyback[0] is sold[-1]

    v.clear_buyback()
    assert v.buyback == []

    # serialization round-trip; buyback is NOT serialized
    v.sell(hero, sold[0])
    d = vendor_to_dict(v)
    assert "buyback" not in d
    v2 = vendor_from_dict(d)
    assert v2.buyback == []
    assert v2.last_refresh == v.last_refresh
    assert len(v2.stock) == len(v.stock)
    for a, b in zip(v.stock, v2.stock):
        assert a.base_id == b.base_id and a.rarity is b.rarity
        assert a.ilvl == b.ilvl and a.name == b.name
        assert len(a.affixes) == len(b.affixes) and len(a.implicit) == len(b.implicit)
        assert price(a) == price(b)

    print(f"rarities over {total} items: " +
          ", ".join(f"{r.value} {counts[r] / total:.1%}" for r in Rarity))
    print("vendor OK")
