$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoArchive = "https://github.com/boooppppiiii-cloud/duanjuuuuuu/archive/refs/heads/main.zip"
$installRoot = Join-Path $env:LOCALAPPDATA "Jushu\assistant"
$appRoot = Join-Path $installRoot "app"
$venvRoot = Join-Path $installRoot ".venv"
$settingsFile = Join-Path $installRoot "settings.env"
$launcherFile = Join-Path $installRoot "start-jushu-local-assistant.ps1"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("jushu-assistant-" + [guid]::NewGuid().ToString("N"))
$logFile = Join-Path ([System.IO.Path]::GetTempPath()) "Jushu-Local-Assistant-install.log"
$currentStep = "Starting installer"
$installFailure = $null

function Write-InstallLog([string]$text) {
    try {
        $line = "{0} {1}{2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $text, [Environment]::NewLine
        [System.IO.File]::AppendAllText($logFile, $line, [System.Text.Encoding]::UTF8)
    } catch { }
}

function Write-Step([string]$text) {
    $script:currentStep = $text
    Write-InstallLog ("STEP: " + $text)
    Write-Host ""
    Write-Host ("[Jushu] " + $text) -ForegroundColor Green
}

function Resolve-ExecutablePath([object]$value) {
    if ($null -eq $value) { return $null }
    $candidate = [string]$value
    if ([string]::IsNullOrWhiteSpace($candidate)) { return $null }
    try {
        $item = Get-Item -LiteralPath $candidate -ErrorAction Stop
        if ($item.PSIsContainer) { return $null }
        return $item.FullName
    } catch {
        return $null
    }
}

function Find-Python {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe")
    )
    $commands = @(Get-Command python.exe -All -ErrorAction SilentlyContinue)
    foreach ($command in $commands) {
        $commandPath = Resolve-ExecutablePath $command.Source
        if ($commandPath) { $candidates += $commandPath }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        $candidatePath = Resolve-ExecutablePath $candidate
        if (-not $candidatePath) { continue }
        try {
            $supported = & $candidatePath -c "import sys; print('yes' if (3, 11) <= sys.version_info[:2] < (3, 13) else 'no')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $supported -eq "yes") { return $candidatePath }
        } catch { }
    }
    return $null
}

function Find-WinGetBinary([string]$name) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) {
        $commandPath = Resolve-ExecutablePath $command.Source
        if ($commandPath) { return $commandPath }
    }
    $packagesRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $packagesRoot) {
        return Get-ChildItem -LiteralPath $packagesRoot -Recurse -Filter $name -File -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
    }
    return $null
}

