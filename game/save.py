"""Bar of Exile — serialization and save files."""
from __future__ import annotations

import json
import os
import random
import sys
import time
from dataclasses import fields as dataclass_fields

from game.core import Affix, Hero, Item, Rarity, RARITY_LADDER, Slot, StatMod, Stats


def _default_save_dir() -> str:
    """Where save files live.

    Source run: <repo>/saves (next to the game package). Frozen build
    (PyInstaller): a `saves/` folder NEXT TO the .exe — never inside the bundle,
    which for a onefile build is a temp dir wiped on exit (players would lose
    progress every launch). Override with BOE_SAVE_DIR for portable/testing use."""
    env = os.environ.get("BOE_SAVE_DIR")
    if env:
        return env
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "saves")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "saves")


SAVE_DIR = _default_save_dir()
DEFAULT_SAVE = os.path.join(SAVE_DIR, "save.json")
# Stage 6.1: offline is a reduced-efficiency catch-up channel — never better than
# leaving the window open. Piecewise efficiency over elapsed away-time; past the
# last boundary the character earns nothing (come back and play).
OFFLINE_TIERS = [(8 * 3600, 0.60), (24 * 3600, 0.35), (72 * 3600, 0.15)]
OFFLINE_ITEM_ROLLS_CAP = 20  # how many drops are actually rolled per away-session
OFFLINE_ITEMS_KEEP = 20      # magic+ finds kept; normals auto-salvaged to gold

# best-first sort key across the full 10-tier ladder (higher desirability = lower
# number). Derived from core.RARITY_LADDER so new tiers are covered automatically.
_RARITY_ORDER = {r: len(RARITY_LADDER) - 1 - i for i, r in enumerate(RARITY_LADDER)}
SAVE_VERSION = 5  # v5: Skills V2 block (hero.skills_v2); v4: per-skill socketed passives (hero.skill_runes); v3: 1001-node tree (old passive ids refunded), StatMod.more, meta.tree_version/boss_bonus


def _mod_to_dict(m: StatMod) -> dict:
    d = {"stat": m.stat, "flat": m.flat, "inc": m.inc}
    if m.more:
        d["more"] = m.more
    return d


def _mod_from_dict(d: dict) -> StatMod:
    return StatMod(stat=d["stat"], flat=d.get("flat", 0.0), inc=d.get("inc", 0.0),
                   more=d.get("more", 0.0))


def _affix_to_dict(a: Affix) -> dict:
    d = {
        "id": a.id,
        "name": a.name,
        "is_prefix": a.is_prefix,
        "tier": a.tier,
        "mods": [_mod_to_dict(m) for m in a.mods],
    }
    if a.lines:
        d["lines"] = list(a.lines)
    if getattr(a, "stars", 0):
        d["stars"] = int(a.stars)  # E.5 greater-affix tier (omitted when 0)
    return d


def _affix_from_dict(d: dict) -> Affix:
    return Affix(
        id=d["id"],
        name=d["name"],
        is_prefix=d["is_prefix"],
        tier=d["tier"],
        mods=[_mod_from_dict(m) for m in d.get("mods", [])],
        lines=list(d.get("lines", [])),
        stars=int(d.get("stars", 0)),
    )


def item_to_dict(item: Item) -> dict:
    return {
        "base_id": item.base_id,
        "base_name": item.base_name,
        "slot": item.slot.value,
        "rarity": item.rarity.value,
        "ilvl": item.ilvl,
        "req_level": item.req_level,
        "name": item.name,
        "class_req": list(item.class_req),
        "implicit": [_mod_to_dict(m) for m in item.implicit],
        "affixes": [_affix_to_dict(a) for a in item.affixes],
        # cube rework step 1: corruption level + over-limit red lines
        "corruption": int(getattr(item, "corruption", 0)),
        "corrupted_lines": [_affix_to_dict(a) for a in getattr(item, "corrupted_lines", [])],
        # 10-tier ladder relic/primal overlay (omit when empty for back-compat)
        "modifier": getattr(item, "modifier", "") or "",
    }


