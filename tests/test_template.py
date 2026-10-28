"""模板渲染与 STL 解析测试。"""

from __future__ import annotations

import struct

import pytest

from stampgen import openscad, paths, template
from stampgen.metrics import fit


def _binary_stl(path, triangles):
    """写一个最小二进制 STL。triangles: [(v1, v2, v3), ...]"""
    with open(path, "wb") as fh:
        fh.write(b"\0" * 80)
        fh.write(struct.pack("<I", len(triangles)))
        for tri in triangles:
            fh.write(struct.pack("<3f", 0, 0, 1))
            for vertex in tri:
                fh.write(struct.pack("<3f", *vertex))
            fh.write(struct.pack("<H", 0))


def test_to_defines_quotes_strings(face, metrics_of, spec):
    fit_result = fit(metrics_of, 'AB"C', spec)
    params = template.RenderParams.build("AB\"C", face, spec, fit_result, metrics_of)
    defines = template.to_defines(params)
    assert "-D" in defines
    assert 'name="AB\\"C"' in defines


def test_to_defines_formats_floats(face, metrics_of, spec):
    fit_result = fit(metrics_of, "BELLA", spec)
    params = template.RenderParams.build("BELLA", face, spec, fit_result, metrics_of)
    defines = template.to_defines(params)
    # 底座长度逐名不同，由 fit 给出，不再等于某个固定的目标宽度
    raw = next(d for d in defines if d.startswith("base_len="))
    assert float(raw.split("=", 1)[1]) == pytest.approx(fit_result.base_len_mm, abs=1e-3)


def test_render_params_offsets_baseline(face, metrics_of, spec):
    params = template.RenderParams.build("BELLA", face, spec, fit(metrics_of, "BELLA", spec), metrics_of)
    assert params.text_offset_y < 0  # 大写字高带的中心在基线之上，需要下移


def test_preview_scad_is_self_contained(face, metrics_of, spec):
    params = template.RenderParams.build("BELLA", face, spec, fit(metrics_of, "BELLA", spec), metrics_of)
    text = template.preview_scad(params, paths.scad_template())
    assert 'name="BELLA";' in text
    assert "mirror([1, 0, 0])" in text


def test_stl_stats_binary(tmp_path):
    path = tmp_path / "a.stl"
    _binary_stl(
        path,
        [
            ((0, 0, 0), (10, 0, 0), (0, 4, 0)),
            ((0, 0, 0), (0, 0, 3), (10, 0, 0)),
        ],
    )
    stats = openscad.stl_stats(path)
    assert stats.triangles == 2
    assert stats.width == pytest.approx(10)
    assert stats.depth == pytest.approx(4)
    assert stats.height == pytest.approx(3)


def test_stl_extent_filters_by_height(tmp_path):
    path = tmp_path / "b.stl"
    _binary_stl(
        path,
        [
            ((0, 0, 0), (10, 0, 0), (0, 4, 0)),
            ((-2, -1, 8), (2, 1, 8), (0, 0, 8)),
        ],
    )
    whole = openscad.stl_extent(path)
    above = openscad.stl_extent(path, z_above=5.0)
    assert whole.width == pytest.approx(12)
    assert above.width == pytest.approx(4)
    assert above.y_center == pytest.approx(0.0)


def test_stl_stats_ascii(tmp_path):
    path = tmp_path / "c.stl"
    path.write_text(
        "solid s\n"
        "facet normal 0 0 1\n outer loop\n"
        "  vertex 0 0 0\n  vertex 5 0 0\n  vertex 0 2 0\n"
        " endloop\nendfacet\nendsolid s\n",
        encoding="utf-8",
    )
    stats = openscad.stl_stats(path)
    assert stats.width == pytest.approx(5)
    assert stats.depth == pytest.approx(2)


def test_missing_openscad_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        openscad.version(tmp_path / "nope.exe")
