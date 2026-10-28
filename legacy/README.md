# legacy —— 旧版（同事还在用的那套）

新版功能全部由 `src/stampgen/` 提供，但旧版**仍然完整可用**，同事暂时不用换。

## 这里有什么

```
legacy/
├── batch_3Dnames.py        # 旧版批量脚本（当前在用的那个，含并发渲染）
├── stamp_template.scad     # 旧版模板（含 overlap 优化，见下文）
├── all_in_one.py           # 更早的合并脚本，命令行备用
├── 提取字体.py              # 字体改造（统一 advance + 大写上移）
├── all_in_one_config.json  # 运行配置（含本机绝对路径，不入库）
└── archive/                # 更早的废弃脚本，仅留档
    ├── main.py
    ├── beifen1.py
    ├── font.py
    ├── tesy.py
    └── stamp_template.scad # 优化前的原始模板
```

> **2026-10-28 结构重构**：原来的 `program/` 目录已拆解。
> 源码归到本目录，其余（4 套 venv、build、dist、`.idea`、字体副本、37MB 旧 exe）
> 全部归档到 `build/trash/2026-10-28-refactor/`，需要还原随时可以从那里拿回来。

## 三个入口

**1）推荐：双击项目根的 `run-legacy.bat`**

启动 `dist\legacy\PJ1Program\PJ1Program.exe`（v1.3.0，重新打包的版本）。
整个 `PJ1Program` 文件夹拷给同事就能用，OpenSCAD、模板都在里面。

- 10 个名字（去重后 7 个）实测 **5.5 秒**，平均 0.8 秒/个
- 参数（OpenSCAD 路径、模板、字间距、并发数）改一次就自动存进
  `all_in_one_config.json`（exe 同级），下次打开自动沿用
- 换电脑 / 挪文件夹后路径失效会自动重新找 OpenSCAD

**2）改代码后试跑：双击 `run-legacy-py.bat`**

用项目里的 `.venv313` 直接跑 `legacy/batch_3Dnames.py`，和你在 PyCharm 里
点运行完全等效。改完代码不用重新打包，立刻能看到效果。

**3）命令行跑批**

```bat
dist\legacy\PJ1Program\PJ1Program.exe batch ^
    --names "D:\HA1\PJ1\data\names\names1026.txt" ^
    --outroot "D:\HA1\PJ1\data\output_stl" ^
    --spacing 1.2 ^
    --workers 4
```

`--workers 0`（或留空）= 按 CPU 核数自动，封顶 4。
注意：界面版 exe 没有控制台，命令行模式看不到输出，但文件会正常生成。
要看日志请用第 2 种方式，或 `python legacy\batch_3Dnames.py batch ...`。

旧版按字符数查表定底座长度（2→18mm、3→24mm、5→36mm、13→65mm）。

### 怎么判断它在干活

点「开始」后日志框应依次出现：

```
[10:39:45] 开始任务：批量生成 STL
[10:39:45] OpenSCAD 版本： OpenSCAD version 2021.01
[10:39:45] [生成] (1/7) 名字: BESS, 字符数: 4, 底座长度: 30mm, 字间距: 1.2
[10:39:47] [完成] (1/7) BESS.stl  422 KB  1.8s
```

正常是 1~3 秒蹦一条。如果一条要等 1 分钟以上，说明 OpenSCAD 路径不对，
在界面第一行改成 `<exe 所在目录>\OpenSCAD\openscad.exe`（新版会自动找到）。

## 为什么以前那么慢（三个坑，都修了）

老包（37MB，2026-03 打的，已归档）有这些问题：

1. **模板里文字底面和底座顶面完全共面**（z 都等于 `base_height/2`）。
   CGAL 做并集要反复切分共面面片：单个名字 13.6 秒，而纯 text 只要 0.84 秒。
   现在加了 `overlap = 0.05`（文字往底座里多埋 0.05mm，远低于打印精度），
   **13.6s → 3.4s**，外形尺寸完全不变（36.0 × 6.168 × 16.0）。
   这是最大的单点收益，而且跟打包方式无关。
2. **OpenSCAD 被打进了 exe 里**，`--onefile` 每次启动解压到
   `%TEMP%\_MEIxxxxx\`，目录名每次都变。现在改成 `--onedir`，OpenSCAD 放在
   exe 旁边的 `OpenSCAD\`，路径固定。
3. **配置文件写进 `_MEIPASS` 临时目录**，程序一关就没了 —— 所以以前
   「参数记不住」，每次都得重填 OpenSCAD 路径。现在写在 exe 旁边。

顺带一提：曾怀疑「fontconfig 缓存与 OpenSCAD 路径强绑定」，实测**不成立**。
把 OpenSCAD 整份复制到全新路径跑，仍是 7.1 秒，和固定路径一致——
缓存落在 `%LOCALAPPDATA%\fontconfig\cache`，按字体目录做 key。

## 文件对照

| 文件 | 现状 |
|---|---|
| `batch_3Dnames.py` | 本目录，旧版主脚本，仍可用 |
| `stamp_template.scad` | 本目录，含 overlap 优化 |
| `all_in_one.py` | 本目录，更早的合并脚本 |
| `提取字体.py` | 本目录，改造字体用（新版不需要） |
| `main.py` / `beifen1.py` / `font.py` / `tesy.py` | `archive/`，功能已被取代 |
| `program/` 整个目录 | 已拆解，见文首说明 |
| `program/dist/PJ1Program.exe` | 已归档，被 `dist/legacy/PJ1Program/` 取代 |

## 新旧版的关键差异

新版有**两种宽度模式**，旧版的做法对应其中「固定字号」那个：

| | 旧版 | 新版·固定字号（默认） | 新版·固定宽度 |
|---|---|---|---|
| 你给什么 | 字号 6mm、间距 | 字号 6mm、间距 | 目标总宽（如 30mm） |
| 底座长度 | 按字符数查表：2→18、3→24、5→36、13→65 | 按字体真实字宽精算 | 恒定，等于目标宽度 |
| 成品宽度 | 名字长短不同就不同 | 名字长短不同就不同 | 恒定 |
| 字号 | 固定 | 固定 | 自适应，受底座宽度约束 |
| 字体 | 需先用脚本改字体再放进去 | `.ttf` 直接放 `fonts/` | 同左 |
| 超长名字 | 表里没有就静默跳过 | 自动变长，不跳过 | 提前报 `too_long` 并算出建议宽度 |
| 配置 | 老包每次重置；新包自动保存 | 自动保存，下次沿用 | 同左 |
| 速度 | 老包 1~2 分钟/个，新包 ~1 秒/个 | ~2 秒/个（含探针校准） | 同左 |

旧版和新版「固定字号」模式的方向完全一致，都是「字固定、底座伸缩」，
差别只在底座长度怎么算：旧版假设每个字母占一个字号宽（`字符数 × 6 + 6`），
新版按字体真实度量算。所以同一批名字新版会明显更窄——
`TESS` 旧版给 30mm，4 个字母实际只占 12.7mm。
想要旧版那种宽松感，把新版的「左右留白」设到 6~8mm。

「固定宽度」是旧版没有的模式，用于成套出货要统一外形时。

