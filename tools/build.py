#!/usr/bin/env python3
"""打包脚本：把 stampgen 打成可分发的 Windows exe。

产出::

    dist/StampGen.exe          图形界面（无控制台窗口）
    dist/stampgen-cli.exe      命令行（保留控制台输出）
    dist/OpenSCAD/             便携 OpenSCAD（若项目根存在该目录）
    dist/README.md             使用说明

用法::

    .venv313/Scripts/python.exe tools/build.py            # 完整构建
    .venv313/Scripts/python.exe tools/build.py --no-openscad
    .venv313/Scripts/python.exe tools/build.py --zip      # 额外打一个便携压缩包

设计要点：

* ``fonts/``、``scad/``、``assets/`` 通过 ``--add-data`` 塞进 exe，
  运行期由 ``stampgen.paths.resource_root()`` 从 ``sys._MEIPASS`` 找到。
* ``--paths src`` 让 PyInstaller 在构建期就能解析 ``stampgen`` 包，
  入口脚本因此可以写得极薄。
* 两个 exe 共用同一套依赖，只有 console/windowed 之别。
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
SRC = ROOT / "src"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
ICON = ROOT / "assets" / "stampgen.ico"

APP_NAME = "StampGen"
CLI_NAME = "stampgen-cli"
VERSION = (2, 2, 7, 0)
VERSION_STR = ".".join(str(x) for x in VERSION[:3])

# 需要随程序分发的只读资源：源目录 -> exe 内目录名
DATA_DIRS = ["fonts", "scad", "assets"]

VERSION_INFO_TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version},
    prodvers={version},
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
        [StringStruct('CompanyName', 'stampgen'),
         StringStruct('FileDescription', '{description}'),
         StringStruct('FileVersion', '{version_str}'),
         StringStruct('InternalName', '{internal}'),
         StringStruct('LegalCopyright', ''),
         StringStruct('OriginalFilename', '{internal}.exe'),
         StringStruct('ProductName', '名字印章生成器'),
         StringStruct('ProductVersion', '{version_str}')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""

QUICKSTART = """\
名字印章生成器 {version}
========================================

【怎么算尺寸：只有一个逻辑】

  字号由你给定（如 6mm），底座长度按名字的真实字宽算出来，
  但不会超过你设的「最长不超过」（如 60mm）。

  · 3 个字母的印章就出 3 个字母那么长，不会硬撑到 60mm
  · 名字太长时，先把字间距从 1.00 压到 0.85（省约 15% 宽度）
  · 还不够就按比例缩字号，缩到 2.5mm 仍放不下才判「超长」并跳过
  · 每次调整都会在结果表的「状态」列标出来，鼠标悬停看完整原因

【个别名字装不下时】

  底座宽度（截面）默认是 6.6mm。个别名字的墨迹太高（比如含 g/y/p
  这类下沉字母）装不下时，程序只把这一枚的底座加宽（如 7.2mm），
  字号保持 6.00mm 不变 —— 一套印章字一样大，比截面一样宽更重要。

  结果表的「底座宽 mm」列会显示每一枚的实际宽度，加宽的行标橙色。
  想改成「缩字号、底座统一」：取消勾选「个别名字装不下时加宽它的底座」。

【字符间距是等距的】

  内置字体是等宽的（每个字母占位一样），但「占位相同」不等于
  「视觉间距相同」—— M 几乎占满格子、A 偏左，直接排出来疏密不匀。
  程序按墨迹宽重新平均分配间隙，打印出来每个间隙都一样宽。

  预览条用同一套坐标渲染，所见即所得。

【怎么用】

1. 双击 StampGen.exe 打开界面。
2. 填「印章几何」：底座宽度、高度、最长不超过、左右留白、字体高度。
3. 填「字体」：字体、字号、字间距、几何加粗、大小写。
   预览条会显示清单里第一个名字，改字号/加粗/大小写都会跟着变。
4. 选名字清单：点「选择 txt 文件」，或直接把名字粘贴进右下框
   （左边有行号，一行一个名字）。大小写在读入后立即生效。
5. 点「开始生成」，完成后自动打开这一批的文件夹。

  结果表会列出每个名字的字号、间距、底座宽、底座长与状态，
  参数一改就自动刷新，不用点任何「预览」按钮。

【输出在哪】

  <输出目录>\\output_stl<日期>\\20261029_2359\\
      Amanda.stl
      MIKE.stl
      json\\manifest.json

  每次「开始生成」新建一个带时间戳的子文件夹，一天做几批都不会
  互相覆盖。模型在顶层，json 记录收在 json\\ 里。

