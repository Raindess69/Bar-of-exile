"""Bar of Exile — headless farm simulator (report-only, never touches balance).

Mirrors main.py's Game loop without Qt: spawner.tick -> combat.tick -> death check
-> tick_skills_v2 -> kill rewards (the m._rewarded flag, Spawner.notify_kill,
event drain, grant_skill_xp + apply_level_growth + ensure_skills_v2 after grant_xp).

Strategy per class: replay the campaign (Acts 1-3) across all four difficulty
loops — Normal -> Cruel -> Merciless -> Nightmare — exactly as main.py does.
Within a loop, farm the current zone until the next one unlocks by level (boss
zones: stay until the boss is dead); on clearing the Act-3 finale (lord_of_ash),
roll into the next loop once its gate opens (final boss killed on the previous
loop AND the level requirement). Each loop raises the effective monster level via
the difficulty's mlvl_offset, which is what keeps XP flowing — sitting on a low
loop decays XP to a near-zero floor (progression.zone_xp_mult), so looping is the
only way to ~100. Greedily equip any drop that beats current gear on a rough hero
score. If the hero dies while a zone boss is up, the boss despawns with the
monster wipe and the Spawner never re-arms it — same as main.py, where the player
recovers by re-selecting the zone in ZonesPanel (fresh Spawner). The sim mirrors
that player action on respawn, otherwise every run stalls forever at the first
boss death.

Usage: python tools/sim.py [--hours N] [--classes warrior,mage] [--seed N]
                           [--offline H] [--csv]
Writes docs/sim_report.md (+ docs/sim_report.csv with --csv) and prints a table.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from game import classes, progression, tree, world
from game.combat import CombatSystem
from game.core import TICK_DT, CombatEvent, Item, Monster
from game.item_roller import Rarity
from game.loot import roll_boss_drops, roll_drop, roll_gold
from game.skills_v2 import ensure_skills_v2, grant_skill_xp, tick_skills_v2

# Level marks span the whole 4-loop range: reaching ~100 now REQUIRES walking the
# campaign four times (Normal->Cruel->Merciless->Nightmare), so the report needs
# the higher milestones to show the loop progression, not just the Normal opener.
LEVEL_MARKS = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
RESPAWN_SEC = 2.5   # main.py RESPAWN_SEC
VIEW_W = 800.0      # main.py default view width

# The loop chain replays the campaign zones (Acts 1-3) only; Act 4 / rifts are
# manual endgame and are excluded from the auto-advance chain (world.py mirrors
# this via CAMPAIGN_ZONES). Each difficulty loop re-walks exactly this list.
CAMPAIGN = world.CAMPAIGN_ZONES
# Unique boss templates across one campaign loop (a boss recurs every loop with
# the same template id, so dedupe for the summary's per-boss columns). Order
# follows campaign progression so the columns read Act1 -> Act3 finale.
_seen_boss: set[str] = set()
BOSSES = [(z.boss_template_id, world.TEMPLATES[z.boss_template_id].name)
          for z in CAMPAIGN if z.boss_template_id
          and not (z.boss_template_id in _seen_boss
                   or _seen_boss.add(z.boss_template_id))]


class TrackingCombat(CombatSystem):
    """CombatSystem that accumulates hero->monster damage for avg DPS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hero_damage = 0.0

    def _deal(self, target, dmg, dtype, is_crit, is_dot=False):
        if isinstance(target, Monster):
            self.hero_damage += max(dmg, 0.0)
        super()._deal(target, dmg, dtype, is_crit, is_dot)


def hero_score(hero) -> float:
    """Rough gear metric: offense-weighted DPS + effective HP proxy."""
    s = hero.stats
    dps = ((s.damage_min + s.damage_max) / 2
           + s.added_fire + s.added_cold + s.added_lightning + s.added_chaos
           ) * max(s.attack_speed, 0.05)
    ehp = (s.life + s.armor * 0.6 + s.evasion * 0.4 + s.life_regen * 8
           + (s.res_fire + s.res_cold + s.res_lightning + s.res_chaos) * 0.7)
    return dps * 3.0 + ehp


def _ehp(hero) -> float:
    """Effective-HP proxy for reporting: life padded by mitigation stats."""
    s = hero.stats
    return (s.life + s.armor * 0.6 + s.evasion * 0.4
            + (s.res_fire + s.res_cold + s.res_lightning + s.res_chaos) * 0.7)


