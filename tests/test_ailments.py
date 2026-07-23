#!/usr/bin/env python3
"""Plain-assert tests for game/ailments.py (standalone, no combat integration).
Run: python tests/test_ailments.py  (NOT via -m)."""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from game import ailments as al
from game.core import DamageType, Hero, Monster, Stats


class Roll:
    """Deterministic rng: uniform() returns the preset value (0 => always hit)."""
    def __init__(self, value: float = 0.0):
        self.value = value

    def uniform(self, a: float, b: float) -> float:
        return self.value


ALWAYS = Roll(0.0)
NEVER = Roll(100.0)  # uniform() >= chance for any chance <= 100 => never applies


def mob(boss: bool = False, x: float = 0.0) -> Monster:
    m = Monster(name="Dummy", stats=Stats(life=10_000.0, attack_speed=1.0),
                x=x, is_boss=boss)
    m.init_hp()
    return m


def drain(target, duration: float, dt: float = 0.05, flags=frozenset()) -> float:
    """Tick for `duration` seconds, return total DoT damage."""
    total, t = 0.0, 0.0
    while t < duration - 1e-9:
        total += al.tick_ailments(target, dt, set(flags))
        t += dt
    return total


ALL_CHANCES = {f"{k}_chance_pct": 100.0 for k in al.AILMENT_ORDER}


# --- 1. each ailment applies and expires -------------------------------------
def test_apply_and_expire():
    for kind, dtype, dur in [
        ("ignite", DamageType.FIRE, al.IGNITE_DURATION),
        ("bleed", DamageType.PHYS, al.BLEED_DURATION),
        ("poison", DamageType.CHAOS, al.POISON_DURATION),
        ("freeze", DamageType.COLD, al.FREEZE_STOP_DURATION + al.FREEZE_SLOW_DURATION),
        ("shock", DamageType.LIGHTNING, al.SHOCK_DURATION),
        ("stun", DamageType.PHYS, al.STUN_DURATION),
    ]:
        m = mob()
        got = al.try_apply_on_hit(m, 100.0, dtype, ALL_CHANCES, {}, set(), ALWAYS)
        assert kind in got, (kind, got)
        assert kind in al.active_icons(m), kind
        drain(m, dur + 0.3)
        assert kind not in al.active_icons(m), f"{kind} did not expire"
    # wrong damage type does not trigger the typed ailments
    m = mob()
    got = al.try_apply_on_hit(m, 100.0, DamageType.FIRE,
                              {"bleed_chance_pct": 100.0, "freeze_chance_pct": 100.0},
                              {}, set(), ALWAYS)
    assert got == [], got
    # failed roll applies nothing
    m = mob()
    assert al.try_apply_on_hit(m, 100.0, DamageType.FIRE, ALL_CHANCES, {}, set(), NEVER) == []
    # hero can only receive stun
    h = Hero(name="H", stats=Stats(), base_stats=Stats())
    h.init_hp()
    got = al.try_apply_on_hit(h, 100.0, DamageType.FIRE, ALL_CHANCES, {}, set(), ALWAYS)
    assert got == ["stun"] and al.active_icons(h) == ["stun"], got


