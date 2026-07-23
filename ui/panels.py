"""Bar of Exile — popup panels: item tooltip, inventory, character sheet.

Also home of the shared panel plumbing (UX wave, spec §6):
  * PanelFrame — base for every closable panel: title bar with an X button,
    Esc to close, a status line for action feedback, and a height clamp so a
    panel never overlaps the game strip (content scrolls inside instead).
  * PanelManager — open/close coordinator: opening a panel closes the rest,
    except the vendor+inventory and stash+inventory pairs.
"""
from __future__ import annotations

import json
import logging
import zlib
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QPixmap, QIcon, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from game import skills_v2 as SV
from game.core import (
    DTYPE_COLORS, RARITY_COLORS, Affix, DamageType, Hero, Item, Rarity, Slot, StatMod, Stats,
    MOD_RELIC, MOD_PRIMAL,
)
from game.economy import item_value

CELL = 46
INV_COLS, INV_ROWS = 8, 4
AFFIX_COLOR = "#8888ff"

PANEL_GAP = 16          # clearance kept between a clamped panel and the screen top
STATUS_CLEAR_MS = 5000  # status line auto-clears after this many ms

SLOT_EN = {
    Slot.WEAPON: "Weapon", Slot.HELMET: "Helmet", Slot.BODY: "Body Armour",
    Slot.GLOVES: "Gloves", Slot.BOOTS: "Boots", Slot.BELT: "Belt",
    Slot.AMULET: "Amulet", Slot.RING: "Ring",
}
SLOT_ABBR = {
    Slot.WEAPON: "We", Slot.HELMET: "He", Slot.BODY: "Bd", Slot.GLOVES: "Gl",
    Slot.BOOTS: "Bt", Slot.BELT: "Be", Slot.AMULET: "Am", Slot.RING: "Ri",
}
WEAPON_ABBR = (("sword", "Sw"), ("blade", "Sw"), ("bow", "Bo"), ("staff", "St"),
               ("axe", "Ax"), ("mace", "Ma"), ("cudgel", "Ma"), ("sceptre", "Ma"))
CLASS_EN = {
    "warrior": "Warrior", "mage": "Mage", "archer": "Archer",
    "cleric": "Cleric", "barbarian": "Barbarian",
}

