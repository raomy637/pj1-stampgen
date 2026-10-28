import os
import subprocess

# ---------------- 配置区域 ----------------

# 1. OpenSCAD 可执行文件路径
OPENSCAD_PATH = r"D:\OpenSCAD\openscad.exe"   # 按你的真实路径来

# 2. 当前脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 3. OpenSCAD 模板文件（和 main.py 同目录）
SCAD_TEMPLATE = os.path.join(BASE_DIR, "stamp_template.scad")

# 4. 名字列表 txt 文件（每行一个名字）
NAMES_TXT = os.path.join(BASE_DIR, "names1230.txt")

# 5. 输出 STL 的文件夹
OUTPUT_DIR = os.path.join(BASE_DIR, "output_stl")

# 6. 字符数 → 底座长度(mm) 映射表
BASE_LENGTH_MAP = {
    2: 18,
    3: 24,
    4: 30,
    5: 36,
    6: 42,
    7: 48,
    8: 54,
    9: 60,
    10: 60,
    11: 65,
    12: 65,
    13: 65,
}

# 7. 字间距系数（OpenSCAD text() 的 spacing 参数）
#    1.0 = 默认；1.1/1.2 会更松；建议先从 1.15 试起
LETTER_SPACING = 1.2

# ------------------------------------------------------


def get_base_len(char_count: int) -> int:
    """根据字符数返回底座长度，没有定义的字符数会报错。"""
    try:
        return BASE_LENGTH_MAP[int(char_count)]
    except KeyError:
        raise ValueError(
            f"字符数 {char_count} 在 BASE_LENGTH_MAP 中没有定义，"
            f"请在脚本顶部的 BASE_LENGTH_MAP 里补充映射。"
        )


def load_names(path: str):
    """从 names.txt 读取名字列表，一行一个，自动去掉空行和前后空格。"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到名字列表文件：{path}")
    names = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name:
                continue
            names.append(name)
    return names


def main():
    # 0. 基础检查
    if not os.path.isfile(OPENSCAD_PATH):
        raise FileNotFoundError(f"找不到 OpenSCAD 可执行文件：{OPENSCAD_PATH}")

    if not os.path.isfile(SCAD_TEMPLATE):
        raise FileNotFoundError(f"找不到模板文件 stamp_template.scad：{SCAD_TEMPLATE}")

    # 1. 读取名字列表
    names = load_names(NAMES_TXT)
    if not names:
        print("names.txt 里没有有效名字（全是空行？），程序结束。")
        return

    # 2. 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 3. 逐个名字生成 STL
    for name in names:
        # 计算字符数：这里直接使用 len(name)
        char_count = len(name)

        try:
            base_len = get_base_len(char_count)
        except ValueError as e:
            print(f"[跳过] 名字 {name!r}：{e}")
            continue

        output_path = os.path.join(OUTPUT_DIR, f"{name}.stl")

        cmd = [
            OPENSCAD_PATH,
            "-o", output_path,
            "-D", f'name="{name}"',
            "-D", f"base_len={base_len}",
            "-D", f"letter_spacing={LETTER_SPACING}",  # ✅ 新增：传入字间距
            SCAD_TEMPLATE,
        ]

        print(f"[生成] 名字: {name}, 字符数: {char_count}, 底座长度: {base_len}mm, 字间距: {LETTER_SPACING}")
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[OpenSCAD 错误] 生成 {name}.stl 失败：{e}")
            continue

    print("全部处理完成。输出目录：", OUTPUT_DIR)


if __name__ == "__main__":
    main()
