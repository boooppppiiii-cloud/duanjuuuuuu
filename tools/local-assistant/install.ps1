$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$pythonInstallerUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
$ffmpegArchiveUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$installRoot = if ($env:JUSHU_ASSISTANT_INSTALL_ROOT) { $env:JUSHU_ASSISTANT_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "Jushu\assistant" }
$appRoot = Join-Path $installRoot "app"
$venvRoot = Join-Path $installRoot ".venv"
$runtimeRoot = Join-Path $installRoot "runtime"
$pythonRoot = Join-Path $runtimeRoot "python"
$ffmpegRoot = Join-Path $runtimeRoot "ffmpeg"
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

function Invoke-VerifiedDownload([string]$uri, [string]$destination, [string]$label, [long]$minimumBytes) {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Remove-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue
            Write-Host ("Downloading {0} ({1}/3)..." -f $label, $attempt)
            Invoke-WebRequest -Uri $uri -OutFile $destination -UseBasicParsing -TimeoutSec 900
            $download = Get-Item -LiteralPath $destination -ErrorAction Stop
            if ($download.Length -lt $minimumBytes) { throw "The downloaded file is incomplete." }
            return
        } catch {
            Write-InstallLog ("Download failed for " + $label + ": " + $_.Exception.Message)
            if ($attempt -eq 3) { throw "Could not download $label after three attempts. Check the network connection and retry." }
            Start-Sleep -Seconds (2 * $attempt)
        }
    }
}

