"""Bar of Exile — Ferek's Game of Certainties: gamble popup panel.

One button per equipment slot; a click pays gamble_cost(hero.level, slot) and
rolls an unidentified prize through game.gamble (pity math lives there and is
deliberately NOT shown — Ferek keeps his books closed).
"""
from __future__ import annotations

import random

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from game.core import Hero, Slot
from game.gamble import GambleVendor, gamble_cost
from ui.panels import CELL, INV_COLS, INV_ROWS, SLOT_EN, Cell, ItemTooltip, PanelFrame

COLS = 4  # 8 slot buttons in a 4x2 grid
GOLD_COLOR = "#d4c08a"
POOR_COLOR = "#c05050"
FEREK_LINE = "“Certainty costs extra, friend. Luck is for the poor.” — Ferek"

BTN_STYLE = """
QPushButton { background: #221b15; border: 1px solid #3a3226; color: #c8b898;
              padding: 4px 2px; }
QPushButton:hover { border: 1px solid #8a7a4a; }
QPushButton:pressed { background: #2a2318; }
"""


class GamblePanel(PanelFrame):
    """Gamble vendor: click a slot to buy a random item of that slot at hero level."""

    def __init__(self, hero: Hero, vendor: GambleVendor | None, rng: random.Random,
                 on_change=None):
        super().__init__("Ferek's Game of Certainties")
        self.hero, self.rng, self.on_change = hero, rng, on_change
        self.vendor = vendor if vendor is not None else GambleVendor(rng)
        self.tooltip = ItemTooltip()

        # Add gold label to title bar
        self.gold_lab = QLabel("")
        self.gold_lab.setStyleSheet(f"color:{GOLD_COLOR}; font-weight:bold;")
        self.add_header_widget(self.gold_lab)

        root = QVBoxLayout(self.content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        flavor = QLabel(FEREK_LINE)
        flavor.setObjectName("dim")
        root.addWidget(flavor)

        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        self.slot_btns: dict[str, QPushButton] = {}
        self.cost_labs: dict[str, QLabel] = {}
        for i, slot in enumerate(Slot):
            btn = QPushButton(SLOT_EN[slot])
            btn.setStyleSheet(BTN_STYLE)
            btn.setFixedWidth(max(CELL * 2, 92))
            btn.clicked.connect(lambda _=False, s=slot: self._on_gamble(s))
            lab = QLabel("", alignment=Qt.AlignmentFlag.AlignCenter)
            self.slot_btns[slot.value] = btn
            self.cost_labs[slot.value] = lab
            r, c = divmod(i, COLS)
            grid.addWidget(btn, r * 3, c)
            grid.addWidget(lab, r * 3 + 1, c)
        grid.setRowMinimumHeight(2, 6)
        root.addLayout(grid)

        res_row = QHBoxLayout()
        res_row.setSpacing(8)
        res_head = QLabel("Last prize")
        res_head.setObjectName("dim")
        res_row.addWidget(res_head)
        self.result_cell = Cell("gamble", 0)
        self.result_cell.hovered.connect(self._on_hover)
        self.result_cell.unhovered.connect(lambda _c: self.tooltip.hide())
        res_row.addWidget(self.result_cell)
        self.result_lab = QLabel("")
        self.result_lab.setObjectName("dim")
        res_row.addWidget(self.result_lab)
        res_row.addStretch(1)
        root.addLayout(res_row)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        root.addWidget(self.status)

        self.refresh()

    # ------------------------------------------------------------- actions
    def _keystones(self) -> frozenset:
        return frozenset(getattr(self.hero, "flags", ()) or ())

    def _on_gamble(self, slot: Slot) -> None:
        if len(self.hero.inventory) >= INV_COLS * INV_ROWS:
            self.status.setText("Inventory full")
            return
        res = self.vendor.roll_item(
            max(1, self.hero.level), slot=slot.value, gold=self.hero.gold,
            keystones=self._keystones(), class_id=self.hero.class_id)
        if not res["ok"]:
            self.status.setText("Not enough gold")
            return
        self.hero.gold -= res["cost"]
        item = res["item"]
        self.hero.inventory.append(item)
        self.result_cell.set_item(item)
        self.result_lab.setText(item.display_name())
        self.tooltip.hide()
        self.refresh()
        self.status.setText(f"Ferek hands over {item.display_name()}")
        if self.on_change:
            self.on_change()

    def _on_hover(self, cell: Cell) -> None:
        if not cell.item:
            return
        pos = cell.mapToGlobal(QPoint(0, -6))
        self.tooltip.show_item(cell.item, pos, hero_class=self.hero.class_id)

    # ------------------------------------------------------------- refresh
    def refresh(self) -> None:
        self.gold_lab.setText(f"Gold: {self.hero.gold}")
        ks = self._keystones()
        level = max(1, self.hero.level)
        for slot in Slot:
            cost = gamble_cost(level, slot.value, ks)
            color = GOLD_COLOR if self.hero.gold >= cost else POOR_COLOR
            lab = self.cost_labs[slot.value]
            lab.setText(f"{cost}g")
            lab.setStyleSheet(f"color:{color}; font-size:10px; font-weight:bold;")
        self.status.setText("")
        self.adjustSize()

    def hideEvent(self, e):
        self.tooltip.hide()
        super().hideEvent(e)


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    from game.core import Stats

    hero = Hero(name="Test", stats=Stats(), base_stats=Stats(), gold=0, class_id="warrior")
    hero.level = 30
    hero.equipment = {s.value: None for s in Slot}
    hero.inventory = []
    hero.init_hp()
    hero.recalc()

    rng = random.Random(20260716)
    vendor = GambleVendor(rng)
    panel = GamblePanel(hero, vendor, rng, on_change=lambda: None)
    panel.show()

    # costs match the binding formula (weapon base, jewelry x1.5)
    assert panel.cost_labs[Slot.WEAPON.value].text() == f"{gamble_cost(30, 'weapon')}g"
    assert panel.cost_labs[Slot.RING.value].text() == f"{gamble_cost(30, 'ring')}g"
    assert gamble_cost(30, "ring") == max(1, int(round(gamble_cost(30) * 1.5)))
    assert POOR_COLOR in panel.cost_labs[Slot.WEAPON.value].styleSheet()  # broke -> red

    # rich: exact deduction, item lands in the inventory, pity state advanced
    cost = gamble_cost(30, "weapon")
    hero.gold = cost + 5
    panel.refresh()
    assert GOLD_COLOR in panel.cost_labs[Slot.WEAPON.value].styleSheet()
    panel._on_gamble(Slot.WEAPON)
    assert hero.gold == 5, hero.gold
    assert len(hero.inventory) == 1
    assert vendor.lifetime_rolls == 1 and vendor.stats["gold_spent"] == cost
    assert panel.result_cell.item is hero.inventory[0]
    assert "Ferek hands over" in panel.status.text()

    # last-prize tooltip on hover
    panel._on_hover(panel.result_cell)
    assert panel.tooltip.isVisible()
    panel.tooltip.hide()

    # broke: refused, nothing rolls, status explains why
    hero.gold = 0
    panel.refresh()
    panel._on_gamble(Slot.WEAPON)
    assert len(hero.inventory) == 1 and vendor.lifetime_rolls == 1
    assert panel.status.text() == "Not enough gold"

    # inventory full: refused even with gold, no gold spent, no roll consumed
    hero.gold = 10 ** 9
    hero.inventory = [hero.inventory[0]] * (INV_COLS * INV_ROWS)
    panel.refresh()
    panel._on_gamble(Slot.RING)
    assert hero.gold == 10 ** 9 and vendor.lifetime_rolls == 1
    assert panel.status.text() == "Inventory full"

    # jewelry roll actually charges the x1.5 price
    hero.inventory = []
    ring_cost = gamble_cost(30, "ring")
    hero.gold = ring_cost
    panel.refresh()
    panel._on_gamble(Slot.RING)
    assert hero.gold == 0 and len(hero.inventory) == 1

    # pity state round-trips through save meta
    v2 = GambleVendor.from_dict(vendor.to_dict(), rng)
    assert v2.pity == vendor.pity and v2.stats == vendor.stats

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_gamble_test.png")
    panel.grab().save(path)
    print("OK:", path)