# --- 2. poison stacking ------------------------------------------------------
def test_poison_stacking():
    m = mob()
    for _ in range(5):
        al.try_apply_on_hit(m, 100.0, DamageType.CHAOS,
                            {"poison_chance_pct": 100.0}, {}, set(), ALWAYS)
    assert len(al.get_state(m).poisons) == al.POISON_MAX_STACKS == 3
    # each stack is a full instance: total = 3 * 60% * 100
    total = drain(m, al.POISON_DURATION + 0.3)
    assert abs(total - 3 * al.POISON_PCT * 100.0) < 1e-6, total
    # at cap a stronger poison replaces the weakest
    m = mob()
    for dmg in (100.0, 100.0, 100.0):
        al.try_apply_on_hit(m, dmg, DamageType.CHAOS,
                            {"poison_chance_pct": 100.0}, {}, set(), ALWAYS)
    got = al.try_apply_on_hit(m, 500.0, DamageType.CHAOS,
                              {"poison_chance_pct": 100.0}, {}, set(), ALWAYS)
    assert got == ["poison"]
    st = al.get_state(m)
    assert len(st.poisons) == 3
    assert abs(max(p.dps for p in st.poisons) * al.POISON_DURATION
               - al.POISON_PCT * 500.0) < 1e-6
    # ...but a weaker one at cap is rejected
    got = al.try_apply_on_hit(m, 50.0, DamageType.CHAOS,
                              {"poison_chance_pct": 100.0}, {}, set(), ALWAYS)
    assert got == [] and len(al.get_state(m).poisons) == 3
    # plaguebearer: raised but FINITE cap (audit M3 — no unbounded growth)
    m = mob()
    for _ in range(7):
        al.try_apply_on_hit(m, 100.0, DamageType.CHAOS,
                            {"poison_chance_pct": 100.0}, {}, {"plaguebearer"}, ALWAYS)
    assert len(al.get_state(m).poisons) == 7  # below cap: all stack
    # hammer well past the cap — must clamp at PLAGUEBEARER_MAX_STACKS, not grow forever
    for _ in range(100):
        al.try_apply_on_hit(m, 100.0, DamageType.CHAOS,
                            {"poison_chance_pct": 100.0}, {}, {"plaguebearer"}, ALWAYS)
    assert len(al.get_state(m).poisons) == al.PLAGUEBEARER_MAX_STACKS == 20
    assert al.PLAGUEBEARER_DIRECT_PENALTY == 0.15


# --- 3. DoT snapshot ---------------------------------------------------------
def test_dot_snapshot():
    m = mob()
    scalers = {"dot_damage_inc_pct": 50.0, "burning_damage_inc_pct": 50.0}
    al.try_apply_on_hit(m, 100.0, DamageType.FIRE,
                        {"ignite_chance_pct": 100.0}, scalers, set(), ALWAYS)
    expected = al.IGNITE_PCT * 100.0 * 2.0  # (1 + (50+50)/100)
    # mutate the scalers dict after application — ticks must not change
    scalers["dot_damage_inc_pct"] = 0.0
    scalers["burning_damage_inc_pct"] = 0.0
    total = drain(m, al.IGNITE_DURATION + 0.3)
    assert abs(total - expected) < 1e-6, (total, expected)
    # bleed scales from dot_damage_inc_pct only
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.PHYS, {"bleed_chance_pct": 100.0},
                        {"dot_damage_inc_pct": 20.0, "burning_damage_inc_pct": 999.0},
                        set(), ALWAYS)
    total = drain(m, al.BLEED_DURATION + 0.3)
    assert abs(total - al.BLEED_PCT * 100.0 * 1.2) < 1e-6, total


# --- 4. boss control durations x0.5 ------------------------------------------
def test_boss_control_halving():
    b = mob(boss=True)
    al.try_apply_on_hit(b, 100.0, DamageType.COLD,
                        {"freeze_chance_pct": 100.0}, {}, set(), ALWAYS)
    st = al.get_state(b)
    assert abs(st.freeze_stop_t - al.FREEZE_STOP_DURATION * 0.5) < 1e-9
    assert abs(st.freeze_slow_t - al.FREEZE_SLOW_DURATION * 0.5) < 1e-9
    assert al.move_speed_mult(b) == 0.0
    drain(b, al.FREEZE_STOP_DURATION * 0.5 + 0.05)
    assert abs(al.move_speed_mult(b) - 0.7) < 1e-9  # slow phase
    drain(b, al.FREEZE_SLOW_DURATION * 0.5 + 0.1)
    assert al.move_speed_mult(b) == 1.0
    # stun halved too, and it interrupts (attack_cd reset to a full swing)
    b = mob(boss=True)
    b.attack_cd = 0.1
    al.apply_stun(b)
    assert abs(al.get_state(b).stun_t - al.STUN_DURATION * 0.5) < 1e-9
    assert b.attack_cd == 1.0 and al.is_stunned(b)
    drain(b, al.STUN_DURATION * 0.5 + 0.05)
    assert not al.is_stunned(b)
    # non-boss gets full durations
    m = mob()
    al.apply_stun(m)
    assert abs(al.get_state(m).stun_t - al.STUN_DURATION) < 1e-9


