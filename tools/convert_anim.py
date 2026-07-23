#!/usr/bin/env python
"""Convert pre-cut Fable anim frames (assets/anims/) into game assets.

The pack frames are RGBA on a unified per-anim canvas, feet aligned at the
bottom (VFX centered). Conversion is therefore purely mechanical: pick rows,
crop to the union alpha bbox (same box for every frame -> zero jitter),
scale ONCE per entity with NEAREST so the final canvas height == target h.

Usage:
  python tools/convert_anim.py sprite <id> --h 40 \
      --walk barb_main/row_00[:0-11] [--walk ...] \
      --attack barb_main/row_03[:0,1,2,4-6] [--mirror] [--wipe]

  python tools/convert_anim.py vfx <effect> --h 64 --fps 14 \
      --src pixel_art_vfx_sprite_sheet/row_00[:sel] [--wipe]

Source spec: <sheet>/<row>[:selector]. Selector = comma list of indices and
ranges over the row frames sorted by name ("0-3,5,8"); default = all.
Subfolder auto-picked: for --walk prefer walk/ else all/; --attack prefer
attack/ else all/; vfx --src prefers all/.

sprite: writes assets/sprites/<id>/walk_NN.png + atk_NN.png,
        assets/sprites/_entries/<id>.json, QA montage in
        assets/sprites/_tmp_conv/<id>_montage.png. manifest.json NOT touched
        (merge via tools/merge_entries.py).
vfx:    writes assets/vfx/<effect>/frame_NN.png, updates assets/vfx/
        manifest.json ({effect: {frames, fps}}), QA montage alongside.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ANIMS = ROOT / "assets" / "anims"
SPRITES = ROOT / "assets" / "sprites"
VFX = ROOT / "assets" / "vfx"


def parse_sel(sel: str | None, n: int) -> list[int]:
    if not sel:
        return list(range(n))
    out: list[int] = []
    for part in sel.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    bad = [i for i in out if i >= n]
    if bad:
        sys.exit(f"selector {sel}: indices {bad} out of range (row has {n})")
    return out


def load_source(spec: str, prefer: tuple[str, ...]) -> list[Image.Image]:
    """spec = <sheet>/<row>[:sel] -> list of RGBA frames."""
    path_part, _, sel = spec.partition(":")
    row_dir = ANIMS / path_part
    if not row_dir.is_dir():
        sys.exit(f"no such row dir: {row_dir}")
    sub = next((row_dir / s for s in prefer if (row_dir / s).is_dir()), None)
    if sub is None:
        sys.exit(f"{row_dir}: none of subfolders {prefer} exist "
                 f"(has: {[p.name for p in row_dir.iterdir() if p.is_dir()]})")
    files = sorted(sub.glob("frame_*.png"))
    if not files:
        sys.exit(f"{sub}: no frame_*.png")
    idx = parse_sel(sel, len(files))
    return [Image.open(files[i]).convert("RGBA") for i in idx]


def convert(frames: list[Image.Image], target_h: int,
            mirror: bool) -> list[Image.Image]:
    """Normalize frames that may come from rows with DIFFERENT canvases.

    Pack invariant: each frame's canvas has the figure anchored bottom-center
    (feet at canvas bottom, x-center = canvas w/2). We express every alpha
    bbox relative to that anchor, take the union across all frames, scale
    once (target_h / union height) and paste bottom-anchored — zero jitter
    even when mixing rows.
    """
    rel = []  # (im, bbox, dxl, dxr, dyt, dyb) relative to bottom-center
    L = T = 10**9
    R = B = -(10**9)
    for im in frames:
        bb = im.split()[3].getbbox()
        if not bb:
            continue
        l, t, r, b = bb
        cx, ch = im.width / 2, im.height
        dxl, dxr, dyt, dyb = l - cx, r - cx, t - ch, b - ch
        rel.append((im, bb, dxl, dyt))
        L, R = min(L, dxl), max(R, dxr)
        T, B = min(T, dyt), max(B, dyb)
    if not rel:
        sys.exit("all frames fully transparent?!")
    scale = target_h / (B - T)
    W = max(1, round((R - L) * scale))
    out = []
    for im, bb, dxl, dyt in rel:
        crop = im.crop(bb)
        sw = max(1, round(crop.width * scale))
        sh = max(1, round(crop.height * scale))
        crop = crop.resize((sw, sh), Image.NEAREST)
        canvas = Image.new("RGBA", (W, target_h), (0, 0, 0, 0))
        x = round((dxl - L) * scale)
        y = round((dyt - T) * scale)
        y = min(y, target_h - sh)  # rounding guard, keep feet inside
        canvas.paste(crop, (min(x, W - sw), max(0, y)), crop)
        if mirror:
            canvas = canvas.transpose(Image.FLIP_LEFT_RIGHT)
        out.append(canvas)
    return out


def montage(rows: list[list[Image.Image]], path: Path, scale: int = 2) -> None:
    rows = [r for r in rows if r]
    pad = 2
    fw = max(im.width for r in rows for im in r)
    fh = max(im.height for r in rows for im in r)
    cw, ch = fw * scale + pad, fh * scale + pad
    W = max(len(r) for r in rows) * cw + pad
    H = len(rows) * ch + pad
    canvas = Image.new("RGB", (W, H), (40, 42, 48))
    for ry, row in enumerate(rows):
        for cx, im in enumerate(row):
            big = im.resize((im.width * scale, im.height * scale),
                            Image.NEAREST)
            x = pad + cx * cw + (fw * scale - big.width) // 2
            y = pad + ry * ch + (fh * scale - big.height)  # feet aligned
            canvas.paste(big, (x, y), big)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def wipe_pngs(d: Path) -> int:
    n = 0
    if d.is_dir():
        for p in d.glob("*.png"):
            p.unlink()
            n += 1
    return n


def cmd_sprite(a) -> None:
    walk = [f for s in a.walk for f in load_source(s, ("walk", "all"))]
    attack = [f for s in a.attack for f in load_source(s, ("attack", "all"))]
    if not walk:
        sys.exit("sprite needs at least one --walk source")
    n_w = len(walk)
    both = convert(walk + attack, a.h, a.mirror)
    walk_c, atk_c = both[:n_w], both[n_w:]
    d = SPRITES / a.id
    d.mkdir(parents=True, exist_ok=True)
    if a.wipe:
        print(f"wiped {wipe_pngs(d)} old png")
    entry = {"walk": [], "attack": [], "h": a.h}
    for i, im in enumerate(walk_c):
        name = f"walk_{i:02d}.png"
        im.save(d / name)
        entry["walk"].append(name)
    for i, im in enumerate(atk_c):
        name = f"atk_{i:02d}.png"
        im.save(d / name)
        entry["attack"].append(name)
    if not entry["attack"]:
        del entry["attack"]
    ed = SPRITES / "_entries"
    ed.mkdir(exist_ok=True)
    (ed / f"{a.id}.json").write_text(json.dumps(entry, indent=1), "utf-8")
    mp = SPRITES / "_tmp_conv" / f"{a.id}_montage.png"
    montage([walk_c, atk_c], mp)
    cw = walk_c[0].size
    print(f"[{a.id}] walk {len(walk_c)} + atk {len(atk_c)} @ {cw[0]}x{cw[1]}"
          f"{' MIRRORED' if a.mirror else ''} -> {d}\n  QA: {mp}")


def cmd_vfx(a) -> None:
    frames = [f for s in a.src for f in load_source(s, ("all", "walk"))]
    conv = convert(frames, a.h, False)
    d = VFX / a.effect
    d.mkdir(parents=True, exist_ok=True)
    if a.wipe:
        print(f"wiped {wipe_pngs(d)} old png")
    for i, im in enumerate(conv):
        im.save(d / f"frame_{i:02d}.png")
    mpath = VFX / "manifest.json"
    try:
        man = json.loads(mpath.read_text("utf-8"))
    except (OSError, ValueError):
        man = {}
    man[a.effect] = {"frames": len(conv), "fps": a.fps}
    mpath.write_text(json.dumps(man, indent=1), "utf-8")
    mp = VFX / "_tmp_conv" / f"{a.effect}_montage.png"
    montage([conv], mp)
    print(f"[vfx {a.effect}] {len(conv)} frames @ h={a.h} fps={a.fps} -> {d}"
          f"\n  QA: {mp}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sprite")
    sp.add_argument("id")
    sp.add_argument("--h", type=int, default=40)
    sp.add_argument("--walk", action="append", default=[])
    sp.add_argument("--attack", action="append", default=[])
    sp.add_argument("--mirror", action="store_true")
    sp.add_argument("--wipe", action="store_true")
    sp.set_defaults(fn=cmd_sprite)
    vp = sub.add_parser("vfx")
    vp.add_argument("effect")
    vp.add_argument("--h", type=int, default=64)
    vp.add_argument("--fps", type=int, default=14)
    vp.add_argument("--src", action="append", required=True)
    vp.add_argument("--wipe", action="store_true")
    vp.set_defaults(fn=cmd_vfx)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