# ------------------------------------------------------------ tree allocation
# Per-stat weights mirroring hero_score's DPS(×3) + EHP shape, so a node's value
# is judged the same way gear is. A real player walks toward life/damage/crit;
# this greedy scorer reproduces that without mutating the hero to test each node.
# Tree stats are almost all `inc`% (flats ~0), so weights are "value per 1% inc"
# (offense ≈ 3× defense, matching the DPS×3 vs EHP×1 split). Flat added-damage
# nodes use their own scale via the flat term.
_STAT_W = {
    # offense — ~1% DPS each, weighted ×3 like hero_score's dps bucket
    "damage_inc": 3.0, "attack_speed": 3.0, "cast_speed_inc": 3.0,
    "crit_chance": 2.5, "crit_multi": 2.0, "cooldown_reduction": 2.5,
    "aoe_damage_inc": 1.6, "boss_damage_inc": 1.2, "dot_damage_inc": 1.2,
    "life_leech": 6.0,
    # flat added damage (per point of min/max/element) — small absolute numbers
    "damage_min": 3.0, "damage_max": 3.0, "added_fire": 3.0, "added_cold": 3.0,
    "added_lightning": 3.0, "added_chaos": 3.0,
    # defense / sustain — ~1% EHP each (life inc), weight ×1
    "life": 1.0, "armor": 0.6, "evasion": 0.4, "life_regen": 1.2,
    "res_fire": 0.9, "res_cold": 0.9, "res_lightning": 0.9, "res_chaos": 0.9,
    "life_on_kill": 1.5, "move_speed": 2.0, "healing_inc": 0.5,
    # utility — mild pull so magic-find / xp nodes aren't worthless detours
    "item_rarity": 0.4, "gold_find": 0.2, "xp_gain_inc": 0.6,
}


def node_value(node) -> float:
    """Static worth of a node from its StatMods: flat added-damage counts at full
    weight; inc/more % counts per-point at the same weight (tree % values are
    small integers, so no extra halving). Higher = a player wants it sooner."""
    v = 0.0
    for m in node.mods:
        w = _STAT_W.get(m.stat, 0.15)
        v += m.flat * w + (m.inc + m.more) * w
    return v


def auto_allocate_tree(hero) -> int:
    """Spend every available passive point (and boss-granted Class Point) the way
    a player would: repeatedly take the highest-value reachable node. Frontier is
    recomputed after each pick so newly-adjacent nodes open up. Returns nodes taken.

    Normal points buy the best reachable normal node; Class Points buy the best
    reachable ck (class sub-tree) node — the two pools never cross (tree.allocate
    enforces that). Notables/keystones are valued by their own mods, so a strong
    keystone one step off the frontier still wins on its turn."""
    taken = 0
    # normal tree points
    while tree.points_available(hero) > 0:
        best, best_v = None, -1.0
        for nid, node in tree.NODES.items():
            if node.kind == "ck" or nid in hero.passives:
                continue
            path = tree.path_to(hero, nid)
            if not path or len(path) > tree.points_available(hero):
                continue
            # value the whole path (transit smalls count too), amortised per point
            pv = sum(node_value(tree.NODES[p]) for p in path) / len(path)
            if pv > best_v:
                best, best_v = nid, pv
        if best is None:
            break
        got = tree.allocate_path(hero, best)
        if got <= 0:
            break
        taken += got
    # class points -> best reachable ck node (gates checked inside allocate)
    while tree.class_points_available(hero) > 0:
        cands = [(node_value(node), nid) for nid, node in tree.NODES.items()
                 if node.kind == "ck" and nid not in hero.passives
                 and tree.is_available(hero, nid)]
        if not cands:
            break
        cands.sort(reverse=True)
        if not tree.allocate(hero, cands[0][1]):
            break
        taken += 1
    return taken


