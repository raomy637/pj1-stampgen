@echo off
rem 用项目虚拟环境直接跑旧版脚本（不走打包的 exe），适合改完代码马上试。
rem OpenSCAD 会自动找到项目根的 OpenSCAD\，路径固定，渲染约 3 秒/个。
cd /d "%~dp0legacy"
start "" "%~dp0.venv313\Scripts\pythonw.exe" "batch_3Dnames.py"