# --- 5. ignite: strongest wins; pyromaniac -----------------------------------
def test_ignite_strongest_and_pyromaniac():
    m = mob()
    al.try_apply_on_hit(m, 200.0, DamageType.FIRE,
                        {"ignite_chance_pct": 100.0}, {}, set(), ALWAYS)
    dps_strong = al.get_state(m).ignite.dps
    # weaker hit must NOT replace it
    got = al.try_apply_on_hit(m, 50.0, DamageType.FIRE,
                              {"ignite_chance_pct": 100.0}, {}, set(), ALWAYS)
    assert got == [] and al.get_state(m).ignite.dps == dps_strong
    # stronger hit replaces it
    got = al.try_apply_on_hit(m, 400.0, DamageType.FIRE,
                              {"ignite_chance_pct": 100.0}, {}, set(), ALWAYS)
    assert got == ["ignite"] and al.get_state(m).ignite.dps > dps_strong
    total = drain(m, al.IGNITE_DURATION + 0.3)
    assert abs(total - al.IGNITE_PCT * 400.0) < 1e-6, total  # only strongest ticked
    # pyromaniac: same total damage, delivered faster
    p = mob()
    al.try_apply_on_hit(p, 100.0, DamageType.FIRE,
                        {"ignite_chance_pct": 100.0}, {}, {"pyromaniac"}, ALWAYS)
    fast = drain(p, al.IGNITE_DURATION / al.PYROMANIAC_TICK_SPEED + 0.1,
                 flags={"pyromaniac"})
    assert abs(fast - al.IGNITE_PCT * 100.0) < 1e-6, fast  # all dealt within 2s
    assert al.get_state(p).ignite is None  # already burned out
    n = mob()
    al.try_apply_on_hit(n, 100.0, DamageType.FIRE,
                        {"ignite_chance_pct": 100.0}, {}, set(), ALWAYS)
    slow = drain(n, al.IGNITE_DURATION / al.PYROMANIAC_TICK_SPEED + 0.1)
    assert slow < fast  # normal ignite has damage still pending at t=2.1s
    assert al.get_state(n).ignite is not None


# --- 6. shock ----------------------------------------------------------------
def test_shock():
    m = mob()
    assert al.damage_taken_mult(m) == 1.0
    al.try_apply_on_hit(m, 100.0, DamageType.LIGHTNING,
                        {"shock_chance_pct": 100.0}, {}, set(), ALWAYS)
    assert abs(al.damage_taken_mult(m) - 1.15) < 1e-9
    drain(m, al.SHOCK_DURATION + 0.1)
    assert al.damage_taken_mult(m) == 1.0
    # shock_effect_inc_pct snapshots at application time
    m = mob()
    scalers = {"shock_effect_inc_pct": 40.0}
    al.try_apply_on_hit(m, 100.0, DamageType.LIGHTNING,
                        {"shock_chance_pct": 100.0}, scalers, set(), ALWAYS)
    scalers["shock_effect_inc_pct"] = 0.0
    assert abs(al.damage_taken_mult(m) - (1 + 0.15 * 1.4)) < 1e-9
    # spread_shock copies to monsters within radius
    src = mob(x=0.0)
    near, far, dead = mob(x=50.0), mob(x=100.0), mob(x=10.0)
    dead.alive = False
    al.try_apply_on_hit(src, 100.0, DamageType.LIGHTNING,
                        {"shock_chance_pct": 100.0}, {"shock_effect_inc_pct": 40.0},
                        {"storm_herald"}, ALWAYS)
    al.spread_shock(src, [src, near, far, dead])
    assert abs(al.damage_taken_mult(near) - (1 + 0.15 * 1.4)) < 1e-9
    assert al.damage_taken_mult(far) == 1.0 and al.damage_taken_mult(dead) == 1.0
    assert al.SHOCK_SPREAD_RADIUS == 60.0


# --- 7. winters_grasp --------------------------------------------------------
def test_winters_grasp():
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.COLD, {"freeze_chance_pct": 100.0},
                        {}, {"winters_grasp"}, ALWAYS)
    st = al.get_state(m)
    assert abs(st.freeze_stop_t - al.FREEZE_STOP_DURATION * 2) < 1e-9
    assert abs(st.freeze_slow_t - al.FREEZE_SLOW_DURATION * 2) < 1e-9
    drain(m, al.FREEZE_STOP_DURATION * 2 + 0.05)
    assert abs(al.move_speed_mult(m) - (1 - 0.345)) < 1e-9  # 34.5% slow


