#!/bin/bash
# Build PWA Baker, put it in ~/Applications, and open it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/Applications"

"$ROOT/build.sh" "$ROOT/build"

if pgrep -x PWABaker >/dev/null; then
  echo "==> quitting the running PWA Baker"
  osascript -e 'quit app "PWA Baker"' >/dev/null 2>&1 || pkill -x PWABaker || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do pgrep -x PWABaker >/dev/null || break; sleep 0.5; done
fi

mkdir -p "$DEST"
rm -rf "$DEST/PWA Baker.app"
cp -R "$ROOT/build/PWA Baker.app" "$DEST/"
echo "==> installed $DEST/PWA Baker.app"
open "$DEST/PWA Baker.app"
