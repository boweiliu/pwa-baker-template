# Helper for install-pwa-full.sh (was an inline heredoc; see helpers/README).
import hashlib
import sys


def read_varint(b,i):
    v=0;s=0
    while True:
        x=b[i];i+=1;v|=(x&0x7f)<<s
        if not x&0x80:break
        s+=7
    return v,i
def write_varint(n):
    o=bytearray()
    while n>=0x80:o.append((n&0x7f)|0x80);n>>=7
    o.append(n);return bytes(o)
def parse(b):
    f=[];i=0;n=len(b)
    while i<n:
        t,i=read_varint(b,i);fn=t>>3;wt=t&7
        if wt==0: v,i=read_varint(b,i);f.append((fn,0,v))
        elif wt==2:
            ln,i=read_varint(b,i);s=b[i:i+ln];i+=ln;f.append((fn,2,parse_len(s)))
        elif wt==5: f.append((fn,5,b[i:i+4]));i+=4
        elif wt==1: f.append((fn,1,b[i:i+8]));i+=8
        else: raise ValueError
    return f
def parse_len(s):
    try: return ('msg',parse(s),s)
    except: return ('bytes',s)
def ser(f):
    o=bytearray()
    for fn,wt,v in f:
        t=(fn<<3)|wt
        if wt==0: o+=write_varint(t);o+=write_varint(v)
        elif wt==2:
            inner=ser(v[1]) if v[0]=='msg' else v[1]
            o+=write_varint(t);o+=write_varint(len(inner));o+=inner
        elif wt==5: o+=write_varint(t);o+=v
        elif wt==1: o+=write_varint(t);o+=v
    return bytes(o)
def rep(f,old,new):
    for i,(fn,wt,v) in enumerate(f):
        if wt==2:
            if v[0]=='bytes' and v[1]==old.encode(): f[i]=(fn,2,('bytes',new.encode()))
            elif v[0]=='msg': rep(v[1],old,new)
def del_field(f,path):
    if not path: return
    tgt=path[0]
    for i,(fn,wt,v) in enumerate(f):
        if fn==tgt:
            if len(path)==1: del f[i]
            elif wt==2 and v[0]=='msg': del_field(v[1],path[1:])
            return
tmpl=open(sys.argv[1],'rb').read()
start_url=sys.argv[2]; name=sys.argv[3]; icon=sys.argv[4]; out=sys.argv[5]
msg=parse(tmpl)
rep(msg,"https://khmyznikov.com/pwa-install/",start_url)
rep(msg,"https://khmyznikov.com/pwa-install/manifest.json",start_url)
rep(msg,"https://khmyznikov.com/pwa-install/icons/icon@192.png",icon if icon!='placeholder' else start_url+"icon-192.png")
rep(msg,"https://khmyznikov.com/pwa-install/icons/icon@512.png",icon if icon!='placeholder' else start_url+"icon-512.png")
rep(msg,"Progressive Web Application",name)
rep(msg,"Installation component",name)
rep(msg,"pwa-install/","")   # no manifest -> relative_manifest_id="" -> manifest_id = origin
import urllib.parse as _up

_pu=_up.urlparse(start_url)
mid=f"{_pu.scheme}://{_pu.hostname}{(':'+str(_pu.port)) if _pu.port else ''}/"   # GURL origin.spec()
open(out,'wb').write(ser(msg))
h=hashlib.sha256(hashlib.sha256(mid.encode()).digest()).digest()[:16].hex()
print(''.join(chr(ord('a')+int(c,16)) for c in h))
