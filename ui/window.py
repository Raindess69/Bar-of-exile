"""Bar of Exile — taskbar strip window. Pure shell: game logic hooks in via callbacks."""
from __future__ import annotations

import time
import traceback
from collections import deque
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QRect
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon, QFont, QAction
from PyQt6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu, QToolTip

STRIP_H = 64
CHEVRON_W = 28   # narrow full-height column for the menu collapse chevron
GRID_COLS = 6    # 12 menu buttons laid out as 6 cols x 2 rows (important on top)
BTN_ZONE = CHEVRON_W + GRID_COLS * 44  # 336; imported by main.py
FLASH_TIME = 3.0
FLASH_QUEUE_CAP = 4  # pending flash messages beyond the one on screen
BUTTONS = [
    ("▶", "panel", "Collapse menu"),  # label/tip are dynamic, see _chevron()
    ("I", "inventory", "Inventory"),
    ("S", "stash", "Stash"),
    ("C", "character", "Character"),
    ("K", "skills", "Skills"),
    ("T", "tree", "Passive Tree"),
    ("U", "cube", "Transmutation Cube"),
    ("V", "vendor", "Vendor"),
    ("G", "gamble", "Ferek's Game of Certainties"),
    ("X", "stats", "Statistics"),
    ("Z", "zones", "Zones"),
    ("▁", "hide", "Hide"),
    ("✕", "quit", "Quit"),
]

_BTN_DIR = Path(__file__).resolve().parent.parent / "assets" / "ui" / "buttons"
_BTN_FILES = {
    "inventory": "btn_inventory", "stash": "btn_stash", "character": "btn_character",
    "skills": "btn_skills", "tree": "btn_tree", "cube": "btn_cube", "vendor": "btn_vendor",
    "gamble": "btn_gamble", "stats": "btn_stats",
    "zones": "btn_zones", "hide": "btn_minimize", "quit": "btn_close",
}
_btn_pixmaps: dict[str, QPixmap | None] = {}


def _btn_pixmap(name: str, hover: bool, size: int) -> QPixmap | None:
    key = f"{name}:{hover}:{size}"
    if key not in _btn_pixmaps:
        base = _BTN_FILES.get(name)
        pm = None
        if base:
            path = _BTN_DIR / (f"{base}_hover.png" if hover else f"{base}.png")
            if not path.exists():
                path = _BTN_DIR / f"{base}.png"
            raw = QPixmap(str(path)) if path.exists() else QPixmap()
            if not raw.isNull():
                pm = raw.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        _btn_pixmaps[key] = pm
    return _btn_pixmaps[key]


def _make_tray_icon() -> QIcon:
    pm = QPixmap(16, 16)
    pm.fill(QColor(180, 30, 30))
    p = QPainter(pm)
    p.setPen(QPen(QColor(255, 220, 60), 2))
    p.drawLine(3, 13, 12, 4)
    p.setPen(QPen(QColor(255, 220, 60), 1))
    p.drawLine(4, 8, 8, 12)
    p.end()
    return QIcon(pm)


