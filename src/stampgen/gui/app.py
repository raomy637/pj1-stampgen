"""Tkinter 图形界面。

设计目标：一次配置、反复使用。参数区在左，预览与日志在右，
所有设置写入 ``stampgen_config.json``，下次启动自动恢复。
"""

from __future__ import annotations

import queue
import threading
import traceback
import webbrowser
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import batch as batch_mod
from .. import metrics, openscad, paths, validate
from ..config import AppConfig, load_config, save_config
from ..fonts import FontLibrary

APP_TITLE = "名字印章生成器"
COLOR_OK = "#0f6e56"
COLOR_WARN = "#854f0b"
COLOR_ERR = "#a32d2d"
COLOR_MUTED = "#5f5e5a"


def _enable_dpi_awareness() -> None:
    """Windows 高分屏下避免界面模糊。"""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class StampApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.library = FontLibrary()
        self.cfg: AppConfig = load_config()
        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None

        root.title(APP_TITLE)
        root.geometry("1120x800")
        root.minsize(980, 700)
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
        self.var_family = tk.StringVar()
        self.var_style = tk.StringVar()
        self.var_width = tk.StringVar(value=f"{spec.target_width_mm:g}")
        self.var_margin = tk.StringVar(value=f"{spec.margin_mm:g}")
        self.var_min_size = tk.StringVar(value=f"{spec.min_size_mm:g}")
        self.var_max_size = tk.StringVar(value=f"{spec.max_size_mm:g}")
        self.var_weight = tk.StringVar(value=f"{spec.weight_offset_mm:g}")
        self.var_base_w = tk.StringVar(value=f"{spec.base_width_mm:g}")
        self.var_base_h = tk.StringVar(value=f"{spec.base_height_mm:g}")
        self.var_letter_h = tk.StringVar(value=f"{spec.letter_height_mm:g}")
        self.var_names = tk.StringVar()
        self.var_outroot = tk.StringVar()
        self.var_status = tk.StringVar(value="就绪")
        # 这两项留空表示"用默认值"，界面显示的是当前实际生效的路径
        self.var_openscad = tk.StringVar(
            value=self.cfg.openscad_path or str(paths.default_openscad())
        )
        self.var_template = tk.StringVar(
            value=self.cfg.scad_template or str(paths.scad_template())
        )

    # ---------------- 界面 ----------------

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        self._build_params(outer).grid(row=0, column=0, sticky="we")
        self._build_files(outer).grid(row=1, column=0, sticky="we", pady=(10, 6))
        self._build_actions(outer).grid(row=2, column=0, sticky="we", pady=(0, 8))
        self._build_body(outer).grid(row=3, column=0, sticky="nsew")

    def _build_params(self, parent: ttk.Frame) -> ttk.Widget:
        box = ttk.LabelFrame(parent, text=" 印章参数 ", padding=10)
        for col in (1, 3, 5):
            box.columnconfigure(col, weight=1)

        ttk.Label(box, text="字体").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        self.cmb_family = ttk.Combobox(box, textvariable=self.var_family, state="readonly", width=22)
        self.cmb_family.grid(row=0, column=1, sticky="we", pady=4)
        self.cmb_family.bind("<<ComboboxSelected>>", lambda _e: self._refresh_styles())

        ttk.Label(box, text="字重").grid(row=0, column=2, sticky="e", padx=(14, 6), pady=4)
        self.cmb_style = ttk.Combobox(box, textvariable=self.var_style, state="readonly", width=14)
        self.cmb_style.grid(row=0, column=3, sticky="we", pady=4)
        self.cmb_style.bind("<<ComboboxSelected>>", lambda _e: self._schedule_preview())

        ttk.Label(box, text="几何加粗 mm").grid(row=0, column=4, sticky="e", padx=(14, 6), pady=4)
        spin_weight = ttk.Spinbox(
            box,
            textvariable=self.var_weight,
            from_=0.0,
            to=0.3,
            increment=0.02,
            width=8,
            command=self._schedule_preview,
        )
        spin_weight.grid(row=0, column=5, sticky="w", pady=4)
        spin_weight.bind("<FocusOut>", lambda _e: self._schedule_preview())

        ttk.Label(box, text="目标宽度 mm").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=4)
        ent_width = ttk.Entry(box, textvariable=self.var_width)
        ent_width.grid(row=1, column=1, sticky="we", pady=4)
        ent_width.bind("<FocusOut>", lambda _e: self._schedule_preview())

        ttk.Label(box, text="左右留白 mm").grid(row=1, column=2, sticky="e", padx=(14, 6), pady=4)
        ent_margin = ttk.Entry(box, textvariable=self.var_margin)
        ent_margin.grid(row=1, column=3, sticky="we", pady=4)
        ent_margin.bind("<FocusOut>", lambda _e: self._schedule_preview())

        ttk.Label(box, text="字号范围 mm").grid(row=1, column=4, sticky="e", padx=(14, 6), pady=4)
        range_box = ttk.Frame(box)
        range_box.grid(row=1, column=5, sticky="we", pady=4)
        e_min = ttk.Entry(range_box, textvariable=self.var_min_size, width=6)
        e_min.pack(side="left")
        ttk.Label(range_box, text=" ~ ").pack(side="left")
        e_max = ttk.Entry(range_box, textvariable=self.var_max_size, width=6)
        e_max.pack(side="left")
        for w in (e_min, e_max):
            w.bind("<FocusOut>", lambda _e: self._schedule_preview())

        ttk.Label(box, text="底座 宽/高/字高").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=4)
        base_box = ttk.Frame(box)
        base_box.grid(row=2, column=1, sticky="we", pady=4)
        for var in (self.var_base_w, self.var_base_h, self.var_letter_h):
            ent = ttk.Entry(base_box, textvariable=var, width=7)
            ent.pack(side="left", padx=(0, 4))
            ent.bind("<FocusOut>", lambda _e: self._schedule_preview())

        self.lbl_hint = ttk.Label(
            box,
            text="字号上限会同时受「底座宽度」约束：字高不得超过底座宽，否则字母会悬空。",
            foreground=COLOR_MUTED,
        )
        self.lbl_hint.grid(row=2, column=2, columnspan=4, sticky="w", padx=(14, 0), pady=4)
        return box

    def _build_files(self, parent: ttk.Frame) -> ttk.Widget:
        box = ttk.Frame(parent)
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="名字清单", width=10).grid(row=0, column=0, sticky="w", pady=3)
        ent_names = ttk.Entry(box, textvariable=self.var_names)
        ent_names.grid(row=0, column=1, sticky="we", pady=3)
        ttk.Button(box, text="选择文件", width=10, command=self._pick_names).grid(
            row=0, column=2, padx=(6, 0), pady=3
        )
        self._bind_drop(ent_names)

        ttk.Label(box, text="输出目录", width=10).grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(box, textvariable=self.var_outroot).grid(row=1, column=1, sticky="we", pady=3)
        ttk.Button(box, text="选择目录", width=10, command=self._pick_outroot).grid(
            row=1, column=2, padx=(6, 0), pady=3
        )

        # 以下两项一般不用改：留默认值即可，换机器/移动 exe 后会自动重新探测
        ttk.Label(box, text="OpenSCAD", width=10).grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(box, textvariable=self.var_openscad).grid(row=2, column=1, sticky="we", pady=3)
        ttk.Button(box, text="选择文件", width=10, command=self._pick_openscad).grid(
            row=2, column=2, padx=(6, 0), pady=3
        )

        ttk.Label(box, text="模板 scad", width=10).grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(box, textvariable=self.var_template).grid(row=3, column=1, sticky="we", pady=3)
        ttk.Button(box, text="选择文件", width=10, command=self._pick_template).grid(
            row=3, column=2, padx=(6, 0), pady=3
        )
        return box

    def _bind_drop(self, widget: tk.Widget) -> None:
        try:
            from tkinterdnd2 import DND_FILES

            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    def _build_actions(self, parent: ttk.Frame) -> ttk.Widget:
        bar = ttk.Frame(parent)
        ttk.Button(bar, text="预览拟合", command=self.preview).pack(side="left")
        self.btn_start = ttk.Button(bar, text="开始生成", command=self.start)
        self.btn_start.pack(side="left", padx=(8, 0))
        self.btn_cancel = ttk.Button(bar, text="取消", command=self.cancel_run, state="disabled")
        self.btn_cancel.pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="自检", command=self.check_env).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="打开输出目录", command=self.open_output).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="清空日志", command=self.clear_log).pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(bar, mode="determinate", length=220)
        self.progress.pack(side="right")
        ttk.Label(bar, textvariable=self.var_status, foreground=COLOR_MUTED).pack(
            side="right", padx=(0, 10)
        )
        return bar

    def _build_body(self, parent: ttk.Frame) -> ttk.Widget:
        paned = ttk.Panedwindow(parent, orient=tk.VERTICAL)

        preview_box = ttk.LabelFrame(paned, text=" 拟合预览 ", padding=(8, 6))
        cols = ("name", "chars", "size", "spacing", "width", "fill", "status")
        headings = {
            "name": ("名字", 160),
            "chars": ("字符", 50),
            "size": ("字号", 70),
            "spacing": ("间距", 70),
            "width": ("估算宽", 80),
            "fill": ("填充率", 70),
            "status": ("状态", 360),
        }
        self.tree = ttk.Treeview(preview_box, columns=cols, show="headings", height=7)
        for key in cols:
            text, width = headings[key]
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w" if key in {"name", "status"} else "center")
        self.tree.tag_configure("warn", foreground=COLOR_WARN)
        self.tree.tag_configure("err", foreground=COLOR_ERR)
        self.tree.tag_configure("ok", foreground=COLOR_OK)
        scroll = ttk.Scrollbar(preview_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill=tk.BOTH, expand=True)
        scroll.pack(side="right", fill="y")
        paned.add(preview_box, weight=3)

        log_box = ttk.LabelFrame(paned, text=" 运行日志 ", padding=(8, 6))
        self.txt_log = tk.Text(log_box, height=12, wrap="word", state="disabled")
        log_scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=log_scroll.set)
        self.txt_log.pack(side="left", fill=tk.BOTH, expand=True)
        log_scroll.pack(side="right", fill="y")
        paned.add(log_box, weight=2)
        return paned

    # ---------------- 字体 ----------------

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

    # ---------------- 配置 ----------------

    def _load_cfg_into_ui(self) -> None:
        self.var_names.set(self.cfg.names_txt)
        self.var_outroot.set(self.cfg.output_root_dir)

    def _collect_cfg(self) -> AppConfig:
        cfg = self.cfg
        spec = cfg.spec

        def num(var: tk.StringVar, label: str, minimum: float = 0.0) -> float:
            raw = (var.get() or "").strip()
            try:
                value = float(raw)
            except ValueError:
                raise ValueError(f"{label} 不是有效数字：{raw!r}")
            if value < minimum:
                raise ValueError(f"{label} 不能小于 {minimum}")
            return value

        spec.target_width_mm = num(self.var_width, "目标宽度", 1.0)
        spec.margin_mm = num(self.var_margin, "留白")
        spec.min_size_mm = num(self.var_min_size, "最小字号", 0.5)
        spec.max_size_mm = num(self.var_max_size, "最大字号", 0.5)
        spec.weight_offset_mm = num(self.var_weight, "几何加粗")
        spec.base_width_mm = num(self.var_base_w, "底座宽度", 0.5)
        spec.base_height_mm = num(self.var_base_h, "底座高度", 0.5)
        spec.letter_height_mm = num(self.var_letter_h, "文字高度", 0.2)
        if spec.min_size_mm > spec.max_size_mm:
            raise ValueError("最小字号不能大于最大字号")
        if 2 * spec.margin_mm >= spec.target_width_mm:
            raise ValueError("左右留白之和必须小于目标宽度")
        if spec.weight_offset_mm > 0.3:
            raise ValueError("几何加粗建议不超过 0.3mm，否则 A/O/e 的内孔会被填死")

        cfg.font_family = self.var_family.get()
        cfg.font_style = self.var_style.get() or "Regular"
        cfg.names_txt = self.var_names.get().strip()
        cfg.output_root_dir = self.var_outroot.get().strip()
        # 与默认值相同就存空串：这样换机器、移动 exe 之后会自动重新探测，
        # 也不会把 PyInstaller 的临时解包路径写进配置。
        raw_exe = self.var_openscad.get().strip()
        cfg.openscad_path = (
            "" if not raw_exe or Path(raw_exe) == paths.default_openscad() else raw_exe
        )
        raw_tpl = self.var_template.get().strip()
        cfg.scad_template = (
            "" if not raw_tpl or Path(raw_tpl) == paths.scad_template() else raw_tpl
        )
        return cfg

    def _persist(self) -> None:
        try:
            save_config(self._collect_cfg())
        except Exception:
            pass

    def _schedule_persist(self) -> None:
        """参数改动后延迟存盘。

        不等到关窗才保存：用户改完参数直接关任务管理器、或程序被强杀时，
        下次打开还能沿用上次的目标宽度等设置。
        """
        job = getattr(self, "_persist_job", None)
        if job:
            self.root.after_cancel(job)
        self._persist_job = self.root.after(1500, self._persist_now)

    def _persist_now(self) -> None:
        self._persist_job = None
        self._persist()

    # ---------------- 日志 ----------------

    def log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def _append_log(self, message: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", message + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def clear_log(self) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

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
                    self.var_status.set(f"{done}/{total}")
                elif kind == "status":
                    self.var_status.set(payload)
                elif kind == "done":
                    self._on_worker_done(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ---------------- 交互 ----------------

    def _pick_names(self) -> None:
        path = filedialog.askopenfilename(
            title="选择名字清单",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialdir=str(paths.app_root()),
        )
        if path:
            self.var_names.set(path)
            self.preview()

    def _pick_outroot(self) -> None:
        path = filedialog.askdirectory(title="选择输出根目录")
        if path:
            self.var_outroot.set(path)

    def _pick_openscad(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 openscad.exe",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")],
            initialdir=str(Path(self.var_openscad.get()).parent),
        )
        if path:
            self.var_openscad.set(path)

    def _pick_template(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 scad 模板",
            filetypes=[("OpenSCAD 模型", "*.scad"), ("所有文件", "*.*")],
            initialdir=str(Path(self.var_template.get()).parent),
        )
        if path:
            self.var_template.set(path)
            self._schedule_preview()

    def _on_drop(self, event) -> None:  # pragma: no cover - 依赖 GUI
        raw = str(event.data).strip()
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        for part in raw.split():
            candidate = part.strip("{}")
            if candidate.lower().endswith(".txt") and Path(candidate).is_file():
                self.var_names.set(candidate)
                self.preview()
                return

    def open_output(self) -> None:
        try:
            cfg = self._collect_cfg()
        except ValueError:
            return
        names = Path(cfg.names_txt)
        if not cfg.output_root_dir:
            messagebox.showinfo(APP_TITLE, "请先选择输出目录")
            return
        target = batch_mod.derive_output_dir(names, cfg.output_root_dir)
        if not target.is_dir():
            target = Path(cfg.output_root_dir)
        if target.is_dir():
            webbrowser.open(target.as_uri())
        else:
            messagebox.showinfo(APP_TITLE, f"目录还不存在：{target}")

    def _read_names(self) -> list[str]:
        raw = self.var_names.get().strip()
        if not raw:
            raise ValueError("请先选择名字清单")
        path = Path(raw)
        if not path.is_file():
            raise ValueError(f"找不到名字清单：{path}")
        return validate.normalize_names(path.read_text(encoding="utf-8").splitlines())

    def _schedule_preview(self) -> None:
        if getattr(self, "_preview_job", None):
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(250, self.preview)
        self._schedule_persist()

    # ---------------- 预览 ----------------

    def preview(self) -> None:
        self._preview_job = None
        self.tree.delete(*self.tree.get_children())
        try:
            cfg = self._collect_cfg()
            names = self._read_names()
        except ValueError as exc:
            self.var_status.set(str(exc))
            return
        if not names:
            self.var_status.set("名字清单为空")
            return

        face = self.library.find(cfg.font_family, cfg.font_style)
        if face is None:
            self.var_status.set("内置字体库为空")
            return
        fm = self.library.metrics(face)
        spec = cfg.spec
        unique, duplicates = validate.dedupe(names)
        issues = validate.validate_batch(unique, fm, spec)
        curve = metrics.resolve_curve(face, spec)

        filled = 0
        for name in unique:
            blocking = validate.blocking_issues(issues.get(name, []))
            fit = metrics.fit(fm, name, spec)
            if blocking:
                note = validate.format_issues(blocking)
                tag = "err"
                size = spacing = width = ""
                fill = ""
            else:
                note = "；".join(fit.notes) or {
                    "ok": "正常",
                    "underfill": "未填满",
                    "spacing_min": "间距已压缩",
                }.get(fit.status, fit.status)
                tag = "ok" if fit.status == "ok" else "warn"
                size = f"{fit.size_mm:.2f}"
                spacing = f"{fit.spacing:.2f}"
                width = f"{fit.width_mm:.2f}"
                fill = f"{fit.fill_ratio * 100:.0f}%"
                filled += 1
            self.tree.insert(
                "",
                "end",
                values=(name, len(name), size, spacing, width, fill, note),
                tags=(tag,),
            )
        for name in duplicates:
            self.tree.insert(
                "",
                "end",
                values=(name, len(name), "", "", "", "", "与本批次前面重名，只生成一次"),
                tags=("err",),
            )
        self.var_status.set(
            f"可生成 {filled} / {len(unique)}　|　{face.label}　"
            f"精度 $fa={curve[0]:g} $fs={curve[1]:g}"
        )

    # ---------------- 自检 ----------------

    def check_env(self) -> None:
        try:
            cfg = self._collect_cfg()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.log("—— 自检 ——")
        try:
            self.log(f"OpenSCAD：{openscad.version(cfg.resolved_openscad())}")
        except Exception as exc:
            self.log(f"OpenSCAD 检测失败：{exc}")
            return
        self.log(f"模板：{cfg.resolved_template()}")
        face = self.library.find(cfg.font_family, cfg.font_style)
        if face is None:
            self.log("内置字体库为空")
            return
        ok = openscad.can_resolve_font(cfg.resolved_openscad(), face, self.library.env())
        self.log(f"字体解析：{face.label} → {'成功' if ok else '失败（会回退到默认字体）'}")
        self.log(f"fontconfig：{self.library.write_fontconfig()}")

    # ---------------- 生成 ----------------

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            cfg = self._collect_cfg()
            names = self._read_names()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        if not names:
            messagebox.showinfo(APP_TITLE, "名字清单为空")
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
                "请在上方「OpenSCAD」一栏指定 openscad.exe，\n"
                "或把 OpenSCAD 文件夹放在本程序旁边。",
            )
            return

        self._persist()
        self.cancel.clear()
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress["value"] = 0
        self.log("")
        self.log(f"开始生成，共 {len(names)} 个名字")

        output_dir = batch_mod.derive_output_dir(Path(cfg.names_txt), cfg.output_root_dir)
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
            self.var_status.set("已中止")
            return
        for line in report.lines():
            self.log(line)
        self.log("")
        self.log(report.summary())
        self.var_status.set(
            f"完成：成功 {report.generated}，跳过 {report.skipped}，失败 {report.failed}"
        )

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