STYLE = """
QWidget { background: transparent; color: #c8b898; font-family: Consolas, 'Courier New', monospace; font-size: 12px; }
QWidget#panel { background: #1a1512; border: 1px solid #6a5a3a; }
QFrame#cell { background: #221b15; border: 1px solid #3a3226; }
QFrame#cell:hover { border: 1px solid #8a7a4a; }
QLabel { border: none; }
QLabel#hdr { color: #d4c08a; font-weight: bold; }
QLabel#dim { color: #7a6f5a; font-size: 10px; }
QScrollBar:vertical { background: #1a1512; width: 10px; }
QScrollBar::handle:vertical { background: #3a3226; min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #6a5a3a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

# shared button skin for panel action buttons (Sort, Take All, Sell junk, ...)
BTN_QSS = """
QPushButton {
    background: #2a2218; color: #d4c08a; border: 1px solid #6a5a3a;
    padding: 4px 14px; font-weight: bold;
}
QPushButton:hover { border: 1px solid #8a7a4a; background: #342a1c; }
QPushButton:disabled { color: #6a5f4a; border-color: #3a3226; }
"""

_CLOSE_QSS = """
QPushButton { background: transparent; color: #7a6f5a; border: 1px solid transparent;
              font-size: 13px; font-weight: bold; }
QPushButton:hover { background: #4a1c1c; color: #ffffff; border: 1px solid #6a3a3a; }
"""


def item_abbr(item: Item) -> str:
    if item.slot == Slot.WEAPON:
        for key, ab in WEAPON_ABBR:
            if key in item.base_id:
                return ab
    return SLOT_ABBR[item.slot]


# --- item icons ------------------------------------------------------------
_log = logging.getLogger(__name__)
ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
ICON_SLOT_DIRS = {
    Slot.HELMET: "helmet", Slot.BODY: "armor", Slot.GLOVES: "gloves",
    Slot.BELT: "belts", Slot.AMULET: "gems", Slot.RING: "rings",
    Slot.BOOTS: "boots",
}
WEAPON_ICON_DIRS = (("bow", "bow"), ("staff", "staff"), ("axe", "axe"),
                    ("mace", "mace"), ("cudgel", "mace"), ("sceptre", "mace"))

_icon_map: dict[str, str] | None = None       # base_id -> relative icon path (map.json)
_icon_files: dict[str, list[Path]] = {}       # folder -> sorted png paths
_icon_pixmaps: dict[str, QPixmap | None] = {}  # base_id -> scaled pixmap (lazy)
_fallback_pm: QPixmap | None = None


def _load_icon_map() -> dict[str, str]:
    global _icon_map
    if _icon_map is None:
        try:
            _icon_map = json.loads((ICON_DIR / "map.json").read_text())
        except (OSError, ValueError):
            _icon_map = {}
    return _icon_map


def _dir_files(folder: str) -> list[Path]:
    if folder not in _icon_files:
        _icon_files[folder] = sorted((ICON_DIR / folder).glob("*.png"), key=lambda p: p.name)
    return _icon_files[folder]


def _fallback_icon() -> QPixmap:
    global _fallback_pm
    if _fallback_pm is None:
        _fallback_pm = QPixmap(str(ICON_DIR / "fallback.png"))
        if _fallback_pm.isNull():
            _fallback_pm = QPixmap(CELL - 10, CELL - 10)
            _fallback_pm.fill(QColor("#2a2218"))
    return _fallback_pm


def load_icon(path: str) -> QPixmap:
    pm = QPixmap(path)
    if pm.isNull():
        _log.warning("missing icon: %s", path)
        return _fallback_icon()
    return pm


def _icon_path(item: Item) -> Path | None:
    """Curated map.json first, else deterministic: slot -> folder, name hash -> file."""
    rel = _load_icon_map().get(item.base_id)
    if rel and (ICON_DIR / rel).exists():
        return ICON_DIR / rel
    if item.slot is Slot.WEAPON:
        folder = next((d for key, d in WEAPON_ICON_DIRS if key in item.base_id), "sword")
    else:
        folder = ICON_SLOT_DIRS.get(item.slot)
    if not folder:
        return None
    files = _dir_files(folder)
    if not files:
        return None
    return files[zlib.crc32(item.base_id.encode()) % len(files)]


def item_pixmap(item: Item) -> QPixmap | None:
    """Icon scaled to fit a cell (keeping aspect), or None. Lazy: needs QApplication."""
    if item.base_id in _icon_pixmaps and _icon_pixmaps[item.base_id] is None:
        del _icon_pixmaps[item.base_id]

    if item.base_id not in _icon_pixmaps:
        path = _icon_path(item)
        if path is not None:
            raw = load_icon(str(path))
            inner = CELL - 10
            pm = raw.scaled(
                inner, inner,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            pm = _fallback_icon().scaled(
                CELL - 10, CELL - 10,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        _icon_pixmaps[item.base_id] = pm
    return _icon_pixmaps[item.base_id]


def sell_price(item: Item) -> int:
    return item_value(item)


# --- skill icons (skills_map.json: skill_id -> relative path in assets/icons) ---
SKILL_ICON_PX = 28

_skill_map: dict[str, str] | None = None
_skill_pixmaps: dict[str, QPixmap | None] = {}


def _load_skill_map() -> dict[str, str]:
    global _skill_map
    if _skill_map is None:
        try:
            _skill_map = json.loads((ICON_DIR / "skills_map.json").read_text())
        except (OSError, ValueError):
            _skill_map = {}
    return _skill_map


def skill_pixmap(skill_id: str) -> QPixmap | None:
    """Skill icon scaled to SKILL_ICON_PX, or None. Lazy: needs QApplication."""
    if skill_id not in _skill_pixmaps:
        pm = None
        rel = _load_skill_map().get(skill_id)
        if rel and (ICON_DIR / rel).exists():
            raw = QPixmap(str(ICON_DIR / rel))
            if not raw.isNull():
                pm = raw.scaled(
                    SKILL_ICON_PX, SKILL_ICON_PX,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,  # crisp pixel art
                )
        _skill_pixmaps[skill_id] = pm
    return _skill_pixmaps[skill_id]


# --- HoverTip (instant tooltip, no QToolTip delay) ----------------------------
class HoverTip(QWidget):
    _instance: "HoverTip | None" = None

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(
            "QWidget { background: #1a1512; border: 1px solid #6a5a3a; padding: 6px; }"
            "QLabel { color: #c8b898; font-family: Consolas, monospace; font-size: 11px; border: none; }"
        )
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)

    @classmethod
    def instance(cls) -> "HoverTip":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def show_for(self, widget: QWidget, html: str):
        self.label.setText(html)
        self.label.adjustSize()
        self.resize(self.label.size().width() + 12, self.label.size().height() + 12)
        pos = widget.mapToGlobal(QPoint(0, -self.height() - 4))
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            if pos.y() < geo.top():
                pos = widget.mapToGlobal(QPoint(0, widget.height() + 4))
            if pos.x() + self.width() > geo.right():
                pos.setX(geo.right() - self.width())
        self.move(pos)
        self.show()


_hover_tip: HoverTip | None = None


def _tip() -> HoverTip:
    return HoverTip.instance()


def _fmt(v: float) -> str:
    return str(int(v)) if float(v) == int(v) else f"{v:.1f}"


def can_equip(hero: Hero, item: Item) -> bool:
    req = getattr(item, "class_req", ()) or ()
    return not req or hero.class_id in req


# --- item sorting (stash / inventory Sort buttons) ---------------------------
_SLOT_ORDER = {slot: i for i, slot in enumerate(Slot)}
_RARITY_ORDER = {Rarity.NORMAL: 0, Rarity.MAGIC: 1, Rarity.RARE: 2, Rarity.UNIQUE: 3}


def sort_items(items: list[Item]) -> None:
    """In place: slot order, then rarity (best first), then ilvl descending."""
    items.sort(key=lambda it: (_SLOT_ORDER[it.slot], -_RARITY_ORDER[it.rarity], -it.ilvl))


def item_html(item: Item, hero_class: str | None = None, equipped: bool = False,
              hint: str | None = None) -> str:
    col = RARITY_COLORS[item.rarity]
    sep = '<div style="color:#6a5a3a; text-align:center">──────────────</div>'
    lines = []
    if equipped:
        lines.append('<div style="color:#d4c08a; font-weight:bold; text-align:center; '
                     'background:#2a2318">— EQUIPPED —</div>')
    # E.5: if ANY affix line on the item carries a greater-affix ★, mark the item
    # NAME at the very top with the highest star count found (gold ★, one glance =
    # "this item has a starred stat"). The per-line ★ prefix still renders below.
    _stars = max((getattr(a, "stars", 0)
                  for a in list(item.affixes) + list(getattr(item, "corrupted_lines", []) or [])),
                 default=0)
    _star_pre = f'<span style="color:#ffd24a">{"★" * _stars}</span> ' if _stars else ""
    lines.append(f'<div style="color:{col}; font-weight:bold; text-align:center">{_star_pre}{item.display_name()}</div>')
    # 10-tier ladder overlays (tiers 8 & 10): a foil-unique (RELIC) or perfect-roll
    # (PRIMAL) badge under the name. Relic = warm foil gold; primal = rainbow band
    # (the HTML-tooltip stand-in for the in-world rainbow-cycle frame).
    _mod = getattr(item, "modifier", "") or ""
    if _mod == MOD_RELIC:
        lines.append('<div style="color:#ffcf6b; font-weight:bold; letter-spacing:2px; '
                     'text-align:center">✦ RELIC ✦</div>')
    elif _mod == MOD_PRIMAL:
        lines.append('<div style="color:#ff5edb; font-weight:bold; letter-spacing:2px; '
                     'text-align:center">◆ PRIMAL ◆</div>')
    if item.rarity in (Rarity.RARE, Rarity.UNIQUE) and item.name:
        lines.append(f'<div style="color:{col}; text-align:center">{item.base_name}</div>')
    lines.append(
        f'<div style="color:#7a6f5a; text-align:center">'
        f'Item Level: {item.ilvl} &nbsp;·&nbsp; Requires Level {item.req_level}</div>'
    )
    req = getattr(item, "class_req", ()) or ()
    if req:
        usable = hero_class is None or hero_class in req
        rcol = "#7a6f5a" if usable else "#e04040"
        names = ", ".join(CLASS_EN.get(c, c) for c in req)
        lines.append(f'<div style="color:{rcol}; text-align:center">Classes: {names}</div>')
    if item.implicit:
        lines.append(sep)
        for m in item.implicit:
            lines.append(f'<div style="color:#b8b0a0; font-style:italic; text-align:center">{m.describe()}</div>')
    if item.affixes:
        lines.append(sep)
        for a in item.affixes:
            for text in (a.lines or [m.describe() for m in a.mods]):
                lines.append(f'<div style="color:{AFFIX_COLOR}; text-align:center">{text}</div>')
    # cube step 1: over-limit corrupted lines render red, under a CORRUPTED tag.
    corr = getattr(item, "corruption", 0)
    clines = getattr(item, "corrupted_lines", None) or []
    if corr or clines:
        lines.append(sep)
        roman = ["", "I", "II", "III"][min(corr, 3)]
        tag = f"CORRUPTED{f' {roman}' if roman else ''}"
        lines.append(f'<div style="color:#e04040; font-weight:bold; text-align:center">{tag}</div>')
        for a in clines:
            for text in (a.lines or [m.describe() for m in a.mods]):
                lines.append(f'<div style="color:#e04040; text-align:center">{text}</div>')
    lines.append(f'<div style="color:#7a6f5a; text-align:center">Value: {item_value(item)} gold</div>')
    if hint:
        lines.append(f'<div style="color:#7a6f5a; text-align:center; font-size:10px">{hint}</div>')
    body = "".join(lines)
    # red frame around the whole tooltip for corrupted items
    if corr:
        return (f'<div style="border:2px solid #e04040; padding:3px">{body}</div>')
    return body


class Panel(QWidget):
    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)


def _hdr(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("hdr")
    return lab


def panel_max_height() -> int:
    """Vertical space a panel may occupy: the screen above the game strip minus
    a small gap. Panels are anchored above the strip and must never cover it."""
    try:
        from ui.window import STRIP_H
    except ImportError:  # standalone smoke without the strip module
        STRIP_H = 64
    screen = QApplication.primaryScreen()
    if screen is None:
        return 10 ** 6
    geo = screen.availableGeometry()
    return max(160, geo.height() - STRIP_H - PANEL_GAP)


class _ContentScroll(QScrollArea):
    """Scroll area that prefers its content's full size, so the panel sizes to
    the content and only scrolls once PanelFrame's height clamp kicks in."""

    def sizeHint(self) -> QSize:
        w = self.widget()
        if w is None:
            return super().sizeHint()
        sh = w.sizeHint()
        return QSize(sh.width() + 2, sh.height() + 2)


class PanelFrame(Panel):
    """Base for every closable popup panel (spec §6).

    Provides: a title bar with the panel name and a close X, Esc-to-close, a
    dim status line for action feedback (never fail silently — W3.4), and a
    height clamp: the panel may use at most the screen space above the game
    strip; taller content scrolls inside. Since panels are placed above the
    strip, any growth goes upward, never down onto the strip.

    Subclasses build their UI inside ``self.content``::

        root = QVBoxLayout(self.content)

    Extra title-bar widgets (buttons, gold label) go through
    :meth:`add_header_widget`. Refused actions call :meth:`set_status`.
    ``ItemTooltip`` deliberately stays on the plain :class:`Panel` base — a
    tooltip needs neither an X button nor Esc handling.
    """

    closed = pyqtSignal()  # emitted whenever the panel hides (X, Esc, manager, code)

    def __init__(self, title: str):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 10)
        outer.setSpacing(6)

        self._head = QHBoxLayout()
        self._head.setSpacing(8)
        self.title_lab = _hdr(title)
        self._head.addWidget(self.title_lab)
        self._head.addStretch(1)
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("close")
        self.close_btn.setFixedSize(18, 18)
        self.close_btn.setStyleSheet(_CLOSE_QSS)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.setToolTip("Close (Esc)")
        self.close_btn.clicked.connect(self.close_panel)
        self._head.addWidget(self.close_btn)
        outer.addLayout(self._head)

        self.content = QWidget()
        self._scroll = _ContentScroll()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self.content)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Panels always size their width to fit content (see adjustSize), so a
        # horizontal scrollbar can only ever appear as a one-frame flicker during
        # relayout (e.g. a button relabelling wider). Kill it outright.
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll, 1)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        outer.addWidget(self.status)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self.status.setText(""))

        # Esc closes even when a child widget holds focus
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close_panel)

    # ------------------------------------------------------------- frame API
    def add_header_widget(self, w: QWidget) -> None:
        """Insert a widget into the title bar, left of the close button."""
        self._head.insertWidget(self._head.count() - 1, w)

    def set_status(self, text: str) -> None:
        """User feedback line; auto-clears after STATUS_CLEAR_MS."""
        self.status.setText(text)
        if text:
            self._status_timer.start(STATUS_CLEAR_MS)

    def close_panel(self) -> None:
        self.hide()

    # ------------------------------------------------------------- behaviour
    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            e.accept()
            self.close_panel()
        else:
            super().keyPressEvent(e)

    def adjustSize(self) -> None:
        """Grow to fit content, but clamp to the space above the game strip;
        when clamped, reserve the scrollbar gutter so cells are not squeezed."""
        self.setMaximumHeight(16777215)  # let sizeHint report the honest size
        need = self.sizeHint()
        max_h = panel_max_height()
        self.setMaximumHeight(max_h)
        if need.height() > max_h:
            gutter = self._scroll.verticalScrollBar().sizeHint().width()
            self.resize(need.width() + gutter, max_h)
        else:
            super().adjustSize()

    def showEvent(self, e):
        self.status.setText("")  # stale feedback must not greet a fresh open
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        super().showEvent(e)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.closed.emit()


