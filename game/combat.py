"""Bar of Exile — tick-based combat system."""
from __future__ import annotations

import random

from game import ailments
from game import mob_rarity
from game import skills_v2
from game import unique_specials
from game.combat_math import (
    crit_mult, apply_leech, kill_heal, rolls_dodge,
    LEECH_CAP_PCT, OVERHEAL_DECAY_FRAC, CULL_FRAC, CULL_FRAC_BOSS,
)
# Re-exported: callers (e.g. tests/test_class_keystones.py) import these tuning
# constants from game.combat, so they stay part of this module's public surface.
from game.combat_math import (  # noqa: F401
    KILL_HEAL_FRAC, OVERHEAL_CAP_FRAC,
)
from game.core import (
    CombatEvent,
    DamageType,
    Entity,
    Hero,
    Monster,
    Stats,
    TICK_DT,
)

MONSTER_ATTACK_RANGE = 36.0
CORPSE_LINGER = 1.0
HIT_FLASH = 0.1  # render reads e._flash for the white hit-flash

# Corrosion (slime debuff): slime-type mobs shave the hero's EFFECTIVE armour on
# each landed hit — stacks, capped, and decays. Gentle by design: it never
# touches hero.stats (recalc-safe), only the mitigation calc in _monster_strike,
# and only slime-family mobs apply it (the Orc Warlord death-wall is non-slime,
# so this cannot regress that tuning). the_quarantine_rolls (corrosion_immune)
# negates it entirely. Balance lives here — flagged for manual review.
CORROSION_PER_STACK = 0.06     # -6% effective armour per stack
CORROSION_MAX_STACKS = 5       # cap at -30% armour
CORROSION_DURATION = 4.0       # seconds since the last stack before it clears


def _is_slime(m: Monster) -> bool:
    mid = getattr(m, "monster_id", "") or ""
    return mid.startswith("slime") or mid == "mother_of_slimes"

# keystone: deadeye "+20% damage to distant targets" (pierce: TODO, no projectile entities)
DEADEYE_RANGE = 100.0
DEADEYE_MORE = 1.2

# S.4 class-keystone combat hooks (flags come from hero.flags, set by tree.py
# when a ck-node is allocated). Whitelist (§2 of CLASS_KEYSTONES_TREE_REWORK):
#   ck_cull_10   — finish a target left below the cull threshold after a hit
#                  (10% for normal mobs, 5% for bosses).
#   ck_fifth_shot — every 5th hero hit is a guaranteed crit.
#   ck_overheal  — leech overflow past max life becomes temp HP (see below).
#   ck_kill_heal — each kill heals the hero for 2% of max life.
# The old v1 keystone system (first_blood / cull_N) is retired: its flags are no
# longer supplied by the tree or data, so its hooks were removed here.
# CULL_FRAC / CULL_FRAC_BOSS / OVERHEAL_* / KILL_HEAL_FRAC / LEECH_CAP_PCT now
# live in game.combat_math (shared with the skill path, audit 2b) and are
# imported at the top of this module.

# Melee classes swing wide: the strike also hits other monsters within
# CLEAVE_RANGE of the primary target, for CLEAVE_MULT of the rolled damage.
# Without this a melee hero stands inside a 12-strong pack taking hits from
# every mob while killing one at a time; ranged classes thin packs at 260px
# and never take that punishment. Cleave is what makes melee viable.
MELEE_CLEAVE_CLASSES = {"warrior", "barbarian", "cleric"}
CLEAVE_RANGE = 60.0
CLEAVE_MULT = 0.5
CLEAVE_MAX_TARGETS = 4

# The mage's auto-attack bolt (proj_mage) explodes on impact: monsters near
# the primary target take a fraction of the rolled damage as splash.
MAGE_SPLASH_RANGE = 50.0
MAGE_SPLASH_MULT = 0.35
MAGE_SPLASH_MAX_TARGETS = 3

# Ranged classes fire a travelling projectile VFX from hero to target on each
# auto-attack. Damage still resolves instantly in _hero_strike (idle-game feel);
# the projectile is purely visual, homing onto the live target. Maps class_id ->
# the vfx effect id (see assets/vfx/manifest.json proj_*).
RANGED_PROJECTILE = {
    "archer": "proj_arrow",
    "mage": "proj_mage",
}

