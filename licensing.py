from __future__ import annotations

import base64
import os
from pathlib import Path
import sys
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from settings import get_app_data_dir, load_settings, update_setting

if sys.platform == "win32":
    try:
        import winreg
    except ImportError:
        winreg = None
else:
    winreg = None

# Public key used to verify license keys offline. This is safe to ship: it can
# only VERIFY signatures, never CREATE them. Valid license keys can only be
# produced by whoever holds the matching private key (see keygen_tool.py,
# which must never be distributed with the application).
PUBLIC_KEY_HEX = "fd3a559d47979ef16a094fc90e1e6353d301d887447d0d9ee43afde122890eb9"

_TIER_PRO = 0
_TIER_VIP = 1
_TIER_BY_PREFIX = {"PRO": _TIER_PRO, "VIP": _TIER_VIP}
_PREFIX_BY_TIER = {_TIER_PRO: "PRO", _TIER_VIP: "VIP"}
_SIGNATURE_LEN = 64
_PAYLOAD_LEN = 1 + _SIGNATURE_LEN  # tier byte + Ed25519 signature

FREE_BATCH_LIMIT = 5


def _signing_message(tier_byte: int) -> bytes:
    """Fixed message format signed by the license issuer for a given tier."""
    return b"SHADOW-LICENSE-V1:" + bytes([tier_byte])


def _public_key() -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))


def _b32_encode(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=")


def _b32_decode(text: str) -> bytes | None:
    # Restore padding for standard base32 decoding.
    pad_len = (-len(text)) % 8
    try:
        return base64.b32decode(text + ("=" * pad_len))
    except Exception:
        return None


def _group(text: str, size: int = 8) -> str:
    return "-".join(text[i:i + size] for i in range(0, len(text), size))


def validate_license_key(key: str) -> bool:
    """Cryptographically verify a Pro or VIP license key offline (Ed25519)."""
    if not key or not isinstance(key, str):
        return False
    clean = key.strip().upper().replace(" ", "")
    parts = clean.split("-")
    if len(parts) < 2:
        return False
    prefix = parts[0]
    if prefix not in _TIER_BY_PREFIX:
        return False

    encoded_payload = "".join(parts[1:])
    payload = _b32_decode(encoded_payload)
    if payload is None or len(payload) != _PAYLOAD_LEN:
        return False

    tier_byte = payload[0]
    signature = payload[1:]
    if tier_byte != _TIER_BY_PREFIX[prefix]:
        return False

    try:
        _public_key().verify(signature, _signing_message(tier_byte))
    except InvalidSignature:
        return False
    except Exception:
        return False
    return True


def _get_registry_license() -> str:
    """Retrieve license key from Windows Registry (HKCU\\Software\\Shadow or legacy MediaCompressorStudio)."""
    if not winreg:
        return ""
    for subkey_name in (r"Software\Shadow", r"Software\MediaCompressorStudio"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey_name) as key:
                val, _ = winreg.QueryValueEx(key, "LicenseKey")
                if isinstance(val, str) and validate_license_key(val):
                    return val.strip()
        except Exception:
            pass
    return ""


def _save_registry_license(license_key: str) -> None:
    """Save or delete license key in Windows Registry under Software\\Shadow."""
    if not winreg:
        return
    for subkey_name in (r"Software\Shadow", r"Software\MediaCompressorStudio"):
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey_name) as key:
                winreg.SetValueEx(key, "LicenseKey", 0, winreg.REG_SZ, license_key)
                winreg.SetValueEx(key, "Activated", 0, winreg.REG_DWORD, 1 if license_key else 0)
        except Exception:
            pass


def _get_file_license() -> str:
    """Check dedicated backup license files."""
    candidates: list[Path] = [
        get_app_data_dir() / "license.key",
    ]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Shadow" / "license.key")
        candidates.append(Path(local_appdata) / "MediaCompressorStudio" / "license.key")
    candidates.append(Path.home() / ".shadow" / "license.key")
    candidates.append(Path.home() / ".mediacompressor" / "license.key")

    for p in candidates:
        try:
            if p.is_file():
                content = p.read_text(encoding="utf-8").strip()
                if validate_license_key(content):
                    return content
        except Exception:
            pass
    return ""


