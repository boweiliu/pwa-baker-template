# Helper for install-pwa-full.sh (was an inline heredoc; see helpers/README).
import re
import sys
import urllib.parse

try: h=open(sys.argv[1],encoding='utf-8',errors='replace').read()
except Exception: sys.exit(0)
for t in re.findall(r'<link[^>]+>',h,re.I):
    if re.search(r'rel=["\'][^"\']*apple-touch-icon',t,re.I):
        m=re.search(r'href=["\']([^"\']+)["\']',t,re.I)
        if m: print(urllib.parse.urljoin(sys.argv[2],m.group(1))); break
