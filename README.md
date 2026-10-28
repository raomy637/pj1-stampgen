# 名字印章生成器（stampgen）

把客户名字批量转成可 3D 打印的印章 STL。核心能力：

- **两种宽度模式**：字固定算宽度（默认，字一样大、底座随名字变）／宽固定算字号（成品一样宽）
- **可换字体**：字体放在 `fonts/` 里即可用，不需要装进 Windows
- **可调字重**：优先用字体自带字重，再叠加 0~0.3mm 几何加粗微调
- **生成即校验**：每枚印章都会解析 STL 实测宽度，超差自动修正

## 快速开始

```bat
:: 图形界面
run.bat

:: 命令行：字固定 6mm，程序算出每个名字的底座长度
.venv313\Scripts\python.exe -m stampgen batch --names data\names\names1026.txt --mode auto --size 6

:: 命令行：成品统一 30mm 宽，字号自动求解
.venv313\Scripts\python.exe -m stampgen batch --names data\names\names1026.txt --mode fixed --width 30
```

图形界面操作顺序：选宽度模式 → 选字体 → 填字号（或目标宽度）→ 选名字清单 →
选输出目录 → 预览拟合 → 开始生成。
输出目录规则沿用历史约定：`names1026.txt` → `<输出目录>\output_stl1026\`。

## 两种宽度模式

| | 固定字号 → 自适应宽度（默认） | 固定宽度 → 自适应字号 |
|---|---|---|
| 你给什么 | 字号 6mm、字间距、留白 | 目标宽度 30mm |
| 程序算什么 | 每个名字各自的底座长度 | 每个名字各自的字号与间距 |
| 成品特征 | 字一样大，长名字的印章更长 | 印章一样宽，短名字的字更小 |
| 适合 | 一盒印章要统一字高（旧版的做法） | 成套出货要统一外形 |
| 预览里看 | 文字宽、底座长 | 文字宽、填充率 |

**固定字号模式**下，底座长度 = 文字实测墨迹宽 + 2×左右留白。
旧版按「字符数 × 6 + 6」给底座，对短名字明显偏宽松
（`TESS` 旧版给 30mm，而 4 个字母实际只占 12.7mm）；
想要同样的松紧感，把留白设到 6~8mm 即可。

**固定宽度模式**下，字号上限会被底座宽度卡住：字高不能超过底座宽。
`Daziji_V1` 的 6mm 字高是 5.88mm，底座 6mm 刚好装下；换成字高比更大的字体
（如 `Daziji_V5`，6mm 字号字高 6.43mm），就得把底座加宽到 6.5mm 以上，
否则程序会把字号压下来并在预览里说明。

## 参数会记住

界面里改过的所有参数——**目标宽度**、留白、字号范围、底座尺寸、几何加粗、字体、上次的名字清单与输出目录——
都会自动写进 `stampgen_config.json`（exe 同级），下次打开自动恢复。
改完参数**停止输入 1.5 秒**就会存一次，不必等关窗口；就算程序被强杀，下次也还在。

命令行默认**不写**配置（脚本反复调用时不该悄悄改掉默认值）。想让某组参数长期生效，加 `--save`：

```bat
stampgen-cli.exe fit --width 28 --save
:: 以后不带 --width 也按 28mm 走
```

删掉 `stampgen_config.json` 即可恢复出厂默认。


## 参数说明

| 参数 | 默认 | 说明 |
|---|---|---|
| 宽度模式 | 固定字号 | 固定字号＝算底座长度；固定宽度＝算字号与间距 |
| 固定字号 | 6 mm | 仅固定字号模式；所有名字共用同一字号 |
| 字间距 | 1.0 | 仅固定字号模式；1.0 为字体原字距，微调可改成品长度 |
| 目标宽度 | 30 mm | 仅固定宽度模式；印章底座长度，也是文字要填满的宽度 |
| 左右留白 | 1.5 mm | 文字与底座两端的间隙；固定宽度模式下可用宽 = 目标宽度 − 2×留白 |
| 字号范围 | 3.5 ~ 6 mm | 仅固定宽度模式；上限还会被底座宽度约束 |
| 几何加粗 | 0 mm | `offset(delta)`，超过约 0.3mm 会把 A/O/e 的内孔填死 |
| 底座 宽/高 | 6 / 10 mm | 截面尺寸；字高不得超过底座宽，否则字母悬空 |
| 文字高度 | 6 mm | 文字沿 Z 的挤出高度 |
| 同时生成 | 自动 | 并发渲染数；留空按 CPU 核数，封顶 4 |

**字号上限为什么会被底座宽度限制**：文字是站在底座顶面上、沿 +Z 挤出的，
字形在 Y 方向的高度不能超过底座宽度（6mm），否则字母会伸出底座边缘。
程序按字体实际字高比反推上限，所以换个更高的字体，字号会自动变小。

**为什么有的名字填不满**（仅固定宽度模式）：短名字（如 `AVA`）会先顶到字号上限，
再把间距放大去凑宽度；间距放到上限还凑不够，就停在「未填满」状态，
并在预览里给出建议宽度。这时要么把目标宽度改小，要么加大底座宽度换更大的字号——
两者是物理约束，不是算法问题。名字过长则相反：压到最小字号仍超宽时直接判 `too_long`，
并算出「底座至少要多少毫米」。改用固定字号模式就没有这个问题。

## 字体

把 `.ttf` / `.otf` 放进 `fonts/` 即可，程序启动时自动扫描。
界面的「字体 / 字重」两个下拉框来自扫描结果，同一个字体族有几个字重就列几个。

实现方式：运行时生成一份临时 fontconfig 配置，通过 `FONTCONFIG_FILE`
传给 OpenSCAD 子进程，因此**不需要把字体安装到系统**，换机器、重装系统都不会失效。

## 工作原理

三个经过实测校准的结论（OpenSCAD 2021.01）：

1. **`size` 不是毫米**。OpenSCAD 按 96dpi/72pt 放大，实际 em ≈ `size × 4/3`，
   且 advance 与字形墨迹的放大比例略有差异（1.3563 vs 1.3888），
   所以不能用单一系数换算。
2. **宽度与字号严格成正比**。因此一次廉价探针（只挤出 0.2mm 文字，约 0.3~1 秒）
   就能反推出精确字号，并自动吸收字体 GPOS 字距调整带来的误差。
   批次生成时，每个名字先探针、再正式渲染，实测偏差通常 < 0.02mm。
3. **曲面精度要按字体自适应**。做旧/点阵类字体每字有上百个轮廓节点，
   用粗精度（`$fa=12 $fs=2`）与细精度渲染结果视觉一致，但耗时从 48s 降到 7.5s；
   而常规字体（Arial）用粗精度会让 O/R 明显多边形化。程序按字体节点数自动选择。

`valign` 也改成 `baseline` + 由字体墨迹包围盒算出的垂直偏移，
这样任何字体都能在底座上精确居中（OpenSCAD 自带的 `center` 是按 ascent/descent 算的，
对整体上移过的自定义字体会明显偏上）。

## 命令行

```bat
:: 列出内置字体
python -m stampgen fonts

