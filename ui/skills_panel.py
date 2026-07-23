"""Bar of Exile — Skills panel V2 (Gem Souls).

Three columns (§8 of SKILLS_MECHANICS_V2):
  - LEFT   : 4×4 grid of the class's 16 skills. Locked = dark + level tag.
             Click an unlocked skill to equip it into the common pool.
  - CENTER : the loadout bar — Primary (auto-attack, always on) + a shared pool
             of skill slots that open at levels 1/25/50/75. ANY skill type
             (spender/aura/utility/ultimate) competes for the same pool, so you
             pick at most 4 skills total. ▲/▼ reorder the cast priority; ✕
             unequips. Open-but-empty slots glow; locked slots show their level.
  - RIGHT  : the selected skill's card — rank bar (skill-xp progress) and the
             four talent tiers (rank 5/10/15/20, pick 1 of 3), plus a per-skill
             talent respec.

All state changes go through game.skills_v2 pure helpers — this file only draws
and dispatches, it never edits hero.skills_v2 directly.

Public contract (main.py depends on it, do not break):
    SkillsPanel(hero, on_change) ; .refresh()
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from game.core import Hero, DTYPE_COLORS, DamageType
from game import skills_v2 as SV
from ui.panels import (
    BTN_QSS, PanelFrame, _tip, skill_pixmap, SKILL_ICON_PX,
)

# skill-type -> short badge shown under grid/slot icons
_TYPE_BADGE = {"primary": "P", "spender": "S", "aura": "AU",
               "utility": "U", "ultimate": "ULT"}

GRID_QSS_LOCKED = (
    "QPushButton { background:#1a1512; border:1px solid #2a2218; color:#5a5040; }"
)
GRID_QSS_EQUIPPED = (
    "QPushButton { background:#2a2818; border:2px solid #6a8a3a; }"
    "QPushButton:hover { border:2px solid #8aac4a; }"
)
GRID_QSS_AVAIL = (
    "QPushButton { background:#221b15; border:1px solid #3a3226; }"
    "QPushButton:hover { border:1px solid #6a5a3a; background:#2a2218; }"
)
SLOT_OPEN_QSS = """
QPushButton { background:#221b15; border:1px dashed #4a4030; color:#8a7f5a;
              font-size:10px; font-family:Consolas, monospace; }
