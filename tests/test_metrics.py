"""字宽模型与限宽求解的单元测试。

基准数据来自在 OpenSCAD 2021.01 上的实测（Daziji_V5，size=10，spacing=1.0）。
"""

from __future__ import annotations

import math

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

SIZE = 6.0


@pytest.fixture()
def roomy(metrics_of) -> StampSpec:
    """底座宽度够装下 6mm 字号的参数，排除「限字高」干扰。"""
    spec = StampSpec(weight_offset_mm=0.0)
    spec.font_size_mm = SIZE
    spec.base_width_mm = metrics.ink_height_mm(metrics_of, "BELLA", SIZE) + 0.1
    return spec


# ---------------- 字宽模型 ----------------


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


def test_weight_offset_widens(metrics_of):
    plain = metrics.predict_width(metrics_of, "BELLA", 5.0, 1.0, 0.0)
    bold = metrics.predict_width(metrics_of, "BELLA", 5.0, 1.0, 0.2)
    assert bold - plain == pytest.approx(0.4, abs=1e-6)


def test_size_from_probe_is_linear():
    assert metrics.size_from_probe(20.0, 10.0, 30.0) == pytest.approx(15.0)
    assert metrics.size_from_probe(0.0, 10.0, 30.0) == 0.0


def test_probe_scale_recovers_systematic_bias(metrics_of):
    exact = metrics.predict_width(metrics_of, "BELLA", 10.0, 1.0, 0.0)
    scale = metrics.probe_scale(metrics_of, "BELLA", 1.0, exact * 1.02, 10.0)
    assert scale == pytest.approx(1.02, rel=1e-6)


# ---------------- 几何约束 ----------------


def test_size_cap_fills_base_width_exactly(metrics_of, spec):
    cap_limit = metrics.size_cap_from_base(metrics_of, spec)
    assert metrics.ink_height_mm(metrics_of, metrics.UPPERCASE_SAMPLE, cap_limit) == (
        pytest.approx(spec.base_width_mm, rel=1e-6)
    )


def test_ink_height_beats_cap_height(metrics_of):
    """真正决定装不装得下的是墨迹高度，不是「基线到大写字母顶」。

    这些字体是同一套轮廓做了不同幅度的整体上移，cap_height 差很多
    （0.70~0.85），但同一个名字的墨迹高度完全一样。
    """
    ink = metrics.ink_height_mm(metrics_of, "TESS", SIZE)
    assert 5.9 < ink < 6.3
    assert metrics.has_descender(metrics_of, "DAISY") is False
    assert metrics.has_descender(metrics_of, "Daisy") is True


def test_descender_makes_text_taller(metrics_of):
    assert metrics.ink_height_mm(metrics_of, "Daisy", SIZE) > metrics.ink_height_mm(
        metrics_of, "DAISY", SIZE
    )


def test_size_cap_subtracts_bold_expansion(metrics_of):
    """加粗会让墨迹上下各外扩 weight，上限必须跟着降（v2.1.0 这里漏算过）。"""
    plain_spec = StampSpec(weight_offset_mm=0.0)
    bold_spec = StampSpec(weight_offset_mm=0.2)
    plain = metrics.size_cap_from_base(metrics_of, plain_spec)
    bold = metrics.size_cap_from_base(metrics_of, bold_spec)
    assert bold < plain
    # 加粗 0.2 时，墨迹高 + 2×0.2 正好等于底座宽度
    assert metrics.ink_height_mm(
        metrics_of, metrics.UPPERCASE_SAMPLE, bold
    ) + 0.4 == pytest.approx(bold_spec.base_width_mm, rel=1e-6)


def test_base_len_inverts_max_text_width(spec):
    assert spec.base_len_for(spec.max_text_width()) == pytest.approx(spec.max_width_mm)


# ---------------- 限宽求解 ----------------


def test_fit_keeps_requested_size_when_it_fits(metrics_of, roomy):
    fit = metrics.fit(metrics_of, "BELLA", roomy)
    assert fit.status == "ok"
    assert fit.size_mm == pytest.approx(SIZE)
    assert fit.spacing == pytest.approx(roomy.letter_spacing)


