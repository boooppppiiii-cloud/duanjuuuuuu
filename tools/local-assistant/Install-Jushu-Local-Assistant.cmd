@echo off
title Jushu Local Assistant Installer
set "INSTALL_SCRIPT=%~dp0install.ps1"

if not exist "%INSTALL_SCRIPT%" (
  echo.
  echo The installer package is incomplete. Download and extract it again.
  echo.
  pause
  exit /b 1
)

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_SCRIPT%"
if errorlevel 1 (
  echo.
  echo Installation did not complete. Keep the failed step and diagnostic log path shown above.
)
echo.
pause