【参数会被记住】

  改完参数停手 1.5 秒就自动存进：
      %APPDATA%\\stampgen\\stampgen_config.json
  所有版本共用这一份 —— 换文件夹、升级版本都不会丢参数。
  想恢复出厂设置：删掉那个文件即可。

【需要 OpenSCAD】

本程序调用 OpenSCAD 完成建模，需要本机有 openscad.exe：
  · 推荐：把 OpenSCAD 整个文件夹放在本 exe 旁边（本包里已附带 OpenSCAD\\）
  · 或者：在界面里手动指定 openscad.exe 路径

【字体】

内置 11 个字重面：Daziji_V1~V5、Special Elite（3 个）、
ELEGANT TYPEWRITER（Regular/Bold/Light/Italic）。

⚠️ ELEGANT TYPEWRITER 声明「仅限非商业使用」，商业销售印章需先向
   作者购买授权（krraaa@yahoo.com）。其余字体是 Apache 2.0。

想加自己的字体：在本 exe 旁边新建 fonts 文件夹，把 .ttf 丢进去即可 ——
程序会优先使用外部 fonts\\，没有才用 exe 内置的字体。

【同时生成】

「同时生成」留空 = 按 CPU 核数自动决定（封顶 4）。
名字多的时候能快 3~4 倍，填 1 则退回逐个生成。

【命令行用法】

  stampgen-cli.exe fonts                                   列出可用字体
  stampgen-cli.exe check                                   自检 OpenSCAD 与字体解析
  stampgen-cli.exe fit --names names.txt                   只算尺寸，不建模
  stampgen-cli.exe batch --names names.txt --size 6 --max-width 60
  stampgen-cli.exe batch --names names.txt --case upper --weight 0.1
  stampgen-cli.exe batch --names names.txt --no-widen      装不下时缩字号
  stampgen-cli.exe fit --size 6 --max-width 60 --save      把这组参数存为默认