class Sim:
    def __init__(self, class_id: str, hours: float, seed: int):
        self.rng = random.Random(seed)
        self.hero = classes.make_hero(class_id)
        self.hero.x = 40.0
        ensure_skills_v2(self.hero)  # seed Skills V2 loadout (as main.py does)
        # 4-loop campaign: start on Normal at the Act-1 opener; the difficulty
        # carries the mlvl_offset that the Spawner applies to monster scaling.
        self.diff = progression.DIFFICULTIES[0]  # normal
        self.diff_i = 0
        self.zone = world.first_campaign_zone()
        self.combat = TrackingCombat(self.hero, self.rng)
        self.spawner = world.Spawner(self.zone, self.diff.monster_mult, self.rng,
                                     mlvl_offset=self.diff.mlvl_offset)
        self.t = 0.0
        self.end_t = hours * 3600.0
        self.death_timer = 0.0
        self.total_kills = 0
        self.deaths = 0
        self.equips = 0
        self.skill_damage = 0.0
        self.drops_by_rarity: dict[str, int] = {}   # rarity name -> count
        self.boss_attempts: dict[str, int] = {}     # monster_id -> boss encounters
        self.ehp_samples: list[float] = []          # sampled effective-HP proxy
        self.level_times: dict[int, float] = {1: 0.0}
        self.boss_times: dict[str, float] = {}
        self.zone_deaths: dict[str, int] = {}
        self.boss_wipes: dict[str, int] = {}  # zone id -> deaths with the boss up
        self.zone_entries: list[tuple[str, float, int]] = [(self.zone.id, 0.0, 1)]
        # 4-loop gate feed: "{monster_id}@{difficulty_id}" for every act boss ever
        # first-killed. difficulty_unlocked reads this to open the next loop.
        self.boss_first_kills: list[str] = []
        # Loop timeline: one row per difficulty loop started, seeded with Normal at
        # t=0 (difficulty_id, sim_time, hero_level). Rolls append on loop-over.
        self.loop_entries: list[tuple[str, float, int]] = [(self.diff.id, 0.0, 1)]
        self.anomalies: dict[str, int] = {}
        self._ev: list[CombatEvent] = []
        # per-sim-hour snapshots (Gate 6.0): cumulative counters at each hour mark
        self.hourly: list[dict] = []
        self._next_hour = 3600.0
        self._snap_prev = {"kills": 0, "deaths": 0, "gold": 0,
                           "dmg": 0.0, "rarity": {}}

    # -------------------------------------------------------------- guards
    def _guard(self, label: str, fn, *args, **kwargs):
        """Never fix foreign modules: log the failure and keep simulating."""
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            key = f"{label}: {type(e).__name__}: {e}"
            self.anomalies[key] = self.anomalies.get(key, 0) + 1
            return None

    # -------------------------------------------------------------- loop
    def run(self) -> dict:
        while self.t < self.end_t:
            self.step()
        return self.result()

    def step(self) -> None:
        hero = self.hero
        was_alive = hero.alive
        if was_alive:
            self._guard("spawner.tick", self.spawner.tick,
                        TICK_DT, self.combat.monsters, hero.x, VIEW_W)
        self._guard("combat.tick", self.combat.tick, TICK_DT)
        self.combat.events.clear()
        if was_alive and (not hero.alive or hero.hp <= 0):
            self.on_death()
        if hero.alive:
            self._guard("tick_skills_v2", tick_skills_v2,
                        hero, self.combat.monsters, self._ev, TICK_DT, self.rng)
            for e in self._ev:
                if e.kind == "damage":
                    self.skill_damage += e.value
            self._ev.clear()
            for m in self.combat.monsters:
                if not m.alive and not getattr(m, "_rewarded", False):
                    m._rewarded = True
                    self.on_kill(m)
        else:
            self.death_timer -= TICK_DT
            if self.death_timer <= 0:
                self.respawn()
        self.t += TICK_DT
        if int(self.t) % 60 == 0 and hero.alive:
            self.ehp_samples.append(_ehp(hero))
        if self.t >= self._next_hour:
            self._snapshot_hour()
            self._next_hour += 3600.0

    def _snapshot_hour(self) -> None:
        """Record cumulative-since-last-hour deltas for per-hour rate metrics."""
        p = self._snap_prev
        rar_delta = {k: self.drops_by_rarity.get(k, 0) - p["rarity"].get(k, 0)
                     for k in set(self.drops_by_rarity) | set(p["rarity"])}
        self.hourly.append({
            "hour": round(self.t / 3600.0),
            "level": self.hero.level,
            "kills": self.total_kills - p["kills"],
            "deaths": self.deaths - p["deaths"],
            "gold": self.hero.gold - p["gold"],
            "dmg": (self.combat.hero_damage + self.skill_damage) - p["dmg"],
            "rarity": rar_delta,
            "ehp": (sum(self.ehp_samples) / len(self.ehp_samples)
                    if self.ehp_samples else 0.0),
            "zone": self.zone.id,
        })
        self._snap_prev = {
            "kills": self.total_kills, "deaths": self.deaths,
            "gold": self.hero.gold,
            "dmg": self.combat.hero_damage + self.skill_damage,
            "rarity": dict(self.drops_by_rarity)}
        self.ehp_samples.clear()

    # -------------------------------------------------------------- events
    def on_kill(self, m: Monster) -> None:
        self.total_kills += 1
        self._guard("spawner.notify_kill", self.spawner.notify_kill, m)
        gold = self._guard("roll_gold", roll_gold, m, self.rng)
        self.hero.gold += gold or 0
        if m.is_boss:
            self.boss_times.setdefault(m.monster_id, self.t)
            self.boss_attempts[m.monster_id] = \
                self.boss_attempts.get(m.monster_id, 0) + 1
            # Difficulty-gate feed: record the first kill of each act boss per loop
            # ("{monster_id}@{difficulty_id}"); difficulty_unlocked needs the final
            # boss's entry present to open the next loop. Sim-local bookkeeping.
            key = f"{m.monster_id}@{self.diff.id}"
            if key not in self.boss_first_kills:
                self.boss_first_kills.append(key)
            # S.4: act bosses grant Class Points (once per boss ever) — mirror
            # main.py so the ck sub-tree actually gets fed during the sim.
            if self._guard("grant_class_point",
                           tree.grant_class_point, self.hero, m.monster_id):
                self._guard("auto_allocate_tree", auto_allocate_tree, self.hero)
            drops = self._guard("roll_boss_drops", roll_boss_drops,
                                m, m.level, self.rng, self.diff.loot_bonus) or []
        else:
            item = self._guard("roll_drop", roll_drop,
                               m, m.level, self.rng, self.diff.loot_bonus)
            drops = [item] if item else []
        for it in drops:
            if it is not None:
                rname = getattr(it.rarity, "name", str(it.rarity))
                self.drops_by_rarity[rname] = self.drops_by_rarity.get(rname, 0) + 1
            if self._guard("try_equip", self.try_equip, it):
                self.equips += 1
        prev = self.hero.level
        # XP mirrors main.py: base * xp_mult, then decayed by zone_xp_mult against
        # the EFFECTIVE monster level (zone mlvl + difficulty offset). The deep 2%
        # floor is what makes staying on a low loop a dead end — the sim MUST apply
        # it or XP calibration reads wildly optimistic.
        mob_xp = int(m.xp_reward * self.diff.xp_mult)
        eff_mlvl = self.zone.monster_level + self.diff.mlvl_offset
        mob_xp = int(mob_xp * progression.zone_xp_mult(self.hero.level, eff_mlvl))
        mob_xp = max(1, mob_xp)
        self._guard("grant_skill_xp", grant_skill_xp, self.hero, mob_xp)
        leveled = self._guard("grant_xp", progression.grant_xp,
                              self.hero, mob_xp, self._ev)
        self._ev.clear()
        if leveled:
            self._guard("apply_level_growth", classes.apply_level_growth, self.hero)
            self._guard("ensure_skills_v2", ensure_skills_v2, self.hero)
            # spend the freshly-earned passive point(s) like a player would
            self._guard("auto_allocate_tree", auto_allocate_tree, self.hero)
            for lv in range(prev + 1, self.hero.level + 1):
                self.level_times.setdefault(lv, self.t)
        self.maybe_advance_zone()

    def try_equip(self, item: Item | None) -> bool:
        hero = self.hero
        if item is None or item.req_level > hero.level:
            return False
        slot = item.slot.value
        if slot not in hero.equipment:
            return False
        old = hero.equipment[slot]
        before = hero_score(hero)
        hero.equipment[slot] = item
        hero.recalc()
        if hero_score(hero) > before:
            return True
        hero.equipment[slot] = old
        hero.recalc()
        return False

    def maybe_advance_zone(self) -> None:
        """Idle auto-advance within a loop, then loop-rollover — mirrors main.py's
        _maybe_auto_advance + _maybe_start_next_loop over CAMPAIGN_ZONES."""
        # Hold boss zones until the boss is actually down.
        if self.zone.boss_template_id and not self.spawner.boss_killed:
            return
        nxt = world.next_campaign_zone(self.zone)
        if nxt is not None:
            # Gate on the RAW monster_level (not the offset one) exactly like
            # main.py: under-levelled -> keep farming here until the next opens.
            if not progression.zone_unlocked(self.hero.level, nxt.monster_level):
                return
            self._switch_zone(nxt)
            return
        # No next campaign zone -> we just cleared the Act-3 finale (lord_of_ash).
        # If the next difficulty's gate is open, roll the loop over into its Act 1.
        self._maybe_start_next_loop()

    def _switch_zone(self, zone) -> None:
        """Move into `zone` under the current difficulty: fresh Spawner (with the
        loop's mlvl_offset), reset position/HP, record a zone entry."""
        self.zone = zone
        self.combat.monsters.clear()
        self.spawner = world.Spawner(self.zone, self.diff.monster_mult, self.rng,
                                     mlvl_offset=self.diff.mlvl_offset)
        self.hero.x = 40.0
        self.hero.alive = True
        self.hero.hp = self.hero.max_hp
        self.zone_entries.append((zone.id, self.t, self.hero.level))

    def _maybe_start_next_loop(self) -> None:
        """Roll into the next difficulty loop once its gate opens (final act boss
        killed on this loop AND hero at the unlock level). Sim-local control flow —
        the gate check itself calls into progression, everything else is local."""
        idx = next((i for i, d in enumerate(progression.DIFFICULTIES)
                    if d.id == self.diff.id), None)
        if idx is None or idx + 1 >= len(progression.DIFFICULTIES):
            return  # already on the hardest loop — stay (farm the finale)
        nxt_diff = progression.DIFFICULTIES[idx + 1]
        if not progression.difficulty_unlocked(
                nxt_diff.id, self.boss_first_kills, self.hero.level):
            return  # gate not met — stay on this loop
        self.diff = nxt_diff
        self.diff_i = idx + 1
        self._switch_zone(world.first_campaign_zone())
        self.loop_entries.append((nxt_diff.id, self.t, self.hero.level))

    def on_death(self) -> None:
        self.deaths += 1
        self.zone_deaths[self.zone.id] = self.zone_deaths.get(self.zone.id, 0) + 1
        self.hero.alive = False
        self.hero.hp = 0
        self.death_timer = RESPAWN_SEC

    def respawn(self) -> None:
        self.combat.monsters.clear()
        # Dying wipes monsters incl. a live boss, and the Spawner never re-arms
        # it (boss_spawned stays True). main.py players recover by re-entering
        # the zone (new Spawner); mirror that here or the sim stalls forever.
        if (self.zone.boss_template_id and self.spawner.boss_spawned
                and not self.spawner.boss_killed):
            self.boss_wipes[self.zone.id] = self.boss_wipes.get(self.zone.id, 0) + 1
            self.spawner = world.Spawner(self.zone, self.diff.monster_mult,
                                         self.rng, mlvl_offset=self.diff.mlvl_offset)
        self.hero.alive = True
        self.hero.hp = self.hero.max_hp
        self.hero.x = 40.0

    # -------------------------------------------------------------- output
    def result(self) -> dict:
        hours = self.t / 3600.0
        return {
            "class_id": self.hero.class_id,
            "hours": hours,
            "level": self.hero.level,
            "xp": self.hero.xp,
            "gold": self.hero.gold,
            "kills": self.total_kills,
            "deaths": self.deaths,
            "equips": self.equips,
            "points_spent": tree.points_spent(self.hero),
            "points_avail": tree.points_available(self.hero),
            "ck_allocated": len(tree.ck_allocated(self.hero)),
            "cp_avail": tree.class_points_available(self.hero),
            "keystones": [tree.NODES[n].name for n in self.hero.passives
                          if n in tree.NODES and tree.NODES[n].kind == "keystone"],
            "kills_h": self.total_kills / hours if hours else 0.0,
            "deaths_h": self.deaths / hours if hours else 0.0,
            "dps": (self.combat.hero_damage + self.skill_damage) / self.t if self.t else 0.0,
            "drops_by_rarity": self.drops_by_rarity,
            "boss_attempts": self.boss_attempts,
            "hourly": self.hourly,
            "level_times": self.level_times,
            "boss_times": self.boss_times,
            "zone_deaths": self.zone_deaths,
            "boss_wipes": self.boss_wipes,
            "zone_entries": self.zone_entries,
            "final_zone": self.zone.id,
            "final_difficulty": self.diff.id,
            "loop_entries": self.loop_entries,
            "anomalies": self.anomalies,
        }


