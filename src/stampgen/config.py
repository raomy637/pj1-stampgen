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

    # --- 宽度求解方向 ---
    width_mode: str = "auto"
    """宽度是输入还是输出。

    * ``"auto"``：给定字号与间距，算出每个名字各自的底座长度。字号恒定，
      成品宽度随名字长短变化 —— 也就是旧版 ``batch_3Dnames.py`` 的行为，
      只是旧版按字符数查表估算，这里是按字体度量精算。**默认模式**，
      因为实际生产里绝大多数是"字要一样大"。
    * ``"fixed"``：给定目标宽度，反解字号与间距。成品一律同宽，适合成套出货。
    """

    auto_size_mm: float = 6.0
    """``auto`` 模式下的固定字号；仍受底座宽度约束（字高不得超过底座宽）。"""

    auto_spacing: float = 1.0
    """``auto`` 模式下的字间距。1.0 为字体原字距。"""

    # --- 几何 ---
    target_width_mm: float = 30.0
    """``fixed`` 模式的印章底座长度，也是文字需要填满的目标宽度。

    ``auto`` 模式下此值不参与计算，底座长度由 :meth:`base_len_for` 逐名求出。
    """

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
        """``fixed`` 模式下文字可用的净宽度（已扣除两侧留白与加粗占位）。"""
        return max(
            0.0,
            self.target_width_mm - 2.0 * self.margin_mm - 2.0 * max(0.0, self.weight_offset_mm),
        )

    def is_auto_width(self) -> bool:
        return self.width_mode == "auto"

    def base_len_for(self, width_mm: float) -> float:
        """由文字墨迹宽度反推底座长度（``auto`` 模式）。

        与 :meth:`available_mm` 严格互逆：``base_len_for(available_mm())``
        应当还原出 ``target_width_mm``，这样两种模式的留白含义完全一致。
        """
        return (
            width_mm
            + 2.0 * self.margin_mm
            + 2.0 * max(0.0, self.weight_offset_mm)
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

    workers: int = 0
    """并发渲染数。0 表示按 CPU 核数自动决定（封顶 4）。

    OpenSCAD 每次调用都是独立进程，彼此无共享状态；fontconfig 缓存已在
    批次开始前预热，所以并发不会互相拖慢。
    """

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


WIDTH_MODES = ("fixed", "auto")
"""``fixed`` = 定宽自适应字号；``auto`` = 定字号自适应宽度。"""


def config_from_dict(data: dict[str, Any]) -> AppConfig:
    """从字典构造配置，忽略未知字段、兼容缺失字段。"""
    spec_data = data.get("spec") or {}
    cfg = AppConfig(**_filtered(_CFG_FIELDS, data))
    cfg.spec = StampSpec(**_filtered(_SPEC_FIELDS, spec_data))
    # 手工改坏配置时不该让程序起不来，回退到默认模式即可
    if cfg.spec.width_mode not in WIDTH_MODES:
        cfg.spec.width_mode = "fixed"
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
