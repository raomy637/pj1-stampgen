"""批次编排：大小写转换 → 预检 → 限宽求解 → 渲染 → 实测复核 → 记录 manifest。"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from . import console, metrics, openscad, template, validate
from .config import CASE_LABELS, AppConfig
from .fonts import FontFace, FontLibrary

ProgressFn = Callable[[int, int, str, str], None]
"""进度回调：(已完成数, 总数, 名字, 状态描述)。"""

LogFn = Callable[[str], None]

PROBE_SIZE = 10.0
"""探针渲染使用的固定字号；宽度与字号成正比，据此反推精确宽度。"""

PROBE_TOLERANCE = 0.003
"""解析预测与实测的相对偏差超过这个值才重新求解，避免无意义的抖动。"""

BASE_EPS = 0.02
"""底座长度比上限多出这点以内视为没超（STL 顶点精度级别）。"""


@dataclass
class NameResult:
    name: str
    status: str
    """ok / skipped / failed"""

    size_mm: float = 0.0
    spacing: float = 1.0
    predicted_width: float = 0.0
    measured_width: float | None = None
    measured_depth: float | None = None
    base_len: float = 0.0
    """实际用于渲染的底座长度（逐名不同）。"""

    fill_ratio: float = 0.0
    attempts: int = 0
    message: str = ""
    label: str = ""
    """状态短标签，给界面结果表用（正常 / 已压缩 / 已缩字 / 超长 …）。"""

    @property
    def deviation(self) -> float | None:
        if self.measured_width is None or not self.predicted_width:
            return None
        return (self.measured_width - self.predicted_width) / self.predicted_width


@dataclass
class BatchReport:
    output_dir: Path
    font_label: str
    total: int = 0
    generated: int = 0
    skipped: int = 0
    failed: int = 0
    compressed: int = 0
    """被压缩过的数量（间距或字号被压），用于提示用户。"""

    elapsed: float = 0.0
    results: list[NameResult] = field(default_factory=list)

    def lines(self) -> list[str]:
        rows = []
        # 用纯 ASCII 标记：中文 Windows 控制台是 cp936，✓/✗ 会直接抛 UnicodeEncodeError
        for r in self.results:
            mark = {"ok": "OK", "skipped": "--", "failed": "NG"}.get(r.status, "??")
            measured = f"{r.measured_width:.2f}" if r.measured_width is not None else "-"
            base = f"{r.base_len:.2f}" if r.base_len else "-"
            rows.append(
                f"{mark} {console.pad(r.name, 16)}"
                f" 字号 {r.size_mm:>5.2f}  间距 {r.spacing:>4.2f}"
                f"  底座 {base:>6}  文字宽 {measured:>6}"
                f"  {console.pad(r.label or '-', 7)}{r.message}"
            )
        return rows

    def summary(self) -> str:
        extra = f"，压缩 {self.compressed}" if self.compressed else ""
        return (
            f"共 {self.total} 个，成功 {self.generated}，跳过 {self.skipped}，"
            f"失败 {self.failed}{extra}，耗时 {self.elapsed:.1f}s\n输出目录：{self.output_dir}"
        )


def derive_output_dir(names_txt: Path | str, root: Path | str) -> Path:
    """沿用历史约定：``names1026.txt`` → ``<root>/output_stl1026``。

    文件名里没有 ``names`` 前缀（如 ``names.txt`` 或 ``0305.txt``）时，
    直接取整个 stem；纯 ``names`` 则不加后缀，避免出现 ``output_stlnames``。
    """
    stem = Path(names_txt).stem
    m = re.search(r"names(\d+)", stem, re.IGNORECASE)
    if m:
        suffix = m.group(1)
    else:
        suffix = "" if stem.lower() == "names" else stem
    return Path(root) / f"output_stl{suffix}"


def _noop(*_args, **_kwargs) -> None:
    return None


def resolve_workers(requested: int, total: int) -> int:
    """决定并发数。0 或负数表示自动：按 CPU 核数，封顶 4。

    封顶 4 是因为 OpenSCAD 渲染是 CPU 密集型的，再往上加收益递减，
    反而把机器拖到没法干别的事。
    """
    if total <= 0:
        return 1
    count = requested if requested and requested > 0 else min(4, os.cpu_count() or 1)
    return max(1, min(count, total))


def run_batch(
    cfg: AppConfig,
    names: Sequence[str],
    output_dir: Path,
    library: FontLibrary | None = None,
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
    cancel: threading.Event | None = None,
) -> BatchReport:
    progress = progress or _noop
    log = log or _noop
    library = library or FontLibrary()
    spec = cfg.spec

    face = library.find(cfg.font_family, cfg.font_style)
    if face is None:
        raise RuntimeError(f"内置字体库为空，请把 .ttf 放到 {library.directory}")
    font_metrics = library.metrics(face)
    curve = metrics.resolve_curve(face, spec)
    env = library.env()
    exe = cfg.resolved_openscad()
    tpl = cfg.resolved_template()

    case = spec.effective_case()
    converted = validate.apply_case(validate.normalize_names(names), case)

    report = BatchReport(
        output_dir=Path(output_dir), font_label=face.label, total=len(converted)
    )
    started = time.time()

    log(f"字体：{face.label}（{face.path.name}）")
    log(
        f"曲面精度：$fa={curve[0]:g} $fs={curve[1]:g}"
        f"（{'字体自带细节，粗精度' if face.is_dense_outline else '轮廓干净，细精度'}）"
    )
    log(
        f"字号 {spec.font_size_mm:g}mm、间距 {spec.letter_spacing:g}、"
        f"底座最长 {spec.max_width_mm:g}mm（短名字按实际宽度出，不补齐）"
    )
    if case != "keep":
        log(f"大小写：{CASE_LABELS.get(case, case)}")

    work, duplicates = validate.dedupe(converted)
    issues = validate.validate_batch(work, font_metrics, spec)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 预热：首次加载 fontconfig 字体缓存可能耗时数十秒
    log("预热字体缓存（本机首次运行需扫描系统字体，可能要 1 分钟左右）…")
    try:
        took = openscad.warmup(exe, face, env)
        log(f"预热完成，耗时 {took:.1f}s")
    except openscad.OpenSCADError as exc:
        log(f"预热失败（不致命）：{exc}")

    z_probe = spec.base_height_mm / 2.0 + 0.6
    workers = resolve_workers(cfg.workers, len(work))
    if workers > 1:
        log(f"并发渲染：{workers} 路")

    lock = threading.Lock()
    done_count = 0

    def say(message: str) -> None:
        # 并发时两条日志会互相插进对方中间，加锁保证每条完整
        with lock:
            log(message)

    def tick(index: int, name: str, status: str) -> None:
        nonlocal done_count
        with lock:
            done_count += 1
            done = done_count
        progress(done, len(work), name, status)

    def calibrate(name: str, fit: metrics.FitResult) -> metrics.FitResult:
        """用一次廉价实测探针把解析模型拉到实测口径。

        解析模型只到 1~2% 精度（字体 GPOS 字距会额外收紧），在 60mm 上限上
        就是 0.6~1.2mm 的误差 —— 足以让成品悄悄超上限。探针把宽度校准到
        0.02mm 级，再回灌给 fit 重新判断是否需要压缩。
        """
        try:
            probe_w = openscad.probe_text_width(exe, face, name, fit.spacing, env)
        except openscad.OpenSCADError as exc:
            say(f"  探针失败，改用解析估算：{exc}")
            return fit
        scale = metrics.probe_scale(font_metrics, name, fit.spacing, probe_w, PROBE_SIZE)
        if abs(scale - 1.0) <= PROBE_TOLERANCE:
            return fit
        calibrated = metrics.fit(font_metrics, name, spec, width_scale=scale)
        return calibrated if calibrated.ok else fit

    def process(index: int, name: str) -> NameResult:
        if cancel is not None and cancel.is_set():
            # 并发时任务可能在取消信号发出后才被调度到，这里再兜一次
            return NameResult(name, "skipped", message="已取消", label="跳过")
        found = issues.get(name, [])
        blocking = validate.blocking_issues(found)
        if blocking:
            result = NameResult(
                name, "skipped", message=validate.format_issues(blocking), label="跳过"
            )
            tick(index, name, "跳过")
            say(f"[跳过] {name}：{result.message}")
            return result

        fit = calibrate(name, metrics.fit(font_metrics, name, spec))
        if not fit.ok:
            result = NameResult(
                name,
                "skipped",
                size_mm=fit.size_mm,
                spacing=fit.spacing,
                predicted_width=fit.width_mm,
                fill_ratio=fit.fill_ratio,
                base_len=fit.base_len_mm,
                message=fit.detail,
                label=fit.label,
            )
            tick(index, name, "跳过")
            say(f"[跳过] {name}：{result.message}")
            return result

        out_path = output_dir / f"{name}.stl"
        result = NameResult(
            name,
            "ok",
            size_mm=fit.size_mm,
            spacing=fit.spacing,
            predicted_width=fit.width_mm,
            fill_ratio=fit.fill_ratio,
            base_len=fit.base_len_mm,
            label=fit.label,
            message=fit.detail if fit.needs_attention else "",
        )
        current = fit
        attempts = 0

        try:
            while True:
                attempts += 1
                params = template.RenderParams.build(
                    name, face, spec, current, font_metrics, curve=curve
                )
                openscad.export_stl(exe, tpl, params, out_path, env)
                extent = openscad.stl_extent(out_path, z_above=z_probe)
                result.measured_width = round(extent.width, 3)
                result.measured_depth = round(extent.depth, 3)
                result.size_mm = params.letter_size
                result.spacing = params.letter_spacing
                result.base_len = params.base_len

                # 唯一的硬指标：成品总长不得超过上限
                actual_base = spec.base_len_for(extent.width)
                if actual_base <= spec.max_width_mm + BASE_EPS:
                    break
                if attempts > cfg.max_fit_retries:
                    result.message = (
                        f"实测 {actual_base:.2f}mm 仍超过上限 {spec.max_width_mm:g}mm，"
                        f"已重试 {attempts} 次"
                    )
                    break

                factor = spec.max_text_width() / extent.width if extent.width > 0 else 1.0
                new_size = max(spec.hard_min_size_mm, current.size_mm * factor)
                if abs(new_size - current.size_mm) < 0.01:
                    result.message = f"实测 {actual_base:.2f}mm 超过上限，字号已到下限"
                    break
                say(f"  校正 {name}：实测 {actual_base:.2f}mm 超限，字号 {current.size_mm:.2f} → {new_size:.2f}")
                new_width = current.width_mm * (new_size / current.size_mm if current.size_mm else 1.0)
                current = replace(
                    current,
                    size_mm=round(new_size, 3),
                    width_mm=round(new_width, 3),
                    base_len_mm=round(spec.base_len_for(new_width), 3),
                )
                result.label = "已校正"
                result.predicted_width = current.width_mm

            result.attempts = attempts
            tick(index, name, "完成")
            say(
                f"[生成] ({index}/{len(work)}) {name} 字号 {result.size_mm:.2f} "
                f"间距 {result.spacing:.2f} 底座 {result.base_len:.2f} "
                f"文字宽 {result.measured_width:.2f}mm  {result.label}"
            )
        except Exception as exc:  # 单个失败不影响整批
            result.status = "failed"
            result.label = "失败"
            result.message = str(exc)
            tick(index, name, "失败")
            say(f"[失败] {name}：{exc}")
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink(missing_ok=True)

        return result

    results: dict[int, NameResult] = {}
    already_cancelled = cancel is not None and cancel.is_set()

    if already_cancelled:
        say("已取消")
        for index, name in enumerate(work, start=1):
            results[index] = NameResult(name, "skipped", message="已取消", label="跳过")
    elif workers == 1:
        for index, name in enumerate(work, start=1):
            if cancel is not None and cancel.is_set():
                say("已取消")
                break
            results[index] = process(index, name)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process, i, n): i for i, n in enumerate(work, start=1)}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:  # process 内部已兜底，这里只防万一
                    name = work[index - 1]
                    results[index] = NameResult(
                        name, "failed", message=str(exc), label="失败"
                    )
                    say(f"[失败] {name}：{exc}")
                if cancel is not None and cancel.is_set():
                    # 已开始的任务没法撤回，但还没轮到的可以取消
                    for pending in futures:
                        pending.cancel()
                    say("已取消，等待进行中的任务结束…")
                    break

    # 并发完成顺序是乱的，结果要按名字清单的原顺序落盘
    for index in sorted(results):
        item = results[index]
        report.results.append(item)
        if item.status == "ok":
            report.generated += 1
            if item.label in {"已压缩", "已缩字", "限字高", "已校正"}:
                report.compressed += 1
        elif item.status == "skipped":
            report.skipped += 1
        else:
            report.failed += 1

    for dup in duplicates:
        report.skipped += 1
        report.results.append(
            NameResult(
                dup,
                "skipped",
                message="与本批次前面重名，只生成一次",
                label="跳过",
            )
        )
        log(f"[跳过] {dup}：与本批次前面重名")

    report.elapsed = time.time() - started
    _write_manifest(cfg, face, report)
    return report


def _write_manifest(cfg: AppConfig, face: FontFace, report: BatchReport) -> Path:
    path = report.output_dir / "manifest.json"
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "font": {
            "family": face.family,
            "style": face.style,
            "file": face.path.name,
        },
        "spec": asdict(cfg.spec),
        "verify_tolerance_mm": cfg.verify_tolerance_mm,
        "summary": {
            "total": report.total,
            "generated": report.generated,
            "skipped": report.skipped,
            "failed": report.failed,
            "compressed": report.compressed,
            "elapsed_sec": round(report.elapsed, 2),
        },
        "items": [asdict(r) for r in report.results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
