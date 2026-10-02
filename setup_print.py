"""Stage the verified Windows Ghostscript runtime without a system install."""
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

from model_catalog import _download

VERSION = "10080"
SHA256 = "52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50"


def main():
    if sys.platform != "win32":
        if not shutil.which("gs"):
            raise RuntimeError("Install native Ghostscript (brew install ghostscript on macOS)")
        return
    root = Path(__file__).resolve().parent
    destination = root / "vendor" / "ghostscript"
    if (destination / "bin" / "gswin64c.exe").is_file():
        return
    installer = root / "vendor" / "downloads" / f"gs{VERSION}w64.exe"
    _download(f"https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs{VERSION}/gs{VERSION}w64.exe",
              installer, SHA256, progress=print)
    candidates = [shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe"]
    extractor = next((p for p in candidates if p and Path(p).is_file()), None)
    if not extractor:
        raise RuntimeError("Install 7-Zip to extract the portable print engine, then rerun setup_print.py")
    subprocess.run([extractor, "x", str(installer), f"-o{destination}", "-y"], check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    if not (destination / "bin" / "gswin64c.exe").is_file():
        raise RuntimeError("Ghostscript extraction did not produce its executable")


if __name__ == "__main__":
    main()
