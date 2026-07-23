"""Regression test for SAVE-H1 (audit 18.07): Skills V2 progression must
survive a save/load roundtrip.

The bug: save.py pops the stale "keystones" key on load, but "keystones" was
still in skills_v2._REQUIRED_KEYS, so ensure_skills_v2's subset check
(_REQUIRED_KEYS <= set(sv)) failed on EVERY real save and reset the block to
defaults — wiping sxp / talents / awakened / tomes_read / tome-unlocked skills.

Run from repo root:  python tests/test_save_skills_v2_roundtrip.py
(NOT `python -m tests.x` — the environment has a conflicting site-packages `tests`.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import classes, skills_v2 as SV
from game.save import hero_from_dict, hero_to_dict


def _fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def test_progression_survives_roundtrip():
    """A hero with real Skills V2 progress must keep it across to_dict/from_dict."""
    hero = classes.make_hero("mage")
    hero.level = 30
    classes.apply_level_growth(hero)
    SV.ensure_skills_v2(hero)

    # Simulate genuine progress the player accrued.
    sv = hero.skills_v2
    a_skill = sv["loadout"]["slots"][0] or next(iter(sv["unlocked"]))
    sv["sxp"][a_skill] = 137
    sv["talents"][a_skill] = 1
    sv["awakened"] = [a_skill]
    sv["tomes_read"] = 3
    # A skill unlocked via a tome (not by level) must not be lost on load.
    tome_skill = "__tome_only_skill__"
    if tome_skill not in sv["unlocked"]:
        sv["unlocked"].append(tome_skill)

    d = hero_to_dict(hero)
    hero2 = hero_from_dict(d)
    sv2 = hero2.skills_v2

    if sv2.get("sxp", {}).get(a_skill) != 137:
        _fail(f"sxp wiped on load: {sv2.get('sxp')}")
    if sv2.get("talents", {}).get(a_skill) != 1:
        _fail(f"talents wiped on load: {sv2.get('talents')}")
    if a_skill not in sv2.get("awakened", []):
        _fail(f"awakening wiped on load: {sv2.get('awakened')}")
    if sv2.get("tomes_read") != 3:
        _fail(f"tomes_read wiped on load: {sv2.get('tomes_read')}")
    if tome_skill not in sv2.get("unlocked", []):
        _fail("tome-unlocked skill lost on load")
    print("1. progression survives save/load roundtrip OK")


def test_stale_keystones_key_dropped():
    """Legacy v1 saves carrying skills_v2['keystones'] must still load cleanly,
    with the dead key dropped and the rest of the block intact."""
    hero = classes.make_hero("warrior")
    hero.level = 20
    classes.apply_level_growth(hero)
    SV.ensure_skills_v2(hero)
    a_skill = hero.skills_v2["loadout"]["slots"][0] or next(iter(hero.skills_v2["unlocked"]))
    hero.skills_v2["sxp"][a_skill] = 42

    d = hero_to_dict(hero)
    d["skills_v2"]["keystones"] = {"old_pick": True}  # inject legacy dead key

    hero2 = hero_from_dict(d)
    if "keystones" in hero2.skills_v2:
        _fail("stale 'keystones' key not dropped on load")
    if hero2.skills_v2.get("sxp", {}).get(a_skill) != 42:
        _fail("legacy save lost sxp on load")
    print("2. stale keystones key dropped, block preserved OK")


def test_required_keys_no_keystones():
    """Guard the root cause directly: 'keystones' must not be a required key."""
    if "keystones" in SV._REQUIRED_KEYS:
        _fail("'keystones' is back in _REQUIRED_KEYS — SAVE-H1 will regress")
    if "keystones" in SV.default_skills_v2("mage", 1):
        _fail("'keystones' is back in default_skills_v2 — SAVE-H1 will regress")
    print("3. 'keystones' absent from _REQUIRED_KEYS and default block OK")


if __name__ == "__main__":
    test_progression_survives_roundtrip()
    test_stale_keystones_key_dropped()
    test_required_keys_no_keystones()
    print("\nALL SAVE/SKILLS_V2 ROUNDTRIP TESTS PASSED")
