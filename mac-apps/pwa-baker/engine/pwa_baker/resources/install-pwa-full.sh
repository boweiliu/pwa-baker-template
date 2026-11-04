#!/usr/bin/env bash
#
# install-pwa-full.sh — create a FULL-FIDELITY macOS PWA (.app) for a URL with
# NO Chromium process running. The result is indistinguishable from one Chromium
# installs itself: standalone window, own name/title bar, 3-dot menu → App info
# / Uninstall, and an entry in chrome://apps.
#
# See full-fidelity-path.md for the model, pitfalls, and recipe.
#
# Usage:
#   install-pwa-full.sh <url> [--name NAME] [--icon PATH|URL] [--browser-app PATH] [--template PATH]
#
# Requires: /Applications/Chromium.app (or --browser-app), a one-time calibration
# template (default ./calib/webapp_record_template.bin), and: curl, python3, sips,
# iconutil, codesign, node+npm (auto-bootstraps classic-level for the LevelDB write).
#
# Letter icons (for sites with no usable icon) come from $PWA_BAKER_ICON_RENDERER
# when set (the PWA Baker app sets it to its own binary, which draws them with
# AppKit); otherwise from a python with Pillow, bootstrapped into a venv on demand.
#
# Based on an earlier stand-alone version of this installer, adapted for PWA Baker.

set -euo pipefail

URL=""; NAME_OVERRIDE=""; ICON_OVERRIDE=""
BROWSER_APP="/Applications/Chromium.app"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPERS="$SCRIPT_DIR/helpers"
TEMPLATE="$SCRIPT_DIR/calib/webapp_record_template.bin"
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME_OVERRIDE="$2"; shift 2;;
    --icon) ICON_OVERRIDE="$2"; shift 2;;
    --browser-app) BROWSER_APP="$2"; shift 2;;
    --template) TEMPLATE="$2"; shift 2;;
    -*) echo "unknown: $1" >&2; exit 2;;
    *) URL="$1"; shift;;
  esac
done
[ -n "$URL" ] || { echo "usage: $0 <url> [--name NAME] [--icon PATH|URL]" >&2; exit 2; }
[ -d "$BROWSER_APP" ] || { echo "browser not found: $BROWSER_APP" >&2; exit 1; }
[ -f "$TEMPLATE" ] || { echo "template not found: $TEMPLATE (run one-time calibration; see full-fidelity-path.md)" >&2; exit 1; }
for t in curl python3 sips iconutil codesign node npm; do command -v $t >/dev/null || { echo "need $t" >&2; exit 1; }; done

# Resolve a python with Pillow for the letter-icon step (the PIL branch draws a
# letter on a colored rounded square; without PIL you get a flat color only).
# Prefer a cached venv, then any python that imports PIL, else bootstrap one.
# Only called when no icon renderer is available and a letter icon is needed.
resolve_icon_py() {
  local VENV="$HOME/.cache/pwa-baker-venv" c BPY
  for c in "$VENV/bin/python" python3 "$(command -v python3)" /opt/homebrew/bin/python3 \
           /usr/bin/python3 "$HOME/.pyenv/shims/python3"; do
    [ -n "$c" ] && command -v "$c" >/dev/null 2>&1 && "$c" -c "import PIL" 2>/dev/null && { echo "$c"; return; }
  done
  BPY="$(command -v python3 || echo /usr/bin/python3)"
  if "$BPY" -m venv "$VENV" >/dev/null 2>&1 && "$VENV/bin/pip" install -q Pillow >/dev/null 2>&1; then
    echo "$VENV/bin/python"; return
  fi
  echo python3   # fallback path: flat color, no letter
}

# file -b: without it the file's own name ("icon.png") would match.
is_image() { [ -s "$1" ] && file -b "$1" 2>/dev/null | grep -qiE 'image|icon resource'; }

