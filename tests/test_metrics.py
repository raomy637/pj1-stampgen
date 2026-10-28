"""字宽模型与自适应拟合的单元测试。

基准数据来自在 OpenSCAD 2021.01 上的实测（Daziji_V5，size=10，spacing=1.0）。
"""

from __future__ import annotations

import pytest

from stampgen import metrics
from stampgen.config import StampSpec

# name -> 实测墨迹宽度(mm)，size=10，spacing=1.0
MEASURED = {
    "A": 7.649,
    "AA": 16.259,
    "BELLA": 41.67,
    "GRACIE": 50.56,
}


def test_ink_linear_single_char_has_no_advance_term(metrics_of):
    k, c = metrics.ink_linear(metrics_of, "A")
    assert k == 0.0
    assert c > 0.4  # A 的字面宽度约 0.55 em


def test_ink_linear_grows_with_length(metrics_of):
    k1, _ = metrics.ink_linear(metrics_of, "AB")
    k2, _ = metrics.ink_linear(metrics_of, "ABC")
    assert k2 > k1


@pytest.mark.parametrize("name,expected", MEASURED.items())
def test_predict_width_matches_measured(metrics_of, name, expected):
    predicted = metrics.predict_width(metrics_of, name, size_mm=10.0, spacing=1.0)
    assert predicted == pytest.approx(expected, rel=0.01)


def test_size_limit_respects_base_width(metrics_of, spec):
    limit = metrics.size_limit_from_geometry(metrics_of, spec)
    cap = metrics.cap_height_mm(metrics_of, limit)
    assert cap == pytest.approx(spec.base_width_mm - 2 * spec.edge_mm, rel=0.02)


def test_size_bounds_never_inverted(metrics_of):
    spec = StampSpec(min_size_mm=8.0, max_size_mm=2.0)
    lo, hi = metrics.size_bounds(metrics_of, spec)
    assert lo <= hi


def test_fit_fills_available_width(metrics_of, spec):
    fit = metrics.fit(metrics_of, "BELLA", spec)
    assert fit.status == "ok"
    assert fit.width_mm == pytest.approx(spec.available_mm(), rel=0.02)


def test_fit_short_name_underfills(metrics_of, spec):
    fit = metrics.fit(metrics_of, "AVA", spec)
    assert fit.status == "underfill"
    assert fit.fill_ratio < 1.0
    assert fit.spacing == pytest.approx(spec.max_spacing)
    # 提示里要给出可执行的下一步，而不只是"填不满"
    assert any("建议目标宽度改为约" in n for n in fit.notes)


def test_fit_long_name_reports_suggestion(metrics_of, spec):
    fit = metrics.fit(metrics_of, "AUDREY  HEPBURN", spec)
    assert fit.status in {"too_long", "spacing_min"}
    if fit.status == "too_long":
        assert any("建议底座宽度" in n for n in fit.notes)


def test_fit_empty_name(metrics_of, spec):
    fit = metrics.fit(metrics_of, "   ", spec)
    assert fit.status == "empty"
    assert not fit.ok


def test_fit_missing_glyph(metrics_of, spec):
    fit = metrics.fit(metrics_of, "名字", spec)
    assert fit.status == "missing_glyph"


def test_fit_invalid_when_margin_too_large(metrics_of):
    spec = StampSpec(target_width_mm=10.0, margin_mm=6.0)
    fit = metrics.fit(metrics_of, "BELLA", spec)
    assert fit.status == "invalid"


def test_weight_offset_widens(metrics_of):
    plain = metrics.predict_width(metrics_of, "BELLA", 5.0, 1.0, 0.0)
    bold = metrics.predict_width(metrics_of, "BELLA", 5.0, 1.0, 0.2)
    assert bold - plain == pytest.approx(0.4, abs=1e-6)


def test_size_from_probe_is_linear():
    assert metrics.size_from_probe(20.0, 10.0, 30.0) == pytest.approx(15.0)
    assert metrics.size_from_probe(0.0, 10.0, 30.0) == 0.0


