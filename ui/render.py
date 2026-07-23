"""Bar of Exile — sprite assets, procedural pixel fallbacks and strip rendering."""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPixmap,
                         QPolygonF, QTransform)

from game.combat import CORPSE_LINGER
from game import mob_rarity
from game.core import (DTYPE_COLORS, RARITY_COLORS, CombatEvent, DamageType,
                       Hero, Monster, Rarity)

# Ailment system is developed in parallel; render must not depend on it.
try:
    from game.ailments import active_icons
except ImportError:
    active_icons = None

AILMENT_COLORS = {
    "ignite": "#ff6a2a",
    "bleed": "#cc2233",
    "poison": "#55cc33",
    "freeze": "#66bbee",
    "shock": "#ffd94a",
    "stun": "#cccccc",
}

H = 64
GROUND_H = 10
PATH_H = 6          # dark walking path along the strip bottom
DEATH_FADE = 0.35   # seconds a corpse takes to fade out
HIT_FLASH = 0.1     # seconds of white flash after taking a hit
_SKIN = "#e8c298"

# Projectile skills whose VFX sheet begins with launch/flight frames that should
# travel from caster to target; value = fraction of frames spent in flight before
# the on-target explosion. Non-listed skills play in place at the target.
_SKILL_TRAVEL_FRAC = {
    "fireball": 0.55,
}

# Ranged auto-attack projectiles: fraction of the sheet spent flying hero->target
# before the on-target burst. proj_mage = 10 bolt frames + 6 impact (10/16); proj
# _arrow is all flight (no separate impact sheet), so it flies the whole way.
_PROJ_TRAVEL_FRAC = {
    "proj_mage": 0.625,
    "proj_arrow": 0.9,
}
# On-screen height (px) for each projectile effect — kept small for the ~64px strip.
_PROJ_H = {
    "proj_mage": 22,
    "proj_arrow": 12,
}
# Flight altitude: px between the strip baseline and the projectile's bottom
# edge, so bolts/arrows leave at staff/bow level (~chest of a 44px hero)
# instead of skimming the ground.
_PROJ_ALT = {
    "proj_mage": 14,
    "proj_arrow": 18,
}

# Elemental-projectile stand-in (no dedicated VFX sheet for most skills): a skill
# tagged "proj" reuses the auto-attack arrow/bolt sprite, recoloured by its damage
# type (poison arrow = purple, lightning = yellow, fire = orange…). Which base
# projectile a class fires:
_CLASS_PROJ = {
    "archer": "proj_arrow",
    "mage": "proj_mage",
}
# Purely-cosmetic projectile tint overrides by skill id, for skills whose flavour
# is elemental but whose damage_type is phys (so we don't touch resists/ailments/
# balance just to colour an arrow). Value = hex colour for the flying sprite.
_SKILL_TINT_OVERRIDE = {
    "explosive_arrow": "#ff6633",  # "explosive" reads as fire-orange
}
# Cache: skill id -> (is_projectile, DamageType) parsed once from skills_v2 data.
_skill_proj_cache: dict[str, tuple[bool, "DamageType"]] | None = None


def _skill_proj_info(sid: str) -> tuple[bool, "DamageType"]:
    """(is_projectile, damage_type) for a skill id, from skills_v2.json tags.
    Cached; unknown ids -> (False, PHYS)."""
    global _skill_proj_cache
    if _skill_proj_cache is None:
        _skill_proj_cache = {}
        try:
            from game.skills_v2 import load_skills_v2
            for s in load_skills_v2().values():
                _skill_proj_cache[s.id] = ("proj" in s.tags, s.damage_type)
        except Exception:
            _skill_proj_cache = {}
    return _skill_proj_cache.get(sid, (False, DamageType.PHYS))


CLASS_STYLE = {
    "berserker": {"body": "#8a2f22", "pants": "#5a3a26", "hair": "#3a2418"},
    "ranger": {"body": "#2f7a3a", "pants": "#3f5030", "hair": "#254a1e"},
    "sorceress": {"body": "#3050b0", "pants": "#283a80", "hair": "#20287a"},
}

MONSTER_STYLE: dict[str, tuple[str, str]] = {
    "zombie": ("#6a8f4f", "medium"),
    "skeleton": ("#d8d8c4", "medium"),
    "skeleton_archer": ("#c2c2a8", "medium"),
    "goblin": ("#48a848", "small"),
    "cave_rat": ("#8a7460", "small"),
    "bandit": ("#a37f4e", "medium"),
    "goblin_shaman": ("#5fc98a", "small"),
    "fire_spirit": ("#ff6633", "medium"),
    "ice_fiend": ("#66ccff", "medium"),
    "ice_beast": ("#66ccff", "medium"),
    "stone_golem": ("#9a9a9a", "large"),
    "ancient_golem": ("#b3a077", "large"),
    "blood_ape": ("#8a2f2f", "medium"),
    "cursed_priest": ("#7a5f9a", "medium"),
    "demon": ("#a03030", "medium"),
    "dune_bandit": ("#c2a26a", "medium"),
    "fire_serpent": ("#e04422", "medium"),
    "goblin_king": ("#3a9a3a", "large"),
    "imp": ("#c25a2a", "small"),
    "jungle_stalker": ("#3f6f34", "medium"),
    "lich_emperor": ("#9a86d8", "large"),
    "lord_of_ash": ("#d8622a", "large"),
    "mother_of_slimes": ("#7ad24a", "large"),
    "mummy": ("#c8bd9a", "medium"),
    "orc": ("#5a7a3a", "medium"),
    "orc_brute": ("#4e6c34", "large"),
    "orc_warlord": ("#44622c", "large"),
    "sand_leaper": ("#d2b475", "small"),
    "scarab_swarm": ("#3a4a68", "small"),
    "skeleton_mage": ("#b8c2d8", "medium"),
    "slime_icy": ("#7ad0f0", "small"),
    "slime_magma": ("#f06a2a", "small"),
    "slime_toxic": ("#66d22a", "small"),
    "temple_guardian": ("#c2a24e", "large"),
    "tomb_snake": ("#cdb87e", "small"),
    "venom_toad": ("#6a9a2f", "small"),
    "vulture_demon": ("#6a4a6a", "medium"),
    "plague_rat": ("#7a6050", "small"),
}
_DEFAULT_STYLE = ("#909090", "medium")
_SIZE_PX = {"small": (8, 10), "medium": (11, 14), "large": (15, 20)}

