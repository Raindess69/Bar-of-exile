"""Update icon map.json to use new icon folders."""
import json
from pathlib import Path

ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons"
MAP_PATH = ICONS_DIR / "map.json"

# Map base_id to (folder, icon_index)
# Tier 1 items use low indices, tier 2 mid, tier 3 high
ICON_MAP = {
    # Swords (warrior)
    "rusted_sword": ("sword", 0),
    "long_sword": ("sword", 5),
    "vaal_blade": ("sword", 10),
    # Bows (archer)
    "crude_bow": ("bow", 0),
    "hunter_bow": ("bow", 6),
    "imperial_bow": ("bow", 12),
    # Staves (mage)
    "gnarled_staff": ("staff", 0),
    "runic_staff": ("staff", 5),
    "vaal_staff": ("staff", 10),
    # Axes (barbarian)
    "rusted_axe": ("axe", 0),
    "broad_axe": ("axe", 5),
    "vaal_axe": ("axe", 10),
    # Maces (cleric)
    "worn_cudgel": ("mace", 0),
    "war_mace": ("mace", 5),
    "vaal_sceptre": ("mace", 10),
    # Helmets
    "leather_cap": ("helmet", 15),
    "chain_coif": ("helmet", 25),
    "great_helm": ("helmet", 40),
    # Body armor
    "leather_vest": ("armor", 14),  # light armor
    "scale_mail": ("armor", 30),    # medium
    "plate_mail": ("armor", 50),    # heavy
    # Gloves
    "leather_gloves": ("gloves_new", 0),
    "chain_gloves": ("gloves_new", 8),
    "plate_gauntlets": ("gloves_new", 16),
    # Boots
    "leather_boots": ("boots", 0),
    "chain_boots": ("boots", 32),
    "plate_greaves": ("boots", 64),
    # Belts (use existing)
    "rope_belt": ("belts", 0),
    "studded_belt": ("belts", 1),
    "heavy_belt": ("belts", 2),
    # Amulets (use existing)
    "bone_amulet": ("gems", 0),
    "jade_amulet": ("gems", 1),
    "onyx_amulet": ("gems", 2),
    # Rings (use existing)
    "coral_ring": ("rings", 0),
    "azure_ring": ("rings", 1),
    "ruby_ring": ("rings", 2),
}

def main():
    new_map = {}

    for base_id, (folder, idx) in ICON_MAP.items():
        # Check if it's a numbered icon or legacy folder
        if folder in ("sword", "bow", "staff", "axe", "mace", "helmet", "armor", "boots"):
            icon_path = f"{folder}/{folder}_{idx:02d}.png"
        elif folder == "gloves_new":
            # Special case: files are named gloves_XX.png not gloves_new_XX.png
            icon_path = f"{folder}/gloves_{idx:02d}.png"
        else:
            # Legacy folders (belts, gems, rings)
            icon_path = f"{folder}/{idx}.png"

        # Verify file exists
        full_path = ICONS_DIR / icon_path
        if full_path.exists():
            new_map[base_id] = icon_path
            print(f"✓ {base_id:20s} -> {icon_path}")
        else:
            print(f"✗ {base_id:20s} -> {icon_path} (NOT FOUND)")

    # Write updated map
    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(new_map, f, indent=1, sort_keys=True)

    print(f"\nWrote {len(new_map)}/36 mappings to {MAP_PATH}")

if __name__ == "__main__":
    main()
