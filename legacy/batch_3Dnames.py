#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
all_in_one.py

合并脚本：字体处理 + OpenSCAD 检测 + 批量 STL 生成
新增：GUI 初始化界面（Tkinter + tkinterdnd2 拖拽），可持久化配置

依赖（GUI 拖拽）：
    pip install tkinterdnd2

运行方式：
1) 直接运行（无参数） -> 打开 GUI
   python all_in_one.py

2) 命令行（保留原能力）
   python all_in_one.py check --openscad "D:\\OpenSCAD\\openscad.exe"
   python all_in_one.py batch --openscad ... --template ... --names ... --out ...
   python all_in_one.py font --input ... --name ... --width ... --y-offset ...
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# =========================
# 默认配置（初始值）
# =========================

def _app_dir() -> str:
    """程序所在目录。

    打包成 exe 后返回 exe 所在目录（而不是 PyInstaller 的临时解包目录），
    这样配置文件、模板、OpenSCAD 都固定在 exe 旁边，路径不会每次启动都变——
    路径一变，OpenSCAD 的字体缓存就失效，每个名字都要重扫系统字体（1~2 分钟/个）。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _detect_openscad() -> str:
    """按优先级找 OpenSCAD：exe 同级 → 项目便携版 → 系统安装版。"""
    candidates = [
        os.path.join(_app_dir(), "OpenSCAD", "openscad.exe"),
        r"D:\HA1\PJ1\OpenSCAD\openscad.exe",
        os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"), "OpenSCAD", "openscad.exe"
        ),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[0]


DEFAULT_OPENSCAD_PATH = _detect_openscad()
DEFAULT_SCAD_TEMPLATE = "stamp_template.scad"
# 留空而不是写死一个名字文件：默认填个不存在的 names1230.txt，
# 同事会以为已经选好了，点开始才报错。空着更直观。
DEFAULT_NAMES_TXT = ""
DEFAULT_OUTPUT_ROOT_DIR = "output_root"  # GUI 中会让用户选择（必须）；此处仅占位
DEFAULT_LETTER_SPACING: Optional[float] = 1.2  # None 表示不传

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

DEFAULT_FONT_INPUT = r"D:\HA1\PJ1\Special_Elite\SpecialElite-Regular.ttf"
DEFAULT_NEW_FONT_NAME = "Daziji_V5"
DEFAULT_CUSTOM_WIDTH = 1300
DEFAULT_Y_OFFSET = 200

# =========================
# 配置持久化
# =========================

CONFIG_FILE_NAME = "all_in_one_config.json"


@dataclass
class AppConfig:
    openscad_path: str = DEFAULT_OPENSCAD_PATH
    scad_template: str = DEFAULT_SCAD_TEMPLATE
    names_txt: str = DEFAULT_NAMES_TXT
    output_root_dir: str = ""  # 必选
    letter_spacing: Optional[float] = DEFAULT_LETTER_SPACING
    workers: int = 0  # 0 = 自动（按 CPU 核数，封顶 4）

    # font
    font_input: str = DEFAULT_FONT_INPUT
    new_font_name: str = DEFAULT_NEW_FONT_NAME
    custom_width: int = DEFAULT_CUSTOM_WIDTH
    y_offset: int = DEFAULT_Y_OFFSET


def _resource_dir() -> str:
    """只读资源目录。

    打包成 exe 后 PyInstaller 会把 --add-data 的内容解压到临时目录（sys._MEIPASS），
    模板文件在那里；未打包时就是脚本所在目录。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and os.path.isdir(meipass):
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def script_dir() -> str:
    """配置文件的落地目录：始终跟随 exe / 脚本，保证便携且路径稳定。"""
    return _app_dir()


def config_path() -> str:
    return os.path.join(script_dir(), CONFIG_FILE_NAME)


def load_config() -> AppConfig:
    p = config_path()
    if not os.path.isfile(p):
        return AppConfig()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        cfg = AppConfig()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return _heal_config(cfg)
    except Exception:
        # 配置损坏不阻塞运行，回退默认
        return AppConfig()


def _heal_config(cfg: AppConfig) -> AppConfig:
    """配置里的路径失效时自动纠正。

    典型场景：整个文件夹被拷到别的电脑 / 换了盘符，
    配置里记的是旧的绝对路径，直接沿用会报“找不到 OpenSCAD”。
    这里检测到不存在就重新探测一次，用户不用手动改。
    """
    if not cfg.openscad_path or not os.path.isfile(cfg.openscad_path):
        cfg.openscad_path = _detect_openscad()
    if cfg.scad_template and not os.path.isfile(_abs_in_script_dir(cfg.scad_template)):
        cfg.scad_template = DEFAULT_SCAD_TEMPLATE
    return cfg


