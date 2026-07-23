"""v3.1 guard, rewritten for audit M6: every stat id in data/affixes_v2.json and
data/passives_v2.json must resolve to a Stats field that some engine system
actually READS — not merely a field that exists.

The old version only checked that a stat mapped onto *some* existing Stats field.
That passes for a field nothing consumes, which is exactly how `evasion` shipped
inert for so long (the field existed; no code rolled it). Grabля №10: a stat/flag
without a consumer is silently dead. This test now fails unless the field name
appears as an attribute read (`.field`) somewhere in the engine sources — so a
new stat that maps to a never-read field fails here instead of dying quietly.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import statmap
from game.core import Stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_stats() -> set[str]:
    with open(os.path.join(ROOT, "data", "affixes_v2.json"), encoding="utf-8") as f:
        affixes = json.load(f)["affixes"]
    stats = {a["stat"] for a in affixes}
    with open(os.path.join(ROOT, "data", "passives_v2.json"), encoding="utf-8") as f:
        tree = json.load(f)
    for n in tree.get("nodes", []):
        stats.update((n.get("stats") or {}).keys())
    return stats


# Every engine source a stat could legitimately be consumed in. combat_math.py
# added in 2b (shared damage/leech/crit/evasion helpers now live there).
_CONSUMER_FILES = [
    os.path.join("game", n) for n in (
        "combat.py", "combat_math.py", "skills.py", "skills_v2.py",
        "loot.py", "progression.py", "ailments.py", "core.py",
    )
] + ["main.py"]


def _read_sources() -> str:
    src = ""
    for rel in _CONSUMER_FILES:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            src += f.read()
    return src


# Fields consumed generically inside the apply_mods / mitigation core loop and
# the base life/damage/attack math — these are "read" structurally even though a
# textual `.field` grep in a high-level system may miss them. Kept deliberately
# small; anything outside this set MUST show an explicit consumer read.
_CORE_READ = {
    "life", "damage_min", "damage_max", "attack_speed", "move_speed",
    "armor", "res_fire", "res_cold", "res_lightning", "res_chaos",
    "crit_chance", "crit_multi",  # rolled in crit_mult / _monster_strike
}


def main() -> None:
    stats = _data_stats()
    src = _read_sources()
    all_fields = set(vars(Stats()).keys())

    # 1) every data stat must map onto real Stats fields (no phantom targets)
    phantom = []
    mapped: set[str] = set()
    for stat in sorted(stats):
        if statmap.is_pair_stat(stat):
            fields = [m.stat for m in statmap.mods_for_pair(stat, 1, 2)]
        else:
            fields = [m.stat for m in statmap.mods_for(stat, 1)]
        for f in fields:
            if f not in all_fields:
                phantom.append((stat, f))
            else:
                mapped.add(f)
    assert not phantom, f"stats mapping to non-existent Stats fields: {phantom}"

    # 2) every mapped field must actually be READ by engine code (audit M6):
    #    core-loop fields are exempt, the rest need an explicit `.field` read.
    read_re = {f: re.compile(r"\.%s\b" % re.escape(f)) for f in mapped}
    inert = [f for f in sorted(mapped)
             if f not in _CORE_READ and not read_re[f].search(src)]
    assert not inert, (
        "mapped Stats fields with NO consumer read in engine code "
        f"(grabля №10 — inert stat): {inert}")

    print(f"stat coverage OK: {len(stats)} data stats -> {len(mapped)} fields, "
          "all consumed")


if __name__ == "__main__":
    main()
