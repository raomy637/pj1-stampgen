"""Tkinter 图形界面。

布局分五块（自上而下）：

1. 印章几何：底座宽/高、最长不超过、左右留白、字体高度
2. 字体：字体/字重/字号/字间距/几何加粗/大小写 + 实时预览条
3. 配置（自动探测，左）与名字清单（右，带行号可粘贴）
4. 结果预览表 + 运行日志
5. 底部操作栏

参数一改就自动刷新（250ms 防抖），不需要「预览拟合」按钮；
所有设置写入 ``stampgen_config.json``，下次启动自动恢复。
"""

from __future__ import annotations

import os
import queue
import threading
import traceback
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import batch as batch_mod
from .. import console, metrics, paths, validate
from ..config import CASE_LABELS, AppConfig, load_config, save_config
from ..fonts import FontFace, FontLibrary
from . import fontpreview

APP_TITLE = "名字印章生成器"
COLOR_OK = "#0f6e56"
COLOR_WARN = "#854f0b"
COLOR_ERR = "#a32d2d"
COLOR_MUTED = "#5f5e5a"
COLOR_INFO = "#185fa5"
COLOR_PREVIEW_BG = "#fbfbf9"
COLOR_PREVIEW_BORDER = "#d8d8d4"

BUILTIN_TEMPLATE_LABEL = "（内置模板）"
"""打包运行时内置模板在 %TEMP%\\_MEIxxxxx\\ 里，路径每次启动都变。

界面上直接显示那个临时路径会让人以为要维护它，所以只显示这个占位文案；
用户真要自定义模板，点「选择文件」指到自己的 .scad 即可。
"""

_FIELD_LABELS = {
    "base_width_mm": ("底座宽度", "mm"),
    "base_height_mm": ("底座高度", "mm"),
    "max_width_mm": ("最长不超过", "mm"),
    "margin_mm": ("左右留白", "mm"),
    "letter_height_mm": ("字体高度", "mm"),
    "font_size_mm": ("字号", "mm"),
    "letter_spacing": ("字间距", ""),
    "weight_offset_mm": ("几何加粗", "mm"),
}
"""「采用」之后要在状态栏说清改了哪个参数，这里是字段 → 中文名 + 单位。"""

STATUS_MAX_CHARS = 66
"""状态栏最多显示的字数。超出截断并加省略号 —— 完整信息看日志。"""