# --- 8. total DoT over full duration ≈ pct of hit (quantization tolerance) ----
def test_dot_totals():
    tol = 1e-6  # exact tick counts, only float error expected
    cases = [
        ("ignite", DamageType.FIRE, al.IGNITE_PCT, al.IGNITE_DURATION),
        ("bleed", DamageType.PHYS, al.BLEED_PCT, al.BLEED_DURATION),
        ("poison", DamageType.CHAOS, al.POISON_PCT, al.POISON_DURATION),
    ]
    for kind, dtype, pct, dur in cases:
        for hit in (37.0, 123.4, 999.9):
            m = mob()
            al.try_apply_on_hit(m, hit, dtype, {f"{kind}_chance_pct": 100.0},
                                {}, set(), ALWAYS)
            total = drain(m, dur + 0.3, dt=0.07)  # off-grid dt: quantized ticks
            assert abs(total - pct * hit) < max(tol, pct * hit * 0.01), (kind, hit, total)


# --- 9. SK-M4: per-skill overrides via scalers -------------------------------
def test_stun_s_override():
    # stun_s replaces the hardcoded STUN_DURATION
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.PHYS, {"stun_chance_pct": 100.0},
                        {"stun_s": 1.5}, set(), ALWAYS)
    assert abs(al.get_state(m).stun_t - 1.5) < 1e-9
    # boss halving still applies ON TOP of the override
    b = mob(boss=True)
    al.try_apply_on_hit(b, 100.0, DamageType.PHYS, {"stun_chance_pct": 100.0},
                        {"stun_s": 1.5}, set(), ALWAYS)
    assert abs(al.get_state(b).stun_t - 0.75) < 1e-9
    # duration_mult stacks with stun_s
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.PHYS, {"stun_chance_pct": 100.0},
                        {"stun_s": 1.0, "duration_mult": 2.0}, set(), ALWAYS)
    assert abs(al.get_state(m).stun_t - 2.0) < 1e-9
    # no key -> classic behaviour
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.PHYS, {"stun_chance_pct": 100.0},
                        {}, set(), ALWAYS)
    assert abs(al.get_state(m).stun_t - al.STUN_DURATION) < 1e-9


def test_bleed_stacks():
    # bleed_stacks:3 -> 3 independent stacks instead of single "strongest wins"
    m = mob()
    for _ in range(3):
        al.try_apply_on_hit(m, 100.0, DamageType.PHYS, {"bleed_chance_pct": 100.0},
                            {"bleed_stacks": 3}, set(), ALWAYS)
    assert len(al.get_state(m).bleeds) == 3
    assert al.get_state(m).bleed is None  # classic slot untouched
    assert "bleed" in al.active_icons(m)
    total = drain(m, al.BLEED_DURATION + 0.3)
    assert abs(total - 3 * al.BLEED_PCT * 100.0) < 1e-6, total
    # at cap a stronger bleed replaces the weakest; a weaker one is rejected
    m = mob()
    for _ in range(3):
        al.try_apply_on_hit(m, 100.0, DamageType.PHYS, {"bleed_chance_pct": 100.0},
                            {"bleed_stacks": 3}, set(), ALWAYS)
    got = al.try_apply_on_hit(m, 500.0, DamageType.PHYS, {"bleed_chance_pct": 100.0},
                              {"bleed_stacks": 3}, set(), ALWAYS)
    assert got == ["bleed"] and len(al.get_state(m).bleeds) == 3
    got = al.try_apply_on_hit(m, 50.0, DamageType.PHYS, {"bleed_chance_pct": 100.0},
                              {"bleed_stacks": 3}, set(), ALWAYS)
    assert got == [] and len(al.get_state(m).bleeds) == 3
    # no key -> classic single bleed, strongest wins
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.PHYS, {"bleed_chance_pct": 100.0},
                        {}, set(), ALWAYS)
    got = al.try_apply_on_hit(m, 50.0, DamageType.PHYS, {"bleed_chance_pct": 100.0},
                              {}, set(), ALWAYS)
    assert got == [] and al.get_state(m).bleed is not None
    assert al.get_state(m).bleeds == []


