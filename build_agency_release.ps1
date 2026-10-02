param(
    [string]$WorkRoot = (Join-Path $PSScriptRoot 'agency-build'),
    [switch]$SkipTests,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$taskProject = [IO.Path]::GetFullPath($PSScriptRoot)
$taskRoot = [IO.Path]::GetFullPath($WorkRoot)
$taskPython = Join-Path $taskProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create the project .venv and run setup_studio.ps1 first.' }
New-Item -ItemType Directory -Force -Path $taskRoot | Out-Null
$taskReportDir = Join-Path $taskRoot 'verification'
New-Item -ItemType Directory -Force -Path $taskReportDir | Out-Null
function Invoke-AgencyProcess([string]$Executable, [string[]]$Arguments, [string]$Label) {
    $taskStdout = Join-Path $taskReportDir ($Label + '.stdout.log')
    $taskStderr = Join-Path $taskReportDir ($Label + '.stderr.log')
    $taskProcess = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $taskProject -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $taskStdout -RedirectStandardError $taskStderr
    if ($taskProcess.ExitCode -ne 0) { throw "$Label failed ($($taskProcess.ExitCode)); see $taskStdout and $taskStderr" }
}
Push-Location $taskProject
try {
    if (-not $SkipTests) {
        $env:SHADOW_TEST_FULL_STUDIO = '1'
        Invoke-AgencyProcess $taskPython @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v') 'source-tests'
    }
    $taskDist = Join-Path $taskRoot 'dist'
    $taskBuild = Join-Path $taskRoot 'build'
    if (-not $SkipBuild) {
        Invoke-AgencyProcess $taskPython @('-m', 'PyInstaller', '--noconfirm', '--distpath', ('"' + $taskDist + '"'), '--workpath', ('"' + $taskBuild + '"'), 'Shadow.spec') 'pyinstaller'
    }
    $taskApp = Join-Path $taskDist 'Shadow\Shadow.exe'
    $taskSmokePath = Join-Path $taskReportDir 'packaged-smoke.json'
    Invoke-AgencyProcess $taskApp @('--studio-smoke-report', ('"' + $taskSmokePath + '"')) 'packaged-smoke'
    $taskSmoke = Get-Content -LiteralPath $taskSmokePath -Raw | ConvertFrom-Json
    if (-not $taskSmoke.passed) { throw 'Packaged engine verification did not pass.' }
    $taskIscc = @((Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'), 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe') | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $taskIscc) { throw 'Inno Setup 6 was not found.' }
    $taskInstallerDir = Join-Path $taskRoot 'installer'
    New-Item -ItemType Directory -Force -Path $taskInstallerDir | Out-Null
    $taskBundleBytes = (Get-ChildItem -LiteralPath (Join-Path $taskDist 'Shadow') -File -Recurse | Measure-Object -Property Length -Sum).Sum
    $taskSpanning = if ($taskBundleBytes -gt 3GB) { 'yes' } else { 'no' }
    $taskCompression = if ($taskSpanning -eq 'yes') { 'none' } else { 'lzma2' }
    $taskSolid = if ($taskSpanning -eq 'yes') { 'no' } else { 'yes' }
    Invoke-AgencyProcess $taskIscc @(('/DMyAppSource="' + (Join-Path $taskDist 'Shadow') + '"'), '/DMyAppOutputName=Shadow-Agency-Studio-Setup', ("/DMyAppDiskSpanning=" + $taskSpanning), ("/DMyAppCompression=" + $taskCompression), ("/DMyAppSolidCompression=" + $taskSolid), ('/O"' + $taskInstallerDir + '"'), 'installer.iss') 'installer'
    $taskInstaller = Join-Path $taskInstallerDir 'Shadow-Agency-Studio-Setup.exe'
    $taskHash = Get-FileHash -LiteralPath $taskInstaller -Algorithm SHA256
    Set-Content -LiteralPath ($taskInstaller + '.sha256') -Value ($taskHash.Hash.ToLowerInvariant() + '  Shadow-Agency-Studio-Setup.exe') -Encoding ASCII
    $taskParts = @(Get-ChildItem -LiteralPath $taskInstallerDir -File | Where-Object { $_.Name -match '^Shadow-Agency-Studio-Setup(?:-\d+)?\.(exe|bin)$' } | ForEach-Object {
        @{ name = $_.Name; bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
    $taskReceipt = @{ installer = $taskInstaller; bytes = (Get-Item -LiteralPath $taskInstaller).Length; sha256 = $taskHash.Hash.ToLowerInvariant(); files = $taskParts; packaged_checks = $taskSmoke.checks }
    $taskReceipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $taskReportDir 'release-receipt.json') -Encoding UTF8
    Write-Output "Verified installer: $taskInstaller"
} finally {
    Pop-Location
}
