"""Slice each STL at several heights and count separate printed regions.

v0.1 failed because the first layer broke into 18 isolated islands. v0.4 uses
independent posts on purpose, so above the rim the expected count is 4 per slot
(20 for the full module). This script verifies the counts match the design
instead of assuming "1 everywhere".

It also measures the area of downward-facing horizontal faces above the plate:
any such face means material was printed over empty space. v0.4 had 360 mm2 of
these at the post feet; they must stay at zero. v0.6's integral tenon starts
at z=0 for exactly this reason.

Usage: python check_layers.py
"""
from __future__ import annotations

import math
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
STL_DIR = os.path.join(ROOT, "stl")

# name: [(z, expected body count), ...]
# z values are offset from facet planes to avoid degenerate sections.
LAYERS = {
    "v0_fit_test.stl": [
        (0.5, 1), (3.0, 1), (10.0, 1), (16.0, 4), (25.0, 4), (39.0, 4),
    ],
    "module_5slot.stl": [
        (0.5, 1), (10.0, 1), (16.0, 20), (25.0, 20), (39.0, 20),
    ],
    # One print yields two separate coupons (female + male).
    "joint_fit_test.stl": [
        (0.5, 2), (3.0, 2), (8.0, 2), (14.0, 2),
    ],
}

# Preview-only seated assembly: the two coupons touch face-to-face, so a
# cross-section merges their outlines and layer counting is meaningless.
# build.py verifies it via additive volume + watertightness instead; here
# only the unsupported-face check applies.
OVERHANG_ONLY = ["joint_pair_demo.stl"]


def load(fn: str) -> list[tuple[float, float, float]]:
    text = open(fn, encoding="utf-8", errors="replace").read()
    verts = re.findall(
        r"vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", text)
    return [tuple(map(float, v)) for v in verts]


def section(verts, z0: float):
    segs = []
    for i in range(0, len(verts), 3):
        tri = verts[i:i + 3]
        pts = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            p, q = tri[a], tri[b]
            if (p[2] - z0) * (q[2] - z0) < 0:
                t = (z0 - p[2]) / (q[2] - p[2])
                pts.append((round(p[0] + t * (q[0] - p[0]), 3),
                            round(p[1] + t * (q[1] - p[1]), 3)))
        unique = []
        for p in pts:
            if p not in unique:
                unique.append(p)
        if len(unique) == 2:
            segs.append((unique[0], unique[1]))
    return segs


def loops(segs):
    adj = defaultdict(list)
    unused = set()
    for a, b in segs:
        adj[a].append(b)
        adj[b].append(a)
        unused.add((a, b))
        unused.add((b, a))
    out = []
    while unused:
        s, n = next(iter(unused))
        loop = [s]
        cur, nxt = s, n
        for _ in range(100000):
            unused.discard((cur, nxt))
            unused.discard((nxt, cur))
            loop.append(nxt)
            cand = [x for x in adj[nxt] if x != cur and (nxt, x) in unused]
            if not cand:
                break
            n2 = cand[0]
            cur, nxt = nxt, n2
            if nxt == s:
                unused.discard((cur, nxt))
                unused.discard((nxt, cur))
                break
        out.append(loop)
    return out


def inside(pt, poly) -> bool:
    x, y = pt
    hit = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x1 + (y - y1) * (x2 - x1) / (y2 - y1) > x:
                hit = not hit
    return hit


def outer_count(rings) -> int:
    """Loops nested inside another loop are holes, not separate bodies."""
    return sum(1 for i, r in enumerate(rings)
               if not any(inside(r[0], o) for j, o in enumerate(rings) if j != i))


