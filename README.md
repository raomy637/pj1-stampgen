# 名字印章生成器（stampgen）

当前版本 **2.2.7**　|　[更新日志](CHANGELOG.md)　|　[设计文档](docs/plans/)　|　[旧版说明](legacy/README.md)

> 便携包里只有 `README.md` / `CHANGELOG.md` / `使用说明.txt` / `fonts/` 下的许可证，
> `docs/` 和 `legacy/` 的链接只在源码仓库里有效。

把客户名字批量转成可 3D 打印的印章 STL。核心能力：

- **限宽出尺寸**：字号你定，底座长度按名字真实字宽算，但不超过「最长不超过」；短名字不补齐
- **逐名底座宽度**：个别名字装不下时单独加宽它的底座，字号保持统一（不会为了一个字把整批压小）
- **可换字体**：字体放在 `fonts/` 里即可用，不需要装进 Windows，选完立刻有预览
- **字符等距**：等宽字体的「占位」相同但「墨迹间隙」不同，程序按墨迹宽重新平均分配，打印出来间距一致
- **可调字重**：优先用字体自带字重，再叠加 0~0.3mm 几何加粗微调（预览同步变化）
- **大小写**：保持原样 / 全部大写 / 首字母大写 / 全部小写，读入即生效
- **生成即校验**：每枚印章都会解析 STL 实测宽度，超上限自动缩字重做

## 快速开始

```bat
:: 图形界面
run.bat

:: 命令行：字固定 6mm，底座按名字算，最长不超过 60mm
.venv313\Scripts\python.exe -m stampgen batch --names data\names\names1026.txt --size 6 --max-width 60

:: 想统一大写 + 略微加粗
.venv313\Scripts\python.exe -m stampgen batch --names data\names\names1026.txt --size 6 --case upper --weight 0.08
```

图形界面操作顺序：填印章几何 → 选字体/字号/加粗/大小写（预览条即时可见）→
选名字 txt 或直接粘贴 → 选输出目录 → 开始生成。
参数一改结果表就自动刷新，没有「预览」按钮要点。
输出目录规则：`names1026.txt` → `<输出目录>\output_stl1026\`，
直接粘贴的名字（没有 txt）→ `<输出目录>\output_stl\`。
**每次点「开始生成」会在里面新建一个带时间戳的子文件夹**，一天做几批都不会互相覆盖：

```
<输出目录>\output_stl1026\
  20261029_2359\        ← 第一批
    Amanda.stl
    MIKE.stl
    json\manifest.json
  20261030_0915\        ← 第二批，互不影响
    Daisy.stl
    json\manifest.json
```

模型文件在批次目录顶层，json 记录收在 `json\` 子文件夹里。
生成完会自动打开输出文件夹（可在配置区取消勾选）。

## 限宽：字号固定，底座按名字伸缩

只有一个逻辑：**你给字号，程序算底座长度，但不许超过上限**。

```
1. 墨迹高 + 2×加粗 > 底座宽度 + 0.3 ?
   a. 是 → 这一枚的底座单独加宽到刚好装下（字号不动）→ 状态「加宽」
   b. 关掉开关则改为缩字号 → 状态「限字高」
2. width = 字体度量算出的文字墨迹宽
   base_len = width + 2 × 左右留白
3. base_len > 最长不超过 ?
   a. 先把字间距从 1.00 压到 0.85（约省 15% 宽度）
   b. 还超 → 按比例缩字号（间距保持 0.85）
   c. 缩到 2.5mm 仍超 → 判「超长」，跳过并算出需要多长