try {
    try { Remove-Item -LiteralPath $logFile -Force -ErrorAction SilentlyContinue } catch { }
    Write-InstallLog "Installer started"
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "The current Windows user directory is unavailable."
    }

    Write-Step "Checking the Python runtime"
    $python = Find-Python
    if (-not $python) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        $wingetPath = if ($winget) { Resolve-ExecutablePath $winget.Source } else { $null }
        if (-not $wingetPath) {
            throw "Python 3.11/3.12 is missing and winget is unavailable. Install Python 3.12 from https://www.python.org/downloads/windows/ and run this installer again."
        }
        Write-Host "Installing Python 3.12 for the current Windows user..."
        & $wingetPath install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Python installation failed with exit code $LASTEXITCODE." }
        $python = Find-Python
        if (-not $python) { throw "Python was installed but is not visible yet. Run this installer again." }
    }

    Write-Step "Downloading the latest Jushu Local Assistant"
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    $archiveFile = Join-Path $tempRoot "source.zip"
    Invoke-WebRequest -Uri $repoArchive -OutFile $archiveFile -UseBasicParsing
    Expand-Archive -LiteralPath $archiveFile -DestinationPath $tempRoot -Force
    $sourceRoot = Get-ChildItem -LiteralPath $tempRoot -Directory | Where-Object { $_.Name -like "duanjuuuuuu-*" } | Select-Object -First 1
    if (-not $sourceRoot) { throw "The downloaded archive has an unexpected structure. Try again later." }

    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("python.exe", "pythonw.exe") -and $_.CommandLine -match "backend\.local_workspace" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $appRoot) { Remove-Item -LiteralPath $appRoot -Recurse -Force }
    New-Item -ItemType Directory -Path $appRoot -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceRoot.FullName "backend") -Destination $appRoot -Recurse -Force

    Write-Step "Installing local video components (first install can take several minutes)"
    $venvPython = Join-Path $venvRoot "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $python -m venv $venvRoot
        if ($LASTEXITCODE -ne 0) { throw "Creating the local Python environment failed." }
    }
    & $venvPython -m pip install --disable-pip-version-check --upgrade pip wheel
    if ($LASTEXITCODE -ne 0) { throw "Updating the package installer failed." }
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $appRoot "backend\requirements-local-assistant.txt")
    if ($LASTEXITCODE -ne 0) { throw "Installing Local Assistant dependencies failed." }

    Write-Step "Checking FFmpeg video tools"
    $ffmpeg = Find-WinGetBinary "ffmpeg.exe"
    $ffprobe = Find-WinGetBinary "ffprobe.exe"
    if (-not $ffmpeg -or -not $ffprobe) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        $wingetPath = if ($winget) { Resolve-ExecutablePath $winget.Source } else { $null }
        if (-not $wingetPath) { throw "FFmpeg is missing and winget is unavailable." }
        Write-Host "Installing FFmpeg..."
        & $wingetPath install --id Gyan.FFmpeg --exact --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "FFmpeg installation failed with exit code $LASTEXITCODE." }
        $ffmpeg = Find-WinGetBinary "ffmpeg.exe"
        $ffprobe = Find-WinGetBinary "ffprobe.exe"
        if (-not $ffmpeg -or -not $ffprobe) { throw "FFmpeg was installed but is not visible yet. Run this installer again." }
    }

    if (-not (Test-Path -LiteralPath $settingsFile)) {
        $ffmpegValue = $ffmpeg.Replace("\", "/")
        $ffprobeValue = $ffprobe.Replace("\", "/")
        @"
FFMPEG_BINARY=$ffmpegValue
FFPROBE_BINARY=$ffprobeValue
GEMINI_API_KEY=
QWEN_API_KEY=
"@ | Set-Content -LiteralPath $settingsFile -Encoding UTF8
    }

    @'
$ErrorActionPreference = "Stop"
$installRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$appRoot = Join-Path $installRoot "app"
$settingsFile = Join-Path $installRoot "settings.env"
$python = Join-Path $installRoot ".venv\Scripts\python.exe"

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:17862/api/local/health" -TimeoutSec 2 | Out-Null
    exit 0
} catch { }

if (Test-Path -LiteralPath $settingsFile) {
    foreach ($line in Get-Content -LiteralPath $settingsFile -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith("#")) { continue }
        $parts = $line.Split("=", 2)
        if ($parts.Count -eq 2) { [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process") }
    }
}
Set-Location -LiteralPath $appRoot
& $python -m backend.local_workspace
'@ | Set-Content -LiteralPath $launcherFile -Encoding UTF8

    Write-Step "Creating startup shortcuts"
    $shell = New-Object -ComObject WScript.Shell
    $shortcutTargets = @()
    $desktopRoot = [Environment]::GetFolderPath("Desktop")
    if (-not [string]::IsNullOrWhiteSpace($desktopRoot)) {
        $shortcutTargets += (Join-Path $desktopRoot "Jushu Local Assistant.lnk")
    }
    if (-not [string]::IsNullOrWhiteSpace($env:APPDATA)) {
        $startupRoot = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
        New-Item -ItemType Directory -Path $startupRoot -Force -ErrorAction SilentlyContinue | Out-Null
        $shortcutTargets += (Join-Path $startupRoot "Jushu Local Assistant.lnk")
    }
    foreach ($shortcutPath in $shortcutTargets) {
        try {
            $shortcut = $shell.CreateShortcut($shortcutPath)
            $shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
            $shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcherFile`""
            $shortcut.WorkingDirectory = $installRoot
            $shortcut.Description = "Jushu Local Assistant"
            $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,21"
            $shortcut.Save()
            Write-InstallLog ("Shortcut created: " + $shortcutPath)
        } catch {
            Write-Warning ("Could not create shortcut: " + $shortcutPath)
            Write-InstallLog ("Shortcut warning: " + $_.Exception.Message)
        }
    }

    Write-Step "Starting and checking the Local Assistant"
    Start-Process powershell.exe -ArgumentList "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcherFile`"" -WorkingDirectory $installRoot -WindowStyle Hidden
    $ready = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:17862/api/local/health" -TimeoutSec 2
            if ($health.status -eq "ok") { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { throw "The Local Assistant was installed but did not start in time. Open the Jushu Local Assistant desktop shortcut and retry." }

    Write-Host ""
    Write-Host "Installation completed. Return to the Jushu web app and run the check again." -ForegroundColor Green
    Write-Host "Source videos remain on this computer and are not uploaded by this installer."
    Write-InstallLog "Installation completed"
} catch {
    $installFailure = $_
    Write-InstallLog ("FAILED at " + $currentStep + ": " + $_.Exception.Message)
    Write-InstallLog ("Position: " + $_.InvocationInfo.PositionMessage)
    Write-InstallLog ("Stack: " + $_.ScriptStackTrace)
    Write-Host ""
    Write-Host "Installation failed." -ForegroundColor Red
    Write-Host ("Failed step: " + $currentStep) -ForegroundColor Yellow
    Write-Host ("Reason: " + $_.Exception.Message) -ForegroundColor Red
    if ($_.InvocationInfo.ScriptLineNumber) {
        Write-Host ("Installer line: " + $_.InvocationInfo.ScriptLineNumber) -ForegroundColor DarkGray
    }
    Write-Host ("Diagnostic log: " + $logFile) -ForegroundColor Yellow
} finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}

if ($installFailure) { exit 1 }
