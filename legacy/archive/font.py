from fontTools.ttLib import TTFont
import os

# ================= 自定义设置区域 =================
# 1. 原始文件路径（请确保这个文件存在！）
input_path = r"D:\download\Special_Elite\SpecialElite-Regular.ttf"

# 2. 你想给新字体起的名字（用于 PS 列表显示）
new_font_name = "Daziji_V5"

# 3. 字间距设置 (Width)：
# 标准 Pica 建议在 600-720 之间。值越大，字间距越宽。
custom_width = 1300

# 4. 大写偏移量 (Shift)：
# 0 不偏移，60 左右会有明显的机械不齐感。
y_offset = 200
# =================================================

# 自动定位输出文件夹
folder = os.path.dirname(input_path)
output_path = os.path.join(folder, f"{new_font_name}.ttf")

if not os.path.exists(input_path):
    print(f"错误：找不到原始文件！请检查路径：{input_path}")
else:
    font = TTFont(input_path)

    # --- A. 处理等宽和自定义间距 ---
    hmtx = font['hmtx']
    for glyph_name in hmtx.metrics:
        # 获取当前的左边距 (lsb)
        lsb = hmtx[glyph_name][1]
        # 统一宽度
        hmtx[glyph_name] = (custom_width, lsb)

    # --- B. 处理大写字母上移 (修正了 glyf 的拼写) ---
    glyf_table = font['glyf']  # 之前这里写成了 'gyf'
    cmap = font.getBestCmap()

    for char_code in range(ord('A'), ord('Z') + 1):
        glyph_name = cmap.get(char_code)
        if glyph_name and glyph_name in glyf_table:
            glyph = glyf_table[glyph_name]

            # 处理简单字形
            if hasattr(glyph, 'coordinates'):
                glyph.coordinates.translate((0, y_offset))
                bounds = glyph.recalcBounds(glyf_table)
                if bounds:
                    glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax = bounds

            # 处理复合字形
            elif glyph.isComposite():
                for component in glyph.components:
                    component.y += y_offset

    # --- C. 强力修改字体名称 (ID 1, 4, 6 是 PS 识别的关键) ---
    for record in font['name'].names:
        # ID 1: Family Name, ID 4: Full Name, ID 6: PostScript Name
        if record.nameID in [1, 4, 6]:
            record.string = new_font_name.encode(record.getEncoding())

    # --- D. 声明等宽属性 ---
    font['post'].isFixedPitch = 1
    if 'OS/2' in font:
        font['OS/2'].panose.bProportion = 9

        # 保存文件
    font.save(output_path)
    print(f"\n--- 任务成功完成！ ---")
    print(f"1. 新字体名称: {new_font_name}")
    print(f"2. 字符宽度 (Pitch): {custom_width}")
    print(f"3. 上移偏移量: {y_offset}")
    print(f"4. 文件路径: {output_path}")
    print(f"\n提示：请去文件夹双击安装 '{new_font_name}.ttf'，然后重启 PS 即可。")