_RES_BY_TYPE = {
    DamageType.FIRE: "res_fire",
    DamageType.COLD: "res_cold",
    DamageType.LIGHTNING: "res_lightning",
    DamageType.CHAOS: "res_chaos",
}


def _set_anim(e: Entity, anim: str) -> None:
    if e.anim != anim:
        e.anim = anim
        e.anim_t = 0.0


# Armor mitigation coefficient K in armor/(armor + K*raw). Lower K => armor
# blocks more of a big hit. The formula is used in BOTH directions, so K is split:
#   PHYS_K_OFFENSE  — hero->monster (_strike_damage): keeps the original 10.0, so
#                     mob armor still barely dents player damage (offense & the
#                     over-limit exploit surface are unchanged).
#   PHYS_K_HERO_DEF — monster->hero (_monster_strike): gentler, so plate armor
#                     keeps real traction against the geometric late-act damage
#                     curve. This is the act3 melee death-wall fix (AUDIT_20 #1).
#                     Melee-only in effect — ranged carry ~0 armor, so their
#                     mitigation is ~0 regardless of K.
PHYS_K_OFFENSE = 10.0
PHYS_K_HERO_DEF = 4.0


def _mitigate_phys(raw: float, armor: float, k: float = PHYS_K_OFFENSE) -> float:
    if raw <= 0:
        return 0.0
    reduction = armor / (armor + k * raw)
    return raw * (1.0 - min(reduction, 0.9))


def _mitigate_elem(raw: float, target: Stats, dtype: DamageType) -> float:
    if raw <= 0:
        return 0.0
    res = getattr(target, _RES_BY_TYPE[dtype])
    # H3: floor at 0 — a resist >100% must never heal the target (negative dmg).
    return max(0.0, raw * (1.0 - res / 100.0))