def item_from_dict(d: dict) -> Item:
    return Item(
        base_id=d["base_id"],
        base_name=d["base_name"],
        slot=Slot(d["slot"]),
        rarity=Rarity(d["rarity"]),
        ilvl=d["ilvl"],
        req_level=d.get("req_level", 1),
        name=d.get("name", ""),
        class_req=tuple(d.get("class_req", ())),
        implicit=[_mod_from_dict(m) for m in d.get("implicit", [])],
        affixes=[_affix_from_dict(a) for a in d.get("affixes", [])],
        # old saves lack these -> default 0 / [] (never crash)
        corruption=int(d.get("corruption", 0)),
        corrupted_lines=[_affix_from_dict(a) for a in d.get("corrupted_lines", [])],
        modifier=str(d.get("modifier", "") or ""),
    )


def hero_to_dict(hero: Hero) -> dict:
    return {
        "class_id": hero.class_id,
        "name": hero.name,
        "level": hero.level,
        "xp": hero.xp,
        "gold": hero.gold,
        # passive_mods is runtime-only and intentionally NOT saved (tree module rebuilds it)
        "passives": list(getattr(hero, "passives", [])),
        "bonus_points": int(getattr(hero, "bonus_points", 0)),
        # S.4 rework: Class Points earned from act-boss first kills (boss ids).
        "class_point_sources": list(getattr(hero, "class_point_sources", [])),
        "active_skills": list(getattr(hero, "active_skills", [])),
        "skill_talents": dict(getattr(hero, "skill_talents", {})),
        "skill_runes": {sid: dict(slots) for sid, slots
                        in getattr(hero, "skill_runes", {}).items()},
        # v5: Skills V2 (Gem Souls) state — unlocked/loadout/priority/sxp/
        # talents/keystones/awakened/tomes_read. Plain JSON-safe dict.
        "skills_v2": dict(getattr(hero, "skills_v2", {})),
        "base_stats": dict(vars(hero.base_stats)),
        "equipment": {
            slot: (item_to_dict(it) if it else None) for slot, it in hero.equipment.items()
        },
        "inventory": [item_to_dict(it) for it in hero.inventory],
        "stash": [item_to_dict(it) for it in hero.stash],
        # E.1/E.2 econ 2.0 (additive at SAVE_VERSION 5). idle_upgrades: {id:lvl};
        # stash_tabs_owned: int (>=1). Sanitized on load by their own modules.
        "idle_upgrades": dict(getattr(hero, "idle_upgrades", {})),
        "stash_tabs_owned": int(getattr(hero, "stash_tabs_owned", 1)),
    }


def _clean_stats(raw: dict) -> dict:
    """Keep only keys that are real Stats fields. Saves written before a stat was
    removed from the engine (e.g. the retired `mana`) still carry it; passing it
    to Stats(**...) would raise TypeError and abort the whole load. Dropping
    unknown keys lets such saves load cleanly (forward/backward compatible)."""
    valid = {f.name for f in dataclass_fields(Stats)}
    return {k: v for k, v in dict(raw).items() if k in valid}


