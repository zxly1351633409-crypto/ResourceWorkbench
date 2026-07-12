@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "RESOURCE_WORKBENCH_HOME=%~dp0.runtime\formal-demo"
set "PYTHONPATH=%~dp0src"
set "PYTHONW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"
if exist "%PYTHONW%" (
  start "" "%PYTHONW%" -m resource_workbench.qt_app --auto-run
) else (
  start "" python -m resource_workbench.qt_app --auto-run
)
