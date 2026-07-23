#!/usr/bin/env python3
"""LOOT-M3 regression — unique special hooks & numeric mods are all live.

Two rule-holes were closed in earlier sessions and are pinned here so a future
edit can't silently reopen them:

  * drop_only (The Unbought Victory) must NOT be obtainable from gambling —
    roll_unique(exclude_drop_only=True) filters it out.
  * life_leech (Flesh-Forge Prototype) is now a NUMERIC life_leech_pct that
    routes through statmap onto the live Stats.life_leech field (not a
    display-only flavour line).

Plus a coverage guard: EVERY numeric mod on EVERY unique lands on a live engine
path (statmap-routed OR a real Stats field) — zero inert unique mods.

Run:
  python tests/test_unique_specials_live.py   (NOT via -m)
or:
  python -m pytest tests/test_unique_specials_live.py -q
"""
import dataclasses
import os
import random
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from game import statmap
from game.core import Stats, StatMod, apply_mods
from game.uniques import UNIQUES, roll_unique, _build


def _special_ids(u):
    return {sid for sid, _ in u.special}


# --- drop_only is filtered out of gambling but still rollable as a drop ------ #
def test_drop_only_excluded_from_gamble():
    drop_only = [u for u in UNIQUES if "drop_only" in _special_ids(u)]
    assert drop_only, "expected at least one drop_only unique (The Unbought Victory)"
    ids = {u.id for u in drop_only}

    # 400 gamble rolls at a high ilvl must never surface a drop_only unique.
    rng = random.Random(20200)
    for _ in range(400):
        it = roll_unique(99, rng, exclude_drop_only=True)
        if it is None:
            continue
        base_id = it.affixes[0].id
        assert base_id not in ids, f"drop_only unique {base_id} leaked into gamble"

    # ...but the same unique IS reachable on the normal drop path (no exclude).
    rng = random.Random(20200)
    seen = set()
    for _ in range(4000):
        it = roll_unique(99, rng, exclude_drop_only=False)
        if it is not None:
            seen.add(it.affixes[0].id)
    assert ids & seen, "drop_only unique unreachable even as a drop"


# --- life_leech is a live numeric stat, not a flavour line ------------------- #
def test_flesh_forge_leech_is_numeric():
    ff = next(u for u in UNIQUES if u.id == "flesh_forge_prototype")
    # the mod list carries the numeric key that statmap routes to Stats.life_leech
    keys = {m[0] for m in ff.mods}
    assert "life_leech_pct" in keys, "Flesh-Forge lost its numeric leech mod"
    assert statmap.has_engine_support("life_leech_pct")

    routed = statmap.mods_for("life_leech_pct", 2)
    assert any(sm.stat == "life_leech" and sm.flat == 2 for sm in routed), routed

    # end-to-end: the built item's mods actually raise Stats.life_leech.
    item = _build(ff, 38, random.Random(3))
    base = Stats()
    out = apply_mods(base, item.all_mods())
    assert out.life_leech >= 2.0, f"leech not applied: {out.life_leech}"


# --- coverage: no unique carries a truly inert numeric mod ------------------- #
def test_no_inert_unique_mods():
    real_fields = {f.name for f in dataclasses.fields(Stats)}
    inert = []
    for u in UNIQUES:
        for m in u.mods:
            for part in m[0].split("|"):
                if statmap.has_engine_support(part):
                    continue          # v2 key routed onto a live field
                if part in real_fields:
                    continue          # direct engine field
                inert.append((u.id, part))
    assert not inert, f"inert unique mods (dead raw keys): {inert}"


# --- every declared special id is wired (mirrors unique_specials self-check) - #
def test_every_special_is_wired():
    from game import unique_specials as us
    declared = {sid for u in UNIQUES for sid, _ in u.special}
    wired = set(us._SPECIAL_MODS) | set(us._SPECIAL_FLAGS)
    # drop_only = roller-side tag; life_leech = numeric stat (life_leech_pct).
    orphans = declared - wired - {"drop_only", "life_leech"}
    assert not orphans, f"unwired unique specials: {orphans}"


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("test_unique_specials_live OK")


if __name__ == "__main__":
    _run()
