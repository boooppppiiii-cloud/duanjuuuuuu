@echo off
title Jushu Local Assistant Installer
if not exist "%~dp0install.ps1" (
  echo The installer files are incomplete.
  echo Extract the whole ZIP file first, then run this CMD file from the extracted folder.
  echo.
  pause
  exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Installation did not complete. Keep the failed step and diagnostic log path shown above.
)
echo.
pause
