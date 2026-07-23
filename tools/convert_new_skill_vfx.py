#!/usr/bin/env python
"""Convert pre-cut skill VFX frames from `new assets/<id>/` into game vfx.

The `new assets` pack has, per skill, a folder with <id>_NN.png frames (RGBA,
large ~1000px canvas) + anim.json ({frames, frame_ms, loop, canvas}). Game vfx
live in assets/vfx/skill_<id>/frame_NN.png + a manifest.json record
{skill_<id>: {frames, fps}} and are tiny (target height ~56 for skill effects,
~20 for projectiles). Conversion is mechanical:

  1. union alpha bbox across ALL frames (same crop box -> zero jitter),
  2. downscale ONCE to target height (LANCZOS, these are AI art not true
     pixel art so LANCZOS beats NEAREST on big downscales),
  3. write assets/vfx/skill_<id>/frame_NN.png,
  4. update assets/vfx/manifest.json {skill_<id>: {frames, fps}},
  5. QA montage in assets/vfx/_tmp_new/<id>_montage.png.

fps derived from anim.json frame_ms (1000/frame_ms), clamped [8,20], default 14.

Usage:
  python tools/convert_new_skill_vfx.py <id> [<id> ...] --h 56 [--dry] [--backup]
  python tools/convert_new_skill_vfx.py --all-direct --h 56   # all name==skill_id
Nothing is deleted; --backup renames an existing target dir to <dir>.bak first.
"""
import argparse
import json
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
NEW = ROOT / "new assets"
VFX = ROOT / "assets" / "vfx"
TMP = VFX / "_tmp_new"


def union_bbox(frames: list[Image.Image]) -> tuple[int, int, int, int]:
    box = None
    for im in frames:
        a = im.getchannel("A")
        bb = a.getbbox()
        if bb is None:
            continue
        if box is None:
            box = list(bb)
        else:
            box[0] = min(box[0], bb[0])
            box[1] = min(box[1], bb[1])
            box[2] = max(box[2], bb[2])
            box[3] = max(box[3], bb[3])
    return tuple(box) if box else None


def convert(sid: str, target_h: int, dry: bool, backup: bool,
            effect_id: str | None = None) -> dict | None:
    src = NEW / sid
    aj = src / "anim.json"
    if not aj.exists():
        print(f"  !! {sid}: no anim.json, skip")
        return None
    meta = json.loads(aj.read_text("utf-8"))
    on_disk = {p.name for p in src.glob(f"{sid}_*.png")}
    listed = meta.get("frames") or sorted(on_disk)
    # keep anim.json order, but drop names that were never actually cut
    frame_names = [fn for fn in listed if fn in on_disk]
    dropped = [fn for fn in listed if fn not in on_disk]
    if dropped:
        print(f"     note {sid}: {len(dropped)} listed frame(s) missing on "
              f"disk, ignored: {', '.join(dropped)}")
    frames = [Image.open(src / fn).convert("RGBA") for fn in frame_names]
    if not frames:
        print(f"  !! {sid}: no frames, skip")
        return None

    bbox = union_bbox(frames)
    if bbox is None:
        print(f"  !! {sid}: all frames empty, skip")
        return None
    cropped = [im.crop(bbox) for im in frames]
    cw, ch = cropped[0].size
    scale = target_h / ch
    tw = max(1, round(cw * scale))
    resized = [im.resize((tw, target_h), Image.LANCZOS) for im in cropped]

    fps = 14
    fm = meta.get("frame_ms")
    if fm:
        fps = max(8, min(20, round(1000 / fm)))

    effect = f"skill_{effect_id or sid}"
    outdir = VFX / effect
    if outdir.exists() and backup and not dry:
        bak = VFX / (effect + ".bak")
        if bak.exists():
            shutil.rmtree(bak)
        shutil.move(str(outdir), str(bak))
        print(f"     backed up existing -> {bak.name}")
    if not dry:
        outdir.mkdir(parents=True, exist_ok=True)
        for old in outdir.glob("frame_*.png"):
            old.unlink()
        for i, im in enumerate(resized):
            im.save(outdir / f"frame_{i:02d}.png")
        # QA montage
        TMP.mkdir(parents=True, exist_ok=True)
        pad = 2
        mw = sum(im.width for im in resized) + pad * (len(resized) + 1)
        mont = Image.new("RGBA", (mw, target_h + 2 * pad), (30, 30, 30, 255))
        x = pad
        for im in resized:
            mont.alpha_composite(im, (x, pad))
            x += im.width + pad
        mont.save(TMP / f"{sid}_montage.png")

    print(f"  ok {sid}: {len(resized)} frames, {cw}x{ch}->{tw}x{target_h}, "
          f"fps={fps}{' [DRY]' if dry else ''}")
    return {"effect": effect, "frames": len(resized), "fps": fps,
            "src": src}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--h", type=int, default=56)
    ap.add_argument("--all-direct", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--backup", action="store_true")
    ap.add_argument("--cleanup", action="store_true",
                    help="delete the source `new assets/<id>/` folder after a "
                         "successful convert (frees the pack folder)")
    args = ap.parse_args()

    skills = {s["id"] for s in json.loads(
        (ROOT / "data" / "skills_v2.json").read_text("utf-8"))["skills"]}
    if args.all_direct:
        ids = sorted(d.name for d in NEW.iterdir()
                     if d.is_dir() and d.name in skills)
    else:
        ids = args.ids
    if not ids:
        print("no ids")
        return

    manifest_path = VFX / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    results = []
    for tok in ids:
        # token may be "folder" or "folder:skill_id" (map mismatched names)
        if ":" in tok:
            folder, eff = tok.split(":", 1)
        else:
            folder, eff = tok, None
        r = convert(folder, args.h, args.dry, args.backup, effect_id=eff)
        if r:
            results.append(r)
    if not args.dry:
        for r in results:
            manifest[r["effect"]] = {"frames": r["frames"], "fps": r["fps"]}
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
        print(f"\nmanifest updated: +{len(results)} entries")
        if args.cleanup:
            removed = 0
            for r in results:
                srcdir = r["src"]
                if srcdir.exists():
                    shutil.rmtree(srcdir)
                    removed += 1
            print(f"cleanup: removed {removed} source folder(s) from "
                  f"'{NEW.name}'")
    print(f"done: {len(results)} converted")


if __name__ == "__main__":
    main()