def _enable_dpi_awareness() -> None:
    """Windows 高分屏下避免界面模糊。"""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _read_text_file(path: Path) -> str:
    """读文本，UTF-8 优先，失败退回 GBK（老 txt 常是 GBK）。"""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class StampApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.library = FontLibrary()
        self.cfg: AppConfig = load_config()
        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None

        self._names_source_txt = ""
        """名字清单来自哪个 txt；为空表示用户直接粘贴的。决定输出目录命名。"""

        self._preview_photo = None
        self._row_detail: dict[str, str] = {}
        self._hover_iid = ""
        self._tip: tk.Toplevel | None = None
        self._preview_job: str | None = None
        self._persist_job: str | None = None
        self._spec_widgets: dict[str, ttk.Entry] = {}
        """字段名 → 输入框，用于「采用」之后聚焦选中。"""

        root.title(APP_TITLE)
        root.geometry("1160x920")
        root.minsize(1040, 800)
        self._set_icon()

        self._build_vars()
        self._build_ui()
        self._refresh_fonts()
        self._load_cfg_into_ui()
        self._poll_queue()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- 图标 ----------------

    def _set_icon(self) -> None:
        icon = paths.icon_path()
        if not icon.is_file():
            return
        try:
            self.root.iconbitmap(default=str(icon))
        except Exception:
            pass

    # ---------------- 变量 ----------------

    def _build_vars(self) -> None:
        spec = self.cfg.spec

        # 印章几何
        self.var_base_w = tk.StringVar(value=f"{spec.base_width_mm:g}")
        self.var_base_h = tk.StringVar(value=f"{spec.base_height_mm:g}")
        self.var_max_w = tk.StringVar(value=f"{spec.max_width_mm:g}")
        self.var_margin = tk.StringVar(value=f"{spec.margin_mm:g}")
        self.var_letter_h = tk.StringVar(value=f"{spec.letter_height_mm:g}")
        self.var_widen = tk.BooleanVar(value=spec.widen_base_per_name)

        # 字体
        self.var_family = tk.StringVar()
        self.var_style = tk.StringVar()
        self.var_size = tk.StringVar(value=f"{spec.font_size_mm:g}")
        self.var_spacing = tk.StringVar(value=f"{spec.letter_spacing:g}")
        self.var_weight = tk.StringVar(value=f"{spec.weight_offset_mm:g}")
        self.var_case = tk.StringVar(value=CASE_LABELS.get(spec.effective_case(), "保持原样"))
        self._case_label_to_key = {v: k for k, v in CASE_LABELS.items()}

        # 其它
        self.var_workers = tk.StringVar(
            value="" if not self.cfg.workers else str(self.cfg.workers)
        )
        self.var_outroot = tk.StringVar()
        self.var_out_hint = tk.StringVar(value="实际输出：—")
        self.var_open_after = tk.BooleanVar(value=self.cfg.open_output_after_run)
        self.var_status = tk.StringVar(value="就绪")
        self.var_names_stat = tk.StringVar(value="共 0 个")
        self.var_names_file = tk.StringVar(value="")
        self.var_preview_caption = tk.StringVar(value="")

        self.var_openscad = tk.StringVar(
            value=self.cfg.openscad_path or str(paths.default_openscad())
        )
        if self.cfg.scad_template:
            tpl_display = self.cfg.scad_template
        elif paths.is_frozen():
            # 打包后的内置模板在临时解包目录，显示真实路径只会让人困惑
            tpl_display = BUILTIN_TEMPLATE_LABEL
        else:
            tpl_display = str(paths.scad_template())
        self.var_template = tk.StringVar(value=tpl_display)

        # 「采用」按钮按字段名改对应的输入框
        self._spec_vars = {
            "base_width_mm": self.var_base_w,
            "base_height_mm": self.var_base_h,
            "max_width_mm": self.var_max_w,
            "margin_mm": self.var_margin,
            "letter_height_mm": self.var_letter_h,
            "font_size_mm": self.var_size,
            "letter_spacing": self.var_spacing,
            "weight_offset_mm": self.var_weight,
        }

    # ---------------- 界面 ----------------

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(12, 10, 12, 8))
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

        self._build_geometry(outer).grid(row=0, column=0, sticky="we")
        self._build_font(outer).grid(row=1, column=0, sticky="we", pady=(8, 0))
        self.hint_frame = ttk.Frame(outer)
        self.hint_frame.grid(row=2, column=0, sticky="we", pady=(6, 0))
        self._build_sources(outer).grid(row=3, column=0, sticky="we", pady=(8, 0))
        self._build_body(outer).grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        self._build_actions(outer).grid(row=5, column=0, sticky="we", pady=(8, 0))

    def _entry(self, parent: ttk.Frame, var: tk.StringVar, width: int = 9) -> ttk.Entry:
        ent = ttk.Entry(parent, textvariable=var, width=width)
        ent.bind("<FocusOut>", lambda _e: self._schedule_preview())
        ent.bind("<Return>", lambda _e: self._schedule_preview())
        return ent

    def _build_geometry(self, parent: ttk.Frame) -> ttk.Widget:
        box = ttk.LabelFrame(parent, text=" 印章几何 ", padding=(10, 6))
        pairs = [
            ("底座宽度 mm", self.var_base_w, "base_width_mm"),
            ("底座高度 mm", self.var_base_h, "base_height_mm"),
            ("最长不超过 mm", self.var_max_w, "max_width_mm"),
            ("左右留白 mm", self.var_margin, "margin_mm"),
            ("字体高度 mm", self.var_letter_h, "letter_height_mm"),
        ]
        col = 0
        for i, (label, var, field) in enumerate(pairs):
            ttk.Label(box, text=label).grid(
                row=0, column=col, sticky="e", padx=(0 if i == 0 else 16, 6), pady=2
            )
            ent = self._entry(box, var)
            ent.grid(row=0, column=col + 1, sticky="w", pady=2)
            self._spec_widgets[field] = ent
            col += 2

        opts = ttk.Frame(box)
        opts.grid(row=1, column=0, columnspan=col, sticky="we", pady=(6, 0))
        ttk.Checkbutton(
            opts,
            text="个别名字装不下时加宽它的底座（不缩字）",
            variable=self.var_widen,
            command=self._schedule_preview,
        ).pack(side="left")
        ttk.Label(
            opts,
            text="底座长度按名字自动算，短名字不会硬撑到上限",
            foreground=COLOR_MUTED,
        ).pack(side="left", padx=(20, 0))
        return box

    def _build_font(self, parent: ttk.Frame) -> ttk.Widget:
        box = ttk.LabelFrame(parent, text=" 字体 ", padding=(10, 6))
        # 最后一列吃掉多余宽度，预览条才能铺满
        box.columnconfigure(11, weight=1)

        ttk.Label(box, text="字体").grid(row=0, column=0, sticky="e", padx=(0, 6), pady=2)
        self.cmb_family = ttk.Combobox(
            box, textvariable=self.var_family, state="readonly", width=20
        )
        self.cmb_family.grid(row=0, column=1, sticky="w", pady=2)
        self.cmb_family.bind("<<ComboboxSelected>>", lambda _e: self._refresh_styles())

        ttk.Label(box, text="字重").grid(row=0, column=2, sticky="e", padx=(16, 6), pady=2)
        self.cmb_style = ttk.Combobox(
            box, textvariable=self.var_style, state="readonly", width=11
        )
        self.cmb_style.grid(row=0, column=3, sticky="w", pady=2)
        self.cmb_style.bind("<<ComboboxSelected>>", lambda _e: self._schedule_preview())

        ttk.Label(box, text="字号 mm").grid(row=0, column=4, sticky="e", padx=(16, 6), pady=2)
        ent_size = self._entry(box, self.var_size, 7)
        ent_size.grid(row=0, column=5, sticky="w", pady=2)
        self._spec_widgets["font_size_mm"] = ent_size

        ttk.Label(box, text="字间距").grid(row=0, column=6, sticky="e", padx=(16, 6), pady=2)
        ent_spacing = self._entry(box, self.var_spacing, 7)
        ent_spacing.grid(row=0, column=7, sticky="w", pady=2)
        self._spec_widgets["letter_spacing"] = ent_spacing

        ttk.Label(box, text="几何加粗 mm").grid(row=0, column=8, sticky="e", padx=(16, 6), pady=2)
        spin_weight = ttk.Spinbox(
            box,
            textvariable=self.var_weight,
            from_=0.0,
            to=0.3,
            increment=0.02,
            width=7,
            command=self._schedule_preview,
        )
        spin_weight.grid(row=0, column=9, sticky="w", pady=2)
        spin_weight.bind("<FocusOut>", lambda _e: self._schedule_preview())
        spin_weight.bind("<KeyRelease>", lambda _e: self._schedule_preview())
        self._spec_widgets["weight_offset_mm"] = spin_weight  # type: ignore[assignment]

        ttk.Label(box, text="大小写").grid(row=0, column=10, sticky="e", padx=(16, 6), pady=2)
        self.cmb_case = ttk.Combobox(
            box,
            textvariable=self.var_case,
            state="readonly",
            width=11,
            values=[CASE_LABELS[k] for k in ("keep", "upper", "capitalize", "lower")],
        )
        self.cmb_case.grid(row=0, column=11, sticky="w", pady=2)
        self.cmb_case.bind("<<ComboboxSelected>>", lambda _e: self._schedule_preview())

        # 固定高度的预览容器：图换尺寸时布局不跳
        self.preview_holder = tk.Frame(
            box,
            height=88,
            background=COLOR_PREVIEW_BG,
            highlightthickness=1,
            highlightbackground=COLOR_PREVIEW_BORDER,
        )
        self.preview_holder.grid(
            row=1, column=0, columnspan=12, sticky="we", pady=(8, 0)
        )
        self.preview_holder.pack_propagate(False)
        self.lbl_preview = tk.Label(
            self.preview_holder,
            bd=0,
            anchor="w",
            background=COLOR_PREVIEW_BG,
            foreground=COLOR_MUTED,
            text="选择字体后这里显示预览",
        )
        self.lbl_preview.pack(fill="both", expand=True, padx=6, pady=2)

        ttk.Label(
            box,
            textvariable=self.var_preview_caption,
            foreground=COLOR_MUTED,
        ).grid(row=2, column=0, columnspan=12, sticky="w", pady=(4, 0))
        return box

    def _build_sources(self, parent: ttk.Frame) -> ttk.Widget:
        wrap = ttk.Frame(parent)
        wrap.columnconfigure(0, weight=0, minsize=520)
        wrap.columnconfigure(1, weight=1)
        wrap.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(wrap, text=" 配置（自动探测） ", padding=(10, 6))
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(1, weight=1)

        rows = [
            ("OpenSCAD", self.var_openscad, self._pick_openscad),
            ("模板 scad", self.var_template, self._pick_template),
            ("输出目录", self.var_outroot, self._pick_outroot),
        ]
        for i, (label, var, command) in enumerate(rows):
            ttk.Label(left, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ent = ttk.Entry(left, textvariable=var)
            ent.grid(row=i, column=1, sticky="we", pady=3, padx=(6, 6))
            ttk.Button(left, text="选择", width=6, command=command).grid(row=i, column=2, pady=3)
            if var is self.var_outroot:
                # 手改路径后「实际输出」要跟着变
                ent.bind("<FocusOut>", lambda _e: self._refresh_output_label())
                ent.bind("<Return>", lambda _e: self._refresh_output_label())

        opt = ttk.Frame(left)
        opt.grid(row=3, column=0, columnspan=3, sticky="we", pady=(6, 0))
        ttk.Checkbutton(
            opt,
            text="完成后自动打开输出文件夹",
            variable=self.var_open_after,
        ).pack(side="left")
        ttk.Label(opt, text="同时生成").pack(side="left", padx=(18, 6))
        spin_workers = ttk.Spinbox(
            opt, textvariable=self.var_workers, from_=0, to=16, increment=1, width=5
        )
        spin_workers.pack(side="left")
        ttk.Label(opt, text="个（0=自动）", foreground=COLOR_MUTED).pack(side="left", padx=(6, 0))

        ttk.Label(
            left, textvariable=self.var_out_hint, foreground=COLOR_MUTED, anchor="w"
        ).grid(row=4, column=0, columnspan=3, sticky="we", pady=(6, 0))

        right = ttk.LabelFrame(wrap, text=" 名字清单 ", padding=(10, 6))
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        bar = ttk.Frame(right)
        bar.grid(row=0, column=0, sticky="we", pady=(0, 5))
        ttk.Button(bar, text="选择 txt 文件", width=13, command=self._pick_names).pack(side="left")
        # 选完之后这里显示文件名，用户一眼知道现在用的是哪个清单
        ttk.Label(bar, textvariable=self.var_names_file, foreground=COLOR_INFO).pack(
            side="left", padx=(10, 0)
        )
        ttk.Label(bar, textvariable=self.var_names_stat, foreground=COLOR_MUTED).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            bar, text="也可直接粘贴，一行一个名字", foreground=COLOR_MUTED
        ).pack(side="right")

        edit = ttk.Frame(right)
        edit.grid(row=1, column=0, sticky="nsew")
        edit.columnconfigure(1, weight=1)
        edit.rowconfigure(0, weight=1)

        # 左侧行号列：禁用、灰底、不参与 Tab 焦点。
        # height 必须给 1 —— 默认 24 行会把整个区块撑到 400px 高。
        self.txt_lineno = tk.Text(
            edit,
            width=4,
            height=1,
            state="disabled",
            background="#f0f0ee",
            foreground=COLOR_MUTED,
            relief="flat",
            borderwidth=0,
            takefocus=0,
            wrap="none",
        )
        self.txt_lineno.grid(row=0, column=0, sticky="ns")

        self.txt_names = tk.Text(edit, height=5, wrap="none", undo=True, relief="solid", borderwidth=1)
        self.txt_names.grid(row=0, column=1, sticky="nsew")

        self.names_scroll = ttk.Scrollbar(edit, orient="vertical")
        self.names_scroll.grid(row=0, column=2, sticky="ns")
        self.txt_names.configure(yscrollcommand=self._on_names_scroll)
        self.names_scroll.configure(command=self.txt_names.yview)

        self.txt_names.bind("<KeyRelease>", lambda _e: self._on_names_changed())
        self.txt_names.bind("<<Paste>>", lambda _e: self.root.after(10, self._on_names_changed))
        self.txt_names.bind("<<Cut>>", lambda _e: self.root.after(10, self._on_names_changed))
        self.txt_names.bind("<ButtonRelease-1>", lambda _e: self._redraw_line_numbers())
        self.txt_names.bind("<MouseWheel>", lambda _e: self.root.after(1, self._redraw_line_numbers))
        self._bind_drop(self.txt_names)
        return wrap

    def _build_body(self, parent: ttk.Frame) -> ttk.Widget:
        paned = ttk.Panedwindow(parent, orient=tk.VERTICAL)

        result_box = ttk.LabelFrame(paned, text=" 结果预览 ", padding=(8, 6))
        cols = (
            "no",
            "name",
            "chars",
            "size",
            "spacing",
            "base_w",
            "base_len",
            "status",
            "spacer",
        )
        headings = {
            "no": ("序号", 44, "center", False),
            "name": ("名字", 240, "w", False),
            "chars": ("字符", 46, "center", False),
            "size": ("字号 mm", 68, "center", False),
            "spacing": ("间距", 56, "center", False),
            "base_w": ("底座宽 mm", 84, "center", False),
            "base_len": ("底座长 mm", 84, "center", False),
            "status": ("状态", 74, "center", False),
            # 占位列：把多余宽度收在表格最右侧，名字列就不会被拉成一片空白
            "spacer": ("", 20, "w", True),
        }
        self.tree = ttk.Treeview(result_box, columns=cols, show="headings", height=12)
        for key in cols:
            text, width, anchor, stretch = headings[key]
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor, stretch=stretch)
        self.tree.tag_configure("warn", foreground=COLOR_WARN)
        self.tree.tag_configure("err", foreground=COLOR_ERR)
        self.tree.tag_configure("ok", foreground=COLOR_OK)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", lambda _e: self._hide_tip())
        self.tree.bind("<ButtonPress>", lambda _e: self._hide_tip())
        scroll = ttk.Scrollbar(result_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill=tk.BOTH, expand=True)
        scroll.pack(side="right", fill="y")
        paned.add(result_box, weight=5)

        log_box = ttk.LabelFrame(paned, text=" 运行日志 ", padding=(8, 6))
        self.txt_log = tk.Text(log_box, height=3, wrap="word", state="disabled")
        log_scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=log_scroll.set)
        self.txt_log.pack(side="left", fill=tk.BOTH, expand=True)
        log_scroll.pack(side="right", fill="y")
        paned.add(log_box, weight=1)
        return paned

    def _build_actions(self, parent: ttk.Frame) -> ttk.Widget:
        bar = ttk.Frame(parent)
        self.btn_start = ttk.Button(bar, text="开始生成", command=self.start, width=12)
        self.btn_start.pack(side="left")
        self.btn_cancel = ttk.Button(
            bar, text="取消", command=self.cancel_run, state="disabled", width=8
        )
        self.btn_cancel.pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(bar, mode="determinate", length=180)
        self.progress.pack(side="right")
        self.lbl_status = ttk.Label(
            bar, textvariable=self.var_status, foreground=COLOR_MUTED, anchor="e"
        )
        self.lbl_status.pack(side="right", padx=(0, 10))
        return bar

    def _bind_drop(self, widget: tk.Widget) -> None:
        try:
            from tkinterdnd2 import DND_FILES

            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    # ---------------- 字体 ----------------

    def _current_face(self) -> FontFace | None:
        return self.library.find(self.var_family.get(), self.var_style.get() or "Regular")

    def _refresh_fonts(self) -> None:
        families = self.library.families()
        names = list(families)
        self.cmb_family["values"] = names
        if not names:
            self.log("内置字体库为空，请把 .ttf 放入 fonts 目录")
            return
        current = self.var_family.get() or self.cfg.font_family
        self.var_family.set(current if current in families else names[0])
        self._refresh_styles()

    def _refresh_styles(self) -> None:
        families = self.library.families()
        styles = families.get(self.var_family.get(), [])
        self.cmb_style["values"] = styles
        current = self.var_style.get() or self.cfg.font_style
        self.var_style.set(current if current in styles else (styles[0] if styles else ""))
        self._schedule_preview()

    def _refresh_font_preview(self) -> None:
        """用 Pillow 直接渲染内置 ttf，字体/字号/加粗/大小写一变就重画。"""
        face = self._current_face()
        if face is None:
            self.lbl_preview.configure(image="", text="（没有可用字体）")
            self._preview_photo = None
            return
        try:
            size_mm = float(self.var_size.get())
            weight = float(self.var_weight.get())
        except ValueError:
            size_mm, weight = 6.0, 0.0
        names = self._read_names()
        try:
            spacing = float(self.var_spacing.get())
        except ValueError:
            spacing = 1.0

        # 有名字就预览这个名字（逐字等距，和打印完全一致）；没有才显示样例
        if names:
            text = names[0]
            letter_x = metrics.letter_positions(
                self.library.metrics(face), text, size_mm, spacing, weight
            )
            caption = f"预览：{text}"
        else:
            text = fontpreview.sample_text(self._case_mode(), "")
            letter_x = None
            caption = "预览：字体样例（输入名字后显示该名字）"

        # 把当前参数写出来：加粗 0.02mm 的视觉差异很小，有数字回显才确认得了
        self.var_preview_caption.set(
            f"{caption} · 字号 {size_mm:g}mm · 加粗 {weight:g}mm · "
            f"{CASE_LABELS.get(self._case_mode(), '保持原样')} · "
            f"字符等距，与实际打印一致"
        )
        width = max(self.preview_holder.winfo_width() - 16, 480)
        rendered = fontpreview.render_preview(
            face.path,
            text,
            size_mm,
            weight,
            letter_x=letter_x,
            max_px=width,
            bg=COLOR_PREVIEW_BG,
        )
        if rendered is None:
            self.lbl_preview.configure(
                image="", text=f"{face.label}：预览不可用（缺少 Pillow 或字体损坏）"
            )
            self._preview_photo = None
            return
        image, _scale = rendered
        try:
            from PIL import ImageTk

            self._preview_photo = ImageTk.PhotoImage(image)
        except Exception:
            self._preview_photo = None
            self.lbl_preview.configure(image="", text=f"{face.label}（预览不可用）")
            return
        self.lbl_preview.configure(image=self._preview_photo, text="")

    # ---------------- 配置 ----------------

    def _load_cfg_into_ui(self) -> None:
        self.var_outroot.set(self.cfg.output_root_dir)
        # 故意不自动载入上次的清单：那些名字多半已经生成过了，
        # 一打开就填满会让人以为要重新跑一遍。cfg.names_txt 只留着
        # 给「选择 txt 文件」对话框当初始目录，以及命名输出文件夹。
        self._refresh_output_label()
        self.preview()

    def _case_mode(self) -> str:
        return self._case_label_to_key.get(self.var_case.get(), "keep")

    def _collect_cfg(self) -> AppConfig:
        cfg = self.cfg
        spec = cfg.spec

        def num(var: tk.StringVar, label: str, minimum: float = 0.0) -> float:
            raw = (var.get() or "").strip()
            try:
                value = float(raw)
            except ValueError:
                raise ValueError(f"{label} 不是有效数字：{raw!r}") from None
            if value < minimum:
                raise ValueError(f"{label} 不能小于 {minimum:g}")
            return value

        spec.base_width_mm = num(self.var_base_w, "底座宽度", 0.5)
        spec.base_height_mm = num(self.var_base_h, "底座高度", 0.5)
        spec.max_width_mm = num(self.var_max_w, "最长上限", 1.0)
        spec.margin_mm = num(self.var_margin, "左右留白")
        spec.letter_height_mm = num(self.var_letter_h, "字体高度", 0.2)
        spec.font_size_mm = num(self.var_size, "字号", 0.5)
        spec.letter_spacing = num(self.var_spacing, "字间距", 0.1)
        spec.weight_offset_mm = num(self.var_weight, "几何加粗")
        spec.case_mode = self._case_mode()
        spec.widen_base_per_name = bool(self.var_widen.get())

        raw_workers = (self.var_workers.get() or "").strip()
        if raw_workers:
            try:
                cfg.workers = max(0, int(float(raw_workers)))
            except ValueError:
                raise ValueError(f"同时生成数不是有效整数：{raw_workers!r}") from None
        else:
            cfg.workers = 0

        cfg.font_family = self.var_family.get()
        cfg.font_style = self.var_style.get() or "Regular"
        # 本次没选文件时保留上次的路径，下次「选择」对话框直接打开那个目录
        cfg.names_txt = self._names_source_txt or self.cfg.names_txt
        cfg.output_root_dir = self.var_outroot.get().strip()
        cfg.open_output_after_run = bool(self.var_open_after.get())
        # 与默认值相同就存空串：这样换机器、移动 exe 之后会自动重新探测，
        # 也不会把 PyInstaller 的临时解包路径写进配置。
        raw_exe = self.var_openscad.get().strip()
        cfg.openscad_path = (
            "" if not raw_exe or Path(raw_exe) == paths.default_openscad() else raw_exe
        )
        raw_tpl = self.var_template.get().strip()
        if not raw_tpl or raw_tpl == BUILTIN_TEMPLATE_LABEL:
            cfg.scad_template = ""
        elif Path(raw_tpl) == paths.scad_template():
            cfg.scad_template = ""
        else:
            cfg.scad_template = raw_tpl
        return cfg

    def _persist(self) -> None:
        try:
            save_config(self._collect_cfg())
        except Exception:
            pass

    def _schedule_persist(self) -> None:
        """参数改动后延迟存盘。

        不等到关窗才保存：用户改完参数直接关任务管理器、或程序被强杀时，
        下次打开还能沿用上次的字体、字号、大小写等设置。
        """
        if self._persist_job:
            self.root.after_cancel(self._persist_job)
        self._persist_job = self.root.after(1500, self._persist_now)

    def _persist_now(self) -> None:
        self._persist_job = None
        self._persist()

    def _refresh_output_label(self) -> None:
        root = self.var_outroot.get().strip()
        if not root:
            self.var_out_hint.set("实际输出：请先选择输出目录")
            return
        # 显示下一次生成会落到的具体批次目录（时间戳按当前分钟算）
        base = batch_mod.derive_output_dir(self._names_source_txt or "names", root)
        self.var_out_hint.set(f"实际输出：{batch_mod.batch_dir(base)}")

    # ---------------- 日志与状态 ----------------

    def log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def _append_log(self, message: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", message + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        """状态栏字数有限，超出就截断 —— 完整信息在日志里。"""
        text = (text or "").replace("\n", " ")
        if len(text) > STATUS_MAX_CHARS:
            text = text[: STATUS_MAX_CHARS - 1] + "…"
        self.var_status.set(text)

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "progress":
                    done, total = payload
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = done
                    self._set_status(f"生成中 {done}/{total}")
                elif kind == "status":
                    self._set_status(payload)
                elif kind == "done":
                    self._on_worker_done(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ---------------- 名字清单 ----------------

    def _on_names_scroll(self, first: str, last: str) -> None:
        self.names_scroll.set(first, last)
        self._redraw_line_numbers()

    def _redraw_line_numbers(self) -> None:
        """只画可见区间的行号，上千行也不会卡。"""
        txt = self.txt_names
        try:
            last = int(txt.index("end-1c").split(".")[0])
            top = int(txt.index("@0,0").split(".")[0])
            height = max(txt.winfo_height() - 2, 1)
            bottom = int(txt.index(f"@0,{height}").split(".")[0])
        except Exception:
            return
        # 末尾空行不编号：粘贴内容常以换行结尾，那行并没有名字
        total = last
        if last > 1 and not txt.get(f"{last}.0", f"{last}.end"):
            total = last - 1
        start = max(1, top - 1)
        end = min(total, max(bottom, top) + 1)
        if end < start:
            end = start
        numbers = "\n".join(str(n) for n in range(start, end + 1))
        # 前后补空行，让行号框与主框总行数一致，yview 才能严格对齐
        body = "\n" * (start - 1) + numbers + "\n" * max(0, total - end)
        self.txt_lineno.configure(state="normal")
        self.txt_lineno.delete("1.0", "end")
        self.txt_lineno.insert("1.0", body)
        self.txt_lineno.configure(state="disabled")
        self.txt_lineno.yview_moveto(0 if total <= 1 else (start - 1) / total)

    def _on_names_changed(self) -> None:
        self._redraw_line_numbers()
        self._schedule_preview()

    def _read_names(self) -> list[str]:
        raw = self.txt_names.get("1.0", "end").splitlines()
        names = validate.normalize_names(raw)
        return validate.apply_case(names, self._case_mode())

    def _refresh_names_stat(self) -> None:
        names = self._read_names()
        unique, duplicates = validate.dedupe(names)
        text = f"共 {len(names)} 个"
        if duplicates:
            text += f"（重名 {len(duplicates)}，去重后 {len(unique)}）"
        self.var_names_stat.set(text)
        if self._names_source_txt:
            name = Path(self._names_source_txt).name
            self.var_names_file.set(console.truncate(name, 28))
        else:
            self.var_names_file.set("（粘贴输入）" if names else "")

    def _load_names_file(self, path: Path) -> None:
        try:
            content = _read_text_file(path)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"读取失败：{exc}")
            return
        self._names_source_txt = str(path)
        self.txt_names.delete("1.0", "end")
        self.txt_names.insert("1.0", content.strip())
        self._redraw_line_numbers()
        self._refresh_output_label()
        self.preview()

    # ---------------- 交互 ----------------

    def _pick_names(self) -> None:
        # 优先打开当前清单所在目录；没选过就退回上次用过的那个
        start = self._names_source_txt or self.cfg.names_txt
        path = filedialog.askopenfilename(
            title="选择名字清单",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialdir=str(Path(start).parent) if start else str(paths.app_root()),
        )
        if path:
            self._load_names_file(Path(path))

    def _pick_outroot(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.var_outroot.set(path)
            self._refresh_output_label()
            self._schedule_preview()

    def _pick_openscad(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 openscad.exe",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")],
            initialdir=str(Path(self.var_openscad.get()).parent),
        )
        if path:
            self.var_openscad.set(path)
            self._schedule_persist()

    def _pick_template(self) -> None:
        current = self.var_template.get().strip()
        if not current or current == BUILTIN_TEMPLATE_LABEL:
            start = str(paths.app_root())
        else:
            start = str(Path(current).parent)
        path = filedialog.askopenfilename(
            title="选择 scad 模板",
            filetypes=[("OpenSCAD 模型", "*.scad"), ("所有文件", "*.*")],
            initialdir=start,
        )
        if path:
            self.var_template.set(path)
            self._schedule_persist()

    def _on_drop(self, event) -> None:  # pragma: no cover - 依赖 GUI
        raw = str(event.data).strip()
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        for part in raw.split():
            candidate = part.strip("{}")
            if candidate.lower().endswith(".txt") and Path(candidate).is_file():
                self._load_names_file(Path(candidate))
                return

    # ---------------- 提示带 ----------------

    _HINT_STYLE = {
        validate.ERROR: ("✕", COLOR_ERR),
        validate.WARN: ("!", COLOR_WARN),
        validate.INFO: ("i", COLOR_INFO),
    }

    def _render_hints(self, issues: list[validate.SpecIssue]) -> None:
        for child in self.hint_frame.winfo_children():
            child.destroy()
        for issue in issues[:3]:
            row = ttk.Frame(self.hint_frame)
            row.pack(fill="x", pady=1)
            mark, color = self._HINT_STYLE.get(issue.level, ("!", COLOR_WARN))
            tk.Label(row, text=mark, fg=color, font=("", 10, "bold")).pack(side="left")
            tk.Label(
                row,
                text=issue.message,
                fg=color,
                anchor="w",
                justify="left",
                wraplength=780,
            ).pack(side="left", padx=(6, 0))
            if issue.fixable:
                # 按钮文字由问题自己决定：全局参数类叫「采用」，
                # 个别名字加宽类叫「统一为 7.20mm」—— 点之前就知道它影响全部
                ttk.Button(
                    row,
                    text=issue.action_label,
                    command=lambda i=issue: self._apply_fix(i.fix, i.action_label),
                ).pack(side="left", padx=(10, 0))

    def _apply_fix(self, fix: dict, action_label: str = "采用") -> None:
        changed: list[tuple[str, str]] = []
        for key, value in fix.items():
            var = self._spec_vars.get(key)
            if var is None:
                continue
            text = f"{value:g}" if isinstance(value, float) else str(value)
            var.set(text)
            changed.append((key, text))
        self._schedule_preview()
        if not changed:
            return
        # 把改动的输入框顶到眼前：聚焦 + 选中文字。
        # 光靠"值变了"用户注意不到，光标落在那个框上就一眼看见了。
        key, text = changed[0]
        widget = self._spec_widgets.get(key)
        if widget is not None:
            try:
                widget.focus_set()
                widget.selection_range(0, "end")
            except tk.TclError:
                pass
        name, unit = _FIELD_LABELS.get(key, (key, ""))
        self._set_status(f"已把{name}改为 {text}{unit}（全部名字适用）")

    # ---------------- 悬停提示 ----------------

    def _on_tree_motion(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid == self._hover_iid:
            return
        self._hover_iid = iid
        self._hide_tip()
        detail = self._row_detail.get(iid, "")
        if detail:
            self._show_tip(event.x_root + 16, event.y_root + 12, detail)

    def _show_tip(self, x: int, y: int, text: str) -> None:
        tip = tk.Toplevel(self.root)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tip,
            text=text,
            justify="left",
            background="#fdf6e3",
            relief="solid",
            borderwidth=1,
            wraplength=420,
            padx=8,
            pady=4,
        ).pack()
        self._tip = tip

    def _hide_tip(self) -> None:
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    # ---------------- 预览 ----------------

    def _schedule_preview(self) -> None:
        if self._preview_job:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(250, self.preview)
        self._schedule_persist()

    def preview(self) -> None:
        self._preview_job = None
        self.tree.delete(*self.tree.get_children())
        self._row_detail.clear()
        self._hover_iid = ""
        self._hide_tip()
        self._refresh_font_preview()
        self._refresh_names_stat()
        self._refresh_output_label()

        try:
            cfg = self._collect_cfg()
        except ValueError as exc:
            self._render_hints([])
            self._set_status(str(exc))
            return

        face = self._current_face()
        if face is None:
            self._render_hints([])
            self._set_status("内置字体库为空")
            return
        fm = self.library.metrics(face)
        spec = cfg.spec

        names = self._read_names()
        unique, duplicates = validate.dedupe(names)
        # 参数约束要拿清单里的真实名字来算字高，先有名字再校验
        self._render_hints(validate.check_spec(fm, spec, unique))
        if not names:
            self._set_status("名字清单为空 —— 选择 txt 或直接粘贴")
            return
        name_issues = validate.validate_batch(unique, fm, spec)

        ok_count = 0
        lengths: list[float] = []
        widths: list[float] = []
        for index, name in enumerate(unique, start=1):
            blocking = validate.blocking_issues(name_issues.get(name, []))
            if blocking:
                values = (index, name, len(name), "", "", "", "", "跳过", "")
                tag = "err"
                detail = validate.format_issues(blocking)
            else:
                fit = metrics.fit(fm, name, spec)
                if fit.is_blocking:
                    tag = "err"
                elif fit.needs_attention:
                    tag = "warn"
                else:
                    tag = "ok"
                values = (
                    index,
                    name,
                    len(name),
                    f"{fit.size_mm:.2f}",
                    f"{fit.spacing:.2f}",
                    f"{fit.base_width_mm:.2f}",
                    f"{fit.base_len_mm:.2f}",
                    fit.label,
                    "",
                )
                # 正常的不弹提示，否则鼠标一扫满屏都是气泡
                detail = fit.detail if (fit.needs_attention or fit.is_blocking) else ""
                if fit.ok:
                    ok_count += 1
                    lengths.append(fit.base_len_mm)
                    widths.append(fit.base_width_mm)
            iid = self.tree.insert("", "end", values=values, tags=(tag,))
            self._row_detail[iid] = detail

        for name in duplicates:
            iid = self.tree.insert(
                "",
                "end",
                values=("—", name, len(name), "", "", "", "", "重名", ""),
                tags=("err",),
            )
            self._row_detail[iid] = "与本批次前面重名，只生成一次"

        # 字体名上面的下拉框里已经显示了，状态栏留给尺寸
        span = f"，底座长 {min(lengths):.1f}~{max(lengths):.1f}mm" if lengths else ""
        if widths and max(widths) - min(widths) > 0.05:
            span += f"，宽 {min(widths):.1f}~{max(widths):.1f}mm"
        self._set_status(f"可生成 {ok_count}/{len(unique)}{span}")

    # ---------------- 生成 ----------------

    def _resolve_output_dir(self, cfg: AppConfig) -> Path:
        return batch_mod.derive_output_dir(
            self._names_source_txt or "names", cfg.output_root_dir
        )

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            cfg = self._collect_cfg()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        names = self._read_names()
        if not names:
            messagebox.showinfo(APP_TITLE, "名字清单为空，请选择 txt 或直接粘贴")
            return
        face = self._current_face()
        if face is not None:
            spec_issues = validate.check_spec(self.library.metrics(face), cfg.spec, names)
            errors = [i for i in spec_issues if i.is_error]
            if errors:
                messagebox.showerror(
                    APP_TITLE,
                    "参数有问题，无法生成：\n\n" + "\n".join(f"· {i.message}" for i in errors),
                )
                return
        if not cfg.output_root_dir:
            messagebox.showinfo(APP_TITLE, "请先选择输出目录")
            return
        if not Path(cfg.output_root_dir).is_dir():
            messagebox.showerror(APP_TITLE, f"输出目录不存在：{cfg.output_root_dir}")
            return
        if not cfg.resolved_openscad().is_file():
            messagebox.showerror(
                APP_TITLE,
                "找不到 OpenSCAD：\n"
                f"{cfg.resolved_openscad()}\n\n"
                "请在「OpenSCAD」一栏指定 openscad.exe，\n"
                "或把 OpenSCAD 文件夹放在本程序旁边。",
            )
            return

        self._persist()
        self.cancel.clear()
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress["value"] = 0
        # 每批一个时间戳子目录：一天做几次都不会互相覆盖
        output_dir = batch_mod.batch_dir(self._resolve_output_dir(cfg))
        self.log("")
        self.log(f"开始生成，共 {len(names)} 个名字")
        self.log(f"输出到：{output_dir}")

        self.worker = threading.Thread(
            target=self._run_batch, args=(cfg, names, output_dir), daemon=True
        )
        self.worker.start()

    def _run_batch(self, cfg: AppConfig, names: list[str], output_dir: Path) -> None:
        try:
            report = batch_mod.run_batch(
                cfg,
                names,
                output_dir,
                library=self.library,
                progress=lambda i, n, name, st: (
                    self.log_queue.put(("progress", (i, n))),
                    self.log(f"  [{i}/{n}] {name} {st}"),
                ),
                log=self.log,
                cancel=self.cancel,
            )
            self.log_queue.put(("done", report))
        except Exception as exc:
            self.log(f"批次异常：{exc}")
            self.log(traceback.format_exc(limit=3))
            self.log_queue.put(("done", None))

    def _on_worker_done(self, report: batch_mod.BatchReport | None) -> None:
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        if report is None:
            self._set_status("已中止")
            return
        for line in report.lines():
            self.log(line)
        self.log("")
        self.log(report.summary())
        bases = [r.base_len for r in report.results if r.base_len]
        span = f"，底座 {min(bases):.1f}~{max(bases):.1f}mm" if bases else ""
        self._set_status(
            f"完成：成功 {report.generated}，跳过 {report.skipped}，"
            f"失败 {report.failed}{span}"
        )
        if report.generated and self.var_open_after.get():
            self._open_folder(report.output_dir)

    def _open_folder(self, path: Path) -> None:
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                webbrowser.open(Path(path).as_uri())
        except OSError as exc:
            self.log(f"打开输出文件夹失败：{exc}")

    def cancel_run(self) -> None:
        self.cancel.set()
        self.log("已请求取消，等待当前模型完成…")

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel(APP_TITLE, "任务仍在运行，确定退出？"):
                return
            self.cancel.set()
        self._persist()
        self.root.destroy()


def run() -> int:
    _enable_dpi_awareness()
    try:
        from tkinterdnd2 import TkinterDnD

        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()
    StampApp(root)
    root.mainloop()
    return 0
