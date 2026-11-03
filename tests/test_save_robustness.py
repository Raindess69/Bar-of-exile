"""Audit 2026-11-03: autosave must survive transient Windows file locks.

Before: Game.save() (autosave QTimer every 30 s + aboutToQuit) called
save_game() unguarded. An OSError there - e.g. PermissionError from os.replace
while antivirus/OneDrive holds save.json - is raised inside a Qt slot, and
PyQt6 then calls abort(): the whole game closes (exit code 134).
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

import main as M
from game import classes
from game import save as save_mod

_real_replace = os.replace


def _hero():
    return classes.make_hero("warrior")


def test_transient_permission_error_is_retried(tmp_path, monkeypatch):
    path = str(tmp_path / "save.json")
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(13, "[WinError 32] file is being used by another process")
        return _real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    monkeypatch.setattr(save_mod.time, "sleep", lambda _s: None)
    save_mod.save_game(path, _hero(), {"kills": 7})
    assert calls["n"] == 3
    loaded = save_mod.load_game(path)
    assert loaded is not None and loaded[1]["kills"] == 7


def test_persistent_lock_raises_and_keeps_previous_save(tmp_path, monkeypatch):
    path = str(tmp_path / "save.json")
    save_mod.save_game(path, _hero(), {"kills": 1})

    def locked(src, dst):
        raise PermissionError(13, "[WinError 5] Access is denied")

    monkeypatch.setattr(os, "replace", locked)
    monkeypatch.setattr(save_mod.time, "sleep", lambda _s: None)
    try:
        save_mod.save_game(path, _hero(), {"kills": 2})
    except PermissionError:
        pass
    else:
        raise AssertionError("persistent PermissionError must propagate from save_game")
    monkeypatch.setattr(os, "replace", _real_replace)
    loaded = save_mod.load_game(path)
    assert loaded is not None and loaded[1]["kills"] == 1  # previous save intact


def test_save_is_fsynced_before_replace(tmp_path, monkeypatch):
    order = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(os, "replace", lambda s, d: (order.append("replace"), _real_replace(s, d))[1])
    save_mod.save_game(str(tmp_path / "save.json"), _hero(), {})
    assert order == ["fsync", "replace"]


def test_game_save_survives_os_error(tmp_path, monkeypatch, capsys):
    g = M.Game(_hero(), {}, save_path=str(tmp_path / "slot.json"))
    g.strip.hide()

    def boom(*_a, **_k):
        raise PermissionError(13, "[WinError 5] Access is denied")

    monkeypatch.setattr(M, "save_game", boom)
    g.save()  # must not raise (would abort the app from the QTimer slot)
    assert "could not write" in capsys.readouterr().out
    monkeypatch.undo()
    g.save()
    assert save_mod.load_game(str(tmp_path / "slot.json")) is not None
