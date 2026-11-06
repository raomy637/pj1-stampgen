"""按模型高度（Z 轴尺寸）把 STL 分组到同名文件夹。

用法:
    python tools/organize_by_height.py <目标目录> [--tol 0.01] [--dry-run]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stl_bbox import read_stl_bbox  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--tol", type=float, default=0.01, help="同高判定容差(mm)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.target)
    files = sorted(p for p in root.glob("*.stl") if p.is_file())
    if not files:
        print("目录内没有 STL 文件")
        return 1

    # 1) 量高度
    items = []
    for f in files:
        (x0, x1), (y0, y1), (z0, z1), tris = read_stl_bbox(f)
        items.append({"file": f, "h": z1 - z0, "zmin": z0,
                      "x": x1 - x0, "y": y1 - y0, "tris": tris})

    # 2) 分组（按高度升序，容差内归入同组）
    items.sort(key=lambda d: d["h"])
    groups = []
    for it in items:
        if groups and abs(it["h"] - groups[-1]["ref"]) <= args.tol:
            groups[-1]["items"].append(it)
        else:
            groups.append({"ref": it["h"], "items": [it]})

    # 3) 建目录并移动
    print(f"共 {len(items)} 个模型，分为 {len(groups)} 组\n")
    for g in groups:
        name = f"高度{g['ref']:.3f}mm"
        d = root / name
        print(f"[{name}] {len(g['items'])} 个")
        for it in sorted(g["items"], key=lambda d: d["file"].name.lower()):
            tag = f"  (zmin={it['zmin']:.2f})" if abs(it["zmin"]) > 0.005 else ""
            print(f"    {it['file'].name}  H={it['h']:.3f}{tag}")
            if not args.dry_run:
                d.mkdir(parents=True, exist_ok=True)
                dest = d / it["file"].name
                if dest.exists():
                    print(f"    ! 目标已存在，跳过: {dest}")
                    continue
                shutil.move(str(it["file"]), str(dest))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
