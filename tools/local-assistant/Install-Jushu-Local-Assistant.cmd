@echo off
title Jushu Local Assistant Installer
set "BOOTSTRAP_ROOT=%TEMP%\Jushu-Local-Assistant-Installer"
set "BOOTSTRAP_ZIP=%TEMP%\Jushu-Local-Assistant-Windows-v2.zip"
set "INSTALL_SCRIPT=%BOOTSTRAP_ROOT%\install.ps1"

echo Preparing the latest installer...
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $zip=Join-Path $env:TEMP 'Jushu-Local-Assistant-Windows-v2.zip'; $root=Join-Path $env:TEMP 'Jushu-Local-Assistant-Installer'; Invoke-WebRequest -UseBasicParsing -Uri 'https://app.duanju.chat/downloads/Jushu-Local-Assistant-Windows-v2.zip' -OutFile $zip; if(Test-Path -LiteralPath $root){Remove-Item -LiteralPath $root -Recurse -Force}; Expand-Archive -LiteralPath $zip -DestinationPath $root -Force"
if errorlevel 1 (
  echo.
  echo Could not prepare the installer. Check the network connection and try again.
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
