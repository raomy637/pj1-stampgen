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

import math
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

GEOMETRY_TOLERANCE_MM = 0.3
"""墨迹高度超出底座宽度的容许量。

圆形字母（O / S / D）按字体设计会比 H 略微高出一点点（overshoot），
实测本项目七款字体在 6mm 字号下墨迹高 6.01~6.23mm，即最多溢出 0.23mm。
这是字形设计，不是参数错误，0.15mm 的悬挑打印毫无问题。

留 0.3mm 而不是 0.2mm，是为了让「KHLOE 被压、DAISY 不被压」这种
差 0.03mm 就一个缩字一个不缩的割裂不出现在同一批里。
超过 0.3mm 才是真的装不下 —— 例如带 g/y/p 的下沉字母，6mm 字号溢出 2mm。
"""

UPPERCASE_SAMPLE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
"""没有具体名字时，用大写字母集合估字体的墨迹高度。"""

STATUS_LABELS = {
    "ok": "正常",
    "spacing_compressed": "已压缩",
    "wider_base": "加宽",
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
    "wider_base": 2,
    "size_capped": 2,
    "size_shrunk": 3,
    "too_long": 4,
    "empty": 8,
    "missing_glyph": 8,
    "invalid": 8,
}

_ATTENTION = {"spacing_compressed", "wider_base", "size_capped", "size_shrunk"}
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

    base_width_mm: float = 0.0
    """该名字实际使用的底座宽度（Y 向）。

    通常等于 ``spec.base_width_mm``；名字里的墨迹太高（g/y/p 下沉）
    且开启了逐名加宽时，会单独变宽。
    """

    status: str = "ok"
    notes: list[str] = field(default_factory=list)
    limit_mm: float = 0.0
    """底座长度上限（``spec.max_width_mm``），方便界面直接取用。"""

    fill_ratio: float = 0.0
    """文字宽占上限的比例。短名字会明显小于 1，这是正常的。"""

    letter_x: list[float] = field(default_factory=list)
    """逐字等距排布时每个字符的位置（advance 原点，相对文字中心）。

    空表示按字体原本的字距排布（``text(spacing=...)``）。
    """

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


def _v_boxes(metrics: FaceMetrics, text: str) -> list[tuple[int, int]]:
    if not text or not metrics.upem:
        return []
    return [metrics.v_bboxes[ord(ch)] for ch in text if ord(ch) in metrics.v_bboxes]


def ink_ratio(metrics: FaceMetrics, text: str = "") -> float:
    """文字墨迹高度相对 em 的比例 —— 判断「字装不装得下」的唯一正确度量。

    文字是垂直居中的，占的是墨迹包围盒（含圆形字母的 overshoot、
    含 g/y/p 的下沉部分），所以直接量这个高度。
    传空字符串时用大写字母集合估字体的一般情况。

    **一个字都没有的文字（如中文名）不能拿大写字母集合顶替** ——
    那会算出 6.85mm 这种虚高值，触发「底座不够宽」的假警报，而这类名字
    本来就会被判为缺字跳过。这里直接退回 cap_ratio，不让它参与判断。
    """
    boxes = _v_boxes(metrics, text)
    if text and not boxes:
        return metrics.cap_ratio()
    boxes = boxes or _v_boxes(metrics, UPPERCASE_SAMPLE)
    if boxes and metrics.upem:
        y_min = min(b[0] for b in boxes)
        y_max = max(b[1] for b in boxes)
        return (y_max - y_min) / metrics.upem
    return metrics.cap_ratio()


def ink_height_mm(metrics: FaceMetrics, text: str, size_mm: float) -> float:
    """文字在给定字号下的墨迹高度（毫米）。"""
    return ink_ratio(metrics, text) * size_mm * INK_SCALE


def has_descender(metrics: FaceMetrics, text: str) -> bool:
    """文字里有没有沉到基线以下的字母（g / y / p / q / j）。"""
    return any(b[0] < 0 for b in _v_boxes(metrics, text))


def text_offset_y(metrics: FaceMetrics, text: str, size_mm: float) -> float:
    """把整串文字的墨迹垂直中心移到 y=0 所需的平移量（毫米）。

    OpenSCAD 的 ``valign="center"`` 是按字体 ascent/descent 居中的，
    对整体上移过的自定义字体（如 Daziji 系列）会明显偏上；
    因此模板改用 ``valign="baseline"``，再由本函数按实际墨迹包围盒精确居中。
    """
    if not metrics.upem or not text:
        return 0.0
    return -metrics.ink_y_center(text) / metrics.upem * size_mm * INK_SCALE


