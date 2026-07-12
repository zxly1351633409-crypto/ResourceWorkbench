@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "RESOURCE_WORKBENCH_HOME=%~dp0.runtime\legacy-demo"
set "PYTHONPATH=%~dp0src"
python -m resource_workbench.gui --path "%~dp0测试" --auto-run

