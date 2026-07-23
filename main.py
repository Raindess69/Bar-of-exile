"""Bar of Exile — entry point: game loop and integration of all modules."""
from __future__ import annotations

import random
import sys
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication

from game import classes, progression, world, zone_mods
from game.combat import CombatSystem
from game.core import RARITY_COLORS, TICK_DT, CombatEvent, Hero, Monster, Rarity
from game.item_roller import RARITY_WEIGHTS
from game.loot import roll_boss_drops, roll_drop, roll_gold
from game.unique_specials import UNIQUE_DROP_MULT
from game.save import load_game, offline_progress, save_game
from game.skills_v2 import tick_skills_v2, ensure_skills_v2, grant_skill_xp
from game import tomes
from game import rifts
from game.vendor import Vendor, vendor_from_dict, vendor_to_dict
from ui.cube_panel import CubePanel
from ui.panels import CharacterPanel, InventoryPanel, PanelManager, sell_price
from ui.render import FlairSystem, GameRenderer
from ui.stash_panel import StashPanel
from ui.window import BTN_ZONE, TaskbarStrip
from ui.zones_panel import ZonesPanel

try:
    from game import tree
    from ui.tree_panel import TreePanel
except ImportError:
    tree = None
    TreePanel = None

try:
    from ui.vendor_panel import VendorPanel
except ImportError:
    VendorPanel = None

try:
    from game.gamble import GambleVendor
    from ui.gamble_panel import GamblePanel
except ImportError:
    GambleVendor = None
    GamblePanel = None

try:
    from game.stats_track import StatsTracker
    from ui.stats_panel import StatsPanel
except ImportError:
    StatsTracker = None
    StatsPanel = None

try:
    from ui.skills_panel import SkillsPanel
except ImportError:
    SkillsPanel = None

INV_CAP = 32
AUTOSAVE_SEC = 30
RESPAWN_SEC = 2.5
MAX_ACC = 0.25
RATE_SNAPSHOT_SEC = 60.0   # roll the online-rate average this often (Stage 6.1)
RATE_SMOOTH = 0.5          # EMA weight for the newest window vs history


def _slot_path(hero: Hero) -> str:
    """Per-character save file so distinct heroes don't overwrite each other.
    Filename = class + readable ascii tag + a short hash of the *raw* name.
    The hash makes the path unique per distinct name — critical for non-ASCII
    (Cyrillic) names, which the ascii tag alone collapses to the same string
    ('Гром' and 'Кель' both sanitize to '') — while staying deterministic so
    the same hero always resolves to the same file."""
    import hashlib
    import os
    import re
    from game.save import SAVE_DIR
    name = getattr(hero, "name", "") or "exile"
    tag = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
    stem = f"{hero.class_id}_{tag}_{digest}" if tag else f"{hero.class_id}_{digest}"
    return os.path.join(SAVE_DIR, f"{stem}.json")

def _free_slot_path(hero: Hero) -> str:
    """A slot path guaranteed not to overwrite an existing save. If the natural
    path is taken (same class+name already exists), append _2, _3, … so a brand
    new hero never clobbers an old one."""
    import os
    base = _slot_path(hero)
    if not os.path.exists(base):
        return base
    stem, ext = os.path.splitext(base)
    n = 2
    while os.path.exists(f"{stem}_{n}{ext}"):
        n += 1
    return f"{stem}_{n}{ext}"


def _safe_meta(what: str, build, fallback):
    """Deserialize a meta sub-object, falling back to an empty one if the saved
    data is corrupt (C3). A stale enum in vendor stock or a malformed gamble/stats
    blob must not abort the whole game boot — better an empty vendor than no game."""
    try:
        return build()
    except Exception as e:
        print(f"[save] warning: meta['{what}'] corrupt, using default: {e}")
        return fallback()


