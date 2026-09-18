# Downloads the FFmpeg "essentials" build into vendor\ffmpeg so it can be
# bundled into the packaged .exe (see media_engine.py + Shadow.spec).
# Not run automatically on every dev machine -- only needed before building
# a release, or if vendor\ffmpeg is missing/out of date.
$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$vendorDir = Join-Path $project "vendor\ffmpeg"
New-Item -ItemType Directory -Force -Path $vendorDir | Out-Null

$zipUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$zipPath = Join-Path $env:TEMP "shadow_ffmpeg_download.zip"

Write-Output "Downloading FFmpeg essentials build..."
Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath

$extractDir = Join-Path $env:TEMP "shadow_ffmpeg_extract"
if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
Expand-Archive -Path $zipPath -DestinationPath $extractDir

$buildFolder = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
Copy-Item (Join-Path $buildFolder.FullName "bin\ffmpeg.exe") (Join-Path $vendorDir "ffmpeg.exe") -Force
Copy-Item (Join-Path $buildFolder.FullName "bin\ffprobe.exe") (Join-Path $vendorDir "ffprobe.exe") -Force
Copy-Item (Join-Path $buildFolder.FullName "LICENSE") (Join-Path $vendorDir "LICENSE-ffmpeg-GPLv3.txt") -Force

Remove-Item $zipPath -Force
Remove-Item -Recurse -Force $extractDir

Write-Output "FFmpeg placed in $vendorDir"
Write-Output "Note: this build is GPLv3-licensed. It is bundled unmodified as a separate"
Write-Output "executable invoked via subprocess (not linked into the app), with its license"
Write-Output "included. See EULA.txt / README.md for the attribution notice."
