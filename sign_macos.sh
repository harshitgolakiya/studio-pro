#!/usr/bin/env bash
# ==============================================================================
# sign_macos.sh
# Codesigns, notarizes, and staples Shadow.app and Shadow-Media-Studio-Setup.dmg.
#
# Environment variables:
#   APPLE_DEVELOPER_IDENTITY   e.g. "Developer ID Application: Your Name (TEAMID)"
#   APPLE_ID                   e.g. "developer@example.com"
#   APPLE_APP_SPECIFIC_PASSWORD e.g. "abcd-efgh-ijkl-mnop"
#   APPLE_TEAM_ID              e.g. "ABCDE12345"
# ==============================================================================

set -euo pipefail

APP_PATH="${1:-dist/Shadow.app}"
DMG_PATH="${2:-}"
ENTITLEMENTS="${3:-entitlements.plist}"

if [[ ! -d "$APP_PATH" ]]; then
    echo "Error: Application bundle not found at $APP_PATH" >&2
    exit 1
fi

IDENTITY="${APPLE_DEVELOPER_IDENTITY:-}"

if [[ -z "$IDENTITY" ]]; then
    echo "Warning: APPLE_DEVELOPER_IDENTITY not set. Checking for available Developer ID identities..."
    IDENTITY=$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -n 1 | awk -F '"' '{print $2}' || true)
    if [[ -z "$IDENTITY" ]]; then
        echo "No Developer ID identity found. To ad-hoc sign for local execution:"
        codesign --force --deep -s - "$APP_PATH"
        echo "Ad-hoc signed: $APP_PATH"
        exit 0
    fi
fi

echo "==> Signing internal frameworks and binaries in $APP_PATH"
find "$APP_PATH/Contents/Frameworks" -type f \( -name "*.dylib" -o -name "*.so" \) 2>/dev/null | while read -r lib; do
    codesign --force --timestamp --options runtime --sign "$IDENTITY" "$lib" || true
done

echo "==> Signing main application bundle: $APP_PATH"
if [[ -f "$ENTITLEMENTS" ]]; then
    codesign --force --timestamp --options runtime --deep \
        --entitlements "$ENTITLEMENTS" \
        --sign "$IDENTITY" \
        "$APP_PATH"
else
    codesign --force --timestamp --options runtime --deep \
        --sign "$IDENTITY" \
        "$APP_PATH"
fi

echo "==> Verifying application signature"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
spctl --assess --type exec -v "$APP_PATH" || true

# If DMG is provided, sign and notarize it
if [[ -n "$DMG_PATH" && -f "$DMG_PATH" ]]; then
    echo "==> Signing DMG: $DMG_PATH"
    codesign --force --timestamp --sign "$IDENTITY" "$DMG_PATH"

    if [[ -n "${APPLE_ID:-}" && -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" && -n "${APPLE_TEAM_ID:-}" ]]; then
        echo "==> Submitting DMG for Apple Notarization..."
        xcrun notarytool submit "$DMG_PATH" \
            --apple-id "$APPLE_ID" \
            --password "$APPLE_APP_SPECIFIC_PASSWORD" \
            --team-id "$APPLE_TEAM_ID" \
            --wait

        echo "==> Stapling notarization ticket to DMG..."
        xcrun stapler staple "$DMG_PATH"

        echo "==> Verifying DMG Gatekeeper assessment..."
        spctl --assess --type open --context context:primary-signature -v "$DMG_PATH"
        echo "==> Notarization and stapling complete for: $DMG_PATH"
    else
        echo "Note: APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, or APPLE_TEAM_ID missing; skipping notarization."
    fi
fi

echo "==> macOS signing workflow completed successfully."
