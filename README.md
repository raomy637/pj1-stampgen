# 名字印章生成器（stampgen）

当前版本 **2.2.8**　|　[更新日志](CHANGELOG.md)　|　[开发入口](AGENTS.md)　|　[设计文档](docs/plans/)　|　[旧版说明](legacy/README.md)

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

`python -m stampgen` 要求包可导入。**首次使用先装一次**（推荐可编辑安装）：

```bat
.venv313\Scripts\python.exe -m pip install -e ".[gui,dev]"
```

不想装也可以，临时把 `src` 加进 `PYTHONPATH`（`run.bat` 内部就是这么做的）：

```bat
set "PYTHONPATH=%CD%\src"
```

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
每个批次目录的 `json\manifest.json` 记录当次字体、全部参数、
每个名字的字号/间距/底座宽度/实测宽度，便于事后追溯。
生成完会自动打开输出文件夹（可在配置区取消勾选）。

## 参数会记住

界面里改过的所有参数都会自动存进 `%APPDATA%\stampgen\stampgen_config.json`
（**不在 exe 旁边**，所有版本共用同一份，换 `dist/v2.2.x/` 不会丢参数），
改完停止输入 1.5 秒即存；删掉该文件恢复出厂默认。
命令行默认不写配置，加 `--save` 才持久化。

> 迁移细节（v2.2.3 及更早写在 exe 同级、首次启动自动搬家一次）：[docs/guides/config.md](docs/guides/config.md)

## 参数说明

| 参数 | 默认 | 说明 |
|---|---|---|
| 底座宽度 | 6.6 mm | 截面 Y 向的**默认**值；个别名字装不下会自动加宽 |
| 装不下时加宽底座 | 勾选 | 勾选=加宽这一枚的底座（字号统一）；取消=缩这一枚的字号（底座统一） |
| 字符等距 | 关闭 | 默认按字体原字距（与 v1.x 一致）；需要绝对均匀间隙时用 `--even-spacing` 打开 |
| 底座高度 | 10 mm | 截面 Z 向 |
| 最长不超过 | 60 mm | 底座长度硬上限；短名字不补齐，超了才压 |
| 左右留白 | 3.5 mm | 底座长 = 文字宽 + 2×留白；v1.x 实测单边 3.5~4mm |
| 字体高度 | 6 mm | 文字沿 Z 的挤出高度 |
| 字号 | 6 mm | 所有名字共用同一字号（超宽或超高时会被压，状态列会标） |
| 字间距 | 1.0 | 1.0 为字体原字距（v1.x 也是原字距）；超宽时先压到 0.85 |
| 几何加粗 | 0 mm | `offset(delta)`；Arial 6mm 笔画已 0.82mm，默认不加粗，超过约 0.3mm 会把 A/O/e 的内孔填死 |
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

> 限宽 / 加宽 / 缩字的完整规则与实测数据：[docs/guides/width-fitting.md](docs/guides/width-fitting.md)

## 已知限制

| 限制 | 说明 | 怎么办 |
|---|---|---|
| **字体许可** | `ELEGANT TYPEWRITER` 声明仅限非商业使用 | 商业销售印章需联系作者买授权；或改用 Apache 2.0 的 Special Elite 系列 |
| **只支持 ASCII** | 字体没有中文字形，中文名会被判「缺字」跳过 | 用拼音/英文名；换带中文字形的字体也可，但要先确认字形完整 |
| **依赖 OpenSCAD 2021.01** | 尺寸模型是在这个版本上标定的（`size` 的 4/3 换算、CGAL 行为） | 换版本后建议先跑一次 `stampgen-cli.exe fit --names 清单.txt` 核对尺寸 |
| **逐名底座宽度** | 装不下的名字底座会变宽，一批印章截面可能 6.6 / 7.2 混排 | 取消勾选「装不下时加宽底座」就退回缩字号；或把默认底座调到最大需求值 |
| **等距只调间隙** | 字母本身的宽窄不变（M 还是比 I 宽），只是空白被拉平 | 这是视觉等距的固有限制；真要等宽字形得换字体 |

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

## 目录速查

```
src/stampgen/   主程序包        tests/    118 单测 + 14 端到端
scad/           OpenSCAD 模板   fonts/    内置字体 11 个字重面
tools/          打包 / 产物回归 / GUI 冒烟 / 图标
docs/           plans（决策）+ guides（细节）+ assets（图与表）
letter_blocks/  字母块子项目（独立，自带 README）
legacy/         旧版脚本与模板（run-legacy.bat 仍可用）
data/ dist/ build/ OpenSCAD/ .venv313/ .cache/   数据与产物，不入库
```

完整目录树与「build/trash 已不存在」等易误解点：[docs/guides/structure.md](docs/guides/structure.md)

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
.venv313\Scripts\python.exe tools\verify_build.py --dist dist\v2.2.8
```

## 延伸阅读

| 想知道 | 读 |
|---|---|
| 改代码前必须遵守什么 | [AGENTS.md](AGENTS.md) |
| 限宽 / 加宽 / 缩字怎么算 | [docs/guides/width-fitting.md](docs/guides/width-fitting.md) |
| 字体、字符等距、许可 | [docs/guides/fonts.md](docs/guides/fonts.md) |
| OpenSCAD 尺寸为什么这么标定 | [docs/guides/how-it-works.md](docs/guides/how-it-works.md) |
| 打包 exe 与产物验证 | [docs/guides/packaging.md](docs/guides/packaging.md) |
| 旧版对照 / 同事还在用旧版 | [docs/guides/legacy-migration.md](docs/guides/legacy-migration.md) |
| 目录结构全貌 | [docs/guides/structure.md](docs/guides/structure.md) |
