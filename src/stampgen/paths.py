"""运行期路径解析。

区分两个根目录：

* ``resource_root()``：随程序分发的只读资源（``fonts/``、``scad/``、``assets/``）。
  源码运行时指向项目根；PyInstaller 打包后指向解包临时目录 ``sys._MEIPASS``。
* ``app_root()``：可写的应用目录，配置文件与缓存放这里。
  源码运行时是项目根；打包后是 exe 所在目录。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def is_frozen() -> bool:
    """当前是否运行在 PyInstaller 打包产物里。"""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """只读资源根目录。"""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_root() -> Path:
    """可写应用根目录（配置、缓存、默认输出）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def fonts_dir() -> Path:
    """字体库目录。

    打包后 ``resource_root()`` 指向解包临时目录，用户无法往里放字体，
    因此优先使用 exe 同级的 ``fonts/``（便携式自定义字体库）；
    不存在时回退到随程序分发的内置字体。
    """
    external = app_root() / "fonts"
    if external.is_dir() and any(external.glob("*.ttf")):
        return external
    return resource_root() / "fonts"


def scad_template() -> Path:
    """SCAD 模板文件。"""
    return resource_root() / "scad" / "stamp_template.scad"


def assets_dir() -> Path:
    return resource_root() / "assets"


def icon_path() -> Path:
    return assets_dir() / "stampgen.ico"


def cache_dir() -> Path:
    """可写的缓存目录；优先应用目录，不可写时退回临时目录。"""
    preferred = app_root() / ".cache"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".writable"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return preferred
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "stampgen-cache"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def config_path() -> Path:
    return app_root() / "stampgen_config.json"


def default_openscad() -> Path:
    """按优先级探测 OpenSCAD 可执行文件。"""
    candidates = [
        app_root() / "OpenSCAD" / "openscad.exe",
        Path(r"D:\OpenSCAD\openscad.exe"),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "OpenSCAD" / "openscad.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]