def hero_from_dict(d: dict) -> Hero:
    base = Stats(**_clean_stats(d["base_stats"]))
    hero = Hero(
        name=d["name"],
        stats=base.copy(),
        class_id=d["class_id"],
        level=d["level"],
        xp=d["xp"],
        gold=d["gold"],
        base_stats=base,
        equipment={
            slot: (item_from_dict(it) if it else None)
            for slot, it in d.get("equipment", {}).items()
        },
        inventory=[item_from_dict(it) for it in d.get("inventory", [])],
        stash=[item_from_dict(it) for it in d.get("stash", [])],
    )
    # v1 saves have no "passives" key -> default []; passive_mods stays empty
    # until the tree module rebuilds it from these ids.
    # v2 saves carry ids from the old 54-node tree: tree.rebuild() drops unknown
    # ids, so the points refund themselves (points_available = level-1+bonus-spent).
    hero.passives = list(d.get("passives", []))
    hero.bonus_points = int(d.get("bonus_points", 0))
    # S.4 rework: Class Points sources (act-boss ids). Missing on pre-rework saves.
    hero.class_point_sources = list(d.get("class_point_sources", []))
    hero.active_skills = list(d.get("active_skills", []))
    hero.skill_talents = dict(d.get("skill_talents", {}))
    # v4: per-skill socketed passives. Drop unknown passive ids (data may change).
    from game.combat_math import load_socket_passives
    known = set(load_socket_passives())
    runes: dict[str, dict[str, str]] = {}
    for sid, slots in d.get("skill_runes", {}).items():
        kept = {k: v for k, v in dict(slots).items() if v in known}
        if kept:
            runes[sid] = kept
    hero.skill_runes = runes
    # v5: Skills V2 block. No migration from v4 skill choices (test characters
    # per user directive) — ensure_skills_v2 seeds/repairs it from the hero's
    # class+level, so a missing or stale block just becomes the v2 default.
    hero.skills_v2 = dict(d.get("skills_v2", {}))
    # S.4 rework: the v1 keystone prototype stored picks in skills_v2["keystones"].
    # That system is gone (class keystones now live in the passive tree) — drop the
    # stale key so old saves load cleanly instead of carrying dead state.
    hero.skills_v2.pop("keystones", None)
    from game.skills_v2 import ensure_skills_v2
    ensure_skills_v2(hero)
    # E.1/E.2 econ 2.0: sanitize through the owning modules. Old saves lack both
    # keys -> idle_upgrades {} and stash_tabs_owned 1 (their sanitizers default).
    from game import idle_upgrades as _iu, stash_tabs as _st
    hero.idle_upgrades = _iu.sanitize(d.get("idle_upgrades"))
    hero.stash_tabs_owned = _st.sanitize_owned(d.get("stash_tabs_owned"))
    hero.recalc()
    hero.max_hp = hero.stats.life
    hero.hp = hero.max_hp
    return hero


def save_game(path: str, hero: Hero, meta: dict) -> None:
    data = {
        "version": SAVE_VERSION,
        "saved_at": time.time(),
        "hero": hero_to_dict(hero),
        "meta": dict(meta),
    }
    dirname = os.path.dirname(os.path.abspath(path))
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        # Flush to disk before the rename: after a power cut / BSOD NTFS can keep
        # the rename but not the data, leaving an empty or garbled save.
        f.flush()
        os.fsync(f.fileno())
    _replace_with_retry(tmp, path)


