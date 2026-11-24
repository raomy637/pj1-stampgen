"""Render the parametric SCAD into STL files and a self-contained 3D preview.

Usage:  python build.py
Output: stl/*.stl  +  preview.html
"""
from __future__ import annotations

import json
import math
import os
import re
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
OPENSCAD = r"D:\HA1\PJ1\OpenSCAD\openscad.exe"
SCAD = os.path.join(ROOT, "router_dock.scad")
STL_DIR = os.path.join(ROOT, "stl")
TEMPLATE = os.path.join(ROOT, "preview_template.html")
PREVIEW = os.path.join(ROOT, "preview.html")

# part_id, preview key, filename, extra -D overrides
PARTS = [
    (1, "v0",        "v0_fit_test.stl",     {}),
    (2, "module",    "module_5slot.stl",    {}),
    (4, "joint",     "joint_fit_test.stl",  {}),
    (5, "jointPair", "joint_pair_demo.stl", {}),
]

# ---- Bambu Lab P1S / Bambu Studio DEFAULT printable volume --------
# 256^3 is the toolhead's physical reach, NOT the default usable volume.
# Bambu Studio ships P1/X1 with a 250 mm printable height (headroom for
# Z-hop and bed clearance), and marks the left-front cutter block as an
# 18 x 28 mm non-printable area. Unlocking the full 256 mm needs a printed
# cutter-block mod, a chamber clean-out, and NO AMS filament changes.
# Source: wiki.bambulab.com/zh/knowledge-sharing/print-volume-limitations
BED_X = 256.0
BED_Y = 256.0
BED_Z = 250.0
CUTTER_ZONE = 28.0   # conservative: the larger of the 18 / 28 mm dimensions
BRIM = 0.0           # extra per-side margin; set >0 only if brim is required
# Engineering margin at the plate edge (clips, uneven heat, long-part warp).
# NOT an official limit - adjustable. With 5 mm, MW <= 251 mm, so GAP = 22
# is the largest integer slot gap that stays uniform AND printable.
BED_MIN_MARGIN = 5.0


def scad_params(text: str) -> dict[str, float]:
    """Read simple numeric assignments straight from the SCAD source."""
    out = {}
    for m in re.finditer(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*([0-9.]+)\s*;", text, re.M):
        out[m.group(1)] = float(m.group(2))
    return out


def derived(p: dict[str, float]) -> dict:
    solid = int(p["SOLID"])
    vent = int(p.get("VENT", 0))
    fence_on = int(p.get("FENCE_ON", 0))
    fence_mode = int(p.get("FENCE_MODE", 3))
    sw = p["SLOT_W"] + p.get("SLOT_W_ADD", 0) + 2 * p["CLEARANCE"]
    sl = p["SLOT_L"] + 2 * p["CLEARANCE"]
    pitch = sw + p["GAP"]
    n = int(p["N_SLOTS"])
    slots_w = n * sw + (n - 1) * p["GAP"]
    body_w = p["END_MARGIN"] + slots_w + p["END_MARGIN_R"]
    mw = body_w + p["T_DEPTH"]          # total envelope including the tenon
    md = 2 * p["Y_MARGIN"] + sl
    zbase = 0 if solid else p["FOOT_H"]
    zb = zbase + p["BASE_T"]
    zt = zb + p["SLOT_DEPTH"]
    zf = zt + (p.get("FENCE_H", 0) if fence_on else 0)
    # Solid at the seam between the last slot of A and the first slot of B.
    # This equals M_L + M_R regardless of GAP, so setting M_L + M_R = GAP
    # makes the seam exactly as wide as every internal cooling channel.
    seam = p["END_MARGIN_R"] + p["END_MARGIN"]
    return {
        "sw": sw, "sl": sl, "pitch": pitch, "mw": mw, "body_w": body_w,
        "md": md, "z0": zbase, "zb": zb, "zt": zt, "zf": zf,
        "seam": seam,
        "uniform": abs(seam - p["GAP"]) < 1e-6,
        "post_ok": p["END_MARGIN_R"] >= p["FENCE_T"],
        "pocket_ok": p["END_MARGIN"] >= p["T_DEPTH"] + 2,
        "solid": solid, "vent": vent,
        "fence_on": fence_on, "fence_mode": fence_mode,
        "fence_t": p["FENCE_T"], "fence_h": p["FENCE_H"],
        "fence_l": p["FENCE_L"], "fence_end": p["FENCE_END"],
        "n_posts": n * 4,
        "v0w": 2 * p["END_MARGIN"] + sw + p["GAP"],
        "slot_depth": p["SLOT_DEPTH"], "gap": p["GAP"],
        "n_slots": n, "end_margin": p["END_MARGIN"],
        "end_margin_r": p["END_MARGIN_R"],
        "y_margin": p["Y_MARGIN"], "base_t": p["BASE_T"],
        "foot_h": 0 if solid else p["FOOT_H"], "clearance": p["CLEARANCE"],
        "slot_w_add": p.get("SLOT_W_ADD", 0),
        "router_show": p["ROUTER_SHOW"],
        "joint_lock": int(p.get("JOINT_LOCK", 1)),
        "t_depth": p["T_DEPTH"], "neck_x": p["T_NECK_X"],
        "neck_w": p["T_NECK_W"], "head_w": p["T_HEAD_W"],
        "joint_gap": p["JOINT_GAP"],
        "tenon_reach": p["T_DEPTH"] - p["JOINT_GAP"],
        "jt_x": p.get("JT_X", 10), "jt_y": p.get("JT_Y", 28),
        "jt_gap_y": p.get("JT_GAP_Y", 5), "jt_h": zt,
        "corner_r": p["CORNER_R"], "chamfer": p["CHAMFER"],
        "bed_x": BED_X, "bed_y": BED_Y, "bed_z": BED_Z,
        "bed_margin_x": BED_X - mw, "bed_margin_y": BED_Y - md,
        "bed_margin_z": BED_Z - zf,
        "bed_y_center": (BED_Y - md) / 2,
        "bed_brim": BRIM, "bed_cutter_zone": CUTTER_ZONE,
        "bed_min_margin": BED_MIN_MARGIN,
        "bed_ok": (mw + 2 * BRIM <= BED_X - BED_MIN_MARGIN
                   and md + 2 * BRIM <= BED_Y
                   and zf <= BED_Z and (BED_Y - md) / 2 >= CUTTER_ZONE),
    }


def render(part_id: int, filename: str, extra: dict | None = None) -> str:
    out = os.path.join(STL_DIR, filename)
    cmd = [OPENSCAD, "-o", out, "-D", "PART_ID=%d" % part_id]
    for key, value in (extra or {}).items():
        cmd += ["-D", "%s=%s" % (key, value)]
    cmd.append(SCAD)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if res.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError("OpenSCAD failed for %s\n%s\n%s" %
                           (filename, res.stdout[-1500:], res.stderr[-1500:]))
    return out


def _normal_from_vertices(t: list[float]) -> list[float]:
    ux, uy, uz = t[3] - t[0], t[4] - t[1], t[5] - t[2]
    vx, vy, vz = t[6] - t[0], t[7] - t[1], t[8] - t[2]
    n = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx]
    length = math.sqrt(sum(q * q for q in n)) or 1.0
    return [q / length for q in n]


