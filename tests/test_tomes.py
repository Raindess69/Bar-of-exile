"""Unit tests for game.tomes (S.5 contract — Skill Tomes).

Run from repo root:  python tests/test_tomes.py
(NOT `python -m tests.x` — the environment has a conflicting site-packages `tests`.)
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import classes
from game import skills_v2 as SV
from game import tomes as T


def _mk_hero(class_id="warrior", level=10):
    hero = classes.make_hero(class_id)
    hero.level = level
    classes.apply_level_growth(hero)
    SV.ensure_skills_v2(hero)
    return hero


def _all_class_skill_ids(class_id):
    return [s.id for s in SV.load_skills_v2().values() if s.class_id == class_id]


# --- 1. drop roll: base rate + pity guarantee ----------------------------- #
def test_roll_and_pity():
    hero = _mk_hero()
    rng = random.Random(0)
    # a huge dry streak MUST guarantee a drop, whatever the rng rolls
    assert T.roll_tome_drop(hero, 1, rng, pity=10 ** 9) is True, "pity must guarantee"
    # with no pity the drop is rare — over many rolls it fires sometimes, but far
    # from always (sanity that it is not stuck on True/False)
    hits = sum(T.roll_tome_drop(hero, 1, random.Random(s), pity=0) for s in range(2000))
    assert 0 < hits < 2000, f"base-rate drops should be rare, got {hits}/2000"
    # act scaling lifts the rate
    lo = sum(T.roll_tome_drop(hero, 1, random.Random(s), pity=0) for s in range(3000))
    hi = sum(T.roll_tome_drop(hero, 3, random.Random(s), pity=0) for s in range(3000))
    assert hi > lo, f"higher act should drop more often ({hi} vs {lo})"
    # determinism: same rng state -> same answer
    a = T.roll_tome_drop(hero, 2, random.Random(42), pity=5)
    b = T.roll_tome_drop(hero, 2, random.Random(42), pity=5)
    assert a == b, "roll must be deterministic for a given rng"
    print("1. roll/pity OK")


# --- 2. reading a tome unlocks a locked skill ----------------------------- #
def test_read_unlocks():
    hero = _mk_hero(level=10)
    targets = T.readable_tome_targets(hero)
    assert targets, "a fresh lvl10 hero should have locked-but-reachable skills"
    # all targets are within +10 levels, locked, and of the hero's class
    unlocked = set(hero.skills_v2["unlocked"])
    skills = SV.load_skills_v2()
    for sid in targets:
        s = skills[sid]
        assert s.class_id == hero.class_id
        assert s.unlock_level <= hero.level + 10
        assert sid not in unlocked
    before = len(hero.skills_v2["unlocked"])
    res = T.read_tome(hero, 1, random.Random(3))
    assert res["kind"] == "unlock", res
    assert res["skill_id"] in targets
    assert res["skill_id"] in hero.skills_v2["unlocked"]
    assert len(hero.skills_v2["unlocked"]) == before + 1
    assert res["name"] == skills[res["skill_id"]].name
    print("2. read unlocks locked skill OK")


# --- 3. duplicate tome (nothing to unlock) -> skill XP -------------------- #
def test_read_duplicate_to_sxp():
    hero = _mk_hero(level=60)
    # force "everything reachable is already unlocked"
    hero.skills_v2["unlocked"] = _all_class_skill_ids(hero.class_id)
    assert T.readable_tome_targets(hero) == [], "should be nothing left to unlock"
    sxp_before = dict(hero.skills_v2.get("sxp", {}))
    act = 3
    res = T.read_tome(hero, act, random.Random(7))
    assert res["kind"] == "sxp", res
    assert res["amount"] == T.TOME_DUP_SXP_PER_ACT * act
    sid = res["skill_id"]
    assert sid is not None
    gained = hero.skills_v2["sxp"][sid] - sxp_before.get(sid, 0)
    assert gained == res["amount"], f"sxp should grow by {res['amount']}, got {gained}"
    print("3. duplicate -> sxp OK")


# --- 4. tomes_read increments on every read ------------------------------- #
def test_tomes_read_counter():
    hero = _mk_hero(level=10)
    start = hero.skills_v2.get("tomes_read", 0)
    rng = random.Random(11)
    for i in range(5):
        T.read_tome(hero, 1, rng)
        assert hero.skills_v2["tomes_read"] == start + i + 1
    print("4. tomes_read counter OK")


if __name__ == "__main__":
    test_roll_and_pity()
    test_read_unlocks()
    test_read_duplicate_to_sxp()
    test_tomes_read_counter()
    print("\nALL TOMES TESTS PASSED")