def save_config(cfg: AppConfig) -> None:
    p = config_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)


def _abs_in_script_dir(path: str) -> str:
    """将相对路径解析成绝对路径。

    查找顺序：exe/脚本同级目录 → 打包资源目录。
    这样用户把自定义模板放在 exe 旁边可以覆盖内置模板，
    而内置模板在打包后位于临时解包目录也能被找到。
    """
    if not path:
        return path
    if os.path.isabs(path):
        return path
    for base in (script_dir(), _resource_dir()):
        candidate = os.path.join(base, path)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(script_dir(), path)


# =========================
# OpenSCAD / 批量生成
# =========================

def check_openscad(openscad_path: str) -> str:
    """调用 openscad -v 并返回版本输出（stdout 或 stderr）。"""
    if not openscad_path or not os.path.isfile(openscad_path):
        raise FileNotFoundError(f"找不到 OpenSCAD 可执行文件：{openscad_path}")

    try:
        result = subprocess.run(
            [openscad_path, "-v"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_no_window_kwargs(),
        )
        return (result.stdout or result.stderr or "").strip()
    except subprocess.CalledProcessError as e:
        msg = (e.stdout or "") + "\n" + (e.stderr or "")
        raise RuntimeError(f"OpenSCAD 返回错误：{msg.strip()}") from e


def load_names(path: str) -> List[str]:
    """从 txt 读取名字列表，一行一个，自动去掉空行和前后空格。"""
    if not path or not os.path.isfile(path):
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
        raise ValueError(f"字符数 {char_count} 在 BASE_LENGTH_MAP 中没有定义，请补充映射。")


def _derive_output_subfolder_name(names_txt_path: str) -> str:
    """
    规则：在用户选的根目录下创建名为 output_stlXXXX 的文件夹，
    其中 XXXX 来自 names 后面的数字，例如 names1211.txt -> output_stl1211
    若无法提取数字，则使用文件名 stem 作为后缀：namesABC.txt -> output_stl_namesABC
    """
    stem = Path(names_txt_path).stem  # names1211
    m = re.search(r"names(\d+)$", stem, flags=re.IGNORECASE)
    if m:
        return f"output_stl{m.group(1)}"
    # 尝试更宽松：names1211_anything -> 取 names 后连续数字
    m2 = re.search(r"names(\d+)", stem, flags=re.IGNORECASE)
    if m2:
        return f"output_stl{m2.group(1)}"
    return f"output_stl_{stem}"


# 文件名里不允许出现的字符（Windows）。名字本身不动，只影响落盘文件名。
_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _safe_filename(name: str) -> str:
    """把名字转成合法的 Windows 文件名。"""
    cleaned = _BAD_FILENAME_CHARS.sub("_", name).strip().strip(".")
    return cleaned or "unnamed"


def _no_window_kwargs() -> dict:
    """让子进程不弹黑框。

    打包成 --windowed 的 exe 后，每启动一次 openscad.exe 都会闪一个控制台窗口；
    加上 CREATE_NO_WINDOW 就不会了。非 Windows 平台返回空字典。
    """
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def _default_workers() -> int:
    """默认并发数：OpenSCAD 单次渲染是单线程吃满一个核，按核数开就行，
    但封顶 4 个——再多对机械硬盘和内存带宽反而没收益。"""
    cpu = os.cpu_count() or 2
    return max(1, min(4, cpu))



def batch_generate_stl(
    openscad_path: str,
    scad_template: str,
    names_txt: str,
    output_root_dir: str,
    base_length_map: Dict[int, int],
    letter_spacing: Optional[float] = None,
    log: Optional[callable] = None,
    workers: int = 0,
) -> str:
    """
    逐个名字调用 OpenSCAD 生成 STL。
    返回实际输出目录（output_root_dir 下创建的 output_stlXXXX）。

    workers: 并发渲染的进程数；0 表示按 CPU 核数自动取（封顶 4）。
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)
        else:
            print(msg)

    if not openscad_path or not os.path.isfile(openscad_path):
        raise FileNotFoundError(f"找不到 OpenSCAD 可执行文件：{openscad_path}")

    scad_template = _abs_in_script_dir(scad_template)
    if not scad_template or not os.path.isfile(scad_template):
        raise FileNotFoundError(f"找不到模板文件：{scad_template}")

    names_txt = os.path.abspath(names_txt)
    if not os.path.isfile(names_txt):
        raise FileNotFoundError(f"找不到名字列表文件：{names_txt}")

    if not output_root_dir:
        raise ValueError("输出根目录未选择。请在界面中选择输出文件夹。")
    output_root_dir = os.path.abspath(output_root_dir)
    if not os.path.isdir(output_root_dir):
        raise FileNotFoundError(f"输出根目录不存在：{output_root_dir}")

    # 输出目录：根目录下创建 output_stlXXXX
    subfolder = _derive_output_subfolder_name(names_txt)
    output_dir = os.path.join(output_root_dir, subfolder)
    os.makedirs(output_dir, exist_ok=True)

    names = load_names(names_txt)
    if not names:
        _log("名字列表文件里没有有效名字（可能全是空行），程序结束。")
        return output_dir

    _log(f"输出目录：{output_dir}")
    _log(f"模板：{scad_template}")
    _log(f"名字文件：{names_txt}")
    _log(f"OpenSCAD：{openscad_path}")
    _log(f"字间距 spacing：{'(不传)' if letter_spacing is None else letter_spacing}")

    # 去重但保持顺序：同名重复渲染纯属浪费，而且并发写同一个文件会写坏
    unique_names: List[str] = []
    seen = set()
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        unique_names.append(n)
    if len(unique_names) != len(names):
        _log(f"名字共 {len(names)} 行，去重后 {len(unique_names)} 个（重复的不再重复生成）")

    # 先按字符数过滤，避免每个任务里重复判断
    jobs: List[Tuple[int, str, int]] = []
    for idx, name in enumerate(unique_names, start=1):
        try:
            base_len = get_base_len(len(name), base_length_map)
        except ValueError as e:
            _log(f"[跳过] ({idx}/{len(unique_names)}) 名字 {name!r}：{e}")
            continue
        jobs.append((idx, name, base_len))

    if not jobs:
        _log("没有可生成的名字（字符数都不在底座长度映射里），程序结束。")
        return output_dir

    total = len(jobs)
    workers = int(workers or 0)
    if workers <= 0:
        workers = _default_workers()
    workers = max(1, min(workers, total))
    if workers > 1:
        _log(f"并发数：{workers}（同时跑 {workers} 个 OpenSCAD 进程）")
    else:
        _log("并发数：1（逐个生成）")

    done = {"ok": 0, "fail": 0}
    lock = threading.Lock()
    started_all = time.time()

    def _render_one(job: Tuple[int, str, int]) -> None:
        idx, name, base_len = job
        out_name = _safe_filename(name)
        if out_name != name:
            _log(f"[提示] 名字 {name!r} 含非法文件名字符，落盘为 {out_name}.stl")
        output_path = os.path.join(output_dir, f"{out_name}.stl")

        cmd = [
            openscad_path,
            "-o", output_path,
            "-D", f'name="{name}"',
            "-D", f"base_len={base_len}",
        ]
        if letter_spacing is not None:
            cmd += ["-D", f"letter_spacing={letter_spacing}"]
        cmd.append(scad_template)

        info = f"[生成] ({idx}/{total}) 名字: {name}, 字符数: {len(name)}, 底座长度: {base_len}mm"
        if letter_spacing is not None:
            info += f", 字间距: {letter_spacing}"
        _log(info)

        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_no_window_kwargs(),
            )
        except Exception as e:  # noqa: BLE001 - 单个名字失败不能拖垮整批
            with lock:
                done["fail"] += 1
            _log(f"[失败] {name}.stl 无法启动 OpenSCAD：{e}")
            return

        cost = time.time() - t0
        if proc.returncode != 0 or not os.path.isfile(output_path):
            with lock:
                done["fail"] += 1
            detail = (proc.stderr or proc.stdout or "").strip()
            detail = detail[-800:] if detail else "(无输出)"
            _log(f"[失败] {name}.stl 生成失败（{cost:.1f}s，返回码 {proc.returncode}）：\n{detail}")
            return

        size_kb = os.path.getsize(output_path) / 1024
        with lock:
            done["ok"] += 1
            n_done = done["ok"] + done["fail"]
        _log(f"[完成] ({n_done}/{total}) {out_name}.stl  {size_kb:.0f} KB  {cost:.1f}s")

    if workers == 1:
        for job in jobs:
            _render_one(job)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # list() 把异常抛出来，避免线程里的异常被静默吞掉
            list(pool.map(_render_one, jobs))

    elapsed = time.time() - started_all
    avg = elapsed / total if total else 0
    _log(
        f"全部处理完成：成功 {done['ok']} 个，失败 {done['fail']} 个，"
        f"总耗时 {elapsed:.1f}s（平均 {avg:.1f}s/个）"
    )
    if done["fail"]:
        _log("有失败项，请看上面的 [失败] 行里的 OpenSCAD 报错。")
    return output_dir



# =========================
# 字体修改（保留）
# =========================

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

    # C. 修改字体名称（nameID 1/4/6）
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


# =========================
# GUI（初始化界面）
# =========================

def run_gui() -> int:
    """
    初始化界面：
    1) 拖拽 names*.txt 进入（tkinterdnd2）
    2) 选择输出根目录（必须），保存配置
    3) 选择 OpenSCAD 路径、模板 scad、字间距 spacing（原硬编码项）
    4) 开始按钮 + 日志输出框
    5) 输出目录：<root>/output_stl#### （#### 来自 names 后数字）
    """
    # Tkinter import
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import filedialog, messagebox, ttk

    # Drag&Drop 支持（可选）
    DND_AVAILABLE = False
    TkBase = tk.Tk
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
        TkBase = TkinterDnD.Tk  # type: ignore
        DND_AVAILABLE = True
    except Exception:
        DND_AVAILABLE = False

    cfg = load_config()

    # 日志队列（后台线程 -> 主线程）
    log_q: "queue.Queue[str]" = queue.Queue()

    def ui_log(msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        log_q.put(f"[{ts}] {msg}")

    def normalize_dnd_path(raw: str) -> str:
        # tkinterdnd2 可能返回 "{C:/a b/c.txt}" 或多文件 "path1 path2"
        s = raw.strip()
        if s.startswith("{") and s.endswith("}"):
            s = s[1:-1]
        # 取第一个文件
        if " " in s and os.path.exists(s) is False:
            # 粗略解析：按空格拆分，找第一个存在的
            for part in s.split():
                p = part.strip("{}")
                if os.path.exists(p):
                    return p
        return s

    def validate_txt(path: str) -> Tuple[bool, str]:
        if not path:
            return False, "未选择名字 txt 文件。"
        if not os.path.isfile(path):
            return False, f"名字 txt 文件不存在：{path}"
        if not path.lower().endswith(".txt"):
            return False, "名字文件必须是 .txt"
        return True, ""

    def validate_required_folder(path: str) -> Tuple[bool, str]:
        if not path:
            return False, "输出根目录未选择。"
        if not os.path.isdir(path):
            return False, f"输出根目录不存在：{path}"
        return True, ""

    root = TkBase()
    root.title("STL 批量生成 - 初始化界面")
    root.geometry("900x640")

    def pick_ui_font(size: int = 9) -> Tuple[str, int]:
        """挑一个自带中文字形的字体。

        Tk 默认字体（Segoe UI / TkDefaultFont）里没有汉字，Windows 会临时
        回退到中文字体来画字，但行高仍按默认字体的度量算 —— 结果就是
        日志框里相邻两行互相压在一起。显式指定中文字体，行高才对得上。
        """
        try:
            families = set(tkfont.families(root))
        except Exception:
            families = set()
        for cand in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun"):
            if cand in families:
                return cand, size
        return "TkDefaultFont", size

    ui_font = pick_ui_font(9)

    # ---- 变量绑定
    var_openscad = tk.StringVar(value=cfg.openscad_path or DEFAULT_OPENSCAD_PATH)
    var_template = tk.StringVar(value=cfg.scad_template or DEFAULT_SCAD_TEMPLATE)
    var_names = tk.StringVar(value=cfg.names_txt or "")
    var_outroot = tk.StringVar(value=cfg.output_root_dir or "")
    var_spacing = tk.StringVar(value="" if cfg.letter_spacing is None else str(cfg.letter_spacing))
    var_workers = tk.StringVar(value=str(cfg.workers) if cfg.workers else "")

    # ---- 布局
    frm = ttk.Frame(root, padding=12)
    frm.pack(fill=tk.BOTH, expand=True)

    # 行工具函数
    def add_row(row: int, label: str, var: tk.StringVar, btn_text: str, btn_cmd):
        ttk.Label(frm, text=label, width=20).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
        ent = ttk.Entry(frm, textvariable=var)
        ent.grid(row=row, column=1, sticky="we", pady=6)
        btn = ttk.Button(frm, text=btn_text, command=btn_cmd, width=16)
        btn.grid(row=row, column=2, sticky="e", padx=(8, 0), pady=6)
        return ent

    frm.columnconfigure(1, weight=1)

    # OpenSCAD 路径
    def pick_openscad():
        p = filedialog.askopenfilename(
            title="选择 OpenSCAD 可执行文件",
            filetypes=[("OpenSCAD", "*.exe"), ("All files", "*.*")],
        )
        if p:
            var_openscad.set(p)

    add_row(0, "OpenSCAD 路径", var_openscad, "选择文件", pick_openscad)

    # 模板
    def pick_template():
        p = filedialog.askopenfilename(
            title="选择 stamp_template.scad",
            filetypes=[("OpenSCAD 脚本", "*.scad"), ("All files", "*.*")],
            initialdir=script_dir(),
        )
        if p:
            # 保存相对路径更便携（与脚本同目录时）
            try:
                p_rel = os.path.relpath(p, script_dir())
                var_template.set(p_rel)
            except Exception:
                var_template.set(p)

    add_row(1, "模板 scad", var_template, "选择文件", pick_template)

    # names txt（拖拽 + 按钮选择）
    def pick_names():
        p = filedialog.askopenfilename(
            title="选择名字列表 txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
            initialdir=script_dir(),
        )
        if p:
            var_names.set(p)

    ent_names = add_row(2, "名字 txt（可拖拽）", var_names, "选择文件", pick_names)

    # 输出根目录
    def pick_outroot():
        p = filedialog.askdirectory(title="选择输出根目录（必须）")
        if p:
            var_outroot.set(p)

    add_row(3, "输出根目录（必选）", var_outroot, "选择文件夹", pick_outroot)

    # spacing
    ttk.Label(frm, text="字间距 spacing", width=20).grid(row=4, column=0, sticky="w", padx=(0, 8), pady=6)
    ent_spacing = ttk.Entry(frm, textvariable=var_spacing)
    ent_spacing.grid(row=4, column=1, sticky="we", pady=6)

    ttk.Label(frm, text="提示：留空=不传；输入 -1=不传；其它为浮点数", foreground="#555").grid(
        row=4, column=2, sticky="e", padx=(8, 0), pady=6
    )

    # 并发数
    ttk.Label(frm, text="同时生成（并发数）", width=20).grid(
        row=5, column=0, sticky="w", padx=(0, 8), pady=6
    )
    ent_workers = ttk.Entry(frm, textvariable=var_workers)
    ent_workers.grid(row=5, column=1, sticky="we", pady=6)
    ttk.Label(
        frm,
        text=f"留空=自动（本机 {os.cpu_count() or 2} 核，封顶 4）",
        foreground="#555",
    ).grid(row=5, column=2, sticky="e", padx=(8, 0), pady=6)

    # 拖拽绑定
    if DND_AVAILABLE:
        try:
            ent_names.drop_target_register("DND_Files")
            ent_names.dnd_bind("<<Drop>>", lambda e: var_names.set(normalize_dnd_path(e.data)))
        except Exception:
            # 若绑定失败，不影响按钮选择
            pass
    else:
        ttk.Label(frm, text="未检测到 tkinterdnd2：拖拽不可用，可用“选择文件”。", foreground="#a00").grid(
            row=5, column=2, sticky="w", padx=(8, 0), pady=6
        )

    # 按钮区
    btn_bar = ttk.Frame(frm)
    btn_bar.grid(row=6, column=0, columnspan=3, sticky="we", pady=(8, 8))
    btn_bar.columnconfigure(0, weight=1)

    # 日志框
    txt = tk.Text(frm, height=18, wrap="word", font=ui_font, spacing1=1, spacing3=1)
    txt.grid(row=7, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(7, weight=1)

    # 滚动条
    yscroll = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
    yscroll.grid(row=7, column=3, sticky="ns")
    txt.configure(yscrollcommand=yscroll.set)

    def pump_log():
        try:
            while True:
                m = log_q.get_nowait()
                txt.insert("end", m + "\n")
                txt.see("end")
        except queue.Empty:
            pass
        root.after(80, pump_log)

    pump_log()

    # 配置保存（每次开始前保存）
    def persist_from_ui() -> AppConfig:
        # spacing 解析规则：空 / -1 / None => 不传
        s = (var_spacing.get() or "").strip()
        if s == "" or s == "-1":
            spacing_val = None
        else:
            try:
                spacing_val = float(s)
                if spacing_val < 0:
                    spacing_val = None
            except ValueError:
                raise ValueError("字间距 spacing 输入不合法：请输入空、-1 或浮点数（例如 1.2）。")

        # 并发数：留空 = 自动（0）
        w = (var_workers.get() or "").strip()
        if w == "":
            workers_val = 0
        else:
            try:
                workers_val = int(w)
            except ValueError:
                raise ValueError("并发数必须是整数（留空表示自动）。") from None
            if workers_val < 0:
                raise ValueError("并发数不能为负数（留空表示自动）。")

        new_cfg = AppConfig(
            openscad_path=var_openscad.get().strip(),
            scad_template=var_template.get().strip(),
            names_txt=var_names.get().strip(),
            output_root_dir=var_outroot.get().strip(),
            letter_spacing=spacing_val,
            workers=workers_val,
            font_input=cfg.font_input,
            new_font_name=cfg.new_font_name,
            custom_width=cfg.custom_width,
            y_offset=cfg.y_offset,
        )
        save_config(new_cfg)
        return new_cfg

    running_flag = {"running": False}

    def on_check():
        try:
            current = persist_from_ui()
        except Exception as e:
            messagebox.showerror("配置错误", str(e))
            return

        try:
            ver = check_openscad(current.openscad_path)
            ui_log("OpenSCAD 检测成功。版本信息：")
            ui_log(ver if ver else "(无输出)")
        except Exception as e:
            ui_log(f"OpenSCAD 检测失败：{e}")
            messagebox.showerror("OpenSCAD 检测失败", str(e))

    def worker_start(current: AppConfig):
        try:
            ui_log("开始任务：批量生成 STL")
            # 先检查 OpenSCAD
            ver = check_openscad(current.openscad_path)
            ui_log("OpenSCAD 版本： " + (ver if ver else "(无输出)"))

            out_dir = batch_generate_stl(
                openscad_path=current.openscad_path,
                scad_template=current.scad_template,
                names_txt=current.names_txt,
                output_root_dir=current.output_root_dir,
                base_length_map=DEFAULT_BASE_LENGTH_MAP,
                letter_spacing=current.letter_spacing,
                log=ui_log,
                workers=current.workers,
            )
            ui_log(f"任务完成。输出目录：{out_dir}")
        except Exception as e:
            ui_log(f"任务失败：{e}")
        finally:
            running_flag["running"] = False

    def on_start():
        if running_flag["running"]:
            return

        # 必选校验
        ok, msg = validate_txt(var_names.get().strip())
        if not ok:
            messagebox.showerror("缺少必要信息", msg)
            return

        ok2, msg2 = validate_required_folder(var_outroot.get().strip())
        if not ok2:
            messagebox.showerror("缺少必要信息", msg2)
            return

        try:
            current = persist_from_ui()
        except Exception as e:
            messagebox.showerror("配置错误", str(e))
            return

        running_flag["running"] = True
        t = threading.Thread(target=worker_start, args=(current,), daemon=True)
        t.start()

    def on_clear_log():
        txt.delete("1.0", "end")

    ttk.Button(btn_bar, text="检测 OpenSCAD", command=on_check).pack(side="left")
    ttk.Button(btn_bar, text="开始", command=on_start).pack(side="left", padx=(10, 0))
    ttk.Button(btn_bar, text="清空日志", command=on_clear_log).pack(side="left", padx=(10, 0))
    ttk.Button(btn_bar, text="退出", command=root.destroy).pack(side="right")

    # 窗口顶部提示
    tip = (
        "操作流程：\n"
        "1) 将 namesXXXX.txt 拖入“名字 txt”输入框（或点“选择文件”）\n"
        "2) 选择输出根目录（必选）\n"
        "3) OpenSCAD 路径 / 模板 / spacing / 并发数，改一次就会自动保存，下次沿用\n"
        "4) 点“开始”，日志在下方输出\n"
        "输出目录规则：<输出根目录>/output_stlXXXX（XXXX 来自 names 后数字）\n"
        "并发数留空即自动（按 CPU 核数，封顶 4），一个名字约 5~10 秒"
    )
    txt.insert("end", tip + "\n\n")
    txt.see("end")

    root.mainloop()
    return 0


# =========================
# CLI
# =========================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="all_in_one.py",
        description="合并脚本：字体处理 + OpenSCAD 检测 + 批量 STL 生成（含 GUI）",
    )
    sub = parser.add_subparsers(dest="cmd", required=False)

    # check
    p_check = sub.add_parser("check", help="检测 OpenSCAD 是否可调用并输出版本信息")
    p_check.add_argument("--openscad", default=DEFAULT_OPENSCAD_PATH, help="OpenSCAD 可执行文件路径")

    # batch
    p_batch = sub.add_parser("batch", help="批量调用 OpenSCAD 生成 STL（命令行）")
    p_batch.add_argument("--openscad", default=DEFAULT_OPENSCAD_PATH, help="OpenSCAD 可执行文件路径")
    p_batch.add_argument("--template", default=DEFAULT_SCAD_TEMPLATE, help="stamp_template.scad 路径（默认脚本目录）")
    p_batch.add_argument("--names", default=DEFAULT_NAMES_TXT, help="名字列表 txt（默认脚本目录）")
    p_batch.add_argument(
        "--outroot",
        default="",
        help="输出根目录（必填）。实际输出会创建子目录 output_stlXXXX",
    )
    p_batch.add_argument(
        "--spacing",
        type=float,
        default=DEFAULT_LETTER_SPACING,
        help="OpenSCAD text() spacing 参数；设为 -1 表示不传该参数",
    )
    p_batch.add_argument(
        "--workers",
        type=int,
        default=0,
        help="并发渲染进程数；0 表示自动（按 CPU 核数，封顶 4）",
    )

    # font
    p_font = sub.add_parser("font", help="修改字体（等宽/字宽、上移大写、改 name）")
    p_font.add_argument("--input", default=DEFAULT_FONT_INPUT, help="输入字体 ttf 路径")
    p_font.add_argument("--name", default=DEFAULT_NEW_FONT_NAME, help="新字体名称（Name 表）")
    p_font.add_argument("--width", type=int, default=DEFAULT_CUSTOM_WIDTH, help="统一字符宽度（advanceWidth）")
    p_font.add_argument("--y-offset", type=int, default=DEFAULT_Y_OFFSET, help="大写 A-Z 上移偏移量")
    p_font.add_argument("--output", default=None, help="输出字体路径（默认同目录：<name>.ttf）")

    return parser


def _ensure_streams() -> None:
    """保证 sys.stdout / sys.stderr 可用。

    打包成 --windowed 的 exe 后这两个是 None，任何 print 都会抛
    ``AttributeError: 'NoneType' object has no attribute 'write'``。
    命令行模式虽然看不到输出，但至少不该因为「打印日志」而崩溃。
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))
            except OSError:
                pass


