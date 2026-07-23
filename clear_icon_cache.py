"""Clear icon cache - run this if items show 'M' instead of icons."""
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from ui import panels

print(f"Icon cache has {len(panels._icon_pixmaps)} entries")
if panels._icon_pixmaps:
    print("Sample cached items:")
    for i, (base_id, pm) in enumerate(list(panels._icon_pixmaps.items())[:10]):
        print(f"  {base_id}: {'OK' if pm else 'NONE (missing icon)'}")

    none_count = sum(1 for pm in panels._icon_pixmaps.values() if pm is None)
    print(f"\nTotal with None: {none_count}/{len(panels._icon_pixmaps)}")

panels._icon_pixmaps.clear()
print("\n✓ Icon cache cleared. Restart the game.")
