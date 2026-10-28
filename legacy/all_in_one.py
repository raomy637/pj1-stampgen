#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
all_in_one.py

将以下脚本合并为单文件：
- font.py：使用 fontTools 修改字体（等宽/字宽、上移大写、改 name 表、声明等宽）
- tesy.py：检测 OpenSCAD 是否可调用（输出版本）
- main.py / beifen1.py：批量调用 OpenSCAD + stamp_template.scad 生成 STL

用法示例：
1) 检查 OpenSCAD 版本
   python all_in_one.py check

2) 批量生成 STL（默认使用脚本顶部 DEFAULT_* 配置）
   python all_in_one.py batch

3) 指定名字列表/字间距/输出目录
   python all_in_one.py batch --names names1230.txt --spacing 1.2 --out output_stl

4) 修改字体
   python all_in_one.py font --input "D:\\download\\Special_Elite\\SpecialElite-Regular.ttf" --name Daziji_V5 --width 1300 --y-offset 200

说明：
- 本脚本默认配置与 main.py（names1230.txt + spacing 参数）一致；如你想沿用 beifen1.py（names.txt 且不传 spacing），
  直接在 batch 子命令中指定 --names names.txt，并且不传 --spacing 或者显式传 1.0 即可。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

# =======================================================
# 默认配置（与原脚本保持一致，可按需改）
# =======================================================

# 1) OpenSCAD 可执行文件路径
DEFAULT_OPENSCAD_PATH = r"D:\OpenSCAD\openscad.exe"

# 2) OpenSCAD 模板文件（默认与本脚本同目录）
DEFAULT_SCAD_TEMPLATE = "stamp_template.scad"

# 3) 名字列表 txt 文件（默认与本脚本同目录）
DEFAULT_NAMES_TXT = ("names0101.txt")  # 对应 main.py；beifen1.py 是 names.txt

# 4) 输出 STL 文件夹（默认与本脚本同目录）
DEFAULT_OUTPUT_DIR = "output_stl"

# 5) 字符数 → 底座长度(mm) 映射表
DEFAULT_BASE_LENGTH_MAP: Dict[int, int] = {
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

# 6) OpenSCAD text() spacing 参数（main.py 的 LETTER_SPACING）
DEFAULT_LETTER_SPACING: Optional[float] = 1.2  # None 表示不传该 -D 参数

# 7) 字体修改默认参数（font.py）
DEFAULT_FONT_INPUT = r"D:\download\Special_Elite\SpecialElite-Regular.ttf"
DEFAULT_NEW_FONT_NAME = "Daziji_V5"
DEFAULT_CUSTOM_WIDTH = 1300
DEFAULT_Y_OFFSET = 200


# =======================================================
# 业务函数：OpenSCAD 检测、批量 STL 生成、字体修改
# =======================================================

def _abs_in_script_dir(path: str) -> str:
    """将相对路径解析到本脚本所在目录。"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return path if os.path.isabs(path) else os.path.join(base_dir, path)


def check_openscad(openscad_path: str) -> str:
    """调用 openscad -v 并返回版本输出（stdout 或 stderr）。"""
    if not os.path.isfile(openscad_path):
        raise FileNotFoundError(f"找不到 OpenSCAD 可执行文件：{openscad_path}")

    try:
        result = subprocess.run(
            [openscad_path, "-v"],
            check=True,
            capture_output=True,
            text=True,
        )
        return (result.stdout or result.stderr or "").strip()
    except subprocess.CalledProcessError as e:
        # OpenSCAD 有时会把版本打印到 stderr；但这里 check=True 若非 0 退出则抛错
        msg = (e.stdout or "") + "\n" + (e.stderr or "")
        raise RuntimeError(f"OpenSCAD 返回错误：{msg.strip()}") from e


def load_names(path: str) -> List[str]:
    """从 txt 读取名字列表，一行一个，自动去掉空行和前后空格。"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到名字列表文件：{path}")
    names: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if name:
                names.append(name)
    return names


