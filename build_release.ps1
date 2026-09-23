param (
    [switch]$Sign,
    [string]$CertPath = $env:SHADOW_CERT_PATH,
    [string]$CertPassword = $env:SHADOW_CERT_PASSWORD,
    [string]$Thumbprint = $env:SHADOW_CERT_THUMBPRINT
)

$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project
$python = Join-Path $project "..\.venv\Scripts\python.exe"
$iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"

Get-Process -Name "*Shadow*", "*WebP*", "*Setup*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 300

if (-not (Test-Path (Join-Path $project "vendor\ffmpeg\ffmpeg.exe"))) {
    & (Join-Path $project "fetch_ffmpeg.ps1")
}

& $python -m unittest discover -s tests -v
& $python -m PyInstaller --clean "Shadow.spec"

# Sign application executable if signing credentials are provided
if ($Sign -or $CertPath -or $Thumbprint) {
    Write-Host "Signing application executable..." -ForegroundColor Cyan
    & (Join-Path $project "sign_windows.ps1") -Files @("dist\Shadow\Shadow.exe") -CertPath $CertPath -CertPassword $CertPassword -Thumbprint $Thumbprint
}

Get-Process -Name "*Shadow*", "*WebP*", "*Setup*" -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item -Path "installer\Shadow-Media-Studio-Setup.exe", "installer\Shadow-Setup.exe" -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

& $iscc installer.iss

# Sign installer executable if signing credentials are provided
$installerPath = "installer\Shadow-Media-Studio-Setup.exe"
if (($Sign -or $CertPath -or $Thumbprint) -and (Test-Path $installerPath)) {
    Write-Host "Signing installer package..." -ForegroundColor Cyan
    & (Join-Path $project "sign_windows.ps1") -Files @($installerPath) -CertPath $CertPath -CertPassword $CertPassword -Thumbprint $Thumbprint
}

Write-Output "Release created: $project\$installerPath"
