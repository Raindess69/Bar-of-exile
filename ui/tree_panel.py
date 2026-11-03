"""Bar of Exile — passive tree panel v3: PoE-style, big viewport, pan/zoom, path preview."""
from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QPushButton, QToolTip,
                             QVBoxLayout, QWidget)

from game import tree
from game.core import Hero
from ui.panels import Panel, _hdr

HIT_SLOP_WU = 6                   # extra world units accepted around a node as a hit
CELL = 256                        # spatial hash cell, world units
ZOOM_MAX = 2.5
ZOOM_MIN_ABS = 0.4                # absolute floor unless fit-to-view needs less
DRAG_THRESHOLD = 4                # px of movement before a press becomes a pan
ICON_MIN_PX = 7                   # node screen radius below which icons are skipped

NODE_RADIUS_WU = {"class_start": 34, "small": 10, "notable": 17, "keystone": 24, "ck": 16}
KIND_LABEL = {"class_start": "Class Start", "small": "",
              "notable": "Notable", "keystone": "Keystone", "ck": "Class Keystone"}

BRANCH_ACCENT = {
    "warrior": "#c25a50",
    "mage": "#5f8fd6",
    "archer": "#63b268",
    "cleric": "#ded4b2",
    "barbarian": "#c87f3c",
}
NEUTRAL_ACCENT = "#9a8f7a"

COL_BG_EDGE = QColor("#07080a")
COL_BG_CENTER = QColor("#14171c")
COL_RING = QColor("#1b1f26")
COL_EDGE_DIM = QColor("#2a2e35")
COL_EDGE_LIT = QColor("#5faf6a")
COL_EDGE_PATH = QColor("#7fb3c8")
COL_ALLOC_FILL = QColor("#3f9950")
COL_ALLOC_BORDER = QColor("#9fe8a8")
COL_AVAIL_FILL = QColor("#23262c")
COL_LOCK_FILL = QColor("#16181d")
COL_LOCK_BORDER = QColor("#3a3f47")
COL_PATH_BORDER = QColor("#9fd0e0")
COL_KEYSTONE_RING = QColor("#ff3b30")
COL_HOVER = QColor("#ffffff")

MOD_COLOR = "#8888ff"
GOLD = "#ffd76a"
DIM = "#7a6f5a"

_TOOLTIP_QSS = """
QToolTip {
    background-color: #16130f; color: #c8b898; border: 1px solid #6a5a3a;
    font-family: Consolas, 'Courier New', monospace; font-size: 12px;
}
"""


def _accent(node: tree.NodeDef) -> str:
    return BRANCH_ACCENT.get(node.branch or "", NEUTRAL_ACCENT)


def _tooltip_html(node: tree.NodeDef, hero: Hero, path_len: int,
                  expanded: bool = False) -> str:
    lines = [f'<div style="color:{_accent(node)}; font-weight:bold">{node.name}</div>']
    kind = KIND_LABEL.get(node.kind, "")
    if kind:
        lines.append(f'<div style="color:{DIM}">{kind}</div>')
    for text in tree.node_lines(node):
        lines.append(f'<div style="color:{MOD_COLOR}">{text}</div>')
    if node.kind not in ("keystone", "class_start", "ck") and node.description and not node.stats:
        lines.append(f'<div style="color:{DIM}; font-style:italic">{node.description}</div>')
    # --- class sub-tree bubbles: expand/collapse hint or "<Class> only" ---
    if node.kind == "class_start":
        own = node.id == tree.start_id_for(hero.class_id)
        if own:
            cp = tree.class_points_available(hero)
            act = "collapse" if expanded else "expand"
            status = f"Your class — click to {act} the class tree"
            if cp > 0:
                status += f" · {cp} class point{'s' if cp != 1 else ''} to spend"
            color = GOLD
        else:
            cls = node.branch or "Another class"
            status, color = f"{cls.title()} only", DIM
        lines.append(f'<div style="color:{color}">{status}</div>')
        return "".join(lines)
    # --- ck (class sub-tree) node status: spends Class Points ---
    if node.kind == "ck":
        cp = tree.class_points_available(hero)
        if tree.is_allocated(hero, node.id):
            status, color = "Allocated — right-click to refund", GOLD
        elif node.level_req and hero.level < node.level_req:
            status, color = f"Requires level {node.level_req}", DIM
        elif node.exclusive_group and any(
                tree.NODES.get(nid) and tree.NODES[nid].exclusive_group == node.exclusive_group
                for nid in hero.passives):
            status, color = "Locked — another attunement chosen", DIM
        elif path_len and tree.is_available(hero, node.id):
            if cp >= 1:
                status, color = "Click to allocate (1 class point)", "#e8e0d0"
            else:
                status, color = "No class points available", DIM
        else:
            status, color = "Unreachable", DIM
        lines.append(f'<div style="color:{color}">{status}</div>')
        return "".join(lines)
    if node.id == tree.start_id_for(hero.class_id):
        status, color = "Your class origin — pre-allocated", GOLD
    elif tree.is_allocated(hero, node.id):
        status, color = "Allocated — right-click to refund", GOLD
    elif path_len:
        if tree.points_available(hero) >= path_len:
            cost = "Click to allocate" if path_len == 1 else f"Click to travel — {path_len} points"
            status, color = cost, "#e8e0d0"
        else:
            status, color = f"Needs {path_len} points ({tree.points_available(hero)} available)", DIM
    else:
        status, color = "Unreachable", DIM
    lines.append(f'<div style="color:{color}">{status}</div>')
    return "".join(lines)


