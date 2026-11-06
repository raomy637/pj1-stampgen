# 打包与产物验证

> 从 `README.md` 拆出（2026-11-06），正文未改。返回 [README](../../README.md) ｜ 相关代码 `tools/build.py`、`tools/verify_build.py`

## 打包

```bat
:: 新版
.venv313\Scripts\python.exe tools\build.py            :: 构建两个 exe
.venv313\Scripts\python.exe tools\build.py --zip      :: 额外产出便携压缩包
.venv313\Scripts\python.exe tools\build.py --no-cli --no-openscad

:: 旧版（同事还在用的那个）
.venv313\Scripts\python.exe tools\build_legacy.py --zip
```

产物在 `dist\`：

| 文件 | 说明 |
|---|---|
| `StampGen.exe` | 图形界面，无控制台窗口 |
| `stampgen-cli.exe` | 命令行，保留控制台输出 |
| `OpenSCAD\` | 便携 OpenSCAD（项目根有该目录时自动复制） |
| `使用说明.txt` / `README.md` | 给最终用户看的说明 |

`fonts/`、`scad/`、`assets/` 会一并打进 exe，拷走单个文件即可运行。
想换字体时，在 exe 同级新建 `fonts\` 放入 `.ttf`，程序会优先使用外部目录，
没有才回退到内置字体。

图形界面版是 `--windowed`，没有控制台，所以启动期异常会写进
`stampgen_crash.log`（exe 同级）并弹窗提示，不会静默退出。

## 打完包一定要验证

两条命令都跑一遍：

```bat
:: 跑 exe 的 fonts / fit / check / batch，并检查 tkdnd 与图标是否打进包里
.venv313\Scripts\python.exe tools\verify_build.py --dist dist\v2.2.8

:: 启动 GUI、确认主窗口出现、截图到 dist\gui_check.png 后自动关闭
.venv313\Scripts\python.exe tools\gui_smoke.py
```

> 每次发版把上面两条命令里的 `--dist` 换成当次版本目录，别照抄旧版本号。
