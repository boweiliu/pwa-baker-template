# Helper for install-pwa-full.sh: a letter icon with Pillow (used when no icon renderer is given).
import colorsys
import hashlib
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    # Pillow missing: fall back to a flat solid-color PNG via a tiny
    # hand-written PNG writer (no third-party deps).
    out,name=sys.argv[1],sys.argv[2]; S=512
    h=int(hashlib.sha256(name.encode()).hexdigest(),16)
    r,g,b=colorsys.hsv_to_rgb(((h>>8)&0xffff)/65535.0,0.62,0.86)
    rgb=(int(r*255),int(g*255),int(b*255))
    import struct
    import zlib
    rowlen=1+3*S
    raw=bytearray()
    for _ in range(S):
        raw.append(0)                 # filter byte (None)
        raw.extend(rgb*S)             # S pixels of solid color per row
    def chunk(t,d):
        return struct.pack(">I",len(d))+t+d+struct.pack(">I",zlib.crc32(t+d)&0xffffffff)
    sig=b"\x89PNG\r\n\x1a\n"
    ihdr=struct.pack(">IIBBBBB",S,S,8,2,0,0,0)
    idat=zlib.compress(bytes(raw),9)
    open(out,"wb").write(sig+chunk(b"IHDR",ihdr)+chunk(b"IDAT",idat)+chunk(b"IEND",b""))
    sys.exit(0)
out,name=sys.argv[1],sys.argv[2]; S=512
img=Image.new("RGBA",(S,S),(0,0,0,0)); d=ImageDraw.Draw(img)
h=int(hashlib.sha256(name.encode()).hexdigest(),16)
r,g,b=colorsys.hsv_to_rgb(((h>>8)&0xffff)/65535.0,0.62,0.86)
d.rounded_rectangle([0,0,S,S],radius=96,fill=(int(r*255),int(g*255),int(b*255),255))
L=next((c for c in name if c.isalpha()),name[0] if name else 'A')
f=None
for p in ("/System/Library/Fonts/Helvetica.ttc","/System/Library/Fonts/SFNS.ttf","/Library/Fonts/Arial.ttf"):
    try: f=ImageFont.truetype(p,300); break
    except: pass
if not f: f=ImageFont.load_default()
b=d.textbbox((0,0),L,font=f); lw,lh=b[2]-b[0],b[3]-b[1]
d.text(((S-lw)//2-b[0],(S-lh)//2-b[1]-10),L,font=f,fill=(255,255,255,255))
img.save(out,"PNG")
