"""字宽模型与定宽自适应求解。

核心结论（已在 OpenSCAD 2021.01 上实测校准）：

1. ``text(size=...)`` 的 ``size`` 并不是毫米 —— OpenSCAD 内部按 96dpi/72pt
   放大 4/3 倍，实际 em 尺寸 = ``size * 4/3`` 毫米。
2. 文字墨迹宽度对 ``size`` 与 ``spacing`` 都是线性的：

       W_em(spacing) = k * spacing + c
       W_mm = W_em * size * K + 2 * weight_offset

   其中 ``k`` 是「末字符之前的 advance 之和」，``c`` 是
   「末字符 xMax − 首字符 xMin」，两者都由字体度量精确给出。
   实测偏差 < 0.5%（旧版只累加 advance 的近似式偏差约 1%）。
3. ``offset(delta=d)`` 几何加粗会让墨迹两侧各外扩 d，宽度增加约 2d。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import StampSpec
from .fonts import FaceMetrics, FontFace

OPENSCAD_SIZE_SCALE = 4.0 / 3.0
"""OpenSCAD 2021.01 的 size→毫米基础换算系数（96dpi / 72pt）。"""

# 以下两个系数由实测标定（Daziji / Special Elite 三种字体一致，说明是
# OpenSCAD 的固定行为而非字体差异）：
#   * 字符推进（advance）实际放大 4/3 × 1.01725
#   * 字形墨迹（bbox）实际放大 4/3 × 1.04159
# 两者不一致，是因为 OpenSCAD 传给 FreeType 的字号与 upem 之间存在固定偏差。
ADVANCE_SCALE = OPENSCAD_SIZE_SCALE * 1.01725
INK_SCALE = OPENSCAD_SIZE_SCALE * 1.04159

#: 轮廓节点密集的字体（做旧、点阵风格）：粗精度即可，视觉无差别。
CURVE_DENSE = (12.0, 2.0)
#: 轮廓干净、靠贝塞尔曲线描述字形：必须细精度，否则 O/R 会明显多边形化。
CURVE_CLEAN = (4.0, 0.3)


def resolve_curve(face: FontFace, spec: StampSpec) -> tuple[float, float]:
    """决定 ``$fa`` / ``$fs``。

    实测（OpenSCAD 2021.01，字号 5.2mm、5 个字母、含底座布尔运算）：

    * 做旧字体 ``$fa=12/$fs=2.0`` 与 ``$fa=4/$fs=0.8`` 渲染结果视觉一致，
      但耗时从 48s 降到 7.5s、体积从 1.9MB 降到 0.37MB。
    * 常规字体（Arial）在 ``$fs=1.6`` 时 O/R 已明显多边形化，必须 ≤0.4。
    """
    if spec.curve_fa > 0 and spec.curve_fs > 0:
        return spec.curve_fa, spec.curve_fs
    return CURVE_DENSE if face.is_dense_outline else CURVE_CLEAN


@dataclass
class FitResult:
    size_mm: float
    spacing: float
    width_mm: float
    available_mm: float
    fill_ratio: float
    status: str
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status not in {"empty", "missing_glyph", "too_long", "invalid"}


def ink_linear(metrics: FaceMetrics, text: str) -> tuple[float, float]:
    """返回 (k, c)，使墨迹宽度（em）= k * spacing + c。"""
    if not text or not metrics.upem:
        return 0.0, 0.0
    first, last = text[0], text[-1]
    advance_before_last = sum(metrics.advances.get(ord(ch), 0) for ch in text[:-1]) / metrics.upem
    box_last = metrics.bboxes.get(ord(last))
    box_first = metrics.bboxes.get(ord(first))
    if box_last is None or box_first is None:
        total, last_adv = metrics.advance_em(text)
        return total - last_adv, last_adv
    return advance_before_last, (box_last[1] - box_first[0]) / metrics.upem


def predict_width(
    metrics: FaceMetrics,
    text: str,
    size_mm: float,
    spacing: float,
    weight_offset_mm: float = 0.0,
) -> float:
    """预测文字墨迹宽度（毫米）。

    未发生字距调整（kerning）时误差 < 0.3%；字体带 GPOS 字距时可能偏大 1~2%，
    批次生成时用 :func:`stampgen.openscad.probe_text_width` 实测修正。
    """
    k, c = ink_linear(metrics, text)
    if k <= 0 and c <= 0:
        return 0.0
    return (
        (k * spacing * ADVANCE_SCALE + c * INK_SCALE) * size_mm
        + 2.0 * max(0.0, weight_offset_mm)
    )


def cap_height_mm(metrics: FaceMetrics, size_mm: float) -> float:
    return metrics.cap_ratio() * size_mm * OPENSCAD_SIZE_SCALE


def text_offset_y(metrics: FaceMetrics, text: str, size_mm: float) -> float:
    """把整串文字的墨迹垂直中心移到 y=0 所需的平移量（毫米）。

    OpenSCAD 的 ``valign="center"`` 是按字体 ascent/descent 居中的，
    对整体上移过的自定义字体（如 Daziji 系列）会明显偏上；
    因此模板改用 ``valign="baseline"``，再由本函数按实际墨迹包围盒精确居中。
    """
    if not metrics.upem or not text:
        return 0.0
    return -metrics.ink_y_center(text) / metrics.upem * size_mm * INK_SCALE


def size_limit_from_geometry(metrics: FaceMetrics, spec: StampSpec) -> float:
    """由底座宽度反推允许的最大字号（保证字高不超出底座）。"""
    cap_ratio = metrics.cap_ratio()
    if cap_ratio <= 0:
        return spec.max_size_mm
    usable = spec.base_width_mm - 2.0 * spec.edge_mm - 2.0 * max(0.0, spec.weight_offset_mm)
    if usable <= 0:
        return spec.hard_min_size_mm
    return usable / (cap_ratio * OPENSCAD_SIZE_SCALE)


def size_bounds(metrics: FaceMetrics, spec: StampSpec) -> tuple[float, float]:
    """实际可用的字号区间 (min, max)，已考虑底座几何约束。"""
    geo_limit = size_limit_from_geometry(metrics, spec)
    size_max = min(spec.max_size_mm, geo_limit)
    size_min = min(spec.min_size_mm, size_max)
    return size_min, size_max


def solve_size(metrics: FaceMetrics, text: str, available_mm: float, spacing: float) -> float:
    """在给定间距下，反解填满可用宽度所需的字号。"""
    k, c = ink_linear(metrics, text)
    denom = k * spacing * ADVANCE_SCALE + c * INK_SCALE
    if denom <= 0:
        return 0.0
    return available_mm / denom


def solve_spacing(
    metrics: FaceMetrics, text: str, available_mm: float, size_mm: float
) -> float | None:
    """在给定字号下，反解填满可用宽度所需的间距；单字符无法求解返回 None。"""
    k, c = ink_linear(metrics, text)
    if size_mm <= 0 or k <= 0:
        return None
    return (available_mm / size_mm - c * INK_SCALE) / (k * ADVANCE_SCALE)


def size_from_probe(probe_width_mm: float, probe_size_mm: float, target_mm: float) -> float:
    """由一次实测探针反推填满目标宽度所需的字号。

    宽度与字号严格成正比（已实测），因此单次探针即可得到精确字号，
    并且自动吸收字体 GPOS 字距调整带来的误差。
    """
    if probe_width_mm <= 0 or probe_size_mm <= 0:
        return 0.0
    return probe_size_mm * target_mm / probe_width_mm


def underfill_note(spec: StampSpec, width_mm: float, available_mm: float) -> str:
    """短名字填不满时的提示，带一个可执行的目标宽度建议。

    单独抽成函数是因为批次会用实测值回填宽度，提示文案需要跟着刷新。
    """
    suggest = width_mm + 2.0 * spec.margin_mm + 2.0 * spec.weight_offset_mm
    return (
        f"成品仅 {width_mm:.1f}mm，未填满 {available_mm:.1f}mm；"
        f"建议目标宽度改为约 {suggest:.1f}mm，或加大底座宽度以提高字号上限"
    )


def fit(metrics: FaceMetrics, text: str, spec: StampSpec) -> FitResult:
    """定宽自适应：求 (字号, 间距) 使文字尽量填满目标宽度。"""
    text = (text or "").strip()
    available = spec.available_mm()

    if not text:
        return FitResult(0.0, spec.default_spacing, 0.0, available, 0.0, "empty", ["名字为空"])

    if available <= 0:
        return FitResult(
            0.0,
            spec.default_spacing,
            0.0,
            available,
            0.0,
            "invalid",
            [f"可用宽度为 {available:.2f}mm，请检查目标宽度与留白设置"],
        )

    missing = metrics.missing_chars(text)
    if missing:
        return FitResult(
            0.0,
            spec.default_spacing,
            0.0,
            available,
            0.0,
            "missing_glyph",
            [f"当前字体缺少字符：{''.join(missing)}"],
        )

    k, c = ink_linear(metrics, text)
    if k <= 0 and c <= 0:
        return FitResult(0.0, spec.default_spacing, 0.0, available, 0.0, "invalid", ["字体度量为空"])

    notes: list[str] = []
    size_min, size_max = size_bounds(metrics, spec)
    geo_limit = size_limit_from_geometry(metrics, spec)
    if geo_limit < spec.max_size_mm:
        notes.append(f"字号上限受底座宽度约束，实际上限 {geo_limit:.2f}mm")

    spacing = spec.default_spacing
    status = "ok"
    size = solve_size(metrics, text, available, spacing)

    if size > size_max:
        # 字太大：封顶后用间距补足
        size = size_max
        solved = solve_spacing(metrics, text, available, size)
        if solved is None:
            spacing = spec.default_spacing
        elif solved > spec.max_spacing:
            spacing = spec.max_spacing
            status = "underfill"
            notes.append("名字较短，间距已达上限")
        else:
            spacing = solved
    elif size < size_min:
        # 字太小：托底后用压缩间距补偿
        size = size_min
        solved = solve_spacing(metrics, text, available, size)
        if solved is not None and solved >= spec.min_spacing:
            spacing = solved
        else:
            spacing = spec.min_spacing
            shrunk = solve_size(metrics, text, available, spacing)
            if shrunk >= size_min:
                size = shrunk
            elif shrunk >= spec.hard_min_size_mm:
                size = shrunk
                status = "spacing_min"
                notes.append("间距已压到下限，字号相应缩小")
            else:
                size = spec.hard_min_size_mm
                status = "too_long"
                needed = predict_width(
                    metrics, text, spec.hard_min_size_mm, spec.min_spacing, spec.weight_offset_mm
                )
                suggest = needed + 2.0 * spec.margin_mm + 2.0 * spec.weight_offset_mm
                notes.append(
                    f"名字过长：最小字号 {spec.hard_min_size_mm:.1f}mm 下仍需 "
                    f"{needed:.1f}mm，建议底座宽度不小于 {suggest:.1f}mm"
                )

    width = predict_width(metrics, text, size, spacing, spec.weight_offset_mm)
    fill = width / available if available > 0 else 0.0

    if status == "underfill":
        # 给出可执行的下一步：要么把底座改短，要么把底座加宽换更大的字号
        notes.append(underfill_note(spec, width, available))

    return FitResult(
        size_mm=round(size, 3),
        spacing=round(spacing, 3),
        width_mm=round(width, 3),
        available_mm=round(available, 3),
        fill_ratio=round(fill, 4),
        status=status,
        notes=notes,
    )
