"""Bar of Exile — launcher window: Main Menu / Character Select / Load / Settings.

Opens on game start, before the taskbar strip. After Confirm/Load it emits the
chosen action (new hero or loaded save) and closes; main.py starts the 64px bar.
Art packs in assets/ui/launcher/ (v1 main menu) and assets/ui/launcher2/ (v2 menu
art: charselect / load / settings). Pixel art is scaled nearest-neighbour only.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from PyQt6.QtCore import QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QCheckBox, QLabel, QLineEdit, QPushButton, QSlider, QStackedWidget, QWidget,
)

from game import classes
from game.save import SAVE_DIR

_ART = Path(__file__).resolve().parent.parent / "assets" / "ui" / "launcher"
_ART2 = Path(__file__).resolve().parent.parent / "assets" / "ui" / "launcher2"
_PORTRAITS = Path(__file__).resolve().parent.parent / "assets" / "ui" / "portraits"
W, H = 1376, 768

FONT_FAMILY = "Verdana"
GOLD = "#e8d5a0"
GOLD_BORDER = QColor(0xc9, 0xa2, 0x27)
ZONE_GOLD = QColor(0xc9, 0xa2, 0x27)
# sampled from a clean pixel of the load screen's info bar — used to cover the
# baked 'Total Playtime: --h --m --s' dashes before drawing the real value.
BAR_FILL = QColor(64, 55, 48)
# muted tan sampled from the baked 'Last Played:' / 'Total Playtime:' labels, so
# the dynamic values we overlay read as the same font as the baked labels.
INFO_TAN = QColor(0xc2, 0xa6, 0x98)

SETTINGS_PATH = Path(SAVE_DIR) / "settings.json"
DEFAULT_SETTINGS = {
    "volume": 80,            # sound volume (sfx); key kept as 'volume' for old files
    "music_volume": 80,
    "strip_scale": 100,
    "start_with_windows": False,
    "show_damage_numbers": True,
    "screen_shake": True,
    "always_on_top": True,
    "fps_cap": 30,           # 30 / 60
}


def load_settings() -> dict:
    d = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            d.update({k: data[k] for k in DEFAULT_SETTINGS if k in data})
    except (OSError, ValueError):
        pass
    return d


def save_settings(d: dict) -> None:
    try:
        os.makedirs(SAVE_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except OSError:
        pass


def _pix(name: str, folder: Path = _ART) -> QPixmap | None:
    p = folder / name
    if not p.exists():
        return None
    pm = QPixmap(str(p))
    return pm if not pm.isNull() else None


# module-level pixmap cache so screens don't reload art on every repaint
_cache: dict[str, QPixmap | None] = {}


def art(name: str, folder: Path = _ART) -> QPixmap | None:
    key = f"{folder}/{name}"
    if key not in _cache:
        _cache[key] = _pix(name, folder)
    return _cache[key]


def _draw_text_outlined(p: QPainter, x: int, y: int, text: str,
                        color: QColor, ow: int = 2) -> None:
    """Draw pixel-font text with a black outline so it reads over busy zone art."""
    p.setPen(QColor(0, 0, 0))
    for dx in (-ow, 0, ow):
        for dy in (-ow, 0, ow):
            if dx or dy:
                p.drawText(x + dx, y + dy, text)
    p.setPen(color)
    p.drawText(x, y, text)


def _draw_backdrop(p: QPainter):
    """Atmospheric stone backdrop fallback — vertical stone gradient + centre glow
    + dark vignette + gold trim. Only used if a v2 background PNG is missing."""
    g = QLinearGradient(0, 0, 0, H)
    g.setColorAt(0.0, QColor(0x1a, 0x14, 0x0f))
    g.setColorAt(0.5, QColor(0x24, 0x1d, 0x16))
    g.setColorAt(1.0, QColor(0x0d, 0x0a, 0x08))
    p.fillRect(QRect(0, 0, W, H), g)
    rg = QRadialGradient(QPointF(W / 2, H * 0.42), W * 0.62)
    rg.setColorAt(0.0, QColor(0x6b, 0x51, 0x22, 70))
    rg.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(QRect(0, 0, W, H), rg)
    vg = QRadialGradient(QPointF(W / 2, H / 2), W * 0.72)
    vg.setColorAt(0.62, QColor(0, 0, 0, 0))
    vg.setColorAt(1.0, QColor(0, 0, 0, 160))
    p.fillRect(QRect(0, 0, W, H), vg)
    p.fillRect(QRect(0, 0, W, 4), QColor(0x8a, 0x6f, 0x1e))
    p.fillRect(QRect(0, H - 4, W, 4), QColor(0x8a, 0x6f, 0x1e))


def _draw_bg(p: QPainter, name: str):
    """Draw a v2 full-screen background scaled 0.5x nearest-neighbour, else the
    procedural stone backdrop."""
    bg = art(name, _ART2)
    if bg:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawPixmap(QRect(0, 0, W, H), bg)
    else:
        _draw_backdrop(p)


class MainMenuScreen(QWidget):
    """The original baked title art (screen_main_menu.png — logo + New/Load/
    Options/Exit drawn into the pixels) with invisible hotspots over the buttons.
    Kept as-is: the user likes this screen. Only the *later* screens are custom."""

    # fractional hotspots (x0,y0,x1,y1) over the drawn buttons — DPI-independent
    HOTSPOTS = [
        ("new", 0.38, 0.33, 0.63, 0.45),
        ("load", 0.38, 0.47, 0.63, 0.59),
        ("options", 0.38, 0.61, 0.63, 0.73),
        ("exit", 0.38, 0.75, 0.63, 0.87),
    ]

    picked = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setFixedSize(W, H)
        self.setMouseTracking(True)
        self._bg = art("screen_main_menu.png")
        self._hover = -1

    def _rects(self) -> list[tuple[str, QRect]]:
        out = []
        for name, x0, y0, x1, y1 in self.HOTSPOTS:
            out.append((name, QRect(int(x0 * W), int(y0 * H),
                                    int((x1 - x0) * W), int((y1 - y0) * H))))
        return out

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        if self._bg:
            p.drawPixmap(self.rect(), self._bg)
        if 0 <= self._hover < len(self.HOTSPOTS):
            _, r = self._rects()[self._hover]
            pressed = self.property("pressed") is True
            p.fillRect(r, QColor(255, 255, 255, 50 if pressed else 28))

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        hover = -1
        for i, (_n, r) in enumerate(self._rects()):
            if r.contains(pos):
                hover = i
                break
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover >= 0
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def mousePressEvent(self, e):
        if self._hover >= 0:
            self.setProperty("pressed", True)
            self.update()

    def mouseReleaseEvent(self, e):
        self.setProperty("pressed", False)
        pos = e.position().toPoint()
        for name, r in self._rects():
            if r.contains(pos):
                self.picked.emit(name)
                break
        self.update()

    def leaveEvent(self, _e):
        if self._hover != -1:
            self._hover = -1
            self.update()


class ImageButton(QPushButton):
    """QPushButton that paints a pixmap (dimmed when disabled). Falls back to a
    styled text button when the art is missing."""

    def __init__(self, pixmap_name: str, fallback: str, parent: QWidget,
                 folder: Path = _ART):
        super().__init__(parent)
        self._pm = art(pixmap_name, folder)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._pm:
            self.setStyleSheet("QPushButton { border:none; background:transparent; }")
        else:
            self.setText(fallback)
            self.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
            self.setStyleSheet(
                "QPushButton { background:#1a1714; color:#e8d5a0; border:2px solid #c9a227; }"
                "QPushButton:disabled { color:#6a5a3a; border-color:#3a3226; }")

    def paintEvent(self, e):
        if not self._pm:
            return super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.setOpacity(1.0 if self.isEnabled() else 0.4)
        p.drawPixmap(self.rect(), self._pm)


class TextFrameButton(QPushButton):
    """Procedurally-drawn framed text button — dark plate + full double gold
    border (never clipped), gold text, hover-brighten, dim when disabled. Used
    where a baked RGB button art would get its border cut off when stretched."""

    def __init__(self, text: str, parent: QWidget):
        super().__init__(parent)
        self._text = text
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def set_text(self, text: str):
        self._text = text
        self.update()

    def enterEvent(self, _e):
        self._hover = True
        self.update()

    def leaveEvent(self, _e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        enabled = self.isEnabled()
        r = self.rect().adjusted(1, 1, -2, -2)
        plate = QColor(0x24, 0x1d, 0x14) if (self._hover and enabled) else QColor(0x1a, 0x17, 0x14)
        p.fillRect(r, plate)
        border = GOLD_BORDER if enabled else QColor(0x3a, 0x32, 0x26)
        pen = QPen(border)
        pen.setWidth(2)
        p.setPen(pen)
        p.drawRect(r)
        p.drawRect(r.adjusted(3, 3, -3, -3))
        p.setFont(QFont(FONT_FAMILY, 14, QFont.Weight.Bold))
        p.setPen(QColor(GOLD) if enabled else QColor(0x6a, 0x5a, 0x3a))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


class Banner(QWidget):
    """Procedural title plate: dark bar + double gold border + centred gold text.
    We draw it ourselves rather than reuse banner_title_frame.png because that art
    has the words 'LOAD ADVENTURE' baked into its pixels — unusable as a generic
    frame for other screens."""

    BW, BH = 620, 92

    def __init__(self, text: str, y: int, parent: QWidget):
        super().__init__(parent)
        self._text = text
        self.setGeometry((W - self.BW) // 2, y, self.BW, self.BH)

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect().adjusted(2, 2, -2, -2)
        p.fillRect(r, QColor(0x14, 0x11, 0x0e))
        pen = QPen(GOLD_BORDER)
        pen.setWidth(2)
        p.setPen(pen)
        p.drawRect(r)
        p.setPen(QColor(0x8a, 0x6f, 0x1e))
        p.drawRect(r.adjusted(4, 4, -4, -4))
        p.setFont(QFont(FONT_FAMILY, 22, QFont.Weight.Bold))
        p.setPen(QColor(GOLD))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


class ClassTile(QWidget):
    """Framed class icon with name beneath. Border is drawn procedurally in three
    states (idle grey / hover gold / selected thick gold) so it never depends on
    a baked-in frame and stays identical for every class regardless of the source
    icon's exact pixel height (e.g. cleric art is 258x257, one short)."""

    clicked = pyqtSignal(str)

    BOX = 128
    PAD = 6  # gap between frame and image so the border is always fully visible

    def __init__(self, class_id: str, name: str, parent=None):
        super().__init__(parent)
        self.class_id = class_id
        self.class_name = name
        self.selected = False
        self._hover = False
        self.setFixedSize(150, 176)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._icon = art(f"class_{class_id}.png")
        if self._icon is None:
            self._icon = art(f"{class_id}.png", _PORTRAITS)

    def set_selected(self, on: bool):
        if on != self.selected:
            self.selected = on
            self.update()

    def enterEvent(self, _e):
        self._hover = True
        self.update()

    def leaveEvent(self, _e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        box = self.BOX
        x = (self.width() - box) // 2
        y = 6
        frame = QRect(x, y, box, box)
        # dark plate behind the icon so the border reads on every class
        p.fillRect(frame, QColor(0x14, 0x11, 0x0e))
        if self._icon:
            inner = frame.adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
            p.drawPixmap(inner, self._icon)
        # procedural border: always drawn, colour/width by state
        if self.selected:
            pen = QPen(GOLD_BORDER)
            pen.setWidth(3)
            p.setPen(pen)
            p.drawRect(frame)
            p.drawRect(frame.adjusted(3, 3, -3, -3))
        elif self._hover:
            pen = QPen(GOLD_BORDER)
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(frame)
        else:
            pen = QPen(QColor(0x6a, 0x57, 0x2f))
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(frame)
        p.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.Bold))
        p.setPen(QColor(GOLD) if (self.selected or self._hover) else QColor(0xb8, 0xa8, 0x78))
        p.drawText(QRect(0, y + box + 4, self.width(), 28),
                   Qt.AlignmentFlag.AlignHCenter, self.class_name)

    def mouseReleaseEvent(self, _e):
        self.clicked.emit(self.class_id)