```

三条约束性质不同：

- 底座宽度是**逐名**的：一套印章「字一样大」比「截面一样宽」重要，
  个别名字（含 g/y/p 下沉字母）会单独变胖，其余仍用默认值
- 「最长不超过」是**硬上限**，超了必须压，压不动就跳过
- 短名字**不补齐**：`AVA` 就是 13mm，不会硬撑到 60mm

每次调整都会在结果表的「状态」列标出来（加宽 / 已压缩 / 已缩字 / 限字高 / 超长），
「底座宽 mm」列直接显示每一枚的实际宽度，鼠标悬停看完整原因。
**动过就一定会告诉你，不会偷偷改。**

旧版按「字符数 × 6 + 6」给底座，对短名字明显偏宽松
（`TESS` 旧版给 30mm，4 个字母实际只占 12.7mm）；
想要同样的松紧感，把留白设到 6~8mm 即可。

**为什么字号会被底座宽度限制**：文字站在底座顶面上、沿 +Z 挤出，
并且按**墨迹包围盒**垂直居中，所以能占满底座宽度的就是这个墨迹高度。
程序按字体真实轮廓算高度，装不下就压字号。

实测本项目七款字体在 6mm 字号下墨迹高 6.01~6.23mm（`TESS` 6.01、`DAISY` 6.18），
比 6mm 底座多出 0.0~0.23mm —— 这是圆形字母（O/S/D）的 overshoot，属于字形设计，
0.3mm 以内程序不管。超过才是真的装不下：

| 名字 | 6mm 字号的墨迹高 | 6mm 底座 |
|---|---|---|
| `TESS` | 6.01 mm | 放得下 |
| `DAISY` | 6.18 mm | 放得下（overshoot 0.18mm） |
| `Daisy`（小写 y） | 8.11 mm | 放不下，会压到 4.44mm |

所以参数区下方会直接给一条提示 + 「采用」按钮，点一下就改好。
（注：这里的字高按墨迹量，不是「基线到大写字母顶」——
自定义字体常整体上移，那个数会虚高但字形没变大。）

## 参数会记住

界面里改过的所有参数——**字号**、字间距、几何加粗、大小写、最长不超过、留白、
底座尺寸、字体、上次的名字清单与输出目录——
都会自动写进 `%APPDATA%\stampgen\stampgen_config.json`，下次打开自动恢复。

**配置不在 exe 旁边**，所有版本共用同一份 —— 换 `dist/v2.2.x/` 这种目录不会丢参数。
（v2.2.3 及更早版本写在 exe 同级，首次启动会自动搬过来一次。）
改完参数**停止输入 1.5 秒**就会存一次，不必等关窗口；就算程序被强杀，下次也还在。

命令行默认**不写**配置（脚本反复调用时不该悄悄改掉默认值）。想让某组参数长期生效，加 `--save`：

```bat
stampgen-cli.exe fit --size 6 --max-width 28 --save
:: 以后不带 --size / --max-width 也按 6mm / 28mm 走
```

删掉 `%APPDATA%\stampgen\stampgen_config.json` 即可恢复出厂默认。


## 参数说明

| 参数 | 默认 | 说明 |
|---|---|---|
| 底座宽度 | 6.6 mm | 截面 Y 向的**默认**值；个别名字装不下会自动加宽 |
| 装不下时加宽底座 | 勾选 | 勾选=加宽这一枚的底座（字号统一）；取消=缩这一枚的字号（底座统一） |
| 字符等距 | 开启 | 按墨迹宽平均分配间隙；关掉则按字体原本字距（`--no-even-spacing`） |
| 底座高度 | 10 mm | 截面 Z 向 |
| 最长不超过 | 60 mm | 底座长度硬上限；短名字不补齐，超了才压 |
| 左右留白 | 1.5 mm | 底座长 = 文字宽 + 2×留白 |
| 字体高度 | 6 mm | 文字沿 Z 的挤出高度 |
| 字号 | 6 mm | 所有名字共用同一字号（超宽或超高时会被压，状态列会标） |
| 字间距 | 1.0 | 1.0 为字体原字距；超宽时先压到 0.85 |
| 几何加粗 | 0.2 mm | `offset(delta)`，超过约 0.3mm 会把 A/O/e 的内孔填死 |
| 大小写 | 保持原样 | 保持原样 / 全部大写 / 首字母大写 / 全部小写，读入即生效 |
| 同时生成 | 自动 | 并发渲染数；留空按 CPU 核数，封顶 4 |

参数之间不是独立的，程序会实时校验并在参数区下方给提示（最多 3 条，带「采用」）：

| 检查项 | 条件 | 级别 | 程序行为 |
|---|---|---|---|
| 留白挤掉全部宽度 | `2 × 留白 ≥ 最长不超过` | 红 | 拒绝生成 |
| 加粗过量 | `加粗 > 0.3mm` | 红 | 拒绝生成 |
| 墨迹高度超出底座宽 | `墨迹高 + 2×加粗 > 底座宽 + 0.3` | 蓝/橙 | 自动加宽该名底座（蓝）；关掉开关则缩字号（橙） |
| 上限过小 | 该字号下 `MMM` 都放不下 | 橙 | 生成时大量缩字，提示加大上限 |
| 文字高度过高 | `字体高度 > 1.5 × 底座高度` | 橙 | 不阻止，提示印章会偏高 |

「墨迹高度」这条要拿清单里的**具体名字**来算 —— 字有多高取决于名字里有哪些字母
（g/y/p 有下沉、Q 的尾巴到基线、V 比 W 高一截），用固定样本估只会误报。
所以名字清单为空时这条不检查；会被跳过的名字（中文、超长、缺字形）也不参与计算。

## 字体

把 `.ttf` / `.otf` 放进 `fonts/` 即可，程序启动时自动扫描。

### 内置字体

| 字体 | 字重 | 类型 | 6mm 字号字高 | 许可 |
|---|---|---|---|---|
| `Daziji_V1` ~ `V5` | Regular | 等宽（改造版） | 5.9~6.9mm | 随 Special Elite（Apache 2.0） |
| `Special Elite` | Regular | 等宽 | 5.6mm | Apache 2.0 |
| `Special Elite Mono Final` | Regular | 等宽 | 6.1mm | Apache 2.0 |
| **`ELEGANT TYPEWRITER`** | **Regular / Bold / Light / Italic** | **比例** | **5.3mm** | **⚠️ 仅限非商业使用** |

> **`ELEGANT TYPEWRITER` 的许可限制**：作者 Lukas Krakora 声明
> "free for **non-commercial** use only"。商业用途（例如批量制作并销售印章）
> 需要先联系 `krraaa@yahoo.com` 购买商业授权。
> 许可证原文见 `fonts/ELEGANT_TYPEWRITER_LICENSE.txt`。

它是**比例字体**（每个字母占位不同），原始字距已经由设计师调过，
间隙极差只有 0.17~0.69mm（`Daziji` 系列是 1.27mm），所以视觉上更均匀。

### 字符等距

内置字体都是「等宽」的（每个字母占位一样），但**占位相同不等于视觉间距相同**：

| 字母 | 占位 | 墨迹宽 | 左边空 | 右边空 |
|---|---|---|---|---|
| A | 5.29 | 4.59 | −0.01 | 0.71 |
| M | 5.29 | 5.07 | 0.39 | −0.17 |

A 偏左、M 偏右还溢出格子，直接排出来 A→M 间隙 1.10mm、M→A 是 −0.17mm（重叠）。
程序改成**逐字定位**，把间隙按墨迹宽平均分配（`AMANDA` 五个间隙全是 0.49mm）。
**总宽不变**，所以底座长度和限宽判断都不受影响；预览用同一套坐标，所见即所得。
界面的「字体 / 字重」两个下拉框来自扫描结果，同一个字体族有几个字重就列几个。

实现方式：运行时生成一份临时 fontconfig 配置，通过 `FONTCONFIG_FILE`
传给 OpenSCAD 子进程，因此**不需要把字体安装到系统**，换机器、重装系统都不会失效。

## 已知限制

| 限制 | 说明 | 怎么办 |
|---|---|---|
| **字体许可** | `ELEGANT TYPEWRITER` 声明仅限非商业使用 | 商业销售印章需联系作者买授权；或改用 Apache 2.0 的 Special Elite 系列 |
| **只支持 ASCII** | 字体没有中文字形，中文名会被判「缺字」跳过 | 用拼音/英文名；换带中文字形的字体也可，但要先确认字形完整 |
| **依赖 OpenSCAD 2021.01** | 尺寸模型是在这个版本上标定的（`size` 的 4/3 换算、CGAL 行为） | 换版本后建议先跑一次 `stampgen-cli.exe fit --names 清单.txt` 核对尺寸 |
| **逐名底座宽度** | 装不下的名字底座会变宽，一批印章截面可能 6.6 / 7.2 混排 | 取消勾选「装不下时加宽底座」就退回缩字号；或把默认底座调到最大需求值 |
| **等距只调间隙** | 字母本身的宽窄不变（M 还是比 I 宽），只是空白被拉平 | 这是视觉等距的固有限制；真要等宽字形得换字体 |

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
4. **字形轮廓可能自交**。个别字母（Daziji 系列的小写 `y`）轮廓有重复点或自交，
   单独挤出看不出来，但和底座做 union 时 CGAL 会报 `mesh is not closed`，
   然后**只导出底座、把字母整个丢掉**（退出码还是 0）。程序会检查这个输出，
   自动用 `offset(r=0.001)` 重建多边形再渲染一次，尺寸影响 0.001mm。

`valign` 也改成 `baseline` + 由字体墨迹包围盒算出的垂直偏移，
这样任何字体都能在底座上精确居中（OpenSCAD 自带的 `center` 是按 ascent/descent 算的，
对整体上移过的自定义字体会明显偏上）。

## 命令行

```bat
:: 列出内置字体
python -m stampgen fonts

