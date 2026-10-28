# 单模式重构与界面重做

日期：2026-10-28
状态：待确认

## 一、背景

v2.1.0 提供了两种宽度模式（定字号算宽度 / 定宽度算字号），实际使用后确认只需要一种：

> 事实上不应该有2种模式，应该只有1种模式，我们只需要设置最宽不能超过多少就可以了。
> 例如最宽不能超过60mm，假如用户只需要做3个字母的印章，其实完全不用非得挤满60mm。

同时提出一批界面改进：大小写转换、粘贴输入、字体预览、加粗预览、参数分组、配置区两列、
生成后自动打开文件夹，以及删掉三个冗余按钮。

## 二、核心变更：从「定宽」改为「限宽」

### 旧逻辑

两种模式二选一，`width_mode` 决定求解方向：

- `fixed`：给定 `target_width_mm`，反解字号与间距，成品一律同宽
- `auto`：给定字号与间距，算出底座长度，短名字不挤满

### 新逻辑

只有一种模式：**字号固定，底座长度按名字算，但不超过上限**。

```
1. size = font_size_mm
   若字高（size × 字高比 × 4/3）> 底座宽度 → 压到上限并提示

2. width = predict_width(text, size, spacing)
   base_len = width + 2 × margin + 2 × weight_offset

3. 若 base_len > max_width_mm：
   a. 先把间距压到 min_spacing，重算 base_len
      若已满足 → 记录「间距压缩到 X」
   b. 仍不满足 → 按比例缩字号（间距保持 min_spacing）
      记录「字号缩到 X、间距压到 Y」
   c. 若缩到 hard_min_size_mm 仍超宽 → 状态 too_long，跳过并给出建议
```

两个约束的性质不同：

- `max_width_mm` 是**硬上限**，超过就必须压
- 短名字**不补齐**，`base_len` 算多少就是多少

### 为什么先压间距再缩字号

字号是印章的视觉主体，间距是排版微调。间距从 1.0 压到 0.85 大约能省 15% 宽度，
大部分长名字只靠压间距就能塞进上限，字号得以保持不变。只有极长的名字才需要缩字号。

用户确认：**压缩后必须在界面上提醒**，不能悄悄改。

## 三、数据模型

`StampSpec` 重写：

```python
@dataclass
class StampSpec:
    # 印章几何
    base_width_mm: float = 6.0
    base_height_mm: float = 10.0
    letter_height_mm: float = 6.0
    max_width_mm: float = 60.0        # 新增：底座最长
    margin_mm: float = 1.5

    # 字体
    font_size_mm: float = 6.0         # 原 auto_size_mm
    letter_spacing: float = 1.0       # 原 auto_spacing
    min_spacing: float = 0.85         # 保留：压缩下限
    weight_offset_mm: float = 0.0
    case_mode: str = "keep"           # 新增：keep/upper/capitalize/lower

    # 精度与保护
    edge_mm: float = 0.2
    hard_min_size_mm: float = 2.5
    curve_fa: float = 0.0
    curve_fs: float = 0.0
    max_chars: int = 16
```

删除：`width_mode`、`target_width_mm`、`auto_size_mm`、`auto_spacing`、
`min_size_mm`、`max_size_mm`、`default_spacing`、`max_spacing`、`available_mm()`

保留 `min_spacing`，作为超宽时的压缩下限。

### 配置迁移

旧配置里是 `auto_size_mm` / `auto_spacing`，新字段名不同。读取时做一次映射：

```python
if "font_size_mm" not in spec_data and "auto_size_mm" in spec_data:
    spec_data["font_size_mm"] = spec_data["auto_size_mm"]
if "letter_spacing" not in spec_data and "auto_spacing" in spec_data:
    spec_data["letter_spacing"] = spec_data["auto_spacing"]
```

旧配置的 `target_width_mm` 忽略；若它比 60 大，把 `max_width_mm` 设成它，避免老用户
突然发现成品变短。

## 四、界面

### 布局

分五个区块，从上到下：

1. **印章几何**：底座宽度、底座高度、最长不超过、左右留白、字体高度
2. **字体**：字体、字号、字间距、几何加粗、大小写 + 实时字体预览条
3. **配置（自动探测）** 左 / **名字清单** 右，两列并排
   - 左：OpenSCAD 路径、模板 scad、输出目录、「完成后自动打开文件夹」勾选
   - 右：选择 txt 按钮、粘贴框（左侧带行号列）、「共 N 个名字」统计