class PanelManager:
    """Open/close coordinator for popup panels (spec §6.2).

    All panels are mutually exclusive except the pairs in ALLOWED_PAIRS —
    trading and stashing need the inventory open alongside. Works with any
    QWidget (show/hide/isVisible); PanelFrame's ``closed`` signal additionally
    reports X/Esc closes through ``on_change``.

    main.py wiring::

        mgr = PanelManager(place=self._place, on_change=self._update_chevron)
        mgr.register("inventory", self.inv_panel, refresh=self.inv_panel.refresh)
        mgr.register("zones", self.zones_panel, refresh=lambda: self.zones_panel.refresh(...))
        ...menu button -> mgr.toggle("inventory")

    Canonical names: inventory, character, stash, vendor, cube, gamble,
    zones, stats, tree.
    """

    ALLOWED_PAIRS = (frozenset({"vendor", "inventory"}),
                     frozenset({"stash", "inventory"}))

    def __init__(self, place=None, on_change=None):
        self._panels: dict[str, QWidget] = {}
        self._refresh: dict[str, object] = {}
        self.place = place          # callable(panel): position it above the strip
        self.on_change = on_change  # callable(): chevron/state update in main

    def register(self, name: str, panel: QWidget, refresh=None) -> None:
        self._panels[name] = panel
        if refresh is not None:
            self._refresh[name] = refresh
        closed = getattr(panel, "closed", None)  # PanelFrame X/Esc notifications
        if closed is not None:
            closed.connect(self._changed)

    def is_open(self, name: str) -> bool:
        p = self._panels.get(name)
        return p is not None and p.isVisible()

    def open_names(self) -> list[str]:
        return [n for n, p in self._panels.items() if p.isVisible()]

    def open_widgets(self) -> list[QWidget]:
        return [p for p in self._panels.values() if p.isVisible()]

    def toggle(self, name: str) -> bool:
        """Show/hide a panel by name; opening closes every non-paired panel.
        Returns True when the panel ends up visible."""
        panel = self._panels.get(name)
        if panel is None:
            return False
        if panel.isVisible():
            panel.hide()
        else:
            for other, p in self._panels.items():
                if other != name and p.isVisible() \
                        and frozenset({name, other}) not in self.ALLOWED_PAIRS:
                    p.hide()
            fn = self._refresh.get(name)
            if fn:
                fn()
            if self.place:
                self.place(panel)
            panel.show()
        self._changed()
        return panel.isVisible()

    def close_all(self) -> None:
        for p in self._panels.values():
            p.hide()
        self._changed()

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()


