# 字体与字符等距

> 从 `README.md` 拆出（2026-11-06），正文未改。返回 [README](../../README.md) ｜ 相关代码 `src/stampgen/fonts.py`

把 `.ttf` / `.otf` 放进 `fonts/` 即可，程序启动时自动扫描。

## 内置字体

| 字体 | 字重 | 类型 | 6mm 字号字高 | 许可 |
|---|---|---|---|---|
| **`Arial`**（默认） | **Regular / Bold / Italic / Bold Italic** | **比例** | **6.17mm** | 系统自带，不随程序分发 |
| `Daziji_V1` ~ `V5` | Regular | 等宽（改造版） | 5.9~6.9mm | 随 Special Elite（Apache 2.0） |
| `Special Elite` | Regular | 等宽 | 5.6mm | Apache 2.0 |
| `Special Elite Mono Final` | Regular | 等宽 | 6.1mm | Apache 2.0 |
| **`ELEGANT TYPEWRITER`** | **Regular / Bold / Light / Italic** | **比例** | **5.3mm** | **⚠️ 仅限非商业使用** |

> **`ELEGANT TYPEWRITER` 的许可限制**：作者 Lukas Krakora 声明
> "free for **non-commercial** use only"。商业用途（例如批量制作并销售印章）
> 需要先联系 `krraaa@yahoo.com` 购买商业授权。
> 许可证原文见 `fonts/ELEGANT_TYPEWRITER_LICENSE.txt`。

**为什么默认是 Arial**：v1.x 的模板把 `font_name` 硬编码成 `"Arial"`，成品笔画
约 0.82mm、边缘干净。Special Elite / Daziji / ELEGANT TYPEWRITER 都是做旧或
打字机体，6mm 字号下笔画只有 0.57~0.65mm，且轮廓自带锯齿，0.4mm 喷嘴打出来
会发虚、笔画断续。Arial 从系统字体目录读取（`SYSTEM_FONT_FILES` 白名单），
**不复制进安装包**，避免 Monotype 的授权问题；系统里没有 Arial 时该字体不出现，
程序自动退回字体库第一个。

它是**比例字体**（每个字母占位不同），原始字距已经由设计师调过，
间隙极差只有 0.17~0.69mm（`Daziji` 系列是 1.27mm），所以视觉上更均匀。

## 字符等距（默认关闭）

开启方式：`--even-spacing`。默认关闭，因为 v1.x 没有这个行为，
Arial 这类比例字体的原生字距已经由设计师调好。

等宽字体（Daziji / Special Elite 系列）才是「等宽」的（每个字母占位一样），但**占位相同不等于视觉间距相同**：

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