def test_fit_short_name_is_not_padded(metrics_of, roomy):
    """3 个字母的印章就该比 8 个字母的短，不能硬撑到上限。"""
    short = metrics.fit(metrics_of, "AVA", roomy)
    long = metrics.fit(metrics_of, "GRACIE", roomy)
    assert short.status == "ok" and long.status == "ok"
    assert short.base_len_mm < long.base_len_mm < roomy.max_width_mm
    assert short.fill_ratio < 0.5


def test_fit_exactly_at_limit_stays_ok(metrics_of, roomy):
    width = metrics.predict_width(metrics_of, "BELLA", SIZE, roomy.letter_spacing, 0.0)
    roomy.max_width_mm = roomy.base_len_for(width)
    fit = metrics.fit(metrics_of, "BELLA", roomy)
    assert fit.status == "ok"
    assert fit.base_len_mm == pytest.approx(roomy.max_width_mm, abs=1e-3)


def test_fit_compresses_spacing_first(metrics_of, roomy):
    """略微超宽只压间距，字号必须保持不变。"""
    width = metrics.predict_width(metrics_of, "BELLA", SIZE, 0.92, 0.0)
    roomy.max_width_mm = roomy.base_len_for(width)

    fit = metrics.fit(metrics_of, "BELLA", roomy)
    assert fit.status == "spacing_compressed"
    assert fit.size_mm == pytest.approx(SIZE)
    assert fit.spacing == pytest.approx(0.92, abs=1e-3)
    assert fit.base_len_mm == pytest.approx(roomy.max_width_mm, abs=1e-3)
    assert fit.needs_attention
    assert any("间距" in n for n in fit.notes)


def test_fit_shrinks_size_after_spacing_floor(metrics_of, roomy):
    """间距压到下限还超宽，才缩字号。"""
    floor_width = metrics.predict_width(metrics_of, "GRACIE", SIZE, roomy.min_spacing, 0.0)
    roomy.max_width_mm = roomy.base_len_for(floor_width * 0.85)

    fit = metrics.fit(metrics_of, "GRACIE", roomy)
    assert fit.status == "size_shrunk"
    assert fit.spacing == pytest.approx(roomy.min_spacing)
    assert roomy.hard_min_size_mm < fit.size_mm < SIZE
    assert fit.base_len_mm <= roomy.max_width_mm + 1e-6
    assert any("字号再缩到" in n for n in fit.notes)


def test_fit_marks_too_long_with_suggestion(metrics_of, roomy):
    roomy.max_width_mm = 12.0
    fit = metrics.fit(metrics_of, "GRACIE", roomy)
    assert fit.status == "too_long"
    assert not fit.ok
    assert fit.size_mm == pytest.approx(roomy.hard_min_size_mm)
    assert any("建议把上限加到" in n for n in fit.notes)
    assert fit.label == "超长"


def test_fit_ignores_overshoot_within_tolerance(metrics_of):
    """圆形字母的 overshoot 是字形设计，容差以内不该动任何东西。"""
    spec = StampSpec(font_size_mm=6.0, weight_offset_mm=0.0)
    spec.base_width_mm = metrics.ink_height_mm(metrics_of, "BELLA", 6.0) - 0.1
    fit = metrics.fit(metrics_of, "BELLA", spec)
    assert fit.status == "ok"
    assert fit.size_mm == pytest.approx(6.0)
    assert fit.base_width_mm == pytest.approx(spec.base_width_mm, abs=1e-3)


# ---------------- 逐名底座宽度 ----------------


def test_fit_widens_base_instead_of_shrinking(metrics_of):
    """装不下时默认加宽底座：字号是视觉主体，不能为它让步。"""
    spec = StampSpec(font_size_mm=9.0, base_width_mm=6.0, weight_offset_mm=0.0)
    fit = metrics.fit(metrics_of, "BELLA", spec)
    assert fit.status == "wider_base"
    assert fit.size_mm == pytest.approx(9.0)
    assert fit.base_width_mm > spec.base_width_mm
    assert metrics.ink_height_mm(metrics_of, "BELLA", fit.size_mm) <= fit.base_width_mm + 1e-9


def test_widen_rounds_up_to_tenth(metrics_of):
    spec = StampSpec(font_size_mm=6.0, weight_offset_mm=0.0)
    spec.base_width_mm = metrics.ink_height_mm(metrics_of, "BELLA", 6.0) - 0.4
    fit = metrics.fit(metrics_of, "BELLA", spec)
    total = metrics.ink_height_mm(metrics_of, "BELLA", 6.0)
    assert fit.base_width_mm == pytest.approx(math.ceil((total + 0.05) * 10) / 10)


