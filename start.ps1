$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
@('dramas','bgm','assets','clips','posts','packages','uploads') | ForEach-Object { New-Item -ItemType Directory -Force -Path (Join-Path 'media' $_) | Out-Null }
New-Item -ItemType Directory -Force -Path 'logs','backend/data' | Out-Null
& .\.venv\Scripts\python.exe scripts\doctor.py
if ($LASTEXITCODE -ne 0) { Write-Host '环境体检未通过，请按上方“怎么修”处理后重试。' -ForegroundColor Red; exit 1 }
docker compose up -d --build
$frontendPort = if ($env:FRONTEND_BIND_PORT) { $env:FRONTEND_BIND_PORT } else { '5174' }
Write-Host "服务已启动。打开 http://127.0.0.1:$frontendPort 开始使用" -ForegroundColor Green
