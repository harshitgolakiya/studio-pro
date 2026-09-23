"""Cross-platform code signing and signature verification utilities.

Supports:
- Windows: Authenticode signing via signtool.exe or Set-AuthenticodeSignature,
  and signature inspection via Get-AuthenticodeSignature.
- macOS: codesign with Hardened Runtime and entitlements, xcrun notarytool
  for Apple notarization, and stapling via xcrun stapler.
- Self-signed test certificate generation for CI / local test environments.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_TIMESTAMP_SERVER = "http://timestamp.digicert.com"


@dataclass
class SignatureInfo:
    path: str
    is_signed: bool
    status: str = "NotSigned"  # Valid, NotSigned, HashMismatch, NotTrusted, etc.
    signer: str = ""
    timestamp: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def find_windows_signtool() -> str | None:
    """Locate signtool.exe from PATH or Windows Kits directory."""
    which_signtool = shutil.which("signtool.exe") or shutil.which("signtool")
    if which_signtool:
        return which_signtool

    # Common Windows SDK search roots
    sdk_roots = [
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
    ]
    for root in sdk_roots:
        kits = Path(root) / "Windows Kits" / "10" / "bin"
        if kits.is_dir():
            # Search x64 versions first, sorted newest version first
            for arch in ("x64", "x86", "arm64"):
                matches = sorted(kits.glob(f"*/{arch}/signtool.exe"), reverse=True)
                if matches:
                    return str(matches[0])
    return None


def verify_signature(target_path: Path | str) -> SignatureInfo:
    """Inspect and verify the code signature of an executable, installer, or bundle."""
    path = Path(target_path).resolve()
    if not path.exists():
        return SignatureInfo(
            path=str(path),
            is_signed=False,
            status="FileNotFound",
            details={"error": f"File not found: {path}"},
        )

    current_os = platform.system()
    if current_os == "Windows":
        return _verify_windows_signature(path)
    elif current_os == "Darwin":
        return _verify_macos_signature(path)
    else:
        return SignatureInfo(
            path=str(path),
            is_signed=False,
            status="UnsupportedPlatform",
            details={"platform": current_os},
        )


def _verify_windows_signature(path: Path) -> SignatureInfo:
    """Verify Windows Authenticode signature using PowerShell."""
    pwsh = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or "powershell"
    script = (
        f"$sig = Get-AuthenticodeSignature -LiteralPath '{path}'; "
        "$res = [PSCustomObject]@{"
        "Status = [string]$sig.Status; "
        "StatusMessage = [string]$sig.StatusMessage; "
        "Signer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { '' }; "
        "Thumbprint = if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { '' }; "
        "TimeStamper = if ($sig.TimeStamperCertificate) { $sig.TimeStamperCertificate.Subject } else { '' }; "
        "}; "
        "$res | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            raw_status = (data.get("Status") or "").strip()
            status = raw_status if raw_status else "NotSigned"
            is_signed = status in ("Valid", "NotTrusted")
            return SignatureInfo(
                path=str(path),
                is_signed=is_signed,
                status=status,
                signer=data.get("Signer", ""),
                timestamp=data.get("TimeStamper") or None,
                details=data,
            )
    except Exception as e:
        log.debug("PowerShell authenticode check failed: %s", e)

    return SignatureInfo(
        path=str(path),
        is_signed=False,
        status="CheckFailed",
        details={"error": "Could not inspect signature via PowerShell"},
    )


def _verify_macos_signature(path: Path) -> SignatureInfo:
    """Verify macOS signature using codesign and spctl."""
    codesign = shutil.which("codesign")
    if not codesign:
        return SignatureInfo(path=str(path), is_signed=False, status="CodesignNotFound")

    proc = subprocess.run(
        [codesign, "-dvvv", str(path)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    output = (proc.stdout + "\n" + proc.stderr).strip()
    is_signed = "code object is not signed at all" not in output and proc.returncode == 0
    signer = ""
    for line in output.splitlines():
        if line.startswith("Authority="):
            signer = line.split("=", 1)[1].strip()
            break

    # Gatekeeper check
    spctl = shutil.which("spctl")
    gatekeeper_status = "Unknown"
    if spctl and is_signed:
        target_type = "open" if path.suffix.lower() == ".dmg" else "exec"
        gproc = subprocess.run(
            [spctl, "--assess", "--type", target_type, "-v", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        gatekeeper_status = "Accepted" if gproc.returncode == 0 else "Rejected"

    return SignatureInfo(
        path=str(path),
        is_signed=is_signed,
        status="Valid" if is_signed else "NotSigned",
        signer=signer,
        details={"output": output, "gatekeeper": gatekeeper_status},
    )


def sign_windows_binary(
    target_path: Path | str,
    cert_path: Path | str | None = None,
    cert_password: str | None = None,
    thumbprint: str | None = None,
    timestamp_server: str = DEFAULT_TIMESTAMP_SERVER,
    signtool_path: str | None = None,
) -> tuple[bool, str]:
    """Sign a Windows executable or installer using signtool.exe or Set-AuthenticodeSignature."""
    path = Path(target_path).resolve()
    if not path.exists():
        return False, f"Target file does not exist: {path}"

    signtool = signtool_path or find_windows_signtool()
    if signtool:
        cmd = [signtool, "sign", "/fd", "SHA256", "/tr", timestamp_server, "/td", "SHA256"]
        if cert_path:
            cmd.extend(["/f", str(cert_path)])
            if cert_password:
                cmd.extend(["/p", cert_password])
        elif thumbprint:
            cmd.extend(["/sha1", thumbprint, "/sm"])
        else:
            cmd.extend(["/a"])  # Auto-select best cert in store

        cmd.append(str(path))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            return True, f"Signed successfully with signtool: {path.name}"
        return False, f"signtool error ({proc.returncode}): {proc.stderr or proc.stdout}"

    # Fallback to PowerShell Set-AuthenticodeSignature
    pwsh = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or "powershell"
    if cert_path:
        ps_script = (
            f"$pass = ConvertTo-SecureString -String '{cert_password or ''}' -AsPlainText -Force; "
            f"$cert = Get-PfxCertificate -FilePath '{cert_path}' -Password $pass; "
            f"$sig = Set-AuthenticodeSignature -FilePath '{path}' -Certificate $cert "
            f"-TimestampServer '{timestamp_server}' -HashAlgorithm SHA256; "
            "if ($sig.Status -eq 'Valid' -or $sig.Status -eq 'UnknownError') { exit 0 } else { exit 1 }"
        )
    elif thumbprint:
        ps_script = (
            f"$cert = Get-Item 'Cert:\\CurrentUser\\My\\{thumbprint}' -ErrorAction SilentlyContinue; "
            f"if (-not $cert) {{ $cert = Get-Item 'Cert:\\LocalMachine\\My\\{thumbprint}' }}; "
            f"$sig = Set-AuthenticodeSignature -FilePath '{path}' -Certificate $cert "
            f"-TimestampServer '{timestamp_server}' -HashAlgorithm SHA256; "
            "if ($sig.Status -eq 'Valid' -or $sig.Status -eq 'UnknownError') { exit 0 } else { exit 1 }"
        )
    else:
        return False, "Neither signtool.exe nor certificate parameters were available"

    proc = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True, f"Signed via Set-AuthenticodeSignature: {path.name}"
    return False, f"Set-AuthenticodeSignature failed: {proc.stderr or proc.stdout}"


def sign_macos_bundle(
    bundle_path: Path | str,
    identity: str,
    entitlements_path: Path | str | None = None,
    deep: bool = True,
) -> tuple[bool, str]:
    """Sign a macOS .app bundle using codesign."""
    path = Path(bundle_path).resolve()
    if not path.exists():
        return False, f"Target bundle does not exist: {path}"

    cmd = ["codesign", "--force", "--timestamp", "--options", "runtime"]
    if deep:
        cmd.append("--deep")
    if entitlements_path and Path(entitlements_path).is_file():
        cmd.extend(["--entitlements", str(entitlements_path)])
    cmd.extend(["-s", identity, str(path)])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return True, f"Signed macOS bundle: {path.name}"
    return False, f"codesign failed ({proc.returncode}): {proc.stderr or proc.stdout}"


def notarize_macos_dmg(
    dmg_path: Path | str,
    apple_id: str,
    app_password: str,
    team_id: str,
) -> tuple[bool, str]:
    """Submit a DMG to Apple Notary Service and staple the ticket."""
    path = Path(dmg_path).resolve()
    if not path.exists():
        return False, f"DMG does not exist: {path}"

    cmd = [
        "xcrun", "notarytool", "submit", str(path),
        "--apple-id", apple_id,
        "--password", app_password,
        "--team-id", team_id,
        "--wait",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return False, f"Notarization submission failed: {proc.stderr or proc.stdout}"

    # Staple ticket
    staple_proc = subprocess.run(["xcrun", "stapler", "staple", str(path)], capture_output=True, text=True)
    if staple_proc.returncode != 0:
        return False, f"Stapling failed: {staple_proc.stderr or staple_proc.stdout}"

    return True, f"Successfully notarized and stapled: {path.name}"


def create_self_signed_certificate(
    output_pfx: Path | str,
    password: str = "shadow123",
    subject: str = "CN=Shadow Media Studio Test",
) -> Path | None:
    """Generate a self-signed code-signing certificate for testing."""
    pfx_path = Path(output_pfx).resolve()
    pfx_path.parent.mkdir(parents=True, exist_ok=True)

    # If running on Windows, try PowerShell New-SelfSignedCertificate
    if platform.system() == "Windows":
        pwsh = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or "powershell"
        script = (
            f"$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject '{subject}' "
            "-CertStoreLocation 'Cert:\\CurrentUser\\My'; "
            f"$pass = ConvertTo-SecureString -String '{password}' -AsPlainText -Force; "
            f"Export-PfxCertificate -Cert $cert -FilePath '{pfx_path}' -Password $pass; "
            "if (Test-Path '{pfx_path}') { exit 0 } else { exit 1 }"
        )
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and pfx_path.is_file():
            return pfx_path

    # Cross-platform fallback using cryptography
    try:
        from datetime import datetime, timedelta, timezone
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        sub_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject.replace("CN=", ""))])
        cert = (
            x509.CertificateBuilder()
            .subject_name(sub_name)
            .issuer_name(sub_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]),
                critical=True,
            )
            .sign(key, hashes.SHA256())
        )
        pfx_bytes = pkcs12.serialize_key_and_certificates(
            name=b"ShadowTestCert",
            key=key,
            cert=cert,
            cas=None,
            encryption_algorithm=BestAvailableEncryption(password.encode("utf-8")),
        )
        pfx_path.write_bytes(pfx_bytes)
        return pfx_path
    except Exception as e:
        log.warning("Could not generate self-signed cert via cryptography: %s", e)
        return None
