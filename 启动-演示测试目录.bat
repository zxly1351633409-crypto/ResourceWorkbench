@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
python -m resource_workbench.gui --path "F:\gpt codex huancun\资源管理工具开发\测试" --auto-run

