"""配置序列化与迁移测试。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from stampgen.config import (
    CASE_MODES,
    AppConfig,
    StampSpec,
    config_from_dict,
    load_config,
    migrate_spec_dict,
    save_config,
)


def test_roundtrip(tmp_path):
    path = tmp_path / "cfg.json"
    cfg = AppConfig(font_family="Daziji_V5", names_txt="a.txt")
    cfg.spec = StampSpec(max_width_mm=48.0, font_size_mm=5.5, weight_offset_mm=0.12)
    save_config(cfg, path)

    loaded = load_config(path)
    assert loaded.font_family == "Daziji_V5"
    assert loaded.spec.max_width_mm == 48.0
    assert loaded.spec.font_size_mm == 5.5
    assert loaded.spec.weight_offset_mm == 0.12


def test_missing_file_returns_default(tmp_path):
    cfg = load_config(tmp_path / "nope.json")
    assert isinstance(cfg, AppConfig)
    assert cfg.spec.max_width_mm > 0


def test_corrupt_file_returns_default(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.spec.max_width_mm > 0


def test_unknown_keys_ignored(tmp_path):
    path = tmp_path / "extra.json"
    path.write_text(
        json.dumps({"font_family": "X", "spec": {"max_width_mm": 25, "unknown": 1}}),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.font_family == "X"
    assert cfg.spec.max_width_mm == 25


def test_config_from_dict_without_spec():
    cfg = config_from_dict({"font_family": "Y"})
    assert cfg.font_family == "Y"
    assert cfg.spec.max_width_mm > 0


def test_max_text_width_subtracts_margin_and_weight():
    spec = StampSpec(max_width_mm=30, margin_mm=1.5, weight_offset_mm=0.2)
    assert spec.max_text_width() == 30 - 3.0 - 0.4


def test_stale_template_path_falls_back_to_bundled():
    """打包后配置里可能残留已失效的临时解包路径，应回退到当前内置模板。"""
    cfg = AppConfig(scad_template=str(Path(tempfile.gettempdir()) / "_MEI_gone" / "t.scad"))
    assert cfg.resolved_template().is_file()


def test_existing_template_path_is_respected(tmp_path):
    tpl = tmp_path / "custom.scad"
    tpl.write_text("// custom", encoding="utf-8")
    cfg = AppConfig(scad_template=str(tpl))
    assert cfg.resolved_template() == tpl


# ---------------- 大小写 ----------------

def test_case_mode_roundtrip(tmp_path):
    path = tmp_path / "case.json"
    cfg = AppConfig()
    cfg.spec = StampSpec(case_mode="upper", font_size_mm=5.5, letter_spacing=1.15)
    cfg.workers = 3
    save_config(cfg, path)

    loaded = load_config(path)
    assert loaded.spec.case_mode == "upper"
    assert loaded.spec.font_size_mm == 5.5
    assert loaded.spec.letter_spacing == 1.15
    assert loaded.workers == 3


def test_invalid_case_mode_falls_back_to_keep(tmp_path):
    """手工把配置改坏时不该让程序起不来。"""
    path = tmp_path / "bad_case.json"
    path.write_text('{"spec": {"case_mode": "随便写的"}}', encoding="utf-8")
    assert load_config(path).spec.case_mode == "keep"
    assert StampSpec(case_mode="随便写的").effective_case() == "keep"


def test_all_case_modes_are_declared():
    for mode in CASE_MODES:
        assert StampSpec(case_mode=mode).effective_case() == mode


# ---------------- 旧配置迁移 ----------------


def test_migrate_renames_old_fields():
    data = migrate_spec_dict({"auto_size_mm": 7.0, "auto_spacing": 1.2})
    assert data["font_size_mm"] == 7.0
    assert data["letter_spacing"] == 1.2


def test_migrate_keeps_new_fields_when_both_present():
    data = migrate_spec_dict({"auto_size_mm": 7.0, "font_size_mm": 5.0})
    assert data["font_size_mm"] == 5.0


def test_migrate_large_target_width_becomes_max_width():
    """老用户把目标宽度设成 80mm，新版不该突然只出 60mm。"""
    data = migrate_spec_dict({"target_width_mm": 80.0})
    assert data["max_width_mm"] == 80.0


def test_migrate_ignores_small_target_width():
    data = migrate_spec_dict({"target_width_mm": 30.0})
    assert "max_width_mm" not in data


def test_old_config_loads_without_error(tmp_path):
    """v2.1.0 的完整配置应当能直接读进来，参数不丢。"""
    path = tmp_path / "old.json"
    path.write_text(
        json.dumps(
            {
                "font_family": "Daziji_V1",
                "spec": {
                    "width_mode": "auto",
                    "auto_size_mm": 6.5,
                    "auto_spacing": 1.05,
                    "target_width_mm": 70.0,
                    "base_width_mm": 6.2,
                    "min_size_mm": 3.0,
                    "max_size_mm": 7.0,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.spec.font_size_mm == 6.5
    assert cfg.spec.letter_spacing == 1.05
    assert cfg.spec.max_width_mm == 70.0
    assert cfg.spec.base_width_mm == 6.2
    assert not hasattr(cfg.spec, "width_mode")


def test_base_len_for_inverts_max_text_width():
    """底座长度与允许的文字宽度必须严格互逆。"""
    spec = StampSpec(max_width_mm=30, margin_mm=1.5, weight_offset_mm=0.1)
    assert spec.base_len_for(spec.max_text_width()) == 30.0


def test_open_output_default_is_on():
    assert AppConfig().open_output_after_run is True