# ------------------------------------------------------------------ report
def fmt_t(sec: float | None) -> str:
    if sec is None:
        return "-"
    if sec < 5400:
        return f"{sec / 60:.1f}m"
    return f"{sec / 3600:.2f}h"


def _row(r: dict) -> list[str]:
    cells = [r["class_id"]]
    cells += [fmt_t(r["level_times"].get(lv)) for lv in LEVEL_MARKS]
    cells += [fmt_t(r["boss_times"].get(bid)) for bid, _ in BOSSES]
    cells += [f"{r['kills_h']:.0f}", f"{r['deaths_h']:.1f}", f"{r['dps']:.1f}",
              str(r["level"])]
    return cells


def _headers() -> list[str]:
    return (["Class"] + [f"L{lv}" for lv in LEVEL_MARKS]
            + [name for _, name in BOSSES]
            + ["Kills/h", "Deaths/h", "Avg DPS", "Final lvl"])


def print_table(results: list[dict]) -> None:
    headers = _headers()
    rows = [_row(r) for r in results]
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))


def _conclusions(results: list[dict]) -> list[str]:
    out = []
    by_lvl = sorted(results, key=lambda r: (-r["level"], -r["xp"]))
    fast, slow = by_lvl[0], by_lvl[-1]
    out.append(f"- **Fastest progression:** {fast['class_id']} "
               f"(lvl {fast['level']}, {fast['kills_h']:.0f} kills/h). "
               f"**Slowest:** {slow['class_id']} (lvl {slow['level']}, "
               f"{slow['kills_h']:.0f} kills/h).")
    # walls: slowest level bracket averaged across classes that reached it
    brackets = list(zip(LEVEL_MARKS, LEVEL_MARKS[1:]))
    avg: dict[tuple[int, int], float] = {}
    for a, b in brackets:
        ts = [r["level_times"][b] - r["level_times"][a] for r in results
              if a in r["level_times"] and b in r["level_times"]]
        if ts:
            avg[(a, b)] = sum(ts) / len(ts)
    if avg:
        (a, b), sec = max(avg.items(), key=lambda kv: kv[1])
        out.append(f"- **Biggest progression wall:** levels {a}→{b}, "
                   f"avg {fmt_t(sec)} across classes that got there.")
    unreached = {lv for lv in LEVEL_MARKS
                 for r in results if lv not in r["level_times"]}
    if unreached:
        out.append(f"- **Not reached by every class:** "
                   f"{', '.join(f'L{lv}' for lv in sorted(unreached))}.")
    deadly = [r for r in results if r["deaths_h"] >= 2.0]
    if deadly:
        out.append("- **High death rate:** "
                   + ", ".join(f"{r['class_id']} ({r['deaths_h']:.1f}/h)"
                               for r in deadly) + ".")
    for bid, name in BOSSES:
        missed = [r["class_id"] for r in results if bid not in r["boss_times"]]
        if missed:
            out.append(f"- **{name} not killed by:** {', '.join(missed)}.")
    # stuck detection: long tail spent in a non-terminal zone without clearing it.
    # The sim is legitimately "done/farming" only when it has reached the Nightmare
    # loop AND is sitting in the campaign finale zone (CAMPAIGN[-1]); everything
    # else is a real stall worth flagging. Boss lookups use CAMPAIGN_ZONES.
    finale_zone = CAMPAIGN[-1].id
    for r in results:
        zid, entered, _ = r["zone_entries"][-1]
        tail = r["hours"] * 3600.0 - entered
        boss_id = next((z.boss_template_id for z in CAMPAIGN if z.id == zid), None)
        cleared = boss_id and boss_id in r["boss_times"]
        terminal = (r["final_difficulty"] == "nightmare" and zid == finale_zone)
        if tail > 0.25 * r["hours"] * 3600.0 and not cleared and not terminal:
            wipes = r["boss_wipes"].get(zid, 0)
            out.append(f"- **{r['class_id']} stuck in `{zid}`** for the last "
                       f"{fmt_t(tail)}" + (f", {wipes} boss wipes" if wipes else "")
                       + ".")
    return out