4. **结果预览表**：序号、名字、字符、字号 mm、间距、底座长 mm、状态
5. **底部操作栏**：开始生成、取消、进度条、状态文字

#### 结果表的列设计

| 列 | 宽度 | 说明 |
|---|---|---|
| 序号 | 40 | 与名字清单的行号一致 |
| 名字 | 自适应 | 转换大小写之后的名字 |
| 字符 | 45 | 字符数 |
| 字号 mm | 60 | 压缩后会小于设定值，一眼能看出被压 |
| 间距 | 55 | 1.00 是原字距，小于 1 说明被压过 |
| 底座长 mm | 75 | 成品总宽 |
| 状态 | 70 | **只放短标签，不放长句** |

所有长度字段的表头都带 `mm` 单位。

#### 状态列为什么只放短标签

名字越长、压缩越狠，说明文字就越长（如「字号缩到 4.82、间距压到 0.85 以适配 60mm」），
固定列宽必然被切掉。所以状态列只放 4 个短标签，详情走鼠标悬停：

| 标签 | 触发条件 | 颜色 |
|---|---|---|
| 正常 | 没触发任何压缩 | 绿 |
| 已压缩 | 只压了间距 | 橙 |
| 已缩字 | 间距压到下限后仍超宽，又缩了字号 | 橙 |
| 超长 | 缩到 `hard_min_size_mm` 仍超宽 | 红 |

具体压了多少，看「字号」「间距」两列即可（设 6.0 显示 4.82 就说明被压了）。
悬停某行时用 `Toplevel` 弹一个无边框提示，显示完整原因。

这样状态列固定 5 个汉字宽，无论名字多长都不会截断。

### 删除的控件

| 控件 | 原因 |
|---|---|
| 预览拟合 | 参数一改就自动刷新（250ms 防抖），按钮多余 |
| 清空日志 | 用户不需要 |
| 自检 | 它检查的 OpenSCAD 版本、模板路径、字体解析，生成时本来就会做，失败也会报错 |
| 宽度模式单选 | 只剩一种模式 |
| 目标宽度 / 字号范围 | 被「最长不超过」和「字号」取代 |
| 打开输出目录按钮 | 改成生成完自动打开，带勾选可关 |

### 字体预览

选字体后立刻在预览条里渲染。技术方案（用户选「精确」）：

- `PIL.ImageFont.truetype(path, px)` 直接加载 `fonts/` 里的 ttf，不需要安装到系统
- 加粗用 `stroke_width`，值 = `weight_offset_mm × scale`，与 OpenSCAD 的 `offset(delta)`
  效果基本一致
- `scale = 4 px/mm`，6mm 字号 → 24px
- 转成 `ImageTk.PhotoImage` 显示在 Label 上
- 预览文字固定为 `ABCDE abcde 0123`，换字体时对比最明显；大小写切换时同步变化

### 行号列

左侧一个窄 `Text`（宽 3 字符、禁用、灰底），右侧主 `Text`。三个事件触发重绘：

- 主 Text 的 `yscrollcommand` 里同步左侧 yview
- `<KeyRelease>`、`<<Paste>>`、`<MouseWheel>` 后重算行数

行号只画到可见区域，避免上千行时卡顿。

### 大小写

`case_mode` 在读入名字后立即应用，后续校验、预览、文件名、STL 全部用转换后的名字。

| 值 | 效果 | 示例 |
|---|---|---|
| keep | 原样 | `tess` → `tess` |
| upper | 全大写 | `tess` → `TESS` |
| capitalize | 每词首字母大写 | `mary jane` → `Mary Jane` |
| lower | 全小写 | `TESS` → `tess` |

### 名字来源

两种方式并存，粘贴优先：

- 点「选择 txt 文件」→ 读入并填进粘贴框，之后仍可编辑
- 直接往粘贴框里粘贴 → 实时统计数量

读取时统一走 `normalize_names`（去空行、去首尾空白）。

### 参数校验与提示带

参数之间不是独立的，有几条硬约束。在参数区底部加一条实时提示带，参数一变就重新校验。

| 检查项 | 条件 | 级别 | 程序行为 |
|---|---|---|---|
| 留白挤掉全部宽度 | `2 × margin >= max_width` | 红 | 拒绝生成 |
| 加粗过量 | `weight_offset > 0.3` | 红 | 拒绝生成 |
| 字高超出底座宽 | `cap_height(size) + 2 × weight > base_width` | 橙 | 自动压字号，提示建议底座宽度 |
| 最长上限过小 | 6mm 字号下 3 个字符都放不下 | 橙 | 生成时会大量缩字，提示加大上限 |
| 字体高度过高 | `letter_height > 1.5 × base_height` | 橙 | 不阻止，提示印章会很高 |

