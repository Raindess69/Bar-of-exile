"""E.5 greater-affix (stars) roll table — pure, rng-only, MF-independent.

A rolled affix line has a small chance to gain 1-4 ★. A star multiplies the
line's rolled magnitude by `star_mult`, which can push it ABOVE the affix's
normal roll_max (spec: "breaks tier cap"). The roll depends ONLY on rng — it is
deliberately NOT scaled by magic find / item_rarity, so player farming stats do
not inflate greater-affix odds (mirrors D4 masterworking feel).

Single source of truth: item_roller._make_affix calls star_roll once per line
and applies star_mult to the rolled value(s). Kept as a standalone module so the
table is unit-testable without the roller / core plumbing (test_greater_affix).
"""
from __future__ import annotations

import random

# (stars, per-line chance, magnitude multiplier). Chances are disjoint slices of
# a single rng draw; their sum (~8.95%) is the total chance of ANY star. Rarest
# first so the cumulative walk assigns the low-probability high tiers correctly.
_STAR_TABLE: list[tuple[int, float, float]] = [
    (4, 0.0005, 2.20),
    (3, 0.0040, 1.90),
    (2, 0.0200, 1.55),
    (1, 0.0650, 1.25),
]

_MULT: dict[int, float] = {s: m for s, _, m in _STAR_TABLE}


def star_roll(rng: random.Random) -> int:
    """Return 0 (no star) or 1-4. rng-only — never touched by magic find."""
    r = rng.random()
    acc = 0.0
    for stars, chance, _ in _STAR_TABLE:
        acc += chance
        if r < acc:
            return stars
    return 0


def star_mult(stars: int) -> float:
    """Magnitude multiplier for a star count. 0 -> 1.0 (no change)."""
    return _MULT.get(int(stars), 1.0)


def star_mark(stars: int) -> str:
    """Display prefix for a starred line ("" when no star)."""
    return "★" * int(stars) + " " if stars else ""


if __name__ == "__main__":
    rng = random.Random(0)
    n = 200_000
    counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for _ in range(n):
        counts[star_roll(rng)] += 1
    # empirical frequencies land near the table (loose bounds; seeded rng)
    assert 0.055 < counts[1] / n < 0.075, counts
    assert 0.014 < counts[2] / n < 0.026, counts
    assert counts[0] / n > 0.90
    assert star_mult(0) == 1.0 and star_mult(4) == 2.20
    assert star_mark(0) == "" and star_mark(2) == "★★ "
    print("greater_affix OK", counts)
