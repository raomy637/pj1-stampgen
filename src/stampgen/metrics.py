"""字宽模型与限宽求解。

核心结论（已在 OpenSCAD 2021.01 上实测校准）：

1. ``text(size=...)`` 的 ``size`` 并不是毫米 —— OpenSCAD 内部按 96dpi/72pt
   放大 4/3 倍，实际 em 尺寸 = ``size * 4/3`` 毫米。
2. 文字墨迹宽度对 ``size`` 与 ``spacing`` 都是线性的：

       W_em(spacing) = k * spacing + c
       W_mm = W_em * size * K + 2 * weight_offset

   其中 ``k`` 是「末字符之前的 advance 之和」，``c`` 是
   「末字符 xMax − 首字符 xMin」，两者都由字体度量精确给出。
   实测偏差 < 0.5%（旧版只累加 advance 的近似式偏差约 1%）。
3. ``offset(delta=d)`` 几何加粗会让墨迹两侧各外扩 d，宽度与字高各增加 2d。

求解策略（v2.2.0 起只有一种模式）：**限宽**。

    size = 用户给定字号（先受「字高 ≤ 底座宽」硬约束压低）
    width = predict(text, size, spacing)
    若 width > 上限：先压间距到 min_spacing，仍超则按比例缩字号，
    缩到 hard_min_size_mm 还超就判 too_long。

短名字不补齐到上限 —— 3 个字母的印章就该比 8 个字母的短。
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

GEOMETRY_TOLERANCE_MM = 0.05
"""字高超出底座宽度的容许量。

与模板里的 ``overlap = 0.05`` 同量级：一根 0.4mm 喷嘴的八分之一，
粘得住、看得见，不值得为它把字号压掉 0.04mm 并在每一行标「限字高」。
"""

STATUS_LABELS = {
    "ok": "正常",
    "spacing_compressed": "已压缩",
    "size_capped": "限字高",
    "size_shrunk": "已缩字",
    "too_long": "超长",
    "empty": "空",
    "missing_glyph": "缺字",
    "invalid": "无效",
}
"""状态短标签。