:: 自检：OpenSCAD 版本、模板、字体是否真的能被解析
python -m stampgen check

:: 只预览尺寸结果，不生成模型
python -m stampgen fit --names names\names1026.txt --size 6 --max-width 60

:: 批量生成
python -m stampgen batch --names names\names1026.txt --size 6 --font Daziji_V5
:: 输出到 <names 同目录>\output_stl1026\<时间戳>\；--outdir 可指定固定目录（不再加时间戳）

:: 打开图形界面
python -m stampgen gui
```

常用覆盖参数：`--font` `--style` `--size` `--spacing` `--case` `--max-width`
`--margin` `--weight` `--min-spacing` `--base-width` `--base-height` `--letter-height` `--workers`。

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
│   ├── metrics.py          # 字宽模型 + 限宽求解
│   ├── template.py         # SCAD 参数渲染
│   ├── openscad.py         # 子进程调用、STL 测量、探针
│   ├── validate.py         # 名字预检 + 大小写 + 参数约束
│   ├── console.py          # 控制台对齐（中文占两列）
│   ├── batch.py            # 批次编排 + manifest
│   ├── cli.py              # 命令行入口
│   └── gui/
│       ├── app.py          # 图形界面
│       └── fontpreview.py  # Pillow 字体预览条
├── legacy/                 # 旧版（当前可用）
│   ├── batch_3Dnames.py    # 旧版批量脚本（含并发渲染）
│   ├── stamp_template.scad # 旧版模板（含 overlap 优化）
│   ├── all_in_one.py       # 更早的合并脚本
│   ├── 提取字体.py          # 字体改造（等宽 + 上移）
│   └── archive/            # 更早的废弃脚本，仅留档
├── scad/stamp_template.scad
├── fonts/                  # 内置字体库（11 个字重面）
│   ├── LICENSE.txt                        # Special Elite（Apache 2.0）
│   └── ELEGANT_TYPEWRITER_LICENSE.txt     # ⚠️ 仅限非商业使用
├── assets/                 # 图标
├── docs/plans/             # 设计文档（每次重构的方案与决策）
├── tests/                  # pytest（118 单测 + 14 端到端）
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
├── CHANGELOG.md            # 更新日志
├── run.bat                 # 新版图形界面
├── run-legacy.bat          # 旧版 exe
└── run-legacy-py.bat       # 旧版源码方式
```

每个批次目录的 `json\manifest.json` 记录当次字体、全部参数、
每个名字的字号/间距/底座宽度/实测宽度，便于事后追溯。

`build/trash/` 是重构与打包时的归档区：历史版本按日期存放，随时可以整个
删掉 `build/` 回收空间。

## 开发

```bat
.venv313\Scripts\python.exe -m pip install -e ".[dev]"
.venv313\Scripts\python.exe -m pytest
```

测试分两层：

- **纯函数层**（118 项）：字宽模型、限宽求解、字符等距、校验、配置迁移、STL 解析，
  不依赖 OpenSCAD，秒级跑完
- **端到端层**（14 项）：真实调用 OpenSCAD 渲染并复核几何（含逐名底座宽度、
  轮廓自交修复、并发一致性），缺 OpenSCAD 时自动跳过，约 3 分钟

```bat
:: 只跑快的
.venv313\Scripts\python.exe -m pytest --ignore=tests/test_e2e.py

:: 打包后的产物回归（8 项：体积、字体枚举、拟合、自检、批量生成、tkdnd、图标）
.venv313\Scripts\python.exe tools\verify_build.py --dist dist\v2.2.6
```

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
