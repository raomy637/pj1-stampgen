"""SCAD 参数渲染与命令行定义构造。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import metrics as metrics_mod
from .config import StampSpec
from .fonts import FaceMetrics, FontFace
from .metrics import FitResult


@dataclass
class RenderParams:
    name: str
    base_len: float
    base_width: float
    base_height: float
    letter_size: float
    letter_spacing: float
    letter_height: float
    font_family: str
    font_style: str
    weight_offset: float
    text_offset_y: float
    curve_fa: float
    curve_fs: float

    @classmethod
    def build(
        cls,
        name: str,
        face: FontFace,
        spec: StampSpec,
        fit: FitResult,
        metrics: FaceMetrics | None = None,
        base_len: float | None = None,
        curve: tuple[float, float] | None = None,
    ) -> "RenderParams":
        offset_y = 0.0
        if metrics is not None:
            offset_y = metrics_mod.text_offset_y(metrics, name, fit.size_mm)
        fa, fs = curve if curve is not None else (4.0, 0.3)
        return cls(
            name=name,
            base_len=round(spec.target_width_mm if base_len is None else base_len, 3),
            base_width=round(spec.base_width_mm, 3),
            base_height=round(spec.base_height_mm, 3),
            letter_size=round(fit.size_mm, 4),
            letter_spacing=round(fit.spacing, 4),
            letter_height=round(spec.letter_height_mm, 3),
            font_family=face.family,
            font_style=face.style,
            weight_offset=round(spec.weight_offset_mm, 4),
            text_offset_y=round(offset_y, 4),
            curve_fa=round(fa, 3),
            curve_fs=round(fs, 3),
        )


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".") or "0"
    raise TypeError(f"不支持的参数类型：{type(value)!r}")


def to_defines(params: RenderParams) -> list[str]:
    """构造 OpenSCAD 的 ``-D key=value`` 参数列表。"""
    pairs = [
        ("name", params.name),
        ("base_len", params.base_len),
        ("base_width", params.base_width),
        ("base_height", params.base_height),
        ("letter_size", params.letter_size),
        ("letter_spacing", params.letter_spacing),
        ("letter_height", params.letter_height),
        ("font_family", params.font_family),
        ("font_style", params.font_style),
        ("weight_offset", params.weight_offset),
        ("text_offset_y", params.text_offset_y),
        ("curve_fa", params.curve_fa),
        ("curve_fs", params.curve_fs),
    ]
    args: list[str] = []
    for key, value in pairs:
        args.extend(["-D", f"{key}={_fmt(value)}"])
    return args


def preview_scad(params: RenderParams, template: Path) -> str:
    """生成自包含的 scad 文本，便于在 OpenSCAD GUI 中直接打开检查。"""
    header = "\n".join(
        f"{key}={_fmt(value)};"
        for key, value in [
            ("name", params.name),
            ("base_len", params.base_len),
            ("base_width", params.base_width),
            ("base_height", params.base_height),
            ("letter_size", params.letter_size),
            ("letter_spacing", params.letter_spacing),
            ("letter_height", params.letter_height),
            ("font_family", params.font_family),
            ("font_style", params.font_style),
            ("weight_offset", params.weight_offset),
            ("text_offset_y", params.text_offset_y),
            ("curve_fa", params.curve_fa),
            ("curve_fs", params.curve_fs),
        ]
    )
    body = Path(template).read_text(encoding="utf-8")
    return f"// 由 stampgen 生成的预览文件\n{header}\n\n{body}"
