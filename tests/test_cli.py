"""命令行参数持久化测试。

用户的核心诉求之一：给过一次目标宽度，以后就不想再给。
命令行侧用显式 ``--save`` 落盘，避免脚本反复调用时污染默认配置。
"""

from __future__ import annotations

import json

from stampgen import cli, paths


def _use_tmp_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "stampgen_config.json"
    monkeypatch.setattr(paths, "config_path", lambda: cfg_file)
    return cfg_file


def test_save_flag_persists_width(tmp_path, monkeypatch):
    cfg_file = _use_tmp_config(tmp_path, monkeypatch)
    rc = cli.main(["fit", "--width", "32", "--margin", "2", "--save"])
    assert rc == 0
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["spec"]["target_width_mm"] == 32
    assert data["spec"]["margin_mm"] == 2


def test_without_save_flag_nothing_written(tmp_path, monkeypatch):
    cfg_file = _use_tmp_config(tmp_path, monkeypatch)
    rc = cli.main(["fit", "--width", "32"])
    assert rc == 0
    assert not cfg_file.exists()


def test_saved_width_is_reused(tmp_path, monkeypatch):
    cfg_file = _use_tmp_config(tmp_path, monkeypatch)
    cli.main(["fit", "--width", "28", "--save"])
    # 第二次不带 --width，应沿用 28
    from stampgen.config import load_config

    assert load_config(cfg_file).spec.target_width_mm == 28