def unsupported_area(path: str) -> float:
    """Area of downward-facing horizontal faces above the build plate.

    Such a face means material was printed over empty space. The bottom face
    at z=0 is excluded: it rests on the plate.
    """
    text = open(path, encoding="utf-8", errors="replace").read()
    num = r"[+-]?\d*\.?\d+(?:[eE][+-]?\d+)?"
    total = 0.0
    for chunk in text.split("facet normal ")[1:]:
        lines = chunk.strip().splitlines()
        n = [float(x) for x in re.findall(num, lines[0])][:3]
        v = [[float(x) for x in re.findall(num, l)]
             for l in lines if l.strip().startswith("vertex")]
        if len(v) < 3 or len(n) < 3 or n[2] >= -0.9:
            continue
        if sum(p[2] for p in v) / 3 <= 0.5:
            continue
        u = [v[1][i] - v[0][i] for i in range(3)]
        w = [v[2][i] - v[0][i] for i in range(3)]
        cr = [u[1]*w[2]-u[2]*w[1], u[2]*w[0]-u[0]*w[2],
              u[0]*w[1]-u[1]*w[0]]
        total += 0.5 * math.sqrt(sum(q*q for q in cr))
    return total


def post_widths(path: str) -> list[float]:
    """Width of every upright post, read from the highest flat top faces.

    v0.6 clipped the two rightmost posts from 5 mm down to 2 mm because
    END_MARGIN_R was smaller than the post thickness. Instead of hardcoding
    a target width, assert all posts are the SAME width: that catches any
    future margin/post clash without tying this script to a parameter.
    """
    text = open(path, encoding="utf-8", errors="replace").read()
    num = r"[+-]?\d*\.?\d+(?:[eE][+-]?\d+)?"
    faces: list[tuple[float, float]] = []
    for chunk in text.split("facet normal ")[1:]:
        lines = chunk.strip().splitlines()
        n = [float(x) for x in re.findall(num, lines[0])][:3]
        v = [[float(x) for x in re.findall(num, l)]
             for l in lines if l.strip().startswith("vertex")]
        if len(v) < 3 or len(n) < 3 or n[2] < 0.9:
            continue
        z = round(sum(p[2] for p in v) / 3, 2)
        for p in v:
            faces.append((z, round(p[0], 2)))
    if not faces:
        return []
    ztop = max(z for z, _ in faces)
    xs = {x for z, x in faces if abs(z - ztop) < 0.02}
    groups: list[list[float]] = []
    for x in sorted(xs):
        if not groups or x - groups[-1][-1] > 8:
            groups.append([x])
        else:
            groups[-1].append(x)
    return [g[-1] - g[0] for g in groups]


def main() -> int:
    bad = 0
    for name, checks in LAYERS.items():
        path = os.path.join(STL_DIR, name)
        if not os.path.isfile(path):
            print("  %-22s MISSING" % name)
            bad += 1
            continue
        verts = load(path)
        cells = []
        for z, expected in checks:
            rs = loops(section(verts, z))
            if not rs:
                cells.append("z=%g:空层(期望%d)" % (z, expected))
                bad += 1
                continue
            n = outer_count(rs)
            flag = "" if n == expected else " != %d" % expected
            if flag:
                bad += 1
            cells.append("z=%g:%d体/%d环%s" % (z, n, len(rs), flag))
        print("  %-22s %s" % (name, "  ".join(cells)))
    print("\n  Unsupported horizontal faces (z > 0.5 mm):")
    for name in list(LAYERS) + OVERHANG_ONLY:
        path = os.path.join(STL_DIR, name)
        if not os.path.isfile(path):
            continue
        area = unsupported_area(path)
        if area >= 0.01:
            bad += 1
        print("  %-22s %-4s %8.2f mm2" %
              (name, "OK" if area < 0.01 else "FAIL", area))
    print("\n  Upright post widths (highest flat top faces):")
    for name in ("module_5slot.stl", "v0_fit_test.stl"):
        path = os.path.join(STL_DIR, name)
        if not os.path.isfile(path):
            continue
        w = post_widths(path)
        if not w:
            print("  %-22s FAIL no post top faces found" % name)
            bad += 1
            continue
        spread = max(w) - min(w)
        ok = spread < 0.05
        if not ok:
            bad += 1
        print("  %-22s %-4s %d groups  min %.2f / max %.2f mm" %
              (name, "OK" if ok else "FAIL", len(w), min(w), max(w)))
    print("\n  %s" % ("PASS - layers, overhangs and post widths match the design"
                      if bad == 0 else "FAIL - %d check(s) off target" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