:: 自检：OpenSCAD 版本、模板、字体是否真的能被解析
python -m stampgen check

:: 只预览拟合结果，不生成模型
python -m stampgen fit --names names\names1026.txt --width 30

:: 批量生成
python -m stampgen batch --names names\names1026.txt --out output_stl --width 30 --font Daziji_V5

:: 打开图形界面
python -m stampgen gui
```

常用覆盖参数：`--font` `--style` `--width` `--margin` `--min-size` `--max-size`
`--weight` `--base-width` `--base-height` `--letter-height`。

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

打完包一定要验证，两条命令都跑一遍：

```bat
:: 跑 exe 的 fonts / fit / check / batch，并检查 tkdnd 与图标是否打进包里
.venv313\Scripts\python.exe tools\verify_build.py

:: 启动 GUI、确认主窗口出现、截图到 dist\gui_check.png 后自动关闭
.venv313\Scripts\python.exe tools\gui_smoke.py
```



## 目录结构

按「代码 / 数据 / 产物 / 环境」四层分开，只有前两层进版本库。

```
PJ1/
├── src/stampgen/           # 主程序包
│   ├── config.py           # 参数模型 + JSON 持久化
│   ├── paths.py            # 资源/配置路径解析（区分源码与打包）
│   ├── fonts.py            # 字体库、度量读取、fontconfig 注入
│   ├── metrics.py          # 字宽模型 + 定宽自适应求解
│   ├── template.py         # SCAD 参数渲染
│   ├── openscad.py         # 子进程调用、STL 测量、探针
│   ├── validate.py         # 名字预检
│   ├── batch.py            # 批次编排 + manifest
│   ├── cli.py              # 命令行入口
│   └── gui/app.py          # 图形界面
├── legacy/                 # 旧版（当前可用）
│   ├── batch_3Dnames.py    # 旧版批量脚本（含并发渲染）
│   ├── stamp_template.scad # 旧版模板（含 overlap 优化）
│   ├── all_in_one.py       # 更早的合并脚本
│   ├── 提取字体.py          # 字体改造（等宽 + 上移）
│   └── archive/            # 更早的废弃脚本，仅留档
├── scad/stamp_template.scad
├── fonts/                  # 内置字体库（含 LICENSE.txt）
├── assets/                 # 图标
├── tests/                  # pytest
├── tools/
│   ├── make_icon.py        # 生成 assets/stampgen.ico
│   ├── build.py            # 新版 PyInstaller 打包
│   ├── build_legacy.py     # 旧版 PyInstaller 打包
│   ├── verify_build.py     # 跑 exe 做功能回归
│   ├── gui_smoke.py        # GUI 冒烟测试 + 截图
│   ├── entry_gui.py        # 打包入口（界面，带崩溃兜底）
│   └── entry_cli.py        # 打包入口（命令行）
├── data/                   # 业务数据（不入库，约 400MB）
│   ├── names/              # 名字清单
│   └── output_stl/         # 生成结果
├── build/ dist/            # 构建中间产物与成品（不入库）
├── OpenSCAD/               # 便携 OpenSCAD（不入库）
├── .venv313/               # 唯一的虚拟环境（不入库）
├── run.bat                 # 新版图形界面
├── run-legacy.bat          # 旧版 exe
└── run-legacy-py.bat       # 旧版源码方式
```

每个输出目录里会写一份 `manifest.json`，记录当次字体、全部参数、
每个名字的字号/间距/实测宽度，便于事后追溯。

`build/trash/` 是重构与打包时的归档区：历史版本按日期存放，随时可以整个
删掉 `build/` 回收空间。

## 开发

```bat
.venv313\Scripts\python.exe -m pip install -e ".[dev]"
.venv313\Scripts\python.exe -m pytest
```

测试分两层：纯函数层（字宽模型、拟合、校验、STL 解析）不依赖 OpenSCAD；
端到端层会真实调用 OpenSCAD 渲染并复核几何，缺 OpenSCAD 时自动跳过。

## 从旧版本迁移

旧版功能对照（`legacy/batch_3Dnames.py` 及更早的脚本）：

| 旧版功能 | 新版 |
|---|---|
| 拖拽 `names*.txt` | ✅ 保留 |
| 选择输出根目录 | ✅ 保留 |
| 选择 OpenSCAD 路径 | ✅ 保留（且会探测 exe 同级的 `OpenSCAD\`） |
| 选择 scad 模板 | ✅ 保留 |
| 配置持久化 | ✅ 增强：参数改完 1.5 秒自动存，不用等关窗 |
| 日志框 / 后台线程 / 自检 | ✅ 保留，自检内容更细（版本、模板、字体解析、fontconfig） |
| 输出目录 `output_stl####` | ✅ 保留 |
| 手填字间距 spacing | ✅ 保留：固定字号模式下直接指定 |
| 字符数 → 底座长度映射表 | ✅ 升级：固定字号模式下按字体度量精算宽度，不再按字符数粗估 |
| 固定总宽、字号自适应 | ✅ 新增：切到固定宽度模式 |
| 字体改造（改 advance、整体上移） | ⚠️ 不再需要：直接把 `.ttf` 放 `fonts/` 即可；确需改造仍可用 `legacy/提取字体.py` |

