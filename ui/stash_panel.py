"""Bar of Exile — unlimited stash popup panel. Storage lives in Hero.stash.

UX wave (spec §6): sits on PanelFrame — title bar with X, Esc closes, and the
frame's height clamp + internal scroll keep the panel above the game strip
(it grows upward, never down onto the strip). Buttons: Stash all, Take All
(§6.6, keeps the remainder when the inventory fills up) and Sort (§6.6,
slot -> rarity -> ilvl desc, shared sort_items with the inventory).
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout

from game.core import Hero
from game import stash_tabs
from ui.panels import (
    BTN_QSS, INV_COLS, INV_ROWS, Cell, ItemTooltip, PanelFrame, sort_items,
)

STASH_COLS = INV_COLS
MIN_ROWS = 4       # empty stash still shows a grid


class StashPanel(PanelFrame):
    """Unlimited storage: click a stash item -> back to inventory (if it fits),
    'Stash all' -> whole inventory into the stash, 'Take All' -> stash into
    the inventory while there is room, 'Sort' -> slot/rarity/ilvl order."""

    def __init__(self, hero: Hero, on_change=None):
        super().__init__("Stash")
        self.hero, self.on_change = hero, on_change
        self.tooltip = ItemTooltip()
        self.cells: list[Cell] = []

        self.sort_btn = QPushButton("Sort")
        self.take_all_btn = QPushButton("Take All")
        self.stash_all_btn = QPushButton("Stash all")
        self.buy_tab_btn = QPushButton("Buy Slots")
        for btn, fn in ((self.sort_btn, self._on_sort),
                        (self.take_all_btn, self._take_all),
                        (self.stash_all_btn, self._stash_all),
                        (self.buy_tab_btn, self._buy_tab)):
            btn.setStyleSheet(BTN_QSS)
            btn.clicked.connect(fn)
            self.add_header_widget(btn)

        root = QVBoxLayout(self.content)
        root.setContentsMargins(0, 0, 0, 0)
        self.grid = QGridLayout()
        self.grid.setSpacing(4)
        self.grid.setContentsMargins(0, 0, 0, 0)
        # Pin the grid left: when the header (4 buttons) makes the panel wider
        # than 8 cells, leftover width goes to the trailing stretch — NOT
        # distributed between the fixed-size cells (which would open gaps).
        grid_row = QHBoxLayout()
        grid_row.setContentsMargins(0, 0, 0, 0)
        grid_row.addLayout(self.grid)
        grid_row.addStretch(1)
        root.addLayout(grid_row)
        root.addStretch(1)

        self.refresh()

    # ------------------------------------------------------------- actions
    def _inv_cap(self) -> int:
        return INV_COLS * INV_ROWS

    def _stash_all(self) -> None:
        h = self.hero
        if not h.inventory:
            self.set_status("Inventory is empty")
            return
        cap = stash_tabs.capacity(h.stash_tabs_owned)
        moved = 0
        while h.inventory and len(h.stash) < cap:
            h.stash.append(h.inventory.pop(0))
            moved += 1
        self._changed()
        if moved == 0:
            self.set_status("Stash full — buy slots")
        elif h.inventory:
            self.set_status(f"Stashed {moved} — stash full, {len(h.inventory)} left")
        else:
            self.set_status(f"Stashed {moved} item{'s' if moved != 1 else ''}")

    def _buy_tab(self) -> None:
        h = self.hero
        if h.stash_tabs_owned >= stash_tabs.MAX_TABS:
            self.set_status("Max stash slots owned")
            return
        new_owned, new_gold, ok = stash_tabs.buy_tab(h.stash_tabs_owned, h.gold)
        if not ok:
            price = stash_tabs.tab_price(h.stash_tabs_owned + 1)
            gained = stash_tabs.capacity(h.stash_tabs_owned + 1) - stash_tabs.capacity(h.stash_tabs_owned)
            self.set_status(f"+{gained} slots costs {price:,}g — not enough gold")
            return
        h.stash_tabs_owned, h.gold = new_owned, new_gold
        self._changed()
        self.set_status(f"Bought slots — {stash_tabs.capacity(new_owned)} total")

    def _take_all(self) -> None:
        """Spec §6.6: fill the inventory from the stash; whatever does not fit
        stays in the stash — nothing is ever lost."""
        h = self.hero
        if not h.stash:
            self.set_status("Stash is empty")
            return
        moved = 0
        while h.stash and len(h.inventory) < self._inv_cap():
            h.inventory.append(h.stash.pop(0))
            moved += 1
        self._changed()
        if moved == 0:
            self.set_status("Inventory full")  # W3.4: no silent refusal
        elif h.stash:
            self.set_status(f"Took {moved} — inventory full, {len(h.stash)} left")
        else:
            self.set_status(f"Took {moved} item{'s' if moved != 1 else ''}")

    def _on_sort(self) -> None:
        sort_items(self.hero.stash)
        self._changed()
        self.set_status("Stash sorted")

    def _on_click(self, cell: Cell) -> None:
        h = self.hero
        if cell.key >= len(h.stash):
            return  # empty cell
        if len(h.inventory) >= self._inv_cap():
            self.set_status("Inventory full")  # W3.4
            return
        h.inventory.append(h.stash.pop(cell.key))
        self._changed()

    def _on_hover(self, cell: Cell) -> None:
        if not cell.item:
            return
        pos = cell.mapToGlobal(QPoint(0, -6))
        self.tooltip.show_item(cell.item, pos, hero_class=self.hero.class_id)

    def _changed(self) -> None:
        self.tooltip.hide()
        self.refresh()
        if self.on_change:
            self.on_change()

    # ------------------------------------------------------------- refresh
    def refresh(self) -> None:
        h = self.hero
        rows = max(MIN_ROWS, -(-max(1, len(h.stash) + 1) // STASH_COLS))
        want = rows * STASH_COLS
        while len(self.cells) < want:
            i = len(self.cells)
            cell = Cell("stash", i)
            cell.clicked.connect(self._on_click)
            cell.hovered.connect(self._on_hover)
            cell.unhovered.connect(lambda _c: self.tooltip.hide())
            self.cells.append(cell)
            self.grid.addWidget(cell, i // STASH_COLS, i % STASH_COLS)
        for i, cell in enumerate(self.cells):
            cell.set_item(h.stash[i] if i < len(h.stash) else None)
            cell.setVisible(i < want)
        self.stash_all_btn.setEnabled(bool(h.inventory))
        self.take_all_btn.setEnabled(bool(h.stash))
        self.sort_btn.setEnabled(bool(h.stash))
        owned = h.stash_tabs_owned
        cap = stash_tabs.capacity(owned)
        maxed = owned >= stash_tabs.MAX_TABS
        self.buy_tab_btn.setEnabled(not maxed and stash_tabs.can_buy_tab(owned, h.gold))
        if maxed:
            self.buy_tab_btn.setText(f"Slots {cap} (max)")
        else:
            gained = stash_tabs.capacity(owned + 1) - cap
            self.buy_tab_btn.setText(
                f"Buy +{gained} Slots ({stash_tabs.tab_price(owned + 1):,}g)")
        self.title_lab.setText(f"Stash — {len(h.stash)}/{cap} slots")
        self.adjustSize()

    def hideEvent(self, e):
        self.tooltip.hide()
        super().hideEvent(e)  # PanelFrame emits `closed` for the manager


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)

    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    from game.core import Item, Rarity, Slot, StatMod, Stats
    from ui.panels import panel_max_height

    hero = Hero(name="Test", stats=Stats(), base_stats=Stats(), gold=10, class_id="warrior")
    hero.equipment = {s.value: None for s in Slot}
    hero.inventory = [
        Item("coral_ring", "Coral Ring", Slot.RING, Rarity.NORMAL, 5, req_level=1,
             implicit=[StatMod("life", flat=15)]),
        Item("rope_belt", "Rope Belt", Slot.BELT, Rarity.MAGIC, 3, req_level=1),
    ]
    hero.stash = [
        Item("long_sword", "Long Sword", Slot.WEAPON, Rarity.RARE, 15, req_level=12, name="Dread Bane"),
    ]
    hero.init_hp()
    hero.recalc()

    panel = StashPanel(hero, on_change=lambda: None)
    panel.show()

    # stash all: inventory empties into the stash, status reports the count
    panel._stash_all()
    assert hero.inventory == [] and len(hero.stash) == 3
    assert not panel.stash_all_btn.isEnabled()
    assert "Stashed 2" in panel.status.text()

    # click first stash cell -> item returns to inventory
    panel._on_click(panel.cells[0])
    assert len(hero.stash) == 2 and len(hero.inventory) == 1
    assert hero.inventory[0].base_id == "long_sword"

    # take all: everything moves while there is room
    panel._take_all()
    assert hero.stash == [] and len(hero.inventory) == 3
    assert "Took 2" in panel.status.text()
    assert not panel.take_all_btn.isEnabled() and not panel.sort_btn.isEnabled()
    panel._take_all()  # empty stash: explicit feedback, no crash
    assert panel.status.text() == "Stash is empty"

    # take all with a nearly-full inventory: remainder STAYS in the stash
    hero.stash = [Item(f"ring_{i}", f"Ring {i}", Slot.RING, Rarity.NORMAL, 1, req_level=1)
                  for i in range(6)]
    hero.inventory = [hero.stash[0]] * (INV_COLS * INV_ROWS - 2)
    panel.refresh()
    total = len(hero.stash) + len(hero.inventory)
    panel._take_all()
    assert len(hero.inventory) == INV_COLS * INV_ROWS and len(hero.stash) == 4
    assert len(hero.stash) + len(hero.inventory) == total, "take_all must not lose items"
    assert "inventory full" in panel.status.text() and "4 left" in panel.status.text()
    panel._take_all()  # zero room: refusal is reported, not silent
    assert panel.status.text() == "Inventory full"
    panel._on_click(panel.cells[0])  # single-click take is refused too
    assert len(hero.stash) == 4 and panel.status.text() == "Inventory full"

    # sort: slot order, then rarity desc, then ilvl desc (shared sort_items)
    r_low = Item("gold_ring", "Gold Ring", Slot.RING, Rarity.NORMAL, 3, req_level=1)
    r_hi = Item("gold_ring", "Gold Ring", Slot.RING, Rarity.NORMAL, 9, req_level=1)
    sword = Item("long_sword", "Long Sword", Slot.WEAPON, Rarity.RARE, 15, req_level=12)
    magic_ring = Item("iron_ring", "Iron Ring", Slot.RING, Rarity.MAGIC, 5, req_level=1)
    hero.stash = [r_low, magic_ring, sword, r_hi]
    panel.refresh()
    panel._on_sort()
    assert hero.stash == [sword, magic_ring, r_hi, r_low], [i.base_id for i in hero.stash]
    assert panel.status.text() == "Stash sorted"

    # unlimited: grid grows past one page; the clamp keeps the panel above the strip
    hero.inventory = []
    hero.stash.extend(
        Item(f"ring_{i}", f"Ring {i}", Slot.RING, Rarity.NORMAL, 1, req_level=1) for i in range(60)
    )
    panel.refresh()
    assert len(panel.cells) >= 62
    assert panel.height() <= panel_max_height(), (panel.height(), panel_max_height())

    # X and Esc close (PanelFrame)
    panel.close_btn.click()
    assert not panel.isVisible(), "X must close the stash"
    panel.show()
    QTest.keyClick(panel, Qt.Key.Key_Escape)
    assert not panel.isVisible(), "Esc must close the stash"
    panel.show()

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stash_test.png")
    panel.grab().save(path)
    print("OK:", path)