def read_stl(path: str) -> list[list[float]]:
    data = open(path, "rb").read()
    tris: list[list[float]] = []
    if len(data) >= 84 and not data.lstrip().startswith(b"solid"):
        count = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * count <= len(data):
            for i in range(count):
                v = struct.unpack_from("<12fH", data, 84 + 50 * i)
                tris.append([round(q, 4) for q in v[3:12]] +
                            [round(q, 4) for q in v[0:3]])
        else:
            raise RuntimeError("truncated binary STL: " + path)
    else:
        text = data.decode("utf-8", "replace")
        verts = re.findall(r"vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", text)
        norms = re.findall(r"facet\s+normal\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", text)
        for i in range(len(verts) // 3):
            t = [float(q) for chunk in verts[3 * i:3 * i + 3] for q in chunk]
            n = [float(q) for q in norms[i]] if i < len(norms) else [0, 0, 0]
            tris.append([round(q, 4) for q in t] + [round(q, 4) for q in n])
    for t in tris:
        if math.sqrt(sum(q * q for q in t[9:12])) < 0.5:
            t[9:12] = [round(q, 4) for q in _normal_from_vertices(t)]
    return tris


def validate(tris: list[list[float]], name: str) -> float:
    """Watertightness + signed volume check; returns the absolute volume."""
    edges: dict[tuple, int] = {}
    vol = 0.0
    for t in tris:
        v = [(t[0], t[1], t[2]), (t[3], t[4], t[5]), (t[6], t[7], t[8])]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            e = tuple(sorted((v[a], v[b])))
            edges[e] = edges.get(e, 0) + 1
        a, b, c = v
        vol += (a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
    boundary = sum(1 for c in edges.values() if c == 1)
    nonmanifold = sum(1 for c in edges.values() if c > 2)
    status = "OK" if boundary == 0 and nonmanifold == 0 else "CHECK"
    print("  %-22s %-5s boundary %3d  nonmanifold %3d  %9.1f mm3" %
          (name, status, boundary, nonmanifold, abs(vol)))
    return abs(vol)


def main() -> int:
    os.makedirs(STL_DIR, exist_ok=True)
    src = open(SCAD, encoding="utf-8").read()
    meta = derived(scad_params(src))
    mode = "SOLID" if meta["solid"] else "GRATED"
    print("module: body %.1f + tenon %.1f = %.1f mm  |  %.1f x %.1f mm  %s / VENT=%d" %
          (meta["body_w"], meta["t_depth"], meta["mw"],
           meta["md"], meta["zf"], mode, meta["vent"]))
    print("slot:   %.1f x %.1f mm  (width +%.1f)  pitch %.1f  P1S bed margin %.1f mm" %
          (meta["sw"], meta["sl"], meta["slot_w_add"], meta["pitch"],
           256 - meta["mw"]))
    print("posts:  %d pcs  %.1f x %.1f mm  H=%.1f mm above rim" %
          (meta["n_posts"], meta["fence_t"], meta["fence_l"], meta["fence_h"]))
    print("joint:  integral %s  female deep %.1f / male reach %.1f mm  gap %.1f mm  seam %.1f mm" %
          ("T-lock" if meta["joint_lock"] else "rect", meta["t_depth"],
           meta["tenon_reach"], meta["joint_gap"], meta["seam"]))
    print("pitch:  internal %.1f / seam %.1f mm  uniform=%s  right wall %.1f mm  left wall %.1f mm" %
          (meta["pitch"] - meta["sw"], meta["seam"], meta["uniform"],
           meta["end_margin_r"], meta["end_margin"]))
    print("bed:    P1S default %.0f x %.0f x %.0f mm  margin X %.1f / Y %.1f / Z %.1f mm  "
          "min-X-margin %.1f mm  centered-Y %.1f mm  brim %.1f mm  -> %s" %
          (BED_X, BED_Y, BED_Z, meta["bed_margin_x"], meta["bed_margin_y"],
           meta["bed_margin_z"], BED_MIN_MARGIN, meta["bed_y_center"], BRIM,
           "PASS" if meta["bed_ok"] else "FAIL"))

    # Regression guards: uniform seam, unclipped posts, intact female pocket,
    # and a module that fits the P1S DEFAULT printable volume (not the 256 mm
    # hardware extreme, which needs a mod and disables AMS).
    if not meta["uniform"]:
        raise RuntimeError("seam %.1f != GAP %.1f: slot pitch will not be uniform"
                           % (meta["seam"], meta["gap"]))
    if not meta["post_ok"]:
        raise RuntimeError("END_MARGIN_R %.1f < FENCE_T %.1f: right posts will be clipped"
                           % (meta["end_margin_r"], meta["fence_t"]))
    if not meta["pocket_ok"]:
        raise RuntimeError("END_MARGIN %.1f < T_DEPTH+2: female pocket cuts slot 1"
                           % meta["end_margin"])
    if not meta["bed_ok"]:
        raise RuntimeError(
            "module does not fit the P1S DEFAULT printable volume safely: "
            "X %.1f + 2*brim %.1f needs %.0f mm margin / %.0f, Y %.1f / %.0f, "
            "Z %.1f / %.0f, centered Y start %.1f vs cutter zone %.0f mm. "
            "Do not rely on the 256 mm 'extreme build volume' mod "
            "(hardware change, no AMS)." %
            (meta["mw"], BRIM, BED_MIN_MARGIN, BED_X, meta["md"], BED_Y,
             meta["zf"], BED_Z, meta["bed_y_center"], CUTTER_ZONE))

    models = {}
    vols = {}
    for part_id, part, filename, extra in PARTS:
        path = render(part_id, filename, extra)
        tris = read_stl(path)
        models[part] = tris
        print("  %-22s %6d triangles  %7.1f KB" %
              (filename, len(tris), os.path.getsize(path) / 1024))
        vols[part] = validate(tris, filename)

    core = [len(models[k]) for k in ("v0", "module", "joint")]
    if len(set(core)) != 3:
        raise RuntimeError("PART_ID switch did not take effect: %s" % core)

    # The assembled demo contains the very same two coupons as the fit-test
    # STL, only relocated. Equal triangle count and additive volume prove
    # the male tenon does not intersect the female pocket.
    if len(models["jointPair"]) != len(models["joint"]):
        raise RuntimeError("joint demo is not composed of the same two coupons: %d vs %d"
                           % (len(models["jointPair"]), len(models["joint"])))
    v_pair, v_joint = vols["jointPair"], vols["joint"]
    if abs(v_pair - v_joint) > 1.0:
        raise RuntimeError(
            "male tenon interferes with the female pocket: pair %.1f vs test %.1f mm3"
            % (v_pair, v_joint))
    print("  joint fit:       assembled %.1f mm3 = fit-test %.1f mm3  ->  no interference"
          % (v_pair, v_joint))

    tpl = open(TEMPLATE, encoding="utf-8").read()
    html = (tpl.replace("/*__META__*/", json.dumps(meta, separators=(",", ":")))
               .replace("/*__GEOMETRY__*/", json.dumps(models, separators=(",", ":"))))
    open(PREVIEW, "w", encoding="utf-8").write(html)
    print("  preview.html       %7.1f KB" % (os.path.getsize(PREVIEW) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
