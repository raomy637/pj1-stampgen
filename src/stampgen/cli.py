"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, batch, console, metrics, openscad, validate
from .config import CASE_LABELS, CASE_MODES, AppConfig, load_config, save_config
from .fonts import FontLibrary


def _apply_overrides(cfg: AppConfig, args: argparse.Namespace) -> AppConfig:
    if getattr(args, "openscad", None):
        cfg.openscad_path = args.openscad
    if getattr(args, "template", None):
        cfg.scad_template = args.template
    if getattr(args, "font", None):
        cfg.font_family = args.font
    if getattr(args, "style", None):
        cfg.font_style = args.style
    if getattr(args, "max_width", None) is not None:
        cfg.spec.max_width_mm = args.max_width
    if getattr(args, "size", None) is not None:
        cfg.spec.font_size_mm = args.size
    if getattr(args, "spacing", None) is not None:
        cfg.spec.letter_spacing = args.spacing
    if getattr(args, "case", None):
        cfg.spec.case_mode = args.case
    if getattr(args, "workers", None) is not None:
        cfg.workers = args.workers
    if getattr(args, "margin", None) is not None:
        cfg.spec.margin_mm = args.margin
    if getattr(args, "weight", None) is not None:
        cfg.spec.weight_offset_mm = args.weight
    if getattr(args, "min_spacing", None) is not None:
        cfg.spec.min_spacing = args.min_spacing
    if getattr(args, "base_width", None) is not None:
        cfg.spec.base_width_mm = args.base_width
    if getattr(args, "base_height", None) is not None:
        cfg.spec.base_height_mm = args.base_height
    if getattr(args, "letter_height", None) is not None:
        cfg.spec.letter_height_mm = args.letter_height
    if getattr(args, "save", False):
        # 显式要求才落盘：命令行常被脚本反复调用，不该悄悄改掉用户的默认配置
        save_config(cfg)
    return cfg


def _read_names(path: Path) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"找不到名字文件：{path}")
    return validate.normalize_names(path.read_text(encoding="utf-8").splitlines())


def cmd_fonts(args: argparse.Namespace) -> int:
    lib = FontLibrary(args.fonts_dir)
    faces = lib.scan()
    if not faces:
        print(f"内置字体库为空：{lib.directory}")
        return 2
    print(f"内置字体库：{lib.directory}\n")
    print(f"{'字体族':<30}{'样式':<12}{'字高比':>7}{'节点/字':>9}  文件")
    for face in faces:
        m = lib.metrics(face)
        print(
            f"{face.family:<30}{face.style:<12}{m.cap_ratio():>7.3f}"
            f"{face.points_per_glyph:>9.0f}  {face.path.name}"
        )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    cfg = _apply_overrides(load_config(), args)
    exe = cfg.resolved_openscad()
    try:
        ver = openscad.version(exe)
    except Exception as exc:
        print(f"[失败] OpenSCAD 检测：{exc}")
        return 2
    print(f"[通过] OpenSCAD：{ver}")
    print(f"[通过] 模板：{cfg.resolved_template()}")

    lib = FontLibrary(args.fonts_dir)
    face = lib.find(cfg.font_family, cfg.font_style)
    if face is None:
        print(f"[失败] 内置字体库为空：{lib.directory}")
        return 2
    ok = openscad.can_resolve_font(exe, face, lib.env())
    print(f"[{'通过' if ok else '失败'}] 字体解析：{face.label}（{face.path.name}）")
    if not ok:
        print("        OpenSCAD 未能解析到该字体，生成时会回退到默认字体。")
        return 2
    print(f"[通过] fontconfig：{lib.write_fontconfig()}")
    return 0


