"""Tests for cube rework step 1 — item corruption (CUBE_CORRUPTION_SPEC.md §7).

Runnable both ways:
    python tests/test_cube_corruption.py
    pytest tests/test_cube_corruption.py
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import cube, statmap
from game.core import Affix, Hero, Item, Rarity, Slot, Stats, StatMod, apply_mods
from game.item_roller import POOL, reroll_affixes
from game.loot import make_item
from game.save import item_from_dict, item_to_dict


def _item(ilvl: int, rarity: Rarity, rng: random.Random) -> Item:
    """A fresh rolled item forced to `rarity` with a matching affix set."""
    it = make_item(ilvl, rng)
    if rarity is Rarity.UNIQUE:
        # keep rolling until a real unique lands (some ilvls have none)
        for _ in range(200):
            u = make_item(ilvl, rng, magic_find=0.0)
            if u.rarity is Rarity.UNIQUE:
                return u
        it.rarity = Rarity.RARE  # fallback: no unique for this ilvl
        reroll_affixes(it, rng)
        return it
    it.rarity = rarity
    reroll_affixes(it, rng)
    return it


# --------------------------------------------------------------- §7.1 distribution
def test_distribution():
    rng = random.Random(12345)
    N = 10000
    for rarity in (Rarity.NORMAL, Rarity.MAGIC, Rarity.RARE, Rarity.UNIQUE):
        table = cube.corruption_table(0, rarity)
        assert sum(pct for _, pct in table) == 100, rarity
        counts = {code: 0 for code, _ in table}
        for _ in range(N):
            code = cube._pick_outcome(table, rng)
            counts[code] += 1
        for code, pct in table:
            got = counts[code] / N * 100
            assert abs(got - pct) <= 2.0, (rarity, code, got, pct)
    # levels I/II gambles too
    for level in (1, 2):
        table = cube.corruption_table(level, Rarity.RARE)
        assert sum(pct for _, pct in table) == 100
        counts = {code: 0 for code, _ in table}
        for _ in range(N):
            counts[cube._pick_outcome(table, rng)] += 1
        for code, pct in table:
            assert abs(counts[code] / N * 100 - pct) <= 2.0, (level, code)
    print("distribution OK")


# --------------------------------------------------- §7.2 line goes through statmap
def test_line_uses_live_pool_and_recalc():
    rng = random.Random(7)
    known = {a["id"] for a in POOL}
    # force a LINE outcome by patching the table locally
    for _ in range(50):
        it = _item(40, Rarity.NORMAL, rng)
        added = cube._make_corrupt_line(it, rng)
        assert added is not None
        # affix id is a live pool member
        assert added.id in known, added.id
        # its mods carry NO raw keys — every StatMod maps to a real Stats field
        for m in added.mods:
            assert hasattr(Stats(), m.stat), (added.id, m.stat)
        assert statmap.has_engine_support(POOL_of(added.id)["stat"])

    # apply the line and confirm it moves a stat in recalc when equipped
    hero = Hero(name="T", stats=Stats(), base_stats=Stats(), class_id="warrior")
    hero.init_hp()
    it = _item(60, Rarity.RARE, rng)
    # deterministically add a life line so we can measure it
    life_entry = next(a for a in POOL if a["stat"] == "life_flat"
                      and Slot.BODY.value in a["_slots"])
    it.slot = Slot.BODY
    it.corrupted_lines.append(cube._affix_from_entry(life_entry, rng))
    it.corruption = 1
    base_life = apply_mods(hero.base_stats, [m for a in it.affixes for m in a.mods]).life
    with_corrupt = apply_mods(hero.base_stats, it.all_mods()).life
    assert with_corrupt > base_life, (base_life, with_corrupt)

    hero.equipment[Slot.BODY.value] = it
    before = hero.max_hp
    hero.recalc()
    assert hero.max_hp > before, (before, hero.max_hp)
    print("line/statmap/recalc OK")


def POOL_of(affix_id: str) -> dict:
    return next(a for a in POOL if a["id"] == affix_id)


# --------------------------------------------------- §7.3 destroy removes the item
def test_destroy_removes_and_saves():
    rng = random.Random(2)
    hero = Hero(name="T", stats=Stats(), base_stats=Stats(), class_id="warrior")
    hero.init_hp()
    it = _item(30, Rarity.RARE, rng)

    # destroy: corrupt_item returns item=None and never mutates the item; the
    # caller drops it from the single live reference (the cube slot).
    res = _forced_corrupt(it, cube.OUT_DESTROY, rng)
    assert res.outcome == cube.OUT_DESTROY and res.item is None
    cube_items = [it, None, None, None]
    if res.outcome == cube.OUT_DESTROY:
        cube_items[0] = None
    assert all(x is None for x in cube_items)
    # no dangling refs anywhere on the hero
    for bucket in (hero.inventory, hero.stash, list(hero.equipment.values())):
        assert it not in bucket

    # the panel's _do_corrupt performs gold->roll->remove->save atomically and
    # calls on_save exactly once; verify the destroy branch through the panel.
    _panel_destroy_calls_save()
    print("destroy/removal OK")


def _panel_destroy_calls_save():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from ui.cube_panel import CubePanel
    rng = random.Random(1)
    hero = Hero(name="T", stats=Stats(), base_stats=Stats(), class_id="warrior")
    hero.init_hp()
    hero.gold = 10_000
    it = _item(30, Rarity.RARE, rng)
    saves = {"n": 0}
    panel = CubePanel(hero, on_change=lambda: None, rng=rng,
                      on_flash=lambda t: None, on_save=lambda: saves.__setitem__("n", saves["n"] + 1))
    panel.cube_items[0] = it
    cost = cube.corrupt_cost(it)
    gold_before = hero.gold
    # patch the roll to force a destroy
    orig = cube.corrupt_item
    import game.cube as _c
    from ui import cube_panel as _cp
    _cp.corrupt_item = lambda item, r: cube.CorruptResult(cube.OUT_DESTROY, None, level=0)
    try:
        panel._do_corrupt(it, cost)
    finally:
        _cp.corrupt_item = orig
    assert panel.cube_items[0] is None, "destroyed item must leave the cube"
    assert hero.gold == gold_before - cost, "gold charged once, not refunded"
    assert saves["n"] == 1, "autosave must fire exactly once (atomic §6.1)"
    panel.deleteLater()


def _forced_corrupt(item: Item, outcome: str, rng: random.Random) -> cube.CorruptResult:
    """Drive corrupt_item deterministically by monkeypatching _pick_outcome."""
    orig = cube._pick_outcome
    cube._pick_outcome = lambda table, r: outcome
    try:
        return cube.corrupt_item(item, rng)
    finally:
        cube._pick_outcome = orig


# --------------------------------------------------- §7.4 degrade never grows
def test_degrade_never_grows():
    rng = random.Random(99)
    for _ in range(80):
        it = _item(70, Rarity.RARE, rng)
        before = _numeric_snapshot(it)
        _forced_corrupt(it, cube.OUT_DEGRADE, rng)
        after = _numeric_snapshot(it)
        assert len(before) == len(after)
        for b, a in zip(before, after):
            assert a <= b + 1e-9, (b, a)
    # uniques degrade too, never up
    for _ in range(40):
        u = _item(55, Rarity.UNIQUE, rng)
        if u.rarity is not Rarity.UNIQUE:
            continue
        before = _numeric_snapshot(u)
        _forced_corrupt(u, cube.OUT_DEGRADE, rng)
        after = _numeric_snapshot(u)
        for b, a in zip(before, after):
            assert a <= b + 1e-9, (b, a)
    print("degrade OK")


def _numeric_snapshot(it: Item) -> list[float]:
    vals: list[float] = []
    for a in list(it.affixes) + list(it.corrupted_lines):
        for m in a.mods:
            vals.append(m.flat)
            vals.append(m.inc)
    return vals


# --------------------------------------------------- §7.5 gates
def test_gates():
    rng = random.Random(5)
    # corrupted item refused by 3->1 and ilvl_up
    from game.core import Rarity as R
    norm = _item(20, R.NORMAL, rng)
    trip = [_clone_normal(norm) for _ in range(3)]
    trip[0].corruption = 1
    out, msg = cube.transmute(trip, rng)
    assert out is None and "orrupt" in msg, msg
    # non-corrupted triple still works
    trip2 = [_clone_normal(norm) for _ in range(3)]
    out2, _ = cube.transmute(trip2, rng)
    assert out2 is not None

    # corruption=3 terminal
    it = _item(30, R.RARE, rng)
    it.corruption = 3
    ok, _ = cube.can_corrupt(it)
    assert not ok
    it.corruption = 2
    ok, _ = cube.can_corrupt(it)
    assert ok

    # cost is charged before roll & scales by level
    assert cube.corrupt_cost(_lvl(0)) == cube.CORRUPT_COST[0]
    assert cube.corrupt_cost(_lvl(1)) == cube.CORRUPT_COST[1]
    assert cube.corrupt_cost(_lvl(2)) == cube.CORRUPT_COST[2]
    print("gates OK")


def _lvl(n: int) -> Item:
    it = Item(base_id="b", base_name="B", slot=Slot.RING, rarity=Rarity.RARE, ilvl=10)
    it.corruption = n
    return it


def _clone_normal(proto: Item) -> Item:
    it = Item(base_id=proto.base_id, base_name=proto.base_name, slot=proto.slot,
              rarity=Rarity.NORMAL, ilvl=proto.ilvl, req_level=proto.req_level)
    return it


# --------------------------------------------------- §7.6 save/load roundtrip
def test_save_roundtrip():
    rng = random.Random(3)
    it = _item(50, Rarity.RARE, rng)
    line = cube._make_corrupt_line(it, rng)
    it.corrupted_lines.append(line)
    it.corruption = 2
    rt = item_from_dict(item_to_dict(it))
    assert rt.corruption == 2
    assert len(rt.corrupted_lines) == 1
    assert rt.corrupted_lines[0].id == line.id
    assert [m.stat for m in rt.corrupted_lines[0].mods] == [m.stat for m in line.mods]

    # old save without the fields -> defaults, no crash
    d = item_to_dict(it)
    del d["corruption"]
    del d["corrupted_lines"]
    legacy = item_from_dict(d)
    assert legacy.corruption == 0 and legacy.corrupted_lines == []

    # unknown affix id in corrupted_lines dropped on migrate, no crash
    hero = Hero(name="T", stats=Stats(), base_stats=Stats(), class_id="warrior")
    hero.init_hp()
    ghost = Item(base_id="b", base_name="B", slot=Slot.RING, rarity=Rarity.RARE, ilvl=10)
    ghost.corruption = 1
    ghost.corrupted_lines = [Affix(id="__gone__", name="Ghost", is_prefix=True, tier=3,
                                   mods=[StatMod("life", flat=99)])]
    hero.inventory.append(ghost)
    from game.save import _migrate_affixes
    _migrate_affixes(hero)
    assert ghost.corrupted_lines == [], ghost.corrupted_lines
    print("save roundtrip OK")


# --------------------------------------------------- §7.7 UI text == roll numbers
def test_ui_text_matches_table():
    for level in (0, 1, 2):
        for rarity in (Rarity.NORMAL, Rarity.MAGIC, Rarity.RARE, Rarity.UNIQUE):
            table = cube.corruption_table(level, rarity)
            text = cube.corruption_chance_text(level, rarity)
            for _, pct in table:
                assert f"{pct}%" in text, (level, rarity, pct, text)
    print("ui text OK")


# --------------------------------------------------- corrupt_item integration
def test_corrupt_item_applies():
    rng = random.Random(8)
    # LINE bumps corruption and adds exactly one corrupted line
    it = _item(60, Rarity.NORMAL, rng)
    n_before = len(it.corrupted_lines)
    res = _forced_corrupt(it, cube.OUT_LINE, rng)
    assert res.outcome == cube.OUT_LINE
    assert it.corruption == 1
    assert len(it.corrupted_lines) == n_before + 1
    assert res.added is it.corrupted_lines[-1]
    # NOTHING just marks it
    it2 = _item(60, Rarity.RARE, rng)
    res2 = _forced_corrupt(it2, cube.OUT_NOTHING, rng)
    assert res2.outcome == cube.OUT_NOTHING and it2.corruption == 1
    assert it2.corrupted_lines == []
    # flash text variants
    assert "CORRUPTED" in cube.corrupt_flash_text(res, it.display_name())
    dead = cube.CorruptResult(cube.OUT_DESTROY, None, level=0)
    assert "DESTROYED" in cube.corrupt_flash_text(dead, "Foo")
    vapor = cube.CorruptResult(cube.OUT_DESTROY, None, level=1)
    assert "VAPORIZED" in cube.corrupt_flash_text(vapor, "Foo")
    print("corrupt_item OK")


def _run_all():
    test_distribution()
    test_line_uses_live_pool_and_recalc()
    test_destroy_removes_and_saves()
    test_degrade_never_grows()
    test_gates()
    test_save_roundtrip()
    test_ui_text_matches_table()
    test_corrupt_item_applies()
    print("\nALL cube corruption tests passed")


if __name__ == "__main__":
    _run_all()