class Cell(QFrame):
    clicked = pyqtSignal(object)
    rclicked = pyqtSignal(object)
    hovered = pyqtSignal(object)
    unhovered = pyqtSignal(object)

    def __init__(self, kind: str, key):
        super().__init__()
        self.kind, self.key = kind, key
        self.item: Item | None = None
        self.setObjectName("cell")
        self.setFixedSize(CELL, CELL)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        self.lab = QLabel("", alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lab)

    def set_item(self, item: Item | None) -> None:
        self.item = item
        if item:
            pm = item_pixmap(item)
            if pm is not None:
                self.lab.setPixmap(pm)
            else:
                self.lab.setText(item_abbr(item))
            self.lab.setStyleSheet(
                f"background:{RARITY_COLORS[item.rarity]}; color:#1a1512; font-weight:bold;"
            )
        else:
            self.lab.setPixmap(QPixmap())
            self.lab.setText("")
            self.lab.setStyleSheet("background:transparent;")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)
        elif e.button() == Qt.MouseButton.RightButton:
            self.rclicked.emit(self)

    def enterEvent(self, e):
        self.hovered.emit(self)

    def leaveEvent(self, e):
        self.unhovered.emit(self)


def _clamp_to_screen(x: int, y: int, w: int, h: int) -> QPoint:
    """Keep a (x,y,w,h) popup fully inside the screen it lands on. Fixes tooltips
    on right-hand inventory cells flying off the right/top edge of the monitor —
    we shift left/down so the whole box stays visible instead of clipping."""
    screen = QApplication.screenAt(QPoint(x, y)) or QApplication.primaryScreen()
    if screen is None:
        return QPoint(max(0, x), max(0, y))
    geo = screen.availableGeometry()
    if x + w > geo.right():
        x = geo.right() - w
    if x < geo.left():
        x = geo.left()
    if y + h > geo.bottom():
        y = geo.bottom() - h
    if y < geo.top():
        y = geo.top()
    return QPoint(x, y)


class ItemTooltip(Panel):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        self.lab = QLabel()
        self.lab.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.lab)

    def show_item(self, item: Item, pos: QPoint, hero_class: str | None = None,
                  equipped: bool = False, hint: str | None = None) -> None:
        self.lab.setText(item_html(item, hero_class, equipped, hint))
        self.adjustSize()
        self.move(_clamp_to_screen(pos.x(), pos.y() - self.height(),
                                   self.width(), self.height()))
        self.show()


