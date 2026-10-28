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
