@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Source development profile, isolated from personal and public builds.
set "RESOURCE_WORKBENCH_HOME=%~dp0.runtime\development"
set "PYTHONPATH=%~dp0src"
set "PYTHONW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"

if exist "%PYTHONW%" (
  start "" "%PYTHONW%" -m resource_workbench.qt_app
) else (
  start "" pythonw -m resource_workbench.qt_app
)