def test_resolve_curve_prefers_explicit_values(face, spec):
    spec.curve_fa = 7.0
    spec.curve_fs = 1.5
    assert metrics.resolve_curve(face, spec) == (7.0, 1.5)


def test_resolve_curve_auto_for_dense_font(face, spec):
    if not face.is_dense_outline:
        pytest.skip("该字体不是密集轮廓")
    assert metrics.resolve_curve(face, spec) == metrics.CURVE_DENSE


# ---------------- 固定字号模式（auto）----------------


def test_fit_auto_keeps_requested_size(metrics_of, spec):
    """字高装得下就必须保留用户给的字号，不能按 edge 余量偷偷压小。

    旧版一直是"字号 = 底座宽"这种贴边用法，字高通常略小于底座宽就能打印。
    这里若按 edge_mm=0.2 的舒适余量去压，成品就和旧版对不上了。
    """
    spec.width_mode = "auto"
    spec.auto_size_mm = 6.0
    # 底座宽度按该字体的实际字高给（不同字体字高比不同，不能写死 6.0）
    spec.base_width_mm = metrics.cap_height_mm(metrics_of, 6.0) + 0.1

    fit = metrics.fit_auto(metrics_of, "BELLA", spec)
    assert fit.size_mm == pytest.approx(6.0)
    assert fit.status == "ok"
    assert metrics.cap_height_mm(metrics_of, fit.size_mm) <= spec.base_width_mm


def test_fit_auto_caps_when_base_too_narrow(metrics_of):
    spec = StampSpec(width_mode="auto", auto_size_mm=9.0, base_width_mm=6.0)
    fit = metrics.fit_auto(metrics_of, "BELLA", spec)
    assert fit.status == "size_capped"
    assert fit.size_mm < 9.0
    # 提示必须告诉用户把底座加宽到多少才能用回原字号
    assert any("底座宽度加到" in n for n in fit.notes)


def test_fit_auto_size_stays_constant_across_names(metrics_of, spec):
    spec.width_mode = "auto"
    short = metrics.fit_auto(metrics_of, "AVA", spec)
    long = metrics.fit_auto(metrics_of, "GRACIE", spec)
    assert short.size_mm == pytest.approx(long.size_mm)
    assert long.base_len_mm > short.base_len_mm


def test_fit_auto_spacing_and_weight_widen(metrics_of, spec):
    spec.width_mode = "auto"
    spec.auto_spacing = 1.0
    base = metrics.fit_auto(metrics_of, "BELLA", spec).width_mm

    spec.auto_spacing = 1.4
    wider = metrics.fit_auto(metrics_of, "BELLA", spec).width_mm
    assert wider > base

    spec.auto_spacing = 1.0
    spec.weight_offset_mm = 0.2
    bold = metrics.fit_auto(metrics_of, "BELLA", spec).width_mm
    assert bold - base == pytest.approx(0.4, abs=1e-6)


def test_fit_auto_margin_widens_base(metrics_of, spec):
    spec.width_mode = "auto"
    spec.margin_mm = 1.5
    tight = metrics.fit_auto(metrics_of, "BELLA", spec).base_len_mm
    spec.margin_mm = 6.0
    loose = metrics.fit_auto(metrics_of, "BELLA", spec).base_len_mm
    assert loose - tight == pytest.approx(9.0)


def test_fit_auto_rejects_missing_glyph(metrics_of, spec):
    spec.width_mode = "auto"
    fit = metrics.fit_auto(metrics_of, "名字", spec)
    assert fit.status == "missing_glyph"
    assert not fit.ok


def test_fit_auto_empty(metrics_of, spec):
    spec.width_mode = "auto"
    assert metrics.fit_auto(metrics_of, "  ", spec).status == "empty"


def test_fit_sets_base_len_to_target(metrics_of, spec):
    """fixed 模式下底座长度恒等于目标宽度。"""
    fit = metrics.fit(metrics_of, "BELLA", spec)
    assert fit.base_len_mm == pytest.approx(spec.target_width_mm)
