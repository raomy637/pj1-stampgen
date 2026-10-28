"""名字预检与参数约束测试。"""

from __future__ import annotations

import pytest

from stampgen import metrics, validate
from stampgen.config import StampSpec


# ---------------- 名字预检 ----------------


def test_normalize_drops_blank_lines():
    assert validate.normalize_names([" A ", "", "B", "   "]) == ["A", "B"]


def test_duplicate_is_error(metrics_of, spec):
    issues = validate.validate_batch(["BELLA", "BELLA"], metrics_of, spec)
    assert any(i.code == "duplicate" for i in issues["BELLA"])


def test_too_many_chars(metrics_of):
    spec = StampSpec(max_chars=5)
    issues = validate.validate_batch(["ABCDEFG"], metrics_of, spec)
    assert any(i.code == "too_many_chars" for i in issues["ABCDEFG"])


def test_non_ascii_rejected(metrics_of, spec):
    issues = validate.validate_batch(["小美"], metrics_of, spec)
    codes = {i.code for i in issues["小美"]}
    assert "non_ascii" in codes


def test_double_space_warns(metrics_of, spec):
    issues = validate.validate_batch(["MOO  DENG"], metrics_of, spec)
    assert any(i.code == "double_space" for i in issues["MOO  DENG"])
    assert not validate.blocking_issues(issues["MOO  DENG"])


def test_missing_glyph_detected(metrics_of, spec):
    issues = validate.validate_batch(["BELLA\u2603"], metrics_of, spec)
    assert any(i.code == "missing_glyph" for i in issues["BELLA\u2603"])


def test_dedupe_keeps_first_occurrence():
    unique, duplicates = validate.dedupe(["A", "B", "A", "C", "B"])
    assert unique == ["A", "B", "C"]
    assert duplicates == ["A", "B"]


def test_clean_name_has_no_blocking_issues(metrics_of, spec):
    issues = validate.validate_batch(["BELLA"], metrics_of, spec)
    assert validate.blocking_issues(issues["BELLA"]) == []


# ---------------- 大小写转换 ----------------


def test_apply_case_keep():
    assert validate.apply_case(["tess", "Mary Jane"], "keep") == ["tess", "Mary Jane"]


def test_apply_case_upper():
    assert validate.apply_case(["tess", "Mary Jane"], "upper") == ["TESS", "MARY JANE"]


def test_apply_case_lower():
    assert validate.apply_case(["TESS", "Mary Jane"], "lower") == ["tess", "mary jane"]


def test_apply_case_capitalize():
    assert validate.apply_case(["mary jane", "TESS"], "capitalize") == ["Mary Jane", "Tess"]


def test_apply_case_unknown_mode_falls_back_to_keep():
    assert validate.apply_case(["tess"], "随便写的") == ["tess"]


def test_apply_case_preserves_order_and_count():
    names = ["a", "b", "c"]
    assert len(validate.apply_case(names, "upper")) == 3


def test_case_conversion_merges_duplicates():
    """转换后同名就该合并，否则会生成两个一样的文件。"""
    names = validate.apply_case(["tess", "TESS"], "upper")
    unique, duplicates = validate.dedupe(names)
    assert unique == ["TESS"]
    assert duplicates == ["TESS"]


# ---------------- 参数约束 ----------------


def _codes(issues):
    return {i.code for i in issues}


def test_check_spec_clean_defaults(metrics_of):
    """默认参数本身自洽：底座宽度按该字体的实际字高给足。"""
    spec = StampSpec()
    spec.base_width_mm = metrics.cap_height_mm(metrics_of, spec.font_size_mm) + 0.2
    assert validate.check_spec(metrics_of, spec) == []


def test_check_spec_flags_default_6mm_base_for_tall_font(metrics_of):
    """字高比 0.803 的字体，6mm 字号字高 6.43mm，6mm 底座确实装不下。"""
    spec = StampSpec(font_size_mm=6.0, base_width_mm=6.0)
    if metrics.cap_height_mm(metrics_of, 6.0) <= 6.0:
        pytest.skip("该字体 6mm 字号字高不超过 6mm")
    assert "cap_over_base" in _codes(validate.check_spec(metrics_of, spec))


def test_check_spec_margin_eats_all_width(metrics_of):
    spec = StampSpec(max_width_mm=10.0, margin_mm=6.0)
    issues = validate.check_spec(metrics_of, spec)
    assert "margin_eats_all" in _codes(issues)
    first = issues[0]
    assert first.is_error
    assert first.fixable and "max_width_mm" in first.fix


def test_check_spec_weight_over_limit(metrics_of):
    issues = validate.check_spec(metrics_of, StampSpec(weight_offset_mm=0.5))
    assert "weight_too_much" in _codes(issues)
    fix = next(i.fix for i in issues if i.code == "weight_too_much")
    assert fix["weight_offset_mm"] == 0.3


def test_check_spec_cap_over_base_width(metrics_of):
    """6mm 字号字高 6.43mm，6mm 底座装不下 —— 必须提示并给出建议底座宽度。"""
    spec = StampSpec(font_size_mm=6.0, base_width_mm=6.0)
    issues = validate.check_spec(metrics_of, spec)
    issue = next(i for i in issues if i.code == "cap_over_base")
    assert not issue.is_error
    cap = metrics.cap_height_mm(metrics_of, 6.0)
    if cap > 6.0:
        assert issue.fix["base_width_mm"] > 6.0
        assert f"{cap:.2f}" in issue.message


def test_check_spec_no_cap_warning_when_base_is_wide(metrics_of):
    spec = StampSpec(font_size_mm=6.0, base_width_mm=metrics.cap_height_mm(metrics_of, 6.0) + 0.2)
    assert "cap_over_base" not in _codes(validate.check_spec(metrics_of, spec))


def test_check_spec_max_width_too_small(metrics_of):
    spec = StampSpec(font_size_mm=6.0, max_width_mm=12.0)
    issues = validate.check_spec(metrics_of, spec)
    issue = next(i for i in issues if i.code == "max_width_too_small")
    assert issue.fix["max_width_mm"] > 12.0


def test_check_spec_letter_height_too_tall(metrics_of):
    spec = StampSpec(base_height_mm=6.0, letter_height_mm=12.0)
    issues = validate.check_spec(metrics_of, spec)
    issue = next(i for i in issues if i.code == "letter_height_too_tall")
    assert issue.fix["letter_height_mm"] == 9.0


def test_check_spec_spacing_below_floor(metrics_of):
    spec = StampSpec(letter_spacing=0.7, min_spacing=0.85)
    issues = validate.check_spec(metrics_of, spec)
    issue = next(i for i in issues if i.code == "spacing_below_floor")
    assert not issue.fixable  # 这条没有"正确值"可一键采用


def test_check_spec_errors_sort_first(metrics_of):
    spec = StampSpec(max_width_mm=10.0, margin_mm=6.0, letter_height_mm=99.0, base_height_mm=6.0)
    issues = validate.check_spec(metrics_of, spec)
    assert issues[0].is_error
    assert validate.has_blocking_spec_issue(issues)


def test_check_spec_without_metrics_still_checks_simple_rules():
    issues = validate.check_spec(None, StampSpec(weight_offset_mm=0.9))
    assert "weight_too_much" in _codes(issues)
