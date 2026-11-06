"""配置模型与 JSON 持久化。

v2.2.0 起只有一种宽度逻辑：**限宽**。字号由用户给定，底座长度按名字精算，
但不超过 ``max_width_mm``。短名字不补齐，长名字先压间距、再缩字号。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from . import paths

CASE_MODES = ("keep", "upper", "capitalize", "lower")
"""大小写转换方式。

* ``keep``：原样
* ``upper``：全部大写
* ``capitalize``：每个词首字母大写
* ``lower``：全部小写
"""

CASE_LABELS = {
    "keep": "保持原样",
    "upper": "全部大写",
    "capitalize": "首字母大写",
    "lower": "全部小写",
}


@dataclass
class StampSpec:
    """印章几何与字体参数（长度单位：毫米）。

    坐标约定与 SCAD 模板一致：X = 底座长度（文字排布方向），
    Y = 底座宽度，Z = 底座高度；文字沿 +Z 挤出。
    """

    # --- 印章几何 ---
    base_width_mm: float = 6.6
    """底座宽度（Y 方向）。字高不得超过它，否则字母会悬在底座外。

    开启 :attr:`widen_base_per_name` 时它变成「默认/最小」宽度：
    个别名字装不下会单独加宽，其余仍用它。
    """

    widen_base_per_name: bool = True
    """个别名字墨迹太高时，加宽它的底座而不是缩字号。

    一套印章「字一样大」比「截面一样宽」重要：缩字号会让那一枚看起来像次品，
    加宽底座只是让它胖一点。关掉则回到「底座统一、字号各自缩小」。"""

    base_height_mm: float = 10.0
    """底座高度（Z 方向，即手柄连接部分的厚度）。"""

    letter_height_mm: float = 6.0
    """文字挤出高度（沿 Z）。"""

    max_width_mm: float = 60.0
    """底座长度的硬上限。

    实际底座长度由名字宽度算出，**短名字不补齐到上限**；
    只有算出超过上限时才压缩（先压间距，再缩字号）。
    """

    margin_mm: float = 3.5
    """文字左右留白（单边）。底座长度 = 文字宽 + 2 × 留白。

    v1.x 用「字符数 → 底座长」查表（2 字 18、3 字 24、4 字 30…），换算成留白
    是 3.5~4mm，比 1.5mm 松弛得多，成品看起来字不顶边。实测旧成品
    ``BO`` 底座 18mm、墨迹 10.92mm，单边留白 3.54mm，取 3.5mm 基本重合。
    """

    # --- 字体 ---
    font_size_mm: float = 6.0
    """字号。仍受底座宽度约束（字高不得超过底座宽），超出时自动压低并提示。"""

    letter_spacing: float = 1.0
    """字间距。1.0 为字体原字距，大于 1 更疏、小于 1 更紧。

    默认 1.0：v1.x 的模板里没有 ``letter_spacing`` 变量（``main.py`` 传的
    ``-D letter_spacing=1.2`` 被 OpenSCAD 直接忽略），成品一直是字体原字距。
    实测 v1.x 的 ``BO`` 墨迹宽 10.92mm，和 1.0 完全一致；设成 1.2 会宽到
    12.01mm，字母之间明显发空。
    """

    even_spacing: bool = False
    """逐字等距排布（按墨迹宽平均分配间隙）。

    默认关闭：开启后字距由程序重排，会偏离字体设计师给定的节奏，Arial 这类
    比例字体尤其明显（v1.x 没有这个功能，关掉才和旧成品一致）。等宽字体
    （Daziji / Special Elite 系列）想要绝对均匀的间隙时再打开。
    """

    min_spacing: float = 0.85
    """超宽时允许压缩到的间距下限。再往下字形会粘连。"""

    weight_offset_mm: float = 0.0
    """几何加粗量（``offset(delta)``）。0 表示不加粗，安全上限约 0.3mm。

    默认 0：Arial 在 6mm 字号下笔画约 0.82mm，本身够粗；再叠加 0.2mm 会让
    e/a/o 的字腔（counter）缩到 0.5mm 以下，打印容易糊死。换细笔画字体
    （做旧体、手写体）时再按需加粗。
    """

    case_mode: str = "keep"
    """大小写转换，取值见 :data:`CASE_MODES`。"""

    # --- 精度与保护 ---
    hard_min_size_mm: float = 2.5
    """低于此字号视为无法成形，判为超长并跳过。"""

    curve_fa: float = 0.0
    curve_fs: float = 0.0
    """0 表示自动：按字体轮廓复杂度选精度，见 :func:`stampgen.metrics.resolve_curve`。"""

    max_chars: int = 16

    def base_len_for(self, width_mm: float) -> float:
        """由文字墨迹宽度反推底座长度。"""
        return (
            width_mm
            + 2.0 * self.margin_mm
            + 2.0 * max(0.0, self.weight_offset_mm)
        )

    def max_text_width(self) -> float:
        """在上限之内，文字允许占据的最大墨迹宽度。"""
        return max(
            0.0,
            self.max_width_mm
            - 2.0 * self.margin_mm
            - 2.0 * max(0.0, self.weight_offset_mm),
        )

    def effective_case(self) -> str:
        return self.case_mode if self.case_mode in CASE_MODES else "keep"


@dataclass
class AppConfig:
    openscad_path: str = ""
    font_family: str = "Arial"
    """默认字体。找不到时 FontLibrary.find() 会退回字体库第一个，不会报错。

    Arial 与 v1.x 模板硬编码的 ``font_name = "Arial"`` 一致：无做旧噪点、
    笔画 0.82mm，小字号打印边缘最干净。Special Elite 等做旧体适合看样，
    实际出货不如 Arial 清晰。
    """

    font_style: str = "Regular"
    names_txt: str = ""
    output_root_dir: str = ""
    scad_template: str = ""
    spec: StampSpec = field(default_factory=StampSpec)

    verify_tolerance_mm: float = 0.3
    """STL 实测宽度与预测底座长的允许偏差，超出则按比例修正后重生成。"""

    max_fit_retries: int = 2

    workers: int = 0
    """并发渲染数。0 表示按 CPU 核数自动决定（封顶 4）。

    OpenSCAD 每次调用都是独立进程，彼此无共享状态；fontconfig 缓存已在
    批次开始前预热，所以并发不会互相拖慢。
    """

    open_output_after_run: bool = True
    """生成完成后自动打开输出文件夹。"""

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

#: 旧版本字段名 → 新字段名。v2.1.0 用 auto_size_mm / auto_spacing。
_SPEC_ALIASES = {
    "auto_size_mm": "font_size_mm",
    "auto_spacing": "letter_spacing",
}


def _filtered(cls_fields: set[str], data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k in cls_fields}


def migrate_spec_dict(spec_data: dict[str, Any]) -> dict[str, Any]:
    """把旧版配置字典迁移成新版字段名。

    * ``auto_size_mm`` → ``font_size_mm``
    * ``auto_spacing`` → ``letter_spacing``
    * 旧版 ``target_width_mm``（定宽模式的目标宽度）若大于默认上限，
      则把它当作 ``max_width_mm``，避免老用户突然发现成品变短。
    * 其余旧字段（``width_mode`` / ``min_size_mm`` / ``max_size_mm`` 等）
      直接丢弃，由 :func:`_filtered` 兜底。
    """
    data = dict(spec_data)
    for old, new in _SPEC_ALIASES.items():
        if new not in data and old in data:
            data[new] = data[old]

    legacy_width = data.get("target_width_mm")
    if "max_width_mm" not in data and isinstance(legacy_width, (int, float)):
        if float(legacy_width) > StampSpec.max_width_mm:
            data["max_width_mm"] = float(legacy_width)
    return data


def config_from_dict(data: dict[str, Any]) -> AppConfig:
    """从字典构造配置，忽略未知字段、兼容缺失字段。"""
    spec_data = migrate_spec_dict(data.get("spec") or {})
    cfg = AppConfig(**_filtered(_CFG_FIELDS, data))
    cfg.spec = StampSpec(**_filtered(_SPEC_FIELDS, spec_data))
    # 手工改坏配置时不该让程序起不来，回退到默认值即可
    if cfg.spec.case_mode not in CASE_MODES:
        cfg.spec.case_mode = "keep"
    return cfg


def config_to_dict(cfg: AppConfig) -> dict[str, Any]:
    return asdict(cfg)


def _migrate_legacy_config(target: Path) -> None:
    """把 exe 同目录的老配置搬到用户配置目录（只做一次）。

    v2.2.3 及更早版本把配置写在 exe 旁边，换个版本文件夹就找不到，
    用户会以为「默认参数被改了」。搬到 %APPDATA% 之后所有版本共用一份。
    """
    if target.is_file():
        return
    legacy = paths.legacy_config_path()
    if not legacy.is_file() or legacy.resolve() == target.resolve():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
    except OSError:
        pass  # 搬不过去就用默认值，不该因此起不来


def load_config(path: Path | None = None) -> AppConfig:
    p = path or paths.config_path()
    if path is None:
        _migrate_legacy_config(p)
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
