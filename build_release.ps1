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

Get-Process -Name "*Shadow*", "*WebP*", "*Setup*" -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item -Path "installer\Shadow-Media-Studio-Setup.exe", "installer\Shadow-Setup.exe" -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

& $iscc installer.iss

Write-Output "Release created: $project\installer\Shadow-Media-Studio-Setup.exe"
