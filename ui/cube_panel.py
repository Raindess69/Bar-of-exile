"""Bar of Exile — Horadric-cube popup panel. Recipes in game/cube.py.

UX wave (spec §6): sits on PanelFrame — title bar with X, Esc closes, height
clamped above the game strip, refused actions report through the status line.
"""
from __future__ import annotations

import random

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QGridLayout, QHBoxLayout,
                            QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from game.core import Hero, Item, Rarity
from game.cube import (RECIPES, can_corrupt, corrupt_cost, corrupt_flash_text,
                       corrupt_item, corruption_chance_text, has_corrupted,
                       transmute)
from ui.panels import BTN_QSS, INV_COLS, INV_ROWS, Cell, ItemTooltip, PanelFrame, _hdr

CUBE_SLOTS = 4
_TAB_W = 122   # width of the vertical tab column
_PAGE_W = 240  # width of a tab's action page (room for description + buttons)
_STATION_W = _TAB_W + 8 + _PAGE_W

_CORRUPT_QSS = (
    "QPushButton{background:#3a1414; color:#e08080; border:1px solid #7a2a2a;"
    " padding:4px 8px; font-weight:bold;}"
    "QPushButton:hover{background:#4a1a1a;}"
    "QPushButton:disabled{color:#6a4a4a; border-color:#4a2a2a;}"
)
_CONFIRM_QSS = (
    "QPushButton{background:#8a1a1a; color:#ffdcdc; border:2px solid #ff4040;"
    " padding:4px 8px; font-weight:bold;}"
    "QPushButton:hover{background:#a02020;}"
)
# Vertical tab selector — one row per cube operation. Scales past 10 ops without
# stealing space from the per-op description/buttons (the whole point of the tabs).
_TAB_QSS = (
    "QPushButton{background:#1c1c22; color:#b0b0b8; border:1px solid #33333c;"
    " padding:6px 8px; text-align:left;}"
    "QPushButton:hover{background:#26262e;}"
    "QPushButton:checked{background:#2e2e3a; color:#ffffff; border-color:#5a5a7a;"
    " font-weight:bold;}"
)

# Per-recipe UI text (kept in the UI layer — engine recipes stay untouched).
# Falls back to Recipe.name for any recipe without an entry here.
_TAB_LABELS = {
    "norm3_magic": "3 → Magic",
    "magic3_rare": "3 Magic → Rare",
    "rare_reroll": "Reroll Rare",
    "rings_amulet": "Rings → Amulet",
    "ilvl_up": "ilvl +5",
}
_RECIPE_HELP = {
    "norm3_magic": "Place 3 Normal items of the SAME base. Reforges them into one "
                   "Magic item.",
    "magic3_rare": "Place any 3 Magic items. The highest item-level one is reforged "
                   "into a Rare.",
    "rare_reroll": "Place 3 Magic + 1 Rare. Re-rolls the Rare's affixes into a fresh "
                   "Rare.",
    "rings_amulet": "Place 2 Rings. Produces a Magic Amulet at their average item "
                    "level.",
    "ilvl_up": "Place any 3 items. The first gains +5 item level (up to 100). Fuel "
               "with junk.",
}
_CORRUPT_HELP = ("Place a SINGLE item, then CORRUPT. Permanent and risky — it can add "
                 "an over-limit line, degrade the item, or DESTROY it outright. A "
                 "corrupted item is locked out of every other recipe.")