"""


def _log(msg: str) -> None:
    print(msg, flush=True)


def _data_args() -> list[str]:
    args: list[str] = []
    for name in DATA_DIRS:
        src = ROOT / name
        if not src.is_dir():
            raise SystemExit(f"缺少资源目录：{src}")
        args += ["--add-data", f"{src}{os.pathsep}{name}"]
    return args


def _write_version_file(path: Path, description: str, internal: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        VERSION_INFO_TEMPLATE.format(
            version=VERSION,
            version_str=VERSION_STR,
            description=description,
            internal=internal,
        ),
        encoding="utf-8",
    )
    return path


def _common_args(version_file: Path) -> list[str]:
    return [
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD / "work"),
        "--specpath",
        str(BUILD),
        "--paths",
        str(SRC),
        "--icon",
        str(ICON),
        "--version-file",
        str(version_file),
        "--onefile",
        *_data_args(),
        # tkinterdnd2 的 tkdnd 二进制要靠它自带的 hook 收集；
        # 这里再显式指定一次，避免 hook 自动发现失效时静默丢掉拖拽功能。
        "--additional-hooks-dir",
        str(Path(_tkinterdnd2_dir()) / "__pyinstaller"),
        "--hidden-import",
        "tkinterdnd2",
    ]


def _tkinterdnd2_dir() -> str:
    import tkinterdnd2

    return str(Path(tkinterdnd2.__file__).resolve().parent)


def _run_pyinstaller(args: list[str]) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", *args]
    _log("\n$ " + " ".join(cmd[:6]) + " ...")
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        raise SystemExit(f"PyInstaller 失败（返回码 {proc.returncode}）")


def _ensure_not_running(path: Path) -> None:
    """覆盖前确认 exe 没在运行。

    否则 PyInstaller 会在删除旧产物这一步失败，报一堆看不懂的 OSError。
    """
    if not path.exists():
        return
    try:
        with path.open("ab"):
            pass
    except OSError:
        raise SystemExit(
            f"{path.name} 正在运行或被占用，无法覆盖。\n"
            f"请先关闭它（任务管理器里结束 StampGen.exe）再重新打包。"
        ) from None


def build_gui() -> Path:
    _log("\n=== [1/2] 构建图形界面 StampGen.exe ===")
    vf = _write_version_file(BUILD / "version_gui.txt", "名字印章批量生成器", APP_NAME)
    _run_pyinstaller(
        [
            str(ROOT / "tools" / "entry_gui.py"),
            "--name",
            APP_NAME,
            "--windowed",
            *_common_args(vf),
        ]
    )
    return DIST / f"{APP_NAME}.exe"


def build_cli() -> Path:
    _log("\n=== [2/2] 构建命令行 stampgen-cli.exe ===")
    vf = _write_version_file(BUILD / "version_cli.txt", "名字印章生成器（命令行）", CLI_NAME)
    _run_pyinstaller(
        [
            str(ROOT / "tools" / "entry_cli.py"),
            "--name",
            CLI_NAME,
            "--console",
            *_common_args(vf),
        ]
    )
    return DIST / f"{CLI_NAME}.exe"


def stage_openscad() -> bool:
    """把项目根的 OpenSCAD 目录复制到 dist，形成免安装便携包。"""
    src = ROOT / "OpenSCAD"
    if not (src / "openscad.exe").is_file():
        _log("  [跳过] 未找到 OpenSCAD/openscad.exe，便携包将依赖用户自备 OpenSCAD")
        return False
    dst = DIST / "OpenSCAD"
    _log(f"  复制 OpenSCAD -> {dst}")
    # 用增量覆盖而不是先删后拷：既更快，也避免批量删除被安全策略拦截
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return True


def write_quickstart() -> Path:
    path = DIST / "使用说明.txt"
    path.write_text(QUICKSTART.format(version=VERSION_STR), encoding="utf-8")
    # README 与更新日志一起放进产物：README 里链接了 CHANGELOG，缺了就断链
    for name in ("README.md", "CHANGELOG.md"):
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, DIST / name)
    return path


def make_zip(exes: list[Path]) -> Path:
    target = DIST / f"{APP_NAME}-{VERSION_STR}-win64.zip"
    if target.exists():
        target.unlink()
    _log(f"\n打包便携压缩包 -> {target}")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for exe in exes:
            zf.write(exe, exe.name)
        for extra in ["使用说明.txt", "README.md", "CHANGELOG.md"]:
            p = DIST / extra
            if p.is_file():
                zf.write(p, extra)
        # 字体许可证要随包分发（Apache 2.0 与商业字体都要求保留声明）
        for lic in sorted((ROOT / "fonts").glob("*LICENSE*")):
            zf.write(lic, f"fonts/{lic.name}")
        oscad = DIST / "OpenSCAD"
        if oscad.is_dir():
            for f in sorted(oscad.rglob("*")):
                if f.is_file():
                    zf.write(f, str(f.relative_to(DIST)))
    return target


def report(exes: list[Path], zip_path: Path | None) -> None:
    _log("\n=== 产物 ===")
    for exe in exes:
        mb = exe.stat().st_size / 1024 / 1024
        _log(f"  {exe.name:<20}{mb:6.1f} MB")
    if zip_path and zip_path.is_file():
        _log(f"  {zip_path.name:<20}{zip_path.stat().st_size / 1024 / 1024:6.1f} MB")
    if (DIST / "OpenSCAD").is_dir():
        _log("  OpenSCAD/           已附带")
    _log(f"\n输出目录：{DIST}")


def main(argv: list[str] | None = None) -> int:
    global DIST
    parser = argparse.ArgumentParser(description="打包 stampgen 为 Windows exe")
    parser.add_argument("--no-openscad", action="store_true", help="不复制 OpenSCAD 目录")
    parser.add_argument("--no-cli", action="store_true", help="只构建图形界面")
    parser.add_argument("--zip", action="store_true", help="额外生成便携压缩包")
    parser.add_argument(
        "--dist",
        default=None,
        help="输出目录（默认 dist/）。程序正开着占用 exe 时，可以指到别的目录并行构建",
    )
    parser.add_argument(
        "--zip-only", action="store_true", help="跳过 PyInstaller，只重新打包便携压缩包"
    )
    args = parser.parse_args(argv)

    if args.dist:
        DIST = Path(args.dist).resolve()

    if args.zip_only:
        exes = [p for p in (DIST / f"{APP_NAME}.exe", DIST / f"{CLI_NAME}.exe") if p.is_file()]
        if not exes:
            raise SystemExit("dist 里没有 exe，先完整构建一次")
        write_quickstart()
        report(exes, make_zip(exes))
        return 0

    if not ICON.is_file():
        raise SystemExit(f"缺少图标：{ICON}（先运行 tools/make_icon.py）")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("未安装 PyInstaller：pip install pyinstaller") from None

    started = time.time()
    DIST.mkdir(parents=True, exist_ok=True)
    _ensure_not_running(DIST / f"{APP_NAME}.exe")
    if not args.no_cli:
        _ensure_not_running(DIST / f"{CLI_NAME}.exe")

    exes = [build_gui()]
    if not args.no_cli:
        exes.append(build_cli())

    for exe in exes:
        if not exe.is_file() or exe.stat().st_size < 1024 * 1024:
            raise SystemExit(f"产物异常：{exe}")

    if not args.no_openscad:
        stage_openscad()

    write_quickstart()
    zip_path = make_zip(exes) if args.zip else None
    report(exes, zip_path)
    _log(f"\n完成，耗时 {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
