#!/usr/bin/env bash
# calib/regen.sh — regenerate the WebApp-proto calibration template from a real
# Chromium PWA install. Run AFTER installing any one PWA via the target Chromium
# (e.g. visit https://khmyznikov.com/pwa-install/ and click Install, then quit
# Chromium). Then re-run install-pwa-full.sh.
#
# Usage: ./calib/regen.sh [app_id]
#   omit app_id to auto-pick the first installed app in the Sync DB
set -euo pipefail
UD="$HOME/Library/Application Support/Chromium"
DB="$UD/-/Sync Data/LevelDB"
OUT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODEDIR="$HOME/.cache/install-pwa-full-node"
command -v node >/dev/null || { echo "need node+npm" >&2; exit 1; }
if [ ! -d "$NODEDIR/node_modules/classic-level" ]; then
  echo "bootstrapping classic-level (one-time)..."; mkdir -p "$NODEDIR"
  (cd "$NODEDIR" && npm init -y >/dev/null 2>&1 && npm install classic-level >/dev/null 2>&1)
fi
[ -d "$DB" ] || { echo "no Sync DB at $DB — install a PWA via Chromium first" >&2; exit 1; }
NODE_PATH="$NODEDIR/node_modules" node - "$DB" "${1:-}" "$OUT" <<'JS'
const {ClassicLevel}=require('classic-level'); const fs=require('fs');
const [,,dbp,idArg,out]=process.argv;
const db=new ClassicLevel(dbp,{readOnly:true,keyEncoding:'utf8',valueEncoding:'buffer'});
const P='web_apps-dt-';
const CALIB_MARK='khmyznikov.com/pwa-install';  // the installer substitutes this app's strings
(async()=>{
  let key;
  if(idArg) key=P+idArg;
  else {
    // prefer the khmyznikov calibration app (its strings are the installer's substitution targets)
    let fallback=null;
 for await (const [k,v] of db.iterator({valueEncoding:'buffer'})) {
      if(!k.startsWith(P)||k===P+'DATABASE_METADATA') continue;
      if(!fallback) fallback=k;
      if(v.includes(Buffer.from(CALIB_MARK))) { key=k; break; }
    }
    if(!key) key=fallback;
  }
  if(!key) throw new Error('no installed PWA found in the Sync DB; install the khmyznikov demo (https://khmyznikov.com/pwa-install/) via Chromium first, then quit Chromium');
  const v=await db.get(key,{valueEncoding:'buffer'});
  if(!idArg && !v.includes(Buffer.from(CALIB_MARK)))
    console.error('WARNING: this record is not the khmyznikov demo; the installer substitutes khmyznikov strings and may not match. Install the demo and re-run.');
  fs.writeFileSync(out+'/webapp_record_template.bin', v);
  const md=await db.get(P+'DATABASE_METADATA',{valueEncoding:'buffer'});
  fs.writeFileSync(out+'/database_metadata.bin', md);
  console.log('wrote webapp_record_template.bin from key', key, 'len', v.length);
  console.log('wrote database_metadata.bin len', md.length);
  await db.close();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
JS
# snapshot the Local State app_shims entry (reference only; not required at runtime)
python3 -c "import json,os;p=os.path.expanduser('~/Library/Application Support/Chromium/Local State');ls=json.load(open(p));open('$OUT/local_state_app_shims.json','w').write(json.dumps(ls.get('app_shims',{}),indent=2));print('wrote local_state_app_shims.json')" 2>/dev/null || true
echo
echo "Calibration regenerated. Re-run: install-pwa-full.sh <url>"