class CubePanel(PanelFrame):
    def __init__(self, hero: Hero, on_change=None, rng: random.Random | None = None,
                 on_flash=None, on_save=None):
        super().__init__("Transmutation Cube")
        self.hero, self.on_change = hero, on_change
        # cube step 1: on_flash(str) queues a result banner; on_save() is the
        # immediate atomic autosave after a corruption roll (§6.1).
        self.on_flash = on_flash
        self.on_save = on_save
        self.rng = rng or random.Random()
        self.cube_items: list[Item | None] = [None] * CUBE_SLOTS
        self._corrupt_armed = False  # two-step ARE YOU SURE? state
        self.tooltip = ItemTooltip()

        root = QHBoxLayout(self.content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        # ---- left column: shared cube slots + result, then the tabbed station.
        left = QVBoxLayout()
        left.setSpacing(6)
        cube_grid = QGridLayout()
        cube_grid.setSpacing(4)
        self.cube_cells: list[Cell] = []
        for i in range(CUBE_SLOTS):
            cell = Cell("cube", i)
            self._wire(cell)
            self.cube_cells.append(cell)
            cube_grid.addWidget(cell, 0, i)
        left.addLayout(cube_grid)
        self.result_lab = QLabel("Pick an operation, place items")
        self.result_lab.setObjectName("dim")
        self.result_lab.setWordWrap(True)
        self.result_lab.setFixedWidth(_STATION_W)
        left.addWidget(self.result_lab)
        left.addWidget(self._build_station())
        left.addStretch(1)
        root.addLayout(left)

        inv_box = QVBoxLayout()
        inv_box.setSpacing(4)
        inv_box.addWidget(_hdr("Inventory"))
        inv_grid = QGridLayout()
        inv_grid.setSpacing(4)
        self.inv_cells: list[Cell] = []
        for i in range(INV_COLS * INV_ROWS):
            cell = Cell("inv", i)
            self._wire(cell)
            self.inv_cells.append(cell)
            inv_grid.addWidget(cell, i // INV_COLS, i % INV_COLS)
        inv_box.addLayout(inv_grid)
        inv_box.addStretch(1)
        root.addLayout(inv_box)

        self.refresh()

    # ---------------------------------------------------------------- station
    def _build_station(self) -> QWidget:
        """Vertical tab column + stacked action pages. One tab per cube
        operation (5 recipes + Corrupt); each page owns its own description and
        buttons so a growing op list never crowds them (user directive)."""
        station = QWidget()
        row = QHBoxLayout(station)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.tab_col = QVBoxLayout()
        self.tab_col.setSpacing(2)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.pages = QStackedWidget()
        self.pages.setFixedWidth(_PAGE_W)
        # page index -> Recipe (recipe tabs) or None (the Corrupt tab)
        self._page_recipe: dict[int, object] = {}
        self._transmute_btns: dict[int, QPushButton] = {}

        for recipe in RECIPES:
            self._add_recipe_tab(recipe)
        self._add_corrupt_tab()

        self.tab_group.idClicked.connect(self._on_tab)
        self.tab_col.addStretch(1)
        tab_wrap = QWidget()
        tab_wrap.setFixedWidth(_TAB_W)
        tab_wrap.setLayout(self.tab_col)
        row.addWidget(tab_wrap)
        row.addWidget(self.pages)

        first = self.tab_group.button(0)
        if first:
            first.setChecked(True)
        return station

    def _add_tab_button(self, idx: int, text: str) -> None:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setStyleSheet(_TAB_QSS)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tab_group.addButton(btn, idx)
        self.tab_col.addWidget(btn)

    def _add_recipe_tab(self, recipe) -> None:
        idx = self.pages.count()
        self._add_tab_button(idx, _TAB_LABELS.get(recipe.id, recipe.name))
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        title = _hdr(recipe.name)
        title.setWordWrap(True)
        box.addWidget(title)
        help_lab = QLabel(_RECIPE_HELP.get(recipe.id, ""))
        help_lab.setObjectName("dim")
        help_lab.setWordWrap(True)
        box.addWidget(help_lab)
        box.addStretch(1)
        if recipe.id == "norm3_magic":
            self.fill_btn = QPushButton("Auto-fill 3× same base")
            self.fill_btn.setStyleSheet(BTN_QSS)
            self.fill_btn.clicked.connect(self._fill_three_same)
            box.addWidget(self.fill_btn)
        btn = QPushButton("Transmute")
        btn.setStyleSheet(BTN_QSS)
        btn.clicked.connect(self._on_transmute)
        box.addWidget(btn)
        self._transmute_btns[idx] = btn
        self._page_recipe[idx] = recipe
        self.pages.addWidget(page)

    def _add_corrupt_tab(self) -> None:
        idx = self.pages.count()
        self._add_tab_button(idx, "☠ Corrupt")
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        title = _hdr("Corruption")
        box.addWidget(title)
        help_lab = QLabel(_CORRUPT_HELP)
        help_lab.setObjectName("dim")
        help_lab.setWordWrap(True)
        box.addWidget(help_lab)
        self.corrupt_lab = QLabel("")
        self.corrupt_lab.setObjectName("dim")
        self.corrupt_lab.setWordWrap(True)
        box.addWidget(self.corrupt_lab)
        box.addStretch(1)
        self.corrupt_btn = QPushButton("CORRUPT")
        self.corrupt_btn.setStyleSheet(_CORRUPT_QSS)
        self.corrupt_btn.clicked.connect(self._on_corrupt)
        box.addWidget(self.corrupt_btn)
        self._transmute_btns[idx] = None  # corrupt tab has no transmute button
        self._page_recipe[idx] = None
        self.pages.addWidget(page)
        self._corrupt_page = idx

    def _on_tab(self, idx: int) -> None:
        self.pages.setCurrentIndex(idx)
        self._disarm_corrupt()
        self.refresh()

    def _wire(self, cell: Cell) -> None:
        cell.clicked.connect(self._on_click)
        cell.hovered.connect(self._on_hover)
        cell.unhovered.connect(lambda _c: self.tooltip.hide())

    def _cap(self) -> int:
        return INV_COLS * INV_ROWS

    def _on_click(self, cell: Cell) -> None:
        h = self.hero
        if cell.kind == "inv":
            if cell.key >= len(h.inventory):
                return  # empty cell
            if None not in self.cube_items:
                self.set_status("Cube is full")  # W3.4: no silent refusal
                return
            slot = self.cube_items.index(None)
            self.cube_items[slot] = h.inventory.pop(cell.key)
        else:
            item = self.cube_items[cell.key]
            if not item:
                return
            if len(h.inventory) >= self._cap():
                self.set_status("Inventory full")  # W3.4
                return
            self.cube_items[cell.key] = None
            h.inventory.append(item)
        self._changed()

    def _on_hover(self, cell: Cell) -> None:
        if cell.item:
            self.tooltip.show_item(cell.item, cell.mapToGlobal(QPoint(0, -6)))

    def _on_transmute(self) -> None:
        items = [it for it in self.cube_items if it]
        if not items:
            self.result_lab.setText("Cube is empty")
            return
        # Run the CURRENT tab's recipe explicitly — two recipes can both accept
        # the same items (e.g. ilvl_up vs 3→Magic), and the tab is the user's
        # stated intent. Falls back to generic matching if no tab recipe.
        recipe = self._page_recipe.get(self.pages.currentIndex())
        if recipe is not None:
            if any(getattr(it, "corruption", 0) >= 1 for it in items):
                # engine lock: corrupted items are barred from every normal recipe
                self.result_lab.setText("Corrupted items can only be corrupted further")
                return
            if not recipe.check(items):
                self.result_lab.setText(f"Items don't match: {recipe.name}")
                return
            result, name = recipe.apply(items, self.rng), recipe.name
        else:
            result, name = transmute(items, self.rng)
        if result is None:
            self.result_lab.setText(name)
            return
        self.cube_items = [None] * CUBE_SLOTS
        for i, it in enumerate(result[:CUBE_SLOTS]):
            self.cube_items[i] = it
        self.result_lab.setText(name)
        self._changed()

    def _changed(self) -> None:
        self.tooltip.hide()
        self._disarm_corrupt()
        self.refresh()
        if self.on_change:
            self.on_change()

    # ------------------------------------------------------------ corruption
    def _corrupt_target(self) -> Item | None:
        """Corruption acts on a single item — valid only when exactly one item
        sits in the cube (no ambiguity with the multi-item recipes)."""
        items = [it for it in self.cube_items if it]
        return items[0] if len(items) == 1 else None

    def _disarm_corrupt(self) -> None:
        self._corrupt_armed = False
        self.corrupt_btn.setText("CORRUPT")
        self.corrupt_btn.setStyleSheet(_CORRUPT_QSS)

    def _on_corrupt(self) -> None:
        item = self._corrupt_target()
        if item is None:
            self.corrupt_lab.setText("Place a single item to corrupt")
            self._disarm_corrupt()
            return
        ok, why = can_corrupt(item)
        if not ok:
            self.corrupt_lab.setText(why)
            self._disarm_corrupt()
            return
        cost = corrupt_cost(item)
        if self.hero.gold < cost:
            self.corrupt_lab.setText(f"Need {cost} gold to corrupt")
            self._disarm_corrupt()
            return
        if not self._corrupt_armed:
            # first click -> arm the two-step confirmation (no modal, §5)
            self._corrupt_armed = True
            self.corrupt_btn.setText("ARE YOU SURE?")
            self.corrupt_btn.setStyleSheet(_CONFIRM_QSS)
            return
        self._do_corrupt(item, cost)

    def _do_corrupt(self, item: Item, cost: int) -> None:
        """Atomic (§6.1): gold -> roll -> apply -> remove-if-destroyed -> save,
        all in this one function so a kill after the roll cannot save-scum."""
        self._disarm_corrupt()
        slot = self.cube_items.index(item)
        name = item.display_name()
        self.hero.gold -= cost                     # §6.4: charged BEFORE the roll
        result = corrupt_item(item, self.rng)
        if result.outcome == "destroy":
            # §6.2: the cube slot is the sole live reference — dropping it removes
            # the item from the game with no dangling refs in stash/buyback.
            self.cube_items[slot] = None
        flash = corrupt_flash_text(result, name)
        # L1: the player-visible banner is the on_flash strip; a corrupt_lab
        # setText here is dead — return_items() below refreshes and clears it.
        if self.on_flash:
            self.on_flash(flash)
        self.tooltip.hide()
        # M1: cube_items is not serialized; a survived item lives ONLY in its slot,
        # so the immediate autosave below would checkpoint gold-spent-but-item-gone.
        # Flush survivors to inventory (a serialized container) BEFORE saving — same
        # contract as hideEvent/quit. Player re-places to corrupt further.
        self.return_items()
        if self.on_change:
            self.on_change()
        if self.on_save:
            self.on_save()                          # §6.1: immediate autosave

    @staticmethod
    def _find_triple(items: list[Item]) -> str | None:
        counts: dict[str, int] = {}
        for it in items:
            if it.rarity is Rarity.NORMAL:
                counts[it.base_id] = counts.get(it.base_id, 0) + 1
                if counts[it.base_id] == 3:
                    return it.base_id
        return None

    def _fill_three_same(self) -> None:
        self.return_items()
        h = self.hero
        base_id = self._find_triple(h.inventory)
        if base_id is None:
            self.result_lab.setText("No 3 identical bases in inventory")
            return
        picked = [it for it in h.inventory
                  if it.rarity is Rarity.NORMAL and it.base_id == base_id][:3]
        taken = {id(it) for it in picked}
        h.inventory[:] = [it for it in h.inventory if id(it) not in taken]
        for i, it in enumerate(picked):
            self.cube_items[i] = it
        self.result_lab.setText(f"Placed 3x {picked[0].base_name}")
        self._changed()

    def refresh(self) -> None:
        for i, cell in enumerate(self.cube_cells):
            cell.set_item(self.cube_items[i])
        for i, cell in enumerate(self.inv_cells):
            cell.set_item(self.hero.inventory[i] if i < len(self.hero.inventory) else None)
        pool = self.hero.inventory + [it for it in self.cube_items if it]
        self.fill_btn.setEnabled(self._find_triple(pool) is not None)
        idx = self.pages.currentIndex()
        items = [it for it in self.cube_items if it]
        recipe = self._page_recipe.get(idx)
        btn = self._transmute_btns.get(idx)
        if recipe is not None and btn is not None:
            # per-tab: the Transmute button lights up only when the cube contents
            # match THIS recipe (not just any recipe) — clear, honest feedback.
            # L3: mirror transmute()'s gate — a corrupted item is locked out of
            # every normal recipe, so the button must stay dark for it too.
            btn.setEnabled(recipe.check(items) and not has_corrupted(items))
        self._refresh_corrupt()
        self.adjustSize()

    def _refresh_corrupt(self) -> None:
        """Show the CORRUPT button + chance panel only for a single cube item;
        the chance text comes from the same table the roll uses (§5)."""
        item = self._corrupt_target()
        if item is None:
            self.corrupt_btn.setEnabled(False)
            self.corrupt_lab.setText("")
            return
        ok, why = can_corrupt(item)
        if not ok:
            self.corrupt_btn.setEnabled(False)      # corruption 3 = terminal (§4)
            self.corrupt_lab.setText(why)
            return
        self.corrupt_btn.setEnabled(True)
        cost = corrupt_cost(item)
        text = corruption_chance_text(item.corruption, item.rarity)
        self.corrupt_lab.setText(f"{text}\nCost: {cost} gold")

    def return_items(self) -> None:
        for i, it in enumerate(self.cube_items):
            if it:
                self.hero.inventory.append(it)
                self.cube_items[i] = None
        self.refresh()

    def _select_tab_by_recipe(self, recipe_id: str | None) -> None:
        """Test/host helper: activate the tab whose recipe has `recipe_id`
        (or the Corrupt tab when `recipe_id` is None)."""
        for idx, rec in self._page_recipe.items():
            if (rec.id if rec is not None else None) == recipe_id:
                self.tab_group.button(idx).setChecked(True)
                self._on_tab(idx)
                return
        # L4: no tab owns this recipe — a silent no-op left the caller believing
        # a tab was selected. Fail loud so a typo'd id surfaces immediately.
        known = [rec.id if rec is not None else None
                 for rec in self._page_recipe.values()]
        raise KeyError(f"no cube tab for recipe {recipe_id!r}; have {known}")

    def hideEvent(self, e):
        self.tooltip.hide()
        self.return_items()
        if self.on_change:
            self.on_change()
        super().hideEvent(e)  # PanelFrame emits `closed` for the manager


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)

    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    from game.core import Rarity, Stats
    from game.affixes import roll_affixes
    from game.loot import make_item
    from ui.panels import panel_max_height

    rng = random.Random(7)
    hero = Hero(name="Test", stats=Stats(), base_stats=Stats(), class_id="warrior")
    hero.init_hp()
    for i in range(3):
        it = make_item(20 + i, rng)
        it.rarity = Rarity.MAGIC
        roll_affixes(it, rng)
        hero.inventory.append(it)
    hero.inventory.append(make_item(10, rng))

    panel = CubePanel(hero, on_change=lambda: None, rng=rng)
    panel.show()

    panel._select_tab_by_recipe("magic3_rare")
    for _ in range(3):
        panel._on_click(panel.inv_cells[0])
    assert sum(1 for it in panel.cube_items if it) == 3
    assert len(hero.inventory) == 1

    panel._on_transmute()
    out = [it for it in panel.cube_items if it]
    assert len(out) == 1 and out[0].rarity is Rarity.RARE
    assert "Rare" in panel.result_lab.text()
    print("recipe:", panel.result_lab.text())
    print("result:", f"[{out[0].rarity.value}] {out[0].display_name()} (ilvl {out[0].ilvl})")

    panel._on_click(panel.cube_cells[0])
    assert panel.cube_items[0] is None and len(hero.inventory) == 2

    panel._on_click(panel.inv_cells[0])
    panel.hide()
    assert all(it is None for it in panel.cube_items) and len(hero.inventory) == 2

    panel.show()
    panel._on_transmute()
    assert "match" in panel.result_lab.text() or "empty" in panel.result_lab.text()

    # --- 3x same base button (lives on the norm3_magic tab) ---
    panel._select_tab_by_recipe("norm3_magic")
    proto = make_item(15, rng)
    proto.rarity = Rarity.NORMAL
    hero.inventory.append(proto)
    for _ in range(2):
        it = make_item(15, rng)
        it.rarity = Rarity.NORMAL
        it.base_id, it.base_name, it.slot = proto.base_id, proto.base_name, proto.slot
        hero.inventory.append(it)
    panel.refresh()
    assert panel.fill_btn.isEnabled()

    inv_before = len(hero.inventory)
    panel._fill_three_same()
    assert sum(1 for it in panel.cube_items if it) == 3
    assert len(hero.inventory) == inv_before - 3
    assert panel.result_lab.text() == f"Placed 3x {proto.base_name}"
    print("fill:", panel.result_lab.text())

    panel._on_transmute()
    out = [it for it in panel.cube_items if it]
    assert len(out) == 1 and out[0].rarity is Rarity.MAGIC and out[0].base_id == proto.base_id
    print("result:", f"[{out[0].rarity.value}] {out[0].display_name()} (ilvl {out[0].ilvl})")

    panel.return_items()
    assert not panel.fill_btn.isEnabled()
    panel._fill_three_same()
    assert panel.result_lab.text() == "No 3 identical bases in inventory"
    assert all(it is None for it in panel.cube_items)

    # W3.4: full cube / full inventory refusals report through the status line
    fillers = [make_item(5, rng) for _ in range(CUBE_SLOTS + 1)]
    hero.inventory.extend(fillers)
    panel.refresh()
    for _ in range(CUBE_SLOTS):
        panel._on_click(panel.inv_cells[0])
    assert None not in panel.cube_items
    panel._on_click(panel.inv_cells[0])  # cube already full
    assert panel.status.text() == "Cube is full"
    n_inv = len(hero.inventory)
    hero.inventory.extend(make_item(5, rng) for _ in range(INV_COLS * INV_ROWS - n_inv))
    panel.refresh()
    panel._on_click(panel.cube_cells[0])  # inventory has no room to take it back
    assert panel.cube_items[0] is not None
    assert panel.status.text() == "Inventory full"
    panel.return_items()  # inventory overflows the grid but items are not lost
    assert all(it is None for it in panel.cube_items)

    # --- tabbed corruption: switch tab, a single item arms the CORRUPT button ---
    panel.return_items()
    hero.inventory.clear()
    hero.gold = 100000
    single = make_item(30, rng)
    single.rarity = Rarity.RARE
    roll_affixes(single, rng)
    hero.inventory.append(single)
    panel.refresh()
    panel._select_tab_by_recipe(None)  # Corrupt tab
    assert panel.pages.currentIndex() == panel._corrupt_page
    panel._on_click(panel.inv_cells[0])   # one item in the cube
    assert panel.corrupt_btn.isEnabled()
    assert "Corrupt" in panel.corrupt_lab.text()
    panel._on_corrupt()                   # first click -> arm
    assert panel.corrupt_btn.text() == "ARE YOU SURE?"
    panel._disarm_corrupt()
    panel.return_items()
    print("corrupt tab OK")

    # PanelFrame: X button and Esc close; the panel never overlaps the strip
    panel.show()
    assert panel.height() <= panel_max_height()
    panel.close_btn.click()
    assert not panel.isVisible(), "X must close the cube"
    panel.show()
    QTest.keyClick(panel, Qt.Key.Key_Escape)
    assert not panel.isVisible(), "Esc must close the cube"

    panel.show()
    panel.refresh()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cube_test.png")
    panel.grab().save(path)
    print("OK:", path)
