"""配置模型与 JSON 持久化。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from . import paths


@dataclass
class StampSpec:
    """印章几何与自适应拟合参数（单位：毫米）。

    坐标约定与 SCAD 模板一致：X = 底座长度（即目标宽度方向），
    Y = 底座宽度，Z = 底座高度；文字沿 +Z 挤出。
    """

    # --- 几何 ---
    target_width_mm: float = 30.0
    """印章底座长度，也是文字需要填满的目标宽度。"""

    margin_mm: float = 1.5
    """文字左右留白（单边）。可用宽度 = target_width - 2*margin。"""

    base_width_mm: float = 6.0
    base_height_mm: float = 10.0
    letter_height_mm: float = 6.0
    """文字挤出高度（沿 Z）。"""

    edge_mm: float = 0.2
    """字高方向与底座边缘的安全间隙，用于约束最大字号。"""

    # --- 自适应拟合 ---
    min_size_mm: float = 3.5
    max_size_mm: float = 6.0
    """用户设定的字号上限；实际还会被 base_width 的几何约束进一步压低。"""

    hard_min_size_mm: float = 2.5
    """低于此字号视为无法成形，直接判为超长。"""

    default_spacing: float = 1.0
    min_spacing: float = 0.85
    max_spacing: float = 1.6

    # --- 字重 ---
    weight_offset_mm: float = 0.0
    """几何加粗量（offset delta）。0 表示不加粗，安全上限约 0.25mm。"""

    # --- 曲面精度 ---
    curve_fa: float = 0.0
    curve_fs: float = 0.0
    """0 表示自动：按字体轮廓复杂度选精度，见 :func:`stampgen.metrics.resolve_curve`。"""

    # --- 校验 ---
    max_chars: int = 16

    def available_mm(self) -> float:
        """文字可用的净宽度（已扣除两侧留白与加粗占位）。"""
        return max(
            0.0,
            self.target_width_mm - 2.0 * self.margin_mm - 2.0 * max(0.0, self.weight_offset_mm),
        )


@dataclass
class AppConfig:
    openscad_path: str = ""
    font_family: str = ""
    font_style: str = "Regular"
    names_txt: str = ""
    output_root_dir: str = ""
    scad_template: str = ""
    spec: StampSpec = field(default_factory=StampSpec)

    verify_tolerance_mm: float = 0.3
    """STL 实测宽度与目标宽度的允许偏差，超出则按比例修正后重生成。"""

    max_fit_retries: int = 2

    def resolved_openscad(self) -> Path:
        p = Path(self.openscad_path) if self.openscad_path else paths.default_openscad()
        return p

    def resolved_template(self) -> Path:
        """模板路径。

        打包运行时内置模板位于解包临时目录（``_MEIPASS``），该路径每次启动都变。
        所以配置里存下的绝对路径可能已经失效，这里做一次存在性校验，
        失效就回退到当前运行期的内置模板。
        """
        if self.scad_template:
            p = Path(self.scad_template)
            if p.is_file():
                return p
        return paths.scad_template()


_SPEC_FIELDS = {f.name for f in fields(StampSpec)}
_CFG_FIELDS = {f.name for f in fields(AppConfig)}


def _filtered(cls_fields: set[str], data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k in cls_fields}


def config_from_dict(data: dict[str, Any]) -> AppConfig:
    """从字典构造配置，忽略未知字段、兼容缺失字段。"""
    spec_data = data.get("spec") or {}
    cfg = AppConfig(**_filtered(_CFG_FIELDS, data))
    cfg.spec = StampSpec(**_filtered(_SPEC_FIELDS, spec_data))
    return cfg


def config_to_dict(cfg: AppConfig) -> dict[str, Any]:
    return asdict(cfg)


def load_config(path: Path | None = None) -> AppConfig:
    p = path or paths.config_path()
    if not p.is_file():
        return default_config()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("配置根节点必须是对象")
        return config_from_dict(data)
    except (OSError, ValueError, TypeError):
        # 配置损坏不应阻塞启动，回退默认值
        return default_config()


def save_config(cfg: AppConfig, path: Path | None = None) -> Path:
    p = path or paths.config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(config_to_dict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def default_config() -> AppConfig:
    cfg = AppConfig()
    cfg.openscad_path = str(paths.default_openscad())
    # 打包后内置模板在临时解包目录里，写进配置必然失效，留空让运行期动态解析
    cfg.scad_template = "" if paths.is_frozen() else str(paths.scad_template())
    return cfg
