@echo off
set "SCRIPT_DIR=%~dp0"
if "%~1"=="" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%darkweb_collector\scripts\start_all_services_windows.ps1" start
) else (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%darkweb_collector\scripts\start_all_services_windows.ps1" %*
)
