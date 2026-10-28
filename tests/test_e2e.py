"""端到端测试：真实调用 OpenSCAD 生成印章并复核几何。

没有 OpenSCAD 或字体库时自动跳过。
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from stampgen import batch, metrics, openscad, paths
from stampgen.config import AppConfig, StampSpec
from stampgen.template import RenderParams

SIZE = 6.0
MAX_WIDTH = 60.0


@pytest.fixture()
def cfg(face, metrics_of) -> AppConfig:
    cfg = AppConfig(font_family=face.family, font_style=face.style)
    cfg.spec = StampSpec(
        font_size_mm=SIZE,
        max_width_mm=MAX_WIDTH,
        # 底座宽度按该字体实际墨迹高度给，避免"限字高"掩盖了限宽逻辑
        base_width_mm=metrics.ink_height_mm(metrics_of, "BELLA", SIZE) + 0.2,
    )
    return cfg


def _z_probe(spec: StampSpec) -> float:
    return spec.base_height_mm / 2 + 0.6


def test_single_stamp_matches_predicted_base_len(
    tmp_path, cfg, face, library, openscad_exe, metrics_of
):
    spec = cfg.spec
    fit_result = metrics.fit(metrics_of, "BELLA", spec)
    curve = metrics.resolve_curve(face, spec)
    params = RenderParams.build("BELLA", face, spec, fit_result, metrics_of, curve=curve)

    out = tmp_path / "BELLA.stl"
    openscad.export_stl(openscad_exe, paths.scad_template(), params, out, library.env())

    stats = openscad.stl_stats(out)
    assert stats.width == pytest.approx(fit_result.base_len_mm, abs=0.05)
    assert stats.height == pytest.approx(spec.base_height_mm + spec.letter_height_mm, abs=0.1)

    extent = openscad.stl_extent(out, z_above=_z_probe(spec))
    assert extent.width == pytest.approx(fit_result.width_mm, abs=0.3)
    assert extent.y_center == pytest.approx(0.0, abs=0.15)


def test_batch_generates_and_writes_manifest(tmp_path, cfg, library, openscad_exe):
    names = ["BELLA", "AVA"]
    report = batch.run_batch(cfg, names, tmp_path / "out", library=library)

    assert report.generated == 2
    assert report.failed == 0
    for name in names:
        assert (tmp_path / "out" / f"{name}.stl").is_file()
    manifest = tmp_path / "out" / "manifest.json"
    assert manifest.is_file()

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["summary"]["generated"] == 2
    # manifest 里记录的必须是压缩后的字号/间距
    items = {i["name"]: i for i in payload["items"]}
    assert items["BELLA"]["size_mm"] == pytest.approx(cfg.spec.font_size_mm, abs=1e-3)
    assert items["BELLA"]["spacing"] == pytest.approx(cfg.spec.letter_spacing, abs=1e-3)


def test_batch_short_name_gets_shorter_base(tmp_path, cfg, library):
    """短名字不补齐：AVA 的底座必须比 BELLA 短。"""
    report = batch.run_batch(cfg, ["AVA", "BELLA"], tmp_path / "out2", library=library)
    assert report.generated == 2, [r.message for r in report.results]
    ava = next(r for r in report.results if r.name == "AVA")
    bella = next(r for r in report.results if r.name == "BELLA")
    assert ava.base_len < bella.base_len
    assert ava.size_mm == pytest.approx(bella.size_mm, abs=1e-3)


def test_batch_never_exceeds_max_width(tmp_path, face, metrics_of, library):
    """核心约束：所有成品的总长都不超过上限，超的会被压缩而不是硬撑。"""
    cfg = AppConfig(font_family=face.family, font_style=face.style)
    cfg.spec = StampSpec(
        font_size_mm=SIZE,
        max_width_mm=30.0,
        base_width_mm=metrics.ink_height_mm(metrics_of, "BELLA", SIZE) + 0.2,
    )
    report = batch.run_batch(cfg, ["AVA", "BELLA", "GRACIE"], tmp_path / "lim", library=library)
    assert report.generated >= 2, [r.message for r in report.results]

    for item in report.results:
        if item.status != "ok":
            continue
        assert item.base_len <= cfg.spec.max_width_mm + 0.05
        stats = openscad.stl_stats(tmp_path / "lim" / f"{item.name}.stl")
        assert stats.width <= cfg.spec.max_width_mm + 0.05

    # 长名字必然被压过，而且状态要如实标出来
    long_ones = [r for r in report.results if r.status == "ok" and r.label != "正常"]
    assert long_ones, [r.label for r in report.results]


def test_batch_applies_case_mode(tmp_path, cfg, library):
    cfg.spec.case_mode = "upper"
    report = batch.run_batch(cfg, ["bella", "Ava"], tmp_path / "case", library=library)
    assert report.generated == 2
    assert (tmp_path / "case" / "BELLA.stl").is_file()
    assert (tmp_path / "case" / "AVA.stl").is_file()


def test_batch_skips_invalid_names(tmp_path, cfg, library):
    report = batch.run_batch(cfg, ["BELLA", "名字", "BELLA"], tmp_path / "out3", library=library)
    statuses = [r.status for r in report.results if r.name == "BELLA"]
    assert "ok" in statuses
    assert any(r.name == "名字" and r.status == "skipped" for r in report.results)
    assert report.skipped >= 2
    assert report.generated == 1


def test_batch_respects_cancel(tmp_path, cfg, library):
    cancel = threading.Event()
    cancel.set()
    report = batch.run_batch(
        cfg, ["BELLA", "AVA"], tmp_path / "out4", library=library, cancel=cancel
    )
    assert report.generated == 0


def test_derive_output_dir():
    assert batch.derive_output_dir("names1026.txt", "D:/x").name == "output_stl1026"
    assert batch.derive_output_dir("other.txt", "D:/x").name == "output_stlother"
    # 纯 names.txt 不应变成 output_stlnames
    assert batch.derive_output_dir("names.txt", "D:/x").name == "output_stl"
    assert batch.derive_output_dir("Names.TXT", "D:/x").name == "output_stl"


def test_resolve_workers():
    assert batch.resolve_workers(0, 10) == min(4, os.cpu_count() or 1)
    assert batch.resolve_workers(2, 10) == 2
    assert batch.resolve_workers(99, 3) == 3  # 不超过任务数
    assert batch.resolve_workers(0, 0) == 1


def test_batch_parallel_matches_serial(tmp_path, cfg, library):
    """并发不能改变结果：顺序、数量、成品宽度都要和串行一致。"""
    names = ["BELLA", "AVA", "GRACIE"]
    cfg.workers = 1
    serial = batch.run_batch(cfg, names, tmp_path / "s", library=library)
    cfg.workers = 3
    parallel = batch.run_batch(cfg, names, tmp_path / "p", library=library)

    assert [r.name for r in serial.results] == [r.name for r in parallel.results]
    assert parallel.generated == serial.generated
    for a, b in zip(serial.results, parallel.results):
        assert a.measured_width == pytest.approx(b.measured_width, abs=0.05)
        assert a.base_len == pytest.approx(b.base_len, abs=0.05)