make_letter_icon() {
  rm -f "$WORK/icon.png"
  if [ -n "${PWA_BAKER_ICON_RENDERER:-}" ] && "$PWA_BAKER_ICON_RENDERER" --render-icon "$WORK/icon.png" "$NAME" >/dev/null 2>&1 && is_image "$WORK/icon.png"; then
    return 0
  fi
  "$(resolve_icon_py)" "$HELPERS/letter_icon.py" "$WORK/icon.png" "$NAME"
}

UD="${PWA_BAKER_CHROMIUM_USER_DATA:-$HOME/Library/Application Support/Chromium}"   # real profile (NOT /tmp)
APPS_DIR="${PWA_BAKER_APPS_DIR:-$HOME/Applications/Chromium Apps.localized}"
BROWSER_BUNDLE_ID=$(plutil -extract CFBundleIdentifier raw "$BROWSER_APP/Contents/Info.plist")
BROWSER_VERSION=$(plutil -extract CFBundleVersion raw "$BROWSER_APP/Contents/Info.plist")
BROWSER_BIN="$BROWSER_APP/Contents/MacOS/$(plutil -extract CFBundleExecutable raw "$BROWSER_APP/Contents/Info.plist")"
LOADER=$(find "$BROWSER_APP/Contents/Frameworks" -name app_mode_loader -type f 2>/dev/null | head -1)
[ -f "$LOADER" ] || { echo "app_mode_loader not found in $BROWSER_APP" >&2; exit 1; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# --- 1. fetch manifest / fallback name + icon -------------------------------
PAGE="$WORK/page.html"
HTTP=$(curl -sSL -A "Mozilla/5.0" -w '%{http_code}' -o "$PAGE" "$URL" 2>/dev/null || true)
NAME=""; START_URL="$URL"; MANIFEST_OK=0; ICON_URL=""
if grep -qiE '<link[^>]+rel=["'"'"']manifest["'"'"'][^>]*>' "$PAGE" 2>/dev/null; then
  MHREF=$(python3 "$HELPERS/manifest_href.py" "$PAGE" "$URL")
  if [ -n "${MHREF:-}" ] && curl -sSL -A "Mozilla/5.0" -o "$WORK/m.json" "$MHREF" 2>/dev/null \
     && python3 -c "import json,sys;json.load(open(sys.argv[1],encoding='utf-8',errors='replace'))" "$WORK/m.json" 2>/dev/null; then
    MANIFEST_OK=1
    read -r NAME START_URL ICON_URL < <(python3 "$HELPERS/manifest_fields.py" "$WORK/m.json" "$URL" "$MHREF")
    NAME="${NAME//$'\t'/ }"
  fi
fi
[ -z "$NAME" ] && [ -z "$NAME_OVERRIDE" ] && NAME=$(python3 -c "import sys,urllib.parse;h=urllib.parse.urlparse(sys.argv[1]).hostname or 'Web App';print(h.split('.')[0].split('-')[0].replace('_',' ').title())" "$URL")
[ -n "$NAME_OVERRIDE" ] && NAME="$NAME_OVERRIDE"
[ -z "$NAME" ] && NAME="Web App"
echo "name: $NAME"
echo "start_url: $START_URL"
echo "manifest: $([ $MANIFEST_OK = 1 ] && echo yes || echo "no (HTTP $HTTP)")"

# --- resolve icon source to $WORK/icon.png (>=512 ideally) -----------------
# Order: --icon, the manifest's largest icon, the page's apple-touch-icon, the
# site's /apple-touch-icon.png and /icon.png, /favicon.ico, then a letter icon.
ICON_SOURCE=""
if [ -n "$ICON_OVERRIDE" ]; then
  if [ -f "$ICON_OVERRIDE" ]; then cp "$ICON_OVERRIDE" "$WORK/icon.png"; else curl -sSL -o "$WORK/icon.png" "$ICON_OVERRIDE" || true; fi
  is_image "$WORK/icon.png" && ICON_SOURCE="given"
fi
if [ -z "$ICON_SOURCE" ] && [ $MANIFEST_OK = 1 ] && [ -n "$ICON_URL" ]; then
  curl -sSL -o "$WORK/icon.png" "$ICON_URL" || true
  is_image "$WORK/icon.png" && ICON_SOURCE="manifest"
fi
if [ -z "$ICON_SOURCE" ]; then
  ROOT=$(python3 -c "import sys,urllib.parse;u=urllib.parse.urlparse(sys.argv[1]);print(u.scheme+'://'+u.netloc)" "$URL")
  TOUCH=$(python3 "$HELPERS/touch_icon.py" "$PAGE" "$URL" 2>/dev/null || true)
  for c in ${TOUCH:+"$TOUCH"} "$ROOT/apple-touch-icon.png" "$ROOT/icon.png" "$ROOT/favicon.ico"; do
    rm -f "$WORK/icon.png"
    curl -sSL -o "$WORK/icon.png" "$c" 2>/dev/null || true
    if is_image "$WORK/icon.png"; then ICON_SOURCE="site:$c"; break; fi
  done
fi
if [ -z "$ICON_SOURCE" ]; then make_letter_icon; ICON_SOURCE="letter"; fi
# A download sips cannot read (an SVG, a broken file) falls back to a letter icon too, rather
# than leaving the icon steps below with nothing to resize.
rm -f "$WORK/icon-checked.png"
if sips -s format png "$WORK/icon.png" --out "$WORK/icon-checked.png" >/dev/null 2>&1 && [ -s "$WORK/icon-checked.png" ]; then
  mv "$WORK/icon-checked.png" "$WORK/icon.png"
elif [ "$ICON_SOURCE" != "letter" ]; then
  ICON_SOURCE="letter (the icon from $ICON_SOURCE was unreadable)"; make_letter_icon
fi
echo "icon_source: $ICON_SOURCE"
file "$WORK/icon.png"

# --- 2+3. compute app id + synthesize WebApp proto --------------------------
PROTO="$WORK/app.bin"
APP_ID=$(python3 "$HELPERS/synth_proto.py" "$TEMPLATE" "$START_URL" "$NAME" "${ICON_URL:-placeholder}" "$PROTO")
echo "app_id: $APP_ID"
[ -n "$APP_ID" ] || { echo "proto synthesis failed" >&2; exit 1; }

# --- 4. write WebAppDB (BUFFER encoding) into real profile ------------------
NODEDIR="$HOME/.cache/install-pwa-full-node"
if [ ! -d "$NODEDIR/node_modules/classic-level" ]; then
  echo "bootstrapping classic-level (one-time)..."
  mkdir -p "$NODEDIR"; (cd "$NODEDIR" && npm init -y >/dev/null 2>&1 && npm install classic-level >/dev/null 2>&1)
fi
NODE_PATH="$NODEDIR/node_modules" node - "$UD/-" "$APP_ID" "$PROTO" <<'JS'
const {ClassicLevel}=require('classic-level'); const fs=require('fs');
const [,,prof,id,proto]=process.argv;
const db=new ClassicLevel(prof+'/Sync Data/LevelDB',{keyEncoding:'utf8',valueEncoding:'buffer'});
(async()=>{
  if (db.status !== 'open') await db.open();
  await db.put('web_apps-dt-'+id, fs.readFileSync(proto));
  await db.put('web_apps-dt-DATABASE_METADATA', Buffer.from([0x08,0x07]));
  await db.put('_mts_schema_descriptor', Buffer.from([0x08,0x01]));
  await db.close();
  console.log('DB written');
})().catch(e=>{console.error('DB ERR',e.message);process.exit(1);});
JS

# --- 5. write icons to Manifest Resources ---------------------------------
MR="$UD/-/Web Applications/Manifest Resources/$APP_ID"
rm -rf "$MR"; mkdir -p "$MR/Icons" "$MR/Icons Maskable" "$MR/Icons Monochrome" "$MR/Trusted Icons/Icons" "$MR/Trusted Icons/Icons Maskable" "$MR/Trusted Icons/Icons Monochrome"
for s in 32 48 64 96 128 192 256 512; do sips -s format png -z $s $s "$WORK/icon.png" --out "$MR/Icons/$s.png" >/dev/null 2>&1; done
for s in 32 48 64 96 128 256 512; do cp "$MR/Icons/$s.png" "$MR/Trusted Icons/Icons/$s.png"; done
echo "icons: $(ls "$MR/Icons" | tr '\n' ' ')"

# --- 6. add app_shims to Local State ---------------------------------------
mkdir -p "$UD"
python3 - "$UD/Local State" "$APP_ID" <<'PY'
import json,sys
p,id=sys.argv[1],sys.argv[2]
try:
    ls=json.load(open(p))
except FileNotFoundError:
    ls={}
ls.setdefault('app_shims',{})[id]={'installed_profiles':['-'],'last_active_profiles':['-'],'notification_permission':1}
json.dump(ls,open(p,'w'))
print('app_shims added')
PY

# --- 7. build the shim (name must match proto name) ------------------------
SAFE="${NAME//\//_}"
SHIM="$APPS_DIR/$SAFE.app"
rm -rf "$SHIM"; mkdir -p "$SHIM/Contents/MacOS" "$SHIM/Contents/Resources"
cp "$LOADER" "$SHIM/Contents/MacOS/app_mode_loader"
ICONSET="$WORK/icon.iconset"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do sips -s format png -z $s $s "$WORK/icon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1; sips -s format png -z $((s*2)) $((s*2)) "$WORK/icon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1; done
iconutil -c icns "$ICONSET" -o "$SHIM/Contents/Resources/app.icns" 2>/dev/null
# rebuild-in-place leaves a stale icon in the IconServices cache; drop the
# bundle's cached entry so the Dock/Finder re-read app.icns on next launch.
LSR=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister
$LSR -f "$SHIM" >/dev/null 2>&1 || true
find ~/Library/Caches/com.apple.iconservices.store -name "*" -delete 2>/dev/null || true
printf 'APPL????' > "$SHIM/Contents/PkgInfo"
BID="$BROWSER_BUNDLE_ID.app.$APP_ID"
cat > "$SHIM/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>app_mode_loader</string>
<key>CFBundleIconFile</key><string>app</string>
<key>CFBundleIdentifier</key><string>$BID</string>
<key>CFBundleName</key><string>$SAFE</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>${BROWSER_VERSION%.*}</string>
<key>CrAppModeShortcutID</key><string>$APP_ID</string>
<key>CrAppModeShortcutName</key><string>$SAFE</string>
<key>CrAppModeShortcutURL</key><string>$START_URL</string>
<key>CrAppModeUserDataDir</key><string>$UD/-/Web Applications/_crx_$APP_ID</string>
<key>CrAppModeProfileDir</key><string>-</string>
<key>CrBundleIdentifier</key><string>$BROWSER_BUNDLE_ID</string>
<key>CrBundleVersion</key><string>$BROWSER_VERSION</string>
<key>CrAppModeIsAdhocSigned</key><true/>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
plutil -convert binary1 "$SHIM/Contents/Info.plist"

# --- 8. sign in place with disable-library-validation entitlement ----------
cat > "$WORK/entitlements.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>
<key>com.apple.security.cs.disable-library-validation</key><true/>
</dict></plist>
PLIST
codesign --force --sign - --identifier "$BID" --options runtime --entitlements "$WORK/entitlements.plist" "$SHIM" 2>&1 | head -1
xattr -dr com.apple.quarantine "$SHIM" 2>/dev/null || true
lsregister="/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister"
[ -x "$lsregister" ] && "$lsregister" -f "$SHIM" 2>/dev/null || true

echo
echo "Created: $SHIM"
echo "App id:  $APP_ID"
echo "Bundle:  $BID"
echo
echo "Launch:  open \"$SHIM\""
