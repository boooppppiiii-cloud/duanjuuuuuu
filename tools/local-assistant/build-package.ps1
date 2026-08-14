$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$output = Join-Path $projectRoot "frontend\public\downloads\Jushu-Local-Assistant-Windows-v11.zip"
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("jushu-local-package-" + [guid]::NewGuid().ToString("N"))

try {
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Install-Jushu-Local-Assistant.cmd") -Destination $stage
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install.ps1") -Destination $stage
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.txt") -Destination $stage

    $backendStage = Join-Path $stage "backend"
    New-Item -ItemType Directory -Path $backendStage -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot "backend\app") -Destination $backendStage -Recurse
    Get-ChildItem -LiteralPath (Join-Path $backendStage "app") -Directory -Filter "__pycache__" -Recurse | Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath (Join-Path $backendStage "app") -File -Recurse |
        Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
        Remove-Item -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot "backend\local_workspace.py") -Destination $backendStage
    Copy-Item -LiteralPath (Join-Path $projectRoot "backend\requirements-local-assistant.txt") -Destination $backendStage
    Set-Content -LiteralPath (Join-Path $backendStage "__init__.py") -Value "" -Encoding UTF8
    $backendData = Join-Path $backendStage "data"
    New-Item -ItemType Directory -Path $backendData -Force | Out-Null
    foreach ($name in @("banned_words.txt", "cover_style.json", "moderation.json")) {
        Copy-Item -LiteralPath (Join-Path $projectRoot "backend\data\$name") -Destination $backendData
    }
    Copy-Item -LiteralPath (Join-Path $projectRoot "backend\data\templates") -Destination $backendData -Recurse

    New-Item -ItemType Directory -Path (Split-Path -Parent $output) -Force | Out-Null
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $output -CompressionLevel Optimal -Force
    $archive = Get-Item -LiteralPath $output
    if ($archive.Length -lt 100000) { throw "Generated installer archive is unexpectedly small." }
    Write-Host ("Created {0} ({1:N0} bytes)" -f $archive.FullName, $archive.Length)
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
