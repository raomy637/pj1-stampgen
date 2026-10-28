"""名字清单预检：重复、超长、缺字、异常字符。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .config import StampSpec
from .fonts import FaceMetrics

ERROR = "error"
WARN = "warn"


@dataclass
class Issue:
    level: str
    code: str
    message: str

    @property
    def is_error(self) -> bool:
        return self.level == ERROR


def normalize_names(raw: Iterable[str]) -> list[str]:
    """去空白、去空行，保持原始顺序。"""
    result: list[str] = []
    for line in raw:
        name = (line or "").strip()
        if name:
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
