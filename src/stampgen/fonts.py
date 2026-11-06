"""内置字体库：扫描、度量读取、fontconfig 注入。

OpenSCAD 通过 fontconfig 解析字体名，默认只认系统已安装字体。
本模块在运行时生成一份临时 fontconfig 配置，把 ``fonts/`` 目录加进去，
再通过 ``FONTCONFIG_FILE`` 环境变量传给 OpenSCAD 子进程，
从而实现「字体随程序走、不需要装进 Windows」。
"""

from __future__ import annotations

import os
import xml.sax.saxutils as xml_escape
from dataclasses import dataclass, field
from pathlib import Path

from fontTools.ttLib import TTFont

from . import paths

FONT_SUFFIXES = {".ttf", ".otf"}

# 字体族名/样式名的候选 nameID，按优先级排列
_FAMILY_IDS = (16, 1)
_STYLE_IDS = (17, 2)

SYSTEM_FONT_FILES = (
    "arial.ttf",
    "arialbd.ttf",
    "ariali.ttf",
    "arialbi.ttf",
)
"""允许从系统字体目录额外加载的字体文件名（只列白名单，不全量扫描）。

为什么要这个：v1.x 的模板把 ``font_name`` 硬编码成 ``"Arial"``，成品笔画宽
约 0.82mm、字面无做旧噪点，0.4mm 喷嘴打出来边缘干净。v2.x 的默认字体换成
了 Special Elite 这类做旧打字机体，6mm 字号下笔画只有 0.57mm、轮廓带锯齿，
同样工艺打印会显得发虚、笔画断续。把 Arial 重新纳入字体库，才能复现 v1.x
的成品效果。

只读系统字体、不复制文件：Arial 是 Monotype 的商业字体，随程序分发有授权
问题，指到系统里已装的那份即可（fontconfig 本来就会扫系统目录）。
"""


@dataclass(frozen=True)
class FontFace:
    """一个字重面（family + style 唯一确定一个文件）。"""

    path: Path
    family: str
    style: str
    full_name: str
    upem: int
    cap_height: int
    glyph_count: int
    is_mono: bool
    points_per_glyph: float = 0.0
    """字形轮廓的平均节点数，用于判断字体是否「自带细节」。

    手工做旧/点阵风格字体每字常有上百个节点（如 Special Elite 系列约 210），
    而常规字体只有 20 左右。节点多的字体本身就是粗糙的，
    再做高精度曲面细分不会增加视觉信息，只会让布尔运算变慢几十倍。
    """

    @property
    def label(self) -> str:
        return f"{self.family} {self.style}".strip()

    @property
    def openscad_font(self) -> str:
        """传给 OpenSCAD ``text(font=...)`` 的字符串。"""
        return f"{self.family}:style={self.style}"

    @property
    def is_dense_outline(self) -> bool:
        return self.points_per_glyph >= 60.0


@dataclass
class FaceMetrics:
    """渲染所需的字体度量，避免重复解析字体文件。"""

    upem: int
    advances: dict[int, int] = field(default_factory=dict)
    cap_height: int = 0
    bboxes: dict[int, tuple[int, int]] = field(default_factory=dict)
    """每个字符的字形横向包围盒 (xMin, xMax)，用于精确计算墨迹宽度。"""
    v_bboxes: dict[int, tuple[int, int]] = field(default_factory=dict)
    """每个字符的字形纵向包围盒 (yMin, yMax)，用于把文字垂直居中。"""

    def advance_units(self, text: str) -> int:
        return sum(self.advances.get(ord(ch), 0) for ch in text)

    def advance_em(self, text: str) -> tuple[float, float]:
        """返回 (A, L)：整串 advance 总和、末字符 advance，单位 em。"""
        if not text or not self.upem:
            return 0.0, 0.0
        total = self.advance_units(text) / self.upem
        last = self.advances.get(ord(text[-1]), 0) / self.upem
        return total, last

    def ink_width_em(self, text: str, spacing: float = 1.0) -> float:
        """整串墨迹宽度（em）。

        与只累加 advance 相比，这里扣掉了首字符左侧、末字符右侧的字面边距，
        因此与实际渲染宽度基本一致：

            墨迹宽 = 末字符起点 + 末字符 xMax - 首字符 xMin

        其中第 i 个字符的起点 = 前 i 个字符 advance 之和 × spacing。
        """
        if not text or not self.upem:
            return 0.0
        first, last = text[0], text[-1]
        advance_before_last = sum(
            self.advances.get(ord(ch), 0) for ch in text[:-1]
        ) * spacing
        box_last = self.bboxes.get(ord(last))
        box_first = self.bboxes.get(ord(first))
        if box_last is None or box_first is None:
            # 缺字形包围盒时退回 advance 近似
            total = self.advance_units(text)
            effective = total + (spacing - 1.0) * self.advances.get(ord(last), 0)
            return effective / self.upem
        return (advance_before_last + box_last[1] - box_first[0]) / self.upem

    def cap_ratio(self) -> float:
        """大写字高相对 em 的比例。"""
        if not self.upem:
            return 0.7
        return self.cap_height / self.upem if self.cap_height else 0.7

    def missing_chars(self, text: str) -> list[str]:
        return sorted({ch for ch in text if ord(ch) not in self.advances})

    def ink_y_center(self, text: str) -> float:
        """整串文字墨迹的垂直中心（字体单位，相对基线）。"""
        boxes = [self.v_bboxes[ord(ch)] for ch in text if ord(ch) in self.v_bboxes]
        if not boxes:
            return self.cap_height / 2.0
        y_min = min(b[0] for b in boxes)
        y_max = max(b[1] for b in boxes)
        return (y_min + y_max) / 2.0


