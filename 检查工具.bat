@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
python -m resource_workbench.cli tools
echo.
pause

