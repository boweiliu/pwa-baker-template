#!/bin/bash
# Put an Apple-silicon Chromium snapshot at /Applications/Chromium.app (the same kind of build
# the 557 session installed; Homebrew's chromium cask is blocked by Gatekeeper).
#   REV=<revision> ci/get_chromium.sh    default: the newest snapshot
set -euo pipefail
BASE=https://commondatastorage.googleapis.com/chromium-browser-snapshots/Mac_Arm
REV="${REV:-$(curl -sSf "$BASE/LAST_CHANGE")}"
for try in 0 1 2 3 4 5; do
  if curl -sSfL -o /tmp/chrome-mac.zip "$BASE/$REV/chrome-mac.zip"; then break; fi
  echo "no build at $REV yet; trying an older one"; REV=$((REV - 20))
done
rm -rf /tmp/chromium && unzip -q /tmp/chrome-mac.zip -d /tmp/chromium
rm -rf /Applications/Chromium.app && mv /tmp/chromium/chrome-mac/Chromium.app /Applications/
xattr -dr com.apple.quarantine /Applications/Chromium.app 2>/dev/null || true
echo "Chromium $(plutil -extract CFBundleShortVersionString raw /Applications/Chromium.app/Contents/Info.plist) (snapshot $REV)"