def main(argv: Optional[List[str]] = None) -> int:
    _ensure_streams()
    parser = build_parser()
    args = parser.parse_args(argv)

    # 无子命令：默认启动 GUI（满足“初始化界面”需求）
    if args.cmd is None:
        return run_gui()

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
        scad_template = args.template
        names_txt = args.names
        out_root = args.outroot

        spacing = args.spacing
        letter_spacing = None if spacing is None or spacing < 0 else float(spacing)

        try:
            _ = check_openscad(openscad_path)
        except Exception as e:
            print(f"OpenSCAD 检测失败：{e}")
            return 2

        try:
            out_dir = batch_generate_stl(
                openscad_path=openscad_path,
                scad_template=scad_template,
                names_txt=names_txt,
                output_root_dir=out_root,
                base_length_map=DEFAULT_BASE_LENGTH_MAP,
                letter_spacing=letter_spacing,
                log=lambda m: print(m),
                workers=args.workers,
            )
            print("输出目录：", out_dir)
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


def _write_crash_log(exc: BaseException) -> None:
    """windowed exe 崩了是「双击没反应」，什么提示都没有。
    把 traceback 写到 exe 旁边的日志里，出问题至少能查。"""
    import traceback

    path = os.path.join(script_dir(), "PJ1Program_crash.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("\n===== %Y-%m-%d %H:%M:%S =====\n"))
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except OSError:
        pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - 兜底写日志再退出
        _write_crash_log(exc)
        raise
