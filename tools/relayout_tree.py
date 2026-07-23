"""Relayout the 1001-node passive tree: uniform disk («шар») instead of the old
Fable star-spiral. 5 class wedges of exactly 200 nodes, guaranteed node spacing,
edges rewired globally so neighboring wedges connect along the whole border.
One-shot: python tools/relayout_tree.py  (run from project root)."""
from __future__ import annotations

import json
import math
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "passives.json")
PREVIEW = os.path.join(ROOT, "docs", "tree_preview.png")

R_MAX = 1800.0
R_MIN = 170.0          # hole around the start node
TARGET_D = 90.0        # min node spacing to relax towards
RELAX_ITERS = 120
KNN = 6
LOOP_MAX = 140.0       # extra loop edges up to this length
DEG_CAP = 4
MIN_CROSS_PER_BORDER = 3

random.seed(20260715)


def load():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- layout
def vogel_points(n: int) -> list[list[float]]:
    ga = math.pi * (3 - math.sqrt(5))
    pts = []
    for k in range(1, n + 1):
        r = math.sqrt(R_MIN ** 2 + (R_MAX ** 2 - R_MIN ** 2) * k / n)
        th = k * ga
        pts.append([r * math.cos(th), r * math.sin(th)])
    return pts


def relax(pts: list[list[float]]) -> float:
    """Push apart pairs closer than TARGET_D; clamp to the annulus. Returns min dist."""
    cell = TARGET_D
    mind = 0.0
    for _ in range(RELAX_ITERS):
        grid: dict[tuple[int, int], list[int]] = {}
        for i, (x, y) in enumerate(pts):
            grid.setdefault((int(x // cell), int(y // cell)), []).append(i)
        mind = float("inf")
        moved = False
        for (cx, cy), idxs in grid.items():
            cand: list[int] = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cand += grid.get((cx + dx, cy + dy), [])
            for i in idxs:
                for j in cand:
                    if j <= i:
                        continue
                    dx = pts[j][0] - pts[i][0]
                    dy = pts[j][1] - pts[i][1]
                    d = math.hypot(dx, dy) or 1e-6
                    mind = min(mind, d)
                    if d < TARGET_D:
                        push = (TARGET_D - d) / 2 / d
                        pts[i][0] -= dx * push
                        pts[i][1] -= dy * push
                        pts[j][0] += dx * push
                        pts[j][1] += dy * push
                        moved = True
        for p in pts:
            r = math.hypot(p[0], p[1]) or 1e-6
            rr = min(R_MAX, max(R_MIN, r))
            if rr != r:
                p[0] *= rr / r
                p[1] *= rr / r
        if not moved:
            break
    return mind


# ---------------------------------------------------------------- wedges
def circular_mean(angles: list[float]) -> float:
    return math.atan2(sum(math.sin(a) for a in angles) / len(angles),
                      sum(math.cos(a) for a in angles) / len(angles))


def assign_wedges(data: dict, pts: list[list[float]]) -> dict[str, list[int]]:
    """Split points into 5 contiguous arcs of exactly 200, one per branch,
    keeping each branch roughly where its old star arm pointed."""
    branches = data["meta"]["branches"]
    axes = {}
    for br in branches:
        angs = [math.atan2(n["y"], n["x"]) for n in data["nodes"] if n.get("branch") == br]
        axes[br] = circular_mean(angs)
    order = sorted(branches, key=lambda b: axes[b])
    # first boundary: midpoint between last and first axis (wrapping)
    a_last, a_first = axes[order[-1]], axes[order[0]]
    boundary = a_last + ((a_first - a_last) % (2 * math.pi)) / 2
    idx = sorted(range(len(pts)),
                 key=lambda i: (math.atan2(pts[i][1], pts[i][0]) - boundary) % (2 * math.pi))
    per = len(pts) // len(branches)
    return {br: idx[k * per:(k + 1) * per] for k, br in enumerate(order)}


def place_branch(nodes: list[dict], point_ids: list[int], pts: list[list[float]]) -> None:
    """Rank-match: deeper (old radius) node -> farther point. Keeps progression."""
    nodes_by_depth = sorted(nodes, key=lambda n: math.hypot(n["x"], n["y"]))
    pids_by_r = sorted(point_ids, key=lambda i: math.hypot(pts[i][0], pts[i][1]))
    for n, pid in zip(nodes_by_depth, pids_by_r):
        n["x"], n["y"] = round(pts[pid][0], 2), round(pts[pid][1], 2)


def snug_keystones(data: dict) -> None:
    """Swap each keystone into the free spot nearest its paired notable
    (keystones must hang 1 edge behind a notable — keep that edge short)."""
    by_branch: dict[str, list[dict]] = {}
    for n in data["nodes"]:
        if n.get("branch"):
            by_branch.setdefault(n["branch"], []).append(n)
    for br, nodes in by_branch.items():
        notables = [n for n in nodes if n["type"] == "notable"]
        smalls = [n for n in nodes if n["type"] == "small"]
        used = set()
        for ks in [n for n in nodes if n["type"] == "keystone"]:
            r_ks = math.hypot(ks["x"], ks["y"])
            nb = min((n for n in notables if n["id"] not in used),
                     key=lambda n: abs(math.hypot(n["x"], n["y"]) - r_ks))
            used.add(nb["id"])
            sm = min(smalls, key=lambda s: math.hypot(s["x"] - nb["x"], s["y"] - nb["y"]))
            ks["x"], sm["x"] = sm["x"], ks["x"]
            ks["y"], sm["y"] = sm["y"], ks["y"]


# ---------------------------------------------------------------- edges
class DSU:
    def __init__(self, ids):
        self.p = {i: i for i in ids}

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.p[ra] = rb
        return True


def rewire(data: dict) -> list[list]:
    nodes = {n["id"]: n for n in data["nodes"]}
    pos = {i: (n["x"], n["y"]) for i, n in nodes.items()}

    def dist(a, b):
        return math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])

    trunk = [i for i, n in nodes.items() if n["type"] not in ("keystone",)]
    # kNN candidates over trunk (global: cross-branch pairs included)
    cand: set[tuple[str, str]] = set()
    cell = 200.0
    grid: dict[tuple[int, int], list[str]] = {}
    for i in trunk:
        grid.setdefault((int(pos[i][0] // cell), int(pos[i][1] // cell)), []).append(i)
    for i in trunk:
        cx, cy = int(pos[i][0] // cell), int(pos[i][1] // cell)
        near: list[str] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                near += grid.get((cx + dx, cy + dy), [])
        for j in sorted((j for j in near if j != i), key=lambda j: dist(i, j))[:KNN]:
            cand.add((i, j) if i < j else (j, i))

    ranked = sorted(cand, key=lambda e: dist(*e))
    dsu = DSU(trunk)
    edges: list[tuple[str, str]] = []
    deg: dict[str, int] = {i: 0 for i in nodes}
    for a, b in ranked:
        if dsu.union(a, b):
            edges.append((a, b))
            deg[a] += 1
            deg[b] += 1
    # stitch any leftover components (kNN graph may be disconnected)
    comps: dict[str, list[str]] = {}
    for i in trunk:
        comps.setdefault(dsu.find(i), []).append(i)
    while len(comps) > 1:
        groups = list(comps.values())
        base = max(groups, key=len)
        best = None
        for g in groups:
            if g is base:
                continue
            for a in g:
                for b in base:
                    d = dist(a, b)
                    if best is None or d < best[0]:
                        best = (d, a, b)
        _, a, b = best
        dsu.union(a, b)
        edges.append((a, b))
        deg[a] += 1
        deg[b] += 1
        comps = {}
        for i in trunk:
            comps.setdefault(dsu.find(i), []).append(i)

    have = {frozenset(e) for e in edges}
    # short loop edges: redundancy + natural cross-branch stitching, capped degree
    for a, b in ranked:
        if frozenset((a, b)) in have or dist(a, b) > LOOP_MAX:
            continue
        if deg[a] >= DEG_CAP or deg[b] >= DEG_CAP:
            continue
        edges.append((a, b))
        have.add(frozenset((a, b)))
        deg[a] += 1
        deg[b] += 1

    # keystones: exactly one edge, to the nearest notable
    for i, n in nodes.items():
        if n["type"] != "keystone":
            continue
        nb = min((j for j, m in nodes.items() if m["type"] == "notable"),
                 key=lambda j: dist(i, j))
        edges.append((i, nb))
        deg[i] += 1
        deg[nb] += 1

    # start: one spoke into each branch
    for br in data["meta"]["branches"]:
        nearest = min((i for i, n in nodes.items()
                       if n.get("branch") == br and n["type"] == "small"),
                      key=lambda i: dist("start", i))
        if frozenset(("start", nearest)) not in have:
            edges.append(("start", nearest))
            have.add(frozenset(("start", nearest)))
            deg["start"] += 1
            deg[nearest] += 1

    # guarantee every wedge border is stitched at several radii
    order = sorted(data["meta"]["branches"],
                   key=lambda br: circular_mean(
                       [math.atan2(n["y"], n["x"]) for n in data["nodes"]
                        if n.get("branch") == br]))
    for k, br in enumerate(order):
        nxt = order[(k + 1) % len(order)]
        cross = [e for e in edges
                 if {nodes[e[0]].get("branch"), nodes[e[1]].get("branch")} == {br, nxt}]
        if len(cross) >= MIN_CROSS_PER_BORDER:
            continue
        pairs = sorted(
            ((dist(a, b), a, b)
             for a in trunk if nodes[a].get("branch") == br
             for b in trunk if nodes[b].get("branch") == nxt),
            key=lambda t: t[0])
        for d, a, b in pairs:
            if len(cross) >= MIN_CROSS_PER_BORDER:
                break
            if frozenset((a, b)) in have:
                continue
            edges.append((a, b))
            have.add(frozenset((a, b)))
            cross.append((a, b))
            deg[a] += 1
            deg[b] += 1
    return [list(e) for e in edges]


# ---------------------------------------------------------------- checks
def verify(data: dict) -> dict:
    nodes = {n["id"]: n for n in data["nodes"]}
    adj: dict[str, set[str]] = {i: set() for i in nodes}
    lens = []
    for a, b in data["edges"]:
        adj[a].add(b)
        adj[b].add(a)
        lens.append(math.hypot(nodes[a]["x"] - nodes[b]["x"], nodes[a]["y"] - nodes[b]["y"]))
    seen, stack = {"start"}, ["start"]
    while stack:
        for nb in adj[stack.pop()]:
            if nb not in seen:
                seen.add(nb)
                stack.append(nb)
    assert len(seen) == len(nodes), f"disconnected: {len(seen)}/{len(nodes)}"
    for i, n in nodes.items():
        if n["type"] == "keystone":
            assert len(adj[i]) == 1, f"{i}: {len(adj[i])} edges"
            (nb,) = adj[i]
            assert nodes[nb]["type"] == "notable", f"{i} not behind a notable"
    cross = sum(1 for a, b in data["edges"]
                if nodes[a].get("branch") and nodes[b].get("branch")
                and nodes[a]["branch"] != nodes[b]["branch"])
    lens.sort()
    return {"edges": len(lens), "max_len": round(lens[-1], 1),
            "median_len": round(lens[len(lens) // 2], 1), "cross_branch": cross}


def min_spacing(data: dict) -> float:
    pts = [(n["x"], n["y"]) for n in data["nodes"]]
    cell = 100.0
    grid: dict[tuple[int, int], list[int]] = {}
    for i, (x, y) in enumerate(pts):
        grid.setdefault((int(x // cell), int(y // cell)), []).append(i)
    mind = float("inf")
    for (cx, cy), idxs in grid.items():
        cand = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cand += grid.get((cx + dx, cy + dy), [])
        for i in idxs:
            for j in cand:
                if j > i:
                    mind = min(mind, math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]))
    return mind


# ---------------------------------------------------------------- preview
def render_preview(data: dict) -> None:
    from PIL import Image, ImageDraw
    size = 1600
    sc = size / (2 * (R_MAX + 60))
    def to_px(x, y):
        return x * sc + size / 2, y * sc + size / 2
    colors = {"warrior": (200, 75, 75), "barbarian": (210, 132, 47),
              "archer": (75, 171, 90), "mage": (75, 116, 200), "cleric": (200, 180, 75)}
    img = Image.new("RGB", (size, size), (16, 14, 20))
    d = ImageDraw.Draw(img)
    nodes = {n["id"]: n for n in data["nodes"]}
    for a, b in data["edges"]:
        na, nb = nodes[a], nodes[b]
        col = (150, 150, 170) if na.get("branch") != nb.get("branch") else (70, 66, 80)
        d.line([*to_px(na["x"], na["y"]), *to_px(nb["x"], nb["y"])], fill=col, width=1)
    for n in data["nodes"]:
        x, y = to_px(n["x"], n["y"])
        r = {"start": 14, "small": 3, "notable": 6, "keystone": 9}[n["type"]]
        col = colors.get(n.get("branch"), (240, 240, 240))
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
        if n["type"] == "keystone":
            d.ellipse([x - r - 2, y - r - 2, x + r + 2, y + r + 2], outline=(255, 255, 255), width=2)
    img.save(PREVIEW)


def main() -> None:
    data = load()
    non_start = [n for n in data["nodes"] if n["type"] != "start"]
    pts = vogel_points(len(non_start))
    mind = relax(pts)
    print(f"relaxed: min point dist {mind:.1f}wu (target {TARGET_D})")

    wedges = assign_wedges(data, pts)
    for br, pids in wedges.items():
        place_branch([n for n in non_start if n["branch"] == br], pids, pts)
    start = next(n for n in data["nodes"] if n["type"] == "start")
    start["x"] = start["y"] = 0.0
    snug_keystones(data)

    data["edges"] = rewire(data)
    stats = verify(data)
    spacing = round(min_spacing(data), 1)
    data["meta"]["edge_count"] = stats["edges"]
    data["meta"]["layout"] = {
        "kind": "uniform_disk_v4",
        "disk_radius": R_MAX, "inner_radius": R_MIN,
        "min_node_spacing": spacing,
        "cluster_radii": [R_MAX * k / 5 for k in range(1, 6)],
        "wedges": "5 contiguous 200-node arcs, rank-matched by old radius (progression kept)",
    }
    data["meta"]["edges_rewired"] = ("uniform disk relayout + global MST/kNN rewire "
                                     "(star spiral with node overlaps replaced)")
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    render_preview(data)
    print(f"spacing {spacing}wu | {stats} | preview -> {PREVIEW}")


if __name__ == "__main__":
    main()
