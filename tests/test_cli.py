"""命令行参数持久化测试。

用户的核心诉求之一：给过一次参数，以后就不想再给。
命令行侧用显式 ``--save`` 落盘，避免脚本反复调用时污染默认配置。
"""

from __future__ import annotations

import json

from stampgen import cli, paths
from stampgen.config import load_config


def _use_tmp_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "stampgen_config.json"
    monkeypatch.setattr(paths, "config_path", lambda: cfg_file)
    return cfg_file


def test_save_flag_persists_max_width(tmp_path, monkeypatch):
    cfg_file = _use_tmp_config(tmp_path, monkeypatch)
    rc = cli.main(["fit", "--max-width", "32", "--margin", "2", "--save"])
    assert rc == 0
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["spec"]["max_width_mm"] == 32
    assert data["spec"]["margin_mm"] == 2


def test_without_save_flag_nothing_written(tmp_path, monkeypatch):
    cfg_file = _use_tmp_config(tmp_path, monkeypatch)
    rc = cli.main(["fit", "--max-width", "32"])
    assert rc == 0
    assert not cfg_file.exists()


def test_saved_width_is_reused(tmp_path, monkeypatch):
    cfg_file = _use_tmp_config(tmp_path, monkeypatch)
    cli.main(["fit", "--max-width", "28", "--save"])
    # 第二次不带 --max-width，应沿用 28
    assert load_config(cfg_file).spec.max_width_mm == 28


def test_save_flag_persists_case_and_size(tmp_path, monkeypatch):
    cfg_file = _use_tmp_config(tmp_path, monkeypatch)
    rc = cli.main(["fit", "--size", "5.5", "--spacing", "1.1", "--case", "upper", "--save"])
    assert rc == 0
    spec = load_config(cfg_file).spec
    assert spec.font_size_mm == 5.5
    assert spec.letter_spacing == 1.1
    assert spec.case_mode == "upper"


def test_removed_flags_are_rejected(tmp_path, monkeypatch):
    """v2.1.0 的 --mode/--width 已删除，不该静默接受。"""
    _use_tmp_config(tmp_path, monkeypatch)
    for argv in (["fit", "--mode", "auto"], ["fit", "--width", "30"]):
        try:
            cli.main(argv)
        except SystemExit as exc:
            assert exc.code != 0
        else:  # pragma: no cover - argparse 一定会退出
            raise AssertionError(f"{argv} 应当被拒绝")