新版新增：宽度模式切换、字体族/字重下拉、几何加粗、拟合预览表格、重名去重、
缺字检测、STL 实测宽度复核、并发渲染、`manifest.json` 追溯、命令行子命令、
曲面精度自适应。

| 旧文件 | 现状 |
|---|---|
| `main.py` / `beifen1.py` / `font.py` / `tesy.py` | 移入 `legacy/archive/`，功能已由 `stampgen batch` 取代 |
| `提取字体.py` | 移入 `legacy/`，字体改造改为直接放 `fonts/` |
| `batch_3Dnames.py` | 移入 `legacy/`，仍可用（`run-legacy.bat`），新版由 `stampgen.gui` 取代 |
| `program/` 整个目录 | 已拆解：源码进 `legacy/`，其余（venv / build / dist / .idea / 字体副本）归档到 `build/trash/` |
| `program/dist/PJ1Program.exe`（37MB 慢包） | 已归档，被 `dist/legacy/PJ1Program/` 取代 |

旧版硬编码的「字符数 → 底座长度」映射表已被固定字号模式取代：
同样是不用管宽度，但新版按字体真实度量算，不再假设每个字母都占 6mm
（旧版对 `LILLY` 这种窄字母会过宽，对 `WALKER` 这种宽字母会偏窄）。