def _replace_with_retry(src: str, dst: str, attempts: int = 5, delay: float = 0.05) -> None:
    """os.replace with a short retry. On Windows antivirus, the search indexer or
    cloud sync (OneDrive) briefly lock a freshly written file and the rename fails
    with PermissionError (WinError 5/32); a moment later it succeeds."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay * (i + 1))


def load_game(path: str) -> tuple[Hero, dict] | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        hero = hero_from_dict(data["hero"])
        _migrate_affixes(hero)
        meta = dict(data.get("meta", {}))
        meta["saved_at"] = data.get("saved_at", time.time())
        meta["version"] = data.get("version", 1)
        return hero, meta
    except Exception as e:
        print(f"[save] warning: failed to load '{path}': {e}")
        return None


def _migrate_affixes(hero: Hero) -> None:
    """v3 affix pool migration: drop affixes whose id left the pool (old v2
    stun/block/ailment-chance families). Unique specials (tier 0) are kept —
    they never lived in the pool. Items keep base/implicit/name untouched."""
    try:
        from game.item_roller import POOL
    except Exception:
        return
    known = {a["id"] for a in POOL}
    changed = False
    for it in [*hero.inventory, *hero.stash,
               *(i for i in hero.equipment.values() if i)]:
        kept = [a for a in it.affixes if a.tier == 0 or a.id in known]
        if len(kept) != len(it.affixes):
            it.affixes = kept
            changed = True
        # cube step 1 §6.5: a corrupted over-limit line whose affix id has left
        # the live pool is silently dropped (never crash). Uniques' tier-0 fixed
        # lines never live in the pool, so keep them.
        clines = getattr(it, "corrupted_lines", None)
        if clines:
            ckept = [a for a in clines if a.tier == 0 or a.id in known]
            if len(ckept) != len(clines):
                it.corrupted_lines = ckept
                changed = True
    if changed:
        hero.recalc()


def _offline_effective_seconds(elapsed: float) -> float:
    """Integrate OFFLINE_TIERS efficiency over `elapsed` seconds and return the
    equivalent number of full-rate online seconds. Each tier's efficiency applies
    only to the slice of away-time inside that tier's window; beyond the last
    boundary the rate is 0 (no reward for being gone longer than 72h)."""
    eff = 0.0
    prev = 0.0
    for boundary, rate in OFFLINE_TIERS:
        if elapsed <= prev:
            break
        slice_len = min(elapsed, boundary) - prev
        eff += slice_len * rate
        prev = boundary
    return eff


def offline_progress(saved_at: float, hero: Hero, kills_per_hour_estimate: float = 120.0,
                     zone_id: str | None = None,
                     rng: random.Random | None = None,
                     rate_snapshot: dict | None = None) -> dict:
    """Simulate an away-session as a reduced-efficiency catch-up (Stage 6.1.4).

    Away-gain is derived from the hero's OWN recent online rates, not re-derived
    from zone math (that re-derivation is where the old ×600 gold bug lived).
    `rate_snapshot` carries rolling online rates persisted every 60s:
        {"xp_per_sec", "gold_per_sec", "kills_per_sec"}.
    When absent (legacy saves / first session) we fall back to a conservative
    estimate from the save's zone so old saves still behave sanely.

    Effective online-equivalent seconds = integral of the tiered efficiency curve
    over elapsed away-time (see _offline_effective_seconds). XP is returned RAW —
    the caller feeds it through grant_xp, which applies xp_gain_inc EXACTLY ONCE
    (M1 fix). There is NO level cap: idle progress is the whole point, and the
    tiered efficiency already keeps offline strictly worse than online.

    Pure function: nothing on the hero is mutated — the caller applies the
    returned gold/xp/items itself.
    """
    from game import loot, world
    from game.economy import item_value

    elapsed = max(0.0, time.time() - saved_at)
    eff_sec = _offline_effective_seconds(elapsed)
    # E.1 up_offline: multiply the tiered offline efficiency by the permanent
    # idle-upgrade bonus (1.0..1.20). Scaling eff_sec == scaling every tier factor.
    ups = getattr(hero, "idle_upgrades", None)
    if ups:
        from game import idle_upgrades as _iu
        eff_sec *= _iu.offline_efficiency_mult(ups)
    hours = elapsed / 3600.0

    # --- rates: prefer the persisted online snapshot, else zone-based fallback ---
    if rate_snapshot and rate_snapshot.get("xp_per_sec"):
        xp_per_sec = max(0.0, rate_snapshot.get("xp_per_sec", 0.0))
        gold_per_sec = max(0.0, rate_snapshot.get("gold_per_sec", 0.0))
        kills_per_sec = max(0.0, rate_snapshot.get("kills_per_sec", 0.0))
    else:
        # Conservative fallback from the save's zone (clamped to the unlock rule).
        mlvl: int | None = None
        if zone_id:
            try:
                mlvl = min(world.get_zone(zone_id).monster_level, hero.level + 2)
            except KeyError:
                mlvl = None
        eff_mlvl = mlvl if mlvl is not None else max(1, hero.level)
        kills_per_sec = kills_per_hour_estimate / 3600.0
        xp_per_kill = max(1, int(world.XP_BASE * (1.0 + world.XP_GROWTH * (eff_mlvl - 1))))
        xp_per_sec = kills_per_sec * xp_per_kill
        # M4c: the online path (loot.roll_gold) multiplies by gold_find; the
        # snapshot captures it, but this zone-based fallback must apply it too or
        # old saves without a snapshot silently lose all gold_find offline.
        gold_find = 0.0
        s0 = getattr(hero, "stats", None)
        if s0 is not None:
            gold_find = getattr(s0, "gold_find", 0.0)
        gold_per_sec = kills_per_sec * (2.5 + 2.0 * eff_mlvl) * (1 + gold_find / 100.0)

    kills = int(kills_per_sec * eff_sec)
    xp = int(xp_per_sec * eff_sec)           # RAW xp; grant_xp multiplies later
    gold = int(gold_per_sec * eff_sec)

    # levels_gained is a display estimate — compute on the FINAL amount grant_xp
    # will award (single xp_gain_inc multiplication), so the flash matches reality.
    mult = 1.0
    s = getattr(hero, "stats", None)
    if s is not None and getattr(s, "xp_gain_inc", 0):
        mult *= 1 + s.xp_gain_inc / 100.0
    if "timeworn" in getattr(hero, "flags", set()):
        mult *= 0.9
    from game import progression
    final_xp = int(xp * mult)
    total_xp = hero.xp + final_xp
    level = hero.level
    # Stage 6.6: leveling is uncapped offline too (bounded only by earned xp).
    cap = progression.LEVEL_CAP
    while (cap is None or level < cap) and \
            total_xp >= progression.xp_to_level(level + 1):
        level += 1
    levels_gained = level - hero.level

    # --- items: no flood. magic+ kept (cap OFFLINE_ITEMS_KEEP), normals -> gold ---
    r = rng if rng is not None else random.Random()
    eff_mlvl_items = max(1, min(hero.level, hero.level + 2))
    if zone_id:
        try:
            eff_mlvl_items = min(world.get_zone(zone_id).monster_level, hero.level + 2)
        except KeyError:
            pass
    n_rolls = min(OFFLINE_ITEM_ROLLS_CAP, int(kills * loot.DROP_CHANCE))
    rolled = [loot.make_item(eff_mlvl_items, r, class_id=hero.class_id or None)
              for _ in range(n_rolls)]
    # keep magic+ (anything above normal on the ladder); scrap+normal auto-salvage.
    _JUNK = (Rarity.SCRAP, Rarity.NORMAL)
    keepers = [it for it in rolled if it.rarity not in _JUNK]
    salvage = [it for it in rolled if it.rarity in _JUNK]
    keepers.sort(key=lambda it: (_RARITY_ORDER[it.rarity], -it.ilvl))
    items = keepers[:OFFLINE_ITEMS_KEEP]
    gold += sum(item_value(it) for it in salvage + keepers[OFFLINE_ITEMS_KEEP:])

    return {
        "hours": hours,
        "gold": gold,
        "xp": xp,
        "levels_gained": levels_gained,
        "items": items,
        "kills": kills,
    }


if __name__ == "__main__":
    sword = Item(
        base_id="long_sword",
        base_name="Long Sword",
        slot=Slot.WEAPON,
        rarity=Rarity.RARE,
        ilvl=12,
        req_level=8,
        name="Fatal Long Sword of Fury",
        class_req=("warrior",),
        implicit=[StatMod("damage_min", flat=6), StatMod("damage_max", flat=14)],
        affixes=[
            Affix("phys_inc_t3", "Fatal", True, 3, [StatMod("damage_max", inc=40)]),
            Affix("attack_speed_t2", "of Fury", False, 2, [StatMod("attack_speed", inc=12)]),
        ],
    )
    ring = Item(
        base_id="iron_ring",
        base_name="Iron Ring",
        slot=Slot.RING,
        rarity=Rarity.MAGIC,
        ilvl=5,
        name="Ruby Iron Ring",
        implicit=[StatMod("damage_min", flat=1)],
        affixes=[Affix("fire_res_t5", "Ruby", True, 5, [StatMod("res_fire", flat=15)])],
    )
    spare = Item(
        base_id="leather_cap",
        base_name="Leather Cap",
        slot=Slot.HELMET,
        rarity=Rarity.NORMAL,
        ilvl=3,
    )

    hero = Hero(name="Tester", stats=Stats(), base_stats=Stats(life=80, damage_max=9))
    hero.level = 7
    hero.xp = 340
    hero.gold = 155
    hero.equipment = {Slot.WEAPON.value: sword, Slot.RING.value: ring, Slot.BODY.value: None}
    hero.inventory = [spare]
    hero.stash = [Item(base_id="broad_axe", base_name="Broad Axe", slot=Slot.WEAPON,
                       rarity=Rarity.NORMAL, ilvl=14, req_level=12,
                       class_req=("barbarian",))]
    hero.passives = ["iron_skin", "quick_reflexes"]
    hero.bonus_points = 6
    hero.recalc()
    hero.hp = hero.max_hp

    path = os.path.join(SAVE_DIR, "_test.json")
    save_game(path, hero, {"zone_id": "act1_coast", "difficulty_id": "normal", "kills": 42, "playtime": 123.4})

    loaded = load_game(path)
    assert loaded is not None
    h2, meta = loaded
    assert h2.level == hero.level and h2.gold == hero.gold and h2.xp == hero.xp
    assert h2.class_id == hero.class_id and h2.name == hero.name
    assert h2.passives == ["iron_skin", "quick_reflexes"]
    assert h2.bonus_points == 6
    # StatMod.more round-trips (and is omitted from dicts when 0)
    assert _mod_from_dict(_mod_to_dict(StatMod("life", more=25))).more == 25
    assert "more" not in _mod_to_dict(StatMod("life", flat=5))
    assert len(h2.inventory) == 1
    assert sum(1 for it in h2.equipment.values() if it) == 2
    w2 = h2.equipment[Slot.WEAPON.value]
    assert w2 is not None and w2.rarity is Rarity.RARE and w2.slot is Slot.WEAPON
    assert len(w2.affixes) == 2 and len(w2.implicit) == 2
    assert w2.affixes[0].mods[0].inc == 40 and w2.implicit[0].flat == 6
    assert len(w2.all_mods()) == len(sword.all_mods())
    # class_req round-trips; unrestricted items keep ()
    assert w2.class_req == ("warrior",), w2.class_req
    assert h2.inventory[0].class_req == ()
    # stash round-trips and does not leak into stats
    assert len(h2.stash) == 1 and h2.stash[0].class_req == ("barbarian",)
    assert h2.stash[0].base_id == "broad_axe"
    assert h2.stats.life == hero.stats.life and h2.hp == h2.max_hp
    assert meta["kills"] == 42 and meta["version"] == SAVE_VERSION and "saved_at" in meta

    # backward compat: version-1 save (no "passives" key) must load with passives=[];
    # pre-class_req/stash saves get class_req=() and stash=[]
    with open(path, "r", encoding="utf-8") as f:
        v1_data = json.load(f)
    v1_data["version"] = 1
    del v1_data["hero"]["passives"]
    del v1_data["hero"]["stash"]
    del v1_data["hero"]["equipment"]["weapon"]["class_req"]
    v1_path = os.path.join(SAVE_DIR, "_test_v1.json")
    with open(v1_path, "w", encoding="utf-8") as f:
        json.dump(v1_data, f, ensure_ascii=False)
    loaded_v1 = load_game(v1_path)
    assert loaded_v1 is not None
    h1, meta1 = loaded_v1
    assert h1.passives == [] and meta1["version"] == 1
    assert h1.level == hero.level and len(h1.inventory) == 1
    assert h1.stash == []
    assert h1.equipment[Slot.WEAPON.value].class_req == ()

    # --- offline progress v3 (Stage 6.1.4): tiered efficiency, no level cap,
    # snapshot-driven rates, magic+ items kept / normals salvaged to gold ---
    from game import progression as _prog
    snap = {"xp_per_sec": 5.0, "gold_per_sec": 3.0, "kills_per_sec": 0.3}
    off = offline_progress(meta["saved_at"] - 3 * 3600, h2, zone_id="a1_caves",
                           rng=random.Random(42), rate_snapshot=snap)
    assert 2.9 < off["hours"] <= 3.1 and off["gold"] > 0 and off["xp"] > 0
    assert off["kills"] > 0
    # 3h fully inside tier 1 (0.60): eff seconds = 3h*0.60. xp = xp_per_sec*eff.
    eff1 = _offline_effective_seconds(3 * 3600)
    assert abs(eff1 - 3 * 3600 * 0.60) < 1.0, eff1
    assert off["xp"] == int(snap["xp_per_sec"] * eff1), (off["xp"], eff1)
    assert off["kills"] == int(snap["kills_per_sec"] * eff1)
    # items: magic+ only, capped, sorted by rarity (ilvl tie-break)
    assert len(off["items"]) <= OFFLINE_ITEMS_KEEP
    for it in off["items"]:
        assert it.rarity in (Rarity.MAGIC, Rarity.RARE, Rarity.UNIQUE), it.rarity
    keys = [(_RARITY_ORDER[it.rarity], -it.ilvl) for it in off["items"]]
    assert keys == sorted(keys), keys
    for it in off["items"]:
        rt = item_from_dict(item_to_dict(it))
        assert rt.rarity is it.rarity and rt.ilvl == it.ilvl and rt.base_id == it.base_id

    # tiered efficiency: 100h away caps at 72h of accrual, and the tiers make
    # the effective online-equivalent time strictly less than 24h of full rate.
    eff_100 = _offline_effective_seconds(100 * 3600)
    eff_expected = (8 * 3600 * 0.60) + (16 * 3600 * 0.35) + (48 * 3600 * 0.15)
    assert abs(eff_100 - eff_expected) < 1.0, (eff_100, eff_expected)
    # 24h offline effective ≈ (8*0.6 + 16*0.35) = 10.4h of full-rate online.
    eff_24 = _offline_effective_seconds(24 * 3600)
    assert abs(eff_24 - (8 * 3600 * 0.60 + 16 * 3600 * 0.35)) < 1.0
    online_24 = 24 * 3600
    ratio = eff_24 / online_24
    assert 0.40 <= ratio <= 0.55, ratio  # gate 6.1: 24h offline ≈ 45–55% of online

    # legacy save (no snapshot): zone fallback still yields sane positive gains
    off_nz = offline_progress(meta["saved_at"] - 3 * 3600, h2, zone_id="a1_caves",
                              rng=random.Random(44))
    assert off_nz["gold"] > 0 and off_nz["xp"] > 0 and off_nz["kills"] > 0

    # --- M1 regression: xp_gain_inc applied EXACTLY once (in grant_xp) ---
    # offline_progress returns RAW xp; grant_xp multiplies. levels_gained must
    # match what grant_xp actually awards after that single multiplication.
    import copy
    from game.core import CombatEvent
    hboost = copy.deepcopy(h2)
    hboost.base_stats.xp_gain_inc = 200.0
    hboost.level = 5
    hboost.xp = _prog.xp_to_level(5)
    hboost.recalc()
    assert hboost.stats.xp_gain_inc == 200.0
    off_b = offline_progress(meta["saved_at"] - 8 * 3600, hboost, zone_id="a1_caves",
                             rng=random.Random(46), rate_snapshot=snap)
    ev: list[CombatEvent] = []
    lvl_before = hboost.level
    _prog.grant_xp(hboost, off_b["xp"], ev)  # single multiplication, as _apply_offline does
    assert off_b["levels_gained"] == hboost.level - lvl_before, \
        (off_b["levels_gained"], hboost.level - lvl_before)
    # M1: online 12h at +200% == offline-equivalent 12h at +200% within 1%.
    # Feed the same RAW xp both ways; grant_xp is the single multiply point.
    raw_xp = 100000
    ha = copy.deepcopy(hboost); ha.xp = 0; ha.level = 5; ha.recalc()
    hb = copy.deepcopy(hboost); hb.xp = 0; hb.level = 5; hb.recalc()
    _prog.grant_xp(ha, raw_xp, [])
    _prog.grant_xp(hb, raw_xp, [])
    assert ha.level == hb.level and ha.xp == hb.xp, "xp_gain_inc must be single-source"
    # ~zero elapsed -> empty report
    off_zero = offline_progress(meta["saved_at"], h2, rng=random.Random(45),
                                rate_snapshot=snap)
    assert off_zero["kills"] == 0 and off_zero["items"] == [] and off_zero["xp"] == 0

    assert load_game(os.path.join(SAVE_DIR, "_missing.json")) is None

    os.remove(path)
    os.remove(v1_path)
    print("save OK")