def test_other_names_keep_default_base_width(metrics_of):
    """只有装不下的那个变宽，其余仍用默认值。"""
    spec = StampSpec(font_size_mm=6.0, base_width_mm=6.6, weight_offset_mm=0.18)
    short = metrics.fit(metrics_of, "TESS", spec)
    tall = metrics.fit(metrics_of, "Daisy", spec)
    assert short.base_width_mm == pytest.approx(6.6)
    assert tall.base_width_mm > 6.6
    assert tall.size_mm == pytest.approx(short.size_mm)


def test_fit_caps_size_when_widen_disabled(metrics_of):
    spec = StampSpec(font_size_mm=9.0, base_width_mm=6.0, weight_offset_mm=0.0, widen_base_per_name=False)
    fit = metrics.fit(metrics_of, "BELLA", spec)
    assert fit.status == "size_capped"
    assert fit.size_mm < 9.0
    assert fit.base_width_mm == pytest.approx(6.0)
    assert any("底座宽度加到" in n for n in fit.notes)


def test_fit_widens_for_descender(metrics_of, roomy):
    """g/y/p 会沉到基线以下，底座得单独加宽。"""
    fit = metrics.fit(metrics_of, "Daisy", roomy)
    assert fit.status == "wider_base"
    assert fit.base_width_mm > roomy.base_width_mm
    assert any("下沉字母" in n for n in fit.notes)


def test_widen_note_mentions_bold_expansion(metrics_of):
    """加粗把墨迹顶出底座时，文案必须把加粗算进去，不能自相矛盾。"""
    spec = StampSpec(font_size_mm=6.0, weight_offset_mm=0.25)
    spec.base_width_mm = metrics.ink_height_mm(metrics_of, "BELLA", 6.0) + 0.1
    fit = metrics.fit(metrics_of, "BELLA", spec)
    assert fit.status == "wider_base"
    note = " ".join(fit.notes)
    assert "加加粗" in note and "共" in note


def test_wider_base_label_is_short(metrics_of):
    spec = StampSpec(font_size_mm=9.0, base_width_mm=6.0, weight_offset_mm=0.0)
    fit = metrics.fit(metrics_of, "BELLA", spec)
    assert fit.label == "加宽"
    assert fit.needs_attention
    assert fit.ok


def test_fit_empty_name(metrics_of, spec):
    fit = metrics.fit(metrics_of, "   ", spec)
    assert fit.status == "empty"
    assert not fit.ok


def test_fit_missing_glyph(metrics_of, spec):
    fit = metrics.fit(metrics_of, "名字", spec)
    assert fit.status == "missing_glyph"
    assert not fit.ok


def test_fit_invalid_when_margin_too_large(metrics_of):
    spec = StampSpec(max_width_mm=10.0, margin_mm=6.0, weight_offset_mm=0.0)
    fit = metrics.fit(metrics_of, "BELLA", spec)
    assert fit.status == "invalid"
    assert not fit.ok


def test_fit_respects_probe_scale(metrics_of, roomy):
    """实测比预测宽 2% 时，压缩判断也必须按实测口径来。"""
    width = metrics.predict_width(metrics_of, "BELLA", SIZE, roomy.letter_spacing, 0.0)
    roomy.max_width_mm = roomy.base_len_for(width) * 1.01  # 只留 1% 余量
    fit = metrics.fit(metrics_of, "BELLA", roomy, width_scale=1.02)
    assert fit.status != "ok"
    assert fit.base_len_mm <= roomy.max_width_mm + 1e-6


def test_fit_base_len_accounts_for_margin(metrics_of, roomy):
    fit = metrics.fit(metrics_of, "BELLA", roomy)
    assert fit.base_len_mm == pytest.approx(
        fit.width_mm + 2 * roomy.margin_mm + 2 * roomy.weight_offset_mm, abs=1e-3
    )


# ---------------- 状态与精度 ----------------


def test_every_status_has_short_label():
    for status in metrics.STATUS_LABELS:
        assert len(metrics.STATUS_LABELS[status]) <= 4


