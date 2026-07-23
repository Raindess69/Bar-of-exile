"""Convert new mob anim.json format to manifest.json entries."""
import json
from pathlib import Path

SPRITES_DIR = Path(__file__).parent.parent / "assets" / "sprites"
MANIFEST_PATH = SPRITES_DIR / "manifest.json"

def convert_mob_to_manifest_entry(mob_dir: Path) -> dict | None:
    """Read anim.json and generate manifest entry."""
    anim_path = mob_dir / "anim.json"
    if not anim_path.exists():
        return None

    try:
        with open(anim_path, encoding="utf-8") as f:
            anim = json.load(f)
    except (OSError, ValueError):
        return None

    entry = {}

    # Walk animation
    if "walk" in anim:
        walk_dir = mob_dir / "walk"
        if walk_dir.exists():
            frames = sorted(walk_dir.glob("*.png"))
            entry["walk"] = [f"walk/{f.name}" for f in frames]

    # Attack animation
    if "attack" in anim:
        attack_dir = mob_dir / "attack"
        if attack_dir.exists():
            frames = sorted(attack_dir.glob("*.png"))
            entry["attack"] = [f"attack/{f.name}" for f in frames]

    # In-game render height. Do NOT derive size from the source sheet's pixel
    # dimensions (the old `frame_h*render_scale*0.15` made a human bandit smaller
    # than a zombie — see tools/_resize_mobs.py). New mobs default to the HUMAN
    # rung of the semantic ladder; re-tier them by editing tools/_resize_mobs.py's
    # TIER table and running it (it clamps upscale to avoid blur).
    if "walk" in anim:
        entry["h"] = 42  # HUMAN rung; retier via tools/_resize_mobs.py

    return entry if entry else None

def main():
    # Load existing manifest
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    print(f"Loaded manifest with {len(manifest)} entries")

    # Find all new mob directories (those with anim.json but not in manifest)
    new_mobs = []
    for mob_dir in sorted(SPRITES_DIR.iterdir()):
        if not mob_dir.is_dir():
            continue
        if mob_dir.name.startswith("_"):
            continue
        if mob_dir.name in manifest:
            continue  # already in manifest

        anim_json = mob_dir / "anim.json"
        if anim_json.exists():
            new_mobs.append(mob_dir)

    print(f"Found {len(new_mobs)} new mobs to convert")

    # Convert each new mob
    added = 0
    for mob_dir in new_mobs:
        entry = convert_mob_to_manifest_entry(mob_dir)
        if entry:
            manifest[mob_dir.name] = entry
            added += 1
            print(f"  + {mob_dir.name}: {len(entry.get('walk', []))} walk, "
                  f"{len(entry.get('attack', []))} attack, h={entry.get('h')}")
        else:
            print(f"  ! {mob_dir.name}: conversion failed")

    # Write updated manifest
    if added > 0:
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1)
        print(f"\nUpdated manifest.json: +{added} mobs, total {len(manifest)} entries")
    else:
        print("\nNo mobs added")

if __name__ == "__main__":
    main()