QPushButton:hover { border:1px solid #6a5a3a; }
"""
SLOT_FILLED_QSS = """
QPushButton { background:#2a2818; border:1px solid #6a8a3a; color:#d4e08a;
              font-size:10px; font-family:Consolas, monospace; }
QPushButton:hover { border:1px solid #8aac4a; }
"""
SLOT_CLOSED_QSS = """
QPushButton { background:#161210; border:1px solid #241e18; color:#4a4030;
              font-size:10px; font-family:Consolas, monospace; }
"""
TALENT_QSS = """
QPushButton { background:#221b15; color:#c8b898; border:1px solid #3a3226;
              padding:4px 8px; font-size:11px; text-align:left; }
QPushButton:hover { border:1px solid #6a5a3a; background:#2a2218; }
QPushButton:disabled { color:#5a5040; border-color:#2a2218; }
"""
TALENT_CHOSEN_QSS = """
QPushButton { background:#2a2818; color:#d4e08a; border:1px solid #6a8a3a;
              padding:4px 8px; font-size:11px; text-align:left; }
"""
MICRO_QSS = """
QPushButton { background:#221b15; color:#c8b898; border:1px solid #3a3226;
              font-size:11px; padding:0; }
QPushButton:hover { border:1px solid #6a5a3a; }
QPushButton:disabled { color:#4a4030; border-color:#241e18; }
"""


class SkillsPanel(PanelFrame):
    def __init__(self, hero: Hero, on_change=None):
        super().__init__("Skills")
        self.setFixedWidth(760)
        self.hero = hero
        self.on_change = on_change
        self._selected: str | None = None   # skill id shown in the right card
        self.root = QHBoxLayout(self.content)
        self.root.setSpacing(12)
        self._build_ui()

    # ------------------------------------------------------------- build
    def _build_ui(self):
        left = self._column(250)
        mid = self._column(210)
        right = self._column(268)
        self.root.addWidget(left[0])
        self.root.addWidget(mid[0])
        self.root.addWidget(right[0])
        lcol, mcol, rcol = left[1], mid[1], right[1]

        # LEFT — skill grid
        lcol.addWidget(self._hdr("Skills (click to equip)"))
        self._grid = QGridLayout()
        self._grid.setSpacing(4)
        lcol.addLayout(self._grid)
        lcol.addStretch()

        # CENTER — loadout
        mcol.addWidget(self._hdr("Loadout"))
        self._loadout_area = QVBoxLayout()
        self._loadout_area.setSpacing(4)
        mcol.addLayout(self._loadout_area)
        mcol.addStretch()

        # RIGHT — selected skill card
        rcol.addWidget(self._hdr("Skill Detail"))
        self._card_area = QVBoxLayout()
        self._card_area.setSpacing(6)
        rcol.addLayout(self._card_area)
        rcol.addStretch()

    def _column(self, width: int) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        w.setFixedWidth(width)
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        return w, col

    def _hdr(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("hdr")
        return lab

    @staticmethod
    def _sep() -> QFrame:
        s = QFrame()
        s.setFrameShape(QFrame.Shape.HLine)
        s.setStyleSheet("QFrame { color:#3a3226; }")
        return s

    def _hook_tip(self, w: QWidget, html: str):
        w._tip_html = html
        w.enterEvent = lambda e, x=w: _tip().show_for(x, x._tip_html)
        w.leaveEvent = lambda e, x=w: _tip().hide()

    # ------------------------------------------------------------- refresh
    def refresh(self):
        SV.ensure_skills_v2(self.hero)
        # default selection: the primary skill
        if self._selected is None:
            self._selected = self.hero.skills_v2["loadout"].get("primary")
        self._refresh_grid()
        self._refresh_loadout()
        self._refresh_card()

    def _changed(self):
        self._refresh_grid()
        self._refresh_loadout()
        self._refresh_card()
        if self.on_change:
            self.on_change()

    _DTYPE_NAME = {"phys": "Physical", "fire": "Fire", "cold": "Cold",
                   "lightning": "Lightning", "chaos": "Chaos"}

    def _skill_tip(self, sk: SV.SkillV2) -> str:
        rank, into, need = SV.rank_progress(self.hero, sk.id)
        badge = {"primary": "Primary (auto-attack)", "spender": "Spender",
                 "aura": "Aura", "utility": "Utility",
                 "ultimate": "Ultimate"}.get(sk.type, sk.type)
        lines = [f"<b>{sk.name}</b> — <span style='color:#8a9f5a'>{badge}</span>",
                 f"<span style='color:#7a6f5a'>Rank {rank}"
                 + ("" if need == 0 else f" ({into}/{need} sxp)") + "</span>"]

        if sk.base_damage_pct > 0:
            dt = sk.damage_type
            dcol = DTYPE_COLORS.get(dt, "#c8b898")
            dname = self._DTYPE_NAME.get(dt.value, dt.value.title())
            # per-hit estimate against a 0-resist target, using the live formula
            # from combat_math._deal: base = avg attack dmg (+ added element),
            # scaled by base% × rank-MORE × talent inc.
            s = self.hero.stats
            avg = (s.damage_min + s.damage_max) / 2
            added = getattr(s, f"added_{dt.value}", 0.0)
            pct = SV._effective_pct(self.hero, sk)
            per_hit = (avg + added) * pct
            hits_txt = f" ×{sk.hits} hits" if sk.hits > 1 else ""
            lines.append(
                f"<span style='color:#7a6f5a'>Damage type:</span> "
                f"<span style='color:{dcol}; font-weight:bold'>{dname}</span>")
            eff_pct = sk.base_damage_pct * (SV.skill_more_mult(self.hero, sk.id))
            lines.append(
                f"<span style='color:#7a6f5a'>Base:</span> {sk.base_damage_pct:g}%"
                + (f" → {eff_pct:g}% at rank {rank}" if abs(eff_pct - sk.base_damage_pct) > 0.1 else "")
                + hits_txt)
            lines.append(
                f"<span style='color:#7a6f5a'>Est. hit:</span> "
                f"<span style='color:{dcol}'>~{per_hit:,.0f}</span>"
                + (f" <span style='color:#7a6f5a'>×{sk.hits} = {per_hit * sk.hits:,.0f}</span>"
                   if sk.hits > 1 else "")
                + " <span style='color:#5a5040'>(vs 0 res)</span>")
            scale = "Attack Damage" if dt == DamageType.PHYS \
                else f"Attack Damage + Added {dname}"
            lines.append(f"<span style='color:#7a6f5a'>Scales with:</span> {scale}")
            if sk.per_rank_more_pct > 0:
                lines.append(
                    f"<span style='color:#7a6f5a'>Per rank:</span> "
                    f"+{sk.per_rank_more_pct:g}% more damage")

        # ailment this skill can inflict, derived the same way combat does it
        ail = SV._ailment_from(self.hero, sk)
        if ail is not None:
            kind, chance = ail
            lines.append(f"<span style='color:#8a6f9a'>{kind.title()}</span> "
                         f"<span style='color:#7a6f5a'>on hit ({chance:g}%)</span>")

        if sk.cooldown_s > 0:
            lines.append(f"<span style='color:#7a6f5a'>Cooldown: {sk.cooldown_s:g}s</span>")
        elif sk.type == "primary":
            lines.append("<span style='color:#7a6f5a'>Fires at your attack rate</span>")
        if sk.range_px > 0:
            reach = "melee" if sk.range_px <= 90 else "ranged"
            lines.append(f"<span style='color:#7a6f5a'>Range: {sk.range_px:g}px ({reach})</span>")
        if "aoe" in sk.tags or sk.params.get("aoe"):
            cap = sk.params.get("max_targets")
            lines.append("<span style='color:#6a8a9a'>Area of Effect</span>"
                         + (f" <span style='color:#7a6f5a'>(up to {cap} targets)</span>" if cap else ""))
        if sk.tags:
            lines.append("<span style='color:#5a6f8a'>[" + ", ".join(sk.tags) + "]</span>")
        return "<br>".join(lines)

    def _refresh_grid(self):
        while self._grid.count():
            it = self._grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        sv = self.hero.skills_v2
        unlocked = set(sv.get("unlocked", []))
        equipped = set(SV._equipped_ids(sv))
        skills = SV.load_skills_v2()
        cls_skills = SV._class_skills(self.hero.class_id)  # unlock order
        for i, sk in enumerate(cls_skills):
            btn = QPushButton()
            btn.setFixedSize(SKILL_ICON_PX + 14, SKILL_ICON_PX + 14)
            pm = skill_pixmap(sk.id)
            if pm:
                btn.setIcon(QIcon(pm))
                btn.setIconSize(pm.size())
            else:
                btn.setText(_TYPE_BADGE.get(sk.type, "?"))
            if sk.id not in unlocked:
                btn.setStyleSheet(GRID_QSS_LOCKED)
                btn.setEnabled(False)
                self._hook_tip(btn, f"<b>{sk.name}</b><br>"
                               f"<span style='color:#7a6f5a'>Unlocks at level "
                               f"{sk.unlock_level}</span>")
            else:
                btn.setStyleSheet(GRID_QSS_EQUIPPED if sk.id in equipped
                                  else GRID_QSS_AVAIL)
                self._hook_tip(btn, self._skill_tip(sk))
                btn.clicked.connect(lambda _c, s=sk.id: self._equip(s))
            self._grid.addWidget(btn, i // 4, i % 4)

    def _equip(self, sid: str):
        ok = SV.equip_skill(self.hero, sid)
        if ok:
            self._selected = sid
            self.set_status(f"Equipped {SV.load_skills_v2()[sid].name}")
            self._changed()
        else:
            _, why = SV.can_equip(self.hero, sid)
            self.set_status(why or "can't equip that")

    # ------------------------------------------------------------- loadout
    def _refresh_loadout(self):
        while self._loadout_area.count():
            it = self._loadout_area.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())
        lo = self.hero.skills_v2["loadout"]
        n_open = SV.slots_open(self.hero.level)

        # primary (auto-attack) — always present, separate from the pool
        self._loadout_area.addWidget(self._slot_button("primary", lo.get("primary"), True))

        # common skill pool: any type (spender/aura/utility/ultimate) shares it.
        # Rows read top→bottom as cast priority; ▲/▼ reorder within the pool.
        self._loadout_area.addWidget(self._sep())
        self._loadout_area.addWidget(self._mini_hdr("Skill slots (any type · cast priority)"))
        slots = [s for s in lo.get("slots", []) if s]
        for i, sid in enumerate(slots):
            self._loadout_area.addLayout(self._active_row(sid, i, len(slots)))
        for _ in range(len(slots), n_open):       # open empty pool slots
            self._loadout_area.addWidget(self._slot_button("slots", None, True,
                                                           label="+ skill"))
        for idx in range(n_open, SV.MAX_SKILL_SLOTS):  # not-yet-unlocked slots
            lvl = SV.SKILL_SLOT_LEVELS[idx]
            self._loadout_area.addWidget(self._slot_button("slots", None, False,
                                                           label=f"slot @ Lvl {lvl}"))

    def _mini_hdr(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet("QLabel { color:#7a6f5a; font-size:10px; }")
        return lab

    def _slot_button(self, fam: str, sid: str | None, is_open: bool,
                     label: str | None = None) -> QPushButton:
        btn = QPushButton()
        btn.setMinimumHeight(30)
        if not is_open:
            btn.setStyleSheet(SLOT_CLOSED_QSS)
            btn.setEnabled(False)
            btn.setText(label or f"{fam} (locked)")
            return btn
        if sid:
            sk = SV.load_skills_v2()[sid]
            btn.setStyleSheet(SLOT_FILLED_QSS)
            btn.setText(f"[{_TYPE_BADGE.get(sk.type, '?')}] {sk.name}")
            self._hook_tip(btn, self._skill_tip(sk))
            btn.clicked.connect(lambda _c, s=sid: self._select(s))
        else:
            btn.setStyleSheet(SLOT_OPEN_QSS)
            btn.setText(label or f"empty {fam}")
            self._hook_tip(btn, f"<span style='color:#7a6f5a'>Open {fam} slot — "
                                f"click a matching skill on the left to equip.</span>")
        return btn

    def _active_row(self, sid: str, idx: int, total: int) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(3)
        row.addWidget(self._slot_button("slots", sid, True), 1)
        up = QPushButton("▲")
        up.setFixedSize(22, 30)
        up.setStyleSheet(MICRO_QSS)
        up.setEnabled(idx > 0)
        up.clicked.connect(lambda _c, s=sid: self._move(s, -1))
        self._hook_tip(up, "Higher cast priority")
        dn = QPushButton("▼")
        dn.setFixedSize(22, 30)
        dn.setStyleSheet(MICRO_QSS)
        dn.setEnabled(idx < total - 1)
        dn.clicked.connect(lambda _c, s=sid: self._move(s, +1))
        self._hook_tip(dn, "Lower cast priority")
        x = QPushButton("✕")
        x.setFixedSize(22, 30)
        x.setStyleSheet(MICRO_QSS)
        x.clicked.connect(lambda _c, s=sid: self._unequip(s))
        self._hook_tip(x, "Unequip")
        row.addWidget(up)
        row.addWidget(dn)
        row.addWidget(x)
        return row

    def _move(self, sid: str, delta: int):
        if SV.move_priority(self.hero, sid, delta):
            self._changed()

    def _unequip(self, sid: str):
        if SV.unequip_skill(self.hero, sid):
            self.set_status("Unequipped")
            self._changed()

    def _select(self, sid: str):
        self._selected = sid
        self._refresh_card()

    # ------------------------------------------------------------- card
    def _refresh_card(self):
        self._clear_layout(self._card_area)
        sid = self._selected
        skills = SV.load_skills_v2()
        if not sid or sid not in skills:
            hint = QLabel("Select a loadout slot to see its ranks & talents.")
            hint.setWordWrap(True)
            hint.setStyleSheet("QLabel { color:#5a5040; font-size:11px; }")
            self._card_area.addWidget(hint)
            return
        sk = skills[sid]
        rank, into, need = SV.rank_progress(self.hero, sid)

        name = QLabel(f"{sk.name}")
        name.setStyleSheet("QLabel { color:#d4e08a; font-size:13px; font-weight:bold; }")
        self._card_area.addWidget(name)

        maxed = (need == 0)
        rank_lab = QLabel(f"Rank {rank}" + (" — MAX" if maxed else ""))
        rank_lab.setStyleSheet("QLabel { color:#7a6f5a; font-size:10px; }")
        self._card_area.addWidget(rank_lab)

        bar = QProgressBar()
        bar.setFixedHeight(10)
        bar.setTextVisible(False)
        if maxed:
            bar.setRange(0, 1)
            bar.setValue(1)
        else:
            bar.setRange(0, max(1, need))
            bar.setValue(max(0, into))
        bar.setStyleSheet(
            "QProgressBar { background:#1a1512; border:1px solid #3a3226; }"
            "QProgressBar::chunk { background:#6a8a3a; }")
        self._card_area.addWidget(bar)

        self._card_area.addWidget(self._sep())

        tiers = SV.talent_tiers_for(self.hero, sid)
        for tier in tiers:
            r = tier["rank"]
            state = "✓" if tier["unlocked"] else f"rank {r}"
            hdr = QLabel(f"Talent @ rank {r}  ({state})")
            hdr.setStyleSheet(
                f"QLabel {{ color:{'#8a9f5a' if tier['unlocked'] else '#5a5040'};"
                " font-size:10px; }")
            self._card_area.addWidget(hdr)
            for i, opt in enumerate(tier["options"]):
                btn = QPushButton(opt["name"])
                btn.setMinimumHeight(26)
                chosen = tier["chosen_idx"] == i
                if chosen:
                    btn.setStyleSheet(TALENT_CHOSEN_QSS)
                    btn.setEnabled(False)
                else:
                    btn.setStyleSheet(TALENT_QSS)
                    btn.setEnabled(tier["unlocked"])
                    if tier["unlocked"]:
                        btn.clicked.connect(
                            lambda _c, rr=r, ii=i: self._pick(rr, ii))
                self._hook_tip(btn, f"<b>{opt['name']}</b><br>{opt['desc']}")
                self._card_area.addWidget(btn)

        self._card_area.addWidget(self._sep())
        cost = SV.RESPEC_GOLD_PER_LEVEL * max(1, self.hero.level)
        respec = QPushButton(f"Respec talents ({cost} gold)")
        respec.setStyleSheet(BTN_QSS)
        has_picks = bool(self.hero.skills_v2.get("talents", {}).get(sid))
        respec.setEnabled(has_picks and self.hero.gold >= cost)
        respec.clicked.connect(lambda _c, s=sid: self._respec(s))
        self._card_area.addWidget(respec)

    def _pick(self, tier_rank: int, idx: int):
        if SV.pick_talent(self.hero, self._selected, tier_rank, idx):
            self.set_status("Talent chosen!")
            self._changed()
        else:
            self.set_status("Talent locked — rank too low")

    def _respec(self, sid: str):
        ok, msg = SV.respec_talents(self.hero, sid)
        self.set_status(msg)
        if ok:
            self._changed()

    # ------------------------------------------------------------- util
    def _clear_layout(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())


# --------------------------------------------------------------------------- #
# smoke: python -m ui.skills_panel
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    from game import classes

    app = QApplication(sys.argv)
    for cid in ("warrior", "barbarian", "archer", "mage", "cleric"):
        hero = classes.make_hero(cid)
        hero.level = 30
        classes.apply_level_growth(hero)
        SV.ensure_skills_v2(hero)
        for s in SV._equipped_ids(hero.skills_v2):
            hero.skills_v2["sxp"][s] = 4000  # give ranks so talents unlock
        p = SkillsPanel(hero, on_change=lambda: None)
        p.refresh()
        # exercise a couple of interactions headlessly
        eq = SV._equipped_ids(hero.skills_v2)
        p._select(eq[0])
        p._refresh_card()
        print(f"{cid:9}: loadout={eq} selected={p._selected} — panel OK")
    print("skills_panel smoke OK")