def cmd_fit(args: argparse.Namespace) -> int:
    cfg = _apply_overrides(load_config(), args)
    lib = FontLibrary(args.fonts_dir)
    face = lib.find(cfg.font_family, cfg.font_style)
    if face is None:
        print("内置字体库为空")
        return 2
    fm = lib.metrics(face)
    names = _read_names(Path(args.names)) if args.names else ["BELLA", "AVA", "GRACIE"]
    spec = cfg.spec
    curve = metrics.resolve_curve(face, spec)
    case = spec.effective_case()
    names = validate.apply_case(names, case)

    print(
        f"字体 {face.label} | 字号 {spec.font_size_mm:g}mm | 间距 {spec.letter_spacing:g} | "
        f"底座最长 {spec.max_width_mm:g}mm | 精度 $fa={curve[0]:g} $fs={curve[1]:g}"
        f"{' | 大小写 ' + CASE_LABELS[case] if case != 'keep' else ''}\n"
    )

    issues = validate.validate_batch(names, fm, spec)
    header = (
        console.pad("名字", 18)
        + console.pad("字号", 7, "right")
        + console.pad("间距", 7, "right")
        + console.pad("文字宽", 9, "right")
        + console.pad("底座长", 9, "right")
        + "  状态"
    )
    print(header)
    print("-" * 64)
    for name in names:
        fit = metrics.fit(fm, name, spec)
        bad = validate.blocking_issues(issues.get(name, []))
        note = validate.format_issues(bad) if bad else fit.detail
        line = (
            console.pad(name, 18)
            + f"{fit.size_mm:>7.2f}{fit.spacing:>7.2f}"
            + f"{fit.width_mm:>9.2f}{fit.base_len_mm:>9.2f}  "
            + console.pad(fit.label, 7)
        )
        print(line + (note if fit.needs_attention or bad else ""))

    spec_issues = validate.check_spec(fm, spec)
    if spec_issues:
        print("\n参数检查：")
        for issue in spec_issues:
            tag = "错误" if issue.is_error else "提示"
            print(f"  [{tag}] {issue.message}")

    print(
        "\n说明：以上是纯解析结果（不解析 GPOS 字偶距），对 AV/VA 这类紧排字母会偏大 1mm 左右；"
        "\n      实际生成时每个名字会先做一次实测探针校准，成品尺寸以实测为准。"
    )
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    cfg = _apply_overrides(load_config(), args)
    names_path = Path(args.names)
    names = _read_names(names_path)
    if not names:
        print("名字文件里没有有效内容")
        return 2

    out_root = Path(args.out or names_path.parent)
    output_dir = Path(args.outdir) if args.outdir else batch.derive_output_dir(names_path, out_root)
    lib = FontLibrary(args.fonts_dir)

    try:
        report = batch.run_batch(
            cfg,
            names,
            output_dir,
            library=lib,
            log=lambda m: print(m, flush=True),
            progress=lambda i, n, name, st: print(f"  [{i}/{n}] {name} {st}", flush=True),
        )
    except Exception as exc:
        print(f"批次失败：{exc}")
        return 2

    print()
    for line in report.lines():
        print(line)
    print("\n" + report.summary())
    return 0 if report.failed == 0 else 1


def cmd_gui(args: argparse.Namespace) -> int:
    from .gui.app import run

    return run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stampgen",
        description="名字印章批量生成：字号固定、底座按名字伸缩且不超上限",
    )
    parser.add_argument("--version", action="version", version=f"stampgen {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--fonts-dir", default=None, help="覆盖内置字体库目录")
        p.add_argument("--openscad", default=None, help="OpenSCAD 可执行文件路径")
        p.add_argument("--template", default=None, help="stamp_template.scad 路径")
        p.add_argument("--font", default=None, help="字体族名")
        p.add_argument("--style", default=None, help="字体样式，如 Regular / Bold")
        p.add_argument("--max-width", type=float, default=None, help="底座长度上限（毫米）")
        p.add_argument("--size", type=float, default=None, help="字号（毫米）")
        p.add_argument("--spacing", type=float, default=None, help="字间距，1.0 为原字距")
        p.add_argument(
            "--case",
            choices=list(CASE_MODES),
            default=None,
            help="大小写：keep 原样 / upper 全大写 / capitalize 首字母大写 / lower 全小写",
        )
        p.add_argument(
            "--workers",
            type=int,
            default=None,
            help="并发渲染数，0 或省略=按 CPU 核数自动（封顶 4）",
        )
        p.add_argument("--margin", type=float, default=None, help="文字单边留白（毫米）")
        p.add_argument("--weight", type=float, default=None, help="几何加粗量（毫米）")
        p.add_argument("--min-spacing", type=float, default=None, help="超宽时允许压缩到的间距下限")
        p.add_argument("--base-width", type=float, default=None, help="底座宽度 Y")
        p.add_argument("--base-height", type=float, default=None, help="底座高度 Z")
        p.add_argument("--letter-height", type=float, default=None, help="文字挤出高度")
        p.add_argument(
            "--save",
            action="store_true",
            help="把本次参数写入配置文件，以后不带参数也沿用",
        )

    p_fonts = sub.add_parser("fonts", help="列出内置字体")
    p_fonts.add_argument("--fonts-dir", default=None)
    p_fonts.set_defaults(func=cmd_fonts)

    p_check = sub.add_parser("check", help="自检 OpenSCAD 与字体解析")
    add_common(p_check)
    p_check.set_defaults(func=cmd_check)

    p_fit = sub.add_parser("fit", help="只预览拟合结果，不生成模型")
    add_common(p_fit)
    p_fit.add_argument("--names", default=None, help="名字清单 txt")
    p_fit.set_defaults(func=cmd_fit)

    p_batch = sub.add_parser("batch", help="批量生成 STL")
    add_common(p_batch)
    p_batch.add_argument("--names", required=True, help="名字清单 txt")
    p_batch.add_argument("--out", default=None, help="输出根目录（默认与 names 同目录）")
    p_batch.add_argument("--outdir", default=None, help="直接指定输出目录，覆盖自动命名")
    p_batch.set_defaults(func=cmd_batch)

    p_gui = sub.add_parser("gui", help="打开图形界面（默认）")
    p_gui.set_defaults(func=cmd_gui)

    return parser


def _safe_streams() -> None:
    """避免任何字符在 cp936 控制台上把整批结果炸掉。

    批次跑完才打印报告，此时因一个无法编码的字符抛异常，用户会以为整个批次失败。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _safe_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        return cmd_gui(args)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
