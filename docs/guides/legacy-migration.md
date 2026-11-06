# 从旧版本迁移 / 先用旧版

> 从 `README.md` 拆出（2026-11-06），正文未改。返回 [README](../../README.md) ｜ 旧版说明见 `legacy/README.md`

## 从旧版本迁移

旧版功能对照（`legacy/batch_3Dnames.py` 及更早的脚本）：

| 旧版功能 | 新版 |
|---|---|
| 拖拽 `names*.txt` | ✅ 保留（也可以直接把名字粘进粘贴框） |
| 选择输出根目录 | ✅ 保留 |
| 选择 OpenSCAD 路径 | ✅ 保留（且会探测 exe 同级的 `OpenSCAD\`） |
| 选择 scad 模板 | ✅ 保留 |
| 配置持久化 | ✅ 增强：参数改完 1.5 秒自动存，不用等关窗 |
| 日志框 / 后台线程 | ✅ 保留 |
| 输出目录 `output_stl####` | ✅ 保留，并在其下按时间戳分批，同名不再覆盖 |
| 手填字间距 spacing | ✅ 保留 |
| 字符数 → 底座长度映射表 | ✅ 升级：按字体度量精算宽度，不再按字符数粗估 |
| 固定总宽、字号自适应 | ➖ 已去掉：用「最长不超过」代替，短名字不再硬撑到统一宽度 |
| 字体改造（改 advance、整体上移） | ⚠️ 不再需要：直接把 `.ttf` 放 `fonts/` 即可；确需改造仍可用 `legacy/提取字体.py` |

新版新增：字体预览条、字符等距、大小写转换、粘贴框（带行号）、
参数约束提示与一键采用、逐名底座宽度、结果表状态短标签 + 悬停详情、
生成后自动打开文件夹、输出按批次分文件夹、几何加粗、重名去重（含大小写）、
缺字检测、STL 实测宽度复核、并发渲染、`manifest.json` 追溯、命令行子命令、
曲面精度自适应、配置跨版本共享。

| 旧文件 | 现状 |
|---|---|
| `main.py` / `beifen1.py` / `font.py` / `tesy.py` | 移入 `legacy/archive/`，功能已由 `stampgen batch` 取代 |
| `提取字体.py` | 移入 `legacy/`，字体改造改为直接放 `fonts/` |
| `batch_3Dnames.py` | 移入 `legacy/`，仍可用（`run-legacy.bat`），新版由 `stampgen.gui` 取代 |
| `program/` 整个目录 | 已拆解：源码进 `legacy/`，其余（venv / build / dist / .idea / 字体副本）归档到 `build/trash/` |
| `program/dist/PJ1Program.exe`（37MB 慢包） | 已归档，被 `dist/legacy/PJ1Program/` 取代 |

旧版硬编码的「字符数 → 底座长度」映射表已被限宽算法取代：
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
