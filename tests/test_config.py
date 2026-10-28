"""配置序列化测试。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from stampgen.config import AppConfig, StampSpec, config_from_dict, load_config, save_config


def test_roundtrip(tmp_path):
    path = tmp_path / "cfg.json"
    cfg = AppConfig(font_family="Daziji_V5", names_txt="a.txt")
    cfg.spec = StampSpec(target_width_mm=32.5, weight_offset_mm=0.12)
    save_config(cfg, path)

    loaded = load_config(path)
    assert loaded.font_family == "Daziji_V5"
    assert loaded.spec.target_width_mm == 32.5
    assert loaded.spec.weight_offset_mm == 0.12


def test_missing_file_returns_default(tmp_path):
    cfg = load_config(tmp_path / "nope.json")
    assert isinstance(cfg, AppConfig)
    assert cfg.spec.target_width_mm > 0


def test_corrupt_file_returns_default(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.spec.target_width_mm > 0


def test_unknown_keys_ignored(tmp_path):
    path = tmp_path / "extra.json"
    path.write_text(
        json.dumps({"font_family": "X", "spec": {"target_width_mm": 25, "unknown": 1}}),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.font_family == "X"
    assert cfg.spec.target_width_mm == 25


def test_config_from_dict_without_spec():
    cfg = config_from_dict({"font_family": "Y"})
    assert cfg.font_family == "Y"
    assert cfg.spec.target_width_mm > 0


def test_available_width_subtracts_margin_and_weight():
    spec = StampSpec(target_width_mm=30, margin_mm=1.5, weight_offset_mm=0.2)
    assert spec.available_mm() == 30 - 3.0 - 0.4


def test_stale_template_path_falls_back_to_bundled():
    """打包后配置里可能残留已失效的临时解包路径，应回退到当前内置模板。"""
    cfg = AppConfig(scad_template=str(Path(tempfile.gettempdir()) / "_MEI_gone" / "t.scad"))
    assert cfg.resolved_template().is_file()


def test_existing_template_path_is_respected(tmp_path):
    tpl = tmp_path / "custom.scad"
    tpl.write_text("// custom", encoding="utf-8")
    cfg = AppConfig(scad_template=str(tpl))
    assert cfg.resolved_template() == tpl


def test_width_mode_roundtrip(tmp_path):
    path = tmp_path / "mode.json"
    cfg = AppConfig()
    cfg.spec = StampSpec(width_mode="auto", auto_size_mm=5.5, auto_spacing=1.15)
    cfg.workers = 3
    save_config(cfg, path)

    loaded = load_config(path)
    assert loaded.spec.width_mode == "auto"
    assert loaded.spec.auto_size_mm == 5.5
    assert loaded.spec.auto_spacing == 1.15
    assert loaded.workers == 3


def test_invalid_width_mode_falls_back_to_fixed(tmp_path):
    """手工把配置改坏时不该让程序起不来。"""
    path = tmp_path / "bad_mode.json"
    path.write_text('{"spec": {"width_mode": "随便写的"}}', encoding="utf-8")
    assert load_config(path).spec.width_mode == "fixed"


def test_base_len_for_inverts_available_mm():
    """auto 模式的底座长度与 fixed 模式的可用宽度必须严格互逆。"""
    spec = StampSpec(target_width_mm=30, margin_mm=1.5, weight_offset_mm=0.1)
    assert spec.base_len_for(spec.available_mm()) == 30.0


def test_is_auto_width():
    assert StampSpec(width_mode="auto").is_auto_width()
    assert not StampSpec(width_mode="fixed").is_auto_width()