class Game:
    """Owns all state: hero, zone, combat, spawning, UI."""

    def __init__(self, hero: Hero, meta: dict, save_path: str | None = None):
        self.hero = hero
        self.rng = random.Random()
        self.meta = meta
        self.save_path = save_path or _slot_path(hero)
        self.playtime = float(meta.get("playtime", 0.0))
        self.total_kills = int(meta.get("kills", 0))
        # S.5 Skill Tomes: mobs-since-last-tome, drives roll_tome_drop's soft/hard
        # pity so a tome is never impossibly far away. Persisted in meta.
        self.tome_pity = int(meta.get("tome_pity", 0))
        # 6.6 Rifts: endless instanced endgame. `rift` holds the persistent tier /
        # death-streak; `in_rift` is the live flag for "the current zone is a rift"
        # (not persisted — a rift run is re-entered from the waypoint each boot).
        self.rift = rifts.RiftState.from_dict(meta.get("rift"))
        self.in_rift = False
        # Stage 6.1: rolling online-rate snapshot for offline catch-up. Updated
        # every RATE_SNAPSHOT_SEC from deltas since the last snapshot; persisted in
        # meta so offline_progress derives away-gain from the hero's OWN pace.
        self._rate_accum = {"xp": 0.0, "gold": 0.0, "kills": 0.0, "t": 0.0}
        self.rate_snapshot = dict(meta.get("rate_snapshot", {}))

        diff_id = meta.get("difficulty_id", "normal")
        self.difficulty = next(
            (d for d in progression.DIFFICULTIES if d.id == diff_id), progression.DIFFICULTIES[0]
        )
        try:
            self.zone = world.get_zone(meta.get("zone_id", "a1_shore"))
        except KeyError:
            self.zone = world.ZONES[0]

        # Idle auto-advance: after clearing a zone (boss down, or no boss), walk
        # to the next unlocked zone on its own — and roll over into the next
        # difficulty's Act 1 once the campaign is beaten. Default ON (idle game);
        # players toggle it off from the waypoint panel to farm a single zone.
        self.auto_advance = bool(meta.get("auto_advance", True))

        self.combat = CombatSystem(self.hero, self.rng)
        self.spawner = self._make_spawner()
        self.renderer = GameRenderer()
        self.flair = FlairSystem()
        self.acc = 0.0
        self.death_timer = 0.0
        self.view_w = 800

        self.hero.x = 40.0
        self.strip = TaskbarStrip(self._paint, self._tick, self._click)
        self.strip.on_button = self._button

        self.inv_panel = InventoryPanel(self.hero, on_change=self._on_gear_change)
        self.stash_panel = StashPanel(self.hero, on_change=self._on_gear_change)
        self.char_panel = CharacterPanel(self.hero)
        self.zones_panel = ZonesPanel(self._on_zone_select,
                                      on_toggle_auto=self._on_toggle_auto)
        self.cube_panel = CubePanel(self.hero, on_change=self._on_gear_change, rng=self.rng,
                                    on_flash=self.strip.flash_notify, on_save=self.save)
        # C3: a corrupt sub-object in meta (e.g. a stale rarity/slot enum in the
        # vendor stock) must not abort the whole boot — fall back to a fresh one.
        self.vendor = _safe_meta("vendor", lambda: vendor_from_dict(meta.get("vendor", {})),
                                 lambda: vendor_from_dict({}))
        self.vendor_panel = (
            VendorPanel(self.hero, self.vendor, self.rng, on_change=self._on_gear_change)
            if VendorPanel else None
        )
        self.inv_panel.sell_hook = self._sell_to_vendor
        self.inv_panel.can_sell = self._vendor_is_open
        self.gamble_vendor = (
            _safe_meta("gamble", lambda: GambleVendor.from_dict(meta.get("gamble", {}), self.rng),
                       lambda: GambleVendor.from_dict({}, self.rng))
            if GambleVendor else None
        )
        self.gamble_panel = (
            GamblePanel(self.hero, self.gamble_vendor, self.rng, on_change=self._on_gear_change)
            if GamblePanel and self.gamble_vendor else None
        )
        self.tree_panel = TreePanel(self.hero, on_change=self._on_gear_change) if TreePanel else None
        if tree:
            # S.4 rework retro-grant: old saves that already killed act bosses get
            # their Class Points back-filled before the tree is rebuilt.
            tree.sync_class_points_from_kills(self.hero, self.meta.get("boss_first_kills"))
            tree.rebuild(self.hero)

        self.stats = (
            _safe_meta("stats", lambda: StatsTracker.from_dict(meta.get("stats")),
                       lambda: StatsTracker.from_dict(None))
            if StatsTracker else None
        )
        self.stats_panel = StatsPanel(self.stats) if StatsPanel and self.stats else None
        self.skills_panel = SkillsPanel(self.hero, on_change=self._on_gear_change) if SkillsPanel else None

        self.panels = PanelManager(place=self._place, on_change=self._update_chevron)
        self.panels.register("inventory", self.inv_panel, refresh=self.inv_panel.refresh)
        self.panels.register("stash", self.stash_panel, refresh=self.stash_panel.refresh)
        self.panels.register("character", self.char_panel, refresh=self.char_panel.refresh)
        self.panels.register("cube", self.cube_panel, refresh=self.cube_panel.refresh)
        self.panels.register("zones", self.zones_panel, refresh=lambda: self.zones_panel.refresh(
            self.hero.level, self.zone.id, self.difficulty.id,
            boss_first_kills=self.meta.get("boss_first_kills"),
            rift_state=self.rift, auto_advance=self.auto_advance))
        if self.vendor_panel:
            self.panels.register("vendor", self.vendor_panel, refresh=self.vendor_panel.refresh)
        if self.gamble_panel:
            self.panels.register("gamble", self.gamble_panel, refresh=self.gamble_panel.refresh)
        if self.tree_panel:
            self.panels.register("tree", self.tree_panel, refresh=self.tree_panel.refresh)
        if self.skills_panel:
            self.panels.register("skills", self.skills_panel, refresh=self.skills_panel.refresh)
        if self.stats_panel:
            self.panels.register("stats", self.stats_panel,
                                 refresh=lambda: self.stats_panel.refresh(self.stats))

        # collapsible panel state (ITEMS_TREE_V2 part 3): canonical panel names to
        # restore on expand; persisted in save meta as "open_panels".
        # Older saves stored attribute names (inv_panel, ...) — map them over.
        _legacy = {"inv_panel": "inventory", "stash_panel": "stash", "char_panel": "character",
                   "zones_panel": "zones", "cube_panel": "cube", "vendor_panel": "vendor",
                   "gamble_panel": "gamble", "tree_panel": "tree", "stats_panel": "stats"}
        self._collapsed: list[str] = [_legacy.get(n, n) for n in meta.get("open_panels", [])]

        self.autosave = QTimer()
        self.autosave.timeout.connect(self.save)
        self.autosave.start(AUTOSAVE_SEC * 1000)

        self._panel_key = QShortcut(QKeySequence("F1"), self.strip)
        self._panel_key.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._panel_key.activated.connect(self._toggle_collapse)

        self.strip.show()

    # ------------------------------------------------------------------ loop
    def _tick(self, dt: float) -> None:
        self.flair.tick(dt)
        self.playtime += dt
        self._update_rate_snapshot(dt)
        self.acc = min(self.acc + dt, MAX_ACC)
        while self.acc >= TICK_DT:
            self.acc -= TICK_DT
            self._step()

    def _update_rate_snapshot(self, dt: float) -> None:
        """Roll a per-second online-rate average every RATE_SNAPSHOT_SEC of live
        play (only while alive/active). Feeds offline_progress with the hero's
        own recent pace instead of re-deriving it from zone math (Stage 6.1)."""
        acc = self._rate_accum
        acc["t"] += dt
        if acc["t"] < RATE_SNAPSHOT_SEC:
            return
        span = acc["t"]
        new = {"xp_per_sec": acc["xp"] / span,
               "gold_per_sec": acc["gold"] / span,
               "kills_per_sec": acc["kills"] / span}
        prev = self.rate_snapshot
        # Exponential smoothing so a quiet/AFK window doesn't zero the estimate.
        a = RATE_SMOOTH
        self.rate_snapshot = {
            k: (a * new[k] + (1 - a) * prev.get(k, new[k])) if prev else new[k]
            for k in new
        }
        self._rate_accum = {"xp": 0.0, "gold": 0.0, "kills": 0.0, "t": 0.0}

    def _step(self) -> None:
        events = self.combat.events
        was_alive = self.hero.alive
        self.hero._px = self.hero.x
        for m in self.combat.monsters:
            m._px = m.x
        if was_alive:
            self.spawner.tick(TICK_DT, self.combat.monsters, self.hero.x, self.view_w)
        self.combat.tick(TICK_DT)
        if was_alive and (not self.hero.alive or self.hero.hp <= 0):
            self._on_hero_death(events)
        if self.hero.alive:
            tick_skills_v2(self.hero, self.combat.monsters, events, TICK_DT, self.rng)
            for m in self.combat.monsters:
                if not m.alive and not getattr(m, "_rewarded", False):
                    m._rewarded = True
                    self._on_kill(m, events)
        else:
            self.death_timer -= TICK_DT
            if self.death_timer <= 0:
                self._respawn()
        if (self.spawner.boss_spawned and not self.spawner.boss_killed
                and not any(m.is_boss for m in self.combat.monsters)):
            self.spawner.boss_despawned()
        if self.spawner.notice:
            self.strip.flash_notify(self.spawner.notice)
            self.spawner.notice = None
        self.flair.add_events(events)
        if self.stats:
            self.stats.feed(events, TICK_DT)
        events.clear()

    def _make_spawner(self) -> world.Spawner:
        if self.in_rift:
            # 6.6: rift zones force their own mods + a steeper kills_to_boss
            # (60+10*tier) via the spawner override; no boss_killed persistence
            # (each tier is a fresh instance).
            mods = rifts.rift_mods(self.rift.tier, self.rng)
            return world.Spawner(
                self.zone, self.difficulty.monster_mult, self.rng, mod_ids=mods,
                kills_to_boss_override=rifts.rift_kills_to_boss(self.rift.tier))
        mods = self._zone_mods_for(self.zone)
        sp = world.Spawner(self.zone, self.difficulty.monster_mult, self.rng,
                           mod_ids=mods, mlvl_offset=self.difficulty.mlvl_offset)
        key = f"{self.zone.id}@{self.difficulty.id}"
        if key in self.meta.get("boss_killed_zones", []):
            sp.boss_killed = True
        return sp

    def _zone_mods_for(self, zone) -> list[str]:
        """6.5: resolve this zone's auto-mods — reuse the persisted roll if present,
        otherwise roll fresh (gated by hero level / act) and persist it."""
        store = self.meta.setdefault("zone_mods", {})
        if zone.id in store:
            return list(store[zone.id])
        if not zone_mods.is_active(self.hero.level, zone.act):
            store[zone.id] = []
            return []
        mods = zone_mods.roll_mods(zone.act, self.difficulty.id, self.rng)
        store[zone.id] = mods
        return mods

    def _on_kill(self, m, events: list[CombatEvent]) -> None:
        self.total_kills += 1
        self._rate_accum["kills"] += 1
        self.spawner.notify_kill(m)
        s = self.hero.stats
        # 6.5: zone-local reward riders (xp/drop_qty/gold ONLY — never global stats).
        rw = getattr(self.spawner, "reward_mults", None) or {}
        gold_gain = roll_gold(m, self.rng, gold_find=s.gold_find)
        gold_gain = int(gold_gain * rw.get("gold", 1.0))
        if self.in_rift:
            gold_gain = int(gold_gain * rifts.gold_mult(self.rift.tier))
        self.hero.gold += gold_gain
        self._rate_accum["gold"] += gold_gain
        mf = self.difficulty.loot_bonus + s.item_rarity
        iq = getattr(s, "item_quantity", 0.0)  # E.3: more drops (drop-chance mult)
        # gamblers_paradox (unique_drop_penalty): equipped unique halves the
        # UNIQUE rarity weight on monster (non-boss) drops — a gambler's curse.
        uw = None
        if "unique_drop_penalty" in self.hero.flags:
            uw = RARITY_WEIGHTS[Rarity.UNIQUE] * UNIQUE_DROP_MULT
        # 6.6: rift drops roll off a higher ilvl floor + boosted unique pity.
        rift_ilvl = rifts.RIFT_MIN_ILVL if self.in_rift else 0
        if m.is_boss:
            if self.in_rift:
                drops = roll_boss_drops(m, max(m.level, rift_ilvl), self.rng,
                                        magic_find=mf * rifts.UNIQUE_PITY_MULT)
                self._on_rift_boss_kill()
            else:
                drops = roll_boss_drops(m, m.level, self.rng, magic_find=mf)
                self.strip.flash_notify(f"{self.zone.name}: boss defeated!")
                killed = self.meta.setdefault("boss_killed_zones", [])
                zkey = f"{self.zone.id}@{self.difficulty.id}"
                if zkey not in killed:
                    killed.append(zkey)
                self._on_boss_first_kill(m)
            if self.stats:
                self.stats.note_boss_kill()
        else:
            item = roll_drop(m, m.level, self.rng, magic_find=mf, item_quantity=iq,
                             unique_weight=uw)
            drops = [item] if item else []
            # 6.5 drop_qty rider: juiced zones roll extra trash drops. The rider
            # (e.g. 1.12) becomes a 12% chance at one more roll (zone-local only).
            dq = rw.get("drop_qty", 1.0)
            if dq > 1.0 and self.rng.random() < (dq - 1.0):
                extra = roll_drop(m, m.level, self.rng, magic_find=mf, item_quantity=iq,
                                  unique_weight=uw)
                if extra:
                    drops.append(extra)
        for item in drops:
            if len(self.hero.inventory) < INV_CAP:
                self.hero.inventory.append(item)
                events.append(CombatEvent(
                    "loot", x=m.x, text=f"{item.display_name()}|{RARITY_COLORS[item.rarity]}"))
            else:
                self._overflow_item(item, m.x, events)
        self._update_inv_alert()
        prev_level = self.hero.level
        mob_xp = int(m.xp_reward * self.difficulty.xp_mult)
        # 6.1.2: farming zones far below your level decays XP toward the floor.
        # Uses the EFFECTIVE monster level (zone + difficulty offset) so a higher
        # loop keeps the hero inside the grace band instead of decaying off the
        # raw campaign level — this is what makes the loops the way forward.
        eff_mlvl = self.zone.monster_level + self.difficulty.mlvl_offset
        mob_xp = int(mob_xp * progression.zone_xp_mult(self.hero.level, eff_mlvl))
        # 6.5: zone-local xp rider (juiced zones pay more).
        mob_xp = int(mob_xp * rw.get("xp", 1.0))
        mob_xp = max(1, mob_xp)
        self._rate_accum["xp"] += mob_xp
        grant_skill_xp(self.hero, mob_xp)  # Skills V2: ranks level from kills
        self._roll_tome(m, events)  # S.5: chance to drop+read a Skill Tome
        leveled = progression.grant_xp(self.hero, mob_xp, events)
        if leveled:
            classes.apply_level_growth(self.hero)
            ensure_skills_v2(self.hero)  # unlock/open newly reached skills+slots
            self._flash_zone_unlocks(prev_level)
        if self.inv_panel.isVisible():
            self.inv_panel.refresh()
        if self.char_panel.isVisible():
            self.char_panel.refresh()
        # Idle auto-advance: check AFTER xp/level so a boss kill that also levels
        # us can immediately unlock and roll into the next zone/loop.
        self._maybe_auto_advance()

    def _roll_tome(self, m, events: list[CombatEvent]) -> None:
        """S.5 Skill Tome drop: each kill has an act-scaled, pity-safe chance to
        drop a tome, which is read immediately (tomes are logic-only, never an
        inventory Item). Reading unlocks a still-locked class skill, or converts
        to skill XP if nothing is left to unlock. `tome_pity` counts mobs since
        the last tome and guarantees one before it grows unbounded."""
        act = self.zone.act
        if not tomes.roll_tome_drop(self.hero, act, self.rng, pity=self.tome_pity):
            self.tome_pity += 1
            return
        self.tome_pity = 0
        res = tomes.read_tome(self.hero, act, self.rng)
        # Unlocking a brand-new skill is a real milestone -> keep the banner flash.
        # A duplicate tome (just skill XP) is minor and frequent-ish -> show it as
        # a small floating loot-style text over the mob instead of a screen banner
        # (user feedback: the big centered flash over-triggered for tomes).
        if res["kind"] == "unlock":
            self.strip.flash_notify(f"New skill unlocked: {res['name']}!")
        else:
            events.append(CombatEvent(
                "loot", x=m.x, text=f"Skill Tome +{res['amount']} sxp|#8a70d0"))
        if self.skills_panel and self.skills_panel.isVisible():
            self.skills_panel.refresh()

    # ------------------------------------------------------------------ rifts
    def _enter_rift(self) -> None:
        """6.6: enter (or resume) the endless rift at the current tier. Builds a
        fresh rift Zone from the Act 4 pool and swaps the spawner over to it."""
        if not rifts.is_unlocked(self.meta.get("boss_first_kills")):
            self.strip.flash_notify("Rifts unlock after Lord of Ash falls.")
            return
        cost = rifts.rift_entry_cost(self.rift.tier)
        if self.hero.gold < cost:
            self.strip.flash_notify(
                f"Rift Tier {self.rift.tier} entry costs {cost:,}g — not enough gold.")
            return
        self.hero.gold -= cost
        self.in_rift = True
        self.rift.deaths = 0
        self.zone = rifts.make_rift_zone(self.rift.tier)
        self.combat.monsters.clear()
        self.spawner = self._make_spawner()
        self.hero.x = 40.0
        self.hero.alive = True
        self.hero.hp = self.hero.max_hp
        self.hero.anim = "walk"
        self.strip.flash_notify(
            f"Rift Tier {self.rift.tier} — the Abyss deepens. (-{cost:,}g)")
        self.save()

    def _on_rift_boss_kill(self) -> None:
        """Rift boss down: advance a tier and rebuild the (harder) instance."""
        new_tier = self.rift.on_boss_kill()
        self.strip.flash_notify(f"Rift cleared! Descending to Tier {new_tier}.")
        self.zone = rifts.make_rift_zone(new_tier)
        self.combat.monsters.clear()
        self.spawner = self._make_spawner()
        self.hero.x = 40.0
        self.save()

    def _overflow_item(self, item, x: float, events: list[CombatEvent]) -> None:
        """Inventory full: rare/unique are never silently lost — they go to the stash."""
        if item.rarity in (Rarity.RARE, Rarity.UNIQUE):
            self.hero.stash.append(item)
            events.append(CombatEvent(
                "loot", x=x, text=f"{item.display_name()} → stash|{RARITY_COLORS[item.rarity]}"))
            if self.stash_panel.isVisible():
                self.stash_panel.refresh()
        else:
            gold = sell_price(item)
            self.hero.gold += gold
            events.append(CombatEvent(
                "loot", x=x, text=f"+{gold} gold (auto-sold: {item.display_name()})|#c8a44a"))

    def _update_inv_alert(self) -> None:
        if hasattr(self.strip, "set_button_alert"):
            self.strip.set_button_alert("inventory", len(self.hero.inventory) >= INV_CAP)

    def _flash_zone_unlocks(self, prev_level: int) -> None:
        """After a level-up, announce zones/difficulties that just became reachable."""
        now = self.hero.level
        for z in world.ZONES:
            if progression.zone_unlocked(now, z.monster_level) \
                    and not progression.zone_unlocked(prev_level, z.monster_level):
                self.strip.flash_notify(f"Zone unlocked: {z.name}")
        for d in progression.DIFFICULTIES:
            if prev_level < d.unlock_hero_level <= now:
                hint = progression.unlock_hint(d.id)
                tail = f" — {hint}" if hint else ""
                self.strip.flash_notify(f"{d.name} difficulty reached{tail}")

    def _on_boss_first_kill(self, m) -> None:
        """+3 passive points for the FIRST kill of an act boss per difficulty (tree rules)."""
        if not m.monster_id:
            return
        key = f"{m.monster_id}@{self.difficulty.id}"
        done = self.meta.setdefault("boss_first_kills", [])
        if key in done:
            return
        done.append(key)
        self.hero.bonus_points += 3
        self.strip.flash_notify("First kill! +3 passive points")
        # S.4 rework: act bosses also grant Class Points (once per boss ever,
        # PoE-lab style) for the class sub-trees. Dedup lives in grant_class_point.
        if tree:
            cp = tree.grant_class_point(self.hero, m.monster_id)
            if cp:
                self.strip.flash_notify(f"+{cp} Class Point{'s' if cp != 1 else ''}!")
                if self.tree_panel:
                    self.tree_panel.refresh()
        if m.monster_id == progression.FINAL_ACT_BOSS_ID:
            idx = next((i for i, d in enumerate(progression.DIFFICULTIES)
                        if d.id == self.difficulty.id), None)
            if idx is not None and idx + 1 < len(progression.DIFFICULTIES):
                nxt = progression.DIFFICULTIES[idx + 1]
                if progression.difficulty_unlocked(
                        nxt.id, done, self.hero.level):
                    self.strip.flash_notify(f"{nxt.name} difficulty unlocked!")

    def _on_hero_death(self, events: list[CombatEvent]) -> None:
        self.hero.alive = False
        self.hero.hp = 0
        self.hero.anim = "dead"
        self.hero.anim_t = 0.0
        self.death_timer = RESPAWN_SEC
        if self.stats:
            self.stats.note_death()
        self.strip.flash_notify("You have died...")
        # 6.6: dying in a rift builds toward a tier demotion (3 deaths -> tier-1).
        if self.in_rift:
            before = self.rift.tier
            after = self.rift.on_death()
            if after < before:
                self.strip.flash_notify(f"The rift rejects you — down to Tier {after}.")
                # rebuild the instance at the lower tier on the next respawn
                self.zone = rifts.make_rift_zone(after)

    def _respawn(self) -> None:
        boss = next((m for m in self.combat.monsters if m.is_boss and m.alive), None)
        self.combat.monsters.clear()
        if boss is not None:
            boss.hp = boss.max_hp
            boss.x = 40.0 + self.view_w
            boss._px = boss.x
            self.combat.monsters.append(boss)
        self.hero.alive = True
        self.hero.hp = self.hero.max_hp
        self.hero.anim = "walk"
        self.hero.anim_t = 0.0
        self.hero.x = 40.0

    # ------------------------------------------------------------------ ui
    def _paint(self, p, w: int, h: int) -> None:
        self.view_w = w
        alpha = max(0.0, min(1.0, self.acc / TICK_DT))
        for e in (self.hero, *self.combat.monsters):
            # Dead monsters must not slide: a corpse that died mid-tick still has
            # x one step ahead of _px, and interpolating it would drag the
            # fading sprite toward the hero. Snap corpses to their own position.
            if isinstance(e, Monster) and not e.alive:
                e._dx = e.x
                continue
            px = getattr(e, "_px", e.x)
            e._dx = px + (e.x - px) * alpha
        camera_x = self.hero._dx - 140.0
        self.renderer.paint(p, w, h, self.hero, self.combat.monsters,
                            self.flair, self.zone.bg_theme, camera_x,
                            zone_name=self.zone.name,
                            kills=self.spawner.kills,
                            kills_to_boss=self.spawner.kills_to_boss,
                            boss_spawned=self.spawner.boss_spawned,
                            boss_killed=self.spawner.boss_killed,
                            has_boss=bool(self.zone.boss_template_id))

    def _click(self, x: int, y: int, button: str) -> None:
        pass

    def _button(self, name: str) -> None:
        if name == "hide":
            self.strip.hide()
        elif name == "quit":
            self.cube_panel.return_items()
            self.save()
            QApplication.quit()
        else:
            self.panels.toggle(name)

    def _update_chevron(self) -> None:
        self.strip.set_panel_chevron(bool(self.panels.open_names()))

    # ---------------------------------------------- collapsible panel (V2 p.3)
    def _toggle_collapse(self) -> None:
        """F1: hide all open panels (remembering them) or restore the set."""
        open_now = self.panels.open_names()
        if open_now:
            self._collapsed = open_now
            self.panels.close_all()
        else:
            for n in self._collapsed or ["character"]:
                if not self.panels.is_open(n):
                    self.panels.toggle(n)

    def _place(self, panel) -> None:
        g = self.strip.geometry()
        panel.adjustSize()
        y = max(0, g.y() - panel.height() - 8)
        right = g.x() + g.width() - 10
        # Cascade: park each already-open panel to the left so a paired
        # panel (vendor/stash beside inventory) stays fully visible.
        others = [p for p in self.panels.open_widgets()
                  if p is not panel and p.isVisible()]
        occupied = right
        for p in others:
            px = p.x()
            if px < occupied:
                occupied = px
        x = right - panel.width() if not others else occupied - panel.width() - 8
        panel.move(max(0, x), y)

    def _vendor_is_open(self) -> bool:
        """RMB-sell in the inventory is only allowed while the shop is open."""
        return bool(self.vendor_panel and self.vendor_panel.isVisible())

    def _sell_to_vendor(self, item) -> bool:
        """Inventory right-click routes through the vendor (buyback) while it's open."""
        if self.vendor_panel and self.vendor_panel.isVisible():
            return self.vendor_panel.sell_item(item)
        return False

    def _on_gear_change(self) -> None:
        self._update_inv_alert()
        if self.char_panel.isVisible():
            self.char_panel.refresh()
        if self.inv_panel.isVisible():
            self.inv_panel.refresh()
        if self.stash_panel.isVisible():
            self.stash_panel.refresh()

    def _on_toggle_auto(self, enabled: bool) -> None:
        self.auto_advance = bool(enabled)
        self.save()
        # Turning it back on should immediately resume advancing if the current
        # zone is already cleared.
        if self.auto_advance and self.hero.alive:
            self._maybe_auto_advance()

    def _on_zone_select(self, zone_id: str, diff_id: str) -> None:
        self.zones_panel.hide()
        # 6.6: the waypoint's rift row selects the sentinel id — enter the rift
        # instead of a normal zone (tier/difficulty come from RiftState).
        if zone_id == rifts.RIFT_ZONE_ID:
            self._enter_rift()
            return
        self.difficulty = next(
            (d for d in progression.DIFFICULTIES if d.id == diff_id), self.difficulty)
        self._switch_zone(world.get_zone(zone_id), announce=True)
        self.save()

    def _switch_zone(self, zone, announce: bool = False) -> None:
        """Move the hero into `zone` under the current difficulty: fresh spawner,
        reset position/HP. Shared by manual waypoint picks and auto-advance."""
        self.in_rift = False  # leaving the rift back to the overworld
        self.zone = zone
        self.combat.monsters.clear()
        self.spawner = self._make_spawner()
        self.hero.x = 40.0
        self.hero.alive = True
        self.hero.hp = self.hero.max_hp
        self.hero.anim = "walk"
        if announce:
            self.strip.flash_notify(f"{self.zone.name} · {self.difficulty.name}")

    def _maybe_auto_advance(self) -> None:
        """Idle progression: once the current zone is cleared, walk to the next
        one on its own. Off when the player unticks auto-advance (farming a zone),
        or inside a rift (rifts advance by tier, not by campaign order)."""
        if not self.auto_advance or self.in_rift:
            return
        # Hold boss zones until the boss is actually down.
        if self.zone.boss_template_id and not self.spawner.boss_killed:
            return
        nxt = world.next_campaign_zone(self.zone)
        if nxt is not None:
            if not progression.zone_unlocked(self.hero.level, nxt.monster_level):
                return  # under-levelled: farm here until the next zone opens
            self._switch_zone(nxt, announce=True)
            self.save()
            return
        # No next campaign zone -> we just cleared the Act 3 finale (lord_of_ash).
        # If the next difficulty is open, roll the loop over into its Act 1.
        self._maybe_start_next_loop()

    def _maybe_start_next_loop(self) -> None:
        done = self.meta.get("boss_first_kills", [])
        idx = next((i for i, d in enumerate(progression.DIFFICULTIES)
                    if d.id == self.difficulty.id), None)
        if idx is None or idx + 1 >= len(progression.DIFFICULTIES):
            return  # already on the hardest loop — stay (farm / manual Act 4)
        nxt_diff = progression.DIFFICULTIES[idx + 1]
        if not progression.difficulty_unlocked(nxt_diff.id, done, self.hero.level):
            return  # gate not met (level) — stay on this loop
        self.difficulty = nxt_diff
        self._switch_zone(world.first_campaign_zone(), announce=False)
        self.strip.flash_notify(
            f"{nxt_diff.name} loop — back to {self.zone.name}")
        self.save()

    # ------------------------------------------------------------------ save
    def save(self) -> None:
        self.meta.update(
            zone_id=self.zone.id, difficulty_id=self.difficulty.id,
            kills=self.total_kills, playtime=round(self.playtime, 1),
            vendor=vendor_to_dict(self.vendor),
            tree_version=getattr(tree, "TREE_VERSION", 1) if tree else 0,
            open_panels=self.panels.open_names() or self._collapsed,
            rate_snapshot=self.rate_snapshot,
            tome_pity=self.tome_pity,
            rift=self.rift.to_dict(),
            auto_advance=self.auto_advance,
        )
        if self.gamble_vendor:
            self.meta["gamble"] = self.gamble_vendor.to_dict()
        if self.stats:
            self.meta["stats"] = self.stats.to_dict()
        save_game(self.save_path, self.hero, self.meta)


