"""PyInstaller 入口：命令行（保留控制台）。

支持 ``fonts`` / ``check`` / ``fit`` / ``batch`` 子命令；
不带子命令时同样打开图形界面。
"""

from __future__ import annotations

import sys


def main() -> int:
    from stampgen.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