class CombatSystem:
    def __init__(self, hero: Hero, rng: random.Random | None = None):
        self.hero = hero
        self.rng = rng or random.Random()
        self.monsters: list[Monster] = []
        self.events: list[CombatEvent] = []
        self.kills: int = 0
        self._corpse_timers: dict[int, float] = {}
        self._corrosion_stacks: int = 0   # slime armour-shred on the hero
        self._corrosion_t: float = 0.0     # time left before stacks clear
        # covenant_of_the_hunt: (StatMod, time_left) pairs stolen from slain Rares.
        # The mods live on hero._stolen_mods (folded into recalc); this list owns
        # their expiry. Kept here (not on the hero) so it stays transient.
        self._stolen: list[list] = []

    def hero_attack_range(self) -> float:
        if self.hero.class_id == "archer":
            return 260.0
        if self.hero.class_id == "mage":
            return 260.0
        if self.hero.class_id == "cleric":
            return 140.0
        if self.hero.class_id == "barbarian":
            return 48.0
        return 48.0

    def tick(self, dt: float) -> None:
        hero = self.hero
        if hero.alive:
            self._regen(hero, dt)
            self._move_and_act(dt)
        self._tick_ailments(dt)
        self._tick_corrosion(dt)
        self._tick_stolen(dt)
        self._cleanup_corpses(dt)
        hero.anim_t += dt
        if getattr(hero, "_flash", 0.0) > 0:
            hero._flash -= dt
        for m in self.monsters:
            m.anim_t += dt
            if getattr(m, "_flash", 0.0) > 0:
                m._flash -= dt

    def _tick_ailments(self, dt: float) -> None:
        """DoT ticks on monsters (and stun timer on the hero)."""
        ailments.tick_ailments(self.hero, dt)
        # ashfall_mantle (stagger): advance the hero's deferred-burn instances and
        # apply their damage as a DoT (no re-stagger — _deal guards on is_dot).
        dots = getattr(self.hero, "_stagger_dots", None)
        if dots:
            burn = sum(d.advance(dt) for d in dots)
            self.hero._stagger_dots = [d for d in dots if not d.expired]
            if burn > 0 and self.hero.alive:
                self._deal(self.hero, burn, DamageType.FIRE, False, is_dot=True)
        for m in self.monsters:
            if not m.alive:
                continue
            dot = ailments.tick_ailments(m, dt)
            if dot > 0:
                self._deal(m, dot, DamageType.CHAOS, False, is_dot=True)

    def _tick_corrosion(self, dt: float) -> None:
        """Corrosion stacks clear in one shot once CORROSION_DURATION elapses
        since the last stack landed (no partial decay — matches the design note)."""
        if self._corrosion_stacks <= 0:
            return
        self._corrosion_t -= dt
        if self._corrosion_t <= 0:
            self._corrosion_stacks = 0
            self._corrosion_t = 0.0

    def _tick_stolen(self, dt: float) -> None:
        """Age covenant_of_the_hunt steals; drop the expired and re-fold survivors
        into hero._stolen_mods (recalc reads that list). Only recalcs on change."""
        if not self._stolen:
            return
        for pair in self._stolen:
            pair[1] -= dt
        live = [p for p in self._stolen if p[1] > 0]
        if len(live) != len(self._stolen):
            self._stolen = live
            self.hero._stolen_mods = [p[0] for p in live]
            self.hero.recalc()

    def _steal_from_rare(self, mob: Monster) -> None:
        """On killing a Rare mob with rare_mod_steal equipped, grab one of its
        affixes for STEAL_DURATION. Caps at STEAL_MAX (oldest steal drops first)."""
        if "rare_mod_steal" not in self.hero.flags:
            return
        if mob_rarity.tier_of(mob) != mob_rarity.RARE:
            return
        mod = unique_specials.steal_mod_from(mob, self.rng)
        self._stolen.append([mod, unique_specials.STEAL_DURATION])
        if len(self._stolen) > unique_specials.STEAL_MAX:
            self._stolen.pop(0)  # oldest expires early to honour the cap
        self.hero._stolen_mods = [p[0] for p in self._stolen]
        self.hero.recalc()

    def _regen(self, hero: Hero, dt: float) -> None:
        if hero.stats.life_regen > 0 and hero.hp < hero.max_hp:
            hero.hp = min(hero.max_hp, hero.hp + hero.stats.life_regen * dt)
        # ck_overheal: temp HP buffer decays over time (never below 0).
        temp = getattr(hero, "_ck_temp_hp", 0.0)
        if temp > 0 and hero.max_hp > 0:
            temp -= OVERHEAL_DECAY_FRAC * hero.max_hp * dt
            setattr(hero, "_ck_temp_hp", max(0.0, temp))

    def _move_and_act(self, dt: float) -> None:
        hero = self.hero
        alive_mobs = [m for m in self.monsters if m.alive]
        target = min(alive_mobs, key=lambda m: abs(m.x - hero.x)) if alive_mobs else None

        hero.attack_cd -= dt
        if ailments.is_stunned(hero):
            _set_anim(hero, "hurt")
        elif target and abs(target.x - hero.x) <= self.hero_attack_range():
            hero.facing = 1 if target.x >= hero.x else -1
            _set_anim(hero, "attack")
            if hero.attack_cd <= 0:
                self._hero_strike(target)
                hero.attack_cd = 1.0 / max(hero.stats.attack_speed, 0.05)
        else:
            hero.facing = 1
            _set_anim(hero, "walk")
            hero.x += hero.stats.move_speed * dt

        for m in alive_mobs:
            m.attack_cd -= dt
            if not m.alive or not hero.alive:
                continue
            if ailments.is_stunned(m) or ailments.move_speed_mult(m) == 0.0:
                continue  # stunned/frozen: no move, no attack
            dist = abs(hero.x - m.x)
            m.facing = 1 if hero.x >= m.x else -1
            if dist <= MONSTER_ATTACK_RANGE:
                _set_anim(m, "attack")
                if m.attack_cd <= 0:
                    self._monster_strike(m)
                    m.attack_cd = 1.0 / max(m.stats.attack_speed, 0.05)
            else:
                _set_anim(m, "walk")
                step = m.stats.move_speed * dt * ailments.move_speed_mult(m)
                m.x += step * m.facing
                if (m.x - hero.x) * m.facing > 0:
                    m.x = hero.x

    def _strike_damage(self, target: Monster, phys: float, mult: float) -> float:
        """Damage a single rolled swing (phys + elems, crit mult already folded
        into `mult`) deals to `target` after its mitigation, keystones, idle
        stats and ailments. Pure — no hp mutation."""
        hero = self.hero
        s = hero.stats
        # the_smiths_regret (phys_to_fire): a slice of the swing's PHYS is dealt
        # as FIRE instead — mitigated by the target's fire resist, not armour.
        phys_hit = phys * mult
        conv_fire = 0.0
        if "phys_to_fire" in hero.flags:
            conv = phys_hit * unique_specials.PHYS_TO_FIRE_PCT / 100.0
            phys_hit -= conv
            conv_fire = _mitigate_elem(conv, target.stats, DamageType.FIRE)
        total = _mitigate_phys(phys_hit, target.stats.armor) + conv_fire
        # heartstone_of_the_firstborn (low_life_fire): +% Fire Damage while the
        # hero is on Low Life. Scales the flat added-fire block below.
        fire_mult = 1.0
        if ("low_life_fire" in hero.flags and hero.max_hp > 0
                and hero.hp / hero.max_hp < unique_specials.LOW_LIFE_THRESHOLD):
            fire_mult += unique_specials.LOW_LIFE_FIRE_PCT / 100.0
        for dtype, raw in (
            (DamageType.FIRE, s.added_fire * fire_mult),
            (DamageType.COLD, s.added_cold),
            (DamageType.LIGHTNING, s.added_lightning),
            (DamageType.CHAOS, s.added_chaos),
        ):
            if raw > 0:
                total += _mitigate_elem(raw * mult, target.stats, dtype)

        if "deadeye" in hero.flags and abs(target.x - hero.x) >= DEADEYE_RANGE:
            total *= DEADEYE_MORE
        if "berserker_oath" in hero.flags and hero.max_hp > 0:
            missing_pct = (1 - hero.hp / hero.max_hp) * 100
            total *= 1 + 0.02 * missing_pct

        total *= 1 + s.damage_inc / 100.0
        if target.is_boss:
            total *= 1 + s.boss_damage_inc / 100.0
        total *= ailments.damage_taken_mult(target)
        if "plaguebearer" in hero.flags:
            total *= 1 - ailments.PLAGUEBEARER_DIRECT_PENALTY
        return total

    def _hero_strike(self, target: Monster) -> None:
        hero = self.hero
        s = hero.stats
        phys = self.rng.uniform(s.damage_min, s.damage_max)
        # Shared crit roll (combat_math.crit_mult): ck_fifth_shot forces a crit
        # on every 5th hero hit, else a normal crit_chance% roll. Skills use the
        # same helper (without ck_fifth) so crit works on both paths (audit H2).
        is_crit, mult = crit_mult(hero, self.rng, ck_fifth=True)
        # The auto-attack IS the equipped primary skill (design §2: primaries are
        # "auto-attack replacers"). Fold in the primary's rank MORE bucket +
        # talents so leveling it up actually matters, without a second cast.
        mult *= skills_v2.primary_growth_mult(hero)

        # ranged classes: travelling projectile VFX hero -> target (visual only,
        # damage still resolves below). text carries the effect id.
        proj = RANGED_PROJECTILE.get(hero.class_id)
        if proj:
            self.events.append(CombatEvent(
                "proj", x=target.x, text=proj, origin=hero.x, target=target))

        # primary target + melee cleave onto nearby mobs (halved, capped),
        # or the mage bolt's impact splash (smaller radius and fraction)
        hits: list[tuple[Monster, float]] = [
            (target, self._strike_damage(target, phys, mult))]
        aoe_mult, aoe_range, aoe_cap = 0.0, 0.0, 0
        if hero.class_id in MELEE_CLEAVE_CLASSES:
            aoe_mult, aoe_range, aoe_cap = CLEAVE_MULT, CLEAVE_RANGE, CLEAVE_MAX_TARGETS
        elif hero.class_id == "mage":
            aoe_mult, aoe_range, aoe_cap = (
                MAGE_SPLASH_MULT, MAGE_SPLASH_RANGE, MAGE_SPLASH_MAX_TARGETS)
        if aoe_cap:
            extra = [m for m in self.monsters
                     if m.alive and m is not target
                     and abs(m.x - target.x) <= aoe_range]
            extra.sort(key=lambda m: abs(m.x - target.x))
            for m in extra[:aoe_cap]:
                hits.append((m, self._strike_damage(m, phys, mult) * aoe_mult))

        gain = 0.0
        cull = "ck_cull_10" in hero.flags
        for mob, dmg in hits:
            was_alive = mob.alive
            self._deal(mob, dmg, hero.damage_type, is_crit)
            # ck_cull_10: finish a target left below the cull threshold after the
            # hit. Bosses are cullable too now (§2 rework), at a lower fraction.
            if cull and mob.alive and mob.max_hp > 0:
                frac = CULL_FRAC_BOSS if mob.is_boss else CULL_FRAC
                if mob.hp <= mob.max_hp * frac:
                    self._deal(mob, mob.hp + 1.0, hero.damage_type, False)
            gain += dmg * min(s.life_leech, LEECH_CAP_PCT) / 100.0
            if was_alive and not mob.alive:
                gain += s.life_on_kill
        if gain > 0:
            self._apply_leech(gain)

        # galewind (knockback): chance to shove the primary target away from the
        # hero. Pure position nudge — mob re-approaches next tick (soft DPS gate).
        if ("knockback" in hero.flags and target.alive
                and self.rng.random() < unique_specials.KNOCKBACK_CHANCE):
            direction = 1.0 if target.x >= hero.x else -1.0
            target.x += direction * unique_specials.KNOCKBACK_DIST

    def _apply_leech(self, gain: float) -> None:
        """Apply life gain to the hero (fills hp, ck_overheal spill into temp HP).
        Thin wrapper over the shared combat_math.apply_leech so the auto-attack
        and skill paths gain life identically (audit 2b)."""
        apply_leech(self.hero, gain)

    def _monster_strike(self, m: Monster) -> None:
        hero = self.hero
        # evasion (audit H1): a fully-dodged hit deals nothing. Roll before the
        # damage math so an evasive hero (archer identity) actually mitigates.
        if rolls_dodge(hero, self.rng):
            self.events.append(CombatEvent("miss", x=hero.x))
            return
        s = m.stats
        raw = self.rng.uniform(s.damage_min, s.damage_max)
        is_crit = self.rng.uniform(0, 100) < s.crit_chance
        raw *= s.crit_multi / 100.0 if is_crit else 1.0
        # corrosion: current stacks shave the hero's effective armour for THIS
        # hit only (never mutates hero.stats). corrosion_immune ignores it.
        eff_armor = hero.stats.armor
        if self._corrosion_stacks > 0 and "corrosion_immune" not in hero.flags:
            eff_armor *= max(0.0, 1.0 - CORROSION_PER_STACK * self._corrosion_stacks)
        # 6.5 zone-mod "burning": a slice of the hit is dealt as fire (zm_fire_pct).
        fire_pct = getattr(m, "zm_fire_pct", 0.0) if getattr(m, "zm_burning", False) else 0.0
        base_raw = raw * (1.0 - fire_pct)
        if m.damage_type == DamageType.PHYS:
            dmg = _mitigate_phys(base_raw, eff_armor, PHYS_K_HERO_DEF)
        else:
            dmg = _mitigate_elem(base_raw, hero.stats, m.damage_type)
        self._deal(hero, dmg, m.damage_type, is_crit)
        if fire_pct > 0:
            fire_raw = raw * fire_pct
            fire_dmg = _mitigate_elem(fire_raw, hero.stats, DamageType.FIRE)
            self._deal(hero, fire_dmg, DamageType.FIRE, False)
        # slime-family attackers add a corrosion stack (no-op vs corrosion_immune,
        # so we skip the bookkeeping entirely and let existing stacks decay).
        if _is_slime(m) and "corrosion_immune" not in hero.flags:
            self._corrosion_stacks = min(CORROSION_MAX_STACKS,
                                         self._corrosion_stacks + 1)
            self._corrosion_t = CORROSION_DURATION

    def _deal(self, target: Entity, dmg: float, dtype: DamageType, is_crit: bool,
              is_dot: bool = False) -> None:
        dmg = max(dmg, 0.0)
        # ashfall_mantle (stagger): a slice of an INCOMING instant hit is deferred
        # into a burn over STAGGER_DURATION instead of landing now — spreads spikes.
        # Guarded by is_dot so the deferred burn never re-staggers itself.
        if (dmg > 0 and target is self.hero and not is_dot
                and "stagger" in self.hero.flags):
            split = dmg * unique_specials.STAGGER_PCT
            if split > 0:
                dmg -= split
                dots = getattr(self.hero, "_stagger_dots", None)
                if dots is None:
                    dots = []
                    self.hero._stagger_dots = dots
                dots.append(ailments._make_dot(
                    "ignite", split, unique_specials.STAGGER_DURATION))
        # ck_overheal: the hero's temp-HP buffer soaks incoming damage first,
        # the remainder hits real hp. Only applies to the hero, not monsters.
        if dmg > 0 and target is self.hero:
            temp = getattr(target, "_ck_temp_hp", 0.0)
            if temp > 0:
                absorbed = min(temp, dmg)
                setattr(target, "_ck_temp_hp", temp - absorbed)
                dmg -= absorbed
        target.hp -= dmg
        if dmg > 0 and target.alive and not is_dot:
            target._flash = HIT_FLASH
        kind = "dot" if is_dot else ("crit" if is_crit else "damage")
        self.events.append(
            CombatEvent(kind, x=target.x, value=dmg, dtype=dtype)
        )
        if target.hp <= 0 and target.alive:
            target.hp = 0.0
            target.alive = False
            _set_anim(target, "dead")
            if isinstance(target, Monster):
                self.kills += 1
                self._corpse_timers[id(target)] = CORPSE_LINGER
                self.events.append(CombatEvent("kill", x=target.x, dtype=dtype))
                # ck_kill_heal: every kill (direct, cleave, splash or DoT) heals
                # the hero — shared helper, same on the skill path (audit M1).
                kill_heal(self.hero)
                # covenant_of_the_hunt: killing a Rare steals one of its affixes.
                self._steal_from_rare(target)

    def _cleanup_corpses(self, dt: float) -> None:
        expired: list[Monster] = []
        for m in self.monsters:
            if m.alive:
                continue
            key = id(m)
            self._corpse_timers[key] = self._corpse_timers.get(key, CORPSE_LINGER) - dt
            if self._corpse_timers[key] <= 0:
                expired.append(m)
        for m in expired:
            self.monsters.remove(m)
            self._corpse_timers.pop(id(m), None)


