"""Bar of Exile — zone and difficulty picker panel (PoE-style waypoint)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

from ui.panels import PanelFrame


@dataclass
class _StubZone:
    id: str
    name: str
    monster_level: int


@dataclass
class _StubDiff:
    id: str
    name: str
    unlock_hero_level: int


_STUB_ZONES = [
    _StubZone("stub_shore", "Shore (stub)", 1),
    _StubZone("stub_forest", "Forest (stub)", 5),
]
_STUB_DIFFS = [_StubDiff("normal", "Normal", 1)]


def _load_data():
    try:
        from game.progression import (DIFFICULTIES, available_difficulties,
                                      difficulty_unlocked, unlock_hint,
                                      zone_unlocked)
        from game.world import ZONES
        return (ZONES, DIFFICULTIES, available_difficulties, zone_unlocked,
                difficulty_unlocked, unlock_hint)
    except ImportError:
        def _avail(hero_level: int):
            return [d for d in _STUB_DIFFS if hero_level >= d.unlock_hero_level]

        def _unlocked(hero_level: int, zone_monster_level: int) -> bool:
            return hero_level >= zone_monster_level - 2

        def _diff_unlocked(diff_id: str, boss_first_kills: list[str],
                           hero_level: int) -> bool:
            d = next((x for x in _STUB_DIFFS if x.id == diff_id), None)
            return d is not None and hero_level >= d.unlock_hero_level

        def _hint(diff_id: str) -> str:
            return ""

        return _STUB_ZONES, _STUB_DIFFS, _avail, _unlocked, _diff_unlocked, _hint


# --- world map art (assets/ui/map/index.json: world + per-theme thumbs) -----
MAP_DIR = Path(__file__).resolve().parent.parent / "assets" / "ui" / "map"
THUMB_W, THUMB_H = 56, 34
WORLD_MAX_H = 120

_map_index: dict | None = None
_thumb_pixmaps: dict[str, QPixmap | None] = {}  # filename -> scaled pixmap (lazy)


def _load_map_index() -> dict:
    global _map_index
    if _map_index is None:
        try:
            _map_index = json.loads((MAP_DIR / "index.json").read_text())
        except (OSError, ValueError):
            _map_index = {}
    return _map_index


def _thumb_pixmap(zone) -> QPixmap | None:
    """Zone thumb by id first, else by bg_theme. Lazy cache; None if missing."""
    idx = _load_map_index()
    rel = (idx.get("zones", {}).get(zone.id)
           or idx.get("themes", {}).get(getattr(zone, "bg_theme", "")))
    if not rel:
        return None
    if rel not in _thumb_pixmaps:
        pm = None
        path = MAP_DIR / rel
        if path.exists():
            raw = QPixmap(str(path))
            if not raw.isNull():
                pm = raw.scaled(THUMB_W, THUMB_H,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        _thumb_pixmaps[rel] = pm
    return _thumb_pixmaps[rel]


def _world_pixmap(width: int) -> QPixmap | None:
    rel = _load_map_index().get("world")
    if not rel or not (MAP_DIR / rel).exists():
        return None
    raw = QPixmap(str(MAP_DIR / rel))
    if raw.isNull():
        return None
    return raw.scaled(width, WORLD_MAX_H,
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


_QSS = """
QWidget#zonesPanel {
    background-color: #1a1512;
    border: 1px solid #6a5a3a;
}
QLabel {
    color: #c8b88a;
    font-family: Consolas, "Courier New", monospace;
    font-size: 11px;
    background: transparent;
    border: none;
}
QLabel#title {
    color: #d4c08a;
    font-size: 12px;
    font-weight: bold;
}
QFrame#sep {
    background-color: #3a3226;
    border: none;
    max-height: 1px;
    min-height: 1px;
}
QPushButton {
    background: transparent;
    border: 1px solid transparent;
    color: #b0a080;
    font-family: Consolas, "Courier New", monospace;
    font-size: 11px;
    padding: 3px 8px;
    text-align: left;
}
QPushButton:hover:enabled { background: #2a2318; border-color: #6a5a3a; }
QPushButton[kind="tab"] { text-align: center; padding: 3px 10px; }
QPushButton[state="locked"] { color: #5a5348; }
QPushButton[state="selected"] {
    color: #ffd76a; border-color: #6a5a3a; background: #262015;
}
QPushButton[state="current"] {
    color: #ffcc44; border-color: #8a7a4a; background: #262015; font-weight: bold;
}
"""


class ZonesPanel(PanelFrame):
    def __init__(self, on_select: Callable[[str, str], None],
                 on_toggle_auto: Callable[[bool], None] | None = None):
        super().__init__("· WAYPOINTS ·")
        self.on_select = on_select
        self.on_toggle_auto = on_toggle_auto
        self._hero_level = 1
        self._current_zone = ""
        self._selected_diff = ""
        self._auto_advance = True
        self._boss_first_kills: list[str] = []
        self._rift_state = None
        self._data = None

        # Apply zone-specific styling to content only
        self.content.setObjectName("zonesPanel")
        self.content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.content.setStyleSheet(_QSS)
        self.setMinimumWidth(380)

        root = QVBoxLayout(self.content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        world = _world_pixmap(self.minimumWidth() - 22)  # minus root margins
        if world is not None:
            map_lab = QLabel()
            map_lab.setPixmap(world)
            map_lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(map_lab)

        self._tabs_row = QHBoxLayout()
        self._tabs_row.setSpacing(4)
        root.addLayout(self._tabs_row)

        sep = QFrame()
        sep.setObjectName("sep")
        root.addWidget(sep)

        self._zones_col = QVBoxLayout()
        self._zones_col.setSpacing(2)
        root.addLayout(self._zones_col)
        root.addStretch(1)

    def refresh(self, hero_level: int, current_zone: str, current_diff: str,
                boss_first_kills: list[str] | None = None,
                rift_state=None, auto_advance: bool | None = None) -> None:
        self._hero_level = hero_level
        self._current_zone = current_zone
        self._boss_first_kills = list(boss_first_kills) if boss_first_kills else []
        self._rift_state = rift_state
        if auto_advance is not None:
            self._auto_advance = bool(auto_advance)
        self._data = _load_data()
        zones, diffs, _avail_fn, _zone_fn, diff_unlocked_fn, _hint_fn = self._data
        unlocked_ids = [d.id for d in diffs
                        if diff_unlocked_fn(d.id, self._boss_first_kills, hero_level)]
        if current_diff in unlocked_ids:
            self._selected_diff = current_diff
        elif self._selected_diff not in unlocked_ids:
            self._selected_diff = unlocked_ids[0] if unlocked_ids else (diffs[0].id if diffs else "")
        self._rebuild()

    def _rebuild(self) -> None:
        zones, diffs, _avail_fn, zone_unlocked_fn, diff_unlocked_fn, hint_fn = self._data
        _clear_layout(self._tabs_row)
        _clear_layout(self._zones_col)

        for d in diffs:
            btn = QPushButton()
            btn.setProperty("kind", "tab")
            btn.setText(d.name)
            if diff_unlocked_fn(d.id, self._boss_first_kills, self._hero_level):
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setProperty("state",
                                "selected" if d.id == self._selected_diff else "normal")
                btn.clicked.connect(partial(self._pick_diff, d.id))
            else:
                btn.setProperty("state", "locked")
                btn.setEnabled(False)
                hint = hint_fn(d.id)
                if self._hero_level < d.unlock_hero_level:
                    req = f"Requires level {d.unlock_hero_level}"
                    hint = f"{hint} ({req})" if hint else req
                btn.setToolTip(hint)
            self._tabs_row.addWidget(btn)
        self._tabs_row.addStretch(1)

        # Idle auto-advance toggle: when on, the game walks to the next zone (and
        # rolls into the next difficulty loop) on its own; untick to farm here.
        auto_btn = QPushButton()
        auto_btn.setProperty("kind", "autotoggle")
        auto_btn.setCheckable(True)
        auto_btn.setChecked(self._auto_advance)
        auto_btn.setText("☑ Auto" if self._auto_advance else "☐ Farm here")
        auto_btn.setProperty("state", "selected" if self._auto_advance else "normal")
        auto_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        auto_btn.setToolTip("On: auto-advance zones and loop into the next "
                            "difficulty.\nOff: stay and farm the current zone.")
        auto_btn.clicked.connect(self._toggle_auto)
        self._tabs_row.addWidget(auto_btn)

        for z in zones:
            unlocked = zone_unlocked_fn(self._hero_level, z.monster_level)
            btn = QPushButton()
            btn.setProperty("kind", "zone")
            pm = _thumb_pixmap(z)
            if pm is not None:
                btn.setIcon(QIcon(pm))
                btn.setIconSize(QSize(THUMB_W, THUMB_H))
            if unlocked:
                btn.setText(f"{z.name:<24} monster lvl {z.monster_level:>2}")
                is_cur = z.id == self._current_zone
                btn.setProperty("state", "current" if is_cur else "normal")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(partial(self._pick_zone, z.id))
            else:
                btn.setText(f"\U0001F512 {z.name:<22} Requires level {z.monster_level - 2}")
                btn.setProperty("state", "locked")
                btn.setEnabled(False)
            self._zones_col.addWidget(btn)

        self._add_rift_row()
        self.adjustSize()

    def _add_rift_row(self) -> None:
        """6.6: endgame rift entry. Shown once Lord of Ash is dead on any
        difficulty; emits the sentinel rift id so main enters the rift instead of
        a normal zone. Hidden entirely while still locked (avoids spoiling it)."""
        try:
            from game import rifts
        except ImportError:
            return
        if not rifts.is_unlocked(self._boss_first_kills):
            return
        tier = 1
        rs = self._rift_state
        if rs is not None:
            tier = getattr(rs, "tier", 1)
        sep = QFrame()
        sep.setObjectName("sep")
        self._zones_col.addWidget(sep)
        btn = QPushButton()
        btn.setProperty("kind", "zone")
        btn.setProperty("state", "current" if self._current_zone.startswith("rift_") else "normal")
        cost = rifts.rift_entry_cost(tier)
        btn.setText(f"⨂ Enter Rift — Tier {tier:<3} endless endgame  ({cost:,}g)")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self.on_select(rifts.RIFT_ZONE_ID, self._selected_diff))
        self._zones_col.addWidget(btn)

    def _pick_diff(self, diff_id: str) -> None:
        self._selected_diff = diff_id
        self._rebuild()

    def _toggle_auto(self) -> None:
        self._auto_advance = not self._auto_advance
        if self.on_toggle_auto is not None:
            self.on_toggle_auto(self._auto_advance)
        self._rebuild()

    def _pick_zone(self, zone_id: str) -> None:
        self.on_select(zone_id, self._selected_diff)


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    picked: list[tuple[str, str]] = []
    panel = ZonesPanel(on_select=lambda z, d: (picked.append((z, d)), print("select:", z, d)))
    panel.refresh(hero_level=10, current_zone="a1_forest", current_diff="normal")
    panel.show()

    zone_btns = [panel._zones_col.itemAt(i).widget()
                 for i in range(panel._zones_col.count())]
    assert zone_btns, "no zones"
    enabled = [b for b in zone_btns if b.isEnabled()]
    locked = [b for b in zone_btns if not b.isEnabled()]
    print(f"zones: {len(zone_btns)}, unlocked: {len(enabled)}, locked: {len(locked)}")
    assert enabled, "all zones locked at level 10"
    enabled[0].click()
    assert picked and picked[0][1] == "normal", picked

    with_thumb = [b for b in zone_btns if not b.icon().isNull()]
    print(f"thumbnails: {len(with_thumb)}/{len(zone_btns)}")
    if (MAP_DIR / "index.json").exists():
        assert with_thumb, "index.json exists but no zone row got a thumbnail"

    def _tab_btns():
        return [panel._tabs_row.itemAt(i).widget()
                for i in range(panel._tabs_row.count())
                if panel._tabs_row.itemAt(i).widget() is not None
                and panel._tabs_row.itemAt(i).widget().property("kind") == "tab"]

    # difficulty gate: level 99 but no boss kills -> only first tab enabled
    panel.refresh(hero_level=99, current_zone="a1_forest", current_diff="normal")
    tabs = _tab_btns()
    assert tabs, "no difficulty tabs"
    enabled_tabs = [b for b in tabs if b.isEnabled()]
    locked_tabs = [b for b in tabs if not b.isEnabled()]
    print(f"diffs (no kills): {len(tabs)}, unlocked: {len(enabled_tabs)}, locked: {len(locked_tabs)}")
    if len(tabs) > 1:
        assert len(enabled_tabs) == 1, "boss gate ignored: extra difficulties unlocked"
        assert all(b.toolTip() for b in locked_tabs), "locked tab without unlock hint tooltip"

    # boss kill on Normal + level 25 -> second tier unlocks
    panel.refresh(hero_level=25, current_zone="a1_forest", current_diff="cruel",
                  boss_first_kills=["lord_of_ash@normal"])
    tabs = _tab_btns()
    enabled_ids = [b.text() for b in tabs if b.isEnabled()]
    print(f"diffs (boss@normal, lvl 25): unlocked = {enabled_ids}")
    if len(tabs) > 1:
        assert len(enabled_ids) == 2, enabled_ids
        assert panel._selected_diff == "cruel", panel._selected_diff

    # auto-advance toggle: callback fires, state flips, button relabels
    toggled: list[bool] = []
    panel.on_toggle_auto = lambda v: toggled.append(v)
    panel.refresh(hero_level=25, current_zone="a1_forest", current_diff="cruel",
                  boss_first_kills=["lord_of_ash@normal"], auto_advance=True)
    auto_btns = [panel._tabs_row.itemAt(i).widget()
                 for i in range(panel._tabs_row.count())
                 if panel._tabs_row.itemAt(i).widget() is not None
                 and panel._tabs_row.itemAt(i).widget().property("kind") == "autotoggle"]
    assert len(auto_btns) == 1, "auto-advance toggle missing"
    assert panel._auto_advance is True
    auto_btns[0].click()
    assert toggled == [False], toggled
    assert panel._auto_advance is False, "toggle did not flip state"
    print("auto-advance toggle OK")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_zones_test.png")
    panel.grab().save(out)
    print("render:", out)
    print("OK")
