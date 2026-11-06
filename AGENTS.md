# AGENTS.md — stampgen 项目入口

> **唯一入口，只做路由。不要一次读完所有文档**：本文件（≤120 行）→ `README.md`（索引）→ `docs/guides/*.md`（细节）。
> 运行环境：`3dprint`（DESKTOP-E72MK8D / 192.168.68.44）→ `D:\HA1\PJ1`，Windows，**该机没有 git 客户端**。

## 这是什么

把客户名字批量转成可 3D 打印的印章 STL。Python 3.13（`.venv313`）+ OpenSCAD 2021.01，
单机 Windows 工具：GUI 给业务同事用，CLI 给脚本用。

- **版本唯一事实来源**：`pyproject.toml` 与 `src/stampgen/__init__.py`（当前 **2.2.8**）
- 发版时四处同步：上述两个文件 + `README.md` 第 3 行 + `CHANGELOG.md` 新条目 + `dist/vX.Y.Z/`
- 打包产物：`dist/vX.Y.Z/`，含 `StampGen.exe`（界面）、`stampgen-cli.exe`（命令行）、便携 `OpenSCAD\`

## 30 秒跑起来

```bat
:: 首次：装依赖（python -m stampgen 需要包可导入）
.venv313\Scripts\python.exe -m pip install -e ".[gui,dev]"

:: 日常：图形界面
run.bat

:: 命令行
.venv313\Scripts\python.exe -m stampgen batch --names data\names\names1026.txt --size 6 --max-width 60
```

没装 editable 时，`python -m stampgen` 会报 `No module named stampgen`；
临时绕过用 `set "PYTHONPATH=%CD%\src"`（`run.bat` 就是这么做的）。

## 改代码前的铁律

1. **没有失败测试就不写代码**；改代码必须同时加/改 `tests/` 里的用例
2. **默认只跑快速层**（`--ignore=tests/test_e2e.py`，秒级）；端到端层约 3 分钟，按需跑，不擅自全量
3. **主流程禁删**：旧版退役走 `legacy/` 归档 + `run-legacy.bat` 保留，不物理删除
4. **尺寸类改动必须实测**：影响几何的改动要用同名字对比 STL 实测宽度/字高，数字写进 `CHANGELOG.md`
5. **文档只增不减是事故**：新规则追加到对应文档；超红线先按主题拆分，不按行数硬切

## 我要做什么 → 读哪里

| 我要… | 读 |
|---|---|
| 装环境 / 跑 GUI / 跑 CLI | `README.md` §快速开始 |
| 调参数（字号、留白、加粗、并发、大小写） | `README.md` §参数说明 |
| 改限宽 / 缩字 / 加宽底座逻辑 | `docs/guides/width-fitting.md` + `src/stampgen/metrics.py` |
| 加字体 / 改字符等距 | `docs/guides/fonts.md` + `src/stampgen/fonts.py` |
| 改 OpenSCAD 模板 / 挤出与居中 | `scad/stamp_template.scad` + `docs/guides/how-it-works.md` |
| 打包 exe / 验证产物 | `docs/guides/packaging.md` + `tools/build.py` |
| 旧版对照（同事还在用旧版） | `docs/guides/legacy-migration.md` + `legacy/README.md` |
| 查某次重构为什么这么定 | `docs/plans/`（按日期命名，文首有「状态」） |
| 查某个版本改了什么 | `CHANGELOG.md` |
| 找素材 / 实测截图 | `docs/assets/`、`.cache/`（临时脚本与截图，可删） |

## 目录速查

```
src/stampgen/   主程序包（config / paths / fonts / metrics / template / openscad /
                validate / console / batch / cli / gui）
tests/          pytest：纯函数层 118 项 + 端到端层 14 项
scad/           OpenSCAD 模板（唯一一份，legacy 里的是旧版）
fonts/          内置字体 11 个字重面 + 两份许可证
tools/          打包、产物回归、GUI 冒烟、图标生成
docs/           plans/（设计决策）+ guides/（细节）+ assets/（图与表）
letter_blocks/  字母块子项目（独立，自带 README 与 scripts）
legacy/         旧版脚本与模板（仍可用，见 run-legacy.bat）
data/ dist/ build/ OpenSCAD/ .venv313/   数据与产物，不入库
```

完整树见 `README.md` §目录结构。

## 常用命令

```bat
.venv313\Scripts\python.exe -m pytest --ignore=tests/test_e2e.py   :: 快速层，秒级
.venv313\Scripts\python.exe -m pytest tests\test_e2e.py            :: 端到端，约 3 分钟
.venv313\Scripts\python.exe -m stampgen check                      :: 自检：OpenSCAD / 模板 / 字体
.venv313\Scripts\python.exe tools\build.py --zip                   :: 打包 + 便携压缩包
.venv313\Scripts\python.exe tools\verify_build.py --dist dist\v2.2.8   :: 产物回归
```

## 不要做

- 不要把 `data/` `dist/` `build/` `OpenSCAD/` `.venv313/` `.cache/` 提交进版本库
- 不要动 `fonts/ELEGANT_TYPEWRITER_LICENSE.txt` 的授权声明 —— 该字体**仅限非商业使用**
- 不要在没跑受影响测试的情况下宣称完成
