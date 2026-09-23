<#
.SYNOPSIS
    Signs Windows binaries and the Inno Setup installer for Shadow Media Studio Pro.
.DESCRIPTION
    Supports Signtool.exe and PowerShell Authenticode signing using:
    - PFX certificate file + password
    - Installed certificate thumbprint (Cert:\CurrentUser\My or Cert:\LocalMachine\My)
    - Auto-generated local self-signed test certificate
#>

param (
    [string[]]$Files = @("dist\Shadow\Shadow.exe", "installer\Shadow-Media-Studio-Setup.exe"),
    [string]$CertPath = $env:SHADOW_CERT_PATH,
    [string]$CertPassword = $env:SHADOW_CERT_PASSWORD,
    [string]$Thumbprint = $env:SHADOW_CERT_THUMBPRINT,
    [string]$TimestampServer = "http://timestamp.digicert.com",
    [switch]$GenerateTestCert,
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"

function Find-SignTool {
    $found = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }

    $roots = @(
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    )
    foreach ($root in $roots) {
        if (-not $root) { continue }
        $kitsBin = Join-Path $root "Windows Kits\10\bin"
        if (Test-Path $kitsBin) {
            $matches = Get-ChildItem -Path $kitsBin -Filter "signtool.exe" -Recurse -ErrorAction SilentlyContinue |
                       Where-Object { $_.FullName -match "x64" } |
                       Sort-Object -Property FullName -Descending
            if ($matches.Count -gt 0) {
                return $matches[0].FullName
            }
        }
    }
    return $null
}

if ($VerifyOnly) {
    Write-Host "Verifying Authenticode signatures..." -ForegroundColor Cyan
    foreach ($file in $Files) {
        if (-not (Test-Path $file)) {
            Write-Warning "File not found: $file"
            continue
        }
        $sig = Get-AuthenticodeSignature -LiteralPath $file
        Write-Host "[$($sig.Status)] $file" -ForegroundColor ($sig.Status -eq "Valid" ? "Green" : "Yellow")
        if ($sig.SignerCertificate) {
            Write-Host "  Signer: $($sig.SignerCertificate.Subject)"
            Write-Host "  Thumbprint: $($sig.SignerCertificate.Thumbprint)"
        }
    }
    exit 0
}

# If no cert provided and test cert requested, create one
if (-not $CertPath -and -not $Thumbprint -and $GenerateTestCert) {
    Write-Host "Generating local self-signed code signing certificate..." -ForegroundColor Yellow
    $testCert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=Shadow Media Studio Test" -CertStoreLocation "Cert:\CurrentUser\My"
    $Thumbprint = $testCert.Thumbprint
    Write-Host "Created test certificate with thumbprint: $Thumbprint" -ForegroundColor Green
}

if (-not $CertPath -and -not $Thumbprint) {
    Write-Host "No code signing certificate specified (SHADOW_CERT_PATH or SHADOW_CERT_THUMBPRINT)." -ForegroundColor Yellow
    Write-Host "To test signing locally, run with -GenerateTestCert" -ForegroundColor Gray
    exit 0
}

$signtool = Find-SignTool

foreach ($file in $Files) {
    if (-not (Test-Path $file)) {
        Write-Warning "Skipping nonexistent file: $file"
        continue
    }

    Write-Host "Signing: $file" -ForegroundColor Cyan
    $signed = $false

    if ($signtool) {
        $args = @("sign", "/fd", "SHA256", "/tr", $TimestampServer, "/td", "SHA256")
        if ($CertPath) {
            $args += @("/f", $CertPath)
            if ($CertPassword) { $args += @("/p", $CertPassword) }
        } elseif ($Thumbprint) {
            $args += @("/sha1", $Thumbprint, "/sm")
        }
        $args += $file

        & $signtool @args
        if ($LASTEXITCODE -eq 0) { $signed = $true }
    }

    if (-not $signed) {
        Write-Host "Signing with Set-AuthenticodeSignature fallback..." -ForegroundColor Gray
        if ($CertPath) {
            $secPass = ConvertTo-SecureString -String ($CertPassword ?? "") -AsPlainText -Force
            $cert = Get-PfxCertificate -FilePath $CertPath -Password $secPass
        } else {
            $cert = Get-Item "Cert:\CurrentUser\My\$Thumbprint" -ErrorAction SilentlyContinue
            if (-not $cert) { $cert = Get-Item "Cert:\LocalMachine\My\$Thumbprint" }
        }

        if ($cert) {
            $sig = Set-AuthenticodeSignature -FilePath $file -Certificate $cert -TimestampServer $TimestampServer -HashAlgorithm SHA256
            if ($sig.Status -eq "Valid" -or $sig.Status -eq "UnknownError") {
                $signed = $true
            } else {
                Write-Warning "Authenticode status: $($sig.Status) - $($sig.StatusMessage)"
            }
        }
    }

    if ($signed) {
        Write-Host "Successfully signed: $file" -ForegroundColor Green
    } else {
        Write-Error "Failed to sign: $file"
    }
}