def get_base_len(char_count: int, base_length_map: Dict[int, int]) -> int:
    """根据字符数返回底座长度，没有定义会报错。"""
    try:
        return base_length_map[int(char_count)]
    except KeyError:
        raise ValueError(
            f"字符数 {char_count} 在 BASE_LENGTH_MAP 中没有定义，请补充映射。"
        )


def batch_generate_stl(
    openscad_path: str,
    scad_template: str,
    names_txt: str,
    output_dir: str,
    base_length_map: Dict[int, int],
    letter_spacing: Optional[float] = None,
) -> None:
    """逐个名字调用 OpenSCAD 生成 STL。"""
    if not os.path.isfile(openscad_path):
        raise FileNotFoundError(f"找不到 OpenSCAD 可执行文件：{openscad_path}")
    if not os.path.isfile(scad_template):
        raise FileNotFoundError(f"找不到模板文件：{scad_template}")

    names = load_names(names_txt)
    if not names:
        print("名字列表文件里没有有效名字（可能全是空行），程序结束。")
        return

    os.makedirs(output_dir, exist_ok=True)

    for name in names:
        char_count = len(name)
        try:
            base_len = get_base_len(char_count, base_length_map)
        except ValueError as e:
            print(f"[跳过] 名字 {name!r}：{e}")
            continue

        output_path = os.path.join(output_dir, f"{name}.stl")

        cmd = [
            openscad_path,
            "-o", output_path,
            "-D", f'name="{name}"',
            "-D", f"base_len={base_len}",
        ]

        if letter_spacing is not None:
            cmd += ["-D", f"letter_spacing={letter_spacing}"]

        cmd.append(scad_template)

        info = f"[生成] 名字: {name}, 字符数: {char_count}, 底座长度: {base_len}mm"
        if letter_spacing is not None:
            info += f", 字间距: {letter_spacing}"
        print(info)

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[OpenSCAD 错误] 生成 {name}.stl 失败：{e}")
            continue

    print("全部处理完成。输出目录：", output_dir)


