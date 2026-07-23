"""Bar of Exile — statistics popup panel: rolling DPS, kills, deaths, loot by rarity."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from game.core import RARITY_COLORS, Rarity
from game.stats_track import DPS_WINDOW, StatsTracker
from ui.panels import PanelFrame

DPS_COLOR = "#d4c08a"
DIM = "#7a6f5a"
VAL = "#c8b898"
DEATH_COLOR = "#e04040"
BOSS_COLOR = "#af6025"


def _fmt_num(v: float) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 10_000:
        return f"{v / 1_000:.1f}K"
    return str(int(v))


def _fmt_time(secs: float) -> str:
    s = int(secs)
    h, m = s // 3600, (s % 3600) // 60
    if h:
        return f"{h}h {m:02d}m {s % 60:02d}s"
    return f"{m:02d}m {s % 60:02d}s"


def _row(name: str, val: str, color: str = VAL) -> str:
    return f'<div><span style="color:{DIM}">{name}:</span> <span style="color:{color}">{val}</span></div>'


class StatsPanel(PanelFrame):
    """Popup with lifetime combat statistics. refresh(tracker) redraws the values;
    while visible a 1s QTimer re-polls the last tracker (rolling DPS decays)."""

    def __init__(self, tracker: StatsTracker | None = None):
        super().__init__("Statistics")
        self.tracker = tracker

        lay = QVBoxLayout(self.content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.dps_lab = QLabel()
        self.dps_lab.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.dps_lab)

        cols = QHBoxLayout()
        cols.setSpacing(20)
        self.col1, self.col2 = QLabel(), QLabel()
        for c in (self.col1, self.col2):
            c.setTextFormat(Qt.TextFormat.RichText)
            c.setAlignment(Qt.AlignmentFlag.AlignTop)
            cols.addWidget(c)
        lay.addLayout(cols)

        self.loot_hdr = QLabel("Loot Found")
        self.loot_hdr.setObjectName("dim")
        lay.addWidget(self.loot_hdr)
        self.loot_lab = QLabel()
        self.loot_lab.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.loot_lab)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------- refresh
    def refresh(self, tracker: StatsTracker | None = None) -> None:
        if tracker is not None:
            self.tracker = tracker
        t = self.tracker
        if t is None:
            self.dps_lab.setText(_row("DPS", "—"))
            self.col1.setText("")
            self.col2.setText("")
            self.loot_lab.setText(f'<div style="color:{DIM}">No data</div>')
            self.adjustSize()
            return

        self.dps_lab.setText(
            f'<div><span style="color:{DIM}">DPS (last {DPS_WINDOW:.0f}s):</span> '
            f'<span style="color:{DPS_COLOR}; font-weight:bold; font-size:16px">{_fmt_num(t.dps())}</span></div>'
        )
        hours = t.playtime / 3600
        self.col1.setText("".join([
            _row("Kills", _fmt_num(t.kills)),
            _row("Boss Kills", _fmt_num(t.boss_kills), BOSS_COLOR),
            _row("Deaths", _fmt_num(t.deaths), DEATH_COLOR if t.deaths else VAL),
        ]))
        self.col2.setText("".join([
            _row("Total Damage", _fmt_num(t.total_damage)),
            _row("Playtime", _fmt_time(t.playtime)),
            _row("Kills / hour", _fmt_num(t.kills / hours) if hours > 0 else "—"),
        ]))
        self.loot_lab.setText("".join(
            _row(r.value.title(), _fmt_num(n), RARITY_COLORS[r])
            for r, n in t.loot.items()
        ))
        self.adjustSize()

    def showEvent(self, e):
        self.refresh()
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from game.core import CombatEvent, DamageType

    app = QApplication(sys.argv)

    t = StatsTracker()
    for _ in range(40):  # 2s of combat, 25 dmg per step
        t.feed([CombatEvent("damage", x=100, value=25, dtype=DamageType.PHYS)], 0.05)
    t.feed([
        CombatEvent("crit", x=100, value=500, dtype=DamageType.FIRE),
        CombatEvent("kill", x=100),
        CombatEvent("kill", x=110, text="Zombie"),
        CombatEvent("loot", x=100, text="Coral Ring|#c8c8c8"),
        CombatEvent("loot", x=100, text="Viper Blade|#8888ff"),
        CombatEvent("loot", x=100, text="Dread Bane|#ffff77"),
        CombatEvent("loot", x=100, text="Sar-Hazan's Grip|#af6025"),
    ], 0.05)
    t.note_boss_kill()
    t.note_death()

    panel = StatsPanel()
    panel.show()
    assert "No data" in panel.loot_lab.text()  # trackerless panel degrades gracefully

    panel.refresh(t)
    assert panel.tracker is t
    assert f"{DPS_WINDOW:.0f}s" in panel.dps_lab.text()
    assert _fmt_num(t.dps()) in panel.dps_lab.text()
    assert "Kills" in panel.col1.text() and "2" in panel.col1.text()
    assert "Boss Kills" in panel.col1.text() and "Deaths" in panel.col1.text()
    assert "Total Damage" in panel.col2.text() and "Playtime" in panel.col2.text()
    for r in Rarity:  # all four rarities listed with their colors
        assert r.value.title() in panel.loot_lab.text()
        assert RARITY_COLORS[r] in panel.loot_lab.text()

    # refresh() without an argument re-polls the stored tracker
    for _ in range(300):  # 15 quiet seconds -> rolling window empties
        t.feed([], 0.05)
    panel.refresh()
    assert _fmt_num(0) in panel.dps_lab.text()

    # timer runs only while visible
    assert panel._timer.isActive()
    panel.hide()
    assert not panel._timer.isActive()

    # formatting helpers
    assert _fmt_num(999) == "999" and _fmt_num(25_500) == "25.5K"
    assert _fmt_num(2_400_000) == "2.40M"
    assert _fmt_time(59) == "00m 59s" and _fmt_time(3725) == "1h 02m 05s"

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stats_test.png")
    panel.grab().save(path)
    print("OK:", path)
