"""Headless smoke + behaviour tests for ui.rarity_frames (Relic/Primal frames).

Disjoint from the game: only PyQt6 primitives go in. Runnable both ways:
    python tests/test_rarity_frames.py
    pytest tests/test_rarity_frames.py

Offscreen QApplication at import time (same setup as tests/test_wave1.py) so a
QPixmap can be constructed in CI with no display.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from ui import rarity_frames as RF  # noqa: E402


def _alpha_pixmap(w: int = 20, h: int = 24) -> QPixmap:
    """A transparent pixmap with an opaque blob in the middle — a valid alpha
    source (some pixels alpha=255, some alpha=0), like an item icon."""
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.fillRect(4, 5, w - 8, h - 10, QColor(200, 160, 90, 255))
    p.fillRect(w // 2 - 1, 1, 2, h - 2, QColor(255, 255, 255, 255))
    p.end()
    return pm


def _reset_caches() -> None:
    RF._mask_cache.clear()
    RF._holo_cache.clear()
    RF._mask_builds = 0
    RF._holo_builds = 0


def _non_transparent_pixels(pm: QPixmap) -> int:
    img = pm.toImage()
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if QColor.fromRgba(img.pixel(x, y)).alpha() > 0:
                n += 1
    return n


# ----------------------------------------------------------- basic invariants

def test_holo_does_not_crash_and_pads_by_frame_px():
    _reset_caches()
    src = _alpha_pixmap(20, 24)
    out = RF.holo_foil_frame(src, seed=3)
    assert out.width() == src.width() + 2 * RF.FRAME_PX, out.width()
    assert out.height() == src.height() + 2 * RF.FRAME_PX, out.height()
    assert _non_transparent_pixels(out) > 0, "holo frame is entirely blank"


def test_rainbow_does_not_crash_and_pads_by_frame_px():
    _reset_caches()
    src = _alpha_pixmap(20, 24)
    out = RF.rainbow_cycle_frame(src, time_ms=0.0)
    assert out.width() == src.width() + 2 * RF.FRAME_PX, out.width()
    assert out.height() == src.height() + 2 * RF.FRAME_PX, out.height()
    assert _non_transparent_pixels(out) > 0, "rainbow frame is entirely blank"


def test_frames_are_multicolour_not_single_tint():
    """A rainbow border must contain several distinct hues, unlike the flat
    single-colour _outline_frame halo."""
    _reset_caches()
    src = _alpha_pixmap()
    img = RF.holo_foil_frame(src, seed=0).toImage()
    hues = set()
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor.fromRgba(img.pixel(x, y))
            if c.alpha() > 0:
                hues.add(c.hue() // 20)  # bucket hues into ~18 bins
    assert len(hues) >= 4, f"expected many hues around the ring, got {len(hues)}"


# ------------------------------------------------------------ caching behaviour

def test_mask_cache_hit_on_repeat_input():
    """Repeated calls with the same source reuse the cached (expensive) ring
    mask: the build counter must not advance past 1."""
    _reset_caches()
    src = _alpha_pixmap()
    RF.rainbow_cycle_frame(src, time_ms=0.0)
    assert RF._mask_builds == 1
    RF.rainbow_cycle_frame(src, time_ms=500.0)
    RF.rainbow_cycle_frame(src, time_ms=1234.5)
    RF.holo_foil_frame(src, seed=7)
    # Every subsequent call reused the mask -> still exactly one build.
    assert RF._mask_builds == 1, RF._mask_builds


def test_holo_result_cache_hit_on_repeat():
    """holo_foil is a static snapshot: identical (source, seed) returns the very
    same cached pixmap and does not rebuild."""
    _reset_caches()
    src = _alpha_pixmap()
    a = RF.holo_foil_frame(src, seed=5)
    assert RF._holo_builds == 1
    b = RF.holo_foil_frame(src, seed=5)
    assert RF._holo_builds == 1, "second identical holo call should hit the cache"
    assert a.cacheKey() == b.cacheKey(), "cache must return the same QPixmap object"
    # A different seed is a different snapshot -> a rebuild.
    RF.holo_foil_frame(src, seed=6)
    assert RF._holo_builds == 2


# ------------------------------------------------------- animation is animated

def _pixels_differ(a: QPixmap, b: QPixmap) -> bool:
    ia, ib = a.toImage(), b.toImage()
    if ia.size() != ib.size():
        return True
    for y in range(ia.height()):
        for x in range(ia.width()):
            if ia.pixel(x, y) != ib.pixel(x, y):
                return True
    return False


def test_rainbow_cycle_changes_over_time():
    """Different time_ms must yield visually different frames (the ring rotates),
    while the mask stays cached (only the cheap colour pass re-runs)."""
    _reset_caches()
    src = _alpha_pixmap()
    f0 = RF.rainbow_cycle_frame(src, time_ms=0.0)
    f_quarter = RF.rainbow_cycle_frame(src, time_ms=RF._CYCLE_MS * 0.25)
    f_half = RF.rainbow_cycle_frame(src, time_ms=RF._CYCLE_MS * 0.5)
    assert _pixels_differ(f0, f_quarter), "quarter-cycle frame identical to t=0"
    assert _pixels_differ(f0, f_half), "half-cycle frame identical to t=0"
    assert RF._mask_builds == 1, "colour animation must not rebuild the mask"


def test_rainbow_cycle_wraps_to_same_frame():
    """A full _CYCLE_MS rotation lands back on the starting colours."""
    _reset_caches()
    src = _alpha_pixmap()
    f0 = RF.rainbow_cycle_frame(src, time_ms=0.0)
    f_full = RF.rainbow_cycle_frame(src, time_ms=RF._CYCLE_MS)
    assert not _pixels_differ(f0, f_full), "one full cycle should match t=0"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL OK")