class TaskbarStrip(QWidget):
    def __init__(self, paint_cb, tick_cb, click_cb):
        super().__init__()
        self.paint_cb = paint_cb
        self.tick_cb = tick_cb
        self.click_cb = click_cb
        self.on_button = None

        self._hover_btn = -1
        self._menu_collapsed = False
        self._button_alerts: set[str] = set()
        self._drag_offset_y: int | None = None
        self._flash_text = ""
        self._flash_left = 0.0
        self._flash_queue: deque[str] = deque()  # pending texts, cap 4
        self._last_tick = time.perf_counter()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._place()
        self._setup_tray()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(33)

    def _place(self) -> None:
        geo = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(geo.x(), geo.y() + geo.height() - STRIP_H, geo.width(), STRIP_H)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(_make_tray_icon(), self)
        self.tray.setToolTip("Bar of Exile")
        menu = QMenu()
        act_toggle = QAction("Show/Hide", menu)
        act_toggle.triggered.connect(self.toggle_visible)
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(lambda: self._fire_button("quit"))
        menu.addAction(act_toggle)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _on_tray(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()

    def toggle_visible(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def flash_notify(self, text: str) -> None:
        if self._flash_left <= 0 and not self._flash_queue:
            self._flash_text = text
            self._flash_left = FLASH_TIME
            self.update()
            return
        last = self._flash_queue[-1] if self._flash_queue else self._flash_text
        if text == last:  # dedup back-to-back repeats
            return
        if len(self._flash_queue) >= FLASH_QUEUE_CAP:
            self._flash_queue.popleft()  # drop oldest pending; on-screen text is untouched
        self._flash_queue.append(text)

    def _fire_button(self, name: str) -> None:
        if self.on_button:
            try:
                self.on_button(name)
            except Exception:
                print("on_button error:")
                traceback.print_exc()
        elif name == "hide":
            self.hide()
        elif name == "quit":
            QApplication.instance().quit()

    def set_panel_chevron(self, expanded: bool) -> None:
        pass  # no-op stub: chevron now toggles menu collapse internally; kept so main.py calls don't crash

    def _chevron(self) -> tuple[str, str]:
        """(label, tooltip) for the menu chevron depending on collapse state."""
        if self._menu_collapsed:
            return "◀", "Expand menu"
        return "▶", "Collapse menu"

    def effective_btn_zone(self) -> int:
        """Current width of the button zone: chevron only when menu is collapsed."""
        return CHEVRON_W if self._menu_collapsed else BTN_ZONE

    def set_button_alert(self, name: str, on: bool) -> None:
        """Toggle a red alert frame on the named button (e.g. inventory full)."""
        changed = (name in self._button_alerts) != on
        if on:
            self._button_alerts.add(name)
        else:
            self._button_alerts.discard(name)
        if changed:
            self.update()

    def _btn_rects(self) -> list[QRect]:
        """Rects aligned 1:1 with BUTTONS. Chevron = narrow full-height column,
        the other 12 buttons form a symmetric 6x2 grid; grid rects are empty when collapsed."""
        h = self.height()
        x0 = self.width() - self.effective_btn_zone()
        cell_w = (BTN_ZONE - CHEVRON_W) // GRID_COLS
        cell_h = h // 2
        rects: list[QRect] = []
        gi = 0
        for _label, name, _tip in BUTTONS:
            if name == "panel":
                rects.append(QRect(x0, 0, CHEVRON_W, h))
            elif self._menu_collapsed:
                rects.append(QRect())
            else:
                row, col = divmod(gi, GRID_COLS)
                rects.append(QRect(x0 + CHEVRON_W + col * cell_w, row * cell_h, cell_w, cell_h))
                gi += 1
        return rects

    def _on_tick(self) -> None:
        now = time.perf_counter()
        dt = now - self._last_tick
        self._last_tick = now
        if self._flash_left > 0:
            self._flash_left = max(0.0, self._flash_left - dt)
        if self._flash_left <= 0 and self._flash_queue:
            self._flash_text = self._flash_queue.popleft()
            self._flash_left = FLASH_TIME
        try:
            self.tick_cb(dt)
        except Exception:
            print("tick_cb error:")
            traceback.print_exc()
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        zone = self.effective_btn_zone()
        p.fillRect(0, 0, w, h, QColor(10, 10, 14, 235))

        p.save()
        p.setClipRect(0, 0, w - zone, h)
        try:
            self.paint_cb(p, w - zone, h)
        except Exception:
            print("paint_cb error:")
            traceback.print_exc()
        p.restore()

        rects = self._btn_rects()
        p.setPen(QPen(QColor(60, 60, 70), 1))
        p.drawLine(w - zone, 4, w - zone, h - 4)
        font = QFont("Segoe UI", 11)
        font.setBold(True)
        p.setFont(font)
        chevron_label, _ = self._chevron()
        for i, (label, name, tip) in enumerate(BUTTONS):
            r = rects[i]
            if r.isEmpty():
                continue
            if name == "panel":
                label = chevron_label
            hover = i == self._hover_btn
            pm = _btn_pixmap(name, hover, min(r.width() - 4, r.height() - 4))
            if pm is not None:
                if hover and not (_BTN_DIR / f"{_BTN_FILES[name]}_hover.png").exists():
                    p.fillRect(r.adjusted(1, 2, -1, -2), QColor(255, 255, 255, 35))
                p.drawPixmap(r.x() + (r.width() - pm.width()) // 2,
                             r.y() + (r.height() - pm.height()) // 2, pm)
            else:
                if hover:
                    p.fillRect(r.adjusted(1, 2, -1, -2), QColor(255, 255, 255, 35))
                p.setPen(QColor(200, 200, 210) if not hover else QColor(255, 235, 150))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
            if name in self._button_alerts:
                p.fillRect(r.adjusted(1, 1, -1, -1), QColor(220, 60, 50, 40))
                p.setPen(QPen(QColor(220, 60, 50), 2))
                p.drawRect(r.adjusted(1, 1, -2, -2))

        if self._flash_left > 0 and self._flash_text:
            alpha = int(255 * min(1.0, self._flash_left / 1.0))
            font = QFont("Segoe UI", 14)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(0, 0, 0, alpha))
            area = QRect(1, 1, w - zone, h)
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, self._flash_text)
            p.setPen(QColor(255, 215, 80, alpha))
            area = QRect(0, 0, w - zone, h)
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, self._flash_text)
        p.end()

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()
        btn = event.button()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if btn == Qt.MouseButton.MiddleButton or (btn == Qt.MouseButton.LeftButton and ctrl):
            self._drag_offset_y = int(event.globalPosition().y()) - self.y()
            return
        if pos.x() >= self.width() - self.effective_btn_zone():
            for i, r in enumerate(self._btn_rects()):
                if not r.isEmpty() and r.contains(pos):
                    name = BUTTONS[i][1]
                    if name == "panel":  # handled internally: toggle menu collapse
                        self._menu_collapsed = not self._menu_collapsed
                        self._hover_btn = -1
                        self.update()
                    else:
                        self._fire_button(name)
                    return
            return
        name = {Qt.MouseButton.LeftButton: "left", Qt.MouseButton.RightButton: "right"}.get(btn)
        if name:
            try:
                self.click_cb(pos.x(), pos.y(), name)
            except Exception:
                print("click_cb error:")
                traceback.print_exc()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset_y is not None:
            self.move(self.x(), int(event.globalPosition().y()) - self._drag_offset_y)
            return
        pos = event.position().toPoint()
        hover = -1
        if pos.x() >= self.width() - self.effective_btn_zone():
            for i, r in enumerate(self._btn_rects()):
                if not r.isEmpty() and r.contains(pos):
                    hover = i
                    break
        if hover != self._hover_btn:
            self._hover_btn = hover
            if hover >= 0:
                tip = self._chevron()[1] if BUTTONS[hover][1] == "panel" else BUTTONS[hover][2]
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
            else:
                QToolTip.hideText()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset_y = None

    def leaveEvent(self, event) -> None:
        if self._hover_btn != -1:
            self._hover_btn = -1
            self.update()


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)

    def test_paint(p: QPainter, w: int, h: int) -> None:
        p.setPen(QColor(200, 200, 200))
        p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, f"game zone {w}x{h}")

    strip = TaskbarStrip(test_paint, lambda dt: None, lambda x, y, b: None)
    strip.show()
    strip.flash_notify("Level up!")
    for _ in range(10):
        strip._on_tick()

    # chevron column + symmetric 6x2 grid (12 menu buttons, two distinct y values)
    rects = strip._btn_rects()
    assert len(rects) == len(BUTTONS), f"expected {len(BUTTONS)} rects, got {len(rects)}"
    grid = [r for r in rects[1:] if not r.isEmpty()]
    assert len(grid) == 12, f"expected 12 grid rects, got {len(grid)}"
    grid_ys = {r.y() for r in grid}
    assert len(grid_ys) == 2, f"expected 2 grid rows, got y values {grid_ys}"
    top = [r for r in grid if r.y() == min(grid_ys)]
    bot = [r for r in grid if r.y() == max(grid_ys)]
    assert len(top) == len(bot) == 6, f"rows must be symmetric: top={len(top)} bot={len(bot)}"
    assert rects[0].width() == CHEVRON_W and rects[0].height() == strip.height()
    print(f"grid OK: BTN_ZONE={BTN_ZONE}, rows y={sorted(grid_ys)}, 6+6 symmetric")

    # collapse toggle changes effective zone width
    assert strip.effective_btn_zone() == BTN_ZONE
    strip._menu_collapsed = True
    assert strip.effective_btn_zone() == CHEVRON_W
    assert all(r.isEmpty() for r in strip._btn_rects()[1:])
    strip._menu_collapsed = False
    assert strip.effective_btn_zone() == BTN_ZONE
    print("collapse toggle OK")

    # alert API + legacy no-op stub
    strip.set_button_alert("inventory", True)
    strip.set_panel_chevron(True)
    strip._on_tick()

    # flash queue: 3 rapid notifies show in order, dedup drops repeats
    strip._flash_left = 0.0
    strip._flash_queue.clear()
    strip.flash_notify("Boss defeated!")
    strip.flash_notify("First kill! +3 passive points")
    strip.flash_notify("First kill! +3 passive points")  # dedup
    strip.flash_notify("Offline report: 42 kills")
    shown = [strip._flash_text]
    for _ in range(40):  # 40 * 0.5s fake dt covers 3 messages x 3s
        strip._last_tick -= 0.5
        strip._on_tick()
        if strip._flash_text != shown[-1]:
            shown.append(strip._flash_text)
    assert shown == ["Boss defeated!", "First kill! +3 passive points",
                     "Offline report: 42 kills"], f"flash order wrong: {shown}"
    assert not strip._flash_queue and strip._flash_left == 0.0
    print(f"flash queue OK: {shown}")

    pm = strip.grab()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_window_test.png")
    pm.save(out)
    g = strip.geometry()
    print(f"geometry: x={g.x()} y={g.y()} w={g.width()} h={g.height()}")
    print(f"saved: {out}")
    print("OK")
