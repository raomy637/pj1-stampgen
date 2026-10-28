"""字体预览条：用 Pillow 直接读内置 ttf 渲染，不需要安装到系统。

为什么不直接让 Tk 用 ``font=(family, size)``：内置字体没装进系统，
Tk 根本找不到它。Pillow 的 ``ImageFont.truetype(path)`` 可以直接按文件路径
加载，还能用 ``stroke_width`` 模拟 OpenSCAD 的 ``offset(delta)`` 几何加粗。
"""

from __future__ import annotations

from pathlib import Path

PREVIEW_SAMPLES = {
    "keep": "ABCDE abcde 0123",
    "upper": "ABCDE ABCDE 0123",
    "lower": "abcde abcde 0123",
    "capitalize": "Abcde Abcde 0123",
}
"""预览文本。含大小写混排 + 数字，换字体时差异最明显。"""

SCALE_CANDIDATES = (8.0, 7.0, 6.0, 5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0)
"""候选比例（像素/毫米），从大到小试。

8 px/mm 下 6mm 字号的大写字高约 35px，字形细节看得清；字号特别大或
名字特别长时逐级缩小，保证整条塞进预览框。
"""

PAD = 10


def sample_text(case_mode: str, first_name: str = "") -> str:
    """预览要渲染的文字：固定样例 + 清单里的第一个名字。"""
    sample = PREVIEW_SAMPLES.get(case_mode, PREVIEW_SAMPLES["keep"])
    return f"{sample}   {first_name}" if first_name else sample


def render_preview(
    font_path: Path | str,
    text: str,
    size_mm: float,
    weight_mm: float = 0.0,
    max_px: int = 900,
    max_height_px: int = 74,
    fg: str = "#1a1a18",
    bg: str = "#fbfbf9",
):
    """渲染预览图，返回 ``(PIL.Image, 像素/毫米)``；Pillow 不可用或字体坏了返回 None。"""
    if not text:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None

    size_mm = max(0.5, float(size_mm))
    weight_mm = max(0.0, float(weight_mm))

    for scale in SCALE_CANDIDATES:
        px = max(6, int(round(size_mm * scale)))
        try:
            font = ImageFont.truetype(str(font_path), px)
        except Exception:
            return None
        stroke = max(0, int(round(weight_mm * scale)))
        try:
            box = font.getbbox(text, stroke_width=stroke)
        except TypeError:  # 老版本 Pillow 不支持 stroke_width
            box = font.getbbox(text)
        width = box[2] - box[0] + 2 * PAD
        height = box[3] - box[1] + 2 * PAD
        too_wide = width > max_px
        too_tall = height > max_height_px
        if (too_wide or too_tall) and scale != SCALE_CANDIDATES[-1]:
            continue
        image = Image.new("RGB", (max(width, 24), max(height, 24)), bg)
        draw = ImageDraw.Draw(image)
        draw.text(
            (PAD - box[0], PAD - box[1]),
            text,
            font=font,
            fill=fg,
            stroke_width=stroke,
            stroke_fill=fg,
        )
        return image, scale
    return None