def test_detail_falls_back_to_label(metrics_of, roomy):
    """没有额外说明时，悬停提示就用短标签，不能是空串。"""
    fit = metrics.fit(metrics_of, "BELLA", roomy)
    assert fit.notes == []
    assert fit.detail == fit.label == "正常"


def test_detail_carries_reason_when_compressed(metrics_of, roomy):
    roomy.max_width_mm = 12.0
    fit = metrics.fit(metrics_of, "GRACIE", roomy)
    assert fit.detail != fit.label
    assert len(fit.detail) > len(fit.label)


def test_resolve_curve_prefers_explicit_values(face, spec):
    spec.curve_fa = 7.0
    spec.curve_fs = 1.5
    assert metrics.resolve_curve(face, spec) == (7.0, 1.5)


def test_resolve_curve_auto_for_dense_font(face, spec):
    if not face.is_dense_outline:
        pytest.skip("该字体不是密集轮廓")
    assert metrics.resolve_curve(face, spec) == metrics.CURVE_DENSE


# ---------------- 视觉等距排布 ----------------


def _gaps(metrics_of, text, size_mm, weight=0.0):
    """按 letter_positions 算出的落点，返回每对相邻字母的墨迹间隙（mm）。"""
    pos = metrics.letter_positions(metrics_of, text, size_mm, 1.0, weight)
    scale = size_mm * metrics.INK_SCALE
    gaps = []
    for i in range(len(text) - 1):
        right = pos[i] + metrics_of.bboxes[ord(text[i])][1] / metrics_of.upem * scale
        left = pos[i + 1] + metrics_of.bboxes[ord(text[i + 1])][0] / metrics_of.upem * scale
        gaps.append(left - right)
    return gaps


def test_letter_positions_make_gaps_equal(metrics_of):
    """等宽字体只保证占位相同，这里要让墨迹间隙也相同。"""
    gaps = _gaps(metrics_of, "AMANDA", 6.0)
    assert len(gaps) == 5
    for g in gaps:
        assert g == pytest.approx(gaps[0], abs=1e-6)


def test_letter_positions_keep_total_width(metrics_of):
    """重排间隙不能改变总宽，否则底座长度和限宽判断全要跟着改。"""
    text = "AMANDA"
    pos = metrics.letter_positions(metrics_of, text, 6.0, 1.0, 0.0)
    scale = 6.0 * metrics.INK_SCALE
    left = pos[0] + metrics_of.bboxes[ord(text[0])][0] / metrics_of.upem * scale
    last = text[-1]
    right = pos[-1] + metrics_of.bboxes[ord(last)][1] / metrics_of.upem * scale
    assert right - left == pytest.approx(
        metrics.predict_width(metrics_of, text, 6.0, 1.0, 0.0), abs=1e-6
    )


def test_letter_positions_single_char_is_centered(metrics_of):
    pos = metrics.letter_positions(metrics_of, "A", 6.0, 1.0, 0.0)
    assert len(pos) == 1
    scale = 6.0 * metrics.INK_SCALE
    box = metrics_of.bboxes[ord("A")]
    left = pos[0] + box[0] / metrics_of.upem * scale
    right = pos[0] + box[1] / metrics_of.upem * scale
    assert (left + right) / 2 == pytest.approx(0.0, abs=1e-6)


def test_letter_positions_equal_with_bold(metrics_of):
    gaps = _gaps(metrics_of, "AMANDA", 6.0, weight=0.2)
    for g in gaps:
        assert g == pytest.approx(gaps[0], abs=1e-6)


def test_letter_positions_empty(metrics_of):
    assert metrics.letter_positions(metrics_of, "  ", 6.0) == []


def test_fit_keeps_natural_spacing_by_default(metrics_of, roomy):
    """默认不做视觉等距：letter_x 为空，走 OpenSCAD 单串 text()（与 v1.x 一致）。"""
    fit = metrics.fit(metrics_of, "AMANDA", roomy)
    assert fit.letter_x == []


def test_fit_fills_letter_x_when_even_spacing_on(metrics_of):
    spec = StampSpec(font_size_mm=6.0, weight_offset_mm=0.0, even_spacing=True)
    fit = metrics.fit(metrics_of, "AMANDA", spec)
    assert len(fit.letter_x) == len("AMANDA")
