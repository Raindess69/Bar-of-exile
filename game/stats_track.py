"""Bar of Exile — combat statistics tracker. PyQt-free."""
from __future__ import annotations

from collections import deque

from game.core import RARITY_COLORS, CombatEvent, Rarity

DPS_WINDOW = 10.0  # seconds of rolling damage history for the DPS meter

_COLOR_TO_RARITY = {color: rarity for rarity, color in RARITY_COLORS.items()}


class StatsTracker:
    """Accumulates lifetime combat statistics from the per-step CombatEvent stream.

    feed(events, dt) must be called every fixed step BEFORE events.clear().
    Limitations of the event stream (by design of game.combat / game.skills):
    - "damage"/"crit" events carry no source marker, so the DPS meter counts
      hero-dealt AND monster-dealt (on the hero) hits alike; it slightly
      overstates true hero DPS while the hero is being hit.
    - Hero death produces no event -> the owner calls note_death().
    - "kill" events don't mark bosses -> the owner calls note_boss_kill()
      (in addition to the "kill" event, which already counts in kills).
    - Gold gains produce no event and are not tracked here.
    """

    def __init__(self):
        # lifetime totals (serialized via to_dict/from_dict)
        self.total_damage = 0.0
        self.kills = 0
        self.boss_kills = 0
        self.deaths = 0
        self.playtime = 0.0  # seconds
        self.loot: dict[Rarity, int] = {r: 0 for r in Rarity}
        # rolling DPS state (session-only, NOT serialized)
        self._t = 0.0
        self._window: deque[tuple[float, float]] = deque()  # (t, damage)

    # ------------------------------------------------------------------ feed
    def feed(self, events: list[CombatEvent], dt: float) -> None:
        self._t += dt
        self.playtime += dt
        step_dmg = 0.0
        for e in events:
            if e.kind in ("damage", "crit"):
                step_dmg += e.value
            elif e.kind == "kill":
                self.kills += 1
            elif e.kind == "loot":
                # text format: "Item Name|#rrggbb" (see main.py loot events)
                _, sep, color = e.text.rpartition("|")
                rarity = _COLOR_TO_RARITY.get(color) if sep else None
                if rarity is not None:
                    self.loot[rarity] += 1
        if step_dmg > 0:
            self.total_damage += step_dmg
            self._window.append((self._t, step_dmg))
        cutoff = self._t - DPS_WINDOW
        while self._window and self._window[0][0] <= cutoff:
            self._window.popleft()

    def note_death(self) -> None:
        """Hero death has no CombatEvent — the game loop calls this explicitly."""
        self.deaths += 1

    def note_boss_kill(self) -> None:
        """Kill events don't mark bosses — the game loop calls this explicitly."""
        self.boss_kills += 1

    def dps(self) -> float:
        """Rolling damage per second over the last DPS_WINDOW seconds."""
        span = min(self._t, DPS_WINDOW)
        if span <= 0 or not self._window:
            return 0.0
        return sum(d for _, d in self._window) / max(span, 1.0)

    # ------------------------------------------------------------------ save
    def to_dict(self) -> dict:
        """Lifetime totals for the save meta. Rolling DPS state is session-only."""
        return {
            "total_damage": round(self.total_damage, 1),
            "kills": self.kills,
            "boss_kills": self.boss_kills,
            "deaths": self.deaths,
            "playtime": round(self.playtime, 1),
            "loot": {r.value: n for r, n in self.loot.items() if n},
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "StatsTracker":
        t = cls()
        data = data or {}
        t.total_damage = float(data.get("total_damage", 0.0))
        t.kills = int(data.get("kills", 0))
        t.boss_kills = int(data.get("boss_kills", 0))
        t.deaths = int(data.get("deaths", 0))
        t.playtime = float(data.get("playtime", 0.0))
        for key, n in (data.get("loot") or {}).items():
            try:
                t.loot[Rarity(key)] = int(n)
            except ValueError:
                pass  # unknown rarity in an old/edited save — skip
        return t


if __name__ == "__main__":
    from game.core import DamageType

    t = StatsTracker()
    # 1 second of combat: 20 steps, one 10-damage hit per step
    for _ in range(20):
        t.feed([CombatEvent("damage", x=100, value=10, dtype=DamageType.PHYS)], 0.05)
    assert abs(t.total_damage - 200) < 1e-9, t.total_damage
    assert abs(t.dps() - 200) < 1e-9, t.dps()  # 200 dmg over 1s span (min-1s floor)

    # crits count into DPS; kills / loot / heal / levelup routed correctly
    t.feed([
        CombatEvent("crit", x=100, value=50, dtype=DamageType.FIRE),
        CombatEvent("kill", x=100),
        CombatEvent("kill", x=110, text="Zombie"),  # skills.py kill variant
        CombatEvent("loot", x=100, text="Viper Blade|#8888ff"),
        CombatEvent("loot", x=100, text="Odd|Name|#af6025"),  # '|' in the name
        CombatEvent("loot", x=100, text="no color here"),      # ignored
        CombatEvent("heal", x=50, value=30),
        CombatEvent("levelup", x=50, text="Level 7!"),
    ], 0.05)
    assert t.total_damage == 250 and t.kills == 2
    assert t.loot[Rarity.MAGIC] == 1 and t.loot[Rarity.UNIQUE] == 1
    assert t.loot[Rarity.NORMAL] == 0 and t.loot[Rarity.RARE] == 0

    # window expiry: 15 quiet seconds -> everything falls out of the 10s window
    for _ in range(300):
        t.feed([], 0.05)
    assert t.dps() == 0.0, t.dps()
    assert abs(t.playtime - 16.05) < 1e-6, t.playtime

    # explicit notes
    t.note_death()
    t.note_boss_kill()
    assert t.deaths == 1 and t.boss_kills == 1

    # save round-trip: lifetime totals survive, rolling state resets
    d = t.to_dict()
    t2 = StatsTracker.from_dict(d)
    assert t2.total_damage == d["total_damage"] and t2.kills == 2
    assert t2.boss_kills == 1 and t2.deaths == 1
    assert abs(t2.playtime - d["playtime"]) < 1e-9
    assert t2.loot[Rarity.MAGIC] == 1 and t2.loot[Rarity.UNIQUE] == 1
    assert t2.dps() == 0.0
    assert d["loot"] == {"magic": 1, "unique": 1}  # zero counts omitted
    assert StatsTracker.from_dict(None).kills == 0
    assert StatsTracker.from_dict({"loot": {"bogus": 3}}).loot[Rarity.NORMAL] == 0

    # DPS spans <1s don't explode (min-1s denominator floor)
    t3 = StatsTracker()
    t3.feed([CombatEvent("damage", x=0, value=100)], 0.05)
    assert t3.dps() == 100.0, t3.dps()

    print("stats_track OK: dmg=%.0f kills=%d dps=%.1f" % (t.total_damage, t.kills, t.dps()))