THEMES = {
    "beach": {"sky": ("#7fb8d8", "#e8d8a8"), "far": "#5f93ad",
              "ground": "#d2b98a", "ground_top": "#e2cf9f", "dots": "#a98f60"},
    "swamp": {"sky": ("#39443a", "#2a3328"), "far": "#222d22",
              "ground": "#33402c", "ground_top": "#41503a", "dots": "#242f1f"},
    "forest": {"sky": ("#2c4a3e", "#1d3328"), "far": "#16281e",
               "ground": "#35492c", "ground_top": "#44583a", "dots": "#26361f"},
    "cave": {"sky": ("#16161f", "#221f2c"), "far": "#2a2838",
             "ground": "#3a3745", "ground_top": "#474355", "dots": "#4c4860"},
    "ruins": {"sky": ("#3c3352", "#2a2438"), "far": "#241f36",
              "ground": "#4a4138", "ground_top": "#584e42", "dots": "#372f27"},
    "desert": {"sky": ("#c9a25f", "#e8d0a0"), "far": "#b08c58",
               "ground": "#d8bd85", "ground_top": "#e5cf9d", "dots": "#b09566"},
    "tomb": {"sky": ("#2a2436", "#1e1a2a"), "far": "#352c44",
             "ground": "#443c50", "ground_top": "#524a60", "dots": "#2e2838"},
    "jungle": {"sky": ("#1f3d2a", "#142a1c"), "far": "#0f2016",
               "ground": "#2a4020", "ground_top": "#375030", "dots": "#1c3018"},
    "temple": {"sky": ("#4a3f2a", "#332c1e"), "far": "#5a4c30",
               "ground": "#6a5a3a", "ground_top": "#7a693f", "dots": "#4c4028"},
}

_LEG_FRAMES = [
    [(5, 10, 2, 6), (8, 10, 2, 6)],
    [(3, 10, 2, 6), (9, 10, 2, 5)],
    [(5, 10, 2, 6), (8, 10, 2, 6)],
    [(5, 10, 2, 5), (10, 10, 2, 6)],
]

# PNG sprites' native facing. Heroes are drawn facing right, monsters facing
# left (see _draw_entity flip logic); loaded sprites get mirrored to match.
# Flip this to False if the sprite sheets turn out to face left.
SPRITE_FACES_RIGHT = True

_SPRITES_DIR = Path(__file__).resolve().parent.parent / "assets" / "sprites"
_BG_DIR = Path(__file__).resolve().parent.parent / "assets" / "backgrounds"
_VFX_DIR = Path(__file__).resolve().parent.parent / "assets" / "vfx"


class BackgroundStore:
    """Location background strips cut from art, keyed by zone theme.

    Falls back to None (procedural themes) when the art is missing."""

    def __init__(self) -> None:
        self._index: dict[str, list[str]] | None = None
        self._cache: dict[tuple[str, int], QPixmap | None] = {}

    def _load_index(self) -> dict[str, list[str]]:
        if self._index is None:
            self._index = {}
            try:
                data = json.loads((_BG_DIR / "index.json").read_text("utf-8"))
                for section in ("themes", "extra"):
                    for k, files in data.get(section, {}).items():
                        if files:
                            self._index[k] = files
            except (OSError, ValueError):
                pass
        return self._index

    def tile(self, theme_id: str, h: int) -> QPixmap | None:
        key = (theme_id, h)
        if key not in self._cache:
            pm = None
            files = self._load_index().get(theme_id)
            if files:
                src = QPixmap(str(_BG_DIR / files[0]))
                if not src.isNull():
                    pm = src.scaledToHeight(
                        h, Qt.TransformationMode.SmoothTransformation)
            self._cache[key] = pm
        return self._cache[key]


class VfxStore:
    """Frame sequences from assets/vfx/<effect>/ per assets/vfx/manifest.json."""

    def __init__(self) -> None:
        self._manifest: dict | None = None
        self._cache: dict[tuple[str, int], list[QPixmap]] = {}

    def _load_manifest(self) -> dict:
        if self._manifest is None:
            try:
                self._manifest = json.loads(
                    (_VFX_DIR / "manifest.json").read_text("utf-8"))
            except (OSError, ValueError):
                self._manifest = {}
        return self._manifest

    def fps(self, effect: str) -> int:
        return int(self._load_manifest().get(effect, {}).get("fps", 12))

    def frames(self, effect: str, h: int) -> list[QPixmap]:
        key = (effect, h)
        if key not in self._cache:
            out: list[QPixmap] = []
            if effect in self._load_manifest():
                d = _VFX_DIR / effect
                try:
                    names = sorted(f for f in os.listdir(d) if f.endswith(".png"))
                except OSError:
                    names = []
                for n in names:
                    pm = QPixmap(str(d / n))
                    if not pm.isNull():
                        out.append(pm.scaledToHeight(
                            h, Qt.TransformationMode.FastTransformation))
            self._cache[key] = out
        return self._cache[key]


VFX = VfxStore()