def _apply_offline(game: Game, saved_at: float) -> None:
    res = offline_progress(saved_at, game.hero, zone_id=game.meta.get("zone_id"),
                           rate_snapshot=game.meta.get("rate_snapshot"))
    if res["hours"] < 0.02 or (res["gold"] <= 0 and res["xp"] <= 0):
        return
    game.hero.gold += res["gold"]
    events: list[CombatEvent] = []
    if progression.grant_xp(game.hero, res["xp"], events):
        classes.apply_level_growth(game.hero)
    # offline loot: top finds go to inventory; overflow follows the usual
    # rule (rare/unique -> stash, rest auto-sold), nothing is silently lost
    kept, stashed, sold_gold = 0, 0, 0
    for item in res.get("items", []):
        if len(game.hero.inventory) < INV_CAP:
            game.hero.inventory.append(item)
            kept += 1
        elif item.rarity in (Rarity.RARE, Rarity.UNIQUE):
            game.hero.stash.append(item)
            stashed += 1
        else:
            sold_gold += sell_price(item)
    if sold_gold:
        game.hero.gold += sold_gold
    game._update_inv_alert()
    parts = [f"+{res['gold']} gold", f"+{res['xp']} XP"]
    if res.get("levels_gained"):
        parts.append(f"+{res['levels_gained']} levels")
    if kept:
        parts.append(f"{kept} items")
    if stashed:
        parts.append(f"{stashed} → stash")
    game.strip.flash_notify(
        f"While you were away ({res['hours']:.1f}h): " + ", ".join(parts))


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    holder: dict[str, Game] = {}

    from ui.launcher import Launcher
    launcher = Launcher()

    def _begin(game: Game) -> None:
        holder["game"] = game
        launcher.close()

    def on_new(class_id: str, name: str) -> None:
        hero = classes.make_hero(class_id, name=name)
        ensure_skills_v2(hero)  # seed Skills V2 loadout for the fresh hero
        # C2: never clobber an existing hero's slot — pick a free path (_2, _3, …)
        game = Game(hero, {}, save_path=_free_slot_path(hero))
        game.save()
        _begin(game)

    def on_load(path: str) -> None:
        loaded = load_game(path)
        if not loaded or loaded[0].class_id not in classes.CLASSES:
            launcher.loadscr.refresh()  # stale/broken slot — just re-list
            return
        hero, meta = loaded
        game = Game(hero, meta, save_path=path)
        _begin(game)
        _apply_offline(game, meta["saved_at"])

    launcher.new_hero.connect(on_new)
    launcher.load_hero.connect(on_load)
    launcher.show()

    def _flush_and_save() -> None:
        g = holder.get("game")
        if g is None:
            return
        g.cube_panel.return_items()  # M1: flush cube survivors before hard-close save
        g.save()

    app.aboutToQuit.connect(_flush_and_save)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