def _save_file_license(license_key: str) -> None:
    """Save or delete dedicated backup license files."""
    targets: list[Path] = [
        get_app_data_dir() / "license.key",
    ]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        targets.append(Path(local_appdata) / "Shadow" / "license.key")
        if not license_key:
            targets.append(Path(local_appdata) / "MediaCompressorStudio" / "license.key")
    appdata = os.environ.get("APPDATA")
    if appdata and not license_key:
        targets.append(Path(appdata) / "MediaCompressorStudio" / "license.key")
    targets.append(Path.home() / ".shadow" / "license.key")
    if not license_key:
        targets.append(Path.home() / ".mediacompressor" / "license.key")

    for p in targets:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if license_key:
                p.write_text(license_key, encoding="utf-8")
            elif p.exists():
                p.unlink()
        except Exception:
            pass


def get_active_license_key() -> str:
    """
    Retrieve active license key by checking Windows Registry, backup license files,
    and settings.json. Auto-repairs settings if needed.
    """
    # 1. Registry
    reg_key = _get_registry_license()
    if reg_key:
        return reg_key

    # 2. Backup key files
    file_key = _get_file_license()
    if file_key:
        # Sync to registry
        _save_registry_license(file_key)
        return file_key

    # 3. Settings JSON
    cfg = load_settings()
    cfg_key = cfg.get("license_key", "")
    if cfg.get("license_activated") and isinstance(cfg_key, str) and validate_license_key(cfg_key):
        # Sync to registry & key file
        _save_registry_license(cfg_key)
        _save_file_license(cfg_key)
        return cfg_key

    return ""


def is_vip_activated() -> bool:
    """Check whether a valid VIP license key has been activated."""
    key = get_active_license_key()
    if not key:
        return False
    clean = key.strip().upper()
    return bool(clean.startswith("VIP-") and validate_license_key(clean))


def is_pro_activated() -> bool:
    """Check whether a valid Pro or VIP license has been activated on this machine."""
    key = get_active_license_key()
    if not key:
        return False
    return validate_license_key(key.strip())


def activate_license(key: str) -> tuple[bool, str]:
    """Validate and activate a license key, saving status across Registry, files, and settings."""
    clean = key.strip().upper().replace(" ", "")

    if validate_license_key(clean):
        # 1. Windows Registry
        _save_registry_license(clean)
        # 2. Backup license files
        _save_file_license(clean)
        # 3. Settings JSON
        update_setting("license_key", clean)
        update_setting("license_activated", True)

        if clean.startswith("VIP-"):
            return True, "VIP Master Key activated! All features and Media Stream Downloader unlocked."
        return True, "Pro License successfully activated! All features unlocked."
    return False, "Invalid license key. Format must be: PRO-XXXXXXXX-... or VIP-XXXXXXXX-..."


def deactivate_license() -> None:
    """Deactivate current license across all persistence backends."""
    _save_registry_license("")
    _save_file_license("")
    update_setting("license_key", "")
    update_setting("license_activated", False)


def get_license_info() -> dict[str, Any]:
    """Return dictionary with active license status details."""
    key = get_active_license_key()
    is_vip = is_vip_activated()
    is_pro = is_pro_activated()

    if is_vip:
        status_text = "VIP Master Edition (All Features Unlocked)"
    elif is_pro:
        status_text = "Pro Lifetime License (Activated)"
    else:
        status_text = "Free Evaluation Mode"

    return {
        "is_pro": is_pro,
        "is_vip": is_vip,
        "status_text": status_text,
        "key": key if is_pro else "",
        "batch_limit": None if is_pro else FREE_BATCH_LIMIT,
    }
