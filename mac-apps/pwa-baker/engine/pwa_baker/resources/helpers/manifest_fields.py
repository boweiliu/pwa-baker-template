# Helper for install-pwa-full.sh (was an inline heredoc; see helpers/README).
import json
import sys
import urllib.parse

m=json.load(open(sys.argv[1],encoding='utf-8',errors='replace')); base=sys.argv[2]; mh=sys.argv[3]
name=m.get('name') or m.get('short_name') or 'Web App'
start=urllib.parse.urljoin(base, m.get('start_url','.') if isinstance(m.get('start_url'),str) else '.')
cands=[]
for ic in m.get('icons',[]):
    try: w=int(str(ic.get('sizes','0x0')).split('x')[0])
    except: w=0
    if (ic.get('type','') or '').lower() in ('image/png','') and ('any' in ic.get('purpose','any') or 'maskable' in ic.get('purpose','any')):
        cands.append((w,urllib.parse.urljoin(mh,ic.get('src',''))))
cands.sort(reverse=True)
print(name.replace(' ','\t'), start.replace(' ','%20'), cands[0][1] if cands else '')
