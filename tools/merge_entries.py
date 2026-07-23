#!/usr/bin/env python
"""Merge assets/sprites/_entries/*.json into assets/sprites/manifest.json.

Each entry {"walk": [...], "attack": [...], "h": N} replaces the manifest
record for its id wholesale. Verifies every referenced file exists; an entry
with missing files is SKIPPED with a loud warning (manifest keeps old record).

Usage: python tools/merge_entries.py [--dry]
"""
import argparse
import json
from pathlib import Path

SPRITES = Path(__file__).resolve().parent.parent / "assets" / "sprites"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    manifest_path = SPRITES / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    entries = sorted((SPRITES / "_entries").glob("*.json"))
    if not entries:
        print("no _entries to merge")
        return
    merged, skipped = [], []
    for ep in entries:
        sid = ep.stem
        try:
            entry = json.loads(ep.read_text("utf-8"))
        except ValueError as e:
            skipped.append((sid, f"bad json: {e}"))
            continue
        files = list(entry.get("walk", [])) + list(entry.get("attack", []))
        if not entry.get("walk"):
            skipped.append((sid, "no walk frames"))
            continue
        missing = [f for f in files if not (SPRITES / sid / f).is_file()]
        if missing:
            skipped.append((sid, f"missing files: {missing[:4]}{'...' if len(missing) > 4 else ''}"))
            continue
        old = manifest.get(sid)
        manifest[sid] = entry
        merged.append(sid)
        ow = len(old.get("walk", [])) if old else 0
        oa = len(old.get("attack", [])) if old else 0
        print(f"[+] {sid}: walk {ow}->{len(entry['walk'])}, "
              f"attack {oa}->{len(entry.get('attack', []))}, h={entry.get('h')}")
    for sid, why in skipped:
        print(f"[!] SKIP {sid}: {why}")
    if args.dry:
        print("dry run, manifest untouched")
        return
    if merged:
        manifest_path.write_text(json.dumps(manifest, indent=1), "utf-8")
        print(f"manifest.json updated: {', '.join(merged)}")


if __name__ == "__main__":
    main()