def letter_positions(
    metrics: FaceMetrics,
    text: str,
    size_mm: float,
    spacing: float = 1.0,
    weight_offset_mm: float = 0.0,
) -> list[float]:
    """逐字等距排布时，每个字符的 advance 原点相对文字中心的 X 偏移（毫米）。

    等宽字体只保证「占位相同」，不保证「墨迹间隙相同」——
    M 墨迹 5.07mm 几乎占满格子、A 只有 4.59mm 还偏左，
    结果 A→M 间隙 1.10mm、M→A 是 -0.17mm（重叠）。

    这里改用视觉等距：**总宽完全不变**（等于 :func:`predict_width`，
    所以底座长度、限宽判断都不用改），只是把间隙重新平均分配：

        gap = (总宽 - Σ墨迹宽) / (字符数 - 1)

    返回的位置是 OpenSCAD ``text(halign="left")`` 需要的 advance 原点，
    直接 ``translate([x, 0])`` 即可。
    """
    text = (text or "").strip()
    if not text:
        return []
    weight = max(0.0, weight_offset_mm)
    scale = size_mm * INK_SCALE

    x_mins: list[float] = []
    widths: list[float] = []
    for ch in text:
        box = metrics.bboxes.get(ord(ch))
        x_min = box[0] / metrics.upem * scale if box else 0.0
        x_max = box[1] / metrics.upem * scale if box else 0.0
        x_mins.append(x_min)
        widths.append(max(0.0, x_max - x_min))

    total = predict_width(metrics, text, size_mm, spacing, weight)
    if total <= 0:
        return []

    if len(text) == 1:
        # 单字符没有间隙，只要墨迹居中
        return [-(widths[0] + 2.0 * weight) / 2.0 - x_mins[0] + weight]

    cell = [w + 2.0 * weight for w in widths]
    gap = (total - sum(cell)) / (len(text) - 1)
    positions: list[float] = []
    cursor = -total / 2.0
    for i in range(len(text)):
        # cursor 是「含加粗的墨迹左边界」，换算成 advance 原点
        positions.append(cursor - x_mins[i] + weight)
        cursor += cell[i] + gap
    return positions


def size_cap_from_base(metrics: FaceMetrics, spec: StampSpec, text: str = "") -> float:
    """由底座宽度反推字号硬上限。

    墨迹高（含加粗外扩 2 × weight）不得超过底座宽度，否则字母会悬在底座外。
    这是**唯一**一条压字号的几何约束 —— 不再额外留 edge 余量，否则
    「6mm 字号配 6mm 底座」这种一直能打的组合会被莫名其妙压小。

    ``text`` 为空时按该字体的大写字母集合估算。
    """
    ratio = ink_ratio(metrics, text)
    if ratio <= 0:
        return float("inf")
    usable = spec.base_width_mm - 2.0 * max(0.0, spec.weight_offset_mm)
    if usable <= 0:
        return 0.0
    return usable / (ratio * INK_SCALE)


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


def _blank(
    spacing: float, limit: float, base_width: float, status: str, message: str
) -> FitResult:
    """无解时的占位结果（空名字 / 缺字 / 参数无效）。"""
    return FitResult(
        size_mm=0.0,
        spacing=spacing,
        width_mm=0.0,
        base_len_mm=0.0,
        base_width_mm=base_width,
        status=status,
        notes=[message],
        limit_mm=limit,
    )


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

    base_width = spec.base_width_mm

    if not text:
        return _blank(spacing0, limit, base_width, "empty", "名字为空")

    missing = metrics.missing_chars(text)
    if missing:
        return _blank(
            spacing0, limit, base_width, "missing_glyph", f"当前字体缺少字符：{''.join(missing)}"
        )

    if limit <= 0:
        return _blank(
            spacing0,
            limit,
            base_width,
            "invalid",
            f"左右留白 2 × {spec.margin_mm:g}mm 已占满上限 {spec.max_width_mm:g}mm，请加大上限",
        )

    k, c = ink_linear(metrics, text)
    if k <= 0 and c <= 0:
        return _blank(spacing0, limit, base_width, "invalid", "字体度量为空")

    scale = width_scale if width_scale > 0 else 1.0
    # 预测宽 × scale ≤ limit  ⇔  预测宽 ≤ limit / scale
    eff_limit = limit / scale

    def width_at(size: float, spacing: float) -> float:
        return predict_width(metrics, text, size, spacing, weight)

    notes: list[str] = []
    status = "ok"
    size = spec.font_size_mm
    spacing = spacing0

    # ---- 第一步：墨迹高度不得超过底座宽 ----
    ink = ink_height_mm(metrics, text, size)
    total = ink + 2.0 * weight
    if total > spec.base_width_mm + GEOMETRY_TOLERANCE_MM:
        shape = f"墨迹高 {ink:.2f}mm" + (
            f" 加加粗 {2.0 * weight:.2f}mm 共 {total:.2f}mm" if weight > 0 else ""
        )
        if has_descender(metrics, text):
            shape += "（含下沉字母 g/y/p）"
        if spec.widen_base_per_name:
            # 字号是视觉主体：宁可让这一枚印章胖一点，也不把它压小。
            # 向上取整到 0.1mm，再留 0.05mm 避免墨迹正好贴边。
            base_width = math.ceil((total + 0.05) * 10) / 10
            status = _worse(status, "wider_base")
            notes.append(
                f"{shape}，超过默认底座宽度 {spec.base_width_mm:.2f}mm，"
                f"已把这一枚的底座加宽到 {base_width:.1f}mm（字号保持 {size:.2f}mm）"
            )
        else:
            size = size_cap_from_base(metrics, spec, text)
            status = _worse(status, "size_capped")
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
    # 视觉等距：总宽不变，只重排间隙，保证打印出来字符间距一致
    letter_x = (
        letter_positions(metrics, text, size, spacing, weight)
        if spec.even_spacing
        else []
    )
    fill = width / limit if limit > 0 else 0.0

    return FitResult(
        size_mm=round(size, 3),
        spacing=round(spacing, 3),
        width_mm=round(width, 3),
        base_len_mm=round(base_len, 3),
        base_width_mm=round(base_width, 3),
        status=status,
        notes=notes,
        limit_mm=limit,
        fill_ratio=round(fill, 4),
        letter_x=[round(v, 4) for v in letter_x],
    )