def _make_dead_frame(src: QPixmap) -> QPixmap:
    """Corpse frame from a walk frame: darkened and translucent, upright.

    No rotation — the corpse dissolves in place via the caller's fade-out.
    Rotating looked wrong on wide mobs (spider/scarab flipped onto their side).
    """
    out = QPixmap(src.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setOpacity(0.72)
    p.drawPixmap(0, 0, src)
    p.setOpacity(1.0)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    p.fillRect(out.rect(), QColor(0, 0, 0, 110))
    p.end()
    return out


class SpriteStore:
    """Lazy loader for PNG sprite frames described by assets/sprites/manifest.json.

    Manifest format: {"<id>": {"walk": [...], "attack": [...], "h": int}} with
    files in assets/sprites/<id>/. Missing "attack" reuses walk frames, missing
    "dead" is synthesized from walk_0. Returns None for unknown/broken ids so
    callers can fall back to procedural pixmaps.
    """

    def __init__(self, root: Path = _SPRITES_DIR) -> None:
        self.root = Path(root)
        self._manifest: dict | None = None
        self._cache: dict[tuple[str, bool], dict[str, list[QPixmap]]] = {}

    def _load_manifest(self) -> dict:
        if self._manifest is None:
            try:
                with open(self.root / "manifest.json", encoding="utf-8") as f:
                    self._manifest = json.load(f)
            except (OSError, ValueError):
                self._manifest = {}
        return self._manifest

    def has(self, sprite_id: str) -> bool:
        return sprite_id in self._load_manifest()

    def frames(self, sprite_id: str, mirror: bool = False) -> dict[str, list[QPixmap]] | None:
        key = (sprite_id, mirror)
        if key in self._cache:
            return self._cache[key]
        entry = self._load_manifest().get(sprite_id)
        if not isinstance(entry, dict):
            return None
        entry = self._normalize_entry(entry)
        # Frames may live in a subdir other than sprite_id (atlas rips share a
        # parent folder, e.g. "undead_jungle/jungle_stalker/all/frame_000.png").
        sub = entry.get("dir", sprite_id)
        h = int(entry.get("h", 32))
        # One scale factor per sprite, keyed off the walk sheet's native height.
        # All states share it so the body stays the same on-screen size — a taller
        # attack sheet then just extends upward (raised weapon), feet on the baseline.
        # Scaling each sheet to h independently shrank the body on the taller attack
        # frames (worst on warrior: walk 269px vs attack 588px source).
        ref = None
        for name in entry.get("walk") or []:
            raw = QPixmap(str(self.root / sub / name))
            if not raw.isNull():
                ref = raw.height()
                break
        factor = (h / ref) if ref else 1.0
        out: dict[str, list[QPixmap]] = {}
        for state in ("walk", "attack", "dead"):
            pms = [pm for name in entry.get(state) or []
                   if (pm := self._load_png(sub, name, factor, mirror)) is not None]
            if pms:
                out[state] = pms
        if "walk" not in out:
            return None  # nothing usable — procedural fallback
        if "attack" not in out:
            out["attack"] = out["walk"]
        if "dead" not in out:
            out["dead"] = [_make_dead_frame(out["walk"][0])]
        self._cache[key] = out
        return out

    @staticmethod
    def _normalize_entry(entry: dict) -> dict:
        """Atlas rips list every frame in one `all` sequence (walk then attack,
        no split). Expand that into walk/attack here so the rest of the loader
        stays uniform. `all_split` is the walk fraction (default 0.5). Entries
        that already give explicit walk/attack pass through untouched."""
        if "all" not in entry or entry.get("walk"):
            return entry
        frames = entry["all"]
        if not isinstance(frames, list) or not frames:
            return entry
        split = entry.get("all_split", 0.5)
        cut = max(1, min(len(frames) - 1, round(len(frames) * split))) \
            if len(frames) > 1 else 1
        out = dict(entry)
        out["walk"] = frames[:cut]
        out["attack"] = frames[cut:] or frames[:cut]
        return out

    def _load_png(self, sub: str, name: str, factor: float, mirror: bool) -> QPixmap | None:
        pm = QPixmap(str(self.root / sub / name))
        if pm.isNull():
            return None
        if factor != 1.0:
            pm = pm.scaledToHeight(
                max(1, round(pm.height() * factor)),
                Qt.TransformationMode.FastTransformation)
        if mirror:
            pm = pm.transformed(QTransform().scale(-1, 1))
        return pm


_sprite_store = SpriteStore()


def _pm(w: int, h: int) -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def _scale(pm: QPixmap, f: float = 2.0) -> QPixmap:
    return pm.scaled(int(pm.width() * f), int(pm.height() * f),
                     Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.FastTransformation)


def _draw_weapon(p: QPainter, class_id: str, state: str, i: int) -> None:
    wood = QColor("#7a5230")
    if class_id == "ranger":
        p.fillRect(12, 4, 1, 9, wood)
        p.fillRect(11, 3, 1, 1, wood)
        p.fillRect(11, 13, 1, 1, wood)
        if state == "attack":
            j = i % 3
            pull = (11, 9, 11)[j]
            p.fillRect(pull, 5, 1, 7, QColor("#d8d8c8"))
            if j == 0:
                p.fillRect(9, 8, 5, 1, QColor("#a08050"))
            elif j == 1:
                p.fillRect(7, 8, 6, 1, QColor("#a08050"))
            else:
                p.fillRect(14, 8, 2, 1, QColor("#a08050"))
        else:
            p.fillRect(11, 5, 1, 7, QColor("#b8b8a8"))
    elif class_id == "sorceress":
        orb = QColor("#66e0ff")
        if state == "attack":
            j = i % 3
            p.fillRect(11, 2, 1, 12, wood)
            p.fillRect(10, 0, 3, 3, orb)
            if j >= 1:
                p.fillRect(11, 1, 1, 1, QColor("#ffffff"))
            if j == 2:
                p.fillRect(13, 3, 1, 1, orb)
                p.fillRect(14, 5, 1, 1, orb)
                p.fillRect(15, 7, 1, 1, orb)
        else:
            p.fillRect(11, 3, 1, 11, wood)
            p.fillRect(10, 1, 3, 2, orb)
    else:
        blade = QColor("#b8b8c0")
        if state == "attack":
            j = i % 3
            if j == 0:
                p.fillRect(10, 2, 1, 6, wood)
                p.fillRect(8, 1, 3, 2, blade)
            elif j == 1:
                p.fillRect(11, 1, 1, 6, wood)
                p.fillRect(10, 0, 4, 2, blade)
            else:
                p.fillRect(10, 7, 5, 1, wood)
                p.fillRect(14, 5, 2, 3, blade)
        else:
            p.fillRect(11, 5, 1, 6, wood)
            p.fillRect(10, 3, 4, 2, blade)


def _hero_pix(class_id: str, state: str, i: int) -> QPixmap:
    st = CLASS_STYLE.get(class_id, CLASS_STYLE["berserker"])
    body, pants, hair = QColor(st["body"]), QColor(st["pants"]), QColor(st["hair"])
    skin = QColor(_SKIN)
    if state == "dead":
        pm = _pm(16, 8)
        p = QPainter(pm)
        p.fillRect(4, 4, 8, 3, body)
        p.fillRect(1, 4, 3, 3, skin)
        p.fillRect(12, 5, 3, 2, pants)
        p.end()
        return pm
    pm = _pm(16, 16)
    p = QPainter(pm)
    if class_id == "sorceress":
        p.fillRect(4, 5, 6, 8, body)
        p.fillRect(4, 12, 6, 1, body.darker(140))
        f = (0, 1, 0, -1)[i % 4] if state == "walk" else 0
        p.fillRect(5 + f, 13, 2, 3, pants)
        p.fillRect(8 - f, 13, 2, 3, pants)
    else:
        legs = _LEG_FRAMES[i % 4] if state == "walk" else _LEG_FRAMES[0]
        for lx, ly, lw, lh in legs:
            p.fillRect(lx, ly, lw, lh, pants)
            p.fillRect(lx, ly + lh - 1, lw, 1, pants.darker(160))
        p.fillRect(4, 5, 6, 5, body)
        p.fillRect(4, 9, 6, 1, body.darker(150))
    p.fillRect(5, 1, 4, 4, skin)
    p.fillRect(5, 0, 4, 2, hair)
    p.fillRect(8, 3, 1, 1, QColor("#201818"))
    p.fillRect(9, 5, 1, 3, skin)
    _draw_weapon(p, class_id, state, i)
    p.end()
    return pm


_hero_cache: dict[str, dict[str, list[QPixmap]]] = {}


def make_hero_frames(class_id: str) -> dict[str, list[QPixmap]]:
    if class_id not in _hero_cache:
        # _draw_entity draws heroes unflipped when facing right, so the base
        # frames must face right: mirror PNGs only if they face left.
        sprite = _sprite_store.frames(class_id, mirror=not SPRITE_FACES_RIGHT)
        if sprite is not None:
            _hero_cache[class_id] = sprite
        else:
            _hero_cache[class_id] = {
                "walk": [_scale(_hero_pix(class_id, "walk", i)) for i in range(4)],
                "attack": [_scale(_hero_pix(class_id, "attack", i)) for i in range(3)],
                "dead": [_scale(_hero_pix(class_id, "dead", 0))],
            }
    return _hero_cache[class_id]


def _monster_pix(bw: int, bh: int, color: str, state: str, i: int, is_boss: bool) -> QPixmap:
    c = QColor(color)
    if not c.isValid():
        c = QColor(_DEFAULT_STYLE[0])
    dark, light = c.darker(160), c.lighter(130)
    if state == "dead":
        pm = _pm(bh, 6)
        p = QPainter(pm)
        p.fillRect(1, 2, bh - 2, 3, c.darker(130))
        p.fillRect(2, 3, 1, 1, QColor("#181818"))
        p.end()
        return pm
    oy = 3 if is_boss else 0
    pm = _pm(bw, bh + oy)
    p = QPainter(pm)
    legs_h = 3
    body_y = oy + 2
    body_h = bh - 2 - legs_h
    dx = -1 if (state == "attack" and i % 2 == 1) else 0
    p.fillRect(1 + dx, body_y, bw - 2, body_h, c)
    p.fillRect(1 + dx, body_y, bw - 2, 1, light)
    p.fillRect(1 + dx, body_y + body_h - 1, bw - 2, 1, dark)
    p.fillRect(1 + dx, body_y - 1, 1, 1, dark)
    p.fillRect(bw - 2 + dx, body_y - 1, 1, 1, dark)
    eye = QColor("#ffdd44") if (state == "attack" and i % 2 == 1) else QColor("#ff3434")
    p.fillRect(2 + dx, body_y + 2, 1, 1, eye)
    p.fillRect(4 + dx, body_y + 2, 1, 1, eye)
    ly = oy + bh - legs_h
    if state == "attack" or i % 2 == 0:
        p.fillRect(2, ly, 2, legs_h, dark)
        p.fillRect(bw - 4, ly, 2, legs_h, dark)
    else:
        p.fillRect(1, ly, 2, legs_h, dark)
        p.fillRect(bw - 3, ly, 2, legs_h - 1, dark)
    if state == "attack":
        if i % 2 == 0:
            p.fillRect(0, body_y + 3, 1, 2, dark)
        else:
            p.fillRect(0, body_y + 2, 2, 2, dark)
    if is_boss:
        gold = QColor("#ffd24a")
        p.fillRect(2, 1, bw - 4, 1, gold)
        p.fillRect(2, 0, 1, 1, gold)
        p.fillRect(bw // 2, 0, 1, 1, gold)
        p.fillRect(bw - 3, 0, 1, 1, gold)
    p.end()
    return pm


_monster_cache: dict[tuple, dict[str, list[QPixmap]]] = {}


def make_monster_frames(monster_id: str, color: str, size: str, is_boss: bool) -> dict[str, list[QPixmap]]:
    key = (monster_id, color, size, is_boss)
    if key not in _monster_cache:
        # _draw_entity draws monsters unflipped when facing left (toward the
        # hero), so base frames must face left: mirror right-facing PNGs.
        sprite = _sprite_store.frames(monster_id, mirror=SPRITE_FACES_RIGHT)
        if sprite is not None:
            _monster_cache[key] = sprite
            return sprite
        bw, bh = _SIZE_PX.get(size, _SIZE_PX["medium"])
        f = 2.0 * 1.4 if is_boss else 2.0
        if is_boss:
            f = min(f, 50.0 / (bh + 3))
        _monster_cache[key] = {
            "walk": [_scale(_monster_pix(bw, bh, color, "walk", i, is_boss), f) for i in range(2)],
            "attack": [_scale(_monster_pix(bw, bh, color, "attack", i, is_boss), f) for i in range(2)],
            "dead": [_scale(_monster_pix(bw, bh, color, "dead", 0, is_boss), f)],
        }
    return _monster_cache[key]


_flash_cache: dict[int, QPixmap] = {}


def _flash_frame(pm: QPixmap) -> QPixmap:
    """White-tinted copy of a frame, keyed by the source pixmap's cacheKey."""
    key = pm.cacheKey()
    if key not in _flash_cache:
        if len(_flash_cache) > 256:
            _flash_cache.clear()
        out = QPixmap(pm.size())
        out.fill(Qt.GlobalColor.transparent)
        q = QPainter(out)
        q.drawPixmap(0, 0, pm)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        q.fillRect(out.rect(), QColor(255, 255, 255, 210))
        q.end()
        _flash_cache[key] = out
    return _flash_cache[key]


# E.6: monster rarity outline. A solid-colour silhouette of the sprite's alpha
# mask, blitted at 8 surrounding ±2px offsets UNDER the sprite so a coloured ring
# leaks out around the edge. Cached by (sprite cacheKey, colour) — computed once
# per (frame, tier), never per-tick (the 30 FPS budget is sacred, spec §E.6).
_outline_cache: dict[tuple[int, str], QPixmap] = {}
_OUTLINE_PX = 2
_OUTLINE_ALPHA = 200

def _outline_frame(pm: QPixmap, color_hex: str) -> QPixmap:
    """Ring-shaped coloured halo matching the sprite silhouette, size-padded by 2px."""
    key = (pm.cacheKey(), color_hex)
    cached = _outline_cache.get(key)
    if cached is not None:
        return cached
    if len(_outline_cache) > 256:
        _outline_cache.clear()
    d = _OUTLINE_PX
    # solid-colour silhouette (alpha mask tinted to the tier colour)
    col = QColor(color_hex)
    col.setAlpha(_OUTLINE_ALPHA)
    sil = QPixmap(pm.size())
    sil.fill(Qt.GlobalColor.transparent)
    q = QPainter(sil)
    q.drawPixmap(0, 0, pm)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    q.fillRect(sil.rect(), col)
    q.end()
    # pad canvas by d on every side, stamp the silhouette at the 8 neighbours
    out = QPixmap(pm.width() + 2 * d, pm.height() + 2 * d)
    out.fill(Qt.GlobalColor.transparent)
    q = QPainter(out)
    for dx, dy in ((-d, 0), (d, 0), (0, -d), (0, d),
                   (-d, -d), (d, -d), (-d, d), (d, d)):
        q.drawPixmap(d + dx, d + dy, sil)
    q.end()
    _outline_cache[key] = out
    return out


_tint_cache: dict[tuple[int, int], QPixmap] = {}


def _tint_frame(pm: QPixmap, color: QColor) -> QPixmap:
    """Copy of a frame colour-shifted toward `color`, keeping the original shape
    and shading. Used to recolour the arrow/bolt projectile by damage type so an
    elemental skill (poison/lightning/fire arrow) reuses the base arrow sprite in
    its element's colour instead of needing its own VFX sheet. Cached by
    (source pixmap, colour)."""
    key = (pm.cacheKey(), color.rgba())
    cached = _tint_cache.get(key)
    if cached is None:
        if len(_tint_cache) > 256:
            _tint_cache.clear()
        out = QPixmap(pm.size())
        out.fill(Qt.GlobalColor.transparent)
        q = QPainter(out)
        q.drawPixmap(0, 0, pm)
        # Multiply keeps the sprite's internal shading; a softer overlay on top
        # lifts the hue so dark arrows still read as coloured.
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        q.fillRect(out.rect(), color)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        soft = QColor(color)
        soft.setAlpha(120)
        q.fillRect(out.rect(), soft)
        q.end()
        _tint_cache[key] = out
        cached = out
    return cached


class FlairSystem:
    def __init__(self) -> None:
        self._items: list[dict] = []
        self._sprites: list[dict] = []
        self._rng = random.Random()

    def _spawn_vfx(self, effect: str, x: float, h: int,
                   origin: float | None = None, travel_frac: float = 0.0,
                   target: object | None = None, alt: int = 0,
                   tint: QColor | None = None) -> bool:
        if not VFX.frames(effect, h):
            return False
        self._sprites.append(dict(effect=effect, x=x, h=h, t=0.0,
                                  origin=origin, travel_frac=travel_frac,
                                  target=target, alt=alt, tint=tint))
        return True

    def add_events(self, events: list[CombatEvent]) -> None:
        for e in events:
            if e.kind == "damage":
                it = dict(text=str(int(round(e.value))),
                          color=QColor(DTYPE_COLORS.get(e.dtype, "#ffffff")),
                          px=9, ttl=0.8, bold=False)
            elif e.kind == "dot":
                if e.value < 1:
                    continue
                it = dict(text=str(int(round(e.value))),
                          color=QColor("#9a70d0"), px=7, ttl=0.5, bold=False)
            elif e.kind == "crit":
                hits = [k for k in VFX._load_manifest() if k.startswith("hit")]
                if hits:
                    self._spawn_vfx(self._rng.choice(hits), e.x, 34)
                it = dict(text=f"{int(round(e.value))}!", color=QColor("#ffaa22"),
                          px=13, ttl=0.9, bold=True)
            elif e.kind == "heal":
                it = dict(text=f"+{int(round(e.value))}", color=QColor("#55e055"),
                          px=9, ttl=0.8, bold=False)
            elif e.kind == "miss":
                # evasion dodge (audit H1): show a faint "miss" so the dodge reads.
                it = dict(text="miss", color=QColor("#aab4c0"),
                          px=8, ttl=0.6, bold=False)
            elif e.kind == "levelup":
                if self._spawn_vfx("levelup", e.x, 56):
                    continue
                it = dict(text=e.text or "LEVEL UP!", color=QColor("#ffd700"),
                          px=12, ttl=1.4, bold=True)
            elif e.kind == "skill":
                # Projectile skills fly from caster to target over the sheet's
                # launch frames; the rest of the sheet is the on-target explosion.
                # The sprite homes onto the live monster so the blast tracks it
                # even as the mob keeps moving.
                origin = getattr(e, "origin", None)
                tf = _SKILL_TRAVEL_FRAC.get(e.text, 0.0) if origin is not None else 0.0
                if self._spawn_vfx(f"skill_{e.text}", e.x, 56, origin=origin,
                                   travel_frac=tf, target=getattr(e, "target", None)):
                    continue
                # No dedicated sheet: if this is a projectile skill, fire the
                # class's base arrow/bolt recoloured by damage type (poison arrow
                # = purple, lightning = yellow, fire = orange). Cheap stand-in
                # that reads as "an elemental shot" without bespoke art.
                is_proj, sdt = _skill_proj_info(e.text)
                base_proj = _CLASS_PROJ.get(getattr(e, "class_id", "")) if is_proj else None
                if base_proj:
                    override = _SKILL_TINT_OVERRIDE.get(e.text)
                    if override:
                        tint = QColor(override)
                    elif sdt != DamageType.PHYS:
                        tint = QColor(DTYPE_COLORS.get(sdt, "#ffffff"))
                    else:
                        tint = None  # plain phys arrow, no recolour
                    label_col = tint or QColor("#ffd24a")
                    if self._spawn_vfx(base_proj, e.x, _PROJ_H.get(base_proj, 16),
                                       origin=origin,
                                       travel_frac=_PROJ_TRAVEL_FRAC.get(base_proj, 0.9),
                                       target=getattr(e, "target", None),
                                       alt=_PROJ_ALT.get(base_proj, 0),
                                       tint=tint):
                        label = (e.text or "skill").replace("_", " ").title()
                        it = dict(text=label, color=label_col, px=10, ttl=0.7, bold=True)
                        it.update(x=e.x + self._rng.uniform(-6, 6),
                                  y=26.0 + self._rng.uniform(-3, 3), t=0.0, vy=24.0)
                        self._items.append(it)
                        continue
                # Skills V2 stub: no real VFX sheet for this skill id yet. Draw a
                # procedural placeholder so the cast is still visible instead of
                # silent nothing. Ignore origin/travel_frac here — the stub just
                # pops on the target. A generic "hit" flash is spawned if any is
                # available (same sheets crit reuses), otherwise the label alone.
                hits = [k for k in VFX._load_manifest() if k.startswith("hit")]
                if hits:
                    self._spawn_vfx(self._rng.choice(hits), e.x, 34,
                                    target=getattr(e, "target", None))
                label = (e.text or "skill").replace("_", " ").title()
                it = dict(text=label, color=QColor("#ffd24a"),
                          px=11, ttl=0.7, bold=True)
            elif e.kind == "proj":
                # ranged auto-attack: projectile sheet homes hero -> target,
                # then bursts on impact. text is the effect id (proj_mage/arrow).
                origin = getattr(e, "origin", None)
                tf = _PROJ_TRAVEL_FRAC.get(e.text, 0.9)
                self._spawn_vfx(e.text, e.x, _PROJ_H.get(e.text, 16),
                                origin=origin, travel_frac=tf,
                                target=getattr(e, "target", None),
                                alt=_PROJ_ALT.get(e.text, 0))
                continue
            elif e.kind == "loot":
                name, _, col = e.text.partition("|")
                color = QColor(col.strip()) if col.strip() else QColor()
                if not color.isValid():
                    color = QColor(RARITY_COLORS[Rarity.NORMAL])
                it = dict(text=name, color=color, px=9, ttl=1.4, bold=False)
            else:
                continue
            it.update(x=e.x + self._rng.uniform(-6, 6),
                      y=26.0 + self._rng.uniform(-3, 3), t=0.0, vy=24.0)
            self._items.append(it)

    def tick(self, dt: float) -> None:
        for it in self._items:
            it["t"] += dt
            it["y"] -= it["vy"] * dt
        self._items = [it for it in self._items if it["t"] < it["ttl"]]
        for s in self._sprites:
            s["t"] += dt
        self._sprites = [
            s for s in self._sprites
            if s["t"] * VFX.fps(s["effect"]) < len(VFX.frames(s["effect"], s["h"]))
        ]

    def paint(self, p: QPainter, camera_x: float) -> None:
        for s in self._sprites:
            fl = VFX.frames(s["effect"], s["h"])
            i = int(s["t"] * VFX.fps(s["effect"]))
            if 0 <= i < len(fl):
                pm = fl[i]
                # elemental projectile stand-in: recolour the base arrow/bolt by
                # damage type (skills with no dedicated VFX sheet).
                tint = s.get("tint")
                if tint is not None:
                    pm = _tint_frame(pm, tint)
                # home onto the live monster so the blast tracks it as it moves
                tgt = s.get("target")
                dest = getattr(tgt, "x", None)
                if dest is None:
                    dest = s["x"]
                x = dest
                origin = s.get("origin")
                tf = s.get("travel_frac", 0.0)
                if origin is not None and tf > 0 and len(fl) > 1:
                    # lerp caster -> live target across the first travel_frac of frames
                    prog = min(1.0, (i / len(fl)) / tf)
                    x = origin + (dest - origin) * prog
                p.drawPixmap(round(x - camera_x - pm.width() / 2),
                             H - PATH_H + 2 - pm.height() - s.get("alt", 0), pm)
        for it in self._items:
            a = max(0.0, min(1.0, (it["ttl"] - it["t"]) / (it["ttl"] * 0.4)))
            f = QFont("Verdana")
            f.setPixelSize(it["px"])
            f.setBold(it["bold"])
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(it["text"])
            x = it["x"] - camera_x - tw / 2
            sh = QColor(0, 0, 0)
            sh.setAlphaF(a * 0.7)
            p.setPen(sh)
            p.drawText(QPointF(x + 1, it["y"] + 1), it["text"])
            c = QColor(it["color"])
            c.setAlphaF(a)
            p.setPen(c)
            p.drawText(QPointF(x, it["y"]), it["text"])


class GameRenderer:
    def __init__(self) -> None:
        self._far: dict[tuple, QPixmap] = {}
        self._ground: dict[str, QPixmap] = {}
        self._bg = BackgroundStore()

    def paint(self, p: QPainter, w: int, h: int, hero: Hero, monsters: list[Monster],
              flair: "FlairSystem", bg_theme: str, camera_x: float,
              zone_name: str = "", kills: int = 0, kills_to_boss: int = 0,
              boss_spawned: bool = False, boss_killed: bool = False,
              has_boss: bool = True) -> None:
        bg = self._bg.tile(bg_theme, h)
        if bg is not None:
            self._blit_tiles(p, bg, w, 0, camera_x * 0.5)
        else:
            theme = THEMES.get(bg_theme) or THEMES["forest"]
            g = QLinearGradient(0, 0, 0, h)
            g.setColorAt(0.0, QColor(theme["sky"][0]))
            g.setColorAt(1.0, QColor(theme["sky"][1]))
            p.fillRect(0, 0, w, h, g)
            self._blit_tiles(p, self._far_tile(bg_theme, h), w, 0, camera_x * 0.3)
            self._blit_tiles(p, self._ground_tile(bg_theme), w, h - GROUND_H, camera_x)
        # dark walking path: entities plant their feet 2px into it
        p.fillRect(0, h - PATH_H, w, PATH_H, QColor(10, 8, 6, 95))
        p.fillRect(0, h - PATH_H, w, 1, QColor(0, 0, 0, 150))
        baseline = h - PATH_H + 2
        for m in monsters:
            col, sz = MONSTER_STYLE.get(m.monster_id, _DEFAULT_STYLE)
            frames = make_monster_frames(m.monster_id, col, sz, m.is_boss)
            spm = self._draw_entity(p, m, frames, baseline, camera_x, w, flip_positive=True)
            if spm and m.alive and m.hp < m.max_hp:
                self._hp_bar(p, m, spm, baseline, camera_x, QColor("#e03030"))
            if (spm and m.alive and active_icons is not None
                    and getattr(m, "_ailments", None) is not None):
                self._ailment_dots(p, m, spm, baseline, camera_x)
        frames = make_hero_frames(hero.class_id)
        spm = self._draw_entity(p, hero, frames, baseline, camera_x, w, flip_positive=False)
        if spm and hero.alive:
            self._hp_bar(p, hero, spm, baseline, camera_x, QColor("#3ed23e"))
            f = QFont("Verdana")
            f.setPixelSize(8)
            p.setFont(f)
            label = f"{hero.name} lv.{hero.level}"
            tw = p.fontMetrics().horizontalAdvance(label)
            tx = round(getattr(hero, "_dx", hero.x) - camera_x - tw / 2)
            ty = baseline - spm.height() - 8
            p.setPen(QColor("#101010"))
            p.drawText(tx + 1, ty + 1, label)
            p.setPen(QColor("#f0e6c8"))
            p.drawText(tx, ty, label)
        flair.paint(p, camera_x)
        if zone_name:
            self._draw_hud(p, zone_name, kills, kills_to_boss, boss_spawned,
                           boss_killed, has_boss)

    def _draw_hud(self, p: QPainter, zone_name: str, kills: int, kills_to_boss: int,
                  boss_spawned: bool, boss_killed: bool, has_boss: bool = True) -> None:
        # no kill counter by user's request — zone name only, plus BOSS!/cleared state
        if boss_killed:
            text = f"{zone_name}  ·  cleared"
        elif boss_spawned:
            text = f"{zone_name}  ·  BOSS!"
        else:
            text = zone_name
        f = QFont("Verdana")
        f.setPixelSize(8)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(text)
        x, y = 6, 4
        p.fillRect(x - 3, y, tw + 6, 12, QColor(0, 0, 0, 110))
        p.setPen(QColor("#101010"))
        p.drawText(x + 1, y + 10, text)
        p.setPen(QColor("#ffd700") if boss_spawned and not boss_killed else QColor("#e8dcc0"))
        p.drawText(x, y + 9, text)
        # W3.1 (PG-3): boss progress — only pre-spawn in zones that have a boss
        if has_boss and kills_to_boss > 0 and not boss_spawned and not boss_killed:
            done = min(kills, kills_to_boss)
            label = f"Boss: {done}/{kills_to_boss}"
            f2 = QFont("Verdana")
            f2.setPixelSize(7)
            p.setFont(f2)
            lw = p.fontMetrics().horizontalAdvance(label)
            by = y + 14
            bar_w, bar_h = 40, 3
            p.fillRect(x - 3, by, max(lw, bar_w) + 6, 9 + bar_h, QColor(0, 0, 0, 90))
            p.setPen(QColor("#101010"))
            p.drawText(x + 1, by + 8, label)
            p.setPen(QColor("#c8b890"))
            p.drawText(x, by + 7, label)
            bar_y = by + 9
            p.fillRect(x, bar_y, bar_w, bar_h, QColor(0, 0, 0, 110))
            fill = round((bar_w - 2) * done / kills_to_boss)
            if fill > 0:
                p.fillRect(x + 1, bar_y + 1, fill, bar_h - 2, QColor("#ffd24a"))

    def _draw_entity(self, p: QPainter, e, frames: dict[str, list[QPixmap]],
                     baseline: int, camera_x: float, w: int, flip_positive: bool) -> QPixmap | None:
        state = e.anim if e.anim in frames else ("dead" if not e.alive else "walk")
        fl = frames[state]
        # short procedural loops look right at 8 fps; long cut sequences need more
        fps = 8 if len(fl) <= 8 else 14
        pm = fl[int(e.anim_t * fps) % len(fl)]
        flip = (e.facing == 1) if flip_positive else (e.facing == -1)
        if flip:
            pm = pm.transformed(QTransform().scale(-1, 1))
        sx = getattr(e, "_dx", e.x) - camera_x
        if sx < -40 or sx > w + 40:
            return None
        if getattr(e, "_flash", 0.0) > 0 and e.alive:
            pm = _flash_frame(pm)
        alpha = 1.0
        if not e.alive and isinstance(e, Monster):
            # corpse fades out over its last DEATH_FADE seconds of linger
            alpha = max(0.0, min(1.0, (CORPSE_LINGER - e.anim_t) / DEATH_FADE))
            if alpha <= 0.0:
                return None
        if alpha < 1.0:
            p.setOpacity(alpha)
        px = round(sx - pm.width() / 2)
        py = baseline - pm.height()
        # E.6: rarity outline drawn UNDER the sprite (live mobs only, not corpses)
        if e.alive and isinstance(e, Monster):
            oc = mob_rarity.OUTLINE_COLOR.get(mob_rarity.tier_of(e))
            if oc:
                halo = _outline_frame(pm, oc)
                p.drawPixmap(px - _OUTLINE_PX, py - _OUTLINE_PX, halo)
        p.drawPixmap(px, py, pm)
        if alpha < 1.0:
            p.setOpacity(1.0)
        return pm

    def _hp_bar(self, p: QPainter, e, spm: QPixmap, baseline: int,
                camera_x: float, color: QColor) -> None:
        bw = max(16, min(30, spm.width()))
        sx = round(getattr(e, "_dx", e.x) - camera_x - bw / 2)
        y = baseline - spm.height() - 5
        p.fillRect(sx, y, bw, 3, QColor("#241418"))
        frac = max(0.0, min(1.0, e.hp / e.max_hp if e.max_hp else 0.0))
        p.fillRect(sx + 1, y + 1, max(0, round((bw - 2) * frac)), 1, color)

    def _ailment_dots(self, p: QPainter, m, spm: QPixmap, baseline: int,
                      camera_x: float) -> None:
        """Tiny 3x3 dots in the free row above the HP bar, one per ailment."""
        names = active_icons(m)
        if not names:
            return
        bw = max(16, min(30, spm.width()))
        sx = round(getattr(m, "_dx", m.x) - camera_x - bw / 2)
        dy = baseline - spm.height() - 5 - 4  # bar top is -5; 3px dot + 1px gap
        for name in names:
            col = AILMENT_COLORS.get(name)
            if col:
                p.fillRect(sx, dy, 3, 3, QColor(col))
                sx += 4

    def _blit_tiles(self, p: QPainter, tile: QPixmap, w: int, y: int, off: float) -> None:
        tw = tile.width()
        x = -int(off % tw)
        while x < w:
            p.drawPixmap(x, y, tile)
            x += tw

    def _far_tile(self, theme_id: str, h: int) -> QPixmap:
        key = (theme_id, h)
        if key not in self._far:
            t = THEMES.get(theme_id) or THEMES["forest"]
            far = QColor(t["far"])
            tw = 240
            pm = _pm(tw, h)
            p = QPainter(pm)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(far)
            gy = h - GROUND_H
            if theme_id == "beach":
                p.fillRect(0, gy - 16, tw, 6, far.lighter(120))
                for x, wl in ((5, 90), (85, 120), (170, 85)):
                    p.drawEllipse(x, gy - 12, wl, 24)
            elif theme_id == "desert":
                for x, wl, dh in ((0, 110, 14), (75, 130, 18), (165, 100, 12)):
                    p.drawEllipse(x, gy - dh, wl, dh * 2)
            elif theme_id in ("swamp", "jungle"):
                for x in (18, 62, 118, 168, 212):
                    th = 16 + (x * 7) % 12
                    p.fillRect(x, gy - th, 2, th, far)
                    p.fillRect(x - 3, gy - th + 4, 4, 1, far)
                    p.fillRect(x + 1, gy - th + 9, 4, 1, far)
            elif theme_id == "cave":
                for x in (12, 55, 95, 140, 185, 220):
                    tl = 12 + (x * 3) % 10
                    p.drawPolygon(QPolygonF([QPointF(x, 0), QPointF(x + 9, 0),
                                             QPointF(x + 4.5, tl)]))
                for x in (32, 78, 122, 166, 205):
                    th = 8 + (x * 5) % 8
                    p.drawPolygon(QPolygonF([QPointF(x, gy), QPointF(x + 8, gy),
                                             QPointF(x + 4, gy - th)]))
            elif theme_id == "ruins":
                for x in (15, 58, 104, 150, 196):
                    ch = 14 + (x * 3) % 12
                    p.fillRect(x, gy - ch, 5, ch, far)
                    p.fillRect(x - 1, gy - ch - 2, 7, 2, far)
                p.fillRect(74, gy - 7, 22, 7, far)
            elif theme_id in ("tomb", "temple"):
                for x in (12, 52, 96, 142, 188, 224):
                    ch = 16 + (x * 5) % 10
                    p.fillRect(x, gy - ch, 6, ch, far)
                    p.fillRect(x - 2, gy - ch - 2, 10, 2, far)
                    p.fillRect(x - 1, gy - 2, 8, 2, far)
                if theme_id == "temple":
                    p.fillRect(88, gy - 30, 64, 3, far)
            else:
                for x in (2, 44, 88, 132, 176, 214):
                    th = 20 + (x * 5) % 12
                    p.drawPolygon(QPolygonF([QPointF(x, gy), QPointF(x + 18, gy),
                                             QPointF(x + 9, gy - th)]))
            p.end()
            self._far[key] = pm
        return self._far[key]

    def _ground_tile(self, theme_id: str) -> QPixmap:
        if theme_id not in self._ground:
            t = THEMES.get(theme_id) or THEMES["forest"]
            pm = QPixmap(120, GROUND_H)
            pm.fill(QColor(t["ground"]))
            p = QPainter(pm)
            p.fillRect(0, 0, 120, 1, QColor(t["ground_top"]))
            rng = random.Random(sum(map(ord, theme_id)))
            dot = QColor(t["dots"])
            for _ in range(34):
                p.fillRect(rng.randrange(120), rng.randrange(2, GROUND_H), 1, 1, dot)
            p.end()
            self._ground[theme_id] = pm
        return self._ground[theme_id]


if __name__ == "__main__":
    import sys
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
    from PyQt6.QtWidgets import QApplication
    from game.core import Stats
    app = QApplication(sys.argv)

    for cid in ("berserker", "ranger", "sorceress"):
        fr = make_hero_frames(cid)
        assert len(fr["walk"]) == 4 and len(fr["attack"]) == 3 and len(fr["dead"]) == 1
    for mid, (col, sz) in MONSTER_STYLE.items():
        make_monster_frames(mid, col, sz, False)
        make_monster_frames(mid, col, sz, True)

    # PNG sprite path: warrior hero + goblin/orc monsters
    assert _sprite_store.has("warrior") and _sprite_store.has("goblin")
    wfr = make_hero_frames("warrior")
    # warrior v2 art renders at manifest height (44); the invariant that matters is
    # walk and attack share one scale factor (the old bust-vs-fullbody bug), not a
    # magic constant — assert consistency + a sane range instead of an exact px.
    _wh = wfr["walk"][0].height()
    assert 36 <= _wh <= 52, _wh
    assert abs(wfr["attack"][0].height() - _wh) <= 6, (wfr["attack"][0].height(), _wh)
    assert len(wfr["attack"]) >= 5 and len(wfr["dead"]) == 1
    assert len(wfr["walk"]) >= 8, len(wfr["walk"])
    gfr = make_monster_frames("goblin", *MONSTER_STYLE["goblin"], False)
    assert gfr["walk"][0].height() >= 26 and len(gfr["attack"]) >= 4
    # orc renders at its manifest height (semantic size ladder, HUMAN rung=42);
    # read it from the store rather than hard-coding so retiering can't break this.
    _orc_h = int(_sprite_store._load_manifest()["orc"]["h"])
    ofr = make_monster_frames("orc", *MONSTER_STYLE["orc"], False)
    assert ofr["walk"][0].height() == _orc_h, (ofr["walk"][0].height(), _orc_h)
    # procedural fallback path: force the id past the sprite store with a bogus id.
    tfr = make_monster_frames("__no_art__", "#909090", "medium", False)
    assert len(tfr["walk"]) == 2

    hero = Hero(name="Exile", stats=Stats(), base_stats=Stats(),
                class_id="warrior", level=7, x=300.0)
    hero.init_hp()
    hero.hp = hero.max_hp * 0.7
    hero.anim = "attack"
    hero.anim_t = 0.15

    def mk(mid: str, x: float, anim: str = "walk", frac: float = 1.0, boss: bool = False) -> Monster:
        m = Monster(name=mid, stats=Stats(life=40), x=x, monster_id=mid,
                    is_boss=boss, facing=-1)
        m.init_hp()
        m.hp = m.max_hp * frac
        m.anim = anim
        m.anim_t = 0.3
        m.alive = anim != "dead"
        return m

    monsters = [
        mk("skeleton", 380, "dead", 0.0),
        mk("goblin", 430, "walk", 0.55),
        mk("orc", 480, "attack", 0.8),
        mk("goblin_king", 560, "walk", 0.9, boss=True),
        mk("tomb_snake", 660, frac=0.7),
        mk("unknown_mob", 740, frac=0.4),
    ]

    # ailment dots: fake state on the goblin, active_icons stubbed in-module
    monsters[1]._ailments = object()
    active_icons = lambda t: ["ignite", "poison"]  # noqa: E731

    flair = FlairSystem()
    flair.add_events([
        CombatEvent("damage", 430, 12, DamageType.PHYS),
        CombatEvent("crit", 480, 48, DamageType.FIRE),
        CombatEvent("damage", 560, 9, DamageType.COLD),
        CombatEvent("levelup", 300, text="LEVEL 7!"),
        CombatEvent("loot", 505, text="Viper Blade|#8888ff"),
    ])
    flair.tick(0.1)

    # skill-cast VFX: manifest entries present, events spawn sprites, wide
    # piercing_shot frames and unknown skills don't crash
    for eff in ("skill_fireball", "skill_cleave", "skill_piercing_shot"):
        assert eff in VFX._load_manifest(), f"{eff} missing from vfx manifest"
        assert VFX.frames(eff, 56), f"{eff} frames failed to load"
    n_before = len(flair._sprites)
    items_before = len(flair._items)
    flair.add_events([
        CombatEvent("skill", 430, text="fireball"),
        CombatEvent("skill", 480, text="piercing_shot"),
        CombatEvent("skill", 520, text="no_such_skill"),
    ])
    # fireball + piercing_shot have real sheets -> 2 sprites, no labels.
    # no_such_skill has no sheet -> procedural stub: a "No Such Skill" label
    # (always) plus a generic hit flash sprite when any hit sheet exists.
    real_sprites = 2
    has_hit = any(k.startswith("hit") for k in VFX._load_manifest())
    stub_sprites = 1 if has_hit else 0
    assert len(flair._sprites) == n_before + real_sprites + stub_sprites, len(flair._sprites)
    stub_labels = [it["text"] for it in flair._items[items_before:]]
    assert "No Such Skill" in stub_labels, stub_labels
    print(f"skill stub OK: label={stub_labels} flash_sprite={bool(stub_sprites)}")
    flair.tick(0.05)

    canvas = QPixmap(1200, H)
    canvas.fill(QColor("#101010"))
    p = QPainter(canvas)
    r = GameRenderer()
    r.paint(p, 1200, H, hero, monsters, flair, "desert", hero.x - 120,
            zone_name="Twilight Shore", kills=17, kills_to_boss=30)
    p.end()
    img = canvas.toImage()
    found = {c: False for c in ("#ff6a2a", "#55cc33")}
    for yy in range(H):
        for xx in range(200, 320):  # goblin is at x=430, camera_x=180
            name = QColor(img.pixel(xx, yy)).name()
            if name in found:
                found[name] = True
    assert all(found.values()), f"ailment dots missing: {found}"
    # W3.1: boss progress bar fill (#ffd24a) must appear in the HUD corner
    bar_found = any(QColor(img.pixel(xx, yy)).name() == "#ffd24a"
                    for yy in range(0, 36) for xx in range(0, 60))
    assert bar_found, "boss progress bar missing from HUD"
    # has_boss=False must not draw it
    canvas2 = QPixmap(300, H)
    canvas2.fill(QColor("#101010"))
    p2 = QPainter(canvas2)
    r.paint(p2, 300, H, hero, [], flair, "desert", hero.x - 120,
            zone_name="Town", kills=17, kills_to_boss=30, has_boss=False)
    p2.end()
    img2 = canvas2.toImage()
    assert not any(QColor(img2.pixel(xx, yy)).name() == "#ffd24a"
                   for yy in range(0, 36) for xx in range(0, 60)), \
        "progress bar drawn for bossless zone"
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_render_test.png")
    canvas.save(out)
    print("OK", out)
