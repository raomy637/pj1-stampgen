"""控制台文本对齐：中文占两列，``str.ljust`` 按字符数算不准。"""

from __future__ import annotations

import unicodedata


def display_width(text: str) -> int:
    """按终端显示列数计算宽度（全角字符算 2）。"""
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
    return width


def pad(text: str, width: int, align: str = "left") -> str:
    """按显示宽度补空格。"""
    filler = " " * max(0, width - display_width(text))
    if align == "right":
        return filler + text
    if align == "center":
        left = len(filler) // 2
        return " " * left + text + " " * (len(filler) - left)
    return text + filler


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """按显示宽度截断，超长时补省略号。"""
    if display_width(text) <= width:
        return text
    budget = width - display_width(ellipsis)
    result = ""
    used = 0
    for ch in text:
        step = 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
        if used + step > budget:
            break
        result += ch
        used += step
    return result + ellipsis
