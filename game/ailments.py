"""Bar of Exile — ailment system (ignite/bleed/poison/freeze/shock/stun).

Standalone module: does NOT touch hp or emit events itself. The combat
integrator is expected to:
  * call try_apply_on_hit(...) after every landed hit (with the FINAL
    post-mitigation damage — DoTs snapshot it and never re-evaluate);
  * call tick_ailments(target, dt, flags) every tick and subtract the
    returned DoT damage from target.hp / emit events itself;
  * multiply direct damage dealt TO a shocked target by damage_taken_mult();
  * multiply monster movement by move_speed_mult() and skip attacks while
    is_stunned() / frozen;
  * apply the plaguebearer -15% direct damage penalty
    (PLAGUEBEARER_DIRECT_PENALTY) to the hero's direct hits;
  * on shock application with storm_herald: call spread_shock(source, monsters);
  * roll monster-on-hero stun against stun_avoid itself, then apply_stun(hero).

Trigger gating: ignite<-FIRE, bleed<-PHYS, poison<-CHAOS, freeze<-COLD,
shock<-LIGHTNING hits; stun can trigger off any damage type. A Hero target
can only ever receive stun. Boss (is_boss) halves ALL control durations
(freeze stop, freeze slow, stun); DoT and shock durations are not halved.

Per-skill overrides (audit SK-M4): try_apply_on_hit reads OPTIONAL keys from
the `scalers` dict it already receives, each falling back to the module
constant when the key is absent or None (full backward compatibility). This
lets skills carry their own numbers (e.g. Shield Bash stun_s:1.5, Rupture
bleed_stacks:3) instead of the tooltip lying about hardcoded values:
  * stun_s        -> stun duration in seconds (default STUN_DURATION). Boss
                     control-halving (BOSS_CONTROL_MULT) still applies ON TOP.
  * bleed_stacks  -> if > 1, bleed is allowed to stack up to that many
                     instances (poison-style: weakest replaced when stronger);
                     absent/1 keeps the classic single "strongest wins" bleed.
  * poison_stacks -> poison stack cap (default POISON_MAX_STACKS). The
                     plaguebearer keystone cap (PLAGUEBEARER_MAX_STACKS) stays
                     PRIORITARY when its flag is active.
  * ignite_pct / bleed_pct / poison_pct -> DoT damage fraction of the hit
                     (default IGNITE_PCT / BLEED_PCT / POISON_PCT).
  * duration_mult -> multiplier applied to the duration of EVERY ailment this
                     call produces, after all other math (default 1.0).
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    from game.core import DamageType, Hero
except ImportError:  # direct script run: python game/ailments.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from game.core import DamageType, Hero

# --- tuning ---
DOT_TICK_PERIOD = 0.25              # DoTs tick 4 times per second
IGNITE_PCT, IGNITE_DURATION = 0.40, 3.0     # fire DoT, single instance
BLEED_PCT, BLEED_DURATION = 0.50, 4.0       # phys DoT, single instance
POISON_PCT, POISON_DURATION = 0.60, 5.0     # chaos DoT, stacking
POISON_MAX_STACKS = 3
# Plaguebearer keystone raises the cap far above baseline (a strong build-around)
# but MUST stay finite: an uncapped list grows without bound on long boss fights,
# which is both a DoT exploit and an unbounded-memory leak (audit M3).
PLAGUEBEARER_MAX_STACKS = 20
FREEZE_STOP_DURATION = 0.8          # full stop, then...
FREEZE_SLOW_DURATION = 2.0          # ...slow phase
FREEZE_SLOW_PCT = 30.0
SHOCK_DURATION = 3.0
SHOCK_BONUS = 0.15                  # +15% increased damage taken
STUN_DURATION = 0.6
BOSS_CONTROL_MULT = 0.5             # bosses: all control durations halved

# --- keystones (consumed via the `flags` set) ---
PYROMANIAC_TICK_SPEED = 1.5         # ignite ticks 50% faster (same total dmg)
WINTERS_GRASP_SLOW_PCT = 34.5       # 30% * 1.15
WINTERS_GRASP_FREEZE_MULT = 2.0     # freeze durations x2
PLAGUEBEARER_DIRECT_PENALTY = 0.15  # -15% direct damage (applied by integrator)
SHOCK_SPREAD_RADIUS = 60.0          # px; spread itself is done by integrator

AILMENT_ORDER = ("ignite", "bleed", "poison", "freeze", "shock", "stun")

_TRIGGER_TYPE = {
    "ignite": DamageType.FIRE,
    "bleed": DamageType.PHYS,
    "poison": DamageType.CHAOS,
    "freeze": DamageType.COLD,
    "shock": DamageType.LIGHTNING,
    # "stun": any damage type
}


@dataclass
class AilmentInstance:
    """One DoT instance. Damage is fully snapshotted at apply time:
    total = pct * final_hit * (1 + inc/100), split into equal ticks."""
    kind: str
    per_tick: float          # damage dealt per tick (snapshot)
    tick_period: float       # seconds between ticks
    ticks_left: int
    acc: float = 0.0         # accumulated time toward the next tick

    @property
    def dps(self) -> float:
        return self.per_tick / self.tick_period if self.tick_period > 0 else 0.0

    @property
    def expired(self) -> bool:
        return self.ticks_left <= 0

    def advance(self, dt: float) -> float:
        """Advance own timer; return DoT damage produced during this step."""
        if self.ticks_left <= 0:
            return 0.0
        self.acc += dt
        dmg = 0.0
        while self.acc >= self.tick_period and self.ticks_left > 0:
            self.acc -= self.tick_period
            dmg += self.per_tick
            self.ticks_left -= 1
        return dmg


def _make_dot(kind: str, total: float, duration: float,
              tick_period: float = DOT_TICK_PERIOD) -> AilmentInstance:
    ticks = max(int(round(duration / DOT_TICK_PERIOD)), 1)
    return AilmentInstance(kind=kind, per_tick=total / ticks,
                           tick_period=tick_period, ticks_left=ticks)


@dataclass
class AilmentState:
    """Per-entity ailment container, stored as entity._ailments."""
    ignite: AilmentInstance | None = None
    bleed: AilmentInstance | None = None
    bleeds: list[AilmentInstance] = field(default_factory=list)  # only used when bleed_stacks>1
    poisons: list[AilmentInstance] = field(default_factory=list)
    freeze_stop_t: float = 0.0   # full-stop phase remaining
    freeze_slow_t: float = 0.0   # slow phase remaining (runs after stop ends)
    slow_mult: float = 1.0       # snapshot: 0.7 (or 0.655 with winters_grasp)
    shock_t: float = 0.0
    shock_bonus: float = 0.0     # snapshot: 0.15 * (1 + shock_effect_inc/100)
    stun_t: float = 0.0


def get_state(entity) -> AilmentState:
    st = getattr(entity, "_ailments", None)
    if st is None:
        st = AilmentState()
        entity._ailments = st
    return st


def try_apply_on_hit(target, final_damage: float, damage_type,
                     chances: dict[str, float], scalers: dict[str, float],
                     flags: set[str], rng) -> list[str]:
    """Roll every ailment chance independently for one landed hit.
    `final_damage` is the post-armor/post-res damage of the hit (snapshot base).
    Returns names of ailments that actually changed state (a successful roll
    that loses "strongest wins" / a full poison cap is NOT reported).

    Optional per-skill overrides are read from `scalers` (all fall back to the
    module constants when the key is absent or None):
      stun_s, bleed_stacks, poison_stacks,
      ignite_pct, bleed_pct, poison_pct, duration_mult.
    See the module docstring for their exact semantics."""
    st = get_state(target)
    ctrl = BOSS_CONTROL_MULT if getattr(target, "is_boss", False) else 1.0
    hero_target = isinstance(target, Hero)  # heroes only receive stun
    dot_inc = scalers.get("dot_damage_inc_pct", 0.0)
    applied: list[str] = []

    # --- per-skill overrides (SK-M4): read from scalers, None-safe with fallback ---
    def _num(key, fallback):
        v = scalers.get(key)
        return fallback if v is None else v

    dur_mult = float(_num("duration_mult", 1.0))
    ignite_pct = float(_num("ignite_pct", IGNITE_PCT))
    bleed_pct = float(_num("bleed_pct", BLEED_PCT))
    poison_pct = float(_num("poison_pct", POISON_PCT))
    bleed_stacks = int(_num("bleed_stacks", 1))
    poison_stacks = int(_num("poison_stacks", POISON_MAX_STACKS))

    for kind in AILMENT_ORDER:
        chance = chances.get(f"{kind}_chance_pct", 0.0)
        if chance <= 0:
            continue
        trig = _TRIGGER_TYPE.get(kind)
        if trig is not None and damage_type != trig:
            continue
        if hero_target and kind != "stun":
            continue
        if rng.uniform(0.0, 100.0) >= chance:
            continue

        if kind == "ignite":
            if final_damage <= 0:
                continue
            inc = dot_inc + scalers.get("burning_damage_inc_pct", 0.0)
            total = ignite_pct * final_damage * (1 + inc / 100.0)
            speed = PYROMANIAC_TICK_SPEED if "pyromaniac" in flags else 1.0
            inst = _make_dot("ignite", total, IGNITE_DURATION * dur_mult,
                             DOT_TICK_PERIOD / speed)
            if st.ignite is None or st.ignite.expired or inst.dps > st.ignite.dps:
                st.ignite = inst
                applied.append(kind)

        elif kind == "bleed":
            if final_damage <= 0:
                continue
            total = bleed_pct * final_damage * (1 + dot_inc / 100.0)
            inst = _make_dot("bleed", total, BLEED_DURATION * dur_mult)
            if bleed_stacks > 1:
                # poison-style stacking up to `bleed_stacks`; the classic single
                # st.bleed slot is left untouched so plain readers see nothing new
                if len(st.bleeds) < bleed_stacks:
                    st.bleeds.append(inst)
                    applied.append(kind)
                else:  # at cap: replace the weakest stack if the new one is stronger
                    weakest = min(range(len(st.bleeds)),
                                  key=lambda i: st.bleeds[i].dps)
                    if inst.dps > st.bleeds[weakest].dps:
                        st.bleeds[weakest] = inst
                        applied.append(kind)
            elif st.bleed is None or st.bleed.expired or inst.dps > st.bleed.dps:
                st.bleed = inst
                applied.append(kind)

        elif kind == "poison":
            if final_damage <= 0:
                continue
            total = poison_pct * final_damage * (1 + dot_inc / 100.0)
            inst = _make_dot("poison", total, POISON_DURATION * dur_mult)
            cap = PLAGUEBEARER_MAX_STACKS if "plaguebearer" in flags else poison_stacks
            if len(st.poisons) < cap:
                st.poisons.append(inst)
                applied.append(kind)
            else:  # at cap: replace the weakest stack if the new one is stronger
                weakest = min(range(len(st.poisons)),
                              key=lambda i: st.poisons[i].dps)
                if inst.dps > st.poisons[weakest].dps:
                    st.poisons[weakest] = inst
                    applied.append(kind)

        elif kind == "freeze":
            fmult = WINTERS_GRASP_FREEZE_MULT if "winters_grasp" in flags else 1.0
            st.freeze_stop_t = max(st.freeze_stop_t,
                                   FREEZE_STOP_DURATION * fmult * ctrl * dur_mult)
            st.freeze_slow_t = max(st.freeze_slow_t,
                                   FREEZE_SLOW_DURATION * fmult * ctrl * dur_mult)
            slow_pct = (WINTERS_GRASP_SLOW_PCT if "winters_grasp" in flags
                        else FREEZE_SLOW_PCT)
            st.slow_mult = 1.0 - slow_pct / 100.0
            applied.append(kind)

        elif kind == "shock":
            bonus = SHOCK_BONUS * (1 + scalers.get("shock_effect_inc_pct", 0.0) / 100.0)
            if st.shock_t <= 0 or bonus >= st.shock_bonus:
                st.shock_bonus = bonus
                st.shock_t = SHOCK_DURATION * dur_mult
                applied.append(kind)

        elif kind == "stun":
            # stun_s overrides the base duration; dur_mult scales it; boss halving
            # is applied INSIDE apply_stun (control-halving stays on top).
            stun_dur = float(_num("stun_s", STUN_DURATION)) * dur_mult
            apply_stun(target, stun_dur)
            applied.append(kind)

    return applied


def tick_ailments(target, dt: float, flags: set[str] | None = None) -> float:
    """Advance all ailment timers; return total DoT damage for this step.
    The integrator subtracts it from hp and emits events. `flags` is accepted
    for contract stability (all keystone effects are snapshotted at apply)."""
    st = get_state(target)
    dmg = 0.0
    if st.ignite is not None:
        dmg += st.ignite.advance(dt)
        if st.ignite.expired:
            st.ignite = None
    if st.bleed is not None:
        dmg += st.bleed.advance(dt)
        if st.bleed.expired:
            st.bleed = None
    if st.bleeds:
        for b in st.bleeds:  # each bleed stack runs its own timer (bleed_stacks>1)
            dmg += b.advance(dt)
        st.bleeds = [b for b in st.bleeds if not b.expired]
    if st.poisons:
        for p in st.poisons:  # each poison stack runs its own timer
            dmg += p.advance(dt)
        st.poisons = [p for p in st.poisons if not p.expired]

    if st.stun_t > 0:
        st.stun_t = max(0.0, st.stun_t - dt)
    if st.shock_t > 0:
        st.shock_t = max(0.0, st.shock_t - dt)
        if st.shock_t <= 0:
            st.shock_bonus = 0.0
    if st.freeze_stop_t > 0:
        st.freeze_stop_t -= dt
        if st.freeze_stop_t < 0:  # spill leftover time into the slow phase
            st.freeze_slow_t = max(0.0, st.freeze_slow_t + st.freeze_stop_t)
            st.freeze_stop_t = 0.0
    elif st.freeze_slow_t > 0:
        st.freeze_slow_t = max(0.0, st.freeze_slow_t - dt)
    return dmg


# --- state helpers for the integrator ---

def damage_taken_mult(target) -> float:
    """1.15 (scaled by snapshotted shock_effect_inc) while shocked, else 1.0."""
    st = get_state(target)
    return 1.0 + st.shock_bonus if st.shock_t > 0 else 1.0


def move_speed_mult(target) -> float:
    """0.0 while frozen, 0.7/0.655 while slowed, else 1.0."""
    st = get_state(target)
    if st.freeze_stop_t > 0:
        return 0.0
    if st.freeze_slow_t > 0:
        return st.slow_mult
    return 1.0


def is_stunned(target) -> bool:
    return get_state(target).stun_t > 0


def apply_stun(target, duration: float = STUN_DURATION) -> None:
    """Stun + interrupt: resets the target's attack timer to a full swing.
    Boss targets get the duration halved (control halving)."""
    if getattr(target, "is_boss", False):
        duration *= BOSS_CONTROL_MULT
    st = get_state(target)
    st.stun_t = max(st.stun_t, duration)
    spd = getattr(getattr(target, "stats", None), "attack_speed", 0.0)
    if spd > 0:
        target.attack_cd = max(getattr(target, "attack_cd", 0.0),
                               1.0 / max(spd, 0.05))


def spread_shock(source, monsters, radius: float = SHOCK_SPREAD_RADIUS) -> None:
    """storm_herald: copy source's shock to alive monsters within `radius` px
    (strongest shock wins on each target)."""
    src = get_state(source)
    if src.shock_t <= 0:
        return
    for m in monsters:
        if m is source or not getattr(m, "alive", True):
            continue
        if abs(m.x - source.x) > radius:
            continue
        st = get_state(m)
        if st.shock_t <= 0 or src.shock_bonus >= st.shock_bonus:
            st.shock_bonus = src.shock_bonus
            st.shock_t = max(st.shock_t, src.shock_t)


def active_icons(target) -> list[str]:
    """Names of active ailments, in AILMENT_ORDER, for icon rendering."""
    st = get_state(target)
    icons: list[str] = []
    if st.ignite is not None and not st.ignite.expired:
        icons.append("ignite")
    if st.bleed is not None and not st.bleed.expired:
        icons.append("bleed")
    elif any(not b.expired for b in st.bleeds):
        icons.append("bleed")
    if any(not p.expired for p in st.poisons):
        icons.append("poison")
    if st.freeze_stop_t > 0 or st.freeze_slow_t > 0:
        icons.append("freeze")
    if st.shock_t > 0:
        icons.append("shock")
    if st.stun_t > 0:
        icons.append("stun")
    return icons


if __name__ == "__main__":
    import random

    from game.core import Monster, Stats
    m = Monster(name="Dummy", stats=Stats(life=1000))
    m.init_hp()
    rng = random.Random(1)
    hit = try_apply_on_hit(m, 100.0, DamageType.FIRE,
                           {"ignite_chance_pct": 100.0}, {}, set(), rng)
    assert hit == ["ignite"] and active_icons(m) == ["ignite"]
    total = sum(tick_ailments(m, 0.05) for _ in range(62))  # 3.1s
    assert abs(total - 40.0) < 1e-6, total
    print("ailments OK:", total)
