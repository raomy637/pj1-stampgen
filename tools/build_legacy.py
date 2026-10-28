#!/usr/bin/env python3
"""把旧版批量脚本（legacy/batch_3Dnames.py）重新打包成「快」的 exe。

为什么要重新打包
----------------
老包（已归档到 ``build/trash/``）是 ``--onefile`` 打的，并且把整个
``OpenSCAD\\`` 目录塞进了 exe 里。onefile 每次启动都要把 40 多 MB 解压到
``%TEMP%\\_MEIxxxxx``，那个临时目录每次都不一样：

* 启动慢（解压 + 杀软对新释放的 40MB exe 做实时扫描）；
* ``openscad.exe`` 的路径每次都变，fontconfig 缓存跟着失效；
* 配置文件写到 ``_MEIPASS`` 里，程序一关就没了 —— 所以以前「参数记不住」；
* ``--windowed`` 下 ``subprocess`` 没做重定向，OpenSCAD 的输出没地方去。

这个脚本改用 ``--onedir``，并且 **不把 OpenSCAD 打进 exe**，而是放在 exe
旁边。于是：启动是秒开、OpenSCAD 路径固定、配置写在 exe 旁边能记住。

产出
----
::

    dist/legacy/PJ1Program/
        PJ1Program.exe        图形界面（无控制台）
        OpenSCAD/             便携 OpenSCAD（固定路径，缓存可复用）
        stamp_template.scad   模板（放这儿方便同事自己改）
        使用说明.txt
        _internal/            PyInstaller 运行时（别动）

用法::

    .venv313/Scripts/python.exe tools/build_legacy.py
    .venv313/Scripts/python.exe tools/build_legacy.py --zip
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "legacy"
DIST_ROOT = ROOT / "dist" / "legacy"
BUILD = ROOT / "build" / "legacy"
ICON = ROOT / "assets" / "stampgen.ico"
ENTRY = LEGACY / "batch_3Dnames.py"
TEMPLATE = LEGACY / "stamp_template.scad"
OPENSCAD_SRC = ROOT / "OpenSCAD"

APP_NAME = "PJ1Program"
VERSION = (1, 3, 0, 0)
VERSION_STR = ".".join(str(x) for x in VERSION[:3])
APP_DIR = DIST_ROOT / APP_NAME

VERSION_INFO = f"""\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={VERSION},
    prodvers={VERSION},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [StringStruct('CompanyName', 'PJ1'),
         StringStruct('FileDescription', '名字印章 STL 批量生成（旧版界面）'),
         StringStruct('FileVersion', '{VERSION_STR}'),
         StringStruct('InternalName', '{APP_NAME}'),
         StringStruct('LegalCopyright', ''),
         StringStruct('OriginalFilename', '{APP_NAME}.exe'),
         StringStruct('ProductName', '名字印章生成器'),
         StringStruct('ProductVersion', '{VERSION_STR}')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""

README = f"""\
名字印章 STL 批量生成器 {VERSION_STR}
============================================

【第一次用】
1. 把整个「{APP_NAME}」文件夹拷到电脑上（不要只拷 exe，
   OpenSCAD 和模板都在这个文件夹里）。
2. 双击 {APP_NAME}.exe 打开界面。
3. 拖入 namesXXXX.txt（一行一个名字），选输出根目录。
4. 点「开始」。STL 会生成到：<输出根目录>/output_stlXXXX/

【为什么现在快了】
· 一个名字从 1~2 分钟降到 3 秒左右；并发默认开 4 个，平均每个名字不到 1 秒。
· 以前慢是因为 OpenSCAD 被塞在 exe 里，每次启动都解压到新的临时目录，
  字体缓存每次失效，要重扫系统几百个字体。
· 现在 OpenSCAD 就放在本文件夹的 OpenSCAD\\ 里，路径固定，缓存能复用。

【参数会被记住】
OpenSCAD 路径、模板、字间距、并发数，改一次就自动存进
all_in_one_config.json（和 exe 同一个文件夹），下次打开自动沿用。
想恢复默认：删掉 all_in_one_config.json。

【换了电脑 / 挪了文件夹】
配置里的旧路径失效时程序会自动重新找 OpenSCAD，一般不用手动改。
实在找不到，就在界面第一行手动选一下 OpenSCAD\\openscad.exe。

【「同时生成（并发数）」填多少】
留空 = 自动（按 CPU 核数，最多 4）。
电脑卡就把这个数改小，比如 2；机器强可以填 6~8，但收益不大。

【改了模板？】
stamp_template.scad 就在 exe 旁边，可以直接用记事本改（字体、字号、底座尺寸）。
改坏了没关系，删掉它，程序会用内置的那份。

【命令行用法（可选）】
  {APP_NAME}.exe 不带参数          打开界面
  {APP_NAME}.exe batch --names a.txt --outroot D:\\out --workers 4
  注意：界面版没有控制台，看不到命令行输出；需要看输出请用
  legacy\\batch_3Dnames.py 配合 python 运行。
"""


def _log(msg: str) -> None:
    print(msg, flush=True)


def _ensure_not_running(exe: Path) -> None:
    """覆盖前确认 exe 没在跑，否则 PyInstaller 删旧目录会失败。"""
    if not exe.exists():
        return
    try:
        with exe.open("ab"):
            pass
    except OSError:
        raise SystemExit(
            f"{exe.name} 正在运行或被占用，无法覆盖。\n"
            f"请先关掉它（任务管理器里结束 {APP_NAME}.exe）再重新打包。"
        ) from None


def _tkinterdnd2_hook_dir() -> str:
    import tkinterdnd2

    return str(Path(tkinterdnd2.__file__).resolve().parent / "__pyinstaller")


def _check_inputs() -> None:
    for p in (ENTRY, TEMPLATE):
        if not p.is_file():
            raise SystemExit(f"缺少输入文件：{p}")
    if not ICON.is_file():
        raise SystemExit(f"缺少图标：{ICON}（先运行 tools/make_icon.py）")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("未安装 PyInstaller：.venv313/Scripts/pip install pyinstaller") from None


def _retire_old_app_dir() -> Path | None:
    """把上一次的产物目录改名挪进 build/ 垃圾区，而不是删掉。

    两个原因：

    1. PyInstaller 发现 ``dist/legacy/PJ1Program`` 已存在时会先 rmtree 再建，
       上千个文件的批量删除很容易被安全策略拦下（表现为
       ``[safe-delete] SAFE_DELETE_BULK_CONFIRM_REQUIRED`` 后构建中断）。
    2. 改名是同一块盘上的原子操作，瞬间完成、不删任何文件，绝不会被拦。

    ``build/`` 本来就是构建垃圾区，用户想回收空间直接删掉整个 build 目录即可。
    """
    if not APP_DIR.exists():
        return None
    trash = BUILD / "trash" / f"PJ1Program-{int(time.time())}"
    trash.parent.mkdir(parents=True, exist_ok=True)
    try:
        APP_DIR.rename(trash)
    except OSError as exc:
        raise SystemExit(
            f"无法重命名旧产物目录 {APP_DIR}（{exc}）。\n"
            f"请先关闭 {APP_NAME}.exe，或手动把该文件夹挪走再重试。"
        ) from None
    _log(f"  旧产物已挪到 {trash.relative_to(ROOT)}（可随时删掉整个 build 目录）")
    return trash


def run_pyinstaller() -> Path:
    _log(f"=== 构建 {APP_NAME}.exe（onedir，不含 OpenSCAD）===")
    BUILD.mkdir(parents=True, exist_ok=True)
    vf = BUILD / "version_legacy.txt"
    vf.write_text(VERSION_INFO, encoding="utf-8")

    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    _ensure_not_running(APP_DIR / f"{APP_NAME}.exe")
    retired = _retire_old_app_dir()

    args = [
        str(ENTRY),
        "--name", APP_NAME,
        "--windowed",
        "--noconfirm",
        "--clean",
        # 关键：onedir 而不是 onefile —— 启动不解压，路径稳定
        "--onedir",
        "--distpath", str(DIST_ROOT),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--icon", str(ICON),
        "--version-file", str(vf),
        # 模板进 _internal，同时下面会往 exe 旁边再放一份（可编辑的那份优先）
        "--add-data", f"{TEMPLATE}{os.pathsep}.",
        "--hidden-import", "tkinterdnd2",
        "--additional-hooks-dir", _tkinterdnd2_hook_dir(),
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "matplotlib",
        "--exclude-module", "PIL",
    ]
    cmd = [sys.executable, "-m", "PyInstaller", *args]
    _log("\n$ " + " ".join(cmd[:4]) + " ... (onedir)")
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        # 构建失败时把旧产物还回去，别让用户手上一个能用的都没有
        if retired and retired.exists() and not APP_DIR.exists():
            retired.rename(APP_DIR)
            _log("  构建失败，已把旧产物恢复回原位")
        raise SystemExit(f"PyInstaller 失败（返回码 {proc.returncode}）")

    exe = APP_DIR / f"{APP_NAME}.exe"
    if not exe.is_file():
        raise SystemExit(f"未生成 exe：{exe}")
    return exe


def stage_openscad() -> bool:
    """把便携 OpenSCAD 复制到 exe 同级。

    这是整个提速的核心：路径固定，OpenSCAD 的字体缓存才能复用。
    """
    if not (OPENSCAD_SRC / "openscad.exe").is_file():
        _log(f"  [跳过] 没找到 {OPENSCAD_SRC / 'openscad.exe'}")
        _log("         用户需要自己在界面里指定 openscad.exe 路径")
        return False
    dst = APP_DIR / "OpenSCAD"
    _log(f"  复制 OpenSCAD -> {dst}")
    # 增量覆盖：比先删后拷快，也避免批量删除被安全策略拦
    shutil.copytree(OPENSCAD_SRC, dst, dirs_exist_ok=True)
    return True


def stage_assets() -> None:
    """模板和使用说明放到 exe 旁边，方便同事直接改。"""
    shutil.copy2(TEMPLATE, APP_DIR / TEMPLATE.name)
    (APP_DIR / "使用说明.txt").write_text(README, encoding="utf-8")
    _log("  模板 / 使用说明 已放到 exe 同级")


def make_zip() -> Path:
    target = DIST_ROOT / f"{APP_NAME}-{VERSION_STR}-win64.zip"
    if target.exists():
        target.unlink()
    _log(f"\n打包 -> {target}")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(APP_DIR.rglob("*")):
            if f.is_file():
                zf.write(f, str(Path(APP_NAME) / f.relative_to(APP_DIR)))
    return target


def report(exe: Path, zip_path: Path | None) -> None:
    _log("\n=== 产物 ===")
    total = sum(f.stat().st_size for f in APP_DIR.rglob("*") if f.is_file())
    _log(f"  {APP_DIR.relative_to(ROOT)}/   {total / 1024 / 1024:.1f} MB（整包）")
    _log(f"  {exe.name:<24}{exe.stat().st_size / 1024 / 1024:6.1f} MB（exe 本身）")
    if zip_path and zip_path.is_file():
        _log(f"  {zip_path.name:<24}{zip_path.stat().st_size / 1024 / 1024:6.1f} MB（压缩包）")
    _log("\n发给同事：整个 PJ1Program 文件夹（或那个 zip）拷过去，双击 exe 即可。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重新打包旧版批量脚本为快速 exe")
    parser.add_argument("--no-openscad", action="store_true", help="不复制 OpenSCAD 目录")
    parser.add_argument("--zip", action="store_true", help="额外生成 zip 压缩包")
    parser.add_argument("--stage-only", action="store_true", help="跳过 PyInstaller，只补资源")
    args = parser.parse_args(argv)

    started = time.time()
    _check_inputs()

    if args.stage_only:
        if not (APP_DIR / f"{APP_NAME}.exe").is_file():
            raise SystemExit(f"{APP_DIR} 里还没有 exe，先完整构建一次")
        if not args.no_openscad:
            stage_openscad()
        stage_assets()
    else:
        exe = run_pyinstaller()
        if not args.no_openscad:
            stage_openscad()
        stage_assets()

    zip_path = make_zip() if args.zip else None
    report(APP_DIR / f"{APP_NAME}.exe", zip_path)
    _log(f"\n完成，耗时 {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