def modify_font(
    input_path: str,
    new_font_name: str,
    custom_width: int,
    y_offset: int,
    output_path: Optional[str] = None,
) -> str:
    """
    修改字体：
    - 统一 hmtx 的 advanceWidth（等宽/字距）
    - 上移 A-Z（简单字形 + 复合字形）
    - 修改 name 表（nameID 1/4/6）
    - 设置 post.isFixedPitch、OS/2 panose 比例
    返回输出字体路径。
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError as e:
        raise ImportError("缺少依赖 fontTools：请先 pip install fonttools") from e

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"错误：找不到原始字体文件：{input_path}")

    if output_path is None:
        folder = os.path.dirname(input_path)
        output_path = os.path.join(folder, f"{new_font_name}.ttf")

    font = TTFont(input_path)

    # A. 处理等宽和自定义间距（hmtx）
    hmtx = font["hmtx"]
    for glyph_name in list(hmtx.metrics.keys()):
        lsb = hmtx[glyph_name][1]
        hmtx[glyph_name] = (int(custom_width), lsb)

    # B. 处理大写字母上移（glyf + cmap）
    glyf_table = font["glyf"]
    cmap = font.getBestCmap() or {}

    for char_code in range(ord("A"), ord("Z") + 1):
        glyph_name = cmap.get(char_code)
        if not glyph_name or glyph_name not in glyf_table:
            continue
        glyph = glyf_table[glyph_name]

        # 简单字形
        if hasattr(glyph, "coordinates"):
            glyph.coordinates.translate((0, int(y_offset)))
            bounds = glyph.recalcBounds(glyf_table)
            if bounds:
                glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax = bounds

        # 复合字形
        elif glyph.isComposite():
            for component in glyph.components:
                component.y += int(y_offset)

    # C. 强力修改字体名称（nameID 1/4/6）
    if "name" in font:
        for record in font["name"].names:
            if record.nameID in (1, 4, 6):
                record.string = new_font_name.encode(record.getEncoding())

    # D. 声明等宽属性
    if "post" in font:
        font["post"].isFixedPitch = 1
    if "OS/2" in font:
        font["OS/2"].panose.bProportion = 9

    font.save(output_path)
    return output_path


# =======================================================
# CLI
# =======================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="all_in_one.py",
        description="合并脚本：字体处理 + OpenSCAD 检测 + 批量 STL 生成",
    )
    # 方案 B：子命令非强制，允许“裸跑”
    sub = parser.add_subparsers(dest="cmd", required=False)

    # check
    p_check = sub.add_parser("check", help="检测 OpenSCAD 是否可调用并输出版本信息")
    p_check.add_argument(
        "--openscad",
        default=DEFAULT_OPENSCAD_PATH,
        help="OpenSCAD 可执行文件路径",
    )

    # batch
    p_batch = sub.add_parser("batch", help="批量调用 OpenSCAD 生成 STL")
    p_batch.add_argument(
        "--openscad",
        default=DEFAULT_OPENSCAD_PATH,
        help="OpenSCAD 可执行文件路径",
    )
    p_batch.add_argument(
        "--template",
        default=DEFAULT_SCAD_TEMPLATE,
        help="stamp_template.scad 路径（默认脚本目录）",
    )
    p_batch.add_argument(
        "--names",
        default=DEFAULT_NAMES_TXT,
        help="名字列表 txt（默认脚本目录）",
    )
    p_batch.add_argument(
        "--out",
        default=DEFAULT_OUTPUT_DIR,
        help="输出 STL 文件夹（默认脚本目录）",
    )
    p_batch.add_argument(
        "--spacing",
        type=float,
        default=DEFAULT_LETTER_SPACING,
        help="OpenSCAD text() spacing 参数；设为 -1 表示不传该参数（等同 beifen1.py）",
    )

    # font
    p_font = sub.add_parser("font", help="修改字体（等宽/字宽、上移大写、改 name）")
    p_font.add_argument("--input", default=DEFAULT_FONT_INPUT, help="输入字体 ttf 路径")
    p_font.add_argument("--name", default=DEFAULT_NEW_FONT_NAME, help="新字体名称")
    p_font.add_argument("--width", type=int, default=DEFAULT_CUSTOM_WIDTH, help="统一字符宽度")
    p_font.add_argument("--y-offset", type=int, default=DEFAULT_Y_OFFSET, help="大写 A-Z 上移偏移量")
    p_font.add_argument("--output", default=None, help="输出字体路径")

    return parser



def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # 方案 B：不写子命令时，自动等价于 batch
    if args.cmd is None:
        args = parser.parse_args(["batch"])

    cmd = args.cmd

    if cmd == "check":
        try:
            ver = check_openscad(args.openscad)
            print("调用成功，版本信息：")
            print(ver if ver else "(无输出)")
            return 0
        except Exception as e:
            print(str(e))
            return 2

    if cmd == "batch":
        openscad_path = args.openscad
        scad_template = _abs_in_script_dir(args.template)
        names_txt = _abs_in_script_dir(args.names)
        output_dir = _abs_in_script_dir(args.out)

        spacing = args.spacing
        letter_spacing = None if spacing is None or spacing < 0 else float(spacing)

        try:
            _ = check_openscad(openscad_path)
        except Exception as e:
            print(f"OpenSCAD 检测失败：{e}")
            return 2

        try:
            batch_generate_stl(
                openscad_path=openscad_path,
                scad_template=scad_template,
                names_txt=names_txt,
                output_dir=output_dir,
                base_length_map=DEFAULT_BASE_LENGTH_MAP,
                letter_spacing=letter_spacing,
            )
            return 0
        except Exception as e:
            print(str(e))
            return 2

    if cmd == "font":
        try:
            out = modify_font(
                input_path=args.input,
                new_font_name=args.name,
                custom_width=args.width,
                y_offset=args.y_offset,
                output_path=args.output,
            )
            print("\n--- 任务成功完成！ ---")
            print(f"1. 新字体名称: {args.name}")
            print(f"2. 字符宽度 (Pitch): {args.width}")
            print(f"3. 上移偏移量: {args.y_offset}")
            print(f"4. 文件路径: {out}")
            return 0
        except Exception as e:
            print(str(e))
            return 2

    parser.print_help()
    return 1



if __name__ == "__main__":
    raise SystemExit(main())