try {
    try { Remove-Item -LiteralPath $logFile -Force -ErrorAction SilentlyContinue } catch { }
    Write-InstallLog "Installer started"
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "The current Windows user directory is unavailable."
    }

    $currentSessionId = (Get-Process -Id $PID).SessionId
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $interactiveShell = Get-CimInstance Win32_Process -Filter "Name = 'explorer.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.SessionId -eq $currentSessionId } | Select-Object -First 1
    if ($interactiveShell) {
        $shellOwner = Invoke-CimMethod -InputObject $interactiveShell -MethodName GetOwner -ErrorAction SilentlyContinue
        $shellIdentity = if ($shellOwner -and $shellOwner.User) { ("{0}\{1}" -f $shellOwner.Domain, $shellOwner.User).TrimStart('\') } else { "" }
        if ($shellIdentity -and -not $currentIdentity.Equals($shellIdentity, [StringComparison]::OrdinalIgnoreCase)) {
            throw "This installer is running as $currentIdentity, but the desktop belongs to $shellIdentity. Close it and double-click the installer normally from the user who runs the Jushu web app; do not use a different administrator account."
        }
    }

    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

    Write-Step "Preparing the private Python runtime"
    $python = Join-Path $pythonRoot "python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        $pythonInstaller = Join-Path $tempRoot "python-3.12.10-amd64.exe"
        Invoke-VerifiedDownload $pythonInstallerUrl $pythonInstaller "the private Python runtime" 20000000
        New-Item -ItemType Directory -Path $pythonRoot -Force | Out-Null
        $pythonInstall = Start-Process -FilePath $pythonInstaller -ArgumentList @(
            "/quiet", "InstallAllUsers=0", "TargetDir=`"$pythonRoot`"", "Include_pip=1", "Include_launcher=0",
            "AssociateFiles=0", "Shortcuts=0", "PrependPath=0", "Include_test=0", "Include_doc=0", "Include_tcltk=0"
        ) -Wait -PassThru -WindowStyle Hidden
        if ($pythonInstall.ExitCode -ne 0) { throw "Installing the private Python runtime failed with exit code $($pythonInstall.ExitCode)." }
    }
    if (-not (Test-Path -LiteralPath $python)) { throw "The private Python runtime was not installed correctly." }
    $pythonVersion = & $python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
    if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne "3.12") {
        throw "The private Python runtime is invalid. Delete $pythonRoot and run the installer again."
    }

    Write-Step "Installing the bundled Jushu Local Assistant"
    $sourceBackend = Join-Path $PSScriptRoot "backend"
    if (-not (Test-Path -LiteralPath (Join-Path $sourceBackend "local_workspace.py"))) {
        throw "The installer package is incomplete. Download the latest package from the Jushu web app and extract it again."
    }

    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    try {
        $existingHealth = Invoke-RestMethod -Uri "http://127.0.0.1:17862/api/local/health" -TimeoutSec 2
        if ($existingHealth.status -eq "ok" -and $existingHealth.windows_user -and -not $existingHealth.windows_user.Equals($env:USERNAME, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Port 17862 is occupied by a Local Assistant running as Windows user '$($existingHealth.windows_user)'. Sign in as that user and exit the old assistant, or restart Windows and run this installer from the current user before opening the old shortcut."
        }
    } catch {
        if ($_.Exception.Message -like "Port 17862 is occupied*") { throw }
    }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -in @("python.exe", "pythonw.exe") -and
            $_.CommandLine -match "backend\.local_workspace" -and
            ($_.SessionId -eq $currentSessionId -or ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($installRoot, [StringComparison]::OrdinalIgnoreCase)))
        } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $portReleased = -not (Get-NetTCPConnection -LocalPort 17862 -State Listen -ErrorAction SilentlyContinue)
        if ($portReleased) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $portReleased) {
        throw "Port 17862 is still in use. Close the old Jushu Local Assistant or restart Windows, then run this installer again from the current Windows user."
    }
    if (Test-Path -LiteralPath $appRoot) { Remove-Item -LiteralPath $appRoot -Recurse -Force }
    New-Item -ItemType Directory -Path (Join-Path $appRoot "backend") -Force | Out-Null
    Copy-Item -Path (Join-Path $sourceBackend "*") -Destination (Join-Path $appRoot "backend") -Recurse -Force

    Write-Step "Installing local video components (first install can take several minutes)"
    $venvPython = Join-Path $venvRoot "Scripts\python.exe"
    $venvReady = $false
    if (Test-Path -LiteralPath $venvPython) {
        try {
            $venvBase = & $venvPython -c "import sys; print(sys.base_prefix)" 2>$null
            $venvReady = $LASTEXITCODE -eq 0 -and ([System.IO.Path]::GetFullPath($venvBase).TrimEnd('\') -eq [System.IO.Path]::GetFullPath($pythonRoot).TrimEnd('\'))
        } catch { $venvReady = $false }
    }
    if (-not $venvReady) {
        if (Test-Path -LiteralPath $venvRoot) { Remove-Item -LiteralPath $venvRoot -Recurse -Force }
        & $python -m venv $venvRoot
        if ($LASTEXITCODE -ne 0) { throw "Creating the local Python environment failed." }
    }
    $dependenciesReady = $false
    try {
        & $venvPython -c "import fastapi, uvicorn, sqlmodel, pydantic_settings, multipart, httpx, faster_whisper, google.genai, PIL, googleapiclient, google.auth"
        $dependenciesReady = $LASTEXITCODE -eq 0
    } catch { $dependenciesReady = $false }
    if (-not $dependenciesReady) {
        & $venvPython -m pip install --disable-pip-version-check --upgrade pip wheel
        if ($LASTEXITCODE -ne 0) { throw "Updating the package installer failed." }
        & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $appRoot "backend\requirements-local-assistant.txt")
        if ($LASTEXITCODE -ne 0) { throw "Installing Local Assistant dependencies failed." }
    } else {
        Write-InstallLog "Existing local video components are ready; dependency download skipped"
    }

    Write-Step "Preparing the private FFmpeg video tools"
    $ffmpeg = Join-Path $ffmpegRoot "bin\ffmpeg.exe"
    $ffprobe = Join-Path $ffmpegRoot "bin\ffprobe.exe"
    if (-not (Test-Path -LiteralPath $ffmpeg) -or -not (Test-Path -LiteralPath $ffprobe)) {
        $ffmpegArchive = Join-Path $tempRoot "ffmpeg-release-essentials.zip"
        $ffmpegExtract = Join-Path $tempRoot "ffmpeg-extracted"
        Invoke-VerifiedDownload $ffmpegArchiveUrl $ffmpegArchive "the private FFmpeg runtime" 50000000
        Expand-Archive -LiteralPath $ffmpegArchive -DestinationPath $ffmpegExtract -Force
        $downloadedFfmpeg = Get-ChildItem -LiteralPath $ffmpegExtract -Recurse -Filter "ffmpeg.exe" -File | Select-Object -First 1
        if (-not $downloadedFfmpeg) { throw "The FFmpeg archive has an unexpected structure." }
        $downloadedFfprobe = Join-Path $downloadedFfmpeg.Directory.FullName "ffprobe.exe"
        if (-not (Test-Path -LiteralPath $downloadedFfprobe)) { throw "The FFmpeg archive does not contain ffprobe.exe." }
        $ffmpegBin = Join-Path $ffmpegRoot "bin"
        if (Test-Path -LiteralPath $ffmpegRoot) { Remove-Item -LiteralPath $ffmpegRoot -Recurse -Force }
        New-Item -ItemType Directory -Path $ffmpegBin -Force | Out-Null
        Copy-Item -Path (Join-Path $downloadedFfmpeg.Directory.FullName "*") -Destination $ffmpegBin -Force
    }
    if (-not (Test-Path -LiteralPath $ffmpeg) -or -not (Test-Path -LiteralPath $ffprobe)) { throw "The private FFmpeg runtime was not installed correctly." }

    $settings = [ordered]@{}
    if (Test-Path -LiteralPath $settingsFile) {
        foreach ($line in Get-Content -LiteralPath $settingsFile -Encoding UTF8) {
            if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith("#")) { continue }
            $parts = $line.Split("=", 2)
            if ($parts.Count -eq 2) { $settings[$parts[0].Trim()] = $parts[1].Trim() }
        }
    }
    $settings["FFMPEG_BINARY"] = $ffmpeg.Replace("\", "/")
    $settings["FFPROBE_BINARY"] = $ffprobe.Replace("\", "/")
    if (-not $settings.Contains("GEMINI_API_KEY")) { $settings["GEMINI_API_KEY"] = "" }
    if (-not $settings.Contains("QWEN_API_KEY")) { $settings["QWEN_API_KEY"] = "" }
    $settingsLines = @($settings.GetEnumerator() | ForEach-Object { "{0}={1}" -f $_.Key, $_.Value })
    [System.IO.File]::WriteAllLines($settingsFile, $settingsLines, (New-Object System.Text.UTF8Encoding($false)))

    @'
$ErrorActionPreference = "Stop"
$installRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$appRoot = Join-Path $installRoot "app"
$settingsFile = Join-Path $installRoot "settings.env"
$python = Join-Path $installRoot ".venv\Scripts\python.exe"
$logRoot = Join-Path $installRoot "logs"
$stdoutLog = Join-Path $logRoot "assistant.out.log"
$stderrLog = Join-Path $logRoot "assistant.err.log"
$currentSessionId = (Get-Process -Id $PID).SessionId

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:17862/api/local/health" -TimeoutSec 2
    if ($health.status -eq "ok" -and $health.version -eq "1.13.0" -and $health.windows_user -eq $env:USERNAME -and $health.session_id -eq $currentSessionId -and $health.picker_ready -eq $true -and $health.capabilities -contains "native_folder_picker_v3" -and $health.capabilities -contains "legacy_server_import_v1" -and $health.capabilities -contains "factory_cancel_v1" -and $health.capabilities -contains "factory_sensitive_policy_v3" -and $health.capabilities -contains "factory_analysis_worker_v1" -and $health.capabilities -contains "factory_task_history_v1" -and $health.capabilities -contains "local_storage_manager_v1" -and $health.capabilities -contains "factory_model_proxy_v1" -and $health.capabilities -contains "meta_duration_guard_v1" -and $health.capabilities -contains "meta_metadata_guard_v1") { exit 0 }
} catch { }

if (Test-Path -LiteralPath $settingsFile) {
    foreach ($line in Get-Content -LiteralPath $settingsFile -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith("#")) { continue }
        $parts = $line.Split("=", 2)
        if ($parts.Count -eq 2) { [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process") }
    }
}
Set-Location -LiteralPath $appRoot
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
try {
    $process = Start-Process -FilePath $python -ArgumentList @("-m", "backend.local_workspace") -WorkingDirectory $appRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Local Assistant exited with code $($process.ExitCode). See $stderrLog" }
} catch {
    Add-Content -LiteralPath $stderrLog -Value ((Get-Date -Format "s") + " launcher error: " + $_.Exception.Message)
    throw
}
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
            if ($health.status -eq "ok" -and $health.version -eq "1.13.0" -and $health.windows_user -eq $env:USERNAME -and $health.session_id -eq $currentSessionId -and $health.picker_ready -eq $true -and $health.capabilities -contains "native_folder_picker_v3" -and $health.capabilities -contains "legacy_server_import_v1" -and $health.capabilities -contains "factory_cancel_v1" -and $health.capabilities -contains "factory_sensitive_policy_v3" -and $health.capabilities -contains "factory_analysis_worker_v1" -and $health.capabilities -contains "factory_task_history_v1" -and $health.capabilities -contains "local_storage_manager_v1" -and $health.capabilities -contains "factory_model_proxy_v1" -and $health.capabilities -contains "meta_duration_guard_v1" -and $health.capabilities -contains "meta_metadata_guard_v1") { $ready = $true; break }
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
