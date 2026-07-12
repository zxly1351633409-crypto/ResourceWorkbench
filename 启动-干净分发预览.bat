@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Use a new temporary profile on every launch. Never touches personal data.
set "RESOURCE_WORKBENCH_HOME=%TEMP%\ResourceWorkbench-CleanPreview-%RANDOM%-%RANDOM%"
mkdir "%RESOURCE_WORKBENCH_HOME%" >nul 2>nul

if exist "%~dp0dist\ResourceWorkbench\ResourceWorkbench.exe" (
  start "" "%~dp0dist\ResourceWorkbench\ResourceWorkbench.exe"
  exit /b 0
)

set "PYTHONPATH=%~dp0src"
set "PYTHONW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"
if exist "%PYTHONW%" (
  start "" "%PYTHONW%" -m resource_workbench.qt_app
) else (
  start "" pythonw -m resource_workbench.qt_app
)
