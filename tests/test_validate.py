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


def test_dedupe_is_case_insensitive():
    """Windows 文件名不区分大小写，DAISY 和 Daisy 会写进同一个文件。"""
    unique, duplicates = validate.dedupe(["DAISY", "Daisy", "daisy", "TESS"])
    assert unique == ["DAISY", "TESS"]
    assert duplicates == ["Daisy", "daisy"]


def test_case_only_duplicate_explains_why(metrics_of, spec):
    issues = validate.validate_batch(["DAISY", "Daisy"], metrics_of, spec)
    assert any("仅大小写不同" in i.message for i in issues["Daisy"])


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
    """默认参数本身自洽：底座宽度按该字体的实际墨迹高度给足。"""
    spec = StampSpec()
    spec.base_width_mm = metrics.ink_height_mm(metrics_of, "TESS", spec.font_size_mm) + 0.2
    assert validate.check_spec(metrics_of, spec, ["TESS"]) == []


def test_check_spec_clean_at_default_6mm(metrics_of):
    """默认的 6mm 字号配 6mm 底座是能打的，不该报警。"""
    spec = StampSpec(font_size_mm=6.0, base_width_mm=6.0)
    issues = validate.check_spec(metrics_of, spec, ["TESS", "DAISY", "WALKER"])
    assert "cap_over_base" not in _codes(issues)


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


def test_check_spec_reports_widened_base(metrics_of):
    """默认会自动加宽，所以这是「已经处理好了」的告知，不是催用户改。"""
    spec = StampSpec(font_size_mm=6.0)
    spec.base_width_mm = metrics.ink_height_mm(metrics_of, "BELLA", 6.0) - 0.6
    issues = validate.check_spec(metrics_of, spec, ["BELLA"])
    issue = next(i for i in issues if i.code == "base_widened")
    assert issue.level == validate.INFO
    assert not issue.is_error
    assert "BELLA" in issue.message
    assert issue.action_label.startswith("统一为")
    assert issue.fix["base_width_mm"] > spec.base_width_mm


def test_check_spec_warns_when_widen_disabled(metrics_of):
    """关掉自动加宽后才变成「会缩字号」的警告。"""
    spec = StampSpec(font_size_mm=6.0, widen_base_per_name=False)
    spec.base_width_mm = metrics.ink_height_mm(metrics_of, "BELLA", 6.0) - 0.6
    issues = validate.check_spec(metrics_of, spec, ["BELLA"])
    issue = next(i for i in issues if i.code == "cap_over_base")
    assert issue.level == validate.WARN
    assert issue.action_label == "采用"


def test_check_spec_escalates_when_most_names_need_widening(metrics_of):
    """超过半数名字都要加宽，说明全局值设小了，提示升级为警告。"""
    spec = StampSpec(font_size_mm=6.0, base_width_mm=4.0)
    issues = validate.check_spec(metrics_of, spec, ["TESS", "DAISY", "WALKER"])
    issue = next(i for i in issues if i.code == "base_widened")
    assert issue.level == validate.WARN
    assert "建议整体调大" in issue.message


def test_check_spec_no_cap_warning_when_base_is_wide(metrics_of):
    spec = StampSpec(font_size_mm=6.0)
    spec.base_width_mm = metrics.ink_height_mm(metrics_of, "BELLA", 6.0) + 0.3
    assert "base_widened" not in _codes(validate.check_spec(metrics_of, spec, ["BELLA"]))


def test_check_spec_skips_cap_check_without_names(metrics_of):
    """没有具体名字就不猜字高 —— 用固定样本估只会误报。"""
    spec = StampSpec(font_size_mm=6.0, base_width_mm=4.0)
    assert "base_widened" not in _codes(validate.check_spec(metrics_of, spec))


def test_check_spec_flags_descender_name(metrics_of):
    spec = StampSpec(font_size_mm=6.0, weight_offset_mm=0.0)
    spec.base_width_mm = metrics.ink_height_mm(metrics_of, "DAISY", 6.0) + 0.05
    issues = validate.check_spec(metrics_of, spec, ["DAISY", "Daisy"])
    issue = next(i for i in issues if i.code == "base_widened")
    assert "Daisy" in issue.message


# ---------------- 不可生成的名字不参与参数建议 ----------------


def test_renderable_names_filters_unusable(metrics_of):
    spec = StampSpec(max_chars=5)
    names = ["TESS", "方法喱", "TOOLONGNAME", "", "BELLA"]
    assert validate.renderable_names(names, metrics_of, spec) == ["TESS", "BELLA"]


def test_check_spec_ignores_unrenderable_names(metrics_of):
    """截图里的坑：中文名会被跳过，不能拿它算字高、给出假警报。"""
    spec = StampSpec(base_width_mm=6.6, font_size_mm=6.0, weight_offset_mm=0.18)
    names = ["TESS", "LEELA", "DAISY", "KHLOE", "WALKER", "LORNA", "方法喱"]
    assert validate.check_spec(metrics_of, spec, names) == []


def test_ink_ratio_does_not_inflate_missing_glyphs(metrics_of):
    """一个字形都没有时不能拿大写字母集合顶替，那会算出 6.85mm 的假数。"""
    fallback = metrics.ink_ratio(metrics_of, "方法喱")
    assert fallback == pytest.approx(metrics_of.cap_ratio())
    assert fallback < metrics.ink_ratio(metrics_of, "")


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
