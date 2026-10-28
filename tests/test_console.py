"""控制台对齐工具测试。"""

from __future__ import annotations

from stampgen import console


def test_display_width_counts_cjk_as_two():
    assert console.display_width("abc") == 3
    assert console.display_width("正常") == 4
    assert console.display_width("已缩字") == 6


def test_pad_aligns_by_display_width():
    assert console.display_width(console.pad("正常", 8)) == 8
    assert console.display_width(console.pad("已缩字", 8)) == 8
    assert console.pad("ab", 4, "right") == "  ab"


def test_truncate_keeps_budget():
    out = console.truncate("abcdefghij", 5)
    assert console.display_width(out) <= 5
    assert out.endswith("…")
    assert console.truncate("abc", 5) == "abc"
