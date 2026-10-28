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
    return StampSpec()


@pytest.fixture(scope="session")
def openscad_exe() -> Path:
    exe = paths.default_openscad()
    if not exe.is_file():
        pytest.skip("未找到 OpenSCAD，跳过端到端测试")
    return exe
