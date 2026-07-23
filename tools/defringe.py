#!/usr/bin/env python3
"""defringe.py — remove white/light halo pixels around cut sprites (in place).

Usage:
    python defringe.py <dir> [--white 185] [--sat 40] [--ring 2] [--dry]

Walks <dir> recursively, processes every frame_*.png / icon_*.png (RGBA).
Only touches a thin ring at the sprite edge, so bright pixels inside the
sprite body are safe. Overwrites files; keeps a .bak only with --bak.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image


def defringe_img(im: Image.Image, white: int, sat: int, ring: int):
    arr = np.array(im.convert("RGBA"), dtype=np.int16)
    rgb, alpha = arr[..., :3], arr[..., 3]
    solid = alpha > 0
    if not solid.any():
        return None, 0
    # erode `ring` times -> inner core; ring mask = solid minus core
    core = solid.copy()
    for _ in range(ring):
        e = core.copy()
        e[1:, :] &= core[:-1, :]
        e[:-1, :] &= core[1:, :]
        e[:, 1:] &= core[:, :-1]
        e[:, :-1] &= core[:, 1:]
        core = e
    edge = solid & ~core
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    # whitish = bright and low-saturation (white/light-gray JPEG halo)
    whitish = (mn > white) & ((mx - mn) < sat)
    # also kill semi-transparent light pixels on the edge (soft halo)
    soft = (alpha < 255) & (mn > white - 30)
    kill = edge & (whitish | soft)
    n = int(kill.sum())
    if n == 0:
        return None, 0
    alpha[kill] = 0
    arr[..., 3] = alpha
    return Image.fromarray(arr.astype(np.uint8)), n


PREFIXES = ("frame_", "icon_", "walk_", "atk_", "attack_")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--white", type=int, default=185)
    ap.add_argument("--sat", type=int, default=40)
    ap.add_argument("--ring", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--bak", action="store_true")
    a = ap.parse_args()
    files = touched = killed = 0
    for dp, _, fns in os.walk(a.root):
        for fn in fns:
            if not fn.lower().endswith(".png"):
                continue
            if not fn.startswith(PREFIXES):
                continue
            p = os.path.join(dp, fn)
            try:
                im = Image.open(p)
            except Exception as e:
                print(f"[!] {p}: {e}", file=sys.stderr)
                continue
            files += 1
            out, n = defringe_img(im, a.white, a.sat, a.ring)
            if out is None:
                continue
            touched += 1
            killed += n
            if not a.dry:
                if a.bak:
                    os.replace(p, p + ".bak")
                out.save(p)
    print(f"scanned {files} png, cleaned {touched}, removed {killed} halo px"
          + (" (dry run)" if a.dry else ""))


if __name__ == "__main__":
    main()
