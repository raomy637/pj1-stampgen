"""共用 fixture。"""

from __future__ import annotations

from pathlib import Path

import pytest

from stampgen import paths
from stampgen.config import StampSpec
from stampgen.fonts import FontLibrary


@pytest.fixture(scope="session")
def library() -> FontLibrary:
    lib = FontLibrary()
    if not lib.scan():
        pytest.skip("内置字体库为空，跳过字体相关测试")
    return lib


@pytest.fixture(scope="session")
def face(library: FontLibrary):
    return library.find("Daziji_V5")


@pytest.fixture(scope="session")
def metrics_of(library: FontLibrary, face):
    return library.metrics(face)


@pytest.fixture()
def spec() -> StampSpec:
    """测试基准参数。

    显式关掉几何加粗：生产默认值会随使用习惯调整（现在是 6.6mm / 加粗 0.2），
    测试若跟着漂移，断言的数字就永远对不上。
    """
    return StampSpec(weight_offset_mm=0.0)


@pytest.fixture(scope="session")
def openscad_exe() -> Path:
    exe = paths.default_openscad()
    if not exe.is_file():
        pytest.skip("未找到 OpenSCAD，跳过端到端测试")
    return exe
