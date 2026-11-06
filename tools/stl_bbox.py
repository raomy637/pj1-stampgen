"""计算 STL 文件的包围盒尺寸（支持二进制与 ASCII STL）。

用法:
    python tools/stl_bbox.py <目录或文件> [...]
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path


def _bbox_from_points(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


def read_stl_bbox(path: Path):
    """返回 ((xmin,xmax),(ymin,ymax),(zmin,zmax), 三角面数)。"""
    data = path.read_bytes()
    if not data:
        raise ValueError("空文件")

    # 二进制 STL: 84 字节头 + n*50 字节
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + n * 50:
            pts = []
            unpack = struct.Struct("<12fH").unpack_from
            for i in range(n):
                v = unpack(data, 84 + i * 50)
                pts.append((v[3], v[4], v[5]))
                pts.append((v[6], v[7], v[8]))
                pts.append((v[9], v[10], v[11]))
            if not pts:
                raise ValueError("无三角面")
            return (*_bbox_from_points(pts), n)

    # ASCII STL
    text = data.decode("utf-8", errors="ignore")
    if "vertex" not in text:
        raise ValueError("无法识别的 STL 格式")
    pts = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0].lower() == "vertex":
            pts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    if not pts:
        raise ValueError("ASCII STL 无顶点数据")
    tris = text.lower().count("facet normal")
    return (*_bbox_from_points(pts), tris)


def iter_stl(target: Path):
    if target.is_file():
        yield target
    else:
        yield from sorted(target.rglob("*.stl"))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    for arg in argv[1:]:
        root = Path(arg)
        for f in iter_stl(root):
            try:
                (x0, x1), (y0, y1), (z0, z1), tris = read_stl_bbox(f)
                print(
                    f"{f.name}\t"
                    f"X={x1 - x0:.3f}\tY={y1 - y0:.3f}\tZ={z1 - z0:.3f}\t"
                    f"zmin={z0:.3f}\ttris={tris}"
                )
            except Exception as exc:  # noqa: BLE001
                print(f"{f.name}\tERROR\t{exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
