"""Bar of Exile — vendor popup panel: hourly stock of 8 items bought for gold."""
from __future__ import annotations

import random
import time

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from game.core import Hero, Item, Rarity
from game.economy import bulk_sell_threshold, item_value
from game.vendor import Vendor, price
from game import idle_upgrades
from ui.panels import BTN_QSS, CELL, INV_COLS, INV_ROWS, Cell, ItemTooltip, PanelFrame

COLS, ROWS = 4, 2  # 8 stock cells
BUYBACK_CELLS = 5  # spec 6.4: session-only buyback, newest first
GOLD_COLOR = "#d4c08a"
POOR_COLOR = "#c05050"


class VendorPanel(PanelFrame):
    """Hourly shop: hover a cell for the tooltip, click to buy into the inventory."""

    def __init__(self, hero: Hero, vendor: Vendor, rng: random.Random, on_change=None):
        super().__init__("Vendor")
        self.hero, self.vendor, self.rng, self.on_change = hero, vendor, rng, on_change
        self.tooltip = ItemTooltip()
        self.cells: list[Cell] = []
        self.price_labs: list[QLabel] = []

        # Add gold and restock labels to title bar
        self.gold_lab = QLabel("")
        self.gold_lab.setStyleSheet(f"color:{GOLD_COLOR}; font-weight:bold;")
        self.add_header_widget(self.gold_lab)
        self.restock_lab = QLabel("")
        self.restock_lab.setObjectName("dim")
        self.add_header_widget(self.restock_lab)

        root = QVBoxLayout(self.content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        grid = QGridLayout()
        grid.setSpacing(4)
        for i in range(COLS * ROWS):
            cell = Cell("vendor", i)
            cell.clicked.connect(self._on_click)
            cell.hovered.connect(self._on_hover)
            cell.unhovered.connect(lambda _c: self.tooltip.hide())
            self.cells.append(cell)
            lab = QLabel("", alignment=Qt.AlignmentFlag.AlignCenter)
            lab.setFixedWidth(CELL)
            self.price_labs.append(lab)
            r, c = divmod(i, COLS)
            grid.addWidget(cell, r * 2, c)
            grid.addWidget(lab, r * 2 + 1, c)
        root.addLayout(grid)

        self.bulk_btn = QPushButton("")
        self.bulk_btn.clicked.connect(self._on_bulk_sell)
        root.addWidget(self.bulk_btn)

        # E.1 idle-upgrades: permanent gold-sink. One buy row per upgrade line.
        train_head = QLabel("Training — permanent upgrades")
        train_head.setObjectName("dim")
        root.addWidget(train_head)
        self.train_btns: dict[str, QPushButton] = {}
        for uid in idle_upgrades.UPGRADE_ORDER:
            btn = QPushButton("")
            btn.setStyleSheet(BTN_QSS)
            btn.clicked.connect(lambda _=False, u=uid: self._buy_upgrade(u))
            self.train_btns[uid] = btn
            root.addWidget(btn)

        bb_head = QLabel("Buyback")
        bb_head.setObjectName("dim")
        root.addWidget(bb_head)
        bb_row = QHBoxLayout()
        bb_row.setSpacing(4)
        self.buyback_cells: list[Cell] = []
        for i in range(BUYBACK_CELLS):
            cell = Cell("buyback", i)
            cell.clicked.connect(self._on_buyback_click)
            cell.hovered.connect(self._on_hover)
            cell.unhovered.connect(lambda _c: self.tooltip.hide())
            self.buyback_cells.append(cell)
            bb_row.addWidget(cell)
        bb_row.addStretch(1)
        root.addLayout(bb_row)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        root.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    # ------------------------------------------------------------- actions
    def _on_click(self, cell: Cell) -> None:
        idx = cell.key
        if idx >= len(self.vendor.stock):
            return
        cost = price(self.vendor.stock[idx])
        if self.hero.gold < cost:
            self.status.setText("Not enough gold")
            return
        if len(self.hero.inventory) >= INV_COLS * INV_ROWS:
            self.status.setText("Inventory full")
            return
        item = self.vendor.buy(self.hero, idx)
        if item is None:
            return
        self.hero.inventory.append(item)
        self.tooltip.hide()
        self.refresh()
        if self.on_change:
            self.on_change()

    def _on_buyback_click(self, cell: Cell) -> None:
        idx = cell.key
        if idx >= len(self.vendor.buyback):
            return
        item = self.vendor.buyback[idx]
        if self.hero.gold < item_value(item):
            self.status.setText("Not enough gold")
            return
        if len(self.hero.inventory) >= INV_COLS * INV_ROWS:
            self.status.setText("Inventory full")
            return
        item = self.vendor.buy_back(self.hero, idx)
        if item is None:
            return
        self.hero.inventory.append(item)
        self.tooltip.hide()
        self.refresh()
        if self.on_change:
            self.on_change()

    def sell_item(self, item: Item) -> bool:
        gold = self.vendor.sell(self.hero, item)
        self.refresh()
        self.status.setText(f"Sold {item.display_name()} for {gold} gold")
        if self.on_change:
            self.on_change()
        return True

    def _on_bulk_sell(self) -> None:
        cap = bulk_sell_threshold(self.hero.level)
        sold, gold = 0, 0
        for item in list(self.hero.inventory):
            # junk = anything under the ilvl threshold, plus normals at any ilvl
            if item.ilvl < cap or item.rarity is Rarity.NORMAL:
                self.hero.inventory.remove(item)
                gold += self.vendor.sell(self.hero, item)
                sold += 1
        self.refresh()
        self.status.setText(f"Sold {sold} items for {gold} gold" if sold else "Nothing to sell")
        if self.on_change:
            self.on_change()

    def _buy_upgrade(self, uid: str) -> None:
        h = self.hero
        ups = getattr(h, "idle_upgrades", None) or {}
        if idle_upgrades.is_maxed(ups, uid):
            self.status.setText(f"{idle_upgrades.UPGRADES[uid].name} maxed")
            return
        new_ups, new_gold, ok = idle_upgrades.buy(ups, uid, h.gold)
        if not ok:
            lvl = new_ups.get(uid, 0)
            self.status.setText(
                f"{idle_upgrades.UPGRADES[uid].name} costs "
                f"{idle_upgrades.cost(uid, lvl):,}g — not enough gold")
            return
        h.idle_upgrades, h.gold = new_ups, new_gold
        h.recalc()  # fold the new bonus into gold_find / xp_gain_inc aggregates
        self.refresh()
        self.status.setText(f"{idle_upgrades.UPGRADES[uid].name} → lvl {new_ups[uid]}")
        if self.on_change:
            self.on_change()

    def _refresh_training(self) -> None:
        ups = getattr(self.hero, "idle_upgrades", None) or {}
        for uid, btn in self.train_btns.items():
            up = idle_upgrades.UPGRADES[uid]
            lvl = ups.get(uid, 0)
            if idle_upgrades.is_maxed(ups, uid):
                btn.setText(f"{up.name}  lvl {lvl}/{up.max_lvl}  (MAX)")
                btn.setEnabled(False)
            else:
                c = idle_upgrades.cost(uid, lvl)
                btn.setText(f"{up.name}  lvl {lvl}/{up.max_lvl}  —  {c:,}g")
                btn.setEnabled(self.hero.gold >= c)

    def _on_hover(self, cell: Cell) -> None:
        if not cell.item:
            return
        pos = cell.mapToGlobal(QPoint(0, -6))
        self.tooltip.show_item(cell.item, pos, hero_class=self.hero.class_id)

    def _tick(self) -> None:
        if self.vendor.maybe_refresh(max(1, self.hero.level), self.rng,
                                     time.time(), class_id=self.hero.class_id):
            self.refresh()
        else:
            self._update_labels()

    def _update_labels(self) -> None:
        self.gold_lab.setText(f"Gold: {self.hero.gold}")
        secs = self.vendor.seconds_to_refresh(time.time())
        self.restock_lab.setText(f"Restock in {secs // 60:02d}:{secs % 60:02d}")

    # ------------------------------------------------------------- refresh
    def refresh(self) -> None:
        self.vendor.maybe_refresh(max(1, self.hero.level), self.rng,
                                  time.time(), class_id=self.hero.class_id)
        stock = self.vendor.stock
        for i, (cell, lab) in enumerate(zip(self.cells, self.price_labs)):
            item = stock[i] if i < len(stock) else None
            cell.set_item(item)
            if item:
                cost = price(item)
                color = GOLD_COLOR if self.hero.gold >= cost else POOR_COLOR
                lab.setText(str(cost))
                lab.setStyleSheet(f"color:{color}; font-size:10px; font-weight:bold;")
            else:
                lab.setText("")
        buyback = self.vendor.buyback
        for i, cell in enumerate(self.buyback_cells):
            cell.set_item(buyback[i] if i < len(buyback) else None)
        cap = bulk_sell_threshold(self.hero.level)
        self.bulk_btn.setText(f"Sell junk (ilvl < {cap})")
        self._refresh_training()
        self.status.setText("")
        self._update_labels()
        self.adjustSize()

    def showEvent(self, e):
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        self.tooltip.hide()
        self.vendor.clear_buyback()  # spec 6.4: buyback is session-only
        super().hideEvent(e)


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    from game.core import Slot, Stats

    hero = Hero(name="Test", stats=Stats(), base_stats=Stats(), gold=10, class_id="warrior")
    hero.equipment = {s.value: None for s in Slot}
    hero.inventory = []
    hero.init_hp()
    hero.recalc()

    vendor = Vendor()
    panel = VendorPanel(hero, vendor, random.Random(7), on_change=lambda: None)
    panel.refresh()
    panel.show()
    assert len(vendor.stock) == 8

    # buy with enough gold: exact deduction, item lands in the inventory
    cost = price(vendor.stock[0])
    hero.gold = cost + 5
    panel._on_click(panel.cells[0])
    assert hero.gold == 5 and len(hero.inventory) == 1
    assert len(vendor.stock) == 7

    # broke: refused, nothing changes, status explains why
    hero.gold = 0
    panel._on_click(panel.cells[0])
    assert len(hero.inventory) == 1 and len(vendor.stock) == 7
    assert panel.status.text() == "Not enough gold"

    # sell_item: exactly item_value gold, item lands in buyback cell 0
    sold = hero.inventory.pop(0)
    val = item_value(sold)
    gold_before_sale = hero.gold
    assert panel.sell_item(sold) is True
    assert hero.gold == gold_before_sale + val
    assert vendor.buyback[0] is sold
    assert panel.buyback_cells[0].item is sold
    assert f"for {val} gold" in panel.status.text()

    # buyback click: item returns to the inventory, gold net-zero vs before the sale
    panel._on_buyback_click(panel.buyback_cells[0])
    assert hero.gold == gold_before_sale
    assert sold in hero.inventory and len(vendor.buyback) == 0
    assert panel.buyback_cells[0].item is None

    # bulk sell: below-threshold items and ALL normals go; rare/magic >= cap stay
    hero.level = 20
    cap = bulk_sell_threshold(hero.level)
    assert cap == 15
    junk_n = Item("coral_ring", "Coral Ring", Slot.RING, Rarity.NORMAL, 5, req_level=1)
    junk_m = Item("jade_amulet", "Jade Amulet", Slot.AMULET, Rarity.MAGIC, 9, req_level=1)
    junk_hi_n = Item("chain_coif", "Chain Coif", Slot.HELMET, Rarity.NORMAL, 18, req_level=1)
    keep_rare = Item("long_sword", "Long Sword", Slot.WEAPON, Rarity.RARE, 18, req_level=1)
    keep_magic = Item("iron_ring", "Iron Ring", Slot.RING, Rarity.MAGIC, 18, req_level=1)
    hero.inventory[:] = [junk_n, junk_m, junk_hi_n, keep_rare, keep_magic]
    panel.refresh()
    assert f"ilvl < {cap}" in panel.bulk_btn.text()
    gold_before_bulk = hero.gold
    panel._on_bulk_sell()
    assert hero.inventory == [keep_rare, keep_magic]
    assert hero.gold == gold_before_bulk + item_value(junk_n) + item_value(junk_m) \
        + item_value(junk_hi_n)
    assert "Sold 3 items" in panel.status.text()
    # newest first in buyback
    assert vendor.buyback[0] is junk_hi_n and vendor.buyback[1] is junk_m \
        and vendor.buyback[2] is junk_n

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor_test.png")
    panel.grab().save(path)

    # E.1 Training: buy up_gold, gold drops by exact cost, level ticks, recalc folds it
    from game import idle_upgrades as _iu
    hero.idle_upgrades = {}
    hero.gold = _iu.cost("up_gold", 0) + 3
    before = hero.gold
    panel._buy_upgrade("up_gold")
    assert hero.idle_upgrades.get("up_gold") == 1, hero.idle_upgrades
    assert hero.gold == before - _iu.cost("up_gold", 0)
    assert hero.stats.gold_find >= 0.4  # recalc folded the +0.4% into the aggregate
    hero.gold = 0
    panel._buy_upgrade("up_gold")  # broke: refused, level unchanged
    assert hero.idle_upgrades.get("up_gold") == 1
    assert "not enough gold" in panel.status.text()

    # closing the panel drops the buyback — it is session-only
    panel.hide()
    assert vendor.buyback == []
    assert panel.buyback_cells[0].item is junk_hi_n  # cells repopulate on next refresh
    panel.refresh()
    assert all(c.item is None for c in panel.buyback_cells)

    print("OK:", path)
