"""Stash tab limit / purchase logic (ECONOMY_IDLE_SPEC.md — E.2).

Pure, self-contained logic. Items are treated as OPAQUE objects: this module
never imports Item/core and only ever works on counts and lists. The parent
session owns the actual stash container, the save layer and the UI.

--------------------------------------------------------------------------------
TAB-INDEXING DECISION (documented per spec request)
--------------------------------------------------------------------------------
The spec price table is 1-based and lists ten entries:

    Tab :  1     2     3     4     5      6    7    8     9     10
    Cost:  1k    5k    20k   75k   250k   1M   4M   15M   50M   150M

``tab_price(N)`` returns the table entry for tab N *verbatim* (1-based), so the
table maps 1:1 onto the constant and there is no off-by-one surprise.

The player STARTS owning 1 tab. Therefore the first *purchasable* tab is tab 2,
and buying the next tab while you own ``tabs_owned`` tabs costs
``tab_price(tabs_owned + 1)``:

    own 1 -> buy tab  2 -> costs tab_price(2)  = 5k
    own 9 -> buy tab 10 -> costs tab_price(10) = 150M

Because tab 1 is granted for free at start, its 1k table entry is never actually
paid. The gold a player spends to fully unlock the stash is therefore
sum(tab_price(2..10)) = 220,350,000, and the full table sums to
sum(tab_price(1..10)) = 220,351,000 — both land at "≈220M" as the spec states.
(The test asserts the full-table sum is within tolerance of 220M.)

--------------------------------------------------------------------------------
HOOKS THE PARENT MUST WIRE (this module edits nothing else)
--------------------------------------------------------------------------------
Save (game/save.py, SAVE_VERSION stays 5 — additive, migration below):
  * Persist ``stash_tabs_owned: int``. On load: ``sanitize_owned(raw)`` (missing
    field / garbage -> 1).
  * Each stash item carries a tab index. Compute the natural index for an item
    at linear position i with ``tab_of_slot(i)``.
  * Old save WITHOUT these fields -> run ``migrate_unlimited(items, tabs_owned)``:
    the ``fit`` list goes into owned tabs (index via ``tab_of_slot``), the
    ``overflow`` list goes into a service "Overflow" tab that is WITHDRAW-ONLY
    and vanishes once emptied. NEVER auto-delete an item.

Stash container / UI:
  * Before adding an item: reject if ``is_full(len(items), tabs_owned)`` (full
    tab -> red highlight, drop refused). The Overflow tab never accepts adds.
  * Tab bar: locked tab N shows ``tab_price(N)`` in tooltip; two-step buy calls
    ``buy_tab`` and, on ok, commits the returned (tabs_owned, gold).
  * Gate the buy button with ``can_buy_tab(tabs_owned, gold)``.
"""

from __future__ import annotations

__all__ = [
    "STASH_TAB_SLOTS",
    "MAX_TABS",
    "TAB_PRICES",
    "tab_price",
    "can_buy_tab",
    "buy_tab",
    "capacity",
    "is_full",
    "migrate_unlimited",
    "tab_of_slot",
    "sanitize_owned",
]

# --- constants ------------------------------------------------------------- #
STASH_TAB_SLOTS = 40
MAX_TABS = 10

# 1-based price table (see module docstring). TAB_PRICES[0] is the price of
# tab 1, TAB_PRICES[9] is the price of tab 10. Sum ≈ 220M.
TAB_PRICES = [
    1_000,        # tab 1  (granted free at start; entry kept for a 1:1 table)
    5_000,        # tab 2
    20_000,       # tab 3
    75_000,       # tab 4
    250_000,      # tab 5
    1_000_000,    # tab 6
    4_000_000,    # tab 7
    15_000_000,   # tab 8
    50_000_000,   # tab 9
    150_000_000,  # tab 10
]


# --- pricing --------------------------------------------------------------- #
def tab_price(tab_number: int) -> int:
    """Price of the tab numbered ``tab_number`` (1-based, verbatim from table).

    Raises ValueError outside [1, MAX_TABS]. Callers that ask for the "next"
    tab should guard with ``tabs_owned < MAX_TABS`` first (``can_buy_tab``
    already does).
    """
    if not (1 <= tab_number <= MAX_TABS):
        raise ValueError(f"tab_number must be in [1, {MAX_TABS}], got {tab_number}")
    return TAB_PRICES[tab_number - 1]


def can_buy_tab(tabs_owned: int, gold: int) -> bool:
    """True iff there is a next tab to buy and the player can afford it."""
    tabs_owned = sanitize_owned(tabs_owned)
    if tabs_owned >= MAX_TABS:
        return False
    return int(gold) >= tab_price(tabs_owned + 1)


def buy_tab(tabs_owned: int, gold: int) -> tuple[int, int, bool]:
    """Atomically buy the next tab.

    Returns (new_tabs_owned, new_gold, ok). On failure nothing changes and ok is
    False. Gold can never go negative — the affordability check guarantees it.
    """
    tabs_owned = sanitize_owned(tabs_owned)
    gold = int(gold)
    if not can_buy_tab(tabs_owned, gold):
        return tabs_owned, gold, False
    price = tab_price(tabs_owned + 1)
    return tabs_owned + 1, gold - price, True


# --- capacity -------------------------------------------------------------- #
def capacity(tabs_owned: int) -> int:
    """Total item slots across all owned tabs."""
    return sanitize_owned(tabs_owned) * STASH_TAB_SLOTS


def is_full(item_count: int, tabs_owned: int) -> bool:
    """True when the stash can hold no more items (boundary is exactly capacity)."""
    return int(item_count) >= capacity(tabs_owned)


def tab_of_slot(slot_index: int) -> int:
    """0-based tab that a linear slot index lands in (40 slots per tab)."""
    return int(slot_index) // STASH_TAB_SLOTS


# --- migration ------------------------------------------------------------- #
def migrate_unlimited(items: list, tabs_owned: int) -> tuple[list, list]:
    """Split a legacy unlimited stash into (fit, overflow).

    ``fit`` are the items that lay into the owned tabs in order; ``overflow`` is
    the remainder destined for the withdraw-only Overflow tab. Order is
    preserved and NO item is lost: len(fit) + len(overflow) == len(items).
    """
    cap = capacity(tabs_owned)
    fit = list(items[:cap])
    overflow = list(items[cap:])
    return fit, overflow


# --- save hygiene ---------------------------------------------------------- #
def sanitize_owned(raw) -> int:
    """Clamp ``raw`` into [1, MAX_TABS]; coerce to int; default 1 on garbage."""
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return 1
    if val < 1:
        return 1
    if val > MAX_TABS:
        return MAX_TABS
    return val
