"""Regression test: save files must survive crashes and corruption.

Before: save_game wrote <slot>.json.tmp and os.replace'd it without fsync, and
kept no backup. A power loss / BSOD right after an autosave could leave a
zero-length or garbage slot file; load_game then returned None and the hero
silently vanished from the load screen (up to ~168h of idle progress lost).

Now: the temp file is fsync'd before the swap, the previous *valid* save is kept
as <slot>.json.bak, and load_game falls back to it when the main file is corrupt.

Run from repo root:  python tests/test_save_durability.py   (or via pytest)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import classes
from game.save import BACKUP_SUFFIX, load_game, save_game


def _hero(level: int):
    hero = classes.make_hero("warrior", name="Durable")
    hero.level = level
    return hero


def test_save_then_load_roundtrip_and_no_stray_tmp():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "warrior_durable_abc123.json")
        save_game(path, _hero(5), {"kills": 1})
        loaded = load_game(path)
        assert loaded is not None and loaded[0].level == 5
        assert not os.path.exists(path + ".tmp"), "temp file must be swapped away"


def test_backup_holds_previous_good_save():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "warrior_durable_abc123.json")
        save_game(path, _hero(5), {})
        assert not os.path.exists(path + BACKUP_SUFFIX), "no backup on first save"
        save_game(path, _hero(6), {})
        with open(path + BACKUP_SUFFIX, encoding="utf-8") as f:
            assert json.load(f)["hero"]["level"] == 5
        assert load_game(path)[0].level == 6


def test_corrupt_main_recovers_from_backup():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "warrior_durable_abc123.json")
        save_game(path, _hero(10), {})
        save_game(path, _hero(11), {})          # backup now holds level 10
        with open(path, "w", encoding="utf-8") as f:
            f.write("")                         # simulate crash: zero-length file
        loaded = load_game(path)
        assert loaded is not None, "hero must be recovered, not lost"
        assert loaded[0].level == 10


def test_corrupt_main_never_overwrites_good_backup():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "warrior_durable_abc123.json")
        save_game(path, _hero(20), {})
        save_game(path, _hero(21), {})          # backup = 20
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"hero": {trunc')         # corrupt main
        save_game(path, _hero(22), {})          # must NOT rotate garbage into .bak
        with open(path + BACKUP_SUFFIX, encoding="utf-8") as f:
            assert json.load(f)["hero"]["level"] == 20
        assert load_game(path)[0].level == 22


def test_missing_file_and_unrecoverable_corruption_return_none():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "warrior_durable_abc123.json")
        assert load_game(path) is None
        with open(path, "w", encoding="utf-8") as f:
            f.write("not json")                 # corrupt, and no backup exists
        assert load_game(path) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
