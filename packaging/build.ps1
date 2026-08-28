# Task Verge packaging script — self-contained desktop EXE + installer
# Run from the project root:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
param(
    [switch]$InstallerOnly,
    [switch]$ZipOnly,
    [switch]$SkipTests,
    [string]$SigningThumbprint = $env:TASKVERGE_SIGNING_THUMBPRINT,
    [string]$TimestampServer = $env:TASKVERGE_TIMESTAMP_URL
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dist = Join-Path $Root "dist"
$Version = "0.2.0"
$OutputZip = Join-Path $Root "task-verge-portable-v$Version-win-x64.zip"

function Sign-Artifact([string]$Path) {
    if (-not $SigningThumbprint) { return }
    $cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object Thumbprint -eq $SigningThumbprint | Select-Object -First 1
    if (-not $cert -or -not $cert.HasPrivateKey) { throw "Code-signing certificate unavailable: $SigningThumbprint" }
    $args = @{ FilePath=$Path; Certificate=$cert; HashAlgorithm="SHA256" }
    if ($TimestampServer) { $args.TimestampServer=$TimestampServer }
    $signature = Set-AuthenticodeSignature @args
    if ($signature.Status -ne "Valid") { throw "Signing failed for $Path`: $($signature.StatusMessage)" }
}

Write-Host "=== Task Verge Build ===" -ForegroundColor Cyan

$buildRequirements = Join-Path $Root "requirements-build.txt"
if (-not (Test-Path $buildRequirements)) { throw "Missing build dependency manifest: $buildRequirements" }

if (-not $SkipTests -and -not $InstallerOnly) {
    & (Join-Path $Root "packaging\verify.ps1")
    if ($LASTEXITCODE -ne 0) { throw "verification failed" }
}

# ---- Native desktop bundle ----
if (-not $InstallerOnly) {
    Write-Host "[1/2] Building native desktop bundle..." -ForegroundColor Yellow

    # Clean dist/
    if (Test-Path $Dist) { Remove-Item -Recurse -Force $Dist }
    $Work = Join-Path $Root "build\pyinstaller"
    python -m PyInstaller --noconfirm --clean --windowed --onedir `
        --name TaskVerge --distpath $Dist --workpath $Work `
        --specpath (Join-Path $Root "build") `
        --icon (Join-Path $Root "web\taskverge.ico") `
        --version-file (Join-Path $Root "packaging\version_info.txt") `
        --add-data "$(Join-Path $Root 'web');web" `
        (Join-Path $Root "task-panel.pyw")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
    Sign-Artifact (Join-Path $Dist "TaskVerge\TaskVerge.exe")

    # Create ZIP
    if (Test-Path $OutputZip) { Remove-Item $OutputZip -Force }
    Compress-Archive -Path "$Dist\TaskVerge\*" -DestinationPath $OutputZip -Force
    Write-Host "  → $OutputZip" -ForegroundColor Green
}

# ---- Inno Setup ----
if (-not $ZipOnly) {
    Write-Host "[2/2] Inno Setup installer..." -ForegroundColor Yellow
    $issPath = Join-Path $Root "packaging\installer.iss"

    if (-not (Test-Path $issPath)) {
        Write-Host "  SKIP: installer.iss not found (Inno Setup skeleton needs ISCC.exe)" -ForegroundColor DarkYellow
    } else {
        $iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "C:\Program Files\Inno Setup 6\ISCC.exe", "C:\Program Files (x86)\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($iscc) {
            & $iscc $issPath
            if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }
            Sign-Artifact (Join-Path $Root "task-verge-setup-v$Version-win-x64.exe")
            Write-Host "  → Installer built" -ForegroundColor Green
        } else {
            Write-Host "  SKIP: ISCC.exe not found at $iscc" -ForegroundColor DarkYellow
        }
    }
}

Write-Host "=== Done ===" -ForegroundColor Cyan