class InventoryPanel(PanelFrame):
    HINT_INV = "RMB: sell (Vendor must be open) · Shift: compare"
    HINT_EQUIP = "Click: unequip"
    SELL_HINT = "RMB an item to sell it — only while the Vendor window is open."

    def __init__(self, hero: Hero, on_change=None):
        super().__init__("Inventory")
        self.hero, self.on_change = hero, on_change
        self.sell_hook = None  # callable(Item) -> bool; True = sale handled externally (vendor)
        self.can_sell = lambda: True  # main.py gates this on the vendor being open
        self.confirm_sell = self._ask_confirm  # callable(Item) -> bool; replaceable in tests
        self.tooltip = ItemTooltip()
        self.compare_tip = ItemTooltip()
        self._hover_cell: Cell | None = None
        QApplication.instance().installEventFilter(self)

        self.sort_btn = QPushButton("Sort")
        self.sort_btn.setStyleSheet(BTN_QSS)
        self.sort_btn.clicked.connect(self._on_sort)
        self.add_header_widget(self.sort_btn)

        root = QHBoxLayout(self.content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        eq_box = QVBoxLayout()
        eq_box.setSpacing(2)
        eq_box.addWidget(_hdr("Equipment"))
        eq_grid = QGridLayout()
        eq_grid.setHorizontalSpacing(6)
        eq_grid.setVerticalSpacing(2)
        self.eq_cells: dict[str, Cell] = {}
        for i, slot in enumerate(Slot):
            lab = QLabel(SLOT_EN[slot])
            lab.setObjectName("dim")
            cell = Cell("equip", slot.value)
            self._wire(cell)
            self.eq_cells[slot.value] = cell
            eq_grid.addWidget(lab, (i // 2) * 2, i % 2)
            eq_grid.addWidget(cell, (i // 2) * 2 + 1, i % 2)
        eq_box.addLayout(eq_grid)
        eq_box.addStretch(1)
        root.addLayout(eq_box)

        inv_box = QVBoxLayout()
        inv_box.setSpacing(4)
        inv_box.addWidget(_hdr("Backpack"))
        inv_grid = QGridLayout()
        inv_grid.setSpacing(4)
        self.inv_cells: list[Cell] = []
        for i in range(INV_COLS * INV_ROWS):
            cell = Cell("inv", i)
            self._wire(cell)
            self.inv_cells.append(cell)
            inv_grid.addWidget(cell, i // INV_COLS, i % INV_COLS)
        inv_box.addLayout(inv_grid)
        self.gold_lab = QLabel()
        inv_box.addWidget(self.gold_lab)
        self.sell_hint_lab = QLabel(self.SELL_HINT)
        self.sell_hint_lab.setObjectName("dim")
        self.sell_hint_lab.setWordWrap(True)
        inv_box.addWidget(self.sell_hint_lab)
        inv_box.addStretch(1)
        root.addLayout(inv_box)

        self.refresh()

    def _wire(self, cell: Cell) -> None:
        cell.clicked.connect(self._on_click)
        cell.rclicked.connect(self._on_rclick)
        cell.hovered.connect(self._on_hover)
        cell.unhovered.connect(self._on_unhover)

    def _cap(self) -> int:
        return INV_COLS * INV_ROWS

    def _on_click(self, cell: Cell) -> None:
        h = self.hero
        if cell.kind == "inv":
            if cell.key >= len(h.inventory):
                return
            item = h.inventory[cell.key]
            if not can_equip(h, item):
                names = ", ".join(CLASS_EN.get(c, c) for c in item.class_req)
                self.set_status(f"Cannot equip: {names} only")
                return
            h.inventory.pop(cell.key)
            prev = h.equipment.get(item.slot.value)
            h.equipment[item.slot.value] = item
            if prev:
                h.inventory.insert(cell.key, prev)
        else:
            item = h.equipment.get(cell.key)
            if not item:
                return
            if len(h.inventory) >= self._cap():
                self.set_status("Inventory full")
                return
            h.equipment[cell.key] = None
            h.inventory.append(item)
        self._changed()

    def _on_rclick(self, cell: Cell) -> None:
        """Sell the clicked backpack item — but ONLY while the vendor window is
        open (main.py wires can_sell to vendor visibility). Without an open shop
        a right-click does nothing but nudge the player with a status line, so
        items can't be sold by accident. Rare/unique still ask to confirm; the
        sell_hook (vendor buyback) takes over the gold credit when it returns
        True, otherwise we fall back to a flat item_value credit."""
        h = self.hero
        if cell.kind != "inv" or cell.key >= len(h.inventory):
            return
        if not self.can_sell():
            self.set_status("Open the Vendor to sell (RMB sells only then)")
            return
        item = h.inventory[cell.key]
        if item.rarity in (Rarity.RARE, Rarity.UNIQUE) and not self.confirm_sell(item):
            return
        h.inventory.pop(cell.key)
        if self.sell_hook and self.sell_hook(item):
            self._changed()
            return
        value = sell_price(item)
        h.gold += value
        self._changed()
        self.set_status(f"Sold {item.display_name()} for {value} gold")

    def _ask_confirm(self, item: Item) -> bool:
        resp = QMessageBox.question(
            self, "Sell item",
            f"Sell {item.display_name()} for {sell_price(item)} gold?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return resp == QMessageBox.StandardButton.Yes

    def _on_sort(self) -> None:
        sort_items(self.hero.inventory)
        self._changed()
        self.set_status("Backpack sorted")

    def _on_hover(self, cell: Cell, shift: bool | None = None) -> None:
        self._hover_cell = cell
        if not cell.item:
            return
        pos = cell.mapToGlobal(QPoint(0, -6))
        hint = self.HINT_INV if cell.kind == "inv" else self.HINT_EQUIP
        self.tooltip.show_item(cell.item, pos, hero_class=self.hero.class_id,
                               equipped=(cell.kind == "equip"), hint=hint)
        if shift is None:
            shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        eq = self.hero.equipment.get(cell.item.slot.value) if cell.kind == "inv" else None
        if shift and eq is not None and eq is not cell.item:
            # compare window sits to the left of the hovered tooltip
            self.compare_tip.show_item(eq, pos, hero_class=self.hero.class_id, equipped=True)
            self.compare_tip.move(_clamp_to_screen(
                pos.x() - self.compare_tip.width() - 8,
                pos.y() - self.compare_tip.height(),
                self.compare_tip.width(), self.compare_tip.height()))
        else:
            self.compare_tip.hide()

    def _on_unhover(self, _cell: Cell) -> None:
        self._hover_cell = None
        self._hide_tips()

    def eventFilter(self, obj, e):
        # Shift pressed/released while already hovering a cell -> refresh compare tip
        if e.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) \
                and e.key() == Qt.Key.Key_Shift and self._hover_cell is not None:
            self._on_hover(self._hover_cell, shift=(e.type() == QEvent.Type.KeyPress))
        return super().eventFilter(obj, e)

    def _hide_tips(self) -> None:
        self.tooltip.hide()
        self.compare_tip.hide()

    def _changed(self) -> None:
        self.hero.recalc()
        self._hide_tips()
        self.refresh()
        if self.on_change:
            self.on_change()

    def refresh(self) -> None:
        for key, cell in self.eq_cells.items():
            cell.set_item(self.hero.equipment.get(key))
        for i, cell in enumerate(self.inv_cells):
            cell.set_item(self.hero.inventory[i] if i < len(self.hero.inventory) else None)
        self.gold_lab.setText(f"Gold: {self.hero.gold}")
        if self.can_sell():
            self.sell_hint_lab.setText("Vendor open — RMB an item to sell it.")
            self.sell_hint_lab.setStyleSheet("color:#8a9f5a;")
        else:
            self.sell_hint_lab.setText(self.SELL_HINT)
            self.sell_hint_lab.setStyleSheet("")
        self.adjustSize()

    def hideEvent(self, e):
        self._hover_cell = None
        self._hide_tips()
        super().hideEvent(e)


class CharacterPanel(PanelFrame):
    def __init__(self, hero: Hero):
        super().__init__("Character")
        self.hero = hero
        self.head = self.title_lab  # refresh() rewrites it to "<class> — Level N"
        lay = QVBoxLayout(self.content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.sub = QLabel()
        self.sub.setObjectName("dim")
        cols = QHBoxLayout()
        cols.setSpacing(20)
        self.col1, self.col2 = QLabel(), QLabel()
        for c in (self.col1, self.col2):
            c.setTextFormat(Qt.TextFormat.RichText)
            c.setAlignment(Qt.AlignmentFlag.AlignTop)
            cols.addWidget(c)
        lay.addWidget(self.sub)
        lay.addLayout(cols)
        self.skills_hdr = QLabel("Skills")
        self.skills_hdr.setObjectName("dim")
        lay.addWidget(self.skills_hdr)
        self.skills_row = QHBoxLayout()
        self.skills_row.setSpacing(4)
        self.skills_row.addStretch(1)
        lay.addLayout(self.skills_row)
        self._skill_labels: list[QLabel] = []
        self.refresh()

    @staticmethod
    def _row(name: str, val: str, color: str = "#c8b898") -> str:
        return f'<div><span style="color:#7a6f5a">{name}:</span> <span style="color:{color}">{val}</span></div>'

    def refresh(self) -> None:
        h, s = self.hero, self.hero.stats
        self.head.setText(f"{CLASS_EN.get(h.class_id, h.class_id)} — Level {h.level}")
        self.sub.setText(f"XP: {h.xp} · Gold: {h.gold}")
        r = self._row
        self.col1.setText("".join([
            r("Life", f"{int(h.hp)}/{int(h.max_hp)}"),
            r("Damage", f"{int(s.damage_min)}–{int(s.damage_max)}"),
            r("Attack Speed", f"{s.attack_speed:.2f}/s"),
            r("Crit Chance", f"{_fmt(s.crit_chance)}%"),
            r("Crit Multiplier", f"{_fmt(s.crit_multi)}%"),
        ]))
        self.col2.setText("".join([
            r("Armour", _fmt(s.armor)),
            r("Evasion", _fmt(s.evasion)),
            r("Fire Resistance", f"{_fmt(s.res_fire)}%", DTYPE_COLORS[DamageType.FIRE]),
            r("Cold Resistance", f"{_fmt(s.res_cold)}%", DTYPE_COLORS[DamageType.COLD]),
            r("Lightning Resistance", f"{_fmt(s.res_lightning)}%", DTYPE_COLORS[DamageType.LIGHTNING]),
            r("Chaos Resistance", f"{_fmt(s.res_chaos)}%", DTYPE_COLORS[DamageType.CHAOS]),
            r("Move Speed", f"{int(s.move_speed)} px/s"),
        ]))
        self._refresh_skills()
        self.adjustSize()

    def _refresh_skills(self) -> None:
        """Show the REAL equipped Skills V2 loadout (primary / actives / aura /
        utility / ultimate) — a read-only mirror of what's slotted in the Skills
        panel, not the full unlockable list."""
        for lab in self._skill_labels:
            self.skills_row.removeWidget(lab)
            lab.deleteLater()
        self._skill_labels = []

        SV.ensure_skills_v2(self.hero)
        equipped = SV._equipped_ids(self.hero.skills_v2)
        skills = SV.load_skills_v2()
        badge = {"primary": "P", "spender": "S", "aura": "AU",
                 "utility": "U", "ultimate": "ULT"}
        for sid in equipped:
            sk = skills.get(sid)
            if sk is None:
                continue
            lab = QPushButton()
            lab.setFixedSize(SKILL_ICON_PX + 6, SKILL_ICON_PX + 6)
            lab.setStyleSheet("QPushButton { background:#221b15; border:1px solid #3a3226; }"
                            "QPushButton:hover { border:1px solid #6a5a3a; }")
            lab.setFlat(True)
            pm = skill_pixmap(sid)
            if pm is not None:
                lab.setIcon(QIcon(pm))
                lab.setIconSize(pm.size())
            else:
                lab.setText(badge.get(sk.type, sk.name[:2]))
            rank, _, _ = SV.rank_progress(self.hero, sid)
            lab._tip_html = (f"<b>{sk.name}</b> "
                             f"<span style='color:#8a9f5a'>[{badge.get(sk.type, sk.type)}]</span>"
                             f"<br><span style='color:#7a6f5a'>Rank {rank}</span>")
            lab.enterEvent = lambda e, w=lab: _tip().show_for(w, w._tip_html)
            lab.leaveEvent = lambda e, w=lab: _tip().hide()
            self.skills_row.insertWidget(len(self._skill_labels), lab)
            self._skill_labels.append(lab)
        self.skills_hdr.setText("Equipped Skills")
        self.skills_hdr.setVisible(bool(self._skill_labels))


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)

    sword = Item(
        "long_sword", "Long Sword", Slot.WEAPON, Rarity.RARE, 15, req_level=12,
        name="Dread Bane",
        implicit=[StatMod("damage_min", flat=8), StatMod("damage_max", flat=16)],
        affixes=[
            Affix("tyr", "Tyrannical", True, 2, [StatMod("damage_max", flat=9)]),
            Affix("swift", "of Swiftness", False, 3, [StatMod("attack_speed", inc=12)]),
            Affix("stout", "Stout", True, 4, [StatMod("life", flat=25)]),
        ],
    )
    helm = Item(
        "chain_coif", "Chain Coif", Slot.HELMET, Rarity.MAGIC, 13, req_level=10,
        name="Chain Coif of the Guardian",
        implicit=[StatMod("armor", flat=26), StatMod("evasion", flat=26)],
        affixes=[Affix("guard", "of the Guardian", False, 4, [StatMod("life", flat=18)])],
    )
    ring = Item(
        "coral_ring", "Coral Ring", Slot.RING, Rarity.NORMAL, 5, req_level=1,
        implicit=[StatMod("life", flat=15)],
    )
    amulet = Item(
        "jade_amulet", "Jade Amulet", Slot.AMULET, Rarity.MAGIC, 14, req_level=12,
        name="Jade Amulet of the Salamander",
        implicit=[StatMod("evasion", flat=20)],
        affixes=[Affix("sala", "of the Salamander", False, 3, [StatMod("res_fire", flat=22)])],
    )

    hero = Hero(name="Test", stats=Stats(), base_stats=Stats(), gold=40, class_id="warrior")
    hero.equipment = {s.value: None for s in Slot}
    hero.equipment[Slot.WEAPON.value] = sword
    hero.inventory = [helm, ring, amulet]
    hero.init_hp()
    hero.recalc()

    inv = InventoryPanel(hero, on_change=lambda: None)
    ch = CharacterPanel(hero)
    tip = ItemTooltip()
    inv.refresh()
    ch.refresh()
    tip.show_item(sword, QPoint(100, 400))
    inv.show()

    inv._on_click(inv.inv_cells[0])
    assert hero.equipment[Slot.HELMET.value] is helm
    assert "Value:" in item_html(sword) and "Value:" in item_html(ring)
    assert "RMB: sell" in item_html(ring, hint=InventoryPanel.HINT_INV)  # tooltip hint

    # RMB is gated on can_sell(): with the vendor closed nothing sells
    inv.can_sell = lambda: False
    gold_before = hero.gold
    inv_len = len(hero.inventory)
    inv._on_rclick(inv.inv_cells[0])
    assert hero.gold == gold_before and len(hero.inventory) == inv_len
    assert "Vendor" in inv.status.text()
    inv.can_sell = lambda: True

    # RMB on a normal item: instant sale, gold fallback (no hook), status feedback
    gold_before = hero.gold
    ring_value = sell_price(ring)
    inv._on_rclick(inv.inv_cells[0])
    assert hero.gold == gold_before + ring_value and len(hero.inventory) == 1
    assert f"for {ring_value} gold" in inv.status.text()

    # sell_hook returning True handles the sale itself: no gold fallback
    hooked: list = []
    inv.sell_hook = lambda it: hooked.append(it) or True
    gold_before = hero.gold
    inv._on_rclick(inv.inv_cells[0])
    assert hooked == [amulet] and hero.gold == gold_before and len(hero.inventory) == 0
    inv.sell_hook = None
    hero.inventory.append(amulet)
    inv.refresh()

    # RMB on rare: needs confirmation; declined -> nothing happens
    rare_ring = Item("iron_ring", "Iron Ring", Slot.RING, Rarity.RARE, 20, req_level=1,
                     name="Doom Loop")
    hero.inventory.append(rare_ring)
    inv.refresh()
    asked: list = []
    inv.confirm_sell = lambda it: asked.append(it) and False
    gold_before = hero.gold
    inv._on_rclick(inv.inv_cells[1])
    assert asked == [rare_ring] and rare_ring in hero.inventory and hero.gold == gold_before
    # accepted -> sold at item_value
    inv.confirm_sell = lambda it: True
    inv._on_rclick(inv.inv_cells[1])
    assert rare_ring not in hero.inventory
    assert hero.gold == gold_before + sell_price(rare_ring)

    bow = Item(
        "short_bow", "Short Bow", Slot.WEAPON, Rarity.NORMAL, 5, req_level=1,
        class_req=("archer",), implicit=[StatMod("damage_max", flat=4)],
    )
    hero.inventory.append(bow)
    inv.refresh()
    assert not can_equip(hero, bow)
    inv._on_click(inv.inv_cells[1])
    assert hero.equipment[Slot.WEAPON.value] is sword and bow in hero.inventory
    assert inv.status.text() == "Cannot equip: Archer only"  # W3.4: no silent refusal
    assert 'color:#e04040' in item_html(bow, hero_class="warrior")

    # W3.4: unequip into a full backpack reports instead of silently failing
    hero.inventory = [ring] * (INV_COLS * INV_ROWS)
    inv.refresh()
    inv._on_click(inv.eq_cells[Slot.WEAPON.value])
    assert hero.equipment[Slot.WEAPON.value] is sword
    assert inv.status.text() == "Inventory full"
    hero.inventory = [amulet, bow]
    inv.refresh()

    # Sort button: slot order, then rarity desc, then ilvl desc
    r1 = Item("gold_ring", "Gold Ring", Slot.RING, Rarity.NORMAL, 3, req_level=1)
    r2 = Item("gold_ring", "Gold Ring", Slot.RING, Rarity.NORMAL, 9, req_level=1)
    hero.inventory = [r1, amulet, bow, r2]
    inv.refresh()
    inv._on_sort()
    assert hero.inventory == [bow, amulet, r2, r1], [i.base_id for i in hero.inventory]
    assert inv.status.text() == "Backpack sorted"

    # shift-hover: compare tooltip of the equipped item in the same slot
    from PyQt6.QtTest import QTest
    inv._on_hover(inv.inv_cells[0])  # bow, no shift
    assert inv.tooltip.isVisible() and not inv.compare_tip.isVisible()
    assert "RMB: sell" in inv.tooltip.lab.text() and "Shift: compare" in inv.tooltip.lab.text()
    QTest.keyPress(inv, Qt.Key.Key_Shift)  # eventFilter re-runs hover with shift held
    assert inv.compare_tip.isVisible(), "compare tip must appear on Shift"
    assert "EQUIPPED" in inv.compare_tip.lab.text()
    QTest.keyRelease(inv, Qt.Key.Key_Shift)
    assert not inv.compare_tip.isVisible(), "compare tip must hide on Shift release"
    inv._on_unhover(inv.inv_cells[0])
    assert not inv.tooltip.isVisible()

    # X button closes; Esc closes; tooltip has neither
    assert inv.isVisible()
    inv.close_btn.click()
    assert not inv.isVisible(), "X button must close the panel"
    inv.show()
    QTest.keyClick(inv, Qt.Key.Key_Escape)
    assert not inv.isVisible(), "Esc must close the panel"
    assert not hasattr(tip, "close_btn"), "tooltip must stay a plain Panel"
    inv.show()

    # height clamp: tall content scrolls, the panel never exceeds the space
    # above the strip (it is anchored above the strip, so it grows upward)
    tall = PanelFrame("Tall")
    tl = QVBoxLayout(tall.content)
    for i in range(300):
        tl.addWidget(QLabel(f"row {i}"))
    tall.show()
    tall.adjustSize()
    assert tall.height() <= panel_max_height(), (tall.height(), panel_max_height())
    assert tall.content.sizeHint().height() > tall.height(), "content should overflow into scroll"
    tall.hide()
    assert inv.height() <= panel_max_height()

    # PanelManager: exclusivity with the two allowed pairs
    stub_vendor, stub_stash, stub_cube = QWidget(), QWidget(), QWidget()
    changes: list[int] = []
    refreshed: list[str] = []
    mgr = PanelManager(on_change=lambda: changes.append(1))
    mgr.register("inventory", inv, refresh=lambda: refreshed.append("inventory"))
    mgr.register("vendor", stub_vendor)
    mgr.register("stash", stub_stash)
    mgr.register("cube", stub_cube)
    inv.hide()
    assert mgr.open_names() == []
    assert mgr.toggle("inventory") and mgr.is_open("inventory")
    assert refreshed == ["inventory"], "refresh hook must run before show"
    assert mgr.toggle("vendor") and mgr.is_open("vendor") and mgr.is_open("inventory"), \
        "vendor+inventory is an allowed pair"
    assert mgr.toggle("cube")
    assert mgr.is_open("cube") and not mgr.is_open("vendor") and not mgr.is_open("inventory"), \
        "cube must close everything else"
    assert mgr.toggle("stash") and not mgr.is_open("cube")
    assert mgr.toggle("inventory") and mgr.is_open("stash") and mgr.is_open("inventory"), \
        "stash+inventory is an allowed pair"
    assert not mgr.toggle("inventory") and mgr.is_open("stash"), "toggle off leaves the pair partner"
    mgr.toggle("inventory")
    n_changes = len(changes)
    inv.close_btn.click()  # X close must reach on_change via the closed signal
    assert len(changes) > n_changes, "X close must notify the manager"
    mgr.close_all()
    assert mgr.open_names() == []
    assert mgr.toggle("nope") is False  # unknown name: no crash

    inv.show()
    # equipped-skills row mirrors the Skills V2 loadout: warrior lvl1 = 1 slot
    # (primary), lvl16 = 5 (primary + 3 actives-window + aura/util as they open).
    assert len(ch._skill_labels) == 1, len(ch._skill_labels)
    hero.level = 16
    SV.ensure_skills_v2(hero)
    ch.refresh()
    assert len(ch._skill_labels) == 5, len(ch._skill_labels)
    # every slot renders either its icon or a type-badge fallback (never blank)
    assert all(not l.icon().isNull() or bool(l.text()) for l in ch._skill_labels), \
        "equipped skill slot rendered blank"
    assert "Level 16" in ch.title_lab.text()  # class/level lives in the title bar now

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_panels_test.png")
    inv.grab().save(path)
    ch.grab().save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_char_test.png"))
    print("OK:", path)
