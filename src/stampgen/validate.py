"""名字清单预检：大小写转换、重复、超长、缺字、异常字符。

另含参数之间的逻辑约束校验（:func:`check_spec`）——
字号、底座宽度、留白、上限这几个数不是独立的，界面要在参数区直接提示。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .config import CASE_MODES, StampSpec
from .fonts import FaceMetrics

ERROR = "error"
WARN = "warn"
INFO = "info"
"""提示级别。

* ``ERROR`` 红：参数自相矛盾，拒绝生成
* ``WARN`` 橙：会自动处理，但用户最好知道
* ``INFO`` 灰蓝：已经处理好了，纯告知
"""

#: 校验「上限是不是定得太小」时用的样本文本：三个最宽的字母。
#: 连 MMM 都放不下，说明任何 3 字母以上的名字都会被大幅缩字。
SAMPLE_TEXT = "MMM"


@dataclass
class Issue:
    level: str
    code: str
    message: str

    @property
    def is_error(self) -> bool:
        return self.level == ERROR


@dataclass
class SpecIssue:
    """参数约束问题。``fix`` 给出「一键采用」要改的字段与目标值。"""

    level: str
    code: str
    message: str
    fix: dict[str, Any] = field(default_factory=dict)
    action_label: str = "采用"
    """按钮文字。个别名字加宽时改成「统一为 7.20mm」，让用户点之前就知道影响全部。"""

    @property
    def is_error(self) -> bool:
        return self.level == ERROR

    @property
    def fixable(self) -> bool:
        return bool(self.fix)


def normalize_names(raw: Iterable[str]) -> list[str]:
    """去空白、去空行，保持原始顺序。"""
    result: list[str] = []
    for line in raw:
        name = (line or "").strip()
        if name:
            result.append(name)
    return result


def _capitalize_word(match: re.Match[str]) -> str:
    word = match.group(0)
    return word[:1].upper() + word[1:].lower()


def apply_case(names: Iterable[str], mode: str) -> list[str]:
    """按 ``mode`` 转换大小写，保持顺序与空行处理不变。

    * ``keep``：原样
    * ``upper``：全部大写
    * ``lower``：全部小写
    * ``capitalize``：每个空格分隔的词首字母大写，其余小写
      （``mary jane`` → ``Mary Jane``；连字符算同一个词）
    """
    if mode not in CASE_MODES:
        mode = "keep"
    result: list[str] = []
    for name in names:
        if mode == "upper":
            result.append(name.upper())
        elif mode == "lower":
            result.append(name.lower())
        elif mode == "capitalize":
            result.append(re.sub(r"\S+", _capitalize_word, name))
        else:
            result.append(name)
    return result


def dedupe(names: Iterable[str]) -> tuple[list[str], list[str]]:
    """拆成 (首次出现的名字, 重复出现的名字)，保持原始顺序。

    **按大小写不敏感比较** —— 输出文件是 ``<名字>.stl``，而 Windows / macOS
    的文件名不区分大小写，``DAISY`` 和 ``Daisy`` 会写进同一个文件，
    后一个把前一个覆盖掉（清单 8 个、实际只剩 7 个 STL）。
    """
    seen: dict[str, str] = {}
    unique: list[str] = []
    duplicates: list[str] = []
    for name in names:
        key = name.casefold()
        if key in seen:
            duplicates.append(name)
        else:
            seen[key] = name
            unique.append(name)
    return unique, duplicates


def validate_batch(
    names: list[str],
    metrics: FaceMetrics,
    spec: StampSpec,
) -> dict[str, list[Issue]]:
    """逐个名字给出问题清单。同名多次出现时只保留第一条。"""
    issues: dict[str, list[Issue]] = {}
    seen: dict[str, int] = {}
    first_seen: dict[str, str] = {}

    for name in names:
        found: list[Issue] = []
        key = name.casefold()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            previous = first_seen[key]
            if previous == name:
                message = f"与本批次第 {seen[key] - 1} 条重复，已跳过"
            else:
                # 大小写不同也会写进同一个文件（Windows 不区分），必须算重复
                message = f"与「{previous}」仅大小写不同，文件名会冲突，已跳过"
            found.append(Issue(ERROR, "duplicate", message))
        else:
            first_seen[key] = name

        if not name:
            found.append(Issue(ERROR, "empty", "名字为空"))
        else:
            if len(name) > spec.max_chars:
                found.append(
                    Issue(ERROR, "too_many_chars", f"{len(name)} 个字符，超过上限 {spec.max_chars}")
                )
            if name != name.strip():
                found.append(Issue(WARN, "whitespace", "首尾含空格，已自动去除"))
            if "  " in name:
                found.append(Issue(WARN, "double_space", "含连续空格"))
            if any(ord(ch) < 32 for ch in name):
                found.append(Issue(ERROR, "control_char", "含不可见控制字符"))
            if any(ord(ch) > 127 for ch in name):
                found.append(Issue(ERROR, "non_ascii", "含非 ASCII 字符，字体可能缺字"))
            missing = metrics.missing_chars(name)
            if missing:
                found.append(
                    Issue(ERROR, "missing_glyph", f"字体缺少字符：{''.join(missing)}")
                )

        issues[name] = found

    return issues


def blocking_issues(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.is_error]


def format_issues(issues: list[Issue]) -> str:
    return "；".join(i.message for i in issues)


# ---------------------------------------------------------------- 参数约束


def check_spec(
    metrics: FaceMetrics | None, spec: StampSpec, names: Iterable[str] | None = None
) -> list[SpecIssue]:
    """检查参数之间的逻辑约束，按严重程度排序（错误在前）。

    这些约束不是拍脑袋定的，都能算出具体数字，所以每条都带上建议值，
    界面可以直接给一个「采用」按钮。

    「墨迹高度装不下底座」这条必须拿**具体名字**来算 —— 字有多高取决于
    名字里有哪些字母（g/y/p 有下沉、Q 的尾巴到基线、V 比 W 高一截），
    用一个固定样本估只会误报。所以 ``names`` 为空时跳过这条。
    """
    from . import metrics as m

    found: list[SpecIssue] = []
    weight = max(0.0, spec.weight_offset_mm)

    # 1) 留白挤掉了全部可用宽度
    if 2.0 * spec.margin_mm >= spec.max_width_mm:
        suggest = round(2.0 * spec.margin_mm + 20.0, 1)
        found.append(
            SpecIssue(
                ERROR,
                "margin_eats_all",
                f"左右留白各 {spec.margin_mm:g}mm，已经占满上限 {spec.max_width_mm:g}mm，"
                f"文字没有位置可放。建议把上限加到 {suggest:g}mm",
                {"max_width_mm": suggest},
            )
        )

    # 2) 几何加粗过量：offset(delta) 是两侧同时外扩，会把内孔吃掉
    if weight > 0.3:
        found.append(
            SpecIssue(
                ERROR,
                "weight_too_much",
                f"几何加粗 {weight:g}mm 超过安全上限 0.3mm，A/O/e 的内孔会被糊死。"
                f"建议改为 0.3mm",
                {"weight_offset_mm": 0.3},
            )
        )

    if metrics is not None:
        # 3) 墨迹高度超过底座宽度 —— 只统计真会生成的名字
        usable = renderable_names(names or [], metrics, spec)
        need_wider = _names_needing_wider_base(usable, metrics, spec)
        if need_wider:
            widest_total, widest_name = need_wider[0]
            widest = math.ceil((widest_total + 0.05) * 10) / 10
            count = len(need_wider)
            if spec.widen_base_per_name:
                # 已经自动加宽了，这条只是告知，不该让用户觉得要做什么
                # 只有 1 个名字特殊，不算「全局值设小了」；至少 2 个且过半才算
                majority = count >= 2 and count * 2 >= len(usable)
                if majority:
                    text = (
                        f"{len(usable)} 个名字里 {count} 个需要更宽的底座"
                        f"（最大 {widest:.2f}mm），建议整体调大底座宽度"
                    )
                    level = WARN
                else:
                    text = (
                        f"{len(usable)} 个名字里 {count} 个需要更宽的底座："
                        f"{widest_name} → {widest:.2f}mm"
                        f"（其余用 {spec.base_width_mm:g}mm，字号不变）"
                    )
                    level = INFO
                found.append(
                    SpecIssue(
                        level,
                        "base_widened",
                        text,
                        {"base_width_mm": widest},
                        action_label=f"统一为 {widest:.2f}mm",
                    )
                )
            else:
                cap_limit = m.size_cap_from_base(metrics, spec, widest_name)
                found.append(
                    SpecIssue(
                        WARN,
                        "cap_over_base",
                        f"{len(usable)} 个名字里 {count} 个装不下（{widest_name} 需要 "
                        f"{widest:.2f}mm），会缩字号到 {cap_limit:.2f}mm。"
                        f"建议把底座宽度改为 {widest:.2f}mm",
                        {"base_width_mm": widest},
                    )
                )

        # 4) 上限定得太小 → 会大量缩字
        sample = m.predict_width(metrics, SAMPLE_TEXT, spec.font_size_mm, spec.letter_spacing, weight)
        sample_base = spec.base_len_for(sample)
        if sample_base > spec.max_width_mm + 1e-9:
            suggest = round(sample_base + 2.0, 1)
            found.append(
                SpecIssue(
                    WARN,
                    "max_width_too_small",
                    f"上限 {spec.max_width_mm:g}mm 太小：{spec.font_size_mm:g}mm 字号下"
                    f"连 {SAMPLE_TEXT} 三个字母都需要 {sample_base:.1f}mm，"
                    f"生成时会大量缩字。建议上限 ≥ {suggest:g}mm",
                    {"max_width_mm": suggest},
                )
            )

    # 5) 文字挤出高度过高 → 印章会很厚
    if spec.letter_height_mm > 1.5 * spec.base_height_mm:
        found.append(
            SpecIssue(
                WARN,
                "letter_height_too_tall",
                f"文字高度 {spec.letter_height_mm:g}mm 超过底座高度 "
                f"{spec.base_height_mm:g}mm 的 1.5 倍，印章会明显偏高。"
                f"建议不超过 {spec.base_height_mm * 1.5:g}mm",
                {"letter_height_mm": round(spec.base_height_mm * 1.5, 1)},
            )
        )

    # 6) 间距下限高于设定间距（用户把间距调得比下限还紧）
    if spec.letter_spacing < spec.min_spacing:
        found.append(
            SpecIssue(
                WARN,
                "spacing_below_floor",
                f"字间距 {spec.letter_spacing:g} 已经比压缩下限 {spec.min_spacing:g} 更紧，"
                f"超宽时没有压缩余量",
                {},
            )
        )

    order = {ERROR: 0, WARN: 1, INFO: 2}
    found.sort(key=lambda i: order.get(i.level, 3))
    return found


def has_blocking_spec_issue(issues: list[SpecIssue]) -> bool:
    return any(i.is_error for i in issues)


def renderable_names(
    names: Iterable[str], fm: FaceMetrics, spec: StampSpec
) -> list[str]:
    """只留真会生成的名字。

    参数建议必须建立在这些名字上。清单里常混进中文名、超长名、
    字体没有字形的名字，它们会被跳过、根本不参与渲染，
    拿它们算字高只会制造假警报。
    """
    usable: list[str] = []
    for name in names:
        if not name or len(name) > spec.max_chars:
            continue
        if any(ord(ch) < 32 or ord(ch) > 127 for ch in name):
            continue
        if fm.missing_chars(name):
            continue
        usable.append(name)
    return usable


def _names_needing_wider_base(
    names: list[str], fm: FaceMetrics, spec: StampSpec
) -> list[tuple[float, str]]:
    """装不下当前底座宽度的名字，按需要宽度从大到小排。

    返回 ``[(墨迹高 + 2×加粗, 名字), ...]``。
    """
    from . import metrics as m

    weight = max(0.0, spec.weight_offset_mm)
    limit = spec.base_width_mm + m.GEOMETRY_TOLERANCE_MM
    result: list[tuple[float, str]] = []
    for name in names:
        total = m.ink_height_mm(fm, name, spec.font_size_mm) + 2.0 * weight
        if total > limit:
            result.append((total, name))
    result.sort(reverse=True)
    return result
