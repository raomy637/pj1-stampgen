"""批次编排：预检 → 拟合 → 渲染 → 实测复核 → 记录 manifest。"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from . import metrics, openscad, template, validate
from .config import AppConfig
from .fonts import FontFace, FontLibrary

ProgressFn = Callable[[int, int, str, str], None]
"""进度回调：(已完成数, 总数, 名字, 状态描述)。"""

LogFn = Callable[[str], None]

PROBE_SIZE = 10.0
"""探针渲染使用的固定字号；宽度与字号成正比，据此反推目标字号。"""


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
    fill_ratio: float = 0.0
    attempts: int = 0
    message: str = ""

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
    elapsed: float = 0.0
    results: list[NameResult] = field(default_factory=list)

    def lines(self) -> list[str]:
        rows = []
        # 用纯 ASCII 标记：中文 Windows 控制台是 cp936，✓/✗ 会直接抛 UnicodeEncodeError
        for r in self.results:
            mark = {"ok": "OK", "skipped": "--", "failed": "NG"}.get(r.status, "??")
            measured = f"{r.measured_width:.2f}" if r.measured_width is not None else "-"
            rows.append(
                f"{mark} {r.name:<16} 字号 {r.size_mm:>5.2f}  间距 {r.spacing:>4.2f}  "
                f"预测 {r.predicted_width:>6.2f}  实测 {measured:>6}  {r.message}"
            )
        return rows

    def summary(self) -> str:
        return (
            f"共 {self.total} 个，成功 {self.generated}，跳过 {self.skipped}，"
            f"失败 {self.failed}，耗时 {self.elapsed:.1f}s\n输出目录：{self.output_dir}"
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

    report = BatchReport(output_dir=Path(output_dir), font_label=face.label, total=len(names))
    started = time.time()

    log(f"字体：{face.label}（{face.path.name}）")
    log(f"曲面精度：$fa={curve[0]:g} $fs={curve[1]:g}（{'字体自带细节，粗精度' if face.is_dense_outline else '轮廓干净，细精度'}）")
    log(f"目标宽度：{spec.target_width_mm}mm，文字可用宽度：{spec.available_mm():.2f}mm")

    work, duplicates = validate.dedupe(list(names))
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

    for index, name in enumerate(work, start=1):
        if cancel is not None and cancel.is_set():
            log("已取消")
            break

        found = issues.get(name, [])
        blocking = validate.blocking_issues(found)
        if blocking:
            report.skipped += 1
            result = NameResult(name, "skipped", message=validate.format_issues(blocking))
            report.results.append(result)
            progress(index, len(work), name, "跳过")
            log(f"[跳过] {name}：{result.message}")
            continue

        fit = metrics.fit(font_metrics, name, spec)
        if not fit.ok:
            report.skipped += 1
            result = NameResult(
                name,
                "skipped",
                size_mm=fit.size_mm,
                spacing=fit.spacing,
                predicted_width=fit.width_mm,
                fill_ratio=fit.fill_ratio,
                message="；".join(fit.notes) or fit.status,
            )
            report.results.append(result)
            progress(index, len(work), name, "跳过")
            log(f"[跳过] {name}：{result.message}")
            continue

        lo, hi = metrics.size_bounds(font_metrics, spec)
        # 解析模型只能给到 1~2% 精度（字体 GPOS 字距会额外收紧），
        # 用一次廉价的实测探针反推精确字号与精确宽度。
        try:
            probe_w = openscad.probe_text_width(exe, face, name, fit.spacing, env)
            if fit.status == "underfill":
                # 短名字：字号与间距都已到顶，只校正报告里的宽度
                fit.width_mm = round(probe_w * fit.size_mm / PROBE_SIZE, 3)
            else:
                exact = metrics.size_from_probe(probe_w, PROBE_SIZE, spec.available_mm())
                if exact > hi:
                    exact = hi
                    fit.notes.append("字号已顶到上限，未填满目标宽度")
                    fit.status = "underfill"
                elif exact < lo:
                    exact = lo
                    fit.notes.append("字号已到下限")
                fit.size_mm = round(exact, 3)
                fit.width_mm = round(probe_w * fit.size_mm / PROBE_SIZE, 3)
            if spec.available_mm() > 0:
                fit.fill_ratio = round(fit.width_mm / spec.available_mm(), 4)
            if fit.status == "underfill":
                # 探针回填了真实宽度，提示里的数字也要跟着更新
                note = metrics.underfill_note(spec, fit.width_mm, spec.available_mm())
                fit.notes = [n for n in fit.notes if not n.startswith("成品仅")] + [note]
        except openscad.OpenSCADError as exc:
            log(f"  探针失败，改用解析估算：{exc}")

        out_path = output_dir / f"{name}.stl"
        result = NameResult(
            name,
            "ok",
            size_mm=fit.size_mm,
            spacing=fit.spacing,
            predicted_width=fit.width_mm,
            fill_ratio=fit.fill_ratio,
        )
        current_fit = fit
        attempts = 0

        try:
            while True:
                attempts += 1
                params = template.RenderParams.build(
                    name, face, spec, current_fit, font_metrics, curve=curve
                )
                openscad.export_stl(exe, tpl, params, out_path, env)
                extent = openscad.stl_extent(out_path, z_above=z_probe)
                result.measured_width = round(extent.width, 3)
                result.measured_depth = round(extent.depth, 3)
                result.size_mm = params.letter_size
                result.spacing = params.letter_spacing

                drift = extent.width - spec.available_mm()
                if abs(drift) <= cfg.verify_tolerance_mm:
                    break
                if current_fit.status == "underfill":
                    # 短名字已顶到字号与间距上限，再修正只会把字撑出底座
                    result.message = "；".join(current_fit.notes) or "未填满目标宽度"
                    break
                if attempts > cfg.max_fit_retries:
                    result.message = f"实测偏差 {drift:+.2f}mm 未能在 {attempts} 次内收敛"
                    break

                factor = spec.available_mm() / extent.width if extent.width > 0 else 1.0
                lo, hi = metrics.size_bounds(font_metrics, spec)
                new_size = min(max(current_fit.size_mm * factor, lo), hi)
                if abs(new_size - current_fit.size_mm) < 0.01:
                    result.message = f"实测偏差 {drift:+.2f}mm，字号已到边界"
                    break
                log(f"  修正 {name}：字号 {current_fit.size_mm:.2f} → {new_size:.2f}")
                current_fit.size_mm = round(new_size, 3)
                current_fit.width_mm = round(
                    metrics.predict_width(
                        font_metrics, name, new_size, current_fit.spacing, spec.weight_offset_mm
                    ),
                    3,
                )
                result.predicted_width = current_fit.width_mm

            result.attempts = attempts
            report.generated += 1
            progress(index, len(work), name, "完成")
            log(f"[生成] ({index}/{len(work)}) {name} 字号 {result.size_mm:.2f} 间距 {result.spacing:.2f} 实测宽 {result.measured_width:.2f}mm")
        except Exception as exc:  # 单个失败不影响整批
            report.failed += 1
            result.status = "failed"
            result.message = str(exc)
            progress(index, len(work), name, "失败")
            log(f"[失败] {name}：{exc}")
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink(missing_ok=True)

        report.results.append(result)

    for dup in duplicates:
        report.skipped += 1
        report.results.append(
            NameResult(dup, "skipped", message="与本批次前面重名，只生成一次")
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
            "elapsed_sec": round(report.elapsed, 2),
        },
        "items": [asdict(r) for r in report.results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