class NewCharacterScreen(QWidget):
    """OUR 5 classes on the v2 night-camp background: class tiles up top, an
    optional name field + confirm in a dark panel on the left, live class info in
    a dark panel on the right — the central campfire is kept clear."""

    confirmed = pyqtSignal(str, str)  # class_id, name ("" -> make_hero uses class name)
    back = pyqtSignal()

    # semi-transparent panels flanking the campfire (don't cover the centre glow)
    LEFT_PANEL = QRect(40, 356, 430, 300)
    RIGHT_PANEL = QRect(906, 356, 430, 300)

    def __init__(self):
        super().__init__()
        self.setFixedSize(W, H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._sel: str | None = None
        Banner("CHARACTER SELECTION", 22, self)

        # class tiles: 5 across, centred, up high over the tents (dark art)
        self._tiles: list[ClassTile] = []
        ids = list(classes.CLASSES.items())
        tile_w, gap = 150, 16
        total = len(ids) * tile_w + (len(ids) - 1) * gap
        x0 = (W - total) // 2
        for i, (cid, cdef) in enumerate(ids):
            t = ClassTile(cid, cdef.name, self)
            t.move(x0 + i * (tile_w + gap), 140)
            t.clicked.connect(self._select)
            self._tiles.append(t)

        # left panel: name field + confirm
        self._name_lbl = QLabel("Name (optional):", self)
        self._name_lbl.setGeometry(self.LEFT_PANEL.x() + 24, self.LEFT_PANEL.y() + 26, 380, 26)
        self._name_lbl.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.Bold))
        self._name_lbl.setStyleSheet(f"color:{GOLD}; background:transparent;")

        self._name = QLineEdit(self)
        self._name.setGeometry(self.LEFT_PANEL.x() + 24, self.LEFT_PANEL.y() + 58, 380, 44)
        self._name.setMaxLength(24)
        self._name.setPlaceholderText("Named after class if blank")
        self._name.setFont(QFont(FONT_FAMILY, 13))
        self._name.setStyleSheet(
            "QLineEdit { background:#14110e; color:#e8d5a0; border:2px solid #c9a227;"
            " padding:4px 8px; selection-background-color:#6b5122; }")

        self._confirm = TextFrameButton("CONFIRM CHARACTER", self)
        self._confirm.setGeometry(self.LEFT_PANEL.x() + 55, self.LEFT_PANEL.y() + 176, 320, 58)
        self._confirm.clicked.connect(self._do_confirm)

        # right panel: live class info
        self._info = QLabel(self)
        self._info.setGeometry(self.RIGHT_PANEL.x() + 20, self.RIGHT_PANEL.y() + 20,
                               self.RIGHT_PANEL.width() - 40, self.RIGHT_PANEL.height() - 40)
        self._info.setWordWrap(True)
        self._info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._info.setFont(QFont(FONT_FAMILY, 12))
        self._info.setStyleSheet(f"color:{GOLD}; background:transparent;")
        self._info.setText("Choose a class.")

        self._sync_confirm()

    def _select(self, class_id: str):
        self._sel = class_id
        for t in self._tiles:
            t.set_selected(t.class_id == class_id)
        cdef = classes.CLASSES[class_id]
        role = {"warrior": "Melee tank", "barbarian": "Melee bruiser",
                "archer": "Ranged", "mage": "Ranged caster",
                "cleric": "Medium range"}.get(class_id, "")
        self._info.setText(f"<b>{cdef.name}</b> — {role}<br><br>{cdef.description}")
        self._sync_confirm()

    def _sync_confirm(self):
        self._confirm.setEnabled(bool(self._sel))
        self._confirm.update()

    def _do_confirm(self):
        if self._sel:
            self.confirmed.emit(self._sel, self._name.text().strip())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.back.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        _draw_bg(p, "screen_charselect_bg.png")
        # semi-transparent dark panels flanking the campfire
        for panel in (self.LEFT_PANEL, self.RIGHT_PANEL):
            p.fillRect(panel, QColor(0x0d, 0x0a, 0x08, 205))
            pen = QPen(GOLD_BORDER)
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(panel.adjusted(1, 1, -1, -1))


