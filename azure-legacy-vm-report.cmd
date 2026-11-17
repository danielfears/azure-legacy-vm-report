@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "NoDefaultCurrentDirectoryInExePath=1"
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
if defined PYTHONPATH (
  set "PYTHONPATH=%HERE%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%HERE%"
)
where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
  py -3 -m azure_legacy_vm_report %*
  exit /b %ERRORLEVEL%
)
python -m azure_legacy_vm_report %*
exit /b %ERRORLEVEL%
