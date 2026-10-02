#!/bin/bash
set -euo pipefail
# Pinned hashes are from Homebrew's LibreOffice 26.8.0 cask.
case "$(uname -m)" in
  arm64) folder=aarch64; arch=aarch64; expected=8858d8058da4f862f47559486814e65efc27294da67c5e4bb56b006b1ee59f89 ;;
  x86_64) folder=x86_64; arch=x86-64; expected=2dcbce4894e01bc1ecd594658e2cbda70ff7bfcd0b310f35d38887797172d09e ;;
  *) echo 'Unsupported macOS architecture' >&2; exit 1 ;;
esac
filename="LibreOffice_26.8.0_MacOS_${arch}.dmg"
work=$(mktemp -d "${TMPDIR:-/tmp}/shadow-office.XXXXXX")
mount="$work/mounted"
mkdir -p "$mount" vendor/libreoffice
trap 'hdiutil detach "$mount" -quiet >/dev/null 2>&1 || true' EXIT
downloaded=false
for base in https://mirrors.ibiblio.org/libreoffice https://download.documentfoundation.org/libreoffice; do
  if curl --fail --location --connect-timeout 20 --max-time 600 --retry 2 \
      "$base/stable/26.8.0/mac/$folder/$filename" -o "$work/office.dmg"; then
    actual=$(shasum -a 256 "$work/office.dmg" | awk '{print $1}')
    if [[ "$actual" == "$expected" ]]; then downloaded=true; break; fi
    echo "LibreOffice checksum mismatch from $base" >&2
  fi
done
if [[ "$downloaded" != true ]]; then echo 'No verified LibreOffice download available' >&2; exit 1; fi
hdiutil attach "$work/office.dmg" -nobrowse -readonly -mountpoint "$mount"
ditto "$mount/LibreOffice.app" vendor/libreoffice/LibreOffice.app
codesign --verify --deep --strict vendor/libreoffice/LibreOffice.app
echo 'Verified LibreOffice staged for source and packaged conversions.'
