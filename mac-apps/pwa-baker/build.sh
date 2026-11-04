#!/bin/bash
# Build "PWA Baker.app" from source with the Xcode command line tools (no Xcode project).
#   ./build.sh [output dir]     default: ./build
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$ROOT/build}"
APP="$OUT/PWA Baker.app"
ARCH="$(uname -m)"
command -v swiftc >/dev/null || { echo "Needs the Xcode command line tools: xcode-select --install" >&2; exit 1; }

rm -rf "$APP" "$OUT/AppIcon.iconset"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/engine"
echo "==> compiling"
swiftc -O -parse-as-library -swift-version 5 -target "$ARCH-apple-macos13.0" \
  -o "$APP/Contents/MacOS/PWABaker" "$ROOT"/app/Sources/*.swift
cp "$ROOT/app/Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"

echo "==> bundling the engine"
rsync -a --exclude '__pycache__' --exclude '*.pyc' "$ROOT/engine/pwa_baker" "$APP/Contents/Resources/engine/"
chmod +x "$APP/Contents/Resources/engine/pwa_baker/resources/install-pwa-full.sh"

echo "==> drawing the app icon"
"$APP/Contents/MacOS/PWABaker" --render-app-icon "$OUT/AppIcon.iconset"
iconutil -c icns "$OUT/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"

echo "==> signing (ad hoc)"
codesign --force --deep --sign - "$APP"
echo "Built: $APP"