def _iter_saves() -> list[dict]:
    """Real saves from saves/*.json (skip _test/trash), newest first.
    Only per-character slots are listed: their stem always ends in a 6-hex
    sha1 suffix (see main._slot_path). Legacy phantoms without it — the old
    single-file 'save.json' and pre-hash 'warrior_warrior.json' — are ignored
    so they can't offer a parallel-progress trap in the Load screen."""
    out = []
    if not os.path.isdir(SAVE_DIR):
        return out
    for fn in os.listdir(SAVE_DIR):
        if not fn.endswith(".json") or fn.startswith("_"):
            continue
        if not re.search(r"_[0-9a-f]{6}\.json$", fn):
            continue  # legacy slot without the per-name hash suffix
        path = os.path.join(SAVE_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        hero = d.get("hero", {})
        meta = d.get("meta", {})
        out.append({
            "path": path, "file": fn,
            "class_id": hero.get("class_id", "?"),
            "level": hero.get("level", 1),
            "name": hero.get("name", "Exile"),
            "zone_id": meta.get("zone_id", ""),
            "playtime": meta.get("playtime", 0.0),
            "saved_at": d.get("saved_at") or meta.get("saved_at") or 0.0,
        })
    out.sort(key=lambda s: s.get("saved_at") or 0.0, reverse=True)
    return out


def _abs_time(epoch: float | None) -> str:
    """epoch seconds -> 'YYYY-MM-DD HH:MM' for the 'Last Played:' bar."""
    if not epoch:
        return "never"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(epoch)))
    except (ValueError, TypeError, OSError):
        return "unknown"


