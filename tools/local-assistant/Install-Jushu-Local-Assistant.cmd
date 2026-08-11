@echo off
title Jushu Local Assistant Installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Installation did not complete. Keep the error above and contact your administrator.
)
echo.
pause
