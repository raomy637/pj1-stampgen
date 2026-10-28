"""名字清单预检：大小写转换、重复、超长、缺字、异常字符。

另含参数之间的逻辑约束校验（:func:`check_spec`）——
字号、底座宽度、留白、上限这几个数不是独立的，界面要在参数区直接提示。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .config import CASE_MODES, StampSpec
from .fonts import FaceMetrics

ERROR = "error"
WARN = "warn"

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
    """拆成 (首次出现的名字, 重复出现的名字)，保持原始顺序。"""
    seen: set[str] = set()
    unique: list[str] = []
    duplicates: list[str] = []
    for name in names:
        if name in seen:
            duplicates.append(name)
        else:
            seen.add(name)
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

    for name in names:
        found: list[Issue] = []
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            found.append(Issue(ERROR, "duplicate", f"与本批次第 {seen[name] - 1} 条重复，已跳过"))

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


def check_spec(metrics: FaceMetrics | None, spec: StampSpec) -> list[SpecIssue]:
    """检查参数之间的逻辑约束，按严重程度排序（错误在前）。

    这些约束不是拍脑袋定的，都能算出具体数字，所以每条都带上建议值，
    界面可以直接给一个「采用」按钮。
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
        # 3) 字高超过底座宽度 → 生成时会自动压字号
        cap = m.cap_height_mm(metrics, spec.font_size_mm)
        if cap + 2.0 * weight > spec.base_width_mm + m.GEOMETRY_TOLERANCE_MM:
            cap_limit = m.size_cap_from_base(metrics, spec)
            need = round(cap + 2.0 * weight + 0.1, 1)
            found.append(
                SpecIssue(
                    WARN,
                    "cap_over_base",
                    f"当前字体 {spec.font_size_mm:g}mm 字号字高 {cap:.2f}mm"
                    f"（含加粗 {2.0 * weight:.2f}mm）超过底座宽度 "
                    f"{spec.base_width_mm:g}mm，会自动压到 {cap_limit:.2f}mm。"
                    f"建议底座宽度 ≥ {need:g}mm",
                    {"base_width_mm": need},
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

    found.sort(key=lambda i: 0 if i.is_error else 1)
    return found


def has_blocking_spec_issue(issues: list[SpecIssue]) -> bool:
    return any(i.is_error for i in issues)
