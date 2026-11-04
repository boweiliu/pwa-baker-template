# Helper for install-pwa-full.sh (was an inline heredoc; see helpers/README).
import re
import sys
import urllib.parse

h,b=open(sys.argv[1],encoding='utf-8',errors='replace').read(),sys.argv[2]
m=re.search(r'<link[^>]+rel=["\']manifest["\'][^>]*>',h,re.I); 
if not m: sys.exit(1)
t=m.group(0); h2=re.search(r'href=["\']([^"\']+)["\']',t,re.I)
print(urllib.parse.urljoin(b,h2.group(1)) if h2 else "")