if __name__ == "__main__":
    rng = random.Random(42)
    hero = Hero(
        name="Test Warrior",
        stats=Stats(life=120, damage_min=8, damage_max=14, attack_speed=1.4,
                    crit_chance=20, armor=50, life_regen=2.0, added_fire=3.0),
        base_stats=Stats(),
        class_id="warrior",
    )
    hero.init_hp()

    cs = CombatSystem(hero, rng)
    for i in range(3):
        m = Monster(
            name=f"Zombie {i + 1}",
            stats=Stats(life=30, damage_min=2, damage_max=4, attack_speed=0.8,
                        move_speed=40, armor=10),
            x=hero.x + 120 + i * 60,
            monster_id="zombie",
            level=1,
            damage_type=DamageType.PHYS,
        )
        m.init_hp()
        cs.monsters.append(m)

    total_events = 0
    for _ in range(200):
        cs.tick(TICK_DT)
        total_events += len(cs.events)
        cs.events.clear()

    print(f"kills={cs.kills} events={total_events} hero_hp={hero.hp:.1f}/{hero.max_hp:.0f} "
          f"alive_mobs={sum(1 for m in cs.monsters if m.alive)} x={hero.x:.0f}")
    assert cs.kills > 0, "hero killed nothing"
    assert hero.alive

    # --- S.4 class-keystone hook smoke tests -----------------------------------
    def _mk_hero(flags):
        h = Hero(name="H", stats=Stats(life=100, damage_min=5, damage_max=5,
                                       attack_speed=1.0, crit_chance=0, crit_multi=200),
                 base_stats=Stats(), class_id="warrior")
        h.init_hp()
        h.flags = set(flags)
        return h

    def _mk_mob(life, is_boss=False):
        m = Monster(name="M", stats=Stats(life=life, armor=0), x=0.0,
                    monster_id="t", level=1, is_boss=is_boss,
                    damage_type=DamageType.PHYS)
        m.init_hp()
        return m

    # ck_cull_10: mob left at 9% hp is culled; a boss at 9% survives (boss cull=5%).
    h = _mk_hero({"ck_cull_10"})
    c = CombatSystem(h, random.Random(1))
    mob = _mk_mob(100); mob.hp = 9.0; c.monsters.append(mob)
    c._deal(mob, 0.0, DamageType.PHYS, False)  # hit that leaves it below 10%
    # emulate the _hero_strike cull check directly (no damage rolled):
    if mob.alive and mob.hp <= mob.max_hp * CULL_FRAC:
        c._deal(mob, mob.hp + 1.0, DamageType.PHYS, False)
    assert not mob.alive, "cull failed on 9% normal mob"
    boss = _mk_mob(100, is_boss=True); boss.hp = 9.0; c.monsters.append(boss)
    if boss.alive and boss.hp <= boss.max_hp * (CULL_FRAC_BOSS if boss.is_boss else CULL_FRAC):
        c._deal(boss, boss.hp + 1.0, DamageType.PHYS, False)
    assert boss.alive, "boss wrongly culled at 9% (threshold should be 5%)"
    boss.hp = 4.0
    if boss.alive and boss.hp <= boss.max_hp * CULL_FRAC_BOSS:
        c._deal(boss, boss.hp + 1.0, DamageType.PHYS, False)
    assert not boss.alive, "boss not culled at 4%"

    # ck_fifth_shot: every 5th strike is a forced crit (crit_chance=0 otherwise).
    h = _mk_hero({"ck_fifth_shot"})
    c = CombatSystem(h, random.Random(2))
    crits = []
    for i in range(10):
        tm = _mk_mob(10_000); c.monsters = [tm]
        c.events.clear()
        c._hero_strike(tm)
        crits.append(any(e.kind == "crit" for e in c.events))
    assert crits == [False, False, False, False, True] * 2, f"fifth_shot pattern wrong: {crits}"

    # ck_overheal: leech overflow spills into temp HP, capped at 20% max life.
    h = _mk_hero({"ck_overheal"})
    h.stats.life_leech = 100.0  # everything leeches
    c = CombatSystem(h, random.Random(3))
    h.hp = h.max_hp  # already full -> all leech overflows
    c._apply_leech(50.0)  # cap is 20 (20% of 100)
    assert abs(getattr(h, "_ck_temp_hp") - 20.0) < 1e-9, getattr(h, "_ck_temp_hp")
    # temp HP absorbs damage before real hp
    c._deal(h, 12.0, DamageType.PHYS, False)
    assert abs(getattr(h, "_ck_temp_hp") - 8.0) < 1e-9 and h.hp == h.max_hp
    c._deal(h, 20.0, DamageType.PHYS, False)  # 8 soaked, 12 to hp
    assert getattr(h, "_ck_temp_hp") == 0.0 and abs(h.hp - (h.max_hp - 12.0)) < 1e-9
    # decay: 2% max life / sec
    setattr(h, "_ck_temp_hp", 10.0)
    c._regen(h, 1.0)  # regen=0, decays 0.02*100*1 = 2
    assert abs(getattr(h, "_ck_temp_hp") - 8.0) < 1e-9, getattr(h, "_ck_temp_hp")

    # ck_kill_heal: a kill heals 2% max life.
    h = _mk_hero({"ck_kill_heal"})
    c = CombatSystem(h, random.Random(4))
    h.hp = 50.0
    km = _mk_mob(5); c.monsters = [km]
    c._deal(km, 999.0, DamageType.PHYS, False)
    assert not km.alive and abs(h.hp - 52.0) < 1e-9, h.hp

    print("combat OK")