def _read_name(tt: TTFont, ids: tuple[int, ...]) -> str:
    if "name" not in tt:
        return ""
    best: dict[int, str] = {}
    for rec in tt["name"].names:
        if rec.nameID not in ids:
            continue
        try:
            value = rec.toUnicode().strip()
        except Exception:  # 个别字体编码损坏，跳过
            continue
        if not value:
            continue
        # 优先英文（Windows platform 3 / lang 0x409）
        priority = 0 if (rec.platformID == 3 and rec.langID == 0x409) else 1
        if rec.nameID not in best or priority == 0:
            best[rec.nameID] = value
    for nid in ids:
        if nid in best:
            return best[nid]
    return ""


def _cap_height(tt: TTFont) -> int:
    """大写字高（字体单位）。

    优先取实际字形包围盒而非 OS/2.sCapHeight —— 后者在手工改造过的
    字体里常常是过期值（例如本项目 Daziji 系列被整体上移后未同步更新，
    sCapHeight 只有真实值的一半）。
    """
    try:
        cmap = tt.getBestCmap() or {}
        if "glyf" in tt:
            glyf = tt["glyf"]
            heights: list[int] = []
            for ch in "HABCDEFGIJKLMNOPQRSTUVWXYZ":
                gname = cmap.get(ord(ch))
                if not gname:
                    continue
                glyph = glyf[gname]
                glyph.recalcBounds(glyf)
                y_max = getattr(glyph, "yMax", 0)
                if y_max:
                    heights.append(int(y_max))
            if heights:
                # 用中位数抗个别字母（如 O 的视觉溢出）干扰
                heights.sort()
                return heights[len(heights) // 2]
    except Exception:
        pass
    try:
        os2 = tt["OS/2"]
        if getattr(os2, "sCapHeight", 0):
            return int(os2.sCapHeight)
    except Exception:
        pass
    return 0


def _points_per_glyph(tt: TTFont) -> float:
    """估算字形轮廓平均节点数（取有映射的字形样本的中位数）。"""
    try:
        cmap = tt.getBestCmap() or {}
        if "glyf" not in tt:
            return 0.0
        glyf = tt["glyf"]
        counts: list[int] = []
        for code, gname in cmap.items():
            if code < 32:
                continue
            try:
                glyph = glyf[gname]
                if glyph.isComposite():
                    counts.append(sum(1 for _ in getattr(glyph, "components", [])) * 4)
                else:
                    counts.append(len(getattr(glyph, "coordinates", []) or []))
            except Exception:
                continue
            if len(counts) >= 400:
                break
        if not counts:
            return 0.0
        counts.sort()
        return float(counts[len(counts) // 2])
    except Exception:
        return 0.0


def _load_face(path: Path) -> FontFace | None:
    try:
        tt = TTFont(str(path), lazy=True)
    except Exception:
        return None
    try:
        family = _read_name(tt, _FAMILY_IDS)
        style = _read_name(tt, _STYLE_IDS) or "Regular"
        full = _read_name(tt, (4,)) or f"{family} {style}".strip()
        upem = int(tt["head"].unitsPerEm)
        cap = _cap_height(tt)
        glyph_count = len(tt.getGlyphOrder())
        is_mono = False
        try:
            is_mono = bool(tt["post"].isFixedPitch)
        except Exception:
            pass
        if not family:
            family = path.stem
        return FontFace(
            path=path,
            family=family,
            style=style,
            full_name=full,
            upem=upem,
            cap_height=cap,
            glyph_count=glyph_count,
            is_mono=is_mono,
            points_per_glyph=_points_per_glyph(tt),
        )
    except Exception:
        return None
    finally:
        try:
            tt.close()
        except Exception:
            pass


def _load_metrics(path: Path) -> FaceMetrics:
    tt = TTFont(str(path), lazy=True)
    try:
        upem = int(tt["head"].unitsPerEm)
        cap = _cap_height(tt)
        cmap = tt.getBestCmap() or {}
        hmtx = tt["hmtx"]
        advances: dict[int, int] = {}
        bboxes: dict[int, tuple[int, int]] = {}
        v_bboxes: dict[int, tuple[int, int]] = {}
        glyf = tt["glyf"] if "glyf" in tt else None
        for code, gname in cmap.items():
            try:
                advances[code] = int(hmtx[gname][0])
            except KeyError:
                continue
            if glyf is not None:
                try:
                    glyph = glyf[gname]
                    glyph.recalcBounds(glyf)
                    x_min = getattr(glyph, "xMin", 0)
                    x_max = getattr(glyph, "xMax", 0)
                    if x_max or x_min:
                        bboxes[code] = (int(x_min), int(x_max))
                    v_bboxes[code] = (
                        int(getattr(glyph, "yMin", 0)),
                        int(getattr(glyph, "yMax", 0)),
                    )
                except Exception:
                    pass
        return FaceMetrics(
            upem=upem,
            advances=advances,
            cap_height=cap,
            bboxes=bboxes,
            v_bboxes=v_bboxes,
        )
    finally:
        try:
            tt.close()
        except Exception:
            pass


def _system_font_dirs() -> list[Path]:
    dirs: list[Path] = []
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        dirs.append(Path(windir) / "Fonts")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    return [d for d in dirs if d.is_dir()]


class FontLibrary:
    """内置字体库。"""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory else paths.fonts_dir()
        self._faces: list[FontFace] | None = None
        self._metrics: dict[Path, FaceMetrics] = {}
        self._conf_path: Path | None = None

    # ---------- 扫描 ----------

    def scan(self, force: bool = False) -> list[FontFace]:
        if self._faces is not None and not force:
            return self._faces
        faces: list[FontFace] = []
        seen: dict[tuple[str, str], FontFace] = {}
        if self.directory.is_dir():
            for path in sorted(self.directory.iterdir()):
                if path.suffix.lower() not in FONT_SUFFIXES:
                    continue
                face = _load_face(path)
                if face is None:
                    continue
                key = (face.family.lower(), face.style.lower())
                if key in seen:
                    continue  # 同族同重名重复文件，保留先出现的
                seen[key] = face
                faces.append(face)

        # 内置目录没有时，补上白名单里的系统字体（如 Arial）
        for path in self._system_candidates():
            face = _load_face(path)
            if face is None:
                continue
            key = (face.family.lower(), face.style.lower())
            if key in seen:
                continue
            seen[key] = face
            faces.append(face)

        faces.sort(key=lambda f: (f.family.lower(), f.style.lower()))
        self._faces = faces
        return faces

    def _system_candidates(self) -> list[Path]:
        """白名单系统字体里，实际存在的文件。"""
        found: list[Path] = []
        for directory in _system_font_dirs():
            for filename in SYSTEM_FONT_FILES:
                path = directory / filename
                if path.is_file():
                    found.append(path)
        return found

    def faces(self) -> list[FontFace]:
        return self.scan()

    def families(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for face in self.scan():
            result.setdefault(face.family, [])
            if face.style not in result[face.family]:
                result[face.family].append(face.style)
        return dict(sorted(result.items(), key=lambda kv: kv[0].lower()))

    def find(self, family: str, style: str = "Regular") -> FontFace | None:
        faces = self.scan()
        if not faces:
            return None
        fam_l, sty_l = family.lower(), (style or "Regular").lower()
        for face in faces:
            if face.family.lower() == fam_l and face.style.lower() == sty_l:
                return face
        # 样式不存在时退回该族第一个
        for face in faces:
            if face.family.lower() == fam_l:
                return face
        return faces[0]

    def metrics(self, face: FontFace) -> FaceMetrics:
        if face.path not in self._metrics:
            self._metrics[face.path] = _load_metrics(face.path)
        return self._metrics[face.path]

    # ---------- fontconfig ----------

    def write_fontconfig(self, cache: Path | None = None) -> Path:
        """生成 fontconfig 配置，使 OpenSCAD 能加载内置字体。"""
        if self._conf_path is not None and self._conf_path.is_file():
            return self._conf_path

        cache = cache or (paths.cache_dir() / "fontconfig")
        cache.mkdir(parents=True, exist_ok=True)
        conf_path = cache.parent / "fonts.conf"

        dirs = [self.directory, *_system_font_dirs()]
        dir_xml = "\n".join(
            f"  <dir>{xml_escape.escape(str(d))}</dir>" for d in dirs if d and d.is_dir()
        )
        conf = (
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
            "<fontconfig>\n"
            f"{dir_xml}\n"
            f"  <cachedir>{xml_escape.escape(str(cache))}</cachedir>\n"
            "  <config><rescan><int>0</int></rescan></config>\n"
            "</fontconfig>\n"
        )
        conf_path.write_text(conf, encoding="utf-8")
        self._conf_path = conf_path
        return conf_path

    def env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """构造带 FONTCONFIG_FILE 的环境变量字典。"""
        env = dict(os.environ if base is None else base)
        env["FONTCONFIG_FILE"] = str(self.write_fontconfig())
        return env

    def verify_renderable(self, openscad_path: Path, face: FontFace) -> bool:
        """用 OpenSCAD 实际渲染一次，确认该字体真的能被解析。"""
        from . import openscad as osc

        return osc.can_resolve_font(openscad_path, face, self.env())
