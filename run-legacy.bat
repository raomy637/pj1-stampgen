@echo off
rem 启动旧版界面（PJ1Program）。
rem 打包成 onedir 后 exe 依赖同目录的 _internal\ 和 OpenSCAD\，
rem 所以必须先 cd 到 exe 所在目录再启动，否则会找不到运行时。
cd /d "%~dp0dist\legacy\PJ1Program"
start "" "PJ1Program.exe"