def write_report(results: list[dict], hours: float, seed: int, path: str) -> None:
    headers = _headers()
    lines = [
        "# Bar of Exile — farm simulation report",
        "",
        f"Headless sim of `main.py`'s loop (TICK_DT={TICK_DT}, 4-loop campaign: "
        f"Normal -> Cruel -> Merciless -> Nightmare), "
        f"{hours:g} game hours per class, seed base {seed}.",
        "Strategy: replay the campaign (Acts 1-3) across all four difficulty loops "
        "— farm current zone until the next unlocks by level (boss zones held "
        "until the boss dies), then on clearing the Act-3 finale roll into the "
        "next loop once its gate opens (final boss killed on the previous loop + "
        "level req). Each loop raises the effective monster level (mlvl_offset), "
        "so XP keeps flowing — staying on a low loop decays XP to a 2% floor. "
        "Greedy auto-equip of drops by a rough score (DPS + EHP proxy). Balance "
        "untouched — report only.",
        "",
        "## Summary",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for r in results:
        lines.append("| " + " | ".join(_row(r)) + " |")
    lines += ["", "## Zone timeline (entered at / hero level)", ""]
    for r in results:
        entries = ", ".join(f"{zid} @ {fmt_t(t)} (lvl {lvl})"
                            for zid, t, lvl in r["zone_entries"])
        lines.append(f"- **{r['class_id']}** — {entries}. "
                     f"Ended in `{r['final_zone']}` with {r['gold']} gold, "
                     f"{r['equips']} gear upgrades, "
                     f"{r['points_spent']} passives spent"
                     + (f" ({r['points_avail']} unspent)" if r['points_avail'] else "")
                     + f", {r['ck_allocated']} class nodes"
                     + (f" ({r['cp_avail']} CP unspent)" if r['cp_avail'] else "")
                     + (f", keystones: {', '.join(r['keystones'])}"
                        if r['keystones'] else "") + ".")
    lines += ["", "## Loop timeline (difficulty loop started at / hero level)", ""]
    for r in results:
        loops = ", ".join(f"{did} @ {fmt_t(t)} (lvl {lvl})"
                          for did, t, lvl in r["loop_entries"])
        lines.append(f"- **{r['class_id']}** — {loops}. "
                     f"Ended on **{r['final_difficulty']}** at lvl {r['level']}.")
    lines += ["", "## Deaths by zone (boss wipes = deaths with the zone boss up)", ""]
    for r in results:
        parts = []
        for zid, n in sorted(r["zone_deaths"].items(), key=lambda kv: -kv[1]):
            wipes = r["boss_wipes"].get(zid, 0)
            parts.append(f"{zid} x{n}" + (f" ({wipes} boss wipes)" if wipes else ""))
        lines.append(f"- **{r['class_id']}** — "
                     + (", ".join(parts) if parts else "no deaths") + ".")
    lines += ["", "## Conclusions", ""]
    lines += _conclusions(results)
    lines += ["", "## Per-hour metrics (rates, drops by rarity)", ""]
    for r in results:
        if not r.get("hourly"):
            continue
        lines.append(f"### {r['class_id']}")
        lines.append("")
        lines.append("| Hour | Lvl | Kills | Deaths | Gold | DPS | EHP | "
                     "Normal | Magic | Rare | Unique | Zone |")
        lines.append("|" + "|".join("---" for _ in range(12)) + "|")
        for h in r["hourly"]:
            rar = h["rarity"]
            lines.append(
                f"| {h['hour']} | {h['level']} | {h['kills']} | {h['deaths']} | "
                f"{h['gold']} | {h['dmg'] / 3600.0:.0f} | {h['ehp']:.0f} | "
                f"{rar.get('NORMAL', 0)} | {rar.get('MAGIC', 0)} | "
                f"{rar.get('RARE', 0)} | {rar.get('UNIQUE', 0)} | {h['zone']} |")
        lines.append("")
    lines += ["", "## Anomalies (errors in game modules, bypassed)", ""]
    all_anoms = [(r["class_id"], msg, n)
                 for r in results for msg, n in r["anomalies"].items()]
    if all_anoms:
        lines += [f"- `{cid}` — {msg} (x{n})" for cid, msg, n in all_anoms]
    else:
        lines.append("None.")
    lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nreport written: {path}")


def write_csv(results: list[dict], path: str) -> None:
    """Per-hour rows across all classes for spreadsheet analysis (Gate 6.0)."""
    rows = ["class,hour,level,kills,deaths,gold,dps,ehp,"
            "normal,magic,rare,unique,zone"]
    for r in results:
        for h in r.get("hourly", []):
            rar = h["rarity"]
            rows.append(",".join(str(x) for x in [
                r["class_id"], h["hour"], h["level"], h["kills"], h["deaths"],
                h["gold"], f"{h['dmg'] / 3600.0:.1f}", f"{h['ehp']:.1f}",
                rar.get("NORMAL", 0), rar.get("MAGIC", 0),
                rar.get("RARE", 0), rar.get("UNIQUE", 0), h["zone"]]))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    print(f"csv written: {path}")


def run_offline(class_id: str, online_hours: float, offline_hours: float,
                seed: int) -> None:
    """Compare online vs offline gain: farm `online_hours` to build a hero, then
    apply `offline_hours` of away-time through save.offline_progress (Gate 6.1)."""
    from game import save
    sim = Sim(class_id, online_hours, seed)
    sim.run()
    lvl_before, xp_before = sim.hero.level, sim.hero.xp
    online_xph = xp_lin(sim.hero) / online_hours if online_hours else 0.0
    off = save.offline_progress(
        saved_at=0.0, hero=sim.hero, zone_id=sim.zone.id,
        rng=random.Random(seed))
    # save.offline_progress reads elapsed from wall clock via saved_at=0; some
    # builds take explicit hours — guard either shape.
    print(f"[offline] {class_id}: online {online_hours:g}h -> lvl {lvl_before} "
          f"(~{online_xph:.0f} xp/h online)")
    print(f"          offline result: {off}")


def xp_lin(hero) -> float:
    """Cumulative XP proxy = total xp poured in, for rate comparison."""
    return progression.xp_to_level(hero.level) + hero.xp


def _apply_profile(spec: str) -> None:
    """Sweep helper: override monster_mult/mlvl_offset per difficulty from a CLI
    string so balance candidates can run in parallel without editing
    progression.py. In-memory only — mutates the loaded DIFFICULTIES dataclasses,
    writes nothing. Format: 'cruel:1.0:8;merciless:1.2:16;nightmare:1.5:26'."""
    by_id = {d.id: d for d in progression.DIFFICULTIES}
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        did, mm, off = chunk.split(":")
        d = by_id.get(did.strip())
        if d is None:
            sys.exit(f"--profile: unknown difficulty '{did}' "
                     f"(have: {', '.join(by_id)})")
        d.monster_mult = float(mm)
        d.mlvl_offset = int(off)
    tiers = "; ".join(f"{d.id} mm={d.monster_mult} off={d.mlvl_offset}"
                      for d in progression.DIFFICULTIES)
    print(f"[profile] {tiers}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Headless farm simulator for Bar of Exile")
    ap.add_argument("--hours", type=float, default=4.0, help="game hours per class")
    ap.add_argument("--classes", default=",".join(classes.CLASSES),
                    help="comma-separated class ids")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--offline", type=float, default=0.0,
                    help="hours of away-time to simulate after --hours online")
    ap.add_argument("--csv", action="store_true",
                    help="also write docs/sim_report.csv (per-hour rows)")
    ap.add_argument("--out", default="sim_report",
                    help="basename under docs/ for the report (parallel runs "
                         "must differ or they clobber each other)")
    ap.add_argument("--profile", default="",
                    help="balance sweep override: semicolon-separated "
                         "'diff_id:mon_mult:offset' tuples, e.g. "
                         "'cruel:1.0:8;merciless:1.2:16;nightmare:1.5:26'. "
                         "Mutates progression.DIFFICULTIES in this process only "
                         "(report-only sweep, never writes game files).")
    ap.add_argument("--xp-a", type=float, default=0.0,
                    help="override progression.XP_A for this process only "
                         "(0 = leave as-is). Isolates the XP-curve length knob "
                         "for parallel sweeps; report-only, writes no game files.")
    args = ap.parse_args()

    if args.xp_a > 0:
        progression.XP_A = args.xp_a
        print(f"[xp_a] XP_A={progression.XP_A}")
    if args.profile:
        _apply_profile(args.profile)

    ids = [c.strip() for c in args.classes.split(",") if c.strip()]
    unknown = [c for c in ids if c not in classes.CLASSES]
    if unknown:
        sys.exit(f"unknown classes: {unknown} (have: {', '.join(classes.CLASSES)})")

    if args.offline > 0:
        for i, cid in enumerate(ids):
            run_offline(cid, args.hours, args.offline, args.seed + i)
        return

    results = []
    for i, cid in enumerate(ids):
        t0 = time.time()
        sim = Sim(cid, args.hours, args.seed + i)
        results.append(sim.run())
        print(f"[{cid}] {args.hours:g}h simulated in {time.time() - t0:.1f}s wall "
              f"(lvl {sim.hero.level}, {sim.total_kills} kills, {sim.deaths} deaths)")

    print()
    print_table(results)
    docs_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    write_report(results, args.hours, args.seed,
                 os.path.join(docs_dir, f"{args.out}.md"))
    if args.csv:
        write_csv(results, os.path.join(docs_dir, f"{args.out}.csv"))


if __name__ == "__main__":
    main()