结果表的状态列固定只有 4 个汉字宽，长句子一律走悬停提示，
所以这里只放短标签，完整原因在 :attr:`FitResult.detail`。
"""

_SEVERITY = {
    "ok": 0,
    "spacing_compressed": 1,
    "size_capped": 2,
    "size_shrunk": 3,
    "too_long": 4,
    "empty": 8,
    "missing_glyph": 8,
    "invalid": 8,
}

_ATTENTION = {"spacing_compressed", "size_capped", "size_shrunk"}
_BLOCKING = {"too_long", "empty", "missing_glyph", "invalid"}


def _worse(a: str, b: str) -> str:
    """取更严重的状态，用于一件事接一件事发生时的状态合并。"""
    return a if _SEVERITY.get(a, 0) >= _SEVERITY.get(b, 0) else b


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
    """一个名字的求解结果。"""

    size_mm: float
    spacing: float
    width_mm: float
    """文字墨迹宽度（毫米）。"""

    base_len_mm: float
    """底座长度 = 文字宽 + 2 × 留白 + 2 × 加粗。"""

    status: str = "ok"
    notes: list[str] = field(default_factory=list)
    limit_mm: float = 0.0
    """底座长度上限（``spec.max_width_mm``），方便界面直接取用。"""

    fill_ratio: float = 0.0
    """文字宽占上限的比例。短名字会明显小于 1，这是正常的。"""

    @property
    def ok(self) -> bool:
        return self.status not in _BLOCKING

    @property
    def label(self) -> str:
        """状态短标签（≤4 个汉字）。"""
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def detail(self) -> str:
        """完整原因，用于日志与悬停提示。"""
        return "；".join(self.notes) or self.label

    @property
    def needs_attention(self) -> bool:
        """被压缩过，需要提醒用户。"""
        return self.status in _ATTENTION

    @property
    def is_blocking(self) -> bool:
        return self.status in _BLOCKING


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
    """字号对应的字高（毫米），含 OpenSCAD 的 4/3 放大。"""
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


def size_cap_from_base(metrics: FaceMetrics, spec: StampSpec) -> float:
    """由底座宽度反推字号硬上限。

    字高（含加粗外扩 2 × weight）不得超过底座宽度，否则字母会悬在底座外。
    这是**唯一**一条压字号的几何约束 —— 不再额外留 edge 余量，否则
    「6mm 字号配 6mm 底座」这种一直能打的组合会被莫名其妙压到 5.71mm。
    """
    cap_ratio = metrics.cap_ratio()
    if cap_ratio <= 0:
        return float("inf")
    usable = spec.base_width_mm - 2.0 * max(0.0, spec.weight_offset_mm)
    if usable <= 0:
        return 0.0
    return usable / (cap_ratio * OPENSCAD_SIZE_SCALE)


def solve_size_for_width(
    metrics: FaceMetrics,
    text: str,
    target_width_mm: float,
    spacing: float,
    weight_offset_mm: float = 0.0,
) -> float:
    """在给定间距下，反解正好占满目标宽度所需的字号。"""
    k, c = ink_linear(metrics, text)
    denom = k * spacing * ADVANCE_SCALE + c * INK_SCALE
    if denom <= 0:
        return 0.0
    usable = target_width_mm - 2.0 * max(0.0, weight_offset_mm)
    if usable <= 0:
        return 0.0
    return usable / denom


def solve_spacing_for_width(
    metrics: FaceMetrics,
    text: str,
    target_width_mm: float,
    size_mm: float,
    weight_offset_mm: float = 0.0,
) -> float | None:
    """在给定字号下，反解正好占满目标宽度所需的间距；单字符无法求解返回 None。"""
    k, c = ink_linear(metrics, text)
    if size_mm <= 0 or k <= 0:
        return None
    usable = target_width_mm - 2.0 * max(0.0, weight_offset_mm)
    if usable <= 0:
        return None
    return (usable / size_mm - c * INK_SCALE) / (k * ADVANCE_SCALE)


def size_from_probe(probe_width_mm: float, probe_size_mm: float, target_mm: float) -> float:
    """由一次实测探针反推占满目标宽度所需的字号。

    宽度与字号严格成正比（已实测），因此单次探针即可得到精确字号，
    并且自动吸收字体 GPOS 字距调整带来的误差。
    """
    if probe_width_mm <= 0 or probe_size_mm <= 0:
        return 0.0
    return probe_size_mm * target_mm / probe_width_mm


def probe_scale(
    metrics: FaceMetrics, text: str, spacing: float, probe_width_mm: float, probe_size_mm: float
) -> float:
    """实测宽度 / 解析预测宽度。

    探针在 ``probe_size_mm`` 下渲染（无加粗），比值可以直接当作
    「解析模型相对实测的系统性偏差」，后续用 ``width_scale`` 传回 :func:`fit`，
    让压缩判断也建立在实测口径上。
    """
    predicted = predict_width(metrics, text, probe_size_mm, spacing, 0.0)
    if predicted <= 0 or probe_width_mm <= 0:
        return 1.0
    return probe_width_mm / predicted


def fit(
    metrics: FaceMetrics,
    text: str,
    spec: StampSpec,
    width_scale: float = 1.0,
) -> FitResult:
    """限宽求解：字号尽量保持不变，超宽时先压间距、再缩字号。

    ``width_scale`` 是实测探针给出的修正系数（实测宽 / 预测宽）。实现上
    只是把「允许宽度」除以它，就等价于把所有预测宽度乘以它，逻辑无需改动。
    """
    text = (text or "").strip()
    limit = spec.max_text_width()
    weight = max(0.0, spec.weight_offset_mm)
    spacing0 = spec.letter_spacing

    if not text:
        return FitResult(0.0, spacing0, 0.0, 0.0, "empty", ["名字为空"], limit)

    missing = metrics.missing_chars(text)
    if missing:
        return FitResult(
            0.0, spacing0, 0.0, 0.0, "missing_glyph", [f"当前字体缺少字符：{''.join(missing)}"], limit
        )

    if limit <= 0:
        return FitResult(
            0.0,
            spacing0,
            0.0,
            0.0,
            "invalid",
            [f"左右留白 2 × {spec.margin_mm:g}mm 已占满上限 {spec.max_width_mm:g}mm，请加大上限"],
            limit,
        )

    k, c = ink_linear(metrics, text)
    if k <= 0 and c <= 0:
        return FitResult(0.0, spacing0, 0.0, 0.0, "invalid", ["字体度量为空"], limit)

    scale = width_scale if width_scale > 0 else 1.0
    # 预测宽 × scale ≤ limit  ⇔  预测宽 ≤ limit / scale
    eff_limit = limit / scale

    def width_at(size: float, spacing: float) -> float:
        return predict_width(metrics, text, size, spacing, weight)

    notes: list[str] = []
    status = "ok"
    size = spec.font_size_mm
    spacing = spacing0

    # ---- 第一步：字高不得超过底座宽 ----
    cap = cap_height_mm(metrics, size)
    total = cap + 2.0 * weight
    if total > spec.base_width_mm + GEOMETRY_TOLERANCE_MM:
        size = size_cap_from_base(metrics, spec)
        status = _worse(status, "size_capped")
        # 加粗会让墨迹上下各外扩 weight，必须一起算，否则文案会自相矛盾
        # （"字高 5.88 超过 6.00" 这种）
        shape = f"字高 {cap:.2f}mm" + (
            f" 加加粗 {2.0 * weight:.2f}mm 共 {total:.2f}mm" if weight > 0 else ""
        )
        notes.append(
            f"字号 {spec.font_size_mm:.2f}mm 的{shape}超过底座宽度 "
            f"{spec.base_width_mm:.2f}mm，已压到 {size:.2f}mm；"
            f"想用原字号请把底座宽度加到 {total:.2f}mm"
        )

    # ---- 第二步：超宽则先压间距 ----
    raw = width_at(size, spacing)
    if raw > eff_limit + 1e-9:
        floor = min(spacing0, spec.min_spacing)
        solved = solve_spacing_for_width(metrics, text, eff_limit, size, weight)
        if solved is not None and solved >= floor:
            spacing = solved
            status = _worse(status, "spacing_compressed")
            notes.append(
                f"名字偏长，间距从 {spacing0:.2f} 压到 {spacing:.2f}，"
                f"以适配上限 {spec.max_width_mm:g}mm"
            )
        else:
            spacing = floor
            # ---- 第三步：间距压到底还超，才缩字号 ----
            if width_at(size, spacing) > eff_limit + 1e-9:
                solved_size = solve_size_for_width(metrics, text, eff_limit, spacing, weight)
                if solved_size >= spec.hard_min_size_mm:
                    size = solved_size
                    status = _worse(status, "size_shrunk")
                    notes.append(
                        f"间距已压到下限 {spacing:.2f}，字号再缩到 {size:.2f}mm "
                        f"才放进 {spec.max_width_mm:g}mm"
                    )
                else:
                    size = spec.hard_min_size_mm
                    status = "too_long"
                    need = width_at(size, spacing) * scale
                    suggest = spec.base_len_for(need)
                    notes.append(
                        f"名字过长：字号缩到下限 {spec.hard_min_size_mm:.2f}mm、"
                        f"间距压到 {spacing:.2f} 仍需 {need:.2f}mm，"
                        f"超过上限 {spec.max_width_mm:g}mm；"
                        f"建议把上限加到 {suggest:.1f}mm 或缩短名字"
                    )
            else:
                status = _worse(status, "spacing_compressed")
                notes.append(
                    f"名字偏长，间距从 {spacing0:.2f} 压到 {spacing:.2f}，"
                    f"以适配上限 {spec.max_width_mm:g}mm"
                )

    width = width_at(size, spacing) * scale
    base_len = spec.base_len_for(width)
    fill = width / limit if limit > 0 else 0.0

    return FitResult(
        size_mm=round(size, 3),
        spacing=round(spacing, 3),
        width_mm=round(width, 3),
        base_len_mm=round(base_len, 3),
        status=status,
        notes=notes,
        limit_mm=limit,
        fill_ratio=round(fill, 4),
    )