def test_poison_stacks_override():
    # custom cap of 5
    m = mob()
    for _ in range(8):
        al.try_apply_on_hit(m, 100.0, DamageType.CHAOS, {"poison_chance_pct": 100.0},
                            {"poison_stacks": 5}, set(), ALWAYS)
    assert len(al.get_state(m).poisons) == 5
    # plaguebearer cap stays PRIORITARY over poison_stacks when its flag is set
    m = mob()
    for _ in range(30):
        al.try_apply_on_hit(m, 100.0, DamageType.CHAOS, {"poison_chance_pct": 100.0},
                            {"poison_stacks": 5}, {"plaguebearer"}, ALWAYS)
    assert len(al.get_state(m).poisons) == al.PLAGUEBEARER_MAX_STACKS == 20
    # no key -> default POISON_MAX_STACKS
    m = mob()
    for _ in range(8):
        al.try_apply_on_hit(m, 100.0, DamageType.CHAOS, {"poison_chance_pct": 100.0},
                            {}, set(), ALWAYS)
    assert len(al.get_state(m).poisons) == al.POISON_MAX_STACKS == 3


def test_dot_pct_overrides():
    # poison_pct overrides the damage fraction
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.CHAOS, {"poison_chance_pct": 100.0},
                        {"poison_pct": 1.0}, set(), ALWAYS)
    total = drain(m, al.POISON_DURATION + 0.3)
    assert abs(total - 1.0 * 100.0) < 1e-6, total
    # bleed_pct overrides
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.PHYS, {"bleed_chance_pct": 100.0},
                        {"bleed_pct": 0.25}, set(), ALWAYS)
    total = drain(m, al.BLEED_DURATION + 0.3)
    assert abs(total - 0.25 * 100.0) < 1e-6, total
    # ignite_pct overrides
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.FIRE, {"ignite_chance_pct": 100.0},
                        {"ignite_pct": 0.8}, set(), ALWAYS)
    total = drain(m, al.IGNITE_DURATION + 0.3)
    assert abs(total - 0.8 * 100.0) < 1e-6, total


def test_duration_mult():
    # duration_mult stretches DoT duration (same total dmg, more ticks/longer)
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.CHAOS, {"poison_chance_pct": 100.0},
                        {"duration_mult": 2.0}, set(), ALWAYS)
    # still alive well past the base duration...
    drain(m, al.POISON_DURATION + 0.3)
    assert "poison" in al.active_icons(m), "duration_mult 2x should keep poison alive"
    # ...expires after the doubled duration; total still == pct * hit
    total = drain(m, al.POISON_DURATION + 0.3)
    assert "poison" not in al.active_icons(m)
    # freeze duration also scaled by duration_mult
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.COLD, {"freeze_chance_pct": 100.0},
                        {"duration_mult": 2.0}, set(), ALWAYS)
    st = al.get_state(m)
    assert abs(st.freeze_stop_t - al.FREEZE_STOP_DURATION * 2.0) < 1e-9
    assert abs(st.freeze_slow_t - al.FREEZE_SLOW_DURATION * 2.0) < 1e-9
    # shock duration scaled too
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.LIGHTNING, {"shock_chance_pct": 100.0},
                        {"duration_mult": 2.0}, set(), ALWAYS)
    assert abs(al.get_state(m).shock_t - al.SHOCK_DURATION * 2.0) < 1e-9


def test_overrides_none_safe():
    # explicit None must behave exactly like an absent key (fallback to constants)
    m = mob()
    scal = {"stun_s": None, "bleed_stacks": None, "poison_stacks": None,
            "ignite_pct": None, "bleed_pct": None, "poison_pct": None,
            "duration_mult": None}
    al.try_apply_on_hit(m, 100.0, DamageType.PHYS, {"stun_chance_pct": 100.0},
                        dict(scal), set(), ALWAYS)
    assert abs(al.get_state(m).stun_t - al.STUN_DURATION) < 1e-9
    m = mob()
    al.try_apply_on_hit(m, 100.0, DamageType.CHAOS, {"poison_chance_pct": 100.0},
                        dict(scal), set(), ALWAYS)
    total = drain(m, al.POISON_DURATION + 0.3)
    assert abs(total - al.POISON_PCT * 100.0) < 1e-6, total


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"{t.__name__} OK")
    print(f"\nall {len(tests)} ailment tests passed")
