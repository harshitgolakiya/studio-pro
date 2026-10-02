param(
    [string]$Python = "python",
    [switch]$SkipOffice,
    [switch]$SkipModels
)
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    & $Python -m pip install -r requirements-studio.txt
    if ($LASTEXITCODE -ne 0) { throw "Studio package installation failed" }
    if (-not (Test-Path -LiteralPath "vendor/ffmpeg/ffmpeg.exe")) {
        & (Join-Path $PSScriptRoot "fetch_ffmpeg.ps1")
        if (-not (Test-Path -LiteralPath "vendor/ffmpeg/ffmpeg.exe")) { throw "FFmpeg setup failed" }
    }
    if (-not $SkipOffice -and -not (Test-Path -LiteralPath "vendor/libreoffice/program/soffice.com")) {
        $officeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "vendor/libreoffice"))
        $downloads = Join-Path $PSScriptRoot "vendor/downloads"
        New-Item -ItemType Directory -Force -Path $downloads | Out-Null
        $msi = Join-Path $downloads "LibreOffice_26.2.6_Win_x86-64.msi"
        $url = "https://download.documentfoundation.org/libreoffice/stable/26.2.6/win/x86_64/LibreOffice_26.2.6_Win_x86-64.msi"
        $expected = "f9877032fd908beb9c0ddf06df4af5c2e85f419c42e14876c4cce5aae5fb2660"
        if (-not (Test-Path -LiteralPath $msi)) {
            Write-Host "Downloading the Office engine…"
            $ProgressPreference = "SilentlyContinue"
            try {
                Invoke-WebRequest -Uri $url -OutFile $msi -TimeoutSec 120
            } catch {
                Write-Host "Trying the LibreOffice mirror..."
                Invoke-WebRequest -Uri 'https://mirrors.ibiblio.org/libreoffice/stable/26.2.6/win/x86_64/LibreOffice_26.2.6_Win_x86-64.msi' -OutFile $msi -TimeoutSec 600
            }
        }
        if ((Get-FileHash -LiteralPath $msi -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
            throw "LibreOffice download checksum mismatch; remove the downloaded MSI and retry."
        }
        Write-Host "Extracting LibreOffice locally (no system installation)…"
        $msiLog = Join-Path $downloads "libreoffice-extract.log"
        $proc = Start-Process msiexec.exe -ArgumentList @("/a", "`"$msi`"", "/qn", "TARGETDIR=`"$officeRoot`"", "/L*v", "`"$msiLog`"") -WindowStyle Hidden -Wait -PassThru
        if ($proc.ExitCode -ne 0) { throw "Office extraction failed ($($proc.ExitCode)); see $msiLog" }
        if (-not (Test-Path -LiteralPath (Join-Path $officeRoot "program/soffice.com"))) {
            throw "Office extraction did not produce program/soffice.com"
        }
    }
    if (-not $SkipModels) {
        & $Python setup_studio_models.py
        if ($LASTEXITCODE -ne 0) { throw "Speech model setup failed" }
    }
    & $Python setup_print.py
    if ($LASTEXITCODE -ne 0) { throw "Print engine setup failed" }
    Write-Host "Studio engines ready. Run: $Python main.py"
} finally {
    Pop-Location
}
