# 参数持久化（配置存在哪）

> 从 `README.md` 拆出（2026-11-06），正文未改。返回 [README](../../README.md) ｜ 相关代码 `src/stampgen/config.py`、`src/stampgen/paths.py`

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
