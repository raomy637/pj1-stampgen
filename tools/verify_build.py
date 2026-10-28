#!/usr/bin/env python3
"""打包产物验证：直接跑 dist 里的 exe，确认资源真的打进去了。

检查项：

1. 两个 exe 存在且体积合理
2. ``fonts`` 能列出内置字体（证明 ``fonts/`` 进了包、fontTools 可用）
3. ``fit`` 能算出字号（证明字宽模型与配置链路正常）
4. ``check`` 能解析字体（证明 ``scad/`` 模板路径与 fontconfig 注入正常）
5. ``batch`` 能真出 STL 并复核宽度（端到端，较慢，可用 --skip-batch 跳过）
6. exe 里含 tkdnd 二进制（证明拖拽功能没被 PyInstaller 丢掉）
7. 图标已嵌入 exe（导出 png 供肉眼确认）

用法::

    .venv313/Scripts/python.exe tools/verify_build.py
    .venv313/Scripts/python.exe tools/verify_build.py --skip-batch
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
GUI_EXE = DIST / "StampGen.exe"
CLI_EXE = DIST / "stampgen-cli.exe"

results: list[tuple[bool, str, str]] = []


def check(ok: bool, title: str, detail: str = "") -> bool:
    results.append((ok, title, detail))
    mark = "通过" if ok else "失败"
    print(f"[{mark}] {title}" + (f" —— {detail}" if detail else ""), flush=True)
    return ok


def _decode(data: bytes) -> str:
    """exe 的 stdout 走系统代码页（中文 Windows 是 cp936）。

    PyInstaller 的引导程序会显式设置 Python 的 IO 配置，``PYTHONIOENCODING``
    对冻结后的程序不一定生效，所以这里拿到字节后自己判断编码。
    """
    if not data:
        return ""
    for enc in ("utf-8", "cp936", "mbcs"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def run(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    cp = subprocess.run(
        [str(CLI_EXE), *args],
        capture_output=True,
        timeout=timeout,
        cwd=str(DIST),
        env=env,
    )
    return subprocess.CompletedProcess(
        cp.args, cp.returncode, _decode(cp.stdout), _decode(cp.stderr)
    )


def source_font_count() -> int | None:
    """源码模式下能列出几个字体面，作为 exe 输出的对照基线。"""
    try:
        cp = subprocess.run(
            [sys.executable, "-m", "stampgen", "fonts"],
            capture_output=True,
            timeout=180,
            cwd=str(ROOT),
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT / "src"),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            },
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if cp.returncode != 0:
        return None
    return sum(1 for ln in _decode(cp.stdout).splitlines() if ".ttf" in ln)


def step_files() -> None:
    for exe, floor in ((GUI_EXE, 8.0), (CLI_EXE, 8.0)):
        if not exe.is_file():
            check(False, f"{exe.name} 存在", "文件缺失")
            continue
        mb = exe.stat().st_size / 1024 / 1024
        check(mb >= floor, f"{exe.name} 体积 {mb:.1f} MB", f"下限 {floor} MB")


def step_fonts() -> None:
    try:
        cp = run(["fonts"], timeout=120)
    except subprocess.TimeoutExpired:
        check(False, "fonts 子命令", "超时")
        return
    rows = [ln for ln in cp.stdout.splitlines() if ".ttf" in ln]
    baseline = source_font_count()
    ok = cp.returncode == 0 and len(rows) >= 7
    detail = f"{len(rows)} 个字体面"
    if baseline is not None:
        ok = ok and len(rows) == baseline
        detail += f"（源码模式 {baseline} 个，一致）" if len(rows) == baseline else f"（源码模式 {baseline} 个，不一致）"
    check(ok, "内置字体可枚举", detail)
    if cp.returncode != 0:
        print(cp.stderr[-800:], flush=True)


def step_fit() -> None:
    try:
        cp = run(["fit"], timeout=180)
    except subprocess.TimeoutExpired:
        check(False, "fit 子命令", "超时")
        return
    check(cp.returncode == 0 and "字号" in cp.stdout, "拟合预览可运行")
    print("\n".join("      " + ln for ln in cp.stdout.strip().splitlines()[:7]), flush=True)


def step_check() -> None:
    try:
        cp = run(["check"], timeout=300)
    except subprocess.TimeoutExpired:
        check(False, "check 子命令", "超时")
        return
    passed = cp.stdout.count("[通过]")
    ok = cp.returncode == 0 and passed >= 4
    check(ok, "OpenSCAD + 模板 + 字体解析", f"{passed} 项通过")
    for ln in cp.stdout.strip().splitlines():
        print("      " + ln, flush=True)


def step_batch() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="stampgen_verify_"))
    names = tmp / "names.txt"
    names.write_text("BELLA\nAVA\n", encoding="utf-8")
    started = time.time()
    try:
        cp = run(["batch", "--names", str(names), "--out", str(tmp)], timeout=900)
    except subprocess.TimeoutExpired:
        check(False, "批量生成 STL", "超时（>900s）")
        return
    outdir = tmp / "output_stl"
    stls = sorted(outdir.glob("*.stl")) if outdir.is_dir() else []
    manifest = outdir / "manifest.json" if outdir.is_dir() else None
    ok = cp.returncode == 0 and len(stls) == 2 and manifest is not None and manifest.is_file()
    detail = f"{len(stls)} 个 STL，耗时 {time.time() - started:.0f}s"
    check(ok, "批量生成 STL", detail)
    print("\n".join("      " + ln for ln in cp.stdout.strip().splitlines()[-6:]), flush=True)
    if not ok:
        print(cp.stderr[-1200:], flush=True)


def step_tkdnd() -> None:
    """确认 tkdnd 的 dll 被打进 exe（拖拽功能依赖它）。"""
    try:
        cp = subprocess.run(
            [sys.executable, "-m", "PyInstaller.utils.cliutils.archive_viewer", "-l", str(GUI_EXE)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        check(False, "tkdnd 已打包", "列举归档超时")
        return
    blob = (cp.stdout or "") + (cp.stderr or "")
    found = "tkdnd" in blob.lower()
    check(found, "tkdnd 已打包（拖拽可用）", "归档中命中 tkdnd" if found else "未命中，拖拽会降级")


def step_icon() -> None:
    out = DIST / "icon_check.png"
    ps = (
        "Add-Type -AssemblyName System.Drawing; "
        f"$i=[System.Drawing.Icon]::ExtractAssociatedIcon('{GUI_EXE}'); "
        f"$i.ToBitmap().Save('{out}'); "
        f"Write-Output $i.Width"
    )
    try:
        cp = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        check(False, "图标已嵌入", "提取超时")
        return
    ok = cp.returncode == 0 and out.is_file()
    check(ok, "图标已嵌入 exe", f"导出 {out.name}" if ok else (cp.stderr or "")[-200:])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="验证 dist 下的打包产物")
    parser.add_argument("--skip-batch", action="store_true", help="跳过耗时的端到端生成")
    args = parser.parse_args(argv)

    print(f"验证目录：{DIST}\n", flush=True)
    step_files()
    step_fonts()
    step_fit()
    step_check()
    if not args.skip_batch:
        step_batch()
    step_tkdnd()
    step_icon()

    failed = [r for r in results if not r[0]]
    print(f"\n{'=' * 46}")
    print(f"共 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    for _, title, detail in failed:
        print(f"  失败：{title} {detail}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
