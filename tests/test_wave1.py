"""Wave 1 loop fixes: boss lifecycle, inventory overflow, re-enter rewards."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

import random

import main as M
from game import classes, world
from game.core import CombatEvent, Item, Rarity, Slot


def make_game():
    hero = classes.make_hero("warrior")
    g = M.Game(hero, {})
    g.strip.hide()
    return g


def test_boss_survives_hero_death():
    g = make_game()
    zone = world.get_zone("a1_ruins")
    g.zone = zone
    g.spawner = world.Spawner(zone, 1.0, g.rng)
    for _ in range(g.spawner.kills_to_boss):
        g.spawner.notify_kill()
    g.spawner.tick(0.05, g.combat.monsters, 0.0, 800.0)
    boss = next(m for m in g.combat.monsters if m.is_boss)
    boss.hp = boss.max_hp * 0.3  # damaged boss
    trash = world.scale_monster(world.TEMPLATES["goblin"], 1, 1.0, g.rng)
    g.combat.monsters.append(trash)
    g.hero.hp = -1
    g._on_hero_death([])
    g._respawn()
    alive = [m for m in g.combat.monsters]
    assert boss in alive, "boss must survive hero death"
    assert trash not in alive, "trash must be cleared on respawn"
    assert boss.hp == boss.max_hp, "boss heals to full"
    print("boss survives hero death OK")


def test_boss_rearm_after_despawn():
    sp = world.Spawner(world.get_zone("a1_ruins"), 1.0, random.Random(1))
    for _ in range(sp.kills_to_boss):
        sp.notify_kill()
    monsters = []
    sp.tick(0.05, monsters, 0.0, 800.0)
    assert sp.boss_spawned
    sp.boss_despawned()  # boss vanished without dying
    for _ in range(sp.rearm_kills):
        assert sp.boss_spawned, "not re-armed before N kills"
        sp.notify_kill()
    assert not sp.boss_spawned, "spawner must re-arm"
    assert sp.notice and "returns" in sp.notice
    monsters = []
    sp.tick(0.05, monsters, 0.0, 800.0)
    assert monsters and monsters[0].is_boss, "boss respawns after re-arm"
    print("boss re-arm OK")


def test_zone_reenter_no_boss_respawn():
    g = make_game()
    g._on_zone_select("a1_ruins", "normal")
    boss = world.scale_monster(world.TEMPLATES["goblin_king"], 18, 1.0, g.rng)
    boss.alive = False
    g.spawner.boss_spawned = True
    g._on_kill(boss, [])
    assert g.spawner.boss_killed
    pts_after_first = g.hero.bonus_points
    assert pts_after_first >= 3, "first kill grants +3"
    # re-enter zone: boss stays dead, no reward duplication
    g._on_zone_select("a1_shore", "normal")
    g._on_zone_select("a1_ruins", "normal")
    assert g.spawner.boss_killed, "killed boss must not respawn on re-enter"
    for _ in range(g.spawner.kills_to_boss + 5):
        g.spawner.notify_kill()
    monsters = []
    g.spawner.tick(0.05, monsters, 0.0, 800.0)
    assert not any(m.is_boss for m in monsters), "no boss respawn in cleared zone"
    boss2 = world.scale_monster(world.TEMPLATES["goblin_king"], 18, 1.0, g.rng)
    boss2.alive = False
    g._on_boss_first_kill(boss2)
    assert g.hero.bonus_points == pts_after_first, "no reward duplication"
    print("zone re-enter OK")


def _stub(rarity, name):
    return Item(base_id="iron_ring", base_name=name, slot=Slot.RING,
                rarity=rarity, ilvl=5)


def test_overflow():
    g = make_game()
    g.hero.inventory = [_stub(Rarity.NORMAL, f"Filler {i}") for i in range(M.INV_CAP)]
    g.hero.stash = []
    events: list[CombatEvent] = []
    uniq = _stub(Rarity.UNIQUE, "The Precious")
    g._overflow_item(uniq, 100.0, events)
    assert uniq in g.hero.stash, "unique must go to stash, never lost"
    assert any("stash" in e.text for e in events)
    gold0 = g.hero.gold
    events.clear()
    g._overflow_item(_stub(Rarity.MAGIC, "Trash Ring"), 100.0, events)
    assert g.hero.gold > gold0, "magic auto-sold"
    assert any("auto-sold" in e.text for e in events), "auto-sell must be visible"
    print("overflow OK")


test_boss_survives_hero_death()
test_boss_rearm_after_despawn()
test_zone_reenter_no_boss_respawn()
test_overflow()
print("test_wave1: ALL OK")
