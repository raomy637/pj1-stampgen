"""名字预检测试。"""

from __future__ import annotations

from stampgen import validate
from stampgen.config import StampSpec


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
