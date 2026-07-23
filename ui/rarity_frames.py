"""Bar of Exile — rarity-frame VFX for the 10-tier item ladder (Relic/Primal).

Disjoint module: deliberately does NOT import ui.render / main.py / window.py /
game.core. Callers pass raw PyQt6 primitives (an alpha-carrying QPixmap, e.g. an
item icon) plus plain params (seed / time_ms) and get back a padded, coloured
ring pixmap meant to be blitted UNDER the icon — the exact silhouette-and-stamp
technique ui.render._outline_frame uses for the E.6 monster-rarity halo (solid
colour silhouette of the alpha mask, stamped at 8 surrounding offsets, cached by
`cacheKey()`), just recoloured per-position-around-the-perimeter instead of one
flat tier colour.

Two functions, two tiers of the same effect:
  - holo_foil_frame    -> Relic: a STATIC multi-band rainbow ("holographic foil
                          viewed at one fixed angle"), deterministic per seed.
  - rainbow_cycle_frame -> Primal: the SAME ring geometry, but the gradient's
                          start angle rotates with time_ms (RGB-peripheral style
                          hue-cycling).

Caching (mirrors the comment above ui.render._outline_frame almost exactly):
  - `_ring_mask()` builds the EXPENSIVE part — the alpha-silhouette dilated into
    a ring via 8 QPainter blits — and is cached forever, keyed by the source
    QPixmap's `cacheKey()` (same key strategy as _outline_frame/_flash_frame).
  - The colour pass (one QConicalGradient + one SourceIn fillRect) is CHEAP:
      * holo_foil_frame is a deterministic snapshot per (source, seed), so the
        whole coloured result is cached too (same pattern as _outline_frame,
        which caches by (cacheKey, colour)).
      * rainbow_cycle_frame is intentionally NOT cached by time_ms — that key
        is continuous/unbounded and would never hit while leaking memory — it
        is recomputed every call directly from the cached ring mask, so the
        per-tick cost is exactly one gradient object + one fillRect.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QConicalGradient, QPainter, QPixmap

# Padding added on every side of the returned pixmap — same convention as
# ui.render._OUTLINE_PX (E.6 halo): the ring pokes out past the sprite's own
# bounds, so callers must offset the blit by -FRAME_PX on both axes.
FRAME_PX = 2
_FRAME_ALPHA = 235  # near-opaque so the rainbow reads clearly against the sprite

_HOLO_BANDS = 3      # hue wraps this many times around the perimeter -> foil "bands"
_HOLO_STOPS = 18     # gradient colour stops baked into the static holo snapshot
_RAINBOW_STOPS = 12  # gradient colour stops for the animated cycle's hue ladder
_CYCLE_MS = 2000.0   # ms for one full 360deg rotation of the rainbow

# ------------------------------------------------------------- expensive: mask

_mask_cache: dict[int, QPixmap] = {}
_mask_builds = 0  # incremented only on an actual (non-cached) mask build; tests
                   # use this counter to assert repeated calls hit the cache.


def _ring_mask(alpha_source: QPixmap) -> QPixmap:
    """Opaque-white ring silhouette padded by FRAME_PX, cached by cacheKey().

    Identical stamp pattern to render._outline_frame (silhouette blitted at 8
    neighbours offset by ±FRAME_PX so a ring leaks out around the sprite edge),
    just left uncoloured here so a cheap colour pass can be swapped per frame.
    """
    global _mask_builds
    key = alpha_source.cacheKey()
    cached = _mask_cache.get(key)
    if cached is not None:
        return cached
    _mask_builds += 1
    if len(_mask_cache) > 256:
        _mask_cache.clear()
    d = FRAME_PX
    sil = QPixmap(alpha_source.size())
    sil.fill(Qt.GlobalColor.transparent)
    q = QPainter(sil)
    q.drawPixmap(0, 0, alpha_source)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    q.fillRect(sil.rect(), QColor(255, 255, 255, 255))
    q.end()
    out = QPixmap(alpha_source.width() + 2 * d, alpha_source.height() + 2 * d)
    out.fill(Qt.GlobalColor.transparent)
    q = QPainter(out)
    for dx, dy in ((-d, 0), (d, 0), (0, -d), (0, d),
                   (-d, -d), (d, -d), (-d, d), (d, d)):
        q.drawPixmap(d + dx, d + dy, sil)
    q.end()
    _mask_cache[key] = out
    return out


# ---------------------------------------------------------------- cheap: colour

def _paint_conical(mask: QPixmap, stops: list[tuple[float, QColor]],
                   angle_deg: float) -> QPixmap:
    """Recolour `mask` (opaque silhouette) with a conical gradient centred on
    it, via CompositionMode_SourceIn — the same tint trick _outline_frame uses
    for a flat colour fill, generalised to a multi-stop gradient brush."""
    out = QPixmap(mask.size())
    out.fill(Qt.GlobalColor.transparent)
    q = QPainter(out)
    q.drawPixmap(0, 0, mask)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    grad = QConicalGradient(out.width() / 2.0, out.height() / 2.0, angle_deg)
    for t, col in stops:
        grad.setColorAt(t, col)
    q.fillRect(out.rect(), QBrush(grad))
    q.end()
    return out


def _holo_stops(seed: int) -> list[tuple[float, QColor]]:
    """Static multi-band hue ladder for holo_foil: several rainbow wraps around
    the perimeter (like foil trading-card stock) plus a cosine value/saturation
    shimmer so alternating bands read lighter/darker at a FIXED viewing angle —
    no time dependency; this is a one-off "snapshot" of the holo pattern, only
    `seed` (per-item/per-icon) varies the phase so not every Relic looks identical.
    """
    phase = (seed * 47) % 360
    out: list[tuple[float, QColor]] = []
    for i in range(_HOLO_STOPS + 1):
        t = i / _HOLO_STOPS
        hue = (t * 360.0 * _HOLO_BANDS + phase) % 360.0
        shimmer = 0.5 + 0.5 * math.cos(2 * math.pi * t * _HOLO_BANDS * 2)
        val = min(255, int(180 + 75 * shimmer))
        sat = min(255, int(210 + 45 * (1 - shimmer)))
        out.append((t, QColor.fromHsv(int(hue), sat, val, _FRAME_ALPHA)))
    return out


_holo_cache: dict[tuple[int, int], QPixmap] = {}
_holo_builds = 0


def holo_foil_frame(alpha_source: QPixmap, seed: int = 0) -> QPixmap:
    """Static holographic-foil ring for Relic-tier items.

    Deterministic per (source pixmap, seed): a multi-band rainbow gradient
    around the perimeter with a cosine shimmer, fixed at "one viewing angle".
    Unlike rainbow_cycle_frame it never changes across calls for the same
    inputs, so — same as _outline_frame caching by (cacheKey, colour) — the
    whole coloured result is cached here too, not just the mask.
    """
    global _holo_builds
    key = (alpha_source.cacheKey(), seed)
    cached = _holo_cache.get(key)
    if cached is not None:
        return cached
    _holo_builds += 1
    if len(_holo_cache) > 256:
        _holo_cache.clear()
    mask = _ring_mask(alpha_source)
    out = _paint_conical(mask, _holo_stops(seed), angle_deg=float((seed * 47) % 360))
    _holo_cache[key] = out
    return out


_rainbow_stops_cache: list[tuple[float, QColor]] | None = None


def _rainbow_stops() -> list[tuple[float, QColor]]:
    global _rainbow_stops_cache
    if _rainbow_stops_cache is None:
        _rainbow_stops_cache = [
            (i / _RAINBOW_STOPS,
             QColor.fromHsv(int((i / _RAINBOW_STOPS) * 360.0) % 360, 255, 255, _FRAME_ALPHA))
            for i in range(_RAINBOW_STOPS + 1)
        ]
    return _rainbow_stops_cache


def rainbow_cycle_frame(alpha_source: QPixmap, time_ms: float) -> QPixmap:
    """Animated RGB-cycling ring for Primal-tier items.

    The mask (expensive: silhouette + 8-way dilation) is cached by source
    cacheKey() via _ring_mask — built once per sprite frame regardless of how
    many different time_ms values are requested. The colour pass here is the
    cheap per-tick part and is deliberately NOT cached by time_ms (a
    continuously-varying key would never hit and would just grow the cache
    forever); every call re-tints the same cached mask with a QConicalGradient
    whose start angle is time_ms's phase within the _CYCLE_MS rotation, so the
    per-frame cost is exactly one gradient object + one fillRect — no
    per-pixel work, same 0-popixel-ops-per-tick budget as _outline_frame.
    """
    mask = _ring_mask(alpha_source)
    angle = (time_ms % _CYCLE_MS) / _CYCLE_MS * 360.0
    return _paint_conical(mask, _rainbow_stops(), angle_deg=angle)
