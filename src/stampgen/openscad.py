"""OpenSCAD 子进程封装与 STL 几何测量。"""

from __future__ import annotations

import os
import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .fonts import FontFace
from .template import RenderParams, to_defines


class OpenSCADError(RuntimeError):
    pass


@dataclass
class StlStats:
    triangles: int
    width: float
    depth: float
    height: float


@dataclass
class Extent:
    """某个 Z 高度以上部分的包围盒。"""

    count: int
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_max: float

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def depth(self) -> float:
        return self.y_max - self.y_min

    @property
    def y_center(self) -> float:
        return (self.y_min + self.y_max) / 2.0


def version(exe: Path, timeout: float = 30.0) -> str:
    """调用 ``openscad -v`` 并返回版本字符串。"""
    exe = Path(exe)
    if not exe.is_file():
        raise FileNotFoundError(f"找不到 OpenSCAD 可执行文件：{exe}")
    proc = subprocess.run(
        [str(exe), "-v"],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise OpenSCADError(f"OpenSCAD 返回错误（{proc.returncode}）：{out.strip()}")
    return out.strip()


def _run(
    exe: Path,
    args: list[str],
    env: dict[str, str] | None,
    timeout: float,
) -> subprocess.CompletedProcess:
    exe = Path(exe)
    if not exe.is_file():
        raise FileNotFoundError(f"找不到 OpenSCAD 可执行文件：{exe}")
    try:
        proc = subprocess.run(
            [str(exe), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenSCADError(f"OpenSCAD 执行超时（{timeout}s）") from exc
    if proc.returncode != 0:
        detail = ((proc.stdout or "") + (proc.stderr or "")).strip()
        raise OpenSCADError(f"OpenSCAD 渲染失败：{detail or '无输出'}")
    return proc


def export_stl(
    exe: Path,
    template: Path,
    params: RenderParams,
    out_path: Path,
    env: dict[str, str] | None = None,
    timeout: float = 180.0,
    binary: bool = True,
) -> Path:
    """渲染单个印章并导出 STL。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = ["-o", str(out_path)]
    if binary:
        args += ["--export-format", "binstl"]
    args += to_defines(params)
    args.append(str(template))
    proc = _run(exe, args, env, timeout)

    # CGAL 失败时 OpenSCAD 不会返回非零退出码，而是只把底座导出、
    # 字母整个丢掉 —— 必须自己查输出，否则会静默产出没有字的印章。
    output = (proc.stdout or "") + (proc.stderr or "")
    if "not closed" in output or "Unable to convert to CGAL_Nef_Polyhedron" in output:
        raise OpenSCADError(
            f"网格未闭合：字形轮廓自交，无法与底座合并（{out_path.name}）"
        )

    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise OpenSCADError(f"未生成有效 STL：{out_path}")
    return out_path


_ASCII_VERTEX = re.compile(r"vertex\s+(-?[\d.eE+]+)\s+(-?[\d.eE+]+)\s+(-?[\d.eE+]+)")


def _read_vertices(path: Path) -> tuple[int, list[tuple[float, float, float]]]:
    """解析 STL，返回 (三角面数, 顶点列表)。兼容二进制与 ASCII。"""
    data = Path(path).read_bytes()
    if len(data) < 84:
        raise OpenSCADError(f"STL 文件损坏：{path}")

    count = struct.unpack("<I", data[80:84])[0]
    if len(data) == 84 + count * 50:
        verts: list[tuple[float, float, float]] = []
        unpack = struct.unpack_from
        for i in range(count):
            base = 84 + i * 50 + 12
            for j in range(3):
                off = base + j * 12
                verts.append(unpack("<3f", data, off))
        if not verts:
            raise OpenSCADError(f"STL 为空：{path}")
        return count, verts

    text = data.decode("utf-8", errors="replace")
    raw = _ASCII_VERTEX.findall(text)
    if not raw:
        raise OpenSCADError(f"无法解析 STL：{path}")
    verts = [(float(a), float(b), float(c)) for a, b, c in raw]
    return text.count("facet normal"), verts


def stl_stats(path: Path) -> StlStats:
    """整体包围盒尺寸（含底座）。"""
    count, verts = _read_vertices(path)
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return StlStats(count, max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def stl_extent(path: Path, z_above: float | None = None) -> Extent:
    """指定高度以上部分的包围盒。

    印章的底座占满整个目标宽度，直接量整体包围盒只会量到底座，
    因此校验文字宽度时必须只取底座顶面以上的顶点。
    """
    count, verts = _read_vertices(path)
    if z_above is not None:
        verts = [v for v in verts if v[2] > z_above]
    if not verts:
        raise OpenSCADError(f"STL 在 z>{z_above} 以上没有几何体：{path}")
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return Extent(
        count=count,
        x_min=min(xs),
        x_max=max(xs),
        y_min=min(ys),
        y_max=max(ys),
        z_max=max(zs),
    )


_PROBE_SCAD = 'linear_extrude(height=1) text("HHH", size=10, font="{font}", halign="center");'


def _probe_width(exe: Path, font: str, env: dict[str, str] | None, timeout: float) -> float:
    with tempfile.TemporaryDirectory(prefix="stampgen-probe-") as tmp:
        scad = Path(tmp) / "probe.scad"
        stl = Path(tmp) / "probe.stl"
        scad.write_text(_PROBE_SCAD.format(font=font), encoding="utf-8")
        _run(exe, ["-o", str(stl), "--export-format", "binstl", str(scad)], env, timeout)
        return stl_stats(stl).width


def can_resolve_font(
    exe: Path,
    face: FontFace,
    env: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> bool:
    """验证 OpenSCAD 是否真的解析到了目标字体。

    做法：分别用目标字体与一个必然不存在的字体渲染同一串字符，
    若包围盒宽度完全一致，说明目标字体被静默回退到了默认字体。
    """
    try:
        target = _probe_width(exe, face.openscad_font, env, timeout)
        fallback = _probe_width(exe, "__stampgen_missing_font__", env, timeout)
    except (OpenSCADError, FileNotFoundError, OSError):
        return False
    return abs(target - fallback) > 1e-4


def openscad_env(font_env: dict[str, str] | None) -> dict[str, str] | None:
    """统一构造子进程环境（保留当前进程变量，叠加 fontconfig）。"""
    if font_env is None:
        return None
    env = dict(os.environ)
    env.update(font_env)
    return env


_WARMUP_SCAD = 'linear_extrude(height=0.2) text("H", size=2, font="{font}");'


_PROBE_TMPL = (
    "$fa=6; $fs=1;\n"
    "linear_extrude(height=0.2)\n"
    '    text("{text}", size={size}, font="{font}", spacing={spacing},\n'
    '         halign="center", valign="baseline");\n'
)


def _scad_quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def probe_text_width(
    exe: Path,
    face: FontFace,
    text: str,
    spacing: float,
    env: dict[str, str] | None = None,
    size: float = 10.0,
    timeout: float = 120.0,
) -> float:
    """实测某串文字在给定字号/间距下的墨迹宽度。

    只挤出 0.2mm 且用粗精度，单次约 0.3~1 秒，比整枚印章快一个数量级。
    宽度与字号严格成正比，因此一次探针就能反推出精确字号，
    并自动吸收字体 GPOS 字距调整造成的解析误差。
    """
    with tempfile.TemporaryDirectory(prefix="stampgen-probe-") as tmp:
        scad = Path(tmp) / "probe.scad"
        stl = Path(tmp) / "probe.stl"
        scad.write_text(
            _PROBE_TMPL.format(
                text=_scad_quote(text),
                size=f"{size:g}",
                font=face.openscad_font,
                spacing=f"{spacing:g}",
            ),
            encoding="utf-8",
        )
        _run(exe, ["-o", str(stl), "--export-format", "binstl", str(scad)], env, timeout)
        return stl_stats(stl).width


def warmup(exe: Path, face: FontFace, env: dict[str, str] | None = None, timeout: float = 600.0) -> float:
    """预热 fontconfig 缓存。

    首次让 OpenSCAD 加载自定义字体目录时，fontconfig 需要扫描并建缓存，
    实测可能耗时 60~80 秒。提前在批次开始时做一次，避免用户误以为程序卡死。
    返回耗时秒数。
    """
    import time

    started = time.time()
    with tempfile.TemporaryDirectory(prefix="stampgen-warm-") as tmp:
        scad = Path(tmp) / "warm.scad"
        stl = Path(tmp) / "warm.stl"
        scad.write_text(_WARMUP_SCAD.format(font=face.openscad_font), encoding="utf-8")
        _run(exe, ["-o", str(stl), "--export-format", "binstl", str(scad)], env, timeout)
    return time.time() - started
