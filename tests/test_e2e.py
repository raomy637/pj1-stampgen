"""端到端测试：真实调用 OpenSCAD 生成印章并复核几何。

没有 OpenSCAD 或字体库时自动跳过。
"""

from __future__ import annotations

import os
import threading

import pytest

from stampgen import batch, metrics, openscad, paths
from stampgen.config import AppConfig, StampSpec
from stampgen.template import RenderParams


@pytest.fixture()
def cfg(face) -> AppConfig:
    cfg = AppConfig(font_family=face.family, font_style=face.style)
    # 这批用例验证的是"定宽自适应字号"，显式声明模式，别依赖默认值
    cfg.spec = StampSpec(width_mode="fixed", target_width_mm=30.0)
    return cfg


def test_single_stamp_matches_target_width(tmp_path, cfg, face, library, openscad_exe, metrics_of):
    spec = cfg.spec
    fit_result = metrics.fit(metrics_of, "BELLA", spec)
    curve = metrics.resolve_curve(face, spec)
    params = RenderParams.build("BELLA", face, spec, fit_result, metrics_of, curve=curve)

    out = tmp_path / "BELLA.stl"
    env = library.env()
    openscad.export_stl(openscad_exe, paths.scad_template(), params, out, env)

    stats = openscad.stl_stats(out)
    assert stats.width == pytest.approx(spec.target_width_mm, abs=0.05)
    assert stats.height == pytest.approx(spec.base_height_mm + spec.letter_height_mm, abs=0.1)

    extent = openscad.stl_extent(out, z_above=spec.base_height_mm / 2 + 0.6)
    assert extent.width <= spec.available_mm() + 0.4
    assert extent.y_center == pytest.approx(0.0, abs=0.15)


def test_batch_generates_and_writes_manifest(tmp_path, cfg, library, openscad_exe):
    names = ["BELLA", "AVA"]
    report = batch.run_batch(cfg, names, tmp_path / "out", library=library)

    assert report.generated == 2
    assert report.failed == 0
    for name in names:
        assert (tmp_path / "out" / f"{name}.stl").is_file()
    assert (tmp_path / "out" / "manifest.json").is_file()

    bella = next(r for r in report.results if r.name == "BELLA")
    assert bella.measured_width == pytest.approx(cfg.spec.available_mm(), abs=0.3)


def test_batch_skips_invalid_names(tmp_path, cfg, library):
    report = batch.run_batch(cfg, ["BELLA", "名字", "BELLA"], tmp_path / "out2", library=library)
    statuses = [r.status for r in report.results if r.name == "BELLA"]
    assert "ok" in statuses
    assert any(r.name == "名字" and r.status == "skipped" for r in report.results)
    assert report.skipped >= 2
    assert report.generated == 1


def test_batch_respects_cancel(tmp_path, cfg, library):
    cancel = threading.Event()
    cancel.set()
    report = batch.run_batch(
        cfg, ["BELLA", "AVA"], tmp_path / "out3", library=library, cancel=cancel
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


def test_batch_auto_mode_varies_base_length(
    tmp_path, face, library, openscad_exe, metrics_of
):
    """固定字号模式下：字号一致、底座长度随名字变，且实测底座与预测一致。"""
    cfg = AppConfig(font_family=face.family, font_style=face.style)
    cfg.spec = StampSpec(
        width_mode="auto",
        auto_size_mm=6.0,
        auto_spacing=1.0,
        base_width_mm=metrics.cap_height_mm(metrics_of, 6.0) + 0.1,
    )
    report = batch.run_batch(cfg, ["AVA", "BELLA"], tmp_path / "auto", library=library)
    assert report.generated == 2, [r.message for r in report.results]

    ava = next(r for r in report.results if r.name == "AVA")
    bella = next(r for r in report.results if r.name == "BELLA")
    assert ava.size_mm == pytest.approx(bella.size_mm)
    assert bella.base_len > ava.base_len

    stats = openscad.stl_stats(tmp_path / "auto" / "BELLA.stl")
    assert stats.width == pytest.approx(bella.base_len, abs=0.05)


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