class LoadGameScreen(QWidget):
    """The v2 screen_load_full.png used as a full baked background (3 slot rows +
    per-row door/skull buttons + bottom NEW CHARACTER/SETTINGS/BACK bar). We only
    overlay DYNAMIC per-save text/portraits and place invisible hotspots over the
    baked buttons (instance-patching paint on the JPEG-derived art is a no-go)."""

    load_save = pyqtSignal(str)   # path
    delete_save = pyqtSignal(str)
    new_char = pyqtSignal()
    open_settings = pyqtSignal()
    back = pyqtSignal()

    ROW_TOP0 = 186
    ROW_DY = 164
    N_SLOTS = 3

    # bottom baked buttons (read off the art with a coordinate grid)
    BTN_NEW = QRect(384, 702, 262, 42)
    BTN_SETTINGS = QRect(660, 702, 172, 42)
    BTN_BACK = QRect(864, 702, 116, 42)

    def __init__(self):
        super().__init__()
        self.setFixedSize(W, H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._saves: list[dict] = []
        self._sel = -1
        self._hover_btn = ""  # "", "new", "settings", "back", "load:i", "del:i"

    # --- hotspot geometry -------------------------------------------------
    def _row_top(self, i: int) -> int:
        return self.ROW_TOP0 + i * self.ROW_DY

    def _row_rect(self, i: int) -> QRect:
        return QRect(168, self._row_top(i), 1044, 150)

    def _door_rect(self, i: int) -> QRect:
        return QRect(1053, self._row_top(i) + 27, 66, 62)

    def _skull_rect(self, i: int) -> QRect:
        return QRect(1127, self._row_top(i) + 27, 66, 62)

    def refresh(self):
        self._saves = _iter_saves()
        self._sel = 0 if self._saves else -1
        self.update()

    # --- painting ---------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        _draw_bg(p, "screen_load_full.png")
        for i in range(self.N_SLOTS):
            top = self._row_top(i)
            row = self._row_rect(i)
            if i < len(self._saves):
                self._paint_save(p, i, top)
            else:
                # empty baked slot -> dim + centred prompt
                p.fillRect(row, QColor(0, 0, 0, 120))
                p.setFont(QFont(FONT_FAMILY, 15, QFont.Weight.Bold))
                p.setPen(QColor(0x9a, 0x8a, 0x6a))
                p.drawText(row, Qt.AlignmentFlag.AlignCenter, "— empty —")
            # selection / hover highlight on the row
            if i == self._sel and i < len(self._saves):
                pen = QPen(GOLD_BORDER)
                pen.setWidth(3)
                p.setPen(pen)
                p.drawRect(row.adjusted(1, 1, -1, -1))
        # button hover glow (over baked buttons)
        self._paint_btn_hover(p)

    def _paint_save(self, p: QPainter, i: int, top: int):
        s = self._saves[i]
        cdef = classes.CLASSES.get(s["class_id"])
        cname = cdef.name if cdef else s["class_id"]
        # portrait, aspect-fit & centred in the baked frame opening. The frame's
        # inner hole is ~116x117 centred at widget (236, top+73); the portrait PNGs
        # are non-square runic medallions (~0.93:1), so fitting them into a square
        # box would squash the circle and shove it off-centre. Scale to fit while
        # keeping aspect, then centre inside the opening.
        icon = art(f"{s['class_id']}.png", _PORTRAITS)
        if icon:
            OPEN_CX, OPEN_CY, OPEN = 236, top + 73, 112  # inner opening (square-ish)
            iw, ih = icon.width(), icon.height()
            scale = OPEN / max(iw, ih)
            dw, dh = round(iw * scale), round(ih * scale)
            pbox = QRect(OPEN_CX - dw // 2, OPEN_CY - dh // 2, dw, dh)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.drawPixmap(pbox, icon)
        # hero name + level/class + zone (outlined pixel text)
        p.setFont(QFont(FONT_FAMILY, 18, QFont.Weight.Bold))
        _draw_text_outlined(p, 335, top + 52, s["name"], QColor(GOLD))
        p.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
        _draw_text_outlined(p, 335, top + 82, f"Lvl {s['level']}  {cname}", QColor(GOLD))
        zone = s["zone_id"].replace("_", " ").title()
        if zone:
            p.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.Bold))
            _draw_text_outlined(p, 335, top + 106, zone, ZONE_GOLD)
        # info bar values — matched to the baked 'Last Played:' / 'Total Playtime:'
        # labels: same tan, same Verdana-bold-18 size, sitting on the baked
        # baseline (widget y = top+133). The baked labels already read
        # 'Last Played:' (ends ~x449) and 'Total Playtime:' (ends ~x545 widget),
        # so we only append the dynamic value after each colon.
        BASE = top + 133
        p.setFont(QFont(FONT_FAMILY, 18, QFont.Weight.Bold))
        p.setPen(INFO_TAN)
        p.drawText(462, BASE, _abs_time(s["saved_at"]))
        # cover the baked '--h --m --s' placeholder (value only, after the colon).
        # The band has a vertical gradient, so a flat fill leaves a visible seam —
        # instead we blit a clean slice of the band texture straight from the
        # source art (the empty gap between the two labels, same row & y, so the
        # gradient matches pixel-for-pixel), then draw the real value over it.
        bg = art("screen_load_full.png", _ART2)
        cover = QRect(1090, top + 104, 112, 44)     # value region, y padded past descenders
        if bg:
            sx = 2  # art is 2x the widget
            src_clean_x = 600                        # clean band gap between the labels
            src = QRect(src_clean_x * sx, cover.y() * sx, cover.width() * sx, cover.height() * sx)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.drawPixmap(cover, bg, src)
        else:
            p.fillRect(cover, BAR_FILL)
        mins = int(s["playtime"] // 60)
        p.setPen(INFO_TAN)
        p.drawText(1095, BASE, f"{mins // 60}h {mins % 60}m")

    def _paint_btn_hover(self, p: QPainter):
        rects = {"new": self.BTN_NEW, "settings": self.BTN_SETTINGS, "back": self.BTN_BACK}
        for i in range(self.N_SLOTS):
            rects[f"load:{i}"] = self._door_rect(i)
            rects[f"del:{i}"] = self._skull_rect(i)
        r = rects.get(self._hover_btn)
        if r is not None:
            p.fillRect(r, QColor(255, 255, 255, 30))

    # --- interaction ------------------------------------------------------
    def _hit(self, pos) -> str:
        if self.BTN_NEW.contains(pos):
            return "new"
        if self.BTN_SETTINGS.contains(pos):
            return "settings"
        if self.BTN_BACK.contains(pos):
            return "back"
        for i in range(self.N_SLOTS):
            if self._door_rect(i).contains(pos):
                return f"load:{i}"
            if self._skull_rect(i).contains(pos):
                return f"del:{i}"
        return ""

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        hb = self._hit(pos)
        if hb != self._hover_btn:
            self._hover_btn = hb
            cur = Qt.CursorShape.PointingHandCursor
            if not hb:
                # rows are still clickable to select
                for i in range(self.N_SLOTS):
                    if self._row_rect(i).contains(pos):
                        break
                else:
                    cur = Qt.CursorShape.ArrowCursor
            self.setCursor(cur)
            self.update()

    def mouseReleaseEvent(self, e):
        pos = e.position().toPoint()
        hb = self._hit(pos)
        if hb == "new":
            self.new_char.emit()
            return
        if hb == "settings":
            self.open_settings.emit()
            return
        if hb == "back":
            self.back.emit()
            return
        if hb.startswith("load:"):
            i = int(hb.split(":")[1])
            if i < len(self._saves):
                self._sel = i
                self.load_save.emit(self._saves[i]["path"])
            return
        if hb.startswith("del:"):
            i = int(hb.split(":")[1])
            if i < len(self._saves):
                self.delete_save.emit(self._saves[i]["path"])
            return
        # click on a row body: select filled row, or empty row -> new character
        for i in range(self.N_SLOTS):
            if self._row_rect(i).contains(pos):
                if i < len(self._saves):
                    if self._sel == i:
                        self.load_save.emit(self._saves[i]["path"])
                    else:
                        self._sel = i
                        self.update()
                else:
                    self.new_char.emit()
                return

    def leaveEvent(self, _e):
        if self._hover_btn:
            self._hover_btn = ""
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.back.emit()


class SettingsScreen(QWidget):
    """Settings on the v2 ruins background. Two columns: sliders (sound/music
    volume, strip scale) on the left; stub toggles (damage numbers, screen shake,
    always on top, start with Windows) and an FPS-cap cycle button on the right.
    All values persist to saves/settings.json (loaded on open, saved on every
    change); only volume/strip_scale are consumed by the game yet — the rest are
    mock-ups wired for the future."""

    back = pyqtSignal()

    FPS_CHOICES = (30, 60)

    PANEL = QRect(int(0.18 * W), 150, int(0.64 * W), 468)

    def __init__(self):
        super().__init__()
        self.setFixedSize(W, H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._settings = load_settings()
        Banner("SETTINGS", 40, self)

        # two columns inside the panel
        colw = self.PANEL.width() // 2 - 80
        lx = self.PANEL.x() + 48
        rx = self.PANEL.x() + self.PANEL.width() // 2 + 32
        label_css = f"color:{GOLD}; background:transparent;"
        slider_css = (
            "QSlider::groove:horizontal { height:8px; background:#14110e;"
            " border:1px solid #6a572f; }"
            "QSlider::sub-page:horizontal { background:#8a6f1e; }"
            "QSlider::handle:horizontal { width:16px; margin:-6px 0; background:#e8d5a0;"
            " border:1px solid #c9a227; }")
        checkbox_css = (
            "QCheckBox { color:#e8d5a0; background:transparent; }"
            "QCheckBox::indicator { width:20px; height:20px; background:#14110e;"
            " border:2px solid #c9a227; }"
            "QCheckBox::indicator:checked { background:#8a6f1e; }")

        def mk_slider(y: int, lo: int, hi: int, value: int, cb) -> tuple[QLabel, QSlider]:
            lbl = QLabel(self)
            lbl.setGeometry(lx, self.PANEL.y() + y, colw, 26)
            lbl.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
            lbl.setStyleSheet(label_css)
            s = QSlider(Qt.Orientation.Horizontal, self)
            s.setGeometry(lx, self.PANEL.y() + y + 32, colw, 28)
            s.setRange(lo, hi)
            s.setValue(value)
            s.setStyleSheet(slider_css)
            s.valueChanged.connect(cb)
            return lbl, s

        def mk_check(y: int, text: str, checked: bool, cb) -> QCheckBox:
            c = QCheckBox(text, self)
            c.setGeometry(rx, self.PANEL.y() + y, colw, 30)
            c.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
            c.setChecked(checked)
            c.setStyleSheet(checkbox_css)
            c.toggled.connect(cb)
            return c

        # left column: sliders
        self._vol_lbl, self._vol = mk_slider(
            40, 0, 100, int(self._settings["volume"]), self._on_vol)
        self._music_lbl, self._music = mk_slider(
            132, 0, 100, int(self._settings["music_volume"]), self._on_music)
        self._scale_lbl, self._scale = mk_slider(
            224, 50, 200, int(self._settings["strip_scale"]), self._on_scale)

        # right column: stub toggles + fps cap
        self._dmg = mk_check(40, "Show damage numbers",
                             bool(self._settings["show_damage_numbers"]), self._on_dmg)
        self._shake = mk_check(84, "Screen shake",
                               bool(self._settings["screen_shake"]), self._on_shake)
        self._ontop = mk_check(128, "Always on top",
                               bool(self._settings["always_on_top"]), self._on_ontop)
        self._start = mk_check(172, "Start with Windows",
                               bool(self._settings["start_with_windows"]), self._on_start)

        if self._settings["fps_cap"] not in self.FPS_CHOICES:
            self._settings["fps_cap"] = DEFAULT_SETTINGS["fps_cap"]
        self._fps_btn = TextFrameButton("", self)
        self._fps_btn.setGeometry(rx, self.PANEL.y() + 224, 220, 48)
        self._fps_btn.clicked.connect(self._on_fps)

        # back
        self._back_btn = TextFrameButton("BACK", self)
        self._back_btn.setGeometry(self.PANEL.center().x() - 90, self.PANEL.bottom() - 66, 180, 52)
        self._back_btn.clicked.connect(self.back.emit)

        self._refresh_labels()

    def _refresh_labels(self):
        self._vol_lbl.setText(f"Sound volume: {self._vol.value()}")
        self._music_lbl.setText(f"Music volume: {self._music.value()}")
        self._scale_lbl.setText(f"Strip scale: {self._scale.value()}%")
        self._fps_btn.set_text(f"FPS CAP: {self._settings['fps_cap']}")

    def _persist(self):
        save_settings(self._settings)

    def _on_vol(self, v):
        self._settings["volume"] = v
        self._refresh_labels()
        self._persist()

    def _on_music(self, v):
        self._settings["music_volume"] = v
        self._refresh_labels()
        self._persist()

    def _on_scale(self, v):
        self._settings["strip_scale"] = v
        self._refresh_labels()
        self._persist()

    def _on_dmg(self, on):
        self._settings["show_damage_numbers"] = bool(on)
        self._persist()

    def _on_shake(self, on):
        self._settings["screen_shake"] = bool(on)
        self._persist()

    def _on_ontop(self, on):
        self._settings["always_on_top"] = bool(on)
        self._persist()

    def _on_start(self, on):
        self._settings["start_with_windows"] = bool(on)
        self._persist()

    def _on_fps(self):
        cur = self._settings["fps_cap"]
        i = self.FPS_CHOICES.index(cur) if cur in self.FPS_CHOICES else 0
        self._settings["fps_cap"] = self.FPS_CHOICES[(i + 1) % len(self.FPS_CHOICES)]
        self._refresh_labels()
        self._persist()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.back.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        _draw_bg(p, "screen_settings_bg.png")
        p.fillRect(self.PANEL, QColor(0x0d, 0x0a, 0x08, 210))
        pen = QPen(GOLD_BORDER)
        pen.setWidth(2)
        p.setPen(pen)
        p.drawRect(self.PANEL.adjusted(1, 1, -1, -1))


class Launcher(QStackedWidget):
    """Launcher hub. Emits new_hero(class_id, name) or load_hero(path). Screens:
    main menu -> character select / load / settings."""

    new_hero = pyqtSignal(str, str)
    load_hero = pyqtSignal(str)
    options = pyqtSignal()  # kept for interface stability (main menu 'options')

    def __init__(self):
        super().__init__()
        self.setFixedSize(W, H)
        self.setWindowTitle("Bar of Exile")
        self.menu = MainMenuScreen()
        self.newchar = NewCharacterScreen()
        self.loadscr = LoadGameScreen()
        self.settings = SettingsScreen()
        for w in (self.menu, self.newchar, self.loadscr, self.settings):
            self.addWidget(w)

        self.menu.picked.connect(self._on_menu)
        self.newchar.confirmed.connect(self._on_confirm)
        self.newchar.back.connect(self._go_menu)
        self.loadscr.load_save.connect(self._on_load)
        self.loadscr.delete_save.connect(self._on_delete)
        self.loadscr.new_char.connect(lambda: self._show(self.newchar))
        self.loadscr.open_settings.connect(self._go_settings)
        self.loadscr.back.connect(self._go_menu)
        self.settings.back.connect(self._go_menu)

        scr = self.screen().availableGeometry() if self.screen() else None
        if scr:
            self.move(scr.center().x() - W // 2, scr.center().y() - H // 2)

    def _show(self, w: QWidget):
        self.setCurrentWidget(w)
        w.setFocus()

    def _go_menu(self):
        self._show(self.menu)

    def _go_settings(self):
        self.settings._settings = load_settings()
        self._show(self.settings)

    def _on_menu(self, name: str):
        if name == "new":
            self._show(self.newchar)
        elif name == "load":
            self.loadscr.refresh()
            self._show(self.loadscr)
        elif name == "options":
            self._go_settings()
        elif name == "exit":
            self.close()

    def _on_confirm(self, class_id: str, name: str):
        self.new_hero.emit(class_id, name)

    def _on_load(self, path: str):
        self.load_hero.emit(path)

    def _on_delete(self, path: str):
        trash = os.path.join(SAVE_DIR, "trash")
        os.makedirs(trash, exist_ok=True)
        try:
            os.replace(path, os.path.join(trash, os.path.basename(path)))
        except OSError:
            pass
        self.loadscr.refresh()


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    lz = Launcher()
    lz.new_hero.connect(lambda c, n: print("new:", c, n) or app.quit())
    lz.load_hero.connect(lambda p: print("load:", p) or app.quit())
    lz.show()
    sys.exit(app.exec())
