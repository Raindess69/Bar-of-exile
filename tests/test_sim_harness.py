"""tools/sim.py must follow the same equip rules as the game."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import sim  # noqa: E402
from game.items import make_base_item  # noqa: E402


def test_sim_never_equips_other_class_gear():
    s = sim.Sim("mage", hours=0.0, seed=1)
    bow = make_base_item("imperial_bow", 1)
    assert bow.class_req == ("archer",)
    bow.req_level = 1
    before = s.hero.equipment.get("weapon")
    assert s.try_equip(bow) is False
    assert s.hero.equipment.get("weapon") is before


def test_sim_still_equips_own_class_upgrades():
    s = sim.Sim("mage", hours=0.0, seed=1)
    staff = make_base_item("runic_staff", 1)
    assert "mage" in staff.class_req
    staff.req_level = 1
    assert s.try_equip(staff) is True
    assert s.hero.equipment["weapon"] is staff


if __name__ == "__main__":
    test_sim_never_equips_other_class_gear()
    test_sim_still_equips_own_class_upgrades()
    print("ok")
