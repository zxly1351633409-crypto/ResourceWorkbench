@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "RESOURCE_WORKBENCH_HOME=%~dp0.runtime\cli"
set "PYTHONPATH=%~dp0src"
echo 请输入要分析的资源文件夹或压缩包路径：
set /p TARGET=路径：
if "%TARGET%"=="" (
  echo 没有输入路径，已退出。
  pause
  exit /b 1
)
python -m resource_workbench.cli analyze "%TARGET%"
echo.
pause

