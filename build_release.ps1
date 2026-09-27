param (
    [switch]$Sign,
    [string]$CertPath = $env:SHADOW_CERT_PATH,
    [string]$CertPassword = $env:SHADOW_CERT_PASSWORD,
    [string]$Thumbprint = $env:SHADOW_CERT_THUMBPRINT
)

$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project
$pythonCandidates = @(
    (Join-Path $project ".venv\Scripts\python.exe"),
    (Join-Path $project "..\.venv\Scripts\python.exe")
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    throw "No project virtual environment found. Create .venv and install requirements.txt first."
}

$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $iscc) {
    throw "Inno Setup 6 was not found. Install it with: winget install JRSoftware.InnoSetup"
}

Get-Process -Name "Shadow", "Shadow-Media-Studio-Setup" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 300

if (-not (Test-Path (Join-Path $project "vendor\ffmpeg\ffmpeg.exe"))) {
    & (Join-Path $project "fetch_ffmpeg.ps1")
}

Write-Host "Running automated tests..." -ForegroundColor Cyan
& $python -m unittest discover -s tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    throw "Automated tests failed; release build stopped."
}

Remove-Item -Recurse -Force (Join-Path $project "dist\Shadow"), (Join-Path $project "build\Shadow") -ErrorAction SilentlyContinue

& $python -m PyInstaller --clean -y "Shadow.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

# Sign application executable if signing credentials are provided
if ($Sign -or $CertPath -or $Thumbprint) {
    Write-Host "Signing application executable..." -ForegroundColor Cyan
    & (Join-Path $project "sign_windows.ps1") -Files @("dist\Shadow\Shadow.exe") -CertPath $CertPath -CertPassword $CertPassword -Thumbprint $Thumbprint
}

Get-Process -Name "Shadow", "Shadow-Media-Studio-Setup" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

New-Item -ItemType Directory -Path (Join-Path $project "dist_installer") -Force | Out-Null
$compiledInstaller = Join-Path $project "dist_installer\Shadow-Media-Studio-Setup.exe"
$innoSucceeded = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    & $iscc /O"dist_installer" installer.iss
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $compiledInstaller)) {
        $innoSucceeded = $true
        break
    }
    if ($attempt -lt 3) {
        Write-Warning "Inno Setup attempt $attempt failed (Windows may be scanning the new executable); retrying..."
        Remove-Item -LiteralPath $compiledInstaller -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}
if (-not $innoSucceeded) {
    throw "Inno Setup compilation failed."
}
Copy-Item -Force $compiledInstaller (Join-Path $project "installer\Shadow-Media-Studio-Setup.exe")
Remove-Item -Recurse -Force (Join-Path $project "dist_installer") -ErrorAction SilentlyContinue

# Sign installer executable if signing credentials are provided
$installerPath = "installer\Shadow-Media-Studio-Setup.exe"
if (($Sign -or $CertPath -or $Thumbprint) -and (Test-Path $installerPath)) {
    Write-Host "Signing installer package..." -ForegroundColor Cyan
    & (Join-Path $project "sign_windows.ps1") -Files @($installerPath) -CertPath $CertPath -CertPassword $CertPassword -Thumbprint $Thumbprint
}

Write-Output "Release created: $project\$installerPath"
