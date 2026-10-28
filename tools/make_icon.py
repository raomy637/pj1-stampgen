"""生成应用图标 assets/stampgen.ico。

以 1024px 超采样绘制后降采样，保证小尺寸下边缘干净。
图标语义：一枚印章压在纸面上，下方是压出的名字痕迹。

用法：python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
CANVAS = 1024
ICO_SIZES = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]

BG_TOP = (15, 110, 86)
BG_BOTTOM = (4, 52, 44)
BODY = (240, 249, 245)
BODY_SHADE = (206, 232, 222)
IMPRINT = (250, 238, 218)
ACCENT = (239, 159, 39)


def _rounded(draw: ImageDraw.ImageDraw, box, radius, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_icon() -> Image.Image:
    """一枚字母「压」在底座上，下方一道压印痕。

    只保留三个大色块，保证 16px 下仍可辨认。
    """
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = int(CANVAS * 0.22)
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, CANVAS, CANVAS), radius=radius, fill=255)
    gradient = Image.new("RGBA", (1, CANVAS))
    for y in range(CANVAS):
        t = y / (CANVAS - 1)
        gradient.putpixel(
            (0, y),
            (
                int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
                int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
                int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
                255,
            ),
        )
    img.paste(gradient.resize((CANVAS, CANVAS)), (0, 0), mask)

    # 字母：用系统里最粗的无衬线字体，笔画粗才抗缩放
    glyph = "A"
    font = None
    for candidate in ("ariblk.ttf", "arialbd.ttf", "seguibl.ttf"):
        path = Path(r"C:\Windows\Fonts") / candidate
        if path.is_file():
            try:
                from PIL import ImageFont

                font = ImageFont.truetype(str(path), int(CANVAS * 0.52))
                break
            except Exception:
                continue
    if font is None:
        from PIL import ImageFont

        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), glyph, font=font)
    gw, gh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    gx = (CANVAS - gw) / 2 - bbox[0]
    gy = CANVAS * 0.30 - gh / 2 - bbox[1]
    draw.text((gx, gy), glyph, font=font, fill=BODY)

    # 底座：紧贴字母下方的一根粗条
    base_w = int(CANVAS * 0.60)
    base_h = int(CANVAS * 0.105)
    base_x = (CANVAS - base_w) // 2
    base_y = int(CANVAS * 0.585)
    _rounded(draw, (base_x, base_y, base_x + base_w, base_y + base_h), int(CANVAS * 0.03), BODY)

    # 压印痕：底座下方一道强调色细线
    line_w = int(CANVAS * 0.42)
    line_y = int(CANVAS * 0.755)
    _rounded(
        draw,
        ((CANVAS - line_w) // 2, line_y, (CANVAS + line_w) // 2, line_y + int(CANVAS * 0.032)),
        int(CANVAS * 0.016),
        ACCENT,
    )
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    img = draw_icon()
    png_path = ASSETS / "stampgen.png"
    img.resize((256, 256), Image.LANCZOS).save(png_path)

    ico_path = ASSETS / "stampgen.ico"
    img.save(ico_path, format="ICO", sizes=ICO_SIZES)
    print(f"已生成：{ico_path}")
    print(f"已生成：{png_path}")


if __name__ == "__main__":
    main()
