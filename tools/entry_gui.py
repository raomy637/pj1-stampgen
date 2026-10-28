"""PyInstaller 入口：图形界面（无控制台窗口）。

打包成 ``--windowed`` 后没有控制台，任何启动期异常都会静默消失。
所以这里兜住所有异常：写一份崩溃日志到 exe 同级目录，并弹窗告知用户。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def _log_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parents[1]
    return base / "stampgen_crash.log"


def _report(exc: BaseException) -> None:
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        _log_path().write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "名字印章生成器 启动失败",
            f"{type(exc).__name__}: {exc}\n\n详细日志：\n{_log_path()}",
        )
        root.destroy()
    except Exception:
        pass


def main() -> int:
    from stampgen.gui.app import run

    return run()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - 顶层兜底
        _report(exc)
        raise SystemExit(1) from None