## 想先用旧版（同事还没学会新版时）

旧版**没有删，而且已经重新打包，现在很快**：

| 方式 | 怎么用 | 速度 |
|---|---|---|
| **推荐** | 双击项目根的 `run-legacy.bat`，或直接双击 `dist\legacy\PJ1Program\PJ1Program.exe` | ~1 秒/个 |
| 改代码后试跑 | 双击 `run-legacy-py.bat`（用 `.venv313` 跑 `legacy/batch_3Dnames.py`） | ~3 秒/个 |
| 已归档 | `program\dist\PJ1Program.exe`（2026-03 的老包，在 `build\trash\` 里） | 1~2 分钟/个 |

新包 `dist\legacy\PJ1Program\` 是自包含的：OpenSCAD、模板、运行时都在文件夹里，
整个文件夹拷给同事双击就能用，参数（OpenSCAD 路径 / 模板 / 字间距 / 并发数）
改一次就记住。实测 10 个名字（去重后 7 个）**5.5 秒**。

```bat
:: 重新打包旧版
.venv313\Scripts\python.exe tools\build_legacy.py --zip
```

### 老包为什么慢（两个坑）

1. **OpenSCAD 被打进了 exe**，`--onefile` 每次启动解压到新的
   `%TEMP%\_MEIxxxxx\`。OpenSCAD 一换目录 fontconfig 字体缓存就失效，
   要重扫系统几百个字体——**每个名字都重扫一次**，1~2 分钟/个。
2. **配置写进 `_MEIPASS` 临时目录**，程序一关就没了，所以「参数记不住」。

新包改用 `--onedir` + OpenSCAD 放在 exe 旁边，路径固定，配置也写在 exe 旁边。

### 还有个隐藏的性能坑（已修）

`stamp_template.scad` 里文字底面原来和底座顶面**完全共面**，CGAL 做并集要反复
切分共面面片，单个名字从 3 秒拖到 13 秒。加了 `overlap = 0.05`（文字往底座里
多埋 0.05mm，远低于打印精度）后 **13.6s → 3.4s**，外形尺寸完全不变。

新旧版的分工可以这么理解：旧版「字固定、底座伸缩」，新版「底座固定、字伸缩」。
详见 `legacy/README.md`。