字高按字体实际字高比计算（`cap_ratio × size × 4/3`），不同字体差别明显：

- `Daziji_V1` 字高比 0.735 → 6mm 字号字高 5.88mm，底座 6mm 刚好装下
- `Daziji_V5` 字高比 0.803 → 6mm 字号字高 6.43mm，底座 6mm 装不下

所以提示文案必须带具体数字和建议值，不能只说"参数不合理"：

> 当前字体 6mm 字号字高 6.43mm，超过底座宽度 6mm，会自动压到 5.59mm。
> 建议底座宽度 ≥ 6.5mm。　[采用]

提示带最多显示 3 条，按严重程度排序。

### 已知 bug 要一并修掉

`metrics.fit_auto` 里的 `hard_limit` 只算了底座宽度，没减掉 `2 × weight_offset_mm`：

```python
hard_limit = spec.base_width_mm / (cap_ratio * OPENSCAD_SIZE_SCALE)   # 漏了加粗
```

加粗 0.2mm 时字高会多出 0.4mm，可能顶出底座。`size_limit_from_geometry()` 里是对的，
`fit_auto` 抄漏了。重构时统一走一个函数。

### 生成完成

结束后若勾选了「完成后自动打开文件夹」，用 `os.startfile(输出目录)` 打开。

## 五、实现清单

| 文件 | 改动 |
|---|---|
| `config.py` | StampSpec 重写、配置迁移、case_mode 校验 |
| `metrics.py` | 删 `fit_auto`，`fit` 改为限宽逻辑；新增 `solve_size_for_max` |
| `template.py` | `base_len` 直接用 `fit.base_len_mm`（已经是这样） |
| `validate.py` | 新增 `apply_case()` 与 `check_spec()`（参数约束校验） |
| `batch.py` | 删模式分派；日志显示压缩情况 |
| `cli.py` | 删 `--mode/--width/--min-size/--max-size`，加 `--max-width/--size/--spacing/--case` |
| `gui/app.py` | 整体重写布局；新增字体预览、行号框、大小写下拉；删三个按钮 |
| `tools/build.py` | 移除 `--exclude-module PIL`；QUICKSTART 更新 |
| `tests/` | 重写受影响的用例，新增限宽压缩、大小写、迁移测试 |

## 六、测试计划

单元层（不依赖 OpenSCAD）：

- 限宽：短名字不补齐、刚好等于上限、超宽只压间距、超宽压间距+缩字号、极长判 too_long
- 大小写：四种模式的转换结果
- 参数校验：留白挤满宽度、加粗过量、字高超出底座、最长上限过小、字体高度过高
- 加粗计入字高：`fit_auto` 的 `hard_limit` 必须减去 `2 × weight_offset`
- 配置：迁移映射、非法 case_mode 回退、max_width 边界
- 字宽模型：原有 12 项回归

端到端（真实渲染）：

- 一批混合长短的名字，确认每个 STL 总宽 = 预测底座长，且都不超过 max_width
- 生成后 manifest 里记录的是压缩后的字号/间距
- 并发与串行结果一致

界面层：

- GUI 冒烟 + 截图，确认五个区块都在、字体预览条有内容
- 粘贴 → 行号出现 → 统计更新
- 状态列在最长名字（如 16 字符）下仍完整显示，不出现省略号

## 七、风险

| 风险 | 应对 |
|---|---|
| Pillow 让安装包增大 ~8MB | 可接受；exe 从 15MB 到约 23MB |
| 行号列与 Text 滚动不同步 | 用 `yscrollcommand` 回调统一驱动；只画可见行 |
| 删掉定宽模式后，老用户找不到"统一宽度" | 文档说明：用「最长不超过」设成目标值，短名字仍会更短；确有需要再加回 |
| 旧配置字段名变化导致参数丢失 | 加迁移映射，有测试覆盖 |
| 字体预览与实际 OpenSCAD 渲染有细微差异 | 预览只用于看字体观感，最终尺寸以实测探针为准，界面注明 |

## 八、不做的事

- 不加回定宽模式
- 不做印章三维预览（成本高，收益低）
- 不做名字清单的表格编辑（粘贴 + txt 已覆盖）