def _build_hash() -> dict[tuple[int, int], list[str]]:
    grid: dict[tuple[int, int], list[str]] = {}
    for n in tree.NODES.values():
        key = (int(n.pos[0] // CELL), int(n.pos[1] // CELL))
        grid.setdefault(key, []).append(n.id)
    return grid


_HASH = _build_hash()


def _load_edge_arcs() -> dict[tuple[str, str], tuple[float, float, float, int, int]]:
    """v3.1 pack: some edges are circle arcs — {"a","b","cx","cy","r"}, endpoints
    baked on the circle. Precompute Qt angles (1/16 deg, 0 = 3 o'clock, CCW on
    screen) for the MINOR arc so paintEvent only scales center/radius per frame.
    Keyed by both (a, b) and (b, a); edges absent here render as straight lines."""
    arcs: dict[tuple[str, str], tuple[float, float, float, int, int]] = {}
    for rec in tree.EDGE_ARCS:
        a, b = rec["a"], rec["b"]
        na, nb = tree.NODES.get(a), tree.NODES.get(b)
        if na is None or nb is None:
            continue
        cx, cy, r = float(rec["cx"]), float(rec["cy"]), float(rec["r"])
        # world y points down (same as screen) -> Qt angle uses -dy
        ang_a = math.degrees(math.atan2(cy - na.pos[1], na.pos[0] - cx))
        ang_b = math.degrees(math.atan2(cy - nb.pos[1], nb.pos[0] - cx))
        span = (ang_b - ang_a + 540.0) % 360.0 - 180.0  # signed minor span
        arcs[(a, b)] = arcs[(b, a)] = (cx, cy, r, round(ang_a * 16), round(span * 16))
    return arcs


_ARCS = _load_edge_arcs()

# --- talent icons: notables/keystones get an icon from assets/icons/talents ---
_TAL_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons" / "talents"
# icon groups are thematic 25-icon packs; keystones share the "void" pack
_BRANCH_GROUPS = {
    "warrior": ("arm", "str"),
    "barbarian": ("brb", "str"),
    "archer": ("hunt", "rng"),
    "mage": ("mag", "int"),
    "cleric": ("holy",),
}
_group_files: dict[tuple[str, ...], list[Path]] = {}
_icon_cache: dict[tuple[str, int], QPixmap | None] = {}


def _pool(groups: tuple[str, ...]) -> list[Path]:
    if groups not in _group_files:
        files: list[Path] = []
        for g in groups:
            files += sorted(_TAL_DIR.glob(f"{g}_*.png"),
                            key=lambda p: int(p.stem.split("_")[-1]))
        _group_files[groups] = files
    return _group_files[groups]


def _node_icon(node: tree.NodeDef, size: int) -> QPixmap | None:
    if node.kind not in ("notable", "keystone") or size < ICON_MIN_PX:
        return None
    key = (node.id, size)
    if key not in _icon_cache:
        import zlib
        groups = ("void",) if node.kind == "keystone" else _BRANCH_GROUPS.get(node.branch or "")
        pm = None
        if groups:
            pool = _pool(groups)
            if pool:
                path = pool[zlib.crc32(node.id.encode()) % len(pool)]
                raw = QPixmap(str(path))
                if not raw.isNull():
                    pm = raw.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.FastTransformation)
        _icon_cache[key] = pm
    return _icon_cache[key]


class _TreeCanvas(QWidget):
    """Viewport into world space: pan by dragging anywhere, wheel zoom, culled painting."""

    def __init__(self, panel: "TreePanel", w: int, h: int):
        super().__init__(panel)
        self.panel = panel
        self.setFixedSize(w, h)
        self.setMouseTracking(True)
        self.setStyleSheet(_TOOLTIP_QSS)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._hover: str | None = None
        self._path: list[str] = []
        self._drag_from: QPointF | None = None
        self._dragged = False
        # S.4 rework: class ids whose sub-tree is currently expanded (UI-local,
        # never saved). Clicking a class-start bubble toggles its set membership.
        self._expanded: set[str] = set()
        # camera: world point at canvas center + scale (px per world unit)
        xs = [n.pos[0] for n in tree.NODES.values()]
        ys = [n.pos[1] for n in tree.NODES.values()]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        self.fit_scale = min(w, h) / (span * 1.05)
        # floor at 0.4 unless the whole tree needs a smaller scale to fit
        self.zoom_min = min(ZOOM_MIN_ABS, self.fit_scale * 0.9)
        # default view: hero's class start with its surrounding region readable
        self.scale = max(self.zoom_min, min(ZOOM_MAX, min(w, h) / (span * 0.45)))
        self.cam_x, self.cam_y = tree.NODES[self._start_id()].pos
        # guide rings: v2 META has no cluster_radii (layout is a text note) — skip then
        layout = tree.META.get("layout")
        radii = layout.get("cluster_radii") if isinstance(layout, dict) else None
        self._rings = [float(r) for r in (radii or [])]

    def _start_id(self) -> str:
        return tree.start_id_for(self.panel.hero.class_id)

    def _ck_shown(self, node: tree.NodeDef) -> bool:
        """A class sub-tree node is drawn/hittable only while its class bubble is
        expanded. Allocated ck nodes always show so a build stays visible."""
        if node.kind != "ck":
            return True
        if node.class_req in self._expanded:
            return True
        return node.id in self.panel.hero.passives

    # ------------------------------------------------------------ transform
    def _to_screen(self, wx: float, wy: float) -> QPointF:
        return QPointF((wx - self.cam_x) * self.scale + self.width() / 2,
                       (wy - self.cam_y) * self.scale + self.height() / 2)

    def _to_world(self, pos: QPointF) -> tuple[float, float]:
        return ((pos.x() - self.width() / 2) / self.scale + self.cam_x,
                (pos.y() - self.height() / 2) / self.scale + self.cam_y)

    def _node_at(self, pos: QPointF) -> str | None:
        wx, wy = self._to_world(pos)
        cx, cy = int(wx // CELL), int(wy // CELL)
        best, best_d2 = None, float("inf")
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for nid in _HASH.get((gx, gy), ()):
                    n = tree.NODES[nid]
                    if not self._ck_shown(n):
                        continue
                    r = NODE_RADIUS_WU.get(n.kind, 10) + HIT_SLOP_WU
                    dx, dy = n.pos[0] - wx, n.pos[1] - wy
                    d2 = dx * dx + dy * dy
                    if d2 <= r * r and d2 < best_d2:
                        best, best_d2 = nid, d2
        return best

    def center_on_start(self) -> None:
        self.cam_x, self.cam_y = tree.NODES[self._start_id()].pos
        self.update()

    # ------------------------------------------------------------ painting
    def paintEvent(self, e) -> None:
        hero = self.panel.hero
        start_id = self._start_id()
        allocated = set(hero.passives)
        anchors = allocated | {start_id}
        w, h = self.width(), self.height()

        pad = 80.0
        wx0, wy0 = self._to_world(QPointF(0, 0))
        wx1, wy1 = self._to_world(QPointF(w, h))
        wx0, wy0, wx1, wy1 = wx0 - pad, wy0 - pad, wx1 + pad, wy1 + pad

        def visible(n: tree.NodeDef) -> bool:
            return (wx0 <= n.pos[0] <= wx1 and wy0 <= n.pos[1] <= wy1
                    and self._ck_shown(n))

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, self.scale > 0.3)

        # vignette background + faint guide rings around the start
        grad = QRadialGradient(self._to_screen(0, 0), max(w, h) * 1.2)
        grad.setColorAt(0.0, COL_BG_CENTER)
        grad.setColorAt(1.0, COL_BG_EDGE)
        p.fillRect(self.rect(), QBrush(grad))
        p.setPen(QPen(COL_RING, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        c0 = self._to_screen(0, 0)
        for r in self._rings:
            p.drawEllipse(c0, r * self.scale, r * self.scale)

        path_nodes = set(self._path)
        path_edges: set[frozenset[str]] = set()
        if self._path:
            chain = [*self._path]
            # anchor edge: connect the first path node back to the allocated subgraph
            first = tree.NODES[self._path[0]]
            for nb in tree.ADJ[first.id]:
                if nb in anchors:
                    chain.insert(0, nb)
                    break
            path_edges = {frozenset(pair) for pair in zip(chain, chain[1:])}

        lines: tuple[list, list, list] = ([], [], [])   # dim / lit / hot
        arcs: tuple[list, list, list] = ([], [], [])
        for a, b in tree.EDGES:
            na, nb = tree.NODES[a], tree.NODES[b]
            if not (visible(na) or visible(nb)):
                continue
            if frozenset((a, b)) in path_edges:
                k = 2
            elif a in anchors and b in anchors and (a in allocated or b in allocated):
                k = 1
            else:
                k = 0
            arc = _ARCS.get((a, b))
            if arc is not None:
                acx, acy, r, start, span = arc
                c = self._to_screen(acx, acy)
                rpx = r * self.scale
                arcs[k].append((QRectF(c.x() - rpx, c.y() - rpx, rpx * 2, rpx * 2),
                                start, span))
            else:
                lines[k].append((self._to_screen(*na.pos), self._to_screen(*nb.pos)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for pen, seg, arc_seg in ((QPen(COL_EDGE_DIM, 1), lines[0], arcs[0]),
                                  (QPen(COL_EDGE_LIT, 3), lines[1], arcs[1]),
                                  (QPen(COL_EDGE_PATH, 2, Qt.PenStyle.DashLine),
                                   lines[2], arcs[2])):
            p.setPen(pen)
            for pa, pb in seg:
                p.drawLine(pa, pb)
            for rect, start, span in arc_seg:
                p.drawArc(rect, start, span)

        for n in tree.NODES.values():
            if not visible(n):
                continue
            c = self._to_screen(*n.pos)
            radius = max(2.5, NODE_RADIUS_WU.get(n.kind, 10) * self.scale)
            accent = QColor(_accent(n))
            is_own_start = n.id == start_id
            if n.id in allocated or is_own_start:
                fill, border, width = COL_ALLOC_FILL, COL_ALLOC_BORDER, 2
            elif n.id in path_nodes:
                fill, border, width = COL_AVAIL_FILL, COL_PATH_BORDER, 2
            elif tree.is_available(hero, n.id):
                fill, border, width = accent.darker(160), accent.lighter(145), 2
            else:
                fill = COL_LOCK_FILL
                border = QColor(accent).darker(260) if n.branch else COL_LOCK_BORDER
                width = 1
            if n.kind == "class_start":
                # class origins: big class-colored disc; hero's own reads as allocated
                if not is_own_start and n.id not in allocated:
                    fill = accent.darker(200)
                    border = accent
                    width = 2
                p.setPen(QPen(accent, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, radius + 6, radius + 6)
            elif n.kind == "keystone":
                # red accent ring regardless of state
                p.setPen(QPen(COL_KEYSTONE_RING, max(2.0, 3 * self.scale)))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, radius + 5, radius + 5)
            elif n.kind == "notable":
                ring = QColor(border)
                ring.setAlpha(90)
                p.setPen(QPen(ring, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, radius + 3, radius + 3)
            elif n.kind == "ck":
                # class sub-tree node: gold accent ring so it reads apart from the
                # main tree (it's bought with Class Points, not tree points).
                p.setPen(QPen(QColor(GOLD), max(1.5, 2.5 * self.scale)))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, radius + 4, radius + 4)
            p.setPen(QPen(border, width))
            p.setBrush(QBrush(fill))
            p.drawEllipse(c, radius, radius)
            # notable/keystone art inside the circle (quantized size to keep the cache small)
            icon = _node_icon(n, int(radius * 1.5) & ~1)
            if icon is not None:
                dim = fill is COL_LOCK_FILL  # locked = not allocated/available/on path
                if dim:
                    p.setOpacity(0.4)
                p.drawPixmap(QPointF(c.x() - icon.width() / 2,
                                     c.y() - icon.height() / 2), icon)
                if dim:
                    p.setOpacity(1.0)
            if n.id == self._hover:
                p.setPen(QPen(COL_HOVER, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, radius + 3, radius + 3)
        p.end()

    # ------------------------------------------------------------ input
    def wheelEvent(self, e) -> None:
        # zoom towards the cursor: keep the world point under it fixed
        wx, wy = self._to_world(e.position())
        factor = 1.12 if e.angleDelta().y() > 0 else 1 / 1.12
        self.scale = max(self.zoom_min, min(ZOOM_MAX, self.scale * factor))
        sx, sy = e.position().x(), e.position().y()
        self.cam_x = wx - (sx - self.width() / 2) / self.scale
        self.cam_y = wy - (sy - self.height() / 2) / self.scale
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._drag_from = e.position()
            self._dragged = False

    def mouseMoveEvent(self, e) -> None:
        if self._drag_from is not None:
            d = e.position() - self._drag_from
            if self._dragged or abs(d.x()) + abs(d.y()) > DRAG_THRESHOLD:
                if not self._dragged:
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._dragged = True
                self.cam_x -= d.x() / self.scale
                self.cam_y -= d.y() / self.scale
                self._drag_from = e.position()
                self.update()
                return
        self._update_hover(e.position(), e.globalPosition().toPoint())

    def _update_hover(self, pos: QPointF, global_pos=None) -> None:
        nid = self._node_at(pos)
        if nid != self._hover:
            self._hover = nid
            self._path = tree.path_to(self.panel.hero, nid) if nid else []
            self.update()
        if nid and global_pos is not None:
            QToolTip.showText(global_pos,
                              _tooltip_html(tree.NODES[nid], self.panel.hero,
                                            len(self._path)), self)
        elif global_pos is not None:
            QToolTip.hideText()

    def mouseReleaseEvent(self, e) -> None:
        was_drag = self._dragged
        self._drag_from, self._dragged = None, False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if was_drag:
            return
        nid = self._node_at(e.position())
        if not nid:
            return
        node = tree.NODES[nid]
        # S.4 rework: clicking a class-start bubble toggles its sub-tree. Only the
        # hero's OWN class expands; foreign bubbles just show a "<Class> only" tip.
        if node.kind == "class_start":
            if e.button() == Qt.MouseButton.LeftButton:
                self._toggle_subtree(nid)
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.panel._try_allocate(nid)
        elif e.button() == Qt.MouseButton.RightButton:
            self.panel._try_deallocate(nid)

    def _toggle_subtree(self, start_id: str) -> None:
        """Expand/collapse the class sub-tree for the class start clicked, if it's
        the hero's own class. Foreign class starts do nothing (tooltip explains)."""
        cls = None
        for c, sid in (tree.META.get("class_start_nodes") or {}).items():
            if sid == start_id:
                cls = c
                break
        if cls is None or cls != self.panel.hero.class_id:
            return
        if cls in self._expanded:
            self._expanded.discard(cls)
        else:
            self._expanded.add(cls)
        self._hover = None
        self._path = []
        self.update()

    def leaveEvent(self, e) -> None:
        if self._hover is not None:
            self._hover = None
            self._path = []
            self.update()
        QToolTip.hideText()


class TreePanel(Panel):
    """Popup with the passive tree. refresh() re-reads hero state (used by main's toggle)."""

    def __init__(self, hero: Hero, on_change=None, tree_api=None):
        super().__init__()
        self.hero, self.on_change = hero, on_change
        scr = QApplication.primaryScreen()
        avail = scr.availableGeometry() if scr else None
        cw = int(avail.width() * 0.72) if avail else 1100
        ch = int(avail.height() * 0.74) if avail else 700
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.head = _hdr("")
        top.addWidget(self.head, 1)
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet(
            "QPushButton { background: #2a1416; color: #c8b898; border: 1px solid #6a3a3a;"
            " font-size: 12px; padding: 0; }"
            "QPushButton:hover { background: #4a1c1c; color: #ffffff; }")
        self.close_btn.clicked.connect(self.hide)
        top.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)
        self.canvas = _TreeCanvas(self, cw, ch)
        lay.addWidget(self.canvas)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        pts = tree.points_available(self.hero)
        self.head.setText(
            f"Passive Tree — {pts} points available, {tree.points_spent(self.hero)} spent")
        self.head.setMaximumWidth(self.canvas.width())
        self.canvas.update()
        self.adjustSize()

    def _try_allocate(self, node_id: str) -> None:
        if tree.allocate_path(self.hero, node_id):
            self.canvas._path = []
            self.refresh()
            if self.on_change:
                self.on_change()

    def _try_deallocate(self, node_id: str) -> None:
        if tree.deallocate(self.hero, node_id):
            self.canvas._path = []
            self.refresh()
            if self.on_change:
                self.on_change()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def showEvent(self, e) -> None:
        self.refresh()
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e) -> None:
        self._timer.stop()
        QToolTip.hideText()
        super().hideEvent(e)


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from game import classes

    app = QApplication(sys.argv)
    hero = classes.make_hero("warrior")
    hero.level = 20
    classes.apply_level_growth(hero)

    changes: list[int] = []
    panel = TreePanel(hero, on_change=lambda: changes.append(1))
    panel.refresh()
    panel.show()
    assert "points available" in panel.head.text(), panel.head.text()
    # close button hides the panel
    assert panel.close_btn.text() == "✕"
    panel.close_btn.click()
    assert not panel.isVisible(), "close button did not hide the panel"
    panel.show()
    scr_w = QApplication.primaryScreen().availableGeometry().width()
    assert panel.canvas.width() >= int(scr_w * 0.7), (panel.canvas.width(), scr_w)

    cv = panel.canvas
    start_id = tree.start_id_for(hero.class_id)
    start = tree.NODES[start_id]

    # v2 sanity: 5 class starts, no global center node
    starts = [n for n in tree.NODES.values() if n.kind == "class_start"]
    assert len(starts) == 5, len(starts)

    # v3.1 edge arcs: loaded, symmetric keys, every arc pair is a real edge,
    # endpoints sit on their circle, and the precomputed span is the MINOR arc
    assert _ARCS, "edge_arcs missing from data/passives_v2.json"
    edge_set = {frozenset(e) for e in tree.EDGES}
    pairs = {frozenset(k) for k in _ARCS}
    assert all(fs in edge_set for fs in pairs), "arc pair not present in edges"
    assert all((b, a) in _ARCS for (a, b) in _ARCS), "arc lookup not symmetric"
    for (a, b), (acx, acy, r, a0, span) in _ARCS.items():
        assert 0 < abs(span) <= 180 * 16, (a, b, span)
        for nid in (a, b):
            n = tree.NODES[nid]
            d = ((n.pos[0] - acx) ** 2 + (n.pos[1] - acy) ** 2) ** 0.5
            assert abs(d - r) < 1.0, (nid, d, r)
    # angle math: endpoint b = rotating a's Qt angle by the signed span
    (a, b), (acx, acy, r, a0, span) = next(iter(_ARCS.items()))
    nb_ = tree.NODES[b]
    end = math.radians((a0 + span) / 16.0)
    bx, by = acx + r * math.cos(end), acy - r * math.sin(end)
    assert abs(bx - nb_.pos[0]) < 1.0 and abs(by - nb_.pos[1]) < 1.0, \
        ((bx, by), nb_.pos)

    # camera opens centered on the warrior's class start
    assert abs(cv.cam_x - start.pos[0]) < 1 and abs(cv.cam_y - start.pos[1]) < 1, \
        (cv.cam_x, cv.cam_y, start.pos)
    assert cv._node_at(cv._to_screen(*start.pos)) == start_id

    # zoom range: clamps at zoom_min (0.4 or fit*0.9, whichever smaller) and 2.5
    assert cv.zoom_min == min(ZOOM_MIN_ABS, cv.fit_scale * 0.9), (cv.zoom_min, cv.fit_scale)
    assert cv.zoom_min <= cv.scale <= ZOOM_MAX

    class _E:
        def __init__(self, dy: int):
            self.dy = dy
        def position(self):
            return QPointF(cv.width() / 2, cv.height() / 2)
        def angleDelta(self):
            outer = self
            class _D:
                def y(self):
                    return outer.dy
            return _D()

    for _ in range(80):
        cv.wheelEvent(_E(120))
    assert abs(cv.scale - ZOOM_MAX) < 1e-9, cv.scale
    for _ in range(80):
        cv.wheelEvent(_E(-120))
    assert abs(cv.scale - cv.zoom_min) < 1e-9, (cv.scale, cv.zoom_min)

    # zoom anchor: world point under the cursor stays fixed
    cv.center_on_start()
    cv.scale = 1.0
    s0 = cv.scale
    probe = QPointF(cv.width() / 2 + 60, cv.height() / 2 + 40)
    class _EP(_E):
        def position(self):
            return probe
    wx0, wy0 = cv._to_world(probe)
    cv.wheelEvent(_EP(120))
    assert cv.scale > s0
    wx1, wy1 = cv._to_world(probe)
    assert abs(wx1 - wx0) < 1 and abs(wy1 - wy0) < 1, "zoom anchor drifted"

    # hover a far node -> path preview appears
    far = next(n for n in tree.NODES.values()
               if n.kind == "small" and start_id not in tree.ADJ[n.id]
               and len(tree.path_to(hero, n.id)) >= 3)
    cv.cam_x, cv.cam_y = far.pos
    cv._update_hover(cv._to_screen(*far.pos))
    assert cv._hover == far.id and len(cv._path) >= 3, (cv._hover, cv._path)

    # click a far node -> whole path allocated (PoE travel)
    cost = len(cv._path)
    panel._try_allocate(far.id)
    assert tree.is_allocated(hero, far.id) and changes == [1]
    assert tree.points_spent(hero) == cost, (tree.points_spent(hero), cost)
    assert not cv._path, "path preview not cleared after allocation"

    # RMB refund a leaf
    panel._try_deallocate(far.id)
    assert not tree.is_allocated(hero, far.id) and len(changes) == 2

    # tooltip sanity with travel cost (while far is unallocated)
    html = _tooltip_html(far, hero, 5)
    assert far.name in html and "5 points" in html

    # re-allocate a few points so the screenshot shows the allocated state
    panel._try_allocate(far.id)

    # keystone tooltips must not mention a level gate anymore
    ks = next(n for n in tree.NODES.values() if n.kind == "keystone")
    html = _tooltip_html(ks, hero, len(tree.path_to(hero, ks.id)))
    assert "Requires level" not in html, html

    base = os.path.dirname(os.path.abspath(__file__))
    cv.center_on_start()
    cv.scale = max(cv.zoom_min, min(ZOOM_MAX, 1.0))
    panel.refresh()
    panel.grab().save(os.path.join(base, "_tree_test.png"))
    cv.scale = cv.fit_scale
    cv.update()
    panel.grab().save(os.path.join(base, "_tree_test_full.png"))
    print("render:", os.path.join(base, "_tree_test.png"))
    print("tree_panel OK")
