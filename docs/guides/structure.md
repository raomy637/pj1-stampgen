# 目录结构

> 从 `README.md` 拆出（2026-11-06），并补登记了 `letter_blocks/`、`.cache/`、`docs/guides/`、`docs/assets/`。
> 返回 [README](../../README.md)

按「代码 / 数据 / 产物 / 环境」四层分开，只有前两层进版本库。

```
PJ1/
├── AGENTS.md               # 入口（路由），改代码前先读
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
├── docs/
│   ├── plans/              # 设计文档（每次重构的方案与决策，文首有「状态」）
│   ├── guides/             # 细节文档（限宽 / 字体 / 原理 / 打包 / 迁移 / 配置 / 运维 / 本文件）
│   └── assets/             # 文档配图与参数表（字体对比、字粒-字距表）
├── tests/                  # pytest（118 单测 + 14 端到端）
├── tools/
│   ├── make_icon.py        # 生成 assets/stampgen.ico
│   ├── build.py            # 新版 PyInstaller 打包
│   ├── build_legacy.py     # 旧版 PyInstaller 打包
│   ├── verify_build.py     # 跑 exe 做功能回归
│   ├── gui_smoke.py        # GUI 冒烟测试 + 截图
│   ├── entry_gui.py        # 打包入口（界面，带崩溃兜底）
│   └── entry_cli.py        # 打包入口（命令行）
├── letter_blocks/          # 字母块子项目（独立：自带 README / scad / scripts / out）
├── data/                   # 业务数据（不入库，约 350MB）
│   ├── names/              # 名字清单
│   ├── output_stl/         # 生成结果（按 output_stl<批次号>\<时间戳>\ 分层，现 71 个批次）
│   ├── new_output_stl/     # 换字体试做的结果
│   └── 订单/               # 订单原始文件
├── build/                  # PyInstaller 中间产物（spec / tmp / work / version_*.txt，不入库，可整删）
├── dist/                   # 成品：vX.Y.Z/ + legacy/，不入库，只保留当前版本
├── OpenSCAD/               # 便携 OpenSCAD（不入库）
├── .venv313/               # 唯一的虚拟环境（不入库）
├── .cache/                 # 一次性调试脚本与实测截图（不入库，可随时删）
├── backup_docs_20261106/   # 2026-11-06 文档治理前的一次性备份（已 gitignore，确认后可删）
├── CHANGELOG.md            # 更新日志
├── README.md               # 索引：快速开始 / 参数 / 限制 / 开发
├── run.bat                 # 新版图形界面
├── run-legacy.bat          # 旧版 exe
└── run-legacy-py.bat       # 旧版源码方式
```

项目外还有一个归档区（同盘，不进版本库）：

```
D:\HA1\archive\
├── output_stl_2026Q1\      # 2026 年 1~3 月的 78 个批次（需要时移回 data\output_stl\ 即可）
└── releases\               # 历史发布包
```

## 三个容易误解的点

- `build/` 只有 PyInstaller 的中间产物，可以整个删掉回收空间。
  早期重构的归档区 `build/trash/` **已不存在**，历史慢包由 `dist/legacy/` 取代。
- `dist/` 里每个版本目录各带一份便携 OpenSCAD（约 48MB），
  只保留当前版本即可，旧版本目录删掉不影响已装好的程序。
- `data/output_stl/` 只放**最近约半年**的批次，更早的移到 `D:\HA1\archive\`。
  清理规则与恢复方式见 `docs/guides/ops.md`。
